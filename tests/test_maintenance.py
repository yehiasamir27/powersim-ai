"""Tests for the maintenance work-order queue."""

import pytest

from simulator.maintenance import (
    MaintenanceManager,
    WorkOrderPriority,
    WorkOrderStatus,
    WorkOrderType,
)


@pytest.fixture
def manager() -> MaintenanceManager:
    return MaintenanceManager()


def _make(manager, asset_id, priority):
    return manager.create_work_order(
        asset_id=asset_id,
        work_type=WorkOrderType.PREVENTIVE,
        priority=priority,
        description="test",
        reason="test",
    )


def test_queue_sorted_by_priority(manager):
    _make(manager, "T1", WorkOrderPriority.LOW)
    _make(manager, "M1", WorkOrderPriority.CRITICAL)
    _make(manager, "G1", WorkOrderPriority.MEDIUM)
    _make(manager, "P1", WorkOrderPriority.HIGH)
    order = [wo.priority for wo in manager.get_queue()]
    assert order == [
        WorkOrderPriority.CRITICAL,
        WorkOrderPriority.HIGH,
        WorkOrderPriority.MEDIUM,
        WorkOrderPriority.LOW,
    ]


def test_start_then_complete_lifecycle(manager):
    wo = _make(manager, "T1", WorkOrderPriority.HIGH)
    assert manager.start_work(wo.id) is True
    assert manager.is_asset_under_maintenance("T1") is True
    assert wo.status is WorkOrderStatus.IN_PROGRESS
    assert manager.complete_work(wo.id) is True
    assert manager.is_asset_under_maintenance("T1") is False
    # Completed orders leave the active queue and land in history.
    assert manager.get_work_order(wo.id) is None
    assert len(manager.completed_history) == 1


def test_cannot_complete_before_start(manager):
    wo = _make(manager, "T1", WorkOrderPriority.LOW)
    assert manager.complete_work(wo.id) is False


def test_defer_and_cancel(manager):
    wo1 = _make(manager, "T1", WorkOrderPriority.LOW)
    wo2 = _make(manager, "M1", WorkOrderPriority.LOW)
    assert manager.defer_work(wo1.id, "waiting for parts") is True
    assert wo1.status is WorkOrderStatus.DEFERRED
    assert "waiting for parts" in wo1.reason
    assert manager.cancel_work(wo2.id) is True
    assert wo2.status is WorkOrderStatus.CANCELLED


def test_pending_orders_filtered_by_asset(manager):
    _make(manager, "T1", WorkOrderPriority.LOW)
    _make(manager, "M1", WorkOrderPriority.HIGH)
    pending_t1 = manager.get_pending_orders("T1")
    assert len(pending_t1) == 1
    assert pending_t1[0].asset_id == "T1"


def test_statistics(manager):
    _make(manager, "T1", WorkOrderPriority.CRITICAL)
    _make(manager, "M1", WorkOrderPriority.HIGH)
    stats = manager.get_statistics()
    assert stats["total_active"] == 2
    assert stats["critical_count"] == 1
    assert stats["high_priority_count"] == 1


def test_scheduling_by_priority(manager):
    critical = _make(manager, "T1", WorkOrderPriority.CRITICAL)
    low = _make(manager, "M1", WorkOrderPriority.LOW)
    # Critical is scheduled immediately; low is pushed out.
    assert critical.scheduled_at <= low.scheduled_at
