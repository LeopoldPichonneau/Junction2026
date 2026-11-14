# decision/ — Décision & preuves (Nathanaël)

Tous les scripts se lancent **depuis la racine du dépôt**, avec Python 3.12 et `pip install pyarrow httpx`.
Ils lisent `.env` à la racine. Avec `USE_MOCK=true` (valeur par défaut si `.env` n'existe pas), aucune clé n'est
nécessaire et les sorties vont dans des fichiers `*.mock.jsonl`, pour ne jamais se faire passer pour de vraies données.
**Pour les vrais fichiers que les autres attendent, il faut `USE_MOCK=false` dans `.env`** (+ `GEMINI_API_KEY`, `GEMINI_MODEL`),
et les 16 fichiers `data/versions-XX.parquet` (avec un seul, on ne couvre que 281 articles).

| Ordre | Commande | Lit | Écrit (dans `data/exchange/`) |
|---|---|---|---|
| 1 | `python decision/accounts.py` | `data/versions-*.parquet` | `accounts.jsonl` (format 4.3 bis) + `accounts_summary.json` → **à donner à Maël** |
| 2 | `python decision/decide.py` | `analysis.jsonl` (Maël) | `decisions.jsonl` (format 4.3) |
| 3 | `python decision/exposure.py` (peut tourner **avant** Nemotron : il prend `candidates.jsonl` si `analysis.jsonl` n'existe pas encore) | les cas, parquet, API d'audience | `exposure.jsonl` (gardé d'une fois sur l'autre : seuls les nouveaux cas sont calculés) ; après `decide.py` : `python decision/exposure.py --merge-only` ajoute `exposure` dans `decisions.jsonl` |
| 4 | `python decision/quality.py campaign` | `candidates.jsonl` (vraies photos d'articles différents) | `synthetic_candidates.jsonl` (10 textes + 3 légendes trompeuses) → **à donner à Maël** |
| 5 | `python decision/quality.py review-sheet` | `decisions.jsonl` | `data/manual_review.csv` (20 cas à relire à la main) |
| 6 | `python decision/quality.py report` | tout ce qui précède | `quality.json` (servi tel quel par l'API) |

Essai sans attendre Maël : `python decision/decide.py --input decision/sample/analysis.sample.jsonl`
(10 lignes écrites à la main, `rev_id` 1 à 10, marquées `sample`). Toute entrée autre que `analysis.jsonl` écrit dans
`decisions.test.jsonl`, jamais dans le fichier importé par Léopold, et une ligne `sample` n'est jamais publiée.

**Règle des deux avis (dans le code)** : `flag` seulement si Nemotron dit `suspicious: true` **et** Gemini dit `flag` ;
`dismiss` si les deux disent non ; sinon `human_review` (désaccord, avis manquant, réponse bizarre).
`publish` n'est possible que pour un `flag`, et jamais pour la campagne `synthetic`.
Les cas non suspects reçoivent `dismiss` par règle (`decided_by: "rule"`), sauf un échantillon (5 %) envoyé à Gemini
pour mesurer les désaccords. Une erreur réseau n'écrit rien : relancer reprend là où on s'était arrêté.

**Champs ajoutés au format 4.3** (à signaler à Léopold pour l'import) : `page_id`, `title`, `kind`, `synthetic`,
`signal_type`, `explanation`, `decided_by`, `decider_model`, `prompt_version`, `nemotron_suspicious`,
`gemini_decision`, `disagreement`, et dans `exposure` : `still_online`, `readers_partial`, `ended_by`, `tracked_by`, `titles`.
`tracked_by: "revert only"` = notre parseur ne voit pas le changement (ex. image dans une infobox) : seule une annulation
termine le cas, la durée et les lecteurs peuvent être surestimés. **Ne pas mettre un tel cas en avant dans la démo.**

**Fin d'un cas (exposition)** : la première version suivante qui revient au texte d'avant (même `sha1`), ou où le contenu
suspect a disparu (légende/fichier pour une image, nombre de `<ref>` revenu pour les sources, moins de la moitié des mots
introduits pour le texte), en se basant sur la version suspecte elle-même. Sinon « toujours en ligne » jusqu'au 01/10/2026 (fin des données). Les lecteurs sont un
**plafond** (vues de tout l'article), comptés avec le titre de chaque période, `null` avant juillet 2015.

**Campagne de test** : `synthetic: true` est la seule étiquette. `decide.py` la retire avant d'appeler Gemini ;
Maël doit faire de même avant Nemotron, sinon le test se note lui-même.

À remplir par l'équipe, jamais inventé : `data/manual_review.csv` et `decision/PROMPT-LOG.md`.
