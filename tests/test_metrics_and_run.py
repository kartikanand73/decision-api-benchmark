"""Metrics are right on hand-built inputs; the whole pipeline runs on mocks; the dataset is sound."""

from __future__ import annotations

import asyncio
from collections import Counter
from pathlib import Path

import pytest

from compare.dataset import ARCHETYPES, generate
from compare.metrics import auc, calibration, pct, summarize
from compare.policy import decide
from compare.providers import Answer, make_client
from compare.report import render_html, render_md
from compare.metrics import bootstrap_difference, class_scores, macro_f1
from compare.rubric import ORDER_SETS, ORDERS, ROUTES, ordered_routes
from compare.run import execute, plan_calls


def test_percentile_auc_calibration():
    assert pct([1, 2, 3, 4], 0.5) == 2.5 and pct([], 0.5) is None
    assert auc([0.9, 0.8, 0.2], [True, True, False]) == 1.0
    assert auc([0.5, 0.5], [True, False]) == 0.5
    c = calibration([(0.9, True), (0.9, False)])
    assert c["ece"] == pytest.approx(0.4)


@pytest.mark.parametrize("amount,probs,conf,ato,action", [
    (100, {"approve": .9, "step_up_verification": .08, "manual_review": .02}, .85, .1, "approve"),
    (6000, {"approve": .9, "step_up_verification": .08, "manual_review": .02}, .85, .1, "step_up_verification"),
    (100, {"approve": .6, "step_up_verification": .35, "manual_review": .05}, .4, .1, "step_up_verification"),
    (100, {"approve": .5, "step_up_verification": .15, "manual_review": .35}, .25, .1, "manual_review"),
    (100, {"approve": .95, "step_up_verification": .04, "manual_review": .01}, .92, .7, "manual_review"),
    (100, None, None, None, "manual_review"),
])
def test_policy(amount, probs, conf, ato, action):
    assert decide(amount, probs, conf, ato)[0] == action


def _ans(provider, case, order="original", phase="measure", choice="approve", pa=0.9, ok=True):
    p = {"approve": pa, "step_up_verification": round(1 - pa - 0.01, 4), "manual_review": 0.01}
    return Answer(provider=provider, case_id=case["id"], order=order, phase=phase, ok=ok, status=200 if ok else 500,
                  choice=choice if ok else None, probs=p if ok else None, confidence=0.8 if ok else None,
                  confidence_source="api", takeover=0.05 if ok else None, latency_ms=100, total_ms=100,
                  attempts=1, input_tokens=1000, cost_usd=1000 * 0.1 / 1e6,
                  error_kind=None if ok else "http").to_json()


def test_order_flips_and_repeat_are_detected():
    cases = [c for c in generate(40, 3) if c["expected_route"] == "approve" and c["request"]["amount"] < 5000][:4]
    calls = []
    for c in cases:
        calls.append(_ans("openai", c))
        calls.append(_ans("openai", c, "reversed", choice="step_up_verification", pa=0.3))   # order effect
        calls.append(_ans("openai", c, phase="repeat"))
    r = summarize(calls, cases)["providers"]["openai"]
    assert r["accuracy"]["route_accuracy"] == 1.0
    assert r["order"]["cases_route_changed"] == 4 and r["order"]["same_action_in_every_order"] == 0
    assert r["order"]["p_approve_range_mean"] == pytest.approx(0.6)
    assert r["order"]["per_order"]["reversed"]["route_accuracy"] == 0.0
    assert r["repeat"]["same_choice_rate"] == 1.0 and r["repeat"]["identical_probabilities_rate"] == 1.0
    assert r["cost"]["per_1k_decisions_usd"] == pytest.approx(0.1)


def test_failed_call_counts_wrong_and_fails_safe():
    cases = generate(10, 4)[:2]
    calls = [_ans("jev", cases[0], choice=cases[0]["expected_route"]), _ans("jev", cases[1], ok=False)]
    r = summarize(calls, cases)["providers"]["jev"]
    assert r["accuracy"]["route_accuracy"] == 0.5 and r["accuracy"]["route_accuracy_answered"] == 1.0
    assert r["accuracy"]["actions"].get("manual_review", 0) >= 1
    assert r["reliability"]["errors"] == {"http": 1}


