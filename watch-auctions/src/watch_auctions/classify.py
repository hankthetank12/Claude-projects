"""Decide what counts as a watch, which brand it is, and which houses are "small"."""
from __future__ import annotations

import re

BRANDS = [
    "A. Lange & Sohne", "Audemars Piguet", "Patek Philippe", "Vacheron Constantin",
    "Jaeger-LeCoultre", "Breguet", "Blancpain", "Glashutte Original", "F.P. Journe",
    "H. Moser", "Richard Mille", "Hublot", "Panerai", "IWC", "Rolex", "Tudor",
    "Omega", "Cartier", "Breitling", "TAG Heuer", "Heuer", "Zenith", "Chopard",
    "Piaget", "Ulysse Nardin", "Girard-Perregaux", "Bell & Ross", "Grand Seiko",
    "Seiko", "Longines", "Tissot", "Hamilton", "Oris", "Rado", "Movado", "Bulova",
    "Gruen", "Elgin", "Waltham", "Hampden", "Illinois Watch", "Bunn Special", "South Bend",
    "Junghans", "Westclox", "Tourneau", "Gallet", "Lemania", "Ingersoll", "Glycine", "Favre-Leuba", "Mühle", "Fendi", "Universal Geneve", "Eterna",
    "Baume & Mercier", "Montblanc", "Bvlgari", "Bulgari", "Hermes", "Chanel",
    "Tiffany", "Gucci", "Corum", "Ebel", "Concord", "Raymond Weil", "Frederique Constant",
    "Franck Muller", "Jules Jurgensen", "Le Coultre", "LeCoultre", "Wittnauer",
    "Doxa", "Sinn", "Nomos", "Citizen", "Casio", "Timex", "Invicta", "Swatch",
    "Mido", "Certina", "Enicar", "Vulcain", "Lucien Piccard", "Benrus",
]
_ALIASES = {"Bulgari": "Bvlgari", "Le Coultre": "Jaeger-LeCoultre", "LeCoultre": "Jaeger-LeCoultre",
            "Heuer": "TAG Heuer", "Bunn Special": "Illinois Watch", "Mühle": "Muhle Glashutte"}


def _fold(s: str) -> str:
    return (s.lower().replace("ö", "o").replace("ü", "u").replace("è", "e")
            .replace("é", "e").replace("’", "'"))


_BRAND_RES = [(b, re.compile(r"(?<![a-z])" + re.escape(_fold(b)).replace(r"\ ", r"[\s.\-]*") + r"(?![a-z])"))
              for b in BRANDS]

WATCH_WORDS = re.compile(
    r"\b(watch|watches|wristwatch|wrist watch|chronograph|chronometer|timepiece|"
    r"submariner|daytona|datejust|speedmaster|seamaster|navitimer|royal oak|nautilus|"
    r"calatrava|reverso|santos|tank)\b")
# Things that mention watches but are not watches.
NOT_A_WATCH = re.compile(
    r"\b(watch (band|strap|bracelet only|box|case only|parts?|movement only|stand|winder|fob|chain|key|tool|"
    r"holder|display|catalog|book)|bands? only|straps? only|empty box|box only|boxes only|"
    r"watch ?winder|display case|book|catalogue|catalog|poster|sign|advert|clock|"
    r"watchmaker'?s? (tools?|lathe)|crystal only|dial only|bezel only|watch fob)\b")

# Big international houses. The point is the long tail, so these are hidden by default.
MAJOR_HOUSES = re.compile(
    r"\b(bonhams|christie'?s|sotheby'?s|phillips|heritage auctions|hindman|freeman'?s|"
    r"skinner|doyle|antiquorum|dorotheum|bukowskis|bruun rasmussen|dr\.? crott|"
    r"auktionen dr\. crott)\b", re.I)


def is_watch(title: str, category: str = "") -> bool:
    t = _fold(title)
    if NOT_A_WATCH.search(t):
        return False
    if "watch" in _fold(category) and "clock" not in _fold(category):
        return True
    return bool(WATCH_WORDS.search(t)) or bool(detect_brand(title) and _strong_brand(title))


def _strong_brand(title: str) -> bool:
    # Brands that only make watches; a title naming one is a watch even without the word.
    b = detect_brand(title)
    return b in {"Rolex", "Patek Philippe", "Audemars Piguet", "Omega", "Tudor", "Breitling",
                 "Vacheron Constantin", "Jaeger-LeCoultre", "Panerai", "IWC", "TAG Heuer",
                 "Zenith", "Hublot", "Longines", "Grand Seiko", "Richard Mille", "Breguet"}


def detect_brand(title: str) -> str:
    t = _fold(title)
    best = None
    for brand, rx in _BRAND_RES:
        m = rx.search(t)
        if m and (best is None or m.start() < best[1]):
            best = (brand, m.start())
    if not best:
        return ""
    return _ALIASES.get(best[0], best[0])


def is_major_house(name: str) -> bool:
    return bool(MAJOR_HOUSES.search(name))
