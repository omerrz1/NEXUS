# Nexus — Architecture

> A local-first AI agent for the terminal. Local model, local tools. The one thing that leaves the machine is a web search, and only its search text, shown to the user first.

**Status:** the brain, the CLI, the agent loop, nine tools (files, commands, web search, a todo list, and session notes), the guardrails, context compaction, and saved sessions are built. Undo, config files, and the remaining tools are planned. Language: Python 3.11+. The design is open to change.

---

## 1. Goals and principles

1. **Local by default.** The model, the tools, and every file stay on the machine. The only traffic that leaves it is the text of a `web_search`, which the user sees first (§5.5), and the model server is reached over loopback. No telemetry, no update checks, no cloud fallback. This is enforced in code and tests (see §8), not just by convention.
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

1. `context` keeps the messages (system prompt + history) inside the token budget: it trims old tool output, and past about 70% it summarizes the oldest turns.
2. `brain` sends them, plus the tool specs, to the local model server and streams back text and/or tool calls.
3. If there are no tool calls, the model has answered and the loop ends.
4. For each tool call: the arguments are validated, then `guardrails` returns **allow / ask / deny**.
5. If allowed (or the user approves), the tool runs. Its output is capped and appended to the history.
6. After the turn, `session` saves the conversation with its todo list and notes. (Snapshots before writes, for undo, are planned.)
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
│   │   ├── repl.py                   # interactive session: read input, run a turn, save it
│   │   ├── oneshot.py                # `nexus -p "..."` non-interactive mode
│   │   ├── doctor.py                 # `nexus doctor`: server reachable? model loaded? tool calls work?
│   │   ├── prompt.py                 # the input line: / and @ completion menu, history, status bar
│   │   ├── stream.py                 # one model turn, live: thinking animation, streamed Markdown
│   │   ├── render.py                 # banner, details card, tool-call and result lines
│   │   ├── slash.py                  # the slash command list, grouped /help, and the dispatcher
│   │   ├── session_commands.py       # /new /sessions /resume /rename /delete, and opening a session
│   │   ├── memory_commands.py        # /memory /todo /compact
│   │   ├── tool_views.py             # /tools and /tool
│   │   ├── settings.py               # mode / depth / reasoning settings, saved between sessions
│   │   ├── picker.py                 # inline arrow-key menu, with per-row hotkeys
│   │   ├── approve.py                # the approval prompt (implements Approver)
│   │   ├── preview.py                # draws a change: syntax-colored code, or a diff
│   │   ├── todo_view.py              # the todo list as a checklist
│   │   ├── export.py                 # /copy and /save
│   │   ├── agent_events.py           # turns loop events into terminal output
│   │   ├── status.py                 # server health probe, git branch, the context meter
│   │   └── theme.py                  # colors and animation helpers
│   │
│   ├── brain/                        # talks to the model
│   │   ├── base.py                   # Brain protocol, BrainReply, Depth
│   │   ├── openai_compat.py          # llama.cpp server, Ollama, LM Studio, mlx-lm
│   │   ├── mock.py                   # scripted replies for tests
│   │   ├── toolcalls.py              # extract tool calls: native -> text fallback -> JSON repair
│   │   └── tokens.py                 # token estimate, corrected by real usage from the server
│   │
│   ├── loop/                         # the agent loop
│   │   ├── agent.py                  # run_agent(): the loop itself, and run_tool_call()
│   │   ├── budget.py                 # fitting the prompt in the window: trim, then summarize
│   │   ├── deps.py                   # Deps: everything the loop needs, passed in explicitly
│   │   ├── stop.py                   # stop conditions: repeat detector, error streak
│   │   └── events.py                 # event dataclasses and HaltReason
│   │
│   ├── tools/                        # what the model can do
│   │   ├── base.py                   # Tool, ToolContext, ToolResult, Preview, Risk
│   │   ├── registry.py               # the explicit tool list; get, names, specs
│   │   ├── output.py                 # cap_text(): keep tool output inside the size limits
│   │   ├── process.py                # run a child process: no input, a time limit, no secrets
│   │   ├── builtin/
│   │   │   ├── read_file.py          # numbered lines, paged
│   │   │   ├── list_dir.py           # folder listing, shallow or a few levels deep
│   │   │   ├── find_files.py         # find by name pattern, with time and match limits
│   │   │   ├── write_file.py         # create or replace a file; previews the code or a diff
│   │   │   ├── run_command.py        # bash, no stdin, timeout kills the process tree
│   │   │   ├── web_search.py         # DuckDuckGo search: titles, links, snippets
│   │   │   ├── update_todo.py        # the model's checklist for multi-step work
│   │   │   ├── remember.py           # save a session note
│   │   │   ├── forget.py             # delete a session note
│   │   │   ├── create_tool.py        # make or replace a tool Nexus can call (always asks)
│   │   │   ├── delete_tool.py        # delete a tool Nexus made (always asks)
│   │   │   └── (planned)             # search_text, edit_file
│   │   ├── web/
│   │   │   └── duckduckgo.py         # reads DuckDuckGo's HTML results page; skips ads
│   │   └── custom/                   # tools Nexus makes for itself
│   │       ├── manifest.py           # a tool's name, purpose, and inputs; validated on creation
│   │       ├── script_tool.py        # a Tool that runs a saved script as a child process
│   │       └── library.py            # ~/.nexus/tools: one folder per tool, saved and loaded
│   │
│   ├── instructions/                 # what the model is told
│   │   ├── assemble.py               # builds the system prompt from the layers
│   │   ├── project.py                # (planned) loads NEXUS.md (global + project)
│   │   ├── environment.py            # cwd, OS, shell, date: a snapshot at session start
│   │   └── prompts/                  # shipped prompt text as plain markdown, not string literals
│   │       ├── core.md               # identity: a general AI agent, and its working style
│   │       ├── tool_use.md           # how and when to call tools; search results are untrusted
│   │       ├── working_rules.md      # look before changing, smallest change, check the result
│   │       ├── compaction.md         # how to write the running summary (used by context/)
│   │       └── (planned) plan_mode.md  # read-only addendum
│   │
│   ├── guardrails/                   # what the model may do
│   │   ├── modes.py                  # Mode: read-only | ask | auto
│   │   ├── policy.py                 # check_tool_call(tool, args, mode, ctx) -> Verdict
│   │   ├── commands.py               # command denylist and the read-only safe list
│   │   ├── approval.py               # Approval, Answer, and the Approver interface
│   │   └── network.py                # (planned) loopback-and-search-only enforcement
│   │
│   ├── context/                      # keeps the prompt inside the token budget
│   │   ├── manager.py                # shrink_to_fit(): stub old tool output when space runs out
│   │   ├── compaction.py             # summarize old turns into one message
│   │   └── repomap.py                # (later) compact map of the repo
│   │
│   ├── session/                      # what belongs to one conversation
│   │   ├── memory.py                 # SessionMemory: the todo list and notes
│   │   ├── store.py                  # Session, SessionStore: one JSON file per session
│   │   └── checkpoints.py            # (planned) pre-write snapshots -> /undo
│   │
│   └── config/                       # (planned)
│       ├── schema.py                 # config shape (pydantic, validated)
│       └── load.py                   # defaults <- ~/.nexus/config.toml <- ./.nexus/config.toml <- flags
│
└── tests/
    ├── conftest.py                   # autouse fixture: fail any non-loopback network connection
    ├── test_cli*.py                  # rendering, slash commands, approval, sessions, previews
    ├── test_brain/                   # includes the malformed-output corpus for the parser
    ├── test_tools/                   # built-in tools, web search over a mock transport, tool making
    ├── test_guardrails/              # adversarial command and policy tests
    ├── test_loop/                    # full loop against the mock brain, including compaction
    ├── test_context/                 # trimming and summarizing
    ├── test_session/                 # the store and session memory
    ├── test_architecture.py          # import scan enforcing the dependency rule; prompt budget
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

