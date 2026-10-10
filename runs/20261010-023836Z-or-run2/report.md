# TypeSafe Jev vs OpenAI Decisions vs Microsoft Decision-1: run report

## Run

| Item | Value |
| --- | --- |
| Started (UTC) | 2026-10-10T02:38:36.195647+00:00 |
| Duration | 246.3 s |
| Command | `python -m compare.run --label or-run2 --yes --location Columbus OH` |
| Cases | 500 (dataset sha256 8e337b334f20396d) |
| Rubric | version 1.1 · sha256 77829124a289f6b1 |
| Policy | withdrawal-policy/1.0.0 · approve > 0.8, confidence ≥ 0.5, review ≥ 0.3, takeover ≥ 0.5, ceiling $5,000 |
| TypeSafe Jev | https://openrouter.ai/api/v1/systemone (systemone) · model requested `typesafe/jev-1.13` · served `typesafe/jev-1.13-20260917` · $0.042/M input tokens |
| OpenAI Decisions | https://openrouter.ai/api/v1/systemone (systemone (OpenRouter)) · model requested `openai/gpt-6-luna-decisions` · served `openai/gpt-6-luna-decisions-20261006` · $0.1/M input tokens |
| Microsoft Decision-1 | https://openrouter.ai/api/v1/systemone (systemone) · model requested `microsoft/microsoft-decision-1` · served `microsoft/microsoft-decision-1-20261009` · $0.042/M input tokens |
| Concurrency / timeout / warm-up | 4 per provider / 30 s / 5 calls |
| Client location | Columbus OH |
| Code version | not a git checkout |
| Environment | Python 3.14.5 · Windows-11-10.0.26200-SP0 |

## Headline

|  | Metric | TypeSafe Jev | OpenAI Decisions | Microsoft Decision-1 |
| --- | --- | --- | --- | --- |
| Latency | p50 | 238 ms | 200 ms | 304 ms |
| Latency | p95 | 334 ms | 329 ms | 385 ms |
| Latency | p99 | 444 ms | 748 ms | 493 ms |
| Latency | p95 including retries | 334 ms | 329 ms | 385 ms |
| Latency | server-reported processing p50 | not reported | not reported | not reported |
| Cost | per 1,000 decisions (list price) | $0.0324 | $0.0611 | $0.0178 |
| Cost | per 1 million decisions | $32.45 | $61.09 | $17.75 |
| Cost | billed in this run | $0.09913 (provider says $0.09913) | $0.18661 (provider says $0.18661) | $0.05424 (provider says $0.05424) |
| Cost | input tokens per call | 773 | 611 | 423 |
| Cost | output tokens per call | 63.9 | 0.0 | 2.0 |
| Accuracy | route matches analyst label (all cases) | 92.2% | 77.4% | 90.8% |
| Accuracy | route accuracy (answered cases only) | 92.2% | 77.4% | 90.8% |
| Accuracy | route macro-F1 (each class weighted equally) | 88.0% | 71.4% | 87.4% |
| Accuracy | route balanced accuracy (mean recall per class) | 90.7% | 77.2% | 91.1% |
| Accuracy | final action matches label (same policy) | 83.2% | 73.6% | 79.0% |
| Accuracy | final action macro-F1 | 84.5% | 75.7% | 72.9% |
| Accuracy | fraud auto-approved | 0 | 0 | 0 |
| Accuracy | manual reviews (unnecessary) | 106 (2) | 112 (10) | 147 (50) |
| Calibration | ECE (lower is better) | 0.066 | 0.041 | 0.062 |
| Calibration | Brier score (lower is better) | 0.117 | 0.297 | 0.112 |
| Calibration | log loss (lower is better) | 0.198 | 0.458 | 0.191 |
| Calibration | top probability ≥ 0.95 | 53% | 32% | 49% |
| Calibration | takeover question AUC | 1.000 | 1.000 | 1.000 |
| Reliability | successful calls | 3000 / 3000 | 3000 / 3000 | 3000 / 3000 |
| Reliability | errors by kind | none | none | none |
| Reliability | calls that needed a retry | 0 | 0 | 0 |
| Robustness | same route in every option order | 91.8% (41 of 500 changed, 6 orders) | 64.2% (179 of 500 changed, 6 orders) | 97.2% (14 of 500 changed, 6 orders) |
| Robustness | same final action in every option order | 460 / 500 (92.0%) | 422 / 500 (84.4%) | 483 / 500 (96.6%) |
| Robustness | macro-F1 spread across option orders | 10.0% | 25.9% | 1.5% |
| Robustness | same answer when asked twice | same choice 50 / 50 (100%); identical probabilities 27 / 50 (54.0%); max change 0.080 | same choice 50 / 50 (100%); identical probabilities 50 / 50 (100%); max change 0.000 | same choice 49 / 50 (98.0%); identical probabilities 8 / 50 (16.0%); max change 0.122 |

