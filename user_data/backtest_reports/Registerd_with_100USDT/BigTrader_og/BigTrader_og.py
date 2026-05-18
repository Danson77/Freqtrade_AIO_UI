
from freqtrade.strategy.interface import IStrategy
from freqtrade.strategy import merge_informative_pair
from typing import Dict, List
from functools import reduce
from pandas import DataFrame


import talib.abstract as ta
import freqtrade.vendor.qtpylib.indicators as qtpylib
import datetime
from technical.util import resample_to_interval, resampled_merge
from datetime import datetime, timedelta
from freqtrade.persistence import Trade
from freqtrade.strategy import stoploss_from_open






















































low_offset = 0.958 # something lower than 1
high_offset = 1.012 # something higher than 1


class BigTrader_og(IStrategy):
    INTERFACE_VERSION = 2

    minimal_roi = {
        "0": 0.09,
    }

    stoploss = -0.5

    trailing_stop = True
    trailing_stop_positive = 0.005
    trailing_stop_positive_offset = 0.029
    trailing_only_offset_is_reached = True

    use_sell_signal = True
    sell_profit_only = True
    sell_profit_offset = 0.01
    ignore_roi_if_buy_signal = True

    timeframe = '5m'

    process_only_new_candles = True

    startup_candle_count: int = 60

    order_types = {
        'buy': 'market',
        'sell': 'market',
        'stoploss': 'market',
        'stoploss_on_exchange': True
    }

    order_time_in_force = {
        'buy': 'gtc',
        'sell': 'gtc'
    }

    plot_config = {
        'main_plot': {
            'tema': {},
            'sar': {'color': 'white'},
        },
        'subplots': {
            "MACD": {
                'macd': {'color': 'blue'},
                'macdsignal': {'color': 'orange'},
            },
            "RSI": {
                'rsi': {'color': 'red'},
            }
        }
    }








    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:









        dataframe['sma_15'] = ta.SMA(dataframe, timeperiod=15)









        return dataframe

    def populate_buy_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                (dataframe['close'] < (dataframe['sma_15'] * low_offset))
                &
                (dataframe['close'] > dataframe['close'].shift(4))
                &
                (dataframe['close'].shift(8) > dataframe['close'].shift(4))
                &
                (dataframe['close'].shift(12) > dataframe['close'].shift(8))
                &
                (dataframe['volume'] > 0)
                ),
            'buy'] = 1
        return dataframe

    def populate_sell_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                (dataframe['open'] > (dataframe['sma_15'] * high_offset))
                &
                (dataframe['open'] < dataframe['close'].shift(4))
                &
                (dataframe['close'].shift(8) < dataframe['close'].shift(4))
                &
                (dataframe['close'].shift(12) < dataframe['close'].shift(8))
                &
                (dataframe['volume'] > 0)
                ),
            'sell'] = 1
        return dataframe