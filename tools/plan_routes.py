"""Plan multi-stop trade runs: at every stop sell what you carry, buy a (mixed) load for the next stop.

  python tools/plan_routes.py --vehicle PoweredCart [--legs 4] [--cash 1000] [--start "Shop name" | --start 640,1640]

Search: beam search over shop sequences. A leg X -> Y fills the vehicle greedily with everything X sells that Y buys
(best profit per unit of the scarcer resource -- slots or weight -- first), bounded by X's stock, Y's demand, Y's
money, your cash and the vehicle. Stock/demand/money used by earlier legs are subtracted, and sales add to your cash.

Side deals: after a run is chosen, leftover space on each leg is filled with goods bought at one stop and sold at a
later, non-adjacent stop ("carry-through"), so a detour only adds cargo when space is free.

Score: profit per minute of the whole run (travel + --stop-minutes per stop, + reaching the first shop when --start).
Writes data/plans.json for the map page.
"""
import argparse
import json
import math
import os
import re

from pricing import best_price, line_cost

clean = lambda s: re.sub(r"<[^>]+>", "", s or "").strip()


def wrap_dist(a, b, wrap=False, W=2000):
    dx = abs(a["x"] - b["x"]); dz = abs(a["z"] - b["z"])
    if wrap:  # only for water vehicles: FactorEco's island is ringed by ocean
        dx, dz = min(dx, W - dx), min(dz, W - dz)
    return math.hypot(dx, dz)


class Market:
    def __init__(self, shops, items, vehicle, a):
        self.shops = {s["id"]: s for s in shops}
        self.items, self.v, self.a = items, vehicle, a
        # pair -> [(item, sellOffer at X, buyOffer at Y, unit profit)]
        self.pairs = {}
        sells = {s["id"]: {} for s in shops}
        for s in shops:
            for o in s["sells"]:
                if o["item"] and o["quantity"] > 0 and o["price"] >= 0:
                    sells[s["id"]].setdefault(o["item"], o)
        for X in shops:
            for Y in shops:
                if X is Y or X["currency"] != Y["currency"]:
                    continue
                m = []
                for bo in Y["buys"]:
                    if bo["quantity"] <= 0:
                        continue
                    # A tag offer ("any Wood") takes every item in its tag; they all draw on the offer's one limit.
                    for name in [bo["item"]] if bo["item"] else bo.get("tagItems") or []:
                        so = sells[X["id"]].get(name)
                        if so:
                            # Ranked by the margin at the list price, or at the best discount for a deal that only pays
                            # with one; fill() prices each lot by its real quantity and drops it if the tier isn't reached.
                            unit = bo["price"] * (1 + a.bonus) - so["price"]
                            best = bo["price"] * (1 + a.bonus) - best_price(so)
                            if best > 0:
                                m.append((name, so, bo, unit if unit > 0 else best))
                if m:
                    self.pairs[(X["id"], Y["id"])] = m
        self.out = {}
        for (x, y) in self.pairs:
            self.out.setdefault(x, []).append(y)

    def minutes(self, a_pos, b_pos):
        return wrap_dist(a_pos, b_pos, self.a.wrap) * self.a.route_factor / self.v["speed"] / 60

    def item(self, name):
        return self.items.get(name) or {"weightKg": 0.0, "stackSize": 100, "carried": False, "unknown": True}

    def fill(self, X, Y, st, slots_left, weight_left, cash, extra=()):
        """Greedy load for X -> Y. `st` = consumption state. Returns (load lines, slots, weight, cost, revenue)."""
        cands = list(self.pairs.get((X, Y), [])) + list(extra)
        def density(c):
            it = self.item(c[0])
            per_unit = max(1 / it["stackSize"] / self.v["slots"], it["weightKg"] / self.v["maxWeightKg"])
            return c[3] / per_unit
        cands.sort(key=density, reverse=True)
        Yshop = self.shops[Y]
        y_money = math.inf if Yshop["balance"] == "infinite" else (Yshop["balance"] or 0) - st["money"].get(Y, 0)
        load, used_slots, used_w, cost, revenue = [], 0, 0.0, 0.0, 0.0
        partial = {}  # item -> units already in a partially filled stack
        taken = {}    # buy offer -> units this load already sells to it (tag offers take several items)
        used = {}     # item -> units of the seller's stock this load already takes (two offers can want one item)
        for name, so, bo, unit in cands:
            it = self.item(name)
            key = offer_key(Y, bo)
            avail = so["quantity"] - st["sold"].get((X, name), 0) - used.get(name, 0)
            want = bo["quantity"] - st["bought"].get(key, 0) - taken.get(key, 0)
            if bo.get("noCap", bo["quantity"] == 999 and not bo["limit"]):  # older shops.json files have no noCap
                want = math.inf
            q = min(avail, want)
            if q <= 0:
                continue
            room_slots = (slots_left - used_slots) * it["stackSize"] + partial.get(name, 0)
            room_w = math.floor((weight_left - used_w) / it["weightKg"]) if it["weightKg"] > 0 else math.inf
            afford = math.floor((cash - cost) / so["price"]) if so["price"] > 0 else math.inf
            payable = math.floor((y_money - revenue) / bo["price"]) if bo["price"] > 0 else math.inf
            q = int(min(q, room_slots, room_w, afford, payable))
            if q <= 0:
                continue
            lot_cost, lot_revenue = line_cost(so, q), q * bo["price"] * (1 + self.a.bonus)
            if lot_revenue - lot_cost <= 1e-9:
                continue  # only pays at a discount this quantity doesn't reach
            new_total = q - partial.get(name, 0)
            used_slots += max(0, math.ceil(new_total / it["stackSize"]))
            partial[name] = (-new_total) % it["stackSize"]
            used_w += q * it["weightKg"]
            cost += lot_cost
            revenue += lot_revenue
            taken[key] = taken.get(key, 0) + q
            used[name] = used.get(name, 0) + q
            load.append({"item": name, "qty": q, "buy": round(lot_cost / q, 4), "list": so["price"], "sell": bo["price"], "profit": round(lot_revenue - lot_cost, 2),
                         "offer": key, "viaTag": None if bo["item"] else bo.get("tag"), "unknownItem": bool(it.get("unknown"))})
        return load, used_slots, used_w, cost, revenue


