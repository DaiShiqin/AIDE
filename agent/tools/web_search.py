from __future__ import annotations

import json
import os
from html.parser import HTMLParser
from typing import Any, Dict, Iterable, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

from agent.config import AgentConfig
from agent.models import ToolResult


DEFAULT_MAX_RESULTS = 5
DEFAULT_TIMEOUT = 15


def _get_config_value(
    config: AgentConfig,
    attr_names: Iterable[str],
    env_names: Iterable[str] = (),
    default: Optional[Any] = None,
) -> Optional[Any]:
    """Read value from AgentConfig first, then environment variables.

    This keeps the search tool compatible with different AgentConfig field names.
    """
    for name in attr_names:
        value = getattr(config, name, None)
        if value not in (None, ""):
            return value

    for name in env_names:
        value = os.getenv(name)
        if value not in (None, ""):
            return value

    return default


def _get_int_config(
    config: AgentConfig,
    attr_names: Iterable[str],
    env_names: Iterable[str] = (),
    default: int = DEFAULT_MAX_RESULTS,
) -> int:
    value = _get_config_value(config, attr_names, env_names, default)
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _clean_text(value: Optional[str]) -> str:
    if not value:
        return ""
    return " ".join(str(value).replace("\n", " ").replace("\t", " ").split())


def _normalize_result(
    title: Optional[str],
    url: Optional[str],
    snippet: Optional[str],
    source: str,
    score: Optional[float] = None,
    position: Optional[int] = None,
) -> Dict[str, Any]:
    item: Dict[str, Any] = {
        "title": _clean_text(title),
        "url": _clean_text(url),
        "snippet": _clean_text(snippet),
        "source": source,
    }
    if score is not None:
        item["score"] = score
    if position is not None:
        item["position"] = position
    return item


def _request_json(
    url: str,
    *,
    method: str = "GET",
    payload: Optional[Dict[str, Any]] = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> Dict[str, Any]:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; AgentWebSearch/1.0)",
        "Accept": "application/json",
    }

    body: Optional[bytes] = None
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = Request(url, data=body, headers=headers, method=method)

    try:
        with urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            text = response.read().decode(charset, errors="replace")
            return json.loads(text)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"网络连接失败: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"搜索服务返回内容不是合法 JSON: {exc}") from exc


def _tavily_search(query: str, config: AgentConfig, max_results: int, timeout: int) -> ToolResult:
    api_key = _get_config_value(
        config,
        attr_names=(
            "tavily_api_key",
            "web_search_api_key",
            "web_search_tavily_api_key",
        ),
        env_names=("TAVILY_API_KEY", "WEB_SEARCH_API_KEY"),
    )
    if not api_key:
        return ToolResult(
            tool="web_search",
            ok=False,
            summary="Tavily 搜索缺少 API Key，请配置 TAVILY_API_KEY 或 config.tavily_api_key。",
            data={"query": query, "provider": "tavily", "results": []},
        )

    search_depth = _get_config_value(
        config,
        attr_names=("tavily_search_depth", "web_search_depth"),
        env_names=("TAVILY_SEARCH_DEPTH", "WEB_SEARCH_DEPTH"),
        default="basic",
    )

    payload = {
        "api_key": api_key,
        "query": query,
        "search_depth": search_depth,
        "max_results": max_results,
        "include_answer": True,
        "include_raw_content": False,
    }
    response = _request_json(
        "https://api.tavily.com/search",
        method="POST",
        payload=payload,
        timeout=timeout,
    )

    results: List[Dict[str, Any]] = []
    for idx, item in enumerate(response.get("results") or [], start=1):
        result = _normalize_result(
            title=item.get("title"),
            url=item.get("url"),
            snippet=item.get("content") or item.get("snippet"),
            source="tavily",
            score=item.get("score"),
            position=idx,
        )
        if result["url"]:
            results.append(result)

    answer = _clean_text(response.get("answer"))
    summary = answer or f"Tavily 检索完成，共返回 {len(results)} 条结果。"

    return ToolResult(
        tool="web_search",
        ok=True,
        summary=summary,
        data={
            "query": query,
            "provider": "tavily",
            "answer": answer,
            "results": results,
        },
    )


