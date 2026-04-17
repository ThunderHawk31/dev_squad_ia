"""
tasks.py — Injection contextuelle sélective + Tester + Build Fixer
Pipeline Code en 2 phases :
  Phase 1 : make_code_task_analysis()  — Plan → Code → Tests → Sécurité (lecture seule)
  Phase 2 : make_write_task()          — Écriture des fichiers après validation humaine dans l'UI
"""

import os
from crewai import Task


def _load_claude_md(project_root: str) -> str:
    path = os.path.join(project_root, "CLAUDE.md")
    if os.path.exists(path):
        with open(path) as f:
            return f.read()
    return "Pas de CLAUDE.md — explorer le projet pour comprendre sa structure."


def _build_function_index(project_root: str, max_files: int = 5) -> str:
    """
    Construit un index compact fonctions/classes → numéros de lignes
    pour les fichiers Python principaux du projet.
    
    L'index est injecté dans la tâche Manager pour que le plan inclue
    des numéros de lignes exacts — évite à l'agent de chercher les fonctions.
    
    Format de sortie (compact, ~1 token par entrée) :
      server.py: get_artisans:254 | post_artisan:280 | chat_send:312 ...
    """
    import ast as _ast
    
    # Fichiers à indexer par priorité
    candidates = [
        "backend/server.py", "backend/main.py", "server.py", "main.py",
        "app.py", "backend/app.py", "api/routes.py",
    ]
    
    index_lines = []
    scanned = 0
    
    for rel_path in candidates:
        if scanned >= max_files:
            break
        full_path = os.path.join(project_root, rel_path)
        if not os.path.exists(full_path):
            continue
        
        try:
            with open(full_path, encoding="utf-8", errors="ignore") as f:
                source = f.read()
            
            tree = _ast.parse(source)
            entries = []
            
            for node in _ast.walk(tree):
                if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                    # Ignorer les fonctions privées très courtes (helpers internes)
                    if not node.name.startswith("__"):
                        entries.append(f"{node.name}:{node.lineno}")
                elif isinstance(node, _ast.ClassDef):
                    entries.append(f"[{node.name}]:{node.lineno}")
            
            if entries:
                # Trier par numéro de ligne
                entries.sort(key=lambda e: int(e.split(":")[-1]))
                fname = os.path.basename(full_path)
                total_lines = source.count("\n") + 1
                index_lines.append(
                    f"{fname} ({total_lines}L): " + " | ".join(entries[:40])
                )
                scanned += 1
        
        except Exception:
            continue  # Fichier non parseable — ignorer silencieusement
    
    if not index_lines:
        return ""
    
    return (
        "=== INDEX FONCTIONS (lignes exactes) ===\n"
        + "\n".join(index_lines)
        + "\n=== FIN INDEX ===\n"
    )


def _extract_section(claude_md: str, keywords: list[str]) -> str:
    """Extrait uniquement les sections pertinentes du CLAUDE.md."""
    lines = claude_md.split("\n")
    result = []
    current_section = []
    in_relevant = False

    for line in lines:
        if line.startswith("## "):
            # Sauvegarder section précédente si pertinente
            if in_relevant and current_section:
                result.extend(current_section)
            # Nouvelle section
            current_section = [line]
            in_relevant = any(kw.lower() in line.lower() for kw in keywords)
        else:
            current_section.append(line)

    # Dernière section
    if in_relevant and current_section:
        result.extend(current_section)

    # Toujours inclure le header du projet (première section)
    header_lines = []
    for line in lines:
        if line.startswith("## ") and len(header_lines) > 0:
            break
        header_lines.append(line)

    combined = "\n".join(header_lines) + "\n\n" + "\n".join(result)
    return combined if result else claude_md  # fallback sur tout le fichier


