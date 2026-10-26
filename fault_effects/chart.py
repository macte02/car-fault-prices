"""Charts for the report.

    python -m fault_effects.chart

reports/chart_cost_by_value.png   what each problem costs on a 2 000 / 5 000 / 10 000 € car
reports/chart_cost_curves.png     euro cost vs. the car's value, key problems
reports/chart_warning_lights.png  which warning light matters

Only clear, data-supported costs are drawn. A point is left out when its 95%
interval includes zero or the estimate is positive (a fault cannot add value;
a positive estimate means "no measurable cost" plus noise or an equipment
signal), or when fewer than M.MIN_SUPPORT cars with that problem have a value
near that point.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D

from fault_effects import model as M
from fault_effects import paths

SURFACE, INK, INK2, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#8a8984", "#e4e3df"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]   # validated categorical slots 1–5
MARKERS = ["o", "s", "D", "^", "v"]

LABEL = {
    "gearbox_issue": "Gearbox problem", "engine_failure": "Engine failure / rebuild needed",
    "engine_knock": "Engine knocking", "engine_running_issue": "Engine runs badly (misfire, smoke, turbo)",
    "timing_chain_issue": "Timing chain noisy / stretched", "clutch_issue": "Clutch / flywheel worn",
    "steering_issue": "Steering problem", "rust_severe": "Rust, structural (holes, sills)",
    "rust_cosmetic": "Rust, cosmetic", "crash_damage": "Crash damage", "body_dents": "Dents",
    "windshield_crack": "Cracked windshield", "ac_issue": "A/C not working", "brakes_issue": "Brakes worn / noisy",
    "suspension_issue": "Suspension (springs, shocks, knocks)", "wheel_bearing": "Wheel bearing noise",
    "oil_leak": "Oil leak", "exhaust_issue": "Exhaust leak", "tyres_worn": "Tyres worn",
    "interior_damage": "Interior torn / broken", "electrical_minor": "Minor electrics broken",
    "non_runner": "Won't start / won't move", "not_roadworthy": "Not roadworthy / driving ban",
    "inspection_lapsed": "Inspection lapsed", "inspection_failed": "Inspection failed",
    "project_for_parts": "Sold as project / for parts", "warning_light_any": "Any warning light",
    "light_engine": "Engine light", "light_oil": "Oil-pressure light", "light_gearbox": "Gearbox light",
    "light_abs_esp": "ABS / ESP light", "light_airbag": "Airbag light", "light_brake": "Brake / pad-wear light",
    "light_coolant": "Coolant light", "light_dpf": "DPF light", "light_glow_plug": "Glow-plug light",
    "light_service": "Service reminder", "light_bulb": "Bulb-failure light", "light_tpms": "Tyre-pressure light",
    "light_battery": "Battery / charging light", "light_unspecified": "Light, type not stated",
}

BROKEN = ["engine_failure", "gearbox_issue", "engine_knock", "engine_running_issue", "timing_chain_issue",
          "rust_severe", "clutch_issue", "steering_issue", "crash_damage", "brakes_issue", "ac_issue",
          "rust_cosmetic", "body_dents", "windshield_crack", "suspension_issue", "wheel_bearing", "oil_leak",
          "tyres_worn", "exhaust_issue", "interior_damage", "electrical_minor"]
SEEN = ["non_runner", "not_roadworthy", "inspection_lapsed", "inspection_failed", "light_engine", "light_oil",
        "light_gearbox", "light_abs_esp", "light_airbag", "light_brake", "light_bulb", "light_tpms",
        "light_service"]
CHART_VALUES = [2000.0, 5000.0, 10000.0]
CURVES = ["engine_failure", "gearbox_issue", "light_engine", "rust_severe", "clutch_issue"]


def _style(ax) -> None:
    ax.set_facecolor(SURFACE)
    ax.tick_params(colors=INK2, labelsize=8)
    for s in ax.spines.values():
        s.set_visible(False)


def _header(fig, title: str, subtitle: str, right: float = 1.0, top_in: float = 0.8) -> None:
    """Title + subtitle in fixed inches from the top, then fit the axes below them."""
    h = fig.get_figheight()
    fig.text(0.012, 1 - 0.18 / h, title, fontsize=11, color=INK, ha="left", va="top")
    fig.text(0.012, 1 - 0.45 / h, subtitle, fontsize=8, color=INK2, ha="left", va="top")
    fig.tight_layout(rect=(0, 0, right, 1 - top_in / h))


def _euro(v, _=None) -> str:
    return f"{v:,.0f} €".replace(",", " ").replace("-", "−")


def _count(n) -> str:
    return f"{int(n):,}".replace(",", " ")


def _shown(r) -> bool:
    """A cost worth drawing: supported by data, clearly below zero."""
    return bool(r.supported and r.eur_hi < 0)


def cost_by_value() -> None:
    c = pd.read_csv(paths.REPORTS / "effects_curves.csv")
    ref = c[c.kind == "ref"].set_index(["flag", "value"])

    def order(flags):
        keep, none = [], []
        for f in flags:
            pts = [ref.loc[(f, v)] for v in CHART_VALUES if (f, v) in ref.index]
            if any(_shown(p) for p in pts):
                key = next((p.eur for p in pts[1:2] if _shown(p)), pts[0].eur)
                keep.append((key, f))
            elif pts:
                none.append(f)
        return [f for _, f in sorted(keep)], none

    broken, broken_none = order(BROKEN)
    seen, seen_none = order(SEEN)
    rows = [("group", "What's broken  (incl. the lights, won't-start or failed inspection it causes)")]
    rows += [("flag", f) for f in broken]
    rows += [("group", "What the buyer sees  (warning lights, inspection, won't start)")]
    rows += [("flag", f) for f in seen]
    n = len(rows)
    fig, ax = plt.subplots(figsize=(9.6, 0.4 * n + 2.4), dpi=160)
    fig.patch.set_facecolor(SURFACE)
    _style(ax)
    yt, yl = [], []
    offs = [0.2, 0.0, -0.2]
    for i, (kind, key) in enumerate(rows):
        y = n - 1 - i
        if kind == "group":
            ax.text(0.0, y - 0.1, key, transform=ax.get_yaxis_transform(), fontsize=9, fontweight="bold",
                    color=INK, ha="right", va="center")
            continue
        yt.append(y)
        yl.append(LABEL.get(key, key))
        for j, v in enumerate(CHART_VALUES):
            if (key, v) not in ref.index:
                continue
            r = ref.loc[(key, v)]
            if not _shown(r):
                continue
            ax.plot([r.eur_lo, r.eur_hi], [y + offs[j]] * 2, color=SERIES[j], lw=1.6, alpha=0.5, zorder=2)
            ax.plot([r.eur], [y + offs[j]], marker=MARKERS[j], ms=6.5, color=SERIES[j], ls="",
                    markeredgecolor=SURFACE, markeredgewidth=1.0, zorder=3)
    ax.axvline(0, color=MUTED, lw=1, zorder=1)
    ax.set_yticks(yt)
    ax.set_yticklabels(yl, fontsize=8.5, color=INK)
    ax.tick_params(axis="y", length=0)
    ax.set_ylim(-0.7, n - 0.3)
    ax.set_xlim(right=150)
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(_euro))
    ax.grid(axis="x", color=GRID, lw=0.8, zorder=0)
    ax.set_xlabel("What the problem takes off the auction price (€) · line = 95% interval", fontsize=8.5, color=INK2)
    ax.legend(handles=[Line2D([], [], marker=MARKERS[j], color=SERIES[j], ls="", ms=7,
                              label=f"{_euro(v)} car") for j, v in enumerate(CHART_VALUES)],
              title="Car worth, without problems:", title_fontsize=8, alignment="left",
              loc="lower left", bbox_to_anchor=(0, 1.0), ncol=3, frameon=False, fontsize=8, labelcolor=INK)
    none = broken_none + seen_none
    note = ("No measurable cost (interval includes zero): " + ", ".join(LABEL.get(f, f).lower() for f in none)
            if none else "")
    fig.text(0.012, 0.012, note, fontsize=7.5, color=INK2, ha="left", va="bottom", wrap=True)
    _header(fig, "What a problem costs at auction",
            "Huutokaupat, 21 911 sold cars, compared with the same make/model, year, mileage and power.\n"
            f"A dot is left out where its 95% interval includes zero or fewer than {M.MIN_SUPPORT} cars "
            "with that problem are worth about that much.", top_in=0.95)
    fig.subplots_adjust(bottom=max(fig.subplotpars.bottom, 0.75 / fig.get_figheight()))
    fig.savefig(paths.REPORTS / "chart_cost_by_value.png", facecolor=SURFACE)
    plt.close(fig)


def cost_curves() -> None:
    c = pd.read_csv(paths.REPORTS / "effects_curves.csv")
    g = c[c.kind == "grid"]
    fig, ax = plt.subplots(figsize=(9.2, 5.4), dpi=160)
    fig.patch.set_facecolor(SURFACE)
    _style(ax)
    ends = []
    for i, f in enumerate(CURVES):
        r = g[(g.flag == f) & g.supported].sort_values("value")
        if r.empty:
            continue
        ax.fill_between(r.value, r.eur_lo, r.eur_hi, color=SERIES[i], alpha=0.13, lw=0, zorder=1)
        ax.plot(r.value, r.eur, color=SERIES[i], lw=2.2, zorder=3)
        ends.append([r.eur.iat[-1], r.value.iat[-1], LABEL.get(f, f)])
    # End labels, nudged apart vertically so neighbours don't collide.
    ends.sort()
    gap = 330.0
    for k in range(1, len(ends)):
        if ends[k][0] - ends[k - 1][0] < gap:
            ends[k][0] = ends[k - 1][0] + gap
    for y, x, lab in ends:
        ax.annotate(lab, (x, y), xytext=(6, 0), textcoords="offset points", fontsize=8, color=INK, va="center")
    ax.axhline(0, color=MUTED, lw=1, zorder=1)
    ax.set_xscale("log")
    ticks = [500, 1000, 2000, 5000, 10000, 20000]
    ax.set_xticks(ticks)
    ax.set_xticklabels([_euro(t) for t in ticks])
    ax.minorticks_off()
    ax.set_xlim(400, 60000)
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(_euro))
    ax.grid(color=GRID, lw=0.8, zorder=0)
    ax.set_xlabel("What the car would be worth without the problem", fontsize=8.5, color=INK2)
    ax.set_ylabel("Effect on auction price", fontsize=8.5, color=INK2)
    _header(fig, "The same problem costs more on a more valuable car",
            f"Shaded = 95% interval · a line stops where fewer than {M.MIN_SUPPORT} cars with that problem are "
            "worth about that much.\nEngine failure, gearbox, rust and clutch include the lights and won't-start "
            "they cause.", top_in=0.95)
    fig.savefig(paths.REPORTS / "chart_cost_curves.png", facecolor=SURFACE)
    plt.close(fig)


LIGHTS = ["light_engine", "light_oil", "light_gearbox", "light_abs_esp", "light_airbag", "light_unspecified",
          "light_coolant", "light_brake", "light_dpf", "light_service", "light_bulb", "light_glow_plug",
          "light_battery", "light_tpms"]


def warning_lights() -> None:
    ov = pd.read_csv(paths.REPORTS / "effects_overall.csv").set_index("flag")
    c = pd.read_csv(paths.REPORTS / "effects_curves.csv")
    at2k = c[(c.kind == "ref") & (c.value == 2000.0)].set_index("flag")
    r = ov.loc[[f for f in LIGHTS if f in ov.index and ov.loc[f, "n_faulty"] >= M.MIN_N]].sort_values("pct")
    n = len(r)
    fig, ax = plt.subplots(figsize=(9.2, 0.38 * n + 1.7), dpi=160)
    fig.patch.set_facecolor(SURFACE)
    _style(ax)
    for i, (f, row) in enumerate(r.iterrows()):
        y = n - 1 - i
        clear = row.pct_hi < 0
        if clear:
            ax.barh(y, row.pct * 100, height=0.62, color=SERIES[0], zorder=2)
            ax.plot([row.pct_lo * 100, row.pct_hi * 100], [y, y], color=INK2, lw=1.2, zorder=3)
            e = at2k.loc[f, "eur"] if f in at2k.index else np.nan
            txt = f"{row.pct * 100:+.0f}%  ·  ≈{_euro(e)} on a 2 000 € car" if np.isfinite(e) else f"{row.pct * 100:+.0f}%"
        else:
            ax.plot([row.pct_lo * 100, row.pct_hi * 100], [y, y], color=MUTED, lw=1.2, zorder=3)
            ax.plot([row.pct * 100], [y], marker="o", ms=4.5, color=MUTED, zorder=4)
            txt = "no measurable effect"
        ax.text(1.0, y, txt.replace("-", "−"), transform=ax.get_yaxis_transform(), fontsize=8, color=INK2,
                va="center", ha="left")
    ax.axvline(0, color=MUTED, lw=1, zorder=1)
    ax.set_yticks(range(n))
    ax.set_yticklabels([f"{LABEL.get(f, f)}  (n={_count(ov.loc[f, 'n_faulty'])})" for f in reversed(r.index)],
                       fontsize=8.5, color=INK)
    ax.tick_params(axis="y", length=0)
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:+.0f}%".replace("-", "−")))
    ax.grid(axis="x", color=GRID, lw=0.8, zorder=0)
    ax.set_xlabel("Price difference vs. the same car without that light (%) · line = 95% interval",
                  fontsize=8.5, color=INK2)
    _header(fig, "Which warning light actually matters",
            "Light type from the seller's own description · grey = no measurable effect (interval includes zero)",
            right=0.78)
    fig.savefig(paths.REPORTS / "chart_warning_lights.png", facecolor=SURFACE)
    plt.close(fig)


def main() -> None:
    cost_by_value()
    cost_curves()
    warning_lights()
    print(f"wrote charts to {paths.REPORTS}")


if __name__ == "__main__":
    main()
