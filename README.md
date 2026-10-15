# pharmacy-agents

Pharmacy claim domain agents built on the `rulegraph` kernel. Each agent is a **planner** scoped to one branch of the adjudication taxonomy, with the same capabilities as a core agent: it understands the question, plans which rule domains to check, runs its **investigators** concurrently, verifies every outcome in its scope is explained, runs its own bounded gap round (policy graph, related concepts, sweep of its scope), and answers from its domain's point of view with cited evidence. Outcomes outside its scope are reported as out of scope, never guessed.

The agents work on their own or under a core planner, which imports this package and calls them in process (no network hop between core and domain agents).

| Agent | Rule domains |
|---|---|
| `eligibility` | eligibility |
| `coverage` | formulary (including exclusions) |
| `utilization_management` | prior_authorization, step_therapy, quantity_limits |
| `clinical_dur` | dur (drug interactions), refill_too_soon |
| `network` | network (pharmacy channel and limits) |
| `cob` | cob |
| `cost_share` | benefit_copay (copay, coinsurance), accumulators (deductible) |

## Quick start

```bash
pip install -r requirements-dev.txt
pharmacy-agents agents
pharmacy-agents validate
pharmacy-agents --today 2026-10-14 eval                # domain goldens
pharmacy-agents ask utilization_management RX-1001 "Why was this rejected?"
pharmacy-agents ask cost_share RX-1005 "Why did the member pay $35?"
pytest                                                 # 40 tests
```

From Python:

```python
from pharmacy_agents import build
system = build()                                   # fixtures; set PHARMACY_CLAIMS_URL / PHARMACY_BENEFITS_URL for real APIs
exp = await system.agents["coverage"].ask("Why isn't this covered?", "RX-1003")
report = await system.agents["network"].handle(task)   # a DomainTask from a core planner
```

## Layout

| Path | What it is |
|---|---|
| `src/pharmacy_agents/pack/` | Knowledge pack: taxonomy, ontology, field catalog, reject codes, rule domains and cards, procedures, wording |
| `src/pharmacy_agents/record.py` | Claim adapter: status, reject and price tokens, dates, derived fields |
| `src/pharmacy_agents/system.py` | Builds the toolbox (fixtures or HTTP APIs) and the domain agents |
| `src/pharmacy_agents/fixtures/` | Synthetic claims and a versioned benefit setup (~12k fields) |
| `goldens/domain_goldens.yaml` | Questions for each domain agent with expected answers |
| `.claude/skills/rule-graph-agent-system/` | Claude skill for building and extending core and domain agents on the kernel |

The ADK adapter is optional (`.[adk]`): `rulegraph.adapters.adk.build_workflow(agent)` runs any domain agent as an ADK workflow graph. Other SDKs: see the skill's `references/sdk-adapters.md`.
