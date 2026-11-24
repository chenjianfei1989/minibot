"""第二版记忆存储的搜索辅助函数。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SearchResult:
    uri: str
    title: str
    kind: str
    node_type: str | None
    matched_by: str
    snippet: str
    parent_uri: str | None


def normalize_query(query: str) -> str:
    """统一查询的大小写与空白，便于计算匹配。"""
    return " ".join(query.strip().lower().split())


def rank_search_results(query: str, documents: list[dict]) -> list[SearchResult]:
    """对候选记忆文档计算相关性，并返回排序后的命中结果。"""
    normalized = normalize_query(query)
    ranked: list[tuple[int, SearchResult]] = []
    for doc in documents:
        title = str(doc["title"])
        uri = str(doc["uri"])
        kind = str(doc["kind"])
        node_type = doc.get("node_type")
        search_text = str(doc.get("search_text") or "")
        triggers = [str(term) for term in doc.get("triggers") or []]
        title_norm = title.lower()
        uri_norm = uri.lower()
        search_norm = search_text.lower()

        score = -1
        matched_by = ""
        if any(normalize_query(term) == normalized for term in triggers):
            score = 400
            matched_by = "trigger"
        elif title_norm == normalized:
            score = 320
            matched_by = "title"
        elif normalized and normalized in title_norm:
            score = 260
            matched_by = "title"
        elif normalized and normalized in uri_norm:
            score = 220
            matched_by = "uri"
        elif normalized and normalized in search_norm:
            score = 150
            matched_by = "content"

        if score < 0:
            continue
        if kind == "memory":
            score += 10
        snippet_source = search_text or title
        snippet = snippet_source[:160]
        ranked.append(
            (
                score,
                SearchResult(
                    uri=uri,
                    title=title,
                    kind=kind,
                    node_type=node_type,
                    matched_by=matched_by,
                    snippet=snippet,
                    parent_uri=doc.get("parent_uri"),
                ),
            )
        )

    ranked.sort(key=lambda item: (-item[0], item[1].title))
    return [item[1] for item in ranked]
