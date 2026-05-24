"""Flatten validation hits into actionable **candidates** (no mutation)."""


def single_row_candidates_for_violations(
    *,
    column: str | None,
    violations: list[int],
    severity: str,
    rule_ref: dict,
    kind: str = "single_column",
) -> list[dict]:
    """
    One candidate per offending row × optional column (multi-column attaches multiple columns).

    candidate_action stays symbolic until explicit user DECISION/APPLY elsewhere.
    """
    out = []
    for row in violations:
        out.append(
            {
                "kind": kind,
                "column": column,
                "row": int(row),
                "severity": severity,
                "candidate_action": "REMOVE_VALUE",
                "alternate_actions": ["MARK_VALID", "KEEP", "SKIP"],
                "rule": rule_ref,
            }
        )
    return out


def build_validation_candidates(single_reports: list[dict], multi_reports: list[dict]) -> list[dict]:
    candidates: list[dict] = []
    for sr in single_reports:
        cols = sr.get("column") or ""
        refs = {"rule_expression": sr.get("rule_expression"), "rule_id": sr.get("rule_id")}
        violations = sr.get("violations") or []
        if not violations:
            continue
        candidates.extend(
            single_row_candidates_for_violations(
                column=cols,
                violations=violations,
                severity=sr.get("severity") or "medium",
                rule_ref=refs,
                kind="single_column",
            )
        )

    for mr in multi_reports:
        refs = {"rule_expression": mr.get("rule_expression"), "rule_id": mr.get("rule_id")}
        violations = mr.get("violations") or []
        if not violations:
            continue

        cols = mr.get("columns_involved") or []
        anchor = cols[0] if cols else None
        candidates.extend(
            single_row_candidates_for_violations(
                column=anchor,
                violations=violations,
                severity=mr.get("severity") or "medium",
                rule_ref={
                    **refs,
                    "columns_involved": cols,
                    "explain": mr.get("explain"),
                },
                kind="multi_column",
            )
        )

    return candidates
