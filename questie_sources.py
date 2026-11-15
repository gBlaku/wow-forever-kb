"""Add item sources (quest rewards, drops, vendors, objects, crafting) to wow_forever.db.

Crafting comes from the client tables (SkillLineAbility + SpellEffect); everything else
comes from Questie, as described below.

Source: the Questie addon's WoW Forever database (github.com/Questie/QuestieDB,
data/Forever/*.lua, GPLv3). It is Classic Era data with Forever map coordinates,
so brand-new Forever items, NPCs and quests are not in it yet.

Called by build_db.py; can also run on its own:  python questie_sources.py
"""
import csv
import os
import re
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
QDIR = os.path.join(DATA, "questie")
CLASS_BITS = {1: "Warrior", 2: "Paladin", 3: "Hunter", 4: "Rogue", 5: "Priest",
              7: "Shaman", 8: "Mage", 9: "Warlock", 11: "Druid"}
ALLIANCE, HORDE = 1 | 4 | 8 | 64, 2 | 16 | 32 | 128

# ---------------------------------------------------------------- Lua literal parser
_TOKEN = re.compile(r"""
    (?P<ws>\s+|--[^\n]*)
  | (?P<str>'(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*")
  | (?P<num>-?(?:0x[0-9a-fA-F]+|\d+\.?\d*(?:[eE][-+]?\d+)?|\.\d+))
  | (?P<word>[A-Za-z_]\w*)
  | (?P<sym>[{}\[\]=,;])
""", re.X)
_ESC = {"n": "\n", "t": "\t", "\\": "\\", "'": "'", '"': '"'}


def _tokens(s):
    pos = 0
    for m in _TOKEN.finditer(s):
        if m.start() != pos:
            raise ValueError(f"Unexpected text at {pos}: {s[pos:pos+40]!r}")
        pos = m.end()
        kind = m.lastgroup
        if kind == "ws":
            continue
        v = m.group()
        if kind == "str":
            v = re.sub(r"\\(.)", lambda e: _ESC.get(e.group(1), e.group(1)), v[1:-1])
        elif kind == "num":
            v = int(v, 16) if v.lower().startswith(("0x", "-0x")) else (float(v) if any(c in v for c in ".eE") else int(v))
        yield kind, v
    if pos != len(s):
        raise ValueError(f"Unexpected text at {pos}")


def parse_lua_table(text):
    """Parse a Lua table literal into nested dicts keyed 1..n (or explicit keys)."""
    toks = list(_tokens(text))
    i = 0

    def value():
        nonlocal i
        kind, v = toks[i]
        i += 1
        if kind == "sym" and v == "{":
            return table()
        if kind == "word":
            return {"nil": None, "true": True, "false": False}.get(v, v)
        return v

    def table():
        nonlocal i
        t, n = {}, 0
        while True:
            kind, v = toks[i]
            if kind == "sym" and v == "}":
                i += 1
                return t
            if kind == "sym" and v in ",;":
                i += 1
                continue
            if kind == "sym" and v == "[":
                i += 1
                k = value()
                i += 2  # ']' '='
                t[k] = value()
            elif kind == "word" and toks[i + 1] == ("sym", "="):
                i += 2
                t[v] = value()
            else:
                n += 1
                val = value()
                if val is not None:
                    t[n] = val
    if toks[0] == ("word", "return"):
        i = 1
    return value()


def load_questie(name, var):
    with open(os.path.join(QDIR, name), encoding="utf-8") as f:
        src = f.read()
    m = re.search(var + r"\s*=\s*\[(=*)\[(.*?)\]\1\]", src, re.S)
    if not m:
        raise ValueError(f"{var} not found in {name}")
    return parse_lua_table(m.group(2))


def ids(t):
    """Questie list fields -> list of ints."""
    if not t:
        return []
    if isinstance(t, dict):
        return [v for _, v in sorted(t.items(), key=lambda kv: kv[0] if isinstance(kv[0], int) else 0) if isinstance(v, int)]
    return [t] if isinstance(t, int) else []


