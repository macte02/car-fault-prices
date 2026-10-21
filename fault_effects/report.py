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
    "light_unspecified", "engine_failure", "engine_knock", "gearbox_issue", "non_runner", "clutch_issue",
    "engine_running_issue", "timing_belt_due", "timing_chain_issue", "steering_issue", "not_roadworthy",
    "inspection_lapsed", "inspection_failed", "rust_severe", "rust_cosmetic", "crash_damage", "windshield_crack",
    "ac_issue", "project_for_parts",
]
BAND_FLAGS = ["warning_light_any", "light_engine", "light_abs_esp", "light_airbag", "engine_failure", "engine_knock",
              "gearbox_issue", "clutch_issue", "non_runner", "engine_running_issue", "not_roadworthy",
              "inspection_lapsed", "inspection_failed", "rust_severe", "rust_cosmetic", "windshield_crack"]
SEG_MATRIX = ["warning_light_any", "light_engine", "rust_severe", "rust_cosmetic", "windshield_crack",
              "inspection_lapsed", "not_roadworthy", "gearbox_issue", "clutch_issue", "engine_failure"]
SHORT = {
    "warning_light_any": "any light", "light_engine": "engine light", "rust_severe": "rust (struct.)",
    "rust_cosmetic": "rust (cosm.)", "windshield_crack": "windshield", "inspection_lapsed": "insp. lapsed",
    "not_roadworthy": "not roadworthy", "gearbox_issue": "gearbox", "clutch_issue": "clutch",
    "engine_failure": "engine failure",
}
MINUS = "−"
NBSP = " "   # thin no-break space as thousands separator


def _nan(x) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))


def num(x: float, signed: bool = False) -> str:
    s = f"{x:+,.0f}" if signed else f"{x:,.0f}"
    return s.replace(",", NBSP).replace("-", MINUS)


def pct(x) -> str:
    return "–" if _nan(x) else f"{x * 100:+.1f}%".replace("-", MINUS)


def ci(lo, hi) -> str:
    return "" if _nan(lo) else f"[{lo * 100:+.1f}, {hi * 100:+.1f}]".replace("-", MINUS)


def eur(x) -> str:
    return "–" if _nan(x) else f"{num(x, True)} €"


def eur_ci(lo, hi) -> str:
    return "" if _nan(lo) else f"[{num(lo, True)}, {num(hi, True)}]"


