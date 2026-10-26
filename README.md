# pharmacy-agents

The pharmacy claim domain agents: **eligibility, coverage, utilization management, clinical DUR, network, COB and cost share**.

Each domain is a separate **knowledge fragment** (`src/pharmacy_agents/packs/<agent>/`) that extends the shared pharmacy base pack (`pharmacy-base`), and each is registered as its own `rulegraph.domains` entry point. Moving a domain to its own repo means moving its folder and entry point; nothing else changes.

Every domain agent is a planner with the core's capabilities: it plans which of its rule domains to check, runs its investigators concurrently, verifies every outcome in its scope is explained, runs its own bounded gap round, and answers from its domain's point of view with cited evidence. A core planner discovers the installed domain packages and calls the agents in process, sharing its context and memory.

| Agent | Rule domains |
|---|---|
| `eligibility` | eligibility |
| `coverage` | formulary (including exclusions) |
| `utilization_management` | prior_authorization, step_therapy, quantity_limits |
| `clinical_dur` | dur (drug interactions), refill_too_soon |
| `network` | network (pharmacy channel and limits) |
| `cob` | cob |
| `cost_share` | benefit_copay (copay, coinsurance), accumulators (deductible) |

```bash
pip install -r requirements-dev.txt                       # kernel and base, then this package
pharmacy-domains agents
pharmacy-domains validate
pharmacy-domains --today 2026-10-14 eval goldens/domain_goldens.yaml
pharmacy-domains ask cost_share RX-1005 "Why did the member pay $35?" --trace
pharmacy-domains view                                       # offline browser: graph, taxonomy, glossary, rules, policies
pytest
```

```python
import pharmacy_agents
system = pharmacy_agents.build()                                      # all seven on the pharmacy base
um = pharmacy_agents.build(agents=["utilization_management"])        # one domain alone, as its tests do
exp = await system.agents["coverage"].ask("Why isn't this covered?", "RX-1003")
```

Each fragment holds its taxonomy concepts, fields, rule domains and rules, its **glossary terms** (`glossary/terms.yaml`) and the **policy sections** its rules cite, with their text (`policies/policies.yaml`, sample text). `pharmacy-domains validate` checks every file against its JSON Schema and that every cited policy section exists; `tests/test_packs.py` checks each domain alone on the base, as if it were its own repo.

The `rule-graph-agent-system` skill in `.claude/skills/` covers building and splitting domain repos (`references/domain-repos.md`).
