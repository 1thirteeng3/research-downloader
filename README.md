# Research Downloader Agent 📚

An autonomous AI agent with a web chat interface for downloading scientific literature, books, and articles from academic databases (arXiv) and shadow libraries (Anna's Archive).

## Features
- 💬 **Chat Interface**: Natural language requests for downloading papers.
- 📄 **Batch Upload**: Upload `.txt` files with multiple queries.
- 🧠 **Smart Organization**: Automatically parses metadata and organizes downloads into semantic folders.
- ⚙️ **Dual Sources**: Fetches from **arXiv API** (papers) and **Anna's Archive** (books/seminars).

## Setup & Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/YOUR_USERNAME/research-downloader.git
   cd research-downloader
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   playwright install chromium
   ```

3. **Run the Application:**
   ```bash
   streamlit run app.py
   ```

## Folder Structure
- `app.py`: The Streamlit graphical interface.
- `backend/`: The core python scripts powering the agent.
  - `main.py`: CLI orchestrator.
  - `arxiv_fetcher.py`: Official arXiv API module.
  - `shadow_scraper.py`: Playwright scraper for Anna's Archive.
  - `organizer.py`: Moves and renames files cleanly.
