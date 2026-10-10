# TypeSafe Jev vs OpenAI Decisions vs Microsoft Decision-1: run report

## Run

| Item | Value |
| --- | --- |
| Started (UTC) | 2026-10-10T00:41:37.502454+00:00 |
| Duration | 14.5 s |
| Command | `python -m compare.run --limit 20 --repeat 5 --label smoke2 --yes` |
| Cases | 20 (dataset sha256 8e337b334f20396d) |
| Rubric | version 1.1 · sha256 77829124a289f6b1 |
| Policy | withdrawal-policy/1.0.0 · approve > 0.8, confidence ≥ 0.5, review ≥ 0.3, takeover ≥ 0.5, ceiling $5,000 |
| TypeSafe Jev | https://openrouter.ai/api/v1/systemone (systemone) · model requested `typesafe/jev-1.13` · served `typesafe/jev-1.13-20260917` · $0.042/M input tokens |
| OpenAI Decisions | https://openrouter.ai/api/v1/systemone (systemone (OpenRouter)) · model requested `openai/gpt-6-luna-decisions` · served `openai/gpt-6-luna-decisions-20261006` · $0.1/M input tokens |
| Microsoft Decision-1 | https://openrouter.ai/api/v1/systemone (systemone) · model requested `microsoft/microsoft-decision-1` · served `microsoft/microsoft-decision-1-20261009` · $0.042/M input tokens |
| Concurrency / timeout / warm-up | 4 per provider / 30 s / 5 calls |
| Client location | not recorded (add --location) |
| Code version | not a git checkout |
| Environment | Python 3.14.5 · Windows-11-10.0.26200-SP0 |

## Headline

|  | Metric | TypeSafe Jev | OpenAI Decisions | Microsoft Decision-1 |
| --- | --- | --- | --- | --- |
| Latency | p50 | 229 ms | 222 ms | 302 ms |
| Latency | p95 | 335 ms | 381 ms | 461 ms |
| Latency | p99 | 390 ms | 423 ms | 573 ms |
| Latency | p95 including retries | 335 ms | 381 ms | 461 ms |
| Latency | server-reported processing p50 | not reported | not reported | not reported |
| Cost | per 1,000 decisions (list price) | $0.0325 | $0.0611 | $0.0178 |
| Cost | per 1 million decisions | $32.45 | $61.12 | $17.76 |
| Cost | billed in this run | $0.00422 (provider says $0.00422) | $0.00794 (provider says $0.00794) | $0.00231 (provider says $0.00231) |
| Cost | input tokens per call | 773 | 611 | 423 |
| Cost | output tokens per call | 63.7 | 0.0 | 2.0 |
| Accuracy | route matches analyst label (all cases) | 85.0% | 80.0% | 90.0% |
| Accuracy | route accuracy (answered cases only) | 85.0% | 80.0% | 90.0% |
| Accuracy | route macro-F1 (each class weighted equally) | 62.3% | 58.9% | 75.6% |
| Accuracy | route balanced accuracy (mean recall per class) | 75.7% | 73.6% | 86.8% |
| Accuracy | final action matches label (same policy) | 75.0% | 95.0% | 85.0% |
| Accuracy | final action macro-F1 | 79.2% | 95.0% | 76.4% |
| Accuracy | fraud auto-approved | 0 | 0 | 0 |
| Accuracy | manual reviews (unnecessary) | 3 (0) | 3 (0) | 3 (1) |
| Calibration | ECE (lower is better) | 0.104 | 0.130 | 0.099 |
| Calibration | Brier score (lower is better) | 0.163 | 0.202 | 0.134 |
| Calibration | log loss (lower is better) | 0.256 | 0.307 | 0.200 |
| Calibration | top probability ≥ 0.95 | 50% | 40% | 65% |
| Calibration | takeover question AUC | 1.000 | 1.000 | 1.000 |
| Reliability | successful calls | 120 / 120 | 120 / 120 | 120 / 120 |
| Reliability | errors by kind | none | none | none |
| Reliability | calls that needed a retry | 0 | 0 | 0 |
| Robustness | same route in every option order | 85.0% (3 of 20 changed, 6 orders) | 75.0% (5 of 20 changed, 6 orders) | 95.0% (1 of 20 changed, 6 orders) |
| Robustness | same final action in every option order | 100.0% | 70.0% | 100.0% |
| Robustness | macro-F1 spread across option orders | 20.0% | 19.9% | 13.3% |
| Robustness | same answer when asked twice | 100% same choice, 40% identical probabilities | 100% same choice, 100% identical probabilities | 100% same choice, 20% identical probabilities |

