# --------------------------------
import logging
import pandas as pd
import numpy as np
import time
import freqtrade.vendor.qtpylib.indicators as qtpylib
import pandas_ta as pta
import talib.abstract as ta
from datetime import datetime, timedelta, timezone
from functools import reduce
from typing import List
# --- Do not remove these libs ---
from freqtrade.strategy.interface import IStrategy
from typing import Dict, List
from pandas import DataFrame, Series
from freqtrade.persistence import Trade, PairLocks
from freqtrade.strategy import (BooleanParameter, DecimalParameter, RealParameter, IntParameter, stoploss_from_open, merge_informative_pair)
from skopt.space import Dimension, Integer

logger = logging.getLogger(__name__)
########################################################################################################################################################
# Custom indicators and helper functions
########################################################################################################################################################
def bollinger_bands(stock_price, window_size, num_of_std):
    rolling_mean = stock_price.rolling(window=window_size).mean()
    rolling_std = stock_price.rolling(window=window_size).std()
    lower_band = rolling_mean - (rolling_std * num_of_std)
    return np.nan_to_num(rolling_mean), np.nan_to_num(lower_band)
########################################################################################################################################################
# ha_typical_price
########################################################################################################################################################
def ha_typical_price(bars):
    res = (bars['ha_high'] + bars['ha_low'] + bars['ha_close']) / 3.
    return Series(index=bars.index, data=res)
########################################################################################################################################################
# Ewo
########################################################################################################################################################
def EWO(dataframe, ema_length=5, ema2_length=35):
    df = dataframe.copy()
    ema1 = ta.EMA(df, timeperiod=ema_length)
    ema2 = ta.EMA(df, timeperiod=ema2_length)
    emadif = (ema1 - ema2) / df['low'] * 100
    return emadif
########################################################################################################################################################
# pct_change
########################################################################################################################################################   
def pct_change(a, b):
    return (b - a) / a
########################################################################################################################################################
class ClucHAnix_BB_RPB_MOD_CTT_1m(IStrategy):
########################################################################################################################################################
# Hyperopt
########################################################################################################################################################
    buy_params = {
        "lambo2_enabled": True,
        "clucha_enabled": True,
        "cofi_enabled": True,
        "ewo_low_enabled": True,
        "ewo_1_enabled": True,
        #
        "local_uptrend_enabled": True,
        "nfi32_enabled": True,
        "lambo1_enabled": True,
        # Safe
        "antipump_threshold": 0.133,
        "buy_btc_safe_1d": -0.311,
        #lambo 1
        "lambo1_ema_14_factor": 1.054,
        "lambo1_rsi_14_limit": 26,
        "lambo1_rsi_4_limit": 18,
        # lambo 2
        "lambo2_ema_14_factor": 0.981,
        "lambo2_rsi_14_limit": 39,
        "lambo2_rsi_4_limit": 44,
        # local trend
        "local_trend_bb_factor": 0.823,
        "local_trend_closedelta": 19.253,
        "local_trend_ema_diff": 0.125,
        #nfi32
        "nfi32_cti_limit": -1.09639,
        "nfi32_rsi_14": 15,
        "nfi32_rsi_4": 49,
        "nfi32_sma_factor": 0.93391,
        # ewo 1
        "ewo_1_rsi_14": 45,
        "ewo_1_rsi_4": 7,
        "ewo_high": 5.249,
        # ewo_1 & ewo_low & is safe
        "ewo_candles_buy": 13,
        "ewo_candles_sell": 19,
        # Ewo 1 & Low
        "ewo_high_offset": 1.04116,
        "ewo_low_offset": 0.97463,
        # Ewo Low
        "ewo_low": -11.424,
        "ewo_low_rsi_4": 35,
        # cofi
        "cofi_adx": 8,
        "cofi_ema": 0.639,
        "cofi_ewo_high": 5.6,
        "cofi_fastd": 40,
        "cofi_fastk": 13,
        # clucha
        "clucha_bbdelta_close": 0.04796,
        "clucha_bbdelta_tail": 0.93112,
        "clucha_close_bblower": 0.01645,
        "clucha_closedelta_close": 0.00931,
        "clucha_rocr_1h": 0.41663,
    }
    sell_params = {
        # custom stoploss params, come from BB_RPB_TSL
        "pHSL": -0.32,
        "pPF_1": 0.02,
        "pPF_2": 0.047,
        "pSL_1": 0.02,
        "pSL_2": 0.046,
        # Sell 
        'sell_fisher': 0.38414, 
        'sell_bbmiddle_close': 1.07634,
    }
    minimal_roi = {
        "7200": 0.01, # After 5 days, take 1% profit
        "4320": 0.03, # After 3 days, take 2% profit
        "2880": 0.04, # After 2 days, take 3% profit
        "1440": 0.05, # After 1 day, take 4% profit
        "480":  0.08, # After 8 hours, take 5% profit
        "120":  0.10, # After 2 hours, take 8% profit
        "15":  0.15, # After 15 minutes, take 10% profit
        "0":   0.20 
        #"0": 0.05,
        #"15": 0.04,
        #"51": 0.03,
        #"81": 0.02,
        #"112": 0.01,
        #"154": 0.0001,
        #"240": -10
    }
    stoploss = -0.99
    trailing_stop = False
    trailing_stop_positive = 0.01
    trailing_stop_positive_offset = 0.0135
    trailing_only_offset_is_reached = False
    use_custom_stoploss = True
