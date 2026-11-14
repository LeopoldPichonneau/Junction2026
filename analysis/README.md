# analysis/ — Analyse (Maël)

Trouver les modifications suspectes dans l'historique de Wikipédia finnoise, récupérer les images concernées,
puis les faire examiner par Nemotron. Tout se lance **depuis la racine du dépôt**, avec Python 3.12 et
`python -m pip install pyarrow httpx`. Les scripts lisent `.env` à la racine (clé Verda, adresse, User-Agent).

## Les commandes, dans l'ordre

| Ordre | Commande | Lit | Écrit (dans `data/exchange/`) | Durée (fichier 01) |
|---|---|---|---|---|
| 1 | `python analysis/find_candidates.py data/versions-01.parquet` | parquet | `candidates.jsonl` (format 4.1) | ≈ 4-5 min |
| 2 | `python analysis/fetch_images.py` | `candidates.jsonl` | `images.jsonl` + remplit `thumb_url`, `author`, `license` dans `candidates.jsonl` | ≈ 1 min |
| 3 | `python analysis/run_nemotron.py --limit 10` | `candidates.jsonl` | `analysis.jsonl` (format 4.2) | 1-3 s par cas |
| 4 | `python analysis/insights.py data/versions-01.parquet` | `analysis.jsonl` + parquet | `insights.json` (durée en ligne selon l'attention portée à l'article, comptes récidivistes, comptes neufs, robots écartés) + `case-durations.jsonl` (un cas suspect par ligne) | ≈ 3-5 min |
| 5 | `python analysis/term_timeline.py data/versions-01.parquet` | parquet | `term-timeline.json` : mois par mois, les noms de la guerre de 1918 (neutres / camp blanc / camp rouge) dans l'article 1150 et dans tous les articles | ≈ 1 min |
| 6 | `python analysis/still_online.py data/versions-01.parquet` | parquet | `still-online.json` : les termes partisans encore présents dans la dernière version de chaque article, avec leur phrase et depuis quand (liste **à relire**, beaucoup d'usages sont légitimes : titres de livres, citations) | ≈ 1 min |
| 7 | `python analysis/cloudinary_cards.py --archive` (clés Cloudinary dans `.env`) | `candidates.jsonl`, `decisions.jsonl`, `images.jsonl`, `data/versions-*.parquet` | `cloudinary.jsonl` : pour chaque cas d'image publié, l'image de l'époque (et, si elle a été remplacée, celle d'avant) envoyée à Cloudinary avec ses preuves en métadonnées (`rev_id`, article, date, côté, légende, auteur, licence) et son empreinte `phash`. Les réglages communs sont dans le preset `timeproof-evidence` | 1 min |
| 7 bis | `python analysis/cloudinary_cards.py --compare` (aucun fichier envoyé : le nom du cloud suffit) | `analysis/demo_cases.json`, `candidates.jsonl`, `decisions.jsonl`, `cloudinary.jsonl` | une ligne par cas d'image archivé qui a une image avant et une image après : `before_url` / `after_url` (les deux côtés du curseur, à la même taille et au même cadrage, avec la légende de l'époque), `archived_url`, `author`, `license` | < 1 min |
| 8 | `python analysis/english_titles.py data/versions-*.parquet` | les fichiers parquet | `titles-en.jsonl` : le titre anglais de chaque article qui a un équivalent sur Wikipédia en anglais (liens interlangues de Wikipédia, jamais de traduction automatique). Sert à chercher un article en anglais dans la Time machine | 10 min |
| — | `python analysis/check_nemotron.py` | `.env` | rien : dit si le serveur Nemotron répond | < 10 min |

- Plusieurs fichiers d'un coup : `python analysis/find_candidates.py data/versions-01.parquet data/versions-02.parquet …`
- Un seul article pour tester : `--page-id 1150` (étapes 1 et 2), `--rev-id 24234965` (étape 3).
- **Les fichiers de `data/` ne sont jamais dans Git** : chacun les régénère avec ces commandes (ou les reçoit par Discord).

## Mode simulé

Avec `USE_MOCK=true` dans `.env`, aucune requête n'est envoyée : `fetch_images.py` écrit `images-mock.jsonl` sans toucher
`candidates.jsonl`, et `run_nemotron.py` écrit `analysis-mock.jsonl`. Les fausses données ne se mélangent jamais aux vraies.

## Ce que fait chaque étape

**1. `find_candidates.py`** compare chaque version d'un article à la précédente.
- Ignore : la création de l'article, les annulations (même `sha1` qu'une version antérieure), les modifications
  sans changement, les modifications mineures et les robots déclarés (nom finissant par « bot »). Elles servent quand même
  de « version précédente » pour la comparaison suivante.
- `kind` (une seule ligne par `rev_id`, le signal le plus fort gagne) : `image` si une légende change ou une image est
  remplacée → `sources` si le nombre de `<ref>` baisse → `framing` si les mots surveillés de 1918 changent
  (vapaussota, sisällissota, kansalaissota, luokkasota, punakapina, veljessota, toutes déclinaisons) → `image` pour une
  image ajoutée ou retirée. `image` et `refs_removed` sont remplis dès qu'ils existent, quel que soit `kind`.
