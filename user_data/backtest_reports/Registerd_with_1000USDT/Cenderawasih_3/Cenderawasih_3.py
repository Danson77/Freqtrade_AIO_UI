import logging
import math
from functools import reduce

import talib.abstract as ta
from pandas import DataFrame, Series
from freqtrade.strategy import IStrategy, DecimalParameter, IntParameter

logger = logging.getLogger(__name__)


class Cenderawasih_3(IStrategy):
    INTERFACE_VERSION = 3

    def version(self) -> str:
        return "v3_fixed"

    minimal_roi = {
        "0": 100.0
    }

    buy_params = {
        "base_nb_candles_buy_hma": 42,
        "low_offset_hma": 0.899,
    }

    sell_params = {
        "base_nb_candles_sell_ema": 31,
        "high_offset_ema": 1.0,
        "base_nb_candles_sell_ema2": 87,
        "high_offset_ema2": 0.84,
        "base_nb_candles_sell_ema3": 98,
        "high_offset_ema3": 0.969,
        "base_nb_candles_sell_ema4": 91,
        "high_offset_ema4": 1.113,
        "base_nb_candles_sell_zema": 93,
        "high_offset_zema": 1.089,
        "base_nb_candles_sell_zema2": 57,
        "high_offset_zema2": 0.879,
    }

    optimize_buy_hma = False
    base_nb_candles_buy_hma = IntParameter(5, 100, default=42, space="buy", optimize=optimize_buy_hma)
    low_offset_hma = DecimalParameter(0.6, 0.99, default=0.899, space="buy", optimize=optimize_buy_hma)

    optimize_sell_zema = False
    base_nb_candles_sell_zema = IntParameter(5, 100, default=93, space="sell", optimize=optimize_sell_zema)
    high_offset_zema = DecimalParameter(1.0, 1.2, default=1.089, space="sell", optimize=optimize_sell_zema)

    optimize_sell_zema2 = False
    base_nb_candles_sell_zema2 = IntParameter(5, 100, default=57, space="sell", optimize=optimize_sell_zema2)
    high_offset_zema2 = DecimalParameter(0.6, 0.99, default=0.879, space="sell", optimize=optimize_sell_zema2)

    optimize_sell_ema = False
    base_nb_candles_sell_ema = IntParameter(5, 100, default=31, space="sell", optimize=optimize_sell_ema)
    high_offset_ema = DecimalParameter(1.0, 1.2, default=1.0, space="sell", optimize=optimize_sell_ema)

    optimize_sell_ema2 = False
    base_nb_candles_sell_ema2 = IntParameter(5, 100, default=87, space="sell", optimize=optimize_sell_ema2)
    high_offset_ema2 = DecimalParameter(0.7, 0.99, default=0.84, space="sell", optimize=optimize_sell_ema2)

    optimize_sell_ema3 = False
    base_nb_candles_sell_ema3 = IntParameter(5, 100, default=98, space="sell", optimize=optimize_sell_ema3)
    high_offset_ema3 = DecimalParameter(0.7, 0.99, default=0.969, space="sell", optimize=optimize_sell_ema3)

    optimize_sell_ema4 = False
    base_nb_candles_sell_ema4 = IntParameter(5, 100, default=91, space="sell", optimize=optimize_sell_ema4)
    high_offset_ema4 = DecimalParameter(1.0, 1.2, default=1.113, space="sell", optimize=optimize_sell_ema4)

    stoploss = -0.1

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
        dataframe["live_data_ok"] = (
            dataframe["volume"].rolling(window=72, min_periods=72).min() > 0
        )

        if not self.optimize_buy_hma:
            dataframe["hma_offset_buy"] = (
                tv_hma(dataframe, int(self.base_nb_candles_buy_hma.value)) * self.low_offset_hma.value
            )

        if not self.optimize_sell_zema:
            dataframe["zema_offset_sell"] = (
                zema(dataframe, int(self.base_nb_candles_sell_zema.value)) * self.high_offset_zema.value
            )

        if not self.optimize_sell_zema2:
            dataframe["zema_offset_sell2"] = (
                zema(dataframe, int(self.base_nb_candles_sell_zema2.value)) * self.high_offset_zema2.value
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

        if not self.optimize_sell_ema4:
            dataframe["ema_offset_sell4"] = (
                ta.EMA(dataframe["close"], timeperiod=int(self.base_nb_candles_sell_ema4.value))
                * self.high_offset_ema4.value
            )

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        conditions = []

        if self.optimize_buy_hma:
            dataframe["hma_offset_buy"] = (
                tv_hma(dataframe, int(self.base_nb_candles_buy_hma.value)) * self.low_offset_hma.value
            )

        dataframe["enter_tag"] = ""
        dataframe["enter_long"] = 0

        add_check = (
            dataframe["live_data_ok"]
            & (dataframe["volume"] > 0)
        )

        buy_offset_hma = dataframe["close"] < dataframe["hma_offset_buy"]
        conditions.append(buy_offset_hma)

        dataframe["enter_tag"] = dataframe["enter_tag"].mask(
            buy_offset_hma,
            dataframe["enter_tag"] + "hma "
        )

        if conditions:
            dataframe.loc[
                reduce(lambda x, y: x | y, conditions) & add_check,
                "enter_long"
            ] = 1

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        if self.optimize_sell_zema:
            dataframe["zema_offset_sell"] = (
                zema(dataframe, int(self.base_nb_candles_sell_zema.value)) * self.high_offset_zema.value
            )

        if self.optimize_sell_zema2:
            dataframe["zema_offset_sell2"] = (
                zema(dataframe, int(self.base_nb_candles_sell_zema2.value)) * self.high_offset_zema2.value
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

        if self.optimize_sell_ema4:
            dataframe["ema_offset_sell4"] = (
                ta.EMA(dataframe["close"], timeperiod=int(self.base_nb_candles_sell_ema4.value))
                * self.high_offset_ema4.value
            )

        dataframe["exit_tag"] = ""
        dataframe["exit_long"] = 0
        conditions = []

        sell_zema_1 = dataframe["close"] > dataframe["zema_offset_sell"]
        conditions.append(sell_zema_1)
        dataframe["exit_tag"] = dataframe["exit_tag"].mask(
            sell_zema_1,
            dataframe["exit_tag"] + "ZEMA_1 "
        )

        sell_zema_2 = dataframe["close"] < dataframe["zema_offset_sell2"]
        conditions.append(sell_zema_2)
        dataframe["exit_tag"] = dataframe["exit_tag"].mask(
            sell_zema_2,
            dataframe["exit_tag"] + "ZEMA_2 "
        )

        sell_ema_1 = dataframe["close"] > dataframe["ema_offset_sell"]
        conditions.append(sell_ema_1)
        dataframe["exit_tag"] = dataframe["exit_tag"].mask(
            sell_ema_1,
            dataframe["exit_tag"] + "EMA_1 "
        )

        sell_ema_2 = (
            (dataframe["close"] < dataframe["ema_offset_sell2"]).astype(int).rolling(2).min() > 0
        )
        conditions.append(sell_ema_2)
        dataframe["exit_tag"] = dataframe["exit_tag"].mask(
            sell_ema_2,
            dataframe["exit_tag"] + "EMA_2 "
        )

        sell_ema_3 = dataframe["close"] < dataframe["ema_offset_sell3"]
        conditions.append(sell_ema_3)
        dataframe["exit_tag"] = dataframe["exit_tag"].mask(
            sell_ema_3,
            dataframe["exit_tag"] + "EMA_3 "
        )

        sell_ema_4 = (
            (dataframe["close"] > dataframe["ema_offset_sell4"]).astype(int).rolling(2).min() > 0
        )
        conditions.append(sell_ema_4)
        dataframe["exit_tag"] = dataframe["exit_tag"].mask(
            sell_ema_4,
            dataframe["exit_tag"] + "EMA_4 "
        )

        add_check = (
            dataframe["live_data_ok"]
            & (dataframe["volume"] > 0)
        )

        if conditions:
            dataframe.loc[
                reduce(lambda x, y: x | y, conditions) & add_check,
                "exit_long"
            ] = 1

        return dataframe


def tv_wma(series: Series, length: int = 9) -> Series:
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
    length = int(length)
    if length < 1:
        return dataframe[field].copy()

    half_length = max(1, length // 2)
    sqrt_length = max(1, int(math.sqrt(length)))

    wma_half = tv_wma(dataframe[field], half_length)
    wma_full = tv_wma(dataframe[field], length)
    h = 2 * wma_half - wma_full

    return tv_wma(h, sqrt_length)


def zema(dataframe: DataFrame, period: int, field: str = "close") -> Series:
    ema1 = ta.EMA(dataframe[field], timeperiod=int(period))
    ema2 = ta.EMA(ema1, timeperiod=int(period))
    d = ema1 - ema2
    return ema1 + d