# How much does a fault lower a used car's price?

![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)
![statsmodels](https://img.shields.io/badge/statsmodels-hedonic%20OLS-4B8BBE)
![LightGBM](https://img.shields.io/badge/LightGBM-cross--check-9ACD32)

I co-run a small used-car business, and we kept guessing how much an engine light or a rusty sill should
knock off the price. So I measured it on **21,911 sold cars** from Huutokaupat.com auctions (May to
October 2026): each car with a disclosed problem is compared with otherwise identical cars that didn't
have it.

**Short version:** on a car that would be worth 2,000 € without problems, a failed engine takes about
**−850 €** off the auction price, a gearbox problem **−795 €**, structural rust **−573 €** and an engine
warning light **−466 €**. On a 5,000 € car the same problems cost roughly −2,000 €, −1,570 €, −970 € and
−980 €.

Full results with every fault and warning light: [`reports/fault_effects.md`](reports/fault_effects.md)

![What a problem costs at auction](reports/chart_cost_by_value.png)

## How it works

1. **Fault flags from the listing text.** Sellers describe problems in free Finnish text plus a short
   checklist ("Palaako jokin vikavalo?"). [`faults.py`](fault_effects/faults.py) turns that into ~60
   flags with regex rules that handle negations ("ei ruostetta") and seller boilerplate.
   I hand-checked samples of every rule; precision/recall is in
   [`reports/rule_validation.csv`](reports/rule_validation.csv) and the labels in
   [`fault_effects/labels/`](fault_effects/labels/).
2. **Like-for-like comparison.** A hedonic regression on log price with make × model fixed effects,
   controlling for model year, mileage, power, fuel, gearbox, drive and auction month. Standard errors
   are the larger of make×model-clustered and heteroskedasticity-robust.
3. **Euros, not just percent.** A repair costs about the same on a cheap car and an expensive one, so
   each fault gets a smooth curve over the car's "clean value" (an out-of-fold LightGBM estimate of what
   it would sell for with no problems). A number is only shown where at least 20 cars with that fault
   are worth about that much.
4. **Cross-checks.** LightGBM and exact matching run next to the regression (the pooled table in the
   report), and [`reports/robustness.csv`](reports/robustness.csv) re-runs the main model on subsets
   such as accepted sales only. There's also a small sample of 540 Nettiauto asking prices, though most
   faults are too rare in it to say much.

Two kinds of effect are reported separately:

- **What's broken** (engine, gearbox, rust, clutch…) includes what it causes. A dead engine also
  brings an engine light and a failed inspection, and that's part of what it costs you.
- **What the buyer sees** (warning lights, inspection status, won't start) is valued on its own, e.g.
  an engine light whose cause nobody knows.

![Which warning light matters](reports/chart_warning_lights.png)

## Running it

```sh
pip install -r requirements.txt

# everything (≈ 5 min): features → rule tests → model → charts → report
python -m fault_effects.run_all --huutokaupat-db data/huutokaupat.db

# one car
python -m fault_effects.query --make Volkswagen --model Golf --year 2012 --fuel diesel --fault light_engine

# any fault you can describe with a regex (prints the matches so you can check them first)
python -m fault_effects.adhoc --help

# optional: collect Nettiauto asking prices (slow on purpose, one request every 2.5–5 s)
python -m fault_effects.collect_nettiauto --max-pages 120
```

| Module | Does |
|---|---|
| `faults.py` | Finnish/English fault rules + checklist parsing |
| `features.py` | One row per car: price, make × model, year, km, kW, fuel, gearbox, drive, month + fault flags |
| `validate.py` | Draws hand-check samples and scores the rules |
| `model.py` | Hedonic OLS, LightGBM, matching, per-segment shrinkage, robustness |
| `report.py`, `chart.py` | The report and charts in `reports/` |
| `query.py`, `adhoc.py` | Answers for a single car or a custom fault |
| `collect_nettiauto.py` | Polite, resumable Nettiauto collector |

## Data

The raw data isn't in the repo. The Huutokaupat auction archive was collected separately, and listing
text belongs to the sites it came from. What is here: all the code, the hand-check labels (ad IDs and
0/1 only, no listing text) and the result tables and charts.

## Limitations

These are market associations from what sellers chose to disclose, not repair quotes. A seller who
hides a fault makes that fault look cheaper than it is, and the model doesn't see trim level. That's
why a tyre-pressure light can come out as "no cost": it also tells you the car has tyre-pressure
sensors.

---

Built by **Mac Teppo** · [LinkedIn](https://www.linkedin.com/in/mac-teppo)
