import argparse
import sys
from arxiv_fetcher import download_from_arxiv
from shadow_scraper import download_from_annas_archive
from react_agent import run_react_agent

def main():
    parser = argparse.ArgumentParser(description="Research Downloader Agent")
    parser.add_argument("--query", type=str, help="Search query for literature")
    parser.add_argument("--source", type=str, choices=["arxiv", "anna"], default="arxiv", help="Source to download from")
    parser.add_argument("--max-results", type=int, default=3, help="Maximum number of results to download")
    parser.add_argument("--arxiv-id", type=str, help="Direct arXiv ID to download")
    parser.add_argument("--lang", type=str, default="", help="Language filter (e.g., 'fr', 'en') for Anna's Archive")
    parser.add_argument("--mode", type=str, choices=["heuristic", "react"], default="heuristic", help="Execution mode")
    parser.add_argument("--api-key", type=str, help="OpenAI API key for ReAct mode")
    
    args = parser.parse_args()

    if args.mode == "react":
        if not args.api_key:
            print("Error: --api-key is required for ReAct mode.")
            sys.exit(1)
        run_react_agent(query=args.query, api_key=args.api_key, max_results=args.max_results)
    else:
        if args.source == "arxiv" or args.arxiv_id:
            print("Initializing arXiv fetcher...")
            download_from_arxiv(query=args.query, max_results=args.max_results, arxiv_id=args.arxiv_id)
        elif args.source == "anna":
            print("Initializing Anna's Archive fetcher...")
            download_from_annas_archive(query=args.query, max_results=args.max_results, lang=args.lang)
        else:
            print(f"Source '{args.source}' is not yet implemented.")
            sys.exit(1)

if __name__ == "__main__":
    main()
