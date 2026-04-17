"""
tabs/tab_agent_direct.py — Onglet "Agent Direct"
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
    """Rendu de l'onglet Agent Direct."""
    with tab:

        st.subheader("💬 Parler directement à un agent")
        st.caption("Sans pipeline complet — une tâche, un agent, une réponse directe")

        col_a, col_b = st.columns(2)
        with col_a:
            agent_choice = st.selectbox("Agent", [
                "Back-end", "Front-end", "Sécurité",
                "Testeur", "Build Fixer", "Error Triage", "Performance", "Chercheur Web"
            ])
        with col_b:
            project_direct = st.selectbox(
                "Projet cible", list(PROJECT_ROOTS.keys()), key="direct_proj"
            )

        direct_msg = st.text_area(
            "Message",
            height=120,
            placeholder=(
                "Ex: Explique-moi la fonction get_artisan dans server.py\n"
                "Ex: Refactore cette fonction pour éviter les requêtes N+1\n"
                "Ex: Quelles sont les failles potentielles sur l'endpoint /api/chat/send ?"
            ),
        )

        if st.button("💬 Envoyer", type="primary", disabled=not direct_msg):
            project_root_direct = PROJECT_ROOTS[project_direct]
            (manager, backend, frontend,
             tester, build_fixer,
             security, error_triage, cleaner,
             performance, researcher) = make_agents(project_root_direct)

            agent_map = {
                "Back-end":      backend,
                "Front-end":     frontend,
                "Sécurité":      security,
                "Testeur":       tester,
                "Build Fixer":   build_fixer,
                "Error Triage":  error_triage,
                "Performance":   performance,
                "Chercheur Web": researcher,
            }
            selected_agent = agent_map[agent_choice]

            direct_task = Task(
                description=direct_msg,
                expected_output="Réponse directe, concise et actionnable.",
                agent=selected_agent,
            )

            direct_crew = Crew(
                agents=[selected_agent],
                tasks=[direct_task],
                process=Process.sequential,
                verbose=True,
                memory=False,
                respect_context_window=True,
            )

            with st.spinner(f"{agent_choice} réfléchit..."):
                result = direct_crew.kickoff()

            st.success("✅ Réponse reçue")
            tokens = _extract_metrics(direct_crew)
            cost   = _estimate_cost(tokens)
            _show_cost_metrics(tokens, cost)

            result_str = str(result)
            st.markdown("### Réponse")
            st.markdown(result_str)

            save_run(
                run_type="direct",
                project=project_direct,
                instruction=f"[{agent_choice}] {direct_msg}",
                result=result_str,
                prompt_tokens=tokens["prompt"],
                completion_tokens=tokens["completion"],
                total_tokens=tokens["total"],
            )


    # ── Tab 7 : Déployer ─────────────────────────────────────────────────────────
