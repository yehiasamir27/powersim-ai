/*
 * PowerSim AI — client-side simulation engine.
 *
 * A faithful browser port of the Python core (simulator/power_system.py,
 * simulator/waste_stream.py, ai_agent/*.py, simulator/business_impact.py) so the
 * public demo runs with **no backend at all** on static hosting.
 *
 * Why this exists: Vercel's serverless model has no always-on process, and its
 * WebSocket support is capped at the function's max duration with no shared
 * in-memory state across reconnects — a live simulation would drop and reset. The
 * full Python/FastAPI/Docker stack remains the production/on-prem deployment; this
 * is the zero-setup public demo.
 *
 * The frames emitted here match the server's WebSocket frames exactly, so the
 * dashboard renders identically whether data comes from FastAPI or from here.
 */
(function (global) {
  "use strict";

  // ---- Deterministic RNG (mulberry32) + Gaussian --------------------------
  function mulberry32(a) {
    return function () {
      a |= 0; a = (a + 0x6d2b79f5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  class Rng {
    constructor(seed) { this._r = mulberry32(seed >>> 0); this._spare = null; }
    random() { return this._r(); }
    uniform(a, b) { return a + (b - a) * this._r(); }
    normal(mu, sigma) {
      if (this._spare !== null) { const s = this._spare; this._spare = null; return mu + sigma * s; }
      let u = 0, v = 0, s = 0;
      do { u = this._r() * 2 - 1; v = this._r() * 2 - 1; s = u * u + v * v; } while (s >= 1 || s === 0);
      const f = Math.sqrt((-2 * Math.log(s)) / s);
      this._spare = v * f;
      return mu + sigma * u * f;
    }
  }
  const clamp = (x, lo, hi) => Math.min(hi, Math.max(lo, x));
  const lerp = (healthy, failed, stress) => healthy + (failed - healthy) * stress;

  // =========================================================================
  // Power pillar
  // =========================================================================
  const TICK_SECONDS = 900.0; // 15 simulated minutes per tick
  const EMA_ALPHA = 0.35;

  const FAILURE_SIGNATURES = {
    bearing_wear: { label: "Bearing wear", health_impact: 12, mult: 2.5, temp: 8, vib: 4, bearing: 25, oil: 0, pf: 0, cur: 0 },
    insulation_breakdown: { label: "Insulation breakdown", health_impact: 16, mult: 2.2, temp: 12, vib: 0, bearing: 0, oil: 0, pf: -0.08, cur: 0 },
    oil_degradation: { label: "Oil degradation", health_impact: 10, mult: 1.8, temp: 6, vib: 0, bearing: 0, oil: -1.6, pf: 0, cur: 0 },
    misalignment: { label: "Shaft misalignment", health_impact: 8, mult: 1.7, temp: 3, vib: 3.5, bearing: 0, oil: 0, pf: 0, cur: 0 },
    overload: { label: "Sustained overload", health_impact: 14, mult: 2.3, temp: 15, vib: 0, bearing: 0, oil: 0, pf: -0.05, cur: 0.25 },
  };

  const ASSET_CONFIGS = [
    { id: "T1", type: "transformer", name: "Traction Transformer", rated: 1000, load: 0.72, rate: 0.020, crit: 40, fail: 12,
      s: { nt: 58, ft: 115, nv: 0.8, fv: 6.0, no: 5.5, fo: 1.8, np: 0.97, fp: 0.80, volt: 25000, cur: 40, tn: 1.0, vn: 0.12 } },
    { id: "M1", type: "motor", name: "Traction Motor", rated: 500, load: 0.78, rate: 0.032, crit: 35, fail: 8,
      s: { nt: 62, ft: 120, nv: 1.6, fv: 9.0, no: 4.5, fo: 1.2, np: 0.90, fp: 0.72, volt: 1500, cur: 215, tn: 1.4, vn: 0.22 } },
    { id: "G1", type: "generator", name: "Signalling Backup Generator", rated: 750, load: 0.55, rate: 0.026, crit: 38, fail: 10,
      s: { nt: 60, ft: 118, nv: 1.2, fv: 7.5, no: 5.0, fo: 1.5, np: 0.92, fp: 0.75, volt: 400, cur: 1082, tn: 1.3, vn: 0.18 } },
    { id: "P1", type: "pump", name: "Transformer Cooling Pump", rated: 50, load: 0.82, rate: 0.040, crit: 30, fail: 6,
      s: { nt: 45, ft: 95, nv: 2.0, fv: 10.0, no: 4.0, fo: 1.0, np: 0.88, fp: 0.70, volt: 415, cur: 85, tn: 1.6, vn: 0.28 } },
  ];

  class PowerSystem {
    constructor(seed) {
      this.rng = new Rng(seed);
      this.tickCount = 0;
      this.assets = ASSET_CONFIGS.map((c) => ({
        cfg: c, trueHealth: 100, estHealth: 100, state: "normal", hours: 0, failureMode: null,
      }));
    }
    byId(id) { return this.assets.find((a) => a.cfg.id === id); }

    effRate(a) {
      let r = a.cfg.rate;
      if (a.failureMode && FAILURE_SIGNATURES[a.failureMode]) r *= FAILURE_SIGNATURES[a.failureMode].mult;
      return r;
    }
    updateState(a) {
      const o = a.estHealth;
      if (o <= a.cfg.fail) a.state = "failed";
      else if (o <= a.cfg.crit) a.state = "critical";
      else if (o <= 60) a.state = "degraded";
      else a.state = "normal";
    }
    injectFailure(id, type) {
      const a = this.byId(id);
      if (!a || !FAILURE_SIGNATURES[type]) return false;
      a.trueHealth = Math.max(0, a.trueHealth - FAILURE_SIGNATURES[type].health_impact);
      a.failureMode = type;
      this.updateState(a);
      return true;
    }
    performMaintenance(id) {
      const a = this.byId(id);
      if (!a) return null;
      const prior = a.state;
      a.trueHealth = a.state === "failed" ? 75 : Math.min(100, a.trueHealth + 45);
      a.failureMode = null;
      a.estHealth = a.trueHealth;
      this.updateState(a);
      return prior;
    }
    estimateHealth(cfg, temp, vib, bearing, oil, pf) {
      const s = cfg.s;
      const st = (v, h, f) => (f - h === 0 ? 0 : clamp((v - h) / (f - h), 0, 1.2));
      const fused =
        st(temp, s.nt, s.ft) * 0.25 +
        st(vib, s.nv, s.fv) * 0.30 +
        clamp(bearing / 80, 0, 1.2) * 0.20 +
        st(oil, s.no, s.fo) * 0.10 +
        st(pf, s.np, s.fp) * 0.15;
      return clamp(100 * (1 - fused), 0, 100);
    }
    rul(a) {
      const rate = this.effRate(a);
      const headroom = a.estHealth - a.cfg.fail;
      if (headroom <= 0) return 0;
      return (headroom / Math.max(rate, 1e-6)) * (TICK_SECONDS / 3600);
    }
    tick() {
      this.tickCount++;
      const telemetry = {};
      for (const a of this.assets) {
        // Degrade latent health
        a.trueHealth = Math.max(0, a.trueHealth - this.effRate(a) * (1 + this.rng.uniform(0, 0.10)));
        a.hours += TICK_SECONDS / 3600;

        const cfg = a.cfg, s = cfg.s;
        const stress = 1 - a.trueHealth / 100;
        const sig = a.failureMode ? FAILURE_SIGNATURES[a.failureMode] : null;
        const loadFrac = clamp(cfg.load + this.rng.normal(0, 0.06), 0.2, 1.15);
        const loadThermal = (loadFrac - cfg.load) * 12;
        const spikeT = this.rng.random() < 0.006 ? 18 : 0;
        const spikeV = this.rng.random() < 0.006 ? 2.5 : 0;

        const temperature = lerp(s.nt, s.ft, stress) + loadThermal + (sig ? sig.temp : 0) + this.rng.normal(0, s.tn) + spikeT;
        const vibration = Math.max(0.05, lerp(s.nv, s.fv, stress) + (sig ? sig.vib : 0) + this.rng.normal(0, s.vn) + spikeV);
        const bearing = clamp(stress * 80 + (sig ? sig.bearing : 0) + this.rng.normal(0, 1.5), 0, 100);
        const oil = clamp(lerp(s.no, s.fo, stress) + (sig ? sig.oil : 0) + this.rng.normal(0, 0.12), 0.2, 10);
        const pf = clamp(lerp(s.np, s.fp, stress) + (sig ? sig.pf : 0) + this.rng.normal(0, 0.008), 0.5, 1);
        const voltage = s.volt * (1 + this.rng.normal(0, 0.005));
        const current = s.cur * loadFrac * (1 + (sig ? sig.cur : 0)) * (1 + this.rng.normal(0, 0.02));

        const est = this.estimateHealth(cfg, temperature, vibration, bearing, oil, pf);
        a.estHealth = EMA_ALPHA * est + (1 - EMA_ALPHA) * a.estHealth;
        this.updateState(a);

        telemetry[cfg.id] = {
          temperature: +temperature.toFixed(2), vibration: +vibration.toFixed(3),
          voltage: +voltage.toFixed(1), current: +current.toFixed(1),
          bearing_wear: +bearing.toFixed(2), oil_pressure: +oil.toFixed(2),
          health_score: +a.estHealth.toFixed(1), power_factor: +pf.toFixed(3),
          rul_hours: +this.rul(a).toFixed(1),
          anomaly_score: +clamp(100 - a.estHealth, 0, 100).toFixed(1),
          load: +(loadFrac * 100).toFixed(1),
          efficiency: +clamp(0.96 - stress * 0.22, 0.6, 0.99).toFixed(3),
        };
      }
      return telemetry;
    }
    summary() {
      let total = 0, minRul = Infinity;
      const assets = this.assets.map((a) => {
        total += a.estHealth;
        minRul = Math.min(minRul, this.rul(a));
        return {
          asset_id: a.cfg.id, asset_type: a.cfg.type, name: a.cfg.name,
          health: +a.estHealth.toFixed(1), true_health: +a.trueHealth.toFixed(2),
          operating_state: a.state, total_operating_hours: +a.hours.toFixed(2),
          failure_mode: a.failureMode,
          failure_label: a.failureMode ? FAILURE_SIGNATURES[a.failureMode].label : null,
        };
      });
      return {
        tick_count: this.tickCount,
        uptime_hours: +((this.tickCount * TICK_SECONDS) / 3600).toFixed(2),
        overall_health: +(total / this.assets.length).toFixed(2),
        min_rul_hours: minRul === Infinity ? null : +minRul.toFixed(1),
        assets,
      };
    }
  }

  // =========================================================================
  // Waste pillar
  // =========================================================================
  const COMP_KEYS = ["metal", "plastic", "organic", "chemical", "inert"];
  const HAZ_THRESHOLD = 0.32;
  const DIVERSION = { reduce: 0.30, reuse: 0.95, recycle: 0.85, recover: 0.60, dispose: 0.0 };
  const COMPLIANCE_RULES = {
    "H-01": { d: "Hazardous waste must be separated before disposal", s: "non_compliant" },
    "H-02": { d: "Hazardous material is mixed into normal waste", s: "non_compliant" },
    "C-01": { d: "Too contaminated to recycle (over 60%)", s: "non_compliant" },
    "C-02": { d: "High contamination (over 40%) lowers recycling value", s: "advisory" },
    "M-01": { d: "Too wet (over 55%) to recycle or recover well", s: "advisory" },
    "W-01": { d: "Over 500 kg, so an official waste record is required", s: "advisory" },
  };
  const WASTE_SOURCES = [
    { id: "WT1", name: "Traction Substation", asset: "T1", base: 85, p: 0.18, cont: 22, moist: 14,
      comp: { metal: 0.18, plastic: 0.07, organic: 0.02, chemical: 0.55, inert: 0.18 } },
    { id: "WM1", name: "Motor Workshop", asset: "M1", base: 140, p: 0.38, cont: 18, moist: 10,
      comp: { metal: 0.62, plastic: 0.12, organic: 0.03, chemical: 0.15, inert: 0.08 } },
    { id: "WG1", name: "Signalling Power Room", asset: "G1", base: 95, p: 0.30, cont: 25, moist: 16,
      comp: { metal: 0.34, plastic: 0.14, organic: 0.06, chemical: 0.24, inert: 0.22 } },
    { id: "WP1", name: "Cooling System", asset: "P1", base: 70, p: 0.32, cont: 30, moist: 38,
      comp: { metal: 0.17, plastic: 0.34, organic: 0.12, chemical: 0.14, inert: 0.23 } },
    { id: "WPL1", name: "Train Depot", asset: null, base: 320, p: 0.45, cont: 20, moist: 32,
      comp: { metal: 0.10, plastic: 0.34, organic: 0.40, chemical: 0.04, inert: 0.12 } },
  ];

  class WasteSystem {
    constructor(seed) {
      this.rng = new Rng(seed + 7777);
      this.tickCount = 0;
      this.hist = {};
      WASTE_SOURCES.forEach((s) => (this.hist[s.id] = { w: [], c: [] }));
      this.totals = { generated: 0, diverted: 0, events: 0 };
      this.recent = [];
      this.byCategory = { recyclable: 0, hazardous: 0, general: 0, reusable_byproduct: 0 };
      this.nonCompliant = 0;
    }
    static classify(comp, contamination) {
      const chemical = comp.chemical || 0;
      if (chemical >= HAZ_THRESHOLD || contamination > 85) {
        return ["hazardous", clamp(66 + (chemical - HAZ_THRESHOLD) * 160, 60, 99)];
      }
      const cleanF = 1 - contamination / 100;
      const scores = {
        recyclable: ((comp.metal || 0) + (comp.plastic || 0)) * 1.25 * cleanF,
        reusable_byproduct: (comp.organic || 0) * 1.35 * cleanF,
        general: 0.34 + contamination / 260,
      };
      const ranked = Object.entries(scores).sort((a, b) => b[1] - a[1]);
      const margin = (ranked[0][1] - ranked[1][1]) / (ranked[0][1] || 1);
      return [ranked[0][0], clamp(55 + margin * 100, 40, 99)];
    }
    detectAnomalies(sid, weight, comp) {
      const found = [];
      const h = this.hist[sid];
      if (h.w.length >= 5) {
        const mean = h.w.reduce((a, b) => a + b, 0) / h.w.length;
        const sd = Math.sqrt(h.w.reduce((a, b) => a + (b - mean) ** 2, 0) / h.w.length);
        const spike = sd > 1e-6 ? (weight - mean) / sd > 2.2 : weight > mean * 1.5;
        if (spike) found.push(`Volume spike: ${weight.toFixed(0)} kg vs ${mean.toFixed(0)} kg usual`);
      }
      if (h.c.length >= 5) {
        let l1 = 0;
        COMP_KEYS.forEach((k) => {
          const base = h.c.reduce((a, c) => a + c[k], 0) / h.c.length;
          l1 += Math.abs(comp[k] - base);
        });
        if (l1 > 0.28) found.push(`Composition drift: the mix changed by ${l1.toFixed(2)}`);
      }
      return found;
    }
    static checkCompliance(category, comp, contamination, moisture, weight) {
      const fired = [];
      if (category === "hazardous") fired.push("H-01");
      else if ((comp.chemical || 0) > 0.25) fired.push("H-02");
      if (contamination > 60) fired.push("C-01");
      else if (contamination > 40) fired.push("C-02");
      if (moisture > 55) fired.push("M-01");
      if (weight > 500) fired.push("W-01");
      let status = "compliant";
      fired.forEach((c) => {
        const s = COMPLIANCE_RULES[c].s;
        if (s === "non_compliant") status = "non_compliant";
        else if (s === "advisory" && status === "compliant") status = "advisory";
      });
      return [status, fired];
    }
    static recommend(category, contamination, severity, anomalies) {
      if (category === "hazardous")
        return ["recover", "Hazardous. Send to licensed treatment to recover material or energy."];
      if (category === "reusable_byproduct" && contamination <= 40)
        return ["reuse", "Clean byproduct. Reuse it as raw material."];
      if (category === "recyclable") {
        if (contamination <= 40) return ["recycle", "Clean recyclable material. Send it to recycling."];
        return ["reduce", "Too dirty to recycle. Fix sorting at the source."];
      }
      if (anomalies.length || severity > 55)
        return ["reduce", "Unusual amount of waste. Check the process that made it."];
      return ["dispose", "Mixed waste with no reuse option. Dispose of it safely."];
    }
    tick(assetHealth) {
      this.tickCount++;
      const events = [];
      for (const src of WASTE_SOURCES) {
        if (this.rng.random() > src.p) continue;
        const health = src.asset ? (assetHealth[src.asset] ?? 100) : 100;
        const stress = clamp(1 - health / 100, 0, 1);
        const surge = this.rng.random() < 0.05 ? 2.4 : 1.0;
        const weight = Math.max(5, src.base * (1 + 0.55 * stress) * (1 + this.rng.normal(0, 0.16)) * surge);
        const density = 260 + 240 * src.comp.metal;

        const comp = {};
        COMP_KEYS.forEach((k) => (comp[k] = src.comp[k]));
        comp.chemical += 0.18 * stress;
        comp.metal += 0.06 * stress;
        let total = 0;
        COMP_KEYS.forEach((k) => { comp[k] = Math.max(0, comp[k] + this.rng.normal(0, 0.025)); total += comp[k]; });
        COMP_KEYS.forEach((k) => (comp[k] = comp[k] / (total || 1)));

        const contamination = clamp(src.cont + 38 * stress + this.rng.normal(0, 4), 0, 100);
        const moisture = clamp(src.moist + this.rng.normal(0, 5), 0, 100);

        const [category, confidence] = WasteSystem.classify(comp, contamination);
        const anomalies = this.detectAnomalies(src.id, weight, comp);
        const h = this.hist[src.id];
        h.w.push(weight); if (h.w.length > 20) h.w.shift();
        h.c.push(comp); if (h.c.length > 20) h.c.shift();

        let severity = contamination * 0.55 + (comp.chemical || 0) * 55;
        if (category === "hazardous") severity += 18;
        severity = clamp(severity + 8 * anomalies.length, 0, 100);

        const [status, rules] = WasteSystem.checkCompliance(category, comp, contamination, moisture, weight);
        const [action, rationale] = WasteSystem.recommend(category, contamination, severity, anomalies);
        const diverted = weight * DIVERSION[action];

        const ev = {
          event_id: Math.random().toString(36).slice(2, 10),
          timestamp: new Date().toISOString(), tick: this.tickCount,
          source_id: src.id, source_name: src.name, asset_id: src.asset,
          weight_kg: +weight.toFixed(1), volume_m3: +(weight / density).toFixed(2),
          composition: comp, contamination_pct: +contamination.toFixed(1),
          moisture_pct: +moisture.toFixed(1), category,
          classification_confidence: +confidence.toFixed(1), severity: +severity.toFixed(1),
          anomalies, compliance_status: status,
          triggered_rules: rules.map((c) => ({ code: c, description: COMPLIANCE_RULES[c].d })),
          recommended_action: action, action_rationale: rationale,
          diverted_kg: +diverted.toFixed(1),
        };
        ev._rules = rules;
        events.push(ev);
        this.totals.generated += weight;
        this.totals.diverted += diverted;
        this.totals.events++;
        this.byCategory[category]++;
        if (status === "non_compliant") this.nonCompliant++;
        this.recent.unshift(ev);
        if (this.recent.length > 60) this.recent.pop();
      }
      return events;
    }
    summary() {
      const g = this.totals.generated;
      return {
        tick_count: this.tickCount, total_events: this.totals.events,
        generated_kg: +g.toFixed(1), diverted_kg: +this.totals.diverted.toFixed(1),
        diversion_rate_pct: g ? +((100 * this.totals.diverted) / g).toFixed(1) : 0,
        by_category: this.byCategory,
        non_compliant_recent: this.recent.filter((e) => e.compliance_status === "non_compliant").length,
      };
    }
  }

  // =========================================================================
  // Agents (rule engines — mirrors the Python fallback path)
  // =========================================================================
  const RULE_T = { critical_health: 20, high_health: 35, degraded_health: 55, high_temperature: 95,
    high_vibration: 5, low_oil_pressure: 2.5, high_bearing_wear: 55, low_rul_hours: 72 };

  class Agent {
    detectFactors(a, t) {
      const f = [];
      if (a.health <= RULE_T.degraded_health) f.push(`health is low at ${Math.round(a.health)}%`);
      if (t.temperature >= RULE_T.high_temperature) f.push(`running hot at ${t.temperature.toFixed(1)} °C`);
      if (t.vibration >= RULE_T.high_vibration) f.push(`high vibration at ${t.vibration.toFixed(2)} mm/s`);
      if (t.bearing_wear >= RULE_T.high_bearing_wear) f.push(`bearing wear at ${Math.round(t.bearing_wear)}%`);
      if (t.oil_pressure <= RULE_T.low_oil_pressure) f.push(`low oil pressure at ${t.oil_pressure.toFixed(2)} bar`);
      if (t.rul_hours > 0 && t.rul_hours <= RULE_T.low_rul_hours) f.push(`short remaining life (RUL ${Math.round(t.rul_hours)} h)`);
      if (a.failure_mode) f.push(`active fault: ${a.failure_mode.replace("_", " ")}`);
      return f;
    }
    evaluate(a, t) {
      const factors = this.detectFactors(a, t);
      let risk = 0;
      if (a.health <= RULE_T.critical_health) risk += 50;
      else if (a.health <= RULE_T.high_health) risk += 30;
      else if (a.health <= RULE_T.degraded_health) risk += 15;
      if (t.temperature >= RULE_T.high_temperature) risk += 15;
      if (t.vibration >= RULE_T.high_vibration) risk += 20;
      if (t.bearing_wear >= RULE_T.high_bearing_wear) risk += 15;
      if (t.oil_pressure <= RULE_T.low_oil_pressure) risk += 15;
      if (t.rul_hours > 0 && t.rul_hours <= RULE_T.low_rul_hours) risk += 20;
      if (a.failure_mode) risk += 20;

      let dt, pr, act;
      if (risk >= 70) { dt = "emergency"; pr = "critical"; act = "Send a team now and prepare a safe shutdown"; }
      else if (risk >= 50) { dt = "repair"; pr = "high"; act = "Repair within 4 hours"; }
      else if (risk >= 30) { dt = "maintain"; pr = "medium"; act = "Service within 24 hours"; }
      else if (risk >= 15) { dt = "inspect"; pr = "low"; act = "Inspect at the next planned visit"; }
      else { dt = "monitor"; pr = "low"; act = "Keep watching"; }

      const trail = [
        `Read ${a.name}: ${t.temperature.toFixed(1)} °C, vibration ${t.vibration.toFixed(2)} mm/s, health ${Math.round(a.health)}%, remaining life ${Math.round(t.rul_hours)} h.`,
        factors.length ? "Warning signs: " + factors.join("; ") + "." : "No warning signs.",
        `Risk ${risk.toFixed(0)} of 100, so the decision is ${dt.toUpperCase()}.`,
        `Action: ${act}.`,
      ];
      return {
        decision_type: dt, confidence: Math.min(95, 55 + risk * 0.4),
        description: `${a.asset_id} ${a.name}`,
        recommended_action: act, reasoning: trail[1], priority: pr,
        source: "rules", reasoning_trail: trail, detected_factors: factors,
        rul_hours: t.rul_hours, requires_maintenance: dt !== "monitor",
      };
    }
  }

  const WASTE_LABELS = { monitor: "WATCH", inspect: "CHECK", treat: "REVIEW", segregate: "SEPARATE", escalate: "ALERT" };
  const PLAN_VERBS = { reduce: "fix the process that made it", reuse: "reuse it", recycle: "send it to recycling", recover: "send it to licensed treatment", dispose: "dispose of it safely" };

  class WasteAgentJs {
    evaluate(ev) {
      const factors = [];
      let risk = 0;
      if (ev.compliance_status === "non_compliant") { risk += 40; factors.push("breaks a waste rule"); }
      else if (ev.compliance_status === "advisory") { risk += 15; factors.push("rule warning"); }
      risk += ev.severity * 0.4;
      if (ev.category === "hazardous") { risk += 15; factors.push("hazardous material"); }
      if (ev.contamination_pct > 60) factors.push(`contamination at ${ev.contamination_pct.toFixed(0)}%`);
      ev.anomalies.forEach((a) => { risk += 12; factors.push(a.charAt(0).toLowerCase() + a.slice(1)); });
      risk = Math.min(100, risk);

      let dt, pr, act;
      if (risk >= 70) { dt = "escalate"; pr = "critical"; act = "Hold the load and tell the safety team."; }
      else if (risk >= 50) { dt = "segregate"; pr = "high"; act = "Separate it at the source, then check it again."; }
      else if (risk >= 32) { dt = "treat"; pr = "medium"; act = `Review the load, then ${PLAN_VERBS[ev.recommended_action]}.`; }
      else if (risk >= 16) { dt = "inspect"; pr = "low"; act = "Check a sample at the next pickup."; }
      else { dt = "monitor"; pr = "low"; act = "No action needed."; }

      const cat = ev.category.replace("_", " ");
      let line2 = "No rule broken and the mix looks normal.";
      if (factors.length) {
        line2 = "Warning signs: " + factors.join("; ") + ".";
        const rules = (ev._rules || []).map((c) => COMPLIANCE_RULES[c].d.toLowerCase());
        if (rules.length) line2 += " Rule: " + rules.join("; ") + ".";
      }
      const trail = [
        `Found ${ev.weight_kg.toFixed(0)} kg of ${cat} waste at ${ev.source_name}. Contamination ${ev.contamination_pct.toFixed(0)}%, moisture ${ev.moisture_pct.toFixed(0)}%, confidence ${ev.classification_confidence.toFixed(0)}%.`,
        line2,
        `Risk ${risk.toFixed(0)} of 100, so the decision is ${WASTE_LABELS[dt]}.`,
        `Best option: ${ev.recommended_action.toUpperCase()}. ${ev.action_rationale} About ${ev.diverted_kg.toFixed(0)} kg kept out of landfill.`,
      ];
      return { decision_type: dt, priority: pr, source: "rules", recommended_action: act, reasoning_trail: trail, risk_score: risk };
    }
  }

  // =========================================================================
  // Business impact
  // =========================================================================
  const NOMINAL_EFF = 0.96;
  class Impact {
    constructor() {
      this.a = {
        downtime_cost_per_hour: 25000, energy_tariff_per_kwh: 0.12,
        grid_emission_factor_kg_per_kwh: 0.45, unplanned_downtime_hours_per_failure: 8,
        planned_maintenance_hours: 2, disposal_cost_per_tonne: 55,
        co2e_avoided_per_tonne_diverted_kg: 380, compliance_penalty_avoided_usd: 2500,
      };
      this.c = { failures: 0, reactive: 0, downtimeH: 0, energyKwh: 0, energyKwNow: 0,
        baseKwh: 0, wGen: 0, wDiv: 0, wEvents: 0, incidents: 0, hazardous: 0 };
    }
    onTick(assets, telemetry, hoursPerTick) {
      let waste = 0, base = 0;
      assets.forEach((a) => {
        const t = telemetry[a.cfg.id];
        if (!t) return;
        const consumed = a.cfg.rated * (t.load / 100);
        waste += consumed * Math.max(0, (NOMINAL_EFF - t.efficiency) / NOMINAL_EFF);
        base += consumed;
      });
      this.c.energyKwNow = waste;
      this.c.energyKwh += waste * hoursPerTick;
      this.c.baseKwh += base * hoursPerTick;
    }
    onMaintenance(prior) {
      if (prior === "degraded" || prior === "critical") {
        this.c.failures++;
        this.c.downtimeH += Math.max(0, this.a.unplanned_downtime_hours_per_failure - this.a.planned_maintenance_hours);
      } else if (prior === "failed") this.c.reactive++;
    }
    onWaste(ev) {
      this.c.wEvents++; this.c.wGen += ev.weight_kg; this.c.wDiv += ev.diverted_kg;
      if (ev.compliance_status === "non_compliant") this.c.incidents++;
      if (ev.category === "hazardous") this.c.hazardous++;
    }
    scorecard(energyWastePct) {
      const c = this.c;
      const inter = c.failures + c.reactive;
      const sub = {
        reliability: inter ? (100 * c.failures) / inter : 100,
        energy: Math.max(0, 100 - energyWastePct),
        waste_diversion: c.wGen > 0 ? (100 * c.wDiv) / c.wGen : 0,
        compliance: c.wEvents ? 100 * (1 - c.incidents / c.wEvents) : 100,
      };
      const weights = { reliability: 0.3, energy: 0.25, waste_diversion: 0.25, compliance: 0.2 };
      const score = Object.keys(weights).reduce((s, k) => s + sub[k] * weights[k], 0);
      Object.keys(sub).forEach((k) => (sub[k] = +sub[k].toFixed(1)));
      return { score: +score.toFixed(1), subscores: sub, weights };
    }
    snapshot() {
      const a = this.a, c = this.c;
      const downtimeCost = c.downtimeH * a.downtime_cost_per_hour;
      const wastePct = c.baseKwh > 0 ? (100 * c.energyKwh) / c.baseKwh : 0;
      const divT = c.wDiv / 1000;
      const disposal = divT * a.disposal_cost_per_tonne;
      const wCo2 = divT * a.co2e_avoided_per_tonne_diverted_kg;
      const compVal = c.incidents * a.compliance_penalty_avoided_usd;
      return {
        simulated: true, failures_prevented: c.failures, reactive_repairs: c.reactive,
        downtime_hours_avoided: +c.downtimeH.toFixed(2),
        downtime_cost_avoided_usd: +downtimeCost.toFixed(2),
        energy_waste_kw_now: +c.energyKwNow.toFixed(2),
        energy_wasted_kwh: +c.energyKwh.toFixed(2),
        energy_waste_pct: +wastePct.toFixed(2),
        energy_cost_wasted_usd: +(c.energyKwh * a.energy_tariff_per_kwh).toFixed(2),
        co2_wasted_kg: +(c.energyKwh * a.grid_emission_factor_kg_per_kwh).toFixed(1),
        waste_events: c.wEvents, waste_generated_kg: +c.wGen.toFixed(1),
        waste_diverted_kg: +c.wDiv.toFixed(1),
        waste_diversion_rate_pct: c.wGen > 0 ? +((100 * c.wDiv) / c.wGen).toFixed(1) : 0,
        disposal_cost_avoided_usd: +disposal.toFixed(2),
        waste_co2e_avoided_kg: +wCo2.toFixed(1),
        compliance_incidents_caught: c.incidents, hazardous_events: c.hazardous,
        compliance_value_usd: +compVal.toFixed(2),
        value_protected_usd: +(downtimeCost + disposal + compVal).toFixed(2),
        sustainability: this.scorecard(wastePct),
      };
    }
  }

  // =========================================================================
  // Engine facade — emits frames identical to the server's WebSocket frames
  // =========================================================================
  class PowerSimEngine {
    constructor(seed) { this.seed = seed || 42; this.reset(); }
    reset() {
      this.power = new PowerSystem(this.seed);
      this.waste = new WasteSystem(this.seed);
      this.agent = new Agent();
      this.wasteAgent = new WasteAgentJs();
      this.impact = new Impact();
      this.queue = [];
      this.decisions = {};
      this.latestTelemetry = {};
      this._wid = 1;
    }
    tick() {
      const telemetry = this.power.tick();
      this.latestTelemetry = telemetry;
      this.impact.onTick(this.power.assets, telemetry, TICK_SECONDS / 3600);

      const health = {};
      this.power.assets.forEach((a) => (health[a.cfg.id] = a.estHealth));
      const wasteEvents = this.waste.tick(health).map((ev) => {
        const d = this.wasteAgent.evaluate(ev);
        this.impact.onWaste(ev);
        return {
          kind: "waste", timestamp: ev.timestamp, tick: ev.tick,
          asset_id: ev.source_id, asset_name: ev.source_name,
          decision_type: d.decision_type, priority: d.priority, source: d.source,
          summary: d.recommended_action, reasoning_trail: d.reasoning_trail,
          work_order: null, waste: ev,
        };
      });

      return {
        type: "tick", tick_count: this.power.tickCount, timestamp: new Date().toISOString(),
        state: this.power.summary(), telemetry, impact: this.impact.snapshot(),
        queue_stats: this.queueStats(), waste: this.waste.summary(), waste_events: wasteEvents,
      };
    }
    runAgentPass() {
      const events = [];
      const summary = this.power.summary();
      summary.assets.forEach((a) => {
        const t = this.latestTelemetry[a.asset_id];
        if (!t) return;
        const d = this.agent.evaluate(a, t);
        const prev = this.decisions[a.asset_id];
        this.decisions[a.asset_id] = d;
        const hasOpen = this.queue.some((w) => w.asset_id === a.asset_id);
        if (d.requires_maintenance && !hasOpen) {
          const wo = { id: "w" + this._wid++, asset_id: a.asset_id,
            work_type: { inspect: "inspection", maintain: "preventive", repair: "corrective", emergency: "emergency" }[d.decision_type] || "inspection",
            priority: d.priority, status: "pending" };
          this.queue.push(wo);
          events.push(this._ev(a, d, { work_order_id: wo.id, priority: wo.priority }));
        } else if (!prev || prev.decision_type !== d.decision_type) {
          events.push(this._ev(a, d, null));
        }
      });
      return {
        type: "agent", timestamp: new Date().toISOString(), decisions: this.decisions,
        events, agent_status: { enabled: false, available: false, model: "rule engine in the browser", url: "local", last_mode: "rules" },
        fleet_summary: this.fleetSummary(),
      };
    }
    _ev(a, d, wo) {
      return { kind: "maintenance", timestamp: new Date().toISOString(), tick: this.power.tickCount,
        asset_id: a.asset_id, asset_name: a.name, decision_type: d.decision_type,
        priority: d.priority, source: d.source, summary: d.recommended_action,
        reasoning_trail: d.reasoning_trail, work_order: wo };
    }
    fleetSummary() {
      const ds = Object.values(this.decisions);
      if (!ds.length) return "The agent is starting. Waiting for the first readings.";
      const need = ds.filter((d) => d.decision_type !== "monitor");
      if (!need.length) return `All ${ds.length} assets are healthy. The agent keeps watching.`;
      const rank = { emergency: 4, repair: 3, maintain: 2, inspect: 1, monitor: 0 };
      const worst = ds.reduce((m, d) => (rank[d.decision_type] > rank[m.decision_type] ? d : m));
      return `${need.length} of ${ds.length} assets need attention. Top priority: ${worst.decision_type.toUpperCase()} on ${worst.description}.`;
    }
    queueStats() {
      return { total_active: this.queue.length, pending: this.queue.length, in_progress: 0,
        completed_total: 0, critical_count: this.queue.filter((w) => w.priority === "critical").length,
        high_priority_count: this.queue.filter((w) => w.priority === "high").length };
    }
    // -- commands (mirror the REST API) --
    injectFailure(id, type) { return this.power.injectFailure(id, type); }
    performMaintenance(id) {
      const prior = this.power.performMaintenance(id);
      if (prior === null) return false;
      this.impact.onMaintenance(prior);
      this.queue = this.queue.filter((w) => w.asset_id !== id);
      return true;
    }
    completeWorkOrder(wid) { this.queue = this.queue.filter((w) => w.id !== wid); }
    getQueue() { return { work_orders: this.queue, stats: this.queueStats() }; }
    updateAssumptions(patch) {
      Object.entries(patch).forEach(([k, v]) => { if (v !== null && v !== undefined && !Number.isNaN(v) && k in this.impact.a) this.impact.a[k] = v; });
      return this.getImpact();
    }
    getImpact() {
      return { snapshot: this.impact.snapshot(), methodology: {
        disclaimer: "All figures are simulated projections from the browser demo. No real world validation is implied. Replace the assumptions with your own line economics.",
        assumptions: this.impact.a,
        formulas: {
          downtime_cost_avoided_usd: "failures_prevented x (unplanned_downtime_hours_per_failure minus planned_maintenance_hours) x downtime_cost_per_hour.",
          energy_wasted_kwh: "Sum over ticks of rated_kW x load_fraction x (nominal_efficiency minus current_efficiency) / nominal_efficiency.",
          waste_diverted_kg: "Sum over waste events of weight_kg x the diversion rate of the recommended 4R action.",
          disposal_cost_avoided_usd: "(waste_diverted_kg / 1000) x disposal_cost_per_tonne",
          compliance_value_usd: "compliance_incidents_caught x compliance_penalty_avoided_usd",
        },
      } };
    }
  }

  global.PowerSimEngine = PowerSimEngine;
})(window);
