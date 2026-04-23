import asyncio
import atexit
import hashlib
import json
import os
import time
from typing import Any

import gradio as gr
from agents import ModelSettings, Runner
from agents.extensions.sandbox import ModalSandboxClient, ModalSandboxClientOptions
from agents.run import RunConfig
from agents.sandbox import Manifest, SandboxAgent, SandboxRunConfig
from agents.sandbox.entries import File
from agents.sandbox.errors import WorkspaceStartError


DEFAULT_README = """# Support Ticket Triage

Small service that labels customer tickets by urgency and team.
"""

DEFAULT_APP = '''def route_ticket(subject: str, customer_tier: str) -> dict:
    urgent = customer_tier == "enterprise" or "outage" in subject.lower()
    return {
        "priority": "high" if urgent else "normal",
        "team": "support-ops" if urgent else "customer-care",
    }
'''

DEFAULT_TESTS = '''from src.app import route_ticket


def test_enterprise_tickets_are_high_priority():
    assert route_ticket("Question about billing", "enterprise")["priority"] == "high"


def test_outages_route_to_support_ops():
    result = route_ticket("Checkout outage in EU", "growth")
    assert result == {"priority": "high", "team": "support-ops"}


def test_standard_tickets_route_to_customer_care():
    result = route_ticket("How do I export reports?", "starter")
    assert result == {"priority": "normal", "team": "customer-care"}
'''

DEFAULT_RELEASE_CHECKS = """# Release Checks

- Confirm routing rules match the current support escalation policy.
- Run the ticket routing tests before deployment.
- Review the fallback behavior for unknown customer tiers.
"""

DEFAULT_INSTRUCTIONS = (
    "You are a coding assistant working inside a Modal sandbox. "
    "Always inspect the workspace before answering. "
    "You can read project files, create or edit files, and run tests when the user asks. "
    "Keep answers practical and mention changed files or commands run."
)

DEFAULT_MODEL = "gpt-5.4-mini"
DEFAULT_APP_NAME = "openai-agents-modal-demo"
WORKSPACE_PERSISTENCE = "tar"
SANDBOX_TIMEOUT_SECONDS = 300


def build_manifest() -> Manifest:
    return Manifest(
        entries={
            "README.md": File(content=DEFAULT_README.encode("utf-8")),
            "src/app.py": File(content=DEFAULT_APP.encode("utf-8")),
            "tests/test_app.py": File(content=DEFAULT_TESTS.encode("utf-8")),
            "docs/release-checks.md": File(
                content=DEFAULT_RELEASE_CHECKS.encode("utf-8")
            ),
        }
    )


def fingerprint_manifest(manifest: Manifest) -> str:
    payload: dict[str, Any] = {
        "app_name": DEFAULT_APP_NAME,
        "workspace_persistence": WORKSPACE_PERSISTENCE,
        "timeout": SANDBOX_TIMEOUT_SECONDS,
        "entries": {},
    }
    for path, entry in sorted(manifest.entries.items(), key=lambda item: str(item[0])):
        content = getattr(entry, "content", b"")
        payload["entries"][str(path)] = content.decode("utf-8", errors="replace")

    encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:12]


def build_agent(manifest: Manifest, model: str, instructions: str) -> SandboxAgent:
    return SandboxAgent(
        name="Modal Sandbox Chat Assistant",
        model=model.strip(),
        instructions=instructions.strip(),
        default_manifest=manifest,
        model_settings=ModelSettings(tool_choice="required"),
    )


def build_options() -> ModalSandboxClientOptions:
    return ModalSandboxClientOptions(
        app_name=DEFAULT_APP_NAME,
        workspace_persistence=WORKSPACE_PERSISTENCE,
        timeout=SANDBOX_TIMEOUT_SECONDS,
    )


def format_history(history: Any) -> str:
    if not history:
        return ""

    lines: list[str] = []
    for item in history[-8:]:
        if isinstance(item, dict):
            role = item.get("role", "message")
            content = item.get("content", "")
            lines.append(f"{role}: {content}")
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            lines.append(f"user: {item[0]}")
            lines.append(f"assistant: {item[1]}")
    return "\n".join(lines)


class ReusableSandbox:
    def __init__(self) -> None:
        self._client = ModalSandboxClient()
        self._sandbox: Any | None = None
        self._fingerprint: str | None = None
        self._lock = asyncio.Lock()

    async def session(
        self,
        manifest: Manifest,
        options: ModalSandboxClientOptions,
        fingerprint: str,
    ) -> tuple[Any, bool]:
        async with self._lock:
            if self._sandbox is not None and self._fingerprint == fingerprint:
                return self._sandbox, True

            await self.close_locked()
            sandbox = await self._client.create(manifest=manifest, options=options)
            try:
                await sandbox.start()
            except Exception:
                try:
                    await sandbox.aclose()
                finally:
                    await self._client.delete(sandbox)
                raise

            self._sandbox = sandbox
            self._fingerprint = fingerprint
            return self._sandbox, False

    async def close(self) -> None:
        async with self._lock:
            await self.close_locked()

    async def close_locked(self) -> None:
        if self._sandbox is None:
            return

        sandbox = self._sandbox
        self._sandbox = None
        self._fingerprint = None

        try:
            await sandbox.aclose()
        finally:
            await self._client.delete(sandbox)


SANDBOX_CACHE = ReusableSandbox()