########################################################################################################################################################
# Main
    can_short = False
########################################################################################################################################################
    timeframe = '1m'  # The primary timeframe for analysis.
    inf_tf = '1h'
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
# Parameters
########################################################################################################################################################
    # BTC Safe
    is_optimize_btc = True
    buy_btc_safe_1d = DecimalParameter(-0.5, -0.015, default=buy_params['buy_btc_safe_1d'], optimize=is_optimize_btc)
    antipump_threshold = DecimalParameter(0, 0.4, default=buy_params['antipump_threshold'], space='buy', optimize=is_optimize_btc)
    # lambo1
    is_optimize_lambo1 = True
    lambo1_ema_14_factor = DecimalParameter(0.8, 1.2, decimals=3,  default=buy_params['lambo1_ema_14_factor'], space='buy', optimize=is_optimize_lambo1)
    lambo1_rsi_4_limit = IntParameter(5, 60, default=buy_params['lambo1_rsi_4_limit'], space='buy', optimize=is_optimize_lambo1)
    lambo1_rsi_14_limit = IntParameter(5, 60, default=buy_params['lambo1_rsi_14_limit'], space='buy', optimize=is_optimize_lambo1)
    # lambo2
    is_optimize_lambo2 = True
    lambo2_ema_14_factor = DecimalParameter(0.8, 1.2, decimals=3,  default=buy_params['lambo2_ema_14_factor'], space='buy', optimize=is_optimize_lambo2)
    lambo2_rsi_4_limit = IntParameter(5, 60, default=buy_params['lambo2_rsi_4_limit'], space='buy', optimize=is_optimize_lambo2)
    lambo2_rsi_14_limit = IntParameter(5, 60, default=buy_params['lambo2_rsi_14_limit'], space='buy', optimize=is_optimize_lambo2)
    # local_uptrend
    is_optimize_local = True
    local_trend_ema_diff = DecimalParameter(0, 0.2, default=buy_params['local_trend_ema_diff'], space='buy', optimize=is_optimize_local)
    local_trend_bb_factor = DecimalParameter(0.8, 1.2, default=buy_params['local_trend_bb_factor'], space='buy', optimize=is_optimize_local)
    local_trend_closedelta = DecimalParameter(5.0, 30.0, default=buy_params['local_trend_closedelta'], space='buy', optimize=is_optimize_local)
    # nfi32
    is_optimize_nfi32 = True
    nfi32_rsi_4 = IntParameter(1, 100, default=buy_params['nfi32_rsi_4'], space='buy', optimize=is_optimize_nfi32)
    nfi32_rsi_14 = IntParameter(1, 100, default=buy_params['nfi32_rsi_4'], space='buy', optimize=is_optimize_nfi32)
    nfi32_sma_factor = DecimalParameter(0.7, 1.2, default=buy_params['nfi32_sma_factor'], decimals=5, space='buy', optimize=is_optimize_nfi32)
    nfi32_cti_limit = DecimalParameter(-1.2, 0, default=buy_params['nfi32_cti_limit'], decimals=5, space='buy', optimize=is_optimize_nfi32)
    # Ewo 1
    is_optimize_ewo1 = True
    ewo_1_rsi_14 = IntParameter(10, 100, default=buy_params['ewo_1_rsi_14'], space='buy', optimize=is_optimize_ewo1)
    ewo_1_rsi_4 = IntParameter(1, 50, default=buy_params['ewo_1_rsi_4'], space='buy', optimize=is_optimize_ewo1)
    ewo_high = DecimalParameter(2.0, 15.0, default=buy_params['ewo_high'], space='buy', optimize=is_optimize_ewo1)
    # ewo_1 and ewo_low and is safe
    is_optimize_candles = True
    ewo_candles_buy = IntParameter(2, 30, default=buy_params['ewo_candles_buy'], space='buy', optimize=is_optimize_candles)
    ewo_candles_sell = IntParameter(2, 35, default=buy_params['ewo_candles_sell'], space='buy', optimize=is_optimize_candles)
    # Ewo 1 & Low
    is_optimize_1low = True
    ewo_high_offset = DecimalParameter(0.75, 1.5, default=buy_params['ewo_high_offset'], decimals=5, space='buy', optimize=is_optimize_1low)
    ewo_low_offset = DecimalParameter(0.7, 1.2, default=buy_params['ewo_low_offset'], decimals=5, space='buy', optimize=is_optimize_1low)
    # Ewo Low
    is_optimize_low = True
    ewo_low = DecimalParameter(-20.0, -8.0, default=buy_params['ewo_low'], space='buy', optimize=is_optimize_low)
    ewo_low_rsi_4 = IntParameter(1, 50, default=buy_params['ewo_low_rsi_4'], space='buy', optimize=is_optimize_low)
    # cofi
    is_optimize_cofi = True
    cofi_ema = DecimalParameter(0.6, 1.4, default=buy_params['cofi_ema'] , space='buy', optimize=is_optimize_cofi)
    cofi_fastk = IntParameter(1, 100, default=buy_params['cofi_fastk'], space='buy', optimize=is_optimize_cofi)
    cofi_fastd = IntParameter(1, 100, default=buy_params['cofi_fastd'], space='buy', optimize=is_optimize_cofi)
    cofi_adx = IntParameter(1, 100, default=buy_params['cofi_adx'], space='buy', optimize=is_optimize_cofi)
    cofi_ewo_high = DecimalParameter(1.0, 15.0, default=buy_params['cofi_ewo_high'], space='buy', optimize=is_optimize_cofi)
    # ClucHA
    is_optimize_ClucHA = True
    clucha_bbdelta_close = DecimalParameter(0.01,0.05, default=buy_params['clucha_bbdelta_close'], decimals=5, space='buy', optimize=is_optimize_ClucHA)
    clucha_bbdelta_tail = DecimalParameter(0.7, 1.2, default=buy_params['clucha_bbdelta_tail'], decimals=5, space='buy', optimize=is_optimize_ClucHA)
    clucha_close_bblower = DecimalParameter(0.001, 0.05, default=buy_params['clucha_close_bblower'], decimals=5, space='buy', optimize=is_optimize_ClucHA)
    clucha_closedelta_close = DecimalParameter(0.001, 0.05, default=buy_params['clucha_closedelta_close'], decimals=5, space='buy', optimize=is_optimize_ClucHA)
    clucha_rocr_1h = DecimalParameter(0.1, 1.0, default=buy_params['clucha_rocr_1h'], decimals=5, space='buy', optimize=is_optimize_ClucHA)
    # Sell
    is_optimize_exit = True
    sell_fisher = RealParameter(0.1, 0.5, default=0.38414, space='sell', optimize=is_optimize_exit)
    sell_bbmiddle_close = RealParameter(0.97, 1.1, default=1.07634, space='sell', optimize=is_optimize_exit)
