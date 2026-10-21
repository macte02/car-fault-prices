"""Forest plot of the headline effects -> reports/fault_effects.png.

    python -m fault_effects.chart
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from fault_effects import faults as F
from fault_effects import model as M
from fault_effects import paths

SURFACE, INK, INK2, MUTED, GRID, SERIES = "#fcfcfb", "#0b0b0b", "#52514e", "#8a8984", "#e4e3df", "#2a78d6"

GROUPS = [
    ("Warning lights (seller checklist)", ["warning_light_any", "light_engine", "light_oil", "light_gearbox",
                                           "light_abs_esp", "light_airbag", "light_brake", "light_dpf",
                                           "light_service", "light_bulb", "light_tpms"]),
    ("Mechanical", ["gearbox_issue", "non_runner", "engine_major", "engine_running_issue", "clutch_issue",
                    "steering_issue", "timing_belt_due"]),
    ("Body & inspection", ["inspection_lapsed", "inspection_failed", "not_roadworthy", "rust_severe",
                           "rust_cosmetic", "crash_damage", "windshield_crack"]),
]


def main() -> None:
    ov = pd.read_csv(paths.REPORTS / "effects_overall.csv").set_index("flag")
    rows = []
    for g, flags in GROUPS:
        rows.append(("group", g, None))
        for f in flags:
            if f in ov.index and ov.loc[f, "n_faulty"] >= M.MIN_N:
                rows.append(("flag", f, ov.loc[f]))
    n = len(rows)
    fig, ax = plt.subplots(figsize=(9.2, 0.34 * n + 1.4), dpi=160)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    y = n - 1
    yticks, ylabels = [], []
    for kind, key, r in rows:
        if kind == "group":
            ax.text(-0.62, y, key, fontsize=9.5, fontweight="bold", color=INK, va="center", ha="left",
                    transform=ax.get_yaxis_transform() if False else ax.transData)
        else:
            lo, hi, pt = r.pct_lo * 100, r.pct_hi * 100, r.pct * 100
            ax.plot([lo, hi], [y, y], color=SERIES, lw=2, solid_capstyle="round", zorder=2)
            ax.scatter([pt], [y], s=42, color=SERIES, edgecolor=SURFACE, linewidth=2, zorder=3)
            yticks.append(y)
            ylabels.append(f"{F.LABELS.get(key, key)}  (n={int(r.n_faulty):,})".replace(",", " "))
            ax.text(1.01, y, f"{pt:+.1f}%  [{lo:+.1f}, {hi:+.1f}]".replace("-", "−"), fontsize=8,
                    color=INK2, va="center", ha="left", transform=ax.get_yaxis_transform())
        y -= 1
    ax.axvline(0, color=MUTED, lw=1, zorder=1)
    ax.set_yticks(yticks)
    ax.set_yticklabels(ylabels, fontsize=8.5, color=INK)
    ax.set_xlim(-60, 15)
    ax.set_ylim(-0.7, n - 0.3)
    ax.set_xlabel("Price difference vs. comparable car without the fault (%), 95% CI", fontsize=8.5, color=INK2)
    ax.tick_params(axis="x", colors=INK2, labelsize=8)
    ax.tick_params(axis="y", length=0)
    ax.grid(axis="x", color=GRID, lw=0.8, zorder=0)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_title("What a disclosed fault does to the auction price  (Huutokaupat, hedonic OLS)",
                 fontsize=10.5, color=INK, loc="left", pad=10)
    # group headers sit left of the tick labels
    for t in ax.texts:
        if t.get_fontweight() == "bold":
            t.set_x(-60)
            t.set_ha("left")
    fig.tight_layout()
    out = paths.REPORTS / "fault_effects.png"
    fig.savefig(out, facecolor=SURFACE)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