def test_call_plan_is_shuffled_and_complete():
    cases = generate(10, 5)
    w = plan_calls(cases, ["jev", "openai"], ["original", "reversed"], 3, seed=1)
    assert len(w) == 10 * 2 * 2 + 3 * 2
    assert Counter(x[0] for x in w) == {"jev": 23, "openai": 23}
    assert [x[0] for x in w[:6]] != ["jev"] * 6
    assert w == plan_calls(cases, ["jev", "openai"], ["original", "reversed"], 3, seed=1)   # reproducible


def test_mock_pipeline_end_to_end(tmp_path: Path):
    cases = generate(30, 6)
    clients = {p: make_client(p, mock=True) for p in ("jev", "openai", "microsoft")}
    calls = asyncio.run(execute(clients, cases, ORDER_SETS["all"], repeat=5, warmup=2, concurrency=4,
                                seed=1, out=tmp_path, quiet=True))
    assert len(calls) == 3 * (30 * 6 + 5 + 2) and (tmp_path / "calls.jsonl").exists()
    s = summarize(calls, cases)
    assert [(h["a"], h["b"]) for h in s["pairs"]] == [("jev", "openai"), ("jev", "microsoft"), ("openai", "microsoft")]
    assert sorted(s["ranking"]["macro_f1"]) == ["jev", "microsoft", "openai"]
    for p in ("jev", "openai", "microsoft"):
        r = s["providers"][p]
        assert r["simulated"] and r["latency"]["n"] == 180 and r["reliability"]["success_rate"] == 1.0
        assert r["order"]["position"]["bias_vs_one_third"] == pytest.approx([0, 0, 0], abs=1e-9)
        assert r["order"]["cases_route_changed"] == 0          # mocks are order-invariant by construction
    meta = {"mock": True, "started_at": "2026-10-08T00:00:00+00:00", "duration_s": 1, "command": "x",
            "dataset": {"sha256": "abc"}, "rubric_version": "1.1", "rubric_sha256": "def",
            "policy": {"version": "p", "approve_min_probability": .8, "approve_min_confidence": .5,
                       "manual_review_min_probability": .3, "account_takeover_max": .5, "auto_approve_ceiling_usd": 5000},
            "providers": {p: {"label": c.label, "model_requested": c.model, "endpoint": "mock", "price_in_per_mtok": c.price_in}
                          for p, c in clients.items()},
            "args": {"concurrency": 4, "timeout": 30, "warmup": 2}, "python": "3", "platform": "x"}
    md = render_md(meta, s)
    for h in ("MOCK RUN", "## Headline", "## Same cases, side by side", "## Option-order check", "## Repeatability",
              "Macro-F1", "### Position bias", "### By order", "### Per-route precision"):
        assert h in md
    assert "<html" in render_html(meta, s, md)


def test_dataset_is_deterministic_labelled_and_model_only():
    a, b = generate(200, 9), generate(200, 9)
    assert a == b and len({c["id"] for c in a}) == 200
    assert {c["archetype"] for c in a} == {x[0] for x in ARCHETYPES}
    for c in a:
        r = c["request"]
        assert r["amount"] <= r["available_balance"] and r["account_status"] == "active" and r["failed_auth_attempts_24h"] < 5
        if c["archetype"] == "large_familiar":
            assert c["expected_route"] == "approve" and c["expected_action"] == "step_up_verification"


def test_env_example_parses_with_inline_comments(tmp_path):
    from dotenv import dotenv_values
    v = dotenv_values(Path(__file__).resolve().parents[1] / ".env.example")
    for base in ("TYPESAFE_BASE_URL", "OPENAI_BASE_URL", "MSD_BASE_URL"):
        assert v[base] == "https://openrouter.ai/api"
    assert v["JEV_MODEL"] == "typesafe/jev-1.13" and v["DECISIONS_MODEL"] == "openai/gpt-6-luna-decisions"
    assert v["MSD_MODEL"] == "microsoft/microsoft-decision-1" and v["DECISIONS_PRICE_IN_PER_MTOK"] == "0.10"


