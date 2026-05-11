"""
Research Downloader — Streamlit GUI
====================================
Modos de execução:
  • Script (Dumb)  → Cascade fixa: arXiv → Anna's Archive → Web Search
  • ReAct (Smart)  → Agente LLM que planeja e decide rotas dinamicamente

Cada fetcher retorna FetchResult para o cascade sempre saber o que rolou.
"""
import streamlit as st
import time
import json
import os
import re
import sys
from datetime import datetime

# ── Path setup so backend modules import correctly ──
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))
from backend.result import FetchResult

# ═══════════════════════════════════════════════════════
#  PAGE CONFIG
# ═══════════════════════════════════════════════════════
st.set_page_config(
    page_title="Research Downloader",
    page_icon="📚",
    layout="wide",
    menu_items={
        "About": "📖 Research Downloader — SOTA Cascade Fetcher\n"
                 "Modes: Script (dumb) | ReAct (intelligent)\n"
                 "Sources: arXiv → Anna's Archive → Sci-Hub → Web Search"
    }
)

# ═══════════════════════════════════════════════════════
#  CUSTOM CSS
# ═══════════════════════════════════════════════════════
st.markdown("""
<style>
    .main-header {
        font-size: 2rem;
        font-weight: 700;
        color: #1a1a2e;
        margin-bottom: 0.2rem;
    }
    .sub-header {
        font-size: 0.9rem;
        color: #666;
        margin-bottom: 1.5rem;
    }
    .status-box {
        padding: 0.6rem 1rem;
        border-radius: 8px;
        font-family: monospace;
        font-size: 0.82rem;
        margin-bottom: 0.4rem;
    }
    .status-arxiv  { background: #e3f2fd; border-left: 4px solid #1565c0; color: #0d47a1; }
    .status-anna   { background: #f3e5f5; border-left: 4px solid #6a1b9a; color: #4a148c; }
    .status-web    { background: #fff3e0; border-left: 4px solid #e65100; color: #bf360c; }
    .status-done   { background: #e8f5e9; border-left: 4px solid #2e7d32; color: #1b5e20; }
    .status-error  { background: #ffebee; border-left: 4px solid #c62828; color: #b71c1c; }
    .metric-card {
        background: #f8f9fa;
        border-radius: 12px;
        padding: 1rem;
        text-align: center;
        border: 1px solid #dee2e6;
    }
    .metric-number {
        font-size: 2rem;
        font-weight: 700;
        color: #1a1a2e;
    }
    .metric-label {
        font-size: 0.75rem;
        color: #666;
        text-transform: uppercase;
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: 6px;
    }
    .stTabs [data-baseweb="tab"] {
        padding: 8px 16px;
        border-radius: 6px 6px 0 0;
    }
    .download-item {
        background: #f1f3f5;
        border-radius: 8px;
        padding: 0.6rem 1rem;
        margin-bottom: 0.4rem;
        font-size: 0.85rem;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }
    .chat-bubble-user {
        background: #d4e8ff;
        border-radius: 12px 12px 2px 12px;
        padding: 0.7rem 1rem;
        margin-bottom: 0.5rem;
        max-width: 80%;
        margin-left: auto;
    }
    .chat-bubble-agent {
        background: #f1f3f5;
        border-radius: 12px 12px 12px 2px;
        padding: 0.7rem 1rem;
        margin-bottom: 0.5rem;
        max-width: 80%;
    }
</style>
""", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════
#  SESSION STATE
# ═══════════════════════════════════════════════════════
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "download_log" not in st.session_state:
    st.session_state.download_log = []
if "stats" not in st.session_state:
    st.session_state.stats = {"arxiv": 0, "annas": 0, "web": 0, "scihub": 0,
                               "total_downloaded": 0, "total_failed": 0}

# ═══════════════════════════════════════════════════════
#  SIDEBAR — Settings
# ═══════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("## ⚙️ Configurações")

    # Mode selector
    mode = st.radio(
        "Modo de Execução",
        ["🤖 Script (Dumb)", "🧠 ReAct (Intelligent)"],
        help="Script: cascade fixa sem LLM. ReAct: agente LLM planeja buscas."
    )
    is_react = "ReAct" in mode

    # API Key (only needed for ReAct)
    api_key = ""
    if is_react:
        api_key = st.text_input(
            "🔑 OpenAI API Key",
            type="password",
            help="Necesária apenas para o modo ReAct. A chave é usada diretamente, não armazenada."
        )
        if not api_key:
            st.warning("⚠️ Insira sua API Key para usar o modo ReAct.")
            st.stop()
        model_name = st.selectbox(
            "🤖 Modelo",
            ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
            index=0
        )
    else:
        model_name = None

    st.divider()

    # Source preferences
    st.markdown("### 🎯 Fontes Preferidas")
    use_arxiv = st.checkbox("arXiv (Open Science)", value=True)
    use_annas = st.checkbox("Anna's Archive (Shadow)", value=True)
    use_web   = st.checkbox("Web Search (Garimpo)", value=True)
    use_scihub = st.checkbox("Sci-Hub (DOI)", value=False)

    st.divider()

    # Max results slider
    max_results = st.slider("Máx. resultados por query", 1, 20, 5)

    # Language filter
    lang_filter = st.text_input("🌐 Filtro de idioma (ex: en, fr, pt, es)", "")

    st.divider()

    # Stats
    st.markdown("### 📊 Estatísticas")
    cols = st.columns(2)
    cols[0].metric("📚 Baixados", st.session_state.stats["total_downloaded"])
    cols[1].metric("❌ Falhas", st.session_state.stats["total_failed"])

    st.markdown(f"""
    <div style="font-size:0.78rem; color:#888; margin-top:0.5rem;">
    arXiv: {st.session_state.stats['arxiv']} ·
    Anna's: {st.session_state.stats['annas']} ·
    Web: {st.session_state.stats['web']} ·
    SciHub: {st.session_state.stats['scihub']}
    </div>
    """, unsafe_allow_html=True)

    st.divider()

    # Clear button
    if st.button("🗑️ Limpar Histórico"):
        st.session_state.chat_history = []
        st.session_state.download_log = []
        st.rerun()

# ═══════════════════════════════════════════════════════
#  MAIN CONTENT
# ═══════════════════════════════════════════════════════
st.markdown('<div class="main-header">📚 Research Downloader</div>', unsafe_allow_html=True)
st.markdown(
    f'<div class="sub-header">'
    f'Cascade: arXiv → Anna\'s Archive → Web Search | '
    f'Modo: {"🧠 ReAct (Intelligent)" if is_react else "🤖 Script (Dumb)"}'
    f'</div>',
    unsafe_allow_html=True
)

# ── Chat area ────────────────────────────────────────────────────────────
chat_container = st.container()
with chat_container:
    for entry in st.session_state.chat_history:
        if entry["role"] == "user":
            st.markdown(
                f'<div class="chat-bubble-user"><strong>Você:</strong> {entry["content"]}</div>',
                unsafe_allow_html=True
            )
        else:
            st.markdown(
                f'<div class="chat-bubble-agent"><strong>🤖 Agente:</strong><br>{entry["content"]}</div>',
                unsafe_allow_html=True
            )

# ── Input section ────────────────────────────────────────────────────────
st.markdown("### 💬 O que você quer baixar?")

col1, col2 = st.columns([4, 1])
with col1:
    user_input = st.text_input(
        "Prompt",
        placeholder="Ex: Baixe artigos SOTA de Integrated Information Theory (IIT) no arXiv...",
        label_visibility="collapsed",
    )
with col2:
    uploaded_file = st.file_uploader("📄 ou envie .txt com links", type=["txt"], label_visibility="collapsed")

# Process file upload
file_content = ""
if uploaded_file is not None:
    try:
        content_bytes = uploaded_file.read()
        file_content = content_bytes.decode("utf-8", errors="ignore")
        st.success(f"✅ {uploaded_file.name} carregado ({len(file_content.splitlines())} linhas)")
    except Exception as e:
        st.error(f"Erro ao ler arquivo: {e}")

# Submit button
col_btn1, col_btn2 = st.columns([1, 5])
with col_btn1:
    submitted = st.button("▶️ Executar", type="primary", use_container_width=True)

if submitted:
    queries_to_process = []

    # Parse text input
    if user_input.strip():
        queries_to_process.append(("text", user_input.strip()))

    # Parse file
    if file_content:
        lines = [l.strip() for l in file_content.splitlines() if l.strip()]
        for line in lines:
            if line.startswith("http"):
                queries_to_process.append(("link", line))
            else:
                queries_to_process.append(("query", line))

    if not queries_to_process:
        st.warning("Nenhuma query para processar. Digite algo ou envie um arquivo.")
    else:
        with st.spinner(f"Processando {len(queries_to_process)} queries em modo {'ReAct' if is_react else 'Script'}..."):
            for qtype, qvalue in queries_to_process:
                # Add user message to chat
                label = f"[{qtype.upper()}] {qvalue[:100]}"
                st.session_state.chat_history.append({
                    "role": "user",
                    "content": label,
                    "timestamp": datetime.now().isoformat()
                })

                # Build status placeholder
                status_placeholder = st.empty()
                log_lines = []

                def log(msg: str, level: str = "info"):
                    ts = datetime.now().strftime("%H:%M:%S")
                    line = f"[{ts}] {msg}"
                    log_lines.append((level, line))
                    status_text = "\n".join(
                        f"{'  ' * (0 if l[0] != 'step' else 1)}{l[1]}" for l in log_lines
                    )
                    status_placeholder.markdown(
                        f"```\n{status_text}\n```"
                    )

                log(f"▶️ Query: {qvalue[:80]}")
                log(f"   Mode: {'ReAct' if is_react else 'Script'} | Max results: {max_results}", level="step")

                # ── Import and run ──────────────────────────────────────────
                from backend.arxiv_fetcher import download_from_arxiv
                from backend.shadow_scraper import download_from_annas_archive, download_from_scihub
                from backend.web_search_fetcher import download_from_web_search

                downloaded_paths = []
                errors = []

                if is_react:
                    log("🧠 Iniciando agente ReAct...", level="step")
                    from backend.cascade_fetcher import run_cascade_react

                    result = run_cascade_react(
                        query=qvalue,
                        api_key=api_key,
                        model=model_name,
                        max_results=max_results,
                        verbose=True,
                    )
                    if result.success:
                        downloaded_paths = result.paths
                    errors.append(result.error) if result.error else None

                else:
                    log("🤖 Executando cascade em modo Script...", level="step")

                    # ── Normalize query so URLs/IDs are parsed before fetching ──
                    from backend.cascade_fetcher import normalize_query
                    norm_query, norm_arxiv_id, norm_doi = normalize_query(qvalue)
                    if norm_arxiv_id:
                        log(f"   🔎 Parsed arXiv ID: {norm_arxiv_id}")
                    if norm_doi:
                        log(f"   🔎 Parsed DOI: {norm_doi}")

                    # Use run_cascade_script which handles the full cascade
                    from backend.cascade_fetcher import run_cascade_script
                    result = run_cascade_script(
                        query=norm_query,
                        arxiv_id=norm_arxiv_id,
                        doi=norm_doi,
                        preferred_source=None,
                        max_results=max_results,
                        lang=lang_filter,
                        verbose=True,
                    )
                    if result.success:
                        downloaded_paths = result.paths
                        # Update stats by source
                        src_counts = {}
                        for p in result.paths:
                            src = result.source or "script"
                            src_counts[src] = src_counts.get(src, 0) + 1
                        for src, cnt in src_counts.items():
                            if src == "arxiv":
                                st.session_state.stats["arxiv"] += cnt
                            elif src in ("annas_archive", "Anna's Archive"):
                                st.session_state.stats["annas"] += cnt
                            elif src == "web_search":
                                st.session_state.stats["web"] += cnt
                            elif src == "scihub":
                                st.session_state.stats["scihub"] += cnt
                    if result.error:
                        errors.append(result.error)

                # ── Update stats ───────────────────────────────────────────
                st.session_state.stats["total_downloaded"] += len(downloaded_paths)
                if not downloaded_paths:
                    st.session_state.stats["total_failed"] += 1

                # ── Add agent response to chat ─────────────────────────────
                if downloaded_paths:
                    paths_str = "\n".join([f"  • `{p}`" for p in downloaded_paths])
                    agent_msg = (
                        f"✅ **{len(downloaded_paths)} arquivo(s) baixado(s)**\n\n"
                        f"{paths_str}\n\n"
                        f"_Mode: {'ReAct' if is_react else 'Script'} | "
                        f"Total nesta sessão: {st.session_state.stats['total_downloaded']}_"
                    )
                else:
                    agent_msg = (
                        f"❌ Nenhum arquivo baixado para esta query.\n\n"
                        f"_Erro: {errors[0] if errors else 'Sem detalhes'}_"
                    )

                st.session_state.chat_history.append({
                    "role": "agent",
                    "content": agent_msg,
                    "timestamp": datetime.now().isoformat(),
                    "paths": downloaded_paths
                })

                # Sleep between queries to respect rate limits
                time.sleep(3)

        st.rerun()

# ═══════════════════════════════════════════════════════
#  DOWNLOAD LOG / HISTORY
# ═══════════════════════════════════════════════════════
with st.expander("📋 Histórico de Downloads", expanded=False):
    for entry in st.session_state.chat_history:
        if entry.get("paths"):
            for p in entry["paths"]:
                st.markdown(f"- `{p}`")