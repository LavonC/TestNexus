"""
In-memory PDF extraction and parsing engine for government circulars and job notices.
Extracts advertisement numbers, posts, departments, qualifications, and deadlines
from bytes streams using pypdf with zero disk footprint.
"""

from __future__ import annotations

import io
import logging
import re

import pypdf

from src.models import JobOpening

logger = logging.getLogger(__name__)

# Keywords identifying Computer Science / IT / Computer Engineering relevance
CE_RELEVANT_KEYWORDS = [
    "computer",
    "information technology",
    "software",
    "programmer",
    "coding",
    "cyber",
    "data science",
    "system analyst",
    "network engineer",
    "hardware",
    "electronics",
    "technical officer",
    "web developer",
    "database",
    "infotech",
    "ditec",
]

# Common tech stacks extracted from government engineering syllabus / qualifications
GOVT_CE_TECH_TERMS = [
    ("python", "Python"),
    ("c\\+\\+", "C++"),
    ("\\bc\\b", "C"),
    ("java\\b", "Java"),
    ("sql", "SQL"),
    ("database", "Database Management"),
    ("networking", "Networking"),
    ("cyber", "Cybersecurity"),
    ("linux", "Linux"),
    ("embedded", "Embedded Systems"),
    ("cloud", "Cloud Computing"),
    ("ai\\b|artificial intelligence", "Artificial Intelligence"),
    ("machine learning", "Machine Learning"),
]


def extract_text_from_pdf_bytes(pdf_bytes: bytes, max_pages: int = 15) -> str:
    """
    Extract text content from raw PDF bytes in-memory.
    Limits extraction to max_pages to keep memory usage and latency bounded.
    """
    if not pdf_bytes:
        return ""

    try:
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception as dec_err:
                logger.debug("Failed to decrypt PDF with empty password: %s", dec_err)

        total_pages = len(reader.pages)
        pages_to_extract = min(total_pages, max_pages)

        text_parts: list[str] = []
        for i in range(pages_to_extract):
            try:
                page = reader.pages[i]
                page_text = page.extract_text() or ""
                if page_text.strip():
                    text_parts.append(page_text.strip())
            except Exception as e:
                logger.debug("Failed to extract page %d: %s", i + 1, e)

        full_text = "\n\n".join(text_parts)
        # Normalize carriage returns and multiple blank lines
        cleaned = re.sub(r"\r\n|\r", "\n", full_text)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        res_text = cleaned.strip()
        if not res_text and total_pages > 0:
            logger.info("PDF has %d pages but zero extractable text (likely a scanned raster image).", total_pages)
        return res_text

    except Exception as exc:
        logger.warning("Error reading PDF bytes: %s", exc)
        return ""


