"""
tabs/tab_code.py — Onglet "Tâche Code"
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
    """Rendu de l'onglet Tâche Code."""
    with tab:
        st.subheader("Pipeline : Plan → Code → Tests → Sécurité → ✅ Validation → Écriture")
        st.caption("Les fichiers ne sont écrits qu'après votre validation du rapport de sécurité.")

        project = st.selectbox("Projet cible", list(PROJECT_ROOTS.keys()))
        project_root = PROJECT_ROOTS[project]

        has_claude_md = os.path.exists(os.path.join(project_root, "CLAUDE.md"))
        if has_claude_md:
            st.success("📋 CLAUDE.md détecté — injection contextuelle sélective activée")
        else:
            st.warning("⚠️ Pas de CLAUDE.md — agents en mode exploration (coûteux)")

        # ── Templates rapides ──
        st.markdown("**⚡ Templates rapides**")
        templates = [
            "Corrige la faille Antigravity n°",
            "Ajoute pagination sur /api/",
            "Crée endpoint CRUD pour ",
            "Ajoute tests pytest pour ",
            "Refactorise  pour éviter les requêtes N+1",
        ]
        tpl_cols = st.columns(len(templates))
        for i, (col, tpl) in enumerate(zip(tpl_cols, templates)):
            with col:
                if st.button(tpl[:28] + "…", key=f"tpl_{i}", use_container_width=True):
                    st.session_state["instruction_prefill"] = tpl

        # ── Bannière de validation en haut (visible sans scroller) ──
        if st.session_state.get("phase1_done") and not st.session_state.get("write_approved"):
            st.error(
                "🔴 **Phase 1 terminée — Rapport prêt, en attente de votre validation !**  \n"
                "👇 Faites défiler vers le bas pour lire le rapport et cliquer sur **✅ Valider — Écrire les fichiers**.",
            )

        instruction = st.text_area(
            "Instruction",
            value=st.session_state.pop("instruction_prefill", ""),
            placeholder="Ex: Ajoute un endpoint /api/artisans/{id}/reviews avec pagination et auth JWT",
            height=100,
            key="instruction_input",
        )


        col1, col2, col3 = st.columns(3)
        with col1:
            with_tests = st.checkbox("Inclure Testeur + Build Fixer", value=True)
        with col2:
            with_frontend = st.checkbox("Inclure Agent Frontend", value=False,
                help="Décocher si la tâche est purement back-end (économise ~30% des tokens)")
        with col3:
            with_perf = st.checkbox("Inclure Agent Performance", value=False)

        # Mode patch dans options avancées — sans sécurité, pour les petits fixes
        n_tasks = (3 if not with_frontend else 4) + (2 if with_tests else 0) + (1 if with_perf else 0)

        # ── Options avancées ──
        with st.expander("⚙️ Options avancées", expanded=False):
            patch_mode = st.checkbox(
                "⚡ Mode patch (sans audit sécurité)",
                value=False,
                key="patch_mode",
                help="Skip l'agent Sécurité — pour les petits fixes évidents (B2, H2...). Économise ~40% du coût total."
            )
            dry_run_mode = st.checkbox(
                "🔍 Mode simulation (dry run)",
                value=False,
                key="dry_run_mode",
                help="L'agent analyse et propose le code SANS écrire aucun fichier. "
                     "Utile pour voir le plan et estimer le risque avant de s'engager."
            )
            use_memory = st.checkbox(
                "🧠 Mémoire inter-runs (CrewAI Memory)",
                value=False,
                key="use_memory",
                help="Les agents se souviennent des runs précédents (stockage local ChromaDB). Nécessite : pip install chromadb"
            )
            budget_limit = st.number_input(
                "💰 Budget max ($)", min_value=0.01, max_value=5.0,
                value=0.50, step=0.05, format="%.2f",
                key="budget_limit",
                help="Avertissement si le coût estimé dépasse ce seuil"
            )

        # ── Estimation améliorée du coût avant lancement ──
        past_runs = [r for r in load_history() if r.get("type") == "code"]
        if instruction:
            _est = _estimate_cost_before_launch(
                instruction=instruction,
                project_root=project_root,
                n_tasks=n_tasks,
                with_tests=with_tests,
                patch_mode=patch_mode,
                past_runs=past_runs,
            )
            _label = f"~${_est['mid']:.3f} (fourchette ${_est['low']:.3f}–${_est['high']:.3f})"
            _method = _est["method"]

            if _est["mid"] > budget_limit:
                st.warning(
                    f"⚠️ **Coût estimé {_label}** dépasse votre budget de ${budget_limit:.2f}.  \n"
                    f"Méthode : {_method}. Vous pouvez quand même lancer."
                )
            else:
                col_cost1, col_cost2 = st.columns([2, 1])
                with col_cost1:
                    st.caption(f"💰 Coût estimé : **{_label}** — méthode : {_method}")
                with col_cost2:
                    # Barre de progression visuelle budget
                    _pct = min(_est["mid"] / budget_limit, 1.0)
                    _color = "🟢" if _pct < 0.5 else "🟡" if _pct < 0.8 else "🔴"
                    st.caption(f"{_color} {int(_pct*100)}% du budget (${budget_limit:.2f})")
        else:
            st.caption(f"💰 Entrez une instruction pour voir l'estimation de coût")

        # ── Alerte fichier volumineux ──
        if instruction and project_root:
            # Détecter si des fichiers volumineux vont être touchés
            _big_files = []
            for _fname in ["server.py", "main.py", "app.py"]:
                _fpath = os.path.join(project_root, "backend", _fname)
                if os.path.exists(_fpath):
                    _line_count = sum(1 for _ in open(_fpath, errors="ignore"))
                    if _line_count > 300:
                        _big_files.append(f"`{_fname}` ({_line_count} lignes)")
            
            _mentions_file = any(f in instruction for f in ["server.py", "main.py", ".py", "backend"])
            if _big_files and _mentions_file and not patch_mode:
                st.warning(
                    f"⚠️ **Fichier volumineux détecté** : {', '.join(_big_files)}  \n"
                    "L'agent risque de lire le fichier entier → coût élevé et risque de réécriture.  \n"
                    "💡 **Recommandation** : Préciser les numéros de lignes dans l'instruction, "
                    "ou activer le **Mode patch** dans Options avancées."
                )
            
            # ── Bouton reformatage d'instruction ──
            if len(instruction) > 80 and "\n" in instruction:
                if st.button("🔧 Reformater l'instruction", key="btn_reformat",
                            help="Haiku reformate votre instruction en bloc en instruction structurée (~$0.005)"):
                    claude_md_path = os.path.join(project_root, "CLAUDE.md")
                    with st.spinner("Reformatage en cours..."):
                        reformatted = _preprocess_instruction(instruction, project, claude_md_path)
                    st.session_state["instruction_prefill"] = reformatted
                    st.rerun()

        # ── Phase 1 : Analyse ──
        if st.button("🚀 Lancer l'analyse", type="primary", disabled=not instruction, key="btn_analyse"):
            (manager, backend, frontend,
             tester, build_fixer,
             security, error_triage, cleaner,
             performance, researcher) = make_agents(project_root)

            tasks, security_task, security_context, backend_agent = make_code_task_analysis(
                instruction, manager, backend, frontend,
                security, error_triage, tester, build_fixer,
                project_root,
                performance_agent=performance if with_perf else None,
                include_tests=with_tests,
                include_performance=with_perf,
                include_frontend=with_frontend,
                include_security=not patch_mode,
            )

            # Construire la liste des agents actifs selon les options
            active_agents = [manager, backend]
            if with_frontend:
                active_agents.append(frontend)
            if with_tests:
                active_agents += [tester, build_fixer]
            if not patch_mode:
                active_agents.append(security)
            if with_perf:
                active_agents.append(performance)

            # ── Timeline live des agents ──────────────────────────────────────
            st.markdown("#### 🗂️ Timeline d'exécution")

            # Agents attendus selon les options
            _expected_agents = ["Chef d\'Orchestre", "Développeur Back-end"]
            if with_frontend:     _expected_agents.append("Développeur Front-end")
            if with_tests:        _expected_agents += ["Testeur", "Build Fixer"]
            if with_perf:         _expected_agents.append("Analyste Performance")
            if not patch_mode:    _expected_agents.append("Auditeur Sécurité")

            # Containers pour la timeline et les logs
            timeline_box = st.empty()
            log_box      = st.empty()

            # État de la timeline
            _timeline_state: dict[str, str] = {a: "pending" for a in _expected_agents}
            _current_agent: list[str]       = [""]
            step_logs: list[str]            = []

            _STATUS_ICONS = {
                "pending": "⏳",
                "running": "🔄",
                "done":    "✅",
                "failed":  "❌",
            }

            def _render_timeline():
                """Redessine la timeline dans timeline_box."""
                rows = []
                for ag, status in _timeline_state.items():
                    icon = _STATUS_ICONS.get(status, "⏳")
                    style = "**" if status == "running" else ""
                    rows.append(f"{icon} {style}{ag}{style}")
                timeline_box.markdown("  →  ".join(rows))

            def _on_step(output):
                """Callback CrewAI — met à jour timeline + logs."""
                agent_name = getattr(output, "agent", "Agent") or "Agent"

                # Marquer l'agent précédent comme done
                if _current_agent[0] and _current_agent[0] in _timeline_state:
                    _timeline_state[_current_agent[0]] = "done"

                # Marquer l'agent courant comme running
                _matched = next(
                    (a for a in _timeline_state if a.lower() in agent_name.lower()
                     or agent_name.lower() in a.lower()),
                    None
                )
                if _matched:
                    _timeline_state[_matched] = "running"
                    _current_agent[0] = _matched
                _render_timeline()

                # Log compact
                raw = getattr(output, "raw", None) or getattr(output, "output", None) or str(output)
                clean = str(raw).replace("\\n", " ").replace("\\t", " ")
                first_line = next(
                    (l.strip() for l in clean.split("\n") if l.strip()),
                    clean[:180]
                )
                step_logs.append(f"🤖 **{agent_name}** → {first_line[:180]}")
                with log_box.expander(f"📋 Logs ({len(step_logs)} étapes)", expanded=False):
                    for lg in step_logs[-8:]:
                        st.markdown(f"- {lg}")

            _render_timeline()  # afficher la timeline vide avant le kickoff

            crew = Crew(
                agents=active_agents,
                tasks=tasks,
                process=Process.sequential,
                verbose=True,
                step_callback=_on_step,
                memory=use_memory,  # False par défaut, True si activé dans options avancées
                respect_context_window=True,
            )

            with st.spinner(f"Phase 1 : {n_tasks} tâches en cours..."):
                result = crew.kickoff()

            # Sauvegarder en session pour la Phase 2
            st.session_state["analysis_result"]      = str(result)
            st.session_state["analysis_tokens"]      = _extract_metrics(crew)
            st.session_state["security_task"]        = security_task
            st.session_state["security_context"]     = security_context
            st.session_state["backend_agent"]        = backend_agent
            st.session_state["analysis_project"]     = project
            st.session_state["analysis_root"]        = project_root
            st.session_state["analysis_instruction"] = instruction
            st.session_state["analysis_dry_run"]     = dry_run_mode
            st.session_state["phase1_done"]          = True
            # Pas de st.rerun() : le bloc de validation ci-dessous
            # s'affiche immédiatement dans le même rendu

        # ── Affichage Phase 1 + Validation ──
        if st.session_state.get("phase1_done"):
            tokens1 = st.session_state.get("analysis_tokens", {})
            cost1   = _estimate_cost(tokens1)

            st.success("✅ Phase 1 terminée — Rapport d'analyse prêt")
            _show_cost_metrics(tokens1, cost1)

            result_str = st.session_state.get("analysis_result", "")
            col_rapport, col_pdf = st.columns([4, 1])
            with col_rapport:
                st.markdown("**📊 Rapport complet (Plan + Code + Tests + Sécurité)**")
            with col_pdf:
                # Bouton PDF Phase 1
                _pdf1_bytes = _generate_pdf_report(
                    instruction=st.session_state.get("analysis_instruction", ""),
                    project=st.session_state.get("analysis_project", ""),
                    result_str=result_str,
                    files_written=[],
                    tokens=tokens1,
                    cost=cost1,
                )
                _ext1 = "pdf" if _pdf1_bytes[:4] == b"%PDF" else "txt"
                st.download_button(
                    "📥 PDF",
                    data=_pdf1_bytes,
                    file_name=f"squad_rapport_{st.session_state.get('analysis_project','')}.{_ext1}",
                    mime="application/pdf" if _ext1 == "pdf" else "text/plain",
                    key="dl_pdf_phase1",
                )
            with st.expander("Voir le rapport", expanded=True):
                st.markdown(result_str)

            st.divider()
            st.markdown("### 🔒 Validation avant écriture des fichiers")

            # ── Fichiers prévus (extraits du rapport Phase 1) ──
            planned = _extract_planned_files(result_str)
            if planned:
                icon_map = {"py": "🐍", "js": "🟨", "jsx": "⚛️", "tsx": "⚛️",
                            "ts": "🔷", "json": "📋", "md": "📝", "yaml": "⚙️",
                            "yml": "⚙️", "toml": "⚙️", "env": "🔑"}
                st.markdown(f"**📁 Fichiers qui seront modifiés ({len(planned)}) :**")
                for p in planned:
                    ext = p.rsplit(".", 1)[-1] if "." in p else ""
                    ico = icon_map.get(ext, "📄")
                    exists = os.path.exists(p)
                    badge = "✅ existe" if exists else "🆕 nouveau fichier"
                    st.markdown(f"  {ico} `{p}` — {badge}")
            else:
                st.caption("ℹ️ Fichiers cibles non détectés dans le rapport — vérifiez le plan ci-dessus.")

            # ── Seuil de risque automatique ──────────────────────────────────
            _SENSITIVE_PATTERNS = [
                "server.py", "main.py", "auth", "supabase", "secret",
                "migration", "schema.sql", "delete", "drop", ".env",
            ]
            _planned_lower = " ".join(planned).lower() if planned else result_str.lower()
            _sensitive_hits = [p for p in _SENSITIVE_PATTERNS if p in _planned_lower]
            _has_critical   = "CRITIQUE" in result_str.upper()

            if _has_critical:
                st.error(
                    "🚨 **FINDING CRITIQUE DÉTECTÉ — Validation bloquée**  \n"
                    "Corrigez manuellement les points CRITIQUE avant de valider.  \n"
                    "Cliquez Annuler, corrigez, puis relancez."
                )
                _can_validate = False
            elif _sensitive_hits:
                st.warning(
                    f"⚠️ **Zone sensible détectée** : `{'`, `'.join(_sensitive_hits)}`  \n"
                    "Ces fichiers/zones requièrent une attention particulière. "
                    "Relisez le rapport avant de valider."
                )
                _can_validate = True
            else:
                st.info(
                    "Relisez le rapport de sécurité ci-dessus.\n\n"
                    "**CRITIQUE** → refuser et corriger manuellement.  \n"
                    "**MOYEN / INFO** → vous pouvez valider."
                )
                _can_validate = True

            _is_dry_run = st.session_state.get("analysis_dry_run", False)

            if _is_dry_run:
                st.info(
                    "🔍 **Mode simulation actif** — aucun fichier ne sera écrit.  \n"
                    "Le rapport ci-dessus montre ce que l'agent *aurait* fait.  \n"
                    "Pour appliquer les changements, décochez Mode simulation et relancez."
                )
                if st.button("🔄 Relancer en mode réel", key="btn_rerun_real"):
                    st.session_state["phase1_done"] = False
                    st.session_state["analysis_dry_run"] = False
                    st.info("Décochez Mode simulation dans Options avancées, puis relancez.")
            else:
                col_ok, col_ko = st.columns(2)
                with col_ok:
                    if st.button(
                        "✅ Valider — Écrire les fichiers", type="primary",
                        key="btn_write", disabled=not _can_validate
                    ):
                        st.session_state["write_approved"] = True
                        st.rerun()
                with col_ko:
                    if st.button("❌ Annuler — Ne pas écrire", type="secondary", key="btn_cancel"):
                        st.session_state["phase1_done"]  = False
                        st.session_state["write_approved"] = False
                        st.warning("Écriture annulée. Les fichiers n'ont pas été modifiés.")

        # ── Phase 2 : Écriture ──
        if st.session_state.get("write_approved"):
            st.session_state["write_approved"] = False  # reset pour éviter re-run

            backend_agent    = st.session_state["backend_agent"]
            security_task    = st.session_state["security_task"]
            security_context = st.session_state["security_context"]
            project_root_w   = st.session_state["analysis_root"]
            project_w        = st.session_state["analysis_project"]
            instruction_w    = st.session_state["analysis_instruction"]
            tokens1          = st.session_state.get("analysis_tokens", {})

            # Phase 2 : Sonnet requis — Haiku échoue sur les gros contextes en écriture
            from agents import claude_sonnet
            from crewai import Agent as _Agent
            # Récupérer read/write tools depuis backend_agent de façon sécurisée
            _ba_tools = backend_agent.tools or []
            _read_tool  = _ba_tools[0] if len(_ba_tools) > 0 else None
            _write_tool = _ba_tools[1] if len(_ba_tools) > 1 else None
            _write_agent_tools = [t for t in [_read_tool, _write_tool] if t is not None]

            write_agent = _Agent(
                role="Développeur Back-end (Écriture)",
                goal="Écrire les fichiers finaux UN PAR UN avec file_writer_tool.",
                backstory=(
                    "Tu reçois le code validé et tu l'écris sur le filesystem. "
                    "Un seul appel file_writer_tool par fichier, toujours avec filename + directory + content."
                ),
                llm=claude_sonnet,
                tools=_write_agent_tools,
                verbose=True,
                max_iter=8,
            )
            write_task = make_write_task(write_agent, security_task, security_context)
            write_crew = Crew(
                agents=[write_agent],
                tasks=[write_task],
                process=Process.sequential,
                verbose=True,
                memory=False,
                respect_context_window=True,
            )

            with st.spinner("Phase 2 : écriture des fichiers..."):
                write_result = write_crew.kickoff()

            tokens2 = _extract_metrics(write_crew)
            total_tokens = {
                "total":      tokens1.get("total", 0) + tokens2.get("total", 0),
                "prompt":     tokens1.get("prompt", 0) + tokens2.get("prompt", 0),
                "completion": tokens1.get("completion", 0) + tokens2.get("completion", 0),
            }
            total_cost = _estimate_cost(total_tokens)

            st.success("✅ Phase 2 — Fichiers écrits")
            st.markdown("#### Coût total (Phase 1 + Phase 2)")
            _show_cost_metrics(total_tokens, total_cost)

            write_str = str(write_result)
            files_data = _parse_written_files(write_str)
            files_paths = _show_files_report(files_data)

            # ── PDF rapport final (Phase 1 + Phase 2) ──
            _full_result = st.session_state.get("analysis_result", "") + "\n\n" + write_str
            _pdf_final = _generate_pdf_report(
                instruction=instruction_w,
                project=project_w,
                result_str=_full_result,
                files_written=files_paths or [],
                tokens=total_tokens,
                cost=total_cost,
            )
            _ext_f = "pdf" if _pdf_final[:4] == b"%PDF" else "txt"
            st.download_button(
                "📥 Télécharger le rapport complet (PDF)",
                data=_pdf_final,
                file_name=f"squad_rapport_{project_w}_{instruction_w[:20].replace(' ','_')}.{_ext_f}",
                mime="application/pdf" if _ext_f == "pdf" else "text/plain",
                key="dl_pdf_final",
            )

            # Git diff + commit + rollback
            with st.expander("🔀 Git diff & actions", expanded=False):
                diff_output = _git_diff(project_root_w)
                st.code(diff_output, language="diff")

                col_commit, col_rollback = st.columns(2)
                with col_commit:
                    commit_msg = st.text_input(
                        "Message de commit",
                        value=f"feat: {instruction_w[:80]}",
                        key="commit_msg_code"
                    )
                    if st.button("📦 Commit", key="commit_code"):
                        commit_result = _git_commit(project_root_w, commit_msg)
                        st.code(commit_result)

                with col_rollback:
                    st.markdown("**🔙 Rollback**")
                    # Rollback fichier par fichier
                    if files_paths:
                        _rb_file = st.selectbox(
                            "Fichier à restaurer",
                            ["— sélectionner —"] + (files_paths or []),
                            key="rollback_file_select",
                        )
                        if st.button("↩️ Restaurer ce fichier", key="btn_rollback_file",
                                    disabled=_rb_file == "— sélectionner —"):
                            try:
                                import subprocess as _sp
                                _rb_result = _sp.run(
                                    ["git", "checkout", "HEAD", "--", _rb_file],
                                    cwd=project_root_w, capture_output=True, text=True
                                )
                                if _rb_result.returncode == 0:
                                    st.success(f"✅ `{_rb_file}` restauré depuis HEAD")
                                else:
                                    st.error(f"❌ {_rb_result.stderr}")
                            except Exception as e:
                                st.error(f"Erreur rollback : {e}")

                    # Rollback total
                    if st.button("⚠️ Rollback TOUT (git checkout HEAD)", key="btn_rollback_all",
                                help="Restaure tous les fichiers modifiés au dernier commit"):
                        _rb_confirm = st.session_state.get("rollback_confirm", False)
                        if not _rb_confirm:
                            st.session_state["rollback_confirm"] = True
                            st.warning("Cliquez une 2ème fois pour confirmer le rollback total.")
                        else:
                            try:
                                import subprocess as _sp2
                                _rb_all = _sp2.run(
                                    ["git", "checkout", "HEAD", "--"] + (files_paths or []),
                                    cwd=project_root_w, capture_output=True, text=True
                                )
                                st.session_state["rollback_confirm"] = False
                                if _rb_all.returncode == 0:
                                    st.success(f"✅ {len(files_paths or [])} fichier(s) restauré(s)")
                                else:
                                    st.error(f"❌ {_rb_all.stderr}")
                            except Exception as e:
                                st.error(f"Erreur rollback : {e}")
                    else:
                        st.session_state["rollback_confirm"] = False

            # Railway health check
            if project_w == "FindUP":
                with st.expander("🏥 Railway health check", expanded=False):
                    if st.button("Vérifier le déploiement", key="railway_check_code"):
                        health = _check_railway(RAILWAY_URL)
                        if health["ok"]:
                            st.success(f"✅ Railway OK — HTTP {health['status']}")
                        else:
                            st.error(f"❌ Railway KO — {health.get('status', 0)} {health.get('error', '')}")

            # Historique
            save_run(
                run_type="code",
                project=project_w,
                instruction=instruction_w,
                result=st.session_state.get("analysis_result", "") + "\n\n---\n\n" + write_str,
                prompt_tokens=total_tokens["prompt"],
                completion_tokens=total_tokens["completion"],
                total_tokens=total_tokens["total"],
                files_modified=files_paths or [],
            )

            # Reset Phase 1
            st.session_state["phase1_done"] = False


    # ── Tab 2 : Recherche Web ─────────────────────────────────────────────────────
