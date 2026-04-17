"""
app.py — Interface Streamlit — 10 agents | 5 onglets
Pipeline Code en 2 phases : Analyse → Validation humaine → Écriture
"""

import os
import re
import subprocess
import requests as req_lib
import streamlit as st
from dotenv import load_dotenv
from crewai import Crew, Process, Task

from agents import make_agents
from tasks import (
    make_code_task_analysis, make_write_task,
    make_research_task, make_error_triage_task,
    make_claude_md_task,
)
from run_history import save_run, load_history, clear_history

load_dotenv()

PROJECT_ROOTS = {
    "FindUP":    os.environ.get("PROJECT_ROOT_FINDUP", "./"),
    "Techwatch": os.environ.get("PROJECT_ROOT_TECHWATCH", "./"),
    "Autre":     os.environ.get("PROJECT_ROOT", "./"),
}
RAILWAY_URL = os.environ.get("RAILWAY_URL", "https://alert-cat-production.up.railway.app")

st.set_page_config(page_title="Squad IA — Nolan", page_icon="🤖", layout="wide")
st.title("🤖 Squad IA")
st.caption("10 agents | CrewAI + Claude | FindUP & Techwatch")

# ── Init session_state (évite KeyError au premier chargement) ─────────────────
_SS_DEFAULTS = {
    "phase1_done":          False,
    "write_approved":       False,
    "analysis_result":      None,
    "analysis_tokens":      {},
    "security_task":        None,
    "security_context":     [],
    "backend_agent":        None,
    "analysis_project":     None,
    "analysis_root":        None,
    "analysis_instruction": None,
    "instruction_prefill":  "",
    "just_pushed":          False,
}
for _k, _v in _SS_DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v


# ── Helpers ──────────────────────────────────────────────────────────────────

def _extract_metrics(crew) -> dict:
    """
    Extrait les métriques de tokens d'un crew après kickoff.
    Essaie plusieurs noms d'attributs car CrewAI les change entre versions.
    """
    try:
        m = crew.usage_metrics
        if m is None:
            return {"total": 0, "prompt": 0, "completion": 0}

        # CrewAI >= 0.130 : UsageMetrics avec total_tokens
        total      = int(getattr(m, "total_tokens",            0) or 0)
        prompt     = int(getattr(m, "prompt_tokens",           0) or 0)
        completion = int(getattr(m, "completion_tokens",       0) or 0)

        # Fallback : certaines versions utilisent d'autres noms
        if total == 0:
            total      = int(getattr(m, "input_tokens",        0) or 0) +                          int(getattr(m, "output_tokens",       0) or 0)
            prompt     = int(getattr(m, "input_tokens",        0) or 0)
            completion = int(getattr(m, "output_tokens",       0) or 0)

        # Fallback 2 : accès dict si c'est un objet mappable
        if total == 0 and hasattr(m, "__dict__"):
            d = vars(m)
            prompt     = int(d.get("prompt_tokens",     d.get("input_tokens",  0)) or 0)
            completion = int(d.get("completion_tokens", d.get("output_tokens", 0)) or 0)
            total      = prompt + completion

        return {"total": total, "prompt": prompt, "completion": completion}
    except Exception:
        return {"total": 0, "prompt": 0, "completion": 0}


def _estimate_cost(tokens: dict) -> float:
    """Estime le coût $ (mix pondéré 2/10 Sonnet + 8/10 Haiku)."""
    cost_in  = tokens["prompt"]     / 1_000_000 * 1.29
    cost_out = tokens["completion"] / 1_000_000 * 6.44
    return round(cost_in + cost_out, 4)


def _git_diff(project_root: str) -> str:
    """Retourne git diff --stat depuis le dernier commit."""
    try:
        r = subprocess.run(
            ["git", "diff", "--stat", "HEAD"],
            cwd=project_root, capture_output=True, text=True, timeout=10
        )
        return r.stdout.strip() or "Aucune modification détectée par git."
    except Exception as e:
        return f"Git non disponible : {e}"


