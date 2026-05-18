# --- Do not remove these libs ---
import warnings
from functools import reduce
from datetime import datetime

import freqtrade.vendor.qtpylib.indicators as qtpylib
import numpy as np
import pandas_ta as pta
import talib.abstract as ta

from freqtrade.persistence import Trade
from freqtrade.strategy import (
    CategoricalParameter,
    DecimalParameter,
    IntParameter,
    merge_informative_pair,
    stoploss_from_open,
)
from freqtrade.strategy.interface import IStrategy
from pandas import DataFrame, Series
from technical.indicators import RMI, zema, ichimoku

warnings.filterwarnings("ignore", category=FutureWarning)


############################################################################
# Custom indicators and helper functions
############################################################################
def ha_typical_price(bars: DataFrame) -> Series:
    res = (bars["ha_high"] + bars["ha_low"] + bars["ha_close"]) / 3.0
    return Series(index=bars.index, data=res)


def vwma(dataframe: DataFrame, length: int = 10) -> Series:
    """Volume Weighted Moving Average"""
    pv = dataframe["close"] * dataframe["volume"]
    vol_sma = ta.SMA(dataframe["volume"], timeperiod=length)
    pv_sma = ta.SMA(pv, timeperiod=length)
    return Series(pv_sma / vol_sma, index=dataframe.index)


def moderi(dataframe: DataFrame, len_slow_ma: int = 32) -> Series:
    slow_ma = Series(ta.EMA(vwma(dataframe, length=len_slow_ma), timeperiod=len_slow_ma), index=dataframe.index)
    return slow_ma >= slow_ma.shift(1)


def EWO(dataframe: DataFrame, ema_length: int = 5, ema2_length: int = 35) -> Series:
    ema1 = ta.EMA(dataframe, timeperiod=ema_length)
    ema2 = ta.EMA(dataframe, timeperiod=ema2_length)
    emadif = (ema1 - ema2) / dataframe["low"] * 100
    return Series(emadif, index=dataframe.index)


def SROC(dataframe: DataFrame, roclen: int = 21, emalen: int = 13, smooth: int = 21) -> Series:
    roc = ta.ROC(dataframe, timeperiod=roclen)
    ema = ta.EMA(dataframe, timeperiod=emalen)
    sroc = ta.ROC(ema, timeperiod=smooth)
    return Series(sroc, index=dataframe.index)


########################################################################################################################################################
# Percent Changes
########################################################################################################################################################
def range_percent_change(dataframe: DataFrame, method: str, length: int) -> Series:
    """
    Rolling Percentage Change Maximum across interval.
    :param dataframe: OHLC dataframe
    :param method: 'HL' High to Low / 'OC' Open to Close
    :param length: lookback length
    """
    if method == "HL":
        return (
            (dataframe["high"].rolling(length).max() - dataframe["low"].rolling(length).min())
            / dataframe["low"].rolling(length).min()
        )
    elif method == "OC":
        return (
            (dataframe["open"].rolling(length).max() - dataframe["close"].rolling(length).min())
            / dataframe["close"].rolling(length).min()
        )
    else:
        raise ValueError(f"Method {method} not defined!")


########################################################################################################################################################
# Williams %R
########################################################################################################################################################
def williams_r(dataframe: DataFrame, period: int = 14) -> Series:
    highest_high = dataframe["high"].rolling(center=False, window=period).max()
    lowest_low = dataframe["low"].rolling(center=False, window=period).min()

    wr = Series(
        (highest_high - dataframe["close"]) / (highest_high - lowest_low),
        name=f"{period} Williams %R",
        index=dataframe.index,
    )

    return wr * -100


########################################################################################################################################################
# Chaikin Money Flow
########################################################################################################################################################
def chaikin_money_flow(dataframe: DataFrame, n: int = 20, fillna: bool = False) -> Series:
    mfv = (
        ((dataframe["close"] - dataframe["low"]) - (dataframe["high"] - dataframe["close"]))
        / (dataframe["high"] - dataframe["low"])
    )
    mfv = mfv.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    mfv *= dataframe["volume"]

    cmf = mfv.rolling(n, min_periods=0).sum() / dataframe["volume"].rolling(n, min_periods=0).sum()

    if fillna:
        cmf = cmf.replace([np.inf, -np.inf], np.nan).fillna(0)

    return Series(cmf, name="cmf", index=dataframe.index)


########################################################################################################################################################
# PMAX
########################################################################################################################################################
def pmax(df: DataFrame, period: int, multiplier: int, length: int, MAtype: int, src: int):
    """
    Safe NumPy 2.x compatible PMAX implementation.
    Returns:
        pm  : Series[float]
        pmx : Series[object] with 'up' / 'down' / None
    """
    period = int(period)
    multiplier = int(multiplier)
    length = int(length)
    MAtype = int(MAtype)
    src = int(src)

    if src == 1:
        masrc = df["close"]
    elif src == 2:
        masrc = (df["high"] + df["low"]) / 2
    elif src == 3:
        masrc = (df["high"] + df["low"] + df["close"] + df["open"]) / 4
    else:
        raise ValueError(f"Unsupported src: {src}")

    # MAtype:
    # 1 EMA
    # 2 DEMA
    # 3 T3
    # 4 SMA
    # 5 VIDYA
    # 6 TEMA
    # 7 WMA
    # 8 VWMA
    # 9 zema
    if MAtype == 1:
        mavalue = ta.EMA(masrc, timeperiod=length)
    elif MAtype == 2:
        mavalue = ta.DEMA(masrc, timeperiod=length)
    elif MAtype == 3:
        mavalue = ta.T3(masrc, timeperiod=length)
    elif MAtype == 4:
        mavalue = ta.SMA(masrc, timeperiod=length)
    elif MAtype == 5:
        raise NotImplementedError("VIDYA branch is not implemented in this strategy.")
    elif MAtype == 6:
        mavalue = ta.TEMA(masrc, timeperiod=length)
    elif MAtype == 7:
        mavalue = ta.WMA(masrc, timeperiod=length)
    elif MAtype == 8:
        mavalue = vwma(df, length)
    elif MAtype == 9:
        mavalue = zema(df, period=length)
    else:
        raise ValueError(f"Unsupported MAtype: {MAtype}")

    atr = ta.ATR(df, timeperiod=period)

    basic_ub = mavalue + ((multiplier / 10.0) * atr)
    basic_lb = mavalue - ((multiplier / 10.0) * atr)

    basic_ub_np = Series(basic_ub, index=df.index).to_numpy(dtype=float)
    basic_lb_np = Series(basic_lb, index=df.index).to_numpy(dtype=float)
    mavalue_np = Series(mavalue, index=df.index).to_numpy(dtype=float)

    final_ub = np.zeros(len(df), dtype=float)
    final_lb = np.zeros(len(df), dtype=float)

    for i in range(period, len(df)):
        final_ub[i] = (
            basic_ub_np[i]
            if (basic_ub_np[i] < final_ub[i - 1] or mavalue_np[i - 1] > final_ub[i - 1])
            else final_ub[i - 1]
        )
        final_lb[i] = (
            basic_lb_np[i]
            if (basic_lb_np[i] > final_lb[i - 1] or mavalue_np[i - 1] < final_lb[i - 1])
            else final_lb[i - 1]
        )

    pm_arr = np.zeros(len(df), dtype=float)

    for i in range(period, len(df)):
        if pm_arr[i - 1] == final_ub[i - 1]:
            pm_arr[i] = final_ub[i] if mavalue_np[i] <= final_ub[i] else final_lb[i]
        elif pm_arr[i - 1] == final_lb[i - 1]:
            pm_arr[i] = final_lb[i] if mavalue_np[i] >= final_lb[i] else final_ub[i]
        else:
            pm_arr[i] = 0.0

    pm = Series(pm_arr, index=df.index)

    pmx_arr = np.full(len(df), None, dtype=object)
    up_mask = (pm_arr > 0.0) & (mavalue_np >= pm_arr)
    down_mask = (pm_arr > 0.0) & (mavalue_np < pm_arr)
    pmx_arr[up_mask] = "up"
    pmx_arr[down_mask] = "down"

    pmx = Series(pmx_arr, index=df.index)

    return pm, pmx


