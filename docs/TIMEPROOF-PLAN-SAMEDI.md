# TimeProof — plan de samedi (pour débutants)

> Samedi 14/11 · départ 10h (1 h de retard) · heure d'Helsinki · table A6
> À lire en entier par les 4 avant de commencer. Gardez [TIMEPROOF-RESUME.md](TIMEPROOF-RESUME.md) à côté.
> **Détails techniques** (pile, schéma SQL, colonnes des données, exemples d'appels, algorithmes, formats de l'API, pièges) : [TECH.md](TECH.md).

---

## 1. Qui fait quoi

| Qui | Rôle | En une phrase | Son dossier dans le dépôt |
|---|---|---|---|
| **Léopold** | **Serveur & base** | Le VPS, MariaDB avec tout l'historique, l'API qui sert les données au site, puis la **veille** (bonus après 17h) | `server/` (+ `docker-compose.yml`, `db/`) |
| **Maël** | **Analyse** | Trouver les modifications suspectes (texte, images, sources) et les faire examiner par Nemotron | `analysis/` |
| **Nathanaël** | **Décision & preuves** | Gemini décide et publie, **profil des comptes** (bots, comptes jetables), score d'exposition, chiffre de fiabilité | `decision/` |
| **Eléa** | **Site, Lens & pitch** | Le tableau de bord (avec le panneau **Detection quality**), la TimeProof Lens sur Wikipédia, le déploiement CRACI, la vidéo | `web/`, `lens/`, `.github/` |

Pourquoi cette répartition :
- **Léopold** est propriétaire du dépôt GitHub : il garde la branche `main` propre.
- **Maël** a déjà fait marcher Nemotron hier soir.
- **Nathanaël** a une partie indépendante qu'il peut développer sur des exemples.
- **Eléa** a la partie la plus visible, celle que le jury verra.

Avant de coder : lire cette fiche et [TECH.md](TECH.md), puis avancer une petite étape à la fois.

---

## 2. Démarrage (10h00 → 10h30, tout le monde)

