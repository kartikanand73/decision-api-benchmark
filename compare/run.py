"""Run the head-to-head benchmark.

    python -m compare.run --mock                          # no keys: checks the pipeline (numbers are fake)
    python -m compare.run --limit 20 --label smoke        # small live run
    python -m compare.run --label full                    # all cases, both option orders, repeat check

Fairness rules built in:
* Same cases, same rubric, same policy for both providers.
* Warm-up calls per provider (default 5) are made first and excluded, so TLS/connection setup isn't timed.
* All calls are shuffled together with a fixed seed and run with the same concurrency per provider, so
  neither provider is always measured first, last, or at a quieter minute.
* One HTTP client per provider with keep-alive; identical timeout and retry policy.

Everything lands in runs/<UTC stamp>[-label]/: calls.jsonl (every API call with the full response),
summary.json, report.md, report.html, console.txt, meta.json.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import os
import platform
import random
import subprocess
import sys
import time
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

from .dataset import load
from .env import ROOT, load_env
from .metrics import summarize
from .policy import POLICY_VERSION, Thresholds
from .providers import Answer, Client, make_client
from .rubric import ORDER_SETS, RUBRIC_VERSION, ROUTE_CRITERIA, ROUTE_INSTRUCTIONS, TAKEOVER_CRITERIA, TAKEOVER_INSTRUCTIONS

SAFE_ENV = ["TYPESAFE_BASE_URL", "JEV_MODEL", "JEV_PRICE_IN_PER_MTOK",
            "OPENAI_BASE_URL", "DECISIONS_MODEL", "DECISIONS_PRICE_IN_PER_MTOK",
            "MSD_BASE_URL", "MSD_MODEL", "MSD_PATH", "MSD_PRICE_IN_PER_MTOK"]   # never keys


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()[:16]


def plan_calls(cases: list[dict], providers: list[str], orders: list[str], repeat: int, seed: int) -> list[tuple]:
    work = [(p, c, o, "measure") for c in cases for p in providers for o in orders]
    work += [(p, c, "original", "repeat") for c in cases[:repeat] for p in providers]
    random.Random(seed).shuffle(work)
    return work


async def execute(clients: dict[str, Client], cases: list[dict], orders: list[str], repeat: int, warmup: int,
                  concurrency: int, seed: int, out: Path | None = None, quiet: bool = False) -> list[dict]:
    log = (out / "calls.jsonl").open("w", encoding="utf-8") if out else None
    results: list[dict] = []

    def record(a: Answer) -> None:
        d = a.to_json()
        results.append(d)
        if log:
            log.write(json.dumps(d, ensure_ascii=False) + "\n")
            log.flush()

    try:
        # warm-up: sequential, excluded from metrics (still billed)
        for name, cl in clients.items():
            for c in cases[:warmup]:
                record(await cl.ask(c, "original", "warmup"))
        work = plan_calls(cases, list(clients), orders, repeat, seed)
        sems = {name: asyncio.Semaphore(concurrency) for name in clients}
        done = {name: 0 for name in clients}
        total = {name: sum(w[0] == name for w in work) for name in clients}
        step = max(1, len(work) // 10)
        t0 = time.perf_counter()

        async def one(w: tuple) -> None:
            name, case, order, phase = w
            async with sems[name]:
                a = await clients[name].ask(case, order, phase)
            record(a)
            done[name] += 1
            n = sum(done.values())
            if not quiet and (n % step == 0 or n == len(work)):
                print(f"  {n}/{len(work)} calls ({time.perf_counter() - t0:.0f}s) "
                      + "  ".join(f"{k}: {done[k]}/{total[k]}" for k in clients), flush=True)

        await asyncio.gather(*(one(w) for w in work))
    finally:
        if log:
            log.close()
        for cl in clients.values():
            await cl.aclose()
    return results


def meta(a: argparse.Namespace, data_path: Path, clients: dict[str, Client], started: datetime, secs: float) -> dict:
    try:
        git = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                             timeout=5).stdout.strip() or None
    except Exception:  # noqa: BLE001
        git = None
    rubric = json.dumps([ROUTE_INSTRUCTIONS, ROUTE_CRITERIA, TAKEOVER_INSTRUCTIONS, TAKEOVER_CRITERIA]).encode()
    return {"started_at": started.isoformat(), "duration_s": round(secs, 1),
            "command": " ".join(["python -m compare.run", *sys.argv[1:]]),
            "args": {k: v for k, v in vars(a).items()},
            "mock": a.mock,
            "providers": {n: {"label": c.label, "model_requested": c.model, "endpoint": getattr(c, "url", None) if not a.mock else "mock",
                              "wire_format": getattr(c, "wire", None) if not a.mock else "mock",
                              "price_in_per_mtok": c.price_in} for n, c in clients.items()},
            "config": {k: os.environ.get(k) for k in SAFE_ENV},
            "dataset": {"path": str(data_path), "sha256": _sha(data_path.read_bytes())},
            "rubric_version": RUBRIC_VERSION, "rubric_sha256": _sha(rubric),
            "policy": {"version": POLICY_VERSION, **Thresholds().as_dict()},
            "git_commit": git, "python": platform.python_version(), "platform": platform.platform(),
            "client_location_note": a.location or None}


def console_summary(summary: dict, m: dict) -> str:
    buf = io.StringIO()
    with redirect_stdout(buf):
        print(f"\n{'MOCK RUN: numbers are simulated, not evidence' if m['mock'] else 'LIVE RUN'} · "
              f"{summary['cases']} cases · {m['duration_s']}s")
        for p, r in summary["providers"].items():
            L, C, A, R = r["latency"], r["cost"], r["accuracy"], r["reliability"]
            fmt = lambda v, f="{:.0f}": "–" if v is None else f.format(v)  # noqa: E731
            print(f"\n{m['providers'][p]['label']} ({', '.join(r['served_models']) or m['providers'][p]['model_requested']})")
            print(f"  latency  p50 {fmt(L['p50'])} ms  p95 {fmt(L['p95'])} ms  p99 {fmt(L['p99'])} ms  (n={L['n']})"
                  + (f"  server-reported p50 {fmt(L['server_reported']['p50'])} ms" if L["server_reported"] else ""))
            print(f"  cost     ${C['per_1k_decisions_usd']:.4f} per 1k decisions · ${C['billed_in_run_usd']:.4f} this run"
                  + (f" (provider-reported ${C['provider_reported_usd']:.4f})" if C["provider_reported_usd"] is not None else "")
                  + f" · {fmt(r['tokens']['input_per_call'])} input tokens/call")
            print(f"  accuracy route {A['route_accuracy']:.1%}  action {A['action_accuracy']:.1%}  "
                  f"fraud approved {A['fraud_auto_approved']}  manual reviews {A['manual_reviews']}")
            print(f"  calib    ECE {fmt(r['calibration']['ece'], '{:.3f}')}  Brier {fmt(r['calibration']['brier'], '{:.3f}')}  "
                  f"top prob ≥0.95: {fmt(r['calibration']['share_top_ge_0_95'], '{:.0%}')}  "
                  f"takeover AUC {fmt(r['takeover']['auc'], '{:.3f}')}")
            print(f"  reliab.  {R['ok']}/{R['measure_calls']} ok  errors {R['errors'] or 0}  retried {R['calls_needing_retry']}")
            ac = A["route_classes"]
            print(f"  balance  macro-F1 {fmt(ac['macro_f1'], '{:.1%}')}  balanced accuracy {fmt(ac['balanced_accuracy'], '{:.1%}')}  "
                  + "  ".join(f"F1 {k.split('_')[0]} {v['f1']:.0%}" for k, v in ac["per_class"].items()))
            if r["order"]:
                o = r["order"]
                pos = o.get("position")
                print(f"  order    {len(o['orders'])} orders: same route in every order {fmt(o['same_route_in_every_order'], '{:.1%}')} "
                      f"({o['cases_route_changed']} of {o['cases_all_orders_ok']} answered in all orders changed)  "
                      f"same action {fmt(o['same_action_in_every_order'], '{:.1%}')}  "
                      f"P(approve) range mean {fmt(o['p_approve_range_mean'], '{:.3f}')}  "
                      f"macro-F1 spread {fmt(o['macro_f1_spread'], '{:.1%}')}"
                      + (f"  position bias {', '.join(f'{x:+.3f}' for x in pos['bias_vs_one_third'])}" if pos else ""))
            if r["repeat"]:
                q = r["repeat"]
                from .report import share
                print(f"  repeat   same choice {share(q.get('same_choice_count'), q['pairs'])}  "
                      f"identical probs {share(q.get('identical_count'), q['pairs'])}  "
                      f"max Δp {fmt(q['max_abs_delta'], '{:.3f}')}")
            for msg, n in R["error_samples"].items():
                print(f"  ! {n}x {msg}")
        from .providers import SHORT_LABELS
        short = lambda p: SHORT_LABELS.get(p, p)  # noqa: E731
        for h in summary.get("pairs", []):
            A, B = short(h["a"]), short(h["b"])
            mf = h["macro_f1"]
            lo, hi = mf["difference_ci95"]
            print(f"\n{A} vs {B} on {h['cases']} cases: both right {h['both_right']}, only {A} {h['only_a_right']}, "
                  f"only {B} {h['only_b_right']}, neither {h['neither_right']} · route agreement {h['route_agreement']:.0%}"
                  + (f" · {A} faster on {h['a_faster_share']:.0%} of paired calls" if h["a_faster_share"] is not None else ""))
            print(f"  macro-F1 {A} {mf['a']:.1%} vs {B} {mf['b']:.1%}: difference {mf['difference']:+.1%} "
                  f"(95% CI {lo:+.1%} to {hi:+.1%}{', excludes 0' if lo > 0 or hi < 0 else ', includes 0'})")
        rk = summary.get("ranking")
        if rk and len(summary["providers"]) > 2:
            print("\nranking  " + " | ".join(f"{k}: {' > '.join(short(p) for p in v)}" for k, v in rk.items()))
    return buf.getvalue()


def main(argv: list[str] | None = None) -> Path:
    ap = argparse.ArgumentParser(description="Jev vs OpenAI Decisions vs Microsoft Decision-1, head to head")
    ap.add_argument("--data", default=str(ROOT / "data" / "cases.jsonl"))
    ap.add_argument("--providers", default="jev,openai,microsoft", help="any of jev,openai,microsoft")
    ap.add_argument("--limit", type=int, default=0, help="use only the first N cases")
    ap.add_argument("--orders", choices=list(ORDER_SETS), default="all",
                    help="all = every permutation of the three options (6 orders); both = original + reversed; "
                         "original = no order check")
    ap.add_argument("--repeat", type=int, default=50, help="ask the first N cases a second time (repeatability)")
    ap.add_argument("--warmup", type=int, default=5)
    ap.add_argument("--concurrency", type=int, default=4, help="in-flight requests per provider")
    ap.add_argument("--timeout", type=float, default=30.0)
    ap.add_argument("--seed", type=int, default=2026, help="call-order shuffle seed")
    ap.add_argument("--label", default="")
    ap.add_argument("--location", default="", help="optional note, e.g. 'Columbus OH, home fibre'")
    ap.add_argument("--mock", action="store_true", help="simulated providers; no keys, no cost, numbers are fake")
    ap.add_argument("--yes", action="store_true", help="skip the cost confirmation for large live runs")
    a = ap.parse_args(argv)

    load_env()
    data_path = Path(a.data)
    cases = load(data_path)
    if a.limit:
        cases = cases[: a.limit]
    providers = [p.strip() for p in a.providers.split(",") if p.strip()]
    orders = ORDER_SETS[a.orders]
    repeat = min(a.repeat, len(cases))
    try:
        clients = {p: make_client(p, a.mock, a.timeout) for p in providers}
    except (RuntimeError, ValueError) as exc:
        raise SystemExit(f"error: {exc}") from None

    n_calls = len(providers) * (len(cases) * len(orders) + repeat + min(a.warmup, len(cases)))
    est = sum(len(cases) * len(orders) + repeat + a.warmup for _ in providers)
    print(f"{len(cases)} cases × {len(orders)} order(s) + {repeat} repeats + {a.warmup} warm-up, per provider "
          f"→ {n_calls} API calls ({', '.join(providers)}){' [MOCK]' if a.mock else ''}")
    if not a.mock:
        rough = sum(c.price_in for c in clients.values()) * 800 / 1e6 * (est / len(providers))
        print(f"rough cost at ~800 input tokens/call: ${rough:.3f}")
        if n_calls > 400 and not a.yes and sys.stdin.isatty():
            if input("continue? [y/N] ").strip().lower() != "y":
                raise SystemExit("cancelled")

    started = datetime.now(timezone.utc)
    stamp = started.strftime("%Y%m%d-%H%M%SZ") + ("-mock" if a.mock else "") + (f"-{a.label}" if a.label else "")
    out = ROOT / "runs" / stamp
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    calls = asyncio.run(execute(clients, cases, orders, repeat, min(a.warmup, len(cases)), a.concurrency, a.seed, out))
    m = meta(a, data_path, clients, started, time.perf_counter() - t0)
    summary = summarize(calls, cases)
    (out / "meta.json").write_text(json.dumps(m, indent=2), encoding="utf-8")
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    from .report import write_reports
    try:
        write_reports(out, m, summary)
    except Exception as exc:  # noqa: BLE001 - the data is already saved; never lose the console summary
        print(f"\n! report generation failed ({type(exc).__name__}: {exc}). Data is saved in {out}; "
              f"after fixing, rebuild with: python -m compare.report {out}")
    text = console_summary(summary, m)
    (out / "console.txt").write_text(text, encoding="utf-8")
    print(text)
    print(f"\nrun folder -> {out}\nreport     -> {out / 'report.html'}")
    return out


if __name__ == "__main__":
    main()
