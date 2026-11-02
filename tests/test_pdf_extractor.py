"""
Unit tests for in-memory PDF extraction and government job parsing engine.
"""

from __future__ import annotations

import io

import pypdf

from src.pdf_extractor import (
    extract_advertisement_number,
    extract_application_deadline,
    extract_department,
    extract_text_from_pdf_bytes,
    parse_government_job_pdf,
)


def create_sample_pdf(text_lines: list[str]) -> bytes:
    """Helper to generate a valid PDF byte string with specified text lines."""
    stream_text = "BT\n/F1 12 Tf\n"
    y = 720
    for line in text_lines:
        # Escape parenthesis in PDF text
        safe_line = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream_text += f"72 {y} Td\n({safe_line}) Tj\n-72 -20 Td\n"
        y -= 20
    stream_text += "ET\n"
    stream_bytes = stream_text.encode("latin-1")
    length = len(stream_bytes)

    pdf = (
        b"%PDF-1.4\n"
        b"1 0 obj <</Type /Catalog /Pages 2 0 R>> endobj\n"
        b"2 0 obj <</Type /Pages /Kids [3 0 R] /Count 1>> endobj\n"
        b"3 0 obj <</Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R>> endobj\n"
        b"4 0 obj <</Type /Font /Subtype /Type1 /BaseFont /Helvetica>> endobj\n"
        + f"5 0 obj <</Length {length}>> stream\n".encode("ascii")
        + stream_bytes
        + b"endstream\nendobj\n"
        b"xref\n0 6\n0000000000 65535 f \n"
        b"0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n"
        b"0000000244 00000 n \n0000000318 00000 n \n"
        b"trailer <</Size 6 /Root 1 0 R>>\nstartxref\n500\n%%EOF\n"
    )
    return pdf


def test_extract_text_from_pdf_bytes_empty():
    assert extract_text_from_pdf_bytes(b"") == ""
    assert extract_text_from_pdf_bytes(b"garbage not a pdf") == ""


def test_extract_text_from_pdf_bytes_valid():
    lines = [
        "GOA PUBLIC SERVICE COMMISSION",
        "ADVERTISEMENT NO. 04/2026",
        "Applications are invited for the following posts",
    ]
    pdf_bytes = create_sample_pdf(lines)
    text = extract_text_from_pdf_bytes(pdf_bytes)
    assert "GOA PUBLIC SERVICE COMMISSION" in text
    assert "ADVERTISEMENT NO. 04/2026" in text


def test_extract_advertisement_number():
    t1 = "GOA PUBLIC SERVICE COMMISSION\nADVERTISEMENT NO. 04/2026\nOnline Applications..."
    assert extract_advertisement_number(t1) == "Advt. No. 04/2026"

    t2 = "GPSC NOTICE Advt. No. 12/Year 2026 dated 10-01-2026"
    assert "Advt. No." in (extract_advertisement_number(t2) or "")

    t3 = "No advertisement mentioned here"
    assert extract_advertisement_number(t3) is None


def test_extract_application_deadline():
    t1 = "Last date for submission of online applications is 28.02.2026."
    assert extract_application_deadline(t1) == "28.02.2026"

    t2 = "Online applications accepted upto 15th March 2026."
    assert "15th March 2026" in (extract_application_deadline(t2) or "")


def test_extract_department():
    t1 = "Directorate of Technical Education, Porvorim, Goa"
    assert "Directorate Of Technical Education" in extract_department(t1)

    t2 = "Post at Goa Engineering College, Farmagudi"
    assert "Goa Engineering College" in extract_department(t2)


def test_parse_government_job_pdf():
    sample_text = """
    GOA PUBLIC SERVICE COMMISSION
    ADVERTISEMENT NO. 03/2026
    Online applications are invited for the following posts. Last date for submission of online applications is 28.02.2026.

    1. ASSISTANT PROFESSOR IN COMPUTER ENGINEERING
    Goa Engineering College, Farmagudi, Ponda - Goa.
    Educational & Other Qualifications:
    Essential: Bachelor's and Master's degree in Computer Engineering or Computer Science with First Class.
    Experience with Python, C++, Database Management and Cloud Computing.

    2. JUNIOR ENGINEER (INFORMATION TECHNOLOGY)
    Department of Information Technology, Panaji, Goa.
    Essential: Degree in Information Technology or Computer Science from a recognized University.
    Knowledge of Networking, Linux, and SQL. 2 years experience desirable.

    3. MEDICAL OFFICER
    Directorate of Health Services, Campal, Panaji.
    Essential: MBBS Degree from a recognized institute.
    """

    openings = parse_government_job_pdf(sample_text, pdf_url="https://gpsc.goa.gov.in/advt03.pdf")

    assert len(openings) == 3

    # Check 1st opening
    ce_prof = next((j for j in openings if "Computer Engineering" in j.title), None)
    assert ce_prof is not None
    assert ce_prof.is_computer_eng_relevant is True
    assert ce_prof.source_type == "PDF"
    assert ce_prof.source_url == "https://gpsc.goa.gov.in/advt03.pdf"
    assert any("Python" in t for t in ce_prof.tech_stack)
    assert "28.02.2026" in ce_prof.experience_level

    # Check 2nd opening
    it_eng = next((j for j in openings if "Information Technology" in j.title), None)
    assert it_eng is not None
    assert it_eng.is_computer_eng_relevant is True
    assert any("Linux" in t for t in it_eng.tech_stack)

    # Check 3rd opening (Medical Officer - should NOT be CE relevant)
    med_off = next((j for j in openings if "Medical Officer" in j.title), None)
    assert med_off is not None
    assert med_off.is_computer_eng_relevant is False


def test_parse_government_job_pdf_cleans_post_prefix():
    text = """
    GOA PUBLIC SERVICE COMMISSION
    ADVERTISEMENT NO. 05/2026

    1. NAME OF THE POST: SYSTEM ADMINISTRATOR (INFORMATION TECHNOLOGY)
    Department of Information Technology, Porvorim, Goa.
    Qualifications: Degree in Computer Science with knowledge of Linux and Networking.
    """
    openings = parse_government_job_pdf(text)
    assert len(openings) == 1
    # Title must NOT retain 'Name of the Post:'
    assert not openings[0].title.lower().startswith("name of the post")
    assert "System Administrator" in openings[0].title
    assert openings[0].is_computer_eng_relevant is True


def test_extract_text_encrypted_blank_password():
    """Verify that PDFs encrypted with blank passwords decrypt and extract cleanly."""
    # Create a simple PDF using pypdf writer
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=72, height=72)
    # Encrypt with blank user password
    writer.encrypt("", "owner_secret")
    buf = io.BytesIO()
    writer.write(buf)
    encrypted_bytes = buf.getvalue()

    # extract_text_from_pdf_bytes should handle without crashing
    text = extract_text_from_pdf_bytes(encrypted_bytes)
    assert isinstance(text, str)
