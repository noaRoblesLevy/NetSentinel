"""SQLAlchemy models for NetSentinel."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, String, Boolean, DateTime, Text, Float, Integer, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class User(Base):
    """User model for authentication."""
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=False)
    role = Column(String(50), default="viewer")  # admin, analyst, viewer
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Site(Base):
    """Site/tenant model."""
    __tablename__ = "sites"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    internal_subnets = Column(JSON)  # Stored as inet[] in DB, accessed as list
    status = Column(String(20), default="onboarding")  # onboarding, learning, active, paused
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    assets = relationship("Asset", back_populates="site", lazy="dynamic")
    alerts = relationship("Alert", back_populates="site", lazy="dynamic")


class Asset(Base):
    """Network asset model."""
    __tablename__ = "assets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    site_id = Column(UUID(as_uuid=True), ForeignKey("sites.id"), nullable=False)
    ip = Column(String(45), nullable=False)  # inet type in DB
    hostname = Column(String(255))
    custom_name = Column(String(255))
    mac_address = Column(String(17))  # macaddr type in DB
    role_tag = Column(String(50), default="unknown")
    subnet_label = Column(String(100))
    first_seen = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow)
    is_monitored = Column(Boolean, default=True)
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    site = relationship("Site", back_populates="assets")
    alerts = relationship("Alert", back_populates="asset", lazy="dynamic")


class Alert(Base):
    """Security alert model."""
    __tablename__ = "alerts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    site_id = Column(UUID(as_uuid=True), ForeignKey("sites.id"), nullable=False)
    asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id"), nullable=False)
    alert_type = Column(String(100), nullable=False)
    severity = Column(String(20), nullable=False)  # low, medium, high, critical
    status = Column(String(50), default="open")  # open, acknowledged, investigating, resolved, false_positive
    title = Column(String(500), nullable=False)
    description = Column(Text)
    peak_score = Column(Float, default=0.0)
    avg_score = Column(Float, default=0.0)
    start_time = Column(DateTime)
    end_time = Column(DateTime)
    explanation = Column(JSON, default=dict)
    suggested_actions = Column(JSON, default=list)
    resolution_notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    site = relationship("Site", back_populates="alerts")
    asset = relationship("Asset", back_populates="alerts")


class AlertRule(Base):
    """Custom alert rule model."""
    __tablename__ = "alert_rules"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    site_id = Column(UUID(as_uuid=True), ForeignKey("sites.id"), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    rule_type = Column(String(50), nullable=False)  # threshold, persistence, rate, baseline
    severity = Column(String(20), default="medium")
    config = Column(JSON, default=dict)
    enabled = Column(Boolean, default=True)
    times_matched = Column(Integer, default=0)
    last_matched_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
