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
    "timing_belt_due", "timing_chain_issue", "gearbox_issue", "clutch_issue", "engine_failure", "engine_knock",
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
MATCH_FAULTS = ["warning_light_any", "timing_belt_due", "gearbox_issue", "clutch_issue", "engine_failure",
                "engine_knock",
                "engine_running_issue", "non_runner", "not_roadworthy", "inspection_lapsed",
                "inspection_failed", "rust_severe", "crash_damage", "windshield_crack", "project_for_parts",
                "water_ingress", "coolant_issue", "dpf_issue"]

SEG_FLAGS = ["warning_light_any", "light_engine", "light_abs_esp", "light_airbag", "light_dpf",
             "light_glow_plug", "timing_belt_due", "gearbox_issue", "clutch_issue", "engine_failure",
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

    Standard errors (cov="max", the default) are the larger of the make×model-
    clustered and the heteroskedasticity-robust (HC1) ones, per coefficient.
    Clustering is the right default when a flag varies across hundreds of
    make×models, but for a term identified inside one or a few FE groups
    (segment or price-band interactions) the within-cluster score of that term
    is ~0 by construction and a clustered SE collapses; HC1 then binds.
    `self.covs` keeps both matrices so derived quantities can take the larger.
    """

    def __init__(self, cov: str = "max"):
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
        self.cols = list(Xd.columns)
        ols = sm.OLS(yd.values, Xd.values)
        fits = []
        if self.cov_type in ("cluster", "max"):
            fits.append(ols.fit(cov_type="cluster", cov_kwds={"groups": codes}))
        if self.cov_type in ("hc1", "max"):
            fits.append(ols.fit(cov_type="HC1"))
        self.res = fits[0]
        self.beta = pd.Series(self.res.params, index=self.cols)
        self.covs = [pd.DataFrame(f.cov_params(), index=self.cols, columns=self.cols) for f in fits]
        se = np.max([f.bse for f in fits], axis=0)
        self.se = pd.Series(se, index=self.cols)
        # Covariance whose diagonal matches the reported SEs (correlations from the first fit).
        c0 = self.covs[0].values
        d0 = np.sqrt(np.clip(np.diag(c0), 1e-30, None))
        corr = c0 / np.outer(d0, d0)
        self.cov = pd.DataFrame(corr * np.outer(se, se), index=self.cols, columns=self.cols)
        from scipy.stats import norm
        self.pvalues = pd.Series(2 * norm.sf(np.abs(self.beta.values / se)), index=self.cols)
        fe = (y - X[self.cols] @ self.beta).groupby(g.values).mean()
        self.fe = fe.to_dict()
        resid = y - (X[self.cols] @ self.beta + g.map(self.fe))
        self.smear = float(np.mean(np.exp(resid)))
        self.n, self.n_groups = len(y), g.nunique()
        self.used_index = y.index
        return self

    def lin_se(self, w: pd.Series) -> float:
        """SE of the linear combination w·β — the larger across covariance estimators."""
        idx = list(w.index)
        return float(max(np.sqrt(w.values @ C.loc[idx, idx].values @ w.values) for C in self.covs))

    def predict_log(self, X: pd.DataFrame, g: pd.Series, fallback: float | None = None) -> pd.Series:
        fe = g.map(self.fe)
        if fallback is not None:
            fe = fe.fillna(fallback)
        return X.reindex(columns=self.cols, fill_value=0.0) @ self.beta + fe


def ols_effects(df: pd.DataFrame, flags: list[str], fe_col: str = "make_model",
                clean: pd.Series | None = None) -> tuple[pd.DataFrame, FEOLS]:
    d, med = fill_numeric(df)
    Xc, lv = controls(d)
    X = pd.concat([Xc, d[flags].astype(float)], axis=1)
    m = FEOLS().fit(X, d.log_price, d[fe_col])
    m.medians, m.levels, m.flags = med, lv, flags
    used = d.loc[m.used_index]
    Xu = X.loc[m.used_index]
    yhat = m.predict_log(Xu, used[fe_col])
    fcols = [c for c in flags if c in m.beta.index and c not in NON_FAULTS]
    tot = pd.Series(used[fcols].values @ m.beta[fcols].values, index=used.index)
    clean_u = clean_prices(m, used, yhat, tot, clean)
    full = clean_u * np.exp(tot)          # each car's expected price as it is (all its faults)
    rows = []
    for f in flags:
        treated = used[f] == 1
        n_t = int(treated.sum())
        row = {"flag": f, "n_faulty": n_t, "n_total": int(len(used))}
        if f in m.beta.index and n_t > 0:
            b, se = m.beta[f], m.se[f]
            p0 = full[treated] * np.exp(-b)  # the same cars with only this fault removed
            row.update(b=b, se=se, p=float(m.pvalues[f]),
                       pct=np.expm1(b), pct_lo=np.expm1(b - 1.96 * se), pct_hi=np.expm1(b + 1.96 * se),
                       clean_price_median=float(np.median(p0)), actual_price_median=float(used.price[treated].median()),
                       eur=float(np.mean(p0) * np.expm1(b)),
                       eur_lo=float(np.mean(p0) * np.expm1(b - 1.96 * se)),
                       eur_hi=float(np.mean(p0) * np.expm1(b + 1.96 * se)))
            if f not in NON_FAULTS:
                row.update(total_discount(m, used.loc[treated, fcols], fcols, clean_u[treated]))
        rows.append(row)
    return pd.DataFrame(rows), m


def clean_prices(m: "FEOLS", used: pd.DataFrame, yhat: pd.Series, tot: pd.Series,
                 clean: pd.Series | None) -> pd.Series:
    """Expected price of each car with every disclosed fault removed.

    With `clean` (the LightGBM out-of-fold clean value) the euro conversion uses
    the better-calibrated model: the hedonic OLS over-predicts newer, pricier
    cars (one set of year dummies and one mileage curve for every model), by
    ~25–40% in the top value bands. Without it, the OLS fit is used."""
    if clean is not None:
        c = clean.reindex(used.index)
        return c.fillna(np.exp(yhat - tot) * m.smear)
    return np.exp(yhat - tot) * m.smear


# Flags that describe the car / paperwork rather than a fault; they stay part
# of the "clean" price when computing a total discount.
NON_FAULTS = set(OTHER_FLAGS)


def total_discount(m: "FEOLS", T: pd.DataFrame, coef_cols: list[str], clean: pd.Series) -> dict:
    """Total discount of these cars vs. the same cars with *every* disclosed
    fault removed: mean of Σ_k β_k·x_ik, delta-method CI (gradient = mean x).
    T's columns are the fault indicators, in the same order as coef_cols;
    `clean` is each car's price with every fault removed."""
    tot_i = T.values @ m.beta[coef_cols].values
    tot = float(tot_i.mean())
    tse = m.lin_se(pd.Series(T.values.mean(axis=0), index=coef_cols))
    clean = clean.values
    return dict(total_pct=np.expm1(tot), total_pct_lo=np.expm1(tot - 1.96 * tse),
                total_pct_hi=np.expm1(tot + 1.96 * tse),
                total_eur=float(np.mean(clean * np.expm1(tot_i))),
                total_eur_lo=float(np.mean(clean) * np.expm1(tot - 1.96 * tse)),
                total_eur_hi=float(np.mean(clean) * np.expm1(tot + 1.96 * tse)),
                fully_clean_price_median=float(np.median(clean)),
                other_faults_mean=float(T.values.sum(axis=1).mean() - 1))


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
        m = FEOLS().fit(X, d.log_price, d.make_model)
        used = d.loc[m.used_index]
        yhat = m.predict_log(X.loc[m.used_index], used.make_model)
        fcols = [c for c in list(spec) + list(inter.columns) if c in m.beta.index and c not in NON_FAULTS]
        tot = pd.Series(X.loc[m.used_index, fcols].values @ m.beta[fcols].values, index=used.index)
        full = clean_prices(m, used, yhat, tot, used.get("clean_value")) * np.exp(tot)
        b0 = m.beta.get(f, np.nan)
        thetas = {}
        for s in eligible:
            col = f"{f}*{s}"
            if col not in m.beta.index:
                continue
            th = b0 + m.beta[col]
            thetas[s] = (th, m.lin_se(pd.Series([1.0, 1.0], index=[f, col])))
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
                p0 = full[treated] * np.exp(-th)
                row.update(pct=np.expm1(th), pct_lo=np.expm1(th - 1.96 * se), pct_hi=np.expm1(th + 1.96 * se),
                           pct_shrunk=np.expm1(shr), clean_price_median=float(np.median(p0)),
                           eur=float(np.median(p0) * np.expm1(th)), eur_shrunk=float(np.median(p0) * np.expm1(shr)))
            rows.append(row)
    return pd.DataFrame(rows)


# ─────────────────────────── value bands ───────────────────────────
# A fixed-cost repair is a big share of a 2 000 € car and a small share of a
# 20 000 € one, so a single % does not describe every car. Effects are
# re-estimated per band of each car's *clean* value — its out-of-fold predicted
# price with all faults removed. Banding on the sale price itself would push
# faulty cars into cheaper bands (selection on the outcome).

BANDS = [(0, 1_000, "under 1 000 €"), (1_000, 3_000, "1 000–3 000 €"), (3_000, 5_000, "3 000–5 000 €"),
         (5_000, 10_000, "5 000–10 000 €"), (10_000, 20_000, "10 000–20 000 €"), (20_000, np.inf, "over 20 000 €")]
BAND_LABELS = [b[2] for b in BANDS]
MIN_N_BAND = 20


def clean_value_oof(df: pd.DataFrame, spec: list[str], k: int = 5, seed: int = 7) -> pd.Series:
    """Out-of-fold expected price of each car with every disclosed fault set to 0.

    LightGBM, not the hedonic OLS: on fault-free cars the OLS over-predicts the
    upper value bands (mean log error −0.17 at 5–10k, −0.27 at 10–20k, −0.41
    above 20k) while LightGBM stays flat (≈ −0.11, the mean-vs-median smearing
    gap) in every band. Duan smearing from the out-of-fold residuals."""
    import lightgbm as lgb
    from sklearn.model_selection import KFold

    faults = [c for c in spec if c not in NON_FAULTS]
    X, _ = lgb_frame(df, spec)
    y = df.log_price.values
    clean_log, fit_log = np.zeros(len(df)), np.zeros(len(df))
    for tr, te in KFold(k, shuffle=True, random_state=seed).split(df):
        g = lgb.LGBMRegressor(**LGB_PARAMS).fit(X.iloc[tr], y[tr])
        fit_log[te] = g.predict(X.iloc[te])
        X0 = X.iloc[te].copy()
        X0[faults] = 0
        clean_log[te] = g.predict(X0)
    smear = float(np.mean(np.exp(y - fit_log)))
    out = pd.Series(np.exp(clean_log) * smear, index=df.index)
    out.attrs["smear"] = smear
    return out


def value_band(v: pd.Series) -> pd.Series:
    return pd.cut(v, [b[0] for b in BANDS] + [np.inf], right=False, labels=BAND_LABELS).astype(str)


def band_effects(df: pd.DataFrame) -> pd.DataFrame:
    """Fault effects estimated separately in each clean-value band (fault×band
    interactions in one FE model; controls and admin flags shared)."""
    d, _ = fill_numeric(df)
    Xc, _ = controls(d)
    band_dum = pd.DataFrame({f"band={b}": (d.band == b).astype(float) for b in BAND_LABELS[1:]}, index=d.index)
    rows = []
    for spec, report in ((SPEC_A, ["warning_light_any"]), (SPEC_B, [f for f in SPEC_B if f not in NON_FAULTS])):
        faults = [f for f in spec if f not in NON_FAULTS]
        inter = pd.DataFrame({f"{f}@{b}": d[f].astype(float) * (d.band == b) for f in faults for b in BAND_LABELS},
                             index=d.index)
        X = pd.concat([Xc, band_dum, d[[f for f in spec if f in NON_FAULTS]].astype(float), inter], axis=1)
        m = FEOLS().fit(X, d.log_price, d.make_model)
        used = d.loc[m.used_index]
        yhat = m.predict_log(X.loc[m.used_index], used.make_model)
        icols = [c for c in inter.columns if c in m.beta.index]
        tot = pd.Series(X.loc[m.used_index, icols].values @ m.beta[icols].values, index=used.index)
        clean_u = clean_prices(m, used, yhat, tot, used.get("clean_value"))
        full = clean_u * np.exp(tot)
        for b in BAND_LABELS:
            inb = used.band == b
            cols_b = [f"{f}@{b}" for f in faults if f"{f}@{b}" in m.beta.index]
            base_b = [c.split("@")[0] for c in cols_b]
            for f in report:
                col = f"{f}@{b}"
                t = inb & (used[f] == 1)
                row = {"flag": f, "band": b, "n_band": int(inb.sum()), "n_faulty": int(t.sum())}
                if col in m.beta.index and t.any():
                    bb, se = m.beta[col], m.se[col]
                    p0 = full[t] * np.exp(-bb)
                    row.update(pct=np.expm1(bb), pct_lo=np.expm1(bb - 1.96 * se), pct_hi=np.expm1(bb + 1.96 * se),
                               clean_price_median=float(np.median(p0)),
                               eur=float(np.mean(p0) * np.expm1(bb)),
                               eur_lo=float(np.mean(p0) * np.expm1(bb - 1.96 * se)),
                               eur_hi=float(np.mean(p0) * np.expm1(bb + 1.96 * se)))
                    row.update(total_discount(m, used.loc[t, base_b], cols_b, clean_u[t]))
                rows.append(row)
    out = pd.DataFrame(rows)
    out["enough_data"] = out.n_faulty >= MIN_N_BAND
    return out


# ─────────────────────────── robustness ───────────────────────────

ROBUST_FLAGS = ["warning_light_any", "light_engine", "timing_belt_due", "gearbox_issue", "clutch_issue",
                "engine_failure", "engine_knock", "non_runner", "rust_severe", "crash_damage", "inspection_failed",
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

    # Each car's price with every disclosed fault removed (LightGBM, out-of-fold):
    # used for the value bands and to turn % effects into euros.
    clean = clean_value_oof(df, SPEC_B)
    df["clean_value"] = clean
    df["band"] = value_band(df.clean_value)
    log.info("clean values done (%.0fs): %s", time.time() - t0, df.band.value_counts().to_dict())

    eff_a, m_a = ols_effects(df, SPEC_A, clean=df.clean_value)
    eff_b, m_b = ols_effects(df, SPEC_B, clean=df.clean_value)
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
        with open(paths.MODEL_DIR / "lgbm_specB.pkl", "wb") as fh:
            pickle.dump({"model": full_b, "flags": SPEC_B, "smear": clean.attrs["smear"]}, fh)
        log.info("LightGBM effects done (%.0fs)", time.time() - t0)
    match = matched_effects(df, report_flags)
    overall = overall.merge(match, on="flag", how="left")
    overall["label"] = overall.flag.map(F.LABELS)
    overall["enough_data"] = overall.n_faulty >= MIN_N
    overall.to_csv(paths.REPORTS / "effects_overall.csv", index=False)

    seg = segment_effects(df, overall)
    seg.to_csv(paths.REPORTS / "effects_by_segment.csv", index=False)
    log.info("segments done (%.0fs)", time.time() - t0)

    bands = band_effects(df)
    bands.to_csv(paths.REPORTS / "effects_by_band.csv", index=False)
    log.info("value bands done (%.0fs): %s", time.time() - t0, df.band.value_counts().to_dict())

    rob = robustness(df)
    rob.to_csv(paths.REPORTS / "robustness.csv", index=False)
    log.info("robustness done (%.0fs)", time.time() - t0)

    with open(paths.MODEL_DIR / "ols.pkl", "wb") as fh:
        pickle.dump({"A": strip(m_a), "B": strip(m_b)}, fh)

    meta = json.loads((paths.DATA / "features_meta.json").read_text(encoding="utf-8"))
    meta.update(analysis_n=int(len(df)), make_models=int(df.make_model.nunique()),
                ols_n=int(m_b.n), ols_groups=int(m_b.n_groups),
                price_median=float(df.price.median()), accepted_share=float(df.accepted.mean()),
                lgb_boot=0 if args.skip_ml else args.boot,
                band_counts={b: int((df.band == b).sum()) for b in BAND_LABELS})

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