########################################################################################################################################################
# Mom DIV
########################################################################################################################################################
def momdiv(
    dataframe: DataFrame,
    mom_length: int = 10,
    bb_length: int = 20,
    bb_dev: float = 2.0,
    lookback: int = 30,
) -> DataFrame:
    mom: Series = ta.MOM(dataframe, timeperiod=mom_length)
    upperband, middleband, lowerband = ta.BBANDS(
        mom, timeperiod=bb_length, nbdevup=bb_dev, nbdevdn=bb_dev, matype=0
    )
    buy = qtpylib.crossed_below(mom, lowerband)
    sell = qtpylib.crossed_above(mom, upperband)
    hh = dataframe["high"].rolling(lookback).max()
    ll = dataframe["low"].rolling(lookback).min()
    coh = dataframe["high"] >= hh
    col = dataframe["low"] <= ll

    return DataFrame(
        {
            "momdiv_mom": mom,
            "momdiv_upperb": upperband,
            "momdiv_lowerb": lowerband,
            "momdiv_buy": buy,
            "momdiv_sell": sell,
            "momdiv_coh": coh,
            "momdiv_col": col,
        },
        index=dataframe.index,
    )


########################################################################################################################################################
# T3
########################################################################################################################################################
def T3(dataframe: DataFrame, length: int = 5) -> Series:
    """
    T3 Average by HPotter on Tradingview
    """
    df = dataframe.copy()

    df["xe1"] = ta.EMA(df["close"], timeperiod=length)
    df["xe2"] = ta.EMA(df["xe1"], timeperiod=length)
    df["xe3"] = ta.EMA(df["xe2"], timeperiod=length)
    df["xe4"] = ta.EMA(df["xe3"], timeperiod=length)
    df["xe5"] = ta.EMA(df["xe4"], timeperiod=length)
    df["xe6"] = ta.EMA(df["xe5"], timeperiod=length)

    b = 0.7
    c1 = -(b**3)
    c2 = 3 * b * b + 3 * (b**3)
    c3 = -6 * b * b - 3 * b - 3 * (b**3)
    c4 = 1 + 3 * b + (b**3) + 3 * b * b

    df["T3Average"] = c1 * df["xe6"] + c2 * df["xe5"] + c3 * df["xe4"] + c4 * df["xe3"]
    return df["T3Average"]


########################################################################################################################################################
'''
    BB_RPB_TSL
    @author jilv220
    Simple bollinger brand strategy inspired by this blog
    RPB, Real Pull Back
    The trailing custom stoploss taken from BigZ04_TSL from Perkmeister (modded by ilya)
'''
########################################################################################################################################################
class DS_Gusta_5m(IStrategy):
    INTERFACE_VERSION = 3

########################################################################################################################################################
# Hyperopt
########################################################################################################################################################
    buy_params = {
        "max_slip": 0.983,
        "buy_bb_width_1h": 0.954,
        "buy_roc_1h": 86,
        "buy_threshold": 0.003,
        "buy_bb_factor": 0.999,
        "buy_bb_delta": 0.025,
        "buy_bb_width": 0.095,
        "buy_cci": -116,
        "buy_cci_length": 25,
        "buy_rmi": 49,
        "buy_rmi_length": 17,
        "buy_srsi_fk": 32,
        "buy_closedelta": 17.922,
        "buy_ema_diff": 0.026,
        "buy_ema_high": 0.968,
        "buy_ema_low": 0.935,
        "buy_ewo": -5.001,
        "buy_rsi": 23,
        "buy_rsi_fast": 44,
        "buy_ema_high_2": 1.087,
        "buy_ema_low_2": 0.970,
        "buy_ewo_high_2": 4.179,
        "buy_rsi_ewo_2": 35,
        "buy_rsi_fast_ewo_2": 45,
        "buy_r_deadfish_bb_factor": 1.014,
        "buy_r_deadfish_bb_width": 0.299,
        "buy_r_deadfish_ema": 1.054,
        "buy_r_deadfish_volume_factor": 1.59,
        "buy_r_deadfish_cti": -0.115,
        "buy_r_deadfish_r14": -44.34,
        "buy_clucha_bbdelta_close": 0.049,
        "buy_clucha_bbdelta_tail": 1.146,
        "buy_clucha_close_bblower": 0.018,
        "buy_clucha_closedelta_close": 0.017,
        "buy_clucha_rocr_1h": 0.526,
        "buy_adx": 13,
        "buy_ewo_high": 8.594,
        "buy_fastd": 28,
        "buy_fastk": 39,
        "buy_gumbo_ema": 1.121,
        "buy_gumbo_ewo_low": -9.442,
        "buy_gumbo_cti": -0.374,
        "buy_gumbo_r14": -51.971,
        "buy_sqzmom_ema": 0.981,
        "buy_sqzmom_ewo": -3.966,
        "buy_sqzmom_r14": -45.068,
        "buy_nfix_49_cti": -0.105,
        "buy_nfix_49_r14": -81.827,
    }

    sell_params = {
        "sell_cmf": -0.046,
        "sell_ema": 0.988,
        "sell_ema_close_delta": 0.022,
        "sell_deadfish_profit": -0.063,
        "sell_deadfish_bb_factor": 0.954,
        "sell_deadfish_bb_width": 0.043,
        "sell_deadfish_volume_factor": 2.37,
        "sell_cti_r_cti": 0.844,
        "sell_cti_r_r": -19.99,
    }

    minimal_roi = {
        "0": 0.205,
        "81": 0.038,
        "292": 0.005,
    }

    stoploss = -0.99
    trailing_stop = False
    trailing_stop_positive = 0.001
    trailing_stop_positive_offset = 0.0135
    trailing_only_offset_is_reached = False
    use_custom_stoploss = True

