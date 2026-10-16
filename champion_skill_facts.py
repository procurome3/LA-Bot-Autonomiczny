"""Conservative factual skill parsing. References to statuses are not grants.

This module stores normalized operations, predicates and numbers, never source
descriptions or editorial ratings. Unsupported clauses are flagged for review.
"""
from __future__ import annotations

import json
import re

PARSER_VERSION = "facts_v5"

BUFFS = {
    "increase atk", "increase def", "increase spd", "increase acc", "increase res",
    "increase c. rate", "increase c. dmg", "shield", "strengthen", "block debuffs",
    "block damage", "unkillable", "ally protection", "veil", "perfect veil",
    "stoneskin", "continuous heal", "revive on death", "counterattack", "reflect damage",
    "taunt", "poison cloud", "shatter", "intercept", "fervor", "life barrier",
}
DEBUFFS = {
    "decrease atk", "decrease def", "decrease spd", "decrease acc", "decrease res",
    "decrease c. rate", "decrease c. dmg", "weaken", "poison", "bomb", "stun",
    "freeze", "sleep", "provoke", "fear", "true fear", "sheep", "petrification",
    "heal reduction", "hp burn", "leech", "block buffs", "block active skills",
    "block passive skills", "hex", "smite", "enfeeble", "seal", "hunter's gaze",
}
ALIASES = {
    "increase attack": "increase atk", "decrease attack": "decrease atk",
    "increase defense": "increase def", "increase defence": "increase def",
    "decrease defense": "decrease def", "decrease defence": "decrease def",
    "increase speed": "increase spd", "decrease speed": "decrease spd",
    "increase accuracy": "increase acc", "decrease accuracy": "decrease acc",
    "increase resistance": "increase res", "decrease resistance": "decrease res",
    "stone skin": "stoneskin", "hunters gaze": "hunter's gaze",
    "counter attack": "counterattack",
}
CONTROL = {"stun", "freeze", "sleep", "provoke", "fear", "true fear", "sheep", "petrification", "block active skills", "block passive skills"}
PROTECTION = {"shield", "strengthen", "increase def", "block damage", "unkillable", "ally protection", "veil", "perfect veil", "stoneskin", "taunt", "poison cloud", "intercept"}
_ALIASES_PATTERN = "|".join(re.escape(x) for x in sorted(BUFFS | DEBUFFS | set(ALIASES) | {"block revive"}, key=len, reverse=True))
_STATUS = re.compile(r"\[([^\]]{2,60})\]|(?<![\w])(" + _ALIASES_PATTERN + r")(?![\w])(?=\s+(?:buff|debuff)s?\b)", re.I)
_GOVERNOR = re.compile(r"\b(plac\w*|appl\w*|giv\w*|grant\w*|remov\w*|steal\w*|ignor\w*|immun\w*|transfer\w*|spread\w*|extend\w*|destroy\w*)\b", re.I)


def clean(text):
    return re.sub(r"\s+", " ", str(text or "").replace("’", "'").replace("‘", "'")).strip()


def _name(text):
    name = clean(text).lower()
    return ALIASES.get(name, name)


def split_books(text):
    parts = re.split(r"\b(?:Level|Lvl\.?)\s*\d+\s*:", clean(text), maxsplit=1, flags=re.I)
    books = parts[1] if len(parts) > 1 else ""
    cooldown = sum(int(x) for x in re.findall(r"Cooldown\s*[-−]\s*(\d+)", books, re.I))
    chance = sum(float(x) for x in re.findall(r"(?:Buff\s*/\s*Debuff|Debuff|Buff)\s+Chance\s*\+\s*(\d+(?:\.\d+)?)%", books, re.I))
    return parts[0], cooldown, chance


def _sentences(text):
    protected = re.sub(r"\bC\.\s*(Rate|DMG)", lambda m: "C_" + m[1], text, flags=re.I)
    return [x.replace("C_", "C. ").strip() for x in re.split(r"(?<=[.!?])\s+", protected) if x.strip()]


