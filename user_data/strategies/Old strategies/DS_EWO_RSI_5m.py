from datetime import datetime, timedelta
from typing import Optional, Union
import freqtrade.vendor.qtpylib.indicators as qtpylib
import talib.abstract as ta
import pandas_ta as pta
import pandas as pd
from freqtrade.persistence import Trade
from freqtrade.strategy.interface import IStrategy
from pandas import DataFrame
from freqtrade.strategy import DecimalParameter, IntParameter
from functools import reduce

############################################################################
# Custom indicators and helper functions
############################################################################
def ewo(dataframe, ema_length=5, ema2_length=35):
    df = dataframe.copy()
    ema1 = ta.EMA(df, timeperiod=ema_length)
    ema2 = ta.EMA(df, timeperiod=ema2_length)
    emadif = (ema1 - ema2) / df['low'] * 100
    return emadif
########################################################################################################################################################
class DS_EWO_RSI_5m(IStrategy):
########################################################################################################################################################
# Hyperopt
########################################################################################################################################################
    buy_params = {
        # RSI/EWO
        "buy_rsi_fast": 50,
        "buy_rsi": 30,
        "buy_ewo": -1.238,
        "buy_ema_low": 0.956,
        "buy_ema_high": 0.986,
        # CTI/SMA
        "buy_rsi_fast_32": 63,
        "buy_rsi_32": 16,
        "buy_sma15_32": 0.932,
        "buy_cti_32": -0.8,
    }
    sell_params = {
        # DEADFISH
        "sell_deadfish_bb_width": 0.05,
        "sell_deadfish_profit": -0.05,
        "sell_deadfish_bb_factor": 1.0,
        "sell_deadfish_volume_factor": 1.0,
        "sell_fastx": 75,
    }
    minimal_roi = {
        "0": 10
    }
    stoploss = -0.99
    trailing_stop = False  # Whether to use a trailing stop.
    trailing_stop_positive = 0.02 #povodne 0.001
    trailing_stop_positive_offset = 0.10 #povodne 0.012
    trailing_only_offset_is_reached = True  # Only trigger trailing stop if the offset is reached.
    use_custom_stoploss = True  # Whether to use a custom stoploss function.
########################################################################################################################################################
# Main
########################################################################################################################################################
    timeframe = '5m'  # The primary timeframe for analysis.
    process_only_new_candles = True
    startup_candle_count = 20

    # Sell signal configuration.
    use_exit_signal = True  # Whether to use the strategy's exit signal.
    exit_profit_only = False  # If True, only sell when in profit.
    exit_profit_offset = 0.01  # Offset added to exit signal (profitable threshold).
    ignore_roi_if_entry_signal = False  # If True, ignore ROI when the buy signal is still present.

    # Configuration of order types.
    order_types = {
        'entry': 'market',
        'exit': 'market',
        'emergency_exit': 'market',
        'force_entry': 'market',
        'force_exit': "market",
        'stoploss': 'market',
        'stoploss_on_exchange': False,
        'stoploss_on_exchange_interval': 60,
        'stoploss_on_exchange_limit_ratio': 0.99
    }
    # Order Time-In-Force defines how long an order will remain active before it is executed or expired.
    order_time_in_force = {
        'entry': 'gtc',
        'exit': 'gtc'
    }
    # Plotting configuration for visualizing indicators in backtesting.
    plot_config = {
        'main_plot': {
            'ma_buy': {'color': 'orange'},  # Color for the buy moving average.
            'ma_sell': {'color': 'orange'},  # Color for the sell moving average.
        },
    }
########################################################################################################################################################
# Parameters
########################################################################################################################################################
    is_optimize_ewo = True
    buy_rsi_fast = IntParameter(35, 50, default=50, space='buy', optimize=is_optimize_ewo)
    buy_rsi = IntParameter(15, 35, default=30, space='buy', optimize=is_optimize_ewo)
    buy_ewo = DecimalParameter(-6.0, 5, default=-1.238, space='buy', optimize=is_optimize_ewo)
    buy_ema_low = DecimalParameter(0.9, 0.99, default=0.956, space='buy', optimize=is_optimize_ewo)
    buy_ema_high = DecimalParameter(0.95, 1.2, default=0.986, space='buy', optimize=is_optimize_ewo)

    is_optimize_32 = True
    buy_rsi_fast_32 = IntParameter(20, 70, default=63, space='buy', optimize=is_optimize_32)
    buy_rsi_32 = IntParameter(15, 50, default=16, space='buy', optimize=is_optimize_32)
    buy_sma15_32 = DecimalParameter(0.900, 1, default=0.932, decimals=3, space='buy', optimize=is_optimize_32)
    buy_cti_32 = DecimalParameter(-1, 0, default=-0.8, decimals=2, space='buy', optimize=is_optimize_32)

    is_optimize_deadfish = True
    sell_deadfish_bb_width = DecimalParameter(0.03, 0.75, default=0.05, space='sell', optimize=is_optimize_deadfish)
    sell_deadfish_profit = DecimalParameter(-0.15, -0.05, default=-0.05, space='sell', optimize=is_optimize_deadfish)
    sell_deadfish_bb_factor = DecimalParameter(0.90, 1.20, default=1.0, space='sell', optimize=is_optimize_deadfish)
    sell_deadfish_volume_factor = DecimalParameter(1, 2.5, default=1.0, space='sell', optimize=is_optimize_deadfish)

    sell_fastx = IntParameter(50, 100, default=75, space='sell', optimize=True)
