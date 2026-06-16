from analysis_state.schema_graph_utils import (
    enrich_schema_graph_edges,
    infer_owl_type,
    parse_domains_from_reason,
    parse_embedding_similarity,
)


def test_parse_embedding_similarity():
    assert parse_embedding_similarity("Same domain (age), similarity=0.612; potential") == 0.612
    assert parse_embedding_similarity("High embedding similarity (0.401) within same cluster") == 0.401
    assert parse_embedding_similarity("no numbers") is None


def test_infer_owl_type_cross_domain():
    assert infer_owl_type("cross_domain_linkage") == "owl:ObjectProperty"


def test_infer_owl_type_co_cluster_same_domain():
    assert (
        infer_owl_type(
            "co_cluster_semantic",
            source_domain="age",
            target_domain="age",
        )
        == "owl:equivalentProperty"
    )


def test_infer_owl_type_co_cluster_cross_domain():
    assert (
        infer_owl_type(
            "co_cluster_semantic",
            source_domain="age",
            target_domain="health",
        )
        == "owl:ObjectProperty"
    )


def test_infer_owl_type_intra_domain_high_similarity():
    assert (
        infer_owl_type(
            "intra_domain_association",
            semantic_reason="Same domain (age), similarity=0.612; potential redundant",
        )
        == "rdfs:subPropertyOf"
    )


def test_parse_cross_domain_reason():
    sd, td = parse_domains_from_reason("Cross-domain linkage labour_market <-> inflation; similarity=0.854.")
    assert sd == "labour_market"
    assert td == "inflation"


def test_enrich_schema_graph_edges_uses_domain_map():
    edges = enrich_schema_graph_edges(
        [
            {
                "source": "index_agricultural_labourers",
                "target": "index_rural_labourers",
                "weight": 0.9,
                "relationship_type": "co_cluster_semantic",
                "semantic_reason": "High similarity (0.933) within same cluster; coherence bonus 0.180.",
            }
        ],
        domain_map={
            "index_agricultural_labourers": "labour_market",
            "index_rural_labourers": "labour_market",
        },
    )
    assert edges[0]["owl_type"] == "owl:equivalentProperty"


def test_infer_owl_type_intra_domain_low_similarity():
    assert (
        infer_owl_type(
            "intra_domain_association",
            semantic_reason="Same domain (age), similarity=0.412.",
        )
        == "rdfs:seeAlso"
    )

