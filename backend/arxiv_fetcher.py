import arxiv
import os
from organizer import organize_paper

def download_from_arxiv(query=None, max_results=3, arxiv_id=None):
    client = arxiv.Client()
    
    if arxiv_id:
        print(f"Searching arXiv for ID: {arxiv_id}")
        search = arxiv.Search(id_list=[arxiv_id])
    elif query:
        print(f"Searching arXiv for query: '{query}' (max {max_results} results)")
        search = arxiv.Search(
            query=query,
            max_results=max_results,
            sort_by=arxiv.SortCriterion.Relevance
        )
    else:
        print("Error: Must provide either a query or an arxiv_id.")
        return

    tmp_dir = "/home/.z/workspaces/research_tmp"
    os.makedirs(tmp_dir, exist_ok=True)

    try:
        results = list(client.results(search))
    except Exception as e:
        print(f"Error fetching from arXiv: {e}")
        return

    if not results:
        print("No results found.")
        return

    for paper in results:
        print(f"\n--- Found Paper ---")
        print(f"Title: {paper.title}")
        print(f"Authors: {', '.join([author.name for author in paper.authors])}")
        print(f"Published: {paper.published.year}")
        print(f"Entry ID: {paper.entry_id}")
        
        # Download to tmp
        print("Downloading PDF...")
        tmp_filename = f"{paper.get_short_id()}.pdf"
        tmp_path = os.path.join(tmp_dir, tmp_filename)
        
        try:
            import requests
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
            pdf_url = paper.pdf_url
            if not pdf_url.endswith(".pdf"):
                 pdf_url += ".pdf"
            response = requests.get(pdf_url, headers=headers, stream=True)
            response.raise_for_status()
            with open(tmp_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
        except Exception as e:
            print(f"Failed to download with requests, fallback to arxiv: {e}")
            paper.download_pdf(dirpath=tmp_dir, filename=tmp_filename)
        
        # Organize into SecondBrain
        organize_paper(
            source_file=tmp_path,
            title=paper.title,
            authors=[author.name for author in paper.authors],
            year=paper.published.year,
            source="arXiv"
        )