########################################################################################################################################################
# Main
########################################################################################################################################################
    timeframe = "5m"
    inf_1h = "1h"
    process_only_new_candles = True
    startup_candle_count = 800

    use_exit_signal = True
    exit_profit_only = False
    exit_profit_offset = 0.01
    ignore_roi_if_entry_signal = False

    order_types = {
        "entry": "market",
        "exit": "market",
        "emergency_exit": "market",
        "force_entry": "market",
        "force_exit": "market",
        "stoploss": "market",
        "stoploss_on_exchange": False,
        "stoploss_on_exchange_interval": 60,
        "stoploss_on_exchange_limit_ratio": 0.99,
    }

    order_time_in_force = {
        "entry": "gtc",
        "exit": "gtc",
    }

    plot_config = {
        "main_plot": {
            "ma_buy": {"color": "orange"},
            "ma_sell": {"color": "orange"},
        },
    }

########################################################################################################################################################
# Parameters
########################################################################################################################################################
    is_optimize_dip = False
    buy_rmi = IntParameter(30, 50, default=35, optimize=is_optimize_dip)
    buy_cci = IntParameter(-135, -90, default=-133, optimize=is_optimize_dip)
    buy_srsi_fk = IntParameter(30, 50, default=25, optimize=is_optimize_dip)
    buy_cci_length = IntParameter(25, 45, default=25, optimize=is_optimize_dip)
    buy_rmi_length = IntParameter(8, 20, default=8, optimize=is_optimize_dip)

    is_optimize_break = False
    buy_bb_width = DecimalParameter(0.065, 0.135, default=0.095, optimize=is_optimize_break)
    buy_bb_delta = DecimalParameter(0.018, 0.035, default=0.025, optimize=is_optimize_break)

    is_optimize_local_uptrend = False
    buy_ema_diff = DecimalParameter(0.022, 0.027, default=0.025, optimize=is_optimize_local_uptrend)
    buy_bb_factor = DecimalParameter(0.990, 0.999, default=0.995, optimize=False)
    buy_closedelta = DecimalParameter(12.0, 18.0, default=15.0, optimize=is_optimize_local_uptrend)

    is_optimize_ewo = False
    buy_rsi_fast = IntParameter(35, 50, default=45, optimize=is_optimize_ewo)
    buy_rsi = IntParameter(15, 35, default=35, optimize=is_optimize_ewo)
    buy_ewo = DecimalParameter(-6.0, 5, default=-5.585, optimize=is_optimize_ewo)
    buy_ema_low = DecimalParameter(0.9, 0.99, default=0.942, optimize=is_optimize_ewo)
    buy_ema_high = DecimalParameter(0.95, 1.2, default=1.084, optimize=is_optimize_ewo)

    is_optimize_ewo_2 = False
    buy_rsi_fast_ewo_2 = IntParameter(15, 50, default=45, optimize=is_optimize_ewo_2)
    buy_rsi_ewo_2 = IntParameter(15, 50, default=35, optimize=is_optimize_ewo_2)
    buy_ema_low_2 = DecimalParameter(0.90, 1.2, default=0.970, optimize=is_optimize_ewo_2)
    buy_ema_high_2 = DecimalParameter(0.90, 1.2, default=1.087, optimize=is_optimize_ewo_2)
    buy_ewo_high_2 = DecimalParameter(2, 12, default=4.179, optimize=is_optimize_ewo_2)

    is_optimize_r_deadfish = False
    buy_r_deadfish_ema = DecimalParameter(0.90, 1.2, default=1.087, optimize=is_optimize_r_deadfish)
    buy_r_deadfish_bb_width = DecimalParameter(0.03, 0.75, default=0.05, optimize=is_optimize_r_deadfish)
    buy_r_deadfish_bb_factor = DecimalParameter(0.90, 1.2, default=1.0, optimize=is_optimize_r_deadfish)
    buy_r_deadfish_volume_factor = DecimalParameter(1, 2.5, default=1.0, optimize=is_optimize_r_deadfish)

    is_optimize_r_deadfish_protection = False
    buy_r_deadfish_cti = DecimalParameter(-0.6, -0.0, default=-0.5, optimize=is_optimize_r_deadfish_protection)
    buy_r_deadfish_r14 = DecimalParameter(-60, -44, default=-60, optimize=is_optimize_r_deadfish_protection)

    is_optimize_clucha = False
    buy_clucha_bbdelta_close = DecimalParameter(0.01, 0.05, default=0.02206, optimize=is_optimize_clucha)
    buy_clucha_bbdelta_tail = DecimalParameter(0.7, 1.2, default=1.02515, optimize=is_optimize_clucha)
    buy_clucha_closedelta_close = DecimalParameter(0.001, 0.05, default=0.04401, optimize=is_optimize_clucha)
    buy_clucha_rocr_1h = DecimalParameter(0.1, 1.0, default=0.47782, optimize=is_optimize_clucha)

    is_optimize_gumbo = False
    buy_gumbo_ema = DecimalParameter(0.9, 1.2, default=0.97, optimize=is_optimize_gumbo)
    buy_gumbo_ewo_low = DecimalParameter(-12.0, 5, default=-5.585, optimize=is_optimize_gumbo)

    is_optimize_gumbo_protection = False
    buy_gumbo_cti = DecimalParameter(-0.9, -0.0, default=-0.5, optimize=is_optimize_gumbo_protection)
    buy_gumbo_r14 = DecimalParameter(-100, -44, default=-60, optimize=is_optimize_gumbo_protection)

    is_optimize_sqzmom_protection = False
    buy_sqzmom_ema = DecimalParameter(0.9, 1.2, default=0.97, optimize=is_optimize_sqzmom_protection)
    buy_sqzmom_ewo = DecimalParameter(-12, 12, default=0, optimize=is_optimize_sqzmom_protection)
    buy_sqzmom_r14 = DecimalParameter(-100, -22, default=-50, optimize=is_optimize_sqzmom_protection)

    is_optimize_nfix_49_protection = False
    buy_nfix_49_cti = DecimalParameter(-0.9, -0.0, default=-0.5, optimize=is_optimize_nfix_49_protection)
    buy_nfix_49_r14 = DecimalParameter(-100, -44, default=-60, optimize=is_optimize_nfix_49_protection)

    is_optimize_btc_safe = False
    buy_btc_safe = IntParameter(-300, 50, default=-200, optimize=is_optimize_btc_safe)
    buy_btc_safe_1d = DecimalParameter(-0.075, -0.025, default=-0.05, optimize=is_optimize_btc_safe)
    buy_threshold = DecimalParameter(0.003, 0.012, default=0.008, optimize=is_optimize_btc_safe)

    is_optimize_check = False
    buy_roc_1h = IntParameter(-25, 200, default=10, optimize=is_optimize_check)
    buy_bb_width_1h = DecimalParameter(0.3, 2.0, default=0.3, optimize=is_optimize_check)

    is_optimize_slip = False
    max_slip = DecimalParameter(0.33, 1.00, default=0.33, decimals=3, optimize=is_optimize_slip, space="buy", load=True)

    sell_btc_safe = IntParameter(-400, -300, default=-365, optimize=False)

    is_optimize_sell_stoploss = False
    sell_cmf = DecimalParameter(-0.4, 0.0, default=0.0, optimize=is_optimize_sell_stoploss)
    sell_ema_close_delta = DecimalParameter(0.022, 0.027, default=0.024, optimize=is_optimize_sell_stoploss)
    sell_ema = DecimalParameter(0.97, 0.99, default=0.987, optimize=is_optimize_sell_stoploss)

    is_optimize_deadfish = False
    sell_deadfish_bb_width = DecimalParameter(0.03, 0.75, default=0.05, optimize=is_optimize_deadfish)
    sell_deadfish_profit = DecimalParameter(-0.15, -0.05, default=-0.05, optimize=is_optimize_deadfish)
    sell_deadfish_bb_factor = DecimalParameter(0.90, 1.20, default=1.0, optimize=is_optimize_deadfish)
    sell_deadfish_volume_factor = DecimalParameter(1, 2.5, default=1.0, optimize=is_optimize_deadfish)

    is_optimize_bleeding = False
    sell_bleeding_cti = DecimalParameter(-0.9, -0.0, default=-0.5, optimize=is_optimize_bleeding)
    sell_bleeding_r14 = DecimalParameter(-100, -44, default=-60, optimize=is_optimize_bleeding)
    sell_bleeding_volume_factor = DecimalParameter(1, 2.5, default=1.0, optimize=is_optimize_bleeding)

    is_optimize_cti_r = False
    sell_cti_r_cti = DecimalParameter(0.55, 1, default=0.5, optimize=is_optimize_cti_r)
    sell_cti_r_r = DecimalParameter(-15, 0, default=-20, optimize=is_optimize_cti_r)

