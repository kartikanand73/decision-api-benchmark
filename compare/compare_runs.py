"""Compare two or more complete benchmark runs, with the uncertainty stated.

    python -m compare.run --label run1 --yes
    python -m compare.run --label run2 --yes          # later, ideally another day / hour
    python -m compare.compare_runs runs/<run1> runs/<run2>

Writes runs/compare-<stamp>/comparison.md and comparison.json:
* 95% intervals (case-resampling bootstrap) for every pairwise difference in macro-F1, accuracy and latency,
  pooled across runs, plus each provider's per-run intervals
* the ranking in each run (point estimates only: small real differences can swap rank between finite runs,
  and an unchanged rank can still sit inside the noise, so read it next to the intervals)
* every headline metric per run, with the spread between runs
* case-level drift: how often each provider gave the same route to the same case in different runs
"""

from __future__ import annotations

import hashlib
import json
import random
import statistics
import sys
from collections import Counter
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path

from .env import ROOT
from .metrics import pct
from .report import LABEL, _row, _table, share
from .rubric import ROUTES

RESAMPLES = 2000

# (key, label, getter, better: "lower" | "higher", format)
METRICS = [
    ("p50", "Latency p50 (ms)", lambda r: r["latency"]["p50"], "lower", "{:,.0f}"),
    ("p95", "Latency p95 (ms)", lambda r: r["latency"]["p95"], "lower", "{:,.0f}"),
    ("cost", "Cost per 1k decisions ($)", lambda r: r["cost"]["per_1k_decisions_usd"], "lower", "{:.4f}"),
    ("acc", "Route accuracy", lambda r: r["accuracy"]["route_accuracy"], "higher", "{:.1%}"),
    ("f1", "Route macro-F1", lambda r: r["accuracy"]["route_classes"]["macro_f1"], "higher", "{:.1%}"),
    ("bal", "Route balanced accuracy", lambda r: r["accuracy"]["route_classes"]["balanced_accuracy"], "higher", "{:.1%}"),
    ("act", "Final action accuracy", lambda r: r["accuracy"]["action_accuracy"], "higher", "{:.1%}"),
    ("fraud", "Fraud auto-approved", lambda r: r["accuracy"]["fraud_auto_approved"], "lower", "{:.0f}"),
    ("ece", "ECE", lambda r: r["calibration"]["ece"], "lower", "{:.3f}"),
    ("brier", "Brier score", lambda r: r["calibration"]["brier"], "lower", "{:.3f}"),
    ("order", "Same route in every option order", lambda r: (r["order"] or {}).get("same_route_in_every_order"), "higher", "{:.1%}"),
    ("ok", "Success rate", lambda r: r["reliability"]["success_rate"], "higher", "{:.1%}"),
]


