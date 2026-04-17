# Setup — Squad IA (local, 2 PC)

## Prérequis communs aux 2 machines
- Python 3.11+
- Git

---

## 1. Première installation (PC principal)

```bash
# Cloner ou créer le repo
git init squad_ia && cd squad_ia
# ... ou git clone git@github.com:toi/squad_ia.git

pip install -r requirements.txt

cp .env.example .env
# Remplir les 4 variables dans .env :
#   ANTHROPIC_API_KEY  → https://console.anthropic.com
#   TAVILY_API_KEY     → https://app.tavily.com (gratuit)
#   N8N_CLEANER_WEBHOOK → URL webhook n8n existant
#   PROJECT_ROOT       → chemin absolu vers findup/ ou techwatch/

streamlit run app.py
```

---

## 2. Deuxième PC

```bash
git clone git@github.com:toi/squad_ia.git
cd squad_ia
pip install -r requirements.txt

cp .env.example .env
# Remplir .env (mêmes clés API, PROJECT_ROOT adapté au chemin sur ce PC)

streamlit run app.py
```

> ⚠️ Ne jamais committer le fichier .env
> Le .gitignore doit contenir : .env

---

## 3. Synchronisation entre les 2 PC

Le code = Git (push/pull normal)
Les clés API = à remplir manuellement sur chaque machine (jamais dans Git)
PROJECT_ROOT = chemin local de chaque machine (différent sur chaque PC)

---

## Variables d'environnement

| Variable               | Où la récupérer                          |
|------------------------|------------------------------------------|
| ANTHROPIC_API_KEY      | console.anthropic.com → API Keys        |
| TAVILY_API_KEY         | app.tavily.com → Free tier (1000 req/mois) |
| N8N_CLEANER_WEBHOOK    | Ton instance n8n → Webhook URL          |
| PROJECT_ROOT           | Chemin absolu local (ex: /Users/nolan/findup) |

---

## Lancer l'interface

```bash
streamlit run app.py
# Ouvre automatiquement http://localhost:8501
```
