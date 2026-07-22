"""
Industrial data-integration layer.

Defines the ``TelemetrySource`` contract that decouples PowerSim's agentic core
from *where* telemetry comes from. Today the only implemented source is the
digital-twin simulator; OPC-UA and MQTT/Sparkplug B connectors are scaffolded
stubs on the roadmap (see docs/MARKET_RESEARCH.md — multi-protocol connectivity
is table stakes for industrial buyers). Keeping the boundary explicit is what
makes "swap the simulator for a real plant" a connector, not a rewrite.
"""

from .base import (
    PLANNED_INTEGRATIONS,
    IntegrationInfo,
    TelemetrySource,
    get_integration_catalog,
)
from .simulated import SimulatedTelemetrySource

__all__ = [
    "TelemetrySource",
    "IntegrationInfo",
    "PLANNED_INTEGRATIONS",
    "get_integration_catalog",
    "SimulatedTelemetrySource",
]
