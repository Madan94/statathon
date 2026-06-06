import sys
import os
from pathlib import Path

# Add the root 'statathon' directory to Python's path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from model.semantic_mapping.column_preprocessor import ColumnPreprocessor

preprocessor = ColumnPreprocessor()
output = preprocessor.normalize_columns(["hh_size", "exp_total", "is_beneficiary"])
print(f"\nExact Preprocessor Output: {output}\n")
