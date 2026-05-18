import freqtrade.vendor.qtpylib.indicators as qtpylib
import numpy as np
import pandas as pd
import talib.abstract as ta

from freqtrade.persistence import Trade
from freqtrade.strategy.interface import IStrategy
from freqtrade.strategy import merge_informative_pair, DecimalParameter, stoploss_from_open
from pandas import DataFrame, Series
from datetime import datetime


########################################################################################################################################################
# bollinger_bands
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
    res = (bars["ha_high"] + bars["ha_low"] + bars["ha_close"]) / 3.0
    return Series(index=bars.index, data=res)


########################################################################################################################################################
class DS_CHA_5m(IStrategy):
########################################################################################################################################################
    INTERFACE_VERSION = 3
    can_short = False

########################################################################################################################################################
# Hyperopt
########################################################################################################################################################
    buy_params = {
        "rocr_1h": 0.525,
        "bbdelta_close": 0.014,
        "closedelta_close": 0.01,
        "bbdelta_tail": 0.846,
        "close_bblower": 0.003,
    }

    sell_params = {
        "sell_bbmiddle_close": 1.059,
        "sell_fisher": 0.157,
        "pHSL": -0.486,
        "pPF_1": 0.014,
        "pPF_2": 0.067,
        "pSL_1": 0.014,
        "pSL_2": 0.066,
    }

    minimal_roi = {
        "0": 100
    }

    stoploss = -0.99
    trailing_stop = False
    trailing_stop_positive = 0.001
    trailing_stop_positive_offset = 0.012
    trailing_only_offset_is_reached = False
    use_custom_stoploss = True

