"""Validate the fault rules against a hand-checked sample.

    python -m fault_effects.validate sample     # write data/validation_sample.txt to read + label
    python -m fault_effects.validate evaluate   # precision / recall from fault_effects/labels/*.csv

For each key flag the sample has two parts:
  pos  — up to 20 random rows the rule flagged          -> precision
  miss — up to 15 random rows that mention the topic's
         word stem but were NOT flagged                 -> missed positives
Recall is then estimated as TP / (TP + FN) with
  TP = n_flagged · precision,  FN = n_stem_unflagged · miss_rate,
which assumes a true positive always mentions the stem (true by construction
for these stems — e.g. every gearbox complaint names the gearbox).

Labels live in fault_effects/labels/huutokaupat_handcheck.csv as
`flag,ad_id,part,label,round` (no listing text is committed). Round 1 was a
development pass (not recorded); a flag is evaluated only on labels drawn after
its rule was last changed (RULE_VERSION), so reported numbers are out-of-sample
for the rules as shipped.
"""

from __future__ import annotations

import argparse
import json
import math
import re

import numpy as np
import pandas as pd

from fault_effects import faults as F
from fault_effects import paths

LABEL_FILE = paths.LABELS / "huutokaupat_handcheck.csv"
SAMPLE_TXT = paths.DATA / "validation_sample.txt"

# Round in which each flag's rule was last edited; labels from earlier rounds
# describe an older rule and are ignored.
RULE_VERSION: dict[str, int] = {
    "engine_major": 4, "gearbox_issue": 3, "clutch_issue": 3, "inspection_failed": 3,
    "timing_belt_due": 3, "crash_damage": 4, "rust_severe": 4,
}

# flag -> (where to look, stem regex on folded text)
KEY_FLAGS: dict[str, tuple[str, str]] = {
    "light_engine": ("light", r"moottor|engine|hairio|check|\bmil\b|\bepc\b"),
    "light_abs_esp": ("light", r"abs|esp|luisto|vakau|traction|stabil"),
    "light_airbag": ("light", r"airbag|turvatyyn|srs|tyyny"),
    "light_dpf": ("light", r"dpf|hiukkas|partikkel|fap|noki"),
    "light_glow_plug": ("light", r"hehku|glow"),
    "timing_belt_due": ("free", r"jakohihn|timing belt"),
    "gearbox_issue": ("free", r"vaihteist|vaihdelaatik|vaihteet|vaihde\b|pakki|dsg|gearbox|transmission"),
    "clutch_issue": ("free", r"kytki|clutch|vauhtipyor"),
    "engine_major": ("free", r"moottor|kone\b|kansitiiv|nakut|kolkut|kolkot|kampiakse|kiertokan|engine"),
    "non_runner": ("free", r"kaynnist|liiku|kulje|ajokun|ajokel|hinaus|hinur|lavet|start"),
    "crash_damage": ("free+body", r"kolar|tormay|tormann|peltivaur|korivaur|rakennevaur|crash|collision|"
                                  r"hirvi|ojaan|ulosajo|vaurioituneena|runkoaisa"),
    "rust": ("free+body", r"ruost|rust|kupla|kupru|kukki"),
    "rust_severe": ("free+body", r"ruost|rust"),
    "windshield_crack": ("windshield+free", r"halk|halki|saro|crack|murtum"),
    "inspection_failed": ("inspection+free", r"hylat|hylky|hylkay|ajo-?oikeu|ajoaika|korjauskeho|vikalista|"
                                             r"uusintakatsast|katsastuksessa (?:ilmen|havait|todet)"),
}


def _texts(row: pd.Series, where: str) -> str:
    parts = []
    if "light" in where:
        parts.append(f"LIGHT: {row.light_answer}")
    if "inspection" in where:
        parts.append(f"INSPECTION: {row.inspection_answer}")
    if "windshield" in where:
        parts.append(f"WINDSHIELD: {row.windshield_answer}")
    if "body" in where:
        parts.append(f"BODY: {row.body_answer}")
    if "free" in where:
        parts.append(f"TITLE: {row.title}")
        free = " / ".join(F.sentences(str(row.faults_text or "")))
        parts.append(f"FAULTS: {free}")
        if isinstance(row.service_book_answer, str):
            parts.append(f"SERVICEBOOK: {row.service_book_answer}")
    return "\n    ".join(str(p) for p in parts)


def _stem_snippets(text: str, stem: str, width: int = 110) -> str:
    t = F.fold(text)
    out = []
    for m in re.finditer(stem, t):
        out.append("…" + t[max(0, m.start() - width):m.end() + width].replace("\n", " ") + "…")
        if len(out) >= 3:
            break
    return "  ||  ".join(out)


