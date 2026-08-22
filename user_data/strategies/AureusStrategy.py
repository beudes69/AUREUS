"""AUREUS — stratégie Freqtrade minimale (étape 1 : socle).

Cette version est volontairement inerte : elle valide la configuration
(fail-fast), initialise la persistence et les diagnostics, et ne génère
JAMAIS de signal d'entrée. Triple verrou anti-trade :
1. ``populate_entry_trend`` force ``enter_long = enter_short = 0`` ;
2. ``confirm_trade_entry`` retourne toujours ``False`` (défense en profondeur) ;
3. la config impose ``dry_run=true`` et ``max_open_trades=1``.
"""

from pathlib import Path

from pandas import DataFrame

from freqtrade.strategy import IStrategy

from aureus.config_schema import validate_config
from aureus.diagnostics import DiagnosticsWriter, Event
from aureus.state import StateStore


class AureusStrategy(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "5m"
    can_short = True
    process_only_new_candles = True
    startup_candle_count = 0

    # Aucune sortie par ROI ; stoploss très large, jamais atteint (aucun trade
    # possible à l'étape 1) — le vrai stop viendra de l'EntryPlan.
    minimal_roi: dict = {}
    stoploss = -0.99
    use_exit_signal = True

    def bot_start(self, **kwargs) -> None:
        """Validation fail-fast + initialisation persistence/diagnostics."""
        aureus_config = validate_config(self.config)

        user_data_dir = Path(self.config["user_data_dir"])
        self._diagnostics = DiagnosticsWriter(user_data_dir / "logs" / "aureus_diagnostics.jsonl")
        self._state_store = StateStore(user_data_dir / "aureus_state.json")

        state = self._state_store.load()
        if state.recovered_from_corruption:
            self._diagnostics.emit(
                Event.STATE_RECOVERED_CORRUPT,
                payload={
                    "detail": "état persisté illisible : quarantaine effectuée, "
                    "redémarrage en mode conservateur (halted jusqu'au reset UTC)"
                },
            )
        # Re-persiste immédiatement : matérialise l'état conservateur éventuel.
        self._state_store.save(state)

        self._diagnostics.emit(
            Event.BOT_STARTED,
            payload={
                "dry_run": self.config.get("dry_run"),
                "risk_per_trade": aureus_config.risk_per_trade,
                "max_leverage": aureus_config.max_leverage,
                "halted": state.daily_risk.halted,
            },
        )
        self._diagnostics.emit(Event.CONFIG_VALIDATED)

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Étape 1 : aucun indicateur, aucune logique métier.
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Aucun signal, jamais.
        dataframe["enter_long"] = 0
        dataframe["enter_short"] = 0
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0
        dataframe["exit_short"] = 0
        return dataframe

    def confirm_trade_entry(
        self,
        pair: str,
        order_type: str,
        amount: float,
        rate: float,
        time_in_force: str,
        current_time,
        entry_tag,
        side: str,
        **kwargs,
    ) -> bool:
        # Défense en profondeur (étape 1) : même si un signal apparaissait,
        # aucune entrée n'est confirmée.
        return False
