"""
cascade_fetcher.py
Intelligent cascade downloader with 3-tier fallback:
  1. arXiv        → Open Science (free, legal, fast)
  2. Anna's/LibGen → Shadow Libraries (books, unavailable papers)
  3. Web Search    → "Garimpo na web" (catch-all for any remaining)

Supports two execution modes:
  - "dumb" (script mode): simple sequential cascade, no LLM needed
  - "react" (ReAct agent): uses an LLM to plan searches and route intelligently

Each fetcher returns a FetchResult so the cascade always knows
what succeeded, what failed, and why.
"""
import time
from result import FetchResult
from arxiv_fetcher import download_from_arxiv
from shadow_scraper import download_from_annas_archive, download_from_scihub
from web_search_fetcher import download_from_web_search


# ─────────────────────────────────────────────
# Script Mode  (dumb / sequential cascade)
# ─────────────────────────────────────────────

def run_cascade_script(
    query: str = None,
    arxiv_id: str = None,
    preferred_source: str = None,   # "arxiv" | "annas_archive" | None (tries all)
    max_results: int = 3,
    lang: str = "",
    doi: str = None,
    verbose: bool = True,
) -> FetchResult:
    """
    Dumb script-mode cascade. No LLM needed.
    Tries sources in order until we hit max_results.

    Args:
        query:        Natural-language search term
        arxiv_id:     Specific arXiv ID to fetch directly
        preferred_source: Force only one source (skip cascade)
        max_results:  Stop after this many files downloaded
        lang:         Language filter for Anna's Archive
        doi:          DOI → try Sci-Hub before shadow libraries

    Returns:
        FetchResult with all paths collected across all tiers.
    """
    if verbose:
        print(f"\n{'='*60}")
        print(f"  📥 CASCADE FETCHER (Script Mode)")
        print(f"  query={query!r}  arxiv_id={arxiv_id!r}  lang={lang!r}")
        print(f"{'='*60}")

    total_paths = []
    errors = []
    items_found = 0

    # ── Tier 1: arXiv ──────────────────────────────────────────────
    arxiv_done = (
        preferred_source and preferred_source != "arxiv"
    )
    if not arxiv_done:
        if verbose:
            print(f"\n── [Tier 1] arXiv (Open Science) ──")

        result = download_from_arxiv(
            query=query,
            arxiv_id=arxiv_id,
            max_results=max_results,
        )

        if result.success:
            total_paths.extend(result.paths)
            items_found += result.items_found
            if verbose:
                print(f"  ✅ arXiv: {len(result.paths)} files | total={len(total_paths)}")
        else:
            errors.append(f"arXiv: {result.error}")
            if verbose:
                print(f"  ❌ arXiv failed: {result.error}")

        # Stop carly if we hit the target
        if len(total_paths) >= max_results:
            return _build_result(total_paths, errors, items_found, "mixed")

    # ── Tier 2a: Sci-Hub (DOI) ─────────────────────────────────────
    if doi and len(total_paths) < max_results:
        if verbose:
            print(f"\n── [Tier 2a] Sci-Hub (DOI={doi}) ──")
        result = download_from_scihub(doi)
        if result.success:
            total_paths.extend(result.paths)
            items_found += 1
            if verbose:
                print(f"  ✅ Sci-Hub: {len(result.paths)} files")
        else:
            errors.append(f"Sci-Hub: {result.error}")
            if verbose:
                print(f"  ❌ Sci-Hub failed: {result.error}")

    # ── Tier 2b: Anna's Archive / LibGen ───────────────────────────
    annas_done = (
        preferred_source and preferred_source not in ("annas_archive", "shadow")
    )
    if not annas_done and len(total_paths) < max_results:
        if verbose:
            print(f"\n── [Tier 2b] Anna's Archive (Shadow Libraries) ──")
        result = download_from_annas_archive(
            query=query or arxiv_id or "",
            max_results=max_results - len(total_paths),
            lang=lang,
        )
        if result.success:
            total_paths.extend(result.paths)
            items_found += result.items_found
            if verbose:
                print(f"  ✅ Anna's: {len(result.paths)} files | total={len(total_paths)}")
        else:
            errors.append(f"Anna's: {result.error}")
            if verbose:
                print(f"  ❌ Anna's failed: {result.error}")

        if len(total_paths) >= max_results:
            return _build_result(total_paths, errors, items_found, "mixed")

    # ── Tier 3: Web Search (Garimpo) ────────────────────────────────
    if len(total_paths) < max_results:
        if verbose:
            print(f"\n── [Tier 3] Web Search (Garimpo na Web) ──")
        result = download_from_web_search(
            query=query or arxiv_id or "",
            max_results=max_results - len(total_paths),
        )
        if result.success:
            total_paths.extend(result.paths)
            items_found += result.items_found
            if verbose:
                print(f"  ✅ Web: {len(result.paths)} files | total={len(total_paths)}")
        else:
            errors.append(f"Web: {result.error}")
            if verbose:
                print(f"  ❌ Web search failed: {result.error}")

    if verbose:
        print(f"\n{'='*60}")
        print(f"  ✅ Cascade complete. Downloaded {len(total_paths)}/{max_results} files.")
        if errors:
            print(f"  ⚠️  Errors: {' | '.join(errors)}")
        print(f"{'='*60}\n")

    return _build_result(total_paths, errors, items_found, "mixed")


