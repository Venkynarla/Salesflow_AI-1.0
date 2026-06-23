from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, DateTime,
    Boolean, ForeignKey, Enum as SAEnum
)
from sqlalchemy.orm import relationship, declarative_base
import enum

Base = declarative_base()


class ContactStatus(str, enum.Enum):
    pending      = "pending"
    enriching    = "enriching"
    enriched     = "enriched"
    drafting     = "drafting"
    draft_ready  = "draft_ready"
    approved     = "approved"
    sent         = "sent"
    followed_up  = "followed_up"
    replied      = "replied"
    bounced      = "bounced"
    error        = "error"


class Contact(Base):
    __tablename__ = "contacts"

    id            = Column(Integer, primary_key=True, index=True)
    campaign_id   = Column(Integer, ForeignKey("campaigns.id"), nullable=True)

    # Basic info from uploaded CSV
    name          = Column(String(200), nullable=False)
    email         = Column(String(200), nullable=False, unique=True, index=True)
    linkedin_url  = Column(String(500), nullable=True)
    company       = Column(String(200), nullable=True)
    job_title     = Column(String(200), nullable=True)

    # Free personalization inputs
    company_website       = Column(String(500), nullable=True)
    personalization_notes = Column(Text, nullable=True)

    # Website/company enrichment data
    company_summary     = Column(Text, nullable=True)
    company_signals     = Column(Text, nullable=True)
    company_pain_points = Column(Text, nullable=True)
    enrichment_source   = Column(String(100), nullable=True)

    # Optional LinkedIn/manual data. Keep these fields for backward compatibility.
    linkedin_headline    = Column(Text, nullable=True)
    linkedin_summary     = Column(Text, nullable=True)
    linkedin_experience  = Column(Text, nullable=True)
    linkedin_skills      = Column(Text, nullable=True)
    enriched_at          = Column(DateTime, nullable=True)

    # Email drafts & sending
    email_subject        = Column(Text, nullable=True)
    email_body           = Column(Text, nullable=True)
    email_sent_at        = Column(DateTime, nullable=True)
    followup_count       = Column(Integer, default=0)
    last_followup_at     = Column(DateTime, nullable=True)
    next_followup_at     = Column(DateTime, nullable=True)

    # Status
    status        = Column(SAEnum(ContactStatus), default=ContactStatus.pending, index=True)
    error_message = Column(Text, nullable=True)

    created_at    = Column(DateTime, default=datetime.utcnow)
    updated_at    = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    campaign      = relationship("Campaign", back_populates="contacts")
    activities    = relationship("Activity", back_populates="contact", cascade="all, delete-orphan")


class Campaign(Base):
    __tablename__ = "campaigns"

    id            = Column(Integer, primary_key=True, index=True)
    name          = Column(String(200), nullable=False)
    description   = Column(Text, nullable=True)

    # Your product / offer context
    your_name         = Column(String(200), nullable=True)
    your_company      = Column(String(200), nullable=True)
    your_role         = Column(String(200), nullable=True)
    value_proposition = Column(Text, nullable=True)

    # Follow-up schedule (days after initial send)
    followup_days     = Column(String(50), default="3,7,14")
    max_followups     = Column(Integer, default=3)

    is_active     = Column(Boolean, default=True)
    created_at    = Column(DateTime, default=datetime.utcnow)

    contacts      = relationship("Contact", back_populates="campaign", cascade="all, delete-orphan")


class Activity(Base):
    __tablename__ = "activities"

    id            = Column(Integer, primary_key=True, index=True)
    contact_id    = Column(Integer, ForeignKey("contacts.id"), nullable=False)
    activity_type = Column(String(50), nullable=False)
    detail        = Column(Text, nullable=True)
    created_at    = Column(DateTime, default=datetime.utcnow)

    contact       = relationship("Contact", back_populates="activities")
