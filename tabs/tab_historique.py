"""
tabs/tab_historique.py — Onglet "Historique"
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
    """Rendu de l'onglet Historique."""
    with tab:
        st.subheader("📜 Historique des runs")

        # Recharger depuis le fichier à chaque visite de l'onglet
        history = load_history()

        if not history:
            st.info("Aucun run sauvegardé. Lance ton premier pipeline dans l'onglet Code !")
            st.caption(f"Fichier historique : `{os.path.join(os.path.dirname(os.path.abspath(__file__)), 'runs_history.json')}`")
        else:
            # ── Métriques globales ──
            total_cost       = sum(r.get("cost_usd", 0) for r in history)
            total_runs       = len(history)
            total_tokens_all = sum(r.get("tokens", {}).get("total", 0) for r in history)
            avg_cost         = total_cost / total_runs if total_runs else 0

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Runs total", total_runs)
            m2.metric("Tokens total", f"{total_tokens_all:,}")
            m3.metric("Coût total", f"~${total_cost:.3f}")
            m4.metric("Coût moyen/run", f"~${avg_cost:.3f}")

            st.divider()

            # ── Graphe coût par run (30 derniers) ──
            recent = history[-30:]
            if len(recent) >= 2:
                import json as _json

                # Préparer les données pour le graphe
                chart_data = {
                    "Run": list(range(1, len(recent) + 1)),
                    "Coût ($)": [r.get("cost_usd", 0) for r in recent],
                    "Coût cumulé ($)": [],
                }
                cumul = 0
                for r in recent:
                    cumul += r.get("cost_usd", 0)
                    chart_data["Coût cumulé ($)"].append(round(cumul, 4))

                # Labels lisibles pour l'axe X
                labels = [
                    f"{r.get('timestamp', '')[:10]} — {r.get('instruction', '')[:20]}…"
                    for r in recent
                ]

                import pandas as _pd
                _df = _pd.DataFrame({
                    "Coût ($)": chart_data["Coût ($)"],
                    "Cumulé ($)": chart_data["Coût cumulé ($)"],
                }, index=labels)

                tab_bar, tab_line = st.tabs(["📊 Coût par run", "📈 Coût cumulé"])
                with tab_bar:
                    st.bar_chart(_df[["Coût ($)"]], use_container_width=True, height=200)
                    # Annoter le run le plus cher
                    max_idx = chart_data["Coût ($)"].index(max(chart_data["Coût ($)"]))
                    max_run = recent[max_idx]
                    st.caption(
                        f"💸 Run le plus cher : `{max_run.get('instruction','')[:50]}` "
                        f"— ~${max_run.get('cost_usd',0):.4f}"
                    )
                with tab_line:
                    st.line_chart(_df[["Cumulé ($)"]], use_container_width=True, height=200)
                    st.caption(f"💰 Total cumulé sur {len(recent)} runs : ~${cumul:.3f}")

            st.divider()

            # ── Liste des runs ──
            type_colors = {"code": "💻", "research": "🔍", "triage": "🚨", "direct": "💬"}
            for run in reversed(history):
                run_type     = run.get("type", "?")
                icon         = type_colors.get(run_type, "🤖")
                ts           = run.get("timestamp", "")[:16].replace("T", " ")
                cost         = run.get("cost_usd", 0)
                project_name = run.get("project", "?")
                tokens_total = run.get("tokens", {}).get("total", 0)
                files        = run.get("files_modified", [])
                files_str    = f" | 📁 {len(files)} fichier{'s' if len(files)>1 else ''}" if files else ""

                label = (
                    f"{icon} `{ts}` — **{project_name}** — "
                    f"*{run.get('instruction', '')[:50]}…*  "
                    f"| {tokens_total:,} tok | ~${cost:.4f}{files_str}"
                )
                with st.expander(label, expanded=False):
                    col_info, col_action = st.columns([3, 1])
                    with col_info:
                        st.write(f"**Type :** {run_type} | **Projet :** {project_name}")
                        st.write(f"**Instruction :** {run.get('instruction', '')}")
                    with col_action:
                        # Bouton replay
                        if st.button("↩️ Rejouer", key=f"replay_{run.get('id',0)}",
                                    help="Pré-remplit l'instruction dans l'onglet Code"):
                            st.session_state["instruction_prefill"] = run.get("instruction", "")
                            st.info("Instruction copiée — retournez dans l'onglet Tâche Code")

                    if files:
                        st.markdown("**📁 Fichiers modifiés :**")
                        for fp in files:
                            ext    = fp.rsplit(".", 1)[-1] if "." in fp else ""
                            icon_f = {"py": "🐍", "js": "🟨", "jsx": "⚛️", "ts": "🔷",
                                      "tsx": "⚛️", "json": "📋", "md": "📝"}.get(ext, "📄")
                            exists = os.path.exists(fp)
                            badge  = "" if exists else " ⚠️ introuvable"
                            st.write(f"  {icon_f} `{fp}`{badge}")

                    with st.expander("📊 Aperçu résultat", expanded=False):
                        st.markdown(run.get("result_preview", "*(vide)*"))

            st.divider()
            col_clear, col_export = st.columns(2)
            with col_clear:
                if st.button("🗑️ Vider l'historique", type="secondary"):
                    clear_history()
                    st.rerun()
            with col_export:
                # Export CSV simple
                if history:
                    import csv as _csv, io as _io
                    buf = _io.StringIO()
                    writer = _csv.DictWriter(buf, fieldnames=["id","timestamp","type","project","instruction","cost_usd","tokens_total"])
                    writer.writeheader()
                    for r in history:
                        writer.writerow({
                            "id": r.get("id",""),
                            "timestamp": r.get("timestamp",""),
                            "type": r.get("type",""),
                            "project": r.get("project",""),
                            "instruction": r.get("instruction","")[:100],
                            "cost_usd": r.get("cost_usd",0),
                            "tokens_total": r.get("tokens",{}).get("total",0),
                        })
                    st.download_button(
                        "📥 Exporter CSV",
                        data=buf.getvalue(),
                        file_name="squad_ia_history.csv",
                        mime="text/csv",
                    )


    # ── Tab 5 : CLAUDE.md Editor ────────────────────────────────────────────────
