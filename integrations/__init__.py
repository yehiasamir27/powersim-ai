"""
Industrial data-integration layer.

Defines the contracts that decouple PowerSim's agentic core from *where* data
comes from — ``TelemetrySource`` for power-asset telemetry and
``WasteEventSource`` for waste consignments. Today the only implemented source is
the digital-twin simulator; OPC-UA, MQTT/Sparkplug B, and the waste-side
connectors (IoT sensors, conveyor vision, ERP/MES, regulatory feeds) are
scaffolded stubs on the roadmap. Keeping the boundary explicit is what makes
"swap the simulator for a real plant" a connector, not a rewrite.
"""

from .base import (
    PLANNED_INTEGRATIONS,
    IntegrationInfo,
    TelemetrySource,
    info_to_dict,
)
from .simulated import SimulatedTelemetrySource
from .waste_sources import (
    WASTE_INTEGRATIONS,
    ErpMesSource,
    IoTWasteSensorSource,
    RegulatoryFeedSource,
    SmartBinCameraSource,
    WasteEventSource,
)

#: Every integration across both product pillars, in display order.
ALL_INTEGRATIONS: tuple[IntegrationInfo, ...] = PLANNED_INTEGRATIONS + WASTE_INTEGRATIONS


def get_integration_catalog() -> list[dict]:
    """Return the full integration catalog (power + waste) for the API/UI."""
    return [info_to_dict(i) for i in ALL_INTEGRATIONS]


__all__ = [
    "TelemetrySource",
    "WasteEventSource",
    "IntegrationInfo",
    "PLANNED_INTEGRATIONS",
    "WASTE_INTEGRATIONS",
    "ALL_INTEGRATIONS",
    "get_integration_catalog",
    "info_to_dict",
    "SimulatedTelemetrySource",
    "IoTWasteSensorSource",
    "SmartBinCameraSource",
    "ErpMesSource",
    "RegulatoryFeedSource",
]
