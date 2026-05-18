# --- Do not remove these libs ---
import freqtrade.vendor.qtpylib.indicators as qtpylib
import talib.abstract as ta
from freqtrade.strategy.interface import IStrategy
from pandas import DataFrame, Series


# --------------------------------
import logging
import pandas as pd
import numpy as np
import time
import pandas_ta as pta

from datetime import datetime, timedelta, timezone
from functools import reduce
from typing import List
# --- Do not remove these libs ---

from typing import Dict, List
from freqtrade.persistence import Trade, PairLocks
from freqtrade.strategy import (BooleanParameter, DecimalParameter, RealParameter, IntParameter, stoploss_from_open, merge_informative_pair)
from skopt.space import Dimension, Integer

########################################################################################################################################################
class CofiBitStrategy(IStrategy):
########################################################################################################################################################
# Hyperopt
########################################################################################################################################################
    buy_params = {
    }
    sell_params = {
    }
    minimal_roi = {
        "40": 0.05,
        "30": 0.06,
        "20": 0.07,
        "0": 0.10
    }
    stoploss = -0.25
    trailing_stop = False
    trailing_stop_positive = 0.01
    trailing_stop_positive_offset = 0.0135
    trailing_only_offset_is_reached = False
    use_custom_stoploss = False
########################################################################################################################################################
# Main
    can_short = False
########################################################################################################################################################
    timeframe = '5m'  # The primary timeframe for analysis.
    process_only_new_candles = True
    startup_candle_count = 200

    use_exit_signal = False
    exit_profit_only = False
    exit_profit_offset = 0.01  # Offset added to exit signal (profitable threshold).
    ignore_roi_if_entry_signal = False  # If True, ignore ROI when the buy signal is still present.

    # Configuration of order types.
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

        # Order Time-In-Force defines how long an order will remain active before it is executed or expired.
    order_time_in_force = {
        'entry': 'gtc',
        'exit': 'gtc'
    }

    # Plotting configuration for visualizing indicators in backtesting.
    plot_config = {
        'main_plot': {
            'ma_buy': {'color': 'orange'},  # Color for the buy moving average.
            'ma_sell': {'color': 'orange'},  # Color for the sell moving average.
        },
    }

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        stoch_fast = ta.STOCHF(dataframe, 5, 3, 0, 3, 0)
        dataframe['fastd'] = stoch_fast['fastd']
        dataframe['fastk'] = stoch_fast['fastk']
        dataframe['ema_high'] = ta.EMA(dataframe, timeperiod=5, price='high')
        dataframe['ema_close'] = ta.EMA(dataframe, timeperiod=5, price='close')
        dataframe['ema_low'] = ta.EMA(dataframe, timeperiod=5, price='low')
        dataframe['adx'] = ta.ADX(dataframe)

        return dataframe

    def populate_buy_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        Based on TA indicators, populates the buy signal for the given dataframe
        :param dataframe: DataFrame
        :return: DataFrame with buy column
        """
        dataframe.loc[
            (
                (dataframe['open'] < dataframe['ema_low']) &
                (qtpylib.crossed_above(dataframe['fastk'], dataframe['fastd'])) &
                # (dataframe['fastk'] > dataframe['fastd']) &
                (dataframe['fastk'] < 30) &
                (dataframe['fastd'] < 30) &
                (dataframe['adx'] > 30)
            ),
            'buy'] = 1

        return dataframe

    def populate_sell_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        Based on TA indicators, populates the sell signal for the given dataframe
        :param dataframe: DataFrame
        :return: DataFrame with buy column
        """
        dataframe.loc[
            (
                (dataframe['open'] >= dataframe['ema_high'])
            ) |
            (
                # (dataframe['fastk'] > 70) &
                # (dataframe['fastd'] > 70)
                (qtpylib.crossed_above(dataframe['fastk'], 70)) |
                (qtpylib.crossed_above(dataframe['fastd'], 70))
            ),
            'sell'] = 1

        return dataframe
