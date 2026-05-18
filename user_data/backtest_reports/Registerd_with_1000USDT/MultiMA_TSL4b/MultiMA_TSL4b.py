import warnings
warnings.filterwarnings(
    "ignore",
    message=".*Downcasting object dtype arrays on \\.fillna, \\.ffill, \\.bfill is deprecated.*",
    category=FutureWarning,
)

import freqtrade.vendor.qtpylib.indicators as qtpylib
from typing import Dict, List, Optional
import numpy as np
import pandas as pd
import talib.abstract as ta
from freqtrade.strategy import IStrategy
from freqtrade.strategy import (
    merge_informative_pair,
    CategoricalParameter,
    DecimalParameter,
    IntParameter,
    BooleanParameter,
    timeframe_to_minutes,
)
from pandas import DataFrame, Series
from functools import reduce
from freqtrade.persistence import Trade, PairLocks
from datetime import datetime, timedelta, timezone
from freqtrade.exchange import timeframe_to_prev_date
from technical.indicators import zema
import math
import pandas_ta as pta
import logging
import time

logger = logging.getLogger(__name__)


def ensure_datetime(dataframe: DataFrame) -> DataFrame:
    if dataframe is None or dataframe.empty:
        return dataframe
    if "date" in dataframe.columns:
        dataframe = dataframe.copy()
        dataframe["date"] = pd.to_datetime(dataframe["date"], utc=True, errors="coerce")
        dataframe = dataframe.dropna(subset=["date"])
    return dataframe


########################################################################################################################################################
# VIDYA
########################################################################################################################################################
def vidya(dataframe, length=10, alpha=0.2):
    df = dataframe.copy()

    tr = ta.TRANGE(df)
    volatility = ta.SMA(tr, timeperiod=length)

    ema_base = ta.EMA(df["close"], timeperiod=length)
    diff = df["close"] - ema_base

    out = diff.ewm(alpha=alpha, adjust=False).mean()

    close_sma = ta.SMA(df["close"], timeperiod=length)
    close_sma = Series(close_sma, index=df.index, dtype="float64").replace(0, np.nan)

    out = out * (1 + alpha * (volatility / close_sma))
    out = Series(out, index=df.index, dtype="float64").fillna(0.0)

    return out


########################################################################################################################################################
# Elliot Wave Oscillator
########################################################################################################################################################
def EWO(dataframe, sma1_length=5, sma2_length=35):
    df = dataframe.copy()
    sma1 = ta.SMA(df, timeperiod=sma1_length)
    sma2 = ta.SMA(df, timeperiod=sma2_length)
    smadif = (sma1 - sma2) / df["close"] * 100
    return smadif


########################################################################################################################################################
# PMAX
########################################################################################################################################################
def pmax(df, period, multiplier, length, MAtype, src):
    df = df.copy()

    period = int(period)
    multiplier = int(multiplier)
    length = int(length)
    MAtype = int(MAtype)
    src = int(src)

    if src == 1:
        masrc = df["close"]
    elif src == 2:
        masrc = (df["high"] + df["low"]) / 2.0
    else:
        masrc = (df["high"] + df["low"] + df["close"] + df["open"]) / 4.0

    if MAtype == 1:
        mavalue = ta.EMA(masrc, timeperiod=length)
    elif MAtype == 2:
        mavalue = ta.DEMA(masrc, timeperiod=length)
    elif MAtype == 3:
        mavalue = ta.T3(masrc, timeperiod=length)
    elif MAtype == 4:
        mavalue = ta.SMA(masrc, timeperiod=length)
    elif MAtype == 5:
        mavalue = vidya(df, length=length)
    elif MAtype == 6:
        mavalue = ta.TEMA(masrc, timeperiod=length)
    elif MAtype == 7:
        mavalue = ta.WMA(masrc, timeperiod=length)
    elif MAtype == 8:
        mavalue = vwma(df, length)
    elif MAtype == 9:
        mavalue = zema(df, period=length)
    else:
        mavalue = ta.EMA(masrc, timeperiod=length)

    mavalue = Series(mavalue, index=df.index, dtype="float64").fillna(0.0)

    atr_series = ta.ATR(df, timeperiod=period)
    atr_series = Series(atr_series, index=df.index, dtype="float64").fillna(0.0)

    basic_ub = (mavalue + ((multiplier / 10.0) * atr_series)).to_numpy(dtype=float)
    basic_lb = (mavalue - ((multiplier / 10.0) * atr_series)).to_numpy(dtype=float)
    mavalue_np = mavalue.to_numpy(dtype=float)

    final_ub = np.zeros(len(df), dtype=float)
    final_lb = np.zeros(len(df), dtype=float)

    for i in range(period, len(df)):
        final_ub[i] = (
            basic_ub[i]
            if (basic_ub[i] < final_ub[i - 1] or mavalue_np[i - 1] > final_ub[i - 1])
            else final_ub[i - 1]
        )
        final_lb[i] = (
            basic_lb[i]
            if (basic_lb[i] > final_lb[i - 1] or mavalue_np[i - 1] < final_lb[i - 1])
            else final_lb[i - 1]
        )

    pm_arr = np.zeros(len(df), dtype=float)
    for i in range(period, len(df)):
        pm_arr[i] = (
            final_ub[i]
            if (pm_arr[i - 1] == final_ub[i - 1] and mavalue_np[i] <= final_ub[i])
            else final_lb[i]
            if (pm_arr[i - 1] == final_ub[i - 1] and mavalue_np[i] > final_ub[i])
            else final_lb[i]
            if (pm_arr[i - 1] == final_lb[i - 1] and mavalue_np[i] >= final_lb[i])
            else final_ub[i]
            if (pm_arr[i - 1] == final_lb[i - 1] and mavalue_np[i] < final_lb[i])
            else 0.0
        )

    pm = Series(pm_arr, index=df.index, dtype="float64")

    pmx = pd.Series(index=df.index, dtype="object")
    valid_mask = pm > 0.0
    pmx.loc[valid_mask & (mavalue < pm)] = "down"
    pmx.loc[valid_mask & (mavalue >= pm)] = "up"

    return pm, pmx