## Same cases, side by side

Every pair of providers on the same cases (original option order). **Macro-F1** weights each route equally, so the largest class can't dominate (this set has 16 approve, 1 step-up, 3 manual review). The interval is a paired bootstrap over cases (2,000 resamples): if it excludes 0, the gap is not an artefact of which cases happened to be in the dataset.

| A vs B | Both right | Only A | Only B | Neither | Route agreement | Action agreement | Macro-F1 A / B | Difference (95% CI) | Separated? | A faster |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| TypeSafe Jev vs OpenAI Decisions | 15 | 2 | 1 | 2 | 85.0% | 80.0% | 62.3% / 58.9% | +3.4% (-7.8% to +17.3%) | no | 30% |
| TypeSafe Jev vs Microsoft Decision-1 | 16 | 1 | 2 | 1 | 85.0% | 70.0% | 62.3% / 75.6% | -13.3% (-50.0% to +10.4%) | no | 85% |
| OpenAI Decisions vs Microsoft Decision-1 | 16 | 0 | 2 | 2 | 90.0% | 90.0% | 58.9% / 75.6% | -16.7% (-51.4% to +0.0%) | no | 95% |

Ranking: **macro f1** Microsoft Decision-1 > TypeSafe Jev > OpenAI Decisions; **route accuracy** Microsoft Decision-1 > TypeSafe Jev > OpenAI Decisions; **latency p50** OpenAI Decisions > TypeSafe Jev > Microsoft Decision-1; **cost per 1k** Microsoft Decision-1 > TypeSafe Jev > OpenAI Decisions; **ece** Microsoft Decision-1 > TypeSafe Jev > OpenAI Decisions.


### Per-route precision, recall and F1 (original option order)

| Route | Cases | TypeSafe Jev precision | TypeSafe Jev recall | TypeSafe Jev F1 | OpenAI Decisions precision | OpenAI Decisions recall | OpenAI Decisions F1 | Microsoft Decision-1 precision | Microsoft Decision-1 recall | Microsoft Decision-1 F1 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Approve | 16 | 100% | 94% | 97% | 100% | 88% | 93% | 100% | 94% | 97% |
| Step-up | 1 | 25% | 100% | 40% | 20% | 100% | 33% | 33% | 100% | 50% |
| Manual review | 3 | 100% | 33% | 50% | 100% | 33% | 50% | 100% | 67% | 80% |

### Route accuracy by case type

| Case type | Cases | TypeSafe Jev | OpenAI Decisions | Microsoft Decision-1 |
| --- | --- | --- | --- | --- |
| ato_quiet | 1 | 100% | 100% | 100% |
| benign_notes | 1 | 100% | 0% | 100% |
| large_familiar | 3 | 100% | 67% | 67% |
| mule | 2 | 0% | 0% | 50% |
| routine | 8 | 100% | 100% | 100% |
| traveler_no_notice | 1 | 100% | 100% | 100% |
| traveler_with_notice | 4 | 75% | 100% | 100% |

### Confusion matrix: TypeSafe Jev (rows = analyst label, columns = model's choice)

| Label \ answer | Approve | Step-up | Manual review | Error |
| --- | --- | --- | --- | --- |
| Approve | 15 | 1 | 0 | 0 |
| Step-up | 0 | 1 | 0 | 0 |
| Manual review | 0 | 2 | 1 | 0 |

### Confusion matrix: OpenAI Decisions (rows = analyst label, columns = model's choice)

| Label \ answer | Approve | Step-up | Manual review | Error |
| --- | --- | --- | --- | --- |
| Approve | 14 | 2 | 0 | 0 |
| Step-up | 0 | 1 | 0 | 0 |
| Manual review | 0 | 2 | 1 | 0 |

