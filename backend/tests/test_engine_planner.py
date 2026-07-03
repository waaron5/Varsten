from app.engine import (
    build_observe_only_plan,
    classify_request,
    normalize_request_facts,
    outcome_prior_from_learning_candidate,
    plan_to_metadata,
)
from app.engine.types import CandidateStatus, OutcomePrior, PlannerInput, QualityGateStatus, RequestFacts
from app.proxy.evidence import DecisionDraft, _decision_metadata
from app.proxy.request_context import RequestContext


def _candidate(plan, lever: str):
    return next(candidate for candidate in plan.candidates if candidate.lever == lever)


def _cache_gate(candidate):
    return candidate.reason_detail["cache_gate"]


def test_low_risk_plan_marks_candidates_without_authorizing_execution():
    ctx = RequestContext(task_type="classification.intent", task_confidence=0.95, risk_level="low")
    body = {"messages": [{"role": "user", "content": "Classify this support ticket."}]}

    plan = build_observe_only_plan(
        PlannerInput(
            request_id="req_123",
            provider="openai",
            model="gpt-4o",
            body=body,
            context=ctx,
            semantic_cache_enabled=True,
            routing_policy_present=True,
            routing_policy_id="route-policy-123",
            trim_policy_present=True,
            trim_policy_id="trim-policy-456",
        )
    )

    # Exact cache is eligible and gate-cleared, so the planner selects it to enforce.
    assert plan.selected.action == "exact_cache"
    assert plan.selected.mode == "enforce"
    assert _candidate(plan, "exact_cache").status == CandidateStatus.ELIGIBLE
    assert _candidate(plan, "exact_cache").quality_gate == QualityGateStatus.NOT_REQUIRED
    assert _cache_gate(_candidate(plan, "exact_cache")) == {
        "mode": "shadow",
        "decision": "allow",
        "enforced": False,
        "reason_code": "cache_gate_shadow_allow",
        "blockers": [],
    }
    assert _candidate(plan, "semantic_cache").status == CandidateStatus.SHADOW_ONLY
    assert _cache_gate(_candidate(plan, "semantic_cache"))["decision"] == "allow"
    assert _candidate(plan, "model_routing").status == CandidateStatus.SHADOW_ONLY
    assert _candidate(plan, "model_routing").policy_id == "route-policy-123"
    assert _candidate(plan, "token_trim").status == CandidateStatus.SHADOW_ONLY
    assert _candidate(plan, "token_trim").policy_id == "trim-policy-456"


def test_unknown_task_blocks_optimization_candidates():
    body = {"messages": [{"role": "user", "content": "Summarize this."}]}

    plan = build_observe_only_plan(
        PlannerInput(
            request_id="req_unknown",
            provider="openai",
            model="gpt-4o",
            body=body,
            semantic_cache_enabled=True,
            routing_policy_present=True,
            trim_policy_present=True,
        )
    )

    assert plan.classification.unknown_task is True
    assert "unknown_task" in plan.classification.reason_codes
    assert plan.selected.action == "observe"
    for lever in ("exact_cache", "semantic_cache"):
        candidate = _candidate(plan, lever)
        assert candidate.status == CandidateStatus.REJECTED
        assert _cache_gate(candidate)["decision"] == "reject"
        assert _cache_gate(candidate)["enforced"] is False
        assert _cache_gate(candidate)["blockers"] == ["risky_or_unknown"]
    for lever in ("model_routing", "token_trim"):
        candidate = _candidate(plan, lever)
        assert candidate.status == CandidateStatus.REJECTED
        assert candidate.reason_detail["blockers"] == ["risky_or_unknown"]


