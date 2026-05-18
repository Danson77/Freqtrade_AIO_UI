import freqtrade.vendor.qtpylib.indicators as qtpylib
import numpy as np
import pandas as pd
import talib.abstract as ta

from freqtrade.strategy.interface import IStrategy
from freqtrade.strategy import merge_informative_pair, DecimalParameter, stoploss_from_open
from pandas import DataFrame, Series
from datetime import datetime
from freqtrade.persistence import Trade


def bollinger_bands(stock_price, window_size, num_of_std):
    rolling_mean = stock_price.rolling(window=window_size).mean()
    rolling_std = stock_price.rolling(window=window_size).std()
    lower_band = rolling_mean - (rolling_std * num_of_std)
    return np.nan_to_num(rolling_mean), np.nan_to_num(lower_band)


def ha_typical_price(bars):
    res = (bars['ha_high'] + bars['ha_low'] + bars['ha_close']) / 3.0
    return Series(index=bars.index, data=res)


class ClucHAnix(IStrategy):
    INTERFACE_VERSION = 3

    buy_params = {
        'bbdelta-close': 0.01965,
        'bbdelta-tail': 0.95089,
        'close-bblower': 0.00799,
        'closedelta-close': 0.00556,
        'rocr-1h': 0.54904
    }

    sell_params = {
        "pHSL": -0.35,
        "pPF_1": 0.02,
        "pPF_2": 0.05,
        "pSL_1": 0.02,
        "pSL_2": 0.04,
        'sell-fisher': 0.38414,
        'sell-bbmiddle-close': 1.07634
    }

    minimal_roi = {
        "0": 100
    }

    stoploss = -0.99
    trailing_stop = False
    trailing_stop_positive = 0.001
    trailing_stop_positive_offset = 0.012
    trailing_only_offset_is_reached = False

    timeframe = '1m'
    inf_tf = '1h'

    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    use_custom_stoploss = True
    process_only_new_candles = True
    startup_candle_count = 168
    can_short = False

    order_types = {
        'entry': 'market',
        'exit': 'market',
        'emergency_exit': 'market',
        'force_entry': "market",
        'force_exit': 'market',
        'stoploss': 'market',
        'stoploss_on_exchange': False,
        'stoploss_on_exchange_interval': 60,
        'stoploss_on_exchange_limit_ratio': 0.99
    }

    pHSL = DecimalParameter(-0.200, -0.040, default=-0.08, decimals=3, space='sell', load=True)
    pPF_1 = DecimalParameter(0.008, 0.020, default=0.016, decimals=3, space='sell', load=True)
    pSL_1 = DecimalParameter(0.008, 0.020, default=0.011, decimals=3, space='sell', load=True)
    pPF_2 = DecimalParameter(0.040, 0.100, default=0.080, decimals=3, space='sell', load=True)
    pSL_2 = DecimalParameter(0.020, 0.070, default=0.040, decimals=3, space='sell', load=True)

    def informative_pairs(self):
        pairs = self.dp.current_whitelist()
        return [(pair, self.inf_tf) for pair in pairs]

    @staticmethod
    def _ensure_datetime(dataframe: DataFrame) -> DataFrame:
        if dataframe is None or dataframe.empty:
            return dataframe
        if 'date' in dataframe.columns:
            dataframe = dataframe.copy()
            dataframe['date'] = pd.to_datetime(dataframe['date'], utc=True, errors='coerce')
            dataframe = dataframe.dropna(subset=['date'])
        return dataframe

    def _add_empty_informative_cols(self, dataframe: DataFrame) -> DataFrame:
        fallback_cols = [
            f'ha_close_{self.inf_tf}',
            f'rocr_{self.inf_tf}',
        ]
        for col in fallback_cols:
            if col not in dataframe.columns:
                dataframe[col] = np.nan
        return dataframe

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

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = dataframe.copy()
        dataframe = self._ensure_datetime(dataframe)

        # Main timeframe Heikin Ashi
        if dataframe is not None and not dataframe.empty:
            heikinashi = qtpylib.heikinashi(dataframe)
            dataframe['ha_open'] = heikinashi['open']
            dataframe['ha_close'] = heikinashi['close']
            dataframe['ha_high'] = heikinashi['high']
            dataframe['ha_low'] = heikinashi['low']
        else:
            dataframe['ha_open'] = np.nan
            dataframe['ha_close'] = np.nan
            dataframe['ha_high'] = np.nan
            dataframe['ha_low'] = np.nan

        # Bollinger
        mid, lower = bollinger_bands(ha_typical_price(dataframe), window_size=40, num_of_std=2)
        dataframe['lower'] = lower
        dataframe['mid'] = mid

        dataframe['bbdelta'] = (dataframe['mid'] - dataframe['lower']).abs()
        dataframe['closedelta'] = (dataframe['ha_close'] - dataframe['ha_close'].shift()).abs()
        dataframe['tail'] = (dataframe['ha_close'] - dataframe['ha_low']).abs()

        dataframe['bb_lowerband'] = dataframe['lower']
        dataframe['bb_middleband'] = dataframe['mid']

        dataframe['ema_fast'] = ta.EMA(dataframe['ha_close'], timeperiod=3)
        dataframe['ema_slow'] = ta.EMA(dataframe['ha_close'], timeperiod=50)
        dataframe['volume_mean_slow'] = dataframe['volume'].rolling(window=30).mean()
        dataframe['rocr'] = ta.ROCR(dataframe['ha_close'], timeperiod=28)

        rsi = ta.RSI(dataframe)
        dataframe["rsi"] = rsi
        rsi_scaled = 0.1 * (rsi - 50)
        dataframe["fisher"] = (np.exp(2 * rsi_scaled) - 1) / (np.exp(2 * rsi_scaled) + 1)

        # Informative 1h
        informative = self.dp.get_pair_dataframe(pair=metadata['pair'], timeframe=self.inf_tf)

        if informative is not None and not informative.empty:
            informative = informative.copy()
            informative = self._ensure_datetime(informative)

            if informative is not None and not informative.empty:
                inf_heikinashi = qtpylib.heikinashi(informative)
                informative['ha_close'] = inf_heikinashi['close']
                informative['rocr'] = ta.ROCR(informative['ha_close'], timeperiod=168)

                dataframe = merge_informative_pair(
                    dataframe,
                    informative,
                    self.timeframe,
                    self.inf_tf,
                    ffill=True
                )
            else:
                dataframe = self._add_empty_informative_cols(dataframe)
        else:
            dataframe = self._add_empty_informative_cols(dataframe)

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        params = self.buy_params
        dataframe['enter_long'] = 0

        dataframe.loc[
            (
                dataframe[f'rocr_{self.inf_tf}'].gt(params['rocr-1h'])
            ) &
            (
                (
                    (dataframe['lower'].shift().gt(0)) &
                    (dataframe['bbdelta'].gt(dataframe['ha_close'] * params['bbdelta-close'])) &
                    (dataframe['closedelta'].gt(dataframe['ha_close'] * params['closedelta-close'])) &
                    (dataframe['tail'].lt(dataframe['bbdelta'] * params['bbdelta-tail'])) &
                    (dataframe['ha_close'].lt(dataframe['lower'].shift())) &
                    (dataframe['ha_close'].le(dataframe['ha_close'].shift()))
                ) |
                (
                    (dataframe['ha_close'] < dataframe['ema_slow']) &
                    (dataframe['ha_close'] < params['close-bblower'] * dataframe['bb_lowerband'])
                )
            ),
            'enter_long'
        ] = 1

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        params = self.sell_params
        dataframe['exit_long'] = 0

        dataframe.loc[
            (dataframe['fisher'] > params['sell-fisher']) &
            (dataframe['ha_high'].le(dataframe['ha_high'].shift(1))) &
            (dataframe['ha_high'].shift(1).le(dataframe['ha_high'].shift(2))) &
            (dataframe['ha_close'].le(dataframe['ha_close'].shift(1))) &
            (dataframe['ema_fast'] > dataframe['ha_close']) &
            ((dataframe['ha_close'] * params['sell-bbmiddle-close']) > dataframe['bb_middleband']) &
            (dataframe['volume'] > 0),
            'exit_long'
        ] = 1

        return dataframe