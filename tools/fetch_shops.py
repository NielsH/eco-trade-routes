"""Fetch live shop and item data from the RecipeApi web API and write data/shops.json + data/items.json.

Replaces extract_shops.py (save backup) and the item half of build_catalog.py (source parsing) once the server runs
RecipeApi with the /shops and /items routes. The output keeps the PoC shape so find_routes.py / plan_routes.py work
unchanged, plus the live-only fields (canAccept/canStore, emptySlots).

Usage: python fetch_shops.py [--server https://play.factoreco.org] [--data data]
"""
import argparse
import json
import os
import urllib.request


def norm(tag):
    return (tag or "").replace(" ", "").lower()


def tag_index(base, items):
    """Tag name -> item type names. Exact from /items Tags (RecipeApi with the Tags field); otherwise from /tags, which
    is keyed by display name and lists item display names, matched loosely."""
    if items and "Tags" in items[0]:
        index = {}
        for i in items:
            for t in i["Tags"]:
                index.setdefault(norm(t), []).append(i["Item"])
        return index, "exact (/items Tags)"
    by_name = {i["Name"]: i["Item"] for i in items}
    for url in (base + "/tags?all=true", base + "/tags"):  # ?all=true 500s on servers with a nameless mod tag (fixed in RecipeApi)
        try:
            tags = get(url)["Tags"]
        except Exception:
            continue
        return {norm(t): [by_name[n] for n in names if n in by_name] for t, names in tags.items()}, f"by display name ({url.rsplit('/', 1)[-1]})"
    return {}, "unavailable"


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "eco-trade-routes"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def offer(o, buying, key, tags):
    out = {
        "key": key, "tagItems": tags.get(norm(o.get("Tag")), []) if o.get("Tag") and not o.get("Item") else None,
        "item": o.get("Item"), "itemName": o.get("ItemName"), "tag": o.get("Tag"), "category": o.get("Category"),
        "price": o["Price"], "limit": o.get("Limit", 0),
        "minDurability": o.get("MinDurability"), "minIntegrity": o.get("MinIntegrity"),
    }
    if buying:
        # quantity = what the planner may sell here: the live CanAccept already folds in demand, the owner's money and
        # free storage. 999 + unlimited mirrors the save-based PoC for offers with no limit at all.
        accept = o.get("CanAccept")
        out.update({
            "quantity": accept if accept is not None else 999, "unlimited": o.get("Wanted") is None,
            "wanted": o.get("Wanted"), "canAfford": o.get("CanAfford"), "canStore": o.get("CanStore"), "canAccept": accept,
        })
    else:
        out.update({"quantity": o["Available"], "unlimited": False})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="https://play.factoreco.org")
    ap.add_argument("--data", default="data")
    a = ap.parse_args()
    base = a.server.rstrip("/") + "/api/v1/plugins/RecipeApi"
    os.makedirs(a.data, exist_ok=True)

    items = get(base + "/items")["Items"]
    tags, tag_source = tag_index(base, items)
    raw = get(base + "/shops")
    shops, errors = [], []
    for s in raw["Shops"]:
        if "Error" in s:
            errors.append(f"{s.get('Name')}: {s['Error']}")
            continue
        p = s["Position"]
        shops.append({
            "id": s["Id"], "name": s["Name"], "owner": s.get("Owner"), "creator": s.get("Creator"),
            "position": {"x": p["X"], "y": p["Y"], "z": p["Z"]},
            "on": s["On"], "enabled": s["Enabled"], "operating": s["Operating"],
            "currency": s.get("Currency"), "bankAccount": s.get("BankAccount"),
            "balance": "infinite" if s.get("UnlimitedBalance") else s.get("Balance"),
            "emptySlots": s.get("EmptySlots"),
            "sells": [offer(o, False, f"{s['Id']}/s{n}", tags) for n, o in enumerate(s["Sells"])],
            "buys": [offer(o, True, f"{s['Id']}/b{n}", tags) for n, o in enumerate(s["Buys"])],
            "links": [],
        })
    shops.sort(key=lambda s: (s["name"] or "").lower())
    json.dump({"source": f"{a.server} at {raw['GeneratedAt']}", "worldSize": {"x": 2000, "z": 2000}, "shops": shops},
              open(os.path.join(a.data, "shops.json"), "w", encoding="utf-8"), indent=1)

    json.dump({i["Item"]: {"weightKg": i["Weight"] / 1000, "stackSize": i["MaxStackSize"], "carried": i["Carried"], "name": i["Name"],
                            "tags": i.get("Tags")}
               for i in items}, open(os.path.join(a.data, "items.json"), "w", encoding="utf-8"), indent=1)

    tag_offers = [o for s in shops for o in s["buys"] if o["tagItems"] is not None]
    unresolved = sorted({o["tag"] for o in tag_offers if not o["tagItems"]})
    print(f"{len(shops)} shops, {len(items)} items from {a.server} (generated {raw['GeneratedAt']})")
    print(f"{len(tag_offers)} tag buy offers, tags resolved {tag_source}" + (f"; unresolved: {', '.join(unresolved)}" if unresolved else ""))
    for e in errors:
        print("  shop error:", e)


if __name__ == "__main__":
    main()
