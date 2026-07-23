"""
Waste-pillar production data sources — roadmap stubs.

Mirrors the ``TelemetrySource`` pattern used for the power pillar: an explicit
contract plus clearly-labelled stubs, so a real deployment is a connector rather
than a rewrite. Nothing here fakes an integration — every stub raises
``NotImplementedError`` with a pointer to the roadmap.

Intended production sources (see docs/TECHNICAL_OVERVIEW.md):

* **IoT waste sensors** — smart-bin fill level, load cells / weighbridges,
  moisture and gas sensors on skips and compactors.
* **RFID / smart-bin / conveyor cameras** — consignment identity plus the frame
  stream a CNN visual-sorting model would classify in production.
* **ERP / MES** — production orders and batch context, so waste can be attributed
  to a job, line, shift and material input.
* **Regulatory & market feeds** — hazardous-waste manifest rules, permitted
  disposal routes, and secondary-material market prices for 4R optimisation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from .base import IntegrationInfo


class WasteEventSource(ABC):
    """Abstract source of waste-consignment events.

    ``read`` returns a list of waste-event dicts in the same shape the simulator
    produces (see ``simulator.waste_stream.WasteEvent.to_dict``), so the
    classification, compliance and 4R layers are source-agnostic.
    """

    info: IntegrationInfo

    @abstractmethod
    async def connect(self) -> None:
        """Establish the connection. Idempotent."""

    @abstractmethod
    async def read(self) -> list[dict]:
        """Return newly-observed waste consignments."""

    @abstractmethod
    async def close(self) -> None:
        """Release resources. Idempotent."""

    def describe(self) -> dict:
        i = self.info
        return {
            "key": i.key,
            "name": i.name,
            "protocol": i.protocol,
            "status": i.status,
            "description": i.description,
            "standards": list(i.standards),
        }


class _PlannedWasteSource(WasteEventSource):
    """Shared behaviour for not-yet-implemented waste connectors."""

    def __init__(self, endpoint: str = "") -> None:
        self.endpoint = endpoint

    async def connect(self) -> None:
        raise NotImplementedError(
            f"{self.info.name} integration is on the roadmap. The WasteEventSource "
            "interface is defined so this becomes a connector, not a rewrite — see "
            "docs/TECHNICAL_OVERVIEW.md."
        )

    async def read(self) -> list[dict]:
        raise NotImplementedError(f"{self.info.name} integration is on the roadmap.")

    async def close(self) -> None:
        return None


class IoTWasteSensorSource(_PlannedWasteSource):
    """Planned smart-bin / weighbridge / moisture sensor ingest."""

    info = IntegrationInfo(
        key="waste_iot",
        name="IoT Waste Sensors",
        protocol="MQTT / HTTP",
        status="planned",
        description=(
            "Smart-bin fill level, load-cell weight, moisture and gas sensors on "
            "skips, compactors and weighbridges."
        ),
        standards=("MQTT 5.0", "LoRaWAN"),
    )


class SmartBinCameraSource(_PlannedWasteSource):
    """Planned RFID + conveyor-camera ingest (feeds production CV sorting)."""

    info = IntegrationInfo(
        key="waste_vision",
        name="RFID / Conveyor Vision",
        protocol="RTSP / RFID",
        status="planned",
        description=(
            "Consignment identity via RFID plus conveyor/bin camera frames — the "
            "input a production CNN visual-sorting model would classify."
        ),
        standards=("ISO 18000-6C", "RTSP"),
    )


class ErpMesSource(_PlannedWasteSource):
    """Planned ERP/MES context ingest for waste attribution."""

    info = IntegrationInfo(
        key="waste_erp",
        name="ERP / MES Context",
        protocol="REST / OData",
        status="planned",
        description=(
            "Production orders, batches, shifts and material inputs so waste is "
            "attributable to a job and line."
        ),
        standards=("ISA-95", "OData"),
    )


class RegulatoryFeedSource(_PlannedWasteSource):
    """Planned regulatory + secondary-material market feed."""

    info = IntegrationInfo(
        key="waste_regulatory",
        name="Regulatory & Market Feeds",
        protocol="REST",
        status="planned",
        description=(
            "Hazardous-waste manifest rules, permitted disposal routes and "
            "secondary-material prices to drive 4R route optimisation."
        ),
        standards=("Basel Convention", "Egypt Law 202/2020"),
    )


#: Catalog entries contributed by the waste pillar.
WASTE_INTEGRATIONS: tuple[IntegrationInfo, ...] = (
    IoTWasteSensorSource.info,
    SmartBinCameraSource.info,
    ErpMesSource.info,
    RegulatoryFeedSource.info,
)
