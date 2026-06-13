"""E12 — Value-Free Contract Validator (Hard Gate).

Ensures template.ast.json and template.blueprint.json remain reusable
templates — no actual report values, filled prose, table rows, or chart
series may leak into these artifacts.

This is a HARD GATE: emission is blocked if any value leakage is detected
in STRICT mode.

Core principle:
    Values and prose live ONLY in report.output.ast.json (③).
    ① template.ast.json and ② template.blueprint.json are value-free negatives.

Usage:
    from report_builder.value_free_validator import validate_value_free
    result = validate_value_free(skeleton_dict, blueprint_dict)
    if result.has_errors:
        raise ValueLeakageError(result.leakages)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterator

# ─────────────────────────────────────────────────────────────────────────────
# Result models
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class ValueLeakage:
    """One detected value/prose leakage violation."""
    code: str = ""
    severity: str = "error"             # error | warn
    path: str = ""
    message: str = ""
    valuePreview: str = ""
    recommendedAction: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "path": self.path,
            "message": self.message,
            "valuePreview": self.valuePreview,
            "recommendedAction": self.recommendedAction,
        }


@dataclass
class ValueFreeValidationResult:
    """Result of value-free validation."""
    status: str = "VALID"               # VALID | INVALID
    leakages: list[ValueLeakage] = field(default_factory=list)
    warnings: list[ValueLeakage] = field(default_factory=list)
    checkedPaths: list[str] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return any(l.severity == "error" for l in self.leakages)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "leakageCount": len(self.leakages),
            "warningCount": len(self.warnings),
            "leakages": [l.to_dict() for l in self.leakages],
            "warnings": [w.to_dict() for w in self.warnings],
            "checkedPaths": self.checkedPaths,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Detection patterns
# ─────────────────────────────────────────────────────────────────────────────

# Structural numbers that ARE allowed (context-dependent)
_YEAR_RE = re.compile(r'^(19|20)\d{2}(-\d{2,4})?$')
_TABLE_NUM_RE = re.compile(r'^(Table|Fig(ure)?)\s+\d+(\.\d+)?$', re.IGNORECASE)
_VERSION_RE = re.compile(r'^\d{1,2}\.\d{1,2}(\.\d{1,3})?$')  # 1.0, 3.2.1 (not 400.7)

# Data value patterns (numbers that should NOT appear in templates)
_LARGE_DECIMAL_RE = re.compile(r'\b\d{2,}\.\d{1,}\b')          # 400.7, 11.29, 672.07
_PERCENTAGE_VALUE_RE = re.compile(r'\b\d+\.\d+\s*%')           # 78.4%, 11.29%
_CURRENCY_RE = re.compile(r'[₹$€£]\s*[\d,]+\.?\d*')           # ₹16,893, $1,234.56
_LARGE_INT_RE = re.compile(r'\b\d{4,}\b')                      # 16893, 400700 (not years)
_COMMA_NUMBER_RE = re.compile(r'\b\d{1,3}(,\d{3})+(\.\d+)?\b')  # 1,234,567

# Paths where numeric values ARE allowed (structural, not data)
_NUMERIC_ALLOWED_PATHS = {
    "templateMeta.version",
    "metadata.version",
    "styleAST",
    "layoutAST",
    "geometryAST",
    "source.page",
    "sourcePage",
    "sourcePages",
    "page",
    "sizePt",
    "fontSize",
    "bbox",
    "confidence",
    "expectedCardinality",
    "cardinalityHint",
    "priority",
    "order",
    "tableNumber",
    "figureNumber",
    "span",
    "rowCount",
    "colCount",
    "minValue",
    "maxValue",
    "min",
    "max",
    "valueDomain",
}

# Max chars before content is suspicious prose
_PROSE_THRESHOLD = 120


# ─────────────────────────────────────────────────────────────────────────────
# Utility helpers
# ─────────────────────────────────────────────────────────────────────────────


def preview(value: Any, max_len: int = 120) -> str:
    """Create a safe preview string from a value."""
    s = str(value)
    if len(s) > max_len:
        return s[:max_len] + "..."
    return s


def is_structural_number(value: Any, path: str) -> bool:
    """Check if a numeric value is structural (allowed) based on path context."""
    if not isinstance(value, (int, float)):
        return False

    # Path-based allowlist
    path_parts = path.split(".")
    for allowed in _NUMERIC_ALLOWED_PATHS:
        if allowed in path:
            return True

    # Small integers in structural positions (order, priority, page)
    if isinstance(value, int) and 0 <= value <= 1000:
        # Check path hints
        last = path_parts[-1] if path_parts else ""
        if last in ("page", "order", "priority", "span", "index", "level",
                    "sizePt", "bold", "italic", "colSpan", "rowSpan"):
            return True

    # Confidence/ratio scores [0, 1]
    if isinstance(value, float) and 0.0 <= value <= 1.0:
        last = path_parts[-1] if path_parts else ""
        if last in ("confidence", "score", "threshold", "opacity"):
            return True

    return False


def looks_like_data_value(text: str, path: str) -> bool:
    """Check if a text string contains what looks like actual statistical data."""
    if not text or len(text) < 3:
        return False

    # Path-based exclusion (these paths can have numbers)
    for allowed in _NUMERIC_ALLOWED_PATHS:
        if allowed in path:
            return False

    # Check patterns
    if _LARGE_DECIMAL_RE.search(text):
        # But exclude years
        matches = _LARGE_DECIMAL_RE.findall(text)
        for m in matches:
            if not _YEAR_RE.match(m) and not _VERSION_RE.match(m):
                return True

    if _PERCENTAGE_VALUE_RE.search(text):
        return True

    if _CURRENCY_RE.search(text):
        return True

    if _COMMA_NUMBER_RE.search(text):
        return True

    return False


def looks_like_report_prose(text: str, path: str) -> bool:
    """Check if text looks like copied report prose (not a template)."""
    if not text or len(text) < _PROSE_THRESHOLD:
        return False

    # Template strings are ok
    if is_template_string(text):
        return False

    # Very long text with sentence structure = likely prose
    sentences = text.count(".") + text.count("!") + text.count("?")
    words = len(text.split())

    if words > 25 and sentences >= 2:
        return True

    if len(text) > 300:
        return True

    return False


def is_template_string(text: str) -> bool:
    """Check if text is a template placeholder."""
    if not text:
        return True  # empty is fine
    if "{{" in text and "}}" in text:
        return True
    if text.startswith("{") and text.endswith("}"):
        return True
    if text in ("", "empty", "placeholder", "TBD"):
        return True
    return False


def walk_json(obj: Any, path: str = "") -> Iterator[tuple[str, Any]]:
    """Walk a JSON-like structure yielding (path, value) pairs."""
    if isinstance(obj, dict):
        for key, val in obj.items():
            child_path = f"{path}.{key}" if path else key
            yield child_path, val
            yield from walk_json(val, child_path)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            child_path = f"{path}[{i}]"
            yield child_path, item
            yield from walk_json(item, child_path)


# ─────────────────────────────────────────────────────────────────────────────
# Template AST validator
# ─────────────────────────────────────────────────────────────────────────────


def assert_template_ast_value_free(skeleton: dict[str, Any]) -> list[ValueLeakage]:
    """Check template.ast.json for value/prose leakage.

    Hard errors:
    1. contentAST.blocks[].content must be empty/placeholder
    2. tableAST.tables[].rows must be empty
    3. chartAST.charts[].series must be empty
    4. figureAST.figures[].caption must be empty/templated
    5. No metric values
    """
    leakages: list[ValueLeakage] = []

    # ── 1. Content blocks must be empty ──
    content_ast = skeleton.get("contentAST") or {}
    blocks = (content_ast.get("blocks") or []) + (content_ast.get("paragraphs") or [])
    for i, block in enumerate(blocks):
        content = block.get("content") or ""
        if not content:
            continue
        if is_template_string(content):
            continue
        if looks_like_report_prose(content, f"contentAST.blocks[{i}].content"):
            leakages.append(ValueLeakage(
                code="PROSE_IN_TEMPLATE_AST",
                severity="error",
                path=f"contentAST.blocks[{i}].content",
                message="Block contains report prose — must be empty in template",
                valuePreview=preview(content),
                recommendedAction="Clear content to '' or use template placeholder",
            ))
        elif looks_like_data_value(content, f"contentAST.blocks[{i}].content"):
            leakages.append(ValueLeakage(
                code="DATA_VALUE_IN_CONTENT",
                severity="error",
                path=f"contentAST.blocks[{i}].content",
                message="Block contains data values — must be empty in template",
                valuePreview=preview(content),
                recommendedAction="Clear content to ''",
            ))

    # ── 2. Table rows must be empty ──
    table_ast = skeleton.get("tableAST") or {}
    for i, table in enumerate(table_ast.get("tables") or []):
        rows = table.get("rows") or []
        if rows:
            leakages.append(ValueLeakage(
                code="TABLE_ROWS_IN_TEMPLATE",
                severity="error",
                path=f"tableAST.tables[{i}].rows",
                message=f"Table has {len(rows)} data rows — must be empty in template",
                valuePreview=preview(rows[0]) if rows else "",
                recommendedAction="Set rows=[] in template AST",
            ))
        cells = table.get("cells") or []
        if cells:
            leakages.append(ValueLeakage(
                code="TABLE_CELLS_IN_TEMPLATE",
                severity="error",
                path=f"tableAST.tables[{i}].cells",
                message=f"Table has {len(cells)} cells — must be empty in template",
                valuePreview=preview(cells[0]) if cells else "",
                recommendedAction="Set cells=[] in template AST",
            ))

    # ── 3. Chart series must be empty ──
    chart_ast = skeleton.get("chartAST") or {}
    for i, chart in enumerate(chart_ast.get("charts") or []):
        series = chart.get("series") or []
        if series:
            # Check if series have actual data values
            has_data = any(
                s.get("data") or s.get("values") or s.get("dataPoints")
                for s in series if isinstance(s, dict)
            )
            if has_data:
                leakages.append(ValueLeakage(
                    code="CHART_SERIES_IN_TEMPLATE",
                    severity="error",
                    path=f"chartAST.charts[{i}].series",
                    message=f"Chart has {len(series)} series with data — must be empty in template",
                    valuePreview=preview(series[0]),
                    recommendedAction="Set series=[] in template AST",
                ))
        data_points = chart.get("dataPoints") or []
        if data_points:
            leakages.append(ValueLeakage(
                code="CHART_DATAPOINTS_IN_TEMPLATE",
                severity="error",
                path=f"chartAST.charts[{i}].dataPoints",
                message="Chart has dataPoints — must be empty in template",
                valuePreview=preview(data_points[0]) if data_points else "",
                recommendedAction="Set dataPoints=[] in template AST",
            ))

    # ── 4. Figure captions must be empty/templated ──
    figure_ast = skeleton.get("figureAST") or {}
    for i, fig in enumerate(figure_ast.get("figures") or []):
        caption = fig.get("caption") or ""
        if caption and not is_template_string(caption):
            if looks_like_data_value(caption, f"figureAST.figures[{i}].caption"):
                leakages.append(ValueLeakage(
                    code="FIGURE_CAPTION_DATA",
                    severity="error",
                    path=f"figureAST.figures[{i}].caption",
                    message="Figure caption contains data values",
                    valuePreview=preview(caption),
                    recommendedAction="Clear caption or use template: '{{caption}}'",
                ))
            elif looks_like_report_prose(caption, f"figureAST.figures[{i}].caption"):
                leakages.append(ValueLeakage(
                    code="FIGURE_CAPTION_PROSE",
                    severity="error",
                    path=f"figureAST.figures[{i}].caption",
                    message="Figure caption is full prose — must be empty/templated",
                    valuePreview=preview(caption),
                    recommendedAction="Clear caption or use template placeholder",
                ))

    # ── 5. Metric values must be null ──
    metric_ast = skeleton.get("metricAST") or {}
    for i, metric in enumerate(metric_ast.get("metrics") or []):
        value = metric.get("value")
        if value is not None and value != "" and not is_template_string(str(value)):
            leakages.append(ValueLeakage(
                code="METRIC_VALUE_IN_TEMPLATE",
                severity="error",
                path=f"metricAST.metrics[{i}].value",
                message="Metric has a value — must be null in template",
                valuePreview=preview(value),
                recommendedAction="Set value=null in template AST",
            ))

    # ── 6. factGraph must be empty ──
    fact_graph = skeleton.get("factGraph") or {}
    facts = fact_graph.get("facts") or []
    if facts:
        # Check if facts contain actual data statements
        for i, fact in enumerate(facts):
            statement = fact.get("statement") or fact.get("text") or ""
            if statement and looks_like_data_value(statement, f"factGraph.facts[{i}]"):
                leakages.append(ValueLeakage(
                    code="FACT_IN_TEMPLATE",
                    severity="error",
                    path=f"factGraph.facts[{i}]",
                    message="factGraph contains data — must be empty in template",
                    valuePreview=preview(statement),
                    recommendedAction="Clear factGraph.facts=[] in template",
                ))
                break  # One is enough to flag

    return leakages


# ─────────────────────────────────────────────────────────────────────────────
# Blueprint validator
# ─────────────────────────────────────────────────────────────────────────────


def assert_blueprint_value_free(blueprint: dict[str, Any]) -> list[ValueLeakage]:
    """Check template.blueprint.json for value/prose leakage.

    Hard errors:
    1. No statistical data values in entity names/intents
    2. No long report prose in any text field
    3. No table row values in tableTemplates
    4. No chart values in figureTemplates
    """
    leakages: list[ValueLeakage] = []

    # ── 1. Entity names should not contain data values ──
    for i, ent in enumerate(blueprint.get("entities") or []):
        name = ent.get("canonicalName") or ""
        if looks_like_data_value(name, f"entities[{i}].canonicalName"):
            # But allow "Table 1.1" style references or year-suffixed names
            if not _TABLE_NUM_RE.match(name) and not _YEAR_RE.match(name.split()[-1] if name.split() else ""):
                leakages.append(ValueLeakage(
                    code="DATA_IN_ENTITY_NAME",
                    severity="warn",
                    path=f"entities[{i}].canonicalName",
                    message=f"Entity name contains what looks like a data value: '{name}'",
                    valuePreview=name,
                    recommendedAction="Remove data values from entity canonical names",
                ))

    # ── 2. Question intents should not contain answers ──
    questions: list[dict[str, Any]] = []
    for topic in (blueprint.get("topics") or []):
        questions.extend(topic.get("questions") or [])
    questions.extend(blueprint.get("questions") or [])

    for i, q in enumerate(questions):
        intent = q.get("intent") or q.get("questionText") or ""
        if looks_like_data_value(intent, f"questions[{i}].intent"):
            leakages.append(ValueLeakage(
                code="DATA_IN_QUESTION_INTENT",
                severity="error",
                path=f"questions[{i}].intent",
                message="Question intent contains data values — should be value-free",
                valuePreview=preview(intent),
                recommendedAction="Remove actual values from intent text",
            ))
        if looks_like_report_prose(intent, f"questions[{i}].intent"):
            leakages.append(ValueLeakage(
                code="PROSE_IN_QUESTION",
                severity="error",
                path=f"questions[{i}].intent",
                message="Question intent is full prose — should be concise analytical intent",
                valuePreview=preview(intent),
                recommendedAction="Shorten intent to a clear question",
            ))

    # ── 3. Table templates should not have row data ──
    for i, tt in enumerate(blueprint.get("tableTemplates") or blueprint.get("tableStructures") or []):
        rows = tt.get("rows") or tt.get("data") or tt.get("sampleRows") or []
        if rows:
            leakages.append(ValueLeakage(
                code="TABLE_DATA_IN_BLUEPRINT",
                severity="error",
                path=f"tableTemplates[{i}].rows",
                message=f"Table template has {len(rows)} data rows — blueprint must be value-free",
                valuePreview=preview(rows[0]) if rows else "",
                recommendedAction="Remove rows/data/sampleRows from table templates",
            ))

    # ── 4. Figure templates should not have series data ──
    for i, ft in enumerate(blueprint.get("figureTemplates") or []):
        series = ft.get("series") or ft.get("data") or ft.get("values") or []
        if series and any(isinstance(s, (dict, list)) and s for s in series):
            leakages.append(ValueLeakage(
                code="CHART_DATA_IN_BLUEPRINT",
                severity="error",
                path=f"figureTemplates[{i}].series",
                message="Figure template has series data — blueprint must be value-free",
                valuePreview=preview(series[0]) if series else "",
                recommendedAction="Remove series/data/values from figure templates",
            ))

    # ── 5. No facts with actual data in blueprint ──
    facts = (blueprint.get("factGraph") or {}).get("facts") or blueprint.get("facts") or []
    if facts:
        for i, fact in enumerate(facts):
            statement = fact.get("statement") or fact.get("text") or ""
            if looks_like_data_value(statement, f"facts[{i}]"):
                leakages.append(ValueLeakage(
                    code="FACTS_IN_BLUEPRINT",
                    severity="error",
                    path=f"facts[{i}]",
                    message="Blueprint contains facts with data values — must be value-free",
                    valuePreview=preview(statement),
                    recommendedAction="Remove factGraph/facts from blueprint",
                ))
                break

    return leakages


# ─────────────────────────────────────────────────────────────────────────────
# Main validators
# ─────────────────────────────────────────────────────────────────────────────


def assert_value_free(
    skeleton: dict[str, Any],
    blueprint: dict[str, Any],
) -> list[ValueLeakage]:
    """Validate both template files for value/prose leakage.

    Returns list of all leakages found. Empty list = clean.
    """
    leakages: list[ValueLeakage] = []
    leakages.extend(assert_template_ast_value_free(skeleton))
    leakages.extend(assert_blueprint_value_free(blueprint))
    return leakages


def validate_value_free(
    skeleton: dict[str, Any],
    blueprint: dict[str, Any],
) -> ValueFreeValidationResult:
    """Full value-free validation returning structured result.

    Args:
        skeleton: template.ast.json dict
        blueprint: template.blueprint.json dict

    Returns:
        ValueFreeValidationResult with status, leakages, and checked paths.
    """
    leakages = assert_value_free(skeleton, blueprint)

    errors = [l for l in leakages if l.severity == "error"]
    warnings = [l for l in leakages if l.severity == "warn"]

    checked_paths = [
        "contentAST.blocks[].content",
        "tableAST.tables[].rows",
        "chartAST.charts[].series",
        "figureAST.figures[].caption",
        "metricAST.metrics[].value",
        "factGraph.facts[]",
        "entities[].canonicalName",
        "questions[].intent",
        "tableTemplates[].rows",
        "figureTemplates[].series",
    ]

    result = ValueFreeValidationResult(
        status="INVALID" if errors else "VALID",
        leakages=leakages,
        warnings=warnings,
        checkedPaths=checked_paths,
    )
    return result
