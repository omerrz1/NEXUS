"""web_search: look something up on the web and return titles, links, and short snippets."""

import httpx
from pydantic import BaseModel, Field

from nexus.tools.base import Preview, Risk, Tool, ToolContext, ToolResult
from nexus.tools.output import cap_text
from nexus.tools.web.duckduckgo import SearchResult, search_duckduckgo

_REQUEST_TIMEOUT_SEC = 15.0


class WebSearchArgs(BaseModel):
    query: str = Field(min_length=1, max_length=200, description="What to search for.")
    max_results: int = Field(default=5, ge=1, le=10, description="How many results to return.")


class WebSearch(Tool[WebSearchArgs]):
    name = "web_search"
    description = (
        "Search the web with DuckDuckGo. Returns titles, links, and short snippets; "
        "it cannot open the pages themselves."
    )
    args_model = WebSearchArgs
    risk = Risk.NETWORK

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client

    def run(self, args: WebSearchArgs, ctx: ToolContext) -> ToolResult:
        if self._client is None:
            self._client = httpx.Client(timeout=_REQUEST_TIMEOUT_SEC, follow_redirects=True)
        try:
            results = search_duckduckgo(args.query, self._client, args.max_results)
        except httpx.HTTPError as err:
            return ToolResult.error(f"The web search failed: {str(err) or type(err).__name__}.")

        if results is None:
            return ToolResult.error(
                "DuckDuckGo did not return search results; it may be limiting requests. "
                "Try again in a minute, or answer without searching."
            )
        if not results:
            return ToolResult.success(f'No results for "{args.query}". Try different words.')
        text, truncated = cap_text(_format(results), ctx)
        return ToolResult.success(text, truncated)

    def preview(self, args: WebSearchArgs, ctx: ToolContext) -> Preview | None:
        """The exact text that will leave this computer."""
        note = "(this text is sent to DuckDuckGo)"
        return Preview("Search the web", body=f'"{args.query}"\n{note}')


def _format(results: list[SearchResult]) -> str:
    return "\n\n".join(
        f"{number}. {result.title}\n   {result.url}\n   {result.snippet}"
        for number, result in enumerate(results, start=1)
    )
