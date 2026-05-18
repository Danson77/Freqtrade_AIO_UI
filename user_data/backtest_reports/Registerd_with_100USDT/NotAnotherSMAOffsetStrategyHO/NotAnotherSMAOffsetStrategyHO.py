# --- Do not remove these libs ---
from freqtrade.strategy.interface import IStrategy
from typing import Dict, List
from functools import reduce
from pandas import DataFrame
# --------------------------------

import pandas as pd
import talib.abstract as ta
import numpy as np
import freqtrade.vendor.qtpylib.indicators as qtpylib

from datetime import datetime, timedelta
from freqtrade.persistence import Trade
from freqtrade.strategy import (
    stoploss_from_open,
    merge_informative_pair,
    DecimalParameter,
    IntParameter,
    CategoricalParameter
)

import technical.indicators as ftt


########################################################################################################################################################
# Custom indicators and helper functions
########################################################################################################################################################
def EWO(dataframe: DataFrame, ema_length: int = 5, ema2_length: int = 35):
    df = dataframe.copy()
    ema1 = ta.EMA(df, timeperiod=ema_length)
    ema2 = ta.EMA(df, timeperiod=ema2_length)
    emadif = (ema1 - ema2) / df['low'] * 100
    return emadif


########################################################################################################################################################
class NotAnotherSMAOffsetStrategyHO(IStrategy):
########################################################################################################################################################

    INTERFACE_VERSION = 3

    buy_params = {
        "base_nb_candles_buy": 26,
        "ewo_high_2": -5.885,
        "low_offset_2": 0.951,
        "rsi_buy": 67,
        "ewo_high": 3.422,
        "low_offset": 0.966,
        "ewo_low": -8.064,
    }

    sell_params = {
        "base_nb_candles_sell": 29,
        "high_offset": 1.064,
        "high_offset_2": 1.002,
        "pHSL": -0.397,
        "pPF_1": 0.012,
        "pPF_2": 0.07,
        "pSL_1": 0.015,
        "pSL_2": 0.068,
    }

    minimal_roi = {
        "0": 0.112,
        "37": 0.096,
        "96": 0.039,
        "200": 0
    }

    stoploss = -0.342

    trailing_stop = True
    trailing_stop_positive = 0.005
    trailing_stop_positive_offset = 0.03
    trailing_only_offset_is_reached = True

    use_custom_stoploss = False
    can_short = False

    timeframe = '5m'
    inf_1h = '1h'
    process_only_new_candles = True
    startup_candle_count = 200

    use_exit_signal = True
    exit_profit_only = False
    exit_profit_offset = 0.01
    ignore_roi_if_entry_signal = False

    slippage_protection = {
        'retries': 3,
        'max_slippage': -0.02
    }

    order_types = {
        'entry': 'limit',
        'exit': 'market',
        'trailing_stop_loss': 'market',
        'emergency_exit': 'market',
        'force_entry': 'market',
        'force_exit': 'market',
        'stoploss': 'market',
        'stoploss_on_exchange': False,
        'stoploss_on_exchange_interval': 60,
        'stoploss_on_exchange_limit_ratio': 0.99
    }

    order_time_in_force = {
        'entry': 'gtc',
        'exit': 'ioc'
    }

    plot_config = {
        'main_plot': {
            'ma_buy': {'color': 'orange'},
            'ma_sell': {'color': 'orange'},
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
    fast_ewo = 50
    slow_ewo = 200

    base_nb_candles_buy = IntParameter(
        5, 80,
        default=buy_params['base_nb_candles_buy'],
        space='buy',
        optimize=False
    )

    ewo_high_2 = DecimalParameter(
        -6.0, 12.0,
        default=buy_params['ewo_high_2'],
        space='buy',
        optimize=False
    )

    low_offset_2 = DecimalParameter(
        0.9, 0.99,
        default=buy_params['low_offset_2'],
        space='buy',
        optimize=False
    )

    rsi_buy = IntParameter(
        30, 70,
        default=buy_params['rsi_buy'],
        space='buy',
        optimize=False
    )

    ewo_high = DecimalParameter(
        2.0, 12.0,
        default=buy_params['ewo_high'],
        space='buy',
        optimize=False
    )

    low_offset = DecimalParameter(
        0.9, 0.99,
        default=buy_params['low_offset'],
        space='buy',
        optimize=False
    )

    ewo_low = DecimalParameter(
        -20.0, -8.0,
        default=buy_params['ewo_low'],
        space='buy',
        optimize=False
    )

    base_nb_candles_sell = IntParameter(
        5, 80,
        default=sell_params['base_nb_candles_sell'],
        space='sell',
        optimize=False
    )

    high_offset = DecimalParameter(
        0.95, 1.1,
        default=sell_params['high_offset'],
        space='sell',
        optimize=False
    )

    high_offset_2 = DecimalParameter(
        0.99, 1.5,
        default=sell_params['high_offset_2'],
        space='sell',
        optimize=True
    )

########################################################################################################################################################
# Custom Stoploss Params
########################################################################################################################################################
    is_optimize_stoploss = False

    pHSL = DecimalParameter(
        -0.500, -0.040,
        default=-0.08,
        decimals=3,
        space='sell',
        optimize=is_optimize_stoploss,
        load=True
    )

    pPF_1 = DecimalParameter(
        0.008, 0.020,
        default=0.016,
        decimals=3,
        space='sell',
        optimize=is_optimize_stoploss,
        load=True
    )

    pSL_1 = DecimalParameter(
        0.008, 0.020,
        default=0.011,
        decimals=3,
        space='sell',
        optimize=is_optimize_stoploss,
        load=True
    )

    pPF_2 = DecimalParameter(
        0.040, 0.100,
        default=0.080,
        decimals=3,
        space='sell',
        optimize=is_optimize_stoploss,
        load=True
    )

    pSL_2 = DecimalParameter(
        0.020, 0.070,
        default=0.040,
        decimals=3,
        space='sell',
        optimize=is_optimize_stoploss,
        load=True
    )

########################################################################################################################################################
# Helpers
########################################################################################################################################################
    @staticmethod
    def _ensure_datetime_utc(dataframe: DataFrame) -> DataFrame:
        if dataframe is None or dataframe.empty:
            return dataframe

        if 'date' in dataframe.columns:
            dataframe['date'] = pd.to_datetime(dataframe['date'], utc=True, errors='coerce')
            dataframe = dataframe.dropna(subset=['date']).copy()

        return dataframe

########################################################################################################################################################
# Informative
########################################################################################################################################################
    def informative_pairs(self):
        pairs = self.dp.current_whitelist()
        return [(pair, self.inf_1h) for pair in pairs]

    def informative_1h_indicators(self, metadata: dict) -> DataFrame:
        """
        Fetch and prepare 1h informative dataframe safely.
        """
        assert self.dp, "DataProvider is required for multiple timeframes."

        informative_1h = self.dp.get_pair_dataframe(
            pair=metadata['pair'],
            timeframe=self.inf_1h
        )

        if informative_1h is None or informative_1h.empty:
            return DataFrame()

        informative_1h = informative_1h.copy()
        informative_1h = self._ensure_datetime_utc(informative_1h)

        if informative_1h.empty:
            return DataFrame()

        informative_1h['ema_50'] = ta.EMA(informative_1h, timeperiod=50)
        informative_1h['ema_200'] = ta.EMA(informative_1h, timeperiod=200)
        informative_1h['rsi'] = ta.RSI(informative_1h, timeperiod=14)

        bollinger = qtpylib.bollinger_bands(
            qtpylib.typical_price(informative_1h),
            window=20,
            stds=2
        )
        informative_1h['bb_lowerband'] = bollinger['lower']
        informative_1h['bb_middleband'] = bollinger['mid']
        informative_1h['bb_upperband'] = bollinger['upper']

        return informative_1h

########################################################################################################################################################
# Indicators
########################################################################################################################################################
    def normal_tf_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        for val in self.base_nb_candles_buy.range:
            dataframe[f'ma_buy_{val}'] = ta.EMA(dataframe, timeperiod=val)

        for val in self.base_nb_candles_sell.range:
            dataframe[f'ma_sell_{val}'] = ta.EMA(dataframe, timeperiod=val)

        dataframe['hma_50'] = qtpylib.hull_moving_average(dataframe['close'], window=50)
        dataframe['ema_100'] = ta.EMA(dataframe, timeperiod=100)
        dataframe['sma_9'] = ta.SMA(dataframe, timeperiod=9)

        dataframe['EWO'] = EWO(dataframe, self.fast_ewo, self.slow_ewo)

        dataframe['rsi'] = ta.RSI(dataframe, timeperiod=14)
        dataframe['rsi_fast'] = ta.RSI(dataframe, timeperiod=4)
        dataframe['rsi_slow'] = ta.RSI(dataframe, timeperiod=20)

        return dataframe

########################################################################################################################################################
# Merge + Populate
########################################################################################################################################################
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = dataframe.copy()
        dataframe = self._ensure_datetime_utc(dataframe)

        informative_1h = self.informative_1h_indicators(metadata)

        # Merge only if informative data actually exists and has valid dates.
        if informative_1h is not None and not informative_1h.empty and 'date' in informative_1h.columns:
            dataframe = merge_informative_pair(
                dataframe,
                informative_1h,
                self.timeframe,
                self.inf_1h,
                ffill=True
            )
        else:
            # Create fallback columns so strategy won't explode if 1h data is missing.
            fallback_cols = [
                f'ema_50_{self.inf_1h}',
                f'ema_200_{self.inf_1h}',
                f'rsi_{self.inf_1h}',
                f'bb_lowerband_{self.inf_1h}',
                f'bb_middleband_{self.inf_1h}',
                f'bb_upperband_{self.inf_1h}',
            ]
            for col in fallback_cols:
                if col not in dataframe.columns:
                    dataframe[col] = np.nan

        dataframe = self.normal_tf_indicators(dataframe, metadata)
        return dataframe

########################################################################################################################################################
# Buy
########################################################################################################################################################
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                (dataframe['rsi_fast'] < 35) &
                (dataframe['close'] < (dataframe[f'ma_buy_{self.base_nb_candles_buy.value}'] * self.low_offset.value)) &
                (dataframe['EWO'] < self.ewo_low.value) &
                (dataframe['volume'] > 0) &
                (dataframe['close'] < (dataframe[f'ma_sell_{self.base_nb_candles_sell.value}'] * self.high_offset.value))
            ),
            ['enter_long', 'enter_tag']
        ] = (1, 'ewolow')

        dataframe.loc[
            (
                (dataframe['rsi_fast'] < 35) &
                (dataframe['close'] < (dataframe[f'ma_buy_{self.base_nb_candles_buy.value}'] * self.low_offset.value)) &
                (dataframe['EWO'] > self.ewo_high.value) &
                (dataframe['rsi'] < self.rsi_buy.value) &
                (dataframe['volume'] > 0) &
                (dataframe['close'] < (dataframe[f'ma_sell_{self.base_nb_candles_sell.value}'] * self.high_offset.value))
            ),
            ['enter_long', 'enter_tag']
        ] = (1, 'ewo1')

        dataframe.loc[
            (
                (dataframe['rsi_fast'] < 35) &
                (dataframe['close'] < (dataframe[f'ma_buy_{self.base_nb_candles_buy.value}'] * self.low_offset_2.value)) &
                (dataframe['EWO'] > self.ewo_high_2.value) &
                (dataframe['rsi'] < self.rsi_buy.value) &
                (dataframe['volume'] > 0) &
                (dataframe['close'] < (dataframe[f'ma_sell_{self.base_nb_candles_sell.value}'] * self.high_offset.value)) &
                (dataframe['rsi'] < 25)
            ),
            ['enter_long', 'enter_tag']
        ] = (1, 'ewo2')

        return dataframe