def _git_commit(project_root: str, message: str) -> str:
    """Commit toutes les modifications dans project_root."""
    try:
        subprocess.run(["git", "add", "-A"], cwd=project_root, check=True, timeout=10)
        r = subprocess.run(
            ["git", "commit", "-m", message],
            cwd=project_root, capture_output=True, text=True, timeout=10
        )
        return (r.stdout + r.stderr).strip()
    except Exception as e:
        return f"Erreur git commit : {e}"


def _git_push(project_root: str, branch: str = "main") -> str:
    """Push vers origin/branch. Retourne stdout+stderr."""
    try:
        r = subprocess.run(
            ["git", "push", "origin", branch],
            cwd=project_root, capture_output=True, text=True, timeout=30
        )
        return (r.stdout + r.stderr).strip() or f"Push origin/{branch} OK"
    except Exception as e:
        return f"Erreur git push : {e}"


def _git_status(project_root: str) -> str:
    """Retourne git status --short."""
    try:
        r = subprocess.run(
            ["git", "status", "--short"],
            cwd=project_root, capture_output=True, text=True, timeout=10
        )
        return r.stdout.strip() or "Rien à commiter."
    except Exception as e:
        return f"Git non disponible : {e}"


def _git_current_branch(project_root: str) -> str:
    """Retourne le nom de la branche courante."""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=project_root, capture_output=True, text=True, timeout=5
        )
        return r.stdout.strip() or "main"
    except Exception:
        return "main"


def _check_railway(url: str) -> dict:
    """Vérifie le statut HTTP du déploiement Railway."""
    try:
        resp = req_lib.get(url, timeout=10)
        return {"status": resp.status_code, "ok": resp.status_code < 400}
    except Exception as e:
        return {"status": 0, "ok": False, "error": str(e)}


def _show_cost_metrics(tokens: dict, cost: float):
    """Affiche les métriques tokens + coût en colonnes."""
    c1, c2, c3 = st.columns(3)
    c1.metric("Tokens total",  f"{tokens['total']:,}")
    c2.metric("Prompt / Output", f"{tokens['prompt']:,} / {tokens['completion']:,}")
    c3.metric("Coût estimé",  f"~${cost:.4f}")


def _extract_planned_files(result_str: str) -> list[str]:
    """
    Extrait les fichiers PRÉVUS depuis le rapport Phase 1 (plan du Manager).
    Utilisé dans la section de validation pour informer l'utilisateur
    avant qu'il clique sur Valider.
    """
    # Chemins absolus mentionnés dans le plan
    paths = re.findall(
        r'(/(?:home|var|tmp|usr)/[^\s<>()]+\.(?:py|jsx|tsx|js|ts|json|md|txt|yaml|yml|toml|cfg|ini|env))',
        result_str
    )
    # Dédupliquer en conservant l'ordre
    seen = set()
    unique = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique


def _parse_written_files(result_str: str) -> list[dict]:
    """
    Parse la sortie du write_task pour extraire les fichiers modifiés.
    Format attendu : FICHIER: /chemin/absolu/vers/fichier.py  (42 lignes)
    """
    files = []
    # Chercher le format strict "FICHIER: ..."
    strict = re.findall(
        r"FICHIER:\s*(/[^\s(]+)\s*\((\d+)\s*lignes?\)",
        result_str, re.IGNORECASE
    )
    for path, lines in strict:
        files.append({"path": path.strip(), "lines": int(lines), "source": "strict"})

    # Fallback : chemins absolus dans le texte si format strict absent
    if not files:
        abs_paths = re.findall(
            r"(/home/[^\s\"'<>]+\.(?:py|jsx|tsx|js|ts|json|md))",
            result_str
        )
        for path in list(dict.fromkeys(abs_paths)):  # dédupliqué, ordre conservé
            files.append({"path": path, "lines": None, "source": "fallback"})

    return files


