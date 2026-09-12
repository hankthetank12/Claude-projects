"""How a proposed order reaches a real shopping cart.

This is deliberately a seam. Deciding *what* to buy is the hard part and lives
in `basket`; getting those items into a cart is a swappable back end, because
the way to do it depends on what access you have and what you are willing to
maintain.

Implemented:

* `DeepLinkCart` — emits one Whole Foods search link per item. Nothing to
  authenticate, nothing to break; tapping a link on a phone opens the Amazon
  app at that product so it is one tap to add.

Not implemented, and why:

* `BrowserCart` — driving a signed-in browser session to add items directly.
  Amazon publishes no customer API for grocery order history or the cart, so
  this would mean automating the site with real account credentials. That
  breaches Amazon's Conditions of Use, risks the account it runs as, and needs
  live credentials plus interactive 2FA to build or test at all. The class
  below documents the contract it would have to satisfy rather than shipping a
  version that cannot be verified.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from .basket import OrderLine
from .render import search_url


@dataclass
class CartEntry:
    """One proposed item, resolved to something actionable."""

    name: str
    quantity: float
    unit: str
    url: str | None = None
    added: bool = False
    detail: str | None = None


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
        return [
            CartEntry(
                name=line.name,
                quantity=line.quantity,
                unit=line.stats.unit,
                url=search_url(line.name),
                added=False,
                detail="search link; add from the app",
            )
            for line in lines
        ]


class CartUnavailable(RuntimeError):
    """Raised when a back end cannot be used in this environment."""


class BrowserCart:
    """Contract for a future signed-in browser back end.

    A working implementation would need to, at minimum:

    1. Reuse a persistent browser profile so a human logs in once, interactively,
       and later runs ride on that session. Storing an account password in
       config, or defeating a login challenge, is out of scope by design.
    2. Hand every CAPTCHA, one-time code and re-authentication prompt back to a
       human rather than attempting to satisfy it automatically.
    3. Resolve each proposed line to a specific product and refuse ambiguous
       matches instead of guessing, since a wrong match becomes a real purchase.
    4. Stop at the cart. Never advance to checkout, delivery slot or payment.
    5. Be rate limited to human pace, and abort the whole run on the first
       unexpected page rather than clicking blindly onward.

    Point 3 is the one that makes this genuinely risky: "Organic Sweet Onion"
    matches dozens of listings, and history records the name only, never the
    product identifier that would make the match exact.
    """

    def __init__(self, *, profile_dir: str | None = None) -> None:
        self.profile_dir = profile_dir

    def submit(self, lines: Sequence[OrderLine]) -> list[CartEntry]:
        raise CartUnavailable(
            "The signed-in browser back end is not implemented. It needs real "
            "account credentials and an interactive login to build or verify, "
            "and it breaches Amazon's Conditions of Use. Use DeepLinkCart, or "
            "see this class's docstring for the contract an implementation "
            "would have to meet."
        )


def get_adapter(name: str) -> CartAdapter:
    """Look up a cart back end by name."""
    adapters: dict[str, CartAdapter] = {
        "links": DeepLinkCart(),
        "browser": BrowserCart(),
    }
    if name not in adapters:
        raise CartUnavailable(f"unknown cart back end {name!r}; try {sorted(adapters)}")
    return adapters[name]
