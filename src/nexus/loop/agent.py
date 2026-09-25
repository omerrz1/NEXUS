"""The agent loop: ask the model, run the tools it requests, repeat until it answers."""

from dataclasses import dataclass
from enum import Enum, auto
from typing import Any

from pydantic import BaseModel, ValidationError

from nexus.brain.base import BrainReply, Depth
from nexus.brain.tokens import estimate_conversation_tokens
from nexus.guardrails.approval import Approval
from nexus.guardrails.modes import Mode
from nexus.guardrails.policy import Decision, check_tool_call
from nexus.loop.budget import DEFAULT_SCALE, make_room, next_scale, spec_tokens
from nexus.loop.deps import Deps
from nexus.loop.events import (
    EventHandler,
    Halted,
    HaltReason,
    ModelFinished,
    ModelStarted,
    Notice,
    ReasoningDelta,
    TextDelta,
    ToolFinished,
    ToolRequested,
    ToolStarted,
)
from nexus.loop.stop import Signal, StopTracker
from nexus.messages import Message, ToolCall, Usage
from nexus.tools.base import Tool, ToolResult

_EMPTY_REPLY_NUDGE = "You did not write an answer. Write your answer to the user now."
_REPEAT_WARNING = (
    "\n(You have made this exact call several times with the same result. "
    "Try something different, or answer the user.)"
)
_HALT_MESSAGES: dict[HaltReason, str] = {
    HaltReason.MAX_STEPS: "Stopped: the step limit for one request was reached.",
    HaltReason.REPEATED_CALL: "Stopped: the model kept repeating the same action.",
    HaltReason.ERROR_STREAK: "Stopped: too many tool calls failed in a row.",
    HaltReason.CONTEXT_FULL: (
        "Stopped: the conversation no longer fits in the model's {window:,}-token context "
        "window. Use /new to start a fresh conversation."
    ),
    HaltReason.EMPTY_REPLY: (
        "Stopped: the model finished thinking but never wrote an answer. "
        "Try again, or use /depth fast."
    ),
    HaltReason.REPLY_CUT_OFF: (
        "The reply was cut off: the model ran out of room in its {window:,}-token context "
        "window. Use /new to start a fresh conversation, or give the model server a bigger "
        "context window (see the README)."
    ),
}


@dataclass(frozen=True)
class RunResult:
    """How one user turn ended."""

    usage: Usage
    final_text: str
    halt: HaltReason | None = None


def run_agent(
    messages: list[Message],
    deps: Deps,
    mode: Mode,
    depth: Depth,
    on_event: EventHandler,
) -> RunResult:
    """Run one user turn until the model answers or a stop condition fires.

    `messages` is the whole conversation and already ends with the user's message. It is
    extended in place with everything the model says and every tool result.
    """
    stop = StopTracker()
    usage = Usage.empty()
    request = messages[-1]  # What the user asked; compaction never folds it into a summary.
    scale = DEFAULT_SCALE
    retry_without_thinking = False
    for step in range(1, deps.max_steps + 1):
        # After an empty reply, ask again without thinking so the model answers directly.
        step_depth = Depth.FAST if retry_without_thinking else depth
        retry_without_thinking = False
        tool_spec_tokens = spec_tokens(deps)  # Tools can be made or deleted during a turn.
        fits, spent = make_room(
            messages, deps, step_depth, tool_spec_tokens, scale, request, on_event
        )
        usage = usage + spent
        if not fits:
            return _halted(HaltReason.CONTEXT_FULL, usage, deps, on_event)

        sent_estimate = estimate_conversation_tokens(messages) + tool_spec_tokens
        on_event(ModelStarted(step))
        reply = _ask_model(messages, deps, step_depth, on_event)
        scale = next_scale(sent_estimate, reply.usage, scale)
        usage = usage + reply.usage

        if reply.cut_off:
            # A reply that hit the length limit may hold half a tool call, so nothing runs.
            messages.append(Message.assistant(reply.message.content))
            return _halted(HaltReason.REPLY_CUT_OFF, usage, deps, on_event, reply.message.content)

        outcome = _handle_reply(reply, messages, deps, mode, stop, on_event)
        if outcome is StepOutcome.ANSWERED:
            return RunResult(usage, reply.message.content)
        retry_without_thinking = outcome is StepOutcome.RETRY_WITHOUT_THINKING
        if stop.halt_reason is not None:
            return _halted(stop.halt_reason, usage, deps, on_event)
    return _halted(HaltReason.MAX_STEPS, usage, deps, on_event)


class StepOutcome(Enum):
    """What the loop does after one model reply."""

    ANSWERED = auto()  # The reply is the final answer.
    CONTINUE = auto()  # Ask the model again, now with tool results or feedback.
    RETRY_WITHOUT_THINKING = auto()  # Ask again, with thinking turned off.


