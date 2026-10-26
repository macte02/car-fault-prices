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
from fault_effects.chart import BROKEN, LABEL, SEEN

HEADLINE = ["engine_failure", "gearbox_issue", "non_runner", "not_roadworthy", "engine_knock", "rust_severe",
            "inspection_lapsed", "inspection_failed", "light_engine", "engine_running_issue", "clutch_issue",
            "light_abs_esp", "light_airbag", "rust_cosmetic", "windshield_crack", "suspension_issue"]
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


def md_table(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for _, r in df.iterrows():
        lines.append("| " + " | ".join(str(r[c]) for c in cols) + " |")
    return "\n".join(lines)


def cost_cell(r) -> str:
    if r is None or not r.supported:
        return "too few cars"
    if r.eur_hi < 0:
        return f"**{eur(r.eur)}** [{num(r.eur_lo, True)}, {num(r.eur_hi, True)}]"
    return "no measurable cost"


def cost_table(curves: pd.DataFrame, flags: list[str], values: list[float]) -> pd.DataFrame:
    ref = curves[curves.kind == "ref"].set_index(["flag", "value"])
    rows = []
    for f in flags:
        if (f, values[0]) not in ref.index:
            continue
        row = {"Problem": LABEL.get(f, F.LABELS.get(f, f)), "Cars with it": num(ref.loc[(f, values[0]), "n_faulty"])}
        for v in values:
            row[f"car worth {num(v)} €"] = cost_cell(ref.loc[(f, v)] if (f, v) in ref.index else None)
        rows.append(row)
    return pd.DataFrame(rows)


def main() -> None:
    R = paths.REPORTS
    ov = pd.read_csv(R / "effects_overall.csv")
    curves = pd.read_csv(R / "effects_curves.csv")
    seg = pd.read_csv(R / "effects_by_segment.csv")
    rob = pd.read_csv(R / "robustness.csv")
    cv = pd.read_csv(R / "model_cv.csv") if (R / "model_cv.csv").exists() else None
    val = pd.read_csv(R / "rule_validation.csv") if (R / "rule_validation.csv").exists() else None
    meta = json.loads((R / "run_meta.json").read_text(encoding="utf-8"))
    na = pd.read_csv(R / "effects_nettiauto.csv") if (R / "effects_nettiauto.csv").exists() else None
    o = ov.set_index("flag")
    ref = curves[curves.kind == "ref"].set_index(["flag", "value"])

    def at(f, v):
        return ref.loc[(f, v), "eur"] if (f, v) in ref.index else float("nan")

    out = []
    out.append("# How much do specific problems lower a used car's price?\n")
    out.append(
        f"Source: **{num(meta['rows'])} sold Huutokaupat passenger-car auctions** ({meta['end_min']} – "
        f"{meta['end_max']}); analysis sample **{num(meta['analysis_n'])} cars** across {num(meta['make_models'])} "
        f"make×model variants (auctions with at least one bid and a final bid ≥ 100 €; model years 1990+). "
        f"Median price {num(meta['price_median'])} €.\n")
    out.append(
        f"**Headline.** On a car that would be worth 2 000 € without problems, a failed engine takes "
        f"**{eur(at('engine_failure', 2000.0))}** off the auction price, a gearbox problem "
        f"**{eur(at('gearbox_issue', 2000.0))}**, structural rust **{eur(at('rust_severe', 2000.0))}** and an "
        f"engine warning light **{eur(at('light_engine', 2000.0))}**. On a 5 000 € car the same problems cost "
        f"{eur(at('engine_failure', 5000.0))}, {eur(at('gearbox_issue', 5000.0))}, "
        f"{eur(at('rust_severe', 5000.0))} and {eur(at('light_engine', 5000.0))}.\n")

    out.append("## How to read the numbers\n")
    out.append(
        "Every number compares a car that has the problem with otherwise comparable cars that don't — same "
        "make×model, model year, mileage, engine power, fuel, gearbox, drive and auction month.\n\n"
        "- **What's broken** (engine, gearbox, rust, clutch, …) is valued *including what it causes*: a failed "
        "engine also brings an engine light, \"won't start\" or a failed inspection, and those are part of what "
        "the failure does to the price. Other, unrelated problems on the same car are held fixed.\n"
        "- **What the buyer sees** (warning lights, inspection status, won't start) is valued as it is, with "
        "whatever else the seller disclosed held fixed — e.g. an engine light whose cause nobody knows.\n"
        "- **Euros depend on the car's value.** A repair costs roughly the same on a cheap or a dear car, so "
        "one percentage can't describe both. Each problem gets one smooth curve: its % effect is allowed to "
        "change with the car's value (linearly in log value), estimated on all cars at once. The value is the "
        "car's *clean value* — what a LightGBM model, out-of-fold, predicts it would fetch with no problems.\n"
        f"- A figure is shown only where at least {M.MIN_SUPPORT} cars with that problem are worth about that "
        "much (within a factor of two); elsewhere the curve would be guessing. **No measurable cost** means "
        "the 95% interval includes zero — or the estimate came out positive, which a fault can't really do: "
        "a tyre-pressure or air-suspension light, for example, also tells you the car *has* those systems, "
        "and the model doesn't see trim level.\n")

    out.append("## What a problem costs, by what the car is worth\n")
    out.append("![What a problem costs](chart_cost_by_value.png)\n")
    out.append("![Cost vs. car value](chart_cost_curves.png)\n")
    values = [float(v) for v in M.REF_VALUES]
    out.append("What's broken (incl. the lights, won't-start or failed inspection it causes) — euros off the "
               "auction price, 95% interval in brackets:\n")
    out.append(md_table(cost_table(curves, [f for f in BROKEN if (f, 2000.0) in ref.index], values)) + "\n")
    out.append("What the buyer sees:\n")
    out.append(md_table(cost_table(curves, [f for f in ["warning_light_any"] + SEEN if (f, 2000.0) in ref.index],
                                   values)) + "\n")

    out.append("## Which warning light matters\n")
    out.append("![Which warning light matters](chart_warning_lights.png)\n")
    lights = [f for f in F.LIGHT_FLAGS if f in o.index and o.loc[f, "n_faulty"] >= M.MIN_N]
    lt = pd.DataFrame({
        "Light": [LABEL.get(f, f) for f in lights],
        "Cars": [num(o.loc[f, "n_faulty"]) for f in lights],
        "Effect": [(f"**{pct(o.loc[f, 'pct'])}** {ci(o.loc[f, 'pct_lo'], o.loc[f, 'pct_hi'])}"
                    if o.loc[f, "pct_hi"] < 0 else f"no measurable effect {ci(o.loc[f, 'pct_lo'], o.loc[f, 'pct_hi'])}")
                   for f in lights],
        "≈ € on a 2 000 € car": [cost_cell(ref.loc[(f, 2000.0)]) if (f, 2000.0) in ref.index else "" for f in lights],
    }).sort_values("Cars", key=lambda s: s.str.replace(NBSP, "").astype(int), ascending=False)
    out.append(md_table(lt) + "\n")

    out.append("## All problems, pooled over all cars (%)\n")
    boot = meta.get("lgb_boot", 0)
    out.append("One % per problem from the same hedonic model (log price, make×model fixed effects; 95% CIs use "
               "the larger of make×model-clustered and heteroskedasticity-robust standard errors). "
               "**Effect** = incl. consequences for what's broken, as seen for what the buyer sees. "
               "*Alone* = the problem with every other disclosed flag held fixed (smaller for broken parts, "
               "because their consequences are then held fixed too). LightGBM = out-of-bag counterfactual "
               f"of the alone-effect ({boot} bootstrap refits). Matched = same make×model, year, fuel, gearbox "
               "and 50 000 km band; cars whose only major problem is this one vs. cars with none.\n")
    rows = []
    for f in [x for x in BROKEN + ["warning_light_any"] + SEEN if x in o.index]:
        r = o.loc[f]
        if r.n_faulty < M.MIN_N:
            continue
        root = f in M.ROOT_FLAGS and not _nan(r.get("incl_pct"))
        e, lo, hi = (r.incl_pct, r.incl_pct_lo, r.incl_pct_hi) if root else (r.pct, r.pct_lo, r.pct_hi)
        rows.append({
            "Problem": LABEL.get(f, f), "Cars": num(r.n_faulty),
            "Effect": (f"**{pct(e)}** {ci(lo, hi)}" if hi < 0 else f"≈0 {ci(lo, hi)}"),
            "Alone": f"{pct(r.pct)} {ci(r.pct_lo, r.pct_hi)}" if root else "",
            "LightGBM": f"{pct(r.get('lgb_pct'))} {ci(r.get('lgb_pct_lo'), r.get('lgb_pct_hi'))}",
            "Matched": (f"{pct(r.get('match_pct'))} (n={num(r.match_n_faulty)})" if not _nan(r.get("match_pct"))
                        else "too few"),
        })
    out.append(md_table(pd.DataFrame(rows)) + "\n")

    out.append("## Per make / model (largest models)\n")
    out.append(f"% effects with the problem's other disclosed flags held fixed, from one model with "
               f"problem×model interactions and **shrunk toward the all-cars effect** (empirical Bayes) because "
               f"single-model estimates are noisy. `too few` = under {M.MIN_N_SEG} cars with that problem in "
               f"that model (count in brackets). Raw estimates with CIs: `effects_by_segment.csv`.\n")
    segs = seg.groupby("segment").n_segment.first().sort_values(ascending=False)
    mat = []
    for s, n in segs.items():
        row = {"Model": s, "Cars": num(n)}
        for f in SEG_MATRIX:
            r = seg[(seg.segment == s) & (seg.flag == f)]
            if not len(r):
                row[SHORT[f]] = ""
                continue
            r = r.iloc[0]
            row[SHORT[f]] = (f"{pct(r.pct_shrunk)} ({num(r.n_faulty)})" if not _nan(r.get("pct_shrunk"))
                             else f"too few ({num(r.n_faulty)})")
        mat.append(row)
    out.append(md_table(pd.DataFrame(mat)) + "\n")

    out.append("## Robustness\n")
    out.append("The *alone* % effect re-estimated on different samples / fixed effects. If a number moves a lot "
               "here, don't quote it.\n")
    piv = rob.assign(v=[pct(p) if n >= M.MIN_N else "too few" for p, n in zip(rob.pct, rob.n_faulty)])
    piv = piv.pivot_table(index="flag", columns="variant", values="v", aggfunc="first")
    piv = piv.reindex([f for f in M.ROBUST_FLAGS if f in piv.index])
    piv.index = [LABEL.get(f, F.LABELS.get(f, f)) for f in piv.index]
    out.append(md_table(piv.reset_index().rename(columns={"index": "Problem"})) + "\n")

    if cv is not None:
        out.append("## Out-of-sample fit (5-fold CV)\n")
        out.append("Predicting log(price) of held-out auctions; the gain from adding the problem flags is "
                   "measured out of sample.\n")
        t = cv.assign(**{"R² (log price)": cv.R2_log.round(3), "MAE (log)": cv.MAE_log.round(3),
                         "Median abs. % error": (cv.median_abs_pct_error * 100).round(1).astype(str) + "%"})
        out.append(md_table(t[["model", "features", "R² (log price)", "MAE (log)", "Median abs. % error"]]) + "\n")

    if val is not None:
        out.append("## How good are the problem flags?\n")
        out.append("Rules were checked by hand on fresh random samples drawn *after* each rule's last change "
                   "(a first development round only fixed rules). Precision = share of flagged listings that "
                   "really have the problem (20 checked). Recall is estimated from 15 unflagged listings that "
                   "mention the topic's keyword stem, so its interval is wide. Missed problems sit in the "
                   "comparison group and pull effects **toward zero**. After the last check, a few fixes only "
                   "*removed* matches (negations such as 'ruoste ei ole mennyt läpi', a cracked rear window, ad "
                   "wording like 'xenon-ajovalot'), so for structural rust, windshield and light types the "
                   "precision shown is a lower bound.\n")
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
        out.append(f"{num(meta.get('nettiauto_n', 0))} private-seller listings under 5 000 € (a saved "
                   "search), problems from the free-text description only. Asking prices, not sale prices; "
                   "small sample — indicative only. *Alone* % effects.\n")
        nao = na.set_index("flag")
        t = pd.DataFrame([{"Problem": LABEL.get(f, f), "Listings with it": num(nao.loc[f, "n_faulty"]),
                           "Effect": (f"{pct(nao.loc[f, 'pct'])} {ci(nao.loc[f, 'pct_lo'], nao.loc[f, 'pct_hi'])}"
                                      if nao.loc[f, "n_faulty"] >= M.MIN_N else "too few")}
                          for f in ["warning_light_any", "not_roadworthy", "inspection_lapsed", "rust_cosmetic",
                                    "rust_severe", "windshield_crack", "project_for_parts"] if f in nao.index])
        out.append(md_table(t) + "\n")

    out.append("## What this is not\n")
    out.append(
        "- **Not repair quotes.** An effect is how much less bidders paid for cars that disclosed the problem "
        "than for comparable cars that didn't. It mixes the expected repair cost with risk (an unknown cause "
        "behind an engine light) and anything else that goes with disclosing it.\n"
        "- **Disclosure-based.** Problems are what sellers wrote. The 'is any warning light on?' checklist "
        "question is asked of every seller, so the light results are the cleanest; free-text problems depend on "
        "how carefully a seller writes, and missed mentions make effects look smaller.\n"
        "- **Auction market, mostly cheap cars.** Huutokaupat buyers are bargain hunters and traders, and few "
        "cars here are worth over 10 000 €, so the top of every curve is thin.\n"
        "- **Controls, not problems.** Import, one key, no service book, tyres and 'emissions system modified' "
        "are held fixed as car attributes; their coefficients say which kinds of cars carry them.\n")
    (R / "fault_effects.md").write_text("\n".join(out), encoding="utf-8")
    print(f"wrote {R / 'fault_effects.md'}")


if __name__ == "__main__":
    main()
