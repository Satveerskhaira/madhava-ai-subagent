from datetime import date

import pytest

from rulegraph.models import Evidence
from rulegraph.rules.evaluator import referenced_paths, render
from rulegraph.rules.graph import PolicyGraph, Seed
from rulegraph.rules.validate import validate
from rulegraph.tools.apis import count_leaves


def ev(path, value):
    return Evidence(source="reference" if path.startswith("plan") else "record", path=path, value=value)


# ------------------------------------------------------------------ pack
def test_pack_validates_cleanly(knowledge):
    assert validate(knowledge) == []


def test_taxonomy_defines_agents_and_rule_domains(knowledge):
    tax = knowledge.taxonomy
    assert list(tax.agents) == ["eligibility", "coverage", "utilization_management", "clinical_dur",
                                "network", "cob", "cost_share"]
    assert tax.rule_domains("utilization_management") == {"prior_authorization", "step_therapy", "quantity_limits"}
    assert tax.classify("reject:75") == "um.prior_authorization"
    assert tax.precedence("eligibility.member_coverage") < tax.precedence("um.prior_authorization")
    assert "um.quantity_limits" in tax.get("network.specialty_channel").related


def test_question_matching_prefers_longest_labels(knowledge):
    found = knowledge.taxonomy.match_text("Is prior authorization needed, or is it a plan limit?")
    assert found[:2] == ["um.prior_authorization", "um.quantity_limits"]
    assert "um.prior_authorization" not in knowledge.taxonomy.match_text("why did the member pay this?")


def test_jsonld_exports_are_namespaced(knowledge):
    tax = knowledge.taxonomy.to_jsonld()
    pa_node = next(n for n in tax["@graph"] if n["@id"].endswith("um.prior_authorization"))
    assert pa_node["@id"].startswith("https://example.org/pharmacy/taxonomy/")
    onto = knowledge.ontology.to_jsonld()
    assert any(n["@id"].endswith("explains") for n in onto["@graph"])


def test_ontology_blocks_invalid_edges(knowledge):
    with pytest.raises(ValueError):
        PolicyGraph(knowledge.ontology).add_edge("field:claim.dos", "explains", "outcome:reject:75")


def test_rule_sets_resolve_by_date(knowledge):
    store = knowledge.rules
    assert store.rule_set("prior_authorization", date(2026, 9, 14)).id == "RS-PA-2026.01.1"
    assert store.resolve_rule("R-PA-001", date(2026, 10, 1))[1].version == 2
    assert store.diff("prior_authorization", date(2026, 9, 1), date(2026, 10, 14))["changed"] == ["R-PA-001@1->2"]


def test_graph_search_keeps_paths_and_respects_scope(knowledge):
    hits = knowledge.graph.search([Seed("outcome:reject:76", 1.0, "reject:76")], rule_concept=knowledge.rule_concepts())
    net = next(h for h in hits if h.rule_id == "R-NET-001")
    assert net.path == ["outcome:reject:76", "<-explains-", "rule:R-NET-001"]
    um = knowledge.taxonomy.branch("utilization_management")
    scoped = knowledge.graph.search([Seed("outcome:reject:76", 1.0, "reject:76")], scope_concepts=um,
                                    rule_concept=knowledge.rule_concepts())
    assert "R-NET-001" not in {h.rule_id for h in scoped}


# ------------------------------------------------------------- rules
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


# -------------------------------------------------------------- data
def test_claim_adapter_derives_fields_and_tokens(system):
    snap = system.toolbox.get_record_outcome("RX-1002")
    assert snap["record"]["history"]["daysSinceLastFill"] == 11
    assert snap["outcome_tokens"] == ["reject:79"] and snap["adverse"] is True
    assert system.toolbox.get_record_outcome("RX-1006")["amount_tokens"] == ["price:deductible"]


def test_reference_slices_are_small_and_dated(system):
    plan = system.toolbox.references.get_as_of("PLN-COMM-4T", date(2026, 9, 1))
    assert count_leaves(plan.payload) > 12000
    sep = system.toolbox.get_reference_slice("RX-1005", ["plan.costShare.copay"])["plan.costShare.copay"]
    may = system.toolbox.get_reference_slice("RX-1013", ["plan.costShare.copay"])["plan.costShare.copay"]
    assert sep.pointer == "/costShare/tiers/2/retail/copay"            # tier from the plan, channel from the claim
    assert (sep.reference_version, sep.value) == ("2026.07", 35.0)
    assert (may.reference_version, may.value) == ("2026.01", 30.0)
    missing = system.toolbox.get_reference_slice("RX-1001", ["plan.formulary.drug.excluded"])
    assert missing["plan.formulary.drug.excluded"].present is False
