"""
Digital Twin implementation for industrial power system assets.

This module simulates real-time behavior of power system components including
transformers, motors, generators, and pumps. Each asset has physics-based
degradation models and telemetry generation.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Tuple
import numpy as np


class AssetType(Enum):
    """Types of power system assets."""
    TRANSFORMER = "transformer"
    MOTOR = "motor"
    GENERATOR = "generator"
    PUMP = "pump"


class AssetOperationalState(Enum):
    """Operational states for assets."""
    NORMAL = "normal"
    DEGRADED = "degraded"
    CRITICAL = "critical"
    FAILED = "failed"
    UNDER_MAINTENANCE = "under_maintenance"


@dataclass
class TelemetryData:
    """Real-time telemetry readings from an asset."""
    timestamp: datetime
    temperature: float  # Celsius
    vibration: float  # mm/s RMS
    voltage: float  # Volts
    current: float  # Amps
    bearing_wear: float  # 0-100%
    oil_pressure: float  # bar
    health_score: float  # 0-100%
    power_factor: float  # 0-1
    load: float = 0.0  # Percentage of rated capacity
    efficiency: float = 0.0  # Percentage

    def to_dict(self) -> dict:
        """Convert telemetry to dictionary for JSON serialization."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "temperature": float(self.temperature),
            "vibration": float(self.vibration),
            "voltage": float(self.voltage),
            "current": float(self.current),
            "bearing_wear": float(self.bearing_wear),
            "oil_pressure": float(self.oil_pressure),
            "health_score": float(self.health_score),
            "power_factor": float(self.power_factor),
        }


@dataclass
class AssetConfig:
    """Configuration parameters for an asset."""
    asset_id: str
    asset_type: AssetType
    name: str
    rated_capacity: float  # kVA or kW
    normal_temp_range: Tuple[float, float]
    normal_vibration_range: Tuple[float, float]
    degradation_rate: float  # Base degradation per tick
    critical_threshold: float  # Health % at which asset is critical
    failure_threshold: float  # Health % at which asset fails