## Same cases, side by side

Every pair of providers on the same cases (original option order). **Macro-F1** weights each route equally, so the largest class can't dominate (this set has 320 approve, 76 step-up, 104 manual review). The interval is a paired bootstrap over cases (2,000 resamples): if it excludes 0, the gap is not an artefact of which cases happened to be in the dataset.

| A vs B | Both right | Only A | Only B | Neither | Route agreement | Action agreement | Macro-F1 A / B | Difference (95% CI) | Separated? | A faster |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| TypeSafe Jev vs OpenAI Decisions | 377 | 84 | 10 | 29 | 81.2% | 76.0% | 88.0% / 71.4% | +16.7% (+12.7% to +20.5%) | yes | 25% |
| TypeSafe Jev vs Microsoft Decision-1 | 432 | 29 | 22 | 17 | 89.8% | 75.8% | 88.0% / 87.4% | +0.6% (-2.8% to +3.9%) | no | 88% |
| OpenAI Decisions vs Microsoft Decision-1 | 380 | 7 | 74 | 39 | 83.8% | 76.2% | 71.4% / 87.4% | -16.1% (-20.1% to -12.0%) | yes | 92% |

Ranking: **macro f1** TypeSafe Jev > Microsoft Decision-1 > OpenAI Decisions; **route accuracy** TypeSafe Jev > Microsoft Decision-1 > OpenAI Decisions; **latency p50** OpenAI Decisions > TypeSafe Jev > Microsoft Decision-1; **cost per 1k** Microsoft Decision-1 > TypeSafe Jev > OpenAI Decisions; **ece** OpenAI Decisions > Microsoft Decision-1 > TypeSafe Jev.


### Per-route precision, recall and F1 (original option order)

| Route | Cases | TypeSafe Jev precision | TypeSafe Jev recall | TypeSafe Jev F1 | OpenAI Decisions precision | OpenAI Decisions recall | OpenAI Decisions F1 | Microsoft Decision-1 precision | Microsoft Decision-1 recall | Microsoft Decision-1 F1 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Approve | 320 | 100% | 95% | 98% | 100% | 81% | 89% | 100% | 92% | 96% |
| Step-up | 76 | 66% | 100% | 80% | 40% | 100% | 57% | 62% | 100% | 77% |
| Manual review | 104 | 100% | 77% | 87% | 100% | 51% | 68% | 100% | 82% | 90% |

### Route accuracy by case type

| Case type | Cases | TypeSafe Jev | OpenAI Decisions | Microsoft Decision-1 |
| --- | --- | --- | --- | --- |
| account_takeover | 49 | 82% | 45% | 100% |
| ato_quiet | 22 | 100% | 77% | 95% |
| benign_notes | 33 | 100% | 73% | 97% |
| large_familiar | 27 | 93% | 37% | 56% |
| mule | 33 | 55% | 42% | 45% |
| new_device_legit | 43 | 100% | 100% | 100% |
| routine | 217 | 99% | 85% | 94% |
| traveler_no_notice | 33 | 100% | 100% | 100% |
| traveler_with_notice | 43 | 74% | 93% | 100% |

### Confusion matrix: TypeSafe Jev (rows = analyst label, columns = model's choice)

| Label \ answer | Approve | Step-up | Manual review | Error |
| --- | --- | --- | --- | --- |
| Approve | 305 | 15 | 0 | 0 |
| Step-up | 0 | 76 | 0 | 0 |
| Manual review | 0 | 24 | 80 | 0 |

### Confusion matrix: OpenAI Decisions (rows = analyst label, columns = model's choice)

| Label \ answer | Approve | Step-up | Manual review | Error |
| --- | --- | --- | --- | --- |
| Approve | 258 | 62 | 0 | 0 |
| Step-up | 0 | 76 | 0 | 0 |
| Manual review | 0 | 51 | 53 | 0 |

