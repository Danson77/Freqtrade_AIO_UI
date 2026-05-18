from datetime import datetime, timedelta
import talib.abstract as ta
import pandas_ta as pta
from freqtrade.persistence import Trade
from freqtrade.strategy.interface import IStrategy
from pandas import DataFrame
from freqtrade.strategy import DecimalParameter, IntParameter, stoploss_from_open
from functools import reduce
import warnings

warnings.simplefilter(action="ignore", category=RuntimeWarning)

## Bull version, No stoploss, Just do it

class GeneTrader_10(IStrategy):
    minimal_roi = {
        "0": 1
    }
    timeframe = '5m'
    process_only_new_candles = True
    startup_candle_count = 240

    trailing_stop = False
    trailing_stop_positive = 0.002
    trailing_stop_positive_offset = 0.05
    trailing_only_offset_is_reached = True

    use_custom_stoploss = True

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

    # Hyperopt Parameters
    # hard stoploss profit
    pHSL = DecimalParameter(-0.2, -0.04, default=-0.2, space='sell', optimize=True)
    # profit threshold 1, trigger point, SL_1 is used
    pPF_1 = DecimalParameter(0.008, 0.02, default=0.015, space='sell', optimize=True)
    pSL_1 = DecimalParameter(0.008, 0.02, default=0.013, space='sell', optimize=True)
    # profit threshold 2, SL_2 is used
    pPF_2 = DecimalParameter(0.04, 0.1, default=0.04, space='sell', optimize=True)
    pSL_2 = DecimalParameter(0.02, 0.07, default=0.057, space='sell', optimize=True)

    stoploss_opt = DecimalParameter(-0.6, -0.1, default=-0.27, space='sell', optimize=True)
    stoploss = stoploss_opt.value
    pMinProfit = DecimalParameter(-0.3, 0.0, default=-0.288, space='sell', optimize=True)
    pCurrentProfit = DecimalParameter(-0.1, 0.2, default=0.092, space='sell', optimize=True)

    buy_rsi_fast_32 = IntParameter(20.0, 70.0, default=65, space='buy', optimize=True)
    buy_rsi_32 = IntParameter(15.0, 50.0, default=36, space='buy', optimize=True)
    buy_sma15_32 = DecimalParameter(0.9, 1.0, default=0.9, space='buy', optimize=True)
    buy_cti_32 = DecimalParameter(-1.0, 1.0, default=0.78, space='buy', optimize=True)

    sell_fastx = IntParameter(50.0, 100.0, default=89, space='sell', optimize=True)

    sell_loss_cci = IntParameter(0.0, 600.0, default=448, space='sell', optimize=True)
    sell_loss_cci_profit = DecimalParameter(-0.15, 0.0, default=-0.08, space='sell', optimize=True)

    buy_new_rsi_fast = IntParameter(20.0, 70.0, default=57, space='buy', optimize=True)
    buy_new_rsi = IntParameter(15.0, 50.0, default=15, space='buy', optimize=True)
    buy_new_sma15 = DecimalParameter(0.9, 1.0, default=0.965, space='buy', optimize=True)
    
    sell_cci = IntParameter(0.0, 600.0, default=156, space='sell', optimize=True)

    time_sell_4_3 = IntParameter(2.0, 6.0, default=6, space='sell', optimize=True)
    time_sell_10_7 = IntParameter(6.0, 12.0, default=6, space='sell', optimize=True)

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

        return dataframe

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
                (dataframe['rsi_fast'] < self.buy_new_rsi_fast.value) &
                (dataframe['rsi'] > self.buy_new_rsi.value) &
                (dataframe['close'] < dataframe['sma_15'] * self.buy_new_sma15.value) &
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
