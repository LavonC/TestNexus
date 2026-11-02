"""
Pydantic data models for structured intelligence extraction and storage.
"""

from __future__ import annotations

from typing import Literal

from pydantic import AliasChoices, BaseModel, Field, field_validator


class JobOpening(BaseModel):
    """Represents a discrete job opening identified at a company."""

    title: str = Field(
        ...,
        description="Job title, e.g., Software Engineer, Embedded C++ Developer, QA Analyst",
    )
    department: str = Field(
        default="Engineering",
        description="Department, e.g., Software Engineering, Embedded Systems, Product, QA",
    )
    experience_level: str = Field(
        default="Unknown",
        description="Experience level, e.g., Fresher/Intern, 1-3 years, Mid-Level, Senior, Lead, Unknown",
    )
    tech_stack: list[str] = Field(
        default_factory=list,
        description="Skills and technologies required/mentioned for this role (e.g., Python, C++, React, Docker)",
    )
    is_computer_eng_relevant: bool = Field(
        default=True,
        description="True if the role is relevant to Computer Science / Computer Engineering / IT graduates",
    )
    apply_url: str | None = Field(
        default=None,
        description="Direct application link, job posting URL, or ATS link (Zoho, Keka, LinkedIn, etc.)",
    )
    source_type: str = Field(
        default="WEB",
        description="Source format where the job was detected ('WEB', 'ATS', or 'PDF')",
    )
    source_url: str | None = Field(
        default=None,
        description="URL of source document or PDF if applicable",
    )
    application_deadline: str | None = Field(
        default=None,
        description="Application deadline date or timestamp if explicitly extracted (e.g. from govt circular)",
    )
    is_government: bool = Field(
        default=False,
        description="True if the posting is from a government portal, PSU, or autonomous body",
    )


HiringStatusType = Literal[
    "Actively Hiring",
    "Open Applications Only",
    "Open Applications / Email Resume",
    "No Listed Openings",
    "Unknown",
]


class CompanyIntelligence(BaseModel):
    """Structured intelligence extracted by Gemini 3.8 Flash for a Goan tech company."""

    company_name: str = Field(
        ..., description="Official or well-known name of the company"
    )

    goa_office_locations: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("goa_office_locations", "goa_locations"),
        description="Specific office locations within Goa (e.g., Verna, Panaji, Margao, Porvorim, Mapusa, Vasco)",
    )

    core_domain: str = Field(
        ...,
        description="Primary industry or business domain (e.g., SaaS, Embedded/IoT, Industrial Automation, IT Services, FinTech)",
    )

    primary_tech_stack: list[str] = Field(
        default_factory=list,
        description="Overall tech stack, languages, tools, and platforms utilized by the company",
    )

    hiring_status: HiringStatusType = Field(
        default="Unknown",
        description="Current hiring status category based on available data",
    )

    active_openings: list[JobOpening] = Field(
        default_factory=list,
        description="List of active job openings identified from scraping and search grounding",
    )

    recent_news_summary: str | None = Field(
        default=None,
        description="Summary of recent company news, product releases, or expansions synthesized from RSS and search",
    )

    application_contact_email: str | None = Field(
        default=None,
        validation_alias=AliasChoices("application_contact_email", "careers_email"),
        description="HR or careers contact email address if publicly mentioned (e.g., careers@company.com)",
    )

    summary_explanation: str | None = Field(
        default=None,
        description="A concise 2-3 sentence overview of what this company does in Goa and how a Computer Engineer fits in",
    )

    @property
    def goa_locations(self) -> list[str]:
        """Convenience alias for goa_office_locations."""
        return self.goa_office_locations

    @property
    def careers_email(self) -> str | None:
        """Convenience alias for application_contact_email."""
        return self.application_contact_email

    @field_validator("hiring_status", mode="before")
    @classmethod
    def normalize_hiring_status(cls, v: str) -> str:
        """Normalize varied hiring status strings to valid enum values."""
        if not v:
            return "Unknown"
        s = str(v).strip().lower()
        if "actively hiring" in s or "active" in s:
            return "Actively Hiring"
        if "email resume" in s or "open application" in s or "walk-in" in s:
            return "Open Applications Only"
        if "no listed" in s or "not hiring" in s or "none" in s:
            return "No Listed Openings"
        return "Unknown"


class CompanySeed(BaseModel):
    """Seed record representing a company target to scrape."""

    name: str
    website: str | None = None
    careers: str | None = None
    rss: str | None = None


class ScrapedData(BaseModel):
    """Aggregated raw and semi-structured scrape output for a company."""

    company_name: str
    homepage_text: str = ""
    careers_page_text: str = ""
    rss_summary: str = ""
    ats_links: list[str] = Field(default_factory=list)
    careers_fetch_failed: bool = False
    used_playwright: bool = False
    needs_search_grounding: bool = False
    pdf_openings: list[JobOpening] = Field(default_factory=list)


class BatchCompanyIntelligence(BaseModel):
    """Batch container for multi-company structured intelligence extraction."""

    companies: list[CompanyIntelligence] = Field(
        default_factory=list,
        description="List of structured company intelligence records extracted for the requested companies",
    )


class JobAlertCreate(BaseModel):
    """Payload to subscribe for job email alerts."""

    email: str
    tech_filter: list[str] = Field(default_factory=list)
    location_filter: list[str] = Field(default_factory=list)
    experience_filter: str | None = None
    ce_only: bool = False


class JobAlertResponse(BaseModel):
    """Subscription confirmation response."""

    id: int
    email: str
    message: str
    unsubscribe_token: str


class ChatRequest(BaseModel):
    """Request payload for /api/chat endpoint."""

    question: str
    api_key: str | None = None
    model: str | None = None


class ChatResponse(BaseModel):
    """Response payload for /api/chat endpoint."""

    answer: str
    source: str = "gemini"
    model: str | None = None

