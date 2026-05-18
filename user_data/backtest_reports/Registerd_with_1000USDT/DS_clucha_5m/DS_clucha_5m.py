from datetime import datetime, timedelta, timezone
from freqtrade.persistence import Trade, PairLocks
from freqtrade.strategy import (
    BooleanParameter,
    DecimalParameter,
    IntParameter,
    RealParameter,
    stoploss_from_open,
    merge_informative_pair,
    CategoricalParameter,
)
from freqtrade.strategy.interface import IStrategy
from functools import reduce
from logging import FATAL
from pandas import DataFrame, Series
from technical.util import resample_to_interval, resampled_merge
from typing import Dict, List, Optional, Union
import freqtrade.vendor.qtpylib.indicators as qtpylib
import logging
import math
import numpy as np
import pandas as pd
import pandas_ta as pta
import talib.abstract as ta

logger = logging.getLogger(__name__)

############################################################################
# Custom indicators and helper functions
############################################################################
def bollinger_bands(stock_price, window_size, num_of_std):
    rolling_mean = stock_price.rolling(window=window_size).mean()
    rolling_std = stock_price.rolling(window=window_size).std()
    lower_band = rolling_mean - (rolling_std * num_of_std)
    return np.nan_to_num(rolling_mean), np.nan_to_num(lower_band)


def ha_typical_price(bars):
    res = (bars["ha_high"] + bars["ha_low"] + bars["ha_close"]) / 3.0
    return Series(index=bars.index, data=res)


class DS_clucha_5m(IStrategy):
    INTERFACE_VERSION = 3
    can_short = False

########################################################################################################################################################
# Main
########################################################################################################################################################
    timeframe = "5m"

    use_exit_signal = True
    exit_profit_only = False
    exit_profit_offset = 0.01
    ignore_roi_if_entry_signal = False

    use_custom_stoploss = True

    trailing_stop = False
    trailing_stop_positive = 0.001
    trailing_stop_positive_offset = 0.012
    trailing_only_offset_is_reached = False

    process_only_new_candles = True
    startup_candle_count = 168

    order_types = {
        "entry": "market",
        "exit": "market",
        "emergency_exit": "market",
        "force_entry": "market",
        "force_exit": "market",
        "stoploss": "market",
        "stoploss_on_exchange": False,
        "stoploss_on_exchange_interval": 60,
        "stoploss_on_exchange_limit_ratio": 0.99
    }

    slippage_protection = {
        "retries": 3,
        "max_slippage": -0.02
    }

    plot_config = {
        "main_plot": {
            "ma_buy": {"color": "green"},
            "ma_sell": {"color": "orange"},
        },
    }

########################################################################################################################################################
# Hyperopt
########################################################################################################################################################
    buy_params = {
        "clucha_enabled": True,
        "bbdelta_close": 0.01889,
        "bbdelta_tail": 0.72235,
        "close_bblower": 0.0127,
        "closedelta_close": 0.00916,
        "rocr_1h": 0.79492,
    }

    sell_params = {
        "sell_fisher": 0.39075,
        "sell_bbmiddle_close": 0.99754,
        "pHSL": -0.35,
        "pPF_1": 0.011,
        "pPF_2": 0.064,
        "pSL_1": 0.011,
        "pSL_2": 0.062,
    }

    minimal_roi = {
        "0": 100
    }

    stoploss = -0.99

########################################################################################################################################################
# Parameters
########################################################################################################################################################
    rocr_1h = RealParameter(0.5, 1.0, default=0.54904, space="buy", optimize=True)
    bbdelta_close = RealParameter(0.0005, 0.02, default=0.01965, space="buy", optimize=True)
    closedelta_close = RealParameter(0.0005, 0.02, default=0.00556, space="buy", optimize=True)
    bbdelta_tail = RealParameter(0.7, 1.0, default=0.95089, space="buy", optimize=True)
    close_bblower = RealParameter(0.0005, 0.02, default=0.00799, space="buy", optimize=True)

    sell_fisher = RealParameter(0.1, 0.5, default=0.38414, space="sell", optimize=True)
    sell_bbmiddle_close = RealParameter(0.97, 1.1, default=1.07634, space="sell", optimize=True)

    clucha_enabled = BooleanParameter(default=buy_params["clucha_enabled"], space="buy", optimize=True)

