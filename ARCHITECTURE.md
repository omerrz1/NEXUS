# Nexus — Architecture

> A local-first coding agent for the terminal. Local model, local tools, no network.

**Status:** the brain and the CLI are built; everything else is planned. Language: Python 3.11+. The design is open to change.

---

## 1. Goals and principles

1. **Local only.** The only network traffic Nexus makes is HTTP to a model server on loopback. No telemetry, no update checks, no cloud fallback, no web tools. This is enforced in code (see §8), not just by convention.
2. **Built for small models.** Local models have smaller effective context windows and are less reliable at tool calling than hosted frontier models. Every choice below (few tools, strict schemas, errors fed back to the model, aggressive context budgeting) assumes this.
3. **A small loop with pluggable parts.** Brain, tools, guardrails, and UI each sit behind an interface, so any of them can be swapped or mocked in tests.
4. **Safe by default.** Workspace-jailed file access, approval for writes and commands, undo for every edit.
5. **Observable.** Every step is an event. Events drive the UI and are written to a session log that can be replayed.
6. **Readable over clever.** Plain Python, full type hints, small functions, explicit wiring, few dependencies. The rules are in §6.

---

## 2. The five parts of an agent, and where they live

| Concept | What it means in Nexus | Package |
|---|---|---|
| **Brain** | The LLM behind a provider interface, plus tool-call extraction | `nexus/brain/` |
| **Tools** | Typed capabilities the model can call | `nexus/tools/` |
| **Loop** | Ask the brain, act, observe, repeat until done | `nexus/loop/` |
| **Instructions** | System prompt, tool-use rules, project rules | `nexus/instructions/` |
| **Guardrails** | Policy that decides allow / ask / deny before anything runs | `nexus/guardrails/` |

Three supporting layers make the five parts work well with a local model:

| Layer | Job | Package |
|---|---|---|
| **Context** | Keep the prompt inside the token budget (stubbing, compaction) | `nexus/context/` |
| **Session** | Append-only event log, resume, pre-write checkpoints for undo | `nexus/session/` |
| **CLI** | The only code that touches the terminal | `nexus/cli/` |

---

## 3. System overview

```
                      ┌───────────┐
      you ──────────► │    CLI    │  renders events, asks for approvals
                      └─────┬─────┘
                            │
┌──────────────┐      ┌─────▼─────┐
│ INSTRUCTIONS ├─────►│   LOOP    │
└──────────────┘      └─────┬─────┘
                            │
        ┌───────────┬───────┴───┬─────────────┐
        │           │           │             │
  ┌─────▼─────┐ ┌───▼───┐ ┌─────▼──────┐ ┌────▼────┐
  │  CONTEXT  │ │ BRAIN │ │ GUARDRAILS │ │ SESSION │
  └───────────┘ └───┬───┘ └─────┬──────┘ └─────────┘
                    │           │ allow
   HTTP, loopback   │           │
                    │      ┌────▼────┐
                    │      │  TOOLS  │
              ┌─────▼────┐ └────┬────┘
              │  local   │      │
              │  model   │      ▼
              │  server  │  workspace
              └──────────┘  (files, shell)
```

**One user turn, step by step:**

1. `context` assembles the messages (system prompt + history) within the token budget.
2. `brain` sends them, plus the tool specs, to the local model server and streams back text and/or tool calls.
3. If there are no tool calls, the model has answered and the loop ends.
4. For each tool call: the arguments are validated, then `guardrails` returns **allow / ask / deny**.
5. If allowed (or the user approves), the tool runs. Its output is capped and appended to the history.
6. `session` logs every event and snapshots files before writes.
7. The loop checks its stop conditions and goes back to step 1.

---

## 4. Repository layout

Files marked `(planned)` do not exist yet. A file or folder is created when it is implemented, so the repository only ever contains working code.

