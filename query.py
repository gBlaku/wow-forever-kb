"""Look up WoW Forever items a class can use at a given level.

Examples:
  py query.py --class hunter --level 40 --slot one-hand
  py query.py --class hunter --level 40 --slot ranged --sort agility
  py query.py --class rogue --level 30 --slot chest --min-quality rare
  py query.py --name "krol blade"
  py query.py --sql "select name, dps from visible_items where subclass='Dagger' order by dps desc limit 5"
"""
import argparse
import os
import sqlite3
import sys

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wow_forever.db")
CLASS_BIT = {"warrior": 1, "paladin": 2, "hunter": 3, "rogue": 4, "priest": 5,
             "shaman": 7, "mage": 8, "warlock": 9, "druid": 11}
SLOT_GROUPS = {
    "one-hand": ["One-Hand", "Main Hand", "Off Hand"],
    "1h": ["One-Hand", "Main Hand", "Off Hand"],
    "main-hand": ["One-Hand", "Main Hand"],
    "off-hand": ["One-Hand", "Off Hand", "Held In Off-hand", "Shield"],
    "two-hand": ["Two-Hand"], "2h": ["Two-Hand"],
    "weapon": ["One-Hand", "Main Hand", "Off Hand", "Two-Hand"],
    "ranged": ["Ranged", "Thrown"],
    "head": ["Head"], "neck": ["Neck"], "shoulder": ["Shoulder"], "back": ["Back"],
    "chest": ["Chest"], "wrist": ["Wrist"], "hands": ["Hands"], "waist": ["Waist"],
    "legs": ["Legs"], "feet": ["Feet"], "finger": ["Finger"], "ring": ["Finger"],
    "trinket": ["Trinket"], "shield": ["Shield"], "relic": ["Relic"],
}
QUALITY = {"poor": 0, "common": 1, "uncommon": 2, "green": 2, "rare": 3, "blue": 3,
           "epic": 4, "purple": 4, "legendary": 5}
STAT_FIELDS = ["agility", "strength", "stamina", "intellect", "spirit", "attack_power",
               "ranged_attack_power", "hit", "crit", "haste", "spell_power", "healing",
               "spell_damage", "mp5", "defense", "dodge", "parry", "block", "block_value",
               "bonus_armor", "fire_res", "frost_res", "nature_res", "shadow_res", "arcane_res"]
SHORT = {"agility": "Agi", "strength": "Str", "stamina": "Sta", "intellect": "Int",
         "spirit": "Spi", "attack_power": "AP", "ranged_attack_power": "RAP", "hit": "Hit",
         "crit": "Crit", "haste": "Haste", "spell_power": "SP", "healing": "Heal",
         "spell_damage": "SpellDmg", "mp5": "MP5", "defense": "Def", "dodge": "Dodge",
         "parry": "Parry", "block": "Block", "block_value": "BlockVal",
         "bonus_armor": "Armor", "fire_res": "FireRes", "frost_res": "FrostRes",
         "nature_res": "NatRes", "shadow_res": "ShadowRes", "arcane_res": "ArcRes"}


def stats_text(r):
    parts = [f"{r[f]:+d} {SHORT[f]}" for f in STAT_FIELDS if r[f]]
    if r["other_stats"]:
        parts.append(r["other_stats"])
    return ", ".join(parts)


def print_items(rows, verbose):
    if not rows:
        print("No items found.")
        return
    for r in rows:
        head = f"[{r['quality_name']}] {r['name']}  (ilvl {r['item_level']}, req {r['required_level']})"
        if r["estimated"]:
            head += "  *Classic data, Forever stats not published yet"
        kind = f"{r['slot']} {r['subclass']}"
        if r["dps"]:
            approx = "~" if r["dps_approx"] else ""
            kind += f" | {r['min_damage']}-{r['max_damage']} @ {r['speed']:.2f} = {approx}{r['dps']} dps"
        if r["armor"]:
            kind += f" | {r['armor']} armor"
        print(head)
        print(f"    {kind}")
        st = stats_text(r)
        if st:
            print(f"    {st}")
        if r["effects"]:
            print(f"    {r['effects']}")
        extra = [x for x in (r["bonding"], f"Classes: {r['classes']}" if r["classes"] else "",
                             f"Set: {r['item_set']}" if r["item_set"] else "") if x]
        if r["required_reputation"]:
            print(f"    Requires {r['required_reputation']}")
        if r["source_summary"]:
            for part in r["source_summary"].split(" | "):
                print(f"    > {part}")
        elif r["id"] >= 240000:
            print("    > Source: new WoW Forever item, not in the quest/drop database yet (see Wowhead)")
        if verbose and extra:
            print(f"    {' | '.join(extra)}")
        print(f"    {r['wowhead']}")


