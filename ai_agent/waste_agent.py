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

from simulator.waste_stream import ComplianceStatus, WasteCategory, WasteEvent


class WasteDecisionType(Enum):
    """Escalating actions the waste agent can recommend."""

    MONITOR = "monitor"  # nothing required
    INSPECT = "inspect"  # sample/verify at next collection
    TREAT = "treat"  # route to licensed treatment/recovery
    SEGREGATE = "segregate"  # fix the stream at source before disposal
    ESCALATE = "escalate"  # regulatory exposure — notify EHS


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

        # Compliance carries the most weight — it is a legal exposure, not a preference.
        if event.compliance_status is ComplianceStatus.NON_COMPLIANT:
            risk += 40.0
            factors.append("Non-compliant consignment")
        elif event.compliance_status is ComplianceStatus.ADVISORY:
            risk += 15.0
            factors.append("Compliance advisory raised")

        risk += event.severity * 0.40
        if event.category is WasteCategory.HAZARDOUS:
            risk += 15.0
            factors.append("Hazardous classification")
        if event.contamination_pct > 60.0:
            factors.append(f"Contamination {event.contamination_pct:.0f}%")
        for anomaly in event.anomalies:
            risk += 12.0
            factors.append(anomaly)

        risk = min(100.0, risk)

        if risk >= self.THRESHOLDS["escalate"]:
            dtype, priority = WasteDecisionType.ESCALATE, "critical"
            action = "Hold consignment and notify EHS — regulatory reporting exposure."
        elif risk >= self.THRESHOLDS["segregate"]:
            dtype, priority = WasteDecisionType.SEGREGATE, "high"
            action = "Segregate at source before disposal, then re-classify."
        elif risk >= self.THRESHOLDS["treat"]:
            dtype, priority = WasteDecisionType.TREAT, "medium"
            action = "Route to licensed treatment / recovery."
        elif risk >= self.THRESHOLDS["inspect"]:
            dtype, priority = WasteDecisionType.INSPECT, "low"
            action = "Sample and verify composition at next collection."
        else:
            dtype, priority = WasteDecisionType.MONITOR, "low"
            action = "No action required — continue monitoring."

        rules_txt = ", ".join(event.triggered_rules) if event.triggered_rules else "none"
        trail = [
            (
                f"Detected {event.weight_kg:.0f} kg {event.category.value.replace('_', ' ')} "
                f"waste from {event.source_name} ({event.source_id}) — contamination "
                f"{event.contamination_pct:.0f}%, moisture {event.moisture_pct:.0f}%, "
                f"classified with {event.classification_confidence:.0f}% confidence."
            )
        ]
        if factors:
            trail.append("Flagged: " + "; ".join(factors) + f". Rules fired: {rules_txt}.")
        else:
            trail.append("No compliance rules triggered; composition within baseline.")
        trail.append(f"Risk score {risk:.0f}/100 → {dtype.value.upper()}.")
        trail.append(
            f"4R recommendation: {event.recommended_action.value.upper()} — "
            f"{event.action_rationale} (≈{event.diverted_kg:.0f} kg diverted from landfill)."
        )

        reasoning = (
            f"{event.category.value.replace('_', ' ').title()} consignment scored "
            f"{risk:.0f}/100"
            + (f" on: {'; '.join(factors)}." if factors else " with no risk factors.")
        )

        return WasteDecision(
            decision_type=dtype,
            confidence=min(96.0, 58.0 + risk * 0.38),
            description=f"{event.source_id} ({event.source_name}) — {event.category.value}",
            recommended_action=action,
            reasoning=reasoning,
            priority=priority,
            reasoning_trail=trail,
            detected_factors=factors,
            risk_score=risk,
        )
