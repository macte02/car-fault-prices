"""Price effect of any fault you can describe with a keyword pattern.

    python -m fault_effects.adhoc --name broken_spring \
        --pattern "jous\\w*(?:\\W+\\w+){0,3}?\\W+(?:poikki|katken\\w*|rikki)" --exclude "jousto"

The pattern is a regular expression on folded text (lowercase, ä→a, ö→o) of
the auction title, the "Viat ja muut havainnot" text and the checklist answers.
Dealer boilerplate is stripped first, and a negator just before the match
("ei ... jousi poikki") cancels it — the same matching as the built-in rules.

It prints how many cars match and a sample of the matched text (read them: a
pattern is only as good as its matches), which existing fault flags the same
cars carry, and then the effect from the same hedonic model as the report with
this flag added:
  * this fault, others held fixed — the fault's own effect;
  * total gap of these cars — vs. the same cars with every disclosed fault
    removed (includes what usually comes with it);
  * per clean-value band where at least 20 cars match.
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from fault_effects import faults as F
from fault_effects import model as M
from fault_effects import paths

TEXT_COLS = ["title", "faults_text", "body_answer", "interior_answer", "light_answer", "windshield_answer",
             "inspection_answer", "service_book_answer"]


def flag_cars(df: pd.DataFrame, name: str, pattern: str, exclude: str | None) -> tuple[pd.Series, pd.Series]:
    tx = pd.read_csv(paths.DATA / "text_huutokaupat.csv.gz", dtype={"ad_id": str}).set_index("ad_id")
    tx = tx.reindex(df.ad_id)
    rule = F.Rule(name, F.R(pattern), exclude=F.R(exclude) if exclude else None, scope="sentence")
    evidence = []
    for _, r in tx.iterrows():
        text = "\n".join(str(r[c]) for c in TEXT_COLS if isinstance(r.get(c), str))
        h = rule.hits(F.sentences(text))
        evidence.append(h[0] if h else "")
    ev = pd.Series(evidence, index=df.index)
    return (ev != "").astype(int), ev


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", required=True, help="short flag name, e.g. broken_spring")
    ap.add_argument("--pattern", required=True, help="regex on folded text (ä→a, ö→o)")
    ap.add_argument("--exclude", default=None, help="regex; a sentence matching it is skipped")
    ap.add_argument("--show", type=int, default=15, help="matched snippets to print")
    a = ap.parse_args()

    df = M.load_huutokaupat()
    flag, ev = flag_cars(df, a.name, a.pattern, a.exclude)
    df[a.name] = flag
    n = int(flag.sum())
    print(f"\n{n} of {len(df):,} cars match '{a.name}'.")
    if n == 0:
        return
    sample = ev[flag == 1].sample(min(a.show, n), random_state=1)
    print("Sample of matched text (check these):")
    for ad, t in zip(df.loc[sample.index, "ad_id"], sample):
        print(f"  {ad}  …{t}…")

    others = [f for f in M.SPEC_B if f not in M.NON_FAULTS]
    co = df.loc[flag == 1, others].mean().sort_values(ascending=False)
    co = co[co >= 0.1]
    if len(co):
        print("Existing flags on the same cars: " + ", ".join(f"{F.LABELS.get(k, k)} {v:.0%}" for k, v in co.items()))
    if n < M.MIN_N:
        print(f"\nNot enough data: fewer than {M.MIN_N} matching cars.")
        return

    df["clean_value"] = M.clean_value_oof(df, M.SPEC_B)
    df["band"] = M.value_band(df.clean_value)
    eff, _ = M.ols_effects(df, M.SPEC_B + [a.name], clean=df.clean_value)
    r = eff.set_index("flag").loc[a.name]
    print(f"\nThis fault, others held fixed: {r.pct:+.1%}  (95% CI {r.pct_lo:+.1%} … {r.pct_hi:+.1%})"
          f"  ≈ {r.eur:+,.0f} € per car (CI {r.eur_lo:+,.0f} … {r.eur_hi:+,.0f} €)")
    print(f"Total gap of these cars vs. fault-free: {r.total_pct:+.1%}  ≈ {r.total_eur:+,.0f} €"
          f"  (they carry {r.other_faults_mean:.1f} other fault flags on average)")
    print(f"Median value of these cars without this fault: {r.clean_price_median:,.0f} €")

    bands = M.band_effects(df, extra=[a.name])
    bt = bands[bands.flag == a.name]
    print("\nBy clean-value band (this fault, others held fixed):")
    for _, b in bt.iterrows():
        if b.n_faulty >= M.MIN_N_BAND and pd.notna(b.get("pct")):
            print(f"  {b.band:>16}: {b.eur:+,.0f} € (CI {b.eur_lo:+,.0f} … {b.eur_hi:+,.0f}), {b.pct:+.1%}, n={int(b.n_faulty)}")
        else:
            print(f"  {b.band:>16}: not enough data (n={int(b.n_faulty)})")


if __name__ == "__main__":
    main()
