"""Sites endpoints."""

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Site

router = APIRouter()


class SiteResponse(BaseModel):
    id: str
    name: str
    description: str | None
    internal_subnets: List[str]
    status: str
    created_at: str

    class Config:
        from_attributes = True


@router.get("", response_model=List[SiteResponse])
def get_sites(db: Session = Depends(get_db)):
    """Get all sites."""
    sites = db.query(Site).all()
    return [
        SiteResponse(
            id=str(site.id),
            name=site.name,
            description=site.description,
            internal_subnets=[str(s) for s in (site.internal_subnets or [])],
            status=site.status,
            created_at=site.created_at.isoformat() if site.created_at else "",
        )
        for site in sites
    ]


@router.get("/{site_id}", response_model=SiteResponse)
def get_site(site_id: UUID, db: Session = Depends(get_db)):
    """Get a specific site."""
    site = db.query(Site).filter(Site.id == site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    return SiteResponse(
        id=str(site.id),
        name=site.name,
        description=site.description,
        internal_subnets=[str(s) for s in (site.internal_subnets or [])],
        status=site.status,
        created_at=site.created_at.isoformat() if site.created_at else "",
    )
