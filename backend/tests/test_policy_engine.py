import pytest
from pydantic import ValidationError

from app.enums import Effect
from app.policy import PolicyEngine, PolicySpec, build_context
from app.policy.engine import MISSING, resolve_path


def engine_with(rules, default=Effect.REQUIRE_APPROVAL) -> PolicyEngine:
    return PolicyEngine(PolicySpec(name="test", default_effect=default, rules=rules))


def rule(rule_id, effect, when, priority=0, **kwargs):
    return {"id": rule_id, "effect": effect, "priority": priority, "when": when, **kwargs}


def ctx(**overrides):
    base = {"action": {"type": "click", "label": "Next", "amount_usd": 100}, "page": {"url": ""}}
    base.update(overrides)
    return base


class TestPathResolution:
    def test_resolves_nested_path(self):
        assert resolve_path({"a": {"b": {"c": 7}}}, "a.b.c") == 7

    def test_missing_key_returns_sentinel(self):
        assert resolve_path({"a": {}}, "a.b") is MISSING

    def test_descending_into_non_dict_returns_sentinel(self):
        assert resolve_path({"a": 5}, "a.b") is MISSING

    def test_falsy_values_are_returned_not_treated_as_missing(self):
        assert resolve_path({"a": 0}, "a") == 0
        assert resolve_path({"a": False}, "a") is False
        assert resolve_path({"a": ""}, "a") == ""


class TestOperators:
    @pytest.mark.parametrize(
        ("op", "value", "expected"),
        [
            ("eq", "Next", True),
            ("eq", "Back", False),
            ("neq", "Back", True),
            ("in", ["Next", "Prev"], True),
            ("in", ["Prev"], False),
            ("not_in", ["Prev"], True),
            ("contains", "ex", True),
            ("not_contains", "zz", True),
            ("startswith", "Ne", True),
            ("endswith", "xt", True),
            ("matches", "^N.xt$", True),
            ("matches", "^zzz$", False),
            ("exists", None, True),
        ],
    )
    def test_string_operators(self, op, value, expected):
        e = engine_with([rule("r", "allow", {"field": "action.label", "op": op, "value": value})])
        assert (e.evaluate(ctx()).effect == Effect.ALLOW) is expected

    @pytest.mark.parametrize(
        ("op", "value", "expected"),
        [("gt", 50, True), ("gt", 100, False), ("gte", 100, True), ("lt", 200, True), ("lte", 99, False)],
    )
    def test_numeric_operators(self, op, value, expected):
        e = engine_with(
            [rule("r", "allow", {"field": "action.amount_usd", "op": op, "value": value})]
        )
        assert (e.evaluate(ctx()).effect == Effect.ALLOW) is expected

    def test_numeric_operator_coerces_numeric_strings(self):
        e = engine_with([rule("r", "allow", {"field": "action.amount_usd", "op": "gt", "value": 50})])
        result = e.evaluate(ctx(action={"type": "click", "amount_usd": "750.50"}))
        assert result.effect is Effect.ALLOW

    def test_numeric_operator_on_non_numeric_warns_and_does_not_match(self):
        e = engine_with([rule("r", "allow", {"field": "action.label", "op": "gt", "value": 50})])
        result = e.evaluate(ctx())
        assert result.used_default is True
        assert any("numeric operands" in w for w in result.warnings)

    def test_not_exists_matches_absent_field(self):
        e = engine_with([rule("r", "allow", {"field": "action.nope", "op": "not_exists"})])
        assert e.evaluate(ctx()).effect is Effect.ALLOW

    def test_missing_field_never_matches_a_value_operator(self):
        e = engine_with([rule("r", "allow", {"field": "action.nope", "op": "eq", "value": None})])
        assert e.evaluate(ctx()).used_default is True

    def test_case_insensitive_comparison(self):
        cond = {"field": "action.label", "op": "eq", "value": "next", "case_sensitive": False}
        assert engine_with([rule("r", "allow", cond)]).evaluate(ctx()).effect is Effect.ALLOW

    def test_contains_on_list_field(self):
        e = engine_with([rule("r", "allow", {"field": "action.tags", "op": "contains", "value": "x"})])
        result = e.evaluate(ctx(action={"type": "click", "tags": ["x", "y"]}))
        assert result.effect is Effect.ALLOW

    def test_invalid_regex_warns_instead_of_raising(self):
        e = engine_with([rule("r", "deny", {"field": "action.label", "op": "matches", "value": "("})])
        result = e.evaluate(ctx())
        assert result.used_default is True
        assert any("invalid regex" in w for w in result.warnings)

    def test_in_operator_with_non_list_value_warns(self):
        e = engine_with([rule("r", "allow", {"field": "action.label", "op": "in", "value": "Next"})])
        result = e.evaluate(ctx())
        assert result.used_default is True
        assert any("needs a list" in w for w in result.warnings)


