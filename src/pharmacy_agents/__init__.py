"""Pharmacy claim domain agents.

Seven knowledge fragments, one per domain agent (eligibility, coverage,
utilization management, clinical DUR, network, COB, cost share), each
extending the pharmacy base pack and registered as its own `rulegraph.domains`
entry point, with its own goldens and tests. A core planner discovers them and
calls them in process. Moving a domain to its own repository later is a matter
of moving its `packs/<agent>` folder, goldens and entry point.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from rulegraph import DirectorySource, DomainPackage

__version__ = "0.2.0"
AGENTS = ["eligibility", "coverage", "utilization_management", "clinical_dur", "network", "cob", "cost_share"]


def pack_dir(agent: str) -> Path:
    return Path(str(resources.files("pharmacy_agents") / "packs" / agent))


def _package(agent: str) -> DomainPackage:
    name = "pharmacy-" + {"utilization_management": "um", "clinical_dur": "clinical-dur",
                          "cost_share": "cost-share"}.get(agent, agent)
    return DomainPackage(name=name, source=DirectorySource(pack_dir(agent)), agents=[agent], version=__version__)


packages = {a: _package(a) for a in AGENTS}
eligibility, coverage, utilization_management, clinical_dur, network, cob, cost_share = (packages[a] for a in AGENTS)


def build(settings=None, *, agents: list[str] | None = None, **kwargs):
    """These domains on the pharmacy base: all of them, or only `agents` (one domain's own tests)."""
    from pharmacy_base import build as base_build
    chosen = [packages[a] for a in (agents or AGENTS)]
    return base_build(settings, fragments=chosen, **kwargs)


__all__ = ["AGENTS", "build", "pack_dir", "packages"]