def _subject(text, default="unknown"):
    low = text.lower()
    if re.search(r"all (?:dead )?allies|each ally", low):
        return "all_dead_allies" if "dead" in low else "all_allies"
    if re.search(r"all enemies|each (?:enemy|target)|enemies'", low):
        return "all_enemies"
    if re.search(r"this champion|on (?:them|himself|herself)|their (?:own )?turn meter", low):
        return "self"
    if re.search(r"(?:an?|one|1|random|revived) (?:dead )?ally", low):
        return "one_dead_ally" if "dead" in low else "one_ally"
    if re.search(r"target|enemy", low):
        return "enemy"
    return default


def _conditions(sentence):
    low = sentence.lower()
    out = []
    if re.search(r"if .*?(?:does not|doesn't|fails? to) kill", low):
        out.append({"subject": "action", "predicate": "killed_target", "value": False})
    elif re.search(r"if .*?kills? (?:an? |the )?enemy|if .*?kills? the target", low):
        out.append({"subject": "action", "predicate": "killed_target", "value": True})
    if re.search(r"if .*?ally .*?(?:successfully )?revived", low):
        out.append({"subject": "action", "predicate": "revived_ally", "value": True})
    hp = re.search(r"(?:less than|below)\s*(\d+(?:\.\d+)?)%\s*HP", sentence, re.I)
    if hp:
        out.append({"subject": "effect_target", "predicate": "hp_percent_below", "value": float(hp[1])})
    marker = re.search(r"\b(?:if|while|unless)\b.*?\bunder\b", low)
    if marker:
        names = [_name(m[1] or m[2]) for m in _STATUS.finditer(sentence, marker.end())]
        names = [n for n in names if n in BUFFS | DEBUFFS]
        if names:
            out.append({"subject": "actor" if "this champion" in low[marker.start():marker.end()] else "target", "predicate": "has_any_status" if " or " in low[marker.end():] else "has_all_statuses", "names": list(dict.fromkeys(names))})
    if re.search(r"start of (?:each|every|the) round", low):
        out.append({"subject": "battle", "predicate": "event", "value": "round_start"})
    return out


def tags_for_effects(effects):
    tags = set()
    for effect in effects:
        kind, name = effect["kind"], effect["name"]
        if kind == "buff":
            tags.add("support")
            if name in PROTECTION:
                tags.add("protection")
            if name == "block debuffs":
                tags.add("cleanse")
            if name == "revive on death":
                tags.add("revive")
        if kind == "debuff" and name in CONTROL:
            tags.add("control")
        if kind in {"buff", "debuff"} and name in {"increase spd", "decrease spd"}:
            tags.update({"speed", "turn_meter"})
        tags.update({"turn_meter": {"turn_meter"}, "revive": {"revive", "support"}, "heal": {"heal", "support"}, "strip": {"strip"}, "cleanse": {"cleanse", "support"}, "cooldown": {"control", "lockout"}, "extra_turn": {"extra_turn"}, "transform": {"transform"}, "anti_revive": {"anti_revive"}, "damage_rule": {"damage"}}.get(kind, set()))
    return sorted(tags)


