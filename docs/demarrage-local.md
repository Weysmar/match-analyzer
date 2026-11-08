# Lancer le projet en local

Ce guide part d'un PC vierge et va jusqu'au site qui tourne sur `http://localhost:3000`, où l'on peut déposer ses replays, voir les fiches de match et ses statistiques.

En local, quatre éléments tournent ensemble :

| Élément | Rôle | Lancé par |
| --- | --- | --- |
| PostgreSQL et un émulateur S3 (RustFS) | Base de données et stockage des fichiers | Docker, `just dev-up` |
| L'API (FastAPI) | Comptes, uploads, matchs, statistiques | `just api` |
| Le worker et le parser `rl-parse` | Lecture et analyse des replays | `just worker` |
| Le site (Next.js) | L'interface | `just web` |

---

## 1. Systèmes pris en charge

- **Linux** : Ubuntu 24.04 ou plus récent, recommandé.
- **Windows 10 ou 11** : **via WSL2**, avec Ubuntu. Le projet se développe ainsi : tout se passe dans le Linux de WSL, le navigateur reste celui de Windows.
- **macOS** : non pris en charge. Le worker isole le parser avec des limites système propres à Linux.

Prévoir au moins 8 Go de RAM et 10 Go d'espace libre. La première compilation du parser Rust prend quelques minutes.

---

## 2. Windows seulement : installer WSL2 et Ubuntu

Dans PowerShell, en administrateur :

```powershell
wsl --install -d Ubuntu-24.04
```

Redémarre si Windows le demande, puis ouvre « Ubuntu » depuis le menu Démarrer et choisis un nom d'utilisateur et un mot de passe Linux.

**Important** : travaille toujours dans le système de fichiers Linux (`~/code/...`), jamais dans `/mnt/c/...`. Sous `/mnt/c`, tout est beaucoup plus lent et les droits de fichiers posent problème.

Toutes les commandes qui suivent se tapent **dans le terminal Ubuntu**.

---

## 3. Installer les outils

Versions attendues :

| Outil | Version | Remarque |
| --- | --- | --- |
| Git | récente | |
| Docker avec Compose v2 | récente | Pour PostgreSQL et le S3 |
| Rust (`rustup`) | 1.99.1 | Installée automatiquement par `rust-toolchain.toml` |
| `uv` | 0.13 ou plus | Installe aussi Python 3.14 tout seul |
| Node.js | 22 ou plus | |
| `pnpm` | 12.18.0 | Fourni par Corepack, version fixée par `package.json` |
| `just` | 1.x | Lance les recettes du projet |

### Paquets de base

```bash
sudo apt-get update
sudo apt-get install -y git curl build-essential pkg-config ca-certificates
```

### Docker

