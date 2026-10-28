from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.schemas.channel import TVChannelPublicRead
from app.schemas.content import ContentListItemRead
from app.schemas.hero_featured import HeroFeaturedSlideRead
from app.schemas.promotion_banner import PromotionBannerRead
from app.schemas.series import SeriesListItemRead

SECTION_TYPES = (
    "hero",
    "banners",
    "tv",
    "free_today",
    "trending",
    "most_watched",
    "coming_soon",
    "series",
    "genre",
    "custom",
    "plans",
)

SectionType = Literal[
    "hero",
    "banners",
    "tv",
    "free_today",
    "trending",
    "most_watched",
    "coming_soon",
    "series",
    "genre",
    "custom",
    "plans",
]

SINGLETON_TYPES = frozenset(
    {
        "hero",
        "banners",
        "tv",
        "free_today",
        "trending",
        "most_watched",
        "coming_soon",
        "series",
        "plans",
    }
)

SECTION_CAPS: dict[str, int] = {
    "free_today": 10,
    "trending": 12,
    "most_watched": 10,
    "coming_soon": 12,
    "series": 12,
    "genre": 12,
    "custom": 12,
    "tv": 12,
    "hero": 10,
    "banners": 10,
}

ITEM_KINDS_BY_TYPE: dict[str, frozenset[str]] = {
    "free_today": frozenset({"movie"}),
    "trending": frozenset({"movie"}),
    "most_watched": frozenset({"movie"}),
    "coming_soon": frozenset({"movie"}),
    "genre": frozenset({"movie"}),
    "custom": frozenset({"movie", "series"}),
    "series": frozenset({"series"}),
    "tv": frozenset({"tv_channel"}),
    "hero": frozenset({"hero_slide"}),
    "banners": frozenset({"banner"}),
    "plans": frozenset(),
}

ItemKind = Literal["movie", "series", "tv_channel", "hero_slide", "banner"]


class HomeSectionCreate(BaseModel):
    type: SectionType
    title: str | None = Field(default=None, max_length=120)
    genre_name: str | None = Field(default=None, max_length=80)
    is_visible: bool = True
    sort_order: int = 0

    @model_validator(mode="after")
    def check_type_fields(self) -> "HomeSectionCreate":
        if self.type == "genre":
            if not (self.genre_name and self.genre_name.strip()):
                raise ValueError("genre_name is required for genre sections")
        if self.type == "custom":
            if not (self.title and self.title.strip()):
                raise ValueError("title is required for custom sections")
        return self


class HomeSectionUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=120)
    genre_name: str | None = Field(default=None, max_length=80)
    is_visible: bool | None = None
    sort_order: int | None = None


class HomeSectionReorder(BaseModel):
    ids: list[UUID] = Field(min_length=1)


class HomeSectionItemCreate(BaseModel):
    item_kind: ItemKind
    ref_id: UUID
    sort_order: int = 0


class HomeSectionItemUpdate(BaseModel):
    sort_order: int


class HomeSectionItemRead(BaseModel):
    id: UUID
    section_id: UUID
    item_kind: str
    ref_id: UUID
    sort_order: int
    created_at: datetime
    updated_at: datetime
    label: str | None = None
    poster_key: str | None = None
    slug: str | None = None

    model_config = {"from_attributes": True}


class HomeSectionAdminRead(BaseModel):
    id: UUID
    type: str
    title: str | None
    genre_name: str | None
    is_visible: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime
    item_count: int = 0
    items: list[HomeSectionItemRead] = []

    model_config = {"from_attributes": True}


class HomeSectionPublicRead(BaseModel):
    id: UUID
    type: str
    title: str | None = None
    genre_name: str | None = None
    sort_order: int
    movies: list[ContentListItemRead] = []
    series: list[SeriesListItemRead] = []
    channels: list[TVChannelPublicRead] = []
    hero_slides: list[HeroFeaturedSlideRead] = []
    banners: list[PromotionBannerRead] = []
