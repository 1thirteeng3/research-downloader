"""
shadow_scraper.py
Search Anna's Archive and Sci-Hub for materials not on arXiv.
Anna's Archive: annas-archive.org (provides a unified search across Libgen, Z-Library, etc.)
Uses Playwright to handle Cloudflare anti-bot protections.
"""
import os
import re
import time
import requests
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from organizer import organize_paper
from result import FetchResult

# Anna's Archive domains (they rotate mirrors)
ANNA_DOMAINS = ["annas-archive.gs", "annas-archive.li", "annas-archive.se"]
_LIBGEN_EDITION_BASE = "https://libgen.li/ads/author/"  # fallback


def _get_annas_search_url(query: str, lang: str = "") -> str:
    domain = ANNA_DOMAINS[0]
    url = f"https://{domain}/search?q={requests.utils.quote(query)}"
    if lang:
        url += f"&lang={lang}"
    return url


def _get_detail_field(soup: BeautifulSoup, pattern: str) -> str:
    """Extract a text field from Anna's Archive detail page."""
    for el in soup.find_all(string=re.compile(pattern, re.I)):
        parent = el.find_parent()
        if parent:
            next_el = parent.find_next_sibling()
            if next_el:
                return next_el.get_text(strip=True)
    return "Unknown"


def _extract_annas_metadata(soup: BeautifulSoup) -> dict:
    """Parse title, author, year, isbn from an Anna's Archive detail page."""
    title = "Unknown Title"
    author = "Unknown Author"
    year = "Unknown"
    isbn = ""

    # Main title block
    title_el = soup.find(class_=re.compile(r"text-3xl|Title"))
    if title_el:
        title = title_el.get_text(strip=True)

    # Author under the title
    author_el = soup.find(class_=re.compile(r"italic|Author"))
    if not author_el:
        author_el = soup.find(string=re.compile(r"Author|author", re.I))
        if author_el:
            author_el = author_el.find_parent()
    if author_el:
        author = author_el.get_text(strip=True)

    year_el = soup.find(string=re.compile(r"Year|出版|year|publisher", re.I))
    if year_el:
        yr = re.search(r"\d{4}", str(year_el))
        if yr:
            year = yr.group()

    isbn_match = re.search(r"ISBN[:\s]*([\d\-X]{10,17})", soup.get_text(), re.I)
    if isbn_match:
        isbn = isbn_match.group(1)

    return {"title": title[:200], "author": author[:100], "year": year, "isbn": isbn}


def _download_from_libgen_fallback(title: str, author: str = "") -> list:
    """Fallback: try LibGen's JSON API when Anna's is blocked."""
    downloaded = []
    tmp_dir = os.path.join(os.path.expanduser("~"), ".research_tmp")
    os.makedirs(tmp_dir, exist_ok=True)

    search_url = f"https://libgen.li/json.php?ids=1&req={requests.utils.quote(title)}"
    if author:
        search_url += f"+{requests.utils.quote(author)}"

    try:
        print(f"  [LibGen fallback] Searching: {search_url}")
        resp = requests.get(search_url, timeout=15)
        items = resp.json() if resp.headers.get("content-type", "").find("json") != -1 else []
        for item in items[:3]:
            if item.get("src") or item.get("coverurl"):
                try:
                    file_url = item.get("src") or item.get("coverurl")
                    if not file_url.startswith("http"):
                        file_url = f"https://libgen.li/{file_url.lstrip('/')}"
                    ext = os.path.splitext(file_url.split("?")[0])[1] or ".pdf"
                    filename = f"libgen_{item.get('id', '0')}{ext}"
                    tmp_path = os.path.join(tmp_dir, filename)
                    headers = {"User-Agent": "ResearchDownloaderBot/1.0"}
                    r = requests.get(file_url, headers=headers, stream=True, timeout=30)
                    r.raise_for_status()
                    with open(tmp_path, "wb") as f:
                        for chunk in r.iter_content(8192):
                            f.write(chunk)
                    final = organize_paper(tmp_path,
                                           title=item.get("title", title),
                                           authors=[item.get("author", author)],
                                           year=item.get("year", ""),
                                           source="LibGen")
                    if final:
                        downloaded.append(final)
                except Exception as e:
                    print(f"  [LibGen item failed] {e}")
    except Exception as e:
        print(f"  [LibGen fallback failed] {e}")

    return downloaded


