from datetime import datetime, timedelta, timezone
from functools import reduce
from typing import List

import freqtrade.vendor.qtpylib.indicators as qtpylib
import numpy as np
import pandas as pd
import pandas_ta as pta
import talib.abstract as ta
from freqtrade.persistence import Trade, PairLocks
from freqtrade.strategy import (
    BooleanParameter,
    DecimalParameter,
    IntParameter,
    stoploss_from_open,
    merge_informative_pair,
)
from freqtrade.strategy.interface import IStrategy
from pandas import DataFrame, Series
import logging

logger = logging.getLogger(__name__)


def pct_change(a, b):
    return (b - a) / a


def EWO(dataframe, ema_length=5, ema2_length=35):
    df = dataframe.copy()
    ema1 = ta.EMA(df, timeperiod=ema_length)
    ema2 = ta.EMA(df, timeperiod=ema2_length)
    emadif = (ema1 - ema2) / df["low"] * 100
    return emadif


def bollinger_bands(stock_price, window_size, num_of_std):
    rolling_mean = stock_price.rolling(window=window_size).mean()
    rolling_std = stock_price.rolling(window=window_size).std()
    lower_band = rolling_mean - (rolling_std * num_of_std)
    return np.nan_to_num(rolling_mean), np.nan_to_num(lower_band)


def ha_typical_price(bars):
    res = (bars["ha_high"] + bars["ha_low"] + bars["ha_close"]) / 3.0
    return Series(index=bars.index, data=res)


