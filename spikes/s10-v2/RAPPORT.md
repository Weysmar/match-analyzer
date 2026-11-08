# Rapport de l'étape 10 : vérification technique de la V2

> 2026-11-08. Plan : `docs/PLAN-V2.md`, étape 10. Le code de ce dossier est jetable.
> Corpus : 122 replays, soit 97 fichiers distincts une fois les doublons retirés (les copies identiques donnent les mêmes chiffres). Aucun pseudo ni identifiant ne sort des scripts : les joueurs sont désignés par leur ligne dans le roster.

## En bref

| Question | Réponse mesurée | Conséquence |
| -------- | --------------- | ----------- |
| Les détecteurs de `subtr-actor` tournent-ils sans `StatsCollector` ni timeline ? | **Oui**, par `collect_builtin_analysis_graph_for_replay` avec la liste des nœuds voulus, qui tire leurs dépendances. Aucun échec là où le parser réussit (119 sur 119). | DV1 réalisable |
| Coût ? | Graphe seul : **0,68 s** en médiane, **3,0 s** au maximum ; mémoire de pointe **238 Mo** au maximum | Très en dessous des limites du bac à sable (30 s, 512 Mo) |
| Les touches sont-elles crédibles ? | `subtr-actor` : le buteur a touché la balle dans les 10 s avant **98,6 %** des 714 buts ; aucune touche pendant un compte à rebours | Qualité suffisante pour bâtir dessus |
| Une détection en Python ferait-elle aussi bien ? | Non : **95,0 %** des buteurs, et elle ne retrouve que **78 %** des touches de `subtr-actor` | DV1 : `subtr-actor` |
| Taille du document de la vue 2D ? | À 15 Hz : **184 Ko** compressés en médiane, erreur de position **16 uu** au p95 | DV2 : 15 Hz |
| Le lecteur Canvas est-il assez rapide ? | **0,02 ms** de processeur par image (budget à 60 images/s : 16,7 ms). Le rendu sur téléphone reste à mesurer 👤 | DV3 : Canvas, sous réserve du téléphone |

## T10.1 : coût des détecteurs

Binaire `probe/` : il lit le replay comme `rl-parse`, puis lance le graphe avec les nœuds `touch`, `possession`, `rotation`, `kickoff`, `fifty_fifty`, `beaten_to_ball` et `rush`. Mesures par GNU `time` (`run_probe.py`, `summarize_cost.py`).

| | Médiane | Maximum |
| - | ------: | ------: |
| `rl-parse --frames` | 0,25 s, 52 Mo | 1,96 s, 292 Mo |
| Spike complet (lecture, `ReplayDataCollector`, graphe) | 0,90 s, 35 Mo | 4,47 s, 238 Mo |
| Graphe seul | 0,68 s | 2,97 s |

- Le plan fixait « au plus +50 % du temps de `rl-parse --frames` ». **Ce budget est dépassé** : le spike prend 3,4 fois ce temps. Il était mal posé : `rl-parse` est si rapide (0,25 s) qu'une proportion n'a pas de sens. Le vrai budget est le bac à sable : 30 s et 512 Mo, largement tenus.
- Intégrés dans `rl-parse`, les détecteurs partageraient la lecture du replay : le surcoût réel est le graphe seul, environ 0,7 s par replay. **La mémoire combinée** (parser et graphe dans le même processus) reste à mesurer à T11.1 : la somme des maximums (530 Mo) dépasse 512 Mo, mais les deux maximums ne viennent pas forcément du même replay, ni du même moment.
- Le maximum vient du match privé de 38 minutes du corpus.

Événements par replay (médiane, maximum) : touches 157 et 1 404 ; segments de possession 65 et 546 ; rôles de rotation 720 et 2 690 ; kickoffs 8 et 53 ; duels 17 et 123 ; « devancé sur la balle » 25 et 140 ; surnombres 12 et 44.

## T10.2 : qualité des touches de `subtr-actor`

`check_touches.py`, sur les 97 replays distincts et leurs 714 buts.

| Contrôle | Résultat |
| -------- | -------- |
| Une touche de l'équipe du buteur dans les 10 s avant le but | 99,2 % |
| Une touche du buteur lui-même dans les 10 s | 98,6 % |
| Touches pendant un compte à rebours | 0 |
| Touches par minute de jeu actif, par joueur | médiane 7,2 ; p5 0,8 ; p95 15,3 |

Les 1,4 % restants n'ont pas été examinés un par un. Pistes probables : buts contre son camp, ou dernière touche attribuée à un coéquipier sur une déviation. À regarder dans la vue 2D à l'étape 11.

## T10.3 : détection en Python, pour comparer

Une touche = un saut de la vitesse de la balle d'au moins 300 uu/s entre deux frames, avec une voiture à moins de 260 uu du centre de la balle, attribuée à la plus proche, au plus une par joueur toutes les 4 frames. Valeurs de départ raisonnables, non optimisées.

| | `subtr-actor` | Python |
| - | ------------: | -----: |
| Touches | 16 399 | 14 136 |
| Buteur avec une touche dans les 10 s | 98,6 % | 95,0 % |
| Touches en compte à rebours | 0 | 0 |
| Touches par minute (médiane) | 7,2 | 6,4 |

