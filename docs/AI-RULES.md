# Règles de l'équipe — TimeProof (Junction 2026, équipe ENLMe)

Ces règles s'appliquent à **tous** les membres de l'équipe et à leurs assistants IA.
**Pour que votre assistant IA les lise automatiquement** : dans le fichier d'instructions **local** de votre assistant, à la racine du dépôt, ajoutez une ligne qui importe ce fichier (`@docs/AI-RULES.md`). Ce fichier local **ne doit jamais être committé** : ajoutez son nom dans `.git/info/exclude` (fichier d'exclusion personnel, non versionné).

## Le projet en 3 lignes

TimeProof montre qui réécrit l'histoire sur Wikipédia, quand et comment, et ne publie que ce qu'il peut prouver.
Données : 862 076 versions de 19 742 articles de Wikipédia finnoise sur l'histoire de la Finlande (2003 → 1er octobre 2026), fournies par MariaDB.
Hackathon de 48 h : **soumission finale dimanche 15/11 avant 9h30, heure d'Helsinki** (limite 10h).

## À lire avant de coder (dans cet ordre)

1. `docs/TIMEPROOF-RESUME.md` : l'idée, le périmètre, qui fait quoi.
2. `docs/TIMEPROOF-PLAN-SAMEDI.md` : le plan heure par heure, Git, le contrat entre modules (formats JSONL).
3. `docs/TECH.md` : la pile technique, le schéma de la base, les colonnes des données, des exemples d'appels qui marchent, les algorithmes et les pièges.

**Si une information manque dans ces documents, demande à l'humain plutôt que d'inventer** (nom de modèle, adresse, format, chemin).

## Qui possède quoi (ne modifie que ton dossier)

| Personne | Branche | Dossiers |
|---|---|---|
| Léopold (propriétaire du dépôt, fusionne dans `main`) | `feat/server` | `server/`, `db/`, `docker-compose.yml`, `.gitignore`, `.env.example` |
| Maël | `feat/analysis` | `analysis/` |
| Nathanaël | `feat/decision` | `decision/` |
| Eléa | `feat/web` | `web/`, `lens/`, `.github/` |

Les autres échangent par **fichiers JSONL dans `data/exchange/`** (formats : plan, section 4). Ne change jamais un format sans prévenir l'équipe.

## Règles Git (impératives)

- **Ne jamais travailler ni pousser directement sur `main`.** Travaille sur ta branche, puis ouvre une Pull Request ; Léopold fusionne aux rendez-vous (13h30, 17h, 21h, 1h).
- **`git add <ton_dossier>/` uniquement.** Jamais `git add .` ni `git add -A` : le dossier `data/` (fichiers de plusieurs centaines de Mo) et les clés ne doivent jamais être committés.
- **Jamais `--force`**, jamais de réécriture de l'historique partagé.
- **Aucune mention d'IA dans les commits, les Pull Requests ni les fichiers du dépôt** : pas de ligne `Co-Authored-By` ajoutée par un assistant, pas de signature « Generated with … », pas de nom d'outil d'IA. Message de commit simple, au format `dossier: ce qui change` (ex. `analysis: detect caption changes`).
- **Pas de push sans que l'humain l'ait demandé.**

## Règles de code

- **Python 3.12**, code et commentaires **en anglais** ; on répond à l'équipe **en français**.
- Bibliothèques autorisées : `pyarrow`, `httpx`, `PyMySQL`, `fastapi`, `uvicorn`. Toute autre dépendance : demande d'abord.
- Le site (`web/`) : **HTML + CSS + JavaScript simples, sans framework ni étape de build**. Textes visibles **en anglais**.
- **Tout appel externe** (Nemotron, Gemini, Wikimedia) passe par **une seule fonction** avec un mode simulé (`USE_MOCK=true`) qui renvoie des données réalistes au bon format.
- **Écris les résultats ligne par ligne** dans les JSONL au fur et à mesure : si un script plante, on ne perd rien et on peut reprendre.
- Les clés et mots de passe sont lus depuis `.env` (jamais écrits dans le code). Liste des variables : `docs/TECH.md`.
- Petit et qui marche avant gros et à moitié fini. Les commentaires expliquent **pourquoi**, pas quoi.

## Règles éthiques (non négociables)

- **Aucun nom de compte Wikipédia** dans ce qui est public (site, résumés, JSONL d'échange) : on utilise `account_hash`.
- **Jamais de « découverte » inventée.** La fausse campagne de test est étiquetée `synthetic` et n'apparaît jamais sur le site public.
- Images Wikimedia affichées **avec auteur et licence** ; textes Wikipédia sous **CC BY-SA 4.0** (créditer).
- On ne modifie **jamais** Wikipédia.
- Un cas n'est « signalé » que si **Nemotron et Gemini sont d'accord** ; sinon `human_review`.

## Environnement (Windows)

- Terminal recommandé : Git Bash. Avec `docker compose exec … /data/…`, préfixe `MSYS_NO_PATHCONV=1` (sinon `/data` est réécrit en chemin Windows).
- L'horloge de certains PC est fausse : **l'heure qui compte est celle d'Helsinki** (téléphones).
