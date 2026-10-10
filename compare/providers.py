"""The two API clients, with identical timing, retry and parsing rules.

Each client sends the same question (rubric.py) in its own wire format and returns an `Answer`.
Both use the same HTTP stack, the same retry policy, the same connection reuse and the same clock,
so a latency difference is a difference between the services, not between our two code paths.

What each API receives
----------------------
Microsoft-Decision-1 uses the same System One wire format as Jev (state + questions dict, choice / noul
answers), so it gets byte-for-byte the same request body as Jev except for the model id.

                    Jev / Microsoft  POST .../systemone     OpenAI  POST {base}/decisions
  program state     `state`: JSON object                     `input`: the same JSON, as text
  route question    choice, `criteria` {route: text}         choice, `choices` [{value, description}]
  takeover question noul, `criteria` {true, false}           predicate (no criteria field: the true/false
                                                             descriptions are appended to `instructions`)
  option order      key order of `criteria`                  order of `choices`

None of the three charges for output tokens. Prices come from env vars so they can be updated without code.
"""

from __future__ import annotations

import asyncio
import email.utils
import hashlib
import json
import math
import os
import random
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

from .rubric import (ROUTE_CRITERIA, ROUTE_INSTRUCTIONS, ROUTES, TAKEOVER_CRITERIA, TAKEOVER_INSTRUCTIONS,
                     build_state, confidence_from_probs, ordered_routes)

RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 529}
MAX_ATTEMPTS = 3
KEEP_HEADERS = re.compile(r"(processing|server-timing|request-id|x-generation|ratelimit|retry-after|openai-model|"
                          r"openai-version|x-model)", re.I)


@dataclass
class Answer:
    provider: str
    case_id: str
    order: str                         # original | reversed
    phase: str = "measure"             # warmup | measure | repeat
    ok: bool = False
    error_kind: str | None = None      # http | timeout | network | schema | refusal
    error: str | None = None
    status: int | None = None
    choice: str | None = None
    probs: dict[str, float] | None = None
    confidence: float | None = None
    confidence_source: str | None = None   # api | derived
    confidence_formula_gap: float | None = None
    takeover: float | None = None
    latency_ms: float = 0.0            # wall time of the attempt that produced this answer
    total_ms: float = 0.0              # including retries and back-off
    attempts: int = 0
    server_ms: float | None = None     # provider-reported processing time, when a header gives it
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0              # list price x reported tokens
    provider_cost_usd: float | None = None   # cost the provider itself reported (e.g. OpenRouter)
    served_model: str | None = None
    response_id: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    started_at: str = ""
    simulated: bool = False
    raw: Any = None                    # the full response body, kept as evidence

    def to_json(self) -> dict:
        return asdict(self)


class SchemaError(ValueError):
    """The response did not fit the closed contract (3 routes, valid probabilities, a takeover probability)."""


class Refusal(SchemaError):
    pass


def _check_probs(probs: dict[str, float]) -> dict[str, float]:
    if set(probs) != set(ROUTES):
        raise SchemaError(f"probabilities must cover exactly {list(ROUTES)}, got {sorted(probs)}")
    for k, v in probs.items():
        if not isinstance(v, (int, float)) or not 0.0 <= v <= 1.0 or math.isnan(v):
            raise SchemaError(f"probability for {k} out of range: {v!r}")
    if abs(sum(probs.values()) - 1.0) > 0.02:
        raise SchemaError(f"probabilities sum to {sum(probs.values()):.3f}, not 1")
    return {k: float(probs[k]) for k in ROUTES}


def _unit(v: Any, what: str) -> float:
    if not isinstance(v, (int, float)) or not 0.0 <= v <= 1.0:
        raise SchemaError(f"{what} out of range: {v!r}")
    return float(v)