############################################################################################################################################################################
    # Custom Stoploss
    is_optimize_stoploss = True
    # Hard stoploss profit
    pHSL = DecimalParameter(-0.500, -0.040, default=-0.08, decimals=3, space='sell', optimize=is_optimize_stoploss, load=True)
    # profit threshold 1, trigger point, SL_1 is used
    pPF_1 = DecimalParameter(0.008, 0.020, default=0.016, decimals=3, space='sell', optimize=is_optimize_stoploss, load=True)
    pSL_1 = DecimalParameter(0.008, 0.020, default=0.011, decimals=3, space='sell', optimize=is_optimize_stoploss, load=True)
    # profit threshold 2, SL_2 is used
    pPF_2 = DecimalParameter(0.040, 0.100, default=0.080, decimals=3, space='sell',optimize=is_optimize_stoploss, load=True)
    pSL_2 = DecimalParameter(0.020, 0.070, default=0.040, decimals=3, space='sell', optimize=is_optimize_stoploss,load=True)
############################################################################################################################################################################
    # Enables
    is_optimize_enabled = True
    ewo_1_enabled = BooleanParameter(default=buy_params['ewo_1_enabled'], space='buy', optimize=is_optimize_enabled)
    ewo_low_enabled = BooleanParameter(default=buy_params['ewo_low_enabled'], space='buy', optimize=is_optimize_enabled)
    cofi_enabled = BooleanParameter(default=buy_params['cofi_enabled'], space='buy', optimize=is_optimize_enabled)
    lambo1_enabled = BooleanParameter(default=buy_params['lambo1_enabled'], space='buy', optimize=is_optimize_enabled)
    lambo2_enabled = BooleanParameter(default=buy_params['lambo2_enabled'], space='buy', optimize=is_optimize_enabled)
    local_uptrend_enabled = BooleanParameter(default=buy_params['local_uptrend_enabled'], space='buy', optimize=is_optimize_enabled)
    nfi32_enabled = BooleanParameter(default=buy_params['nfi32_enabled'], space='buy', optimize=is_optimize_enabled)
    clucha_enabled = BooleanParameter(default=buy_params['clucha_enabled'], space='buy', optimize=is_optimize_enabled)
########################################################################################################################################################
# Informative
########################################################################################################################################################
    def informative_pairs(self):
        pairs = self.dp.current_whitelist()
        informative_pairs = [(pair, '1h') for pair in pairs]
        informative_pairs += [("BTC/USDT", "1m")]
        informative_pairs += [("BTC/USDT", "1d")]

        return informative_pairs