def md_table(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for _, r in df.iterrows():
        lines.append("| " + " | ".join(str(r[c]) for c in cols) + " |")
    return "\n".join(lines)


def effects_table(ov: pd.DataFrame, flags: list[str], ml: bool = True) -> pd.DataFrame:
    rows = []
    o = ov.set_index("flag")
    for f in flags:
        if f not in o.index:
            continue
        r = o.loc[f]
        base = {"Fault": F.LABELS.get(f, f), "n faulty": num(r.n_faulty)}
        if r.n_faulty < M.MIN_N:
            rows.append({**base, "This fault (others held fixed)": "not enough data", "≈ €": "",
                         "Total gap of these cars": "", **({"LightGBM": "", "Matched": ""} if ml else {})})
            continue
        row = {**base,
               "This fault (others held fixed)": f"**{pct(r.pct)}** {ci(r.pct_lo, r.pct_hi)}",
               "≈ €": f"{eur(r.eur)} {eur_ci(r.eur_lo, r.eur_hi)}",
               "Total gap of these cars": (f"{pct(r.get('total_pct'))} · {eur(r.get('total_eur'))}"
                                           if not _nan(r.get("total_pct")) else "")}
        if ml:
            row["LightGBM"] = f"{pct(r.get('lgb_pct'))} {ci(r.get('lgb_pct_lo'), r.get('lgb_pct_hi'))}"
            row["Matched"] = (f"{pct(r.get('match_pct'))} (n={num(r.match_n_faulty)})"
                              if not _nan(r.get("match_pct")) else f"n/e (n={num(r.get('match_n_faulty') or 0)})")
        rows.append(row)
    return pd.DataFrame(rows)


def band_table(bands: pd.DataFrame, value: str) -> pd.DataFrame:
    rows = []
    for f in BAND_FLAGS:
        row = {"Fault": F.LABELS.get(f, f)}
        for b in M.BAND_LABELS:
            r = bands[(bands.flag == f) & (bands.band == b)]
            if not len(r):
                row[b] = ""
                continue
            r = r.iloc[0]
            if r.n_faulty < M.MIN_N_BAND or _nan(r.get("pct")):
                row[b] = f"n/e ({num(r.n_faulty)})"
            elif value == "eur":
                clear = r.eur_hi < 0 or r.eur_lo > 0
                row[b] = (f"**{eur(r.eur)}** ({num(r.n_faulty)})" if clear
                          else f"{eur(r.eur)} ({num(r.n_faulty)}, n.s.)")
            elif value == "eur_ci":
                row[b] = eur_ci(r.eur_lo, r.eur_hi)
            elif value == "pct":
                row[b] = f"{pct(r.pct)} {ci(r.pct_lo, r.pct_hi)}"
            elif value == "total":
                row[b] = eur(r.get("total_eur"))
        rows.append(row)
    return pd.DataFrame(rows)


def main() -> None:
    R = paths.REPORTS
    ov = pd.read_csv(R / "effects_overall.csv")
    seg = pd.read_csv(R / "effects_by_segment.csv")
    bands = pd.read_csv(R / "effects_by_band.csv")
    rob = pd.read_csv(R / "robustness.csv")
    cv = pd.read_csv(R / "model_cv.csv") if (R / "model_cv.csv").exists() else None
    val = pd.read_csv(R / "rule_validation.csv") if (R / "rule_validation.csv").exists() else None
    meta = json.loads((R / "run_meta.json").read_text(encoding="utf-8"))
    na = pd.read_csv(R / "effects_nettiauto.csv") if (R / "effects_nettiauto.csv").exists() else None

    o = ov.set_index("flag")
    wl, el = o.loc["warning_light_any"], o.loc["light_engine"]
    bwl = bands[bands.flag == "warning_light_any"].set_index("band")
    out = []
    out.append("# How much do specific faults lower a used car's price?\n")
    out.append(
        f"Source: **{num(meta['rows'])} sold Huutokaupat passenger-car auctions** ({meta['end_min']} – "
        f"{meta['end_max']}); analysis sample **{num(meta['analysis_n'])} cars** across {num(meta['make_models'])} "
        f"make×model variants (auctions with at least one bid and a final bid ≥ 100 €; model years 1990+). "
        f"Median price {num(meta['price_median'])} €; {meta['accepted_share']:.0%} of auctions ended with the seller "
        f"accepting the top bid (the rest still give the market's top bid).\n")

    lines = [f"{b}: **{eur(bwl.loc[b, 'eur'])}** ({pct(bwl.loc[b, 'pct'])}, n = {num(bwl.loc[b, 'n_faulty'])})"
             for b in M.BAND_LABELS if b in bwl.index and bwl.loc[b, "n_faulty"] >= M.MIN_N_BAND]
    out.append("**Headline.** A warning light on the seller's checklist costs more euros on a more valuable car "
               "but a smaller share of its price. By the car's clean value: " + "; ".join(lines) +
               f". Pooled over all cars: {pct(wl.pct)} {ci(wl.pct_lo, wl.pct_hi)}. The engine / check-engine "
               f"light alone: {pct(el.pct)} {ci(el.pct_lo, el.pct_hi)} (n = {num(el.n_faulty)}).\n")
    out.append("Every effect compares a car that disclosed the fault with otherwise comparable cars — same "
               "make×model, model year, mileage, power, fuel, gearbox, drive and auction month.\n")

    # ── by value band
    counts = meta.get("band_counts", {})
    out.append("## By car value (€)\n")
    out.append("Cars are banded by their **clean value**: the price LightGBM predicts for that car with every "
               "disclosed fault removed, out-of-fold so a car's own sale price doesn't decide its band (banding on "
               "the sale price would push faulty cars into cheaper bands). LightGBM rather than the hedonic model "
               "because on fault-free cars the hedonic model over-predicts newer, pricier cars by 25–40% in the top "
               "bands, while LightGBM's error is flat across bands. The % effects still come from the hedonic "
               "model; euros = that % × the car's clean value × its other faults' discount. Cars per band: "
               + ", ".join(f"{b} {num(counts.get(b, 0))}" for b in M.BAND_LABELS) + ". "
               f"Each cell is the euro effect of that fault with the other disclosed faults held fixed, and the "
               f"number of faulty cars in the band. **Bold** = the 95% interval excludes zero; `n.s.` = it "
               f"includes zero (no clear effect — small positive numbers in the upper bands are noise, not "
               f"faults that raise the price); `n/e` = fewer than {M.MIN_N_BAND} faulty cars. Same model as the "
               f"main table but with every fault interacted with the band.\n")
    out.append(md_table(band_table(bands, "eur")) + "\n")
    out.append("![Euro effect by clean-value band](fault_effects_bands.png)\n")
    out.append("95% intervals of the euro effects:\n")
    out.append(md_table(band_table(bands, "eur_ci")) + "\n")
    out.append("The same as a percentage of the car's clean price:\n")
    out.append(md_table(band_table(bands, "pct")) + "\n")

    # ── engine vs gearbox
    ef, ek, gb = o.loc["engine_failure"], o.loc["engine_knock"], o.loc["gearbox_issue"]
    out.append("## Why can a gearbox fault look bigger than engine damage?\n")
    out.append(
        "Two different questions give two different numbers:\n\n"
        "- **This fault, others held fixed** (the main column): how much the fault itself moves the price when "
        "everything else the seller disclosed is the same. A car with a failed engine usually *also* gets flagged "
        "\"won't start\", \"not roadworthy\", \"engine light on\" or \"sold for parts\" — those flags take their "
        "own share of the discount, so the engine flag's own coefficient is smaller.\n"
        "- **Total gap of these cars**: the cars that have the fault vs. the same cars with *every* disclosed "
        "fault removed — what a buyer actually sees, including whatever usually comes with the fault (and "
        "also unrelated faults those cars happen to have, so read it as typical, not causal).\n\n"
        f"Engine failure: {pct(ef.pct)} on its own, but these cars sell {pct(ef.total_pct)} "
        f"({eur(ef.total_eur)}) below a clean car; they carry {ef.other_faults_mean:.1f} other fault flags on "
        f"average. Gearbox problem: {pct(gb.pct)} on its own, {pct(gb.total_pct)} ({eur(gb.total_eur)}) in total, "
        f"{gb.other_faults_mean:.1f} other flags. Engine knocking noise: {pct(ek.pct)} on its own, "
        f"{pct(ek.total_pct)} total. In euros, an engine failure on its own costs about as much as a gearbox "
        f"problem ({eur(ef.eur)} vs {eur(gb.eur)}), but together with what usually comes with it much more "
        f"({eur(ef.total_eur)} vs {eur(gb.total_eur)}); it also sits on pricier cars (median clean value "
        f"{num(ef.clean_price_median)} € vs {num(gb.clean_price_median)} €). The two % effects' intervals "
        f"overlap ({ci(ef.pct_lo, ef.pct_hi)} vs {ci(gb.pct_lo, gb.pct_hi)}). "
        "The earlier single \"major engine damage\" flag mixed outright failures with mere knocking noises; "
        "they are now separate.\n")

    out.append("## All faults (pooled over all cars)\n")
    boot = meta.get("lgb_boot", 0)
    out.append("This fault = hedonic OLS on log(price) with make×model fixed effects; 95% CIs use the larger of "
               "make×model-clustered and heteroskedasticity-robust standard errors. ≈ € = that effect on the "
               "faulty cars' own value without this fault (LightGBM clean value, their other faults kept). Total "
               "gap = see the section above. LightGBM = out-of-bag "
               f"counterfactual (flag on vs. off), {boot} bootstrap refits. Matched = same make×model, year, fuel, "
               "gearbox and 50 000 km band; cars whose *only* major fault is this one vs. cars with none. "
               f"Below {M.MIN_N} faulty cars a row says *not enough data*. A pooled % hides that the euro "
               "effect grows with the car's value — use the band tables for euros.\n")
    out.append("![Pooled % effects with 95% CIs](fault_effects.png)\n")
    out.append(md_table(effects_table(ov, HEADLINE)) + "\n")

    out.append("### Per make / model (largest segments)\n")
    out.append(f"Segment-specific % effects from the OLS with fault×segment interactions, shown **shrunk toward "
               f"the overall effect** (empirical Bayes) because single-segment estimates are noisy; raw estimates "
               f"and CIs are in `effects_by_segment.csv`. `n/e` = fewer than {M.MIN_N_SEG} faulty cars in that "
               f"segment (count in brackets).\n")
    segs = seg.groupby("segment").n_segment.first().sort_values(ascending=False)
    mat = []
    for s, n in segs.items():
        row = {"Segment": s, "n": num(n)}
        for f in SEG_MATRIX:
            r = seg[(seg.segment == s) & (seg.flag == f)]
            if not len(r):
                row[SHORT[f]] = ""
                continue
            r = r.iloc[0]
            row[SHORT[f]] = (f"{pct(r.pct_shrunk)} ({num(r.n_faulty)})" if not _nan(r.get("pct_shrunk"))
                             else f"n/e ({num(r.n_faulty)})")
        mat.append(row)
    out.append(md_table(pd.DataFrame(mat)) + "\n")

    out.append("Engine light by segment (raw estimate with 95% CI, then shrunk, and the euro gap at the "
               "segment's typical clean price):\n")
    e = seg[(seg.flag == "light_engine") & seg.pct.notna()].sort_values("n_faulty", ascending=False)
    tab = pd.DataFrame({
        "Segment": e.segment, "n faulty": [num(x) for x in e.n_faulty],
        "Raw": [f"{pct(a)} {ci(b, c)}" for a, b, c in zip(e.pct, e.pct_lo, e.pct_hi)],
        "Shrunk": [pct(x) for x in e.pct_shrunk],
        "≈ € (shrunk)": [eur(x) for x in e.eur_shrunk],
        "Clean price": [f"{num(x)} €" for x in e.clean_price_median],
    })
    out.append(md_table(tab) + "\n")

    out.append("## Robustness\n")
    out.append("Same OLS on different samples / fixed effects (% effect of the fault, others held fixed). If a "
               "number moves a lot here, don't quote it.\n")
    piv = rob.assign(v=[pct(p) if n >= M.MIN_N else "n/e" for p, n in zip(rob.pct, rob.n_faulty)])
    piv = piv.pivot_table(index="flag", columns="variant", values="v", aggfunc="first")
    piv = piv.reindex([f for f in M.ROBUST_FLAGS if f in piv.index])
    piv.index = [F.LABELS.get(f, f) for f in piv.index]
    out.append(md_table(piv.reset_index().rename(columns={"index": "Fault"})) + "\n")

    if cv is not None:
        out.append("## Out-of-sample fit (5-fold CV)\n")
        out.append("Predicting log(price) of held-out auctions; the gain from adding the fault flags is measured "
                   "out of sample.\n")
        t = cv.assign(**{"R² (log price)": cv.R2_log.round(3), "MAE (log)": cv.MAE_log.round(3),
                         "Median abs. % error": (cv.median_abs_pct_error * 100).round(1).astype(str) + "%"})
        out.append(md_table(t[["model", "features", "R² (log price)", "MAE (log)", "Median abs. % error"]]) + "\n")

    if val is not None:
        out.append("## How good are the fault flags?\n")
        out.append("Rules were checked by hand on fresh random samples drawn *after* each rule's last change "
                   "(a first development round only fixed rules). Precision = share of flagged listings that "
                   "really have the fault (20 checked). Recall is estimated from 15 unflagged listings that "
                   "mention the topic's keyword stem, so its interval is wide. Missed faults sit in the 'clean' "
                   "group and bias effects **toward zero**. Light types are classified within the seller's 'yes, "
                   "a light is on' answer. Engine failure and knock are the two halves of the validated "
                   "engine-damage rule. After the last check, a few fixes only *removed* matches (negations such "
                   "as 'ruoste ei ole mennyt läpi', a cracked rear window, ad wording like 'xenon-ajovalot'), so "
                   "for structural rust, windshield and light types the precision shown is a lower bound.\n")
        t = pd.DataFrame({
            "Flag": val.label, "n flagged": [num(x) for x in val.n_flagged],
            "Precision": [f"{p:.0%} [{lo:.0%}, {hi:.0%}]" for p, lo, hi in
                          zip(val.precision, val.precision_lo, val.precision_hi)],
            "Recall (est.)": [("≈100% (no unflagged mentions)" if s == 0 else f"{r:.0%} [{lo:.0%}, {hi:.0%}]")
                              for r, lo, hi, s in zip(val.recall_est, val.recall_lo, val.recall_hi,
                                                      val.stem_unflagged)],
        })
        out.append(md_table(t) + "\n")

    if na is not None:
        out.append("## Cross-check on Nettiauto asking prices\n")
        out.append(f"{num(meta.get('nettiauto_n', 0))} private-seller listings under 5 000 € (the watcher's saved "
                   "search), flags from the free-text description only (no checklist). Asking prices, not sale "
                   "prices, and the 5 000 € cap truncates clean cars, which pulls effects toward zero.\n")
        t = effects_table(na, ["warning_light_any", "engine_failure", "gearbox_issue", "clutch_issue",
                               "non_runner", "not_roadworthy", "inspection_lapsed", "rust_severe", "rust_cosmetic",
                               "crash_damage", "timing_belt_due", "windshield_crack"], ml=False)
        out.append(md_table(t) + "\n")

    out.append("## How to read this — and what it is not\n")
    out.append(
        "- **Associations, not repair quotes.** An effect says how much less bidders paid for cars that disclosed "
        "the fault than for comparable cars that did not. It mixes the expected repair cost with risk (an "
        "unknown cause behind an engine light) and anything else correlated with disclosure.\n"
        "- **Disclosure-based.** Faults are what sellers wrote. The checklist question 'is any warning light on?' "
        "is asked of every seller, which makes the light results the cleanest; free-text faults depend on how "
        "carefully a seller writes.\n"
        "- **Auction market.** Huutokaupat buyers are mostly bargain hunters and traders; dealer retail prices "
        "react differently. Few cars are worth over 20 000 € here, so the top band is thin.\n"
        "- **Small effects are not zero effects.** Near 0 the interval is the answer: e.g. a TPMS light costs "
        "little or nothing on its own.\n"
        "- **Controls, not faults.** 'Emissions system modified' and paperwork flags (import, one key, no "
        "service book, …) are controls; their coefficients pick up which kinds of cars carry them.\n")
    (R / "fault_effects.md").write_text("\n".join(out), encoding="utf-8")
    print(f"wrote {R / 'fault_effects.md'}")


if __name__ == "__main__":
    main()
