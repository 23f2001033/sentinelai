import pytest

from app.operator.actions import (
    ACTION_SPECS,
    ActionValidationError,
    action_catalogue,
    is_sensitive_label,
    validate_action,
)


class TestValidation:
    def test_unknown_action_rejected(self):
        with pytest.raises(ActionValidationError):
            validate_action("hack_the_mainframe", {})

    def test_missing_required_param_rejected(self):
        with pytest.raises(ActionValidationError):
            validate_action("click", {})

    def test_blank_required_param_rejected(self):
        with pytest.raises(ActionValidationError):
            validate_action("navigate", {"url": "   "})

    def test_optional_params_are_not_required(self):
        assert validate_action("scroll", {}) == {"is_sensitive": False}

    def test_bare_host_is_normalised_to_https(self):
        assert validate_action("navigate", {"url": "example.com"})["url"] == "https://example.com"

    def test_existing_scheme_is_preserved(self):
        assert validate_action("navigate", {"url": "http://x.test"})["url"] == "http://x.test"

    @pytest.mark.parametrize(
        "url",
        [
            "file:///etc/passwd",
            "file://C:/Windows/win.ini",
            "javascript:alert(1)",
            "data:text/html,<script>alert(1)</script>",
            "chrome://settings",
        ],
    )
    def test_non_http_schemes_are_rejected(self, url):
        """file:// would let the agent read local files; data:/javascript: bypass the action surface."""
        with pytest.raises(ActionValidationError):
            validate_action("navigate", {"url": url})

    def test_download_is_scheme_checked_too(self):
        with pytest.raises(ActionValidationError):
            validate_action("download", {"url": "file:///etc/shadow"})

    def test_catalogue_lists_every_action(self):
        catalogue = action_catalogue()
        assert all(name in catalogue for name in ACTION_SPECS)


class TestSensitivity:
    def test_sensitivity_is_re_derived_not_trusted(self):
        """A planner claiming a credential field is safe must not be believed."""
        params = validate_action(
            "type", {"ref": "e1", "label": "CVV", "text": "123", "is_sensitive": False}
        )
        assert params["is_sensitive"] is True

    def test_explicit_flag_is_still_honoured(self):
        params = validate_action(
            "type", {"ref": "e1", "label": "Notes", "text": "x", "is_sensitive": True}
        )
        assert params["is_sensitive"] is True

    def test_non_field_actions_default_to_not_sensitive(self):
        assert validate_action("click", {"ref": "e1"})["is_sensitive"] is False

    @pytest.mark.parametrize(
        "label",
        [
            "Password",
            "card number",
            "CVV",
            "CVC",
            "API Key",
            "api_key",
            "Social Security",
            "secret token",
            "Routing number",
            "IBAN",
            "Security Code",
        ],
    )
    def test_sensitive_labels_detected(self, label):
        assert is_sensitive_label(label)

    @pytest.mark.parametrize(
        "label", ["Your name", "Agenda", "Quantity", "Preferred date", "Work email", "Part or SKU"]
    )
    def test_ordinary_labels_not_flagged(self, label):
        assert not is_sensitive_label(label)

    def test_any_candidate_can_trigger_the_flag(self):
        assert is_sensitive_label(None, "", "cc-number-ish password")

    def test_no_candidates_is_not_sensitive(self):
        assert not is_sensitive_label(None, "")
