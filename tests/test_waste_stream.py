"""Tests for the waste-management simulator: classification, anomaly, compliance, 4R."""

import pytest

from simulator.waste_stream import (
    ComplianceStatus,
    RecoveryAction,
    WasteCategory,
    WasteStreamSystem,
)


def _comp(metal=0.0, plastic=0.0, organic=0.0, chemical=0.0, inert=0.0):
    return {
        "metal": metal,
        "plastic": plastic,
        "organic": organic,
        "chemical": chemical,
        "inert": inert,
    }


@pytest.fixture
def system() -> WasteStreamSystem:
    return WasteStreamSystem(seed=42)


# -- Layer 2: classification ------------------------------------------------


def test_classify_hazardous_by_chemical_threshold():
    comp = _comp(metal=0.2, plastic=0.1, chemical=0.5, inert=0.2)
    category, confidence = WasteStreamSystem.classify(comp, contamination_pct=20.0)
    assert category is WasteCategory.HAZARDOUS
    assert confidence >= 60.0


def test_classify_hazardous_by_extreme_contamination():
    comp = _comp(metal=0.5, plastic=0.3, inert=0.2)  # low chemical
    category, _ = WasteStreamSystem.classify(comp, contamination_pct=90.0)
    assert category is WasteCategory.HAZARDOUS


def test_classify_recyclable_when_clean_metal_plastic():
    comp = _comp(metal=0.6, plastic=0.25, inert=0.15)
    category, _ = WasteStreamSystem.classify(comp, contamination_pct=10.0)
    assert category is WasteCategory.RECYCLABLE


def test_classify_reusable_byproduct_when_organic_and_clean():
    comp = _comp(organic=0.75, plastic=0.05, inert=0.2)
    category, _ = WasteStreamSystem.classify(comp, contamination_pct=8.0)
    assert category is WasteCategory.REUSABLE_BYPRODUCT


def test_classify_general_fallback_for_inert_mixed():
    comp = _comp(metal=0.05, plastic=0.05, organic=0.05, inert=0.85)
    category, _ = WasteStreamSystem.classify(comp, contamination_pct=35.0)
    assert category is WasteCategory.GENERAL


def test_chemical_just_below_threshold_is_not_hazardous():
    comp = _comp(metal=0.4, plastic=0.2, chemical=0.31, inert=0.09)
    category, _ = WasteStreamSystem.classify(comp, contamination_pct=20.0)
    assert category is not WasteCategory.HAZARDOUS


# -- Layer 2: anomaly detection ---------------------------------------------


def test_volume_spike_detected(system):
    comp = _comp(metal=0.5, plastic=0.3, inert=0.2)
    for _ in range(10):
        system._weight_history["WM1"].append(100.0)
        system._composition_history["WM1"].append(comp)
    found = system.detect_anomalies("WM1", weight=400.0, composition=comp)
    assert any("Volume spike" in f for f in found)


def test_no_anomaly_on_stable_stream(system):
    comp = _comp(metal=0.5, plastic=0.3, inert=0.2)
    for _ in range(10):
        system._weight_history["WM1"].append(100.0)
        system._composition_history["WM1"].append(comp)
    assert system.detect_anomalies("WM1", weight=102.0, composition=comp) == []


def test_composition_drift_detected(system):
    stable = _comp(metal=0.6, plastic=0.2, inert=0.2)
    drifted = _comp(metal=0.1, plastic=0.1, chemical=0.6, inert=0.2)
    for _ in range(10):
        system._weight_history["WM1"].append(100.0)
        system._composition_history["WM1"].append(stable)
    found = system.detect_anomalies("WM1", weight=100.0, composition=drifted)
    assert any("Composition drift" in f for f in found)


# -- Layer 3: expert-system compliance --------------------------------------


def test_hazardous_triggers_segregation_rule():
    status, rules = WasteStreamSystem.check_compliance(
        WasteCategory.HAZARDOUS, _comp(chemical=0.6, inert=0.4), 20.0, 10.0, 100.0
    )
    assert "H-01" in rules
    assert status is ComplianceStatus.NON_COMPLIANT


def test_mixed_hazardous_in_general_stream_flagged():
    status, rules = WasteStreamSystem.check_compliance(
        WasteCategory.GENERAL, _comp(chemical=0.28, inert=0.72), 10.0, 10.0, 100.0
    )
    assert "H-02" in rules
    assert status is ComplianceStatus.NON_COMPLIANT


def test_high_contamination_is_non_compliant():
    status, rules = WasteStreamSystem.check_compliance(
        WasteCategory.RECYCLABLE, _comp(metal=0.8, inert=0.2), 75.0, 10.0, 100.0
    )
    assert "C-01" in rules
    assert status is ComplianceStatus.NON_COMPLIANT


