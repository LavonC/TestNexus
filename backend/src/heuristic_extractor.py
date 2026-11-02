"""
Local heuristic pre-extraction module (offline-first).
Extracts contact emails, Goa office locations, tech stack keywords,
and constructs fallback offline intelligence for unreachable or dead sites.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from src.models import CompanyIntelligence, JobOpening, ScrapedData

logger = logging.getLogger(__name__)

# Canonical Goa locations mapping (variations -> canonical name)
GOA_LOCATION_CANONICAL = {
    "verna": "Verna",
    "verna industrial estate": "Verna",
    "panaji": "Panaji",
    "panjim": "Panaji",
    "margao": "Margao",
    "madgaon": "Margao",
    "porvorim": "Porvorim",
    "alto porvorim": "Porvorim",
    "mapusa": "Mapusa",
    "mapuca": "Mapusa",
    "vasco": "Vasco",
    "vasco da gama": "Vasco",
    "miramar": "Miramar",
    "dona paula": "Dona Paula",
    "ponda": "Ponda",
    "curti": "Ponda",
    "farmagudi": "Ponda",
    "bicholim": "Bicholim",
    "kundaim": "Kundaim",
    "corlim": "Corlim",
    "tuem": "Tuem",
    "tuem electronic city": "Tuem",
    "taleigao": "Taleigao",
    "bambolim": "Bambolim",
    "thivim": "Thivim",
    "nuvem": "Nuvem",
    "salcete": "Salcete",
    "bardez": "Bardez",
    "tiswadi": "Tiswadi",
    "canacona": "Canacona",
    "sanquelim": "Sanquelim",
    "curchorem": "Curchorem",
    "quepem": "Quepem",
    "colva": "Colva",
    "calangute": "Calangute",
    "candolim": "Candolim",
    "arpora": "Arpora",
    "anjuna": "Anjuna",
    "assagao": "Assagao",
    "siolim": "Siolim",
    "morjim": "Morjim",
    "pernem": "Pernem",
    "sancoale": "Sancoale",
    "cortalim": "Cortalim",
    "loutolim": "Loutolim",
    "cansaulim": "Cansaulim",
    "chicalim": "Chicalim",
    "dabolim": "Dabolim",
    "fatorda": "Fatorda",
    "navelim": "Navelim",
    "benaulim": "Benaulim",
    "cavelossim": "Cavelossim",
    "cumbarjua": "Cumbarjua",
    "valpoi": "Valpoi",
}

# Regex pattern for matching Goa locations
# Multi-word first, then single-word
_SORTED_LOCS = sorted(GOA_LOCATION_CANONICAL.keys(), key=lambda s: len(s), reverse=True)
_LOCS_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in _SORTED_LOCS) + r")\b",
    re.IGNORECASE,
)

# Common tech keywords to extract from pages
KNOWN_TECH_KEYWORDS = [
    # Languages
    "Python", "JavaScript", "TypeScript", "Java", "C++", "C#", "Golang", "Go",
    "Rust", "PHP", "Ruby", "Swift", "Kotlin", "HTML", "CSS", "SQL", "Bash", "Shell",
    "Dart", "Scala", "R", "MATLAB", "Solidity", "Assembly",
    # Frameworks & Libraries
    "React", "React Native", "Next.js", "Angular", "Vue", "Svelte", "Node.js", "Express",
    "NestJS", "Django", "FastAPI", "Flask", "Spring Boot", "Spring", ".NET", "ASP.NET",
    "Laravel", "Flutter", "Tailwind", "Bootstrap", "GraphQL", "REST API", "gRPC",
    # Cloud, DevOps & Infrastructure
    "AWS", "Azure", "GCP", "Google Cloud", "Docker", "Kubernetes", "Linux", "Unix",
    "Git", "GitHub", "GitLab", "Jenkins", "Terraform", "Ansible", "CI/CD", "Kafka",
    "RabbitMQ", "Celery", "Nginx", "Apache",
    # Databases
    "PostgreSQL", "MySQL", "MongoDB", "Redis", "SQLite", "Elasticsearch", "Oracle",
    "Cassandra", "DynamoDB", "Firebase", "Supabase", "MSSQL", "MariaDB", "Snowflake", "BigQuery",
    # Specialized / Hardware / Embedded
    "Embedded", "IoT", "Firmware", "Microcontrollers", "RTOS", "ARM", "STM32", "ESP32",
    "Arduino", "Raspberry Pi", "PCB", "FPGA", "PLC", "SCADA", "CAN bus", "Modbus",
    "Industrial Automation", "Robotics", "Hardware",
    # AI / Data Science
    "Machine Learning", "Deep Learning", "Computer Vision", "NLP", "Artificial Intelligence",
    "LLM", "Generative AI", "PyTorch", "TensorFlow", "Keras", "OpenCV", "Pandas", "NumPy", "Scikit-Learn",
    # QA & Testing
    "Selenium", "Cypress", "Playwright", "Automation Testing", "Manual Testing", "Postman", "Pytest", "Jest",
]

# Case-sensitive / boundary patterns for 120+ keywords
TECH_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Tricky languages
    (re.compile(r"\bC\+\+(?!\w)"), "C++"),
    (re.compile(r"\bC#(?!\w)"), "C#"),
    (re.compile(r"\b(?:Golang|Go lang)\b|\bGo\b(?=[\s,/]*(?:developer|engineer|backend|programming|code|,))|\b(?:and|in|with|using)\s+Go\b", re.IGNORECASE), "Go"),
    (re.compile(r"\b\.NET\b", re.IGNORECASE), ".NET"),
    (re.compile(r"\bASP\.NET\b", re.IGNORECASE), "ASP.NET"),
    (re.compile(r"\bNode\.?js\b", re.IGNORECASE), "Node.js"),
    (re.compile(r"\bNext\.?js\b", re.IGNORECASE), "Next.js"),
    (re.compile(r"\bNest\.?js\b", re.IGNORECASE), "NestJS"),
    (re.compile(r"\bVue(?:\.js)?\b", re.IGNORECASE), "Vue"),
    (re.compile(r"\bSvelte\b", re.IGNORECASE), "Svelte"),
    (re.compile(r"\bReact\s+Native\b", re.IGNORECASE), "React Native"),
    (re.compile(r"\bReact(?:\.js)?\b", re.IGNORECASE), "React"),
    (re.compile(r"\bAngular\b", re.IGNORECASE), "Angular"),
    (re.compile(r"\bTypeScript\b", re.IGNORECASE), "TypeScript"),
    (re.compile(r"\bJavaScript\b", re.IGNORECASE), "JavaScript"),
    (re.compile(r"\bPython\b", re.IGNORECASE), "Python"),
    (re.compile(r"\bJava\b(?!\s*script)", re.IGNORECASE), "Java"),
    (re.compile(r"\bSpring\s*Boot\b", re.IGNORECASE), "Spring Boot"),
    (re.compile(r"\bSpring\s+Framework\b|\bSpring\s+Cloud\b", re.IGNORECASE), "Spring"),
    (re.compile(r"\bDjango\b", re.IGNORECASE), "Django"),
    (re.compile(r"\bFastAPI\b", re.IGNORECASE), "FastAPI"),
    (re.compile(r"\bFlask\b", re.IGNORECASE), "Flask"),
    (re.compile(r"\bPHP\b", re.IGNORECASE), "PHP"),
    (re.compile(r"\bLaravel\b", re.IGNORECASE), "Laravel"),
    (re.compile(r"\bFlutter\b", re.IGNORECASE), "Flutter"),
    (re.compile(r"\bDart\b", re.IGNORECASE), "Dart"),
    (re.compile(r"\bSwift\b", re.IGNORECASE), "Swift"),
    (re.compile(r"\bKotlin\b", re.IGNORECASE), "Kotlin"),
    (re.compile(r"\bRust\b", re.IGNORECASE), "Rust"),
    (re.compile(r"\bRuby(?:\s+on\s+Rails)?\b", re.IGNORECASE), "Ruby"),
    (re.compile(r"\bScala\b", re.IGNORECASE), "Scala"),
    (re.compile(r"\bSolidity\b", re.IGNORECASE), "Solidity"),
    (re.compile(r"\bHTML5?\b", re.IGNORECASE), "HTML"),
    (re.compile(r"\bCSS3?\b", re.IGNORECASE), "CSS"),
    (re.compile(r"\bTailwind(?:\s+CSS)?\b", re.IGNORECASE), "Tailwind"),
    (re.compile(r"\bBootstrap\b", re.IGNORECASE), "Bootstrap"),
    (re.compile(r"\bGraphQL\b", re.IGNORECASE), "GraphQL"),
    (re.compile(r"\bREST(?:ful)?\s+API\b", re.IGNORECASE), "REST API"),
    (re.compile(r"\bgRPC\b", re.IGNORECASE), "gRPC"),
    # Cloud & DevOps
    (re.compile(r"\bDocker\b", re.IGNORECASE), "Docker"),
    (re.compile(r"\bKubernetes\b|\bk8s\b", re.IGNORECASE), "Kubernetes"),
    (re.compile(r"\bAWS\b|\bAmazon\s+Web\s+Services\b", re.IGNORECASE), "AWS"),
    (re.compile(r"\bAzure\b", re.IGNORECASE), "Azure"),
    (re.compile(r"\b(GCP|Google\s+Cloud(?:\s+Platform)?)\b", re.IGNORECASE), "GCP"),
    (re.compile(r"\bLinux\b", re.IGNORECASE), "Linux"),
    (re.compile(r"\bUnix\b", re.IGNORECASE), "Unix"),
    (re.compile(r"\bBash\b|\bShell\s+scripting\b", re.IGNORECASE), "Bash"),
    (re.compile(r"\bGit\b(?!\s*lab|\s*hub)", re.IGNORECASE), "Git"),
    (re.compile(r"\bGitHub\b", re.IGNORECASE), "GitHub"),
    (re.compile(r"\bGitLab\b", re.IGNORECASE), "GitLab"),
    (re.compile(r"\bJenkins\b", re.IGNORECASE), "Jenkins"),
    (re.compile(r"\bTerraform\b", re.IGNORECASE), "Terraform"),
    (re.compile(r"\bAnsible\b", re.IGNORECASE), "Ansible"),
    (re.compile(r"\bCI\s*\/\s*CD\b|\bContinuous\s+Integration\b", re.IGNORECASE), "CI/CD"),
    (re.compile(r"\bKafka\b", re.IGNORECASE), "Kafka"),
    (re.compile(r"\bRabbitMQ\b", re.IGNORECASE), "RabbitMQ"),
    (re.compile(r"\bCelery\b", re.IGNORECASE), "Celery"),
    (re.compile(r"\bNginx\b", re.IGNORECASE), "Nginx"),
    # Databases
    (re.compile(r"\bPostgreSQL\b|\bPostgres\b", re.IGNORECASE), "PostgreSQL"),
    (re.compile(r"\bMySQL\b", re.IGNORECASE), "MySQL"),
    (re.compile(r"\bMongoDB\b", re.IGNORECASE), "MongoDB"),
    (re.compile(r"\bRedis\b", re.IGNORECASE), "Redis"),
    (re.compile(r"\bSQLite\b", re.IGNORECASE), "SQLite"),
    (re.compile(r"\bElasticsearch\b", re.IGNORECASE), "Elasticsearch"),
    (re.compile(r"\bOracle(?:\s+Database|\s+DB)?\b", re.IGNORECASE), "Oracle"),
    (re.compile(r"\bCassandra\b", re.IGNORECASE), "Cassandra"),
    (re.compile(r"\bDynamoDB\b", re.IGNORECASE), "DynamoDB"),
    (re.compile(r"\bFirebase\b", re.IGNORECASE), "Firebase"),
    (re.compile(r"\bSupabase\b", re.IGNORECASE), "Supabase"),
    (re.compile(r"\bSnowflake\b", re.IGNORECASE), "Snowflake"),
    (re.compile(r"\bBigQuery\b", re.IGNORECASE), "BigQuery"),
    # Hardware, Embedded & IoT
    (re.compile(r"\bEmbedded\s*(?:C|Systems?|Software|Firmware)?\b", re.IGNORECASE), "Embedded"),
    (re.compile(r"\bIoT\b|\bInternet\s+of\s+Things\b", re.IGNORECASE), "IoT"),
    (re.compile(r"\bFirmware\b", re.IGNORECASE), "Firmware"),
    (re.compile(r"\bMicrocontrollers?\b|\bMCU\b", re.IGNORECASE), "Microcontrollers"),
    (re.compile(r"\bRTOS\b|\bFreeRTOS\b", re.IGNORECASE), "RTOS"),
    (re.compile(r"\bARM\s*(?:Cortex)?\b", re.IGNORECASE), "ARM"),
    (re.compile(r"\bSTM32\b", re.IGNORECASE), "STM32"),
    (re.compile(r"\bESP32\b|\bESP8266\b", re.IGNORECASE), "ESP32"),
    (re.compile(r"\bArduino\b", re.IGNORECASE), "Arduino"),
    (re.compile(r"\bRaspberry\s+Pi\b", re.IGNORECASE), "Raspberry Pi"),
    (re.compile(r"\bPCB\s+(?:Design|Layout)\b", re.IGNORECASE), "PCB Design"),
    (re.compile(r"\bFPGA\b", re.IGNORECASE), "FPGA"),
    (re.compile(r"\bPLC\b|\bSCADA\b", re.IGNORECASE), "PLC / SCADA"),
    (re.compile(r"\bCAN(?:\s*bus)?\b", re.IGNORECASE), "CAN bus"),
    (re.compile(r"\bModbus\b", re.IGNORECASE), "Modbus"),
    (re.compile(r"\bIndustrial\s+Automation\b", re.IGNORECASE), "Industrial Automation"),
    (re.compile(r"\bRobotics\b", re.IGNORECASE), "Robotics"),
    # AI & ML
    (re.compile(r"\bMachine\s+Learning\b|\bML\b", re.IGNORECASE), "Machine Learning"),
    (re.compile(r"\bDeep\s+Learning\b", re.IGNORECASE), "Deep Learning"),
    (re.compile(r"\bArtificial\s+Intelligence\b|\bAI\b", re.IGNORECASE), "Artificial Intelligence"),
    (re.compile(r"\bComputer\s+Vision\b", re.IGNORECASE), "Computer Vision"),
    (re.compile(r"\bNLP\b|\bNatural\s+Language\s+Processing\b", re.IGNORECASE), "NLP"),
    (re.compile(r"\bLLMs?\b|\bLarge\s+Language\s+Models?\b", re.IGNORECASE), "LLM"),
    (re.compile(r"\bGenerative\s+AI\b|\bGenAI\b", re.IGNORECASE), "Generative AI"),
    (re.compile(r"\bPyTorch\b", re.IGNORECASE), "PyTorch"),
    (re.compile(r"\bTensorFlow\b", re.IGNORECASE), "TensorFlow"),
    (re.compile(r"\bOpenCV\b", re.IGNORECASE), "OpenCV"),
    (re.compile(r"\bPandas\b", re.IGNORECASE), "Pandas"),
    (re.compile(r"\bNumPy\b", re.IGNORECASE), "NumPy"),
    (re.compile(r"\bScikit-Learn\b|\bSklearn\b", re.IGNORECASE), "Scikit-Learn"),
    # QA & Testing
    (re.compile(r"\bSelenium\b", re.IGNORECASE), "Selenium"),
    (re.compile(r"\bPlaywright\b", re.IGNORECASE), "Playwright"),
    (re.compile(r"\bCypress\b", re.IGNORECASE), "Cypress"),
    (re.compile(r"\bAutomation\s+Testing\b|\bQA\s+Automation\b", re.IGNORECASE), "Automation Testing"),
    (re.compile(r"\bManual\s+Testing\b", re.IGNORECASE), "Manual Testing"),
    (re.compile(r"\bPostman\b", re.IGNORECASE), "Postman"),
    (re.compile(r"\bPytest\b", re.IGNORECASE), "Pytest"),
    (re.compile(r"\bJest\b", re.IGNORECASE), "Jest"),
]

# Email regex
EMAIL_REGEX = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b"
)

# File extensions to ignore in email matches
INVALID_EMAIL_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp", ".css", ".js", ".woff", ".ico"
}

# Example / bogus email domains
IGNORE_EMAIL_DOMAINS = {
    "example.com", "domain.com", "yoursite.com", "email.com", "company.com",
    "test.com", "sentry.io", "wixpress.com"
}


def extract_emails(text: str) -> list[str]:
    """Extract valid contact/career email addresses from text."""
    if not text:
        return []

    found = EMAIL_REGEX.findall(text)
    valid_emails: list[str] = []
    seen: set[str] = set()

    # Prioritize career/hr/job emails
    def email_priority(email: str) -> int:
        lower = email.lower()
        if any(prefix in lower for prefix in ("career", "jobs", "hr@", "recruitment", "hiring", "apply")):
            return 0
        if any(prefix in lower for prefix in ("info@", "contact@", "hello@", "support@")):
            return 1
        return 2

    for raw in found:
        email = raw.strip().rstrip(".")
        lower = email.lower()
        if lower in seen:
            continue
        # Check invalid extension
        if any(lower.endswith(ext) for ext in INVALID_EMAIL_EXTENSIONS):
            continue
        # Check ignored domain
        parts = lower.split("@")
        if len(parts) != 2 or parts[1] in IGNORE_EMAIL_DOMAINS:
            continue

        seen.add(lower)
        valid_emails.append(email)

    valid_emails.sort(key=email_priority)
    return valid_emails


def extract_goa_locations(text: str) -> list[str]:
    """Extract and canonicalize Goa office locations mentioned in text."""
    if not text:
        return []

    matched_canonical: list[str] = []
    seen: set[str] = set()

    for match in _LOCS_PATTERN.finditer(text):
        raw_loc = match.group(0).lower()
        canonical = GOA_LOCATION_CANONICAL.get(raw_loc)
        if canonical and canonical not in seen:
            seen.add(canonical)
            matched_canonical.append(canonical)

    return matched_canonical


def extract_tech_stack(text: str) -> list[str]:
    """Extract matched tech keywords from text."""
    if not text:
        return []

    detected: list[str] = []
    seen: set[str] = set()

    for pattern, tech_name in TECH_PATTERNS:
        if pattern.search(text):
            if tech_name not in seen:
                seen.add(tech_name)
                detected.append(tech_name)

    return detected


PARKED_DOMAIN_PHRASES = (
    "buy this domain",
    "domain is for sale",
    "is available for purchase",
    "hugedomains.com",
    "dan.com",
    "sedo.com",
    "parked free",
    "godaddy.com/domainsearch",
    "this domain has expired",
    "renew your domain",
    "domain parking",
    "this domain name is for sale",
    "website is coming soon",
)

EXTERNAL_ATS_PROVIDERS = (
    "keka.com",
    "zohorecruit.com",
    "myworkdayjobs.com",
    "workday.com",
    "lever.co",
    "greenhouse.io",
    "smartrecruiters.com",
    "freshteam.com",
    "bamboohr.com",
    "recruitee.com",
)


def _extract_url_from_markdown(link_str: str) -> str:
    """Extract clean URL from markdown link '[text](url)' or return clean url directly."""
    if not link_str:
        return ""
    m = re.search(r"\]\((https?://[^\s\)]+)\)", link_str)
    if m:
        return m.group(1).strip()
    clean = link_str.strip()
    if clean.startswith(("http://", "https://")):
        return clean
    return ""


def is_site_unreachable(scraped_data: ScrapedData) -> bool:
    """
    Check if a company's site is completely unreachable, dead, DNS failed, or parked.
    Such sites have minimal or error text in both homepage and careers page,
    with no verified external ATS portals.
    """
    home = (scraped_data.homepage_text or "").strip()
    careers = (scraped_data.careers_page_text or "").strip()

    # 1. Parked domain check: if homepage or careers displays domain-for-sale/parked text
    home_lower = home.lower()
    careers_lower = careers.lower()
    is_home_parked = any(phrase in home_lower for phrase in PARKED_DOMAIN_PHRASES)
    is_careers_parked = any(phrase in careers_lower for phrase in PARKED_DOMAIN_PHRASES)
    if is_home_parked or (is_careers_parked and (not home or "failed to fetch" in home_lower or "getaddrinfo" in home_lower)):
        return True

    # 2. If genuine external ATS links were detected (e.g. Keka, Lever, Zoho), site is reachable via ATS
    has_external_ats = any(
        any(provider in (link or "").lower() for provider in EXTERNAL_ATS_PROVIDERS)
        for link in scraped_data.ats_links
    )
    if has_external_ats:
        return False

    # 3. If homepage has substantial real content and is not an error, site is reachable
    dead_error_phrases = (
        "failed to fetch",
        "name or service not known",
        "getaddrinfo failed",
        "nodename nor servname provided",
        "connection refused",
        "http 404",
        "http 500",
        "http 502",
        "http 503",
        "timeout fetching",
        "no url provided",
    )

    has_home_error = any(err in home_lower for err in dead_error_phrases)
    if len(home) > 200 and not has_home_error:
        return False

    has_careers_error = any(err in careers_lower for err in dead_error_phrases)

    # If both homepage and careers explicitly failed or returned fetch errors
    if (has_home_error or not home) and (has_careers_error or scraped_data.careers_fetch_failed or not careers):
        if has_home_error or has_careers_error:
            return True

    return False


JOB_ROLE_KEYWORDS = (
    "engineer", "developer", "programmer", "analyst", "architect",
    "specialist", "lead", "designer", "qa", "tester", "intern", "trainee",
    "devops", "administrator", "consultant", "scientist", "technician",
    "officer", "professor", "lecturer", "manager", "associate", "examiner",
)

EXCLUDED_HEADINGS = (
    "about us", "our team", "why join us", "careers at", "life at",
    "core values", "employee benefits", "contact us", "get in touch",
    "open positions", "current openings", "job openings", "view all",
    "who we are", "what we do", "perks", "culture", "how we work",
    "frequently asked", "privacy policy", "terms of service",
    "post name", "department name", "sr. no.", "serial no", "last date", "action", "details",
)


_CE_PATTERN = re.compile(
    r"\b(?:computer|software|developer|engineer|data|web|frontend|backend|"
    r"full\s*stack|cloud|devops|qa|tester|testing|embedded|firmware|it|"
    r"information\s+technology|python|java|c\+\+|react|node|ai|"
    r"machine\s+learning|scada|plc|networking|cybersecurity|technical\s+examiner)\b",
    re.IGNORECASE,
)


def extract_heuristic_job_openings(text: str, default_url: str = "") -> list[JobOpening]:
    """
    Deterministically extract job openings from HTML markdown headings, lists, and job notices.
    Operates 100% offline with zero LLM API calls.
    """
    if not text:
        return []

    openings: list[JobOpening] = []
    seen_titles: set[str] = set()

    lines = text.split("\n")
    for i, line in enumerate(lines):
        raw = line.strip()
        if not raw:
            continue

        cand_title = None
        # Check headings: ### Python Engineer or ## QA Analyst
        m_head = re.match(r"^#{1,4}\s+(.+)$", raw)
        if m_head:
            cand = m_head.group(1).strip(" *-_:.")
            cand_lower = cand.lower()
            if not any(ex in cand_lower for ex in EXCLUDED_HEADINGS) and any(kw in cand_lower for kw in JOB_ROLE_KEYWORDS):
                if 5 <= len(cand) <= 80:
                    cand_title = cand

        # Check list bullets: * Senior Java Developer
        if not cand_title:
            m_bullet = re.match(r"^[\*\-•]\s+(.+)$", raw)
            if m_bullet:
                cand = m_bullet.group(1).strip(" *-_:.")
                cand_lower = cand.lower()
                if not any(ex in cand_lower for ex in EXCLUDED_HEADINGS) and any(kw in cand_lower for kw in JOB_ROLE_KEYWORDS):
                    if 5 <= len(cand) <= 75 and not cand.endswith("."):
                        cand_title = cand

        # Check markdown table rows: | 1 | DEPARTMENT | Assistant Engineer | ... | [View](url) |
        is_table_row = False
        cand_dept = None
        if not cand_title and raw.startswith("|") and raw.endswith("|"):
            parts = [p.strip() for p in raw.strip("|").split("|")]
            if not all(set(p) <= {"-", " ", ":"} for p in parts if p):
                for col_idx, col in enumerate(parts):
                    col_clean = re.sub(r"\[.*?\]\(.*?\)", "", col).strip(" *-_:.")
                    col_lower = col_clean.lower()
                    if not any(ex in col_lower for ex in EXCLUDED_HEADINGS) and any(kw in col_lower for kw in JOB_ROLE_KEYWORDS):
                        if 5 <= len(col_clean) <= 90:
                            cand_title = col_clean
                            is_table_row = True
                            if col_idx > 0 and len(parts[col_idx - 1]) > 3:
                                cand_dept = parts[col_idx - 1].strip(" *-_:.")
                            break

        if cand_title:
            norm = normalize_company_name(cand_title)
            if norm in seen_titles:
                continue
            seen_titles.add(norm)

            # In table rows, restrict context to current row to prevent leakage across jobs
            if is_table_row:
                context_block = raw
            else:
                context_block = " ".join(lines[i : min(len(lines), i + 6)])
            job_tech = extract_tech_stack(context_block)
            if not job_tech:
                job_tech = extract_tech_stack(cand_title)

            # Experience detection
            exp_level = "Unknown"
            if re.search(r"\b(?:fresher|intern|trainee|entry\s*level)\b", context_block, re.IGNORECASE):
                exp_level = "Fresher/Intern"
            elif re.search(r"([0-9]{1,2})\s*[-+]\s*([0-9]{1,2})?\s*years?", context_block, re.IGNORECASE):
                m_exp = re.search(r"([0-9]{1,2}(?:\s*[-+]\s*[0-9]{1,2})?\s*years?)", context_block, re.IGNORECASE)
                if m_exp:
                    exp_level = m_exp.group(1)
            elif re.search(r"\bsenior|lead\b", cand_title, re.IGNORECASE):
                exp_level = "Senior"

            # Apply link detection (search context_block and current raw line)
            apply_link = default_url or None
            m_link = re.search(r"\[(?:apply|link|view|details|more)\]\(([^\s\)]+)\)", raw, re.IGNORECASE) or re.search(r"\[(?:apply|link|view|details|more)\]\(([^\s\)]+)\)", context_block, re.IGNORECASE)
            if m_link:
                from urllib.parse import urljoin
                apply_link = urljoin(default_url, m_link.group(1).strip())

            is_ce = bool(_CE_PATTERN.search(f"{cand_title} {context_block}"))

            clean_title = re.sub(r"\s+", " ", cand_title).title()
            dept_title = cand_dept or ("Engineering" if is_ce else "General")

            openings.append(
                JobOpening(
                    title=clean_title,
                    department=dept_title,
                    experience_level=exp_level,
                    tech_stack=job_tech[:5],
                    is_computer_eng_relevant=is_ce,
                    apply_url=apply_link,
                    source_type="WEB",
                    source_url=default_url or None,
                )
            )

    return openings


def build_offline_profile(
    company_name: str,
    scraped_data: ScrapedData,
    seed: dict[str, Any] | None = None,
) -> CompanyIntelligence:
    """
    Construct a complete offline intelligence profile without calling an LLM (0 API calls).
    Extracts structured openings from PDFs, ATS portals, and careers page markdown.
    """
    seed_dict = seed or {}
    website_url = seed_dict.get("website", "")
    careers_url = seed_dict.get("careers", "")

    home_text = scraped_data.homepage_text or ""
    careers_text = scraped_data.careers_page_text or ""
    combined_text = (
        f"{home_text}\n"
        f"{careers_text}\n"
        f"{scraped_data.rss_summary}\n"
        f"{website_url}\n"
        f"{careers_url}"
    )

    # Check for parked domain status
    lower_comb = combined_text.lower()
    is_parked = any(phrase in lower_comb for phrase in PARKED_DOMAIN_PHRASES)

    locations = extract_goa_locations(combined_text) or ["Goa"]
    emails = extract_emails(combined_text)
    tech = extract_tech_stack(combined_text)

    # Identify genuine external ATS candidate URLs
    ats_candidates: list[str] = []

    # Check links collected by scraper: only accept verified external ATS portals
    for raw_link in scraped_data.ats_links:
        clean_url = _extract_url_from_markdown(raw_link)
        if clean_url and any(prov in clean_url.lower() for prov in EXTERNAL_ATS_PROVIDERS):
            if clean_url not in ats_candidates:
                ats_candidates.append(clean_url)

    # Check seed careers URL: only accept if it actually resolved and is an external ATS
    if careers_url and not scraped_data.careers_fetch_failed and any(
        prov in careers_url.lower() for prov in EXTERNAL_ATS_PROVIDERS
    ):
        if careers_url not in ats_candidates:
            ats_candidates.append(careers_url)

    # Collect discrete active job openings from PDFs and heuristic text
    active_openings: list[JobOpening] = []

    # 1. Incorporate any PDF circular openings already parsed
    if getattr(scraped_data, "pdf_openings", None):
        active_openings.extend(scraped_data.pdf_openings)

    # 2. Extract heuristic openings from careers markdown text
    if not is_parked and careers_text:
        heuristic_openings = extract_heuristic_job_openings(
            careers_text, default_url=careers_url or website_url
        )
        for h_job in heuristic_openings:
            if not any(
                normalize_company_name(h_job.title) == normalize_company_name(existing.title)
                for existing in active_openings
            ):
                active_openings.append(h_job)

    # 3. If ATS candidate links were found and still no discrete openings detected
    if not is_parked and not active_openings and ats_candidates:
        for link in ats_candidates[:3]:
            active_openings.append(
                JobOpening(
                    title="Software / Tech Role (ATS Posting)",
                    department="Engineering",
                    experience_level="Unknown",
                    tech_stack=tech[:3],
                    is_computer_eng_relevant=True,
                    apply_url=link,
                    source_type="ATS",
                    source_url=link,
                )
            )

    # Determine hiring status
    if not is_parked and active_openings:
        hiring_status = "Actively Hiring"
    elif not is_parked and emails:
        hiring_status = "Open Applications Only"
    elif any(k in lower_comb for k in ("no current opening", "no active vacancy", "not hiring", "no vacancy")):
        hiring_status = "No Listed Openings"
    else:
        hiring_status = "Unknown"

    contact_email = emails[0] if emails and not is_parked else None

    # Determine basic domain heuristic
    if any(k in lower_comb for k in ("iot", "embedded", "firmware", "hardware")):
        core_domain = "IoT / Embedded Systems"
    elif any(k in lower_comb for k in ("saas", "cloud", "platform", "software")):
        core_domain = "Software & SaaS Solutions"
    elif any(k in lower_comb for k in ("automation", "industrial", "robotics", "plc")):
        core_domain = "Industrial Automation"
    else:
        core_domain = "Information Technology & Engineering Services"

    if is_parked:
        summary_explanation = (
            f"{company_name}'s domain appears to be parked, expired, or for sale. "
            f"No active engineering operations or job postings detected."
        )
    else:
        summary_explanation = (
            f"{company_name} is a Goa-based technology entity operating in {core_domain} "
            f"with offices associated with {', '.join(locations)}. "
            f"Public website access was limited or offline during automated collection."
        )

    return CompanyIntelligence(
        company_name=company_name,
        goa_office_locations=locations,
        core_domain=core_domain,
        primary_tech_stack=tech or ["Software Engineering"],
        hiring_status=hiring_status,
        active_openings=active_openings,
        recent_news_summary=None,
        application_contact_email=contact_email,
        summary_explanation=summary_explanation,
    )


def clean_json_text(text: str) -> str:
    """
    Strip markdown code fences and extraneous text from LLM output.
    Extracts valid JSON payload inside ```json ... ``` or outermost { ... } / [ ... ].
    """
    if not text:
        return "{}"
    s = text.strip()
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", s, re.IGNORECASE)
    if fence_match:
        return fence_match.group(1).strip()

    start_brace = s.find("{")
    start_bracket = s.find("[")

    if start_brace != -1 and (start_bracket == -1 or start_brace < start_bracket):
        end_brace = s.rfind("}")
        if end_brace != -1 and end_brace > start_brace:
            return s[start_brace : end_brace + 1].strip()
    elif start_bracket != -1:
        end_bracket = s.rfind("]")
        if end_bracket != -1 and end_bracket > start_bracket:
            return s[start_bracket : end_bracket + 1].strip()

    return s


def normalize_company_name(name: str) -> str:
    """
    Normalize company name by stripping legal/corporate noise and special characters
    to allow robust matching in batch extraction.
    """
    s = re.sub(r"[^\w\s]", " ", name.lower())
    noise_words = {
        "pvt",
        "ltd",
        "private",
        "limited",
        "inc",
        "llc",
        "corp",
        "corporation",
        "technologies",
        "technology",
        "solutions",
        "services",
        "systems",
        "india",
        "goa",
        "software",
    }
    tokens = [w for w in s.split() if w not in noise_words]
    return " ".join(tokens) if tokens else s.strip()

