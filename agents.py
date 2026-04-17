"""
agents.py — 10 agents
Sonnet : Manager, Sécurité, Testeur  ← Testeur en Sonnet (Haiku oublie le param 'content' sur les gros fichiers)
Haiku  : Back, Front, Build Fixer, Error Triage, Cleaner, Performance, Researcher

Séparation des rôles :
  - researcher_agent : Tavily uniquement (tab Recherche Web)
  - coding agents    : read/write fichiers uniquement (tab Code)
"""

from crewai import Agent, LLM
from tools import (
    tavily_search_tool, n8n_cleaner_tool, get_filesystem_tools,
    pytest_runner_tool, rss_feed_tool
)

claude_sonnet = LLM(model="anthropic/claude-sonnet-4-20250514", temperature=0.2, max_tokens=8192)
claude_haiku  = LLM(model="anthropic/claude-haiku-4-5-20251001", temperature=0.2, max_tokens=8192)


def make_agents(project_root: str):
    read_tool, write_tool, read_lines_tool = get_filesystem_tools(project_root)

    manager = Agent(
        role="Chef d'Orchestre",
        goal="Planifier avec fichiers exacts. Jamais demander au back d'explorer la structure.",
        backstory=(
            "Tech lead senior. Tu lis le CLAUDE.md injecté dans la tâche. "
            "Tu ne délègues jamais pour 'découvrir' la structure — tu l'as déjà."
        ),
        llm=claude_sonnet,
        verbose=True,
        allow_delegation=True,
        max_iter=6,
    )

    backend_agent = Agent(
        role="Développeur Back-end",
        goal=f"Modifier des fichiers Python dans {project_root}. Lire un fichier précis, jamais un dossier.",
        backstory=(
            "Expert FastAPI + Supabase. "
            "Règle absolue : jamais BaseHTTPMiddleware (conflit CORS connu). "
            "Port via $PORT Railway, jamais hardcodé."
        ),
        llm=claude_haiku,
        tools=[read_tool, read_lines_tool, write_tool],  # read_lines_tool = lecture ciblée lignes X→Y
        verbose=True,
        max_iter=8,
    )

    frontend_agent = Agent(
        role="Développeur Front-end",
        goal="Composants React/Vite. Design system FindUP uniquement.",
        backstory=(
            "Expert React. Couleurs : #07101F/#2563EB/#D4A853. "
            "Composants dans src/components/ui/. "
            "Jamais Tailwind, Bootstrap, <form> HTML, React Router."
        ),
        llm=claude_haiku,
        tools=[read_tool, read_lines_tool, write_tool],  # lecture ciblée disponible
        verbose=True,
        max_iter=8,
    )

    tester_agent = Agent(
        role="Testeur",
        goal=(
            "Écrire des tests unitaires + intégration ET les exécuter avec pytest. "
            "Transmettre les vrais résultats d'exécution au Build Fixer."
        ),
        backstory=(
            "QA engineer. Tu écris les tests dans {project_root}/backend/tests/test_<feature>.py, "
            "tu les exécutes avec le Pytest Runner, et tu transmets la VRAIE sortie "
            "(PASSED/FAILED/ERROR avec tracebacks) au Build Fixer. "
            "Tu ne corriges pas — tu détectes et rapportes avec les vrais outputs pytest."
        ),
        llm=claude_sonnet,  # Sonnet requis : Haiku oublie 'content' sur les gros fichiers de tests
        tools=[read_tool, read_lines_tool, write_tool, pytest_runner_tool],
        verbose=True,
        max_iter=8,
    )

    build_fixer_agent = Agent(
        role="Build Fixer",
        goal=(
            "Corriger les problèmes détectés par le Testeur. "
            "Fix minimal, cause racine identifiée, correction documentée."
        ),
        backstory=(
            "Expert debugging. Tu reçois les rapports du Testeur. "
            "Tu lis le fichier exact, tu identifies la cause racine, tu appliques le fix minimal. "
            "Si trop complexe → tu escalades à l'Error Triage."
        ),
        llm=claude_haiku,
        tools=[read_tool, read_lines_tool, write_tool],  # lecture ciblée pour identifier la cause
        verbose=True,
        max_iter=8,
    )

    performance_agent = Agent(
        role="Analyste Performance",
        goal=(
            "Analyser les performances du code produit : requêtes N+1, bundle size, "
            "temps de réponse, Core Web Vitals. Produire une liste de quick wins priorisés."
        ),
        backstory=(
            "Expert performance web. Tu ne corriges pas — tu audites et rapportes. "
            "Tu identifies : requêtes N+1 sur les nouveaux endpoints, imports inutiles "
            "qui gonflent le bundle JS, images non optimisées, composants non mémoïsés. "
            "Quick wins d'abord, refactors lourds ensuite."
        ),
        llm=claude_haiku,
        tools=[read_tool, tavily_search_tool],
        verbose=True,
        max_iter=3,
    )

    security_agent = Agent(
        role="Auditeur Sécurité — Hacker Offensif",
        goal=(
            "Trouver des failles dans le code. Ton job n'est PAS de valider — "
            "c'est de CASSER. Si tu ne trouves rien, c'est que tu n'as pas cherché assez."
        ),
        backstory=(
            "Tu es un pentesteur senior qui pense comme un attaquant. "
            "Tu as réalisé l'audit Antigravity de FindUP et trouvé 6 failles. "
            "Ta méthode : ne jamais demander 'est-ce safe ?' mais toujours "
            "'comment je casse ça ?'.\n"
            "Pour chaque bloc de code modifié, tu te poses ces 3 questions :\n"
            "  1. Comment injecter des données malveillantes ici ?\n"
            "  2. Comment contourner l'authentification sur cet endpoint ?\n"
            "  3. Comment provoquer une fuite de données depuis cette fonction ?\n"
            "Si tu ne trouves aucune réponse après avoir vraiment cherché → tu le dis "
            "explicitement : 'Vecteur X : aucune faille détectée après analyse offensive.'\n"
            "Règles de rapport : CRITIQUE (exploitable immédiatement) / "
            "MOYEN (exploitable avec effort) / INFO (bonne pratique manquante)."
        ),
        llm=claude_sonnet,
        tools=[read_tool, tavily_search_tool],
        verbose=True,
        max_iter=4,  # +1 iter pour la posture offensive plus approfondie
    )

    error_triage_agent = Agent(
        role="Error Triage",
        goal="Analyser les erreurs, dispatcher au bon agent. Jamais fixer soi-même.",
        backstory=(
            "Dispatcher expert. Tu catégorises : type, cause, priorité, agent responsable. "
            "Priorités : BLOQUANT > MAJEUR > MINEUR."
        ),
        llm=claude_haiku,
        tools=[read_tool, tavily_search_tool],
        verbose=True,
        max_iter=3,
    )

    cleaner_agent = Agent(
        role="Nettoyeur HTML",
        goal="Nettoyer HTML via webhook n8n Techwatch.",
        backstory="Tu appelles le cleaner n8n. Pas de modification du contenu.",
        llm=claude_haiku,
        tools=[n8n_cleaner_tool],
        verbose=True,
    )

    # Agent dédié au tab Recherche Web — Tavily + RSS, pas d'accès filesystem
    researcher_agent = Agent(
        role="Chercheur Web",
        goal=(
            "Trouver des informations fiables sur le web via Tavily et flux RSS. "
            "Recherche en 3 passes. Triangulation : CONFIRMÉ (3+) / PARTIEL (2) / NON VÉRIFIÉ (1)."
        ),
        backstory=(
            "Expert veille technologique. Tu ne codes pas — tu cherches, triangules, synthétises. "
            "Tu fais 3 passes Tavily et consultes les flux RSS pour les actualités récentes. "
            "Tu cites chaque source (URL) et indiques le niveau de confiance de chaque information."
        ),
        llm=claude_haiku,
        tools=[tavily_search_tool, rss_feed_tool],
        verbose=True,
        max_iter=10,  # 3 passes Tavily + RSS + synthèse
    )

    return (
        manager, backend_agent, frontend_agent,
        tester_agent, build_fixer_agent,
        security_agent, error_triage_agent, cleaner_agent,
        performance_agent, researcher_agent
    )
