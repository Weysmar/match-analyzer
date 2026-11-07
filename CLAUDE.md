# CLAUDE.md : outil d'analyse de replays Rocket League

> Document de référence pour le développement. À lire en entier avant toute tâche.
> Nom de code provisoire : `match-analyzer`. Le nom commercial ne doit **pas** contenir « Rocket League » (marque déposée).
> Plan et contrats détaillés : `docs/PLAN.md`. Mesures sur replays réels : `spikes/s0-parse/RAPPORT.md`. En cas de doute sur un détail d'implémentation, le plan fait foi.

---

## 1. Contexte et objectif

Construire une plateforme web qui analyse les fichiers de replay Rocket League (`.replay`) d'un joueur pour lui fournir :

1. des statistiques détaillées (boost, mouvement, positionnement, possession) ;
2. la détection de patterns tactiques (buts encaissés, rotations, double commits, gestion du boost) ;
3. à terme, des recommandations personnalisées, comparées à des benchmarks par rang.

L'architecture doit être **mutualisable** avec l'outil d'analyse CS2 [Untraded](https://github.com/untraded/untraded), développé en parallèle dans son propre dépôt : mêmes conventions et mêmes idées (comptes, stockage, jobs, dashboard, coaching), sans paquet partagé en V1. L'extraction d'une plateforme commune se décidera après la V1. Les dossiers `apps/` et `db/` d'Untraded sont en AGPL : **n'en copier aucun code**, n'en reprendre que les idées.

**Principe produit directeur : zéro installation pour essayer.** L'upload web est la porte d'entrée principale. L'app Windows ne vient qu'ensuite, pour automatiser.

---

## 2. Contraintes techniques à connaître

- **Pas d'API web officielle** pour récupérer les replays d'un joueur. La connexion Epic (OAuth) ne donne que l'identité (`basic_profile`, `friends_list`, `presence`), aucune donnée de jeu.
- **PC uniquement** : les replays sont des fichiers locaux dans `%USERPROFILE%\Documents\My Games\Rocket League\TAGame\Demos`. Les joueurs console n'ont pas accès à leurs fichiers.
- **Les replays ne sont pas sauvegardés automatiquement** : le joueur doit les sauvegarder en fin de match (ou via la sauvegarde rapide).
- **Easy Anti-Cheat actif depuis le 28/04/2026** : interdiction absolue de tout code injecté dans le processus du jeu. On lit uniquement des fichiers et, plus tard, la Stats API locale officielle.
- **Format `.replay` propriétaire et non documenté**, rétro-ingénié par la communauté. Deux parties :
  - **header** : métadonnées, score, buts, stats de fin de match par joueur, identifiants de plateforme (`OnlineID`, ou `PlayerID.EpicAccountId` pour Epic ; ce champ manque sur les anciens replays). Rapide à parser. La liste des joueurs peut être incomplète.
  - **network stream** : réplication réseau frame par frame (positions, rotations, vélocités, boost, sauts, démolitions, pads). Lourd et **susceptible de casser à chaque patch du jeu**.
- **Pas d'inputs fins de manette** dans les replays : on voit l'état résultant des voitures, pas les sticks.
- **Le rang/MMR n'est pas dans le fichier** : il faudra une autre source (déclaration du joueur dans un premier temps).
- Les positions des autres joueurs subissent la latence réseau du client qui a enregistré le replay.
- **Une grande partie des joueurs PC sont uniquement sur Epic** : depuis le passage en free-to-play (2020), le jeu n'est plus téléchargeable sur Steam pour les nouveaux joueurs. La connexion Epic est donc indispensable pour toucher le public, pas un bonus.

---

## 3. Stack retenue