def analysis_rows() -> pd.DataFrame:
    df = pd.read_csv(paths.FEATURES_HK, dtype={"ad_id": str})
    tx = pd.read_csv(paths.DATA / "text_huutokaupat.csv.gz", dtype={"ad_id": str})
    df = df.merge(tx, on="ad_id", how="left")
    ok = ((df.bid_count.fillna(0) >= 1) | (df.bid_count.isna() & (df.accepted == 1))) & (df.price >= 100)
    return df[ok].reset_index(drop=True)


def cmd_sample(seed: int, flags: list[str] | None = None) -> None:
    df = analysis_rows()
    rng = np.random.default_rng(seed)
    lines = []
    for flag, (where, stem) in KEY_FLAGS.items():
        if flags and flag not in flags:
            continue
        scope = df[df.warning_light_any == 1] if where == "light" else df
        blob = scope.apply(lambda r: F.fold(_texts(r, where)), axis=1)
        has_stem = blob.str.contains(stem, regex=True)
        pos = scope[scope[flag] == 1]
        miss = scope[(scope[flag] == 0) & has_stem]
        lines.append(f"\n######## {flag}  (flagged {len(pos)}, stem-but-unflagged {len(miss)}, scope {len(scope)})")
        for part, frame, k in (("pos", pos, 20), ("miss", miss, 15)):
            if not len(frame):
                continue
            pick = frame.iloc[rng.choice(len(frame), size=min(k, len(frame)), replace=False)]
            for _, r in pick.iterrows():
                ev = json.loads(r.evidence or "{}").get(flag, "")
                body = _stem_snippets(_texts(r, where), stem) if part == "miss" else ev
                lines.append(f"[{flag}|{part}|{r.ad_id}] {body}")
    SAMPLE_TXT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {SAMPLE_TXT}")


def _wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (math.nan, math.nan)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - h) / d, (c + h) / d)


def evaluate() -> pd.DataFrame:
    labels = pd.read_csv(LABEL_FILE, dtype={"ad_id": str})
    df = analysis_rows()
    out = []
    for flag, (where, stem) in KEY_FLAGS.items():
        scope = df[df.warning_light_any == 1] if where == "light" else df
        blob = scope.apply(lambda r: F.fold(_texts(r, where)), axis=1)
        n_flagged = int((scope[flag] == 1).sum())
        n_stem_unflagged = int(((scope[flag] == 0) & blob.str.contains(stem, regex=True)).sum())
        lab = labels[(labels.flag == flag) & (labels["round"] >= RULE_VERSION.get(flag, 2))]
        pos, miss = lab[lab.part == "pos"], lab[lab.part == "miss"]
        tp, npos = int(pos.label.sum()), len(pos)
        fn, nmiss = int(miss.label.sum()), len(miss)
        prec = tp / npos if npos else math.nan
        miss_rate = fn / nmiss if nmiss else math.nan
        tp_est = n_flagged * prec
        fn_est = n_stem_unflagged * miss_rate if n_stem_unflagged else 0.0
        recall = tp_est / (tp_est + fn_est) if (tp_est + fn_est) > 0 else math.nan
        lo, hi = _wilson(tp, npos)
        # Recall interval from the miss-rate interval (precision held at its point value).
        m_lo, m_hi = _wilson(fn, nmiss) if nmiss else (0.0, 0.0)
        rec_hi = tp_est / (tp_est + n_stem_unflagged * m_lo) if tp_est else math.nan
        rec_lo = tp_est / (tp_est + n_stem_unflagged * m_hi) if tp_est else math.nan
        out.append({"flag": flag, "label": F.LABELS.get(flag, flag),
                    "rounds": ",".join(str(r) for r in sorted(lab["round"].unique())), "n_flagged": n_flagged,
                    "checked_pos": npos, "precision": prec, "precision_lo": lo, "precision_hi": hi,
                    "checked_miss": nmiss, "missed_in_check": fn, "stem_unflagged": n_stem_unflagged,
                    "recall_est": recall, "recall_lo": rec_lo, "recall_hi": rec_hi})
    res = pd.DataFrame(out)
    paths.REPORTS.mkdir(exist_ok=True)
    res.to_csv(paths.REPORTS / "rule_validation.csv", index=False)
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["sample", "evaluate"])
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--flags", nargs="*", default=None)
    a = ap.parse_args()
    if a.cmd == "sample":
        cmd_sample(a.seed, a.flags)
    else:
        res = evaluate()
        with pd.option_context("display.width", 200, "display.max_columns", 20):
            print(res.round(2).to_string(index=False))


if __name__ == "__main__":
    main()
