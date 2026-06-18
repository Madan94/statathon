"""
STEP 0-PRE — LLM Column Name Enrichment.

Before semantic matching, cryptic column names (ASI block codes like 'J11',
'HI3', survey codes like 'fsu_serial_no', 'mult', etc.) are expanded into
meaningful English phrases so that the embedding and keyword signals fire
correctly.

Strategy:
  1. Identify "cryptic" columns — those whose normalized text has little
     semantic content (short, all digits, coded patterns).
  2. Batch-call LLM once per dataset with usecase context.
  3. For each enriched column, replace `normalized` and `representation` in the
     ColumnFeature so the rest of the pipeline sees rich text.
  4. If LLM is unavailable, fall back to a built-in lookup table that covers
     the most common MoSPI / ASI / PLFS / HCES codes.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from semantic_mapping_v2.feature_extraction import ColumnFeature
from semantic_mapping_v2.llm_client import generate_text, llm_configured, strip_json_fence

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[a-z]+", re.I)

# ---------------------------------------------------------------------------
# Static fallback lookup: code pattern → human description
# Covers ASI block letters, PLFS/HCES admin fields, common codes.
# ---------------------------------------------------------------------------
_STATIC_LOOKUP: dict[str, str] = {
    # ASI block codes
    "yr": "reference year",
    "blk": "ASI block identifier",
    "ae01": "enterprise type classification code",
    "aj01": "administrative identifier",
    "ah01": "raw material input item",
    # Block H — inputs (HI1-HI7)
    "hi1": "raw material input item 1 name",
    "hi2": "raw material input item 2 name",
    "hi3": "raw material input cost value",
    "hi4": "raw material input quantity",
    "hi5": "raw material source domestic or imported",
    "hi6": "raw material expenditure",
    "hi7": "raw material input item 7",
    # Block J — products sold (J11-J113)
    "j11": "product sold item 1 name",
    "j12": "product sold item 1 quantity",
    "j13": "product sold item 1 value",
    "j14": "product sold item 2 name",
    "j15": "product sold item 2 quantity",
    "j16": "product sold item 2 value",
    "j17": "product sold item 3 name",
    "j18": "product sold item 3 quantity",
    "j19": "product sold item 3 value",
    "j110": "product sold item 4 value",
    "j111": "product sold item 4 name",
    "j112": "product sold item 4 quantity",
    "j113": "product sold item 4 unit",
    # General PLFS/HCES survey admin
    "fsu_serial_no": "first stage unit serial number identifier",
    "fsu": "first stage unit sampling unit",
    "fod_sub_region": "field operations division sub region geography",
    "nss_region": "national sample survey region",
    "second_stage_stratum_no": "second stage stratum number survey",
    "sub_stratum": "survey sub stratum classification",
    "sub_sample": "survey sub sample replication",
    "sample_su_no": "sample secondary unit number identifier",
    "sample_sub_division_no": "sample sub division number identifier",
    "sample_household_no": "sample household serial number",
    "sample_hhld_no": "sample household number",
    "questionnaire_no": "questionnaire number survey metadata",
    "multiplier": "survey expansion multiplier weight",
    "mult": "survey multiplier expansion weight",
    "canvass_time_minutes": "time taken to canvass survey in minutes",
    "response_code": "survey response code status",
    "substitution_reason": "reason for household substitution",
    "reason_for_substitution_code": "reason code for household substitution",
    "survey_code": "survey code metadata",
    "schedule_id": "survey schedule identifier",
    "informant_sl_no": "informant serial number identifier",
    "psu_code": "primary sampling unit code identifier",
    "survey_wave_year": "survey wave year reference period",
    # HCES-specific ration / online columns
    "ration_any_item_last_30_days": "received any ration item in last 30 days",
    "ration_rice": "ration rice quantity from PDS food expenditure",
    "ration_wheat": "ration wheat quantity from PDS food expenditure",
    "ration_coarse_grain": "ration coarse grain from PDS food expenditure",
    "ration_sugar": "ration sugar quantity from PDS food expenditure",
    "ration_pulses": "ration pulses from PDS food expenditure",
    "ration_edible_oil": "ration edible oil from PDS food expenditure",
    "ration_other_food_items": "ration other food items from PDS",
    "online_groceries": "online purchased groceries food expenditure",
    "online_milk": "online milk purchase food expenditure",
    "online_vegetables": "online vegetables purchase food expenditure",
    "online_fresh_fruits": "online fresh fruits purchase food expenditure",
    "online_dry_fruits": "online dry fruits purchase food expenditure",
    "online_egg_fish_meat": "online egg fish meat purchase food expenditure",
    "online_served_processed_food": "online served or processed food purchase",
    "online_packed_processed_food": "online packed processed food expenditure",
    "online_other_food_items": "online other food items expenditure",
    "ceremony_performed_last_30_days": "ceremony performed in last 30 days household",
    "meals_served_to_non_hh_members": "meals served to non household members",
    # HCES beneficiary / scheme / social protection columns (LEVEL-07)
    "kerosene_ration_card": "kerosene ration card welfare scheme beneficiary",
    "lpg_subsidy_received": "LPG subsidy received welfare scheme beneficiary",
    "lpg_subsidized_cylinders": "LPG subsidized cylinders social welfare beneficiary",
    "free_electricity": "free electricity social welfare scheme beneficiary",
    "any_member_attended_school": "any household member attended school education",
    "num_govt_school_attended": "number of members attending government school education",
    "num_private_school_attended": "number attending private school education",
    "free_textbooks_received": "free textbooks received government scheme education beneficiary",
    "total_textbooks": "total textbooks education",
    "free_stationery_received": "free stationery received education scheme beneficiary",
    "total_stationery": "total stationery education",
    "free_school_bag_received": "free school bag scheme beneficiary education",
    "total_school_bags": "total school bags education",
    "free_other_items_received": "free other items education scheme beneficiary",
    "total_other_items": "total other items",
    "fee_waiver_received": "fee waiver received education scheme beneficiary",
    "num_fee_waiver_received": "number fee waiver beneficiaries education",
    "ayushman_beneficiary": "Ayushman Bharat health scheme beneficiary medical",
    "num_ayushman_beneficiaries": "number of Ayushman health scheme beneficiaries",
    "hospitalization_case": "hospitalization medical health case",
    "medical_benefit_received": "medical benefit received health scheme beneficiary",
    "num_medical_beneficiaries": "number medical benefit beneficiaries health",
    "medical_benefit_amount": "medical benefit amount expenditure health",
    "online_purchase_fuel_light": "online purchase fuel light non food expenditure",
    "online_purchase_toilet_articles": "online purchase toilet articles non food expenditure",
    "online_purchase_education": "online purchase education expenditure beneficiary",
    "online_purchase_medicine": "online purchase medicine health expenditure",
    "online_purchase_services": "online purchase services expenditure",
    # HCES LEVEL-01 / LEVEL-03 misc
    "survey_name": "survey name metadata identifier",
    "level": "survey level section metadata",
    "year": "year reference period survey metadata",
}

# Regex for obviously cryptic names: pure codes like J11, HI3, AJ01, or short all-caps
_CRYPTIC_RE = re.compile(r"^[a-zA-Z]{1,3}\d{1,3}$")


def _is_cryptic(col: str, normalized: str) -> bool:
    """Return True if the column name has too little semantic content."""
    n = col.strip().lower()
    # Pure block codes
    if _CRYPTIC_RE.match(n):
        return True
    # Very short names (≤3 chars)
    if len(n.replace("_", "")) <= 3:
        return True
    # Normalized produces ≤2 meaningful words with very short total length
    words = [w for w in normalized.split() if len(w) > 1]
    if len(words) <= 1 and len(normalized.replace(" ", "")) <= 5:
        return True
    return False


def _lookup(col: str) -> str | None:
    """Check static lookup table (normalized key)."""
    key = col.strip().lower()
    if key in _STATIC_LOOKUP:
        return _STATIC_LOOKUP[key]
    # Try without underscores for exact code match
    bare = key.replace("_", "")
    if bare in _STATIC_LOOKUP:
        return _STATIC_LOOKUP[bare]
    return None


# ---------------------------------------------------------------------------
# LLM expansion
# ---------------------------------------------------------------------------
_CHUNK = int(os.getenv("SEMV2_ENRICH_BATCH_SIZE", "20"))


def _enrich_via_llm(
    columns: list[tuple[str, ColumnFeature]],
    usecase: str,
    dataset_name: str,
) -> dict[str, str]:
    """Call LLM to get one-line English descriptions for cryptic columns.
    Returns {col_name: description}."""
    if not llm_configured():
        return {}

    out: dict[str, str] = {}
    for start in range(0, len(columns), _CHUNK):
        chunk = columns[start : start + _CHUNK]
        items = [
            {
                "column": c,
                "dtype": feat.dtype,
                "samples": [str(v)[:20] for v in feat.samples[:3]],
            }
            for c, feat in chunk
        ]
        prompt = (
            f"Dataset: '{dataset_name}' (usecase: {usecase}, source: MoSPI India official statistics).\n"
            f"Expand each column code into a short English phrase (5-10 words) describing what it measures.\n"
            f"COLUMNS: {json.dumps(items, ensure_ascii=True)}\n"
            f'Return JSON only: {{"expansions":[{{"column":"...","description":"short phrase"}}]}}'
        )
        try:
            raw = generate_text(prompt, system="Return valid JSON only.")
            data = json.loads(strip_json_fence(raw))
            if isinstance(data, dict):
                data = data.get("expansions") or []
            for entry in data or []:
                if isinstance(entry, dict) and entry.get("column") and entry.get("description"):
                    out[str(entry["column"]).strip()] = str(entry["description"]).strip()
        except Exception as exc:
            logger.debug("LLM column enrichment chunk failed: %s", exc)
    return out


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def enrich_column_features(
    features: dict[str, ColumnFeature],
    *,
    usecase: str,
    dataset_name: str,
    use_llm: bool = True,
) -> tuple[dict[str, ColumnFeature], dict[str, int]]:
    """
    Mutate ColumnFeature.normalized and .representation in-place for columns
    that are cryptic or known survey codes.

    The LLM is the PRIMARY, dataset-agnostic enrichment layer: it expands any
    cryptic code using usecase + sample-value context, so this generalises to
    datasets we have never seen. The static lookup table is only a FALLBACK,
    used when the LLM is unavailable (no key / quota exhausted / offline) or
    returns nothing for a given column.
    Returns the same dict (mutated in-place).
    """
    # Candidates needing help: cryptic names OR known coded survey fields.
    candidates: list[tuple[str, ColumnFeature]] = [
        (col, feat)
        for col, feat in features.items()
        if _is_cryptic(col, feat.normalized) or _lookup(col) is not None
    ]
    if not candidates:
        return features, {"llm_enriched": 0, "lookup_enriched": 0, "enriched_total": 0}

    # PRIMARY — LLM enrichment (works for any dataset, not just known codes).
    llm_desc: dict[str, str] = {}
    if use_llm and llm_configured():
        llm_desc = _enrich_via_llm(candidates, usecase, dataset_name)

    # Apply: prefer the LLM description, fall back to the static lookup table.
    enriched_count = llm_used = lookup_used = 0
    for col, feat in candidates:
        desc = llm_desc.get(col)
        source = "llm"
        if not desc:
            desc = _lookup(col)
            source = "lookup"
        if desc:
            _apply(feat, desc, source)
            enriched_count += 1
            if source == "llm":
                llm_used += 1
            else:
                lookup_used += 1

    if enriched_count:
        logger.info(
            "Column enrichment: %d/%d expanded (dataset=%s, llm=%d, lookup=%d)",
            enriched_count,
            len(features),
            dataset_name,
            llm_used,
            lookup_used,
        )
    return features, {
        "llm_enriched": llm_used,
        "lookup_enriched": lookup_used,
        "enriched_total": enriched_count,
    }


def _apply(feat: ColumnFeature, description: str, source: str) -> None:
    """Replace normalized + representation with richer description."""
    feat.normalized = description
    # Rebuild representation with enriched text
    parts = [description, f"type {feat.dtype}"]
    if feat.samples:
        parts.append("values " + ", ".join(str(s)[:20] for s in feat.samples[:4]))
    feat.representation = ". ".join(parts)
