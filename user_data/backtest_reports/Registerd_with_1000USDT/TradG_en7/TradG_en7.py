from datetime import datetime, timedelta
import talib.abstract as ta
import pandas_ta as pta
import pandas as pd
from freqtrade.persistence import Trade
from freqtrade.strategy.interface import IStrategy
from pandas import DataFrame
from freqtrade.strategy import DecimalParameter, IntParameter, RealParameter, stoploss_from_open
from functools import reduce
import warnings

warnings.simplefilter(action="ignore", category=RuntimeWarning)

########################################################################################################################################################
class TradG_en7(IStrategy):
########################################################################################################################################################
# Hyperopt
########################################################################################################################################################
    buy_params = {
        "buy_rsi_fast_32": 62,
        "buy_rsi_32": 19,
        "buy_sma15_32": 0.97,
        "buy_cti_32": 0.89,
        "buy_new_rsi_fast": 46,
        "buy_new_rsi": 29,
        "buy_new_sma15": 0.978,
    }
    sell_params = {
        "stoploss": -0.35,
        "pMinProfit": -0.06,
        "pCurrentProfit": 0.041,
        "sell_fastx": 73,
        "sell_loss_cci": 184,
        "sell_loss_cci_profit": -0.01,
        "sell_cci": 154,
        "time_sell_4_3": 6,
        "time_sell_10_7": 6,
        "pHSL": -0.15,
        "pPF_1": 0.016,
        "pPF_2": 0.024,
        "pSL_1": 0.014,
        "pSL_2": 0.022
    }
    minimal_roi = {
        "0": 1
    }
    stoploss = -0.15
    trailing_stop = False
    trailing_stop_positive = 0.002
    trailing_stop_positive_offset = 0.05
    trailing_only_offset_is_reached = True
    use_custom_stoploss = True
