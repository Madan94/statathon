"""Structured extraction prompts — type-specific prompts for Pass 2 and Pass 3.

Each prompt is designed for Qwen2.5-VL-7B within a 2048-token context.
They ask for JSON output to enable structured AST assembly.
"""

# ─────────────────────────────────────────────────────────────────────────────
# Pass 2: Content Extraction Prompts
# ─────────────────────────────────────────────────────────────────────────────

CONTENT_EXTRACTION_PROMPT = """\
You are analyzing page {page_num} of {total_pages} of document "{doc_title}".
Layout analysis detected these regions:
{region_desc}

For each region, extract:
- text: verbatim text content
- table: column headers + 2 sample rows as JSON
- figure/chart: type, title, axis labels
- heading: text + level (1=chapter, 2=section, 3=subsection)

Output JSON: {{"regions": [{{"region_idx": 0, "type": "...", "content": {{...}}}}]}}
Be concise. Only output JSON."""

TABLE_EXTRACTION_PROMPT = """\
Extract this table from page {page_num} of "{doc_title}".
Region bounding box: {bbox}
Hint text: {hint_text}

Output JSON:
{{
  "title": "table title or description",
  "columns": ["col1", "col2", ...],
  "rows": [["val1", "val2", ...], ...],
  "rowCount": <total rows>,
  "units": {{"col1": "unit", ...}},
  "notes": "any footnotes or caveats"
}}
Only output valid JSON."""

CHART_DESCRIPTION_PROMPT = """\
Describe this chart/figure from page {page_num} of "{doc_title}".
Region bounding box: {bbox}
Hint text: {hint_text}

Output JSON:
{{
  "chartType": "bar|line|pie|scatter|area|other",
  "title": "chart title",
  "xAxis": {{"label": "...", "categories": [...]}},
  "yAxis": {{"label": "...", "range": [min, max]}},
  "series": [{{"name": "...", "trend": "increasing|decreasing|stable"}}],
  "keyInsight": "one sentence summary of what the chart shows"
}}
Only output valid JSON."""


# ─────────────────────────────────────────────────────────────────────────────
# Pass 3: Semantic Analysis Prompts
# ─────────────────────────────────────────────────────────────────────────────

SEMANTIC_ANALYSIS_PROMPT = """\
{context_prefix}

Content:
{chunk_text}

Extract from this section:
1. semantic_hierarchy: [{{"nodeId": "s1", "parentId": null, "level": 1, "title": "...", "pageSpan": [1,3]}}]
2. entities: [{{"entityId": "e1", "type": "org|metric|demographic|time", "name": "..."}}]
3. template_slots: [{{"slotId": "slot1", "entityRef": "e1", "slotType": "value|label|range", "currentValue": "...", "description": "..."}}]
4. questions: [{{"id": "q1", "question": "...", "section": "..."}}]

Output ONLY JSON with these 4 keys. Be concise."""

ENTITY_EXTRACTION_PROMPT = """\
{context_prefix}

Text from "{section_title}" (pages {start_page}-{end_page}):
{text}

Extract all named entities and metrics. Categories:
- org: organizations, companies, agencies
- metric: KPIs, statistics, percentages, dollar amounts
- demographic: population groups, age ranges, regions
- time: dates, time periods, fiscal years

Output JSON:
{{
  "entities": [
    {{"entityId": "e1", "type": "org", "name": "...", "context": "brief context"}},
    ...
  ],
  "template_slots": [
    {{"slotId": "slot1", "entityRef": "e1", "slotType": "value", "currentValue": "...", "description": "what this value represents"}}
  ]
}}
Only output valid JSON."""