@dataclass
class AssetData:
    """Complete state of a single asset."""
    config: AssetConfig
    health: float = 100.0  # 0-100%
    operating_state: AssetOperationalState = AssetOperationalState.NORMAL
    total_operating_hours: float = 0.0
    last_maintenance: Optional[datetime] = None
    failure_mode: Optional[str] = None
    degradation_factors: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert asset state to dictionary for JSON serialization."""
        return {
            "asset_id": self.config.asset_id,
            "asset_type": self.config.asset_type.value,
            "name": self.config.name,
            "health": round(self.health, 2),
            "operating_state": self.operating_state.value,
            "total_operating_hours": round(self.total_operating_hours, 2),
            "last_maintenance": self.last_maintenance.isoformat() if self.last_maintenance else None,
            "failure_mode": self.failure_mode,
        }


class PowerSystem:
    """
    Digital twin of an industrial power system.

    Simulates multiple assets with physics-based degradation models,
    real-time telemetry generation, and failure propagation.
    """

    # Simulation constants
    TICK_DURATION_SECONDS = 5.0  # Each simulation tick represents 5 seconds of operation
    AMBIENT_TEMPERATURE = 25.0  # Celsius
    BASE_LOAD_VARIATION = 0.05  # 5% random variation

    def __init__(self, seed: Optional[int] = None):
        """
        Initialize the power system digital twin.

        Args:
            seed: Random seed for reproducible simulations
        """
        self.rng = np.random.default_rng(seed)
        self.tick_count: int = 0
        self.start_time: datetime = datetime.now()
        self.assets: Dict[str, AssetData] = {}
        self.telemetry_history: Dict[str, List[TelemetryData]] = {}
        self._initialize_assets()

    def _initialize_assets(self) -> None:
        """Create initial asset configurations."""
        asset_configs = [
            AssetConfig(
                asset_id="T1",
                asset_type=AssetType.TRANSFORMER,
                name="Main Transformer",
                rated_capacity=1000.0,  # kVA
                normal_temp_range=(40.0, 75.0),
                normal_vibration_range=(0.5, 2.0),
                degradation_rate=0.02,
                critical_threshold=40.0,
                failure_threshold=10.0,
            ),
            AssetConfig(
                asset_id="M1",
                asset_type=AssetType.MOTOR,
                name="Induction Motor A",
                rated_capacity=500.0,  # kW
                normal_temp_range=(50.0, 85.0),
                normal_vibration_range=(1.0, 3.5),
                degradation_rate=0.03,
                critical_threshold=35.0,
                failure_threshold=5.0,
            ),
            AssetConfig(
                asset_id="G1",
                asset_type=AssetType.GENERATOR,
                name="Backup Generator",
                rated_capacity=750.0,  # kVA
                normal_temp_range=(45.0, 80.0),
                normal_vibration_range=(0.8, 2.5),
                degradation_rate=0.025,
                critical_threshold=38.0,
                failure_threshold=8.0,
            ),
            AssetConfig(
                asset_id="P1",
                asset_type=AssetType.PUMP,
                name="Coolant Pump",
                rated_capacity=50.0,  # kW
                normal_temp_range=(35.0, 65.0),
                normal_vibration_range=(1.5, 4.0),
                degradation_rate=0.04,
                critical_threshold=30.0,
                failure_threshold=5.0,
            ),
        ]

        for config in asset_configs:
            self.assets[config.asset_id] = AssetData(config=config)
            self.telemetry_history[config.asset_id] = []

    def get_asset(self, asset_id: str) -> Optional[AssetData]:
        """Get state of a specific asset."""
        return self.assets.get(asset_id)

    def get_all_assets(self) -> List[AssetData]:
        """Get state of all assets."""
        return list(self.assets.values())

    def get_telemetry_history(self, asset_id: str, max_points: int = 100) -> List[TelemetryData]:
        """Get recent telemetry history for an asset."""
        history = self.telemetry_history.get(asset_id, [])
        return history[-max_points:]

    def inject_failure(self, asset_id: str, failure_type: str) -> bool:
        """
        Inject a specific failure mode into an asset.

        Args:
            asset_id: Target asset identifier
            failure_type: Type of failure to inject

        Returns:
            True if failure was injected successfully
        """
        asset = self.assets.get(asset_id)
        if not asset:
            return False

        failure_modes = {
            "bearing_wear": {
                "health_impact": -25.0,
                "vibration_increase": 3.0,
                "temp_increase": 15.0,
            },
            "insulation_breakdown": {
                "health_impact": -30.0,
                "resistance_decrease": 50.0,
                "harmonic_increase": 0.15,
            },
            "oil_degradation": {
                "health_impact": -20.0,
                "oil_quality_decrease": 40.0,
                "temp_increase": 10.0,
            },
            "misalignment": {
                "health_impact": -15.0,
                "vibration_increase": 4.0,
                "efficiency_decrease": 0.1,
            },
            "overload": {
                "health_impact": -35.0,
                "temp_increase": 25.0,
                "efficiency_decrease": 0.15,
            },
        }

        if failure_type not in failure_modes:
            return False

        effects = failure_modes[failure_type]
        asset.health = max(0.0, asset.health + effects["health_impact"])
        asset.failure_mode = failure_type

        # Store degradation factors for telemetry generation
        asset.degradation_factors = effects

        self._update_operating_state(asset)
        return True

    def perform_maintenance(self, asset_id: str) -> bool:
        """
        Perform maintenance on an asset, restoring its health.

        Args:
            asset_id: Target asset identifier

        Returns:
            True if maintenance was performed successfully
        """
        asset = self.assets.get(asset_id)
        if not asset:
            return False

        # Restore health based on current state
        if asset.operating_state == AssetOperationalState.FAILED:
            asset.health = 70.0  # Partial recovery from failure
        else:
            asset.health = min(100.0, asset.health + 40.0)

        asset.failure_mode = None
        asset.degradation_factors = {}
        asset.last_maintenance = datetime.now()
        self._update_operating_state(asset)
        return True

    def _update_operating_state(self, asset: AssetData) -> None:
        """Update asset operating state based on health level."""
        if asset.health <= asset.config.failure_threshold:
            asset.operating_state = AssetOperationalState.FAILED
        elif asset.health <= asset.config.critical_threshold:
            asset.operating_state = AssetOperationalState.CRITICAL
        elif asset.health <= 60.0:
            asset.operating_state = AssetOperationalState.DEGRADED
        elif asset.operating_state == AssetOperationalState.UNDER_MAINTENANCE:
            asset.operating_state = AssetOperationalState.NORMAL
        else:
            asset.operating_state = AssetOperationalState.NORMAL

    def tick(self) -> Dict[str, TelemetryData]:
        """
        Advance simulation by one tick.

        Returns:
            Dictionary mapping asset IDs to their new telemetry readings
        """
        self.tick_count += 1
        telemetry: Dict[str, TelemetryData] = {}

        for asset_id, asset in self.assets.items():
            if asset.operating_state != AssetOperationalState.UNDER_MAINTENANCE:
                self._simulate_asset_tick(asset)

            tel = self._generate_telemetry(asset)
            telemetry[asset_id] = tel

            # Store in history (keep last 100 points)
            history = self.telemetry_history[asset_id]
            history.append(tel)
            if len(history) > 100:
                history.pop(0)

        return telemetry

    def _simulate_asset_tick(self, asset: AssetData) -> None:
        """Simulate one tick of asset operation and degradation."""
        # Base degradation
        degradation = asset.config.degradation_rate

        # Load-based degradation factor
        load_factor = 1.0 + (self.rng.random() * self.BASE_LOAD_VARIATION)
        degradation *= load_factor

        # Accelerated degradation if already damaged
        if asset.failure_mode:
            degradation *= 2.0

        # Apply degradation
        asset.health = max(0.0, asset.health - degradation)
        asset.total_operating_hours += self.TICK_DURATION_SECONDS / 3600.0

        # Update operating state
        self._update_operating_state(asset)

    def _generate_telemetry(self, asset: AssetData) -> TelemetryData:
        """Generate realistic telemetry readings for an asset."""
        config = asset.config
        now = datetime.now()

        # Asset-specific base values
        asset_bases = {
            "T1": {"temp": (60, 85), "vib": (0.5, 2.0), "voltage": 11000, "current": 52},
            "M1": {"temp": (45, 75), "vib": (1.0, 5.0), "voltage": 415, "current": 720},
            "G1": {"temp": (55, 80), "vib": (0.8, 3.0), "voltage": 400, "current": 1082},
            "P1": {"temp": (40, 65), "vib": (1.5, 4.0), "voltage": 415, "current": 85},
        }

        bases = asset_bases.get(asset.config.asset_id, {"temp": (50, 80), "vib": (1.0, 3.0), "voltage": 400, "current": 100})

        # Health-based degradation effects
        health_factor = 1.0 - (asset.health / 100.0)

        # Apply degradation factors from failure modes
        temp_offset = asset.degradation_factors.get("temp_increase", 0.0)
        vibration_offset = asset.degradation_factors.get("vibration_increase", 0.0)

        # Calculate telemetry values with slow degradation drift + Gaussian noise + occasional spikes
        spike_temp = self.rng.random() < 0.005
        spike_vib = self.rng.random() < 0.005

        # Temperature: base range + degradation + noise + occasional spike
        temp_base = sum(bases["temp"]) / 2
        temperature = (
            temp_base +
            temp_offset +
            (health_factor * 15.0) +
            self.rng.normal(0, 2.0) +
            (25.0 if spike_temp else 0.0)
        )

        # Vibration: base range + degradation + noise + occasional spike
        vibration_base = sum(bases["vib"]) / 2
        vibration = max(
            0.1,
            vibration_base +
            vibration_offset +
            (health_factor * 2.0) +
            self.rng.normal(0, 0.3) +
            (3.0 if spike_vib else 0.0)
        )

        # Voltage: nominal with small variation
        voltage = bases["voltage"] * (1.0 + self.rng.normal(0, 0.02))

        # Current: based on load with variation
        current = bases["current"] * (0.6 + 0.2 * self.rng.random() + health_factor * 0.1)

        # Bearing wear: slowly increasing over time, based on health
        bearing_wear = min(100.0, max(0.0, (100.0 - asset.health) + self.rng.normal(0, 2.0)))

        # Oil pressure: 2-8 bar range
        oil_pressure = max(2.0, min(8.0, 5.0 + self.rng.normal(0, 0.5) - health_factor * 2.0))

        # Health score: computed from all metrics
        health_score = self._compute_health_score(
            temperature, vibration, bearing_wear, oil_pressure, voltage, asset
        )

        # Power factor: 0.8-0.95 range
        power_factor = max(0.7, min(0.98, 0.90 - health_factor * 0.15 + self.rng.normal(0, 0.02)))

        # Load and efficiency for backwards compatibility
        load = 50.0 + self.rng.random() * 30.0
        efficiency = max(0.75, 0.95 - health_factor * 0.2)

        return TelemetryData(
            timestamp=now,
            temperature=temperature,
            vibration=vibration,
            voltage=voltage,
            current=current,
            bearing_wear=bearing_wear,
            oil_pressure=oil_pressure,
            health_score=health_score,
            power_factor=power_factor,
            load=load,
            efficiency=efficiency,
        )

    def _compute_health_score(
        self,
        temperature: float,
        vibration: float,
        bearing_wear: float,
        oil_pressure: float,
        voltage: float,
        asset: AssetData,
    ) -> float:
        """Compute overall health score from sensor metrics."""
        config = asset.config

        # Temperature health (based on normal range)
        temp_min, temp_max = config.normal_temp_range
        temp_health = max(0.0, 100.0 - abs(temperature - (temp_min + temp_max) / 2) * 2)

        # Vibration health
        vib_min, vib_max = config.normal_vibration_range
        vib_health = max(0.0, 100.0 - vibration * 15)

        # Bearing wear health (inverse)
        bearing_health = 100.0 - bearing_wear

        # Oil pressure health (optimal around 5 bar)
        oil_health = 100.0 - abs(oil_pressure - 5.0) * 15

        # Voltage health (should be close to nominal)
        voltage_health = max(0.0, 100.0 - abs(voltage - config.rated_capacity) / config.rated_capacity * 100)

        # Weighted average
        health_score = (
            temp_health * 0.25 +
            vib_health * 0.25 +
            bearing_health * 0.20 +
            oil_health * 0.15 +
            voltage_health * 0.15
        )

        return max(0.0, min(100.0, health_score))

    def get_state_summary(self) -> dict:
        """Get a summary of the current system state."""
        assets = []
        overall_health = 0.0

        for asset_id, asset in self.assets.items():
            assets.append(asset.to_dict())
            overall_health += asset.health

        overall_health /= len(self.assets)

        uptime_ticks = self.tick_count
        uptime_seconds = uptime_ticks * self.TICK_DURATION_SECONDS
        uptime_hours = uptime_seconds / 3600.0

        return {
            "tick_count": self.tick_count,
            "uptime_hours": round(uptime_hours, 2),
            "overall_health": round(overall_health, 2),
            "assets": assets,
        }