def parse_facts(text):
    mechanics, _, book_chance = split_books(text)
    effects, requirements, review = [], [], set()
    for sentence in _sentences(mechanics):
        low = sentence.lower()
        conditions = _conditions(sentence)
        if re.search(r"\b(?:if|unless|whenever)\b", low) and not conditions:
            review.add("unmodeled_conditional_clause")

        def add(kind, name, **values):
            obj = {"kind": kind, "name": name, "target": values.pop("target", "unknown"), "duration_turns": None, "chance_percent": None}
            obj.update(values)
            if conditions:
                obj["conditions"] = conditions
            effects.append(obj)

        for match in _STATUS.finditer(sentence):
            name = _name(match[1] or match[2])
            if name in {"passive effect", "active effect", "p"}:
                continue
            explicit_kind_hint = re.match(r"\s*(buff|debuff)\b", sentence[match.end():], re.I)
            if name not in BUFFS | DEBUFFS | {"block revive"} and not explicit_kind_hint:
                review.add("unknown_status_name")
                continue
            prefix = sentence[:match.start()]
            governors = list(_GOVERNOR.finditer(prefix))
            governor = governors[-1] if governors else None
            # "under Veil" is a requirement, not a buff placed by this skill.
            condition_markers = list(re.finditer(r"\b(?:if|unless|while|under|without|immune to)\b", prefix, re.I))
            last_condition = condition_markers[-1] if condition_markers else None
            if not governor or (last_condition and last_condition.start() > governor.end() and "immune" not in governor[0].lower()):
                requirements.append({"name": name, "relation": "mentioned_or_required"})
                continue
            verb = governor[0].lower()
            if verb.startswith("ignor"):
                add("ignore_status", name, target="enemy")
                continue
            if verb.startswith("immun"):
                add("immunity", name, target="self")
                continue
            if verb.startswith(("remov", "steal", "destroy", "extend")):
                requirements.append({"name": name, "relation": "removed_stolen_or_modified"})
                continue
            if not verb.startswith(("plac", "appl", "giv", "grant", "transfer", "spread")):
                continue
            after = sentence[match.end():]
            boundary = re.search(r"\b(?:places?|applies|removes?|steals?|then)\b", after, re.I)
            duration_text = after[:boundary.start()] if boundary else after
            duration = re.search(r"for\s+(\d+)\s+turn", duration_text, re.I)
            chance_matches = re.findall(r"(\d+(?:\.\d+)?)%\s+chance", prefix, re.I)
            chance = float(chance_matches[-1]) if chance_matches else 100.0
            value = re.search(r"(\d+(?:\.\d+)?)%\s*$", prefix)
            explicit_kind = re.match(r"\s*(buff|debuff)\b", after, re.I)
            kind = explicit_kind[1].lower() if explicit_kind else "buff" if name in BUFFS else "debuff"
            target = _subject(duration_text, "self" if kind == "buff" and "this champion" in low else "enemy" if kind == "debuff" else "unknown")
            if name == "block revive":
                add("anti_revive", "block revive", target="enemy", chance_percent=chance)
                continue
            add(kind, name, target=target, duration_turns=int(duration[1]) if duration else None, chance_percent=chance, chance_booked_percent=min(100.0, chance + book_chance), value_percent=float(value[1]) if value else None)

        for match in re.finditer(r"\b(fills?|decreases?|reduces?|steals?)\s+([^.!?]*?Turn Meters?[^.!?]*?)\b(?:by|for|of)\s*(\d+(?:\.\d+)?)%", sentence, re.I):
            operation = "fill" if match[1].lower().startswith("fill") else "steal" if match[1].lower().startswith("steal") else "decrease"
            add("turn_meter", "turn meter " + operation, target=_subject(match[2]), value_percent=float(match[3]))
        # Common steal phrasing puts the percentage before Turn Meter.
        for match in re.finditer(r"steals?\s*(\d+(?:\.\d+)?)%\s+of (?:the )?target's Turn Meter", sentence, re.I):
            add("turn_meter", "turn meter steal", target="enemy", value_percent=float(match[1]))
        revive = re.search(r"\brevives?\s+(all dead allies|(?:a|one|1|random) (?:dead )?ally|this champion)", sentence, re.I)
        if revive:
            hp = re.search(r"(?:with|to)\s*(\d+(?:\.\d+)?)%\s*(?:of (?:their|its) (?:MAX )?)?HP", sentence, re.I)
            add("revive", "revive", target=_subject(revive[0]), value_percent=float(hp[1]) if hp else None, value_basis="target_max_hp")
        if re.search(r"\bgrants? .*?extra turn|\bgains? .*?extra turn", low):
            add("extra_turn", "extra turn", target="self")
        if re.search(r"\btransforms? this champion into (?:their |the )?(?:alternate|base) form", low):
            add("transform", "transform", target="self", destination_form="alternate" if "alternate form" in low else "base")
        if re.search(r"\b(?:removes?|steals?)\s+(?:all|(?:a|one|\d+) random) buffs", low):
            add("strip", "steal buffs" if "steal" in low else "remove buffs", target="all_enemies" if "all enemies" in low else "enemy")
        if re.search(r"decreas\w* (?:the )?duration of .*?buffs", low):
            amount = re.search(r"by\s+(\d+)\s+turn", low)
            chance = re.search(r"(\d+(?:\.\d+)?)%\s+chance", low)
            add("strip", "decrease buff duration", target="all_enemies" if "all enemy" in low or "all enemies" in low else "enemy", amount=int(amount[1]) if amount else None, chance_percent=float(chance[1]) if chance else 100.0, chance_booked_percent=min(100.0, float(chance[1]) + book_chance) if chance else 100.0)
        if re.search(r"\bremoves? (?:all|a|one|\d+) (?:\w+ )?debuffs?", low):
            add("cleanse", "remove debuffs", target=_subject(sentence, "ally"))
        cooldown = re.search(r"increas\w* .*?(?:skill cooldowns?|cooldowns? of .*?skills?) by\s*(\d+)\s*turn", low)
        if cooldown:
            add("cooldown", "increase cooldown", target="all_enemies" if "all enemies" in low or "all enemy" in low else "enemy", amount=int(cooldown[1]))
        if re.search(r"puts? .*?skills? on (?:full )?cooldown|places? .*?skills? on (?:full )?cooldown", low):
            add("cooldown", "full cooldown", target="enemy")
        for match in re.finditer(r"heals? (all allies|this champion|the target|an ally|each ally)\s+by\s*(\d+(?:\.\d+)?)%", sentence, re.I):
            basis = "damage_dealt" if "damage dealt" in low else "target_max_hp" if "max hp" in low else "unknown"
            add("heal", "heal", target=_subject(match[1]), value_percent=float(match[2]), value_basis=basis)
        ignore_def = re.search(r"ignores?\s*(\d+(?:\.\d+)?)%\s*(?:of\s+)?(?:(?:each |the )?(?:target|enemy)(?:'s)?\s+)?DEF", sentence, re.I)
        if ignore_def:
            add("damage_rule", "ignore def", target="enemy", value_percent=float(ignore_def[1]))

    unique = list({json.dumps(e, sort_keys=True): e for e in effects}.values())
    requires = list({json.dumps(e, sort_keys=True): e for e in requirements}.values())
    return unique, tags_for_effects(unique), requires, sorted(review)