########################################################################################################################################################
# Main
########################################################################################################################################################
    timeframe = '5m'  # The primary timeframe for analysis.
    #inf_1h = '1h'  # Informative timeframe to gather additional data.
    process_only_new_candles = True
    startup_candle_count = 240

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
        'force_exit': 'market',
        'stoploss': 'market',
        'stoploss_on_exchange': False,
        'stoploss_on_exchange_interval': 60,
        'stoploss_on_exchange_limit_ratio': 0.99
    }

    # Order Time-In-Force defines how long an order will remain active before it is executed or expired.
    order_time_in_force = {
        'entry': 'gtc',
        'exit': 'ioc'
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
    buy_rsi_fast_32 = IntParameter(20.0, 70.0, default=62, space='buy', optimize=True)
    buy_rsi_32 = IntParameter(15.0, 50.0, default=19, space='buy', optimize=True)
    buy_sma15_32 = DecimalParameter(0.9, 1.0, default=0.97, space='buy', optimize=True)
    buy_cti_32 = DecimalParameter(-1.0, 1.0, default=0.89, space='buy', optimize=True)

    buy_new_rsi_fast = IntParameter(20.0, 70.0, default=46, space='buy', optimize=True)
    buy_new_rsi = IntParameter(15.0, 50.0, default=29, space='buy', optimize=True)
    buy_new_sma15 = DecimalParameter(0.9, 1.0, default=0.978, space='buy', optimize=True)
    
    # Sell
    stoploss_opt = DecimalParameter(-0.6, -0.1, default=-0.35, space='sell', optimize=True)
    stoploss = stoploss_opt.value
    pMinProfit = DecimalParameter(-0.3, 0.0, default=-0.06, space='sell', optimize=True)
    pCurrentProfit = DecimalParameter(-0.1, 0.2, default=0.041, space='sell', optimize=True)

    sell_fastx = IntParameter(50.0, 100.0, default=73, space='sell', optimize=True)

    sell_loss_cci = IntParameter(0.0, 600.0, default=184, space='sell', optimize=True)
    sell_loss_cci_profit = DecimalParameter(-0.15, 0.0, default=-0.01, space='sell', optimize=True)

    sell_cci = IntParameter(0.0, 600.0, default=154, space='sell', optimize=True)

    time_sell_4_3 = IntParameter(2.0, 6.0, default=6, space='sell', optimize=True)
    time_sell_10_7 = IntParameter(6.0, 12.0, default=6, space='sell', optimize=True)

    # hard stoploss profit
    pHSL = DecimalParameter(-0.2, -0.04, default=-0.143, space='sell', optimize=True)
    # profit threshold 1, trigger point, SL_1 is used
    pPF_1 = DecimalParameter(0.008, 0.02, default=0.011, space='sell', optimize=True)
    pSL_1 = DecimalParameter(0.008, 0.02, default=0.012, space='sell', optimize=True)
    # profit threshold 2, SL_2 is used
    pPF_2 = DecimalParameter(0.04, 0.1, default=0.047, space='sell', optimize=True)
    pSL_2 = DecimalParameter(0.02, 0.07, default=0.043, space='sell', optimize=True)
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

        # profit sell indicators
        stoch_fast = ta.STOCHF(dataframe, 5, 3, 0, 3, 0)
        dataframe['fastk'] = stoch_fast['fastk']

        dataframe['cci'] = ta.CCI(dataframe, timeperiod=20)

        dataframe['ma120'] = ta.MA(dataframe, timeperiod=120)
        dataframe['ma240'] = ta.MA(dataframe, timeperiod=240)

        # Calculate auxiliary fields
        dataframe['current_time'] = pd.to_datetime(dataframe.index)  # Ensure datetime index
        dataframe['trade_open_time'] = dataframe['current_time'] - pd.Timedelta(hours=1)  # Example placeholder logic
        dataframe['trade_open_price'] = dataframe['close'].shift(1)  # Simulate entry price
        dataframe['current_profit'] = (dataframe['close'] - dataframe['trade_open_price']) / dataframe['trade_open_price']
        # Calculate additional conditions for exits
        dataframe['min_profit'] = dataframe['close'] / dataframe['open'] - 1  # Assuming min_rate = open for demonstration

        return dataframe
########################################################################################################################################################
# Entry Trend
########################################################################################################################################################
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        conditions = []
        dataframe.loc[:, 'enter_tag'] = ''
        rsi_32 = (
                (dataframe['rsi_slow'] < dataframe['rsi_slow'].shift(1)) &
                (dataframe['rsi_fast'] < self.buy_rsi_fast_32.value) &
                (dataframe['rsi'] > self.buy_rsi_32.value) &
                (dataframe['close'] < dataframe['sma_15'] * self.buy_sma15_32.value) &
                (dataframe['cti'] < self.buy_cti_32.value)
        )

        rsi_ = (
                (dataframe['rsi_slow'] < dataframe['rsi_slow'].shift(1)) &
                (dataframe['rsi_fast'] < self.buy_new_rsi_fast.value) &
                (dataframe['rsi'] > self.buy_new_rsi.value) &
                (dataframe['close'] < dataframe['sma_15'] * self.buy_new_sma15.value) &
                (dataframe['cti'] < self.buy_cti_32.value)
        )

        conditions.append(rsi_32)
        dataframe.loc[rsi_32, 'enter_tag'] += 'rsi_32'

        conditions.append(rsi_)
        dataframe.loc[rsi_, 'enter_tag'] += 'rsi_'

        if conditions:
            dataframe.loc[
                reduce(lambda x, y: x | y, conditions),
                'enter_long'] = 1
        return dataframe
########################################################################################################################################################
# Custom Stoploss
########################################################################################################################################################
    def custom_stoploss(self, pair: str, trade: 'Trade', current_time: datetime, current_rate: float, current_profit: float, **kwargs) -> float:

        # hard stoploss profit
        HSL = self.pHSL.value
        PF_1 = self.pPF_1.value
        SL_1 = self.pSL_1.value
        PF_2 = self.pPF_2.value
        SL_2 = self.pSL_2.value

        # For profits between PF_1 and PF_2 the stoploss (sl_profit) used is linearly interpolated 
        # between the values of SL_1 and SL_2. For all profits above PL_2 the sl_profit value
        # rises linearly with current profit, for profits below PF_1 the hard stoploss profit is used.

        if (current_profit > PF_2):
            sl_profit = SL_2 + (current_profit - PF_2)
        elif (current_profit > PF_1):
            sl_profit = SL_1 + ((current_profit - PF_1) * (SL_2 - SL_1) / (PF_2 - PF_1))
        else:
            sl_profit = HSL

        # Only for hyperopt invalid return
        if (sl_profit >= current_profit):
            return -0.99

        return stoploss_from_open(sl_profit, current_profit)
########################################################################################################################################################
# Exit Trend
########################################################################################################################################################
    def custom_exit(self, pair: str, trade: 'Trade', current_time: 'datetime', current_rate: float, current_profit: float, **kwargs):
        dataframe, _ = self.dp.get_analyzed_dataframe(pair=pair, timeframe=self.timeframe)
        current_candle = dataframe.iloc[-1].squeeze()
        
        min_profit = trade.calc_profit_ratio(trade.min_rate)
        current_profit_threshold = self.pCurrentProfit.value

        if current_profit > 0:
            if current_candle["fastk"] > self.sell_fastx.value:
                return "fastk_profit_sell"
        
        if min_profit <= self.pMinProfit.value:  # 使用 pMinProfit 超参数
            if current_profit > self.sell_loss_cci_profit.value:
                if current_candle["cci"] > self.sell_loss_cci.value:
                    return "cci_loss_sell"
                    
        if current_profit >= current_profit_threshold:  # 使用 pCurrentProfit 超参数
            if current_candle["cci"] > self.sell_cci.value:
                return "cci_loss_sell_fast"
        
        if current_time - timedelta(hours=self.time_sell_4_3.value) > trade.open_date_utc:
            if current_profit > -0.03:
                return "time_loss_sell_4_3"
        
        if current_time - timedelta(hours=self.time_sell_10_7.value) > trade.open_date_utc:
            if current_profit > -0.07:
                return "time_loss_sell_10_7"

        return None

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[:, ['exit_long', 'exit_tag']] = (0, 'long_out')
        return dataframe