# Jev vs OpenAI Decisions vs Microsoft Decision-1

A narrow, reproducible head-to-head between three **decision APIs**: models that answer a typed question with a fixed set of options and probabilities instead of generating text.

| | TypeSafe Jev | OpenAI Decisions API | Microsoft Decision-1 |
|---|---|---|---|
| Endpoint | `POST /v1/systemone` (direct or OpenRouter) | `POST /v1/systemone` (OpenRouter) or `POST /v1/decisions` (direct) | `POST /v1/systemone` (OpenRouter) or `/providers/microsoft/v1/systemone` (Foundry) |
| Model | `jev-1.13` | `openai/gpt-6-luna-decisions` (OpenRouter) / `gpt-6-luna` (direct) | `microsoft/microsoft-decision-1` (post-trained Qwen3.5-9B) |
| Status (Oct 2026) | Generally available (also on OpenRouter) | Public beta since 6 Oct 2026 | Released 9 Oct 2026; GA in Foundry, also on OpenRouter |
| List price | $0.042 per million input tokens, output free | $0.10 per million input tokens, output free | $0.042 per million input tokens, output free |

All three get **the same question about the same cases, with the same rubric text**, and every answer goes through **the same deterministic policy**. The benchmark measures:

| | What | How |
|---|---|---|
| ⏱ | **Latency** | p50 / p90 / p95 / p99 wall-clock per call, warm-up excluded; provider-reported processing time when a header carries it |
| 💲 | **Cost** | list price × the tokens each API reports; per call, per 1,000 and per 1 million decisions; the provider's own figure when it returns one |
| 🎯 | **Accuracy** | the model's route vs an analyst label, as plain accuracy **and macro-F1** (the classes are imbalanced); the final action after the same policy; fraud auto-approved; unnecessary manual reviews; breakdown by case type; a paired-bootstrap 95% interval on the gap between **every pair** of models |
| 📏 | **Calibration** | ECE, Brier score, log loss, how often the top probability is ≥ 0.95, AUC on the takeover question |
| 🔁 | **Robustness** | the same case with the options listed in **all six possible orders** (does the order change the answer? is there a position bias?), the same case **asked twice**, and the **whole benchmark run twice** (does the conclusion survive?) |
| 🧱 | **Reliability** | success rate, errors by kind (HTTP, timeout, schema, refusal), retries |