### Confusion matrix: Microsoft Decision-1 (rows = analyst label, columns = model's choice)

| Label \ answer | Approve | Step-up | Manual review | Error |
| --- | --- | --- | --- | --- |
| Approve | 15 | 1 | 0 | 0 |
| Step-up | 0 | 1 | 0 | 0 |
| Manual review | 0 | 1 | 2 | 0 |

## Calibration

When a model says 80%, is it right about 80% of the time? Bins are by the model's top probability.

**TypeSafe Jev**

| Top probability | Cases | Mean stated | Actually right |
| --- | --- | --- | --- |
| 0.0-0.2 | 0 | – | – |
| 0.2-0.4 | 0 | – | – |
| 0.4-0.6 | 5 | 55% | 40% |
| 0.6-0.8 | 3 | 68% | 100% |
| 0.8-1.0 | 12 | 97% | 100% |

**OpenAI Decisions**

| Top probability | Cases | Mean stated | Actually right |
| --- | --- | --- | --- |
| 0.0-0.2 | 0 | – | – |
| 0.2-0.4 | 0 | – | – |
| 0.4-0.6 | 3 | 54% | 33% |
| 0.6-0.8 | 3 | 71% | 33% |
| 0.8-1.0 | 14 | 94% | 100% |

**Microsoft Decision-1**

| Top probability | Cases | Mean stated | Actually right |
| --- | --- | --- | --- |
| 0.0-0.2 | 0 | – | – |
| 0.2-0.4 | 0 | – | – |
| 0.4-0.6 | 1 | 49% | 100% |
| 0.6-0.8 | 3 | 70% | 33% |
| 0.8-1.0 | 16 | 98% | 100% |

## Option-order check

Same case, same rubric, the three options listed in 6 different orders. A model that reads the content and not the order gives the same answer every time.

|  | TypeSafe Jev | OpenAI Decisions | Microsoft Decision-1 |
| --- | --- | --- | --- |
| Cases answered in every order | 20 | 20 | 20 |
| Same route in every order | 85.0% | 75.0% | 95.0% |
| Cases whose route changed | 3 | 5 | 1 |
| Distinct routes per case (1 / 2 / 3) | 17 / 3 / 0 | 15 / 5 / 0 | 19 / 1 / 0 |
| Same final action in every order | 100.0% | 70.0% | 100.0% |
| P(approve) range across orders, mean | 0.059 | 0.240 | 0.008 |
| P(approve) range across orders, p95 | 0.181 | 0.735 | 0.025 |
| Largest range, any option | 0.200 | 0.830 | 0.123 |
| Route accuracy, best − worst order | 10.0% | 20.0% | 5.0% |
| Macro-F1, best − worst order | 20.0% | 19.9% | 13.3% |

### By order

| Order (A = approve, S = step-up, M = manual review) | TypeSafe Jev accuracy | TypeSafe Jev macro-F1 | OpenAI Decisions accuracy | OpenAI Decisions macro-F1 | Microsoft Decision-1 accuracy | Microsoft Decision-1 macro-F1 |
| --- | --- | --- | --- | --- | --- | --- |
| A-S-M (original) | 85.0% | 62.3% | 80.0% | 58.9% | 90.0% | 75.6% |
| A-M-S | 85.0% | 62.3% | 80.0% | 58.9% | 85.0% | 62.3% |
| S-A-M | 85.0% | 62.3% | 65.0% | 51.2% | 90.0% | 75.6% |
| S-M-A | 95.0% | 82.2% | 65.0% | 51.2% | 85.0% | 62.3% |
| M-A-S | 90.0% | 66.7% | 85.0% | 71.1% | 90.0% | 75.6% |
| M-S-A (reversed) | 95.0% | 82.2% | 85.0% | 71.1% | 85.0% | 62.3% |

### Position bias (all six orders)

Across the six orders every option sits in every position equally often, so an order-blind model averages exactly 1/3 probability per position. A positive number means the model favours that slot.

