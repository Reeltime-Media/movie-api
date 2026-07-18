import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

from app.core.money import validate_usd_price


class TranscodeJobRead(BaseModel):
    id: uuid.UUID
    content_id: uuid.UUID
    source_key: str
    status: str
    attempts: int
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    content_title: str | None = None
    content_type: str | None = None
    content_slug: str | None = None
    series_id: uuid.UUID | None = None
    series_title: str | None = None
    season_number: int | None = None
    episode_number: int | None = None

    model_config = {"from_attributes": True}


class MovieAssetUploadStart(BaseModel):
    video_content_type: str | None = None
    poster_content_type: str | None = None
    banner_content_type: str | None = None


class MovieAssetUploadStartRead(BaseModel):
    source_key: str | None = None
    video_upload_url: str | None = None
    poster_key: str | None = None
    poster_upload_url: str | None = None
    banner_key: str | None = None
    banner_upload_url: str | None = None


class MovieAssetUploadComplete(BaseModel):
    source_key: str | None = None
    poster_key: str | None = None
    banner_key: str | None = None


class DashboardUserSummary(BaseModel):
    total: int
    admins: int
    active: int


class DashboardContentSummary(BaseModel):
    movies: int
    series: int
    published: int
    drafts: int
    review: int
    scheduled: int


class DashboardPaymentSummary(BaseModel):
    total: int
    succeeded: int
    pending: int
    failed: int
    revenue_usd: Decimal


class DashboardTranscodeSummary(BaseModel):
    pending: int
    processing: int
    failed: int


class DashboardSummaryRead(BaseModel):
    users: DashboardUserSummary
    content: DashboardContentSummary
    payments: DashboardPaymentSummary
    transcodes: DashboardTranscodeSummary


class RevenueTimelinePoint(BaseModel):
    date: date
    revenue_usd: Decimal
    payment_count: int


class RevenueTimelineRead(BaseModel):
    days: int
    date_from: date | None = None
    date_to: date | None = None
    period_revenue_usd: Decimal
    all_time_revenue_usd: Decimal
    succeeded_payments: int
    points: list[RevenueTimelinePoint]


class TopTitleReportRead(BaseModel):
    id: uuid.UUID
    title: str
    type: str
    status: str
    revenue_usd: Decimal
    purchase_count: int
    watch_count: int
    completion_count: int


class AdminMovieCreate(BaseModel):
    title: str
    description: str | None = None
    genres: list[str] = []
    release_year: int | None = None
    rating: Decimal | None = None
    runtime_minutes: int | None = Field(default=None, gt=0)
    price_usd: Decimal = Decimal("0")
    trailer_url: str | None = None

    @field_validator("title")
    @classmethod
    def title_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("title is required")
        return value

    @field_validator("price_usd")
    @classmethod
    def check_price_usd(cls, value: Decimal) -> Decimal:
        return validate_usd_price(value)


class AdminPaymentRead(BaseModel):
    intent_id: str
    order_id: str
    user_id: uuid.UUID | None
    user_email: str
    user_full_name: str | None
    kind: str
    content_id: uuid.UUID | None
    amount_usd: Decimal
    status: str
    created_at: datetime
    resolved_at: datetime | None
