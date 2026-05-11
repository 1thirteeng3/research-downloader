import streamlit as st
import subprocess
import os

st.set_page_config(page_title="Research Downloader", page_icon="📚", layout="centered")

st.title("📚 SOTA Research Downloader")
st.markdown("Ask the agent to download materials (papers, books) from **arXiv** or **Anna's Archive**.")

# Chat history
if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "assistant", "content": "Hello! I am your Research Downloader agent. What would you like me to fetch today?"}]

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# File uploader for batch queries
with st.sidebar:
    st.header("Batch Upload")
    uploaded_file = st.file_uploader("Upload a .txt file with queries (one per line)", type=["txt"])
    max_results = st.number_input("Max results per query", min_value=1, max_value=10, value=3)

prompt = st.chat_input("Ex: Download SOTA papers on IIT from arxiv")

def run_agent(query):
    # Heuristic parsing of the prompt
    source = "anna" if "lacan" in query.lower() or "anna" in query.lower() or "book" in query.lower() else "arxiv"
    
    cmd = ["python", "backend/main.py", "--query", query, "--source", source, "--max-results", str(max_results)]
    
    st.session_state.messages.append({"role": "assistant", "content": f"Running search on **{source.upper()}** for: `{query}`..."})
    with st.chat_message("assistant"):
        st.markdown(f"Running search on **{source.upper()}** for: `{query}`...")
        
        with st.spinner("Downloading... This might take a while."):
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=os.path.dirname(os.path.abspath(__file__)))
            output = result.stdout + "\n" + result.stderr
            st.code(output)
            st.session_state.messages.append({"role": "assistant", "content": f"```text\n{output}\n```"})

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    run_agent(prompt)

if uploaded_file is not None:
    content = uploaded_file.read().decode("utf-8")
    queries = [q.strip() for q in content.split('\n') if q.strip()]
    if st.sidebar.button("Run Batch Download"):
        for q in queries:
            st.session_state.messages.append({"role": "user", "content": f"*(Batch)* {q}"})
            run_agent(q)
            st.rerun()
