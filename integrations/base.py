"""
Telemetry-source contract and integration catalog.

``TelemetrySource`` is the seam between PowerSim's agentic core and the outside
world. Every source — the simulator today, OPC-UA / MQTT / historians tomorrow —
implements the same async contract, so the sense→think→act loop never needs to
know whether a reading came from a physics model or a real PLC.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

IntegrationStatus = Literal["available", "planned", "experimental"]


@dataclass(frozen=True)
class IntegrationInfo:
    """UI/roadmap metadata describing a data integration."""

    key: str
    name: str
    protocol: str
    status: IntegrationStatus
    description: str
    standards: tuple[str, ...] = ()


class TelemetrySource(ABC):
    """Abstract source of asset telemetry.

    Implementations must be safe to poll from the async simulation loop. ``read``
    returns a mapping of ``asset_id -> telemetry dict`` (the same shape the rest of
    the system consumes, i.e. ``TelemetryData.to_dict()``).
    """

    #: Static metadata for the integration catalog / roadmap UI.
    info: IntegrationInfo

    @abstractmethod
    async def connect(self) -> None:
        """Establish the connection / start the simulator. Idempotent."""

    @abstractmethod
    async def read(self) -> dict[str, dict]:
        """Return the latest telemetry for every asset as ``asset_id -> dict``."""

    @abstractmethod
    async def close(self) -> None:
        """Release resources / stop streaming. Idempotent."""

    def describe(self) -> dict:
        """Return this source's catalog metadata as a plain dict."""
        info = self.info
        return {
            "key": info.key,
            "name": info.name,
            "protocol": info.protocol,
            "status": info.status,
            "description": info.description,
            "standards": list(info.standards),
        }


# ---------------------------------------------------------------------------
# Integration catalog — surfaced at /api/integrations and rendered as roadmap
# indicators in the dashboard so the product visibly anticipates real
# industrial deployment (multi-protocol connectivity = table stakes, per
# docs/MARKET_RESEARCH.md).
# ---------------------------------------------------------------------------

PLANNED_INTEGRATIONS: tuple[IntegrationInfo, ...] = (
    IntegrationInfo(
        key="simulator",
        name="Digital Twin Simulator",
        protocol="in-process",
        status="available",
        description="Physics based digital twin that streams live asset data.",
        standards=(),
    ),
    IntegrationInfo(
        key="opcua",
        name="OPC UA",
        protocol="OPC UA",
        status="planned",
        description=(
            "Connects to PLCs, SCADA and edge gateways using the standard industrial protocol."
        ),
        standards=("OPC UA", "IEC 62541"),
    ),
    IntegrationInfo(
        key="mqtt",
        name="MQTT and Sparkplug B",
        protocol="MQTT",
        status="planned",
        description=("Light messaging that streams sensor data from the edge to the cloud."),
        standards=("MQTT 5.0", "Sparkplug B"),
    ),
    IntegrationInfo(
        key="modbus",
        name="Modbus TCP",
        protocol="Modbus",
        status="planned",
        description="Reads older field devices that use Modbus.",
        standards=("Modbus TCP",),
    ),
    IntegrationInfo(
        key="historian",
        name="Process Historian (OSIsoft/AVEVA PI)",
        protocol="PI Web API",
        status="planned",
        description="Loads past data from existing plant historians.",
        standards=("AVEVA PI", "ISA-95"),
    ),
    IntegrationInfo(
        key="iso50001",
        name="ISO 50001 Energy Reporting",
        protocol="export",
        status="planned",
        description=("Energy reports ready for ISO 50001 and EU energy rules."),
        standards=("ISO 50001", "EU EED 2023/1791"),
    ),
)


def info_to_dict(info: IntegrationInfo) -> dict:
    """Serialise one catalog entry for the API/UI."""
    return {
        "key": info.key,
        "name": info.name,
        "protocol": info.protocol,
        "status": info.status,
        "description": info.description,
        "standards": list(info.standards),
    }


def get_integration_catalog() -> list[dict]:
    """Return the power-pillar integration catalog as plain dicts.

    The package-level ``integrations.get_integration_catalog`` composes this with
    the waste-pillar entries.
    """
    return [info_to_dict(i) for i in PLANNED_INTEGRATIONS]
