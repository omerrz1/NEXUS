"""CLI entrypoint: argument parsing, wiring dependencies, and dispatching modes."""

import argparse
import sys

from rich.console import Console

import nexus
from nexus.brain.openai_compat import OpenAIBrain
from nexus.cli.doctor import run_doctor
from nexus.cli.oneshot import run_oneshot
from nexus.cli.repl import run_repl


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
        type=str,
        choices=["read-only", "ask", "auto"],
        default="ask",
        help="Security mode (read-only, ask, auto).",
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

    if args.prompt is not None:
        code = run_oneshot(args.prompt, brain)
        sys.exit(code)

    run_repl(
        brain=brain,
        model_name=args.model,
        base_url=args.base_url,
        mode=args.mode,
        animate_banner=not args.no_anim,
        console=console,
    )


if __name__ == "__main__":
    main()
