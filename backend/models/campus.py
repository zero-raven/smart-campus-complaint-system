"""Campus physical assets: campus_building and campus_location."""

from __future__ import annotations

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base


class CampusBuilding(Base):
    __tablename__ = "campus_building"
    __table_args__ = (
        CheckConstraint(
            "building_type IN ('ACADEMIC','HOSTEL','ADMIN','LAB','SPORTS','MESS','OTHER')",
            name="valid_building_type",
        ),
    )

    building_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    building_code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    building_name: Mapped[str] = mapped_column(String(120), nullable=False)
    building_type: Mapped[str] = mapped_column(String(30), nullable=False)
    floors: Mapped[int | None] = mapped_column(SmallInteger)
    dept_id: Mapped[int | None] = mapped_column(
        ForeignKey("department.dept_id", ondelete="SET NULL")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    locations = relationship(
        "CampusLocation", back_populates="building", cascade="all, delete-orphan"
    )


class CampusLocation(Base):
    __tablename__ = "campus_location"
    __table_args__ = (
        CheckConstraint(
            "location_type IN ('ROOM','LAB','CORRIDOR','WASHROOM','STAIRCASE','COMMON','OTHER')",
            name="valid_location_type",
        ),
    )

    location_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    building_id: Mapped[int] = mapped_column(
        ForeignKey("campus_building.building_id", ondelete="CASCADE"), nullable=False
    )
    location_type: Mapped[str] = mapped_column(String(30), nullable=False)
    floor_no: Mapped[int | None] = mapped_column(SmallInteger)
    room_number: Mapped[str | None] = mapped_column(String(20))
    landmark: Mapped[str | None] = mapped_column(String(120))

    building = relationship("CampusBuilding", back_populates="locations")