########################################################################################################################################################
########################################################################################################################################################
# Informative 1h
########################################################################################################################################################
    def informative_1h_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        assert self.dp, "DataProvider is required for multiple timeframes."

        informative_1h = self.dp.get_pair_dataframe(pair=metadata["pair"], timeframe=self.inf_1h)

        # hard guard for missing 1h data
        if informative_1h is None or informative_1h.empty:
            return DataFrame()

        informative_1h = informative_1h.copy()

        informative_1h["ema_8"] = ta.EMA(informative_1h, timeperiod=8)
        informative_1h["ema_50"] = ta.EMA(informative_1h, timeperiod=50)
        informative_1h["ema_100"] = ta.EMA(informative_1h, timeperiod=100)
        informative_1h["ema_200"] = ta.EMA(informative_1h, timeperiod=200)

        informative_1h["cti"] = pta.cti(informative_1h["close"], length=20)
        informative_1h["cti_40"] = pta.cti(informative_1h["close"], length=40)

        crsi_closechange = informative_1h["close"] / informative_1h["close"].shift(1)
        crsi_updown = np.where(
            crsi_closechange.gt(1), 1.0,
            np.where(crsi_closechange.lt(1), -1.0, 0.0)
        )
        informative_1h["crsi"] = (
            ta.RSI(informative_1h["close"], timeperiod=3)
            + ta.RSI(crsi_updown, timeperiod=2)
            + ta.ROC(informative_1h["close"], 100)
        ) / 3

        informative_1h["r_96"] = williams_r(informative_1h, period=96)
        informative_1h["r_480"] = williams_r(informative_1h, period=480)

        bollinger2 = qtpylib.bollinger_bands(
            qtpylib.typical_price(informative_1h), window=20, stds=2
        )
        informative_1h["bb_lowerband2"] = bollinger2["lower"]
        informative_1h["bb_middleband2"] = bollinger2["mid"]
        informative_1h["bb_upperband2"] = bollinger2["upper"]
        informative_1h["bb_width"] = (
            (informative_1h["bb_upperband2"] - informative_1h["bb_lowerband2"])
            / informative_1h["bb_middleband2"]
        )

        informative_1h["roc"] = ta.ROC(informative_1h, timeperiod=9)

        mom = momdiv(informative_1h)
        informative_1h["momdiv_buy"] = mom["momdiv_buy"]
        informative_1h["momdiv_sell"] = mom["momdiv_sell"]
        informative_1h["momdiv_coh"] = mom["momdiv_coh"]
        informative_1h["momdiv_col"] = mom["momdiv_col"]

        informative_1h["rsi"] = ta.RSI(informative_1h, timeperiod=14)
        informative_1h["cmf"] = chaikin_money_flow(informative_1h, 20)

        # only compute HA when informative dataframe is non-empty
        inf_heikinashi = qtpylib.heikinashi(informative_1h)
        informative_1h["ha_close"] = inf_heikinashi["close"]
        informative_1h["rocr"] = ta.ROCR(informative_1h["ha_close"], timeperiod=168)

        informative_1h["T3"] = T3(informative_1h)
        informative_1h["EWO"] = EWO(informative_1h, 50, 200)

        informative_1h["hl_pct_change_5"] = range_percent_change(informative_1h, "HL", 5)
        informative_1h["low_5"] = informative_1h["low"].shift().rolling(5).min()
        informative_1h["safe_dump_50"] = (
            (informative_1h["hl_pct_change_5"] < 0.66)
            | (informative_1h["close"] < informative_1h["low_5"])
            | (informative_1h["close"] > informative_1h["open"])
        )

        return informative_1h

########################################################################################################################################################
# Indicators
########################################################################################################################################################
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        informative_1h = self.informative_1h_indicators(dataframe, metadata)

        if informative_1h is not None and not informative_1h.empty:
            dataframe = merge_informative_pair(
                dataframe, informative_1h, self.timeframe, self.inf_1h, ffill=True
            )
        else:
            # fallback columns when 1h data is missing
            nan_cols = [
                "ema_8_1h", "ema_50_1h", "ema_100_1h", "ema_200_1h",
                "cti_1h", "cti_40_1h", "crsi_1h",
                "r_96_1h", "r_480_1h",
                "bb_lowerband2_1h", "bb_middleband2_1h", "bb_upperband2_1h",
                "bb_width_1h", "roc_1h",
                "rsi_1h", "cmf_1h", "ha_close_1h", "rocr_1h",
                "T3_1h", "EWO_1h", "hl_pct_change_5_1h", "low_5_1h",
            ]
            false_cols = [
                "momdiv_buy_1h", "momdiv_sell_1h", "momdiv_coh_1h",
                "momdiv_col_1h", "safe_dump_50_1h",
            ]

            for col in nan_cols:
                if col not in dataframe.columns:
                    dataframe[col] = np.nan

            for col in false_cols:
                if col not in dataframe.columns:
                    dataframe[col] = False

        dataframe = self.normal_tf_indicators(dataframe, metadata)
        return dataframe