**How the code differs from the sketch above.** The loop is built as sketched, with three simplifications that keep it plainer:

- `run_agent(messages, deps, mode, depth, on_event)` works on the conversation list directly, so there is no separate `AgentState` class. The REPL owns the list and undoes a turn by truncating it.
- Events go to a plain `on_event` callback instead of an `EventBus` object.
- `check_tool_call(...)` is a function, not a `Guard` class, because it has no state. The mode is passed in on each call, so `/mode` takes effect immediately.

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
- **A tool that can need approval describes what it will do** with a `Preview`: plain data (a title, and for a file write its path, current contents, and new contents; for a command or search, the text). The terminal decides how to draw it, so tools stay free of UI code.
- **Schemas are flat.** Nested argument models are expanded in `Tool.spec()` (no `$ref` or `$defs`), because small models read one flat schema more reliably and it costs fewer tokens.
- **Registration is a plain list** in `registry.py`. No decorators or auto-discovery, so reading one file tells you every tool that exists.
- **Keep the tool count small.** Each tool costs prompt tokens and increases the chance of a wrong choice. A test keeps the system prompt plus every built-in tool spec under 2000 tokens. Tools Nexus makes add their own specs on top, so at most 12 can exist at once.

**v1 tool set:**

| Tool | Risk | Purpose |
|---|---|---|
| `read_file` | read | Numbered lines; `offset` / `limit` for paging |
| `list_dir` | read | Directory listing, shallow by default |
| `find_files` | read | Find files by glob pattern |
| `search_text` | read | *(planned)* Search file contents (uses `rg` if installed, built-in fallback otherwise) |
| `write_file` | write | Create a file or fully overwrite one; previews the code or a diff |
| `edit_file` | write | *(planned)* Exact-match replace (see below); returns a unified diff |
| `run_command` | exec | Run a shell command in the workspace, with timeout and output cap |
| `web_search` | network | Search DuckDuckGo: titles, links, and snippets. Cannot open the pages |
| `update_todo` | none | The model's checklist for multi-step work; the whole list is sent each time. Survives summarizing |
| `remember` / `forget` | none | Save or delete a short session note (at most 20, 300 characters each). Survives summarizing |
| `create_tool` / `delete_tool` | write, always asks | Make, replace, or delete a tool of Nexus's own (see below) |

