"""Seed default agents into the database.

Run with: python -m scripts.seed_agents
"""

import asyncio
import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.constants import (
    CLAUDE_HAIKU,
    CLAUDE_OPUS,
    CLAUDE_SONNET,
    GEMINI_FLASH,
    GEMINI_PRO,
)
from app.models import Agent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Path to prompts directory
PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def load_prompt(name: str) -> str:
    """Load prompt from file."""
    prompt_path = PROMPTS_DIR / f"{name}.md"
    if prompt_path.exists():
        return prompt_path.read_text()
    return f"You are a {name} agent."


# Default agent configurations
DEFAULT_AGENTS = [
    # === From AgentType enum ===
    {
        "slug": "coder",
        "name": "Code Generator",
        "description": "Implements features, fixes bugs, and writes clean code",
        "system_prompt": load_prompt("coder"),
        "primary_model_id": CLAUDE_SONNET,
        "fallback_models": [GEMINI_FLASH],
        "escalation_model_id": CLAUDE_OPUS,
        "temperature": 0.3,
    },
    {
        "slug": "planner",
        "name": "Task Planner",
        "description": "Analyzes tasks and creates implementation plans",
        "system_prompt": load_prompt("planner"),
        "primary_model_id": CLAUDE_SONNET,
        "fallback_models": [GEMINI_PRO],
        "escalation_model_id": CLAUDE_OPUS,
        "temperature": 0.5,
    },
    {
        "slug": "reviewer",
        "name": "Code Reviewer",
        "description": "Reviews code for quality, security, and best practices",
        "system_prompt": load_prompt("reviewer"),
        "primary_model_id": CLAUDE_OPUS,
        "fallback_models": [GEMINI_PRO],
        "temperature": 0.2,
    },
    {
        "slug": "fixer",
        "name": "Error Fixer",
        "description": "Diagnoses and fixes errors in code",
        "system_prompt": load_prompt("fixer"),
        "primary_model_id": CLAUDE_SONNET,
        "fallback_models": [GEMINI_FLASH],
        "escalation_model_id": CLAUDE_OPUS,
        "temperature": 0.3,
    },
    # === Self-healing agents ===
    {
        "slug": "worker",
        "name": "Self-Healing Worker",
        "description": "First-line error fixing (cheap, fast operations)",
        "system_prompt": """You are a fast worker agent for quick fixes.

Your job is to fix simple errors quickly and efficiently:
- Syntax errors
- Import errors
- Type errors
- Simple logic bugs

Keep responses short and focused. Fix the immediate problem only.
Do not refactor or add features.""",
        "primary_model_id": GEMINI_FLASH,
        "fallback_models": [CLAUDE_HAIKU],
        "escalation_model_id": CLAUDE_SONNET,
        "temperature": 0.1,
    },
    {
        "slug": "supervisor",
        "name": "Supervisor Agent",
        "description": "Complex fix analysis and coordination",
        "system_prompt": """You are a supervisor agent for complex error analysis.

Your job is to:
1. Analyze errors that the worker couldn't fix
2. Understand the root cause
3. Design a proper fix
4. Coordinate with other agents if needed

Think step by step. Consider side effects.""",
        "primary_model_id": CLAUDE_SONNET,
        "fallback_models": [GEMINI_PRO],
        "escalation_model_id": CLAUDE_OPUS,
        "temperature": 0.4,
    },
    {
        "slug": "auditor",
        "name": "Audit Agent",
        "description": "Cross-checks fixes for correctness",
        "system_prompt": """You are an audit agent for verifying fixes.

Your job is to:
1. Review proposed fixes from other agents
2. Verify the fix addresses the root cause
3. Check for potential side effects
4. Approve or reject the fix

Be thorough but efficient. Trust but verify.""",
        "primary_model_id": GEMINI_PRO,
        "fallback_models": [CLAUDE_SONNET],
        "temperature": 0.2,
    },
    # === Utility agents ===
    {
        "slug": "summarizer",
        "name": "Content Summarizer",
        "description": "Summarizes content concisely",
        "system_prompt": """You are a summarization agent.

Summarize content clearly and concisely:
- Extract key points
- Maintain accuracy
- Be brief but complete

Output in bullet points or short paragraphs.""",
        "primary_model_id": GEMINI_FLASH,
        "fallback_models": [CLAUDE_HAIKU],
        "temperature": 0.3,
    },
    {
        "slug": "analyst",
        "name": "Code Analyst",
        "description": "Analyzes code structure and patterns",
        "system_prompt": """You are a code analysis agent.

Analyze code to understand:
- Architecture and structure
- Dependencies and relationships
- Patterns and anti-patterns
- Potential improvements

Be thorough in analysis but focused in recommendations.""",
        "primary_model_id": CLAUDE_SONNET,
        "fallback_models": [GEMINI_PRO],
        "temperature": 0.4,
    },
    {
        "slug": "extractor",
        "name": "Data Extractor",
        "description": "Extracts structured data from unstructured content",
        "system_prompt": """You are a data extraction agent.

Extract structured data from content:
- Parse text into structured formats
- Identify key entities and relationships
- Output valid JSON

Be precise and consistent in output format.""",
        "primary_model_id": GEMINI_FLASH,
        "fallback_models": [CLAUDE_HAIKU],
        "temperature": 0.1,
    },
    # === Consultation agents (for /consult skill) ===
    {
        "slug": "validator",
        "name": "Quick Validator",
        "description": "Fast syntax, format, and correctness validation",
        "system_prompt": load_prompt("validator"),
        "primary_model_id": GEMINI_FLASH,
        "fallback_models": [CLAUDE_HAIKU],
        "temperature": 0.1,
    },
    {
        "slug": "explorer",
        "name": "Codebase Explorer",
        "description": "Fast codebase exploration and search synthesis",
        "system_prompt": load_prompt("explorer"),
        "primary_model_id": GEMINI_FLASH,
        "fallback_models": [CLAUDE_SONNET],
        "temperature": 0.2,
    },
    {
        "slug": "designer",
        "name": "UI/UX Designer",
        "description": "Visual design analysis and UI/UX recommendations",
        "system_prompt": load_prompt("designer"),
        "primary_model_id": GEMINI_PRO,
        "fallback_models": [CLAUDE_SONNET],
        "temperature": 0.4,
    },
    {
        "slug": "reasoner",
        "name": "Reasoning Consultant",
        "description": "Complex reasoning, trade-off analysis, and strategic decisions",
        "system_prompt": """You are a reasoning consultant for complex decisions.

Your job is to:
1. Analyze trade-offs between options
2. Consider multiple perspectives
3. Provide clear recommendations with rationale
4. Identify risks and mitigation strategies

Think systematically. Be thorough but concise.""",
        "primary_model_id": GEMINI_PRO,
        "fallback_models": [CLAUDE_SONNET],
        "temperature": 0.5,
    },
    # === QA agents ===
    {
        "slug": "qa",
        "name": "QA Supervisor",
        "description": "Reviews task execution quality and determines pass/fail",
        "system_prompt": load_prompt("qa"),
        "primary_model_id": CLAUDE_OPUS,
        "fallback_models": [CLAUDE_SONNET],
        "escalation_model_id": CLAUDE_OPUS,
        "temperature": 0.2,
    },
]


