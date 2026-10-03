# Eco trade routes

A route planner for shop arbitrage on an [Eco](https://play.eco) server: buy at one shop, sell at another for more,
and chain the trips. It runs entirely in the browser, so it works on GitHub Pages.

It reads the server live:

| Source | Used for |
| --- | --- |
| `/api/v1/plugins/RecipeApi/shops` | every shop: position, status, currency, owner balance, offers, and how much each buy offer can take right now |
| `/api/v1/plugins/RecipeApi/items` | weight, stack size, carried flag and tags of every item |
| `/api/v1/plugins/RecipeApi/players` | online players' positions, to plan from where you stand |
| `/api/v1/plugins/RecipeApi/tags` | fallback for tag offers on servers whose `/items` has no `Tags` yet |
| `/Layers/TerrainLatest.gif` | the server's own 2D map, used as the backdrop |

The `RecipeApi` routes come from the [EcoRecipeApi](https://github.com/NielsH/eco-recipe-api) server mod. Eco's web
server sends `Access-Control-Allow-Origin: *`, so a page on any host can read them.

## Use

Open `index.html`: the GitHub Pages site, or the file locally. The server defaults to `https://play.factoreco.org`;
point it elsewhere with `?server=https://your.server`.

- **Start**: anywhere, **Pick on map** (click a spot or a shop), **Start here** on a shop, or your player from the
  dropdown.
- **Runs**: multi-stop routes ranked by profit per minute. Each stop sells the load and buys a mixed load for the next
  leg, within the vehicle's slots and weight, your cash, the seller's stock, the buyer's demand, money and storage
  space. Spare room on a leg is filled with goods for a later stop (side deals).
- **Continue from <last stop>** plans the next run from where this one ends, assuming its trades happened.
  **Refresh** reloads the real state.
- **Settings**: vehicle (slots, max kg and speed are editable), cash limit, legs, currency, time per stop, road
  factor (road distance / straight line) and a sale bonus %. Turn on edge wrap for boats only: on a world ringed by
  ocean, land vehicles can't cross the edge.

Travel time is straight-line distance × road factor ÷ vehicle speed, so treat the minutes as an estimate.

## Tools (optional, Python)

`tools/` has command-line versions of the same planner plus helpers. None of them are needed for the page. Run them
from the repo root; they read and write `data/` (git-ignored).

| Script | Does |
| --- | --- |
| `fetch_shops.py` | live `/shops` + `/items` into `data/shops.json` and `data/items.json` |
| `plan_routes.py` | multi-stop runs (`--vehicle`, `--cash`, `--start "Shop" \| x,z`, `--legs`) |
| `find_routes.py` | direct A→B deals |
| `build_catalog.py` | regenerate `vehicles.js` (and `data/items.json`) from an Eco source checkout: `--eco <Eco>/Server [--server <server>/Mods/UserCode]` |
| `extract_shops.py` | shops from a save file (`Game.eco`) instead of the API; needs a sibling clone of [eco-save-reader](https://github.com/NielsH/eco-save-reader) |
