import pytest

from app.enums import Effect
from app.policy import PolicyEngine, build_context, load_default_policy


@pytest.fixture(scope="module")
def engine() -> PolicyEngine:
    return PolicyEngine(load_default_policy())


def decide(engine, action_type, params=None, page_url="", session=None):
    return engine.evaluate(
        build_context(
            action_type=action_type,
            action_params=params or {},
            page_url=page_url,
            session=session or {},
        )
    )


class TestReadOnlyWorkRunsUnattended:
    @pytest.mark.parametrize("action", ["read_page", "scroll", "wait", "observe"])
    def test_observation_is_allowed(self, engine, action):
        assert decide(engine, action).effect is Effect.ALLOW

    def test_allowlisted_navigation_is_allowed(self, engine):
        result = decide(engine, "navigate", {"url": "https://vendor-portal.example.com/orders"})
        assert result.effect is Effect.ALLOW
        assert result.deciding_rule_id == "allow-navigation-within-allowlist"

    def test_ordinary_click_is_allowed(self, engine):
        assert decide(engine, "click", {"label": "View orders"}).effect is Effect.ALLOW

    def test_ordinary_typing_is_allowed(self, engine):
        params = {"label": "Search", "text": "widgets", "is_sensitive": False}
        assert decide(engine, "type", params).effect is Effect.ALLOW


class TestHumanApprovalGate:
    def test_off_allowlist_navigation_needs_approval(self, engine):
        result = decide(engine, "navigate", {"url": "https://unknown-supplier.io/login"})
        assert result.effect is Effect.REQUIRE_APPROVAL
        assert result.deciding_rule_id == "approve-navigation-off-allowlist"

    def test_form_submission_needs_approval(self, engine):
        assert decide(engine, "submit", {"label": "Book meeting"}).effect is Effect.REQUIRE_APPROVAL

    def test_outbound_message_needs_approval(self, engine):
        result = decide(engine, "click", {"label": "Send invite"})
        assert result.effect is Effect.REQUIRE_APPROVAL
        assert result.deciding_rule_id == "approve-outbound-message"

    def test_spend_above_threshold_needs_approval(self, engine):
        result = decide(engine, "purchase", {"label": "Confirm order", "amount_usd": 750})
        assert result.effect is Effect.REQUIRE_APPROVAL
        assert result.risk_score >= 70

    def test_spend_below_threshold_does_not_trip_the_finance_rule(self, engine):
        result = decide(engine, "purchase", {"label": "Confirm order", "amount_usd": 100})
        assert "approve-spend-over-threshold" not in [m.rule_id for m in result.matches]

    def test_checkout_page_interaction_needs_approval(self, engine):
        result = decide(engine, "click", {"label": "Continue"}, page_url="https://shop.test/checkout")
        assert result.effect is Effect.REQUIRE_APPROVAL

    def test_download_needs_approval(self, engine):
        assert decide(engine, "download", {"label": "invoice.pdf"}).effect is Effect.REQUIRE_APPROVAL


class TestHardDenials:
    def test_credential_entry_is_denied(self, engine):
        result = decide(engine, "type", {"label": "Password", "is_sensitive": True})
        assert result.effect is Effect.DENY
        assert result.deciding_rule_id == "deny-credential-entry"

    def test_credential_field_denied_by_label_even_if_flag_missing(self, engine):
        result = decide(engine, "type", {"label": "Card Number", "is_sensitive": False})
        assert result.effect is Effect.DENY

    def test_destructive_action_is_denied(self, engine):
        assert decide(engine, "click", {"label": "Delete account"}).effect is Effect.DENY

    def test_spend_above_hard_cap_is_denied_not_merely_gated(self, engine):
        result = decide(engine, "purchase", {"label": "Confirm", "amount_usd": 9000})
        assert result.effect is Effect.DENY
        assert result.deciding_rule_id == "deny-spend-over-hard-cap"

    def test_exhausted_budget_denies_further_work(self, engine):
        result = decide(engine, "read_page", session={"budget_exhausted": True})
        assert result.effect is Effect.DENY


class TestPostureGuarantees:
    def test_unknown_action_falls_back_to_approval_not_allow(self, engine):
        result = decide(engine, "transfer_funds", {"label": "wire"})
        assert result.effect is Effect.REQUIRE_APPROVAL
        assert result.used_default is True

    def test_shipped_policy_produces_no_authoring_warnings(self, engine):
        scenarios = [
            ("read_page", {}, ""),
            ("navigate", {"url": "https://example.com"}, ""),
            ("click", {"label": "Next"}, "https://example.com"),
            ("type", {"label": "Name", "text": "Ada", "is_sensitive": False}, ""),
            ("submit", {"label": "Save"}, ""),
            ("purchase", {"label": "Buy", "amount_usd": 42}, ""),
        ]
        for action_type, params, page_url in scenarios:
            result = decide(engine, action_type, params, page_url)
            assert result.warnings == [], f"{action_type} produced {result.warnings}"

    def test_every_shipped_rule_has_a_human_readable_reason(self, engine):
        for rule in engine.spec.rules:
            assert rule.resolved_reason().strip()
