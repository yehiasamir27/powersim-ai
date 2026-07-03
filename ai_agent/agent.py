"""
AI Agent implementation for predictive maintenance diagnostics.

This module implements an Agentic AI system following the sense→think→act
paradigm for industrial predictive maintenance. The agent analyzes telemetry
data from power system assets and generates maintenance recommendations using
LLM-based reasoning (via Ollama) with rule-based fallback.
"""

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import httpx


class DecisionType(Enum):
    """Types of decisions the agent can make."""
    MONITOR = "monitor"  # Continue monitoring, no action needed
    INSPECT = "inspect"  # Schedule inspection
    MAINTAIN = "maintain"  # Schedule preventive maintenance
    REPAIR = "repair"  # Schedule corrective maintenance
    EMERGENCY = "emergency"  # Immediate emergency response required


@dataclass
class SenseData:
    """
    Data collected during the sense phase.

    Contains telemetry readings, asset state, and historical context
    for a single asset at a point in time.
    """
    asset_id: str
    asset_type: str
    asset_name: str
    health: float
    operating_state: str
    telemetry: Dict[str, float]
    failure_mode: Optional[str]
    total_operating_hours: float
    tick_count: int

    def to_dict(self) -> dict:
        """Convert sense data to dictionary."""
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
    """
    Decision output from the agent's think/act phases.

    Attributes:
        decision_type: Type of decision made
        confidence: Confidence level 0-100%
        description: Human-readable explanation
        recommended_action: Specific action to take
        reasoning: Chain of thought leading to decision
        strategic_recommendation: Long-term policy suggestions
        requires_maintenance: Whether maintenance should be scheduled
        priority: Suggested priority level
    """
    decision_type: DecisionType
    confidence: float
    description: str
    recommended_action: str
    reasoning: str
    strategic_recommendation: str
    requires_maintenance: bool = False
    priority: str = "medium"

    def to_dict(self) -> dict:
        """Convert decision to dictionary."""
        return {
            "decision_type": self.decision_type.value,
            "confidence": round(self.confidence, 2),
            "description": self.description,
            "recommended_action": self.recommended_action,
            "reasoning": self.reasoning,
            "strategic_recommendation": self.strategic_recommendation,
            "requires_maintenance": self.requires_maintenance,
            "priority": self.priority,
        }