########################################################################################################################################################
# Indicators
########################################################################################################################################################
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Heikin Ashi Candles
        heikinashi = qtpylib.heikinashi(dataframe)
        dataframe['ha_open'] = heikinashi['open']
        dataframe['ha_close'] = heikinashi['close']
        dataframe['ha_high'] = heikinashi['high']
        dataframe['ha_low'] = heikinashi['low']
        # EMA
        dataframe['ema_8'] = ta.EMA(dataframe, timeperiod=8)
        dataframe['ema_14'] = ta.EMA(dataframe, timeperiod=14)
        dataframe['ema_26'] = ta.EMA(dataframe, timeperiod=26)
        dataframe['sma_15'] = ta.SMA(dataframe, timeperiod=15)
        dataframe['rsi_4'] = ta.RSI(dataframe, timeperiod=4)
        dataframe['rsi_14'] = ta.RSI(dataframe, timeperiod=14)
        dataframe['rsi_20'] = ta.RSI(dataframe, timeperiod=20)
        # Pump strength
        dataframe['dema_30'] = ta.DEMA(dataframe, period=30)
        dataframe['dema_200'] = ta.DEMA(dataframe, period=200)
        dataframe['pump_strength'] = (dataframe['dema_30'] - dataframe['dema_200']) / dataframe['dema_30']
        # CTI
        dataframe['cti'] = pta.cti(dataframe["close"], length=20)
        # Avg Volume
        dataframe['avg_volume'] = ta.SMA(dataframe['volume'], timeperiod=200)
        dataframe['vroc_bool'] = (dataframe['avg_volume'] > dataframe['avg_volume'].shift(1)) & (dataframe['close'] > dataframe['close'].shift(1))
        dataframe['vroc'] = np.where(dataframe['vroc_bool'] == True, ((dataframe['avg_volume'] - dataframe['avg_volume'].shift(1)) * (100 / dataframe['avg_volume'].shift(1))), 0)
        #dataframe['vroc'] = (dataframe['avg_volume'] - dataframe['avg_volume'].shift(1)) * (100 / dataframe['avg_volume'].shift(1))
        #if (dataframe['vroc'] > dataframe['historicMax'].rolling(200).max()):
        #    dataframe['historicMax'] = dataframe['vroc']
        #dataframe.loc[0,'historicMax'] = 10
        #dataframe['historicMax'] = np.where(dataframe['vroc'] > dataframe['historicMax'].shift(1), dataframe['vroc'].rolling(200).max(), dataframe['historicMax'].shift(1).rolling(200).max())
        dataframe['vroc_max'] = dataframe['vroc'].rolling(200).max()
        dataframe['historicMax'] = np.where(dataframe['vroc_max'] > 10, dataframe['vroc_max'], 10)
        dataframe['historicMax'] = dataframe['historicMax'].rolling(200).max()
        dataframe['vroc_normalized'] = 100 * dataframe['vroc'] / dataframe['historicMax']
        dataframe['recent_pump'] = ((dataframe['vroc_normalized'].rolling(96).max() > 90) | (dataframe['vroc_normalized'].rolling(48).max() > 10) | (dataframe['vroc_normalized'].rolling(24).max() > 5)) & (dataframe['vroc_bool'] == True)
        # Cofi
        stoch_fast = ta.STOCHF(dataframe, 5, 3, 0, 3, 0)
        dataframe['fastd'] = stoch_fast['fastd']
        dataframe['fastk'] = stoch_fast['fastk']
        dataframe['adx'] = ta.ADX(dataframe)
        # Set Up Bollinger Bands
        mid, lower = bollinger_bands(ha_typical_price(dataframe), window_size=40, num_of_std=2)
        dataframe['lower'] = lower
        dataframe['mid'] = mid
        # Boiling bands
        bollinger2 = qtpylib.bollinger_bands(qtpylib.typical_price(dataframe), window=20, stds=2)
        dataframe['bb_lowerband2'] = bollinger2['lower']
        dataframe['bb_middleband2'] = bollinger2['mid']
        dataframe['bb_upperband2'] = bollinger2['upper']
        dataframe['closedelta'] = (dataframe['close'] - dataframe['close'].shift()).abs()
        # # ClucHA
        dataframe['bbdelta'] = (mid - dataframe['lower']).abs()
        dataframe['ha_closedelta'] = (dataframe['ha_close'] - dataframe['ha_close'].shift()).abs()
        dataframe['tail'] = (dataframe['ha_close'] - dataframe['ha_low']).abs()
        dataframe['bb_lowerband'] = dataframe['lower']
        dataframe['bb_middleband'] = dataframe['mid']
        # EMA
        dataframe['ema_fast'] = ta.EMA(dataframe['ha_close'], timeperiod=3)
        dataframe['ema_slow'] = ta.EMA(dataframe['ha_close'], timeperiod=50)
        dataframe['rocr'] = ta.ROCR(dataframe['ha_close'], timeperiod=28)
        # Elliot
        dataframe['EWO'] = EWO(dataframe, 50, 200)
        # RSI
        rsi = ta.RSI(dataframe)
        dataframe["rsi"] = rsi
        rsi = 0.1 * (rsi - 50)
        dataframe["fisher"] = (np.exp(2 * rsi) - 1) / (np.exp(2 * rsi) + 1)
        # Informative
        informative = self.dp.get_pair_dataframe(pair=metadata['pair'], timeframe=self.inf_tf)
        inf_heikinashi = qtpylib.heikinashi(informative)
        informative['ha_close'] = inf_heikinashi['close']
        informative['rocr'] = ta.ROCR(informative['ha_close'], timeperiod=168)
        dataframe = merge_informative_pair(dataframe, informative, self.timeframe, self.inf_tf, ffill=True)
        ### BTC protection
        dataframe['btc_1m']= self.dp.get_pair_dataframe('BTC/USDT', timeframe='1m')['close']
        btc_1d = self.dp.get_pair_dataframe('BTC/USDT', timeframe='1d')[['date', 'close']].rename(columns={"close": "btc"}).shift(1)
        dataframe = merge_informative_pair(dataframe, btc_1d, '1m', '1d', ffill=True)

        return dataframe
