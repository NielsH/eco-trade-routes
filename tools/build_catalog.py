"""Build items.json (weight, stack size, carried) and vehicles.json (slots, max weight, speed) from Eco C# sources.

Reads an Eco server source checkout (its `Server` folder), then optionally overlays a server's `Mods/UserCode` folder
(item overrides and modded items; only its top level and `AutoGen/<kind>/*.override.cs` are read, so a slow network
mount is fine). The live page gets items from RecipeApi's /items; this script mainly regenerates vehicles.js.

vehicles.json is meant to be edited: modular vehicles (trucks, tractors) get their storage from fitted modules and
are written with null slots/weight, to be filled in by hand.

Usage (from the repo root): python tools/build_catalog.py --eco <path to Eco>/Server [--server <server>/Mods/UserCode] [--out data]
"""
import argparse
import glob
import json
import os
import re

CLASS_RE = re.compile(r"(?:public|internal)\s+(?:abstract\s+|partial\s+|sealed\s+)*class\s+(\w+)(?:<[^>]*>)?\s*:\s*([\w.]+)")
STORAGE_RE = re.compile(r"GetComponent<PublicStorageComponent>\(\)\.Initialize\((\d+),\s*(\d+)\s*(?:,\s*([^;]*))?\);")
VEHICLE_RE = re.compile(r"GetComponent<VehicleComponent>\(\)\.Initialize\(([\d.]+)f?,\s*([\d.]+)f?(?:,\s*(\d+))?(?:,\s*null,\s*(true))?")


def scan_classes(path, classes):
    try:
        text = open(path, encoding="utf-8-sig", errors="replace").read()
    except OSError:
        return
    for m in CLASS_RE.finditer(text):
        # Attributes are the run of `[...]`, comment and blank lines directly above the class line. (Not "back to the
        # previous brace": attribute arguments like `new float[] {1f, 1.4f}` contain braces.)
        lines = text[:m.start()].split("\n")
        attr_lines = [lines.pop()]  # modifiers on the class line itself
        while lines and (lines[-1].strip().startswith(("[", "//", "///")) or not lines[-1].strip()):
            attr_lines.append(lines.pop())
        attrs = "\n".join(reversed(attr_lines))
        name, base = m.group(1), m.group(2).split(".")[-1]
        if name == base:
            # `RampItem<T> : RampItem` -- the generic and plain class share a key once generics are stripped; fold the
            # generic's attributes into the plain one instead of creating a self-loop.
            c = classes.setdefault(name, {"base": None, "weight": None, "stack": None, "carried": False, "file": path})
            w = re.search(r"\bWeight\((\d+)\)", attrs); st = re.search(r"\bMaxStackSize\((\d+)\)", attrs)
            c["weight"] = c["weight"] if c["weight"] is not None else (int(w.group(1)) if w else None)
            c["stack"] = c["stack"] if c["stack"] is not None else (int(st.group(1)) if st else None)
            c["carried"] = c["carried"] or bool(re.search(r"(?<!Not)\bCarried\b", attrs))
            continue
        w = re.search(r"\bWeight\((\d+)\)", attrs)
        s = re.search(r"\bMaxStackSize\((\d+)\)", attrs)
        prev = classes.get(name, {})
        classes[name] = {
            # A later file (server override) replaces the whole class, like UserCode .override.cs does.
            "base": base,
            "weight": int(w.group(1)) if w else None,
            "stack": int(s.group(1)) if s else None,
            "carried": bool(re.search(r"(?<!Not)\bCarried\b", attrs)),
            "file": path,
        } if not prev or path.endswith(".override.cs") or prev.get("base") is None else prev


