# Deployment

PowerSim AI ships in **two deployment modes**, deliberately. They are not
alternatives to each other — one is the product, the other is the shop window.

| | Production / on-prem | Public demo |
|---|---|---|
| **Stack** | Python · FastAPI · WebSocket · Ollama · Docker | Static HTML/CSS/JS |
| **Simulation runs** | Server-side (`SimulationService`) | In the browser (`static/assets/sim-engine.js`) |
| **LLM reasoning** | Yes (Ollama, optional) | No — deterministic rule engine only |
| **Contact form** | Delivered server-side (`POST /api/contact`) | Degrades to a documented fallback |
| **Where** | Customer VM, plant edge node, or any container host | Vercel (or any static host) |

---

## 1. Production / on-prem (the real stack)

```bash
docker compose up --build
```

Everything in the README's quickstart applies. This is what a customer or design
partner would actually run: persistent process, real WebSocket streaming, live
agent loop, and the LLM path available.

## 2. Public demo (Vercel, free tier)

### Why the demo is static

Vercel's serverless model is a poor fit for a *persistent* simulation:

- **No always-on process.** Work is bounded by a function invocation; there is no
  background loop that can keep ticking a digital twin between requests.
- **WebSockets are capped by function duration.** Vercel added WebSocket support
  to Functions (public beta, June 2026), but a connection dies at the function's
  `maxDuration` — **300 s on Hobby** — and clients must reconnect.
- **Instances are stateless and not sticky.** A reconnect isn't guaranteed to hit
  the same instance, so in-memory simulation state would reset. Vercel's own
  guidance is to keep state in an external store (e.g. Redis).

A server-driven live demo would therefore stutter and reset roughly every five
minutes. Running the same simulation **client-side** gives a smoother zero-setup
experience, costs nothing, and can't be rate-limited — so that's what the hosted
demo does. `sim-engine.js` is a faithful port of the Python core and emits frames
byte-compatible with the server's WebSocket frames, so the dashboard is the same
code either way and honestly labels itself *"in-browser demo"*.

### Deploy

```bash
python scripts/build_static.py
npm i -g vercel
vercel login
vercel link --yes --project powersim-ai
vercel deploy --prod --yes
```

`vercel login` is **interactive** — it opens a browser for OAuth and has no
non-interactive form. The only bypass is a token created from
`vercel.com/account/tokens` while signed in, after which deployment is fully
scriptable:

```bash
export VERCEL_TOKEN=...          # created by you in the Vercel dashboard
export VERCEL_ORG_ID=...         # these two skip `vercel link`
export VERCEL_PROJECT_ID=...
vercel deploy --prod --yes
```

Production lands on the project's auto-assigned `*.vercel.app` alias. `vercel
deploy` prints the URL on stdout — put it at the top of the README.

### Configuration

[`vercel.json`](../vercel.json) sets `framework: null`, `outputDirectory: public`
and `cleanUrls: true`. With `cleanUrls`, `public/dashboard.html` is served at
`/dashboard` and `public/pitch.html` at `/pitch` — **no rewrites needed**. (If you
ever add rewrites alongside `cleanUrls`, omit the `.html` extension in both source
and destination.)

`scripts/build_static.py` assembles `public/` and preserves the absolute
`/static/assets/...` paths the pages use, so one set of HTML files works under
both FastAPI and static hosting. Re-run it after any change under `static/`.

### ⚠️ Licensing caveat

Vercel's **Hobby plan is for non-commercial, personal use only**. A demo attached
to a company raising a round sits in a grey area. Before using this URL in
investor materials, either move the project to a paid plan or confirm the current
fair-use terms — this is a business decision, not a technical one.

## 3. Keeping the two in sync

`static/*.html` is the single source for both modes. After editing any page or
asset:

```bash
python scripts/build_static.py   # refresh public/
pytest                           # the Python core is unaffected but verify
```

The Python simulation remains authoritative; `sim-engine.js` mirrors it. If you
change physics constants, thresholds or impact assumptions in `simulator/`, mirror
them in `static/assets/sim-engine.js` so the hosted demo doesn't drift.