def test_high_risk_fresh_personalized_request_rejects_cache_and_risky_levers():
    ctx = RequestContext(task_type="finance.trade", task_confidence=0.9, risk_level="high", customer_id="cust_123")
    body = {"messages": [{"role": "user", "content": "What is the latest stock price for my account?"}]}

    plan = build_observe_only_plan(
        PlannerInput(
            request_id="req_risky",
            provider="openai",
            model="gpt-4o",
            body=body,
            context=ctx,
            semantic_cache_enabled=True,
            routing_policy_present=True,
            routing_policy_id="route-policy-risky",
            trim_policy_present=True,
            trim_policy_id="trim-policy-risky",
        )
    )

    assert {"risk_high", "freshness_sensitive", "personalized_request"} <= set(plan.classification.reason_codes)
    assert _candidate(plan, "exact_cache").status == CandidateStatus.REJECTED
    assert _candidate(plan, "semantic_cache").status == CandidateStatus.REJECTED
    assert _cache_gate(_candidate(plan, "exact_cache"))["blockers"] == [
        "risky_or_unknown",
        "personalized_request",
        "freshness_sensitive",
    ]
    assert _candidate(plan, "model_routing").status == CandidateStatus.REJECTED
    assert _candidate(plan, "model_routing").policy_id == "route-policy-risky"
    assert _candidate(plan, "token_trim").status == CandidateStatus.REJECTED
    assert _candidate(plan, "token_trim").policy_id == "trim-policy-risky"
    assert _candidate(plan, "exact_cache").estimated_savings_usd is None


def test_cache_shadow_gate_rejects_tool_dependent_requests_without_authorizing_execution():
    ctx = RequestContext(task_type="agent.lookup", task_confidence=0.9, risk_level="low")
    body = {
        "messages": [{"role": "user", "content": "Look up this account."}],
        "tools": [{"type": "function", "function": {"name": "get_account"}}],
    }

    plan = build_observe_only_plan(
        PlannerInput(
            request_id="req_tool_cache",
            provider="openai",
            model="gpt-4o-mini",
            body=body,
            context=ctx,
            semantic_cache_enabled=True,
        )
    )

    assert plan.selected.action == "observe"
    for lever in ("exact_cache", "semantic_cache"):
        candidate = _candidate(plan, lever)
        assert candidate.status == CandidateStatus.REJECTED
        gate = _cache_gate(candidate)
        assert gate["mode"] == "shadow"
        assert gate["decision"] == "reject"
        assert gate["enforced"] is False
        assert gate["blockers"] == ["tools_present"]


def test_disabled_features_are_unavailable_not_implicitly_eligible():
    ctx = RequestContext(task_type="summarization.short", task_confidence=0.8, risk_level="low")
    body = {"messages": [{"role": "user", "content": "Summarize this paragraph."}]}

    plan = build_observe_only_plan(
        PlannerInput(
            request_id="req_disabled",
            provider="openai",
            model="gpt-4o-mini",
            body=body,
            context=ctx,
            optimize_enabled=False,
            semantic_cache_enabled=True,
            routing_policy_present=True,
            trim_policy_present=True,
        )
    )

    assert plan.selected.action == "observe"
    assert {candidate.status for candidate in plan.candidates} == {CandidateStatus.UNAVAILABLE}
    assert {candidate.reason_code for candidate in plan.candidates} == {"optimization_disabled"}


def test_classifier_detects_tools_json_and_multimodal_without_returning_prompt_text():
    body = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Return structured fields from this image."},
                    {"type": "image_url", "image_url": {"url": "https://example.invalid/image.png"}},
                ],
            }
        ],
        "tools": [{"type": "function", "function": {"name": "lookup"}}],
        "response_format": {"type": "json_schema", "json_schema": {"name": "fields", "schema": {}}},
    }

    classification = classify_request(
        body,
        RequestContext(task_type="vision.extract", task_confidence=0.95, risk_level="low"),
    )

    assert classification.has_tools is True
    assert classification.wants_json is True
    assert classification.has_multimodal is True
    assert classification.prompt_chars == len("Return structured fields from this image.")
    assert {"tools_present", "json_output", "multimodal_content"} <= set(classification.reason_codes)
    assert "Return structured fields from this image." not in classification.reason_codes