def _preprocess_instruction(raw: str, project: str, claude_md_path: str) -> str:
    """
    Reformate une instruction floue/en bloc en instruction structurée pour les agents.
    Coût ~$0.005 avec Haiku. Retourne l'instruction améliorée.
    """
    try:
        import anthropic as _ant
        _client = _ant.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
        
        claude_md_hint = ""
        if os.path.exists(claude_md_path):
            with open(claude_md_path, encoding="utf-8", errors="ignore") as f:
                claude_md_hint = f.read()[:800]  # premiers 800 chars seulement
        
        system = (
            "Tu es un assistant qui reformate des instructions de développement floues "
            "en instructions claires et structurées pour des agents IA. "
            "Réponds UNIQUEMENT avec l'instruction reformatée, rien d'autre. "
            "Format de sortie :\n"
            "Tâche : [action précise]\n"
            "Fichier cible : [chemin absolu si connu]\n"
            "Contraintes : [ce qu'il ne faut pas toucher]\n"
            "Contexte utile : [info clé uniquement]"
        )
        
        prompt = (
            f"Projet : {project}\n"
            f"CLAUDE.md (extrait) : {claude_md_hint}\n\n"
            f"Instruction brute : {raw}\n\n"
            "Reformate cette instruction en gardant l'intention exacte. "
            "Si l'instruction est déjà claire et courte, retourne-la telle quelle."
        )
        
        resp = _client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
            system=system,
        )
        result = resp.content[0].text.strip()
        return result if result else raw
    except Exception:
        return raw  # fallback silencieux — retourne l'original si ça échoue


def _estimate_cost_before_launch(
    instruction: str,
    project_root: str,
    n_tasks: int,
    with_tests: bool,
    patch_mode: bool,
    past_runs: list,
) -> dict:
    """
    Estime le coût AVANT de lancer, basé sur :
    - Taille du CLAUDE.md × agents actifs
    - Longueur de l'instruction × tâches
    - Overhead fixe CrewAI par agent
    - Moyenne des runs historiques similaires
    Retourne un dict avec low/mid/high et la méthode utilisée.
    """
    # ── Méthode 1 : historique ──
    similar = [r for r in past_runs if r.get("type") == "code"]
    # Filtrer par mode patch si possible
    if patch_mode:
        patch_runs = [r for r in similar if r.get("tokens", {}).get("total", 0) < 150_000]
        if patch_runs:
            similar = patch_runs

    if similar:
        costs = [r.get("cost_usd", 0) for r in similar[-5:]]
        avg   = sum(costs) / len(costs)
        # Ajuster selon le nombre de tâches (base = 5 tâches)
        base_tasks = 5
        ratio = n_tasks / base_tasks
        mid   = round(avg * ratio, 4)
        low   = round(mid * 0.6, 4)
        high  = round(mid * 1.8, 4)
        method = f"historique ({len(similar)} runs)"
        return {"low": low, "mid": mid, "high": high, "method": method}

    # ── Méthode 2 : estimation analytique ──
    # Tokens input estimés
    claude_md_path = os.path.join(project_root, "CLAUDE.md")
    claude_md_size = 0
    if os.path.exists(claude_md_path):
        claude_md_size = sum(1 for _ in open(claude_md_path, errors="ignore"))

    n_agents = 2 + (1 if not patch_mode else 0)  # manager + backend + sécurité optionnelle
    if with_tests:
        n_agents += 2  # tester + build fixer

    # Chaque agent reçoit CLAUDE.md (~3 tokens/ligne) + instruction (~1 token/mot)
    tokens_per_agent_input = claude_md_size * 3 + len(instruction.split()) * 4
    overhead_per_agent     = 2_000  # overhead CrewAI par agent
    total_input  = (tokens_per_agent_input + overhead_per_agent) * n_agents * n_tasks
    total_output = 800 * n_tasks  # ~800 tokens de réponse par tâche

    # Coût mix Sonnet/Haiku
    cost_input  = total_input  / 1_000_000 * 1.29
    cost_output = total_output / 1_000_000 * 6.44
    mid  = round(cost_input + cost_output, 4)
    low  = round(mid * 0.5, 4)
    high = round(mid * 2.5, 4)  # large marge car estimation approximative
    method = "analytique (pas d'historique)"
    return {"low": low, "mid": mid, "high": high, "method": method}


