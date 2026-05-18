from datetime import datetime, timedelta
from typing import Optional, Union
import freqtrade.vendor.qtpylib.indicators as qtpylib
import talib.abstract as ta
import pandas_ta as pta
from freqtrade.persistence import Trade
from freqtrade.strategy.interface import IStrategy
from pandas import DataFrame
from freqtrade.strategy import DecimalParameter, IntParameter
from functools import reduce
########################################################################################################################################################
# EWO (Elliott Wave Oscillator) Calculation
########################################################################################################################################################
def ewo(dataframe: DataFrame, ema_length: int = 5, ema2_length: int = 35) -> DataFrame:
    ema1 = ta.EMA(dataframe, timeperiod=ema_length)
    ema2 = ta.EMA(dataframe, timeperiod=ema2_length)
    emadif = (ema1 - ema2) / dataframe['low'] * 100
    return emadif

#def ewo(dataframe, ema_length=5, ema2_length=35):
#    ema1 = ta.EMA(dataframe, timeperiod=ema_length)
#    ema2 = ta.EMA(dataframe, timeperiod=ema2_length)
#    emadif = (ema1 - ema2) / dataframe['low'] * 100
#    return emadif
########################################################################################################################################################
class E0V1E(IStrategy):
########################################################################################################################################################
# Hyperopt
########################################################################################################################################################
    minimal_roi = {
        "0": 100
    }

    # Optimal timeframe for the strategy
    timeframe = '5m'

    # Run "populate_indicators()" only for new candle.
    process_only_new_candles = True
    startup_candle_count = 20

    order_types = {
        'entry': 'market',
        'exit': 'market',
        'emergency_exit': 'market',
        'force_entry': 'market',
        'force_exit': "market",
        'stoploss': 'market',
        'stoploss_on_exchange': False,

        'stoploss_on_exchange_interval': 60,
        'stoploss_on_exchange_market_ratio': 0.99
    }

    # Disabled
    stoploss = -0.1

    # Custom stoploss
    use_custom_stoploss = True
########################################################################################################################################################
# Parameters
########################################################################################################################################################
    is_optimize_ewo = True
    buy_rsi_fast = IntParameter(35, 50, default=45, space='buy', optimize=is_optimize_ewo)
    buy_rsi = IntParameter(15, 35, default=35, space='buy', optimize=is_optimize_ewo)
    buy_ewo = DecimalParameter(-6.0, 5, default=-5.585, space='buy', optimize=is_optimize_ewo)
    buy_ema_low = DecimalParameter(0.9, 0.99, default=0.942, space='buy', optimize=is_optimize_ewo)
    buy_ema_high = DecimalParameter(0.95, 1.2, default=1.084, space='buy', optimize=is_optimize_ewo)

    is_optimize_32 = False
    buy_rsi_fast_32 = IntParameter(20, 70, default=46, space='buy', optimize=is_optimize_32)
    buy_rsi_32 = IntParameter(15, 50, default=19, space='buy', optimize=is_optimize_32)
    buy_sma15_32 = DecimalParameter(0.900, 1, default=0.942, decimals=3, space='buy', optimize=is_optimize_32)
    buy_cti_32 = DecimalParameter(-1, 0, default=-0.86, decimals=2, space='buy', optimize=is_optimize_32)

    is_optimize_deadfish = False
    sell_deadfish_bb_width = DecimalParameter(0.03, 0.75, default=0.05, space='sell', optimize=is_optimize_deadfish)
    sell_deadfish_profit = DecimalParameter(-0.15, -0.05, default=-0.05, space='sell', optimize=is_optimize_deadfish)
    sell_deadfish_bb_factor = DecimalParameter(0.90, 1.20, default=1.0, space='sell', optimize=is_optimize_deadfish)
    sell_deadfish_volume_factor = DecimalParameter(1, 2.5, default=1.0, space='sell', optimize=is_optimize_deadfish)

    sell_fastx = IntParameter(50, 100, default=75, space='sell', optimize=False)
    delay_time = IntParameter(90, 1440, default=300, space='sell', optimize=False)
    fask_trailing = DecimalParameter(0.001, 0.02, default=0.001, space='sell', optimize=True)
