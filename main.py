import asyncio

from agents import ModelSettings, Runner
from agents.extensions.sandbox import ModalSandboxClient, ModalSandboxClientOptions
from agents.run import RunConfig
from agents.sandbox import Manifest, SandboxAgent, SandboxRunConfig
from agents.sandbox.entries import File


async def main():
    manifest = Manifest(
        entries={
            "README.md": File(
                content=(
                    b"# Support Ticket Triage\n\n"
                    b"Small service that labels customer tickets by urgency and team.\n"
                )
            ),
            "src/app.py": File(
                content=(
                    b"def route_ticket(subject: str, customer_tier: str) -> dict:\n"
                    b"    urgent = customer_tier == \"enterprise\" or \"outage\" in subject.lower()\n"
                    b"    return {\n"
                    b"        \"priority\": \"high\" if urgent else \"normal\",\n"
                    b"        \"team\": \"support-ops\" if urgent else \"customer-care\",\n"
                    b"    }\n"
                )
            ),
            "docs/release-checks.md": File(
                content=(
                    b"# Release Checks\n\n"
                    b"- Confirm routing rules match the current support escalation policy.\n"
                )
            ),
        }
    )

    agent = SandboxAgent(
        name="Modal Sandbox Assistant",
        model="gpt-5.4-mini",
        instructions=(
            "You are a coding assistant reviewing a small production service. "
            "Inspect the sandbox workspace before answering. "
            "Keep the answer short and practical."
        ),
        default_manifest=manifest,
        model_settings=ModelSettings(tool_choice="required"),
    )

    client = ModalSandboxClient()
    options = ModalSandboxClientOptions(
        app_name="openai-agents-modal-demo",
        workspace_persistence="tar",
    )

    sandbox = await client.create(
        manifest=manifest,
        options=options,
    )

    await sandbox.start()

    try:
        result = await Runner.run(
            agent,
            (
                "Explain what this service does and name one production check "
                "before release. Keep it under 3 sentences."
            ),
            run_config=RunConfig(
                sandbox=SandboxRunConfig(session=sandbox),
                workflow_name="Modal sandbox example",
            ),
        )

        print(result.final_output)

    finally:
        try:
            await sandbox.aclose()
        finally:
            await client.delete(sandbox)


if __name__ == "__main__":
    asyncio.run(main())