Accord avec `subtr-actor`, même joueur à ±3 frames : **91 %** des touches Python sont aussi chez `subtr-actor`, qui en a **22 %** que Python manque. Ce rappel est approximatif : il compte les touches Python retrouvées, rapportées au total de `subtr-actor`.

La méthode Python pourrait progresser, en réglant les seuils ou avec le marqueur `HitTeamNum`. Elle partirait de loin derrière un détecteur déjà réglé, pour un seul avantage : fonctionner sur les matchs dont le fichier brut est purgé, que DV6 règle autrement.

## T10.4 : document de la vue 2D

`measure_view.py` : positions entières en uu, cap en degrés, boost entier, indicateur de présence, JSON en colonnes compressé par gzip. L'erreur compare l'interpolation linéaire entre échantillons à chaque frame réelle, balle et voitures.

| Fréquence | gzip, médiane | gzip, maximum | Erreur p95 (médiane des replays) | Pire replay, p95 | Erreur p99 |
| --------- | ------------: | ------------: | -------------------------------: | ---------------: | ---------: |
| 10 Hz | 128 Ko | 988 Ko | 21 uu | 36 uu | 37 uu |
| **15 Hz** | **184 Ko** | 1 398 Ko | **16 uu** | 27 uu | 30 uu |
| 30 Hz | 339 Ko | 2 524 Ko | 9 uu | 18 uu | 16 uu |

Repère d'échelle : une voiture mesure environ 118 uu de long, la balle 186 uu de diamètre. À 15 Hz, l'écart est invisible à l'écran.

Le budget du plan (300 Ko par match) tient pour un match normal à 10 ou 15 Hz, mais pas pour le match de 38 minutes (1,4 Mo à 15 Hz). Deux pistes pour T12.1 : coder les positions en différences (souvent petites, donc très compressibles), ou poser un budget proportionnel à la durée (environ 35 Ko par minute de jeu).

## T10.5 : prototype de lecteur

`viewer/` : page Canvas sans bibliothèque. Elle a le terrain debout (bleu en bas), les voitures orientées, la barre de boost, la balle avec son ombre au sol, l'interpolation, lecture et pause, la vitesse, ±5 s, un curseur et des raccourcis vers chaque but, 5 s avant.

- Sur PC, le dessin d'une image d'une toile de 1080 × 1582 pixels (téléphone 1080p à densité 3) coûte **0,02 ms** de processeur. Le rendu par le GPU est différé et n'est pas inclus.
- Le compteur d'images par seconde n'a pas pu être lu dans le navigateur intégré, qui ne redessine qu'à la capture d'écran.
- **Test à faire 👤** : une copie autonome du prototype est publiée en page privée (https://claude.ai/artifact/PosH3W6poZqtYn5R4JBie1), avec un compteur d'images par seconde. Ouvre-la sur ton téléphone et sur ton PC, lance la lecture, et note le chiffre.

## T10.6 : décisions proposées

| # | Recommandation après mesure |
| - | --------------------------- |
| DV1 | **Touches par `subtr-actor`, émises par `rl-parse`** dans `events.json`. Confirmé : meilleure qualité, coût faible. |
| DV2 | **Document à 15 Hz**, stocké dans le S3, lu par URL présignée. Le budget passe à environ 35 Ko par minute de jeu, avec un codage en différences à essayer à T12.1. |
| DV3 | **Canvas**, sous réserve du test sur téléphone. |
| DV4 | Inchangé : mode étiquetage en développement, export JSON. |
| DV5 | Inchangé : pas de rotations en 1v1. |
| DV6 | **Confirmé** : livrer T11.1 (touches émises par le parser) au plus tôt, idéalement avant la mise en production de la V1. |
| **DV7** *(nouvelle)* | **Que prendre d'autre à `subtr-actor` ?** Le même passage du graphe donne aussi kickoffs, duels, « devancé sur la balle », possession, rôles et surnombres, sans relire le replay. Recommandation : **`rl-parse` émet aussi les kickoffs, les duels et « devancé sur la balle »**. Ces détecteurs s'appuient sur des détails du replay (octet de dodge, phases de kickoff) que les frames ne gardent pas. **Possession, rôles, double commits et overcommits restent calculés en Python** depuis les touches et les frames : ce sont des règles simples sur des positions, et la section 4 du plan exige qu'on puisse les écrire, les tester et en régler les seuils nous-mêmes. Les sorties de `subtr-actor` pour ceux-là servent de référence de comparaison. |

## Fichiers

| Fichier | Rôle |
| ------- | ---- |
| `probe/` | Binaire Rust du spike (`s10-probe list` et `s10-probe run`) |
| `run_probe.py` | T10.1 : parser et spike sur le corpus, temps et mémoire |
| `summarize_cost.py` | T10.1 : synthèse |
| `check_touches.py` | T10.2 et T10.3 |
| `measure_view.py` | T10.4, et données du prototype |
| `viewer/` | T10.5 : prototype de lecteur |

Pour tout relancer : `cargo build --release` dans `probe/` (avec `CARGO_TARGET_DIR` sur la cible du parser pour réutiliser la compilation), puis `uv run python spikes/s10-v2/run_probe.py`, `summarize_cost.py`, `uv run --with numpy python spikes/s10-v2/check_touches.py` et `measure_view.py`. Les sorties vont dans `out/`, jamais versionné.
