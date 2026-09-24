# Nexus

A coding agent for the terminal that runs entirely on your machine: a local model, local tools, and no network access beyond a model server on loopback.

> **Status: early.** You can chat with a local model in a polished terminal UI. The agent parts (tools, the agent loop, safety rules) are being built next. See the build order in [ARCHITECTURE.md §10](ARCHITECTURE.md#10-build-order).

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

## What is in the code

Only folders with working code exist. Each new part gets its folder when it is built, following the plan in [ARCHITECTURE.md](ARCHITECTURE.md).

```
src/nexus/
├── messages.py      the data every part shares: messages, tool calls, token usage
├── brain/           talks to the local model                        done
├── cli/             everything you see in the terminal               done
├── tools/           what the model can do (the interface; no tools yet)
├── guardrails/      what the model may do (only the modes so far)
└── instructions/    what the model is told (prompt text)
```

### Where to start reading

1. `cli/main.py`: reads the command-line flags and connects the parts.
2. `cli/repl.py`: the interactive loop: read input, run a command or send it to the model.
3. `brain/base.py`: the contract every model adapter follows.
4. `brain/openai_compat.py`: the adapter that streams replies from the local server.

## Development

```sh
make check     # lint, format check, type check (mypy --strict), and tests
make format    # auto-format the code
```

Design, conventions, and the reasons behind them are in [ARCHITECTURE.md](ARCHITECTURE.md). Code conventions are in §6.
