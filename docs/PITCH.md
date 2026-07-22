# PowerSim AI — Pitch

> Structured to convert directly into deck slides. All product metrics are
> **simulated projections**; market figures are cited in
> [`MARKET_RESEARCH.md`](MARKET_RESEARCH.md). Placeholders marked **[TODO]** are
> where the founder must supply real, verifiable numbers — never fabricate.

**One-liner:** *PowerSim AI is the autonomous reliability engineer for industrial power — an agentic digital twin that catches equipment failures before they happen, explains why, and proves the ROI.*

---

## 1. Problem

Industrial plants lose enormous value to **unplanned downtime**, and prevention is getting harder:

- **The experts are retiring.** ~3.8M US manufacturing workers are needed through 2033, with ~1.9M potentially unfilled (Deloitte / Manufacturing Institute, 2024). Scarce vibration/reliability knowledge is walking out the door.
- **Alarm fatigue kills programs.** Legacy threshold monitoring generates low-context alerts; when operators repeatedly find nothing wrong, they stop trusting alerts and revert to reactive maintenance — erasing ROI.
- **Integration, not algorithms, is the blocker.** Telemetry is trapped in historians and legacy PLCs; most predictive-maintenance effort is data engineering, and programs stall in "pilot purgatory."

The result: maintenance stays mostly reactive/calendar-based while everyone agrees predictive is better.

## 2. Solution

A continuous **sense → think → act** agent over a physics-based digital twin:

- **Sense** — estimate each asset's health and remaining useful life from sensor fusion (temperature, vibration, bearing wear, oil pressure, power factor), with an anomaly score.
- **Think** — an LLM-or-rules agent decides whether to monitor, inspect, maintain, repair, or escalate — and emits a **transparent reasoning trail**. When the LLM is unavailable, it falls back to rules and *says so* (never a silent degrade).
- **Act** — decisions become prioritized work orders, and prevented failures become downtime, cost, energy and CO₂ saved — computed against the operator's own economics.

**What makes it different:** it *closes the loop* (acts), it's *explainable by default*, and its ROI is *buyer-supplied* — the three places incumbents visibly disappoint.

## 3. Why now

- **$3.1B** — Schneider Electric's 2026 acquisition of industrial-AI firm Cognite, explicitly to make AI *execute* operations. (Cognite / Bloomberg)
- **$53B** — Gartner's forecast for supply-chain software *with agentic AI* by 2030, up from <$2B in 2025.
- **Regulation as tailwind** — EU Energy Efficiency Directive audits (2026) and ISO 50001 mandates (2027), plus CBAM (live 2026), require the auditable, asset-level energy data this product produces.
- **MENA inflection** — Egypt's July 2025 removal of subsidised industrial electricity tariffs makes efficiency ROI compelling overnight.

The agentic thesis is validated by both M&A and incumbent roadmaps — but few have *scaled deployment*. The opening is a trusted, transparent, fast-to-deploy entrant.

## 4. Product / demo

A working product today, not slideware:

- Live **dashboard** streaming the sense→think→act loop, with a guided tour.
- **Reasoning "why" trail** — e.g. *"Sensed M1: 89°C, 8.1 mm/s, bearing 47%, health 45%, RUL 115h → REPAIR."*
- **Business-impact panel** — value protected, downtime avoided, energy/CO₂ wasted, with editable economics and visible methodology.
- **Integration roadmap** surfaced in-product (OPC-UA, MQTT, historian, ISO 50001).

Demo flow: inject a fault → the twin's sensors react → the agent catches it, explains itself, and opens a work order → perform maintenance → watch the ROI credit.

## 5. Technology moat

- **Deployment-ready architecture.** A clean `TelemetrySource` seam means swapping the simulator for a real OPC-UA / MQTT feed is a *connector, not a rewrite*.
- **Trust as a moat.** Explainable, simulation-first, honestly labelled — the opposite of inflated-accuracy incumbents, and exactly what conservative high-consequence operators want.
- **Engineering credibility.** Tested core (53 tests), CI, one-command Docker — passes technical due diligence.
- **MENA-native wedge.** Local presence, Arabic UI roadmap, data residency — no incumbent is MENA-native.

## 6. Market sizing

| Layer | Figure | Basis |
|---|---|---|
| **TAM** | ~$13–14B (2025) → ~$97–98B (early 2030s), ~25%+ CAGR | Analyst estimates for global predictive-maintenance software (vary widely — *directional*; cite the specific report you rely on) |
| **SAM** | **[TODO]** | Mid-market industrial + MENA energy/manufacturing digitization you can realistically serve |
| **SOM** | **[TODO]** | 3-year beachhead: # design-partner plants × ACV |

> **[TODO — founder]** Replace SAM/SOM with a defensible bottom-up build (target plant count × annual contract value). Anchor TAM to one named analyst report rather than a range.

## 7. Competitive landscape

| Vendor | Position | Where PowerSim differs |
|---|---|---|
| **Augury** ($1B+, $75M Feb 2025) | Sensor + prescriptive AI, enterprise, blue-chip logos | Software-first, mid-market, no hardware lock-in |
| **Tractian** ($120M Series C 2024) | "Industrial Copilot", HW+SW+CMMS | Agentic *act* loop + edge/on-prem, MENA-native |
| **Cognite** (acquired by Schneider, $3.1B) | Industrial DataOps / digital-twin platform | Turnkey agent, not a platform to build on |
| **Siemens Senseye** | OEM PdM + GenAI copilot, installed base | Vendor-neutral, transparent, lower-friction |
| **Avathon, Samotics, Falkonry** | Broad AI platform / ESA sensing / anomaly ML | Explainable, ROI-instrumented, mid-market focus |

Positioning gaps PowerSim credibly claims: **agentic autonomy vs dashboards**, **mid-market affordability**, **MENA focus**, **edge/on-prem**, and **transparent simulation-first** reasoning. (Full analysis in [`MARKET_RESEARCH.md`](MARKET_RESEARCH.md).)

## 8. Business model

Software-first SaaS priced by fleet:

- **Pilot** — prove the loop on a line, instrumented for ROI from day one.
- **Plant / Core** — whole-plant coverage, OPC-UA / MQTT ingest, work-order/CMMS export, ISO 50001 energy reporting.
- **Edge / On-prem** — air-gap-friendly deployment for data-sensitive operators, IEC 62443-aligned roadmap.

Motion: land with a low-friction pilot, expand across sites. **[TODO]** validate price points / ACV with design-partner conversations.

## 9. Traction & roadmap

- **Now:** working, tested product + live explainable demo.
- **Next:** OPC-UA / MQTT connectors; 2–3 design-partner pilots on real assets.
- **Later:** ISO 50001 energy reporting, IEC 62443-aligned edge, learned RUL with uncertainty, Arabic UI & MENA data residency.

> **[TODO — founder]** Add real traction as it lands — LOIs, pilots, waitlist, design-partner conversations. Investors verify; do not fabricate.

## 10. The ask

Raising a **[TODO: amount]** pre-seed/seed round to convert the working demo into validated pilots:

- Hire **[TODO: roles]**
- Ship the OPC-UA / MQTT connectors
- Land **[TODO: N]** design-partner plants over **[TODO: timeframe]**

> **[TODO — founder]** Set amount, use of funds, milestones, and target investors. Keep it specific and grounded.

---

*All in-product metrics are simulated projections; real-world validation on customer assets is the next milestone.*
