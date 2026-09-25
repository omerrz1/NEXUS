"""Tests for web search: reading DuckDuckGo's results page, and the tool around it.

The pages below copy the structure of real responses. The tool is tested over a mock
transport, so no test ever touches the network.
"""

from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import ValidationError

from nexus.tools.base import Risk, ToolContext
from nexus.tools.builtin.web_search import WebSearch, WebSearchArgs
from nexus.tools.web.duckduckgo import SEARCH_URL, parse_results, search_duckduckgo

ORGANIC = """
<div class="result results_links results_links_deep web-result ">
  <div class="links_main links_deep result__body">
    <h2 class="result__title">
      <a rel="nofollow" class="result__a" href="{url}">{title}</a>
    </h2>
    <div class="result__extras"><div class="result__extras__url">
      <a class="result__url" href="{url}">shown-address.example</a>
    </div></div>
    <a class="result__snippet" href="{url}">{snippet}</a>
    <div class="clear"></div>
  </div>
</div>
"""

AD = """
<div class="result results_links results_links_deep result--ad ">
  <h2 class="result__title">
    <a rel="nofollow" class="result__a"
       href="https://duckduckgo.com/y.js?ad_domain=shop.example&amp;click_metadata=abc">Buy now!</a>
  </h2>
  <a class="result__snippet" href="https://duckduckgo.com/y.js?ad=1">Cheap, cheap, cheap</a>
</div>
"""


def page(*blocks: str) -> str:
    return f'<html><body><div class="results">{"".join(blocks)}</div></body></html>'


def organic(title: str, url: str, snippet: str = "A snippet.") -> str:
    return ORGANIC.format(title=title, url=url, snippet=snippet)


NO_RESULTS = page(
    '<div class="no-results__container result__title">'
    '<div class="no-results__message">No results found for <b>zzz</b>.</div></div>'
)
CHALLENGE = (
    "<html><body><div class='anomaly-modal'>Please complete the challenge</div></body></html>"
)


# ---- reading the page


def test_organic_results_are_read_in_order() -> None:
    html = page(
        organic("First", "https://one.example/a", "About one."),
        organic("Second", "https://two.example/b", "About two."),
    )
    results = parse_results(html)
    assert results is not None
    assert [(r.title, r.url, r.snippet) for r in results] == [
        ("First", "https://one.example/a", "About one."),
        ("Second", "https://two.example/b", "About two."),
    ]


def test_ads_are_skipped_entirely() -> None:
    html = page(AD, organic("Real", "https://real.example"), AD)
    results = parse_results(html)
    assert results is not None and [r.title for r in results] == ["Real"]
    assert "y.js" not in str(results)


def test_an_ad_after_a_result_does_not_leak_into_it() -> None:
    html = page(organic("Real", "https://real.example", "Real snippet."), AD)
    results = parse_results(html)
    assert results is not None and len(results) == 1
    assert results[0].snippet == "Real snippet."  # not "Cheap, cheap, cheap"


def test_redirect_links_are_unwrapped_and_bare_links_get_a_scheme() -> None:
    wrapped = "//duckduckgo.com/l/?uddg=https%3A%2F%2Ftarget.example%2Fpage%3Fq%3D1&rut=abc"
    html = page(organic("Wrapped", wrapped), organic("Bare", "//bare.example/x"))
    results = parse_results(html)
    assert results is not None
    assert [r.url for r in results] == ["https://target.example/page?q=1", "https://bare.example/x"]


def test_markup_entities_and_whitespace_in_text_are_cleaned_up() -> None:
    html = page(
        organic(
            "  Tom &amp; Jerry\n     — the   show ",
            "https://tv.example",
            "Learn <b>how</b> to\n   watch it &mdash; free &lt;3",
        )
    )
    results = parse_results(html)
    assert results is not None
    assert results[0].title == "Tom & Jerry — the show"
    assert results[0].snippet == "Learn how to watch it — free <3"


def test_a_result_with_no_snippet_still_counts() -> None:
    html = page(
        '<div class="result web-result"><a class="result__a" href="https://x.example">X</a></div>'
    )
    results = parse_results(html)
    assert results is not None and results[0].snippet == ""


def test_a_page_saying_no_results_gives_an_empty_list_not_an_error() -> None:
    assert parse_results(NO_RESULTS) == []


@pytest.mark.parametrize("html", [CHALLENGE, "", "<html></html>", "not html at all"])
def test_a_page_that_is_not_a_results_page_gives_none(html: str) -> None:
    assert parse_results(html) is None


# ---- asking DuckDuckGo


