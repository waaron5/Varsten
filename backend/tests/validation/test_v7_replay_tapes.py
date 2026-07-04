"""V7 — replay tapes with planted ground truth.

Three deterministic workload tapes, each with known-optimal savings planted in
its structure. Detection must find what was planted (quantified, not just
present), the measured savings must approach the theoretical availability
(capture rate — the honest 'how good is it' number), and the tape with nothing
to save must produce a near-no-op. Tapes are generated in-code from fixed seeds
rather than committed JSONL: byte-reproducible and reviewable in one place.
"""

import random
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from harness import TrafficFactory, ValidationReport, canary_scan
from sqlalchemy import select

from app.engine.agent_loops import detect_agent_loops
from app.models import Recommendation, UsageEvent
from app.recommendations import refresh_recommendations
from app.savings import month_start

# Big enough that the prompt-cache detector's >=1500-token bar is comfortably met.
SUPPORT_SYSTEM = "You are the support policy engine; apply every rule in order, verbatim. " * 90
AGENT_SYSTEM = "You are a research sub-agent. Current step context: "


@pytest.mark.anyio
async def test_v7_tape1_support_agent_capture_rate(sim_env, data_plane):
    """Tape 1: stable-prefix support traffic where 40% of requests are exact
    duplicates. Theoretical saving = the provider cost of every duplicate after
    its first occurrence (exact cache serves them at $0). Detection must also
    flag the stable prefix for prompt caching and the model for downshift."""
    report = ValidationReport(scenario="v7_tape1_support_agent")
    env = sim_env
    random.seed(20260704)
    env.provider.profile(env.model_big, reply=lambda n: "Spam")

    factory = TrafficFactory(env, model=env.model_big, feature="support_agent", system_prompt=SUPPORT_SYSTEM)
    # 15 distinct questions; 10 of them asked twice more (20 duplicate requests).
    distinct = [factory.next_request() for _ in range(15)]
    tape = list(distinct)
    for body, headers in distinct[:10]:
        tape.append((body, headers))
        tape.append((body, headers))
    random.shuffle(tape)

    for body, headers in tape:
        response = await data_plane.post("/v1/chat/completions", headers=headers, json=body)
        assert response.status_code == 200

    db = env.db()
    try:
        events = db.scalars(select(UsageEvent).where(UsageEvent.project_id == env.project_id)).all()
        hits = [e for e in events if (e.event_metadata or {}).get("cache") == "hit"]
        misses = [e for e in events if (e.event_metadata or {}).get("cache") == "miss"]
        report.metric("requests", len(tape))
        report.metric("cache_hits", len(hits))
        report.check("planted_duplicates_all_served_from_cache", len(hits) == 20, len(hits))

        # Capture rate: measured saved_usd vs the provider cost the duplicates
        # would have incurred (== a first-occurrence miss of the same request).
        captured = sum(Decimal((e.event_metadata or {})["saved_usd"]) for e in hits)
        per_request_cost = misses[0].cost_usd if misses else Decimal("0")
        theoretical = per_request_cost * 20
        rate = captured / theoretical if theoretical else Decimal("0")
        report.metric("captured_usd", str(captured))
        report.metric("theoretical_usd", str(theoretical))
        report.metric("capture_rate", str(round(rate, 4)))
        report.check("capture_rate_above_90pct", rate >= Decimal("0.9"), str(rate))

        refresh_recommendations(db, env.project(db))
        db.commit()
        recs = {r.type for r in db.scalars(select(Recommendation).where(Recommendation.project_id == env.project_id))}
        report.check("detects_stable_prefix_prompt_cache", "prompt_cache" in recs, sorted(recs))
        report.check("detects_downshift_candidate", "model_downshift" in recs, sorted(recs))
        canary_scan(env, report)
    finally:
        db.close()
    report.finish()


