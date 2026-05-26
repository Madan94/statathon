import pytest
from unittest.mock import MagicMock, patch, ANY
from api.services.semantic_persistence_service import SemanticPersistenceService
from core.state import AnalysisState

@pytest.fixture
def mock_db_session():
    """Pytest fixture for a mock SQLAlchemy session."""
    return MagicMock()

def test_supabase_serialization(mock_db_session):
    """
    Tests that the SemanticPersistenceService correctly serializes
    the AnalysisState and calls the appropriate repository methods.
    """
    # 1. Setup Mock Data
    dataset_id = 'test_123'
    analysis_id = 'analysis_abc'
    
    mock_state = MagicMock(spec=AnalysisState)
    mock_state.dataset_id = dataset_id
    mock_state.analysis_id = analysis_id
    mock_state.dataset_profile = {
        "archetype": "labor_force_survey",
        "dataset_description": "A sample survey."
    }
    mock_state.column_profiles = {
        "col1": {"description": "Age of respondent"},
        "col2": {"description": "Gender of respondent"}
    }
    mock_state.inferred_dataset_context = {
        "domain": "social_survey",
        "confidence": 0.8
    }
    mock_state.profiling_summary = {
        "completeness": 0.95,
        "uniqueness": 0.98
    }
    mock_state.dataset_metadata = {
        "row_count": 1000,
        "file_size": 51200
    }
    mock_state.static_domains = ["gender", "state"]
    mock_state.schema_blueprint = {
        "col1": {"type": "numerical"},
        "col2": {"type": "categorical"}
    }
    mock_state.knowledge_graph = {
        "nodes": [], "edges": []
    }
    mock_state.semantic_profile = {
        "columns": {
            "col1": {
                "domain": "age",
                "confidence": 0.9,
                "cluster_id": "cluster_a",
                "explainability": "High",
                "top_domain_scores": [("age", 0.9)],
                "normalized_name": "col1_norm",
                "cluster_support": 0.8,
                "graph_consistency": 0.85,
            },
            "col2": {
                "domain": "gender",
                "confidence": 0.95,
                "cluster_id": "cluster_b",
                "is_independent": True,
            }
        }
    }
    mock_state.semantic_clusters = [
        {
            "cluster_id": "cluster_a",
            "domain": "age_group",
            "support_score": 0.88,
            "support": 2,
            "columns": ["col1", "col3"],
            "domain_distribution": {"age": 1.0}
        }
    ]
    mock_state.schema_graph = {
        "edges": [
            {"source": "col1", "target": "col2", "weight": 0.5, "relationship_type": "semantic", "semantic_reason": "related"}
        ]
    }
    mock_state.dependency_graph = {
        "col1": [
            {"column": "col2", "score": 0.7, "dependency_reason": "correlated", "embedding_similarity": 0.6, "cluster_strength": 0.5, "graph_signal": 0.9}
        ]
    }

    # 2. Mock the Repositories
    with patch('api.services.semantic_persistence_service.SemanticProfileRepository') as MockProfileRepo, \
         patch('api.services.semantic_persistence_service.SemanticClusterRepository') as MockClusterRepo, \
         patch('api.services.semantic_persistence_service.SchemaGraphRepository') as MockGraphRepo, \
         patch('api.services.semantic_persistence_service.PriorityDependencyRepository') as MockPriorityRepo, \
         patch('api.services.semantic_persistence_service.DatasetContextRepository') as MockContextRepo, \
         patch('api.services.semantic_persistence_service.DatasetIntelligenceRepository') as MockIntelRepo:

        # Instantiate mocks
        mock_profile_repo = MockProfileRepo.return_value
        mock_cluster_repo = MockClusterRepo.return_value
        mock_graph_repo = MockGraphRepo.return_value
        mock_priority_repo = MockPriorityRepo.return_value

        # 3. Execute the Save
        persistence_service = SemanticPersistenceService(db=mock_db_session)
        persistence_service.persist_state(mock_state)

        # 4. Assert Database Calls
        # Assert that repositories were initialized with the db session
        MockProfileRepo.assert_called_once_with(mock_db_session)
        MockClusterRepo.assert_called_once_with(mock_db_session)
        MockGraphRepo.assert_called_once_with(mock_db_session)
        MockPriorityRepo.assert_called_once_with(mock_db_session)

        # Assert that the main 'replace' methods were called on the repos
        mock_profile_repo.replace_for_analysis.assert_called_once()
        mock_cluster_repo.replace_for_analysis.assert_called_once()
        mock_graph_repo.replace_for_analysis.assert_called_once()
        mock_priority_repo.replace_for_analysis.assert_called_once()

        # Assert calls with correct IDs
        mock_profile_repo.replace_for_analysis.assert_called_with(dataset_id, analysis_id, ANY)
        mock_cluster_repo.replace_for_analysis.assert_called_with(dataset_id, analysis_id, ANY)
        mock_graph_repo.replace_for_analysis.assert_called_with(dataset_id, analysis_id, ANY)
        mock_priority_repo.replace_for_analysis.assert_called_with(dataset_id, analysis_id, ANY)

        # Assert payload for profile repo
        profile_args, _ = mock_profile_repo.replace_for_analysis.call_args
        assert profile_args[2][0]['column_name'] == 'col1'
        assert profile_args[2][0]['semantic_domain'] == 'age'
        assert profile_args[2][1]['column_name'] == 'col2'
        assert profile_args[2][1]['semantic_domain'] == 'gender'
