"""The normalized shape every input adapter produces.

Receipts, order exports and scraped pages all disagree about how they spell a
product. Everything downstream (cadence, budgets, the order sheet) works off
these types instead, so adding a new source means writing a parser that emits
`Order` objects and nothing else has to change.
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Iterable

# Receipt lines carry a department in caps before the product name, e.g.
# "PRODUCE Organic Rosemary, 0.75 OZ". Stripping it keeps that item from
# splitting in two when another receipt omits the prefix.
_DEPARTMENT_PREFIXES = (
    "PRODUCE",
    "MEAT",
    "SEAFOOD",
    "BAKERY",
    "DELI",
    "GROCERY",
    "DAIRY",
    "FROZEN",
    "WHOLE BODY",
    "CUSTOMER SERVICES",
    "SPECIALTY",
    "PREPARED FOODS",
    "FLORAL",
)

# Sizes ride along on the name (", 32 OZ"). They are worth keeping for display
# but must not be part of the identity key, or a repackaged size looks new.
_SIZE_UNITS = r"(?:OZ|FZ|LB|CT|EA|ML|L|G|KG|QT|PT|GAL|IN|PK|EACH)"
_SIZE_RE = re.compile(rf",\s*(?P<size>[\d.]+\s*{_SIZE_UNITS})\s*$", re.IGNORECASE)

# Not groceries: these ride on every receipt and must never be "due".
_NON_GROCERY = (
    "bag fee",
    "container deposit",
    "bottle deposit",
    "single container deposit",
    "carryout bag",
)

# Matched as word prefixes, so "raspberr" catches "raspberries" while short
# stems cannot bite: a bare "can" would otherwise claim "Cannellini".
_DEPARTMENT_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Produce",
        (
            "lettuce", "spinach", "kale", "carrot", "onion", "garlic", "cucumber",
            "asparagus", "celery", "tomato", "potato", "avocado", "banana",
            "apple", "berry", "berries", "raspberr", "blueberr", "strawberr",
            "lemon", "lime", "herb", "rosemary", "thyme", "basil", "cilantro",
            "parsley", "broccoli", "cauliflower", "squash", "mushroom", "ginger",
            "scallion", "shallot", "zucchini", "arugula", "grape", "melon",
            "pear", "peach", "orange", "salad",
        ),
    ),
    (
        "Meat & seafood",
        ("chicken", "beef", "pork", "turkey", "lamb", "salmon", "shrimp", "fish",
         "bacon", "sausage", "steak", "ground"),
    ),
    (
        "Dairy & eggs",
        ("milk", "cheese", "yogurt", "butter", "egg", "cream", "parmigiano",
         "chevre", "mozzarella", "feta", "ricotta", "kefir"),
    ),
    (
        "Bakery",
        ("bread", "bagel", "tortilla", "roll", "croissant", "muffin", "cake",
         "cookie", "brownie", "treat", "baguette"),
    ),
    ("Frozen", ("frozen", "popsicle")),
    (
        "Beverages",
        ("water", "juice", "coffee", "tea", "kombucha", "soda", "seltzer",
         "sparkling", "pellegrino", "cola", "lemonade"),
    ),
    (
        "Pantry",
        ("pasta", "rice", "bean", "lentil", "broth", "stock", "sauce", "oil",
         "vinegar", "flour", "sugar", "salt", "spice", "canned", "paste",
         "cereal", "oats", "honey", "syrup", "almond", "cashew", "peanut",
         "nuts", "quinoa", "noodle", "tuna", "chickpea"),
    ),
    (
        "Snacks",
        ("chip", "cracker", "candy", "taffy", "chocolate", "popcorn", "pretzel",
         "granola", "jerky"),
    ),
    (
        "Household",
        ("paper", "towel", "detergent", "soap", "cleaner", "wrap", "foil",
         "sponge", "napkin", "bag"),
    ),
)

# Checked before the keyword sweep, for names that legitimately contain words
# from two departments: chicken broth is pantry stock, not meat.
_DEPARTMENT_OVERRIDES: tuple[tuple[str, str], ...] = (
    (r"\b(?:broth|stock|bouillon|consomme)", "Pantry"),
    (r"\b(?:sauce|paste|salsa|pesto|hummus)", "Pantry"),
    (r"\bice cream|\bgelato|\bsorbet", "Frozen"),
    (r"\b(?:taffy|candy|gummy|licorice|chocolate|marshmallow)", "Snacks"),
)


def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def split_size(name: str) -> tuple[str, str | None]:
    """Split a trailing package size off a product name."""
    match = _SIZE_RE.search(name)
    if not match:
        return name.strip(), None
    return name[: match.start()].strip().rstrip(","), match.group("size").strip()


def strip_department(name: str) -> tuple[str, str | None]:
    """Remove a leading ALL-CAPS department prefix, returning it separately."""
    for prefix in _DEPARTMENT_PREFIXES:
        if name.upper().startswith(prefix + " "):
            return name[len(prefix) :].strip(), prefix.title()
    return name, None


def canonical_key(name: str) -> str:
    """A stable identity for a product across receipts.

    Case, accents, punctuation and package size all vary between receipts for
    what is plainly the same thing, so none of them survive into the key.
    """
    bare, _ = strip_department(name)
    bare, _ = split_size(bare)
    bare = _strip_accents(bare).lower()
    bare = re.sub(r"[^a-z0-9]+", " ", bare)
    return re.sub(r"\s+", " ", bare).strip()


def guess_department(name: str, hint: str | None = None) -> str:
    """Best-effort shopping department, so the list is ordered like the store.

    A receipt's own department prefix wins when it is meaningful; "Grocery" and
    "Customer Services" are too coarse to be worth keeping.
    """
    if hint and hint.lower() not in {"customer services", "grocery"}:
        return hint
    lowered = name.lower()
    for pattern, department in _DEPARTMENT_OVERRIDES:
        if re.search(pattern, lowered):
            return department
    for department, keywords in _DEPARTMENT_KEYWORDS:
        if any(re.search(r"\b" + re.escape(keyword), lowered) for keyword in keywords):
            return department
    # "Organic <something we do not recognise>" is overwhelmingly produce.
    if re.search(r"\borganic\b", lowered):
        return "Produce"
    return "Other"


def is_non_grocery(name: str) -> bool:
    """True for fees and deposits, which appear on receipts but are not items."""
    lowered = name.lower()
    return any(marker in lowered for marker in _NON_GROCERY)


@dataclass
class LineItem:
    """One line of one order."""

    raw_name: str
    name: str
    key: str
    department: str
    quantity: float = 1.0
    unit: str = "each"  # "each" or a weight unit such as "lb"
    unit_price: float | None = None
    line_total: float | None = None
    promotion: float = 0.0
    size: str | None = None
    # Set only by sources that record one (an account export does; a receipt
    # email does not). An exact id is the difference between adding the right
    # product and guessing from a name.
    product_id: str | None = None

    @classmethod
    def from_raw(
        cls,
        raw_name: str,
        *,
        quantity: float = 1.0,
        unit: str = "each",
        unit_price: float | None = None,
        line_total: float | None = None,
        promotion: float = 0.0,
        product_id: str | None = None,
    ) -> "LineItem":
        without_department, department_hint = strip_department(raw_name)
        name, size = split_size(without_department)
        return cls(
            raw_name=raw_name,
            name=name or raw_name,
            key=canonical_key(raw_name),
            department=guess_department(name, department_hint),
            quantity=quantity,
            unit=unit,
            unit_price=unit_price,
            line_total=line_total,
            promotion=promotion,
            size=size,
            product_id=product_id,
        )

    @property
    def is_non_grocery(self) -> bool:
        return is_non_grocery(self.raw_name)

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_name": self.raw_name,
            "name": self.name,
            "key": self.key,
            "department": self.department,
            "quantity": self.quantity,
            "unit": self.unit,
            "unit_price": self.unit_price,
            "line_total": self.line_total,
            "promotion": self.promotion,
            "size": self.size,
            "product_id": self.product_id,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "LineItem":
        return cls(
            raw_name=payload["raw_name"],
            name=payload.get("name") or payload["raw_name"],
            key=payload.get("key") or canonical_key(payload["raw_name"]),
            department=payload.get("department") or "Other",
            quantity=float(payload.get("quantity", 1.0)),
            unit=payload.get("unit", "each"),
            unit_price=payload.get("unit_price"),
            line_total=payload.get("line_total"),
            promotion=float(payload.get("promotion", 0.0)),
            size=payload.get("size"),
            product_id=payload.get("product_id"),
        )


@dataclass
class Order:
    """One shopping trip or delivery."""

    order_id: str
    ordered_on: date
    items: list[LineItem] = field(default_factory=list)
    store: str | None = None
    subtotal: float | None = None
    tax: float | None = None
    total: float | None = None
    savings: float | None = None
    channel: str = "unknown"  # in-store, delivery, pickup
    source: str | None = None  # where the record came from, for debugging
    # Receipt emails list at most 20 lines even when more was bought, so a
    # missing tail is a fact about the source that the maths must know.
    stated_item_count: int | None = None

    @property
    def units_listed(self) -> int:
        """Units across the listed lines.

        Receipts report "Items Purchased" as a count of units, not lines, and
        weigh-out items (0.45 lb of cheese) count as a single unit.
        """
        total = 0
        for item in self.items:
            total += int(math.ceil(item.quantity)) if item.unit == "each" else 1
        return total

    @property
    def truncated(self) -> bool:
        """True when the source listed fewer units than the order contained."""
        if self.stated_item_count is None:
            return False
        return self.units_listed < self.stated_item_count

    @property
    def grocery_items(self) -> list[LineItem]:
        return [item for item in self.items if not item.is_non_grocery]

    def to_dict(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "ordered_on": self.ordered_on.isoformat(),
            "store": self.store,
            "subtotal": self.subtotal,
            "tax": self.tax,
            "total": self.total,
            "savings": self.savings,
            "channel": self.channel,
            "source": self.source,
            "stated_item_count": self.stated_item_count,
            "items": [item.to_dict() for item in self.items],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Order":
        return cls(
            order_id=payload["order_id"],
            ordered_on=date.fromisoformat(payload["ordered_on"]),
            items=[LineItem.from_dict(raw) for raw in payload.get("items", [])],
            store=payload.get("store"),
            subtotal=payload.get("subtotal"),
            tax=payload.get("tax"),
            total=payload.get("total"),
            savings=payload.get("savings"),
            channel=payload.get("channel", "unknown"),
            source=payload.get("source"),
            stated_item_count=payload.get("stated_item_count"),
        )


def merge_duplicate_lines(items: Iterable[LineItem]) -> list[LineItem]:
    """Collapse repeated lines for the same product within a single order."""
    merged: dict[str, LineItem] = {}
    for item in items:
        existing = merged.get(item.key)
        if existing is None:
            merged[item.key] = item
            continue
        existing.quantity += item.quantity
        if existing.line_total is not None and item.line_total is not None:
            existing.line_total += item.line_total
        existing.promotion += item.promotion
        existing.product_id = existing.product_id or item.product_id
    return list(merged.values())