### Confusion matrix: Microsoft Decision-1 (rows = analyst label, columns = model's choice)

| Label \ answer | Approve | Step-up | Manual review | Error |
| --- | --- | --- | --- | --- |
| Approve | 293 | 27 | 0 | 0 |
| Step-up | 0 | 76 | 0 | 0 |
| Manual review | 0 | 19 | 85 | 0 |

## Calibration

When a model says 80%, is it right about 80% of the time? Bins are by the model's top probability.

**TypeSafe Jev**

| Top probability | Cases | Mean stated | Actually right |
| --- | --- | --- | --- |
| 0.0-0.2 | 0 | – | – |
| 0.2-0.4 | 0 | – | – |
| 0.4-0.6 | 67 | 54% | 54% |
| 0.6-0.8 | 86 | 69% | 91% |
| 0.8-1.0 | 347 | 96% | 100% |

**OpenAI Decisions**

| Top probability | Cases | Mean stated | Actually right |
| --- | --- | --- | --- |
| 0.0-0.2 | 0 | – | – |
| 0.2-0.4 | 0 | – | – |
| 0.4-0.6 | 73 | 54% | 52% |
| 0.6-0.8 | 124 | 69% | 60% |
| 0.8-1.0 | 303 | 93% | 91% |

**Microsoft Decision-1**

| Top probability | Cases | Mean stated | Actually right |
| --- | --- | --- | --- |
| 0.0-0.2 | 0 | – | – |
| 0.2-0.4 | 0 | – | – |
| 0.4-0.6 | 20 | 55% | 50% |
| 0.6-0.8 | 69 | 70% | 52% |
| 0.8-1.0 | 411 | 95% | 99% |

## Option-order check

Same case, same rubric, the three options listed in 6 different orders. A model that reads the content and not the order gives the same answer every time.

|  | TypeSafe Jev | OpenAI Decisions | Microsoft Decision-1 |
| --- | --- | --- | --- |
| Cases answered in every order | 500 | 500 | 500 |
| Same route in every order | 459 / 500 (91.8%) | 321 / 500 (64.2%) | 486 / 500 (97.2%) |
| Cases whose route changed | 41 | 179 | 14 |
| Distinct routes per case (1 / 2 / 3) | 459 / 41 / 0 | 321 / 179 / 0 | 486 / 14 / 0 |
| Same final action in every order | 460 / 500 (92.0%) | 422 / 500 (84.4%) | 483 / 500 (96.6%) |
| P(approve) range across orders, mean | 0.047 | 0.194 | 0.016 |
| P(approve) range across orders, p95 | 0.200 | 0.671 | 0.080 |
| Largest range, any option | 0.300 | 0.940 | 0.350 |
| Route accuracy, best − worst order | 6.6% | 26.8% | 1.2% |
| Macro-F1, best − worst order | 10.0% | 25.9% | 1.5% |

### By order

| Order (A = approve, S = step-up, M = manual review) | TypeSafe Jev accuracy | TypeSafe Jev macro-F1 | OpenAI Decisions accuracy | OpenAI Decisions macro-F1 | Microsoft Decision-1 accuracy | Microsoft Decision-1 macro-F1 |
| --- | --- | --- | --- | --- | --- | --- |
| A-S-M (original) | 92.2% | 88.0% | 77.4% | 71.4% | 90.8% | 87.4% |
| A-M-S | 97.0% | 95.3% | 83.0% | 77.0% | 91.0% | 87.3% |
| S-A-M | 96.0% | 93.8% | 61.4% | 60.6% | 90.4% | 86.8% |
| S-M-A | 98.0% | 96.9% | 63.0% | 64.8% | 91.2% | 87.7% |
| M-A-S | 97.4% | 95.4% | 88.2% | 86.6% | 90.4% | 86.8% |
| M-S-A (reversed) | 98.8% | 98.1% | 78.6% | 77.7% | 91.6% | 88.3% |

### Position bias (all six orders)

Across the six orders every option sits in every position equally often, so an order-blind model averages exactly 1/3 probability per position. A positive number means the model favours that slot.

