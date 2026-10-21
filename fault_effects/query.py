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

    with open(paths.MODEL_DIR / "ols.pkl", "rb") as fh:
        models = pickle.load(fh)
    spec = "A" if a.fault == "warning_light_any" else "B"
    m = models[spec]

    same_year = cand[cand.year == a.year]
    pick = same_year if len(same_year) else cand
    car = pick.iloc[[0]].copy()
    car["make_model"] = pick.make_model.mode().iat[0]
    car["year"] = a.year
    car["km"] = a.km if a.km is not None else float(cand.km.median())
    car["gear"] = a.gear or cand.gear.mode().iat[0]
    car["drive"] = cand.drive.mode().iat[0]
    car["kw"] = float(cand.kw.median())
    car["log_kw"] = np.log(car.kw)
    car["km_missing"] = car["kw_missing"] = 0
    car["month"] = df.month.max()
    car["end_date"] = df.end_date.max()
    car["seller_type"] = "unknown"
    car["dealer_style"] = int(cand.dealer_style.mean() >= 0.5)
    for f in M.SPEC_A + M.SPEC_B:
        car[f] = 0
    car["age"] = pd.to_datetime(car.end_date).dt.year - a.year

    d, _ = M.fill_numeric(car, m["medians"])
    Xc, _ = M.controls(d, m["levels"])
    X = pd.concat([Xc, d[m["flags"]].astype(float)], axis=1).reindex(columns=m["cols"], fill_value=0.0)
    fe = m["fe"].get(car.make_model.iat[0], np.median(list(m["fe"].values())))
    clean = float(np.exp(X.values @ m["beta"].values + fe) * m["smear"])

    seg_name = car.segment.iat[0]
    eff = overall.set_index("flag").loc[a.fault]
    source = "overall"
    pct, lo, hi = eff.pct, eff.pct_lo, eff.pct_hi
    seg_path = paths.REPORTS / "effects_by_segment.csv"
    if seg_path.exists():
        seg = pd.read_csv(seg_path)
        s = seg[(seg.flag == a.fault) & (seg.segment == seg_name)]
        if len(s) and pd.notna(s.pct.iat[0]):
            source = f"segment '{seg_name}' (n_faulty={int(s.n_faulty.iat[0])}, shrunk toward overall)"
            pct, lo, hi = s.pct_shrunk.iat[0], s.pct_lo.iat[0], s.pct_hi.iat[0]
        elif len(s):
            source = f"overall (segment '{seg_name}' has only {int(s.n_faulty.iat[0])} faulty cars)"

    print(f"\n{a.year} {a.make} {a.model} ({car.fuel.iat[0]}, {car.gear.iat[0]}, {car.km.iat[0]:,.0f} km, "
          f"model row '{car.make_model.iat[0]}')")
    print(f"  predicted clean auction price  ≈ {clean:,.0f} €")
    if eff.n_faulty < M.MIN_N or pd.isna(pct):
        print(f"  {F.LABELS.get(a.fault, a.fault)}: not enough data (n={int(eff.n_faulty)})")
    else:
        print(f"  {F.LABELS.get(a.fault, a.fault)}: {pct:+.1%}  (95% CI {lo:+.1%} … {hi:+.1%}; {source})")
        print(f"  → ≈ {clean * (1 + pct):,.0f} €, i.e. {clean * pct:+,.0f} € "
              f"(CI {clean * lo:+,.0f} … {clean * hi:+,.0f} €)")

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
