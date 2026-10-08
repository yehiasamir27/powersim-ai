"""
MQTT / Sparkplug B telemetry source — roadmap stub.

Intended implementation (not yet built): subscribe to an MQTT broker, decode
Sparkplug B payloads (NBIRTH/DBIRTH metric definitions, NDATA/DDATA updates), and
map metrics onto PowerSim's ``TelemetryData`` shape. MQTT/Sparkplug B is the
lightweight edge-to-cloud transport half of the modern industrial stack — a
complement to OPC-UA, and table stakes for buyers (see docs/MARKET_RESEARCH.md).

A production build would target ``aiomqtt`` plus a Sparkplug B codec, with a
topic/metric → asset mapping config and last-will handling for edge-node liveness.
"""

from __future__ import annotations

from .base import IntegrationInfo, TelemetrySource


class MqttTelemetrySource(TelemetrySource):
    """Planned MQTT / Sparkplug B subscriber. Not yet implemented."""

    info = IntegrationInfo(
        key="mqtt",
        name="MQTT and Sparkplug B",
        protocol="MQTT",
        status="planned",
        description=("Light messaging that streams sensor data from the edge to the cloud."),
        standards=("MQTT 5.0", "Sparkplug B"),
    )

    def __init__(
        self,
        broker_host: str,
        broker_port: int = 1883,
        topic_prefix: str = "spBv1.0",
    ) -> None:
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.topic_prefix = topic_prefix

    async def connect(self) -> None:
        raise NotImplementedError(
            "MQTT/Sparkplug B integration is on the roadmap. The interface is "
            "defined so this becomes a connector, not a rewrite."
        )

    async def read(self) -> dict[str, dict]:
        raise NotImplementedError("MQTT/Sparkplug B integration is on the roadmap.")

    async def close(self) -> None:
        return None
