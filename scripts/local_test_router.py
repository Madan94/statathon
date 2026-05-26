import sys
import numpy as np
sys.path.insert(0, '.')

from model.semantic_mapping.hierarchical_router import HierarchicalDomainRouter

class DummyEmbedder:
    def embed_text(self, t):
        return np.ones(384)
    def encode(self, t):
        return np.ones(384)

r = HierarchicalDomainRouter('model/config/domain_definitions.json', DummyEmbedder())

print('census fuzzy vocab sample keys:', list(r.fuzzy_vocab.get('census', {}).keys())[:10])

from rapidfuzz import process, distance
keys = list(r.fuzzy_vocab.get('census', {}).keys())
print('rapidfuzz extractOne for psu_code:', process.extractOne('psu_code', keys, scorer=distance.JaroWinkler.normalized_similarity))

print('predict_domain for psu_code:', r.predict_domain('psu_code', np.ones(384), 'census'))
