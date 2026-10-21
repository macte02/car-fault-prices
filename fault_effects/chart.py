"""Charts for the report.

    python -m fault_effects.chart

reports/fault_effects.png        forest plot of the pooled % effects
reports/fault_effects_bands.png  euro effect by clean-value band for key faults
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from fault_effects import faults as F
from fault_effects import model as M
from fault_effects import paths

SURFACE, INK, INK2, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#8a8984", "#e4e3df"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]   # validated categorical slots 1–5
MARKERS = ["o", "s", "D", "^", "v"]

GROUPS = [
    ("Warning lights (seller checklist)", ["warning_light_any", "light_engine", "light_oil", "light_gearbox",
                                           "light_abs_esp", "light_airbag", "light_brake", "light_dpf",
                                           "light_service", "light_bulb", "light_tpms"]),
    ("Mechanical", ["gearbox_issue", "non_runner", "engine_failure", "engine_knock", "engine_running_issue",
                    "clutch_issue", "steering_issue", "timing_belt_due"]),
    ("Body & inspection", ["inspection_lapsed", "inspection_failed", "not_roadworthy", "rust_severe",
                           "rust_cosmetic", "crash_damage", "windshield_crack"]),
]
BAND_CHART = ["warning_light_any", "light_engine", "gearbox_issue", "engine_failure", "rust_severe"]


def _style(ax) -> None:
    ax.set_facecolor(SURFACE)
    ax.tick_params(colors=INK2, labelsize=8)
    for s in ax.spines.values():
        s.set_visible(False)


def forest() -> None:
    ov = pd.read_csv(paths.REPORTS / "effects_overall.csv").set_index("flag")
    rows = []
    for g, flags in GROUPS:
        rows.append(("group", g, None))
        rows += [("flag", f, ov.loc[f]) for f in flags if f in ov.index and ov.loc[f, "n_faulty"] >= M.MIN_N]
    n = len(rows)
    fig, ax = plt.subplots(figsize=(9.2, 0.34 * n + 1.4), dpi=160)
    fig.patch.set_facecolor(SURFACE)
    _style(ax)
    yticks, ylabels = [], []
    for i, (kind, key, r) in enumerate(rows):
        y = n - 1 - i
        if kind == "group":
            ax.text(-60, y, key, fontsize=9.5, fontweight="bold", color=INK, va="center", ha="left")
            continue
        lo, hi, pt = r.pct_lo * 100, r.pct_hi * 100, r.pct * 100
        ax.plot([lo, hi], [y, y], color=SERIES[0], lw=2, solid_capstyle="round", zorder=2)
        ax.scatter([pt], [y], s=42, color=SERIES[0], edgecolor=SURFACE, linewidth=2, zorder=3)
        yticks.append(y)
        ylabels.append(f"{F.LABELS.get(key, key)}  (n={int(r.n_faulty):,})".replace(",", " "))
        ax.text(1.01, y, f"{pt:+.1f}%  [{lo:+.1f}, {hi:+.1f}]".replace("-", "−"), fontsize=8, color=INK2,
                va="center", ha="left", transform=ax.get_yaxis_transform())
    ax.axvline(0, color=MUTED, lw=1, zorder=1)
    ax.set_yticks(yticks)
    ax.set_yticklabels(ylabels, fontsize=8.5, color=INK)
    ax.tick_params(axis="y", length=0)
    ax.set_xlim(-60, 15)
    ax.set_ylim(-0.7, n - 0.3)
    ax.set_xlabel("Price difference vs. comparable car without the fault (%), other faults held fixed, 95% CI",
                  fontsize=8.5, color=INK2)
    ax.grid(axis="x", color=GRID, lw=0.8, zorder=0)
    ax.set_title("What a disclosed fault does to the auction price  (Huutokaupat, pooled over all cars)",
                 fontsize=10.5, color=INK, loc="left", pad=10)
    fig.tight_layout()
    fig.savefig(paths.REPORTS / "fault_effects.png", facecolor=SURFACE)


def by_band() -> None:
    b = pd.read_csv(paths.REPORTS / "effects_by_band.csv")
    fig, ax = plt.subplots(figsize=(9.2, 5.0), dpi=160)
    fig.patch.set_facecolor(SURFACE)
    _style(ax)
    xs = list(range(len(M.BAND_LABELS)))
    for i, f in enumerate(BAND_CHART):
        r = b[b.flag == f].set_index("band").reindex(M.BAND_LABELS)
        ok = r.n_faulty >= M.MIN_N_BAND
        x = [xs[j] for j, o in enumerate(ok) if o]
        y = list(r.eur[ok])
        ax.plot(x, y, color=SERIES[i], lw=2, zorder=2)
        clear = list(((r.eur_hi < 0) | (r.eur_lo > 0))[ok])
        for xi, yi, c in zip(x, y, clear):   # hollow marker = 95% interval includes zero
            ax.plot([xi], [yi], marker=MARKERS[i], ms=7, color=SERIES[i] if c else SURFACE,
                    markeredgecolor=SERIES[i], markeredgewidth=1.8, zorder=3)
        if x:
            ax.annotate(F.LABELS.get(f, f), (x[-1], y[-1]), xytext=(8, 0), textcoords="offset points",
                        fontsize=8, color=INK, va="center")
    ax.axhline(0, color=MUTED, lw=1, zorder=1)
    ax.set_xticks(xs)
    ax.set_xticklabels(M.BAND_LABELS, fontsize=8, color=INK2)
    ax.set_xlim(-0.3, len(xs) - 0.4 + 1.6)
    ax.grid(axis="y", color=GRID, lw=0.8, zorder=0)
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f} €".replace(",", " ")
                                                                  .replace("-", "−")))
    ax.set_xlabel("Car's clean value (predicted price with no faults)", fontsize=8.5, color=INK2)
    ax.set_title("Euro effect of a fault grows with the car's value", fontsize=10.5, color=INK, loc="left",
                 pad=18)
    ax.text(0, 1.015, f"Other faults held fixed · bands with ≥{M.MIN_N_BAND} faulty cars · hollow marker = "
            "95% interval includes zero", transform=ax.transAxes, fontsize=8, color=INK2)
    fig.tight_layout()
    fig.savefig(paths.REPORTS / "fault_effects_bands.png", facecolor=SURFACE)


def main() -> None:
    forest()
    by_band()
    print(f"wrote {paths.REPORTS / 'fault_effects.png'} and fault_effects_bands.png")


if __name__ == "__main__":
    main()
