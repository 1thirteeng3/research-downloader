"""
arxiv_fetcher.py
Download scientific papers from arXiv.org using the official arXiv API.
API docs: https://info.arxiv.org/api/index.html
Rate limit: 1 request every 3 seconds per IP (hard limit: 4 requests/s with token)
"""
import arxiv
import os
import time
import requests
from organizer import organize_paper
from result import FetchResult

# Hard respect for arXiv rate limits: 1 request per 3 seconds
_ARXIV_RATE_LIMIT_SECONDS = 3
_last_call_time = 0

def _rate_limit():
    """Enforce arXiv's 1-req-per-3s policy."""
    global _last_call_time
    elapsed = time.monotonic() - _last_call_time
    if elapsed < _ARXIV_RATE_LIMIT_SECONDS:
        sleep_time = _ARXIV_RATE_LIMIT_SECONDS - elapsed
        print(f"  [arXiv rate-limit] sleeping {sleep_time:.1f}s...")
        time.sleep(sleep_time)
    _last_call_time = time.monotonic()


def download_from_arxiv(query: str = None, max_results: int = 3, arxiv_id: str = None) -> FetchResult:
    """
    Fetch papers from arXiv by query or specific ID.
    Returns FetchResult with success, paths, error, source.
    """
    client = arxiv.Client()
    results = []
    error_msg = ""

    _rate_limit()

    if arxiv_id:
        # Normalize older-style IDs (math.DG/0611259 → DG0611259 or 0611259)
        normalized_id = arxiv_id.strip()
        for prefix in ["math.", "hep-th/", "hep-ph/", "gr-qc/", "cs.", "physics."]:
            normalized_id = normalized_id.replace(prefix, "")
        normalized_id = normalized_id.replace("/", "")
        print(f"Searching arXiv for ID: {normalized_id}")
        try:
            search = arxiv.Search(id_list=[normalized_id])
            results = list(client.results(search))
        except Exception as e:
            error_msg = str(e)
            # 404 or not found → consider it a soft failure (ID not on arXiv)
            if "not found" in error_msg.lower() or "404" in error_msg:
                error_msg = f"arXiv ID '{normalized_id}' not found on arXiv (probably pre-2007 or non-arXiv source)"
            return FetchResult(success=False, error=error_msg, source="arxiv",
                              metadata={"arxiv_id": normalized_id, "original_id": arxiv_id})

    elif query:
        print(f"Searching arXiv for: '{query}' (max {max_results} results)")
        try:
            search = arxiv.Search(
                query=query,
                max_results=max_results,
                sort_by=arxiv.SortCriterion.Relevance,
                sort_order=arxiv.SortOrder.Descending
            )
            results = list(client.results(search))
        except Exception as e:
            error_msg = str(e)
            return FetchResult(success=False, error=error_msg, source="arxiv",
                              metadata={"query": query, "max_results": max_results})
    else:
        return FetchResult(success=False, error="Must provide either query or arxiv_id", source="arxiv")

    if not results:
        return FetchResult(success=False,
                          error=f"No results for query='{query}' or ID='{arxiv_id}'",
                          source="arxiv",
                          metadata={"query": query, "arxiv_id": arxiv_id})

    tmp_dir = os.path.join(os.path.expanduser("~"), ".research_tmp")
    os.makedirs(tmp_dir, exist_ok=True)

    downloaded_paths = []
    for paper in results:
        short_id = paper.get_short_id().replace("/", "_")
        tmp_filename = f"{short_id}.pdf"
        tmp_path = os.path.join(tmp_dir, tmp_filename)

        print(f"  Title: {paper.title[:80]}...")
        print(f"  Authors: {', '.join([a.name for a in paper.authors][:3])}")
        print(f"  Published: {paper.published.year} | ID: {short_id}")

        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (compatible; ResearchDownloaderBot/1.0; mailto:giovanni@example.com)"
            }
            pdf_url = paper.pdf_url
            if not pdf_url.endswith(".pdf"):
                pdf_url += ".pdf"

            response = requests.get(pdf_url, headers=headers, stream=True, timeout=30)
            response.raise_for_status()

            with open(tmp_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                # Rate limited even with our guard — back off and retry once
                print(f"  [arXiv 429] Waiting 10s to retry...")
                time.sleep(10)
                try:
                    response = requests.get(pdf_url, headers=headers, stream=True, timeout=30)
                    response.raise_for_status()
                    with open(tmp_path, "wb") as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            f.write(chunk)
                except Exception as retry_err:
                    print(f"  Fallback download failed: {retry_err}")
                    paper.download_pdf(dirpath=tmp_dir, filename=tmp_filename)
            else:
                print(f"  HTTP error, falling back to official client: {e}")
                paper.download_pdf(dirpath=tmp_dir, filename=tmp_filename)
        except Exception as e:
            print(f"  Download error, falling back to official client: {e}")
            paper.download_pdf(dirpath=tmp_dir, filename=tmp_filename)

        _rate_limit()  # Enforce rate limit after each paper

        final_path = organize_paper(
            source_file=tmp_path,
            title=paper.title,
            authors=[a.name for a in paper.authors],
            year=str(paper.published.year),
            source="arXiv"
        )
        if final_path:
            downloaded_paths.append(final_path)

    return FetchResult(
        success=len(downloaded_paths) > 0,
        paths=downloaded_paths,
        error="" if downloaded_paths else "Download completed but no files were saved",
        source="arxiv",
        items_found=len(results),
        metadata={"query": query, "arxiv_id": arxiv_id, "papers_found": len(results)}
    )
