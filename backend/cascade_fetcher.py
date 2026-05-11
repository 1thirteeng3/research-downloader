"""
cascade_fetcher.py
Intelligent cascade downloader with 3-tier fallback:
  1. arXiv        → Open Science (free, legal, fast)
  2. Anna's/LibGen → Shadow Libraries (books, unavailable papers)
  3. Web Search    → "Garimpo na web" (catch-all for any remaining)

Supports two execution modes:
  - "dumb" (script mode): simple sequential cascade, no LLM needed
  - "react" (ReAct agent): uses an LLM to plan searches and route intelligently

Each fetcher returns a FetchResult so the cascade always knows what succeeded, what failed, and why.
"""
import time
import re
from result import FetchResult
from arxiv_fetcher import download_from_arxiv
from shadow_scraper import download_from_annas_archive, download_from_scihub
from web_search_fetcher import download_from_web_search


# ─────────────────────────────────────────────────────────
# URL / Query Normalization
# ─────────────────────────────────────────────────────────

# Match arXiv IDs inside URLs or plain:
#   - 0801.3170, hep-th/9707234, math.DG/0611259, 2301.00012
_ARXIV_URL_RE  = re.compile(r'(?:arxiv\.org/|abs/|pdf[/\.])(?:PS_cache/arxiv/)?(?:[\w.-]+/)?(\d{4}\.\d{4,5}(?:v\d+)?)')
_DOI_RE        = re.compile(r'(?:https?://(?:dx\.)?doi\.org/|doi[:=]?)(10\.\d{4,9}/[^\s"\'#]+)', re.I)
_SIMPLE_ARXIV_RE = re.compile(r'^(\d{4}\.\d{4,5}(?:v\d+)?)$')

def normalize_query(raw: str) -> tuple[str, str, str]:
    """
    Parse a raw input string that might be:
      - A plain arXiv ID   : 0801.3170, hep-th/9707234
      - A full arXiv URL   : http://arxiv.org/abs/0801.3170
      - A PDF cache URL    : http://arxiv.org/PS_cache/arxiv/pdf/0805/0805.0157v4.pdf#page=12
      - A DOI URL          : https://doi.org/10.1038/nature12373
      - Free text query    : Integrated Information Theory

    Returns (query, arxiv_id, doi)
      - arxiv_id is set ONLY when the input is a specific arXiv ID
      - doi is set ONLY when the input is a specific DOI
      - query is the cleaned free-text search (empty string if fully resolved above)
    """
    raw = raw.strip()
    if not raw:
        return "", None, None

    # Remove page anchors
    url_clean = raw.split("#")[0]

    # 1. Extract arXiv ID from URL
    m = _ARXIV_URL_RE.search(url_clean)
    if m:
        return "", m.group(1), None

    # 2. Check if raw itself is a bare arXiv ID
    m = _SIMPLE_ARXIV_RE.match(raw.replace("/", "").strip())
    if m:
        return "", raw.strip(), None

    # 3. Extract DOI from URL
    m = _DOI_RE.search(url_clean)
    if m:
        return "", None, m.group(1)

    # 4. Plain text query
    return raw, None, None


# ─────────────────────────────────────────────────────────
# Script Mode  (dumb / sequential cascade)
# ─────────────────────────────────────────────────────────

