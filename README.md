# Nexus

An AI agent for the terminal that runs entirely on your machine: a local model, local tools, and no network access beyond a model server on loopback.

> **Status: early.** Nexus can chat and use tools: browse folders, read and write files, and run bash commands, with approval prompts and safety rules. Sessions with undo, config files, and more tools are next. See the build order in [ARCHITECTURE.md §10](ARCHITECTURE.md#10-build-order).

## Quick start

You need Python 3.11+ and a local model server with an OpenAI-compatible API, such as [Ollama](https://ollama.com).

```sh
python3 -m venv .venv
make install          # installs Nexus and the dev tools into .venv
.venv/bin/nexus       # start the interactive session
```

Useful from there:

| Do this | To |
|---|---|
| Type `/` | Open the command menu |
| Type `@` | Mention a file |
| `Shift-Tab` / `Ctrl-T` | Cycle the permission mode / thinking depth |
| `nexus --depth fast` | Skip the model's thinking for quick answers |
| `nexus -p "question"` | Ask one question without the interactive session |
| `nexus doctor` | Check that the model server is reachable and working |

## What the agent can do

| Tool | What it does | Asks first? |
|---|---|---|
| `list_dir`, `find_files`, `read_file` | Look around: browse any folder, find files by name, read text files | No |
| `write_file` | Create a file or replace one (you see a diff first) | In `ask` mode; always outside the working directory |
| `run_command` | Run a bash command (no input, no internet, secrets removed from its environment) | In `ask` mode, unless it is a read-only command like `ls` or `git status` |

Press `Shift-Tab` to change how much it asks: `read-only` (never changes anything), `ask` (the default), or `auto` (writes inside the working directory and runs commands without asking). Commands that need the internet, `sudo`, and recursive deletes of your home folder or working directory are always refused.

**Context size.** Nexus assumes the model server runs with a 16,384-token window (`--context-window`). Ollama's own default is only 4096, which tool use fills quickly, and its OpenAI-style API ignores any window size a client asks for, so the window has to be set on the server. Give your model a window with a Modelfile:

```
FROM your-model
PARAMETER num_ctx 16384
```

then `ollama create your-model -f Modelfile` (or set `OLLAMA_CONTEXT_LENGTH=16384` for the whole server). If the number Nexus assumes is too big, it corrects itself the first time a reply is cut off, and it tells you when that happens. Use `/new` to start a fresh conversation when the window is full.

## What is in the code

Only folders with working code exist. Each new part gets its folder when it is built, following the plan in [ARCHITECTURE.md](ARCHITECTURE.md).

```
src/nexus/
├── messages.py      the data every part shares: messages, tool calls, token usage
├── brain/           talks to the local model
├── cli/             everything you see in the terminal
├── loop/            the agent loop: ask the model, run its tools, repeat
├── tools/           what the model can do: five built-in tools
├── guardrails/      what the model may do: modes, command rules, approval
├── context/         keeps the conversation inside the model's window (started)
└── instructions/    what the model is told: prompt layers and environment
```

### Where to start reading

1. `cli/main.py`: reads the command-line flags and connects the parts.
2. `cli/repl.py`: the interactive loop: read input, run a command or send it to the model.
3. `brain/base.py`: the contract every model adapter follows.
4. `brain/openai_compat.py`: the adapter that streams replies from the local server.
5. `loop/agent.py`: the loop that runs tools until the model answers.

## Development

```sh
make check     # lint, format check, type check (mypy --strict), and tests
make format    # auto-format the code
```

Design, conventions, and the reasons behind them are in [ARCHITECTURE.md](ARCHITECTURE.md). Code conventions are in §6.
