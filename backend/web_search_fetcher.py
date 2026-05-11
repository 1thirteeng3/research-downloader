"""
web_search_fetcher.py
Tier-3 "garimpo na web" fetcher.
Uses DuckDuckGo (no API key needed) to find direct PDF links.
Last resort when Tier-1 (arXiv) and Tier-2 (Shadow Libraries) both fail.
"""
import os
import re
import time
import requests
import urllib.parse
from bs4 import BeautifulSoup
from organizer import organize_paper
from result import FetchResult

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def _is_valid_pdf_url(url: str) -> bool:
    """Reject file-hosting landing pages; only accept direct PDF/EPUB/DJVU."""
    bad = ["google.com/url", "redirect", "out.php", "libgen", "z-lib", "annas",
           "sci-hub", "springer", "wiley", "tandfonline", "sagepub"]
    url_lower = url.lower()
    if any(b in url_lower for b in bad):
        return False
    return url_lower.endswith((".pdf", ".epub", ".djvu", ".azw3"))


def _resolve_duckduckgo_redirect(href: str) -> str:
    """Extract the real URL from DuckDuckGo's uddg= redirect param."""
    if "uddg=" in href:
        try:
            return urllib.parse.unquote(href.split("uddg=")[1].split("&")[0])
        except Exception:
            pass
    return href


def download_from_web_search(query: str, max_results: int = 3) -> FetchResult:
    """
    Tier-3 garimpo na web via DuckDuckGo HTML search.
    Looks for direct PDF/EPUB links and downloads them.
    Returns FetchResult.
    """
    print(f"[WebSearch] Garimpando na web por: '{query}'")

    # Encode query and add ext:pdf to prefer direct file links
    safe_query = f"{query} filetype:pdf OR filetype:epub"
    encoded = urllib.parse.quote(safe_query)
    search_url = f"https://html.duckduckgo.com/html/?q={encoded}&kl=wt-wt"

    tmp_dir = os.path.join(os.path.expanduser("~"), ".research_tmp")
    os.makedirs(tmp_dir, exist_ok=True)

    try:
        resp = requests.get(search_url, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        return FetchResult(success=False, error=f"DuckDuckGo request failed: {e}", source="web_search")

    soup = BeautifulSoup(resp.text, "html.parser")
    # DuckDuckGo HTML result URLs
    result_links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "http" in href and "duckduckgo" not in href:
            resolved = _resolve_duckduckgo_redirect(href)
            if resolved not in result_links:
                result_links.append(resolved)

    pdf_links = [u for u in result_links if _is_valid_pdf_url(u)]

    if not pdf_links:
        return FetchResult(
            success=False,
            error=f"No direct PDF/EPUB links found for query: {query!r}",
            source="web_search",
            items_found=0,
        )

    if len(pdf_links) > max_results:
        pdf_links = pdf_links[:max_results]

    downloaded_paths = []
    for i, url in enumerate(pdf_links):
        print(f"  [{i+1}/{len(pdf_links)}] Downloading: {url[:80]}")
        try:
            file_resp = requests.get(url, headers=_HEADERS, stream=True, timeout=30)
            file_resp.raise_for_status()

            content_disp = file_resp.headers.get("Content-Disposition", "")
            filename_match = re.search(r'filename="?([^";\n]+)', content_disp)
            if filename_match:
                filename = filename_match.group(1).strip()
            else:
                ext = os.path.splitext(url.split("?")[0])[1] or ".pdf"
                filename = f"webgarimpo_{i+1}{ext}"

            # Skip zero-length or HTML responses (some hosts serve HTML for PDF)
            ct = file_resp.headers.get("Content-Type", "")
            if "html" in ct.lower() and filename.endswith(".pdf"):
                print(f"    Skipping HTML response pretending to be PDF")
                continue

            tmp_path = os.path.join(tmp_dir, filename.replace("/", "_").replace("\\", "_"))
            with open(tmp_path, "wb") as f:
                for chunk in file_resp.iter_content(8192):
                    f.write(chunk)

            file_size = os.path.getsize(tmp_path)
            if file_size < 5000:  # Reject placeholder files
                print(f"    File too small ({file_size} bytes), skipping")
                os.remove(tmp_path)
                continue

            title = os.path.splitext(filename)[0].replace("_", " ").replace("-", " ")
            final_path = organize_paper(
                source_file=tmp_path,
                title=title,
                authors=["Web Extract"],
                year="Unknown",
                source="WebGarimpo"
            )
            if final_path:
                downloaded_paths.append(final_path)
                print(f"    ✅ Saved ({file_size:,} bytes): {final_path}")
            time.sleep(1)  # Be gentle
        except Exception as e:
            print(f"    ❌ Failed: {e}")
            continue

    return FetchResult(
        success=len(downloaded_paths) > 0,
        paths=downloaded_paths,
        error="" if downloaded_paths else "All web download attempts failed",
        source="web_search",
        items_found=len(pdf_links),
        metadata={"query": query, "links_found": len(result_links), "pdfs_found": len(pdf_links)}
    )
