"""Tests for the digital-twin physics engine."""

from simulator.power_system import (
    FAILURE_SIGNATURES,
    AssetOperationalState,
    PowerSystem,
)


def _run(ps: PowerSystem, n: int):
    tel = {}
    for _ in range(n):
        tel = ps.tick()
    return tel


def test_initial_fleet(power_system: PowerSystem):
    assert set(power_system.assets) == {"T1", "M1", "G1", "P1"}
    for asset in power_system.get_all_assets():
        assert asset.true_health == 100.0
        assert asset.operating_state is AssetOperationalState.NORMAL


def test_health_degrades_monotonically_without_intervention(power_system: PowerSystem):
    start = power_system.assets["P1"].true_health
    _run(power_system, 100)
    assert power_system.assets["P1"].true_health < start
    # Degradation is strictly non-increasing tick to tick (no random recovery).
    prev = power_system.assets["P1"].true_health
    for _ in range(20):
        power_system.tick()
        now = power_system.assets["P1"].true_health
        assert now <= prev + 1e-9
        prev = now


def test_inject_failure_applies_impact_and_mode(power_system: PowerSystem):
    _run(power_system, 5)
    before = power_system.assets["M1"].true_health
    assert power_system.inject_failure("M1", "bearing_wear") is True
    after = power_system.assets["M1"].true_health
    expected_drop = FAILURE_SIGNATURES["bearing_wear"].health_impact
    assert before - after == expected_drop
    assert power_system.assets["M1"].failure_mode == "bearing_wear"


def test_inject_failure_rejects_unknown(power_system: PowerSystem):
    assert power_system.inject_failure("M1", "not_a_failure") is False
    assert power_system.inject_failure("NOPE", "bearing_wear") is False


def test_bearing_fault_raises_vibration(power_system: PowerSystem):
    _run(power_system, 5)
    nominal_vib = power_system.assets["M1"].config.sensors.nominal_vibration
    power_system.inject_failure("M1", "bearing_wear")
    tel = _run(power_system, 20)
    assert tel["M1"].vibration > nominal_vib * 1.5


def test_overload_fault_raises_temperature_and_current(power_system: PowerSystem):
    _run(power_system, 5)
    baseline = power_system.tick()["G1"]
    power_system.inject_failure("G1", "overload")
    tel = _run(power_system, 20)
    assert tel["G1"].temperature > baseline.temperature
    assert tel["G1"].current > baseline.current


def test_maintenance_restores_and_clears_fault(power_system: PowerSystem):
    _run(power_system, 5)
    power_system.inject_failure("P1", "oil_degradation")
    _run(power_system, 30)
    assert power_system.perform_maintenance("P1") is True
    asset = power_system.assets["P1"]
    assert asset.failure_mode is None
    assert asset.true_health >= 75.0
    # Estimate is snapped up on maintenance so the UI recovers promptly.
    assert asset.estimated_health >= 70.0


def test_rul_positive_and_shrinks_under_fault(power_system: PowerSystem):
    tel = _run(power_system, 10)
    healthy_rul = tel["M1"].rul_hours
    assert healthy_rul > 0
    power_system.inject_failure("M1", "overload")
    tel = _run(power_system, 25)
    assert tel["M1"].rul_hours >= 0
    assert tel["M1"].rul_hours < healthy_rul


def test_estimate_tracks_truth_when_healthy(power_system: PowerSystem):
    _run(power_system, 40)
    for asset in power_system.get_all_assets():
        assert abs(asset.estimated_health - asset.true_health) < 8.0


def test_operating_state_follows_estimated_health(power_system: PowerSystem):
    asset = power_system.assets["T1"]
    asset.estimated_health = 100.0
    power_system._update_operating_state(asset)
    assert asset.operating_state is AssetOperationalState.NORMAL
    asset.estimated_health = 50.0
    power_system._update_operating_state(asset)
    assert asset.operating_state is AssetOperationalState.DEGRADED
    asset.estimated_health = asset.config.critical_threshold - 1
    power_system._update_operating_state(asset)
    assert asset.operating_state is AssetOperationalState.CRITICAL
    asset.estimated_health = asset.config.failure_threshold - 1
    power_system._update_operating_state(asset)
    assert asset.operating_state is AssetOperationalState.FAILED


def test_under_maintenance_pauses_degradation(power_system: PowerSystem):
    power_system.set_under_maintenance("T1", True)
    health_before = power_system.assets["T1"].true_health
    _run(power_system, 30)
    assert power_system.assets["T1"].true_health == health_before


def test_determinism_with_seed():
    a = PowerSystem(seed=123)
    b = PowerSystem(seed=123)
    for _ in range(50):
        ta = a.tick()
        tb = b.tick()
        for aid in ta:
            assert ta[aid].temperature == tb[aid].temperature
            assert ta[aid].vibration == tb[aid].vibration


def test_state_summary_shape(power_system: PowerSystem):
    _run(power_system, 5)
    summary = power_system.get_state_summary()
    assert summary["tick_count"] == 5
    assert 0 <= summary["overall_health"] <= 100
    assert len(summary["assets"]) == 4
    assert summary["min_rul_hours"] is not None


def test_telemetry_history_is_bounded(power_system: PowerSystem):
    _run(power_system, 200)
    history = power_system.get_telemetry_history("T1", max_points=1000)
    assert len(history) <= power_system._history_limit
