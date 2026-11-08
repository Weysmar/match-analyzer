# Rapport d'oracle : les métriques V1 face à `subtr-actor`

> T7.13 de `docs/PLAN.md`. Établi le 2026-11-08 avec `just oracle-report`, `rl-parse` 0.1.2, `rl_analysis` version d'analyse 1 et `subtr-actor` 1.5.1. Le rapport ne contient que des comptes et des écarts, jamais un pseudo ni un identifiant.

## Périmètre

- **Corpus** : 122 replays, dont 100 fichiers distincts. Seuls ceux que `rl-parse` lit en entier comptent : les 3 de mode non pris en charge (`unsupported_mode`) en sont exclus.
- **Format actuel seulement** (`net` ≥ 10), comme au spike : **92 replays** comparés, et 5 plus anciens comptés à part (A50). Sur deux replays de 2016, c'est la référence elle-même qui se trompe : le module boost de `subtr-actor` suit un joueur 30 à 69 s de moins que ses propres modules mouvement et positionnement.
- **Référence** : `rl-oracle`, un binaire de test jamais déployé, dont la sortie est mise en cache (A49). `subtr-actor` lit tous les replays comparés.

## Écarts

Écart absolu par joueur, entre nos métriques et `subtr-actor`, dans nos unités.

| Métrique | Joueurs | Médiane | 95ᵉ centile | Max | Lecture |
| --- | --- | --- | --- | --- | --- |
| `boost.avg` | 362 | 0,006 pt | 0,023 pt | 1,17 pt | ✅ Identique au spike |
| `boost.pct_zero` | 362 | 0,16 pt | 1,14 pt | 3,10 pt | ✅ Identique au spike |
| `boost.pct_full` | 362 | 0,16 pt | 0,29 pt | 0,57 pt | ✅ |
| `boost.pads_big` | 360 | 0 | 3 | 20 | ✅ Critère T7.5 : médiane 0, p95 ≤ 4. Voir plus bas |
| `boost.pads_small` | 360 | 0 | 2 | 15 | ✅ Critère T7.5 : médiane 0, p95 ≤ 5 |
| `move.speed_avg` | 361 | 0,0005 uu/s | 2,1 uu/s | 4,9 uu/s | ✅ |
| `move.pct_supersonic` | 361 | 0 | 0,03 pt | 0,11 pt | ✅ |
| `move.pct_ground` | 361 | 0 | 0,11 pt | 0,65 pt | ✅ |
| `move.pct_low_air` | 361 | 0 | 0,11 pt | 0,67 pt | ✅ |
| `move.pct_high_air` | 361 | 0 | 0,01 pt | 0,06 pt | ✅ Les trois bandes font 100 % ± 0,1 pour chaque joueur |
| `pos.dist_ball_avg` | 361 | 0,005 uu | 55 uu | 122 uu | ✅ Spike : 0,004 / 65 uu |
| `pos.pct_last_back` | 325 | 4,6 pt | 8,2 pt | 100 pt | ✅ Définition différente, voir plus bas |
| `event.demos_inflicted` | 256 | 0 | 0 | 0 | ✅ Identique |
| `event.demos_taken` | 256 | 0 | 0 | 0 | ✅ Identique |

**Définitions propres au plan.** Les tiers (D4, ±1707) et devant / derrière la balle (sans marge) diffèrent volontairement de `subtr-actor`. Recalculés avec ses réglages, ils valident le calcul lui-même :

| Vérification | Valeurs | Médiane | 95ᵉ centile | Max |
| --- | --- | --- | --- | --- |
| Tiers coupés à ±2300 | 1 083 | 0,05 pt | 0,69 pt | 2,2 pt |
| Devant / derrière avec une marge de 150 uu | 722 | 0,07 pt | 0,42 pt | 1,4 pt |

**Consommation de boost** (`boost.used_per_min`, T7.4), en écart relatif :

| Vérification | Joueurs | Médiane | 95ᵉ centile | Critère |
| --- | --- | --- | --- | --- |
| Par rapport à `boost_active` × débit | 361 | 0,5 % | 1,5 % | < 5 % ✅ |
| Toutes les frames, par rapport à `amount_used` | 362 | 3,3 % | 9,9 % | < 5 % ✅ |

`boost.pads_enemy_half` n'a pas d'équivalent chez `subtr-actor` : elle est vérifiée sur données synthétiques, miroir orange, ligne médiane et changement d'équipe compris.

## Écarts expliqués

Chaque écart notable a sa cause, et aucun n'est corrigé pour coller à `subtr-actor` (D8).

1. **Gros pads, jusqu'à 20 de moins chez nous.** `subtr-actor` en compte toujours autant ou plus, jamais moins (78 joueurs sur 360). Il ajoute des ramassages qu'il déduit des hausses de boost (T2.7), alors que nous ne comptons que ceux que le replay réplique, dédupliqués (A18).
2. **Un replay sans aucun événement de pad (A51).** Un replay de 2021, 12 minutes de jeu, ne réplique aucun ramassage. `subtr-actor` en déduit 10 gros pads. Nos métriques de pads y valent `null` plutôt qu'un 0 faux.
3. **Dernier défenseur, 4,6 points en médiane (A53).** Notre définition est volontairement simple (T7.10) : le joueur le plus en arrière parmi ses coéquipiers présents. `subtr-actor` applique une logique de rôle. Les plus grands écarts, jusqu'à 100 points, viennent de 8 replays aux équipes déséquilibrées par des départs ou des arrivées.
4. **Distance à la balle, 55 uu au 95ᵉ centile.** Même ordre que le spike (65 uu). Les frames sans balle sont exclues de notre moyenne.
5. **Changements d'équipe (A52), corrigés.** Avant `rl-parse` 0.1.2, deux parties privées montraient jusqu'à 52 points d'écart sur le positionnement. L'équipe est désormais écrite frame par frame : l'écart maximal est tombé à 2,2 points.

**Aucun écart inexpliqué.** Le critère de fin de l'étape 7 est atteint pour le calcul des métriques. `just reprocess` (T7.14) reste à faire.

## Limites

- Le corpus ne couvre que des matchs récents en 2v2 classé, et quelques autres modes. Le 1v1 et le 3v3 récents manquent (question ouverte de `CLAUDE.md`).
- `subtr-actor` n'est pas une vérité officielle : il n'existe aucune référence officielle pour ces métriques. Concorder avec lui prouve surtout que les deux calculs lisent les mêmes données de la même façon.
- Le seuil supersonique (2200 uu/s) reste une convention que les données ne permettent pas de vérifier (A11).
