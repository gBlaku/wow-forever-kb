# WoW Forever Armory & item data

> **AI assistants (Claude, ChatGPT…):** to answer gear, quest or loot questions, read
> https://gblaku.github.io/wow-forever-kb/llms.txt first. It explains how to answer and links
> to every class, level, item and dungeon page.
>
> **Coding agents (Claude Code, Codex…):** you can also query the data directly. No build is needed:
> ```bash
> git clone https://github.com/gBlaku/wow-forever-kb && cd wow-forever-kb
> curl -LO https://gblaku.github.io/wow-forever-kb/wow_forever.db
> python query.py --class hunter --level 40 --slot ranged      # see --help; or use --sql
> ```

A free, searchable database of **World of Warcraft: Forever** items, quest rewards and boss loot.
It's built from the game client's own data, plus open-source quest and loot databases, and rebuilt
automatically every day.

- **Search it:** https://gblaku.github.io/wow-forever-kb/
- **Query it with SQL in your browser:** [open in Datasette Lite](https://lite.datasette.io/?url=https://gblaku.github.io/wow-forever-kb/wow_forever.db)
- **Ask an AI:** paste https://gblaku.github.io/wow-forever-kb/llms.txt into Claude or ChatGPT, then
  ask e.g. "best weapons for a level 40 hunter" or "what drops in Uldaman"
- **Use it from code:** plain JSON and CSV files, listed [below](#data-api)

## For players

Open the [Armory](https://gblaku.github.io/wow-forever-kb/):

1. Pick your **class**, **level** and **slot**, or click a quick button like "Hunter 40 · one-hand".
2. Results are sorted by DPS. Use **Sort by** to sort by a stat such as Agility.
3. Click an item for its in-game style tooltip and **How to get it**: quest, boss with drop chance,
   vendor, chest or crafting.
4. The search box also finds bosses and zones. Try `Herod` or `Uldaman`.
5. The **Quests** tab lists quests in your level range with what they reward. Rewards your class
   can't use are crossed out.

Items marked **Classic data** are still hidden in the Forever client. Their stats come from Classic
and may change.

## For AI assistants

[`llms.txt`](https://gblaku.github.io/wow-forever-kb/llms.txt) is the entry point. It explains the
data and links to short Markdown pages an assistant can read in one go:

- `ai/<class>.md`: weapon and armor rules, and links to levels 1-60
- `ai/<class>/<level>.md`: best items per slot at that level, with stats and how to get each one,
  plus quests with rewards ([example: hunter 40](https://gblaku.github.io/wow-forever-kb/ai/hunter/40.md))
- `ai/item/<id>.md`: one item, with every source, drop chance and Wowhead link
- `ai/zones.md` and `ai/zone/<name>.md`: dungeons, raids and zones, with their bosses and loot
- `ai/names/<letter>.md`: item name index

Every link is written out in full because AI browsing tools only open URLs they have already seen.
Rankings use rough per-class stat values (listed on each class page), so the assistant should
adjust for the player's spec.

## Data API

There is no server and no key. These are static files on GitHub Pages, served with CORS, so they work
from scripts, spreadsheets, bots and web pages. Base URL: `https://gblaku.github.io/wow-forever-kb/`

| File | What's in it |
|---|---|
| [`api/meta.json`](https://gblaku.github.io/wow-forever-kb/api/meta.json) | Game build, when it was generated, counts, sources |
| [`api/items.json`](https://gblaku.github.io/wow-forever-kb/api/items.json) · [`.csv`](https://gblaku.github.io/wow-forever-kb/api/items.csv) | Every known item (about 23,000), one object/row each |
| [`api/item_sources.json`](https://gblaku.github.io/wow-forever-kb/api/item_sources.json) · [`.csv`](https://gblaku.github.io/wow-forever-kb/api/item_sources.csv) | How to get each item: quest, drop (with % chance), vendor, chest, crafted |
| [`api/quests.json`](https://gblaku.github.io/wow-forever-kb/api/quests.json) · [`.csv`](https://gblaku.github.io/wow-forever-kb/api/quests.csv) | Every quest: level, pick-up level, faction, zone, quest giver |
| [`api/proficiency.json`](https://gblaku.github.io/wow-forever-kb/api/proficiency.json) | Which weapons and armor each class can use, and from what level |
| [`wow_forever.db`](https://gblaku.github.io/wow-forever-kb/wow_forever.db) | Everything in one SQLite database (about 22 MB) |

In the JSON files, empty fields are left out. The CSV files have every column.

### Examples

Python:

```python
import json, urllib.request

base = "https://gblaku.github.io/wow-forever-kb/api/"
items = json.load(urllib.request.urlopen(base + "items.json"))

hunter_bit = 1 << (3 - 1)  # class ids: Warrior 1, Paladin 2, Hunter 3, Rogue 4, Priest 5, Shaman 7, Mage 8, Warlock 9, Druid 11
daggers = [i for i in items
           if i.get("subclass") == "Dagger" and i.get("required_level", 0) <= 40
           and (i.get("class_mask", -1) in (-1, 0) or i["class_mask"] & hunter_bit)]
for i in sorted(daggers, key=lambda i: -i.get("dps", 0))[:5]:
    print(i["name"], i.get("dps"), i.get("agility"), i.get("source_summary"))
```

JavaScript:

```js
const items = await (await fetch("https://gblaku.github.io/wow-forever-kb/api/items.json")).json();
const ravager = items.find((i) => i.name === "Ravager");
console.log(ravager.dps, ravager.source_summary); // "Drop: Herod (lvl 40 elite, Scarlet Monastery, 25%)"
```

SQL in the browser: [best agility weapons up to level 40](https://lite.datasette.io/?url=https://gblaku.github.io/wow-forever-kb/wow_forever.db#/wow_forever?sql=select%20name%2C%20subclass%2C%20required_level%2C%20dps%2C%20agility%2C%20attack_power%2C%20source_summary%0Afrom%20visible_items%0Awhere%20item_class%20%3D%20%27Weapon%27%20and%20required_level%20%3C%3D%2040%20and%20agility%20%3E%200%0Aorder%20by%20dps%20desc%20limit%2020).
Edit the query and download the results as JSON or CSV.

### Item fields

| Field | Meaning |
|---|---|
| `id`, `name`, `wowhead` | Item ID, name, Wowhead link |
| `quality`, `quality_name` | 0 Poor … 2 Uncommon, 3 Rare, 4 Epic, 5 Legendary |
| `item_level`, `required_level` | As on the tooltip (`required_level` 0 = no requirement) |
| `level_hint` | The level the item is really for: required level, or for items with no requirement, the level of its quest or the creature that drops it |
| `item_class`, `subclass`, `slot` | e.g. Weapon / Dagger / One-Hand, Armor / Leather / Chest |
| `class_mask`, `classes` | Class restriction (bit = class id − 1; −1 or 0 = everyone) |
| `speed`, `min_damage`, `max_damage`, `dps` | Weapons (`dps_approx` = 1 for a few hand-tuned weapons) |
| `armor` | Armor value |
| `agility`, `strength`, `stamina`, `intellect`, `spirit`, `attack_power`, `crit`, `hit`, `spell_power`, `*_res`, … | Stats |
| `effects` | Equip / Use / Chance on hit text |
| `source_types`, `source_summary` | How to get it (summary). Details are in `item_sources` |
| `estimated` | 1 = hidden in the Forever client; name and stats are from Classic |
| `bonding`, `is_unique`, `item_set`, `required_reputation`, `sell_price_copper` | As named |

`item_sources` columns: `item_id`, `kind` (quest, drop, vendor, object, crafted, container),
`source_id` (quest, NPC, chest or spell ID; 0 = world-drop summary), `name`, `min_level`, `max_level`,
`zone`, `extra` (faction for quests, elite/boss for creatures, recipe info), `chance` (% per kill
or per chest), and `wowhead` (link to the quest, NPC, chest or recipe).

Wowhead links are built from the game's own IDs, so they always point at the right page. For items
still hidden in Forever, Wowhead may not show stats until a player finds the item.

## Run it yourself

Needs Python 3.9+ with nothing else to install.

```bash
python download_data.py   # game tables, Questie and vmangos data (about 70 MB)
python build_db.py        # builds wow_forever.db
python export_web.py      # data for the page
python export_api.py      # site/ folder: page + API files
python export_ai.py       # site/llms.txt + site/ai/ pages for AI assistants
python query.py --class hunter --level 40 --slot one-hand
python query.py --quests --class hunter --faction horde --level 40
python query.py --name "Ravager"
```

Run `python query.py --help` for all options: class, level, slot, type, quality, stat, source,
sort, and raw `--sql`.

The [GitHub Action](.github/workflows/pages.yml) runs these steps every day and publishes `site/`
to GitHub Pages.

## Where the data comes from

| Data | Source |
|---|---|
| Items: names, stats, damage, armor, effects, crafting | WoW Forever client tables (DB2), exported by [wago.tools](https://wago.tools) (product `wowf`). Stats, damage and armor use Blizzard's item-budget formulas and match Wowhead on the items checked |
| Quests, vendors | [Questie](https://github.com/Questie/QuestieDB) addon's WoW Forever database (`data/Forever`, GPLv3) |
| Creature and chest loot, drop chances; stats for items still hidden in Forever | [vmangos](https://github.com/vmangos/core) Classic world database (GPLv2) |

## Known limits

- **New Forever content:** quests, loot and items added in WoW Forever aren't in the Questie and
  vmangos data yet. About 7,500 new Forever items are hidden in the client, so there's no data for
  them anywhere yet.
- **Classic data:** Forever kept the Classic required level on 99% and the primary stats on 88% of
  items visible in both. Treat `estimated` items as close, not exact.
- **Class rules** follow Classic: Hunters and Shamans wear mail from 40, Warriors and Paladins wear
  plate from 40.
- **Random enchantments** ("of the Monkey" and similar) aren't included in item stats.

Not affiliated with or endorsed by Blizzard Entertainment. World of Warcraft is a trademark of
Blizzard Entertainment, Inc.
