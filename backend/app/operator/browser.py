from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from .actions import is_sensitive_label

COLLECT_ELEMENTS_JS = """
() => {
  const SELECTOR = [
    'a[href]', 'button', 'input', 'select', 'textarea',
    '[role="button"]', '[role="link"]', '[role="textbox"]', '[contenteditable="true"]'
  ].join(',');

  document.querySelectorAll('[data-sentinel-ref]').forEach(el => el.removeAttribute('data-sentinel-ref'));

  const elements = [];
  let seq = 0;
  for (const el of document.querySelectorAll(SELECTOR)) {
    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    const hidden = style.display === 'none' || style.visibility === 'hidden'
      || style.opacity === '0' || (rect.width === 0 && rect.height === 0);
    if (hidden) continue;

    const ref = 'e' + (++seq);
    el.setAttribute('data-sentinel-ref', ref);

    // Form controls are named by their <label>; everything else by its own text.
    // Getting this right matters: policy rules match on these labels.
    const isField = ['input', 'select', 'textarea'].includes(el.tagName.toLowerCase());
    const labelText = () => {
      if (el.id) {
        const lab = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
        if (lab) return (lab.innerText || '').trim();
      }
      const parentLabel = el.closest('label');
      return parentLabel ? (parentLabel.innerText || '').trim() : '';
    };

    const candidates = isField
      ? [el.getAttribute('aria-label'), labelText(), el.getAttribute('placeholder'),
         el.getAttribute('title'), el.getAttribute('name')]
      : [el.getAttribute('aria-label'), (el.innerText || '').trim(),
         el.getAttribute('title'), el.getAttribute('name'), labelText()];

    let name = (candidates.find(c => c && c.trim()) || '').trim();

    elements.push({
      ref,
      tag: el.tagName.toLowerCase(),
      type: (el.getAttribute('type') || '').toLowerCase(),
      role: el.getAttribute('role') || '',
      name: name.slice(0, 140),
      value: String(el.value || '').slice(0, 80),
      disabled: Boolean(el.disabled),
      autocomplete: el.getAttribute('autocomplete') || '',
      href: el.getAttribute('href') || ''
    });
    if (seq >= 60) break;
  }

  return {
    url: location.href,
    title: document.title,
    text: (document.body ? document.body.innerText : '').slice(0, 3000),
    elements
  };
}
"""


@dataclass
class PageElement:
    ref: str
    tag: str
    type: str
    role: str
    name: str
    value: str = ""
    disabled: bool = False
    is_sensitive: bool = False
    href: str = ""

    def describe(self) -> str:
        kind = self.type or self.role or self.tag
        parts = [f"[{self.ref}] {kind}", f'"{self.name}"' if self.name else "(unlabelled)"]
        if self.value:
            parts.append(f"currently={self.value!r}")
        if self.is_sensitive:
            parts.append("SENSITIVE")
        if self.disabled:
            parts.append("disabled")
        return " ".join(parts)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ref": self.ref,
            "tag": self.tag,
            "type": self.type,
            "role": self.role,
            "name": self.name,
            "value": self.value,
            "disabled": self.disabled,
            "is_sensitive": self.is_sensitive,
        }


@dataclass
class PageObservation:
    url: str = ""
    title: str = ""
    text: str = ""
    elements: list[PageElement] = field(default_factory=list)

    def element(self, ref: str) -> PageElement | None:
        return next((e for e in self.elements if e.ref == ref), None)

    def render(self, max_elements: int = 40) -> str:
        listing = "\n".join(e.describe() for e in self.elements[:max_elements]) or "(no controls)"
        return (
            f"URL: {self.url}\nTITLE: {self.title}\n\n"
            f"VISIBLE TEXT:\n{self.text[:1500]}\n\nINTERACTIVE ELEMENTS:\n{listing}"
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "text": self.text[:1500],
            "elements": [e.as_dict() for e in self.elements],
        }


def _mark_sensitive(raw: dict[str, Any]) -> bool:
    if raw.get("type") == "password":
        return True
    autocomplete = (raw.get("autocomplete") or "").lower()
    if autocomplete.startswith("cc-") or autocomplete == "one-time-code":
        return True
    return is_sensitive_label(raw.get("name"), raw.get("autocomplete"))


class BrowserOperatorError(RuntimeError):
    pass


