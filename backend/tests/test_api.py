import pytest


class TestBootstrap:
    def test_health_reports_planner_configuration(self, client):
        body = client.get("/api/health").json()
        assert body["status"] == "ok"
        assert "planner_configured" in body

    def test_seed_installs_baseline_policy_and_agent(self, client):
        policies = client.get("/api/policies").json()
        assert len(policies) >= 1
        assert policies[0]["rules"], "baseline policy should ship with rules"
        assert client.get("/api/agents").json()

    def test_demo_site_is_served(self, client):
        assert client.get("/demo/").status_code == 200
        assert client.get("/demo/checkout.html").status_code == 200

    def test_console_is_served_and_survives_a_deep_link(self, client):
        """A refresh on /app/runs/1 must return the SPA shell, not a 404."""
        assert client.get("/app/").status_code == 200
        deep = client.get("/app/runs/1")
        assert deep.status_code == 200
        assert "<div id=\"root\">" in deep.text

    def test_root_redirects_to_console(self, client):
        assert client.get("/", follow_redirects=False).status_code in {307, 308}

    def test_spa_route_cannot_escape_the_static_directory(self, client):
        escaped = client.get("/app/../../config.py")
        assert "get_settings" not in escaped.text


class TestPolicyApi:
    def test_create_and_version_bump_on_update(self, client):
        payload = {
            "name": "Strict Read Only",
            "description": "Nothing but reading.",
            "default_effect": "deny",
            "rules": [
                {
                    "id": "allow-read",
                    "effect": "allow",
                    "priority": 10,
                    "when": {"field": "action.type", "op": "eq", "value": "read_page"},
                }
            ],
        }
        created = client.post("/api/policies", json=payload).json()
        assert created["version"] == 1
        assert created["default_effect"] == "deny"

        payload["description"] = "Updated."
        updated = client.put(f"/api/policies/{created['id']}", json=payload).json()
        assert updated["version"] == 2

    def test_duplicate_policy_name_conflicts(self, client):
        body = {"name": "Duplicate Me", "rules": []}
        assert client.post("/api/policies", json=body).status_code == 201
        assert client.post("/api/policies", json=body).status_code == 409

    def test_rules_round_trip_through_storage(self, client):
        body = {
            "name": "Round Trip",
            "rules": [
                {
                    "id": "nested",
                    "effect": "require_approval",
                    "when": {
                        "all": [
                            {"field": "action.type", "op": "eq", "value": "click"},
                            {"any": [{"field": "action.label", "op": "contains", "value": "Pay"}]},
                        ]
                    },
                }
            ],
        }
        created = client.post("/api/policies", json=body).json()
        sim = client.post(
            f"/api/policies/{created['id']}/simulate",
            json={"action_type": "click", "action_params": {"label": "Pay now"}},
        ).json()
        assert sim["effect"] == "require_approval"

    def test_invalid_rule_is_rejected(self, client):
        bad = {"name": "Bad", "rules": [{"id": "x", "effect": "allow", "when": {"op": "eq"}}]}
        assert client.post("/api/policies", json=bad).status_code == 422

    def test_missing_policy_returns_404(self, client):
        assert client.get("/api/policies/99999").status_code == 404


class TestSimulation:
    @pytest.mark.parametrize(
        ("action_type", "params", "expected"),
        [
            ("read_page", {}, "allow"),
            ("type", {"label": "Card number", "text": "4111"}, "deny"),
            ("submit", {"label": "Send meeting request"}, "require_approval"),
            ("click", {"label": "Delete account"}, "deny"),
            ("transfer_funds", {"label": "wire"}, "require_approval"),
        ],
    )
    def test_baseline_decisions(self, client, action_type, params, expected):
        body = client.post(
            "/api/policies/1/simulate",
            json={"action_type": action_type, "action_params": params},
        ).json()
        assert body["effect"] == expected

    def test_simulation_returns_the_context_it_evaluated(self, client):
        body = client.post(
            "/api/policies/1/simulate",
            json={"action_type": "navigate", "action_params": {"url": "https://Evil.test/x"}},
        ).json()
        assert body["context"]["action"]["domain"] == "evil.test"
        assert body["deciding_rule_id"] == "approve-navigation-off-allowlist"


class TestAgentApi:
    def test_agent_requires_existing_policy(self, client):
        body = {"name": "Orphan", "policy_set_id": 99999}
        assert client.post("/api/agents", json=body).status_code == 404

    def test_duplicate_agent_name_conflicts(self, client):
        body = {"name": "Twin Agent", "policy_set_id": 1}
        assert client.post("/api/agents", json=body).status_code == 201
        assert client.post("/api/agents", json=body).status_code == 409


class TestRunApi:
    @pytest.fixture
    def run_id(self, client, monkeypatch):
        async def noop(_run_id):
            return None

        monkeypatch.setattr("app.routers.runs.start_run", noop)
        response = client.post(
            "/api/runs",
            json={"agent_id": 1, "goal": "Book a meeting with Acme", "start_url": "http://x/demo/"},
        )
        assert response.status_code == 201
        return response.json()["id"]

    def test_run_is_created_and_listed(self, client, run_id):
        assert any(r["id"] == run_id for r in client.get("/api/runs").json())

    def test_run_detail_includes_steps_collection(self, client, run_id):
        detail = client.get(f"/api/runs/{run_id}").json()
        assert detail["goal"].startswith("Book a meeting")
        assert detail["steps"] == []

    def test_cancel_marks_run_cancelled_and_audits(self, client, run_id):
        assert client.post(f"/api/runs/{run_id}/cancel").json()["status"] == "cancelled"
        kinds = [e["kind"] for e in client.get(f"/api/runs/{run_id}/audit").json()]
        assert "run_finished" in kinds

    def test_cancel_is_idempotent(self, client, run_id):
        client.post(f"/api/runs/{run_id}/cancel")
        assert client.post(f"/api/runs/{run_id}/cancel").status_code == 200

    def test_unknown_agent_rejected(self, client):
        body = {"agent_id": 99999, "goal": "do something"}
        assert client.post("/api/runs", json=body).status_code == 404

    def test_missing_run_returns_404(self, client):
        assert client.get("/api/runs/99999").status_code == 404


class TestTelemetry:
    def test_spend_summary_shape(self, client):
        body = client.get("/api/spend/summary").json()
        assert set(body) == {"total_usd", "total_input_tokens", "total_output_tokens", "calls", "by_run"}

    def test_stats_shape(self, client):
        body = client.get("/api/stats").json()
        assert "runs_by_status" in body and "pending_approvals" in body
