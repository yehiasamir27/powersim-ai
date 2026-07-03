# PowerSim AI - Real-Time Predictive Maintenance Simulation

A production-grade, AI-powered Predictive Maintenance simulation system for industrial power systems. This project demonstrates **Agentic AI** concepts (sense→think→act loops), **digital twin** technology, and **prognostic health management** as described in modern maintenance management literature.

## Overview

PowerSim AI simulates a real-time digital twin of an industrial power system, continuously monitoring asset health and using AI agents to:
- **Sense**: Collect telemetry from transformers, motors, generators, and pumps
- **Think**: Analyze degradation patterns and predict failures using LLM reasoning
- **Act**: Generate maintenance work orders and strategic recommendations

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        CLIENT (Browser)                         │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  Real-time Dashboard (WebSocket → Chart.js)              │  │
│  │  - Asset health cards with animated status               │  │
│  │  - 4 real-time telemetry charts                          │  │
│  │  - AI Agent reasoning panel                              │  │
│  │  - Maintenance queue management                          │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
                    WebSocket (ws://localhost:8000/ws)
                              │
┌─────────────────────────────────────────────────────────────────┐
│                      FASTAPI SERVER (main.py)                   │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐ │
│  │  WebSocket      │  │  REST API       │  │  Static Files   │ │
│  │  Manager        │  │  Endpoints      │  │  Server         │ │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘ │
└───────────┼────────────────────┼────────────────────┼──────────┘
            │                    │                    │
    ┌───────┴────────┐  ┌────────┴────────┐  ┌──────┴──────┐
    │                │  │                 │  │             │
┌───┴────────────┐  ┌─┴────────────────┐  ┌┴──────────────┐
│ power_system.py│  │ maintenance.py   │  │ agent.py      │
│ (Digital Twin) │  │ (Queue Mgmt)     │  │ (LLM Agent)   │
│                │  │                  │  │               │
│ - Transformer  │  │ - Work Orders    │  │ - Sense Loop  │
│ - Motor        │  │ - Scheduling     │  │ - Think Loop  │
│ - Generator    │  │ - Priority Queue │  │ - Act Loop    │
│ - Pump         │  │ - History        │  │ - Ollama API  │
└────────────────┘  └──────────────────┘  └───────────────┘
```

## Features

- **Real-time Digital Twin**: Simulates 4 industrial assets with physics-based degradation
- **AI-Powered Diagnostics**: LLM-based agent analyzes telemetry and generates insights
- **Predictive Maintenance**: Proactive work order generation before failures occur
- **Strategic Recommendations**: Long-term policy suggestions based on trend analysis
- **Cyberpunk UI**: CRT scanline effects, electric color scheme, real-time charts
- **Zero External Dependencies**: All state in-memory, no database required

## Prerequisites

- Python 3.11+
- pip
- Ollama (optional, for AI agent): [https://ollama.ai](https://ollama.ai)

## Installation

```bash
# Clone or navigate to the project directory
cd powersim-ai

# Install Python dependencies
pip install -r requirements.txt

# (Optional) Install Ollama model for AI agent
ollama pull qwen2.5:7b
```

## Running the Application

```bash
# Start the FastAPI server
uvicorn main:app --reload --port 8000

# Open browser to http://localhost:8000
```

## Architecture Components

### Simulator (`simulator/`)
- **power_system.py**: Digital twin implementation with 4 asset types
- **maintenance.py**: Work order queue and scheduling logic

### AI Agent (`ai_agent/`)
- **agent.py**: Sense→Think→Act loop with Ollama LLM integration
- Generates diagnostic reports and strategic recommendations

### Server (`main.py`)
- WebSocket manager for real-time client updates
- REST API for maintenance queue management
- Static file server for the dashboard

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Serve dashboard |
| GET | `/api/state` | Get current simulation state |
| POST | `/api/inject-failure` | Inject failure into asset |
| POST | `/api/maintenance` | Trigger maintenance on asset |
| GET | `/api/queue` | Get maintenance queue |
| POST | `/api/queue/{id}/complete` | Complete work order |
| POST | `/api/queue/{id}/defer` | Defer work order |
| WS | `/ws` | WebSocket for real-time updates |

## Without Ollama

The application runs without Ollama installed. The AI agent will use rule-based diagnostics as a fallback when the LLM is unavailable.

## License

MIT License