- **Linux** : installer Docker Engine en suivant la documentation officielle (https://docs.docker.com/engine/install/ubuntu/), puis autoriser ton utilisateur à s'en servir sans `sudo`. Ferme ensuite le terminal et rouvre-le.

  ```bash
  sudo usermod -aG docker "$USER"
  ```

- **Windows (WSL2)** : au choix,
  - Docker Desktop pour Windows, avec **Settings → Resources → WSL integration** activé pour ta distribution Ubuntu ;
  - ou Docker Engine installé directement dans Ubuntu, comme sous Linux.

Vérifie :

```bash
docker run --rm hello-world
docker compose version
```

### Rust

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal
source "$HOME/.cargo/env"
```

La bonne version (1.99.1, avec `clippy` et `rustfmt`) s'installe d'elle-même à la première commande lancée dans le dépôt.

### uv (Python)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Rouvre le terminal ensuite. `uv` télécharge Python 3.14 tout seul si besoin.

### Node.js et pnpm

Installe Node.js 22 ou plus, depuis https://nodejs.org ou avec `nvm`, puis active pnpm par Corepack :

```bash
node --version          # v22 ou plus
corepack enable pnpm    # pnpm prend la version fixée par le projet (12.18.0)
```

Selon l'installation de Node, `corepack enable` peut demander `sudo`.

### just

```bash
sudo apt-get install -y just
```

Si ta version d'Ubuntu ne le propose pas : `cargo install just`.

### Vérification

```bash
git --version && docker compose version && cargo --version && uv --version && node --version && just --version
```

---

## 4. Récupérer le code

Le dépôt est privé : il faut un compte GitHub qui y a accès. Le plus simple est la CLI GitHub (`sudo apt-get install -y gh`), qui configure aussi Git :

```bash
gh auth login
mkdir -p ~/code && cd ~/code
git clone https://github.com/Weysmar/match-analyzer.git
cd match-analyzer
```

Avec une clé SSH déjà enregistrée sur GitHub, `git clone git@github.com:Weysmar/match-analyzer.git` marche aussi.

---

## 5. Configurer

```bash
cp .env.example .env
```

Les valeurs par défaut de `.env.example` conviennent telles quelles pour le local : mots de passe de développement, ports 5432 (PostgreSQL), 9000 (S3), 8000 (API) et 3000 (site). Le fichier `.env` n'est jamais versionné.

Si un port est déjà pris sur ta machine, change `DEV_POSTGRES_PORT` ou `DEV_S3_PORT` dans `.env`, ainsi que les URL qui les utilisent (`DATABASE_URL`, `API_DATABASE_URL`, `WORKER_DATABASE_URL`, `TEST_DATABASE_URL`, `S3_ENDPOINT`, `S3_PUBLIC_ENDPOINT`).

---

## 6. Installer les dépendances

```bash
just install
```

Cette recette installe les paquets Python (`uv sync`) et JavaScript (`pnpm install`), aux versions exactes des fichiers de verrouillage.

---

## 7. Démarrer la base et le stockage

```bash
just dev-up
```

Ce que fait cette commande :

1. démarre PostgreSQL et RustFS dans Docker, accessibles seulement depuis ta machine ;
2. crée le bucket S3 et sa règle CORS, qui autorise le site à y envoyer les fichiers ;
3. applique les migrations de la base et crée les rôles `ma_api` et `ma_worker`.

Les données sont gardées entre deux démarrages.

---

## 8. Lancer l'application

Ouvre **trois terminaux**, chacun dans `~/code/match-analyzer`.

**Terminal 1, l'API :**

```bash
just api
```

Elle répond sur `http://127.0.0.1:8000`. Sa documentation interactive est sur `http://127.0.0.1:8000/api/docs`.

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

---

## 9. Utiliser le site

1. **Analyser** : dépose un ou plusieurs fichiers `.replay`, jusqu'à 50 à la fois. Ils se trouvent sur PC dans `Documents\My Games\Rocket League\TAGame\Demos`. Pense à sauvegarder le replay en fin de match.
   - Sur Chrome et Edge, le bouton **« Choisir mon dossier Demos »** ouvre directement ce dossier. Aux visites suivantes, « Importer les nouveaux replays » n'envoie que les nouveaux fichiers.
   - Chaque fichier passe par « Envoi », « Analyse en cours », puis « Prêt ».
2. **Voir le match** : réponds à « Lequel de ces joueurs es-tu ? ». Ce choix est mémorisé pour les matchs suivants. La fiche montre ensuite le score, les joueurs, la chronologie des buts et les 21 statistiques.
3. **Mes stats** : moyennes sur tes derniers matchs et évolution d'une statistique.
4. **Se connecter** (facultatif) : avec Steam, depuis l'en-tête ou depuis l'invitation sous un match. Les matchs de la session sans compte sont alors rattachés au compte. La connexion Epic reste désactivée (`FEATURE_EPIC_LOGIN=false`) tant qu'Epic n'a pas validé l'application.
5. **Paramètres** : comptes liés, et suppression du compte ou des données de la session.

Pour suivre la file de traitement :

```bash
just worker-status
```

---

## 10. Arrêter

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

---

## 11. Mettre à jour après un `git pull`

```bash
git pull
just install
just db-migrate
```

Si l'analyse a changé de version, tu peux relancer le traitement des matchs déjà importés, avec le worker en marche :

```bash
just reprocess --analysis-outdated
```

Pour une nouvelle version du parser, c'est `just reprocess --parser-outdated`.

---

## 12. Lancer les tests (facultatif)

| Commande | Ce qu'elle vérifie | Prérequis |
| --- | --- | --- |
| `just check` | Lint, types et tests unitaires (Rust, Python, TypeScript) | Aucun |
| `just test-db` | Base de données, API et worker | `just dev-up` |
| `just test-s3` | Stockage S3 réel | `just dev-up` |
| `just test-e2e` | Parcours complet dans un navigateur, FR et EN, sur mobile | `just dev-up`, plus les bibliothèques de Chromium ci-dessous |

Pour `just test-e2e`, Chromium a besoin de quelques bibliothèques système :

```bash
sudo apt-get install -y libnss3 libnspr4 libasound2t64
```

Sur Ubuntu 22.04, le dernier paquet s'appelle `libasound2`.

Les replays de test ne sont jamais versionnés : ils contiennent les pseudos d'autres joueurs. `just corpus-fetch` télécharge les replays publics du corpus de test.

---

## 13. En cas de problème

| Symptôme | Cause probable | Solution |
| --- | --- | --- |
| `just dev-up` échoue sur un port déjà utilisé | Un autre PostgreSQL ou service occupe 5432 ou 9000 | Changer les ports dans `.env` (voir l'étape 5) |
| `permission denied` sur Docker | Utilisateur hors du groupe `docker` | `sudo usermod -aG docker "$USER"`, puis rouvrir le terminal |
| Les fichiers restent bloqués sur « Envoi » ou « Échec : l'envoi a échoué » | Site ouvert sur `127.0.0.1` au lieu de `localhost`, ou S3 arrêté | Ouvrir `http://localhost:3000`, vérifier `just dev-up` |
| Les fichiers restent sur « Analyse en cours » | Le worker ne tourne pas | `just worker`, puis `just worker-status` |
| `PARSER_BIN is not an executable program` | Lancement du worker sans `just` | Toujours passer par `just worker` |
| L'en-tête n'affiche ni session ni compte, les pages sont vides | L'API ne tourne pas | `just api` |
| Lenteur extrême sous Windows | Projet cloné sous `/mnt/c/...` | Le recloner dans `~/code` |
| `just test-e2e` : `libnspr4.so: cannot open shared object file` | Bibliothèques de Chromium absentes | Voir l'étape 12 |
| Connexion Steam : retour sur l'accueil avec « La connexion n'a pas abouti » | Session de connexion expirée (10 minutes) ou Steam injoignable | Recommencer la connexion |

Pour aller plus loin : `CLAUDE.md` décrit le projet et ses règles, et `docs/PLAN.md` le plan détaillé avec toutes les décisions.
