"""Pharmacy claim domain agents not yet in their own repositories.

Six knowledge fragments, one per domain agent (eligibility, coverage, clinical
DUR, network, COB, cost share), each extending the pharmacy base pack and
registered as its own `rulegraph.domains` entry point. Utilization management
already lives in its own repository (pharmacy-um-agent). Moving another domain
out is a matter of moving its `packs/<agent>` folder and entry point.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from rulegraph import DirectorySource, DomainPackage

__version__ = "0.2.0"
AGENTS = ["eligibility", "coverage", "clinical_dur", "network", "cob", "cost_share"]


def pack_dir(agent: str) -> Path:
    return Path(str(resources.files("pharmacy_agents") / "packs" / agent))


def _package(agent: str) -> DomainPackage:
    name = "pharmacy-" + {"clinical_dur": "clinical-dur", "cost_share": "cost-share"}.get(agent, agent)
    return DomainPackage(name=name, source=DirectorySource(pack_dir(agent)), agents=[agent], version=__version__)


packages = {a: _package(a) for a in AGENTS}
eligibility, coverage, clinical_dur, network, cob, cost_share = (packages[a] for a in AGENTS)


def build(settings=None, **kwargs):
    """These six domains on the pharmacy base (this package's own tests and direct questions)."""
    from pharmacy_base import build as base_build
    return base_build(settings, fragments=list(packages.values()), **kwargs)


__all__ = ["AGENTS", "build", "pack_dir", "packages"]