def load_run(d: Path) -> dict:
    calls = [json.loads(l) for l in (d / "calls.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    return {"dir": d, "name": d.name, "meta": json.loads((d / "meta.json").read_text(encoding="utf-8")),
            "summary": json.loads((d / "summary.json").read_text(encoding="utf-8")), "calls": calls}


def _fmt(v, f):
    return "–" if v is None else f.format(v)


def _load_labels(runs: list[dict]) -> tuple[dict | None, str | None]:
    """Case labels from the dataset the runs used (path in meta.json, checked against its sha256)."""
    meta = runs[0]["meta"].get("dataset") or {}
    if not meta.get("path"):
        return None, "run metadata has no dataset path; intervals for accuracy/macro-F1 skipped"
    raw = Path(meta["path"])
    for cand in (raw, ROOT / raw, ROOT / "data" / raw.name):
        try:
            if cand.exists():
                data = cand.read_bytes()
                if hashlib.sha256(data).hexdigest()[:16] != meta["sha256"]:
                    return None, f"{cand} does not match the dataset the runs used (sha256 differs)"
                rows = [json.loads(l) for l in data.decode("utf-8").splitlines() if l.strip()]
                return {r["id"]: r["expected_route"] for r in rows}, None
        except OSError:
            continue
    return None, f"dataset {raw.name} not found next to the project; intervals for accuracy/macro-F1 skipped"


def _f1_acc(conf: Counter, total: int) -> tuple[float, float]:
    f1s = []
    for k in ROUTES:
        tp = conf[(k, k)]
        fp = sum(v for (e, g), v in conf.items() if g == k and e != k)
        fn = sum(v for (e, g), v in conf.items() if e == k and g != k)
        if tp + fn == 0:
            continue
        pr, rc = (tp / (tp + fp) if tp + fp else 0.0), tp / (tp + fn)
        f1s.append(2 * pr * rc / (pr + rc) if pr + rc else 0.0)
    acc = sum(v for (e, g), v in conf.items() if e == g) / max(1, total)
    return (statistics.fmean(f1s) if f1s else 0.0), acc


def uncertainty(runs: list[dict], providers: list[str], labels: dict | None, B: int = RESAMPLES, seed: int = 11) -> dict:
    """Case-resampling bootstrap. The same resampled case sets are used for every provider, so pairwise
    differences stay paired. 'Pooled' keeps each case's observations from every run together (cluster bootstrap)."""
    case_ids = sorted({c["case_id"] for r in runs for c in r["calls"] if c["phase"] == "measure"})
    n = len(case_ids)
    rng = random.Random(seed)
    draws = [[rng.randrange(n) for _ in range(n)] for _ in range(B)]
    scopes = {r["name"]: [r] for r in runs}
    scopes["pooled"] = runs

    def per_case(scope_runs, p):
        ans = {i: [] for i in case_ids}       # (expected, answer) from the original order, one per run
        lat = {i: [] for i in case_ids}       # latencies of every successful measure call, all orders, all runs
        for r in scope_runs:
            for c in r["calls"]:
                if c["provider"] != p or c["phase"] != "measure":
                    continue
                if c["ok"]:
                    lat[c["case_id"]].append(c["latency_ms"])
                if c["order"] == "original" and labels:
                    ans[c["case_id"]].append((labels.get(c["case_id"]), c["choice"] if c["ok"] else None))
        return [ans[i] for i in case_ids], [lat[i] for i in case_ids]

    def stats(ans, lat, idx):
        conf, total, lats = Counter(), 0, []
        for j in idx:
            for o in ans[j]:
                conf[o] += 1
                total += 1
            lats.extend(lat[j])
        f1, acc = _f1_acc(conf, total) if total else (None, None)
        return {"macro_f1": f1, "accuracy": acc, "p50": pct(lats, .5), "p95": pct(lats, .95)}

    keys = ("macro_f1", "accuracy", "p50", "p95")
    out = {"resamples": B, "cases": n, "labels_available": labels is not None, "providers": {}, "pairs": {}}
    boot: dict = {}
    for scope, srs in scopes.items():
        for p in providers:
            ans, lat = per_case(srs, p)
            point = stats(ans, lat, range(n))
            samples = [stats(ans, lat, d) for d in draws]
            boot[(scope, p)] = samples
            out["providers"].setdefault(p, {})[scope] = {
                k: (None if point[k] is None else
                    [point[k], pct([s[k] for s in samples], .025), pct([s[k] for s in samples], .975)]) for k in keys}
        for a, b in combinations(providers, 2):
            pa, pb = out["providers"][a][scope], out["providers"][b][scope]
            row = {}
            for k in keys:
                if pa[k] is None or pb[k] is None:
                    row[k] = None
                    continue
                diffs = [sa[k] - sb[k] for sa, sb in zip(boot[(scope, a)], boot[(scope, b)])]
                row[k] = [pa[k][0] - pb[k][0], pct(diffs, .025), pct(diffs, .975)]
            out["pairs"].setdefault(f"{a}~{b}", {"a": a, "b": b})[scope] = row
    return out


def compare(runs: list[dict]) -> dict:
    warnings = []
    for key, what in (("dataset", "dataset"), ("rubric_sha256", "rubric")):
        vals = {json.dumps(r["meta"][key] if key != "dataset" else r["meta"]["dataset"]["sha256"]) for r in runs}
        if len(vals) > 1:
            warnings.append(f"runs used different {what}s: comparison is not like-for-like")
    if any(r["meta"]["mock"] for r in runs):
        warnings.append("at least one run is a MOCK run: its numbers are simulated")
    providers = [p for p in ("jev", "openai", "microsoft") if all(p in r["summary"]["providers"] for r in runs)]

    table = {}
    for key, label, get, better, f in METRICS:
        row = {}
        for p in providers:
            vals = [get(r["summary"]["providers"][p]) for r in runs]
            nums = [v for v in vals if v is not None]
            row[p] = {"values": vals, "spread": (max(nums) - min(nums)) if len(nums) > 1 else None}
        winners = []      # best provider in each run ("tie" if several share the best value, None if missing)
        if len(providers) >= 2:
            for k in range(len(runs)):
                vals = {p: row[p]["values"][k] for p in providers}
                if any(v is None for v in vals.values()):
                    winners.append(None)
                    continue
                best = (min if better == "lower" else max)(vals.values())
                top = [p for p, v in vals.items() if v == best]
                winners.append(top[0] if len(top) == 1 else "tie")
        table[key] = {"label": label, "better": better, "format": f, "by_provider": row, "winner_by_run": winners,
                      "holds_in_every_run": bool(winners) and None not in winners and len(set(winners)) == 1
                      and winners[0] != "tie"}

    # macro-F1 difference with each run's bootstrap interval
    gaps = []
    for r in runs:
        for h in r["summary"].get("pairs") or []:
            if h["a"] in providers and h["b"] in providers:
                mf = h["macro_f1"]
                gaps.append({"pair": f"{h['a']}~{h['b']}", "a": h["a"], "b": h["b"], "run": r["name"],
                             "difference": mf["difference"], "ci95": mf["difference_ci95"]})

    # case-level drift between runs (original option order)
    drift = {}
    for p in providers:
        pick = lambda r: {c["case_id"]: c for c in r["calls"]  # noqa: E731
                          if c["provider"] == p and c["phase"] == "measure" and c["order"] == "original" and c["ok"]}
        pairs = []
        for r1, r2 in combinations(runs, 2):
            A, B = pick(r1), pick(r2)
            ids = sorted(set(A) & set(B))
            same = sum(A[i]["choice"] == B[i]["choice"] for i in ids)
            dp = [max(abs(A[i]["probs"][k] - B[i]["probs"][k]) for k in A[i]["probs"]) for i in ids]
            identical = sum(x == 0 for x in dp)        # exact equality of all three probabilities
            pairs.append({"runs": [r1["name"], r2["name"]], "cases": len(ids),
                          "same_route_count": same, "identical_count": identical,
                          "same_route": same / max(1, len(ids)), "routes_changed": len(ids) - same,
                          "identical_probabilities": identical / max(1, len(dp)),
                          "mean_max_abs_delta": sum(dp) / len(dp) if dp else None,
                          "max_abs_delta": max(dp) if dp else None})
        drift[p] = pairs
    labels, why = _load_labels(runs)
    if why:
        warnings.append(why)
    unc = uncertainty(runs, providers, labels) if len(providers) >= 1 else None
    return {"uncertainty": unc,"runs": [{"name": r["name"], "started_at": r["meta"]["started_at"], "mock": r["meta"]["mock"],
                      "location": r["meta"].get("client_location_note"),
                      "served": {p: list(r["summary"]["providers"][p]["served_models"]) for p in providers}} for r in runs],
            "providers": providers, "warnings": warnings, "metrics": table, "macro_f1_gap": gaps, "drift": drift}


def render(c: dict) -> str:
    P = c["providers"]
    names = [r["name"] for r in c["runs"]]
    L = ["# Run-to-run comparison", ""]
    for w in c["warnings"]:
        L += [f"> ⚠️ {w}", ""]
    L += _table(["Run", "Started (UTC)", "Location", *(f"{LABEL[p]} served" for p in P)],
                [[r["name"], r["started_at"][:19], r["location"] or "–", *(", ".join(r["served"][p]) or "–" for p in P)]
                 for r in c["runs"]])
    U = c.get("uncertainty")
    names_scopes = names + ["pooled"]
    pts = lambda v: "–" if v is None else f"{v[0] * 100:+.1f} pts ({v[1] * 100:+.1f} to {v[2] * 100:+.1f})"  # noqa: E731
    ms = lambda v: "–" if v is None else f"{v[0]:+,.0f} ms ({v[1]:+,.0f} to {v[2]:+,.0f})"  # noqa: E731
    sep = lambda v: v is not None and (v[1] > 0 or v[2] < 0)  # noqa: E731
    if U:
        L += ["", "## Uncertainty", "",
              f"95% intervals from a case-resampling bootstrap ({U['resamples']:,} resamples over {U['cases']} cases). "
              "The same resampled cases are used for every provider, so differences stay paired. **Pooled** keeps each "
              "case's answers from every run together, so it reflects both which cases were sampled and run-to-run "
              "variation in the answers. An interval that excludes 0 means the difference is unlikely to come from those "
              "sources alone; one that includes 0 means these runs cannot tell the providers apart on that metric. "
              "Neither interval covers changes in conditions between runs (time of day, network path, a model update), "
              "which the per-run rows let you inspect.", ""]
        L += ["### Pairwise differences, pooled across runs (A − B)", ""]
        rows = []
        for key, pr in U["pairs"].items():
            v = pr.get("pooled") or {}
            separated = [lbl for k, lbl in (("macro_f1", "macro-F1"), ("accuracy", "accuracy"), ("p50", "p50"), ("p95", "p95"))
                         if sep(v.get(k))]
            rows.append([f"{LABEL.get(pr['a'], pr['a'])} − {LABEL.get(pr['b'], pr['b'])}", pts(v.get("macro_f1")),
                         pts(v.get("accuracy")), ms(v.get("p50")), ms(v.get("p95")), ", ".join(separated) or "none"])
        L += _table(["A − B", "Macro-F1", "Accuracy", "Latency p50", "Latency p95", "Interval excludes 0 on"], rows)
        if not U["labels_available"]:
            L += ["", "_Accuracy and macro-F1 intervals need the dataset file; see the warning above._"]
        L += ["", "### Each provider, per run and pooled", ""]
        pv = lambda v, f: "–" if v is None else f"{f.format(v[0])} ({f.format(v[1])}–{f.format(v[2])})"  # noqa: E731
        L += _table(["Provider", "Scope", "Macro-F1", "Accuracy", "Latency p50 (ms)", "Latency p95 (ms)"],
                    [[LABEL[p], sc, pv(U["providers"][p][sc]["macro_f1"], "{:.1%}"), pv(U["providers"][p][sc]["accuracy"], "{:.1%}"),
                      pv(U["providers"][p][sc]["p50"], "{:,.0f}"), pv(U["providers"][p][sc]["p95"], "{:,.0f}")]
                     for p in P for sc in names_scopes])
        L += ["", "### Pairwise differences in each run", ""]
        L += _table(["A − B", "Run", "Macro-F1", "Accuracy", "Latency p50"],
                    [[f"{LABEL.get(pr['a'], pr['a'])} − {LABEL.get(pr['b'], pr['b'])}", sc, pts(pr[sc].get("macro_f1")),
                      pts(pr[sc].get("accuracy")), ms(pr[sc].get("p50"))]
                     for pr in U["pairs"].values() for sc in names])
    L += ["", "## Ranking in each run (point estimates)", "",
          "Which provider had the best value in each run. A rank is a point estimate: a small real difference can swap "
          "rank between finite runs, and an unchanged rank does not by itself show a real difference. Read it next to "
          "the intervals above.", ""]
    rows = []
    for key, m in c["metrics"].items():
        if len(P) >= 2:
            w = m["winner_by_run"]
            if None in w:
                verdict = "– (missing in a run)"
            elif set(w) == {"tie"}:
                verdict = "tie in every run"
            elif m["holds_in_every_run"]:
                verdict = "same in every run"
            else:
                verdict = "differs between runs"
            rows.append([m["label"], f"{m['better']} is better", *(LABEL.get(x, x or "–") for x in w), verdict])
    if rows:
        L += _table(["Metric", "", *names, "Best provider"], rows)
    L += ["", "## Every metric, every run", ""]
    head = ["Metric"] + [f"{LABEL[p]} · {n}" for p in P for n in names] + [f"{LABEL[p]} spread" for p in P]
    body = []
    for key, m in c["metrics"].items():
        f = m["format"]
        body.append([m["label"], *(_fmt(v, f) for p in P for v in m["by_provider"][p]["values"]),
                     *(_fmt(m["by_provider"][p]["spread"], f) for p in P)])
    L += _table(head, body)
    L += ["", "## Same case, different run (original option order)", "",
          "How often a provider gave the same route to the same case in two separate runs.", ""]
    L += _table(["Provider", "Runs", "Same route", "Identical probabilities (all three, exact)", "Largest probability change"],
                [[LABEL[p], " vs ".join(d["runs"]), share(d.get("same_route_count"), d["cases"]),
                  share(d.get("identical_count"), d["cases"]), _fmt(d["max_abs_delta"], "{:.3f}")]
                 for p in P for d in c["drift"][p]])
    L += ["", "Identical means all three route probabilities were exactly equal; the largest change is measured over the "
          "same three fields, so 'identical' is all of them only when the largest change is 0.", ""]
    return "\n".join(L)


def main(argv: list[str] | None = None) -> Path:
    args = sys.argv[1:] if argv is None else argv
    if len(args) < 2:
        raise SystemExit("usage: python -m compare.compare_runs runs/<run1> runs/<run2> [more runs]")
    runs = [load_run(Path(a)) for a in args]
    print(f"comparing {len(runs)} runs; computing bootstrap intervals ({RESAMPLES:,} resamples, about 30 s)...", flush=True)
    c = compare(runs)
    out = ROOT / "runs" / ("compare-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ"))
    out.mkdir(parents=True, exist_ok=True)
    (out / "comparison.json").write_text(json.dumps(c, indent=2), encoding="utf-8")
    md = render(c)
    (out / "comparison.md").write_text(md, encoding="utf-8")
    print(md)
    print(f"\n-> {out / 'comparison.md'}")
    return out


if __name__ == "__main__":
    main()
