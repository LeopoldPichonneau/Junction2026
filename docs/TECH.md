# TimeProof — référence technique

> Tout ce qu'il faut pour coder sa partie sans redemander. Complète `TIMEPROOF-PLAN-SAMEDI.md` (qui fait quoi, quand, formats JSONL).
> **Testé** = vérifié par l'équipe vendredi soir. Le reste est une décision d'équipe à appliquer telle quelle.

## Sommaire
1. [Pile technique et arborescence](#1-pile-technique-et-arborescence)
2. [Variables d'environnement](#2-variables-denvironnement)
3. [Les données](#3-les-données)
4. [Schéma de la base](#4-schéma-de-la-base)
5. [Charger l'historique avec les vraies dates (Léopold)](#5-charger-lhistorique-avec-les-vraies-dates-léopold)
6. [Lire le wikitexte : images, sources, mots, coordination (Maël)](#6-lire-le-wikitexte--images-sources-mots-coordination-maël)
7. [Appeler Nemotron (Maël)](#7-appeler-nemotron-maël)
8. [Appeler Gemini (Nathanaël)](#8-appeler-gemini-nathanaël)
9. [Les API Wikimedia (tout le monde)](#9-les-api-wikimedia-tout-le-monde)
10. [Profil des comptes, exposition, fiabilité (Nathanaël)](#10-profil-des-comptes-exposition-fiabilité-nathanaël)
11. [L'API du site : formats de réponse (Léopold → Eléa)](#11-lapi-du-site--formats-de-réponse-léopold--eléa)
12. [La Lens (Eléa)](#12-la-lens-eléa)
13. [Déploiement : VPS + CRACI (Léopold, Eléa)](#13-déploiement--vps--craci-léopold-eléa)
14. [Pièges déjà rencontrés](#14-pièges-déjà-rencontrés)

---

## 1. Pile technique et arborescence

| Couche | Choix | Pourquoi |
|---|---|---|
| Base | **MariaDB `mariadb:lts`** (Docker), tables **système-versionnées** | Le cœur du challenge MariaDB ; testé en 12.3.3 |
| Serveur | **Python 3.12 + FastAPI + uvicorn**, accès base avec **PyMySQL** | Simple, tout le monde lit du Python |
| Scripts d'analyse | **Python 3.12 + pyarrow + httpx** | Lire les parquet, appeler les API |
| Site | **HTML + CSS + JS simples**, sans framework, servi **par FastAPI** comme fichiers statiques | Pas d'étape de build, pas de serveur en plus |
| IA | **Nemotron 3.5 Super VL** (serveur fourni, hébergé chez Verda) + **Gemini** (API Google) | Les deux parlent le format OpenAI |
| Hébergement | **VPS Hostinger KVM 2** (2 vCPU, 8 Go RAM, 100 Go disque), Docker Compose | Exigé par le challenge Hostinger |
| CI/CD | **CRACI** (`runs-on: craci`) : vérifie et déploie à chaque push sur `main` | Tech challenge CRACI |

```
Junction2026/
├── docs/                     ces documents, dont AI-RULES.md (règles pour tous et pour les assistants IA)
├── docker-compose.yml        Léopold : services db + server
├── .env.example              Léopold : liste des variables, sans valeurs
├── .gitignore                Léopold
├── db/schema.sql             Léopold : section 4
├── server/                   Léopold : FastAPI (main.py), load_versions.py, import_jsonl.py, watch.py, wikitext.py
├── analysis/                 Maël : find_candidates.py, fetch_images.py, run_nemotron.py
├── decision/                 Nathanaël : decide.py, accounts.py, exposure.py, quality.py
├── web/                      Eléa : index.html, case.html, timemachine.html, quality.html, style.css, app.js, mock/*.json
├── lens/                     Eléa : build_bookmarklet.py, lens.js, bookmarklet.txt
├── .github/workflows/        Eléa : deploy.yml (CRACI)
└── data/                     JAMAIS dans git : versions-XX.parquet, exchange/*.jsonl
```

**Ports** : le serveur écoute sur 8000 dans son conteneur, publié en **80** sur le VPS (8000 en local). **MariaDB n'est jamais publié** (pas de `ports:` pour `db`).

**Le site est servi par FastAPI** : les routes `/api/...` d'abord, puis `app.mount("/", StaticFiles(directory="web", html=True))`. Le dossier `web/` est monté dans le conteneur.

## 2. Variables d'environnement

Fichier `.env` à la racine (jamais committé ; `.env.example` sans valeurs est committé). Les clés circulent **en message privé Discord**.

```
# Base
DB_HOST=db
DB_PORT=3306
DB_NAME=timeproof
DB_USER=timeproof
DB_PASSWORD=
DB_ROOT_PASSWORD=
APP_PORT=8000                 # 80 sur le VPS

# true = aucune clé nécessaire, les appels externes renvoient des données simulées au bon format
USE_MOCK=true

# Nemotron (serveur fourni, hébergé chez Verda) — testé
VERDA_INFERENCE_KEY=
NEMOTRON_BASE_URL=https://containers.datacrunch.io/nemotron-3-5-super-vl-b300/v1
NEMOTRON_MODEL=nemotron-3.5-super-vl

# Gemini — clé sur aistudio.google.com ; copier l'identifiant d'un modèle "Flash" depuis AI Studio
GEMINI_API_KEY=
GEMINI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
GEMINI_MODEL=

# Identifiant envoyé aux API Wikimedia (sans lui : erreur 429) — testé
WIKI_USER_AGENT=TimeProofBot/0.1 (https://hackjunction.com; Junction 2026 hackathon prototype)
```

Clé de secours si le serveur Nemotron tombe : une clé `nvapi-…` de build.nvidia.com, adresse `https://integrate.api.nvidia.com/v1`, modèle `nvidia/nemotron-3.5-super-vl-120b-a12b` (≈ 40 appels/min par clé). **La clé Verda ne marche pas à cette adresse** (erreur 401, testé).

## 3. Les données

Source : [MariaDB/mariadb-wikipedia-datasets](https://github.com/MariaDB/mariadb-wikipedia-datasets), jeu **M** (« every version »).

- 16 fichiers : `https://github.com/MariaDB/mariadb-wikipedia-datasets/releases/download/m-2026-10/versions-01.parquet` … `versions-16.parquet` (315 Mo en tout ; `SHA256SUMS` dans la même release).
- Le fichier 01 fait 20 Mo, contient **281 articles, 103 607 versions**, dont *Suomen sisällissota* (`page_id` 1150, 3 357 versions), *Talvisota* (1256), *Urho Kekkonen* (1275), *Carl Gustaf Emil Mannerheim* (6021).
- Les lignes sont rangées **par article, de la plus ancienne à la plus récente**.

| Colonne | Type | Contenu |
|---|---|---|
| `page_id` | uint32 | Identifiant Wikipédia de l'article |
| `title` | string | Titre **à cette version** (les articles sont parfois renommés) |
| `rev_id` | uint32 | Identifiant de la version (`https://fi.wikipedia.org/?oldid=<rev_id>`) |
| `parent_id` | uint32 | Version précédente |
| `timestamp` | timestamp[ms, tz=UTC] | Date de la modification (UTC) |
| `user` | string | Nom du compte, adresse IP ou compte temporaire `~2026-…` |
| `anonymous` | bool | Modification anonyme (19 % des versions) |
| `comment` | string | Résumé de modification |
| `minor` | bool | Marquée « mineure » |
| `sha1` | string | Empreinte du texte : **même sha1 = même texte** (sert à repérer les annulations) |
| `bytes` | uint32 | Taille du texte |
| `text` | string | **Wikitexte brut** (pas de Markdown propre pour les vieilles versions) |

**Lire un parquet sans saturer la mémoire** (le texte du fichier 01 fait environ 760 Mo) :
```python
import pyarrow.parquet as pq
pf = pq.ParquetFile("data/versions-01.parquet")
for batch in pf.iter_batches(batch_size=2000):            # par paquets
    for row in batch.to_pylist():
        ...
# ou seulement certains articles :
table = pq.read_table("data/versions-01.parquet", filters=[("page_id", "in", [1150, 1256])])
```

**Une annulation** (« revert ») est une version dont le `sha1` est égal à celui d'une version **antérieure du même article**, mais différent de celui de la version juste avant.

Mesures faites vendredi sur le fichier 01, annulations exclues :
- 5 771 versions modifient au moins une image ;
- 2 315 légendes modifiées et 1 442 remplacements d'image ;
- 1 605 versions retirent des références (11 421 références retirées) ;
- 274 articles sur 281 ont au moins un changement d'image.

## 4. Schéma de la base

Contenu de `db/schema.sql` (Léopold). La table `article` reprend le schéma de l'exemple officiel MariaDB ([mariadb-system-versioning-wikipedia](https://github.com/MariaDB/mariadb-system-versioning-wikipedia), licence MIT, à créditer dans le README).

```sql
-- Une ligne par article = ce que Wikipédia affiche aujourd'hui ; chaque version passée
-- est une ligne d'historique, écrite avec la vraie date Wikipédia.
CREATE TABLE IF NOT EXISTS article (
  page_id    INT UNSIGNED NOT NULL,
  title      VARCHAR(255) NOT NULL,
  rev_id     INT UNSIGNED NOT NULL,
  parent_id  INT UNSIGNED,
  user       VARCHAR(255),             -- reste en base ; jamais renvoyé par l'API publique
  anonymous  BOOL NOT NULL DEFAULT 0,
  comment    TEXT,
  minor      BOOL NOT NULL DEFAULT 0,
  sha1       CHAR(31),
  len        INT UNSIGNED,
  text       MEDIUMTEXT COMPRESSED NOT NULL,
  row_start  TIMESTAMP(6) GENERATED ALWAYS AS ROW START INVISIBLE,
  row_end    TIMESTAMP(6) GENERATED ALWAYS AS ROW END INVISIBLE,
  PERIOD FOR SYSTEM_TIME (row_start, row_end),
  PRIMARY KEY (page_id),
  KEY (sha1), KEY (rev_id), KEY (user),
  KEY start_key (page_id, row_start)   -- rend rapides les dates anciennes "as of"
) CHARACTER SET utf8mb4 WITH SYSTEM VERSIONING;

-- Importés depuis data/exchange/*.jsonl par server/import_jsonl.py
CREATE TABLE IF NOT EXISTS candidate (
  rev_id INT UNSIGNED PRIMARY KEY, page_id INT UNSIGNED NOT NULL, title VARCHAR(255),
  kind ENUM('framing','image','sources','coordination') NOT NULL,
  edited_at DATETIME(6) NOT NULL, account_hash CHAR(16), synthetic BOOL NOT NULL DEFAULT 0,
  data JSON NOT NULL,                  -- la ligne JSONL complète
  KEY (page_id), KEY (kind)
) CHARACTER SET utf8mb4;

CREATE TABLE IF NOT EXISTS analysis (
  rev_id INT UNSIGNED PRIMARY KEY, model VARCHAR(120) NOT NULL,
  suspicious BOOL, data JSON NOT NULL
) CHARACTER SET utf8mb4;

-- Historisée : on peut prouver quand un cas a été publié ou retiré
CREATE TABLE IF NOT EXISTS decision (
  rev_id INT UNSIGNED PRIMARY KEY,
  decision ENUM('flag','dismiss','human_review') NOT NULL,
  publish BOOL NOT NULL DEFAULT 0, confidence FLOAT,
  days_live FLOAT, readers_est INT UNSIGNED, still_online BOOL,
  data JSON NOT NULL
) CHARACTER SET utf8mb4 WITH SYSTEM VERSIONING;

CREATE TABLE IF NOT EXISTS account_profile (
  account_hash CHAR(16) PRIMARY KEY,
  kind ENUM('declared_bot','bot_like','throwaway','single_purpose','normal') NOT NULL,
  score FLOAT, data JSON NOT NULL
) CHARACTER SET utf8mb4;
```

Pour l'import, une ligne JSONL donne une ligne de table : les colonnes servent à filtrer et à trier, la ligne complète va dans `data` (JSON). Les chiffres de fiabilité ne vont pas en base : Nathanaël écrit `data/exchange/quality.json`, que l'API renvoie tel quel.

## 5. Charger l'historique avec les vraies dates (Léopold)

**Le problème** : une table système-versionnée date chaque ligne **au moment de l'insertion**. Si on insère normalement, toutes les versions seraient datées de samedi, et « as of 2015 » ne renverrait rien.

**La solution** (méthode de l'exemple officiel MariaDB, testée vendredi) : écrire soi-même `row_start` et `row_end`.

```sql
SET time_zone = '+00:00';                       -- Wikipédia est en UTC
SET system_versioning_insert_history = 1;      -- autorise l'écriture de row_start/row_end
-- chaque version sauf la dernière : début = sa date, fin = la date de la version suivante
INSERT INTO article (page_id, title, rev_id, parent_id, user, anonymous, comment, minor, sha1, len, text, row_start, row_end)
VALUES (...);
-- la version actuelle : seulement le début (MariaDB met la fin "toujours en cours")
INSERT INTO article (page_id, title, rev_id, parent_id, user, anonymous, comment, minor, sha1, len, text, row_start)
VALUES (...);
SET system_versioning_insert_history = 0;
```

L'algorithme, par article :
1. Trier les versions par (`timestamp`, `rev_id`).
2. Si deux versions ont la même seconde, ajouter **1 microseconde** à la seconde, sinon une version finirait là où elle commence.
3. Insérer par **lots d'au plus ~8 Mo de texte** (pas par nombre de lignes) et lancer MariaDB avec `--max-allowed-packet=256M`.
4. Une transaction par article ; si l'article est déjà en base, passer au suivant, pour pouvoir relancer après un plantage.

**Mesuré vendredi** : 3 357 versions de l'article 1150 en **61 s**, pic d'environ **1,3 Go** de RAM. Tout M est **estimé à 4–6 h** (extrapolation, peut-être plus sur 2 vCPU) → à lancer **en fond** sur le VPS, fichier par fichier, avec un journal.

**Le script tourne DANS le conteneur `server`**. Sur le VPS lui-même, la base n'est pas joignable (`db` n'existe que dans le réseau Docker) et `pyarrow` n'est pas installé. Le dossier `server/` est copié dans `/app` du conteneur, et les données sont montées dans `/data` :
```bash
# 1. vérifier d'abord que les tables existent
docker compose exec -T db mariadb -u timeproof -p"$DB_PASSWORD" timeproof -e "SHOW TABLES"
# 2. lancer le chargement des 16 fichiers en fond
nohup bash -c 'for i in $(seq -w 1 16); do docker compose exec -T server python load_versions.py /data/versions-$i.parquet; done' > load.log 2>&1 &
tail -f load.log
```

**Création des tables** : `db/schema.sql` est monté dans le service `db` sur `/docker-entrypoint-initdb.d/`. MariaDB l'exécute **une seule fois, au premier démarrage, quand le volume est vide**. Pour changer le schéma plus tard : `docker compose down -v` (efface la base !) ou un `ALTER TABLE` à la main (sur une table historisée : `SET system_versioning_alter_history = KEEP;` d'abord).

**Requêtes clés** :
```sql
-- l'article tel qu'il était le 1er juin 2015 (date ET heure obligatoires)
SELECT title, rev_id, row_start, text FROM article
  FOR SYSTEM_TIME AS OF TIMESTAMP '2015-06-01 00:00:00' WHERE page_id = 1150;
-- toutes les versions, avec les annulations
SELECT rev_id, row_start, sha1 <> LAG(sha1) OVER (ORDER BY row_start)
         AND MIN(row_start) OVER (PARTITION BY sha1) < row_start AS is_revert
FROM article FOR SYSTEM_TIME ALL WHERE page_id = 1150 ORDER BY row_start;
```

**Test qui doit passer** : `as_of=2006-01-01` sur 1150 renvoie une version de 2005 (vérifié vendredi : rev 472288, 11/10/2005).

**Après le chargement**, une nouvelle version (veille) s'ajoute avec un simple `UPDATE article SET … WHERE page_id = …` : MariaDB archive l'ancienne version tout seul.

## 6. Lire le wikitexte : images, sources, mots, coordination (Maël)

**Toujours analyser le wikitexte brut AVANT de le nettoyer**, car le nettoyage efface les images et les références.

**Images** : liens `[[Tiedosto:Nom.jpg|thumb|…|Légende]]` (préfixes : `Tiedosto`, `Kuva`, `File`, `Image`). La légende est le **dernier** morceau après `|`. Elle peut contenir des `[[liens]]`, donc on compte les crochets au lieu d'utiliser une simple expression régulière :
```python
import re
PREFIX = re.compile(r"\[\[\s*(Tiedosto|Kuva|File|Image)\s*:", re.I)

def images(text: str) -> dict[str, str]:
    """{nom_de_fichier: légende}"""
    out, i = {}, 0
    while (m := PREFIX.search(text, i)):
        depth, j = 0, m.start()
        while j < len(text) - 1:
            if text.startswith("[[", j): depth += 1; j += 2
            elif text.startswith("]]", j):
                depth -= 1; j += 2
                if depth == 0: break
            else: j += 1
        parts = text[m.end():j - 2].split("|")
        name = parts[0].strip().replace("_", " ")
        if name:
            out[name[:1].upper() + name[1:]] = parts[-1].strip() if len(parts) > 1 else ""
        i = j
    return out
```
Comparer avec la version précédente : fichier ajouté, retiré, remplacé, ou **légende modifiée** (même fichier, légende différente et non vide des deux côtés). Limite : les images placées dans les modèles (`{{Infobox …|kuva=…}}`) ne sont pas vues.

**Sources** : `len(re.findall(r"<ref[\s>]", text, re.I))`. Si le nombre baisse → `kind: "sources"`.

**Nettoyer pour comparer les mots** : retirer les commentaires `<!-- -->`, les `<ref>…</ref>`, les tableaux `{| … |}`, les modèles `{{…}}` (en boucle, car ils s'imbriquent), les liens de fichiers ; remplacer `[[cible|texte]]` par `texte`, et retirer `'''` et `''`. Puis comparer **mot à mot**, uniquement dans les paragraphes qui ont changé (`difflib.SequenceMatcher` sur les listes de mots), sinon une faute corrigée compte comme un paragraphe entier.

**Mots surveillés pour la dérive** (1918, à compléter avec l'aide de Gemini pour d'autres thèmes) : `vapaussota` (guerre de libération), `sisällissota` (guerre civile), `kansalaissota`, `luokkasota` (guerre de classes), `punakapina` (rébellion rouge), `veljessota` (guerre fratricide). Le signal est le **rapport** entre termes au fil du temps, pas le compte brut. Mesuré sur 1150 : *sisällissota* / *vapaussota* passe d'environ 1:1 (2005) à environ 3:1 (2026).

**Coordination (version simple, sans IA)** :
1. Pour chaque texte ajouté d'au moins 20 mots : minuscules, sans ponctuation, découpé en suites de 8 mots consécutifs, chacune transformée en empreinte (`hash`).
2. On regroupe : une même suite ajoutée par **au moins 2 comptes différents**, sur **au moins 2 articles différents**, en **14 jours** → `kind: "coordination"`.
3. On ignore les annulations, les modifications mineures et les robots officiels.

**Priorités pour Nemotron** (ne pas lancer 100 000 appels) : d'abord les légendes modifiées et les remplacements d'image des articles sensibles (1918, guerres, présidents, Carélie), puis la coordination, puis les sources retirées, puis la dérive.

**Toutes les annulations et modifications mineures sont exclues** du tri. L'empreinte d'un compte : `hashlib.sha256(user.encode()).hexdigest()[:16]`.

## 7. Appeler Nemotron (Maël)

**Testé vendredi** : comprend le finnois (il a repéré « guerre civile » → « guerre de libération » et expliqué le changement de cadrage), décrit une photo et a démasqué une fausse légende. Durée : **1,3 s** pour le texte, **2,3 s** avec image. L'image peut être envoyée **par son lien** (miniature Wikimedia).

```python
import json, os, httpx

def ask_nemotron(prompt: str, image_url: str | None = None) -> dict:
    content = prompt if not image_url else [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": image_url}},
    ]
    r = httpx.post(
        os.environ["NEMOTRON_BASE_URL"] + "/chat/completions",
        headers={"Authorization": f"Bearer {os.environ['VERDA_INFERENCE_KEY']}"},
        json={"model": os.environ["NEMOTRON_MODEL"], "temperature": 0.6, "top_p": 0.95,
              "max_tokens": 1500, "messages": [{"role": "user", "content": content}]},
        timeout=180,
    )
    r.raise_for_status()
    text = r.json()["choices"][0]["message"].get("content") or ""   # le raisonnement éventuel est dans "reasoning_content"
    return json.loads(text[text.find("{"): text.rfind("}") + 1])    # ne garder que le JSON
```

**Consigne de l'enquêteur** (point de départ) :
```
You investigate one edit to a Finnish Wikipedia article about the history of Finland.
Texts are in Finnish; reason over them and answer in English.
Decide whether this edit looks like an attempt to push a narrative (one-sided reframing,
misleading image or caption, removal of sources, coordinated editing) rather than ordinary
editing (new facts, style, sourcing, vandalism cleanup). Be conservative: most edits are ordinary.
If an image is attached, describe what it actually shows and say whether the caption matches it.
Answer with JSON only:
{"suspicious": true|false, "signals": ["…"], "report": "3-6 sentences a human can check",
 "image_findings": {"what_it_shows": "…", "caption_matches": true|false|null} | null}
```
Le message utilisateur contient la ligne de `candidates.jsonl` (texte ajouté/retiré, légendes, compte en version anonymisée).

**Limites** : serveur **partagé** entre équipes (limite d'appels inconnue → demander à Verda sur Discord), donc pas plus de 2 à 4 appels en parallèle sans leur accord. Écrire chaque résultat dès qu'il arrive dans `analysis.jsonl`, et sauter les `rev_id` déjà traités au redémarrage.

## 8. Appeler Gemini (Nathanaël)

Même format que Nemotron (compatibilité OpenAI de Google, vérifiée vendredi dans leur documentation) :
```python
r = httpx.post(os.environ["GEMINI_BASE_URL"] + "chat/completions",       # l'adresse finit déjà par "/"
               headers={"Authorization": f"Bearer {os.environ['GEMINI_API_KEY']}"},
               json={"model": os.environ["GEMINI_MODEL"], "temperature": 0.2,
                     "messages": [{"role": "system", "content": DECIDER_PROMPT},
                                  {"role": "user", "content": json.dumps(analysis_line, ensure_ascii=False)}]},
               timeout=120)
```

**Consigne du décideur** (point de départ) :
```
You make the final call on a Wikipedia edit, given the evidence and an investigator's report
(the investigator can be wrong). Texts are Finnish; write in English for a general reader.
"flag" = likely narrative manipulation, "dismiss" = ordinary editing, "human_review" = unclear.
False positives are costly: when in doubt, choose human_review. Never name any account.
Answer with JSON only:
{"decision": "flag"|"dismiss"|"human_review", "confidence": 0.0-1.0, "publish": true|false,
 "signal_type": "framing"|"image"|"sources"|"coordination",
 "headline_en": "max 90 characters", "summary_en": "2-4 sentences", "explanation": "why"}
```

**Règle des deux avis, appliquée dans le code et pas laissée au modèle** :
- `flag` si Gemini dit `flag` **et** Nemotron dit `suspicious: true` ;
- `dismiss` si les deux disent « pas suspect » ;
- `human_review` dans tous les autres cas, **et pour toute réponse hors de ces 3 valeurs** ;
- `publish` n'est possible que pour un `flag`.

**Coût** : appeler Gemini seulement sur les cas « suspects » de Nemotron, plus un échantillon d'environ 50 non-suspects (pour mesurer les désaccords). **Tous les autres** (Nemotron dit « pas suspect » et le cas n'est pas tiré au sort) reçoivent `dismiss` **par règle**, sans appel à Gemini, avec `"decided_by": "rule"` dans la ligne.

## 9. Les API Wikimedia (tout le monde)

**Toujours** envoyer l'en-tête `User-Agent: $WIKI_USER_AGENT`. Avec un identifiant générique, on a eu l'**erreur 429** vendredi. Pas plus de quelques requêtes par seconde.

| Besoin | Adresse |
|---|---|
| Miniature + auteur + licence d'une image (≤ 50 titres par requête) | `https://fi.wikipedia.org/w/api.php?action=query&format=json&prop=imageinfo&iiprop=url\|extmetadata&iiurlwidth=800&titles=Tiedosto:A.jpg\|Tiedosto:B.jpg` → `thumburl`, `extmetadata.Artist`, `extmetadata.LicenseShortName` |
| Résumé + image principale d'un article | `https://fi.wikipedia.org/api/rest_v1/page/summary/Suomen_sisällissota` |
| Vues par jour (depuis 07/2015) | `https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/fi.wikipedia/all-access/user/<Titre_avec_underscores>/daily/<AAAAMMJJ>/<AAAAMMJJ>` |
| Nouvelles versions d'un article (veille) — **à vérifier au premier appel** | `https://fi.wikipedia.org/w/api.php?action=query&format=json&prop=revisions&pageids=<id>&rvdir=newer&rvstart=<ISO date>&rvlimit=50&rvprop=ids\|timestamp\|user\|comment\|sha1\|size\|flags\|content&rvslots=main` (un article par requête) |
| Liste des robots officiels — **à vérifier au premier appel** | `https://fi.wikipedia.org/w/api.php?action=query&format=json&list=allusers&augroup=bot&aulimit=500` |
| Liens pour le site | version : `https://fi.wikipedia.org/?oldid=<rev_id>` · différence avec la précédente : `https://fi.wikipedia.org/w/index.php?diff=prev&oldid=<rev_id>` |

Vérifié vendredi : l'API de vues répond pour *Suomen_sisällissota* (136 mois, 1 874 510 vues de juillet 2015 à octobre 2026).

## 10. Profil des comptes, exposition, fiabilité (Nathanaël)

**Source des données : les fichiers parquet, pas la base.** Le chargement complet dans MariaDB prendra des heures : le profil des comptes et l'exposition se calculent directement depuis `data/versions-XX.parquet` (même lecture que section 3).

**Profil des comptes** (`accounts.jsonl`, sans IA, sur les parquet) :

| `kind` | Règle de départ (à ajuster en regardant les données) |
|---|---|
| `declared_bot` | nom dans la liste des robots officiels (section 9) ou finissant par « bot » → **bénin, exclu de tout** |
| `bot_like` | ≥ 20 modifications en 1 h, ou intervalles très réguliers (écart-type des intervalles < 10 % de leur moyenne) |
| `throwaway` | actif ≤ 7 jours en tout, ≥ 3 articles sensibles touchés |
| `single_purpose` | ≥ 10 modifications, toutes sur ≤ 2 articles du même thème |
| `normal` | le reste |

Ajouter le **taux d'annulation** (part de ses modifications annulées par un autre compte) dans `reasons`. Chaque compte non normal doit avoir des `reasons` **lisibles par un humain**.

**Exposition** d'un cas :
- **durée en ligne** : de la date de la version suspecte jusqu'à la date de la **première version suivante** où le contenu suspect a disparu (pour une image : la légende ou le fichier change ; pour un texte : les mots ajoutés ne sont plus présents). Si le contenu est toujours là : `still_online: true`, durée jusqu'à aujourd'hui ;
- **lecteurs estimés** : somme des vues par jour sur la période (section 9), avec le **titre de l'époque**. `null` si la période est avant juillet 2015, et c'est un **plafond** (vues de tout l'article) : on l'écrit toujours « ≈ ».

**Fiabilité** → `data/exchange/quality.json` :
```json
{"synthetic_campaign": {"planted": 13, "caught": 11},
 "manual_review": {"reviewed": 20, "correct": 17},
 "downgraded_by_two_model_rule": 42,
 "declared_bots_excluded": 398,
 "suspicious_accounts": 27,
 "notes": {"synthetic_campaign": "13 fake edits planted in a test copy, never shown publicly"}}
```
La fausse campagne est générée par `decision/quality.py` sous forme de lignes `candidates.jsonl` avec `"synthetic": true`. Elle passe dans la même chaîne, et **elle est filtrée de toute réponse publique**.

## 11. L'API du site : formats de réponse (Léopold → Eléa)

Eléa crée des fichiers `web/mock/*.json` **exactement** à ces formats. **Aucune réponse publique ne contient `user`.**

```jsonc
// GET /api/stats
{"articles": 19742, "versions": 862076, "candidates": 0, "analysed": 0, "published": 0, "readers_exposed_est": 0}

// GET /api/cases            (publiés, triés par readers_est puis confidence)   ?since=7d pour la veille
[{"rev_id": 23498098, "page_id": 1150, "title": "Suomen sisällissota", "date": "2019-03-02",
  "signal_type": "image", "headline_en": "…", "summary_en": "…", "confidence": 0.8,
  "days_live": 412, "readers_est": 38000, "still_online": false, "image_thumb": "https://upload.wikimedia.org/…"}]

// GET /api/cases/{rev_id}   (fiche de preuves)
{"rev_id": 23498098, "page_id": 1150, "title": "…", "date": "2019-03-02", "signal_type": "image",
 "headline_en": "…", "summary_en": "…", "confidence": 0.8,
 "added": "…", "removed": "…",
 "image": {"file": "…", "thumb_url": "…", "caption_old": "…", "caption_new": "…", "author": "…", "license": "CC BY-SA 4.0"},
 "investigator": {"model": "nemotron-3.5-super-vl", "report": "…", "signals": ["…"],
                  "image_findings": {"what_it_shows": "…", "caption_matches": false}},
 "decider": {"model": "gemini-…", "decision": "flag", "explanation": "…"},
 "exposure": {"live_from": "2019-03-02", "live_until": "2020-04-17", "days_live": 412, "readers_est": 38000, "still_online": false},
 "account": {"kind": "throwaway", "reasons": ["…"]},
 "links": {"version": "https://fi.wikipedia.org/?oldid=23498098",
           "diff": "https://fi.wikipedia.org/w/index.php?diff=prev&oldid=23498098"}}

// GET /api/quality          = le contenu de data/exchange/quality.json

// GET /api/articles
[{"page_id": 1150, "title": "Suomen sisällissota", "versions": 3357, "first_edit": "2003-08-26", "last_edit": "2026-09-12"}]

// GET /api/articles/{page_id}?as_of=2015-06-01      (texte nettoyé, sans nom de compte)
{"page_id": 1150, "title": "…", "rev_id": 14664523, "as_of": "2015-06-01", "saved_at": "2015-02-09T18:57:03Z", "text": "…"}

// GET /api/articles/{page_id}/timeline
[{"month": "2008-03", "edits": 12, "reverts": 2}]
```

`/api/articles` ne doit pas recalculer un `GROUP BY` sur 862 000 lignes à chaque appel : le précalculer une fois à la fin du chargement, dans une petite table ou un fichier.

## 12. La Lens (Eléa)

**Avant de construire (2 minutes)** : vérifier qu'un favori peut agir sur Wikipédia. Créez un favori dont l'adresse est :
```
javascript:(()=>{document.querySelectorAll('#mw-content-text img').forEach(i=>i.style.outline='4px solid red')})()
```
Ouvrez `https://fi.wikipedia.org/wiki/Suomen_sisällissota` et cliquez sur le favori. Si les images ont un contour rouge, la méthode marche. Sinon (sécurité de la page), prévenez l'équipe tout de suite : le plan B est une extension de navigateur minimale chargée à la main en mode développeur.

**Décision technique : la Lens n'appelle PAS notre serveur.** Wikipédia est en **HTTPS**, notre VPS en **HTTP** : le navigateur **bloque** un appel d'une page HTTPS vers une adresse HTTP (« contenu mixte »).

**Donc** :
- `lens/build_bookmarklet.py` lit `analysis.jsonl` + `decisions.jsonl` (cas publiés des **2-3 articles de démo** seulement) et produit un petit JSON d'annotations ;
- il l'**intègre directement** dans `lens/lens.js`, puis génère `lens/bookmarklet.txt` (`javascript:(()=>{…})()`) à copier dans un favori ;
- sur la page Wikipédia, le script repère :
  - **les images**, par leur nom de fichier dans l'attribut `src` des `<img>` ;
  - **les passages**, en cherchant le texte ajouté dans les paragraphes (`document.querySelectorAll("#mw-content-text p")`) ;
- il les entoure (contour coloré) et affiche une infobulle au survol : *« Caption changed 3 times since 2009 · online 412 days · ≈ 38,000 readers »*, avec un lien vers la fiche de cas sur notre site (un simple lien, autorisé) ;
- gardez le JSON intégré petit (quelques dizaines d'annotations) : un favori trop long peut être tronqué par le navigateur.

## 13. Déploiement : VPS + CRACI (Léopold, Eléa)

**VPS (une fois, Léopold)**, en root :
```bash
curl -fsSL https://get.docker.com | sh            # script officiel d'installation de Docker
adduser --disabled-password deploy && usermod -aG docker deploy
ufw allow 22 && ufw allow 80 && ufw --force enable  # SSH + web seulement, jamais 3306
# coller la clé publique de déploiement dans /home/deploy/.ssh/authorized_keys
```
Puis, en tant que `deploy` : créer `~/timeproof/` avec `.env` (vraies valeurs, `APP_PORT=80`, `USE_MOCK=false`) et `data/`, télécharger les 16 fichiers parquet directement sur le VPS, puis lancer le chargement (section 5).

**`docker-compose.yml`** :
- service `db` : `mariadb:lts`, variables `MARIADB_DATABASE` / `MARIADB_USER` / `MARIADB_PASSWORD` / `MARIADB_ROOT_PASSWORD` prises dans `.env`, `command: --max-allowed-packet=256M`, volume persistant pour `/var/lib/mysql`, volume `./db/schema.sql:/docker-entrypoint-initdb.d/01-schema.sql:ro`, healthcheck `healthcheck.sh --connect --innodb_initialized`, **pas de `ports:`** ;
- service `server` : construit depuis `server/` (`python:3.12-slim`, `WORKDIR /app`, `COPY . .`, `pip install fastapi uvicorn PyMySQL pyarrow httpx`), `env_file: .env`, `depends_on: db (service_healthy)`, `ports: "${APP_PORT}:8000"`, volumes `./web:/app/web:ro` et `./data:/data`, commande `uvicorn main:app --host 0.0.0.0 --port 8000`.

**CRACI (Eléa, avec Léopold)** :
1. platform.craci.com → créer l'organisation avec le code d'invitation → Settings → Builds → installer l'application GitHub sur le dépôt.
2. Dans le dépôt GitHub → Settings → Secrets → Actions : `VPS_HOST`, `VPS_USER` (`deploy`), `VPS_SSH_KEY` (clé privée).
3. `.github/workflows/deploy.yml` :
```yaml
name: deploy
on:
  push:
    branches: [main]
jobs:
  deploy:
    runs-on: craci
    steps:
      - uses: actions/checkout@v4
      - name: Check Python files compile
        run: for d in server analysis decision; do [ -d "$d" ] && python3 -m compileall -q "$d"; done; true
      - name: Ship to the VPS and restart
        env:
          VPS_HOST: ${{ secrets.VPS_HOST }}
          VPS_USER: ${{ secrets.VPS_USER }}
          VPS_SSH_KEY: ${{ secrets.VPS_SSH_KEY }}
        run: |
          mkdir -p ~/.ssh && printf '%s\n' "$VPS_SSH_KEY" > ~/.ssh/k && chmod 600 ~/.ssh/k
          ssh-keyscan -H "$VPS_HOST" >> ~/.ssh/known_hosts
          tar czf - --exclude=.git --exclude=data --exclude=.env . | ssh -i ~/.ssh/k "$VPS_USER@$VPS_HOST" "mkdir -p ~/timeproof && tar xzf - -C ~/timeproof"
          ssh -i ~/.ssh/k "$VPS_USER@$VPS_HOST" "cd ~/timeproof && docker compose up -d --build"
```
Ce fichier n'a **jamais tourné** : vérifiez au premier push que le runner CRACI a bien `ssh` et `python3`. La veille peut être lancée par un second workflow avec `on: schedule: - cron: "0 * * * *"`, qui exécute `server/watch.py` sur le VPS par `ssh`.

## 14. Pièges déjà rencontrés

| Piège | Solution |
|---|---|
| Git Bash réécrit `/data/…` en chemin Windows | Préfixer `MSYS_NO_PATHCONV=1` |
| L'horloge de certains PC avance d'une heure | Se fier à l'heure d'Helsinki des téléphones |
| `TIMESTAMP ?` refuse une date seule | Écrire `'2015-06-01 00:00:00'` |
| Toutes les versions datées du jour du chargement | `system_versioning_insert_history = 1` + `row_start`/`row_end` (section 5) |
| Erreur 429 de Wikimedia | User-Agent descriptif (section 2) |
| Erreur 401 « Invalid JWT » avec la clé Verda | Elle ne marche qu'à l'adresse Verda, pas chez NVIDIA |
| Une faute corrigée compte comme un paragraphe entier | Comparer mot à mot dans les seuls paragraphes changés |
| Les images et références disparaissent à l'analyse | Les extraire **avant** de nettoyer le wikitexte |
| La réponse de l'IA contient du texte autour du JSON | Garder seulement du premier `{` au dernier `}` |
| Le titre d'un article change avec le temps | Pour les vues, utiliser le `title` de la version concernée |
| Lens bloquée sur Wikipédia | Données intégrées au favori, aucun appel réseau (section 12) |
