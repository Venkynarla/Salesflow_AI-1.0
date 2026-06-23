"""Free company enrichment using public website pages.

This replaces the old LinkedIn-first approach with a safer, free workflow:
company website -> extracted context -> signals/pain points -> AI draft.
"""

from __future__ import annotations

import re
from typing import Dict, List
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup


DEFAULT_PATHS = [
    "",
    "/about",
    "/about-us",
    "/services",
    "/solutions",
    "/products",
    "/platform",
    "/customers",
    "/case-studies",
    "/blog",
    "/news",
    "/careers",
    "/jobs",
]


def clean_text(text: str, limit: int = 6000) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text[:limit]


def normalize_url(url: str | None) -> str:
    if not url:
        return ""
    url = str(url).strip()
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def _same_domain(base_url: str, candidate_url: str) -> bool:
    try:
        base = urlparse(base_url).netloc.replace("www.", "")
        candidate = urlparse(candidate_url).netloc.replace("www.", "")
        return bool(base and candidate and base == candidate)
    except Exception:
        return False


async def fetch_page(url: str) -> str:
    """Fetch a public page and return clean visible text only."""
    if not url:
        return ""
    try:
        async with httpx.AsyncClient(timeout=12, follow_redirects=True) as client:
            response = await client.get(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (compatible; SalesFlowResearchBot/1.0; "
                        "+https://example.com/bot)"
                    )
                },
            )
            if response.status_code >= 400:
                return ""

            soup = BeautifulSoup(response.text, "html.parser")
            for tag in soup(["script", "style", "svg", "noscript", "nav", "footer", "header", "form"]):
                tag.decompose()
            return clean_text(soup.get_text(" "), 3000)
    except Exception:
        return ""


def _discover_relevant_links(base_url: str, html_text: str) -> List[str]:
    """Best-effort link discovery from homepage HTML text is intentionally simple here.

    We keep the crawler conservative to avoid scraping aggressively.
    """
    return [urljoin(base_url, path) for path in DEFAULT_PATHS]


def extract_signals(text: str) -> str:
    low = (text or "").lower()
    signals: list[str] = []

    checks = [
        (("hiring", "careers", "join our team", "open roles", "job openings"), "Hiring or team growth signal"),
        (("ai", "artificial intelligence", "automation", "machine learning", "genai"), "AI or automation interest signal"),
        (("cloud", "platform", "saas", "api", "developer"), "Cloud/platform modernization signal"),
        (("enterprise", "global", "large organizations"), "Enterprise customer focus"),
        (("case study", "customers", "trusted by", "success story"), "Customer proof or case-study signal"),
        (("launch", "new product", "announced", "release"), "Product launch or recent initiative signal"),
        (("security", "compliance", "governance", "privacy"), "Security/compliance priority signal"),
        (("sales", "revenue", "pipeline", "crm"), "Sales/revenue operations signal"),
    ]

    for keywords, label in checks:
        if any(k in low for k in keywords) and label not in signals:
            signals.append(label)

    return ", ".join(signals[:6])


def infer_basic_pain_points(text: str, title: str = "") -> str:
    low = f"{text or ''} {title or ''}".lower()
    pains: list[str] = []

    if any(k in low for k in ["sales", "revenue", "pipeline", "sdr", "outbound", "crm"]):
        pains.append("scaling outbound/revenue operations")
    if any(k in low for k in ["data", "analytics", "dashboard", "insights", "reporting"]):
        pains.append("data quality, reporting, and decision visibility")
    if any(k in low for k in ["manual", "workflow", "operations", "process", "back office"]):
        pains.append("manual workflow automation")
    if any(k in low for k in ["cloud", "platform", "api", "saas", "engineering"]):
        pains.append("platform reliability and cloud modernization")
    if any(k in low for k in ["security", "compliance", "governance", "privacy"]):
        pains.append("security, governance, and compliance")
    if any(k in low for k in ["customer", "support", "experience", "engagement"]):
        pains.append("customer experience and support efficiency")

    return ", ".join(pains[:5])


async def enrich_company_website(company_website: str | None, company: str = "", title: str = "") -> Dict[str, str]:
    """Return free enrichment data from a company's public website."""
    base = normalize_url(company_website)
    if not base:
        return {
            "company_summary": "",
            "company_signals": "",
            "company_pain_points": infer_basic_pain_points(company or "", title),
            "enrichment_source": "uploaded_data_only",
        }

    urls = _discover_relevant_links(base, "")
    collected: list[str] = []
    seen: set[str] = set()

    for url in urls:
        if url in seen or not _same_domain(base, url):
            continue
        seen.add(url)
        text = await fetch_page(url)
        if text and len(text) > 120:
            collected.append(f"URL: {url}\n{text}")
        if len("\n\n".join(collected)) > 12000:
            break

    combined = "\n\n".join(collected)
    if not combined:
        return {
            "company_summary": "",
            "company_signals": "",
            "company_pain_points": infer_basic_pain_points(company or "", title),
            "enrichment_source": "website_failed",
        }

    return {
        "company_summary": clean_text(combined, 7000),
        "company_signals": extract_signals(combined),
        "company_pain_points": infer_basic_pain_points(combined, title),
        "enrichment_source": "company_website",
    }