def _generate_pdf_report(
    instruction: str,
    project: str,
    result_str: str,
    files_written: list,
    tokens: dict,
    cost: float,
) -> bytes:
    """
    Génère un rapport PDF structuré depuis le résultat Phase 1 + Phase 2.
    Retourne les bytes du PDF.
    Utilise uniquement la stdlib + reportlab si disponible, sinon markdown brut.
    """
    from datetime import datetime as _dt

    # ── Tentative avec reportlab ──
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.lib.colors import HexColor, black, white, red, orange, green, gray
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
            HRFlowable, KeepTogether
        )
        from reportlab.lib.enums import TA_LEFT, TA_CENTER
        import io as _io, re as _re

        buf = _io.BytesIO()
        doc = SimpleDocTemplate(
            buf, pagesize=A4,
            leftMargin=2*cm, rightMargin=2*cm,
            topMargin=2*cm, bottomMargin=2*cm,
        )

        styles = getSampleStyleSheet()
        # Custom styles
        title_style = ParagraphStyle("Title2",
            fontSize=18, fontName="Helvetica-Bold",
            textColor=HexColor("#07101F"), spaceAfter=6,
        )
        h1_style = ParagraphStyle("H1",
            fontSize=13, fontName="Helvetica-Bold",
            textColor=HexColor("#2563EB"), spaceBefore=12, spaceAfter=4,
        )
        h2_style = ParagraphStyle("H2",
            fontSize=11, fontName="Helvetica-Bold",
            textColor=HexColor("#07101F"), spaceBefore=8, spaceAfter=3,
        )
        body_style = ParagraphStyle("Body2",
            fontSize=9, fontName="Helvetica",
            textColor=black, leading=13, spaceAfter=4,
        )
        code_style = ParagraphStyle("Code2",
            fontSize=8, fontName="Courier",
            textColor=HexColor("#333333"), backColor=HexColor("#F5F5F5"),
            leading=11, spaceAfter=4, leftIndent=10,
        )
        meta_style = ParagraphStyle("Meta",
            fontSize=8, fontName="Helvetica",
            textColor=HexColor("#666666"), spaceAfter=2,
        )

        story = []

        # ── Header ──
        story.append(Paragraph("🤖 Squad IA — Rapport de run", title_style))
        story.append(Paragraph(
            f"Projet : <b>{project}</b> &nbsp;|&nbsp; "
            f"Date : <b>{_dt.now().strftime('%d/%m/%Y %H:%M')}</b>",
            meta_style
        ))
        story.append(HRFlowable(width="100%", thickness=2,
                                color=HexColor("#2563EB"), spaceAfter=8))

        # ── Résumé exécutif ──
        story.append(Paragraph("📋 Résumé exécutif", h1_style))

        # Compter CRITIQUE / MOYEN / INFO dans le rapport
        crit  = len(_re.findall(r"CRITIQUE|critique|critical", result_str, _re.I))
        moyen = len(_re.findall(r"MOYEN|moyen|medium|warning", result_str, _re.I))
        info  = len(_re.findall(r"INFO|info", result_str, _re.I))

        summary_data = [
            ["Métrique", "Valeur"],
            ["Instruction", instruction[:80] + ("…" if len(instruction) > 80 else "")],
            ["Fichiers modifiés", str(len(files_written))],
            ["Tokens consommés", f"{tokens.get('total', 0):,}"],
            ["Coût estimé", f"~${cost:.4f}"],
            ["Findings CRITIQUE", str(crit)],
            ["Findings MOYEN", str(moyen)],
            ["Findings INFO", str(info)],
        ]
        tbl = Table(summary_data, colWidths=[5*cm, 12*cm])
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), HexColor("#2563EB")),
            ("TEXTCOLOR",  (0,0), (-1,0), white),
            ("FONTNAME",   (0,0), (-1,0), "Helvetica-Bold"),
            ("FONTSIZE",   (0,0), (-1,-1), 9),
            ("BACKGROUND", (0,1), (-1,-1), HexColor("#F8F9FA")),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [white, HexColor("#F0F4FF")]),
            ("GRID",       (0,0), (-1,-1), 0.5, HexColor("#CCCCCC")),
            ("VALIGN",     (0,0), (-1,-1), "MIDDLE"),
            ("TOPPADDING", (0,0), (-1,-1), 5),
            ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ]))
        story.append(tbl)
        story.append(Spacer(1, 0.4*cm))

        # ── Décision rapide ──
        if crit > 0:
            verdict_color = HexColor("#DC2626")
            verdict_text  = f"❌ REFUSER — {crit} finding(s) CRITIQUE(S) détecté(s)"
        elif moyen > 0:
            verdict_color = HexColor("#D97706")
            verdict_text  = f"⚠️ VALIDER AVEC PRÉCAUTION — {moyen} finding(s) MOYEN"
        else:
            verdict_color = HexColor("#16A34A")
            verdict_text  = "✅ VALIDER — Aucun finding critique"

        verdict_style = ParagraphStyle("Verdict",
            fontSize=11, fontName="Helvetica-Bold",
            textColor=white, backColor=verdict_color,
            spaceBefore=4, spaceAfter=8,
            leftIndent=8, rightIndent=8,
            borderPadding=(6, 8, 6, 8),
        )
        story.append(Paragraph(verdict_text, verdict_style))

        # ── Fichiers modifiés ──
        if files_written:
            story.append(Paragraph("📁 Fichiers modifiés", h1_style))
            for fp in files_written:
                ext   = fp.rsplit(".", 1)[-1] if "." in fp else ""
                icons = {"py": "🐍", "js": "🟨", "jsx": "⚛️", "ts": "🔷",
                         "tsx": "⚛️", "json": "📋", "md": "📝"}
                ico   = icons.get(ext, "📄")
                story.append(Paragraph(f"{ico} <font name='Courier'>{fp}</font>", body_style))

        # ── Rapport complet (nettoyé) ──
        story.append(Paragraph("📊 Rapport complet", h1_style))
        story.append(HRFlowable(width="100%", thickness=1,
                                color=HexColor("#CCCCCC"), spaceAfter=4))

        # Nettoyer le markdown pour reportlab
        clean = result_str
        clean = _re.sub(r"```[a-z]*[\n]?", "", clean)
        clean = _re.sub(r"```", "", clean)
        clean = _re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", clean)
        clean = _re.sub(r"\*(.+?)\*", r"<i>\1</i>", clean)
        clean = _re.sub(r"#{1,3} (.+)", r"<b>\1</b>", clean)

        for line in clean.split("\n"):
            line = line.strip()
            if not line:
                story.append(Spacer(1, 0.1*cm))
                continue
            # Détecter les lignes CRITIQUE/MOYEN/INFO
            if "CRITIQUE" in line.upper():
                s = ParagraphStyle("Crit", parent=body_style,
                    textColor=HexColor("#DC2626"), fontName="Helvetica-Bold")
            elif "MOYEN" in line.upper():
                s = ParagraphStyle("Moyen", parent=body_style,
                    textColor=HexColor("#D97706"), fontName="Helvetica-Bold")
            elif line.startswith("INFO") or "✅" in line:
                s = ParagraphStyle("Info", parent=body_style,
                    textColor=HexColor("#16A34A"))
            else:
                s = body_style
            try:
                story.append(Paragraph(line[:500], s))
            except Exception:
                story.append(Paragraph(line[:500].replace("<", "&lt;").replace(">", "&gt;"), body_style))

        # ── Footer ──
        story.append(Spacer(1, 0.5*cm))
        story.append(HRFlowable(width="100%", thickness=1,
                                color=HexColor("#CCCCCC")))
        story.append(Paragraph(
            f"Squad IA — généré le {_dt.now().strftime('%d/%m/%Y à %H:%M')} "
            f"| Tokens : {tokens.get('total',0):,} | Coût : ~${cost:.4f}",
            meta_style
        ))

        doc.build(story)
        return buf.getvalue()

    except ImportError:
        # ── Fallback : PDF minimal en texte brut via bytes ──
        lines = [
            f"SQUAD IA — RAPPORT DE RUN",
            f"Projet : {project}",
            f"Date : {_dt.now().strftime('%d/%m/%Y %H:%M')}",
            f"Instruction : {instruction[:200]}",
            f"Tokens : {tokens.get('total',0):,} | Coût : ~${cost:.4f}",
            "",
            "RAPPORT :",
            result_str[:5000],
        ]
        # Retourner en bytes UTF-8 — pas un vrai PDF mais téléchargeable
        return "\n".join(lines).encode("utf-8")