The `none`-risk tools only change Nexus's own session memory, never the user's files, so they never need approval. Their state lives in one `SessionMemory` object that the tools, the loop, and the CLI share (§5.7).

**Tools Nexus makes for itself** (`nexus/tools/custom/`). A tool made at run time is a folder in `~/.nexus/tools/<name>/` holding `tool.json` (name, description, and inputs) and `run.py`. Editing a tool is replacing it: the model reads `run.py`, then calls `create_tool` again with the same name.

- **A script and a subprocess, not Python loaded into Nexus.** `ScriptTool` runs `run.py` with the interpreter that runs Nexus, passes the inputs as one JSON object on standard input, and returns what it prints. It goes through the same `tools/process.py` as `run_command`: working directory, no other input, a one-minute limit that kills the whole process tree, and an environment without secrets. Model-written code never runs inside the Nexus process, and no manifest can point at another program.
- **Inputs are text.** Every input is a required string, so the schema stays flat and small models fill it in reliably. The script converts what it needs.
- **The registry changes at run time.** A new tool is in the model's list on its very next step, so the loop recounts the size of the tool specs every step, not once per turn. Tools on disk are loaded at startup by an explicit `load_custom_tools` call, never by `default_registry()`, so tests never read a developer's real tools. A saved tool whose name matches a built-in is skipped and reported.
- **Bad scripts are refused before the user is asked.** `create_tool` checks the name, the inputs, and the script's syntax while validating its arguments, so the model gets "syntax error on line 3" as an ordinary tool error and the user is not asked to approve code that cannot run.
- **Names are safe by construction.** A tool name is 3 to 40 lowercase letters, digits, and underscores, checked before any path is built, so a name can never leave the library folder. The folder and its files are readable only by the owner, and files are replaced atomically.

**`edit_file` is the most failure-prone tool with small models**, so it is built defensively: `old_string` must match exactly once (or `replace_all` is set); a whitespace-tolerant fallback match is tried before failing; on failure it returns the closest matching region so the model can correct itself instead of guessing.

### 5.4 Instructions (`nexus/instructions/`)

The system prompt is assembled from layers, in this order:

