"""Estimate how much each disclosed fault lowers the price.

    python -m fault_effects.model [--boot 30]

Three estimators, so no single modelling choice carries the result:

1. Hedonic OLS on log(price) with make×model fixed effects (absorbed by
   within-transformation), year and auction-month dummies, a piecewise-linear
   mileage spline, log(kW), fuel / gearbox / drive / seller controls, and all
   fault flags at once. Standard errors are clustered by make×model. A flag's
   coefficient b means "cars with this fault sell for exp(b)−1 % less than
   otherwise comparable cars", holding the other disclosed faults fixed.
2. LightGBM on the same features (no linearity / additivity assumption). The
   effect is the out-of-bag counterfactual: predict each faulty car with the
   flag on vs. off, averaged over faulty cars, bootstrapped for a CI. A SHAP
   effect (mean TreeSHAP of the flag, treated minus untreated) is reported too.
3. Exact matching: same make×model, model year, fuel, gearbox and 50 000 km
   band; cars whose only checked fault is this one vs. cars with none.

Per-segment effects (top make/base-model groups) come from the OLS with
flag×segment interactions, shown raw and shrunk toward the overall effect
(empirical Bayes), and as "not enough data" below 15 faulty cars.
"""

from __future__ import annotations

import argparse
import json
import logging
import pickle
import time

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import sparse

from fault_effects import faults as F
from fault_effects import paths

log = logging.getLogger("model")

MIN_N = 30            # min faulty cars for an overall effect
MIN_N_SEG = 15        # min faulty cars for a segment effect
MIN_SEG_SIZE = 250    # segments analysed separately
KM_KNOTS = (100, 200, 300, 400)   # thousand km

# Faults derived from text / checklist that we report effects for.
TEXT_MODEL_FLAGS = [
    "timing_belt_due", "timing_chain_issue", "gearbox_issue", "clutch_issue", "engine_major",
    "engine_running_issue", "non_runner", "not_roadworthy", "inspection_lapsed", "inspection_failed",
    "rust_cosmetic", "rust_severe", "crash_damage", "body_dents", "paint_damage", "windshield_crack",
    "water_ingress", "interior_damage", "ac_issue", "oil_leak", "coolant_issue", "brakes_issue",
    "suspension_issue", "wheel_bearing", "exhaust_issue", "steering_issue", "electrical_minor",
    "dpf_issue", "emissions_issue", "battery_weak", "odometer_uncertain", "project_for_parts",
    "tyres_worn",
]
LIGHT_TYPES = F.LIGHT_FLAGS                      # incl. light_unspecified
OTHER_FLAGS = F.ADMIN_FLAGS + ["timing_belt_done"]
SPEC_A = ["warning_light_any"] + TEXT_MODEL_FLAGS + OTHER_FLAGS
SPEC_B = LIGHT_TYPES + TEXT_MODEL_FLAGS + OTHER_FLAGS

# "Major" checked faults used to define clean controls for matching.
MATCH_FAULTS = ["warning_light_any", "timing_belt_due", "gearbox_issue", "clutch_issue", "engine_major",
                "engine_running_issue", "non_runner", "not_roadworthy", "inspection_lapsed",
                "inspection_failed", "rust_severe", "crash_damage", "windshield_crack", "project_for_parts",
                "water_ingress", "coolant_issue", "dpf_issue"]

SEG_FLAGS = ["warning_light_any", "light_engine", "light_abs_esp", "light_airbag", "light_dpf",
             "light_glow_plug", "timing_belt_due", "gearbox_issue", "clutch_issue", "engine_major",
             "non_runner", "not_roadworthy", "inspection_lapsed", "inspection_failed", "rust_cosmetic",
             "rust_severe", "crash_damage", "windshield_crack"]

LGB_PARAMS = dict(n_estimators=700, learning_rate=0.04, num_leaves=63, min_child_samples=20,
                  subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0,
                  random_state=0, verbose=-1)


# ─────────────────────────── data ───────────────────────────