# ---- macro-F1, permutations, position bias, run-to-run ---------------------------------------
def test_macro_f1_hand_computed():
    # approve: tp 8 fp 1 fn 2 -> P .889 R .8 F1 .842 ; step: tp 1 fp 2 fn 1 -> P .333 R .5 F1 .4 ; manual: tp 3 fp 0 fn 0 -> 1.0
    pairs = ([("approve", "approve")] * 8 + [("approve", "step_up_verification")] * 2
             + [("step_up_verification", "step_up_verification")] + [("step_up_verification", "approve")]
             + [("manual_review", "manual_review")] * 3)
    cs = class_scores(pairs)
    assert cs["per_class"]["approve"]["f1"] == pytest.approx(16 / 19)
    assert cs["per_class"]["step_up_verification"]["f1"] == pytest.approx(0.4)
    assert cs["macro_f1"] == pytest.approx((16 / 19 + 0.4 + 1.0) / 3)
    assert cs["balanced_accuracy"] == pytest.approx((0.8 + 0.5 + 1.0) / 3)
    # accuracy is 12/15 = 80%, but the weak minority class pulls macro-F1 down to ~75%
    assert macro_f1(pairs) < 12 / 15


def test_macro_f1_counts_failures_against_recall_only():
    ok = [("approve", "approve"), ("step_up_verification", "step_up_verification")]
    assert macro_f1(ok + [("approve", None)]) < macro_f1(ok)
    assert class_scores(ok + [("approve", None)])["per_class"]["approve"]["precision"] == 1.0


def test_bootstrap_interval_separates_a_real_gap_and_not_a_coin_flip():
    rng = __import__("random").Random(3)
    exp = rng.choices(ROUTES, [320, 76, 104], k=500)
    good = [(e, e if rng.random() < .95 else rng.choice(ROUTES)) for e in exp]
    bad = [(e, e if rng.random() < .70 else rng.choice(ROUTES)) for e in exp]
    lo, hi = bootstrap_difference(good, bad, n=500)["difference_ci95"]
    assert lo > 0
    lo, hi = bootstrap_difference(good, good, n=200)["difference_ci95"]
    assert lo == hi == 0


def test_six_orders_are_all_distinct_permutations():
    assert len(ORDERS) == 6 and len({tuple(ordered_routes(o)) for o in ORDERS}) == 6
    assert ordered_routes("original") == list(ROUTES) and ordered_routes("reversed") == list(reversed(ROUTES))
    assert len(plan_calls(generate(10, 1), ["jev"], ORDER_SETS["all"], 0, 1)) == 60


def test_position_bias_is_detected():
    """A fake model that always adds probability to whichever option is listed FIRST."""
    cases = [c for c in generate(60, 8) if c["request"]["amount"] < 5000][:20]
    calls = []
    for c in cases:
        for o in ORDERS:
            lst = ordered_routes(o)
            base = {r: (0.6 if r == c["expected_route"] else 0.2) for r in ROUTES}
            base[lst[0]] += 0.5          # strong enough to beat the right answer when it is not listed first
            z = sum(base.values())
            p = {r: base[r] / z for r in ROUTES}
            a = _ans("openai", c, o, choice=max(p, key=p.get))
            a["probs"] = p
            calls.append(a)
    o = summarize(calls, cases)["providers"]["openai"]["order"]
    bias = o["position"]["bias_vs_one_third"]
    assert bias[0] > 0.1 and bias[1] < 0 and bias[2] < 0
    assert o["cases_route_changed"] == 20 and o["same_route_in_every_order"] == 0
    assert o["position"]["share_chosen_by_position"][0] > 0.5