def parse_effects(text):
    effects, tags, _, _ = parse_facts(text)
    return effects, tags


def parse_skill(name, text, sid, form):
    text, name = clean(text), clean(name)
    mechanics, cooldown_books, _ = split_books(text)
    passive = str(sid).upper().startswith("P")
    aura = str(sid).upper() == "AURA"
    # A duration in the body is never a cooldown.
    cm = re.match(r"^(?:Cooldown\s*:?\s*)?(\d+)\s+Turns?\b", mechanics, re.I)
    cooldown = int(cm[1]) if cm else 0 if sid == "A1" else None
    effects, tags, requirements, review = parse_facts(text)
    low = mechanics.lower()
    target, attack, hits = "unknown", "unknown", None
    match = re.search(r"attacks?\s+(all enemies|(?:1|one) enemy)(?:\s+(\d+)\s+times?)?", mechanics, re.I)
    if match:
        target = "all_enemies" if match[1].lower() == "all enemies" else "one_enemy"
        attack, hits = ("aoe" if target == "all_enemies" else "single"), int(match[2] or 1)
    elif any(e["kind"] == "transform" for e in effects):
        target, attack = "self", "transform"
    elif any(e["kind"] == "revive" and e["target"] != "self" for e in effects):
        target, attack = next(e["target"] for e in effects if e["kind"] == "revive"), "ally_dead"
    elif "all allies" in low or "each ally" in low:
        target, attack = "all_allies", "self"
    elif "this champion" in low:
        target, attack = "self", "self"
    elif re.search(r"\b(?:an?|one|1) ally\b", low):
        target, attack = "one_ally", "ally_living"
    if attack in {"single", "aoe"}:
        tags = sorted(set(tags) | {"damage", attack})
    if passive or aura:
        attack = "passive" if passive else "aura"
    if not mechanics:
        review = sorted(set(review) | {"source_description_empty"})
    elif not effects and attack not in {"single", "aoe", "aura"}:
        review = sorted(set(review) | {"no_modeled_operation"})
    return {"name": name, "form": form, "cooldown_base": cooldown, "cooldown_booked": max(0, cooldown - cooldown_books) if cooldown is not None else None, "target_type": target, "attack_type": attack, "selection_target": "enemy" if match else "none" if passive or aura else "self" if attack in {"self", "transform"} else target, "hits": hits, "tags": tags, "effects": effects, "requirements": requirements, "review_flags": review, "clickable": not passive and not aura, "parser_version": PARSER_VERSION, "parse_confidence": 0.75 if not review else 0.55}
