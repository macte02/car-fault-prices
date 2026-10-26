"""Shared paths. Raw data lives in data/ (gitignored); small result tables in reports/."""

from __future__ import annotations

import os
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"
REPORTS = REPO / "reports"
LABELS = Path(__file__).resolve().parent / "labels"

NETTIAUTO_DB = DATA / "nettiauto_listings.db"
FEATURES_HK = DATA / "features_huutokaupat.csv.gz"
FEATURES_NA = DATA / "features_nettiauto.csv.gz"
MODEL_DIR = DATA / "model"


def huutokaupat_db() -> Path:
    """Huutokaupat archive: env override, else data/huutokaupat.db. Read-only from here."""
    return Path(
        os.environ.get("NETTIAUTO_HUUTOKAUPAT_DB")
        or (DATA / "huutokaupat.db")
    )


def ensure_dirs() -> None:
    for d in (DATA, REPORTS, MODEL_DIR):
        d.mkdir(parents=True, exist_ok=True)
