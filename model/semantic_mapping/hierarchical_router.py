import json
import numpy as np
from numpy.linalg import norm
from rapidfuzz import fuzz, process

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
                vector_list = [self._embed_text(sub_name)]
                for kw in keywords:
                    vector_list.append(self._embed_text(kw))
                self.sub_domain_vectors[tier_name][sub_name] = vector_list

                # Safely cache universal vectors so we never hardcode a dependency on 'census'
                if sub_name in self.universal_keys and sub_name not in self.universal_vectors:
                    self.universal_vectors[sub_name] = vector_list

    def _embed_text(self, text: str):
        if hasattr(self.embedding_model, "embed_text"):
            return self.embedding_model.embed_text(text)
        if hasattr(self.embedding_model, "encode"):
            return self.embedding_model.encode(text)
        raise AttributeError("Embedding model must provide embed_text() or encode().")

    def _append_master_fuzzy(self, keyword: str, sub_name: str) -> None:
        key = keyword.lower()
        bucket = self.master_fuzzy_vocab.setdefault(key, [])
        if sub_name not in bucket:
            bucket.append(sub_name)

    def _build_fuzzy_dictionary(self):
        """Builds a flat lookup dictionary for fast lexical routing."""
        dataset_types = self.ontology.get("dataset_types", {})
        
        for tier_name, tier_data in dataset_types.items():
            self.fuzzy_vocab[tier_name] = {}
            for sub_name, keywords in tier_data.get("subdomains", {}).items():
                self.fuzzy_vocab[tier_name][sub_name.lower()] = sub_name
                self._append_master_fuzzy(sub_name, sub_name)
                for kw in keywords:
                    self.fuzzy_vocab[tier_name][kw.lower()] = sub_name
                    self._append_master_fuzzy(kw, sub_name)

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
        # 1B. RAPIDFUZZ LEXICAL FAST-TRACK (global master vocab)
        # ==========================================
        if self.master_fuzzy_vocab:
            keywords = list(self.master_fuzzy_vocab.keys())
            best_match = process.extractOne(
                col_lower,
                keywords,
                scorer=fuzz.token_set_ratio,
            )

            if best_match and best_match[1] >= 85:
                matched_keyword = best_match[0]
                tied_domains = self.master_fuzzy_vocab.get(matched_keyword) or []
                winning_domain = tied_domains[0] if tied_domains else "unknown"
                if archetype and archetype in self.sub_domain_vectors:
                    archetype_domains = set(self.sub_domain_vectors[archetype].keys())
                    for candidate in tied_domains:
                        if candidate in archetype_domains:
                            winning_domain = candidate
                            break
                macro_tier = (
                    self._best_tier_for_domain(winning_domain)
                    or archetype
                    or "unknown"
                )
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

        winning_tier = max(tier_scores, key=tier_scores.get)
        macro_confidence = tier_scores.get(winning_tier, 0.0)

        # ==========================================
        # 3. GLOBAL VECTOR SIEVE + SOFT ARCHETYPE WEIGHTING
        # ==========================================
        global_vectors: dict[str, list] = {}
        for _tier_name, subs in self.sub_domain_vectors.items():
            for sub_name, vector_list in subs.items():
                if sub_name not in global_vectors:
                    global_vectors[sub_name] = vector_list
        for uk, vector_list in self.universal_vectors.items():
            if uk not in global_vectors:
                global_vectors[uk] = vector_list

        if not global_vectors:
            fallback_tier = archetype if archetype and archetype in self.tier_vectors else winning_tier
            return {
                "predicted_domain": fallback_tier,
                "macro_tier": fallback_tier,
                "confidence": float(macro_confidence),
                "pass_1_score": float(macro_confidence),
                "pass_2_score": float(macro_confidence),
                "is_locked": False,
                "match_method": "embedding_similarity",
                "matched_keyword": fallback_tier,
                "display_label": self._humanize_label(fallback_tier),
            }

        archetype_subs: set[str] = set()
        if archetype and archetype in self.sub_domain_vectors:
            archetype_subs = set(self.sub_domain_vectors[archetype].keys())

        adjusted_scores: dict[str, float] = {}
        for sub_name, vector_list in global_vectors.items():
            max_sim = -1.0
            for kw_vec in vector_list:
                sim = self.cosine_similarity(column_vector, kw_vec)
                if sim > max_sim:
                    max_sim = sim
            if sub_name in archetype_subs:
                max_sim = min(1.0, max_sim * 1.05)
            adjusted_scores[sub_name] = max_sim

        winning_domain = max(adjusted_scores, key=adjusted_scores.get)
        micro_confidence = adjusted_scores[winning_domain]
        macro_tier = self._best_tier_for_domain(winning_domain) or winning_tier or archetype or "unknown"
        macro_confidence = tier_scores.get(macro_tier, macro_confidence)

        return {
            "predicted_domain": winning_domain,
            "macro_tier": macro_tier,
            "confidence": float(micro_confidence),
            "pass_1_score": float(macro_confidence),
            "pass_2_score": float(micro_confidence),
            "sub_domain_scores": {k: float(v) for k, v in adjusted_scores.items()},
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