"""Interactive REPL session for conversational interaction with the local model."""

import time

from rich.console import Console

from nexus.brain.base import Brain
from nexus.cli.render import CliRenderer
from nexus.cli.slash import handle_slash_command
from nexus.messages import Message


def run_repl(
    brain: Brain,
    model_name: str = "nexus-qwen",
    base_url: str = "http://127.0.0.1:11434/v1",
    mode: str = "ask",
    animate_banner: bool = True,
    console: Console | None = None,
) -> None:
    """Launch the interactive REPL with blue styling, banner animation, and streaming."""
    out = CliRenderer(console=console)
    out.print_banner(animate=animate_banner)
    out.print_hud(model=model_name, base_url=base_url, mode=mode, tokens=0, speed=0.0)

    out.console.print(
        "[dim]Type your prompt or [bold cyan]/help[/bold cyan] for commands.\n"
        "Press [bold cyan]Ctrl-C[/bold cyan] to cancel, "
        "[bold cyan]Ctrl-D[/bold cyan] to exit.[/dim]\n"
    )

    messages: list[Message] = [
        Message.system(
            "You are Nexus, a local-first coding assistant. "
            "You operate with a local model, local tools, and zero network access. "
            "Be concise, direct, and helpful."
        )
    ]
    total_tokens = 0
    turns_count = 0
    latest_speed = 0.0

    while True:
        try:
            clock = time.strftime("%H:%M")
            user_input = out.console.input(
                f"[bold #0096c7]╭─[/bold #0096c7] [bold #70d6ff]you[/bold #70d6ff] "
                f"[dim]({clock})[/dim]\n"
                "[bold #0096c7]╰─[/bold #0096c7] [bold #00b4d8]›[/bold #00b4d8] "
            ).strip()
        except KeyboardInterrupt:
            out.console.print("\n[dim]Cancelled turn.[/dim]\n")
            continue
        except EOFError:
            out.console.print("\n[bold #70d6ff]Session closed. Goodbye![/bold #70d6ff]")
            break

        if not user_input:
            continue

        if user_input.startswith("/"):
            context = {
                "model": model_name,
                "base_url": base_url,
                "mode": mode,
                "tokens": total_tokens,
                "turns": turns_count,
                "speed": latest_speed,
                "context_window": brain.context_window,
                "renderer": out,
            }
            should_exit = handle_slash_command(user_input, context, out.console)
            if should_exit:
                break
            continue

        messages.append(Message.user(user_input))
        out.start_stream()

        try:
            reply = brain.chat(
                messages,
                on_delta=out.print_chunk,
                on_reasoning=out.print_reasoning_chunk,
            )
            latest_speed = out.end_stream()
            messages.append(reply.message)
            total_tokens += reply.usage.total_tokens
            turns_count += 1

            if reply.tool_calls:
                for call in reply.tool_calls:
                    out.print_tool_call(call.name, call.arguments)
        except KeyboardInterrupt:
            out.end_stream()
            out.console.print("[dim]Interrupted model generation.[/dim]\n")
        except Exception as err:
            out.end_stream()
            out.print_error(f"Inference error: {err}\n")
