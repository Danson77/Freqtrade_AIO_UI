from datetime import datetime, timedelta, timezone
from freqtrade.persistence import Trade, PairLocks
from freqtrade.strategy import (BooleanParameter, DecimalParameter, IntParameter, RealParameter, stoploss_from_open, merge_informative_pair, CategoricalParameter)
from freqtrade.strategy.interface import IStrategy
from functools import reduce
from logging import FATAL
from pandas import DataFrame, Series
from skopt.space import Dimension, Integer
from technical.util import resample_to_interval, resampled_merge
from typing import Dict, List, Optional, Union
import freqtrade.vendor.qtpylib.indicators as qtpylib
import logging
import math
import numpy as np
import pandas as pd
import pandas_ta as pta
import talib.abstract as ta

############################################################################
# Custom indicators and helper functions
############################################################################
def bollinger_bands(stock_price, window_size, num_of_std):
    rolling_mean = stock_price.rolling(window=window_size).mean()
    rolling_std = stock_price.rolling(window=window_size).std()
    lower_band = rolling_mean - (rolling_std * num_of_std)
    return np.nan_to_num(rolling_mean), np.nan_to_num(lower_band)

def ha_typical_price(bars):
    res = (bars['ha_high'] + bars['ha_low'] + bars['ha_close']) / 3.
    return Series(index=bars.index, data=res)

########################################################################################################################################################
class DS_clucha_5m(IStrategy):
########################################################################################################################################################
# Main
########################################################################################################################################################
    timeframe = '5m'  # The primary timeframe for analysis.

    use_exit_signal = True  # Whether to use the strategy's exit signal.
    exit_profit_only = False  # If True, only sell when in profit.
    exit_profit_offset = 0.01  # Offset added to exit signal (profitable threshold).
    ignore_roi_if_entry_signal = False  # If True, ignore ROI when the buy signal is still present.

    # Custom stoploss configuration.
    use_custom_stoploss = True  # Whether to use a custom stoploss function.

    # Trailing stop configuration.
    trailing_stop = False  # Whether to use a trailing stop.
    trailing_stop_positive = 0.001  # Positive offset for trailing stop.
    trailing_stop_positive_offset = 0.012  # Offset for triggering the trailing stop.
    trailing_only_offset_is_reached = False  # Only trigger trailing stop if the offset is reached.

    # Whether to process only new candles.
    process_only_new_candles = True
    
    # Number of past candles to consider upon startup.
    startup_candle_count = 168

    # Configuration of order types.
    order_types = {
        'entry': 'market',
        'exit': 'market',
        'emergencysell': 'market',
        'forcebuy': "market",
        'forcesell': 'market',
        'stoploss': 'market',
        'stoploss_on_exchange': False,
        'stoploss_on_exchange_interval': 60,
        'stoploss_on_exchange_limit_ratio': 0.99
    }
    
    # Slippage protection to avoid selling at a too low price.
    slippage_protection = {
        'retries': 3,  # Number of retries to avoid slippage.
        'max_slippage': -0.02  # Maximum allowed slippage.
    }
    
    # Plotting configuration for visualizing indicators in backtesting.
    plot_config = {
        'main_plot': {
            'ma_buy': {'color': 'green'},  # Color for the buy moving average.
            'ma_sell': {'color': 'orange'},  # Color for the sell moving average.
        },
    }
    
########################################################################################################################################################
# Hyperopt
########################################################################################################################################################
    buy_params = {
        "clucha_enabled": True,        # (*DD* 4.84%)  Cum Profit % 1083.39
        
########################################################################################################################################################
        "bbdelta_close": 0.01889,
        "bbdelta_tail": 0.72235,
        "close_bblower": 0.0127,
        "closedelta_close": 0.00916,
        "rocr_1h": 0.79492,
    }
    
    # Sell hyperspace params: Define parameters related to selling strategies
    sell_params = {
        # Sell signal params
        'sell_fisher': 0.39075,
        'sell_bbmiddle_close': 0.99754,
        # Custom Stoploos
        "pHSL": -0.35,
        "pPF_1": 0.011,
        "pPF_2": 0.064,
        "pSL_1": 0.011,
        "pSL_2": 0.062,
    }
    
    # ROI table: Defines the desired profit targets at different time intervals
    minimal_roi = {
        "0": 100
    }
    
    # Stoploss: Defines the maximum tolerated loss before the trade is closed
    stoploss = -0.99

