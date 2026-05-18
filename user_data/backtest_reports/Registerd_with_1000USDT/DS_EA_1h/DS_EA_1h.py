from datetime import datetime, timedelta
import talib.abstract as ta
import pandas_ta as pta
from freqtrade.persistence import Trade
from freqtrade.strategy.interface import IStrategy
from pandas import DataFrame
from freqtrade.strategy import DecimalParameter, IntParameter
from functools import reduce
import warnings
import pandas as pd

warnings.simplefilter(action="ignore", category=RuntimeWarning)
########################################################################################################################################################
class DS_EA_1h(IStrategy):
########################################################################################################################################################
# Hyperopt
########################################################################################################################################################
    buy_params = {
        "buy_rsi_fast_32": 45,
        "buy_rsi_32": 35,
        "buy_sma15_32": 0.961,
        "buy_cti_32": -0.58,
    }
    sell_params = {
        "sell_loss_cci": 148,
        'sell_loss_cci_profit': -0.04,
        "sell_cci": 90,
    }
    minimal_roi = {
        "0": 1
    }
    stoploss = -0.99#-0.25
    trailing_stop = True
    trailing_stop_positive = 0.001           # Offest from profit for trailing stop.
    trailing_stop_positive_offset = 0.012    # Profit necessary to have trailing_stop_positive apply.
    trailing_only_offset_is_reached = False  # Keep stoploss static UNTIL the offset is reached then trigger trailing stop.
    use_custom_stoploss = False
    use_custom_sell = False
########################################################################################################################################################
# Main
########################################################################################################################################################
    timeframe = '1h'  # The primary timeframe for analysis.
    process_only_new_candles = True
    startup_candle_count = 120

    # Sell signal configuration.
    use_exit_signal = True
    exit_profit_only = False
    exit_profit_offset = 0.01  # Offset added to exit signal (profitable threshold).
    ignore_roi_if_entry_signal = False  # If True, ignore ROI when the buy signal is still present.

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
    is_optimize_32 = True
    buy_rsi_fast_32 = IntParameter(20, 70, default=45, space='buy', optimize=is_optimize_32)
    buy_rsi_32 = IntParameter(15, 50, default=35, space='buy', optimize=is_optimize_32)
    buy_sma15_32 = DecimalParameter(0.900, 1, default=0.961, decimals=3, space='buy', optimize=is_optimize_32)
    buy_cti_32 = DecimalParameter(-1, 0, default=-0.58, decimals=2, space='buy', optimize=is_optimize_32)
    # Sell
    sell_fastx = IntParameter(50, 100, default=70, space='sell', optimize=True)
    sell_loss_cci = IntParameter(low=0, high=600, default=148, space='sell', optimize=False)
    sell_loss_cci_profit = DecimalParameter(-0.15, 0, default=-0.04, decimals=2, space='sell', optimize=False)
    sell_cci = IntParameter(low=0, high=200, default=90, space='sell', optimize=False)
########################################################################################################################################################
# Indicators
########################################################################################################################################################
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe['sma_15'] = ta.SMA(dataframe, timeperiod=15)
        dataframe['cti'] = pta.cti(dataframe["close"], length=20)
        dataframe['rsi'] = ta.RSI(dataframe, timeperiod=14)
        dataframe['rsi_fast'] = ta.RSI(dataframe, timeperiod=4)
        dataframe['rsi_slow'] = ta.RSI(dataframe, timeperiod=20)
        stoch_fast = ta.STOCHF(dataframe, 5, 3, 0, 3, 0)
        dataframe['fastk'] = stoch_fast['fastk']
        dataframe['cci'] = ta.CCI(dataframe, timeperiod=20)
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
        conditions.append(buy_1)
        dataframe.loc[buy_1, 'enter_tag'] += 'buy_1'
        
        if conditions:
            dataframe.loc[reduce(lambda x, y: x | y, conditions), 'enter_long'] = 1

        return dataframe
########################################################################################################################################################
# Exit Trade
########################################################################################################################################################
    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Ensure the index is in datetime format
        if not isinstance(dataframe.index, pd.DatetimeIndex):
            dataframe.index = pd.to_datetime(dataframe.index)

        dataframe.loc[:, "exit_long"] = 0  # Default: No exit signal
        dataframe.loc[:, "exit_tag"] = None  # Default: No exit tag

        for index, row in dataframe.iterrows():
            # Use the index (datetime) for current_time
            current_time = index

            # Get trade_open_time from metadata or use a fallback
            trade_open_time = metadata.get("trade_open_date_utc")
            if not trade_open_time:
                trade_open_time = current_time - timedelta(hours=3)  # Fallback to a default value

            # Fast profit sell within 10 minutes
            if current_time - timedelta(minutes=10) < trade_open_time and row.get("current_profit", 0) >= 0.05:
                dataframe.loc[index, "exit_long"] = 1
                dataframe.loc[index, "exit_tag"] = "profit_sell_fast"

            # Profit-based exits
            if row.get("current_profit", 0) > 0:
                if row["fastk"] > self.sell_fastx.value:
                    dataframe.loc[index, "exit_long"] = 1
                    dataframe.loc[index, "exit_tag"] = "fastk_profit_sell"

                if row["cci"] > self.sell_cci.value:
                    dataframe.loc[index, "exit_long"] = 1
                    dataframe.loc[index, "exit_tag"] = "cci_profit_sell"

            # Profit sell after 2 hours
            if current_time - timedelta(hours=2) > trade_open_time and row.get("current_profit", 0) > 0:
                dataframe.loc[index, "exit_long"] = 1
                dataframe.loc[index, "exit_tag"] = "profit_sell_in_2h"

            # Sell when high >= open_rate and cci condition is met
            if row["high"] >= row.get("open_rate", 0) and row["cci"] > self.sell_cci.value:
                dataframe.loc[index, "exit_long"] = 1
                dataframe.loc[index, "exit_tag"] = "cci_sell"

            # Loss-based cci sell
            if row.get("current_profit", 0) > self.sell_loss_cci_profit.value and row["cci"] > self.sell_loss_cci.value:
                dataframe.loc[index, "exit_long"] = 1
                dataframe.loc[index, "exit_tag"] = "cci_loss_sell"

        return dataframe
