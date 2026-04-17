"""
tools.py — Outils disponibles pour les agents
"""

import os
import sys
import subprocess
import requests
from crewai_tools import TavilySearchTool, FileReadTool, FileWriterTool
from crewai.tools import BaseTool
from pydantic import Field

# ── Tavily ───────────────────────────────────────────────────────────────────
_TAVILY_KEY = os.environ.get("TAVILY_API_KEY", "")
if _TAVILY_KEY:
    tavily_search_tool = TavilySearchTool(
        api_key=_TAVILY_KEY,
        search_depth="advanced",
        max_results=5,
    )
else:
    # Clé absente — outil désactivé (évite le crash au démarrage)
    class _TavilyDisabled(BaseTool):
        name: str = "tavily_search"
        description: str = "Tavily désactivé — TAVILY_API_KEY manquante dans .env"
        def _run(self, query: str = "") -> str:
            return "ERREUR : TAVILY_API_KEY non configurée. Ajouter la clé dans .env"
    tavily_search_tool = _TavilyDisabled()

# ── Filesystem dynamique (un pair read/write par projet) ─────────────────────
def get_filesystem_tools(project_root: str):
    """Retourne (read_tool, write_tool) isolés sur project_root."""
    read_tool = FileReadTool(file_path=project_root)
    write_tool = SafeFileWriterTool()
    return read_tool, write_tool


# ── Whitelist des dossiers autorisés en écriture ─────────────────────────────
def _get_allowed_roots() -> list[str]:
    """Retourne les dossiers racines autorisés depuis les variables d'env."""
    roots = []
    for key in ["PROJECT_ROOT_FINDUP", "PROJECT_ROOT_TECHWATCH", "PROJECT_ROOT"]:
        val = os.environ.get(key, "").strip()
        if val:
            roots.append(os.path.abspath(val))
    return roots


def _is_path_allowed(directory: str) -> bool:
    """Vérifie que le dossier cible est dans une racine autorisée."""
    allowed_roots = _get_allowed_roots()
    if not allowed_roots:
        return True  # Pas de whitelist configurée → permissif (fallback)
    abs_dir = os.path.abspath(directory)
    return any(abs_dir.startswith(root) for root in allowed_roots)


class SafeFileWriterTool(BaseTool):
    """
    Wrapper autour de FileWriterTool avec :
    - Interception des appels sans 'content' (bug Haiku)
    - Whitelist de dossiers autorisés (empêche l'écriture hors projet)
    - Pydantic v2 compatible
    """
    name: str = "file_writer_tool"
    description: str = (
        "Écrit du contenu dans un fichier. "
        "Paramètres OBLIGATOIRES : filename (str), content (str). "
        "Paramètre optionnel : directory (str, défaut './'), overwrite (bool, défaut False). "
        "IMPORTANT : n'appelle jamais cet outil sans le paramètre 'content'. "
        "IMPORTANT : écrire uniquement dans les dossiers du projet configurés."
    )

    def _run(self, filename: str = "", directory: str = "./",
             overwrite: bool = True, content: str = None) -> str:

        # ── Vérif 1 : content présent ──
        if content is None or content == "":
            return (
                "ERREUR file_writer_tool : paramètre 'content' manquant ou vide.\n"
                "Tu dois appeler cet outil avec : filename, directory ET content dans le même appel.\n"
                "Exemple : file_writer_tool(filename='server.py', "
                "directory='/home/.../backend', content='<code ici>')"
            )

        # ── Vérif 2 : filename présent ──
        if not filename:
            return "ERREUR file_writer_tool : paramètre 'filename' manquant."

        # ── Vérif 3 : whitelist dossiers ──
        if not _is_path_allowed(directory):
            allowed = _get_allowed_roots()
            return (
                f"REFUSÉ file_writer_tool : écriture hors du projet interdite.\n"
                f"Dossier demandé : {os.path.abspath(directory)}\n"
                f"Dossiers autorisés : {', '.join(allowed)}\n"
                "Utilise uniquement les chemins définis dans PROJECT_ROOT_FINDUP / PROJECT_ROOT_TECHWATCH."
            )

        # ── Vérif 4 : pas de fichier sensible ──
        sensitive = [".env", "secrets", "private_key", "id_rsa", ".pem", ".key"]
        if any(s in filename.lower() for s in sensitive):
            return (
                f"REFUSÉ file_writer_tool : écriture de fichier sensible interdite : {filename}\n"
                "Les fichiers de secrets ne doivent jamais être modifiés par les agents."
            )

        try:
            writer = FileWriterTool()
            return writer._run(
                filename=filename,
                directory=directory,
                overwrite=overwrite,
                content=content,
            )
        except Exception as e:
            return f"ERREUR file_writer_tool : {e}"

