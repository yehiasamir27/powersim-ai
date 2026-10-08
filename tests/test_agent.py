"""Tests for the AI agent's decision logic (rule engine, LLM disabled)."""

import pytest

from ai_agent.agent import AgentMode, AIAgent, DecisionType
from simulator.maintenance import MaintenanceManager, WorkOrderPriority, WorkOrderType


@pytest.fixture
def agent() -> AIAgent:
    # LLM disabled -> deterministic rule engine.
    return AIAgent(enabled=False)


def _asset_state(asset_id="M1", health=100.0, state="normal", failure=None):
    return {
        "asset_id": asset_id,
        "asset_type": "motor",
        "name": "Traction Motor",
        "health": health,
        "operating_state": state,
        "total_operating_hours": 100.0,
        "failure_mode": failure,
    }


def _telemetry(temp=62.0, vib=1.6, bearing=5.0, oil=4.5, rul=800.0):
    return {
        "temperature": temp,
        "vibration": vib,
        "voltage": 415.0,
        "current": 500.0,
        "bearing_wear": bearing,
        "oil_pressure": oil,
        "health_score": 100.0,
        "power_factor": 0.9,
        "anomaly_score": 0.0,
        "rul_hours": rul,
    }


async def test_healthy_asset_monitors(agent):
    decision = await agent.think(agent.sense(_asset_state(), _telemetry(), 1))
    assert decision.decision_type is DecisionType.MONITOR
    assert decision.requires_maintenance is False
    assert decision.reasoning_trail  # trail always populated


async def test_critical_asset_escalates(agent):
    state = _asset_state(health=15.0, state="critical", failure="bearing_wear")
    tel = _telemetry(temp=110.0, vib=8.0, bearing=80.0, oil=2.0, rul=20.0)
    decision = await agent.think(agent.sense(state, tel, 1))
    assert decision.decision_type in (DecisionType.REPAIR, DecisionType.EMERGENCY)
    assert decision.requires_maintenance is True
    assert decision.priority in ("high", "critical")
    assert decision.detected_factors  # named risk factors present


async def test_reasoning_trail_and_mode(agent):
    decision = await agent.think(agent.sense(_asset_state(), _telemetry(), 1))
    assert decision.source == AgentMode.LLM_DISABLED.value
    assert agent.last_mode == AgentMode.LLM_DISABLED.value
    assert len(decision.reasoning_trail) >= 2


async def test_act_creates_matching_work_order(agent):
    manager = MaintenanceManager()
    state = _asset_state(health=15.0, state="critical", failure="overload")
    tel = _telemetry(temp=115.0, vib=9.0, bearing=85.0, oil=1.5, rul=10.0)
    decision = await agent.think(agent.sense(state, tel, 1))
    action = agent.act(decision, "M1", manager)
    assert action is not None
    wo = manager.get_work_order(action["work_order_id"])
    assert wo.asset_id == "M1"
    assert wo.work_type in (WorkOrderType.CORRECTIVE, WorkOrderType.EMERGENCY)
    assert wo.priority in (WorkOrderPriority.HIGH, WorkOrderPriority.CRITICAL)


async def test_act_noop_when_monitoring(agent):
    manager = MaintenanceManager()
    decision = await agent.think(agent.sense(_asset_state(), _telemetry(), 1))
    assert agent.act(decision, "M1", manager) is None
    assert manager.get_queue() == []


def test_detect_factors_flags_bearing_and_rul(agent):
    state = _asset_state(health=40.0)
    tel = _telemetry(bearing=70.0, rul=24.0)
    factors = agent._detect_factors(agent.sense(state, tel, 1))
    joined = " ".join(factors).lower()
    assert "bearing" in joined
    assert "rul" in joined


def test_agent_status_reports_disabled(agent):
    status = agent.get_status()
    assert status["enabled"] is False
    assert status["model"]


async def test_run_cycle_structure(agent):
    manager = MaintenanceManager()
    result = await agent.run_cycle(_asset_state(), _telemetry(), 1, manager)
    assert set(result) == {"sense", "decision", "action"}
    assert result["decision"]["decision_type"] == "monitor"