def _finish(choice: Any, probs: dict[str, float], api_conf: Any, takeover: float) -> dict:
    if choice not in ROUTES:
        raise SchemaError(f"choice outside the closed set: {choice!r}")
    derived = confidence_from_probs(probs)
    conf = _unit(api_conf, "confidence") if api_conf is not None else derived
    return {"choice": choice, "probs": probs, "confidence": conf,
            "confidence_source": "api" if api_conf is not None else "derived",
            "confidence_formula_gap": None if api_conf is None else round(abs(conf - derived), 4),
            "takeover": takeover}


# --------------------------------------------------------------------------- wire formats
def jev_request(request: dict, model: str, order: str = "original") -> dict:
    return {
        "state": build_state(request),
        "model": model,
        "questions": {
            "route": {"type": "choice", "instructions": ROUTE_INSTRUCTIONS,
                      "criteria": {r: ROUTE_CRITERIA[r] for r in ordered_routes(order)}},
            "account_takeover": {"type": "noul", "instructions": TAKEOVER_INSTRUCTIONS, "criteria": TAKEOVER_CRITERIA},
        },
    }


def parse_jev(body: dict) -> dict:
    try:
        route, ato = body["answers"]["route"], body["answers"]["account_takeover"]
        if route.get("type") != "choice" or ato.get("type") != "noul":
            raise SchemaError(f"unexpected answer types: {route.get('type')}, {ato.get('type')}")
        return _finish(route.get("choice"), _check_probs(dict(route["probabilities"])), route.get("confidence"),
                       _unit(ato["noul"], "takeover probability"))
    except SchemaError:
        raise
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise SchemaError(f"{type(exc).__name__}: {exc}") from exc


DECISIONS_INPUT_PREFIX = "Withdrawal request (program state as JSON):\n"


def decisions_request(request: dict, model: str, order: str = "original") -> dict:
    takeover = (f"{TAKEOVER_INSTRUCTIONS} True means: {TAKEOVER_CRITERIA['true']} "
                f"False means: {TAKEOVER_CRITERIA['false']}")
    return {
        "model": model,
        "input": DECISIONS_INPUT_PREFIX + json.dumps(build_state(request), ensure_ascii=False),
        "questions": [
            {"type": "choice", "name": "route", "instructions": ROUTE_INSTRUCTIONS,
             "choices": [{"value": r, "description": ROUTE_CRITERIA[r]} for r in ordered_routes(order)]},
            {"type": "predicate", "name": "account_takeover", "instructions": takeover},
        ],
    }


def parse_decisions(body: dict) -> dict:
    try:
        answers = {a["name"]: a for a in body["answers"]}
        route, ato = answers["route"], answers["account_takeover"]
        for name, a in (("route", route), ("account_takeover", ato)):
            if a.get("type") == "refusal":
                raise Refusal(f"{name}: refusal")
        if route.get("type") != "choice" or ato.get("type") != "predicate":
            raise SchemaError(f"unexpected answer types: {route.get('type')}, {ato.get('type')}")
        probs: dict[str, float] = {}
        for p in route["probabilities"]:
            if p["value"] in probs:
                raise SchemaError(f"duplicate probability for {p['value']!r}")
            probs[p["value"]] = p["probability"]
        return _finish(route.get("choice"), _check_probs(probs), route.get("confidence"),
                       _unit(ato["probability"], "takeover probability"))
    except SchemaError:
        raise
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise SchemaError(f"{type(exc).__name__}: {exc}") from exc


# --------------------------------------------------------------------------- clients
def _price(env: str, default: float) -> float:
    try:
        return float(os.environ.get(env) or default)
    except ValueError:
        return default


def _num(v: Any) -> float | None:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _retry_after(resp: httpx.Response, attempt: int) -> float:
    v = resp.headers.get("retry-after")
    if v:
        try:
            return min(10.0, float(v))
        except ValueError:
            try:
                return min(10.0, max(0.0, email.utils.parsedate_to_datetime(v).timestamp() - time.time()))
            except (TypeError, ValueError):
                pass
    return min(10.0, 0.5 * 2**attempt) * (0.8 + 0.4 * random.random())


