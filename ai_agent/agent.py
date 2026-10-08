"""
Agentic AI for predictive-maintenance diagnostics (sense -> think -> act).

The agent observes asset telemetry, reasons about condition and risk, and emits a
decision with a transparent **reasoning trail** (the "why" behind every
recommendation — a named buyer requirement, see docs/MARKET_RESEARCH.md). Reasoning
uses a local LLM via Ollama when available and a deterministic rule engine
otherwise; the active mode is always reported honestly rather than degrading
silently.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

import httpx

from logging_config import get_logger

logger = get_logger("powersim.agent")


class DecisionType(Enum):
    """Types of decisions the agent can make."""

    MONITOR = "monitor"  # continue monitoring, no action
    INSPECT = "inspect"  # schedule inspection
    MAINTAIN = "maintain"  # schedule preventive maintenance
    REPAIR = "repair"  # schedule corrective maintenance
    EMERGENCY = "emergency"  # immediate response required


class AgentMode(str, Enum):
    """Which reasoning path produced the most recent decision (honest status)."""

    LLM = "llm"
    RULES = "rules"
    LLM_UNAVAILABLE = "llm_unavailable"  # rules used: Ollama unreachable
    LLM_ERROR = "llm_error"  # rules used: Ollama call failed
    LLM_DISABLED = "llm_disabled"  # rules used: LLM disabled by config


@dataclass
class SenseData:
    """Snapshot of an asset assembled during the sense phase."""

    asset_id: str
    asset_type: str
    asset_name: str
    health: float
    operating_state: str
    telemetry: dict[str, float]
    failure_mode: str | None
    total_operating_hours: float
    tick_count: int

    def to_dict(self) -> dict:
        return {
            "asset_id": self.asset_id,
            "asset_type": self.asset_type,
            "asset_name": self.asset_name,
            "health": self.health,
            "operating_state": self.operating_state,
            "telemetry": self.telemetry,
            "failure_mode": self.failure_mode,
            "total_operating_hours": self.total_operating_hours,
            "tick_count": self.tick_count,
        }


@dataclass
class AgentDecision:
    """Decision output from the think phase, with a transparent reasoning trail."""

    decision_type: DecisionType
    confidence: float
    description: str
    recommended_action: str
    reasoning: str
    strategic_recommendation: str
    requires_maintenance: bool = False
    priority: str = "medium"
    source: str = AgentMode.RULES.value  # "llm" | "rules"
    reasoning_trail: list[str] = field(default_factory=list)
    detected_factors: list[str] = field(default_factory=list)
    rul_hours: float = 0.0

    def to_dict(self) -> dict:
        return {
            "decision_type": self.decision_type.value,
            "confidence": round(self.confidence, 1),
            "description": self.description,
            "recommended_action": self.recommended_action,
            "reasoning": self.reasoning,
            "strategic_recommendation": self.strategic_recommendation,
            "requires_maintenance": self.requires_maintenance,
            "priority": self.priority,
            "source": self.source,
            "reasoning_trail": self.reasoning_trail,
            "detected_factors": self.detected_factors,
            "rul_hours": round(self.rul_hours, 1),
        }


class AIAgent:
    """Predictive-maintenance agent with an LLM-or-rules think phase."""

    DIAGNOSTIC_PROMPT = """You are an expert predictive-maintenance AI agent for \
industrial power systems. Analyse the asset telemetry and return a diagnostic \
assessment.

ASSET:
- ID: {asset_id} | Type: {asset_type} ({asset_name})
- Estimated health: {health}% | State: {operating_state}
- Operating hours: {operating_hours:.1f} | Active fault: {failure_mode}

TELEMETRY:
- Temperature: {temperature} C
- Vibration: {vibration} mm/s RMS
- Voltage: {voltage} V | Current: {current} A
- Bearing wear: {bearing_wear}% | Oil pressure: {oil_pressure} bar
- Power factor: {power_factor} | Anomaly score: {anomaly_score}/100
- Estimated remaining useful life: {rul_hours} hours

