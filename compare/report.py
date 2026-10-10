"""report.md (renders on GitHub) and report.html (self-contained, for screenshots) from one summary.

    python -m compare.report runs/<folder>      # rebuild both from summary.json + meta.json
"""

from __future__ import annotations

import html
import json
import sys
from pathlib import Path

from .providers import LABELS as LABEL
from .rubric import order_label

SERIES = {"jev": 1, "openai": 2, "microsoft": 3}
ROUTES = ("approve", "step_up_verification", "manual_review")
ORDER_CODE = lambda o: order_label(o).split(" ")[0]  # noqa: E731
SHORT = {"approve": "Approve", "step_up_verification": "Step-up", "manual_review": "Manual review", "error": "Error"}


def _f(v, spec="{:.0f}", none="–"):
    return none if v is None else spec.format(v)


def _ms(v):
    return _f(v, "{:,.0f} ms")


def _usd(v, places=4):
    return "–" if v is None else f"${v:,.{places}f}"


def _pc(v, places=1):
    return "–" if v is None else f"{v:.{places}%}"


def share(n: int | None, d: int | None) -> str:
    """'499 / 500 (99.8%)'. Never prints 100% or 0% unless it is exactly all or none."""
    if n is None or not d:
        return "–"
    v = n / d
    if 0 < n < d:
        pct = f"{v:.1%}"
        if pct == "100.0%":
            pct = ">99.9%"
        elif pct == "0.0%":
            pct = "<0.1%"
    else:
        pct = "100%" if n == d else "0%"
    return f"{n} / {d} ({pct})"


def headline_rows(s: dict) -> list[tuple[str, str, callable]]:
    """(section, metric, fn(provider_metrics) -> str)."""
    sr = lambda r: r["latency"]["server_reported"] or {}  # noqa: E731
    return [
        ("Latency", "p50", lambda r: _ms(r["latency"]["p50"])),
        ("Latency", "p95", lambda r: _ms(r["latency"]["p95"])),
        ("Latency", "p99", lambda r: _ms(r["latency"]["p99"])),
        ("Latency", "p95 including retries", lambda r: _ms(r["latency"]["p95_including_retries"])),
        ("Latency", "server-reported processing p50", lambda r: _ms(sr(r).get("p50")) if sr(r) else "not reported"),
        ("Cost", "per 1,000 decisions (list price)", lambda r: _usd(r["cost"]["per_1k_decisions_usd"])),
        ("Cost", "per 1 million decisions", lambda r: _usd(r["cost"]["per_1m_decisions_usd"], 2)),
        ("Cost", "billed in this run", lambda r: _usd(r["cost"]["billed_in_run_usd"], 5)
            + (f" (provider says {_usd(r['cost']['provider_reported_usd'], 5)})" if r["cost"]["provider_reported_usd"] is not None else "")),
        ("Cost", "input tokens per call", lambda r: _f(r["tokens"]["input_per_call"])),
        ("Cost", "output tokens per call", lambda r: _f(r["tokens"]["output_per_call"], "{:.1f}")),
        ("Accuracy", "route matches analyst label (all cases)", lambda r: _pc(r["accuracy"]["route_accuracy"])),
        ("Accuracy", "route accuracy (answered cases only)", lambda r: _pc(r["accuracy"]["route_accuracy_answered"])),
        ("Accuracy", "route macro-F1 (each class weighted equally)", lambda r: _pc(r["accuracy"]["route_classes"]["macro_f1"])),
        ("Accuracy", "route balanced accuracy (mean recall per class)", lambda r: _pc(r["accuracy"]["route_classes"]["balanced_accuracy"])),
        ("Accuracy", "final action matches label (same policy)", lambda r: _pc(r["accuracy"]["action_accuracy"])),
        ("Accuracy", "final action macro-F1", lambda r: _pc(r["accuracy"]["action_classes"]["macro_f1"])),
        ("Accuracy", "fraud auto-approved", lambda r: str(r["accuracy"]["fraud_auto_approved"])),
        ("Accuracy", "manual reviews (unnecessary)", lambda r: f"{r['accuracy']['manual_reviews']} ({r['accuracy']['unnecessary_manual_reviews']})"),
        ("Calibration", "ECE (lower is better)", lambda r: _f(r["calibration"]["ece"], "{:.3f}")),
        ("Calibration", "Brier score (lower is better)", lambda r: _f(r["calibration"]["brier"], "{:.3f}")),
        ("Calibration", "log loss (lower is better)", lambda r: _f(r["calibration"]["log_loss"], "{:.3f}")),
        ("Calibration", "top probability ≥ 0.95", lambda r: _pc(r["calibration"]["share_top_ge_0_95"], 0)),
        ("Calibration", "takeover question AUC", lambda r: _f(r["takeover"]["auc"], "{:.3f}")),
        ("Reliability", "successful calls", lambda r: f"{r['reliability']['ok']} / {r['reliability']['measure_calls']}"),
        ("Reliability", "errors by kind", lambda r: ", ".join(f"{k}: {v}" for k, v in r["reliability"]["errors"].items()) or "none"),
        ("Reliability", "calls that needed a retry", lambda r: str(r["reliability"]["calls_needing_retry"])),
        ("Robustness", "same route in every option order", lambda r: "not run" if not r["order"] else
            f"{_pc(r['order']['same_route_in_every_order'])} ({r['order']['cases_route_changed']} of "
            f"{r['order']['cases_all_orders_ok']} changed, {len(r['order']['orders'])} orders)"),
        ("Robustness", "same final action in every option order", lambda r: "not run" if not r["order"] else
            share(r["order"].get("cases_same_action"), r["order"]["cases_all_orders_ok"])),
        ("Robustness", "macro-F1 spread across option orders", lambda r: "not run" if not r["order"] else
            _pc(r["order"]["macro_f1_spread"])),
        ("Robustness", "same answer when asked twice", lambda r: "not run" if not r["repeat"] else
            f"same choice {share(r['repeat'].get('same_choice_count'), r['repeat']['pairs'])}; identical probabilities "
            f"{share(r['repeat'].get('identical_count'), r['repeat']['pairs'])}; max change {_f(r['repeat']['max_abs_delta'], '{:.3f}')}"),
    ]


