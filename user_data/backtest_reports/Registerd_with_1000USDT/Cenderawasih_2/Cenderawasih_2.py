import logging
import math
from functools import reduce

import pandas_ta as pta
import talib.abstract as ta
from pandas import DataFrame, Series

from freqtrade.strategy import IStrategy, DecimalParameter, IntParameter

logger = logging.getLogger(__name__)


def tv_wma(series: Series, length: int = 9) -> Series:
    """
    TradingView-style WMA
    """
    length = int(length)
    if length < 1:
        return series.copy()

    weights = list(range(1, length + 1))
    weight_sum = sum(weights)

    return series.rolling(length).apply(
        lambda x: (x * weights).sum() / weight_sum,
        raw=True
    )


def tv_hma(dataframe: DataFrame, length: int = 9, field: str = "close") -> Series:
    """
    TradingView-style HMA
    """
    length = int(length)
    if length < 1:
        return dataframe[field].copy()

    half_length = max(1, length // 2)
    sqrt_length = max(1, int(math.sqrt(length)))

    wma_half = tv_wma(dataframe[field], half_length)
    wma_full = tv_wma(dataframe[field], length)
    hull_input = 2 * wma_half - wma_full

    return tv_wma(hull_input, sqrt_length)


def zema(dataframe: DataFrame, period: int, field: str = "close") -> Series:
    """
    Zero-lag EMA approximation
    """
    period = int(period)
    ema1 = ta.EMA(dataframe[field], timeperiod=period)
    ema2 = ta.EMA(ema1, timeperiod=period)
    d = ema1 - ema2
    return ema1 + d


def rvol(dataframe: DataFrame, window: int = 24) -> Series:
    avg_volume = ta.SMA(dataframe["volume"], timeperiod=int(window))
    return dataframe["volume"] / avg_volume


class Cenderawasih_2(IStrategy):
    INTERFACE_VERSION = 3

    def version(self) -> str:
        return "v2_fixed"

    minimal_roi = {
        "0": 100.0
    }

    buy_params = {
        "base_nb_candles_buy_hma": 37,
        "low_offset_hma": 0.915,
        "base_nb_candles_buy_ema": 32,
        "low_offset_ema": 1.01,
        "buy_length_volatility": 10,
        "buy_max_volatility": 1.62,
        "base_nb_candles_buy_vwma": 54,
        "low_offset_vwma": 0.988,
        "buy_rsi_1": 65,
        "buy_rsi_fast_1": 39,
        "rsi_buy_ema": 56,
        "buy_length_volume": 26,
        "buy_volume_volatility": 2.73,
    }

    sell_params = {
        "base_nb_candles_sell_hma": 87,
        "high_offset_hma": 0.933,
        "base_nb_candles_sell_ema": 16,
        "high_offset_ema": 0.97,
        "base_nb_candles_sell_ema2": 70,
        "high_offset_ema2": 0.989,
        "base_nb_candles_sell_ema3": 82,
        "high_offset_ema3": 0.927,
    }

    protection_params = {
        "cooldown_lookback": 2,
    }

    cooldown_lookback = IntParameter(2, 48, default=2, space="protection", optimize=False)

    @property
    def protections(self):
        return [
            {
                "method": "CooldownPeriod",
                "stop_duration_candles": self.cooldown_lookback.value
            }
        ]

    dummy = IntParameter(20, 70, default=61, space="buy", optimize=False)

    rsi_buy_ema = IntParameter(20, 70, default=56, space="buy", optimize=False)
    buy_rsi_1 = IntParameter(0, 70, default=65, space="buy", optimize=False)
    buy_rsi_fast_1 = IntParameter(0, 70, default=39, space="buy", optimize=False)

    optimize_buy_hma = False
    base_nb_candles_buy_hma = IntParameter(5, 100, default=37, space="buy", optimize=optimize_buy_hma)
    low_offset_hma = DecimalParameter(0.9, 0.99, default=0.915, space="buy", optimize=optimize_buy_hma)

    optimize_buy_ema = False
    base_nb_candles_buy_ema = IntParameter(5, 100, default=32, space="buy", optimize=optimize_buy_ema)
    low_offset_ema = DecimalParameter(0.9, 1.1, default=1.01, space="buy", optimize=optimize_buy_ema)

    optimize_buy_vwma = False
    base_nb_candles_buy_vwma = IntParameter(5, 80, default=54, space="buy", optimize=optimize_buy_vwma)
    low_offset_vwma = DecimalParameter(0.9, 0.99, default=0.988, space="buy", optimize=optimize_buy_vwma)

    optimize_buy_volatility = False
    buy_length_volatility = IntParameter(10, 200, default=10, space="buy", optimize=optimize_buy_volatility)
    buy_min_volatility = DecimalParameter(0, 0.5, default=0, decimals=2, space="buy", optimize=False)
    buy_max_volatility = DecimalParameter(0.5, 2, default=1.62, decimals=2, space="buy", optimize=optimize_buy_volatility)

    optimize_buy_volume = False
    buy_length_volume = IntParameter(5, 100, default=26, space="buy", optimize=optimize_buy_volume)
    buy_volume_volatility = DecimalParameter(0.5, 3, default=2.73, decimals=2, space="buy", optimize=optimize_buy_volume)

    optimize_sell_hma = False
    base_nb_candles_sell_hma = IntParameter(5, 100, default=87, space="sell", optimize=optimize_sell_hma)
    high_offset_hma = DecimalParameter(0.9, 1.1, default=0.933, space="sell", optimize=optimize_sell_hma)

    optimize_sell_ema = False
    base_nb_candles_sell_ema = IntParameter(5, 100, default=16, space="sell", optimize=optimize_sell_ema)
    high_offset_ema = DecimalParameter(0.9, 1.1, default=0.97, space="sell", optimize=optimize_sell_ema)

    optimize_sell_ema2 = False
    base_nb_candles_sell_ema2 = IntParameter(5, 100, default=70, space="sell", optimize=optimize_sell_ema2)
    high_offset_ema2 = DecimalParameter(0.9, 1.1, default=0.989, space="sell", optimize=optimize_sell_ema2)

    optimize_sell_ema3 = False
    base_nb_candles_sell_ema3 = IntParameter(5, 100, default=82, space="sell", optimize=optimize_sell_ema3)
    high_offset_ema3 = DecimalParameter(0.9, 1.1, default=0.927, space="sell", optimize=optimize_sell_ema3)

    stoploss = -0.098

    trailing_stop = False
    trailing_stop_positive = 0.001
    trailing_stop_positive_offset = 0.01
    trailing_only_offset_is_reached = True

    use_exit_signal = True
    exit_profit_only = False
    exit_profit_offset = 0.01
    ignore_roi_if_entry_signal = False

    timeframe = "5m"
    process_only_new_candles = True
    startup_candle_count = 999

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["rsi"] = ta.RSI(dataframe["close"], timeperiod=14)
        dataframe["rsi_fast"] = ta.RSI(dataframe["close"], timeperiod=4)

        dataframe["live_data_ok"] = (
            dataframe["volume"].rolling(window=72, min_periods=72).min() > 0
        )

        if not self.optimize_buy_hma:
            dataframe["hma_offset_buy"] = (
                tv_hma(dataframe, int(self.base_nb_candles_buy_hma.value)) * self.low_offset_hma.value
            )

        if not self.optimize_buy_ema:
            dataframe["ema_offset_buy"] = (
                ta.EMA(dataframe["close"], timeperiod=int(self.base_nb_candles_buy_ema.value))
                * self.low_offset_ema.value
            )

        if not self.optimize_buy_vwma:
            dataframe["vwma_offset_buy"] = (
                pta.vwma(
                    close=dataframe["close"],
                    volume=dataframe["volume"],
                    length=int(self.base_nb_candles_buy_vwma.value)
                ) * self.low_offset_vwma.value
            )

        if not self.optimize_buy_volatility:
            df_std = dataframe["close"].rolling(int(self.buy_length_volatility.value)).std()
            dataframe["volatility"] = (
                (df_std > self.buy_min_volatility.value)
                & (df_std < self.buy_max_volatility.value)
            )

        if not self.optimize_buy_volume:
            df_rvol = rvol(dataframe, int(self.buy_length_volume.value))
            dataframe["volume_volatility"] = df_rvol < self.buy_volume_volatility.value

        if not self.optimize_sell_hma:
            dataframe["hma_offset_sell"] = (
                tv_hma(dataframe, int(self.base_nb_candles_sell_hma.value)) * self.high_offset_hma.value
            )

        if not self.optimize_sell_ema:
            dataframe["ema_offset_sell"] = (
                ta.EMA(dataframe["close"], timeperiod=int(self.base_nb_candles_sell_ema.value))
                * self.high_offset_ema.value
            )

        if not self.optimize_sell_ema2:
            dataframe["ema_offset_sell2"] = (
                ta.EMA(dataframe["close"], timeperiod=int(self.base_nb_candles_sell_ema2.value))
                * self.high_offset_ema2.value
            )

        if not self.optimize_sell_ema3:
            dataframe["ema_offset_sell3"] = (
                ta.EMA(dataframe["close"], timeperiod=int(self.base_nb_candles_sell_ema3.value))
                * self.high_offset_ema3.value
            )

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        conditions = []

        if self.optimize_buy_hma:
            dataframe["hma_offset_buy"] = (
                tv_hma(dataframe, int(self.base_nb_candles_buy_hma.value)) * self.low_offset_hma.value
            )

        if self.optimize_buy_ema:
            dataframe["ema_offset_buy"] = (
                ta.EMA(dataframe["close"], timeperiod=int(self.base_nb_candles_buy_ema.value))
                * self.low_offset_ema.value
            )

        if self.optimize_buy_vwma:
            dataframe["vwma_offset_buy"] = (
                pta.vwma(
                    close=dataframe["close"],
                    volume=dataframe["volume"],
                    length=int(self.base_nb_candles_buy_vwma.value)
                ) * self.low_offset_vwma.value
            )

        if self.optimize_buy_volatility:
            df_std = dataframe["close"].rolling(int(self.buy_length_volatility.value)).std()
            dataframe["volatility"] = (
                (df_std > self.buy_min_volatility.value)
                & (df_std < self.buy_max_volatility.value)
            )

        if self.optimize_buy_volume:
            df_rvol = rvol(dataframe, int(self.buy_length_volume.value))
            dataframe["volume_volatility"] = df_rvol < self.buy_volume_volatility.value

        dataframe["enter_tag"] = ""
        dataframe["enter_long"] = 0

        add_check = (
            dataframe["live_data_ok"]
            & dataframe["volatility"].fillna(False)
            & dataframe["volume_volatility"].fillna(False)
            & (dataframe["close"] < dataframe["ema_offset_buy"])
            & (dataframe["volume"] > 0)
            & (dataframe["rsi_fast"] < self.buy_rsi_fast_1.value)
            & (dataframe["rsi"] < self.buy_rsi_1.value)
        )

        buy_offset_hma = dataframe["close"] < dataframe["hma_offset_buy"]
        conditions.append(buy_offset_hma)
        dataframe["enter_tag"] = dataframe["enter_tag"].mask(
            buy_offset_hma,
            dataframe["enter_tag"] + "hma "
        )

        buy_offset_vwma = dataframe["close"] < dataframe["vwma_offset_buy"]
        conditions.append(buy_offset_vwma)
        dataframe["enter_tag"] = dataframe["enter_tag"].mask(
            buy_offset_vwma,
            dataframe["enter_tag"] + "vwma "
        )

        if conditions:
            dataframe.loc[
                reduce(lambda x, y: x | y, conditions) & add_check,
                "enter_long"
            ] = 1

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        if self.optimize_sell_hma:
            dataframe["hma_offset_sell"] = (
                tv_hma(dataframe, int(self.base_nb_candles_sell_hma.value)) * self.high_offset_hma.value
            )

        if self.optimize_sell_ema:
            dataframe["ema_offset_sell"] = (
                ta.EMA(dataframe["close"], timeperiod=int(self.base_nb_candles_sell_ema.value))
                * self.high_offset_ema.value
            )

        if self.optimize_sell_ema2:
            dataframe["ema_offset_sell2"] = (
                ta.EMA(dataframe["close"], timeperiod=int(self.base_nb_candles_sell_ema2.value))
                * self.high_offset_ema2.value
            )

        if self.optimize_sell_ema3:
            dataframe["ema_offset_sell3"] = (
                ta.EMA(dataframe["close"], timeperiod=int(self.base_nb_candles_sell_ema3.value))
                * self.high_offset_ema3.value
            )

        dataframe["exit_tag"] = ""
        dataframe["exit_long"] = 0
        conditions = []

        sell_cond_1 = dataframe["close"] > dataframe["hma_offset_sell"]
        conditions.append(sell_cond_1)
        dataframe["exit_tag"] = dataframe["exit_tag"].mask(
            sell_cond_1,
            dataframe["exit_tag"] + "HMA_1 "
        )

        sell_cond_3 = (
            (dataframe["close"] < dataframe["ema_offset_sell3"]).astype(int).rolling(2).sum() == 2
        )
        conditions.append(sell_cond_3)
        dataframe["exit_tag"] = dataframe["exit_tag"].mask(
            sell_cond_3,
            dataframe["exit_tag"] + "EMA_3 "
        )

        sell_cond_2 = dataframe["close"] > dataframe["ema_offset_sell"]
        conditions.append(sell_cond_2)
        dataframe["exit_tag"] = dataframe["exit_tag"].mask(
            sell_cond_2,
            dataframe["exit_tag"] + "EMA_1 "
        )

        sell_cond_4 = dataframe["close"] < dataframe["ema_offset_sell2"]
        conditions.append(sell_cond_4)
        dataframe["exit_tag"] = dataframe["exit_tag"].mask(
            sell_cond_4,
            dataframe["exit_tag"] + "EMA_2 "
        )

        add_check = dataframe["volume"] > 0

        if conditions:
            dataframe.loc[
                reduce(lambda x, y: x | y, conditions) & add_check,
                "exit_long"
            ] = 1

        return dataframe