def offer_key(shop_id, bo):
    """Identity of a buy offer, so all items sold to one tag offer share its limit."""
    return bo.get("key") or f"{shop_id}/{bo['item'] or 'tag:' + str(bo.get('tag'))}"


def apply(st, X, Y, load, revenue):
    st = {"sold": dict(st["sold"]), "bought": dict(st["bought"]), "money": dict(st["money"])}
    for l in load:
        st["sold"][(X, l["item"])] = st["sold"].get((X, l["item"]), 0) + l["qty"]
        st["bought"][l["offer"]] = st["bought"].get(l["offer"], 0) + l["qty"]
    st["money"][Y] = st["money"].get(Y, 0) + revenue
    return st


def plan(m, a, start_pos, start_shop):
    v = m.v
    seeds = [start_shop] if start_shop else list(m.out)
    beam = []
    for s in seeds:
        lead = m.minutes(start_pos, m.shops[s]["position"]) if start_pos else 0.0
        beam.append({"path": [s], "legs": [], "profit": 0.0, "minutes": lead + a.stop_minutes, "cash": a.cash,
                     "st": {"sold": {}, "bought": {}, "money": {}}})
    results = []
    for depth in range(a.legs):
        nxt = []
        for b in beam:
            X = b["path"][-1]
            for Y in m.out.get(X, []):
                if len(b["path"]) >= 2 and Y == b["path"][-2] and not a.allow_backtrack:
                    pass  # ping-pong is allowed: A->B->A is often the best use of a return trip
                load, slots, w, cost, rev = m.fill(X, Y, b["st"], v["slots"], v["maxWeightKg"], b["cash"])
                if not load:
                    continue
                profit = rev - cost
                mins = m.minutes(m.shops[X]["position"], m.shops[Y]["position"]) + a.stop_minutes
                nb = {"path": b["path"] + [Y],
                      "legs": b["legs"] + [{"from": X, "to": Y, "load": load, "slots": slots, "weightKg": round(w, 1),
                                            "cost": round(cost, 2), "revenue": round(rev, 2), "minutes": round(mins, 2)}],
                      "profit": b["profit"] + profit, "minutes": b["minutes"] + mins,
                      "cash": b["cash"] - cost + rev, "st": apply(b["st"], X, Y, load, rev)}
                nxt.append(nb)
        # Keep the best per (last shop, path length) bucket, then the top of the beam by rate.
        nxt.sort(key=lambda n: -(n["profit"] / n["minutes"]))
        seen, beam = {}, []
        for n in nxt:
            k = (n["path"][-1], tuple(sorted(set(n["path"]))))
            if k in seen:
                continue
            seen[k] = 1
            beam.append(n)
            if len(beam) >= a.beam:
                break
        results += beam
        if not beam:
            break
    return results


