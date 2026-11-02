"""
Comprehensive unit and integration tests for the Interactive CLI Q&A Interface and DatabaseQAAgent.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.cli import handle_local_commands, parse_cli_args, run_single_query
from src.database import DatabaseManager
from src.gemini_agent import DatabaseQAAgent, GeminiIntelligenceAgent
from src.main import parse_args
from src.models import CompanyIntelligence, JobOpening


@pytest.fixture
async def populated_db(tmp_path: Path):
    """Create and populate a temporary SQLite database with test companies and jobs."""
    db_file = tmp_path / "test_qa_companies.db"
    db = DatabaseManager(db_path=db_file)
    await db.init_db()

    seeds = [
        {
            "name": "Spintly",
            "website": "https://spintly.com",
            "careers": "https://spintly.com/careers",
            "rss": None,
        },
        {
            "name": "Teknorix",
            "website": "https://teknorix.com",
            "careers": "https://teknorix.com/careers",
            "rss": None,
        },
        {
            "name": "Pending Tech",
            "website": "https://pending.com",
            "careers": "https://pending.com/careers",
            "rss": None,
        },
    ]
    await db.seed_companies(seeds)

    # Spintly - COMPLETED
    intel_spintly = CompanyIntelligence(
        company_name="Spintly",
        goa_office_locations=["Verna", "Panaji"],
        core_domain="SaaS / IoT Access Control",
        primary_tech_stack=["React", "Python", "Node.js", "Docker"],
        hiring_status="Actively Hiring",
        active_openings=[
            JobOpening(
                title="Python Backend Engineer",
                department="Engineering",
                experience_level="1-3 years",
                tech_stack=["Python", "FastAPI", "PostgreSQL"],
                is_computer_eng_relevant=True,
                apply_url="https://spintly.keka.com/job/1",
            ),
            JobOpening(
                title="Firmware Developer",
                department="Embedded",
                experience_level="Mid-Level",
                tech_stack=["C++", "FreeRTOS", "BLE"],
                is_computer_eng_relevant=True,
                apply_url="https://spintly.keka.com/job/2",
            ),
        ],
        application_contact_email="careers@spintly.com",
        summary_explanation="Spintly develops cloud-based access control systems in Verna.",
        recent_news_summary="Expanded Verna R&D facility.",
    )
    await db.save_company_intelligence("Spintly", intel_spintly, seed=seeds[0])

    # Teknorix - COMPLETED
    intel_teknorix = CompanyIntelligence(
        company_name="Teknorix",
        goa_office_locations=["Verna"],
        core_domain="Custom Software / Cloud Solutions",
        primary_tech_stack=[".NET", "C#", "Angular", "Azure"],
        hiring_status="Actively Hiring",
        active_openings=[
            JobOpening(
                title="Full Stack .NET Developer",
                department="Software Development",
                experience_level="Fresher/Intern",
                tech_stack=[".NET Core", "C#", "Angular"],
                is_computer_eng_relevant=True,
                apply_url="https://teknorix.com/careers/apply",
            )
        ],
        application_contact_email="hr@teknorix.com",
        summary_explanation="Teknorix builds enterprise web and cloud applications in Verna.",
    )
    await db.save_company_intelligence("Teknorix", intel_teknorix, seed=seeds[1])

    return db


# ==============================================================================
# 1. DATABASE MANAGER QUERY TESTS
# ==============================================================================

@pytest.mark.asyncio
async def test_search_companies_by_query_and_filters(populated_db: DatabaseManager):
    """Test searching companies by keyword, location, tech stack, and status."""
    # Search by general query (IoT)
    results = await populated_db.search_companies(query="IoT")
    assert len(results) == 1
    assert results[0]["company_name"] == "Spintly"
    assert results[0]["opening_count"] == 2

    # Search by location (Verna) -> Both Spintly and Teknorix
    results_verna = await populated_db.search_companies(location="Verna")
    assert len(results_verna) == 2
    names = [r["company_name"] for r in results_verna]
    assert "Spintly" in names
    assert "Teknorix" in names

    # Search by tech stack (C#)
    results_csharp = await populated_db.search_companies(tech="C#")
    assert len(results_csharp) == 1
    assert results_csharp[0]["company_name"] == "Teknorix"

    # Search by status (PENDING)
    results_pending = await populated_db.search_companies(status="PENDING")
    assert len(results_pending) == 1
    assert results_pending[0]["company_name"] == "Pending Tech"

    # Search with limit
    results_limit = await populated_db.search_companies(limit=1)
    assert len(results_limit) == 1


@pytest.mark.asyncio
async def test_get_company_profile(populated_db: DatabaseManager):
    """Test retrieving full company profile and discrete openings."""
    # Exact match
    spintly = await populated_db.get_company_profile("Spintly")
    assert spintly is not None
    assert spintly["company_name"] == "Spintly"
    assert spintly["core_domain"] == "SaaS / IoT Access Control"
    assert "Verna" in spintly["goa_locations"]
    assert len(spintly["active_openings"]) == 2
    titles = [j["title"] for j in spintly["active_openings"]]
    assert "Python Backend Engineer" in titles
    assert "Firmware Developer" in titles

    # Case-insensitive substring match
    tek = await populated_db.get_company_profile("tekno")
    assert tek is not None
    assert tek["company_name"] == "Teknorix"
    assert len(tek["active_openings"]) == 1

    # Non-existent company
    non_existent = await populated_db.get_company_profile("NonExistentCo")
    assert non_existent is None

    # Empty string
    assert await populated_db.get_company_profile("") is None


@pytest.mark.asyncio
async def test_search_job_openings(populated_db: DatabaseManager):
    """Test searching job openings with company metadata."""
    # Search by title
    jobs_py = await populated_db.search_job_openings(title="Python")
    assert len(jobs_py) == 1
    assert jobs_py[0]["title"] == "Python Backend Engineer"
    assert jobs_py[0]["company_name"] == "Spintly"
    assert "Verna" in jobs_py[0]["goa_locations"]

    # Search by experience level (Fresher/Intern)
    jobs_fresher = await populated_db.search_job_openings(experience_level="Fresher")
    assert len(jobs_fresher) == 1
    assert jobs_fresher[0]["company_name"] == "Teknorix"
    assert jobs_fresher[0]["title"] == "Full Stack .NET Developer"

    # Search by tech
    jobs_ble = await populated_db.search_job_openings(tech="BLE")
    assert len(jobs_ble) == 1
    assert jobs_ble[0]["title"] == "Firmware Developer"

    # Search only CE relevant
    all_ce_jobs = await populated_db.search_job_openings(only_ce_relevant=True)
    assert len(all_ce_jobs) == 3


    # Search by general query across tech stack or company
    jobs_fastapi = await populated_db.search_job_openings(query="FastAPI")
    assert len(jobs_fastapi) == 1
    assert jobs_fastapi[0]["title"] == "Python Backend Engineer"

    jobs_by_co = await populated_db.search_job_openings(query="Teknorix")
    assert len(jobs_by_co) == 1
    assert jobs_by_co[0]["company_name"] == "Teknorix"


@pytest.mark.asyncio
async def test_execute_read_only_query(populated_db: DatabaseManager):
    """Test safe read-only SQL execution and injection protection."""
    # Valid SELECT
    rows = await populated_db.execute_read_only_query(
        "SELECT company_name, hiring_status FROM companies WHERE status = 'COMPLETED' ORDER BY company_name ASC"
    )
    assert len(rows) == 2
    assert rows[0]["company_name"] == "Spintly"
    assert rows[1]["company_name"] == "Teknorix"

    # Valid SELECT with aggregate
    stats_rows = await populated_db.execute_read_only_query(
        "SELECT COUNT(*) as cnt FROM job_openings"
    )
    assert rows[0] is not None
    assert stats_rows[0]["cnt"] == 3

    # Markdown code fences support
    md_rows = await populated_db.execute_read_only_query(
        "```sql\nSELECT company_name FROM companies WHERE status = 'COMPLETED';\n```"
    )
    assert len(md_rows) == 2

    # Leading SQL comments support
    comment_rows = await populated_db.execute_read_only_query(
        "-- Get count of active jobs\nSELECT COUNT(*) as total FROM job_openings"
    )
    assert comment_rows[0]["total"] == 3

    # Permitted keywords and semicolons inside string literals
    lit_rows = await populated_db.execute_read_only_query(
        "SELECT * FROM companies WHERE core_domain LIKE '%;%'"
    )
    assert isinstance(lit_rows, list)

    create_lit_rows = await populated_db.execute_read_only_query(
        "SELECT * FROM job_openings WHERE title LIKE '%creative%'"
    )
    assert isinstance(create_lit_rows, list)

    # Reject non-SELECT
    with pytest.raises(ValueError, match="Only read-only SELECT or WITH"):
        await populated_db.execute_read_only_query("DELETE FROM companies")

    with pytest.raises(ValueError, match="Only read-only SELECT or WITH"):
        await populated_db.execute_read_only_query("INSERT INTO companies (company_name) VALUES ('Hacked')")

    with pytest.raises(ValueError, match="Only read-only SELECT or WITH"):
        await populated_db.execute_read_only_query("DROP TABLE companies")

    # Reject multiple statements
    with pytest.raises(ValueError, match="Multiple SQL statements"):
        await populated_db.execute_read_only_query("SELECT 1; DROP TABLE companies")

    # Reject prohibited keywords inside sub-expressions
    with pytest.raises(ValueError, match="forbidden"):
        await populated_db.execute_read_only_query("SELECT * FROM companies WHERE company_name IN (DELETE FROM companies)")


@pytest.mark.asyncio
async def test_database_manager_str_path(tmp_path: Path):
    """Test DatabaseManager correctly handles string path argument without AttributeError."""
    db_file = str(tmp_path / "str_path_test.db")
    db = DatabaseManager(db_path=db_file)
    await db.init_db()
    assert Path(db_file).exists()


@pytest.mark.asyncio
async def test_get_context_summary(populated_db: DatabaseManager):
    """Test generation of context summary for model grounding."""
    summary = await populated_db.get_context_summary()
    assert summary["total_monitored_companies"] == 3
    assert summary["completed_companies_count"] == 2
    assert "Spintly" in summary["actively_hiring_companies"]
    assert "Teknorix" in summary["actively_hiring_companies"]
    assert "Verna" in summary["known_goa_locations"]
    assert any("Python" in t for t in summary["popular_tech_stacks"])


# ==============================================================================
# 2. DATABASE QA AGENT & TOOL EXECUTION TESTS
# ==============================================================================

@pytest.mark.asyncio
async def test_qa_agent_tools_execution(populated_db: DatabaseManager):
    """Test that all tool functions exposed by DatabaseQAAgent execute and return correct data."""
    agent = DatabaseQAAgent(db_manager=populated_db, api_key="mock_key")
    tools = agent.get_tools()
    assert len(tools) == 5

    tools_by_name = {t.__name__: t for t in tools}
    assert "get_database_statistics" in tools_by_name
    assert "search_companies" in tools_by_name
    assert "get_company_details" in tools_by_name
    assert "search_job_openings" in tools_by_name
    assert "run_sql_query" in tools_by_name

    # Test get_database_statistics tool
    stats = await tools_by_name["get_database_statistics"]()
    assert stats["total_companies"] == 3
    assert stats["completed"] == 2
    assert stats["total_openings"] == 3

    # Test search_companies tool
    comps = await tools_by_name["search_companies"](location="Verna")
    assert len(comps) == 2

    # Test get_company_details tool
    details = await tools_by_name["get_company_details"]("Spintly")
    assert details["company_name"] == "Spintly"
    assert len(details["active_openings"]) == 2

    # Test missing company details tool
    missing = await tools_by_name["get_company_details"]("GhostCorp")
    assert "error" in missing

    # Test search_job_openings tool
    jobs = await tools_by_name["search_job_openings"](title="Firmware")
    assert len(jobs) == 1
    assert jobs[0]["title"] == "Firmware Developer"

    # Test run_sql_query tool
    sql_res = await tools_by_name["run_sql_query"]("SELECT company_name FROM companies WHERE status='COMPLETED'")
    assert len(sql_res) == 2


@pytest.mark.asyncio
async def test_qa_agent_ask_without_api_key(populated_db: DatabaseManager):
    """Verify that ask() without an API key gracefully returns a friendly warning without crashing."""
    agent = DatabaseQAAgent(db_manager=populated_db, api_key="")
    # Clear env var if present for this test
    with patch.dict("os.environ", {}, clear=True):
        agent.api_key = None
        resp = await agent.ask("Which companies are hiring?")
        assert "GEMINI_API_KEY is not set" in resp


@pytest.mark.asyncio
async def test_qa_agent_ask_with_mocked_chat(populated_db: DatabaseManager):
    """Test full ask() turn with mocked AsyncChat and verify history recording."""
    agent = DatabaseQAAgent(db_manager=populated_db, api_key="mock_key")

    mock_chat = AsyncMock()
    mock_response = MagicMock()
    mock_response.text = "In Verna, Spintly is hiring Python and Firmware Engineers, and Teknorix is hiring .NET Developers."
    mock_chat.send_message.return_value = mock_response

    # Inject mock chat
    agent._chat = mock_chat
    agent._active_model = agent.model_name

    answer = await agent.ask("Which companies in Verna have engineering openings?")
    assert "Spintly" in answer
    assert "Teknorix" in answer
    mock_chat.send_message.assert_called_once_with("Which companies in Verna have engineering openings?")

    # Verify history
    assert len(agent.history) == 1
    assert agent.history[0]["user"] == "Which companies in Verna have engineering openings?"
    assert agent.history[0]["assistant"] == answer

    # Test reset_chat
    agent.reset_chat()
    assert len(agent.history) == 0
    assert agent._chat is None


@pytest.mark.asyncio
async def test_gemini_intelligence_agent_create_qa_agent(populated_db: DatabaseManager):
    """Test factory method on GeminiIntelligenceAgent."""
    intel_agent = GeminiIntelligenceAgent(api_key="test_key", model_name="gemini-3.8-flash")
    qa_agent = intel_agent.create_qa_agent(populated_db)
    assert isinstance(qa_agent, DatabaseQAAgent)
    assert qa_agent.api_key == "test_key"
    assert qa_agent.model_name == "gemini-3.8-flash"


# ==============================================================================
# 3. CLI OFFLINE COMMANDS & REPL LOGIC
# ==============================================================================

@pytest.mark.asyncio
async def test_cli_local_commands(populated_db: DatabaseManager, capsys: pytest.CaptureFixture):
    """Test built-in offline commands handled directly without Gemini."""
    agent = DatabaseQAAgent(db_manager=populated_db, api_key="mock_key")

    # 1. 'help'
    handled = await handle_local_commands("help", populated_db, agent)
    assert handled is True
    out = capsys.readouterr().out
    assert "COMMAND & QUERY GUIDE" in out

    # 2. 'stats'
    handled = await handle_local_commands("stats", populated_db, agent)
    assert handled is True
    out = capsys.readouterr().out
    assert "CURRENT DATABASE METRICS" in out
    assert "Total Companies Monitored : 3" in out

    # 3. 'companies'
    handled = await handle_local_commands("companies Verna", populated_db, agent)
    assert handled is True
    out = capsys.readouterr().out
    assert "Spintly" in out
    assert "Teknorix" in out

    # 4. 'jobs'
    handled = await handle_local_commands("jobs Python", populated_db, agent)
    assert handled is True
    out = capsys.readouterr().out
    assert "Python Backend Engineer" in out

    # 5. 'company <name>'
    handled = await handle_local_commands("company Spintly", populated_db, agent)
    assert handled is True
    out = capsys.readouterr().out
    assert "Spintly" in out
    assert "SaaS / IoT Access Control" in out
    assert "Firmware Developer" in out

    # 6. 'reset'
    agent._history.append({"user": "q", "assistant": "a"})
    handled = await handle_local_commands("reset", populated_db, agent)
    assert handled is True
    assert len(agent.history) == 0

    # 7. Unhandled normal query -> must return False so it gets passed to Gemini
    handled = await handle_local_commands("What is the average salary?", populated_db, agent)
    assert handled is False


@pytest.mark.asyncio
async def test_run_single_query(populated_db: DatabaseManager, capsys: pytest.CaptureFixture):
    """Test running a single question query via CLI."""
    with patch("src.cli.DatabaseQAAgent.ask", new_callable=AsyncMock) as mock_ask:
        mock_ask.return_value = "Spintly is in Verna and Panaji working on IoT."

        await run_single_query(
            query="Where is Spintly located?",
            db=populated_db,
            api_key="mock_key",
        )

        out = capsys.readouterr().out
        assert "Where is Spintly located?" in out
        assert "Spintly is in Verna and Panaji" in out
        mock_ask.assert_called_once_with("Where is Spintly located?")


@pytest.mark.asyncio
async def test_run_single_query_offline_command_routing(populated_db: DatabaseManager, capsys: pytest.CaptureFixture):
    """Test that single query mode executes offline commands locally without calling Gemini API."""
    with patch("src.cli.DatabaseQAAgent.ask", new_callable=AsyncMock) as mock_ask:
        # Run 'stats' as single query - should NOT call Gemini
        await run_single_query(
            query="stats",
            db=populated_db,
            api_key=None,
        )

        out = capsys.readouterr().out
        assert "[STATS] CURRENT DATABASE METRICS" in out
        assert "Total Companies Monitored : 3" in out
        mock_ask.assert_not_called()


@pytest.mark.asyncio
async def test_qa_agent_multi_turn_history_preservation(populated_db: DatabaseManager):
    """Test multi-turn chat preserves turn history and reuses active chat session."""
    agent = DatabaseQAAgent(db_manager=populated_db, api_key="mock_key", model_name="gemini-3.8-flash")
    assert agent.active_model == "gemini-3.8-flash"

    mock_chat = AsyncMock()
    mock_resp1 = MagicMock()
    mock_resp1.text = "Spintly is an IoT access control company in Verna."
    mock_resp2 = MagicMock()
    mock_resp2.text = "Their stack includes Python, React, and Node.js."
    mock_chat.send_message.side_effect = [mock_resp1, mock_resp2]

    # Pre-set active chat (as if turn 1 was established)
    agent._chat = mock_chat
    agent._active_model = "gemini-3-flash-preview"

    # Turn 1
    ans1 = await agent.ask("Who is Spintly?")
    assert "Spintly" in ans1
    assert agent.active_model == "gemini-3-flash-preview"
    assert len(agent.history) == 1

    # Turn 2 - must reuse active chat directly without re-init
    ans2 = await agent.ask("What is their tech stack?")
    assert "Python" in ans2
    assert len(agent.history) == 2
    assert agent.history[0]["user"] == "Who is Spintly?"
    assert agent.history[1]["user"] == "What is their tech stack?"
    assert mock_chat.send_message.call_count == 2


# ==============================================================================
# 4. CLI ARGUMENT PARSING TESTS
# ==============================================================================

def test_cli_argument_parsing():
    """Test CLI argument parser for src/cli.py."""
    with patch("sys.argv", ["cli.py", "--query", "Which companies use Python?", "--model", "gemini-3.8-flash"]):
        args = parse_cli_args()
        assert args.query == "Which companies use Python?"
        assert args.model == "gemini-3.8-flash"

    with patch("sys.argv", ["cli.py", "-q", "Who is hiring?", "--api-key", "custom_key"]):
        args = parse_cli_args()
        assert args.query == "Who is hiring?"
        assert args.api_key == "custom_key"


def test_main_argument_parsing_with_qa_flags():
    """Test argument parser for src/main.py with new interactive and ask flags."""
    with patch("sys.argv", ["main.py", "--interactive"]):
        args = parse_args()
        assert args.interactive is True

    with patch("sys.argv", ["main.py", "--chat"]):
        args = parse_args()
        assert args.chat is True

    with patch("sys.argv", ["main.py", "--ask", "Which companies are in Verna?"]):
        args = parse_args()
        assert args.query == "Which companies are in Verna?"

    with patch("sys.argv", ["main.py", "-q", "Any IoT companies?"]):
        args = parse_args()
        assert args.query == "Any IoT companies?"


# ==============================================================================
# 5. TOOL EXECUTION, TYPE RESOLUTION & GRANULAR FILTERING TESTS
# ==============================================================================

@pytest.mark.asyncio
async def test_tool_annotations_are_concrete_types_for_afc(populated_db: DatabaseManager):
    """Verify that all tools in DatabaseQAAgent have concrete types rather than string annotations."""
    import types as py_types

    from google.genai._extra_utils import convert_argument_from_function

    agent = DatabaseQAAgent(db_manager=populated_db, api_key="mock_key")
    tools = agent.get_tools()

    for tool in tools:
        import inspect
        sig = inspect.signature(tool)
        for param_name, param in sig.parameters.items():
            assert not isinstance(param.annotation, str), (
                f"Parameter '{param_name}' of tool '{tool.__name__}' has string annotation "
                f"'{param.annotation}' which causes google-genai AFC isinstance() TypeError!"
            )
            assert isinstance(param.annotation, (type, py_types.UnionType)), (
                f"Parameter '{param_name}' of tool '{tool.__name__}' is not a concrete type or union: {param.annotation}"
            )

    # Test AFC argument conversion on search_job_openings with standard typed values
    search_tool = next(t for t in tools if t.__name__ == "search_job_openings")
    test_args = {
        "experience_level": "Fresher",
        "only_ce_relevant": True,
        "active_only": True,
        "time_range": "this month",
        "limit": 10,
    }
    converted = convert_argument_from_function(test_args, search_tool)
    assert converted["experience_level"] == "Fresher"
    assert converted["only_ce_relevant"] is True
    assert converted["time_range"] == "this month"

    # Test AFC argument conversion with string values commonly generated by LLMs
    string_args = {
        "days": "30",
        "limit": "15",
        "only_ce_relevant": "true",
        "active_only": "false",
        "include_historical": "true",
    }
    converted_str = convert_argument_from_function(string_args, search_tool)
    assert converted_str["days"] == "30"
    assert converted_str["limit"] == "15"
    assert converted_str["only_ce_relevant"] == "true"

    # Test AFC argument conversion on run_sql_query
    sql_tool = next(t for t in tools if t.__name__ == "run_sql_query")
    converted_sql = convert_argument_from_function({"sql_query": "SELECT 1;"}, sql_tool)
    assert converted_sql["sql_query"] == "SELECT 1;"


@pytest.mark.asyncio
async def test_search_job_openings_fresher_and_synonym_filtering(populated_db: DatabaseManager):
    """Verify search_job_openings returns fresher and intern positions for all common synonym variations."""
    # 1. Direct experience_level="Fresher"
    res1 = await populated_db.search_job_openings(experience_level="Fresher", only_ce_relevant=True)
    assert len(res1) >= 1
    assert any(j["company_name"] == "Teknorix" for j in res1)
    assert any("Fresher" in j.get("experience_level", "") for j in res1)

    # 2. Synonym: "entry-level"
    res2 = await populated_db.search_job_openings(experience_level="entry-level", only_ce_relevant=True)
    assert len(res2) >= 1
    assert any(j["company_name"] == "Teknorix" for j in res2)

    # 3. Synonym: "intern"
    res3 = await populated_db.search_job_openings(experience_level="intern", only_ce_relevant=True)
    assert len(res3) >= 1
    assert any(j["company_name"] == "Teknorix" for j in res3)

    # 4. Synonym: "trainee"
    res4 = await populated_db.search_job_openings(experience_level="trainee", only_ce_relevant=True)
    assert len(res4) >= 1
    assert any(j["company_name"] == "Teknorix" for j in res4)

    # 5. Full text search query="freshers"
    res5 = await populated_db.search_job_openings(query="freshers", only_ce_relevant=True)
    assert len(res5) >= 1
    assert any(j["company_name"] == "Teknorix" for j in res5)

    # 6. Full text search query="fresher"
    res6 = await populated_db.search_job_openings(query="fresher", only_ce_relevant=True)
    assert len(res6) >= 1
    assert any(j["company_name"] == "Teknorix" for j in res6)


@pytest.mark.asyncio
async def test_search_job_openings_time_range_and_ce_filtering(populated_db: DatabaseManager):
    """Test time range and computer engineering relevance filters in search_job_openings."""
    # CE relevant only: should return Spintly (Python, Firmware) and Teknorix (.NET), but not non-CE
    ce_jobs = await populated_db.search_job_openings(only_ce_relevant=True)
    assert all(j["is_computer_eng_relevant"] for j in ce_jobs)

    # Time range: "this month"
    month_jobs = await populated_db.search_job_openings(time_range="this month")
    assert len(month_jobs) >= 1

    # Time range: days=30
    days_jobs = await populated_db.search_job_openings(days=30)
    assert len(days_jobs) >= 1

    # Time range: since ISO string
    since_jobs = await populated_db.search_job_openings(since="2020-01-01T00:00:00+00:00")
    assert len(since_jobs) >= 1


@pytest.mark.asyncio
async def test_run_sql_query_aliases_and_safety(populated_db: DatabaseManager):
    """Test run_sql_query parameter aliases, scalar REPLACE() support, and mutation safety."""
    agent = DatabaseQAAgent(db_manager=populated_db, api_key="mock_key")
    tools = {t.__name__: t for t in agent.get_tools()}
    sql_tool = tools["run_sql_query"]

    # 1. Parameter name 'sql_query'
    res1 = await sql_tool(sql_query="SELECT company_name FROM companies;")
    assert len(res1) >= 2

    # 2. Parameter name 'query'
    res2 = await sql_tool(query="SELECT company_name FROM companies;")
    assert len(res2) >= 2

    # 3. Parameter name 'sql'
    res3 = await sql_tool(sql="SELECT company_name FROM companies;")
    assert len(res3) >= 2

    # 4. Parameter name 'statement'
    res4 = await sql_tool(statement="SELECT company_name FROM companies;")
    assert len(res4) >= 2

    # 5. Semicolon followed by trailing comment must succeed
    res_semi_comment = await sql_tool(sql_query="SELECT company_name FROM companies WHERE status='COMPLETED'; -- comment")
    assert len(res_semi_comment) >= 2

    # 6. Parenthesized query must succeed
    res_paren = await sql_tool(sql_query="(SELECT company_name FROM companies LIMIT 1)")
    assert len(res_paren) == 1

    # 7. Trailing single-line comment without semicolon must succeed with auto LIMIT
    res_trail = await sql_tool(sql_query="SELECT company_name FROM companies -- trailing comment")
    assert len(res_trail) >= 2

    # 8. Scalar REPLACE() string function in SELECT must be allowed
    res_replace = await sql_tool(sql_query="SELECT REPLACE(company_name, 'Spintly', 'SpintlyTech') AS renamed FROM companies WHERE company_name='Spintly';")
    assert len(res_replace) == 1
    assert res_replace[0]["renamed"] == "SpintlyTech"

    # 9. Modifying statement REPLACE INTO must be blocked
    res_blocked = await sql_tool(sql_query="REPLACE INTO companies (company_name) VALUES ('Hacked');")
    assert "error" in res_blocked[0]

    # 10. Empty query error handling
    res_empty = await sql_tool()
    assert "error" in res_empty[0]


@pytest.mark.asyncio
async def test_search_job_openings_no_false_positives_on_internal_international(populated_db: DatabaseManager):
    """Verify that jobs containing 'international' or 'internal' are NOT misclassified as fresher/intern roles."""
    # Seed a company with international sales and internal audit
    intel_audit = CompanyIntelligence(
        company_name="Audit Global",
        goa_office_locations=["Panaji"],
        core_domain="Consulting",
        primary_tech_stack=["Python"],
        hiring_status="Actively Hiring",
        active_openings=[
            JobOpening(
                title="Technical Sales Manager, International Sales",
                department="Sales",
                experience_level="5+ years",
                tech_stack=["Sales"],
                is_computer_eng_relevant=True,
                apply_url="https://audit.com/apply/1",
            ),
            JobOpening(
                title="Lead Internal Audit Specialist",
                department="Finance",
                experience_level="Senior",
                tech_stack=["Excel"],
                is_computer_eng_relevant=False,
                apply_url="https://audit.com/apply/2",
            ),
            JobOpening(
                title="Software Engineering Intern",
                department="Engineering",
                experience_level="Fresher/Intern",
                tech_stack=["Python"],
                is_computer_eng_relevant=True,
                apply_url="https://audit.com/apply/3",
            ),
        ],
    )
    await populated_db.seed_companies([{
        "name": "Audit Global",
        "website": "https://audit.com",
        "careers": "https://audit.com/careers",
        "rss": None,
    }])
    await populated_db.save_company_intelligence(
        "Audit Global",
        intel_audit,
        seed={"name": "Audit Global", "website": "https://audit.com", "careers": "https://audit.com/careers"},
    )

    # Search for fresher openings
    fresher_results = await populated_db.search_job_openings(experience_level="fresher")
    titles = [j["title"] for j in fresher_results if j["company_name"] == "Audit Global"]
    assert "Software Engineering Intern" in titles
    assert "Technical Sales Manager, International Sales" not in titles
    assert "Lead Internal Audit Specialist" not in titles


@pytest.mark.asyncio
async def test_tool_robustness_with_aliases_and_string_coercion(populated_db: DatabaseManager):
    """Verify tool wrappers handle parameter aliases, string-encoded numbers/booleans, and varied date phrases."""
    agent = DatabaseQAAgent(db_manager=populated_db, api_key="mock_key")
    tools = {t.__name__: t for t in agent.get_tools()}

    # 1. search_job_openings with string numbers and booleans
    search_job_tool = tools["search_job_openings"]
    res_jobs = await search_job_tool(
        days="30",
        limit="10",
        only_ce_relevant="true",
        active_only="true",
        experience="Fresher",
        role="Developer",
    )
    assert isinstance(res_jobs, list)
    assert len(res_jobs) >= 1
    assert any("Teknorix" in j["company_name"] for j in res_jobs)

    # 2. search_job_openings with time_range='past 30 days'
    res_range = await search_job_tool(time_range="past 30 days", experience_level="fresher")
    assert isinstance(res_range, list)
    assert len(res_range) >= 1

    # 3. search_companies with aliases: company_name and string limit
    search_co_tool = tools["search_companies"]
    res_co = await search_co_tool(company_name="Spintly", limit="5")
    assert len(res_co) == 1
    assert res_co[0]["company_name"] == "Spintly"

    # 4. get_company_details with alias 'company'
    details_tool = tools["get_company_details"]
    res_details = await details_tool(company="Spintly")
    assert "error" not in res_details
    assert res_details["company_name"] == "Spintly"


@pytest.mark.asyncio
async def test_cli_jobs_command_with_fresher_filter(populated_db: DatabaseManager, capsys: pytest.CaptureFixture):
    """Verify CLI offline command 'jobs fresher' returns matching fresher openings."""
    agent = DatabaseQAAgent(db_manager=populated_db, api_key="mock_key")
    handled = await handle_local_commands("jobs fresher", populated_db, agent)
    assert handled is True
    out = capsys.readouterr().out
    assert "Full Stack .NET Developer" in out
    assert "Teknorix" in out