def resolve(name, classes, depth=0):
    """Walk the base chain: attributes are inherited (ItemAttribute caches GetCustomAttributes(inherit: true))."""
    c = classes.get(name)
    if c is None or depth > 20:
        return {"weight": None, "stack": None, "carried": False}
    parent = resolve(c["base"], classes, depth + 1)
    return {
        "weight": c["weight"] if c["weight"] is not None else parent["weight"],
        "stack": c["stack"] if c["stack"] is not None else parent["stack"],
        "carried": c["carried"] or parent["carried"],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--eco", required=True, help="the Server folder of an Eco source checkout")
    ap.add_argument("--server", help="a server's Mods/UserCode folder, to include its overrides and modded items")
    ap.add_argument("--out", default="data")
    ap.add_argument("--stack-multiplier", type=float, default=1.0, help="Difficulty.eco StackSizeMultiplier (FactorEco: 1.0)")
    a = ap.parse_args()

    classes = {}
    for root in ("Eco.Gameplay", "Eco.Shared", "Mods/__core__"):
        for p in glob.glob(os.path.join(a.eco, root, "**", "*.cs"), recursive=True):
            if os.sep + "obj" + os.sep not in p and "/obj/" not in p:
                scan_classes(p, classes)
    overrides = []
    for p in glob.glob(f"{a.server}/*/*.cs") + glob.glob(f"{a.server}/*.cs") if a.server else []:  # modded items, one level deep
        if "/AutoGen" not in p.replace(os.sep, "/"):
            scan_classes(p, classes)
    for sub in ("Item", "Block", "Vehicle") if a.server else ():
        for p in glob.glob(f"{a.server}/AutoGen/{sub}/*.override.cs"):  # one directory listing each, no recursion
            scan_classes(p, classes)
            overrides.append(os.path.basename(p))

    items = {}
    def is_item(name, depth=0):
        c = classes.get(name)
        return c is not None and depth < 20 and (c["base"] == "Item" or is_item(c["base"], depth + 1))

    for name in classes:
        if not is_item(name):
            continue
        r = resolve(name, classes)
        items[name] = {
            "weightKg": (r["weight"] or 0) / 1000,
            "stackSize": int((r["stack"] or 100) * a.stack_multiplier),  # MaxStackSizeAttribute.Default = 100
            "carried": r["carried"],
        }

    vehicles = {}
    for p in sorted(glob.glob(os.path.join(a.eco, "Mods/__core__/AutoGen/Vehicle/*.cs"))):
        src = open(p, encoding="utf-8-sig").read()
        v = VEHICLE_RE.search(src)
        if not v:
            continue
        s = STORAGE_RE.search(src)
        # Not transport: a digging/farming tool bucket (excavator, skid steer, steam tractor) isn't cargo, and a vehicle with
        # neither cargo storage nor modules (crane, hand plow) carries nothing.
        if "VehicleToolComponent" in src or (not s and "ModularVehicleComponent" not in src):
            continue
        name = os.path.basename(p)[:-3]
        vehicles[name] = {
            "slots": int(s.group(1)) if s else None,
            "maxWeightKg": int(s.group(2)) / 1000 if s else None,
            "restriction": (s.group(3) or "").strip() or None if s else None,
            "speed": float(v.group(1)),
            "roadMult": float(v.group(2)),  # VehicleComponent roadEfficiencyMultiplier: surface factor = 1 + (MoveEfficiency - 1) * this
            "water": "BoatComponent" in src,  # the 5th VehicleComponent.Initialize arg is isDrivenUnderwater, not "is a boat"
            "modular": "ModularVehicleComponent" in src,
            "note": "storage comes from fitted modules: fill in slots/maxWeightKg by hand" if "ModularVehicleComponent" in src and not s else None,
        }
    # Not a vehicle, but a useful baseline: walking with backpack + carried slot. Fill in from your own inventory.
    vehicles["OnFoot"] = {"slots": None, "maxWeightKg": None, "restriction": None, "speed": 5.0, "water": False, "roadMult": 0.0,
                          "modular": False, "note": "fill in your backpack slots and weight limit"}

    os.makedirs(a.out, exist_ok=True)
    json.dump(dict(sorted(items.items())), open(os.path.join(a.out, "items.json"), "w"), indent=1)
    vpath = os.path.join(a.out, "vehicles.json")
    if os.path.exists(vpath):
        # Keep hand edits: only add vehicles that aren't there yet.
        existing = json.load(open(vpath))
        vehicles = {**vehicles, **existing}
    json.dump(vehicles, open(vpath, "w"), indent=1)
    # The web page reads the same table from vehicles.js at the repo root.
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    def slim_entry(v):
        out = {f: v.get(f) for f in ("slots", "maxWeightKg", "speed", "water", "roadMult")}
        tags = re.findall(r'TagRestriction\(\s*"([^"]+)"', v.get("restriction") or "")
        if tags:  # same shape the page gets from /vehicles, by tag because the static table has no item list
            out["storages"] = [{"Accepts": {"OnlyTags": tags}}]
        return out
    slim = {k: slim_entry(v) for k, v in sorted(vehicles.items())}
    open(os.path.join(root, "vehicles.js"), "w", encoding="utf-8", newline="\n").write(
        "//Vehicle cargo capacity and speed, from Eco's AutoGen vehicle sources. Regenerate with: python tools/build_catalog.py\n"
        "//Modular vehicles (trucks, tractors) get storage from fitted modules: slots/maxWeightKg are null, set them in the page.\n"
        "window.VEHICLES = " + json.dumps(slim, indent=1) + ";\n")
    print(f"{len(items)} items, {len(vehicles)} vehicles; server overrides applied: {', '.join(overrides) or 'none'}")


if __name__ == "__main__":
    main()