async def seed_agents(db: AsyncSession) -> int:
    """Seed default agents into database.

    Returns:
        Number of agents created (skips existing)
    """
    created = 0

    for agent_data in DEFAULT_AGENTS:
        # Check if agent already exists
        result = await db.execute(select(Agent).where(Agent.slug == agent_data["slug"]))
        existing = result.scalar_one_or_none()

        if existing:
            logger.info(f"Agent '{agent_data['slug']}' already exists, skipping")
            continue

        # Create new agent
        agent = Agent(
            slug=agent_data["slug"],
            name=agent_data["name"],
            description=agent_data.get("description"),
            system_prompt=agent_data["system_prompt"],
            primary_model_id=agent_data["primary_model_id"],
            fallback_models=agent_data.get("fallback_models", []),
            escalation_model_id=agent_data.get("escalation_model_id"),
            strategies=agent_data.get("strategies", {}),
            temperature=agent_data.get("temperature", 0.7),
            is_active=True,
            version=1,
        )
        db.add(agent)
        created += 1
        logger.info(f"Created agent: {agent_data['slug']}")

    await db.commit()
    return created


async def main():
    """Run the seed script."""
    # Create async engine
    db_url = settings.agent_hub_db_url.replace("postgresql://", "postgresql+asyncpg://")
    engine = create_async_engine(db_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as db:
        count = await seed_agents(db)
        logger.info(f"Seeded {count} agents")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
