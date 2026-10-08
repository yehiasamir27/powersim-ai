"""
Waste-management reasoning agent (Decision & Control layer).

Deliberately mirrors the predictive-maintenance agent: the same risk-scored
monitor → inspect → act progression, the same decision shape, and the same
transparent ``reasoning_trail`` — so a waste event is exactly as legible in the
UI's "why" feed as a maintenance event, and the dashboard renders both with one
code path.

Reasoning here is deterministic and rule-based (matching the expert-system
compliance layer). It is not an LLM or trained model; see
``docs/TECHNICAL_OVERVIEW.md`` for the production upgrade path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from simulator.waste_stream import (
    COMPLIANCE_RULES,
    ComplianceStatus,
    RecoveryAction,
    WasteCategory,
    WasteEvent,
)


class WasteDecisionType(Enum):
    """Escalating actions the waste agent can recommend."""

    MONITOR = "monitor"  # nothing required
    INSPECT = "inspect"  # sample/verify at next collection
    TREAT = "treat"  # route to licensed treatment/recovery
    SEGREGATE = "segregate"  # fix the stream at source before disposal
    ESCALATE = "escalate"  # regulatory exposure — notify EHS


#: What each 4R plan means as a plain instruction.
PLAN_VERBS: dict[RecoveryAction, str] = {
    RecoveryAction.REDUCE: "fix the process that made it",
    RecoveryAction.REUSE: "reuse it",
    RecoveryAction.RECYCLE: "send it to recycling",
    RecoveryAction.RECOVER: "send it to licensed treatment",
    RecoveryAction.DISPOSE: "dispose of it safely",
}

#: Plain English words shown to people for each decision.
DECISION_LABELS: dict[WasteDecisionType, str] = {
    WasteDecisionType.MONITOR: "WATCH",
    WasteDecisionType.INSPECT: "CHECK",
    WasteDecisionType.TREAT: "REVIEW",
    WasteDecisionType.SEGREGATE: "SEPARATE",
    WasteDecisionType.ESCALATE: "ALERT",
}


@dataclass
class WasteDecision:
    """Decision output, shaped like ``AgentDecision`` for UI parity."""

    decision_type: WasteDecisionType
    confidence: float
    description: str
    recommended_action: str
    reasoning: str
    priority: str = "low"
    source: str = "rules"
    reasoning_trail: list[str] = field(default_factory=list)
    detected_factors: list[str] = field(default_factory=list)
    risk_score: float = 0.0

    def to_dict(self) -> dict:
        return {
            "decision_type": self.decision_type.value,
            "confidence": round(self.confidence, 1),
            "description": self.description,
            "recommended_action": self.recommended_action,
            "reasoning": self.reasoning,
            "priority": self.priority,
            "source": self.source,
            "reasoning_trail": self.reasoning_trail,
            "detected_factors": self.detected_factors,
            "risk_score": round(self.risk_score, 1),
        }


class WasteAgent:
    """Scores waste events and recommends a control action with a why-trail."""

    THRESHOLDS = {
        "escalate": 70.0,
        "segregate": 50.0,
        "treat": 32.0,
        "inspect": 16.0,
    }

    def evaluate(self, event: WasteEvent) -> WasteDecision:
        """Score one waste event and produce an explainable decision."""
        factors: list[str] = []
        risk = 0.0

        # Breaking a waste rule carries the most weight: it is a legal risk, not a preference.
        if event.compliance_status is ComplianceStatus.NON_COMPLIANT:
            risk += 40.0
            factors.append("breaks a waste rule")
        elif event.compliance_status is ComplianceStatus.ADVISORY:
            risk += 15.0
            factors.append("rule warning")

        risk += event.severity * 0.40
        if event.category is WasteCategory.HAZARDOUS:
            risk += 15.0
            factors.append("hazardous material")
        if event.contamination_pct > 60.0:
            factors.append(f"contamination at {event.contamination_pct:.0f}%")
        for anomaly in event.anomalies:
            risk += 12.0
            factors.append(anomaly[0].lower() + anomaly[1:])

        risk = min(100.0, risk)

        if risk >= self.THRESHOLDS["escalate"]:
            dtype, priority = WasteDecisionType.ESCALATE, "critical"
            action = "Hold the load and tell the safety team."
        elif risk >= self.THRESHOLDS["segregate"]:
            dtype, priority = WasteDecisionType.SEGREGATE, "high"
            action = "Separate it at the source, then check it again."
        elif risk >= self.THRESHOLDS["treat"]:
            dtype, priority = WasteDecisionType.TREAT, "medium"
            # Follow the 4R plan, after a quick review, so the two never disagree.
            action = f"Review the load, then {PLAN_VERBS[event.recommended_action]}."
        elif risk >= self.THRESHOLDS["inspect"]:
            dtype, priority = WasteDecisionType.INSPECT, "low"
            action = "Check a sample at the next pickup."
        else:
            dtype, priority = WasteDecisionType.MONITOR, "low"
            action = "No action needed."

        category = event.category.value.replace("_", " ")
        trail = [
            (
                f"Found {event.weight_kg:.0f} kg of {category} waste at {event.source_name}. "
                f"Contamination {event.contamination_pct:.0f}%, moisture "
                f"{event.moisture_pct:.0f}%, confidence {event.classification_confidence:.0f}%."
            )
        ]
        if factors:
            rules = [
                COMPLIANCE_RULES[c].description.lower()
                for c in event.triggered_rules
                if c in COMPLIANCE_RULES
            ]
            line = "Warning signs: " + "; ".join(factors) + "."
            if rules:
                line += " Rule: " + "; ".join(rules) + "."
            trail.append(line)
        else:
            trail.append("No rule broken and the mix looks normal.")
        trail.append(f"Risk {risk:.0f} of 100, so the decision is {DECISION_LABELS[dtype]}.")
        trail.append(
            f"Best option: {event.recommended_action.value.upper()}. {event.action_rationale} "
            f"About {event.diverted_kg:.0f} kg kept out of landfill."
        )

        reasoning = f"{category.capitalize()} waste scored {risk:.0f} of 100" + (
            f" because of: {'; '.join(factors)}." if factors else " with no warning signs."
        )

        return WasteDecision(
            decision_type=dtype,
            confidence=min(96.0, 58.0 + risk * 0.38),
            description=f"{event.source_id} {event.source_name} ({category})",
            recommended_action=action,
            reasoning=reasoning,
            priority=priority,
            reasoning_trail=trail,
            detected_factors=factors,
            risk_score=risk,
        )