def _ctx(claude_md: str, role: str) -> str:
    """Retourne le contexte pertinent selon le rôle de l'agent."""
    role_keywords = {
        "manager":      ["projet", "équipe", "stack", "priorité", "ordre"],
        "backend":      ["backend", "architecture", "variables", "railway", "infra", "sécurité", "conventions"],
        "frontend":     ["frontend", "design", "composant", "react", "conventions"],
        "security":     ["sécurité", "faille", "antigravity", "auth"],
        "tester":       ["conventions", "backend", "frontend", "stack"],
        "buildfix":     ["backend", "infra", "railway", "conventions"],
        "performance":  ["backend", "frontend", "architecture", "conventions"],
    }
    keywords = role_keywords.get(role, ["projet", "stack"])
    section = _extract_section(claude_md, keywords)
    return f"=== CONTEXTE PROJET (CLAUDE.md — extrait {role}) ===\n{section}\n=== FIN ===\n\n"


# ── Phase 1 : Analyse ─────────────────────────────────────────────────────────

def make_code_task_analysis(
    instruction: str,
    manager, backend_agent, frontend_agent, security_agent,
    error_triage_agent, tester_agent, build_fixer_agent,
    project_root: str,
    performance_agent=None,
    include_tests: bool = True,
    include_performance: bool = False,
    include_frontend: bool = True,
    include_security: bool = True,
) -> tuple:
    """
    Phase 1 : Plan → Code → Tests → Sécurité (SANS écriture de fichiers).
    Retourne (tasks, security_task, security_context, backend_agent)
    pour que l'UI puisse construire la Phase 2 après validation humaine.
    """
    claude_md = _load_claude_md(project_root)
    
    # Construire l'index des fonctions pour guider le Manager
    _func_index = _build_function_index(project_root)

    # Tâche 1 — Manager planifie
    analysis_task = Task(
        description=(
            _ctx(claude_md, "manager") +
            (_func_index if _func_index else "") +
            f"Demande : {instruction}\n\n"
            "Décompose en étapes concrètes. Pour chaque modification back-end :\n"
            "  - Donner le chemin ABSOLU du fichier à modifier\n"
            "  - Donner les numéros de lignes EXACTS depuis l'index ci-dessus\n"
            "    (ex: 'modifier get_artisans — ligne 254')\n"
            "  - Décrire UNIQUEMENT les lignes à ajouter ou modifier\n"
            "INTERDIT : demander au back-end de lire le fichier entier.\n"
            "N'envoie PAS le back-end explorer la structure — tu as l'index et le CLAUDE.md."
        ),
        expected_output=(
            "Plan avec pour chaque fichier : chemin absolu, numéros de lignes EXACTS "
            "(depuis l'index fonctions), description précise des modifications."
        ),
        agent=manager,
    )

    # Tâche 2 — Back-end implémente
    # Injection du chemin exact dans la description pour ancrer l'agent
    _backend_files = f"Fichiers à modifier selon le plan (chemins exacts depuis CLAUDE.md) : {project_root}"

    backend_task = Task(
        description=(
            _ctx(claude_md, "backend") +
            f"{_backend_files}\n\n"
            "PROTOCOLE DE LECTURE CHIRURGICALE (3 niveaux) :\n\n"
            "  NIVEAU 1 — Lecture ciblée avec read_file_lines (toujours commencer ici) :\n"
            "    → Utiliser l'outil read_file_lines avec les numéros de lignes du plan du Manager.\n"
            "    → Paramètres : file_path=/chemin/absolu, start_line=N, num_lines=50\n"
            "    → Maximum 50 lignes par lecture. JAMAIS FileReadTool sur un gros fichier.\n\n"
            "  NIVEAU 2 — Remontée au caller avec read_file_lines (si dépendance externe) :\n"
            "    → Si la fonction utilise une variable/fonction définie ailleurs :\n"
            "       a) Identifier le nom exact (ex: `chat_rate_limiter`, `supabase_anon`)\n"
            "       b) Appeler read_file_lines(start_line=ligne_de_définition, num_lines=15)\n"
            "       c) Maximum 2 remontées — si toujours bloqué → documenter le blocage\n"
            "    → Coût : 15 lignes via read_file_lines vs 800 lignes via FileReadTool\n\n"
            "  NIVEAU 3 — Structure du fichier (en dernier recours) :\n"
            "    → read_file_lines(start_line=1, num_lines=30) — imports + globals uniquement\n"
            "    → Jamais aller au-delà sans raison documentée\n\n"
            "RÈGLES ABSOLUES :\n"
            "  - PATCH UNIQUEMENT : modifier seulement les lignes du plan. "
            "Si file_writer_tool écrit > 100 lignes → STOP.\n"
            "  - FICHIER EXACT du Manager uniquement — pas de nouveaux fichiers parasites.\n"
            "  - Jamais BaseHTTPMiddleware."
        ),
        expected_output=(
            "Code des lignes modifiées (pas le fichier entier), chemin absolu, numéros de lignes. "
            "Si remontée au caller effectuée : documenter quelle dépendance et pourquoi."
        ),
        agent=backend_agent,
        context=[analysis_task],
    )

    tasks = [analysis_task, backend_task]
    last_fix_task = None

    # Tâche 3 — Front-end (optionnel)
    if include_frontend:
        frontend_task = Task(
            description=(
                _ctx(claude_md, "frontend") +
                "Implémenter les modifications front-end. "
                "Design system : #07101F/#2563EB/#D4A853. "
                "Jamais Tailwind, Bootstrap, ni <form> HTML."
            ),
            expected_output="Composants React cohérents avec le design system.",
            agent=frontend_agent,
            context=[analysis_task, backend_task],
        )
        tasks.append(frontend_task)

    # Tâches 4-5 optionnelles — Tester + Build Fixer
    if include_tests:
        tester_task = Task(
            description=(
                _ctx(claude_md, "tester") +
                f"Écrire ET exécuter les tests pour le code produit par Back-end et Front-end.\n\n"
                f"ÉTAPE 1 — Écrire le fichier de tests :\n"
                f"  Créer UN SEUL fichier : {project_root}/backend/tests/test_<feature>.py\n"
                f"  RÈGLE : appeler file_writer_tool avec filename + directory + content dans le MÊME appel.\n"
                f"  Ne jamais appeler file_writer_tool sans le paramètre 'content'.\n"
                f"  Le conftest.py avec mocks Supabase/Anthropic est déjà présent dans ce dossier.\n"
                f"  Tests unitaires : chaque fonction modifiée\n"
                f"  Tests d'intégration : chaque endpoint créé (utiliser le fixture 'client')\n"
                f"  Edge cases : inputs invalides, auth manquante, erreurs DB\n\n"
                f"ÉTAPE 2 — Exécuter avec Pytest Runner :\n"
                f"  Appeler l'outil 'Pytest Runner' sur le fichier créé.\n"
                f"  Inclure la sortie pytest COMPLÈTE dans ton rapport (PASSED/FAILED/ERROR + tracebacks).\n\n"
                f"ÉTAPE 3 — Rapport au Build Fixer :\n"
                f"  Lister les tests FAILED avec leur traceback exact.\n"
                f"  Le Build Fixer a besoin des vraies erreurs, pas des résultats 'attendus'."
            ),
            expected_output=(
                "Rapport avec : chemin du fichier de tests créé, "
                "sortie pytest complète (PASSED/FAILED/ERROR), "
                "et liste des échecs à corriger avec tracebacks."
            ),
            agent=tester_agent,
            context=[backend_task] + ([frontend_task] if include_frontend else []),
        )
        build_fixer_task = Task(
            description=(
                _ctx(claude_md, "buildfix") +
                "Analyser le rapport du Tester et corriger les problèmes détectés.\n\n"
                "Process :\n"
                "1. Lire UNIQUEMENT le fichier exact mentionné dans le traceback\n"
                "2. Identifier la cause racine (environnement ? import ? logique ?)\n"
                "3. Appliquer le fix minimal — jamais réécrire le fichier entier\n"
                "4. Documenter la correction avec ce format EXACT :\n"
                "   TENTATIVE_1 | Erreur: <message> | Fix: <description> | Fichier: <chemin>\n\n"
                "STATE LOGGER ANTI-BOUCLE (obligatoire) :\n"
                "  - Avant chaque tentative, comparer avec la tentative précédente :\n"
                "    * Si le traceback est IDENTIQUE à la tentative N-1 → STOP immédiat.\n"
                "    * Écrire : 'BOUCLE DÉTECTÉE — même erreur après fix — intervention humaine requise'\n"
                "    * Ne jamais appliquer le même fix deux fois.\n"
                "  - Maximum 2 tentatives par erreur différente.\n\n"
                "RÈGLES ABSOLUES :\n"
                "  - Erreur dans conftest.py ou env → corriger UNIQUEMENT le fichier de test.\n"
                "  - Variable d'env manquante → documenter, ne pas boucler.\n"
                "  - INTERDIT de modifier server.py/main.py pour un mock mal configuré."
            ),
            expected_output=(
                "Rapport structuré avec STATE LOG :\n"
                "TENTATIVE_N | Erreur | Fix appliqué | Résultat (RÉSOLU / BOUCLE / BLOQUÉ)\n"
                "Si BOUCLE ou BLOQUÉ : description précise pour intervention humaine."
            ),
            agent=build_fixer_agent,
            context=[tester_task],
        )
        tasks += [tester_task, build_fixer_task]
        last_fix_task = build_fixer_task

    # Tâche optionnelle — Performance
    if include_performance and performance_agent:
        perf_context = [backend_task]
        if include_frontend and 'frontend_task' in dir():
            perf_context.append(frontend_task)
        if last_fix_task:
            perf_context.append(last_fix_task)
        performance_task = Task(
            description=(
                _ctx(claude_md, "performance") +
                "Analyser les performances du code produit.\n"
                "1. Requêtes N+1 sur les nouveaux endpoints\n"
                "2. Imports inutiles / dead code qui gonfle le bundle JS\n"
                "3. Composants React non mémoïsés qui re-render inutilement\n"
                "4. Temps de réponse estimés des nouveaux endpoints\n"
                "Produire une liste ordonnée par impact (quick wins d'abord)."
            ),
            expected_output="Rapport de performance avec quick wins priorisés.",
            agent=performance_agent,
            context=perf_context,
        )
        tasks.append(performance_task)
        last_fix_task = performance_task

    # Tâche Sécurité — optionnelle (mode patch = sans audit)
    base_context = [backend_task] + ([frontend_task] if include_frontend else [])
    security_context = base_context + ([last_fix_task] if last_fix_task else [])

    if include_security:
        # Récupérer le git diff pour limiter l'analyse aux lignes modifiées
        import subprocess as _sp
        try:
            _diff = _sp.run(
                ["git", "diff", "HEAD"],
                cwd=project_root, capture_output=True, text=True, timeout=8
            ).stdout.strip()
            _diff_hint = (
                f"\n\n=== GIT DIFF (lignes modifiées uniquement) ===\n{_diff[:3000]}\n=== FIN DIFF ===\n"
                if _diff else ""
            )
        except Exception:
            _diff_hint = ""

        security_task = Task(
            description=(
                _ctx(claude_md, "security") +
                "Tu es un pentesteur. Ton job : CASSER ce code, pas le valider.\n\n"
                "MÉTHODE OFFENSIVE — pour chaque modification du diff :\n"
                "  1. Injection : peut-on injecter des données malveillantes ?\n"
                "  2. Auth bypass : peut-on contourner l'authentification ?\n"
                "  3. Data leak : peut-on provoquer une fuite de données ?\n\n"
                "FOCUS : analyse UNIQUEMENT les lignes commençant par '+' dans le diff.\n"
                "Si une nouvelle dépendance apparaît → vérifier qu'elle est dans requirements.txt.\n"
                "Si aucune faille trouvée sur un vecteur → l'écrire explicitement.\n"
                + _diff_hint +
                "\nRéférence : 6 failles Antigravity du CLAUDE.md.\n"
                "Rapport final : CRITIQUE / MOYEN / INFO avec vecteur d'attaque pour chaque finding."
            ),
            expected_output=(
                "Rapport offensif structuré :\n"
                "- Résumé : N findings (X CRITIQUE, Y MOYEN, Z INFO)\n"
                "- Par finding : vecteur d'attaque, ligne concernée, impact, recommandation\n"
                "- Vecteurs sans faille : liste explicite des vecteurs analysés et jugés sûrs"
            ),
            agent=security_agent,
            context=security_context,
        )
        tasks.append(security_task)
    else:
        # Mode patch : pas d'audit, la tâche backend sert de pivot pour la Phase 2
        security_task = backend_task
        security_context = [backend_task]

    return tasks, security_task, security_context, backend_agent


