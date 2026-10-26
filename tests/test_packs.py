from datetime import date

import pytest

from rulegraph.models import Evidence
from rulegraph.rules.evaluator import referenced_paths, render
from rulegraph.rules.graph import PolicyGraph, Seed
from rulegraph.rules.validate import validate


def ev(path, value):
    return Evidence(source="reference" if path.startswith("plan") else "record", path=path, value=value)


def test_fragments_compose_with_the_base_and_validate(knowledge):
    assert validate(knowledge) == []
    assert knowledge.origin.startswith("pharmacy-claims + ") and "pharmacy-cost-share" in knowledge.origin


def test_taxonomy_agents_and_rule_domains(knowledge):
    tax = knowledge.taxonomy
    assert tax.rule_domains("cost_share") == {"benefit_copay", "accumulators"}
    assert tax.rule_domains("clinical_dur") == {"dur", "refill_too_soon"}
    assert tax.classify("reject:41").startswith("cob.")
    assert tax.precedence("eligibility.member_coverage") < tax.precedence("cost_share.copay")
    assert tax.rule_domains("utilization_management") == {"prior_authorization", "step_therapy", "quantity_limits"}


def test_question_matching_prefers_longest_labels(knowledge):
    found = knowledge.taxonomy.match_text("Why did the member pay a copay and not coinsurance?")
    assert {"cost_share.coinsurance", "cost_share.copay"} <= set(found)


def test_jsonld_exports_are_namespaced(knowledge):
    tax = knowledge.taxonomy.to_jsonld()
    node = next(n for n in tax["@graph"] if n["@id"].endswith("network.specialty_channel"))
    assert node["@id"].startswith("https://example.org/pharmacy/taxonomy/")
    onto = knowledge.ontology.to_jsonld()
    assert any(n["@id"].endswith("explains") for n in onto["@graph"])


def test_ontology_blocks_invalid_edges(knowledge):
    with pytest.raises(ValueError):
        PolicyGraph(knowledge.ontology).add_edge("field:claim.dos", "explains", "outcome:reject:75")


def test_graph_search_keeps_paths_and_respects_scope(knowledge):
    hits = knowledge.graph.search([Seed("outcome:reject:76", 1.0, "reject:76")], rule_concept=knowledge.rule_concepts())
    net = next(h for h in hits if h.rule_id == "R-NET-001")
    assert net.path == ["outcome:reject:76", "<-explains-", "rule:R-NET-001"]
    cob = knowledge.taxonomy.branch("cob")
    scoped = knowledge.graph.search([Seed("outcome:reject:76", 1.0, "reject:76")], scope_concepts=cob,
                                    rule_concept=knowledge.rule_concepts())
    assert "R-NET-001" not in {h.rule_id for h in scoped}


def test_missing_required_input_is_unverified(knowledge):
    card = knowledge.rules.rules["R-RTS-001@1"]
    values = {"claim.history.daysSinceLastFill": ev("claim.history.daysSinceLastFill", 10),
              "claim.history.lastDaysSupply": ev("claim.history.lastDaysSupply", 30)}
    result = knowledge.evaluator.evaluate(card, values)
    assert result.fired is None and "plan.dur.refillTooSoon.thresholdPct" in result.error


def test_pricing_amount_is_capped(knowledge):
    card = knowledge.rules.rules["R-CS-002@1"]
    values = {p: ev(p, v) for p, v in {
        "claim.pharmacy.channel": "retail", "claim.pricing.submittedCost": 1000.0,
        "plan.formulary.drug.tier": 4, "plan.costShare.coinsurancePct": 25.0, "plan.costShare.maxPerFill": 150.0,
    }.items()}
    assert knowledge.evaluator.evaluate(card, values).amount == 150.0


def test_templates_and_reference_extraction():
    values = {"plan.x": ev("plan.x", ["A", "B"]), "plan.m": ev("plan.m", 150.0)}
    assert render("{{plan.x|list}} cost ${{plan.m|money}}", values) == "A, B cost $150.00"
    assert referenced_paths("plan.a.b.exists(d, d in claim.c) && has(plan.e)", ("claim", "plan")) == \
        {"plan.a.b", "claim.c", "plan.e"}


def test_cost_share_slices_resolve_tier_and_channel_by_date(system):
    sep = system.toolbox.get_reference_slice("RX-1005", ["plan.costShare.copay"])["plan.costShare.copay"]
    may = system.toolbox.get_reference_slice("RX-1013", ["plan.costShare.copay"])["plan.costShare.copay"]
    assert sep.pointer == "/costShare/tiers/2/retail/copay"            # tier from the plan, channel from the claim
    assert (sep.reference_version, sep.value) == ("2026.07", 35.0)
    assert (may.reference_version, may.value) == ("2026.01", 30.0)


@pytest.mark.parametrize("agent", ["eligibility", "coverage", "utilization_management", "clinical_dur", "network",
                                   "cob", "cost_share"])
def test_each_domain_stands_alone_on_the_base(agent):
    """As if each domain were its own repo: its fragment, glossary terms and policy text validate with only the base."""
    import pharmacy_agents
    system = pharmacy_agents.build(agents=[agent])
    kn = system.knowledge
    assert validate(kn) == [] and list(system.agents) == [agent]
    own_terms = [t for t in kn.glossary.terms.values() if t.kind == "term" and any(
        kn.taxonomy.agent_for(c) == agent and not kn.taxonomy.get(c).agent for c in t.concepts)]
    assert own_terms, f"{agent} has no glossary terms of its own"
    cited = {r.doc + (f" / {r.section}" if r.section else "") for c in kn.rules.rules.values() for r in c.source_refs}
    assert cited <= set(kn.policies)
