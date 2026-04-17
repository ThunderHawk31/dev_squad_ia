"""
tabs/tab_recherche.py — Onglet "Recherche Web"
"""
import os
import re
import subprocess
import streamlit as st
from crewai import Crew, Process, Task
from agents import make_agents
from tasks import (
    make_code_task_analysis, make_write_task,
    make_research_task, make_error_triage_task, make_claude_md_task,
    _build_function_index,
)
from run_history import save_run, load_history, clear_history
from app_helpers import (
    _estimate_cost, _show_cost_metrics, _extract_metrics,
    _parse_written_files, _show_files_report, _extract_planned_files,
    _git_diff, _git_commit, _check_railway,
    _generate_pdf_report, _estimate_cost_before_launch,
    _preprocess_instruction, PROJECT_ROOTS, RAILWAY_URL,
)


def render(tab):
    """Rendu de l'onglet Recherche Web."""
    with tab:
        st.subheader("Recherche avec triangulation des sources")
        st.caption("CONFIRMÉ (3+ sources) | PARTIEL (2 sources) | NON VÉRIFIÉ (1 source)")
        st.caption("🔍 Agent Chercheur Web dédié — accès Tavily uniquement, pas de filesystem")

        query = st.text_input(
            "Requête",
            placeholder="Ex: FastAPI JWT refresh token best practices 2025"
        )

        if st.button("🔍 Rechercher", type="primary", disabled=not query):
            (_, _, _, _, _, _, _, _, _, researcher) = make_agents("./")
            tasks = make_research_task(query, researcher)
            crew = Crew(agents=[researcher], tasks=tasks, process=Process.sequential, verbose=True, memory=False, respect_context_window=True)


            with st.spinner("Recherche en cours..."):
                result = crew.kickoff()

            st.success("✅ Terminé")
            tokens = _extract_metrics(crew)
            cost   = _estimate_cost(tokens)
            _show_cost_metrics(tokens, cost)

            st.markdown("### Synthèse")
            result_str = str(result)
            st.markdown(result_str)

            save_run(
                run_type="research",
                project="Web",
                instruction=query,
                result=result_str,
                prompt_tokens=tokens["prompt"],
                completion_tokens=tokens["completion"],
                total_tokens=tokens["total"],
            )


    # ── Tab 3 : Error Triage ─────────────────────────────────────────────────────
