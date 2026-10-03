# Eco trade routes

A route planner for shop arbitrage on an [Eco](https://play.eco) server: buy at one shop, sell at another for more,
and chain the trips. It runs entirely in the browser, so it works on GitHub Pages.

It reads the server live:

| Source | Used for |
| --- | --- |
| `/api/v1/plugins/RecipeApi/shops` | every shop: position, status, currency, owner balance, offers, and how much each buy offer can take right now |
| `/api/v1/plugins/RecipeApi/items` | weight, stack size, carried flag and tags of every item |
| `/api/v1/plugins/RecipeApi/players` | online players' positions, to plan from where you stand |
| `/api/v1/plugins/RecipeApi/vehicles` | placed vehicles with their real cargo storage: slots, weight, exactly which items fit and how many per slot, fitted modules |
| `/api/v1/plugins/RecipeApi/tags` | fallback for tag offers on servers whose `/items` has no `Tags` yet |
| `/Layers/TerrainLatest.gif` | the server's own 2D map: the backdrop, and roads/ground/water for routing |
| `/Layers/HeightMapLatest.gif`, `/api/v1/map/waterLevel`, `/api/v1/map/dimension` | block heights and sea level, for routing |

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
- **Vehicle**: your own placed vehicles (when you picked your player), every vehicle type placed on the server, and a
  built-in table (`vehicles.js`) for types nobody has placed. Only hauling vehicles are offered: digging and farming
  vehicles (excavator, skid steer, tractors) load into a tool bucket, not cargo. A vehicle's own item rules apply, e.g.
  the Scorpion only takes logs, 100 per slot.
- **Settings**: vehicle slots, max kg and speed (editable), cash limit, legs, currency, time per stop, road
  factor (road distance / straight line) and a sale bonus %. Turn on edge wrap for boats only: on a world ringed by
  ocean, land vehicles can't cross the edge.

## Routing

Travel times are routed over the real map (`routing.js`, in a background worker; about a second for 100 shops):

- **Roads** are read from the map colours (dirt road 1.0, stone road 1.1, asphalt 1.2: Eco's `Road` efficiency). A
  vehicle's speed on a surface is `1 + (efficiency − 1) × road multiplier`, as in Eco's client (Powered Cart 1.5,
  Truck 4: trucks gain most from roads).
- **Off road** is slower: the off-road speed setting (default 0.5), more so on bumpy ground (from the height map).
  Forest without a road (trees aren't on the map but block vehicles) and ground with natural 2-block steps are about 7×
  slower again, so a run only crosses them when there's no real alternative.
- **Water** is impassable for land vehicles unless something is built on it (a bridge). Boats only move on water and
  can reach a shop within about 12 blocks of it. The map doesn't draw water, so it's inferred: riverbed, or natural
  ground below sea level.
- **Cliffs and walls** (natural steps of 3+ blocks off road, or more than one block up per block) can't be driven.
- **Not visible from above**: tunnels, and anything under a roof. Shops that can't be reached are left out of runs.

The map shows each leg along its route with its share on roads. Switch "Travel time" to "straight line × road factor"
for the old estimate. Minutes are still estimates: the speed scale isn't calibrated against real trips yet.

## Tools (optional, Python)

`tools/` has command-line versions of the same planner plus helpers. None of them are needed for the page. Run them
from the repo root; they read and write `data/` (git-ignored).

| Script | Does |
| --- | --- |
| `fetch_shops.py` | live `/shops` + `/items` into `data/shops.json` and `data/items.json` |
| `plan_routes.py` | multi-stop runs (`--vehicle`, `--cash`, `--start "Shop" \| x,z`, `--legs`) |
| `find_routes.py` | direct A→B deals |
| `build_terrain_colors.py` | regenerate `terrain-colors.js` (what each map colour means for driving) from an Eco source checkout: `--eco <Eco>/Server` |
| `build_catalog.py` | regenerate `vehicles.js` (and `data/items.json`) from an Eco source checkout: `--eco <Eco>/Server [--server <server>/Mods/UserCode]` |
| `extract_shops.py` | shops from a save file (`Game.eco`) instead of the API; needs a sibling clone of [eco-save-reader](https://github.com/NielsH/eco-save-reader) |