def download_from_annas_archive(query: str, max_results: int = 3, lang: str = "") -> FetchResult:
    """
    Search Anna's Archive for books/articles and download the files.
    Uses Playwright to bypass Cloudflare. Falls back to LibGen if blocked.
    Returns FetchResult with success, paths, error, source.
    """
    print(f"Searching Anna's Archive for '{query}' (lang: {lang or 'any'})...")

    downloaded_paths = []
    items_found = 0
    errors = []

    # --- Try Anna's Archive with Playwright ---
    for domain in ANNA_DOMAINS:
        if downloaded_paths:
            break

        print(f"  Trying domain: {domain}")
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                               "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                    extra_http_headers={"Accept-Language": f"{lang or 'en'}-US,en;q=0.9"}
                )
                page = context.new_page()

                search_url = _get_annas_search_url(query, lang)
                print(f"  Navigating to {search_url}...")
                page.goto(search_url, timeout=30000)
                page.wait_for_load_state("networkidle", timeout=15000)
                page.wait_for_timeout(2000)  # Let Cloudflare settle

                html = page.content()
                soup = BeautifulSoup(html, "html.parser")

                # Detect Cloudflare challenge
                if "cloudflare" in html.lower() or "checking your browser" in html.lower():
                    print(f"  [Cloudflare challenge detected on {domain}]")
                    errors.append(f"Cloudflare on {domain}")
                    browser.close()
                    continue

                # Extract MD5 result links
                md5_links = []
                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    if re.match(r"^/md5/[a-f0-9]{32}", href):
                        md5_links.append(href)
                        if len(md5_links) >= max_results:
                            break

                if not md5_links:
                    print(f"  No results found on {domain}")
                    errors.append(f"No results on {domain}")
                    browser.close()
                    continue

                print(f"  Found {len(md5_links)} results. Processing...")
                items_found = len(md5_links)

                tmp_dir = os.path.join(os.path.expanduser("~"), ".research_tmp")
                os.makedirs(tmp_dir, exist_ok=True)

                for md5_path in md5_links:
                    detail_url = f"https://{domain}{md5_path}"
                    print(f"  Fetching: {detail_url}")
                    page.goto(detail_url, timeout=30000)
                    page.wait_for_load_state("networkidle", timeout=15000)
                    page.wait_for_timeout(2000)

                    detail_html = page.content()
                    detail_soup = BeautifulSoup(detail_html, "html.parser")
                    meta = _extract_annas_metadata(detail_soup)
                    print(f"    Title: {meta['title'][:60]}")
                    print(f"    Author: {meta['author'][:60]}")

                    # Find download links (Slow / Fast server)
                    dl_url = None
                    for a in detail_soup.find_all("a", href=True):
                        href = a["href"]
                        text = a.get_text(strip=True)
                        if any(kw in text.lower() for kw in ["slow", "partner", "download", "file"]):
                            dl_url = href
                            if not dl_url.startswith("http"):
                                dl_url = f"https://{domain}{dl_url}"
                            break

                    if not dl_url:
                        print("    No download link found")
                        continue

                    # Navigate to download page to get actual file URL
                    page.goto(dl_url, timeout=30000)
                    page.wait_for_timeout(3000)

                    # Look for the final PDF/EPUB/DJVU link
                    final_html = page.content()
                    final_soup = BeautifulSoup(final_html, "html.parser")
                    file_link = None
                    for a in final_soup.find_all("a", href=True):
                        href = a["href"]
                        if any(href.lower().endswith(ext) for ext in [".pdf", ".epub", ".djvu", ".azw3"]):
                            file_link = href
                            if not file_link.startswith("http"):
                                file_link = f"https://{domain}{file_link}"
                            break

                    if not file_link:
                        # Try: directly click or follow "get" link
                        for a in final_soup.find_all("a", href=True):
                            if re.search(r"get|fetch|archive", a["href"], re.I):
                                file_link = a["href"]
                                if not file_link.startswith("http"):
                                    file_link = f"https://{domain}{file_link}"
                                break

                    if not file_link:
                        print("    Could not resolve final file URL")
                        errors.append(f"Could not get file for {meta['title'][:40]}")
                        continue

                    print(f"    Downloading: {file_link}")
                    try:
                        file_resp = requests.get(file_link, stream=True, timeout=60,
                                                headers={"User-Agent": "ResearchDownloaderBot/1.0"})
                        file_resp.raise_for_status()
                        ext = os.path.splitext(file_link.split("?")[0])[1] or ".pdf"
                        filename = f"annas_{md5_path.split('/')[-1]}{ext}"
                        tmp_path = os.path.join(tmp_dir, filename)
                        with open(tmp_path, "wb") as f:
                            for chunk in file_resp.iter_content(8192):
                                f.write(chunk)

                        final_path = organize_paper(
                            source_file=tmp_path,
                            title=meta["title"],
                            authors=[meta["author"]],
                            year=meta["year"],
                            source="Anna'sArchive"
                        )
                        if final_path:
                            downloaded_paths.append(final_path)
                            print(f"    Saved: {final_path}")
                            time.sleep(1)  # Be gentle
                    except Exception as e:
                        print(f"    Download failed: {e}")
                        errors.append(str(e))

                browser.close()

        except Exception as e:
            print(f"  [Anna's Archive error on {domain}] {e}")
            errors.append(f"{domain}: {e}")
            continue

    # --- Fallback to LibGen if Anna's failed ---
    if not downloaded_paths:
        print("  Falling back to LibGen JSON API...")
        libgen_results = _download_from_libgen_fallback(query)
        downloaded_paths.extend(libgen_results)

    return FetchResult(
        success=len(downloaded_paths) > 0,
        paths=downloaded_paths,
        error="; ".join(errors) if errors else "",
        source="annas_archive",
        items_found=items_found,
        metadata={"query": query, "lang": lang, "domains_tried": ANNA_DOMAINS}
    )