########################################################################################################################################################
# Entry Signal
########################################################################################################################################################
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        conditions = []
        dataframe.loc[:, 'enter_tag'] = ''
    
        dataframe[f'ma_buy_{self.ewo_candles_buy.value}'] = ta.EMA(dataframe, timeperiod=int(self.ewo_candles_buy.value))
        dataframe[f'ma_sell_{self.ewo_candles_sell.value}'] = ta.EMA(dataframe, timeperiod=int(self.ewo_candles_sell.value))
    
        is_btc_safe = (
            (pct_change(dataframe['btc_1d'], dataframe['btc_1m']).fillna(0) > self.buy_btc_safe_1d.value) &
            (dataframe['volume'] > 0)           # Make sure Volume is not 0
        )
    
        is_pump_safe = (
            (dataframe['pump_strength'] < self.antipump_threshold.value)
        )
    
        lambo2 = (
            bool(self.lambo2_enabled.value) &
            (dataframe['close'] < (dataframe['ema_14'] * self.lambo2_ema_14_factor.value)) &
            (dataframe['rsi_4'] < int(self.lambo2_rsi_4_limit.value)) &
            (dataframe['rsi_14'] < int(self.lambo2_rsi_14_limit.value)) &
            (dataframe['cti'] < -0.5) &
            (dataframe['recent_pump'] == False)
        )
        dataframe.loc[lambo2, 'enter_tag'] += 'lambo2_'
        conditions.append(lambo2)

        clucHA = (
            bool(self.clucha_enabled.value) &
            (dataframe['rocr_1h'].gt(self.clucha_rocr_1h.value)) &
            ((
                (dataframe['lower'].shift().gt(0)) &
                (dataframe['bbdelta'].gt(dataframe['ha_close'] * self.clucha_bbdelta_close.value)) &
                (dataframe['ha_closedelta'].gt(dataframe['ha_close'] * self.clucha_closedelta_close.value)) &
                (dataframe['tail'].lt(dataframe['bbdelta'] * self.clucha_bbdelta_tail.value)) &
                (dataframe['ha_close'].lt(dataframe['lower'].shift())) &
                (dataframe['ha_close'].le(dataframe['ha_close'].shift())) &
                (dataframe['recent_pump'] == False)
            ) |
            (
                (dataframe['ha_close'] < dataframe['ema_slow']) &
                (dataframe['ha_close'] < self.clucha_close_bblower.value * dataframe['bb_lowerband']) &
                (dataframe['recent_pump'] == False)
            ))
        )
        dataframe.loc[clucHA, 'enter_tag'] += 'clucHA_'
        conditions.append(clucHA)

        lambo1 = (
            bool(self.lambo1_enabled.value) &
            (dataframe['close'] < (dataframe['ema_14'] * self.lambo1_ema_14_factor.value)) &
            (dataframe['rsi_4'] < int(self.lambo1_rsi_4_limit.value)) &
            (dataframe['rsi_14'] < int(self.lambo1_rsi_14_limit.value)) &
            (dataframe['cti'] < -0.5) &
            (dataframe['recent_pump'] == False)
        )
        dataframe.loc[lambo1, 'enter_tag'] += 'lambo1_'
        conditions.append(lambo1)

        ewo_1 = (
            bool(self.ewo_1_enabled.value) &
            (dataframe['rsi_4'] < self.ewo_1_rsi_4.value) &
            (dataframe['close'] < (dataframe[f'ma_buy_{self.ewo_candles_buy.value}'] * self.ewo_low_offset.value)) &
            (dataframe['EWO'] > self.ewo_high.value) &
            (dataframe['rsi_14'] < self.ewo_1_rsi_14.value) &
            (dataframe['close'] < (dataframe[f'ma_sell_{self.ewo_candles_sell.value}'] * self.ewo_high_offset.value)) &
            (dataframe['recent_pump'] == False)
        )
        dataframe.loc[ewo_1, 'enter_tag'] += 'ewo1_'
        conditions.append(ewo_1)

        ewo_low = (
            bool(self.ewo_low_enabled.value) &
            (dataframe['rsi_4'] <  self.ewo_low_rsi_4.value) &
            (dataframe['close'] < (dataframe[f'ma_buy_{self.ewo_candles_buy.value}'] * self.ewo_low_offset.value)) &
            (dataframe['EWO'] < self.ewo_low.value) &
            (dataframe['close'] < (dataframe[f'ma_sell_{self.ewo_candles_sell.value}'] * self.ewo_high_offset.value)) &
            (dataframe['recent_pump'] == False)
        )
        dataframe.loc[ewo_low, 'enter_tag'] += 'ewo_low_'
        conditions.append(ewo_low)

        local_uptrend = (
            bool(self.local_uptrend_enabled.value) &
            (dataframe['ema_26'] > dataframe['ema_14']) &
            (dataframe['ema_26'] - dataframe['ema_14'] > dataframe['open'] * self.local_trend_ema_diff.value) &
            (dataframe['ema_26'].shift() - dataframe['ema_14'].shift() > dataframe['open'] / 100) &
            (dataframe['close'] < dataframe['bb_lowerband2'] * self.local_trend_bb_factor.value) &
            (dataframe['closedelta'] > dataframe['close'] * self.local_trend_closedelta.value / 1000 ) &
            (dataframe['recent_pump'] == False)
        )
        dataframe.loc[local_uptrend, 'enter_tag'] += 'local_uptrend_'
        conditions.append(local_uptrend)

        # Not making buys

        cofi = (
            bool(self.cofi_enabled.value) &
            (dataframe['open'] < dataframe['ema_8'] * self.cofi_ema.value) &
            (qtpylib.crossed_above(dataframe['fastk'], dataframe['fastd'])) &
            (dataframe['fastk'] < self.cofi_fastk.value) &
            (dataframe['fastd'] < self.cofi_fastd.value) &
            (dataframe['adx'] > self.cofi_adx.value) &
            (dataframe['EWO'] > self.cofi_ewo_high.value) &
            (dataframe['recent_pump'] == False)
        )
        dataframe.loc[cofi, 'enter_tag'] += 'cofi_'
        conditions.append(cofi)

        nfi_32 = (
            bool(self.nfi32_enabled.value) &
            (dataframe['rsi_20'] < dataframe['rsi_20'].shift(1)) &
            (dataframe['rsi_4'] < self.nfi32_rsi_4.value) &
            (dataframe['rsi_14'] > self.nfi32_rsi_14.value) &
            (dataframe['close'] < dataframe['sma_15'] * self.nfi32_sma_factor.value) &
            (dataframe['cti'] < self.nfi32_cti_limit.value) &
            (dataframe['recent_pump'] == False)
        )
        dataframe.loc[nfi_32, 'enter_tag'] += 'nfi_32_'
        conditions.append(nfi_32)

        dataframe.loc[is_btc_safe & is_pump_safe & reduce(lambda x, y: x | y, conditions), 'enter_long'] = 1
    
        return dataframe
