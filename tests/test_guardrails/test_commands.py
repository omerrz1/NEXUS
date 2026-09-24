"""Adversarial tests for the command rules: what is always refused and what needs no asking."""

from pathlib import Path

import pytest

from nexus.guardrails.commands import denied_reason, is_safe_command

WORKSPACE = Path.cwd().resolve()


@pytest.mark.parametrize(
    "command",
    [
        "sudo ls",
        "curl http://example.com",
        "ls; curl x",
        "ls && wget y",
        "cat a | ssh host",
        "FOO=1 curl x",
        "env curl x",
        "nohup curl x",
        "/usr/bin/curl x",
        "bash -c 'curl x'",
        "sh -c \"bash -c 'ssh host'\"",
        "eval 'sudo ls'",
        "git push",
        "git -C repo push origin main",
        "git -c user.name=x fetch",
        "git pull",
        "pip install requests",
        "npm i left-pad",
        "brew install jq",
        "dd if=x of=/dev/disk2",
        "mkfs.ext4 /dev/sda1",
        "echo 'unterminated",
    ],
)
def test_always_refused(command: str) -> None:
    assert denied_reason(command, WORKSPACE) is not None


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf /",
        "rm -fr /",
        "rm --recursive /",
        "rm -rf ~",
        "rm -rf ~/*",
        "rm -rf $HOME",
        "rm -rf ${HOME}/",
        "rm -rf .",
        "rm -rf ./",
        "rm -rf *",
        "rm -rf ..",
        f'rm -rf "{WORKSPACE.parent}"',
        f'rm -rf "{WORKSPACE}"',
    ],
)
def test_recursive_deletes_of_important_folders_are_refused(command: str) -> None:
    assert denied_reason(command, WORKSPACE) is not None


@pytest.mark.parametrize(
    "command",
    [
        "ls -la",
        "grep -r curl .",
        "echo sudo",
        "git status",
        "git commit -m 'push notifications'",
        "rm file.txt",
        "rm -rf build",
        "rm -rf ./build/output",
        "python -m pytest -q",
        "cat a | grep b",
    ],
)
def test_ordinary_commands_are_not_refused(command: str) -> None:
    assert denied_reason(command, WORKSPACE) is None


@pytest.mark.parametrize(
    "command",
    [
        *("ls -la", "pwd", "git status", "git diff HEAD", "git log --oneline"),
        *("find . -name '*.py'", "cat a.txt | grep x | wc -l", "echo hi", "grep -rn TODO src"),
    ],
)
def test_read_only_commands_need_no_approval(command: str) -> None:
    assert is_safe_command(command)


@pytest.mark.parametrize(
    "command",
    [
        "rm a",
        "ls > out.txt",
        "ls >> out.txt",
        "cat a; rm b",
        "ls && rm b",
        "ls || rm b",
        "ls &",
        "find . -delete",
        "find . -exec rm {} +",
        "git branch -D x",
        "git checkout .",
        "git commit -am x",
        "echo $(rm a)",
        "echo `rm a`",
        "cat <(rm a)",
        "FOO=1 ls",
        "sed -i s/a/b/ f",
        "python x.py",
        "cat a |",
        "",
    ],
)
def test_everything_else_needs_approval(command: str) -> None:
    assert not is_safe_command(command)
