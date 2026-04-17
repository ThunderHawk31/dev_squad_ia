"""
run_history.py — Historique persistant des runs Squad IA
Sauvegarde chaque run dans runs_history.json (dossier squad)
"""

import json
import os
from datetime import datetime

HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "runs_history.json")

# Pricing Anthropic estimé (mix pondéré 2/9 Sonnet + 7/9 Haiku)
# Sonnet : $3/MTok input, $15/MTok output
# Haiku  : $0.80/MTok input, $4/MTok output
COST_PER_M_INPUT  = (2/9 * 3.0)  + (7/9 * 0.80)  # ~$1.29/MTok
COST_PER_M_OUTPUT = (2/9 * 15.0) + (7/9 * 4.0)   # ~$6.44/MTok


def estimate_cost(prompt_tokens: int, completion_tokens: int) -> float:
    """Estime le coût en $ d'un run selon le mix Sonnet/Haiku."""
    cost = (prompt_tokens / 1_000_000 * COST_PER_M_INPUT) + \
           (completion_tokens / 1_000_000 * COST_PER_M_OUTPUT)
    return round(cost, 4)


def save_run(
    run_type: str,
    project: str,
    instruction: str,
    result: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    files_modified: list = None,
) -> dict:
    """
    Sauvegarde un run dans l'historique JSON.

    Args:
        run_type: 'code' | 'research' | 'triage' | 'direct'
        project: nom du projet (FindUP, Techwatch, Autre)
        instruction: instruction ou query envoyée
        result: résultat complet du run
        prompt_tokens: tokens d'entrée consommés
        completion_tokens: tokens de sortie consommés
        total_tokens: total tokens
        files_modified: liste des chemins de fichiers modifiés

    Returns:
        Le run sauvegardé (dict)
    """
    history = load_history()
    cost = estimate_cost(prompt_tokens, completion_tokens)

    run = {
        "id": len(history) + 1,
        "timestamp": datetime.now().isoformat(),
        "type": run_type,
        "project": project,
        "instruction": instruction[:300],         # Tronquer si trop long
        "result_preview": result[:600],           # Aperçu du résultat
        "tokens": {
            "total": total_tokens,
            "prompt": prompt_tokens,
            "completion": completion_tokens,
        },
        "cost_usd": cost,
        "files_modified": files_modified or [],
    }

    history.append(run)
    _write_history(history)
    return run


def load_history() -> list:
    """Charge et retourne l'historique complet."""
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def clear_history() -> None:
    """Vide l'historique (supprime le fichier JSON)."""
    if os.path.exists(HISTORY_FILE):
        os.remove(HISTORY_FILE)


def _write_history(history: list) -> None:
    """Écrit l'historique dans le fichier JSON."""
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)
