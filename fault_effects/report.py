"""Turn the model outputs into reports/fault_effects.md (+ the CSVs next to it).

    python -m fault_effects.report
"""

from __future__ import annotations

import json
import math

import pandas as pd

from fault_effects import faults as F
from fault_effects import model as M
from fault_effects import paths

HEADLINE = [
    "warning_light_any", "light_engine", "light_abs_esp", "light_airbag", "light_oil", "light_gearbox",
    "light_brake", "light_coolant", "light_dpf", "light_glow_plug", "light_tpms", "light_service", "light_bulb",
    "light_unspecified", "engine_major", "gearbox_issue", "non_runner", "clutch_issue", "engine_running_issue",
    "timing_belt_due", "timing_chain_issue", "steering_issue", "not_roadworthy", "inspection_lapsed",
    "inspection_failed", "rust_severe", "rust_cosmetic", "crash_damage", "windshield_crack", "ac_issue",
    "project_for_parts",
]
SEG_MATRIX = ["warning_light_any", "light_engine", "rust_severe", "rust_cosmetic", "windshield_crack",
              "inspection_lapsed", "not_roadworthy", "gearbox_issue", "clutch_issue", "engine_major"]
SHORT = {
    "warning_light_any": "any light", "light_engine": "engine light", "rust_severe": "rust (struct.)",
    "rust_cosmetic": "rust (cosm.)", "windshield_crack": "windshield", "inspection_lapsed": "insp. lapsed",
    "not_roadworthy": "not roadworthy", "gearbox_issue": "gearbox", "clutch_issue": "clutch",
    "engine_major": "engine damage",
}


def pct(x) -> str:
    return "–" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x * 100:+.1f}%".replace("-", "−")


def ci(lo, hi) -> str:
    if lo is None or (isinstance(lo, float) and math.isnan(lo)):
        return ""
    return f"[{lo * 100:+.1f}, {hi * 100:+.1f}]".replace("-", "−")


def eur(x) -> str:
    return "–" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:+,.0f} €".replace(",", " ").replace("-", "−")


def eur_ci(lo, hi) -> str:
    if lo is None or (isinstance(lo, float) and math.isnan(lo)):
        return ""
    return f"[{lo:+,.0f}, {hi:+,.0f}]".replace(",", " ").replace("-", "−")