| # | Layer | Source | Changes |
|---|---|---|---|
| 1 | Identity and working style | `prompts/core.md` | Never |
| 2 | Tool-use rules | `prompts/tool_use.md` | Never |
| 3 | Working rules | `prompts/working_rules.md` | Never |
| 4 | Mode addendum (planned) | `prompts/plan_mode.md` (read-only mode only) | Per session |
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
| `write` | deny | ask, showing a diff | allow inside the workspace (no undo yet), ask outside it |
| `exec` | deny, except safe-listed commands | ask, unless safe-listed | allow, unless denylisted |
| `network` | ask | ask | allow |
| `none` | allow | allow | allow |

**Rules no mode can override:**

- **Reading is allowed anywhere.** The agent may list, find, and read files on the whole computer so it can help with anything on it. That was safe because nothing it read could leave the machine, and `web_search` changes that: the model can put what it read into a query. So every mode except `auto` shows the exact query and asks first, and the prompt to the model says that search results are data, never instructions. Network commands in `run_command` are still denied. Paths are resolved (symlinks included) before any check.
- **Writing outside the workspace always asks**, even in `auto` mode, and never happens in `read-only` mode. A symlink that leads out of the workspace counts as outside. (This replaces the original rule that confined every path to the workspace.)
- **Tools that change Nexus itself always ask.** `create_tool` and `delete_tool` set `always_ask`: they ask in every mode including `auto`, `read-only` refuses them, and their grant scope is empty, so "always allow" is never offered and approving one change cannot approve the next. A tool Nexus made counts as `exec` risk whatever it says it does, and using it asks in `ask` mode, where the user can allow that one tool for the session.
- **Command denylist** (`commands.py`). Always denied: privilege escalation (`sudo`, `su`), network tools (`curl`, `wget`, `ssh`, `scp`, `nc`, ...), remote git operations (`push`, `pull`, `fetch`, `clone`), and destructive patterns such as `rm -rf` on `/`, `~`, or the workspace root.
- **Scrubbed environment.** `run_command` runs with the workspace as its working directory and an environment stripped of inherited secrets (tokens, API keys, cloud credentials).
- **Limits.** Command timeout, per-result output cap, and file size limits. The output cap is sized to the model's context window (`ToolContext.for_window`) so one result cannot fill it.

**Be honest about made tools.** A script Nexus writes is code the model produced, and nothing inspects what it does: it can use the network, read any file, or write outside the working directory, just as any program the user runs could. The denylist does not look inside scripts, and the subprocess limits (time, environment, no input) contain accidents, not malice. What protects the user is that they read the whole script before it exists, and that approval is never automatic. The OS-level sandbox planned for v2 would contain these too.

**Be honest about what a denylist is.** String-matching commands is a speed bump, not a security boundary; a determined command can evade it. Real containment is an OS-level sandbox (seatbelt / bubblewrap) with the network denied. That is planned for v2 (§10). Until then, `ask` mode with a human reading each command is the actual safety net.

**Approvals** go through an injected interface so the loop stays UI-free:

```python
class Approval(StrEnum):
    ONCE = "once"
    SESSION = "session"
    DENY = "deny"


@dataclass(frozen=True)
class Answer:
    approval: Approval
    instead: str = ""      # for a refusal: what the user wants done instead


class Approver(Protocol):
    def approve(self, call: ToolCall, preview: Preview | None, scope: str) -> Answer: ...
```

`SESSION` grants are scoped by the tool's `grant_scope`, not just its name, and last only for the current session: "always" for `run_command` covers one program (say `git`), and for `write_file` covers the working directory, or one file elsewhere. When the user declines with a note, the loop hands it to the model ("The user declined this action and said: ... Do that instead"), so a refusal steers the model instead of stopping it.

**The approval prompt** (`cli/approve.py`, `cli/preview.py`) is built so that approving code means seeing it:

- The change is drawn in a panel titled with a short path: new files as syntax-colored code with line numbers, changes as a diff of only the changed lines with a little context. A command or search is shown as typed.
- Long changes are cut at 40 lines. When that happens, the first menu entry is "View the N lines not shown", which opens the whole change in a pager, so pressing enter never approves code the user has not seen.
- The answer is one keypress in a menu (arrows and enter, a number, or a hotkey): `y` yes, `a` yes and do not ask again for that scope, `n` no, `t` no and tell Nexus what to do instead. Escape declines.
- Keys typed while the model was working are discarded before the menu appears, so they cannot answer for the user.
- Without a terminal (a pipe, or `-p`), it falls back to typing `y`, `a`, or `n`.

