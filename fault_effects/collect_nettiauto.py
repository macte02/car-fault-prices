"""Polite, resumable Nettiauto collector for the fault-effect study.

Walks a saved search (default: the watcher's own private-seller search,
`haku=P37140032` — private sellers, < 5000 €, < 275 000 km), stores every
result card, then fetches each ad's detail page once for the free-text
description ("Lisätiedot") and the structured spec boxes (Katsastettu,
Mittarilukema, ...).

Reuses nettiauto.parse_search_results() for the cards. Uses an *anonymous*
httpx client rather than nettiauto.fetch(): for-sale listings are public, and
the watcher's saved session cookies turn public pages into 401s once they
expire — which would make nettiauto.fetch() try to relaunch Chrome / CDP.
Nothing here touches cache.db or nettiauto_session.json.

Rate: one request at a time with a 2.5–5 s jittered pause (≈ 15 req/min),
backing off on 429/5xx. Safe to Ctrl+C and re-run; it resumes where it left off.

    python -m fault_effects.collect_nettiauto                 # walk pages, then details
    python -m fault_effects.collect_nettiauto --max-pages 40 --max-details 500
    python -m fault_effects.collect_nettiauto --details-only
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import sqlite3
import time
from dataclasses import asdict

import httpx
from bs4 import BeautifulSoup

import nettiauto
from fault_effects import paths

log = logging.getLogger("collect_nettiauto")

DEFAULT_SEARCH_URL = "https://www.nettiauto.com/hakutulokset?haku=P37140032&sortCol=dateCreated&ord=desc"

SCHEMA = """
CREATE TABLE IF NOT EXISTS cards (
    ad_id          TEXT PRIMARY KEY,
    url            TEXT NOT NULL,
    search_url     TEXT,
    page           INTEGER,
    card_json      TEXT NOT NULL,
    first_seen_at  INTEGER NOT NULL,
    last_seen_at   INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS details (
    ad_id          TEXT PRIMARY KEY,
    fetched_at     INTEGER NOT NULL,
    http_status    INTEGER,
    title          TEXT,
    usp            TEXT,
    description    TEXT,
    info_json      TEXT,      -- {"Perustiedot": {"Katsastettu": "8/2026", ...}, "Muut": [...], ...}
    status_text    TEXT       -- datalayer item_ad_status on the detail page, if any
);
"""


class Polite:
    """Single-connection client with jittered pacing and backoff."""

    def __init__(self, min_wait: float, max_wait: float):
        self.min_wait, self.max_wait = min_wait, max_wait
        self.client = httpx.Client(headers=nettiauto.DEFAULT_HEADERS,
                                   follow_redirects=True, timeout=25.0)
        self._last = 0.0

    def get(self, url: str) -> httpx.Response | None:
        for attempt, backoff in enumerate((0, 15, 60, 180)):
            if backoff:
                log.warning("backing off %ds before retry %d of %s", backoff, attempt, url)
                time.sleep(backoff)
            wait = random.uniform(self.min_wait, self.max_wait) - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            try:
                r = self.client.get(url)
            except (httpx.TransportError, httpx.TimeoutException) as e:
                log.warning("transport error on %s: %s", url, e)
                self._last = time.time()
                continue
            self._last = time.time()
            if r.status_code in (429, 500, 502, 503, 504):
                continue
            return r
        return None


def connect() -> sqlite3.Connection:
    paths.ensure_dirs()
    c = sqlite3.connect(paths.NETTIAUTO_DB, timeout=10)
    c.executescript(SCHEMA)
    return c


def walk_search(c: sqlite3.Connection, http: Polite, search_url: str, max_pages: int) -> int:
    sep = "&" if "?" in search_url else "?"
    total_new = 0
    for page in range(1, max_pages + 1):
        url = search_url if page == 1 else f"{search_url}{sep}page={page}"
        r = http.get(url)
        if r is None or r.status_code != 200:
            log.warning("page %d failed (%s); stopping walk", page, r.status_code if r else "no response")
            break
        cards = nettiauto.parse_search_results(r.text)
        if not cards:
            log.info("page %d empty; end of results", page)
            break
        now = int(time.time())
        new = 0
        for card in cards:
            cur = c.execute("UPDATE cards SET last_seen_at=?, card_json=? WHERE ad_id=?",
                            (now, json.dumps(asdict(card), ensure_ascii=False), card.ad_id))
            if cur.rowcount == 0:
                c.execute("INSERT INTO cards VALUES (?,?,?,?,?,?,?)",
                          (card.ad_id, card.url, search_url, page,
                           json.dumps(asdict(card), ensure_ascii=False), now, now))
                new += 1
        c.commit()
        total_new += new
        log.info("page %d: %d cards, %d new (total cards %d)", page, len(cards), new,
                 c.execute("SELECT COUNT(*) FROM cards").fetchone()[0])
    return total_new


def parse_detail(page_html: str) -> dict:
    """Title / USP / description + every labelled spec box on the page.

    Description extraction follows nettiauto-watcher's parse_comp_quality_text:
    the section whose mobile title is "Lisätiedot", preferring #fullNote."""
    soup = BeautifulSoup(page_html, "lxml")

    def txt(el) -> str:
        return " ".join(el.get_text(" ", strip=True).split()) if el else ""

    info: dict[str, object] = {}
    description = ""
    for section in soup.select(".vehicle-all-info__section.showHideTechnicalSection"):
        heading = txt(section.select_one(".vehicle-all-info__mobile-title"))
        if heading.lower() == "lisätiedot":
            note = section.select_one("#fullNote") or section.select_one("#noteSection") or section
            description = note.get_text("\n", strip=True)
            continue
        boxes = section.select(".vehicle-info-box")
        if boxes:
            kv = {}
            for b in boxes:
                k = txt(b.select_one(".vehicle-info-box__vehicle-info"))
                v = txt(b.select_one(".vehicle-info-box__vehicle-det"))
                if k:
                    kv[k] = v
            info[heading] = kv
        else:
            items = [txt(x) for x in section.select(".vehicle-all-info__details_block")]
            info[heading] = sorted(set(i for i in items if i))

    status = None
    dl = soup.select_one("[data-datalayer]")
    if dl is not None:
        try:
            import html as _html
            status = json.loads(_html.unescape(dl["data-datalayer"])).get("item_ad_status")
        except Exception:
            pass

    return {
        "title": txt(soup.select_one("h1.details-page-header__item-title")),
        "usp": txt(soup.select_one(".grid-x.cell.unique-selling-point")),
        "description": description,
        "info": info,
        "status_text": status,
    }


def fetch_details(c: sqlite3.Connection, http: Polite, max_details: int | None) -> int:
    todo = [row for row in c.execute(
        "SELECT cards.ad_id, cards.url FROM cards LEFT JOIN details USING (ad_id) "
        "WHERE details.ad_id IS NULL ORDER BY cards.first_seen_at DESC, cards.page")]
    if max_details is not None:
        todo = todo[:max_details]
    log.info("%d detail pages to fetch", len(todo))
    done = 0
    for ad_id, url in todo:
        r = http.get(url)
        now = int(time.time())
        if r is None:
            log.warning("giving up on %s for this run", url)
            continue
        if r.status_code != 200:
            c.execute("INSERT OR REPLACE INTO details (ad_id, fetched_at, http_status) VALUES (?,?,?)",
                      (ad_id, now, r.status_code))
        else:
            d = parse_detail(r.text)
            c.execute("INSERT OR REPLACE INTO details VALUES (?,?,?,?,?,?,?,?)",
                      (ad_id, now, 200, d["title"], d["usp"], d["description"],
                       json.dumps(d["info"], ensure_ascii=False), d["status_text"]))
        c.commit()
        done += 1
        if done % 50 == 0:
            log.info("details: %d/%d", done, len(todo))
    return done


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--search-url", default=DEFAULT_SEARCH_URL)
    ap.add_argument("--max-pages", type=int, default=120)
    ap.add_argument("--max-details", type=int, default=None)
    ap.add_argument("--details-only", action="store_true")
    ap.add_argument("--min-wait", type=float, default=2.5)
    ap.add_argument("--max-wait", type=float, default=5.0)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    c = connect()
    http = Polite(args.min_wait, args.max_wait)
    if not args.details_only:
        walk_search(c, http, args.search_url, args.max_pages)
    fetch_details(c, http, args.max_details)
    n_cards = c.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
    n_det = c.execute("SELECT COUNT(*) FROM details WHERE http_status=200").fetchone()[0]
    log.info("done: %d cards, %d with detail text", n_cards, n_det)


if __name__ == "__main__":
    main()