# --------------------------------------------------------------------------- markdown
def _row(cells) -> str:
    return "| " + " | ".join(str(c).replace("|", "/").replace("\n", " ") for c in cells) + " |"


def _table(head, rows) -> list[str]:
    return [_row(head), _row(["---"] * len(head)), *(_row(r) for r in rows)]


def render_md(m: dict, s: dict) -> str:
    P = s["providers"]
    names = [LABEL.get(p, p) for p in P]
    L: list[str] = [f"# {' vs '.join(names)}: run report", ""]
    if m["mock"]:
        L += ["> **MOCK RUN.** Every provider was simulated. Every number below is made up by the mock and says "
              "nothing about any API. Use it only to check that the pipeline works.", ""]
    L += ["## Run", ""]
    L += _table(["Item", "Value"], [
        ["Started (UTC)", m["started_at"]], ["Duration", f"{m['duration_s']} s"], ["Command", f"`{m['command']}`"],
        ["Cases", f"{s['cases']} (dataset sha256 {m['dataset']['sha256']})"],
        ["Rubric", f"version {m['rubric_version']} · sha256 {m['rubric_sha256']}"],
        ["Policy", f"{m['policy']['version']} · approve > {m['policy']['approve_min_probability']}, confidence ≥ "
                   f"{m['policy']['approve_min_confidence']}, review ≥ {m['policy']['manual_review_min_probability']}, "
                   f"takeover ≥ {m['policy']['account_takeover_max']}, ceiling ${m['policy']['auto_approve_ceiling_usd']:,.0f}"],
        *[[f"{LABEL.get(p, p)}", f"{v['endpoint']} ({v.get('wire_format') or '–'}) · model requested `{v['model_requested']}` · "
                                 f"served `{', '.join(P[p]['served_models']) if p in P else '–'}` · ${v['price_in_per_mtok']}/M input tokens"]
          for p, v in m["providers"].items()],
        ["Concurrency / timeout / warm-up", f"{m['args']['concurrency']} per provider / {m['args']['timeout']:g} s / {m['args']['warmup']} calls"],
        ["Client location", m.get("client_location_note") or "not recorded (add --location)"],
        ["Code version", m.get("git_commit") or "not a git checkout"],
        ["Environment", f"Python {m['python']} · {m['platform']}"],
    ])
    L += ["", "## Headline", ""]
    rows = headline_rows(s)
    L += _table(["", "Metric", *names], [[sec, met, *(fn(P[p]) for p in P)] for sec, met, fn in rows])

    pairs = s.get("pairs") or []
    if pairs:
        sup = next(iter(P.values()))["accuracy"]["route_classes"]["per_class"]
        counts = ", ".join(f"{sup[k]['support']} {SHORT[k].lower()}" for k in ROUTES)
        L += ["", "## Same cases, side by side", "",
              f"Every pair of providers on the same cases (original option order). **Macro-F1** weights each route "
              f"equally, so the largest class can't dominate (this set has {counts}). The interval is a paired "
              f"bootstrap over cases ({pairs[0]['macro_f1']['bootstrap_resamples']:,} resamples): if it excludes 0, "
              "the gap is not an artefact of which cases happened to be in the dataset.", ""]
        L += _table(["A vs B", "Both right", "Only A", "Only B", "Neither", "Route agreement", "Action agreement",
                     "Macro-F1 A / B", "Difference (95% CI)", "Separated?", "A faster"],
                    [[f"{LABEL.get(h['a'], h['a'])} vs {LABEL.get(h['b'], h['b'])}", h["both_right"], h["only_a_right"],
                      h["only_b_right"], h["neither_right"], _pc(h["route_agreement"]), _pc(h["action_agreement"]),
                      f"{_pc(h['macro_f1']['a'])} / {_pc(h['macro_f1']['b'])}",
                      f"{h['macro_f1']['difference']:+.1%} ({h['macro_f1']['difference_ci95'][0]:+.1%} to {h['macro_f1']['difference_ci95'][1]:+.1%})",
                      "yes" if h["macro_f1"]["difference_ci95"][0] > 0 or h["macro_f1"]["difference_ci95"][1] < 0 else "no",
                      _pc(h["a_faster_share"], 0)] for h in pairs])
        rk = s.get("ranking")
        if rk and len(P) > 2:
            L += ["", "Ranking: " + "; ".join(f"**{k.replace('_', ' ')}** " + " > ".join(LABEL.get(p, p) for p in v)
                                            for k, v in rk.items()) + ".", ""]
        L += [""]
    L += ["### Per-route precision, recall and F1 (original option order)", ""]
    L += _table(["Route", "Cases", *(f"{n} {m}" for n in names for m in ("precision", "recall", "F1"))],
                [[SHORT[k], next(iter(P.values()))["accuracy"]["route_classes"]["per_class"][k]["support"],
                  *(_pc(P[p]["accuracy"]["route_classes"]["per_class"][k][m], 0) for p in P for m in ("precision", "recall", "f1"))]
                 for k in ROUTES])
    L += [""]
    arch = sorted({a for r in P.values() for a in r["accuracy"]["per_archetype_route_accuracy"]})
    L += ["### Route accuracy by case type", ""]
    L += _table(["Case type", "Cases", *names], [[a, s["archetypes"].get(a, ""),
                *(_pc(P[p]["accuracy"]["per_archetype_route_accuracy"].get(a), 0) for p in P)] for a in arch])
    for p, r in P.items():
        L += ["", f"### Confusion matrix: {LABEL.get(p, p)} (rows = analyst label, columns = model's choice)", ""]
        cols = [*ROUTES, "error"]
        L += _table(["Label \\ answer", *(SHORT[c] for c in cols)],
                    [[SHORT[e], *(r["accuracy"]["confusion"].get(e, {}).get(c, 0) for c in cols)] for e in ROUTES])
    L += ["", "## Calibration", "", "When a model says 80%, is it right about 80% of the time? Bins are by the model's top probability.", ""]
    for p, r in P.items():
        L += [f"**{LABEL.get(p, p)}**", ""]
        L += _table(["Top probability", "Cases", "Mean stated", "Actually right"],
                    [[b["bin"], b["n"], _pc(b["mean_conf"], 0), _pc(b["accuracy"], 0)] for b in r["calibration"]["table"]])
        L += [""]
    if any(r["order"] for r in P.values()):
        some = next(r["order"] for r in P.values() if r["order"])
        L += ["## Option-order check", "", f"Same case, same rubric, the three options listed in {len(some['orders'])} "
              "different orders. A model that reads the content and not the order gives the same answer every time.", ""]
        O = {p: r["order"] for p, r in P.items()}
        val = lambda p, f: f(O[p]) if O[p] else "–"  # noqa: E731
        L += _table(["", *names], [
            ["Cases answered in every order", *(val(p, lambda o: str(o["cases_all_orders_ok"])) for p in P)],
            ["Same route in every order", *(val(p, lambda o: share(o["cases_all_orders_ok"] - o["cases_route_changed"], o["cases_all_orders_ok"])) for p in P)],
            ["Cases whose route changed", *(val(p, lambda o: str(o["cases_route_changed"])) for p in P)],
            ["Distinct routes per case (1 / 2 / 3)", *(val(p, lambda o: " / ".join(str(o["distinct_routes_per_case"].get(k, o["distinct_routes_per_case"].get(str(k), 0))) for k in (1, 2, 3))) for p in P)],
            ["Same final action in every order", *(val(p, lambda o: share(o.get("cases_same_action"), o["cases_all_orders_ok"])) for p in P)],
            ["P(approve) range across orders, mean", *(val(p, lambda o: _f(o["p_approve_range_mean"], "{:.3f}")) for p in P)],
            ["P(approve) range across orders, p95", *(val(p, lambda o: _f(o["p_approve_range_p95"], "{:.3f}")) for p in P)],
            ["Largest range, any option", *(val(p, lambda o: _f(o["max_range_any_route"], "{:.3f}")) for p in P)],
            ["Route accuracy, best − worst order", *(val(p, lambda o: _pc(o["route_accuracy_spread"])) for p in P)],
            ["Macro-F1, best − worst order", *(val(p, lambda o: _pc(o["macro_f1_spread"])) for p in P)],
        ])
        L += ["", "### By order", ""]
        orders = some["orders"]
        L += _table(["Order (A = approve, S = step-up, M = manual review)",
                     *(f"{n} {m}" for n in names for m in ("accuracy", "macro-F1"))],
                    [[order_label(o), *(x for p in P for x in (
                        (_pc(O[p]["per_order"][o]["route_accuracy"]), _pc(O[p]["per_order"][o]["macro_f1"]))
                        if O[p] and o in O[p]["per_order"] else ("–", "–")))] for o in orders])
        if any(O[p] and O[p].get("position") for p in P):
            L += ["", "### Position bias (all six orders)", "",
                  "Across the six orders every option sits in every position equally often, so an order-blind model "
                  "averages exactly 1/3 probability per position. A positive number means the model favours that slot.", ""]
            L += _table(["Position", *(f"{n}: mean P / bias / chosen" for n in names)],
                        [[f"listed {k + 1}{['st', 'nd', 'rd'][k]}", *(
                            f"{_f(O[p]['position']['mean_probability_by_position'][k], '{:.3f}')} / "
                            f"{_f(O[p]['position']['bias_vs_one_third'][k], '{:+.3f}')} / "
                            f"{_pc(O[p]['position']['share_chosen_by_position'][k], 0)}"
                            if O[p] and O[p].get("position") else "–" for p in P)] for k in range(3)])
        for p in P:
            if O[p] and O[p]["changed_examples"]:
                L += ["", f"{LABEL.get(p, p)}, cases whose route changed (first 10): " + "; ".join(
                    f"{x['case']} ({x['archetype']}): " + ", ".join(f"{ORDER_CODE(o)} {SHORT[c][0]}" for o, c in x["answers"].items())
                    for x in O[p]["changed_examples"])]
        L += [""]
    if any(r["repeat"] for r in P.values()):
        L += ["## Repeatability", "", "The first cases asked a second time, identical request.", ""]
        L += _table(["", *names], [
            ["Pairs", *(str(r["repeat"]["pairs"]) if r["repeat"] else "–" for r in P.values())],
            ["Same choice", *(share(r["repeat"].get("same_choice_count"), r["repeat"]["pairs"]) if r["repeat"] else "–" for r in P.values())],
            ["Identical probabilities (all three, exact)", *(share(r["repeat"].get("identical_count"), r["repeat"]["pairs"]) if r["repeat"] else "–" for r in P.values())],
            ["Largest probability change", *(_f(r["repeat"]["max_abs_delta"], "{:.3f}") if r["repeat"] else "–" for r in P.values())],
            ["Same final action", *(share(r["repeat"].get("same_action_count"), r["repeat"]["pairs"]) if r["repeat"] else "–" for r in P.values())],
        ])
        L += [""]
    L += ["## Confidence field", ""]
    L += _table(["", *names], [
        ["Where confidence came from", *(", ".join(f"{k}: {v}" for k, v in r["confidence"]["source"].items()) or "–" for r in P.values())],
        ["Gap from (k·p_max−1)/(k−1), max", *(_f(r["confidence"]["formula_gap_max"], "{:.4f}") for r in P.values())],
        ["Stated choice ≠ highest probability", *(str(r["confidence"]["choice_not_highest_probability"]) for r in P.values())],
    ])
    dis = s.get("disagreements") or []
    if dis:
        L += ["", f"## Where they disagree ({len(dis)} cases, first 25)", ""]
        L += _table(["Case", "Type", "Label", *names],
                    [[d["case"], d["archetype"], SHORT[d["expected"]], *(SHORT.get(d["answers"][p], d["answers"][p] or "–") for p in P)]
                     for d in dis[:25]])
    errs = {p: r["reliability"]["error_samples"] for p, r in P.items() if r["reliability"]["error_samples"]}
    if errs:
        L += ["", "## Error samples", ""]
        for p, e in errs.items():
            L += [f"- **{LABEL.get(p, p)}**: " + "; ".join(f"{n}× `{msg}`" for msg, n in e.items())]
    L += ["", "## How to read this", "",
          "- **Latency** is wall-clock time from this machine, per successful call, warm-up excluded. It includes the "
          "network path to each provider, which depends on where you ran it. Server-reported processing time is shown "
          "when a provider sends it in a response header.",
          "- **Cost** is list price × the tokens each API reported. None of the APIs charges for output tokens. The "
          "tokenizers differ, so the same request can count as a different number of tokens.",
          "- **Accuracy** is against synthetic analyst labels. It tells you how each model reads this rubric on these "
          "cases, not how it would do on your production traffic.",
          "- **Final action** applies one fixed policy to every model. A model can pick the right route and still get a "
          "different action if its probabilities are more or less extreme. That is what the calibration rows explain.",
          "- **One run** is one sample. Run it again on another day before quoting small differences.",
          "- The OpenAI Decisions API is a public beta; behaviour and prices may change.",
          "- Microsoft Decision-1 was released on 9 Oct 2026. Microsoft says its weights are updated continually and "
          "it may be rebased on other models, so pin the served model in each run's metadata when you quote it.",
          "- Every call, with the full response body, is in `calls.jsonl` in this folder.", ""]
    return "\n".join(L)


