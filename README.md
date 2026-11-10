# match-analyzer

Nom de code provisoire. Plateforme web qui analyse les fichiers de replay (`.replay`) d'un joueur : statistiques détaillées, situations de jeu (pertes de balle, kickoffs, duels, double commits, overcommits), contexte de chaque but encaissé et vue 2D du match.

Références : `CLAUDE.md` (le projet et ses règles), `docs/PLAN.md` (V1) et `docs/PLAN-V2.md` (V2), avec toutes les décisions prises en route.

---

## Installer et tester en local

Ce guide part d'un PC vierge et va jusqu'au site qui tourne sur `http://localhost:3000`, où l'on peut déposer ses replays, voir les fiches de match et ses statistiques.

En local, quatre éléments tournent ensemble :

| Élément | Rôle | Lancé par |
| --- | --- | --- |
| PostgreSQL et un émulateur S3 (RustFS) | Base de données et stockage des fichiers | Docker, `just dev-up` |
| L'API (FastAPI) | Comptes, uploads, matchs, statistiques | `just api` |
| Le worker et le parser `rl-parse` | Lecture et analyse des replays | `just worker` |
| Le site (Next.js) | L'interface | `just web` |

### 1. Systèmes pris en charge

- **Windows 10 ou 11** : **via WSL2**, avec Ubuntu. C'est ainsi que le projet se développe : tout tourne dans le Linux de WSL, le navigateur reste celui de Windows.
- **Linux** : Ubuntu 24.04 ou plus récent.
- **macOS** : non pris en charge. Le worker isole le parser avec des limites système propres à Linux.

Prévoir au moins 8 Go de RAM et 10 Go d'espace libre. La première compilation du parser Rust prend quelques minutes.

### 2. Windows seulement : installer WSL2 et Ubuntu

Dans PowerShell, en administrateur :

```powershell
wsl --install -d Ubuntu-24.04
```

Redémarre si Windows le demande, puis ouvre « Ubuntu » depuis le menu Démarrer et choisis un nom d'utilisateur et un mot de passe Linux.

**Important** : travaille toujours dans le système de fichiers Linux (`~/code/...`), jamais dans `/mnt/c/...`. Sous `/mnt/c`, tout est beaucoup plus lent et les droits de fichiers posent problème.

Toutes les commandes qui suivent se tapent **dans le terminal Ubuntu**.

### 3. Installer les outils

| Outil | Version | Remarque |
| --- | --- | --- |
| Git | récente | |
| Docker avec Compose v2 | récente | Pour PostgreSQL et le S3 |
| Rust (`rustup`) | 1.99.1 | Installée automatiquement par `rust-toolchain.toml` |
| `uv` | 0.13 ou plus | Installe aussi Python 3.14 tout seul |
| Node.js | 22 ou plus | |
| `pnpm` | 12.18.0 | Fourni par Corepack, version fixée par `package.json` |
| `just` | 1.x | Lance les recettes du projet |

**Paquets de base :**

```bash
sudo apt-get update
sudo apt-get install -y git curl build-essential pkg-config ca-certificates
```

**Docker :**

- **Windows (WSL2)** : au choix,
  - Docker Desktop pour Windows, avec **Settings → Resources → WSL integration** activé pour ta distribution Ubuntu ;
  - ou Docker Engine installé directement dans Ubuntu, comme sous Linux.
