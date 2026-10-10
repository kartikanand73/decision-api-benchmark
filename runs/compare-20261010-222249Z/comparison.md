# Run-to-run comparison

| Run | Started (UTC) | Location | TypeSafe Jev served | OpenAI Decisions served | Microsoft Decision-1 served |
| --- | --- | --- | --- | --- | --- |
| 20261010-004439Z-or-run1 | 2026-10-10T00:44:39 | Columbus OH | typesafe/jev-1.13-20260917 | openai/gpt-6-luna-decisions-20261006 | microsoft/microsoft-decision-1-20261009 |
| 20261010-023836Z-or-run2 | 2026-10-10T02:38:36 | Columbus OH | typesafe/jev-1.13-20260917 | openai/gpt-6-luna-decisions-20261006 | microsoft/microsoft-decision-1-20261009 |

## Uncertainty

95% intervals from a case-resampling bootstrap (2,000 resamples over 500 cases). The same resampled cases are used for every provider, so differences stay paired. **Pooled** keeps each case's answers from every run together, so it reflects both which cases were sampled and run-to-run variation in the answers. An interval that excludes 0 means the difference is unlikely to come from those sources alone; one that includes 0 means these runs cannot tell the providers apart on that metric. Neither interval covers changes in conditions between runs (time of day, network path, a model update), which the per-run rows let you inspect.

### Pairwise differences, pooled across runs (A − B)

| A − B | Macro-F1 | Accuracy | Latency p50 | Latency p95 | Interval excludes 0 on |
| --- | --- | --- | --- | --- | --- |
| TypeSafe Jev − OpenAI Decisions | +17.8 pts (+14.2 to +21.9) | +15.4 pts (+11.9 to +19.0) | +20 ms (+18 to +21) | -14 ms (-26 to -6) | macro-F1, accuracy, p50, p95 |
| TypeSafe Jev − Microsoft Decision-1 | +1.7 pts (-1.8 to +5.2) | +1.8 pts (-0.8 to +4.6) | -69 ms (-71 to -68) | -62 ms (-69 to -56) | p50, p95 |
| OpenAI Decisions − Microsoft Decision-1 | -16.2 pts (-20.3 to -12.3) | -13.6 pts (-17.0 to -10.4) | -89 ms (-90 to -87) | -48 ms (-55 to -38) | macro-F1, accuracy, p50, p95 |

### Each provider, per run and pooled

| Provider | Scope | Macro-F1 | Accuracy | Latency p50 (ms) | Latency p95 (ms) |
| --- | --- | --- | --- | --- | --- |
| TypeSafe Jev | 20261010-004439Z-or-run1 | 90.4% (87.1%–93.3%) | 93.4% (91.2%–95.4%) | 229 (228–230) | 302 (295–305) |
| TypeSafe Jev | 20261010-023836Z-or-run2 | 88.0% (84.4%–91.4%) | 92.2% (89.8%–94.4%) | 238 (237–240) | 334 (328–339) |
| TypeSafe Jev | pooled | 89.2% (86.1%–92.1%) | 92.8% (90.8%–94.7%) | 233 (232–234) | 321 (315–326) |
| OpenAI Decisions | 20261010-004439Z-or-run1 | 71.4% (66.7%–75.5%) | 77.4% (73.6%–81.0%) | 224 (222–226) | 340 (331–349) |
| OpenAI Decisions | 20261010-023836Z-or-run2 | 71.4% (66.7%–75.5%) | 77.4% (73.6%–81.0%) | 200 (198–202) | 329 (311–348) |
| OpenAI Decisions | pooled | 71.4% (66.7%–75.5%) | 77.4% (73.6%–81.0%) | 214 (212–215) | 335 (330–346) |
| Microsoft Decision-1 | 20261010-004439Z-or-run1 | 87.7% (84.0%–90.9%) | 91.2% (88.6%–93.6%) | 301 (300–303) | 382 (377–388) |
| Microsoft Decision-1 | 20261010-023836Z-or-run2 | 87.4% (83.7%–90.7%) | 90.8% (88.2%–93.2%) | 304 (303–305) | 385 (377–390) |
| Microsoft Decision-1 | pooled | 87.6% (83.9%–90.8%) | 91.0% (88.4%–93.4%) | 303 (301–304) | 383 (379–388) |

### Pairwise differences in each run

| A − B | Run | Macro-F1 | Accuracy | Latency p50 |
| --- | --- | --- | --- | --- |
| TypeSafe Jev − OpenAI Decisions | 20261010-004439Z-or-run1 | +19.0 pts (+15.1 to +23.3) | +16.0 pts (+12.4 to +19.8) | +5 ms (+3 to +7) |
| TypeSafe Jev − OpenAI Decisions | 20261010-023836Z-or-run2 | +16.7 pts (+12.7 to +21.1) | +14.8 pts (+11.2 to +18.6) | +38 ms (+36 to +41) |
| TypeSafe Jev − Microsoft Decision-1 | 20261010-004439Z-or-run1 | +2.7 pts (-1.1 to +6.8) | +2.2 pts (-0.6 to +5.4) | -72 ms (-74 to -70) |
| TypeSafe Jev − Microsoft Decision-1 | 20261010-023836Z-or-run2 | +0.6 pts (-2.8 to +4.1) | +1.4 pts (-1.2 to +4.2) | -66 ms (-68 to -64) |
| OpenAI Decisions − Microsoft Decision-1 | 20261010-004439Z-or-run1 | -16.3 pts (-20.4 to -12.2) | -13.8 pts (-17.2 to -10.4) | -77 ms (-80 to -75) |
| OpenAI Decisions − Microsoft Decision-1 | 20261010-023836Z-or-run2 | -16.1 pts (-20.2 to -12.1) | -13.4 pts (-16.8 to -10.0) | -104 ms (-106 to -102) |

