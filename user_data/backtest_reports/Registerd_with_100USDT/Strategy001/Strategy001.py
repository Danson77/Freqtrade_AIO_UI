
# --- Do not remove these libs ---
from freqtrade.strategy.interface import IStrategy
from typing import Dict, List
from functools import reduce
from pandas import DataFrame
# --------------------------------

import talib.abstract as ta
import freqtrade.vendor.qtpylib.indicators as qtpylib
from datetime import datetime, timedelta
from freqtrade.persistence import Trade

########################################################################################################################################################
class Strategy001(IStrategy):
########################################################################################################################################################
    """
    Strategy 001_custom_sell
    author@: Gerald Lonlas, froggleston
    github@: https://github.com/freqtrade/freqtrade-strategies
    """
########################################################################################################################################################
# Hyperopt
########################################################################################################################################################
    buy_params = {
    }
    sell_params = {
    }
########################################################################################################################################################
# Main
########################################################################################################################################################
    can_short = False

    minimal_roi = {
        "60":  0.01,
        "30":  0.03,
        "20":  0.04,
        "0":  0.05
    }
    ignore_roi_if_entry_signal = False
    
    stoploss = -0.25
    use_custom_stoploss = False

    trailing_stop = False
    trailing_stop_positive = 0.01
    trailing_stop_positive_offset = 0.02
    trailing_only_offset_is_reached = False

    use_entry_signal = True
    use_custom_entry = False

    use_exit_signal = True
    use_custom_exit = True

    exit_profit_only = True
    exit_profit_offset = 0.01
########################################################################################################################################################
# Timeframe and order settings
########################################################################################################################################################
    timeframe = '5m'
    informative_timeframe = '1h'
    process_only_new_candles = False
    startup_candle_count = 80

    order_types = {
        'entry': 'market',
        'exit': 'market',
        'trailing_stop_loss': 'market',
        'emergency_exit': 'market',
        'force_entry': 'market',
        'force_exit': 'market',
        'stoploss': 'market',
        'stoploss_on_exchange': True,
        'stoploss_on_exchange_interval': 60,
        'stoploss_on_exchange_limit_ratio': 0.99
    }
    order_time_in_force = {
        'entry': 'gtc',
        'exit': 'gtc'
    }
    plot_config = {
        'main_plot': {
            'close': {},
        },
        'subplots': {
            "EWO": {
                'EWO': {'color': 'blue'}
            },
            "RSI": {
                'rsi': {'color': 'orange'},
                'rsi_fast': {'color': 'green'},
                'rsi_slow': {'color': 'red'}
            }
        }
    }
########################################################################################################################################################
# Informative
########################################################################################################################################################
    def informative_pairs(self):
        """
        Define additional, informative pair/interval combinations to be cached from the exchange.
        These pair/interval combinations are non-tradeable, unless they are part
        of the whitelist as well.
        For more information, please consult the documentation
        :return: List of tuples in the format (pair, interval)
            Sample: return [("ETH/USDT", "5m"),
                            ("BTC/USDT", "15m"),
                            ]
        """
        return []
########################################################################################################################################################
# Indicators
########################################################################################################################################################
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe['ema20'] = ta.EMA(dataframe, timeperiod=20)
        dataframe['ema50'] = ta.EMA(dataframe, timeperiod=50)
        dataframe['ema100'] = ta.EMA(dataframe, timeperiod=100)

        heikinashi = qtpylib.heikinashi(dataframe)
        dataframe['ha_open'] = heikinashi['open']
        dataframe['ha_close'] = heikinashi['close']

        dataframe['rsi'] = ta.RSI(dataframe, 14)

        return dataframe
########################################################################################################################################################
# Buy
########################################################################################################################################################
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                qtpylib.crossed_above(dataframe['ema20'], dataframe['ema50']) &
                (dataframe['ha_close'] > dataframe['ema20']) &
                (dataframe['ha_open'] < dataframe['ha_close'])  # green bar
            ),
            'enter_long'] = 1

        return dataframe
########################################################################################################################################################
# Sell
########################################################################################################################################################
    def populate_sell_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                qtpylib.crossed_above(dataframe['ema50'], dataframe['ema100']) &
                (dataframe['ha_close'] < dataframe['ema20']) &
                (dataframe['ha_open'] > dataframe['ha_close'])  # red bar
            ),
            'exit_long'] = 1
        return dataframe
########################################################################################################################################################
# Custom Sell
########################################################################################################################################################
    def custom_exit(self, pair: str, trade: 'Trade', current_time: 'datetime', current_rate: float, current_profit: float, **kwargs):
        # get dataframe
        dataframe, _ = self.dp.get_analyzed_dataframe(
            pair=pair, timeframe=self.timeframe)

        # get the current candle
        current_candle = dataframe.iloc[-1].squeeze()

        # if RSI greater than 70 and profit is positive, then sell
        if (current_candle['rsi'] > 70) and (current_profit > 0):
            return "rsi_profit_sell"

        # else, hold
        return None
