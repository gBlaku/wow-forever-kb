"""Write AI-friendly Markdown pages into site/ so anyone can point Claude (or another
assistant) at one link and ask questions like "best weapons for a level 40 hunter".

site/llms.txt                   entry point: what this is, how to answer, links to everything
site/ai/<class>.md              class rules + links to every level page
site/ai/<class>/<level>.md      best items per slot at that level + quests with rewards
site/ai/item/<id>.md            one item: full stats and every way to get it
site/ai/zones.md                dungeons/raids/zones with notable loot
site/ai/zone/<slug>.md          bosses and rares in a zone and what they drop
site/ai/names/<letter>.md       item name index -> item pages

Every link is written out in full, because AI fetch tools only open URLs they have seen.
Run after build_db.py (and after export_api.py, which recreates site/).
"""
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from questie_sources import money  # noqa: E402
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(HERE, "site")
BASE = "https://gblaku.github.io/wow-forever-kb/"
CLASSES = {"Warrior": 1, "Paladin": 2, "Hunter": 3, "Rogue": 4, "Priest": 5,
           "Shaman": 7, "Mage": 8, "Warlock": 9, "Druid": 11}
ALWAYS_OK = {"Neck", "Finger", "Trinket", "Back", "Shirt", "Tabard", "Held In Off-hand"}
DUAL_WIELD = {"Warrior", "Rogue", "Hunter"}
SHIELD = {"Warrior", "Paladin", "Shaman"}
CASTER_OFFHAND = {"Priest", "Mage", "Warlock", "Druid", "Shaman", "Paladin"}

# Rough per-point stat values for a typical damage/heal build of each class. They only
# order the lists; the pages show every stat so the reader (or AI) can judge for a spec.
W = {
    "Warrior": dict(str=1.0, agi=0.7, sta=0.4, ap=0.5, crit=10, hit=10, defense=0.3, melee=3.0, ranged=0.5),
    "Paladin": dict(str=1.0, int=0.7, sta=0.4, spi=0.2, sp=0.8, heal=0.5, ap=0.5, crit=8, mp5=1.0, melee=2.5),
    "Hunter": dict(agi=1.0, ap=0.5, rap=0.5, int=0.3, sta=0.3, crit=10, hit=10, melee=0.3, ranged=3.0),
    "Rogue": dict(agi=1.0, str=0.5, ap=0.5, sta=0.3, crit=10, hit=10, melee=3.0, ranged=0.3),
    "Priest": dict(int=1.0, spi=0.8, sp=0.9, heal=0.6, sta=0.3, mp5=1.0, crit=5),
    "Shaman": dict(int=0.8, str=0.6, agi=0.4, sp=0.8, heal=0.5, ap=0.4, sta=0.3, mp5=0.8, crit=8, melee=2.0),
    "Mage": dict(int=1.0, sp=1.0, spi=0.4, sta=0.3, crit=10, hit=10),
    "Warlock": dict(int=0.8, sta=0.6, sp=1.0, spi=0.3, crit=8, hit=10),
    "Druid": dict(int=0.7, agi=0.6, str=0.6, spi=0.5, sp=0.8, heal=0.5, sta=0.4, ap=0.4, mp5=0.8, crit=8),
}
STAT_LABEL = [("agility", "Agi"), ("strength", "Str"), ("stamina", "Sta"), ("intellect", "Int"),
              ("spirit", "Spi"), ("attack_power", "AP"), ("ranged_attack_power", "RAP"), ("hit", "Hit"),
              ("crit", "Crit"), ("haste", "Haste"), ("spell_power", "SP"), ("healing", "Healing"),
              ("spell_damage", "Spell dmg"), ("mp5", "MP5"), ("defense", "Def"), ("dodge", "Dodge"),
              ("parry", "Parry"), ("block", "Block"), ("block_value", "Block value"),
              ("bonus_armor", "Armor"), ("fire_res", "Fire res"), ("frost_res", "Frost res"),
              ("nature_res", "Nature res"), ("shadow_res", "Shadow res"), ("arcane_res", "Arcane res")]
