"""Searches the web through DuckDuckGo's plain-HTML results page and reads the results from it."""

from dataclasses import dataclass
from enum import Enum, auto
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlparse

import httpx

SEARCH_URL = "https://html.duckduckgo.com/html/"

# The HTML page is meant for browsers, so the request says it comes from one.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.0 Safari/605.1.15"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


@dataclass(frozen=True)
class SearchResult:
    """One organic search result."""

    title: str
    url: str
    snippet: str


def search_duckduckgo(
    query: str, client: httpx.Client, max_results: int
) -> list[SearchResult] | None:
    """Search and return up to `max_results` results.

    Returns an empty list when nothing matched, and None when DuckDuckGo answered with
    something that is not a results page (for example, it is limiting requests). Network
    failures raise httpx.HTTPError; the tool turns them into a message for the model.
    """
    response = client.post(SEARCH_URL, data={"q": query}, headers=_HEADERS)
    response.raise_for_status()
    results = parse_results(response.text)
    return None if results is None else results[:max_results]


def parse_results(html: str) -> list[SearchResult] | None:
    """Read the results out of a results page. None means the page is not a results page."""
    parser = _ResultsParser()
    parser.feed(html)
    parser.close()
    results = parser.finish()
    if results or parser.saw_no_results_message:
        return results
    return None


class _Field(Enum):
    """The part of a result whose text is being collected."""

    TITLE = auto()
    SNIPPET = auto()


@dataclass
class _Draft:
    """A result still being read from the page."""

    url: str = ""
    title: str = ""
    snippet: str = ""


class _ResultsParser(HTMLParser):
    """Collects organic results and skips ads.

    Every result sits in a `<div class="result ...">`. Organic ones also carry the class
    `web-result`; ads carry `result--ad` and link to a tracking redirect, so a result without
    `web-result` is ignored along with everything inside it.
    """

    def __init__(self) -> None:
        super().__init__()
        self.saw_no_results_message = False
        self._results: list[SearchResult] = []
        self._current: _Draft | None = None
        self._collecting: _Field | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = (attributes.get("class") or "").split()
        if "no-results__message" in classes:
            self.saw_no_results_message = True
        if tag == "div" and "result" in classes:
            self._end_result()
            self._current = _Draft() if "web-result" in classes else None
        elif tag == "a" and self._current is not None:
            if "result__a" in classes:
                self._current.url = _real_url(attributes.get("href") or "")
                self._collecting = _Field.TITLE
            elif "result__snippet" in classes:
                self._collecting = _Field.SNIPPET

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self._collecting = None

    def handle_data(self, data: str) -> None:
        if self._current is None:
            return
        if self._collecting is _Field.TITLE:
            self._current.title += data
        elif self._collecting is _Field.SNIPPET:
            self._current.snippet += data

    def finish(self) -> list[SearchResult]:
        """Close the last result and return all of them, in page order."""
        self._end_result()
        return self._results

    def _end_result(self) -> None:
        draft, self._current, self._collecting = self._current, None, None
        if draft is None or not draft.url or not draft.title.strip():
            return
        self._results.append(
            SearchResult(_tidy(draft.title), draft.url, _tidy(draft.snippet)),
        )


def _tidy(text: str) -> str:
    """Collapse the runs of whitespace and newlines that HTML leaves behind."""
    return " ".join(text.split())


def _real_url(href: str) -> str:
    """Return the address a result link points to.

    DuckDuckGo sometimes wraps links in its own redirect, which carries the real address in
    the `uddg` parameter, and sometimes writes them without a scheme.
    """
    wrapped = parse_qs(urlparse(href).query).get("uddg")
    if wrapped:
        return wrapped[0]
    return f"https:{href}" if href.startswith("//") else href