# ── Phase 2 : Écriture ────────────────────────────────────────────────────────

def make_write_task(backend_agent, security_task: Task, security_context: list) -> Task:
    """
    Phase 2 : Écriture des fichiers — déclenchée manuellement après validation humaine.
    Format de réponse strict pour le parsing automatique dans l'UI.
    """
    return Task(
        description=(
            "Écrire les fichiers finaux. Le rapport de sécurité a été validé par l'humain.\n"
            "Le plan et le code produit sont dans le contexte ci-dessus.\n\n"
            "DÉTECTER LE TYPE DE MODIFICATION avant d'écrire :\n"
            "  TYPE A — PATCH (modification de fichier existant) :\n"
            "    → Lire uniquement les lignes concernées (start_line + line_count).\n"
            "    → Écrire UNIQUEMENT les lignes modifiées avec file_writer_tool.\n"
            "    → Si le fichier fait < 80 lignes au total → écrire le fichier entier est OK.\n"
            "    → Si le fichier fait > 80 lignes → INTERDIT d'écrire le fichier entier.\n\n"
            "  TYPE B — NOUVEAU FICHIER (création) :\n"
            "    → Vérifier que le fichier n'existe pas déjà (read_tool pour confirmer).\n"
            "    → Écrire le contenu complet d'un coup avec file_writer_tool.\n"
            "    → Documenter clairement : 'Nouveau fichier créé : /chemin/complet.py'\n\n"
            "  TYPE C — REFACTO LOURD (> 50% du fichier change) :\n"
            "    → Lire le fichier entier d'abord pour confirmer le contexte.\n"
            "    → Écrire le fichier entier avec file_writer_tool (explicitement voulu).\n"
            "    → Documenter : 'Refacto complet — fichier entier réécrit (N lignes)'\n\n"
            "RÈGLES file_writer_tool (tous types) :\n"
            "  - UNE SEULE FOIS PAR FICHIER — filename + directory + content dans le MÊME appel.\n"
            "  - Ne JAMAIS appeler sans 'content'.\n"
            "  - Ne JAMAIS inventer un chemin — utiliser uniquement ceux du plan du Manager.\n\n"
            "Pour chaque fichier, répondre EXACTEMENT :\n"
            "FICHIER: /chemin/absolu/vers/fichier.py  (N lignes — TYPE: patch/nouveau/refacto)"
        ),
        expected_output=(
            "Liste avec format strict, une ligne par fichier :\n"
            "FICHIER: /chemin/absolu/vers/fichier.ext  (N lignes — TYPE: patch/nouveau/refacto)"
        ),
        agent=backend_agent,
        context=[security_task],
    )


