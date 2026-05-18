# === Standard Library ===
from functools import reduce
from datetime import datetime, timedelta

# === Third-Party Libraries ===
from pandas import DataFrame
import talib.abstract as ta
import freqtrade.vendor.qtpylib.indicators as qtpylib
from typing import Dict, List

# === Freqtrade Core ===
from freqtrade.persistence import Trade
from freqtrade.strategy.interface import IStrategy
from freqtrade.strategy import (
    merge_informative_pair,
    stoploss_from_open,
    DecimalParameter,
    IntParameter,
    CategoricalParameter
)

########################################################################################################################################################
class BigTrader2(IStrategy):
########################################################################################################################################################
# Hyperopt
########################################################################################################################################################
    buy_params = {
        "low_offset": 0.958
    }
    sell_params = {
        "base_nb_candles_sell": 16,
        "high_offset": 1.084,
        "high_offset_2": 1.401, 
    }
    slippage_protection = {
        'retries': 3,
        'max_slippage': -0.02
    }
########################################################################################################################################################
# Main
########################################################################################################################################################
    can_short = False

    minimal_roi = {
        "0": 0.09,
    }
    ignore_roi_if_entry_signal = False

    stoploss = -0.25
    use_custom_stoploss = False

    trailing_stop = True
    trailing_stop_positive = 0.001
    trailing_stop_positive_offset = 0.01
    trailing_only_offset_is_reached = True

    use_entry_signal = True
    use_custom_entry = False

    use_exit_signal = True
    use_custom_exit = True

    exit_profit_only = False
    exit_profit_offset = 0.03
########################################################################################################################################################
# Main
########################################################################################################################################################
    timeframe = '5m'
    informative = '1h'
    process_only_new_candles = False
    startup_candle_count = 200

    order_types = {
        'entry': 'market',
        'exit': 'market',
        'trailing_stop_loss': 'market',
        'emergency_exit': 'market',
        'force_entry': 'market',
        'force_exit': 'market',
        'stoploss': 'market',
        'stoploss_on_exchange': False,
        'stoploss_on_exchange_interval': 60,
        'stoploss_on_exchange_limit_ratio': 0.99
    }
    order_time_in_force = {
        'entry': 'gtc',
        'exit': 'gtc'
    }
    plot_config = {
        'main_plot': {
            'ma_buy': {'color': 'orange'},  # Color for the buy moving average.
            'ma_sell': {'color': 'orange'},  # Color for the sell moving average.
        },
    }
########################################################################################################################################################
# Trade Protections
########################################################################################################################################################
    @property
    def protections(self):
        return [
            # Cooldown any signal for 5 candles (25 m) after a trade
            { "method": "CooldownPeriod", "stop_duration_candles": 5 },

            # Allow up to 3% drawdown over the last 9 h before pausing
            {
                "method": "MaxDrawdown",
                "lookback_period_candles": 72,     # 6 h → 9 h
                "trade_limit": 20,
                "stop_duration_candles": 6,        # longer pause
                "max_allowed_drawdown": 0.03       # 3% drawdown allowed
            },

            # Only guard if you’ve lost >3% over a rolling 4 h period
            {
                "method": "StoplossGuard",
                "lookback_period_candles": 48,     # 4 h
                "trade_limit": 4,
                "stop_duration_candles": 4,
                "only_per_pair": False
            },

            # Prevent pairs that only net <2% profit over 2 h, block for 1 h
            {
                "method": "LowProfitPairs",
                "lookback_period_candles": 24,     # 2 h
                "trade_limit": 2,
                "stop_duration_candles": 12,       # 1 h
                "required_profit": 0.02            # 2%
            },

            # Prevent pairs that only net <4% profit over 12 h, block for 2 h
            {
                "method": "LowProfitPairs",
                "lookback_period_candles": 144,    # 12 h
                "trade_limit": 4,
                "stop_duration_candles": 24,       # 2 h
                "required_profit": 0.04            # 4%
            }
        ]
