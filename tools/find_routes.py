"""PoC: rank direct A->B shop arbitrage deals for a chosen vehicle.

Inputs (data/): shops.json (extract_shops.py), items.json + vehicles.json (build_catalog.py).

  python tools/find_routes.py --vehicle PoweredCart [--cash 500] [--top 25]     (from the repo root)
  python tools/find_routes.py --slots 24 --max-weight 5000 --speed 20     # ad-hoc vehicle, e.g. a fitted truck

Per deal: quantity = min(A's stock, B's wanted, B's money / price, your cash / price) and, per trip, what the vehicle
holds: min(slots x stack size, max weight / item weight). Travel time is straight-line distance (wrapping round the
world edge only with --wrap: FactorEco's island is ringed by ocean, so land vehicles can't) x
--route-factor / vehicle speed, so treat minutes as an estimate.
"""
import argparse
import json
import math
import os
import re

clean = lambda s: re.sub(r"<[^>]+>", "", s or "").strip()


def wrap_dist(a, b, size, wrap=False):
    dx = abs(a["x"] - b["x"]); dz = abs(a["z"] - b["z"])
    if wrap:
        dx, dz = min(dx, size["x"] - dx), min(dz, size["z"] - dz)
    return math.hypot(dx, dz)


def per_trip_capacity(item, vehicle):
    """Units of one item a vehicle carries in a single trip; None when the item isn't in the catalog."""
    if item is None:
        return None
    by_slots = vehicle["slots"] * item["stackSize"]
    by_weight = math.floor(vehicle["maxWeightKg"] / item["weightKg"]) if item["weightKg"] > 0 else by_slots
    return min(by_slots, by_weight)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--vehicle", default="PoweredCart", help="key in vehicles.json")
    ap.add_argument("--slots", type=int); ap.add_argument("--max-weight", type=float); ap.add_argument("--speed", type=float)
    ap.add_argument("--cash", type=float, default=float("inf"), help="money you can spend up front")
    ap.add_argument("--currency", default=None, help="only this currency (default: all)")
    ap.add_argument("--wrap", action="store_true", help="allow crossing the world edge (water vehicles)")
    ap.add_argument("--route-factor", type=float, default=1.3, help="road distance / straight-line distance")
    ap.add_argument("--bonus", type=float, default=0.0, help="extra fraction of sale value you receive (e.g. 0.1 for a transport-dailies rebate)")
    ap.add_argument("--sort", choices=["trip", "minute", "total"], default="trip")
    ap.add_argument("--top", type=int, default=25)
    a = ap.parse_args()

    load = lambda n: json.load(open(os.path.join(a.data, n), encoding="utf-8"))
    snap, items, vehicles = load("shops.json"), load("items.json"), load("vehicles.json")
    v = dict(vehicles.get(a.vehicle) or {})
    for k, val in (("slots", a.slots), ("maxWeightKg", a.max_weight), ("speed", a.speed)):
        if val is not None:
            v[k] = val
    if not v.get("slots") or not v.get("maxWeightKg") or not v.get("speed"):
        raise SystemExit(f"vehicle '{a.vehicle}' needs slots/maxWeightKg/speed: edit data/vehicles.json or pass --slots/--max-weight/--speed")
    if v.get("water"):
        print("warning: water vehicle; distances assume you can sail straight between shops")

    shops = [s for s in snap["shops"] if s["on"] and s["enabled"] and s["currency"]
             and (a.currency is None or s["currency"] == a.currency)]
    deals, unknown = [], set()
    for A in shops:
        for so in A["sells"]:
            if not so["item"] or so["quantity"] <= 0 or so["price"] < 0:
                continue  # negative sell prices (shop pays you to take it) are a different deal type; later
            for B in shops:
                if B is A or B["currency"] != A["currency"]:
                    continue
                for bo in B["buys"]:
                    accepts = bo["item"] == so["item"] if bo["item"] else so["item"] in (bo.get("tagItems") or ())  # tag offer: any item in the tag
                    if not accepts or bo["quantity"] <= 0:
                        continue
                    unit = bo["price"] * (1 + a.bonus) - so["price"]
                    if unit <= 0:
                        continue
                    afford_b = math.inf if B["balance"] == "infinite" else math.floor((B["balance"] or 0) / bo["price"])
                    afford_me = math.floor(a.cash / so["price"]) if so["price"] > 0 and a.cash != math.inf else math.inf
                    limits = {"A stock": so["quantity"], "B wants": bo["quantity"], "B money": afford_b, "your cash": afford_me}
                    total = min(limits.values())
                    if total <= 0:
                        continue
                    cap = per_trip_capacity(items.get(so["item"]), v)
                    if cap is None:
                        unknown.add(so["item"])
                    trip = min(total, cap) if cap else total
                    limits["vehicle"] = cap if cap is not None else math.inf
                    dist = wrap_dist(A["position"], B["position"], snap.get("worldSize", {"x": 2000, "z": 2000}), a.wrap)
                    minutes = dist * a.route_factor / v["speed"] / 60
                    deals.append({
                        "item": so["item"], "currency": A["currency"],
                        "from": clean(A["name"]), "fromId": A["id"], "fromPos": A["position"], "buyPrice": so["price"],
                        "to": clean(B["name"]), "toId": B["id"], "toPos": B["position"], "sellPrice": bo["price"],
                        "qtyTotal": total, "qtyPerTrip": trip, "trips": math.ceil(total / trip),
                        "profitPerTrip": round(trip * unit, 2), "profitTotal": round(total * unit, 2),
                        "cashPerTrip": round(trip * so["price"], 2),
                        "distance": round(dist), "minutesOneWay": round(minutes, 1),
                        "profitPerMinute": round(trip * unit / max(minutes, 0.5), 2),
                        "limitedBy": min(limits, key=limits.get), "catalogMissing": cap is None,
                        "viaTag": None if bo["item"] else bo.get("tag"),
                    })

    key = {"trip": "profitPerTrip", "minute": "profitPerMinute", "total": "profitTotal"}[a.sort]
    deals.sort(key=lambda d: -d[key])
    print(f"vehicle {a.vehicle}: {v['slots']} slots, {v['maxWeightKg']:g} kg, speed {v['speed']:g}  |  {len(deals)} deals, sorted by {key}\n")
    print(f"{'/trip':>7} {'/min':>6} {'total':>7} {'qty':>9} {'item':<20} {'buy':>5} {'sell':>5} {'min':>5}  {'limit':<9} from -> to")
    for d in deals[:a.top]:
        qty = f"{d['qtyPerTrip']}x{d['trips']}"
        print(f"{d['profitPerTrip']:>7} {d['profitPerMinute']:>6} {d['profitTotal']:>7} {qty:>9} {(d['item'].removesuffix('Item') + ('*' if d['viaTag'] else ''))[:20]:<20} "
              f"{d['buyPrice']:>5g} {d['sellPrice']:>5g} {d['minutesOneWay']:>5}  {d['limitedBy']:<9} {d['from'][:22]} -> {d['to'][:22]}"
              + ("  [no item data]" if d["catalogMissing"] else ""))
    if unknown:
        print(f"\nno weight/stack data (capacity not applied): {', '.join(sorted(unknown))}")
    json.dump(deals, open(os.path.join(a.data, "deals.json"), "w", encoding="utf-8"), indent=1)


if __name__ == "__main__":
    main()