1. **Installer**, si ce n'est pas déjà fait :
   - [Git](https://git-scm.com/downloads)
   - [Python 3.12](https://www.python.org/downloads/)
   - [VS Code](https://code.visualstudio.com/)
   - [Docker Desktop](https://www.docker.com/products/docker-desktop/), pour Léopold et Nathanaël au minimum
2. **Accès GitHub** : Léopold va sur `github.com/LeopoldPichonneau/Junction2026` → *Settings* → *Collaborators* → il ajoute les comptes GitHub de Maël, Nathanaël et Eléa. Chacun accepte l'invitation reçue par email.
3. **Récupérer le dépôt** (chacun, dans un terminal) :
   ```bash
   git clone https://github.com/LeopoldPichonneau/Junction2026.git
   cd Junction2026
   ```
4. **Les clés**, partagées **en message privé Discord, jamais dans le dépôt** :
   - Maël envoie la clé Verda/Nemotron à qui en a besoin.
   - Nathanaël crée sa clé Gemini sur [aistudio.google.com](https://aistudio.google.com) (avec les 50 $ de crédits).
   - Léopold garde le code CRACI et l'accès au VPS.
4 bis. **L'environnement Python** (chacun, dans le dossier du dépôt ; `pip` seul ne marche pas toujours sous Windows) :
   ```bash
   python -m venv .venv
   source .venv/Scripts/activate        # Git Bash sous Windows ; sur Mac/Linux : source .venv/bin/activate
   python -m pip install pyarrow httpx PyMySQL fastapi uvicorn
   ```
5. **Les données de test** (chacun) : télécharger le premier des 16 fichiers (20 Mo) dans un dossier `data/` du dépôt.
   ```bash
   mkdir data
   curl -L -o data/versions-01.parquet https://github.com/MariaDB/mariadb-wikipedia-datasets/releases/download/m-2026-10/versions-01.parquet
   ```
   Il contient 281 articles, dont l'article sur 1918 (`page_id` 1150). Tout le monde développe dessus ce matin.
6. **Le challenge Hostinger (n'importe qui, ce matin)** : le formulaire n'a accepté qu'**un** challenge principal (MariaDB). Demandez à l'accueil ou aux mentors Hostinger si on peut **ajouter *Decode the Noise***. Sinon, on ne concourt pas pour Hostinger.

---

## 3. Git : la méthode (à suivre à la lettre)

**Règle n°1 : personne ne travaille directement sur `main`.** `main` doit toujours marcher.

**Règle n°2 : chacun ne modifie que SON dossier** (tableau de la section 1). Les fichiers partagés (`db/schema.sql`, `docker-compose.yml`) ne sont modifiés que par Léopold : demandez-lui.

**Le cycle de travail**, à répéter toute la journée :

```bash
# 1. Une fois, au début : créer sa branche
git switch -c feat/analysis          # Léopold : feat/server · Nathanaël : feat/decision · Eléa : feat/web

# 2. Souvent (toutes les 30-60 min) : sauvegarder et envoyer
git add analysis/                    # uniquement son dossier
git commit -m "analysis: detect caption changes"
git push -u origin feat/analysis     # -u seulement la première fois, ensuite : git push

# 3. Aux points de rendez-vous : récupérer le travail des autres
git switch main
git pull
git switch feat/analysis
git merge main
```

**Mettre son travail dans `main`** :
1. Sur GitHub, ouvrez une *Pull Request* de votre branche vers `main`.
2. Écrivez une phrase sur ce que ça fait.
3. Léopold relit vite et clique sur *Merge*.

À faire aux rendez-vous de **13h30, 17h, 21h et 1h**, pas en permanence.

**Ce qu'on ne committe JAMAIS** (Léopold crée le `.gitignore` dans son premier commit) :
```
.env
*.key
*-key.txt
data/
__pycache__/
.venv/
*.jsonl.local
```

**En cas de conflit Git** : ne paniquez pas, ne forcez rien (`--force` interdit). Appelez Léopold ou demandez à l'IA d'expliquer le conflit.

---

## 4. Le contrat : comment les morceaux se parlent

Pour ne pas s'attendre, on s'échange des **fichiers JSONL** (un objet JSON par ligne), rangés dans `data/exchange/`. Chacun peut créer des faux fichiers d'exemple au bon format pour avancer seul.

### 4.1 `candidates.jsonl` — écrit par Maël (étape 1)
Une modification qui mérite d'être examinée :
```json
{"rev_id": 23498098, "page_id": 1150, "title": "Suomen sisällissota", "timestamp": "2025-08-17T10:28:50Z",
 "kind": "image", "account_hash": "a3f9c2…", "user_is_new": true, "synthetic": false, "comment": "…",
 "added": "mots ajoutés", "removed": "mots retirés",
 "image": {"change": "recaptioned", "file": "Jaakarit_vaasan_torilla.jpg",
           "caption_old": "…", "caption_new": "…", "thumb_url": "https://…"},
 "refs_removed": 0}
```
`kind` vaut l'une de ces valeurs : `"framing"`, `"image"`, `"sources"`, `"coordination"`. `image` vaut `null` si aucune image n'est concernée.

### 4.2 `analysis.jsonl` — écrit par Maël (étape 2, Nemotron)
La même ligne, plus le rapport de Nemotron :
```json
{"rev_id": 23498098, "...": "...", "nemotron": {"suspicious": true, "signals": ["caption changed meaning"],
 "report": "3-6 phrases vérifiables", "image_findings": {"what_it_shows": "…", "caption_matches": false}}}
```

### 4.3 `decisions.jsonl` — écrit par Nathanaël (Gemini + exposition)
```json
{"rev_id": 23498098, "decision": "flag", "confidence": 0.8, "publish": true,
 "headline_en": "A 1918 photo caption changed meaning", "summary_en": "2-4 phrases claires",
 "exposure": {"live_from": "2019-03-02", "live_until": null, "days_live": 2450, "readers_est": 38000}}
```
- `decision` : `flag`, `dismiss` ou `human_review`.
- **Règle** : `flag` seulement si Nemotron (`suspicious`) **et** Gemini sont d'accord, sinon `human_review`.
- `readers_est` vaut `null` avant juillet 2015.

### 4.3 bis `accounts.jsonl` — écrit par Nathanaël (profil des comptes, pour Hostinger)
Un compte par ligne, calculé **sans IA** à partir des fichiers de données (auteur, date, anonyme, annulations) :
```json
{"account_hash": "a3f9…", "kind": "bot_like", "declared_bot": false, "score": 0.82,
 "reasons": ["38 edits in 2 h at regular intervals", "edits 6 sensitive articles only", "71% of edits reverted"],
 "edits": 54, "articles": 6, "first_seen": "2024-03-02", "last_seen": "2024-03-09"}
```
- `kind` : `"declared_bot"` (robot officiel de Wikipédia, **bénin**), `"bot_like"`, `"throwaway"` (compte jetable), `"single_purpose"` (un seul thème), `"normal"`.
- **Aucun nom de compte** dans ce fichier : on garde une empreinte (`account_hash`). Le vrai nom ne sert qu'à la file de relecture privée.
- Maël s'en sert pour prioriser ses candidats ; le site en tire le panneau « Detection quality ».

### 4.4 La base et l'API — Léopold
- Table `article` historisée (`WITH SYSTEM VERSIONING`), avec les vraies dates Wikipédia.
- Léopold **importe** `candidates.jsonl`, `analysis.jsonl`, `decisions.jsonl` et `accounts.jsonl` dans la base (tables : [TECH.md, section 4](TECH.md#4-schéma-de-la-base)), et sert `quality.json` tel quel.

| Adresse | Ce qu'elle renvoie | Utilisée par |
|---|---|---|
| `GET /api/articles` | Liste des articles + nombre de versions | Site |
| `GET /api/articles/{page_id}?as_of=2015-06-01` | L'article tel qu'il était à cette date | Site (machine à remonter le temps) |
| `GET /api/articles/{page_id}/timeline` | Nombre de modifications par mois | Site (frise) |
| `GET /api/cases` | Les cas publiés, triés par impact, **sans nom de compte** | Site (tableau de bord) |
| `GET /api/cases/{rev_id}` | La fiche de preuves complète | Site |
| `GET /api/stats` | Chiffres globaux | Site |
| `GET /api/quality` | La fiabilité : taux sur la fausse campagne, fausses alertes relues, cas rétrogradés par la règle des deux avis, robots officiels écartés, comptes au profil suspect | Site (panneau Detection quality) |
| `GET /api/cases?since=7d` | Les cas trouvés par la veille ces 7 derniers jours | Site (rubrique « New this week ») |

Les formats exacts de chaque réponse sont dans [TECH.md, section 11](TECH.md#11-lapi-du-site--formats-de-réponse-léopold--eléa). La Lens n'appelle **pas** l'API (voir 5, Eléa).

### 4.5 Le fichier `.env` (jamais committé, un `.env.example` sans valeurs est committé)
La liste complète des variables, avec les adresses déjà testées, est dans [TECH.md, section 2](TECH.md#2-variables-denvironnement).

---

## 5. La fiche de chacun

### 🖥️ Léopold — Serveur & base

**Objectif du jour** : à 20h, le site tourne sur le VPS avec tout l'historique et les vrais cas.

1. **(10h30) Premier commit sur `main`** : `.gitignore`, `.env.example`, `docker-compose.yml` (MariaDB `mariadb:lts` + un service `server` en Python/FastAPI), `db/schema.sql`, et un README minimal.
2. **(11h) Le script de chargement** `server/load_versions.py` :
   - il lit un fichier parquet et écrit chaque version dans `article` avec sa **vraie date**, grâce à `SET system_versioning_insert_history = 1` et des colonnes `row_start`/`row_end` remplies à la main ;
   - **la méthode est expliquée dans l'exemple officiel MariaDB** : [mariadb-system-versioning-wikipedia](https://github.com/MariaDB/mariadb-system-versioning-wikipedia) (fichiers `schema.sql` et `load.py`, licence MIT, à créditer) ;
   - testez en local sur `versions-01.parquet`, article 1150 : *as of 2006-01-01* doit renvoyer une version de 2005.
3. **(11h30) Le VPS** :
   - installer Docker ;
   - télécharger les 16 fichiers **directement sur le VPS**, en remplaçant `01` par `02`, `03`… jusqu'à `16` dans l'adresse ;
   - **lancer le chargement de tout en fond**, par exemple `nohup … &`. Ça prend plusieurs heures. **C'est la tâche la plus urgente de la journée.**
4. **(13h30–17h) L'API** (tableau 4.4), puis l'import des fichiers JSONL dans la base.
5. **(17h–20h) Avec Eléa** : le déploiement CRACI. Créez une clé SSH pour CRACI et ajoutez-la au VPS ; ouvrez seulement le port web, **jamais 3306** (MariaDB).
6. **(Bonus, seulement si le rendez-vous de 17h est vert) La veille** `server/watch.py` :
   - **toutes les heures**, il demande à Wikipédia les nouvelles versions des **50 articles surveillés** (les plus sensibles) depuis la dernière version connue (API `action=query&prop=revisions`, User-Agent descriptif) ;
   - **le premier passage** comble le trou depuis le 1er octobre 2026, date de fin des données ;
   - **les nouvelles versions** entrent dans `article` par de **simples `UPDATE`** : MariaDB les date tout seul, l'historique devient « vivant » (bel argument pour le jury MariaDB) ;
   - **elles passent ensuite** dans la même chaîne (tri de Maël → Nemotron → Gemini) et alimentent `GET /api/cases?since=7d` ;
   - **pour le lancer** : une tâche `cron` sur le VPS, ou une tâche programmée CRACI (`on: schedule` dans un workflow) qui lance le script par SSH, ce qui donne à CRACI un rôle de plus.

**Pièges** :
- mettez `SET time_zone = '+00:00'` (Wikipédia est en UTC) ;
- une date seule est refusée dans les requêtes « as of » : écrivez `'2015-06-01 00:00:00'` ;
- prévoyez des lots de versions limités en taille, pas en nombre (les textes sont longs).

**Fini quand** : `GET /api/articles/1150?as_of=2006-01-01` répond sur le VPS.

### 🔍 Maël — Analyse

**Objectif du jour** : à 19h, `analysis.jsonl` contient quelques milliers de cas examinés par Nemotron, **et 2 à 3 cas forts pour la démo sont repérés.**

1. **(10h30) `analysis/find_candidates.py`** : lire les parquet directement (pas besoin de la base) et comparer chaque version à la précédente du même article. On retient :
   - **image** : un `[[Tiedosto:…|légende]]` ajouté, retiré ou dont la légende change. Attention, les légendes peuvent contenir des `[[liens]]` : comptez les crochets ;
   - **sources** : le nombre de `<ref>` diminue. Comptez-les **avant** de nettoyer le texte ;
   - **framing** : les mots surveillés changent, par exemple *vapaussota* / *sisällissota* / *kansalaissota* ;
   - **coordination** (version simple) : un même texte ajouté par plusieurs comptes différents sur plusieurs articles en peu de temps.

   On ignore les annulations (`sha1` déjà vu dans l'article) et les modifications mineures. Résultat : `data/exchange/candidates.jsonl`.
2. **(12h) Récupérer les miniatures** des images avec l'API Wikipédia (`prop=imageinfo&iiprop=url|extmetadata&iiurlwidth=800`), par lots de 50 maximum, avec un **User-Agent descriptif**, sinon erreur 429. On garde l'auteur et la licence.
3. **(12h30) `analysis/run_nemotron.py`** : pour chaque candidat, appeler Nemotron (adresse et modèle dans `.env`) avec le texte avant/après et, s'il y a une image, `{"type": "image_url", "image_url": {"url": thumb_url}}`. Demandez une réponse en JSON. Résultat : `analysis.jsonl`.
   - Reprenez le script du test d'hier soir qui a marché.
   - **Priorisez** : d'abord les changements de légende et l'article 1150, puis le reste. Ne lancez pas 100 000 appels.
   - Écrivez chaque résultat dès qu'il arrive : si le script plante, on ne perd rien.
4. **(15h–19h) Chercher les cas de démo** : parcourez les résultats « suspects » et notez les 2 ou 3 plus parlants. **C'est le plus important de la journée pour le pitch.**

**Pièges** :
- demandez à Verda (Discord) la limite d'appels ;
- pas plus de 2 à 4 appels en parallèle sans leur accord ;
- la réponse peut contenir du « raisonnement » avant le JSON : ne gardez que le JSON.

**Fini quand** : `analysis.jsonl` existe pour l'article 1150 avec au moins un vrai cas d'image.

### ⚖️ Nathanaël — Décision & preuves

**Objectif du jour** : à 20h, chaque cas a une décision, un résumé anglais, un score d'exposition, et on a **le chiffre de fiabilité**.

1. **(10h30) Faux `analysis.jsonl`** : écrivez 10 lignes à la main au format 4.2, pour avancer sans attendre Maël.
2. **(11h) `decision/decide.py`** : pour chaque ligne, appeler Gemini (format compatible OpenAI, `.env`), qui renvoie `decision`, `confidence`, `publish`, `headline_en`, `summary_en`.
   - Appliquez **la règle des deux avis** (4.3).
   - Une réponse bizarre de Gemini donne `human_review`.
   - **Économie** : Gemini seulement sur les cas où Nemotron dit « suspect », plus un petit échantillon des autres.
2 bis. **(12h) `decision/accounts.py`, le profil des comptes** (c'est notre réponse au mot « bots » du challenge Hostinger). À partir des fichiers de données, sans IA, pour chaque compte :
   - **robot officiel** : le nom finit par « Bot » ou figure dans la liste des robots de Wikipédia finnoise → `declared_bot`, **bénin, écarté** (exemple vu vendredi : *ZacheBot*) ;
   - **rythme de robot** : beaucoup de modifications en rafale, à intervalles très réguliers ;
   - **compte jetable** : créé, actif quelques jours sur plusieurs articles sensibles, puis disparu ;
   - **compte à sujet unique** : ne touche qu'un thème ;
   - **taux d'annulation** : part de ses modifications défaites par d'autres comptes (même `sha1` qu'une version antérieure juste après lui).

   Chaque compte suspect a des `reasons` lisibles. Résultat : `accounts.jsonl` (format 4.3 bis), à donner à Maël dès que possible.
3. **(13h) `decision/exposure.py`** : pour chaque cas, calculer :
   - **la durée en ligne** : de la version suspecte jusqu'à la première version suivante où le contenu a disparu, ou `null` s'il est toujours là ;
   - **les lecteurs estimés** : somme des vues par jour sur cette période, avec l'API d'audience (`https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/fi.wikipedia/all-access/user/<Titre>/daily/<AAAAMMJJ>/<AAAAMMJJ>`). Utilisez le titre de l'époque. Pas de données avant juillet 2015.
4. **(16h–20h) La fiabilité** :
   - **Fausse campagne, clairement étiquetée** : inventez par exemple 10 fausses modifications (3 faux comptes, même message sur plusieurs articles, + 3 légendes trompeuses). Passez-les dans toute la chaîne et comptez combien sont attrapées.
   - **Fausses alertes** : relisez 20 cas « flag » réels et notez combien sont justes.
   - Gardez un **journal** « consigne v1 → v2 → résultat » : NVIDIA l'exige dans la soumission.

**Pièges** : ne mettez **aucun nom de compte** dans `summary_en` ; la fausse campagne **ne doit jamais** apparaître sur le site public.

**Fini quand** : `decisions.jsonl` existe pour les cas de Maël, avec l'exposition.

### 🎨 Eléa — Site, Lens & pitch

**Objectif du jour** : à 20h, le site est en ligne avec de vrais cas ; à 1h, la Lens marche sur l'article de 1918.

1. **(10h30) Le site avec de fausses données** dans `web/`. Une page simple en HTML/CSS/JS, sans framework si vous débutez. **En anglais**, avec :
   - **l'accueil** : les chiffres (`/api/stats`) et la liste des cas publiés, triés par impact ;
   - **la fiche d'un cas** : titre, résumé, image avec auteur et licence, ancienne/nouvelle légende, « online for N days, seen by ≈ X readers », liens vers Wikipédia (`https://fi.wikipedia.org/?oldid=<rev_id>`) ;
   - **la machine à remonter le temps** : choisir une date → voir l'article à cette date, avec la frise des modifications ;
   - **le panneau « Detection quality »** (`/api/quality`) : **c'est ce que le jury Hostinger regarde en premier**. Il affiche le taux de détection de la fausse campagne, les fausses alertes relues, les cas rétrogradés par la règle des deux avis, les robots officiels écartés et les comptes au profil suspect, avec une phrase sur chaque chiffre ;
   - **la rubrique « New this week »** (`/api/cases?since=7d`), seulement si la veille de Léopold tourne.

   En attendant l'API de Léopold, lisez des fichiers `web/mock/cases.json` et `web/mock/quality.json` au même format.
2. **(13h) La TimeProof Lens** dans `lens/` : un **favori JavaScript** (*bookmarklet*). Cliqué sur une page `fi.wikipedia.org`, il **surligne** les passages et images concernés. Au survol, il affiche l'historique (« réécrit 7 fois depuis 2009 ») et un lien vers la fiche.
   - **Les données sont intégrées dans le favori, sans aucun appel à notre serveur** : Wikipédia est en HTTPS et notre VPS en HTTP, donc le navigateur bloquerait l'appel.
   - On ne le fait que pour les 2-3 articles de la démo. Méthode : [TECH.md, section 12](TECH.md#12-la-lens-eléa).
3. **(17h–20h) Avec Léopold** : le fichier `.github/workflows/deploy.yml` avec `runs-on: craci`. À chaque push sur `main`, CRACI vérifie et déploie sur le VPS. Branchez d'abord le dépôt à CRACI (platform.craci.com, avec le code d'invitation).
4. **(21h–1h)** Finitions, puis préparation de la vidéo : plan des 2 minutes, captures d'écran.

**Pièges** : aucun nom de compte dans les pages publiques ; une image Wikimedia sans auteur ni licence n'a pas le droit d'être affichée.

**Fini quand** : l'URL du VPS montre un vrai cas avec son score d'exposition.

---

## 6. La journée

| Heure | Tout le monde |
|---|---|
| **10h00–10h30** | Démarrage (section 2) |
| 10h30–13h30 | Chacun dans son dossier, avec des données d'exemple |
| **13h30** | **Rendez-vous 1** (15 min) : merge dans `main` ; **un cas de bout en bout** (Maël → Nathanaël → Léopold → Eléa) sur l'article 1150 |
| 13h30–17h | Vraies données ; Léopold vérifie que le chargement avance |
| **17h** | **Rendez-vous 2** : merge ; qu'est-ce qui bloque ? Couper si besoin |
| 17h–21h | Analyse sur tous les candidats retenus ; site en ligne |
| **21h** | **Rendez-vous 3** : le site montre de vrais cas en ligne ? Choix des 2-3 cas de démo |
| 21h–1h | Fiabilité, Lens, finitions |
| **1h** | **Rendez-vous 4** : dernier merge. **2h : on n'ajoute plus rien** |
| Dimanche 6h–9h30 | Vidéo (≤ 2 min), textes de soumission, **soumettre avant 9h30** |
| **Dimanche 10h30** | Relecture entre équipes : **présence obligatoire** |

**Si on est en retard, on coupe dans cet ordre** : veille → vue en transparence → coordination → Lens réduite à l'article 1150 → images réduites aux seules légendes.
**Le profil des comptes et le panneau Detection quality ne se coupent pas** : c'est notre dossier Hostinger.
**On ne coupe jamais** : l'historique en ligne, l'analyse par Nemotron, la règle des deux avis, la fiche de cas avec l'exposition, le chiffre de fiabilité.

---

## 7. Règles d'or

1. **Petit et qui marche** plutôt que gros et à moitié fini. Un cas parfait vaut mieux que 1 000 cas moyens.
2. **On ne reste pas bloqué plus de 20 minutes** : on demande à l'IA, puis à l'équipe.
3. **Pas de clé, pas de mot de passe, pas de données dans Git.**
4. **Aucun nom de compte Wikipédia en public, aucune « découverte » inventée.**
5. **Heure d'Helsinki**, celle des téléphones.
6. **Mangez et dormez un peu** : un débutant fatigué casse `main` à 4h du matin.
