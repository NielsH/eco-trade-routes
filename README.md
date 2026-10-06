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
- **Storage space** at a buyer: the server's dry run of each delivery (per item, also for tag offers like "any Wood"),
  plus the store's free slots shared by everything one run sells there. A store whose storage only takes non-carried
  items gets no logs, whatever its offer says.
- **Continue from <last stop>** plans the next run from where this one ends, assuming its trades happened.
  **Refresh** reloads the real state.
- **Vehicle**: your own placed vehicles (when you picked your player), every vehicle type placed on the server, and a
  built-in table (`vehicles.js`) for types nobody has placed. Only hauling vehicles are offered: digging and farming
  vehicles (excavator, skid steer, tractors) load into a tool bucket, not cargo. A vehicle's own item rules apply, e.g.
  the Scorpion only takes logs, 100 per slot.
- **Boat for water crossings**: pick a boat to bring along with a land vehicle. You pack one vehicle up and carry it in
  the other, so routes switch between land and water at any shore (both ways), each switch costing "Switch min" (default
  1). Cargo is limited by the smaller of the two vehicles; the map draws boat stretches with a blue edge and the run card
  says how much of a leg is by boat.
- **Settings**: vehicle slots, max kg and speed (editable), cash limit, legs, currency, time per stop, road
  factor (road distance / straight line) and a sale bonus %.

## Routing

Travel times are routed over the real map (`routing.js`, in a background worker; about a second for 100 shops):

- **Roads** are read from the map colours (dirt road 1.0, stone road 1.1, asphalt 1.2: Eco's `Road` efficiency). A
  vehicle's speed on a surface is `1 + (efficiency − 1) × road multiplier`, as in Eco's client (Powered Cart 1.5,
  Truck 4: trucks gain most from roads).
- **Off road** is slower: the off-road speed setting (default 0.5), more so on bumpy ground (from the height map).
  Forest without a road (trees aren't on the map but block vehicles) and ground with natural 2-block steps are about 7×
  slower again, so a run only crosses them when there's no real alternative.
- **Water** is impassable for land vehicles unless something is built on it (a bridge). Boats only move on water and
  can reach a shop within about 12 blocks of it. The world wraps around, so a boat can sail off one edge of the
  map and come back on the opposite one. The map doesn't draw water, so it's inferred: riverbed, or natural
  ground below sea level.
- **Cliffs and walls** (natural steps of 3+ blocks off road, or more than one block up per block) can't be driven.
- **Long stretches without a road** are about 10× slower again: farther than half the "Off-road gap" setting (default 80
  blocks) from any road or built-up ground. A short hop between two patches of road costs nothing extra; a route across
  open country only wins when there's no alternative, and the run card flags such a leg.
- **Tunnels and overpasses**: the map shows what's on top, so a road through a tunnel looks cut by a wall. Where a
  straight road stops for at most 16 blocks under something at least 2 blocks above it, and carries on in the same line
  on the other side at about the same height, it's assumed to continue underneath. Longer tunnels, and anything under a
  roof, aren't visible. Shops that can't be reached are left out of runs.

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