########################################################################################################################################################
# Sell
########################################################################################################################################################
    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Initialize 'exit_long' to 0 for all rows
        dataframe['exit_long'] = 0
        dataframe['exit_tag'] = 'no_exit'  # Default tag

        # Define your sell conditions
        sell_conditions = (
            (dataframe['fisher'] > self.sell_fisher.value) &
            (dataframe['ha_high'].le(dataframe['ha_high'].shift(1))) &
            (dataframe['ha_high'].shift(1).le(dataframe['ha_high'].shift(2))) &
            (dataframe['ha_close'].le(dataframe['ha_close'].shift(1))) &
            (dataframe['ema_fast'] > dataframe['ha_close']) &
            ((dataframe['ha_close'] * self.sell_bbmiddle_close.value) > dataframe['bb_middleband']) &
            (dataframe['volume'] > 0)
        )
        # Apply the condition to set 'exit_long' and tag the exit
        dataframe.loc[sell_conditions, 'exit_long'] = 1
        dataframe.loc[sell_conditions, 'exit_tag'] = 'fisher_ema_bearish'
    
        return dataframe
########################################################################################################################################################
# Custom Stoploss
########################################################################################################################################################
    def custom_stoploss(self, pair: str, trade: 'Trade', current_time: datetime, current_rate: float, current_profit: float, **kwargs) -> float:
        # hard stoploss profit
        HSL = self.pHSL.value
        PF_1 = self.pPF_1.value
        SL_1 = self.pSL_1.value
        PF_2 = self.pPF_2.value
        SL_2 = self.pSL_2.value
        
        # For profits between PF_1 and PF_2 the stoploss (sl_profit) used is linearly interpolated
        # between the values of SL_1 and SL_2. For all profits above PF_2 the sl_profit value
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
########################################################################################################################################################
# confirm exit
########################################################################################################################################################
    def confirm_trade_exit(self, pair: str, trade: Trade, order_type: str, amount: float, rate: float, time_in_force: str, exit_reason: str, current_time: datetime, **kwargs) -> bool:

        trade.exit_reason = exit_reason + "_" + trade.enter_tag

        return True
################################################################################################################################################################################################################################################################################################################
################################################################################################################################################################################################################################################################################################################
################################################################################################################################################################################################################################################################################################################
# Aditionals
################################################################################################################################################################################################################################################################################################################
########################################################################################################################################################
class ClucHAnix_BB_RPB_MOD_CTT_1m_TrailingBuy(ClucHAnix_BB_RPB_MOD_CTT_1m):
########################################################################################################################################################
    # Original idea by @MukavaValkku, code by @tirail and @stash86
    #
    # This class is designed to inherit from yours and starts trailing buy with your buy signals
    # Trailing buy starts at any buy signal and will move to next candles if the trailing still active
    # Trailing buy stops  with BUY if : price decreases and rises again more than trailing_buy_offset
    # Trailing buy stops with NO BUY : current price is > initial price * (1 +  trailing_buy_max) OR custom_sell tag
    # IT IS NOT COMPATIBLE WITH BACKTEST/HYPEROPT
    #
    process_only_new_candles = True
    custom_info_trail_buy = dict()
    # Trailing buy parameters
    trailing_buy_order_enabled = True
    trailing_expire_seconds = 1800
    # If the current candle goes above min_uptrend_trailing_profit % before trailing_expire_seconds_uptrend seconds, buy the coin
    trailing_buy_uptrend_enabled = False
    trailing_expire_seconds_uptrend = 90
    min_uptrend_trailing_profit = 0.02
    # Debugs
    debug_mode = True
    trailing_buy_max_stop = 0.02  # stop trailing buy if current_price > starting_price * (1+trailing_buy_max_stop)
    trailing_buy_max_buy = 0.000  # buy if price between uplimit (=min of serie (current_price * (1 + trailing_buy_offset())) and (start_price * 1+trailing_buy_max_buy))
    # Markets
    init_trailing_dict = {
        'trailing_buy_order_started': False,
        'trailing_buy_order_uplimit': 0,
        'start_trailing_price': 0,
        'enter_tag': None,
        'start_trailing_time': None,
        'offset': 0,
        'allow_trailing': False,
    }
