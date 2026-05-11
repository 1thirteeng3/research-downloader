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
import requests
from result import FetchResult
from arxiv_fetcher import download_from_arxiv
from shadow_scraper import download_from_annas_archive, download_from_scihub
from web_search_fetcher import download_from_web_search


# ─────────────────────────────────────────────────────────
# URL / Query Normalization
# ─────────────────────────────────────────────────────────

# arXiv new format (2004+): 4 digits . 4-5 digits [vN]
_ARXIV_NEW_RE = re.compile(r'(?:arxiv\.org/(?:abs|pdf)|/)(\d{4}\.\d{4,5}(?:v\d+)?)', re.I)

# arXiv legacy format (before 2007): category/DDDDDDD (7 digits)
_ARXIV_LEGACY_URL_RE = re.compile(r'(?:arxiv\.org|aps\.arxiv\.org)/(?:abs|ps_cache/arxiv/)?([\w.-]+/\d{7,})', re.I)
_ARXIV_LEGACY_BARE_RE = re.compile(r'^([\w.-]+/\d{7,})$')

# DOI
_DOI_RE = re.compile(r'(?:https?://(?:dx\.)?doi\.org/|doi[:=]?)\s*(10\.\d{4,9}/[^\s"\'#]+)', re.I)

# Plain bare new-format ID: 0801.3170  (no category prefix)
_SIMPLE_NEW_RE = re.compile(r'^(\d{4}\.\d{4,5}(?:v\d+)?)$')


def normalize_query(raw: str) -> tuple[str, str, str]:
    """
    Parse any input (URL, bare ID, DOI, or free text) and return
    (query, arxiv_id, doi).

    Handles:
      - http://arxiv.org/abs/0801.3170        → arXiv ID: 0801.3170
      - http://arxiv.org/abs/math.DG/0611259 → arXiv ID: math.DG/0611259 (legacy)
      - http://arxiv.org/abs/hep-th/9707234   → arXiv ID: hep-th/9707234 (legacy)
      - http://arxiv.org/PS_cache/.../0805.0157v4.pdf → arXiv ID: 0805.0157v4
      - https://doi.org/10.1038/nature12373   → DOI: 10.1038/nature12373
      - "Integrated Information Theory"       → query: Integrated Information Theory
    """
    raw = raw.strip()
    if not raw:
        return "", None, None

    # Strip page anchors (#page=N) and query params
    url_clean = raw.split("#")[0].split("?")[0]

    # 1. New-format arXiv ID (YYMM.NNNNN[vN]) — most URLs contain this
    m = _ARXIV_NEW_RE.search(url_clean)
    if m:
        return "", m.group(1), None

    # 2. Legacy arXiv ID in URL (category/7digits)
    m = _ARXIV_LEGACY_URL_RE.search(url_clean)
    if m:
        return "", m.group(1), None

    # 3. Legacy bare arXiv ID (category/7digits)
    m = _ARXIV_LEGACY_BARE_RE.match(raw)
    if m:
        return "", m.group(1), None

    # 4. Plain new-format bare ID (YYMM.NNNN[vN])
    m = _SIMPLE_NEW_RE.match(raw.replace("/", ""))
    if m:
        return "", raw, None

    # 5. DOI in any form
    m = _DOI_RE.search(url_clean)
    if m:
        return "", None, m.group(1).rstrip("/")

    # 6. Free text → use as search query
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
    verbose: bool = False,
) -> FetchResult:
    """
    Dumb script-mode cascade. No LLM needed.
    Tries sources in order until we hit max_results.
    """
    all_paths = []
    errors = []
    items_found = 0
    _tier_tried = set()

    def _add(result: FetchResult):
        nonlocal all_paths, items_found
        if result.success and result.paths:
            all_paths.extend(result.paths)
            items_found += len(result.paths)
        if result.error:
            errors.append(result.error)

    # ── Tier 1: arXiv ──────────────────────────────────
    if preferred_source != "annas_archive":
        if arxiv_id or query:
            _tier_tried.add("arxiv")
            result = download_from_arxiv(query=query, arxiv_id=arxiv_id, max_results=max_results)
            _add(result)

    if len(all_paths) >= max_results:
        return FetchResult(success=bool(all_paths), paths=all_paths,
                           error="; ".join(errors) if errors else "", source="arxiv")

    # ── Tier 2a: Sci-Hub (if DOI) ───────────────────────
    if doi:
        _tier_tried.add("scihub")
        result = download_from_scihub(doi=doi)
        _add(result)

    if len(all_paths) >= max_results:
        return FetchResult(success=bool(all_paths), paths=all_paths,
                           error="; ".join(errors) if errors else "", source="scihub")

    # ── Tier 2b: Anna's Archive / LibGen ────────────────
    if preferred_source != "arxiv":
        import shadow_scraper
        shadow_scraper.verbose_fetching = verbose
        _tier_tried.add("annas_archive")
        search_q = (doi or arxiv_id or query or "").strip()
        if search_q:
            result = download_from_annas_archive(
                query=search_q,
                max_results=max_results - len(all_paths),
                lang=lang,
            )
            _add(result)

    if len(all_paths) >= max_results:
        return FetchResult(success=bool(all_paths), paths=all_paths,
                           error="; ".join(errors) if errors else "", source="annas_archive")

    # ── Tier 3: Web Search / Garimpo ────────────────────
    if query:
        _tier_tried.add("web")
        result = download_from_web_search(query=query, max_results=max_results - len(all_paths))
        _add(result)

    return FetchResult(
        success=bool(all_paths),
        paths=all_paths,
        error=f"Tiers tried: {', '.join(_tier_tried)}. Errors: {'; '.join(errors)}" if errors else "",
        source=" | ".join(_tier_tried) or "none",
    )


