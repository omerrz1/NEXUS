"""CLI entrypoint: argument parsing, wiring dependencies, and dispatching modes."""

import argparse
import sys
from dataclasses import replace

from rich.console import Console

import nexus
from nexus.brain.base import Depth
from nexus.brain.openai_compat import OpenAIBrain
from nexus.cli.doctor import run_doctor
from nexus.cli.oneshot import run_oneshot
from nexus.cli.repl import run_repl
from nexus.cli.settings import SETTINGS_PATH, Settings, load_settings
from nexus.guardrails.modes import Mode
from nexus.tools.registry import default_registry


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for the Nexus executable."""
    parser = argparse.ArgumentParser(
        prog="nexus",
        description="Nexus: A local-first coding agent for the terminal.",
    )
    parser.add_argument("-v", "--version", action="version", version=f"nexus {nexus.__version__}")
    parser.add_argument(
        "-p", "--prompt", type=str, default=None, help="Execute a single prompt non-interactively."
    )
    parser.add_argument(
        "--model", type=str, default="nexus-qwen", help="Target model name in local runtime."
    )
    parser.add_argument(
        "--base-url",
        type=str,
        default="http://127.0.0.1:11434/v1",
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
        "--no-anim", action="store_true", help="Disable the animated startup banner."
    )

    subparsers = parser.add_subparsers(dest="subcommand", required=False)
    subparsers.add_parser("doctor", help="Run environment and model connectivity diagnostics.")

    return parser.parse_args(argv)


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
            timeout_sec=120.0,
        )
    except Exception as err:
        console.print(f"[bold red]Configuration error:[/bold red] {err}")
        sys.exit(1)

    settings = _apply_flags(load_settings(), args)
    if args.prompt is not None:
        code = run_oneshot(args.prompt, brain, depth=settings.depth)
        sys.exit(code)

    run_repl(
        brain=brain,
        tools=default_registry(),
        settings=settings,
        settings_path=SETTINGS_PATH,
        model_name=args.model,
        base_url=args.base_url,
        animate_banner=not args.no_anim,
        console=console,
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
