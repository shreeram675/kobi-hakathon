"""Retrieval planning, quality gates, and chunking stubs."""

from __future__ import annotations

from schemas import PageRef, ProgramIdentity, SearchQuery


SOURCE_TYPES = ("official", "terms", "faq", "partners", "app_reviews", "news", "forums")


def build_search_queries(identity: ProgramIdentity) -> list[SearchQuery]:
    name = identity.program_name
    brand = identity.brand
    return [
        SearchQuery(query=f"{name} official loyalty program", source_type="official"),
        SearchQuery(query=f"{name} terms and conditions", source_type="terms"),
        SearchQuery(query=f"{name} earn redeem points FAQ", source_type="faq"),
        SearchQuery(query=f"{name} partners {brand}", source_type="partners"),
        SearchQuery(query=f"{name} app reviews rating", source_type="app_reviews"),
        SearchQuery(query=f"{name} recent changes loyalty program", source_type="news"),
        SearchQuery(query=f"{name} review forum complaints", source_type="forums"),
    ]


def passes_zero_result_gate(pages: list[PageRef]) -> bool:
    usable = [page for page in pages if page.token_count > 150 and page.cleaned_text.strip()]
    return len(usable) >= 2
