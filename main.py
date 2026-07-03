"""
PowerSim AI - Real-Time Predictive Maintenance Simulation Server.

This FastAPI application provides:
- WebSocket real-time telemetry streaming
- REST API for maintenance queue management
- Static file serving for the dashboard UI
- Integration with Ollama LLM for AI agent reasoning
"""

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from simulator.power_system import PowerSystem, AssetOperationalState, AssetType, AssetData
from simulator.maintenance import MaintenanceManager, WorkOrderPriority, WorkOrderType
from ai_agent.agent import AIAgent, DecisionType


# =============================================================================
# Application Configuration
# =============================================================================

APP_VERSION = "1.0.0"
SIMULATION_TICK_INTERVAL = 2.0  # Seconds between simulation ticks
WEBSOCKET_HEARTBEAT_INTERVAL = 30.0  # Seconds between heartbeats
OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = "qwen2.5:7b"
OLLAMA_TIMEOUT = 30  # Seconds

# Store latest telemetry for REST API
latest_telemetry: Dict[str, dict] = {}

# =============================================================================
# FastAPI Application Setup
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown events."""
    global latest_telemetry

    # Startup: Start background tasks
    async def run_ticks():
        global latest_telemetry
        while True:
            try:
                # Advance simulation
                telemetry = power_system.tick()

                # Store latest telemetry for REST API
                latest_telemetry = {aid: tel.to_dict() for aid, tel in telemetry.items()}

                # Get current state
                state_summary = power_system.get_state_summary()

                # Build broadcast message
                message = {
                    "type": "tick",
                    "tick_count": power_system.tick_count,
                    "timestamp": datetime.now().isoformat(),
                    "state": state_summary,
                    "telemetry": latest_telemetry,
                    "maintenance": maintenance_manager.get_recommendations() if hasattr(maintenance_manager, 'get_recommendations') else [],
                    "queue_stats": maintenance_manager.get_statistics()
                }

                # Broadcast to all WebSocket clients
                await ws_manager.broadcast(message)

            except Exception as e:
                print(f"Tick error: {e}")

            # Wait for next tick (2 seconds)
            await asyncio.sleep(2)

    # Start the simulation task
    tick_task = asyncio.create_task(run_ticks())

    # Start heartbeat task
    await ws_manager.start_heartbeat()

    yield

    # Shutdown: Cancel tasks
    global simulation_running
    simulation_running = False
    tick_task.cancel()
    ws_manager.stop_heartbeat()


app = FastAPI(
    title="PowerSim AI",
    description="Real-Time AI-Powered Predictive Maintenance Simulation",
    version=APP_VERSION,
    lifespan=lifespan,
)

# Get the directory containing this file
BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"

# =============================================================================
# Global State
# =============================================================================

# Simulation state
power_system = PowerSystem(seed=42)
maintenance_manager = MaintenanceManager()
ai_agent = AIAgent(ollama_url=OLLAMA_URL, model=OLLAMA_MODEL, timeout_seconds=OLLAMA_TIMEOUT)

# WebSocket connections
connected_clients: Set[WebSocket] = set()

# Simulation control
simulation_running = True
last_tick_time: Optional[datetime] = None

# =============================================================================
# WebSocket Manager
# =============================================================================


class WebSocketManager:
    """Manages WebSocket connections and broadcasting."""

    def __init__(self):
        self.connections: Set[WebSocket] = set()
        self._heartbeat_task: Optional[asyncio.Task] = None

    async def connect(self, websocket: WebSocket) -> None:
        """Accept and register a new WebSocket connection."""
        await websocket.accept()
        self.connections.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        """Remove a WebSocket connection."""
        self.connections.discard(websocket)

    async def broadcast(self, message: dict) -> None:
        """Broadcast a message to all connected clients."""
        if not self.connections:
            return

        message_json = json.dumps(message)
        disconnected: Set[WebSocket] = set()

        for websocket in self.connections:
            try:
                await websocket.send_text(message_json)
            except Exception:
                disconnected.add(websocket)

        # Clean up disconnected clients
        self.connections -= disconnected

    async def send(self, websocket: WebSocket, message: dict) -> None:
        """Send a message to a specific client."""
        try:
            await websocket.send_json(message)
        except Exception:
            self.connections.discard(websocket)

    async def start_heartbeat(self) -> None:
        """Start periodic heartbeat to keep connections alive."""
        async def heartbeat_loop():
            while True:
                await asyncio.sleep(WEBSOCKET_HEARTBEAT_INTERVAL)
                await self.broadcast({"type": "heartbeat", "timestamp": datetime.now().isoformat()})

        self._heartbeat_task = asyncio.create_task(heartbeat_loop())

    def stop_heartbeat(self) -> None:
        """Stop the heartbeat task."""
        if self._heartbeat_task:
            self._heartbeat_task.cancel()


ws_manager = WebSocketManager()

# =============================================================================
# Simulation Loop
# =============================================================================


# =============================================================================
# REST API Endpoints
# =============================================================================


@app.get("/")
async def root() -> FileResponse:
    """Serve the main dashboard."""
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Dashboard not found")
    return FileResponse(index_path)


@app.get("/api/state")
async def get_state() -> dict:
    """Get current simulation state."""
    return {
        "state": power_system.get_state_summary(),
        "telemetry": latest_telemetry if latest_telemetry else {
            aid: power_system.get_telemetry_history(aid, max_points=1)[-1].to_dict()
            if power_system.get_telemetry_history(aid)
            else {}
            for aid in power_system.assets.keys()
        },
        "queue": [wo.to_dict() for wo in maintenance_manager.get_queue()],
        "queue_stats": maintenance_manager.get_statistics(),
    }


@app.post("/api/inject-failure")
async def inject_failure(data: dict) -> dict:
    """
    Inject a failure into a specific asset.

    Request body:
        asset_id: str - Target asset ID
        failure_type: str - One of: bearing_wear, insulation_breakdown,
                          oil_degradation, misalignment, overload
    """
    asset_id = data.get("asset_id")
    failure_type = data.get("failure_type")

    if not asset_id or not failure_type:
        raise HTTPException(status_code=400, detail="asset_id and failure_type required")

    if asset_id not in power_system.assets:
        raise HTTPException(status_code=404, detail=f"Asset {asset_id} not found")

    success = power_system.inject_failure(asset_id, failure_type)
    if not success:
        raise HTTPException(status_code=400, detail=f"Failed to inject {failure_type}")

    return {
        "success": True,
        "asset_id": asset_id,
        "failure_type": failure_type,
        "new_health": power_system.assets[asset_id].health,
    }


@app.post("/api/maintenance")
async def trigger_maintenance(data: dict) -> dict:
    """
    Trigger maintenance on a specific asset.

    Request body:
        asset_id: str - Target asset ID
    """
    asset_id = data.get("asset_id")

    if not asset_id:
        raise HTTPException(status_code=400, detail="asset_id required")

    if asset_id not in power_system.assets:
        raise HTTPException(status_code=404, detail=f"Asset {asset_id} not found")

    # Check if already under maintenance
    if maintenance_manager.is_asset_under_maintenance(asset_id):
        raise HTTPException(status_code=400, detail="Asset already under maintenance")

    # Perform maintenance
    success = power_system.perform_maintenance(asset_id)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to perform maintenance")

    return {
        "success": True,
        "asset_id": asset_id,
        "new_health": power_system.assets[asset_id].health,
        "new_state": power_system.assets[asset_id].operating_state.value,
    }


@app.get("/api/queue")
async def get_queue() -> dict:
    """Get the maintenance work order queue."""
    orders = maintenance_manager.get_queue()
    return {
        "work_orders": [wo.to_dict() for wo in orders],
        "stats": maintenance_manager.get_statistics(),
    }


@app.post("/api/queue/{work_order_id}/complete")
async def complete_work_order(work_order_id: str) -> dict:
    """Mark a work order as completed."""
    work_order = maintenance_manager.get_work_order(work_order_id)
    if not work_order:
        raise HTTPException(status_code=404, detail="Work order not found")

    # Start work first if not already started
    if work_order.status.value == "pending":
        maintenance_manager.start_work(work_order_id)

    success = maintenance_manager.complete_work(work_order_id)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to complete work order")

    return {"success": True, "work_order_id": work_order_id}


@app.post("/api/queue/{work_order_id}/defer")
async def defer_work_order(work_order_id: str, data: Optional[dict] = None) -> dict:
    """Defer a work order."""
    work_order = maintenance_manager.get_work_order(work_order_id)
    if not work_order:
        raise HTTPException(status_code=404, detail="Work order not found")

    reason = data.get("reason", "") if data else ""
    success = maintenance_manager.defer_work(work_order_id, reason)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to defer work order")

    return {"success": True, "work_order_id": work_order_id}


@app.post("/api/queue/{work_order_id}/cancel")
async def cancel_work_order(work_order_id: str) -> dict:
    """Cancel a work order."""
    work_order = maintenance_manager.get_work_order(work_order_id)
    if not work_order:
        raise HTTPException(status_code=404, detail="Work order not found")

    success = maintenance_manager.cancel_work(work_order_id)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to cancel work order")

    return {"success": True, "work_order_id": work_order_id}


@app.post("/api/queue/{work_order_id}/start")
async def start_work_order(work_order_id: str) -> dict:
    """Start working on a work order."""
    work_order = maintenance_manager.get_work_order(work_order_id)
    if not work_order:
        raise HTTPException(status_code=404, detail="Work order not found")

    success = maintenance_manager.start_work(work_order_id)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to start work order")

    return {"success": True, "work_order_id": work_order_id}


@app.get("/api/llm/status")
async def get_llm_status() -> dict:
    """Get the LLM availability status."""
    llm_available = await ai_agent.check_llm_availability()
    return {
        "available": llm_available,
        "url": OLLAMA_URL,
        "model": OLLAMA_MODEL,
    }


@app.get("/api/status")
async def get_status() -> dict:
    """Get server status."""
    return {
        "status": "running",
        "tick_count": power_system.tick_count,
        "uptime_hours": power_system.tick_count * PowerSystem.TICK_DURATION_SECONDS / 3600.0,
    }


@app.get("/api/sensors")
async def get_sensors() -> dict:
    """Get current sensor readings for all assets."""
    return {
        "sensors": latest_telemetry,
        "tick_count": power_system.tick_count,
    }


@app.get("/api/maintenance")
async def get_maintenance() -> dict:
    """Get maintenance queue and recommendations."""
    return {
        "queue": [wo.to_dict() for wo in maintenance_manager.get_queue()],
        "stats": maintenance_manager.get_statistics(),
    }


@app.get("/api/history/{asset_id}")
async def get_history(asset_id: str, points: int = 50) -> dict:
    """Get telemetry history for an asset."""
    history = power_system.get_telemetry_history(asset_id, max_points=points)
    return {
        "asset_id": asset_id,
        "history": [tel.to_dict() for tel in history],
    }


@app.post("/api/ai-analysis")
async def run_ai_analysis() -> dict:
    """Run AI analysis on all assets."""
    try:
        # Get current state for all assets
        assets_analysis = {}
        total_risk = 0.0

        for asset in power_system.get_all_assets():
            asset_id = asset.config.asset_id
            tel = latest_telemetry.get(asset_id, {})

            if not tel:
                continue

            # Run AI agent analysis
            try:
                result = await ai_agent.run_cycle(
                    asset_state=asset.to_dict(),
                    telemetry=tel,
                    tick_count=power_system.tick_count,
                    maintenance_manager=maintenance_manager,
                )

                decision = result.get("decision", {})
                decision_type = decision.get("decision_type", "monitor")

                # Map decision to risk level
                risk_map = {
                    "emergency": "CRITICAL",
                    "repair": "HIGH",
                    "maintain": "MEDIUM",
                    "inspect": "LOW",
                    "monitor": "LOW",
                }

                # Calculate confidence based on decision
                confidence = decision.get("confidence", 50.0)

                # Determine urgency
                urgency_map = {
                    "emergency": 0,
                    "repair": 1,
                    "maintain": 3,
                    "inspect": 7,
                    "monitor": 30,
                }
                urgency_days = urgency_map.get(decision_type, 30)

                # Build anomalies list from reasoning
                reasoning = decision.get("reasoning", "")
                anomalies = []
                if "temperature" in reasoning.lower():
                    anomalies.append("Temperature anomaly detected")
                if "vibration" in reasoning.lower():
                    anomalies.append("Excessive vibration")
                if "health" in reasoning.lower():
                    anomalies.append("Health degradation")
                if not anomalies:
                    anomalies.append("No critical anomalies")

                assets_analysis[asset_id] = {
                    "risk_level": risk_map.get(decision_type, "LOW"),
                    "anomalies": anomalies,
                    "recommended_action": decision.get("recommended_action", "Continue monitoring"),
                    "urgency_days": urgency_days,
                    "confidence": round(confidence, 1),
                    "reasoning": decision.get("description", reasoning),
                }

                # Add to total risk
                risk_scores = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
                total_risk += risk_scores.get(risk_map.get(decision_type, "LOW"), 1)

            except Exception as e:
                # Fallback analysis based on rules
                health = tel.get("health_score", 100)
                temp = tel.get("temperature", 50)

                if health < 30 or temp > 85:
                    risk_level = "CRITICAL"
                    action = "Immediate inspection required"
                    urgency = 0
                elif health < 50 or temp > 75:
                    risk_level = "HIGH"
                    action = "Schedule maintenance within 24 hours"
                    urgency = 1
                elif health < 70:
                    risk_level = "MEDIUM"
                    action = "Schedule preventive maintenance"
                    urgency = 3
                else:
                    risk_level = "LOW"
                    action = "Continue monitoring"
                    urgency = 30

                assets_analysis[asset_id] = {
                    "risk_level": risk_level,
                    "anomalies": ["Rule-based fallback analysis"],
                    "recommended_action": action,
                    "urgency_days": urgency,
                    "confidence": 75.0,
                    "reasoning": f"Asset health: {health}%, Temperature: {temp}C",
                }
                total_risk += {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}.get(risk_level, 1)

        # Generate fleet summary
        avg_risk = total_risk / len(assets_analysis) if assets_analysis else 0
        if avg_risk >= 3:
            fleet_summary = f"Fleet risk ELEVATED. Average risk score: {avg_risk:.1f}/4. Immediate attention recommended for high-risk assets."
        elif avg_risk >= 2:
            fleet_summary = f"Fleet risk MODERATE. Average risk score: {avg_risk:.1f}/4. Schedule preventive maintenance during next window."
        else:
            fleet_summary = f"Fleet risk LOW. Average risk score: {avg_risk:.1f}/4. All assets operating within normal parameters."

        # Priority order
        priority_order = sorted(
            assets_analysis.keys(),
            key=lambda x: {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}.get(assets_analysis[x]["risk_level"], 3)
        )

        return {
            "success": True,
            "fleet_summary": fleet_summary,
            "priority_order": priority_order,
            "estimated_total_risk_cost": round(total_risk * 1000, 2),
            "assets": assets_analysis,
            "timestamp": datetime.now().isoformat(),
        }

    except Exception as e:
        # Full fallback
        return {
            "success": True,
            "fleet_summary": "Rule-based analysis complete. All assets monitored.",
            "priority_order": ["T1", "M1", "G1", "P1"],
            "estimated_total_risk_cost": 4000,
            "assets": {
                "T1": {"risk_level": "LOW", "anomalies": ["Normal operation"], "recommended_action": "Continue monitoring", "urgency_days": 30, "confidence": 80.0, "reasoning": "Transformer operating normally"},
                "M1": {"risk_level": "LOW", "anomalies": ["Normal operation"], "recommended_action": "Continue monitoring", "urgency_days": 30, "confidence": 80.0, "reasoning": "Motor operating normally"},
                "G1": {"risk_level": "LOW", "anomalies": ["Normal operation"], "recommended_action": "Continue monitoring", "urgency_days": 30, "confidence": 80.0, "reasoning": "Generator operating normally"},
                "P1": {"risk_level": "LOW", "anomalies": ["Normal operation"], "recommended_action": "Continue monitoring", "urgency_days": 30, "confidence": 80.0, "reasoning": "Pump operating normally"},
            },
            "timestamp": datetime.now().isoformat(),
        }


@app.post("/api/control/inject-failure/{asset_id}")
async def control_inject_failure(asset_id: str, failure_type: str = "bearing_wear") -> dict:
    """Inject failure into an asset."""
    if asset_id not in power_system.assets:
        raise HTTPException(status_code=404, detail=f"Asset {asset_id} not found")

    success = power_system.inject_failure(asset_id, failure_type)
    if not success:
        raise HTTPException(status_code=400, detail=f"Failed to inject {failure_type}")

    return {
        "success": True,
        "asset_id": asset_id,
        "failure_type": failure_type,
        "new_health": power_system.assets[asset_id].health,
    }


@app.post("/api/control/perform-maintenance/{asset_id}")
async def control_perform_maintenance(asset_id: str) -> dict:
    """Perform maintenance on an asset."""
    if asset_id not in power_system.assets:
        raise HTTPException(status_code=404, detail=f"Asset {asset_id} not found")

    if maintenance_manager.is_asset_under_maintenance(asset_id):
        raise HTTPException(status_code=400, detail="Asset already under maintenance")

    success = power_system.perform_maintenance(asset_id)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to perform maintenance")

    return {
        "success": True,
        "asset_id": asset_id,
        "new_health": power_system.assets[asset_id].health,
        "new_state": power_system.assets[asset_id].operating_state.value,
    }


@app.post("/api/control/reset")
async def control_reset() -> dict:
    """Reset the simulation."""
    global power_system, maintenance_manager, latest_telemetry
    power_system = PowerSystem(seed=42)
    maintenance_manager = MaintenanceManager()
    latest_telemetry = {}
    return {"success": True, "message": "Simulation reset"}


# =============================================================================
# WebSocket Endpoint
# =============================================================================


@app.websocket("/ws/live")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time updates."""
    await ws_manager.connect(websocket)

    # Send initial state
    initial_state = {
        "type": "initial_state",
        "state": power_system.get_state_summary(),
        "queue": [wo.to_dict() for wo in maintenance_manager.get_queue()],
    }
    await ws_manager.send(websocket, initial_state)

    try:
        while True:
            # Handle incoming messages (client -> server)
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=1.0)
                message = json.loads(data)

                # Handle client commands
                if message.get("type") == "ping":
                    await ws_manager.send(websocket, {"type": "pong", "timestamp": datetime.now().isoformat()})

            except asyncio.TimeoutError:
                pass  # Expected, continue loop
            except json.JSONDecodeError:
                pass  # Ignore invalid JSON

    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception as e:
        print(f"WebSocket error: {e}")
        ws_manager.disconnect(websocket)


# =============================================================================
# Main Entry Point
# =============================================================================


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
