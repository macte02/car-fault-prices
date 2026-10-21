# How much do specific faults lower a used car's price?

Source: **25 922 sold Huutokaupat passenger-car auctions** (2026-05-05 – 2026-10-21); analysis sample **21 911 cars** across 1 085 make×model variants (auctions with at least one bid and a final bid ≥ 100 €; model years 1990+). Median price 2 020 €; 44% of auctions ended with the seller accepting the top bid (the rest still give the market's top bid).

**Headline.** A warning light on the seller's checklist is associated with a **−18.6% lower price** (95% CI [−20.1  −17.1]  n = 5 365 cars)  ≈ −535 € per car at these prices. For the **engine / check-engine light** specifically: **−23.6%** ([−25.6  −21.5]  n = 2 299)  ≈ −603 €. Effects are for otherwise comparable cars — same make×model  model year  mileage  power  fuel  gearbox  drive and auction month — and hold all other disclosed faults fixed.

## Main results

OLS = hedonic regression on log(price), make×model fixed effects, CIs clustered by make×model. € = average euro gap for the faulty cars (their predicted clean price × effect). LightGBM = out-of-bag counterfactual (flag on vs. off), 30 bootstrap refits. Matched = same make×model, year, fuel, gearbox and 50 000 km band; cars whose *only* major fault is this one vs. cars with none. Below 30 faulty cars a row says *not enough data*.

| Fault | n faulty | Hedonic OLS | ≈ € per car | LightGBM | Matched | Clean price (median) |
|---|---|---|---|---|---|---|
| Any warning light on (seller checklist) | 5365 | **−18.6%** [−20.1, −17.1] | −535 € [−577  −492] | −17.5% [−18.5, −16.6] | −18.9% (n=1138) | 1 870 € |
| Engine / check-engine light | 2299 | **−23.6%** [−25.6, −21.5] | −603 € [−654  −549] | −22.1% [−23.6, −21.4] | −21.3% (n=356) | 1 679 € |
| ABS / ESP / traction-control light | 574 | **−14.5%** [−18.7, −10.1] | −258 € [−332  −180] | −12.1% [−15.0, −10.7] | −23.3% (n=62) | 1 205 € |
| Airbag (SRS) light | 314 | **−14.7%** [−20.0, −9.2] | −277 € [−375  −172] | −9.5% [−12.6, −5.9] | −3.0% (n=44) | 1 222 € |
| Oil-pressure / oil-level light | 154 | **−17.8%** [−25.2, −9.5] | −451 € [−641  −242] | −13.4% [−16.8, −10.3] | n/e (n=20) | 1 800 € |
| Gearbox warning light | 102 | **−16.9%** [−28.4, −3.6] | −378 € [−634  −81] | −16.1% [−20.0, −9.4] | n/e (n=8) | 1 872 € |
| Brake / parking-brake / pad-wear light | 446 | **−7.0%** [−11.4, −2.5] | −179 € [−289  −62] | −4.9% [−7.1, −3.2] | −15.4% (n=59) | 1 720 € |
| Coolant / temperature light | 91 | **−11.4%** [−23.0, +2.0] | −229 € [−462  +40] | −8.7% [−15.2, −1.7] | n/e (n=12) | 1 265 € |
| DPF (particulate filter) light | 138 | **−7.1%** [−15.9, +2.6] | −166 € [−371  +61] | −3.1% [−5.8, +0.8] | n/e (n=5) | 1 767 € |
| Glow-plug light | 124 | **−2.0%** [−9.2, +5.7] | −40 € [−182  +112] | −4.7% [−9.5, −1.8] | n/e (n=8) | 1 638 € |
| Tyre-pressure (TPMS) light | 307 | **+3.5%** [−1.5, +8.7] | +173 € [−72  +430] | −0.5% [−1.7, +0.4] | −0.2% (n=78) | 3 402 € |
| Service-reminder light | 354 | **−4.3%** [−9.3, +1.0] | −103 € [−224  +25] | −3.1% [−4.7, −1.4] | −10.5% (n=67) | 1 612 € |
| Bulb-failure light | 861 | **−2.7%** [−6.2, +0.9] | −62 € [−143  +21] | −1.1% [−1.9, −0.1] | +1.9% (n=234) | 1 857 € |
| Warning light, type not stated | 1044 | **−13.8%** [−17.5, −9.9] | −513 € [−650  −370] | −10.4% [−12.3, −9.1] | −16.1% (n=261) | 2 219 € |
| Major engine damage (knock, head gasket, …) | 244 | **−27.2%** [−32.6, −21.3] | −1 001 € [−1 200  −787] | −22.7% [−25.2, −18.5] | −40.8% (n=31) | 2 549 € |
| Gearbox problem | 426 | **−33.1%** [−37.6, −28.3] | −1 011 € [−1 148  −864] | −26.7% [−29.8, −23.0] | −49.6% (n=60) | 2 113 € |
| Won't start / won't move | 215 | **−30.9%** [−37.5, −23.6] | −787 € [−955  −600] | −26.2% [−37.0, −24.1] | n/e (n=15) | 1 470 € |
| Clutch / flywheel worn | 346 | **−19.9%** [−24.4, −15.2] | −428 € [−523  −327] | −17.2% [−20.0, −14.4] | −12.3% (n=77) | 1 486 € |
| Engine running issue (misfire, smoke, turbo, EGR, …) | 764 | **−20.7%** [−24.3, −16.9] | −584 € [−686  −477] | −18.1% [−20.9, −15.8] | −31.7% (n=103) | 1 840 € |
| Timing belt due / unknown | 77 | **+4.4%** [−6.4, +16.4] | +139 € [−203  +521] | −0.1% [−3.6, +6.4] | n/e (n=14) | 2 118 € |
| Timing-chain noise / stretched | 56 | **−13.7%** [−24.1, −1.9] | −599 € [−1 054  −81] | −11.4% [−17.9, −8.7] | n/e (n=29) | 2 741 € |
| Steering problem / pulls | 201 | **−15.2%** [−21.5, −8.4] | −391 € [−554  −216] | −8.9% [−12.8, −4.6] | −1.3% (n=92) | 1 568 € |
| Not roadworthy / driving ban | 941 | **−23.2%** [−28.4, −17.7] | −802 € [−980  −611] | −13.9% [−15.0, −12.1] | +13.6% (n=64) | 1 710 € |
| inspection_lapsed | 980 | **−29.8%** [−33.4, −26.0] | −731 € [−819  −637] | −27.3% [−30.2, −26.7] | −33.5% (n=116) | 1 248 € |
| Inspection failed (hylätty) | 646 | **−29.1%** [−32.3, −25.7] | −561 € [−623  −496] | −25.6% [−27.8, −23.8] | −33.5% (n=104) | 1 298 € |
| Rust, structural / holes / sills | 395 | **−23.9%** [−28.2, −19.4] | −434 € [−512  −352] | −16.8% [−19.8, −14.7] | −25.0% (n=53) | 1 159 € |
| Rust, cosmetic only | 6461 | **−6.7%** [−8.4, −4.9] | −145 € [−182  −107] | −5.9% [−6.8, −4.6] | −1.3% (n=3265) | 1 579 € |
| Crash / collision damage | 172 | **−9.2%** [−19.5, +2.3] | −463 € [−977  +116] | −8.9% [−13.3, −2.5] | n/e (n=24) | 3 454 € |
| Windshield cracked | 2936 | **−6.3%** [−8.3, −4.4] | −154 € [−201  −106] | −5.0% [−6.2, −3.5] | −7.3% (n=634) | 1 634 € |
| A/C not working properly | 817 | **−9.2%** [−12.5, −5.8] | −210 € [−284  −133] | −7.2% [−8.8, −5.3] | −2.5% (n=452) | 1 416 € |
| Sold as project / for parts / to repair | 295 | **−14.9%** [−21.3, −8.0] | −393 € [−561  −210] | −15.9% [−19.1, −13.6] | −35.3% (n=30) | 1 717 € |

### Per make / model (largest segments)

Segment-specific effects from the OLS with fault×segment interactions, shown **shrunk toward the overall effect** (empirical Bayes) because single-segment estimates are noisy; the raw estimates and CIs are in `effects_by_segment.csv`. `n/e` = fewer than 15 faulty cars in that segment (count in brackets).

| Segment | n | any light | engine light | rust (struct.) | rust (cosm.) | windshield | insp. lapsed | not roadworthy | gearbox | clutch | engine damage |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Volkswagen Golf | 922 | −23.2% (287) | −27.9% (130) | −23.9% (20) | −10.5% (449) | −5.7% (118) | −36.1% (58) | −23.2% (38) | −29.4% (28) | −24.3% (23) | n/e (7) |
| Škoda Octavia | 759 | −18.8% (308) | −24.9% (95) | −23.9% (24) | −6.3% (359) | −8.5% (94) | −49.2% (36) | −23.2% (26) | −35.9% (17) | n/e (8) | n/e (7) |
| Ford Focus | 630 | −24.6% (98) | −24.9% (50) | n/e (11) | −4.8% (229) | −4.6% (72) | −44.7% (28) | n/e (12) | n/e (13) | n/e (8) | n/e (5) |
| Volkswagen Passat | 587 | −20.6% (183) | −23.0% (69) | n/e (14) | −14.5% (273) | −6.4% (84) | −37.0% (21) | −23.2% (24) | n/e (12) | −19.3% (16) | n/e (7) |
| Audi A4 | 574 | −17.6% (160) | −20.5% (72) | n/e (14) | −8.0% (237) | −2.2% (106) | −18.4% (19) | −23.2% (40) | −34.0% (17) | n/e (6) | n/e (7) |
| Mercedes-Benz C-Class | 543 | −17.4% (155) | −23.3% (71) | n/e (4) | −8.2% (127) | −3.2% (81) | −12.4% (29) | −23.2% (43) | n/e (10) | n/e (1) | n/e (10) |
| Volvo V70 | 496 | −19.2% (173) | −21.3% (64) | n/e (14) | −6.2% (162) | −12.0% (60) | −40.5% (21) | −23.2% (22) | n/e (9) | n/e (2) | n/e (3) |
| Mercedes-Benz E-Class | 490 | −10.7% (159) | −21.3% (51) | n/e (6) | −3.5% (113) | −4.8% (75) | +5.7% (18) | −23.2% (52) | n/e (9) | n/e (0) | n/e (7) |
| Toyota Corolla | 449 | −16.1% (51) | −18.4% (32) | n/e (13) | −1.3% (138) | −4.3% (94) | −14.2% (17) | −23.2% (17) | n/e (8) | −16.5% (24) | n/e (1) |
| BMW 3 Serie | 446 | −14.3% (161) | −23.5% (51) | n/e (8) | +0.1% (91) | −3.5% (67) | −23.8% (31) | −23.2% (43) | n/e (4) | n/e (2) | n/e (7) |
| BMW 5 Serie | 432 | −6.3% (133) | −23.2% (38) | n/e (0) | −2.9% (70) | +2.8% (62) | −17.8% (26) | −23.2% (64) | n/e (4) | n/e (1) | n/e (8) |
| Toyota Avensis | 408 | −17.2% (62) | −17.9% (38) | n/e (4) | −1.6% (91) | −7.0% (86) | −36.2% (22) | n/e (11) | n/e (5) | n/e (10) | n/e (0) |
| Ford Mondeo | 396 | −18.6% (60) | −25.8% (31) | n/e (4) | −9.0% (105) | −3.7% (58) | −43.9% (18) | n/e (7) | n/e (12) | n/e (8) | n/e (4) |
| Opel Astra | 372 | −16.1% (90) | −21.3% (50) | n/e (8) | −6.0% (117) | −8.4% (37) | −44.6% (19) | n/e (12) | n/e (7) | n/e (1) | n/e (2) |
| Audi A6 | 342 | −18.0% (118) | −15.2% (53) | n/e (6) | −7.5% (120) | −7.5% (44) | −36.7% (25) | −23.2% (28) | n/e (9) | n/e (2) | n/e (6) |
| Nissan Qashqai | 329 | −17.8% (63) | −19.9% (40) | n/e (1) | −4.5% (27) | +3.6% (38) | n/e (7) | n/e (13) | −33.3% (25) | n/e (5) | n/e (13) |
| Toyota Yaris | 282 | −20.8% (40) | −22.4% (34) | n/e (8) | −6.0% (85) | −9.2% (38) | n/e (9) | n/e (8) | n/e (7) | n/e (12) | n/e (0) |
| Volvo V50 | 267 | −19.8% (65) | −27.2% (34) | n/e (4) | −8.4% (107) | −8.3% (54) | n/e (14) | n/e (9) | n/e (7) | n/e (5) | n/e (0) |

Engine light by segment (raw estimate with 95% CI, then shrunk, and the euro gap at the segment's typical clean price):

| Segment | n faulty | Raw | Shrunk | ≈ € (shrunk) | Clean price |
|---|---|---|---|---|---|
| Volkswagen Golf | 130 | −30.0% [−36.2, −23.0] | −27.9% | −353 € | 1 265 € |
| Škoda Octavia | 95 | −25.7% [−33.1, −17.4] | −24.9% | −298 € | 1 197 € |
| Audi A4 | 72 | −17.4% [−27.6, −5.9] | −20.5% | −422 € | 2 060 € |
| Mercedes-Benz C-Class | 71 | −23.0% [−31.8, −13.1] | −23.3% | −638 € | 2 743 € |
| Volkswagen Passat | 69 | −22.2% [−33.7, −8.7] | −23.0% | −382 € | 1 661 € |
| Volvo V70 | 64 | −18.6% [−29.5, −5.9] | −21.3% | −322 € | 1 513 € |
| Audi A6 | 53 | +1.0% [−15.1, +20.2] | −15.2% | −254 € | 1 679 € |
| BMW 3 Serie | 51 | −23.4% [−33.5, −11.7] | −23.5% | −594 € | 2 531 € |
| Mercedes-Benz E-Class | 51 | −19.2% [−29.1, −7.9] | −21.3% | −840 € | 3 934 € |
| Ford Focus | 50 | −26.5% [−36.5, −15.0] | −24.9% | −245 € | 981 € |
| Opel Astra | 50 | −18.9% [−29.2, −7.0] | −21.3% | −215 € | 1 009 € |
| Nissan Qashqai | 40 | −16.2% [−26.5, −4.5] | −19.9% | −629 € | 3 165 € |
| Toyota Avensis | 38 | −10.8% [−22.9, +3.2] | −17.9% | −209 € | 1 167 € |
| BMW 5 Serie | 38 | −22.7% [−33.4, −10.3] | −23.2% | −711 € | 3 068 € |
| Volvo V50 | 34 | −34.4% [−46.1, −20.1] | −27.2% | −268 € | 985 € |
| Toyota Yaris | 34 | −21.1% [−31.1, −9.7] | −22.4% | −308 € | 1 377 € |
| Toyota Corolla | 32 | −10.2% [−23.6, +5.4] | −18.4% | −215 € | 1 172 € |
| Ford Mondeo | 31 | −30.4% [−42.9, −15.1] | −25.8% | −270 € | 1 048 € |

## Robustness

Same OLS on different samples / fixed effects. If a number moves a lot here, don't quote it.

| Fault | >= 10 bids | accepted sales only | dealer-style listings only | main (all auctions with >=1 bid, price >= 100 €) | model-generation FE | price >= 500 € | private-style listings only |
|---|---|---|---|---|---|---|---|
| Any warning light on (seller checklist) | −17.3% | −18.3% | −17.5% | −18.6% | −18.2% | −15.3% | −20.8% |
| Engine / check-engine light | −22.9% | −23.9% | −23.3% | −23.6% | −23.2% | −19.8% | −24.4% |
| Timing belt due / unknown | +3.0% | −1.2% | +5.1% | +5.8% | +0.4% | +6.0% | n/e |
| Gearbox problem | −32.4% | −35.0% | −32.5% | −34.6% | −34.1% | −27.2% | −36.6% |
| Clutch / flywheel worn | −17.8% | −24.1% | −21.5% | −20.2% | −20.1% | −14.2% | −13.5% |
| Major engine damage (knock, head gasket, …) | −28.8% | −27.2% | −29.4% | −28.9% | −29.8% | −27.9% | −29.5% |
| Won't start / won't move | −25.6% | −30.5% | −31.9% | −31.1% | −30.6% | −23.9% | −31.2% |
| Rust, structural / holes / sills | −23.1% | −23.1% | −22.4% | −23.8% | −21.6% | −15.2% | −27.9% |
| Crash / collision damage | +0.6% | +2.5% | −2.2% | −8.1% | −12.0% | +0.0% | −12.3% |
| Inspection failed (hylätty) | −25.8% | −28.6% | −26.4% | −29.0% | −28.7% | −18.0% | −30.6% |
| Windshield cracked | −6.3% | −6.7% | −6.6% | −6.4% | −4.7% | −4.9% | −5.4% |

## Out-of-sample fit (5-fold CV)

Predicting log(price) of held-out auctions. Adding the fault flags is what this project contributes; the gain is measured out of sample.

| model | features | R² (log price) | MAE (log) | Median abs. % error |
|---|---|---|---|---|
| hedonic OLS | without fault flags | 0.721 | 0.402 | 29.5% |
| LightGBM | without fault flags | 0.762 | 0.361 | 25.5% |
| hedonic OLS | with fault flags | 0.776 | 0.357 | 26.3% |
| LightGBM | with fault flags | 0.817 | 0.314 | 22.3% |

## How good are the fault flags?

Rules were checked by hand on fresh random samples drawn *after* the last rule change (a first development round was used only to fix rules). Precision = share of flagged listings that really have the fault (20 checked). Recall is estimated from 15 unflagged listings that mention the topic's keyword stem, so its interval is wide. Missed faults sit in the 'clean' group and bias effects **toward zero** — the estimates above are, if anything, conservative. Light types are classified within the seller's 'yes, a light is on' answer.

| Flag | n flagged | Precision | Recall (est.) |
|---|---|---|---|
| Engine / check-engine light | 2211 | 100% [84%, 100%] | 100% [99%, 100%] |
| ABS / ESP / traction-control light | 556 | 95% [76%, 99%] | 100% [100%, 100%] |
| Airbag (SRS) light | 308 | 95% [76%, 99%] | ≈100% (no unflagged mentions) |
| DPF (particulate filter) light | 130 | 100% [84%, 100%] | ≈100% (no unflagged mentions) |
| Glow-plug light | 117 | 100% [84%, 100%] | ≈100% (no unflagged mentions) |
| Timing belt due / unknown | 77 | 100% [84%, 100%] | 62% [27%, 90%] |
| Gearbox problem | 435 | 95% [76%, 99%] | 68% [32%, 92%] |
| Clutch / flywheel worn | 353 | 100% [84%, 100%] | 57% [37%, 79%] |
| Major engine damage (knock, head gasket, …) | 245 | 95% [76%, 99%] | 100% [22%, 100%] |
| Won't start / won't move | 217 | 100% [84%, 100%] | 100% [37%, 100%] |
| Crash / collision damage | 179 | 90% [70%, 97%] | 99% [96%, 100%] |
| Rust (any) | 7026 | 100% [84%, 100%] | 100% [97%, 100%] |
| Rust, structural / holes / sills | 408 | 85% [64%, 95%] | 100% [18%, 100%] |
| Windshield cracked | 3012 | 100% [84%, 100%] | 100% [80%, 100%] |
| Inspection failed (hylätty) | 661 | 95% [76%, 99%] | 100% [81%, 100%] |

## Cross-check on Nettiauto asking prices

324 private-seller listings under 5 000 € (the watcher's saved search)  flags from the free-text description only (no checklist). Asking prices  not sale prices  and the 5 000 € cap truncates clean cars  which pulls effects toward zero.

| Fault | n faulty | Hedonic OLS | ≈ € per car | Clean price (median) |
|---|---|---|---|---|
| Any warning light on (seller checklist) | 12 | not enough data |  |  |
| Major engine damage (knock, head gasket, …) | 1 | not enough data |  |  |
| Gearbox problem | 1 | not enough data |  |  |
| Clutch / flywheel worn | 3 | not enough data |  |  |
| Won't start / won't move | 5 | not enough data |  |  |
| Not roadworthy / driving ban | 19 | not enough data |  |  |
| inspection_lapsed | 20 | not enough data |  |  |
| Rust, structural / holes / sills | 2 | not enough data |  |  |
| Rust, cosmetic only | 31 | **−5.9%** [−19.2, +9.5] | −168 € [−546  +272] | 2 906 € |
| Crash / collision damage | 0 | not enough data |  |  |
| Timing belt due / unknown | 1 | not enough data |  |  |
| Windshield cracked | 8 | not enough data |  |  |

## How to read this — and what it is not

- **Associations, not repair quotes.** A coefficient says how much less bidders paid for cars that disclosed the fault than for comparable cars that did not. It mixes the expected repair cost with risk (an unknown cause behind an engine light) and anything else correlated with disclosure.
- **Disclosure-based.** Faults are what sellers wrote. The checklist question 'is any warning light on?' is asked of every seller, which makes the light results the cleanest; free-text faults depend on how carefully a seller writes.
- **Auction market.** Huutokaupat buyers are mostly bargain hunters and traders; dealer retail prices react differently. Euro figures are at the prices of the cars that actually had the fault (cheap, old, high-mileage), so scale them by percentage for a pricier car.
- **Small effects are not zero effects.** For rows near 0 % the CI is the answer: e.g. a TPMS light costs little or nothing on average.
- **Incremental coefficients.** Each flag is estimated holding the others fixed (e.g. 'inspection failed' vs. 'inspection lapsed' are separate groups). 'Emissions system modified' and some paperwork flags are controls; their coefficients pick up which kinds of cars carry them and should not be read as causal.