# --------------------------------------------------------------------------- html
CSS = """
:root{color-scheme:light;--page:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;--grid:#e1e0d9;
--ring:rgba(11,11,11,.10);--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--warn-bg:#fff4dc;--warn-ink:#6b4a00}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;
--ink:#fff;--ink2:#c3c2b7;--muted:#898781;--grid:#2c2c2a;--ring:rgba(255,255,255,.10);--s1:#3987e5;--s2:#d95926;--s3:#199e70;--warn-bg:#3a2d0b;--warn-ink:#f5d58a}}
:root[data-theme="dark"]{color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;--ink:#fff;--ink2:#c3c2b7;--grid:#2c2c2a;
--ring:rgba(255,255,255,.10);--s1:#3987e5;--s2:#d95926;--s3:#199e70;--warn-bg:#3a2d0b;--warn-ink:#f5d58a}
*{box-sizing:border-box}body{margin:0;background:var(--page);color:var(--ink);font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px 64px}h1{font-size:24px;margin:0 0 4px}h2{font-size:16px;margin:28px 0 8px}
.sub{color:var(--ink2);margin:0 0 16px}.banner{background:var(--warn-bg);color:var(--warn-ink);border-radius:8px;padding:12px 14px;margin:16px 0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px}
.card{background:var(--surface);border-radius:10px;box-shadow:0 0 0 1px var(--ring);padding:16px;min-width:0}
.card h3{font-size:14px;margin:0 0 2px}.card p{color:var(--ink2);font-size:12px;margin:0 0 12px}
.legend{display:flex;gap:16px;font-size:12px;color:var(--ink2);margin:8px 0 0}
.legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;vertical-align:-1px}
.bars{display:grid;grid-template-columns:auto 1fr auto;gap:2px 10px;align-items:center;font-size:12px}
.bars .k{color:var(--ink2);white-space:nowrap}.bars .v{color:var(--ink);font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap}
.track{height:14px;position:relative}.bar{height:14px;border-radius:0 4px 4px 0;min-width:2px}
.gap{grid-column:1/-1;height:8px}
table{border-collapse:collapse;width:100%;font-size:13px}th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--grid);vertical-align:top}
th{color:var(--ink2);font-weight:500;font-size:12px}td.n{text-align:right;font-variant-numeric:tabular-nums}
td.sec{color:var(--muted);font-size:12px}.scroll{overflow-x:auto}
#tip{position:fixed;pointer-events:none;background:var(--surface);color:var(--ink);box-shadow:0 0 0 1px var(--ring),0 4px 14px rgba(0,0,0,.15);
border-radius:6px;padding:6px 9px;font-size:12px;display:none;z-index:9}
details summary{cursor:pointer;color:var(--ink2);font-size:13px;margin-top:12px}code{font-size:12px}
"""

