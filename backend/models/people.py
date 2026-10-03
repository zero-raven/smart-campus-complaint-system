"""Identity tables: app_user (all roles) and staff (resolver subtype)."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base

ROLE_VALUES = ("STUDENT", "STAFF", "ADMIN", "VIEWER")


class AppUser(Base):
    __tablename__ = "app_user"
    __table_args__ = (
        CheckConstraint(
            "role IN ('STUDENT','STAFF','ADMIN','VIEWER')", name="valid_role"
        ),
    )

    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    dept_id: Mapped[int | None] = mapped_column(
        ForeignKey("department.dept_id", ondelete="SET NULL")
    )
    usn: Mapped[str | None] = mapped_column(String(30), unique=True)
    phone: Mapped[str | None] = mapped_column(String(20))
    semester: Mapped[int | None] = mapped_column(SmallInteger)
    section_name: Mapped[str | None] = mapped_column(String(20))
    hostel_name: Mapped[str | None] = mapped_column(String(40))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    department = relationship("Department", foreign_keys=[dept_id])
    staff_profile = relationship(
        "Staff", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    complaints = relationship(
        "Complaint", back_populates="reporter", foreign_keys="Complaint.reported_by"
    )


class Staff(Base):
    """Subtype of AppUser: 1:0..1. Staff belong to exactly one department."""

    __tablename__ = "staff"
    __table_args__ = (
        CheckConstraint("max_open_complaints > 0", name="max_open_positive"),
    )

    staff_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("app_user.user_id", ondelete="CASCADE"), unique=True, nullable=False
    )
    dept_id: Mapped[int] = mapped_column(
        ForeignKey("department.dept_id"), nullable=False
    )
    designation: Mapped[str] = mapped_column(String(80), nullable=False)
    max_open_complaints: Mapped[int] = mapped_column(SmallInteger, default=10, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    joined_on: Mapped[date | None] = mapped_column(Date)

    user = relationship("AppUser", back_populates="staff_profile")
    department = relationship("Department", back_populates="staff_members")
    assigned_complaints = relationship(
        "Complaint", back_populates="assignee", foreign_keys="Complaint.assigned_to"
    )
