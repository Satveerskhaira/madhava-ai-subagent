"""Build the pharmacy domain agents.

    from pharmacy_agents import build
    system = build()                                  # sample fixtures
    agent = system.agents["utilization_management"]
    await agent.ask("Why was this rejected?", "RX-1001")       # domain answer
    await agent.handle(task)                                   # task from a core planner

Real APIs: set PHARMACY_CLAIMS_URL and PHARMACY_BENEFITS_URL (and
PHARMACY_API_TOKEN); adjust the path templates below to your services.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from rulegraph import Knowledge, Settings, Toolbox, domain_agents
from rulegraph.agent.language import Language
from rulegraph.agent.planner import Planner
from rulegraph.memory.episodic import EpisodicMemory
from rulegraph.tools.apis import FixtureRecordApi, FixtureReferenceApi, HttpRecordApi, HttpReferenceApi

from .record import ClaimAdapter


def pack_dir() -> Path:
    return Path(str(resources.files("pharmacy_agents") / "pack"))


def fixtures_dir() -> Path:
    return Path(str(resources.files("pharmacy_agents") / "fixtures"))


@dataclass
class DomainSystem:
    settings: Settings
    knowledge: Knowledge
    toolbox: Toolbox
    agents: dict[str, Planner]


def build_toolbox(knowledge: Knowledge, settings: Settings) -> Toolbox:
    claims_url, benefits_url = os.environ.get("PHARMACY_CLAIMS_URL"), os.environ.get("PHARMACY_BENEFITS_URL")
    token = os.environ.get("PHARMACY_API_TOKEN")
    records = (HttpRecordApi(claims_url, "/claims/{id}", token) if claims_url
               else FixtureRecordApi(fixtures_dir() / "claims.yaml", key="claims"))
    references = (HttpReferenceApi(benefits_url, "/plans/{id}/setup?asOf={date}", "/plans/{id}/versions", token)
                  if benefits_url else FixtureReferenceApi(fixtures_dir() / "benefit_setup"))
    return Toolbox(knowledge, records, references, ClaimAdapter(), settings)


def build(settings: Settings | None = None, *, knowledge: Knowledge | None = None, toolbox: Toolbox | None = None,
          language: Language | None = None, episodic: EpisodicMemory | None = None,
          names: list[str] | None = None) -> DomainSystem:
    """Knowledge, toolbox and domain agents. Pass `knowledge`/`toolbox` to share them with a core planner."""
    settings = settings or Settings()
    knowledge = knowledge or Knowledge.load(pack_dir())
    toolbox = toolbox or build_toolbox(knowledge, settings)
    agents = domain_agents(knowledge, toolbox, names=names, language=language,
                           episodic=episodic or EpisodicMemory(settings.episodic_dir), settings=settings)
    return DomainSystem(settings, knowledge, toolbox, agents)
