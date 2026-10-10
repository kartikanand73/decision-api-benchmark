"""The one decision every API is asked to make, written once.

Both providers receive the same program state and the same rubric text. Only the wire format
differs, and each difference the APIs force on us is listed in the provider module.

The rubric is the same text (version 1.1) used in the Jev Decision Gateway experiments, so
results here can be read next to those.
"""

from __future__ import annotations

from typing import Any

RUBRIC_VERSION = "1.1"
ROUTES: tuple[str, ...] = ("approve", "step_up_verification", "manual_review")

ROUTE_INSTRUCTIONS = (
    "This withdrawal has already passed all hard eligibility checks (funds, limits, account status, KYC). "
    "Decide how it should be routed based on how consistent it is with the account owner's normal behaviour."
)

ROUTE_CRITERIA: dict[str, str] = {
    "approve": "Consistent with the owner's normal behaviour: familiar device and location, amount in line with "
    "history, no suspicious account changes. Travel that matches a travel notice on file counts as normal "
    "behaviour. Safe to release without friction.",
    "step_up_verification": "Plausibly the owner but with some unusual element (new device, travel with no "
    "matching travel notice, larger than usual amount). An extra verification challenge would resolve the doubt.",
    "manual_review": "Strong signs of account takeover, money-mule activity or fraud: e.g. new device plus new "
    "location plus recent credential/contact changes, or funds received and immediately drained. "
    "A human analyst should look before anything happens.",
}

TAKEOVER_INSTRUCTIONS = (
    "Do the signals suggest that someone other than the legitimate account owner is attempting this withdrawal?"
)
TAKEOVER_CRITERIA = {
    "true": "Likely account takeover or third-party control of the account.",
    "false": "Likely the legitimate owner.",
}


# Every way to list the three options. A = approve, S = step-up, M = manual review.
# "original" (A-S-M) and "reversed" (M-S-A) keep their names; the other four are named by their letters.
_LETTER = {"A": "approve", "S": "step_up_verification", "M": "manual_review"}
ORDERS: dict[str, str] = {"original": "ASM", "AMS": "AMS", "SAM": "SAM", "SMA": "SMA", "MAS": "MAS", "reversed": "MSA"}
ORDER_SETS = {"original": ["original"], "both": ["original", "reversed"], "all": list(ORDERS)}


def order_label(order: str) -> str:
    code = "-".join(ORDERS[order])
    return f"{code} ({order})" if order in ("original", "reversed") else code


def ordered_routes(order: str) -> list[str]:
    """The three routes in the listed order, e.g. 'original' -> approve, step-up, review."""
    if order not in ORDERS:
        raise ValueError(f"order must be one of {', '.join(ORDERS)}, not {order!r}")
    return [_LETTER[c] for c in ORDERS[order]]


def build_state(request: dict[str, Any]) -> dict[str, Any]:
    """Program state sent to both models. IDs are dropped: they carry no signal."""
    s = {k: v for k, v in request.items() if k not in ("request_id", "account_id", "currency")}
    bal, amt = request["available_balance"], request["amount"]
    avg = request["recent_activity"]["avg_withdrawal_30d"]
    s["amount_to_balance_ratio"] = round(amt / bal, 3) if bal > 0 else None
    s["amount_to_avg_withdrawal_ratio"] = round(amt / avg, 2) if avg > 0 else None
    return s


def confidence_from_probs(probs: dict[str, float]) -> float:
    """TypeSafe's documented confidence: (k * p_max - 1) / (k - 1). OpenAI's docs example matches it."""
    k = len(probs)
    return max(0.0, min(1.0, (k * max(probs.values()) - 1) / (k - 1)))
