from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.models import Region
from app.schemas.schemas import RegionOut

router = APIRouter(prefix="/regions", tags=["Regions"])


@router.get("", response_model=list[RegionOut])
async def list_regions(db: AsyncSession = Depends(get_db)):
    # Public: needed by the self-registration form. Region names are not sensitive.
    result = await db.execute(select(Region).order_by(Region.name))
    return result.scalars().all()