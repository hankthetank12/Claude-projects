"""Synthetic history, so the tool can be seen working with no account at all."""

from __future__ import annotations

import random
from datetime import date, timedelta

from .model import LineItem, Order

# name, unit price, usual quantity, days between purchases
_BASKET: tuple[tuple[str, float, float, int], ...] = (
    ("Organic Whole Milk, 59 FZ", 6.99, 1, 7),
    ("Organic Large Brown Eggs, 12 CT", 7.49, 1, 7),
    ("365 by Whole Foods Market Organic Rolled Oats, 32 OZ", 4.29, 1, 28),
    ("Organic Baby Spinach, 5 OZ", 4.49, 1, 7),
    ("PRODUCE Organic Sweet Onion", 2.99, 2.1, 14),
    ("Organic Garlic, 3 CT", 2.69, 1, 21),
    ("Organic Red Raspberries, 6 OZ", 4.99, 1, 7),
    ("Organic Hass Avocado", 2.49, 3, 7),
    ("Bell & Evans Organic Ground Chicken, 16 OZ", 8.49, 1, 14),
    ("Wild Caught Sockeye Salmon", 18.99, 0.8, 21),
    ("Kettle & Fire Organic Chicken Broth, 32 OZ", 5.29, 2, 21),
    ("Rummo Organic Spaghetti, 16 OZ", 4.49, 1, 14),
    ("Cento Foods Organic Tomato Paste, 4.56 OZ", 3.99, 1, 35),
    ("365 by Whole Foods Market Organic Cannellini Beans, 15.5 OZ", 1.69, 3, 21),
    ("Good Culture Organic Cottage Cheese, 16 OZ", 6.99, 1, 14),
    ("San Pellegrino Sparkling Mineral Water, 33.8 FZ", 3.19, 4, 10),
    ("Unique Snacks Extra Dark Pretzel Splits, 11 OZ", 4.39, 1, 13),
    ("Whole Foods Market Sourdough Loaf", 4.99, 1, 7),
    ("Mitica 24 Month Aged Parmigiano Reggiano", 26.99, 0.45, 35),
    ("Organic Green Cucumber", 1.99, 2, 10),
)

# Bought once and never again — the tool should not propose these.
_ONE_OFFS: tuple[tuple[str, float], ...] = (
    ("One Source Tree Free Birthday Card, 1 EA", 3.99),
    ("Whole Foods Market Birthday Crispy Rice Treat", 2.99),
    ("Numa Banana Cream Taffy, 3.3 OZ", 4.49),
)


def generate(days: int = 140, *, seed: int = 7, today: date | None = None) -> list[Order]:
    """A believable run of weekly shops ending today."""
    rng = random.Random(seed)
    end = today or date.today()
    start = end - timedelta(days=days)

    # Weekly-ish trips.
    trip_dates: list[date] = []
    cursor = start
    while cursor <= end:
        trip_dates.append(cursor)
        cursor += timedelta(days=rng.choice([6, 7, 7, 8, 10]))

    last_bought: dict[str, date] = {}
    orders: list[Order] = []

    for index, trip in enumerate(trip_dates):
        items: list[LineItem] = []
        for name, price, quantity, cadence in _BASKET:
            previous = last_bought.get(name)
            due = previous is None or (trip - previous).days >= cadence - rng.randint(0, 2)
            if not due:
                continue
            # Skip occasionally; real shopping is not that tidy.
            if previous is not None and rng.random() < 0.12:
                continue
            weighted = quantity != int(quantity)
            actual = round(quantity * rng.uniform(0.85, 1.15), 2) if weighted else quantity
            unit = "lb" if weighted else "each"
            items.append(
                LineItem.from_raw(
                    name,
                    quantity=actual,
                    unit=unit,
                    unit_price=price,
                    line_total=round(price * actual, 2),
                )
            )
            last_bought[name] = trip

        if index == 2:
            for name, price in _ONE_OFFS:
                items.append(
                    LineItem.from_raw(name, quantity=1, unit="each", unit_price=price, line_total=price)
                )

        items.append(
            LineItem.from_raw("CUSTOMER SERVICES Bag Fee", quantity=1, unit="each", unit_price=0.0, line_total=0.0)
        )

        if not items:
            continue

        subtotal = round(sum(item.line_total or 0 for item in items), 2)
        orders.append(
            Order(
                order_id=f"113-{1000000 + index * 7919:07d}-{2000000 + index * 3571:07d}",
                ordered_on=trip,
                items=items,
                store="Whole Foods Market - Sample Street",
                subtotal=subtotal,
                tax=round(subtotal * 0.01, 2),
                total=round(subtotal * 1.01, 2),
                channel="in-store",
                source="sample",
                stated_item_count=sum(
                    int(item.quantity) if item.unit == "each" else 1 for item in items
                ),
            )
        )

    return orders