def test_compare_runs_on_two_mock_runs(tmp_path, monkeypatch):
    import json
    from compare import compare_runs, run as run_mod
    monkeypatch.setattr(run_mod, "ROOT", tmp_path)
    monkeypatch.setattr(compare_runs, "ROOT", tmp_path)
    (tmp_path / "data").mkdir()
    data = tmp_path / "data" / "cases.jsonl"
    data.write_text("\n".join(json.dumps(c) for c in generate(15, 2)), encoding="utf-8")
    d1 = run_mod.main(["--mock", "--data", str(data), "--label", "a", "--repeat", "3", "--warmup", "1"])
    d2 = run_mod.main(["--mock", "--data", str(data), "--label", "b", "--repeat", "3", "--warmup", "1"])
    out = compare_runs.main([str(d1), str(d2)])
    md = (out / "comparison.md").read_text(encoding="utf-8")
    assert "## Uncertainty" in md and "Ranking in each run (point estimates)" in md and "MOCK" in md
    assert "should not flip" not in md and "Does the conclusion hold?" not in md
    c = json.loads((out / "comparison.json").read_text(encoding="utf-8"))
    assert c["drift"]["jev"][0]["same_route"] == 1.0          # mocks are deterministic per case
    assert c["metrics"]["f1"]["holds_in_every_run"] in (True, False)
    U = c["uncertainty"]
    assert U["labels_available"] and set(U["pairs"]) == {"jev~openai", "jev~microsoft", "openai~microsoft"}
    pooled = U["pairs"]["jev~openai"]["pooled"]["macro_f1"]
    assert pooled[1] <= pooled[0] <= pooled[2]                 # point estimate inside its interval
    assert set(U["providers"]["jev"]) == {d1.name, d2.name, "pooled"}


def test_compare_runs_picks_best_of_three():
    from compare.compare_runs import compare
    def run(name, f1s, p50s):
        prov = {}
        for p, f1, lat in zip(("jev", "openai", "microsoft"), f1s, p50s):
            prov[p] = {"latency": {"p50": lat, "p95": lat}, "cost": {"per_1k_decisions_usd": .03},
                       "accuracy": {"route_accuracy": f1, "route_classes": {"macro_f1": f1, "balanced_accuracy": f1},
                                    "action_accuracy": f1, "fraud_auto_approved": 0},
                       "calibration": {"ece": .05, "brier": .2}, "order": None, "reliability": {"success_rate": 1.0},
                       "served_models": {p: 1}}
        return {"name": name, "calls": [], "meta": {"dataset": {"sha256": "x"}, "rubric_sha256": "y", "mock": False,
                                                    "started_at": "2026-10-09T00:00:00"},
                "summary": {"providers": prov, "pairs": []}}
    c = compare([run("r1", (.89, .74, .91), (210, 600, 200)), run("r2", (.88, .75, .87), (215, 580, 205))])
    assert c["metrics"]["f1"]["winner_by_run"] == ["microsoft", "jev"] and not c["metrics"]["f1"]["holds_in_every_run"]
    assert c["metrics"]["p50"]["winner_by_run"] == ["microsoft", "microsoft"] and c["metrics"]["p50"]["holds_in_every_run"]
    assert c["metrics"]["cost"]["winner_by_run"] == ["tie", "tie"]


