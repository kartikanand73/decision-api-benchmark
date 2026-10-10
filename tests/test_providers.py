"""Wire formats, strict parsing, and identical HTTP behaviour for both clients."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from compare.dataset import generate
from compare.providers import (DecisionsClient, JevClient, Refusal, SchemaError, decisions_request, jev_request,
                               parse_decisions, parse_jev)
from compare.rubric import ROUTE_CRITERIA, ROUTE_INSTRUCTIONS, ROUTES, TAKEOVER_CRITERIA, build_state

CASE = generate(20, 1)[0]


def jev_body(a=0.7, s=0.2, m=0.1, conf=0.55, ato=0.1):
    return {"id": "gen-1", "model": "typesafe/jev-1.13-20260917", "cost": 0.00002,
            "usage": {"input_tokens": 700, "output_tokens": 0},
            "answers": {"route": {"type": "choice", "choice": "approve",
                                  "probabilities": {"approve": a, "step_up_verification": s, "manual_review": m},
                                  "confidence": conf},
                        "account_takeover": {"type": "noul", "noul": ato}}}


def oai_body(a=0.7, s=0.2, m=0.1, conf=0.55, ato=0.1, choice="approve"):
    return {"id": "dec_1", "model": "gpt-6-luna", "usage": {"input_tokens": 720, "output_tokens": 0},
            "answers": [{"type": "choice", "name": "route", "choice": choice, "confidence": conf,
                         "probabilities": [{"value": "approve", "probability": a},
                                           {"value": "step_up_verification", "probability": s},
                                           {"value": "manual_review", "probability": m}]},
                        {"type": "predicate", "name": "account_takeover", "probability": ato}]}


# ---- requests -----------------------------------------------------------------------------
def test_both_requests_carry_identical_state_and_rubric():
    j, o = jev_request(CASE["request"], "jev-1.13"), decisions_request(CASE["request"], "gpt-6-luna")
    assert j["state"] == build_state(CASE["request"]) == json.loads(o["input"].split("\n", 1)[1])
    assert j["questions"]["route"]["instructions"] == o["questions"][0]["instructions"] == ROUTE_INSTRUCTIONS
    assert j["questions"]["route"]["criteria"] == {c["value"]: c["description"] for c in o["questions"][0]["choices"]} == ROUTE_CRITERIA
    assert o["questions"][1]["type"] == "predicate"
    assert TAKEOVER_CRITERIA["true"] in o["questions"][1]["instructions"]      # no criteria field on predicates
    assert "request_id" not in j["state"] and "account_id" not in j["state"]


def test_reversed_order_changes_only_the_order():
    j1, j2 = jev_request(CASE["request"], "m"), jev_request(CASE["request"], "m", "reversed")
    o1, o2 = decisions_request(CASE["request"], "m"), decisions_request(CASE["request"], "m", "reversed")
    assert list(j2["questions"]["route"]["criteria"]) == list(reversed(ROUTES))
    assert j1["questions"]["route"]["criteria"] == j2["questions"]["route"]["criteria"]
    assert [c["value"] for c in o2["questions"][0]["choices"]] == list(reversed(ROUTES))
    assert o1["input"] == o2["input"] and o1["questions"][1] == o2["questions"][1]


# ---- parsers ------------------------------------------------------------------------------
def test_parsers_accept_documented_shapes_and_check_confidence():
    for parsed in (parse_jev(jev_body()), parse_decisions(oai_body())):
        assert parsed["choice"] == "approve" and parsed["probs"]["approve"] == 0.7
        assert parsed["confidence"] == 0.55 and parsed["confidence_formula_gap"] == 0.0   # (3*0.7-1)/2
        assert parsed["confidence_source"] == "api"
    b = oai_body()
    del b["answers"][0]["confidence"]
    assert parse_decisions(b)["confidence_source"] == "derived"


@pytest.mark.parametrize("mutate", [
    lambda b: b["answers"]["route"].__setitem__("choice", "wire_funds"),
    lambda b: b["answers"]["route"]["probabilities"].pop("manual_review"),
    lambda b: b["answers"]["route"]["probabilities"].__setitem__("approve", 0.95),     # sums to 1.25
    lambda b: b["answers"]["account_takeover"].__setitem__("noul", 1.4),
    lambda b: b["answers"].pop("account_takeover"),
    lambda b: b["answers"]["route"].__setitem__("type", "score"),
])
def test_jev_parser_rejects_off_contract(mutate):
    b = jev_body()
    mutate(b)
    with pytest.raises(SchemaError):
        parse_jev(b)


@pytest.mark.parametrize("mutate", [
    lambda b: b["answers"][0].__setitem__("choice", "wire_funds"),
    lambda b: b["answers"][0]["probabilities"].pop(),
    lambda b: b["answers"][0]["probabilities"].append({"value": "approve", "probability": 0.0}),   # duplicate
    lambda b: b["answers"][0]["probabilities"][0].__setitem__("value", "release"),
    lambda b: b["answers"][1].__setitem__("probability", -0.1),
    lambda b: b["answers"].pop(),
    lambda b: b.pop("answers"),
])
def test_decisions_parser_rejects_off_contract(mutate):
    b = oai_body()
    mutate(b)
    with pytest.raises(SchemaError):
        parse_decisions(b)


def test_refusal_is_its_own_error_kind():
    b = oai_body()
    b["answers"][0] = {"type": "refusal", "name": "route"}
    with pytest.raises(Refusal):
        parse_decisions(b)


# ---- HTTP behaviour (same for both clients) --------------------------------------------------
def _client(cls, handler, **kw):
    return cls("k", "https://api.example", "m", 0.10, timeout_s=5,
               client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), **kw)


@pytest.mark.parametrize("cls,body,path", [(JevClient, jev_body(), "/v1/systemone"),
                                           (DecisionsClient, oai_body(), "/decisions")])
def test_success_after_rate_limit_retry(cls, body, path):
    seen = []

    def handler(req):
        seen.append(req)
        if len(seen) == 1:
            return httpx.Response(429, headers={"retry-after": "0"}, json={"error": "slow down"})
        return httpx.Response(200, headers={"openai-processing-ms": "87", "x-request-id": "req_9"}, json=body)

    a = asyncio.run(_client(cls, handler).ask(CASE))
    assert seen[-1].url.path == path and seen[-1].headers["authorization"] == "Bearer k"
    assert a.ok and a.attempts == 2 and a.total_ms >= a.latency_ms > 0
    assert a.cost_usd == pytest.approx(body["usage"]["input_tokens"] * 0.10 / 1e6)
    assert a.server_ms == 87 and a.headers["x-request-id"] == "req_9"
    assert a.raw == body


def test_provider_reported_cost_is_kept():
    a = asyncio.run(_client(JevClient, lambda r: httpx.Response(200, json=jev_body())).ask(CASE))
    assert a.provider_cost_usd == 0.00002 and a.served_model == "typesafe/jev-1.13-20260917"


@pytest.mark.parametrize("handler,kind", [
    (lambda r: httpx.Response(403, json={"error": {"message": "not enabled for the Decisions beta"}}), "http"),
    (lambda r: httpx.Response(200, text="<html>gateway</html>"), "schema"),
    (lambda r: httpx.Response(200, json={"answers": [{"type": "refusal", "name": "route"},
                                                      {"type": "predicate", "name": "account_takeover", "probability": 0.1}]}), "refusal"),
])
def test_failures_are_recorded_not_raised(handler, kind):
    a = asyncio.run(_client(DecisionsClient, handler).ask(CASE))
    assert not a.ok and a.error_kind == kind and a.probs is None
    if kind == "http":
        assert a.status == 403 and "beta" in a.error and a.attempts == 1     # 403 is not retried


def test_timeout_is_recorded():
    def handler(req):
        raise httpx.ReadTimeout("slow", request=req)
    a = asyncio.run(_client(JevClient, handler).ask(CASE))
    assert not a.ok and a.error_kind == "timeout" and a.attempts == 3


# ---- Microsoft Decision-1 (System One wire format, like Jev) --------------------------------
from compare.providers import MicrosoftClient, make_client  # noqa: E402


@pytest.mark.parametrize("base,expected_url", [
    ("https://openrouter.ai/api", "https://openrouter.ai/api/v1/systemone"),
    ("https://myres.services.ai.azure.com", "https://myres.services.ai.azure.com/providers/microsoft/v1/systemone"),
])
def test_microsoft_endpoint_and_body_match_jev(base, expected_url):
    seen = []

    def handler(req):
        seen.append(req)
        return httpx.Response(200, json={**jev_body(), "model": "microsoft-decision-1"})

    c = MicrosoftClient("k", base, "my-deployment", 0.042, timeout_s=5,
                        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    a = asyncio.run(c.ask(CASE))
    assert str(seen[0].url) == expected_url and seen[0].headers["authorization"] == "Bearer k"
    body = json.loads(seen[0].content)
    jev = jev_request(CASE["request"], "x")
    assert body["model"] == "my-deployment" and {k: v for k, v in body.items() if k != "model"} == \
        {k: v for k, v in jev.items() if k != "model"}                        # identical question to Jev
    assert a.ok and a.provider == "microsoft" and a.served_model == "microsoft-decision-1"
    assert a.cost_usd == pytest.approx(700 * 0.042 / 1e6)


def test_microsoft_from_env(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    for k in ("MSD_BASE_URL", "MSD_MODEL", "MSD_PATH", "MSD_PRICE_IN_PER_MTOK"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.delenv("MSD_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="MSD_API_KEY"):
        make_client("microsoft")
    monkeypatch.setenv("MSD_API_KEY", "k")
    c = make_client("microsoft")
    assert c.url == "https://openrouter.ai/api/v1/systemone" and c.model == "microsoft/microsoft-decision-1"
    assert c.price_in == 0.042
    monkeypatch.setenv("MSD_BASE_URL", "https://r.services.ai.azure.com/?api-version=2026-10-01")
    monkeypatch.setenv("MSD_MODEL", "decision1-prod")
    c = make_client("microsoft")
    assert c.url == "https://r.services.ai.azure.com/providers/microsoft/v1/systemone" and c.model == "decision1-prod"
    monkeypatch.setenv("MSD_PATH", "/openai/v1/systemone")
    assert make_client("microsoft").url == "https://r.services.ai.azure.com/openai/v1/systemone"


# ---- OpenAI's decision model through OpenRouter (System One format) -------------------------
def test_openai_via_openrouter_uses_systemone_and_same_body_as_jev(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-or-x")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://openrouter.ai/api")
    monkeypatch.delenv("DECISIONS_MODEL", raising=False)
    c = make_client("openai")
    assert c.url == "https://openrouter.ai/api/v1/systemone" and c.model == "openai/gpt-6-luna-decisions"
    assert c.wire == "systemone (OpenRouter)"
    seen = []

    def handler(req):
        seen.append(req)
        return httpx.Response(200, json={**jev_body(), "model": "openai/gpt-6-luna-decisions-20261006"})

    c._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    a = asyncio.run(c.ask(CASE, "SAM"))
    body = json.loads(seen[0].content)
    assert {k: v for k, v in body.items() if k != "model"} == \
        {k: v for k, v in jev_request(CASE["request"], "x", "SAM").items() if k != "model"}
    assert a.ok and a.provider == "openai" and a.provider_cost_usd == 0.00002


def test_openai_direct_is_unchanged(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("DECISIONS_MODEL", raising=False)
    c = make_client("openai")
    assert c.url == "https://api.openai.com/v1/decisions" and c.model == "gpt-6-luna" and c.wire == "openai /v1/decisions"
    assert "input" in c.build(CASE["request"], "original")



def test_one_openrouter_key_routes_all_three(monkeypatch):
    for k in ("TYPESAFE_API_KEY", "TYPESAFE_BASE_URL", "JEV_MODEL", "OPENAI_API_KEY", "OPENAI_BASE_URL", "DECISIONS_MODEL",
              "MSD_API_KEY", "MSD_BASE_URL", "MSD_MODEL", "MSD_PATH"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-one")
    clients = {p: make_client(p) for p in ("jev", "openai", "microsoft")}
    assert {p: c.url for p, c in clients.items()} == {p: "https://openrouter.ai/api/v1/systemone" for p in clients}
    assert {p: c.model for p, c in clients.items()} == {"jev": "typesafe/jev-1.13", "openai": "openai/gpt-6-luna-decisions",
                                                       "microsoft": "microsoft/microsoft-decision-1"}
    assert all(c.api_key == "sk-or-one" for c in clients.values())
    bodies = [{k: v for k, v in c.build(CASE["request"], "original").items() if k != "model"} for c in clients.values()]
    assert bodies[0] == bodies[1] == bodies[2]                     # identical question to all three
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")              # a provider's own key wins -> direct
    c = make_client("openai")
    assert c.url == "https://api.openai.com/v1/decisions" and c.api_key == "sk-openai"
