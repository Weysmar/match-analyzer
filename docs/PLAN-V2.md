# Plan d'implémentation V2 : différenciation, vue 2D et seuils

> **Statut : validé par Vincent le 2026-11-08. Étape 10 close le 2026-11-08 (`spikes/s10-v2/RAPPORT.md`) ; DV1 à DV7 tranchées par Vincent le même jour, telles que recommandées (section 2). DV3 reste sous réserve du test du lecteur sur téléphone. Étape 11 en cours : T11.1 et T11.2 sur la branche `feat/parser-touches`.**
> Périmètre : section 9 de `CLAUDE.md` (« V2, différenciation »), sur la base de la V1 livrée (étapes 0 à 8, `docs/PLAN.md`). L'étape 9 (production) se termine en parallèle : la V2 n'en dépend pas, sauf pour sa mise en ligne.
> Mêmes conventions que le plan V1 (section 5) : tâches d'une demi-journée au plus, une « fin » vérifiable par tâche, 👤 pour ce qui demande ton action ou ton accord.

## Sommaire

1. [Objectif et principe](#1-objectif-et-principe)
2. [À trancher avant de commencer](#2-à-trancher-avant-de-commencer)
3. [Ce qui existe déjà](#3-ce-qui-existe-déjà)
4. [Les seuils : règles communes](#4-les-seuils--règles-communes)
5. [Définitions des fonctionnalités](#5-définitions-des-fonctionnalités)
6. [Étape 10 : vérification technique](#étape-10--vérification-technique-spike)
7. [Étapes 11 à 17](#étape-11--touches-et-possession)
8. [Annexe F : base de données](#annexe-f--base-de-données)
9. [Annexe G : contrats d'API](#annexe-g--contrats-dapi)
10. [Annexe H : hors périmètre V2](#annexe-h--hors-périmètre-v2)

---

## 1. Objectif et principe

La V1 répond à « combien » : boost, vitesse, temps par zone. La V2 doit répondre à **« pourquoi »** : pourquoi un but a été encaissé, où la rotation casse, qui gagne les kickoffs et les duels. Trois blocs :

1. **Différenciation** : touches de balle, possession, kickoffs, duels, rôles de rotation, double commits, overcommits, contexte des buts encaissés.
2. **Vue 2D** : revoir chaque situation sur un terrain vu de dessus, depuis des temps cliquables.
3. **Seuils** : chaque détection repose sur des seuils écrits, sourcés, calibrés sur tes replays et versionnés.

**Principe directeur : des faits, pas des opinions.** Une situation n'est affichée que si sa définition tient en une phrase, qu'elle est testée sur des données synthétiques et que sa précision est mesurée sur des situations que tu as vérifiées à l'œil. Pas de note globale, pas de conseil rédigé (V4).

**Critère de fin de la V2** : sur tes replays, chaque détecteur affiché atteint la précision cible de la section 4 (sinon il est marqué « indicatif » ou retiré). Le parcours E2E couvre la vue 2D depuis un but encaissé. Les seuils sont figés dans une version d'analyse.

---

## 2. À trancher avant de commencer

L'étape 10 mesure, puis tu décides. Les recommandations ci-dessous sont celles que je défendrai si les mesures les confirment.

**Décisions prises le 2026-11-08, après l'étape 10 : DV1 à DV7 suivent la recommandation du rapport.** Elles changent le plan sur ces points :

| #   | Décision | Effet sur le plan |
| --- | -------- | ----------------- |
| DV1 | Touches détectées par `subtr-actor`, émises par `rl-parse` | T11.1 tel quel. Le buteur a touché la balle dans 98,6 % des buts du corpus, contre 95,0 % en Python. |
| DV2 | Document de la vue 2D à **15 Hz**, stocké dans le S3 | Budget révisé : **environ 35 Ko par minute de jeu** au lieu de 300 Ko par match (le match de 38 minutes du corpus pèse 1,4 Mo). Codage en différences à essayer à T12.1. |
| DV3 | Canvas | Sous réserve du nombre d'images par seconde sur ton téléphone (T10.5) ; repli SVG sinon. |
| DV4 | Mode étiquetage en développement, export JSON | Inchangé |
| DV5 | Pas de rotations en 1v1 | Inchangé |
| DV6 | Émission des touches au plus tôt | T11.1 passe en tête de la V2, à livrer avant ou juste après la mise en production de la V1. |
| DV7 | `rl-parse` émet aussi **kickoffs, duels et « devancé sur la balle »** (détecteurs de `subtr-actor`) ; possession, rôles, double commits et overcommits restent **calculés en Python** depuis les touches et les frames | T11.1 couvre les quatre flux. L'étape 13 lit les kickoffs et les duels dans `events.json` au lieu de les détecter, puis calcule ses métriques et ses situations. Les sorties de `subtr-actor` pour possession et rotation servent de référence de comparaison (`rl-oracle`). |

| #   | Décision | Recommandation | L'autre option |
| --- | -------- | -------------- | -------------- |
| DV1 | **D'où viennent les touches de balle ?** Le replay ne les enregistre pas : il faut les déduire. | **Les détecteurs de `subtr-actor`**, appelés depuis `rl-parse`, qui écrit les touches dans `events.json`. Ils combinent le marqueur répliqué `Ball_TA:HitTeamNum` (quelle équipe a touché), la déviation de trajectoire de la balle et la géométrie de contact. Ce travail de réglage serait long à refaire. Condition : coût mesuré à l'étape 10 compatible avec la limite du bac à sable (30 s, 512 Mo). | Détection en Python depuis les frames (variation de vitesse de la balle près d'une voiture). Marche sur tous les matchs, même au fichier brut purgé, mais sans le marqueur d'équipe : moins fiable sur les duels. |
| DV2 | **Format de la vue 2D.** | **Un document compact par match**, produit par l'analyse et stocké dans le S3 (`views/<match_id>.json.gz`). Le navigateur le lit par une URL présignée courte, comme les uploads : l'API ne relaie pas les octets. Fréquence et quantification choisies à l'étape 10. | L'API sert les frames à la demande. Plus simple à écrire, mais lourd pour l'API et lent sur mobile. |
| DV3 | **Rendu de la vue 2D.** | **Canvas 2D**, sans bibliothèque. Sept objets animés à 60 images par seconde, sans souci même sur mobile. La CSP n'a rien à ouvrir. | SVG : plus simple à déboguer, mais coûteux à animer en continu. |
| DV4 | **Comment vérifier les détections ?** | **Un mode « étiquetage » de la vue 2D**, réservé au développement. Il présente une à une des situations détectées ; tu réponds « vrai », « faux » ou « incertain ». L'export est un fichier JSON local, jamais versionné. | Une table en base et une interface admin. Plus lourd, utile seulement à plusieurs annotateurs. |
| DV5 | **Rotations en 1v1.** | **Pas de rôles, ni de double commit, ni d'overcommit en 1v1** : valeur `null`, comme le dernier défenseur en V1. | Des indicateurs propres au 1v1. Reportés. |
| DV6 | **Le fichier brut est purgé 30 jours après l'analyse (A74).** Si les touches viennent du parser (DV1), un match plus ancien ne peut pas les recevoir. | **Livrer l'émission des touches par `rl-parse` (T11.1) avant ou juste après la mise en production de la V1.** Tous les matchs de production les auront alors, même si leur analyse V2 arrive plus tard depuis les frames. | Allonger `RAW_RETENTION_DAYS` le temps de la V2, au prix d'un écart avec la section 11 de `CLAUDE.md`. |

---

## 3. Ce qui existe déjà

### 3.1 Dans le projet

| Brique V1 | Utilité pour la V2 |
| --------- | ------------------ |
| `frames.parquet` : positions, quaternions, vitesses, boost, sauts, démolitions et phase, pour chaque joueur et chaque frame | Toutes les détections de position et de mouvement. Gardé tant que le match existe, contrairement au fichier brut. |
| `events.json` : buts (avec score), démolitions, pads, `stat_events` (tirs, arrêts) | Repères, et contrôle des touches (un tir suit une touche) |
| Horloge du jeu (A63) : `game_time_s` des buts, début de la prolongation | Fenêtres « 10 s avant le but », temps affichés |
| Registre des métriques et `metrics.json` | Une métrique V2 s'ajoute sans migration et apparaît sur le site |
| `rl-oracle` et `just oracle-report` | Comparer nos détections à celles de `subtr-actor`, comme pour la V1 |
| `just reprocess --analysis-outdated` | Calculer la V2 sur les matchs existants |
| Parcours Playwright | À étendre à la vue 2D |

### 3.2 Dans `subtr-actor` 1.5.1, déjà en dépendance

Relevé dans le code source le 2026-11-08. Ces calculateurs exposent `new()` et `update()` : à confirmer à l'étape 10 qu'ils tournent sans `StatsCollector` ni timeline, interdits en production (jusqu'à 197 s et 663 Mo).

| Calculateur | Ce qu'il fait | Seuils notables (valeurs par défaut) |
| ----------- | ------------- | ------------------------------------ |
| `touch_state`, `touch` | Touches, avec auteur, force et contexte | Fenêtre de candidats de 4 frames ; touche « douce » si Δv ≥ 320 uu/s, « forte » si Δv ≥ 900 uu/s |
| `possession` | Possession par équipe, avec la perte rattachée à la dernière touche | Balle libre après 3 s sans touche ; changement confirmé en 1,25 s |
| `rotation` | Rôle de 1er, 2e et 3e homme | Marge de profondeur 150 uu ; ambiguïté du 1er homme 250 uu ; anti-rebond 0,35 s |
| `kickoff` | Type de kickoff, preneur, issue, but rapide | Kickoff gagné si la balle est projetée à plus de 256 uu dans le camp adverse 0,5 s après ; but de kickoff dans les 12 s |
| `fifty_fifty` | Duels et leur issue | Durée maximale de 1,25 s ; résolution après 0,35 s |
| `beaten_to_ball` | Joueur engagé sur la balle mais devancé | Approche soutenue : distance réduite d'au moins 200 uu en 1 s, 70 % du temps en rapprochement, alignement d'au moins 0,45, vitesse d'approche d'au moins 400 uu/s, au plus 1 200 uu de la balle |
| `rush` | Attaques en surnombre, donc overcommits adverses | Soutien à 900 uu ; défenseur à 150 uu ; possession gardée au moins 0,75 s |
| `positioning` | Dernier défenseur, plus proche de la balle, défense en recul | Marge de 150 uu ; changement de « plus proche » après 0,2 s |
| `goal_tags` | Étiquettes de buts (19 calculateurs : aérien, à vide, passe…) | Décrivent la façon de marquer, pas la cause d'un but encaissé |

Il contient aussi un modèle d'*expected goals* et des détecteurs de figures (flicks, resets, ceiling shots) : hors périmètre V2 (annexe H).

---

## 4. Les seuils : règles communes

Un seuil mal choisi transforme un fait en opinion. Ces règles s'appliquent à toutes les détections V2.

1. **Un seuil = une constante nommée** dans `rl_analysis/thresholds.py`, avec sa valeur, son unité et sa source. Un test refuse une constante sans source.
2. **Trois sources possibles, dans cet ordre** :
   - **mesure sur le corpus** : distribution, plateau, percentile, avec le chiffre dans le commentaire, comme `constants.py` en V1 ;
   - **valeur par défaut de `subtr-actor` 1.5.1**, avec le fichier et le nom de la constante : c'est notre référence de comparaison, s'en écarter se justifie ;
   - **convention**, marquée comme telle, quand ni la mesure ni la référence ne tranchent.
3. **Calibration sur tes replays** (étape 17) :
   - **précision** : 60 détections par détecteur, tirées au hasard, que tu juges dans la vue 2D (« vrai », « faux », « incertain ») ;
   - **rappel** : 30 fenêtres proches non détectées (par exemple les 10 s avant un but encaissé), où tu dis si la situation était là ;
   - **ajustement** : sur la moitié A des étiquettes, contrôle sur la moitié B, pour ne pas régler les seuils sur les exemples mêmes qui les jugent.
4. **Cibles** : précision ≥ 80 % et rappel ≥ 60 %, les « incertain » exclus du calcul.
   - Un détecteur sous la cible est affiché « indicatif », avec un libellé visible, ou retiré : c'est ta décision 👤.
   - Une métrique continue (possession, rôles) se compare à `subtr-actor` à la place, et ses écarts sont expliqués comme en V1.
5. **Sensibilité** : `just v2-report` montre comment chaque compte bouge quand un seuil varie de ±20 %. Un détecteur dont le compte change de plus de 50 % est jugé fragile, et le rapport le dit.
6. **Versionnement** : tout changement de seuil fait monter `ANALYSIS_VERSION`, et `just reprocess --analysis-outdated` recalcule. Les seuils sont figés en fin d'étape 17.
7. **Transparence** : chaque situation affichée renvoie à sa définition en une phrase, en FR et en EN (« Comment c'est détecté »).
8. **Pas de seuil réglable par l'utilisateur en V2** : un même match doit dire la même chose à tous ses joueurs.

---

## 5. Définitions des fonctionnalités

Valeurs **de départ**, recalibrées à l'étape 17. « Engagé » est une notion commune à plusieurs détecteurs.

**Joueur engagé sur la balle** : approche soutenue sur la dernière seconde, selon les critères de `beaten_to_ball` (section 3.2), ou dodge en direction de la balle, à moins de 1 200 uu d'elle. Seulement en phase de jeu actif, hors démolition.

### 5.1 Touches

| `metric_id` | Définition | Unité |
| ----------- | ---------- | ----- |
| `touch.count` | Touches du joueur en jeu actif | nombre |
| `touch.per_min` | Touches par minute de temps de référence (jeu actif, présent, non démoli) | /min |
| `touch.pct_aerial` | Part des touches avec la voiture en l'air haut (D7 : `z` ≥ 735,5) | % |
| `touch.pct_hard` | Part des touches qui changent la vitesse de la balle d'au moins 900 uu/s | % |

Contrôle automatique : le buteur a une touche dans les 10 s avant le but, pour au moins 95 % des buts. Aucune touche pendant un compte à rebours.

### 5.2 Possession

| `metric_id` | Définition | Unité |
| ----------- | ---------- | ----- |
| `poss.team_pct` *(équipe)* | Part du jeu actif où l'équipe a la possession, après résolution (section 3.2) | % |
| `poss.player_pct` | Part du jeu actif où le joueur est l'auteur de la possession en cours | % |
| `poss.turnovers_lost` | Possessions perdues sur une touche adverse, rattachées au dernier joueur à avoir touché | nombre |
| `poss.turnovers_won` | Possessions gagnées par une touche du joueur | nombre |

### 5.3 Kickoffs et duels

| `metric_id` | Définition | Unité |
| ----------- | ---------- | ----- |
| `kick.taken` | Kickoffs où le joueur est le premier de son équipe à toucher la balle | nombre |
| `kick.won_pct` | Part de ces kickoffs gagnés : balle projetée dans le camp adverse 0,5 s après la première touche | % |
| `kick.time_to_ball` | Temps moyen entre la fin du compte à rebours et la première touche du joueur | s |
| `kick.goals_conceded` *(équipe)* | Buts encaissés dans les 12 s qui suivent un kickoff | nombre |
| `duel.count` | Duels (50/50) disputés | nombre |
| `duel.won_pct` | Part des duels gagnés : possession à la sortie | % |
| `duel.beaten` | Fois où le joueur, engagé, s'est fait devancer sur la balle | nombre |

### 5.4 Rotations (2v2 et 3v3, `null` en 1v1)

| `metric_id` | Définition | Unité |
| ----------- | ---------- | ----- |
| `rot.pct_first` / `rot.pct_second` / `rot.pct_third` | Temps comme 1er, 2e ou 3e homme (le plus proche de la balle dans l'axe d'attaque, etc.). Marges de 150 et 250 uu, anti-rebond 0,35 s. `pct_third` est `null` en 2v2. | % |
| `rot.double_commits` | Double commits où le joueur est impliqué | nombre |
| `rot.overcommits` *(équipe)* | Situations d'overcommit de l'équipe | nombre |

**Double commit** : deux coéquipiers sont engagés sur la balle en même temps pendant au moins 0,25 s. La séquence se termine dans les 1,5 s par une touche de l'un d'eux ou de l'adversaire. Il est dit **« puni »** si l'adversaire tire ou marque dans les 5 s. Les 2 premières secondes après un kickoff sont exclues : y aller à deux y est un choix. Seuils de départ : convention (0,25 s ; 1,5 s ; 5 s), à calibrer.

**Overcommit** : pendant une possession adverse établie (section 3.2), tous les joueurs de l'équipe sont devant la balle (`y` relatif au-delà de celui de la balle de plus de 150 uu) pendant au moins 1 s. La marge de 150 uu vient de `positioning`. Variante évaluée à l'étape 14 : l'attaque en surnombre de `rush`, vue du côté de l'équipe qui défend.

### 5.5 Buts encaissés

Pour chaque but encaissé, une **fiche de contexte** sur la fenêtre des 10 s qui le précèdent, sur l'horloge du jeu. On ne garde que les **faits**, sous forme d'étiquettes :

| Étiquette | Définition (départ) |
| --------- | ------------------- |
| `double_commit` | Un double commit de l'équipe dans la fenêtre |
| `overcommit` | Un overcommit de l'équipe dans la fenêtre |
| `turnover_own_half` | La dernière perte de balle de l'équipe a eu lieu dans sa propre moitié |
| `beaten_to_ball` | Un défenseur engagé s'est fait devancer dans les 3 s avant le tir |
| `last_back_far` | Le dernier défenseur est à plus de 2 000 uu de son but au moment du tir |
| `last_back_low_boost` | Le dernier défenseur a moins de 20 de boost au moment du tir |
| `defender_demolished` | Un défenseur est démoli dans les 3 s avant le but |
| `kickoff_goal` | But dans les 12 s qui suivent un kickoff |
| `own_touch_last` | La dernière touche avant le but vient de l'équipe qui encaisse |

Chaque fiche garde aussi des faits non étiquetés : temps entre la perte de balle et le but, rôles au moment de la perte, boost de chaque défenseur. Ils s'affichent sans jugement. Sur « Mes stats » : la part de chaque étiquette dans tes buts encaissés sur N matchs (« 35 % suivent un double commit »).

### 5.6 Vue 2D

- **Document** `match2d` (version 1) :
  - échantillonné à la fréquence choisie à l'étape 10 (10 ou 15 Hz attendu), positions entières en uu ;
  - pour chaque échantillon : temps du replay, horloge du jeu, phase ; balle `x, y, z` ; pour chaque joueur `x, y, z`, cap, boost et indicateurs (présent, démoli, boost actif) ;
  - les événements : touches, buts, démolitions, situations ;
  - **aucun nom** : les joueurs sont désignés par `match_player_id`, et les pseudos viennent de la fiche, avec les mêmes règles de confidentialité qu'en V1.
- **Stockage** : clé `views/<match_id>.json.gz`, effacée par `gc_match`, régénérée par `reprocess`. 15 Hz (DV2). Budget : environ 35 Ko compressés par minute de jeu.
- **Lecteur** :
  - terrain à l'échelle, vu de dessus, vertical sur mobile et horizontal sur ordinateur ;
  - interpolation entre deux échantillons, hauteur de la balle suggérée par une ombre ;
  - barre de boost ; ta voiture mise en évidence.
- **Commandes** :
  - lecture et pause (Espace), ±5 s (flèches), vitesse ×0,5 / ×1 / ×2 / ×4 ;
  - curseur gradué sur l'horloge du jeu, avec les marqueurs de buts et de situations.
- **Temps cliquables** : chaque but de la timeline et chaque situation ouvre la vue 5 s avant. L'adresse `/matches/<id>?t=<s>` y mène directement.
- **Accessibilité** : les commandes sont de vrais boutons. La liste des situations est l'équivalent textuel du canvas. Pas de lecture automatique.
- **Indisponible** pour un match `header_only` : la fiche le dit.

---

## Étape 10 : vérification technique (spike)

**Objectif** : lever les risques des décisions DV1 à DV3 avant d'investir. **Le code du spike est jetable.**

**Critère de fin** : rapport `spikes/s10-v2/RAPPORT.md` relu, et décisions DV1 à DV6 prises 👤.

| ID    | Tâche | Fin |
| ----- | ----- | --- |
| T10.1 | Brancher dans un binaire de spike les calculateurs `touch_state`, `possession`, `rotation`, `kickoff`, `fifty_fifty`, `beaten_to_ball` et `rush`, sans `StatsCollector` ni timeline. | Tourne sur tout le corpus. Temps et mémoire maximum relevés ; budget : au plus +50 % du temps de `rl-parse --frames`, sous 512 Mo |
| T10.2 | Contrôles automatiques des touches (section 5.1). | Taux de buteurs avec une touche dans les 10 s ; aucune touche en compte à rebours ; distribution des touches par minute |
| T10.3 | Alternative Python de DV1, sur les mêmes contrôles. | Tableau comparatif des deux méthodes |
| T10.4 | Document `match2d` à 10, 15 et 30 Hz : taille compressée et erreur d'interpolation par rapport aux frames complètes. | Taille médiane et maximale, erreur en uu au p95 |
| T10.5 | Prototype de lecteur Canvas sur un match. | Images par seconde mesurées sur PC, et sur ton téléphone 👤 |
| T10.6 | Rapport et décisions. | DV1 à DV6 tranchées 👤 |

**Risques** : les calculateurs peuvent dépendre de l'état d'autres calculateurs (le graphe d'analyse de `subtr-actor`), ce qui en ferait tirer davantage que prévu. Mise à jour de `subtr-actor` à chaque saison du jeu.

---

## Étape 11 : touches et possession

**Objectif** : les touches, la possession et les pertes de balle, testées et contrôlées sur le corpus.

**Critère de fin** : les contrôles de la section 5.1 passent sur le corpus. La possession s'écarte de moins de 3 points de `subtr-actor` en médiane, ou l'écart est expliqué.

**Fichiers** : `games/rocket-league/parser/src/touches.rs`, `packages/schemas/events.schema.json`, `rl_analysis/{thresholds,touches,possession}.py`, migration `0009`.

| ID    | Tâche | Fin |
| ----- | ----- | --- |
| T11.1 | `rl-parse` écrit dans `events.json`, par le graphe de `subtr-actor` limité aux nœuds utiles : `touches` (frame, temps, joueur, équipe, Δv de la balle, contesté), `kickoffs`, `fifty_fifty` et `beaten_to_ball` (DV1, DV7). `parser_version` 0.2.0. **En tête de la V2 (DV6).** | Tests Rust, corpus en CI vert, mémoire de pointe mesurée sous 512 Mo dans le bac à sable |
| T11.2 | Schéma `events` v2, validation, chargement dans `Match`. | Les anciens `events.json` restent lisibles (touches absentes = métriques `null`) |
| T11.3 | `thresholds.py` et la règle des sources (section 4). | Un test refuse un seuil sans source |
| T11.4 | Métriques `touch.*`. | Tests synthétiques, contrôle réel |
| T11.5 | Possession résolue ; table `team_match_metrics` (annexe F). | Tests (balle libre, contestée, changement confirmé), écart à `subtr-actor` mesuré |
| T11.6 | `poss.player_pct`, pertes et gains de balle. | Tests, contrôle réel |
| T11.7 | `rl-oracle` étendu aux touches et à la possession ; rapport. | `just oracle-report` couvre les nouvelles métriques |
| T11.8 | Retraitement : `just reprocess --parser-outdated` sur les matchs dont le brut existe, puis `--analysis-outdated`. | Les matchs au brut purgé sont signalés, et leurs métriques V2 restent `null` |

---

## Étape 12 : vue 2D et outil d'étiquetage

**Objectif** : revoir n'importe quel moment d'un match, et vérifier les détections à l'œil.

**Critère de fin** : depuis un but de la fiche, la vue s'ouvre 5 s avant et le rejoue, sur ordinateur et à 375 px. Le mode étiquetage exporte un fichier.

**Fichiers** : `rl_analysis/view.py`, `services/worker/src/ma_worker/analyze.py`, `services/api/src/ma_api/matches.py`, `apps/web/src/components/view2d/`, `apps/web/src/lib/view2d/`, migration `0010` (`matches.view_key`).

| ID     | Tâche | Fin |
| ------ | ----- | --- |
| T12.1  | Production du document `match2d` par le job `analyze` ; clé en base ; effacement par `gc_match`. | Taille sous le budget, tests, objet supprimé sur S3 |
| T12.2  | `GET /matches/{id}/view` : URL présignée de lecture, courte ; CORS `GET` du S3 (et de R2 à T9.4). | Tests API : propriétaire seulement, 404 sans vue |
| T12.3  | Lecteur : terrain, voitures, balle, interpolation, boost. | Rendu correct sur un match synthétique, testé (positions à un instant donné) |
| T12.4  | Commandes : lecture, vitesse, curseur sur l'horloge, clavier. | Tests des fonctions pures (temps ↔ échantillon) |
| T12.5  | Marqueurs, liens `?t=`, buts de la timeline cliquables. | E2E : un clic sur un but place la vue au bon temps |
| T12.6  | Mobile à 375 px, accessibilité, `prefers-reduced-motion`. | Pas de défilement horizontal, navigation au clavier |
| T12.7  | Mode étiquetage, en développement seulement : file de situations, verdict, export JSON vers `tests/fixtures/labels/` (ignoré par git). | Un lot de 10 étiquettes exporté puis relu par `just v2-report` |

---

## Étape 13 : kickoffs et duels

**Objectif** : métriques `kick.*` et `duel.*`.

**Critère de fin** : tests synthétiques par type de kickoff ; écart à `subtr-actor` expliqué.

| ID    | Tâche | Fin |
| ----- | ----- | --- |
| T13.1 | Kickoffs lus dans `events.json` (DV7) : type (centre, décalé, diagonale), preneur, temps jusqu'à la balle, métriques `kick.*`. | Tests sur les cinq positions de départ, en miroir pour l'équipe orange |
| T13.2 | Issue d'un kickoff et but de kickoff. | Tests, contrôle réel |
| T13.3 | Duels et « devancé sur la balle », lus dans `events.json` (DV7), métriques `duel.*`. | Tests, contrôle réel |
| T13.4 | Situations `kickoff` et `fifty_fifty` en base, visibles dans la vue 2D. | Marqueurs présents sur le curseur |

---

## Étape 14 : rotations

**Objectif** : rôles, double commits et overcommits (section 5.4).

**Critère de fin** : premiers chiffres de précision sur un lot de 30 étiquettes par détecteur, avant la calibration complète de l'étape 17.

| ID    | Tâche | Fin |
| ----- | ----- | --- |
| T14.1 | Rôles de 1er, 2e et 3e homme, `null` en 1v1. | Somme des rôles à 100 % ; écart à `subtr-actor` expliqué |
| T14.2 | « Joueur engagé », définition partagée. | Tests synthétiques : approche, dodge, joueur qui s'éloigne |
| T14.3 | Double commit, puni ou non. | Tests : deux joueurs engagés, un seul, sortie de kickoff exclue |
| T14.4 | Overcommit, avec la variante `rush` en comparaison. | Les deux variantes chiffrées sur le corpus |
| T14.5 | Étiquetage de 30 cas par détecteur 👤 et sensibilité ±20 %. | Précision provisoire publiée dans le rapport |

---

## Étape 15 : buts encaissés

**Objectif** : la fiche de contexte de chaque but encaissé (section 5.5).

**Critère de fin** : sur 30 buts encaissés de tes replays, les étiquettes correspondent à ton avis 👤 avec la précision cible.

| ID    | Tâche | Fin |
| ----- | ----- | --- |
| T15.1 | Fenêtre de 10 s sur l'horloge du jeu, et faits bruts (dernière touche, perte de balle, positions, boost, démolitions). | Tests synthétiques, prolongation comprise |
| T15.2 | Les neuf étiquettes, chacune avec ses seuils et son test. | Tests |
| T15.3 | Situations `goal_context` en base et dans l'API. | Tests API, aucun identifiant de plateforme exposé |
| T15.4 | Revue de 30 buts encaissés dans la vue 2D 👤. | Précision et rappel par étiquette |

---

## Étape 16 : interface d'analyse

**Objectif** : rendre la V2 lisible.

**Critère de fin** : parcours E2E étendu (fiche → analyse → vue 2D), en FR et en EN, à 375 px.

| ID    | Tâche | Fin |
| ----- | ----- | --- |
| T16.1 | Section « Analyse » de la fiche : barre de possession, kickoffs, duels, situations avec temps cliquables. | Rendu testé, textes FR et EN |
| T16.2 | Buts encaissés : une carte par but, avec ses étiquettes, ses faits et « Revoir ». | Rendu testé |
| T16.3 | « Comment c'est détecté » : définition en une phrase pour chaque situation et chaque métrique. | Test : aucune situation sans définition |
| T16.4 | « Mes stats » V2 : nouvelles moyennes, causes des buts encaissés sur N matchs. | Égal à un calcul à la main |
| T16.5 | Parcours E2E étendu. | CI verte |

---

## Étape 17 : calibration et gel des seuils

**Objectif** : appliquer la section 4 à chaque détecteur, puis figer.

**Critère de fin** : rapport final relu ; chaque détecteur est soit à la cible, soit « indicatif », soit retiré 👤 ; `ANALYSIS_VERSION` montée et matchs retraités.

| ID    | Tâche | Fin |
| ----- | ----- | --- |
| T17.1 | Étiquetage complet : 60 détections et 30 fenêtres par détecteur 👤. | Fichiers d'étiquettes complets |
| T17.2 | `just v2-report` : précision, rappel, sensibilité ±20 %, sans aucun pseudo. | Rapport généré |
| T17.3 | Ajustement sur la moitié A, contrôle sur la moitié B. | Écart A/B noté pour chaque seuil |
| T17.4 | Décision par détecteur sous la cible 👤. | Libellé « indicatif » ou retrait en place |
| T17.5 | Gel : sources à jour dans `thresholds.py`, version d'analyse montée, retraitement. | `just reprocess --analysis-outdated` passé, statuts relus |

**Risques** : un corpus trop homogène (surtout du 2v2 classé, section 15 de `CLAUDE.md`) règle les seuils pour un seul mode et un seul niveau. Il faudra des replays de 1v1, de 3v3 et d'autres niveaux avant de généraliser. Une détection à 80 % de précision affirme encore une erreur sur cinq : le libellé doit rester prudent (« probable double commit »).

---

## Amendements en cours de route

Comme pour la V1 (section 2 bis de `docs/PLAN.md`) : ce que l'implémentation a appris, numéroté B1, B2…

| #  | Constat | Traitement |
| -- | ------- | ---------- |
| B1 | Le parser 0.2.0 ajoute quatre listes à `events.json` (T11.1). Les `events.json` déjà stockés ne seront jamais réécrits. | `events.json` passe en version de schéma **2** ; l'en-tête et les frames restent en 1, chacun avec sa propre constante. `parse_events` lit un document v1 comme un v2 dont les quatre listes valent `null` (« pas détecté »), sans modifier le document de l'appelant. Un v1 qui contiendrait déjà une de ces listes est refusé : il est cassé, pas ancien. |
| B2 | Les détecteurs de `subtr-actor` pourraient échouer ou paniquer sur un replay que le reste du parser lit bien. | Les quatre listes valent alors `null`, et le match garde ses frames et ses métriques V1. La panique est rattrapée et reste silencieuse : le crochet de `main.rs` aurait écrit que le parser s'arrêtait, alors qu'il réussit. Aucun cas sur le corpus. |
| B3 | Mesure de T11.1, sur les 98 replays analysables du corpus : `rl-parse --frames` avec les détecteurs prend 0,94 s en médiane et 5,1 s au maximum, pour une mémoire de pointe de 54 Mo en médiane et 294 Mo au maximum. | Sous les limites du bac à sable (30 s, 512 Mo d'espace d'adresses), contrôlées par le test `test_sandbox_on_real_replays` sur tout le corpus. |
| B4 | Contenu des listes, plus compact que les événements de `subtr-actor` | Joueurs traduits en `player_idx`, jamais d'identifiant de plateforme. Touches : frame, temps, joueur, équipe, Δv de la balle, `kind`, `height_band`, `surface`, `contested`. Kickoffs : bornes, type, première touche, équipe gagnante, issue, but, preneurs (temps jusqu'à la balle, boost). Duels : bornes, kickoff ou non, joueurs, gagnant, possession à la sortie. « Devancé sur la balle » : joueur, vainqueur, distance, marge, vitesse d'approche. Le schéma JSON fait foi. |

---

## Annexe F : base de données

Migrations `0009` et `0010`, en plus du registre `player_match_metrics` existant.

```sql
-- Métriques d'équipe (possession, overcommits, buts de kickoff).
CREATE TABLE team_match_metrics (
    match_id         uuid NOT NULL REFERENCES matches (id) ON DELETE CASCADE,
    team             smallint NOT NULL CHECK (team IN (0, 1)),
    metric_id        text NOT NULL,
    value            real,
    analysis_version text NOT NULL,
    computed_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (match_id, team, metric_id)
);

-- Situations détectées : rien qu'identifiants et faits, aucun nom.
CREATE TABLE match_situations (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    match_id         uuid NOT NULL REFERENCES matches (id) ON DELETE CASCADE,
    kind             text NOT NULL CHECK (kind IN
                     ('kickoff', 'fifty_fifty', 'double_commit', 'overcommit', 'goal_context')),
    time_s           real NOT NULL,
    game_time_s      real,
    team             smallint CHECK (team IN (0, 1)),
    player_ids       bigint[] NOT NULL DEFAULT '{}',  -- match_players.id
    tags             text[] NOT NULL DEFAULT '{}',
    details          jsonb NOT NULL DEFAULT '{}',
    analysis_version text NOT NULL
);
CREATE INDEX match_situations_match ON match_situations (match_id, time_s);

ALTER TABLE matches ADD COLUMN view_key text;
```

Droits : `SELECT` pour `ma_api`, lecture et écriture pour `ma_worker`, comme les métriques V1. Les touches restent dans `events.json` et dans le document `match2d` : environ 300 par match, inutiles en base.

---

## Annexe G : contrats d'API

| Méthode et chemin | Changement |
| ----------------- | ---------- |
| `GET /matches/{id}` | Ajoute `team_metrics` (`{"0": {...}, "1": {...}}`) et `situations` (`[{id, kind, time_s, game_time_s, team, players, tags, details}]`). `details` est filtré par type : jamais d'identifiant de plateforme. |
| `GET /matches/{id}/view` | Nouveau : `{"url", "expires_at"}`, URL présignée de lecture (10 min) ; `404 not_available` sans vue. |
| `GET /stats/me` | Les moyennes couvrent les métriques V2. Ajoute `conceded: {"goals", "tags": {"<tag>": n}}` sur les N derniers matchs. |
| `GET /stats/me/history` | Accepte les nouveaux `metric_id`. |

Le catalogue `metrics.json` ajoute un champ `scope` (`player` ou `team`) et, par métrique, la clé de sa définition.

---

## Annexe H : hors périmètre V2

- **Benchmarks par rang, rang déclaré** : V3.
- **Conseils rédigés, LLM, expected goals** : V4. `subtr-actor` a un modèle d'xG, à évaluer à ce moment-là.
- **Détecteurs de figures** (flicks, resets, ceiling shots, air dribbles) : disponibles dans `subtr-actor`, mais ils ne disent rien sur les erreurs. Candidats à une V2.1 si tu les veux.
- **Seuils réglables par l'utilisateur**, vue 3D, partage public d'une vue.
- **Modes spéciaux** (Rumble, Hoops, Dropshot) : toujours exclus (D9).
- **Identité visuelle du site** : piste à ouvrir une fois le nom du produit choisi, sans lien avec ce plan.

---

## Estimation

Environ 45 tâches, soit une vingtaine de jours, hors temps d'étiquetage (environ 3 h de ton côté pour les étapes 14, 15 et 17). L'étape 10 peut remettre en cause DV1 : dans ce cas, l'étape 11 grossit d'environ 3 jours (détection des touches en Python, puis réglage).
