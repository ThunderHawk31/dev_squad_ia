"""
tabs/tab_deployer.py — Onglet "Déployer"
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
    _git_diff, _git_commit, _git_push, _git_status, _git_current_branch,
    _check_railway,
    _generate_pdf_report, _estimate_cost_before_launch,
    _preprocess_instruction, PROJECT_ROOTS, RAILWAY_URL,
)


def render(tab):
    """Rendu de l'onglet Déployer."""
    with tab:
        st.subheader("🚀 Déployer")
        st.caption("Git + Railway — subprocess direct, sans agent CrewAI")

        deploy_proj = st.selectbox("Projet", list(PROJECT_ROOTS.keys()), key="deploy_proj")
        deploy_root = PROJECT_ROOTS[deploy_proj]
        branch = _git_current_branch(deploy_root)

        st.info(f"🌿 Projet : **{deploy_proj}** — branche : `{branch}` — `{deploy_root}`")

        # ── Section Git ───────────────────────────────────────────────────────────
        st.markdown("### 📂 État Git")
        gcol1, gcol2 = st.columns(2)
        with gcol1:
            if st.button("🔍 Voir git status", key="deploy_status"):
                out = _git_status(deploy_root)
                st.code(out, language="bash")
        with gcol2:
            if st.button("📊 Voir git diff", key="deploy_diff"):
                out = _git_diff(deploy_root)
                st.code(out, language="diff")

        st.divider()

        # Message de commit enrichi avec les fichiers des derniers runs
        last_code_runs = [r for r in load_history() if r.get("type") == "code"][-3:]
        files_hint = ""
        if last_code_runs:
            all_files = []
            for r in last_code_runs:
                all_files.extend(r.get("files_modified", []))
            if all_files:
                basenames = list(dict.fromkeys(os.path.basename(f) for f in all_files))[:3]
                files_hint = f" ({', '.join(basenames)})"

        commit_msg_deploy = st.text_input(
            "Message de commit",
            value=f"feat: squad-ia auto-deploy{files_hint}",
            key="deploy_commit_msg",
            help="Préfixes conseillés : feat / fix / chore / refactor / test. Ex: fix: correction CORS endpoint artisans"
        )

        if st.button("📦 Commit (git add -A + commit)", type="primary", key="deploy_commit_btn"):
            out = _git_commit(deploy_root, commit_msg_deploy)
            if "nothing to commit" in out.lower():
                st.info(f"ℹ️ {out}")
            elif "error" in out.lower() or "erreur" in out.lower():
                st.error(f"❌ {out}")
            else:
                st.success(f"✅ Commit OK\n```\n{out}\n```")

        # ── Section Déploiement ───────────────────────────────────────────────────
        st.markdown("### 🌍 Déploiement Railway")

        st.warning(
            f"⚠️ **Cette action push vers `origin/{branch}`.** "
            "Assurez-vous que le code est testé et le commit est fait."
        )
        push_confirmed = st.checkbox(
            f"✅ Je confirme le push vers `{branch}`", key="push_confirm"
        )

        push_col, health_col = st.columns(2)
        with push_col:
            if st.button(
                "🚀 Push vers main", type="primary",
                disabled=not push_confirmed, key="deploy_push_btn"
            ):
                with st.spinner(f"Push origin/{branch}..."):
                    push_out = _git_push(deploy_root, branch)
                if "error" in push_out.lower() or "erreur" in push_out.lower():
                    st.error(f"❌ Push échoué\n```\n{push_out}\n```")
                else:
                    st.success(f"✅ Push OK\n```\n{push_out}\n```")
                    st.session_state["just_pushed"] = True
                    st.rerun()

        with health_col:
            if st.button("🏥 Health check Railway", key="deploy_health_btn"):
                health = _check_railway(RAILWAY_URL)
                if health["ok"]:
                    st.success(f"✅ Railway OK — HTTP {health['status']}")
                else:
                    st.error(f"❌ Railway KO — HTTP {health.get('status', 0)}  {health.get('error', '')}")

        # Health check automatique (3 tentatives) après push
        if st.session_state.pop("just_pushed", False):
            import time
            st.info("🔄 Push détecté — vérification automatique Railway (3 tentatives × 10s)...")
            for attempt in range(1, 4):
                with st.spinner(f"Attente déploiement Railway... ({attempt}/3)"):
                    time.sleep(10)
                health = _check_railway(RAILWAY_URL)
                if health["ok"]:
                    st.success(f"✅ Railway UP après push — HTTP {health['status']} (tentative {attempt}/3)")
                    break
                else:
                    if attempt < 3:
                        st.warning(f"⏳ {attempt}/3 — Railway pas encore prêt — HTTP {health.get('status', 0)}")
                    else:
                        st.error(
                            f"❌ Railway toujours KO après 3 tentatives — HTTP {health.get('status', 0)}\n"
                            f"{health.get('error', '')}"
                        )

        # ── Historique des 5 derniers runs code ───────────────────────────────────
        st.divider()
        st.markdown("### 📜 Derniers runs de code (mémoire des changements)")
        st.caption("Fichiers modifiés par les 5 derniers pipelines Code")

        code_history = [r for r in load_history() if r.get("type") == "code"]
        if not code_history:
            st.info("Aucun run de code dans l'historique.")
        else:
            for run in reversed(code_history[-5:]):
                ts = run.get("timestamp", "")[:16].replace("T", " ")
                instr = run.get("instruction", "")[:70]
                files = run.get("files_modified", [])
                cost = run.get("cost_usd", 0)
                with st.expander(f"💻 `{ts}` — {instr}…  |  ~${cost:.4f}", expanded=False):
                    if files:
                        st.markdown("**Fichiers modifiés :**")
                        for fp in files:
                            ext = fp.rsplit(".", 1)[-1] if "." in fp else ""
                            icon_f = {
                                "py": "🐍", "js": "🟨", "jsx": "⚛️",
                                "ts": "🔷", "tsx": "⚛️", "json": "📋", "md": "📝"
                            }.get(ext, "📄")
                            if os.path.exists(fp):
                                st.markdown(f"  {icon_f} `{os.path.basename(fp)}` — `{fp}`")
                            else:
                                st.write(f"  {icon_f} `{fp}` *(introuvable localement)*")
                    else:
                        st.write("Aucun fichier loggé pour ce run.")


    # ── Tab 8 : AutoAgent ─────────────────────────────────────────────────────────