def list_quests(con, a):
    """Quests in a level range, each with the items it rewards."""
    where, params = ["1=1"], []
    if a.level:
        lo = a.min_level or max(1, a.level - 5)
        where.append("quest_level BETWEEN ? AND ?")
        params += [lo, a.level + 2]
        where.append("required_level <= ?")
        params.append(a.level)
    elif a.min_level:
        where.append("quest_level >= ?")
        params.append(a.min_level)
    if a.faction:
        where.append("faction IN ('Both', ?)")
        params.append(a.faction.capitalize())
    if a.cls:
        where.append("(classes IS NULL OR classes LIKE ?)")
        params.append(f"%{a.cls.capitalize()}%")
    if a.name:
        where.append("(name LIKE ? OR zone LIKE ?)")
        params += [f"%{a.name}%"] * 2
    quests = con.execute(f"SELECT * FROM quests WHERE {' AND '.join(where)} ORDER BY quest_level, zone, name",
                         params).fetchall()
    shown = 0
    for q in quests:
        rewards = con.execute("""SELECT i.* FROM item_sources s JOIN items i ON i.id = s.item_id
            WHERE s.kind = 'quest' AND s.source_id = ? AND i.hidden = 0 ORDER BY i.quality DESC, i.name""",
                              (q["id"],)).fetchall()
        if a.slot:
            rewards = [r for r in rewards if r["slot"] in SLOT_GROUPS[a.slot]]
        if not rewards and (a.slot or not a.verbose):
            continue  # default: only quests that reward items (use -v to see all)
        shown += 1
        if shown > a.limit:
            break
        tags = [q["zone"] or "?", q["faction"]] + ([q["classes"] + " only"] if q["classes"] else [])
        print(f"[{q['quest_level']}] {q['name']}  (pick up at {q['required_level']}; {', '.join(tags)})")
        if q["start_npc"]:
            print(f"    from {q['start_npc']}" + (f", turn in to {q['end_npc']}" if q["end_npc"] and q["end_npc"] != q["start_npc"] else ""))
        for r in rewards:
            bits = [f"{r['slot']} {r['subclass']}" if r["slot"] != "Non-equippable" else r["item_class"]]
            if r["dps"]:
                bits.append(f"{r['dps']} dps")
            if r["armor"]:
                bits.append(f"{r['armor']} armor")
            st = stats_text(r)
            if st:
                bits.append(st)
            usable = ""
            if a.cls and r["item_class"] in ("Weapon", "Armor"):
                ok = con.execute("""SELECT 1 FROM items WHERE id = ? AND (class_mask IN (-1,0) OR class_mask & ? != 0) AND (
                    (item_class='Weapon' AND subclass IN (SELECT subclass FROM proficiency WHERE class=?)) OR
                    (item_class='Armor' AND (slot IN ('Neck','Finger','Trinket','Back','Shirt','Tabard','Held In Off-hand')
                      OR subclass IN (SELECT armor FROM armor_proficiency WHERE class=? AND from_level <= ?))))""",
                                 (r["id"], 1 << (CLASS_BIT[a.cls] - 1), a.cls.capitalize(), a.cls.capitalize(),
                                  a.level or 60)).fetchone()
                usable = "" if ok else "  (can't use)"
            print(f"    - [{r['quality_name']}] {r['name']}: {', '.join(bits)}{usable}")
        print(f"    {q['wowhead']}")
    if not shown:
        print("No quests found.")
    print("\nNote: quest data is Classic Era content from the Questie addon; new WoW Forever quests are not included yet.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--class", dest="cls", choices=sorted(CLASS_BIT))
    ap.add_argument("--level", type=int, help="character level (max required level)")
    ap.add_argument("--min-level", type=int, default=0, help="minimum required level")
    ap.add_argument("--any-ilvl", action="store_true",
                    help="with --level, also show no-requirement items meant for higher levels (raid loot, high quests)")
    ap.add_argument("--source", choices=["quest", "drop", "vendor", "crafted", "object", "container"],
                    help="only items obtainable this way")
    ap.add_argument("--quests", action="store_true",
                    help="list quests (with their item rewards) for --level / --min-level, --class, --faction, --name")
    ap.add_argument("--faction", choices=["alliance", "horde"], help="with --quests: your faction")
    ap.add_argument("--slot", choices=sorted(SLOT_GROUPS))
    ap.add_argument("--type", help="subclass filter, e.g. Dagger, Bow, Leather, 'One-Handed Sword'")
    ap.add_argument("--min-quality", choices=sorted(QUALITY), default="uncommon")
    ap.add_argument("--stat", help="only items with this stat, e.g. agility, attack_power")
    ap.add_argument("--sort", default=None, help="dps, item_level, required_level or any stat (default: dps for weapons, item_level otherwise)")
    ap.add_argument("--name", help="search by name (substring)")
    ap.add_argument("--limit", type=int, default=25)
    ap.add_argument("--include-junk", action="store_true", help="include test/deprecated items")
    ap.add_argument("--sql", help="run raw SQL against the database")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    if a.sql:
        cur = con.execute(a.sql)
        cols = [d[0] for d in cur.description]
        print(" | ".join(cols))
        for row in cur:
            print(" | ".join("" if v is None else str(v) for v in row))
        return

    if a.quests:
        return list_quests(con, a)

    where, params = ["hidden = 0"], []
    if not a.include_junk:
        where.append("junk = 0")
    if a.name:
        where.append("name LIKE ?")
        params.append(f"%{a.name}%")
    else:
        where.append("quality >= ?")
        params.append(QUALITY[a.min_quality])
    # level_hint = the level an item is really for: its required level, or for items with
    # no requirement the quest level / drop level of its source, or item level - 5.
    if a.level:
        where.append("required_level <= ?")
        params.append(a.level)
        if not a.any_ilvl:
            where.append("level_hint <= ?")
            params.append(a.level + 2)
    if a.min_level:
        where.append("level_hint >= ?")
        params.append(a.min_level)
    if a.source:
        where.append("source_types LIKE ?")
        params.append(f"%{a.source}%")
    if a.slot:
        slots = SLOT_GROUPS[a.slot]
        where.append(f"slot IN ({','.join('?' * len(slots))})")
        params += slots
    if a.type:
        where.append("subclass LIKE ?")
        params.append(f"%{a.type}%")
    if a.stat:
        if a.stat not in STAT_FIELDS:
            sys.exit(f"Unknown stat. Choose from: {', '.join(STAT_FIELDS)}")
        where.append(f"{a.stat} > 0")
    if a.cls:
        bit = 1 << (CLASS_BIT[a.cls] - 1)
        cname = a.cls.capitalize()
        lvl = a.level or 60
        where.append("(class_mask IN (-1, 0) OR (class_mask & ?) != 0)")
        params.append(bit)
        # Weapons: class must have the proficiency. Armor: armor type allowed at this level.
        where.append("""(
            (item_class = 'Weapon' AND subclass IN (SELECT subclass FROM proficiency WHERE class = ?))
            OR (item_class = 'Armor' AND (slot IN ('Neck','Finger','Trinket','Back','Shirt','Tabard','Held In Off-hand')
                 OR subclass IN (SELECT armor FROM armor_proficiency WHERE class = ? AND from_level <= ?)))
            OR item_class NOT IN ('Weapon', 'Armor'))""")
        params += [cname, cname, lvl]

    is_weapon = a.slot in ("one-hand", "1h", "main-hand", "two-hand", "2h", "weapon", "ranged")
    sort = a.sort or ("dps" if is_weapon else "item_level")
    if sort not in STAT_FIELDS + ["dps", "item_level", "required_level", "armor", "quality"]:
        sys.exit(f"Can't sort by {sort}")
    order = f"{sort} DESC NULLS LAST, item_level DESC" if sqlite3.sqlite_version_info >= (3, 30) \
        else f"{sort} IS NULL, {sort} DESC, item_level DESC"
    sql = f"SELECT * FROM items WHERE {' AND '.join(where)} ORDER BY {order} LIMIT ?"
    rows = con.execute(sql, params + [a.limit]).fetchall()
    print_items(rows, a.verbose)

    hidden = con.execute("SELECT COUNT(*) FROM items WHERE hidden = 1" +
                         (" AND slot IN (%s)" % ",".join("?" * len(SLOT_GROUPS[a.slot])) if a.slot else ""),
                         SLOT_GROUPS[a.slot] if a.slot else []).fetchone()[0]
    if hidden and not a.name:
        print(f"\nNote: {hidden} items{' in this slot' if a.slot else ''} (all levels) are hidden by "
              f"Blizzard until discovered in-game, so they have no name/stats in the client data. "
              f"Re-run download_data.py after patches.")


if __name__ == "__main__":
    main()
