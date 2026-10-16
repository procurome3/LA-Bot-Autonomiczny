#!/usr/bin/env python3
"""Validate the facts-only Legendary/Mythical Live Arena database."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Mapping

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "champion_database.json"

FORBIDDEN_KEYS = {
    "tier", "tier_rank", "tier_rating", "rating", "ratings", "overall_user",
    "arena_rating", "live_arena_rating", "win_rate", "pick_rate", "ban_rate",
    "book_value", "dungeon_overall", "clan_boss", "hydra", "chimera",
}
RAW_PROSE_KEYS = {"description", "skill_description", "raw_description", "raw_html", "page_text"}


def analyze_database(db):
    """Check real skill identity/layout, separately from semantic review flags."""
    errors, coverage, review = [], [], []
    champs = db.get("champions", {})
    if not isinstance(champs, Mapping):
        return {"errors": [{"code": "champions_not_mapping"}], "coverage_gaps": [], "semantic_review": []}
    def error(path, code):
        errors.append({"path": path, "code": code})
    for ck, champion in champs.items():
        if not isinstance(champion, Mapping):
            error(str(ck), "invalid_champion_record")
            continue
        forms = champion.get("forms") or {}
        for required in (["base", "alternate"] if champion.get("rarity") == "mythical" else ["base"]):
            if skill_count(champion, required) < 2:
                coverage.append({"champion": ck, "form": required})
        for form, data in forms.items():
            skills = data.get("skills", {})
            if not isinstance(skills, Mapping):
                error(f"{ck}.{form}", "invalid_skill_mapping")
                continue
            names = set()
            ids = set()
            for sid, skill in skills.items():
                path = f"{ck}.{form}.{sid}"
                if not isinstance(skill, Mapping):
                    error(path, "invalid_skill_record")
                    continue
                name = re.sub(r"[^a-z0-9]", "", str(skill.get("name", "")).lower())
                if name in names:
                    if str(sid).startswith("P"):
                        review.append({"path": path, "flags": ["same_name_passive_variants_in_source"]})
                    else:
                        error(path, "duplicate_skill_name_same_form")
                names.add(name)
                active = bool(re.fullmatch(r"A[1-4]", str(sid)))
                passive = bool(re.fullmatch(r"P\d*", str(sid)))
                if not (active or passive or sid == "AURA"):
                    error(path, "invalid_or_ambiguous_skill_slot")
                if (passive or sid == "AURA") and skill.get("clickable") is True:
                    error(path, "passive_or_aura_is_clickable")
                if active and ("passive" in str(skill.get("source_skill_type", "")).lower() or re.search(r"\[\s*p\s*\]", str(skill.get("name", "")), re.I)):
                    error(path, "passive_in_active_slot")
                base, booked = skill.get("cooldown_base"), skill.get("cooldown_booked")
                if isinstance(base, (int, float)) and isinstance(booked, (int, float)) and not 0 <= booked <= base:
                    error(path, "inconsistent_cooldowns")
                source_id = skill.get("source_skill_id")
                if source_id is not None:
                    if str(source_id) in ids:
                        error(path, "duplicate_source_skill_id")
                    ids.add(str(source_id))
                for effect in skill.get("effects", []):
                    if effect.get("name", "").lower() in {"passive effect", "active effect"}:
                        error(path, "section_label_is_effect")
                    if effect.get("name") in {"taunt", "poison cloud", "shatter"} and effect.get("kind") == "debuff":
                        error(path, "known_buff_classified_as_debuff")
                    for key in ("chance_percent", "chance_booked_percent"):
                        value = effect.get(key)
                        if value is not None and (not isinstance(value, (int, float)) or not 0 <= value <= 100):
                            error(path, "invalid_effect_chance")
                if skill.get("review_flags"):
                    review.append({"path": path, "flags": skill["review_flags"]})
            expected = {str(x) for x in data.get("expected_skill_ids", [])}
            if expected and ids != expected:
                error(f"{ck}.{form}", "source_skill_id_set_mismatch")
            requested = {str(x) for x in data.get("requested_skill_ids", [])}
            if requested and not ids.issubset(requested):
                error(f"{ck}.{form}", "skill_not_in_selected_game_form")
    for parent, key, value in walk(db):
        if key.lower() in FORBIDDEN_KEYS:
            error(f"{parent}.{key}", "forbidden_ranking_field")
        if key.lower() in RAW_PROSE_KEYS:
            error(f"{parent}.{key}", "raw_source_prose_stored")
    declared = db.get("meta", {}).get("roster_count")
    if declared is not None and declared != len(champs):
        error("meta.roster_count", "stale_roster_count")
    return {"errors": errors, "coverage_gaps": coverage, "semantic_review": review,
            "structurally_valid": not errors, "coverage_complete": not coverage,
            "semantics_exhaustively_verified": False}


def walk(obj, path="root"):
    if isinstance(obj, Mapping):
        for k, v in obj.items():
            yield path, str(k), v
            yield from walk(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk(v, f"{path}[{i}]")


def skill_count(record: Mapping[str, object], form: str) -> int:
    forms = record.get("forms") or {}
    if not isinstance(forms, Mapping):
        return 0
    data = forms.get(form) or {}
    if not isinstance(data, Mapping):
        return 0
    skills = data.get("skills", data)
    return len(skills) if isinstance(skills, Mapping) else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--database", default=str(DEFAULT_DB))
    ap.add_argument("--allow-partial", action="store_true")
    ap.add_argument("--report", help="Write a machine-readable validation report")
    args = ap.parse_args()

    path = Path(args.database)
    try:
        db = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print("INVALID JSON:", exc)
        return 2

    champs = db.get("champions") or {}
    if not isinstance(champs, Mapping):
        print("INVALID: champions is not a mapping")
        return 2

    counts = {"total": 0, "legendary": 0, "mythical": 0, "detailed": 0, "partial": 0, "pending": 0}
    audit = analyze_database(db)
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    missing_forms = []
    low_skill_records = []
    for key, rec in champs.items():
        if not isinstance(rec, Mapping):
            continue
        rarity = str(rec.get("rarity") or "").lower()
        if rarity not in {"legendary", "mythical"}:
            continue
        counts["total"] += 1
        counts[rarity] += 1
        status = str(rec.get("status") or "index_only")
        if status in {"detailed", "detailed_seed"}:
            counts["detailed"] += 1
        elif status == "partial":
            counts["partial"] += 1
        else:
            counts["pending"] += 1

        base = skill_count(rec, "base")
        alt = skill_count(rec, "alternate")
        if base < 2:
            low_skill_records.append((key, "base", base))
        if rarity == "mythical":
            if alt < 2:
                missing_forms.append((key, base, alt))

    forbidden = []
    raw_prose = []
    for parent, key, _ in walk(db):
        low = key.lower()
        if low in FORBIDDEN_KEYS:
            forbidden.append(f"{parent}.{key}")
        if low in RAW_PROSE_KEYS:
            raw_prose.append(f"{parent}.{key}")

    print("=== Champion DB validation ===")
    print(json.dumps(counts, ensure_ascii=False))
    print(f"Mythical missing/weak alternate form: {len(missing_forms)}")
    if missing_forms:
        for row in missing_forms[:40]:
            print("  ", row)
    print(f"Records with weak base skill coverage: {len(low_skill_records)}")
    if low_skill_records:
        for row in low_skill_records[:40]:
            print("  ", row)
    print(f"Forbidden ranking/rating fields stored: {len(forbidden)}")
    if forbidden:
        for p in forbidden[:40]:
            print("  ", p)
    print(f"Raw source-prose fields stored: {len(raw_prose)}")
    if raw_prose:
        for p in raw_prose[:40]:
            print("  ", p)

    print(f"Structural/mechanical validation errors: {len(audit['errors'])}")
    for issue in audit['errors'][:30]:
        print("  ", issue)
    print(f"Skills with conditional/special mechanics requiring semantic review: {len(audit['semantic_review'])}")
    hard_fail = bool(forbidden or raw_prose or low_skill_records or missing_forms or audit['errors'])
    if args.allow_partial:
        hard_fail = bool(forbidden or raw_prose or audit['errors'])
    if hard_fail:
        print("RESULT: INCOMPLETE/INVALID")
        return 1
    if args.allow_partial and (missing_forms or low_skill_records):
        print("RESULT: POLICY_OK_COVERAGE_INCOMPLETE")
        return 0
    print("RESULT: COVERAGE_AND_STRUCTURE_OK; semantic review is separate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
