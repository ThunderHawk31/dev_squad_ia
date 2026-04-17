"""
tabs/tab_error_triage.py — Onglet "Error Triage"
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
    """Rendu de l'onglet Error Triage."""
    with tab:
        st.subheader("🚨 Triage automatique d'erreur")
        st.caption("Error Triage analyse → Build Fixer corrige")

        project_err = st.selectbox("Projet", list(PROJECT_ROOTS.keys()), key="err_proj")
        project_root_err = PROJECT_ROOTS[project_err]

        error_desc = st.text_area(
            "Description de l'erreur",
            placeholder=(
                "Ex: 502 Bad Gateway sur /api/artisans après déploiement Railway.\n"
                "Logs : CORSMiddleware conflict on OPTIONS request."
            ),
            height=120,
        )

        if st.button("🔍 Analyser", type="primary", disabled=not error_desc):
            (manager, backend, frontend,
             tester, build_fixer,
             security, error_triage, cleaner,
             performance, researcher) = make_agents(project_root_err)

            tasks = make_error_triage_task(error_desc, error_triage, backend, build_fixer)

            crew = Crew(
                agents=[error_triage, build_fixer],
                tasks=tasks,
                process=Process.sequential,
                verbose=True,
                memory=False,
                respect_context_window=True,
            )

            with st.spinner("Analyse en cours..."):
                result = crew.kickoff()

            st.success("✅ Analyse terminée")
            tokens = _extract_metrics(crew)
            cost   = _estimate_cost(tokens)
            _show_cost_metrics(tokens, cost)

            result_str = str(result)
            st.markdown("### Rapport de triage")
            st.markdown(result_str)

            # Fichiers modifiés si le Build Fixer a écrit quelque chose
            files_data = _parse_written_files(result_str)
            if files_data:
                _show_files_report(files_data)

            save_run(
                run_type="triage",
                project=project_err,
                instruction=error_desc,
                result=result_str,
                prompt_tokens=tokens["prompt"],
                completion_tokens=tokens["completion"],
                total_tokens=tokens["total"],
            )


    # ── Tab 4 : Historique ────────────────────────────────────────────────────────
