import json

import pytest

from app.config import Settings
from app.operator.browser import PageElement, PageObservation
from app.operator.planner import Planner, PlannerError, extract_json
from app.operator.providers import (
    Completion,
    ProviderError,
    build_client,
    estimate_cost,
    resolve_provider,
)

VALID = {
    "rationale": "Open the vendor directory to find Acme.",
    "action": "click",
    "params": {"ref": "e4", "label": "Open vendor directory"},
}


class FakeClient:
    provider = "fake"
    model = "fake-model"

    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []

    async def complete(self, *, system, user, schema):
        self.prompts.append(user)
        text = self.replies.pop(0)
        return Completion(text=text, input_tokens=100, output_tokens=25, model=self.model)


def observation():
    return PageObservation(
        url="https://portal.test/",
        title="Portal",
        text="Vendor portal",
        elements=[PageElement(ref="e4", tag="a", type="", role="", name="Open vendor directory")],
    )


async def plan_with(replies):
    planner = Planner(client=FakeClient(replies))
    return await planner.plan(goal="Find Acme", observation=observation(), history=[])


class TestJsonExtraction:
    def test_plain_json(self):
        assert extract_json('{"a": 1}') == {"a": 1}

    def test_fenced_json(self):
        assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}

    def test_unlabelled_fence(self):
        assert extract_json('```\n{"a": 1}\n```') == {"a": 1}

    def test_json_wrapped_in_prose(self):
        assert extract_json('Sure! Here you go:\n{"a": 1}\nHope that helps.') == {"a": 1}

    def test_nested_braces_survive(self):
        payload = {"params": {"nested": {"deep": True}}}
        assert extract_json(f"text {json.dumps(payload)} more") == payload

    def test_no_json_raises(self):
        with pytest.raises(PlannerError):
            extract_json("I cannot help with that.")


class TestPlanning:
    async def test_clean_reply_is_parsed(self):
        result = await plan_with([json.dumps(VALID)])
        assert result.action.action == "click"
        assert result.action.params["ref"] == "e4"
        assert result.input_tokens == 100

    async def test_chatty_reply_is_recovered(self):
        result = await plan_with([f"Here is my plan:\n```json\n{json.dumps(VALID)}\n```"])
        assert result.action.action == "click"

    async def test_malformed_reply_triggers_one_repair(self):
        client = FakeClient(["not json at all", json.dumps(VALID)])
        planner = Planner(client=client)
        result = await planner.plan(goal="g", observation=observation(), history=[])
        assert result.action.action == "click"
        assert len(client.prompts) == 2
        assert "rejected" in client.prompts[1]

    async def test_tokens_accumulate_across_the_repair(self):
        result = await plan_with(["garbage", json.dumps(VALID)])
        assert result.input_tokens == 200
        assert result.output_tokens == 50

    async def test_two_bad_replies_fail_loudly(self):
        with pytest.raises(PlannerError, match="unusable output twice"):
            await plan_with(["garbage", "still garbage"])

    async def test_schema_violation_is_repaired(self):
        bad = json.dumps({"rationale": "x", "params": {}})  # missing 'action'
        result = await plan_with([bad, json.dumps(VALID)])
        assert result.action.action == "click"

    async def test_history_is_included_in_the_prompt(self):
        client = FakeClient([json.dumps(VALID)])
        planner = Planner(client=client)
        await planner.plan(
            goal="g",
            observation=observation(),
            history=[{"index": 1, "action": "navigate", "outcome": "succeeded"}],
        )
        assert "navigate" in client.prompts[0]

    async def test_page_elements_reach_the_prompt(self):
        client = FakeClient([json.dumps(VALID)])
        planner = Planner(client=client)
        await planner.plan(goal="g", observation=observation(), history=[])
        assert "e4" in client.prompts[0] and "Open vendor directory" in client.prompts[0]


class TestProviderResolution:
    def test_groq_is_the_default(self):
        config = resolve_provider(Settings(groq_api_key="k"))
        assert config.provider == "groq"
        assert config.base_url.startswith("https://api.groq.com")
        assert config.model == "llama-3.3-70b-versatile"
        assert config.configured

    def test_provider_specific_key_is_picked_up(self):
        config = resolve_provider(Settings(llm_provider="openrouter", openrouter_api_key="k"))
        assert config.api_key == "k"
        assert config.configured

    def test_generic_key_overrides_provider_key(self):
        config = resolve_provider(Settings(llm_provider="groq", groq_api_key="a", llm_api_key="b"))
        assert config.api_key == "b"

    def test_model_override_is_honoured(self):
        config = resolve_provider(
            Settings(llm_provider="groq", groq_api_key="k", planner_model="llama-3.1-8b-instant")
        )
        assert config.model == "llama-3.1-8b-instant"

    def test_base_url_override_is_honoured(self):
        config = resolve_provider(
            Settings(llm_provider="groq", groq_api_key="k", llm_base_url="http://localhost:1234/v1")
        )
        assert config.base_url == "http://localhost:1234/v1"

    def test_ollama_needs_no_key(self):
        assert resolve_provider(Settings(llm_provider="ollama")).configured

    def test_missing_key_is_reported_as_unconfigured(self):
        assert not resolve_provider(Settings(llm_provider="groq")).configured

    def test_unknown_provider_rejected(self):
        with pytest.raises(ProviderError, match="unknown LLM_PROVIDER"):
            resolve_provider(Settings(llm_provider="hal9000"))

    def test_build_client_without_a_key_explains_how_to_fix_it(self):
        with pytest.raises(ProviderError) as exc:
            build_client(Settings(llm_provider="groq"))
        assert "console.groq.com" in str(exc.value)

    def test_anthropic_is_still_selectable(self):
        config = resolve_provider(Settings(llm_provider="anthropic", anthropic_api_key="k"))
        assert config.model == "claude-opus-5"
        assert config.base_url is None


class TestPricing:
    def test_known_model_is_priced(self):
        assert estimate_cost("llama-3.3-70b-versatile", 1_000_000, 0) == pytest.approx(0.59)

    def test_claude_pricing_retained(self):
        assert estimate_cost("claude-opus-5", 1_000_000, 1_000_000) == pytest.approx(30.0)

    def test_unknown_model_costs_zero_rather_than_guessing(self):
        assert estimate_cost("some-new-model", 5000, 5000) == 0.0
