from freqtrade.strategy.interface import IStrategy
from typing import Dict, List
from pandas import DataFrame
from datetime import datetime, timedelta

import pandas as pd
import numpy as np
import talib.abstract as ta
import freqtrade.vendor.qtpylib.indicators as qtpylib

from freqtrade.persistence import Trade
from freqtrade.strategy import (
    stoploss_from_open,
    merge_informative_pair,
    DecimalParameter,
    IntParameter,
)

############################################################################
# Custom indicators and helper functions
############################################################################

def EWO(dataframe: DataFrame, ema_length: int = 5, ema2_length: int = 35) -> DataFrame:
    """
    NOTE: This is not the standard EWO (you used SMA and divide by low).
    Kept as-is to preserve your hyperopt space behaviour.
    """
    df = dataframe.copy()
    sma1 = ta.SMA(df, timeperiod=int(ema_length))
    sma2 = ta.SMA(df, timeperiod=int(ema2_length))
    return (sma1 - sma2) / df["low"] * 100


class DS_SOS_5m(IStrategy):

    ########################################################################
    # Hyperopt params (kept)
    ########################################################################
    buy_params = {
        "base_nb_candles_buy": 8,
        "ewo_high": 2.403,
        "ewo_high_2": -5.585,
        "ewo_low": -14.378,
        "lookback_candles": 3,
        "low_offset": 0.984,
        "low_offset_2": 0.942,
        "profit_threshold": 1.008,
        "rsi_buy": 72
    }

    sell_params = {
        "base_nb_candles_sell": 16,
        "high_offset": 1.084,
        "high_offset_2": 1.401,
        "pHSL": -0.15,
        "pPF_1": 0.016,
        "pPF_2": 0.024,
        "pSL_1": 0.014,
        "pSL_2": 0.022
    }

    slippage_protection = {
        "retries": 3,
        "max_slippage": -0.02
    }

    ########################################################################
    # Main config
    ########################################################################
    can_short = False

    minimal_roi = {"0": 10}  # effectively disables ROI exits

    ignore_roi_if_entry_signal = False

    stoploss = -0.25
    use_custom_stoploss = False  # backtest mode default

    trailing_stop = True         # backtest mode default
    trailing_stop_positive = 0.001
    trailing_stop_positive_offset = 0.01
    trailing_only_offset_is_reached = True

    use_entry_signal = True
    use_exit_signal = True       # you can turn off if you want trailing-only exits
    use_custom_exit = False

    exit_profit_only = False
    exit_profit_offset = 0.03

    timeframe = "5m"
    informative = "1h"

    process_only_new_candles = False
    startup_candle_count = 200

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
    order_time_in_force = {"entry": "gtc", "exit": "gtc"}

    plot_config = {
        "main_plot": {
            "ma_buy": {"color": "orange"},
            "ma_sell": {"color": "orange"},
        },
    }

    ########################################################################
    # Trade Protections (kept)
    ########################################################################
    @property
    def protections(self):
        return [
            {"method": "CooldownPeriod", "stop_duration_candles": 5},
            {
                "method": "MaxDrawdown",
                "lookback_period_candles": 72,   # 6h on 5m candles
                "trade_limit": 20,
                "stop_duration_candles": 6,
                "max_allowed_drawdown": 0.03,
            },
            {
                "method": "StoplossGuard",
                "lookback_period_candles": 48,   # 4h
                "trade_limit": 4,
                "stop_duration_candles": 4,
                "only_per_pair": False,
            },
            {
                "method": "LowProfitPairs",
                "lookback_period_candles": 24,   # 2h
                "trade_limit": 2,
                "stop_duration_candles": 12,     # 1h
                "required_profit": 0.02,
            },
            {
                "method": "LowProfitPairs",
                "lookback_period_candles": 144,  # 12h
                "trade_limit": 4,
                "stop_duration_candles": 24,     # 2h
                "required_profit": 0.04,
            },
        ]

    ########################################################################
    # Parameters
    ########################################################################
    base_nb_candles_buy = IntParameter(2, 20, default=buy_params["base_nb_candles_buy"], space="buy", optimize=True)
    base_nb_candles_sell = IntParameter(2, 25, default=sell_params["base_nb_candles_sell"], space="sell", optimize=True)

    low_offset = DecimalParameter(0.90, 0.99, default=buy_params["low_offset"], space="buy", optimize=True)
    low_offset_2 = DecimalParameter(0.90, 0.99, default=buy_params["low_offset_2"], space="buy", optimize=True)

    high_offset = DecimalParameter(0.95, 1.10, default=sell_params["high_offset"], space="sell", optimize=True)
    high_offset_2 = DecimalParameter(0.99, 1.50, default=sell_params["high_offset_2"], space="sell", optimize=True)

    fast_ewo = 50
    slow_ewo = 200

    lookback_candles = IntParameter(1, 24, default=buy_params["lookback_candles"], space="buy", optimize=True)
    profit_threshold = DecimalParameter(1.00, 1.03, default=buy_params["profit_threshold"], space="buy", optimize=True)

    ewo_low = DecimalParameter(-20.0, -8.0, default=buy_params["ewo_low"], space="buy", optimize=True)
    ewo_high = DecimalParameter(2.0, 12.0, default=buy_params["ewo_high"], space="buy", optimize=True)
    ewo_high_2 = DecimalParameter(-6.0, 12.0, default=buy_params["ewo_high_2"], space="buy", optimize=True)

    rsi_buy = IntParameter(50, 100, default=buy_params["rsi_buy"], space="buy", optimize=True)

    # Perkmeister-style custom stoploss params (kept)
    pHSL = DecimalParameter(-0.200, -0.040, default=sell_params["pHSL"], decimals=3, space="sell", optimize=True, load=True)
    pPF_1 = DecimalParameter(0.008, 0.020, default=sell_params["pPF_1"], decimals=3, space="sell", optimize=True, load=True)
    pSL_1 = DecimalParameter(0.008, 0.020, default=sell_params["pSL_1"], decimals=3, space="sell", optimize=True, load=True)

    # FIX: your default 0.024 must be inside range
    pPF_2 = DecimalParameter(0.020, 0.100, default=sell_params["pPF_2"], decimals=3, space="sell", optimize=True, load=True)
    pSL_2 = DecimalParameter(0.020, 0.070, default=sell_params["pSL_2"], decimals=3, space="sell", optimize=True, load=True)

    ########################################################################
    # Custom Stoploss (only used if use_custom_stoploss=True)
    ########################################################################
    def custom_stoploss(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs,
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

        return stoploss_from_open(sl_profit, current_profit)

    ########################################################################
    # Informative pairs
    ########################################################################
    def informative_pairs(self):
        pairs = self.dp.current_whitelist()
        return [(pair, self.informative) for pair in pairs]

    def informative_1h_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        assert self.dp, "DataProvider is required for multiple timeframes."

        inf = self.dp.get_pair_dataframe(pair=metadata["pair"], timeframe=self.informative)

        # No 1h data: return empty with correct merge key dtype
        if inf is None or inf.empty:
            empty = DataFrame(columns=["date"])
            empty["date"] = pd.to_datetime(empty["date"], utc=True)
            return empty

        # Force UTC datetime merge key
        inf["date"] = pd.to_datetime(inf["date"], utc=True, errors="coerce")

        inf["ema_50"] = ta.EMA(inf, timeperiod=50)
        inf["ema_200"] = ta.EMA(inf, timeperiod=200)
        inf["rsi"] = ta.RSI(inf, timeperiod=14)

        bb = qtpylib.bollinger_bands(qtpylib.typical_price(inf), window=20, stds=2)
        inf["bb_lowerband"] = bb["lower"]
        inf["bb_middleband"] = bb["mid"]
        inf["bb_upperband"] = bb["upper"]

        return inf

    ########################################################################
    # Normal timeframe indicators
    ########################################################################
    def normal_tf_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        for val in self.base_nb_candles_buy.range:
            dataframe[f"ma_buy_{val}"] = ta.EMA(dataframe, timeperiod=int(val))

        for val in self.base_nb_candles_sell.range:
            dataframe[f"ma_sell_{val}"] = ta.EMA(dataframe, timeperiod=int(val))

        dataframe["hma_50"] = qtpylib.hull_moving_average(dataframe["close"], window=50)
        dataframe["ema_100"] = ta.EMA(dataframe, timeperiod=100)
        dataframe["sma_9"] = ta.SMA(dataframe, timeperiod=9)

        dataframe["EWO"] = EWO(dataframe, self.fast_ewo, self.slow_ewo)

        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["rsi_fast"] = ta.RSI(dataframe, timeperiod=4)
        dataframe["rsi_slow"] = ta.RSI(dataframe, timeperiod=20)

        return dataframe

    ########################################################################
    # Populate indicators (safe merge)
    ########################################################################
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Ensure base timeframe date dtype
        dataframe["date"] = pd.to_datetime(dataframe["date"], utc=True, errors="coerce")

        inf = self.informative_1h_indicators(dataframe, metadata)

        if inf is None or inf.empty:
            # placeholders for logic using close_1h rolling
            dataframe["close_1h"] = np.nan
        else:
            dataframe = merge_informative_pair(
                dataframe,
                inf,
                self.timeframe,
                self.informative,
                ffill=True,
            )

        dataframe = self.normal_tf_indicators(dataframe, metadata)
        return dataframe

    ########################################################################
    # Entry signals
    ########################################################################
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        if "enter_tag" not in dataframe.columns:
            dataframe["enter_tag"] = np.nan
        dataframe["enter_tag"] = dataframe["enter_tag"].astype(object)

        dataframe["enter_long"] = 0

        # If close_1h is NaN, rolling().max() will be NaN and comparisons will be False.
        dont_enter = (
            dataframe["close_1h"].rolling(self.lookback_candles.value).max()
            < (dataframe["close"] * self.profit_threshold.value)
        )

        ewo1 = (
            (dataframe["rsi_fast"] < 35)
            & (dataframe["close"] < dataframe[f"ma_buy_{self.base_nb_candles_buy.value}"] * self.low_offset.value)
            & (dataframe["EWO"] > self.ewo_high.value)
            & (dataframe["rsi"] < self.rsi_buy.value)
            & (dataframe["volume"] > 0)
            & (dataframe["close"] < dataframe[f"ma_sell_{self.base_nb_candles_sell.value}"] * self.high_offset.value)
        )
        dataframe.loc[ewo1, ["enter_long", "enter_tag"]] = [1, "ewo1"]

        ewo2 = (
            (dataframe["rsi_fast"] < 35)
            & (dataframe["close"] < dataframe[f"ma_buy_{self.base_nb_candles_buy.value}"] * self.low_offset_2.value)
            & (dataframe["EWO"] > self.ewo_high_2.value)
            & (dataframe["rsi"] < self.rsi_buy.value)
            & (dataframe["volume"] > 0)
            & (dataframe["close"] < dataframe[f"ma_sell_{self.base_nb_candles_sell.value}"] * self.high_offset.value)
            & (dataframe["rsi"] < 25)
        )
        dataframe.loc[ewo2, ["enter_long", "enter_tag"]] = [1, "ewo2"]

        ewolow = (
            (dataframe["rsi_fast"] < 35)
            & (dataframe["close"] < dataframe[f"ma_buy_{self.base_nb_candles_buy.value}"] * self.low_offset.value)
            & (dataframe["EWO"] < self.ewo_low.value)
            & (dataframe["volume"] > 0)
            & (dataframe["close"] < dataframe[f"ma_sell_{self.base_nb_candles_sell.value}"] * self.high_offset.value)
        )
        dataframe.loc[ewolow, ["enter_long", "enter_tag"]] = [1, "ewolow"]

        dataframe.loc[dont_enter, ["enter_long", "enter_tag"]] = [0, np.nan]
        return dataframe

    ########################################################################
    # Exit signals
    ########################################################################
    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0
        dataframe["exit_tag"] = None

        cond_sma_rsi = (
            (dataframe["close"] > dataframe["sma_9"])
            & (dataframe["close"] > (dataframe[f"ma_sell_{self.base_nb_candles_sell.value}"] * self.high_offset_2.value))
            & (dataframe["rsi"] > 50)
            & (dataframe["volume"] > 0)
            & (dataframe["rsi_fast"] > dataframe["rsi_slow"])
        )

        cond_hma_pullback = (
            (dataframe["close"] < dataframe["hma_50"])
            & (dataframe["close"] > (dataframe[f"ma_sell_{self.base_nb_candles_sell.value}"] * self.high_offset.value))
            & (dataframe["volume"] > 0)
            & (dataframe["rsi_fast"] > dataframe["rsi_slow"])
        )

        dataframe.loc[cond_sma_rsi, ["exit_long", "exit_tag"]] = [1, "sma_rsi_exit"]
        dataframe.loc[cond_hma_pullback, ["exit_long", "exit_tag"]] = [1, "hma_pullback_exit"]

        return dataframe

    ########################################################################
    # Confirm exit (kept)
    ########################################################################
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
        **kwargs,
    ) -> bool:
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        last_candle = dataframe.iloc[-1]

        if last_candle is not None and exit_reason in ["sell_signal"]:
            if (last_candle["hma_50"] * 1.149 > last_candle["ema_100"]) and (last_candle["close"] < last_candle["ema_100"] * 0.951):
                return False

        # slippage protection
        try:
            state = self.slippage_protection["__pair_retries"]
        except KeyError:
            state = self.slippage_protection["__pair_retries"] = {}

        candle = dataframe.iloc[-1].squeeze()
        slippage = (rate / candle["close"]) - 1

        if slippage < self.slippage_protection["max_slippage"]:
            pair_retries = state.get(pair, 0)
            if pair_retries < self.slippage_protection["retries"]:
                state[pair] = pair_retries + 1
                return False

        state[pair] = 0
        return True
