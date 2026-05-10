import uuid

from fastapi import APIRouter
from sqlalchemy import select

from app.core.exceptions import ConflictError, NotFoundError
from app.dependencies import AdminUser, CurrentUser, DBSession
from app.models.content import Content
from app.schemas.content import ContentCreate, ContentRead, ContentUpdate, PresignedUploadResponse
from app.services.storage import generate_presigned_upload_url

router = APIRouter(prefix="/content", tags=["content"])


@router.get("/", response_model=list[ContentRead])
async def list_content(db: DBSession, _: CurrentUser):
    result = await db.execute(select(Content).where(Content.is_published.is_(True)))
    return result.scalars().all()


@router.get("/{slug}", response_model=ContentRead)
async def get_content(slug: str, db: DBSession, _: CurrentUser):
    result = await db.execute(select(Content).where(Content.slug == slug))
    content = result.scalar_one_or_none()
    if not content:
        raise NotFoundError("Content not found")
    return content


@router.post("/", response_model=ContentRead, status_code=201)
async def create_content(data: ContentCreate, db: DBSession, _: AdminUser):
    existing = await db.execute(select(Content).where(Content.slug == data.slug))
    if existing.scalar_one_or_none():
        raise ConflictError("Slug already exists")
    content = Content(**data.model_dump())
    db.add(content)
    await db.commit()
    await db.refresh(content)
    return content


@router.patch("/{slug}", response_model=ContentRead)
async def update_content(slug: str, data: ContentUpdate, db: DBSession, _: AdminUser):
    result = await db.execute(select(Content).where(Content.slug == slug))
    content = result.scalar_one_or_none()
    if not content:
        raise NotFoundError("Content not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(content, field, value)
    await db.commit()
    await db.refresh(content)
    return content


@router.delete("/{slug}", status_code=204)
async def delete_content(slug: str, db: DBSession, _: AdminUser):
    result = await db.execute(select(Content).where(Content.slug == slug))
    content = result.scalar_one_or_none()
    if not content:
        raise NotFoundError("Content not found")
    await db.delete(content)
    await db.commit()


@router.post("/{slug}/upload-url", response_model=PresignedUploadResponse)
async def get_upload_url(slug: str, db: DBSession, _: AdminUser):
    """Return a presigned PUT URL so the admin client can upload the raw video directly to R2."""
    result = await db.execute(select(Content).where(Content.slug == slug))
    content = result.scalar_one_or_none()
    if not content:
        raise NotFoundError("Content not found")
    key = f"raw/{content.id}.mp4"
    url = generate_presigned_upload_url(key)
    return PresignedUploadResponse(upload_url=url, key=key)