class ClucHAnix_BB_RPB_MOD_trailing_buy(IStrategy):
    INTERFACE_VERSION = 3
    can_short = False

    buy_params = {
        "antipump_threshold": 0.133,
        "buy_btc_safe_1d": -0.311,
        "clucha_bbdelta_close": 0.04796,
        "clucha_bbdelta_tail": 0.93112,
        "clucha_close_bblower": 0.01645,
        "clucha_closedelta_close": 0.00931,
        "clucha_enabled": False,
        "clucha_rocr_1h": 0.41663,
        "cofi_adx": 8,
        "cofi_ema": 0.639,
        "cofi_enabled": False,
        "cofi_ewo_high": 5.6,
        "cofi_fastd": 40,
        "cofi_fastk": 13,
        "ewo_1_enabled": False,
        "ewo_1_rsi_14": 45,
        "ewo_1_rsi_4": 7,
        "ewo_candles_buy": 13,
        "ewo_candles_sell": 19,
        "ewo_high": 5.249,
        "ewo_high_offset": 1.04116,
        "ewo_low": -11.424,
        "ewo_low_enabled": True,
        "ewo_low_offset": 0.97463,
        "ewo_low_rsi_4": 35,
        "lambo1_ema_14_factor": 1.054,
        "lambo1_enabled": False,
        "lambo1_rsi_14_limit": 26,
        "lambo1_rsi_4_limit": 18,
        "lambo2_ema_14_factor": 0.981,
        "lambo2_enabled": True,
        "lambo2_rsi_14_limit": 39,
        "lambo2_rsi_4_limit": 44,
        "local_trend_bb_factor": 0.823,
        "local_trend_closedelta": 19.253,
        "local_trend_ema_diff": 0.125,
        "local_trend_enabled": True,
        "nfi32_cti_limit": -1.09639,
        "nfi32_enabled": True,
        "nfi32_rsi_14": 15,
        "nfi32_rsi_4": 49,
        "nfi32_sma_factor": 0.93391,
    }

    sell_params = {
        "pHSL": -0.32,
        "pPF_1": 0.02,
        "pPF_2": 0.047,
        "pSL_1": 0.02,
        "pSL_2": 0.046,
        "sell-fisher": 0.38414,
        "sell-bbmiddle-close": 1.07634,
    }

    minimal_roi = {
        "0": 0.05,
        "15": 0.04,
        "51": 0.03,
        "81": 0.02,
        "112": 0.01,
        "154": 0.0001,
        "399": 0,
    }

    stoploss = -0.99

    trailing_stop = False
    trailing_stop_positive = 0.001
    trailing_stop_positive_offset = 0.012
    trailing_only_offset_is_reached = False

    timeframe = "5m"

    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False
    use_custom_stoploss = True

    process_only_new_candles = False
    startup_candle_count = 200

    custom_info_trail_buy = dict()

    trailing_buy_order_enabled = True
    trailing_expire_seconds = 1800
    trailing_buy_uptrend_enabled = False
    trailing_expire_seconds_uptrend = 90
    min_uptrend_trailing_profit = 0.02
    debug_mode = True
    trailing_buy_max_stop = 0.02
    trailing_buy_max_buy = 0.000

    init_trailing_dict = {
        "trailing_buy_order_started": False,
        "trailing_buy_order_uplimit": 0,
        "start_trailing_price": 0,
        "enter_tag": None,
        "start_trailing_time": None,
        "offset": 0,
        "allow_trailing": False,
    }

    pHSL = DecimalParameter(-0.500, -0.040, default=-0.08, decimals=3, space="sell", load=True)
    pPF_1 = DecimalParameter(0.008, 0.020, default=0.016, decimals=3, space="sell", load=True)
    pSL_1 = DecimalParameter(0.008, 0.020, default=0.011, decimals=3, space="sell", load=True)
    pPF_2 = DecimalParameter(0.040, 0.100, default=0.080, decimals=3, space="sell", load=True)
    pSL_2 = DecimalParameter(0.020, 0.070, default=0.040, decimals=3, space="sell", load=True)

    clucha_bbdelta_close = DecimalParameter(0.01, 0.05, default=buy_params["clucha_bbdelta_close"], decimals=5, space="buy", optimize=True)
    clucha_bbdelta_tail = DecimalParameter(0.7, 1.2, default=buy_params["clucha_bbdelta_tail"], decimals=5, space="buy", optimize=True)
    clucha_close_bblower = DecimalParameter(0.001, 0.05, default=buy_params["clucha_close_bblower"], decimals=5, space="buy", optimize=True)
    clucha_closedelta_close = DecimalParameter(0.001, 0.05, default=buy_params["clucha_closedelta_close"], decimals=5, space="buy", optimize=True)
    clucha_rocr_1h = DecimalParameter(0.1, 1.0, default=buy_params["clucha_rocr_1h"], decimals=5, space="buy", optimize=True)

    lambo1_ema_14_factor = DecimalParameter(0.8, 1.2, decimals=3, default=buy_params["lambo1_ema_14_factor"], space="buy", optimize=True)
    lambo1_rsi_4_limit = IntParameter(5, 60, default=buy_params["lambo1_rsi_4_limit"], space="buy", optimize=True)
    lambo1_rsi_14_limit = IntParameter(5, 60, default=buy_params["lambo1_rsi_14_limit"], space="buy", optimize=True)

    lambo2_ema_14_factor = DecimalParameter(0.8, 1.2, decimals=3, default=buy_params["lambo2_ema_14_factor"], space="buy", optimize=True)
    lambo2_rsi_4_limit = IntParameter(5, 60, default=buy_params["lambo2_rsi_4_limit"], space="buy", optimize=True)
    lambo2_rsi_14_limit = IntParameter(5, 60, default=buy_params["lambo2_rsi_14_limit"], space="buy", optimize=True)

    local_trend_ema_diff = DecimalParameter(0, 0.2, default=buy_params["local_trend_ema_diff"], space="buy", optimize=True)
    local_trend_bb_factor = DecimalParameter(0.8, 1.2, default=buy_params["local_trend_bb_factor"], space="buy", optimize=True)
    local_trend_closedelta = DecimalParameter(5.0, 30.0, default=buy_params["local_trend_closedelta"], space="buy", optimize=True)

    ewo_candles_buy = IntParameter(2, 30, default=buy_params["ewo_candles_buy"], space="buy", optimize=True)
    ewo_candles_sell = IntParameter(2, 35, default=buy_params["ewo_candles_sell"], space="buy", optimize=True)
    ewo_low_offset = DecimalParameter(0.7, 1.2, default=buy_params["ewo_low_offset"], decimals=5, space="buy", optimize=True)
    ewo_high_offset = DecimalParameter(0.75, 1.5, default=buy_params["ewo_high_offset"], decimals=5, space="buy", optimize=True)
    ewo_high = DecimalParameter(2.0, 15.0, default=buy_params["ewo_high"], space="buy", optimize=True)
    ewo_1_rsi_14 = IntParameter(10, 100, default=buy_params["ewo_1_rsi_14"], space="buy", optimize=True)
    ewo_1_rsi_4 = IntParameter(1, 50, default=buy_params["ewo_1_rsi_4"], space="buy", optimize=True)
    ewo_low_rsi_4 = IntParameter(1, 50, default=buy_params["ewo_low_rsi_4"], space="buy", optimize=True)
    ewo_low = DecimalParameter(-20.0, -8.0, default=buy_params["ewo_low"], space="buy", optimize=True)

    cofi_ema = DecimalParameter(0.6, 1.4, default=buy_params["cofi_ema"], space="buy", optimize=True)
    cofi_fastk = IntParameter(1, 100, default=buy_params["cofi_fastk"], space="buy", optimize=True)
    cofi_fastd = IntParameter(1, 100, default=buy_params["cofi_fastd"], space="buy", optimize=True)
    cofi_adx = IntParameter(1, 100, default=buy_params["cofi_adx"], space="buy", optimize=True)
    cofi_ewo_high = DecimalParameter(1.0, 15.0, default=buy_params["cofi_ewo_high"], space="buy", optimize=True)

    nfi32_rsi_4 = IntParameter(1, 100, default=buy_params["nfi32_rsi_4"], space="buy", optimize=True)
    nfi32_rsi_14 = IntParameter(1, 100, default=buy_params["nfi32_rsi_14"], space="buy", optimize=True)
    nfi32_sma_factor = DecimalParameter(0.7, 1.2, default=buy_params["nfi32_sma_factor"], decimals=5, space="buy", optimize=True)
    nfi32_cti_limit = DecimalParameter(-1.2, 0, default=buy_params["nfi32_cti_limit"], decimals=5, space="buy", optimize=True)

    buy_btc_safe_1d = DecimalParameter(-0.5, -0.015, default=buy_params["buy_btc_safe_1d"], optimize=True)
    antipump_threshold = DecimalParameter(0, 0.4, default=buy_params["antipump_threshold"], space="buy", optimize=True)

    ewo_1_enabled = BooleanParameter(default=buy_params["ewo_1_enabled"], space="buy", optimize=True)
    ewo_low_enabled = BooleanParameter(default=buy_params["ewo_low_enabled"], space="buy", optimize=True)
    cofi_enabled = BooleanParameter(default=buy_params["cofi_enabled"], space="buy", optimize=True)
    lambo1_enabled = BooleanParameter(default=buy_params["lambo1_enabled"], space="buy", optimize=True)
    lambo2_enabled = BooleanParameter(default=buy_params["lambo2_enabled"], space="buy", optimize=True)
    local_trend_enabled = BooleanParameter(default=buy_params["local_trend_enabled"], space="buy", optimize=True)
    nfi32_enabled = BooleanParameter(default=buy_params["nfi32_enabled"], space="buy", optimize=True)
    clucha_enabled = BooleanParameter(default=buy_params["clucha_enabled"], space="buy", optimize=True)

    def trailing_buy(self, pair, reinit=False):
        if pair not in self.custom_info_trail_buy:
            self.custom_info_trail_buy[pair] = dict()
        if reinit or "trailing_buy" not in self.custom_info_trail_buy[pair]:
            self.custom_info_trail_buy[pair]["trailing_buy"] = self.init_trailing_dict.copy()
        return self.custom_info_trail_buy[pair]["trailing_buy"]

    def trailing_buy_info(self, pair: str, current_price: float):
        current_time = datetime.now(timezone.utc)
        if not self.debug_mode:
            return
        trailing_buy = self.trailing_buy(pair)

        try:
            duration = current_time - trailing_buy["start_trailing_time"]
        except TypeError:
            duration = 0

        logger.info(
            f"pair: {pair} : "
            f"start: {trailing_buy['start_trailing_price']:.4f}, "
            f"duration: {duration}, "
            f"current: {current_price:.4f}, "
            f"uplimit: {trailing_buy['trailing_buy_order_uplimit']:.4f}, "
            f"profit: {self.current_trailing_profit_ratio(pair, current_price) * 100:.2f}%, "
            f"offset: {trailing_buy['offset']}"
        )

    def current_trailing_profit_ratio(self, pair: str, current_price: float) -> float:
        trailing_buy = self.trailing_buy(pair)
        if trailing_buy["trailing_buy_order_started"]:
            return (trailing_buy["start_trailing_price"] - current_price) / trailing_buy["start_trailing_price"]
        return 0

    def trailing_buy_offset(self, dataframe, pair: str, current_price: float):
        current_trailing_profit_ratio = self.current_trailing_profit_ratio(pair, current_price)
        default_offset = 0.005

        trailing_buy = self.trailing_buy(pair)
        if not trailing_buy["trailing_buy_order_started"]:
            return default_offset

        last_candle = dataframe.iloc[-1]
        current_time = datetime.now(timezone.utc)
        trailing_duration = current_time - trailing_buy["start_trailing_time"]

        if trailing_duration.total_seconds() > self.trailing_expire_seconds:
            if (current_trailing_profit_ratio > 0) and (last_candle.get("enter_long", 0) == 1):
                return "forcebuy"
            return None

        if (
            self.trailing_buy_uptrend_enabled
            and trailing_duration.total_seconds() < self.trailing_expire_seconds_uptrend
            and current_trailing_profit_ratio < (-1 * self.min_uptrend_trailing_profit)
        ):
            return "forcebuy"

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

    def informative_pairs(self):
        pairs = self.dp.current_whitelist()
        informative_pairs = [(pair, "1h") for pair in pairs]
        informative_pairs += [("BTC/USDT", "5m")]
        informative_pairs += [("BTC/USDT", "1d")]
        return informative_pairs

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

    def _get_informative_1h(self, pair: str) -> DataFrame:
        informative = self.dp.get_pair_dataframe(pair=pair, timeframe="1h")
        if informative is None or informative.empty:
            return DataFrame(columns=["date", "ha_close", "rocr"])

        informative = informative.copy()
        informative["date"] = pd.to_datetime(informative["date"], utc=True, errors="coerce")
        informative = informative.dropna(subset=["date"])

        if informative.empty:
            return DataFrame(columns=["date", "ha_close", "rocr"])

        inf_heikinashi = qtpylib.heikinashi(informative)
        informative["ha_close"] = inf_heikinashi["close"]
        informative["rocr"] = ta.ROCR(informative["ha_close"], timeperiod=168)

        return informative[["date", "open", "high", "low", "close", "volume", "ha_close", "rocr"]]

    def _merge_btc_5m(self, dataframe: DataFrame) -> DataFrame:
        btc_5m = self.dp.get_pair_dataframe("BTC/USDT", timeframe="5m")
        if btc_5m is None or btc_5m.empty:
            dataframe["btc_5m"] = np.nan
            return dataframe

        btc_5m = btc_5m.copy()
        btc_5m["date"] = pd.to_datetime(btc_5m["date"], utc=True, errors="coerce")
        btc_5m = btc_5m.dropna(subset=["date"])
        if btc_5m.empty:
            dataframe["btc_5m"] = np.nan
            return dataframe

        btc_5m = btc_5m[["date", "close"]].rename(columns={"close": "btc_5m"})
        return merge_informative_pair(dataframe, btc_5m, self.timeframe, "5m", ffill=True)

    def _merge_btc_1d(self, dataframe: DataFrame) -> DataFrame:
        btc_1d = self.dp.get_pair_dataframe("BTC/USDT", timeframe="1d")
        if btc_1d is None or btc_1d.empty:
            dataframe["btc_1d"] = np.nan
            return dataframe

        btc_1d = btc_1d.copy()
        btc_1d["date"] = pd.to_datetime(btc_1d["date"], utc=True, errors="coerce")
        btc_1d = btc_1d.dropna(subset=["date"])
        if btc_1d.empty:
            dataframe["btc_1d"] = np.nan
            return dataframe

        btc_1d = btc_1d[["date", "close"]].rename(columns={"close": "btc_1d"})
        btc_1d["btc_1d"] = btc_1d["btc_1d"].shift(1)
        return merge_informative_pair(dataframe, btc_1d, self.timeframe, "1d", ffill=True)

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = dataframe.copy()
        dataframe["date"] = pd.to_datetime(dataframe["date"], utc=True, errors="coerce")
        dataframe = dataframe.dropna(subset=["date"])

        self.trailing_buy(metadata["pair"])

        heikinashi = qtpylib.heikinashi(dataframe)
        dataframe["ha_open"] = heikinashi["open"]
        dataframe["ha_close"] = heikinashi["close"]
        dataframe["ha_high"] = heikinashi["high"]
        dataframe["ha_low"] = heikinashi["low"]

        dataframe["ema_8"] = ta.EMA(dataframe, timeperiod=8)
        dataframe["ema_14"] = ta.EMA(dataframe, timeperiod=14)
        dataframe["ema_26"] = ta.EMA(dataframe, timeperiod=26)
        dataframe["sma_15"] = ta.SMA(dataframe, timeperiod=15)
        dataframe["rsi_4"] = ta.RSI(dataframe, timeperiod=4)
        dataframe["rsi_14"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["rsi_20"] = ta.RSI(dataframe, timeperiod=20)
        dataframe["cti"] = pta.cti(dataframe["close"], length=20)

        stoch_fast = ta.STOCHF(dataframe, 5, 3, 0, 3, 0)
        dataframe["fastd"] = stoch_fast["fastd"]
        dataframe["fastk"] = stoch_fast["fastk"]
        dataframe["adx"] = ta.ADX(dataframe)

        mid, lower = bollinger_bands(ha_typical_price(dataframe), window_size=40, num_of_std=2)
        dataframe["lower"] = lower
        dataframe["mid"] = mid

        bollinger2 = qtpylib.bollinger_bands(qtpylib.typical_price(dataframe), window=20, stds=2)
        dataframe["bb_lowerband2"] = bollinger2["lower"]
        dataframe["bb_middleband2"] = bollinger2["mid"]
        dataframe["bb_upperband2"] = bollinger2["upper"]

        dataframe["closedelta"] = (dataframe["close"] - dataframe["close"].shift()).abs()
        dataframe["bbdelta"] = (mid - dataframe["lower"]).abs()
        dataframe["ha_closedelta"] = (dataframe["ha_close"] - dataframe["ha_close"].shift()).abs()
        dataframe["tail"] = (dataframe["ha_close"] - dataframe["ha_low"]).abs()
        dataframe["bb_lowerband"] = dataframe["lower"]
        dataframe["bb_middleband"] = dataframe["mid"]

        dataframe["ema_fast"] = ta.EMA(dataframe["ha_close"], timeperiod=3)
        dataframe["ema_slow"] = ta.EMA(dataframe["ha_close"], timeperiod=50)
        dataframe["rocr"] = ta.ROCR(dataframe["ha_close"], timeperiod=28)
        dataframe["EWO"] = EWO(dataframe, 50, 200)

        rsi = ta.RSI(dataframe)
        dataframe["rsi"] = rsi
        rsi = 0.1 * (rsi - 50)
        dataframe["fisher"] = (np.exp(2 * rsi) - 1) / (np.exp(2 * rsi) + 1)

        informative = self._get_informative_1h(metadata["pair"])
        if not informative.empty:
            dataframe = merge_informative_pair(dataframe, informative, self.timeframe, "1h", ffill=True)
        else:
            dataframe["rocr_1h"] = np.nan

        dataframe = self._merge_btc_5m(dataframe)
        dataframe = self._merge_btc_1d(dataframe)

        dataframe["dema_30"] = ta.DEMA(dataframe["close"], timeperiod=30)
        dataframe["dema_200"] = ta.DEMA(dataframe["close"], timeperiod=200)
        dataframe["pump_strength"] = (dataframe["dema_30"] - dataframe["dema_200"]) / dataframe["dema_30"]

        return dataframe

    def confirm_trade_entry(self, pair: str, order_type: str, amount: float, rate: float, time_in_force: str, **kwargs) -> bool:
        val = True

        if self.trailing_buy_order_enabled and self.config["runmode"].value in ("live", "dry_run"):
            val = False
            dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
            if len(dataframe) >= 1:
                last_candle = dataframe.iloc[-1].squeeze()
                current_price = rate
                trailing_buy = self.trailing_buy(pair)
                trailing_buy_offset = self.trailing_buy_offset(dataframe, pair, current_price)

                if trailing_buy["allow_trailing"]:
                    if (not trailing_buy["trailing_buy_order_started"]) and (last_candle.get("enter_long", 0) == 1):
                        trailing_buy["trailing_buy_order_started"] = True
                        trailing_buy["trailing_buy_order_uplimit"] = last_candle["close"]
                        trailing_buy["start_trailing_price"] = last_candle["close"]
                        trailing_buy["enter_tag"] = last_candle.get("enter_tag", "")
                        trailing_buy["start_trailing_time"] = datetime.now(timezone.utc)
                        trailing_buy["offset"] = 0

                        self.trailing_buy_info(pair, current_price)
                        logger.info(f"start trailing buy for {pair} at {last_candle['close']}")

                    elif trailing_buy["trailing_buy_order_started"]:
                        if trailing_buy_offset == "forcebuy":
                            val = True
                            ratio = "%.2f" % (self.current_trailing_profit_ratio(pair, current_price) * 100)
                            self.trailing_buy_info(pair, current_price)
                            logger.info(f"price OK for {pair} ({ratio} %, {current_price}), order may not be triggered if all slots are full")

                        elif trailing_buy_offset is None:
                            self.trailing_buy(pair, reinit=True)
                            logger.info(f'STOP trailing buy for {pair} because "trailing buy offset" returned None')

                        elif current_price < trailing_buy["trailing_buy_order_uplimit"]:
                            old_uplimit = trailing_buy["trailing_buy_order_uplimit"]
                            self.custom_info_trail_buy[pair]["trailing_buy"]["trailing_buy_order_uplimit"] = min(
                                current_price * (1 + trailing_buy_offset),
                                self.custom_info_trail_buy[pair]["trailing_buy"]["trailing_buy_order_uplimit"],
                            )
                            self.custom_info_trail_buy[pair]["trailing_buy"]["offset"] = trailing_buy_offset
                            self.trailing_buy_info(pair, current_price)
                            logger.info(f"update trailing buy for {pair} at {old_uplimit} -> {self.custom_info_trail_buy[pair]['trailing_buy']['trailing_buy_order_uplimit']}")

                        elif current_price < (trailing_buy["start_trailing_price"] * (1 + self.trailing_buy_max_buy)):
                            val = True
                            ratio = "%.2f" % (self.current_trailing_profit_ratio(pair, current_price) * 100)
                            self.trailing_buy_info(pair, current_price)
                            logger.info(f"current price ({current_price}) > uplimit ({trailing_buy['trailing_buy_order_uplimit']}) and lower than starting price ({trailing_buy['start_trailing_price'] * (1 + self.trailing_buy_max_buy)}). OK for {pair} ({ratio} %)")

                        elif current_price > (trailing_buy["start_trailing_price"] * (1 + self.trailing_buy_max_stop)):
                            self.trailing_buy(pair, reinit=True)
                            self.trailing_buy_info(pair, current_price)
                            logger.info(f"STOP trailing buy for {pair} because price is higher than starting price * {1 + self.trailing_buy_max_stop}")

                        else:
                            self.trailing_buy_info(pair, current_price)
                            logger.info(f"price too high for {pair}!")
                else:
                    logger.info(f"Wait for next buy signal for {pair}")

            if val is True:
                self.trailing_buy_info(pair, rate)
                self.trailing_buy(pair, reinit=True)
                logger.info(f"STOP trailing buy for {pair} because I buy it")

        return val

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        conditions = []

        dataframe.loc[:, "enter_tag"] = ""
        dataframe.loc[:, "enter_long"] = 0

        if self.trailing_buy_order_enabled and self.config["runmode"].value in ("live", "dry_run"):
            last_candle = dataframe.iloc[-1].squeeze()
            trailing_buy = self.trailing_buy(metadata["pair"])
            if last_candle.get("enter_long", 0) == 1:
                if not trailing_buy["trailing_buy_order_started"]:
                    open_trades = Trade.get_trades([Trade.pair == metadata["pair"], Trade.is_open.is_(True)]).all()
                    if not open_trades:
                        logger.info(f"Set 'allow_trailing' to True for {metadata['pair']} to start trailing!!!")
                        trailing_buy["allow_trailing"] = True
                        initial_buy_tag = last_candle.get("enter_tag", "buy signal")
                        dataframe.loc[:, "enter_tag"] = f"{initial_buy_tag} (start trail price {last_candle['close']})"
            else:
                if trailing_buy["trailing_buy_order_started"] is True:
                    logger.info(f"Continue trailing for {metadata['pair']}. Manually trigger buy signal!!")
                    dataframe.loc[:, "enter_long"] = 1
                    dataframe.loc[:, "enter_tag"] = trailing_buy["enter_tag"]

        dataframe[f"ma_buy_{self.ewo_candles_buy.value}"] = ta.EMA(dataframe, timeperiod=int(self.ewo_candles_buy.value))
        dataframe[f"ma_sell_{self.ewo_candles_sell.value}"] = ta.EMA(dataframe, timeperiod=int(self.ewo_candles_sell.value))

        lambo1 = (
            bool(self.lambo1_enabled.value)
            & (dataframe["close"] < (dataframe["ema_14"] * self.lambo1_ema_14_factor.value))
            & (dataframe["rsi_4"] < int(self.lambo1_rsi_4_limit.value))
            & (dataframe["rsi_14"] < int(self.lambo1_rsi_14_limit.value))
        )
        dataframe.loc[lambo1, "enter_tag"] += "lambo1_"
        conditions.append(lambo1)

        lambo2 = (
            bool(self.lambo2_enabled.value)
            & (dataframe["close"] < (dataframe["ema_14"] * self.lambo2_ema_14_factor.value))
            & (dataframe["rsi_4"] < int(self.lambo2_rsi_4_limit.value))
            & (dataframe["rsi_14"] < int(self.lambo2_rsi_14_limit.value))
        )
        dataframe.loc[lambo2, "enter_tag"] += "lambo2_"
        conditions.append(lambo2)

        local_uptrend = (
            bool(self.local_trend_enabled.value)
            & (dataframe["ema_26"] > dataframe["ema_14"])
            & ((dataframe["ema_26"] - dataframe["ema_14"]) > dataframe["open"] * self.local_trend_ema_diff.value)
            & ((dataframe["ema_26"].shift() - dataframe["ema_14"].shift()) > dataframe["open"] / 100)
            & (dataframe["close"] < dataframe["bb_lowerband2"] * self.local_trend_bb_factor.value)
            & (dataframe["closedelta"] > dataframe["close"] * self.local_trend_closedelta.value / 1000)
        )
        dataframe.loc[local_uptrend, "enter_tag"] += "local_uptrend_"
        conditions.append(local_uptrend)

        nfi_32 = (
            bool(self.nfi32_enabled.value)
            & (dataframe["rsi_20"] < dataframe["rsi_20"].shift(1))
            & (dataframe["rsi_4"] < self.nfi32_rsi_4.value)
            & (dataframe["rsi_14"] > self.nfi32_rsi_14.value)
            & (dataframe["close"] < dataframe["sma_15"] * self.nfi32_sma_factor.value)
            & (dataframe["cti"] < self.nfi32_cti_limit.value)
        )
        dataframe.loc[nfi_32, "enter_tag"] += "nfi_32_"
        conditions.append(nfi_32)

        ewo_1 = (
            bool(self.ewo_1_enabled.value)
            & (dataframe["rsi_4"] < self.ewo_1_rsi_4.value)
            & (dataframe["close"] < (dataframe[f"ma_buy_{self.ewo_candles_buy.value}"] * self.ewo_low_offset.value))
            & (dataframe["EWO"] > self.ewo_high.value)
            & (dataframe["rsi_14"] < self.ewo_1_rsi_14.value)
            & (dataframe["close"] < (dataframe[f"ma_sell_{self.ewo_candles_sell.value}"] * self.ewo_high_offset.value))
        )
        dataframe.loc[ewo_1, "enter_tag"] += "ewo1_"
        conditions.append(ewo_1)

        ewo_low = (
            bool(self.ewo_low_enabled.value)
            & (dataframe["rsi_4"] < self.ewo_low_rsi_4.value)
            & (dataframe["close"] < (dataframe[f"ma_buy_{self.ewo_candles_buy.value}"] * self.ewo_low_offset.value))
            & (dataframe["EWO"] < self.ewo_low.value)
            & (dataframe["close"] < (dataframe[f"ma_sell_{self.ewo_candles_sell.value}"] * self.ewo_high_offset.value))
        )
        dataframe.loc[ewo_low, "enter_tag"] += "ewo_low_"
        conditions.append(ewo_low)

        cofi = (
            bool(self.cofi_enabled.value)
            & (dataframe["open"] < dataframe["ema_8"] * self.cofi_ema.value)
            & (qtpylib.crossed_above(dataframe["fastk"], dataframe["fastd"]))
            & (dataframe["fastk"] < self.cofi_fastk.value)
            & (dataframe["fastd"] < self.cofi_fastd.value)
            & (dataframe["adx"] > self.cofi_adx.value)
            & (dataframe["EWO"] > self.cofi_ewo_high.value)
        )
        dataframe.loc[cofi, "enter_tag"] += "cofi_"
        conditions.append(cofi)

        clucHA = (
            bool(self.clucha_enabled.value)
            & (dataframe["rocr_1h"].gt(self.clucha_rocr_1h.value))
            & (
                (
                    (dataframe["lower"].shift().gt(0))
                    & (dataframe["bbdelta"].gt(dataframe["ha_close"] * self.clucha_bbdelta_close.value))
                    & (dataframe["ha_closedelta"].gt(dataframe["ha_close"] * self.clucha_closedelta_close.value))
                    & (dataframe["tail"].lt(dataframe["bbdelta"] * self.clucha_bbdelta_tail.value))
                    & (dataframe["ha_close"].lt(dataframe["lower"].shift()))
                    & (dataframe["ha_close"].le(dataframe["ha_close"].shift()))
                )
                | (
                    (dataframe["ha_close"] < dataframe["ema_slow"])
                    & (dataframe["ha_close"] < self.clucha_close_bblower.value * dataframe["bb_lowerband"])
                )
            )
        )
        dataframe.loc[clucHA, "enter_tag"] += "clucHA_"
        conditions.append(clucHA)

        if conditions:
            dataframe.loc[reduce(lambda x, y: x | y, conditions), "enter_long"] = 1

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        params = self.sell_params

        dataframe.loc[:, "exit_long"] = 0

        dataframe.loc[
            (dataframe["fisher"] > params["sell-fisher"])
            & (dataframe["ha_high"].le(dataframe["ha_high"].shift(1)))
            & (dataframe["ha_high"].shift(1).le(dataframe["ha_high"].shift(2)))
            & (dataframe["ha_close"].le(dataframe["ha_close"].shift(1)))
            & (dataframe["ema_fast"] > dataframe["ha_close"])
            & ((dataframe["ha_close"] * params["sell-bbmiddle-close"]) > dataframe["bb_middleband"])
            & (dataframe["volume"] > 0),
            "exit_long",
        ] = 1

        return dataframe

    def confirm_trade_exit(self, pair: str, trade: Trade, order_type: str, amount: float, rate: float, time_in_force: str, exit_reason: str, current_time: datetime, **kwargs) -> bool:
        trade.exit_reason = f"{exit_reason}_{getattr(trade, 'enter_tag', '')}"
        return True