def run_cascade_script(
    query: str = None,
    arxiv_id: str = None,
    preferred_source: str = None,
    max_results: int = 3,
    lang: str = "",
    doi: str = None,
    verbose: bool = True,
) -> FetchResult:
    """
    Dumb script-mode cascade. No LLM needed.
    Tries sources in order until we hit max_results.

    Args:
        query        : Natural-language search term
        arxiv_id     : Specific arXiv ID to fetch directly
        preferred_source : Force only one source (skip cascade)
        max_results  : Stop after this many files downloaded
        lang         : Language filter for Anna's Archive
        doi          : DOI → try Sci-Hub

    Returns:
        FetchResult with all paths collected across all tiers.
    """
    if verbose:
        print(f"\n  🤖 Executando cascade em modo Script...")

    total_paths = []
    errors = []
    items_found = 0

    # ── Tier 1: arXiv (only if we have query or arxiv_id) ──
    if preferred_source in (None, "arxiv") and (query or arxiv_id):
        if verbose:
            print(f"  ── [Tier 1] arXiv (Open Science) ──")
        result = download_from_arxiv(query=query, arxiv_id=arxiv_id, max_results=max_results)
        if result.success:
            total_paths.extend(result.paths)
            items_found += result.items_found
            if verbose:
                print(f"  ✅ arXiv: {len(result.paths)} papers downloaded")
        else:
            if verbose:
                print(f"  ⚠️  arXiv: {result.error}")
            errors.append(f"arXiv:{result.error}")

    # ── Tier 1b: DOI / Sci-Hub ──
    if doi and (not total_paths or preferred_source == "scihub"):
        if verbose:
            print(f"  ── [Tier 1b] Sci-Hub (DOI: {doi}) ──")
        result = download_from_scihub(doi=doi, max_results=max_results)
        if result.success:
            total_paths.extend(result.paths)
            items_found += result.items_found
        else:
            if verbose:
                print(f"  ⚠️  Sci-Hub: {result.error}")
            errors.append(f"SciHub:{result.error}")

    # Stop if we already have enough
    if total_paths and len(total_paths) >= max_results:
        return FetchResult(success=True, paths=total_paths, items_found=items_found,
                           error="; ".join(errors), source="arxiv")

    # ── Tier 2: Anna's Archive ──
    if preferred_source in (None, "annas_archive") and not total_paths:
        if verbose:
            print(f"  ── [Tier 2] Anna's Archive (Shadow Libraries) ──")
        search_term = query or arxiv_id or doi or ""
        result = download_from_annas_archive(query=search_term, max_results=max_results - len(total_paths), lang=lang)
        if result.success:
            total_paths.extend(result.paths)
            items_found += result.items_found
            if verbose:
                print(f"  ✅ Anna's: {len(result.paths)} files downloaded")
        else:
            if verbose:
                print(f"  ⚠️  Anna's: {result.error}")
            errors.append(f"Anna's:{result.error}")

    # ── Tier 3: Web Search / Garimpo ──
    if not total_paths:
        if verbose:
            print(f"  ── [Tier 3] Web Search (Garimpo) ──")
        search_term = query or arxiv_id or doi or ""
        result = download_from_web_search(query=search_term, max_results=max_results)
        if result.success:
            total_paths.extend(result.paths)
            items_found += result.items_found
            if verbose:
                print(f"  ✅ Web: {len(result.paths)} files found")
        else:
            if verbose:
                print(f"  ⚠️  Web: {result.error}")
            errors.append(f"Web:{result.error}")

    return FetchResult(
        success=bool(total_paths),
        paths=total_paths,
        items_found=items_found,
        error="; ".join(errors),
        source="script-cascade",
    )


# ─────────────────────────────────────────────────────────
# ReAct Mode  (LLM-powered intelligent cascade)
# ─────────────────────────────────────────────────────────

def _build_result(paths, errors, items_found, source):
    return FetchResult(
        success=bool(paths),
        paths=paths,
        items_found=items_found,
        error="; ".join(e for e in errors if e),
        source=source,
    )