def load_huutokaupat(min_price: int = 100) -> pd.DataFrame:
    df = pd.read_csv(paths.FEATURES_HK, dtype={"ad_id": str})
    bids_ok = (df.bid_count.fillna(0) >= 1) | (df.bid_count.isna() & (df.accepted == 1))
    df = df[bids_ok & (df.price >= min_price) & df.year.between(1990, 2026)
            & (df.make.fillna("") != "") & (df.model.fillna("") != "")
            & ~df.make.isin(["Ulosmitattu"])].copy()
    return prepare(df)


def load_nettiauto(min_price: int = 100) -> pd.DataFrame:
    df = pd.read_csv(paths.FEATURES_NA, dtype={"ad_id": str})
    df = df[(df.price >= min_price) & df.year.between(1990, 2026) & (df.make.fillna("") != "")].copy()
    df["accepted"] = 1
    return prepare(df)


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    df["sale_year"] = pd.to_datetime(df.end_date, errors="coerce").dt.year.fillna(2026).astype(int)
    df["year"] = df.year.astype(int)
    df["age"] = (df.sale_year - df.year).clip(lower=0)
    df["log_price"] = np.log(df.price.astype(float))
    df["km_missing"] = df.km.isna().astype(int)
    df["kw_missing"] = df.kw.isna().astype(int)
    df["log_kw"] = np.log(df.kw.where(df.kw.between(20, 600)))
    for c in F.ALL_FLAGS:
        if c not in df:
            df[c] = 0
        df[c] = df[c].fillna(0).astype(int)
    df["inspection_lapsed"] = ((df.inspection_invalid == 1) & (df.inspection_failed == 0)).astype(int)
    df["any_fault"] = df[[c for c in MATCH_FAULTS if c in df]].max(axis=1)
    return df


def fill_numeric(df: pd.DataFrame, medians: dict | None = None) -> tuple[pd.DataFrame, dict]:
    """Impute km by age and kW by make×model (train medians), for the linear model."""
    d = df.copy()
    if medians is None:
        medians = {
            "km_by_age": d.groupby("age").km.median().to_dict(),
            "km": float(d.km.median()),
            "kw_by_mm": d.groupby("make_model").log_kw.median().dropna().to_dict(),
            "kw": float(d.log_kw.median()),
        }
    d["km_f"] = d.km.fillna(d.age.map(medians["km_by_age"])).fillna(medians["km"])
    d["log_kw_f"] = d.log_kw.fillna(d.make_model.map(medians["kw_by_mm"])).fillna(medians["kw"])
    return d, medians


def controls(d: pd.DataFrame, levels: dict | None = None) -> tuple[pd.DataFrame, dict]:
    """Hedonic controls (no FE). `levels` fixes the dummy columns for prediction."""
    k = d.km_f / 1000.0
    X = pd.DataFrame({"km": k}, index=d.index)
    for kn in KM_KNOTS:
        X[f"km_gt{kn}"] = (k - kn).clip(lower=0)
    X["km_missing"] = d.km_missing
    X["log_kw"] = d.log_kw_f
    X["kw_missing"] = d.kw_missing
    X["dealer_style"] = d.dealer_style.fillna(0)
    cats = {"year": d.year.astype(str), "month": d.month.astype(str), "fuel": d.fuel, "gear": d.gear,
            "drive": d.drive, "seller": d.seller_type.fillna("unknown")}
    if levels is None:
        # Levels and the omitted base level are fixed on the training data so a
        # test fold or a single query row gets exactly the same columns.
        levels = {c: {"levels": sorted(v.unique().tolist()), "base": v.value_counts().idxmax()}
                  for c, v in cats.items()}
    for c, v in cats.items():
        for l in levels[c]["levels"]:
            if l != levels[c]["base"]:
                X[f"{c}={l}"] = (v == l).astype(float)
    return X.astype(float), levels


# ─────────────────────────── OLS with absorbed FE ───────────────────────────

