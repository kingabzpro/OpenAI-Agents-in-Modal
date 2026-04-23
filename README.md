# OpenAI Agents in Modal

Small demo showing how to run an OpenAI Agents SDK `SandboxAgent` inside a Modal sandbox.

The project includes:

- `main.py`: a minimal command-line sandbox run.
- `app.py`: a clean Gradio chat UI for asking the agent to inspect files, create files, edit code, and run tests in a reusable sandbox.
- `requirements.txt`: pinned Python dependencies.

## Setup

```bash
pip install -r requirements.txt
```

Make sure your OpenAI and Modal credentials are configured before running the examples.

## Run the CLI Demo

```bash
python main.py
```

## Run the Web App

```bash
python app.py
```

Open the local Gradio URL, usually `http://127.0.0.1:7860`.
