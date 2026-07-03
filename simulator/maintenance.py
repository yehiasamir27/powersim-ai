"""
Maintenance management module for work order scheduling and tracking.

This module handles the creation, prioritization, and tracking of maintenance
work orders based on asset health and AI agent recommendations.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional
from uuid import uuid4


class WorkOrderPriority(Enum):
    """Priority levels for maintenance work orders."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class WorkOrderStatus(Enum):
    """Status of a work order."""
    PENDING = "pending"
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    DEFERRED = "deferred"
    CANCELLED = "cancelled"


class WorkOrderType(Enum):
    """Types of maintenance work orders."""
    INSPECTION = "inspection"
    PREVENTIVE = "preventive"
    CORRECTIVE = "corrective"
    EMERGENCY = "emergency"


@dataclass
class WorkOrder:
    """
    A maintenance work order for an asset.

    Attributes:
        id: Unique identifier for the work order
        asset_id: Target asset identifier
        work_type: Type of maintenance work
        priority: Priority level
        status: Current status
        description: Human-readable description of work needed
        reason: Technical reason for the work order
        created_at: When the work order was created
        scheduled_at: When the work is scheduled to begin
        estimated_duration: Expected duration in hours
        strategic_recommendation: Long-term policy suggestions
    """
    id: str = field(default_factory=lambda: str(uuid4())[:8])
    asset_id: str = ""
    work_type: WorkOrderType = WorkOrderType.INSPECTION
    priority: WorkOrderPriority = WorkOrderPriority.MEDIUM
    status: WorkOrderStatus = WorkOrderStatus.PENDING
    description: str = ""
    reason: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    scheduled_at: Optional[datetime] = None
    estimated_duration: float = 2.0
    strategic_recommendation: str = ""

    def to_dict(self) -> dict:
        """Convert work order to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "asset_id": self.asset_id,
            "work_type": self.work_type.value,
            "priority": self.priority.value,
            "status": self.status.value,
            "description": self.description,
            "reason": self.reason,
            "created_at": self.created_at.isoformat(),
            "scheduled_at": self.scheduled_at.isoformat() if self.scheduled_at else None,
            "estimated_duration": self.estimated_duration,
            "strategic_recommendation": self.strategic_recommendation,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "WorkOrder":
        """Create a WorkOrder from a dictionary."""
        return cls(
            id=data.get("id", str(uuid4())[:8]),
            asset_id=data.get("asset_id", ""),
            work_type=WorkOrderType(data.get("work_type", "inspection")),
            priority=WorkOrderPriority(data.get("priority", "medium")),
            status=WorkOrderStatus(data.get("status", "pending")),
            description=data.get("description", ""),
            reason=data.get("reason", ""),
            created_at=datetime.fromisoformat(data["created_at"]) if "created_at" in data else datetime.now(),
            scheduled_at=datetime.fromisoformat(data["scheduled_at"]) if data.get("scheduled_at") else None,
            estimated_duration=data.get("estimated_duration", 2.0),
            strategic_recommendation=data.get("strategic_recommendation", ""),
        )


class MaintenanceManager:
    """
    Manager for maintenance work orders.

    Handles creation, prioritization, scheduling, and tracking of
    maintenance work orders for power system assets.
    """

    # Priority sort order for queue
    PRIORITY_ORDER: Dict[WorkOrderPriority, int] = {
        WorkOrderPriority.CRITICAL: 0,
        WorkOrderPriority.HIGH: 1,
        WorkOrderPriority.MEDIUM: 2,
        WorkOrderPriority.LOW: 3,
    }

    def __init__(self):
        """Initialize the maintenance manager."""
        self.work_orders: Dict[str, WorkOrder] = {}
        self.completed_history: List[WorkOrder] = []
        self._maintenance_in_progress: set = set()

    def create_work_order(
        self,
        asset_id: str,
        work_type: WorkOrderType,
        priority: WorkOrderPriority,
        description: str,
        reason: str,
        strategic_recommendation: str = "",
        estimated_duration: float = 2.0,
    ) -> WorkOrder:
        """
        Create a new work order.

        Args:
            asset_id: Target asset identifier
            work_type: Type of maintenance work
            priority: Priority level
            description: Human-readable description
            reason: Technical reason
            strategic_recommendation: Long-term policy suggestions
            estimated_duration: Expected duration in hours

        Returns:
            The created work order
        """
        work_order = WorkOrder(
            asset_id=asset_id,
            work_type=work_type,
            priority=priority,
            description=description,
            reason=reason,
            strategic_recommendation=strategic_recommendation,
            estimated_duration=estimated_duration,
        )

        # Auto-schedule based on priority
        now = datetime.now()
        if priority == WorkOrderPriority.CRITICAL:
            work_order.scheduled_at = now
        elif priority == WorkOrderPriority.HIGH:
            work_order.scheduled_at = now + timedelta(hours=1)
        elif priority == WorkOrderPriority.MEDIUM:
            work_order.scheduled_at = now + timedelta(hours=4)
        else:
            work_order.scheduled_at = now + timedelta(days=1)

        self.work_orders[work_order.id] = work_order
        return work_order

    def get_work_order(self, work_order_id: str) -> Optional[WorkOrder]:
        """Get a specific work order by ID."""
        return self.work_orders.get(work_order_id)

    def get_queue(self, include_completed: bool = False) -> List[WorkOrder]:
        """
        Get the maintenance queue sorted by priority.

        Args:
            include_completed: Whether to include completed orders

        Returns:
            List of work orders sorted by priority (highest first)
        """
        orders = list(self.work_orders.values())

        if not include_completed:
            orders = [o for o in orders if o.status != WorkOrderStatus.COMPLETED]

        # Sort by priority (lowest number = highest priority)
        orders.sort(key=lambda o: (self.PRIORITY_ORDER[o.priority], o.created_at))

        return orders

    def get_pending_orders(self, asset_id: Optional[str] = None) -> List[WorkOrder]:
        """
        Get pending work orders, optionally filtered by asset.

        Args:
            asset_id: Optional asset ID filter

        Returns:
            List of pending work orders
        """
        orders = self.get_queue()
        if asset_id:
            orders = [o for o in orders if o.asset_id == asset_id]
        return [o for o in orders if o.status in (WorkOrderStatus.PENDING, WorkOrderStatus.SCHEDULED)]

    def start_work(self, work_order_id: str) -> bool:
        """
        Mark a work order as in progress.

        Args:
            work_order_id: ID of work order to start

        Returns:
            True if work was started successfully
        """
        work_order = self.work_orders.get(work_order_id)
        if not work_order or work_order.status not in (WorkOrderStatus.PENDING, WorkOrderStatus.SCHEDULED):
            return False

        work_order.status = WorkOrderStatus.IN_PROGRESS
        self._maintenance_in_progress.add(work_order.asset_id)
        return True

    def complete_work(self, work_order_id: str) -> bool:
        """
        Mark a work order as completed.

        Args:
            work_order_id: ID of work order to complete

        Returns:
            True if work was completed successfully
        """
        work_order = self.work_orders.get(work_order_id)
        if not work_order or work_order.status != WorkOrderStatus.IN_PROGRESS:
            return False

        work_order.status = WorkOrderStatus.COMPLETED
        self._maintenance_in_progress.discard(work_order.asset_id)

        # Move to history
        self.completed_history.append(work_order)
        del self.work_orders[work_order_id]

        return True

    def defer_work(self, work_order_id: str, reason: str = "") -> bool:
        """
        Defer a work order to later.

        Args:
            work_order_id: ID of work order to defer
            reason: Reason for deferral

        Returns:
            True if work was deferred successfully
        """
        work_order = self.work_orders.get(work_order_id)
        if not work_order or work_order.status in (WorkOrderStatus.COMPLETED, WorkOrderStatus.CANCELLED):
            return False

        work_order.status = WorkOrderStatus.DEFERRED
        if reason:
            work_order.reason += f" [Deferred: {reason}]"

        return True

    def cancel_work(self, work_order_id: str) -> bool:
        """
        Cancel a work order.

        Args:
            work_order_id: ID of work order to cancel

        Returns:
            True if work was cancelled successfully
        """
        work_order = self.work_orders.get(work_order_id)
        if not work_order or work_order.status in (WorkOrderStatus.COMPLETED, WorkOrderStatus.CANCELLED):
            return False

        work_order.status = WorkOrderStatus.CANCELLED
        return True

    def is_asset_under_maintenance(self, asset_id: str) -> bool:
        """Check if an asset is currently under maintenance."""
        return asset_id in self._maintenance_in_progress

    def get_statistics(self) -> dict:
        """Get maintenance statistics."""
        total = len(self.work_orders)
        pending = sum(1 for o in self.work_orders.values() if o.status == WorkOrderStatus.PENDING)
        in_progress = sum(1 for o in self.work_orders.values() if o.status == WorkOrderStatus.IN_PROGRESS)
        completed = len(self.completed_history)

        # Priority breakdown
        critical = sum(1 for o in self.work_orders.values() if o.priority == WorkOrderPriority.CRITICAL)
        high = sum(1 for o in self.work_orders.values() if o.priority == WorkOrderPriority.HIGH)

        return {
            "total_active": total,
            "pending": pending,
            "in_progress": in_progress,
            "completed_total": completed,
            "critical_count": critical,
            "high_priority_count": high,
        }

    def get_recommendations(self) -> list:
        """Get maintenance recommendations based on current work orders."""
        recommendations = []
        for order in self.get_queue():
            recommendations.append({
                "asset_id": order.asset_id,
                "work_type": order.work_type.value,
                "priority": order.priority.value,
                "description": order.description,
                "urgency": "immediate" if order.priority == WorkOrderPriority.CRITICAL else "soon" if order.priority == WorkOrderPriority.HIGH else "scheduled",
            })
        return recommendations
