"""Tests for the business-impact (simulated ROI) model."""

import pytest

from simulator.business_impact import NOMINAL_EFFICIENCY, BusinessImpactModel, ImpactAssumptions
from simulator.power_system import PowerSystem


@pytest.fixture
def model() -> BusinessImpactModel:
    return BusinessImpactModel(
        assumptions=ImpactAssumptions(
            downtime_cost_per_hour=10_000.0,
            energy_tariff_per_kwh=0.10,
            grid_emission_factor_kg_per_kwh=0.5,
            unplanned_downtime_hours_per_failure=8.0,
            planned_maintenance_hours=2.0,
        ),
        simulated_hours_per_tick=1.0,
    )


class _FakeAsset:
    def __init__(self, asset_id, rated):
        self.config = type("Cfg", (), {"asset_id": asset_id, "rated_capacity": rated})()


def test_no_waste_when_healthy(model):
    asset = _FakeAsset("A1", 100.0)
    tel = {"A1": {"load": 80.0, "efficiency": NOMINAL_EFFICIENCY}}
    model.on_tick([asset], tel)
    snap = model.snapshot()
    assert snap["energy_wasted_kwh"] == 0.0
    assert snap["co2_wasted_kg"] == 0.0


def test_waste_accrues_when_degraded(model):
    asset = _FakeAsset("A1", 100.0)  # 100 kW rated
    tel = {"A1": {"load": 100.0, "efficiency": 0.76}}  # ~21% efficiency gap
    model.on_tick([asset], tel)
    snap = model.snapshot()
    assert snap["energy_wasted_kwh"] > 0
    # cost and CO2 follow the tariff / factor (abs tolerance covers field rounding).
    assert snap["energy_cost_wasted_usd"] == pytest.approx(
        snap["energy_wasted_kwh"] * 0.10, abs=0.05
    )
    assert snap["co2_wasted_kg"] == pytest.approx(snap["energy_wasted_kwh"] * 0.5, abs=0.05)


def test_predictive_catch_credits_downtime(model):
    model.on_maintenance("degraded")
    snap = model.snapshot()
    assert snap["failures_prevented"] == 1
    assert snap["downtime_hours_avoided"] == pytest.approx(6.0)  # 8 - 2
    assert snap["value_protected_usd"] == pytest.approx(60_000.0)  # 6h * $10k


def test_failed_repair_is_reactive_not_credited(model):
    model.on_maintenance("failed")
    snap = model.snapshot()
    assert snap["reactive_repairs"] == 1
    assert snap["failures_prevented"] == 0
    assert snap["value_protected_usd"] == 0.0


def test_normal_maintenance_not_credited(model):
    model.on_maintenance("normal")
    snap = model.snapshot()
    assert snap["failures_prevented"] == 0
    assert snap["value_protected_usd"] == 0.0


def test_methodology_exposes_assumptions_and_formulas(model):
    m = model.methodology()
    assert "assumptions" in m and "formulas" in m
    assert "disclaimer" in m
    assert m["assumptions"]["downtime_cost_per_hour"] == 10_000.0


def test_from_env_override(monkeypatch):
    monkeypatch.setenv("POWERSIM_IMPACT_DOWNTIME_COST_PER_HOUR", "99999")
    assumptions = ImpactAssumptions.from_env()
    assert assumptions.downtime_cost_per_hour == 99999.0


def test_integrates_with_power_system():
    ps = PowerSystem(seed=42)
    model = BusinessImpactModel(simulated_hours_per_tick=0.25)
    ps.inject_failure("P1", "overload")
    for _ in range(30):
        tel = ps.tick()
        model.on_tick(ps.get_all_assets(), {k: v.to_dict() for k, v in tel.items()})
    assert model.snapshot()["energy_wasted_kwh"] > 0