def test_request_facts_normalize_gemini_native_shape_without_prompt_text():
    prompt = "Return the latest weather as JSON."
    body = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": prompt},
                    {"inlineData": {"mimeType": "image/png", "data": "redacted"}},
                ],
            }
        ],
        "tools": [{"functionDeclarations": [{"name": "lookup_weather"}]}],
        "generationConfig": {"responseMimeType": "application/json"},
    }

    facts = normalize_request_facts(body)
    classification = classify_request(
        facts,
        RequestContext(task_type="weather.lookup", task_confidence=0.9, risk_level="low"),
    )

    assert facts.message_count == 1
    assert facts.prompt_chars == len(prompt)
    assert facts.has_tools is True
    assert facts.wants_json is True
    assert facts.has_multimodal is True
    assert facts.freshness_signal is True
    assert classification.has_tools is True
    assert classification.wants_json is True
    assert classification.has_multimodal is True
    assert classification.freshness_sensitive is True
    assert {"tools_present", "json_output", "multimodal_content", "freshness_sensitive"} <= set(
        classification.reason_codes
    )
    assert prompt not in str(facts)
    assert prompt not in str(classification)


def test_planner_accepts_precomputed_request_facts_as_provider_agnostic_input():
    facts = RequestFacts(
        prompt_chars=42,
        message_count=3,
        has_tools=False,
        wants_json=False,
        has_multimodal=False,
        freshness_signal=False,
        personalized_signal=False,
        high_risk_signal=False,
        source="adapter",
    )
    raw_body_with_private_text = {"messages": [{"role": "user", "content": "latest legal advice for my account"}]}

    plan = build_observe_only_plan(
        PlannerInput(
            request_id="req_provider_facts",
            provider="gemini",
            model="gemini-2.5-flash",
            body=raw_body_with_private_text,
            request_facts=facts,
            context=RequestContext(task_type="classification.intent", task_confidence=0.9, risk_level="low"),
            semantic_cache_enabled=True,
        )
    )

    assert plan.classification.prompt_chars == 42
    assert plan.classification.message_count == 3
    assert plan.classification.freshness_sensitive is False
    assert plan.classification.personalized is False
    assert plan.classification.risk_level.value == "low"
    assert _candidate(plan, "exact_cache").status == CandidateStatus.ELIGIBLE
    assert "latest legal advice for my account" not in str(plan_to_metadata(plan))


def test_plan_metadata_serializer_excludes_request_text():
    prompt = "Classify this private customer note."
    plan = build_observe_only_plan(
        PlannerInput(
            request_id="req_meta",
            provider="openai",
            model="gpt-4o-mini",
            body={"messages": [{"role": "user", "content": prompt}]},
            context=RequestContext(task_type="classification.intent", task_confidence=0.9, risk_level="low"),
        )
    )

    metadata = plan_to_metadata(plan)

    assert metadata["planner_version"] == "planner_v1_observe_only"
    assert metadata["selected"]["action"] == "exact_cache"
    assert metadata["classification"]["prompt_chars"] == len(prompt)
    assert prompt not in str(metadata)


def test_plan_metadata_serializer_includes_policy_ids():
    plan = build_observe_only_plan(
        PlannerInput(
            request_id="req_policy",
            provider="openai",
            model="gpt-4o-mini",
            body={"messages": [{"role": "user", "content": "Classify this."}]},
            context=RequestContext(task_type="classification.intent", task_confidence=0.9, risk_level="low"),
            routing_policy_present=True,
            routing_policy_id="route-policy-123",
            trim_policy_present=True,
            trim_policy_id="trim-policy-456",
        )
    )

    candidates = {candidate["lever"]: candidate for candidate in plan_to_metadata(plan)["candidates"]}

    assert candidates["model_routing"]["policy_id"] == "route-policy-123"
    assert candidates["model_routing"]["status"] == "shadow_only"
    assert candidates["token_trim"]["policy_id"] == "trim-policy-456"
    assert candidates["token_trim"]["status"] == "shadow_only"


