"""
Business-impact model — translates simulated maintenance events into the ROI
metrics industrial buyers actually ask for: unplanned downtime avoided, energy
wasted to degradation, cost, and CO2e.

Design principles (driven by Phase 0 market research, see docs/MARKET_RESEARCH.md):

* **Buyer-supplied inputs, never hard-coded headline ROI.** Every monetary or
  physical assumption lives in :class:`ImpactAssumptions`, is overridable via
  environment variables, and is exposed through :meth:`methodology` so the UI can
  show exactly how each number was derived.
* **Only claim what is directly computable.** The flagship figure is
  *unplanned downtime cost avoided* from genuinely predictive catches (a fault
  addressed before the asset failed). Energy figures are reported as the *waste
  the system is surfacing*, not speculative counterfactual savings.
* **Everything here is a simulated projection.** No real-world validation is
  implied; the UI must label it as such.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Any

# Efficiency of a healthy asset (matches the digital-twin telemetry model,
# where efficiency ≈ 0.96 - stress * 0.22).
NOMINAL_EFFICIENCY = 0.96


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass
class ImpactAssumptions:
    """Transparent, buyer-configurable assumptions behind every impact figure.

    Defaults are deliberately conservative, generic placeholders — a real
    deployment plugs in the operator's own line economics. Values may be
    overridden with ``POWERSIM_IMPACT_*`` environment variables.
    """

    downtime_cost_per_hour: float = 25_000.0  # USD / hour of unplanned downtime
    energy_tariff_per_kwh: float = 0.12  # USD / kWh
    grid_emission_factor_kg_per_kwh: float = 0.45  # kg CO2e / kWh (grid average)
    unplanned_downtime_hours_per_failure: float = 8.0  # avg unplanned outage per failure
    planned_maintenance_hours: float = 2.0  # planned intervention duration
    # -- waste pillar ------------------------------------------------------
    disposal_cost_per_tonne: float = 55.0  # USD / tonne landfill gate + haulage
    co2e_avoided_per_tonne_diverted_kg: float = 380.0  # kg CO2e avoided per tonne diverted
    compliance_penalty_avoided_usd: float = 2_500.0  # USD per incident caught pre-disposal

    @classmethod
    def from_env(cls) -> ImpactAssumptions:
        """Build assumptions from environment overrides (falling back to defaults)."""
        return cls(
            downtime_cost_per_hour=_env_float(
                "POWERSIM_IMPACT_DOWNTIME_COST_PER_HOUR", cls.downtime_cost_per_hour
            ),
            energy_tariff_per_kwh=_env_float(
                "POWERSIM_IMPACT_ENERGY_TARIFF_PER_KWH", cls.energy_tariff_per_kwh
            ),
            grid_emission_factor_kg_per_kwh=_env_float(
                "POWERSIM_IMPACT_GRID_EMISSION_FACTOR", cls.grid_emission_factor_kg_per_kwh
            ),
            unplanned_downtime_hours_per_failure=_env_float(
                "POWERSIM_IMPACT_UNPLANNED_DOWNTIME_HOURS",
                cls.unplanned_downtime_hours_per_failure,
            ),
            planned_maintenance_hours=_env_float(
                "POWERSIM_IMPACT_PLANNED_MAINTENANCE_HOURS", cls.planned_maintenance_hours
            ),
            disposal_cost_per_tonne=_env_float(
                "POWERSIM_IMPACT_DISPOSAL_COST_PER_TONNE", cls.disposal_cost_per_tonne
            ),
            co2e_avoided_per_tonne_diverted_kg=_env_float(
                "POWERSIM_IMPACT_CO2E_PER_TONNE_DIVERTED",
                cls.co2e_avoided_per_tonne_diverted_kg,
            ),
            compliance_penalty_avoided_usd=_env_float(
                "POWERSIM_IMPACT_COMPLIANCE_PENALTY_AVOIDED",
                cls.compliance_penalty_avoided_usd,
            ),
        )

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


@dataclass
class _Counters:
    failures_prevented: int = 0
    reactive_repairs: int = 0
    downtime_hours_avoided: float = 0.0
    energy_wasted_kwh: float = 0.0
    energy_waste_kw_now: float = 0.0
    energy_recovered_kwh: float = 0.0
    baseline_energy_kwh: float = 0.0
    # -- waste pillar --
    waste_generated_kg: float = 0.0
    waste_diverted_kg: float = 0.0
    waste_events: int = 0
    compliance_incidents_caught: int = 0
    hazardous_events: int = 0


class BusinessImpactModel:
    """Accumulates simulated business impact from digital-twin events.

    Wire-up:
        * call :meth:`on_tick` once per simulation tick with the fleet + telemetry;
        * call :meth:`on_maintenance` when an asset is restored;
        * read :meth:`snapshot` for the current metrics and :meth:`methodology`
          for the assumptions/formulas behind them.
    """

    def __init__(
        self,
        assumptions: ImpactAssumptions | None = None,
        simulated_hours_per_tick: float = 0.25,
    ) -> None:
        self.assumptions = assumptions or ImpactAssumptions.from_env()
        self.simulated_hours_per_tick = simulated_hours_per_tick
        self._c = _Counters()

    def reset(self) -> None:
        self._c = _Counters()

    # -- event hooks ------------------------------------------------------

    def on_tick(self, assets: list[Any], telemetry: dict[str, dict]) -> None:
        """Accrue energy-waste metrics for one tick.

        ``wasted_kw`` for an asset is the power lost to reduced efficiency:
        ``rated_kW * load_fraction * (nominal_eff - current_eff) / nominal_eff``.
        """
        hours = self.simulated_hours_per_tick
        waste_kw = 0.0
        baseline_kw = 0.0
        for asset in assets:
            tel = telemetry.get(asset.config.asset_id)
            if not tel:
                continue
            rated_kw = float(asset.config.rated_capacity)  # kVA ~ kW (simplifying)
            load_frac = float(tel.get("load", 0.0)) / 100.0
            eff = float(tel.get("efficiency", NOMINAL_EFFICIENCY))
            consumed_kw = rated_kw * load_frac
            eff_gap = max(0.0, (NOMINAL_EFFICIENCY - eff) / NOMINAL_EFFICIENCY)
            waste_kw += consumed_kw * eff_gap
            baseline_kw += consumed_kw
        self._c.energy_waste_kw_now = waste_kw
        self._c.energy_wasted_kwh += waste_kw * hours
        self._c.baseline_energy_kwh += baseline_kw * hours

    def on_maintenance(self, asset_prior_state: str) -> None:
        """Record a maintenance intervention, classifying it as predictive or reactive.

        A catch while ``degraded`` or ``critical`` is *predictive* — it avoids an
        unplanned failure. A repair after ``failed`` is *reactive* — no downtime
        was avoided, but the event is still tracked for honesty.
        """
        a = self.assumptions
        state = (asset_prior_state or "").lower()
        if state in {"degraded", "critical"}:
            self._c.failures_prevented += 1
            self._c.downtime_hours_avoided += max(
                0.0, a.unplanned_downtime_hours_per_failure - a.planned_maintenance_hours
            )
        elif state == "failed":
            self._c.reactive_repairs += 1

    def on_waste_event(self, event: Any) -> None:
        """Accrue waste-pillar impact from one classified waste consignment.

        Expects an object exposing ``weight_kg``, ``diverted_kg``,
        ``compliance_status`` and ``category`` (a
        :class:`simulator.waste_stream.WasteEvent`). A *compliance incident
        caught* is a non-compliant consignment flagged by the expert system
        **before** disposal — the penalty is avoided precisely because it was
        caught.
        """
        self._c.waste_events += 1
        self._c.waste_generated_kg += float(getattr(event, "weight_kg", 0.0))
        self._c.waste_diverted_kg += float(getattr(event, "diverted_kg", 0.0))
        status = getattr(getattr(event, "compliance_status", None), "value", "")
        if status == "non_compliant":
            self._c.compliance_incidents_caught += 1
        category = getattr(getattr(event, "category", None), "value", "")
        if category == "hazardous":
            self._c.hazardous_events += 1

    # -- reporting --------------------------------------------------------

    def _sustainability_scorecard(self, energy_waste_pct: float) -> dict[str, Any]:
        """Roll the four pillars into one investor-legible 0-100 ESG-style score.

        Weights are explicit and returned alongside the sub-scores so the number is
        auditable rather than a black box.
        """
        c = self._c
        interventions = c.failures_prevented + c.reactive_repairs
        reliability = 100.0 * c.failures_prevented / interventions if interventions else 100.0
        energy = max(0.0, 100.0 - energy_waste_pct)
        diversion = (
            100.0 * c.waste_diverted_kg / c.waste_generated_kg if c.waste_generated_kg > 0 else 0.0
        )
        compliance = (
            100.0 * (1.0 - c.compliance_incidents_caught / c.waste_events)
            if c.waste_events
            else 100.0
        )
        weights = {"reliability": 0.30, "energy": 0.25, "waste_diversion": 0.25, "compliance": 0.20}
        subscores = {
            "reliability": round(reliability, 1),
            "energy": round(energy, 1),
            "waste_diversion": round(diversion, 1),
            "compliance": round(compliance, 1),
        }
        score = sum(subscores[k] * w for k, w in weights.items())
        return {"score": round(score, 1), "subscores": subscores, "weights": weights}

    def snapshot(self) -> dict[str, Any]:
        """Current impact metrics. All values are simulated projections."""
        a = self.assumptions
        c = self._c
        downtime_cost_avoided = c.downtime_hours_avoided * a.downtime_cost_per_hour
        energy_cost_wasted = c.energy_wasted_kwh * a.energy_tariff_per_kwh
        co2_wasted_kg = c.energy_wasted_kwh * a.grid_emission_factor_kg_per_kwh
        waste_pct = (
            100.0 * c.energy_wasted_kwh / c.baseline_energy_kwh
            if c.baseline_energy_kwh > 0
            else 0.0
        )
        # -- waste pillar --
        diverted_tonnes = c.waste_diverted_kg / 1000.0
        disposal_cost_avoided = diverted_tonnes * a.disposal_cost_per_tonne
        waste_co2e_avoided = diverted_tonnes * a.co2e_avoided_per_tonne_diverted_kg
        compliance_value = c.compliance_incidents_caught * a.compliance_penalty_avoided_usd
        diversion_rate = (
            100.0 * c.waste_diverted_kg / c.waste_generated_kg if c.waste_generated_kg > 0 else 0.0
        )
        total_value = downtime_cost_avoided + disposal_cost_avoided + compliance_value

        return {
            "simulated": True,
            "failures_prevented": c.failures_prevented,
            "reactive_repairs": c.reactive_repairs,
            "downtime_hours_avoided": round(c.downtime_hours_avoided, 2),
            "downtime_cost_avoided_usd": round(downtime_cost_avoided, 2),
            "energy_waste_kw_now": round(c.energy_waste_kw_now, 2),
            "energy_wasted_kwh": round(c.energy_wasted_kwh, 2),
            "energy_waste_pct": round(waste_pct, 2),
            "energy_cost_wasted_usd": round(energy_cost_wasted, 2),
            "co2_wasted_kg": round(co2_wasted_kg, 1),
            # -- waste pillar --
            "waste_events": c.waste_events,
            "waste_generated_kg": round(c.waste_generated_kg, 1),
            "waste_diverted_kg": round(c.waste_diverted_kg, 1),
            "waste_diversion_rate_pct": round(diversion_rate, 1),
            "disposal_cost_avoided_usd": round(disposal_cost_avoided, 2),
            "waste_co2e_avoided_kg": round(waste_co2e_avoided, 1),
            "compliance_incidents_caught": c.compliance_incidents_caught,
            "hazardous_events": c.hazardous_events,
            "compliance_value_usd": round(compliance_value, 2),
            # -- rolled up --
            "value_protected_usd": round(total_value, 2),
            "sustainability": self._sustainability_scorecard(waste_pct),
        }

    def methodology(self) -> dict[str, Any]:
        """Human-readable derivation of every figure, for UI hover/footnote."""
        return {
            "disclaimer": (
                "All figures are simulated projections from the digital-twin demo. "
                "No real-world validation is implied. Replace the assumptions below "
                "with your own line economics for a representative estimate."
            ),
            "assumptions": self.assumptions.to_dict(),
            "formulas": {
                "downtime_cost_avoided_usd": (
                    "failures_prevented x (unplanned_downtime_hours_per_failure - "
                    "planned_maintenance_hours) x downtime_cost_per_hour. "
                    "A failure is 'prevented' when maintenance is performed while the "
                    "asset is degraded/critical — before it fails."
                ),
                "energy_wasted_kwh": (
                    "Sum over ticks of rated_kW x load_fraction x "
                    "(nominal_efficiency - current_efficiency) / nominal_efficiency, "
                    "integrated over simulated time."
                ),
                "energy_cost_wasted_usd": "energy_wasted_kwh x energy_tariff_per_kwh",
                "co2_wasted_kg": "energy_wasted_kwh x grid_emission_factor_kg_per_kwh",
                "waste_diverted_kg": (
                    "Sum over waste events of weight_kg x the diversion rate of the "
                    "recommended 4R action (reuse 0.95, recycle 0.85, recover 0.60, "
                    "reduce 0.30, dispose 0.0)."
                ),
                "disposal_cost_avoided_usd": (
                    "(waste_diverted_kg / 1000) x disposal_cost_per_tonne"
                ),
                "waste_co2e_avoided_kg": (
                    "(waste_diverted_kg / 1000) x co2e_avoided_per_tonne_diverted_kg"
                ),
                "compliance_value_usd": (
                    "compliance_incidents_caught x compliance_penalty_avoided_usd. An "
                    "incident is 'caught' when the expert system flags a non-compliant "
                    "consignment before disposal."
                ),
                "value_protected_usd": (
                    "downtime_cost_avoided_usd + disposal_cost_avoided_usd + compliance_value_usd"
                ),
                "sustainability.score": (
                    "Weighted mean of four 0-100 sub-scores — reliability 30% "
                    "(predictive share of interventions), energy 25% (100 - energy "
                    "waste %), waste diversion 25% (diverted / generated), compliance "
                    "20% (share of consignments with no non-compliance)."
                ),
            },
            "nominal_efficiency": NOMINAL_EFFICIENCY,
        }
