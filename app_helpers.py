"""
app_helpers.py — Fonctions utilitaires partagées entre les onglets.

Importé par chaque tab_*.py et par app.py.
"""
import os
import re
import subprocess
import requests as req_lib
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOTS = {
    "FindUP":    os.environ.get("PROJECT_ROOT_FINDUP", "./"),
    "Techwatch": os.environ.get("PROJECT_ROOT_TECHWATCH", "./"),
    "Autre":     os.environ.get("PROJECT_ROOT", "./"),
}
RAILWAY_URL = os.environ.get("RAILWAY_URL", "https://alert-cat-production.up.railway.app")



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