########################################################################################################################################################
# smoothed Heiken Ashi
########################################################################################################################################################
def HA(dataframe, smoothing=None):
    df = dataframe.copy()

    df["HA_Close"] = (df["open"] + df["high"] + df["low"] + df["close"]) / 4.0

    df.reset_index(inplace=True)

    ha_open = [(df["open"][0] + df["close"][0]) / 2.0]
    [ha_open.append((ha_open[i] + df["HA_Close"].values[i]) / 2.0) for i in range(0, len(df) - 1)]
    df["HA_Open"] = ha_open

    df.set_index("index", inplace=True)

    df["HA_High"] = df[["HA_Open", "HA_Close", "high"]].max(axis=1)
    df["HA_Low"] = df[["HA_Open", "HA_Close", "low"]].min(axis=1)

    if smoothing is not None:
        sml = abs(int(smoothing))
        if sml > 0:
            df["Smooth_HA_O"] = ta.EMA(df["HA_Open"], sml)
            df["Smooth_HA_H"] = ta.EMA(df["HA_High"], sml)
            df["Smooth_HA_L"] = ta.EMA(df["HA_Low"], sml)

    return df


########################################################################################################################################################
def pump_warning(dataframe, perc=15):
    df = dataframe.copy()
    df["change"] = df["high"] - df["low"]
    df["test1"] = df["close"] > df["open"]
    df["test2"] = (df["change"] / df["low"]) > (perc / 100)
    df["result"] = (df["test1"] & df["test2"]).astype("int")
    return df["result"]


########################################################################################################################################################
# Volume Weighted Moving Average
########################################################################################################################################################
def vwma(dataframe, length=10):
    pv = dataframe["close"] * dataframe["volume"]
    out = ta.SMA(pv, timeperiod=length) / ta.SMA(dataframe["volume"], timeperiod=length)
    out = Series(out, index=dataframe.index, dtype="float64").fillna(0.0)
    return out


########################################################################################################################################################
def tv_wma(dataframe, length=9, field="close") -> Series:
    norm = 0.0
    total = 0.0

    for i in range(1, length):
        weight = (length - i) * length
        norm += weight
        total += dataframe[field].shift(i) * weight

    out = (total / norm) if norm > 0 else 0.0
    return Series(out, index=dataframe.index, dtype="float64").fillna(0.0)


########################################################################################################################################################
def tv_hma(dataframe, length=9, field="close") -> Series:
    df = dataframe.copy()
    df["h"] = 2 * tv_wma(df, math.floor(length / 2), field) - tv_wma(df, length, field)
    df["tv_hma"] = tv_wma(df, math.floor(math.sqrt(length)), "h")
    return Series(df["tv_hma"], index=df.index, dtype="float64").fillna(0.0)