# ── Recherche Web ─────────────────────────────────────────────────────────────

def make_research_task(query: str, researcher_agent) -> list:
    """
    Tab Recherche Web — 3 passes structurées pour une triangulation rigoureuse.
    Passe 1 : large → Passe 2 : approfondissement → Passe 3 : contradictions → Synthèse
    """
    search_task = Task(
        description=(
            f"Sujet de recherche : **{query}**\n\n"

            "Tu dois effectuer 3 passes de recherche distinctes. "
            "Ne passe pas à la suivante sans avoir complété la précédente.\n\n"

            "FILTRE ANTI-CONTAMINATION (appliquer à chaque source) :\n"
            "  - Source datant d'avant 2024 ET portant sur une lib/API active → "
            "marquer UNCONFIRMED, ne pas l'utiliser dans les recommandations de code.\n"
            "  - Si 2 sources divergent sur une syntaxe API → marquer CONFLICT, "
            "ne pas trancher — signaler au Chef d'Orchestre pour décision humaine.\n"
            "  - Toujours vérifier l'année de publication avant d'extraire une info technique.\n\n"
            "═══ PASSE 1 — Recherche large ═══\n"
            "Appelle Tavily avec la query principale telle quelle.\n"
            "Objectif : collecter 5 sources générales sur le sujet.\n"
            "Pour chaque source : note le titre, l'URL, l'année, et l'information clé.\n"
            "Marque chaque info : CONFIRMÉ (3+ sources) / PARTIEL (2) / NON VÉRIFIÉ (1) / "
            "UNCONFIRMED (source < 2024 sur lib active) / CONFLICT (sources contradictoires).\n\n"

            "═══ PASSE 2 — Approfondissement ═══\n"
            "Identifie les points marqués PARTIEL ou NON VÉRIFIÉ à l'étape 1.\n"
            "Pour chacun, relance Tavily avec une query reformulée et plus précise.\n"
            "Exemple : si la Passe 1 donne 'JWT refresh token' avec 1 source → "
            "cherche 'JWT refresh token expiry best practice 2025 FastAPI'.\n"
            "Mets à jour le niveau de confiance si de nouvelles sources confirment.\n\n"

            "═══ PASSE 3 — Contradictions ═══\n"
            "Cherche activement ce qui contredit ou nuance tes conclusions.\n"
            "Query Tavily : ajoute 'problème', 'danger', 'alternative', 'contre', 'vs' à ta query.\n"
            "Si tu trouves des contradictions, les noter explicitement dans la synthèse.\n\n"

            "═══ BONUS — Flux RSS (si actualité récente) ═══\n"
            "Si le sujet touche à la cybersécurité → appelle RSS Feed Reader avec 'cyber'.\n"
            "Si le sujet touche à l'IA → appelle RSS Feed Reader avec 'ia'.\n"
            "Si le sujet touche à la finance → appelle RSS Feed Reader avec 'finance'.\n"
            "Sinon → appelle RSS Feed Reader avec 'general'.\n\n"

            "═══ SYNTHÈSE FINALE ═══\n"
            "Structure ta réponse ainsi :\n"
            "## Résumé exécutif (3-5 lignes)\n"
            "## Informations CONFIRMÉES (3+ sources récentes)\n"
            "   - [info] — Sources : [URL1], [URL2], [URL3]\n"
            "## Informations PARTIELLES (2 sources)\n"
            "   - [info] — Sources : [URL1], [URL2]\n"
            "## Informations NON VÉRIFIÉES (1 source)\n"
            "   - [info] — Source : [URL]\n"
            "## ⚠️ UNCONFIRMED (sources obsolètes < 2024)\n"
            "   - [info] — Source : [URL] — NE PAS utiliser dans du code sans vérification\n"
            "## ⚡ CONFLICT (sources contradictoires — décision humaine requise)\n"
            "   - [info] — Source A dit X, Source B dit Y — attendre validation\n"
            "## Contradictions et nuances\n"
            "## Actualités RSS récentes (si pertinent)\n"
            "## Recommandation / conclusion"
        ),
        expected_output=(
            "Rapport structuré en 5 sections : Résumé / CONFIRMÉ / PARTIEL / NON VÉRIFIÉ / Contradictions. "
            "Chaque information cite sa ou ses URLs sources. "
            "Niveau de confiance explicite pour chaque info."
        ),
        agent=researcher_agent,
    )
    return [search_task]



