"""The bank's deterministic policy: the same thresholds as the Jev Decision Gateway.

Applied identically to every provider's probabilities. This is where calibration stops being
abstract: a model that is right on the top route but overconfident or underconfident will still
produce different ACTIONS under the same thresholds.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

POLICY_VERSION = "withdrawal-policy/1.0.0"


@dataclass(frozen=True)
class Thresholds:
    approve_min_probability: float = 0.80
    approve_min_confidence: float = 0.50
    manual_review_min_probability: float = 0.30
    account_takeover_max: float = 0.50
    auto_approve_ceiling_usd: float = 5_000.0

    def as_dict(self) -> dict:
        return asdict(self)


def decide(amount: float, probs: dict[str, float] | None, confidence: float | None, takeover: float | None,
           t: Thresholds = Thresholds()) -> tuple[str, list[str]]:
    """Returns (action, reasons). A missing or invalid answer fails safe to manual review."""
    if probs is None or confidence is None or takeover is None:
        return "manual_review", ["NO_VALID_ANSWER_FAIL_SAFE"]
    reasons = []
    if probs["manual_review"] >= t.manual_review_min_probability:
        reasons.append("MANUAL_REVIEW_RISK")
    if takeover >= t.account_takeover_max:
        reasons.append("TAKEOVER_RISK")
    if reasons:
        return "manual_review", reasons
    if probs["approve"] > t.approve_min_probability:
        if confidence < t.approve_min_confidence:
            reasons.append("LOW_CONFIDENCE")
        if amount > t.auto_approve_ceiling_usd:
            reasons.append("ABOVE_AUTO_APPROVE_CEILING")
        if not reasons:
            return "approve", ["APPROVE"]
        return "step_up_verification", reasons
    return "step_up_verification", ["NOT_CLEARLY_APPROVABLE"]
