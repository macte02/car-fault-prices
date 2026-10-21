"""Ask the fitted models about one car.

    python -m fault_effects.query --make Volkswagen --model Golf --year 2012 --fuel diesel --fault light_engine
    python -m fault_effects.query --make Volvo --model V70 --year 2008 --km 320000 --fault rust_severe
    python -m fault_effects.query --list-faults

Builds a representative car from sold Huutokaupat auctions of that make/model
(± 2 model years, same fuel), predicts its clean price with the hedonic model,
and applies the fault effect — the segment's own (shrunk) estimate when there
are enough faulty cars in that segment, else the overall one. Prints the raw
comparable-auction table underneath so the number can be sanity-checked.
"""

from __future__ import annotations

import argparse
import pickle

import numpy as np
import pandas as pd

from fault_effects import faults as F
from fault_effects import model as M
from fault_effects import paths


def representative(df: pd.DataFrame, make: str, model: str, year: int, fuel: str | None) -> pd.DataFrame:
    mk = df.make.str.lower() == make.lower()
    base = df.segment.str.lower() == f"{make} {model}".lower()
    mm = df.model.str.lower().str.startswith(model.lower())
    c = df[mk & (base | mm) & df.year.between(year - 2, year + 2)]
    if fuel:
        c = c[c.fuel == fuel.lower()]
    return c


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--make")
    ap.add_argument("--model")
    ap.add_argument("--year", type=int)
    ap.add_argument("--fuel", choices=["petrol", "diesel", "hybrid", "electric", "gas", "e85"], default=None)
    ap.add_argument("--gear", choices=["manual", "automatic"], default=None)
    ap.add_argument("--km", type=float, default=None)
    ap.add_argument("--fault", default="light_engine")
    ap.add_argument("--list-faults", action="store_true")
    a = ap.parse_args()

    overall = pd.read_csv(paths.REPORTS / "effects_overall.csv")
    if a.list_faults:
        print(overall[["flag", "label", "n_faulty"]].to_string(index=False))
        return
    if not (a.make and a.model and a.year):
        ap.error("--make, --model and --year are required")

    df = M.load_huutokaupat()
    cand = representative(df, a.make, a.model, a.year, a.fuel)
    if a.gear:
        cand = cand[cand.gear == a.gear]
    if cand.empty:
        raise SystemExit("no comparable sold auctions in the data for that make/model/year/fuel")

    # Clean price from LightGBM (better calibrated across price levels than the
    # hedonic OLS); the fault effect itself comes from the hedonic band tables.
    with open(paths.MODEL_DIR / "lgbm_specB.pkl", "rb") as fh:
        lg = pickle.load(fh)
    _, cats = M.lgb_frame(df, lg["flags"])

    same_year = cand[cand.year == a.year]
    pick = same_year if len(same_year) else cand
    car = pick.iloc[[0]].copy()
    car["make_model"] = pick.make_model.mode().iat[0]
    car["year"] = a.year
    car["km"] = a.km if a.km is not None else float(cand.km.median())
    car["gear"] = a.gear or cand.gear.mode().iat[0]
    car["drive"] = cand.drive.mode().iat[0]
    car["kw"] = float(cand.kw.median())
    car["end_date"] = df.end_date.dropna().max()          # priced as of the latest auction month
    car["seller_type"] = "unknown"
    car["dealer_style"] = int(cand.dealer_style.mean() >= 0.5)
    for f in M.SPEC_A + M.SPEC_B:
        car[f] = 0
    car["age"] = pd.to_datetime(car.end_date).dt.year - a.year

    X, _ = M.lgb_frame(car, lg["flags"], cats)
    clean = float(np.exp(lg["model"].predict(X)[0]) * lg["smear"])

    seg_name = car.segment.iat[0]
    ov = overall.set_index("flag")
    if a.fault not in ov.index:
        raise SystemExit(f"unknown fault {a.fault!r}; see --list-faults")
    eff = ov.loc[a.fault]
    band = M.value_band(pd.Series([clean])).iat[0]
    label = F.LABELS.get(a.fault, a.fault)

    # Primary: the effect estimated for cars in this clean-value band.
    source, pct, lo, hi = "all cars pooled", eff.pct, eff.pct_lo, eff.pct_hi
    band_path = paths.REPORTS / "effects_by_band.csv"
    if band_path.exists():
        bt = pd.read_csv(band_path)
        r = bt[(bt.flag == a.fault) & (bt.band == band)]
        if len(r) and r.n_faulty.iat[0] >= M.MIN_N_BAND and pd.notna(r.pct.iat[0]):
            source = f"cars worth {band} (n_faulty={int(r.n_faulty.iat[0])})"
            pct, lo, hi = r.pct.iat[0], r.pct_lo.iat[0], r.pct_hi.iat[0]
        elif len(r):
            source = f"all cars pooled (band {band} has only {int(r.n_faulty.iat[0])} faulty cars)"

    print(f"\n{a.year} {a.make} {a.model} ({car.fuel.iat[0]}, {car.gear.iat[0]}, {car.km.iat[0]:,.0f} km, "
          f"model row '{car.make_model.iat[0]}')")
    print(f"  predicted clean auction price  ≈ {clean:,.0f} €  (band {band})")
    if eff.n_faulty < M.MIN_N or pd.isna(pct):
        print(f"  {label}: not enough data (n={int(eff.n_faulty)})")
    else:
        print(f"  {label}: {clean * pct:+,.0f} €  (95% CI {clean * lo:+,.0f} … {clean * hi:+,.0f} €; "
              f"{pct:+.1%}; effect from {source})")
        print(f"  → ≈ {clean * (1 + pct):,.0f} € with the fault, other disclosed faults absent")
    seg_path = paths.REPORTS / "effects_by_segment.csv"
    if seg_path.exists():
        seg = pd.read_csv(seg_path)
        s = seg[(seg.flag == a.fault) & (seg.segment == seg_name)]
        if len(s) and pd.notna(s.pct.iat[0]):
            print(f"  {seg_name} only: {s.pct.iat[0]:+.1%} (95% CI {s.pct_lo.iat[0]:+.1%} … {s.pct_hi.iat[0]:+.1%}),"
                  f" shrunk toward all cars {s.pct_shrunk.iat[0]:+.1%}; n_faulty={int(s.n_faulty.iat[0])}")
        elif len(s):
            print(f"  {seg_name} only: not enough data (n_faulty={int(s.n_faulty.iat[0])})")

    # Raw comparable table: same segment, ±2 years, same fuel — with and without the fault.
    flag = a.fault
    comp = cand.assign(has_fault=cand[flag].astype(bool))
    tab = comp.groupby("has_fault").agg(n=("price", "size"), median_price=("price", "median"),
                                        median_km=("km", "median"), median_year=("year", "median"))
    print(f"\nRaw sold auctions, {a.make} {a.model} {a.year - 2}–{a.year + 2}"
          f"{' ' + a.fuel if a.fuel else ''} (Huutokaupat):")
    print(tab.to_string())


if __name__ == "__main__":
    main()