def test_outcome_prior_marks_policyless_route_recommendable_without_authorizing_execution():
    ctx = RequestContext(task_type="classification.intent", task_confidence=0.95, risk_level="low")
    prior = OutcomePrior(
        lever="model_downshift",
        readiness_status="recommendable",
        sample_count=8,
        measured_savings_count=8,
        total_gross_savings_usd="0.80",
        average_gross_savings_usd="0.10",
        quality_pass_rate="1.0000",
        feedback_acceptance_rate="1.0000",
        reason_codes=("sample_count_below_auto_threshold",),
    )

    plan = build_observe_only_plan(
        PlannerInput(
            request_id="req_prior",
            provider="openai",
            model="gpt-4o",
            body={"messages": [{"role": "user", "content": "Classify this."}]},
            context=ctx,
            outcome_priors=(prior,),
        )
    )

    candidate = _candidate(plan, "model_routing")
    # Exact cache is eligible and takes selection priority; the routing candidate is
    # still upgraded to recommendable by the prior (visible in the candidates).
    assert plan.selected.action == "exact_cache"
    assert plan.selected.mode == "enforce"
    assert candidate.status == CandidateStatus.RECOMMENDABLE
    assert candidate.quality_gate == QualityGateStatus.PASSED
    assert candidate.reason_code == "outcome_prior_recommendable"
    assert candidate.estimated_savings_usd == "0.10"
    assert candidate.reason_detail["outcome_prior"] == {
        "readiness_status": "recommendable",
        "sample_count": 8,
        "measured_savings_count": 8,
        "total_gross_savings_usd": "0.80",
        "average_gross_savings_usd": "0.10",
        "quality_pass_rate": "1.0000",
        "feedback_acceptance_rate": "1.0000",
        "reason_codes": ["sample_count_below_auto_threshold"],
    }
    metadata_candidate = next(c for c in plan_to_metadata(plan)["candidates"] if c["lever"] == "model_routing")
    assert metadata_candidate["status"] == "recommendable"
    assert metadata_candidate["estimated_savings_usd"] == "0.10"


def test_quality_risk_prior_is_audit_only_and_does_not_recommend():
    ctx = RequestContext(task_type="support.reply", task_confidence=0.9, risk_level="low")
    prior = OutcomePrior(
        lever="token_trim",
        readiness_status="quality_risk",
        sample_count=12,
        measured_savings_count=12,
        total_gross_savings_usd="0.24",
        average_gross_savings_usd="0.02",
        quality_pass_rate="0.9000",
        feedback_acceptance_rate="0.7500",
        reason_codes=("quality_pass_rate_low", "corrective_feedback_present"),
    )

    plan = build_observe_only_plan(
        PlannerInput(
            request_id="req_quality_risk_prior",
            provider="openai",
            model="gpt-4o-mini",
            body={"messages": [{"role": "user", "content": "Draft a reply."}]},
            context=ctx,
            trim_policy_present=True,
            trim_policy_id="trim-policy-risk",
            outcome_priors=(prior,),
        )
    )

    candidate = _candidate(plan, "token_trim")
    assert candidate.status == CandidateStatus.SHADOW_ONLY
    assert candidate.reason_code == "trim_requires_quality_gate"
    assert candidate.reason_detail["outcome_prior"]["readiness_status"] == "quality_risk"
    assert candidate.reason_detail["outcome_prior"]["reason_codes"] == [
        "quality_pass_rate_low",
        "corrective_feedback_present",
    ]


