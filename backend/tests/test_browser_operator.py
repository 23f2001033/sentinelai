from pathlib import Path

import pytest
import pytest_asyncio

from app.enums import Effect
from app.operator import BrowserOperator, validate_action
from app.operator.actions import ActionValidationError, is_sensitive_label
from app.policy import PolicyEngine, build_context, load_default_policy

DEMO = Path(__file__).resolve().parent.parent / "app" / "static" / "demo"


def demo_url(page: str) -> str:
    return (DEMO / page).as_uri()


playwright_available = pytest.importorskip("playwright", reason="playwright not installed")


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def operator():
    op = BrowserOperator(headless=True)
    try:
        await op.start()
    except Exception as exc:  # pragma: no cover - CI without a browser binary
        pytest.skip(f"chromium unavailable: {exc}")
    yield op
    await op.close()


pytestmark = pytest.mark.asyncio(loop_scope="module")


class TestObservation:
    async def test_reads_page_identity_and_controls(self, operator):
        await operator.execute("navigate", {"url": demo_url("index.html")})
        obs = await operator.observe()
        assert "Northwind" in obs.title
        assert "Procurement dashboard" in obs.text
        assert obs.elements, "expected interactive elements on the landing page"

    async def test_every_element_gets_a_stable_ref(self, operator):
        await operator.execute("navigate", {"url": demo_url("vendors.html")})
        obs = await operator.observe()
        refs = [e.ref for e in obs.elements]
        assert len(refs) == len(set(refs))
        assert all(r.startswith("e") for r in refs)

    async def test_elements_carry_human_readable_names(self, operator):
        await operator.execute("navigate", {"url": demo_url("vendors.html")})
        obs = await operator.observe()
        names = [e.name for e in obs.elements]
        assert any("Book a meeting" in n for n in names)

    async def test_render_is_a_compact_prompt_view(self, operator):
        await operator.execute("navigate", {"url": demo_url("index.html")})
        rendered = (await operator.observe()).render()
        assert "URL:" in rendered and "INTERACTIVE ELEMENTS:" in rendered


class TestSensitivityDetection:
    async def test_payment_fields_are_flagged_sensitive(self, operator):
        await operator.execute("navigate", {"url": demo_url("checkout.html")})
        obs = await operator.observe()
        card = next(e for e in obs.elements if "card number" in e.name.lower())
        cvv = next(e for e in obs.elements if "cvv" in e.name.lower())
        assert card.is_sensitive
        assert cvv.is_sensitive

    async def test_ordinary_fields_are_not_flagged(self, operator):
        await operator.execute("navigate", {"url": demo_url("book.html")})
        obs = await operator.observe()
        name_field = next(e for e in obs.elements if e.name.lower().startswith("your name"))
        assert not name_field.is_sensitive

    async def test_sensitive_field_is_denied_by_the_shipped_policy(self, operator):
        """The operator flags the field and the policy engine refuses it — end to end."""
        await operator.execute("navigate", {"url": demo_url("checkout.html")})
        obs = await operator.observe()
        card = next(e for e in obs.elements if "card number" in e.name.lower())

        params = validate_action(
            "type", {"ref": card.ref, "label": card.name, "text": "4111111111111111",
                     "is_sensitive": card.is_sensitive}
        )
        engine = PolicyEngine(load_default_policy())
        decision = engine.evaluate(
            build_context(action_type="type", action_params=params, page_url=obs.url)
        )
        assert decision.effect is Effect.DENY
        assert decision.deciding_rule_id == "deny-credential-entry"


class TestInteraction:
    async def test_click_follows_a_link(self, operator):
        await operator.execute("navigate", {"url": demo_url("index.html")})
        obs = await operator.observe()
        link = next(e for e in obs.elements if "vendor directory" in e.name.lower())
        await operator.execute("click", {"ref": link.ref, "label": link.name})
        assert "vendors" in (await operator.observe()).url

    async def test_typing_lands_in_the_field(self, operator):
        await operator.execute("navigate", {"url": demo_url("book.html")})
        obs = await operator.observe()
        field = next(e for e in obs.elements if e.name.lower().startswith("your name"))
        await operator.execute("type", {"ref": field.ref, "text": "Ada Lovelace"})
        refreshed = (await operator.observe()).element(field.ref)
        assert refreshed is not None and refreshed.value == "Ada Lovelace"

    async def test_select_changes_the_dropdown(self, operator):
        await operator.execute("navigate", {"url": demo_url("book.html")})
        obs = await operator.observe()
        dropdown = next(e for e in obs.elements if e.tag == "select")
        await operator.execute("select", {"ref": dropdown.ref, "value": "afternoon"})
        assert (await operator.observe()).element(dropdown.ref).value == "afternoon"

    async def test_download_never_writes_to_disk(self, operator):
        result = await operator.execute("download", {"url": "https://example.com/x.pdf"})
        assert result["written_to_disk"] is False
