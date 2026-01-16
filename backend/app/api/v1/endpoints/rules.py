"""Alert rules endpoints."""

import logging
from datetime import datetime
from typing import List, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter()


class RuleConfig(BaseModel):
    """Rule configuration."""
    threshold: Optional[float] = 0.85
    window_count: Optional[int] = 3


class RuleCreate(BaseModel):
    """Request model for creating a rule."""
    site_id: str
    name: str
    description: Optional[str] = None
    rule_type: str = "threshold"
    severity: str = "medium"
    config: Optional[RuleConfig] = None
    enabled: bool = True


class RuleUpdate(BaseModel):
    """Request model for updating a rule."""
    name: Optional[str] = None
    description: Optional[str] = None
    rule_type: Optional[str] = None
    severity: Optional[str] = None
    config: Optional[RuleConfig] = None
    enabled: Optional[bool] = None


class RuleResponse(BaseModel):
    """Response model for a rule."""
    id: str
    site_id: str
    name: str
    description: Optional[str]
    rule_type: str
    severity: str
    config: dict
    enabled: bool
    created_at: datetime
    updated_at: Optional[datetime]


def ensure_rules_table(db: Session):
    """Ensure the rules table exists."""
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS alert_rules (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            site_id UUID NOT NULL REFERENCES sites(id),
            name VARCHAR(255) NOT NULL,
            description TEXT,
            rule_type VARCHAR(50) NOT NULL DEFAULT 'threshold',
            severity VARCHAR(20) NOT NULL DEFAULT 'medium',
            config JSONB NOT NULL DEFAULT '{}',
            enabled BOOLEAN NOT NULL DEFAULT true,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ
        )
    """))
    db.commit()


@router.get("", response_model=List[RuleResponse])
def get_rules(
    site_id: str,
    db: Session = Depends(get_db)
):
    """Get all rules for a site."""
    try:
        ensure_rules_table(db)

        result = db.execute(
            text("""
                SELECT id, site_id, name, description, rule_type, severity,
                       config, enabled, created_at, updated_at
                FROM alert_rules
                WHERE site_id = :site_id
                ORDER BY created_at DESC
            """),
            {"site_id": site_id}
        )

        rules = []
        for row in result:
            rules.append(RuleResponse(
                id=str(row.id),
                site_id=str(row.site_id),
                name=row.name,
                description=row.description,
                rule_type=row.rule_type,
                severity=row.severity,
                config=row.config or {},
                enabled=row.enabled,
                created_at=row.created_at,
                updated_at=row.updated_at
            ))

        return rules
    except Exception as e:
        logger.error(f"Failed to get rules: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{rule_id}", response_model=RuleResponse)
def get_rule(
    rule_id: str,
    db: Session = Depends(get_db)
):
    """Get a specific rule."""
    try:
        result = db.execute(
            text("""
                SELECT id, site_id, name, description, rule_type, severity,
                       config, enabled, created_at, updated_at
                FROM alert_rules
                WHERE id = :rule_id
            """),
            {"rule_id": rule_id}
        )

        row = result.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Rule not found")

        return RuleResponse(
            id=str(row.id),
            site_id=str(row.site_id),
            name=row.name,
            description=row.description,
            rule_type=row.rule_type,
            severity=row.severity,
            config=row.config or {},
            enabled=row.enabled,
            created_at=row.created_at,
            updated_at=row.updated_at
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get rule: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("", response_model=RuleResponse, status_code=status.HTTP_201_CREATED)
def create_rule(
    rule: RuleCreate,
    db: Session = Depends(get_db)
):
    """Create a new rule."""
    import json
    try:
        ensure_rules_table(db)

        rule_id = str(uuid4())
        config = rule.config.model_dump() if rule.config else {"threshold": 0.85, "window_count": 3}
        config_json = json.dumps(config)

        db.execute(
            text("""
                INSERT INTO alert_rules (id, site_id, name, description, rule_type, severity, config, enabled)
                VALUES (:id, :site_id, :name, :description, :rule_type, :severity, CAST(:config AS jsonb), :enabled)
            """),
            {
                "id": rule_id,
                "site_id": rule.site_id,
                "name": rule.name,
                "description": rule.description,
                "rule_type": rule.rule_type,
                "severity": rule.severity,
                "config": config_json,
                "enabled": rule.enabled
            }
        )
        db.commit()

        # Fetch the created rule
        return get_rule(rule_id, db)
    except Exception as e:
        logger.error(f"Failed to create rule: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/{rule_id}", response_model=RuleResponse)
def update_rule(
    rule_id: str,
    rule: RuleUpdate,
    db: Session = Depends(get_db)
):
    """Update a rule."""
    import json
    try:
        # Build update query dynamically
        updates = []
        params = {"rule_id": rule_id}

        if rule.name is not None:
            updates.append("name = :name")
            params["name"] = rule.name
        if rule.description is not None:
            updates.append("description = :description")
            params["description"] = rule.description
        if rule.rule_type is not None:
            updates.append("rule_type = :rule_type")
            params["rule_type"] = rule.rule_type
        if rule.severity is not None:
            updates.append("severity = :severity")
            params["severity"] = rule.severity
        if rule.config is not None:
            updates.append("config = CAST(:config AS jsonb)")
            params["config"] = json.dumps(rule.config.model_dump())
        if rule.enabled is not None:
            updates.append("enabled = :enabled")
            params["enabled"] = rule.enabled

        if not updates:
            return get_rule(rule_id, db)

        updates.append("updated_at = NOW()")

        query = f"UPDATE alert_rules SET {', '.join(updates)} WHERE id = :rule_id"
        db.execute(text(query), params)
        db.commit()

        return get_rule(rule_id, db)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update rule: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rule(
    rule_id: str,
    db: Session = Depends(get_db)
):
    """Delete a rule."""
    try:
        result = db.execute(
            text("DELETE FROM alert_rules WHERE id = :rule_id"),
            {"rule_id": rule_id}
        )
        db.commit()

        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Rule not found")

        return None
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete rule: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
