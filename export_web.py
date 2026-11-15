"""Export wow_forever.db to web/items.json for the browser page (web/index.html)."""
import json
import os
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "web", "items.json")
STATS = ["agility", "strength", "stamina", "intellect", "spirit", "attack_power",
         "ranged_attack_power", "hit", "crit", "haste", "spell_power", "healing",
         "spell_damage", "mp5", "defense", "dodge", "parry", "block", "block_value",
         "bonus_armor", "fire_res", "frost_res", "nature_res", "shadow_res", "arcane_res"]
FIELDS = ["id", "name", "q", "ilvl", "req", "ic", "sub", "slot", "mask", "bind", "uniq",
          "speed", "min", "max", "dps", "approx", "armor", "st", "other", "fx", "set", "rep",
          "desc", "sell", "src", "srcTypes", "lvl", "est"]
QUEST_FIELDS = ["id", "name", "qlvl", "req", "faction", "classes", "zone", "from", "to", "rewards"]


def main():
    con = sqlite3.connect(os.path.join(HERE, "wow_forever.db"))
    con.row_factory = sqlite3.Row
    build = con.execute("SELECT value FROM meta WHERE key='build'").fetchone()[0]
    hidden = dict(con.execute("SELECT slot, COUNT(*) FROM items WHERE hidden=1 GROUP BY slot").fetchall())
    rows = []
    for r in con.execute("SELECT * FROM visible_items WHERE quality IS NOT NULL ORDER BY id"):
        st = [[STATS.index(s), r[s]] for s in STATS if r[s]]
        rows.append([r["id"], r["name"], r["quality"], r["item_level"], r["required_level"],
                     r["item_class"], r["subclass"], r["slot"], r["class_mask"], r["bonding"] or "",
                     r["is_unique"], r["speed"], r["min_damage"], r["max_damage"], r["dps"],
                     r["dps_approx"], r["armor"], st, r["other_stats"], r["effects"],
                     r["item_set"], r["required_reputation"], r["description"] or None,
                     r["sell_price_copper"], r["source_summary"], r["source_types"], r["level_hint"],
                     r["estimated"] or 0])
    item_ids = {r[0] for r in rows}
    rewards = {}
    for qid, iid in con.execute("SELECT source_id, item_id FROM item_sources WHERE kind='quest'"):
        if iid in item_ids:
            rewards.setdefault(qid, []).append(iid)
    quests = [[q["id"], q["name"], q["quest_level"], q["required_level"], q["faction"], q["classes"],
               q["zone"], q["start_npc"], q["end_npc"], rewards[q["id"]]]
              for q in con.execute("SELECT * FROM quests ORDER BY quest_level, name") if q["id"] in rewards]
    prof = {}
    for c, s in con.execute("SELECT class, subclass FROM proficiency"):
        prof.setdefault(c, []).append(s)
    armor = {}
    for c, a, lvl in con.execute("SELECT class, armor, from_level FROM armor_proficiency"):
        armor.setdefault(c, {})[a] = lvl
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"build": build, "fields": FIELDS, "stats": STATS, "hidden": hidden,
                   "proficiency": prof, "armor": armor, "items": rows,
                   "questFields": QUEST_FIELDS, "quests": quests},
                  f, ensure_ascii=False, separators=(",", ":"))
    print(f"Wrote {OUT}: {len(rows)} items, {len(quests)} quests with rewards, "
          f"{os.path.getsize(OUT)/1e6:.1f} MB")


if __name__ == "__main__":
    main()
