"""PoC: extract every shop from an Eco save into shops.json.

The output shape is the proposed contract for a future RecipeApi `/shops` endpoint, so the
route finder can switch from this file to the live API without changes.

Usage (from the repo root): python tools/extract_shops.py data/Game.eco data/shops.json
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "eco-save-reader"))  # sibling clone of NielsH/eco-save-reader
from ecosave import SaveFile  # noqa: E402


def type_name(t):
    """'class[Eco.Mods.TechTree.CopperOreItem]' -> 'CopperOreItem'."""
    m = re.match(r"class\[(?:.*\.)?([^.\]]+)\]", t or "")
    return m.group(1) if m else t


def ref_id(v):
    return v.get("$id", v.get("SerializedID")) if isinstance(v, dict) else None


def component(obj, suffix):
    for c in obj.get("Components") or []:
        if isinstance(c, dict) and c.get("$type", "").endswith(suffix + "]"):
            return c
    return None


def offer_json(o):
    tag = o.get("Tag")
    item = (o.get("Stack") or {}).get("Item")
    qty = (o.get("Stack") or {}).get("Quantity", 0)
    buying = bool(o.get("Buying"))
    return {
        "item": type_name(item["$type"]) if isinstance(item, dict) and "$type" in item else None,
        "tag": (tag.get("Name") or tag.get("name") or type_name(tag.get("$type", ""))) if isinstance(tag, dict) else None,
        "price": round(float(o.get("Price") or 0), 4),
        # Store caches these on every stock change (StoreComponent.UpdateStock):
        #   selling: units available to customers (stock minus Limit, which is a keep-in-reserve)
        #   buying : units it still wants (Limit minus stock), 999 when unlimited
        "quantity": qty,
        "limit": o.get("Limit", 0),
        "unlimited": buying and not o.get("Limit"),
        "minDurability": o.get("MinDurability"),
        "minIntegrity": o.get("MinIntegrity"),
    }


def main(save_path, out_path):
    with SaveFile(save_path) as save:
        users = {u["SerializedID"]: u["Name"] for _n, u, e in save.read_all("Users/") if e is None}
        econ = save.read("EconomyManager/Data")
        currencies = {c["SerializedID"]: c for c in econ["CurrencyRegistrar"]["Objs"]}
        accounts = {a["SerializedID"]: a for a in econ["BankAccountsRegistrar"]["Objs"]}
        meta = {}
        try:
            meta = json.loads(save.read_raw("meta.json")) if hasattr(save, "read_raw") else {}
        except Exception:
            pass

        shops = []
        for name, obj, err in save.read_all("WorldObjects/"):
            if err or not isinstance(obj, dict):
                continue
            store = component(obj, "StoreComponent")
            if store is None:
                continue
            credit = (component(obj, "CreditComponent") or {}).get("CreditData") or {}
            onoff = component(obj, "OnOffComponent") or {}
            cur_id = ref_id(credit.get("Currency"))
            acc_id = ref_id(credit.get("BankAccount"))
            acc = accounts.get(acc_id)
            balance = None
            if acc and cur_id is not None:
                for h in acc.get("CurrencyHoldings") or []:
                    if ref_id(h["key"]) == cur_id:
                        balance = h["value"].get("val")
            if isinstance(balance, float) and balance == float("inf"):
                balance = "infinite"  # issuer's own credit currency

            data = store.get("StoreData") or {}
            sells, buys = [], []
            for cat in data.get("SellCategories") or []:
                sells += [dict(offer_json(o), category=cat.get("Name")) for o in cat.get("Offers") or []]
            for cat in data.get("BuyCategories") or []:
                buys += [dict(offer_json(o), category=cat.get("Name")) for o in cat.get("Offers") or []]

            links = []
            link = component(obj, "LinkComponent")
            for s in (link or {}).get("settings") or []:
                k, v = s["key"], s["value"]
                links.append({
                    "objectId": (k.get("Object") or {}).get("ObjectID"),
                    "component": type_name(k.get("ComponentType")),
                    # Only player-modified entries are saved (LinkComponent.PruneSettings); the full link set
                    # is resolved at runtime, so this list is partial. Input = source, Output = target
                    # (LinkComponent.GetSortedLinkedComponents).
                    "source": v.get("Input"),    # store sells from it (StockInventories)
                    "target": v.get("Output"),   # store deposits bought items into it
                })

            pos = obj.get("Position") or [0, 0, 0]
            shops.append({
                "id": obj.get("ObjectID"),
                "name": obj.get("GivenName"),
                "owner": users.get(ref_id(obj.get("Creator"))),
                "position": {"x": round(pos[0], 1), "y": round(pos[1], 1), "z": round(pos[2], 1)},
                "on": bool(onoff.get("on")),
                "enabled": bool(obj.get("enabled")),
                "operating": bool(obj.get("operating")),
                "currency": currencies[cur_id]["Name"] if cur_id in currencies else None,  # None = barter
                "bankAccount": acc.get("Name") if acc else None,
                "balance": balance,
                "sells": sells,
                "buys": buys,
                "links": links,
            })

    shops.sort(key=lambda s: (s["name"] or "").lower())
    out = {"source": os.path.abspath(save_path), "worldSize": {"x": 2000, "z": 2000}, "shops": shops}
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)
    print(f"{len(shops)} shops -> {out_path}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