########################################################################################################################################################
# Main
########################################################################################################################################################
    timeframe = "5m"
    process_only_new_candles = True
    startup_candle_count = 168

    use_exit_signal = True
    exit_profit_only = False
    exit_profit_offset = 0.01
    ignore_roi_if_entry_signal = False

    order_types = {
        "entry": "market",
        "exit": "market",
        "trailing_stop_loss": "market",
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
    is_optimize_entry = True
    rocr_1h = DecimalParameter(0.5, 1.0, default=buy_params["rocr_1h"], space="buy", optimize=is_optimize_entry)
    bbdelta_close = DecimalParameter(0.0005, 0.02, default=buy_params["bbdelta_close"], space="buy", optimize=is_optimize_entry)
    closedelta_close = DecimalParameter(0.0005, 0.02, default=buy_params["closedelta_close"], space="buy", optimize=is_optimize_entry)
    bbdelta_tail = DecimalParameter(0.7, 1.0, default=buy_params["bbdelta_tail"], space="buy", optimize=is_optimize_entry)
    close_bblower = DecimalParameter(0.0005, 0.02, default=buy_params["close_bblower"], space="buy", optimize=is_optimize_entry)

    is_optimize_exit = True
    sell_fisher = DecimalParameter(0.1, 0.5, default=sell_params["sell_fisher"], space="sell", optimize=is_optimize_exit)
    sell_bbmiddle_close = DecimalParameter(0.97, 1.1, default=sell_params["sell_bbmiddle_close"], space="sell", optimize=is_optimize_exit)

    is_optimize_stoploss = True
    pHSL = DecimalParameter(-0.500, -0.040, default=-0.08, decimals=3, space="sell", optimize=is_optimize_stoploss, load=True)
    pPF_1 = DecimalParameter(0.008, 0.020, default=0.016, decimals=3, space="sell", optimize=is_optimize_stoploss, load=True)
    pSL_1 = DecimalParameter(0.008, 0.020, default=0.011, decimals=3, space="sell", optimize=is_optimize_stoploss, load=True)
    pPF_2 = DecimalParameter(0.040, 0.100, default=0.080, decimals=3, space="sell", optimize=is_optimize_stoploss, load=True)
    pSL_2 = DecimalParameter(0.020, 0.070, default=0.040, decimals=3, space="sell", optimize=is_optimize_stoploss, load=True)

########################################################################################################################################################
# Informative
########################################################################################################################################################
    def informative_pairs(self):
        pairs = self.dp.current_whitelist()
        return [(pair, "1h") for pair in pairs]

########################################################################################################################################################
# Custom Stoploss
########################################################################################################################################################
    def custom_stoploss(self, pair: str, trade: "Trade", current_time: datetime, current_rate: float, current_profit: float, **kwargs) -> float:
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

########################################################################################################################################################
# Indicators
########################################################################################################################################################
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = dataframe.copy()

        # Base TF Heikin Ashi
        heikinashi = qtpylib.heikinashi(dataframe)
        dataframe["ha_open"] = heikinashi["open"]
        dataframe["ha_close"] = heikinashi["close"]
        dataframe["ha_high"] = heikinashi["high"]
        dataframe["ha_low"] = heikinashi["low"]

        # Bollinger
        mid, lower = bollinger_bands(ha_typical_price(dataframe), window_size=40, num_of_std=2)
        dataframe["lower"] = lower
        dataframe["mid"] = mid
        dataframe["bbdelta"] = (mid - dataframe["lower"]).abs()
        dataframe["closedelta"] = (dataframe["ha_close"] - dataframe["ha_close"].shift()).abs()
        dataframe["tail"] = (dataframe["ha_close"] - dataframe["ha_low"]).abs()
        dataframe["bb_lowerband"] = dataframe["lower"]
        dataframe["bb_middleband"] = dataframe["mid"]

        # EMA / ROCR
        dataframe["ema_fast"] = ta.EMA(dataframe["ha_close"], timeperiod=3)
        dataframe["ema_slow"] = ta.EMA(dataframe["ha_close"], timeperiod=50)
        dataframe["volume_mean_slow"] = dataframe["volume"].rolling(window=30).mean()
        dataframe["rocr"] = ta.ROCR(dataframe["ha_close"], timeperiod=28)

        # RSI / Fisher
        rsi = ta.RSI(dataframe)
        dataframe["rsi"] = rsi
        fisher_in = 0.1 * (rsi - 50)
        dataframe["fisher"] = (np.exp(2 * fisher_in) - 1) / (np.exp(2 * fisher_in) + 1)

        # 1h informative
        inf_tf = "1h"
        informative = self.dp.get_pair_dataframe(pair=metadata["pair"], timeframe=inf_tf)

        if informative is None or informative.empty:
            dataframe["rocr_1h"] = np.nan
            return dataframe

        informative = informative.copy()
        informative["date"] = pd.to_datetime(informative["date"], utc=True, errors="coerce")
        informative = informative.dropna(subset=["date"])

        if informative.empty:
            dataframe["rocr_1h"] = np.nan
            return dataframe

        inf_heikinashi = qtpylib.heikinashi(informative)
        informative["ha_close"] = inf_heikinashi["close"]
        informative["rocr"] = ta.ROCR(informative["ha_close"], timeperiod=168)

        dataframe = merge_informative_pair(
            dataframe,
            informative[["date", "rocr"]],
            self.timeframe,
            inf_tf,
            ffill=True
        )

        if "rocr_1h" not in dataframe.columns:
            dataframe["rocr_1h"] = np.nan

        return dataframe

########################################################################################################################################################
# Enter Trade
########################################################################################################################################################
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["enter_tag"] = ""
        dataframe["enter_long"] = 0

        roc_condition = dataframe["rocr_1h"].gt(self.rocr_1h.value)

        bb_ha_condition = (
            (dataframe["lower"].shift().gt(0))
            & (dataframe["bbdelta"].gt(dataframe["ha_close"] * self.bbdelta_close.value))
            & (dataframe["closedelta"].gt(dataframe["ha_close"] * self.closedelta_close.value))
            & (dataframe["tail"].lt(dataframe["bbdelta"] * self.bbdelta_tail.value))
            & (dataframe["ha_close"].lt(dataframe["lower"].shift()))
            & (dataframe["ha_close"].le(dataframe["ha_close"].shift()))
        )

        ema_condition = (
            (dataframe["ha_close"] < dataframe["ema_slow"])
            & (dataframe["ha_close"] < self.close_bblower.value * dataframe["bb_lowerband"])
        )

        combined_conditions = roc_condition & (bb_ha_condition | ema_condition)

        dataframe.loc[combined_conditions, "enter_long"] = 1
        dataframe.loc[roc_condition & bb_ha_condition, "enter_tag"] += "bb_ha|"
        dataframe.loc[roc_condition & ema_condition, "enter_tag"] += "ema|"
        dataframe["enter_tag"] = dataframe["enter_tag"].str.rstrip("|")

        return dataframe

########################################################################################################################################################
# Exit Trade
########################################################################################################################################################
    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0
        dataframe["exit_tag"] = "no_exit"

        sell_conditions = (
            (dataframe["fisher"] > self.sell_fisher.value)
            & (dataframe["ha_high"].le(dataframe["ha_high"].shift(1)))
            & (dataframe["ha_high"].shift(1).le(dataframe["ha_high"].shift(2)))
            & (dataframe["ha_close"].le(dataframe["ha_close"].shift(1)))
            & (dataframe["ema_fast"] > dataframe["ha_close"])
            & ((dataframe["ha_close"] * self.sell_bbmiddle_close.value) > dataframe["bb_middleband"])
            & (dataframe["volume"] > 0)
        )

        dataframe.loc[sell_conditions, "exit_long"] = 1
        dataframe.loc[sell_conditions, "exit_tag"] = "fisher_ema_bearish"

        return dataframe