"""
Local LLM fallback client (Ollama / OpenAI-compatible).
Provides 100% offline, free, and unlimited structured extraction.
"""

from __future__ import annotations

import json
import logging
import re

import httpx

from src.heuristic_extractor import build_offline_profile
from src.models import CompanyIntelligence, ScrapedData

logger = logging.getLogger(__name__)


class LocalLLMClient:
    """Async client connecting to a local Ollama or OpenAI-compatible LLM server."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "llama3.2",
        timeout: float = 60.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    async def is_available(self) -> bool:
        """Check if local Ollama or local LLM server is responding."""
        try:
            async with httpx.AsyncClient(timeout=1.5) as client:
                # Test Ollama native /api/version or /api/tags
                resp = await client.get(f"{self.base_url}/api/version")
                if resp.status_code == 200:
                    return True
                # Fallback to OpenAI-compatible /v1/models
                resp2 = await client.get(f"{self.base_url}/v1/models")
                return resp2.status_code == 200
        except Exception:
            return False

    def _clean_json_text(self, text: str) -> str:
        """Strip markdown code fences and extraneous text from LLM JSON output."""
        text = text.strip()
        # Extract text inside ```json ... ``` or ``` ... ```
        fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
        if fence_match:
            text = fence_match.group(1).strip()
        return text

    async def _call_ollama_or_openai(self, prompt: str, system: str = "") -> str:
        """Call Ollama native /api/chat or OpenAI /v1/chat/completions."""
        headers = {"Content-Type": "application/json"}
        payload_native = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system or "You extract accurate JSON."},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.1},
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            # 1. Try Ollama native endpoint /api/chat
            try:
                resp = await client.post(
                    f"{self.base_url}/api/chat",
                    json=payload_native,
                    headers=headers,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return data.get("message", {}).get("content", "")
            except Exception as exc:
                logger.debug("Ollama /api/chat failed, trying /v1/chat/completions: %s", exc)

            # 2. Try OpenAI-compatible endpoint /v1/chat/completions
            payload_openai = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system or "You extract accurate JSON."},
                    {"role": "user", "content": prompt},
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0.1,
            }
            resp = await client.post(
                f"{self.base_url}/v1/chat/completions",
                json=payload_openai,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]

    async def extract_structured_intelligence(
        self,
        company_name: str,
        scraped_data: ScrapedData,
        search_notes: str = "",
    ) -> CompanyIntelligence:
        """Extract structured intelligence for a single company using local LLM."""
        system_instruction = (
            "You are an expert tech career analyst. Output valid JSON adhering strictly to this schema: "
            "{\"company_name\": str, \"goa_office_locations\": list[str], \"core_domain\": str, "
            "\"primary_tech_stack\": list[str], \"hiring_status\": \"Actively Hiring\" | \"Open Applications Only\" | \"No Listed Openings\" | \"Unknown\", "
            "\"active_openings\": list[{\"title\": str, \"department\": str, \"experience_level\": str, \"tech_stack\": list[str], \"is_computer_eng_relevant\": bool, \"apply_url\": str|null}], "
            "\"application_contact_email\": str|null, \"summary_explanation\": str}"
        )

        prompt = f"""
Analyze the following data for tech company: {company_name} in Goa, India.

--- HOMEPAGE CONTENT ---
{scraped_data.homepage_text[:4000] if scraped_data.homepage_text else "None"}

--- CAREERS PAGE CONTENT ---
{scraped_data.careers_page_text[:4000] if scraped_data.careers_page_text else "None"}

--- ATS LINKS ---
{chr(10).join(scraped_data.ats_links) if scraped_data.ats_links else "None"}

Return strict JSON only.
"""
        try:
            raw_output = await self._call_ollama_or_openai(prompt, system_instruction)
            cleaned = self._clean_json_text(raw_output)
            return CompanyIntelligence.model_validate_json(cleaned)
        except Exception as exc:
            logger.warning("Local LLM structured extraction failed for %s: %s. Using heuristic fallback.", company_name, exc)
            return build_offline_profile(company_name, scraped_data)

    async def extract_batch_structured_intelligence(
        self,
        batch_items: list[tuple[str, ScrapedData, str]],
    ) -> list[CompanyIntelligence]:
        """Extract structured intelligence for a batch of companies using local LLM."""
        if not batch_items:
            return []

        company_blocks: list[str] = []
        for idx, (cname, sdata, _) in enumerate(batch_items, 1):
            home_snip = (sdata.homepage_text or "")[:1500]
            careers_snip = (sdata.careers_page_text or "")[:1500]
            ats_snip = "\n".join(sdata.ats_links[:5]) if sdata.ats_links else "None"
            block = (
                f"### COMPANY {idx}: {cname}\n"
                f"Homepage: {home_snip}\n"
                f"Careers: {careers_snip}\n"
                f"ATS Links: {ats_snip}\n"
            )
            company_blocks.append(block)

        system_instruction = (
            "You are an expert tech career analyst. Output valid JSON with key 'companies' containing a list of objects, "
            "where each object has: company_name, goa_office_locations (list of strings like Verna, Panaji, Margao), "
            "core_domain, primary_tech_stack, hiring_status, active_openings (list of {title, department, experience_level, tech_stack, is_computer_eng_relevant, apply_url}), "
            "application_contact_email, summary_explanation."
        )

        prompt = (
            f"Analyze the following {len(batch_items)} tech companies based in Goa, India. "
            f"Extract structured intelligence for each:\n\n"
            + "\n".join(company_blocks)
            + "\nReturn JSON: {\"companies\": [...]}"
        )

        try:
            raw_output = await self._call_ollama_or_openai(prompt, system_instruction)
            cleaned = self._clean_json_text(raw_output)
            parsed = json.loads(cleaned)
            companies_json = parsed.get("companies", parsed if isinstance(parsed, list) else [])
            results = [CompanyIntelligence.model_validate(c) for c in companies_json]

            # Map by company name
            results_by_name = {c.company_name.lower(): c for c in results}
            final_list: list[CompanyIntelligence] = []
            for cname, sdata, _ in batch_items:
                found = results_by_name.get(cname.lower())
                if found:
                    final_list.append(found)
                else:
                    final_list.append(build_offline_profile(cname, sdata))
            return final_list

        except Exception as exc:
            logger.warning("Local LLM batch extraction failed: %s. Using heuristic fallback.", exc)
            return [build_offline_profile(cname, sdata) for cname, sdata, _ in batch_items]
