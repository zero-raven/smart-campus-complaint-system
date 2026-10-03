"""The complaint aggregate and its relational children.

This is the module that imports every other model, so that SQLAlchemy's
string-based relationship resolution can find ``Complaint`` no matter which
module a caller imported first.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base
from backend.models.campus import CampusBuilding, CampusLocation  # noqa: F401
from backend.models.people import AppUser, Staff  # noqa: F401
from backend.models.reference import (  # noqa: F401
    AllowedTransition,
    Category,
    ComplaintStatus,
    Department,
    Priority,
)

__all__ = [
    "Complaint",
    "StatusHistory",
    "Assignment",
    "ComplaintEscalation",
    "Attachment",
    "ComplaintTag",
    "ComplaintTagMap",
    "Notification",
    "Feedback",
    "AuditLog",
    "Outbox",
    "TriageRule",
    "MLModel",
    "CampusBuilding",
    "CampusLocation",
    "AppUser",
    "Staff",
    "Category",
    "ComplaintStatus",
    "Department",
    "Priority",
    "AllowedTransition",
]


class MLModel(Base):
    __tablename__ = "ml_model"

    model_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    algorithm: Mapped[str] = mapped_column(String(60), nullable=False)
    accuracy: Mapped[float | None] = mapped_column(Numeric(5, 4))
    macro_precision: Mapped[float | None] = mapped_column(Numeric(5, 4))
    macro_recall: Mapped[float | None] = mapped_column(Numeric(5, 4))
    macro_f1: Mapped[float | None] = mapped_column(Numeric(5, 4))
    train_samples: Mapped[int | None] = mapped_column(Integer)
    test_samples: Mapped[int | None] = mapped_column(Integer)
    vocab_size: Mapped[int | None] = mapped_column(Integer)
    trained_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    artifact_path: Mapped[str | None] = mapped_column(String(255))


class TriageRule(Base):
    __tablename__ = "triage_rule"
    __table_args__ = (
        CheckConstraint(
            "rule_type IN ('CATEGORY_DEFAULT','DEPARTMENT_DEFAULT',"
            "'PRIORITY_OVERRIDE','KEYWORD')",
            name="valid_rule_type",
        ),
        CheckConstraint(
            "category_id IS NOT NULL OR dept_id IS NOT NULL", name="rule_scope_present"
        ),
    )

    rule_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_type: Mapped[str] = mapped_column(String(24), nullable=False)
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("category.category_id", ondelete="CASCADE")
    )
    dept_id: Mapped[int | None] = mapped_column(
        ForeignKey("department.dept_id", ondelete="CASCADE")
    )
    keyword: Mapped[str | None] = mapped_column(String(120))
    priority_id: Mapped[int | None] = mapped_column(
        ForeignKey("priority.priority_id", ondelete="CASCADE")
    )
    match_weight: Mapped[int] = mapped_column(SmallInteger, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("app_user.user_id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Complaint(Base):
    __tablename__ = "complaint"
    __table_args__ = (
        CheckConstraint(
            "(resolved_at IS NULL AND resolution_notes IS NULL) OR "
            "(resolved_at IS NOT NULL AND resolution_notes IS NOT NULL)",
            name="resolved_fields_pair",
        ),
        CheckConstraint(
            "channel IN ('WEB','EMAIL','KIOSK','MOBILE')", name="valid_channel"
        ),
    )

    complaint_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_no: Mapped[str] = mapped_column(String(24), unique=True, nullable=False)
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    location_id: Mapped[int | None] = mapped_column(
        ForeignKey("campus_location.location_id", ondelete="SET NULL")
    )
    free_location: Mapped[str | None] = mapped_column(String(160))
    category_id: Mapped[int] = mapped_column(
        ForeignKey("category.category_id", ondelete="RESTRICT"), nullable=False
    )
    priority_id: Mapped[int] = mapped_column(
        ForeignKey("priority.priority_id", ondelete="RESTRICT"), nullable=False
    )
    dept_id: Mapped[int] = mapped_column(
        ForeignKey("department.dept_id", ondelete="RESTRICT"), nullable=False
    )
    status_id: Mapped[int] = mapped_column(
        ForeignKey("complaint_status.status_id", ondelete="RESTRICT"), nullable=False
    )
    reported_by: Mapped[int] = mapped_column(
        ForeignKey("app_user.user_id", ondelete="RESTRICT"), nullable=False
    )
    assigned_to: Mapped[int | None] = mapped_column(
        ForeignKey("staff.staff_id", ondelete="SET NULL")
    )
    model_id: Mapped[int | None] = mapped_column(
        ForeignKey("ml_model.model_id", ondelete="SET NULL")
    )
    channel: Mapped[str] = mapped_column(String(20), default="WEB", nullable=False)
    is_auto_classified: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    category_confidence: Mapped[float | None] = mapped_column(Numeric(5, 4))
    is_user_overridden: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    resolution_notes: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    category = relationship("Category", back_populates="complaints")
    priority = relationship("Priority", back_populates="complaints")
    department = relationship("Department", back_populates="complaints")
    status = relationship("ComplaintStatus")
    reporter = relationship(
        "AppUser", back_populates="complaints", foreign_keys=[reported_by]
    )
    assignee = relationship(
        "Staff", back_populates="assigned_complaints", foreign_keys=[assigned_to]
    )
    model = relationship("MLModel")
    location = relationship("CampusLocation")
    history = relationship(
        "StatusHistory",
        back_populates="complaint",
        cascade="all, delete-orphan",
        order_by="StatusHistory.changed_at",
    )
    assignments = relationship(
        "Assignment",
        back_populates="complaint",
        cascade="all, delete-orphan",
        order_by="Assignment.assigned_at",
    )
    tags = relationship(
        "ComplaintTagMap",
        back_populates="complaint",
        cascade="all, delete-orphan",
    )
    attachments = relationship(
        "Attachment", back_populates="complaint", cascade="all, delete-orphan"
    )


class StatusHistory(Base):
    """Append-only relational audit trail of every status transition."""

    __tablename__ = "status_history"

    history_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    complaint_id: Mapped[int] = mapped_column(
        ForeignKey("complaint.complaint_id", ondelete="CASCADE"), nullable=False
    )
    old_status_id: Mapped[int | None] = mapped_column(
        ForeignKey("complaint_status.status_id", ondelete="SET NULL")
    )
    new_status_id: Mapped[int] = mapped_column(
        ForeignKey("complaint_status.status_id", ondelete="RESTRICT"), nullable=False
    )
    changed_by: Mapped[int] = mapped_column(
        ForeignKey("app_user.user_id", ondelete="RESTRICT"), nullable=False
    )
    remarks: Mapped[str | None] = mapped_column(Text)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    complaint = relationship("Complaint", back_populates="history")
    new_status = relationship("ComplaintStatus", foreign_keys=[new_status_id])


class Assignment(Base):
    __tablename__ = "assignment"
    __table_args__ = (
        CheckConstraint(
            "unassigned_at IS NULL OR unassigned_at >= assigned_at",
            name="assignment_window_valid",
        ),
    )

    assignment_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    complaint_id: Mapped[int] = mapped_column(
        ForeignKey("complaint.complaint_id", ondelete="CASCADE"), nullable=False
    )
    staff_id: Mapped[int] = mapped_column(
        ForeignKey("staff.staff_id", ondelete="RESTRICT"), nullable=False
    )
    assigned_by: Mapped[int] = mapped_column(
        ForeignKey("app_user.user_id", ondelete="RESTRICT"), nullable=False
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    unassigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str | None] = mapped_column(Text)

    complaint = relationship("Complaint", back_populates="assignments")
    staff = relationship("Staff")


class ComplaintEscalation(Base):
    __tablename__ = "complaint_escalation"

    escalation_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    complaint_id: Mapped[int] = mapped_column(
        ForeignKey("complaint.complaint_id", ondelete="CASCADE"), nullable=False
    )
    escalated_from: Mapped[int | None] = mapped_column(
        ForeignKey("department.dept_id", ondelete="SET NULL")
    )
    escalated_to: Mapped[int] = mapped_column(
        ForeignKey("department.dept_id", ondelete="RESTRICT"), nullable=False
    )
    escalated_by: Mapped[int] = mapped_column(
        ForeignKey("app_user.user_id", ondelete="RESTRICT"), nullable=False
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    escalated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    complaint = relationship("Complaint")


class Attachment(Base):
    __tablename__ = "attachment"

    attachment_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    complaint_id: Mapped[int] = mapped_column(
        ForeignKey("complaint.complaint_id", ondelete="CASCADE"), nullable=False
    )
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(100))
    file_size: Mapped[int | None] = mapped_column(BigInteger)
    storage_ref: Mapped[str | None] = mapped_column(String(255))
    uploaded_by: Mapped[int] = mapped_column(
        ForeignKey("app_user.user_id", ondelete="RESTRICT"), nullable=False
    )
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    complaint = relationship("Complaint", back_populates="attachments")


class ComplaintTag(Base):
    __tablename__ = "complaint_tag"
    __table_args__ = (
        CheckConstraint("tag_type IN ('MANUAL','AUTO','SYSTEM')", name="valid_tag_type"),
    )

    tag_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tag_name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    tag_type: Mapped[str] = mapped_column(String(30), default="MANUAL", nullable=False)
    description: Mapped[str | None] = mapped_column(Text)


class ComplaintTagMap(Base):
    """Junction table resolving complaint <-> tag (M:N)."""

    __tablename__ = "complaint_tag_map"

    complaint_id: Mapped[int] = mapped_column(
        ForeignKey("complaint.complaint_id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[int] = mapped_column(
        ForeignKey("complaint_tag.tag_id", ondelete="CASCADE"), primary_key=True
    )
    tagged_by: Mapped[int | None] = mapped_column(
        ForeignKey("app_user.user_id", ondelete="SET NULL")
    )
    tagged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    complaint = relationship("Complaint", back_populates="tags")
    tag = relationship("ComplaintTag")


class Notification(Base):
    __tablename__ = "notification"
    __table_args__ = (
        CheckConstraint(
            "channel IN ('IN_APP','EMAIL','SMS')", name="valid_channel"
        ),
        CheckConstraint(
            "category IN ('GENERAL','STATUS_CHANGE','ASSIGNMENT','SLA_WARNING','ESCALATION')",
            name="valid_category",
        ),
    )

    notification_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    complaint_id: Mapped[int | None] = mapped_column(
        ForeignKey("complaint.complaint_id", ondelete="CASCADE")
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("app_user.user_id", ondelete="CASCADE"), nullable=False
    )
    channel: Mapped[str] = mapped_column(String(20), default="IN_APP", nullable=False)
    category: Mapped[str] = mapped_column(String(30), default="GENERAL", nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    complaint = relationship("Complaint")


class Feedback(Base):
    __tablename__ = "feedback"
    __table_args__ = (
        CheckConstraint("rating BETWEEN 1 AND 5", name="rating_range"),
        UniqueConstraint("complaint_id", "user_id", name="uq_feedback_complaint_user"),
    )

    feedback_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    complaint_id: Mapped[int] = mapped_column(
        ForeignKey("complaint.complaint_id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("app_user.user_id", ondelete="CASCADE"), nullable=False
    )
    rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    is_resolved_accurate: Mapped[bool | None] = mapped_column(Boolean)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    complaint = relationship("Complaint")


class AuditLog(Base):
    __tablename__ = "audit_log"

    audit_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(
        ForeignKey("app_user.user_id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(40))
    details: Mapped[str | None] = mapped_column(Text)
    ip_address: Mapped[str | None] = mapped_column(String(45))
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Outbox(Base):
    """Transactional outbox: written in the same TX as the complaint mutation,
    then relayed to MongoDB by services/outbox_relay.py."""

    __tablename__ = "outbox"

    outbox_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    aggregate: Mapped[str] = mapped_column(String(40), default="complaint", nullable=False)
    complaint_id: Mapped[int | None] = mapped_column(
        ForeignKey("complaint.complaint_id", ondelete="CASCADE")
    )
    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    attempts: Mapped[int] = mapped_column(SmallInteger, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)
    published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    complaint = relationship("Complaint")
