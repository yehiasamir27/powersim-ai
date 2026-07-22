"""
OPC-UA telemetry source — roadmap stub.

Intended implementation (not yet built): connect to an OPC-UA server (PLC, SCADA,
or edge gateway), browse/subscribe to the configured node ids, and map incoming
DataValues onto PowerSim's ``TelemetryData`` shape. OPC-UA is the de-facto
vendor-independent industrial interoperability standard (IEC 62541) and is table
stakes for industrial buyers — see docs/MARKET_RESEARCH.md.

A production build would layer on: certificate-based security, subscription
back-pressure handling, and a node-id → asset/metric mapping config. Targeting the
``asyncua`` library.
"""

from __future__ import annotations

from .base import IntegrationInfo, TelemetrySource


class OpcUaTelemetrySource(TelemetrySource):
    """Planned OPC-UA client. Not yet implemented."""

    info = IntegrationInfo(
        key="opcua",
        name="OPC-UA",
        protocol="OPC-UA",
        status="planned",
        description=("Vendor-independent OPC-UA client for PLCs, SCADA and edge gateways."),
        standards=("OPC-UA", "IEC 62541"),
    )

    def __init__(self, endpoint_url: str, node_map: dict[str, dict] | None = None) -> None:
        self.endpoint_url = endpoint_url
        self.node_map = node_map or {}

    async def connect(self) -> None:
        raise NotImplementedError(
            "OPC-UA integration is on the roadmap. Track progress in "
            "docs/TECHNICAL_OVERVIEW.md; the interface is defined so this becomes a "
            "connector, not a rewrite."
        )

    async def read(self) -> dict[str, dict]:
        raise NotImplementedError("OPC-UA integration is on the roadmap.")

    async def close(self) -> None:
        return None