def add_side_deals(m, run, a):
    """Carry-through: buy at stop i, sell at stop j > i+1, using space free on every leg in between."""
    path = run["path"]
    legs = run["legs"] = [dict(leg) for leg in run["legs"]]  # runs share leg dicts with their beam ancestors; don't leak slots into them
    st = run["st"]
    cash_at = []  # cash available when leaving stop i
    c = a.cash
    for leg in legs:
        c -= leg["cost"]; cash_at.append(c); c += leg["revenue"]
    extra_profit, side = 0.0, []
    for i in range(len(path)):
        for j in range(i + 2, len(path)):
            X, Y = path[i], path[j]
            free_slots = min(m.v["slots"] - legs[k]["slots"] for k in range(i, j))
            free_w = min(m.v["maxWeightKg"] - legs[k]["weightKg"] for k in range(i, j))
            if free_slots <= 0 or free_w <= 0:
                continue
            load, slots, w, cost, rev = m.fill(X, Y, st, free_slots, free_w, min(cash_at[i:j]))
            if not load:
                continue
            for k in range(i, j):
                legs[k]["slots"] += slots; legs[k]["weightKg"] = round(legs[k]["weightKg"] + w, 1)
            for k in range(i, j):
                cash_at[k] -= cost
            st = apply(st, X, Y, load, rev)
            side.append({"from": X, "to": Y, "fromStop": i, "toStop": j, "load": load,
                         "cost": round(cost, 2), "revenue": round(rev, 2)})
            extra_profit += rev - cost
    run["side"] = side
    run["profit"] += extra_profit
    return run


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--vehicle", default="PoweredCart")
    ap.add_argument("--slots", type=int); ap.add_argument("--max-weight", type=float); ap.add_argument("--speed", type=float)
    ap.add_argument("--cash", type=float, default=1e12, help="money you can spend up front (default: unlimited)")
    ap.add_argument("--currency", default="Crowns")
    ap.add_argument("--start", help="shop name (substring) or x,z coordinates of where you are")
    ap.add_argument("--legs", type=int, default=4, help="max legs per run")
    ap.add_argument("--min-legs", type=int, default=1)
    ap.add_argument("--beam", type=int, default=300)
    ap.add_argument("--stop-minutes", type=float, default=1.0, help="time spent trading at each stop")
    ap.add_argument("--wrap", action="store_true", help="allow crossing the world edge (water vehicles)")
    ap.add_argument("--route-factor", type=float, default=1.3)
    ap.add_argument("--bonus", type=float, default=0.0)
    ap.add_argument("--allow-backtrack", action="store_true", default=True)
    ap.add_argument("--top", type=int, default=15)
    a = ap.parse_args()

    load = lambda n: json.load(open(os.path.join(a.data, n), encoding="utf-8"))
    snap, items, vehicles = load("shops.json"), load("items.json"), load("vehicles.json")
    v = dict(vehicles.get(a.vehicle) or {})
    for k, val in (("slots", a.slots), ("maxWeightKg", a.max_weight), ("speed", a.speed)):
        if val is not None:
            v[k] = val
    if not v.get("slots") or not v.get("maxWeightKg") or not v.get("speed"):
        raise SystemExit(f"vehicle '{a.vehicle}' needs slots/maxWeightKg/speed (edit data/vehicles.json or pass flags)")
    shops = [s for s in snap["shops"] if s["on"] and s["enabled"] and s["currency"] == a.currency]
    m = Market(shops, items, v, a)

    start_pos = start_shop = None
    if a.start:
        if re.fullmatch(r"\s*-?\d+(\.\d+)?\s*,\s*-?\d+(\.\d+)?\s*", a.start):
            x, z = (float(t) for t in a.start.split(","))
            start_pos = {"x": x, "z": z}
        else:
            hits = [s for s in shops if a.start.lower() in clean(s["name"]).lower()]
            if not hits:
                raise SystemExit(f"no open {a.currency} shop matches '{a.start}'")
            start_shop = hits[0]["id"]

    runs = [r for r in plan(m, a, start_pos, start_shop) if len(r["legs"]) >= a.min_legs]
    runs.sort(key=lambda r: -(r["profit"] / r["minutes"]))
    picked, seen = [], set()
    for r in runs:
        key = tuple(r["path"])
        if key in seen:
            continue
        seen.add(key)
        picked.append(add_side_deals(m, r, a))
        if len(picked) >= a.top:
            break
    picked.sort(key=lambda r: -(r["profit"] / r["minutes"]))

    name = lambda sid: clean(m.shops[sid]["name"])
    print(f"{len(m.shops)} open {a.currency} shops, {len(m.pairs)} profitable shop pairs; vehicle {a.vehicle} "
          f"({v['slots']} slots, {v['maxWeightKg']:g} kg, speed {v['speed']:g})\n")
    for n, r in enumerate(picked, 1):
        print(f"#{n}  {r['profit']:.1f} profit in {r['minutes']:.1f} min = {r['profit'] / r['minutes']:.1f}/min   "
              + " -> ".join(name(s) for s in r["path"]))
        for leg in r["legs"]:
            goods = ", ".join(f"{l['qty']} {l['item'].removesuffix('Item')}" + (f" (as {l['viaTag']})" if l.get("viaTag") else "") for l in leg["load"])
            print(f"     {name(leg['from'])[:24]:>24} -> {name(leg['to'])[:24]:<24} +{leg['revenue'] - leg['cost']:.1f}  "
                  f"[{leg['slots']}/{v['slots']} slots, {leg['weightKg']:g} kg]  {goods}")
        for sd in r["side"]:
            goods = ", ".join(f"{l['qty']} {l['item'].removesuffix('Item')}" for l in sd["load"])
            print(f"     side deal: stop {sd['fromStop'] + 1} -> stop {sd['toStop'] + 1}  +{sd['revenue'] - sd['cost']:.1f}  {goods}")
        print()

    out = {"vehicle": {"name": a.vehicle, **v}, "currency": a.currency, "settings": vars(a),
           "runs": [{k: r[k] for k in ("path", "legs", "side", "profit", "minutes")} for r in picked]}
    json.dump(out, open(os.path.join(a.data, "plans.json"), "w", encoding="utf-8"), indent=1, default=str)


if __name__ == "__main__":
    main()