| Couche                  | Choix                                                                                                     | Raison                                                                                                     |
| ----------------------- | --------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| Front web               | Next.js (TypeScript, App Router) + Tailwind                                                               | Écosystème, SSR, i18n                                                                                      |
| API                     | Python 3.14 + FastAPI                                                                                     | Même langage que le worker et les migrations, aligné sur Untraded                                          |
| File de jobs (V1)       | Table PostgreSQL + `SELECT ... FOR UPDATE SKIP LOCKED`                                                    | Un composant de moins que Redis, suffisant en V1                                                           |
| Parser                  | Rust : `boxcars` + `subtr-actor`, exposé en CLI `rl-parse`                                                | Parsers de référence, rapides, fuzzés                                                                      |
| Analyse                 | Python 3.14 : `polars`, `numpy` si nécessaire                                                             | Data science, futur ML                                                                                     |
| Base de données         | PostgreSQL 16                                                                                             | Comptes, matchs, métriques agrégées                                                                        |
| Données frame par frame | Fichiers Parquet dans le stockage objet                                                                   | Volume, lecture colonnaire                                                                                 |
| Stockage objet          | Émulateur S3 en local (voir `docs/decisions/`), Cloudflare R2 en prod                                     | MinIO est archivé. Pas de frais de sortie en prod                                                          |
| Auth                    | Mode sans compte + Steam OpenID + Epic OAuth (activé derrière un feature flag dès la validation par Epic) | Steam ne demande aucune validation ; Epic impose une Brand Review de plusieurs semaines (voir section 8.4) |
| Infra                   | Docker Compose en local (WSL2), VPS avec Dokploy en prod                                                  | Parsing de fichiers hostiles hors du réseau domestique                                                     |
| App desktop (V3)        | Tauri (Rust)                                                                                              | Embarque le parser Rust, app légère                                                                        |

---

## 4. Structure du dépôt (monorepo)

```
match-analyzer/
├── CLAUDE.md
├── README.md
├── .env.example
├── justfile
├── compose.dev.yaml            # postgres et S3 de développement
├── compose.yaml                # production (étape 9)
├── apps/
│   ├── web/                    # Next.js
│   └── desktop/                # Tauri (V3, ne pas créer en V1)
├── services/
│   ├── api/                    # FastAPI : auth, upload, endpoints
│   └── worker/                 # Python : orchestration des jobs
├── games/
│   └── rocket-league/
│       ├── parser/             # Rust : crate + binaire rl-parse
│       └── analysis/           # Python : package rl_analysis
├── packages/
│   ├── schemas/                # JSON Schema partagés (source de vérité des formats)
│   └── coaching/               # V4 : génération de conseils, ne pas créer en V1
├── db/                         # migrations Alembic versionnées (SQL)
├── docs/                       # PLAN.md, decisions/
├── spikes/                     # code jetable, chaque spike finit par un rapport
└── tests/
    └── fixtures/replays/       # replays de test, jamais versionnés (identifiants de tiers)
```

---

## 5. Pipeline de traitement

```
Upload (web) ──► URL pré-signée API ──► stockage objet (incoming/<upload_id>)
                  │
                  └──► job "parse" en base
                           │
                     Worker Python : contrôle, hash réel, déplacement vers raw/<sha256>.replay
                           │
                  rl-parse (Rust, sous-processus, timeout + limite mémoire)
                           │
                  ├── header.json  ──► tables matches / match_players
                  ├── frames.parquet ──► stockage objet (frames/<match_id>.parquet)
                  └── events.json ──► stockage objet + table match_events
                           │
                     job "analyze"
                           │
                  rl_analysis (Python) ──► table player_match_metrics (+ events)
                           │
                     Dashboard web
```

### 5.1 Déduplication

Un même match peut être uploadé par plusieurs coéquipiers. Dédupliquer :

1. par `sha256` du fichier (même fichier exact) ;
2. par identifiant de match du header (`MatchGUID` + joueurs + score quand il est présent, sinon combinaison date + joueurs + score). Le hash fourni par le navigateur ne fait jamais foi.

Un match dédupliqué est lié à chaque utilisateur qui l'a uploadé.

### 5.2 Versionnement (obligatoire)

Chaque match stocke `parser_version` et `analysis_version`. Toute modification du parser ou d'un calcul incrémente la version correspondante. Un script `reprocess` doit permettre de relancer le traitement sur les matchs dont la version est obsolète, ou sur une plage de `BuildID` du jeu.

### 5.3 Robustesse face aux patchs

- Si le network stream échoue mais que le header passe : enregistrer le match avec `status = 'header_only'`, afficher les stats de base, et le retraiter plus tard.
- Logger le `BuildID` / version du jeu de chaque replay pour repérer rapidement un patch cassant.

---

## 6. Formats de données

Les schémas font foi dans `packages/schemas/`. Contrats détaillés à l'étape 2 de `docs/PLAN.md` : `header.json`, `frames.parquet`, `events.json` et codes de sortie de `rl-parse`.

Points à ne pas oublier, mesurés sur replays réels :