########################################################################################################################################################
# Informative pairs
########################################################################################################################################################
    def informative_pairs(self):
        pairs = self.dp.current_whitelist()
        return [(pair, self.inf_1h) for pair in pairs]
########################################################################################################################################################
# TF Indicators
########################################################################################################################################################
    def normal_tf_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        bollinger2 = qtpylib.bollinger_bands(qtpylib.typical_price(dataframe), window=20, stds=2)
        dataframe["bb_lowerband2"] = bollinger2["lower"]
        dataframe["bb_middleband2"] = bollinger2["mid"]
        dataframe["bb_upperband2"] = bollinger2["upper"]

        bollinger3 = qtpylib.bollinger_bands(qtpylib.typical_price(dataframe), window=20, stds=3)
        dataframe["bb_lowerband3"] = bollinger3["lower"]
        dataframe["bb_middleband3"] = bollinger3["mid"]
        dataframe["bb_upperband3"] = bollinger3["upper"]

        dataframe["bb_width"] = (
            (dataframe["bb_upperband2"] - dataframe["bb_lowerband2"]) / dataframe["bb_middleband2"]
        )
        dataframe["bb_delta"] = (
            (dataframe["bb_lowerband2"] - dataframe["bb_lowerband3"]) / dataframe["bb_lowerband2"]
        )

        for val in self.buy_cci_length.range:
            dataframe[f"cci_length_{val}"] = ta.CCI(dataframe, val)

        dataframe["cci"] = ta.CCI(dataframe, 26)
        dataframe["cci_long"] = ta.CCI(dataframe, 170)

        for val in self.buy_rmi_length.range:
            dataframe[f"rmi_length_{val}"] = RMI(dataframe, length=val, mom=4)

        stoch = ta.STOCHRSI(dataframe, 15, 20, 2, 2)
        dataframe["srsi_fk"] = stoch["fastk"]
        dataframe["srsi_fd"] = stoch["fastd"]

        dataframe["closedelta"] = (dataframe["close"] - dataframe["close"].shift()).abs()

        dataframe["sma_9"] = ta.SMA(dataframe, timeperiod=9)
        dataframe["sma_15"] = ta.SMA(dataframe, timeperiod=15)
        dataframe["sma_20"] = ta.SMA(dataframe, timeperiod=20)
        dataframe["sma_21"] = ta.SMA(dataframe, timeperiod=21)
        dataframe["sma_28"] = ta.SMA(dataframe, timeperiod=28)
        dataframe["sma_30"] = ta.SMA(dataframe, timeperiod=30)
        dataframe["sma_75"] = ta.SMA(dataframe, timeperiod=75)

        dataframe["cti"] = pta.cti(dataframe["close"], length=20)
        dataframe["cmf"] = chaikin_money_flow(dataframe, 20)

        crsi_closechange = dataframe["close"] / dataframe["close"].shift(1)
        crsi_updown = np.where(
            crsi_closechange.gt(1), 1.0, np.where(crsi_closechange.lt(1), -1.0, 0.0)
        )
        dataframe["crsi"] = (
            ta.RSI(dataframe["close"], timeperiod=3)
            + ta.RSI(crsi_updown, timeperiod=2)
            + ta.ROC(dataframe["close"], 100)
        ) / 3

        dataframe["ema_4"] = ta.EMA(dataframe, timeperiod=4)
        dataframe["ema_8"] = ta.EMA(dataframe, timeperiod=8)
        dataframe["ema_12"] = ta.EMA(dataframe, timeperiod=12)
        dataframe["ema_13"] = ta.EMA(dataframe, timeperiod=13)
        dataframe["ema_16"] = ta.EMA(dataframe, timeperiod=16)
        dataframe["ema_20"] = ta.EMA(dataframe, timeperiod=20)
        dataframe["ema_26"] = ta.EMA(dataframe, timeperiod=26)
        dataframe["ema_50"] = ta.EMA(dataframe, timeperiod=50)
        dataframe["ema_100"] = ta.EMA(dataframe, timeperiod=100)
        dataframe["ema_200"] = ta.EMA(dataframe, timeperiod=200)

        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["rsi_fast"] = ta.RSI(dataframe, timeperiod=4)
        dataframe["rsi_slow"] = ta.RSI(dataframe, timeperiod=20)

        dataframe["EWO"] = EWO(dataframe, 50, 200)

        dataframe["r_14"] = williams_r(dataframe, period=14)
        dataframe["r_32"] = williams_r(dataframe, period=32)
        dataframe["r_64"] = williams_r(dataframe, period=64)
        dataframe["r_96"] = williams_r(dataframe, period=96)
        dataframe["r_480"] = williams_r(dataframe, period=480)

        dataframe["volume_mean_4"] = dataframe["volume"].rolling(4).mean().shift(1)
        dataframe["volume_mean_12"] = dataframe["volume"].rolling(12).mean().shift(1)
        dataframe["volume_mean_24"] = dataframe["volume"].rolling(24).mean().shift(1)

        dataframe["mfi"] = ta.MFI(dataframe)

        heikinashi = qtpylib.heikinashi(dataframe)
        dataframe["ha_open"] = heikinashi["open"]
        dataframe["ha_close"] = heikinashi["close"]
        dataframe["ha_high"] = heikinashi["high"]
        dataframe["ha_low"] = heikinashi["low"]

        bollinger2_40 = qtpylib.bollinger_bands(ha_typical_price(dataframe), window=40, stds=2)
        dataframe["bb_lowerband2_40"] = bollinger2_40["lower"]
        dataframe["bb_middleband2_40"] = bollinger2_40["mid"]
        dataframe["bb_upperband2_40"] = bollinger2_40["upper"]

        dataframe["bb_delta_cluc"] = (dataframe["bb_middleband2_40"] - dataframe["bb_lowerband2_40"]).abs()
        dataframe["ha_closedelta"] = (dataframe["ha_close"] - dataframe["ha_close"].shift()).abs()
        dataframe["tail"] = (dataframe["ha_close"] - dataframe["ha_low"]).abs()
        dataframe["ema_slow"] = ta.EMA(dataframe["ha_close"], timeperiod=50)
        dataframe["rocr"] = ta.ROCR(dataframe["ha_close"], timeperiod=28)

        stoch_fast = ta.STOCHF(dataframe, 5, 3, 0, 3, 0)
        dataframe["fastd"] = stoch_fast["fastd"]
        dataframe["fastk"] = stoch_fast["fastk"]
        dataframe["adx"] = ta.ADX(dataframe)

        dataframe["pm"], dataframe["pmx"] = pmax(
            heikinashi, MAtype=1, length=9, multiplier=27, period=10, src=3
        )
        dataframe["source"] = (
            dataframe["high"] + dataframe["low"] + dataframe["open"] + dataframe["close"]
        ) / 4
        dataframe["pmax_thresh"] = ta.EMA(dataframe["source"], timeperiod=9)

        mom = momdiv(dataframe)
        dataframe["momdiv_buy"] = mom["momdiv_buy"]
        dataframe["momdiv_sell"] = mom["momdiv_sell"]
        dataframe["momdiv_coh"] = mom["momdiv_coh"]
        dataframe["momdiv_col"] = mom["momdiv_col"]

        dataframe["T3"] = T3(dataframe)
        dataframe["trange"] = ta.TRANGE(dataframe)

        dataframe["range_ma_28"] = ta.SMA(dataframe["trange"], 28)
        dataframe["kc_upperband_28_1"] = dataframe["sma_28"] + dataframe["range_ma_28"]
        dataframe["kc_lowerband_28_1"] = dataframe["sma_28"] - dataframe["range_ma_28"]

        dataframe["range_ma_20"] = ta.SMA(dataframe["trange"], 20)
        dataframe["kc_upperband_20_2"] = dataframe["sma_20"] + dataframe["range_ma_20"] * 2
        dataframe["kc_lowerband_20_2"] = dataframe["sma_20"] - dataframe["range_ma_20"] * 2
        dataframe["kc_bb_delta"] = (
            (dataframe["kc_lowerband_20_2"] - dataframe["bb_lowerband2"])
            / dataframe["bb_lowerband2"]
            * 100
        )

        dataframe["hh_20"] = ta.MAX(dataframe["high"], 20)
        dataframe["ll_20"] = ta.MIN(dataframe["low"], 20)
        dataframe["avg_hh_ll_20"] = (dataframe["hh_20"] + dataframe["ll_20"]) / 2
        dataframe["avg_close_20"] = ta.SMA(dataframe["close"], 20)
        dataframe["avg_val_20"] = (dataframe["avg_hh_ll_20"] + dataframe["avg_close_20"]) / 2
        dataframe["linreg_val_20"] = ta.LINEARREG(
            dataframe["close"] - dataframe["avg_val_20"], timeperiod=20
        )

        rsi = 0.1 * (dataframe["rsi"] - 50)
        dataframe["fisher"] = (np.exp(2 * rsi) - 1) / (np.exp(2 * rsi) + 1)

        dataframe["moderi_96"] = moderi(dataframe, 96)

        return dataframe

