"""Tests for the server probe and git branch lookup behind the details card."""

import json
import subprocess
from pathlib import Path

import httpx

from nexus.cli.status import ServerStatus, current_git_branch, probe_server

URL = "http://127.0.0.1:11434/v1"


def client_returning(response: httpx.Response) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(lambda request: response))


def models_response(*names: str) -> httpx.Response:
    return httpx.Response(200, content=json.dumps({"data": [{"id": name} for name in names]}))


def test_probe_finds_the_model_even_with_a_latest_tag() -> None:
    client = client_returning(models_response("nexus-qwen:latest", "other:7b"))
    status = probe_server(URL, "nexus-qwen", client=client)
    assert status.online and status.model_found


def test_probe_reports_a_missing_model() -> None:
    status = probe_server(URL, "nexus-qwen", client=client_returning(models_response("other:7b")))
    assert status.online and not status.model_found


def test_probe_treats_errors_and_bad_replies_as_offline() -> None:
    for response in (httpx.Response(500), httpx.Response(200, content=b"not json")):
        assert probe_server(URL, "m", client=client_returning(response)) == ServerStatus(False)


def test_probe_never_contacts_a_non_local_address() -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise AssertionError("a request was sent")

    client = httpx.Client(transport=httpx.MockTransport(fail))
    assert probe_server("https://api.example.com/v1", "m", client=client).online is False


def test_current_git_branch(tmp_path: Path) -> None:
    assert current_git_branch(tmp_path) is None
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "symbolic-ref", "HEAD", "refs/heads/trunk"], cwd=tmp_path, check=True)
    assert current_git_branch(tmp_path) == "trunk"
