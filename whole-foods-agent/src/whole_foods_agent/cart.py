"""How a proposed order reaches a real shopping cart.

This is deliberately a seam. Deciding *what* to buy is the hard part and lives
in `basket`; getting those items into a cart is a swappable back end, because
the way to do it depends on what access you have and what you are willing to
maintain.

Implemented:

* `DeepLinkCart` — emits one Whole Foods search link per item. Nothing to
  authenticate, nothing to break; tapping a link on a phone opens the Amazon
  app at that product so it is one tap to add.

* `BrowserCart` (in `browser_cart`) — drives a signed-in browser to add items
  directly. Amazon publishes no customer API for grocery history or the cart,
  so this automates the website, which breaches their Conditions of Use and
  puts the account at risk. It is dry-run by default, never handles a password,
  refuses ambiguous product matches and stops at the cart. Read that module
  before using it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from .basket import OrderLine
from .render import item_url


@dataclass
class CartEntry:
    """One proposed item, resolved to something actionable."""

    name: str
    quantity: float
    unit: str
    url: str | None = None
    added: bool = False
    detail: str | None = None
    product_id: str | None = None


class CartAdapter(Protocol):
    """Anything that can take proposed lines towards a cart."""

    def submit(self, lines: Sequence[OrderLine]) -> list[CartEntry]:
        ...


class DeepLinkCart:
    """Resolve each line to a Whole Foods search link.

    Adds nothing by itself — the person taps through — which is exactly why it
    needs no credentials and cannot put a wrong item in a real basket.
    """

    def submit(self, lines: Sequence[OrderLine]) -> list[CartEntry]:
        entries = []
        for line in lines:
            product_id = line.stats.product_id
            entries.append(
                CartEntry(
                    name=line.name,
                    quantity=line.quantity,
                    unit=line.stats.unit,
                    url=item_url(line.name, product_id),
                    added=False,
                    product_id=product_id,
                    detail=(
                        "exact product link"
                        if product_id
                        else "search link; pick the right one in the app"
                    ),
                )
            )
        return entries


class CartUnavailable(RuntimeError):
    """Raised when a back end cannot be used in this environment."""


def get_adapter(name: str, **kwargs) -> CartAdapter:
    """Look up a cart back end by name.

    The browser back end is imported lazily: it depends on Playwright, which
    most installs will not have, and nothing else here should require it.
    """
    if name == "links":
        return DeepLinkCart()
    if name == "browser":
        from .browser_cart import BrowserCart

        return BrowserCart(**kwargs)
    raise CartUnavailable(f"unknown cart back end {name!r}; try ['browser', 'links']")