| Position | TypeSafe Jev: mean P / bias / chosen | OpenAI Decisions: mean P / bias / chosen | Microsoft Decision-1: mean P / bias / chosen |
| --- | --- | --- | --- |
| listed 1st | 0.328 / -0.006 / 33% | 0.382 / +0.048 / 42% | 0.333 / -0.000 / 33% |
| listed 2nd | 0.338 / +0.004 / 34% | 0.332 / -0.002 / 32% | 0.333 / -0.000 / 33% |
| listed 3rd | 0.335 / +0.001 / 33% | 0.287 / -0.047 / 27% | 0.334 / +0.000 / 34% |

TypeSafe Jev, cases whose route changed (first 10): case-0000 (traveler_with_notice): A-S-M S, A-M-S A, S-A-M S, S-M-A A, M-A-S A, M-S-A A; case-0005 (mule): A-S-M S, A-M-S M, S-A-M S, S-M-A M, M-A-S S, M-S-A M; case-0012 (mule): A-S-M S, A-M-S S, S-A-M S, S-M-A M, M-A-S S, M-S-A M; case-0026 (mule): A-S-M S, A-M-S M, S-A-M M, S-M-A M, M-A-S M, M-S-A M; case-0030 (traveler_with_notice): A-S-M S, A-M-S S, S-A-M S, S-M-A S, M-A-S A, M-S-A A; case-0034 (mule): A-S-M S, A-M-S M, S-A-M M, S-M-A M, M-A-S M, M-S-A M; case-0050 (routine): A-S-M S, A-M-S A, S-A-M A, S-M-A A, M-A-S A, M-S-A A; case-0058 (mule): A-S-M M, A-M-S M, S-A-M S, S-M-A M, M-A-S S, M-S-A M; case-0068 (mule): A-S-M S, A-M-S S, S-A-M M, S-M-A M, M-A-S M, M-S-A S; case-0075 (mule): A-S-M M, A-M-S M, S-A-M M, S-M-A M, M-A-S M, M-S-A S

OpenAI Decisions, cases whose route changed (first 10): case-0000 (traveler_with_notice): A-S-M A, A-M-S A, S-A-M S, S-M-A S, M-A-S A, M-S-A A; case-0005 (mule): A-S-M S, A-M-S S, S-A-M S, S-M-A S, M-A-S M, M-S-A M; case-0013 (traveler_with_notice): A-S-M A, A-M-S A, S-A-M A, S-M-A S, M-A-S A, M-S-A A; case-0017 (traveler_with_notice): A-S-M A, A-M-S A, S-A-M S, S-M-A A, M-A-S A, M-S-A A; case-0018 (large_familiar): A-S-M A, A-M-S A, S-A-M S, S-M-A S, M-A-S A, M-S-A A; case-0021 (account_takeover): A-S-M M, A-M-S M, S-A-M S, S-M-A M, M-A-S M, M-S-A M; case-0024 (routine): A-S-M A, A-M-S A, S-A-M S, S-M-A S, M-A-S A, M-S-A S; case-0025 (routine): A-S-M A, A-M-S A, S-A-M S, S-M-A S, M-A-S A, M-S-A S; case-0026 (mule): A-S-M S, A-M-S S, S-A-M S, S-M-A S, M-A-S M, M-S-A M; case-0030 (traveler_with_notice): A-S-M A, A-M-S A, S-A-M S, S-M-A S, M-A-S A, M-S-A A

Microsoft Decision-1, cases whose route changed (first 10): case-0005 (mule): A-S-M M, A-M-S S, S-A-M M, S-M-A S, M-A-S M, M-S-A M; case-0066 (routine): A-S-M A, A-M-S A, S-A-M A, S-M-A A, M-A-S S, M-S-A A; case-0097 (routine): A-S-M A, A-M-S S, S-A-M S, S-M-A A, M-A-S A, M-S-A A; case-0163 (mule): A-S-M S, A-M-S M, S-A-M M, S-M-A M, M-A-S S, M-S-A M; case-0190 (ato_quiet): A-S-M M, A-M-S M, S-A-M M, S-M-A S, M-A-S M, M-S-A M; case-0213 (routine): A-S-M S, A-M-S A, S-A-M S, S-M-A A, M-A-S S, M-S-A S; case-0221 (routine): A-S-M S, A-M-S S, S-A-M S, S-M-A A, M-A-S S, M-S-A A; case-0223 (routine): A-S-M S, A-M-S A, S-A-M A, S-M-A A, M-A-S A, M-S-A A; case-0281 (large_familiar): A-S-M S, A-M-S A, S-A-M S, S-M-A S, M-A-S S, M-S-A S; case-0374 (ato_quiet): A-S-M M, A-M-S S, S-A-M S, S-M-A M, M-A-S M, M-S-A M

