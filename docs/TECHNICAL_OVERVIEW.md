# PowerSim AI — Technical Overview

A due-diligence-oriented tour of the architecture, the reasoning behind the key
design decisions, the path from simulation to real industrial telemetry, and the
security/data-handling considerations for a real deployment.

> All current data is **simulated**. This document describes the architecture and
> the intended production path, and is explicit about what is built vs. planned.

---

## 1. System architecture

PowerSim AI is deliberately layered so the **agentic core is independent of both
the data source and the web framework**.

```
Telemetry source(s)  ──▶  SimulationService  ──▶  FastAPI (REST + WebSocket)  ──▶  UI
  simulator (built)         (application core)        (transport only)          site/dashboard/pitch
  OPC-UA / MQTT (planned)   twin · agent · queue
                            · business impact
```

| Layer | Module(s) | Responsibility |
|---|---|---|
| **Config** | `config.py` | Env-driven `pydantic-settings`; no hard-coded hosts/ports/models. |
| **Observability** | `logging_config.py` | Structured console/JSON logging; no `print`. |
| **Domain — twin** | `simulator/power_system.py` | Physics: latent health, sensor generation, health estimation, RUL. |
| **Domain — maintenance** | `simulator/maintenance.py` | Work-order lifecycle + prioritised queue. |
| **Domain — waste** | `simulator/waste_stream.py` | Waste telemetry, classification, anomaly detection, expert-system compliance, 4R routing. |
| **Domain — impact** | `simulator/business_impact.py` | Simulated ROI (downtime/energy/CO₂/waste), sustainability score, buyer-configurable. |
| **Agent** | `ai_agent/agent.py`, `ai_agent/waste_agent.py` | Sense → think → act for both pillars; LLM-or-rules; reasoning trail. |
| **Integrations** | `integrations/` | `TelemetrySource` + `WasteEventSource` contracts, simulator impl, and OPC-UA/MQTT/IoT/vision/ERP/regulatory stubs. |
| **Core** | `simulation_service.py` | Orchestrates the loops; owns all mutable state. Imports **no** FastAPI. |
| **Transport** | `main.py`, `schemas.py` | HTTP/WebSocket, validation, CORS, static hosting. |

Two background loops run in the app:

1. **Telemetry loop** (`SimulationService.advance_telemetry`) — advances the twin one tick, updates the impact model, broadcasts a `tick` frame. Fast and non-blocking.
2. **Agent loop** (`SimulationService.run_agent_pass`) — runs the sense→think→act pass over the fleet, creates work orders idempotently, broadcasts an `agent` frame. Decoupled so a slow LLM call never stalls telemetry streaming.

## 2. Why a digital twin *and* an agent

**The digital twin** models each asset's **latent health** as the ground truth that
drives degradation and failure signatures. Crucially, health is **not** read out
directly — telemetry (temperature, vibration, etc.) is generated from the latent
state, and a separate **sensor-fusion estimate** infers health *back* from those
sensors. This mirrors reality: a real system never observes true condition; it
*infers* it. The status badge, health bar, RUL, and agent all consume the same
observed estimate, so they never disagree — a bug the earlier prototype had.

**The agent** turns inference into decisions. The agentic framing (sense → think →
act) matters because the market is shifting from *analytics that inform* to *agents
that execute* (Schneider/Cognite, Siemens, Honeywell — see market research). The
agent:

- runs a deterministic **rule engine** (scored risk model) every cycle, and
- optionally overlays **LLM reasoning** (via Ollama) for richer narrative, throttled to control cost,
- always emitting a **reasoning trail** and an honest **mode** (`llm` / `rules` / `llm_unavailable` / `llm_error` / `llm_disabled`).

The rule engine is the safety floor: the product is fully functional and
explainable with no LLM at all, which matters for air-gapped OT environments.

### Remaining Useful Life (RUL)

RUL is projected from the observed health trajectory and the effective per-tick
degradation rate (including any active fault multiplier). Uncertainty-aware RUL is
a named market differentiator; the current estimate is deterministic, with
learned/uncertainty-quantified models on the roadmap.

## 3. Data model & contracts

- **Telemetry** is a flat dict (`TelemetryData.to_dict()`) so every layer — agent,
  API, UI — consumes one shape regardless of origin.