It grew out of the [Jev Decision Gateway](https://github.com/kartikanand73/jev-decision-gateway) (Pattern #15 in the *Enterprise AI Architecture Patterns* series), where Jev scores withdrawal-routing decisions inside a governed workflow. This repo strips that down to one question: **given the same decision, how do the decision APIs compare?**

**Vendor claims this benchmark can check.** Microsoft says Decision-1 has zero flips when options are reordered, and a p50 about 35× faster than GPT-6 Sol. OpenRouter shows a 0.21 s p50 for it. Early OpenAI beta testers reported overconfident `choice` probabilities and sensitivity to option order. The six-order check, the calibration section and the latency percentiles test each of these claims on the same cases.

## The question

A bank withdrawal has already passed its hard checks (funds, limits, KYC). Each model is asked two things in one call:

1. **Route**: `approve` | `step_up_verification` | `manual_review`, each with a written description (`compare/rubric.py`)
2. **Account takeover**: the probability that someone other than the owner is acting

The policy (`compare/policy.py`, the same thresholds as the gateway) turns the answer into an action:

```
P(manual_review) ≥ 0.30 or P(takeover) ≥ 0.50                  → manual review
P(approve) > 0.80 and confidence ≥ 0.50 and amount ≤ $5,000    → approve
otherwise                                                      → step-up verification
an error, timeout, refusal or invalid answer                   → manual review (fail safe)
```

Because the policy acts on the probabilities, two models can pick the same route and still produce different actions. A model that is always 98% sure behaves differently under these thresholds from one that is 75% sure. That is why calibration is measured alongside accuracy.

## What each API receives

**Recommended: all three through OpenRouter.** OpenRouter serves all three models on its decisions API (`/v1/systemone`), so every provider gets a **byte-for-byte identical request apart from the model id**, over the same network route, billed through the same account. That removes the request format and the network route as explanations, so differences come from the models and how each vendor serves them behind OpenRouter.

| Provider | Base URL | Model id |
|---|---|---|
| Jev | `https://openrouter.ai/api` | `typesafe/jev-1.13` |
| OpenAI | `https://openrouter.ai/api` | `openai/gpt-6-luna-decisions` |
| Microsoft | `https://openrouter.ai/api` | `microsoft/microsoft-decision-1` |

OpenRouter forwards each request to the vendor (TypeSafe, OpenAI's Decisions API, Azure), so there is still one extra hop compared with calling a vendor directly, but it is the same hop for all three.

**Calling OpenAI directly** (`OPENAI_BASE_URL=https://api.openai.com/v1`) uses OpenAI's own format instead. These are the differences it forces:

| | System One (Jev, Microsoft, OpenAI via OpenRouter) | OpenAI direct |
|---|---|---|
| Program state | `state`: a JSON object | `input`: the same JSON, as text |
| Route question | `choice` with `criteria` `{route: description}` | `choice` with `choices` `[{value, description}]` |
| Takeover question | `noul` with `criteria` `{true, false}` | `predicate`; it has no criteria field, so the true/false descriptions are appended to `instructions` |
| Confidence | returned | returned; every provider's is checked against (k·p_max−1)/(k−1) |

See it for yourself: `python -m compare.ask --raw` prints every exact request and every full response.

**About the Microsoft endpoint.** Microsoft hasn't published Decision-1's wire format yet. Through OpenRouter it is served on the same decisions endpoint as Jev. For Foundry, the path `/providers/microsoft/v1/systemone` with a Bearer key is the one the Foundry playground uses, as documented in [LiteLLM PR #45673](https://github.com/BerriAI/litellm/pull/45673). If Microsoft documents a different one, set `MSD_PATH`.

## Data

`data/cases.jsonl`: 500 synthetic cases (seed 505), each with an analyst label for the route, the final action and (where it is not ambiguous) takeover.

| Case type | Share | Expected route | Why it's there |
|---|---|---|---|
| routine, benign_notes | 50% | approve | plain approvals |
| traveler_with_notice | 9% | approve | approval readable **only** from the free-text notes |
| large_familiar | 5% | approve (policy ceiling makes it step-up) | right route, policy still adds friction |
| traveler_no_notice, new_device_legit | 15% | step-up | genuine ambiguity |
| account_takeover, mule | 16% | manual review | classic fraud patterns |
| ato_quiet | 4% | manual review | takeover visible **only** in the notes |

The classes are imbalanced: **320 approve, 76 step-up, 104 manual review** by route. Plain accuracy rewards a model that is good at approvals and weak on step-ups, so the report also gives **macro-F1** (the average of the per-class F1 scores, each class counting equally), **balanced accuracy** (the average per-class recall), and per-class precision, recall and F1.

Regenerate or make a fresh set: `python -m compare.dataset --n 500 --seed 606 --out data/cases_b.jsonl`.

## Quick start

```bash
git clone https://github.com/kartikanand73/decision-api-benchmark.git
cd decision-api-benchmark
python -m venv .venv
source .venv/bin/activate              # Git Bash on Windows: source .venv/Scripts/activate · PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env                   # Windows: copy .env.example .env   then add your keys
python -m pytest -q                    # 54 tests, no keys needed
```

`.env` is loaded automatically, so there's no need to export variables in bash or PowerShell.

**All three through OpenRouter** (the fairest setup). Each provider follows the same pattern, key, base URL and model, with the same OpenRouter key:

```dotenv
TYPESAFE_API_KEY=sk-or-...
TYPESAFE_BASE_URL=https://openrouter.ai/api
JEV_MODEL=typesafe/jev-1.13

OPENAI_API_KEY=sk-or-...
OPENAI_BASE_URL=https://openrouter.ai/api
DECISIONS_MODEL=openai/gpt-6-luna-decisions

MSD_API_KEY=sk-or-...
MSD_BASE_URL=https://openrouter.ai/api
MSD_MODEL=microsoft/microsoft-decision-1
```

A key and its base URL must match: an OpenRouter key needs the OpenRouter base URL beside it. (Shortcut: `OPENROUTER_API_KEY=...` on its own also routes all three through OpenRouter.)

Each run records the route and wire format of every provider in `meta.json` and in the report's Run table, so a reader can see how each model was called.

- **OpenAI direct** instead: set `OPENAI_API_KEY` to your OpenAI key (the default base for an own key is `https://api.openai.com/v1`, model `gpt-6-luna`).
- **Microsoft Decision-1 via Foundry:** deploy the model under any name except `Microsoft-Decision-1` (Azure reserves it), then set `MSD_BASE_URL=https://<resource>.services.ai.azure.com`, `MSD_MODEL=<deployment name>` and `MSD_API_KEY=<Foundry key>`.
- **Without access to one of them**, run the others with `--providers jev,microsoft` (or any subset).

### 1. One question, every API

```bash
python -m compare.ask                          # first case
python -m compare.ask --archetype ato_quiet    # a takeover that is only visible in the notes
python -m compare.ask --case case-0042 --raw   # exact requests + full responses
python -m compare.ask --order SAM              # same case, options listed step-up, approve, review
python -m compare.ask --file my_case.json      # your own withdrawal
```

```
                              TypeSafe Jev            OpenAI Decisions        Microsoft Decision-1
  choice                      manual review           manual review           manual review
    P(approve)                …                       …                       …
  confidence (source)         …                       …                       …
  P(account takeover)         …                       …                       …
  policy action               …                       …                       …
  latency                     … ms                    … ms                    … ms
  tokens in / out             … / 0                   … / 0                   … / 0
  cost per 1k at this size    $…                      $…                      $…
```

### 2. The benchmark

```bash
python -m compare.run --mock                         # pipeline check, no keys (numbers are fake)
python -m compare.run --limit 20 --label smoke       # small live run
python -m compare.run --label full --location "Columbus OH"
```

A full run asks every case in **all six option orders**: **500 cases × 6 orders + 50 repeats + 5 warm-ups = 3,055 calls per provider**. At about 750 input tokens per call that's roughly **$0.10 on Jev, $0.23 on OpenAI and $0.10 on Microsoft** per run, about $0.43 in total. It asks for confirmation before any live run over 400 calls (`--yes` skips the prompt).

Useful options: `--providers jev,microsoft` (any subset), `--orders both` (original + reversed only) or `--orders original` (no order check), `--repeat 0`, `--concurrency 4`, `--timeout 30`, `--data <file>`.

### 3. Run it again: does the conclusion hold?

```bash
python -m compare.run --label run1 --yes --location "Columbus OH"
python -m compare.run --label run2 --yes --location "Columbus OH"     # ideally a different hour or day
python -m compare.compare_runs runs/*-run1 runs/*-run2              # folder names without < >
```

`compare_runs` writes `runs/compare-<stamp>/comparison.md`, which has:

- **Uncertainty.** 95% intervals for every pairwise difference in macro-F1, accuracy, p50 and p95 latency, both pooled across runs and for each run separately, plus each provider's own intervals. They come from a case-resampling bootstrap that keeps the comparison paired. The pooled version keeps each case's answers from every run together, so it covers both which cases were sampled and run-to-run variation. Neither covers a change in conditions between runs (time of day, network, a model update), which the per-run rows let you see.
- **Ranking in each run.** The best provider on each metric per run, labelled as a point estimate. A small real difference can swap rank between finite runs, and an unchanged rank doesn't by itself show a real difference, so read the ranking next to the intervals.
- Every metric in every run, with the spread between runs.
- **Case-level drift.** How often each provider gave the same route, and exactly the same probabilities, to the same case in different runs, shown as counts (e.g. `499 / 500`) so nothing is rounded up to 100%.

### How the order check works

With three options there are six ways to list them (A = approve, S = step-up, M = manual review): **A-S-M** (original), A-M-S, S-A-M, S-M-A, M-A-S, **M-S-A** (reversed). The report shows:

- **Consistency.** Share of cases with the same route in all six orders, how many distinct routes each case received (1, 2 or 3), and whether the final action stayed the same.
- **Size of the swing.** The range of P(approve) across orders, and each order's own accuracy and macro-F1, with the best−worst spread.
- **Position bias.** Across the six orders every option sits in every position exactly twice, so a model that ignores order averages exactly 1/3 probability per position. Anything above 1/3 means the model favours that slot, typically the first or last listed.

### Fairness rules built in

- Same cases, same rubric, same policy, same HTTP stack, timeout and retry policy for every provider.
- Warm-up calls per provider are made first and excluded, so connection setup isn't timed.
- All calls for all providers are **shuffled together** with a fixed seed and run at the same concurrency, so none is always measured first or at a quieter moment.
- Latency is measured from your machine, so it includes your network path to each provider. Record where you ran it with `--location`. When a provider reports its own processing time in a header (OpenAI sends `openai-processing-ms`), the report shows it separately.

## What a run leaves behind

```
runs/20261008-153000Z-full/
  calls.jsonl     every API call: request id, order, latency, tokens, cost, parsed answer, full response body
  summary.json    every metric in the report
  report.md       renders on GitHub
  report.html     self-contained page for screenshots (light and dark mode)
  console.txt     the terminal summary
  meta.json       command, models requested and served, prices, dataset and rubric fingerprints, policy, git commit
```

`python -m compare.report runs/<folder>` rebuilds both reports from the saved JSON. Mock runs are git-ignored; commit the live run folders you cite.

## Results

Two full runs on 10 October 2026 (UTC), about two hours apart, from Columbus, Ohio. All three providers were called through OpenRouter with byte-identical requests apart from the model id:

| Provider | Model served |
|---|---|
| Jev | `typesafe/jev-1.13-20260917` |
| OpenAI | `openai/gpt-6-luna-decisions-20261006` |
| Microsoft | `microsoft/microsoft-decision-1-20261009` |

Each run sent 500 cases in 6 option orders, plus repeats: 9,165 calls per run, with no errors and no retries in either run. Evidence:
- Run 1: [report](runs/20261010-004439Z-or-run1/report.md) · [folder](runs/20261010-004439Z-or-run1/) (every call with its full response in `calls.jsonl`)
- Run 2: [report](runs/20261010-023836Z-or-run2/report.md) · [folder](runs/20261010-023836Z-or-run2/)
- Run-to-run comparison, with intervals and drift: the `runs/compare-…` folder (`comparison.md`)

Intervals are 95% case-resampling bootstrap intervals pooled across both runs. Accuracy figures use the original option order (approve, step-up, review).

| | TypeSafe Jev | OpenAI Decisions | Microsoft Decision-1 |
|---|---|---|---|
| Route macro-F1 | **89.2%** (86.1–92.1) | 71.4% (66.7–75.5) | **87.6%** (83.9–90.8) |
| Route accuracy | **92.8%** (90.8–94.7) | 77.4% (73.6–81.0) | **91.0%** (88.4–93.4) |
| Fraud auto-approved | 0 | 0 | 0 |
| Unnecessary manual reviews, run 1 / run 2 | 1 / 2 | 10 / 10 | 51 / 50 |
| Latency p50 | 233 ms | **214 ms** | 303 ms |
| Latency p95 | **321 ms** | 335 ms | 383 ms |
| Cost per 1,000 decisions | $0.0324 | $0.0611 | **$0.0178** |
| Input tokens per call (same request) | 773 | 611 | 423 |
| Brier score (lower is better) | 0.117 | 0.296 | **0.112–0.115** |
| Same route in all 6 option orders | 91.6–91.8% | 64.2% | **97.2–97.6%** |
| Macro-F1, best − worst option order | 8–10 pts | 25.9 pts | **1.2–1.5 pts** |
| Same route for the same case in both runs | 476 / 500 | **500 / 500** | 496 / 500 |

**Pairwise differences, pooled across both runs (A − B):**

| A − B | Macro-F1 | Latency p50 | Separated? |
|---|---|---|---|
| Jev − OpenAI | +17.8 pts (+14.2 to +21.9) | +20 ms (+18 to +21) | yes, on both |
| Microsoft − OpenAI | +16.2 pts (+12.3 to +20.3) | +89 ms (+87 to +90) | yes, on both |
| Jev − Microsoft | +1.7 pts (−1.8 to +5.2) | −69 ms (−71 to −68) | latency only; **macro-F1 not separated** |

**What the runs show**

1. **Option order changes decisions, most of all for OpenAI.** Listing the same three options in a different order changed OpenAI's route on 179 of 500 cases, in both runs. Its macro-F1 ranges from 60.6% to 86.6% depending on the order, and the first-listed option gets 0.38 average probability against a neutral 0.33. Jev changed route on 41–42 cases and Microsoft on 12–14. **Treat option order as configuration: pin it, version it with the rubric, and test across orders before changing model or rubric.**
2. **Jev and Microsoft are statistically tied on accuracy; both are well ahead of OpenAI.** The Jev − Microsoft gap includes zero in each run and pooled.
3. **Every error was cautious.** All three had 100% precision on approve and manual review and approved no fraud. Every mistake moved a case towards step-up.
4. **Same thresholds, different actions.** Microsoft picks the right route about as often as Jev, but under the same policy it sends around 50 legitimate cases per run to manual review, against 1–2 for Jev. The thresholds were set with Jev-shaped probabilities. **A shared typed contract makes models swappable in format, not in behaviour, so recalibrate thresholds per vendor.**
5. **Microsoft is cheapest because of its tokenizer, not its price.** It has the same list price as Jev and received the same request, but counted 423 tokens to Jev's 773.
6. **Repeatability differs.** OpenAI returned identical probabilities for 498 of 500 cases across runs. Microsoft kept the same route for 496 of 500, with small probability changes. Jev changed route on 24 of 500 cases between runs. For audited decisions, "same input, same answer" is worth checking.
7. **Latency is close and moves with conditions.** OpenAI's p50 went from 224 to 200 ms between runs and Jev's from 229 to 238 ms, so the Jev − OpenAI p50 gap was +5 ms in run 1 and +38 ms in run 2. Each run's own interval is narrow, so the change reflects conditions (time, network), which no single-run interval captures. Jev has the best tail in run 1; Microsoft is consistently about 70–90 ms slower.

**Vendor claims, checked on these cases:**
- **Microsoft, "zero flips for reordered options":** close, but not zero. 2.4–2.8% of cases changed route, with no measurable position bias.
- **OpenRouter's listed 0.21 s p50 for Microsoft:** 0.30 s measured from Columbus.
- **OpenAI beta testers, "choice order changes the probabilities":** confirmed.
- **OpenAI beta testers, "choice answers are overconfident":** not seen at the top end. OpenAI had the fewest answers at ≥ 0.95 (32%), though in the 0.6–0.8 band it was right 60% of the time when it said 69%.

**Read with care:** these are synthetic cases with synthetic labels, from two runs on one evening, through one route (OpenRouter). OpenAI's model was reached through OpenRouter's request format, which OpenRouter translates for OpenAI's Decisions API; repeating the six-order check directly against `api.openai.com` would show how much of OpenAI's order sensitivity, if any, comes from that translation. The headline accuracy uses one option order, which happens to be Jev's weakest of the six and mid-range for OpenAI; per-order results are in each `report.md`.

## Reading the results honestly

- **Synthetic labels.** Accuracy measures how each model reads *this rubric* on *these cases*, not production performance.
- **One run is one sample.** Run it twice and use `compare_runs`. Report a difference with its interval. An interval that includes zero means these runs can't separate the providers on that metric, whatever the ranks say.
- **Network matters.** p50 from Ohio is not p50 from Frankfurt, and OpenRouter adds a hop that a direct call doesn't. Routing all three through OpenRouter puts them on the same path; mixing routes (one direct, two via OpenRouter) biases latency. Each report's Run table shows the route each provider took.
- **Tokenizers differ.** The same request can count as a different number of tokens on each API; cost uses each provider's own count.
- **New and moving.** The OpenAI Decisions API is in public beta. Microsoft Decision-1 launched on 9 Oct 2026; Microsoft says its weights are updated continually and it may be rebased on other models. Its $0.042 price comes from Microsoft's announcement and OpenRouter's listing. Each run's `meta.json` and report record the served model so results stay attributable. Early testers [reported](https://community.openai.com/t/decisions-api-is-now-available-in-public-beta/1403877) overconfident `choice` probabilities and sensitivity to option order; the calibration and option-order sections exist to test exactly that.
- **Mocks prove the plumbing, not the models.** Mock answers are built from the labels plus noise and are order-invariant by construction.

## Layout

```
compare/
  rubric.py      the question, criteria and program state (shared by all)
  providers.py   Jev, OpenAI and Microsoft clients: wire formats, strict parsers, identical timing and retries, mocks
  policy.py      the deterministic policy applied to all
  dataset.py     labelled case generator
  metrics.py     every number in the report, from calls.jsonl
  report.py      report.md + report.html
  run.py         the benchmark
  compare_runs.py  two or more runs side by side, with bootstrap intervals for every difference
  ask.py         one case, every API, side by side
data/cases.jsonl
tests/           wire formats, parser strictness, HTTP failure handling, macro-F1, bootstrap, position-bias detection,
                 end-to-end mock run, run-to-run comparison
```

## References

- [OpenAI Decisions API guide](https://developers.openai.com/api/docs/guides/decisions)
- [Microsoft-Decision-1 announcement](https://commandline.microsoft.com/microsoft-decision-1-model-foundry/) · [Foundry catalog](https://ai.azure.com/catalog/models/Microsoft-Decision-1) · [OpenRouter](https://openrouter.ai/microsoft/microsoft-decision-1)
- [TypeSafe API docs](https://docs.typesafe.ai/api)
- [Jev Decision Gateway](https://github.com/kartikanand73/jev-decision-gateway)

*No affiliation with TypeSafe, OpenAI or Microsoft. All API usage is paid for by the author.* MIT licence.