Respond in JSON with EXACTLY these fields:
{{
  "decision_type": "monitor" | "inspect" | "maintain" | "repair" | "emergency",
  "confidence": 0-100,
  "description": "one-line condition summary",
  "recommended_action": "specific action to take",
  "reasoning": "concise chain of thought explaining the call",
  "strategic_recommendation": "long-term policy suggestion",
  "priority": "low" | "medium" | "high" | "critical"
}}
Be concise and actionable."""

    RULE_THRESHOLDS = {
        "critical_health": 20.0,
        "high_health": 35.0,
        "degraded_health": 55.0,
        "high_temperature": 95.0,
        "high_vibration": 5.0,
        "low_oil_pressure": 2.5,
        "high_bearing_wear": 55.0,
        "low_rul_hours": 72.0,
    }

    def __init__(
        self,
        ollama_url: str = "http://localhost:11434",
        model: str = "qwen2.5:7b",
        timeout_seconds: float = 30.0,
        enabled: bool = True,
        llm_every_n_cycles: int = 1,
    ) -> None:
        self.ollama_url = ollama_url.rstrip("/")
        self.model = model
        self.timeout_seconds = float(timeout_seconds)
        self.enabled = enabled
        self.llm_every_n_cycles = max(1, llm_every_n_cycles)
        self._llm_available: bool | None = None
        self._last_llm_check: datetime | None = None
        self._cycle_counts: dict[str, int] = {}
        self.last_mode: str = AgentMode.RULES.value

    # -- LLM availability -------------------------------------------------

    async def check_llm_availability(self) -> bool:
        """Return whether Ollama is reachable (cached for 60s)."""
        if not self.enabled:
            return False
        now = datetime.now()
        if (
            self._llm_available is not None
            and self._last_llm_check is not None
            and (now - self._last_llm_check).total_seconds() < 60
        ):
            return self._llm_available

        previous = self._llm_available
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.ollama_url}/api/tags")
            self._llm_available = response.status_code == 200
        except Exception as exc:  # network error, connection refused, etc.
            self._llm_available = False
            logger.debug("Ollama availability check failed: %s", exc)

        if previous != self._llm_available:
            logger.info(
                "Ollama availability changed",
                extra={"available": self._llm_available, "url": self.ollama_url},
            )
        self._last_llm_check = now
        return self._llm_available

    def get_status(self) -> dict:
        """Honest, UI-facing status of the reasoning backend."""
        return {
            "enabled": self.enabled,
            "available": bool(self._llm_available),
            "model": self.model,
            "url": self.ollama_url,
            "last_mode": self.last_mode,
        }

    # -- sense ------------------------------------------------------------

    def sense(self, asset_state: dict, telemetry: dict, tick_count: int) -> SenseData:
        """Assemble a structured snapshot from raw asset state + telemetry."""
        return SenseData(
            asset_id=asset_state["asset_id"],
            asset_type=asset_state["asset_type"],
            asset_name=asset_state["name"],
            health=asset_state["health"],
            operating_state=asset_state["operating_state"],
            telemetry=telemetry,
            failure_mode=asset_state.get("failure_mode"),
            total_operating_hours=asset_state.get("total_operating_hours", 0.0),
            tick_count=tick_count,
        )

    # -- think ------------------------------------------------------------

    async def think(self, sense_data: SenseData) -> AgentDecision:
        """Produce a decision, preferring the LLM and falling back to rules.

        The chosen path (and any fallback reason) is recorded in ``last_mode`` so
        the UI can report it honestly.
        """
        should_use_llm = self.enabled and self._llm_turn(sense_data.asset_id)

        if not self.enabled:
            self.last_mode = AgentMode.LLM_DISABLED.value
            return self._think_with_rules(sense_data, fallback_from=self.last_mode)

        if should_use_llm:
            if await self.check_llm_availability():
                try:
                    decision = await self._think_with_llm(sense_data)
                    self.last_mode = AgentMode.LLM.value
                    return decision
                except (TimeoutError, httpx.HTTPError, json.JSONDecodeError) as exc:
                    logger.warning(
                        "LLM reasoning failed; using rule engine",
                        extra={"asset_id": sense_data.asset_id, "error": str(exc)},
                    )
                    self.last_mode = AgentMode.LLM_ERROR.value
                    return self._think_with_rules(sense_data, fallback_from=self.last_mode)
                except Exception as exc:  # defensive: never let the loop die
                    logger.warning(
                        "Unexpected LLM error; using rule engine",
                        extra={"asset_id": sense_data.asset_id, "error": str(exc)},
                    )
                    self.last_mode = AgentMode.LLM_ERROR.value
                    return self._think_with_rules(sense_data, fallback_from=self.last_mode)
            else:
                self.last_mode = AgentMode.LLM_UNAVAILABLE.value
                return self._think_with_rules(sense_data, fallback_from=self.last_mode)

        # Throttled cycle: use rules this time (LLM narrative runs periodically).
        self.last_mode = AgentMode.RULES.value
        return self._think_with_rules(sense_data)

    def _llm_turn(self, asset_id: str) -> bool:
        """Return True if this cycle should attempt the (throttled) LLM path."""
        count = self._cycle_counts.get(asset_id, 0)
        self._cycle_counts[asset_id] = count + 1
        return count % self.llm_every_n_cycles == 0

    async def _think_with_llm(self, sense_data: SenseData) -> AgentDecision:
        """LLM-backed reasoning via Ollama (raises on failure to trigger fallback)."""
        tel = sense_data.telemetry
        prompt = self.DIAGNOSTIC_PROMPT.format(
            asset_id=sense_data.asset_id,
            asset_type=sense_data.asset_type,
            asset_name=sense_data.asset_name,
            health=round(sense_data.health, 1),
            operating_state=sense_data.operating_state,
            operating_hours=sense_data.total_operating_hours,
            failure_mode=sense_data.failure_mode or "none",
            temperature=round(tel.get("temperature", 0), 1),
            vibration=round(tel.get("vibration", 0), 2),
            voltage=round(tel.get("voltage", 0), 1),
            current=round(tel.get("current", 0), 1),
            bearing_wear=round(tel.get("bearing_wear", 0), 1),
            oil_pressure=round(tel.get("oil_pressure", 0), 2),
            power_factor=round(tel.get("power_factor", 0), 3),
            anomaly_score=round(tel.get("anomaly_score", 0), 1),
            rul_hours=round(tel.get("rul_hours", 0), 1),
        )

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(
                f"{self.ollama_url}/api/generate",
                json={"model": self.model, "prompt": prompt, "stream": False, "format": "json"},
            )
            response.raise_for_status()

        response_text = response.json().get("response", "")
        data = self._extract_json(response_text)

        try:
            decision_type = DecisionType(data.get("decision_type", "monitor"))
        except ValueError:
            decision_type = DecisionType.MONITOR
        priority = data.get("priority", "medium")
        if priority not in ("low", "medium", "high", "critical"):
            priority = "medium"

        reasoning = data.get("reasoning", "LLM analysis complete.")
        trail = [
            f"Read {sense_data.asset_name}: {round(tel.get('temperature', 0), 1)} °C, "
            f"vibration {round(tel.get('vibration', 0), 2)} mm/s, "
            f"health {round(sense_data.health)}%.",
            f"Language model ({self.model}) says: {reasoning}",
            f"Decision: {decision_type.value.upper()}. {data.get('recommended_action', '')}",
        ]
        requires = decision_type != DecisionType.MONITOR
        return AgentDecision(
            decision_type=decision_type,
            confidence=float(data.get("confidence", 60.0)),
            description=data.get("description", "Analysis complete"),
            recommended_action=data.get("recommended_action", "Continue monitoring"),
            reasoning=reasoning,
            strategic_recommendation=data.get(
                "strategic_recommendation", "Continue current maintenance schedule"
            ),
            requires_maintenance=requires,
            priority=priority,
            source=AgentMode.LLM.value,
            reasoning_trail=trail,
            detected_factors=self._detect_factors(sense_data),
            rul_hours=float(tel.get("rul_hours", 0.0)),
        )

    @staticmethod
    def _extract_json(text: str) -> dict:
        """Best-effort JSON extraction from an LLM response."""
        start, end = text.find("{"), text.rfind("}") + 1
        if 0 <= start < end:
            return json.loads(text[start:end])
        return json.loads(text)

    def _detect_factors(self, sense_data: SenseData) -> list[str]:
        """Named risk factors from telemetry (shared by both reasoning paths)."""
        t = self.RULE_THRESHOLDS
        tel = sense_data.telemetry
        factors: list[str] = []
        if sense_data.health <= t["degraded_health"]:
            factors.append(f"health is low at {round(sense_data.health)}%")
        if tel.get("temperature", 0) >= t["high_temperature"]:
            factors.append(f"running hot at {round(tel['temperature'], 1)} °C")
        if tel.get("vibration", 0) >= t["high_vibration"]:
            factors.append(f"high vibration at {round(tel['vibration'], 2)} mm/s")
        if tel.get("bearing_wear", 0) >= t["high_bearing_wear"]:
            factors.append(f"bearing wear at {round(tel['bearing_wear'])}%")
        if tel.get("oil_pressure", 99) <= t["low_oil_pressure"]:
            factors.append(f"low oil pressure at {round(tel['oil_pressure'], 2)} bar")
        if 0 < tel.get("rul_hours", 1e9) <= t["low_rul_hours"]:
            factors.append(f"short remaining life (RUL {round(tel['rul_hours'])} h)")
        if sense_data.failure_mode:
            factors.append(f"active fault: {sense_data.failure_mode.replace('_', ' ')}")
        return factors

    def _think_with_rules(
        self, sense_data: SenseData, fallback_from: str | None = None
    ) -> AgentDecision:
        """Deterministic rule-based reasoning with a scored risk model."""
        t = self.RULE_THRESHOLDS
        tel = sense_data.telemetry
        factors = self._detect_factors(sense_data)

        risk = 0.0
        if sense_data.health <= t["critical_health"]:
            risk += 50.0
        elif sense_data.health <= t["high_health"]:
            risk += 30.0
        elif sense_data.health <= t["degraded_health"]:
            risk += 15.0
        if tel.get("temperature", 0) >= t["high_temperature"]:
            risk += 15.0
        if tel.get("vibration", 0) >= t["high_vibration"]:
            risk += 20.0
        if tel.get("bearing_wear", 0) >= t["high_bearing_wear"]:
            risk += 15.0
        if tel.get("oil_pressure", 99) <= t["low_oil_pressure"]:
            risk += 15.0
        if 0 < tel.get("rul_hours", 1e9) <= t["low_rul_hours"]:
            risk += 20.0
        if sense_data.failure_mode:
            risk += 20.0

        if risk >= 70.0:
            dtype, priority = DecisionType.EMERGENCY, "critical"
            action = "Send a team now and prepare a safe shutdown"
        elif risk >= 50.0:
            dtype, priority = DecisionType.REPAIR, "high"
            action = "Repair within 4 hours"
        elif risk >= 30.0:
            dtype, priority = DecisionType.MAINTAIN, "medium"
            action = "Service within 24 hours"
        elif risk >= 15.0:
            dtype, priority = DecisionType.INSPECT, "low"
            action = "Inspect at the next planned visit"
        else:
            dtype, priority = DecisionType.MONITOR, "low"
            action = "Keep watching"

        reasoning = (
            "Warning signs: " + "; ".join(factors) + f". Risk {risk:.0f} of 100."
            if factors
            else "No warning signs. The asset is working normally."
        )
        rul = float(tel.get("rul_hours", 0.0))
        trail = [
            f"Read {sense_data.asset_name}: {round(tel.get('temperature', 0), 1)} °C, "
            f"vibration {round(tel.get('vibration', 0), 2)} mm/s, "
            f"health {round(sense_data.health)}%, remaining life {round(rul)} h.",
        ]
        if factors:
            trail.append("Warning signs: " + "; ".join(factors) + ".")
        else:
            trail.append("No warning signs.")
        trail.append(f"Risk {risk:.0f} of 100, so the decision is {dtype.value.upper()}.")
        trail.append(f"Action: {action}.")

        return AgentDecision(
            decision_type=dtype,
            confidence=min(95.0, 55.0 + risk * 0.4),
            description=f"{sense_data.asset_id} {sense_data.asset_name}",
            recommended_action=action,
            reasoning=reasoning,
            strategic_recommendation=self._strategic_recommendation(sense_data, risk),
            requires_maintenance=dtype != DecisionType.MONITOR,
            priority=priority,
            source=fallback_from or AgentMode.RULES.value,
            reasoning_trail=trail,
            detected_factors=factors,
            rul_hours=rul,
        )

    @staticmethod
    def _strategic_recommendation(sense_data: SenseData, risk: float) -> str:
        recs: list[str] = []
        if sense_data.health < 40.0:
            recs.append(
                f"Plan replacement for {sense_data.asset_name}; health "
                f"{round(sense_data.health, 1)}% suggests end-of-life approaching."
            )
        mode_recs = {
            "bearing_wear": "Add vibration-based condition monitoring to catch bearing wear earlier.",
            "insulation_breakdown": "Increase insulation-testing frequency from annual to quarterly.",
            "oil_degradation": "Upgrade oil filtration or shorten oil-change intervals.",
            "misalignment": "Run a laser alignment check and adopt a precision-alignment program.",
            "overload": "Review load distribution; consider capacity upgrade or load shedding.",
        }
        if sense_data.failure_mode in mode_recs:
            recs.append(mode_recs[sense_data.failure_mode])
        if risk >= 30.0 and not recs:
            recs.append("Re-evaluate maintenance interval for current operating conditions.")
        if not recs:
            recs.append(
                "Current maintenance strategy is effective; continue scheduled inspections."
            )
        return " ".join(recs)

    # -- act --------------------------------------------------------------

    def act(
        self, decision: AgentDecision, asset_id: str, maintenance_manager: Any
    ) -> dict[str, str] | None:
        """Create a maintenance work order for an actionable decision.

        Returns the created work-order summary, or ``None`` if no action is
        required. Import is local to avoid a hard dependency from the agent onto
        the maintenance package at module load.
        """
        from simulator.maintenance import WorkOrderPriority, WorkOrderType

        if not decision.requires_maintenance:
            return None

        work_type = {
            DecisionType.INSPECT: WorkOrderType.INSPECTION,
            DecisionType.MAINTAIN: WorkOrderType.PREVENTIVE,
            DecisionType.REPAIR: WorkOrderType.CORRECTIVE,
            DecisionType.EMERGENCY: WorkOrderType.EMERGENCY,
        }.get(decision.decision_type, WorkOrderType.INSPECTION)
        priority = {
            "low": WorkOrderPriority.LOW,
            "medium": WorkOrderPriority.MEDIUM,
            "high": WorkOrderPriority.HIGH,
            "critical": WorkOrderPriority.CRITICAL,
        }.get(decision.priority, WorkOrderPriority.MEDIUM)

        work_order = maintenance_manager.create_work_order(
            asset_id=asset_id,
            work_type=work_type,
            priority=priority,
            description=decision.description,
            reason=decision.reasoning,
            strategic_recommendation=decision.strategic_recommendation,
        )
        return {"work_order_id": work_order.id, "priority": priority.value}

    async def run_cycle(
        self,
        asset_state: dict,
        telemetry: dict,
        tick_count: int,
        maintenance_manager: Any,
        create_work_order: bool = True,
    ) -> dict[str, Any]:
        """Run a full sense -> think -> act cycle for one asset."""
        sense_data = self.sense(asset_state, telemetry, tick_count)
        decision = await self.think(sense_data)
        action = None
        if create_work_order:
            action = self.act(decision, sense_data.asset_id, maintenance_manager)
        return {
            "sense": sense_data.to_dict(),
            "decision": decision.to_dict(),
            "action": action,
        }
