"""
tabs/tab_claude_md.py — Onglet "CLAUDE.md"
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
    """Rendu de l'onglet CLAUDE.md."""
    with tab:
        st.subheader("📝 Éditeur CLAUDE.md")
        st.caption("Injectez le contexte projet pour éviter l'exploration aveugle des agents.")
        
        # ── Index des fonctions (aperçu live) ──
        from tasks import _build_function_index as _bfi
        _idx_proj = st.selectbox("Projet pour l'index", list(PROJECT_ROOTS.keys()), key="idx_proj")
        _idx_root = PROJECT_ROOTS[_idx_proj]
        if st.button("🔍 Générer l'index des fonctions", key="btn_gen_index",
                    help="Scanne les fichiers Python du projet et affiche l'index ligne par ligne"):
            _idx = _bfi(_idx_root)
            if _idx:
                st.code(_idx, language="text")
                st.caption(
                    "💡 Cet index est automatiquement injecté dans chaque run. "
                    "Le Manager l'utilise pour donner des numéros de lignes exacts au Back-end."
                )
            else:
                st.info("Aucun fichier Python trouvé dans ce projet.")

        claude_proj = st.selectbox(
            "Projet", list(PROJECT_ROOTS.keys()), key="claude_proj"
        )
        claude_root = PROJECT_ROOTS[claude_proj]
        claude_path = os.path.join(claude_root, "CLAUDE.md")

        # Charger le contenu actuel
        if "claude_content" not in st.session_state or st.session_state.get("claude_proj_loaded") != claude_proj:
            if os.path.exists(claude_path):
                with open(claude_path, encoding="utf-8", errors="ignore") as _cf:
                    st.session_state["claude_content"] = _cf.read()
            else:
                st.session_state["claude_content"] = (
                    "# Projet " + claude_proj + "\n\n"
                    "## Stack\n\n"
                    "## Architecture backend\n\n"
                    "## Architecture frontend\n\n"
                    "## Variables d'environnement\n\n"
                    "## Failles connues\n\n"
                    "## Conventions\n"
                )
            st.session_state["claude_proj_loaded"] = claude_proj

        content_edited = st.text_area(
            "Contenu du CLAUDE.md",
            value=st.session_state["claude_content"],
            height=500,
            key="claude_editor",
            label_visibility="collapsed",
        )

        # Compteur de lignes en temps réel
        line_count = content_edited.count("\n") + 1
        char_count = len(content_edited)
        if line_count <= 150:
            st.caption(f"✅ {line_count} lignes — {char_count} caractères — sous le seuil (≤150)")
        else:
            st.caption(
                f"⚠️ {line_count} lignes — {char_count} caractères — "
                f"**dépassement de {line_count - 150} lignes** : risque de tokens fantômes "
                f"(chaque agent reçoit le fichier entier)"
            )

        col_save, col_reload, col_path = st.columns([1, 1, 3])
        with col_save:
            if st.button("💾 Sauvegarder", type="primary", key="claude_save"):
                try:
                    os.makedirs(claude_root, exist_ok=True)
                    with open(claude_path, "w", encoding="utf-8") as _cf:
                        _cf.write(content_edited)
                    st.session_state["claude_content"] = content_edited
                    st.success(f"✅ Sauvegardé → `{claude_path}`")
                except Exception as e:
                    st.error(f"Erreur écriture : {e}")
        with col_reload:
            if st.button("🔄 Recharger", key="claude_reload"):
                if os.path.exists(claude_path):
                    with open(claude_path, encoding="utf-8", errors="ignore") as _cf:
                        st.session_state["claude_content"] = _cf.read()
                    st.session_state["claude_proj_loaded"] = None  # force reload
                    st.rerun()
                else:
                    st.warning("Aucun fichier à recharger.")
        with col_path:
            if os.path.exists(claude_path):
                st.info(f"📂 `{claude_path}`")
            else:
                st.warning(f"⚠️ Fichier inexistant — sera créé à la sauvegarde : `{claude_path}`")

        # ── Auto-génération par agent IA ──
        st.divider()
        st.markdown("### 🤖 Génération automatique par IA")
        st.caption(
            "Un agent analyse les fichiers clés du projet et génère le CLAUDE.md complet. "
            "Durée : ~1–2 minutes. Résultat écrit directement dans le projet."
        )

        if os.path.exists(claude_path):
            st.warning(
                f"⚠️ Un CLAUDE.md existe déjà (`{claude_path}`). "
                "La génération écrasera son contenu actuel."
            )

        if st.button("🤖 Générer CLAUDE.md automatiquement", type="primary", key="gen_claude_btn"):
            (_, backend_gen, _, _, _, _, _, _, _, _) = make_agents(claude_root)
            gen_task = make_claude_md_task(claude_root, backend_gen)
            gen_crew = Crew(
                agents=[backend_gen],
                tasks=[gen_task],
                process=Process.sequential,
                verbose=True,
                memory=False,
                respect_context_window=True,
            )
            gen_log = st.empty()
            gen_steps: list[str] = []

            def _on_gen_step(output):
                raw = getattr(output, "raw", str(output))[:200].replace("\n", " ")
                gen_steps.append(f"📝 {raw}...")
                gen_log.markdown("\n\n".join(f"- {l}" for l in gen_steps[-4:]))

            gen_crew.step_callback = _on_gen_step

            with st.spinner("🤖 L'agent analyse le projet et rédige le CLAUDE.md..."):
                gen_result = gen_crew.kickoff()

            # Recharger le contenu dans l'éditeur
            if os.path.exists(claude_path):
                with open(claude_path, encoding="utf-8", errors="ignore") as _gf:
                    st.session_state["claude_content"] = _gf.read()
                st.session_state["claude_proj_loaded"] = None
                tokens_gen = _extract_metrics(gen_crew)
                cost_gen   = _estimate_cost(tokens_gen)
                st.success(f"✅ CLAUDE.md généré et sauvegardé ! Coût : ~${cost_gen:.4f}")
                st.rerun()
            else:
                st.error("❌ Le fichier n'a pas été créé. Vérifiez que le chemin du projet est correct.")
                st.markdown(str(gen_result))


    # ── Tab 6 : Agent Direct ─────────────────────────────────────────────────────