########################################################################################################################################################
class MultiMA_TSL4b(IStrategy):
########################################################################################################################################################
    INTERFACE_VERSION = 3
    can_short = False

    protection_params = {
        "cooldown_lookback": 2,
    }

    cooldown_lookback = IntParameter(2, 48, default=2, space="protection", optimize=False)

    @property
    def protections(self):
        prot = []
        prot.append({
            "method": "CooldownPeriod",
            "stop_duration_candles": self.cooldown_lookback.value
        })
        return prot

    buy_params = {
        "base_nb_candles_buy_ema": 32,
        "base_nb_candles_buy_ema2": 73,
        "low_offset_ema": 1.014,
        "low_offset_ema2": 1.054,
        "base_nb_candles_buy_hma": 30,
        "low_offset_hma": 0.953,
        "base_nb_candles_buy_hma2": 66,
        "low_offset_hma2": 0.904,
        "base_nb_candles_buy_vwma": 26,
        "low_offset_vwma": 0.949,
        "base_nb_candles_buy_vwma2": 27,
        "low_offset_vwma2": 0.982,
        "base_nb_candles_buy_vwma3": 69,
        "low_offset_vwma3": 0.932,
        "base_nb_candles_buy_vwma4": 75,
        "low_offset_vwma4": 0.903,
        "rsi_buy_vwma": 66,
        "rsi_fast_buy_vwma": 34,
        "buy_rsi_4_vwma3": 63,
        "buy_rsi_vwma3": 62,
        "buy_rsx_4_vwma3": 69,
        "buy_rsx_vwma3": 58,
        "ewo_high": 5.9,
        "ewo_high2": 6.1,
        "ewo_low": -9.6,
        "ewo_low2": -16.8,
        "rsi_buy": 63,
        "rsi_buy2": 48,
        "rsx_buy": 64,
        "rsx_buy2": 53,
        "rsx_4_buy": 36,
        "rsx_4_buy2": 35,
        "base_nb_candles_ema_sell": 31,
        "high_offset_sell_ema": 1.0,
        "base_nb_candles_ema_sell2": 20,
        "high_offset_sell_ema2": 1.018,
        "buy_length_volatility": 11,
        "buy_max_volatility": 1.65,
        "buy_length_volatility2": 16,
        "buy_max_volatility2": 1.67,
        "rsi_btc_15m_2": 15,
        "rsi_btc_5m_2": 13,
    }

    sell_params = {
        "min_rsi_sell": 47,
        "min_rsi_sell_2": 43,
        "base_nb_candles_ema_sell3": 83,
        "high_offset_sell_ema3": 0.96,
        "base_nb_candles_ema_sell4": 126,
        "high_offset_sell_ema4": 0.901,
        "base_nb_candles_ema_sell5": 134,
        "high_offset_sell_ema5": 1.048,
        "base_nb_candles_ema_sell6": 47,
        "high_offset_sell_ema6": 1.05,
        "base_nb_candles_ema_sell7": 113,
        "high_offset_sell_ema7": 0.948,
        "base_nb_candles_ema_sell8": 16,
        "high_offset_sell_ema8": 0.979,
    }

    minimal_roi = {
        "0": 100
    }

    stoploss = -0.119
    trailing_stop = False
    trailing_only_offset_is_reached = True
    trailing_stop_positive = 0.01
    trailing_stop_positive_offset = 0.018
    use_custom_stoploss = False

    timeframe = "5m"
    process_only_new_candles = True
    startup_candle_count: int = 288

    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    age_filter = 30

    dummy = IntParameter(20, 70, default=61, space="buy", optimize=False)

    optimize_buy_ema = False
    base_nb_candles_buy_ema = IntParameter(5, 80, default=buy_params["base_nb_candles_buy_ema"], space="buy", optimize=optimize_buy_ema)
    low_offset_ema = DecimalParameter(0.9, 1.1, default=buy_params["low_offset_ema"], space="buy", optimize=optimize_buy_ema)

    optimize_buy_ema2 = False
    base_nb_candles_buy_ema2 = IntParameter(5, 80, default=buy_params["base_nb_candles_buy_ema2"], space="buy", optimize=optimize_buy_ema2)
    low_offset_ema2 = DecimalParameter(0.9, 1.1, default=buy_params["low_offset_ema2"], space="buy", optimize=optimize_buy_ema2)

    optimize_buy_hma = False
    base_nb_candles_buy_hma = IntParameter(5, 80, default=buy_params["base_nb_candles_buy_hma"], space="buy", optimize=optimize_buy_hma)
    low_offset_hma = DecimalParameter(0.9, 0.99, default=buy_params["low_offset_hma"], space="buy", optimize=optimize_buy_hma)

    optimize_buy_vwma = False
    base_nb_candles_buy_vwma = IntParameter(5, 80, default=buy_params["base_nb_candles_buy_vwma"], space="buy", optimize=optimize_buy_vwma)
    low_offset_vwma = DecimalParameter(0.9, 0.99, default=buy_params["low_offset_vwma"], space="buy", optimize=optimize_buy_vwma)

    optimize_buy_vwma2 = False
    base_nb_candles_buy_vwma2 = IntParameter(5, 80, default=buy_params["base_nb_candles_buy_vwma2"], space="buy", optimize=optimize_buy_vwma2)
    low_offset_vwma2 = DecimalParameter(0.9, 0.99, default=buy_params["low_offset_vwma2"], space="buy", optimize=optimize_buy_vwma2)

    optimize_buy_vwma3 = False
    base_nb_candles_buy_vwma3 = IntParameter(5, 80, default=6, space="buy", optimize=optimize_buy_vwma3)
    low_offset_vwma3 = DecimalParameter(0.9, 0.99, default=0.95, space="buy", optimize=optimize_buy_vwma3)

    optimize_buy_vwma4 = False
    base_nb_candles_buy_vwma4 = IntParameter(5, 80, default=6, space="buy", optimize=optimize_buy_vwma4)
    low_offset_vwma4 = DecimalParameter(0.9, 0.99, default=0.95, space="buy", optimize=optimize_buy_vwma4)

    optimize_rsi_buy_vwma = False
    rsi_buy_vwma = IntParameter(30, 70, default=50, space="buy", optimize=optimize_rsi_buy_vwma)
    rsi_fast_buy_vwma = IntParameter(30, 70, default=50, space="buy", optimize=optimize_rsi_buy_vwma)

    ewo_check_optimize = False
    ewo_low = DecimalParameter(-20.0, -8.0, default=-20.0, decimals=1, space="buy", optimize=ewo_check_optimize)
    ewo_high = DecimalParameter(2.0, 12.0, default=6.0, decimals=1, space="buy", optimize=ewo_check_optimize)
    ewo_low2 = DecimalParameter(-20.0, -8.0, default=-20.0, decimals=1, space="buy", optimize=ewo_check_optimize)
    ewo_high2 = DecimalParameter(2.0, 12.0, default=6.0, decimals=1, space="buy", optimize=ewo_check_optimize)

    rsi_buy_optimize = False
    rsi_buy = IntParameter(30, 70, default=50, space="buy", optimize=rsi_buy_optimize)
    rsi_buy2 = IntParameter(30, 70, default=50, space="buy", optimize=rsi_buy_optimize)
    buy_rsi_fast = IntParameter(0, 50, default=35, space="buy", optimize=False)

    optimize_rsx_buy = False
    rsx_buy = IntParameter(30, 70, default=50, space="buy", optimize=optimize_rsx_buy)
    rsx_buy2 = IntParameter(30, 70, default=50, space="buy", optimize=optimize_rsx_buy)

    optimize_rsx_4_buy = False
    rsx_4_buy = IntParameter(30, 70, default=50, space="buy", optimize=optimize_rsx_4_buy)
    rsx_4_buy2 = IntParameter(30, 70, default=50, space="buy", optimize=optimize_rsx_4_buy)

    buy_rsx_vwma3 = IntParameter(10, 70, default=50, optimize=False)
    buy_rsx_4_vwma3 = IntParameter(10, 70, default=50, optimize=False)
    buy_rsi_vwma3 = IntParameter(10, 70, default=50, optimize=False)
    buy_rsi_4_vwma3 = IntParameter(10, 70, default=50, optimize=False)

    distance_max_close = DecimalParameter(1.0, 1.2, default=1.06, decimals=2, space="buy", optimize=False)
    distance_max_close2 = DecimalParameter(1.0, 1.2, default=1.09, decimals=2, space="buy", optimize=False)

    optimize_buy_volatility = False
    buy_length_volatility = IntParameter(10, 200, default=72, space="buy", optimize=optimize_buy_volatility)
    buy_min_volatility = DecimalParameter(0, 0.5, default=0, decimals=2, space="buy", optimize=False)
    buy_max_volatility = DecimalParameter(0.5, 2, default=1, decimals=2, space="buy", optimize=optimize_buy_volatility)

    optimize_buy_volatility2 = False
    buy_length_volatility2 = IntParameter(10, 200, default=72, space="buy", optimize=optimize_buy_volatility2)
    buy_max_volatility2 = DecimalParameter(0.5, 2, default=1, decimals=2, space="buy", optimize=optimize_buy_volatility2)

    fast_ewo = IntParameter(10, 50, default=50, space="buy", optimize=False)
    slow_ewo = IntParameter(100, 200, default=200, space="buy", optimize=False)

    optimize_sell_ema = False
    base_nb_candles_ema_sell = IntParameter(5, 80, default=20, space="buy", optimize=optimize_sell_ema)
    high_offset_sell_ema = DecimalParameter(0.99, 1.1, default=1.012, space="buy", optimize=optimize_sell_ema)
    min_rsi_sell = IntParameter(30, 100, default=50, space="sell", optimize=False)

    optimize_sell_ema2 = False
    base_nb_candles_ema_sell2 = IntParameter(5, 80, default=20, space="buy", optimize=optimize_sell_ema2)
    high_offset_sell_ema2 = DecimalParameter(0.99, 1.1, default=1.012, space="buy", optimize=optimize_sell_ema2)
    min_rsi_sell_2 = IntParameter(30, 100, default=50, space="sell", optimize=False)

    optimize_sell_ema3 = False
    base_nb_candles_ema_sell3 = IntParameter(5, 140, default=20, space="sell", optimize=optimize_sell_ema3)
    high_offset_sell_ema3 = DecimalParameter(0.9, 1.1, default=1.012, space="sell", optimize=optimize_sell_ema3)

    optimize_sell_ema4 = False
    base_nb_candles_ema_sell4 = IntParameter(5, 140, default=20, space="sell", optimize=optimize_sell_ema4)
    high_offset_sell_ema4 = DecimalParameter(0.9, 1.1, default=1.012, space="sell", optimize=optimize_sell_ema4)

    optimize_sell_ema5 = False
    base_nb_candles_ema_sell5 = IntParameter(5, 140, default=20, space="sell", optimize=optimize_sell_ema5)
    high_offset_sell_ema5 = DecimalParameter(0.9, 1.1, default=1.012, space="sell", optimize=optimize_sell_ema5)

    optimize_sell_ema6 = False
    base_nb_candles_ema_sell6 = IntParameter(5, 140, default=20, space="sell", optimize=optimize_sell_ema6)
    high_offset_sell_ema6 = DecimalParameter(0.9, 1.1, default=1.012, space="sell", optimize=optimize_sell_ema6)

    optimize_sell_ema7 = False
    base_nb_candles_ema_sell7 = IntParameter(5, 140, default=20, space="sell", optimize=optimize_sell_ema7)
    high_offset_sell_ema7 = DecimalParameter(0.9, 1.1, default=1.012, space="sell", optimize=optimize_sell_ema7)

    optimize_sell_ema8 = False
    base_nb_candles_ema_sell8 = IntParameter(5, 140, default=20, space="sell", optimize=optimize_sell_ema8)
    high_offset_sell_ema8 = DecimalParameter(0.9, 1.1, default=1.012, space="sell", optimize=optimize_sell_ema8)

    def informative_pairs(self):
        pairs = self.dp.current_whitelist()
        return [(pair, "1d") for pair in pairs]

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = dataframe.copy()
        dataframe = ensure_datetime(dataframe)

        # hard-safe 1d informative merge without decorator
        inf_1d = self.dp.get_pair_dataframe(pair=metadata["pair"], timeframe="1d")
        if inf_1d is not None and not inf_1d.empty:
            inf_1d = inf_1d.copy()
            inf_1d = ensure_datetime(inf_1d)
            if inf_1d is not None and not inf_1d.empty:
                inf_1d["age_filter_ok"] = (
                    inf_1d["volume"].rolling(window=self.age_filter, min_periods=self.age_filter).min() > 0
                )
                dataframe = merge_informative_pair(
                    dataframe,
                    inf_1d[["date", "age_filter_ok"]],
                    self.timeframe,
                    "1d",
                    ffill=True,
                )
            else:
                dataframe["age_filter_ok_1d"] = False
        else:
            dataframe["age_filter_ok_1d"] = False

        if "age_filter_ok_1d" not in dataframe.columns:
            dataframe["age_filter_ok_1d"] = False
        dataframe["age_filter_ok_1d"] = (
            dataframe["age_filter_ok_1d"]
            .astype("boolean")
            .fillna(False)
            .astype(bool)
        )

        dataframe["ewo"] = EWO(dataframe, self.fast_ewo.value, self.slow_ewo.value)
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["rsi_fast"] = ta.RSI(dataframe, timeperiod=4)

        dataframe["rsx_14"] = pta.rsx(dataframe["close"], length=14)
        dataframe["rsx_4"] = pta.rsx(dataframe["close"], length=4)

        heikinashi = qtpylib.heikinashi(dataframe)
        heikinashi["volume"] = dataframe["volume"]

        dataframe["pm"], _ = pmax(heikinashi, MAtype=1, length=9, multiplier=27, period=10, src=3)
        df_source = (dataframe["high"] + dataframe["low"] + dataframe["open"] + dataframe["close"]) / 4
        dataframe["pmax_thresh"] = ta.EMA(df_source, timeperiod=9)

        dataframe["live_data_ok"] = (
            dataframe["volume"].rolling(window=72, min_periods=72).min() > 0
        )

        if not self.optimize_buy_ema:
            dataframe["ema_offset_buy"] = ta.EMA(dataframe, int(self.base_nb_candles_buy_ema.value)) * self.low_offset_ema.value
        if not self.optimize_buy_ema2:
            dataframe["ema_offset_buy2"] = ta.EMA(dataframe, int(self.base_nb_candles_buy_ema2.value)) * self.low_offset_ema2.value

        if not self.optimize_sell_ema:
            dataframe["ema_offset_sell"] = ta.EMA(dataframe, int(self.base_nb_candles_ema_sell.value)) * self.high_offset_sell_ema.value
        if not self.optimize_sell_ema2:
            dataframe["ema_offset_sell2"] = ta.EMA(dataframe, int(self.base_nb_candles_ema_sell2.value)) * self.high_offset_sell_ema2.value
        if not self.optimize_sell_ema3:
            dataframe["ema_offset_sell3"] = ta.EMA(dataframe, int(self.base_nb_candles_ema_sell3.value)) * self.high_offset_sell_ema3.value
        if not self.optimize_sell_ema4:
            dataframe["ema_offset_sell4"] = ta.EMA(dataframe, int(self.base_nb_candles_ema_sell4.value)) * self.high_offset_sell_ema4.value
        if not self.optimize_sell_ema5:
            dataframe["ema_offset_sell5"] = ta.EMA(dataframe, int(self.base_nb_candles_ema_sell5.value)) * self.high_offset_sell_ema5.value
        if not self.optimize_sell_ema6:
            dataframe["ema_offset_sell6"] = ta.EMA(dataframe, int(self.base_nb_candles_ema_sell6.value)) * self.high_offset_sell_ema6.value
        if not self.optimize_sell_ema7:
            dataframe["ema_offset_sell7"] = ta.EMA(dataframe, int(self.base_nb_candles_ema_sell7.value)) * self.high_offset_sell_ema7.value
        if not self.optimize_sell_ema8:
            dataframe["ema_offset_sell8"] = ta.EMA(dataframe, int(self.base_nb_candles_ema_sell8.value)) * self.high_offset_sell_ema8.value

        if not self.optimize_buy_hma:
            dataframe["hma_offset_buy"] = tv_hma(dataframe, int(self.base_nb_candles_buy_hma.value)) * self.low_offset_hma.value

        if not self.optimize_buy_vwma:
            dataframe["vwma_offset_buy"] = pta.vwma(dataframe["close"], dataframe["volume"], int(self.base_nb_candles_buy_vwma.value)) * self.low_offset_vwma.value
        if not self.optimize_buy_vwma2:
            dataframe["vwma_offset_buy2"] = pta.vwma(dataframe["close"], dataframe["volume"], int(self.base_nb_candles_buy_vwma2.value)) * self.low_offset_vwma2.value
        if not self.optimize_buy_vwma3:
            dataframe["vwma_offset_buy3"] = pta.vwma(dataframe["close"], dataframe["volume"], int(self.base_nb_candles_buy_vwma3.value)) * self.low_offset_vwma3.value
        if not self.optimize_buy_vwma4:
            dataframe["vwma_offset_buy4"] = pta.vwma(dataframe["close"], dataframe["volume"], int(self.base_nb_candles_buy_vwma4.value)) * self.low_offset_vwma4.value

        if not self.optimize_buy_volatility:
            df_std = dataframe["close"].rolling(int(self.buy_length_volatility.value)).std()
            dataframe["volatility"] = (df_std > self.buy_min_volatility.value) & (df_std < self.buy_max_volatility.value)

        if not self.optimize_buy_volatility2:
            df_std = dataframe["close"].rolling(int(self.buy_length_volatility2.value)).std()
            dataframe["volatility2"] = (df_std > self.buy_min_volatility.value) & (df_std < self.buy_max_volatility2.value)

        dataframe["pm"] = Series(dataframe["pm"], index=dataframe.index, dtype="float64").fillna(0.0)
        dataframe["pmax_thresh"] = Series(dataframe["pmax_thresh"], index=dataframe.index, dtype="float64").fillna(0.0)

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        conditions = []

        if self.optimize_buy_ema:
            dataframe["ema_offset_buy"] = ta.EMA(dataframe, int(self.base_nb_candles_buy_ema.value)) * self.low_offset_ema.value
        if self.optimize_buy_ema2:
            dataframe["ema_offset_buy2"] = ta.EMA(dataframe, int(self.base_nb_candles_buy_ema2.value)) * self.low_offset_ema2.value

        if self.optimize_sell_ema:
            dataframe["ema_offset_sell"] = ta.EMA(dataframe, int(self.base_nb_candles_ema_sell.value)) * self.high_offset_sell_ema.value
        if self.optimize_sell_ema2:
            dataframe["ema_offset_sell2"] = ta.EMA(dataframe, int(self.base_nb_candles_ema_sell2.value)) * self.high_offset_sell_ema2.value

        if self.optimize_buy_volatility:
            df_std = dataframe["close"].rolling(int(self.buy_length_volatility.value)).std()
            dataframe["volatility"] = (df_std > self.buy_min_volatility.value) & (df_std < self.buy_max_volatility.value)

        if self.optimize_buy_volatility2:
            df_std = dataframe["close"].rolling(int(self.buy_length_volatility2.value)).std()
            dataframe["volatility2"] = (df_std > self.buy_min_volatility.value) & (df_std < self.buy_max_volatility2.value)

        dataframe.loc[:, "enter_tag"] = ""
        dataframe.loc[:, "buy_copy"] = 0
        dataframe.loc[:, "buy"] = 0
        dataframe.loc[:, "enter_long"] = 0

        if self.optimize_buy_hma:
            dataframe["hma_offset_buy"] = tv_hma(dataframe, int(self.base_nb_candles_buy_hma.value)) * self.low_offset_hma.value

        buy_offset_hma = (
            (
                (dataframe["close"] < dataframe["hma_offset_buy"])
                & (dataframe["pm"] <= dataframe["pmax_thresh"])
                & (dataframe["rsi"] < 35)
            )
            & (dataframe["rsi_fast"] < 30)
        )
        dataframe.loc[buy_offset_hma, "enter_tag"] += "hma_1 "

        if self.optimize_buy_vwma:
            dataframe["vwma_offset_buy"] = pta.vwma(dataframe["close"], dataframe["volume"], int(self.base_nb_candles_buy_vwma.value)) * self.low_offset_vwma.value
        if self.optimize_buy_vwma2:
            dataframe["vwma_offset_buy2"] = pta.vwma(dataframe["close"], dataframe["volume"], int(self.base_nb_candles_buy_vwma2.value)) * self.low_offset_vwma2.value
        if self.optimize_buy_vwma3:
            dataframe["vwma_offset_buy3"] = pta.vwma(dataframe["close"], dataframe["volume"], int(self.base_nb_candles_buy_vwma3.value)) * self.low_offset_vwma3.value
        if self.optimize_buy_vwma4:
            dataframe["vwma_offset_buy4"] = pta.vwma(dataframe["close"], dataframe["volume"], int(self.base_nb_candles_buy_vwma4.value)) * self.low_offset_vwma4.value

        buy_offset_vwma = (
            (dataframe["close"] < dataframe["vwma_offset_buy"])
            & (dataframe["pm"] <= dataframe["pmax_thresh"])
            & (dataframe["rsi"] < self.rsi_buy_vwma.value)
            & (dataframe["rsi_fast"] < self.rsi_fast_buy_vwma.value)
        )
        dataframe.loc[buy_offset_vwma, "enter_tag"] += "vwma_1 "
        conditions.append(buy_offset_vwma)

        buy_offset_vwma_2 = (
            (dataframe["close"] < dataframe["vwma_offset_buy2"])
            & (dataframe["pm"] > dataframe["pmax_thresh"])
        )
        dataframe.loc[buy_offset_vwma_2, "enter_tag"] += "vwma_2 "
        conditions.append(buy_offset_vwma_2)

        buy_offset_vwma_3 = (
            ((dataframe["close"] < dataframe["vwma_offset_buy3"]).rolling(2).min() > 0)
            & (dataframe["pm"] <= dataframe["pmax_thresh"])
            & (dataframe["rsi"] < self.buy_rsi_vwma3.value)
            & (dataframe["rsi_fast"] < self.buy_rsi_4_vwma3.value)
            & (dataframe["rsx_14"] < self.buy_rsx_vwma3.value)
            & (dataframe["rsx_4"] < self.buy_rsx_4_vwma3.value)
        )
        dataframe.loc[buy_offset_vwma_3, "enter_tag"] += "vwma_3 "
        conditions.append(buy_offset_vwma_3)

        buy_offset_vwma_4 = (
            ((dataframe["close"] < dataframe["vwma_offset_buy4"]).rolling(2).min() > 0)
            & (dataframe["pm"] > dataframe["pmax_thresh"])
        )
        dataframe.loc[buy_offset_vwma_4, "enter_tag"] += "vwma_4 "
        conditions.append(buy_offset_vwma_4)

        add_check = (
            (dataframe["live_data_ok"])
            & (dataframe["age_filter_ok_1d"])
            & (dataframe["rsi_fast"] < self.buy_rsi_fast.value)
            & (
                (
                    (dataframe["close"] < dataframe["ema_offset_buy"])
                    & (dataframe["pm"] <= dataframe["pmax_thresh"])
                    & (dataframe["volatility"])
                    & (dataframe["close"].rolling(288).max() >= (dataframe["close"] * self.distance_max_close.value))
                    & (
                        (dataframe["ewo"] < self.ewo_low.value)
                        | (
                            (dataframe["ewo"] > self.ewo_high.value)
                            & (dataframe["rsi"] < self.rsi_buy.value)
                        )
                    )
                    & (dataframe["close"] < dataframe["ema_offset_sell"])
                    & (dataframe["rsx_14"] < self.rsx_buy.value)
                    & (dataframe["rsx_4"] < self.rsx_4_buy.value)
                )
                | (
                    (dataframe["close"] < dataframe["ema_offset_buy2"])
                    & (dataframe["pm"] > dataframe["pmax_thresh"])
                    & (dataframe["volatility2"])
                    & (dataframe["close"].rolling(288).max() >= (dataframe["close"] * self.distance_max_close2.value))
                    & (
                        (dataframe["ewo"] < self.ewo_low2.value)
                        | (
                            (dataframe["ewo"] > self.ewo_high2.value)
                            & (dataframe["rsi"] < self.rsi_buy2.value)
                        )
                    )
                    & (dataframe["close"] < dataframe["ema_offset_sell2"])
                    & (dataframe["rsx_14"] < self.rsx_buy2.value)
                    & (dataframe["rsx_4"] < self.rsx_4_buy2.value)
                )
            )
            & (dataframe["volume"] > 0)
        )

        if conditions:
            dataframe.loc[
                (add_check & reduce(lambda x, y: x | y, conditions)),
                "enter_long",
            ] = 1

        dataframe.loc[
            buy_offset_hma & buy_offset_vwma,
            "enter_long",
        ] = 0

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[:, "exit_tag"] = ""
        dataframe.loc[:, "exit_long"] = 0
        conditions = []

        if self.optimize_sell_ema3:
            dataframe["ema_offset_sell3"] = ta.EMA(dataframe, int(self.base_nb_candles_ema_sell3.value)) * self.high_offset_sell_ema3.value
        if self.optimize_sell_ema4:
            dataframe["ema_offset_sell4"] = ta.EMA(dataframe, int(self.base_nb_candles_ema_sell4.value)) * self.high_offset_sell_ema4.value
        if self.optimize_sell_ema5:
            dataframe["ema_offset_sell5"] = ta.EMA(dataframe, int(self.base_nb_candles_ema_sell5.value)) * self.high_offset_sell_ema5.value
        if self.optimize_sell_ema6:
            dataframe["ema_offset_sell6"] = ta.EMA(dataframe, int(self.base_nb_candles_ema_sell6.value)) * self.high_offset_sell_ema6.value
        if self.optimize_sell_ema7:
            dataframe["ema_offset_sell7"] = ta.EMA(dataframe, int(self.base_nb_candles_ema_sell7.value)) * self.high_offset_sell_ema7.value
        if self.optimize_sell_ema8:
            dataframe["ema_offset_sell8"] = ta.EMA(dataframe, int(self.base_nb_candles_ema_sell8.value)) * self.high_offset_sell_ema8.value

        sell_cond_1 = (
            (dataframe["close"] > dataframe["ema_offset_sell"])
            & (dataframe["volume"] > 0)
            & (dataframe["rsi"] > self.min_rsi_sell.value)
            & (dataframe["pm"] <= dataframe["pmax_thresh"])
        )
        conditions.append(sell_cond_1)
        dataframe.loc[sell_cond_1, "exit_tag"] += "EMA_1 "

        sell_cond_2 = (
            (dataframe["close"] > dataframe["ema_offset_sell2"])
            & (dataframe["volume"] > 0)
            & (dataframe["rsi"] > self.min_rsi_sell_2.value)
            & (dataframe["pm"] > dataframe["pmax_thresh"])
        )
        conditions.append(sell_cond_2)
        dataframe.loc[sell_cond_2, "exit_tag"] += "EMA_2 "

        sell_cond_3 = (
            (dataframe["close"] < dataframe["ema_offset_sell3"])
            & (dataframe["volume"] > 0)
            & (dataframe["pm"] <= dataframe["pmax_thresh"])
        )
        conditions.append(sell_cond_3)
        dataframe.loc[sell_cond_3, "exit_tag"] += "EMA_3 "

        sell_cond_4 = (
            (dataframe["close"] < dataframe["ema_offset_sell4"])
            & (dataframe["volume"] > 0)
            & (dataframe["pm"] > dataframe["pmax_thresh"])
        )
        conditions.append(sell_cond_4)
        dataframe.loc[sell_cond_4, "exit_tag"] += "EMA_4 "

        sell_cond_5 = (
            ((dataframe["close"] > dataframe["ema_offset_sell5"]).rolling(2).min() > 0)
            & (dataframe["volume"] > 0)
            & (dataframe["pm"] > dataframe["pmax_thresh"])
        )
        conditions.append(sell_cond_5)
        dataframe.loc[sell_cond_5, "exit_tag"] += "EMA_5 "

        sell_cond_6 = (
            ((dataframe["close"] > dataframe["ema_offset_sell6"]).rolling(2).min() > 0)
            & (dataframe["volume"] > 0)
            & (dataframe["pm"] <= dataframe["pmax_thresh"])
        )
        conditions.append(sell_cond_6)
        dataframe.loc[sell_cond_6, "exit_tag"] += "EMA_6 "

        sell_cond_7 = (
            ((dataframe["close"] < dataframe["ema_offset_sell7"]).rolling(2).min() > 0)
            & (dataframe["volume"] > 0)
            & (dataframe["pm"] <= dataframe["pmax_thresh"])
        )
        conditions.append(sell_cond_7)
        dataframe.loc[sell_cond_7, "exit_tag"] += "EMA_7 "

        sell_cond_8 = (
            ((dataframe["close"] < dataframe["ema_offset_sell8"]).rolling(3).min() > 0)
            & (dataframe["volume"] > 0)
            & (dataframe["pm"] > dataframe["pmax_thresh"])
        )
        conditions.append(sell_cond_8)
        dataframe.loc[sell_cond_8, "exit_tag"] += "EMA_8 "

        if conditions:
            dataframe.loc[
                reduce(lambda x, y: x | y, conditions),
                "exit_long",
            ] = 1

        return dataframe