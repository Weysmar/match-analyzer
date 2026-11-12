# Exploitation : déployer et faire tourner la production

Étape 9 de `docs/PLAN.md`. Ce document décrit la pile de production, ses images et ses variables. Les étapes qui demandent tes comptes (R2, VPS, Dokploy, domaine : T9.4 à T9.6) s'appuient dessus.

## La pile

`compose.yaml`, à déployer comme une application Dokploy de type **« Docker Compose »** (pas « Stack » : Swarm ignore `build` et les limites mémoire du worker).

| Service | Image | Rôle | Joignable |
| --- | --- | --- | --- |
| `db` | `postgres:16.15` | Base de données, volume `db-data` | Réseau interne seulement |
| `migrate` | `match-analyzer-api` | `ma-db upgrade` une fois, avant l'API et le worker | Ne reste pas lancé |
| `api` | `match-analyzer-api` | API, port 8000 | Par le site seulement |
| `worker` | `match-analyzer-worker` | Jobs et parser `rl-parse` | Sortie vers la base et R2 |
| `web` | `match-analyzer-web` | Site, port 3000 | **Seul service publié**, par le domaine Dokploy |

Le stockage objet est Cloudflare R2, hors de la pile. Aucun service ne publie de port : `web` est rattaché au domaine dans l'onglet **Domains** de Dokploy (Traefik et TLS), sur le port 3000.

Durcissement : système de fichiers en lecture seule, aucune capacité Linux, `no-new-privileges`, utilisateur non root dans chaque image. Le worker, qui ouvre des fichiers inconnus, a en plus une mémoire bornée (`WORKER_MEMORY_LIMIT`, 1,5 Go par défaut), 256 processus au plus et `/tmp` limité à 1 Go, en plus du bac à sable qu'il donne à `rl-parse` (30 s, 512 Mo d'espace d'adresses).

## Les images

Construites par GitHub Actions (`.github/workflows/release.yml`) à chaque push sur `main`, publiées sur GHCR :

- `ghcr.io/weysmar/match-analyzer-api`
- `ghcr.io/weysmar/match-analyzer-worker`
- `ghcr.io/weysmar/match-analyzer-web`

Chacune porte deux étiquettes : `sha-<commit>` (7 caractères) et `main`. `IMAGE_TAG` choisit laquelle déployer : `main` suit la dernière version, `sha-…` fige une version et permet de revenir en arrière.

À la première publication, GHCR crée les paquets en **privé**. Deux possibilités pour que Dokploy les récupère : les rendre publics (ils ne contiennent ni secret ni donnée), ou enregistrer dans Dokploy un registre `ghcr.io` avec un jeton GitHub qui a le droit `read:packages`.

## Les variables

Elles se saisissent dans l'onglet **Environment** de l'application Dokploy. Chaque service ne reçoit que les siennes : `compose.yaml` les lui passe une par une. Une variable obligatoire absente arrête le déploiement avec son nom.

**Génère les secrets avec `openssl rand -hex 32`** : de l'hexadécimal, sans caractère qui casserait les URL de connexion à la base.

| Variable | Obligatoire | Sert à |
| --- | --- | --- |
| `SITE_URL` | oui | L'adresse publique du site, en `https://` |
| `POSTGRES_PASSWORD` | oui | Le propriétaire de la base, utilisé par `migrate` seulement |
| `API_DB_PASSWORD` | oui | Le rôle `ma_api`, que `migrate` crée avec ce mot de passe |
| `WORKER_DB_PASSWORD` | oui | Le rôle `ma_worker`, de même |
| `SESSION_SECRET` | oui | La signature des cookies (32 caractères au moins) |
| `S3_ENDPOINT` | oui | Le point d'accès R2 : `https://<compte>.r2.cloudflarestorage.com` |
| `S3_PUBLIC_ENDPOINT` | non | L'hôte que voient les navigateurs dans les URL présignées, s'il diffère |
| `S3_BUCKET` | oui | Le bucket R2 |
| `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` | oui | Le jeton R2, limité à ce bucket |
| `S3_REGION` | non | `auto` par défaut, la valeur de R2 |
| `IMAGE_TAG` | non | `main` par défaut |
| `POSTGRES_USER`, `POSTGRES_DB` | non | `ma_owner` et `match_analyzer` par défaut |
| `TRUSTED_PROXY_COUNT` | non | 2 par défaut : Traefik, puis le relais du site |
| `WORKER_CONCURRENCY` | non | 1 par défaut ; chaque parse peut prendre 512 Mo |
| `WORKER_MEMORY_LIMIT` | non | `1536m` par défaut ; à relever avec la concurrence |
| `FEATURE_EPIC_LOGIN`, `EPIC_*` | non | La connexion Epic, désactivée tant que la Brand Review n'est pas validée |

Les autres réglages (durées de session, limites d'upload et de débit, rétention, parser) gardent les valeurs de `.env.example` s'ils ne sont pas donnés : `compose.yaml` les reprend.

## Mettre à jour

1. Fusionne sur `main` : `release.yml` publie les nouvelles images.
2. Dans Dokploy, redéploie l'application. `migrate` applique les nouvelles migrations avant que l'API et le worker ne redémarrent.
3. Si le parser ou l'analyse ont changé de version, relance le traitement des matchs déjà importés, dans cet ordre (amendement B11 de `docs/PLAN-V2.md`) :

   ```bash
   docker compose exec worker ma-worker reprocess --parser-outdated
   docker compose exec worker ma-worker reprocess --analysis-outdated
   ```

Pour revenir en arrière, mets `IMAGE_TAG` sur le `sha-…` précédent et redéploie. Une migration ne se défait pas toute seule : vérifie le journal des migrations avant de revenir sur une version qui en précède une.

## Vérifier la pile sur un poste

La CI le fait à chaque PR (job `images`) ; en local :

```bash
just production-check
```

Cette recette construit les trois images, démarre `compose.yaml` avec un émulateur S3 à la place de R2 et des valeurs de test (`.github/ci.env`, pas des secrets), vérifie que les migrations passent, que l'API joint la base, que le site répond et relaie vers l'API, que le worker reste lancé et qu'aucun service ne tourne en root, puis arrête et supprime tout, volumes compris.

## Reste à faire

- T9.4 👤 : bucket R2, CORS, jeton, cycle de vie de `incoming/`, test du `Content-Length` signé.
- T9.5 👤 : VPS dans l'UE et Dokploy.
- T9.6 👤 : déploiement sur le domaine.
- T9.7 : sauvegardes de la base vers R2, restauration testée.
- T9.9 : journaux structurés et suivi des builds du jeu qui cassent le parser.
