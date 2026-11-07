# 0001. Émulateur S3 de développement

- Statut : accepté le 2026-11-07
- Tâche : T1.4 de `docs/PLAN.md`

## Contexte

`CLAUDE.md` prévoyait MinIO, mais son dépôt est archivé depuis le 25/04/2026 et l'édition communautaire n'est plus distribuée qu'en sources. Le développement a besoin d'un store S3 local, qui doit se comporter comme ce dont l'upload dépend. La production reste sur Cloudflare R2.

## Comparaison

`scripts/s3_check.py`, 11 contrôles, sur des conteneurs temporaires le 2026-11-07 :

| Candidat         | Contrôles | Démarrage | Image    | Licence                          | Configuration                                         |
| ---------------- | --------- | --------- | -------- | -------------------------------- | ----------------------------------------------------- |
| **RustFS 1.0.4** | **11/11** | 8 s       | 418 Mo   | Apache-2.0                       | Deux variables d'environnement                        |
| SeaweedFS 4.52   | 11/11     | 15 s      | 1 058 Mo | Apache-2.0                       | Fichier JSON monté                                    |
| Garage v2.5.0    | 10/11     | 4 s       | 97 Mo    | AGPL (de mémoire, non revérifié) | Fichier TOML, puis disposition, clé et bucket par CLI |

Garage échoue sur un contrôle de sécurité : il renvoie `Access-Control-Allow-Origin: *` à un site non autorisé.

## Décision

**RustFS 1.0.4, version figée, en développement uniquement.** Il réussit tous les contrôles et il est le plus simple à configurer parmi les candidats qui les réussissent.

## Conséquences

- Tout accès passe par des variables `S3_*` génériques : changer d'émulateur ne touche que `compose.dev.yaml`.
- **Ces résultats ne valent pas pour R2.** `just s3-check` doit être relancé sur R2 avant la production (T9.4), en particulier pour le refus d'un corps plus gros que déclaré.
- RustFS a atteint la 1.0 récemment : en cas de souci, SeaweedFS est l'alternative validée.
