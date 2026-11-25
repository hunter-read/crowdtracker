from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

PLATFORMS = ["kickstarter", "backerkit", "gamefound", "pledgemanager", "pledgebox", "indiegogo", "other"]

# Ordered: a project normally moves left to right.
STAGES = [
    "live",  # campaign still running
    "funded",  # campaign over, waiting on the creator
    "survey_open",  # survey / pledge manager waiting on YOU
    "survey_done",
    "charged",  # shipping or final balance charged
    "address_locked",
    "shipping",
    "partial",  # some rewards have arrived, others haven't
    "delivered",
    "cancelled",
]
CLOSED_STAGES = {"delivered", "cancelled"}
ACTION_STAGES = {"survey_open"}

REWARD_KINDS = ["digital", "physical"]

EVENT_KINDS = [
    "update",
    "survey",
    "charge",
    "address_lock",
    "shipping",
    "delivery",
    "estimate_change",
    "stage_change",
    "note",
]
EVENT_SOURCES = ["manual", "system", "email"]


def _now() -> datetime:
    return datetime.now(UTC)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str | None] = mapped_column(String(60))
    creator: Mapped[str | None] = mapped_column(String(200))

    # Where the pledge was made vs. where the survey / pledge manager lives.
    funded_on: Mapped[str] = mapped_column(String(30), default="kickstarter")
    pledge_manager: Mapped[str | None] = mapped_column(String(30))
    campaign_url: Mapped[str | None] = mapped_column(String(500))
    pledge_manager_url: Mapped[str | None] = mapped_column(String(500))

    tier: Mapped[str | None] = mapped_column(String(200))
    pledge_amount: Mapped[float | None] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(3), default="USD")

    # Day the crowdfunding campaign closed: the start of the wait.
    campaign_ended: Mapped[date | None] = mapped_column(Date)

    # Estimate periods, see periods.py. original_est never changes after the
    # campaign; current_est is the creator's latest word.
    original_est: Mapped[str | None] = mapped_column(String(10))
    current_est: Mapped[str | None] = mapped_column(String(10))

    stage: Mapped[str] = mapped_column(String(30), default="funded")
    # Day everything arrived. Set automatically when the pledge becomes "delivered".
    received_on: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    events: Mapped[list[Event]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="Event.occurred_on.desc(), Event.id.desc()",
    )
    rewards: Mapped[list[Reward]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="Reward.position, Reward.id",
    )


class Reward(Base):
    """One thing the pledge promises: a PDF, a hardcover, a wave of add-ons.

    Rewards often arrive separately and in stages, so each has its own
    received date. A pledge with no rewards listed is received as one unit.
    """

    __tablename__ = "rewards"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20), default="physical")
    received_on: Mapped[date | None] = mapped_column(Date)
    position: Mapped[int] = mapped_column(Integer, default=0)

    project: Mapped[Project] = relationship(back_populates="rewards")


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    occurred_on: Mapped[date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String(30), default="note")
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(String(500))
    source: Mapped[str] = mapped_column(String(20), default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    project: Mapped[Project] = relationship(back_populates="events")
