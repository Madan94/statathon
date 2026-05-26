import sys
from pathlib import Path
import json
import numpy as np

# Ensure repo root is on PYTHONPATH
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from model.semantic_mapping.dynamic_domain_generator import DynamicDomainGenerator


def main():
    gen = DynamicDomainGenerator()
    # Mock inputs
    dataset_type = "mospi"
    normalized_columns = {
        "survey_id": "survey_id",
        "state_code": "state_code",
        "hh_size": "hh_size",
        "sal": "sal",
    }
    # Random but deterministic embeddings
    rng = np.random.RandomState(0)
    column_embeddings = {k: rng.rand(384) for k in normalized_columns}
    provisional_domains = {  # provisional parent themes
        "survey_id": "identifier",
        "state_code": "geography",
        "hh_size": "household",
        "sal": "income",
    }

    runtime = gen.generate(
        dataset_type=dataset_type,
        normalized_columns=normalized_columns,
        column_embeddings=column_embeddings,
        provisional_domains=provisional_domains,
        schema_graph=None,
        dataset_domain="Economics",
    )

    print(json.dumps({k: v.get("metadata") for k, v in runtime.items()}, indent=2))


if __name__ == "__main__":
    main()
