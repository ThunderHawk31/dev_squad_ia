# 🤖 Dev Squad AI

**Pipeline multi-agents local pour automatiser le développement — CrewAI + Claude**

> 10 agents spécialisés · 8 onglets Streamlit · Validation humaine · $0.08–0.20 par tâche

---

## Présentation

Dev Squad AI est un système d'agents IA local qui sert d'équipe de développement autonome. Il planifie, code, teste, audite la sécurité et écrit les fichiers — tout en gardant l'humain dans la boucle avant chaque écriture.

Conçu pour des projets FastAPI + React (testé sur [FindUP](https://github.com/ThunderHawk31/FindUP)), il est adaptable à n'importe quel projet Python/JS.

---

## Démonstration

```
Instruction : "Corrige la faille B2 : l'endpoint GET /api/artisans n'a pas de limite de pagination"

Timeline :
  ⏳ Chef d'Orchestre → 🔄 Développeur Back-end → ⏳ Auditeur Sécurité

  ✅ Chef d'Orchestre  → Plan avec lignes exactes (get_artisans:254)
  ✅ Développeur Back-end → Patch ciblé 8 lignes via read_file_lines
  ✅ Auditeur Sécurité  → Aucun finding critique

  📁 Fichiers prévus : server.py ✅ existe
  🔒 Validation humaine → [Valider] [Annuler]

  ✅ Écriture → server.py modifié (patch TYPE A, pas réécriture)
  🔙 Rollback disponible si besoin

Coût : ~$0.08 | Tokens : 45,000 | Durée : ~2 min
```

---

## Architecture

### 10 agents spécialisés

| Agent | Modèle | Rôle | Outils |
|---|---|---|---|
| Chef d'Orchestre | Sonnet | Planification avec index fonctions | — |
| Développeur Back-end | Haiku | FastAPI, lecture chirurgicale par lignes | read, read_lines, write |
| Développeur Front-end | Haiku | React/Vite, design system | read, read_lines, write |
| Testeur | Sonnet | Tests pytest réels + rapport Build Fixer | read, read_lines, write, pytest |
| Build Fixer | Haiku | Corrections avec State Logger anti-boucle | read, read_lines, write |
| Auditeur Sécurité | Sonnet | Posture offensive hacker — diff-only | read, tavily |
| Error Triage | Haiku | Dispatch erreurs | read, tavily |
| Nettoyeur HTML | Haiku | Webhook n8n Techwatch | n8n |
| Analyste Performance | Haiku | N+1, bundle, Core Web Vitals | read, tavily |
| Chercheur Web | Haiku | Tavily 3 passes + RSS + filtre anti-contamination | tavily, rss |

### Pipeline Code — 2 phases

```
Phase 1 (analyse, sans écriture) :
  Manager → Backend → [Frontend] → [Tester → BuildFixer] → [Performance] → Sécurité

                    ↓ Timeline live + rapport + fichiers prévus + seuil de risque

  🔒 Validation humaine obligatoire
     → CRITIQUE détecté : bouton Valider bloqué automatiquement
     → Zone sensible (auth, supabase...) : warning orange

Phase 2 (après validation) :
  Write Agent (Sonnet) → écriture TYPE A/B/C (patch / nouveau / refacto)
  → Rollback one-click disponible par fichier ou total
```

### Optimisations coût

- **Mode patch** — skip agent Sécurité pour les petits fixes (~$0.08/run)
- **Mode simulation** — analyse complète sans écriture, pour évaluer le risque
- **Frontend optionnel** — décocher si tâche purement back-end (-30% tokens)
- **`read_file_lines`** — lecture chirurgicale lignes X→Y (max 150), jamais le fichier entier
- **Index fonctions** — scan `ast` → `get_artisans:254` injecté dans le plan du Manager
- **Whitelist écriture** — agents limités aux dossiers projet configurés
- **`respect_context_window=True`** — résumé automatique si contexte déborde

---

## Interface Streamlit — 8 onglets

| Onglet | Fonction |
|---|---|
| 💻 Tâche Code | Pipeline 2 phases, timeline live, mode simulation, seuil de risque, rollback |
| 🔍 Recherche Web | Tavily 3 passes, triangulation CONFIRMÉ/PARTIEL/UNCONFIRMED/CONFLICT, RSS |
| 🚨 Error Triage | Analyse + fix automatique |
| 📜 Historique | Graphes coût par run + cumulé, replay, export CSV |
| 📝 CLAUDE.md | Éditeur + générateur automatique + aperçu index fonctions |
| 💬 Agent Direct | Un agent, une question, ~$0.02 |
| 🚀 Déployer | Git status/diff/commit/push + Railway health check |
| 🧠 AutoAgent | Analyse les runs, propose des améliorations de prompts, `optimizations.log` |

---

## Installation

### Prérequis

- Python 3.12+
- WSL2 Ubuntu (Windows) ou Linux/macOS
- Clé API Anthropic
- Clé API Tavily (gratuit — 1000 req/mois)

### Setup

```bash
# 1. Cloner le repo
git clone https://github.com/ThunderHawk31/dev_squad_ia.git
cd dev_squad_ia

# 2. Créer le venv
python3 -m venv venv
source venv/bin/activate

# 3. Installer les dépendances
pip install -r requirements.txt

# 4. Configurer les variables d'environnement
cp .env.example .env
nano .env  # remplir les clés

# 5. Lancer l'interface
streamlit run app.py
```

### Variables d'environnement

```env
# Obligatoires
ANTHROPIC_API_KEY=sk-ant-...
TAVILY_API_KEY=tvly-...

# Projets (chemins absolus vers les racines)
PROJECT_ROOT_FINDUP=/home/user/projets/FindUP/backend
PROJECT_ROOT_TECHWATCH=/home/user/projets/techwatch

# Optionnel
RAILWAY_URL=https://votre-app.up.railway.app
FINDUP_PYTHON=/home/user/projets/FindUP/venv/bin/python
N8N_CLEANER_WEBHOOK=https://...
CREWAI_TOOLS_ALLOW_UNSAFE_PATHS=true
```

---

## Sécurité

- **Whitelist écriture** — agents limités aux dossiers `PROJECT_ROOT_*`
- **Fichiers sensibles protégés** — `.env`, `.key`, `.pem` refusés automatiquement
- **Validation humaine** — aucun fichier écrit sans approbation explicite
- **Seuil de risque automatique** — bouton Valider bloqué si finding CRITIQUE détecté
- **Zones sensibles** — warning orange si `auth`, `supabase`, `secrets` touchés
- **Rollback one-click** — `git checkout HEAD -- <fichier>` depuis l'UI

---

## Fonctionnalités avancées

### 🔍 Mode simulation (dry run)
L'agent analyse et produit le rapport complet sans écrire aucun fichier. Idéal pour évaluer le risque et le coût avant de s'engager.

### 🔙 Rollback one-click
Après chaque écriture, selectbox pour choisir un fichier spécifique à restaurer ou rollback total de tous les fichiers modifiés. Double confirmation obligatoire pour le rollback total.

### 🗂️ Timeline live des agents
Barre d'état `⏳ → 🔄 → ✅` pour chaque agent en temps réel pendant l'exécution.

### 🔒 Seuil de risque automatique
Détection automatique des findings CRITIQUE (bouton bloqué) et des zones sensibles comme `auth`, `supabase`, `server.py` (warning orange).

### ⚔️ Hacker prompt (agent Sécurité)
Au lieu de demander "est-ce safe ?", l'agent se demande "comment je casse ça ?" — 3 vecteurs d'attaque analysés sur chaque modification. Diff-only : analyse uniquement les lignes `+` du git diff.

### 🔁 State Logger anti-boucle
Le Build Fixer détecte si le même traceback réapparaît après un fix → arrêt immédiat avec rapport. Évite les boucles coûteuses ($2 → $0.20).

### 📐 `read_file_lines` — lecture chirurgicale
Outil dédié : lit uniquement les lignes X à Y (max 150) avec numéros de lignes style IDE. Réduit ~90% des tokens de lecture sur les gros fichiers. Protocole 3 niveaux : ciblé → remontée caller → imports seulement.

### 📊 Index fonctions
Scan `ast` des fichiers Python → index compact `get_artisans:254 | post_artisan:280 | ...` injecté dans le plan du Manager. L'agent Back-end sait exactement où aller.

### 🌐 Filtre anti-contamination (Recherche Web)
Sources antérieures à 2024 → `UNCONFIRMED`. Sources contradictoires → `CONFLICT` avec décision humaine requise. Évite qu'une doc obsolète pollue les recommandations de code.

### 🧠 AutoAgent (méta-optimisation)
Analyse les N derniers runs, identifie les patterns d'erreurs et les runs coûteux, propose des améliorations AVANT/APRÈS sur les prompts et instructions. Sauvegarde tout dans `optimizations.log`. Export PDF du rapport d'optimisation.

---

## Coûts estimés

| Type de tâche | Config | Coût estimé |
|---|---|---|
| Correction faille simple | Mode patch, sans testeur | ~$0.08 |
| Vérification rapide | Agent Direct | ~$0.02 |
| Nouveau endpoint | Avec sécurité | ~$0.15–0.25 |
| Endpoint complexe + tests | Pipeline complet | ~$0.40–0.60 |
| Recherche web (3 passes) | Researcher seul | ~$0.03–0.05 |
| Analyse AutoAgent | 10 derniers runs | ~$0.05–0.10 |

*Mix pondéré Sonnet/Haiku : ~$1.29/MTok input, ~$6.44/MTok output*

---

## Stack technique

- **Agents** : [CrewAI](https://github.com/crewAIInc/crewAI) ≥ 0.130.0
- **LLMs** : `claude-sonnet-4-20250514` + `claude-haiku-4-5-20251001`
- **Interface** : [Streamlit](https://streamlit.io) ≥ 1.45.0
- **Recherche** : [Tavily](https://tavily.com) + RSS (feedparser)
- **PDF** : reportlab ≥ 4.0
- **Mémoire** : JSON local (`runs_history.json` + `optimizations.log`)

---

## Structure du projet

```
dev_squad_ia/
├── app.py            # Point d'entrée Streamlit (130L) — config + sidebar + render()
├── app_helpers.py    # Helpers partagés entre onglets (git, coût, PDF, etc.)
├── agents.py         # 10 agents avec routing Sonnet/Haiku
├── tasks.py          # Pipelines, tâches, index fonctions
├── tools.py          # SafeFileWriterTool, ReadFileLinesTools, PytestRunner, RSS, n8n
├── prompts.py        # Backstories et goals des agents centralisés
├── run_history.py    # Historique JSON persistant
├── optimizations.log # Journal AutoAgent (créé au premier run)
├── requirements.txt  # Versions épinglées
├── .env.example
├── SETUP.md          # Guide d'installation détaillé
└── tabs/             # Un fichier par onglet Streamlit
    ├── tab_code.py          # 💻 Tâche Code (pipeline 2 phases)
    ├── tab_recherche.py     # 🔍 Recherche Web
    ├── tab_error_triage.py  # 🚨 Error Triage
    ├── tab_historique.py    # 📜 Historique
    ├── tab_claude_md.py     # 📝 CLAUDE.md
    ├── tab_agent_direct.py  # 💬 Agent Direct
    ├── tab_deployer.py      # 🚀 Déployer
    └── tab_autoagent.py     # 🧠 AutoAgent
```

> **Maintenabilité** : modifier un onglet → ouvrir `tabs/tab_*.py`. Modifier un prompt → ouvrir `prompts.py`. Modifier un helper → ouvrir `app_helpers.py`. Les versions sont épinglées dans `requirements.txt`.

---

## Cas d'usage testé

Développé et testé sur **FindUP** (marketplace artisans locaux — FastAPI + React + Supabase) :

- 6 failles de sécurité (audit Antigravity) corrigées automatiquement
- Coût total : ~$0.60 pour les 6 corrections
- Zéro réécriture accidentelle de fichier après ajout des gardes-fous

---

## Licence

MIT — libre d'utilisation, de modification et de distribution.

---