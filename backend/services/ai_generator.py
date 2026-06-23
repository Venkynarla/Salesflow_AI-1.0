"""
AI email generation service.
Uses NVIDIA's OpenAI-compatible API by default.

Drafting goal:
- Prioritize uploaded notes and company website signals.
- Use job title/company only as a fallback.
- Write short, natural, useful B2B outreach.
"""

import json
import logging
import os
import re
from typing import Any, Dict

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
logger = logging.getLogger(__name__)

NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "")
MODEL = os.getenv("NVIDIA_MODEL", "meta/llama-3.1-70b-instruct")

client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=NVIDIA_API_KEY,
)

INITIAL_SYSTEM = """
You are an expert B2B cold email strategist.

Write highly personalized outbound emails using:
1. Uploaded personalization notes
2. Company website summary
3. Company signals
4. Prospect job title
5. Sender value proposition

Strict rules:
1. Do NOT return JSON.
2. Return exactly this format:
SUBJECT: <short human subject, max 7 words>

BODY:
Hi <First Name>,

<paragraph 1: one specific observation from uploaded notes, website summary, company signals, title, or company. No fake flattery.>

<paragraph 2: connect that observation to 1-2 likely business pain points this person may own.>

<paragraph 3: softly introduce sender solution and ask for a short conversation.>

Best,
<sender name>
3. Do not mention LinkedIn unless LinkedIn/manual data is clearly provided.
4. Do not say "I saw" unless the source clearly supports it.
5. Do not invent funding, hiring, partnerships, customers, or achievements.
6. Avoid hype words like revolutionary, cutting-edge, game-changing, synergy, transform.
7. Keep body under 130 words.
8. If enrichment is weak, clearly base the email on title/company only.
9. Make the email feel manual, specific, and low-pressure.
"""

FOLLOWUP_SYSTEM = """
You are writing a brief B2B follow-up email.
Return exactly this format:
SUBJECT: Re: <original subject>

BODY:
Hi <First Name>,

<short follow-up around the same specific pain point, not generic checking-in>

Best,
<sender name>
"""


def _clean_body(body: str, subject: str = "") -> str:
    body = (body or "").strip()
    if body.startswith("{") and "body" in body:
        try:
            data = json.loads(body)
            subject = data.get("subject", subject)
            body = data.get("body", body)
        except Exception:
            pass
    body = re.sub(r"^BODY\s*:\s*", "", body, flags=re.I).strip()
    body = re.sub(r"^Subject\s*:\s*.*?\n+", "", body, flags=re.I | re.S).strip()
    if subject:
        body = body.replace(subject, "").strip()
    body = body.replace("\\n", "\n")
    lines = [line.strip() for line in body.splitlines()]
    cleaned, blank = [], False
    for line in lines:
        if not line:
            if not blank:
                cleaned.append("")
            blank = True
        else:
            cleaned.append(line)
            blank = False
    return "\n".join(cleaned).strip()


def _parse_model_output(text: str) -> Dict[str, str]:
    raw = (text or "").strip()
    if not raw:
        raise ValueError("Empty model response")
    raw = re.sub(r"^```(?:json|text)?", "", raw, flags=re.I).strip()
    raw = re.sub(r"```$", "", raw).strip()
    if raw.startswith("{"):
        try:
            data = json.loads(raw)
            subject = str(data.get("subject", "Relevant idea")).strip()
            body = _clean_body(str(data.get("body", "")).strip(), subject)
            return {"subject": subject, "body": body}
        except Exception:
            pass
    subject = "Relevant idea"
    body = raw
    m = re.search(r"SUBJECT\s*:\s*(.+)", raw, flags=re.I)
    if m:
        subject = m.group(1).strip().strip('"')
    m = re.search(r"BODY\s*:\s*(.*)", raw, flags=re.I | re.S)
    if m:
        body = m.group(1).strip()
    return {"subject": subject, "body": _clean_body(body, subject)}


def _first_name_from_context(prospect_context: str) -> str:
    m = re.search(r"Name:\s*([^\n]+)", prospect_context or "")
    return m.group(1).strip().split()[0] if m else "there"


def _extract_line(prospect_context: str, label: str) -> str:
    m = re.search(rf"^{re.escape(label)}:\s*(.*)$", prospect_context or "", flags=re.I | re.M)
    return m.group(1).strip() if m else ""


def _extract_block(prospect_context: str, label: str) -> str:
    pattern = rf"{re.escape(label)}:\s*\n?(.*?)(?:\n\n[A-Z][A-Za-z /]+:|\Z)"
    m = re.search(pattern, prospect_context or "", flags=re.I | re.S)
    return m.group(1).strip() if m else ""


def _role_pain_points(title: str, company: str, context: str) -> str:
    t = (title or "").lower()
    ctx = (context or "").lower()
    joined = t + " " + ctx

    if any(x in joined for x in ["sales", "revenue", "growth", "sdr", "bd", "business development"]):
        return "scaling outbound, improving pipeline quality, reducing manual prospect research, and keeping personalization consistent"
    if any(x in joined for x in ["marketing", "demand gen", "growth"]):
        return "campaign conversion, audience segmentation, lead quality, and content-to-pipeline attribution"
    if any(x in joined for x in ["data", "analytics", "bi", "insights", "rwe", "real world"]):
        return "trusted data pipelines, dashboard adoption, self-service analytics, lineage, observability, and AI-ready data foundations"
    if any(x in joined for x in ["manufacturing", "quality", "operations", "supply", "plant", "mes", "scada"]):
        return "deviation reduction, batch visibility, predictive quality, workflow friction, and shopfloor data integration"
    if any(x in joined for x in ["digital", "product", "platform", "engineering", "technology", "cloud", "cto", "cio"]):
        return "platform reliability, cloud modernization, GenAI delivery, product engineering velocity, and governed automation"
    if any(x in joined for x in ["clinical", "medical", "regulatory", "r&d", "research"]):
        return "document-heavy workflows, evidence synthesis, compliant AI assistance, and fragmented clinical/scientific data"
    if any(x in joined for x in ["hr", "people", "talent", "recruiting"]):
        return "candidate operations, employee support workflows, knowledge access, and HR process automation"
    return "manual workflows, fragmented systems, data quality, AI adoption risk, and delivery velocity"


