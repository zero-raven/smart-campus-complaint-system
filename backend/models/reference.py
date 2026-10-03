"""Reference / lookup tables: department, category, priority, complaint_status,
allowed_transition."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base


class Department(Base):
    __tablename__ = "department"

    dept_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dept_code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    dept_name: Mapped[str] = mapped_column(String(120), nullable=False)
    office_email: Mapped[str | None] = mapped_column(String(160), unique=True)
    office_phone: Mapped[str | None] = mapped_column(String(20))
    campus_zone: Mapped[str | None] = mapped_column(String(40))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    staff_members = relationship("Staff", back_populates="department")
    complaints = relationship("Complaint", back_populates="department")


class Category(Base):
    __tablename__ = "category"

    category_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category_code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    category_name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    icon: Mapped[str | None] = mapped_column(String(40))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    complaints = relationship("Complaint", back_populates="category")


class Priority(Base):
    __tablename__ = "priority"
    __table_args__ = (
        CheckConstraint("priority_rank BETWEEN 1 AND 4", name="priority_rank_range"),
        CheckConstraint("sla_hours > 0", name="sla_hours_positive"),
    )

    priority_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    priority_code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    priority_name: Mapped[str] = mapped_column(String(60), nullable=False)
    priority_rank: Mapped[int] = mapped_column(SmallInteger, unique=True, nullable=False)
    sla_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    complaints = relationship("Complaint", back_populates="priority")


class ComplaintStatus(Base):
    __tablename__ = "complaint_status"

    status_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    status_code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    status_name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_terminal: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False)


class AllowedTransition(Base):
    """The complaint state machine stored as data (a status-to-status M:N)."""

    __tablename__ = "allowed_transition"
    __table_args__ = (
        CheckConstraint("status_id <> next_status_id", name="no_self_transition"),
    )

    status_id: Mapped[int] = mapped_column(
        ForeignKey("complaint_status.status_id", ondelete="CASCADE"), primary_key=True
    )
    next_status_id: Mapped[int] = mapped_column(
        ForeignKey("complaint_status.status_id", ondelete="CASCADE"), primary_key=True
    )
    required_role: Mapped[str] = mapped_column(String(20), nullable=False)
    requires_remark: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
