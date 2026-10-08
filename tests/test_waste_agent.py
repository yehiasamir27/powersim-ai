"""Tests for the waste agent's decision logic and waste business-impact accrual."""

from datetime import datetime

import pytest

from ai_agent.waste_agent import WasteAgent, WasteDecisionType
from simulator.business_impact import BusinessImpactModel, ImpactAssumptions
from simulator.waste_stream import (
    ComplianceStatus,
    RecoveryAction,
    WasteCategory,
    WasteEvent,
)


def _event(**overrides) -> WasteEvent:
    base = {
        "event_id": "e1",
        "timestamp": datetime.now(),
        "tick": 1,
        "source_id": "WM1",
        "source_name": "Motor Workshop",
        "asset_id": "M1",
        "weight_kg": 120.0,
        "volume_m3": 0.4,
        "composition": {
            "metal": 0.6,
            "plastic": 0.2,
            "organic": 0.05,
            "chemical": 0.05,
            "inert": 0.1,
        },
        "contamination_pct": 12.0,
        "moisture_pct": 10.0,
        "category": WasteCategory.RECYCLABLE,
        "classification_confidence": 88.0,
        "severity": 10.0,
        "anomalies": [],
        "compliance_status": ComplianceStatus.COMPLIANT,
        "triggered_rules": [],
        "recommended_action": RecoveryAction.RECYCLE,
        "action_rationale": "Clean recyclable material. Send it to recycling.",
        "diverted_kg": 102.0,
    }
    base.update(overrides)
    return WasteEvent(**base)


@pytest.fixture
def agent() -> WasteAgent:
    return WasteAgent()


def test_clean_compliant_event_is_monitored(agent):
    decision = agent.evaluate(_event())
    assert decision.decision_type is WasteDecisionType.MONITOR
    assert decision.priority == "low"
    assert decision.reasoning_trail  # trail always present


def test_hazardous_non_compliant_event_escalates(agent):
    decision = agent.evaluate(
        _event(
            category=WasteCategory.HAZARDOUS,
            compliance_status=ComplianceStatus.NON_COMPLIANT,
            triggered_rules=["H-01"],
            severity=80.0,
            contamination_pct=65.0,
            recommended_action=RecoveryAction.RECOVER,
        )
    )
    assert decision.decision_type is WasteDecisionType.ESCALATE
    assert decision.priority == "critical"
    assert any("breaks a waste rule" in f for f in decision.detected_factors)


def test_advisory_event_lands_between_monitor_and_escalate(agent):
    decision = agent.evaluate(
        _event(compliance_status=ComplianceStatus.ADVISORY, triggered_rules=["C-02"], severity=45.0)
    )
    assert decision.decision_type in (
        WasteDecisionType.INSPECT,
        WasteDecisionType.TREAT,
        WasteDecisionType.SEGREGATE,
    )


def test_anomalies_raise_risk(agent):
    calm = agent.evaluate(_event())
    noisy = agent.evaluate(_event(anomalies=["Volume spike: 400 kg vs 100 kg rolling mean"]))
    assert noisy.risk_score > calm.risk_score


def test_trail_is_legible_and_mentions_4r(agent):
    decision = agent.evaluate(_event())
    joined = " ".join(decision.reasoning_trail)
    assert "Found" in joined and "kg" in joined
    assert "Risk" in joined and "of 100" in joined
    assert "RECYCLE" in joined  # 4R recommendation surfaced
    assert "kept out of landfill" in joined


def test_decision_serialises_like_maintenance_decision(agent):
    d = agent.evaluate(_event()).to_dict()
    for key in (
        "decision_type",
        "confidence",
        "priority",
        "source",
        "reasoning_trail",
        "detected_factors",
    ):
        assert key in d


# -- business-impact accrual -------------------------------------------------


@pytest.fixture
def impact() -> BusinessImpactModel:
    return BusinessImpactModel(
        assumptions=ImpactAssumptions(
            disposal_cost_per_tonne=100.0,
            co2e_avoided_per_tonne_diverted_kg=400.0,
            compliance_penalty_avoided_usd=1_000.0,
        ),
        simulated_hours_per_tick=0.25,
    )


def test_waste_event_accrues_diversion_and_value(impact):
    impact.on_waste_event(_event(weight_kg=1000.0, diverted_kg=850.0))
    snap = impact.snapshot()
    assert snap["waste_events"] == 1
    assert snap["waste_generated_kg"] == 1000.0
    assert snap["waste_diverted_kg"] == 850.0
    assert snap["waste_diversion_rate_pct"] == pytest.approx(85.0, abs=0.1)
    # 0.85 t x $100/t
    assert snap["disposal_cost_avoided_usd"] == pytest.approx(85.0, abs=0.5)
    # 0.85 t x 400 kg CO2e/t
    assert snap["waste_co2e_avoided_kg"] == pytest.approx(340.0, abs=1.0)


def test_non_compliant_event_counts_as_incident_caught(impact):
    impact.on_waste_event(_event(compliance_status=ComplianceStatus.NON_COMPLIANT))
    snap = impact.snapshot()
    assert snap["compliance_incidents_caught"] == 1
    assert snap["compliance_value_usd"] == pytest.approx(1_000.0)


def test_compliant_event_is_not_an_incident(impact):
    impact.on_waste_event(_event())
    assert impact.snapshot()["compliance_incidents_caught"] == 0


def test_hazardous_events_are_counted(impact):
    impact.on_waste_event(_event(category=WasteCategory.HAZARDOUS))
    assert impact.snapshot()["hazardous_events"] == 1


def test_value_protected_includes_waste_streams(impact):
    impact.on_waste_event(
        _event(
            weight_kg=1000.0, diverted_kg=850.0, compliance_status=ComplianceStatus.NON_COMPLIANT
        )
    )
    snap = impact.snapshot()
    # 85 disposal + 1000 compliance, no downtime yet
    assert snap["value_protected_usd"] == pytest.approx(1085.0, abs=1.0)


def test_sustainability_scorecard_is_auditable(impact):
    impact.on_waste_event(_event(weight_kg=1000.0, diverted_kg=500.0))
    card = impact.snapshot()["sustainability"]
    assert 0 <= card["score"] <= 100
    assert set(card["weights"]) == {"reliability", "energy", "waste_diversion", "compliance"}
    assert pytest.approx(sum(card["weights"].values())) == 1.0
    assert card["subscores"]["waste_diversion"] == pytest.approx(50.0, abs=0.1)
