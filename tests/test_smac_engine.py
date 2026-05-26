import numpy as np
import pytest
from model.semantic_mapping.cluster_engine import ClusterEngine

def test_vector_clustering_logic():
    """
    Tests that the ClusterEngine correctly groups columns based on the
    cosine similarity of their vector embeddings.
    """
    # 1. Arrange: Initialize the engine and create mock embeddings
    cluster_engine = ClusterEngine(similarity_threshold=0.9) # Use a high threshold for a predictable test
    
    # Create 4 mock column embeddings, with two being mathematically very close
    embeddings = {
        'nic 2008': np.random.rand(384),
        'age': np.random.rand(384),
        'sys checksum': np.random.rand(384),
        'nco 2004': np.random.rand(384) # This will be overwritten
    }
    
    # Force 'nco 2004' to be extremely similar to 'nic 2008'
    embeddings['nco 2004'] = embeddings['nic 2008'] + np.random.normal(0, 0.01, 384)

    # 2. Act: Run the clustering method
    # The engine has `cluster_columns`, which is the main entry point.
    clusters_result = cluster_engine.cluster_columns(embeddings)
    
    # The result is a dictionary mapping cluster IDs to lists of column names.
    # We need to find which cluster our target columns ended up in.
    nic_cluster_id = None
    nco_cluster_id = None
    for cluster_id, columns_in_cluster in clusters_result.items():
        if 'nic 2008' in columns_in_cluster:
            nic_cluster_id = cluster_id
        if 'nco 2004' in columns_in_cluster:
            nco_cluster_id = cluster_id
            
    # 3. Assert: Verify the clustering logic
    assert clusters_result, "The clustering engine should have produced a non-empty result."
    assert nic_cluster_id is not None, "'nic 2008' should have been assigned to a cluster."
    assert nco_cluster_id is not None, "'nco 2004' should have been assigned to a cluster."
    
    assert nic_cluster_id == nco_cluster_id, \
        f"'nic 2008' and 'nco 2004' were forced to be similar but ended up in different clusters: " \
        f"({nic_cluster_id} vs {nco_cluster_id})"
