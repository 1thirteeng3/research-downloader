"""
shadow_scraper.py
Shadow library search using requests (no Playwright dependency).
Searches LibGen JSON API and multiple Anna's Archive / LibGen mirrors.

NOTE: Python 3.13 + Windows + Playwright has known asyncio/subprocess
      incompatibility issues. This module uses requests only.
"""
import os
import re
import time
import requests
from urllib.parse import quote
from organizer import organize_paper
from result import FetchResult

# ── SSL workaround for environments with broken certs ──
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
SSL_VERIFY = False  # Set True if your network is fine

# ── Mirror list ──────────────────────────────────────────
_LIBGEN_JSON_MIRRORS = [
    "https://libgen.li/json.php",
    "https://libgen.is/json.php",
    "https://libgen.fun/json.php",
]
_LIBGEN_BOOK_MIRRORS = [
    "https://libgen.li/ads/author/",
    "https://libgen.is/ads/author/",
    "https://libgen.fun/ads/author/",
]
_ANNA_SEARCH_PATHS = [
    "/search?q=",
]


def download_from_annas_archive(
    query: str,
    max_results: int = 3,
    lang: str = "",
) -> FetchResult:
    """
    Search Anna's Archive (shadow library aggregator) and LibGen mirrors.
    Falls back gracefully through multiple mirrors.

    Returns FetchResult with:
      - success: bool
      - paths:   list of downloaded file paths
      - error:   error message (empty on success)
      - source:  'annas_archive'
    """
    if not query or not query.strip():
        return FetchResult(False, [], "Empty query", "annas_archive")

    search_q = query.strip()
    if lang:
        search_q = f"{search_q} {lang}"
    encoded_q = quote(search_q)

    downloaded_paths = []
    errors = []
    all_mirror_errors = []

    # ── Method 1: LibGen JSON API (most reliable) ──────────
    for mirror in _LIBGEN_JSON_MIRRORS:
        try:
            url = f"{mirror}?ids=1&req={encoded_q}"
            if verbose_fetching:
                print(f"  [Anna's/LibGen] Trying: {url[:100]}")
            resp = requests.get(
                url,
                params={"ids": 1, "req": search_q},
                headers={"User-Agent": "Mozilla/5.0 (compatible; ResearchDownloader/1.0)"},
                timeout=15,
                verify=SSL_VERIFY,
            )
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    if isinstance(data, list) and len(data) > 0:
                        item = data[0]
                        # LibGen JSON returns {id, title, authors, ...}
                        title = item.get("title", search_q)[:80]
                        author = item.get("authors", "Unknown")
                        year = item.get("year", "")
                        md5 = item.get("md5", "")
                        if md5:
                            # Try to get a download link via the LibGen "get" endpoint
                            dl_url = f"https://libgen.li/get?md5={md5}"
                            paths = _try_download_book(dl_url, title, author, year)
                            if paths:
                                return FetchResult(True, paths, "", "annas_archive")
                except Exception:
                    pass  # Try next mirror
        except Exception as e:
            all_mirror_errors.append(f"{mirror}: {e}")
            continue

    # ── Method 2: Anna's Archive search page (requests-based) ──
    anna_domains = ["annas-archive.gs", "annas-archive.li", "annas-archive.se"]
    for domain in anna_domains:
        try:
            search_url = f"https://{domain}/search?q={encoded_q}"
            if verbose_fetching:
                print(f"  [Anna's] Trying: {search_url[:100]}")
            resp = requests.get(
                search_url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept-Language": "en-US,en;q=0.9",
                },
                timeout=15,
                verify=SSL_VERIFY,
            )
            if resp.status_code == 200:
                # Look for /md5/ links in the response
                md5_links = re.findall(r'href="(/md5/[a-f0-9]{32})"', resp.text)
                if md5_links:
                    md5_links = list(dict.fromkeys(md5_links))[:max_results]
                    for md5_path in md5_links:
                        detail_url = f"https://{domain}{md5_path}"
                        paths = _scrape_annas_detail(detail_url, domain, search_q)
                        if paths:
                            downloaded_paths.extend(paths)
                            if len(downloaded_paths) >= max_results:
                                return FetchResult(True, downloaded_paths[:max_results], "", "annas_archive")
        except Exception as e:
            all_mirror_errors.append(f"{domain}: {e}")
            continue

    # ── Method 3: LibGen book-page scrape ────────────────────
    book_paths = _search_libgen_book_pages(search_q, max_results)
    if book_paths:
        downloaded_paths.extend(book_paths)

    error_msg = " | ".join(all_mirror_errors) if all_mirror_errors else ""
    return FetchResult(
        success=bool(downloaded_paths),
        paths=downloaded_paths[:max_results],
        error=error_msg,
        source="annas_archive",
    )


