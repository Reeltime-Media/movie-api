"""Public catalog for the TV5 Entertainment app: TV5 series, Kun Khmer matches and plans.

TV5 titles never appear in Reeltime lists, and Reeltime titles never appear here.
Playback still goes through /playback, which checks the viewer's TV5 subscription.
"""

from fastapi import APIRouter, Query, Request
from sqlalchemy import func, or_, select, union
from sqlalchemy.orm import selectinload

from app.catalog.columns import content_list_load_options
from app.catalog.listing import get_series_detail, list_published_series, list_series_episodes
from app.catalog.search import apply_catalog_search
from app.catalog.series import get_series_or_404
from app.core.apps import TV5
from app.core.exceptions import NotFoundError
from app.dependencies import DBSession, OptionalUser
from app.models.content import Content
from app.models.match_details import MatchDetails
from app.rate_limit import limiter
from app.schemas.content import ContentRead
from app.schemas.hero_featured import HeroFeaturedSlideRead
from app.schemas.pagination import PaginatedResponse, PaginationDep, build_paginated_response
from app.schemas.series import SeriesListItemRead, SeriesRead
from app.schemas.subscription_plan import SubscriptionPlanRead
from app.schemas.tv5 import Tv5MatchListItemRead
from app.services.content_access import can_access_content, user_has_active_subscription
from app.services.hero_featured import TV5_HOME_PLACEMENT, resolve_hero_slides
from app.services.pagination import paginate_query
from app.services.response_cache import cache_get_or_set
from app.services.subscription_plans import list_subscription_plans

router = APIRouter(prefix="/tv5", tags=["tv5"])

_published_matches = (
    select(Content)
    .join(MatchDetails, MatchDetails.content_id == Content.id)
    .where(Content.app == TV5, Content.type == "single", Content.is_published.is_(True))
)


@router.get("/hero", response_model=list[HeroFeaturedSlideRead])
async def list_tv5_hero(db: DBSession):
    """The TV5 home banner: slides an admin set up for TV5, in order. An empty list
    means none are set, and the app falls back to its newest titles."""
    return await cache_get_or_set(
        f"hero:{TV5_HOME_PLACEMENT}",
        lambda: resolve_hero_slides(db, placement=TV5_HOME_PLACEMENT),
    )


@router.get("/series", response_model=PaginatedResponse[SeriesListItemRead])
@limiter.limit("120/minute")
async def list_tv5_series(
    request: Request,
    db: DBSession,
    pagination: PaginationDep,
    search: str | None = Query(default=None, max_length=200),
    genre: str | None = Query(default=None, max_length=100),
):
    _ = request  # SlowAPI
    return await list_published_series(
        db,
        page=pagination.page,
        page_size=pagination.page_size,
        search=search,
        genre=genre,
        app=TV5,
    )


@router.get("/series/{slug}", response_model=SeriesRead)
async def get_tv5_series(slug: str, db: DBSession, current_user: OptionalUser):
    return await get_series_detail(db, slug=slug, current_user=current_user, app=TV5)


@router.get("/series/{slug}/episodes", response_model=PaginatedResponse[ContentRead])
async def list_tv5_episodes(
    slug: str,
    db: DBSession,
    current_user: OptionalUser,
    pagination: PaginationDep,
):
    series = await get_series_or_404(db, slug, published_only=True, app=TV5)
    is_admin = current_user is not None and current_user.role == "admin"
    entitled = current_user is not None and await user_has_active_subscription(
        db, current_user.id, app=TV5
    )
    return await list_series_episodes(
        db,
        series,
        entitled=entitled,
        is_admin=is_admin,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.get("/matches", response_model=PaginatedResponse[Tv5MatchListItemRead])
@limiter.limit("120/minute")
async def list_tv5_matches(
    request: Request,
    db: DBSession,
    pagination: PaginationDep,
    search: str | None = Query(default=None, max_length=200),
    fighter: str | None = Query(default=None, max_length=120, description="Either corner"),
):
    _ = request  # SlowAPI
    stmt = _published_matches.options(
        content_list_load_options(), selectinload(Content.match)
    ).order_by(
        MatchDetails.match_date.desc().nulls_last(),
        Content.sort_order.asc(),
        Content.created_at.desc(),
    )
    stmt = apply_catalog_search(stmt, Content, search=search)
    if fighter and fighter.strip():
        name = fighter.strip().lower()
        stmt = stmt.where(
            or_(
                func.lower(MatchDetails.red_fighter) == name,
                func.lower(MatchDetails.blue_fighter) == name,
            )
        )
    items, total = await paginate_query(
        db, stmt, page=pagination.page, page_size=pagination.page_size
    )
    return build_paginated_response(
        [Tv5MatchListItemRead.model_validate(item) for item in items],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.get("/matches/{slug}", response_model=ContentRead)
async def get_tv5_match(slug: str, db: DBSession, current_user: OptionalUser):
    result = await db.execute(
        _published_matches.options(selectinload(Content.match)).where(Content.slug == slug)
    )
    match = result.scalar_one_or_none()
    if not match:
        raise NotFoundError("Match not found")
    data = ContentRead.model_validate(match)
    if not await can_access_content(db, current_user, None, match):
        data.hls_master_key = None
    return data


@router.get("/fighters", response_model=list[str])
async def list_tv5_fighters(db: DBSession):
    """Every fighter in a published match, for the app's fighter filter."""
    published = _published_matches.with_only_columns(Content.id).subquery()
    names = union(
        select(MatchDetails.red_fighter.label("name")).where(
            MatchDetails.content_id.in_(select(published.c.id))
        ),
        select(MatchDetails.blue_fighter.label("name")).where(
            MatchDetails.content_id.in_(select(published.c.id))
        ),
    ).subquery()
    result = await db.execute(select(names.c.name).order_by(func.lower(names.c.name)))
    return list(result.scalars().all())


@router.get("/plans", response_model=list[SubscriptionPlanRead])
async def list_tv5_plans(db: DBSession):
    return await list_subscription_plans(db, active_only=True, app=TV5)
