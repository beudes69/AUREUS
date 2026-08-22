# AUREUS — Architecture technique

> Bot de trading Freqtrade sur OKX perpetual futures (BTC/USDT:USDT, ETH/USDT:USDT).
> Entrées 5m, régime 1h, dry-run par défaut, 1 position max, Decimal obligatoire pour tout ce qui est monétaire, pas de ML.

---

## 1. Arborescence finale du projet

```
aureus/
├── pyproject.toml                  # deps, pytest, ruff, mypy ; package "aureus" installable (pip install -e .)
├── README.md
├── docs/
│   ├── ARCHITECTURE.md             # ce document
│   └── RUNBOOK.md                  # (étape finale) procédures : incidents, comportement HALT, go-live
├── user_data/
│   ├── strategies/
│   │   ├── AureusStrategy.py       # SEULE classe Freqtrade — adaptateur mince, zéro logique métier
│   │   └── aureus/                 # package métier (sous strategies/ ⇒ importable sans install en container)
│   │       ├── __init__.py
│   │       ├── config_schema.py    # validation fail-fast de la config au démarrage
│   │       ├── boundary.py         # frontière Decimal ⇄ float, quantization aux précisions exchange
│   │       ├── indicators.py       # indicateurs purs (DataFrame in → DataFrame out)
│   │       ├── regime.py           # RegimeEngine 1h (TREND_UP/TREND_DOWN/RANGE/HIGH_VOL/UNKNOWN)
│   │       ├── entry_plan.py       # EntryPlan (frozen dataclass, Decimal) + TTL + invalidation
│   │       ├── risk.py             # RiskEngine pur : sizing, levier, stop, REJECT
│   │       ├── playbooks/
│   │       │   ├── base.py         # interface Playbook + SignalCandidate
│   │       │   ├── trend_pullback.py
│   │       │   └── breakout.py
│   │       ├── gates/              # gardes I/O au moment de l'exécution
│   │       │   ├── funding.py      # FundingGate (veto, dégradation neutre si data absente)
│   │       │   ├── liquidity.py    # LiquidityGate (spread + profondeur, conversion contractSize)
│   │       │   ├── killswitch.py   # DailyKillSwitch persistant (-2R / -3% DD)
│   │       │   └── cooldown.py     # CooldownManager post-loss
│   │       ├── state.py            # persistence état global (JSON atomique temp+rename ou SQLite)
│   │       └── diagnostics.py      # événements funnel, logs JSONL structurés, corrélation plan_id
│   └── config/
│       ├── config.common.json      # pairs, timeframe, order_types, unfilledtimeout, max_open_trades=1
│       ├── config.dryrun.json      # dry_run=true, wallet simulé
│       └── config.backtest.json
├── scripts/
│   ├── Dockerfile                  # base freqtradeorg/freqtrade:stable + package aureus + deps test
│   ├── docker-compose.yml          # service dryrun ; volumes user_data/ (db, logs, état)
│   ├── run_dryrun.sh
│   ├── run_backtest.sh
│   ├── run_validation.sh           # lookahead-analysis + recursive-analysis + backtest de référence
│   ├── verify_okx_contracts.py     # vérif one-shot CCXT : contractSize, precision, limits, unités orderbook
│   ├── walkforward.py              # découpe timerange en fenêtres roulantes, agrège les métriques
│   ├── montecarlo.py               # bootstrap des trades du backtest → distributions DD / retour final
│   └── zero_trade_report.py        # diagnostic ZERO TRADE : quel gate tue quels candidats
└── tests/
    ├── conftest.py                 # fixtures OHLCV synthétiques (tendance, range, spike vol)
    ├── test_boundary.py
    ├── test_indicators.py
    ├── test_regime.py
    ├── test_playbooks.py
    ├── test_risk_properties.py     # property-based (hypothesis) : invariants du risque
    ├── test_entry_plan.py          # TTL, invalidation, immutabilité
    ├── test_gates.py               # funding, liquidity (contractSize), killswitch, cooldown
    ├── test_state_persistence.py   # crash/restart : l'état survit
    └── test_strategy_callbacks.py  # intégration : callbacks Freqtrade mockés bout-en-bout
```