- **Linux** : installe Docker Engine en suivant la documentation officielle (https://docs.docker.com/engine/install/ubuntu/), puis autorise ton utilisateur à s'en servir sans `sudo`, et rouvre le terminal :

  ```bash
  sudo usermod -aG docker "$USER"
  ```

Vérifie :

```bash
docker run --rm hello-world
docker compose version
```

**Rust :**

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal
source "$HOME/.cargo/env"
```

La bonne version (1.99.1, avec `clippy` et `rustfmt`) s'installe d'elle-même à la première commande lancée dans le dépôt.

**uv (Python) :**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Rouvre le terminal ensuite. `uv` télécharge Python 3.14 tout seul si besoin.

**Node.js et pnpm :** installe Node.js 22 ou plus, depuis https://nodejs.org ou avec `nvm`, puis active pnpm par Corepack :

```bash
node --version
corepack enable pnpm
```

La première commande doit afficher v22 ou plus. Selon l'installation de Node, `corepack enable` peut demander `sudo`.

**just :**

```bash
sudo apt-get install -y just
```

Si ta version d'Ubuntu ne le propose pas : `cargo install just`.

**Vérification :**

```bash
git --version && docker compose version && cargo --version && uv --version && node --version && just --version
```

### 4. Récupérer le code

Le dépôt est public :

```bash
mkdir -p ~/code && cd ~/code
git clone https://github.com/Weysmar/match-analyzer.git
cd match-analyzer
```

### 5. Configurer

```bash
cp .env.example .env
```

Les valeurs par défaut conviennent telles quelles en local : mots de passe de développement, ports 5432 (PostgreSQL), 9000 (S3), 8000 (API) et 3000 (site). Le fichier `.env` n'est jamais versionné.

Si un port est déjà pris sur ta machine, change `DEV_POSTGRES_PORT` ou `DEV_S3_PORT` dans `.env`, ainsi que les URL qui les utilisent (`DATABASE_URL`, `API_DATABASE_URL`, `WORKER_DATABASE_URL`, `TEST_DATABASE_URL`, `S3_ENDPOINT`, `S3_PUBLIC_ENDPOINT`).

### 6. Installer les dépendances

```bash
just install
```

Cette recette installe les paquets Python (`uv sync`) et JavaScript (`pnpm install`), aux versions exactes des fichiers de verrouillage.

### 7. Démarrer la base et le stockage

```bash
just dev-up
```

Cette commande :

1. démarre PostgreSQL et RustFS dans Docker, accessibles seulement depuis ta machine ;
2. crée le bucket S3 et sa règle CORS, qui autorise le site à y envoyer les fichiers et à y lire la vue 2D des matchs ;
3. applique les migrations de la base et crée les rôles `ma_api` et `ma_worker`.

Les données sont gardées entre deux démarrages. Sous WSL, les conteneurs s'arrêtent quand WSL s'arrête : relance `just dev-up` à chaque session.

### 8. Lancer l'application

Ouvre **trois terminaux**, chacun dans `~/code/match-analyzer`.

**Terminal 1, l'API :**

```bash
just api
```

Elle répond sur `http://127.0.0.1:8000`, avec sa documentation interactive sur `http://127.0.0.1:8000/api/docs`.

**Terminal 2, le worker :**

```bash
just worker
```

Le premier lancement compile le parser Rust en mode release, ce qui prend quelques minutes. Les suivants démarrent tout de suite.

**Terminal 3, le site :**

```bash
just web
```

Ouvre ensuite **`http://localhost:3000`** dans ton navigateur. Sous Windows, le navigateur Windows atteint directement les services de WSL.

**Utilise bien `localhost` et pas `127.0.0.1`** : le stockage n'accepte les envois que depuis l'adresse déclarée dans `SITE_URL` (`http://localhost:3000`).

### 9. Utiliser le site

1. **Analyser** : dépose un ou plusieurs fichiers `.replay`, jusqu'à 50 à la fois. Sur PC, ils se trouvent dans `Documents\My Games\Rocket League\TAGame\Demos`. Pense à sauvegarder le replay en fin de match.
   - Sur Chrome et Edge, le bouton **« Choisir mon dossier Demos »** ouvre directement ce dossier. Aux visites suivantes, « Importer les nouveaux replays » n'envoie que les nouveaux fichiers.
   - Chaque fichier passe par « Envoi », « Analyse en cours », puis « Prêt ».
2. **Voir le match** : réponds une fois à « Lequel de ces joueurs es-tu ? », le choix est mémorisé. La fiche montre :
   - le score, les joueurs et la chronologie des buts ;
   - la **vue 2D** du match, avec un lien « Revoir » sur chaque but ;
   - l'**analyse** : possession, kickoffs, duels, et les situations détectées, chacune avec « Revoir » ;
   - les **buts encaissés** : pour chaque but, les causes repérées et les faits des 10 secondes avant ;
   - les **statistiques détaillées** par joueur ;
   - « Comment c'est détecté » et « Comment c'est calculé » : chaque métrique et chaque situation en une phrase.
3. **Mes stats** : moyennes sur tes derniers matchs, évolution d'une statistique, et causes de tes buts encaissés.
4. **Se connecter** (facultatif) : avec Steam, depuis l'en-tête ou depuis l'invitation sous un match. Les matchs de la session sans compte sont alors rattachés au compte. La connexion Epic reste désactivée (`FEATURE_EPIC_LOGIN=false`) tant qu'Epic n'a pas validé l'application.
5. **Paramètres** : comptes liés, et suppression du compte ou des données de la session.

Pour suivre la file de traitement :

```bash
just worker-status
```

### 10. Étiqueter les détections (développement)

Avec `just web`, et seulement en développement, chaque fiche de match a un lien **« Étiqueter les situations »**. Il mène à `/matches/<id>/labels`, qui a trois onglets :

| Onglet | Ce que tu juges | Ce que le rapport en tire |
| --- | --- | --- |
| Détections | Chaque situation détectée : vraie, fausse ou incertaine | La précision de chaque détecteur |
| Buts encaissés | À l'aveugle, pour chaque but : chacune des 9 causes était-elle là ? | La précision et le rappel de chaque cause |
| Fenêtres de jeu | À l'aveugle, 10 s de jeu : une perte de balle, un double commit, un overcommit ? | Le rappel de chaque détecteur |

Clique sur **« Exporter »** avant de changer de match : les verdicts vont dans `tests/fixtures/labels/`, jamais versionné. Puis :

```bash
just v2-report
```

### 11. Arrêter

- Arrête l'API, le worker et le site avec `Ctrl+C` dans chaque terminal.
- Arrête PostgreSQL et le S3, en gardant les données :

  ```bash
  just dev-down
  ```

- **Repartir de zéro** supprime **toutes** les données locales (base et fichiers) :

  ```bash
  docker compose -f compose.dev.yaml down -v
  just dev-up
  ```

### 12. Mettre à jour après un `git pull`

```bash
git pull
just install
just db-migrate
```

Si l'analyse a changé de version, relance le traitement des matchs déjà importés, avec le worker en marche :

```bash
just reprocess --analysis-outdated
```

Pour une nouvelle version du parser, c'est `just reprocess --parser-outdated`, à lancer avant.

### 13. Lancer les tests (facultatif)

| Commande | Ce qu'elle vérifie | Prérequis |
| --- | --- | --- |
| `just check` | Lint, types et tests unitaires (Rust, Python, TypeScript) | Aucun |
| `just test-db` | Base de données, API et worker | `just dev-up` |
| `just test-s3` | Stockage S3 réel | `just dev-up` |
| `just test-replays` | Parser et métriques sur de vrais replays, comparés à `subtr-actor` (plusieurs minutes) | Le corpus de replays |
| `just test-pipeline` | De vrais replays de l'API à la base | `just dev-up` et le corpus |
| `just test-e2e` | Parcours complet dans un navigateur, FR et EN, sur mobile | `just dev-up`, le corpus et les bibliothèques de Chromium |

La CI de GitHub ne lance que les vérifications sans replay : le dépôt est public, et les replays contiennent les pseudos d'autres joueurs. Les tests sur replays tournent en local, à la demande. Pour récupérer les replays publics du corpus de test :

```bash
just corpus-fetch
```

Pour `just test-e2e`, Chromium a besoin de quelques bibliothèques système :

```bash
sudo apt-get install -y libnss3 libnspr4 libasound2t64
```

Sur Ubuntu 22.04, le dernier paquet s'appelle `libasound2`. Arrête d'abord l'API, le worker et le site : le test lance les siens sur les mêmes ports.

### 14. En cas de problème

| Symptôme | Cause probable | Solution |
| --- | --- | --- |
| `just dev-up` échoue sur un port déjà utilisé | Un autre PostgreSQL ou service occupe 5432 ou 9000 | Changer les ports dans `.env` (étape 5) |
| `permission denied` sur Docker | Utilisateur hors du groupe `docker` | `sudo usermod -aG docker "$USER"`, puis rouvrir le terminal |
| Les fichiers restent bloqués sur « Envoi » ou « Échec : l'envoi a échoué » | Site ouvert sur `127.0.0.1` au lieu de `localhost`, ou S3 arrêté | Ouvrir `http://localhost:3000`, relancer `just dev-up` |
| Les fichiers restent sur « Analyse en cours » | Le worker ne tourne pas | `just worker`, puis `just worker-status` |
| `PARSER_BIN is not an executable program` | Worker lancé sans `just` | Toujours passer par `just worker` |
| L'en-tête n'affiche ni session ni compte, les pages sont vides | L'API ne tourne pas | `just api` |
| La page d'étiquetage répond 404 | Site lancé en production (`just web-build`) | Le lancer avec `just web` |
| Lenteur extrême sous Windows | Projet cloné sous `/mnt/c/...` | Le recloner dans `~/code` |
| `just test-e2e` : `libnspr4.so: cannot open shared object file` | Bibliothèques de Chromium absentes | Voir l'étape 13 |
| Connexion Steam : retour sur l'accueil avec « La connexion n'a pas abouti » | Session de connexion expirée (10 minutes) ou Steam injoignable | Recommencer la connexion |

---

## Commandes utiles

```bash
just            # la liste de toutes les recettes
just check      # lint, types et tests unitaires
just fmt        # formatage automatique
just openapi    # régénère openapi.json et les types de l'API pour le site
```

Les replays ne sont jamais versionnés : `just corpus-check` vérifie le corpus local contre `tests/fixtures/manifest.toml`.
