"""
Pydantic request/response models for the PowerSim AI API.

Centralising validation here keeps the transport layer thin and gives every
endpoint typed, self-documenting, automatically-validated inputs (surfaced in the
OpenAPI docs at ``/docs``).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

FailureType = Literal[
    "bearing_wear",
    "insulation_breakdown",
    "oil_degradation",
    "misalignment",
    "overload",
]


class InjectFailureRequest(BaseModel):
    """Inject a developing fault into an asset (demo control)."""

    asset_id: str = Field(..., min_length=1, max_length=16, examples=["M1"])
    failure_type: FailureType = Field(..., examples=["bearing_wear"])


class AssetRequest(BaseModel):
    """A request that targets a single asset."""

    asset_id: str = Field(..., min_length=1, max_length=16, examples=["T1"])


class DeferRequest(BaseModel):
    """Defer a work order with an optional reason."""

    reason: str = Field(default="", max_length=500)


class ImpactAssumptionsUpdate(BaseModel):
    """Buyer-supplied ROI inputs for the business-impact model.

    All fields optional; only provided values are updated. This is the honest
    'plug in your own line economics' path the market research calls for.
    """

    downtime_cost_per_hour: float | None = Field(default=None, ge=0, le=1e9)
    energy_tariff_per_kwh: float | None = Field(default=None, ge=0, le=100)
    grid_emission_factor_kg_per_kwh: float | None = Field(default=None, ge=0, le=10)
    unplanned_downtime_hours_per_failure: float | None = Field(default=None, ge=0, le=1000)
    planned_maintenance_hours: float | None = Field(default=None, ge=0, le=1000)


class ContactRequest(BaseModel):
    """'Request a demo / talk to us' submission from the marketing site.

    Captured server-side (logged) — no third-party data egress. The founder wires
    this to their preferred CRM/email; see docs/TECHNICAL_OVERVIEW.md.
    """

    name: str = Field(..., min_length=1, max_length=120)
    email: str = Field(..., min_length=3, max_length=200)
    company: str = Field(default="", max_length=200)
    message: str = Field(..., min_length=1, max_length=4000)