# ---------------------------------------------------------------- import
def add_sources(con):
    print("Loading Questie Forever data...")
    quests = load_questie("foreverQuestDB.lua", "QuestieDB.questData")
    qitems = load_questie("foreverItemDB.lua", "QuestieDB.itemData")
    npcs = load_questie("foreverNpcDB.lua", "QuestieDB.npcData")
    objects = load_questie("foreverObjectDB.lua", "QuestieDB.objectData")

    def read_csv(name):
        with open(os.path.join(DATA, name + ".csv"), encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))
    areas = {int(r["ID"]): r["AreaName_lang"] for r in read_csv("AreaTable")}
    faction_names = {r["ID"]: r["Name_lang"] for r in read_csv("Faction")}
    template_faction = {int(r["ID"]): faction_names.get(r["Faction"]) for r in read_csv("FactionTemplate")}
    sorts = {int(r["ID"]): r["SortName_lang"] for r in read_csv("QuestSort")}

    def zone_name(z):
        if not isinstance(z, int) or z == 0:
            return None
        return areas.get(z) if z > 0 else sorts.get(-z)

    def faction(mask):
        if not mask:
            return "Both"
        low = mask & 0xFF
        a, h = bool(low & ALLIANCE), bool(low & HORDE)
        return "Both" if (a and h) or not (a or h) else ("Alliance" if a else "Horde")

    def class_list(mask):
        if not mask:
            return None
        names = [n for b, n in CLASS_BITS.items() if mask & (1 << (b - 1))]
        return None if len(names) == len(CLASS_BITS) else ", ".join(names)

    con.executescript("""
    DROP TABLE IF EXISTS quests; DROP TABLE IF EXISTS item_sources; DROP TABLE IF EXISTS npcs;
    CREATE TABLE quests (id INTEGER PRIMARY KEY, name TEXT, quest_level INTEGER, required_level INTEGER,
        faction TEXT, classes TEXT, zone TEXT, repeatable INTEGER, start_npc TEXT, end_npc TEXT, wowhead TEXT,
        start_where TEXT, end_where TEXT);
    CREATE TABLE npcs (id INTEGER PRIMARY KEY, name TEXT, title TEXT, min_level INTEGER, max_level INTEGER,
        elite INTEGER, zone TEXT, friendly_to TEXT, faction TEXT);
    CREATE TABLE item_sources (item_id INTEGER, kind TEXT, source_id INTEGER, name TEXT,
        min_level INTEGER, max_level INTEGER, zone TEXT, extra TEXT, chance REAL);
    """)

    npc_rows = {}
    for nid, n in npcs.items():
        if not isinstance(n, dict) or not n.get(1):
            continue
        npc_rows[nid] = (nid, n.get(1), n.get(14), n.get(4), n.get(5), 1 if (n.get(6) or 0) in (1, 2, 3) else 0,
                         zone_name(n.get(9)), n.get(13), template_faction.get(n.get(12)))
    con.executemany("INSERT INTO npcs VALUES (?,?,?,?,?,?,?,?,?)", npc_rows.values())

    def first_npc(t):
        """(name, zone) of the first creature or object that starts/ends a quest."""
        if isinstance(t, dict):
            lst = ids(t.get(1))
            if lst and lst[0] in npc_rows:
                return npc_rows[lst[0]][1], npc_rows[lst[0]][6]
            lst = ids(t.get(2))
            if lst and isinstance(objects.get(lst[0]), dict):
                o = objects[lst[0]]
                return o.get(1), zone_name(o.get(5))
            lst = ids(t.get(3))
            if lst and isinstance(qitems.get(lst[0]), dict):
                return f"the item {qitems[lst[0]].get(1)}", None
        return None, None

    qrows = {}
    for qid, q in quests.items():
        if not isinstance(q, dict) or not q.get(1):
            continue
        start, start_where = first_npc(q.get(2))
        end, end_where = first_npc(q.get(3))
        qrows[qid] = (qid, q.get(1), q.get(5), q.get(4), faction(q.get(6)), class_list(q.get(7)),
                      zone_name(q.get(17)), 1 if (q.get(24) or 0) & 1 else 0,
                      start, end, f"https://www.wowhead.com/forever/quest={qid}", start_where, end_where)
    con.executemany("INSERT INTO quests VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", qrows.values())

    src = []
    for iid, it in qitems.items():
        if not isinstance(it, dict):
            continue
        for qid in ids(it.get(6)):
            q = qrows.get(qid)
            if q:
                extra = q[4] + (f"; {q[5]} only" if q[5] else "")
                src.append((iid, "quest", qid, q[1], q[3], q[2], q[6], extra))
        for nid in ids(it.get(2)):
            n = npc_rows.get(nid)
            if n:
                src.append((iid, "drop", nid, n[1], n[3], n[4], n[6], "elite" if n[5] else None))
        for nid in ids(it.get(14)):
            n = npc_rows.get(nid)
            if n:
                src.append((iid, "vendor", nid, n[1], None, None, n[6], n[2]))
        for oid in ids(it.get(3)):
            o = objects.get(oid)
            if isinstance(o, dict):
                src.append((iid, "object", oid, o.get(1), None, None, zone_name(o.get(5)), None))
        for cid in ids(it.get(4)):
            c = qitems.get(cid)
            if isinstance(c, dict):
                src.append((iid, "container", cid, c.get(1), None, None, None, None))
    # Crafted items come from the game client's own profession tables
    skill_names = {r["ID"]: r["DisplayName_lang"] for r in read_csv("SkillLine")}
    recipe = {}
    for r in read_csv("SkillLineAbility"):
        name = skill_names.get(r["SkillLine"])
        if name:
            recipe.setdefault(r["Spell"], (name, int(r["TrivialSkillLineRankLow"] or 0),
                                           "trainer" if r["AcquireMethod"] == "1" else "recipe"))
    spell_names = {r["ID"]: r["Name_lang"] for r in read_csv("SpellName")}
    for r in read_csv("SpellEffect"):
        if r["Effect"] == "24" and r["EffectItemType"] not in ("0", "") and r["SpellID"] in recipe:
            prof, skill, how = recipe[r["SpellID"]]
            src.append((int(r["EffectItemType"]), "crafted", int(r["SpellID"]), prof, skill or None, None, None,
                        f"{spell_names.get(r['SpellID'], '')}; learned from {how}"))

    con.executemany("INSERT INTO item_sources (item_id, kind, source_id, name, min_level, max_level, zone, extra) "
                    "VALUES (?,?,?,?,?,?,?,?)", src)
    con.execute("CREATE INDEX ix_src_item ON item_sources(item_id)")
    print(f"Questie: {len(qrows)} quests, {len(npc_rows)} NPCs, {len(src)} item-source links")


