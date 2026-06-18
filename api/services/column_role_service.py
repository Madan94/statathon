"""Persist and confirm identifier vs variable column roles."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from core.column_roles import normalize_role
from core.json_safe import make_json_safe
from core.state import AnalysisState
from database.models import Analysis, SemanticProfile
from pipelines.phase3_pipeline import rerun_validation_intel
from services.analysis_payload_cache import invalidate_analysis_cache
from services.analysis_query import get_analysis_meta, load_analysis_checkpoint
from services.normalization_transform_service import load_working_dataframe
from services.phase3_persistence_service import Phase3PersistenceService
from core.ingestion import infer_schema


class ColumnRoleService:
    def __init__(self, db: Session):
        self.db = db

    def _analysis(self, analysis_id: int) -> Analysis:
        an = get_analysis_meta(self.db, analysis_id)
        if not an:
            raise ValueError("Analysis not found")
        return an

    def get_roles(self, analysis_id: int) -> dict[str, Any]:
        an = self._analysis(analysis_id)
        checkpoint = load_analysis_checkpoint(self.db, analysis_id) or {}
        roles: dict[str, dict[str, Any]] = {}
        for row in checkpoint.get("semantic_mapping") or []:
            if not isinstance(row, dict):
                continue
            col = str(row.get("column") or "")
            if not col:
                continue
            roles[col] = {
                "column": col,
                "analysis_role": row.get("analysis_role"),
                "role_confidence": row.get("role_confidence"),
                "role_source": row.get("role_source"),
                "role_reason": row.get("role_reason"),
                "domain": row.get("domain"),
                "original_name": row.get("original_name"),
            }
        if not roles:
            profiles = (
                self.db.query(SemanticProfile)
                .filter(SemanticProfile.analysis_id == analysis_id)
                .all()
            )
            for p in profiles:
                tags = p.contextual_tags if isinstance(p.contextual_tags, dict) else {}
                roles[p.column_name] = {
                    "column": p.column_name,
                    "analysis_role": tags.get("analysis_role"),
                    "role_confidence": tags.get("role_confidence"),
                    "role_source": tags.get("role_source"),
                    "role_reason": tags.get("role_reason"),
                    "domain": p.semantic_domain,
                    "original_name": tags.get("original_name"),
                }
        identifier_count = sum(1 for r in roles.values() if r.get("analysis_role") == "identifier")
        variable_count = sum(1 for r in roles.values() if r.get("analysis_role") == "variable")
        return {
            "analysis_id": analysis_id,
            "roles": list(roles.values()),
            "identifier_count": identifier_count,
            "variable_count": variable_count,
            "column_roles_confirmed": bool(checkpoint.get("column_roles_confirmed")),
        }

    def confirm_roles(
        self,
        analysis_id: int,
        overrides: dict[str, str] | None = None,
        *,
        user_id: int | None = None,
    ) -> dict[str, Any]:
        an = self._analysis(analysis_id)
        checkpoint = dict(load_analysis_checkpoint(self.db, analysis_id) or {})
        mapping = checkpoint.get("semantic_mapping")
        if not isinstance(mapping, list):
            mapping = []

        override_map = {
            str(k): normalize_role(v)
            for k, v in (overrides or {}).items()
            if normalize_role(v)
        }

        columns_meta: dict[str, dict[str, Any]] = {}
        updated_mapping: list[dict[str, Any]] = []

        profiles = (
            self.db.query(SemanticProfile)
            .filter(SemanticProfile.analysis_id == analysis_id)
            .all()
        )
        profile_by_col = {p.column_name: p for p in profiles}

        if isinstance(mapping, list) and mapping:
            source_rows = mapping
        elif profiles:
            source_rows = []
            for p in profiles:
                tags = p.contextual_tags if isinstance(p.contextual_tags, dict) else {}
                source_rows.append(
                    {
                        "column": p.column_name,
                        "domain": p.semantic_domain,
                        "confidence": p.confidence,
                        "cluster_id": p.cluster_id,
                        **tags,
                    }
                )
        else:
            source_rows = []

        for row in source_rows:
            if not isinstance(row, dict):
                continue
            item = dict(row)
            col = str(item.get("column") or "")
            if col in override_map:
                item["analysis_role"] = override_map[col]
                item["role_source"] = "user"
                item["role_confidence"] = 1.0
                item["role_reason"] = "User override in Step 3 semantic review."
            elif not item.get("analysis_role"):
                item["analysis_role"] = override_map.get(col) or "variable"
            updated_mapping.append(item)
            columns_meta[col] = item

        semantic_profile = checkpoint.get("semantic_profile")
        if isinstance(semantic_profile, dict):
            sp_cols = semantic_profile.get("columns")
            if isinstance(sp_cols, dict):
                for col in list(sp_cols.keys()):
                    meta = sp_cols.get(col)
                    if not isinstance(meta, dict):
                        continue
                    meta = dict(meta)
                    if col in override_map:
                        meta["analysis_role"] = override_map[col]
                        meta["role_source"] = "user"
                        meta["role_confidence"] = 1.0
                        meta["role_reason"] = "User override in Step 3 semantic review."
                    elif col in columns_meta:
                        meta.update(
                            {
                                k: columns_meta[col].get(k)
                                for k in (
                                    "analysis_role",
                                    "role_confidence",
                                    "role_source",
                                    "role_reason",
                                )
                                if columns_meta[col].get(k) is not None
                            }
                        )
                    sp_cols[col] = meta
                    columns_meta[str(col)] = meta
                for col, role in override_map.items():
                    if col not in sp_cols:
                        sp_cols[col] = columns_meta.get(col, {"column": col, "analysis_role": role})

        checkpoint["semantic_mapping"] = updated_mapping
        if isinstance(semantic_profile, dict):
            checkpoint["semantic_profile"] = semantic_profile
        checkpoint["column_roles_confirmed"] = True
        checkpoint["column_roles_confirmed_at"] = datetime.utcnow().isoformat()
        if user_id is not None:
            checkpoint["column_roles_confirmed_by"] = user_id
        an.checkpoint = make_json_safe(checkpoint)

        for col, meta in columns_meta.items():
            prof = profile_by_col.get(col) or (
                self.db.query(SemanticProfile)
                .filter(
                    SemanticProfile.analysis_id == analysis_id,
                    SemanticProfile.column_name == col,
                )
                .first()
            )
            if not prof:
                continue
            tags = dict(prof.contextual_tags or {})
            tags["analysis_role"] = meta.get("analysis_role")
            tags["role_confidence"] = meta.get("role_confidence")
            tags["role_source"] = meta.get("role_source")
            tags["role_reason"] = meta.get("role_reason")
            prof.contextual_tags = make_json_safe(tags)

        df, _, _ = load_working_dataframe(self.db, analysis_id, apply_user_norm=True)
        schema = infer_schema(df)
        state = AnalysisState(
            dataset_id=an.dataset_id,
            analysis_id=analysis_id,
            semantic_profile={"columns": columns_meta},
            schema_graph=checkpoint.get("schema_graph") or {},
            dependency_graph=checkpoint.get("priority_dependencies") or {},
            inferred_dataset_context=checkpoint.get("dataset_context") or {},
            column_normalization=checkpoint.get("column_normalization") or [],
        )
        rerun_validation_intel(df, schema, state)
        Phase3PersistenceService(self.db).persist_validation_only(state)
        invalidate_analysis_cache(analysis_id)
        self.db.commit()

        return {
            "success": True,
            "analysis_id": analysis_id,
            "column_roles_confirmed": True,
            "validation_candidates": len(state.validation_candidates or []),
            "identifier_count": sum(
                1 for m in columns_meta.values() if m.get("analysis_role") == "identifier"
            ),
            "variable_count": sum(
                1 for m in columns_meta.values() if m.get("analysis_role") == "variable"
            ),
        }
