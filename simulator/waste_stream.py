"""
AI-driven industrial waste-management engine — the second product pillar.

Implements the four-layer pipeline described in the research foundation
(K. Mohamed, AASTMT, 2026), mirrored in simulation:

1. **Data Collection Layer** — per-source waste-stream telemetry (weight, volume,
   composition, contamination, moisture), generated physically from process load
   and upstream *asset health* rather than random noise: degrading equipment
   produces more scrap and more contaminated output, which links this pillar to
   the predictive-maintenance twin.
2. **AI Processing Layer** — a deterministic, weighted **rule-based classifier**
   (category + confidence) and a **statistical anomaly detector** (volume spike
   via rolling z-score, composition drift via L1 distance).
3. **Decision & Control Layer** — a fully-implemented **expert-system compliance
   check** (explicit, inspectable rules) plus a **4R recommender**
   (reduce / reuse / recycle / recover) with an estimated landfill-diversion rate.
4. **Output & Feedback Layer** — events feed the dashboard, the agent's reasoning
   trail, and the business-impact model.

HONESTY NOTE: the classifier here is **rule-based, not a trained ML model**. It
stands in for the CNN-based visual sorting and ensemble methods (Random Forest /
XGBoost) a production deployment would run on real camera and sensor data, and the
anomaly detector stands in for isolation-forest / autoencoder approaches. See
``docs/TECHNICAL_OVERVIEW.md`` for the production upgrade path.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from uuid import uuid4

import numpy as np

# Composition fractions tracked for every waste event (sum ≈ 1.0).
COMPOSITION_KEYS = ("metal", "plastic", "organic", "chemical", "inert")


class WasteCategory(Enum):
    """Classification output categories."""

    RECYCLABLE = "recyclable"
    HAZARDOUS = "hazardous"
    GENERAL = "general"
    REUSABLE_BYPRODUCT = "reusable_byproduct"


class ComplianceStatus(Enum):
    """Expert-system compliance verdict."""

    COMPLIANT = "compliant"
    ADVISORY = "advisory"
    NON_COMPLIANT = "non_compliant"


class RecoveryAction(Enum):
    """4R hierarchy (plus disposal as the explicit last resort)."""

    REDUCE = "reduce"
    REUSE = "reuse"
    RECYCLE = "recycle"
    RECOVER = "recover"
    DISPOSE = "dispose"


#: Fraction of mass kept out of landfill for each recommended action.
DIVERSION_RATE: dict[RecoveryAction, float] = {
    RecoveryAction.REDUCE: 0.30,  # upstream prevention on the recurring stream
    RecoveryAction.REUSE: 0.95,
    RecoveryAction.RECYCLE: 0.85,
    RecoveryAction.RECOVER: 0.60,  # energy/material recovery from treatment
    RecoveryAction.DISPOSE: 0.0,
}


@dataclass(frozen=True)
class ComplianceRule:
    """A single inspectable expert-system rule."""

    code: str
    description: str
    status: ComplianceStatus


#: The expert-system rule base. Explicit and inspectable by design — this maps to
#: the expert-systems literature (Buchanan) rather than a black-box model.
COMPLIANCE_RULES: dict[str, ComplianceRule] = {
    "H-01": ComplianceRule(
        "H-01",
        "Hazardous waste must be separated before disposal",
        ComplianceStatus.NON_COMPLIANT,
    ),
    "H-02": ComplianceRule(
        "H-02",
        "Hazardous material is mixed into normal waste",
        ComplianceStatus.NON_COMPLIANT,
    ),
    "C-01": ComplianceRule(
        "C-01",
        "Too contaminated to recycle (over 60%)",
        ComplianceStatus.NON_COMPLIANT,
    ),
    "C-02": ComplianceRule(
        "C-02",
        "High contamination (over 40%) lowers recycling value",
        ComplianceStatus.ADVISORY,
    ),
    "M-01": ComplianceRule(
        "M-01",
        "Too wet (over 55%) to recycle or recover well",
        ComplianceStatus.ADVISORY,
    ),
    "W-01": ComplianceRule(
        "W-01",
        "Over 500 kg, so an official waste record is required",
        ComplianceStatus.ADVISORY,
    ),
}


@dataclass(frozen=True)
class WasteSourceProfile:
    """Physical anchor points for one waste-generating source."""

    source_id: str
    name: str
    asset_id: str | None  # upstream power asset, if any
    base_kg_per_event: float
    composition: dict[str, float]  # healthy-state baseline fractions
    contamination_base: float  # % at full asset health
    moisture_base: float  # %
    emit_probability: float = 0.35  # chance of emitting an event per tick


@dataclass
class WasteEvent:
    """A single classified, compliance-checked waste consignment."""

    event_id: str
    timestamp: datetime
    tick: int
    source_id: str
    source_name: str
    asset_id: str | None
    weight_kg: float
    volume_m3: float
    composition: dict[str, float]
    contamination_pct: float
    moisture_pct: float
    category: WasteCategory
    classification_confidence: float
    severity: float  # 0-100
    anomalies: list[str] = field(default_factory=list)
    compliance_status: ComplianceStatus = ComplianceStatus.COMPLIANT
    triggered_rules: list[str] = field(default_factory=list)
    recommended_action: RecoveryAction = RecoveryAction.DISPOSE
    action_rationale: str = ""
    diverted_kg: float = 0.0

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp.isoformat(),
            "tick": self.tick,
            "source_id": self.source_id,
            "source_name": self.source_name,
            "asset_id": self.asset_id,
            "weight_kg": round(self.weight_kg, 1),
            "volume_m3": round(self.volume_m3, 2),
            "composition": {k: round(v, 3) for k, v in self.composition.items()},
            "contamination_pct": round(self.contamination_pct, 1),
            "moisture_pct": round(self.moisture_pct, 1),
            "category": self.category.value,
            "classification_confidence": round(self.classification_confidence, 1),
            "severity": round(self.severity, 1),
            "anomalies": self.anomalies,
            "compliance_status": self.compliance_status.value,
            "triggered_rules": [
                {"code": c, "description": COMPLIANCE_RULES[c].description}
                for c in self.triggered_rules
                if c in COMPLIANCE_RULES
            ],
            "recommended_action": self.recommended_action.value,
            "action_rationale": self.action_rationale,
            "diverted_kg": round(self.diverted_kg, 1),
        }


def _normalise(comp: dict[str, float]) -> dict[str, float]:
    total = sum(max(0.0, v) for v in comp.values()) or 1.0
    return {k: max(0.0, v) / total for k, v in comp.items()}


class WasteStreamSystem:
    """Simulates and processes industrial waste streams (layers 1-3)."""

    #: Rolling window used by the statistical anomaly detector.
    WINDOW = 20
    VOLUME_Z_THRESHOLD = 2.2
    #: Relative-deviation fallback when the rolling window has ~zero variance.
    VOLUME_FLAT_RATIO = 1.5
    DRIFT_L1_THRESHOLD = 0.28

    def __init__(self, seed: int | None = None) -> None:
        self.rng = np.random.default_rng(seed)
        self.tick_count = 0
        self.sources: dict[str, WasteSourceProfile] = {}
        self._weight_history: dict[str, deque[float]] = {}
        self._composition_history: dict[str, deque[dict[str, float]]] = {}
        self.recent_events: deque[WasteEvent] = deque(maxlen=60)
        self._totals = {"generated_kg": 0.0, "diverted_kg": 0.0, "events": 0}
        self._initialise_sources()

    # -- setup ------------------------------------------------------------

    def _initialise_sources(self) -> None:
        profiles = [
            WasteSourceProfile(
                source_id="WT1",
                name="Traction Substation",
                asset_id="T1",
                base_kg_per_event=85.0,
                # Used insulating oil / solvents — genuinely hazardous-dominant,
                # but a low-frequency stream.
                composition={
                    "metal": 0.18,
                    "plastic": 0.07,
                    "organic": 0.02,
                    "chemical": 0.55,
                    "inert": 0.18,
                },
                contamination_base=22.0,
                moisture_base=14.0,
                emit_probability=0.18,
            ),
            WasteSourceProfile(
                source_id="WM1",
                name="Motor Workshop",
                asset_id="M1",
                base_kg_per_event=140.0,
                composition={
                    "metal": 0.62,
                    "plastic": 0.12,
                    "organic": 0.03,
                    "chemical": 0.15,
                    "inert": 0.08,
                },
                contamination_base=18.0,
                moisture_base=10.0,
                emit_probability=0.38,
            ),
            WasteSourceProfile(
                source_id="WG1",
                name="Signalling Power Room",
                asset_id="G1",
                base_kg_per_event=95.0,
                # Filters, gaskets and some used oil — tips hazardous only as the
                # upstream generator degrades.
                composition={
                    "metal": 0.34,
                    "plastic": 0.14,
                    "organic": 0.06,
                    "chemical": 0.24,
                    "inert": 0.22,
                },
                contamination_base=25.0,
                moisture_base=16.0,
                emit_probability=0.30,
            ),
            WasteSourceProfile(
                source_id="WP1",
                name="Cooling System",
                asset_id="P1",
                base_kg_per_event=70.0,
                composition={
                    "metal": 0.17,
                    "plastic": 0.34,
                    "organic": 0.12,
                    "chemical": 0.14,
                    "inert": 0.23,
                },
                contamination_base=30.0,
                moisture_base=38.0,
                emit_probability=0.32,
            ),
            WasteSourceProfile(
                source_id="WPL1",
                name="Train Depot",
                asset_id=None,
                base_kg_per_event=320.0,
                composition={
                    "metal": 0.10,
                    "plastic": 0.34,
                    "organic": 0.40,
                    "chemical": 0.04,
                    "inert": 0.12,
                },
                contamination_base=20.0,
                moisture_base=32.0,
                emit_probability=0.45,
            ),
        ]
        for p in profiles:
            self.sources[p.source_id] = p
            self._weight_history[p.source_id] = deque(maxlen=self.WINDOW)
            self._composition_history[p.source_id] = deque(maxlen=self.WINDOW)

    # -- Layer 1: data collection ----------------------------------------

    def tick(self, asset_health: dict[str, float] | None = None) -> list[WasteEvent]:
        """Advance one tick and return the waste events generated.

        Args:
            asset_health: optional map of ``asset_id -> observed health (0-100)``.
                Degrading upstream equipment increases scrap volume and
                contamination, coupling this pillar to the maintenance twin.
        """
        self.tick_count += 1
        asset_health = asset_health or {}
        events: list[WasteEvent] = []

        for source in self.sources.values():
            if self.rng.random() > source.emit_probability:
                continue
            health = asset_health.get(source.asset_id or "", 100.0)
            events.append(self._generate_event(source, health))

        for ev in events:
            self.recent_events.appendleft(ev)
            self._totals["generated_kg"] += ev.weight_kg
            self._totals["diverted_kg"] += ev.diverted_kg
            self._totals["events"] += 1
        return events

    def _generate_event(self, source: WasteSourceProfile, health: float) -> WasteEvent:
        """Generate one physically-motivated waste consignment."""
        # Process stress rises as the upstream asset degrades (0 healthy .. 1 failed).
        stress = float(np.clip(1.0 - health / 100.0, 0.0, 1.0))

        # Volume: baseline + load noise, amplified by upstream degradation; rare surge.
        surge = 2.4 if self.rng.random() < 0.05 else 1.0
        weight = float(
            max(
                5.0,
                source.base_kg_per_event
                * (1.0 + 0.55 * stress)
                * (1.0 + self.rng.normal(0, 0.16))
                * surge,
            )
        )
        # Bulk density varies with composition; organics/plastics are bulkier.
        density = 260.0 + 240.0 * source.composition["metal"]
        volume = weight / density

        # Composition drifts toward chemical/contaminant fractions under stress.
        comp = {k: source.composition[k] for k in COMPOSITION_KEYS}
        comp["chemical"] += 0.18 * stress
        comp["metal"] += 0.06 * stress  # accelerated wear sheds metal
        comp = {k: v + float(self.rng.normal(0, 0.025)) for k, v in comp.items()}
        comp = _normalise(comp)

        contamination = float(
            np.clip(
                source.contamination_base + 38.0 * stress + self.rng.normal(0, 4.0),
                0.0,
                100.0,
            )
        )
        moisture = float(np.clip(source.moisture_base + self.rng.normal(0, 5.0), 0.0, 100.0))

        # -- Layer 2: AI processing (classification + anomaly detection) --
        category, confidence = self.classify(comp, contamination)
        anomalies = self.detect_anomalies(source.source_id, weight, comp)
        self._weight_history[source.source_id].append(weight)
        self._composition_history[source.source_id].append(comp)

        severity = self._severity(comp, contamination, category, anomalies)

        # -- Layer 3: decision & control (compliance + 4R) ----------------
        status, rules = self.check_compliance(category, comp, contamination, moisture, weight)
        action, rationale = self.recommend_action(category, contamination, severity, anomalies)
        diverted = weight * DIVERSION_RATE[action]

        return WasteEvent(
            event_id=str(uuid4())[:8],
            timestamp=datetime.now(),
            tick=self.tick_count,
            source_id=source.source_id,
            source_name=source.name,
            asset_id=source.asset_id,
            weight_kg=weight,
            volume_m3=volume,
            composition=comp,
            contamination_pct=contamination,
            moisture_pct=moisture,
            category=category,
            classification_confidence=confidence,
            severity=severity,
            anomalies=anomalies,
            compliance_status=status,
            triggered_rules=rules,
            recommended_action=action,
            action_rationale=rationale,
            diverted_kg=diverted,
        )

    # -- Layer 2: classification ------------------------------------------

    #: Chemical mass fraction at or above which a consignment is classified
    #: hazardous — an explicit, inspectable regulatory-style threshold rather than
    #: a learned boundary.
    HAZARDOUS_CHEMICAL_THRESHOLD = 0.32

    @classmethod
    def classify(
        cls, composition: dict[str, float], contamination_pct: float
    ) -> tuple[WasteCategory, float]:
        """Weighted rule-based classifier → (category, confidence 0-100).

        Hazardous is decided by an explicit threshold gate (chemical fraction or
        extreme contamination); the remaining categories are chosen by weighted
        score. NOT a trained model: this is a deterministic function standing in
        for CNN visual sorting / RF-XGBoost ensembles on real sensor data.
        """
        metal = composition.get("metal", 0.0)
        plastic = composition.get("plastic", 0.0)
        organic = composition.get("organic", 0.0)
        chemical = composition.get("chemical", 0.0)
        clean = 1.0 - contamination_pct / 100.0

        if chemical >= cls.HAZARDOUS_CHEMICAL_THRESHOLD or contamination_pct > 85.0:
            over = chemical - cls.HAZARDOUS_CHEMICAL_THRESHOLD
            confidence = float(np.clip(66.0 + over * 160.0, 60.0, 99.0))
            return WasteCategory.HAZARDOUS, confidence

        scores = {
            WasteCategory.RECYCLABLE: (metal + plastic) * 1.25 * clean,
            WasteCategory.REUSABLE_BYPRODUCT: organic * 1.35 * clean,
            WasteCategory.GENERAL: 0.34 + contamination_pct / 260.0,
        }
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        best, best_score = ranked[0]
        runner_score = ranked[1][1]
        margin = (best_score - runner_score) / (best_score or 1.0)
        confidence = float(np.clip(55.0 + margin * 100.0, 40.0, 99.0))
        return best, confidence

    # -- Layer 2: anomaly detection ---------------------------------------

    def detect_anomalies(
        self, source_id: str, weight: float, composition: dict[str, float]
    ) -> list[str]:
        """Statistical anomaly detection (volume spike + composition drift).

        Stands in for isolation-forest / autoencoder detection in production.
        """
        found: list[str] = []
        weights = self._weight_history.get(source_id)
        if weights and len(weights) >= 5:
            arr = np.array(weights, dtype=float)
            mean, std = float(arr.mean()), float(arr.std())
            # Z-score when the stream has variance; fall back to a relative
            # deviation test when it is (near-)constant, where a z-score is
            # undefined but a large jump is still clearly anomalous.
            spike = (
                (weight - mean) / std > self.VOLUME_Z_THRESHOLD
                if std > 1e-6
                else weight > mean * self.VOLUME_FLAT_RATIO
            )
            if spike:
                found.append(f"Volume spike: {weight:.0f} kg vs {mean:.0f} kg usual")
        comps = self._composition_history.get(source_id)
        if comps and len(comps) >= 5:
            baseline = {k: float(np.mean([c[k] for c in comps])) for k in COMPOSITION_KEYS}
            l1 = sum(abs(composition[k] - baseline[k]) for k in COMPOSITION_KEYS)
            if l1 > self.DRIFT_L1_THRESHOLD:
                found.append(f"Composition drift: the mix changed by {l1:.2f}")
        return found

    @staticmethod
    def _severity(
        composition: dict[str, float],
        contamination_pct: float,
        category: WasteCategory,
        anomalies: list[str],
    ) -> float:
        """0-100 severity blending hazard content, contamination and anomalies."""
        severity = contamination_pct * 0.55 + composition.get("chemical", 0.0) * 55.0
        if category is WasteCategory.HAZARDOUS:
            severity += 18.0
        severity += 8.0 * len(anomalies)
        return float(np.clip(severity, 0.0, 100.0))

    # -- Layer 3: expert-system compliance --------------------------------

    @staticmethod
    def check_compliance(
        category: WasteCategory,
        composition: dict[str, float],
        contamination_pct: float,
        moisture_pct: float,
        weight_kg: float,
    ) -> tuple[ComplianceStatus, list[str]]:
        """Fully-implemented rule-based compliance check.

        Returns the worst status triggered and the list of rule codes fired.
        """
        fired: list[str] = []
        chemical = composition.get("chemical", 0.0)

        if category is WasteCategory.HAZARDOUS:
            fired.append("H-01")
        elif chemical > 0.25:
            # Hazardous content riding inside a non-hazardous stream.
            fired.append("H-02")

        if contamination_pct > 60.0:
            fired.append("C-01")
        elif contamination_pct > 40.0:
            fired.append("C-02")

        if moisture_pct > 55.0:
            fired.append("M-01")

        if weight_kg > 500.0:
            fired.append("W-01")

        status = ComplianceStatus.COMPLIANT
        for code in fired:
            rule_status = COMPLIANCE_RULES[code].status
            if rule_status is ComplianceStatus.NON_COMPLIANT:
                status = ComplianceStatus.NON_COMPLIANT
            elif rule_status is ComplianceStatus.ADVISORY and status is ComplianceStatus.COMPLIANT:
                status = ComplianceStatus.ADVISORY
        return status, fired

    # -- Layer 3: 4R optimisation -----------------------------------------

    @staticmethod
    def recommend_action(
        category: WasteCategory,
        contamination_pct: float,
        severity: float,
        anomalies: list[str],
    ) -> tuple[RecoveryAction, str]:
        """Simplified 4R recommender → (action, rationale).

        A production system would solve this as a graph/route optimisation over
        facilities, transport cost and market prices (AIHIF-style); see
        docs/TECHNICAL_OVERVIEW.md.
        """
        if category is WasteCategory.HAZARDOUS:
            return (
                RecoveryAction.RECOVER,
                "Hazardous. Send to licensed treatment to recover material or energy.",
            )
        if category is WasteCategory.REUSABLE_BYPRODUCT and contamination_pct <= 40.0:
            return (
                RecoveryAction.REUSE,
                "Clean byproduct. Reuse it as raw material.",
            )
        if category is WasteCategory.RECYCLABLE:
            if contamination_pct <= 40.0:
                return (
                    RecoveryAction.RECYCLE,
                    "Clean recyclable material. Send it to recycling.",
                )
            return (
                RecoveryAction.REDUCE,
                "Too dirty to recycle. Fix sorting at the source.",
            )
        if anomalies or severity > 55.0:
            return (
                RecoveryAction.REDUCE,
                "Unusual amount of waste. Check the process that made it.",
            )
        return (
            RecoveryAction.DISPOSE,
            "Mixed waste with no reuse option. Dispose of it safely.",
        )

    # -- reporting --------------------------------------------------------

    def get_summary(self) -> dict:
        """Fleet-level waste summary for the API/dashboard."""
        events = list(self.recent_events)
        by_category = {c.value: 0 for c in WasteCategory}
        non_compliant = 0
        for ev in events:
            by_category[ev.category.value] += 1
            if ev.compliance_status is ComplianceStatus.NON_COMPLIANT:
                non_compliant += 1
        generated = self._totals["generated_kg"]
        diverted = self._totals["diverted_kg"]
        return {
            "tick_count": self.tick_count,
            "total_events": self._totals["events"],
            "generated_kg": round(generated, 1),
            "diverted_kg": round(diverted, 1),
            "diversion_rate_pct": round(100.0 * diverted / generated, 1) if generated else 0.0,
            "by_category": by_category,
            "non_compliant_recent": non_compliant,
            "sources": [
                {"source_id": s.source_id, "name": s.name, "asset_id": s.asset_id}
                for s in self.sources.values()
            ],
        }

    def get_recent_events(self, limit: int = 20) -> list[dict]:
        return [e.to_dict() for e in list(self.recent_events)[:limit]]