class FEOLS:
    """OLS with one absorbed fixed effect.

    cov="cluster" clusters on the FE groups (main effects: a flag varies across
    hundreds of make×models). cov="hc1" is for terms identified inside one or
    two FE groups (segment interactions): there the within-cluster score of the
    term is zero by construction, so a clustered SE collapses toward 0.
    """

    def __init__(self, cov: str = "cluster"):
        self.cov_type = cov

    def fit(self, X: pd.DataFrame, y: pd.Series, g: pd.Series):
        keep = g.map(g.value_counts()) > 1          # singletons carry no within-FE information
        X, y, g = X[keep], y[keep], g[keep]
        Xd = X - X.groupby(g.values).transform("mean")
        yd = y - y.groupby(g.values).transform("mean")
        nz = Xd.abs().sum() > 1e-9
        self.dropped = list(Xd.columns[~nz])
        Xd = Xd.loc[:, nz]
        codes = pd.factorize(g)[0]
        if self.cov_type == "cluster":
            self.res = sm.OLS(yd.values, Xd.values).fit(cov_type="cluster", cov_kwds={"groups": codes})
        else:
            self.res = sm.OLS(yd.values, Xd.values).fit(cov_type="HC1")
        self.cols = list(Xd.columns)
        self.beta = pd.Series(self.res.params, index=self.cols)
        self.cov = pd.DataFrame(self.res.cov_params(), index=self.cols, columns=self.cols)
        self.se = pd.Series(self.res.bse, index=self.cols)
        fe = (y - X[self.cols] @ self.beta).groupby(g.values).mean()
        self.fe = fe.to_dict()
        resid = y - (X[self.cols] @ self.beta + g.map(self.fe))
        self.smear = float(np.mean(np.exp(resid)))
        self.n, self.n_groups = len(y), g.nunique()
        self.used_index = y.index
        return self

    def predict_log(self, X: pd.DataFrame, g: pd.Series, fallback: float | None = None) -> pd.Series:
        fe = g.map(self.fe)
        if fallback is not None:
            fe = fe.fillna(fallback)
        return X.reindex(columns=self.cols, fill_value=0.0) @ self.beta + fe


def ols_effects(df: pd.DataFrame, flags: list[str], fe_col: str = "make_model") -> tuple[pd.DataFrame, FEOLS]:
    d, med = fill_numeric(df)
    Xc, lv = controls(d)
    X = pd.concat([Xc, d[flags].astype(float)], axis=1)
    m = FEOLS().fit(X, d.log_price, d[fe_col])
    m.medians, m.levels, m.flags = med, lv, flags
    used = d.loc[m.used_index]
    Xu = X.loc[m.used_index]
    yhat = m.predict_log(Xu, used[fe_col])
    rows = []
    for f in flags:
        treated = used[f] == 1
        n_t = int(treated.sum())
        row = {"flag": f, "n_faulty": n_t, "n_total": int(len(used))}
        if f in m.beta.index and n_t > 0:
            b, se = m.beta[f], m.se[f]
            # Counterfactual clean price of the faulty cars (Duan smearing).
            p0 = np.exp(yhat[treated] - b) * m.smear
            row.update(b=b, se=se, p=float(m.res.pvalues[m.cols.index(f)]),
                       pct=np.expm1(b), pct_lo=np.expm1(b - 1.96 * se), pct_hi=np.expm1(b + 1.96 * se),
                       clean_price_median=float(np.median(p0)), actual_price_median=float(used.price[treated].median()),
                       eur=float(np.mean(p0) * np.expm1(b)),
                       eur_lo=float(np.mean(p0) * np.expm1(b - 1.96 * se)),
                       eur_hi=float(np.mean(p0) * np.expm1(b + 1.96 * se)))
        rows.append(row)
    return pd.DataFrame(rows), m


# ─────────────────────────── cross-validation ───────────────────────────

def _sparse_design(d: pd.DataFrame, flags: list[str], levels: dict, mm_levels: list[str]):
    Xc, _ = controls(d, levels)
    mm = pd.Categorical(d.make_model.where(d.make_model.isin(mm_levels)), categories=mm_levels)
    codes = mm.codes
    ok = codes >= 0
    fe = sparse.csr_matrix((np.ones(ok.sum()), (np.where(ok)[0], codes[ok])), shape=(len(d), len(mm_levels)))
    dense = pd.concat([Xc, d[flags].astype(float)], axis=1).values if flags else Xc.values
    return sparse.hstack([fe, sparse.csr_matrix(dense)]).tocsr()


