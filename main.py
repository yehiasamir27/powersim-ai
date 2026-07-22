"""
PowerSim AI — API & real-time transport layer.

A thin FastAPI shell over :class:`SimulationService`. Responsibilities kept here:
HTTP/WebSocket transport, request validation, CORS, static hosting, and driving
two background loops:

* **telemetry loop** — advances the digital twin and streams ``tick`` frames;
* **agent loop** — runs the continuous sense→think→act pass and streams
  ``agent`` frames (decisions + reasoning trail).

All simulation state lives in the service; this module holds no business logic.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from config import settings
from logging_config import get_logger, setup_logging
from schemas import (
    AssetRequest,
    ContactRequest,
    DeferRequest,
    ImpactAssumptionsUpdate,
    InjectFailureRequest,
)
from simulation_service import SimulationService

setup_logging(settings.log_level, settings.log_json)
logger = get_logger("powersim.api")

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"

service = SimulationService(settings)


# =============================================================================
# WebSocket connection manager
# =============================================================================


class WebSocketManager:
    """Tracks WebSocket clients and broadcasts frames to them."""

    def __init__(self, max_connections: int) -> None:
        self.connections: set[WebSocket] = set()
        self.max_connections = max_connections

    async def connect(self, websocket: WebSocket) -> bool:
        if len(self.connections) >= self.max_connections:
            await websocket.close(code=1013)  # try again later
            logger.warning("WebSocket rejected: connection limit reached")
            return False
        await websocket.accept()
        self.connections.add(websocket)
        return True

    def disconnect(self, websocket: WebSocket) -> None:
        self.connections.discard(websocket)

    async def broadcast(self, message: dict) -> None:
        if not self.connections:
            return
        payload = json.dumps(message, default=str)
        dead: set[WebSocket] = set()
        for ws in self.connections:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.add(ws)
        self.connections -= dead

    async def send(self, websocket: WebSocket, message: dict) -> None:
        try:
            await websocket.send_text(json.dumps(message, default=str))
        except Exception:
            self.disconnect(websocket)


ws_manager = WebSocketManager(settings.max_ws_connections)


# =============================================================================
# Background loops
# =============================================================================


async def _telemetry_loop() -> None:
    """Advance the twin and broadcast telemetry at the configured cadence."""
    interval = settings.simulation_tick_seconds
    while True:
        try:
            frame = await service.advance_telemetry()
            await ws_manager.broadcast(frame)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Telemetry loop error")
        await asyncio.sleep(interval)


async def _agent_loop() -> None:
    """Run the continuous agent pass and broadcast reasoning at its cadence."""
    interval = settings.simulation_tick_seconds * settings.agent_cycle_every_n_ticks
    # Let the first telemetry frame land before reasoning.
    await asyncio.sleep(interval)
    while True:
        try:
            frame = await service.run_agent_pass()
            if frame.get("events") or frame.get("decisions"):
                await ws_manager.broadcast(frame)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Agent loop error")
        await asyncio.sleep(interval)


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    logger.info(
        "Starting %s v%s", settings.app_name, settings.app_version,
        extra={"environment": settings.environment, "ollama": settings.ollama_url},
    )
    tasks = [asyncio.create_task(_telemetry_loop()), asyncio.create_task(_agent_loop())]
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        logger.info("Shutdown complete")


app = FastAPI(
    title=settings.app_name,
    description="Agentic AI + digital-twin predictive maintenance for industrial power systems.",
    version=settings.app_version,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# Static pages
# =============================================================================


def _serve(page: str, fallback: str = "index.html") -> FileResponse:
    path = STATIC_DIR / page
    if not path.exists():
        path = STATIC_DIR / fallback
    if not path.exists():
        raise HTTPException(status_code=404, detail="Page not found")
    return FileResponse(path)


@app.get("/", include_in_schema=False)
async def root() -> FileResponse:
    """Marketing site (falls back to the dashboard if not yet built)."""
    return _serve("index.html")


@app.get("/dashboard", include_in_schema=False)
async def dashboard() -> FileResponse:
    """Live operations dashboard."""
    return _serve("dashboard.html")


@app.get("/pitch", include_in_schema=False)
async def pitch() -> FileResponse:
    """Investor pitch summary."""
    return _serve("pitch.html")


@app.get("/health", include_in_schema=False)
async def health() -> dict:
    """Liveness probe for containers/orchestrators."""
    return {"status": "ok", "tick": service.power_system.tick_count}


# =============================================================================
# REST API — read models
# =============================================================================


@app.get("/api/status")
async def get_status() -> dict:
    summary = service.power_system.get_state_summary()
    return {
        "status": "running",
        "app": settings.app_name,
        "version": settings.app_version,
        "tick_count": summary["tick_count"],
        "uptime_hours": summary["uptime_hours"],
    }


@app.get("/api/state")
async def get_state() -> dict:
    return service.get_state()


@app.get("/api/analysis")
async def get_analysis() -> dict:
    """Latest continuous agent analysis (fleet summary, decisions, why-trail feed)."""
    return service.get_analysis()


@app.post("/api/analysis/run")
async def run_analysis() -> dict:
    """Force an immediate agent pass and return the fresh analysis."""
    await service.run_agent_pass()
    return service.get_analysis()


@app.get("/api/impact")
async def get_impact() -> dict:
    return service.get_impact()


@app.post("/api/impact/assumptions")
async def update_impact(update: ImpactAssumptionsUpdate) -> dict:
    return service.update_impact_assumptions(update.model_dump())


@app.get("/api/integrations")
async def get_integrations() -> dict:
    return {"integrations": service.get_integrations()}


@app.get("/api/agent/status")
async def agent_status() -> dict:
    return service.agent.get_status()


@app.get("/api/llm/status")
async def llm_status() -> dict:
    """Back-compatible LLM status; reports honest availability."""
    available = await service.agent.check_llm_availability()
    status = service.agent.get_status()
    status["available"] = available
    return status


@app.get("/api/history/{asset_id}")
async def get_history(asset_id: str, points: int = 60) -> dict:
    if asset_id not in service.power_system.assets:
        raise HTTPException(status_code=404, detail=f"Asset {asset_id} not found")
    points = max(1, min(points, settings.telemetry_history_points))
    history = service.power_system.get_telemetry_history(asset_id, max_points=points)
    return {"asset_id": asset_id, "history": [t.to_dict() for t in history]}


@app.get("/api/queue")
async def get_queue() -> dict:
    return {
        "work_orders": [wo.to_dict() for wo in service.maintenance.get_queue()],
        "stats": service.maintenance.get_statistics(),
    }


# =============================================================================
# REST API — commands
# =============================================================================


@app.post("/api/inject-failure")
async def inject_failure(req: InjectFailureRequest) -> dict:
    try:
        return service.inject_failure(req.asset_id, req.failure_type)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Asset {req.asset_id} not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/maintenance")
async def perform_maintenance(req: AssetRequest) -> dict:
    try:
        return service.perform_maintenance(req.asset_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Asset {req.asset_id} not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/queue/{work_order_id}/complete")
async def complete_work_order(work_order_id: str) -> dict:
    wo = service.maintenance.get_work_order(work_order_id)
    if not wo:
        raise HTTPException(status_code=404, detail="Work order not found")
    if wo.status.value in ("pending", "scheduled"):
        service.maintenance.start_work(work_order_id)
    if not service.maintenance.complete_work(work_order_id):
        raise HTTPException(status_code=400, detail="Failed to complete work order")
    return {"success": True, "work_order_id": work_order_id}


@app.post("/api/queue/{work_order_id}/start")
async def start_work_order(work_order_id: str) -> dict:
    if not service.maintenance.get_work_order(work_order_id):
        raise HTTPException(status_code=404, detail="Work order not found")
    if not service.maintenance.start_work(work_order_id):
        raise HTTPException(status_code=400, detail="Failed to start work order")
    return {"success": True, "work_order_id": work_order_id}


@app.post("/api/queue/{work_order_id}/defer")
async def defer_work_order(work_order_id: str, req: DeferRequest | None = None) -> dict:
    if not service.maintenance.get_work_order(work_order_id):
        raise HTTPException(status_code=404, detail="Work order not found")
    reason = req.reason if req else ""
    if not service.maintenance.defer_work(work_order_id, reason):
        raise HTTPException(status_code=400, detail="Failed to defer work order")
    return {"success": True, "work_order_id": work_order_id}


@app.post("/api/queue/{work_order_id}/cancel")
async def cancel_work_order(work_order_id: str) -> dict:
    if not service.maintenance.get_work_order(work_order_id):
        raise HTTPException(status_code=404, detail="Work order not found")
    if not service.maintenance.cancel_work(work_order_id):
        raise HTTPException(status_code=400, detail="Failed to cancel work order")
    return {"success": True, "work_order_id": work_order_id}


@app.post("/api/reset")
async def reset_simulation() -> dict:
    service.reset()
    return {"success": True, "message": "Simulation reset"}


@app.post("/api/contact")
async def contact(req: ContactRequest) -> dict:
    """Capture a 'request a demo' submission (logged; no third-party egress)."""
    logger.info(
        "Contact request received",
        extra={"contact_name": req.name, "email": req.email, "company": req.company},
    )
    return {
        "success": True,
        "message": "Thanks — we'll be in touch shortly.",
    }


# =============================================================================
# WebSocket
# =============================================================================


@app.websocket("/ws/live")
async def websocket_endpoint(websocket: WebSocket) -> None:
    if not await ws_manager.connect(websocket):
        return
    await ws_manager.send(
        websocket,
        {
            "type": "initial_state",
            "state": service.power_system.get_state_summary(),
            "telemetry": service.latest_telemetry,
            "decisions": service.latest_decisions,
            "impact": service.impact.snapshot(),
            "queue": [wo.to_dict() for wo in service.maintenance.get_queue()],
        },
    )
    try:
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=1.0)
                message = json.loads(data)
                if message.get("type") == "ping":
                    await ws_manager.send(
                        websocket, {"type": "pong", "timestamp": datetime.now().isoformat()}
                    )
            except TimeoutError:
                continue
            except json.JSONDecodeError:
                continue
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception:
        logger.exception("WebSocket error")
        ws_manager.disconnect(websocket)


@app.exception_handler(Exception)
async def unhandled_exception_handler(_, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error: %s", exc)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# Static assets (mounted last so it doesn't shadow API routes).
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.environment == "development",
    )