########################################################################################################################################################
# Parameters
########################################################################################################################################################
    # buy params
    rocr_1h = RealParameter(0.5, 1.0, default=0.54904, space='buy', optimize=True)
    bbdelta_close = RealParameter(0.0005, 0.02, default=0.01965, space='buy', optimize=True)
    closedelta_close = RealParameter(0.0005, 0.02, default=0.00556, space='buy', optimize=True)
    bbdelta_tail = RealParameter(0.7, 1.0, default=0.95089, space='buy', optimize=True)
    close_bblower = RealParameter(0.0005, 0.02, default=0.00799, space='buy', optimize=True)

    # sell params
    sell_fisher = RealParameter(0.1, 0.5, default=0.38414, space='sell', optimize=True)
    sell_bbmiddle_close = RealParameter(0.97, 1.1, default=1.07634, space='sell', optimize=True)

    # hard stoploss profit
    pHSL = DecimalParameter(-0.500, -0.040, default=-0.08, decimals=3, space='sell', load=True)
    # profit threshold 1, trigger point, SL_1 is used
    pPF_1 = DecimalParameter(0.008, 0.020, default=0.016, decimals=3, space='sell', load=True)
    pSL_1 = DecimalParameter(0.008, 0.020, default=0.011, decimals=3, space='sell', load=True)

    # profit threshold 2, SL_2 is used
    pPF_2 = DecimalParameter(0.040, 0.100, default=0.080, decimals=3, space='sell', load=True)
    pSL_2 = DecimalParameter(0.020, 0.070, default=0.040, decimals=3, space='sell', load=True)

############################################################################################################################################################################
    # Trailing Stoploss Parameters
    is_optimize_stoploss = True
    # Hard Stoploss Profit
    # These parameters help to dynamically adjust the stop loss to lock in profits as the price moves favorably.
    pHSL = DecimalParameter(-0.200, -0.040, default=-0.15, decimals=3, space='sell', optimize=is_optimize_stoploss, load=True)
    # profit threshold 1, trigger point, SL_1 is used
    pPF_1 = DecimalParameter(0.008, 0.020, default=0.016, decimals=3, space='sell', optimize=is_optimize_stoploss, load=True)
    pSL_1 = DecimalParameter(0.008, 0.020, default=0.014, decimals=3, space='sell', optimize=is_optimize_stoploss, load=True)
    # profit threshold 2, SL_2 is used
    pPF_2 = DecimalParameter(0.040, 0.100, default=0.024, decimals=3, space='sell', optimize=is_optimize_stoploss, load=True)
    pSL_2 = DecimalParameter(0.020, 0.070, default=0.022, decimals=3, space='sell', optimize=is_optimize_stoploss, load=True)
    
############################################################################################################################################################################
    # Enabled
    clucha_enabled = BooleanParameter(default=buy_params['clucha_enabled'], space='buy', optimize=True)

########################################################################################################################################################
# Informative Pairs
########################################################################################################################################################
    def informative_pairs(self):
        pairs = self.dp.current_whitelist()
        informative_pairs = [(pair, '1h') for pair in pairs]
        return informative_pairs
        
########################################################################################################################################################
# Indicators
########################################################################################################################################################
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # # Heikin Ashi Candles
        heikinashi = qtpylib.heikinashi(dataframe)
        dataframe['ha_open'] = heikinashi['open']
        dataframe['ha_close'] = heikinashi['close']
        dataframe['ha_high'] = heikinashi['high']
        dataframe['ha_low'] = heikinashi['low']

        # Set Up Bollinger Bands
        mid, lower = bollinger_bands(ha_typical_price(dataframe), window_size=40, num_of_std=2)
        dataframe['lower'] = lower
        dataframe['mid'] = mid

        dataframe['bbdelta'] = (mid - dataframe['lower']).abs()
        dataframe['closedelta'] = (dataframe['ha_close'] - dataframe['ha_close'].shift()).abs()
        dataframe['tail'] = (dataframe['ha_close'] - dataframe['ha_low']).abs()

        dataframe['bb_lowerband'] = dataframe['lower']
        dataframe['bb_middleband'] = dataframe['mid']

        dataframe['ema_fast'] = ta.EMA(dataframe['ha_close'], timeperiod=3)
        dataframe['ema_slow'] = ta.EMA(dataframe['ha_close'], timeperiod=50)
        dataframe['volume_mean_slow'] = dataframe['volume'].rolling(window=30).mean()
        dataframe['rocr'] = ta.ROCR(dataframe['ha_close'], timeperiod=28)

        rsi = ta.RSI(dataframe)
        dataframe["rsi"] = rsi
        rsi = 0.1 * (rsi - 50)
        dataframe["fisher"] = (np.exp(2 * rsi) - 1) / (np.exp(2 * rsi) + 1)

        inf_tf = '1h'

        informative = self.dp.get_pair_dataframe(pair=metadata['pair'], timeframe=inf_tf)

        inf_heikinashi = qtpylib.heikinashi(informative)

        informative['ha_close'] = inf_heikinashi['close']
        informative['rocr'] = ta.ROCR(informative['ha_close'], timeperiod=168)

        dataframe = merge_informative_pair(dataframe, informative, self.timeframe, inf_tf, ffill=True)

        return dataframe
            