- **Pondérer par `dt_s`**, jamais par nombre de frames : elles sont irrégulières malgré `RecordFPS` = 30.
- **`demolished`** : fenêtre de 3,2 s après `DemolishInfo`, arrêtée au changement de phase. Une voiture démolie reste « présente » avec une position fausse.
- **Pads** : dédupliquer les événements bruts par pad, séquence et joueur.
- **Pas de `on_ground`** dans les données : bandes d'altitude à l'analyse, la conduite sur un mur compte comme de l'air.
- **Pas de `StatsCollector` ni de timeline `subtr-actor` en production** (jusqu'à 197 s et 663 Mo sur un long replay). Ils servent de référence de test.
- **`rl-parse` n'émet que ses propres codes d'erreur** : les erreurs de `subtr-actor` peuvent citer des pseudos.

---

## 7. Constantes du terrain (vérifiées sur replays réels)

> En unités Unreal (uu). Mesures dans `spikes/s0-parse/RAPPORT.md`. À centraliser dans `rl_analysis/constants.py`.

- Terrain : `x ∈ [-4096, 4096]`, `y ∈ [-5120, 5120]`, plafond `z ≈ 2044`. Hors du terrain standard : voitures jusqu'à `|y|` ≈ 5990 et balle jusqu'à `|y|` ≈ 5215, dans les buts.
- L'équipe 0 (bleue) défend `y < 0`.
- Tiers du terrain : coupures à `y = ±5120 / 3` (`subtr-actor` utilise ±2300).
- Vitesse max voiture = 2300 uu/s. Seuil supersonique = 2200 uu/s : **convention**, non vérifiable sur les données.
- Boost : 0 à 255 dans les replays, 85 au kickoff, normalisé sur 0 à 100 par `rl-parse`.
- Temps de référence : `kickoff_waiting` + `active` pour le boost et le mouvement, `active` pour le positionnement, toujours hors démolition.

---

## 8. Périmètre V1 (MVP) : ce qu'il faut construire maintenant

Objectif : valider que des joueurs utilisent l'outil. **Ne rien développer hors de cette liste sans demande explicite.**

### 8.1 Fonctionnalités

1. **Compte, sans barrière à l'entrée** :
   - **Mode sans compte** : le joueur dépose un replay et voit son analyse immédiatement, après avoir indiqué une fois « lequel de ces joueurs es-tu ? ». Les uploads sont rattachés à une session anonyme (cookie signé, durée limitée).
   - **Connexion pour sauvegarder l'historique**, proposée après la première analyse :
     - **Steam OpenID** : fournisseur `https://steamcommunity.com/openid`, l'identifiant renvoyé contient le SteamID64 (`https://steamcommunity.com/openid/id/<steamid>`). Utiliser un bouton officiel Steam. Pas de clé Steam Web API nécessaire en V1 (le pseudo est dans le replay).
     - **Epic OAuth** (OIDC, scope `basic_profile`, endpoint `userInfo`) : à développer dès la V1 mais **activé derrière un feature flag** tant que la Brand Review n'est pas validée (section 8.4).
   - **Rattachement** : à la connexion, tous les matchs de la session anonyme sont rattachés au compte. Ils sont vérifiés si l'identifiant de plateforme du joueur choisi correspond à celui du compte connecté. Sinon, ils restent marqués « non vérifiés ».
   - Un utilisateur peut lier Steam **et** Epic au même compte (table `linked_accounts`).
   - Une identité choisie ou mémorisée ne vérifie **jamais** un match. « Mes stats » affiche les matchs non vérifiés avec un libellé et un filtre. Les futurs benchmarks ne s'appuieront que sur des matchs **vérifiés**.
2. **Upload web** :
   - glisser-déposer multi-fichiers (jusqu'à 50 fichiers par lot) ;
   - bouton « choisir mon dossier Demos » via File System Access API (Chrome/Edge), avec import des seuls nouveaux fichiers à chaque visite ; repli automatique sur l'upload classique sur les autres navigateurs ;
   - barre de progression par fichier et statut de traitement.
3. **Identification automatique du joueur** : faire correspondre l'identifiant de plateforme du compte connecté avec les joueurs du header. Si aucune correspondance, demander une fois « lequel de ces joueurs es-tu ? » et mémoriser l'identifiant.
4. **Fiche match** : score, tableau des joueurs, métriques V1 (section 8.2), timeline des buts.
5. **Vue « mes stats »** : moyennes sur les N derniers matchs, évolution simple dans le temps.
6. **Interface FR + EN** dès le départ (i18n), responsive mobile.

### 8.2 Métriques V1 (par joueur et par match)

- **Boost** : consommation par minute, boost moyen, % de temps à 0, % de temps à 100, nombre de gros pads / petits pads, pads pris dans la moitié adverse
- **Mouvement** : vitesse moyenne, % de temps supersonique, % au sol / en l'air bas / en l'air haut
- **Positionnement** : % de temps dans chaque tiers (relatif à son équipe), % devant / derrière la balle, distance moyenne à la balle, % de temps joueur le plus en arrière de son équipe
- **Événements** : démolitions infligées / subies

Chaque métrique doit avoir : une définition écrite dans le code (docstring), un test unitaire sur données synthétiques, et une vérification sur au moins un replay réel.

### 8.3 Hors périmètre V1

Analyse des buts encaissés, rotations, benchmarks par rang, LLM, app desktop, Stats API, import ballchasing, paiement.

### 8.4 Démarche Epic Account Services (à lancer en parallèle du développement)

C'est le délai le plus long du projet : **la soumission doit partir dès le début**, sans attendre que le code soit prêt. Tant que la Brand Review n'est pas validée, la connexion Epic ne fonctionne qu'en interne.

Étapes dans le Epic Developer Portal :

1. Créer le compte développeur et l'**organisation**.
2. Ajouter et **vérifier le domaine** du produit sur l'organisation (la vérification prend du temps ; sans domaine vérifié, les joueurs voient un avertissement à la connexion).
3. Créer le **produit**, puis une **application Epic Account Services**.
4. Configurer les trois blocs jusqu'à ce qu'ils soient tous marqués « Configured » : **Brand Settings**, **Permissions** (Basic Profile), **Linked Clients** (créer un client et vérifier que sa policy autorise bien le scope `basic_profile`).
5. Remplir le questionnaire de classification d'âge s'il est demandé (sinon `basic_profile` peut rester indisponible avec une erreur `scope_not_found`).
6. Soumettre la **Brand Review**.

Checklist à préparer **avant** la première soumission (les refus sont parfois peu explicites, viser un dossier complet du premier coup) :

- [ ] Nom définitif du produit (sans « Rocket League », « Psyonix » ni « Epic Games »)
- [ ] Nom de domaine définitif, en HTTPS, avec une page d'accueil réelle
- [ ] Logo et icône aux formats demandés
- [ ] Politique de confidentialité en ligne (mentionner les données reçues d'Epic : identifiant de compte et nom d'affichage)
- [ ] Conditions générales d'utilisation en ligne
- [ ] URL(s) de redirection OAuth définitives (prod), plus une URL de dev si autorisé
- [ ] Adresse e-mail de contact surveillée (les retours Epic arrivent parfois uniquement dans le portail : le consulter régulièrement)

Côté code : identifiants Epic (`EPIC_CLIENT_ID`, `EPIC_CLIENT_SECRET`, `EPIC_REDIRECT_URI`) dans `.env`, flag `FEATURE_EPIC_LOGIN=false` par défaut.

---

## 9. Roadmap après V1 (pour contexte, ne pas implémenter)

- **V2, différenciation** : touches de balle dérivées (variation de vélocité de la balle à proximité d'une voiture), possession, analyse des 5 à 10 s avant chaque but encaissé, détection des double commits et overcommits, kickoffs. Timestamps cliquables + vue 2D du terrain.
- **V3, fidélisation** : app Tauri (watcher du dossier Demos, parsing local, upload du JSON, écoute de la Stats API officielle sur `127.0.0.1:49123`), import ballchasing par token API, comparaison par rang déclaré.
- **V4, intelligence** : modèles (expected goals, valeur de possession), conseils rédigés par LLM **uniquement à partir de faits calculés et horodatés**, mis en cache par match, offre freemium.

---

## 10. Sécurité

Les fichiers uploadés viennent d'inconnus : les traiter comme hostiles.

- Taille max par fichier : 20 Mo (un replay pèse généralement 1 à 3 Mo). Vérifier l'en-tête du fichier, pas seulement l'extension.
- Parser dans un sous-processus isolé avec **timeout** (30 s) et **limite mémoire** ; jamais dans le processus de l'API.
- Upload vers stockage objet via URL pré-signée à durée courte ; l'API ne relaie pas les octets si possible.
- Rate limiting par utilisateur et par IP sur l'upload et l'auth.
- Aucun secret dans le dépôt : tout passe par `.env` (et `.env.example` documenté).
- Requêtes SQL paramétrées uniquement. Validation des entrées API par schéma.
- En-têtes de sécurité HTTP (CSP, HSTS, etc.) sur le front.

---

## 11. RGPD et données personnelles

- Un replay contient les pseudos et identifiants des **autres joueurs**, qui n'ont rien accepté :
  - n'afficher les adversaires et coéquipiers que par pseudo dans la fiche du match de l'uploadeur, jamais leur identifiant de plateforme ;
  - un joueur anonymisé dans le jeu (`bAnonymizeToOpponents` ou `bAnonymizeToTeammates`) est affiché sous son `AnonymizedName`, car le replay expose quand même son vrai pseudo ;
  - aucune page publique de profil pour un joueur qui n'a pas de compte ;
  - pas de recherche par pseudo d'un joueur tiers.
- Droit à l'effacement : suppression du compte = suppression des liens utilisateur/match ; un match n'est supprimé physiquement que s'il n'est plus lié à aucun utilisateur.
- Les replays bruts sont purgés après 30 jours (configurable) une fois les données dérivées produites, et après 180 jours pour un match `header_only`, gardé pour retraitement.
- Prévoir les pages politique de confidentialité et mentions légales (contenu à fournir par Vincent).

---

## 12. Conventions de code

- **TypeScript** : `strict: true`, Biome, pas de `any` non justifié.
- **Rust** : stable, `cargo fmt`, `cargo clippy -- -D warnings`, pas de `unsafe`.
- **Python** : 3.14, `uv`, `ruff` (lint + format), `mypy --strict`, `pytest`.
- **SQL** : migrations Alembic versionnées dans `db/`, jamais de modification manuelle du schéma.
- **Commits** : Conventional Commits (`feat:`, `fix:`, `chore:`...), petits et atomiques.
- **Tests** : chaque module a ses tests ; les fixtures de replays réels vont dans `tests/fixtures/replays/`.
- **Langue** : code et noms en anglais, commentaires en anglais, textes d'interface via i18n (FR/EN).
- Un `justfile` à la racine : `just dev-up`, `just test`, `just lint`, `just check`, `just reprocess`. Le développement se fait sous WSL2, dans le système de fichiers Linux.

---

## 13. Ordre des premières tâches

Avancer étape par étape, faire valider chaque étape avant de passer à la suivante. Détail des tâches dans `docs/PLAN.md`.

1. **Scaffold** : monorepo, `compose.dev.yaml` (PostgreSQL, S3), `.env.example`, `justfile`, CI de lint/tests.
2. **Parser Rust `rl-parse`** :
   - `--header` → `header.json` ;
   - `--frames` → `frames.parquet` + `events.json` ;
   - tests sur les replays de `tests/fixtures/replays/` ;
   - gestion explicite du cas « header OK, network KO ».
3. **Schémas** dans `packages/schemas/` + validation de la sortie du parser contre ces schémas.
4. **Base de données** : migrations de l'annexe A de `docs/PLAN.md`, dont `users`, `linked_accounts`, `anonymous_sessions`, `uploads`, `matches`, `match_players`, `user_matches` (avec un champ `verified`), `jobs`, `player_match_metrics`.
5. **API** : sessions anonymes, auth Steam OpenID, auth Epic OAuth derrière `FEATURE_EPIC_LOGIN`, rattachement des matchs anonymes à la connexion (section 8.1), URL pré-signée d'upload, création de job, endpoints liste/détail des matchs.
6. **Worker Python** : boucle de jobs, appel de `rl-parse`, insertion header, stockage Parquet, déduplication.
7. **`rl_analysis`** : constantes vérifiées (section 7), puis métriques V1 une par une avec tests.
8. **Front** : page d'upload (drag & drop + File System Access), fiche match, vue « mes stats ».
9. **Production et conformité** : déploiement Dokploy + R2, sauvegardes, purge, effacement, retraitement.

---

## 14. Interdits

- Aucune injection ou lecture mémoire du processus Rocket League.
- Aucun scraping de sites tiers (trackers de rang, etc.) sans accord explicite de Vincent et vérification des CGU.
- Pas de « Rocket League », « Psyonix » ou « Epic Games » dans le nom ou le logo du produit.
- Ne pas modifier le dépôt Untraded depuis ce projet, ni y copier son code AGPL.
- Ne pas ajouter de dépendance lourde sans le justifier dans la PR / le commit.

---

## 15. Questions ouvertes (à trancher avec Vincent)

- **Nom du produit et nom de domaine : à trancher en priorité**, car ils bloquent la soumission Epic (section 8.4).
- Comparaison de l'identifiant Epic d'un replay avec un vrai `account_id` (T0.7 du plan).
- Replays récents en 1v1 et en 3v3 : le corpus de Vincent ne couvre que du 2v2 classé.
