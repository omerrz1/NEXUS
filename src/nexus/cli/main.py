"""CLI entrypoint: argument parsing, wiring dependencies, and dispatching modes."""

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from rich.console import Console

import nexus
from nexus.brain.base import DEFAULT_BASE_URL, DEFAULT_CONTEXT_WINDOW, DEFAULT_MODEL, Depth
from nexus.brain.openai_compat import OpenAIBrain
from nexus.cli.approve import CliApprover
from nexus.cli.doctor import run_doctor
from nexus.cli.oneshot import run_oneshot
from nexus.cli.repl import run_repl
from nexus.cli.settings import SETTINGS_PATH, Settings, load_settings
from nexus.guardrails.modes import Mode
from nexus.loop import Deps
from nexus.session.memory import SessionMemory
from nexus.session.store import SessionStore
from nexus.tools.base import ToolContext
from nexus.tools.registry import default_registry


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for the Nexus executable."""
    parser = argparse.ArgumentParser(
        prog="nexus",
        description="Nexus: A local-first AI agent for the terminal.",
    )
    parser.add_argument("-v", "--version", action="version", version=f"nexus {nexus.__version__}")
    parser.add_argument(
        "-p", "--prompt", type=str, default=None, help="Execute a single prompt non-interactively."
    )
    parser.add_argument(
        "--model", type=str, default=DEFAULT_MODEL, help="Model name on the local server."
    )
    parser.add_argument(
        "--base-url",
        type=str,
        default=DEFAULT_BASE_URL,
        help="Local loopback API base URL.",
    )
    parser.add_argument(
        "--mode",
        type=Mode,
        choices=list(Mode),
        default=None,
        help="Permission mode (read-only, ask, auto). Defaults to your saved setting.",
    )
    parser.add_argument(
        "--depth",
        type=Depth,
        choices=list(Depth),
        default=None,
        help="How long the model thinks before answering: fast (no thinking), "
        "balanced (model default), deep (slowest). Defaults to your saved setting.",
    )
    parser.add_argument(
        "--context-window",
        type=int,
        default=DEFAULT_CONTEXT_WINDOW,
        help="Context size in tokens that the model server runs with. Nexus sizes tool "
        "output and old history to fit it, and corrects it if a reply is cut off.",
    )
    parser.add_argument(
        "--no-anim", action="store_true", help="Disable the animated startup banner."
    )
    parser.add_argument(
        "--resume",
        nargs="?",
        const="",
        default=None,
        metavar="SESSION",
        help="Continue a saved session: its number or id from /sessions. With no value, "
        "continues the latest session started in this folder.",
    )

    subparsers = parser.add_subparsers(dest="subcommand", required=False)
    subparsers.add_parser("doctor", help="Run environment and model connectivity diagnostics.")

    args = parser.parse_args(argv)
    if args.resume is not None and args.prompt is not None:
        parser.error("--resume works only in the interactive session, not with -p")
    return args


def main(argv: list[str] | None = None) -> None:
    """Wire dependencies by hand and run the requested CLI mode."""
    args = parse_args(argv)
    console = Console()

    if args.subcommand == "doctor":
        success = run_doctor(base_url=args.base_url, model=args.model, console=console)
        sys.exit(0 if success else 1)

    try:
        brain = OpenAIBrain(
            base_url=args.base_url,
            model=args.model,
            context_window=args.context_window,
            timeout_sec=120.0,
        )
    except Exception as err:
        console.print(f"[bold red]Configuration error:[/bold red] {err}")
        sys.exit(1)

    settings = _apply_flags(load_settings(), args)
    deps = _build_deps(brain, console)
    if args.prompt is not None:
        code = run_oneshot(args.prompt, deps, depth=settings.depth, mode=settings.mode)
        sys.exit(code)

    run_repl(
        deps=deps,
        settings=settings,
        settings_path=SETTINGS_PATH,
        model_name=args.model,
        base_url=args.base_url,
        animate_banner=not args.no_anim,
        console=console,
        store=SessionStore(),
        resume=args.resume,
    )


def _build_deps(brain: OpenAIBrain, console: Console) -> Deps:
    """Wire the agent loop's parts together by hand."""
    memory = SessionMemory()  # Shared: the memory tools change it, and compaction reads it.
    return Deps(
        brain=brain,
        tools=default_registry(memory),
        approver=CliApprover(console),
        ctx=ToolContext.for_window(Path.cwd(), brain.context_window),
        memory=memory,
    )


def _apply_flags(saved: Settings, args: argparse.Namespace) -> Settings:
    """Command-line flags win over saved settings, but only for this run."""
    return replace(
        saved,
        mode=args.mode or saved.mode,
        depth=args.depth or saved.depth,
    )


if __name__ == "__main__":
    main()
