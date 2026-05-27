import json
import numpy as np
from numpy.linalg import norm
from rapidfuzz import process, distance

class HierarchicalDomainRouter:
    def __init__(self, json_path: str, embedding_model):
        self.embedding_model = embedding_model
        
        with open(json_path, 'r', encoding='utf-8') as f:
            self.ontology = json.load(f)
            
        self.tier_vectors = {}
        self.sub_domain_vectors = {}
        self.fuzzy_vocab = {}
        self.master_fuzzy_vocab = {}
        
        # The exact list of structural domains that must ALWAYS be allowed to compete
        self.universal_keys = {"identifier", "survey_metadata", "geography", "demographic", "household", "uncorrelated_metadata"}
        self.universal_vectors = {}
        
        self._precompute_embeddings()
        self._build_fuzzy_dictionary()

    def _precompute_embeddings(self):
        """Caches vectors for tier-level, sub-domain-level, and universal routing."""
        dataset_types = self.ontology.get("dataset_types", {})
        
        for tier_name, tier_data in dataset_types.items():
            tier_label = tier_data.get("label", tier_name)
            tier_domains = tier_data.get("domains", [])
            tier_text = f"{tier_label} {' '.join(tier_domains)}".strip()
            self.tier_vectors[tier_name] = self._embed_text(tier_text)

            self.sub_domain_vectors[tier_name] = {}
            for sub_name, keywords in tier_data.get("subdomains", {}).items():
                target_text = f"{sub_name} {' '.join(keywords)}".strip()
                vec = self._embed_text(target_text)
                self.sub_domain_vectors[tier_name][sub_name] = vec
                
                # Safely cache universal vectors so we never hardcode a dependency on 'census'
                if sub_name in self.universal_keys and sub_name not in self.universal_vectors:
                    self.universal_vectors[sub_name] = vec

    def _embed_text(self, text: str):
        if hasattr(self.embedding_model, "embed_text"):
            return self.embedding_model.embed_text(text)
        if hasattr(self.embedding_model, "encode"):
            return self.embedding_model.encode(text)
        raise AttributeError("Embedding model must provide embed_text() or encode().")

    def _build_fuzzy_dictionary(self):
        """Builds a flat lookup dictionary for fast lexical routing."""
        dataset_types = self.ontology.get("dataset_types", {})
        
        for tier_name, tier_data in dataset_types.items():
            self.fuzzy_vocab[tier_name] = {}
            for sub_name, keywords in tier_data.get("subdomains", {}).items():
                self.fuzzy_vocab[tier_name][sub_name.lower()] = sub_name
                self.master_fuzzy_vocab[sub_name.lower()] = sub_name
                for kw in keywords:
                    self.fuzzy_vocab[tier_name][kw.lower()] = sub_name
                    self.master_fuzzy_vocab[kw.lower()] = sub_name

    def cosine_similarity(self, vec_a, vec_b):
        return float(np.dot(vec_a, vec_b) / (norm(vec_a) * norm(vec_b)))

    @staticmethod
    def _humanize_label(text: str) -> str:
        return " ".join(w.capitalize() for w in text.replace("_", " ").replace("-", " ").split())

    def predict_domain(self, column_name: str, column_vector: np.ndarray, archetype: str | None = None) -> dict:
        """Executes tier routing followed by contextually pruned sub-domain routing."""
        
        col_lower = column_name.lower()
        column_vector = np.asarray(column_vector)
        
        # ==========================================
        # 1A. DETERMINISTIC STRUCTURAL BYPASS
        # ==========================================
        if col_lower.endswith(("_id", "_code", "uid", "uuid", "pk", "fk")):
            return {
                "predicted_domain": "identifier",
                "macro_tier": archetype or self._best_tier_for_domain("identifier") or archetype or "unknown",
                "confidence": 1.0,
                "pass_1_score": 1.0,
                "pass_2_score": 1.0,
                "is_locked": True,
                "match_method": "schema_suffix_lock",
                "matched_keyword": col_lower,
                "display_label": self._humanize_label(column_name),
            }

        # ==========================================
        # 1B. RAPIDFUZZ LEXICAL FAST-TRACK
        # ==========================================
        tier_name = archetype or self._best_tier(column_vector)
        
        # Safely fetch archetype vocab, fallback to master. NO hardcoded "census" strings.
        target_vocab = self.fuzzy_vocab.get(tier_name)
        if not target_vocab:
            target_vocab = self.master_fuzzy_vocab

        if target_vocab:
            keywords = list(target_vocab.keys())
            best_match = process.extractOne(
                col_lower,
                keywords,
                scorer=distance.JaroWinkler.normalized_similarity
            )

            if best_match and best_match[1] >= 0.85:
                matched_keyword = best_match[0]
                winning_domain = target_vocab[matched_keyword]
                macro_tier = tier_name or self._best_tier_for_domain(winning_domain) or "unknown"
                return {
                    "predicted_domain": winning_domain,
                    "macro_tier": macro_tier,
                    "confidence": 1.0,
                    "pass_1_score": 1.0,
                    "pass_2_score": 1.0,
                    "is_locked": True,
                    "match_method": "rapidfuzz_ontology",
                    "matched_keyword": matched_keyword,
                    "display_label": self._humanize_label(matched_keyword),
                }

        # ==========================================
        # 2. TIER ROUTING
        # ==========================================
        tier_scores = {name: self.cosine_similarity(column_vector, vec) for name, vec in self.tier_vectors.items()}
        if not tier_scores:
            return {
                "predicted_domain": "unknown",
                "macro_tier": archetype or "unknown",
                "confidence": 0.0,
                "pass_1_score": 0.0,
                "pass_2_score": 0.0,
                "is_locked": False,
                "match_method": "embedding_similarity",
                "matched_keyword": None,
                "display_label": self._humanize_label(column_name),
            }

        if archetype and archetype in self.tier_vectors:
            winning_tier = archetype
        else:
            winning_tier = max(tier_scores, key=tier_scores.get)

        macro_confidence = tier_scores.get(winning_tier, 0.0)

        # ==========================================
        # 3. MICRO ROUTING (The Contextual Sieve)
        # ==========================================
        active_tier = archetype if archetype and archetype in self.sub_domain_vectors else winning_tier
        
        # Build the Sieve: Specific Domains + Universal Domains
        target_dataset = self.sub_domain_vectors.get(active_tier, {}).copy()
        
        for uk, uvec in self.universal_vectors.items():
            if uk not in target_dataset:
                target_dataset[uk] = uvec

        if not target_dataset:
            return {
                "predicted_domain": active_tier,
                "macro_tier": active_tier,
                "confidence": float(macro_confidence),
                "pass_1_score": float(macro_confidence),
                "pass_2_score": float(macro_confidence),
                "is_locked": False,
                "match_method": "embedding_similarity",
                "matched_keyword": active_tier,
                "display_label": self._humanize_label(active_tier),
            }

        # Calculate scores ONLY against this pruned dictionary
        sub_scores = {sub_name: self.cosine_similarity(column_vector, sub_vec) 
                      for sub_name, sub_vec in target_dataset.items()}
        
        winning_domain = max(sub_scores, key=sub_scores.get)
        micro_confidence = sub_scores[winning_domain]
        
        # If the archetype was forced, trust the micro_confidence completely.
        if archetype:
            confidence = micro_confidence 
        else:
            confidence = (macro_confidence * 0.3) + (micro_confidence * 0.7)

        return {
            "predicted_domain": winning_domain,
            "macro_tier": active_tier,
            "confidence": float(confidence),
            "pass_1_score": float(macro_confidence),
            "pass_2_score": float(micro_confidence),
            "is_locked": False,
            "match_method": "embedding_similarity",
            "matched_keyword": winning_domain,
            "display_label": self._humanize_label(winning_domain),
        }

    def _best_tier(self, column_vector: np.ndarray) -> str:
        tier_scores = {name: self.cosine_similarity(column_vector, vec) for name, vec in self.tier_vectors.items()}
        return max(tier_scores, key=tier_scores.get) if tier_scores else "unknown"

    def _best_tier_for_domain(self, domain_name: str) -> str | None:
        for tier_name, subdomains in self.sub_domain_vectors.items():
            if domain_name in subdomains:
                return tier_name
        return None