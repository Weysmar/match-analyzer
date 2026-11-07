# Plan d'implémentation V1 : `match-analyzer`

> **Statut : validé par Vincent le 2026-11-06, avec D1, D2 et D3 tels que recommandés. Étape 0 close le 2026-11-07, sauf T0.7 (comparaison Epic, action de Vincent) et la vérification du timeout sur le VPS. Amendements A1 à A17 et D20 validés. Étape 1 terminée le 2026-11-07, dépôt privé `Weysmar/match-analyzer`. Étapes 2 et 3 fusionnées le 2026-11-07. Étape 4 faite sur la branche `feat/db`, à valider par Vincent avant l'étape 5.**
> Date : 2026-11-06. Périmètre : section 8 de `CLAUDE.md`, ordre de la section 13, précédé d'une étape 0 de vérification.
> Rapport de l'étape 0 : `spikes/s0-parse/RAPPORT.md`.

## Sommaire

1. [À trancher avant de commencer](#1-à-trancher-avant-de-commencer)
2. [Réponses intégrées](#2-réponses-intégrées) et [amendements après l'étape 0](#2-bis-amendements-après-létape-0)
3. [Ce que le repérage a déjà établi](#3-ce-que-le-repérage-a-déjà-établi)
4. [Incohérences et risques dans `CLAUDE.md`](#4-incohérences-et-risques-dans-claudemd)
5. [Conventions du plan](#5-conventions-du-plan)
6. [Étape 0 : vérification technique](#étape-0--vérification-technique-spike)
7. [Étapes 1 à 9](#étape-1--scaffold)
8. [Piste parallèle Epic](#piste-parallèle-e--epic-account-services)
9. [Schéma de la base V1](#annexe-a--schéma-de-la-base-de-données-v1)
10. [Variables d'environnement](#annexe-b--variables-denvironnement-envexample)
11. [Décisions par défaut à confirmer](#annexe-c--décisions-par-défaut-à-confirmer)
12. [Hors périmètre](#annexe-d--explicitement-hors-périmètre)
13. [Sources vérifiées](#annexe-e--sources-vérifiées)

---

## 1. À trancher avant de commencer

**Décisions prises le 2026-11-06 : D1, D2 et D3 suivent la recommandation ci-dessous.** Ces trois décisions changent des pans entiers du plan, et les contrats de l'API restent valables quel que soit le choix.

| #      | Décision                                                                                                                                                                  | Recommandation                                                                                                                                                                            | Si tu choisis l'autre option                                                                                                            |
| ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| **D1** | **Stack de l'API et outillage.** `CLAUDE.md` demande Fastify, Python 3.12 et `make`. Untraded (CS2) utilise FastAPI, Python 3.14, Alembic, `just`, `uv`, `pnpm` et Biome. | **S'aligner sur Untraded.** Deux API dans deux langages rendraient la plateforme commune impossible à mutualiser. L'API, le worker et les migrations partageraient aussi un seul langage. | Avec Fastify : seule l'étape 5 change de fichiers et de dépendances, et l'accès à la base ne peut plus partager de code avec le worker. |
| **D2** | **Droits sur le code d'Untraded.** `apps/` et `db/` sont en **AGPL-3.0-only**, seul `packages/` est en MIT. Le dépôt compte un seul contributeur humain (`GirardotN`).    | **Ne rien copier depuis `apps/` et `db/` : reprendre les idées et réécrire.** Si tu détiens les droits, dis-le : la copie devient possible sous une autre licence.                        | Copier du code AGPL dans un service en ligne fermé obligerait à publier les sources de la partie concernée.                             |
| **D3** | **MinIO n'est plus utilisable tel quel.** Le dépôt est archivé depuis le 25/04/2026 et l'édition communautaire n'est plus distribuée qu'en sources.                       | **Choisir un autre émulateur S3 pour le développement** (tâche T1.4). R2 reste la cible de production et les tests d'upload s'y feront aussi.                                             | Garder la dernière image MinIO existante en local uniquement : possible, sans mises à jour de sécurité.                                 |

Trois autres points attendent ta confirmation en [annexe C](#annexe-c--décisions-par-défaut-à-confirmer), ils ont un effet direct sur le produit : **D4** (définition du tiers de terrain), **D5** (matchs non vérifiés à la connexion) et **D6** (conservation des replays bruts).

---

## 2. Réponses intégrées

| Question          | Réponse                          | Conséquence dans le plan                                                                                                       |
| ----------------- | -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| Q1 Replays        | A                                | L'étape 0 démarre avec les replays post-EAC de `subtr-actor`. Tes 10 replays récents sont requis pour clôturer l'étape (T0.2). |
| Q2 Environnement  | A                                | WSL2 + Ubuntu, dépôt dans le système de fichiers Linux (T0.1).                                                                 |
| Q3 Dépôt          | A                                | Dépôt GitHub privé `match-analyzer`, GitHub Actions. Les replays réels ne sont pas versionnés.                                 |
| Q4 CS2            | Dépôt `untraded/untraded` fourni | Dépôt séparé, Untraded sert de référence (voir section 3.1). `games/cs2/` n'est pas créé.                                      |
| Q5 Nom et domaine | A                                | `match-analyzer` reste provisoire. La soumission Epic est un jalon bloqué par ta décision (piste E).                           |
| Q6 Production     | A, Dokploy                       | L'étape 9 déploie sur un VPS avec Dokploy et R2. Budget non précisé : le dimensionnement sort de T0.8.                         |
| Q7 Non vérifiés   | A                                | Une identité mémorisée n'est jamais vérifiée. « Mes stats » affiche les matchs non vérifiés avec un libellé et un filtre.      |

---

## 2 bis. Amendements après l'étape 0

**Validés par Vincent le 2026-11-06.** Mesures et détails dans `spikes/s0-parse/RAPPORT.md`. Les étapes concernées sont déjà corrigées plus bas, et ces constats priment sur la section 3, écrite avant le spike.

| #   | Constat mesuré                                                                                                             | Changement dans le plan                                                                                                 |
| --- | -------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| A1  | `StatsCollector` et la timeline prennent 197 s et 40 s sur un replay de 75 124 frames, pour 663 Mo.                        | Jamais en production, tests uniquement. Renforce D8.                                                                    |
| A2  | Un collecteur autour de `LivePlayTracker` donne 100 % d'accord sur 735 692 frames, et environ 20 fois plus vite.           | `rl-parse` l'utilise pour les phases (T2.4).                                                                            |
| A3  | Les démolitions ne produisent presque jamais de frames vides (1 sur 242), et la position de la voiture démolie est fausse. | `demolished` = fenêtre de 3,2 s après `DemolishInfo`, arrêtée au changement de phase (T2.6).                            |
| A4  | Les événements de pads bruts surcomptent (27 gros contre 18).                                                              | Déduplication par pad et séquence, bornée par le temps de réapparition du pad (A18). Critères de T2.7 et T7.5 revus.                                              |
| A5  | `amount_used` compte toutes les frames mais divise par le temps suivi.                                                     | Consommation par variation de boost. Critère de T7.4 revu.                                                              |
| A6  | Les frames sont irrégulières, et `RecordFPS` = 30 ne garantit rien.                                                        | Pas de sous-échantillonnage : `--fps` devient un plafond optionnel. Tout est pondéré par `dt_s`.                        |
| A7  | Le header ne liste pas tous les joueurs (50 absents, 3 en trop) et utilise `Dingo` et `NNX`.                               | Le réseau fait foi quand il existe. Table de plateformes ajoutée. Plateforme `bot` ajoutée.                             |
| A8  | `game_type` vaut Soccar même en Dropshot.                                                                                  | D9 s'appuie sur la playlist et la carte.                                                                                |
| A9  | Le réseau compte parfois un but de plus que le header, et 5 buts n'ont pas de joueur.                                      | Réseau prioritaire, `player_idx` nullable.                                                                              |
| A10 | Les erreurs de `subtr-actor` peuvent citer des pseudos.                                                                    | `rl-parse` n'émet que ses codes, jamais le texte d'origine (T2.1).                                                      |
| A11 | Aucune rupture visible à 2200 uu/s.                                                                                        | Le seuil supersonique reste une convention, documentée comme telle (T7.1).                                              |
| A12 | Mémoire réelle bien plus basse que prévu.                                                                                  | `PARSER_MEMORY_MB` passe de 1024 à 512, à valider à T6.3.                                                               |
| A13 | Un replay réel atteint 10,6 Mo et 21 fichiers de ton dossier Demos sont des doublons exacts.                               | La limite de 20 Mo est conservée, et la déduplication par hash sera utile dès la première importation.                  |
| A14 | Le Parquet pèse environ 2 fois le fichier brut.                                                                            | Accepté pour la V1. Option si le coût pèse : retirer les quaternions, inutiles aux métriques V1, ou une frame sur deux. |

**Ajoutés après les 18 replays de Vincent (build `261031`), validés le 2026-11-07 :**

| #   | Constat mesuré                                                                                                                                                                             | Changement dans le plan                                                                                                  |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------ |
| A15 | **Correction d'une erreur de ma part** : `PlayerID.EpicAccountId` contient l'identifiant Epic dans le header, identique au réseau pour 84 joueurs Epic sur 84. Absent des anciens replays. | Un match `header_only` récent peut être vérifié. La correspondance par nom devient le dernier recours.                   |
| A16 | 4 joueurs sont anonymisés (`bAnonymizeToOpponents` et `bAnonymizeToTeammates` vrais), mais le header et le réseau exposent quand même leur vrai pseudo et leur identifiant.                | Décision D20 : afficher `AnonymizedName`.                                                                                |
| A17 | Le corpus récent ne couvre que du 2v2 classé.                                                                                                                                              | 1v1 et 3v3 restent couverts par les replays publics jusqu'au build `260918`. À compléter dès que possible, sans bloquer. |

**Ajoutés pendant l'étape 2 :**

| # | Constat mesuré | Changement dans le plan |
|---|---|---|
| A18 | La séquence d'un pad n'est pas unique, et vaut toujours 1 sur les anciens replays : la déduplication d'A4 écrasait de vrais ramassages, jusqu'à 47 pads pour un joueur. | Une répétition est ce que le temps de réapparition du pad rend impossible : 10 s pour un gros, 4 s pour un petit. Écart à `subtr-actor` : médiane 0, p95 de 3 avec les replays récents de Vincent, 4 sur les replays publics seuls. |
| A19 | `NumFrames / RecordFPS` sous-estime la durée d'environ 16 %. | `duration_s` vient de `TotalSecondsPlayed` quand il existe. Le réseau donne la durée exacte dans `events.json`. |
| A20 | Un replay utilise la clé `MatchGuid`, les autres `MatchGUID`. Le header liste parfois des joueurs absents du réseau (3 dans un match privé). | Les deux clés sont lues. Le `roster` reste la référence quand le réseau est lu. |
| A22 | Les 3 entrées du header absentes du réseau sont des spectateurs : `Team` vaut -1 et leur score est nul. | Ils ne sont plus des joueurs : `rl-parse` les retire de `header.json`, et leurs identifiants ne sont pas conservés. |
| A23 | Un schéma combinant `$ref` et type nullable refusait `null` : les contre-exemples l'ont révélé. | Corrigé. Types Python écrits à la main, sans générateur, et contrôlés contre les schémas. Pas de types TypeScript pour ces formats : le front ne les lit pas, il passe par l'API. |
| A24 | L'annexe A autorisait un `match_player_id` d'un autre match, et un événement nommant un joueur d'un autre match. | Clés étrangères composées `(match_id, player)`, rôles `ma_api` et `ma_worker` aux droits minimaux, plateformes et cohérence des rejets contrôlées par la base. `arena_out_of_bounds` conservé dans `matches`. |
| A21 | Les règles `requires` de `clap` laissaient passer une combinaison d'options invalide. | Les combinaisons d'options sont vérifiées par `rl-parse` lui-même. |

**Encore ouvert** : l'identifiant Epic (T0.7).

---

## 3. Ce que le repérage a déjà établi

Légende : **[code]** lu dans les sources, **[fichier]** observé dans des replays réels, **[doc]** documentation officielle, **[à vérifier]** à confirmer à l'étape 0.

### 3.1 Relation avec Untraded

`CLAUDE.md` décrit un monorepo commun où CS2 vit dans `games/cs2/`. La réalité est différente : Untraded est un projet autonome et public, avec sa propre marque déposée, sa licence et une base de données propre à CS2.

**La plateforme commune n'existe pas encore et ne peut pas être reprise telle quelle** :

- `app_user.steam_id` est `NOT NULL` : pas de compte Epic ni de mode sans compte possibles ;
- le schéma est spécifique à CS2 (`match_mode`, `kill`, `round`) ;
- le stockage objet est le système de fichiers local (interface S3 prévue, pas écrite) ;
- l'accès se fait par invitation.

**Recommandation** : un dépôt `match-analyzer` séparé, avec les mêmes conventions et les mêmes idées, sans paquet partagé en V1. L'extraction d'une plateforme commune se décidera après la V1, quand deux implémentations réelles permettront de voir ce qui est commun.

| Idée reprise (réécrite, voir D2)                              | Référence dans Untraded                  | Adaptation ici                                                               |
| ------------------------------------------------------------- | ---------------------------------------- | ---------------------------------------------------------------------------- |
| File de jobs PostgreSQL, reprise des jobs abandonnés, backoff | `apps/worker/.../queue.py`, ADR 0004     | Identique sur le principe                                                    |
| Parsing isolé avec délai                                      | `apps/worker/.../isolated.py`            | Sous-processus `rl-parse` au lieu de `multiprocessing`                       |
| Rétention des fichiers bruts                                  | `apps/worker/.../retention.py`, ADR 0009 | Règle spécifique à `header_only` (D6)                                        |
| Interface de stockage objet                                   | `apps/worker/.../store.py`               | Implémentation S3, qu'Untraded pourra aussi utiliser                         |
| Steam OpenID, cookie de nonce, jeton de session haché         | `apps/api/.../steam.py`, `auth.py`       | Ajout d'Epic et du mode sans compte                                          |
| Service de migration ponctuel, limite mémoire du worker       | `compose.yaml`                           | Adapté à Dokploy                                                             |
| Découpage de la CI (python, typescript, schema, images)       | `.github/workflows/ci.yml`               | Ajout de Rust                                                                |
| Registre de métriques versionnées                             | ADR 0003 et 0007                         | Version allégée : un identifiant par métrique, une version d'analyse globale |

**Non repris en V1** : la sécurité au niveau des lignes (RLS, voir [D11](#annexe-c--décisions-par-défaut-à-confirmer)), les workspaces et équipes, le collecteur Valve, le chiffrement de secrets.

### 3.2 Parser

- **Versions observées le 2026-11-06** : `boxcars` 0.13.0 et `subtr-actor` 1.5.1, licence MIT, Rust ≥ 1.88 **[code]**. Leur publication est très active : 8 versions de `boxcars` entre le 28/04 et le 18/10/2026.
- **Couplage fort** : `subtr-actor` 1.5 expose des types `boxcars` dans son API et impose `boxcars` 0.13, et `RemoteId` est `#[non_exhaustive]` **[code]**. Il faut figer les versions exactes dans `Cargo.lock`.
- **Replays post-EAC** : `subtr-actor` a une batterie de tests sur 5 replays post-EAC (net 11, build `260316.80791.512269`) et sur la saison 24 (868.34, net 12, build `260918.75141.528314`) **[code]**. Ces tests n'ont pas encore été exécutés de notre côté.
- **Header sans réseau** : `boxcars` propose `never_parse_network_data`, `must_parse_network_data` et `ignore_network_data_on_error` **[code]**.

### 3.3 Header (6 replays examinés : 5 de 2026, 1 de 2023)

| Champ                | Constat                                                                                                                                                                    | Conséquence                                                                                                                              |
| -------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| Identifiant Epic     | `OnlineID = 0` pour **tous** les joueurs Epic **[fichier]**. **Corrigé par l'étape 0** : l'identifiant figure dans `PlayerID.EpicAccountId` sur les replays récents (A15). | Un match `header_only` récent peut être vérifié pour un joueur Epic. Sur les anciens replays sans `PlayerID`, il faut le network stream. |
| Identifiant de match | La clé s'écrit `MatchGUID` et non `MatchGuid`. Présente en 2026, absente du replay de 2023 **[fichier]**.                                                                  | La solution de repli (date + joueurs + score) sera réellement utilisée sur les anciens replays.                                          |
| Date                 | `Date` a le format `2026-04-28 18-07-32`, sans fuseau **[fichier]**. `MatchStartEpoch` existe en 2026, pas en 2023 **[fichier]**.                                          | `played_at` vient de `MatchStartEpoch` si présent, unité à confirmer **[à vérifier]**. Sinon `Date`, marqué comme peu fiable.            |
| Buts                 | Les entrées vues exposent `PlayerName`, `PlayerTeam` et `frame` **[fichier]**.                                                                                             | `player_platform_id` de la section 6.1 semble impossible depuis le seul header **[à vérifier]**. Le joueur sera résolu par le réseau.    |
| Durée, playlist      | Pas de durée directe. La playlist vient du réseau (`playlist_id`) **[code]**.                                                                                              | `duration_s` vaut `NumFrames / RecordFPS` à défaut, `playlist` vaut `null` en `header_only`.                                             |
| Anonymisation        | `boxcars` connaît `PRI_TA:AnonymizedName`, `bAnonymizeToOpponents` et `bAnonymizeToTeammates` depuis la v2.70 du jeu **[code]**.                                           | Nouveau cas à tester : quel nom le replay expose-t-il, et comment respecter ce choix ? **[à vérifier]**                                  |

### 3.4 Constantes de la section 7

| Constante               | `CLAUDE.md` | `subtr-actor`                    | État                                                |
| ----------------------- | ----------- | -------------------------------- | --------------------------------------------------- |
| Largeur `x`             | ±4096       | ±4096                            | Concordant, à mesurer                               |
| Longueur `y`            | ±5120       | ±5120                            | Concordant, à mesurer                               |
| Plafond `z`             | ≈ 2044      | 2044                             | Concordant, à mesurer                               |
| Vitesse max             | ≈ 2300      | 2300                             | Concordant, à mesurer                               |
| Supersonique            | ≈ 2200      | 2200                             | Concordant, à mesurer                               |
| Échelle du boost        | 0 à 255     | 0 à 255, 85 au kickoff           | Concordant, à mesurer sur les deux formats de boost |
| **Coupure des tiers**   | **±1707**   | **±2300** (ligne des pads)       | **Divergent : voir D4**                             |
| Équipe bleue en `y < 0` | À vérifier  | Un test le suggère indirectement | À mesurer                                           |

### 3.5 Ce que `subtr-actor` fournit, d'après le code

À confirmer par T0.6 (accessibilité depuis l'API publique, fiabilité sur nos replays).

| Besoin                                | Fourni                                                                                   | Reste à coder                                                                            |
| ------------------------------------- | ---------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| Positions, rotations, vitesses, boost | `ReplayDataCollector`, `FrameRateDecorator`                                              | Écriture Parquet (non fournie)                                                           |
| Sauts, dodges                         | Drapeaux par frame                                                                       | Rien                                                                                     |
| Au sol / en l'air                     | Bandes d'altitude (`z ≤ 20`, `z ≥ 642.775 + rayon de balle`)                             | Pas de vrai `on_ground` : la conduite sur un mur compte comme « en l'air » (voir D7)     |
| Démolitions                           | `DemolishInfo` (attaquant, victime, frame, positions)                                    | Colonne `demolished` à dériver de `PlayerFrame::Empty` et des événements                 |
| Réapparitions                         | `RespawnEvent`, côté statistiques                                                        | Vérifier qu'il est utilisable hors des collecteurs de stats                              |
| Pauses après but, kickoffs            | `GameplayPhase` : `KickoffCountdown`, `KickoffWaitingForTouch`, `ActivePlay`, `PostGoal` | Vérifier l'accès depuis notre collecteur, sinon reproduire la logique                    |
| Ramassage de pads                     | `BoostPadEvent` + `ResolvedBoostPad` (taille, position)                                  | Jointure par `pad_id`, couverture à mesurer                                              |
| Buts                                  | `GoalEvent` avec joueur et score                                                         | Rien                                                                                     |
| Stats agrégées                        | `BoostStats`, `MovementStats`, `PositioningStats`, `DemoPlayerStats`                     | **Couvrent presque toutes les métriques V1.** Serviront de référence de comparaison (D8) |

---

## 4. Incohérences et risques dans `CLAUDE.md`

| #   | Point                                                                                                                                                                   | Traitement proposé                                                                                                  |
| --- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| I1  | La structure `games/cs2/` et la plateforme commune ne correspondent pas à Untraded.                                                                                     | Dépôt séparé, section 3.1.                                                                                          |
| I2  | Fastify, Python 3.12, `make`, ESLint et Prettier divergent d'Untraded.                                                                                                  | D1.                                                                                                                 |
| I3  | MinIO est archivé.                                                                                                                                                      | D3, T1.4.                                                                                                           |
| I4  | **Le contrat `header.json` de la section 6.1 n'est pas réalisable tel quel** (auteurs de buts, durée, identifiant absent des anciens replays).                          | Contrat corrigé à l'étape 2.                                                                                        |
| I5  | **Purge à 30 jours contre retraitement.** Un replay `header_only` purgé ne peut plus jamais être retraité, ni un match reparsé après un correctif du parser.            | D6. Les analyses sont recalculées depuis le Parquet.                                                                |
| I6  | **Une URL pré-signée ne limite pas la taille.** R2 ne prend pas en charge le POST de formulaire avec politique de taille.                                               | PUT avec `Content-Length` signé, à valider sur R2 (T9.4), plus contrôle de taille par le worker.                    |
| I7  | **`raw/<sha256>.replay` avec un hash fourni par le client permet d'empoisonner un fichier.** Un attaquant dépose un autre contenu sous le hash d'un replay légitime.    | Dépôt sous `incoming/<upload_id>`. Le worker calcule le vrai hash et déplace le fichier.                            |
| I8  | **Le contrôle du fichier ne peut pas se faire à l'upload** puisque l'API ne voit pas les octets.                                                                        | Pré-contrôle dans le navigateur (confort) et contrôle réel dans le worker.                                          |
| I9  | **« Vérifié » ne signifie pas « authentique ».** Un replay n'est pas signé : on peut en forger un portant son propre identifiant.                                       | Acceptable en V1. À traiter avant les benchmarks (V3).                                                              |
| I10 | **Déduplication par `MatchGUID` : un fichier forgé pourrait prendre la place d'un vrai match.**                                                                         | Clé `MatchGUID` + hachage des joueurs et du score. En cas de conflit, le match est séparé et l'incident journalisé. |
| I11 | La section 13 oublie le déploiement, la purge, l'effacement, le retraitement et les pages légales, pourtant exigés ailleurs.                                            | Étape 9 ajoutée, dans le périmètre des sections 5.2, 10 et 11.                                                      |
| I12 | **La piste Epic exige une page d'accueil en ligne bien avant le front (étape 8).**                                                                                      | La tâche E4 anticipe une page minimale.                                                                             |
| I13 | Les modes spéciaux (Rumble, Hoops, Dropshot) cassent les constantes et certaines métriques.                                                                             | D9 : analyse limitée au terrain standard, header affiché pour le reste.                                             |
| I14 | « Lot de 50 fichiers » contre un dossier Demos de plusieurs centaines de replays.                                                                                       | Première importation : les 50 plus récents, puis bouton « importer plus ».                                          |
| I15 | La liste de tables de la section 13 ne couvre pas les sessions connectées, les identités mémorisées, les fichiers d'un match, les événements ni la limitation de débit. | Tables `auth_sessions`, `player_claims`, `match_files`, `match_events` et `rate_limit_buckets` ajoutées.            |

---

## 5. Conventions du plan

- **Tâche** : une demi-journée de travail au maximum, validée une par une. Le plan compte 99 tâches (étapes 0 à 9) et 8 tâches Epic, soit au plus une cinquantaine de jours, hors délai de la Brand Review.
- **« Fin »** : commande ou test qui prouve que la tâche est terminée.
- **`just`** : remplace `make` sous réserve de D1, avec les mêmes noms de cibles (`just dev`, `just test`, `just lint`, `just reprocess`).
- **Versions** : celles indiquées ont été observées le 2026-11-06. **Chacune sera revérifiée à l'installation**, puis figée dans un fichier de verrouillage.
- **👤** : tâche qui demande ton action ou ton accord.

| Dépendance                 | Observée                                     | Raison                                                                                                          |
| -------------------------- | -------------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| Rust                       | Stable récente, `subtr-actor` utilise 1.99.1 | Parser                                                                                                          |
| `boxcars` / `subtr-actor`  | 0.13.0 / 1.5.1                               | Imposés par `CLAUDE.md`                                                                                         |
| `parquet` + `arrow` (Rust) | 60.1.0                                       | **Lourds**, mais seule solution pour écrire du Parquet depuis Rust. Fonctionnalités réduites au minimum (zstd). |
| `clap`                     | 4.6.7                                        | Ligne de commande                                                                                               |
| `polars` / `pyarrow`       | 2.1.0 / 26.0.1                               | Analyse                                                                                                         |
| `fastapi` / `uvicorn`      | 0.162.0 / à confirmer                        | API (D1)                                                                                                        |
| `psycopg` / `alembic`      | à confirmer / 1.20.1                         | Base                                                                                                            |
| `boto3`                    | 1.43.125                                     | S3. Vérifier les en-têtes de checksum par défaut avec R2.                                                       |
| Next.js / `next-intl`      | 16.4.5 / à confirmer                         | Front                                                                                                           |

---

## Étape 0 : vérification technique (spike)

**Objectif** : lever le plus gros risque avant d'investir. **Le code du spike est jetable.**

**Critère de fin** : `spikes/s0-parse/RAPPORT.md` est validé par toi, et le plan est amendé si nécessaire.

**Fichiers** : `spikes/s0-parse/` (crate Rust jetable, `RAPPORT.md`), `tests/fixtures/manifest.toml`, `tests/fixtures/replays/` (non versionné), `justfile`.

**Dépendances** : `boxcars` et `subtr-actor` en versions exactes, `serde_json`, `parquet`, `clap`.

**Contrats** : aucun contrat produit. L'étape alimente les contrats de l'étape 2.

**Corpus de test** :

| Dossier            | Contenu                                                                                    | Usage                              |
| ------------------ | ------------------------------------------------------------------------------------------ | ---------------------------------- |
| `replays/public/`  | Replays de `subtr-actor` au commit `ea9f34d`, téléchargés et vérifiés par SHA-256          | Post-EAC, saison 24, CI            |
| `replays/legacy/`  | Tes 69 replays de 2021 à 2023, en local                                                    | Robustesse sur les anciens formats |
| `replays/vincent/` | 👤 **Au moins 10 replays récents variés** : 1v1, 2v2, 3v3, victoire, défaite, prolongation | Validation finale, identité        |

| ID      | Tâche                                                                                                                                                                                                                 | Fin                                                                                                               |
| ------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| T0.1 👤 | Installer Ubuntu sous WSL2, l'intégration Docker Desktop, `rustup`, `uv`, `pnpm`, `just` et `gh`. Créer le dépôt local, y déplacer `CLAUDE.md` et `docs/PLAN.md`.                                                     | `cargo --version && uv --version && pnpm --version && just --version && docker info` réussit dans WSL             |
| T0.2 👤 | Écrire `manifest.toml` et la cible qui télécharge et vérifie `public/`, copier `legacy/`, ajouter tes 10 replays.                                                                                                     | `just corpus-check` : tous les hash concordent et le nombre de fichiers est affiché                               |
| T0.3    | **Parsing.** Pour chaque replay : header, network, `ReplayProcessor`, nombre de frames, durée, mémoire maximale.                                                                                                      | `just spike-parse` écrit `out/parse.csv`. Le rapport donne le taux de réussite par `BuildVersion`.                |
| T0.4    | **Header.** Lister les propriétés par build. Confirmer `OnlineID`, `MatchGUID`, `MatchStartEpoch` (unité), `Date`, buts, durée.                                                                                       | Tableau du rapport, sans aucun pseudo ni identifiant de tiers                                                     |
| T0.5    | **Constantes.** Mesurer sur les frames actives : min/max de `x`, `y`, `z`, boost, distribution des vitesses autour de 2200 et 2300, position au kickoff par équipe, côté des buts encaissés.                          | `just spike-constants` produit le tableau mesuré / attendu de la section 7                                        |
| T0.6    | **Inventaire.** Pour chaque ligne de la section 3.5 : accessible par l'API publique ? fiable ? Mesurer la correspondance démolitions / frames vides, la couverture `pad_id`, le nombre de frames par `GameplayPhase`. | Table « fourni / à coder » finalisée, avec estimation des tâches supplémentaires                                  |
| T0.7 👤 | **Identité.** Comparer `RemoteId` réseau et header. Comparer l'identifiant Epic d'un de tes replays avec l'« Account ID » de ton compte Epic. Tester bots, doublons de pseudo, joueurs partis, anonymisation.         | Le rapport tranche : l'identifiant réseau **égale-t-il** `account_id` d'OAuth ?                                   |
| T0.8    | **Budget.** Taille du Parquet à 30 fps (format choisi à l'étape 2), temps et mémoire par taille de replay. Comparer quelques calculs manuels aux `StatsCollector`. Fixer timeout, limite mémoire et taille du VPS.    | Le rapport donne les valeurs de `PARSER_TIMEOUT_S` et `PARSER_MEMORY_MB`, et une estimation de stockage par match |
| T0.9 👤 | **Rapport et décision.** Appliquer les règles ci-dessous, amender ce plan.                                                                                                                                            | Rapport relu, plan mis à jour et validé                                                                           |

**Règles de décision** :

| Résultat                                                   | Conséquence                                                                                            |
| ---------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| Header ou network < 100 % sur les replays post-EAC récents | **Arrêt.** Chercher la cause, remonter un ticket en amont si besoin. Le reste du plan n'avance pas.    |
| `boxcars` réussit, mais `ReplayProcessor` échoue           | Écrire notre propre extraction sur `boxcars` : à chiffrer, plusieurs jours en plus                     |
| Échecs limités aux anciens replays                         | `legacy` accepté en `header_only`, sans bloquer la V1                                                  |
| Identifiant Epic réseau ≠ `account_id`                     | Les joueurs Epic ne peuvent pas être vérifiés automatiquement : **retour vers toi avant de continuer** |
| Timeout de 30 s insuffisant au 99ᵉ centile                 | Proposer une nouvelle valeur avec mesures à l'appui                                                    |
| Coût d'un match > 5 Mo de Parquet                          | Réduire les colonnes, passer à 15 fps ou réévaluer le format                                           |
| Accès à `GameplayPhase` impossible                         | Reproduire la logique depuis `ReplicatedStateName` : 1 tâche de plus                                   |

**Tests** : pas de tests formels, le code est jetable. Le rapport fait foi.

**Risques** : les replays publics contiennent des identifiants de tiers, ils ne doivent donc pas être versionnés chez nous. Sans tes replays récents, T0.7 ne peut pas conclure. Le fuseau de `Date` peut rester indéterminé.

---

## Étape 1 : scaffold

**Objectif** : un dépôt vérifié à chaque commit.

**Critère de fin** : `just check` passe en local, et la CI est verte sur `main`.

**Fichiers** :

```
match-analyzer/
├── CLAUDE.md, README.md, .env.example, .gitignore, justfile
├── compose.dev.yaml, pyproject.toml, package.json, pnpm-workspace.yaml, biome.json
├── .github/workflows/ci.yml
├── apps/web/
├── services/{api,worker}/
├── games/rocket-league/{parser,analysis}/
├── packages/schemas/
├── db/
├── docs/{PLAN.md,decisions/}
└── tests/fixtures/
```

`apps/desktop/`, `games/cs2/` et `packages/coaching/` ne sont pas créés.

**Dépendances** : `ruff`, `mypy`, `pytest`, Biome, TypeScript, `vitest`, Rust stable, PostgreSQL 16, émulateur S3 (T1.4).

**Contrats** : cibles `just dev-up`, `just test`, `just lint`, `just check`, `just reprocess`. Les noms des variables S3 sont génériques, voir annexe B.

**Tests** : test fumée pour chaque langage. La CI lance les migrations sur PostgreSQL 16 dès l'étape 4.

| ID      | Tâche                                                                                                                                                                                                 | Fin                                                                                                |
| ------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| T1.1 👤 | Créer l'arborescence et le dépôt GitHub privé (création distante soumise à ton accord). `.gitignore` exclut `.env` et tous les replays.                                                               | `gh repo view` et `git status` propre. `git check-ignore tests/fixtures/replays/x.replay` réussit. |
| T1.2    | Espaces de travail `uv` et `pnpm`, `justfile`.                                                                                                                                                        | `just install` réussit depuis un clone neuf                                                        |
| T1.3    | Lint et types stricts : `ruff`, `mypy --strict`, TypeScript strict, Biome, `cargo fmt`, `clippy -D warnings`, `#![forbid(unsafe_code)]`.                                                              | `just lint` réussit, et échoue sur une erreur introduite exprès                                    |
| T1.4    | **Émulateur S3.** Comparer au moins deux candidats (par exemple Garage et SeaweedFS) : PUT pré-signé, `Content-Length` signé, CORS, démarrage en un conteneur. Noter le choix dans `docs/decisions/`. | Le script `just s3-check` réussit sur le candidat retenu                                           |
| T1.5    | `compose.dev.yaml` : PostgreSQL 16 et S3. `.env.example` documenté.                                                                                                                                   | `just dev-up` puis contrôle `pg_isready` et accès au bucket                                        |
| T1.6    | CI : jobs Rust, Python, TypeScript. Replays `public/` mis en cache, jamais versionnés.                                                                                                                | CI verte sur une PR de test                                                                        |

**Risques** : une arborescence dans `/mnt/c` est lente, d'où le système de fichiers Linux. Les URL pré-signées contiennent l'hôte : `localhost` côté navigateur et le nom du service côté conteneur doivent rester cohérents.

---

## Étape 2 : parser `rl-parse`

**Objectif** : transformer un `.replay` en sorties stables, y compris en cas d'échec partiel.

**Critère de fin** : `just test-replays` passe, avec 100 % des post-EAC en succès complet et le cas « header OK, network KO » couvert.

**Fichiers** : `games/rocket-league/parser/{Cargo.toml,Cargo.lock,src/{main,header,identity,frames,parquet,events,error}.rs,tests/}`.

**Dépendances** : `boxcars`, `subtr-actor`, `parquet`, `arrow`, `clap`, `serde`, `serde_json`, `thiserror`.

### Contrats

```bash
rl-parse --header  --input <fichier> --output <header.json>
rl-parse --frames [--fps 30] --input <fichier> --output-dir <dossier>
```

`--fps` est un plafond optionnel : par défaut, toutes les frames du replay sont gardées (A6).

| Plateforme du header                 | `platform` |
| ------------------------------------ | ---------- |
| `OnlinePlatform_Steam`               | `steam`    |
| `OnlinePlatform_Epic`                | `epic`     |
| `OnlinePlatform_PS4`                 | `psn`      |
| `OnlinePlatform_Dingo`               | `xbox`     |
| `OnlinePlatform_NNX`                 | `switch`   |
| `OnlinePlatform_Unknown` avec `bBot` | `bot`      |
| Autre                                | `unknown`  |

| Code de sortie | Sens                        | Traitement par le worker               |
| -------------- | --------------------------- | -------------------------------------- |
| 0              | Succès                      | Suite normale                          |
| 2              | Mauvais arguments           | Bug : job en échec                     |
| 10             | `not_a_replay`              | Upload rejeté                          |
| 11             | `corrupt`                   | Upload rejeté                          |
| 12             | `network_failed`            | `header_only`                          |
| 13             | `processor_failed`          | `header_only`                          |
| 14             | `unsupported_mode`          | `header_only`, sans nouvelle tentative |
| 15             | `output_error`              | Job réessayé                           |
| 101 ou signal  | Panique ou mémoire dépassée | `header_only`, sans nouvelle tentative |

En cas d'erreur, la sortie d'erreur contient une ligne JSON : `{"code":"network_failed","message":"..."}`. Elle ne contient jamais de pseudo ni d'identifiant.

**`header.json`** (section 6.1 corrigée) :

```json
{
  "schema_version": 1,
  "parser_version": "0.1.0",
  "game_build": "260918.75141.528314",
  "build_id": 0,
  "changelist": 0,
  "replay_version": { "major": 868, "minor": 34, "net": 12 },
  "game_class": "TAGame.Replay_Soccar_TA",
  "match_guid": "string|null",
  "replay_id": "string|null",
  "map": "string",
  "played_at": "ISO 8601|null",
  "played_at_source": "epoch|date_without_timezone|null",
  "duration_s": 300.0,
  "match_type": "Online|Private|...|null",
  "playlist": null,
  "team_size": 2,
  "score": { "blue": 3, "orange": 2 },
  "goals": [{ "frame": 1234, "time_s": 41.2, "player_name": "string", "team": 0 }],
  "players": [
    {
      "platform": "steam|epic|psn|xbox|switch|bot|unknown",
      "platform_id": "string|null",
      "name": "string",
      "team": 0,
      "score": 420,
      "goals": 1,
      "assists": 0,
      "saves": 2,
      "shots": 3,
      "is_bot": false
    }
  ]
}
```

`platform_id` vient de `PlayerID.EpicAccountId` pour Epic et d'`OnlineID` pour les autres plateformes. Il vaut `null` pour les bots et lorsque le replay ne le contient pas (anciens replays Epic, `OnlineID` nul). **Écarts avec la section 6.1** : pas de `player_platform_id` dans `goals`, et ajout de `replay_version`, `game_class`, `played_at_source` et `is_bot`. `game_class` sert au contrôle du fichier, pas à reconnaître le mode (A8). Cette liste de joueurs peut être incomplète : `roster` fait foi quand le réseau est lu (A7).

**`frames.parquet`** : une ligne par frame et par joueur, balle dénormalisée (zstd). Format confirmé par T0.8 : 2,23 Mo en médiane, 3,44 Mo au maximum.

| Colonnes                            | Type          | Notes                                                                                                          |
| ----------------------------------- | ------------- | -------------------------------------------------------------------------------------------------------------- |
| `frame`, `time_s`, `dt_s`           | u32, f32, f32 | Après rééchantillonnage                                                                                        |
| `phase`                             | u8            | 0 inconnu, 1 compte à rebours, 2 attente de touche, 3 jeu actif, 4 après but                                   |
| `ball_x/y/z`, `ball_vx/vy/vz`       | f32 nullable  |                                                                                                                |
| `player_idx`, `team`                | u8            | `player_idx` renvoie à `roster`                                                                                |
| `present`                           | bool          | Faux si `PlayerFrame::Empty` : joueur absent ou trou bref. **Sans lien avec les démolitions** (A3)             |
| `x/y/z`, `qx/qy/qz/qw`, `vx/vy/vz`  | f32 nullable  |                                                                                                                |
| `boost`                             | f32 nullable  | **Normalisé de 0 à 100 ici**, une seule fois                                                                   |
| `boost_active`                      | bool          |                                                                                                                |
| `jumped`, `double_jumped`, `dodged` | bool          |                                                                                                                |
| `demolished`                        | bool          | Fenêtre de 3,2 s après `DemolishInfo`, arrêtée au changement de phase. Position invalide pendant cette fenêtre |

Il n'y a pas de `on_ground` : `CLAUDE.md` le demande, mais il n'existe pas dans les données. Les bandes d'altitude sont calculées à l'analyse (D7). **Le Parquet ne contient aucun identifiant de plateforme**, seulement `player_idx`, ce qui simplifie l'effacement.

**`events.json`** :

```json
{
  "schema_version": 1,
  "parser_version": "0.1.0",
  "fps": 30,
  "playlist_id": 11,
  "duration_s": 310.5,
  "arena_out_of_bounds": false,
  "roster": [
    {
      "player_idx": 0,
      "platform": "epic",
      "platform_id": "string",
      "name": "string",
      "team": 0,
      "anonymized": false
    }
  ],
  "goals": [
    {
      "frame": 1234,
      "time_s": 41.2,
      "team": 0,
      "player_idx": 0,
      "score_blue": 1,
      "score_orange": 0
    }
  ],
  "demolitions": [
    {
      "frame": 2000,
      "time_s": 66.6,
      "attacker_idx": 0,
      "victim_idx": 3,
      "x": 0.0,
      "y": 0.0,
      "z": 0.0
    }
  ],
  "pad_pickups": [
    {
      "frame": 900,
      "time_s": 30.0,
      "phase": 3,
      "player_idx": 1,
      "pad_index": 12,
      "size": "big",
      "x": 0.0,
      "y": 0.0,
      "z": 0.0
    }
  ],
  "unresolved_pad_pickups": 0,
  "stat_events": [{ "frame": 1200, "time_s": 40.0, "player_idx": 2, "kind": "shot" }]
}
```

`player_idx` des buts peut être `null` (A9). `pad_pickups` est déjà dédupliqué (A4, A18). `fps` vaut `null` sans plafond. `arena_out_of_bounds` signale une voiture hors du terrain standard en jeu actif (D9). Dans `roster`, `anonymized` est vrai si `bAnonymizeToOpponents` ou `bAnonymizeToTeammates` l'est, et `name` contient alors `AnonymizedName` (A16, D20).

### Tests

- Instantanés de `header.json` sur le corpus public, anonymisés.
- Invariants sur `frames.parquet` : boost dans [0, 100], positions dans les bornes mesurées, quaternions unitaires, buts de `events.json` égaux au score.
- Fichiers hostiles : vide, tronqué à différents points, 20 Mo aléatoires, CRC faux, network corrompu.

| ID    | Tâche                                                                                                                                                        | Fin                                                                                                                                                 |
| ----- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| T2.1  | Crate, CLI, codes de sortie, erreur JSON. Jamais le texte d'une erreur de `subtr-actor` (A10).                                                               | Test du tableau des codes. Un pseudo présent dans le fichier n'apparaît jamais sur la sortie d'erreur                                               |
| T2.2  | `--header` : extraction sans réseau et contrôle du fichier.                                                                                                  | Instantanés verts sur `public/`                                                                                                                     |
| T2.3  | Identité : `PlayerID.EpicAccountId` et `OnlineID` dans le header, `RemoteId` sur le réseau (`unknown` pour les variantes futures), drapeaux d'anonymisation. | Tests par variante. Sur le corpus, identifiant Epic du header égal à celui du réseau pour tous les joueurs                                          |
| T2.4  | Collecte des frames, `dt_s`, `present`, et collecteur de phases autour de `LivePlayTracker` (A2). **Pas de `StatsCollector` ni de timeline.**                | Test : phases identiques à la timeline sur le corpus public. Le replay de 75 124 frames passe en moins de 10 s                                      |
| T2.5  | Écriture Parquet avec le schéma exact.                                                                                                                       | Lecture `polars` depuis un test Python, schéma identique                                                                                            |
| T2.6  | Fenêtre `demolished` (A3), `events.json` : `roster`, buts, démolitions.                                                                                      | Démolitions égales aux `DemoPlayerStats` et au fixture de référence (10 attendues). Buts cohérents avec le score, écarts avec le header journalisés |
| T2.7  | `pad_pickups` dédupliqués (A4, A18), avec taille et position.                                                                         | Sur le corpus : écart médian de 0 avec `subtr-actor`, p95 ≤ 4 gros et ≤ 5 petits pads. Cause de l'écart résiduel notée : `subtr-actor` ajoute des ramassages déduits des hausses de boost                              |
| T2.8  | Cas « header OK, network KO » et fichiers hostiles.                                                                                                          | Tous les cas renvoient le bon code, aucune panique non gérée                                                                                        |
| T2.9  | Cible `just test-replays`, rapport de corpus, performance.                                                                                                   | Rapport : 100 % sur post-EAC, temps sous le timeout                                                                                                 |
| T2.10 | Binaire de production et image minimale.                                                                                                                     | L'image exécute `rl-parse --header` sur un fixture                                                                                                  |

**Risques** : chaque patch du jeu peut casser le network, d'où `header_only` et le suivi des builds (T9.9). L'API de `subtr-actor` change vite : les appels sont concentrés dans `frames.rs`. Le poids de `arrow` et `parquet` augmente le temps de compilation : le cache CI est nécessaire.

---

## Étape 3 : schémas

**Objectif** : une source de vérité validée automatiquement.

**Critère de fin** : `just test-schemas` valide les sorties réelles et refuse des contre-exemples.

**Fichiers** : `packages/schemas/{header,events,frames}.schema.json`, `packages/schemas/README.md`, `packages/schemas/src/ma_schemas/`.

**Dépendances** : `jsonschema` (Python, version à confirmer). Pas de génération de types (A23).

**Contrats** : les trois formats de l'étape 2. `frames.schema.json` décrit colonnes et types Parquet. Toute modification incompatible incrémente `schema_version` et `parser_version`.

**Tests** : validation de tous les fixtures publics, contre-exemples, et test qui échoue si le schéma Parquet réel diverge.

| ID   | Tâche                                                        | Fin                                              |
| ---- | ------------------------------------------------------------ | ------------------------------------------------ |
| T3.1 | `header.schema.json`.                                        | Sorties réelles valides, contre-exemples refusés |
| T3.2 | `events.schema.json`.                                        | Idem                                             |
| T3.3 | `frames.schema.json` et contrôle du fichier réel.            | Une colonne retirée fait échouer le test         |
| T3.4 | Validation intégrée à la CI, et types Python pour le worker. | `just check` inclut les schémas                  |

**Risques** : un schéma trop strict rejette un champ nouveau d'un patch. Les champs inconnus sont donc tolérés en lecture.

---

## Étape 4 : base de données

**Objectif** : créer le schéma de l'[annexe A](#annexe-a--schéma-de-la-base-de-données-v1) par des migrations versionnées.

**Critère de fin** : `just db-migrate` crée le schéma à vide, et le retour arrière fonctionne.

**Fichiers** : `db/pyproject.toml`, `db/src/ma_db/{cli,migrate,sqlfile,testing}.py`, `db/src/ma_db/migrations/`, `db/tests/`.

Le dossier s'écarte de `db/migrations/` pour suivre le paquet Python (`db/src/...`), comme Untraded. Les fichiers restent du SQL versionné.

**Dépendances** : `alembic`, `psycopg`. Rôles séparés : `ma_api` et `ma_worker`.

**Contrats** : annexe A.

**Tests** : montée et descente sur base vide, contraintes (un seul propriétaire, unicité, cascades), simulation de suppression d'utilisateur.

| ID   | Tâche                                                                               | Fin                                                                         |
| ---- | ----------------------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| T4.1 | Paquet `db`, Alembic, CLI, rôles.                                                   | `just db-migrate` réussit sur base vide                                     |
| T4.2 | `users`, `linked_accounts`, `auth_sessions`, `anonymous_sessions`, `player_claims`. | Tests de contraintes verts                                                  |
| T4.3 | `matches`, `match_files`, `match_players`, `match_events`.                          | Test de cascade de suppression vert                                         |
| T4.4 | `uploads`, `user_matches`.                                                          | Test « exactement un propriétaire » vert                                    |
| T4.5 | `jobs`, `player_match_metrics`, `rate_limit_buckets`.                               | Test `FOR UPDATE SKIP LOCKED` sur deux connexions vert                      |
| T4.6 | Test d'effacement de bout en bout, sur données synthétiques.                        | Après suppression, seul le match encore lié à un autre utilisateur subsiste |

**Risques** : les textes contrôlés par `CHECK` restent simples à faire évoluer, mais doivent être couverts par migration. Les identifiants de tiers sont stockés en clair et restreints par l'API (D10).

---

## Étape 5 : API

**Objectif** : exposer les sessions, l'authentification, l'upload et les lectures.

**Critère de fin** : `just test-api` passe, et un parcours complet fonctionne en `curl` sur l'environnement de développement.

**Fichiers** : `services/api/src/ma_api/{app,settings,db,errors,owner,ratelimit,sessions,steam,epic,attach,uploads,matches,stats,account}.py`, `services/api/tests/`.

**Dépendances** : `fastapi`, `uvicorn`, `httpx`, `psycopg`, `psycopg-pool`, `boto3` (D1). Les types TypeScript du front sont générés depuis l'OpenAPI.

### Contrats

Préfixe `/api/v1`. Format d'erreur unique : `{"error":{"code":"too_large","message_key":"errors.too_large","details":{}}}`. Authentification par cookie, contrôle `Origin` sur les requêtes qui modifient des données. Erreurs communes : `400 invalid_request`, `401 not_signed_in`, `403 bad_origin`, `404 not_found`, `429 rate_limited`, `500 internal`.

| Méthode et chemin             | Entrée                                                 | Sortie                                                                                                                                                                                                                                                                                       | Erreurs propres                                                |
| ----------------------------- | ------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------- |
| `GET /health` (sans préfixe)  |                                                        | `{"status":"ok"}`                                                                                                                                                                                                                                                                            | `503 unavailable`                                              |
| `GET /me`                     | Cookie                                                 | `{"kind":"anonymous\|user\|none","user":{...}\|null,"linked_accounts":[{"provider","display_name"}],"features":{"epic_login":false}}`                                                                                                                                                        |                                                                |
| `GET /auth/steam`             | `?return_to` (chemin relatif)                          | `303` vers Steam                                                                                                                                                                                                                                                                             |                                                                |
| `GET /auth/steam/callback`    | Paramètres OpenID                                      | `303` vers le site, cookie posé                                                                                                                                                                                                                                                              | `auth_failed` en paramètre de redirection                      |
| `GET /auth/epic`              | `?return_to`                                           | `303` vers Epic                                                                                                                                                                                                                                                                              | `404` si le drapeau est désactivé                              |
| `GET /auth/epic/callback`     | `code`, `state`                                        | `303` vers le site                                                                                                                                                                                                                                                                           | `auth_failed`, `404` si le drapeau est désactivé               |
| `POST /auth/logout`           |                                                        | `204`                                                                                                                                                                                                                                                                                        |                                                                |
| `POST /uploads`               | `{"files":[{"name","size","sha256?"}]}`, 50 au maximum | `201 {"uploads":[{"upload_id","status":"awaiting_file","url","method":"PUT","headers":{},"expires_at"}\|{"upload_id","status":"duplicate","match_id"}]}`                                                                                                                                     | `413 too_large`, `422 too_many_files`, `429 quota_exceeded`    |
| `POST /uploads/{id}/complete` |                                                        | `202 {"upload_id","status":"uploaded"}`                                                                                                                                                                                                                                                      | `409 invalid_state`, `422 object_missing`, `422 size_mismatch` |
| `GET /uploads`                | `?status&limit&cursor`                                 | `{"items":[{"upload_id","name","status","rejection","match_id"}],"next_cursor"}`                                                                                                                                                                                                             |                                                                |
| `GET /uploads/{id}`           |                                                        | Objet upload                                                                                                                                                                                                                                                                                 |                                                                |
| `GET /matches`                | `?scope=all\|verified&limit&cursor`                    | `{"items":[{"match_id","played_at","map","playlist","team_size","score","status","verified","my_team","won"}],"next_cursor"}`                                                                                                                                                                |                                                                |
| `GET /matches/{id}`           |                                                        | `{"match":{...},"players":[{"match_player_id","name","team","score","goals","assists","saves","shots","is_me"}],"goals":[{"time_s","team","player_name"}],"metrics":{"<match_player_id>":{"<metric_id>":0.0}},"me":{"match_player_id","verified","identity_source"},"needs_identity":false}` |                                                                |
| `POST /matches/{id}/identity` | `{"match_player_id":1}`                                | `200 {"verified":false,"identity_source":"claimed"}`                                                                                                                                                                                                                                         | `409 identity_locked` (match déjà vérifié), `422 not_a_player` |
| `GET /stats/me`               | `?last=20&scope=all\|verified`                         | `{"matches_count","verified_count","averages":{"<metric_id>":0.0}}`                                                                                                                                                                                                                          |                                                                |
| `GET /stats/me/history`       | `?metric_id&last=20&scope`                             | `{"metric_id","points":[{"match_id","played_at","value","verified"}]}`                                                                                                                                                                                                                       | `422 unknown_metric`                                           |
| `DELETE /me`                  |                                                        | `202`                                                                                                                                                                                                                                                                                        | `401`                                                          |
| `DELETE /me/anonymous`        |                                                        | `202`                                                                                                                                                                                                                                                                                        |                                                                |

**Règles de confidentialité** (section 11) : aucune réponse ne contient de `platform_id`. Il n'existe pas d'endpoint de recherche par pseudo ni de profil public. Tout match passe par `owner.owned_match()`, qui exige une ligne dans `user_matches`.

**Sessions** : jeton aléatoire dans un cookie `__Host-` `HttpOnly`, `Secure` et `SameSite=Lax`, stocké haché en base. Le cookie anonyme n'est créé qu'au premier upload.

**Upload** : `POST /uploads` crée la ligne, signe un `PUT` vers `incoming/<upload_id>` avec `Content-Length` et `Content-Type` fixés, durée de 10 min. `sha256` ne sert qu'à détecter un doublon **parmi les fichiers du même propriétaire**. Sinon, une personne connaissant un hash pourrait se lier à un match sans posséder le fichier.

**Vérification** : `verified = true` si et seulement si `(platform, platform_id)` du joueur figure dans `linked_accounts` de l'utilisateur, avec un `platform_id` non nul. Une seule fonction `refresh_verification()` est appelée à la connexion, à la liaison d'un compte et à la fin du parsing.

**Connexion depuis une session anonyme** : tous les matchs de la session sont rattachés au compte, vérifiés si l'identité correspond, sinon non vérifiés et visibles avec un libellé (D5).

**Liaison Steam + Epic** : se connecter à un second fournisseur en étant déjà connecté lie le compte. Si cet identifiant appartient déjà à un autre utilisateur, la réponse est `account_already_linked`, sans fusion en V1 (D12).

### Tests

Chaque endpoint : cas nominal, refus d'accès entre propriétaires, entrées invalides. Steam : réponses forgées (mauvais `return_to`, mauvais fournisseur, `is_valid:false`). Epic : `state` invalide, drapeau désactivé, réponses simulées. Test transversal : **aucune réponse JSON ne contient un `platform_id` connu**.

| ID    | Tâche                                                                                                           | Fin                                                             |
| ----- | --------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------- |
| T5.1  | Application, configuration, format d'erreur, `/health`, en-têtes de sécurité, OpenAPI.                          | `pytest` vert, `/health` répond                                 |
| T5.2  | Accès base et `owned_match()`.                                                                                  | Test : un autre propriétaire reçoit `404`                       |
| T5.3  | Sessions anonymes, cookie, `/me`.                                                                               | Tests : cookie forgé ou expiré refusé                           |
| T5.4  | Limitation de débit PostgreSQL (par session, utilisateur et IP), IP lue seulement depuis le proxy de confiance. | Test : dépassement donne `429`                                  |
| T5.5  | Steam OpenID : connexion, vérification, nonce.                                                                  | Tests de réponses forgées verts                                 |
| T5.6  | Sessions connectées, déconnexion, création de compte.                                                           | Parcours simulé vert                                            |
| T5.7  | Epic OAuth derrière `FEATURE_EPIC_LOGIN`.                                                                       | Tests : `404` drapeau désactivé, parcours simulé activé         |
| T5.8  | Rattachement anonyme, liaison de comptes, `refresh_verification()`.                                             | Tests des cas : correspond, ne correspond pas, déjà lié         |
| T5.9  | `POST /uploads`, signature, quotas.                                                                             | Test : `PUT` réel sur l'émulateur S3                            |
| T5.10 | `complete` et création du job.                                                                                  | Tests : objet absent, mauvaise taille, double appel             |
| T5.11 | `GET /uploads`, statuts.                                                                                        | Tests verts                                                     |
| T5.12 | `GET /matches`, pagination, filtre.                                                                             | Tests verts                                                     |
| T5.13 | `GET /matches/{id}` et test transversal de confidentialité.                                                     | Aucun `platform_id` dans les réponses                           |
| T5.14 | Choix d'identité et mémorisation.                                                                               | Tests : `409` si vérifié, identité réappliquée au match suivant |
| T5.15 | `/stats/me` et historique.                                                                                      | Résultat égal à un calcul à la main sur données synthétiques    |
| T5.16 | `DELETE /me` et `DELETE /me/anonymous`.                                                                         | Test : données supprimées et job de nettoyage créé              |

**Risques** : le comportement de R2 sur `Content-Length` n'est pas documenté officiellement (T9.4). La documentation Epic confirme l'autorisation, le jeton et `account_id`, mais `userInfo` n'est confirmé que par une source tierce : `account_id` suffit pour l'identité, et `userInfo` ne sert qu'au nom affiché. Le test réel d'Epic dépend de la piste E.

---

## Étape 6 : worker

**Objectif** : parser, stocker et dédupliquer de façon fiable.

**Critère de fin** : `just test-pipeline` : un replay déposé sur S3 aboutit à `parsed`, un fichier corrompu à `rejected`, un network cassé à `header_only`, sans intervention.

**Fichiers** : `services/worker/src/ma_worker/{cli,queue,store,sandbox,parse,dedupe,load,identify,gc,retention}.py`, `services/worker/tests/`.

**Dépendances** : `psycopg`, `boto3`, `polars` (à l'étape 7), binaire `rl-parse` dans l'image.

### Contrats

Jobs : table `jobs`, annexe A.

| `kind`     | `payload`       | Effet                                                         |
| ---------- | --------------- | ------------------------------------------------------------- |
| `parse`    | `{"upload_id"}` | Contrôle, déduplication, header, frames, puis `analyze`       |
| `reparse`  | `{"match_id"}`  | Reparse depuis `raw/` s'il existe encore                      |
| `analyze`  | `{"match_id"}`  | Métriques (étape 7)                                           |
| `gc_match` | `{"match_id"}`  | Supprime le match et ses objets s'il n'a plus de propriétaire |

Clés S3 : `incoming/<upload_id>`, `raw/<sha256>.replay`, `frames/<match_id>.parquet`, `events/<match_id>.json`.

**Isolation** (section 10) :

- sous-processus sans shell, environnement vide : **aucun secret transmis** ;
- entrées et sorties dans un dossier temporaire dédié, sans accès au stockage ni à la base ;
- `RLIMIT_AS`, `RLIMIT_CPU`, nouveau groupe de processus tué au délai ;
- conteneur : utilisateur non root, `no-new-privileges`, `cap_drop: ALL`, racine en lecture seule, `/tmp` en `tmpfs` limité, `mem_limit`.

**Déduplication** : (1) `match_files.sha256` ; (2) `dedupe_key` = hachage de `match_guid` + joueurs + score, ou date + joueurs + score si `match_guid` est absent. Si `match_guid` est identique mais que le contenu diverge, le match est séparé et l'incident journalisé (I10). Le fichier en double est supprimé : seul le premier est conservé.

### Tests

Unitaires : `claim`, backoff, jobs abandonnés. Bac à sable : binaires de test qui bouclent, consomment la mémoire ou lisent l'environnement. Intégration : deux fichiers différents avec le même `MatchGUID`, joueur Epic en `header_only`, reprise après arrêt brutal.

| ID   | Tâche                                                                            | Fin                                                                            |
| ---- | -------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| T6.1 | File de jobs, boucle, reprise, backoff, jobs morts visibles.                     | Test à deux workers : aucun job pris deux fois                                 |
| T6.2 | Interface de stockage et implémentation S3.                                      | Tests sur l'émulateur                                                          |
| T6.3 | Bac à sable `rl-parse`.                                                          | Test : boucle infinie tuée à l'heure dite, mémoire limitée, environnement vide |
| T6.4 | Job `parse` : taille, `TAGame.Replay_`, hash, déplacement vers `raw/`.           | Tests : faux fichier rejeté, `incoming/` nettoyé                               |
| T6.5 | Déduplication et liaison à l'utilisateur.                                        | Deux téléversements du même match donnent un seul match et deux liens          |
| T6.6 | Insertion du header et `user_matches`.                                           | Lignes conformes au fixture                                                    |
| T6.7 | Frames et événements, statut `parsed` ou `header_only`, journalisation du build. | Test : network cassé simulé donne `header_only` et le score reste affiché      |
| T6.8 | Identification automatique et mémorisée, fusion header/`roster`.                 | Test : joueur Steam et joueur Epic identifiés après parsing                    |
| T6.9 | Test de bout en bout et `just test-pipeline`.                                    | Critère de fin de l'étape                                                      |

**Risques** : sur les anciens replays sans `PlayerID`, la correspondance entre header et `roster` se fait par nom pour Epic, donc un doublon de pseudo peut gêner. Un match `header_only` ne donne pas les drapeaux d'anonymisation : le pseudo réel y reste visible jusqu'au retraitement (D20). Le premier fichier arrivé fournit les frames, avec la latence propre à ce client.

---

## Étape 7 : `rl_analysis`

**Objectif** : calculer les 21 métriques V1, chacune définie, testée et contrôlée sur un replay réel (section 8.2).

**Critère de fin** : `mypy --strict` et `pytest` passent, et `just oracle-report` ne montre aucun écart inexpliqué sur les replays réels.

**Fichiers** : `games/rocket-league/analysis/src/rl_analysis/{constants,frames,registry,boost,movement,positioning,events,compute}.py`, `tests/`, `services/worker/src/ma_worker/analyze.py`, `scripts/reprocess.py`.

**Dépendances** : `polars`, `numpy` si nécessaire. Pas de `pandas` ni de `pyarrow` direct, sauf besoin avéré à l'installation.

### Contrats

**Temps de référence** : frames pondérées par `dt_s`, joueur présent et non démoli. Boost et mouvement : phases `kickoff_waiting` et `active`. Positionnement : phase `active` seule. Les comptes à rebours et l'après-but sont toujours exclus.

| `metric_id`                                                     | Définition                                                                    | Unité  |
| --------------------------------------------------------------- | ----------------------------------------------------------------------------- | ------ |
| `boost.used_per_min`                                            | Boost consommé, ramené à la minute de temps de référence                      | %/min  |
| `boost.avg`                                                     | Moyenne temporelle du boost                                                   | %      |
| `boost.pct_zero`                                                | Temps avec un boost ≤ 0,39 % (équivalent de 1/255)                            | %      |
| `boost.pct_full`                                                | Temps avec un boost ≥ 99,6 % (équivalent de 254/255)                          | %      |
| `boost.pads_big` / `boost.pads_small`                           | Ramassages de gros et de petits pads                                          | nombre |
| `boost.pads_enemy_half`                                         | Ramassages dans la moitié adverse (`y` relatif à l'équipe > 0)                | nombre |
| `move.speed_avg`                                                | Vitesse moyenne                                                               | uu/s   |
| `move.pct_supersonic`                                           | Temps à vitesse ≥ seuil mesuré (≈ 2200)                                       | %      |
| `move.pct_ground` / `move.pct_low_air` / `move.pct_high_air`    | Bandes d'altitude (D7)                                                        | %      |
| `pos.pct_def_third` / `pos.pct_mid_third` / `pos.pct_att_third` | Temps par tiers, `y` relatif à l'équipe (D4)                                  | %      |
| `pos.pct_ahead_ball` / `pos.pct_behind_ball`                    | `y` relatif à l'équipe supérieur ou inférieur à celui de la balle, sans marge | %      |
| `pos.dist_ball_avg`                                             | Distance moyenne à la balle en 3D                                             | uu     |
| `pos.pct_last_back`                                             | Temps comme joueur le plus en arrière de l'équipe, `null` en 1v1              | %      |
| `event.demos_inflicted` / `event.demos_taken`                   | Démolitions infligées et subies                                               | nombre |

**« Consommation »** : `BoostStats.bpm()` de `subtr-actor` mesure le boost **ramassé**, et non consommé. Le plan retient la consommation, conformément à `CLAUDE.md`, **calculée par la somme des baisses de boost sur le temps de référence** : méthode simple, sans constante de débit, et confirmée par `boost_active` × débit (1 065 et 1 072 unités brutes par minute, A5).

**Masques de temps** : le spike a validé tous les calculs avec le masque de `subtr-actor`, à savoir `kickoff_waiting` + `active` pour le boost et le mouvement, et `active` seul pour le positionnement. **Le plan adopte cette règle, plutôt qu'un temps de référence unique.** Une frame sans vitesse (0,6 %) est exclue de la vitesse moyenne.

Le modèle est `player_match_metrics(match_player_id, metric_id, value, analysis_version)`, et un ajout de métrique ne demande aucune migration. Un match `header_only` n'a aucune métrique : la fiche le signale et n'affiche que les stats du header.

**Reprocess** (section 5.2) :

```bash
just reprocess --parser-outdated [--build-from X --build-to Y] [--dry-run]
just reprocess --analysis-outdated [--dry-run]
```

### Tests

**Chaque métrique** a une docstring, un test synthétique avec résultat calculé à la main (bord de terrain, équipe orange symétrique, joueur démoli exclu, 1v1) et un contrôle sur replay réel. Comparaison à `StatsCollector` : un écart d'unité ou de définition assumée est documenté et non corrigé (D8).

| ID    | Tâche                                                                                                                | Fin                                                                                                          |
| ----- | -------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| T7.1  | Paquet et `constants.py`, à partir du rapport de l'étape 0. Le seuil supersonique est marqué comme convention (A11). | Chaque constante cite sa mesure ou sa source, `mypy --strict` vert                                           |
| T7.2  | Chargement, temps de référence, `y` relatif à l'équipe.                                                              | Tests : phases exclues, miroir orange correct                                                                |
| T7.3  | `boost.avg`, `pct_zero`, `pct_full`.                                                                                 | Tests et contrôle réel verts                                                                                 |
| T7.4  | `boost.used_per_min`.                                                                                                | Écart médian < 5 % avec `boost_active` × débit, et < 5 % avec `amount_used` si l'on compte toutes les frames |
| T7.5  | `pads_big`, `pads_small`, `pads_enemy_half`.                                                                         | Écart médian de 0 avec `subtr-actor`, p95 ≤ 4 gros et ≤ 5 petits pads                                        |
| T7.6  | `speed_avg`, `pct_supersonic`.                                                                                       | Tests et contrôle réel verts                                                                                 |
| T7.7  | Bandes d'altitude.                                                                                                   | Somme égale à 100 % ± 0,1, contrôle réel vert                                                                |
| T7.8  | Tiers.                                                                                                               | Somme égale à 100 %, écart à `subtr-actor` expliqué (D4)                                                     |
| T7.9  | Devant / derrière et distance à la balle.                                                                            | Écart expliqué par la marge de 150 uu                                                                        |
| T7.10 | `pct_last_back`. Définition simple : le plus en arrière de son équipe à chaque frame, sans logique de rôle.          | Test `null` en 1v1, contrôle réel vert, écart à `subtr-actor` (environ 4 points) documenté                   |
| T7.11 | Démolitions.                                                                                                         | Égalité avec `DemoPlayerStats`                                                                               |
| T7.12 | `compute.py`, écriture en base, job `analyze`, `analysis_version`.                                                   | Un match passe à `ready`, et un relancement n'ajoute aucune ligne                                            |
| T7.13 | `just oracle-report` sur un échantillon réel, sans pseudos.                                                          | Rapport relu : écarts tous expliqués                                                                         |
| T7.14 | `just reprocess` (parser, analyse, plage de build, simulation).                                                      | Test : seuls les matchs obsolètes sont repris, et les fichiers purgés sont signalés                          |

**Risques** : le boost est répliqué par à-coups, ce qui peut fausser le calcul par variation. Les positions subissent la latence du client qui a enregistré. Il n'existe aucune référence officielle pour ces métriques.

---

## Étape 8 : front

**Objectif** : un parcours complet, sans installation, en français et en anglais, utilisable sur mobile.

**Critère de fin** : `just test-e2e` : dépôt d'un replay sans compte, choix du joueur, fiche, connexion Steam simulée, « mes stats ». Le tout en FR et en EN, et à 375 px de large.

**Fichiers** : `apps/web/src/{app,components,i18n,lib}/`, `apps/web/messages/{fr,en}.json`, `apps/web/test/`, `apps/web/e2e/`.

**Dépendances** : `next`, `react`, `next-intl`, `tailwindcss`, `vitest`. **Playwright** : outil lourd, justifié ici car seul moyen de tester la chaîne complète dans un navigateur. Pas de bibliothèque de graphiques : un petit SVG suffit pour l'évolution simple. `idb-keyval` à évaluer pour IndexedDB.

**Contrats** : pages `/`, `/upload`, `/matches`, `/matches/[id]`, `/me/stats`, `/settings`, `/privacy`, `/legal`, `/terms`. Le `/api` du site est relayé vers l'API : même origine, cookies de première partie. L'upload va directement du navigateur vers S3 et ne passe pas par le relais.

**Upload** :

- jusqu'à 50 fichiers par lot, 3 envois simultanés, barre de progression par fichier (XHR, car `fetch` ne donne pas la progression d'envoi) ;
- pré-contrôle : extension, taille ≤ 20 Mo et présence de `TAGame.Replay_` en début de fichier, à titre de confort ;
- états : en attente, envoi, traitement, prêt, doublon, partiel (`header_only`), rejeté, avec motif traduit ;
- suivi par interrogation périodique, pas de WebSocket en V1.

**Dossier Demos** (File System Access API) :

- détection de `showDirectoryPicker`, repli sur l'upload classique si absent ;
- l'API exige un contexte sécurisé et une action de l'utilisateur **[doc]** ;
- identifiant du dossier conservé dans IndexedDB. L'autorisation est redemandée à chaque visite : **ce n'est donc pas une synchronisation automatique, et il faut un clic** ;
- déjà importés mémorisés en local (nom, taille, date) puis par hash ;
- première importation : les 50 plus récents.

**Message aux navigateurs non compatibles et aux joueurs console** : texte clair, sans bloquer l'accès.

**Tests** : `vitest` sur la file d'envoi, les états, la détection de nouveaux fichiers. Test qui échoue si une clé manque en FR ou en EN. Playwright sur le critère de fin. La File System Access API sera testée à la main sur Chrome et Edge, car elle s'automatise mal.

| ID    | Tâche                                                                                                                                  | Fin                                                               |
| ----- | -------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| T8.1  | Next.js, Tailwind, i18n FR/EN, mise en page responsive, en-têtes CSP et HSTS.                                                          | Build vert, test des clés i18n, en-têtes présents                 |
| T8.2  | Client API typé depuis l'OpenAPI, relais `/api`.                                                                                       | Types générés en CI, `/api/v1/me` répond via le site              |
| T8.3  | Zone de glisser-déposer et pré-contrôle.                                                                                               | Tests `vitest` : faux fichier refusé, plus de 50 fichiers signalé |
| T8.4  | Moteur d'envoi : signature, `PUT`, progression, reprise des erreurs, `complete`.                                                       | Test d'intégration : 5 fichiers sur l'émulateur S3                |
| T8.5  | Dossier Demos et repli.                                                                                                                | Test manuel Chrome et Edge, repli testé sur Firefox               |
| T8.6  | Suivi d'état du lot.                                                                                                                   | Tests des états, parcours E2E avec replay réel                    |
| T8.7  | « Lequel de ces joueurs es-tu ? » et mémorisation.                                                                                     | E2E : identité reprise au match suivant                           |
| T8.8  | Fiche match : score, tableau des joueurs, état partiel.                                                                                | E2E vert, adversaires affichés par pseudo uniquement              |
| T8.9  | Fiche match : métriques par joueur avec libellés et unités.                                                                            | Valeurs égales à l'API, FR et EN                                  |
| T8.10 | Timeline des buts.                                                                                                                     | Test du placement sur la durée, prolongation comprise             |
| T8.11 | Connexion proposée après la première analyse, bouton Steam officiel, Epic masqué si le drapeau est désactivé, libellé « non vérifié ». | E2E Steam simulé, Epic absent                                     |
| T8.12 | « Mes stats » : moyennes sur les N derniers matchs, filtre « vérifiés ».                                                               | Égal à un calcul à la main                                        |
| T8.13 | Évolution dans le temps en SVG.                                                                                                        | Rendu testé avec 0, 1 et 20 points                                |
| T8.14 | Paramètres : comptes liés, suppression. Pages légales avec ton texte.                                                                  | E2E : suppression puis déconnexion                                |
| T8.15 | Passe mobile et accessibilité, à 375 px.                                                                                               | Aucun défilement horizontal, navigation au clavier possible       |

**Risques** : la File System Access API peut refuser certains dossiers jugés sensibles : à tester sur `Documents\My Games\...`. Une CSP stricte peut gêner Next.js : à valider tôt. L'envoi direct vers R2 demande un CORS correct.

---

## Étape 9 : production et conformité

Étape **ajoutée** à la section 13 (I11, Q6).

**Objectif** : mettre en ligne une version exploitable, avec sauvegardes et conformité.

**Critère de fin** : 10 replays réels passent par la production, la restauration de sauvegarde est testée, la purge et l'effacement sont vérifiés.

**Fichiers** : `compose.yaml`, `services/*/Dockerfile`, `apps/web/Dockerfile`, `games/rocket-league/parser/Dockerfile`, `.github/workflows/release.yml`, `docs/operations.md`.

**Dépendances** : VPS, Dokploy, Cloudflare R2, GHCR.

**Contrats et choix Dokploy** :

- **Type « Docker Compose » et non « Stack »** : la documentation indique que Stack (Swarm) ne prend pas en charge `build`, et les limites mémoire du worker doivent s'appliquer ;
- **images construites par GitHub Actions et publiées sur GHCR** : compiler Rust sur un petit VPS est coûteux ;
- domaine géré par l'onglet Domains, Traefik + TLS, `expose` plutôt que `ports` ;
- **seul `web` est publié** ;
- `migrate` s'exécute une fois avant les services, à valider sous Dokploy.

**Purge** :

| Donnée                          | Règle                                                                          |
| ------------------------------- | ------------------------------------------------------------------------------ |
| `incoming/`                     | 1 jour, règle de cycle de vie R2 et nettoyage par le worker                    |
| `raw/` d'un match `ready`       | `RAW_RETENTION_DAYS` = 30                                                      |
| `raw/` d'un match `header_only` | Conservé pour retraitement jusqu'à `RAW_RETENTION_HEADER_ONLY_DAYS` = 180 (D6) |
| Session anonyme expirée         | Liens supprimés, puis `gc_match`                                               |
| Sessions, compteurs de débit    | Expiration                                                                     |

**Tests** : test de la pile complète en CI, comme le job `images` d'Untraded. Test de restauration. Tests de purge avec des dates simulées.

| ID      | Tâche                                                                                                                      | Fin                                                                          |
| ------- | -------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| T9.1    | Dockerfiles, utilisateur non root, images épinglées.                                                                       | `docker compose build` réussit                                               |
| T9.2    | `compose.yaml` et durcissement du worker.                                                                                  | La pile démarre en CI, `/api/health` répond                                  |
| T9.3    | Publication des images sur GHCR.                                                                                           | Image taguée au commit, publiée depuis `main`                                |
| T9.4 👤 | **Bucket R2** (compte à ta charge) : CORS, jetons, juridiction UE à vérifier, cycle de vie. Tester `Content-Length` signé. | Script : le fichier plus gros que déclaré est refusé. Sinon, retour au plan. |
| T9.5 👤 | VPS UE et Dokploy, taille selon T0.8, pare-feu, SSH.                                                                       | Interface Dokploy accessible et sécurisée                                    |
| T9.6 👤 | Déploiement sur le domaine provisoire ou définitif.                                                                        | `curl -I https://<domaine>` : TLS et en-têtes corrects                       |
| T9.7    | Sauvegarde vers R2 : base Dokploy si R2 est accepté comme destination, sinon service de `pg_dump`. Restauration testée.    | Base restaurée sur une instance vierge, nombre de lignes identique           |
| T9.8    | Purge, sessions expirées, `gc_match`.                                                                                      | Tests avec dates simulées, objets supprimés sur S3                           |
| T9.9    | Suivi : journaux structurés, `just ops-builds` (taux d'échec réseau par build, signal de patch cassant).                   | Le rapport détecte un faux build en échec                                    |
| T9.10   | Revue de sécurité section 10, relecture RGPD section 11, test en production avec 10 replays réels.                         | Liste cochée, 10 replays au bon statut                                       |

**Risques** : le VPS porte aussi Dokploy et sa base. La mémoire de `rl-parse` limite le nombre de workers. La prise en charge de R2 par les sauvegardes Dokploy n'est pas confirmée par la documentation. Les patchs du jeu sont réguliers : prévoir une mise à jour de `boxcars` à chaque saison.

---

## Piste parallèle E : Epic Account Services

À lancer **dès que le nom et le domaine sont décidés**, sans attendre le code. Délai le plus long du projet (section 8.4).

| ID    | Tâche                                                                                                                                                                                                            | Fin                                                   |
| ----- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------- |
| E1 👤 | **Décider du nom et du domaine**, sans « Rocket League », « Psyonix », « Epic Games » ni « Untraded ». Désigner l'exploitant.                                                                                    | Domaine acheté et décision notée                      |
| E2 👤 | Créer le compte développeur et l'organisation.                                                                                                                                                                   | Organisation visible dans le portail                  |
| E3 👤 | Ajouter et vérifier le domaine.                                                                                                                                                                                  | Domaine marqué vérifié                                |
| E4    | **Page d'accueil réelle minimale** en HTTPS, dans `apps/web`, **à faire avant l'étape 8** : présentation, politique de confidentialité, CGU, contact. Demande T1.x, T8.1 et un déploiement réduit (T9.1 à T9.6). | Les 3 URL répondent en HTTPS                          |
| E5 👤 | Fournir logo, icône, textes de la politique et des CGU, adresse de contact surveillée.                                                                                                                           | Checklist 8.4 cochée                                  |
| E6 👤 | Créer le produit et l'application, configurer Brand Settings, Permissions et Linked Clients, questionnaire d'âge si demandé.                                                                                     | Les 3 blocs sont marqués « Configured »               |
| E7 👤 | Soumettre la Brand Review, et consulter le portail régulièrement.                                                                                                                                                | Soumission enregistrée                                |
| E8    | Après validation : test réel, `FEATURE_EPIC_LOGIN=true`, vérifier sur un compte interne que T0.7 se confirme.                                                                                                    | Connexion réelle et match vérifié pour un joueur Epic |

**Conséquence (Q7)** : tant qu'E8 n'est pas fait, un joueur Epic utilise le service sans compte et voit ses matchs comme non vérifiés. Le lancement public n'attend pas Epic.

---

## Annexe A : schéma de la base de données V1

PostgreSQL 16. Tous les temps sont en `timestamptz`, en UTC. **Les migrations de `db/src/ma_db/migrations/versions/` font foi** : cette annexe en donne la vue d'ensemble, sans les droits des rôles `ma_api` et `ma_worker`, définis table par table (A24). Par rapport à la liste de la section 13, `auth_sessions`, `player_claims`, `match_files`, `match_events` et `rate_limit_buckets` sont ajoutées (I15).

```sql
-- Identity -----------------------------------------------------------------------------------
CREATE TABLE users (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    display_name text NOT NULL,
    locale       text NOT NULL DEFAULT 'fr' CHECK (locale IN ('fr', 'en')),
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE linked_accounts (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id             uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    provider            text NOT NULL CHECK (provider IN ('steam', 'epic')),
    provider_account_id text NOT NULL,
    display_name        text,
    created_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (provider, provider_account_id),
    UNIQUE (user_id, provider)
);

CREATE TABLE auth_sessions (
    token_hash bytea PRIMARY KEY,
    user_id    uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL
);
CREATE INDEX auth_sessions_expiry ON auth_sessions (expires_at);

CREATE TABLE anonymous_sessions (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    token_hash bytea NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL
);
CREATE INDEX anonymous_sessions_expiry ON anonymous_sessions (expires_at);

-- "Which of these players are you?", remembered. A claim never proves anything.
CREATE TABLE player_claims (
    id                   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id              uuid REFERENCES users (id) ON DELETE CASCADE,
    anonymous_session_id uuid REFERENCES anonymous_sessions (id) ON DELETE CASCADE,
    platform             text NOT NULL,
    platform_id          text NOT NULL,
    created_at           timestamptz NOT NULL DEFAULT now(),
    CHECK (num_nonnulls(user_id, anonymous_session_id) = 1)
);
CREATE UNIQUE INDEX player_claims_user ON player_claims (user_id, platform, platform_id)
    WHERE user_id IS NOT NULL;
CREATE UNIQUE INDEX player_claims_anon ON player_claims (anonymous_session_id, platform, platform_id)
    WHERE anonymous_session_id IS NOT NULL;

-- Matches ------------------------------------------------------------------------------------
CREATE TABLE matches (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    game              text NOT NULL DEFAULT 'rocket_league',
    dedupe_key        char(64) NOT NULL UNIQUE,
    match_guid        text,
    status            text NOT NULL DEFAULT 'pending' CHECK (status IN
                      ('pending', 'parsing', 'header_only', 'parsed', 'analyzing', 'ready', 'failed')),
    game_build        text,
    build_id          bigint,
    changelist        bigint,
    replay_major      integer,
    replay_minor      integer,
    replay_net        integer,
    map               text,
    played_at         timestamptz,
    played_at_source  text CHECK (played_at_source IN ('epoch', 'date_without_timezone')),
    duration_s        real,
    match_type        text,
    playlist          text,
    team_size         smallint,
    score_blue        smallint,
    score_orange      smallint,
    arena_out_of_bounds boolean NOT NULL DEFAULT false,
    raw_key           text,
    raw_deleted_at    timestamptz,
    frames_key        text,
    events_key        text,
    parser_version    text NOT NULL,
    analysis_version  text,
    error_code        text,
    created_at        timestamptz NOT NULL DEFAULT now(),
    parsed_at         timestamptz,
    analyzed_at       timestamptz
);
CREATE INDEX matches_build ON matches (game_build, status);
CREATE INDEX matches_parser_version ON matches (parser_version);
CREATE INDEX matches_analysis_version ON matches (analysis_version);
CREATE INDEX matches_raw_retention ON matches (status, parsed_at) WHERE raw_deleted_at IS NULL;

-- Every distinct file known for a match (first level of deduplication).
CREATE TABLE match_files (
    sha256      char(64) PRIMARY KEY,
    match_id    uuid NOT NULL REFERENCES matches (id) ON DELETE CASCADE,
    received_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX match_files_match ON match_files (match_id);

-- Includes third parties: platform_id is never returned by the API.
CREATE TABLE match_players (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    match_id     uuid NOT NULL REFERENCES matches (id) ON DELETE CASCADE,
    frames_idx   smallint,          -- player_idx in frames.parquet; null when header_only
    platform     text NOT NULL
                 CHECK (platform IN ('steam', 'epic', 'psn', 'xbox', 'switch', 'bot', 'unknown')),
    platform_id  text,              -- null for bots and when the replay does not carry it
    display_name text NOT NULL,
    team         smallint NOT NULL CHECK (team IN (0, 1)),
    score        integer,
    goals        smallint,
    assists      smallint,
    saves        smallint,
    shots        smallint,
    is_bot       boolean NOT NULL DEFAULT false,
    anonymized   boolean NOT NULL DEFAULT false,
    UNIQUE (match_id, frames_idx),
    UNIQUE (match_id, id)
);
CREATE INDEX match_players_identity ON match_players (platform, platform_id)
    WHERE platform_id IS NOT NULL;

CREATE TABLE match_events (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    match_id         uuid NOT NULL REFERENCES matches (id) ON DELETE CASCADE,
    kind             text NOT NULL CHECK (kind IN ('goal', 'demolition')),
    frame            integer NOT NULL,
    time_s           real NOT NULL,
    team             smallint,
    actor_player_id  bigint,
    victim_player_id bigint,
    FOREIGN KEY (match_id, actor_player_id) REFERENCES match_players (match_id, id)
        ON DELETE SET NULL (actor_player_id),
    FOREIGN KEY (match_id, victim_player_id) REFERENCES match_players (match_id, id)
        ON DELETE SET NULL (victim_player_id)
);
CREATE INDEX match_events_match ON match_events (match_id, time_s);

-- Uploads and ownership ----------------------------------------------------------------------
CREATE TABLE uploads (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id              uuid REFERENCES users (id) ON DELETE CASCADE,
    anonymous_session_id uuid REFERENCES anonymous_sessions (id) ON DELETE CASCADE,
    file_name            text NOT NULL,
    declared_size        bigint NOT NULL CHECK (declared_size > 0),
    declared_sha256      char(64),
    sha256               char(64),
    status               text NOT NULL DEFAULT 'awaiting_file' CHECK (status IN
                         ('awaiting_file', 'uploaded', 'processing', 'done', 'duplicate', 'rejected', 'failed')),
    rejection            text CHECK (rejection IN
                         ('not_a_replay', 'corrupt', 'too_large', 'size_mismatch')),
    incoming_key         text NOT NULL,
    match_id             uuid REFERENCES matches (id) ON DELETE SET NULL,
    created_at           timestamptz NOT NULL DEFAULT now(),
    completed_at         timestamptz,
    CHECK (num_nonnulls(user_id, anonymous_session_id) = 1),
    CHECK ((status = 'rejected') = (rejection IS NOT NULL))
);
CREATE INDEX uploads_user ON uploads (user_id, created_at DESC) WHERE user_id IS NOT NULL;
CREATE INDEX uploads_anon ON uploads (anonymous_session_id, created_at DESC)
    WHERE anonymous_session_id IS NOT NULL;
CREATE INDEX uploads_stale ON uploads (created_at) WHERE status = 'awaiting_file';

CREATE TABLE user_matches (
    id                   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id              uuid REFERENCES users (id) ON DELETE CASCADE,
    anonymous_session_id uuid REFERENCES anonymous_sessions (id) ON DELETE CASCADE,
    match_id             uuid NOT NULL REFERENCES matches (id) ON DELETE CASCADE,
    match_player_id      bigint,
    identity_source      text NOT NULL DEFAULT 'none' CHECK (identity_source IN
                         ('none', 'linked_account', 'claimed', 'memorized')),
    verified             boolean NOT NULL DEFAULT false,
    created_at           timestamptz NOT NULL DEFAULT now(),
    CHECK (num_nonnulls(user_id, anonymous_session_id) = 1),
    CHECK (NOT verified OR identity_source = 'linked_account'),
    CHECK ((identity_source = 'none') = (match_player_id IS NULL)),
    FOREIGN KEY (match_id, match_player_id) REFERENCES match_players (match_id, id)
);
CREATE UNIQUE INDEX user_matches_user ON user_matches (user_id, match_id) WHERE user_id IS NOT NULL;
CREATE UNIQUE INDEX user_matches_anon ON user_matches (anonymous_session_id, match_id)
    WHERE anonymous_session_id IS NOT NULL;
CREATE INDEX user_matches_match ON user_matches (match_id);

-- Metrics ------------------------------------------------------------------------------------
CREATE TABLE player_match_metrics (
    match_player_id  bigint NOT NULL REFERENCES match_players (id) ON DELETE CASCADE,
    metric_id        text NOT NULL,
    value            double precision,   -- null when undefined (e.g. last back in 1v1)
    analysis_version text NOT NULL,
    computed_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (match_player_id, metric_id)
);
CREATE INDEX player_match_metrics_version ON player_match_metrics (analysis_version);

-- Job queue ----------------------------------------------------------------------------------
CREATE TABLE jobs (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    kind         text NOT NULL CHECK (kind IN ('parse', 'reparse', 'analyze', 'gc_match')),
    payload      jsonb NOT NULL DEFAULT '{}',
    status       text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'done', 'dead')),
    priority     smallint NOT NULL DEFAULT 0,
    attempts     smallint NOT NULL DEFAULT 0,
    max_attempts smallint NOT NULL DEFAULT 3,
    run_at       timestamptz NOT NULL DEFAULT now(),
    locked_by    text,
    locked_at    timestamptz,
    last_error   text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    finished_at  timestamptz
);
CREATE INDEX jobs_ready ON jobs (priority DESC, run_at) WHERE status = 'queued';
CREATE INDEX jobs_running ON jobs (locked_at) WHERE status = 'running';

-- Rate limiting (no Redis in V1) -------------------------------------------------------------
CREATE TABLE rate_limit_buckets (
    bucket_key   text NOT NULL,
    window_start timestamptz NOT NULL,
    hits         integer NOT NULL DEFAULT 0,
    PRIMARY KEY (bucket_key, window_start)
);
```

**Rappel** : `user_matches` porte le champ `verified` demandé. `users` n'a pas de suppression logique : la suppression est immédiate, et `gc_match` nettoie ensuite les matchs orphelins.

---

## Annexe B : variables d'environnement (`.env.example`)

| Variable                                                    | Défaut                  | Rôle                                                                       |
| ----------------------------------------------------------- | ----------------------- | -------------------------------------------------------------------------- |
| `APP_ENV`                                                   | `development`           | `development` ou `production`                                              |
| `SITE_URL`                                                  | `http://localhost:3000` | Adresse publique du site, base des redirections OAuth                      |
| `DATABASE_URL` | | Migrations : propriétaire du schéma |
| `API_DB_PASSWORD`, `WORKER_DB_PASSWORD` | | Mots de passe des rôles, posés par `ma-db upgrade` |
| `WORKER_DATABASE_URL` | | Connexion du worker (rôle `ma_worker`) |
| `TEST_DATABASE_URL` | | Base d'administration pour `just test-db`, développement et CI uniquement |
| `API_DATABASE_URL`                                          |                         | Connexion de l'API (rôle restreint)                                        |
| `SESSION_SECRET`                                            |                         | Signature du cookie de nonce OAuth                                         |
| `SESSION_TTL_DAYS`                                          | `30`                    | Durée d'une session connectée                                              |
| `ANON_SESSION_TTL_DAYS`                                     | `30`                    | Durée d'une session anonyme                                                |
| `S3_ENDPOINT`                                               |                         | Émulateur local ou R2                                                      |
| `S3_PUBLIC_ENDPOINT`                                        |                         | Hôte vu par le navigateur pour les URL pré-signées                         |
| `S3_REGION`                                                 | `auto`                  | Région                                                                     |
| `S3_BUCKET`                                                 |                         | Bucket                                                                     |
| `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`                  |                         | Identifiants                                                               |
| `UPLOAD_MAX_BYTES`                                          | `20971520`              | 20 Mo                                                                      |
| `UPLOAD_MAX_FILES_PER_BATCH`                                | `50`                    | Taille d'un lot                                                            |
| `UPLOAD_URL_TTL_S`                                          | `600`                   | Validité d'une URL pré-signée                                              |
| `RATE_UPLOAD_ANON_PER_DAY`                                  | `100`                   | Par session anonyme                                                        |
| `RATE_UPLOAD_IP_PER_DAY`                                    | `200`                   | Par IP                                                                     |
| `RATE_UPLOAD_USER_PER_DAY`                                  | `500`                   | Par utilisateur                                                            |
| `RATE_AUTH_IP_PER_MIN`                                      | `20`                    | Authentification, par IP                                                   |
| `TRUSTED_PROXY_COUNT`                                       | `1`                     | Nombre de proxys de confiance pour lire l'IP                               |
| `FEATURE_EPIC_LOGIN`                                        | `false`                 | Active la connexion Epic                                                   |
| `EPIC_CLIENT_ID`, `EPIC_CLIENT_SECRET`, `EPIC_REDIRECT_URI` |                         | OAuth Epic                                                                 |
| `PARSER_BIN`                                                | `rl-parse`              | Chemin du binaire                                                          |
| `PARSER_TIMEOUT_S`                                          | `30`                    | Confirmé par T0.8, à revérifier sur le VPS                                 |
| `PARSER_MEMORY_MB`                                          | `512`                   | Issu de T0.8, à valider à T6.3 car `RLIMIT_AS` compte la mémoire virtuelle |
| `PARSER_MAX_FPS`                                            |                         | Plafond optionnel, vide par défaut : toutes les frames sont gardées        |
| `WORKER_CONCURRENCY`                                        | `1`                     | À fixer selon le VPS                                                       |
| `RAW_RETENTION_DAYS`                                        | `30`                    | Rétention des fichiers bruts                                               |
| `RAW_RETENTION_HEADER_ONLY_DAYS`                            | `180`                   | Rétention des `header_only` (D6)                                           |
| `OPERATOR_NAME`, `OPERATOR_EMAIL`, `HOSTING_INFO`           |                         | Mentions légales, jamais dans le code                                      |
| `LOG_LEVEL`                                                 | `INFO`                  | Niveau de journalisation                                                   |

Steam ne demande pas de clé en V1 (section 8.1). `.env` n'est jamais versionné, et en production les secrets sont gérés par Dokploy.

---

## Annexe C : décisions par défaut à confirmer

| #       | Décision retenue                                                                                                                                                                                                                                                                            | Raison                                                                                                                                                 | Alternative                                                                                                |
| ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------- |
| **D1**  | Stack alignée sur Untraded                                                                                                                                                                                                                                                                  | Section 1                                                                                                                                              | Fastify                                                                                                    |
| **D2**  | Pas de copie du code AGPL                                                                                                                                                                                                                                                                   | Section 1                                                                                                                                              | Copie si tu détiens les droits                                                                             |
| **D3**  | Autre émulateur S3 que MinIO                                                                                                                                                                                                                                                                | Section 1                                                                                                                                              | Ancienne image MinIO                                                                                       |
| **D4**  | **Tiers à ±1707** (`5120 / 3`, comme `CLAUDE.md`)                                                                                                                                                                                                                                           | Vrais tiers égaux et faciles à expliquer                                                                                                               | ±2300 de `subtr-actor`, la ligne des pads                                                                  |
| **D5**  | **À la connexion, tous les matchs anonymes sont rattachés** : vérifiés si l'identité correspond, sinon non vérifiés et visibles avec un libellé                                                                                                                                             | Lecture de la section 8.1 cohérente avec Q7                                                                                                            | Les laisser dans la session anonyme, puis les perdre à son expiration                                      |
| **D6**  | **`raw/` : 30 jours, 180 pour `header_only`** puis suppression. Métriques recalculées depuis le Parquet, conservé tant que le match existe.                                                                                                                                                 | Résout I5 tout en limitant les données de tiers                                                                                                        | 30 jours partout : pas de retraitement au-delà                                                             |
| **D7**  | **Bandes d'altitude** : sol `z ≤ 20`, air haut `z ≥ 642.775 + rayon de balle`, air bas entre les deux. **La conduite sur un mur compte comme de l'air**, avec mention à l'écran.                                                                                                            | Identique à `subtr-actor`, comparable                                                                                                                  | Détecter les murs par la position : plus juste, plus long                                                  |
| **D8**  | **Métriques calculées en Python**, comparées à `subtr-actor`                                                                                                                                                                                                                                | Respecte `CLAUDE.md`, garde la maîtrise des définitions. **Confirmé par le spike** : `StatsCollector` prend jusqu'à 197 s et 663 Mo sur un long replay | Tout calculer en Rust avec `StatsCollector` : écarté, incompatible avec le timeout de 30 s sur ces replays |
| **D9**  | **Analyse limitée au terrain standard** : playlists 1, 2, 3, 6, 8, 10, 11, 13 et 34 observées sur arène standard, sauf cartes hors standard (`ShatterShot_P` et autres à lister). Une position hors des bornes mesurées déclenche un signalement. Autres modes affichés en stats de header. | `game_class` ne distingue pas les modes (A8). Hoops, Rumble et Snow Day restent à tester avec de vrais replays                                         | Tout analyser au risque de chiffres faux                                                                   |
| **D10** | Identifiants de plateforme en clair en base, jamais renvoyés par l'API                                                                                                                                                                                                                      | Nécessaire à la correspondance, simple                                                                                                                 | Hachage par clé secrète, à réévaluer                                                                       |
| **D11** | Pas de RLS en V1 : `owned_match()` obligatoire et test transversal                                                                                                                                                                                                                          | Mode anonyme, moins de complexité                                                                                                                      | RLS comme Untraded : plus sûr, environ 1 jour de plus                                                      |
| **D12** | Pas de fusion de comptes en V1, liaison refusée si l'identifiant est déjà utilisé                                                                                                                                                                                                           | Cas rare, fusion risquée                                                                                                                               | Fusion avec confirmation                                                                                   |
| **D13** | `frames.parquet` en une table longue, balle dénormalisée                                                                                                                                                                                                                                    | Le plus simple à lire en `polars`, compression à mesurer                                                                                               | Fichiers séparés balle / joueurs                                                                           |
| **D14** | Sessions : jeton aléatoire haché en base au lieu d'un simple cookie signé                                                                                                                                                                                                                   | Révocable, effaçable                                                                                                                                   | Cookie signé seul                                                                                          |
| **D15** | « Vérifié » signifie seulement que l'identifiant présent dans le fichier correspond au compte connecté, sans preuve que le fichier est authentique                                                                                                                                          | I9, acceptable en V1                                                                                                                                   | Aucune alternative connue : les replays ne sont pas signés                                                 |
| **D16** | Temps de référence : `kickoff_waiting` + `active` pour boost et mouvement, `active` pour le positionnement, toujours hors démolition                                                                                                                                                        | Validé par le spike : mêmes masques que `subtr-actor`                                                                                                  | Jeu actif seul partout                                                                                     |
| **D17** | Purge et durées : valeurs de l'annexe B                                                                                                                                                                                                                                                     | Section 15                                                                                                                                             | À ta convenance                                                                                            |
| **D18** | Next.js, `polars`, Tailwind                                                                                                                                                                                                                                                                 | Défauts de `CLAUDE.md`                                                                                                                                 | SvelteKit (section 15)                                                                                     |
| **D19** | VPS et bucket dans l'UE                                                                                                                                                                                                                                                                     | RGPD                                                                                                                                                   | Autre région, à justifier                                                                                  |
| **D20** | **Un joueur anonymisé dans le jeu est affiché sous son `AnonymizedName`**, sauf pour lui-même une fois vérifié. Son identifiant reste stocké pour la vérification, jamais renvoyé par l'API.                                                                                                | Le replay expose son vrai pseudo alors que ce joueur a demandé l'inverse (A16)                                                                         | Afficher le pseudo du replay : plus simple, contraire à son choix                                          |

**Attendus de ta part** : nom, domaine et exploitant (E1) ; 10 replays récents (T0.2) ; textes de la politique de confidentialité, des CGU et des mentions légales (E5, section 11) ; comptes R2 et VPS et budget (T9.4, T9.5).

---

## Annexe D : explicitement hors périmètre

**Fonctionnalités reportées** (section 8.3) :

- analyse des buts encaissés, rotations, double commits, overcommits ;
- touches de balle dérivées, possession, kickoffs comme métriques ;
- vue 2D, timestamps cliquables ;
- benchmarks par rang, rang déclaré ;
- LLM, conseils, modèles (expected goals) ;
- app desktop, watcher, Stats API ;
- import ballchasing ;
- paiement, offre freemium.

**Exclus par ce plan** :

- modification du dépôt Untraded, `games/cs2/`, `apps/desktop/`, `packages/coaching/` ;
- paquet partagé avec Untraded ;
- fusion de comptes, équipes, workspaces, pages publiques, partage de match ;
- recherche par pseudo, profil de joueur tiers ;
- WebSocket, Redis, Kubernetes ;
- analytics tierces : l'usage se mesure par requêtes SQL ;
- synchronisation automatique du dossier Demos sans clic ;
- métriques pour les modes spéciaux.

**Interdits maintenus** (section 14) : aucune injection ni lecture mémoire du jeu, aucun scraping de sites tiers, pas de marque « Rocket League », « Psyonix » ou « Epic Games » dans le nom ou le logo.

---

## Annexe E : sources vérifiées

Code lu dans un clone temporaire, en lecture seule :

- [`boxcars`](https://github.com/nickbabcock/boxcars), commit `6f84377` : `CHANGELOG.md`, `Cargo.toml`, `src/parser.rs`, `src/data.rs`, `src/network/attributes.rs`.
- [`subtr-actor`](https://github.com/rlrml/subtr-actor), commit `ea9f34d` : `CHANGELOG.md`, `docs/replay-format-evolution.md`, `src/domain/`, `src/collector/replay_data.rs`, `src/stats/accumulators/`, `src/stats/calculators/`, `tests/post_eac_replay_fixture_test.rs`.
- [Untraded](https://github.com/untraded/untraded), commit `e77e840` : `CLAUDE.md`, `README.md`, `compose.yaml`, ADR 0001, 0004, 0005, 0006 et 0009, `db/.../0001_initial.sql`, `0009_erasure.sql`, `0010_uploads.sql`, `apps/worker/`, `apps/api/`, `.github/workflows/ci.yml`.

Fichiers examinés : en-têtes de 5 replays de 2026 issus de `subtr-actor` et de ton replay le plus récent de 2023, par un script temporaire qui n'affiche ni pseudo ni identifiant. **Aucun parsing `boxcars` ou `subtr-actor` n'a encore été exécuté : c'est l'objet de l'étape 0.**

Documentation :

- [Epic : Auth Web APIs](https://dev.epicgames.com/docs/web-api-ref/authentication)
- [Cloudflare R2 : URL pré-signées](https://developers.cloudflare.com/r2/api/s3/presigned-urls/)
- [MDN : `showDirectoryPicker`](https://developer.mozilla.org/en-US/docs/Web/API/Window/showDirectoryPicker)
- [Dokploy : domaines Docker Compose](https://docs.dokploy.com/docs/core/docker-compose/domains), [sauvegardes](https://docs.dokploy.com/docs/core/databases/backups)
- [MinIO : dépôt archivé](https://github.com/minio/minio)
- [Arctic : fournisseur Epic](https://arcticjs.dev/providers/epicgames) (source tierce, pour `userInfo`)
- [crates.io](https://crates.io), [PyPI](https://pypi.org), [npm](https://www.npmjs.com) : versions observées le 2026-11-06.