########################################################################################################################################################
# Trailing Buy returns trailing buy info for pair (init if necessary)
########################################################################################################################################################   
    def trailing_buy(self, pair, reinit=False):
        if pair not in self.custom_info_trail_buy:
            self.custom_info_trail_buy[pair] = {}
        if reinit or 'trailing_buy' not in self.custom_info_trail_buy[pair]:
            self.custom_info_trail_buy[pair]['trailing_buy'] = self.init_trailing_dict.copy()
        return self.custom_info_trail_buy[pair]['trailing_buy']
########################################################################################################################################################
# Trailing Buy Info
########################################################################################################################################################        
    def trailing_buy_info(self, pair: str, current_price: float):
        if not self.debug_mode:
            return
        trailing_buy = self.trailing_buy(pair)
        duration = 0
        try:
            duration = (datetime.now(timezone.utc) - trailing_buy['start_trailing_time'])
        except TypeError:
            pass
        finally:
            logger.info(
                f"pair: {pair} : "
                f"start: {trailing_buy['start_trailing_price']:.4f}, "
                f"duration: {duration}, "
                f"current: {current_price:.4f}, "
                f"uplimit: {trailing_buy['trailing_buy_order_uplimit']:.4f}, "
                f"profit: {self.current_trailing_profit_ratio(pair, current_price)*100:.2f}%, "
                f"offset: {trailing_buy['offset']}")
########################################################################################################################################################
# current_trailing_profit_ratio
########################################################################################################################################################
    def current_trailing_profit_ratio(self, pair: str, current_price: float) -> float:
        trailing_buy = self.trailing_buy(pair)
        return (trailing_buy['start_trailing_price'] - current_price) / trailing_buy['start_trailing_price'] if trailing_buy['trailing_buy_order_started'] else 0
########################################################################################################################################################
# Trailing Buy Offset
########################################################################################################################################################
    def trailing_buy_offset(self, dataframe, pair: str, current_price: float):
        # return rebound limit before a buy in % of initial price, function of current price
        # return None to stop trailing buy (will start again at next buy signal)
        # return 'forcebuy' to force immediate buy
        # (example with 0.5%. initial price : 100 (uplimit is 100.5), 2nd price : 99 (no buy, uplimit updated to 99.5), 3price 98 (no buy uplimit updated to 98.5), 4th price 99 -> BUY
        current_trailing_profit_ratio = self.current_trailing_profit_ratio(pair, current_price)
        default_offset = 0.005

        trailing_buy = self.trailing_buy(pair)
        if not trailing_buy['trailing_buy_order_started']:
            return default_offset

        last_candle = dataframe.iloc[-1]
        trailing_duration = (datetime.now(timezone.utc) - trailing_buy['start_trailing_time'])

        if trailing_duration.total_seconds() > self.trailing_expire_seconds:
            return 'forcebuy' if current_trailing_profit_ratio > 0 and last_candle['enter_long'] == 1 else None
        elif self.trailing_buy_uptrend_enabled and trailing_duration.total_seconds() < self.trailing_expire_seconds_uptrend and current_trailing_profit_ratio < (-1 * self.min_uptrend_trailing_profit):
            return 'forcebuy'

        if current_trailing_profit_ratio < 0:
            return default_offset

        trailing_buy_offset = {
            0.06: 0.02,
            0.03: 0.01,
            0: default_offset,
        }

        for key in trailing_buy_offset:
            if current_trailing_profit_ratio > key:
                return trailing_buy_offset[key]

        return default_offset
########################################################################################################################################################
# Populate Indicators
########################################################################################################################################################
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = super().populate_indicators(dataframe, metadata)
        self.trailing_buy(metadata['pair'])
        return dataframe
