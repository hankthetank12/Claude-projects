"""Score how interesting a watch lot is to a collector, and reject the junk.

Every score comes with its reasons, so a ranking you disagree with is easy to
trace. Rejected lots never reach the page; everything else is ranked by score.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from watch_auctions.models import Lot

BRAND_POINTS = {
    # Top-tier makers: always worth a look, whatever the condition.
    "Patek Philippe": 45, "Audemars Piguet": 45, "Vacheron Constantin": 45, "A. Lange & Sohne": 45,
    "F.P. Journe": 45, "Richard Mille": 45, "Breguet": 40, "Rolex": 40, "H. Moser": 38,
    "Blancpain": 35, "Jaeger-LeCoultre": 35,
    # Serious collector brands.
    "Cartier": 30, "Omega": 30, "Tudor": 28, "IWC": 28, "Panerai": 28, "Grand Seiko": 28,
    "Zenith": 26, "TAG Heuer": 24, "Universal Geneve": 26, "Breitling": 24, "Piaget": 26,
    "Chopard": 22, "Ulysse Nardin": 22, "Girard-Perregaux": 22, "Glashutte Original": 26, "Nomos": 20,
    "Sinn": 18, "Doxa": 18, "Hublot": 20, "Bell & Ross": 16, "Franck Muller": 18, "Muhle Glashutte": 16,
    # Solid, collectible, often underpriced at small sales.
    "Longines": 18, "Hamilton": 14, "Heuer": 24, "Lemania": 16, "Gallet": 16, "Eterna": 12,
    "Seiko": 10, "Oris": 12, "Tissot": 10, "Hermes": 14, "Bvlgari": 16, "Jules Jurgensen": 12,
    "Movado": 10, "Gruen": 8, "Elgin": 8, "Waltham": 10, "Illinois Watch": 12, "Hampden": 8,
    "South Bend": 8, "Ball": 12, "Tiffany": 14, "Baume & Mercier": 10, "Ebel": 10, "Corum": 12,
    "Enicar": 10, "Vulcain": 12, "Wittnauer": 6, "Benrus": 6, "Bulova": 6, "Mido": 8,
    "Glycine": 10, "Favre-Leuba": 10, "Junghans": 8, "Citizen": 4, "Raymond Weil": 6,
    "Frederique Constant": 8, "Montblanc": 12, "Concord": 8, "Tourneau": 6, "Rado": 6,
    "Chanel": 20, "Nivada": 12, "Accutron": 12, "Doxa": 18, "Croton": 0,
}

# Mall, fashion and gadget watches: never what a collector is hunting for.
JUNK_BRANDS = re.compile(
    r"\b(fossil|armitron|guess|michael kors|mk\d{4}|invicta|geneva|stauer|anne klein|relic|skagen|nixon|"
    r"casio|g-?shock|timex|disney|acqua|marc jacobs|kenneth cole|steve madden|vera wang|nine west|"
    r"caravelle|lucky brand|tommy hilfiger|diesel|dkny|coach|swatch|xoxo|betsey johnson|juicy|"
    r"apple watch|fitbit|garmin|samsung galaxy watch|smart ?watch|i-?touch|sportquest|peugeot|"
    r"croton|akribos|august steiner|joshua & sons|vivani|bertha|sekonda|ingersoll|"
    r"mickey mouse|timeworks|speidel|carriage|advance|westclox|wrangler|u\.?s\.? polo|"
    r"chaps|nautica|bulova precisionist|citizen eco-?drive|eco-?drive|folio|pedre|gitano)\b")
# Never a watch worth having, whatever the brand.
NOT_A_REAL_WATCH = re.compile(
    r"\b((for )?parts|repair|not working|non[- ]?working|as[- ]is|needs (battery|work|repair)|"
    r"replica|homage|fake|inspired|style watch|costume|kids|children'?s|child|toy|novelty|"
    r"display only|dummy|movement only|case only|dial only|band only|empty|"
    r"panini|trading cards?|football|baseball|topps)\b")
# Several watches in one lot: only worth showing if the brand alone justifies it ("two Rolexes").
MULTI_LOTS = re.compile(
    r"\b(lot of|assorted|assortment|mixed|grab ?bag|bundle|bulk|collection of \d+|untested|"
    r"\(\d+\)\s*(?:\w+\s+){0,3}watch|\d+ (?:\w+ ){0,2}watches|watches \(\d+\)|"
    r"watch lot|\d+ ?pcs?|pieces)\b")

SOLID_PRECIOUS = re.compile(r"\b(18 ?k(t|arat)?|14 ?k(t|arat)?|10 ?k(t|arat)?|9 ?k(t|arat)?|"
                            r"750|585|platinum|pt ?950|solid gold)\b")
NOT_SOLID = re.compile(r"\b(gold[- ]?filled|g\.?f\.?|gold[- ]?plated|plated|gold[- ]?tone|rolled gold|"
                       r"electroplat\w*|vermeil|10k rgp|rgp|r\.g\.p)\b")
MECHANICAL = re.compile(r"\b(automatic|self[- ]?winding|manual[- ]?wind|hand[- ]?wind|wind[- ]?up|"
                        r"mechanical|chronograph|chronometer|\d{2} ?j(ewels?)?|key[- ]?w(ind|ound)|stem[- ]?w(ind|ound)|"
                        r"railroad|calibre|caliber|cal\.)\b")
QUARTZ = re.compile(r"\bquartz\b")
VINTAGE = re.compile(r"\b(vintage|antique|19[0-7]\d'?s?|circa|c\.\s?19\d\d|art deco|victorian|edwardian|"
                     r"pre[- ]?owned|estate)\b")
# A model/reference number, but not a year ("2020 Panini…", "1940 Rolex").
REFERENCE = re.compile(r"\b(ref\.?|reference|model)\s*#?\s*[a-z]{0,3}\d{3,6}|\b(?!(?:19|20)\d\d\b)\d{4,6}[a-z]{0,4}\b|\b\d{2,4}[./-]\d{3,4}\b")
# Diamonds added to a Rolex after it left the factory knock the value down for collectors.
AFTERMARKET = re.compile(r"\b(\d?\.\d+ ?ct|diamond bezel|diam\b|iced|custom diamond|aftermarket)")
COMPLETE = re.compile(r"\b(box (and|&) papers?|box & pap\w*|full set|with papers|original box|"
                      r"certificate|warranty card|serviced)\b")
COMPLICATION = re.compile(r"\b(moon ?phase|perpetual calendar|minute repeater|repeater|tourbillon|"
                          r"gmt|world ?time|triple calendar|split[- ]seconds|rattrapante|alarm|"
                          r"chronograph)\b")

# Without one of these, an unbranded lot has nothing going for it.
MIN_SCORE = 25


@dataclass
class Verdict:
    score: int
    reasons: list[str] = field(default_factory=list)
    rejected: str = ""  # why it's garbage; empty if it's kept


def _money_points(lot: Lot) -> tuple[int, str]:
    est = lot.estimate_high or lot.estimate_low or 0
    # Some houses enter placeholder ranges like "$10 - $100,000"; those say nothing.
    if lot.estimate_low and lot.estimate_high > 5 * lot.estimate_low:
        est = 0
    value = max(est, lot.current_bid or 0)
    if value < 50:
        return 0, ""
    # $100 -> ~4, $1k -> ~12, $10k -> ~20, capped at 25.
    pts = min(25, round(4 + 8 * math.log10(value / 100))) if value >= 100 else 2
    return pts, f"${value:,.0f} {'estimate' if est >= (lot.current_bid or 0) else 'bid'}"


def score(lot: Lot) -> Verdict:
    t = lot.title.lower()
    if m := JUNK_BRANDS.search(t):
        # A fashion brand inside a real maker's title ("Rolex with Fossil box") isn't the watch.
        if not (lot.brand and BRAND_POINTS.get(lot.brand, 0) >= 24 and m.start() > t.find(lot.brand.lower().split()[0])):
            return Verdict(0, rejected=f"fashion/gadget brand: {m.group(0)}")
    if m := NOT_A_REAL_WATCH.search(t):
        return Verdict(0, rejected=f"not a real, working watch: {m.group(0)}")
    if (m := MULTI_LOTS.search(t)) and BRAND_POINTS.get(lot.brand, 0) < 35:
        return Verdict(0, rejected=f"bulk lot: {m.group(0)}")

    pts, why = 0, []
    if lot.brand and (b := BRAND_POINTS.get(lot.brand, 0)):
        pts += b
        why.append(lot.brand)
    solid = SOLID_PRECIOUS.search(t)
    if solid and not NOT_SOLID.search(t):
        pts += 18
        why.append(f"solid {solid.group(0).replace(' ', '').upper()}")
    elif NOT_SOLID.search(t):
        pts -= 3
    if MECHANICAL.search(t):
        pts += 8
        why.append("mechanical")
    elif QUARTZ.search(t):
        pts -= 4
    if m := COMPLICATION.search(t):
        pts += 6
        why.append(m.group(0))
    if VINTAGE.search(t):
        pts += 5
        why.append("vintage")
    if REFERENCE.search(t):
        pts += 4
        why.append("reference no.")
    if AFTERMARKET.search(t):
        pts -= 8
        why.append("added diamonds")
    if COMPLETE.search(t):
        pts += 6
        why.append("box/papers")
    money, money_why = _money_points(lot)
    if money:
        pts += money
        why.append(money_why)
    if lot.bid_count >= 5:
        pts += min(6, lot.bid_count // 5 + 2)
        why.append(f"{lot.bid_count} bids")

    pts = max(0, min(100, pts))
    if pts < MIN_SCORE:
        return Verdict(pts, why, rejected="nothing collectible about it (no notable brand, precious metal or movement)")
    return Verdict(pts, why)
