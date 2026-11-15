# TimeProof — fiche résumé (équipe ENLMe)

> Junction 2026 · vendredi 13/11, soir · **table A6** · **heures = heure d'Helsinki** (celle de vos téléphones) · pré-soumission ✅ faite

## L'idée en une phrase

**TimeProof montre qui réécrit l'histoire sur Wikipédia, quand et comment, et ne publie que ce qu'il peut prouver.**
Données : 862 076 versions de 19 742 articles finnois sur l'histoire de la Finlande (2003 → 2026), fournies par MariaDB, plus les nouvelles versions que la veille en direct ajoute depuis le 14/11.

> **Mise à jour du dimanche 15/11** : ce qui suit est le plan de vendredi. Depuis, se sont ajoutés la **veille en direct** (Hermes Agent sur le VPS Hostinger : contrôle des modifications récentes toutes les 10 minutes, bureau de relecture sur le salon Discord privé, point horaire, voir `hermes/README.md`), les **preuves visuelles Cloudinary** (copie archivée des images de cas, vue avant / après) et la page **Accounts** (profils de comptes par code anonyme). Le déploiement CRACI part de la branche `Deploy`.

## Ce qu'on garde

| Brique | Rôle | Challenge |
|---|---|---|
| **MariaDB** | Chaque version stockée avec sa **vraie date** (tables historisées) → « l'article tel qu'il était le 01/06/2015 » | **Principal** |
| **Hostinger** (VPS) | Le site en ligne : tableau de bord public (anglais) + file de relecture privée | Principal *(si on peut en choisir 2)* |
| **Nemotron** (serveur fourni par l'événement, hébergé chez Verda ; adresse `https://containers.datacrunch.io/nemotron-3-5-super-vl-b300/v1`, modèle `nemotron-3.5-super-vl`, clé `VERDA_INFERENCE_KEY`) | L'**enquêteur** : lit la modification **et regarde l'image** quand une photo ou sa légende change | Tech NVIDIA |
| **Gemini** | Le **décideur** et l'éditeur : signaler ou non, publier ou non, résumé en anglais | Tech Gemini (4 000 €) |
| **CRACI** | Remplace les **machines de GitHub Actions** : chaque push sur `main` est construit et déployé sur le VPS par CRACI (`runs-on: craci`). Le code reste hébergé sur GitHub. Bonus : afficher la liste des dépendances (SBOM) sur le site | Tech CRACI |

**5 signaux** : dérive du vocabulaire · image ou légende trompeuse · sources retirées · campagne coordonnée (textes quasi identiques, sans GPU) · **profil des comptes** (rythme de robot, comptes jetables, sujet unique, taux d'annulation ; les robots officiels de Wikipédia sont écartés comme bénins).
**La veille** (bonus) : toutes les heures, les nouvelles modifications de 50 articles sensibles passent dans la même chaîne → rubrique « New this week ».
**Le panneau « Detection quality »** : fiabilité, fausses alertes, cas rétrogradés, robots écartés. C'est ce que le jury Hostinger regarde.
**Le plus** : le **score d'exposition**, c'est-à-dire combien de jours la version trompeuse est restée en ligne et combien de lecteurs l'ont vue (≈, via l'API d'audience Wikimedia).
**La TimeProof Lens** : un favori à cliquer sur la **vraie page Wikipédia**, qui surligne les passages et images réécrits, avec leur historique et leur exposition au survol. C'est le moment « waouh » de la démo (seulement pour les articles de la démo).
**Garde-fous** : un cas n'est signalé que si les **2 IA sont d'accord**, sinon un humain tranche. **Aucun nom de compte en public.**

**Retiré** : le prix Verda et tout GPU Verda à gérer nous-mêmes (on se contente du serveur Nemotron fourni), questions multilingues (RAG), vecteurs, Arduino. *(La surveillance en direct, retirée vendredi, a finalement été faite samedi soir avec Hermes.)*

## Qui fait quoi

| Personne | Module | Livre |
|---|---|---|
| **Léopold** | **Serveur & base** | VPS + MariaDB, chargement de l'historique, API, import des résultats, déploiement CRACI (avec Eléa), **veille** (bonus) |
| **Maël** | **Analyse** | Tri des modifications suspectes (texte, images, sources), appels Nemotron (texte + image), **les 2-3 cas de démo** |
| **Nathanaël** | **Décision & preuves** | Gemini décideur + éditeur, garde-fou, **profil des comptes**, score d'exposition, **chiffre de fiabilité** (fausse campagne étiquetée) |
| **Eléa** | **Site, Lens & pitch** | Tableau de bord, panneau **Detection quality**, fiche de cas, machine à remonter le temps, **TimeProof Lens**, déploiement CRACI, vidéo 2 min |

Détails, Git et contrat entre les morceaux : [TIMEPROOF-PLAN-SAMEDI.md](TIMEPROOF-PLAN-SAMEDI.md).

## Analyse : est-ce que ça tient ?

**Adéquation aux challenges**
- ✅ **MariaDB** : leurs données, leur fonction phare (l'historique), utilisée de façon créative (durée d'exposition, verdicts eux-mêmes historisés). Grille : la piste historique **seule** suffit (« RAG et/ou historique »).
- ✅ **Hostinger** (« détecter propagande, bots et acteurs malveillants, en ligne sur Hostinger ») : propagande (dérive, images, sources), comportement coordonné, **bots et comptes suspects** (profil des comptes), service de **surveillance** (veille), honnêteté sur les fausses alertes (panneau Detection quality). ⚠️ Le formulaire n'a accepté **qu'un** challenge principal : demander à l'accueil si on peut ajouter *Decode the Noise*.
- ✅ **NVIDIA** : usage texte **+ image**, qu'un modèle texte seul ne peut pas faire. ⚠️ Il faut joindre un texte expliquant comment on a amélioré ses réponses.
- 🟡 **Gemini** : rôle réel (décider, publier) mais classique. Le soigner dans le pitch.

**Ce qui nous démarque** : ① une vraie histoire finlandaise dans le temps (1918 : « guerre de libération » contre « guerre civile ») ; ② des preuves, pas des accusations, avec un chiffre de fiabilité mesuré ; ③ l'enquête sur les images ; ④ le score d'exposition.

**Faisabilité** : réaliste à 4 en 34 h **si** on s'en tient au périmètre ci-dessus.
- **Déjà prouvé ce soir** : charger l'historique avec les vraies dates fonctionne (3 357 versions en 61 s). L'image change dans 5 771 versions sur 103 607 de l'échantillon, donc la matière existe. L'API d'audience répond.
- **Testé vendredi soir** : Nemotron comprend le finnois (il a repéré le passage de « guerre civile » à « guerre de libération ») et lit les images (il a démasqué une fausse légende), en 1 à 2 s par appel. Un seul exemple de chaque.
- **Non prouvé** : le temps de chargement de tout l'historique (estimé à plusieurs heures), et la limite de débit du serveur Nemotron (à demander à Verda).

## Ordre des actions

**Ce soir**
1. **Pré-soumission avant 23h55** (textes prêts, voir le chat)
2. ~~Tester Nemotron : 1 texte finnois + 1 image~~ ✅ fait, ça marche
3. Commander le VPS Hostinger **KVM 2** (8 Go de RAM, 100 Go de disque) et récupérer le code d'invitation CRACI (Discord `#craci` ou leur stand)
4. Répartir A / B / C / D

**Samedi**

| Heure | Quoi |
|---|---|
| 9h00 | 15 min ensemble : formats des tables partagés, branches git |
| 9h–13h | A : VPS + MariaDB + chargement **lancé en fond** · B : tri + Nemotron · C : Gemini sur données simulées · D : site sur données simulées |
| **13h** | **Jalon 1 : un cas de bout en bout avec les vraies IA** |
| 13h–20h | Analyse de tous les candidats retenus, score d'exposition, site sur vraies données |
| **20h** | **Jalon 2 : le tableau de bord montre de vrais cas** |
| 20h–2h | Fiabilité (fausse campagne), choix des cas de démo, finitions |
| **Dim 2h** | **On n'ajoute plus rien** |
| Dim 6h–9h30 | Vidéo 2 min, textes, **soumission avant 9h30** (limite 10h) |
| **Dim 10h30** | **Relecture entre équipes : présence obligatoire** |

**Si on est en retard, on coupe dans cet ordre** : badge SBOM CRACI (le déploiement CRACI, lui, reste) → veille → vue en transparence (ancien texte sous le nouveau) → coordination → Lens réduite au seul article de 1918 → images réduites aux seules légendes.

## Attention à

- **Heure d'Helsinki partout** : se fier aux téléphones, pas à l'horloge des PC (au moins un est mal réglé).
- **Serveur Nemotron partagé** : il peut ralentir ou tomber, et il sera sans doute coupé après l'événement. On analyse donc les cas **à l'avance** et on stocke les résultats ; en secours, une clé `nvapi-` de build.nvidia.com (≈ 40 appels/min).
- **Finnois** : bon sur notre test. Si des cas se passent mal, on ajoute une traduction anglaise à côté du texte original.
- **Jamais de « découverte » inventée** dans le pitch ; la fausse campagne de test est **étiquetée** et séparée.
- **Pas de noms de comptes** sur le site public ; images affichées avec **auteur et licence** ; textes Wikipédia sous **CC BY-SA**.
- **Clés API dans `.env`**, jamais dans git. API NVIDIA ≈ 40 requêtes/min **par clé** → une clé par personne.
- **Audience Wikimedia seulement depuis juillet 2015** ; le score de lecteurs est un **plafond (≈)**.
- **Vidéo ≤ 2 minutes**, publique ; dépôt de code public ; **URL du site** qui marche pendant le jugement.