| Position | TypeSafe Jev: mean P / bias / chosen | OpenAI Decisions: mean P / bias / chosen | Microsoft Decision-1: mean P / bias / chosen |
| --- | --- | --- | --- |
| listed 1st | 0.323 / -0.010 / 32% | 0.392 / +0.059 / 40% | 0.334 / +0.001 / 33% |
| listed 2nd | 0.338 / +0.004 / 33% | 0.319 / -0.014 / 30% | 0.332 / -0.001 / 32% |
| listed 3rd | 0.339 / +0.006 / 34% | 0.289 / -0.044 / 30% | 0.334 / +0.000 / 34% |

TypeSafe Jev, cases whose route changed (first 10): case-0000 (traveler_with_notice): A-S-M S, A-M-S S, S-A-M S, S-M-A A, M-A-S A, M-S-A A; case-0005 (mule): A-S-M S, A-M-S S, S-A-M S, S-M-A S, M-A-S S, M-S-A M; case-0012 (mule): A-S-M S, A-M-S S, S-A-M S, S-M-A M, M-A-S S, M-S-A S

OpenAI Decisions, cases whose route changed (first 10): case-0000 (traveler_with_notice): A-S-M A, A-M-S A, S-A-M S, S-M-A S, M-A-S A, M-S-A A; case-0005 (mule): A-S-M S, A-M-S S, S-A-M S, S-M-A S, M-A-S M, M-S-A M; case-0013 (traveler_with_notice): A-S-M A, A-M-S A, S-A-M A, S-M-A S, M-A-S A, M-S-A A; case-0017 (traveler_with_notice): A-S-M A, A-M-S A, S-A-M S, S-M-A A, M-A-S A, M-S-A A; case-0018 (large_familiar): A-S-M A, A-M-S A, S-A-M S, S-M-A S, M-A-S A, M-S-A A

Microsoft Decision-1, cases whose route changed (first 10): case-0005 (mule): A-S-M M, A-M-S S, S-A-M M, S-M-A S, M-A-S M, M-S-A S

## Repeatability

The first cases asked a second time, identical request.

|  | TypeSafe Jev | OpenAI Decisions | Microsoft Decision-1 |
| --- | --- | --- | --- |
| Pairs | 5 | 5 | 5 |
| Same choice | 100% | 100% | 100% |
| Identical probabilities | 40% | 100% | 20% |
| Largest probability change | 0.010 | 0.000 | 0.002 |
| Same final action | 100% | 100% | 100% |

## Confidence field

|  | TypeSafe Jev | OpenAI Decisions | Microsoft Decision-1 |
| --- | --- | --- | --- |
| Where confidence came from | api: 20 | api: 20 | api: 20 |
| Gap from (k·p_max−1)/(k−1), max | 0.0050 | 0.0050 | 0.0000 |
| Stated choice ≠ highest probability | 0 | 0 | 1 |

## Where they disagree (4 cases, first 25)

| Case | Type | Label | TypeSafe Jev | OpenAI Decisions | Microsoft Decision-1 |
| --- | --- | --- | --- | --- | --- |
| case-0000 | traveler_with_notice | Approve | Step-up | Approve | Approve |
| case-0005 | mule | Manual review | Step-up | Step-up | Manual review |
| case-0009 | benign_notes | Approve | Approve | Step-up | Approve |
| case-0011 | large_familiar | Approve | Approve | Step-up | Step-up |

## How to read this

- **Latency** is wall-clock time from this machine, per successful call, warm-up excluded. It includes the network path to each provider, which depends on where you ran it. Server-reported processing time is shown when a provider sends it in a response header.
- **Cost** is list price × the tokens each API reported. None of the APIs charges for output tokens. The tokenizers differ, so the same request can count as a different number of tokens.
- **Accuracy** is against synthetic analyst labels. It tells you how each model reads this rubric on these cases, not how it would do on your production traffic.
- **Final action** applies one fixed policy to every model. A model can pick the right route and still get a different action if its probabilities are more or less extreme. That is what the calibration rows explain.
- **One run** is one sample. Run it again on another day before quoting small differences.
- The OpenAI Decisions API is a public beta; behaviour and prices may change.
- Microsoft Decision-1 was released on 9 Oct 2026. Microsoft says its weights are updated continually and it may be rebased on other models, so pin the served model in each run's metadata when you quote it.
- Every call, with the full response body, is in `calls.jsonl` in this folder.