JS = """const tip=document.getElementById('tip');document.addEventListener('mousemove',e=>{const t=e.target.closest('[data-tip]');
if(!t){tip.style.display='none';return}tip.innerHTML=t.dataset.tip;tip.style.display='block';
tip.style.left=Math.min(e.clientX+14,innerWidth-tip.offsetWidth-8)+'px';tip.style.top=Math.min(e.clientY+14,innerHeight-tip.offsetHeight-8)+'px'});"""


def _bars(title: str, note: str, groups: list[tuple[str, dict[str, float | None]]], fmt) -> str:
    vals = [v for _, g in groups for v in g.values() if v is not None]
    top = max(vals) if vals else 1
    rows = []
    for gi, (gname, g) in enumerate(groups):
        if gi:
            rows.append('<div class="gap"></div>')
        for p, v in g.items():
            w = 0 if v is None or top == 0 else 100 * v / top
            tipv = html.escape(f"<b>{LABEL.get(p, p)}</b><br>{gname}: {fmt(v)}")
            rows.append(f'<div class="k">{html.escape(gname) if p == next(iter(g)) else ""}</div>'
                        f'<div class="track" data-tip="{tipv}"><div class="bar" style="width:{w:.1f}%;background:var(--s{SERIES.get(p, 1)})"></div></div>'
                        f'<div class="v">{html.escape(fmt(v))}</div>')
    return (f'<div class="card"><h3>{html.escape(title)}</h3><p>{html.escape(note)}</p>'
            f'<div class="bars">{"".join(rows)}</div></div>')