########################################################################################################################################################
# Indicators
########################################################################################################################################################
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        if dataframe.empty:
            return dataframe

        # Calculate moving averages
        dataframe['sma_15'] = ta.SMA(dataframe, timeperiod=15)
        dataframe['ema_8'] = ta.EMA(dataframe, timeperiod=8)
        dataframe['ema_16'] = ta.EMA(dataframe, timeperiod=16)

        # RSI calculations
        dataframe['rsi'] = ta.RSI(dataframe, timeperiod=14)
        dataframe['rsi_fast'] = ta.RSI(dataframe, timeperiod=4)
        dataframe['rsi_slow'] = ta.RSI(dataframe, timeperiod=20)

        # Commodity Channel Index (CTI)
        dataframe['cti'] = pta.cti(dataframe["close"], length=20)

        # Stochastic Fast Indicator
        stoch_fast = ta.STOCHF(dataframe, fastk_period=5, fastd_period=3)
        dataframe['fastd'] = stoch_fast['fastd']
        dataframe['fastk'] = stoch_fast['fastk']

        # Bollinger Bands
        bollinger2 = qtpylib.bollinger_bands(qtpylib.typical_price(dataframe), window=20, stds=2)
        dataframe['bb_lowerband2'] = bollinger2['lower']
        dataframe['bb_middleband2'] = bollinger2['mid']
        dataframe['bb_upperband2'] = bollinger2['upper']
        dataframe['bb_width'] = (dataframe['bb_upperband2'] - dataframe['bb_lowerband2']) / dataframe['bb_middleband2']

        # Volume moving averages
        dataframe['volume_mean_12'] = dataframe['volume'].rolling(12).mean().shift(1)
        dataframe['volume_mean_24'] = dataframe['volume'].rolling(24).mean().shift(1)

        # Custom indicator (EWO)
        dataframe['EWO'] = ewo(dataframe, 50, 200)

        return dataframe
########################################################################################################################################################
# ENTRY TREND
########################################################################################################################################################
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        if dataframe.empty:
            return dataframe

        conditions = []
        dataframe['enter_tag'] = ''

        # Entry condition 1: EWO
        is_ewo = (
            (dataframe['rsi_fast'] < self.buy_rsi_fast.value) &
            (dataframe['close'] < dataframe['ema_8'] * self.buy_ema_low.value) &
            (dataframe['EWO'] > self.buy_ewo.value) &
            (dataframe['close'] < dataframe['ema_16'] * self.buy_ema_high.value) &
            (dataframe['rsi'] < self.buy_rsi.value)
        )
        conditions.append(is_ewo)
        dataframe.loc[is_ewo, 'enter_tag'] += 'ewo'

        # Entry condition 2: Buy_1
        buy_1 = (
            (dataframe['rsi_slow'] < dataframe['rsi_slow'].shift(1)) &
            (dataframe['rsi_fast'] < self.buy_rsi_fast_32.value) &
            (dataframe['rsi'] > self.buy_rsi_32.value) &
            (dataframe['close'] < dataframe['sma_15'] * self.buy_sma15_32.value) &
            (dataframe['cti'] < self.buy_cti_32.value)
        )
        conditions.append(buy_1)
        dataframe.loc[buy_1, 'enter_tag'] += 'buy_1'

        # Combine all conditions
        if conditions:
            dataframe.loc[reduce(lambda x, y: x | y, conditions), 'enter_long'] = 1

        return dataframe
########################################################################################################################################################
# CUSTOM STOPLOSS
########################################################################################################################################################
    def custom_stoploss(self, pair: str, trade: Trade, current_time: datetime, current_rate: float, current_profit: float, **kwargs) -> float:
        delay = timedelta(minutes=self.delay_time.value)

        if current_time - delay > trade.open_date_utc and current_profit >= -0.01:
            return -0.003
        if current_time - delay * 2 > trade.open_date_utc and current_profit >= -0.02:
            return -0.006

        return self.stoploss
########################################################################################################################################################
# CUSTOM EXIT
########################################################################################################################################################
    def custom_exit(self, pair: str, trade: Trade, current_time: datetime, current_rate: float, current_profit: float, **kwargs) -> Optional[Union[str, bool]]:
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        current_candle = dataframe.iloc[-1]

        if current_profit > 0:
            if current_candle["fastk"] > self.sell_fastx.value:
                return "sell_fastk"

        # Deadfish exit condition
        if (
            current_profit < self.sell_deadfish_profit.value and
            current_candle['bb_width'] < self.sell_deadfish_bb_width.value and
            current_candle['close'] > current_candle['bb_middleband2'] * self.sell_deadfish_bb_factor.value and
            current_candle['volume_mean_12'] < current_candle['volume_mean_24'] * self.sell_deadfish_volume_factor.value
        ):
            return "sell_stoploss_deadfish"

        return None
########################################################################################################################################################
# EXIT TREND
########################################################################################################################################################
    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe['exit_long'] = 0
        dataframe['exit_tag'] = 'long_out'
        return dataframe