```
nexus/                                # repository root
├── README.md                         # start here: quick start and a map of the code
├── ARCHITECTURE.md
├── pyproject.toml                    # metadata, dependencies, ruff / mypy / pytest config
├── Makefile                          # `make check` = lint + format check + types + tests
│
├── src/nexus/
│   ├── __main__.py                   # enables `python -m nexus`
│   ├── messages.py                   # shared plain data: Message, ToolCall, ToolSpec, Usage
│   │
│   ├── cli/                          # UI layer: the only place that touches the terminal
│   │   ├── main.py                   # parse args, load settings, wire dependencies by hand, start
│   │   ├── repl.py                   # interactive session
│   │   ├── oneshot.py                # `nexus -p "..."` non-interactive mode
│   │   ├── doctor.py                 # `nexus doctor`: server reachable? model loaded? tool calls work?
│   │   ├── prompt.py                 # the input line: / and @ completion menu, history, status bar
│   │   ├── stream.py                 # one model turn, live: thinking animation, streamed Markdown
│   │   ├── render.py                 # banner, settings card, tool and error cards
│   │   ├── slash.py                  # the slash command list and its handlers
│   │   ├── settings.py               # mode / depth / reasoning settings, saved between sessions
│   │   ├── picker.py                 # inline arrow-key menu
│   │   ├── export.py                 # /copy and /save
│   │   ├── theme.py                  # colors and animation helpers
│   │   └── approve.py                # y / n / always prompts (implements Approver)
│   │
│   ├── brain/                        # talks to the model
│   │   ├── base.py                   # Brain protocol, BrainReply, Depth
│   │   ├── openai_compat.py          # llama.cpp server, Ollama, LM Studio, mlx-lm
│   │   ├── mock.py                   # scripted replies for tests
│   │   ├── toolcalls.py              # extract tool calls: native -> text fallback -> JSON repair
│   │   └── tokens.py                 # token estimate, corrected by real usage from the server
│   │
│   ├── loop/                         # (planned) the agent loop
│   │   ├── agent.py                  # run_agent(): the loop itself
│   │   ├── deps.py                   # Deps: everything the loop needs, passed in explicitly
│   │   ├── state.py                  # AgentState: messages, todo list, files touched, counters
│   │   ├── stop.py                   # stop conditions: max steps, repeat detector, error streak
│   │   └── events.py                 # event dataclasses + EventBus
│   │
│   ├── tools/                        # what the model can do
│   │   ├── base.py                   # Tool, ToolContext, ToolResult, Risk
│   │   ├── registry.py               # the explicit tool list; get, specs, execute (timeout + output cap)
│   │   └── builtin/                  # (planned) read_file, list_dir, find_files, search_text,
│   │                                 #   write_file, edit_file, run_command, update_todo
│   │
│   ├── instructions/                 # what the model is told
│   │   ├── assemble.py               # (planned) builds the system prompt from layers
│   │   ├── project.py                # (planned) loads NEXUS.md (global + project)
│   │   ├── environment.py            # (planned) cwd, OS, shell, git branch/status, date
│   │   └── prompts/                  # shipped prompt text as plain markdown, not string literals
│   │       ├── core.md               # identity and working style
│   │       ├── tool_use.md           # how and when to call tools
│   │       ├── coding.md             # read before edit, minimal diffs, run tests
│   │       └── plan_mode.md          # read-only addendum
│   │
│   ├── guardrails/                   # what the model may do
│   │   ├── modes.py                  # Mode: read-only | ask | auto
│   │   ├── policy.py                 # (planned) Guard.check(tool, args) -> Verdict
│   │   ├── paths.py                  # (planned) workspace jail (resolve, symlink, ../ checks)
│   │   ├── commands.py               # (planned) command allowlist / denylist
│   │   ├── network.py                # (planned) loopback-only enforcement
│   │   └── limits.py                 # (planned) Limits dataclass with defaults
│   │
│   ├── context/                      # (planned) keeps the prompt inside the token budget
│   │   ├── manager.py                # build messages within budget
│   │   ├── compaction.py             # stub old tool output, then summarize old turns
│   │   └── repomap.py                # (later) compact map of the repo
│   │
│   ├── session/                      # (planned)
│   │   ├── log.py                    # append-only JSONL of every event
│   │   ├── resume.py                 # rebuild state from a log
│   │   └── checkpoints.py            # pre-write snapshots -> /undo
│   │
│   └── config/                       # (planned)
│       ├── schema.py                 # config shape (pydantic, validated)
│       └── load.py                   # defaults <- ~/.nexus/config.toml <- ./.nexus/config.toml <- flags
│
└── tests/
    ├── conftest.py                   # autouse fixture: fail any non-loopback network connection
    ├── test_cli.py, test_cli_interactive.py
    ├── test_brain/                   # includes the malformed-output corpus for the parser
    ├── test_tools/
    ├── test_guardrails/              # (planned)
    ├── test_loop/                    # (planned) full loop against the mock brain
    ├── test_context/                 # (planned)
    └── evals/                        # (planned) real-model task suite, run on demand
```

