# Datensatz-Report

Automatisch erzeugt von `tools/analyze_dataset.py`. Quelle: [wty-yy/Clash-Royale-Detection-Dataset](https://github.com/wty-yy/Clash-Royale-Detection-Dataset) (MIT).

## Umfang

- Echte gelabelte Arena-Frames: **6966**
- Annotierte Boxen: **117294**
- Referenzaufloesung der Arena-Crops: **552x896**
- Cutouts fuer die Synthese: **4654** in **154** Ordnern
- Klassen laut YAML: **201**
- Felder pro Labelzeile: {12: 117294}

## Boxgroessen (Diagonale in px @ Referenzaufloesung)

| Perzentil | p1 | p5 | p10 | p25 | p50 | p75 | p90 | p95 | p99 |
|---|---|---|---|---|---|---|---|---|---|
| px | 37.9 | 49.9 | 55.8 | 74.1 | 97.4 | 137.0 | 172.0 | 181.5 | 203.2 |

## Klassen nach Haeufigkeit

| # | Klasse | Boxen | Anteil | med. w x h (px) | Cutouts |
|---|---|---|---|---|---|
| 1 | `queen-tower` | 26343 | 22.46% | 88 x 103 | 54 |
| 5 | `tower-bar` | 24012 | 20.47% | 91 x 28 | 46 |
| 0 | `king-tower` | 14005 | 11.94% | 109 x 137 | 76 |
| 7 | `bar` | 11735 | 10.00% | 54 x 18 | 136 |
| 15 | `skeleton` | 3633 | 3.10% | 30 x 33 | 148 |
| 45 | `royal-recruit` | 3298 | 2.81% | 50 x 68 | 67 |
| 9 | `clock` | 3034 | 2.59% | 38 x 45 | 30 |
| 71 | `musketeer` | 2582 | 2.20% | 39 x 60 | 87 |
| 11 | `text` | 2050 | 1.75% | 130 x 32 | 0 |
| 28 | `ice-golem` | 1781 | 1.52% | 72 x 67 | 54 |
| 40 | `cannon` | 1735 | 1.48% | 72 x 83 | 25 |
| 83 | `zappy` | 1617 | 1.38% | 45 x 49 | 30 |
| 12 | `elixir` | 1495 | 1.27% | 31 x 39 | 32 |
| 6 | `king-tower-bar` | 1422 | 1.21% | 138 x 39 | 17 |
| 80 | `hog-rider` | 1237 | 1.05% | 62 x 71 | 68 |
| 30 | `barbarian` | 888 | 0.76% | 48 x 45 | 42 |
| 109 | `royal-hog` | 837 | 0.71% | 35 x 46 | 27 |
| 2 | `cannoneer-tower` | 780 | 0.66% | 99 x 116 | 20 |
| 19 | `ice-spirit` | 684 | 0.58% | 42 x 35 | 66 |
| 34 | `the-log` | 657 | 0.56% | 104 x 41 | 34 |
| 8 | `bar-level` | 468 | 0.40% | 15 x 19 | 22 |
| 133 | `pekka` | 361 | 0.31% | 80 x 81 | 22 |
| 124 | `elite-barbarian` | 333 | 0.28% | 53 x 55 | 34 |
| 79 | `flying-machine` | 317 | 0.27% | 85 x 87 | 25 |
| 10 | `emote` | 316 | 0.27% | 92 x 79 | 25 |
| 63 | `bandit` | 300 | 0.26% | 46 x 53 | 36 |
| 96 | `lumberjack` | 275 | 0.23% | 61 x 63 | 22 |
| 33 | `rage` | 267 | 0.23% | 286 x 257 | 9 |
| 69 | `fireball` | 264 | 0.23% | 50 x 60 | 37 |
| 73 | `goblin-brawler` | 260 | 0.22% | 57 x 54 | 39 |
| 39 | `minion` | 239 | 0.20% | 41 x 42 | 44 |
| 21 | `goblin` | 234 | 0.20% | 39 x 43 | 63 |
| 3 | `dagger-duchess-tower` | 226 | 0.19% | 97 x 114 | 18 |
| 46 | `royal-recruit-evolution` | 217 | 0.19% | 59 x 78 | 150 |
| 91 | `inferno-dragon` | 211 | 0.18% | 79 x 83 | 27 |
| 84 | `baby-dragon` | 207 | 0.18% | 71 x 72 | 35 |
| 31 | `barbarian-evolution` | 207 | 0.18% | 53 x 74 | 55 |
| 48 | `mega-minion` | 203 | 0.17% | 63 x 63 | 25 |
| 35 | `archer` | 203 | 0.17% | 37 x 45 | 44 |
| 22 | `spear-goblin` | 200 | 0.17% | 42 x 46 | 91 |
| 140 | `little-prince` | 198 | 0.17% | 43 x 54 | 53 |
| 62 | `royal-ghost` | 197 | 0.17% | 56 x 68 | 21 |
| 138 | `golem` | 194 | 0.17% | 86 x 94 | 30 |
| 127 | `elixir-collector` | 186 | 0.16% | 76 x 82 | 16 |
| 65 | `skeleton-dragon` | 183 | 0.16% | 70 x 70 | 101 |
| 16 | `skeleton-evolution` | 172 | 0.15% | 28 x 38 | 46 |
| 118 | `ram-rider` | 171 | 0.15% | 49 x 76 | 18 |
| 68 | `tesla` | 171 | 0.15% | 49 x 46 | 12 |
| 37 | `knight` | 167 | 0.14% | 67 x 68 | 53 |
| 149 | `tesla-evolution` | 164 | 0.14% | 54 x 49 | 12 |
| 59 | `dirt` | 159 | 0.14% | 45 x 49 | 30 |
| 66 | `mortar` | 158 | 0.13% | 60 x 65 | 10 |
| 13 | `selected` | 156 | 0.13% | 39 x 36 | 0 |
| 72 | `goblin-cage` | 154 | 0.13% | 75 x 89 | 4 |
| 55 | `guard` | 145 | 0.12% | 42 x 61 | 69 |
| 17 | `electro-spirit` | 143 | 0.12% | 44 x 45 | 20 |
| 87 | `poison` | 120 | 0.10% | 214 x 180 | 14 |
| 104 | `rascal-girl` | 120 | 0.10% | 42 x 49 | 98 |
| 18 | `fire-spirit` | 118 | 0.10% | 29 x 35 | 29 |
| 24 | `bat` | 117 | 0.10% | 31 x 27 | 95 |
| 90 | `electro-wizard` | 116 | 0.10% | 52 x 55 | 17 |
| 25 | `bat-evolution` | 106 | 0.09% | 55 x 31 | 59 |
| 42 | `firecracker` | 104 | 0.09% | 46 x 55 | 26 |
| 4 | `dagger-duchess-tower-bar` | 102 | 0.09% | 69 x 14 | 22 |
| 139 | `golemite` | 101 | 0.09% | 66 x 63 | 26 |
| 105 | `giant` | 101 | 0.09% | 101 x 96 | 23 |
| 61 | `ice-wizard` | 101 | 0.09% | 57 x 66 | 60 |
| 141 | `royal-guardian` | 99 | 0.08% | 76 x 91 | 26 |
| 101 | `skeleton-king` | 99 | 0.08% | 112 x 89 | 56 |
| 126 | `barbarian-hut` | 97 | 0.08% | 83 x 94 | 1 |
| 58 | `miner` | 97 | 0.08% | 60 x 68 | 46 |
| 85 | `dark-prince` | 96 | 0.08% | 63 x 94 | 34 |
| 100 | `golden-knight` | 93 | 0.08% | 82 x 78 | 45 |
| 64 | `fisherman` | 91 | 0.08% | 73 x 67 | 30 |
| 121 | `monk` | 91 | 0.08% | 66 x 73 | 22 |
| 135 | `mega-knight` | 89 | 0.08% | 86 x 85 | 60 |
| 81 | `battle-healer` | 88 | 0.08% | 84 x 76 | 31 |
| 142 | `archer-evolution` | 83 | 0.07% | 49 x 56 | 57 |
| 95 | `magic-archer` | 81 | 0.07% | 69 x 68 | 26 |
| 102 | `mighty-miner` | 81 | 0.07% | 79 x 110 | 16 |
| 130 | `goblin-giant` | 81 | 0.07% | 85 x 108 | 20 |
| 20 | `heal-spirit` | 81 | 0.07% | 39 x 42 | 21 |
| 23 | `bomber` | 78 | 0.07% | 35 x 53 | 29 |
| 128 | `giant-skeleton` | 78 | 0.07% | 114 x 113 | 15 |
| 29 | `barbarian-barrel` | 76 | 0.06% | 75 x 54 | 8 |
| 132 | `sparky` | 75 | 0.06% | 82 x 90 | 53 |
| 107 | `inferno-tower` | 74 | 0.06% | 75 x 125 | 9 |
| 99 | `hog` | 72 | 0.06% | 34 x 46 | 16 |
| 103 | `rascal-boy` | 72 | 0.06% | 82 x 71 | 52 |
| 51 | `elixir-golem-big` | 70 | 0.06% | 105 x 74 | 11 |
| 106 | `goblin-hut` | 70 | 0.06% | 92 x 91 | 3 |
| 97 | `night-witch` | 70 | 0.06% | 56 x 73 | 36 |
| 50 | `earthquake` | 69 | 0.06% | 216 x 179 | 10 |
| 134 | `electro-giant` | 69 | 0.06% | 106 x 125 | 13 |
| 112 | `prince` | 69 | 0.06% | 60 x 84 | 58 |
| 115 | `executioner` | 66 | 0.06% | 64 x 74 | 20 |
| 113 | `electro-dragon` | 66 | 0.06% | 66 x 65 | 25 |
| 74 | `valkyrie` | 66 | 0.06% | 47 x 51 | 22 |
| 77 | `bomb-tower` | 64 | 0.05% | 82 x 119 | 14 |
| 88 | `hunter` | 63 | 0.05% | 64 x 68 | 22 |
| 136 | `lava-hound` | 63 | 0.05% | 66 x 80 | 22 |
| 98 | `mother-witch` | 62 | 0.05% | 55 x 61 | 38 |
| 47 | `tombstone` | 62 | 0.05% | 69 x 86 | 1 |
| 137 | `lava-pup` | 61 | 0.05% | 35 x 32 | 36 |
| 82 | `furnace` | 58 | 0.05% | 86 x 110 | 2 |
| 108 | `wizard` | 54 | 0.05% | 47 x 51 | 41 |
| 49 | `dart-goblin` | 53 | 0.05% | 57 x 70 | 21 |
| 70 | `mini-pekka` | 47 | 0.04% | 47 x 52 | 26 |
| 14 | `skeleton-king-bar` | 46 | 0.04% | 40 x 13 | 9 |
| 60 | `princess` | 45 | 0.04% | 49 x 53 | 17 |
| 120 | `archer-queen` | 42 | 0.04% | 79 x 77 | 32 |
| 111 | `balloon` | 42 | 0.04% | 85 x 108 | 8 |
| 32 | `wall-breaker` | 39 | 0.03% | 48 x 54 | 20 |
| 122 | `royal-giant` | 37 | 0.03% | 109 x 100 | 10 |
| 52 | `elixir-golem-mid` | 37 | 0.03% | 62 x 53 | 12 |
| 147 | `evolution-symbol` | 36 | 0.03% | 26 x 34 | 29 |
| 117 | `cannon-cart` | 36 | 0.03% | 66 x 73 | 18 |
| 114 | `bowler` | 36 | 0.03% | 79 x 82 | 16 |
| 131 | `x-bow` | 35 | 0.03% | 90 x 82 | 4 |
| 89 | `goblin-drill` | 35 | 0.03% | 58 x 93 | 8 |
| 145 | `bomber-evolution` | 35 | 0.03% | 50 x 56 | 30 |
| 67 | `mortar-evolution` | 35 | 0.03% | 62 x 71 | 11 |
| 146 | `wall-breaker-evolution` | 34 | 0.03% | 61 x 89 | 7 |
| 36 | `arrows` | 33 | 0.03% | 230 x 204 | 6 |
| 38 | `knight-evolution` | 32 | 0.03% | 84 x 66 | 21 |
| 57 | `tornado` | 30 | 0.03% | 323 x 276 | 7 |
| 43 | `firecracker-evolution` | 30 | 0.03% | 54 x 75 | 17 |
| 75 | `battle-ram` | 30 | 0.03% | 47 x 84 | 21 |
| 123 | `royal-giant-evolution` | 29 | 0.02% | 119 x 106 | 16 |
| 119 | `graveyard` | 29 | 0.02% | 242 x 203 | 3 |
| 110 | `witch` | 29 | 0.02% | 67 x 68 | 17 |
| 53 | `elixir-golem-small` | 27 | 0.02% | 31 x 31 | 6 |
| 41 | `skeleton-barrel` | 27 | 0.02% | 75 x 114 | 12 |
| 144 | `valkyrie-evolution` | 27 | 0.02% | 59 x 64 | 35 |
| 78 | `bomb` | 25 | 0.02% | 51 x 54 | 10 |
| 54 | `goblin-barrel` | 23 | 0.02% | 80 x 81 | 21 |
| 116 | `axe` | 22 | 0.02% | 54 x 57 | 18 |
| 92 | `phoenix-big` | 22 | 0.02% | 108 x 72 | 19 |
| 152 | `tesla-evolution-shock` | 22 | 0.02% | 188 x 167 | 0 |
| 125 | `rocket` | 20 | 0.02% | 82 x 95 | 21 |
| 94 | `phoenix-small` | 17 | 0.01% | 90 x 77 | 14 |
| 143 | `ice-spirit-evolution` | 17 | 0.01% | 47 x 49 | 11 |
| 76 | `battle-ram-evolution` | 14 | 0.01% | 68 x 114 | 11 |
| 26 | `zap` | 12 | 0.01% | 154 x 126 | 9 |
| 86 | `freeze` | 12 | 0.01% | 184 x 148 | 5 |
| 27 | `giant-snowball` | 10 | 0.01% | 96 x 97 | 11 |
| 44 | `royal-delivery` | 9 | 0.01% | 91 x 128 | 9 |
| 129 | `lightning` | 9 | 0.01% | 161 x 151 | 7 |
| 150 | `goblin-ball` | 9 | 0.01% | 53 x 60 | 8 |
| 93 | `phoenix-egg` | 8 | 0.01% | 38 x 45 | 7 |
| 151 | `skeleton-king-skill` | 8 | 0.01% | 241 x 201 | 4 |
| 153 | `ice-spirit-evolution-symbol` | 6 | 0.01% | 28 x 32 | 6 |
| 148 | `mirror` | 5 | 0.00% | 185 x 151 | 0 |

## Klassen ohne jede Box in den echten Frames

48 von 201: `clone`, `zap-evolution`, `pad_0`, `pad_1`, `pad_2`, `pad_3`, `pad_4`, `pad_5`, `pad_6`, `pad_7`, `pad_8`, `pad_9`, `pad_10`, `pad_11`, `pad_12`, `pad_13`, `pad_14`, `pad_15`, `pad_16`, `pad_17`, `pad_18`, `pad_19`, `pad_20`, `pad_21`, `pad_22`, `pad_23`, `pad_24`, `pad_25`, `pad_26`, `pad_27`, `pad_28`, `pad_29`, `pad_30`, `pad_31`, `pad_32`, `pad_33`, `pad_34`, `pad_35`, `pad_36`, `pad_37`, `pad_38`, `pad_39`, `pad_40`, `pad_41`, `pad_42`, `pad_43`, `pad_44`, `pad_belong`

> Genau diese Klassen muss der Generator kuenstlich hochziehen - aus echten Spielen kommen dafuer zu wenige oder gar keine Beispiele.

## Cutout-Ordner ohne Bilder

0: -