## Repeatability

The first cases asked a second time, identical request.

|  | TypeSafe Jev | OpenAI Decisions | Microsoft Decision-1 |
| --- | --- | --- | --- |
| Pairs | 50 | 50 | 50 |
| Same choice | 50 / 50 (100%) | 50 / 50 (100%) | 49 / 50 (98.0%) |
| Identical probabilities (all three, exact) | 27 / 50 (54.0%) | 50 / 50 (100%) | 8 / 50 (16.0%) |
| Largest probability change | 0.080 | 0.000 | 0.122 |
| Same final action | 50 / 50 (100%) | 50 / 50 (100%) | 50 / 50 (100%) |

## Confidence field

|  | TypeSafe Jev | OpenAI Decisions | Microsoft Decision-1 |
| --- | --- | --- | --- |
| Where confidence came from | api: 500 | api: 500 | api: 500 |
| Gap from (k·p_max−1)/(k−1), max | 0.0050 | 0.0050 | 0.0000 |
| Stated choice ≠ highest probability | 1 | 0 | 1 |

## Where they disagree (113 cases, first 25)

| Case | Type | Label | TypeSafe Jev | OpenAI Decisions | Microsoft Decision-1 |
| --- | --- | --- | --- | --- | --- |
| case-0000 | traveler_with_notice | Approve | Step-up | Approve | Approve |
| case-0005 | mule | Manual review | Step-up | Step-up | Manual review |
| case-0009 | benign_notes | Approve | Approve | Step-up | Approve |
| case-0011 | large_familiar | Approve | Approve | Step-up | Step-up |
| case-0030 | traveler_with_notice | Approve | Step-up | Approve | Approve |
| case-0031 | routine | Approve | Approve | Step-up | Step-up |
| case-0037 | mule | Manual review | Manual review | Manual review | Step-up |
| case-0042 | account_takeover | Manual review | Manual review | Step-up | Manual review |
| case-0054 | account_takeover | Manual review | Manual review | Step-up | Manual review |
| case-0058 | mule | Manual review | Manual review | Step-up | Manual review |
| case-0059 | benign_notes | Approve | Approve | Step-up | Approve |
| case-0061 | routine | Approve | Approve | Step-up | Approve |
| case-0062 | routine | Approve | Approve | Approve | Step-up |
| case-0066 | routine | Approve | Approve | Step-up | Approve |
| case-0075 | mule | Manual review | Manual review | Step-up | Step-up |
| case-0080 | mule | Manual review | Step-up | Step-up | Manual review |
| case-0087 | routine | Approve | Approve | Step-up | Approve |
| case-0089 | large_familiar | Approve | Approve | Step-up | Step-up |
| case-0091 | routine | Approve | Approve | Approve | Step-up |
| case-0097 | routine | Approve | Approve | Step-up | Approve |
| case-0098 | routine | Approve | Approve | Step-up | Approve |
| case-0104 | ato_quiet | Manual review | Manual review | Step-up | Manual review |
| case-0106 | large_familiar | Approve | Approve | Step-up | Approve |
| case-0107 | account_takeover | Manual review | Manual review | Step-up | Manual review |
| case-0114 | large_familiar | Approve | Approve | Step-up | Step-up |

## How to read this

- **Latency** is wall-clock time from this machine, per successful call, warm-up excluded. It includes the network path to each provider, which depends on where you ran it. Server-reported processing time is shown when a provider sends it in a response header.
- **Cost** is list price × the tokens each API reported. None of the APIs charges for output tokens. The tokenizers differ, so the same request can count as a different number of tokens.
- **Accuracy** is against synthetic analyst labels. It tells you how each model reads this rubric on these cases, not how it would do on your production traffic.
- **Final action** applies one fixed policy to every model. A model can pick the right route and still get a different action if its probabilities are more or less extreme. That is what the calibration rows explain.
- **One run** is one sample. Run it again on another day before quoting small differences.
- The OpenAI Decisions API is a public beta; behaviour and prices may change.
- Microsoft Decision-1 was released on 9 Oct 2026. Microsoft says its weights are updated continually and it may be rebased on other models, so pin the served model in each run's metadata when you quote it.
- Every call, with the full response body, is in `calls.jsonl` in this folder.