def test_reports_survive_providers_that_fail_some_or_all_calls(tmp_path):
    """Regression: a provider with no case answered in every order crashed report.md (position bias was None)."""
    from compare.providers import MockDecisionsClient, MockMicrosoftClient

    class FlakyOpenAI(MockDecisionsClient):          # fails every non-original order
        async def ask(self, case, order="original", phase="measure"):
            a = await super().ask(case, order, phase)
            if order != "original":
                a.ok, a.error_kind, a.error, a.status = False, "http", "HTTP 503: upstream error", 503
                a.probs = a.choice = a.confidence = a.takeover = None
            return a

    class DeadMicrosoft(MockMicrosoftClient):        # fails everything
        async def ask(self, case, order="original", phase="measure"):
            a = await super().ask(case, order, phase)
            a.ok, a.error_kind, a.error, a.status = False, "http", "HTTP 404: model not found", 404
            a.probs = a.choice = a.confidence = a.takeover = None
            return a

    cases = generate(12, 11)
    clients = {"jev": make_client("jev", mock=True), "openai": FlakyOpenAI(), "microsoft": DeadMicrosoft()}
    calls = asyncio.run(execute(clients, cases, ORDER_SETS["all"], repeat=2, warmup=1, concurrency=4, seed=1, quiet=True))
    s = summarize(calls, cases)
    o = s["providers"]["openai"]["order"]
    assert o["cases_all_orders_ok"] == 0 and o["same_route_in_every_order"] is None and o["position"] is None
    assert s["providers"]["microsoft"]["reliability"]["success_rate"] == 0
    meta = {"mock": True, "started_at": "2026-10-09T00:00:00+00:00", "duration_s": 1, "command": "x",
            "dataset": {"sha256": "abc"}, "rubric_version": "1.1", "rubric_sha256": "def",
            "policy": {"version": "p", "approve_min_probability": .8, "approve_min_confidence": .5,
                       "manual_review_min_probability": .3, "account_takeover_max": .5, "auto_approve_ceiling_usd": 5000},
            "providers": {p: {"label": c.label, "model_requested": c.model, "endpoint": "mock", "price_in_per_mtok": c.price_in}
                          for p, c in clients.items()},
            "args": {"concurrency": 4, "timeout": 30, "warmup": 1}, "python": "3", "platform": "x"}
    md = render_md(meta, s)
    assert "## Option-order check" in md and "HTTP 404" in md
    assert "<html" in render_html(meta, s, md)
    from compare.run import console_summary
    assert "Microsoft" in console_summary(s, meta)


def test_share_never_rounds_to_all_or_none():
    from compare.report import share
    assert share(499, 500) == "499 / 500 (99.8%)"
    assert share(9999, 10000) == "9999 / 10000 (>99.9%)"
    assert share(1, 10000) == "1 / 10000 (<0.1%)"
    assert share(500, 500) == "500 / 500 (100%)" and share(0, 50) == "0 / 50 (0%)"
    assert f"{499/500:.0%}" == "100%"                           # the rounding that caused the contradiction


def test_identical_count_agrees_with_max_change():
    """'Identical' and 'largest change' are computed over the same three fields with exact equality."""
    cases = [c for c in generate(40, 12) if c["request"]["amount"] < 5000][:5]
    calls = []
    for k, c in enumerate(cases):
        calls.append(_ans("openai", c))
        r = _ans("openai", c, phase="repeat")
        if k == 0:                                             # one repeat differs by 0.05
            r["probs"] = {**r["probs"], "approve": r["probs"]["approve"] - 0.05,
                          "step_up_verification": r["probs"]["step_up_verification"] + 0.05}
        calls.append(r)
    q = summarize(calls, cases)["providers"]["openai"]["repeat"]
    assert q["identical_count"] == 4 and q["pairs"] == 5 and q["max_abs_delta"] == pytest.approx(0.05)
    from compare.report import share
    assert share(q["identical_count"], q["pairs"]) == "4 / 5 (80.0%)"


def test_rebuild_recomputes_summary_from_calls(tmp_path, monkeypatch):
    """Regression: reports rebuilt from a summary.json written by older code showed '–' for new counts."""
    import json
    from compare import env, report, run as run_mod
    monkeypatch.setattr(run_mod, "ROOT", tmp_path)
    monkeypatch.setattr(env, "ROOT", tmp_path)
    (tmp_path / "data").mkdir()
    data = tmp_path / "data" / "cases.jsonl"
    data.write_text("\n".join(json.dumps(c) for c in generate(12, 4)), encoding="utf-8")
    d = run_mod.main(["--mock", "--data", str(data), "--label", "r", "--repeat", "3", "--warmup", "1"])
    s = json.loads((d / "summary.json").read_text(encoding="utf-8"))
    for p in s["providers"].values():                     # simulate a summary from the previous code version
        p["repeat"].pop("same_choice_count"); p["repeat"].pop("identical_count"); p["order"].pop("cases_same_action")
    (d / "summary.json").write_text(json.dumps(s), encoding="utf-8")
    note = report.rebuild(d)
    md = (d / "report.md").read_text(encoding="utf-8")
    assert "recomputed" in note and (d / "summary.prev.json").exists()
    assert "same choice 3 / 3 (100%)" in md and "| Same final action in every order | 12 / 12 (100%)" in md