########################################################################################################################################################
# Buy Trend
########################################################################################################################################################
    def populate_buy_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Initialize buy and buy_tag columns
        dataframe['buy'] = 0
        dataframe['buy_tag'] = ''
    
        # Define the combined buy condition
        buy_condition = (
            bool(self.clucha_enabled.value) &
            (dataframe['rocr_1h'].gt(self.rocr_1h.value)) &
            ((
                (dataframe['lower'].shift().gt(0)) &
                (dataframe['bbdelta'].gt(dataframe['ha_close'] * self.bbdelta_close.value)) &
                (dataframe['closedelta'].gt(dataframe['ha_close'] * self.closedelta_close.value)) &
                (dataframe['tail'].lt(dataframe['bbdelta'] * self.bbdelta_tail.value)) &
                (dataframe['ha_close'].lt(dataframe['lower'].shift())) &
                (dataframe['ha_close'].le(dataframe['ha_close'].shift()))
            ) | (
                (dataframe['ha_close'] < dataframe['ema_slow']) &
                (dataframe['ha_close'] < self.close_bblower.value * dataframe['bb_lowerband'])
            ))
        )
    
        # Apply the buy condition and tag
        dataframe.loc[buy_condition, 'buy'] = 1
        dataframe.loc[buy_condition, 'buy_tag'] = 'clucHA'
    
        return dataframe
        
########################################################################################################################################################
# Sell Trend
########################################################################################################################################################
    def populate_sell_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe['sell'] = 0
    
        # Define your sell condition
        sell_condition = (
            (dataframe['fisher'] > self.sell_fisher.value) &
            (dataframe['ha_high'].le(dataframe['ha_high'].shift(1))) &
            (dataframe['ha_high'].shift(1).le(dataframe['ha_high'].shift(2))) &
            (dataframe['ha_close'].le(dataframe['ha_close'].shift(1))) &
            (dataframe['ema_fast'] > dataframe['ha_close']) &
            ((dataframe['ha_close'] * self.sell_bbmiddle_close.value) > dataframe['bb_middleband']) &
            (dataframe['volume'] > 0)
        )
    
        # Apply sell condition
        dataframe.loc[sell_condition, 'sell'] = 1
    
        return dataframe
        
########################################################################################################################################################
# Confirm Trade Exit
########################################################################################################################################################
    def confirm_trade_exit(self, pair: str, trade: Trade, order_type: str, amount: float, rate: float, time_in_force: str, sell_reason: str, current_time: datetime, **kwargs) -> bool:
    
        # Update sell reason with buy tag, if available
        if trade and trade.sell_reason:
            trade.sell_reason = sell_reason + "_" + trade.buy_tag
    
        # Retrieve the last candle data
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        last_candle = dataframe.iloc[-1]
    
        # Slippage protection logic
        try:
            state = self.slippage_protection['__pair_retries']
        except KeyError:
            state = self.slippage_protection['__pair_retries'] = {}
    
        slippage = (rate / last_candle['close']) - 1
        if slippage < self.slippage_protection['max_slippage']:
            pair_retries = state.get(pair, 0)
            if pair_retries < self.slippage_protection['retries']:
                state[pair] = pair_retries + 1
                return False
    
        state[pair] = 0
    
        return True
        
########################################################################################################################################################
# Trade Protections
########################################################################################################################################################
    @property
    def protections(self):
        return [
            {
                "method": "CooldownPeriod",
                "stop_duration_candles": 5
            },
            {
                "method": "MaxDrawdown",
                "lookback_period_candles": 48,
                "trade_limit": 20,
                "stop_duration_candles": 4,
                "max_allowed_drawdown": 0.2
            },
            {
                "method": "StoplossGuard",
                "lookback_period_candles": 24,
                "trade_limit": 4,
                "stop_duration_candles": 2,
                "only_per_pair": False
            },
            {
                "method": "LowProfitPairs",
                "lookback_period_candles": 6,
                "trade_limit": 2,
                "stop_duration_candles": 60,
                "required_profit": 0.02
            },
            {
                "method": "LowProfitPairs",
                "lookback_period_candles": 24,
                "trade_limit": 4,
                "stop_duration_candles": 2,
                "required_profit": 0.01
            }
        ]
        
########################################################################################################################################################
# Custom Trailing Stoploss come from BB_RPB_TSL
########################################################################################################################################################
    def custom_stoploss(self, pair: str, trade: 'Trade', current_time: datetime, current_rate: float, current_profit: float, **kwargs) -> float:

        # hard stoploss profit
        HSL = self.pHSL.value
        PF_1 = self.pPF_1.value
        SL_1 = self.pSL_1.value
        PF_2 = self.pPF_2.value
        SL_2 = self.pSL_2.value

        # For profits between PF_1 and PF_2 the stoploss (sl_profit) used is linearly interpolated
        # between the values of SL_1 and SL_2. For all profits above PL_2 the sl_profit value
        # rises linearly with current profit, for profits below PF_1 the hard stoploss profit is used.

        if current_profit > PF_2:
            sl_profit = SL_2 + (current_profit - PF_2)
        elif current_profit > PF_1:
            sl_profit = SL_1 + ((current_profit - PF_1) * (SL_2 - SL_1) / (PF_2 - PF_1))
        else:
            sl_profit = HSL

        # Only for hyperopt invalid return
        if sl_profit >= current_profit:
            return -0.99

        return stoploss_from_open(sl_profit, current_profit)