def md_table(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for _, r in df.iterrows():
        lines.append("| " + " | ".join(str(r[c]) for c in cols) + " |")
    return "\n".join(lines)


def effects_table(ov: pd.DataFrame, flags: list[str]) -> pd.DataFrame:
    rows = []
    o = ov.set_index("flag")
    for f in flags:
        if f not in o.index:
            continue
        r = o.loc[f]
        if r.n_faulty < M.MIN_N:
            rows.append({"Fault": F.LABELS.get(f, f), "n faulty": int(r.n_faulty),
                         "Hedonic OLS": "not enough data", "≈ € per car": "", "LightGBM": "",
                         "Matched": "", "Clean price (median)": ""})
            continue
        match = (f"{pct(r.get('match_pct'))} (n={int(r.match_n_faulty)})"
                 if pd.notna(r.get("match_pct")) else f"n/e (n={int(r.get('match_n_faulty', 0) or 0)})")
        rows.append({
            "Fault": F.LABELS.get(f, f),
            "n faulty": int(r.n_faulty),
            "Hedonic OLS": f"**{pct(r.pct)}** {ci(r.pct_lo, r.pct_hi)}",
            "≈ € per car": f"{eur(r.eur)} {eur_ci(r.eur_lo, r.eur_hi)}",
            "LightGBM": f"{pct(r.get('lgb_pct'))} {ci(r.get('lgb_pct_lo'), r.get('lgb_pct_hi'))}",
            "Matched": match,
            "Clean price (median)": f"{r.clean_price_median:,.0f} €".replace(",", " "),
        })
    return pd.DataFrame(rows)


def main() -> None:
    R = paths.REPORTS
    ov = pd.read_csv(R / "effects_overall.csv")
    seg = pd.read_csv(R / "effects_by_segment.csv")
    rob = pd.read_csv(R / "robustness.csv")
    cv = pd.read_csv(R / "model_cv.csv") if (R / "model_cv.csv").exists() else None
    val = pd.read_csv(R / "rule_validation.csv") if (R / "rule_validation.csv").exists() else None
    meta = json.loads((R / "run_meta.json").read_text(encoding="utf-8"))
    na = pd.read_csv(R / "effects_nettiauto.csv") if (R / "effects_nettiauto.csv").exists() else None

    o = ov.set_index("flag")
    wl, el = o.loc["warning_light_any"], o.loc["light_engine"]
    out = []
    out.append("# How much do specific faults lower a used car's price?\n")
    out.append(
        f"Source: **{meta['rows']:,} sold Huutokaupat passenger-car auctions** ({meta['end_min']} – "
        f"{meta['end_max']}); analysis sample **{meta['analysis_n']:,} cars** across "
        f"{meta['make_models']:,} make×model variants (auctions with at least one bid and a final bid ≥ 100 €; "
        f"model years 1990+). Median price {meta['price_median']:,.0f} €; {meta['accepted_share']:.0%} of "
        f"auctions ended with the seller accepting the top bid (the rest still give the market's top bid).\n"
        .replace(",", " "))
    out.append(
        f"**Headline.** A warning light on the seller's checklist is associated with a "
        f"**{pct(wl.pct)} lower price** (95% CI {ci(wl.pct_lo, wl.pct_hi)}, n = {int(wl.n_faulty):,} cars), "
        f"≈ {eur(wl.eur)} per car at these prices. For the **engine / check-engine light** specifically: "
        f"**{pct(el.pct)}** ({ci(el.pct_lo, el.pct_hi)}, n = {int(el.n_faulty):,}), ≈ {eur(el.eur)}. "
        f"Effects are for otherwise comparable cars — same make×model, model year, mileage, power, fuel, "
        f"gearbox, drive and auction month — and hold all other disclosed faults fixed.\n".replace(",", " "))

    out.append("## Main results\n")
    out.append("OLS = hedonic regression on log(price), make×model fixed effects, CIs clustered by make×model. "
               "€ = average euro gap for the faulty cars (their predicted clean price × effect). LightGBM = "
               "out-of-bag counterfactual (flag on vs. off), 30 bootstrap refits. Matched = same make×model, year, "
               "fuel, gearbox and 50 000 km band; cars whose *only* major fault is this one vs. cars with none. "
               f"Below {M.MIN_N} faulty cars a row says *not enough data*.\n")
    out.append(md_table(effects_table(ov, HEADLINE)) + "\n")

    out.append("### Per make / model (largest segments)\n")
    out.append(f"Segment-specific effects from the OLS with fault×segment interactions, shown **shrunk toward "
               f"the overall effect** (empirical Bayes) because single-segment estimates are noisy; the raw "
               f"estimates and CIs are in `effects_by_segment.csv`. `n/e` = fewer than {M.MIN_N_SEG} faulty cars "
               f"in that segment (count in brackets).\n")
    segs = (seg.groupby("segment").n_segment.first().sort_values(ascending=False))
    mat = []
    for s, n in segs.items():
        row = {"Segment": s, "n": int(n)}
        for f in SEG_MATRIX:
            r = seg[(seg.segment == s) & (seg.flag == f)]
            if not len(r):
                row[SHORT[f]] = ""
                continue
            r = r.iloc[0]
            row[SHORT[f]] = (f"{pct(r.pct_shrunk)} ({int(r.n_faulty)})" if pd.notna(r.get("pct_shrunk"))
                             else f"n/e ({int(r.n_faulty)})")
        mat.append(row)
    out.append(md_table(pd.DataFrame(mat)) + "\n")

    out.append("Engine light by segment (raw estimate with 95% CI, then shrunk, and the euro gap at the "
               "segment's typical clean price):\n")
    e = seg[(seg.flag == "light_engine") & seg.pct.notna()].sort_values("n_faulty", ascending=False)
    tab = pd.DataFrame({
        "Segment": e.segment, "n faulty": e.n_faulty.astype(int),
        "Raw": [f"{pct(a)} {ci(b, c)}" for a, b, c in zip(e.pct, e.pct_lo, e.pct_hi)],
        "Shrunk": [pct(x) for x in e.pct_shrunk],
        "≈ € (shrunk)": [eur(x) for x in e.eur_shrunk],
        "Clean price": [f"{x:,.0f} €".replace(",", " ") for x in e.clean_price_median],
    })
    out.append(md_table(tab) + "\n")

    out.append("## Robustness\n")
    out.append("Same OLS on different samples / fixed effects. If a number moves a lot here, don't quote it.\n")
    piv = rob.assign(v=[f"{pct(p)}" if n >= M.MIN_N else "n/e" for p, n in zip(rob.pct, rob.n_faulty)])
    piv = piv.pivot_table(index="flag", columns="variant", values="v", aggfunc="first")
    piv = piv.reindex([f for f in M.ROBUST_FLAGS if f in piv.index])
    piv.index = [F.LABELS.get(f, f) for f in piv.index]
    piv = piv.reset_index().rename(columns={"index": "Fault"})
    out.append(md_table(piv) + "\n")

    if cv is not None:
        out.append("## Out-of-sample fit (5-fold CV)\n")
        out.append("Predicting log(price) of held-out auctions. Adding the fault flags is what this project "
                   "contributes; the gain is measured out of sample.\n")
        t = cv.assign(**{"R² (log price)": cv.R2_log.round(3), "MAE (log)": cv.MAE_log.round(3),
                         "Median abs. % error": (cv.median_abs_pct_error * 100).round(1).astype(str) + "%"})
        out.append(md_table(t[["model", "features", "R² (log price)", "MAE (log)", "Median abs. % error"]]) + "\n")

    if val is not None:
        out.append("## How good are the fault flags?\n")
        out.append("Rules were checked by hand on fresh random samples drawn *after* the last rule change "
                   "(a first development round was used only to fix rules). Precision = share of flagged "
                   "listings that really have the fault (20 checked). Recall is estimated from 15 unflagged "
                   "listings that mention the topic's keyword stem, so its interval is wide. Missed faults sit in "
                   "the 'clean' group and bias effects **toward zero** — the estimates above are, if anything, "
                   "conservative. Light types are classified within the seller's 'yes, a light is on' answer.\n")
        t = pd.DataFrame({
            "Flag": val.label, "n flagged": val.n_flagged,
            "Precision": [f"{p:.0%} [{lo:.0%}, {hi:.0%}]" for p, lo, hi in
                          zip(val.precision, val.precision_lo, val.precision_hi)],
            "Recall (est.)": [("≈100% (no unflagged mentions)" if s == 0 else
                               f"{r:.0%} [{lo:.0%}, {hi:.0%}]") for r, lo, hi, s in
                              zip(val.recall_est, val.recall_lo, val.recall_hi, val.stem_unflagged)],
        })
        out.append(md_table(t) + "\n")

    if na is not None:
        n_na = meta.get("nettiauto_n", 0)
        out.append("## Cross-check on Nettiauto asking prices\n")
        out.append(f"{n_na:,} private-seller listings under 5 000 € (the watcher's saved search), flags from the "
                   "free-text description only (no checklist). Asking prices, not sale prices, and the 5 000 € "
                   "cap truncates clean cars, which pulls effects toward zero.\n".replace(",", " "))
        t = effects_table(na.assign(match_pct=float("nan"), match_n_faulty=0, lgb_pct=float("nan")),
                          ["warning_light_any", "engine_major", "gearbox_issue", "clutch_issue", "non_runner",
                           "not_roadworthy", "inspection_lapsed", "rust_severe", "rust_cosmetic",
                           "crash_damage", "timing_belt_due", "windshield_crack"])
        out.append(md_table(t.drop(columns=["LightGBM", "Matched"])) + "\n")

    out.append("## How to read this — and what it is not\n")
    out.append(
        "- **Associations, not repair quotes.** A coefficient says how much less bidders paid for cars that "
        "disclosed the fault than for comparable cars that did not. It mixes the expected repair cost with "
        "risk (an unknown cause behind an engine light) and anything else correlated with disclosure.\n"
        "- **Disclosure-based.** Faults are what sellers wrote. The checklist question 'is any warning light "
        "on?' is asked of every seller, which makes the light results the cleanest; free-text faults depend on "
        "how carefully a seller writes.\n"
        "- **Auction market.** Huutokaupat buyers are mostly bargain hunters and traders; dealer retail prices "
        "react differently. Euro figures are at the prices of the cars that actually had the fault (cheap, old, "
        "high-mileage), so scale them by percentage for a pricier car.\n"
        "- **Small effects are not zero effects.** For rows near 0 % the CI is the answer: e.g. a TPMS light "
        "costs little or nothing on average.\n"
        "- **Incremental coefficients.** Each flag is estimated holding the others fixed (e.g. 'inspection "
        "failed' vs. 'inspection lapsed' are separate groups). 'Emissions system modified' and some "
        "paperwork flags are controls; their coefficients pick up which kinds of cars carry them and should "
        "not be read as causal.\n")
    (R / "fault_effects.md").write_text("\n".join(out), encoding="utf-8")
    print(f"wrote {R / 'fault_effects.md'}")


if __name__ == "__main__":
    main()