########################################################################################################################################################
# Buy Signal
########################################################################################################################################################
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        conditions = []
        dataframe.loc[:, "enter_tag"] = ""
        dataframe.loc[:, "enter_long"] = 0

        is_dip = (
            (dataframe[f"rmi_length_{self.buy_rmi_length.value}"] < self.buy_rmi.value)
            & (dataframe[f"cci_length_{self.buy_cci_length.value}"] <= self.buy_cci.value)
            & (dataframe["srsi_fk"] < self.buy_srsi_fk.value)
        )

        is_sqzOff = (
            (dataframe["bb_lowerband2"] < dataframe["kc_lowerband_28_1"])
            & (dataframe["bb_upperband2"] > dataframe["kc_upperband_28_1"])
        )

        is_break = (
            (dataframe["bb_delta"] > self.buy_bb_delta.value)
            & (dataframe["bb_width"] > self.buy_bb_width.value)
            & (dataframe["closedelta"] > dataframe["close"] * self.buy_closedelta.value / 1000)
            & (dataframe["close"] < dataframe["bb_lowerband3"] * self.buy_bb_factor.value)
        )

        is_local_uptrend = (
            (dataframe["ema_26"] > dataframe["ema_12"])
            & (dataframe["ema_26"] - dataframe["ema_12"] > dataframe["open"] * self.buy_ema_diff.value)
            & (dataframe["ema_26"].shift() - dataframe["ema_12"].shift() > dataframe["open"] / 100)
            & (dataframe["close"] < dataframe["bb_lowerband2"] * self.buy_bb_factor.value)
            & (dataframe["closedelta"] > dataframe["close"] * self.buy_closedelta.value / 1000)
        )

        is_ewo = (
            (dataframe["rsi_fast"] < self.buy_rsi_fast.value)
            & (dataframe["close"] < dataframe["ema_8"] * self.buy_ema_low.value)
            & (dataframe["EWO"] > self.buy_ewo.value)
            & (dataframe["close"] < dataframe["ema_16"] * self.buy_ema_high.value)
            & (dataframe["rsi"] < self.buy_rsi.value)
        )

        is_ewo_2 = (
            (dataframe["ema_200_1h"] > dataframe["ema_200_1h"].shift(12))
            & (dataframe["ema_200_1h"].shift(12) > dataframe["ema_200_1h"].shift(24))
            & (dataframe["rsi_fast"] < self.buy_rsi_fast_ewo_2.value)
            & (dataframe["close"] < dataframe["ema_8"] * self.buy_ema_low_2.value)
            & (dataframe["EWO"] > self.buy_ewo_high_2.value)
            & (dataframe["close"] < dataframe["ema_16"] * self.buy_ema_high_2.value)
            & (dataframe["rsi"] < self.buy_rsi_ewo_2.value)
        )

        is_r_deadfish = (
            (dataframe["ema_100"] < dataframe["ema_200"] * self.buy_r_deadfish_ema.value)
            & (dataframe["bb_width"] > self.buy_r_deadfish_bb_width.value)
            & (dataframe["close"] < dataframe["bb_middleband2"] * self.buy_r_deadfish_bb_factor.value)
            & (
                dataframe["volume_mean_12"]
                > dataframe["volume_mean_24"] * self.buy_r_deadfish_volume_factor.value
            )
            & (dataframe["cti"] < self.buy_r_deadfish_cti.value)
            & (dataframe["r_14"] < self.buy_r_deadfish_r14.value)
        )

        is_clucHA = (
            (dataframe["rocr_1h"] > self.buy_clucha_rocr_1h.value)
            & (
                (dataframe["bb_lowerband2_40"].shift() > 0)
                & (dataframe["bb_delta_cluc"] > dataframe["ha_close"] * self.buy_clucha_bbdelta_close.value)
                & (
                    dataframe["ha_closedelta"]
                    > dataframe["ha_close"] * self.buy_clucha_closedelta_close.value
                )
                & (dataframe["tail"] < dataframe["bb_delta_cluc"] * self.buy_clucha_bbdelta_tail.value)
                & (dataframe["ha_close"] < dataframe["bb_lowerband2_40"].shift())
                & (dataframe["ha_close"] < dataframe["ha_close"].shift())
            )
        )

        is_gumbo = (
            (dataframe["EWO"] < self.buy_gumbo_ewo_low.value)
            & (dataframe["bb_middleband2_1h"] >= dataframe["T3_1h"])
            & (dataframe["T3"] <= dataframe["ema_8"] * self.buy_gumbo_ema.value)
            & (dataframe["cti"] < self.buy_gumbo_cti.value)
            & (dataframe["r_14"] < self.buy_gumbo_r14.value)
        )

        is_sqzmom = (
            is_sqzOff
            & (dataframe["linreg_val_20"].shift(2) > dataframe["linreg_val_20"].shift(1))
            & (dataframe["linreg_val_20"].shift(1) < dataframe["linreg_val_20"])
            & (dataframe["linreg_val_20"] < 0)
            & (dataframe["close"] < dataframe["ema_13"] * self.buy_sqzmom_ema.value)
            & (dataframe["EWO"] < self.buy_sqzmom_ewo.value)
            & (dataframe["r_14"] < self.buy_sqzmom_r14.value)
        )

        is_nfi_13 = (
            (dataframe["ema_50_1h"] > dataframe["ema_100_1h"])
            & (dataframe["close"] < dataframe["sma_30"] * 0.99)
            & (dataframe["cti"] < -0.92)
            & (dataframe["EWO"] < -5.585)
            & (dataframe["cti_1h"] < -0.88)
            & (dataframe["crsi_1h"] > 10.0)
        )

        is_nfi_32 = (
            (dataframe["rsi_slow"] < dataframe["rsi_slow"].shift(1))
            & (dataframe["rsi_fast"] < 46)
            & (dataframe["rsi"] > 25.0)
            & (dataframe["close"] < dataframe["sma_15"] * 0.93)
            & (dataframe["cti"] < -0.9)
        )

        is_nfi_33 = (
            (dataframe["close"] < (dataframe["ema_13"] * 0.978))
            & (dataframe["EWO"] > 8)
            & (dataframe["cti"] < -0.88)
            & (dataframe["rsi"] < 32)
            & (dataframe["r_14"] < -98.0)
            & (dataframe["volume"] < (dataframe["volume_mean_4"] * 2.5))
        )

        is_nfix_5 = (
            (dataframe["ema_200_1h"] > dataframe["ema_200_1h"].shift(12))
            & (dataframe["ema_200_1h"].shift(12) > dataframe["ema_200_1h"].shift(24))
            & (dataframe["close"] < dataframe["sma_75"] * 0.932)
            & (dataframe["EWO"] > 3.6)
            & (dataframe["cti"] < -0.9)
            & (dataframe["r_14"] < -97.0)
        )

        is_nfix_49 = (
            (dataframe["ema_26"].shift(3) > dataframe["ema_12"].shift(3))
            & (
                dataframe["ema_26"].shift(3) - dataframe["ema_12"].shift(3)
                > dataframe["open"].shift(3) * 0.032
            )
            & (
                dataframe["ema_26"].shift(9) - dataframe["ema_12"].shift(9)
                > dataframe["open"].shift(3) / 100
            )
            & (dataframe["close"].shift(3) < dataframe["ema_20"].shift(3) * 0.916)
            & (dataframe["rsi"].shift(3) < 32.5)
            & (dataframe["crsi"].shift(3) > 18.0)
            & (dataframe["cti"] < self.buy_nfix_49_cti.value)
            & (dataframe["r_14"] < self.buy_nfix_49_r14.value)
        )

        is_nfi7_33 = (
            (dataframe["moderi_96"])
            & (dataframe["cti"] < -0.88)
            & (dataframe["close"] < (dataframe["ema_13"] * 0.988))
            & (dataframe["EWO"] > 6.4)
            & (dataframe["rsi"] < 32.0)
            & (dataframe["volume"] < (dataframe["volume_mean_4"] * 2.0))
        )

        is_nfi7_37 = (
            (dataframe["pm"] > dataframe["pmax_thresh"])
            & (dataframe["close"] < dataframe["sma_75"] * 0.98)
            & (dataframe["EWO"] > 9.8)
            & (dataframe["rsi"] < 56.0)
            & (dataframe["cti"] < -0.7)
            & (dataframe["safe_dump_50_1h"])
        )

        is_additional_check = (
            (dataframe["roc_1h"] < self.buy_roc_1h.value)
            & (dataframe["bb_width_1h"] < self.buy_bb_width_1h.value)
        )

        is_BB_checked = is_dip & is_break

        conditions.append(is_BB_checked)
        dataframe.loc[is_BB_checked, "enter_tag"] = "bb "

        conditions.append(is_local_uptrend)
        dataframe.loc[is_local_uptrend, "enter_tag"] = "local_uptrend "

        conditions.append(is_ewo)
        dataframe.loc[is_ewo, "enter_tag"] = "ewo "

        conditions.append(is_r_deadfish)
        dataframe.loc[is_r_deadfish, "enter_tag"] = "r_deadfish "

        # conditions.append(is_clucHA)
        # dataframe.loc[is_clucHA, 'enter_tag'] += 'clucHA '

        # conditions.append(is_gumbo)
        # dataframe.loc[is_gumbo, 'enter_tag'] += 'gumbo '

        conditions.append(is_sqzmom)
        dataframe.loc[is_sqzmom, "enter_tag"] = "sqzmom "

        conditions.append(is_nfi_13)
        dataframe.loc[is_nfi_13, "enter_tag"] = "nfi_13 "

        conditions.append(is_nfi_32)
        dataframe.loc[is_nfi_32, "enter_tag"] = "nfi_32 "

        conditions.append(is_nfi_33)
        dataframe.loc[is_nfi_33, "enter_tag"] = "nfi_33 "

        conditions.append(is_nfix_49)
        dataframe.loc[is_nfix_49, "enter_tag"] = "nfix_49 "

        conditions.append(is_nfi7_33)
        dataframe.loc[is_nfi7_33, "enter_tag"] = "nfi7_33 "

        conditions.append(is_nfi7_37)
        dataframe.loc[is_nfi7_37, "enter_tag"] = "nfi7_37 "

        if conditions:
            dataframe.loc[reduce(lambda x, y: x | y, conditions), "enter_long"] = 1

        return dataframe