# ─────────────────────────────────────────────────────────
# ReAct Agent Mode
# ─────────────────────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "download_from_arxiv",
            "description": (
                "Download scientific papers from arXiv by search query or specific ID. "
                "Use for: physics, math, CS, q-bio, q-fin, stats, EESS, economics papers. "
                "arXiv ID formats: new='0801.3170', legacy='hep-th/9707234', 'math.DG/0611259'. "
                "Pass arxiv_id= to fetch a specific paper; pass query= for keyword search."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query":    {"type": "string", "description": "Keyword search (e.g. 'Integrated Information Theory IIT')"},
                    "arxiv_id": {"type": "string", "description": "Specific arXiv ID (e.g. '0801.3170' or 'hep-th/9707234')"},
                    "max_results": {"type": "integer", "description": "Max papers to download", "default": 5},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "download_from_annas_archive",
            "description": (
                "Search Anna's Archive and LibGen for books, seminars, humanities papers, "
                "and any material not indexed on arXiv. Use for: Jacques Lacan seminars, "
                "philosophy books, literature, obscure academic texts. "
                "Returns FetchResult with paths on success."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query":       {"type": "string", "description": "Search query (e.g. 'Jacques Lacan Seminaire 1')"},
                    "max_results": {"type": "integer", "description": "Max results to try downloading", "default": 3},
                    "lang":        {"type": "string", "description": "Language filter (e.g. 'en', 'fr', 'pt')", "default": ""},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "download_from_scihub",
            "description": (
                "Download a scientific paper from Sci-Hub using its DOI. "
                "Only use when you have a DOI (e.g. '10.1038/nature12373'). "
                "arXiv papers do NOT have DOIs — use download_from_arxiv instead."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "doi": {"type": "string", "description": "DOI of the paper (e.g. '10.1038/nature12373')"},
                },
                "required": ["doi"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "download_from_web_search",
            "description": (
                "LAST RESORT — Tier 3 'garimpo na web'. "
                "Search the open web via DuckDuckGo for direct PDF/EPUB links. "
                "Only use when the material is NOT on arXiv, Sci-Hub, or Anna's Archive. "
                "Returns FetchResult with paths on success."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query":       {"type": "string", "description": "Search query"},
                    "max_results": {"type": "integer", "description": "Max PDFs to attempt", "default": 3},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
]

SYSTEM_PROMPT = """You are the Research Cascade Agent — an expert librarian for scientific and academic materials.

Your job: help the user find and download papers, books, and articles using a 3-tier cascade:

  Tier 1 — arXiv        → Open Science (free, legal, fast). Use for: CS, physics, math, stats, engineering.
  Tier 2 — Anna's/LibGen → Shadow Libraries. Use for: books, seminars, humanities, non-arXiv papers.
  Tier 2b — Sci-Hub     → By DOI only. Use for: paywalled papers when DOI is available.
  Tier 3 — Web Search   → LAST RESORT. Only when Tiers 1 and 2 both failed.

STRICT RULES:
  1. For arXiv papers: ALWAYS use download_from_arxiv (NOT web search).
  2. For books/seminars (e.g. Lacan): use download_from_annas_archive.
  3. For DOIs: use download_from_scihub.
  4. Web Search is a last resort only.
  5. After each tool call, analyse the result:
       - If success (paths returned): report to the user and stop.
       - If failure: try the next tier in the cascade.
  6. Stop when you have >= max_results files or when all tiers are exhausted.
  7. For URL inputs like 'http://arxiv.org/abs/hep-th/9707234': extract the ID first, then call the appropriate fetcher.
  8. For legacy arXiv IDs like 'math.DG/0611259' or 'hep-th/9707234': pass them as arxiv_id to download_from_arxiv.

After each tool call, think: Did it succeed? Should I try next tier or stop?
"""


def run_cascade_react(
    query: str,
    api_key: str,
    model: str = "gpt-4o",
    max_results: int = 3,
    verbose: bool = False,
) -> FetchResult:
    """
    ReAct loop: the LLM plans actions, executes tools, and loops until done.
    Uses openai SDK directly.
    """
    try:
        from openai import OpenAI
    except ImportError:
        return FetchResult(False, [], "openai package not installed. Run: pip install openai")

    client = OpenAI(api_key=api_key)

    # Pre-normalize the user's raw input
    clean_query, pre_arxiv_id, pre_doi = normalize_query(query)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Download up to {max_results} file(s) about: {query!r}\n"
                + (f" (pre-extracted arXiv ID: {pre_arxiv_id})" if pre_arxiv_id else "")
                + (f" (pre-extracted DOI: {pre_doi})" if pre_doi else "")
                + "\nStart by calling the most appropriate tool."
            ),
        },
    ]

    total_paths = []
    errors = []
    items_found = 0
    max_turns = 15
    last_reasoning = ""

    for turn in range(max_turns):
        if verbose:
            print(f"\n  🔄 ReAct turn {turn + 1}/{max_turns}")

        # ── LLM decides next action ──────────────────────
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=TOOL_DEFINITIONS,
                tool_choice="auto",
                temperature=0.1,
            )
        except Exception as e:
            errors.append(f"OpenAI API error: {e}")
            break

        message = response.choices[0].message

        # ── No tool call — agent is done ─────────────────
        if not message.tool_calls:
            if message.content:
                last_reasoning = message.content
                if verbose:
                    print(f"  🤖 Agent: {message.content}")
            break

        # ── Execute each tool call ───────────────────────
        for tool_call in message.tool_calls:
            fn_name = tool_call.function.name
            args_str = tool_call.function.arguments
            if verbose:
                print(f"  ⚡ Tool: {fn_name} — {args_str[:200]}")

            # ── Parse arguments safely ─────────────────
            try:
                args = {"max_results": max_results}
                args.update(eval(f"dict({args_str})"))
            except Exception:
                try:
                    import json
                    args = json.loads(args_str)
                except Exception:
                    errors.append(f"Failed to parse args for {fn_name}: {args_str}")
                    continue

            # Override max_results to respect user preference
            args["max_results"] = min(args.get("max_results", max_results), max_results)

            # Pre-fill arxiv_id if we extracted one from the URL
            if fn_name == "download_from_arxiv" and pre_arxiv_id and not args.get("arxiv_id"):
                args["arxiv_id"] = pre_arxiv_id
                if verbose:
                    print(f"     ↳ Injected pre-extracted arXiv ID: {pre_arxiv_id}")

            # Pre-fill DOI if we extracted one
            if fn_name == "download_from_scihub" and pre_doi and not args.get("doi"):
                args["doi"] = pre_doi

            # ── Route to correct fetcher ─────────────────
            result: FetchResult = FetchResult(False, [], f"Unknown tool: {fn_name}")
            if fn_name == "download_from_arxiv":
                result = download_from_arxiv(**{k: v for k, v in args.items() if k in ("query", "arxiv_id", "max_results")})
            elif fn_name == "download_from_annas_archive":
                result = download_from_annas_archive(**{k: v for k, v in args.items() if k in ("query", "max_results", "lang")})
            elif fn_name == "download_from_scihub":
                result = download_from_scihub(**{k: v for k, v in args.items() if k in ("doi",)})
            elif fn_name == "download_from_web_search":
                result = download_from_web_search(**{k: v for k, v in args.items() if k in ("query", "max_results")})

            # ── Record result ───────────────────────────
            if result.success and result.paths:
                total_paths.extend(result.paths)
                items_found += len(result.paths)
            if result.error:
                errors.append(result.error)

            # ── Report back to LLM ──────────────────────
            result_summary = (
                f"FetchResult(success={result.success}, "
                f"paths={result.paths!r}, "
                f"error={result.error!r}, "
                f"source={result.source!r}, "
                f"items_found={items_found})"
            )
            messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": result_summary})

            if verbose:
                print(f"     ↳ Result: {result_summary[:300]}")

            # Stop if we have enough
            if len(total_paths) >= max_results:
                break

        if len(total_paths) >= max_results:
            break

    return FetchResult(
        success=bool(total_paths),
        paths=total_paths,
        error=f"Turns: {turn+1}. Errors: {' | '.join(errors)}" if errors else "",
        source="react",
    )
