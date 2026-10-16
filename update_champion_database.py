#!/usr/bin/env python3
"""Build/update Legendary + Mythical factual kit DB from HellHades champion pages.

IMPORTANT DATA POLICY
---------------------
This updater intentionally ignores Tier List positions, Overall Rating, Arena
rating, win/pick/ban rates, Book Value scores and every other editorial/ranking
metric.  Only factual kit mechanics are stored: skills, cooldowns, targets,
buffs/debuffs/effects, durations, chances and instant effects.

The script is resumable and writes atomically after every successful champion.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import json
import re
import sys
import time
from typing import Dict, Iterable, List, Mapping, Optional, Tuple

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

ROSTER_PATH = ROOT / "data" / "champion_roster_legendary_mythical_2026.json"
DB_PATH = ROOT / "data" / "champion_database.json"
HH_BASE = "https://hellhades.com/raid/champions"
HH_FACTION_BASE = "https://hellhades.com/raid/factions"

# Faction roster pages are used only as a discovery/index source. They are not
# a ranking source. The page itself states that champions are listed by rarity.
# Exact faction pages supplied/verified for the current HellHades layout.
# We keep both the canonical faction landing page and /roster/ as a fallback
# because HellHades has changed which variant contains the champion cards.
FACTION_SOURCES = {
    "Banner Lords": (
        "https://hellhades.com/raid/factions/banner-lords/",
        "https://hellhades.com/raid/factions/banner-lords/roster/",
    ),
    "High Elves": (
        "https://hellhades.com/raid/factions/high-elves/",
        "https://hellhades.com/raid/factions/high-elves/roster/",
    ),
    "Sacred Order": (
        "https://hellhades.com/raid/factions/the-sacred-order/",
        "https://hellhades.com/raid/factions/the-sacred-order/roster/",
    ),
    "Barbarians": (
        "https://hellhades.com/raid/factions/barbarians/",
        "https://hellhades.com/raid/factions/barbarians/roster/",
    ),
    "Ogryn Tribes": (
        "https://hellhades.com/raid/factions/ogryn-tribes/",
        "https://hellhades.com/raid/factions/ogryn-tribes/roster/",
    ),
    "Lizardmen": (
        "https://hellhades.com/raid/factions/lizardmen/",
        "https://hellhades.com/raid/factions/lizardmen/roster/",
    ),
    "Skinwalkers": (
        "https://hellhades.com/raid/factions/skinwalkers/",
        "https://hellhades.com/raid/factions/skinwalkers/roster/",
    ),
    "Orcs": (
        "https://hellhades.com/raid/factions/orcs/",
        "https://hellhades.com/raid/factions/orcs/roster/",
    ),
    "Demonspawn": (
        "https://hellhades.com/raid/factions/demonspawn/",
        "https://hellhades.com/raid/factions/demonspawn/roster/",
    ),
    "Undead Hordes": (
        "https://hellhades.com/raid/factions/undead-hordes/",
        "https://hellhades.com/raid/factions/undead-hordes/roster/",
    ),
    "Dark Elves": (
        "https://hellhades.com/raid/factions/dark-elves/",
        "https://hellhades.com/raid/factions/dark-elves/roster/",
    ),
    "Knights Revenant": (
        "https://hellhades.com/raid/factions/knights-revenant/",
        "https://hellhades.com/raid/factions/knights-revenant/roster/",
    ),
    "Dwarves": (
        "https://hellhades.com/raid/factions/dwarves/",
        "https://hellhades.com/raid/factions/dwarves/roster/",
    ),
    "Shadowkin": (
        "https://hellhades.com/raid/factions/shadowkin/",
        "https://hellhades.com/raid/factions/shadowkin/roster/",
    ),
    "Sylvan Watchers": (
        "https://hellhades.com/raid/factions/sylvan-watchers/",
        "https://hellhades.com/raid/factions/sylvan-watchers/roster/",
    ),
    "Argonites": (
        "https://hellhades.com/raid/factions/argonites/",
        "https://hellhades.com/raid/factions/argonites/roster/",
    ),
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Slugs that cannot be inferred safely from display name.
SLUG_OVERRIDES = {
    "fabian": "lord-entertainer-fabian",
    "krixia": "Night-Queen-Krixia",
    "komidus": "Komidus-Darksmile",
    "tekteon": "tekteon-fissureflesh",
    "vestele": "vestele-riverthorn",
    "siphi": "siphi-the-lost-bride",
    "nais": "Nais-the-Shadowthief",
    "marius": "Marius-The-Gallant",
    "shu_zhen": "shu-zhen-the-valorous",
}

IGNORE_SECTION_WORDS = (
    "rating", "ratings", "masteries", "blessings", "gear recommendations",
    "relics", "overview", "live arena", "book value", "book priority",
)

BUFF_DEBUFF_ALIASES = {
    "increase atk": "increase atk", "increase attack": "increase atk",
    "decrease atk": "decrease atk", "decrease attack": "decrease atk",
    "increase def": "increase def", "increase defense": "increase def",
    "decrease def": "decrease def", "decrease defense": "decrease def",
    "increase spd": "increase spd", "increase speed": "increase spd",
    "decrease spd": "decrease spd", "decrease speed": "decrease spd",
    "block debuffs": "block debuffs", "block buffs": "block buffs",
    "block damage": "block damage", "unkillable": "unkillable",
    "ally protection": "ally protection", "strengthen": "strengthen",
    "shield": "shield", "veil": "veil", "perfect veil": "perfect veil",
    "stone skin": "stoneskin", "stoneskin": "stoneskin",
    "weaken": "weaken", "poison": "poison", "bomb": "bomb",
    "stun": "stun", "freeze": "freeze", "sleep": "sleep",
    "provoke": "provoke", "taunt": "taunt", "fear": "fear",
    "true fear": "true fear", "sheep": "sheep", "petrification": "petrification",
    "heal reduction": "heal reduction", "decrease acc": "decrease acc",
    "increase acc": "increase acc", "decrease c. rate": "decrease c. rate",
    "increase c. rate": "increase c. rate", "increase c. dmg": "increase c. dmg",
    "continuous heal": "continuous heal", "revive on death": "revive on death",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return deepcopy(default)


def write_atomic(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def build_empty_db(roster: Mapping[str, object]) -> dict:
    champs = {}
    for row in roster.get("champions", []):
        if not isinstance(row, Mapping):
            continue
        key = canonical_key(row.get("key") or row.get("name"))
        slug = SLUG_OVERRIDES.get(key) or str(row.get("hellhades_slug") or "").strip("/")
        champs[key] = {
            "name": row.get("name"), "key": key,
            "rarity": str(row.get("rarity") or "").lower(),
            "affinity_group": row.get("affinity_group"),
            "affinity": "", "faction": "", "role": "",
            "source_url": f"{HH_BASE}/{slug}/" if slug else "",
            "source_updated_at": "", "status": "index_only", "forms": {},
        }
    return {
        "schema_version": 2,
        "meta": {
            "generated_at": utc_now(),
            "source": "HellHades individual champion pages",
            "source_index": "HellHades faction landing pages (with /roster/ fallback)",
            "policy": {
                "facts_only": True,
                "tier_ranking_imported": False,
                "ratings_imported": False,
                "live_arena_stats_imported": False,
                "win_pick_ban_rates_imported": False,
            },
            "roster_count": len(champs),
        },
        "champions": champs,
    }


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _norm_slug(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")


def _clean_roster_name(text: str) -> str:
    text = normalize_space(text)
    # Keep this deliberately conservative: names are only used as a fallback.
    text = re.sub(r"\s+(?:Champion|Guide|Raid Shadow Legends).*$", "", text, flags=re.I).strip()
    return text


def _rarity_near_link(link: Tag) -> str:
    """Infer rarity from the nearest rarity heading/container.

    Faction roster pages are grouped by rarity, but HH has changed markup over
    time. We therefore inspect both preceding headings and a few ancestors. If
    we cannot prove the rarity, return an empty string rather than guessing.
    """
    rarities = ("mythical", "legendary", "epic", "rare", "uncommon", "common")
    for h in link.find_all_previous(["h1", "h2", "h3", "h4", "h5", "h6"], limit=8):
        txt = normalize_space(h.get_text(" ", strip=True)).lower()
        for rarity in rarities:
            if re.search(rf"\b{re.escape(rarity)}\b", txt):
                return rarity
    parent = link.parent
    for _ in range(5):
        if parent is None:
            break
        attrs = " ".join([
            str(parent.get("id") or ""),
            " ".join(parent.get("class") or []),
            str(parent.get("data-rarity") or ""),
        ]).lower()
        for rarity in rarities:
            if re.search(rf"\b{re.escape(rarity)}\b", attrs):
                return rarity
        parent = parent.parent
    return ""


def parse_faction_roster_page(html: str, faction: str) -> List[dict]:
    """Extract champion profile links from one HH faction roster page.

    This parser never reads tier/rating values. It only discovers profile URLs,
    display names (when present), faction and rarity grouping.
    """
    soup = BeautifulSoup(html, "html.parser")
    found: Dict[str, dict] = {}
    for a in soup.find_all("a", href=True):
        href = str(a.get("href") or "")
        m = re.search(r"/raid/champions/([^/?#]+)/?", href, re.I)
        if not m:
            continue
        slug = m.group(1).strip()
        if not slug:
            continue
        name = _clean_roster_name(a.get_text(" ", strip=True))
        if not name:
            img = a.find("img")
            if img is not None:
                name = _clean_roster_name(img.get("alt") or img.get("title") or "")
        rarity = _rarity_near_link(a)
        key = _norm_slug(slug)
        row = found.get(key, {})
        # Prefer richer observations if duplicate cards/links exist.
        if name and not row.get("name"):
            row["name"] = name
        if rarity and not row.get("rarity"):
            row["rarity"] = rarity
        row.update({"hellhades_slug": slug, "faction": faction})
        found[key] = row
    return list(found.values())


def fetch_raw_page(session: requests.Session, url: str, timeout: float) -> Tuple[Optional[str], Optional[str]]:
    try:
        r = session.get(url, headers=HEADERS, timeout=timeout)
        if r.status_code == 200 and len(r.text) > 1000:
            return r.text, r.url
        return None, f"HTTP {r.status_code}"
    except Exception as exc:
        return None, str(exc)


def refresh_roster_from_factions(
    session: requests.Session,
    roster: Mapping[str, object],
    *, timeout: float,
    delay: float,
    allowed_rarities: set[str],
) -> Tuple[dict, dict]:
    """Refresh exact champion slugs/factions from all HH faction roster pages.

    Existing Legendary/Mythical rows are matched primarily by exact HH slug,
    then by canonical display name. New champions are added only when the
    faction page itself proves their rarity is Legendary or Mythical.
    """
    payload = dict(roster)
    rows = [dict(x) for x in payload.get("champions", []) if isinstance(x, Mapping)]
    by_slug = {_norm_slug(x.get("hellhades_slug")): x for x in rows if x.get("hellhades_slug")}
    by_name = {canonical_key(x.get("key") or x.get("name")): x for x in rows}
    stats = {"pages_ok": 0, "pages_failed": 0, "links_found": 0, "matched": 0,
             "new": 0, "unknown_rarity_skipped": 0, "errors": {}}

    for faction, urls in FACTION_SOURCES.items():
        html = None
        resolved = None
        tried = []
        for url in urls:
            tried.append(url)
            html, resolved = fetch_raw_page(session, url, timeout)
            if html is None:
                continue
            # A 200 page without any champion profile links is not a useful
            # faction index; try the alternate layout before accepting it.
            probe = parse_faction_roster_page(html, faction)
            if probe:
                discovered = probe
                resolved = url
                break
            html = None
            resolved = "no champion profile links"
        if html is None:
            stats["pages_failed"] += 1
            stats["errors"][faction] = {"error": resolved, "tried": tried}
            print(f"FACTION INDEX FAIL: {faction}: {resolved}; tried={tried}")
            time.sleep(max(0.0, delay))
            continue
        stats["pages_ok"] += 1
        stats["links_found"] += len(discovered)
        stats.setdefault("resolved_sources", {})[faction] = resolved
        for d in discovered:
            s_key = _norm_slug(d.get("hellhades_slug"))
            n_key = canonical_key(d.get("name")) if d.get("name") else ""
            row = by_slug.get(s_key) or (by_name.get(n_key) if n_key else None)
            if row is not None:
                row["hellhades_slug"] = d.get("hellhades_slug") or row.get("hellhades_slug")
                row["faction"] = faction
                if d.get("rarity") in allowed_rarities:
                    row["rarity"] = d["rarity"]
                by_slug[s_key] = row
                if n_key:
                    by_name[n_key] = row
                stats["matched"] += 1
                continue
            rarity = str(d.get("rarity") or "").lower()
            if rarity not in allowed_rarities:
                stats["unknown_rarity_skipped"] += 1
                continue
            name = d.get("name") or re.sub(r"[-_]+", " ", str(d.get("hellhades_slug") or "")).strip().title()
            new_row = {
                "name": name,
                "key": canonical_key(name),
                "rarity": rarity,
                "affinity_group": None,
                "faction": faction,
                "hellhades_slug": d.get("hellhades_slug"),
            }
            rows.append(new_row)
            by_slug[s_key] = new_row
            by_name[new_row["key"]] = new_row
            stats["new"] += 1
        time.sleep(max(0.0, delay))

    # Deduplicate by canonical champion key while preserving current order.
    dedup: Dict[str, dict] = {}
    order: List[str] = []
    for row in rows:
        key = canonical_key(row.get("key") or row.get("name"))
        if not key:
            continue
        if key not in dedup:
            order.append(key)
            dedup[key] = row
        else:
            dedup[key].update({k: v for k, v in row.items() if v not in (None, "")})
    payload["champions"] = [dedup[k] for k in order]
    payload["generated_from"] = "HellHades faction roster pages + individual champion pages"
    payload["source_url"] = "https://hellhades.com/raid/factions/<faction>/roster/"
    payload["faction_index_refreshed_at"] = utc_now()
    payload["counts"] = {
        "total": len(payload["champions"]),
        "legendary": sum(1 for x in payload["champions"] if str(x.get("rarity") or "").lower() == "legendary"),
        "mythical": sum(1 for x in payload["champions"] if str(x.get("rarity") or "").lower() == "mythical"),
    }
    return payload, stats


def page_metadata(soup: BeautifulSoup) -> dict:
    text = soup.get_text("\n", strip=True)
    updated = ""
    m = re.search(r"Last Updated:\s*([^\n]+)", text, re.I)
    if m:
        updated = normalize_space(m.group(1))

    faction = affinity = role = ""
    # HH image alt text is more stable than styling classes.
    for img in soup.find_all("img"):
        alt = normalize_space(img.get("alt") or "")
        low = alt.lower()
        if low.endswith(" faction"):
            faction = alt[:-8].strip()
        elif low.endswith(" affinity"):
            affinity = alt[:-9].strip().lower()
    # Role/type often appears in page text near base stats; keep optional.
    for candidate in ("Attack", "Defense", "Defence", "HP", "Support"):
        if re.search(rf"\b{candidate}\b", text, re.I):
            role = candidate.lower().replace("defence", "defense")
            break
    return {"source_updated_at": updated, "faction": faction, "affinity": affinity, "role": role}


def _section_nodes(soup: BeautifulSoup) -> List[Tag]:
    """Return elements within the factual Skills section only.

    This is the key guard against accidentally ingesting HH ratings/tier data.
    """
    start = None
    for h in soup.find_all(["h2", "h3"]):
        if re.search(r"\bSkills\b", normalize_space(h.get_text(" ", strip=True)), re.I):
            start = h
            break
    if start is None:
        return []
    nodes: List[Tag] = []
    for el in start.find_all_next():
        if el is start:
            continue
        if el.name in ("h2", "h3"):
            title = normalize_space(el.get_text(" ", strip=True)).lower()
            if "skill" not in title and any(word in title for word in ("master", "blessing", "relic", "gear", "video")):
                break
        nodes.append(el)
    return nodes


def _looks_like_skill_heading(text: str) -> bool:
    low = text.lower().strip()
    if not text or len(text) > 90:
        return False
    if any(word in low for word in IGNORE_SECTION_WORDS):
        return False
    if re.fullmatch(r"a[1-4]|p|passive|base form|alternate form", low):
        return False
    if re.fullmatch(r"\d+(?:\.\d+)?/10", low):
        return False
    if re.match(r"level \d+", low):
        return False
    return True


def extract_skill_blocks(soup: BeautifulSoup) -> List[Tuple[str, str, str]]:
    """Return (form, name, text) blocks from the Skills section.

    HH has changed markup several times, so parsing is deliberately structural
    and conservative.  Ambiguous pages remain index-only/partial instead of
    inventing mechanics.
    """
    nodes = _section_nodes(soup)
    headings: List[Tuple[int, Tag, str, str]] = []
    current_form = "base"
    for i, el in enumerate(nodes):
        if el.name not in ("h3", "h4", "h5"):
            continue
        text = normalize_space(el.get_text(" ", strip=True))
        low = text.lower()
        if "alternate form" in low or "second form" in low:
            current_form = "alternate"
            continue
        if "base form" in low or "first form" in low:
            current_form = "base"
            continue
        if _looks_like_skill_heading(text):
            headings.append((i, el, current_form, text))

    blocks = []
    for idx, (pos, el, form, name) in enumerate(headings):
        end_pos = headings[idx + 1][0] if idx + 1 < len(headings) else len(nodes)
        bits: List[str] = []
        # collect unique leaf-ish text until next skill heading
        seen = set()
        for child in nodes[pos + 1:end_pos]:
            if child.name in ("script", "style", "svg", "img"):
                continue
            # avoid parent elements duplicating all descendant text
            if child.find(["p", "li", "h3", "h4", "h5"], recursive=False):
                continue
            txt = normalize_space(child.get_text(" ", strip=True))
            if not txt or txt in seen:
                continue
            seen.add(txt)
            bits.append(txt)
        text = " ".join(bits)
        if len(text) >= 8:
            blocks.append((form, name, text))
    return blocks


from tools.champion_skill_facts import (  # shared by page and API imports
    PARSER_VERSION, parse_effects, parse_skill,
)


def assign_skill_ids(blocks: List[Tuple[str, str, str]]) -> Dict[str, Dict[str, dict]]:
    from tools.update_champion_database_api import parse_api_skill_rows
    grouped: Dict[str, list] = {}
    for form, name, text in blocks:
        grouped.setdefault(form, []).append({"name": name, "description": text})
    return {form: {"skills": parse_api_skill_rows(rows, form)} for form, rows in grouped.items()}


def fetch_page(session: requests.Session, urls: Iterable[str], timeout: float) -> Tuple[Optional[str], Optional[str]]:
    last_error = None
    for url in urls:
        try:
            r = session.get(url, headers=HEADERS, timeout=timeout)
            if r.status_code == 200 and len(r.text) > 2000 and "Skills" in r.text:
                return r.text, r.url
            last_error = f"HTTP {r.status_code}"
        except Exception as exc:
            last_error = str(exc)
    return None, last_error


def candidate_urls(row: Mapping[str, object]) -> List[str]:
    key = canonical_key(row.get("key") or row.get("name"))
    slugs = []
    if key in SLUG_OVERRIDES:
        slugs.append(SLUG_OVERRIDES[key])
    if row.get("hellhades_slug"):
        slugs.append(str(row.get("hellhades_slug")))
    name = str(row.get("name") or "")
    slugs += [
        re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-"),
        re.sub(r"[^A-Za-z0-9]+", "-", name.lower()).strip("-"),
    ]
    out = []
    for slug in slugs:
        url = f"{HH_BASE}/{slug.strip('/')}/"
        if url not in out:
            out.append(url)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--roster", default=str(ROSTER_PATH))
    ap.add_argument("--output", default=str(DB_PATH))
    ap.add_argument("--rarity", nargs="*", default=["legendary", "mythical"])
    ap.add_argument("--names", default="", help="Comma-separated names/keys for a small test update")
    ap.add_argument("--resume", action="store_true", help="Skip detailed records already present")
    ap.add_argument("--force", action="store_true", help="Refresh even detailed records")
    ap.add_argument("--delay", type=float, default=0.45)
    ap.add_argument("--timeout", type=float, default=20.0)
    ap.add_argument("--max", type=int, default=0)
    ap.add_argument("--discover-factions", action="store_true",
                    help="Refresh exact champion links from every HH faction roster before fetching skills")
    ap.add_argument("--report", default=str(ROOT / "data" / "champion_database_update_report.json"))
    args = ap.parse_args()

    roster_path = Path(args.roster)
    output_path = Path(args.output)
    report_path = Path(args.report)
    roster = load_json(roster_path, {"champions": []})
    session = requests.Session()
    faction_stats = None
    if args.discover_factions:
        print("Refreshing champion index from HellHades faction roster pages ...", flush=True)
        roster, faction_stats = refresh_roster_from_factions(
            session, roster, timeout=args.timeout, delay=min(args.delay, 0.25),
            allowed_rarities={x.lower() for x in args.rarity},
        )
        write_atomic(roster_path, roster)
        print("FACTION INDEX:", json.dumps(faction_stats, ensure_ascii=False), flush=True)

    db = load_json(output_path, None)
    if not isinstance(db, Mapping) or not isinstance(db.get("champions"), Mapping):
        db = build_empty_db(roster)
    else:
        db = dict(db)
        db.setdefault("meta", {})
        db["meta"].setdefault("policy", {})
        db["meta"]["policy"].update({
            "facts_only": True, "tier_ranking_imported": False,
            "ratings_imported": False, "live_arena_stats_imported": False,
            "win_pick_ban_rates_imported": False,
        })
        db["meta"]["source_index"] = "HellHades faction landing pages (with /roster/ fallback)"

    wanted = {canonical_key(x) for x in args.names.split(",") if x.strip()}
    rarities = {x.lower() for x in args.rarity}
    rows = [x for x in roster.get("champions", []) if isinstance(x, Mapping)]
    rows = [x for x in rows if str(x.get("rarity") or "").lower() in rarities]
    if wanted:
        rows = [x for x in rows if canonical_key(x.get("key") or x.get("name")) in wanted]
    if args.max > 0:
        rows = rows[:args.max]

    ok = fail = skip = 0
    for i, row in enumerate(rows, 1):
        key = canonical_key(row.get("key") or row.get("name"))
        record = db["champions"].get(key)
        if not isinstance(record, Mapping):
            record = build_empty_db({"champions": [row]})["champions"][key]
        if args.resume and not args.force and record.get("status") in {"detailed", "partial"} and record.get("forms"):
            skip += 1
            continue

        print(f"[{i}/{len(rows)}] {row.get('name')} ...", flush=True)
        html, resolved = fetch_page(session, candidate_urls(row), args.timeout)
        if html is None:
            fail += 1
            print("  FAIL:", resolved)
            record = dict(record); record["status"] = "fetch_failed"; record["last_error"] = resolved
            db["champions"][key] = record
            write_atomic(output_path, db)
            time.sleep(max(0.0, args.delay))
            continue

        soup = BeautifulSoup(html, "html.parser")
        blocks = extract_skill_blocks(soup)
        forms = assign_skill_ids(blocks)
        parsed_count = sum(len(v.get("skills", {})) for v in forms.values())
        meta = page_metadata(soup)
        record = dict(record)
        record.update(meta)
        if row.get("faction"):
            record["faction"] = row.get("faction")
        record["source_url"] = resolved
        record["forms"] = forms
        record["status"] = "detailed" if parsed_count >= 2 else "partial"
        record["parser"] = "hellhades_skills_v2"
        record["updated_at"] = utc_now()
        record.pop("last_error", None)
        db["champions"][key] = record
        db["meta"]["generated_at"] = utc_now()
        coverage = {
            "indexed": len(db["champions"]),
            "detailed": sum(1 for c in db["champions"].values() if isinstance(c, Mapping) and c.get("forms")),
        }
        coverage["pending"] = coverage["indexed"] - coverage["detailed"]
        db["meta"]["coverage"] = coverage
        write_atomic(output_path, db)
        print(f"  OK: {parsed_count} skill blocks, status={record['status']}")
        ok += 1
        time.sleep(max(0.0, args.delay))

    statuses = {}
    for c in db.get("champions", {}).values():
        if isinstance(c, Mapping):
            st = str(c.get("status") or "unknown")
            statuses[st] = statuses.get(st, 0) + 1
    report = {
        "generated_at": utc_now(),
        "facts_only": True,
        "tier_ranking_imported": False,
        "faction_discovery": faction_stats,
        "run": {"ok": ok, "skip": skip, "fail": fail},
        "database_statuses": statuses,
        "database_path": str(output_path),
    }
    write_atomic(report_path, report)
    print(f"DONE: ok={ok} skip={skip} fail={fail} -> {output_path}")
    print(f"REPORT: {report_path}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