class BrowserOperator:
    """Drives a real Chromium page and reports what it can see.

    The operator only exposes a small, named action surface. It deliberately does not
    take free-form JavaScript from the planner, so every step the agent takes is a
    structured action the policy engine can reason about.
    """

    def __init__(
        self, headless: bool = True, timeout_ms: int = 15000, no_sandbox: bool = False
    ) -> None:
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.no_sandbox = no_sandbox
        self._playwright = None
        self._browser = None
        self._page = None

    async def start(self) -> None:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise BrowserOperatorError(
                "Playwright is not installed. Run: pip install playwright && playwright install chromium"
            ) from exc

        # --disable-dev-shm-usage avoids Chromium crashing on the small /dev/shm
        # most container runtimes provide.
        args = ["--disable-dev-shm-usage"]
        if self.no_sandbox:
            args.append("--no-sandbox")

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless, args=args
        )
        context = await self._browser.new_context(viewport={"width": 1280, "height": 800})
        self._page = await context.new_page()
        self._page.set_default_timeout(self.timeout_ms)

    async def close(self) -> None:
        for closer in (
            getattr(self._browser, "close", None),
            getattr(self._playwright, "stop", None),
        ):
            if closer is None:
                continue
            try:
                await closer()
            except Exception:  # pragma: no cover - best-effort teardown
                pass
        self._playwright = self._browser = self._page = None

    @property
    def page(self):
        if self._page is None:
            raise BrowserOperatorError("browser not started; call start() first")
        return self._page

    async def observe(self) -> PageObservation:
        raw = await self.page.evaluate(COLLECT_ELEMENTS_JS)
        elements = [
            PageElement(
                ref=item["ref"],
                tag=item["tag"],
                type=item["type"],
                role=item["role"],
                name=item["name"],
                value=item["value"],
                disabled=item["disabled"],
                is_sensitive=_mark_sensitive(item),
                href=item["href"],
            )
            for item in raw["elements"]
        ]
        return PageObservation(
            url=raw["url"], title=raw["title"], text=raw["text"], elements=elements
        )

    async def screenshot(self) -> bytes | None:
        try:
            return await self.page.screenshot(type="jpeg", quality=60)
        except Exception:  # pragma: no cover - screenshots are advisory
            return None

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        handler = getattr(self, f"_do_{action}", None)
        if handler is None:
            raise BrowserOperatorError(f"action '{action}' is not executable by the browser operator")
        return await handler(params)

    def _selector(self, ref: str) -> str:
        return f'[data-sentinel-ref="{ref}"]'

    async def _settle(self) -> None:
        try:
            await self.page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            await asyncio.sleep(0.3)

    async def _do_navigate(self, params: dict[str, Any]) -> dict[str, Any]:
        await self.page.goto(params["url"], wait_until="domcontentloaded")
        await self._settle()
        return {"navigated_to": self.page.url}

    async def _do_click(self, params: dict[str, Any]) -> dict[str, Any]:
        await self.page.click(self._selector(params["ref"]))
        await self._settle()
        return {"clicked": params.get("label") or params["ref"], "url": self.page.url}

    async def _do_type(self, params: dict[str, Any]) -> dict[str, Any]:
        await self.page.fill(self._selector(params["ref"]), str(params["text"]))
        return {"typed_into": params.get("label") or params["ref"], "characters": len(str(params["text"]))}

    async def _do_select(self, params: dict[str, Any]) -> dict[str, Any]:
        await self.page.select_option(self._selector(params["ref"]), str(params["value"]))
        return {"selected": params["value"]}

    async def _do_submit(self, params: dict[str, Any]) -> dict[str, Any]:
        await self.page.click(self._selector(params["ref"]))
        await self._settle()
        return {"submitted": params.get("label") or params["ref"], "url": self.page.url}

    async def _do_scroll(self, params: dict[str, Any]) -> dict[str, Any]:
        delta = -600 if str(params.get("direction", "down")).lower() == "up" else 600
        await self.page.mouse.wheel(0, delta)
        await asyncio.sleep(0.2)
        return {"scrolled": params.get("direction", "down")}

    async def _do_read_page(self, params: dict[str, Any]) -> dict[str, Any]:
        observation = await self.observe()
        return {"title": observation.title, "url": observation.url}

    async def _do_download(self, params: dict[str, Any]) -> dict[str, Any]:
        # The URL is recorded for the audit trail; bytes are never written to the
        # host filesystem, so an approved download cannot plant an executable.
        return {"download_recorded": params["url"], "written_to_disk": False}