class Recorder:
    """A mock server that answers every request the same way and remembers the requests."""

    def __init__(self, html: str, status: int = 200) -> None:
        self.requests: list[httpx.Request] = []
        self.html, self.status = html, status

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self._answer))

    def _answer(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status, text=self.html)


def test_the_search_is_a_form_post_that_looks_like_a_browser() -> None:
    server = Recorder(page(organic("A", "https://a.example")))
    search_duckduckgo("python dataclasses", server.client(), max_results=5)

    (request,) = server.requests
    assert request.method == "POST" and str(request.url) == SEARCH_URL
    assert parse_qs(request.content.decode()) == {"q": ["python dataclasses"]}
    assert request.headers["User-Agent"].startswith("Mozilla/5.0")


def test_only_the_requested_number_of_results_is_returned() -> None:
    html = page(*(organic(f"R{n}", f"https://r{n}.example") for n in range(8)))
    results = search_duckduckgo("q", Recorder(html).client(), max_results=3)
    assert results is not None and [r.title for r in results] == ["R0", "R1", "R2"]


def test_a_challenge_page_is_reported_as_unreadable_not_as_no_results() -> None:
    assert search_duckduckgo("q", Recorder(CHALLENGE, 202).client(), max_results=5) is None


# ---- the tool


@pytest.fixture
def ctx(tmp_path: Path) -> ToolContext:
    return ToolContext.for_window(tmp_path, 16384)


def run_search(server: Recorder, ctx: ToolContext, **arguments: object):  # type: ignore[no-untyped-def]
    tool = WebSearch(client=server.client())
    return tool.run(WebSearchArgs(**arguments), ctx)  # type: ignore[arg-type]


def test_the_tool_lists_numbered_results_with_links_and_snippets(ctx: ToolContext) -> None:
    html = page(
        organic("First", "https://one.example", "About one."),
        organic("Second", "https://two.example", "About two."),
    )
    result = run_search(Recorder(html), ctx, query="things")
    assert result.ok
    assert result.output == (
        "1. First\n   https://one.example\n   About one.\n\n"
        "2. Second\n   https://two.example\n   About two."
    )


def test_no_results_is_a_normal_answer_the_model_can_act_on(ctx: ToolContext) -> None:
    result = run_search(Recorder(NO_RESULTS), ctx, query="zzz")
    assert result.ok and 'No results for "zzz"' in result.output


def test_a_blocked_search_tells_the_model_to_wait_or_answer_without_it(ctx: ToolContext) -> None:
    result = run_search(Recorder(CHALLENGE, 202), ctx, query="q")
    assert not result.ok and "limiting requests" in result.output


def test_server_errors_and_dead_connections_are_messages_not_crashes(ctx: ToolContext) -> None:
    result = run_search(Recorder("oops", 500), ctx, query="q")
    assert not result.ok and "search failed" in result.output and "500" in result.output

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    tool = WebSearch(client=httpx.Client(transport=httpx.MockTransport(refuse)))
    down = tool.run(WebSearchArgs(query="q"), ctx)
    assert not down.ok and "no route to host" in down.output


def test_a_timeout_with_no_message_still_says_what_happened(ctx: ToolContext) -> None:
    def too_slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("")

    tool = WebSearch(client=httpx.Client(transport=httpx.MockTransport(too_slow)))
    result = tool.run(WebSearchArgs(query="q"), ctx)
    assert not result.ok and "ReadTimeout" in result.output


def test_long_result_lists_are_capped_for_a_small_context(tmp_path: Path) -> None:
    html = page(*(organic(f"R{n}", f"https://r{n}.example", "word " * 60) for n in range(10)))
    small = ToolContext.for_window(tmp_path, 2000)  # 1000 bytes of output at most
    result = run_search(Recorder(html), small, query="q", max_results=10)
    assert result.ok and result.truncated and "output cut" in result.output


def test_the_approval_prompt_shows_exactly_what_will_be_sent(ctx: ToolContext) -> None:
    tool = WebSearch()
    preview = tool.preview(WebSearchArgs(query="my secret project name"), ctx)
    assert preview is not None and preview.title == "Search the web"
    assert "my secret project name" in preview.body and "DuckDuckGo" in preview.body
    assert tool.risk is Risk.NETWORK


def test_arguments_are_validated_for_small_models() -> None:
    with pytest.raises(ValidationError):
        WebSearchArgs(query="")
    with pytest.raises(ValidationError):
        WebSearchArgs(query="x" * 201)
    with pytest.raises(ValidationError):
        WebSearchArgs(query="q", max_results=11)
    assert WebSearchArgs(query="q").max_results == 5