**Safe commands need no approval.** A single read-only command, or a pipe of them (`ls`, `cat`, `grep`, `git status`, `find` without `-delete` or `-exec`, and a few more), runs without asking in every mode except when it is denylisted. Anything with `;`, `&&`, redirection, or substitution asks.

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

**How it works.** Before each model call, `loop/budget.py` sizes the prompt budget: the window, minus room for the reply (a quarter of the window when the model thinks, an eighth when it does not, at least 512 to 1024 tokens), minus the tool specs. Above 70% of it, pass 1 stubs the oldest tool outputs (`shrink_to_fit`). If that is not enough, pass 2 (`context/compaction.py`) runs:

- The newest messages worth about 30% of the budget are kept word for word. The kept part never starts with a tool result, because that must stay next to the assistant message that asked for it, so the newest tool call and its results are always kept.
- Everything older is summarized by the model with thinking off, into one message that follows the system prompt (a user-role message starting `[Summary of the earlier conversation]`, since some chat templates only allow a system message first). The old part can be bigger than the window: it is summarized a block at a time, each block together with the summary so far. An earlier summary is carried forward, never stacked.
- The todo list and notes are copied into the summary unchanged, after the model's text, so they survive every compaction.
- The turn's request is never lost. If a turn runs so long that its own early steps must be summarized, the user's message is put back right after the summary, word for word (`compact()` finds it by identity, not by equal text).
- If the model writes no summary, the conversation is left as it was and the loop stops with `CONTEXT_FULL` (which now only happens when even the newest tool call and results cannot fit).

The summary call is counted in the turn's usage. `/compact` runs the same thing on demand, and the status bar shows the real window use, from the server's own counts.

**Estimates are calibrated.** The local estimate runs about 25% low for code and markdown, so the loop starts with a cautious 1.3x factor and replaces it with the ratio of the server's real `prompt_tokens` to its own estimate after every reply. Tool output is also capped at half the window in bytes (`ToolContext.for_window`).

**Cut-off and empty replies are handled, not hidden.** When the server stops a reply for lack of room (`finish_reason: length`) the brain marks it `cut_off`, the loop runs none of its tool calls (they may be half-written), tells the user, and the brain adopts `prompt + reply` tokens as the real window, which corrects a wrong `--context-window`. When a thinking model puts its answer in its reasoning and returns an empty reply, the loop asks once more with thinking off.

**The window is set on the server.** Nexus cannot change it: Ollama's OpenAI-style endpoint ignores `options.num_ctx` (its native `/api/chat` honors it, which a future Ollama adapter could use). Set it with `OLLAMA_CONTEXT_LENGTH` or a Modelfile `PARAMETER num_ctx`, and tell Nexus with `--context-window` (default 16384, defined with the other server defaults in `brain/base.py`).

### 5.7 Session (`nexus/session/`)

A session is one conversation plus what belongs to it.

- **Memory** (`memory.py`). `SessionMemory` holds the todo list and the notes. It is one shared, mutable object: the `update_todo`, `remember`, and `forget` tools were built with it, the loop reads it to pin it into summaries, and the CLI shows it. `/new` and `/resume` reload it in place, so the tools never point at stale data.
- **Store** (`store.py`). One JSON file per session in `~/.nexus/sessions/`, holding the messages, the memory, a title, and timestamps. The folder is `0700` and files are `0600`, because a conversation can contain private file contents. Files are written to a temporary name and moved into place, so a crash never leaves half a file. Ids are a date, a time, and four random hex digits, and anything else is refused before it reaches the filesystem, so `/resume ../x` cannot become a path. A session is saved after each finished turn; one with no finished turn is not saved. Damaged files are skipped when listing.
- **Resume.** `nexus --resume` continues the latest session started in this folder, `--resume 2` or `--resume <id-prefix>` picks one by its number in `/sessions` or its id. The system prompt is rebuilt on resume so the environment block shows today's date and folder. If the session was started elsewhere, Nexus says so.
- **What survives.** The saved messages are the live conversation, so a summary made by compaction is what is stored; the summarized-away messages are not kept.
- **Checkpoints** *(planned).* Before any write tool runs, the affected files are copied to `.nexus/checkpoints/<session>/<step>/`. `/undo` restores the last step. It does not depend on git.