- Légendes : découpage aux `|` hors des `[[liens]]`, options d'affichage écartées (`thumb`, `pienoiskuva`, `250px`…),
  changements de ponctuation, de majuscules ou d'espaces ignorés. Seul le texte **affiché sous l'image** compte
  (avec `thumb`, `frame`, `pienoiskuva`…) : sans ces options, c'est un simple texte de survol.
- `added` / `removed` : les mots changés, paragraphe par paragraphe, passages séparés par « … », coupés à 1 500 caractères.
- `account_hash` = `sha256(user)[:16]`, même formule que `decision/`. Les noms de compte et adresses IP sont aussi retirés
  du champ `comment`.
- `user_is_new` = la modification a lieu moins de 7 jours après la première modification de ce compte **dans les fichiers
  donnés en entrée** (pas la vraie date de création du compte). Toujours `false` pour une IP ou un compte temporaire.
- Pas encore fait : la coordination (même texte poussé par plusieurs comptes sur plusieurs articles).

**2. `fetch_images.py`** demande à l'API de Wikipédia (lots de 50, User-Agent du `.env`) la miniature (800 px), l'auteur
et la licence de chaque image. Les fichiers déjà dans `images.jsonl` ne sont pas redemandés. Si l'auteur manque
(fréquent pour les vieilles photos du domaine public), on prend le champ « Credit ».
Un même nom de fichier peut montrer aujourd'hui une autre image qu'à l'époque (nouvelle version, ou fichier local
supprimé puis remplacé par un fichier Commons du même nom) : on garde toutes les versions, et chaque candidat reçoit
la miniature de **la version en ligne le jour de la modification** (`image.version_timestamp`). S'il n'y en avait pas
encore, `thumb_url`, `author` et `license` valent `null` : ni le site ni Nemotron ne doivent montrer l'image d'aujourd'hui.

**3. `run_nemotron.py`** envoie chaque candidat à Nemotron (texte + miniature s'il y en a une). Ordre : légendes
modifiées, images remplacées, sources, framing, images ajoutées/retirées ; l'article 1150 d'abord dans chaque groupe.
`--limit` est obligatoire (pas de lancement massif par erreur), 2 appels en parallèle par défaut, 4 au maximum
(serveur partagé). Chaque réponse est écrite dès qu'elle arrive ; au redémarrage, les `rev_id` déjà présents sont sautés.
Le script s'arrête après 10 échecs de suite. Les miniatures sont téléchargées par le script et envoyées
**dans le message** : quand le serveur allait les chercher lui-même chez Wikimedia, la moitié des appels avec image
échouaient (`NEMOTRON_IMAGE_AS_DATA=false` dans `.env` pour revenir aux liens). Consigne actuelle : v4 (le vandalisme
évident n'est pas « suspect »), voir `PROMPT-LOG.md`. `synthetic`, `account_hash` et les identifiants ne sont pas envoyés au modèle.

## Champs ajoutés aux formats (à signaler à Léopold pour l'import)

- `candidates.jsonl`, dans `image` : `author`, `license`, `version_timestamp` (remplis par l'étape 2 ; le site en a besoin).
- `analysis.jsonl`, dans `nemotron` : `model` (colonne `model` de la table `analysis`) et `seconds` (durée de l'appel).
- Nouveau fichier `images.jsonl` : `file`, `found`, `thumb_url`, `versions` (date + miniature de chaque version),
  `description_url` (page Commons), `author`, `credit`, `license`, `license_url`.
- Limite connue : pour une image `replaced`, seul le **nouveau** fichier est gardé (`file`).

## État au samedi 14/11, 13h30 (heure d'Helsinki)

- Étapes 1 et 2 faites sur le fichier 01 : 5 658 candidats (3 661 image, 1 519 sources, 478 framing), 1 872 images
  trouvées sur 2 312 (les autres ont été supprimées de Wikipédia) ; 3 103 candidats ont la miniature de l'époque.
- Étape 3 prête et testée en mode simulé, pas encore lancée en vrai. **Le serveur Nemotron est très lent** : vers 14h15,
  1 appel a mis 219 s, puis 22 à 27 s par appel (contre 1-2 s vendredi). Il n'est pas en panne, il est chargé : les scripts
  attendent maintenant jusqu'à 5 min. À ce rythme, ≈ 2 à 3 cas par minute avec 2 appels en parallèle : il faut bien
  choisir les cas (`--limit`, ordre de priorité), pas tout envoyer.
- Sans clé ou avec une fausse clé, le serveur répond tout de suite « 404 page not found » : ce n'est **pas** le signe
  d'une panne, seulement d'une clé absente. Nos réglages sont identiques à la configuration officielle (adresse, modèle, clé).
- Un cas réel repéré (pas encore examiné par Nemotron) : rev 24234965 du 12/09/2026, article 1150, « Sisällissota »
  remplacé par « Vapaussota » à plusieurs endroits, dont la première phrase ; défait par la modification suivante.
- Secours prévu mais non utilisé (pas de clé) : `NEMOTRON_PROVIDER=nvidia` + `NVIDIA_API_KEY` dans `.env`
  (adresse et modèle de `docs/TECH.md`, section 2, limités à 35 appels/min).
- Sous Windows sans base de fuseaux horaires, `to_pylist()` sur une colonne `timestamp` avec fuseau plante
  (« zoneinfo module or pytz package must be installed ») : `find_candidates.py` convertit les dates en UTC sans fuseau.
