"""
app.py — Interface Streamlit — 10 agents | 5 onglets
Pipeline Code en 2 phases : Analyse → Validation humaine → Écriture
"""

import os
import re
import subprocess
import requests as req_lib
import streamlit as st
from dotenv import load_dotenv
from crewai import Crew, Process, Task

load_dotenv()

st.set_page_config(page_title="Squad IA — Nolan", page_icon="🤖", layout="wide")
st.title("🤖 Squad IA")
st.caption("10 agents | CrewAI + Claude | FindUP & Techwatch")

# ── Init session_state (évite KeyError au premier chargement) ─────────────────
_SS_DEFAULTS = {
    "phase1_done":          False,
    "write_approved":       False,
    "analysis_result":      None,
    "analysis_tokens":      {},
    "security_task":        None,
    "security_context":     [],
    "backend_agent":        None,
    "analysis_project":     None,
    "analysis_root":        None,
    "analysis_instruction": None,
    "instruction_prefill":  "",
    "just_pushed":          False,
}
for _k, _v in _SS_DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v


# ── Shared helpers & config ───────────────────────────────────────────────────
from app_helpers import (
    PROJECT_ROOTS, RAILWAY_URL,
    _extract_metrics, _estimate_cost, _show_cost_metrics,
    _git_diff, _git_commit, _check_railway,
    _parse_written_files, _show_files_report,
    _extract_planned_files, _preprocess_instruction,
    _generate_pdf_report, _estimate_cost_before_launch,
)
from run_history import save_run, load_history, clear_history
from agents import make_agents
from tasks import (
    make_code_task_analysis, make_write_task,
    make_research_task, make_error_triage_task, make_claude_md_task,
)

# ── Tab renderers ─────────────────────────────────────────────────────────────
from tabs.tab_code         import render as render_code
from tabs.tab_recherche    import render as render_recherche
from tabs.tab_error_triage import render as render_error_triage
from tabs.tab_historique   import render as render_historique
from tabs.tab_claude_md    import render as render_claude_md
from tabs.tab_agent_direct import render as render_agent_direct
from tabs.tab_deployer     import render as render_deployer
from tabs.tab_autoagent    import render as render_autoagent


with st.sidebar:
    st.header("Agents")
    agents_info = [
        ("Chef d'Orchestre", "🧠", "Sonnet", "Planification"),
        ("Back-end",         "⚡", "Haiku",  "Implémentation"),
        ("Front-end",        "⚡", "Haiku",  "UI/React"),
        ("Testeur",          "⚡", "Haiku",  "Tests + pytest"),
        ("Build Fixer",      "⚡", "Haiku",  "Auto-correction"),
        ("Sécurité",         "🧠", "Sonnet", "Audit Antigravity"),
        ("Error Triage",     "⚡", "Haiku",  "Dispatch erreurs"),
        ("Cleaner n8n",      "⚡", "Haiku",  "HTML Techwatch"),
        ("Performance",      "⚡", "Haiku",  "N+1, bundle, CWV"),
        ("Chercheur Web",    "⚡", "Haiku",  "Recherche Tavily"),
    ]
    for name, icon, model, role in agents_info:
        st.write(f"{icon} **{name}** `{model}` — *{role}*")

    st.divider()
    st.header("Projets")
    for name, path in PROJECT_ROOTS.items():
        exists = os.path.exists(path)
        claude_md_path = os.path.join(path, "CLAUDE.md")
        has_claude_md = os.path.exists(claude_md_path)
        if has_claude_md:
            with open(claude_md_path, encoding="utf-8", errors="ignore") as _f:
                line_count = sum(1 for _ in _f)
            lines_label = f"`{line_count} lignes` {'✅' if line_count <= 150 else '⚠️ >150 (tokens fantômes)'}"
        else:
            lines_label = ""
        st.write(
            f"{'✅' if exists else '❌'}"
            f"{'📋' if has_claude_md else '⚠️'} "
            f"**{name}** {lines_label}"
        )

    st.divider()
    env_ok = all([os.environ.get("ANTHROPIC_API_KEY"), os.environ.get("TAVILY_API_KEY")])
    if env_ok:
        st.success("✅ Env OK")
    else:
        st.error("❌ Clés manquantes")


# ── Tabs ──────────────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs([
    "💻 Tâche Code",
    "🔍 Recherche Web",
    "🚨 Error Triage",
    "📜 Historique",
    "📝 CLAUDE.md",
    "💬 Agent Direct",
    "🚀 Déployer",
    "🧠 AutoAgent",
])

# ── Render ────────────────────────────────────────────────────────────────────
render_code(tab1)
render_recherche(tab2)
render_error_triage(tab3)
render_historique(tab4)
render_claude_md(tab5)
render_agent_direct(tab6)
render_deployer(tab7)
render_autoagent(tab8)