def _server_ms(headers: httpx.Headers) -> float | None:
    for name in ("openai-processing-ms", "x-processing-ms", "x-response-time"):
        v = _num(re.sub(r"[^0-9.]", "", headers.get(name, "")) or None)
        if v is not None:
            return v
    st = headers.get("server-timing")            # e.g.  total;dur=123.4
    m = re.search(r"dur=([0-9.]+)", st or "")
    return float(m.group(1)) if m else None


OPENROUTER_BASE = "https://openrouter.ai/api"


def resolve_route(key_env: str, base_env: str, direct_base: str) -> tuple[str | None, str]:
    """(api key, base url) for one provider.

    The provider's own key and base URL win when set. Otherwise, if OPENROUTER_API_KEY is set, the provider
    goes through OpenRouter with that key, so one key in .env covers all three.
    """
    own_key, own_base = os.environ.get(key_env), os.environ.get(base_env)
    shared = os.environ.get("OPENROUTER_API_KEY")
    if own_key:
        return own_key, (own_base or direct_base)
    if shared:
        return shared, (own_base or OPENROUTER_BASE)
    return None, (own_base or direct_base)


class Client:
    name = "?"
    label = "?"
    simulated = False

    def __init__(self, api_key: str, base_url: str, model: str, price_in: float, timeout_s: float = 30.0,
                 client: httpx.AsyncClient | None = None) -> None:
        self.api_key, self.base_url, self.model, self.price_in = api_key, base_url.rstrip("/"), model, price_in
        self.timeout_s = timeout_s
        self._http = client or httpx.AsyncClient(timeout=timeout_s, limits=httpx.Limits(max_keepalive_connections=16))

    # subclasses provide these
    url: str
    def build(self, request: dict, order: str) -> dict: raise NotImplementedError
    def parse(self, body: dict) -> dict: raise NotImplementedError

    async def aclose(self) -> None:
        await self._http.aclose()

    async def ask(self, case: dict, order: str = "original", phase: str = "measure") -> Answer:
        a = Answer(provider=self.name, case_id=case["id"], order=order, phase=phase,
                   started_at=datetime.now(timezone.utc).isoformat(), simulated=self.simulated)
        payload = self.build(case["request"], order)
        t_start = time.perf_counter()
        resp: httpx.Response | None = None
        for attempt in range(MAX_ATTEMPTS):
            a.attempts = attempt + 1
            t0 = time.perf_counter()
            try:
                resp = await self._http.post(self.url, json=payload,
                                             headers={"Authorization": f"Bearer {self.api_key}"})
            except httpx.TimeoutException as exc:
                a.latency_ms = (time.perf_counter() - t0) * 1000
                a.error_kind, a.error = "timeout", f"timeout after {self.timeout_s:g}s ({type(exc).__name__})"
                resp = None
            except httpx.TransportError as exc:
                a.latency_ms = (time.perf_counter() - t0) * 1000
                a.error_kind, a.error = "network", f"{type(exc).__name__}: {exc}"
                resp = None
            else:
                a.latency_ms = (time.perf_counter() - t0) * 1000
                if resp.status_code not in RETRY_STATUS:
                    break
            if attempt + 1 < MAX_ATTEMPTS:
                await asyncio.sleep(_retry_after(resp, attempt) if resp is not None else 0.5 * 2**attempt)
        a.total_ms = (time.perf_counter() - t_start) * 1000
        if resp is None:
            return a
        a.status = resp.status_code
        a.headers = {k: v for k, v in resp.headers.items() if KEEP_HEADERS.search(k)}
        a.server_ms = _server_ms(resp.headers)
        try:
            body = resp.json()
        except ValueError:
            body = resp.text[:2000]
        a.raw = body
        if resp.status_code >= 400:
            a.error_kind, a.error = "http", f"HTTP {resp.status_code}: {str(body)[:300]}"
            return a
        a.error_kind = a.error = None
        u = (body.get("usage") or {}) if isinstance(body, dict) else {}
        a.input_tokens, a.output_tokens = int(u.get("input_tokens") or 0), int(u.get("output_tokens") or 0)
        a.cost_usd = a.input_tokens * self.price_in / 1e6       # output tokens are free on all three APIs
        a.provider_cost_usd = _num(body.get("cost", u.get("cost"))) if isinstance(body, dict) else None
        a.served_model = body.get("model") if isinstance(body, dict) else None
        a.response_id = (body.get("id") if isinstance(body, dict) else None) or a.headers.get("x-request-id")
        try:
            parsed = self.parse(body)
        except Refusal as exc:
            a.error_kind, a.error = "refusal", str(exc)
            return a
        except SchemaError as exc:
            a.error_kind, a.error = "schema", str(exc)
            return a
        for k, v in parsed.items():
            setattr(a, k, v)
        a.ok = True
        return a


