# Rapport de l'étape 0 : vérification technique

*Mesuré les 2026-11-06 et 2026-11-07 sous Ubuntu 26.04 (WSL2), Rust 1.99.1, `boxcars` 0.13.0, `subtr-actor` 1.5.1.*

> **Statut : un point reste ouvert.** Le parsing est validé jusqu'au build `261031` du 31 octobre 2026. **Il manque la comparaison de l'identifiant Epic (T0.7).**
>
> **Correction du 2026-11-07** : la première version de ce rapport affirmait que le header ne contenait pas l'identifiant Epic. C'est faux, voir section 12.

## 1. Conclusion

**Le risque principal est levé : `boxcars` et `subtr-actor` conviennent, et la V1 peut continuer sur cette base.** Aucune règle d'arrêt du plan n'est déclenchée. Le spike a cependant invalidé plusieurs hypothèses du plan, et les corrections figurent dans `docs/PLAN.md` (section « Amendements après l'étape 0 »).

| Règle de décision (T0.9) | Résultat | Conséquence |
|---|---|---|
| Header ou network < 100 % sur les post-EAC | **100 %** : 34 replays distincts, 6 builds | Pas d'arrêt |
| `boxcars` réussit mais `ReplayProcessor` échoue | Jamais observé | Pas de code d'extraction à écrire |
| Échecs limités aux anciens replays | **Aucun échec**, seulement 1 replay très lent | `legacy` pris en charge |
| Identifiant Epic réseau ≠ `account_id` | **Non conclu** : même format, comparaison à faire | T0.7 ouvert |
| Timeout de 30 s insuffisant | Non : ≈ 2 s sur le pire cas sans les stats complètes | 30 s conservé |
| Parquet > 5 Mo par match | Non : médiane 2,23 Mo, max 3,44 Mo | Format conservé |
| `GameplayPhase` inaccessible | Accessible, et même sans le graphe d'analyse | Collecteur léger, voir section 5 |

## 2. Corpus

| Groupe | Fichiers | Distincts | Note |
|---|---|---|---|
| `public` | 35 | 34 | `subtr-actor` au commit `ea9f34d`, noms contenant un pseudo exclus |
| `legacy` | 69 | 48 | Tes replays de 2021 à 2023. **21 sont des doublons exacts** (fichiers « - Copie ») |
| `vincent` | 18 | 18 | Tes replays du 2026-11-06, build `261031`, voir section 12 |

Les chiffres des sections 3 à 11 portent sur `public` et `legacy`, et la section 12 donne ceux de `vincent`.

## 3. Parsing (T0.3)

| Groupe | Header | Network | `ReplayData` | Stats complètes |
|---|---|---|---|---|
| Post-EAC (16 distincts) | 16/16 | 16/16 | 16/16 | 16/16 |
| Tous les distincts (82) | 81/82 mesurés, voir ci-dessous | 81/82 | 81/82 | 81/82 |

Le 82ᵉ n'a pas échoué : il a dépassé la limite de 120 s du spike à cause des stats complètes. Détail mesuré en isolé pour ce replay (10,6 Mo, 75 124 frames, soit environ 8 fois un match normal) :

| Étape | Temps | Mémoire maximale |
|---|---|---|
| Network | 67 ms | 93 Mo |
| `ReplayData` | 1,3 s | 181 Mo |
| Timeline (`StatsTimelineEventCollector`) | 40 s | 389 Mo |
| Stats complètes (`StatsCollector`) | **197 s** | **663 Mo** |
| Stats « boost » seules | 62 s | non mesurée |
| Phases par collecteur léger | 0,7 s | non mesurée |

**Conséquence** : `StatsCollector` et la timeline ne doivent pas tourner en production. Ils restent une référence de test.

## 4. Header (T0.4)

- **Identifiant Epic** : `OnlineID = 0` pour 159 entrées Epic sur 159, mais l'identifiant est ailleurs dans le header (section 12).
- **Plateformes du header** : `Steam`, `Epic`, `PS4`, `Dingo` (Xbox), `NNX` (Switch), `Unknown` (bots). `subtr-actor` ne reconnaît pas `NNX`.
- **PS4** : 4 entrées sur 44 ont un `OnlineID` nul, sur d'anciens replays.
- **`MatchGUID`** : 32 caractères. Sur net ≥ 11, absent seulement des 4 replays `Offline`. Rare avant 2026 (4 sur 83).
- **`MatchStartEpoch`** : secondes Unix, présent sur tous les net ≥ 11, rare avant (5 sur 83).
- **`Date`** : heure locale de l'enregistreur. L'écart à l'epoch varie de −7 h à +5,25 h.
- **`Goals`** : uniquement `PlayerName`, `PlayerTeam` et `frame`. Confirmé.
- **`RecordFPS`** : 30 partout, mais le nombre réel de frames par seconde varie (section 6).
- **`game_type`** : `TAGame.Replay_Soccar_TA` partout, **y compris pour le Dropshot**. Il ne distingue donc pas les modes.
- **Liste des joueurs incomplète** : 50 joueurs vus sur le réseau manquent au header, et 3 entrées du header n'ont pas de joueur réseau.
- **Buts** : le réseau compte un but de plus que le header dans 2 replays distincts sur 81. 5 buts n'ont pas de joueur associé.

## 5. Inventaire : fourni ou à coder (T0.6)

| Besoin | Constat | Décision |
|---|---|---|
| Positions, boost, sauts | `ReplayDataCollector`, 1,3 s au pire | Utilisé tel quel |
| Écriture Parquet | Absente | À coder, déjà prévu |
| **Phases de jeu** | La timeline fonctionne mais coûte cher. Un collecteur à nous autour de `LivePlayTracker` donne **100 % d'accord sur 735 692 frames**, en 87 ms au lieu de 1 931 ms (médianes) | **Petit collecteur à coder** |
| **Démolitions** | `DemolishInfo` fiable : infligées et subies identiques aux stats | Utilisé tel quel |
| **Colonne `demolished`** | **L'hypothèse du plan est fausse** : 1 démolition sur 242 est suivie de frames vides. La voiture reste « présente » et sa position est fausse : déplacée de 5 171 uu en médiane, vitesse ≈ 60 uu/s | **Fenêtre à calculer** : du `DemolishInfo` à +3,2 s (réapparition : p5 3,20 s, médiane 3,21 s), arrêtée au changement de phase |
| Frames vides | Joueur absent ou trous brefs, sans lien avec les démolitions | `present = false`, exclu des calculs |
| **Ramassages de pads** | **Les événements bruts surcomptent** : 27 gros pads contre 18 (médianes). Taille résolue pour 99,7 % des ramassages | **Dédupliquer** par pad, séquence et joueur : écart médian 0, p95 de 3 gros et 5 petits |
| Stats agrégées | Excellente référence, trop coûteuses en production | Tests uniquement |

## 6. Constantes (T0.5)

Mesurées en jeu actif sur les arènes standard (net ≥ 10).

| Constante | Attendu | Mesuré | Verdict |
|---|---|---|---|
| `x` voitures | ±4096 | ±4094 | ✅ |
| `y` | ±5120 | Balle ±5215, voitures ±5991 (dans les buts) | ✅ pour le terrain, à prévoir pour les buts |
| Plafond `z` | ≈ 2044 | 2039 voitures, 1976 balle | ✅ |
| Vitesse max | ≈ 2300 | 2300 exactement, plateau net | ✅ |
| **Supersonique** | ≈ 2200 | **Aucune rupture visible à 2200** dans la distribution | ⚠️ Non vérifiable par les données, convention conservée |
| Boost | 0 à 255 | 0 à 255, 85 au kickoff dans 95 replays sur 95 | ✅ |
| Bleu défend `y < 0` | À vérifier | Kickoffs 91/91. Buts bleus en `y > 0` : 306 sur 308, oranges en `y < 0` : 379 sur 380 | ✅ |
| Voiture au sol | | `z` = 17 en médiane | ✅ seuil de 20 valable |

**Arène hors standard** : `ShatterShot_P` (Dropshot) atteint `x` = ±5059 et `y` = ±4588, avec une balle à `z` = −164. Hoops, Rumble et Snow Day ne figurent pas dans le corpus.

**Fréquence réelle** : en jeu, le `dt` le plus long d'un replay vaut 44 ms en médiane et 430 ms au pire. Sur toute la durée, le nombre de frames par seconde descend à 17 sur les replays récents. **Les métriques doivent donc être pondérées par `dt`, jamais par nombre de frames.** Aucun sous-échantillonnage n'est nécessaire.

## 7. Comparaison à `subtr-actor` (T0.8)

72 replays en arène standard, 277 joueurs. Calculs à la main sur les frames, avec les masques de temps de `subtr-actor`.

| Métrique | Écart médian | p95 | Lecture |
|---|---|---|---|
| Boost moyen | 0,014 | 0,061 | ✅ En unités brutes |
| % à 0 / % à 100 | 0,14 / 0,15 pt | 1,14 / 0,24 pt | ✅ |
| Vitesse moyenne | 0,00 | 2,1 uu/s | ✅ |
| % supersonique | 0,00 pt | 0,03 pt | ✅ |
| % sol / air bas / air haut | 0,00 pt | 0,09 pt | ✅ |
| Démolitions | 0 | 0 | ✅ Identiques |
| Tiers avec ±2300 | 0,04 pt | 0,83 pt | ✅ Valide le calcul |
| Devant / derrière avec marge de 150 uu | 0,05 / 0,08 pt | 0,46 pt | ✅ Valide le calcul |
| Distance à la balle | 0,004 uu | 65 uu | ✅ |
| Gros / petits pads dédupliqués | 0 / 0 | 3 / 5 | ⚠️ Reste à expliquer |
| % dernier défenseur | 4,4 pt | 7,8 pt | ⚠️ `subtr-actor` applique sa propre logique de rôle |
| Consommation de boost | Voir ci-dessous | | ⚠️ Définition différente |

**Effet des choix du plan** (médianes) :

| Choix | Défense | Milieu | Attaque |
|---|---|---|---|
| Tiers à ±1707 (D4, retenu) | 43,5 % | 33,3 % | 22,6 % |
| Tiers à ±2300 (`subtr-actor`) | 37,8 % | 43,4 % | 17,8 % |

Sans marge (choix du plan), « devant / derrière » donne 28,7 % / 71,3 %. Avec la marge de 150 uu, 24,5 % / 65,0 %, et 10,5 % « au niveau de la balle ».

**Consommation** : par variation de boost ou par `boost_active` × débit, les deux méthodes concordent (1 065 et 1 072 unités brutes par minute, soit environ 418 %/min). `amount_used` de `subtr-actor` donne 1 229, car il compte toutes les frames, après-but compris, mais divise par le temps suivi. Sur toutes les frames, notre calcul atteint 1 200, soit 2 % d'écart. **Le critère du plan (écart < 5 % avec `amount_used`) était donc mal posé.**

2 joueurs sur 277 ont moins de 5 s de présence et produisent les écarts maximaux : prévoir un test sur ce cas.

## 8. Identité (T0.7)

- **Format** : 170 identifiants Epic réseau sur 170 font 32 caractères hexadécimaux, comme `account_id` dans la documentation Epic. Bon indice, **mais pas une preuve**.
- **Type de `RemoteId`** : `epic` 170, `steam` 161, `playstation` 51, `xbox` 24, `splitscreen` 14, `psynet` 2, `switch` 1. Les bots apparaissent en `splitscreen`, à confirmer.
- **Doublons de pseudo** : 1 replay distinct sur 81, ce qui confirme que le nom ne suffit pas pour les joueurs Epic.
- **Anonymisation** : voir section 12.

**Reste à faire** : comparer l'« Account ID » de ton compte Epic avec tes replays. La commande ne l'affiche pas et ne renvoie qu'un nombre de correspondances :

```bash
just spike-epic <ton_account_id>
```

## 9. Budget (T0.8)

| Mesure (81 replays distincts) | Médiane | Maximum |
|---|---|---|
| Network | 8 ms | 19 ms |
| `ReplayData` | 195 ms | 628 ms |
| Parquet + network + données | | 686 ms |
| Phases par collecteur léger | 87 ms | 400 ms |
| Stats complètes (tests uniquement) | 4,5 s | 10,5 s |
| Mémoire sans les stats, timeline incluse | | 87 Mo |
| Parquet | 2,23 Mo | 3,44 Mo |
| Fichier brut | 1,12 Mo | 2,58 Mo |

**Le Parquet pèse environ 2 fois le fichier brut.** Une image sur deux donnerait 1,18 Mo. Compter environ 2,2 Go pour 1 000 matchs.

**Valeurs retenues** :

- `PARSER_TIMEOUT_S` = 30 : large marge sur cette machine, à revérifier sur le VPS.
- `PARSER_MEMORY_MB` = 512 : le cas extrême de `rl-parse` reste sous 200 Mo. `RLIMIT_AS` compte la mémoire virtuelle, valeur à valider à T6.3.
- `UPLOAD_MAX_BYTES` = 20 Mo : un vrai replay atteint 10,6 Mo, cette limite ne doit donc pas baisser.
- **VPS** : 2 vCPU et 4 Go de RAM semblent suffire pour démarrer. **C'est une estimation** : l'empreinte de Dokploy, Next.js et PostgreSQL n'a pas été mesurée.

## 10. Autres constats

- **Les erreurs de `subtr-actor` peuvent citer des pseudos** (`Player not found` formate des entrées entières du header). `rl-parse` doit produire uniquement ses propres codes d'erreur.
- **Installation** : le système d'autorisation a refusé les scripts `curl | sh`. Les outils viennent donc d'`apt`, de `pipx` et de `npm`, avec Node 22 au lieu de 24 et `just` 1.45.
- **Pas de commit** : le dépôt local n'a encore aucun commit ni dépôt distant.

## 11. Reproduire

Les résultats sur `vincent` s'obtiennent avec les sous-commandes `run`, `corpus-info`, `identity` et `oracle` de `s0-parse`.

```bash
just corpus-check
just spike-parse
just spike-report
just spike-oracle
just spike-light tests/fixtures/replays/public/post-eac-ranked-doubles-2026-04-28.replay
```

## 12. Tes replays récents (T0.2, ajouté le 2026-11-07)

**18 replays distincts, tous du 2026-11-06, build `261031.63733.533021` (net 12) : 18 sur 18 réussis à toutes les étapes.** C'est le build le plus récent testé.

**Variété**

| Critère | Résultat |
|---|---|
| 2v2 classé | 18 |
| **1v1 et 3v3** | **0**. Couverts seulement par les replays publics, jusqu'au build `260918` |
| Joueur récurrent | 1 joueur **Epic** présent dans les 18 replays : 5 victoires, 13 défaites |
| Prolongations | 3 |
| Cartes | 12 différentes, toutes dans les bornes du terrain standard |

**Mesures** : elles confirment la section 7.

| Mesure | Résultat |
|---|---|
| Phases par collecteur léger | 100 % d'accord sur 140 650 frames, 74 ms en médiane |
| Boost, mouvement, démolitions | Écarts médians inférieurs à 0,8 uu/s ou 0,3 point |
| Pads dédupliqués | Écart médian de 0, p95 de 3 gros et 3 petits |
| Consommation | 1 108 et 1 117 unités brutes par minute selon la méthode. Toutes frames : 1 238 contre 1 269 pour `amount_used`, soit 2,5 % d'écart |
| Parquet | 1,84 Mo en médiane, 2,64 Mo au maximum |
| Temps total sans stats complètes | Moins d'une seconde |
| Mémoire avec timeline, sans stats | 77 Mo au maximum |

**Le header contient l'identifiant Epic.** Le champ `PlayerStats[].PlayerID` est une structure `UniqueNetId` avec `Uid`, `NpId`, `EpicAccountId` et `Platform`. Pour **84 joueurs Epic sur 84** (45 dans tes replays, 39 dans les publics), `EpicAccountId` est égal à l'identifiant réseau. `PlayerID` manque sur 64 entrées des replays publics, et sur la plupart des anciens replays. La section 3.3 du plan et ma recommandation précédente s'étaient arrêtées à `OnlineID = 0`.

**Conséquence** : un match `header_only` récent peut être identifié et vérifié pour un joueur Epic, ce qui est plus favorable que prévu.

**Anonymisation** : 4 joueurs de tes replays ont `bAnonymizeToOpponents` et `bAnonymizeToTeammates` vrais (2 Epic, 2 PlayStation). Pour eux, le header et le réseau exposent quand même le vrai pseudo et l'identifiant, et `AnonymizedName` en diffère. Un outil naïf afficherait donc le vrai pseudo d'un joueur qui a demandé l'inverse. Voir la décision D20 du plan.

**Reste différent de `subtr-actor`** : `time_demolished` vaut 4,98 s contre 3,18 s pour notre fenêtre (médianes). La réapparition observée reste à 3,2 s au p5 et 3,23 s en médiane, donc notre fenêtre est conservée.
