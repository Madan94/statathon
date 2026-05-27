import numpy as np
import pytest
from model.semantic_mapping.cluster_engine import ClusterEngine
from model.semantic_mapping.semantic_cluster_engine import SemanticClusterEngine

def test_filter_and_synthesizer_flow():
    """
    Tests the full SMAC flow:
    1. Raw clusters are generated.
    2. A dissimilar column is effectively isolated by the base clustering.
    3. The synthesizer logic assigns a dominant domain to the coherent cluster.
    """
    # 1. Arrange: Mock Data Setup
    raw_clusters = {
        "cluster_0": ["nic_2008", "nco_2004", "visit"],
        "cluster_1": ["sys_checksum_09x"]
    }
    
    # Create mock embeddings
    base_vector = np.random.rand(384)
    embeddings = {
        "nic_2008": base_vector + np.random.normal(0, 0.01, 384),
        "nco_2004": base_vector + np.random.normal(0, 0.01, 384),
        "visit": base_vector + np.random.normal(0, 0.02, 384), # Slightly less similar
        "sys_checksum_09x": np.random.rand(384) # Random
    }

    # Mock domain and confidence inputs for the synthesizer part
    column_domains = {
        "nic_2008": "labor_force_metrics",
        "nco_2004": "labor_force_metrics",
        "visit": "health_metrics", # This should be overridden
        "sys_checksum_09x": "uncorrelated_metadata"
    }
    domain_scores_all = {
        "nic_2008": {"labor_force_metrics": 0.95},
        "nco_2004": {"labor_force_metrics": 0.95},
        "visit": {"health_metrics": 0.40, "labor_force_metrics": 0.35},
        "sys_checksum_09x": {"uncorrelated_metadata": 0.9}
    }

    # 2. Act: Run the engine
    # We mock the base ClusterEngine to return our predictable raw_clusters
    mock_base_engine = ClusterEngine()
    mock_base_engine.cluster_columns = lambda em: raw_clusters
    
    smac_engine = SemanticClusterEngine(base=mock_base_engine)
    
    # The `cluster` method performs both refinement (filtering) and synthesis
    final_clusters, cluster_info = smac_engine.cluster(
        column_embeddings=embeddings,
        column_domains=column_domains,
        domain_scores_all=domain_scores_all
    )

    # 3. Assert: Verify Filter and Synthesizer Logic
    
    # Find the cluster containing our main group and the isolated column
    main_cluster_id = None
    checksum_cluster_id = None
    for cid, members in final_clusters.items():
        if "nic_2008" in members:
            main_cluster_id = cid
        if "sys_checksum_09x" in members:
            checksum_cluster_id = cid

    # Assert Filter Logic: Check that the random column is in its own cluster
    assert checksum_cluster_id is not None, "'sys_checksum_09x' should be in a cluster."
    assert len(final_clusters[checksum_cluster_id]) == 1, "'sys_checksum_09x' should be isolated in its own cluster."
    
    # Assert Synthesizer Logic
    assert main_cluster_id is not None, "The main group should form a cluster."
    
    # Assert that the dominant domain for the main cluster is 'labor_force_metrics'
    main_cluster_details = cluster_info.get(main_cluster_id, {})
    assert main_cluster_details.get("domain") == "labor_force_metrics", \
        "The synthesizer should have assigned the dominant domain 'labor_force_metrics' to the main cluster."

    # Assert that the isolated cluster gets its own domain
    checksum_cluster_details = cluster_info.get(checksum_cluster_id, {})
    assert checksum_cluster_details.get("domain") == "uncorrelated_metadata", \
        "The isolated checksum column should be assigned the 'uncorrelated_metadata' domain."
