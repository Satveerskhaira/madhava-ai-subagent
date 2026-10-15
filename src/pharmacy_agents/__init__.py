"""Pharmacy claim domain agents.

Seven domain agents (eligibility, coverage, utilization management, clinical
DUR, network, COB, cost share). Each is a planner over its rule-domain
investigators: it can answer a question about a claim from its own domain's
point of view, or work on a task delegated by a core planner and report
findings with evidence. Built on the rulegraph kernel; no agent SDK required.
"""

from .record import ClaimAdapter
from .system import DomainSystem, build, build_toolbox, fixtures_dir, pack_dir

__version__ = "0.1.0"
__all__ = ["ClaimAdapter", "DomainSystem", "build", "build_toolbox", "fixtures_dir", "pack_dir"]
