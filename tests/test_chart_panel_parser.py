from __future__ import annotations

from report_builder.chart_panel_parser import group_chart_panels, parse_chart_panel_title


ENTITIES = [
    {"entityId": "ent_lfpr", "canonicalName": "Labour Force Participation Rate", "entityType": "measure", "aliases": ["LFPR"]},
    {"entityId": "ent_sector", "canonicalName": "Sector", "entityType": "dimension", "aliases": ["area"], "valueDomain": {"members": ["Rural", "Urban"]}},
    {"entityId": "ent_age_group", "canonicalName": "Age Group", "entityType": "dimension", "valueDomain": {"members": ["15 years and above"]}},
    {"entityId": "ent_activity_status", "canonicalName": "Activity Status", "entityType": "dimension", "aliases": ["usual status"], "valueDomain": {"members": ["Usual Status (ps+ss)", "Current Weekly Status"]}},
]


def test_parse_plfs_like_chart_title_without_hardcoded_ids():
    parsed = parse_chart_panel_title(
        "Fig. 1(a): LFPR(%) in usual status (ps+ss) for persons of age 15 years and above in rural areas",
        ENTITIES,
    )
    assert parsed.figureNumber == "1"
    assert parsed.panel == "a"
    assert parsed.measureRefs == ["ent_lfpr"]
    assert {f["entityId"] + ":" + f["value"] for f in parsed.filters} >= {
        "ent_sector:Rural",
        "ent_age_group:15 years and above",
        "ent_activity_status:Usual Status (ps+ss)",
    }


def test_group_chart_panels_by_measure_and_figure(caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="report_builder.chart_panel_parser"):
        groups = group_chart_panels([
            {"chartId": "c1", "figureNumber": "1", "panel": "a", "measureEntityId": "ent_lfpr", "filters": []},
            {"chartId": "c2", "figureNumber": "1", "panel": "b", "measureEntityId": "ent_lfpr", "filters": []},
            {"chartId": "c3", "figureNumber": "2", "panel": "a", "measureEntityId": "ent_wpr", "filters": []},
            {"chartId": "c4", "figureNumber": "3", "panel": "a", "measureEntityId": "", "filters": []},
        ])
    assert len(groups) == 2
    lfpr = next(g for g in groups if g["measureEntityId"] == "ent_lfpr")
    assert len(lfpr["panels"]) == 2
    assert "without measureEntityId" in caplog.text