# ── n8n HTML Cleaner ─────────────────────────────────────────────────────────
class N8nCleanerTool(BaseTool):
    name: str = "N8n HTML Cleaner"
    description: str = (
        "Nettoie du HTML brut en l'envoyant au webhook n8n du projet Techwatch. "
        "Input : string HTML. Output : HTML nettoyé prêt pour insertion en DB."
    )
    webhook_url: str = Field(default_factory=lambda: os.environ.get("N8N_CLEANER_WEBHOOK", ""))

    def _run(self, html_content: str) -> str:
        if not self.webhook_url:
            return "ERREUR : N8N_CLEANER_WEBHOOK non configuré"
        try:
            resp = requests.post(self.webhook_url, json={"html": html_content}, timeout=15)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as e:
            return f"ERREUR webhook n8n : {e}"

n8n_cleaner_tool = N8nCleanerTool()

# ── Pytest Runner ───────────────────────────────────────────────────────────────
class PytestRunnerTool(BaseTool):
    name: str = "Pytest Runner"
    description: str = (
        "Exécute pytest sur un fichier ou dossier de tests FindUP. "
        "Input : chemin absolu du fichier .py de tests (ex: /home/nolan/projets/FindUP/backend/tests/test_artisans.py). "
        "Output : sortie pytest complète avec PASSED/FAILED/ERROR et tracebacks."
    )
    python_path: str = Field(
        default_factory=lambda: os.environ.get("FINDUP_PYTHON", sys.executable)
    )

    def _run(self, test_path: str) -> str:
        """Éxécute pytest sur le chemin donné et retourne la sortie complète."""
        try:
            result = subprocess.run(
                [self.python_path, "-m", "pytest", test_path,
                 "-v", "--tb=short", "--no-header", "-q"],
                capture_output=True,
                text=True,
                timeout=120,
            )
            output = (result.stdout + result.stderr).strip()
            return output if output else "Aucune sortie pytest"
        except subprocess.TimeoutExpired:
            return "ERREUR : pytest dépassé 2 minutes (timeout)"
        except FileNotFoundError:
            return (
                f"ERREUR : interpréteur Python introuvable : {self.python_path}\n"
                "Configure FINDUP_PYTHON dans .env (ex: /home/nolan/projets/FindUP/venv/bin/python)"
            )
        except Exception as e:
            return f"ERREUR pytest : {e}"

pytest_runner_tool = PytestRunnerTool()

# ── RSS Feed Reader ───────────────────────────────────────────────────────────
RSS_FEEDS: dict[str, list[str]] = {
    "cyber": [
        "https://www.bleepingcomputer.com/feed/",
        "https://feeds.feedburner.com/TheHackersNews",
    ],
    "finance": [
        "https://feeds.finance.yahoo.com/rss/2.0/headline?s=^GSPC&region=US&lang=en-US",
        "https://www.zonebourse.com/rss/actualites.xml",
    ],
    "ia": [
        "https://www.anthropic.com/news/rss.xml",
        "https://huggingface.co/blog/feed.xml",
    ],
    "general": [
        "https://news.ycombinator.com/rss",
    ],
}


class RSSFeedTool(BaseTool):
    name: str = "RSS Feed Reader"
    description: str = (
        "Lit les flux RSS d'actualités selon une catégorie. "
        "Input : catégorie parmi 'cyber', 'finance', 'ia', 'general'. "
        "Output : 5 derniers articles (titre, résumé, URL, date) pour cette catégorie. "
        "Utilise pour compléter une recherche Tavily avec des actualités récentes."
    )

    def _run(self, category: str) -> str:
        try:
            import feedparser  # type: ignore
        except ImportError:
            return "ERREUR : feedparser non installé. Lancer : pip install feedparser"

        category = category.strip().lower()
        feeds = RSS_FEEDS.get(category, RSS_FEEDS["general"])
        articles: list[str] = []

        for feed_url in feeds:
            try:
                parsed = feedparser.parse(feed_url)
                for entry in parsed.entries[:3]:
                    title   = getattr(entry, "title",   "Sans titre")
                    link    = getattr(entry, "link",    "")
                    summary = getattr(entry, "summary", "")[:200].strip()
                    date    = getattr(entry, "published", getattr(entry, "updated", "date inconnue"))
                    articles.append(
                        f"**{title}**\n📅 {date}\n🔗 {link}\n{summary}\n"
                    )
                    if len(articles) >= 5:
                        break
            except Exception as e:
                articles.append(f"[Feed indisponible : {feed_url} — {e}]")
            if len(articles) >= 5:
                break

        if not articles:
            return f"Aucun article récupéré pour la catégorie '{category}'."

        header = f"### Flux RSS — {category.upper()} ({len(articles)} articles)\n\n"
        return header + "\n---\n".join(articles)


rss_feed_tool = RSSFeedTool()

