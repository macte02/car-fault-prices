"""Fault-effect study: how much do specific disclosed faults lower a used car's price?

Pipeline (run from the repo root):

    python -m fault_effects.collect_nettiauto     # optional: polite Nettiauto asking-price collection
    python -m fault_effects.features              # Huutokaupat (+ Nettiauto) -> fault flags + controls
    python -m fault_effects.validate              # rule precision/recall vs. the hand-checked sample
    python -m fault_effects.model                 # hedonic OLS + LightGBM/SHAP + matched comparisons
    python -m fault_effects.report                # reports/fault_effects.md + CSV tables
    python -m fault_effects.query --make Volkswagen --model Golf --year 2012 --fuel Diesel --fault engine_light

or everything after collection with `python -m fault_effects.run_all`.
"""
