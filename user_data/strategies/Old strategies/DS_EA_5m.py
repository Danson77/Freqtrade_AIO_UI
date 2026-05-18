from datetime import datetime, timedelta
import talib.abstract as ta
import pandas_ta as pta
import numpy as np
from freqtrade.persistence import Trade
from freqtrade.strategy.interface import IStrategy
from pandas import DataFrame
from freqtrade.strategy import DecimalParameter, IntParameter
from functools import reduce
########################################################################################################################################################
TMP_HOLD = []
TMP_HOLD1 = []
########################################################################################################################################################
class DS_EA_5m(IStrategy):
########################################################################################################################################################
# Hyperopt
########################################################################################################################################################
    buy_params = {
        # Main
        "buy_rsi_fast_32": 45,
        "buy_rsi_32": 35,
        "buy_sma15_32": 0.961,
        "buy_cti_32": -0.58,
    }
    sell_params = {
        "sell_fastx": 75,
    }
    minimal_roi = {
        "0": 10
    }
    stoploss = -0.18
    trailing_stop = True
    trailing_stop_positive = 0.001           # Offest from profit for trailing stop.
    trailing_stop_positive_offset = 0.012    # Profit necessary to have trailing_stop_positive apply.
    trailing_only_offset_is_reached = False  # Keep stoploss static UNTIL the offset is reached then trigger trailing stop.
########################################################################################################################################################
# Main
########################################################################################################################################################
    use_custom_stoploss = False
    timeframe = '5m'  # The primary timeframe for analysis.
    # Sell signal configuration.
    use_exit_signal = True
    exit_profit_only = False
    exit_profit_offset = 0.01  # Offset added to exit signal (profitable threshold).
    ignore_roi_if_entry_signal = False  # If True, ignore ROI when the buy signal is still present.
    # Number of past candles to consider upon startup.
    process_only_new_candles = True
    startup_candle_count = 120
    # Configuration of order types.
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
    # Plotting configuration for visualizing indicators in backtesting.
    plot_config = {
        'main_plot': {
            'ma_buy': {'color': 'orange'},  # Color for the buy moving average.
            'ma_sell': {'color': 'orange'},  # Color for the sell moving average.
        },
    }
    # Order Time-In-Force defines how long an order will remain active before it is executed or expired.
    order_time_in_force = {
        'entry': 'gtc',
        'exit': 'gtc'
    }
########################################################################################################################################################
# Parameters
########################################################################################################################################################
    # Buy
    is_optimize_32 = True
    buy_rsi_fast_32 = IntParameter(20, 70, default=45, space='buy', optimize=is_optimize_32)
    buy_rsi_32 = IntParameter(15, 50, default=35, space='buy', optimize=is_optimize_32)
    buy_sma15_32 = DecimalParameter(0.900, 1, default=0.961, decimals=3, space='buy', optimize=is_optimize_32)
    buy_cti_32 = DecimalParameter(-1, 0, default=-0.58, decimals=2, space='buy', optimize=is_optimize_32)
    # Sell
    is_optimize_sell = True
    sell_fastx = IntParameter(50, 100, default=75, space='sell', optimize=is_optimize_sell)

    cci_opt = True
    sell_loss_cci = IntParameter(low=0, high=600, default=80, space='sell', optimize=cci_opt)
    sell_loss_cci_profit = DecimalParameter(-0.15, 0, default=-0.15, decimals=2, space='sell', optimize=cci_opt)
########################################################################################################################################################
# Indicators
########################################################################################################################################################
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # buy_1 indicators
        dataframe['sma_15'] = ta.SMA(dataframe, timeperiod=15)
        dataframe['cti'] = pta.cti(dataframe["close"], length=20)
        dataframe['cci'] = ta.CCI(dataframe, timeperiod=20)

        dataframe['rsi'] = ta.RSI(dataframe, timeperiod=14)
        dataframe['rsi_fast'] = ta.RSI(dataframe, timeperiod=4)
        dataframe['rsi_slow'] = ta.RSI(dataframe, timeperiod=20)
        
        # profit sell indicators
        stoch_fast = ta.STOCHF(dataframe, 5, 3, 0, 3, 0)
        dataframe['fastk'] = stoch_fast['fastk']

        dataframe['ma120'] = ta.MA(dataframe, timeperiod=120)
        dataframe['ma240'] = ta.MA(dataframe, timeperiod=240)

        return dataframe