def _handle_reply(
    reply: BrainReply,
    messages: list[Message],
    deps: Deps,
    mode: Mode,
    stop: StopTracker,
    on_event: EventHandler,
) -> StepOutcome:
    """Add the reply to the conversation and act on it: run tools, give feedback, or finish."""
    if reply.tool_calls:
        messages.append(reply.message)
        _run_tool_calls(reply.tool_calls, messages, deps, mode, stop, on_event)
        return StepOutcome.CONTINUE
    if reply.tool_call_errors:
        messages.append(reply.message)
        messages.append(Message.user(_unreadable_call_message(reply.tool_call_errors)))
        stop.record_unparseable_call()
        return StepOutcome.CONTINUE
    if not reply.message.content.strip():
        # Some models write their answer into their thinking and leave the reply empty.
        # The empty message is not kept: it would only confuse the model.
        on_event(Notice("The model wrote no answer; asking again."))
        messages.append(Message.user(_EMPTY_REPLY_NUDGE))
        stop.record_empty_reply()
        return StepOutcome.RETRY_WITHOUT_THINKING
    messages.append(reply.message)
    return StepOutcome.ANSWERED


def _ask_model(
    messages: list[Message], deps: Deps, depth: Depth, on_event: EventHandler
) -> BrainReply:
    reply = deps.brain.chat(
        messages,
        tools=deps.tools.specs() or None,
        on_delta=lambda text: on_event(TextDelta(text)),
        on_reasoning=lambda text: on_event(ReasoningDelta(text)),
        depth=depth,
    )
    on_event(ModelFinished(reply.usage))
    return reply


def _run_tool_calls(
    calls: tuple[ToolCall, ...],
    messages: list[Message],
    deps: Deps,
    mode: Mode,
    stop: StopTracker,
    on_event: EventHandler,
) -> None:
    """Run each requested tool and add its result to the conversation."""
    for call in calls:
        on_event(ToolRequested(call))
        result = run_tool_call(call, deps, mode, on_event)
        on_event(ToolFinished(call, result))

        text = result.output if result.ok else f"Error: {result.output}"
        if stop.record_call(call, result) is Signal.WARN_REPEAT:
            text += _REPEAT_WARNING
        messages.append(Message.tool(call.id, text, call.name))


def run_tool_call(call: ToolCall, deps: Deps, mode: Mode, on_event: EventHandler) -> ToolResult:
    """Validate one call, check the guardrails, ask the user if needed, then run the tool.

    Every failure becomes a ToolResult the model can read and react to; nothing raises.
    """
    tool = deps.tools.get(call.name)
    if tool is None:
        known = ", ".join(deps.tools.names())
        return ToolResult.error(f"Unknown tool '{call.name}'. Available tools: {known}.")
    try:
        args = tool.args_model.model_validate(call.arguments)
    except ValidationError as err:
        return ToolResult.error(_invalid_arguments_message(tool, err))

    verdict = check_tool_call(tool, args, mode, deps.ctx)
    if verdict.decision is Decision.DENY:
        return ToolResult.error(f"Not allowed: {verdict.reason}")
    if verdict.decision is Decision.ASK:
        answer = deps.approver.approve(
            call, tool.preview(args, deps.ctx), tool.grant_scope(args, deps.ctx)
        )
        if answer.approval is Approval.DENY:
            return ToolResult.error(_declined_message(answer.instead))

    on_event(ToolStarted(call))
    return _execute(tool, args, deps)


def _execute(tool: Tool[Any], args: BaseModel, deps: Deps) -> ToolResult:
    try:
        return tool.run(args, deps.ctx)
    except Exception as err:  # A bug in one tool must not end the whole session.
        return ToolResult.error(f"{tool.name} failed unexpectedly: {err}")


def _declined_message(instead: str) -> str:
    if instead:
        return f'The user declined this action and said: "{instead}". Do that instead.'
    return "The user declined this action. Ask what they want instead."


def _invalid_arguments_message(tool: Tool[Any], err: ValidationError) -> str:
    problems = "; ".join(
        f"{'.'.join(str(part) for part in issue['loc']) or 'arguments'}: {issue['msg']}"
        for issue in err.errors()
    )
    return f"Invalid arguments for {tool.name}: {problems}. Expected: {tool.signature()}."


def _unreadable_call_message(errors: tuple[str, ...]) -> str:
    details = " ".join(errors)
    return f"Your tool call could not be read: {details} Call the tool again with valid JSON."


def _halted(
    reason: HaltReason, usage: Usage, deps: Deps, on_event: EventHandler, text: str = ""
) -> RunResult:
    message = _HALT_MESSAGES[reason].format(window=deps.brain.context_window)
    on_event(Halted(reason, message))
    return RunResult(usage, text, reason)