########################################################################################################################################################
# Populate Buy Trend
########################################################################################################################################################
    def populate_buy_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = super().populate_buy_trend(dataframe, metadata)

        if self.trailing_buy_order_enabled and self.config['runmode'].value in ('live', 'dry_run'): 
            last_candle = dataframe.iloc[-1].squeeze()
            trailing_buy = self.trailing_buy(metadata['pair'])
            if last_candle['enter_long'] == 1:
                if not trailing_buy['trailing_buy_order_started']:
                    open_trades = Trade.get_trades([Trade.pair == metadata['pair'], Trade.is_open.is_(True), ]).all()
                    if not open_trades:
                        logger.info(f"Set 'allow_trailing' to True for {metadata['pair']} to start trailing!!!")
                        trailing_buy['allow_trailing'] = True
                        initial_enter_tag = last_candle['enter_tag'] if 'enter_tag' in last_candle else 'buy signal'
                        dataframe.loc[:, 'enter_tag'] = f"{initial_enter_tag} (start trail price {last_candle['close']})"
            else:
                if trailing_buy['trailing_buy_order_started']:
                    logger.info(f"Continue trailing for {metadata['pair']}. Manually trigger buy signal!!")
                    dataframe.loc[:,'enter_long'] = 1
                    dataframe.loc[:, 'enter_tag'] = trailing_buy['enter_tag']

        return dataframe
########################################################################################################################################################
# Confirm Trade Entry
########################################################################################################################################################
    def confirm_trade_entry(self, pair: str, order_type: str, amount: float, rate: float, time_in_force: str, **kwargs) -> bool:
        val = super().confirm_trade_entry(pair, order_type, amount, rate, time_in_force, **kwargs)
        
        if val and self.trailing_buy_order_enabled and self.config['runmode'].value in ('live', 'dry_run'):
            dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
            if len(dataframe) >= 1:
                last_candle = dataframe.iloc[-1].squeeze()
                current_price = rate
                trailing_buy = self.trailing_buy(pair)
                trailing_buy_offset = self.trailing_buy_offset(dataframe, pair, current_price)

                if trailing_buy['allow_trailing']:
                    if not trailing_buy['trailing_buy_order_started'] and last_candle['enter_long'] == 1:
                        # start trailing buy
                        # self.custom_info_trail_buy[pair]['trailing_buy']['trailing_buy_order_started'] = True
                        # self.custom_info_trail_buy[pair]['trailing_buy']['trailing_buy_order_uplimit'] = last_candle['close']
                        # self.custom_info_trail_buy[pair]['trailing_buy']['start_trailing_price'] = last_candle['close']
                        # self.custom_info_trail_buy[pair]['trailing_buy']['enter_tag'] = f"initial_enter_tag (strat trail price {last_candle['close']})"
                        # self.custom_info_trail_buy[pair]['trailing_buy']['start_trailing_time'] = datetime.now(timezone.utc)
                        # self.custom_info_trail_buy[pair]['trailing_buy']['offset'] = 0
                        trailing_buy['trailing_buy_order_started'] = True
                        trailing_buy['trailing_buy_order_uplimit'] = last_candle['close']
                        trailing_buy['start_trailing_price'] = last_candle['close']
                        trailing_buy['enter_tag'] = last_candle['enter_tag']
                        trailing_buy['start_trailing_time'] = datetime.now(timezone.utc)
                        trailing_buy['offset'] = 0
                        self.trailing_buy_info(pair, current_price)
                        logger.info(f'start trailing buy for {pair} at {last_candle["close"]}')
                    elif trailing_buy['trailing_buy_order_started']:
                        if trailing_buy_offset == 'forcebuy':
                            val = True
                            self.trailing_buy_info(pair, current_price)
                            logger.info(f"price OK for {pair}, order may not be triggered if all slots are full")
                        elif trailing_buy_offset is None:
                            self.trailing_buy(pair, reinit=True)
                            logger.info(f'STOP trailing buy for {pair} because "trailing buy offset" returned None')
                        elif current_price < trailing_buy['trailing_buy_order_uplimit']:
                            old_uplimit = trailing_buy["trailing_buy_order_uplimit"]
                            trailing_buy['trailing_buy_order_uplimit'] = min(current_price * (1 + trailing_buy_offset), trailing_buy['trailing_buy_order_uplimit'])
                            trailing_buy['offset'] = trailing_buy_offset
                            self.trailing_buy_info(pair, current_price)
                            logger.info(f'update trailing buy for {pair} at {old_uplimit} -> {trailing_buy["trailing_buy_order_uplimit"]}')
                        elif current_price < (trailing_buy['start_trailing_price'] * (1 + self.trailing_buy_max_buy)):
                            val = True
                            self.trailing_buy_info(pair, current_price)
                            logger.info(f"current price ({current_price}) > uplimit ({trailing_buy['trailing_buy_order_uplimit']}) and lower than starting price price ({(trailing_buy['start_trailing_price'] * (1 + self.trailing_buy_max_buy))}). OK for {pair}, order may not be triggered if all slots are full")
                        elif current_price > (trailing_buy['start_trailing_price'] * (1 + self.trailing_buy_max_stop)):
                            self.trailing_buy(pair, reinit=True)
                            self.trailing_buy_info(pair, current_price)
                            logger.info(f'STOP trailing buy for {pair} because of the price is higher than starting price * {1 + self.trailing_buy_max_stop}')
                        else:
                            self.trailing_buy_info(pair, current_price)
                            logger.info(f'price too high for {pair} !')
                else:
                    logger.info(f"Wait for next buy signal for {pair}")

            if val:
                self.trailing_buy_info(pair, rate)
                self.trailing_buy(pair, reinit=True)
                logger.info(f'STOP trailing buy for {pair} because I buy it')
        
        return val