class JevClient(Client):
    name, label = "jev", "TypeSafe Jev"
    wire = "systemone"

    @property
    def url(self) -> str:
        return f"{self.base_url}/v1/systemone"

    def build(self, request: dict, order: str) -> dict:
        return jev_request(request, self.model, order)

    def parse(self, body: dict) -> dict:
        return parse_jev(body)

    @classmethod
    def from_env(cls, timeout_s: float = 30.0) -> "JevClient":
        key, base = resolve_route("TYPESAFE_API_KEY", "TYPESAFE_BASE_URL", "https://api.typesafe.ai")
        if not key:
            raise RuntimeError("no key for Jev: set OPENROUTER_API_KEY (all three) or TYPESAFE_API_KEY, or use --mock")
        default_model = "typesafe/jev-1.13" if "openrouter.ai" in base else "jev-1.13"
        return cls(key, base, os.environ.get("JEV_MODEL") or default_model, _price("JEV_PRICE_IN_PER_MTOK", 0.042), timeout_s)


class DecisionsClient(Client):
    """OpenAI's decision model (gpt-6-luna). Two ways in:

      direct      OPENAI_BASE_URL=https://api.openai.com/v1  -> POST /v1/decisions, OpenAI's own format
                  (input text, choices list, predicate), model gpt-6-luna, your OpenAI key
      OpenRouter  OPENAI_BASE_URL=https://openrouter.ai/api  -> POST /v1/systemone, System One format (the SAME
                  body Jev and Microsoft get), model openai/gpt-6-luna-decisions, your OpenRouter key;
                  OpenRouter forwards it to OpenAI's Decisions API
    """
    name, label = "openai", "OpenAI Decisions"

    @property
    def via_openrouter(self) -> bool:
        return "openrouter.ai" in self.base_url

    @property
    def wire(self) -> str:
        return "systemone (OpenRouter)" if self.via_openrouter else "openai /v1/decisions"

    @property
    def url(self) -> str:
        return f"{self.base_url}/v1/systemone" if self.via_openrouter else f"{self.base_url}/decisions"

    def build(self, request: dict, order: str) -> dict:
        if self.via_openrouter:
            return jev_request(request, self.model, order)
        return decisions_request(request, self.model, order)

    def parse(self, body: dict) -> dict:
        return parse_jev(body) if self.via_openrouter else parse_decisions(body)

    @classmethod
    def from_env(cls, timeout_s: float = 30.0) -> "DecisionsClient":
        key, base = resolve_route("OPENAI_API_KEY", "OPENAI_BASE_URL", "https://api.openai.com/v1")
        if not key:
            raise RuntimeError("no key for OpenAI Decisions: set OPENROUTER_API_KEY (all three) or OPENAI_API_KEY, "
                               "or use --mock")
        base = base.rstrip("/")
        default_model = "openai/gpt-6-luna-decisions" if "openrouter.ai" in base else "gpt-6-luna"
        return cls(key, base, os.environ.get("DECISIONS_MODEL") or default_model,
                   _price("DECISIONS_PRICE_IN_PER_MTOK", 0.10), timeout_s)


