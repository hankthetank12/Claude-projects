from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Lot:
    """One watch lot, normalized across platforms."""

    source: str  # platform the lot was found on, e.g. "liveauctioneers"
    source_id: str
    title: str
    url: str
    house: str
    city: str = ""
    state: str = ""
    image: str = ""
    lot_number: str = ""
    sale_title: str = ""
    sale_type: str = ""  # "live" or "timed"
    starts_at: int = 0  # unix seconds; 0 if unknown
    ends_at: int = 0
    currency: str = "USD"
    estimate_low: float = 0
    estimate_high: float = 0
    current_bid: float = 0
    bid_count: int = 0
    brand: str = ""
    also_on: list[dict] = field(default_factory=list)  # same lot cross-listed elsewhere

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Lot":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
