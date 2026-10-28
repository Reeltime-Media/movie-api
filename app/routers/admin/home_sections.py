import uuid

from fastapi import APIRouter
from sqlalchemy import select

from app.core.exceptions import ConflictError, NotFoundError
from app.dependencies import AdminUser, DBSession
from app.models.home_section import HomeSection, HomeSectionItem
from app.schemas.home_section import (
    HomeSectionAdminRead,
    HomeSectionCreate,
    HomeSectionItemCreate,
    HomeSectionItemRead,
    HomeSectionItemUpdate,
    HomeSectionReorder,
    HomeSectionUpdate,
)
from app.services.home_sections import (
    get_section_admin,
    list_section_items_admin,
    list_sections_admin,
    reorder_sections,
    validate_item_add,
    validate_section_create,
)
from app.services.response_cache import cache_delete

router = APIRouter()


async def _invalidate() -> None:
    await cache_delete("home-sections")
    await cache_delete("free-today")
    await cache_delete("genre-rails")
    await cache_delete("hero:home")
    await cache_delete("promos:home")


@router.get("/home-sections", response_model=list[HomeSectionAdminRead])
async def admin_list_home_sections(db: DBSession, _: AdminUser):
    return await list_sections_admin(db)


@router.post("/home-sections", response_model=HomeSectionAdminRead, status_code=201)
async def admin_create_home_section(
    data: HomeSectionCreate,
    db: DBSession,
    _: AdminUser,
):
    try:
        genre_name = await validate_section_create(
            db, section_type=data.type, genre_name=data.genre_name
        )
    except ValueError as exc:
        raise ConflictError(str(exc)) from exc

    section = HomeSection(
        type=data.type,
        title=data.title.strip() if data.title else None,
        genre_name=genre_name,
        is_visible=data.is_visible,
        sort_order=data.sort_order,
    )
    db.add(section)
    await db.commit()
    await db.refresh(section)
    await _invalidate()
    return await get_section_admin(db, section.id)


@router.put("/home-sections/reorder", response_model=list[HomeSectionAdminRead])
async def admin_reorder_home_sections(
    data: HomeSectionReorder,
    db: DBSession,
    _: AdminUser,
):
    try:
        await reorder_sections(db, data.ids)
    except ValueError as exc:
        raise NotFoundError(str(exc)) from exc
    await db.commit()
    await _invalidate()
    return await list_sections_admin(db)


@router.patch("/home-sections/items/{item_id}", response_model=HomeSectionItemRead)
async def admin_update_home_section_item(
    item_id: uuid.UUID,
    data: HomeSectionItemUpdate,
    db: DBSession,
    _: AdminUser,
):
    result = await db.execute(select(HomeSectionItem).where(HomeSectionItem.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise NotFoundError("Home section item not found")
    item.sort_order = data.sort_order
    await db.commit()
    await db.refresh(item)
    await _invalidate()
    enriched = await list_section_items_admin(db, item.section_id)
    for row in enriched:
        if row.id == item.id:
            return row
    return HomeSectionItemRead.model_validate(item)


@router.delete("/home-sections/items/{item_id}", status_code=204)
async def admin_delete_home_section_item(
    item_id: uuid.UUID,
    db: DBSession,
    _: AdminUser,
):
    result = await db.execute(select(HomeSectionItem).where(HomeSectionItem.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise NotFoundError("Home section item not found")
    await db.delete(item)
    await db.commit()
    await _invalidate()


@router.get("/home-sections/{section_id}", response_model=HomeSectionAdminRead)
async def admin_get_home_section(section_id: uuid.UUID, db: DBSession, _: AdminUser):
    section = await get_section_admin(db, section_id)
    if not section:
        raise NotFoundError("Home section not found")
    return section


@router.patch("/home-sections/{section_id}", response_model=HomeSectionAdminRead)
async def admin_update_home_section(
    section_id: uuid.UUID,
    data: HomeSectionUpdate,
    db: DBSession,
    _: AdminUser,
):
    result = await db.execute(select(HomeSection).where(HomeSection.id == section_id))
    section = result.scalar_one_or_none()
    if not section:
        raise NotFoundError("Home section not found")

    if data.title is not None:
        section.title = data.title.strip() or None
    if data.genre_name is not None and section.type == "genre":
        section.genre_name = " ".join(data.genre_name.strip().split()) or section.genre_name
    if data.is_visible is not None:
        section.is_visible = data.is_visible
    if data.sort_order is not None:
        section.sort_order = data.sort_order

    await db.commit()
    await _invalidate()
    return await get_section_admin(db, section_id)


@router.delete("/home-sections/{section_id}", status_code=204)
async def admin_delete_home_section(
    section_id: uuid.UUID,
    db: DBSession,
    _: AdminUser,
):
    result = await db.execute(select(HomeSection).where(HomeSection.id == section_id))
    section = result.scalar_one_or_none()
    if not section:
        raise NotFoundError("Home section not found")
    if section.type not in ("genre", "custom"):
        raise ConflictError("Hide this section instead of deleting it")
    await db.delete(section)
    await db.commit()
    await _invalidate()


@router.get("/home-sections/{section_id}/items", response_model=list[HomeSectionItemRead])
async def admin_list_home_section_items(
    section_id: uuid.UUID,
    db: DBSession,
    _: AdminUser,
):
    result = await db.execute(select(HomeSection.id).where(HomeSection.id == section_id))
    if not result.scalar_one_or_none():
        raise NotFoundError("Home section not found")
    return await list_section_items_admin(db, section_id)


@router.post(
    "/home-sections/{section_id}/items",
    response_model=HomeSectionItemRead,
    status_code=201,
)
async def admin_create_home_section_item(
    section_id: uuid.UUID,
    data: HomeSectionItemCreate,
    db: DBSession,
    _: AdminUser,
):
    result = await db.execute(select(HomeSection).where(HomeSection.id == section_id))
    section = result.scalar_one_or_none()
    if not section:
        raise NotFoundError("Home section not found")

    try:
        await validate_item_add(db, section, item_kind=data.item_kind, ref_id=data.ref_id)
    except ValueError as exc:
        message = str(exc)
        if "not found" in message.lower():
            raise NotFoundError(message) from exc
        raise ConflictError(message) from exc

    item = HomeSectionItem(
        section_id=section_id,
        item_kind=data.item_kind,
        ref_id=data.ref_id,
        sort_order=data.sort_order,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    await _invalidate()
    enriched = await list_section_items_admin(db, section_id)
    for row in enriched:
        if row.id == item.id:
            return row
    return HomeSectionItemRead.model_validate(item)