SLOT_ORDER = ["Head", "Neck", "Shoulder", "Back", "Chest", "Wrist", "Hands", "Waist", "Legs", "Feet",
              "Finger", "Trinket", "Main hand", "Off hand", "Two-hand", "Ranged"]


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "unknown"


def stat_line(it):
    parts = [f"{it[k]:+d} {lbl}" for k, lbl in STAT_LABEL if it.get(k)]
    if it.get("other_stats"):
        parts.append(it["other_stats"])
    return ", ".join(parts)


def effect_values(it):
    """Stats that Classic items carry as Equip effects."""
    fx = it.get("effects") or ""
    v = defaultdict(float)
    for m in re.finditer(r"\+(\d+) (Ranged )?Attack Power", fx):
        v["rap" if m.group(2) else "ap"] += int(m.group(1))
    for m in re.finditer(r"magical spells and effects by up to (\d+)", fx):
        v["sp"] += int(m.group(1))
    for m in re.finditer(r"healing done by spells and effects by up to (\d+)", fx):
        v["heal"] += int(m.group(1))
    for m in re.finditer(r"(\d+) mana (?:every|per) 5 sec", fx):
        v["mp5"] += int(m.group(1))
    # only general bonuses ("Improves your chance to get a critical strike [with spells] by 1%"),
    # not ones tied to a single spell ("critical strike chance of your Healing Wave")
    for m in re.finditer(r"Improves your chance to get a critical strike([^.|]*?) by (\d+)%", fx):
        v["spell_crit" if "spell" in m.group(1) else "crit"] += int(m.group(2))
    for m in re.finditer(r"Improves your chance to hit([^.|]*?) by (\d+)%", fx):
        v["spell_hit" if "spell" in m.group(1) else "hit"] += int(m.group(2))
    return v


CASTERS = {"Priest", "Mage", "Warlock"}


def score(it, cls, slot_group):
    w = W[cls]
    fx = effect_values(it)
    s = (w.get("str", 0) * (it.get("strength") or 0) + w.get("agi", 0) * (it.get("agility") or 0)
         + w.get("sta", 0) * (it.get("stamina") or 0) + w.get("int", 0) * (it.get("intellect") or 0)
         + w.get("spi", 0) * (it.get("spirit") or 0)
         + w.get("ap", 0) * ((it.get("attack_power") or 0) + fx["ap"])
         + w.get("rap", 0) * ((it.get("ranged_attack_power") or 0) + fx["rap"])
         + w.get("sp", 0) * ((it.get("spell_power") or 0) + (it.get("spell_damage") or 0) + fx["sp"])
         + w.get("heal", 0) * ((it.get("healing") or 0) + fx["heal"])
         + w.get("mp5", 0) * ((it.get("mp5") or 0) + fx["mp5"])
         + w.get("defense", 0) * (it.get("defense") or 0)
         # Forever crit/hit are small rating numbers; Classic ones are % from effects
         + w.get("crit", 0) * ((it.get("crit") or 0) / 10
                               + (fx["spell_crit"] if cls in CASTERS else fx["crit"]))
         + w.get("hit", 0) * ((it.get("hit") or 0) / 10
                              + (fx["spell_hit"] if cls in CASTERS else fx["hit"])))
    if it.get("dps"):
        if slot_group == "Ranged":
            s += w.get("ranged", 0) * it["dps"]
        elif slot_group in ("Main hand", "Two-hand"):
            s += w.get("melee", 0) * it["dps"] * (1.0 if slot_group == "Main hand" else 1.3)
        elif slot_group == "Off hand":
            s += w.get("melee", 0) * it["dps"] * 0.5
    return s