**Dependency rule.** `messages.py` imports nothing from Nexus. The leaf packages (`brain`, `tools`, `guardrails`, `context`, `instructions`, `session`, `config`) may import `messages` and each other's interfaces (for example `guardrails` reads `tools.base.Tool`), but never `loop` or `cli`, and never in a cycle. `loop` wires the leaf packages together and never touches the terminal: it emits events and calls an injected `Approver`. `cli` depends on `loop`. This is what makes the loop testable with a mock brain and no UI.

**Stack.** Python 3.11+.

| Kind | Choice | Used for |
|---|---|---|
| Runtime dependency | `pydantic` | Tool argument schemas (one model gives both JSON Schema and validation) and config validation |
| Runtime dependency | `httpx` | Talking to the model server, including streaming |
| Runtime dependency | `rich` | Rendering text, diffs, and spinners in `cli/` only |
| Runtime dependency | `prompt_toolkit` | The input line: completion menus, history, hotkeys, and pickers, in `cli/` only |
| Standard library | `argparse`, `tomllib`, `subprocess`, `pathlib`, `dataclasses`, `json` | Flags, config, commands, paths, data |
| Dev only | `pytest`, `ruff`, `mypy` | Tests, lint and format, type checking |

Three runtime dependencies, on purpose. `httpx` is used directly rather than a vendor SDK, so Nexus controls exactly what is sent and to where.

---

## 5. Components

### 5.1 Brain (`nexus/brain/`)

```python
class Brain(Protocol):
    """Anything that can turn a conversation into the model's next reply."""

    @property
    def context_window(self) -> int: ...

    def chat(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        on_delta: Callable[[str], None] | None = None,
    ) -> BrainReply: ...


@dataclass(frozen=True)
class BrainReply:
    message: Message              # what the model said
    tool_calls: list[ToolCall]    # what it wants to do (may be empty)
    usage: Usage                  # prompt / completion token counts
```

- **One adapter covers most runtimes.** `openai_compat.py` speaks `/v1/chat/completions`, which llama.cpp's server, Ollama, LM Studio, and mlx-lm all expose. It streams the response and reassembles tool-call fragments. Supporting another runtime means adding one file that implements `Brain`.
- **Nexus does not embed, download, or manage models.** The user runs a local model server; Nexus connects to it. `nexus doctor` probes it and reports what works.
- **Loopback only.** The configured base URL must resolve to loopback (see §8) or Nexus refuses to start.
- **Tool-call extraction is layered** (`toolcalls.py`):
  1. Use the server's native `tool_calls` when present.
  2. Otherwise parse tool calls from text (`<tool_call>{...}</tool_call>` blocks, fenced JSON).
  3. Repair common JSON breakage (trailing commas, single quotes, unterminated strings).
  4. If it still fails, tell the model what was wrong and let it retry. This counts toward the error streak.
- **Optional constrained decoding.** Where the server supports it (llama.cpp grammars / JSON schema), a config flag makes malformed tool calls impossible.
- **Sampling.** Low temperature (about 0.2) by default; tool-call turns benefit from determinism.

### 5.2 Loop (`nexus/loop/`)

The loop is deliberately small. Everything else is passed in through `Deps`, wired by hand in `cli/main.py`. `agent.py` should read like prose: the top-level function is the table of contents and the details live in well-named helpers.

