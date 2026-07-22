"""Shared pytest fixtures and test-environment configuration.

Environment variables are set here (before any app module is imported) so the
cached ``Settings`` singleton picks up test-friendly values: the LLM is disabled
(deterministic rule-based reasoning) and the simulation ticks quickly.
"""

import os

os.environ.setdefault("POWERSIM_OLLAMA_ENABLED", "false")
os.environ.setdefault("POWERSIM_SIMULATION_TICK_SECONDS", "0.11")
os.environ.setdefault("POWERSIM_LOG_LEVEL", "WARNING")
os.environ.setdefault("POWERSIM_SIMULATION_SEED", "42")

import pytest  # noqa: E402

from simulator.power_system import PowerSystem  # noqa: E402


@pytest.fixture
def power_system() -> PowerSystem:
    """A fresh, seeded digital twin."""
    return PowerSystem(seed=42)


@pytest.fixture
def client():
    """FastAPI TestClient with lifespan (background loops) running."""
    from fastapi.testclient import TestClient

    import main

    main.service.reset()
    with TestClient(main.app) as test_client:
        yield test_client
