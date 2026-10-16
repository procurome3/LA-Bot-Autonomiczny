#!/usr/bin/env python3
"""Fast facts-only Legendary/Mythical kit updater for Live Arena V16.4.

Primary source is the public HellHades champion + skill API.  We deliberately
read only factual identity/kit fields and discard every tier/rating/statistical
ranking field.  Mythical alternate forms are enriched from factual skill
sections on the champion page, with a Gacha.gg factual skill-page fallback.

The output never stores full third-party prose.  Descriptions are parsed in
memory into normalized mechanics (targets, cooldowns, effects, durations,
chances, TM, revive, strip, cleanse, lockout, transform, etc.).
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import datetime, timezone
from html import unescape
import json
from pathlib import Path
import re
import sys
import threading
import time
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlencode

try:
    import requests
    from bs4 import BeautifulSoup, Tag
except Exception as exc:
    print("Missing dependency:", exc)
    print("Run: py -m pip install -r requirements_livearena.txt")
    raise SystemExit(2)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from champion_database import canonical_key  # noqa: E402
from tools.update_champion_database import (  # noqa: E402
    HEADERS,
    DB_PATH,
    ROSTER_PATH,
    build_empty_db,
    candidate_urls,
    extract_skill_blocks,
    page_metadata,
    parse_skill,
    write_atomic,
)
from tools.champion_skill_facts import PARSER_VERSION, split_books  # noqa: E402
from tools.validate_champion_database import analyze_database  # noqa: E402

API_PARSER_VERSION = "hellhades_api_v5"

HH_CHAMPIONS_API = "https://hellhades.com/wp-json/hh-api/v3/champions?mode=all"
HH_SKILLS_API = "https://hellhades.com/wp-json/hh-api/v3/raid/skills/{id}"
HH_FORMS_API = "https://hellhades.com/wp-json/hh-api/v3/raid/forms/{model}"
HH_LIVE_SKILLS_API = "https://hellhades.com/wp-json/hh-api/v3/skills"
GACHA_BASE = "https://www.gacha.gg/raid-shadow-legends/characters"
REPORT_PATH = ROOT / "data" / "champion_database_update_report.json"
CACHE_DIR = ROOT / "data" / "champion_api_cache"

# Current HH faction identifiers -> canonical runtime labels.
HH_FACTIONS = {
    "banner-lords": "Banner Lords",
    "bannerlords": "Banner Lords",
    "high-elves": "High Elves",
    "the-sacred-order": "Sacred Order",
    "sacred-order": "Sacred Order",
    "barbarians": "Barbarians",
    "ogryn-tribes": "Ogryn Tribes",
    "lizardmen": "Lizardmen",
    "skinwalkers": "Skinwalkers",
    "orcs": "Orcs",
    "demonspawn": "Demonspawn",
    "undead-hordes": "Undead Hordes",
    "dark-elves": "Dark Elves",
    "knight-revenant": "Knights Revenant",
    "knights-revenant": "Knights Revenant",
    "dwarves": "Dwarves",
    "shadowkin": "Shadowkin",
    "sylvan-watchers": "Sylvan Watchers",
    "argonites": "Argonites",
}
HH_ROLES = {"atk": "attack", "def": "defense", "supp": "support", "hp": "hp"}

# We keep only these fields from the HH champion index.  Ratings, tier scores,
# pick/win/ban rates, book value and every editorial metric are intentionally
# absent from this allow-list.
HH_IDENTITY_FIELDS = {
    "id", "heroId", "shortname", "champion", "affinity_index",
    "faction_index", "rarity", "role", "url",
}

_LOCK = threading.Lock()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return deepcopy(default)


def strip_html(value: object) -> str:
    text = unescape(str(value or ""))
    text = BeautifulSoup(text, "html.parser").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()


def norm_name(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def gacha_slug(name: object) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(name or "").lower()).strip("-")


def safe_int(value: object) -> Optional[int]:
    try:
        if value in (None, ""):
            return None
        return int(float(str(value).strip()))
    except Exception:
        return None


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    s.headers["Accept"] = "application/json,text/plain,text/html,*/*"
    return s


def get_json(session: requests.Session, url: str, timeout: float, retries: int = 3):
    last = "unknown error"
    for attempt in range(max(1, retries)):
        try:
            r = session.get(url, timeout=timeout)
            if r.status_code == 200:
                return r.json(), None
            last = f"HTTP {r.status_code}"
        except Exception as exc:
            last = str(exc)
        if attempt + 1 < retries:
            time.sleep(0.7 * (attempt + 1))
    return None, last


def get_text(session: requests.Session, url: str, timeout: float, retries: int = 2):
    last = "unknown error"
    for attempt in range(max(1, retries)):
        try:
            r = session.get(url, timeout=timeout)
            if r.status_code == 200 and len(r.text) > 500:
                return r.text, r.url, None
            last = f"HTTP {r.status_code}"
        except Exception as exc:
            last = str(exc)
        if attempt + 1 < retries:
            time.sleep(0.7 * (attempt + 1))
    return None, None, last


def _identity_only(row: Mapping[str, object]) -> dict:
    return {k: row.get(k) for k in HH_IDENTITY_FIELDS if k in row}


def fetch_hh_index(session: requests.Session, timeout: float, cache: bool = True) -> Tuple[List[dict], Optional[str]]:
    data, err = get_json(session, HH_CHAMPIONS_API, timeout, retries=3)
    if data is None:
        cache_path = CACHE_DIR / "hh_champions_identity.json"
        cached = load_json(cache_path, [])
        return ([x for x in cached if isinstance(x, Mapping)], err) if cached else ([], err)

    rows = data.get("champions", []) if isinstance(data, Mapping) else data
    clean = []
    if isinstance(rows, Sequence) and not isinstance(rows, (str, bytes)):
        for row in rows:
            if isinstance(row, Mapping):
                clean.append(_identity_only(row))
    if cache and clean:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        write_atomic(CACHE_DIR / "hh_champions_identity.json", clean)  # type: ignore[arg-type]
    return clean, None


def _api_match_maps(rows: Iterable[Mapping[str, object]]):
    by_key: Dict[str, Mapping[str, object]] = {}
    by_norm: Dict[str, Mapping[str, object]] = {}
    for row in rows:
        name = strip_html(row.get("champion") or row.get("shortname"))
        if not name:
            continue
        by_key[canonical_key(name)] = row
        by_norm[norm_name(name)] = row
    return by_key, by_norm


def find_api_champion(roster_row: Mapping[str, object], by_key, by_norm):
    candidates = [
        roster_row.get("key"), roster_row.get("name"), roster_row.get("hellhades_slug")
    ]
    for value in candidates:
        key = canonical_key(value)
        if key and key in by_key:
            return by_key[key]
    for value in candidates:
        n = norm_name(value)
        if n and n in by_norm:
            return by_norm[n]
    return None


def _book_count(text: str) -> int:
    return len(re.findall(r"(?:Lvl\.?|Level)\s*\d*\s*:?[\s\-]*Cooldown\s*-\s*1", text, re.I))


def _skill_sid(name: str, stype: str, active_index: int, seen: Mapping[str, object]) -> Tuple[str, int]:
    low = f"{name} {stype}".lower()
    if "aura" in low and "attack" not in low:
        return "AURA", active_index
    if "passive" in low or re.search(r"\[\s*p\s*\]", name, re.I):
        sid = "P" if "P" not in seen else f"P{1 + sum(1 for x in seen if x.startswith('P'))}"
        return sid, active_index
    m = re.search(r"(?:ability|skill)\s*([1-5])", stype, re.I)
    if m:
        idx = int(m.group(1))
        if idx >= 5:
            sid = "P" if "P" not in seen else f"P{1 + sum(1 for x in seen if x.startswith('P'))}"
            return sid, active_index
        return f"A{idx}", max(active_index, idx + 1)
    sid = f"A{active_index}"
    return sid, active_index + 1


def parse_api_skill_rows(rows: Sequence[Mapping[str, object]], form: str = "base") -> Dict[str, dict]:
    skills: Dict[str, dict] = {}
    active_index = 1
    seen_names = set()
    for row in rows:
        name = strip_html(row.get("name"))
        if not name:
            continue
        text = strip_html(row.get("description"))
        normalized_name = (norm_name(re.sub(r"\[\s*p\s*\]", "", name, flags=re.I)), text, str(row.get("cooldown", "")))
        if normalized_name in seen_names:
            continue  # HH sometimes repeats a row (e.g. Lazarius A2).
        seen_names.add(normalized_name)
        stype = strip_html(row.get("type"))
        book_rows = row.get("books") or []
        if isinstance(book_rows, Mapping):
            book_rows = list(book_rows.values())
        if book_rows and not re.search(r"\b(?:Level|Lvl\.?)\s*\d+\s*:", text, re.I):
            for index, book in enumerate(book_rows, 2):
                if isinstance(book, Mapping):
                    kind = str(book.get("type") or "")
                    amount = safe_int(book.get("amount"))
                    if amount is not None and kind in {"Cooldown", "Damage", "Buff/Debuff Chance", "Buff Chance", "Debuff Chance", "Heal"}:
                        text += f" Level {index}: {kind} {'-' if kind == 'Cooldown' else '+'}{amount}{'' if kind == 'Cooldown' else '%'}"
        if active_index > 4 and "A4" in skills and "transform" in skills["A4"].get("tags", []):
            # Some HH rows label a trailing mythical passive as Active.
            stype = "Passive"
        sid, active_index = _skill_sid(name, stype, active_index, skills)
        if sid in skills:
            sid = f"U{len(skills) + 1}"
        cooldown = safe_int(row.get("cooldown"))
        skill = parse_skill(name, text, sid, form)
        if cooldown is not None:
            skill["cooldown_base"] = cooldown
            _, books, _ = split_books(text)
            skill["cooldown_booked"] = max(0, cooldown - books)
        skill["source_skill_type"] = stype
        skill["book_upgrades"] = [
            {"kind": strip_html(book.get("type")), "amount": safe_int(book.get("amount"))}
            for book in book_rows if isinstance(book, Mapping)
        ]
        # Parameters are retained as references; a listed buff is not assumed
        # to be granted (it may instead be ignored, required or removed).
        abilities = row.get("abilities") or []
        if isinstance(abilities, list):
            skill["status_parameters"] = [
                {key: value for key, value in item.items() if key in {"effectid", "effect", "name", "type", "strength", "multiplier", "duration", "skilluse"}}
                for item in abilities if isinstance(item, Mapping)
            ]
        if safe_int(row.get("id")) not in (None, 0):
            skill["source_skill_id"] = str(row["id"])
        # Algebraic game formulas are factual data; never execute them as code.
        multipliers = row.get("multiplier") or []
        if isinstance(multipliers, list):
            skill["multipliers"] = [
                {key: value for key, value in item.items() if key in {"effectid", "kindid", "attacks", "multiplier", "target", "specialrules"}}
                for item in multipliers if isinstance(item, Mapping) and item.get("multiplier") is not None
            ]
        # No source prose is persisted; only normalized mechanics.
        skills[sid] = skill
    return skills


def parse_api_forms(payload) -> dict:
    """Preserve both nested arrays returned by the HH skill endpoint."""
    if isinstance(payload, Mapping):
        payload = payload.get("forms", payload.get("skills", payload))
        if isinstance(payload, Mapping):
            output = {}
            for name, group in payload.items():
                form = "alternate" if str(name).lower() in {"1", "alternate", "alt", "form2"} else "base"
                rows = group.get("skills", []) if isinstance(group, Mapping) else group
                if isinstance(rows, list):
                    output[form] = {"skills": parse_api_skill_rows(rows, form)}
            return output
    if not isinstance(payload, list) or not payload:
        return {}
    groups = [payload] if isinstance(payload[0], Mapping) else payload
    output = {}
    for index, rows in enumerate(groups[:2]):
        if isinstance(rows, list):
            form = "base" if index == 0 else "alternate"
            skills = parse_api_skill_rows([r for r in rows if isinstance(r, Mapping)], form)
            if skills:
                output[form] = {"skills": skills}
    return output


def fetch_hh_skills(session: requests.Session, hh_id: object, timeout: float) -> Tuple[List[dict], Optional[str]]:
    ident = safe_int(hh_id)
    if ident is None:
        return [], "missing HH id"
    data, err = get_json(session, HH_SKILLS_API.format(id=ident), timeout, retries=3)
    if data is None:
        return [], err
    return data, None


def fetch_live_kit(session: requests.Session, hh: Mapping[str, object], timeout: float):
    """Use the same form/skill identifiers as the current HH champion page.

    The legacy post-ID endpoint has stale names/types on some champions. The
    current page rounds the ascended hero ID to its model, selects ascension 6,
    and requests each form's explicit list of game skill IDs.
    """
    hero_id = safe_int(hh.get("heroId"))
    if not hero_id or hero_id < 0:
        return {}, "no live hero model"
    model = hero_id - hero_id % 10
    rows, err = get_json(session, HH_FORMS_API.format(model=model), timeout)
    if not isinstance(rows, list):
        return {}, err or "invalid live form response"
    selected = [x for x in rows if isinstance(x, Mapping) and safe_int(x.get("heroid")) == hero_id and str(x.get("form")) in {"1", "2"}]
    if not selected:
        return {}, "no matching ascension/form rows"
    forms, errors = {}, []
    for row in selected:
        form = "alternate" if str(row["form"]) == "2" else "base"
        ids = str(row.get("skills") or "")
        url = HH_LIVE_SKILLS_API + "?" + urlencode({"skills": ids, "model": row["model"], "heroid": row["heroid"]})
        payload, failure = get_json(session, url, timeout)
        if not isinstance(payload, list):
            errors.append(f"{form}: {failure or 'invalid live skills'}")
            continue
        skills = parse_api_skill_rows([x for x in payload if isinstance(x, Mapping)], form)
        if skills:
            requested_ids = [x.strip() for x in ids.split(",") if x.strip()]
            visible_ids = [str(x["id"]) for x in payload if isinstance(x, Mapping) and safe_int(x.get("id")) not in (None, 0)]
            forms[form] = {"skills": skills, "expected_skill_ids": visible_ids,
                           "requested_skill_ids": requested_ids,
                           "unexposed_skill_ids": sorted(set(requested_ids) - set(visible_ids)),
                           "source_model": str(model), "source_hero_id": str(hero_id), "source_url": url}
    if "base" in forms:
        auras, _ = get_json(session, f"https://hellhades.com/wp-json/hh-api/v3/raid/auras/{hero_id}?mode=hero", timeout, retries=1)
        if isinstance(auras, list):
            forms["base"]["auras"] = [{k: x[k] for k in ("type", "strength", "location", "rules", "faction") if k in x} for x in auras if isinstance(x, Mapping)]
    return forms, "; ".join(errors) or None


def _leaf_text_between(start: Tag, stop_names: Tuple[str, ...] = ("h2", "h3")) -> str:
    bits: List[str] = []
    seen = set()
    for el in start.find_all_next():
        if el is start:
            continue
        if el.name in stop_names:
            break
        if el.name in ("script", "style", "svg", "img"):
            continue
        # Prefer leaf-ish visible elements to avoid repeating container text.
        if el.find(["p", "li", "div", "span"], recursive=False):
            continue
        txt = re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip()
        if txt and txt not in seen:
            seen.add(txt)
            bits.append(txt)
    return " ".join(bits)


def parse_gacha_skill_page(html: str) -> Dict[str, Dict[str, dict]]:
    """Parse factual Skills section from gacha.gg, including mythical forms.

    This is a fallback only for missing mythical alternate forms. Rankings and
    tier text are outside the parsed section and are never read into the DB.
    """
    soup = BeautifulSoup(html, "html.parser")
    start = None
    for h in soup.find_all(["h2", "h3"]):
        if re.fullmatch(r"\s*Skills\s*", h.get_text(" ", strip=True), re.I):
            start = h
            break
    if start is None:
        return {}

    forms: Dict[str, Dict[str, dict]] = {"base": {}, "alternate": {}}
    active_by_form = {"base": 1, "alternate": 1}
    for h in start.find_all_next(["h2", "h3"]):
        if h is start:
            continue
        if h.name == "h2":
            title = re.sub(r"\s+", " ", h.get_text(" ", strip=True)).strip().lower()
            if title in {"art", "how to get", "ratings", "tier lists", "similar characters"} or "art" == title:
                break
        if h.name != "h3":
            continue
        name = re.sub(r"\s+", " ", h.get_text(" ", strip=True)).strip()
        if not name or len(name) > 100:
            continue
        body = _leaf_text_between(h)
        combined = f"{name} {body}"
        marker = re.search(r"Ability\s*([1-5])(?:\s*\(\s*Form\s*([12])\s*\))?", combined, re.I)
        passive_marker = re.search(r"Passive(?:\s*\(\s*Form\s*([12])\s*\))?", combined, re.I)
        aura_marker = re.search(r"\bAura\b", combined, re.I)
        if not (marker or passive_marker or aura_marker):
            continue
        form_num = None
        if marker:
            form_num = marker.group(2)
        elif passive_marker:
            form_num = passive_marker.group(1)
        form = "alternate" if form_num == "2" else "base"
        skills = forms[form]
        if aura_marker and not marker and not passive_marker:
            sid = "AURA"
        elif passive_marker:
            sid = "P" if "P" not in skills else f"P{1 + sum(1 for x in skills if x.startswith('P'))}"
        elif marker:
            idx = int(marker.group(1))
            if idx >= 5:
                sid = "P" if "P" not in skills else f"P{1 + sum(1 for x in skills if x.startswith('P'))}"
            else:
                sid = f"A{idx}"
                active_by_form[form] = max(active_by_form[form], idx + 1)
        else:
            continue
        if sid in skills:
            continue
        cooldown = None
        cm = re.search(r"Cooldown\s*(\d+)\s*turn", combined, re.I)
        if cm:
            cooldown = int(cm.group(1))
        # Remove UI marker only; parse the remaining factual mechanics in RAM.
        mechanics = re.sub(r"Ability\s*[1-5](?:\s*\(\s*Form\s*[12]\s*\))?", " ", body, flags=re.I)
        mechanics = re.sub(r"Passive(?:\s*\(\s*Form\s*[12]\s*\))?", " ", mechanics, flags=re.I)
        mechanics = re.sub(r"Cooldown\s*\d+\s*turns?", " ", mechanics, flags=re.I)
        mechanics = re.sub(r"\s+", " ", mechanics).strip()
        skill = parse_skill(name, mechanics, sid, form)
        if cooldown is not None:
            skill["cooldown_base"] = cooldown
            skill["cooldown_booked"] = max(0, cooldown - split_books(mechanics)[1])
        skill["source_skill_type"] = "gacha_skill_section"
        skills[sid] = skill
    return {k: {"skills": v} for k, v in forms.items() if v}


def parse_hh_mythical_page(html: str) -> Dict[str, Dict[str, dict]]:
    soup = BeautifulSoup(html, "html.parser")
    blocks = extract_skill_blocks(soup)
    if not blocks:
        return {}
    by_form: Dict[str, List[Tuple[str, str]]] = {}
    for form, name, text in blocks:
        by_form.setdefault(form, []).append((name, text))
    out: Dict[str, Dict[str, dict]] = {}
    for form, entries in by_form.items():
        skills = parse_api_skill_rows([{"name": name, "description": text} for name, text in entries], form)
        if skills:
            out[form] = {"skills": skills}
    return out


def _forms_skill_count(forms: Mapping[str, object]) -> int:
    total = 0
    for form in forms.values():
        if isinstance(form, Mapping):
            sk = form.get("skills", form)
            if isinstance(sk, Mapping):
                total += len(sk)
    return total


def _has_alternate(forms: Mapping[str, object]) -> bool:
    alt = forms.get("alternate") if isinstance(forms, Mapping) else None
    return isinstance(alt, Mapping) and bool(alt.get("skills", alt))


def merge_forms(primary: Mapping[str, object], fallback: Mapping[str, object]) -> dict:
    out = deepcopy(dict(primary))
    for form_name, form_data in fallback.items():
        if not isinstance(form_data, Mapping):
            continue
        fskills = form_data.get("skills", form_data)
        if not isinstance(fskills, Mapping):
            continue
        current = out.setdefault(form_name, {"skills": {}})
        if not isinstance(current, Mapping):
            current = {"skills": {}}; out[form_name] = current
        cskills = current.setdefault("skills", {})  # type: ignore[union-attr]
        for sid, skill in fskills.items():
            if sid not in cskills:
                cskills[sid] = deepcopy(skill)
    return out


def mythical_enrichment(session: requests.Session, row: Mapping[str, object], hh: Mapping[str, object], timeout: float) -> Tuple[dict, str]:
    # 1) HellHades individual page: preferred because the user selected HH as
    # the canonical source. It may include both form sections.
    urls = []
    if hh.get("url"):
        urls.append(str(hh.get("url")))
    urls.extend(candidate_urls(row))
    seen = set()
    for url in urls:
        if not url or url in seen:
            continue
        seen.add(url)
        html, _, _ = get_text(session, url, timeout, retries=2)
        if html:
            forms = parse_hh_mythical_page(html)
            if _has_alternate(forms):
                return forms, "hellhades_page"
    # 2) Factual Skills section on gacha.gg as fallback for alternate form.
    name = row.get("name") or hh.get("champion")
    gurl = f"{GACHA_BASE}/{gacha_slug(name)}"
    html, _, _ = get_text(session, gurl, timeout, retries=2)
    if html:
        forms = parse_gacha_skill_page(html)
        if forms:
            return forms, "gacha_skill_section"
    return {}, "none"


def normalized_record_from_api(existing: Mapping[str, object], roster_row: Mapping[str, object], hh: Mapping[str, object], forms: Mapping[str, object], source_note: str) -> dict:
    rec = dict(existing)
    name = strip_html(hh.get("champion") or roster_row.get("name"))
    rec.update({
        "name": name or roster_row.get("name"),
        "key": canonical_key(roster_row.get("key") or name),
        "rarity": str(hh.get("rarity") or roster_row.get("rarity") or "").lower(),
        "affinity": str(hh.get("affinity_index") or rec.get("affinity") or "").lower(),
        "faction": HH_FACTIONS.get(str(hh.get("faction_index") or "").lower(), str(roster_row.get("faction") or rec.get("faction") or "")),
        "role": HH_ROLES.get(str(hh.get("role") or "").lower(), str(hh.get("role") or rec.get("role") or "").lower()),
        "source_url": str(hh.get("url") or rec.get("source_url") or ""),
        "source_updated_at": "",  # The API does not expose a publication date.
        "fetched_at": utc_now(),
        "forms": deepcopy(dict(forms)),
        "parser": API_PARSER_VERSION,
        "data_source": source_note,
        "updated_at": utc_now(),
    })
    rarity = rec["rarity"]
    count = _forms_skill_count(forms)
    if rarity == "mythical":
        rec["status"] = "detailed" if count >= 7 and _has_alternate(forms) else ("partial" if count >= 3 else "fetch_failed")
    else:
        rec["status"] = "detailed" if count >= 2 else ("partial" if count else "fetch_failed")
    rec.pop("last_error", None)
    affinity = rec["affinity"]
    rec["affinity_group"] = "void" if affinity == "void" else "nonvoid" if affinity else ""
    if "base" in rec["forms"] and "auras" in rec["forms"]["base"]:
        rec["auras"] = rec["forms"]["base"].pop("auras")
    rec["mechanics_validation"] = "parsed_not_exhaustively_verified"
    audit = analyze_database({"champions": {rec["key"]: rec}})
    if audit["errors"]:
        rec["status"] = "partial"
        rec["validation_errors"] = audit["errors"]
    else:
        rec.pop("validation_errors", None)
    return rec


def _refresh_roster_identity(roster: dict, hh_rows: Sequence[Mapping[str, object]], rarities: set[str]) -> dict:
    """Update/add Legendary/Mythical roster identities from HH without ratings."""
    by_key = {}
    for source in roster.get("champions", []):
        if isinstance(source, Mapping):
            row = dict(source)
            row["key"] = canonical_key(row.get("key") or row.get("name"))
            by_key[row["key"]] = row
    rows = list(by_key.values())
    for hh in hh_rows:
        rarity = str(hh.get("rarity") or "").lower()
        if rarity not in rarities:
            continue
        name = strip_html(hh.get("champion") or hh.get("shortname"))
        if not name:
            continue
        key = canonical_key(name)
        row = by_key.get(key)
        if row is None:
            row = {"name": name, "key": key, "rarity": rarity}
            rows.append(row); by_key[key] = row
        row["name"] = name
        row["key"] = key
        row["rarity"] = rarity
        if hh.get("url"):
            m = re.search(r"/raid/champions/([^/?#]+)/?", str(hh.get("url")), re.I)
            if m:
                row["hellhades_slug"] = m.group(1)
        row["faction"] = HH_FACTIONS.get(str(hh.get("faction_index") or "").lower(), row.get("faction", ""))
    roster = dict(roster)
    roster["champions"] = rows
    roster["generated_from"] = "HellHades public champion identity API; ratings/tier fields discarded"
    roster["api_identity_refreshed_at"] = utc_now()
    roster["counts"] = {
        "total": sum(1 for x in rows if str(x.get("rarity") or "").lower() in rarities),
        "legendary": sum(1 for x in rows if str(x.get("rarity") or "").lower() == "legendary"),
        "mythical": sum(1 for x in rows if str(x.get("rarity") or "").lower() == "mythical"),
    }
    return roster


def canonicalize_existing_database(db: Mapping[str, object]) -> dict:
    """Collapse aliases without letting a partial alias erase a complete kit."""
    result = deepcopy(dict(db))
    canonical = {}
    def quality(record):
        return (record.get("parser") == API_PARSER_VERSION,
                record.get("status") == "detailed", _forms_skill_count(record.get("forms", {})))
    for raw_key, source in result.get("champions", {}).items():
        if not isinstance(source, Mapping):
            continue
        record = dict(source)
        key = canonical_key(record.get("key") or raw_key)
        record["key"] = key
        old = canonical.get(key)
        if old is None or quality(record) > quality(old):
            canonical[key] = record
    result["champions"] = canonical
    return result


def _worker(row: Mapping[str, object], hh: Mapping[str, object], timeout: float, mythical_pages: bool):
    session = make_session()
    live_forms, live_error = fetch_live_kit(session, hh, timeout)
    if live_forms:
        return live_forms, "hellhades_live_form_skill_api", live_error
    api_rows, err = fetch_hh_skills(session, hh.get("id"), timeout)
    forms = parse_api_forms(api_rows)
    source_note = "hellhades_legacy_api"
    if str(row.get("rarity") or hh.get("rarity") or "").lower() == "mythical" and mythical_pages and not _has_alternate(forms):
        extra, extra_source = mythical_enrichment(session, row, hh, timeout)
        if extra:
            # Prefer page/gacha data for the alternate form, but retain the API
            # base form when its structured response is available.
            forms = merge_forms(forms, extra)
            if _has_alternate(extra):
                source_note += f"+{extra_source}"
    if not forms:
        for url in [str(hh.get("url") or "")] + candidate_urls(row):
            if not url:
                continue
            html, _, _ = get_text(session, url, timeout)
            if html:
                forms = parse_hh_mythical_page(html)
                if forms:
                    source_note = "hellhades_page"
                    break
    return forms, source_note, err


def main() -> int:
    ap = argparse.ArgumentParser(description="Build a facts-only Legendary/Mythical Live Arena kit database")
    ap.add_argument("--roster", default=str(ROSTER_PATH))
    ap.add_argument("--output", default=str(DB_PATH))
    ap.add_argument("--report", default=str(REPORT_PATH))
    ap.add_argument("--rarity", nargs="*", default=["legendary", "mythical"])
    ap.add_argument("--names", default="", help="Comma-separated names/keys for a small test update")
    ap.add_argument("--resume", action="store_true", help="Skip already detailed records")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--timeout", type=float, default=20.0)
    ap.add_argument("--max", type=int, default=0)
    ap.add_argument("--no-mythical-pages", action="store_true")
    args = ap.parse_args()

    roster_path = Path(args.roster)
    output_path = Path(args.output)
    report_path = Path(args.report)
    rarities = {str(x).lower() for x in args.rarity}
    wanted = {canonical_key(x) for x in args.names.split(",") if x.strip()}

    session = make_session()
    print("V16.5: pobieram indeks i aktualne identyfikatory form/skilli HellHades (bez rankingow)...", flush=True)
    hh_rows, index_err = fetch_hh_index(session, args.timeout)
    if not hh_rows:
        print("ERROR: HellHades champion API unavailable:", index_err)
        print("Nie zmieniono obecnej bazy.")
        return 2

    hh_rows = [x for x in hh_rows if str(x.get("rarity") or "").lower() in rarities]
    print(f"HH API: {len(hh_rows)} Legendary/Mythical identity records", flush=True)

    roster = load_json(roster_path, {"champions": []})
    roster = _refresh_roster_identity(roster, hh_rows, rarities)
    write_atomic(roster_path, roster)

    db = load_json(output_path, None)
    if not isinstance(db, Mapping) or not isinstance(db.get("champions"), Mapping):
        db = build_empty_db(roster)
    else:
        db = canonicalize_existing_database(db)
    db.setdefault("meta", {})
    db["meta"].update({
        "generated_at": utc_now(),
        "source": "HellHades public factual champion/skill API + individual mythical skill pages",
        "source_index": HH_CHAMPIONS_API,
        "policy": {
            "facts_only": True,
            "tier_ranking_imported": False,
            "ratings_imported": False,
            "live_arena_stats_imported": False,
            "win_pick_ban_rates_imported": False,
            "book_value_imported": False,
            "full_source_descriptions_stored": False,
        },
    })
    db.setdefault("champions", {})

    by_key, by_norm = _api_match_maps(hh_rows)
    rows = [x for x in roster.get("champions", []) if isinstance(x, Mapping) and str(x.get("rarity") or "").lower() in rarities]
    if wanted:
        rows = [x for x in rows if canonical_key(x.get("key") or x.get("name")) in wanted]
    if args.max > 0:
        rows = rows[:args.max]

    jobs = []
    unmatched = []
    skipped = 0
    for row in rows:
        key = canonical_key(row.get("key") or row.get("name"))
        current = db["champions"].get(key, {})
        if args.resume and not args.force and isinstance(current, Mapping) and current.get("status") == "detailed" and current.get("forms") and current.get("parser") == API_PARSER_VERSION and not analyze_database({"champions": {key: current}})["errors"]:
            skipped += 1
            continue
        hh = find_api_champion(row, by_key, by_norm)
        if hh is None:
            unmatched.append(str(row.get("name") or key))
            continue
        jobs.append((row, hh))

    ok = partial = failed = 0
    errors: Dict[str, str] = {}
    print(f"Do uzupelnienia: {len(jobs)}; skip={skipped}; unmatched={len(unmatched)}", flush=True)

    def save_progress():
        db["meta"]["generated_at"] = utc_now()
        db["meta"]["roster_count"] = len(db["champions"])
        db["meta"]["parser_version"] = API_PARSER_VERSION
        coverage = {
            "indexed": len(db["champions"]),
            "detailed": sum(1 for c in db["champions"].values() if isinstance(c, Mapping) and c.get("status") in {"detailed", "detailed_seed"} and c.get("forms")),
            "partial": sum(1 for c in db["champions"].values() if isinstance(c, Mapping) and c.get("status") == "partial"),
        }
        coverage["pending"] = max(0, coverage["indexed"] - coverage["detailed"] - coverage["partial"])
        db["meta"]["coverage"] = coverage
        write_atomic(output_path, db)

    workers = max(1, min(8, int(args.workers)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {
            pool.submit(_worker, row, hh, args.timeout, not args.no_mythical_pages): (row, hh)
            for row, hh in jobs
        }
        done = 0
        for fut in as_completed(futs):
            row, hh = futs[fut]
            key = canonical_key(row.get("key") or row.get("name"))
            name = str(row.get("name") or key)
            done += 1
            try:
                forms, source_note, err = fut.result()
                existing = db["champions"].get(key)
                if not isinstance(existing, Mapping):
                    existing = build_empty_db({"champions": [row]})["champions"][key]
                rec = normalized_record_from_api(existing, row, hh, forms, source_note)
                if err:
                    rec["last_error"] = err
                if not forms and isinstance(existing, Mapping) and existing.get("forms"):
                    # A transient fetch failure must not erase a previous kit.
                    rec["forms"] = deepcopy(existing["forms"])
                    rec["status"] = "partial"
                    rec["last_error"] = str(err or "no newly parsed skills; previous kit preserved")
                db["champions"][key] = rec
                if rec["status"] == "detailed":
                    ok += 1
                elif rec["status"] == "partial":
                    partial += 1
                else:
                    failed += 1
                    errors[name] = str(err or "no parsed skills")
                print(f"[{done}/{len(jobs)}] {name}: {rec['status']} ({_forms_skill_count(forms)} skills, {source_note})", flush=True)
            except Exception as exc:
                failed += 1
                errors[name] = str(exc)
                print(f"[{done}/{len(jobs)}] {name}: FAIL {exc}", flush=True)
            # Atomic checkpoint every result.  If the process is interrupted,
            # --resume continues from the last completed champion.
            with _LOCK:
                save_progress()

    # Preserve index-only records even when HH has a transient mismatch.
    for name in unmatched:
        errors[name] = "not matched in HellHades identity API"

    statuses: Dict[str, int] = {}
    for rec in db.get("champions", {}).values():
        if isinstance(rec, Mapping):
            st = str(rec.get("status") or "unknown")
            statuses[st] = statuses.get(st, 0) + 1

    report = {
        "generated_at": utc_now(),
        "facts_only": True,
        "rankings_or_ratings_imported": False,
        "source": {
            "champion_identity": HH_CHAMPIONS_API,
            "skills": HH_SKILLS_API,
            "live_forms": HH_FORMS_API,
            "live_skills": HH_LIVE_SKILLS_API,
            "mythical_alternate_fallback": ["HellHades individual skill page", "gacha.gg Skills section"],
        },
        "run": {"detailed": ok, "partial": partial, "failed": failed, "skipped": skipped, "unmatched": len(unmatched)},
        "database_statuses": statuses,
        "unmatched": unmatched,
        "errors": errors,
        "database_path": str(output_path),
    }
    write_atomic(report_path, report)
    save_progress()
    print("\nDONE", json.dumps(report["run"], ensure_ascii=False), flush=True)
    print("REPORT:", report_path)
    return 0 if failed == 0 and partial == 0 and not unmatched else 1


if __name__ == "__main__":
    raise SystemExit(main())