```python
def run_agent(user_input: str, deps: Deps) -> RunResult:
    """Run one user turn: call the model and its tools until the model answers."""
    state = deps.state
    state.add_user_message(user_input)

    for _ in range(deps.limits.max_steps):
        prompt = deps.context.build(state)
        reply = deps.brain.chat(
            prompt,
            tools=deps.tools.specs(),
            on_delta=lambda text: deps.events.emit(TextDelta(text)),
        )
        state.add_assistant_message(reply.message)

        if not reply.tool_calls:
            return RunResult.finished(reply.message)

        for call in reply.tool_calls:
            result = run_tool_call(call, deps)
            state.add_tool_result(call, result)

        halt = check_stop(state, deps.limits)
        if halt is not None:
            return RunResult.halted(halt)

    return RunResult.halted(HaltReason.MAX_STEPS)


def run_tool_call(call: ToolCall, deps: Deps) -> ToolResult:
    """Validate one tool call, check guardrails, ask the user if needed, then run it.

    Every failure becomes a ToolResult the model can read and react to; nothing raises.
    (Event emission is omitted here for brevity.)
    """
    tool = deps.tools.get(call.name)
    if tool is None:
        return ToolResult.error(f"Unknown tool '{call.name}'. Available: {deps.tools.names()}")

    try:
        args = tool.args_model.model_validate(call.arguments)
    except ValidationError as err:
        return ToolResult.error(short_validation_message(tool, err))

    verdict = deps.guard.check(tool, args)
    if verdict.decision is Decision.DENY:
        return ToolResult.error(f"Not allowed: {verdict.reason}")
    if verdict.decision is Decision.ASK:
        if deps.approver.approve(call, verdict.preview) is Approval.DENY:
            return ToolResult.error("The user declined this action.")

    return deps.tools.execute(tool, args)  # applies the timeout and output cap
```

**Stop conditions** (`stop.py`):

| Condition | Default | Behavior |
|---|---|---|
| Model replies with no tool call | n/a | Normal completion |
| Max steps per user turn | 40 | Halt and report |
| Same tool + same arguments repeated | 3 times | Inject "you already did this", halt if it repeats again |
| Consecutive invalid/failed tool calls | 5 | Halt and report |
| Wall-clock budget | 10 min | Halt and report |
| User interrupt (Ctrl-C) | n/a | `KeyboardInterrupt` is caught in `cli/`; the in-flight request is closed, any partial assistant message is discarded, state stays consistent, control returns to the prompt |

**Events** (`events.py`) are frozen dataclasses and the only channel out of the loop. The renderer and the session log both subscribe to the `EventBus`, and the renderer uses `match` to draw each kind.