def _scrape_annas_detail(detail_url: str, domain: str, fallback_title: str) -> list:
    """Try to get a download link from an Anna's Archive detail page."""
    try:
        resp = requests.get(
            detail_url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            timeout=15,
            verify=SSL_VERIFY,
        )
        if resp.status_code != 200:
            return []

        # Look for download buttons / mirror links
        # Pattern: links containing .pdf, .epub, or pointing to libgen
        links = re.findall(r'href="([^"]*\.(?:pdf|epub|mobi)[^"]*)"', resp.text, re.I)
        if not links:
            # Try looking for libgen redirect links
            links = re.findall(r'href="([^"]*libgen[^"]*)"', resp.text, re.I)

        for link in links[:3]:
            if link.startswith("//"):
                link = "https:" + link
            elif not link.startswith("http"):
                link = f"https://{domain}{link}"
            if link.endswith(".pdf") or link.endswith(".epub"):
                return _try_download_book(link, fallback_title, "Unknown", "")
    except Exception:
        pass
    return []


def _search_libgen_book_pages(query: str, max_results: int) -> list:
    """Search LibGen for book pages using their search endpoint."""
    paths = []
    encoded_q = quote(query)
    for mirror in _LIBGEN_BOOK_MIRRORS:
        try:
            search_url = f"{mirror}{encoded_q}"
            resp = requests.get(
                search_url,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=10,
                verify=SSL_VERIFY,
                allow_redirects=True,
            )
            if resp.status_code == 200 and (".pdf" in resp.text.lower() or ".epub" in resp.text.lower()):
                # Try to extract direct download link
                pdf_links = re.findall(r'href="([^"]*\.pdf[^"]*)"', resp.text, re.I)
                for pdf_url in pdf_links[:2]:
                    if not pdf_url.startswith("http"):
                        pdf_url = "https://libgen.li" + pdf_url
                    downloaded = _try_download_book(pdf_url, query[:60], "LibGen", "")
                    if downloaded:
                        paths.extend(downloaded)
                        if len(paths) >= max_results:
                            return paths[:max_results]
        except Exception:
            continue
    return paths


def _try_download_book(url: str, title: str, author: str, year: str) -> list:
    """Attempt to download a book/paper from a direct URL. Returns list of paths."""
    paths = []
    try:
        tmp_dir = os.path.join(os.path.expanduser("~"), ".research_tmp")
        os.makedirs(tmp_dir, exist_ok=True)

        safe_title = "".join(c for c in title[:40] if c.isalnum() or c in " -_").strip()
        ext = ".pdf" if ".pdf" in url.lower() else ".epub"
        tmp_path = os.path.join(tmp_dir, f"annas_{safe_title}{ext}")

        resp = requests.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://libgen.li/",
            },
            stream=True,
            timeout=30,
            verify=SSL_VERIFY,
        )
        resp.raise_for_status()

        with open(tmp_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)

        final_path = organize_paper(
            source_file=tmp_path,
            title=title,
            authors=[author] if author else ["Unknown"],
            year=str(year) if year else "",
            source="Anna's Archive",
        )
        if final_path:
            paths.append(final_path)
    except Exception:
        pass
    return paths


# ─────────────────────────────────────────────
# Sci-Hub fetcher
# ─────────────────────────────────────────────

_SCIHUB_MIRRORS = [
    "https://sci-hub.se",
    "https://sci-hub.st",
    "https://sci-hub.ru",
    "https://sci-hub.m先进",
]


def download_from_scihub(doi: str) -> FetchResult:
    """
    Download a paper from Sci-Hub using its DOI.
    Tries multiple Sci-Hub mirrors until one works.

    Returns FetchResult with paths on success.
    """
    if not doi:
        return FetchResult(False, [], "No DOI provided", "scihub")

    doi = doi.strip().rstrip("/")
    downloaded_paths = []
    errors = []

    for base in _SCIHUB_MIRRORS:
        try:
            # Sci-Hub accepts: https://sci-hub.se/10.1038/nature12373
            url = f"{base}/{doi}"
            if verbose_fetching:
                print(f"  [Sci-Hub] Trying: {url}")

            resp = requests.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Referer": base + "/",
                },
                timeout=30,
                verify=SSL_VERIFY,
                allow_redirects=True,
            )

            if resp.status_code == 200:
                content_type = resp.headers.get("Content-Type", "")
                if "pdf" in content_type or resp.content[:4] == b"%PDF":
                    tmp_dir = os.path.join(os.path.expanduser("~"), ".research_tmp")
                    os.makedirs(tmp_dir, exist_ok=True)
                    safe_doi = "".join(c for c in doi[:40] if c.isalnum() or c in ".-").strip()
                    tmp_path = os.path.join(tmp_dir, f"scihub_{safe_doi}.pdf")
                    with open(tmp_path, "wb") as f:
                        f.write(resp.content)

                    final_path = organize_paper(
                        source_file=tmp_path,
                        title=f"Sci-Hub: {doi}",
                        authors=["Unknown"],
                        year="",
                        source="Sci-Hub",
                    )
                    if final_path:
                        downloaded_paths.append(final_path)
                        return FetchResult(True, downloaded_paths, "", "scihub")
        except Exception as e:
            errors.append(f"{base}: {e}")
            continue

    return FetchResult(
        success=bool(downloaded_paths),
        paths=downloaded_paths,
        error=f"All {len(_SCIHUB_MIRRORS)} Sci-Hub mirrors failed. Errors: {' | '.join(errors[:3']}" if errors else "Unknown error",
        source="scihub",
    )


# Module-level verbose flag (set by cascade_fetcher when verbose=True)
verbose_fetching = False
