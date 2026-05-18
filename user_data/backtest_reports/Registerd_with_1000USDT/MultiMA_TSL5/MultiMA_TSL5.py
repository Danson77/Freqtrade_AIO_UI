import warnings
warnings.filterwarnings(
    "ignore",
    message=".*Downcasting object dtype arrays on \\.fillna, \\.ffill, \\.bfill is deprecated.*",
    category=FutureWarning,
)

import math
import logging
from functools import reduce
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import pandas_ta as pta
import talib.abstract as ta
import freqtrade.vendor.qtpylib.indicators as qtpylib

from pandas import DataFrame, Series
from freqtrade.strategy import IStrategy
from freqtrade.strategy import (
    DecimalParameter,
    IntParameter,
    BooleanParameter,
    CategoricalParameter,
    stoploss_from_open,
    merge_informative_pair,
)
from freqtrade.persistence import Trade
from datetime import datetime


logger = logging.getLogger(__name__)


########################################################################################################################################################
# Helpers
########################################################################################################################################################
def ensure_datetime(dataframe: DataFrame) -> DataFrame:
    if dataframe is None or dataframe.empty:
        return dataframe
    if "date" in dataframe.columns:
        dataframe = dataframe.copy()
        dataframe["date"] = pd.to_datetime(dataframe["date"], utc=True, errors="coerce")
        dataframe = dataframe.dropna(subset=["date"])
    return dataframe


########################################################################################################################################################
# zema
########################################################################################################################################################
def zema(dataframe: DataFrame, period: int, field: str = "close") -> Series:
    df = dataframe.copy()
    df["ema1"] = ta.EMA(df[field], timeperiod=period)
    df["ema2"] = ta.EMA(df["ema1"], timeperiod=period)
    df["d"] = df["ema1"] - df["ema2"]
    df["zema"] = df["ema1"] + df["d"]
    return Series(df["zema"], index=df.index, dtype="float64").fillna(0.0)


########################################################################################################################################################
# tv_wma
########################################################################################################################################################
def tv_wma(series: Series, length: int = 9) -> Series:
    norm = 0.0
    total = 0.0

    for i in range(1, length):
        weight = (length - i) * length
        norm += weight
        total += series.shift(i) * weight

    out = (total / norm) if norm > 0 else 0.0
    return Series(out, index=series.index, dtype="float64").fillna(0.0)


########################################################################################################################################################
# tv_hma
########################################################################################################################################################
def tv_hma(dataframe: DataFrame, length: int = 9, field: str = "close") -> Series:
    h = 2 * tv_wma(dataframe[field], math.floor(length / 2)) - tv_wma(dataframe[field], length)
    out = tv_wma(h, math.floor(math.sqrt(length)))
    return Series(out, index=dataframe.index, dtype="float64").fillna(0.0)


########################################################################################################################################################
# rvol
########################################################################################################################################################
def rvol(dataframe: DataFrame, window: int = 24) -> Series:
    av = Series(
        ta.SMA(dataframe["volume"], timeperiod=int(window)),
        index=dataframe.index,
        dtype="float64"
    )
    av = av.replace(0, np.nan)

    out = dataframe["volume"] / av
    return Series(out, index=dataframe.index, dtype="float64").fillna(0.0)
########################################################################################################################################################
# Volume Weighted Moving Average
########################################################################################################################################################
def vwma(dataframe: DataFrame, length: int = 10) -> Series:
    pv = dataframe["close"] * dataframe["volume"]
    out = ta.SMA(pv, timeperiod=length) / ta.SMA(dataframe["volume"], timeperiod=length)
    return Series(out, index=dataframe.index, dtype="float64").fillna(0.0)


########################################################################################################################################################
# VIDYA
########################################################################################################################################################
def vidya(dataframe: DataFrame, length: int = 10, alpha: float = 0.2) -> Series:
    df = dataframe.copy()

    tr = ta.TRANGE(df)
    volatility = ta.SMA(tr, timeperiod=length)

    ema_base = ta.EMA(df["close"], timeperiod=length)
    diff = df["close"] - ema_base

    out = diff.ewm(alpha=alpha, adjust=False).mean()

    close_sma = ta.SMA(df["close"], timeperiod=length)
    close_sma = Series(close_sma, index=df.index, dtype="float64").replace(0, np.nan)

    out = out * (1 + alpha * (volatility / close_sma))
    return Series(out, index=df.index, dtype="float64").fillna(0.0)


