"""Every number in the report, computed from the raw call log (calls.jsonl) and the case labels.

Conventions
-----------
* Accuracy, calibration and agreement use the ORIGINAL option order ("measure" phase), one answer per case.
* Latency uses every successful measure-phase call (both orders): same work, more samples.
* Warm-up calls are excluded from every metric but included in "billed in this run".
* A failed call counts as wrong for accuracy over all cases, and fails safe to manual review in the policy.
"""

from __future__ import annotations

import math
import statistics
from collections import Counter, defaultdict

from .policy import Thresholds, decide
from .rubric import ORDERS, ROUTES, ordered_routes

ACTIONS = ("approve", "step_up_verification", "manual_review")


def pct(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    k = (len(xs) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def _mean(xs: list[float]) -> float | None:
    return statistics.fmean(xs) if xs else None


def auc(scores: list[float], labels: list[bool]) -> float | None:
    """Probability a random positive scores above a random negative (ties count half)."""
    pos = [s for s, y in zip(scores, labels) if y]
    neg = [s for s, y in zip(scores, labels) if not y]
    if not pos or not neg:
        return None
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def calibration(items: list[tuple[float, bool]], bins: int = 5) -> dict:
    buckets: list[list[tuple[float, bool]]] = [[] for _ in range(bins)]
    for p, ok in items:
        buckets[min(bins - 1, int(p * bins))].append((p, ok))
    table, ece = [], 0.0
    for i, b in enumerate(buckets):
        if not b:
            table.append({"bin": f"{i / bins:.1f}-{(i + 1) / bins:.1f}", "n": 0, "mean_conf": None, "accuracy": None})
            continue
        mc, acc = statistics.fmean(p for p, _ in b), sum(ok for _, ok in b) / len(b)
        ece += len(b) / max(1, len(items)) * abs(mc - acc)
        table.append({"bin": f"{i / bins:.1f}-{(i + 1) / bins:.1f}", "n": len(b), "mean_conf": mc, "accuracy": acc})
    return {"ece": ece if items else None, "table": table}


def class_scores(pairs: list[tuple[str, str | None]], classes=ROUTES) -> dict:
    """Per-class precision / recall / F1, macro-F1 and balanced accuracy.

    pairs = (expected, predicted); predicted None means the call failed: it counts against recall
    for the expected class and against no class's precision.
    """
    per = {}
    for k in classes:
        tp = sum(e == k and p == k for e, p in pairs)
        fp = sum(e != k and p == k for e, p in pairs)
        fn = sum(e == k and p != k for e, p in pairs)
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        per[k] = {"support": tp + fn, "precision": prec, "recall": rec,
                  "f1": 2 * prec * rec / (prec + rec) if prec + rec else 0.0}
    present = [k for k in classes if per[k]["support"]]
    return {"per_class": per,
            "macro_f1": statistics.fmean(per[k]["f1"] for k in present) if present else None,
            "balanced_accuracy": statistics.fmean(per[k]["recall"] for k in present) if present else None}


def macro_f1(pairs: list[tuple[str, str | None]], classes=ROUTES) -> float | None:
    return class_scores(pairs, classes)["macro_f1"]


def _action(c: dict, case: dict, t: Thresholds) -> tuple[str, list[str]]:
    return decide(case["request"]["amount"], c.get("probs"), c.get("confidence"), c.get("takeover"), t)


def provider_metrics(calls: list[dict], cases: list[dict], t: Thresholds) -> dict:
    by_case = {c["id"]: c for c in cases}
    measure = [c for c in calls if c["phase"] == "measure"]
    orig = {c["case_id"]: c for c in measure if c["order"] == "original"}
    rev = {c["case_id"]: c for c in measure if c["order"] == "reversed"}
    rep = {c["case_id"]: c for c in calls if c["phase"] == "repeat"}
    ok_measure = [c for c in measure if c["ok"]]

    # ---- latency
    lat = [c["latency_ms"] for c in ok_measure]
    tot = [c["total_ms"] for c in ok_measure]
    srv = [c["server_ms"] for c in ok_measure if c.get("server_ms") is not None]
    net = [c["latency_ms"] - c["server_ms"] for c in ok_measure if c.get("server_ms") is not None]
    latency = {"n": len(lat), "p50": pct(lat, .5), "p90": pct(lat, .9), "p95": pct(lat, .95), "p99": pct(lat, .99),
               "mean": _mean(lat), "min": min(lat) if lat else None, "max": max(lat) if lat else None,
               "p95_including_retries": pct(tot, .95),
               "server_reported": {"n": len(srv), "p50": pct(srv, .5), "p95": pct(srv, .95),
                                   "network_and_queue_p50": pct(net, .5)} if srv else None}

    # ---- cost and tokens
    billed = [c for c in calls if c["status"] and c["status"] < 400]
    run_cost = sum(c["cost_usd"] for c in calls)
    prov = [c["provider_cost_usd"] for c in calls if c.get("provider_cost_usd") is not None]
    per_call = _mean([c["cost_usd"] for c in ok_measure]) or 0.0
    cost = {"billed_in_run_usd": run_cost, "provider_reported_usd": sum(prov) if prov else None,
            "provider_reported_calls": len(prov), "per_call_usd": per_call,
            "per_1k_decisions_usd": per_call * 1e3, "per_1m_decisions_usd": per_call * 1e6}
    tokens = {"input_per_call": _mean([c["input_tokens"] for c in ok_measure]),
              "output_per_call": _mean([c["output_tokens"] for c in ok_measure]),
              "input_total": sum(c["input_tokens"] for c in calls), "output_total": sum(c["output_tokens"] for c in calls)}

    # ---- reliability
    reliability = {"calls": len(calls), "measure_calls": len(measure), "ok": len(ok_measure),
                   "success_rate": len(ok_measure) / max(1, len(measure)),
                   "errors": dict(Counter(c["error_kind"] for c in measure if not c["ok"])),
                   "http_status": dict(Counter(str(c["status"]) for c in measure if c["status"] and c["status"] >= 400)),
                   "calls_needing_retry": sum(c["attempts"] > 1 for c in calls),
                   "billed_calls": len(billed),
                   "error_samples": dict(Counter((c["error"] or "")[:200] for c in measure if not c["ok"]).most_common(3))}

    # ---- accuracy (original order, one answer per case)
    ids = [c["id"] for c in cases if c["id"] in orig]
    route_right = [orig[i]["ok"] and orig[i]["choice"] == by_case[i]["expected_route"] for i in ids]
    answered = [i for i in ids if orig[i]["ok"]]
    actions = {i: _action(orig[i], by_case[i], t)[0] for i in ids}
    act_right = [actions[i] == by_case[i]["expected_action"] for i in ids]
    per_arch: dict[str, list[bool]] = defaultdict(list)
    confusion: dict[str, Counter] = defaultdict(Counter)
    for i, right in zip(ids, route_right):
        per_arch[by_case[i]["archetype"]].append(right)
        confusion[by_case[i]["expected_route"]][orig[i]["choice"] if orig[i]["ok"] else "error"] += 1
    accuracy = {
        "cases": len(ids),
        "route_accuracy": sum(route_right) / max(1, len(ids)),
        "route_accuracy_answered": sum(orig[i]["choice"] == by_case[i]["expected_route"] for i in answered) / max(1, len(answered)),
        "action_accuracy": sum(act_right) / max(1, len(ids)),
        "fraud_auto_approved": sum(by_case[i]["expected_action"] == "manual_review" and actions[i] == "approve" for i in ids),
        "manual_reviews": sum(a == "manual_review" for a in actions.values()),
        "unnecessary_manual_reviews": sum(a == "manual_review" and by_case[i]["expected_action"] != "manual_review"
                                          for i, a in actions.items()),
        "actions": dict(Counter(actions.values())),
        "route_classes": class_scores([(by_case[i]["expected_route"], orig[i]["choice"] if orig[i]["ok"] else None)
                                       for i in ids]),
        "action_classes": class_scores([(by_case[i]["expected_action"], actions[i]) for i in ids], ACTIONS),
        "per_archetype_route_accuracy": {k: sum(v) / len(v) for k, v in sorted(per_arch.items())},
        "confusion": {k: dict(v) for k, v in confusion.items()},
    }

    # ---- calibration and sharpness (answered cases)
    items, brier, logloss, top = [], [], [], []
    for i in answered:
        p, exp = orig[i]["probs"], by_case[i]["expected_route"]
        items.append((max(p.values()), orig[i]["choice"] == exp))
        brier.append(sum((p[r] - (r == exp)) ** 2 for r in ROUTES))
        logloss.append(-math.log(max(p[exp], 1e-6)))
        top.append(max(p.values()))
    cal = calibration(items)
    calib = {"ece": cal["ece"], "table": cal["table"], "brier": _mean(brier), "log_loss": _mean(logloss),
             "mean_top_probability": _mean(top),
             "share_top_ge_0_95": sum(x >= .95 for x in top) / len(top) if top else None,
             "share_top_ge_0_99": sum(x >= .99 for x in top) / len(top) if top else None}

    # ---- takeover question
    lab = [i for i in answered if by_case[i]["takeover"] is not None]
    ys = [bool(by_case[i]["takeover"]) for i in lab]
    ps = [orig[i]["takeover"] for i in lab]
    takeover = {"labelled_cases": len(lab),
                "accuracy_at_0_5": sum((p >= .5) == y for p, y in zip(ps, ys)) / len(lab) if lab else None,
                "brier": _mean([(p - y) ** 2 for p, y in zip(ps, ys)]), "auc": auc(ps, ys)}

    # ---- confidence field
    oks = [orig[i] for i in answered]
    gaps = [c["confidence_formula_gap"] for c in oks if c.get("confidence_formula_gap") is not None]
    confidence = {"source": dict(Counter(c["confidence_source"] for c in oks)),
                  "formula_gap_mean": _mean(gaps), "formula_gap_max": max(gaps) if gaps else None,
                  "choice_not_highest_probability": sum(c["choice"] != max(c["probs"], key=c["probs"].get) for c in oks)}

    # ---- option order: every order that was asked
    by_order = {o: {c["case_id"]: c for c in measure if c["order"] == o} for o in ORDERS}
    by_order = {o: v for o, v in by_order.items() if v}
    order = None
    if len(by_order) > 1:
        asked = list(by_order)
        full = [i for i in ids if all(i in by_order[o] and by_order[o][i]["ok"] for o in asked)]
        choices = {i: [by_order[o][i]["choice"] for o in asked] for i in full}
        acts = {i: [_action(by_order[o][i], by_case[i], t)[0] for o in asked] for i in full}
        span = lambda i, r: max(by_order[o][i]["probs"][r] for o in asked) - min(by_order[o][i]["probs"][r] for o in asked)  # noqa: E731
        span_a = [span(i, "approve") for i in full]
        span_any = [max(span(i, r) for r in ROUTES) for i in full]
        per_order = {}
        for o in asked:
            got = [(by_case[i]["expected_route"], by_order[o][i]["choice"] if by_order[o][i]["ok"] else None)
                   for i in ids if i in by_order[o]]
            per_order[o] = {"cases": len(got), "route_accuracy": sum(e == g for e, g in got) / max(1, len(got)),
                            "macro_f1": macro_f1(got),
                            "action_accuracy": sum(_action(by_order[o][i], by_case[i], t)[0] == by_case[i]["expected_action"]
                                                   for i in ids if i in by_order[o]) / max(1, len(got))}
        changed = [i for i in full if len(set(choices[i])) > 1]
        position = None
        if len(asked) == len(ORDERS) and full:   # balanced design: each option is listed in each position twice
            pos_p = [[], [], []]
            pos_chosen = Counter()
            for i in full:
                for o in asked:
                    lst, c = ordered_routes(o), by_order[o][i]
                    for k, r in enumerate(lst):
                        pos_p[k].append(c["probs"][r])
                    pos_chosen[lst.index(c["choice"])] += 1
            n = sum(pos_chosen.values())
            position = {"mean_probability_by_position": [_mean(x) for x in pos_p],
                        "bias_vs_one_third": [(_mean(x) or 0) - 1 / 3 for x in pos_p],
                        "share_chosen_by_position": [pos_chosen[k] / max(1, n) for k in range(3)]}
        accs = [v["route_accuracy"] for v in per_order.values()]
        f1s = [v["macro_f1"] for v in per_order.values() if v["macro_f1"] is not None]
        frac = lambda x: x / len(full) if full else None  # noqa: E731   (None = nothing to compare, not 0%)
        order = {"orders": asked, "cases_all_orders_ok": len(full),
                 "same_route_in_every_order": frac(len(full) - len(changed)),
                 "cases_route_changed": len(changed),
                 "same_action_in_every_order": frac(sum(len(set(acts[i])) == 1 for i in full)),
                 "cases_same_action": sum(len(set(acts[i])) == 1 for i in full),
                 "distinct_routes_per_case": dict(Counter(len(set(choices[i])) for i in full)),
                 "p_approve_range_mean": _mean(span_a), "p_approve_range_p95": pct(span_a, .95),
                 "max_range_any_route": max(span_any) if span_any else None,
                 "per_order": per_order,
                 "route_accuracy_spread": max(accs) - min(accs) if accs else None,
                 "macro_f1_spread": max(f1s) - min(f1s) if f1s else None,
                 "position": position,
                 "changed_examples": [{"case": i, "archetype": by_case[i]["archetype"],
                                       "answers": dict(zip(asked, choices[i]))} for i in changed[:10]]}

    # ---- repeatability
    repeat = None
    rpairs = [i for i in rep if i in orig and orig[i]["ok"] and rep[i]["ok"]]
    if rep:
        d = [max(abs(orig[i]["probs"][r] - rep[i]["probs"][r]) for r in ROUTES) for i in rpairs]
        # "identical" = all three route probabilities equal, as returned (exact float equality, no rounding);
        # max_abs_delta is the largest |difference| over the same three fields, so the two always agree:
        # identical_count == pairs  <=>  max_abs_delta == 0
        same_choice = sum(orig[i]["choice"] == rep[i]["choice"] for i in rpairs)
        identical = sum(x == 0 for x in d)
        same_action = sum(actions[i] == _action(rep[i], by_case[i], t)[0] for i in rpairs)
        repeat = {"pairs": len(rpairs),
                  "same_choice_count": same_choice, "identical_count": identical, "same_action_count": same_action,
                  "same_choice_rate": same_choice / max(1, len(rpairs)),
                  "identical_probabilities_rate": identical / max(1, len(d)),
                  "mean_max_abs_delta": _mean(d), "max_abs_delta": max(d) if d else None,
                  "same_action_rate": same_action / max(1, len(rpairs))}

    served = Counter(c["served_model"] for c in calls if c.get("served_model"))
    return {"latency": latency, "cost": cost, "tokens": tokens, "reliability": reliability, "accuracy": accuracy,
            "calibration": calib, "takeover": takeover, "confidence": confidence, "order": order, "repeat": repeat,
            "served_models": dict(served), "simulated": any(c.get("simulated") for c in calls)}


def bootstrap_difference(pa: list[tuple], pb: list[tuple], n: int = 2000, seed: int = 7) -> dict:
    """Paired bootstrap over cases: 95% interval for macro-F1(a) - macro-F1(b) and accuracy(a) - accuracy(b).

    Resampling the same cases for both models keeps the comparison paired. If the interval excludes 0,
    the gap is unlikely to be an artefact of which cases happened to be in the dataset.
    """
    import random
    rng = random.Random(seed)
    m = len(pa)
    acc = lambda p: sum(e == g for e, g in p) / len(p)  # noqa: E731
    def f1_counts(cnt: Counter) -> float:
        f1s = []
        for k in ROUTES:
            tp = cnt[(k, k)]
            fp = sum(v for (e, g), v in cnt.items() if g == k and e != k)
            fn = sum(v for (e, g), v in cnt.items() if e == k and g != k)
            if tp + fn == 0:
                continue
            pr, rc = (tp / (tp + fp) if tp + fp else 0.0), tp / (tp + fn)
            f1s.append(2 * pr * rc / (pr + rc) if pr + rc else 0.0)
        return statistics.fmean(f1s) if f1s else 0.0

    d_f1, d_acc = [], []
    for _ in range(n):
        idx = [rng.randrange(m) for _ in range(m)]
        ca, cb = Counter(pa[i] for i in idx), Counter(pb[i] for i in idx)
        d_f1.append(f1_counts(ca) - f1_counts(cb))
        d_acc.append((sum(v for (e, g), v in ca.items() if e == g) - sum(v for (e, g), v in cb.items() if e == g)) / m)
    return {"difference": (macro_f1(pa) or 0) - (macro_f1(pb) or 0),
            "difference_ci95": [pct(d_f1, .025), pct(d_f1, .975)],
            "accuracy_difference": acc(pa) - acc(pb),
            "accuracy_difference_ci95": [pct(d_acc, .025), pct(d_acc, .975)],
            "bootstrap_resamples": n}


def head_to_head(calls: list[dict], cases: list[dict], t: Thresholds, a: str, b: str) -> dict | None:
    """Two providers on the same cases (original option order). Keys use 'a' / 'b'; the names are in 'a' and 'b'."""
    pick = lambda p: {c["case_id"]: c for c in calls if c["provider"] == p and c["phase"] == "measure"  # noqa: E731
                      and c["order"] == "original"}
    A, B = pick(a), pick(b)
    ids = [c["id"] for c in cases if c["id"] in A and c["id"] in B]
    if not ids:
        return None
    by_case = {c["id"]: c for c in cases}
    ans = lambda c: c["choice"] if c["ok"] else None  # noqa: E731
    right = lambda c, i: c["ok"] and c["choice"] == by_case[i]["expected_route"]  # noqa: E731
    both = sum(right(A[i], i) and right(B[i], i) for i in ids)
    only_a = sum(right(A[i], i) and not right(B[i], i) for i in ids)
    only_b = sum(right(B[i], i) and not right(A[i], i) for i in ids)
    act = lambda c, i: _action(c, by_case[i], t)[0]  # noqa: E731
    paired_lat = [(A[i]["latency_ms"], B[i]["latency_ms"]) for i in ids if A[i]["ok"] and B[i]["ok"]]
    disagreements = [{"case": i, "archetype": by_case[i]["archetype"], "expected": by_case[i]["expected_route"],
                      "a": ans(A[i]) or A[i]["error_kind"], "b": ans(B[i]) or B[i]["error_kind"]}
                     for i in ids if ans(A[i]) != ans(B[i])]
    pa = [(by_case[i]["expected_route"], ans(A[i])) for i in ids]
    pb = [(by_case[i]["expected_route"], ans(B[i])) for i in ids]
    return {"a": a, "b": b, "cases": len(ids), "both_right": both, "only_a_right": only_a, "only_b_right": only_b,
            "neither_right": len(ids) - both - only_a - only_b,
            "macro_f1": {"a": macro_f1(pa), "b": macro_f1(pb), **bootstrap_difference(pa, pb)},
            "route_agreement": sum(ans(A[i]) == ans(B[i]) for i in ids) / len(ids),
            "action_agreement": sum(act(A[i], i) == act(B[i], i) for i in ids) / len(ids),
            "a_faster_share": sum(x < y for x, y in paired_lat) / len(paired_lat) if paired_lat else None,
            "disagreements": disagreements}


def summarize(calls: list[dict], cases: list[dict], t: Thresholds = Thresholds()) -> dict:
    from itertools import combinations
    known = ["jev", "openai", "microsoft"]
    providers = sorted({c["provider"] for c in calls}, key=lambda p: known.index(p) if p in known else 9)
    used = {c["case_id"] for c in calls if c["phase"] == "measure"}
    cases = [c for c in cases if c["id"] in used]
    per = {p: provider_metrics([c for c in calls if c["provider"] == p], cases, t) for p in providers}
    pairs = [h for a, b in combinations(providers, 2) if (h := head_to_head(calls, cases, t, a, b))]
    rank = lambda key: sorted(providers, key=key)  # noqa: E731
    orig = {p: {c["case_id"]: (c["choice"] if c["ok"] else c["error_kind"]) for c in calls
                if c["provider"] == p and c["phase"] == "measure" and c["order"] == "original"} for p in providers}
    disagree = [{"case": c["id"], "archetype": c["archetype"], "expected": c["expected_route"],
                 "answers": {p: orig[p].get(c["id"]) for p in providers}}
                for c in cases if len({orig[p].get(c["id"]) for p in providers}) > 1]
    return {"providers": per, "pairs": pairs, "disagreements": disagree,
            "ranking": {
                "macro_f1": rank(lambda p: -(per[p]["accuracy"]["route_classes"]["macro_f1"] or 0)),
                "route_accuracy": rank(lambda p: -per[p]["accuracy"]["route_accuracy"]),
                "latency_p50": rank(lambda p: per[p]["latency"]["p50"] if per[p]["latency"]["p50"] is not None else 1e18),
                "cost_per_1k": rank(lambda p: per[p]["cost"]["per_1k_decisions_usd"]),
                "ece": rank(lambda p: per[p]["calibration"]["ece"] if per[p]["calibration"]["ece"] is not None else 9),
            },
            "cases": len(cases), "archetypes": dict(Counter(c["archetype"] for c in cases))}