def _serpapi_search(query: str, config: AgentConfig, max_results: int, timeout: int) -> ToolResult:
    api_key = _get_config_value(
        config,
        attr_names=(
            "serpapi_api_key",
            "serp_api_key",
            "web_search_api_key",
            "web_search_serpapi_api_key",
        ),
        env_names=("SERPAPI_API_KEY", "SERP_API_KEY", "WEB_SEARCH_API_KEY"),
    )
    if not api_key:
        return ToolResult(
            tool="web_search",
            ok=False,
            summary="SerpAPI 搜索缺少 API Key，请配置 SERPAPI_API_KEY 或 config.serpapi_api_key。",
            data={"query": query, "provider": "serpapi", "results": []},
        )

    params = {
        "engine": "google",
        "q": query,
        "api_key": api_key,
        "num": max_results,
    }
    url = "https://serpapi.com/search.json?" + urlencode(params)
    response = _request_json(url, timeout=timeout)

    results: List[Dict[str, Any]] = []
    for idx, item in enumerate(response.get("organic_results") or [], start=1):
        result = _normalize_result(
            title=item.get("title"),
            url=item.get("link"),
            snippet=item.get("snippet"),
            source="serpapi",
            position=item.get("position") or idx,
        )
        if result["url"]:
            results.append(result)

    summary = f"SerpAPI 检索完成，共返回 {len(results)} 条自然搜索结果。"
    return ToolResult(
        tool="web_search",
        ok=True,
        summary=summary,
        data={"query": query, "provider": "serpapi", "results": results},
    )


def _unwrap_duckduckgo_url(url: str) -> str:
    """DuckDuckGo HTML results sometimes wrap target URLs in /l/?uddg=..."""
    if not url:
        return ""
    parsed = urlparse(url)
    if parsed.path.startswith("/l/"):
        uddg = parse_qs(parsed.query).get("uddg")
        if uddg:
            return uddg[0]
    return url


class _DuckDuckGoHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: List[Dict[str, Any]] = []
        self._current: Optional[Dict[str, Any]] = None
        self._in_title = False
        self._in_snippet = False

    def handle_starttag(self, tag: str, attrs: List[tuple[str, Optional[str]]]) -> None:
        attrs_dict = {key: value or "" for key, value in attrs}
        class_name = attrs_dict.get("class", "")

        if tag == "a" and "result__a" in class_name:
            if self._current and self._current.get("title") and self._current.get("url"):
                self.results.append(self._current)
            self._current = {
                "title": "",
                "url": _unwrap_duckduckgo_url(attrs_dict.get("href", "")),
                "snippet": "",
                "source": "duckduckgo",
            }
            self._in_title = True

        if tag in ("a", "div") and "result__snippet" in class_name:
            self._in_snippet = True

    def handle_data(self, data: str) -> None:
        if not self._current:
            return
        if self._in_title:
            self._current["title"] = _clean_text(
                f"{self._current.get('title', '')} {data}"
            )
        elif self._in_snippet:
            self._current["snippet"] = _clean_text(
                f"{self._current.get('snippet', '')} {data}"
            )

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_title:
            self._in_title = False
        if tag in ("a", "div") and self._in_snippet:
            self._in_snippet = False

    def close(self) -> None:
        super().close()
        if self._current and self._current.get("title") and self._current.get("url"):
            self.results.append(self._current)
            self._current = None