@pytest.mark.anyio
async def test_v7_tape2_agent_loop_detection_quantified(sim_env, data_plane, monkeypatch):
    """Tape 2: an agentic workflow of 8 traces; in every trace one of the 6
    calls is repeated twice (planted redundancy: 16 wasted calls of 64 total).
    The detector must quantify the waste within tolerance of the plant.

    The exact cache is disabled for this tape deliberately: with it on, the
    byte-identical repeats are served at $0 before they can be waste — the
    agent-loop detector's niche is exactly the redundancy the cache cannot
    absorb (uncached routes, TTL gaps), a real interplay this tape documents."""
    report = ValidationReport(scenario="v7_tape2_agent_loops")
    env = sim_env
    random.seed(7)
    from app.core.config import settings

    monkeypatch.setattr(settings, "proxy_cache_enabled", False)
    # Fixed token profile: every call costs the same, so planted waste is exact.
    # 1600 also keeps the route above the prompt-cache detector's 1500-token bar.
    env.provider.profile(
        env.model_help,
        reply=lambda n: "Step complete with detailed findings for the orchestrator.",
        input_tokens=1600,
    )

    factory = TrafficFactory(env, model=env.model_help, feature="research_agent", system_prompt=None)
    planted_redundant = 0
    total_calls = 0
    for trace in range(8):
        trace_id = f"trace-{env.run_id}-{trace}"
        steps = [f"{env.canary} step {trace}-{s}: gather source material" for s in range(6)]
        calls = list(steps)
        calls.append(steps[2])  # the agent re-asks step 2 ...
        calls.append(steps[2])  # ... twice.
        planted_redundant += 2
        for text in calls:
            body, headers = factory.next_request(trace_id=trace_id, user_text=text)
            # Per-trace volatile system prompt (big, unstable prefix by design).
            body["messages"].insert(0, {"role": "system", "content": f"{AGENT_SYSTEM}{trace_id} " + "ctx " * 2000})
            response = await data_plane.post("/v1/chat/completions", headers=headers, json=body)
            assert response.status_code == 200
            total_calls += 1

    db = env.db()
    try:
        findings = detect_agent_loops(db, env.project(db), month_start(datetime.now(UTC)))
        report.check("agent_loops_detected", len(findings) == 1, len(findings))
        top = findings[0]
        report.metric("planted_redundant_calls", planted_redundant)
        report.metric("detected_redundant_calls", top.redundant_calls)
        report.metric("affected_traces", top.affected_traces)
        report.check("redundancy_quantified_exactly", top.redundant_calls == planted_redundant, top.redundant_calls)
        report.check("all_traces_attributed", top.affected_traces == 8, top.affected_traces)

        # Wasted cost ~= redundant share of the loop groups' cost, measured.
        events = db.scalars(select(UsageEvent).where(UsageEvent.project_id == env.project_id)).all()
        per_call = events[0].cost_usd
        expected_waste = per_call * planted_redundant
        report.metric("detected_wasted_usd", str(top.wasted_cost_usd))
        report.metric("planted_wasted_usd", str(expected_waste))
        report.check(
            "waste_within_5pct_of_plant",
            abs(top.wasted_cost_usd - expected_waste) <= expected_waste * Decimal("0.05"),
            f"detected {top.wasted_cost_usd} vs planted {expected_waste}",
        )

        refresh_recommendations(db, env.project(db))
        db.commit()
        recs = {r.type for r in db.scalars(select(Recommendation).where(Recommendation.project_id == env.project_id))}
        report.check("agent_loop_recommended", "agent_loop" in recs, sorted(recs))
        report.check("unstable_prefix_flagged_for_restructure", "prompt_prefix_restructure" in recs, sorted(recs))
        canary_scan(env, report)
    finally:
        db.close()
    report.finish()


@pytest.mark.anyio
async def test_v7_tape3_nothing_to_save_mostly_noops(sim_env, data_plane):
    """Tape 3: high-variance chat with small prompts and no structure. An honest
    engine has almost nothing to do here and must not invent work: no savings,
    no cache/downshift/loop findings, only harmless housekeeping recs at most."""
    report = ValidationReport(scenario="v7_tape3_high_variance")
    env = sim_env
    random.seed(3)
    env.provider.profile(env.model_help, reply=lambda n: f"A different creative answer #{n} every single time.")

    factory = TrafficFactory(env, model=env.model_help, feature="chat", system_prompt=None)
    for i in range(25):
        body, headers = factory.next_request(user_text=f"{env.canary} totally novel question {i}")
        response = await data_plane.post("/v1/chat/completions", headers=headers, json=body)
        assert response.status_code == 200

    db = env.db()
    try:
        events = db.scalars(select(UsageEvent).where(UsageEvent.project_id == env.project_id)).all()
        report.check("no_savings_claimed", all(not (e.event_metadata or {}).get("saved_usd") for e in events))
        report.check("no_cache_hits", all((e.event_metadata or {}).get("cache") != "hit" for e in events))

        findings = detect_agent_loops(db, env.project(db), month_start(datetime.now(UTC)))
        report.check("no_agent_loops_invented", findings == [], len(findings))

        refresh_recommendations(db, env.project(db))
        db.commit()
        recs = {r.type for r in db.scalars(select(Recommendation).where(Recommendation.project_id == env.project_id))}
        invented = recs & {
            "prompt_cache",
            "prompt_prefix_restructure",
            "model_downshift",
            "agent_loop",
            "semantic_cache",
        }
        report.check("no_optimization_invented_for_unoptimizable_traffic", not invented, sorted(invented))
        report.metric("housekeeping_recommendations", sorted(recs))
        canary_scan(env, report)
    finally:
        db.close()
    report.finish()
