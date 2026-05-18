# --- Do not remove these libs ---
from freqtrade.strategy.interface import IStrategy
from typing import Dict, List
from functools import reduce
from pandas import DataFrame
import talib.abstract as ta
import numpy as np
import freqtrade.vendor.qtpylib.indicators as qtpylib
from datetime import datetime, timedelta
from freqtrade.persistence import Trade
from freqtrade.strategy import DecimalParameter, IntParameter
# --------------------------------

def EWO(dataframe, ema_length=5, ema2_length=35):
    ema1 = ta.EMA(dataframe, timeperiod=ema_length)
    ema2 = ta.EMA(dataframe, timeperiod=ema2_length)
    return (ema1 - ema2) / dataframe['close'] * 100

########################################################################################################################################################
class Ev5(IStrategy):
########################################################################################################################################################
# Hyperopt
########################################################################################################################################################
    buy_params = {
        "lookback_candles": 24,
        "profit_threshold": 1.03,
        "base_nb_candles_buy": 19,
        "ewo_high": 5.417,
        "ewo_low": -17.251,
        "low_offset": 0.983,
        "rsi_buy": 61,
    }
    sell_params = {
        "base_nb_candles_sell": 24,
        "high_offset": 1.011,
        "high_offset_2": 0.997,
    }
########################################################################################################################################################
# Main
########################################################################################################################################################
    can_short = False

    minimal_roi = {
        "0": 0.05,
        "40": 0.04,
        "201": 0.03
    }
    ignore_roi_if_entry_signal = False

    stoploss = -0.25
    use_custom_stoploss = False

    trailing_stop = True
    trailing_stop_positive = 0.001
    trailing_stop_positive_offset = 0.01
    trailing_only_offset_is_reached = True

    use_entry_signal = True
    use_exit_signal = False

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
    fast_ewo = 50
    slow_ewo = 200

    enable_opt_buy = True
    # Buy Params
    base_nb_candles_buy = IntParameter(5, 80, default=17, space='buy', optimize=enable_opt_buy)
    ewo_high = DecimalParameter(2.0, 12.0, default=3.34, space='buy', optimize=enable_opt_buy)
    ewo_low = DecimalParameter(-20.0, -8.0, default=-17.457, space='buy', optimize=enable_opt_buy)
    low_offset = DecimalParameter(0.9, 0.99, default=0.978, space='buy', optimize=enable_opt_buy)
    rsi_buy = IntParameter(30, 70, default=60, space='buy')

    # Sell Params
    base_nb_candles_sell = IntParameter(5, 80, default=39, space='sell', optimize=False)
    high_offset = DecimalParameter(0.99, 1.1, default=1.011, space='sell', optimize=False)
    high_offset_2 = DecimalParameter(0.99, 1.5, default=0.997, space='sell', optimize=False)

    # Additional logic thresholds (needed if using advanced filters)
    lookback_candles = IntParameter(10, 48, default=24, space='buy', optimize=False)
    profit_threshold = DecimalParameter(1.02, 1.10, default=1.03, space='buy', optimize=False)
########################################################################################################################################################
# Infromative
########################################################################################################################################################
    def informative_pairs(self):
        return [(pair, self.informative) for pair in self.dp.current_whitelist()]

    def get_informative_indicators(self, metadata: dict):
        return self.dp.get_pair_dataframe(pair=metadata['pair'], timeframe=self.informative)
########################################################################################################################################################
# Indicators
########################################################################################################################################################
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Precompute all possible ma_buy_ values for hyperopt
        for val in self.base_nb_candles_buy.range:
            dataframe[f'ma_buy_{val}'] = ta.EMA(dataframe, timeperiod=val)
    
        # Precompute all possible ma_sell_ values for hyperopt
        for val in self.base_nb_candles_sell.range:
            dataframe[f'ma_sell_{val}'] = ta.EMA(dataframe, timeperiod=val)
    
        # Standard indicators
        dataframe['EWO'] = EWO(dataframe, self.fast_ewo, self.slow_ewo)
        dataframe['rsi'] = ta.RSI(dataframe, timeperiod=14)
        dataframe['rsi_fast'] = ta.RSI(dataframe, timeperiod=4)
        dataframe['rsi_slow'] = ta.RSI(dataframe, timeperiod=20)
        dataframe['hma_50'] = qtpylib.hull_moving_average(dataframe['close'], window=50)
    
        return dataframe
########################################################################################################################################################
# Entry
########################################################################################################################################################
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe['enter_long'] = 0
        dataframe['enter_tag'] = None

        # --- Condition 1: EWO High ---
        ewo_high_condition = (
            (dataframe['close'] < dataframe[f'ma_buy_{self.base_nb_candles_buy.value}'] * self.low_offset.value) &
            (dataframe['EWO'] > self.ewo_high.value) &
            (dataframe['rsi'] < self.rsi_buy.value) &
            (dataframe['volume'] > 0)
        )
        dataframe.loc[ewo_high_condition, ['enter_long', 'enter_tag']] = [1, 'ewo_high']

        # --- Condition 2: EWO Low ---
        ewo_low_condition = (
            (dataframe['close'] < dataframe[f'ma_buy_{self.base_nb_candles_buy.value}'] * self.low_offset.value) &
            (dataframe['EWO'] < self.ewo_low.value) &
            (dataframe['rsi'] < self.rsi_buy.value) &
            (dataframe['volume'] > 0)
        )
        dataframe.loc[ewo_low_condition, ['enter_long', 'enter_tag']] = [1, 'ewo_low']

        return dataframe
########################################################################################################################################################
# Exit
########################################################################################################################################################
    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        conditions = []

        conditions.append(
            (dataframe['close'] > dataframe[f'ma_sell_{self.base_nb_candles_sell.value}'] * self.high_offset.value) & (dataframe['volume'] > 0)
            )

        if conditions:
            dataframe.loc[
                reduce(lambda x, y: x | y, conditions),
                ['exit_long', 'exit_tag']
            ] = [1, 'nb']

        return dataframe
########################################################################################################################################################
# Custom to Sell unclog
########################################################################################################################################################
#    def custom_exit(self, pair: str, trade: 'Trade', current_time: 'datetime', current_rate: float, current_profit: float, **kwargs):
#        # Sell any positions at a loss if they are held for more than X days.
#        if current_profit <= 0 and (current_time - trade.open_date_utc).days >= 10:
#            return 'unclog'
#
#        if current_profit >= 0 and (current_time - trade.open_date_utc).days >= 10:
#            return 'unclog'