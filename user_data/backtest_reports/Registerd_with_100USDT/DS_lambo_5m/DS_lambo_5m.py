from datetime import datetime
from functools import reduce
from typing import Optional

import logging
import math
import numpy as np
from pandas import DataFrame, Series

import freqtrade.vendor.qtpylib.indicators as qtpylib
import talib.abstract as ta

from freqtrade.persistence import Trade
from freqtrade.strategy import (
    BooleanParameter,
    DecimalParameter,
    IntParameter,
    RealParameter,
    stoploss_from_open,
    merge_informative_pair,
)
from freqtrade.strategy.interface import IStrategy

logger = logging.getLogger(__name__)


############################################################################
# Custom indicators and helper functions
############################################################################
def bollinger_bands(stock_price: Series, window_size: int, num_of_std: float):
    rolling_mean = stock_price.rolling(window=window_size).mean()
    rolling_std = stock_price.rolling(window=window_size).std()
    lower_band = rolling_mean - (rolling_std * num_of_std)
    return np.nan_to_num(rolling_mean), np.nan_to_num(lower_band)


def ha_typical_price(bars: DataFrame) -> Series:
    res = (bars["ha_high"] + bars["ha_low"] + bars["ha_close"]) / 3.0
    return Series(index=bars.index, data=res)