def _duckduckgo_search_by_package(query: str, max_results: int) -> Optional[List[Dict[str, Any]]]:
    """Use installed DuckDuckGo client if available; otherwise return None."""
    DDGS = None
    try:
        from ddgs import DDGS as _DDGS  # type: ignore

        DDGS = _DDGS
    except Exception:
        try:
            from duckduckgo_search import DDGS as _DDGS  # type: ignore

            DDGS = _DDGS
        except Exception:
            DDGS = None

    if DDGS is None:
        return None

    results: List[Dict[str, Any]] = []
    with DDGS() as ddgs:
        for idx, item in enumerate(ddgs.text(query, max_results=max_results), start=1):
            result = _normalize_result(
                title=item.get("title"),
                url=item.get("href") or item.get("url"),
                snippet=item.get("body") or item.get("snippet"),
                source="duckduckgo",
                position=idx,
            )
            if result["url"]:
                results.append(result)
    return results


def _duckduckgo_search_by_html(query: str, max_results: int, timeout: int) -> List[Dict[str, Any]]:
    url = "https://html.duckduckgo.com/html/?" + urlencode({"q": query})
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; AgentWebSearch/1.0)",
            "Accept": "text/html,application/xhtml+xml",
        },
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            html = response.read().decode(charset, errors="replace")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"网络连接失败: {exc.reason}") from exc

    parser = _DuckDuckGoHTMLParser()
    parser.feed(html)
    parser.close()

    return parser.results[:max_results]


def _duckduckgo_search(query: str, config: AgentConfig, max_results: int, timeout: int) -> ToolResult:
    results = _duckduckgo_search_by_package(query, max_results)
    if results is None:
        results = _duckduckgo_search_by_html(query, max_results, timeout)

    if not results:
        return ToolResult(
            tool="web_search",
            ok=False,
            summary="DuckDuckGo 已执行检索，但当前查询没有返回可用结果。建议改写查询词，或切换到 Tavily / SerpAPI。",
            data={"query": query, "provider": "duckduckgo", "results": []},
        )

    summary = f"DuckDuckGo 检索完成，共返回 {len(results)} 条结果。"
    return ToolResult(
        tool="web_search",
        ok=True,
        summary=summary,
        data={"query": query, "provider": "duckduckgo", "results": results},
    )


def web_search(query: str, config: AgentConfig) -> ToolResult:
    provider = (config.web_search_provider or "stub").lower().strip()
    query = _clean_text(query)

    if not query:
        return ToolResult(
            tool="web_search",
            ok=False,
            summary="搜索 query 不能为空。",
            data={"query": query, "provider": provider, "results": []},
        )

    max_results = _get_int_config(
        config,
        attr_names=("web_search_max_results", "search_max_results", "max_search_results"),
        env_names=("WEB_SEARCH_MAX_RESULTS", "SEARCH_MAX_RESULTS"),
        default=DEFAULT_MAX_RESULTS,
    )
    max_results = max(1, min(max_results, 20))

    timeout = _get_int_config(
        config,
        attr_names=("web_search_timeout", "search_timeout"),
        env_names=("WEB_SEARCH_TIMEOUT", "SEARCH_TIMEOUT"),
        default=DEFAULT_TIMEOUT,
    )
    timeout = max(3, min(timeout, 60))

    if provider == "stub":
        return ToolResult(
            tool="web_search",
            ok=True,
            summary=(
                "联网搜索工具当前为 stub 模式。已记录查询意图；如需真实搜索，"
                "请配置 WEB_SEARCH_PROVIDER 为 tavily、serpapi 或 duckduckgo。"
            ),
            data={"query": query, "provider": provider, "results": []},
        )

    try:
        if provider == "tavily":
            return _tavily_search(query, config, max_results, timeout)

        if provider == "serpapi":
            return _serpapi_search(query, config, max_results, timeout)

        if provider in {"duckduckgo", "ddg"}:
            return _duckduckgo_search(query, config, max_results, timeout)

        return ToolResult(
            tool="web_search",
            ok=False,
            summary=f"暂未实现的搜索提供方：{provider}",
            data={"query": query, "provider": provider, "results": []},
        )

    except Exception as exc:
        return ToolResult(
            tool="web_search",
            ok=False,
            summary=f"{provider} 检索失败：{exc}",
            data={"query": query, "provider": provider, "results": []},
        )