def _show_files_report(files: list[dict]):
    """Affiche le rapport des fichiers modifiés avec aperçu du contenu."""
    if not files:
        st.info("Aucun fichier détecté dans la réponse. Vérifier la sortie ci-dessus.")
        return

    st.markdown(f"### 📁 Fichiers modifiés ({len(files)})")

    for f in files:
        path = f["path"]
        lines_label = f"  ({f['lines']} lignes)" if f["lines"] else ""
        ext = path.rsplit(".", 1)[-1] if "." in path else "text"
        lang_map = {
            "py": "python", "js": "javascript", "jsx": "jsx",
            "ts": "typescript", "tsx": "tsx", "json": "json", "md": "markdown"
        }
        icon = {"py": "🐍", "js": "🟨", "jsx": "⚛️", "tsx": "⚛️",
                "ts": "🔷", "json": "📋", "md": "📝"}.get(ext, "📄")

        exists = os.path.exists(path)
        status = "✅" if exists else "⚠️ introuvable"

        with st.expander(f"{icon} `{path}`{lines_label}  {status}", expanded=False):
            if exists:
                try:
                    with open(path, encoding="utf-8", errors="ignore") as fh:
                        content = fh.read()
                    actual_lines = content.count("\n") + 1
                    st.caption(f"{actual_lines} lignes — {len(content)} caractères")
                    st.code(content, language=lang_map.get(ext, "text"))
                except Exception as e:
                    st.error(f"Erreur lecture : {e}")
            else:
                st.warning(f"Fichier non trouvé sur le système : `{path}`")

    return [f["path"] for f in files]


# ── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Agents")
    agents_info = [
        ("Chef d'Orchestre", "🧠", "Sonnet", "Planification"),
        ("Back-end",         "⚡", "Haiku",  "Implémentation"),
        ("Front-end",        "⚡", "Haiku",  "UI/React"),
        ("Testeur",          "⚡", "Haiku",  "Tests + pytest"),
        ("Build Fixer",      "⚡", "Haiku",  "Auto-correction"),
        ("Sécurité",         "🧠", "Sonnet", "Audit Antigravity"),
        ("Error Triage",     "⚡", "Haiku",  "Dispatch erreurs"),
        ("Cleaner n8n",      "⚡", "Haiku",  "HTML Techwatch"),
        ("Performance",      "⚡", "Haiku",  "N+1, bundle, CWV"),
        ("Chercheur Web",    "⚡", "Haiku",  "Recherche Tavily"),
    ]
    for name, icon, model, role in agents_info:
        st.write(f"{icon} **{name}** `{model}` — *{role}*")

    st.divider()
    st.header("Projets")
    for name, path in PROJECT_ROOTS.items():
        exists = os.path.exists(path)
        claude_md_path = os.path.join(path, "CLAUDE.md")
        has_claude_md = os.path.exists(claude_md_path)
        if has_claude_md:
            with open(claude_md_path, encoding="utf-8", errors="ignore") as _f:
                line_count = sum(1 for _ in _f)
            lines_label = f"`{line_count} lignes` {'✅' if line_count <= 150 else '⚠️ >150 (tokens fantômes)'}"
        else:
            lines_label = ""
        st.write(
            f"{'✅' if exists else '❌'}"
            f"{'📋' if has_claude_md else '⚠️'} "
            f"**{name}** {lines_label}"
        )

    st.divider()
    env_ok = all([os.environ.get("ANTHROPIC_API_KEY"), os.environ.get("TAVILY_API_KEY")])
    if env_ok:
        st.success("✅ Env OK")
    else:
        st.error("❌ Clés manquantes")