class TestCombinators:
    def test_all_requires_every_child(self):
        cond = {
            "all": [
                {"field": "action.type", "op": "eq", "value": "click"},
                {"field": "action.label", "op": "eq", "value": "Next"},
            ]
        }
        assert engine_with([rule("r", "allow", cond)]).evaluate(ctx()).effect is Effect.ALLOW

    def test_all_fails_when_one_child_fails(self):
        cond = {
            "all": [
                {"field": "action.type", "op": "eq", "value": "click"},
                {"field": "action.label", "op": "eq", "value": "Nope"},
            ]
        }
        assert engine_with([rule("r", "allow", cond)]).evaluate(ctx()).used_default is True

    def test_any_needs_one_child(self):
        cond = {
            "any": [
                {"field": "action.type", "op": "eq", "value": "wrong"},
                {"field": "action.label", "op": "eq", "value": "Next"},
            ]
        }
        assert engine_with([rule("r", "allow", cond)]).evaluate(ctx()).effect is Effect.ALLOW

    def test_none_inverts_the_group(self):
        cond = {"none": [{"field": "action.type", "op": "eq", "value": "submit"}]}
        assert engine_with([rule("r", "allow", cond)]).evaluate(ctx()).effect is Effect.ALLOW

    def test_nested_groups(self):
        cond = {
            "all": [
                {"field": "action.type", "op": "eq", "value": "click"},
                {
                    "any": [
                        {"field": "action.label", "op": "eq", "value": "Nope"},
                        {"none": [{"field": "action.amount_usd", "op": "gt", "value": 1000}]},
                    ]
                },
            ]
        }
        assert engine_with([rule("r", "allow", cond)]).evaluate(ctx()).effect is Effect.ALLOW

    def test_rule_without_when_always_matches(self):
        e = engine_with([{"id": "catch-all", "effect": "deny"}])
        assert e.evaluate(ctx()).effect is Effect.DENY


class TestPreauthorized:
    """The operator-directed bypass used for a run's starting URL."""

    def test_is_always_allow(self):
        result = PolicyEngine.preauthorized("operator chose this")
        assert result.effect is Effect.ALLOW

    def test_carries_the_given_reason(self):
        result = PolicyEngine.preauthorized("operator chose this")
        assert result.reason == "operator chose this"

    def test_is_not_reported_as_a_default_fallback(self):
        """Must read as a deliberate decision in the audit trail, not 'no rule matched'."""
        assert PolicyEngine.preauthorized("x").used_default is False

    def test_carries_no_matched_rules(self):
        assert PolicyEngine.preauthorized("x").matches == []


