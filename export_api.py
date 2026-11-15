"""Build the static website + data API into ./site (deployed to GitHub Pages).

site/
  index.html             the Armory page
  items.json             compact data the page loads
  wow_forever.db         full SQLite database
  api/meta.json          build, counts, sources, file list
  api/items.json|.csv    every known item, one object/row per item
  api/quests.json|.csv   every quest
  api/item_sources.json|.csv   how to get each item (quest, drop + chance, vendor, chest, crafted)
  api/proficiency.json   class weapon/armor rules used by the filters

Run after build_db.py and export_web.py.
"""
import csv
import datetime
import json
import os
import shutil
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(HERE, "site")
API = os.path.join(SITE, "api")
REPO = "https://github.com/gBlaku/wow-forever-kb"

# Wraps web/index.html (written for claude.ai artifacts, which add the document shell) as a full page
SHELL_HEAD = """<!doctype html>
<html lang="en">
<head>
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<style>:root{color-scheme:light}body{margin:0;font:14px system-ui,sans-serif}img{max-width:100%}[hidden]{display:none!important}</style>
"""


def dump(name, rows, cols):
    with open(os.path.join(API, name + ".json"), "w", encoding="utf-8") as f:
        # empty fields are left out to keep the files small
        json.dump([{k: v for k, v in zip(cols, r) if v is not None and v != ""} for r in rows],
                  f, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(API, name + ".csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        w.writerows(rows)


def main():
    if os.path.exists(SITE):
        shutil.rmtree(SITE)
    os.makedirs(API)
    con = sqlite3.connect(os.path.join(HERE, "wow_forever.db"))

    def table(sql):
        cur = con.execute(sql)
        return cur.fetchall(), [d[0] for d in cur.description]

    items, icols = table("SELECT * FROM items WHERE hidden = 0 AND junk = 0 ORDER BY id")
    quests, qcols = table("SELECT * FROM quests ORDER BY id")
    # Wowhead uses the game's own IDs, so every source links straight to its page
    sources, scols = table("""SELECT s.*, CASE
            WHEN s.source_id IS NULL OR s.source_id = 0 THEN NULL
            WHEN s.kind = 'quest' THEN 'https://www.wowhead.com/forever/quest=' || s.source_id
            WHEN s.kind IN ('drop', 'vendor') THEN 'https://www.wowhead.com/forever/npc=' || s.source_id
            WHEN s.kind = 'object' THEN 'https://www.wowhead.com/forever/object=' || s.source_id
            WHEN s.kind = 'crafted' THEN 'https://www.wowhead.com/forever/spell=' || s.source_id
            WHEN s.kind = 'container' THEN 'https://www.wowhead.com/forever/item=' || s.source_id
        END AS wowhead
        FROM item_sources s JOIN items i ON i.id = s.item_id
        WHERE i.hidden = 0 AND i.junk = 0 ORDER BY s.item_id, s.kind, s.chance DESC""")
    dump("items", items, icols)
    dump("quests", quests, qcols)
    dump("item_sources", sources, scols)

    prof = {}
    for c, s in con.execute("SELECT class, subclass FROM proficiency"):
        prof.setdefault(c, {"weapons": [], "armor": {}})["weapons"].append(s)
    for c, a, lvl in con.execute("SELECT class, armor, from_level FROM armor_proficiency"):
        prof[c]["armor"][a] = lvl
    with open(os.path.join(API, "proficiency.json"), "w", encoding="utf-8") as f:
        json.dump(prof, f, indent=1)

    build = con.execute("SELECT value FROM meta WHERE key='build'").fetchone()[0]
    hidden = con.execute("SELECT COUNT(*) FROM items WHERE hidden = 1").fetchone()[0]
    estimated = con.execute("SELECT COUNT(*) FROM items WHERE estimated = 1 AND junk = 0").fetchone()[0]
    con.close()

    meta = {
        "game": "World of Warcraft: Forever",
        "client_build": build,
        "generated_utc": datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "counts": {"items": len(items), "items_from_classic_data": estimated,
                   "items_still_hidden": hidden, "quests": len(quests), "item_sources": len(sources)},
        "files": {n: f"api/{n}.json" for n in ("items", "quests", "item_sources", "proficiency")}
        | {"items_csv": "api/items.csv", "quests_csv": "api/quests.csv",
           "item_sources_csv": "api/item_sources.csv", "sqlite": "wow_forever.db"},
        "sources": {
            "items": "WoW Forever client tables (DB2) via wago.tools",
            "quests_vendors": "Questie addon WoW Forever database (github.com/Questie/QuestieDB, GPLv3)",
            "loot_and_classic_items": "vmangos Classic world database (github.com/vmangos/core, GPLv2)",
        },
        "docs": REPO + "#readme",
    }
    with open(os.path.join(API, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=1)

    with open(os.path.join(HERE, "web", "index.html"), encoding="utf-8") as f:
        page = f.read()
    with open(os.path.join(SITE, "index.html"), "w", encoding="utf-8") as f:
        f.write(SHELL_HEAD + page + "\n</html>\n")
    shutil.copy(os.path.join(HERE, "web", "items.json"), os.path.join(SITE, "items.json"))
    shutil.copy(os.path.join(HERE, "wow_forever.db"), os.path.join(SITE, "wow_forever.db"))
    open(os.path.join(SITE, ".nojekyll"), "w").close()
    total = sum(os.path.getsize(os.path.join(d, n)) for d, _, fs in os.walk(SITE) for n in fs)
    print(f"Site written to {SITE}: {len(items)} items, {len(quests)} quests, "
          f"{len(sources)} sources, {total/1e6:.0f} MB total")


if __name__ == "__main__":
    main()
