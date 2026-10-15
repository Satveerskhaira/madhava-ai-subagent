import asyncio
from datetime import date
from pathlib import Path

import pytest
import yaml

from rulegraph import discover
from rulegraph.agent.cards import agent_card
from rulegraph.evaluation import check
from rulegraph.models import ContextRef, DomainReport, DomainTask
from rulegraph.rules.validate import validate

GOLDENS = [g for g in yaml.safe_load((Path(__file__).resolve().parents[1] / "goldens" / "domain_goldens.yaml").read_text())["goldens"]
           if g["agent"] == "utilization_management"]


@pytest.fixture()
def system(tmp_path):
    """Utilization management alone on the pharmacy base, as if it were its own repo."""
    import pharmacy_agents
    from rulegraph import Settings
    return pharmacy_agents.build(Settings(today=date(2026, 10, 14), episodic_dir=tmp_path / "episodic"),
                                 agents=["utilization_management"])


def run(coro):
    return asyncio.run(coro)


def task(system, record, tokens=(), concepts=(), hints=(), mode="explain"):
    snap = system.toolbox.get_record_outcome(record)
    ctx = ContextRef(record_id=record, reference_id=snap["reference"]["id"],
                     service_date=date.fromisoformat(snap["service_date"]), rules_mode="as_decided",
                     rules_date=system.toolbox.rules_date(snap, "as_decided"))
    return DomainTask(task_id="t1", agent="utilization_management", context=ctx, mode=mode,
                      outcome_tokens=list(tokens), concepts=list(concepts), hints=list(hints), question="why?")


def test_fragment_composes_with_the_base_and_validates(system):
    kn = system.knowledge
    assert validate(kn) == []
    assert list(system.agents) == ["utilization_management"]
    assert sorted(kn.rules.domains) == ["prior_authorization", "quantity_limits", "step_therapy"]
    # links to other domains' concepts are kept aside until those packages are installed
    assert kn.taxonomy.unresolved_related["um.quantity_limits"] == ["network.specialty_channel"]


def test_registered_as_a_domain_package():
    assert "pharmacy-um" in {p.name for p in discover(extends="pharmacy-claims")}


@pytest.mark.parametrize("golden", GOLDENS, ids=[g["record"] for g in GOLDENS])
def test_um_goldens(system, golden):
    exp = run(system.agents[golden["agent"]].ask(golden["question"], golden["record"]))
    assert check(exp, golden["expect"]) == [], exp.answer


def test_delegated_task_returns_findings_and_a_domain_answer(system):
    report = run(system.agents["utilization_management"].handle(
        task(system, "RX-1001", ["reject:75"], ["um.prior_authorization"])))
    pa = next(f for f in report.findings if f.rule_id == "R-PA-001")
    assert (pa.status, pa.confidence, pa.agent, pa.unit) == ("fired", "confirmed", "utilization_management",
                                                             "prior_authorization")
    assert pa.overrides_checked[0]["rule"] == "R-PA-OVR-002@1" and pa.overrides_checked[0]["matched"] is False
    assert report.answer.startswith("Utilization management agent:") and report.gaps == []
    assert DomainReport.model_validate_json(report.model_dump_json()).findings[0].rule_id


def test_plans_its_own_gap_round_and_reports_the_gap(system):
    report = run(system.agents["utilization_management"].handle(
        task(system, "RX-1007", ["reject:76"], ["um.quantity_limits"])))
    assert [r.reason for r in report.rounds] == ["initial plan", "gap round"]
    assert report.rounds[0].agents == ["quantity_limits:explain:as_decided"]
    assert report.gaps == ["reject:76"]                 # honest: no UM rule explains it


def test_current_rules_mode_uses_newer_versions(system):
    exp = run(system.agents["utilization_management"].ask("Why was this rejected?", "RX-1001", rules_mode="current"))
    assert exp.primary.key == "R-PA-001@2"


def test_failed_investigator_becomes_an_error_report(system):
    agent = system.agents["utilization_management"]

    class Broken:
        name = "prior_authorization"

        async def handle(self, t):
            raise RuntimeError("rule store unavailable")

    agent.executors["prior_authorization"] = Broken()
    exp = run(agent.ask("Why was this rejected?", "RX-1001"))
    assert exp.primary is None and "reject:75" in exp.gaps


def test_agent_card_lists_concepts_as_skills(system):
    card = agent_card(system.agents["utilization_management"])
    assert card["name"] == "pharmacy-utilization_management"
    skill = next(s for s in card["skills"] if s["id"] == "um.prior_authorization")
    assert "reject:75" in skill["tags"] and "rule_domain:prior_authorization" in skill["tags"]


def test_runs_as_an_adk_workflow(system):
    pytest.importorskip("google.adk")
    from google.adk.runners import InMemoryRunner

    from rulegraph.adapters.adk import build_workflow

    async def go():
        runner = InMemoryRunner(node=build_workflow(system.agents["utilization_management"]), app_name="um")
        session = await runner.session_service.create_session(app_name="um", user_id="u")
        out, routes = None, []
        async for ev in runner.run_async(user_id="u", session_id=session.id,
                                         state_delta={"request": {"record_id": "RX-1007", "question": "Why did this reject?"}}):
            if ev.actions and ev.actions.route:
                routes.append(ev.actions.route)
            if isinstance(ev.output, dict) and "answer" in ev.output:
                out = ev.output
        return out, routes

    out, routes = run(go())
    assert routes == ["gap", "done"] and out["gaps"] == ["reject:76"]


def test_rule_sets_resolve_by_date(system):
    store = system.knowledge.rules
    assert store.rule_set("prior_authorization", date(2026, 9, 14)).id == "RS-PA-2026.01.1"
    assert store.resolve_rule("R-PA-001", date(2026, 10, 1))[1].version == 2
    assert store.diff("prior_authorization", date(2026, 9, 1), date(2026, 10, 14))["changed"] == ["R-PA-001@1->2"]


def test_graph_search_respects_the_agent_scope(system):
    from rulegraph.rules.graph import Seed
    kn = system.knowledge
    um = kn.taxonomy.branch("utilization_management")
    hits = kn.graph.search([Seed("outcome:reject:75", 1.0, "reject:75")], scope_concepts=um,
                           rule_concept=kn.rule_concepts())
    assert hits[0].rule_id == "R-PA-001" and all(kn.rules.latest(h.rule_id).concept in um for h in hits)