## Ranking in each run (point estimates)

Which provider had the best value in each run. A rank is a point estimate: a small real difference can swap rank between finite runs, and an unchanged rank does not by itself show a real difference. Read it next to the intervals above.

| Metric |  | 20261010-004439Z-or-run1 | 20261010-023836Z-or-run2 | Best provider |
| --- | --- | --- | --- | --- |
| Latency p50 (ms) | lower is better | OpenAI Decisions | OpenAI Decisions | same in every run |
| Latency p95 (ms) | lower is better | TypeSafe Jev | OpenAI Decisions | differs between runs |
| Cost per 1k decisions ($) | lower is better | Microsoft Decision-1 | Microsoft Decision-1 | same in every run |
| Route accuracy | higher is better | TypeSafe Jev | TypeSafe Jev | same in every run |
| Route macro-F1 | higher is better | TypeSafe Jev | TypeSafe Jev | same in every run |
| Route balanced accuracy | higher is better | TypeSafe Jev | Microsoft Decision-1 | differs between runs |
| Final action accuracy | higher is better | TypeSafe Jev | TypeSafe Jev | same in every run |
| Fraud auto-approved | lower is better | tie | tie | tie in every run |
| ECE | lower is better | OpenAI Decisions | OpenAI Decisions | same in every run |
| Brier score | lower is better | Microsoft Decision-1 | Microsoft Decision-1 | same in every run |
| Same route in every option order | higher is better | Microsoft Decision-1 | Microsoft Decision-1 | same in every run |
| Success rate | higher is better | tie | tie | tie in every run |

## Every metric, every run

| Metric | TypeSafe Jev · 20261010-004439Z-or-run1 | TypeSafe Jev · 20261010-023836Z-or-run2 | OpenAI Decisions · 20261010-004439Z-or-run1 | OpenAI Decisions · 20261010-023836Z-or-run2 | Microsoft Decision-1 · 20261010-004439Z-or-run1 | Microsoft Decision-1 · 20261010-023836Z-or-run2 | TypeSafe Jev spread | OpenAI Decisions spread | Microsoft Decision-1 spread |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Latency p50 (ms) | 229 | 238 | 224 | 200 | 301 | 304 | 10 | 24 | 3 |
| Latency p95 (ms) | 302 | 334 | 340 | 329 | 382 | 385 | 33 | 11 | 3 |
| Cost per 1k decisions ($) | 0.0324 | 0.0324 | 0.0611 | 0.0611 | 0.0178 | 0.0178 | 0.0000 | 0.0000 | 0.0000 |
| Route accuracy | 93.4% | 92.2% | 77.4% | 77.4% | 91.2% | 90.8% | 1.2% | 0.0% | 0.4% |
| Route macro-F1 | 90.4% | 88.0% | 71.4% | 71.4% | 87.7% | 87.4% | 2.3% | 0.0% | 0.2% |
| Route balanced accuracy | 93.1% | 90.7% | 77.2% | 77.2% | 91.1% | 91.1% | 2.4% | 0.0% | 0.0% |
| Final action accuracy | 82.4% | 83.2% | 73.6% | 73.6% | 78.2% | 79.0% | 0.8% | 0.0% | 0.8% |
| Fraud auto-approved | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| ECE | 0.080 | 0.066 | 0.041 | 0.041 | 0.057 | 0.062 | 0.014 | 0.000 | 0.005 |
| Brier score | 0.117 | 0.117 | 0.296 | 0.297 | 0.115 | 0.112 | 0.000 | 0.000 | 0.004 |
| Same route in every option order | 91.6% | 91.8% | 64.2% | 64.2% | 97.6% | 97.2% | 0.2% | 0.0% | 0.4% |
| Success rate | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 0.0% | 0.0% | 0.0% |

## Same case, different run (original option order)

How often a provider gave the same route to the same case in two separate runs.

| Provider | Runs | Same route | Identical probabilities (all three, exact) | Largest probability change |
| --- | --- | --- | --- | --- |
| TypeSafe Jev | 20261010-004439Z-or-run1 vs 20261010-023836Z-or-run2 | 476 / 500 (95.2%) | 212 / 500 (42.4%) | 0.160 |
| OpenAI Decisions | 20261010-004439Z-or-run1 vs 20261010-023836Z-or-run2 | 500 / 500 (100%) | 498 / 500 (99.6%) | 0.050 |
| Microsoft Decision-1 | 20261010-004439Z-or-run1 vs 20261010-023836Z-or-run2 | 496 / 500 (99.2%) | 49 / 500 (9.8%) | 0.183 |

Identical means all three route probabilities were exactly equal; the largest change is measured over the same three fields, so 'identical' is all of them only when the largest change is 0.