- **`TelemetrySource`** (`integrations/base.py`) is the abstraction that decouples
  the core from the data origin:

  ```python
  class TelemetrySource(ABC):
      async def connect(self) -> None: ...
      async def read(self) -> dict[str, dict]:   # asset_id -> telemetry
      async def close(self) -> None: ...
  ```

  `SimulatedTelemetrySource` is the working implementation; `OpcUaTelemetrySource`
  and `MqttTelemetrySource` are stubs that raise `NotImplementedError` with a clear
  roadmap note. **Swapping simulation for a real plant is implementing this one
  interface** — not re-architecting.

## 4. The waste pillar — what is simulated vs. what production requires

The second pillar implements a four-layer pipeline (`simulator/waste_stream.py`,
`ai_agent/waste_agent.py`), deliberately reusing the power pillar's patterns: the
same risk-scored decision progression, the same `reasoning_trail` shape, the same
business-impact model, and the same "honest stub" integration approach.

| Layer | Implementation today | What a production deployment requires |
|---|---|---|
| **1 · Data collection** | Physically-motivated synthetic telemetry (weight, volume, composition, contamination, moisture) driven by process load **and upstream asset health** — degrading equipment produces more contaminated scrap. | Real IoT sensors: load cells/weighbridges, smart-bin fill level, moisture and gas sensors; RFID for consignment identity; conveyor/bin cameras. |
| **2 · AI processing** | **Rule-based classifier**: an explicit hazardous threshold gate (chemical mass fraction ≥ 0.32, or contamination > 85%) plus a weighted score across the remaining categories. **Statistical anomaly detection**: rolling z-score for volume spikes (with a relative-deviation fallback for near-zero-variance windows) and L1 distance for composition drift. | **CNN-based visual sorting** on camera frames and **ensemble models (Random Forest / XGBoost)** over tabular sensor features, trained on real labelled waste datasets. **Isolation Forest / autoencoder** unsupervised anomaly detection. |
| **3 · Decision & control** | **Expert-system compliance layer — fully implemented**, not stubbed: an explicit, inspectable rule base (`H-01`, `H-02`, `C-01`, `C-02`, `M-01`, `W-01`) with worst-status precedence. **Simplified 4R recommender** (reduce/reuse/recycle/recover) keyed on category, contamination, severity and anomalies. | The expert system carries over largely as-is — that is the point of rule-based compliance (it maps to the expert-systems literature, e.g. Buchanan, and stays auditable). Extend with jurisdiction-specific rule packs. The 4R step becomes an **AIHIF-style graph-theory / ML route optimisation** across facilities, transport cost, processing capacity and secondary-material market prices. |
| **4 · Output & feedback** | Dashboard panel, shared why-trail, and business-impact accrual (diversion, disposal cost avoided, incidents caught, CO₂e) plus a weighted sustainability score. | Same surfaces, plus a **continuous-learning loop** — operator corrections on classification and disposal outcomes fed back as labels to retrain the models. *Documented as roadmap; not built.* |

> **Stated plainly:** the classifier in this repository is a deterministic scoring
> function, **not a trained machine-learning model**, and the anomaly detector is a
> rolling statistic, not a learned density model. Nothing in the code or UI claims
> otherwise. The compliance layer, by contrast, is genuinely production-shaped.

### Production integration path (stubs, not fake integrations)

`integrations/waste_sources.py` defines a `WasteEventSource` contract mirroring
`TelemetrySource`, with four clearly-labelled stubs that raise `NotImplementedError`:
**IoT waste sensors** (MQTT/LoRaWAN), **RFID / conveyor vision** (RTSP + ISO 18000-6C),
**ERP / MES context** (ISA-95, OData — attributing waste to a job, line and shift), and
**regulatory & market feeds** (manifest rules, permitted routes, secondary-material
prices). Real ingest is implementing one interface, not re-architecting.

### Egyptian deployment context (plan, not promise)

- **Short term** — single-facility pilot with basic sensors and ML classification, run alongside the predictive-maintenance pillar already built.
- **Medium term** — multi-site scaling with maintenance and waste operating together, sharing one impact model and one compliance rule base.
- **Long term** — full AIHIF-style implementation across facilities, aligned with **Egypt Vision 2030** and national waste-tracking frameworks.

### Addressing the adoption barriers the research identified

The underlying study (see [`PITCH.md`](PITCH.md)) surfaced four recurring barriers to AI
adoption in Egyptian industry. The architecture answers each directly:

