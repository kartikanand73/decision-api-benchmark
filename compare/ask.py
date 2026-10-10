"""Ask every API the same single question and show the answers side by side.

    python -m compare.ask                       # first case in data/cases.jsonl
    python -m compare.ask --case case-0042      # a specific case
    python -m compare.ask --archetype ato_quiet # first case of a type
    python -m compare.ask --file my_case.json   # your own withdrawal (a request object, or a full case)
    python -m compare.ask --order SAM --raw     # options as step-up, approve, review; print full requests and responses
    python -m compare.ask --mock                # no keys

Each provider gets one warm-up call first (not shown) so connection setup isn't counted.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from .dataset import load
from .env import ROOT, load_env
from .policy import decide
from .providers import make_client
from .rubric import ORDERS, ROUTES, order_label

SHORT = {"approve": "approve", "step_up_verification": "step-up", "manual_review": "manual review"}


def pick_case(a: argparse.Namespace) -> dict:
    if a.file:
        obj = json.loads(Path(a.file).read_text(encoding="utf-8"))
        if "request" not in obj:          # bare withdrawal request
            obj = {"id": obj.get("request_id", "custom"), "archetype": "custom", "expected_route": None,
                   "expected_action": None, "takeover": None, "request": obj}
        return obj
    cases = load(a.data)
    if a.case:
        hit = [c for c in cases if c["id"] == a.case]
    elif a.archetype:
        hit = [c for c in cases if c["archetype"] == a.archetype]
    else:
        hit = cases[:1]
    if not hit:
        raise SystemExit("no matching case")
    return hit[0]


async def ask_all(case: dict, providers: list[str], order: str, mock: bool, timeout: float) -> dict:
    clients = {p: make_client(p, mock, timeout) for p in providers}
    try:
        for c in clients.values():                       # warm-up, discarded
            await c.ask(case, order, "warmup")
        answers = await asyncio.gather(*(c.ask(case, order) for c in clients.values()))
        return {"clients": clients, "answers": dict(zip(clients, answers)),
                "requests": {p: c.build(case["request"], order) for p, c in clients.items()}}
    finally:
        for c in clients.values():
            await c.aclose()


def render(case: dict, res: dict) -> str:
    A, C = res["answers"], res["clients"]
    cols = list(A)
    w = 24
    cut = lambda v: v if len(v) < w else v[: w - 2] + "…"  # noqa: E731
    line = lambda k, vals: f"  {k:<28}" + "".join(f"{cut(str(v)):<{w}}" for v in vals)  # noqa: E731
    r = case["request"]
    out = [f"\nCase {case['id']} · {case['archetype']} · ${r['amount']:,.2f} · device {r['device_familiarity']} · "
           f"geo {r['geo_pattern']} · notes: {' / '.join(r['context_notes']) or 'none'}"]
    if case.get("expected_route"):
        out.append(f"Analyst label: route {SHORT[case['expected_route']]}, final action {SHORT[case['expected_action']]}")
    out.append("")
    out.append(line("", [C[p].label for p in cols]))
    out.append(line("model served", [str(A[p].served_model or C[p].model) for p in cols]))
    out.append(line("ok", ["yes" if A[p].ok else f"NO ({A[p].error_kind})" for p in cols]))
    out.append(line("choice", [SHORT.get(A[p].choice, "–") for p in cols]))
    for rt in ROUTES:
        out.append(line(f"  P({SHORT[rt]})", [f"{A[p].probs[rt]:.3f}" if A[p].probs else "–" for p in cols]))
    out.append(line("confidence (source)", [f"{A[p].confidence:.3f} ({A[p].confidence_source})" if A[p].ok else "–" for p in cols]))
    out.append(line("P(account takeover)", [f"{A[p].takeover:.3f}" if A[p].ok else "–" for p in cols]))
    acts = {p: decide(r["amount"], A[p].probs, A[p].confidence, A[p].takeover) for p in cols}
    out.append(line("policy action", [SHORT[acts[p][0]] for p in cols]))
    out.append(line("policy reasons", [",".join(acts[p][1])[:w - 1] for p in cols]))
    out.append(line("latency", [f"{A[p].latency_ms:,.0f} ms" for p in cols]))
    out.append(line("server-reported time", [f"{A[p].server_ms:,.0f} ms" if A[p].server_ms is not None else "–" for p in cols]))
    out.append(line("tokens in / out", [f"{A[p].input_tokens} / {A[p].output_tokens}" for p in cols]))
    out.append(line("cost (list price)", [f"${A[p].cost_usd:.7f}" for p in cols]))
    out.append(line("cost per 1k at this size", [f"${A[p].cost_usd * 1000:.4f}" for p in cols]))
    out.append(line("response id", [str(A[p].response_id or "–")[:w - 1] for p in cols]))
    for p in cols:
        if A[p].error:
            out.append(f"\n  ! {C[p].label}: {A[p].error}")
    if any(a.simulated for a in A.values()):
        out.append("\n  [MOCK] simulated answers: not evidence about any API")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Ask Jev, OpenAI Decisions and Microsoft Decision-1 the same question")
    ap.add_argument("--data", default=str(ROOT / "data" / "cases.jsonl"))
    ap.add_argument("--case")
    ap.add_argument("--archetype")
    ap.add_argument("--file")
    ap.add_argument("--providers", default="jev,openai,microsoft", help="any of jev,openai,microsoft")
    ap.add_argument("--reverse", action="store_true", help="list the options in reverse order (same as --order reversed)")
    ap.add_argument("--order", choices=list(ORDERS), default="original",
                    help="option order: original (A-S-M), AMS, SAM, SMA, MAS, reversed (M-S-A)")
    ap.add_argument("--raw", action="store_true", help="print the exact requests and full responses")
    ap.add_argument("--timeout", type=float, default=30.0)
    ap.add_argument("--mock", action="store_true")
    a = ap.parse_args(argv)
    load_env()
    case = pick_case(a)
    try:
        res = asyncio.run(ask_all(case, [p.strip() for p in a.providers.split(",")],
                                  "reversed" if a.reverse else a.order, a.mock, a.timeout))
    except (RuntimeError, ValueError) as exc:
        raise SystemExit(f"error: {exc}") from None
    print(render(case, res))
    print(f"\n  options listed as {order_label('reversed' if a.reverse else a.order)}")
    if a.raw:
        for p, ans in res["answers"].items():
            print(f"\n--- {res['clients'][p].label}: request ---\n{json.dumps(res['requests'][p], indent=2, ensure_ascii=False)}")
            print(f"--- {res['clients'][p].label}: response ---\n{json.dumps(ans.raw, indent=2, ensure_ascii=False)}")


if __name__ == "__main__":
    main()
