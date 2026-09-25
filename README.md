# Nexus

An AI agent for the terminal that runs on your machine: a local model and local tools. The one thing that can leave your computer is a web search, and only its search text, shown to you first.

> **Status: early.** Nexus can chat and use tools: browse folders, read and write files, run bash commands, and search the web, with approval prompts and safety rules. It keeps a plan and notes, saves every session so you can resume it, and summarizes old conversation so it never runs out of room. Undo, config files, and more tools are next. See the build order in [ARCHITECTURE.md §10](ARCHITECTURE.md#10-build-order).

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
| `nexus --resume` | Continue your last session in this folder (or `--resume 2`, a number from `/sessions`) |
| `nexus -p "question"` | Ask one question without the interactive session |
| `nexus doctor` | Check that the model server is reachable and working |

## What the agent can do

| Tool | What it does | Asks first? |
|---|---|---|
| `list_dir`, `find_files`, `read_file` | Look around: browse any folder, find files by name, read text files | No |
| `write_file` | Create a file or replace one. You see the code, or a diff of the change, first | In `ask` mode; always outside the working directory |
| `web_search` | Search the web with DuckDuckGo: titles, links, and snippets | Unless in `auto` mode. You see the exact text that will be sent |
| `update_todo` | Keep a checklist for work with several steps | No |
| `remember`, `forget` | Save or delete short notes that last for the whole session | No |
| `run_command` | Run a bash command (no input, no internet, secrets removed from its environment) | In `ask` mode, unless it is a read-only command like `ls` or `git status` |

Press `Shift-Tab` to change how much it asks: `read-only` (never changes anything), `ask` (the default), or `auto` (writes inside the working directory and runs commands without asking). Commands that need the internet, `sudo`, and recursive deletes of your home folder or working directory are always refused.

**Approving a change.** When Nexus asks to write a file you see the whole change: new code with syntax colors and line numbers, or a diff of only the changed lines. Long changes are cut, and the first menu entry offers to show the rest, so pressing enter never approves code you have not seen. Answer with one key: `y` yes, `a` yes and do not ask again for that kind of change, `n` no, or `t` no, and tell Nexus what to do instead: what you type goes back to the model, which then tries again.

**Search results are not trusted.** Nexus tells the model that text from the web is data and never instructions. In `auto` mode searches run without asking, so keep an eye on what it does next.

**Context size.** Nexus assumes the model server runs with a 16,384-token window (`--context-window`). Ollama's own default is only 4096, which tool use fills quickly, and its OpenAI-style API ignores any window size a client asks for, so the window has to be set on the server. Give your model a window with a Modelfile:

```
FROM your-model
PARAMETER num_ctx 16384
```

then `ollama create your-model -f Modelfile` (or set `OLLAMA_CONTEXT_LENGTH=16384` for the whole server). If the number Nexus assumes is too big, it corrects itself the first time a reply is cut off, and it tells you when that happens.

The status bar shows how full the window is. Nexus first shortens old tool output, and at about 70% full it has the model summarize the older conversation and carries on with the newest part word for word, so a long session never stops for lack of room. `/compact` does the same on demand.

## Sessions and memory

Every conversation is saved after each turn, in `~/.nexus/sessions/` (readable only by you), together with its plan and notes.

| Command | What it does |
|---|---|
| `/sessions` | List saved sessions |
| `/resume [number\|id]` | Continue one (a menu if you give none) |
| `/new` | Save this session and start a fresh one |
| `/rename <title>`, `/delete [number\|id]` | Rename this session, or delete another |
| `/memory [add\|forget]` | Show, add, or delete this session's notes |
| `/todo` | Show the model's checklist |
| `/compact` | Summarize the older conversation now |

Notes and the checklist belong to one session. They are copied word for word into every summary, so they survive however long the conversation gets.

## What is in the code

Only folders with working code exist. Each new part gets its folder when it is built, following the plan in [ARCHITECTURE.md](ARCHITECTURE.md).

```
src/nexus/
├── messages.py      the data every part shares: messages, tool calls, token usage
├── brain/           talks to the local model
├── cli/             everything you see in the terminal
├── loop/            the agent loop: ask the model, run its tools, repeat
├── tools/           what the model can do: nine built-in tools
├── guardrails/      what the model may do: modes, command rules, approval
├── context/         keeps the conversation inside the model's window: trimming and summarizing
├── session/         saved sessions, and the plan and notes that belong to each
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