RANK = {1: "elite", 2: "rare elite", 3: "boss", 4: "rare"}


def summarize(con):
    """Fill items.source_types / source_summary / level_hint from item_sources."""
    cols = {r[1] for r in con.execute("PRAGMA table_info(items)")}
    for c, t in (("source_types", "TEXT"), ("source_summary", "TEXT"), ("level_hint", "INTEGER")):
        if c not in cols:
            con.execute(f"ALTER TABLE items ADD COLUMN {c} {t}")
    quest_giver = {qid: (who, where) for qid, who, where in
                   con.execute("SELECT id, start_npc, start_where FROM quests")}
    npc_faction = dict(con.execute("SELECT id, faction FROM npcs"))
    item_info = {r[0]: r[1:] for r in con.execute(
        "SELECT id, buy_price_copper, rep_rank, required_reputation FROM items WHERE hidden = 0")}
    by_item = {}
    for row in con.execute("SELECT item_id, kind, source_id, name, min_level, max_level, zone, extra, chance "
                           "FROM item_sources"):
        by_item.setdefault(row[0], []).append(row)

    def lvl(a, b):
        if not a:
            return ""
        return f"lvl {a}" + (f"-{b}" if b and b != a else "")

    updates, rep_updates = [], []
    for (iid, req, ilvl) in con.execute("SELECT id, required_level, item_level FROM items WHERE hidden = 0").fetchall():
        rows = by_item.get(iid, [])
        kinds = sorted({r[1] for r in rows})
        parts = []
        qs = sorted([r for r in rows if r[1] == "quest"], key=lambda r: r[5] or 0)
        if qs:
            def giver(qid):
                who, where = quest_giver.get(qid, (None, None))
                return f"; from {who}{' in ' + where if where else ''}" if who else ""
            parts.append("Quest: " + "; ".join(
                f"{r[3]} (lvl {r[5]}{', ' + r[6] if r[6] else ''}, {r[7]}{giver(r[2])})" for r in qs[:3])
                + (f" +{len(qs)-3} more" if len(qs) > 3 else ""))
        ds = sorted([r for r in rows if r[1] == "drop" and r[2]], key=lambda r: -(r[8] or 0))
        world = [r for r in rows if r[1] == "drop" and not r[2]]
        if ds:
            parts.append("Drop: " + "; ".join(
                f"{r[3]} ({', '.join(x for x in (lvl(r[4], r[5]) + (' ' + r[7] if r[7] else ''), r[6], f'{r[8]:.3g}%' if r[8] else '') if x)})"
                for r in ds[:4]) + (f" +{len(ds)-4} more" if len(ds) > 4 else ""))
        for r in world:
            parts.append(f"World drop: {r[7]}, {lvl(r[4], r[5])}" + (f", up to {r[8]:.2g}% each" if r[8] else ""))
        vs = [r for r in rows if r[1] == "vendor"]
        price, rep_rank, rep = item_info.get(iid, (None, None, None))
        if vs:
            parts.append("Vendor: " + "; ".join(f"{r[3]}{', ' + r[6] if r[6] else ''}" for r in vs[:3])
                         + (f" +{len(vs)-3} more" if len(vs) > 3 else "")
                         + (f" (costs {money(price)})" if price else ""))
            if rep_rank and not rep:
                # the item stores only the rank; the faction is the vendor's own
                fac = next((npc_faction.get(r[2]) for r in vs if npc_faction.get(r[2])), None)
                if fac:
                    rep_updates.append((f"{fac} - {rep_rank}", iid))
        os_ = sorted([r for r in rows if r[1] == "object"], key=lambda r: -(r[8] or 0))
        if os_:
            parts.append("Chest/object: " + "; ".join(
                f"{r[3]}{' (' + ', '.join(x for x in (r[6], f'{r[8]:.3g}%' if r[8] else '') if x) + ')' if r[6] or r[8] else ''}"
                for r in os_[:3]) + (f" +{len(os_)-3} more" if len(os_) > 3 else ""))
        cr = [r for r in rows if r[1] == "crafted"]
        if cr:
            parts.append("Crafted: " + "; ".join(
                f"{r[3]}{' ' + str(r[4]) if r[4] else ''} ({r[7].split('; ')[1]})" for r in cr[:2]))
        cs = [r for r in rows if r[1] == "container"]
        if cs:
            parts.append("Contained in: " + "; ".join(r[3] for r in cs[:3]))

        # Level the item is really for
        if req and req > 1:
            hint = req
        elif qs:
            hint = min(r[5] or r[4] or 0 for r in qs) or None
        elif ds and ds[0][4]:
            hint = ds[0][4]  # level of the creature most likely to drop it
        else:
            hint = None
        if not hint:
            hint = max(1, (ilvl or 0) - 5)
        updates.append((",".join(kinds) or None, " | ".join(parts) or None, hint, iid))
    con.executemany("UPDATE items SET source_types=?, source_summary=?, level_hint=? WHERE id=?", updates)
    con.executemany("UPDATE items SET required_reputation=? WHERE id=?", rep_updates)
    print(f"Summaries: {len(updates)} items, {len(rep_updates)} vendor reputation requirements filled in")


def money(copper):
    g, s, c = copper // 10000, copper // 100 % 100, copper % 100
    return " ".join(x for x in (f"{g}g" if g else "", f"{s}s" if s else "", f"{c}c" if c or not (g or s) else "") if x)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, HERE)
    import vmangos_loot
    c = sqlite3.connect(os.path.join(HERE, "wow_forever.db"))
    add_sources(c)
    vmangos_loot.add_loot(c)
    summarize(c)
    c.commit()