def _fallback_initial(sender_context: Dict[str, Any], prospect_context: str) -> Dict[str, str]:
    sender_name = sender_context.get("your_name") or os.getenv("EMAIL_FROM_NAME", "Venkat")
    sender_company = sender_context.get("your_company") or "Innominds"
    value_prop = sender_context.get("value_proposition") or "AI workflow automation, data engineering, and product engineering"
    first = _first_name_from_context(prospect_context)
    title = _extract_line(prospect_context, "Title")
    company = _extract_line(prospect_context, "Company")
    signals = _extract_block(prospect_context, "Company signals") or _extract_line(prospect_context, "Company signals")
    notes = _extract_block(prospect_context, "Uploaded personalization notes")
    pains = _extract_block(prospect_context, "Likely pain points") or _role_pain_points(title, company, prospect_context)

    if notes:
        opener = f"Noticed this context around {company or 'your team'}: {notes[:140]}"
    elif signals:
        opener = f"Noticed a few signals around {signals[:140]} at {company or 'your company'}"
    elif title or company:
        opener = f"Noticed your role{f' as {title}' if title else ''}{f' at {company}' if company else ''}"
    else:
        opener = "Noticed your team may be working through a few operational priorities"

    body = (
        f"Hi {first},\n\n"
        f"{opener}.\n\n"
        f"That often creates pressure around {pains}. {sender_company} helps teams with {value_prop} without adding extra operational complexity.\n\n"
        "Would it be worth a quick conversation to see if this is relevant?\n\n"
        f"Best,\n{sender_name}"
    )
    return {"subject": "Relevant idea", "body": body}


async def generate_initial_email(prospect_context: str, sender_context: Dict[str, Any], original_subject: str | None = None) -> Dict[str, str]:
    if not NVIDIA_API_KEY:
        logger.warning("NVIDIA_API_KEY is missing. Returning fallback email.")
        return _fallback_initial(sender_context, prospect_context)

    title = _extract_line(prospect_context, "Title")
    company = _extract_line(prospect_context, "Company")
    inferred_pains = _role_pain_points(title, company, prospect_context)

    user_prompt = f"""
Prospect context:
{prospect_context}

Conservative role-based pain point hints:
{inferred_pains}

Sender context:
Name: {sender_context.get('your_name', '')}
Company: {sender_context.get('your_company', '')}
Role: {sender_context.get('your_role', '')}
Value proposition: {sender_context.get('value_proposition', '')}

Task:
Write a short, highly personalized cold email.

Priority order:
1. Use uploaded personalization notes if available.
2. Use company signals if available.
3. Use company website summary if available.
4. Use job title and company as fallback.

The email should feel like it was written manually after researching the company, but it must not fabricate details.
""".strip()
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "system", "content": INITIAL_SYSTEM}, {"role": "user", "content": user_prompt}],
            temperature=0.35,
            max_tokens=600,
        )
        result = _parse_model_output(response.choices[0].message.content or "")
        if not result.get("body"):
            raise ValueError("Model returned empty body")
        return result
    except Exception as e:
        logger.exception("NVIDIA email generation failed: %s", e)
        return _fallback_initial(sender_context, prospect_context)


async def generate_followup_email(prospect_context: str, sender_context: Dict[str, Any], original_subject: str, followup_number: int) -> Dict[str, str]:
    if not NVIDIA_API_KEY:
        return {
            "subject": f"Re: {original_subject or 'Relevant idea'}",
            "body": f"Hi {_first_name_from_context(prospect_context)},\n\nWanted to resurface this in case the pain point is relevant to your current priorities.\n\nBest,\n{sender_context.get('your_name', '')}",
        }
    user_prompt = f"""
Prospect context:
{prospect_context}

Sender: {sender_context.get('your_name', '')} at {sender_context.get('your_company', '')}
Original subject: {original_subject}
Follow-up number: {followup_number}

Write a short follow-up around the same specific pain point. Use SUBJECT/BODY format only.
""".strip()
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "system", "content": FOLLOWUP_SYSTEM}, {"role": "user", "content": user_prompt}],
            temperature=0.3,
            max_tokens=380,
        )
        result = _parse_model_output(response.choices[0].message.content or "")
        if not result.get("subject", "").lower().startswith("re:"):
            result["subject"] = f"Re: {original_subject or result.get('subject','Relevant idea')}"
        return result
    except Exception as e:
        logger.exception("NVIDIA follow-up generation failed: %s", e)
        return {
            "subject": f"Re: {original_subject or 'Relevant idea'}",
            "body": f"Hi {_first_name_from_context(prospect_context)},\n\nWanted to resurface this in case the pain point is relevant.\n\nBest,\n{sender_context.get('your_name', '')}",
        }