class DS_lambo_5m(IStrategy):
    INTERFACE_VERSION = 3

    ########################################################################
    # Main
    ########################################################################
    timeframe = "5m"
    inf_1h = "1h"

    use_exit_signal = True
    use_custom_stoploss = False  # set True if you actually want to use custom_stoploss()
    exit_profit_only = True
    exit_profit_offset = 0.01
    ignore_roi_if_entry_signal = False

    trailing_stop = False
    trailing_stop_positive = 0.001
    trailing_stop_positive_offset = 0.016
    trailing_only_offset_is_reached = False

    process_only_new_candles = True

    # Was too low for your indicator stack
    startup_candle_count = 400

    initial_safety_order_trigger = -0.018
    max_safety_orders = 8
    safety_order_step_scale = 1.2
    safety_order_volume_scale = 1.4

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
        "exit": "ioc",
    }

    slippage_protection = {
        "retries": 3,
        "max_slippage": -0.02,
    }

    plot_config = {
        "main_plot": {
            "ma_buy": {"color": "green"},
            "ma_sell": {"color": "orange"},
        },
    }

    ########################################################################
    # Hyperopt
    ########################################################################
    buy_params = {
        "lambo_2_enabled": True,
        "base_nb_candles_buy": 8,
        "antipump_threshold": 0.133,
        "lambo2_ema_14_factor": 0.981,
        "lambo2_rsi_14_limit": 39,
        "lambo2_rsi_4_limit": 44,
    }

    sell_params = {
        "base_nb_candles_sell": 22,
        "high_offset_2": 1.01,
        "high_offset": 1.014,
        "sell_fisher": 0.39075,
        "sell_bbmiddle_close": 0.99754,
        "pHSL": -0.35,
        "pPF_1": 0.011,
        "pPF_2": 0.064,
        "pSL_1": 0.011,
        "pSL_2": 0.062,
    }

    minimal_roi = {
        "0": 0.99,
    }

    stoploss = -0.15

    ########################################################################
    # Parameters
    ########################################################################
    is_optimize_base_nb_candles = False

    base_nb_candles_buy = IntParameter(
        8, 20,
        default=buy_params["base_nb_candles_buy"],
        space="buy",
        optimize=is_optimize_base_nb_candles,
    )
    base_nb_candles_sell = IntParameter(
        8, 20,
        default=sell_params["base_nb_candles_sell"],
        space="sell",
        optimize=is_optimize_base_nb_candles,
    )

    is_optimize_antipump = True
    antipump_threshold = DecimalParameter(
        0, 0.4,
        default=buy_params["antipump_threshold"],
        space="buy",
        optimize=is_optimize_antipump,
    )

    is_optimize_lambo2 = True
    lambo2_ema_14_factor = DecimalParameter(
        0.8, 1.2,
        decimals=3,
        default=buy_params["lambo2_ema_14_factor"],
        space="buy",
        optimize=is_optimize_lambo2,
    )
    lambo2_rsi_4_limit = IntParameter(
        5, 60,
        default=buy_params["lambo2_rsi_4_limit"],
        space="buy",
        optimize=is_optimize_lambo2,
    )
    lambo2_rsi_14_limit = IntParameter(
        5, 60,
        default=buy_params["lambo2_rsi_14_limit"],
        space="buy",
        optimize=is_optimize_lambo2,
    )

    is_optimize_stoploss = True
    pHSL = DecimalParameter(
        -0.200, -0.040,
        default=-0.15,
        decimals=3,
        space="sell",
        optimize=is_optimize_stoploss,
        load=True,
    )
    pPF_1 = DecimalParameter(
        0.008, 0.020,
        default=0.016,
        decimals=3,
        space="sell",
        optimize=is_optimize_stoploss,
        load=True,
    )
    pSL_1 = DecimalParameter(
        0.008, 0.020,
        default=0.014,
        decimals=3,
        space="sell",
        optimize=is_optimize_stoploss,
        load=True,
    )
    pPF_2 = DecimalParameter(
        0.040, 0.100,
        default=0.024,
        decimals=3,
        space="sell",
        optimize=is_optimize_stoploss,
        load=True,
    )
    pSL_2 = DecimalParameter(
        0.020, 0.070,
        default=0.022,
        decimals=3,
        space="sell",
        optimize=is_optimize_stoploss,
        load=True,
    )

    is_optimize_sell = True
    sell_fisher = RealParameter(
        0.1, 0.5,
        default=0.38414,
        space="sell",
        optimize=is_optimize_sell,
    )
    sell_bbmiddle_close = RealParameter(
        0.97, 1.1,
        default=1.07634,
        space="sell",
        optimize=is_optimize_sell,
    )
    high_offset_2 = DecimalParameter(
        1.010, 1.020,
        default=sell_params["high_offset_2"],
        space="sell",
        optimize=True,
    )
    high_offset = DecimalParameter(
        1.005, 1.015,
        default=sell_params["high_offset"],
        space="sell",
        optimize=True,
    )

    lambo_2_enabled = BooleanParameter(
        default=buy_params["lambo_2_enabled"],
        space="buy",
        optimize=is_optimize_lambo2,
    )

    ########################################################################
    # Informative pairs
    ########################################################################
    def informative_pairs(self):
        pairs = self.dp.current_whitelist()
        return [(pair, self.inf_1h) for pair in pairs]

    def informative_1h_indicators(self, metadata: dict) -> DataFrame:
        assert self.dp, "DataProvider is required for multiple timeframes."

        informative_1h = self.dp.get_pair_dataframe(
            pair=metadata["pair"],
            timeframe=self.inf_1h,
        )

        if informative_1h is None or informative_1h.empty:
            logger.warning(
                f"No informative {self.inf_1h} data for {metadata['pair']}"
            )
            return DataFrame()

        inf_heikinashi = qtpylib.heikinashi(informative_1h.copy())
        informative_1h["ha_close"] = inf_heikinashi["close"]
        informative_1h["rocr"] = ta.ROCR(informative_1h["ha_close"], timeperiod=168)

        return informative_1h

    ########################################################################
    # Indicators
    ########################################################################
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        if dataframe.empty:
            return dataframe

        for val in self.base_nb_candles_buy.range:
            dataframe[f"ma_buy_{val}"] = ta.EMA(dataframe, timeperiod=val)

        for val in self.base_nb_candles_sell.range:
            dataframe[f"ma_sell_{val}"] = ta.EMA(dataframe, timeperiod=val)

        heikinashi = qtpylib.heikinashi(dataframe.copy())
        dataframe["ha_open"] = heikinashi["open"]
        dataframe["ha_close"] = heikinashi["close"]
        dataframe["ha_high"] = heikinashi["high"]
        dataframe["ha_low"] = heikinashi["low"]

        # Pump / anti-pump
        dataframe["dema_30"] = ta.DEMA(dataframe, timeperiod=30)
        dataframe["dema_200"] = ta.DEMA(dataframe, timeperiod=200)
        dataframe["pump_strength"] = np.where(
            dataframe["dema_30"] != 0,
            (dataframe["dema_30"] - dataframe["dema_200"]) / dataframe["dema_30"],
            0,
        )

        # Buy side
        dataframe["ema_14"] = ta.EMA(dataframe, timeperiod=14)
        dataframe["rsi_4"] = ta.RSI(dataframe, timeperiod=4)
        dataframe["rsi_14"] = ta.RSI(dataframe, timeperiod=14)

        # Sell side
        dataframe["hma_50"] = qtpylib.hull_moving_average(dataframe["close"], window=50)
        dataframe["ema_100"] = ta.EMA(dataframe, timeperiod=100)

        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["rsi_fast"] = ta.RSI(dataframe, timeperiod=4)
        dataframe["rsi_slow"] = ta.RSI(dataframe, timeperiod=20)

        rsi = ta.RSI(dataframe, timeperiod=14)
        dataframe["rsi"] = rsi
        fisher_base = 0.1 * (rsi - 50)
        dataframe["fisher"] = (np.exp(2 * fisher_base) - 1) / (np.exp(2 * fisher_base) + 1)

        mid, lower = bollinger_bands(
            ha_typical_price(dataframe),
            window_size=40,
            num_of_std=2,
        )
        dataframe["lower"] = lower
        dataframe["mid"] = mid

        dataframe["bbdelta"] = (dataframe["mid"] - dataframe["lower"]).abs()
        dataframe["closedelta"] = (dataframe["ha_close"] - dataframe["ha_close"].shift()).abs()
        dataframe["tail"] = (dataframe["ha_close"] - dataframe["ha_low"]).abs()

        dataframe["bb_lowerband"] = dataframe["lower"]
        dataframe["bb_middleband"] = dataframe["mid"]

        dataframe["ema_fast"] = ta.EMA(dataframe["ha_close"], timeperiod=3)
        dataframe["ema_slow"] = ta.EMA(dataframe["ha_close"], timeperiod=50)
        dataframe["volume_mean_slow"] = dataframe["volume"].rolling(window=30).mean()
        dataframe["rocr"] = ta.ROCR(dataframe["ha_close"], timeperiod=28)

        informative_1h = self.informative_1h_indicators(metadata)
        if not informative_1h.empty:
            dataframe = merge_informative_pair(
                dataframe,
                informative_1h,
                self.timeframe,
                self.inf_1h,
                ffill=True,
            )

        dataframe = self.pump_dump_protection(dataframe, metadata)
        return dataframe

    ########################################################################
    # Pump / dump protection
    ########################################################################
    def pump_dump_protection(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        if dataframe.empty:
            return dataframe

        df36h = dataframe.copy().shift(432)
        df24h = dataframe.copy().shift(288)

        dataframe["volume_mean_short"] = dataframe["volume"].rolling(4).mean()
        dataframe["volume_mean_long"] = df24h["volume"].rolling(48).mean()
        dataframe["volume_mean_base"] = df36h["volume"].rolling(288).mean()

        base_safe = dataframe["volume_mean_base"].replace(0, np.nan)
        long_safe = dataframe["volume_mean_long"].replace(0, np.nan)

        dataframe["volume_change_percentage"] = dataframe["volume_mean_long"] / base_safe
        dataframe["rsi_mean"] = dataframe["rsi"].rolling(48).mean()

        dataframe["pnd_volume_warn"] = np.where(
            (dataframe["volume_mean_short"] / long_safe) > 5.0,
            -1,
            0,
        )

        dataframe["pnd_volume_warn"] = dataframe["pnd_volume_warn"].fillna(0)

        return dataframe

    ########################################################################
    # Buy trend
    ########################################################################
    def check_lambo_2(self, dataframe: DataFrame):
        return (
            bool(self.lambo_2_enabled.value)
            & (dataframe["close"] < (dataframe["ema_14"] * self.lambo2_ema_14_factor.value))
            & (dataframe["rsi_4"] < int(self.lambo2_rsi_4_limit.value))
            & (dataframe["rsi_14"] < int(self.lambo2_rsi_14_limit.value))
        )

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        if dataframe.empty:
            return dataframe

        dataframe["enter_long"] = 0
        dataframe["enter_tag"] = ""

        dont_buy_conditions = dataframe["pnd_volume_warn"] < 0.0
        is_pump_safe = dataframe["pump_strength"] < self.antipump_threshold.value

        conditions_and_tags = [
            (self.check_lambo_2(dataframe), "lambo_2"),
        ]

        for condition, tag in conditions_and_tags:
            dataframe.loc[condition, "enter_tag"] = tag
            dataframe.loc[
                condition & is_pump_safe & ~dont_buy_conditions,
                "enter_long",
            ] = 1

        dataframe.loc[dont_buy_conditions, "enter_long"] = 0

        return dataframe

    ########################################################################
    # Sell trend
    ########################################################################
    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        if dataframe.empty:
            return dataframe

        dataframe["exit_long"] = 0

        conditions = []

        conditions.append(
            (
                (dataframe["close"] > dataframe["hma_50"])
                & (
                    dataframe["close"]
                    > (
                        dataframe[f"ma_sell_{self.base_nb_candles_sell.value}"]
                        * self.high_offset_2.value
                    )
                )
                & (dataframe["rsi"] > 50)
                & (dataframe["volume"] > 0)
                & (dataframe["rsi_fast"] > dataframe["rsi_slow"])
            )
            |
            (
                (dataframe["close"] < dataframe["hma_50"])
                & (
                    dataframe["close"]
                    > (
                        dataframe[f"ma_sell_{self.base_nb_candles_sell.value}"]
                        * self.high_offset.value
                    )
                )
                & (dataframe["volume"] > 0)
                & (dataframe["rsi_fast"] > dataframe["rsi_slow"])
            )
        )

        if conditions:
            combined_condition = reduce(lambda x, y: x | y, conditions)
            dataframe.loc[combined_condition, "exit_long"] = 1

        return dataframe

    ########################################################################
    # Confirm trade exit
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

        if dataframe is None or dataframe.empty:
            return True

        last_candle = dataframe.iloc[-1].squeeze()

        if exit_reason in ["exit_signal", "sell_signal"]:
            if (
                (last_candle["hma_50"] * 1.149 > last_candle["ema_100"])
                and (last_candle["close"] < last_candle["ema_100"] * 0.951)
            ):
                return False

        try:
            state = self.slippage_protection["__pair_retries"]
        except KeyError:
            state = self.slippage_protection["__pair_retries"] = {}

        slippage = (rate / last_candle["close"]) - 1
        if slippage < self.slippage_protection["max_slippage"]:
            pair_retries = state.get(pair, 0)
            if pair_retries < self.slippage_protection["retries"]:
                state[pair] = pair_retries + 1
                return False

        state[pair] = 0
        return True

    ########################################################################
    # Trade protections
    ########################################################################
    @property
    def protections(self):
        return [
            {
                "method": "CooldownPeriod",
                "stop_duration_candles": 5,
            },
            {
                "method": "MaxDrawdown",
                "lookback_period_candles": 48,
                "trade_limit": 20,
                "stop_duration_candles": 4,
                "max_allowed_drawdown": 0.2,
            },
            {
                "method": "StoplossGuard",
                "lookback_period_candles": 24,
                "trade_limit": 4,
                "stop_duration_candles": 2,
                "only_per_pair": False,
            },
            {
                "method": "LowProfitPairs",
                "lookback_period_candles": 6,
                "trade_limit": 2,
                "stop_duration_candles": 60,
                "required_profit": 0.02,
            },
            {
                "method": "LowProfitPairs",
                "lookback_period_candles": 24,
                "trade_limit": 4,
                "stop_duration_candles": 2,
                "required_profit": 0.01,
            },
        ]

    ########################################################################
    # Adjust trade position
    ########################################################################
    def adjust_trade_position(
        self,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        min_stake: float,
        max_stake: float,
        **kwargs,
    ):
        if current_profit > self.initial_safety_order_trigger:
            return None

        dataframe, _ = self.dp.get_analyzed_dataframe(trade.pair, self.timeframe)
        if dataframe is None or len(dataframe) < 2:
            return None

        last_candle = dataframe.iloc[-1].squeeze()
        previous_candle = dataframe.iloc[-2].squeeze()

        if last_candle["close"] < previous_candle["close"]:
            return None

        count_of_buys = 0
        for order in trade.orders:
            if order.ft_is_open or order.ft_order_side != "buy":
                continue
            if order.status == "closed":
                count_of_buys += 1

        if 1 <= count_of_buys <= self.max_safety_orders:
            if self.safety_order_step_scale == 1:
                safety_order_trigger = abs(self.initial_safety_order_trigger) * count_of_buys
            else:
                safety_order_trigger = abs(self.initial_safety_order_trigger) + (
                    abs(self.initial_safety_order_trigger)
                    * self.safety_order_step_scale
                    * (
                        math.pow(self.safety_order_step_scale, (count_of_buys - 1)) - 1
                    )
                    / (self.safety_order_step_scale - 1)
                )

            if current_profit <= (-1 * abs(safety_order_trigger)):
                try:
                    stake_amount = self.wallets.get_trade_stake_amount(trade.pair, None)
                    stake_amount = stake_amount * math.pow(
                        self.safety_order_volume_scale, (count_of_buys - 1)
                    )
                    logger.info(
                        f"Initiating safety order buy #{count_of_buys} for {trade.pair} "
                        f"with stake amount {stake_amount}"
                    )
                    return stake_amount
                except Exception as exception:
                    logger.info(
                        f"Error while trying to get stake amount for {trade.pair}: {exception}"
                    )
                    return None

        return None

    ########################################################################
    # Custom stoploss
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
    # Custom exit (old custom_sell renamed for interface v3)
    ########################################################################
    def get_max_loss_threshold(self) -> float:
        return -0.04

    def get_max_holding_days(self) -> int:
        return 7

    def custom_exit(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ) -> Optional[str]:
        max_loss_threshold = self.get_max_loss_threshold()
        max_holding_days = self.get_max_holding_days()

        days_held = (current_time - trade.open_date_utc).days

        if current_profit < max_loss_threshold and days_held >= max_holding_days:
            logger.info(
                f"Custom exit for {pair}: Held for {days_held} days with profit {current_profit}."
            )
            return "unclog"

        return None