def main():
    con = sqlite3.connect(os.path.join(HERE, "wow_forever.db"))
    con.row_factory = sqlite3.Row
    build = con.execute("SELECT value FROM meta WHERE key='build'").fetchone()[0]
    items = {r["id"]: dict(r) for r in con.execute("SELECT * FROM visible_items")}
    prof = defaultdict(set)
    for c, s in con.execute("SELECT class, subclass FROM proficiency"):
        prof[c].add(s)
    armor = defaultdict(dict)
    for c, a, lvl in con.execute("SELECT class, armor, from_level FROM armor_proficiency"):
        armor[c][a] = lvl
    sources = defaultdict(list)
    for r in con.execute("SELECT * FROM item_sources ORDER BY chance DESC"):
        sources[r["item_id"]].append(dict(r))
    quests = {r["id"]: dict(r) for r in con.execute("SELECT * FROM quests")}
    quest_rewards = defaultdict(list)
    for r in con.execute("SELECT source_id, item_id FROM item_sources WHERE kind = 'quest'"):
        if r["item_id"] in items:
            quest_rewards[r["source_id"]].append(r["item_id"])

    def giver_text(q):
        if not q.get("start_npc"):
            return ""
        out = f"; quest giver {q['start_npc']}{' in ' + q['start_where'] if q.get('start_where') else ''}"
        if q.get("end_npc") and q["end_npc"] != q["start_npc"]:
            out += f", turn in to {q['end_npc']}{' in ' + q['end_where'] if q.get('end_where') else ''}"
        return out

    def item_url(i):
        return f"{BASE}ai/item/{i}.md"

    def usable(it, cls, level):
        mask = it.get("class_mask")
        if not (mask in (-1, 0, None) or mask & (1 << (CLASSES[cls] - 1))):
            return False
        if it["item_class"] == "Weapon":
            return it["subclass"] in prof[cls]
        if it["item_class"] == "Armor":
            if it["slot"] in ALWAYS_OK:
                return True
            lvl = armor[cls].get(it["subclass"])
            return lvl is not None and lvl <= level
        return False

    def slot_group(it, cls):
        """Which of the class's equipment slots this item can go in (an item can fit two)."""
        s = it["slot"]
        if s in ("Head", "Neck", "Shoulder", "Back", "Chest", "Wrist", "Hands", "Waist", "Legs", "Feet",
                 "Finger", "Trinket"):
            return [s]
        if s == "Two-Hand":
            return ["Two-hand"]
        if s == "Main Hand":
            return ["Main hand"]
        if s == "One-Hand":
            return ["Main hand", "Off hand"] if cls in DUAL_WIELD else ["Main hand"]
        if s == "Off Hand":
            return ["Off hand"] if cls in DUAL_WIELD else []
        if s == "Shield":
            return ["Off hand"] if cls in SHIELD else []
        if s == "Held In Off-hand":
            return ["Off hand"] if cls in CASTER_OFFHAND else []
        if s in ("Ranged", "Thrown", "Relic"):
            return ["Ranged"]
        return []

    def short_source(it):
        src = it.get("source_summary")
        if src:
            return src if len(src) <= 220 else src[:217] + "..."
        if it["id"] >= 200000:
            return "New WoW Forever item; source not in the data yet (check Wowhead)"
        return "Source unknown (check Wowhead)"

    def item_line(it, extra=""):
        bits = [f"{it['quality_name']}", f"ilvl {it['item_level']}", f"req {it['required_level'] or '-'}"]
        kind = f"{it['slot']} {it['subclass']}".strip()
        if it.get("dps"):
            kind += f", {it['min_damage']}-{it['max_damage']} dmg, {it['speed']:.2f} speed, {it['dps']} dps"
        if it.get("armor"):
            kind += f", {it['armor']} armor"
        out = f"- **[{it['name']}]({item_url(it['id'])})** ({', '.join(bits)}) {kind}"
        st = stat_line(it)
        if st:
            out += f". {st}"
        if it.get("effects"):
            fx = it["effects"]
            out += f". {fx if len(fx) <= 200 else fx[:197] + '...'}"
        if it.get("required_reputation"):
            out += f". Requires {it['required_reputation']}"
        out += f"\n  - Get: {short_source(it)}"
        flags = []
        if it.get("estimated"):
            flags.append("Classic data: hidden in Forever so far, stats may differ")
        if not it.get("source_types") and it["quality"] >= 4:
            flags.append("no known source, may not be obtainable")
        if flags:
            out += f"\n  - Note: {'; '.join(flags)}"
        return out + extra

    def write(path, text):
        full = os.path.join(SITE, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(text.rstrip() + "\n")

    footer = (f"\n---\nData: WoW Forever client build {build}, rebuilt daily. "
              f"Start page for assistants: {BASE}llms.txt · Search site: {BASE}\n")

    # ------------------------------------------------------------ item pages + name index
    by_letter = defaultdict(list)
    for it in items.values():
        L = [f"# {it['name']}", "",
             f"- Wowhead: https://www.wowhead.com/forever/item={it['id']}",
             f"- Item ID {it['id']} · {it['quality_name']} · item level {it['item_level']} · "
             f"required level {it['required_level'] or 'none'} · meant for about level {it['level_hint']}",
             f"- {it['slot']} · {it['item_class']} · {it['subclass']}"]
        if it.get("dps"):
            L.append(f"- {it['min_damage']}-{it['max_damage']} damage, speed {it['speed']:.2f}, "
                     f"{'about ' if it.get('dps_approx') else ''}{it['dps']} damage per second")
        if it.get("armor"):
            L.append(f"- {it['armor']} armor")
        st = stat_line(it)
        if st:
            L.append(f"- Stats: {st}")
        if it.get("effects"):
            L.append(f"- Effects: {it['effects']}")
        for k, lbl in (("classes", "Classes"), ("bonding", "Binding"), ("item_set", "Set"),
                       ("required_reputation", "Requires")):
            if it.get(k):
                L.append(f"- {lbl}: {it[k]}")
        users = [c for c in CLASSES if usable(it, c, 60)]
        if it["item_class"] in ("Weapon", "Armor"):
            L.append(f"- Classes that can use it: {', '.join(users) if users else 'none'}")
        if it.get("estimated"):
            L.append("- Note: hidden in the WoW Forever client so far. Name, level and stats are from "
                     "Classic; damage and armor use the Forever formulas. The real item may differ.")
        L += ["", "## How to get it"]
        srcs = sources.get(it["id"], [])
        if not srcs:
            L.append(short_source(it))
        for s in srcs[:30]:
            if s["kind"] == "quest":
                q = quests.get(s["source_id"], {})
                L.append(f"- Quest reward: **{s['name']}** (quest level {s['max_level']}, pick up at "
                         f"{s['min_level']}, {s['zone'] or '?'}, {q.get('faction', '?')}"
                         f"{', ' + q['classes'] + ' only' if q.get('classes') else ''})"
                         f"{giver_text(q)} https://www.wowhead.com/forever/quest={s['source_id']}")
            elif s["kind"] == "drop" and s["source_id"]:
                lv = f"level {s['min_level']}" + (f"-{s['max_level']}" if s['max_level'] and s['max_level'] != s['min_level'] else "")
                L.append(f"- Drop: **{s['name']}** ({lv}{' ' + s['extra'] if s['extra'] else ''}, "
                         f"{s['zone'] or '?'}, {s['chance']:.3g}% per kill) "
                         f"https://www.wowhead.com/forever/npc={s['source_id']}")
            elif s["kind"] == "drop":
                L.append(f"- World drop: {s['extra']}, level {s['min_level']}-{s['max_level']}, "
                         f"up to {s['chance']:.2g}% per kill")
            elif s["kind"] == "vendor":
                L.append(f"- Vendor: **{s['name']}**{' (' + s['extra'] + ')' if s['extra'] else ''}, "
                         f"{s['zone'] or '?'}{', costs ' + money(it['buy_price_copper']) if it.get('buy_price_copper') else ''}"
                         f" https://www.wowhead.com/forever/npc={s['source_id']}")
            elif s["kind"] == "object":
                chance = f", {s['chance']:.3g}%" if s["chance"] else ""
                L.append(f"- Chest/object: **{s['name']}**{', ' + s['zone'] if s['zone'] else ''}{chance}")
            elif s["kind"] == "crafted":
                L.append(f"- Crafted: {s['name']} {s['min_level'] or ''} ({s['extra']}) "
                         f"https://www.wowhead.com/forever/spell={s['source_id']}")
            elif s["kind"] == "container":
                L.append(f"- Found inside: {s['name']} https://www.wowhead.com/forever/item={s['source_id']}")
        if len(srcs) > 30:
            L.append(f"- ...and {len(srcs) - 30} more sources")
        write(f"ai/item/{it['id']}.md", "\n".join(L) + footer)
        first = it["name"][:1].lower()
        key = first if first.isalpha() and first.isascii() else "0"
        by_letter[key].append(it)

    letters = sorted(by_letter)
    for key in letters:
        lst = sorted(by_letter[key], key=lambda i: i["name"].lower())
        L = [f"# Item names starting with {key.upper() if key != '0' else 'a digit or symbol'}", "",
             "Name · slot/type · required level · link", ""]
        L += [f"- [{i['name']}]({item_url(i['id'])}) · {i['slot']} {i['subclass']} · req {i['required_level'] or '-'}"
              for i in lst]
        write(f"ai/names/{key}.md", "\n".join(L) + footer)

    # ------------------------------------------------------------ zones
    zone_creatures = defaultdict(lambda: defaultdict(list))
    zone_levels = defaultdict(list)
    for iid, lst in sources.items():
        it = items.get(iid)
        if not it or it["quality"] < 2 or it["slot"] == "Non-equippable":
            continue
        for s in lst:
            if s["kind"] == "drop" and s["source_id"] and s["zone"] and (s["chance"] or 0) >= 1:
                zone_creatures[s["zone"]][(s["name"], s["source_id"], s["min_level"], s["max_level"], s["extra"])].append((s["chance"], it))
                if s["min_level"]:
                    zone_levels[s["zone"]].append(s["min_level"])
    zone_rows = []
    for zone, creatures in zone_creatures.items():
        lv = zone_levels[zone]
        zone_rows.append((min(lv) if lv else 0, max(lv) if lv else 0, zone))
        L = [f"# {zone}: bosses, rares and their loot", "",
             "Uncommon or better gear that drops at 1% or more, by creature. Chances are per kill "
             "(Classic loot tables).", ""]
        for (name, nid, lo, hi, extra), loot in sorted(creatures.items(), key=lambda kv: kv[0][2] or 0):
            lvl = f"level {lo}" + (f"-{hi}" if hi and hi != lo else "")
            L.append(f"## {name} ({lvl}{' ' + extra if extra else ''})")
            L.append(f"https://www.wowhead.com/forever/npc={nid}")
            L.append("")
            for chance, it in sorted(loot, key=lambda x: -x[0]):
                st = stat_line(it)
                kind = f"{it['slot']} {it['subclass']}"
                if it.get("dps"):
                    kind += f", {it['dps']} dps"
                L.append(f"- [{it['name']}]({item_url(it['id'])}) ({chance:.3g}%) {it['quality_name']}, req "
                         f"{it['required_level'] or '-'}, {kind}{'. ' + st if st else ''}"
                         f"{' (Classic data)' if it.get('estimated') else ''}")
            L.append("")
        write(f"ai/zone/{slug(zone)}.md", "\n".join(L) + footer)
    L = ["# Zones, dungeons and raids with notable loot", "",
         "Creature level range · zone page (bosses, rares and their drops)", ""]
    for lo, hi, zone in sorted(zone_rows):
        L.append(f"- {lo}-{hi}: [{zone}]({BASE}ai/zone/{slug(zone)}.md)")
    write("ai/zones.md", "\n".join(L) + footer)

    # ------------------------------------------------------------ class and level pages
    gear = [it for it in items.values() if it["quality"] >= 1 and it["slot"] != "Non-equippable"
            and it["item_class"] in ("Weapon", "Armor")]
    for cls in CLASSES:
        cslug = cls.lower()
        weapons = sorted(prof[cls])
        arm = ", ".join(f"{a} (from level {l})" if l > 1 else a for a, l in sorted(armor[cls].items(), key=lambda x: x[1])
                        if a in ("Cloth", "Leather", "Mail", "Plate", "Shield", "Libram", "Idol", "Totem"))
        weights = ", ".join(f"{k} {v:g}" for k, v in W[cls].items())
        L = [f"# {cls}: gear by level (WoW Forever)", "",
             f"- Weapons: {', '.join(weapons)}",
             f"- Armor: {arm}",
             f"- Dual wield: {'yes' if cls in DUAL_WIELD else 'no'}",
             f"- Lists are ordered by these rough per-point values: {weights} "
             "(melee/ranged = per point of weapon DPS). Adjust for the player's spec.",
             "", "## Pick a level", ""]
        L += [f"- [{cls} level {lv}]({BASE}ai/{cslug}/{lv}.md)" for lv in range(1, 61)]
        write(f"ai/{cslug}.md", "\n".join(L) + footer)

        fits = []
        for it in gear:
            if not usable(it, cls, 60):
                continue
            for g in slot_group(it, cls):
                fits.append((g, it))
        for lv in range(1, 61):
            per_slot = defaultdict(list)
            for g, it in fits:
                if (it["required_level"] or 0) > lv or (it["level_hint"] or 0) > lv + 2:
                    continue
                if it["item_class"] == "Armor" and it["slot"] not in ALWAYS_OK and not usable(it, cls, lv):
                    continue
                per_slot[g].append((score(it, cls, g), it))
            L = [f"# {cls}, level {lv}: best gear by slot (WoW Forever)", "",
                 f"Items a level {lv} {cls.lower()} can equip, best first by a rough stat score for a typical "
                 f"{cls.lower()} build (see the class page for the weights). Includes items up to 2 levels above "
                 "via no-requirement quest rewards and drops. Each item shows how to get it; open the item link "
                 "for every source and drop chance. Prefer items with a known source.", ""]
            for g in SLOT_ORDER:
                # epics/legendaries with no known source (e.g. odd level-scaled copies) go last
                lst = sorted(per_slot.get(g, []), key=lambda x: (
                    1 if (not x[1].get("source_types") and x[1]["quality"] >= 4) else 0,
                    -x[0], -x[1]["item_level"]))
                if not lst:
                    continue
                n = 8 if g in ("Finger", "Trinket", "Main hand") else 6
                L.append(f"## {g}")
                L += [item_line(it) for _, it in lst[:n]]
                L.append("")
            qlo, qhi = max(1, lv - 3), lv + 2
            qs = [q for q in quests.values() if q["quest_level"] and qlo <= q["quest_level"] <= qhi
                  and (q["required_level"] or 0) <= lv and (not q["classes"] or cls in q["classes"])]
            qlines = []
            for q in sorted(qs, key=lambda q: (q["quest_level"], q["zone"] or "", q["name"])):
                rw = [items[i] for i in quest_rewards.get(q["id"], [])
                      if items[i]["item_class"] in ("Weapon", "Armor") and usable(items[i], cls, lv)]
                if not rw:
                    continue
                rtxt = "; ".join(f"[{i['name']}]({item_url(i['id'])}) ({i['slot']} {i['subclass']}"
                                 f"{', ' + str(i['dps']) + ' dps' if i.get('dps') else ''}"
                                 f"{', ' + stat_line(i) if stat_line(i) else ''})" for i in rw)
                qlines.append(f"- [{q['quest_level']}] **{q['name']}** ({q['zone'] or '?'}, {q['faction']}, "
                              f"pick up at {q['required_level']}{giver_text(q)}): {rtxt} "
                              f"https://www.wowhead.com/forever/quest={q['id']}")
            if qlines:
                L.append(f"## Quests at quest level {qlo}-{qhi} with gear a {cls.lower()} can use")
                L.append("Faction shows who can take the quest. Classic quest data; new Forever quests are missing.")
                L += qlines
                L.append("")
            nav = [f"[{cls} page]({BASE}ai/{cslug}.md)"]
            if lv > 1:
                nav.append(f"[level {lv - 1}]({BASE}ai/{cslug}/{lv - 1}.md)")
            if lv < 60:
                nav.append(f"[level {lv + 1}]({BASE}ai/{cslug}/{lv + 1}.md)")
            nav.append(f"[dungeons and loot]({BASE}ai/zones.md)")
            L.append("More: " + " · ".join(nav))
            write(f"ai/{cslug}/{lv}.md", "\n".join(L) + footer)

    # ------------------------------------------------------------ llms.txt
    L = ["# WoW Forever Armory",
         "",
         "> Item, quest-reward and boss-loot data for World of Warcraft: Forever, built from the game "
         "client's data plus the Questie and vmangos databases and rebuilt daily. Use it to answer gear "
         "questions such as \"best weapons for a level 40 hunter\", \"what drops in Uldaman\" or "
         "\"how do I get Ravager\".",
         "",
         "## How to answer",
         "",
         "1. Gear for a class and level: open that class's page below, then the level page it links to "
         "(for example a level 40 hunter: " + f"{BASE}ai/hunter/40.md" + "). It lists the best items per "
         "slot with stats and how to get each one, plus quests with rewards.",
         "2. One item: open its item page (linked from every list, or find it in the name index below) "
         "for full stats, every source and drop chances.",
         "3. A dungeon, raid or zone: open the zone list and then that zone's page for bosses and loot.",
         "4. Rankings use rough stat values for a typical build. Adjust for the player's spec, faction "
         "(quest rewards show Alliance/Horde/Both) and what they can realistically get. Prefer items "
         "with a known source. Hunters care most about their ranged weapon; melee weapons are mainly "
         "stat sticks for them.",
         "5. Say which items are marked \"Classic data\": Blizzard hides those in WoW Forever so far, so "
         "their stats come from Classic and may change. Quests, drops and vendors are Classic data "
         "too, so content new in Forever is missing. Every item has a Wowhead link for the latest info.",
         "",
         "## Classes",
         ""]
    L += [f"- [{c}]({BASE}ai/{c.lower()}.md): weapon/armor rules and links to levels 1-60" for c in CLASSES]
    L += ["", "## Zones and dungeons", "", f"- [All zones, dungeons and raids with notable loot]({BASE}ai/zones.md)",
          "", "## Find an item by name", ""]
    L += [f"- [{k.upper() if k != '0' else '0-9 and symbols'}]({BASE}ai/names/{k}.md)" for k in letters]
    L += ["", "## Raw data (for code, not for reading)", "",
          f"- [meta.json]({BASE}api/meta.json): build, counts, file list",
          f"- [items.csv]({BASE}api/items.csv), [item_sources.csv]({BASE}api/item_sources.csv), "
          f"[quests.csv]({BASE}api/quests.csv): full tables (several MB)",
          f"- [wow_forever.db]({BASE}wow_forever.db): SQLite database",
          f"- Docs and code: https://github.com/gBlaku/wow-forever-kb",
          "", f"Data: WoW Forever client build {build}. Not affiliated with Blizzard Entertainment."]
    write("llms.txt", "\n".join(L))

    n_files = sum(len(fs) for _, _, fs in os.walk(os.path.join(SITE, "ai")))
    print(f"AI pages: {n_files} files under site/ai plus site/llms.txt")


if __name__ == "__main__":
    main()
