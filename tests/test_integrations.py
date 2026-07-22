"""Tests for the data-integration layer."""

import pytest

from integrations import SimulatedTelemetrySource, get_integration_catalog
from integrations.mqtt import MqttTelemetrySource
from integrations.opcua import OpcUaTelemetrySource
from simulator.power_system import PowerSystem


def test_catalog_has_available_simulator_and_planned_connectors():
    catalog = get_integration_catalog()
    by_key = {i["key"]: i for i in catalog}
    assert by_key["simulator"]["status"] == "available"
    assert by_key["opcua"]["status"] == "planned"
    assert by_key["mqtt"]["status"] == "planned"
    # OPC-UA and MQTT/Sparkplug B are represented (table-stakes protocols).
    assert "OPC-UA" in by_key["opcua"]["standards"]
    assert "Sparkplug B" in by_key["mqtt"]["standards"]


async def test_simulated_source_reads_full_fleet():
    ps = PowerSystem(seed=1)
    source = SimulatedTelemetrySource(ps)
    await source.connect()
    telemetry = await source.read()
    assert set(telemetry) == {"T1", "M1", "G1", "P1"}
    assert "temperature" in telemetry["T1"]
    await source.close()


async def test_opcua_stub_not_implemented():
    with pytest.raises(NotImplementedError):
        await OpcUaTelemetrySource("opc.tcp://localhost:4840").connect()


async def test_mqtt_stub_not_implemented():
    with pytest.raises(NotImplementedError):
        await MqttTelemetrySource("localhost").connect()