def test_outcome_prior_does_not_override_risky_rejection():
    prior = OutcomePrior(
        lever="model_downshift",
        readiness_status="auto_apply_candidate",
        sample_count=50,
        measured_savings_count=50,
        total_gross_savings_usd="5.00",
        average_gross_savings_usd="0.10",
        quality_pass_rate="1.0000",
        feedback_acceptance_rate="1.0000",
    )

    plan = build_observe_only_plan(
        PlannerInput(
            request_id="req_prior_risky",
            provider="openai",
            model="gpt-4o",
            body={"messages": [{"role": "user", "content": "What is the latest price for my portfolio?"}]},
            context=RequestContext(task_type="finance.trade", task_confidence=0.9, risk_level="high"),
            routing_policy_present=True,
            routing_policy_id="route-policy-risky",
            outcome_priors=(prior,),
        )
    )

    candidate = _candidate(plan, "model_routing")
    assert candidate.status == CandidateStatus.REJECTED
    assert candidate.reason_code == "routing_blocked_by_risk"
    assert candidate.reason_detail["outcome_prior"]["readiness_status"] == "auto_apply_candidate"
    assert plan.selected.action == "observe"


def test_learning_candidate_can_round_trip_into_planner_prior():
    prior = outcome_prior_from_learning_candidate(
        {
            "segment": {"lever": "exact_cache"},
            "sample_count": 20,
            "measured_savings_count": 20,
            "total_gross_savings_usd": "0.20",
            "average_gross_savings_usd": "0.01",
            "quality": {"pass_rate": "1.0000"},
            "feedback": {"acceptance_rate": "1.0000"},
            "readiness": {"status": "auto_apply_candidate", "reason_codes": []},
        }
    )
    plan = build_observe_only_plan(
        PlannerInput(
            request_id="req_cache_prior",
            provider="openai",
            model="gpt-4o-mini",
            body={"messages": [{"role": "user", "content": "Classify this."}]},
            context=RequestContext(task_type="classification.intent", task_confidence=0.9, risk_level="low"),
            outcome_priors=(prior,),
        )
    )

    candidate = _candidate(plan, "exact_cache")
    assert candidate.status == CandidateStatus.RECOMMENDABLE
    assert candidate.reason_detail["outcome_prior"]["readiness_status"] == "auto_apply_candidate"
    # The recommendable cache candidate is the selected (enforceable) action.
    assert plan.selected.action == "exact_cache"
    assert plan.selected.mode == "enforce"


def test_decision_metadata_includes_content_free_optimization_plan():
    prompt = "Summarize this internal note."
    ctx = RequestContext(task_type="summarization.short", task_confidence=0.8, risk_level="low")
    plan = build_observe_only_plan(
        PlannerInput(
            request_id="req_draft",
            provider="openai",
            model="gpt-4o-mini",
            body={"messages": [{"role": "user", "content": prompt}]},
            context=ctx,
        )
    )
    draft = DecisionDraft(
        request_id="req_draft",
        client_dialect="openai",
        provider_requested="openai",
        model_requested="gpt-4o-mini",
        ctx=ctx,
        optimization_plan=plan,
    )
    draft.add_runtime_trace(
        stage="cache_lookup",
        lever="semantic_cache",
        action="skipped",
        reason_code="semantic_cache_policy_blocked",
        enforced=True,
        detail={
            "blockers": ["risky_or_unknown"],
            "messages": [{"role": "user", "content": prompt}],
            "tool_arguments": '{"private": true}',
        },
    )

    metadata = _decision_metadata(draft)

    assert metadata["task_type"] == "summarization.short"
    assert metadata["optimization_plan"]["selected"]["action"] == "exact_cache"
    assert metadata["optimization_plan"]["classification"]["prompt_chars"] == len(prompt)
    assert metadata["runtime_trace"] == [
        {
            "stage": "cache_lookup",
            "lever": "semantic_cache",
            "action": "skipped",
            "reason_code": "semantic_cache_policy_blocked",
            "enforced": True,
            "detail": {"blockers": ["risky_or_unknown"]},
        }
    ]
    assert prompt not in str(metadata)
    assert "private" not in str(metadata)
