"""SQLAlchemy ORM models."""

from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text, Boolean, JSON, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class ArticleModel(Base):
    __tablename__ = "articles"

    id = Column(String, primary_key=True)  # MD5 hash of URL
    title = Column(Text, nullable=False)
    url = Column(Text, nullable=False)
    source = Column(String(200), nullable=False)
    published = Column(DateTime(timezone=True), nullable=False)
    category = Column(String(50), nullable=False, default="general")
    tickers = Column(JSON, nullable=False, default=list)  # JSONB in PostgreSQL
    summary = Column(Text, nullable=False, default="")
    fetched_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("idx_articles_published", published.desc()),
        Index("idx_articles_category", "category"),
    )


class UpgradeDowngradeModel(Base):
    __tablename__ = "upgrades_downgrades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(10), nullable=False)
    firm = Column(String(200), nullable=False)
    action = Column(String(50), nullable=False)
    old_rating = Column(String(100), default="")
    new_rating = Column(String(100), default="")
    price_target = Column(String(50), default="")
    published = Column(DateTime(timezone=True), nullable=False)
    source_url = Column(Text, default="")
    source = Column(String(200), default="")

    __table_args__ = (
        Index("idx_ud_published", published.desc()),
    )


class CustomFeedModel(Base):
    __tablename__ = "custom_feeds"

    name = Column(String(200), primary_key=True)
    url = Column(Text, nullable=False)
    category = Column(String(50), nullable=False, default="general")
    enabled = Column(Boolean, nullable=False, default=True)


class UserModel(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), unique=True, nullable=False)
    hashed_password = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    watchlist = relationship("UserWatchlistModel", back_populates="user", cascade="all, delete-orphan")
    settings = relationship("UserSettingsModel", back_populates="user", uselist=False, cascade="all, delete-orphan")
    device_tokens = relationship("DeviceTokenModel", back_populates="user", cascade="all, delete-orphan")


class UserWatchlistModel(Base):
    __tablename__ = "user_watchlists"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    ticker = Column(String(10), primary_key=True)

    user = relationship("UserModel", back_populates="watchlist")


class UserSettingsModel(Base):
    __tablename__ = "user_settings"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    timezone = Column(String(50), nullable=False, default="America/New_York")
    notification_prefs = Column(JSON, nullable=False, default=dict)

    user = relationship("UserModel", back_populates="settings")


class DeviceTokenModel(Base):
    __tablename__ = "device_tokens"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    platform = Column(String(20), nullable=False)
    token = Column(Text, unique=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    user = relationship("UserModel", back_populates="device_tokens")