# ── Tabs ──────────────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs([
    "💻 Tâche Code",
    "🔍 Recherche Web",
    "🚨 Error Triage",
    "📜 Historique",
    "📝 CLAUDE.md",
    "💬 Agent Direct",
    "🚀 Déployer",
    "🧠 AutoAgent",
])


# ── Tab 1 : Code (pipeline 2 phases) ─────────────────────────────────────────
with tab1:
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
with tab2:
    st.subheader("Recherche avec triangulation des sources")
    st.caption("CONFIRMÉ (3+ sources) | PARTIEL (2 sources) | NON VÉRIFIÉ (1 source)")
    st.caption("🔍 Agent Chercheur Web dédié — accès Tavily uniquement, pas de filesystem")

    query = st.text_input(
        "Requête",
        placeholder="Ex: FastAPI JWT refresh token best practices 2025"
    )

    if st.button("🔍 Rechercher", type="primary", disabled=not query):
        (_, _, _, _, _, _, _, _, _, researcher) = make_agents("./")
        tasks = make_research_task(query, researcher)
        crew = Crew(agents=[researcher], tasks=tasks, process=Process.sequential, verbose=True, memory=False, respect_context_window=True)


        with st.spinner("Recherche en cours..."):
            result = crew.kickoff()

        st.success("✅ Terminé")
        tokens = _extract_metrics(crew)
        cost   = _estimate_cost(tokens)
        _show_cost_metrics(tokens, cost)

        st.markdown("### Synthèse")
        result_str = str(result)
        st.markdown(result_str)

        save_run(
            run_type="research",
            project="Web",
            instruction=query,
            result=result_str,
            prompt_tokens=tokens["prompt"],
            completion_tokens=tokens["completion"],
            total_tokens=tokens["total"],
        )


# ── Tab 3 : Error Triage ─────────────────────────────────────────────────────
with tab3:
    st.subheader("🚨 Triage automatique d'erreur")
    st.caption("Error Triage analyse → Build Fixer corrige")

    project_err = st.selectbox("Projet", list(PROJECT_ROOTS.keys()), key="err_proj")
    project_root_err = PROJECT_ROOTS[project_err]

    error_desc = st.text_area(
        "Description de l'erreur",
        placeholder=(
            "Ex: 502 Bad Gateway sur /api/artisans après déploiement Railway.\n"
            "Logs : CORSMiddleware conflict on OPTIONS request."
        ),
        height=120,
    )

    if st.button("🔍 Analyser", type="primary", disabled=not error_desc):
        (manager, backend, frontend,
         tester, build_fixer,
         security, error_triage, cleaner,
         performance, researcher) = make_agents(project_root_err)

        tasks = make_error_triage_task(error_desc, error_triage, backend, build_fixer)

        crew = Crew(
            agents=[error_triage, build_fixer],
            tasks=tasks,
            process=Process.sequential,
            verbose=True,
            memory=False,
            respect_context_window=True,
        )

        with st.spinner("Analyse en cours..."):
            result = crew.kickoff()

        st.success("✅ Analyse terminée")
        tokens = _extract_metrics(crew)
        cost   = _estimate_cost(tokens)
        _show_cost_metrics(tokens, cost)

        result_str = str(result)
        st.markdown("### Rapport de triage")
        st.markdown(result_str)

        # Fichiers modifiés si le Build Fixer a écrit quelque chose
        files_data = _parse_written_files(result_str)
        if files_data:
            _show_files_report(files_data)

        save_run(
            run_type="triage",
            project=project_err,
            instruction=error_desc,
            result=result_str,
            prompt_tokens=tokens["prompt"],
            completion_tokens=tokens["completion"],
            total_tokens=tokens["total"],
        )


# ── Tab 4 : Historique ────────────────────────────────────────────────────────
with tab4:
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
with tab5:
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
with tab6:

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
with tab7:
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
with tab8:
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