########################################################################################################################################################
########################################################################################################################################################
# Parameters
########################################################################################################################################################
    low_offset = DecimalParameter(0.958, 1.00, default=buy_params['low_offset'], space='buy', optimize=True)
    high_offset = DecimalParameter(0.95, 1.1, default=sell_params['high_offset'], space='sell', optimize=True)
    high_offset_2 = DecimalParameter(0.99, 1.5, default=sell_params['high_offset_2'], space='sell', optimize=True)
    base_nb_candles_sell = IntParameter(8, 20, default=sell_params['base_nb_candles_sell'], space='sell', optimize=True)
########################################################################################################################################################
# Indicators
########################################################################################################################################################
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe['hma_50'] = qtpylib.hull_moving_average(dataframe['close'], window=50)
        dataframe['ema_100'] = ta.EMA(dataframe, timeperiod=100)
        dataframe['sma_9'] = ta.SMA(dataframe, timeperiod=9)
        dataframe['sma_15'] = ta.SMA(dataframe, timeperiod=15)

        dataframe['rsi'] = ta.RSI(dataframe, timeperiod=14)
        dataframe['rsi_fast'] = ta.RSI(dataframe, timeperiod=4)
        dataframe['rsi_slow'] = ta.RSI(dataframe, timeperiod=20)

        dataframe[f'ma_sell_{self.base_nb_candles_sell.value}'] = ta.SMA(dataframe['close'], timeperiod=self.base_nb_candles_sell.value)

        return dataframe
########################################################################################################
# Entry Trade Logic (custom_entry)
########################################################################################################
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe['enter_long'] = 0
        dataframe['enter_tag'] = None
    
        # Entry condition
        entry_condition = (
            (dataframe['close'] < (dataframe['sma_15'] * self.low_offset.value)) &
            (dataframe['close'] > dataframe['close'].shift(4)) &
            (dataframe['close'].shift(8) > dataframe['close'].shift(4)) &
            (dataframe['close'].shift(12) > dataframe['close'].shift(8)) &
            (dataframe['volume'] > 0)
        )
    
        dataframe.loc[entry_condition, ['enter_long', 'enter_tag']] = [1, 'low_sma_15']
    
        return dataframe
########################################################################################################
# Exit Trade Logic
########################################################################################################
    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe['exit_long'] = 0
        dataframe['exit_tag'] = None

        # Exit 1: SMA-based
        exit1 = (
            (dataframe['close'] > dataframe['sma_9']) &
            (dataframe['close'] > (dataframe[f'ma_sell_{self.base_nb_candles_sell.value}'] * self.high_offset_2.value)) &
            (dataframe['rsi'] > 50) &
            (dataframe['volume'] > 0) &
            (dataframe['rsi_fast'] > dataframe['rsi_slow'])
        )
        dataframe.loc[exit1, ['exit_long', 'exit_tag']] = [1, 'sma_9']

        # Exit 2: HMA-based — only if exit_long not already set
        exit2 = (
            (dataframe['close'] < dataframe['hma_50']) &
            (dataframe['close'] > (dataframe[f'ma_sell_{self.base_nb_candles_sell.value}'] * self.high_offset.value)) &
            (dataframe['volume'] > 0) &
            (dataframe['rsi_fast'] > dataframe['rsi_slow']) &
            (dataframe['exit_long'] == 0)
        )
        dataframe.loc[exit2, ['exit_long', 'exit_tag']] = [1, 'hma_50']

        return dataframe
########################################################################################################################################################
# Custom to Sell unclog
########################################################################################################################################################
    def custom_exit(self, pair: str, trade: 'Trade', current_time: 'datetime', current_rate: float, current_profit: float, **kwargs):
        # Sell any positions at a loss if they are held for more than X days.
        if current_profit <= 0 and (current_time - trade.open_date_utc).days >= 10:
            return 'unclog'

        if current_profit >= 0 and (current_time - trade.open_date_utc).days >= 10:
            return 'unclog'