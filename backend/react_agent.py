import json
from openai import OpenAI
from arxiv_fetcher import download_from_arxiv
from shadow_scraper import download_from_annas_archive

def run_react_agent(query, api_key, max_results=3):
    client = OpenAI(api_key=api_key)
    
    tools = [
        {
            "type": "function",
            "function": {
                "name": "download_from_arxiv",
                "description": "Download scientific papers from arXiv by natural language search query or specific arXiv ID. Use this for physics, mathematics, computer science, quantitative biology, quantitative finance, statistics, electrical engineering and systems science, and economics papers.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query for arXiv (e.g., 'Integrated Information Theory')"},
                        "arxiv_id": {"type": "string", "description": "Specific arXiv ID to download if explicitly provided (e.g., '1405.0126')"},
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "download_from_annas_archive",
                "description": "Download books, seminars, or articles from Anna's Archive (a shadow library). Use this for literature, humanities, books, and materials not found on arXiv.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query (e.g., 'Jacques Lacan Séminaire')"},
                        "lang": {"type": "string", "description": "Language code if requested (e.g., 'en', 'fr', 'pt', 'es'). Default is empty string."}
                    },
                    "required": ["query"]
                }
            }
        }
    ]
    
    messages = [
        {"role": "system", "content": "You are an intelligent Research Downloader Agent. Your job is to understand the user's request and use the provided tools to fetch the appropriate materials. Decide the best source (arXiv vs Anna's Archive) based on the nature of the request. Formulate clear search queries."},
        {"role": "user", "content": query}
    ]
    
    print(f"🧠 ReAct Agent thinking about: '{query}'")
    try:
        response = client.chat.completions.create(
            model="gpt-4o", # You can also use gpt-4o-mini
            messages=messages,
            tools=tools,
            tool_choice="auto"
        )
    except Exception as e:
        print(f"Error calling LLM API: {e}")
        return
        
    message = response.choices[0].message
    
    if message.tool_calls:
        for tool_call in message.tool_calls:
            function_name = tool_call.function.name
            args = json.loads(tool_call.function.arguments)
            
            if function_name == "download_from_arxiv":
                q = args.get("query")
                aid = args.get("arxiv_id")
                print(f"⚡ Action: Agent decided to use arXiv with query='{q}', arxiv_id='{aid}'")
                download_from_arxiv(query=q, arxiv_id=aid, max_results=max_results)
                
            elif function_name == "download_from_annas_archive":
                q = args.get("query")
                lang = args.get("lang", "")
                print(f"⚡ Action: Agent decided to use Anna's Archive with query='{q}', lang='{lang}'")
                download_from_annas_archive(query=q, max_results=max_results, lang=lang)
    else:
        print("Agent decided no tools were needed or couldn't understand the request.")
        if message.content:
            print(f"Agent response: {message.content}")