def _html_table(head, rows, numeric_from: int = 1) -> str:
    right = ' style="text-align:right"'
    th = "".join(f"<th{right if i >= numeric_from else ''}>{html.escape(str(h))}</th>" for i, h in enumerate(head))
    body = "".join("<tr>" + "".join(
        f'<td class="{"n" if i >= numeric_from else ("sec" if i == 0 and len(head) > 3 else "")}">{html.escape(str(c))}</td>'
        for i, c in enumerate(r)) + "</tr>" for r in rows)
    return f'<div class="scroll"><table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>'


def render_html(m: dict, s: dict, md: str) -> str:
    P = s["providers"]
    names = [LABEL.get(p, p) for p in P]
    legend = "".join(f'<span><i style="background:var(--s{SERIES.get(p, 1)})"></i>{html.escape(LABEL.get(p, p))}</span>' for p in P)
    g = lambda f: {p: f(r) for p, r in P.items()}  # noqa: E731
    charts = [
        _bars("Latency", "Wall-clock per successful call, warm-up excluded. Lower is better.",
              [("p50", g(lambda r: r["latency"]["p50"])), ("p95", g(lambda r: r["latency"]["p95"]))], _ms),
        _bars("Cost per 1,000 decisions", "List price × reported input tokens. Output is free on all three.",
              [("per 1k", g(lambda r: r["cost"]["per_1k_decisions_usd"]))], lambda v: _usd(v)),
        _bars("Accuracy", "Against analyst labels, original option order. Higher is better.",
              [("route", g(lambda r: r["accuracy"]["route_accuracy"])), ("route macro-F1", g(lambda r: r["accuracy"]["route_classes"]["macro_f1"])),
               ("final action", g(lambda r: r["accuracy"]["action_accuracy"]))],
              lambda v: _pc(v)),
        _bars("Calibration error (ECE)", "Gap between stated and actual confidence. Lower is better.",
              [("ECE", g(lambda r: r["calibration"]["ece"]))], lambda v: _f(v, "{:.3f}")),
    ]
    rows = headline_rows(s)
    head = _html_table(["", "Metric", *names], [[sec, met, *(fn(P[p]) for p in P)] for sec, met, fn in rows], 2)
    arch = sorted({a for r in P.values() for a in r["accuracy"]["per_archetype_route_accuracy"]})
    arch_t = _html_table(["Case type", "Cases", *names], [[a, s["archetypes"].get(a, ""),
                         *(_pc(P[p]["accuracy"]["per_archetype_route_accuracy"].get(a), 0) for p in P)] for a in arch])
    pr = s.get("pairs") or []
    h2h = "" if not pr else '<div class="card" style="margin-bottom:16px">' + _html_table(
        ["A vs B", "Both right", "Only A", "Only B", "Macro-F1 A / B", "Difference (95% CI)"],
        [[f"{LABEL.get(h['a'], h['a'])} vs {LABEL.get(h['b'], h['b'])}", h["both_right"], h["only_a_right"], h["only_b_right"],
          f"{_pc(h['macro_f1']['a'])} / {_pc(h['macro_f1']['b'])}",
          f"{h['macro_f1']['difference']:+.1%} ({h['macro_f1']['difference_ci95'][0]:+.1%} to {h['macro_f1']['difference_ci95'][1]:+.1%})"]
         for h in pr]) + "</div>"
    banner = ('<div class="banner"><b>Mock run.</b> Every provider was simulated. These numbers say nothing about any API.</div>'
              if m["mock"] else "")
    prov = " · ".join(f"{LABEL.get(p, p)}: {', '.join(P[p]['served_models']) or v['model_requested']}"
                      for p, v in m["providers"].items() if p in P)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Decision API Benchmark</title><style>{CSS}</style></head><body><main>
