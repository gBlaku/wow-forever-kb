"""Build wow_forever.db (SQLite) from the WoW Forever client tables in ./data.

Data source: the game's own DB2 tables, exported as CSV by wago.tools
(product "wowf"). Re-download with:  python download_data.py
Then rebuild with:                  python build_db.py
"""
import csv
import math
import os
import re
import sqlite3
import sys

csv.field_size_limit(10_000_000)
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
DB_PATH = os.path.join(HERE, "wow_forever.db")


def load(name, key="ID"):
    with open(os.path.join(DATA, name + ".csv"), encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    return {r[key]: r for r in rows} if key else rows


CLASSES = {1: "Warrior", 2: "Paladin", 3: "Hunter", 4: "Rogue", 5: "Priest",
           7: "Shaman", 8: "Mage", 9: "Warlock", 11: "Druid"}
QUALITY = {0: "Poor", 1: "Common", 2: "Uncommon", 3: "Rare", 4: "Epic",
           5: "Legendary", 6: "Artifact", 7: "Heirloom"}
BONDING = {0: "", 1: "Binds when picked up", 2: "Binds when equipped",
           3: "Binds when used", 4: "Quest item"}
SLOTS = {0: "Non-equippable", 1: "Head", 2: "Neck", 3: "Shoulder", 4: "Shirt",
         5: "Chest", 6: "Waist", 7: "Legs", 8: "Feet", 9: "Wrist", 10: "Hands",
         11: "Finger", 12: "Trinket", 13: "One-Hand", 14: "Shield", 15: "Ranged",
         16: "Back", 17: "Two-Hand", 18: "Bag", 19: "Tabard", 20: "Chest",
         21: "Main Hand", 22: "Off Hand", 23: "Held In Off-hand", 24: "Ammo",
         25: "Thrown", 26: "Ranged", 27: "Quiver", 28: "Relic"}
# Full subclass names (ItemSubClass only gives "Axe" for both 1H and 2H)
WEAPON_SUBCLASS = {0: "One-Handed Axe", 1: "Two-Handed Axe", 2: "Bow", 3: "Gun",
                   4: "One-Handed Mace", 5: "Two-Handed Mace", 6: "Polearm",
                   7: "One-Handed Sword", 8: "Two-Handed Sword", 9: "Warglaive",
                   10: "Staff", 11: "Exotic", 12: "Exotic", 13: "Fist Weapon",
                   14: "Miscellaneous", 15: "Dagger", 16: "Thrown", 17: "Spear",
                   18: "Crossbow", 19: "Wand", 20: "Fishing Pole"}
STATS = {0: "mana", 1: "health", 3: "agility", 4: "strength", 5: "intellect",
         6: "spirit", 7: "stamina", 12: "defense", 13: "dodge", 14: "parry",
         15: "block", 16: "hit_melee", 17: "hit_ranged", 18: "hit_spell",
         19: "crit_melee", 20: "crit_ranged", 21: "crit_spell", 31: "hit",
         32: "crit", 35: "resilience", 36: "haste", 37: "expertise",
         38: "attack_power", 39: "ranged_attack_power", 41: "healing",
         42: "spell_damage", 43: "mp5", 45: "spell_power", 46: "hp5",
         47: "spell_penetration", 48: "block_value", 49: "mastery",
         50: "bonus_armor", 51: "fire_res", 52: "frost_res", 53: "holy_res",
         54: "shadow_res", 55: "nature_res", 56: "arcane_res"}
STAT_COLUMNS = ["agility", "strength", "stamina", "intellect", "spirit",
                "attack_power", "ranged_attack_power", "hit", "crit", "haste",
                "spell_power", "healing", "spell_damage", "mp5", "defense",
                "dodge", "parry", "block", "block_value", "bonus_armor",
                "fire_res", "frost_res", "nature_res", "shadow_res", "arcane_res"]
CLASSIC_STATS = {3: "agility", 4: "strength", 5: "intellect", 6: "spirit", 7: "stamina"}
REP_RANKS = {0: "Hated", 1: "Hostile", 2: "Unfriendly", 3: "Neutral", 4: "Friendly",
             5: "Honored", 6: "Revered", 7: "Exalted"}
TRIGGER = {0: "Use", 1: "Equip", 2: "Chance on hit", 4: "Soulstone", 5: "Use", 6: "Learn"}

# Classic weapon proficiencies (trainable). WoW Forever may change these.
PROFICIENCY = {
    "Warrior": ["One-Handed Axe", "Two-Handed Axe", "One-Handed Mace", "Two-Handed Mace",
                "One-Handed Sword", "Two-Handed Sword", "Polearm", "Staff", "Dagger",
                "Fist Weapon", "Bow", "Gun", "Crossbow", "Thrown"],
    "Paladin": ["One-Handed Axe", "Two-Handed Axe", "One-Handed Mace", "Two-Handed Mace",
                "One-Handed Sword", "Two-Handed Sword", "Polearm"],
    "Hunter": ["One-Handed Axe", "Two-Handed Axe", "One-Handed Sword", "Two-Handed Sword",
               "Polearm", "Staff", "Dagger", "Fist Weapon", "Bow", "Gun", "Crossbow", "Thrown"],
    "Rogue": ["One-Handed Mace", "One-Handed Sword", "Dagger", "Fist Weapon", "Bow", "Gun",
              "Crossbow", "Thrown"],
    "Priest": ["One-Handed Mace", "Staff", "Dagger", "Wand"],
    "Shaman": ["One-Handed Axe", "Two-Handed Axe", "One-Handed Mace", "Two-Handed Mace",
               "Staff", "Dagger", "Fist Weapon"],
    "Mage": ["One-Handed Sword", "Staff", "Dagger", "Wand"],
    "Warlock": ["One-Handed Sword", "Staff", "Dagger", "Wand"],
    "Druid": ["One-Handed Mace", "Two-Handed Mace", "Polearm", "Staff", "Dagger", "Fist Weapon"],
}
# Highest armor type, and the level it becomes available (Hunter/Shaman mail at 40,
# Warrior/Paladin plate at 40). Shields: Warrior, Paladin, Shaman.
ARMOR = {"Warrior": [("Mail", 1), ("Plate", 40)], "Paladin": [("Mail", 1), ("Plate", 40)],
         "Hunter": [("Leather", 1), ("Mail", 40)], "Shaman": [("Leather", 1), ("Mail", 40)],
         "Rogue": [("Leather", 1)], "Druid": [("Leather", 1)],
         "Priest": [("Cloth", 1)], "Mage": [("Cloth", 1)], "Warlock": [("Cloth", 1)]}
ARMOR_ORDER = ["Cloth", "Leather", "Mail", "Plate"]

JUNK_RE = re.compile(
    r"\b(test|deprecated|deprecate|unused|placeholder|qa|ph|old|nyi|dnd|monster)\b|^\[|^zz|"
    r"^Monster -|copy$", re.I)


def rpp_column(inv):
    if inv in (1, 5, 7, 17, 20):
        return 0
    if inv in (3, 6, 8, 10, 12):
        return 1
    if inv in (2, 9, 11, 14, 16, 23):
        return 2
    if inv in (13, 21, 22):
        return 3
    if inv in (15, 25, 26, 28):  # verified: bows (15) use column 4
        return 4
    return None


def damage_table(subclass, inv, flags1):
    caster = bool(flags1 & 0x200)
    if subclass == 19:
        return "Wand"
    if subclass == 16 or inv == 25:
        return "Thrown"
    if subclass in (2, 3, 18):
        return "Ranged"
    if inv == 17 or subclass in (1, 5, 6, 8, 10, 17, 20):
        return "TwoHandCaster" if caster else "TwoHand"
    return "OneHandCaster" if caster else "OneHand"


def main():
    print("Loading tables...")
    sparse = load("ItemSparse")
    item = load("Item")
    rpp = load("RandPropPoints")
    dmg = {t: {r["ItemLevel"]: r for r in load("ItemDamage" + t, key=None)}
           for t in ("OneHand", "OneHandCaster", "TwoHand", "TwoHandCaster",
                     "Ranged", "Thrown", "Wand")}
    armor_total = {r["ItemLevel"]: r for r in load("ItemArmorTotal", key=None)}
    armor_loc = load("ArmorLocation")
    armor_q = load("ItemArmorQuality")
    armor_shield = {r["ItemLevel"]: r for r in load("ItemArmorShield", key=None)}
    item_sets = load("ItemSet")
    factions = load("Faction")
    subclass_names = {(r["ClassID"], r["SubClassID"]): r["DisplayName_lang"]
                      for r in load("ItemSubClass", key=None)}
    class_names = {r["ClassID"]: r["ClassName_lang"] for r in load("ItemClass", key=None)}

    print("Loading spells...")
    spell_desc = load("Spell")
    spell_names = load("SpellName")
    spell_eff = {}
    for r in load("SpellEffect", key=None):
        if r["DifficultyID"] in ("0", ""):
            spell_eff.setdefault(r["SpellID"], {})[int(r["EffectIndex"])] = r
    spell_misc = {}
    for r in load("SpellMisc", key=None):
        if r["DifficultyID"] in ("0", ""):
            spell_misc[r["SpellID"]] = r
    durations = load("SpellDuration")
    proc_chance = {}
    for r in load("SpellAuraOptions", key=None):
        if r["DifficultyID"] in ("0", "") and r["ProcChance"] not in ("0", "101", ""):
            proc_chance[r["SpellID"]] = r["ProcChance"]
    radius = {r["ID"]: r["Radius"] for r in load("SpellRadius", key=None)}
    item_effects = load("ItemEffect")
    effects_by_item = {}
    for r in load("ItemXItemEffect", key=None):
        e = item_effects.get(r["ItemEffectID"])
        if e:
            effects_by_item.setdefault(r["ItemID"], []).append(e)
    set_of_item = {}
    for s in item_sets.values():
        for k in range(17):
            iid = s.get(f"ItemID_{k}", "0")
            if iid and iid != "0":
                set_of_item[iid] = s["Name_lang"]

    def spell_duration(sid):
        m = spell_misc.get(sid)
        d = durations.get(m["DurationIndex"]) if m else None
        if not d or int(d["Duration"]) <= 0:
            return None
        sec = int(d["Duration"]) / 1000
        if sec >= 3600:
            return f"{sec/3600:g} hrs"
        if sec >= 60:
            return f"{sec/60:g} min"
        return f"{sec:g} sec"

    def effect_num(sid, idx, kind="s"):
        e = spell_eff.get(sid, {}).get(idx - 1)
        if not e:
            return None
        v = abs(float(e["EffectBasePointsF"] or 0))
        if kind == "M":  # top of a damage range
            v = v * (1 + float(e["Variance"] or 0))
        if kind in ("o", "O"):  # total over the duration
            period = int(e["EffectAuraPeriod"] or 0)
            m = spell_misc.get(sid)
            d = durations.get(m["DurationIndex"]) if m else None
            if not period or not d or int(d["Duration"]) <= 0:
                return None
            v = v * int(d["Duration"]) / period
        return v

    def fmt(v, decimals=0):
        v = round(v, decimals) if decimals else round(v)
        return f"{v:g}" if decimals else str(int(v))

    token = re.compile(r"\$(?:\{([^}]*)\}(?:\.(\d))?|(\d+)?([sSmMoOdDxXtThHaAbBqQeEn])(\d)?)")
    inner = re.compile(r"\$(\d+)?([sSmMo])(\d)")

    def render(sid, text, depth=0):
        if not text:
            return ""

        def sub(m):
            if m.group(0).startswith("${"):
                expr = m.group(1)
                expr = re.sub(r"\$<[^>]*>", "1", expr)
                ok = True

                def val(mm):
                    nonlocal ok
                    v = effect_num(mm.group(1) or sid, int(mm.group(3)), mm.group(2))
                    if v is None:
                        ok = False
                        return "0"
                    return repr(v)
                expr = inner.sub(val, expr).replace("$*", "*").replace("$", "")
                if ok and re.fullmatch(r"[\d\.\s\+\-\*/\(\)]+", expr):
                    try:
                        return fmt(eval(expr, {"__builtins__": {}}), int(m.group(2) or 0))
                    except Exception:
                        pass
                return "X"
            other, kind, n = m.group(3), m.group(4), int(m.group(5) or 1)
            s = other or sid
            if kind in "sSmMoObB":
                v = effect_num(s, n, kind)
                return fmt(v) if v is not None else "X"
            kind = kind.lower()
            if kind == "d":
                return spell_duration(s) or "X sec"
            if kind == "t":
                e = spell_eff.get(s, {}).get(n - 1)
                per = int(e["EffectAuraPeriod"] or 0) if e else 0
                return f"{per/1000:g}" if per else "X"
            if kind == "h":
                return proc_chance.get(s, "X")
            if kind == "a":
                e = spell_eff.get(s, {}).get(n - 1)
                rad = radius.get(e["EffectRadiusIndex_0"]) if e else None
                return f"{float(rad):g}" if rad and float(rad) > 0 else "X"
            if kind == "x":
                e = spell_eff.get(s, {}).get(n - 1)
                return e["EffectChainTargets"] if e and e["EffectChainTargets"] != "0" else "X"
            return "X"

        out = token.sub(sub, text)
        out = re.sub(r"\$[lL]([^:;]+):([^;]+);", r"", out)  # plural forms
        out = re.sub(r"\$\?\w+\[([^\]]*)\]\[([^\]]*)\]", r"", out)  # conditional text: use the default
        return re.sub(r"\s+", " ", out).strip()

    con_path = DB_PATH + ".tmp"
    if os.path.exists(con_path):
        os.remove(con_path)
    con = sqlite3.connect(con_path)
    stat_cols = ", ".join(f"{c} INTEGER" for c in STAT_COLUMNS)
    con.executescript(f"""
    CREATE TABLE items (
        id INTEGER PRIMARY KEY, name TEXT, hidden INTEGER, junk INTEGER,
        quality INTEGER, quality_name TEXT, item_level INTEGER, required_level INTEGER,
        item_class TEXT, subclass TEXT, slot TEXT, inventory_type INTEGER,
        classes TEXT, class_mask INTEGER, bonding TEXT, is_unique INTEGER,
        speed REAL, min_damage INTEGER, max_damage INTEGER, dps REAL, dps_approx INTEGER,
        armor INTEGER, {stat_cols}, other_stats TEXT,
        effects TEXT, item_set TEXT, required_reputation TEXT,
        sell_price_copper INTEGER, buy_price_copper INTEGER, rep_rank TEXT,
        description TEXT, wowhead TEXT, estimated INTEGER);
    CREATE TABLE proficiency (class TEXT, subclass TEXT);
    CREATE TABLE armor_proficiency (class TEXT, armor TEXT, from_level INTEGER);
    CREATE TABLE meta (key TEXT, value TEXT);
    """)
    for cls, subs in PROFICIENCY.items():
        con.executemany("INSERT INTO proficiency VALUES (?,?)", [(cls, s) for s in subs])
    for cls, tiers in ARMOR.items():
        top = ARMOR_ORDER.index(tiers[-1][0])
        for i, a in enumerate(ARMOR_ORDER[: top + 1]):
            lvl = next((l for t, l in tiers if t == a), 1)
            con.execute("INSERT INTO armor_proficiency VALUES (?,?,?)", (cls, a, lvl))
        for a in ("Miscellaneous", "Cosmetic"):
            con.execute("INSERT INTO armor_proficiency VALUES (?,?,1)", (cls, a))
        if cls in ("Warrior", "Paladin", "Shaman"):
            con.execute("INSERT INTO armor_proficiency VALUES (?,?,1)", (cls, "Shield"))
    con.execute("INSERT INTO armor_proficiency VALUES ('Paladin','Libram',1)")
    con.execute("INSERT INTO armor_proficiency VALUES ('Druid','Idol',1)")
    con.execute("INSERT INTO armor_proficiency VALUES ('Shaman','Totem',1)")

    # Classic item data (vmangos) for items the Forever client still hides
    classic = {}
    vm_path = os.path.join(DATA, "vmangos", "mangos.sqlite")
    if os.path.exists(vm_path):
        vm = sqlite3.connect(f"file:{vm_path}?mode=ro", uri=True)
        vm.row_factory = sqlite3.Row
        for row in vm.execute("SELECT * FROM item_template WHERE patch <= 10 ORDER BY patch"):
            classic[row["entry"]] = row
        vm.close()

    rows = []
    for iid, it in item.items():
        sp = sparse.get(iid)
        cid, scid, inv = int(it["ClassID"]), int(it["SubclassID"]), int(it["InventoryType"])
        if cid == 2:
            subclass = WEAPON_SUBCLASS.get(scid, subclass_names.get((it["ClassID"], it["SubclassID"])))
        else:
            subclass = subclass_names.get((it["ClassID"], it["SubclassID"]), "")
        base = dict(id=int(iid), item_class=class_names.get(it["ClassID"], it["ClassID"]),
                    subclass=subclass, slot=SLOTS.get(inv, str(inv)), inventory_type=inv,
                    wowhead=f"https://www.wowhead.com/forever/item={iid}")
        cl = None
        if not sp:
            cl = classic.get(int(iid))
            if not cl:
                base.update(hidden=1, junk=0, name=None)
                rows.append(base)
                continue
            # Hidden in the Forever client but known from Classic: use Classic name, levels and
            # stats; weapon damage and armor still come from the Forever formulas below.
            sp = {"Display_lang": cl["name"], "OverallQualityID": cl["quality"], "ItemLevel": cl["item_level"],
                  "RequiredLevel": cl["required_level"], "AllowableClass": cl["allowable_class"],
                  "Bonding": cl["bonding"], "MaxCount": str(cl["max_count"]), "SellPrice": cl["sell_price"],
                  "Description_lang": cl["description"] or "",
                  "MinFactionID": str(cl["required_reputation_faction"] or 0),
                  "MinReputation": cl["required_reputation_rank"], "ItemDelay": cl["delay"],
                  "BuyPrice": cl["buy_price"],
                  "DmgVariance": 0.4 if (inv == 17 or scid in (1, 5, 6, 8, 10, 17, 18, 20)) else 0.6,
                  "Flags_1": 0, "QualityModifier": 0}
            for k in range(10):
                sp[f"StatModifier_bonusStat_{k}"], sp[f"StatPercentEditor_{k}"] = -1, 0
        name = sp["Display_lang"]
        q = int(sp["OverallQualityID"])
        ilvl = int(sp["ItemLevel"])
        mask = int(sp["AllowableClass"])
        if mask in (-1, 0) or all(mask & (1 << (c - 1)) for c in CLASSES):
            classes = ""
        else:
            classes = ", ".join(n for c, n in CLASSES.items() if mask & (1 << (c - 1)))
        r = dict(base, name=name, hidden=0, junk=1 if JUNK_RE.search(name) else 0,
                 quality=q, quality_name=QUALITY.get(q, str(q)), item_level=ilvl,
                 required_level=int(sp["RequiredLevel"]), classes=classes, class_mask=mask,
                 bonding=BONDING.get(int(sp["Bonding"]), ""),
                 is_unique=1 if sp["MaxCount"] == "1" else 0,
                 sell_price_copper=int(sp["SellPrice"]), buy_price_copper=int(sp["BuyPrice"] or 0),
                 description=sp["Description_lang"],
                 item_set=set_of_item.get(iid), estimated=1 if cl else 0)
        if cl:
            for k in range(1, 11):
                nm = CLASSIC_STATS.get(cl[f"stat_type{k}"])
                if nm and cl[f"stat_value{k}"]:
                    r[nm] = (r.get(nm) or 0) + cl[f"stat_value{k}"]
            for res in ("fire_res", "frost_res", "nature_res", "shadow_res", "arcane_res"):
                if cl[res]:
                    r[res] = cl[res]
        if sp["MinFactionID"] not in ("0", ""):
            fac = factions.get(sp["MinFactionID"])
            fname = fac["Name_lang"] if fac else f"faction {sp['MinFactionID']}"
            rank = REP_RANKS.get(int(sp["MinReputation"] or 0), sp["MinReputation"])
            r["required_reputation"] = f"{fname} - {rank}"
        elif int(sp["MinReputation"] or 0) > 0:
            # PvP/reputation vendor items store only the rank; the faction is the vendor's own
            r["rep_rank"] = REP_RANKS.get(int(sp["MinReputation"]), sp["MinReputation"])

        # Stats: allocation * RandPropPoints budget / 10000
        col = rpp_column(inv)
        budget_row = rpp.get(str(ilvl))
        other = []
        if col is not None and budget_row and q >= 2:
            key = {2: "Good", 3: "Superior"}.get(q, "Epic")
            P = float(budget_row[f"{key}_{col}"])
            for k in range(10):
                stat = int(sp[f"StatModifier_bonusStat_{k}"])
                alloc = int(sp[f"StatPercentEditor_{k}"])
                if stat < 0 or alloc == 0:
                    continue
                val = int(math.floor(alloc * P / 10000 + 0.5))
                nm = STATS.get(stat, f"stat_{stat}")
                if nm in STAT_COLUMNS:
                    r[nm] = (r.get(nm) or 0) + val
                else:
                    other.append(f"{nm} {val:+d}")
        r["other_stats"] = ", ".join(other) or None

        # Weapon damage
        delay = int(sp["ItemDelay"])
        if cid == 2 and delay > 0:
            t = damage_table(scid, inv, int(sp["Flags_1"]))
            drow = dmg[t].get(str(ilvl))
            if drow:
                dps_base = float(drow[f"Quality_{min(q, 6)}"])
                var = float(sp["DmgVariance"] or 0)
                speed = delay / 1000
                avg = dps_base * speed
                mn = int(math.floor(avg * (1 - var / 2)))
                mx = int(math.floor(avg * (1 + var / 2) + 0.5))
                r.update(speed=speed, min_damage=mn, max_damage=mx,
                         dps=round((mn + mx) / 2 / speed, 2),
                         dps_approx=1 if float(sp["QualityModifier"] or 0) != 0 else 0)

        # Armor
        if cid == 4 and q >= 0:
            if scid == 6:
                ar = armor_shield.get(str(ilvl))
                if ar:
                    r["armor"] = int(float(ar[f"Quality_{min(q, 6)}"]))
            elif scid in (1, 2, 3, 4) and inv not in (0, 2, 11, 12, 23):
                tot = armor_total.get(str(ilvl))
                loc = armor_loc.get(str(inv))
                aq = armor_q.get(str(ilvl))
                if tot and loc and aq:
                    mat = ["Cloth", "Leather", "Mail", "Plate"][scid - 1]
                    locmod = {"Cloth": "Clothmodifier", "Leather": "Leathermodifier",
                              "Mail": "Chainmodifier", "Plate": "Platemodifier"}[mat]
                    r["armor"] = int(math.floor(float(tot[mat]) * float(loc[locmod])
                                                * float(aq[f"Qualitymod_{min(q, 6)}"]) + 0.5))

        # Equip / use / on-hit effects
        effs = []
        effect_list = sorted(effects_by_item.get(iid, []), key=lambda e: int(e["LegacySlotIndex"]))
        if cl:
            effect_list = [{"SpellID": str(cl[f"spellid_{k}"]), "TriggerType": cl[f"spelltrigger_{k}"]}
                           for k in range(1, 6) if cl[f"spellid_{k}"]]
        for e in effect_list:
            sid = e["SpellID"]
            sd = spell_desc.get(sid)
            text = render(sid, sd["Description_lang"]) if sd else ""
            if not text:
                sn = spell_names.get(sid)
                text = sn["Name_lang"] if sn else f"spell {sid}"
            effs.append(f"{TRIGGER.get(int(e['TriggerType']), 'Effect')}: {text}")
        r["effects"] = " | ".join(effs) or None
        rows.append(r)

    cols = [c[1] for c in con.execute("PRAGMA table_info(items)")]
    con.executemany(f"INSERT INTO items ({','.join(cols)}) VALUES ({','.join('?'*len(cols))})",
                    [tuple(r.get(c) for c in cols) for r in rows])
    build = open(os.path.join(DATA, "BUILD.txt")).read().strip()
    con.executemany("INSERT INTO meta VALUES (?,?)", [("build", build), ("source", "wago.tools DB2 export, product wowf")])
    sys.path.insert(0, HERE)
    import questie_sources  # quest rewards, vendors, crafting
    import vmangos_loot     # creature and chest loot with drop chances
    questie_sources.add_sources(con)
    vmangos_loot.add_loot(con)
    questie_sources.summarize(con)
    con.executescript("""
    CREATE INDEX ix_items_name ON items(name);
    CREATE INDEX ix_items_slot ON items(slot, subclass, required_level);
    CREATE VIEW visible_items AS SELECT * FROM items WHERE hidden = 0 AND junk = 0;
    """)
    con.commit()
    con.close()
    os.replace(con_path, DB_PATH)
    vis = sum(1 for r in rows if not r.get("hidden") and not r.get("junk"))
    hid = sum(1 for r in rows if r.get("hidden"))
    est = sum(1 for r in rows if r.get("estimated"))
    print(f"{est} hidden items filled in from Classic data (marked estimated)")
    print(f"Built {DB_PATH}: {len(rows)} items ({vis} visible, {hid} hidden by Blizzard, "
          f"{len(rows)-vis-hid} test/junk) from build {build}")


if __name__ == "__main__":
    sys.exit(main())
