from __future__ import annotations

from datetime import date, datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator

from .models import EVENT_KINDS, PLATFORMS, STAGES
from .periods import validate_period


def _platform(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    if value not in PLATFORMS:
        raise ValueError(f"platform must be one of {PLATFORMS}")
    return value


def _url(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    value = value.strip()
    # Only http(s): these are rendered as links in the UI.
    if not value.lower().startswith(("http://", "https://")):
        raise ValueError("URL must start with http:// or https://")
    return value


Period = Annotated[str | None, AfterValidator(validate_period)]
Platform = Annotated[str | None, AfterValidator(_platform)]
Url = Annotated[str | None, AfterValidator(_url)]


class ProjectBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    category: str | None = Field(default=None, max_length=60)
    creator: str | None = Field(default=None, max_length=200)
    funded_on: str = "kickstarter"
    pledge_manager: Platform = None
    campaign_url: Url = None
    pledge_manager_url: Url = None
    tier: str | None = Field(default=None, max_length=200)
    pledge_amount: float | None = Field(default=None, ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    original_est: Period = None
    current_est: Period = None
    stage: str = "funded"
    notes: str | None = None

    @field_validator("funded_on")
    @classmethod
    def _funded_on(cls, v: str) -> str:
        if v not in PLATFORMS:
            raise ValueError(f"funded_on must be one of {PLATFORMS}")
        return v

    @field_validator("stage")
    @classmethod
    def _stage(cls, v: str) -> str:
        if v not in STAGES:
            raise ValueError(f"stage must be one of {STAGES}")
        return v

    @field_validator("currency")
    @classmethod
    def _currency(cls, v: str) -> str:
        return v.upper()


class ProjectCreate(ProjectBase):
    pass


class ProjectUpdate(BaseModel):
    """Partial update: only the fields sent are changed."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    category: str | None = Field(default=None, max_length=60)
    creator: str | None = Field(default=None, max_length=200)
    funded_on: str | None = None
    pledge_manager: Platform = None
    campaign_url: Url = None
    pledge_manager_url: Url = None
    tier: str | None = Field(default=None, max_length=200)
    pledge_amount: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    original_est: Period = None
    current_est: Period = None
    stage: str | None = None
    notes: str | None = None

    @field_validator("funded_on")
    @classmethod
    def _funded_on(cls, v: str | None) -> str | None:
        if v is not None and v not in PLATFORMS:
            raise ValueError(f"funded_on must be one of {PLATFORMS}")
        return v

    @field_validator("stage")
    @classmethod
    def _stage(cls, v: str | None) -> str | None:
        if v is not None and v not in STAGES:
            raise ValueError(f"stage must be one of {STAGES}")
        return v


class EventCreate(BaseModel):
    occurred_on: date | None = None  # defaults to today
    kind: str = "note"
    title: str = Field(min_length=1, max_length=300)
    body: str | None = None
    url: Url = None

    @field_validator("kind")
    @classmethod
    def _kind(cls, v: str) -> str:
        if v not in EVENT_KINDS:
            raise ValueError(f"kind must be one of {EVENT_KINDS}")
        return v


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    occurred_on: date
    kind: str
    title: str
    body: str | None
    url: str | None
    source: str
    created_at: datetime


class ProjectOut(ProjectBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime

    # Derived, see routes._decorate
    original_est_label: str | None = None
    current_est_label: str | None = None
    effective_est: str | None = None
    effective_est_end: date | None = None
    overdue: bool = False
    months_overdue: int = 0
    slip_months: int | None = None
    needs_action: bool = False
    last_event_on: date | None = None
    event_count: int = 0


class ProjectDetail(ProjectOut):
    events: list[EventOut] = []


class Summary(BaseModel):
    total: int
    open: int
    overdue: int
    needs_action: int
    delivered: int