<h1>{html.escape(" vs ".join(names))}</h1>
<p class="sub">{html.escape(m['started_at'][:16].replace('T', ' '))} UTC · {s['cases']} cases · {html.escape(prov)} · rubric {m['rubric_version']}</p>
{banner}<div class="legend">{legend}</div>
<div class="grid" style="margin-top:12px">{''.join(charts)}</div>
<h2>Headline</h2><div class="card">{head}</div>
<h2>Same cases, side by side</h2>{h2h}<div class="card">{arch_t}</div>
<details><summary>Full report (same content as report.md)</summary><pre style="white-space:pre-wrap;font-size:12px;color:var(--ink2)">{html.escape(md)}</pre></details>
</main><div id="tip"></div><script>{JS}</script></body></html>"""


def write_reports(out: Path, m: dict, s: dict) -> None:
    md = render_md(m, s)
    (out / "report.md").write_text(md, encoding="utf-8")
    (out / "report.html").write_text(render_html(m, s, md), encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m compare.report runs/<folder>")
    d = Path(sys.argv[1])
    write_reports(d, json.loads((d / "meta.json").read_text(encoding="utf-8")),
                  json.loads((d / "summary.json").read_text(encoding="utf-8")))
    print(f"rebuilt {d / 'report.md'} and {d / 'report.html'}")
