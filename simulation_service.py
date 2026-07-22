"""
Simulation service — the application core, decoupled from the API/transport layer.

Owns all mutable simulation state (digital twin, maintenance queue, agent,
business-impact model) and orchestrates the continuous sense -> think -> act loop.
FastAPI (``main.py``) is a thin transport shell over this service; nothing in here
imports FastAPI, so the core is unit-testable in isolation.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime
from typing import Any

from ai_agent.agent import AIAgent
from config import Settings
from integrations import SimulatedTelemetrySource, get_integration_catalog
from logging_config import get_logger
from simulator.business_impact import BusinessImpactModel, ImpactAssumptions
from simulator.maintenance import MaintenanceManager
from simulator.power_system import PowerSystem

logger = get_logger("powersim.service")


class SimulationService:
    """Holds and advances all simulation state behind a small, testable API."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._agent_events: deque[dict] = deque(maxlen=60)
        self.latest_telemetry: dict[str, dict] = {}
        self.latest_decisions: dict[str, dict] = {}
        self._build()

    def _build(self) -> None:
        s = self.settings
        self.power_system = PowerSystem(seed=s.simulation_seed)
        self.maintenance = MaintenanceManager()
        self.agent = AIAgent(
            ollama_url=s.ollama_url,
            model=s.ollama_model,
            timeout_seconds=s.ollama_timeout_seconds,
            enabled=s.ollama_enabled,
            llm_every_n_cycles=s.agent_llm_every_n_cycles,
        )
        self.impact = BusinessImpactModel(
            assumptions=ImpactAssumptions.from_env(),
            simulated_hours_per_tick=PowerSystem.TICK_DURATION_SECONDS / 3600.0,
        )
        self.source = SimulatedTelemetrySource(self.power_system)
        self.latest_telemetry = {}
        self.latest_decisions = {}
        self._agent_events.clear()

    # -- lifecycle --------------------------------------------------------

    def reset(self) -> None:
        """Rebuild all state from scratch (fresh seed)."""
        logger.info("Resetting simulation")
        self._build()

    # -- telemetry loop ---------------------------------------------------

    async def advance_telemetry(self) -> dict:
        """Advance one tick, update impact, and return the broadcast payload."""
        telemetry = await self.source.read()
        self.latest_telemetry = telemetry
        self.impact.on_tick(self.power_system.get_all_assets(), telemetry)
        return {
            "type": "tick",
            "tick_count": self.power_system.tick_count,
            "timestamp": datetime.now().isoformat(),
            "state": self.power_system.get_state_summary(),
            "telemetry": telemetry,
            "impact": self.impact.snapshot(),
            "queue_stats": self.maintenance.get_statistics(),
        }

    # -- agent loop (think -> act) ---------------------------------------

    async def run_agent_pass(self) -> dict:
        """Run the agent over the fleet, act idempotently, return a broadcast payload."""
        if not self.latest_telemetry:
            return {"type": "agent", "decisions": {}, "events": []}

        new_events: list[dict] = []
        for asset in self.power_system.get_all_assets():
            aid = asset.config.asset_id
            tel = self.latest_telemetry.get(aid)
            if not tel:
                continue

            sense = self.agent.sense(asset.to_dict(), tel, self.power_system.tick_count)
            decision = await self.agent.think(sense)
            decision_dict = decision.to_dict()
            previous = self.latest_decisions.get(aid, {})
            self.latest_decisions[aid] = decision_dict

            # Act: create a work order only if one isn't already open for the asset.
            if decision.requires_maintenance and not self._has_open_order(aid):
                action = self.agent.act(decision, aid, self.maintenance)
                event = self._make_event(asset, decision_dict, action)
                self._agent_events.appendleft(event)
                new_events.append(event)
            elif decision_dict["decision_type"] != previous.get("decision_type"):
                # State change worth surfacing on the live "why" feed.
                event = self._make_event(asset, decision_dict, None)
                self._agent_events.appendleft(event)
                new_events.append(event)

        return {
            "type": "agent",
            "timestamp": datetime.now().isoformat(),
            "decisions": self.latest_decisions,
            "events": new_events,
            "agent_status": self.agent.get_status(),
            "fleet_summary": self._fleet_summary(),
        }

    def _make_event(self, asset: Any, decision: dict, action: dict | None) -> dict:
        return {
            "timestamp": datetime.now().isoformat(),
            "tick": self.power_system.tick_count,
            "asset_id": asset.config.asset_id,
            "asset_name": asset.config.name,
            "decision_type": decision["decision_type"],
            "priority": decision["priority"],
            "source": decision["source"],
            "summary": decision["recommended_action"],
            "reasoning_trail": decision["reasoning_trail"],
            "work_order": action,
        }

    def _has_open_order(self, asset_id: str) -> bool:
        return bool(self.maintenance.get_pending_orders(asset_id)) or (
            self.maintenance.is_asset_under_maintenance(asset_id)
        )

    def _fleet_summary(self) -> str:
        decisions = self.latest_decisions
        if not decisions:
            return "Agent initialising — awaiting first telemetry."
        rank = {"emergency": 4, "repair": 3, "maintain": 2, "inspect": 1, "monitor": 0}
        worst = max(decisions.values(), key=lambda d: rank.get(d["decision_type"], 0))
        action_needed = [
            d for d in decisions.values() if d["decision_type"] != "monitor"
        ]
        if not action_needed:
            return (
                f"Fleet nominal — all {len(decisions)} assets within normal parameters. "
                "Agent monitoring continuously."
            )
        return (
            f"{len(action_needed)} of {len(decisions)} assets need attention; "
            f"highest priority: {worst['decision_type'].upper()} on "
            f"{worst['description']}."
        )

    # -- interventions (API-facing) --------------------------------------

    def inject_failure(self, asset_id: str, failure_type: str) -> dict:
        if asset_id not in self.power_system.assets:
            raise KeyError(asset_id)
        if not self.power_system.inject_failure(asset_id, failure_type):
            raise ValueError(f"Cannot inject {failure_type}")
        logger.info(
            "Failure injected", extra={"asset_id": asset_id, "failure_type": failure_type}
        )
        return {
            "success": True,
            "asset_id": asset_id,
            "failure_type": failure_type,
            "health": round(self.power_system.assets[asset_id].estimated_health, 1),
        }

    def perform_maintenance(self, asset_id: str) -> dict:
        asset = self.power_system.assets.get(asset_id)
        if asset is None:
            raise KeyError(asset_id)
        if self.maintenance.is_asset_under_maintenance(asset_id):
            raise ValueError("Asset already under maintenance")
        prior_state = asset.operating_state.value
        if not self.power_system.perform_maintenance(asset_id):
            raise ValueError("Maintenance failed")
        # Record simulated business impact of the intervention.
        self.impact.on_maintenance(prior_state)
        logger.info(
            "Maintenance performed",
            extra={"asset_id": asset_id, "prior_state": prior_state},
        )
        return {
            "success": True,
            "asset_id": asset_id,
            "health": round(asset.estimated_health, 1),
            "operating_state": asset.operating_state.value,
        }

    # -- read models ------------------------------------------------------

    def get_state(self) -> dict:
        return {
            "state": self.power_system.get_state_summary(),
            "telemetry": self.latest_telemetry,
            "queue": [wo.to_dict() for wo in self.maintenance.get_queue()],
            "queue_stats": self.maintenance.get_statistics(),
            "impact": self.impact.snapshot(),
            "agent_status": self.agent.get_status(),
        }

    def get_analysis(self) -> dict:
        return {
            "fleet_summary": self._fleet_summary(),
            "decisions": self.latest_decisions,
            "events": list(self._agent_events),
            "agent_status": self.agent.get_status(),
            "timestamp": datetime.now().isoformat(),
        }

    def get_impact(self) -> dict:
        return {
            "snapshot": self.impact.snapshot(),
            "methodology": self.impact.methodology(),
        }

    def update_impact_assumptions(self, updates: dict[str, float]) -> dict:
        for key, value in updates.items():
            if value is not None and hasattr(self.impact.assumptions, key):
                setattr(self.impact.assumptions, key, float(value))
        logger.info("Impact assumptions updated", extra={"updates": updates})
        return self.get_impact()

    @staticmethod
    def get_integrations() -> list[dict]:
        return get_integration_catalog()
