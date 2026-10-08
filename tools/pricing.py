"""Store pricing shared by the CLI tools: Eco 0.14.2 quantity discounts on sell offers (TradePricingUtils).

The best tier one trade's quantity reaches takes its percent off the whole line; a price of 0 or less never discounts.
Offers without tiers (older servers, save-based data) cost price x quantity.
"""


def discount_for(so, q):
    if so["price"] <= 0:
        return 0.0
    return max([0.0] + [t["DiscountPercent"] for t in so.get("discountTiers") or () if q >= t["MinQuantity"]])


def line_cost(so, q):
    return q * so["price"] * (1 - discount_for(so, q) / 100)


def best_price(so):
    """The lowest unit price any quantity can reach."""
    if so["price"] <= 0:
        return so["price"]
    return so["price"] * (1 - max([0.0] + [t["DiscountPercent"] for t in so.get("discountTiers") or ()]) / 100)


def clean_tiers(tiers):
    """Tiers as the server applies them: MinQuantity of at least 1, percent clamped to 0-100, sorted by MinQuantity."""
    out = [{"MinQuantity": int(t.get("MinQuantity") or 0), "DiscountPercent": min(100.0, max(0.0, float(t.get("DiscountPercent") or 0)))}
           for t in tiers or () if isinstance(t, dict)]
    return sorted((t for t in out if t["MinQuantity"] > 0), key=lambda t: t["MinQuantity"])
