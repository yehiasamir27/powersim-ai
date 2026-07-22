"""Simulator-backed telemetry source — the reference ``TelemetrySource``."""

from __future__ import annotations

from simulator.power_system import PowerSystem

from .base import IntegrationInfo, TelemetrySource


class SimulatedTelemetrySource(TelemetrySource):
    """Adapts the digital-twin :class:`PowerSystem` to the ``TelemetrySource`` API.

    ``read`` advances the simulation by one tick and returns the resulting
    telemetry — for a simulated source, polling *is* what produces the next
    reading. A real connector would instead fetch the latest cached values.
    """

    info = IntegrationInfo(
        key="simulator",
        name="Digital-Twin Simulator",
        protocol="in-process",
        status="available",
        description="Physics-based digital twin generating live asset telemetry.",
    )

    def __init__(self, power_system: PowerSystem) -> None:
        self.power_system = power_system
        self._connected = False

    async def connect(self) -> None:
        self._connected = True

    async def read(self) -> dict[str, dict]:
        if not self._connected:
            await self.connect()
        telemetry = self.power_system.tick()
        return {asset_id: reading.to_dict() for asset_id, reading in telemetry.items()}

    async def close(self) -> None:
        self._connected = False
