"""Generate terrain-colors.js: what each colour of the server's 2D map (/Layers/TerrainLatest.gif) means for driving.

The map colours each column by its top solid block, using Eco's AutoGenBlockColorMap (many blocks share a colour).
Water is not drawn: under water the top solid block is the riverbed or seabed. So:
  road     colour -> Road(efficiency): DirtRoad + dirt ramps 1.0, StoneRoad 1.1, AsphaltConcrete 1.2
  natural  colour -> ground MoveEfficiency: DirtBlock-derived soils/sand 0.9, tilled dirt and sand 0.8, rock/ore 1.0
  riverbed colour -> water above it (rivers, lakes); the ocean is found by height (at or below sea level) instead
  forest   colour -> forest biome soils: trees aren't on the map but block vehicles
Anything else is a constructed block (floors, walls, bridge decks); the page treats it as drivable at efficiency 1.0
and relies on the height map to stop it driving through walls.

Usage (from the repo root): python tools/build_terrain_colors.py --eco <path to Eco>/Server
"""
import argparse
import collections
import json
import os
import re


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--eco", required=True, help="the Server folder of an Eco source checkout")
    a = ap.parse_args()
    colormap = open(os.path.join(a.eco, "Eco.Simulation", "WorldLayers", "History", "AutoGenBlockColorMap.cs"), encoding="utf-8").read()
    names_by_hex = collections.defaultdict(set)
    for name, val in re.findall(r'\{\s*"(\w*)",\s*0x([0-9A-Fa-f]{8})\s*\}', colormap):
        names_by_hex[val[2:].upper()].add(name)

    terrain = open(os.path.join(a.eco, "Eco.World", "Blocks", "TerrainBlocks.cs"), encoding="utf-8").read()
    dirt_like = set(re.findall(r"class (\w+)Block : DirtBlock", terrain)) | {"Dirt"}          # MoveEfficiency 0.9 (DirtBlock)
    slow = {"TilledDirt": 0.8, "Sand": 0.8}                                                    # their own MoveEfficiency(0.8f)
    blockdir = os.path.join(a.eco, "Mods", "__core__", "AutoGen", "Block")
    mineral = set()
    for f in os.listdir(blockdir):
        src = open(os.path.join(blockdir, f), encoding="utf-8-sig", errors="replace").read()
        if re.search(r"\b(Minable|Diggable|Excavatable)\b", src) or f.startswith("Crushed") or f.endswith("Ore.cs") or f in ("Coal.cs", "Peat.cs"):
            mineral.add(f[:-3])
    river = {"RiverSand", "Riverbed"}
    forest = {"ColdForestSoil", "WarmForestSoil", "RainforestSoil", "TaigaSoil", "WetlandsSoil", "ForestSoil"}

    def road_eff(name):
        if name.startswith("AsphaltConcrete"): return 1.2
        if name.startswith("StoneRoad"): return 1.1
        if name.startswith(("DirtRoad", "DirtRamp")): return 1.0
        return None

    out = {"road": {}, "natural": {}, "riverbed": [], "forest": []}
    for hx, names in sorted(names_by_hex.items()):
        roads = [road_eff(n) for n in names if road_eff(n) is not None]
        if roads:  # a road colour wins even when shared (StoneRoad shares 747474 with ashlar-limestone shapes)
            out["road"][hx] = max(roads)
            continue
        if names & river:
            out["riverbed"].append(hx)  # shares its colour with CrushedMixedRock piles, which then also read as water
        natural = [n for n in names if n in dirt_like or n in slow or n in mineral or n in river]
        if natural and len(natural) == len(names):
            out["natural"][hx] = min(slow[n] if n in slow else 0.9 if n in dirt_like or n in river else 1.0 for n in natural)
        if names & forest:
            out["forest"].append(hx)

    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    with open(os.path.join(root, "terrain-colors.js"), "w", encoding="utf-8", newline="\n") as f:
        f.write("//Meaning of the server's 2D map colours for driving, from Eco's AutoGenBlockColorMap and block attributes.\n"
                "//Regenerate with: python tools/build_terrain_colors.py --eco <path to Eco>/Server\n")
        f.write("window.TERRAIN_COLORS = " + json.dumps(out, indent=1) + ";\n")
    print(f"roads {len(out['road'])}, natural {len(out['natural'])}, riverbed {out['riverbed']}, forest {out['forest']}")


if __name__ == "__main__":
    main()
