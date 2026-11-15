"""Download the WoW Forever client data tables (CSV) from wago.tools.

Usage:
  py download_data.py            # latest WoW Forever (wowf) build
  py download_data.py 1.60.1.70938
"""
import json
import os
import re
import sys
import time
import urllib.request

TABLES = ["ItemSparse", "Item", "ItemClass", "ItemSubClass", "ChrClasses", "ChrRaces",
          "RandPropPoints", "ItemDamageOneHand", "ItemDamageOneHandCaster",
          "ItemDamageTwoHand", "ItemDamageTwoHandCaster", "ItemDamageRanged",
          "ItemDamageThrown", "ItemDamageWand", "ItemDamageAmmo", "ItemArmorQuality",
          "ItemArmorTotal", "ArmorLocation", "ItemArmorShield", "ItemEffect",
          "ItemXItemEffect", "SpellEffect", "Spell", "SpellName", "SpellMisc",
          "SpellDuration", "ItemSet", "ItemSetSpell", "ItemSearchName", "Faction",
          "AreaTable", "QuestSort", "SkillLineAbility", "SkillLine", "SpellAuraOptions", "SpellRadius", "FactionTemplate"]
# Quest, NPC, drop and vendor data from the Questie addon's WoW Forever database (GPLv3)
QUESTIE = "https://raw.githubusercontent.com/Questie/QuestieDB/master/data/Forever/"
QUESTIE_FILES = ["foreverQuestDB.lua", "foreverItemDB.lua", "foreverNpcDB.lua", "foreverObjectDB.lua"]
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
UA = {"User-Agent": "wow-forever-kb/1.0 (personal use)"}


def get(url):
    headers = dict(UA)
    # GitHub's API rate-limits anonymous calls per IP; shared CI machines hit it, so use the
    # job's token when there is one (GitHub Actions sets GITHUB_TOKEN via the workflow).
    if url.startswith("https://api.github.com/") and os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def latest_build():
    html = get("https://wago.tools/builds").decode("utf-8", "replace").replace("&quot;", '"')
    m = re.search(r'"product":"wowf","version":"([\d.]+)"', html)
    if not m:
        sys.exit("Could not find a wowf build on wago.tools/builds")
    return m.group(1)


def main():
    build = sys.argv[1] if len(sys.argv) > 1 else latest_build()
    print(f"WoW Forever build {build}")
    os.makedirs(DATA, exist_ok=True)
    for t in TABLES:
        body = get(f"https://wago.tools/db2/{t}/csv?build={build}")
        with open(os.path.join(DATA, t + ".csv"), "wb") as f:
            f.write(body)
        print(f"  {t}: {len(body):,} bytes")
        time.sleep(1)  # be polite
    qdir = os.path.join(DATA, "questie")
    os.makedirs(qdir, exist_ok=True)
    for name in QUESTIE_FILES:
        body = get(QUESTIE + name)
        with open(os.path.join(qdir, name), "wb") as f:
            f.write(body)
        print(f"  questie/{name}: {len(body):,} bytes")
    # Classic loot tables and item data from the vmangos project (GPLv2), SQLite snapshot
    import io
    import zipfile
    rel = json.loads(get("https://api.github.com/repos/vmangos/core/releases/tags/db_latest"))
    asset = next(a for a in rel["assets"] if a["name"].startswith("db-sqlite") and a["name"].endswith(".zip"))
    print(f"  vmangos {asset['name']}: {asset['size']:,} bytes (downloading...)")
    with zipfile.ZipFile(io.BytesIO(get(asset["browser_download_url"]))) as z:
        name = next(n for n in z.namelist() if n.endswith("mangos.sqlite"))
        os.makedirs(os.path.join(DATA, "vmangos"), exist_ok=True)
        with open(os.path.join(DATA, "vmangos", "mangos.sqlite"), "wb") as f:
            f.write(z.read(name))
    with open(os.path.join(DATA, "BUILD.txt"), "w") as f:
        f.write(build)
    print("Done. Now run:  py build_db.py")


if __name__ == "__main__":
    main()
