"""Diagnostic tool checking local model server health, model availability, and tool calling."""

import time

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from nexus.brain.base import Depth
from nexus.brain.openai_compat import OpenAIBrain, is_loopback_url
from nexus.messages import Message, ToolSpec


def run_doctor(
    base_url: str = "http://127.0.0.1:11434/v1",
    model: str = "nexus-qwen",
    console: Console | None = None,
) -> bool:
    """Run comprehensive diagnostics on the local environment and model server."""
    out = console or Console()
    out.print(Panel("[bold #70d6ff]NEXUS SYSTEM DOCTOR[/bold #70d6ff]", border_style="#0096c7"))

    table = Table(border_style="#0077b6", header_style="bold #70d6ff")
    table.add_column("Diagnostic Check", style="white")
    table.add_column("Status", justify="center")
    table.add_column("Details", style="dim")

    all_passed = True

    # 1. Loopback Address Verification
    loopback_ok = is_loopback_url(base_url)
    table.add_row(
        "Loopback Isolation",
        "[bold green]PASS[/bold green]" if loopback_ok else "[bold red]FAIL[/bold red]",
        f"Server is strictly loopback: {base_url}",
    )
    if not loopback_ok:
        all_passed = False

    # 2. Server Connectivity
    brain = None
    start_time = time.perf_counter()
    try:
        brain = OpenAIBrain(base_url=base_url, model=model, timeout_sec=10.0)
        # 3. Model Streaming Probe
        reply = brain.chat(
            messages=[Message.user("Reply with only the single word: OK")],
            depth=Depth.FAST,  # the probes check that things work, not answer quality
        )
        latency = (time.perf_counter() - start_time) * 1000
        table.add_row(
            "Local Server Connectivity",
            "[bold green]PASS[/bold green]",
            f"Connected in {latency:.1f}ms",
        )
        table.add_row(
            f"Model '{model}' Inference",
            "[bold green]PASS[/bold green]",
            f"Response received ({reply.usage.total_tokens} tokens)",
        )
    except Exception as err:
        all_passed = False
        table.add_row(
            "Local Server Connectivity",
            "[bold red]FAIL[/bold red]",
            f"Could not reach server: {err}",
        )
        table.add_row(
            f"Model '{model}' Inference",
            "[bold yellow]SKIP[/bold yellow]",
            "Server down",
        )

    # 4. Tool Calling Verification
    if brain is not None:
        try:
            tool_spec = ToolSpec(
                name="ping_probe",
                description="A test tool probe",
                parameters={"type": "object", "properties": {"msg": {"type": "string"}}},
            )
            tool_reply = brain.chat(
                messages=[
                    Message.system("Call ping_probe tool with msg='test'."),
                    Message.user("Run ping_probe."),
                ],
                tools=[tool_spec],
                depth=Depth.FAST,
            )
            has_tools = len(tool_reply.tool_calls) > 0
            table.add_row(
                "Tool Call Protocol Support",
                "[bold green]PASS[/bold green]" if has_tools else "[bold yellow]WARN[/bold yellow]",
                "Native/fallback tool calling verified" if has_tools else "No tool calls generated",
            )
        except Exception as tool_err:
            table.add_row("Tool Call Protocol Support", "[bold red]FAIL[/bold red]", str(tool_err))

    out.print(table)
    summary_color = "green" if all_passed else "red"
    summary_text = (
        "All systems operational. Nexus is ready." if all_passed else "Diagnostics failed."
    )
    out.print(f"\n[bold {summary_color}]Doctor verdict:[/bold {summary_color}] {summary_text}\n")
    return all_passed