class MicrosoftClient(JevClient):
    """Microsoft-Decision-1. Same System One request and response format as Jev.

    Two ways in:
      OpenRouter  MSD_BASE_URL=https://openrouter.ai/api   -> POST /v1/systemone, model microsoft/microsoft-decision-1
      Foundry     MSD_BASE_URL=https://<resource>.services.ai.azure.com
                                                          -> POST /providers/microsoft/v1/systemone, model = your
                                                             deployment name (Azure reserves "Microsoft-Decision-1")
    The Foundry path is not in Microsoft's public docs yet; it is the one the Foundry playground and LiteLLM use.
    Set MSD_PATH to override it if Microsoft publishes a different one.
    """
    name, label = "microsoft", "Microsoft Decision-1"

    def __init__(self, *args, path: str | None = None, **kw) -> None:
        super().__init__(*args, **kw)
        self.path = path or ("/providers/microsoft/v1/systemone" if "services.ai.azure.com" in self.base_url
                             else "/v1/systemone")

    @property
    def url(self) -> str:
        return f"{self.base_url}{self.path}"

    @classmethod
    def from_env(cls, timeout_s: float = 30.0) -> "MicrosoftClient":
        key, base = resolve_route("MSD_API_KEY", "MSD_BASE_URL", OPENROUTER_BASE)
        if not key:
            raise RuntimeError("no key for Microsoft Decision-1: set OPENROUTER_API_KEY (all three) or MSD_API_KEY "
                               "(OpenRouter or Foundry key), or use --mock")
        base = base.split("?")[0].rstrip("/")
        default_model = "microsoft/microsoft-decision-1" if "openrouter.ai" in base else "microsoft-decision-1"
        return cls(key, base, os.environ.get("MSD_MODEL") or default_model,
                   _price("MSD_PRICE_IN_PER_MTOK", 0.042), timeout_s, path=os.environ.get("MSD_PATH") or None)


# --------------------------------------------------------------------------- mocks
class _MockTransport:
    """Builds a provider-shaped response from the case label plus seeded noise.

    MOCK NUMBERS ARE NOT EVIDENCE. They exist so the whole pipeline (wire format, real parsers,
    metrics, reports) can be tested without keys. Accuracy, latency and calibration in a mock run
    are set by the parameters below. Mocks are order-invariant by construction.
    """

    def __init__(self, provider: str, base_ms: float, sharp: float) -> None:
        self.provider, self.base_ms, self.sharp = provider, base_ms, sharp

    def _rng(self, case_id: str, salt: str) -> random.Random:
        return random.Random(int(hashlib.sha256(f"{self.provider}:{salt}:{case_id}".encode()).hexdigest()[:12], 16))

    def probs(self, case: dict) -> tuple[dict[str, float], float]:
        rng = self._rng(case["id"], "p")
        logits = {r: rng.gauss(0, 0.9) for r in ROUTES}
        logits[case["expected_route"]] += 2.2 if rng.random() < 0.88 else -1.0
        m = max(logits.values())
        ex = {k: math.exp((v - m) * self.sharp) for k, v in logits.items()}
        z = sum(ex.values())
        p = {k: round(ex[k] / z, 4) for k in ROUTES}
        p["approve"] = round(1 - p["step_up_verification"] - p["manual_review"], 4)
        t = case.get("takeover")
        ato = min(0.99, max(0.01, (0.8 if t else 0.12) + rng.gauss(0, 0.12)))
        return p, round(ato, 4)

    def latency_ms(self, case: dict, phase: str) -> float:
        rng = self._rng(case["id"], f"lat:{phase}:{random.random()}")
        return max(40.0, rng.lognormvariate(math.log(self.base_ms), 0.35))