def download_from_scihub(doi: str, timeout: int = 30) -> FetchResult:
    """
    Download paper via Sci-Hub given a DOI.
    Sci-Hub domains rotate frequently; try common ones.
    """
    print(f"Searching Sci-Hub for DOI: {doi}...")
    scihub_domains = ["https://sci-hub.se", "https://sci-hub.st", "https://sci-hub.ru"]
    downloaded = []

    for base in scihub_domains:
        try:
            url = f"{base}/{doi}"
            resp = requests.get(url, timeout=timeout,
                               headers={"User-Agent": "ResearchDownloaderBot/1.0"})
            if resp.status_code == 200:
                tmp_dir = os.path.join(os.path.expanduser("~"), ".research_tmp")
                os.makedirs(tmp_dir, exist_ok=True)
                tmp_path = os.path.join(tmp_dir, f"scihub_{doi.replace('/','_')}.pdf")
                with open(tmp_path, "wb") as f:
                    for chunk in resp.iter_content(8192):
                        f.write(chunk)
                final = organize_paper(tmp_path, title=f"SciHub:{doi}",
                                      authors=["Unknown"], year="", source="SciHub")
                if final:
                    downloaded.append(final)
                return FetchResult(success=True, paths=downloaded, source="scihub",
                                  metadata={"doi": doi, "domain": base})
        except Exception as e:
            print(f"  Sci-Hub domain {base} failed: {e}")
            continue

    return FetchResult(success=False, error=f"Could not fetch DOI {doi} from any Sci-Hub domain",
                      source="scihub", metadata={"doi": doi})


if __name__ == "__main__":
    result = download_from_annas_archive("Jacques Lacan Séminaire", max_results=1, lang="fr")
    print(f"Success: {result.success}, Paths: {result.paths}")