~25 fichiers de code au total. Pas de framework maison : le package `aureus` est une bibliothèque de fonctions pures + 4 gates I/O, orchestrée par une seule stratégie Freqtrade.

---

## 2. Responsabilité de chaque module

| Module | Responsabilité | Contrainte clé |
|---|---|---|
| `AureusStrategy.py` | Adaptateur Freqtrade : `populate_*`, `leverage`, `custom_stake_amount`, `custom_entry_price`, `confirm_trade_entry`, `custom_stoploss`, `adjust_trade_position`, `custom_exit`, `order_filled`. Délègue tout. | Zéro calcul métier. Chaque callback est **fail-closed** : pas de plan valide ⇒ pas de trade. |
| `config_schema.py` | Valide la config au boot : `max_open_trades=1`, format des paires, `startup_candle_count` compatible avec la limite OHLCV OKX, `dry_run=true` par défaut, seuils de risque. | Échec ⇒ le bot refuse de démarrer. |
| `boundary.py` | Seul endroit où l'on convertit Decimal ⇄ float. Quantization explicite aux précisions exchange (prix, step de contrat). Comptabilité parallèle Decimal du PnL/R avec alerte si divergence vs Freqtrade > tolérance. | Aucun float monétaire ne circule dans `aureus/*`. |
| `indicators.py` | EMA, ATR, swings (pivots confirmés), Donchian, ADX, réalised vol… Fonctions pures vectorisées. | Interdiction de `shift(-1)` / données futures. Testé unitairement. |
| `regime.py` | Classifie chaque bougie 1h close : `TREND_UP`, `TREND_DOWN`, `RANGE`, `HIGH_VOL`, `UNKNOWN`. Hystérésis : N bougies 1h de confirmation avant changement de régime. | `UNKNOWN` par défaut (démarrage, data insuffisante). Ne lit que des bougies 1h **closes**. |
| `playbooks/` | Chaque playbook = fonction pure : (df 5m enrichi, régime) → `SignalCandidate` (direction, niveau structurel de stop, zone d'entrée, invalidation) ou rien. `trend_pullback` actif en TREND_*, `breakout` actif en TREND_* (cassure dans le sens du régime). `RANGE`/`HIGH_VOL`/`UNKNOWN` ⇒ aucun playbook actif ⇒ no trade. | Un playbook ne dimensionne jamais : il propose des **niveaux**, pas des tailles. |
| `entry_plan.py` | `EntryPlan` : frozen dataclass, tout en Decimal — `plan_id` (uuid), pair, direction, playbook, ts bougie signal, zone d'entrée, `stop_price`, `invalidation_price`, `risk_amount`, `notional`, `amount` (arrondi au step de contrat), `stake` (marge), `leverage`, `tp1_price` (+1R), `ttl_candles`, régime à la création. Méthodes `is_expired(now)` / `is_invalidated(price, regime)`. | **Unique source de vérité** : tous les callbacks lisent le même objet, rien n'est recalculé entre `leverage()` et `confirm_trade_entry()`. |
| `risk.py` | Construit l'EntryPlan à partir d'un SignalCandidate + equity. Stop = structure ± buffer ATR. Sizing 1% equity. Toute violation ⇒ `Reject(reason)`, jamais d'ajustement du stop. | Pur, 100% Decimal, property-tested. Détail des formules en §4. |
| `gates/funding.py` | Veto d'entrée si funding adverse au-delà d'un seuil dans une fenêtre avant le **prochain settlement réel** : horodatage lu depuis l'exchange (`nextFundingTimestamp` / `fundingTimestamp` CCXT), **jamais supposé** à 00:00/08:00/16:00 UTC. Taux indisponible ⇒ **neutre** + flag diagnostic. Prochain settlement inconnu ⇒ politique configurable `unknown_funding_policy` (`neutral` par défaut, `block` possible). | Adapter fin autour de l'API Freqtrade/CCXT, cache court. |
| `gates/liquidity.py` | Sur `dp.orderbook()` : spread ≤ max bps ; profondeur cumulée dans ±K bps ≥ M × notionnel visé. **Conversion contrats → base via `market['contractSize']` lu au boot depuis les métadonnées CCXT du marché — jamais codé en dur.** | Échec ou data douteuse ⇒ REJECT (ici, contrairement au funding, on est fail-closed : c'est un contrôle d'exécution). |
| `gates/killswitch.py` | Accumulateurs journaliers : `daily_equity_anchor` fixée à 00:00 UTC (référence du DD quotidien — **distincte** de `current_equity`, l'equity mark-to-market utilisée pour le sizing), R réalisé, DD incluant l'unrealized. Déclenche si R jour ≤ −2R **ou** DD ≥ 3%. Une fois HALT : **aucune nouvelle entrée jusqu'au reset UTC — pas de re-arm manuel en v1**. **Persistant** : survit au restart. | Ne force pas la clôture de la position ouverte (comportement documenté, configurable). |
| `gates/cooldown.py` | Après un trade perdant : aucune entrée sur la paire pendant N bougies 5m. Persistant. | |
| `state.py` | Persistence de l'état global (killswitch, cooldown, plan en attente par paire) : fichier JSON écrit atomiquement (temp + rename) sous `user_data/`. Les flags **par trade** (`partial_1r_filled`, `plan_id`) passent par `trade.set_custom_data()` (DB Freqtrade). | Chaque écriture est atomique ; lecture tolérante (état corrompu ⇒ état le plus conservateur : killswitch armé, plan invalide). |
| `diagnostics.py` | Événements JSONL structurés, un enum de stages : `signal_generated → plan_created → plan_rejected(reason) → entry_approved / entry_rejected(reason) → order_created → order_filled → entry_timeout → partial_order_created → partial_filled → trailing_armed → exited(reason)`. Chaque ligne porte `plan_id`. | C'est la matière première du ZERO TRADE report. |
| `scripts/` | Wrappers Docker/Freqtrade + labo de validation (voir §6 et étape 7). | Aucune logique métier dupliquée : `walkforward.py` et `montecarlo.py` consomment les exports de `freqtrade backtesting`. |

---

## 3. Flux exact d'une entrée jusqu'à la sortie

`process_only_new_candles = True` — tout se joue sur bougies closes.

1. **Bougie 5m close** → `populate_indicators` : indicateurs 5m + informative 1h via `merge_informative_pair` (ffill, jamais de shift négatif). La colonne `regime` est calculée par `regime.py` sur les 1h closes uniquement.
2. **`populate_entry_trend`** : pour chaque playbook éligible au régime courant, flags vectorisés. `RANGE`/`HIGH_VOL`/`UNKNOWN` ⇒ aucun flag. Signal ⇒ événement `signal_generated`.
3. **Construction du plan** : sur signal, `risk.py` construit l'`EntryPlan` (Decimal, cf. §4) et le stocke dans le pending-plan store (`state.py`), TTL = N bougies 5m. Échec ⇒ `plan_rejected(reason)`, aucun trade. Succès ⇒ `plan_created`.
4. **Callbacks d'entrée Freqtrade** (dans l'ordre d'appel) — chacun lit le plan, aucun ne recalcule :
   - `leverage()` → `plan.leverage` (float via `boundary`). Pas de plan valide ⇒ 1.
   - `custom_stake_amount()` → `plan.stake`. Pas de plan valide ⇒ 0 (le trade est skippé).
   - `custom_entry_price()` → prix dans la zone d'entrée du plan (entrée limit).
   - `confirm_trade_entry()` — **dernier gate, fail-closed** : plan présent, non expiré (TTL), non invalidé (prix/régime), dérive prix courant vs plan ≤ tolérance, killswitch désarmé, cooldown écoulé, FundingGate OK, LiquidityGate OK. Un seul échec ⇒ `entry_rejected(reason)` + plan consommé. Sinon `entry_approved` puis `order_created`.
5. **Fill ou timeout** : `order_filled` (ordre d'entrée) ⇒ `order_filled`, `plan_id` attaché au trade via `set_custom_data`, plan retiré du pending store. Sinon `unfilledtimeout` ⇒ annulation, événement `entry_timeout`, plan expiré.
6. **Gestion de position** :
   - `custom_stoploss` (avec `use_custom_stoploss=True`) retourne le stop **du plan** via `stoploss_from_absolute(plan.stop_price, current_rate, is_short, leverage)`. Statique tant que le partial n'est pas rempli.
   - **Partial +1R** : quand le prix atteint `tp1_price`, `adjust_trade_position` retourne un stake négatif (réduction ~50%) en ordre limit ⇒ `partial_order_created`. Le flag `partial_1r_filled` n'est posé **que** dans `order_filled` pour cet ordre de sortie, persisté via `set_custom_data`. Jamais marqué DONE sur simple placement d'ordre.
   - **Trailing** : uniquement si `partial_1r_filled` est persisté. `custom_stoploss` passe alors à breakeven + frais, puis trail structure/ATR ⇒ `trailing_armed`.
7. **Sortie** : stop touché, trailing touché, ou `custom_exit` (flip de régime contre la position, invalidation structurelle, time-stop). Événement `exited(reason)`.
8. **Post-trade** : PnL/R recalculés en Decimal (shadow accounting `boundary.py`), accumulateurs killswitch mis à jour, cooldown démarré si perte, tout journalisé avec le `plan_id`.

---

## 4. Flux du risque

Tout en Decimal. Deux grandeurs d'equity distinctes :

- **`daily_equity_anchor`** : equity capturée à 00:00 UTC et persistée — sert **uniquement** de référence au drawdown quotidien du kill switch.
- **`current_equity`** : equity mark-to-market au moment du signal — sert **uniquement** au sizing du prochain trade.

Notations : `p_e` = prix d'entrée prévu, `p_s` = stop structurel.

1. **Ancre journalière** : à 00:00 UTC, `daily_equity_anchor` capturée et persistée.
2. **Budget risque** : `risk_amount = current_equity × risk_per_trade` (0.01 initial).
3. **Stop structurel** : `p_s` = swing low/high confirmé ± `k × ATR(5m)` de buffer. Distance `d = |p_e − p_s| / p_e`.
4. **Garde-fous stop — REJECT, jamais d'ajustement** :
   - `d > d_max` (plafond en % et en multiples d'ATR) ⇒ **REJECT** `stop_too_wide`. On n'approche jamais le stop de l'entrée pour faire passer le sizing.
   - `d < d_min` (bruit/spread) ⇒ REJECT `stop_too_tight`.
5. **Sizing** : `notional = risk_amount / d` ; `amount = notional / p_e`, arrondi **vers le bas** au step de contrat **lu des métadonnées CCXT du marché** (jamais codé en dur). Après arrondi, recalcul du risque réalisé : s'il dépasse `1% + ε` ⇒ REJECT `granularity` ; si `amount = 0` ⇒ REJECT `below_min_contract`.
6. **Levier** : `leverage = min(ceil_needed, 5)` avec `stake = notional / leverage`. Si `stake > marge disponible` même à 5x ⇒ **downsize-only** : on réduit `notional` (risque effectif < 1%, jamais >). Seul fallback autorisé dans tout le système : réduire la taille. Jamais élargir/rétrécir le stop, jamais dépasser 5x.
7. **Buffer de liquidation** : distance stop → prix de liquidation estimé ≥ marge de sécurité, sinon REJECT `liquidation_buffer`.
8. **Pré-trade (gates)** : killswitch, cooldown, funding, liquidité — cf. §3 étape 4.
9. **In-trade** : stop du plan seul jusqu'au fill réel du partial +1R ; ensuite BE+frais puis trailing. Aucun élargissement de stop, jamais.
10. **Post-trade / journalier** : R réalisé ajouté à l'accumulateur ; si `ΣR_jour ≤ −2` **ou** `(daily_equity_anchor − current_equity)/daily_equity_anchor ≥ 3%` (unrealized inclus) ⇒ killswitch armé et persisté ⇒ **HALT : plus aucune entrée jusqu'au reset UTC, sans re-arm manuel (v1)**. Perte ⇒ cooldown paire.

---

## 5. Points critiques Freqtrade/OKX à vérifier

1. **Unités de l'orderbook** : CCXT renvoie les tailles OKX swap en **contrats**, pas en base. Conversion obligatoire via `market['contractSize']`, **lu dynamiquement des métadonnées CCXT du marché — aucune valeur codée en dur**. Au boot : vérifier présence et cohérence de `contractSize`, `precision` et `limits` pour chaque paire tradée (fail-fast si absent ou aberrant). `verify_okx_contracts.py` fait la même vérification en one-shot hors bot.
2. **Limite OHLCV par appel** : OKX limite les bougies par requête (≈300 endpoint récent, moins en historique). En live, `startup_candle_count` (et le besoin de l'informative 1h) doit tenir dans `ohlcv_candle_limit` de la classe `Okx` de Freqtrade — vérifier la valeur exacte dans la version utilisée et dimensionner le régime en conséquence.
3. **Funding via API publique** : Freqtrade applique les funding fees au PnL futures automatiquement, mais le DataProvider n'expose pas forcément de méthode publique pour le **taux** courant selon la version. À vérifier ; sinon adapter fin sur `fetch_funding_rate` CCXT, isolé dans `gates/funding.py`, avec dégradation neutre.
4. **Config futures** : `trading_mode: futures`, `margin_mode: isolated`, paires `BTC/USDT:USDT`. Compte OKX en **position mode "net"** (one-way) — le mode hedge fait échouer les ordres via Freqtrade (`posSide`).
5. **Callback `order_filled`** : disponibilité et signature dans la version Freqtrade cible (pivot du "partial DONE après fill réel"). Si absent, fallback : scan des ordres du trade dans `adjust_trade_position` — à trancher à l'étape 6.
6. **Stoploss on exchange OKX** : supporté (algo orders) mais comportement à valider. Décision : stop géré par le bot en dry-run, activation on-exchange validée avant tout go-live.
7. **`custom_stoploss` et levier** : le stop relatif doit être calculé via `stoploss_from_absolute(..., leverage=trade.leverage)` — piège classique en futures (stop en % de la marge vs % du prix).
8. **Lookahead informative** : `merge_informative_pair(..., ffill=True)` gère le décalage 1h→5m, mais toute colonne dérivée doit être validée par `freqtrade lookahead-analysis` ; indicateurs récursifs (EMA sur fenêtre tronquée) par `recursive-analysis`.
9. **Granularité des contrats vs petit compte** : 1 contrat (taille = `contractSize` lu des métadonnées) peut imposer un notionnel minimal élevé ; le recalcul du risque post-arrondi (§4.5) est indispensable, sinon un compte modeste dépasse silencieusement 1%.
10. **`dp.orderbook()` = appel REST** à chaque invocation : cache court (quelques secondes) dans LiquidityGate pour respecter les rate limits OKX sans trader sur un carnet périmé.
11. **`unfilledtimeout` / `order_types`** : entrée limit + timeout court cohérent avec le TTL du plan ; sortie stop en market.

---

## 6. Améliorations proposées (au-delà du cahier des charges)

1. **Corrélation `plan_id` bout-en-bout** : chaque ligne de log, du signal à la sortie, porte l'uuid du plan. Post-mortem et ZERO TRADE report deviennent triviaux (jointure sur un champ).
2. **Machine à états explicite** du cycle de vie (enum unique de stages, transitions validées) au lieu de flags booléens épars — les états illégaux (trailing sans partial) deviennent impossibles par construction, pas seulement testés.
3. **Shadow accounting Decimal** : recalcul indépendant du PnL/R en Decimal et alerte si divergence avec les floats Freqtrade > tolérance. Détecte immédiatement les bugs d'unités, de contractSize ou de précision — la classe de bugs la plus coûteuse en futures.
4. **Fail-fast au boot** : `config_schema.py` + asserts marchés (contractSize, précisions, limits, mode net). Le bot refuse de démarrer plutôt que de trader sur des hypothèses fausses.
5. **Hystérésis de régime** : N bougies 1h de confirmation avant tout changement, `UNKNOWN` par défaut. Supprime le whipsaw de régime, première cause de faux signaux d'un moteur 1h.
6. **Property-based testing (hypothesis) sur le RiskEngine** : sur des milliers d'entrées générées — risque ≤ 1%+ε, levier ≤ 5, stop du bon côté, `amount` multiple du step, REJECT ⇔ aucune sortie partielle d'objet. Bien plus fort que des cas unitaires choisis à la main.
7. **Fenêtre d'évitement funding** : pas d'entrée X minutes avant le prochain settlement (horodatage réel `nextFundingTimestamp` de l'exchange, jamais des heures fixes supposées) si le funding est adverse au-delà du seuil ; settlement inconnu ⇒ politique configurable `unknown_funding_policy`.
8. **Time-stop par playbook** : sortie si +1R n'est pas atteint en N bougies. Réduit l'exposition aux trades morts et améliore mécaniquement l'espérance par unité de temps de risque.
9. **Downsize-only comme unique fallback** codifié dans `risk.py` : la seule dégradation autorisée du système est de réduire la taille. Tout le reste est REJECT. Une règle, zéro ambiguïté.
10. **Kill-switch sans re-arm manuel en v1** : une fois HALT, aucune nouvelle entrée jusqu'au reset UTC (00:00) — moins de surface d'erreur opérateur. Un re-arm manuel pourra être évalué après la première version stable.

---

## 7. Ordre recommandé de développement

1. **Socle** : pyproject, Docker/compose, configs, `config_schema`, `boundary` (Decimal + quantization), `state` (persistence atomique), `diagnostics` (funnel + plan_id), squelette de tests. Le bot démarre en dry-run et loggue, sans trader.
2. **Indicators + RegimeEngine** : indicateurs purs, classification 1h avec hystérésis, fixtures synthétiques, tests anti-lookahead unitaires.
3. **RiskEngine + EntryPlan** : sizing Decimal complet, tous les chemins REJECT, TTL/invalidation, property-based tests. Aucune dépendance Freqtrade — testable seul.
4. **Playbooks + Strategy** : trend_pullback, breakout, `AureusStrategy` câblée (populate_* + callbacks lisant l'EntryPlan), tests d'intégration mockés. Premier backtest de fumée possible.
5. **Gates d'exécution** : liquidity (avec `verify_okx_contracts.py`), funding, cooldown, killswitch persistant. Tests de crash/restart.
6. **Gestion de position** : partial +1R via `adjust_trade_position` + `order_filled`, flags persistés, trailing conditionnel, time-stop. C'est l'étape la plus sensible aux versions Freqtrade (point §5.5).
7. **Validation lab** : `run_validation.sh` (lookahead-analysis, recursive-analysis, backtest de référence), `walkforward.py`, `montecarlo.py`, `zero_trade_report.py`.
8. **Dry-run prolongé OKX + RUNBOOK** : observation multi-jours, analyse ZERO TRADE, calibrage des seuils de gates, runbook opérateur. Critères de sortie avant toute discussion live.