def extract_advertisement_number(text: str) -> str | None:
    """Extract advertisement reference number (e.g. Advt. No. 04/2026, Advt. 01/Year 2026)."""
    patterns = [
        r"(?:ADVERTISEMENT|ADVT\.?)\s*(?:NO\.?|NUMBER)?\s*[:.-]?\s*([0-9]{1,3}\s*(?:\/|\s*Year\s*)[0-9]{2,4})",
        r"(?:ADVERTISEMENT|ADVT\.?)\s*(?:NO\.?|NUMBER)?\s*[:.-]?\s*([0-9]{1,3}\s*[\/-]\s*[0-9]{4})",
        r"(?:Notice\s*No\.?)\s*[:.-]?\s*([0-9A-Za-z\/\-_]+)",
        r"(?:Advt\.\s*No\.\s*)([0-9]+(?:\/[0-9]+)?)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            raw = m.group(1).strip()
            # Clean up whitespace
            cleaned = re.sub(r"\s+", " ", raw)
            return f"Advt. No. {cleaned}"
    return None


def extract_application_deadline(text: str) -> str | None:
    """Extract last date for online application submission."""
    patterns = [
        r"(?:last\s+date|closing\s+date|applications\s+accepted\s+upto)[^\n\d]*?([0-9]{1,2}[./-][0-9]{1,2}[./-][0-9]{2,4})",
        r"(?:last\s+date|closing\s+date|applications\s+accepted\s+upto)[^\n\d]*?([0-9]{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+[0-9]{4})",
        r"(?:upto|till)\s*[:.-]?\s*([0-9]{1,2}[./-][0-9]{1,2}[./-][0-9]{2,4})",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None


def extract_department(block: str) -> str:
    """Extract government department or institution name from text block."""
    dept_patterns = [
        r"((?:Department|Directorate|Corporation|Commission)\s+of\s+[A-Za-z\s&]+?)(?:\n|\.|\,|$)",
        r"([A-Za-z\s]+College\s+of\s+Engineering)",
        r"(Goa\s+Engineering\s+College|Government\s+Polytechnic[A-Za-z\s]*)",
        r"(Directorate\s+of\s+Technical\s+Education)",
        r"(Department\s+of\s+Information\s+Technology[A-Za-z\s,]*)",
    ]
    for pat in dept_patterns:
        m = re.search(pat, block, re.IGNORECASE)
        if m:
            val = m.group(1).strip()
            if 4 < len(val) < 80:
                return val.title()
    return "Government of Goa / GPSC"


def parse_government_job_pdf(text: str, pdf_url: str = "") -> list[JobOpening]:
    """
    Parse government recruitment circular/advertisement text into structured JobOpening models.
    Identifies discrete posts, department, qualifications, deadlines, and computer engineering relevance.
    """
    if not text or len(text.strip()) < 50:
        return []

    advt_no = extract_advertisement_number(text) or "Govt Recruitment Notice"
    deadline = extract_application_deadline(text)

    # Standard online portal fallback for Goa govt recruitment
    apply_url = pdf_url or "https://gpsconline.goa.gov.in"

    # Split text into numbered post sections
    # Handles: "\n1.", "\n  1. ", "\n(1)", "\nItem 1", "\nPost 1:"
    post_blocks = re.split(
        r"(?:\n[ \t]*(?:[0-9]{1,2}\.|\([0-9]{1,2}\)|Item\s+No\.?\s*[0-9]+|Post(?:\s+No\.?)?\s*[:.-]?)\s+)",
        text,
    )

    openings: list[JobOpening] = []

    candidate_blocks: list[str] = []
    if len(post_blocks) > 1:
        # Candidate blocks 1 onwards are the individual posts
        candidate_blocks = post_blocks[1:]
    else:
        candidate_blocks = [text]

    for block in candidate_blocks:
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        if not lines:
            continue

        # Look specifically at line 0 or line 1 for post title
        title = None
        for cand_line in lines[:2]:
            cand_clean = re.sub(
                r"^(?:name\s+of\s+(?:the\s+)?post|post|item\s+no\.?)\s*[:.-]?\s*",
                "",
                cand_line.strip(" :.-,"),
                flags=re.IGNORECASE,
            ).strip(" :.-,")
            # If line has typical title keywords
            if any(
                kw in cand_clean.lower()
                for kw in (
                    "engineer", "professor", "lecturer", "programmer", "officer",
                    "analyst", "developer", "technician", "assistant", "director",
                    "manager", "scientist", "administrator", "specialist",
                    "instructor", "consultant", "lead", "architect", "operator"
                )
            ) and len(cand_clean) <= 90:
                title = cand_clean
                break

        if not title:
            # Try regex on first line, stripping boilerplate prefixes
            cand_raw = re.sub(
                r"^(?:name\s+of\s+(?:the\s+)?post|post|item\s+no\.?)\s*[:.-]?\s*",
                "",
                lines[0].strip(" :.-,"),
                flags=re.IGNORECASE,
            ).strip(" :.-,")
            m = re.search(r"([A-Za-z\s\/\(\)\,\.\-]{4,80})", cand_raw)
            if m and len(m.group(1).strip()) <= 90:
                title = m.group(1).strip(" :.-,")

        if not title or len(title) < 4:
            continue

        clean_title = re.sub(r"\s+", " ", title).title()
        if advt_no and advt_no not in clean_title:
            display_title = f"{clean_title} ({advt_no})"
        else:
            display_title = clean_title

        dept = extract_department(block)

        # Detect experience / qualification snippets
        exp_level = "Degree / Post Graduate"
        if re.search(r"fresher|entry\s*level|no\s*experience", block, re.IGNORECASE):
            exp_level = "Fresher / Degree"
        elif re.search(r"([0-9]{1,2})\s*years?\s*experience", block, re.IGNORECASE):
            exp_m = re.search(r"([0-9]{1,2})\s*years?\s*experience", block, re.IGNORECASE)
            if exp_m:
                exp_level = f"{exp_m.group(1)}+ years experience"

        # Check Computer Engineering / CS / IT relevance
        comb_text = f"{clean_title} {block}".lower()
        is_ce = any(k in comb_text for k in CE_RELEVANT_KEYWORDS)

        # Extract relevant tech tags
        tech_tags: list[str] = []
        for pat, tag_name in GOVT_CE_TECH_TERMS:
            if re.search(pat, comb_text, re.IGNORECASE):
                if tag_name not in tech_tags:
                    tech_tags.append(tag_name)

        if is_ce and not tech_tags:
            tech_tags = ["Computer Engineering", "Information Technology"]

        openings.append(
            JobOpening(
                title=display_title,
                department=dept,
                experience_level=f"{exp_level} (Deadline: {deadline})" if deadline else exp_level,
                tech_stack=tech_tags,
                is_computer_eng_relevant=is_ce,
                apply_url=apply_url,
                source_type="PDF",
                source_url=pdf_url or None,
            )
        )

    # If no structured posts found but whole document is clearly a vacancy notice
    if not openings and len(text) > 100:
        if any(kw in text.lower() for kw in ("vacancy", "advertisement", "recruitment", "posts", "applications are invited")):
            is_ce = any(kw in text.lower() for kw in CE_RELEVANT_KEYWORDS)
            openings.append(
                JobOpening(
                    title=f"Government Recruitment Circular ({advt_no})",
                    department=extract_department(text),
                    experience_level=f"See Circular (Deadline: {deadline})" if deadline else "See Official Notice",
                    tech_stack=["Computer Engineering"] if is_ce else [],
                    is_computer_eng_relevant=is_ce,
                    apply_url=apply_url,
                    source_type="PDF",
                    source_url=pdf_url or None,
                )
            )

    return openings