def _build_result(paths, errors, items_found, source) -> FetchResult:
    return FetchResult(
        success=len(paths) > 0,
        paths=paths,
        error="; ".join(errors) if errors else "",
        source=source,
        items_found=items_found,
        metadata={"downloaded": len(paths)}
    )


# ─────────────────────────────────────────────
# ReAct Agent Mode  (intelligent, LLM-powered)
# ─────────────────────────────────────────────

def run_cascade_react(
    query: str,
    api_key: str,
    model: str = "gpt-4o",
    max_results: int = 3,
    verbose: bool = True,
) -> FetchResult:
    """
    ReAct agent: the LLM plans a search strategy, calls tools,
    observes results, and decides next steps — with cascade guardrails.

    Tools exposed to the agent:
      - download_from_arxiv()
      - download_from_annas_archive()
      - download_from_scihub(doi)
      - download_from_web_search()

    The agent receives structured tool responses (FetchResult summary)
    so it can decide whether to continue to the next tier or retry.
    """
    try:
        from openai import OpenAI
    except ImportError:
        return FetchResult(
            success=False,
            error="openai package not installed. Run: pip install openai",
            source="react"
        )

    client = OpenAI(api_key=api_key)

    if verbose:
        print(f"\n{'='*60}")
        print(f"  🧠 CASCADE FETCHER (ReAct Agent Mode)")
        print(f"  query={query!r}  model={model}")
        print(f"{'='*60}")

    system_prompt = (
        "You are an expert Research Downloader Agent running in ReAct mode.\n"
        "Your goal: download research materials (papers, books) by intelligently "
        "routing user requests across 3 tiers:\n"
        "  Tier 1 – arXiv.org          (free open-access papers, physics/CS/math)\n"
        "  Tier 2 – Anna's Archive      (shadow library: books + papers not on arXiv)\n"
        "         – Sci-Hub            ( DOI-based paper downloads)\n"
        "  Tier 3 – Web Search/Garimpo (catch-all for any material)\n\n"
        "You MUST respect these rules:\n"
        " 1. ALWAYS try arXiv FIRST for scientific papers.\n"
        " 2. For books, seminars, or humanities → try Anna's Archive.\n"
        " 3. For specific DOIs → try Sci-Hub.\n"
        " 4. ONLY use Web Search as last resort (Tier 3).\n"
        " 5. Stop early if you already have ≥ max_results files.\n"
        " 6. Report a FetchResult summary after EACH tool call so I can track progress.\n\n"
        "Tool responses are in this format:\n"
        "  FetchResult(success=bool, paths=[...], error=str, source=str)\n\n"
        "Always respond with a JSON tool call."
    )

    tools = [
        {
            "type": "function",
            "function": {
                "name": "download_from_arxiv",
                "description": (
                    "Download papers from arXiv.org by query or specific ID. "
                    "Use for: physics, mathematics, CS, quantitative finance, stats, "
                    "electrical engineering, economics. Returns FetchResult."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "arxiv_id": {"type": "string"},
                        "max_results": {"type": "integer", "default": 3},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "download_from_annas_archive",
                "description": (
                    "Search and download books, seminars, or articles from "
                    "Anna's Archive shadow library. Best for: literature, humanities, "
                    "Lacan seminars, books not on arXiv. Returns FetchResult."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "max_results": {"type": "integer", "default": 3},
                        "lang": {"type": "string", "default": ""},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "download_from_scihub",
                "description": (
                    "Download a paper via Sci-Hub using its DOI. "
                    "Use when user provides a DOI or when arXiv fails for a known paper. "
                    "Returns FetchResult."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "doi": {"type": "string"},
                    },
                    "required": ["doi"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "download_from_web_search",
                "description": (
                    "Catch-all web search. Searches DuckDuckGo for PDFs and direct links. "
                    "Use as last resort when material is not on arXiv, Anna's, or Sci-Hub. "
                    "Returns FetchResult."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "max_results": {"type": "integer", "default": 3},
                    },
                    "required": ["query"],
                },
            },
        },
    ]

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": (
            f"User request: {query}\n"
            f"Goal: download up to {max_results} relevant files.\n"
            f"Start by searching arXiv with a well-formed query."
        )},
    ]

    max_iterations = 10
    total_paths = []
    errors = []
    items_found = 0

    for iteration in range(max_iterations):
        if len(total_paths) >= max_results:
            if verbose:
                print(f"  ✅ ReAct: reached target ({len(total_paths)} files). Stopping.")
            break

        if verbose:
            print(f"\n── ReAct iteration {iteration + 1}/{max_iterations} ──")

        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
            )
        except Exception as e:
            return FetchResult(success=False, error=str(e), source="react")

        message = response.choices[0].message

        # Agent wants to call tools
        if message.tool_calls:
            for tool_call in message.tool_calls:
                fn_name = tool_call.function.name
                args = {}
                try:
                    fn_args = {}  # will fill below
                    args_str = tool_call.function.arguments
                    import json
                    args = json.loads(args_str)
                except Exception:
                    args = {}

                if verbose:
                    print(f"  ⚡ Calling {fn_name}({args})")

                result: FetchResult = FetchResult(success=False, error="Not implemented", source="react")

                if fn_name == "download_from_arxiv":
                    result = download_from_arxiv(
                        query=args.get("query"),
                        arxiv_id=args.get("arxiv_id"),
                        max_results=args.get("max_results", max_results),
                    )
                elif fn_name == "download_from_annas_archive":
                    result = download_from_annas_archive(
                        query=args["query"],
                        max_results=args.get("max_results", max_results),
                        lang=args.get("lang", ""),
                    )
                elif fn_name == "download_from_scihub":
                    result = download_from_scihub(doi=args["doi"])
                elif fn_name == "download_from_web_search":
                    result = download_from_web_search(
                        query=args["query"],
                        max_results=args.get("max_results", max_results),
                    )

                # Record results
                if result.success:
                    total_paths.extend(result.paths)
                    items_found += result.items_found
                    if verbose:
                        print(f"  ✅ {fn_name}: {len(result.paths)} new files | total={len(total_paths)}")
                else:
                    errors.append(f"{fn_name}: {result.error}")
                    if verbose:
                        print(f"  ❌ {fn_name}: {result.error}")

                # Feed back to LLM as a tool result message
                result_summary = (
                    f"FetchResult(success={result.success}, "
                    f"paths={result.paths}, "
                    f"error={result.error!r}, "
                    f"source={result.source!r}, "
                    f"items_found={result.items_found})"
                )
                messages.append(message)  # agent message
                messages.append({        # tool result
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result_summary,
                })

        else:
            # Agent finished (no tool calls)
            if verbose:
                print(f"  🤖 Agent final message: {message.content}")
            break

    if verbose:
        print(f"\n{'='*60}")
        print(f"  🧠 ReAct complete. Downloaded {len(total_paths)}/{max_results} files.")
        if errors:
            print(f"  ⚠️  Errors: {' | '.join(errors)}")
        print(f"{'='*60}\n")

    return _build_result(total_paths, errors, items_found, "react")