############################################################################################################################################################################
# Trailing Stoploss Parameters
########################################################################################################################################################
    is_optimize_stoploss = True
    pHSL = DecimalParameter(-0.200, -0.040, default=-0.15, decimals=3, space="sell", optimize=is_optimize_stoploss, load=True)
    pPF_1 = DecimalParameter(0.008, 0.020, default=0.016, decimals=3, space="sell", optimize=is_optimize_stoploss, load=True)
    pSL_1 = DecimalParameter(0.008, 0.020, default=0.014, decimals=3, space="sell", optimize=is_optimize_stoploss, load=True)
    pPF_2 = DecimalParameter(0.040, 0.100, default=0.024, decimals=3, space="sell", optimize=is_optimize_stoploss, load=True)
    pSL_2 = DecimalParameter(0.020, 0.070, default=0.022, decimals=3, space="sell", optimize=is_optimize_stoploss, load=True)

########################################################################################################################################################
# Informative Pairs
########################################################################################################################################################
    def informative_pairs(self):
        pairs = self.dp.current_whitelist()
        return [(pair, "1h") for pair in pairs]

########################################################################################################################################################
# Safe informative fetch
########################################################################################################################################################
    def _get_informative_1h(self, pair: str) -> DataFrame:
        informative = self.dp.get_pair_dataframe(pair=pair, timeframe="1h")

        if informative is None or informative.empty:
            return DataFrame(columns=["date", "rocr"])

        informative = informative.copy()

        if "date" in informative.columns:
            informative["date"] = pd.to_datetime(informative["date"], utc=True, errors="coerce")
            informative = informative.dropna(subset=["date"])

        if informative.empty:
            return DataFrame(columns=["date", "rocr"])

        inf_heikinashi = qtpylib.heikinashi(informative)
        informative["ha_close"] = inf_heikinashi["close"]
        informative["rocr"] = ta.ROCR(informative["ha_close"], timeperiod=168)

        return informative[["date", "rocr"]].copy()

########################################################################################################################################################
# Indicators
########################################################################################################################################################
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = dataframe.copy()

        if "date" in dataframe.columns:
            dataframe["date"] = pd.to_datetime(dataframe["date"], utc=True, errors="coerce")
            dataframe = dataframe.dropna(subset=["date"])

        heikinashi = qtpylib.heikinashi(dataframe)
        dataframe["ha_open"] = heikinashi["open"]
        dataframe["ha_close"] = heikinashi["close"]
        dataframe["ha_high"] = heikinashi["high"]
        dataframe["ha_low"] = heikinashi["low"]

        mid, lower = bollinger_bands(ha_typical_price(dataframe), window_size=40, num_of_std=2)
        dataframe["lower"] = lower
        dataframe["mid"] = mid

        dataframe["bbdelta"] = (mid - dataframe["lower"]).abs()
        dataframe["closedelta"] = (dataframe["ha_close"] - dataframe["ha_close"].shift()).abs()
        dataframe["tail"] = (dataframe["ha_close"] - dataframe["ha_low"]).abs()

        dataframe["bb_lowerband"] = dataframe["lower"]
        dataframe["bb_middleband"] = dataframe["mid"]

        dataframe["ema_fast"] = ta.EMA(dataframe["ha_close"], timeperiod=3)
        dataframe["ema_slow"] = ta.EMA(dataframe["ha_close"], timeperiod=50)
        dataframe["volume_mean_slow"] = dataframe["volume"].rolling(window=30).mean()
        dataframe["rocr"] = ta.ROCR(dataframe["ha_close"], timeperiod=28)

        rsi = ta.RSI(dataframe)
        dataframe["rsi"] = rsi
        rsi_t = 0.1 * (rsi - 50)
        dataframe["fisher"] = (np.exp(2 * rsi_t) - 1) / (np.exp(2 * rsi_t) + 1)

        informative = self._get_informative_1h(metadata["pair"])

        if not informative.empty:
            dataframe = merge_informative_pair(
                dataframe,
                informative,
                self.timeframe,
                "1h",
                ffill=True,
            )
        else:
            dataframe["rocr_1h"] = np.nan

        if "rocr_1h" not in dataframe.columns:
            dataframe["rocr_1h"] = np.nan

        return dataframe