def lgb_frame(df: pd.DataFrame, flags: list[str], cats: dict | None = None) -> tuple[pd.DataFrame, dict]:
    X = pd.DataFrame(index=df.index)
    cat_cols = ["make", "make_model", "fuel", "gear", "drive", "seller_type"]
    if cats is None:
        cats = {c: sorted(df[c].fillna("unknown").astype(str).unique().tolist()) for c in cat_cols}
    for c in cat_cols:
        v = df[c].fillna("unknown").astype(str)
        X[c] = pd.Categorical(v.where(v.isin(cats[c])), categories=cats[c])   # unseen level -> NaN
    X["year"] = df.year
    X["age"] = df.age
    X["km"] = df.km
    X["kw"] = df.kw
    X["month_idx"] = pd.to_datetime(df.end_date, errors="coerce").dt.month.fillna(0)
    X["dealer_style"] = df.dealer_style.fillna(0)
    for f in flags:
        X[f] = df[f].astype(int)
    return X, cats


def cross_validate(df: pd.DataFrame, flags: list[str], k: int = 5, seed: int = 42) -> pd.DataFrame:
    import lightgbm as lgb
    from sklearn.linear_model import Ridge
    from sklearn.model_selection import KFold

    y = df.log_price.values
    out = []
    for name, use in (("without fault flags", []), ("with fault flags", flags)):
        oof_ols = np.zeros(len(df))
        oof_lgb = np.zeros(len(df))
        for tr, te in KFold(k, shuffle=True, random_state=seed).split(df):
            dtr, dte = df.iloc[tr], df.iloc[te]
            dtr_f, med = fill_numeric(dtr)
            dte_f, _ = fill_numeric(dte, med)
            _, lv = controls(dtr_f)
            mm_levels = sorted(dtr.make_model.unique())
            r = Ridge(alpha=0.5).fit(_sparse_design(dtr_f, use, lv, mm_levels), y[tr])
            oof_ols[te] = r.predict(_sparse_design(dte_f, use, lv, mm_levels))
            Xtr, cats = lgb_frame(dtr, use)
            Xte, _ = lgb_frame(dte, use, cats)
            g = lgb.LGBMRegressor(**LGB_PARAMS).fit(Xtr, y[tr])
            oof_lgb[te] = g.predict(Xte)
        for model, pred in (("hedonic OLS", oof_ols), ("LightGBM", oof_lgb)):
            err = pred - y
            out.append({"model": model, "features": name,
                        "R2_log": 1 - np.sum(err ** 2) / np.sum((y - y.mean()) ** 2),
                        "MAE_log": float(np.mean(np.abs(err))),
                        "median_abs_pct_error": float(np.median(np.abs(np.expm1(err)))),
                        "n": len(y)})
    return pd.DataFrame(out)


# ─────────────────────────── LightGBM effects ───────────────────────────