Undoing an aborted turn (Ctrl-C or an error) removes the user's message and everything after it, found by identity, because summarizing during the turn can shorten the list.

### 5.8 CLI (`nexus/cli/`)

- **Modes:** interactive REPL (`nexus`), one-shot (`nexus -p "..."`), and `nexus doctor`.
- **Flags:** `--mode`, `--depth`, `--model`, `--base-url`, `--context-window`, `--resume [SESSION]`, `--no-anim`.
- **Slash commands**, grouped in `/help`: `/new` `/sessions` `/resume` `/rename` `/delete` `/compact` `/clear` · `/memory` `/todo` · `/settings` `/mode` `/depth` `/thoughts` · `/model` `/tools` `/tool` `/doctor` · `/copy` `/save` `/stats` `/tokens` · `/help` `/exit`. (`/undo` comes with checkpoints.) The list lives in one place, `SLASH_COMMANDS`, and a test checks that every command is in a help group.
- **Plan and context are visible.** When the model updates its todo list, the CLI draws a checklist card instead of the tool's plain-text reply, and the status bar shows how full the context window is (green, amber above 60%, red above 85%).
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

"Nothing leaves the machine except a search you approve" is a requirement, so it is checked by code and tests rather than trusted.

1. **Loopback check.** At startup, `guardrails/network.py` resolves the model URL and refuses anything that is not loopback (`127.0.0.0/8`, `::1`, `localhost`, or a unix socket).
2. **Runtime socket guard.** The same module wraps `socket.socket.connect` so any non-loopback connection raises `NetworkGuardError`. This covers the whole Nexus process, including every dependency. It does not cover child processes started by `run_command`; those are handled by the command denylist now and the OS sandbox in v2.
3. **No hidden traffic.** No telemetry, crash reporting, update checks, or remote config. Each dependency is checked for network calls before it is added.
4. **CI proof.** An autouse pytest fixture in `tests/conftest.py` fails any test that attempts a non-loopback connection.
5. **One network tool, and it asks.** `web_search` is the only tool that talks to the internet. It sends only the query, through DuckDuckGo's plain-HTML page, and the user sees the exact text first in every mode except `auto`. There is no fetch or browse tool. Its tests run over a mock transport, so the CI guard in item 4 still fails any real outside connection. When `guardrails/network.py` is built, its socket guard must allow the loopback model server and this one search host, and nothing else.
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

**After v1:** plan mode polish, skills (on-demand instruction files listed by name and description, loaded by a tool), local stdio MCP servers, sub-agents, LSP diagnostics, local embedding search, OS-level sandbox.

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
| 10 | Web search | Scrape DuckDuckGo's HTML page directly with `httpx` and the standard library parser; skip ads | No key, no account, no new dependency. It is brittle by nature: the page needs a browser-like `User-Agent`, and DuckDuckGo answers a challenge page when it limits requests, which the tool reports as "may be limiting requests" | The markup changes, or blocks become common; then add a backend behind a small protocol (a local SearXNG instance would keep Nexus's own traffic on loopback) |
| 11 | Sessions | One JSON file per session, rewritten after each turn | Compaction rewrites the history, so an append-only log would need replaying; a snapshot is simple and readable | Sessions grow large, or evals need the full raw history |
| 12 | Summaries | The model summarizes, at about 70% of the budget, keeping the newest 30% verbatim | Cheapest-first (stub, then summarize) keeps most detail, and a rolling summary works on any window size | Summaries lose facts that matter; then pin more, or summarize earlier |
| 13 | Tools Nexus makes | A script run as a child process, inputs as JSON on stdin, every input a string; created only after the user reads the code, every time | Keeps model-written code out of the Nexus process, reuses the command runner's limits, and keeps schemas flat for small models. It is not a sandbox: the approval is the protection | A real sandbox exists (v2), or typed inputs and optional inputs turn out to be needed |

---

## 12. Non-goals for v1

- Cloud or remote model providers
- Fetching or browsing web pages (search results only)
- Multi-agent orchestration
- IDE integration
- Plugin marketplace
- Embedding / RAG index
- MCP support
- Windows support (Linux and macOS first)