########################################################################################################################################################
# Sell
########################################################################################################################################################
    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        conditions = []

        conditions.append(
            (
                (dataframe['close'] > dataframe['sma_9']) &
                (dataframe['close'] > (dataframe[f'ma_sell_{self.base_nb_candles_sell.value}'] * self.high_offset_2.value)) &
                (dataframe['rsi'] > 50) &
                (dataframe['volume'] > 0) &
                (dataframe['rsi_fast'] > dataframe['rsi_slow'])
            )
            |
            (
                (dataframe['close'] < dataframe['hma_50']) &
                (dataframe['close'] > (dataframe[f'ma_sell_{self.base_nb_candles_sell.value}'] * self.high_offset.value)) &
                (dataframe['volume'] > 0) &
                (dataframe['rsi_fast'] > dataframe['rsi_slow'])
            )
        )

        if conditions:
            dataframe.loc[reduce(lambda x, y: x | y, conditions), 'exit_long'] = 1

        return dataframe

########################################################################################################################################################
# Custom Trailing stoploss
########################################################################################################################################################
    def custom_stoploss(
        self,
        pair: str,
        trade: Trade,
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

########################################################################################################################################################
# Confirm Exit
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

        if exit_reason == 'exit_signal':
            if (
                last_candle['hma_50'] * 1.149 > last_candle['ema_100']
                and last_candle['close'] < last_candle['ema_100'] * 0.951
            ):
                return False

        slippage = (rate / last_candle['close']) - 1
        max_slippage = self.slippage_protection.get('max_slippage', 0.01)
        retries_allowed = self.slippage_protection.get('retries', 3)

        state = self.slippage_protection.setdefault('__pair_retries', {})
        pair_retries = state.get(pair, 0)

        if slippage < max_slippage:
            if pair_retries < retries_allowed:
                state[pair] = pair_retries + 1
                return False
            else:
                state[pair] = 0

        return True