########################################################################################################################################################
# Indicators
######################################################################################################################################################## 
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:

        # buy_1 indicators
        dataframe['sma_15'] = ta.SMA(dataframe, timeperiod=15)
        dataframe['cti'] = pta.cti(dataframe["close"], length=20)
        dataframe['rsi'] = ta.RSI(dataframe, timeperiod=14)
        dataframe['rsi_fast'] = ta.RSI(dataframe, timeperiod=4)
        dataframe['rsi_slow'] = ta.RSI(dataframe, timeperiod=20)

        # ewo indicators
        dataframe['ema_8'] = ta.EMA(dataframe, timeperiod=8)
        dataframe['ema_16'] = ta.EMA(dataframe, timeperiod=16)
        dataframe['EWO'] = ewo(dataframe, 50, 200)

        # profit sell indicators
        stoch_fast = ta.STOCHF(dataframe, 5, 3, 0, 3, 0)
        dataframe['fastd'] = stoch_fast['fastd']
        dataframe['fastk'] = stoch_fast['fastk']

        # loss sell indicators
        bollinger2 = qtpylib.bollinger_bands(qtpylib.typical_price(dataframe), window=20, stds=2)
        dataframe['bb_lowerband2'] = bollinger2['lower']
        dataframe['bb_middleband2'] = bollinger2['mid']
        dataframe['bb_upperband2'] = bollinger2['upper']

        dataframe['bb_width'] = ((dataframe['bb_upperband2'] - dataframe['bb_lowerband2']) / dataframe['bb_middleband2'])

        dataframe['volume_mean_12'] = dataframe['volume'].rolling(12).mean().shift(1)
        dataframe['volume_mean_24'] = dataframe['volume'].rolling(24).mean().shift(1)

        dataframe['entry_price'] = dataframe['close'].shift(1)  # Placeholder for actual entry price
        dataframe['exit_price'] = dataframe['close']  # Placeholder for actual exit price

        # Calculate profit as a percentage
        dataframe['profit'] = (dataframe['exit_price'] - dataframe['entry_price']) / dataframe['entry_price'] * 100

        return dataframe
########################################################################################################################################################
# Buy Signal
########################################################################################################################################################
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:

        conditions = []
        dataframe.loc[:, 'enter_tag'] = ''

        rsi_fast = (
                (dataframe['rsi_fast'] < self.buy_rsi_fast.value) &
                (dataframe['close'] < dataframe['ema_8'] * self.buy_ema_low.value) &
                (dataframe['EWO'] > self.buy_ewo.value) &
                (dataframe['close'] < dataframe['ema_16'] * self.buy_ema_high.value) &
                (dataframe['rsi'] < self.buy_rsi.value)
        )

        rsi_slow = (
                (dataframe['rsi_slow'] < dataframe['rsi_slow'].shift(1)) &
                (dataframe['rsi_fast'] < self.buy_rsi_fast_32.value) &
                (dataframe['rsi'] > self.buy_rsi_32.value) &
                (dataframe['close'] < dataframe['sma_15'] * self.buy_sma15_32.value) &
                (dataframe['cti'] < self.buy_cti_32.value)
        )

        conditions.append(rsi_fast)
        dataframe.loc[rsi_fast, 'enter_tag'] += 'rsi_fast'

        conditions.append(rsi_slow)
        dataframe.loc[rsi_slow, 'enter_tag'] += 'rsi_slow'

        if conditions:
            dataframe.loc[
                reduce(lambda x, y: x | y, conditions),
                'enter_long'] = 1

        return dataframe
########################################################################################################################################################
# Custom Stoploss
########################################################################################################################################################
    def custom_stoploss(self, pair: str, trade: Trade, current_time: datetime, current_rate: float, current_profit: float, **kwargs) -> float:

        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        current_candle = dataframe.iloc[-1].squeeze()

        if current_time - timedelta(minutes=60) > trade.open_date_utc:
            if (current_candle["fastk"] > self.sell_fastx.value) and (current_profit > -0.01):
                return -0.001

        if current_time - timedelta(days=1) > trade.open_date_utc:
            if (current_candle["fastk"] > self.sell_fastx.value) and (current_profit > -0.05):
                return -0.001

        enter_tag = ''
        if hasattr(trade, 'enter_tag') and trade.enter_tag is not None:
            enter_tag = trade.enter_tag
        enter_tags = enter_tag.split()

        if "ewo" in enter_tags:
            if current_profit >= 0.05:
                return -0.005

        if current_profit > 0:
            if current_candle["fastk"] > self.sell_fastx.value:
                return -0.001

        return self.stoploss
########################################################################################################################################################
# Sell signal
########################################################################################################################################################
    def populate_exit_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:

        # Initialize default exit signals
        dataframe['exit_long'] = 0
        dataframe['exit_tag'] = None

        # Stoploss - Deadfish exit condition
        dataframe.loc[
            (dataframe['profit'] < self.sell_deadfish_profit.value) &
            (dataframe['bb_width'] < self.sell_deadfish_bb_width.value) &
            (dataframe['close'] > dataframe['bb_middleband2'] * self.sell_deadfish_bb_factor.value) &
            (dataframe['volume_mean_12'] < dataframe['volume_mean_24'] * self.sell_deadfish_volume_factor.value),
            ['exit_long', 'exit_tag']
            ] = (1, 'sell_stoploss_deadfish')

        return dataframe