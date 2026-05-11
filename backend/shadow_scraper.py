import os
import re
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from organizer import organize_paper

def download_from_annas_archive(query, max_results=3, lang=""):
    print(f"Searching Anna's Archive for '{query}' (lang: {lang})...")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"}
        )
        page = context.new_page()
        
        # Using .gs or .li as fallback domains often used by Anna's Archive
        domain = "annas-archive.gs"
        search_url = f"https://{domain}/search?q={query}"
        if lang:
            search_url += f"&lang={lang}"
            
        try:
            print(f"Navigating to {search_url}...")
            page.goto(search_url, timeout=30000)
            page.wait_for_timeout(3000) # Wait for potential JS/Cloudflare
        except Exception as e:
            print(f"Failed to access Anna's Archive (possibly blocked by Cloudflare/ISP): {e}")
            browser.close()
            return
            
        html = page.content()
        soup = BeautifulSoup(html, 'html.parser')
        
        # Anna's archive search results are usually in <a> tags with href starting with /md5/
        links = soup.find_all('a', href=re.compile(r'^/md5/'))
        
        if not links:
            print("No results found or blocked by captcha.")
            browser.close()
            return
            
        results_processed = 0
        md5_links = []
        for link in links:
            href = link.get('href')
            if href not in md5_links:
                md5_links.append(href)
                results_processed += 1
            if results_processed >= max_results:
                break
                
        print(f"Found {len(md5_links)} books.")
        
        tmp_dir = os.path.join(os.path.expanduser("~"), ".research_tmp")
        os.makedirs(tmp_dir, exist_ok=True)
        
        for md5 in md5_links:
            detail_url = f"https://{domain}{md5}"
            print(f"Fetching details from {detail_url}")
            try:
                page.goto(detail_url, timeout=30000)
                page.wait_for_timeout(2000)
            except Exception as e:
                print(f"Failed to load detail page: {e}")
                continue
            
            detail_html = page.content()
            detail_soup = BeautifulSoup(detail_html, 'html.parser')
            
            # Extract title and author for metadata
            title_el = detail_soup.find(class_='text-3xl font-bold')
            author_el = detail_soup.find(class_='italic')
            
            title = title_el.text.strip() if title_el else "Unknown Title"
            author = author_el.text.strip() if author_el else "Unknown Author"
            print(f"Title: {title} | Author: {author}")
            
            # Find the download mirror links
            # We look for the "Slow Partner Server #1" or similar
            download_links = detail_soup.find_all('a', href=True)
            dl_page_url = None
            for a in download_links:
                if 'Slow Partner Server' in a.text or 'Browser downloads' in a.text or 'Libgen' in a.text:
                    dl_page_url = a['href']
                    break
            
            if dl_page_url:
                if not dl_page_url.startswith('http'):
                    dl_page_url = f"https://{domain}{dl_page_url}"
                print(f"Found download page: {dl_page_url}")
                print(f"Note: Deep downloading from mirrors requires handling mirror-specific HTML and captchas.")
                print(f"For now, we have identified the mirror link. Manual intervention might be needed for the final PDF/EPUB if it has a wait timer.")
                # We would implement the specific mirror downloader here
                # E.g., navigating to dl_page_url, finding the actual .pdf/.epub href, and downloading it.
            else:
                print("Could not find a valid download mirror.")
                
        browser.close()

if __name__ == "__main__":
    download_from_annas_archive("Jacques Lacan Séminaire", max_results=1, lang="fr")
