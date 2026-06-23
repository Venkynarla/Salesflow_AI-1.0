"""
Pipeline service:
Free company website enrichment -> AI draft -> optional send -> follow-up scheduling.

This version does not depend on LinkedIn scraping. LinkedIn fields are kept only as optional/manual context.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from backend.models.database import SessionLocal
from backend.models.db import Activity, Campaign, Contact, ContactStatus
from backend.services.ai_generator import generate_followup_email, generate_initial_email
from backend.services.company_enrichment import enrich_company_website
from backend.services.email_sender import send_email

logger = logging.getLogger(__name__)

_PROGRESS: dict[int, dict] = {}


def set_progress(contact_id: int, percent: int, step: str, status: str = "running") -> None:
    percent = max(0, min(100, int(percent)))
    _PROGRESS[int(contact_id)] = {
        "contact_id": int(contact_id),
        "percent": percent,
        "step": step,
        "status": status,
        "updated_at": datetime.utcnow().isoformat(),
    }


def get_progress(contact_id: int) -> dict:
    return _PROGRESS.get(
        int(contact_id),
        {
            "contact_id": int(contact_id),
            "percent": 0,
            "step": "Not started",
            "status": "idle",
            "updated_at": datetime.utcnow().isoformat(),
        },
    )


def _log_activity(db: Session, contact_id: int, activity_type: str, detail: str = "") -> None:
    try:
        db.add(Activity(contact_id=contact_id, activity_type=activity_type, detail=detail))
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Failed to log activity for contact %s", contact_id)


def _set_status(db: Session, contact: Contact, status: ContactStatus, error: Optional[str] = None) -> None:
    contact.status = status
    contact.error_message = error
    contact.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(contact)


def _sender_context(contact: Contact) -> dict:
    campaign: Optional[Campaign] = contact.campaign
    return {
        "your_name": campaign.your_name if campaign and campaign.your_name else "Venkat",
        "your_company": campaign.your_company if campaign and campaign.your_company else "Innominds",
        "your_role": campaign.your_role if campaign and campaign.your_role else "",
        "value_proposition": (
            campaign.value_proposition
            if campaign and campaign.value_proposition
            else "AI workflow automation, data engineering, cloud modernization, and digital product engineering"
        ),
    }


def build_prospect_context(contact: Contact) -> str:
    return f"""
Name: {contact.name or ''}
Email: {contact.email or ''}
Company: {contact.company or ''}
Title: {contact.job_title or ''}
Company website: {contact.company_website or ''}

Uploaded personalization notes:
{contact.personalization_notes or ''}

Company website summary:
{contact.company_summary or ''}

Company signals:
{contact.company_signals or ''}

Likely pain points:
{contact.company_pain_points or ''}

Optional LinkedIn/manual headline:
{contact.linkedin_headline or ''}

Optional LinkedIn/manual summary:
{contact.linkedin_summary or ''}

Optional LinkedIn/manual experience:
{contact.linkedin_experience or ''}