class TestResolution:
    def test_no_match_uses_default_effect(self):
        e = engine_with([rule("r", "allow", {"field": "action.type", "op": "eq", "value": "zzz"})])
        result = e.evaluate(ctx())
        assert result.effect is Effect.REQUIRE_APPROVAL
        assert result.used_default is True
        assert result.matches == []

    def test_higher_priority_wins_over_lower(self):
        always = {"field": "action.type", "op": "eq", "value": "click"}
        e = engine_with(
            [
                rule("broad-deny", "deny", always, priority=10),
                rule("narrow-allow", "allow", always, priority=50),
            ]
        )
        result = e.evaluate(ctx())
        assert result.effect is Effect.ALLOW
        assert result.deciding_rule_id == "narrow-allow"

    def test_equal_priority_resolves_to_most_restrictive(self):
        always = {"field": "action.type", "op": "eq", "value": "click"}
        e = engine_with(
            [
                rule("a", "allow", always, priority=10),
                rule("b", "require_approval", always, priority=10),
                rule("c", "deny", always, priority=10),
            ]
        )
        result = e.evaluate(ctx())
        assert result.effect is Effect.DENY
        assert result.deciding_rule_id == "c"

    def test_all_matching_rules_are_recorded_for_audit(self):
        always = {"field": "action.type", "op": "eq", "value": "click"}
        e = engine_with(
            [rule("a", "allow", always, priority=1), rule("b", "deny", always, priority=99)]
        )
        result = e.evaluate(ctx())
        assert [m.rule_id for m in result.matches] == ["b", "a"]

    def test_disabled_rules_are_skipped(self):
        always = {"field": "action.type", "op": "eq", "value": "click"}
        e = engine_with([rule("off", "deny", always, priority=99, enabled=False)])
        assert e.evaluate(ctx()).used_default is True

    def test_risk_score_is_the_max_across_matches(self):
        always = {"field": "action.type", "op": "eq", "value": "click"}
        e = engine_with(
            [rule("a", "allow", always, priority=9, risk=20), rule("b", "allow", always, risk=75)]
        )
        assert e.evaluate(ctx()).risk_score == 75

    def test_reason_falls_back_to_description_then_rule_id(self):
        always = {"field": "action.type", "op": "eq", "value": "click"}
        described = engine_with([rule("a", "allow", always, description="Because reasons")])
        assert described.evaluate(ctx()).reason == "Because reasons"
        bare = engine_with([rule("b", "allow", always)])
        assert "b" in bare.evaluate(ctx()).reason


class TestSpecValidation:
    def test_duplicate_rule_ids_rejected(self):
        with pytest.raises(ValidationError):
            PolicySpec(name="x", rules=[{"id": "a", "effect": "allow"}, {"id": "a", "effect": "deny"}])

    def test_condition_cannot_be_leaf_and_group(self):
        with pytest.raises(ValidationError):
            PolicySpec(
                name="x",
                rules=[
                    {
                        "id": "a",
                        "effect": "allow",
                        "when": {"field": "a", "op": "eq", "value": 1, "all": []},
                    }
                ],
            )

    def test_condition_needs_a_form(self):
        with pytest.raises(ValidationError):
            PolicySpec(name="x", rules=[{"id": "a", "effect": "allow", "when": {"op": "eq"}}])

    def test_empty_group_rejected(self):
        with pytest.raises(ValidationError):
            PolicySpec(name="x", rules=[{"id": "a", "effect": "allow", "when": {"all": []}}])

    def test_only_one_combinator_per_condition(self):
        with pytest.raises(ValidationError):
            PolicySpec(
                name="x",
                rules=[
                    {
                        "id": "a",
                        "effect": "allow",
                        "when": {
                            "all": [{"field": "a", "op": "exists"}],
                            "any": [{"field": "b", "op": "exists"}],
                        },
                    }
                ],
            )


class TestContextBuilder:
    def test_extracts_domain_from_target_url(self):
        c = build_context(action_type="navigate", action_params={"url": "https://Vendor.EXAMPLE.com/x"})
        assert c["action"]["domain"] == "vendor.example.com"

    def test_amount_only_present_when_supplied(self):
        assert "amount_usd" not in build_context(action_type="click", action_params={})["action"]
        withamt = build_context(action_type="buy", action_params={"amount_usd": 12})
        assert withamt["action"]["amount_usd"] == 12

    def test_page_domain_is_derived(self):
        c = build_context(action_type="click", action_params={}, page_url="https://shop.test/checkout")
        assert c["page"]["domain"] == "shop.test"

    def test_missing_url_yields_empty_domain(self):
        assert build_context(action_type="click", action_params={})["action"]["domain"] == ""