class MockJevClient(JevClient):
    simulated = True

    def __init__(self) -> None:
        self.model, self.price_in, self._mock = "mock-jev", 0.042, _MockTransport("jev", 200, 1.0)

    async def aclose(self) -> None: ...

    async def ask(self, case: dict, order: str = "original", phase: str = "measure") -> Answer:
        p, ato = self._mock.probs(case)
        payload = self.build(case["request"], order)
        tokens = max(1, round(len(json.dumps(payload)) / 3.8))
        body = {"id": f"mock-{case['id']}", "model": self.model, "usage": {"input_tokens": tokens, "output_tokens": 0},
                "answers": {"route": {"type": "choice", "choice": max(p, key=p.get),
                                      "probabilities": {r: p[r] for r in ordered_routes(order)},
                                      "confidence": round(confidence_from_probs(p), 4)},
                            "account_takeover": {"type": "noul", "noul": ato}}}
        return _mock_answer(self, case, order, phase, body)


class MockDecisionsClient(DecisionsClient):
    simulated = True

    def __init__(self) -> None:
        self.model, self.price_in, self._mock = "mock-gpt-6-luna", 0.10, _MockTransport("openai", 260, 1.3)
        self.base_url = "https://api.openai.com/v1"          # mock speaks OpenAI's direct format

    async def aclose(self) -> None: ...

    async def ask(self, case: dict, order: str = "original", phase: str = "measure") -> Answer:
        p, ato = self._mock.probs(case)
        payload = self.build(case["request"], order)
        tokens = max(1, round(len(json.dumps(payload)) / 3.8))
        body = {"id": f"mock-{case['id']}", "model": self.model, "usage": {"input_tokens": tokens, "output_tokens": 0},
                "answers": [{"type": "choice", "name": "route", "choice": max(p, key=p.get),
                             "probabilities": [{"value": r, "probability": p[r]} for r in ordered_routes(order)],
                             "confidence": round(confidence_from_probs(p), 4)},
                            {"type": "predicate", "name": "account_takeover", "probability": ato}]}
        return _mock_answer(self, case, order, phase, body)


def _mock_answer(c: Client, case: dict, order: str, phase: str, body: dict) -> Answer:
    a = Answer(provider=c.name, case_id=case["id"], order=order, phase=phase, simulated=True,
               started_at=datetime.now(timezone.utc).isoformat(), status=200, attempts=1, raw=body)
    a.latency_ms = a.total_ms = c._mock.latency_ms(case, phase)
    a.input_tokens = body["usage"]["input_tokens"]
    a.cost_usd = a.input_tokens * c.price_in / 1e6
    a.served_model, a.response_id = body["model"], body["id"]
    try:
        for k, v in c.parse(body).items():
            setattr(a, k, v)
        a.ok = True
    except SchemaError as exc:
        a.error_kind, a.error = "schema", str(exc)
    return a


class MockMicrosoftClient(MicrosoftClient):
    simulated = True

    def __init__(self) -> None:
        self.model, self.price_in, self._mock = "mock-microsoft-decision-1", 0.042, _MockTransport("microsoft", 190, 1.1)
        self.path = "/v1/systemone"

    async def aclose(self) -> None: ...

    async def ask(self, case: dict, order: str = "original", phase: str = "measure") -> Answer:
        return await MockJevClient.ask(self, case, order, phase)      # same System One wire format


PROVIDERS = {"jev": (JevClient, MockJevClient), "openai": (DecisionsClient, MockDecisionsClient),
             "microsoft": (MicrosoftClient, MockMicrosoftClient)}
PROVIDER_ORDER = list(PROVIDERS)
LABELS = {"jev": "TypeSafe Jev", "openai": "OpenAI Decisions", "microsoft": "Microsoft Decision-1"}
SHORT_LABELS = {"jev": "Jev", "openai": "OpenAI", "microsoft": "Microsoft"}


def make_client(name: str, mock: bool = False, timeout_s: float = 30.0) -> Client:
    if name not in PROVIDERS:
        raise ValueError(f"unknown provider {name!r}; choose from {', '.join(PROVIDERS)}")
    live, fake = PROVIDERS[name]
    return fake() if mock else live.from_env(timeout_s)
