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


def test_session_follow_up_reuses_findings(system):
    cs = system.agents["cost_share"]
    run(cs.ask("Why did the member pay $35?", "RX-1005", session_id="s1"))
    exp = run(cs.ask("Why did the member pay $35?", "RX-1005", session_id="s1"))
    assert exp.rounds[0].agents == [] and exp.primary.rule_id == "R-CS-001"


def test_failed_investigator_becomes_an_error_report(system):
    agent = system.agents["coverage"]

    class Broken:
        name = "formulary"

        async def handle(self, t):
            raise RuntimeError("rule store unavailable")

    agent.executors["formulary"] = Broken()
    exp = run(agent.ask("Why isn't this covered?", "RX-1003"))
    assert exp.primary is None and exp.gaps


def test_agent_cards_list_concepts_as_skills(system):
    card = agent_card(system.agents["cost_share"])
    assert card["name"] == "pharmacy-cost_share"
    skill = next(s for s in card["skills"] if s["id"] == "cost_share.copay")
    assert "price:copay" in skill["tags"] and "rule_domain:benefit_copay" in skill["tags"]


def test_six_packages_are_registered_separately():
    from rulegraph import discover
    names = {p.name for p in discover(extends="pharmacy-claims")}
    assert {"pharmacy-eligibility", "pharmacy-coverage", "pharmacy-clinical-dur", "pharmacy-network",
            "pharmacy-cob", "pharmacy-cost-share"} <= names


def test_runs_as_an_adk_workflow(system):
    pytest.importorskip("google.adk")
    from google.adk.runners import InMemoryRunner

    from rulegraph.adapters.adk import build_workflow

    async def go():
        runner = InMemoryRunner(node=build_workflow(system.agents["network"]), app_name="net")
        session = await runner.session_service.create_session(app_name="net", user_id="u")
        out = None
        async for ev in runner.run_async(user_id="u", session_id=session.id,
                                         state_delta={"request": {"record_id": "RX-1007", "question": "Why did this reject?"}}):
            if isinstance(ev.output, dict) and "answer" in ev.output:
                out = ev.output
        return out

    out = run(go())
    assert out["agent"] == "network" and out["primary"]["rule_id"] == "R-NET-001"


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
                         _completion(['{"intents": ["explain_outcome", "hack"], "concepts": ["network.specialty_channel", "x.y"]}']))
    ask = run(lang.understand("why did this fail", "RX-1"))
    assert ask.intents == ["explain_outcome"] and ask.concepts == ["network.specialty_channel"]


def test_model_narration_must_cite_known_rules(knowledge):
    bundle = {"rule_ids": ["R-PA-001"], "primary_rule": "R-PA-001"}
    good = ModelLanguage(knowledge.taxonomy, {}, _completion(["PA was needed [R-PA-001 v1]."]))
    bad = ModelLanguage(knowledge.taxonomy, {}, _completion(["It was R-XYZ-999."]))
    assert run(good.narrate(bundle, "template")) == "PA was needed [R-PA-001 v1]."
    assert run(bad.narrate(bundle, "template")) == "template"
