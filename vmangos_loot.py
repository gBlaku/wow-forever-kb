"""Add creature and chest loot (with drop chances) to wow_forever.db.

Source: the vmangos project's Classic world database (github.com/vmangos/core,
release "db_latest", SQLite snapshot, GPLv2). This is Classic 1.12 loot; WoW Forever
reworked some gear, so new Forever items and changed drops are not in it.

Replaces Questie's partial "drop" rows; quest, vendor and crafting rows stay.
"""
import os
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
VM_DB = os.path.join(HERE, "data", "vmangos", "mangos.sqlite")
PATCH = 10            # vmangos patch index for 1.12 (latest)
WORLD_DROP_MIN = 12   # an item dropped by more creatures than this is summarised as a world drop
RANK = {1: "elite", 2: "rare elite", 3: "boss", 4: "rare"}


def add_loot(con):
    if not os.path.exists(VM_DB):
        print("vmangos database not found; skipping loot tables (run download_data.py)")
        return
    vm = sqlite3.connect(f"file:{VM_DB}?mode=ro", uri=True)

    def rows(table):
        out = {}
        for entry, item, chance, group, ref, maxc in vm.execute(
                f"SELECT entry, item, ChanceOrQuestChance, groupid, mincountOrRef, maxcount FROM {table} "
                f"WHERE patch_min <= ? AND patch_max >= ?", (PATCH, PATCH)):
            out.setdefault(entry, []).append((item, chance, group, ref, maxc))
        return out

    tables = {"creature": rows("creature_loot_template"), "gameobject": rows("gameobject_loot_template"),
              "reference": rows("reference_loot_template")}
    memo = {}

    def combine(acc, item, p):
        acc[item] = 1 - (1 - acc.get(item, 0)) * (1 - p)

    def resolve(table, entry, depth=0):
        """Probability (0-1) that each item drops from one loot of this table entry."""
        key = (table, entry)
        if key in memo:
            return memo[key]
        memo[key] = {}
        lst = tables[table].get(entry, [])
        # within a group exactly one entry drops: explicit chances first, the rest share equally
        groups = {}
        for r in lst:
            if r[2] > 0:
                groups.setdefault(r[2], []).append(r)
        share = {}
        for g, rs in groups.items():
            explicit = sum(abs(r[1]) for r in rs if r[1] != 0)
            zero = [r for r in rs if r[1] == 0]
            share[g] = max(0.0, 100 - explicit) / len(zero) if zero else 0
        acc = {}
        for item, chance, group, ref, maxc in lst:
            if chance < 0:
                continue  # quest-only drop
            c = (share[group] if (group > 0 and chance == 0) else chance) / 100
            if c <= 0:
                continue
            if ref < 0 and depth < 6:
                sub = resolve("reference", -ref, depth + 1)
                times = max(1, maxc or 1)
                for it, p in sub.items():
                    combine(acc, it, 1 - (1 - c * p) ** times)
            elif ref >= 0:
                combine(acc, item, c)
        memo[key] = acc
        return acc

    # Creatures (latest patch row of each template)
    maps = {}
    for entry, name, mtype in vm.execute("SELECT entry, map_name, map_type FROM map_template ORDER BY patch"):
        maps[entry] = (name, mtype)
    spawn_map = {}
    for cid, m in vm.execute("SELECT id, map FROM creature WHERE patch_min <= ? AND patch_max >= ?", (PATCH, PATCH)):
        if cid not in spawn_map or (maps.get(m, ("", 0))[1] > 0):
            spawn_map[cid] = m
    questie_zone = dict(con.execute("SELECT id, zone FROM npcs"))
    creatures = {}
    for entry, name, lo, hi, rank, loot_id in vm.execute(
            "SELECT entry, name, level_min, level_max, rank, loot_id FROM creature_template WHERE patch <= ? "
            "ORDER BY patch", (PATCH,)):
        creatures[entry] = (name, lo, hi, rank, loot_id)

    def place(cid):
        m = spawn_map.get(cid)
        inst = maps.get(m)
        if inst and inst[1] > 0:
            return inst[0] + (" (raid)" if inst[1] == 2 else "")
        return questie_zone.get(cid) or (inst[0] if inst else None)

    by_item = {}
    for cid, (name, lo, hi, rank, loot_id) in creatures.items():
        if not loot_id:
            continue
        for item, p in resolve("creature", loot_id).items():
            if p >= 0.000001:
                by_item.setdefault(item, []).append((cid, name, lo, hi, rank, p))

    known = {r[0] for r in con.execute("SELECT id FROM items")}
    out = []
    for item, lst in by_item.items():
        if item not in known:
            continue
        lst.sort(key=lambda r: -r[5])
        named = [r for r in lst if r[5] >= 0.01] if len(lst) > WORLD_DROP_MIN else lst
        for cid, name, lo, hi, rank, p in named[:WORLD_DROP_MIN]:
            out.append((item, "drop", cid, name, lo, hi, place(cid), RANK.get(rank), round(p * 100, 3)))
        if len(lst) > WORLD_DROP_MIN:
            rest = [r for r in lst if r not in named[:WORLD_DROP_MIN]] or lst
            lv = [r[2] for r in rest if r[2]] + [r[3] for r in rest if r[3]]
            out.append((item, "drop", 0, "World drop", min(lv) if lv else None, max(lv) if lv else None, None,
                        f"{len(rest)} {'other ' if len(rest) < len(lst) else ''}creatures",
                        round(max(r[5] for r in rest) * 100, 4)))

    # Chests and other loot objects (gameobject type 3 = chest, data1 = loot id)
    go_map = {}
    for gid, m in vm.execute("SELECT id, map FROM gameobject WHERE patch_min <= ? AND patch_max >= ?", (PATCH, PATCH)):
        if gid not in go_map or (maps.get(m, ("", 0))[1] > 0):
            go_map[gid] = m
    chests = {}
    for entry, name, loot_id in vm.execute(
            "SELECT entry, name, data1 FROM gameobject_template WHERE type = 3 AND patch <= ? ORDER BY patch", (PATCH,)):
        chests[entry] = (name, loot_id)
    go_by_item = {}
    for gid, (name, loot_id) in chests.items():
        if not loot_id or gid not in go_map:
            continue
        for item, p in resolve("gameobject", loot_id).items():
            if p >= 0.0001 and item in known:
                go_by_item.setdefault(item, []).append((gid, name, p))
    for item, lst in go_by_item.items():
        lst.sort(key=lambda r: -r[2])
        for gid, name, p in lst[:6]:
            inst = maps.get(go_map[gid])
            zone = inst[0] + (" (raid)" if inst[1] == 2 else "") if inst and inst[1] > 0 else None
            out.append((item, "object", gid, name, None, None, zone, None, round(p * 100, 3)))

    con.execute("DELETE FROM item_sources WHERE kind = 'drop'")
    con.execute("DELETE FROM item_sources WHERE kind = 'object' AND source_id IN (%s)" %
                ",".join(str(g) for g in chests) if chests else "SELECT 1")
    con.executemany("INSERT INTO item_sources (item_id, kind, source_id, name, min_level, max_level, zone, extra, chance) "
                    "VALUES (?,?,?,?,?,?,?,?,?)", out)
    print(f"vmangos loot: {sum(1 for r in out if r[1] == 'drop')} drop links for {len(by_item)} items, "
          f"{sum(1 for r in out if r[1] == 'object')} chest links")
