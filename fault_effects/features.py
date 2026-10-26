"""Build the analysis tables: one row per car, fault flags + hedonic controls.

    python -m fault_effects.features [--huutokaupat-db PATH]

Writes (gitignored):
  data/features_huutokaupat.csv.gz   sold auctions (passenger cars only)
  data/features_nettiauto.csv.gz     Nettiauto asking prices, if collect_nettiauto has run
  data/text_huutokaupat.csv.gz       the raw text + rule evidence, for validation only
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from fault_effects import faults as F
from fault_effects import paths

log = logging.getLogger("features")

FUEL_GROUP = [
    (r"plug-?in|hybrid|hybridi", "hybrid"),
    (r"diesel", "diesel"),
    (r"bensiini|petrol|gasoline", "petrol"),
    (r"s.hk|electric", "electric"),
    (r"kaasu|cng|lpg", "gas"),
    (r"e85|etanoli", "e85"),
]


def fuel_group(f: str | None) -> str:
    t = (f or "").lower()
    if "plug" in t or "hybrid" in t:
        return "hybrid"
    for pat, g in FUEL_GROUP:
        if re.search(pat, t):
            return g
    return "unknown"


def gear_group(g: str | None) -> str:
    t = (g or "").lower()
    if t.startswith("auto"):
        return "automatic"
    if t.startswith("manu"):
        return "manual"
    return "unknown"


def drive_group(d: str | None) -> str:
    t = (d or "").lower()
    if "neli" in t or "4wd" in t or "awd" in t:
        return "4wd"
    if t in ("kaksiveto", "etuveto", "takaveto"):
        return "2wd"
    return "unknown"


def base_model(make: str, model: str) -> str:
    """'Golf Variant' -> 'Golf', '3 Serie Touring' -> '3 Serie', 'C-Class T-Modell' -> 'C-Class'."""
    toks = (model or "").split()
    if not toks:
        return ""
    if len(toks) > 1 and toks[1].lower() in ("serie", "series", "sarja", "-sarja"):
        return f"{toks[0]} Serie"
    return toks[0]


def clean_km(km) -> float | None:
    try:
        km = float(km)
    except (TypeError, ValueError):
        return None
    if km < 1000 or km > 900_000:   # 9 999 999 sentinels, 5-digit rollovers, typos
        return None
    return km


def power_kw(engine: str | None, spec: str | None, biltema: dict | None) -> float | None:
    for s in (engine, spec):
        m = re.search(r"(\d{2,3})\s*kW", s or "")
        if m:
            return float(m.group(1))
    v = (biltema or {}).get("PowerKW")
    try:
        return float(v) if v else None
    except ValueError:
        return None


DEALER_STYLE = re.compile(r"toimestamme|teimme|koeajolla|you are welcome|binding bid|liikkeeseemme|"
                          r"myymalaan|huutokauppaan osallistuminen|asiakkaan|edellisen omistajan mukaan",
                          re.IGNORECASE)


def build_huutokaupat(db_path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    cols = {r[1] for r in con.execute("PRAGMA table_info(huutokaupat_sold)")}
    want = ["ad_id", "url", "end_time", "sold_price", "accepted", "bid_count", "make", "model", "year",
            "mileage_km", "fuel", "transmission", "drive", "engine", "produced_from", "condition_json",
            "faults_text", "raw_json", "source_category", "title", "spec", "seller_type"]
    sel = ", ".join(c if c in cols else f"NULL AS {c}" for c in want)
    rows = con.execute(f"SELECT {sel} FROM huutokaupat_sold").fetchall()
    con.close()
    log.info("read %d Huutokaupat rows from %s", len(rows), db_path)

    recs, texts = [], []
    for r in rows:
        cat = r["source_category"]
        if cat is not None and cat != "henkiloautot":
            continue
        try:
            raw = json.loads(r["raw_json"] or "{}")
        except ValueError:
            raw = {}
        cond = F.parse_condition(r["condition_json"])
        end = None
        if r["end_time"]:
            try:
                end = datetime.fromisoformat(r["end_time"]).date()
            except ValueError:
                pass
        title = r["title"] or (raw.get("huuto") or {}).get("malli")
        fr = F.huutokaupat_flags(cond, r["faults_text"], title, raw.get("huuto"), end)

        make, model = (r["make"] or "").strip(), (r["model"] or "").strip()
        bm = base_model(make, model)
        pf = (r["produced_from"] or "")[:4]
        rec = {
            "ad_id": str(r["ad_id"]),
            "source": "huutokaupat",
            "price": r["sold_price"],
            "accepted": int(r["accepted"] or 0),
            "bid_count": r["bid_count"],
            "end_date": end.isoformat() if end else None,
            "month": end.strftime("%Y-%m") if end else "unknown",
            "make": make,
            "model": model,
            "make_model": f"{make}|{model}",
            "segment": f"{make} {bm}".strip(),
            "generation": f"{make}|{model}|{pf}" if pf.isdigit() else f"{make}|{model}|?",
            "year": r["year"],
            "km": clean_km(r["mileage_km"]),
            "fuel": fuel_group(r["fuel"]),
            "gear": gear_group(r["transmission"]),
            "drive": drive_group(r["drive"]),
            "kw": power_kw(r["engine"], r["spec"], raw.get("biltema")),
            "seller_type": r["seller_type"] or "unknown",
            "dealer_style": int(bool(DEALER_STYLE.search(r["faults_text"] or ""))),
        }
        rec.update(fr.flags)
        recs.append(rec)
        texts.append({
            "ad_id": rec["ad_id"],
            "url": r["url"],
            "title": title,
            "light_answer": cond.get(F.HK_FIELDS["light"]),
            "inspection_answer": cond.get(F.HK_FIELDS["inspection"]),
            "body_answer": cond.get(F.HK_FIELDS["body"]),
            "windshield_answer": cond.get(F.HK_FIELDS["windshield"]),
            "interior_answer": cond.get(F.HK_FIELDS["interior"]),
            "service_book_answer": cond.get(F.HK_FIELDS["service_book"]),
            "faults_text": r["faults_text"],
            "evidence": json.dumps(fr.evidence, ensure_ascii=False),
        })
    return pd.DataFrame(recs), pd.DataFrame(texts)


def _num(s) -> float | None:
    m = re.search(r"\d+(?:[.,]\d+)?", (s or "").replace("\xa0", " ").replace(" ", ""))
    return float(m.group().replace(",", ".")) if m else None


def build_nettiauto(db_path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    rows = con.execute("""SELECT c.ad_id, c.url, c.card_json, c.first_seen_at, d.fetched_at, d.title,
                                 d.usp, d.description, d.info_json
                          FROM cards c JOIN details d USING (ad_id) WHERE d.http_status = 200""").fetchall()
    con.close()
    recs, texts = [], []
    for r in rows:
        card = json.loads(r["card_json"])
        info = json.loads(r["info_json"] or "{}")
        basic = info.get("Perustiedot") or {}
        tech = info.get("Tekniset tiedot") or {}
        fetched = datetime.fromtimestamp(r["fetched_at"]).date()
        fr = F.nettiauto_flags(r["title"] or card.get("title"), r["usp"] or card.get("usp_info"),
                               r["description"], info, card.get("engine_size"), fetched)
        year = card.get("year")
        # Nettiauto's "Katsastettu 8/2026" is the date of the last inspection.
        # Cars >= 10 years old are inspected yearly, so > 13 months ago ≈ overdue.
        insp = re.search(r"(\d{1,2})\s*/\s*(\d{4})", basic.get("Katsastettu") or "")
        months_since = None
        if insp:
            months_since = (fetched.year - int(insp.group(2))) * 12 + fetched.month - int(insp.group(1))
            if year and fetched.year - int(year) >= 10 and months_since > 13:
                fr.flags["inspection_invalid"] = 1
                fr.evidence.setdefault("inspection_invalid", f"[field] last inspection {insp.group(0)}")
        make, model = card.get("make") or "", card.get("model") or ""
        rec = {
            "ad_id": str(r["ad_id"]),
            "source": "nettiauto",
            "price": card.get("price"),
            "accepted": None,
            "bid_count": None,
            "end_date": fetched.isoformat(),
            "month": fetched.strftime("%Y-%m"),
            "make": make,
            "model": model,
            "make_model": f"{make}|{model}",
            "segment": f"{make} {model}".strip(),
            "generation": f"{make}|{model}|?",
            "year": year,
            "km": clean_km(card.get("mileage_km") or _num(basic.get("Mittarilukema"))),
            "fuel": fuel_group(card.get("fuel")),
            "gear": gear_group(card.get("transmission")),
            "drive": drive_group(card.get("drive")),
            "kw": _num((tech.get("Teho") or "").split("kW")[0]) if "kW" in (tech.get("Teho") or "") else None,
            "seller_type": "private" if (card.get("seller_type") or "").lower() == "private seller" else "dealer",
            "dealer_style": 0,
            "months_since_inspection": months_since,
        }
        rec.update(F.finalize(fr).flags)
        recs.append(rec)
        texts.append({"ad_id": rec["ad_id"], "url": r["url"], "title": r["title"], "usp": r["usp"],
                      "description": r["description"], "evidence": json.dumps(fr.evidence, ensure_ascii=False)})
    return pd.DataFrame(recs), pd.DataFrame(texts)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--huutokaupat-db", type=Path, default=None,
                    help="default: $NETTIAUTO_HUUTOKAUPAT_DB or data/huutokaupat.db")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    paths.ensure_dirs()

    db_path = args.huutokaupat_db or paths.huutokaupat_db()
    if not db_path.exists():
        raise SystemExit(f"Huutokaupat archive not found at {db_path} (pass --huutokaupat-db)")
    hk, hk_text = build_huutokaupat(db_path)
    hk.to_csv(paths.FEATURES_HK, index=False)
    hk_text.to_csv(paths.DATA / "text_huutokaupat.csv.gz", index=False)
    meta = {"huutokaupat_db": db_path.name, "rows": len(hk),
            "end_min": hk["end_date"].min(), "end_max": hk["end_date"].max(),
            "built": date.today().isoformat()}
    log.info("Huutokaupat: %d passenger-car rows (%s .. %s)", len(hk), meta["end_min"], meta["end_max"])

    if paths.NETTIAUTO_DB.exists():
        na, na_text = build_nettiauto(paths.NETTIAUTO_DB)
        if len(na):
            na.to_csv(paths.FEATURES_NA, index=False)
            na_text.to_csv(paths.DATA / "text_nettiauto.csv.gz", index=False)
        meta["nettiauto_rows"] = len(na)
        log.info("Nettiauto: %d listings with detail text", len(na))
    (paths.DATA / "features_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
