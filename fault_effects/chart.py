"""Charts for the report.

    python -m fault_effects.chart

reports/fault_effects.png         forest plot of the pooled % effects
reports/fault_effects_bands.png   euro effect by clean-value band for key faults
reports/chart_cost_by_band.png    what each problem costs, three value bands side by side
reports/chart_warning_lights.png  which warning light matters
reports/chart_own_vs_total.png    a fault's own effect vs. the total gap of cars that have it
reports/chart_engine_light_models.png  engine light by make / model
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


COST_FAULTS = ["gearbox_issue", "engine_failure", "non_runner", "light_engine", "inspection_lapsed",
               "inspection_failed", "not_roadworthy", "engine_running_issue", "clutch_issue", "steering_issue",
               "light_oil", "light_abs_esp", "light_airbag", "rust_severe", "ac_issue", "suspension_issue",
               "brakes_issue", "windshield_crack", "rust_cosmetic", "body_dents", "light_bulb", "light_tpms"]
COST_BANDS = ["1 000–3 000 €", "3 000–5 000 €", "5 000–10 000 €"]
SHORT_LABEL = {
    "gearbox_issue": "Gearbox problem", "engine_failure": "Engine failure / rebuild needed",
    "non_runner": "Won't start / won't move", "light_engine": "Engine warning light",
    "inspection_lapsed": "Inspection lapsed", "inspection_failed": "Inspection failed",
    "not_roadworthy": "Not roadworthy / driving ban", "engine_running_issue": "Engine runs badly (misfire, smoke, turbo)",
    "clutch_issue": "Clutch / flywheel worn", "steering_issue": "Steering problem", "light_oil": "Oil-pressure light",
    "light_abs_esp": "ABS / ESP light", "light_airbag": "Airbag light", "rust_severe": "Rust, structural",
    "ac_issue": "A/C not working", "suspension_issue": "Suspension (springs, shocks, knocks)",
    "brakes_issue": "Brakes worn / noisy", "windshield_crack": "Cracked windshield", "rust_cosmetic": "Rust, cosmetic",
    "body_dents": "Dents", "light_bulb": "Bulb-failure light", "light_tpms": "Tyre-pressure light",
    "engine_knock": "Engine knocking noise", "warning_light_any": "Any warning light",
    "light_gearbox": "Gearbox light", "light_brake": "Brake / pad-wear light", "light_coolant": "Coolant light",
    "light_dpf": "DPF light", "light_glow_plug": "Glow-plug light", "light_service": "Service reminder",
    "light_unspecified": "Light, type not stated", "light_battery": "Battery / charging light",
}


def _header(fig, title: str, subtitle: str, right: float = 1.0, top_in: float = 0.8) -> None:
    """Title + subtitle in fixed inches from the top, then fit the axes below them."""
    h = fig.get_figheight()
    fig.text(0.012, 1 - 0.18 / h, title, fontsize=11, color=INK, ha="left", va="top")
    fig.text(0.012, 1 - 0.45 / h, subtitle, fontsize=8, color=INK2, ha="left", va="top")
    fig.tight_layout(rect=(0, 0, right, 1 - top_in / h))


def _euro(v, _=None) -> str:
    return f"{v:,.0f} €".replace(",", " ").replace("-", "−")


def _legend(ax, labels, colors, markers, y=1.02) -> None:
    for i, (lab, c, mk) in enumerate(zip(labels, colors, markers)):
        ax.plot([], [], marker=mk, color=c, ls="", ms=7, label=lab)
    ax.legend(loc="lower left", bbox_to_anchor=(0, y), ncol=len(labels), frameon=False, fontsize=8,
              handletextpad=0.3, columnspacing=1.4, labelcolor=INK)


def cost_by_band() -> None:
    """One row per problem, a dot per value band: what it costs in euros."""
    b = pd.read_csv(paths.REPORTS / "effects_by_band.csv")
    b = b[b.band.isin(COST_BANDS)]
    order = (b[b.band == COST_BANDS[0]].set_index("flag").eur.reindex(COST_FAULTS).sort_values().index.tolist())
    n = len(order)
    fig, ax = plt.subplots(figsize=(9.6, 0.42 * n + 1.9), dpi=160)
    fig.patch.set_facecolor(SURFACE)
    _style(ax)
    offs = [-0.22, 0.0, 0.22]
    for j, band in enumerate(COST_BANDS):
        r = b[b.band == band].set_index("flag")
        for i, f in enumerate(order):
            y = n - 1 - i + offs[j]
            if f not in r.index or r.loc[f, "n_faulty"] < M.MIN_N_BAND:
                continue
            x, lo, hi = r.loc[f, "eur"], r.loc[f, "eur_lo"], r.loc[f, "eur_hi"]
            clear = hi < 0 or lo > 0
            ax.plot([lo, hi], [y, y], color=SERIES[j], lw=1.6, alpha=0.55, solid_capstyle="round", zorder=2)
            ax.plot([x], [y], marker=MARKERS[j], ms=6.5, color=SERIES[j] if clear else SURFACE,
                    markeredgecolor=SERIES[j], markeredgewidth=1.6, ls="", zorder=3)
    ax.axvline(0, color=MUTED, lw=1, zorder=1)
    ax.set_yticks(range(n))
    ax.set_yticklabels([SHORT_LABEL.get(f, F.LABELS.get(f, f)) for f in reversed(order)], fontsize=8.5, color=INK)
    ax.tick_params(axis="y", length=0)
    ax.set_ylim(-0.7, n - 0.3)
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(_euro))
    ax.grid(axis="x", color=GRID, lw=0.8, zorder=0)
    ax.set_xlabel("Price effect of the problem (€), other disclosed problems held fixed · line = 95% interval",
                  fontsize=8.5, color=INK2)
    _legend(ax, [f"car worth {bd}" for bd in COST_BANDS], SERIES[:3], MARKERS[:3])
    _header(fig, "What a problem costs at auction, by what the car would be worth without it",
            "Huutokaupat sold auctions · hollow marker = interval includes zero · "
            f"missing marker = fewer than {M.MIN_N_BAND} cars with that problem in that band")
    fig.savefig(paths.REPORTS / "chart_cost_by_band.png", facecolor=SURFACE)
    plt.close(fig)


LIGHTS = ["light_engine", "light_oil", "light_gearbox", "light_abs_esp", "light_airbag", "light_unspecified",
          "light_coolant", "light_brake", "light_dpf", "light_service", "light_bulb", "light_glow_plug",
          "light_battery", "light_tpms"]


def warning_lights() -> None:
    ov = pd.read_csv(paths.REPORTS / "effects_overall.csv").set_index("flag")
    r = ov.loc[[f for f in LIGHTS if f in ov.index and ov.loc[f, "n_faulty"] >= M.MIN_N]].sort_values("pct")
    n = len(r)
    fig, ax = plt.subplots(figsize=(9.2, 0.38 * n + 1.6), dpi=160)
    fig.patch.set_facecolor(SURFACE)
    _style(ax)
    for i, (f, row) in enumerate(r.iterrows()):
        y = n - 1 - i
        clear = row.pct_hi < 0 or row.pct_lo > 0
        ax.barh(y, row.pct * 100, height=0.62, color=SERIES[0] if clear else "#a9c9ef", zorder=2)
        ax.plot([row.pct_lo * 100, row.pct_hi * 100], [y, y], color=INK2, lw=1.2, zorder=3)
        ax.text(1.0, y, f"{row.pct * 100:+.0f}%   n={int(row.n_faulty):,}".replace(",", " ").replace("-", "−"),
                transform=ax.get_yaxis_transform(), fontsize=8, color=INK2, va="center", ha="left")
    ax.axvline(0, color=MUTED, lw=1, zorder=1)
    ax.set_yticks(range(n))
    ax.set_yticklabels([SHORT_LABEL.get(f, f) for f in reversed(r.index)], fontsize=8.5, color=INK)
    ax.tick_params(axis="y", length=0)
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:+.0f}%".replace("-", "−")))
    ax.grid(axis="x", color=GRID, lw=0.8, zorder=0)
    ax.set_xlabel("Price difference vs. the same car without that light (%), other problems held fixed · "
                  "black line = 95% interval", fontsize=8.5, color=INK2)
    _header(fig, "Which warning light actually matters",
            "Light type from the seller's own description · pale bar = interval includes zero", right=0.9)
    fig.savefig(paths.REPORTS / "chart_warning_lights.png", facecolor=SURFACE)
    plt.close(fig)


OWN_TOTAL = ["engine_failure", "non_runner", "gearbox_issue", "engine_knock", "engine_running_issue",
             "light_engine", "clutch_issue", "rust_severe", "inspection_failed", "light_abs_esp"]


def own_vs_total() -> None:
    ov = pd.read_csv(paths.REPORTS / "effects_overall.csv").set_index("flag").loc[OWN_TOTAL]
    ov = ov.sort_values("total_pct")
    n = len(ov)
    fig, ax = plt.subplots(figsize=(9.2, 0.62 * n + 1.8), dpi=160)
    fig.patch.set_facecolor(SURFACE)
    _style(ax)
    for i, (f, r) in enumerate(ov.iterrows()):
        y = n - 1 - i
        for k, (val, lo, hi, dy) in enumerate([(r.pct, r.pct_lo, r.pct_hi, 0.17),
                                               (r.total_pct, r.total_pct_lo, r.total_pct_hi, -0.17)]):
            ax.barh(y + dy, val * 100, height=0.3, color=SERIES[k], zorder=2)
            ax.plot([lo * 100, hi * 100], [y + dy, y + dy], color=INK2, lw=1.0, zorder=3)
        ax.text(1.02, y, f"{r.pct * 100:+.0f}% alone\n{r.total_pct * 100:+.0f}% total · "
                f"{r.other_faults_mean:.1f} other problems".replace("-", "−"),
                transform=ax.get_yaxis_transform(), fontsize=7.5, color=INK2, va="center", ha="left")
    ax.axvline(0, color=MUTED, lw=1, zorder=1)
    ax.set_xlim(right=2)
    ax.set_yticks(range(n))
    ax.set_yticklabels([SHORT_LABEL.get(f, f) for f in reversed(ov.index)], fontsize=8.5, color=INK)
    ax.tick_params(axis="y", length=0)
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:+.0f}%".replace("-", "−")))
    ax.grid(axis="x", color=GRID, lw=0.8, zorder=0)
    ax.set_xlabel("Price difference (%) · black line = 95% interval", fontsize=8.5, color=INK2)
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color=SERIES[0], label="The problem on its own (other problems held fixed)"),
                       Patch(color=SERIES[1], label="Total gap of cars that have it vs. a fault-free car")],
              loc="lower left", bbox_to_anchor=(0, 1.01), ncol=2, frameon=False, fontsize=8, labelcolor=INK)
    _header(fig, "A problem's own effect vs. what a buyer sees",
            "Serious faults rarely come alone: a failed engine usually also means 'won't start', "
            "'not roadworthy', an engine light…", right=0.8)
    fig.savefig(paths.REPORTS / "chart_own_vs_total.png", facecolor=SURFACE)
    plt.close(fig)


def engine_light_models() -> None:
    seg = pd.read_csv(paths.REPORTS / "effects_by_segment.csv")
    ov = pd.read_csv(paths.REPORTS / "effects_overall.csv").set_index("flag").loc["light_engine"]
    s = seg[(seg.flag == "light_engine") & seg.pct.notna()].sort_values("pct_shrunk")
    n = len(s)
    fig, ax = plt.subplots(figsize=(9.2, 0.36 * n + 1.7), dpi=160)
    fig.patch.set_facecolor(SURFACE)
    _style(ax)
    for i, (_, r) in enumerate(s.iterrows()):
        y = n - 1 - i
        ax.plot([r.pct_lo * 100, r.pct_hi * 100], [y, y], color=SERIES[0], lw=1.6, alpha=0.45, zorder=2)
        ax.plot([r.pct * 100], [y], marker="o", ms=6, color=SURFACE, markeredgecolor=SERIES[0],
                markeredgewidth=1.5, ls="", zorder=3)
        ax.plot([r.pct_shrunk * 100], [y], marker="o", ms=7, color=SERIES[0], markeredgecolor=SURFACE,
                markeredgewidth=1.5, ls="", zorder=4)
        ax.text(1.0, y, f"{r.pct_shrunk * 100:+.0f}% · ≈{_euro(r.eur_shrunk)}  (n={int(r.n_faulty)})".replace("-", "−"),
                transform=ax.get_yaxis_transform(), fontsize=7.5, color=INK2, va="center", ha="left")
    ax.axvline(ov.pct * 100, color=SERIES[1], lw=1.2, ls="--", zorder=1)
    ax.text(ov.pct * 100, n - 0.4, f" all cars {ov.pct * 100:+.0f}%".replace("-", "−"), fontsize=7.5,
            color=INK2, va="bottom")
    ax.axvline(0, color=MUTED, lw=1, zorder=1)
    ax.set_yticks(range(n))
    ax.set_yticklabels(list(reversed(s.segment.tolist())), fontsize=8.5, color=INK)
    ax.tick_params(axis="y", length=0)
    ax.set_ylim(-0.7, n + 0.3)
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:+.0f}%".replace("-", "−")))
    ax.grid(axis="x", color=GRID, lw=0.8, zorder=0)
    ax.set_xlabel("Price effect of the engine warning light (%)", fontsize=8.5, color=INK2)
    _header(fig, "Engine warning light, by make and model",
            "Filled dot = best estimate (pulled toward the all-cars effect) · hollow dot + line = that model alone, "
            "95% interval · € at that model's typical clean price", right=0.8)
    fig.savefig(paths.REPORTS / "chart_engine_light_models.png", facecolor=SURFACE)
    plt.close(fig)


def main() -> None:
    forest()
    by_band()
    cost_by_band()
    warning_lights()
    own_vs_total()
    engine_light_models()
    print(f"wrote charts to {paths.REPORTS}")


if __name__ == "__main__":
    main()