| Barrier | Design response |
|---|---|
| Limited technical expertise | Cloud-based **pre-trained models** — no in-house data-science team required to operate the system. |
| High costs | **Modular, single-use-case rollout** — start on one line or one waste stream, expand on demonstrated ROI. |
| Inconsistent regulation | The **expert-system compliance layer** encodes rules explicitly and auditably, so they can be swapped per jurisdiction without retraining anything. |
| Data scarcity | **Transfer learning** from global datasets with local fine-tuning; the rule-based layers keep the product useful from day one, before any local labels exist. |

## 5. Scalability path: from simulation to real telemetry

1. **Today** — in-process simulator; single-process app; in-memory state.
2. **Connectors** — implement `OpcUaTelemetrySource` (targeting `asyncua`) and
   `MqttTelemetrySource` (Sparkplug B codec). The core and UI need no changes.
3. **State & history** — swap in-memory ring buffers for a time-series store
   (e.g. TimescaleDB / InfluxDB) behind the same accessors; add a historian
   backfill connector (OSIsoft/AVEVA PI).
4. **Horizontal scale** — the transport layer is stateless per request; the
   simulation/agent loops move to a dedicated worker (or per-site edge node)
   publishing frames over a broker (MQTT/Redis) that API nodes fan out via
   WebSocket. Per-plant isolation maps naturally to per-site edge deployments.
5. **Models** — replace/augment the rule engine and deterministic RUL with
   trained models (with uncertainty), served at the edge for data residency.

Because the agent already reasons over the generic telemetry contract, none of the
above touches the reasoning layer.

## 6. Security & data-handling (for real deployment)

Current state is a **demo** (open CORS, no auth, in-memory state — appropriate for
a public simulation). For a real industrial deployment, the intended posture:

- **OT segmentation & standards** — align with **IEC 62443** (incl. `-4-1` secure
  development); treat the app as a Level-3/edge component, never exposed directly to
  Level-0/1 devices. OPC-UA with certificate-based security; MQTT over TLS.
- **On-prem / air-gapped option** — the rule engine + local LLM (Ollama) mean the
  full product can run with **no external egress**, which many energy/defense-
  adjacent operators require. Docker image is self-contained.
- **AuthN/AuthZ** — add OIDC/SSO + role-based access before any multi-tenant or
  internet-facing deployment (not in the demo).
- **Input validation** — already enforced at the edge via Pydantic models
  (`schemas.py`); the WebSocket has a connection cap; a global handler prevents
  internal error leakage.
- **Data residency** — per-site edge deployment keeps plant data local; the
  MENA go-to-market explicitly plans in-region data residency.
- **PII** — the system handles machine telemetry, not personal data; the only
  personal field is the marketing contact form, which is logged server-side with no
  third-party egress (wire to your own CRM).
- **Compliance-ready outputs** — the energy/impact model is designed to export
  auditable, asset-level energy data aligned with ISO 50001 / EU EED reporting.

## 7. Testing, quality & operability

- **53 tests** (`pytest`) covering physics (degradation monotonicity, failure
  signatures, RUL, estimate-vs-truth tracking, seed determinism), the maintenance
  queue, agent decision logic, the business-impact model, integrations, and the API
  (validation, error paths, WebSocket).
- **Static analysis** — `ruff` (lint + format) and `mypy` on all core modules.
- **CI** — GitHub Actions on Python 3.11 & 3.12: lint, format-check, type-check, test.
- **Ops** — env-driven config, structured logs (JSON in prod), a `/health` probe,
  graceful shutdown of background loops, and a Docker `HEALTHCHECK`.

## 8. Key design decisions & trade-offs

| Decision | Rationale | Trade-off |
|---|---|---|
| Single latent-health source of truth | Coherence: badge/bar/RUL/agent never disagree | Slightly more physics code than a naïve model |
| Rules-first, LLM-optional | Works air-gapped; deterministic + testable; honest fallback | LLM narrative is a bonus, not the backbone |
| Two decoupled loops | LLM latency can't stall telemetry | Agent reasons on a near-live (not perfectly synchronous) snapshot |
| `TelemetrySource` abstraction now | Real connectors become drop-ins | Upfront interface design before it's strictly needed |
| In-memory state | Zero-dependency demo, trivial to run | Not durable/scaled — explicitly a roadmap item |
| Self-contained frontend (no CDN) | Works offline in Docker; no CSP/availability risk | Hand-rolled charts instead of a charting lib |

---

*This document reflects the codebase as built. Planned items are labelled; nothing
here implies real-world validation, which is the stated next milestone.*
