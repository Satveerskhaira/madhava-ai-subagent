"""A domain agent also runs as a Google ADK workflow graph (optional adapter)."""

import asyncio

import pytest

pytest.importorskip("google.adk")


def test_domain_agent_as_adk_workflow(system):
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

    out, routes = asyncio.run(go())
    assert routes == ["gap", "done"]                    # the domain agent's own bounded loop
    assert out["agent"] == "utilization_management" and out["gaps"] == ["reject:76"]
