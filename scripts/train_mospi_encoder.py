import json
import os
import shutil
from pathlib import Path
from sentence_transformers import SentenceTransformer, InputExample, losses


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]

def build_training_data(json_path):
    """Parses your ontology to generate MoSPI-specific training pairs."""
    if not os.path.exists(json_path):
        raise FileNotFoundError(f"Ontology file not found at {json_path}")
        
    with open(json_path, 'r', encoding='utf-8') as f:
        ontology = json.load(f)
    
    train_examples = []
    # Iterate through all archetypes
    for arch_name, arch_data in ontology.get("dataset_types", {}).items():
        for sub_name, keywords in arch_data.get("subdomains", {}).items():
            # The 'target_concept' is the human-readable domain name
            target_concept = sub_name.replace('_', ' ')
            
            # Create positive training pairs: (abbreviation, human_readable_domain)
            for kw in keywords:
                train_examples.append(InputExample(texts=[kw.lower(), target_concept]))
                
    return train_examples

def train_model():
    root = repo_root()
    save_path = root / "model" / "weights" / "mospi-minilm-v1"
    ontology_path = root / "model" / "config" / "domain_definitions.json"
    
    # 1. Clean previous broken state
    if os.path.exists(save_path):
        shutil.rmtree(save_path)
    os.makedirs(save_path, exist_ok=True)
    
    # 2. Initialize base model (will download once, then use local cache)
    print("🚀 Initializing model training...")
    model = SentenceTransformer('all-MiniLM-L6-v2')
    
    # 3. Build training data
    examples = build_training_data(str(ontology_path))
    from torch.utils.data import DataLoader
    dataloader = DataLoader(examples, shuffle=True, batch_size=32)
    
    # 4. Train using MNRL (forces abbreviations to match domains in vector space)
    loss = losses.MultipleNegativesRankingLoss(model)
    print(f"🧠 Training on {len(examples)} pairs...")
    model.fit(
        train_objectives=[(dataloader, loss)], 
        epochs=10, 
        warmup_steps=100, 
        show_progress_bar=True
    )
    
    # 5. FORCE FULL SAVE
    # This serializes the transformer weights, config, and modules.
    print(f"💾 Saving model to {save_path}...")
    model.save(str(save_path), safe_serialization=True)
    
    # 6. Verification check
    files = os.listdir(save_path)
    if any(f.endswith(('.safetensors', '.bin')) for f in files):
        print("✅ SUCCESS: Model weights successfully serialized.")
        print(f"📁 Files generated: {files}")
    else:
        print("❌ ERROR: Weights failed to save. Check storage permissions.")

if __name__ == "__main__":
    train_model()