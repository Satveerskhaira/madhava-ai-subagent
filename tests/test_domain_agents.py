import asyncio
from datetime import date
from pathlib import Path

import pytest
import yaml

from rulegraph.agent.cards import agent_card
from rulegraph.agent.language import ModelLanguage
from rulegraph.evaluation import check
from rulegraph.models import ContextRef, DomainReport, DomainTask

GOLDENS = yaml.safe_load((Path(__file__).resolve().parents[1] / "goldens" / "domain_goldens.yaml").read_text())["goldens"]


def run(coro):
    return asyncio.run(coro)


def task(system, agent, record, tokens=(), concepts=(), hints=(), mode="explain", rules_mode="as_decided"):
    snap = system.toolbox.get_record_outcome(record)
    ctx = ContextRef(record_id=record, reference_id=snap["reference"]["id"],
                     service_date=date.fromisoformat(snap["service_date"]), rules_mode=rules_mode,
                     rules_date=system.toolbox.rules_date(snap, rules_mode))
    return DomainTask(task_id="t1", agent=agent, context=ctx, mode=mode, outcome_tokens=list(tokens),
                      concepts=list(concepts), hints=list(hints), question="why?")


@pytest.mark.parametrize("golden", GOLDENS, ids=[f"{g['agent']}-{g['record']}" for g in GOLDENS])
def test_domain_goldens(system, golden):
    exp = run(system.agents[golden["agent"]].ask(golden["question"], golden["record"]))
    assert check(exp, golden["expect"]) == [], exp.answer


def test_delegated_task_returns_findings_and_a_domain_answer(system):
    report = run(system.agents["utilization_management"].handle(
        task(system, "utilization_management", "RX-1001", ["reject:75"], ["um.prior_authorization"])))
    pa = next(f for f in report.findings if f.rule_id == "R-PA-001")
    assert (pa.status, pa.confidence, pa.agent, pa.unit) == ("fired", "confirmed", "utilization_management",
                                                             "prior_authorization")
    assert pa.overrides_checked[0]["rule"] == "R-PA-OVR-002@1" and pa.overrides_checked[0]["matched"] is False
    assert report.answer.startswith("Utilization management agent:") and report.gaps == []
    assert DomainReport.model_validate_json(report.model_dump_json()).findings[0].rule_id


def test_domain_agent_plans_its_own_gap_round(system):
    report = run(system.agents["utilization_management"].handle(
        task(system, "utilization_management", "RX-1007", ["reject:76"], ["um.quantity_limits"])))
    assert [r.reason for r in report.rounds] == ["initial plan", "gap round"]
    assert report.rounds[0].agents == ["quantity_limits:explain:as_decided"]
    assert report.gaps == ["reject:76"]                 # honest: no UM rule explains it


def test_out_of_scope_token_routes_through_hints_and_graph(system):
    # The core's gap round sends reject:76 to network with a hint; network routes it inside its scope.
    report = run(system.agents["network"].handle(
        task(system, "network", "RX-1007", ["reject:76"], ["network.specialty_channel"], ["R-NET-001"])))
    net = next(f for f in report.findings if f.rule_id == "R-NET-001")
    assert net.confidence == "confirmed" and report.gaps == []


def test_delegated_what_if_sweeps_the_domain(system):
    report = run(system.agents["cost_share"].handle(task(system, "cost_share", "RX-1001", mode="what_if")))
    fired = [(f.rule_id, f.amount, f.confidence) for f in report.findings if f.status == "fired"]
    assert fired == [("R-CS-002", 150.0, "what_if")]


def test_override_is_evaluated_across_rule_domains(system):
    report = run(system.agents["cost_share"].handle(
        task(system, "cost_share", "RX-1006", ["price:deductible"], ["cost_share.deductible", "cost_share.copay"])))
    copay = next(f for f in report.findings if f.rule_id == "R-CS-001")
    assert copay.status == "overridden" and copay.overridden_by == "R-ACC-001@1"
    assert len([f for f in report.findings if f.rule_id == "R-ACC-001"]) == 1   # deduplicated


def test_current_rules_mode_uses_newer_versions(system):
    exp = run(system.agents["utilization_management"].ask("Why was this rejected?", "RX-1001", rules_mode="current"))
    assert exp.primary.key == "R-PA-001@2"


def test_session_follow_up_reuses_findings(system):
    cs = system.agents["cost_share"]
    run(cs.ask("Why did the member pay $35?", "RX-1005", session_id="s1"))
    exp = run(cs.ask("Why did the member pay $35?", "RX-1005", session_id="s1"))
    assert exp.rounds[0].agents == [] and exp.primary.rule_id == "R-CS-001"


def test_failed_investigator_becomes_an_error_report(system):
    agent = system.agents["utilization_management"]

    class Broken:
        name = "prior_authorization"

        async def handle(self, t):
            raise RuntimeError("rule store unavailable")

    agent.executors["prior_authorization"] = Broken()
    exp = run(agent.ask("Why was this rejected?", "RX-1001"))
    assert exp.primary is None and "reject:75" in exp.gaps


def test_agent_cards_list_concepts_as_skills(system):
    card = agent_card(system.agents["utilization_management"])
    assert card["name"] == "pharmacy-utilization_management"
    skill = next(s for s in card["skills"] if s["id"] == "um.prior_authorization")
    assert "reject:75" in skill["tags"] and "rule_domain:prior_authorization" in skill["tags"]


def test_knowledge_question_without_a_claim(system):
    exp = run(system.agents["coverage"].ask("What does reject code 76 mean?"))
    assert exp.answer == "Reject code 76: Plan Limitations Exceeded"


# ------------------------------------------------- model layer, no SDK needed
def _completion(replies):
    async def complete(system: str, user: str) -> str:
        return replies.pop(0)
    return complete


def test_model_understanding_is_filtered(knowledge):
    lang = ModelLanguage(knowledge.taxonomy, knowledge.procedures.intents,
                         _completion(['{"intents": ["explain_outcome", "hack"], "concepts": ["um.step_therapy", "x.y"]}']))
    ask = run(lang.understand("why did this fail", "RX-1"))
    assert ask.intents == ["explain_outcome"] and ask.concepts == ["um.step_therapy"]


def test_model_narration_must_cite_known_rules(knowledge):
    bundle = {"rule_ids": ["R-PA-001"], "primary_rule": "R-PA-001"}
    good = ModelLanguage(knowledge.taxonomy, {}, _completion(["PA was needed [R-PA-001 v1]."]))
    bad = ModelLanguage(knowledge.taxonomy, {}, _completion(["It was R-XYZ-999."]))
    assert run(good.narrate(bundle, "template")) == "PA was needed [R-PA-001 v1]."
    assert run(bad.narrate(bundle, "template")) == "template"