########################################################################################################################################################
# pmax
########################################################################################################################################################
def pmax(df: DataFrame, period, multiplier, length, MAtype, src):
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
    atr_series = Series(ta.ATR(df, timeperiod=period), index=df.index, dtype="float64").fillna(0.0)

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

    pm = Series(pm_arr, index=df.index, dtype="float64").fillna(0.0)

    pmx = pd.Series(index=df.index, dtype="object")
    valid_mask = pm > 0.0
    pmx.loc[valid_mask & (mavalue < pm)] = "down"
    pmx.loc[valid_mask & (mavalue >= pm)] = "up"

    return pm, pmx


########################################################################################################################################################
class MultiMA_TSL5(IStrategy):
########################################################################################################################################################
    INTERFACE_VERSION = 3
    can_short = False

    @property
    def protections(self):
        prot = []

        prot.append({
            "method": "LowProfitPairs",
            "lookback_period_candles": self.low_profit_lookback.value,
            "trade_limit": self.low_profit_trade_limit.value,
            "stop_duration_candles": int(self.low_profit_stop_duration.value),
            "required_profit": self.low_profit_min_req.value,
            "only_per_pair": True,
        })

        prot.append({
            "method": "LowProfitPairs",
            "lookback_period_candles": self.low_profit_lookback2.value,
            "trade_limit": self.low_profit_trade_limit2.value,
            "stop_duration_candles": int(self.low_profit_stop_duration2.value),
            "required_profit": self.low_profit_min_req2.value,
            "only_per_pair": False,
        })

        prot.append({
            "method": "MaxDrawdown",
            "lookback_period_candles": self.max_drawdown_lookback.value,
            "trade_limit": self.max_drawdown_trade_limit.value,
            "stop_duration_candles": self.max_drawdown_stop_duration.value,
            "max_allowed_drawdown": (0.05 * self.max_drawdown_allowed.value)
        })

        prot.append({
            "method": "StoplossGuard",
            "lookback_period_candles": self.stoploss_guard_lookback.value,
            "trade_limit": self.stoploss_guard_trade_limit.value,
            "stop_duration_candles": self.stoploss_guard_stop_duration.value,
            "only_per_pair": True,
            "only_per_side": True
        })

        return prot

    protection_params = {
        "low_profit_lookback": 60,
        "low_profit_min_req": 0.04,
        "low_profit_stop_duration": 28,
        "low_profit_trade_limit": 2,
        "low_profit_lookback2": 45,
        "low_profit_min_req2": -0.01,
        "low_profit_stop_duration2": 9,
        "low_profit_trade_limit2": 1,
        "max_drawdown_allowed": 1,
        "max_drawdown_lookback": 56,
        "max_drawdown_stop_duration": 10,
        "max_drawdown_trade_limit": 6,
        "stoploss_guard_lookback": 28,
        "stoploss_guard_stop_duration": 20,
    }

    buy_params = {
        "base_nb_candles_buy_hma": 95,
        "low_offset_hma": 0.92,
        "base_nb_candles_buy_hma2": 59,
        "low_offset_hma2": 0.92,
        "base_nb_candles_buy_hma3": 62,
        "low_offset_hma3": 0.89,
        "base_nb_candles_buy_ema": 7,
        "low_offset_ema": 0.988,
        "base_nb_candles_buy_ema_hma": 41,
        "low_offset_ema_hma": 0.985,
        "base_nb_candles_buy_ema_2": 13,
        "low_offset_ema_2": 0.986,
        "base_nb_candles_buy_ema2": 20,
        "low_offset_ema2": 0.953,
        "base_nb_candles_buy_ema3": 36,
        "low_offset_ema3": 0.955,
        "buy_rsx_1": 59,
        "buy_rsx_fast_1": 70,
        "buy_rsx_2": 42,
        "buy_rsx_fast_2": 68,
        "buy_rsx_fast_hma": 69,
        "buy_rsx_hma": 38,
        "buy_ema_fast_length_15m": 15,
        "buy_ema_fast_length_1h": 15,
        "buy_ema_slow_length_15m": 30,
        "buy_ema_slow_length_1h": 30,
        "buy_length_volume": 15,
        "buy_volume_volatility": 2.29,
        "buy_length_volume2": 21,
        "buy_volume_volatility2": 1.67,
    }

    sell_params = {
        "base_nb_candles_sell_ema": 88,
        "high_offset_ema": 1.05,
        "base_nb_candles_sell_ema2": 38,
        "high_offset_ema2": 1.018,
        "base_nb_candles_sell_ema3": 39,
        "high_offset_ema3": 0.957,
        "base_nb_candles_sell_ema4": 71,
        "high_offset_ema4": 0.941,
        "base_nb_candles_sell_ema5": 22,
        "high_offset_ema5": 0.948,
        "base_nb_candles_sell_ema6": 40,
        "high_offset_ema6": 0.861,
    }

    minimal_roi = {
        "0": 100.0
    }

    stoploss = -0.1

    trailing_stop = False
    trailing_stop_positive = 0.001
    trailing_stop_positive_offset = 0.01
    trailing_only_offset_is_reached = True

    timeframe = "5m"
    process_only_new_candles = True
    startup_candle_count = 200

    use_exit_signal = True
    exit_profit_only = False
    exit_profit_offset = 0.01
    ignore_roi_if_entry_signal = False

    age_filter = 30

    low_profit_optimize = False
    low_profit_lookback = IntParameter(2, 60, default=20, space="protection", optimize=low_profit_optimize)
    low_profit_trade_limit = IntParameter(2, 40, default=3, space="protection", optimize=low_profit_optimize)
    low_profit_stop_duration = IntParameter(2, 40, default=20, space="protection", optimize=low_profit_optimize)
    low_profit_min_req = DecimalParameter(-0.05, 0.05, default=-0.05, space="protection", decimals=2, optimize=low_profit_optimize)

    low_profit_optimize2 = False
    low_profit_lookback2 = IntParameter(2, 60, default=20, space="protection", optimize=low_profit_optimize2)
    low_profit_trade_limit2 = IntParameter(1, 5, default=3, space="protection", optimize=low_profit_optimize2)
    low_profit_stop_duration2 = IntParameter(2, 30, default=20, space="protection", optimize=low_profit_optimize2)
    low_profit_min_req2 = DecimalParameter(-0.05, 0.05, default=-0.05, space="protection", decimals=2, optimize=low_profit_optimize2)

    max_drawdown_optimize = False
    max_drawdown_lookback = IntParameter(2, 60, default=20, space="protection", optimize=max_drawdown_optimize)
    max_drawdown_trade_limit = IntParameter(2, 10, default=3, space="protection", optimize=max_drawdown_optimize)
    max_drawdown_stop_duration = IntParameter(2, 60, default=20, space="protection", optimize=max_drawdown_optimize)
    max_drawdown_allowed = IntParameter(1, 4, default=4, space="protection", optimize=max_drawdown_optimize)

    stoploss_guard_optimize = False
    stoploss_guard_lookback = IntParameter(1, 40, default=20, space="protection", optimize=stoploss_guard_optimize)
    stoploss_guard_trade_limit = IntParameter(1, 4, default=1, space="protection", optimize=False)
    stoploss_guard_stop_duration = IntParameter(1, 40, default=20, space="protection", optimize=stoploss_guard_optimize)

    dummy = IntParameter(20, 70, default=61, space="buy", optimize=False)

    buy_rsx_hma = IntParameter(10, 70, default=50, space="buy", optimize=False)
    buy_rsx_fast_hma = IntParameter(10, 70, default=50, space="buy", optimize=False)

    buy_rsx_1 = IntParameter(10, 70, default=50, space="buy", optimize=False)
    buy_rsx_fast_1 = IntParameter(10, 70, default=50, space="buy", optimize=False)

    buy_rsx_2 = IntParameter(10, 70, default=50, space="buy", optimize=False)
    buy_rsx_fast_2 = IntParameter(10, 70, default=50, space="buy", optimize=False)

    optimize_buy_hma = False
    base_nb_candles_buy_hma = IntParameter(5, 100, default=6, space="buy", optimize=optimize_buy_hma)
    low_offset_hma = DecimalParameter(0.7, 0.99, default=0.95, decimals=2, space="buy", optimize=optimize_buy_hma)

    optimize_buy_hma2 = False
    base_nb_candles_buy_hma2 = IntParameter(5, 100, default=6, space="buy", optimize=optimize_buy_hma2)
    low_offset_hma2 = DecimalParameter(0.7, 0.99, default=0.95, decimals=2, space="buy", optimize=optimize_buy_hma2)

    optimize_buy_hma3 = False
    base_nb_candles_buy_hma3 = IntParameter(5, 100, default=6, space="buy", optimize=optimize_buy_hma3)
    low_offset_hma3 = DecimalParameter(0.7, 0.99, default=0.95, decimals=2, space="buy", optimize=optimize_buy_hma3)

    optimize_buy_ema = False
    base_nb_candles_buy_ema = IntParameter(5, 100, default=6, space="buy", optimize=optimize_buy_ema)
    low_offset_ema = DecimalParameter(0.7, 0.99, default=0.9, space="buy", optimize=optimize_buy_ema)

    optimize_buy_ema_hma = False
    base_nb_candles_buy_ema_hma = IntParameter(5, 100, default=6, space="buy", optimize=optimize_buy_ema_hma)
    low_offset_ema_hma = DecimalParameter(0.7, 0.99, default=0.9, space="buy", optimize=optimize_buy_ema_hma)

    optimize_buy_ema_2 = False
    base_nb_candles_buy_ema_2 = IntParameter(5, 100, default=6, space="buy", optimize=optimize_buy_ema_2)
    low_offset_ema_2 = DecimalParameter(0.7, 0.99, default=0.9, space="buy", optimize=optimize_buy_ema_2)

    optimize_buy_ema2 = False
    base_nb_candles_buy_ema2 = IntParameter(5, 100, default=6, space="buy", optimize=optimize_buy_ema2)
    low_offset_ema2 = DecimalParameter(0.7, 0.99, default=0.9, space="buy", optimize=optimize_buy_ema2)

    optimize_buy_ema3 = False
    base_nb_candles_buy_ema3 = IntParameter(5, 100, default=6, space="buy", optimize=optimize_buy_ema3)
    low_offset_ema3 = DecimalParameter(0.7, 0.99, default=0.9, space="buy", optimize=optimize_buy_ema3)

    length_ema_15m = [5, 10, 15, 20, 25, 30, 35]
    optimize_buy_ema_length_15m = False
    buy_ema_fast_length_15m = CategoricalParameter([5, 10, 15, 20, 25, 30], default=15, optimize=optimize_buy_ema_length_15m)
    buy_ema_slow_length_15m = CategoricalParameter([10, 15, 20, 25, 30, 35], default=30, optimize=optimize_buy_ema_length_15m)

    length_ema_1h = [5, 10, 15, 20, 25, 30, 35]
    optimize_buy_ema_length_1h = False
    buy_ema_fast_length_1h = CategoricalParameter([5, 10, 15, 20, 25, 30], default=15, optimize=optimize_buy_ema_length_1h)
    buy_ema_slow_length_1h = CategoricalParameter([10, 15, 20, 25, 30, 35], default=30, optimize=optimize_buy_ema_length_1h)

    optimize_buy_volume = False
    buy_length_volume = IntParameter(5, 100, default=6, optimize=optimize_buy_volume)
    buy_volume_volatility = DecimalParameter(0.5, 3, default=1, decimals=2, optimize=optimize_buy_volume)

    optimize_buy_volume2 = False
    buy_length_volume2 = IntParameter(5, 100, default=6, optimize=optimize_buy_volume2)
    buy_volume_volatility2 = DecimalParameter(0.5, 3, default=1, decimals=2, optimize=optimize_buy_volume2)

    optimize_sell_ema = False
    base_nb_candles_sell_ema = IntParameter(5, 100, default=6, space="sell", optimize=optimize_sell_ema)
    high_offset_ema = DecimalParameter(1, 1.2, default=1, decimals=2, space="sell", optimize=optimize_sell_ema)

    optimize_sell_ema2 = False
    base_nb_candles_sell_ema2 = IntParameter(5, 100, default=6, space="sell", optimize=optimize_sell_ema2)
    high_offset_ema2 = DecimalParameter(0.9, 1.1, default=0.95, space="sell", optimize=optimize_sell_ema2)

    optimize_sell_ema3 = False
    base_nb_candles_sell_ema3 = IntParameter(5, 100, default=6, space="sell", optimize=optimize_sell_ema3)
    high_offset_ema3 = DecimalParameter(0.8, 0.99, default=0.95, space="sell", optimize=optimize_sell_ema3)

    optimize_sell_ema4 = False
    base_nb_candles_sell_ema4 = IntParameter(5, 100, default=6, space="sell", optimize=optimize_sell_ema4)
    high_offset_ema4 = DecimalParameter(0.8, 0.99, default=0.95, space="sell", optimize=optimize_sell_ema4)

    optimize_sell_ema5 = False
    base_nb_candles_sell_ema5 = IntParameter(5, 100, default=6, space="sell", optimize=optimize_sell_ema5)
    high_offset_ema5 = DecimalParameter(0.8, 0.99, default=0.95, space="sell", optimize=optimize_sell_ema5)

    optimize_sell_ema6 = False
    base_nb_candles_sell_ema6 = IntParameter(5, 100, default=6, space="sell", optimize=optimize_sell_ema6)
    high_offset_ema6 = DecimalParameter(0.8, 0.99, default=0.95, space="sell", optimize=optimize_sell_ema6)

    def informative_pairs(self):
        pairs = self.dp.current_whitelist()
        inf = []
        inf += [(pair, "1d") for pair in pairs]
        inf += [(pair, "1h") for pair in pairs]
        inf += [(pair, "15m") for pair in pairs]
        return inf

    def _merge_1d(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        inf_1d = self.dp.get_pair_dataframe(pair=metadata["pair"], timeframe="1d")
        if inf_1d is None or inf_1d.empty:
            dataframe["age_filter_ok_1d"] = False
            return dataframe

        inf_1d = ensure_datetime(inf_1d.copy())
        if inf_1d is None or inf_1d.empty:
            dataframe["age_filter_ok_1d"] = False
            return dataframe

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

        if "age_filter_ok_1d" not in dataframe.columns:
            dataframe["age_filter_ok_1d"] = False

        dataframe["age_filter_ok_1d"] = (
            dataframe["age_filter_ok_1d"]
            .astype("boolean")
            .fillna(False)
            .astype(bool)
        )

        return dataframe

    def _merge_1h(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        inf_1h = self.dp.get_pair_dataframe(pair=metadata["pair"], timeframe="1h")
        if inf_1h is None or inf_1h.empty:
            dataframe[f"ema_{self.buy_ema_fast_length_1h.value}_1h"] = np.nan
            dataframe[f"ema_{self.buy_ema_slow_length_1h.value}_1h"] = np.nan
            return dataframe

        inf_1h = ensure_datetime(inf_1h.copy())
        if inf_1h is None or inf_1h.empty:
            dataframe[f"ema_{self.buy_ema_fast_length_1h.value}_1h"] = np.nan
            dataframe[f"ema_{self.buy_ema_slow_length_1h.value}_1h"] = np.nan
            return dataframe

        if self.config["runmode"].value in ("hyperopt",) and self.optimize_buy_ema_length_1h:
            for val in self.length_ema_1h:
                inf_1h[f"ema_{val}"] = ta.EMA(inf_1h, timeperiod=int(val))
            cols = ["date"] + [f"ema_{val}" for val in self.length_ema_1h]
        else:
            fast = int(self.buy_ema_fast_length_1h.value)
            slow = int(self.buy_ema_slow_length_1h.value)
            inf_1h[f"ema_{fast}"] = ta.EMA(inf_1h, timeperiod=fast)
            inf_1h[f"ema_{slow}"] = ta.EMA(inf_1h, timeperiod=slow)
            cols = ["date", f"ema_{fast}", f"ema_{slow}"]

        return merge_informative_pair(dataframe, inf_1h[cols], self.timeframe, "1h", ffill=True)

    def _merge_15m(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        inf_15m = self.dp.get_pair_dataframe(pair=metadata["pair"], timeframe="15m")
        if inf_15m is None or inf_15m.empty:
            dataframe[f"ema_{self.buy_ema_fast_length_15m.value}_15m"] = np.nan
            dataframe[f"ema_{self.buy_ema_slow_length_15m.value}_15m"] = np.nan
            return dataframe

        inf_15m = ensure_datetime(inf_15m.copy())
        if inf_15m is None or inf_15m.empty:
            dataframe[f"ema_{self.buy_ema_fast_length_15m.value}_15m"] = np.nan
            dataframe[f"ema_{self.buy_ema_slow_length_15m.value}_15m"] = np.nan
            return dataframe

        if self.config["runmode"].value in ("hyperopt",) and self.optimize_buy_ema_length_15m:
            for val in self.length_ema_15m:
                inf_15m[f"ema_{val}"] = ta.EMA(inf_15m, timeperiod=int(val))
            cols = ["date"] + [f"ema_{val}" for val in self.length_ema_15m]
        else:
            fast = int(self.buy_ema_fast_length_15m.value)
            slow = int(self.buy_ema_slow_length_15m.value)
            inf_15m[f"ema_{fast}"] = ta.EMA(inf_15m, timeperiod=fast)
            inf_15m[f"ema_{slow}"] = ta.EMA(inf_15m, timeperiod=slow)
            cols = ["date", f"ema_{fast}", f"ema_{slow}"]

        return merge_informative_pair(dataframe, inf_15m[cols], self.timeframe, "15m", ffill=True)

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = dataframe.copy()
        dataframe = ensure_datetime(dataframe)

        dataframe = self._merge_1d(dataframe, metadata)
        dataframe = self._merge_1h(dataframe, metadata)
        dataframe = self._merge_15m(dataframe, metadata)

        heikinashi = qtpylib.heikinashi(dataframe)
        heikinashi["volume"] = dataframe["volume"]

        dataframe["pm"], _ = pmax(heikinashi, MAtype=1, length=9, multiplier=27, period=10, src=3)
        df_source = (dataframe["high"] + dataframe["low"] + dataframe["open"] + dataframe["close"]) / 4
        dataframe["pmax_thresh"] = ta.EMA(df_source, timeperiod=9)

        dataframe["rsx_14"] = pta.rsx(dataframe["close"], length=14)
        dataframe["rsx_4"] = pta.rsx(dataframe["close"], length=4)

        dataframe["live_data_ok"] = (dataframe["volume"].rolling(window=72, min_periods=72).min() > 0)

        if not self.optimize_buy_hma:
            dataframe["hma_offset_buy"] = tv_hma(dataframe, int(self.base_nb_candles_buy_hma.value)) * self.low_offset_hma.value

        if not self.optimize_buy_hma2:
            dataframe["hma_offset_buy2"] = tv_hma(dataframe, int(self.base_nb_candles_buy_hma2.value)) * self.low_offset_hma2.value

        if not self.optimize_buy_hma3:
            dataframe["hma_offset_buy3"] = tv_hma(dataframe, int(self.base_nb_candles_buy_hma3.value)) * self.low_offset_hma3.value

        if not self.optimize_buy_ema:
            dataframe["ema_offset_buy"] = ta.EMA(dataframe, int(self.base_nb_candles_buy_ema.value)) * self.low_offset_ema.value

        if not self.optimize_buy_ema_hma:
            dataframe["ema_offset_buy_hma"] = ta.EMA(dataframe, int(self.base_nb_candles_buy_ema_hma.value)) * self.low_offset_ema_hma.value

        if not self.optimize_buy_ema_2:
            dataframe["ema_offset_buy_2"] = ta.EMA(dataframe, int(self.base_nb_candles_buy_ema_2.value)) * self.low_offset_ema_2.value

        if not self.optimize_buy_ema2:
            dataframe["ema_offset_buy2"] = ta.EMA(dataframe, int(self.base_nb_candles_buy_ema2.value)) * self.low_offset_ema2.value

        if not self.optimize_buy_ema3:
            dataframe["ema_offset_buy3"] = ta.EMA(dataframe, int(self.base_nb_candles_buy_ema3.value)) * self.low_offset_ema3.value

        if not self.optimize_buy_volume:
            df_rvol = rvol(dataframe, int(self.buy_length_volume.value))
            dataframe["volume_volatility"] = df_rvol < self.buy_volume_volatility.value

        if not self.optimize_buy_volume2:
            df_rvol = rvol(dataframe, int(self.buy_length_volume2.value))
            dataframe["volume_volatility2"] = df_rvol < self.buy_volume_volatility2.value

        if not self.optimize_sell_ema:
            dataframe["ema_offset_sell"] = ta.EMA(dataframe, int(self.base_nb_candles_sell_ema.value)) * self.high_offset_ema.value

        if not self.optimize_sell_ema2:
            dataframe["ema_offset_sell2"] = ta.EMA(dataframe, int(self.base_nb_candles_sell_ema2.value)) * self.high_offset_ema2.value

        if not self.optimize_sell_ema3:
            dataframe["ema_offset_sell3"] = ta.EMA(dataframe, int(self.base_nb_candles_sell_ema3.value)) * self.high_offset_ema3.value

        if not self.optimize_sell_ema4:
            dataframe["ema_offset_sell4"] = ta.EMA(dataframe, int(self.base_nb_candles_sell_ema4.value)) * self.high_offset_ema4.value

        if not self.optimize_sell_ema5:
            dataframe["ema_offset_sell5"] = ta.EMA(dataframe, int(self.base_nb_candles_sell_ema5.value)) * self.high_offset_ema5.value

        if not self.optimize_sell_ema6:
            dataframe["ema_offset_sell6"] = ta.EMA(dataframe, int(self.base_nb_candles_sell_ema6.value)) * self.high_offset_ema6.value

        dataframe["pm"] = Series(dataframe["pm"], index=dataframe.index, dtype="float64").fillna(0.0)
        dataframe["pmax_thresh"] = Series(dataframe["pmax_thresh"], index=dataframe.index, dtype="float64").fillna(0.0)
        dataframe["age_filter_ok_1d"] = dataframe["age_filter_ok_1d"].fillna(False).astype(bool)

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        conditions = []

        if self.optimize_buy_hma:
            dataframe["hma_offset_buy"] = tv_hma(dataframe, int(self.base_nb_candles_buy_hma.value)) * self.low_offset_hma.value

        if self.optimize_buy_hma2:
            dataframe["hma_offset_buy2"] = tv_hma(dataframe, int(self.base_nb_candles_buy_hma2.value)) * self.low_offset_hma2.value

        if self.optimize_buy_hma3:
            dataframe["hma_offset_buy3"] = tv_hma(dataframe, int(self.base_nb_candles_buy_hma3.value)) * self.low_offset_hma3.value

        if self.optimize_buy_ema:
            dataframe["ema_offset_buy"] = ta.EMA(dataframe, int(self.base_nb_candles_buy_ema.value)) * self.low_offset_ema.value

        if self.optimize_buy_ema_hma:
            dataframe["ema_offset_buy_hma"] = ta.EMA(dataframe, int(self.base_nb_candles_buy_ema_hma.value)) * self.low_offset_ema_hma.value

        if self.optimize_buy_ema_2:
            dataframe["ema_offset_buy_2"] = ta.EMA(dataframe, int(self.base_nb_candles_buy_ema_2.value)) * self.low_offset_ema_2.value

        if self.optimize_buy_ema2:
            dataframe["ema_offset_buy2"] = ta.EMA(dataframe, int(self.base_nb_candles_buy_ema2.value)) * self.low_offset_ema2.value

        if self.optimize_buy_ema3:
            dataframe["ema_offset_buy3"] = ta.EMA(dataframe, int(self.base_nb_candles_buy_ema3.value)) * self.low_offset_ema3.value

        if self.optimize_buy_volume:
            df_rvol = rvol(dataframe, int(self.buy_length_volume.value))
            dataframe["volume_volatility"] = df_rvol < self.buy_volume_volatility.value

        if self.optimize_buy_volume2:
            df_rvol = rvol(dataframe, int(self.buy_length_volume2.value))
            dataframe["volume_volatility2"] = df_rvol < self.buy_volume_volatility2.value

        dataframe.loc[:, "enter_tag"] = ""
        dataframe.loc[:, "enter_long"] = 0

        fast_1h = int(self.buy_ema_fast_length_1h.value)
        slow_1h = int(self.buy_ema_slow_length_1h.value)
        fast_15m = int(self.buy_ema_fast_length_15m.value)
        slow_15m = int(self.buy_ema_slow_length_15m.value)

        col_fast_1h = f"ema_{fast_1h}_1h"
        col_slow_1h = f"ema_{slow_1h}_1h"
        col_fast_15m = f"ema_{fast_15m}_15m"
        col_slow_15m = f"ema_{slow_15m}_15m"

        if col_fast_1h not in dataframe.columns:
            dataframe[col_fast_1h] = np.nan
        if col_slow_1h not in dataframe.columns:
            dataframe[col_slow_1h] = np.nan
        if col_fast_15m not in dataframe.columns:
            dataframe[col_fast_15m] = np.nan
        if col_slow_15m not in dataframe.columns:
            dataframe[col_slow_15m] = np.nan

        go_long_1h = (
            ((fast_1h < slow_1h) & (dataframe[col_fast_1h] > dataframe[col_slow_1h]))
            .astype(int) * 2
        )

        go_long_15m = (
            ((fast_15m < slow_15m) & (dataframe[col_fast_15m] > dataframe[col_slow_15m]))
            .astype(int) * 2
        )

        add_check = (
            dataframe["live_data_ok"]
            &
            dataframe["age_filter_ok_1d"]
            &
            (dataframe["open"] > dataframe["close"])
            &
            (go_long_1h > 0)
            &
            (go_long_15m > 0)
            &
            (
                (
                    (dataframe["close"] < dataframe["ema_offset_buy"])
                    &
                    (dataframe["pm"] <= dataframe["pmax_thresh"])
                    &
                    (dataframe["rsx_14"] < self.buy_rsx_1.value)
                    &
                    (dataframe["rsx_4"] < self.buy_rsx_fast_1.value)
                    &
                    dataframe["volume_volatility"]
                )
                |
                (
                    (dataframe["close"] < dataframe["ema_offset_buy_2"])
                    &
                    (dataframe["pm"] > dataframe["pmax_thresh"])
                    &
                    (dataframe["rsx_14"] < self.buy_rsx_2.value)
                    &
                    (dataframe["rsx_4"] < self.buy_rsx_fast_2.value)
                    &
                    dataframe["volume_volatility2"]
                )
            )
        )

        buy_offset_hma = (
            (dataframe["close"] < dataframe["hma_offset_buy"])
            &
            (dataframe["pm"] <= dataframe["pmax_thresh"])
            &
            (dataframe["rsx_14"] < self.buy_rsx_hma.value)
            &
            (dataframe["rsx_4"] < self.buy_rsx_fast_hma.value)
            &
            (dataframe["close"] < dataframe["ema_offset_buy_hma"])
        )
        dataframe.loc[buy_offset_hma, "enter_tag"] += "hma "
        conditions.append(buy_offset_hma)

        buy_offset_hma2 = (
            (dataframe["close"] < dataframe["hma_offset_buy2"])
            &
            (dataframe["pm"] > dataframe["pmax_thresh"])
        )
        dataframe.loc[buy_offset_hma2, "enter_tag"] += "hma_2 "
        conditions.append(buy_offset_hma2)

        buy_offset_hma3 = (
            ((dataframe["close"] < dataframe["hma_offset_buy3"]).rolling(2).min() > 0)
            &
            (dataframe["pm"] <= dataframe["pmax_thresh"])
        )
        dataframe.loc[buy_offset_hma3, "enter_tag"] += "hma_3 "
        conditions.append(buy_offset_hma3)

        buy_offset_ema2 = (
            ((dataframe["close"] < dataframe["ema_offset_buy2"]).rolling(2).min() > 0)
            &
            (dataframe["pm"] <= dataframe["pmax_thresh"])
        )
        dataframe.loc[buy_offset_ema2, "enter_tag"] += "ema_2 "
        conditions.append(buy_offset_ema2)

        buy_offset_ema3 = (
            ((dataframe["close"] < dataframe["ema_offset_buy3"]).rolling(3).min() > 0)
            &
            (dataframe["pm"] <= dataframe["pmax_thresh"])
        )
        dataframe.loc[buy_offset_ema3, "enter_tag"] += "ema_3 "
        conditions.append(buy_offset_ema3)

        if conditions:
            dataframe.loc[
                reduce(lambda x, y: x | y, conditions) & add_check,
                "enter_long",
            ] = 1

            dataframe.loc[
                buy_offset_hma
                &
                buy_offset_ema2
                &
                np.invert(buy_offset_hma3),
                "enter_long",
            ] = 0

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        if self.optimize_sell_ema:
            dataframe["ema_offset_sell"] = ta.EMA(dataframe, int(self.base_nb_candles_sell_ema.value)) * self.high_offset_ema.value

        if self.optimize_sell_ema2:
            dataframe["ema_offset_sell2"] = ta.EMA(dataframe, int(self.base_nb_candles_sell_ema2.value)) * self.high_offset_ema2.value

        if self.optimize_sell_ema3:
            dataframe["ema_offset_sell3"] = ta.EMA(dataframe, int(self.base_nb_candles_sell_ema3.value)) * self.high_offset_ema3.value

        if self.optimize_sell_ema4:
            dataframe["ema_offset_sell4"] = ta.EMA(dataframe, int(self.base_nb_candles_sell_ema4.value)) * self.high_offset_ema4.value

        if self.optimize_sell_ema5:
            dataframe["ema_offset_sell5"] = ta.EMA(dataframe, int(self.base_nb_candles_sell_ema5.value)) * self.high_offset_ema5.value

        if self.optimize_sell_ema6:
            dataframe["ema_offset_sell6"] = ta.EMA(dataframe, int(self.base_nb_candles_sell_ema6.value)) * self.high_offset_ema6.value

        dataframe.loc[:, "exit_tag"] = ""
        dataframe.loc[:, "exit_long"] = 0
        conditions = []

        sell_ema_1 = (
            (dataframe["close"] > dataframe["ema_offset_sell"])
            &
            (dataframe["pm"] <= dataframe["pmax_thresh"])
        )
        conditions.append(sell_ema_1)
        dataframe.loc[sell_ema_1, "exit_tag"] += "EMA_1 "

        sell_ema_2 = (
            (dataframe["close"] > dataframe["ema_offset_sell2"])
            &
            (dataframe["pm"] > dataframe["pmax_thresh"])
        )
        conditions.append(sell_ema_2)
        dataframe.loc[sell_ema_2, "exit_tag"] += "EMA_2 "

        sell_ema_3 = (
            (dataframe["close"] < dataframe["ema_offset_sell3"])
            &
            (dataframe["pm"] <= dataframe["pmax_thresh"])
        )
        conditions.append(sell_ema_3)
        dataframe.loc[sell_ema_3, "exit_tag"] += "EMA_3 "

        sell_ema_4 = (
            (dataframe["close"] < dataframe["ema_offset_sell4"])
            &
            (dataframe["pm"] > dataframe["pmax_thresh"])
        )
        conditions.append(sell_ema_4)
        dataframe.loc[sell_ema_4, "exit_tag"] += "EMA_4 "

        add_check = (dataframe["volume"] > 0)

        sell_ema_5 = (
            ((dataframe["close"] < dataframe["ema_offset_sell5"]).rolling(2).min() > 0)
            &
            (dataframe["pm"] <= dataframe["pmax_thresh"])
        )
        conditions.append(sell_ema_5)
        dataframe.loc[sell_ema_5, "exit_tag"] += "EMA_5 "

        sell_ema_6 = (
            ((dataframe["close"] < dataframe["ema_offset_sell6"]).rolling(2).min() > 0)
            &
            (dataframe["pm"] > dataframe["pmax_thresh"])
        )
        conditions.append(sell_ema_6)
        dataframe.loc[sell_ema_6, "exit_tag"] += "EMA_6 "

        if conditions:
            dataframe.loc[
                reduce(lambda x, y: x | y, conditions) & add_check,
                "exit_long",
            ] = 1

        return dataframe