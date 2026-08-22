# AUREUS

Bot de trading [Freqtrade](https://www.freqtrade.io/) sur OKX perpetual futures
(BTC/USDT:USDT, ETH/USDT:USDT). Entrées 5m, régime 1h, **dry-run par défaut**,
1 position max, `Decimal` obligatoire pour tout ce qui est monétaire.

Architecture complète : [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Statut

**Étape 1 / 8 — socle technique.** La stratégie se charge dans Freqtrade mais
**ne peut ouvrir aucun trade** (aucun signal + `confirm_trade_entry` refuse tout).

## Structure

- `user_data/strategies/AureusStrategy.py` — stratégie Freqtrade (adaptateur mince)
- `user_data/strategies/aureus/` — package métier (stdlib uniquement à ce stade) :
  `config_schema` (validation fail-fast), `boundary` (frontière Decimal),
  `state` (persistence JSON atomique), `diagnostics` (événements JSONL)
- `user_data/config/` — configs dry-run/backtest OKX
- `scripts/` — Docker + lanceurs
- `tests/` — tests unitaires

## Développement local

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"            # tests sans Freqtrade
pip install -e ".[dev,freqtrade]"  # tests complets + commandes freqtrade

pytest
ruff check .
```

## Dry-run

Sans Docker (Freqtrade installé dans le venv) :

```bash
freqtrade trade \
  --config user_data/config/config.common.json \
  --config user_data/config/config.dryrun.json \
  --strategy AureusStrategy
```

Avec Docker :

```bash
./scripts/run_dryrun.sh
```

Aucune clé API n'est requise en dry-run. Pour plus tard, copier `.env.example`
vers `.env` (jamais committé).

## Fichiers runtime

- État persistant : `user_data/aureus_state.json` (kill switch, cooldowns)
- Diagnostics : `user_data/logs/aureus_diagnostics.jsonl` (une ligne JSON par événement)
