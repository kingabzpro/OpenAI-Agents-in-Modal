# OpenAI Agents in Modal

Run an OpenAI Agents SDK `SandboxAgent` inside a [Modal](https://modal.com) sandbox, with both a CLI demo and a Gradio chat UI.

The agent operates on a preloaded workspace (a small "Support Ticket Triage" service) and can inspect files, create or edit code, and run tests, all inside an isolated Modal container.

## How it works

```
User prompt
    │
    ▼
SandboxAgent (openai-agents SDK)
    │  instructs via tool calls
    ▼
ModalSandboxClient  ──►  Modal sandbox (ephemeral container)
                              ├── README.md
                              ├── src/app.py
                              ├── tests/test_app.py
                              └── docs/release-checks.md
```

The web app (`app.py`) keeps a **reusable sandbox** across requests, it fingerprints the workspace manifest and only recreates the container when the files change. If a sandbox becomes stale, it automatically retries with a fresh one.

## Prerequisites

- Python 3.11+
- [OpenAI API key](https://platform.openai.com/api-keys) — set as `OPENAI_API_KEY`
- [Modal account](https://modal.com) and token — run `modal token new` after installing Modal

## Setup

```bash
pip install -r requirements.txt
modal token new        # one-time authentication
```

## Run the CLI demo

Starts a single sandbox, runs one agent query against the preloaded workspace, prints the result, then tears down the sandbox.

```bash
python main.py
```

**Sample output:**

```
This service routes customer support tickets to the right team based on urgency:
enterprise customers and tickets mentioning "outage" go to support-ops with high
priority; everything else routes to customer-care at normal priority. One pre-release
check: run the ticket routing tests to confirm the routing logic matches the current
escalation policy.
```

## Run the web app

```bash
python app.py
```

Open [http://127.0.0.1:7860](http://127.0.0.1:7860) in your browser.

<img width="1332" height="841" alt="image" src="https://github.com/user-attachments/assets/4b521b92-8764-488d-92b8-0ff2a96d0f14" />


The chat interface lets you talk to the agent across multiple turns. The sandbox is reused between messages so file edits persist within a session. Clearing the chat resets the sandbox.

**Example prompts to try:**

- `Check the project files and explain what this service does.`
- `Create a new helper file for routing rules and add tests for it.`
- `Run the tests and tell me what needs to be fixed before release.`

You can also adjust the model and system instructions via the **Agent instructions** accordion.

## Project structure

| File | Description |
|------|-------------|
| `main.py` | Minimal CLI demo — single run, single sandbox |
| `app.py` | Gradio chat UI with reusable sandbox and retry logic |
| `requirements.txt` | Pinned Python dependencies |