class AIAgent:
    """
    AI Agent for predictive maintenance using sense→think→act loop.

    This agent continuously monitors power system assets, analyzes telemetry
    data using LLM-based reasoning (with rule-based fallback), and generates
    maintenance work orders with strategic recommendations.

    Attributes:
        ollama_url: URL of the Ollama API server
        model: Ollama model name to use
        timeout_seconds: Timeout for LLM requests
        use_llm: Whether to use LLM or rule-based reasoning
    """

    # LLM prompt template for diagnostics
    DIAGNOSTIC_PROMPT = """
You are an expert predictive maintenance AI agent for industrial power systems.
Analyze the following asset telemetry data and provide a diagnostic assessment.

ASSET INFORMATION:
- Asset ID: {asset_id}
- Type: {asset_type} ({asset_name})
- Current Health: {health}%
- Operating State: {operating_state}
- Total Operating Hours: {operating_hours:.2f}
- Failure Mode (if any): {failure_mode}

TELEMETRY READINGS:
- Temperature: {temperature}°C
- Vibration: {vibration} mm/s RMS
- Voltage: {voltage}V
- Current: {current}A
- Bearing Wear: {bearing_wear}%
- Oil Pressure: {oil_pressure} bar
- Health Score: {health_score}%
- Power Factor: {power_factor}

SIMULATION CONTEXT:
- Current Tick: {tick_count}

TASK:
1. Analyze the telemetry data and identify any anomalies or concerning trends.
2. Determine the current asset health status and risk level.
3. Recommend immediate actions if needed.
4. Provide strategic recommendations for long-term maintenance policy.

Respond in JSON format with these exact fields:
{{
    "decision_type": "monitor" | "inspect" | "maintain" | "repair" | "emergency",
    "confidence": 0-100,
    "description": "Brief summary of asset condition",
    "recommended_action": "Specific action to take",
    "reasoning": "Detailed chain of thought explaining your analysis",
    "strategic_recommendation": "Long-term policy suggestion (e.g., extend maintenance interval, upgrade component, change operating parameters)",
    "priority": "low" | "medium" | "high" | "critical"
}}

Be concise but thorough. Focus on actionable insights.
"""

    # Rule-based thresholds for fallback
    RULE_THRESHOLDS = {
        "critical_health": 15.0,
        "high_health": 30.0,
        "degraded_health": 50.0,
        "high_temperature": 80.0,
        "high_vibration": 5.0,
        "low_efficiency": 0.75,
        "low_oil_pressure": 2.5,
        "high_bearing_wear": 70.0,
        "high_harmonic": 0.10,
    }

    def __init__(
        self,
        ollama_url: str = "http://localhost:11434",
        model: str = "qwen2.5:7b",
        timeout_seconds: int = 30,
    ):
        """
        Initialize the AI agent.

        Args:
            ollama_url: Base URL for Ollama API
            model: Model name to use for inference
            timeout_seconds: Request timeout
        """
        self.ollama_url = ollama_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.use_llm = True
        self._llm_available: Optional[bool] = None
        self._last_llm_check: Optional[datetime] = None

    async def check_llm_availability(self) -> bool:
        """
        Check if Ollama LLM is available.

        Returns:
            True if LLM is reachable and responsive
        """
        # Cache check for 60 seconds
        now = datetime.now()
        if (
            self._llm_available is not None
            and self._last_llm_check is not None
            and (now - self._last_llm_check).total_seconds() < 60
        ):
            return self._llm_available

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.ollama_url}/api/tags")
                self._llm_available = response.status_code == 200
        except Exception:
            self._llm_available = False

        self._last_llm_check = now
        return self._llm_available

    async def sense(
        self,
        asset_state: dict,
        telemetry: dict,
        tick_count: int,
    ) -> SenseData:
        """
        Sense phase: Collect and preprocess asset data.

        Args:
            asset_state: Current state of the asset
            telemetry: Current telemetry readings
            tick_count: Current simulation tick

        Returns:
            Structured sense data for the think phase
        """
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

    async def think(self, sense_data: SenseData) -> AgentDecision:
        """
        Think phase: Analyze sense data and make a decision.

        Attempts LLM-based reasoning first, falls back to rule-based
        diagnostics if LLM is unavailable or times out.

        Args:
            sense_data: Data from the sense phase

        Returns:
            Agent decision with reasoning and recommendations
        """
        # Check LLM availability
        llm_available = await self.check_llm_availability()

        if llm_available and self.use_llm:
            try:
                return await self._think_with_llm(sense_data)
            except asyncio.TimeoutError:
                pass  # Fall through to rule-based
            except Exception:
                pass  # Fall through to rule-based

        # Rule-based fallback
        return self._think_with_rules(sense_data)

    async def _think_with_llm(self, sense_data: SenseData) -> AgentDecision:
        """
        Think phase using LLM reasoning.

        Args:
            sense_data: Data from the sense phase

        Returns:
            Agent decision from LLM analysis

        Raises:
            asyncio.TimeoutError: If LLM request times out
            Exception: If LLM request fails
        """
        prompt = self.DIAGNOSTIC_PROMPT.format(
            asset_id=sense_data.asset_id,
            asset_type=sense_data.asset_type,
            asset_name=sense_data.asset_name,
            health=sense_data.health,
            operating_state=sense_data.operating_state,
            operating_hours=sense_data.total_operating_hours,
            failure_mode=sense_data.failure_mode or "None",
            tick_count=sense_data.tick_count,
            temperature=sense_data.telemetry["temperature"],
            vibration=sense_data.telemetry["vibration"],
            voltage=sense_data.telemetry["voltage"],
            current=sense_data.telemetry["current"],
            bearing_wear=sense_data.telemetry["bearing_wear"],
            oil_pressure=sense_data.telemetry["oil_pressure"],
            health_score=sense_data.telemetry["health_score"],
            power_factor=sense_data.telemetry["power_factor"],
        )

        async with httpx.AsyncClient(timeout=float(self.timeout_seconds)) as client:
            response = await client.post(
                f"{self.ollama_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                },
            )
            response.raise_for_status()

        result = response.json()
        response_text = result.get("response", "")

        # Parse JSON response
        try:
            # Try to extract JSON from response
            json_start = response_text.find("{")
            json_end = response_text.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                json_str = response_text[json_start:json_end]
                decision_data = json.loads(json_str)
            else:
                decision_data = json.loads(response_text)
        except json.JSONDecodeError:
            # If JSON parsing fails, use rule-based fallback
            return self._think_with_rules(sense_data)

        # Map string decision type to enum
        decision_type_str = decision_data.get("decision_type", "monitor")
        try:
            decision_type = DecisionType(decision_type_str)
        except ValueError:
            decision_type = DecisionType.MONITOR

        priority_str = decision_data.get("priority", "medium")
        if priority_str not in ("low", "medium", "high", "critical"):
            priority_str = "medium"

        return AgentDecision(
            decision_type=decision_type,
            confidence=float(decision_data.get("confidence", 50.0)),
            description=decision_data.get("description", "Analysis complete"),
            recommended_action=decision_data.get("recommended_action", "Continue monitoring"),
            reasoning=decision_data.get("reasoning", "LLM analysis completed"),
            strategic_recommendation=decision_data.get(
                "strategic_recommendation",
                "Continue current maintenance schedule",
            ),
            requires_maintenance=decision_type in (
                DecisionType.INSPECT,
                DecisionType.MAINTAIN,
                DecisionType.REPAIR,
                DecisionType.EMERGENCY,
            ),
            priority=priority_str,
        )

    def _think_with_rules(self, sense_data: SenseData) -> AgentDecision:
        """
        Think phase using rule-based diagnostics.

        Args:
            sense_data: Data from the sense phase

        Returns:
            Agent decision from rule-based analysis
        """
        t = self.RULE_THRESHOLDS
        tel = sense_data.telemetry

        # Calculate risk score
        risk_score = 0.0
        reasons: List[str] = []

        # Health-based risk
        if sense_data.health <= t["critical_health"]:
            risk_score += 50.0
            reasons.append("Critical health level")
        elif sense_data.health <= t["high_health"]:
            risk_score += 30.0
            reasons.append("High risk health level")
        elif sense_data.health <= t["degraded_health"]:
            risk_score += 15.0
            reasons.append("Degraded health level")

        # Temperature risk
        if tel["temperature"] >= t["high_temperature"]:
            risk_score += 20.0
            reasons.append("High temperature")

        # Vibration risk
        if tel["vibration"] >= t["high_vibration"]:
            risk_score += 20.0
            reasons.append("Excessive vibration")

        # Bearing wear risk
        if tel["bearing_wear"] >= t["high_bearing_wear"]:
            risk_score += 20.0
            reasons.append("High bearing wear")

        # Oil pressure risk
        if tel["oil_pressure"] <= t["low_oil_pressure"]:
            risk_score += 15.0
            reasons.append("Low oil pressure")

        # Failure mode risk
        if sense_data.failure_mode:
            risk_score += 25.0
            reasons.append(f"Active failure mode: {sense_data.failure_mode}")

        # Determine decision based on risk score
        if risk_score >= 70.0:
            decision_type = DecisionType.EMERGENCY
            priority = "critical"
            action = "Initiate emergency shutdown and dispatch maintenance team immediately"
        elif risk_score >= 50.0:
            decision_type = DecisionType.REPAIR
            priority = "high"
            action = "Schedule corrective maintenance within 4 hours"
        elif risk_score >= 30.0:
            decision_type = DecisionType.MAINTAIN
            priority = "medium"
            action = "Schedule preventive maintenance within 24 hours"
        elif risk_score >= 15.0:
            decision_type = DecisionType.INSPECT
            priority = "low"
            action = "Schedule inspection at next maintenance window"
        else:
            decision_type = DecisionType.MONITOR
            priority = "low"
            action = "Continue normal monitoring"

        # Generate strategic recommendation
        strategic_rec = self._generate_strategic_recommendation(sense_data, risk_score)

        # Build reasoning string
        if reasons:
            reasoning = f"Rule-based analysis identified {len(reasons)} risk factors: " + "; ".join(reasons) + "."
        else:
            reasoning = "No significant risk factors detected. Asset operating within normal parameters."

        description = f"Asset {sense_data.asset_id} ({sense_data.asset_name}) - {sense_data.operating_state.upper()}"

        return AgentDecision(
            decision_type=decision_type,
            confidence=min(95.0, 50.0 + risk_score),
            description=description,
            recommended_action=action,
            reasoning=reasoning,
            strategic_recommendation=strategic_rec,
            requires_maintenance=decision_type != DecisionType.MONITOR,
            priority=priority,
        )

    def _generate_strategic_recommendation(
        self,
        sense_data: SenseData,
        risk_score: float,
    ) -> str:
        """
        Generate strategic long-term recommendations.

        Args:
            sense_data: Current sense data
            risk_score: Calculated risk score

        Returns:
            Strategic recommendation string
        """
        recommendations: List[str] = []

        # Health-based recommendations
        if sense_data.health < 40.0:
            recommendations.append(
                f"Consider asset replacement planning for {sense_data.asset_name} - "
                f"current health ({sense_data.health}%) indicates end-of-life approaching"
            )

        # Operating hours recommendations
        if sense_data.total_operating_hours > 1000:
            recommendations.append(
                f"Asset has {sense_data.total_operating_hours:.0f} operating hours - "
                "evaluate extended warranty or replacement options"
            )

        # Failure mode specific
        if sense_data.failure_mode == "bearing_wear":
            recommendations.append(
                "Implement vibration-based condition monitoring program to detect bearing wear earlier"
            )
        elif sense_data.failure_mode == "insulation_breakdown":
            recommendations.append(
                "Review insulation testing schedule - consider increasing frequency from annual to quarterly"
            )
        elif sense_data.failure_mode == "oil_degradation":
            recommendations.append(
                "Evaluate oil filtration system upgrade or more frequent oil change intervals"
            )
        elif sense_data.failure_mode == "misalignment":
            recommendations.append(
                "Perform laser alignment check and implement precision alignment program"
            )
        elif sense_data.failure_mode == "overload":
            recommendations.append(
                "Review load distribution and consider capacity upgrade or load shedding"
            )

        # Risk-based recommendations
        if risk_score >= 30.0:
            recommendations.append(
                "Review maintenance interval - current schedule may be insufficient for operating conditions"
            )

        if not recommendations:
            recommendations.append(
                "Current maintenance strategy appears effective - continue with scheduled inspections"
            )

        return " ".join(recommendations)

    async def act(
        self,
        decision: AgentDecision,
        maintenance_manager: Any,
    ) -> Optional[Dict[str, str]]:
        """
        Act phase: Execute decision by creating maintenance work orders.

        Args:
            decision: Decision from the think phase
            maintenance_manager: MaintenanceManager instance

        Returns:
            Work order ID if created, None otherwise
        """
        from simulator.maintenance import WorkOrderPriority, WorkOrderType

        if not decision.requires_maintenance:
            return None

        # Map decision type to work order type
        work_type_map = {
            DecisionType.INSPECT: WorkOrderType.INSPECTION,
            DecisionType.MAINTAIN: WorkOrderType.PREVENTIVE,
            DecisionType.REPAIR: WorkOrderType.CORRECTIVE,
            DecisionType.EMERGENCY: WorkOrderType.EMERGENCY,
        }

        # Map priority string to enum
        priority_map = {
            "low": WorkOrderPriority.LOW,
            "medium": WorkOrderPriority.MEDIUM,
            "high": WorkOrderPriority.HIGH,
            "critical": WorkOrderPriority.CRITICAL,
        }

        work_type = work_type_map.get(decision.decision_type, WorkOrderType.INSPECTION)
        priority = priority_map.get(decision.priority, WorkOrderPriority.MEDIUM)

        # Create work order
        work_order = maintenance_manager.create_work_order(
            asset_id=sense_data.asset_id if "sense_data" in dir() else "unknown",
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
    ) -> Dict[str, Any]:
        """
        Run a complete sense→think→act cycle.

        Args:
            asset_state: Current asset state
            telemetry: Current telemetry readings
            tick_count: Current simulation tick
            maintenance_manager: MaintenanceManager instance

        Returns:
            Dictionary containing sense data, decision, and action results
        """
        # Sense
        sense_data = await self.sense(asset_state, telemetry, tick_count)

        # Think
        decision = await self.think(sense_data)

        # Act - need to pass asset_id from sense_data
        from simulator.maintenance import WorkOrderPriority, WorkOrderType

        work_order_result = None
        if decision.requires_maintenance:
            work_type_map = {
                DecisionType.INSPECT: WorkOrderType.INSPECTION,
                DecisionType.MAINTAIN: WorkOrderType.PREVENTIVE,
                DecisionType.REPAIR: WorkOrderType.CORRECTIVE,
                DecisionType.EMERGENCY: WorkOrderType.EMERGENCY,
            }
            priority_map = {
                "low": WorkOrderPriority.LOW,
                "medium": WorkOrderPriority.MEDIUM,
                "high": WorkOrderPriority.HIGH,
                "critical": WorkOrderPriority.CRITICAL,
            }

            work_type = work_type_map.get(decision.decision_type, WorkOrderType.INSPECTION)
            priority = priority_map.get(decision.priority, WorkOrderPriority.MEDIUM)

            work_order = maintenance_manager.create_work_order(
                asset_id=sense_data.asset_id,
                work_type=work_type,
                priority=priority,
                description=decision.description,
                reason=decision.reasoning,
                strategic_recommendation=decision.strategic_recommendation,
            )
            work_order_result = {"work_order_id": work_order.id, "priority": priority.value}

        return {
            "sense": sense_data.to_dict(),
            "decision": decision.to_dict(),
            "action": work_order_result,
        }