# ── Error Triage ──────────────────────────────────────────────────────────────

def make_error_triage_task(error_description: str, error_triage_agent, backend_agent, build_fixer_agent) -> list:
    triage_task = Task(
        description=(
            f"Erreur signalée : {error_description}\n\n"
            "Analyser et produire :\n"
            "1. Type (backend/frontend/sécurité/infra)\n"
            "2. Cause racine probable\n"
            "3. Priorité (BLOQUANT/MAJEUR/MINEUR)\n"
            "4. Agent responsable du fix\n"
            "5. Fichiers à examiner en priorité"
        ),
        expected_output="Rapport de triage structuré avec agent assigné.",
        agent=error_triage_agent,
    )

    fix_task = Task(
        description=(
            "Corriger l'erreur selon le rapport de triage.\n"
            "1. Lire le fichier exact identifié\n"
            "2. Appliquer le fix minimal\n"
            "3. Expliquer la correction"
        ),
        expected_output="Code corrigé avec explication et chemin du fichier.",
        agent=build_fixer_agent,
        context=[triage_task],
        # human_input désactivé : bloque Streamlit
    )

    return [triage_task, fix_task]


# ── Auto-génération CLAUDE.md ─────────────────────────────────────────────────

def make_claude_md_task(project_root: str, backend_agent) -> Task:
    """
    Génère automatiquement le CLAUDE.md d'un projet en analysant ses fichiers clés.
    L'agent lit les fichiers importants et produit un CLAUDE.md ≤150 lignes.
    """
    # Fichiers à lire selon le type de projet (chemins relatifs à project_root)
    files_to_read = [
        "README.md", "requirements.txt", "package.json",
        "server.py", "main.py", "app.py",
        "src/main.jsx", "src/App.jsx", "src/App.tsx",
        ".env.example", "railway.json", "Procfile",
    ]
    files_hint = "\n".join(f"  - {project_root}/{f}" for f in files_to_read)

    return Task(
        description=(
            f"Analyser le projet situé dans : {project_root}\n\n"
            "ÉTAPE 1 — Lire les fichiers clés du projet (s'ils existent) :\n"
            f"{files_hint}\n\n"
            "ÉTAPE 2 — Identifier :\n"
            "  - Le stack technique (langage, frameworks, BDD, auth)\n"
            "  - L'architecture principale (endpoints clés, composants principaux)\n"
            "  - Les variables d'environnement nécessaires\n"
            "  - Les conventions de code visibles (nommage, structure)\n"
            "  - Les failles ou anti-patterns connus (ex: BaseHTTPMiddleware, hardcoded secrets)\n\n"
            "ÉTAPE 3 — Écrire le CLAUDE.md en suivant EXACTEMENT ce template :\n\n"
            "```markdown\n"
            "# [Nom du projet]\n\n"
            "## Stack\n"
            "[Technologies utilisées]\n\n"
            "## Architecture backend\n"
            "[Fichiers clés, endpoints principaux, BDD]\n\n"
            "## Architecture frontend\n"
            "[Composants principaux, routing, design system]\n\n"
            "## Variables d'environnement\n"
            "[Clés nécessaires avec description]\n\n"
            "## Failles et anti-patterns connus\n"
            "[Ce qu'il NE faut PAS faire — ex: jamais BaseHTTPMiddleware]\n\n"
            "## Conventions\n"
            "[Nommage, structure des fichiers, règles de code]\n\n"
            "## Ordre de priorité des tâches\n"
            "[Ce que l'équipe fait en priorité]\n"
            "```\n\n"
            "CONTRAINTES ABSOLUES :\n"
            "  - Le fichier final doit faire ≤ 150 lignes (sinon tokens fantômes)\n"
            "  - Écrire dans un style dense et précis — pas de phrases longues\n"
            "  - Utiliser des listes à puces, pas des paragraphes\n"
            f"  - Sauvegarder dans : {project_root}/CLAUDE.md\n"
        ),
        expected_output=(
            f"Contenu du CLAUDE.md généré (≤150 lignes), "
            f"sauvegardé dans {project_root}/CLAUDE.md"
        ),
        agent=backend_agent,
    )