Optional LinkedIn/manual skills:
{contact.linkedin_skills or ''}
""".strip()


async def run_enrichment(db: Session, contact: Contact, auto_draft: bool = True) -> None:
    """Enrich a contact using free company website data and optionally generate a draft."""
    contact_id = contact.id
    set_progress(contact_id, 5, "Starting company enrichment")
    _set_status(db, contact, ContactStatus.enriching)

    try:
        if contact.company_website:
            set_progress(contact_id, 25, "Reading company website")
            company_data = await enrich_company_website(
                contact.company_website,
                contact.company or "",
                contact.job_title or "",
            )
        else:
            set_progress(contact_id, 40, "No company website. Using uploaded contact details")
            company_data = await enrich_company_website(
                "",
                contact.company or "",
                contact.job_title or "",
            )

        contact.company_summary = company_data.get("company_summary") or contact.company_summary
        contact.company_signals = company_data.get("company_signals") or contact.company_signals
        contact.company_pain_points = company_data.get("company_pain_points") or contact.company_pain_points
        contact.enrichment_source = company_data.get("enrichment_source") or "uploaded_data_only"
        contact.enriched_at = datetime.utcnow()
        contact.status = ContactStatus.enriched
        contact.error_message = None
        contact.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(contact)

        set_progress(contact_id, 70, "Company enrichment saved")
        _log_activity(db, contact.id, "enriched", f"Source: {contact.enrichment_source}")

        if auto_draft:
            await run_email_draft(db, contact, start_percent=72, end_percent=100)
        else:
            set_progress(contact_id, 100, "Enrichment completed", "completed")

    except Exception as e:
        logger.exception("Enrichment failed for contact %s", contact_id)
        db.rollback()
        _set_status(db, contact, ContactStatus.error, str(e))
        _log_activity(db, contact_id, "error", f"Enrichment failed: {e}")
        set_progress(contact_id, 100, f"Error: {e}", "error")


async def run_email_draft(
    db: Session,
    contact: Contact,
    start_percent: int = 10,
    end_percent: int = 100,
) -> None:
    """Generate or regenerate a personalised email draft."""
    contact_id = contact.id
    set_progress(contact_id, start_percent, "Preparing AI prompt")
    _set_status(db, contact, ContactStatus.drafting)

    try:
        prospect_context = build_prospect_context(contact)
        sender_context = _sender_context(contact)

        set_progress(contact_id, min(end_percent - 20, 85), "Generating personalized email draft")
        draft = await generate_initial_email(prospect_context, sender_context)

        contact.email_subject = draft.get("subject") or f"Quick thought, {contact.name}"
        contact.email_body = draft.get("body") or ""
        contact.status = ContactStatus.draft_ready
        contact.error_message = None
        contact.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(contact)

        _log_activity(db, contact.id, "draft_ready", f"Subject: {contact.email_subject}")
        set_progress(contact_id, end_percent, "Draft ready", "completed")

    except Exception as e:
        logger.exception("Draft generation failed for contact %s", contact_id)
        db.rollback()
        _set_status(db, contact, ContactStatus.error, str(e))
        _log_activity(db, contact_id, "error", f"Draft failed: {e}")
        set_progress(contact_id, 100, f"Error: {e}", "error")


async def run_send_email(db: Session, contact: Contact) -> None:
    """Send the approved email draft."""
    if not contact.email_subject or not contact.email_body:
        _set_status(db, contact, ContactStatus.error, "No email draft to send")
        return

    try:
        success = await send_email(
            to_email=contact.email,
            to_name=contact.name,
            subject=contact.email_subject,
            body=contact.email_body,
        )

        if success:
            contact.email_sent_at = datetime.utcnow()
            campaign = contact.campaign
            if campaign and campaign.followup_days:
                days = [int(d.strip()) for d in campaign.followup_days.split(",") if d.strip().isdigit()]
                if days:
                    contact.next_followup_at = datetime.utcnow() + timedelta(days=days[0])
            _set_status(db, contact, ContactStatus.sent)
            _log_activity(db, contact.id, "email_sent", contact.email_subject)
        else:
            _set_status(db, contact, ContactStatus.bounced, "SMTP send failed")
    except Exception as e:
        logger.exception("Send failed for contact %s", contact.id)
        _set_status(db, contact, ContactStatus.error, str(e))


async def run_followup(db: Session, contact: Contact) -> None:
    """Generate and send the next follow-up."""
    try:
        campaign = contact.campaign
        if not campaign:
            return

        prospect_context = build_prospect_context(contact)
        sender_context = _sender_context(contact)
        followup_number = (contact.followup_count or 0) + 1

        draft = await generate_followup_email(
            prospect_context=prospect_context,
            sender_context=sender_context,
            original_subject=contact.email_subject or "Quick thought",
            followup_number=followup_number,
        )

        success = await send_email(
            to_email=contact.email,
            to_name=contact.name,
            subject=draft["subject"],
            body=draft["body"],
        )

        if success:
            contact.followup_count = followup_number
            contact.last_followup_at = datetime.utcnow()

            days = [int(d.strip()) for d in (campaign.followup_days or "").split(",") if d.strip().isdigit()]
            if followup_number < (campaign.max_followups or 0) and followup_number < len(days):
                contact.next_followup_at = datetime.utcnow() + timedelta(days=days[followup_number])
            else:
                contact.next_followup_at = None

            contact.status = ContactStatus.followed_up
            contact.updated_at = datetime.utcnow()
            db.commit()
            _log_activity(db, contact.id, "followup_sent", f"Follow-up #{followup_number}: {draft['subject']}")
    except Exception as e:
        logger.exception("Follow-up failed for contact %s", contact.id)
        _set_status(db, contact, ContactStatus.error, str(e))


async def run_full_pipeline(db: Session, contact: Contact, auto_send: bool = False) -> None:
    """Run enrich -> draft -> optional send."""
    await run_enrichment(db, contact, auto_draft=True)
    db.refresh(contact)

    if auto_send and contact.status == ContactStatus.draft_ready:
        contact.status = ContactStatus.approved
        db.commit()
        await run_send_email(db, contact)


async def run_enrichment_for_contact(contact_id: int, auto_draft: bool = True) -> None:
    db = SessionLocal()
    try:
        contact = db.query(Contact).filter(Contact.id == contact_id).first()
        if not contact:
            set_progress(contact_id, 100, "Contact not found", "error")
            return
        await run_enrichment(db, contact, auto_draft=auto_draft)
    finally:
        db.close()


async def run_email_draft_for_contact(contact_id: int) -> None:
    db = SessionLocal()
    try:
        contact = db.query(Contact).filter(Contact.id == contact_id).first()
        if not contact:
            set_progress(contact_id, 100, "Contact not found", "error")
            return
        await run_email_draft(db, contact)
    finally:
        db.close()


async def run_full_pipeline_for_contact(contact_id: int, auto_send: bool = False) -> None:
    db = SessionLocal()
    try:
        contact = db.query(Contact).filter(Contact.id == contact_id).first()
        if not contact:
            set_progress(contact_id, 100, "Contact not found", "error")
            return
        await run_full_pipeline(db, contact, auto_send=auto_send)
    finally:
        db.close()


async def run_send_email_for_contact(contact_id: int) -> None:
    db = SessionLocal()
    try:
        contact = db.query(Contact).filter(Contact.id == contact_id).first()
        if contact:
            await run_send_email(db, contact)
    finally:
        db.close()


async def process_due_followups(db: Session) -> None:
    """Scheduler tick: process due follow-ups."""
    now = datetime.utcnow()
    due = (
        db.query(Contact)
        .filter(
            Contact.next_followup_at.isnot(None),
            Contact.next_followup_at <= now,
            Contact.status.in_([ContactStatus.sent, ContactStatus.followed_up]),
        )
        .all()
    )

    logger.info("Scheduler: %s contacts due for follow-up", len(due))
    for contact in due:
        await run_followup(db, contact)
