"""
Unit tests for data models and schema validation.
"""

from src.models import CompanyIntelligence, JobOpening, ScrapedData


def test_job_opening_defaults():
    job = JobOpening(title="Software Engineer")
    assert job.title == "Software Engineer"
    assert job.department == "Engineering"
    assert job.experience_level == "Unknown"
    assert job.tech_stack == []
    assert job.is_computer_eng_relevant is True
    assert job.apply_url is None


def test_job_opening_custom_values():
    job = JobOpening(
        title="Embedded C++ Engineer",
        department="Hardware/Firmware",
        experience_level="2-4 years",
        tech_stack=["C++", "FreeRTOS", "UART", "STM32"],
        is_computer_eng_relevant=True,
        apply_url="https://keka.com/jobs/123",
    )
    assert job.title == "Embedded C++ Engineer"
    assert "C++" in job.tech_stack
    assert job.apply_url == "https://keka.com/jobs/123"


def test_company_intelligence_aliases_and_normalization():
    # Test with Part 1 naming: goa_office_locations, application_contact_email
    data1 = {
        "company_name": "Spintly",
        "goa_office_locations": ["Verna", "Panaji"],
        "core_domain": "SaaS / Access Control",
        "primary_tech_stack": ["React", "Node.js", "C++", "BLE"],
        "hiring_status": "Actively Hiring",
        "active_openings": [
            {
                "title": "Full Stack Dev",
                "tech_stack": ["React", "Python"],
                "experience_level": "Senior",
            }
        ],
        "application_contact_email": "careers@spintly.com",
        "summary_explanation": "Spintly designs cloud access control in Verna, Goa.",
    }
    intel1 = CompanyIntelligence.model_validate(data1)
    assert intel1.company_name == "Spintly"
    assert intel1.goa_locations == ["Verna", "Panaji"]
    assert intel1.goa_office_locations == ["Verna", "Panaji"]
    assert intel1.careers_email == "careers@spintly.com"
    assert intel1.hiring_status == "Actively Hiring"

    # Test with Part 2 naming: goa_locations, careers_email, alternate status
    data2 = {
        "company_name": "Teknorix Systems",
        "goa_locations": ["Verna"],
        "core_domain": "Enterprise Software",
        "primary_tech_stack": [".NET", "Angular", "Azure"],
        "hiring_status": "Open Applications / Email Resume",
        "careers_email": "hr@teknorix.com",
        "active_openings": [],
        "summary_explanation": "Teknorix builds custom cloud software.",
    }
    intel2 = CompanyIntelligence.model_validate(data2)
    assert intel2.company_name == "Teknorix Systems"
    assert intel2.goa_office_locations == ["Verna"]
    assert intel2.application_contact_email == "hr@teknorix.com"
    # Status should be normalized
    assert intel2.hiring_status == "Open Applications Only"


def test_company_intelligence_status_normalization_edge_cases():
    test_cases = [
        ("actively hiring right now", "Actively Hiring"),
        ("email resume to apply", "Open Applications Only"),
        ("no listed openings currently", "No Listed Openings"),
        ("unknown status", "Unknown"),
        ("", "Unknown"),
    ]
    for raw_status, expected in test_cases:
        intel = CompanyIntelligence(
            company_name="Test Company",
            core_domain="IT",
            hiring_status=raw_status,  # type: ignore
        )
        assert intel.hiring_status == expected


def test_scraped_data_model():
    scraped = ScrapedData(
        company_name="Test Co",
        homepage_text="Welcome to Test Co",
        careers_page_text="We are hiring!",
        rss_summary="Latest news...",
        ats_links=["https://keka.com/testco"],
        needs_search_grounding=False,
    )
    assert scraped.company_name == "Test Co"
    assert len(scraped.ats_links) == 1
    assert scraped.used_playwright is False
