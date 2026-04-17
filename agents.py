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
from prompts import (
    AGENT_MANAGER_GOAL, AGENT_MANAGER_BACKSTORY,
    AGENT_BACKEND_BACKSTORY, AGENT_FRONTEND_BACKSTORY,
    AGENT_SECURITY_ROLE, AGENT_SECURITY_GOAL, AGENT_SECURITY_BACKSTORY,
    AGENT_BUILDFIXER_BACKSTORY, AGENT_RESEARCHER_GOAL,
)

claude_sonnet = LLM(model="anthropic/claude-sonnet-4-20250514", temperature=0.2, max_tokens=8192)
claude_haiku  = LLM(model="anthropic/claude-haiku-4-5-20251001", temperature=0.2, max_tokens=8192)


def make_agents(project_root: str):
    read_tool, write_tool, read_lines_tool = get_filesystem_tools(project_root)

    manager = Agent(
        role="Chef d'Orchestre",
        goal=AGENT_MANAGER_GOAL,
        backstory=AGENT_MANAGER_BACKSTORY,
        llm=claude_sonnet,
        verbose=True,
        allow_delegation=True,
        max_iter=6,
    )

    backend_agent = Agent(
        role="Développeur Back-end",
        goal=f"Modifier des fichiers Python dans {project_root}. Lire un fichier précis, jamais un dossier.",
        backstory=AGENT_BACKEND_BACKSTORY,
        llm=claude_haiku,
        tools=[read_tool, read_lines_tool, write_tool],  # read_lines_tool = lecture ciblée lignes X→Y
        verbose=True,
        max_iter=8,
    )

    frontend_agent = Agent(
        role="Développeur Front-end",
        goal="Composants React/Vite. Design system FindUP uniquement.",
        backstory=AGENT_FRONTEND_BACKSTORY,
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
        backstory=AGENT_BUILDFIXER_BACKSTORY,
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
        role=AGENT_SECURITY_ROLE,
        goal=AGENT_SECURITY_GOAL,
        backstory=AGENT_SECURITY_BACKSTORY,
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
        goal=AGENT_RESEARCHER_GOAL,
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