| Event | Emitted when |
|---|---|
| `TurnStarted` / `TurnEnded` | A user turn begins / ends |
| `TextDelta` | The model streams a chunk of text |
| `AssistantMessage` | The model finishes a message |
| `ToolRequested` | The model asked for a tool |
| `ToolVerdict` | Guardrails returned allow / ask / deny (and the user's answer) |
| `ToolFinished` | A tool finished |
| `Compacted` | Context was shrunk |
| `Halted` | A stop condition fired |

### 5.3 Tools (`nexus/tools/`)

A tool is a small class: a name, a description, a pydantic model for its arguments, a risk level, and a `run` method.

```python
class Risk(StrEnum):
    READ = "read"
    WRITE = "write"
    EXEC = "exec"


Args = TypeVar("Args", bound=BaseModel)


class Tool(ABC, Generic[Args]):
    """One capability the model can call. Subclasses fill in the attributes and run()."""

    name: str                          # verb_noun, e.g. "read_file"
    description: str                   # model-facing, at most two sentences
    args_model: type[Args]             # pydantic model: JSON Schema for the model + validation
    risk: Risk                         # drives guardrail defaults
    path_fields: tuple[str, ...] = ()  # args that hold file paths; guardrails jail-check these

    @abstractmethod
    def run(self, args: Args, ctx: ToolContext) -> ToolResult: ...


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    output: str
    truncated: bool = False
```

**A complete tool looks like this:**

```python
class ReadFileArgs(BaseModel):
    path: str = Field(description="File path, relative to the workspace")
    offset: int = Field(0, ge=0, description="Line to start from (0-based)")
    limit: int = Field(200, ge=1, le=1000, description="Maximum lines to return")


class ReadFile(Tool[ReadFileArgs]):
    name = "read_file"
    description = "Read a text file and return it with line numbers."
    args_model = ReadFileArgs
    risk = Risk.READ
    path_fields = ("path",)

    def run(self, args: ReadFileArgs, ctx: ToolContext) -> ToolResult:
        lines = (ctx.workspace / args.path).read_text().splitlines()
        window = lines[args.offset : args.offset + args.limit]
        return ToolResult.success(number_lines(window, start=args.offset + 1))
```

**Rules every tool follows:**

- **Output is plain text sized for a small context.** Hard cap (default 8 KB / 200 lines) with a footer that tells the model how to get more, e.g. `showing lines 1-200 of 1340; call read_file with offset=200`.
- **Errors are results, not exceptions.** Return `ToolResult.error(...)` with a short, actionable message the model can act on.
- **Tools never check permissions.** Guardrails decide before `run` is called; `path_fields` is how they know which arguments to jail-check.
- **Registration is a plain list** in `registry.py`. No decorators or auto-discovery, so reading one file tells you every tool that exists.
- **Keep the tool count small** (about 8-10). Each tool costs prompt tokens and increases the chance of a wrong choice.

**v1 tool set:**

| Tool | Risk | Purpose |
|---|---|---|
| `read_file` | read | Numbered lines; `offset` / `limit` for paging |
| `list_dir` | read | Directory listing, shallow by default |
| `find_files` | read | Find files by glob pattern |
| `search_text` | read | Search file contents (uses `rg` if installed, built-in fallback otherwise) |
| `write_file` | write | Create a file or fully overwrite one |
| `edit_file` | write | Exact-match replace (see below); returns a unified diff |
| `run_command` | exec | Run a shell command in the workspace, with timeout and output cap |
| `update_todo` | none | A scratchpad task list the model maintains; acts as external working memory |

**`edit_file` is the most failure-prone tool with small models**, so it is built defensively: `old_string` must match exactly once (or `replace_all` is set); a whitespace-tolerant fallback match is tried before failing; on failure it returns the closest matching region so the model can correct itself instead of guessing.

### 5.4 Instructions (`nexus/instructions/`)

The system prompt is assembled from layers, in this order:

| # | Layer | Source | Changes |
|---|---|---|---|
| 1 | Identity and working style | `prompts/core.md` | Never |
| 2 | Tool-use rules | `prompts/tool_use.md` | Never |
| 3 | Coding rules | `prompts/coding.md` | Never |
| 4 | Mode addendum | `prompts/plan_mode.md` (read-only mode only) | Per session |
| 5 | Project instructions | `~/.nexus/NEXUS.md`, then `<repo>/NEXUS.md` | Per session |
| 6 | Environment block | cwd, OS, shell, git branch and status, date | **Snapshot once at session start** |

**Why the order and the snapshot matter.** Local servers reuse their KV cache when the start of the prompt is byte-identical between calls, and prompt processing is the slow part of local inference. Layers 1-6 plus the tool specs form a prefix that stays identical for the whole session, so only new messages need processing. That is why the environment block is captured once rather than refreshed each turn.

**Budget.** Fixed prompt plus tool specs stays under about 2k tokens. A unit test enforces this so the prompt cannot silently grow.

**Prompts are markdown files, not code.** They can be edited, diffed, and versioned against eval results.

### 5.5 Guardrails (`nexus/guardrails/`)

Every tool call passes through one pipeline before it runs:

```
validate args -> path jail -> command rules -> policy (mode x risk) -> approval -> run (timeout + output cap)
```

**Modes** (`modes.py`):

| Risk | `read-only` | `ask` (default) | `auto` |
|---|---|---|---|
| `read` | allow | allow | allow |
| `write` | deny | ask, showing a diff | allow, checkpointed |
| `exec` | deny, except safe-listed commands | ask, unless safe-listed | allow, unless denylisted |

**Rules no mode can override:**

- **Path jail** (`paths.py`). Every path is resolved (symlinks included) and must land inside the workspace root or an explicitly added directory. `../`, absolute paths, and symlink escapes are rejected.
- **Command denylist** (`commands.py`). Always denied: privilege escalation (`sudo`, `su`), network tools (`curl`, `wget`, `ssh`, `scp`, `nc`, ...), remote git operations (`push`, `pull`, `fetch`, `clone`), and destructive patterns such as `rm -rf` on `/`, `~`, or the workspace root.
- **Scrubbed environment.** `run_command` runs with the workspace as its working directory and an environment stripped of inherited secrets (tokens, API keys, cloud credentials).
- **Limits** (`limits.py`). Command timeout, per-result output cap, max file size for reads and writes.

**Be honest about what a denylist is.** String-matching commands is a speed bump, not a security boundary; a determined command can evade it. Real containment is an OS-level sandbox (seatbelt / bubblewrap) with the network denied. That is planned for v2 (§10). Until then, `ask` mode with a human reading each command is the actual safety net.

**Approvals** go through an injected interface so the loop stays UI-free:

```python
class Approval(StrEnum):
    ONCE = "once"
    SESSION = "session"
    DENY = "deny"


class Approver(Protocol):
    def approve(self, call: ToolCall, preview: str | None) -> Approval: ...
```

`SESSION` grants are scoped to one tool plus an argument pattern, and last only for the current session.

### 5.6 Context manager (`nexus/context/`)

The token budget is `context_window - reserved_for_output`. The prompt is laid out to protect the stable prefix:

```
[ system prompt + tool specs ]   stable prefix, fixed budget
[ summary of older turns     ]   produced by compaction, empty at first
[ recent turns, verbatim     ]
[ current user message       ]
```

When usage crosses about 70% of the budget, compaction runs in two passes, cheapest first:

1. **Stub old tool output.** Replace bulky results with one-liners such as `[read_file src/a.py: 240 lines, omitted; re-run to see]`. Tool output is usually most of the tokens and least of the value once it has been acted on.
2. **Summarize old turns.** The model itself condenses the oldest turns into a short summary. The todo list and the list of files touched are pinned and survive every compaction.

Token counts are estimated locally and corrected with the real `usage` numbers the server returns.

### 5.7 Session (`nexus/session/`)

- **Log.** Every event is appended to `~/.nexus/sessions/<id>.jsonl`. This is local, replayable, and doubles as raw material for eval tasks.
- **Resume.** `nexus --resume` rebuilds `AgentState` from a log.
- **Checkpoints.** Before any write tool runs, the affected files are copied to `.nexus/checkpoints/<session>/<step>/`. `/undo` restores the last step. It does not depend on git.

### 5.8 CLI (`nexus/cli/`)

- **Modes:** interactive REPL (`nexus`), one-shot (`nexus -p "..."`), and `nexus doctor`.
- **Flags:** `--mode`, `--model`, `--resume`, `--config`.
- **Slash commands:** `/help` `/clear` `/undo` `/mode` `/model` `/compact` `/resume`.
- **`rich` draws output and `prompt_toolkit` reads input.** The input line has a completion menu (`/` commands with descriptions, `@` file mentions), history with inline suggestions, a status bar, and hotkeys (Shift-Tab cycles the mode, Ctrl-T cycles the thinking depth). Settings are chosen with inline arrow-key pickers and saved to `~/.nexus/settings.json`; command-line flags override them for one run.
- **Installed as a command** via a `pyproject.toml` entry point (`nexus = "nexus.cli.main:main"`).

### 5.9 Config (`nexus/config/`)

Layers, later ones win: built-in defaults, `~/.nexus/config.toml`, `./.nexus/config.toml`, CLI flags. TOML is read with the standard library's `tomllib` and validated by a pydantic model; a bad value produces a clear `ConfigError` at startup.

```toml
[brain]
base_url = "http://127.0.0.1:11434/v1"   # must be loopback
model = "your-local-model"
context_window = 16384
temperature = 0.2
constrained_decoding = false

[agent]
mode = "ask"                              # read-only | ask | auto
max_steps = 40

[limits]
tool_output_bytes = 8192
command_timeout_sec = 120

[tools]
enabled = ["read_file", "list_dir", "find_files", "search_text",
           "write_file", "edit_file", "run_command", "update_todo"]
```

Nothing in the config can point Nexus at a non-loopback host.

---

## 6. Code conventions (readability first)

The code should be readable by someone who has never seen the project. These are rules, not preferences, and `make check` enforces the mechanical ones.

- **Type hints on everything public**, checked with `mypy --strict`. The types document how the pieces fit together.
- **Plain data is `@dataclass(frozen=True)`.** Messages, events, results, and verdicts are immutable. Pydantic is used only at the edges: tool arguments and config.
- **Interfaces are `Protocol`s** (`Brain`, `Approver`). The only base class is `Tool`. No inheritance hierarchies.
- **Synchronous code, no `asyncio`.** The agent is inherently sequential (model, tool, model, ...). One thread of control keeps the loop readable top to bottom and makes Ctrl-C simple. Revisit only if we need parallel tool calls.
- **Small units.** A function fits on one screen (about 25 lines), a module stays under about 250 lines, and nesting stays at two levels: use early returns. When a file outgrows this, split it by responsibility.
- **Explicit over clever.** No metaclasses, no registration decorators, no `**kwargs` pass-through, no dependency-injection framework. The tool list is a plain list, and everything is wired by hand in `cli/main.py`, so you can read what exists and how it connects.
- **Names say what things do.** `verb_noun` functions (`build_prompt`, `check_stop`), noun classes, no abbreviations, no single-letter names outside comprehensions.
- **No magic strings.** Use enums: `Risk.READ`, `Decision.ASK`, `Mode.READ_ONLY`, `HaltReason.MAX_STEPS`.
- **Comments and docstrings explain why.** Every module opens with one line stating its single job. Public functions get a short docstring. Comments never restate the code.
- **Expected failures are values, not exceptions.** A bad tool call becomes `ToolResult.error(...)` and goes back to the model. Exceptions are reserved for real bugs and startup errors (`ConfigError`, `NetworkGuardError`).
- **One command checks everything.** `make check` runs `ruff` (lint and format), `mypy --strict`, and `pytest`. The formatter ends style debates.
- **The architecture is tested.** A small test scans imports and fails if the dependency rule in §4 is broken.

---

## 7. Small-model reliability

The largest risk in a local agent is not the architecture; it is a smaller model making more mistakes per step. These mitigations are built in from the start:

| Failure | Mitigation |
|---|---|
| Malformed tool-call JSON | Tolerant parser with repair; otherwise the error goes back to the model |
| Wrong or missing arguments | Schema validation, then a short error naming the expected shape |
| Invented tool names or file paths | Error lists the valid tools; prompt tells the model to `list_dir` / `find_files` first |
| Whitespace-inexact edits | Tolerant matching plus a closest-region hint |
| Repeating the same call | Repeat detector: nudge, then halt |
| Losing the thread on long tasks | `update_todo` tool, pinned across compaction |
| Context overflow | Per-result caps, stub old output, then summarize |
| Slow prompt processing | Stable prompt prefix for KV-cache reuse |
| Prompt and model regressions | Eval harness (§9): change one thing, measure the pass rate |

---

## 8. Local-only enforcement

"Nothing is external" is a requirement, so it is checked by code and tests rather than trusted.

1. **Loopback check.** At startup, `guardrails/network.py` resolves the model URL and refuses anything that is not loopback (`127.0.0.0/8`, `::1`, `localhost`, or a unix socket).
2. **Runtime socket guard.** The same module wraps `socket.socket.connect` so any non-loopback connection raises `NetworkGuardError`. This covers the whole Nexus process, including every dependency. It does not cover child processes started by `run_command`; those are handled by the command denylist now and the OS sandbox in v2.
3. **No hidden traffic.** No telemetry, crash reporting, update checks, or remote config. Each dependency is checked for network calls before it is added.
4. **CI proof.** An autouse pytest fixture in `tests/conftest.py` fails any test that attempts a non-loopback connection.
5. **No web tools.** There is no fetch or search tool. It is a non-goal for v1 and conflicts with principle 1.
6. **Models are not Nexus's business.** Nexus never downloads weights; getting a model onto disk is a user action outside Nexus.

---

## 9. Testing

Tests use `pytest`. Filesystem tests use the built-in `tmp_path` fixture, so they never touch real files.

| Layer | Approach |
|---|---|
| Tools | Unit tests on temp directories: happy path, truncation, and error cases |
| Guardrails | Adversarial tests: `../` escapes, symlinks, absolute paths, denylisted commands, quoting tricks |
| Tool-call parser | A corpus of real malformed model output collected from session logs |
| Loop | Full runs against `brain/mock.py`, which replays scripted tool-call sequences and makes deterministic assertions |
| Context | Budget math, stubbing, and compaction keeping pinned items |
| Architecture | Import scan enforcing the dependency rule (§4) |
| Evals | 10-30 small tasks, each with a fixture repo, a prompt, and a check command (e.g. "tests pass"). Run against the real local model on demand. Track the pass rate per model and per prompt version |

The eval harness is how we pick a model and tune prompts by measurement instead of by feel.

---

## 10. Build order

| Milestone | Deliverable | Needs a real model? |
|---|---|---|
| **M0 Skeleton** | `pyproject.toml`, `make check`, core types, event bus, mock brain, loop with `read_file`; loop tests pass | No |
| **M1 First conversation** | `openai_compat` brain with streaming, REPL and renderer, config loading, loopback check, `nexus doctor` | Yes |
| **M2 Useful and safe** | Full v1 tool set, guardrails (jail, modes, approver, command rules), checkpoints and `/undo` | Yes |
| **M3 Instructions and context** | Prompt layers, `NEXUS.md`, environment snapshot, context manager with stubbing, session log and resume | Yes |
| **M4 Reliability** | Text tool-call fallback and JSON repair, repeat detector, summarizing compaction, first eval tasks | Yes |
| **M5 Publish-ready** | Packaging (`pipx` / `uv tool install`, PyPI), docs, CI network-egress test, license | No |

**After v1:** plan mode polish, skills (on-demand instruction files listed by name and description, loaded by a tool), custom local tools from `~/.nexus/tools/`, local stdio MCP servers, sub-agents, LSP diagnostics, local embedding search, OS-level sandbox.

---

## 11. Decisions

| # | Decision | Recommendation | Why | Revisit if |
|---|---|---|---|---|
| 1 | Language | Python 3.11+ | Chosen by the project owner; readable, strong local-model ecosystem, and 3.11 brings `tomllib`, `StrEnum`, and better typing | Startup time or distribution becomes a real problem |
| 2 | Concurrency | Synchronous, no `asyncio` | The agent is sequential; the loop reads top to bottom; Ctrl-C stays simple | We need parallel tool calls (threads first) |
| 3 | Model runtime | Any OpenAI-compatible local server. Develop against Ollama; add llama.cpp for constrained decoding | One adapter covers all; Nexus stays out of model management | A runtime needs a native API for something we need |
| 4 | HTTP client | `httpx` directly, no vendor SDK | Full control over what is sent; one fewer large dependency | n/a |
| 5 | Schemas and config | `pydantic` v2 | One definition yields JSON Schema and validation | The dependency weight starts to matter |
| 6 | UI | `rich` output, `prompt_toolkit` input | Completion menus, pickers, and hotkeys make a local agent easy to drive; both stay inside `cli/` | A full-screen layout is needed |
| 7 | Default mode | `ask` | Safe default; `auto` is opt-in | Approvals become friction for common commands |
| 8 | Agent topology | Single loop | Sub-agents multiply context cost, which is scarce locally | Tasks routinely exceed one context window |
| 9 | Model choice | Decide with the eval harness; it is config, not code | Avoids committing before measuring | n/a |

---

## 12. Non-goals for v1

- Cloud or remote model providers
- Web browsing, fetch, or search tools
- Multi-agent orchestration
- IDE integration
- Plugin marketplace
- Embedding / RAG index
- MCP support
- Windows support (Linux and macOS first)
