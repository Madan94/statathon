import pytest
from model.semantic_mapping.column_preprocessor import ColumnPreprocessor

def test_column_normalization():
    """
    Tests the ColumnPreprocessor's ability to clean, normalize, and expand
    abbreviations in a list of raw database-style column headers.
    """
    # 1. Arrange: Define a list of raw, messy column headers
    raw_headers = ["nic_2008", "nco_2004", "AgeGroup", "visit", "sys_checksum_09x"]
    
    # Initialize the preprocessor
    preprocessor = ColumnPreprocessor()
    
    # 2. Act: Run the normalization process
    # The main method is `normalize_columns`, which returns a dictionary
    processed_map = preprocessor.normalize_columns(raw_headers)
    processed_list = list(processed_map.values())
    
    # 3. Assert: Verify the output's integrity and transformations
    assert isinstance(processed_list, list), "Output should be a list of strings."
    assert len(processed_list) == len(raw_headers), "Output list must have the same length as the input."
    
    # Check specific transformations
    assert processed_map["AgeGroup"] == "age group", "CamelCase 'AgeGroup' should be split and lowercased."
    assert processed_map["nic_2008"] == "nic 2008", "Underscores should be replaced with spaces."
    assert "sys checksum 09x" in processed_list, "Special characters and numbers should be handled."
    
    # Verify that a simple word remains correct
    assert processed_map["visit"] == "visit", "Simple words should not be altered."
