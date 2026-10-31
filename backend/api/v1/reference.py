"""Public reference data endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.database import get_db
from backend.models.reference import Category, ComplaintStatus, Department, Priority

router = APIRouter(prefix="/reference", tags=["reference"])


@router.get("/statuses")
def list_statuses(db: Session = Depends(get_db)):
    """List all complaint statuses with id, code, name, and sort order."""
    statuses = db.execute(
        select(ComplaintStatus).order_by(ComplaintStatus.sort_order)
    ).scalars().all()
    return {
        "items": [
            {
                "status_id": s.status_id,
                "status_code": s.status_code,
                "status_name": s.status_name,
                "sort_order": s.sort_order,
                "is_terminal": s.is_terminal,
            }
            for s in statuses
        ]
    }


@router.get("/priorities")
def list_priorities(db: Session = Depends(get_db)):
    """List all priorities with id, code, name, rank, and SLA hours."""
    priorities = db.execute(
        select(Priority).order_by(Priority.priority_rank)
    ).scalars().all()
    return {
        "items": [
            {
                "priority_id": p.priority_id,
                "priority_code": p.priority_code,
                "priority_name": p.priority_name,
                "priority_rank": p.priority_rank,
                "sla_hours": p.sla_hours,
            }
            for p in priorities
        ]
    }


@router.get("/categories")
def list_categories(db: Session = Depends(get_db)):
    """List all categories with id, code, and name."""
    categories = db.execute(
        select(Category).order_by(Category.category_name)
    ).scalars().all()
    return {
        "items": [
            {
                "category_id": c.category_id,
                "category_code": c.category_code,
                "category_name": c.category_name,
            }
            for c in categories
        ]
    }


@router.get("/departments")
def list_departments(db: Session = Depends(get_db)):
    """List all active departments with id, code, and name."""
    departments = db.execute(
        select(Department).where(Department.is_active.is_(True)).order_by(Department.dept_name)
    ).scalars().all()
    return {
        "items": [
            {
                "dept_id": d.dept_id,
                "dept_code": d.dept_code,
                "dept_name": d.dept_name,
            }
            for d in departments
        ]
    }


@router.get("/all")
def list_all_reference(db: Session = Depends(get_db)):
    """Get all reference data in a single call (for initial page load)."""
    statuses = db.execute(
        select(ComplaintStatus).order_by(ComplaintStatus.sort_order)
    ).scalars().all()
    priorities = db.execute(
        select(Priority).order_by(Priority.priority_rank)
    ).scalars().all()
    categories = db.execute(
        select(Category).order_by(Category.category_name)
    ).scalars().all()
    departments = db.execute(
        select(Department).where(Department.is_active.is_(True)).order_by(Department.dept_name)
    ).scalars().all()

    return {
        "statuses": [
            {
                "status_id": s.status_id,
                "status_code": s.status_code,
                "status_name": s.status_name,
                "sort_order": s.sort_order,
                "is_terminal": s.is_terminal,
            }
            for s in statuses
        ],
        "priorities": [
            {
                "priority_id": p.priority_id,
                "priority_code": p.priority_code,
                "priority_name": p.priority_name,
                "priority_rank": p.priority_rank,
                "sla_hours": p.sla_hours,
            }
            for p in priorities
        ],
        "categories": [
            {
                "category_id": c.category_id,
                "category_code": c.category_code,
                "category_name": c.category_name,
            }
            for c in categories
        ],
        "departments": [
            {
                "dept_id": d.dept_id,
                "dept_code": d.dept_code,
                "dept_name": d.dept_name,
            }
            for d in departments
        ],
    }