async def run_agent_once(
    agent: SandboxAgent,
    task: str,
    manifest: Manifest,
    options: ModalSandboxClientOptions,
    fingerprint: str,
) -> tuple[str, bool]:
    sandbox, reused = await SANDBOX_CACHE.session(manifest, options, fingerprint)
    result = await Runner.run(
        agent,
        task,
        run_config=RunConfig(
            sandbox=SandboxRunConfig(session=sandbox),
            workflow_name="Modal sandbox chat app",
        ),
    )
    return str(result.final_output), reused


async def chat_with_agent(
    message: str,
    history: Any,
    instructions: str,
    model: str,
) -> str:
    started = time.monotonic()
    if not message.strip():
        return "Send a request for the sandbox agent."
    if not model.strip():
        return "Set a model before running the agent."

    manifest = build_manifest()
    fingerprint = fingerprint_manifest(manifest)
    agent = build_agent(manifest=manifest, model=model, instructions=instructions)
    options = build_options()

    previous = format_history(history)
    task = message.strip()
    if previous:
        task = (
            "Recent chat context:\n"
            f"{previous}\n\n"
            "Current user request:\n"
            f"{task}"
        )

    try:
        output, reused = await run_agent_once(
            agent=agent,
            task=task,
            manifest=manifest,
            options=options,
            fingerprint=fingerprint,
        )
        elapsed = round(time.monotonic() - started, 2)
        sandbox_state = "reused" if reused else "created"
        return f"{output}\n\n`Sandbox {sandbox_state} in {elapsed}s.`"
    except WorkspaceStartError:
        await SANDBOX_CACHE.close()

        try:
            output, _ = await run_agent_once(
                agent=agent,
                task=task,
                manifest=manifest,
                options=options,
                fingerprint=fingerprint,
            )
            elapsed = round(time.monotonic() - started, 2)
            return f"{output}\n\n`Sandbox recovered and recreated in {elapsed}s.`"
        except Exception as exc:
            elapsed = round(time.monotonic() - started, 2)
            return (
                f"Sandbox run failed after retry in {elapsed}s: "
                f"`{type(exc).__name__}: {exc}`"
            )
    except Exception as exc:
        elapsed = round(time.monotonic() - started, 2)
        return f"Sandbox run failed after {elapsed}s: `{type(exc).__name__}: {exc}`"


async def reset_cached_sandbox() -> None:
    try:
        await SANDBOX_CACHE.close()
    except Exception as exc:
        print(f"Reset failed: {type(exc).__name__}: {exc}")


async def respond(
    message: str,
    history: list[dict[str, str]] | None,
    instructions: str,
    model: str,
) -> tuple[str, list[dict[str, str]]]:
    history = history or []
    if not message.strip():
        return "", history

    reply = await chat_with_agent(
        message=message,
        history=history,
        instructions=instructions,
        model=model,
    )
    return "", [
        *history,
        {"role": "user", "content": message},
        {"role": "assistant", "content": reply},
    ]


def build_app() -> gr.Blocks:
    with gr.Blocks(
        title="Modal Sandbox Chat",
        fill_height=True,
        fill_width=True,
    ) as demo:
        gr.Markdown("# Modal Sandbox Chat")
        gr.Markdown(
            "Ask the agent to inspect the sandbox project, create or edit files, "
            "and run tests inside Modal."
        )

        with gr.Accordion("Agent instructions", open=False):
            instructions = gr.Textbox(
                label="Instructions",
                value=DEFAULT_INSTRUCTIONS,
                lines=3,
            )
            model = gr.Textbox(label="Model", value=DEFAULT_MODEL)

        chatbot = gr.Chatbot(
            label="Conversation",
            height=340,
            buttons=["copy", "copy_all"],
        )

        with gr.Row(equal_height=True):
            message = gr.Textbox(
                label="Message",
                placeholder="Ask it to check files, create files, or run tests...",
                lines=2,
                max_lines=6,
                scale=1,
                min_width=240,
                show_label=False,
            )

            with gr.Column(scale=0, min_width=70):
                with gr.Row(equal_height=True):
                    send_button = gr.Button(
                        "➜",
                        variant="primary",
                        scale=0,
                        min_width=58,
                    )

        gr.Examples(
            examples=[
                "Check the project files and explain what this service does.",
                "Create a new helper file for routing rules and add tests for it.",
                "Run the tests and tell me what needs to be fixed before release.",
            ],
            inputs=message,
            label="Examples",
            run_on_click=False,
        )

        chat_inputs = [message, chatbot, instructions, model]
        chat_outputs = [message, chatbot]
        message.submit(
            respond,
            inputs=chat_inputs,
            outputs=chat_outputs,
            concurrency_limit=1,
            concurrency_id="modal-sandbox",
            api_name="chat_submit",
        )
        send_button.click(
            respond,
            inputs=chat_inputs,
            outputs=chat_outputs,
            concurrency_limit=1,
            concurrency_id="modal-sandbox",
            api_name="chat",
        )
        chatbot.clear(
            reset_cached_sandbox,
            inputs=None,
            outputs=None,
            concurrency_limit=1,
            concurrency_id="modal-sandbox",
            api_name="reset_sandbox",
        )

    demo.queue(max_size=20, default_concurrency_limit=1)
    return demo


def shutdown_cached_sandbox() -> None:
    try:
        asyncio.run(SANDBOX_CACHE.close())
    except RuntimeError:
        pass


atexit.register(shutdown_cached_sandbox)


if __name__ == "__main__":
    server_name = os.getenv("GRADIO_SERVER_NAME", "127.0.0.1")
    server_port = int(os.getenv("GRADIO_SERVER_PORT", "7860"))
    build_app().launch(
        server_name=server_name,
        server_port=server_port,
        show_error=True,
        theme=gr.themes.Ocean(),
    )
