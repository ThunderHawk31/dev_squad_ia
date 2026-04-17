"""
tabs/tab_autoagent.py — Onglet "AutoAgent"
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
    """Rendu de l'onglet AutoAgent."""
    with tab:
        st.subheader("🧠 AutoAgent — Optimisation automatique des prompts")
        st.caption(
            "Analyse les runs passés et propose des améliorations sur les instructions "
            "et backstories des agents. Coût estimé : ~$0.05–0.10 par analyse."
        )

        # ── Chargement historique ──
        _aa_history = load_history()
        _aa_code_runs = [r for r in _aa_history if r.get("type") == "code"]

        if len(_aa_code_runs) < 3:
            st.info(
                f"ℹ️ {len(_aa_code_runs)} run(s) de code dans l'historique. "
                "L'AutoAgent a besoin d'au moins 3 runs pour analyser des patterns."
            )
        else:
            # ── Métriques globales ──
            _aa_total   = len(_aa_code_runs)
            _aa_cost    = sum(r.get("cost_usd", 0) for r in _aa_code_runs)
            _aa_avg     = _aa_cost / _aa_total if _aa_total else 0
            _aa_tokens  = sum(r.get("tokens", {}).get("total", 0) for r in _aa_code_runs)

            # Détecter les runs problématiques
            _aa_expensive = [r for r in _aa_code_runs if r.get("cost_usd", 0) > _aa_avg * 2]
            _aa_errors    = [
                r for r in _aa_code_runs
                if any(kw in r.get("result_preview", "").lower()
                       for kw in ["maximum iterations", "invalid response", "none or empty",
                                   "error", "erreur", "failed", "échec"])
            ]

            col_aa1, col_aa2, col_aa3, col_aa4 = st.columns(4)
            col_aa1.metric("Runs analysés", _aa_total)
            col_aa2.metric("Coût moyen", f"~${_aa_avg:.3f}")
            col_aa3.metric("Runs coûteux (>2×moy)", len(_aa_expensive))
            col_aa4.metric("Runs avec erreurs", len(_aa_errors))

            st.divider()

            # ── Options d'analyse ──
            _aa_n = st.slider(
                "Nombre de runs à analyser",
                min_value=3, max_value=min(20, _aa_total),
                value=min(10, _aa_total), step=1,
                help="Plus de runs = meilleure analyse, mais plus de tokens"
            )

            _aa_focus = st.multiselect(
                "Focus de l'optimisation",
                ["Instructions de tâches", "Backstories agents", "Patterns d'erreurs", "Coût excessif"],
                default=["Instructions de tâches", "Patterns d'erreurs"],
                help="Choisir ce que l'AutoAgent doit analyser en priorité"
            )

            st.divider()

            # ── Lancement ──
            if st.button("🧠 Lancer l'analyse AutoAgent", type="primary",
                         disabled=not _aa_focus, key="btn_autoagent"):

                _runs_sample = _aa_code_runs[-_aa_n:]

                # Préparer le résumé des runs pour le prompt
                _runs_summary = []
                for r in _runs_sample:
                    _runs_summary.append(
                        f"Run #{r.get('id','?')} | {r.get('timestamp','')[:10]} | "
                        f"${r.get('cost_usd',0):.4f} | "
                        f"Instruction: {r.get('instruction','')[:80]} | "
                        f"Aperçu: {r.get('result_preview','')[:150]}"
                    )

                # Lire les prompts actuels des agents et tâches
                try:
                    _agents_src  = open(os.path.join(os.path.dirname(__file__), "agents.py"),
                                        encoding="utf-8").read()[:3000]
                    _tasks_src   = open(os.path.join(os.path.dirname(__file__), "tasks.py"),
                                        encoding="utf-8").read()[:3000]
                except Exception:
                    _agents_src  = "Non disponible"
                    _tasks_src   = "Non disponible"

                _focus_str = ", ".join(_aa_focus)

                _system_prompt = (
                    "Tu es un méta-agent expert en optimisation de systèmes multi-agents. "
                    "Tu analyses les runs passés d'un Squad IA (CrewAI + Claude) et tu proposes "
                    "des améliorations concrètes et actionnables sur les prompts et instructions. "
                    "Tu ne modifies PAS le routing Sonnet/Haiku — seulement les textes."
                )

                _user_prompt = (
                    f"Analyse ces {len(_runs_sample)} runs d'un Squad IA de développement :\n\n"
                    f"{''.join(chr(10).join(_runs_summary))}\n\n"
                    f"Statistiques globales :\n"
                    f"- Coût moyen : ${_aa_avg:.4f}/run\n"
                    f"- Runs coûteux (>2×moy) : {len(_aa_expensive)}\n"
                    f"- Runs avec erreurs : {len(_aa_errors)}\n\n"
                    f"Focus demandé : {_focus_str}\n\n"
                    f"Extraits du code actuel :\n"
                    f"=== agents.py (extrait) ===\n{_agents_src[:1500]}\n\n"
                    f"=== tasks.py (extrait) ===\n{_tasks_src[:1500]}\n\n"
                    f"Produis une analyse structurée :\n"
                    f"## Score de performance actuel\n"
                    f"  - Taux de succès estimé (runs sans erreurs / total)\n"
                    f"  - Coût moyen vs objectif ($0.10-0.20)\n"
                    f"  - Ratio qualité/coût\n\n"
                    f"## Patterns problématiques identifiés\n"
                    f"  (Cite les runs spécifiques avec leur #ID)\n\n"
                    f"## Améliorations proposées\n"
                    f"  Pour chaque amélioration :\n"
                    f"  - AVANT : [texte actuel]\n"
                    f"  - APRÈS : [texte proposé]\n"
                    f"  - IMPACT ATTENDU : [réduction erreurs / coût / tokens]\n"
                    f"  - FICHIER : agents.py ou tasks.py, ligne approximative\n\n"
                    f"## Alertes\n"
                    f"  (Patterns qui risquent de s'aggraver si non traités)\n\n"
                    f"## Score prévu après optimisations\n"
                    f"  Estimation du nouveau ratio qualité/coût"
                )

                with st.spinner("🧠 AutoAgent analyse les runs... (~$0.05–0.10)"):
                    try:
                        import anthropic as _ant
                        _aa_client = _ant.Anthropic(
                            api_key=os.environ.get("ANTHROPIC_API_KEY", "")
                        )
                        _aa_resp = _aa_client.messages.create(
                            model="claude-sonnet-4-20250514",
                            max_tokens=2000,
                            system=_system_prompt,
                            messages=[{"role": "user", "content": _user_prompt}],
                        )
                        _aa_result = _aa_resp.content[0].text
                        _aa_tokens_used = (
                            _aa_resp.usage.input_tokens + _aa_resp.usage.output_tokens
                        )
                        _aa_cost_used = (
                            _aa_resp.usage.input_tokens  / 1_000_000 * 3.0 +
                            _aa_resp.usage.output_tokens / 1_000_000 * 15.0
                        )

                        st.success(
                            f"✅ Analyse terminée — "
                            f"{_aa_tokens_used:,} tokens | ~${_aa_cost_used:.4f}"
                        )

                        # Afficher le rapport
                        st.markdown("---")
                        st.markdown(_aa_result)

                        # Sauvegarder dans optimizations.log
                        _log_path = os.path.join(
                            os.path.dirname(os.path.abspath(__file__)), "optimizations.log"
                        )
                        with open(_log_path, "a", encoding="utf-8") as _lf:
                            from datetime import datetime as _dt2
                            _lf.write(
                                f"\n{'='*60}\n"
                                f"AutoAgent run — {_dt2.now().strftime('%Y-%m-%d %H:%M')}\n"
                                f"Runs analysés : {len(_runs_sample)} | "
                                f"Focus : {_focus_str}\n"
                                f"Coût : ~${_aa_cost_used:.4f}\n"
                                f"{'='*60}\n"
                                f"{_aa_result}\n"
                            )

                        st.divider()

                        # Bouton export PDF du rapport d'optimisation
                        _opt_pdf = _generate_pdf_report(
                            instruction=f"AutoAgent — {_focus_str}",
                            project="Squad IA",
                            result_str=_aa_result,
                            files_written=[],
                            tokens={"total": _aa_tokens_used, "prompt": _aa_resp.usage.input_tokens,
                                    "completion": _aa_resp.usage.output_tokens},
                            cost=_aa_cost_used,
                        )
                        _opt_ext = "pdf" if _opt_pdf[:4] == b"%PDF" else "txt"
                        st.download_button(
                            "📥 Exporter le rapport d'optimisation",
                            data=_opt_pdf,
                            file_name=f"autoagent_rapport_{_dt2.now().strftime('%Y%m%d')}.{_opt_ext}",
                            mime="application/pdf" if _opt_ext == "pdf" else "text/plain",
                            key="dl_autoagent_pdf",
                        )

                    except Exception as e:
                        st.error(f"❌ Erreur AutoAgent : {e}")

            # ── Journal des optimisations passées ──
            _log_path2 = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "optimizations.log"
            )
            if os.path.exists(_log_path2):
                with st.expander("📋 Journal des optimisations passées", expanded=False):
                    with open(_log_path2, encoding="utf-8") as _lf2:
                        _log_content = _lf2.read()
                    st.text(_log_content[-3000:] if len(_log_content) > 3000 else _log_content)
                    if st.button("🗑️ Vider le journal", key="btn_clear_opt_log"):
                        os.remove(_log_path2)
                        st.rerun()

