"""Entity Classifier — determines entity type (dimension/measure/filter/metadata).

Uses keyword heuristics and structural patterns to classify entities.
"""
from __future__ import annotations

import re

# Keywords indicating MEASURE entities (quantitative)
_MEASURE_KEYWORDS = re.compile(
    r"(rate|ratio|percentage|proportion|count|total|average|mean|median|"
    r"index|score|expenditure|income|population|amount|value|weight|"
    r"frequency|density|cost|price|salary|wage|revenue|profit|loss|"
    r"growth|decline|change|variance|deviation|correlation|"
    r"mpce|gdp|gva|cpi|wpi|iip|gfcf|nsdp|gsdp)",
    re.IGNORECASE,
)

# Keywords indicating DIMENSION entities (categorical)
_DIMENSION_KEYWORDS = re.compile(
    r"(state|district|region|zone|sector|rural|urban|gender|sex|"
    r"male|female|category|class|group|type|level|stratum|"
    r"age|year|month|quarter|period|season|round|schedule|"
    r"occupation|industry|religion|caste|education|literacy)",
    re.IGNORECASE,
)

# Keywords indicating FILTER entities
_FILTER_KEYWORDS = re.compile(
    r"(above|below|more than|less than|between|excluding|including|"
    r"only|selected|major|minor|top|bottom)",
    re.IGNORECASE,
)

# Keywords indicating METADATA entities
_METADATA_KEYWORDS = re.compile(
    r"(source|reference|nsso|census|survey|round|schedule|"
    r"publication|ministry|department|directorate|bureau|"
    r"government|india|methodology|sampling|frame)",
    re.IGNORECASE,
)


def classify_entity_type(name: str, source_type: str) -> str:
    """Classify an entity name into dimension/measure/filter/metadata.

    Args:
        name: The entity name to classify.
        source_type: Where the entity was found (table_header, chart_axis, etc.)

    Returns:
        One of: "dimension", "measure", "filter", "metadata"
    """
    name_lower = name.lower().strip()

    # Source-type heuristics
    if source_type == "chart_axis":
        # Y-axis is typically a measure, X-axis is typically a dimension
        if _MEASURE_KEYWORDS.search(name_lower):
            return "measure"
        return "dimension"

    if source_type == "chart_legend":
        return "dimension"  # legends are almost always categorical

    if source_type == "footnote":
        return "metadata"  # footnotes reference sources

    if source_type == "formula_variable":
        return "measure"  # formula variables are typically quantitative

    # Keyword-based classification
    measure_score = len(_MEASURE_KEYWORDS.findall(name_lower))
    dimension_score = len(_DIMENSION_KEYWORDS.findall(name_lower))
    filter_score = len(_FILTER_KEYWORDS.findall(name_lower))
    metadata_score = len(_METADATA_KEYWORDS.findall(name_lower))

    scores = {
        "measure": measure_score,
        "dimension": dimension_score,
        "filter": filter_score,
        "metadata": metadata_score,
    }

    best = max(scores, key=scores.get)  # type: ignore
    if scores[best] > 0:
        return best

    # Fallback: if contains numbers or units, likely measure
    if re.search(r"[₹$%]|\b(lakhs?|crores?|000s?|mn|bn)\b", name_lower):
        return "measure"

    # Default: dimension (most common in government reports)
    return "dimension"
