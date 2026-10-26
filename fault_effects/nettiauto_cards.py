"""Nettiauto search-result cards.

Each card on a results page embeds a JSON datalayer attribute that already
gives make/model/year/price/mileage/fuel, so one results page is enough for the
basic fields. Used by collect_nettiauto.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from typing import Iterable

from bs4 import BeautifulSoup

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0 Safari/537.36"
)
DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "fi-FI,fi;q=0.9,en;q=0.8",
}


@dataclass
class AdCard:
    """A single ad as it appears in a search results page."""
    ad_id: str
    url: str
    make: str
    model: str
    make_slug: str
    model_slug: str
    year: int | None
    price: int | None
    mileage_km: int | None
    fuel: str | None
    transmission: str | None
    drive: str | None
    engine_size: str | None
    seller_type: str | None
    ad_status: str | None
    title: str | None
    usp_info: str | None


def parse_search_results(page_html: str) -> list[AdCard]:
    """Parse a Nettiauto search-results page into ad cards."""
    soup = BeautifulSoup(page_html, "lxml")
    cards: list[AdCard] = []
    seen_ids: set[str] = set()

    for div in soup.select("div.product-card[data-datalayer]"):
        raw = div.get("data-datalayer")
        if not raw:
            continue
        try:
            data = json.loads(html.unescape(raw))
        except json.JSONDecodeError:
            continue
        # Skip "Ohituskaista" (fastlane / sponsored) cards. They rotate per
        # request, so treating them as part of the result set creates phantom
        # "new" ads on every page load. Only "Listaussivu" entries are real results.
        list_id = str(data.get("item_list_id") or "")
        if list_id and list_id.lower() != "listaussivu":
            continue
        ad_id = str(data.get("item_id") or "").strip()
        if not ad_id or ad_id in seen_ids:
            continue
        seen_ids.add(ad_id)

        link = div.select_one("a.product-card-link__tricky-link[href]")
        url = link["href"] if link else ""
        if not url:
            continue
        if url.startswith("/"):
            url = "https://www.nettiauto.com" + url
        make_slug, model_slug = _extract_slugs_from_url(url)

        spec = div.select_one(".product-card__basic-info-list")
        spec_parts = [s.get_text(strip=True).lstrip("●").strip() for s in spec.find_all("span")] if spec else []
        # spec_parts: ["2005", "200 123 km", "Bensiini", "Manuaali", "Etuveto"]

        transmission = _pick(spec_parts, ("manuaali", "automaatti"))
        drive = _pick(spec_parts, ("etuveto", "takaveto", "neliveto"))

        # Mileage: prefer the JSON field but fall back to the spec line. Newly
        # posted ads sometimes have item_mileage missing/empty even though the
        # spec line shows "248 000 km".
        mileage_km = _int(data.get("item_mileage")) or _spec_mileage(spec_parts)
        fuel = (str(data.get("item_power_type") or "").strip()
                or _pick(spec_parts, ("bensiini", "diesel", "hybridi", "sähkö",
                                       "kaasu", "vety", "e85/bensiini")))

        engine_size_el = div.select_one(".product-card__sub-title")
        engine_size = engine_size_el.get_text(" ", strip=True) if engine_size_el else None

        title_el = div.select_one("h2.product-card__title")
        title = title_el.get_text(strip=True) if title_el else None

        usp_el = div.select_one(".product-card__usp-info")
        usp_info = usp_el.get_text(" ", strip=True) if usp_el else None

        cards.append(AdCard(
            ad_id=ad_id,
            url=url,
            make=str(data.get("item_brand") or "").strip(),
            model=str(data.get("item_variant") or "").strip(),
            make_slug=make_slug,
            model_slug=model_slug,
            year=_int(data.get("item_year_model")),
            price=_int(data.get("item_vehicle_price")),
            mileage_km=mileage_km,
            fuel=fuel or None,
            transmission=transmission,
            drive=drive,
            engine_size=engine_size,
            seller_type=str(data.get("item_seller") or "").strip() or None,
            ad_status=str(data.get("item_ad_status") or "").strip() or None,
            title=title,
            usp_info=usp_info,
        ))
    return cards


def _extract_slugs_from_url(url: str) -> tuple[str, str]:
    """`/<make>/<model>/<id>` or absolute -> (make_slug, model_slug)."""
    m = re.search(r"(?:nettiauto\.com)?/([a-z0-9-]+)/([a-z0-9-]+)/\d+", url, re.IGNORECASE)
    return (m.group(1).lower(), m.group(2).lower()) if m else ("", "")


def _pick(parts: Iterable[str], options: tuple[str, ...]) -> str | None:
    for p in parts:
        for opt in options:
            if p.lower().strip() == opt:
                return p.strip()
    return None


def _spec_mileage(parts: Iterable[str]) -> int | None:
    """Pull a mileage figure out of spec_parts items like '248 000 km'."""
    for p in parts:
        m = re.match(r"^\s*([\d\s]+?)\s*km\s*$", p, re.IGNORECASE)
        if m:
            digits = m.group(1).replace(" ", "").replace(" ", "")
            if digits.isdigit():
                return int(digits)
    return None


def _int(v) -> int | None:
    try:
        return int(v) if v is not None and str(v) != "" else None
    except (ValueError, TypeError):
        return None