def lgb_effects(df: pd.DataFrame, flags: list[str], report_flags: list[str], boot: int = 30,
                seed: int = 0) -> tuple[pd.DataFrame, object]:
    """Out-of-bag counterfactual effects + SHAP, bootstrapped."""
    import lightgbm as lgb

    rng = np.random.default_rng(seed)
    X, cats = lgb_frame(df, flags)
    y = df.log_price.values
    n = len(df)
    draws = {f: [] for f in report_flags}
    eur_draws = {f: [] for f in report_flags}
    params = dict(LGB_PARAMS, n_estimators=500)
    for b in range(boot):
        idx = rng.integers(0, n, n)
        oob = np.setdiff1d(np.arange(n), idx)
        g = lgb.LGBMRegressor(**dict(params, random_state=b)).fit(X.iloc[idx], y[idx])
        Xo = X.iloc[oob]
        for f in report_flags:
            t = Xo.index[Xo[f] == 1]
            if len(t) < 5:
                continue
            X1 = Xo.loc[t]
            X0 = X1.copy()
            X0[f] = 0
            p1, p0 = g.predict(X1), g.predict(X0)
            delta = p1 - p0
            draws[f].append(float(np.mean(delta)))
            eur_draws[f].append(float(np.mean(np.exp(p0) * np.expm1(delta))))
    full = lgb.LGBMRegressor(**LGB_PARAMS).fit(X, y)
    contrib = full.predict(X, pred_contrib=True)
    cols = list(X.columns)
    rows = []
    for f in report_flags:
        dr = np.array(draws[f])
        er = np.array(eur_draws[f])
        n_t = int(df[f].sum())
        row = {"flag": f, "n_faulty": n_t}
        if len(dr) >= max(5, boot // 2):
            row.update(lgb_pct=np.expm1(np.median(dr)), lgb_pct_lo=np.expm1(np.percentile(dr, 2.5)),
                       lgb_pct_hi=np.expm1(np.percentile(dr, 97.5)), lgb_eur=float(np.median(er)),
                       lgb_eur_lo=float(np.percentile(er, 2.5)), lgb_eur_hi=float(np.percentile(er, 97.5)))
        j = cols.index(f)
        on = df[f].values == 1
        if on.any() and (~on).any():
            row["shap_pct"] = np.expm1(contrib[on, j].mean() - contrib[~on, j].mean())
        rows.append(row)
    return pd.DataFrame(rows), full


# ─────────────────────────── matching ───────────────────────────

def matched_effects(df: pd.DataFrame, report_flags: list[str], boot: int = 500, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    d = df.copy()
    d["km_band"] = (d.km // 50_000).fillna(-1)
    cell = d.make_model + "|" + d.year.astype(str) + "|" + d.fuel + "|" + d.gear + "|" + d.km_band.astype(str)
    d["cell"] = cell
    clean = d[d.any_fault == 0]
    rows = []
    for f in report_flags:
        others = [c for c in MATCH_FAULTS if c != f]
        if f.startswith("light_"):
            others = [c for c in others if c != "warning_light_any"]
        t = d[(d[f] == 1) & (d[others].max(axis=1) == 0)]
        if f.startswith("light_"):
            # only this light type, no other light type
            other_lights = [c for c in LIGHT_TYPES if c != f]
            t = t[t[other_lights].max(axis=1) == 0]
        c_stats = clean.groupby("cell").log_price.agg(["mean", "count"])
        t_stats = t.groupby("cell").log_price.agg(["mean", "count"])
        j = t_stats.join(c_stats, lsuffix="_t", rsuffix="_c", how="inner")
        row = {"flag": f, "match_cells": len(j), "match_n_faulty": int(j.count_t.sum()) if len(j) else 0}
        if row["match_n_faulty"] >= MIN_N:
            diff = (j.mean_t - j.mean_c).values
            w = j.count_t.values.astype(float)
            est = np.sum(w * diff) / w.sum()
            bs = []
            for _ in range(boot):
                k = rng.integers(0, len(j), len(j))
                bs.append(np.sum(w[k] * diff[k]) / w[k].sum())
            base = float(np.exp(j.mean_c).median())
            row.update(match_pct=np.expm1(est), match_pct_lo=np.expm1(np.percentile(bs, 2.5)),
                       match_pct_hi=np.expm1(np.percentile(bs, 97.5)), match_eur=base * np.expm1(est))
        rows.append(row)
    return pd.DataFrame(rows)


# ─────────────────────────── segments ───────────────────────────

def segment_effects(df: pd.DataFrame, overall: pd.DataFrame) -> pd.DataFrame:
    segs = df.segment.value_counts()
    segs = segs[segs >= MIN_SEG_SIZE].index.tolist()
    d, med = fill_numeric(df)
    Xc, _ = controls(d)
    rows = []
    for f in SEG_FLAGS:
        spec = SPEC_A if f == "warning_light_any" else SPEC_B
        base = pd.concat([Xc, d[spec].astype(float)], axis=1)
        eligible, counts = [], {}
        for s in segs:
            ins = d.segment == s
            nt, nc = int((ins & (d[f] == 1)).sum()), int((ins & (d[f] == 0)).sum())
            counts[s] = (nt, nc, int(ins.sum()))
            if nt >= MIN_N_SEG and nc >= 30:
                eligible.append(s)
        inter = pd.DataFrame({f"{f}*{s}": d[f] * (d.segment == s) for s in eligible}, index=d.index)
        X = pd.concat([base, inter], axis=1)
        m = FEOLS(cov="hc1").fit(X, d.log_price, d.make_model)
        used = d.loc[m.used_index]
        yhat = m.predict_log(X.loc[m.used_index], used.make_model)
        b0 = m.beta.get(f, np.nan)
        thetas = {}
        for s in eligible:
            col = f"{f}*{s}"
            if col not in m.beta.index:
                continue
            th = b0 + m.beta[col]
            var = m.cov.loc[f, f] + m.cov.loc[col, col] + 2 * m.cov.loc[f, col]
            thetas[s] = (th, np.sqrt(var))
        # Empirical-Bayes shrinkage toward the pooled effect.
        if len(thetas) >= 3:
            th = np.array([v[0] for v in thetas.values()])
            se2 = np.array([v[1] ** 2 for v in thetas.values()])
            tau2 = max(0.0, float(np.var(th, ddof=1) - se2.mean()))
        else:
            tau2 = 0.0
        ov = overall.set_index("flag")
        pooled = ov.loc[f, "b"] if f in ov.index else b0
        for s in segs:
            nt, nc, ntot = counts[s]
            row = {"flag": f, "segment": s, "n_segment": ntot, "n_faulty": nt}
            if s in thetas:
                th, se = thetas[s]
                wgt = tau2 / (tau2 + se ** 2) if tau2 > 0 else 0.0
                shr = pooled + wgt * (th - pooled)
                treated = (used.segment == s) & (used[f] == 1)
                p0 = np.exp(yhat[treated] - th) * m.smear
                row.update(pct=np.expm1(th), pct_lo=np.expm1(th - 1.96 * se), pct_hi=np.expm1(th + 1.96 * se),
                           pct_shrunk=np.expm1(shr), clean_price_median=float(np.median(p0)),
                           eur=float(np.median(p0) * np.expm1(th)), eur_shrunk=float(np.median(p0) * np.expm1(shr)))
            rows.append(row)
    return pd.DataFrame(rows)


# ─────────────────────────── robustness ───────────────────────────

ROBUST_FLAGS = ["warning_light_any", "light_engine", "timing_belt_due", "gearbox_issue", "clutch_issue",
                "engine_major", "non_runner", "rust_severe", "crash_damage", "inspection_failed",
                "windshield_crack"]


def robustness(df: pd.DataFrame) -> pd.DataFrame:
    variants = {
        "main (all auctions with >=1 bid, price >= 100 €)": (df, "make_model"),
        "accepted sales only": (df[df.accepted == 1], "make_model"),
        ">= 10 bids": (df[df.bid_count.fillna(0) >= 10], "make_model"),
        "price >= 500 €": (df[df.price >= 500], "make_model"),
        "model-generation FE": (df, "generation"),
        "dealer-style listings only": (df[df.dealer_style == 1], "make_model"),
        "private-style listings only": (df[df.dealer_style == 0], "make_model"),
    }
    rows = []
    for name, (sub, fe) in variants.items():
        for spec in (SPEC_A, SPEC_B):
            eff, _ = ols_effects(sub, spec, fe_col=fe)
            for _, r in eff[eff.flag.isin(ROBUST_FLAGS)].iterrows():
                if spec is SPEC_B and r.flag == "warning_light_any":
                    continue
                if spec is SPEC_A and r.flag.startswith("light_"):
                    continue
                rows.append({"variant": name, "flag": r.flag, "n_faulty": r.n_faulty, "n_total": r.n_total,
                             "pct": r.get("pct"), "pct_lo": r.get("pct_lo"), "pct_hi": r.get("pct_hi")})
    out = pd.DataFrame(rows).drop_duplicates(["variant", "flag"])
    return out


# ─────────────────────────── main ───────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--boot", type=int, default=30, help="LightGBM bootstrap refits")
    ap.add_argument("--skip-ml", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    paths.ensure_dirs()
    t0 = time.time()

    df = load_huutokaupat()
    log.info("Huutokaupat analysis sample: %d cars, %d make×models", len(df), df.make_model.nunique())

    eff_a, m_a = ols_effects(df, SPEC_A)
    eff_b, m_b = ols_effects(df, SPEC_B)
    log.info("OLS done (%.0fs): n=%d groups=%d", time.time() - t0, m_b.n, m_b.n_groups)
    overall = pd.concat([eff_a[eff_a.flag == "warning_light_any"],
                         eff_b[eff_b.flag != "warning_light_any"]], ignore_index=True)
    overall.insert(1, "spec", np.where(overall.flag == "warning_light_any", "A", "B"))

    report_flags = [f for f in overall.flag if df[f].sum() >= MIN_N]
    if not args.skip_ml:
        cv = cross_validate(df, SPEC_B)
        cv.to_csv(paths.REPORTS / "model_cv.csv", index=False)
        log.info("CV done (%.0fs)\n%s", time.time() - t0, cv.round(3).to_string(index=False))
        lgb_b, full_b = lgb_effects(df, SPEC_B, [f for f in report_flags if f != "warning_light_any"], boot=args.boot)
        lgb_a, _ = lgb_effects(df, SPEC_A, ["warning_light_any"], boot=args.boot)
        lgbe = pd.concat([lgb_a, lgb_b], ignore_index=True).drop(columns="n_faulty")
        overall = overall.merge(lgbe, on="flag", how="left")
        full_b.booster_.save_model(str(paths.MODEL_DIR / "lgbm_specB.txt"))
        log.info("LightGBM effects done (%.0fs)", time.time() - t0)
    match = matched_effects(df, report_flags)
    overall = overall.merge(match, on="flag", how="left")
    overall["label"] = overall.flag.map(F.LABELS)
    overall["enough_data"] = overall.n_faulty >= MIN_N
    overall.to_csv(paths.REPORTS / "effects_overall.csv", index=False)

    seg = segment_effects(df, overall)
    seg.to_csv(paths.REPORTS / "effects_by_segment.csv", index=False)
    log.info("segments done (%.0fs)", time.time() - t0)

    rob = robustness(df)
    rob.to_csv(paths.REPORTS / "robustness.csv", index=False)
    log.info("robustness done (%.0fs)", time.time() - t0)

    with open(paths.MODEL_DIR / "ols.pkl", "wb") as fh:
        pickle.dump({"A": strip(m_a), "B": strip(m_b)}, fh)

    meta = json.loads((paths.DATA / "features_meta.json").read_text(encoding="utf-8"))
    meta.update(analysis_n=int(len(df)), make_models=int(df.make_model.nunique()),
                ols_n=int(m_b.n), ols_groups=int(m_b.n_groups),
                price_median=float(df.price.median()), accepted_share=float(df.accepted.mean()))

    # Secondary: Nettiauto asking prices (text-only flags), if collected.
    if paths.FEATURES_NA.exists():
        na = load_nettiauto()
        if len(na) >= 200:
            spec_na = ["warning_light_any"] + [f for f in TEXT_MODEL_FLAGS if f in na]
            eff_na, m_na = ols_effects(na, spec_na)
            eff_na["label"] = eff_na.flag.map(F.LABELS)
            eff_na["enough_data"] = eff_na.n_faulty >= MIN_N
            eff_na.to_csv(paths.REPORTS / "effects_nettiauto.csv", index=False)
            meta.update(nettiauto_n=int(len(na)), nettiauto_ols_n=int(m_na.n))
    (paths.REPORTS / "run_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    log.info("all done in %.0fs", time.time() - t0)


def strip(m: FEOLS) -> dict:
    return {"beta": m.beta, "cov": m.cov, "fe": m.fe, "smear": m.smear, "medians": m.medians,
            "levels": m.levels, "flags": m.flags, "cols": m.cols}


if __name__ == "__main__":
    main()
