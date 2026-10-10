"""Synthetic withdrawal cases with analyst labels.

Every case has already passed hard eligibility checks, so every case is a real question for the models.

Labels per case:
    expected_route   what a correct model should answer (the question every API sees)
    expected_action  what the bank's policy should end up doing (differs only for large_familiar:
                     the route is approve, but the $5,000 auto-approve ceiling forces step-up)
    takeover         true / false, or null where the label is genuinely ambiguous (money mules can be the owner)

Archetypes stress different abilities:
    routine, benign_notes                 plain approvals
    traveler_with_notice                  approval readable ONLY from the free-text notes
    traveler_no_notice, new_device_legit  genuine ambiguity -> step-up
    large_familiar                        familiar but large: route approve, policy ceiling -> step-up
    account_takeover, mule                classic fraud -> manual review
    ato_quiet                             takeover visible ONLY in the notes -> manual review

    python -m compare.dataset --n 500 --seed 505 --out data/cases.jsonl
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

# name, weight, expected_route, expected_action, takeover label
ARCHETYPES: list[tuple[str, int, str, str, bool | None]] = [
    ("routine", 40, "approve", "approve", False),
    ("benign_notes", 6, "approve", "approve", False),
    ("traveler_with_notice", 8, "approve", "approve", False),
    ("traveler_no_notice", 6, "step_up_verification", "step_up_verification", False),
    ("new_device_legit", 8, "step_up_verification", "step_up_verification", False),
    ("large_familiar", 5, "approve", "step_up_verification", False),
    ("account_takeover", 9, "manual_review", "manual_review", True),
    ("ato_quiet", 4, "manual_review", "manual_review", True),
    ("mule", 6, "manual_review", "manual_review", None),
]

BENIGN_NOTES = [
    "Customer asked about mortgage refinancing rates last week.",
    "Customer enrolled in paperless statements.",
    "Branch visit 2 weeks ago to update beneficiary; ID verified in person.",
    "Customer mentioned saving for a home renovation.",
]
TRAVEL_NOTES = [
    "Customer filed a travel notice: Portugal, 3 weeks.",
    "Travel notice on file: Mexico trip for a family wedding.",
    "Customer called to say they are on vacation in Japan until next month.",
    "Travel notice: business trip to Germany.",
]
ATO_NOTES = [
    "Phone number changed 2 hours before this request via online banking.",
    "Email changed yesterday; password reset completed from an unrecognised IP.",
    "Customer reported a possible SIM swap to their carrier this morning (unverified).",
    "New payee added 20 minutes ago; 2FA disabled on profile.",
]


def _base(rng: random.Random) -> dict:
    avg = round(rng.uniform(80, 900), 2)
    return {
        "request_id": "",
        "account_id": f"acct-{rng.randint(10_000, 99_999)}",
        "amount": round(avg * rng.uniform(0.4, 2.0), 2),
        "currency": "USD",
        "available_balance": round(rng.uniform(3_000, 40_000), 2),
        "daily_withdrawn_so_far": 0.0,
        "account_status": "active",
        "kyc_verified": True,
        "account_age_days": rng.randint(200, 4_000),
        "recent_activity": {
            "withdrawals_30d": rng.randint(3, 20),
            "avg_withdrawal_30d": avg,
            "max_withdrawal_90d": round(avg * rng.uniform(1.5, 3.0), 2),
            "inbound_transfers_24h": 0.0,
            "days_since_last_withdrawal": rng.randint(1, 10),
        },
        "device_familiarity": "known",
        "geo_pattern": "home_region",
        "geo_distance_km": round(rng.uniform(0, 25), 1),
        "failed_auth_attempts_24h": 0,
        "context_notes": [],
    }


def make(archetype: str, rng: random.Random) -> dict:
    r = _base(rng)
    ra = r["recent_activity"]
    if archetype == "benign_notes":
        r["context_notes"] = [rng.choice(BENIGN_NOTES)]
    elif archetype == "traveler_with_notice":
        r.update(geo_pattern="foreign", geo_distance_km=round(rng.uniform(3_000, 11_000), 1),
                 context_notes=[rng.choice(TRAVEL_NOTES)])
    elif archetype == "traveler_no_notice":
        r.update(geo_pattern="foreign", geo_distance_km=round(rng.uniform(3_000, 11_000), 1))
    elif archetype == "new_device_legit":
        r.update(device_familiarity=rng.choice(["recently_added", "never_seen"]))
        r["failed_auth_attempts_24h"] = rng.choice([0, 0, 1])
    elif archetype == "large_familiar":
        r["available_balance"] = round(rng.uniform(15_000, 60_000), 2)
        r["amount"] = round(rng.uniform(5_500, 9_000), 2)
        ra["avg_withdrawal_30d"] = round(r["amount"] * rng.uniform(0.5, 0.9), 2)
        ra["max_withdrawal_90d"] = round(r["amount"] * rng.uniform(1.0, 1.4), 2)
    elif archetype == "account_takeover":
        r.update(device_familiarity="never_seen", geo_pattern=rng.choice(["domestic_new", "foreign"]),
                 geo_distance_km=round(rng.uniform(400, 9_000), 1),
                 failed_auth_attempts_24h=rng.randint(1, 3),
                 context_notes=[rng.choice(ATO_NOTES)] if rng.random() < 0.6 else [])
        r["amount"] = round(min(r["available_balance"] * rng.uniform(0.85, 0.99), 9_500), 2)
    elif archetype == "ato_quiet":
        r.update(device_familiarity="recently_added", context_notes=rng.sample(ATO_NOTES, 2))
        r["amount"] = round(ra["avg_withdrawal_30d"] * rng.uniform(1.5, 3.0), 2)
    elif archetype == "mule":
        amt = round(rng.uniform(1_500, 6_000), 2)
        r.update(account_age_days=rng.randint(5, 60), amount=amt,
                 available_balance=round(amt * rng.uniform(1.0, 1.08), 2),
                 device_familiarity=rng.choice(["known", "recently_added"]))
        ra.update(withdrawals_30d=rng.randint(0, 2), avg_withdrawal_30d=round(rng.uniform(40, 150), 2),
                  max_withdrawal_90d=round(rng.uniform(100, 300), 2),
                  inbound_transfers_24h=round(amt * rng.uniform(0.9, 1.1), 2), days_since_last_withdrawal=None)
        if rng.random() < 0.5:
            r["context_notes"] = ["Multiple inbound transfers from unrelated senders in the last day."]
    return r


def generate(n: int = 500, seed: int = 505, prefix: str = "case") -> list[dict]:
    rng = random.Random(seed)
    total = sum(a[1] for a in ARCHETYPES)
    plan: list[tuple] = []
    for a in ARCHETYPES:
        plan += [a] * max(1, round(a[1] * n / total))
    plan = plan[:n]
    while len(plan) < n:
        plan.append(ARCHETYPES[0])
    rng.shuffle(plan)
    cases = []
    for i, (name, _, route, action, takeover) in enumerate(plan):
        req = make(name, rng)
        req["request_id"] = f"{prefix}-{i:04d}"
        cases.append({"id": req["request_id"], "archetype": name, "expected_route": route,
                      "expected_action": action, "takeover": takeover, "request": req})
    return cases


def load(path: str | Path) -> list[dict]:
    return [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate labelled withdrawal cases")
    ap.add_argument("--n", type=int, default=500)
    ap.add_argument("--seed", type=int, default=505)
    ap.add_argument("--prefix", default="case")
    ap.add_argument("--out", default="data/cases.jsonl")
    a = ap.parse_args()
    cases = generate(a.n, a.seed, a.prefix)
    Path(a.out).write_text("\n".join(json.dumps(c) for c in cases) + "\n", encoding="utf-8")
    print(f"wrote {len(cases)} cases -> {a.out}")


if __name__ == "__main__":
    main()