def run_cascade_react(
    query: str,
    api_key: str,
    model: str = "gpt-4o",
    max_results: int = 3,
    lang: str = "",
    verbose: bool = True,
) -> FetchResult:
    """
    ReAct loop.  The LLM gets tool definitions and decides
    when/what to call.  Handles arXiv IDs, DOIs, and free-text
    queries by parsing the input in the system prompt.
    """
    try:
        from openai import OpenAI
    except ImportError:
        return FetchResult(success=False, error="openai package not installed. Run: pip install openai")

    client = OpenAI(api_key=api_key)

    tools = [
        {
            "type": "function",
            "function": {
                "name": "download_from_arxiv",
                "description": (
                    "Download papers from arXiv by query or specific ID.  "
                    "ALWAYS try this first for physics, math, CS, q-bio, q-fin, stats, eess.  "
                    "If the user gave a URL like 'http://arxiv.org/abs/0801.3170', "
                    "use the numeric ID '0801.3170' as the arxiv_id argument.  "
                    "If the user gave a PDF cache URL, extract the numeric ID from it."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query":    {"type": "string", "description": "Natural-language search (e.g. 'Integrated Information Theory'). Use when user gave free text."},
                        "arxiv_id": {"type": "string", "description": "Specific arXiv ID (e.g. '0801.3170'). Use when user gave a URL or bare ID."},
                        "max_results": {"type": "integer", "description": "Max papers to download.", "default": 3},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "download_from_annas_archive",
                "description": (
                    "Download books / seminars / articles from Anna's Archive.  "
                    "Use when arXiv fails OR when the user is looking for books, "
                    "humanities, literature, or non-CSS papers.  "
                    "For Lacan seminars: query='Jacques Lacan Seminaire', lang='fr'."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query":      {"type": "string", "description": "Search term."},
                        "max_results": {"type": "integer", "description": "Max books to download.", "default": 3},
                        "lang":        {"type": "string", "description": "Language code (en, fr, es, pt...)."},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "download_from_scihub",
                "description": "Download a paper via DOI using Sci-Hub. Use when user provides a DOI or a URL like https://doi.org/10.xxx.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "doi":        {"type": "string", "description": "DOI (e.g. '10.1038/nature12373')."},
                        "max_results": {"type": "integer", "description": "Max papers.", "default": 3},
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
                    "Last-resort catch-all. Search the web via DuckDuckGo for direct PDF/EPUB links.  "
                    "Only call this after arXiv, Anna's Archive, and Sci-Hub have all failed."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query":       {"type": "string", "description": "Search query (title, topic, author...)."},
                        "max_results": {"type": "integer", "description": "Max results.", "default": 3},
                    },
                    "required": ["query"],
                },
            },
        },
    ]

    messages = [
        {
            "role": "system",
            "content": (
                "You are a world-class research assistant with access to these tools:\n"
                "  - download_from_arxiv(query, arxiv_id, max_results)\n"
                "  - download_from_annas_archive(query, max_results, lang)\n"
                "  - download_from_scihub(doi, max_results)\n"
                "  - download_from_web_search(query, max_results)\n\n"
                "IMPORTANT — URL / ID parsing rules (apply BEFORE calling any tool):\n"
                "  • http://arxiv.org/abs/0801.3170  → arxiv_id='0801.3170'\n"
                "  • http://arxiv.org/PS_cache/arxiv/pdf/0805/0805.0157v4.pdf → arxiv_id='0805.0157'\n"
                "  • https://doi.org/10.1038/nature12373 → doi='10.1038/nature12373'\n"
                "  • Plain '0801.3170'               → arxiv_id='0801.3170'\n"
                "  • Plain 'hep-th/9707234'           → arxiv_id='hep-th/9707234'\n"
                "  • Free text like 'IIT Tononi'      → query='Integrated Information Theory Tononi'\n\n"
                "Strategy rules:\n"
                "  1. For physics/math/CS papers → ALWAYS try arXiv first.\n"
                "  2. For books, seminars, humanities → try Anna's Archive.\n"
                "  3. For DOIs → try Sci-Hub.\n"
                "  4. Web Search → ONLY as last resort.\n"
                "  5. Stop and return a summary when you have ≥ max_results files.\n"
                "  6. If any tool returns no results, try the next tier.\n"
                "  7. When the user gives many URLs at once (batch), parse ALL of them and call the appropriate tool for each one.\n"
            ),
        },
        {"role": "user", "content": query},
    ]

    total_paths = []
    errors = []
    items_found = 0

    if verbose:
        print(f"  🤖 ReAct Agent inicializado (modelo: {model})")

    for step in range(10):   # max 10 ReAct steps to prevent runaway
        if verbose:
            print(f"\n  ── ReAct Step {step+1} ──")

        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools,
            tool_choice="auto",
        )

        message = response.choices[0].message

        if not message.tool_calls:
            # Agent done
            if verbose:
                print(f"  ✅ Agente terminou: {message.content}")
            break

        for tool_call in message.tool_calls:
            fn_name = tool_call.function.name
            args_str = tool_call.function.arguments

            if verbose:
                print(f"  ⚡ Tool: {fn_name} | args: {args_str[:120]}")

            try:
                args = eval(f"dict({args_str})", {"__builtins__": {}}, {})
            except Exception:
                try:
                    import json
                    args = json.loads(args_str)
                except Exception as e:
                    if verbose:
                        print(f"  ❌ Failed to parse args: {e}")
                    errors.append(f"{fn_name}:parse-error")
                    continue

            # ── Route tool call ──
            if fn_name == "download_from_arxiv":
                result = download_from_arxiv(
                    query=args.get("query"),
                    arxiv_id=args.get("arxiv_id"),
                    max_results=args.get("max_results", max_results),
                )
                items_found += result.items_found

            elif fn_name == "download_from_annas_archive":
                result = download_from_annas_archive(
                    query=args.get("query"),
                    max_results=args.get("max_results", max_results),
                    lang=args.get("lang", lang),
                )
                items_found += result.items_found

            elif fn_name == "download_from_scihub":
                result = download_from_scihub(
                    doi=args.get("doi"),
                    max_results=args.get("max_results", max_results),
                )
                items_found += result.items_found

            elif fn_name == "download_from_web_search":
                result = download_from_web_search(
                    query=args.get("query"),
                    max_results=args.get("max_results", max_results),
                )
                items_found += result.items_found

            else:
                result = FetchResult(success=False, error=f"Unknown tool: {fn_name}")

            if result.paths:
                total_paths.extend(result.paths)

            if result.error:
                errors.append(result.error)

            # ── Give tool result back to LLM ──
            result_summary = (
                f"success={result.success}, "
                f"paths={result.paths}, "
                f"error={result.error!r}, "
                f"source={result.source!r}, "
                f"items_found={result.items_found}"
            )
            messages.append({"role": "assistant", "content": message.content})
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result_summary,
            })

            if total_paths and len(total_paths) >= max_results:
                if verbose:
                    print(f"  ✅ Atingiu {len(total_paths)} resultados. Parando.")
                return _build_result(total_paths, errors, items_found, "react")

    if verbose:
        print(f"\n{'='*60}")
        print(f"  🧠 ReAct completo. Baixados {len(total_paths)}/{max_results} arquivos.")
        if errors:
            print(f"  ⚠️  Erros: {' | '.join(set(errors))}")
        print(f"{'='*60}\n")

    return _build_result(total_paths, errors, items_found, "react")