########################################################################################################################################################
# Buy Trend
########################################################################################################################################################
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["enter_long"] = 0
        dataframe["enter_tag"] = ""

        buy_condition = (
            bool(self.clucha_enabled.value)
            & (dataframe["rocr_1h"].gt(self.rocr_1h.value))
            & (
                (
                    (dataframe["lower"].shift().gt(0))
                    & (dataframe["bbdelta"].gt(dataframe["ha_close"] * self.bbdelta_close.value))
                    & (dataframe["closedelta"].gt(dataframe["ha_close"] * self.closedelta_close.value))
                    & (dataframe["tail"].lt(dataframe["bbdelta"] * self.bbdelta_tail.value))
                    & (dataframe["ha_close"].lt(dataframe["lower"].shift()))
                    & (dataframe["ha_close"].le(dataframe["ha_close"].shift()))
                )
                |
                (
                    (dataframe["ha_close"] < dataframe["ema_slow"])
                    & (dataframe["ha_close"] < self.close_bblower.value * dataframe["bb_lowerband"])
                )
            )
        )

        dataframe.loc[buy_condition, "enter_long"] = 1
        dataframe.loc[buy_condition, "enter_tag"] = "clucHA"

        return dataframe

########################################################################################################################################################
# Sell Trend
########################################################################################################################################################
    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0
        dataframe["exit_tag"] = "no_exit"

        sell_condition = (
            (dataframe["fisher"] > self.sell_fisher.value)
            & (dataframe["ha_high"].le(dataframe["ha_high"].shift(1)))
            & (dataframe["ha_high"].shift(1).le(dataframe["ha_high"].shift(2)))
            & (dataframe["ha_close"].le(dataframe["ha_close"].shift(1)))
            & (dataframe["ema_fast"] > dataframe["ha_close"])
            & ((dataframe["ha_close"] * self.sell_bbmiddle_close.value) > dataframe["bb_middleband"])
            & (dataframe["volume"] > 0)
        )

        dataframe.loc[sell_condition, "exit_long"] = 1
        dataframe.loc[sell_condition, "exit_tag"] = "fisher_ema_bearish"

        return dataframe

########################################################################################################################################################
# Confirm Trade Exit
########################################################################################################################################################
    def confirm_trade_exit(
        self,
        pair: str,
        trade: Trade,
        order_type: str,
        amount: float,
        rate: float,
        time_in_force: str,
        exit_reason: str,
        current_time: datetime,
        **kwargs
    ) -> bool:
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)

        if dataframe is None or dataframe.empty:
            return True

        last_candle = dataframe.iloc[-1]

        state = self.slippage_protection.setdefault("__pair_retries", {})

        slippage = (rate / last_candle["close"]) - 1
        if slippage < self.slippage_protection["max_slippage"]:
            pair_retries = state.get(pair, 0)
            if pair_retries < self.slippage_protection["retries"]:
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
# Custom Trailing Stoploss
########################################################################################################################################################
    def custom_stoploss(
        self,
        pair: str,
        trade: "Trade",
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs
    ) -> float:
        HSL = self.pHSL.value
        PF_1 = self.pPF_1.value
        SL_1 = self.pSL_1.value
        PF_2 = self.pPF_2.value
        SL_2 = self.pSL_2.value

        if current_profit > PF_2:
            sl_profit = SL_2 + (current_profit - PF_2)
        elif current_profit > PF_1:
            sl_profit = SL_1 + ((current_profit - PF_1) * (SL_2 - SL_1) / (PF_2 - PF_1))
        else:
            sl_profit = HSL

        if sl_profit >= current_profit:
            return -0.99

        return stoploss_from_open(sl_profit, current_profit)