########################################################################################################################################################
# Entry Trend
########################################################################################################################################################
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        conditions = []
        dataframe.loc[:, 'enter_tag'] = ''
        buy_1 = (
                (dataframe['rsi_slow'] < dataframe['rsi_slow'].shift(1)) &
                (dataframe['rsi_fast'] < self.buy_rsi_fast_32.value) &
                (dataframe['rsi'] > self.buy_rsi_32.value) &
                (dataframe['close'] < dataframe['sma_15'] * self.buy_sma15_32.value) &
                (dataframe['cti'] < self.buy_cti_32.value)
        )
        
        buy_new = (
                (dataframe['rsi_slow'] < dataframe['rsi_slow'].shift(1)) &
                (dataframe['rsi_fast'] < 34) &
                (dataframe['rsi'] > 28) &
                (dataframe['close'] < dataframe['sma_15'] * 0.96) &
                (dataframe['cti'] < self.buy_cti_32.value)
        )
        
        conditions.append(buy_1)
        dataframe.loc[buy_1, 'enter_tag'] += 'buy_1'

        conditions.append(buy_new)
        dataframe.loc[buy_new, 'enter_tag'] += 'buy_new'

        if conditions:
            dataframe.loc[
                reduce(lambda x, y: x | y, conditions),
                'enter_long'] = 1
        return dataframe
########################################################################################################################################################
# Exit Trade
########################################################################################################################################################
    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        Populate exit trend signals for standard exit strategy in Freqtrade.
        This method generates 'exit_long' signals based on MA, momentum, and custom trade state conditions.
        """
        # Ensure required columns exist
        required_columns = ["close", "ma120", "ma240", "fastk", "cci", "high"]
        for col in required_columns:
            if col not in dataframe.columns:
                raise ValueError(f"Column '{col}' is missing in the dataframe. Please include it.")
    
        # Track trades and conditions similar to custom_exit logic
        dataframe['tmp_hold'] = np.where(
            (dataframe['close'] > dataframe['ma120']) | (dataframe['close'] > dataframe['ma240']),
            1, 0
        )
        dataframe['tmp_hold1'] = np.where(
            ~((dataframe['close'] > dataframe['ma120']) | (dataframe['close'] > dataframe['ma240'])),
            1, 0
        )
    
        # Example Exit Conditions
        # 1. Trend exit: Close price below moving averages
        dataframe['trend_exit'] = np.where(
            (dataframe['close'] < dataframe['ma120']) & 
            (dataframe['close'] < dataframe['ma240']),
            1, 0
        )
    
        # 2. Profit-taking exit: Overbought Fast Stochastic
        dataframe['fastk_profit_sell'] = np.where(
            (dataframe['fastk'] > self.sell_fastx.value),
            1, 0
        )
    
        # 3. Loss threshold exit: CCI conditions
        dataframe['cci_loss_sell'] = np.where(
            (dataframe['cci'] > self.sell_loss_cci.value),
            1, 0
        )
    
        # 4. TMP_HOLD condition: Exit when prices drop below MAs with certain loss
        dataframe['ma120_sell'] = np.where(
            (dataframe['tmp_hold'] == 1) & 
            (dataframe['close'] < dataframe['ma120']) & 
            (dataframe['close'] < dataframe['ma240']),
            1, 0
        )
    
        # 5. TMP_HOLD1 condition: Exit when prices cross above MAs
        dataframe['cross_120_or_240_sell'] = np.where(
            (dataframe['tmp_hold1'] == 1) & 
            ((dataframe['high'] > dataframe['ma120']) | (dataframe['high'] > dataframe['ma240'])),
            1, 0
        )
    
        # Combine all exit signals into 'exit_long' column
        dataframe['exit_long'] = np.where(
            (dataframe['trend_exit'] == 1) |
            (dataframe['fastk_profit_sell'] == 1) |
            (dataframe['cci_loss_sell'] == 1) |
            (dataframe['ma120_sell'] == 1) |
            (dataframe['cross_120_or_240_sell'] == 1),
            1, 0
        )
    
        # Add detailed exit tagging for debugging/insights
        dataframe['exit_tag'] = np.select(
            [
                (dataframe['trend_exit'] == 1),
                (dataframe['fastk_profit_sell'] == 1),
                (dataframe['cci_loss_sell'] == 1),
                (dataframe['ma120_sell'] == 1),
                (dataframe['cross_120_or_240_sell'] == 1),
            ],
            [
                'trend_exit',
                'fastk_profit_sell',
                'cci_loss_sell',
                'ma120_sell',
                'cross_120_or_240_sell',
            ],
            default='none'
        )
    
        return dataframe