def test_moderate_contamination_is_advisory_only():
    status, rules = WasteStreamSystem.check_compliance(
        WasteCategory.RECYCLABLE, _comp(metal=0.8, inert=0.2), 45.0, 10.0, 100.0
    )
    assert "C-02" in rules
    assert status is ComplianceStatus.ADVISORY


def test_moisture_and_weight_advisories():
    status, rules = WasteStreamSystem.check_compliance(
        WasteCategory.GENERAL, _comp(inert=1.0), 10.0, 70.0, 800.0
    )
    assert "M-01" in rules and "W-01" in rules
    assert status is ComplianceStatus.ADVISORY


def test_clean_consignment_is_compliant():
    status, rules = WasteStreamSystem.check_compliance(
        WasteCategory.RECYCLABLE, _comp(metal=0.9, inert=0.1), 5.0, 10.0, 50.0
    )
    assert rules == []
    assert status is ComplianceStatus.COMPLIANT


def test_non_compliant_outranks_advisory():
    status, rules = WasteStreamSystem.check_compliance(
        WasteCategory.HAZARDOUS, _comp(chemical=0.7, inert=0.3), 45.0, 70.0, 900.0
    )
    assert {"H-01", "C-02", "M-01", "W-01"} <= set(rules)
    assert status is ComplianceStatus.NON_COMPLIANT


# -- Layer 3: 4R recommender -------------------------------------------------


def test_hazardous_routes_to_recover():
    action, rationale = WasteStreamSystem.recommend_action(WasteCategory.HAZARDOUS, 20.0, 60.0, [])
    assert action is RecoveryAction.RECOVER
    assert "treatment" in rationale.lower()


def test_clean_recyclable_routes_to_recycle():
    action, _ = WasteStreamSystem.recommend_action(WasteCategory.RECYCLABLE, 15.0, 10.0, [])
    assert action is RecoveryAction.RECYCLE


def test_contaminated_recyclable_routes_to_reduce():
    action, _ = WasteStreamSystem.recommend_action(WasteCategory.RECYCLABLE, 70.0, 40.0, [])
    assert action is RecoveryAction.REDUCE


def test_clean_byproduct_routes_to_reuse():
    action, _ = WasteStreamSystem.recommend_action(WasteCategory.REUSABLE_BYPRODUCT, 12.0, 10.0, [])
    assert action is RecoveryAction.REUSE


def test_ordinary_general_waste_is_disposed():
    action, _ = WasteStreamSystem.recommend_action(WasteCategory.GENERAL, 20.0, 20.0, [])
    assert action is RecoveryAction.DISPOSE


def test_anomalous_general_waste_prompts_reduction():
    action, _ = WasteStreamSystem.recommend_action(
        WasteCategory.GENERAL, 20.0, 20.0, ["Volume spike: 400 kg vs 100 kg rolling mean"]
    )
    assert action is RecoveryAction.REDUCE


# -- Layer 1: generation -----------------------------------------------------


def test_tick_generates_valid_events(system):
    seen = 0
    for _ in range(40):
        for ev in system.tick({"T1": 100.0, "M1": 100.0, "G1": 100.0, "P1": 100.0}):
            seen += 1
            assert ev.weight_kg > 0
            assert 0.0 <= ev.contamination_pct <= 100.0
            assert pytest.approx(sum(ev.composition.values()), rel=1e-6) == 1.0
            assert ev.diverted_kg <= ev.weight_kg
    assert seen > 0


def test_degraded_upstream_asset_raises_contamination(system):
    healthy = WasteStreamSystem(seed=7)
    degraded = WasteStreamSystem(seed=7)
    h_vals, d_vals = [], []
    for _ in range(60):
        for ev in healthy.tick({"M1": 100.0}):
            if ev.source_id == "WM1":
                h_vals.append(ev.contamination_pct)
        for ev in degraded.tick({"M1": 25.0}):
            if ev.source_id == "WM1":
                d_vals.append(ev.contamination_pct)
    assert h_vals and d_vals
    assert sum(d_vals) / len(d_vals) > sum(h_vals) / len(h_vals)


def test_determinism_with_seed():
    a, b = WasteStreamSystem(seed=99), WasteStreamSystem(seed=99)
    health = {"T1": 90.0, "M1": 90.0, "G1": 90.0, "P1": 90.0}
    for _ in range(25):
        ea, eb = a.tick(health), b.tick(health)
        assert len(ea) == len(eb)
        for x, y in zip(ea, eb, strict=True):
            assert x.weight_kg == y.weight_kg
            assert x.category is y.category


def test_summary_totals_are_consistent(system):
    for _ in range(30):
        system.tick({"T1": 80.0, "M1": 80.0, "G1": 80.0, "P1": 80.0})
    summary = system.get_summary()
    assert summary["total_events"] > 0
    assert summary["generated_kg"] > 0
    assert 0.0 <= summary["diversion_rate_pct"] <= 100.0
    assert sum(summary["by_category"].values()) <= summary["total_events"]