########################################################################################################################################################
# Confirm Entry
########################################################################################################################################################
    def confirm_trade_entry(
        self,
        pair: str,
        order_type: str,
        amount: float,
        rate: float,
        time_in_force: str,
        **kwargs,
    ) -> bool:
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        max_slip = self.max_slip.value

        if len(dataframe) < 1:
            return False

        last = dataframe.iloc[-1].squeeze()

        if rate > last["close"]:
            slippage = ((rate / last["close"]) - 1) * 100
            return slippage < max_slip

        return True

########################################################################################################################################################
# Custom Stoploss
########################################################################################################################################################
    def custom_stoploss(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ) -> float:
        sl_new = 1

        if current_profit > 0.2:
            sl_new = 0.05
        elif current_profit > 0.1:
            sl_new = 0.03
        elif current_profit > 0.06:
            sl_new = 0.02
        elif current_profit > 0.03:
            sl_new = 0.015

        return sl_new

########################################################################################################################################################
# Custom Sell From NFIX
########################################################################################################################################################
    def custom_exit(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ):
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)

        if len(dataframe) < 3:
            return None

        last_candle = dataframe.iloc[-1]
        previous_candle_1 = dataframe.iloc[-2]
        previous_candle_2 = dataframe.iloc[-3]

        max_profit = (trade.max_rate - trade.open_rate) / trade.open_rate
        max_loss = (trade.open_rate - trade.min_rate) / trade.min_rate

        enter_tag = "empty"
        if hasattr(trade, "enter_tag") and trade.enter_tag is not None:
            enter_tag = trade.enter_tag

        # sell trail
        if 0.012 > current_profit >= 0.0:
            if (max_profit > (current_profit + 0.045)) and (last_candle["rsi"] < 46.0):
                return f"sell_profit_t_0_1({enter_tag})"
            elif (max_profit > (current_profit + 0.025)) and (last_candle["rsi"] < 32.0):
                return f"sell_profit_t_0_2({enter_tag})"
            elif (max_profit > (current_profit + 0.05)) and (last_candle["rsi"] < 48.0):
                return f"sell_profit_t_0_3({enter_tag})"

        elif 0.02 > current_profit >= 0.012:
            if (max_profit > (current_profit + 0.01)) and (last_candle["rsi"] < 39.0):
                return f"sell_profit_t_1_1({enter_tag})"
            elif (
                (max_profit > (current_profit + 0.035))
                and (last_candle["rsi"] < 45.0)
                and (last_candle["cmf"] < -0.0)
                and (last_candle["cmf_1h"] < -0.0)
            ):
                return f"sell_profit_t_1_2({enter_tag})"
            elif (
                (max_profit > (current_profit + 0.02))
                and (last_candle["rsi"] < 40.0)
                and (last_candle["cmf"] < -0.0)
                and (last_candle["cti_1h"] > 0.8)
            ):
                return f"sell_profit_t_1_4({enter_tag})"
            elif (
                (max_profit > (current_profit + 0.04))
                and (last_candle["rsi"] < 49.0)
                and (last_candle["cmf_1h"] < -0.0)
            ):
                return f"sell_profit_t_1_5({enter_tag})"
            elif (
                (max_profit > (current_profit + 0.06))
                and (last_candle["rsi"] < 43.0)
                and (last_candle["cmf"] < -0.0)
            ):
                return f"sell_profit_t_1_7({enter_tag})"
            elif (
                (max_profit > (current_profit + 0.025))
                and (last_candle["rsi"] < 40.0)
                and (last_candle["cmf"] < -0.1)
                and (last_candle["rsi_1h"] < 50.0)
            ):
                return f"sell_profit_t_1_9({enter_tag})"
            elif (
                (max_profit > (current_profit + 0.025))
                and (last_candle["rsi"] < 46.0)
                and (last_candle["cmf"] < -0.0)
                and (last_candle["r_480_1h"] > -20.0)
            ):
                return f"sell_profit_t_1_10({enter_tag})"
            elif (max_profit > (current_profit + 0.025)) and (last_candle["rsi"] < 42.0):
                return f"sell_profit_t_1_11({enter_tag})"
            elif (
                (max_profit > (current_profit + 0.01))
                and (last_candle["rsi"] < 44.0)
                and (last_candle["cmf"] < -0.25)
            ):
                return f"sell_profit_t_1_12({enter_tag})"

        if 0.012 > current_profit >= 0.0:
            if (last_candle["cti"] > self.sell_cti_r_cti.value) and (
                last_candle["r_14"] > self.sell_cti_r_r.value
            ):
                return f"sell_profit_t_cti_r_0_1({enter_tag})"

        if current_profit > 0.02:
            if last_candle["momdiv_sell_1h"] is True:
                return f"signal_profit_q_momdiv_1h({enter_tag})"
            if last_candle["momdiv_sell"] is True:
                return f"signal_profit_q_momdiv({enter_tag})"
            if last_candle["momdiv_coh"] is True:
                return f"signal_profit_q_momdiv_coh({enter_tag})"

        if last_candle["close"] < last_candle["ema_200"]:
            if 0.02 > current_profit >= 0.01:
                if (last_candle["rsi"] < 34.0) and (last_candle["cmf"] < 0.0):
                    return f"sell_profit_u_bear_1_1({enter_tag})"
                elif (last_candle["rsi"] < 44.0) and (last_candle["cmf"] < -0.4):
                    return f"sell_profit_u_bear_1_2({enter_tag})"

        if (0.06 > current_profit > 0.02) and (last_candle["rsi"] > 80.0):
            return f"signal_profit_q_1({enter_tag})"

        if (0.06 > current_profit > 0.02) and (last_candle["cti"] > 0.95):
            return f"signal_profit_q_2({enter_tag})"

        if (
            (0.06 > current_profit > 0.02)
            and (last_candle["pm"] <= last_candle["pmax_thresh"])
            and (last_candle["close"] > last_candle["sma_21"] * 1.1)
        ):
            return f"signal_profit_q_pmax_bull({enter_tag})"

        if (
            (0.06 > current_profit > 0.02)
            and (last_candle["pm"] > last_candle["pmax_thresh"])
            and (last_candle["close"] > last_candle["sma_21"] * 1.016)
        ):
            return f"signal_profit_q_pmax_bear({enter_tag})"

        if (
            (current_profit < -0.05)
            and (last_candle["close"] < last_candle["ema_200"] * 0.988)
            and (last_candle["cmf"] < -0.046)
            and (((last_candle["ema_200"] - last_candle["close"]) / last_candle["close"]) < 0.022)
            and (last_candle["rsi"] > previous_candle_1["rsi"])
            and (last_candle["rsi"] > (last_candle["rsi_1h"] + 10.0))
        ):
            return f"sell_stoploss_u_e_1({enter_tag})"

        if (
            (current_profit < self.sell_deadfish_profit.value)
            and (last_candle["close"] < last_candle["ema_200"])
            and (last_candle["bb_width"] < self.sell_deadfish_bb_width.value)
            and (last_candle["close"] > last_candle["bb_middleband2"] * self.sell_deadfish_bb_factor.value)
            and (
                last_candle["volume_mean_12"]
                < last_candle["volume_mean_24"] * self.sell_deadfish_volume_factor.value
            )
        ):
            return f"sell_stoploss_deadfish({enter_tag})"

        return None

########################################################################################################################################################
# Sell Signal
########################################################################################################################################################
    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[(dataframe["volume"] > 0), "exit_long"] = 0
        return dataframe