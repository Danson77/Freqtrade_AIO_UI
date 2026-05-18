# --- Do not remove these libs ---
from freqtrade.strategy.interface import IStrategy
from functools import reduce
from pandas import DataFrame
# --------------------------------
import talib.abstract as ta
import freqtrade.vendor.qtpylib.indicators as qtpylib

from freqtrade.strategy import DecimalParameter, IntParameter

from freqtrade.persistence import Trade
from datetime import datetime, timedelta#

########################################################################################################################################################
# ewo
########################################################################################################################################################
def EWO(dataframe, ema_length=5, ema2_length=35):
    df = dataframe.copy()
    ema1 = ta.EMA(df, timeperiod=ema_length)
    ema2 = ta.EMA(df, timeperiod=ema2_length)
    emadif = (ema1 - ema2) / df['close'] * 100
    return emadif

########################################################################################################################################################
class ElliotV8HO(IStrategy):
########################################################################################################################################################
# Hyperopt
########################################################################################################################################################
    # Sell hyperspace params: v1
    # sell_params = {
    #     "base_nb_candles_sell": 24,
    #     "high_offset": 0.991,
    #     "high_offset_2": 0.997
    # }

    # Sell hyperspace params: v5
    # sell_params = {
    #     "base_nb_candles_sell": 30,
    #     "high_offset": 0.973,
    #     "high_offset_2": 1.121,
    # }
    buy_params = {
        "base_nb_candles_buy": 19,
        "ewo_high": 5.417,
        "ewo_low": -17.251,
        "low_offset": 0.983,
        "rsi_buy": 61,
    }
    sell_params = {
        "base_nb_candles_sell": 24,
        "high_offset": 1.011,
        "high_offset_2": 0.997,
    }
    slippage_protection = {
        'retries': 3,
        'max_slippage': -0.02
    }
########################################################################################################################################################
# Main
########################################################################################################################################################
    can_short = False

    minimal_roi = {
        "0": 0.09,
    }
    ignore_roi_if_entry_signal = False

    stoploss = -0.25
    use_custom_stoploss = False

    trailing_stop = True
    trailing_stop_positive = 0.001
    trailing_stop_positive_offset = 0.01
    trailing_only_offset_is_reached = True

    use_entry_signal = True
    use_custom_entry = False

    use_exit_signal = True
    use_custom_exit = True

    exit_profit_only = False
    exit_profit_offset = 0.03
########################################################################################################################################################
# Main
########################################################################################################################################################
    timeframe = '5m'
    informative = '1h'
    process_only_new_candles = False
    startup_candle_count = 200

    order_types = {
        'entry': 'market',
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
        'exit': 'gtc'
    }
    plot_config = {
        'main_plot': {
            'ma_buy': {'color': 'orange'},  # Color for the buy moving average.
            'ma_sell': {'color': 'orange'},  # Color for the sell moving average.
        },
    }
########################################################################################################################################################
# Trade Protections
########################################################################################################################################################
    @property
    def protections(self):
        return [
            # Cooldown any signal for 5 candles (25 m) after a trade
            { "method": "CooldownPeriod", "stop_duration_candles": 5 },

            # Allow up to 3% drawdown over the last 9 h before pausing
            {
                "method": "MaxDrawdown",
                "lookback_period_candles": 72,     # 6 h → 9 h
                "trade_limit": 20,
                "stop_duration_candles": 6,        # longer pause
                "max_allowed_drawdown": 0.03       # 3% drawdown allowed
            },

            # Only guard if you’ve lost >3% over a rolling 4 h period
            {
                "method": "StoplossGuard",
                "lookback_period_candles": 48,     # 4 h
                "trade_limit": 4,
                "stop_duration_candles": 4,
                "only_per_pair": False
            },

            # Prevent pairs that only net <2% profit over 2 h, block for 1 h
            {
                "method": "LowProfitPairs",
                "lookback_period_candles": 24,     # 2 h
                "trade_limit": 2,
                "stop_duration_candles": 12,       # 1 h
                "required_profit": 0.02            # 2%
            },

            # Prevent pairs that only net <4% profit over 12 h, block for 2 h
            {
                "method": "LowProfitPairs",
                "lookback_period_candles": 144,    # 12 h
                "trade_limit": 4,
                "stop_duration_candles": 24,       # 2 h
                "required_profit": 0.04            # 4%
            }
        ]
########################################################################################################################################################
########################################################################################################################################################
# Parameters
########################################################################################################################################################
    # SMAOffset
    base_nb_candles_buy = IntParameter(15, 60, default=buy_params['base_nb_candles_buy'], space='buy', optimize=True)
    base_nb_candles_sell = IntParameter(15, 60, default=sell_params['base_nb_candles_sell'], space='sell', optimize=True)
    low_offset = DecimalParameter(0.9, 0.99, default=buy_params['low_offset'], space='buy', optimize=True)
    high_offset = DecimalParameter(0.9, 1.1, default=sell_params['high_offset'], space='sell', optimize=True)
    high_offset_2 = DecimalParameter(0.99, 1.2, default=sell_params['high_offset_2'], space='sell', optimize=True)

    # Protection
    fast_ewo = 50
    slow_ewo = 200
    ewo_low = DecimalParameter(-20.0, -15.0, default=buy_params['ewo_low'], space='buy', optimize=True)
    ewo_high = DecimalParameter(1.0, 8.0, default=buy_params['ewo_high'], space='buy', optimize=True)
    rsi_buy = IntParameter(25, 75, default=buy_params['rsi_buy'], space='buy', optimize=True)
########################################################################################################################################################
# Informative
########################################################################################################################################################
    def informative_pairs(self):

        pairs = self.dp.current_whitelist()
        informative_pairs = [(pair, self.informative)
            for pair in pairs]

        return informative_pairs
########################################################################################################################################################
    def get_informative_indicators(self, metadata: dict):

        dataframe = self.dp.get_pair_dataframe(
            pair=metadata['pair'], timeframe=self.informative)

        return dataframe
########################################################################################################################################################
# Indicators
########################################################################################################################################################
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:

        if self.config['runmode'].value == 'hyperopt':
            # Calculate all ma_buy values
            for val in self.base_nb_candles_buy.range:
                dataframe[f'ma_buy_{val}'] = ta.EMA(dataframe, timeperiod=val)

            # Calculate all ma_sell values
            for val in self.base_nb_candles_sell.range:
                dataframe[f'ma_sell_{val}'] = ta.EMA(dataframe, timeperiod=val)

        else:
            dataframe[f'ma_buy_{self.base_nb_candles_buy.value}'] = ta.EMA(
                dataframe, timeperiod=self.base_nb_candles_buy.value)

            dataframe[f'ma_sell_{self.base_nb_candles_sell.value}'] = ta.EMA(
                dataframe, timeperiod=self.base_nb_candles_sell.value)

        dataframe['hma_50'] = qtpylib.hull_moving_average(
            dataframe['close'], window=50)

        dataframe['sma_9'] = ta.SMA(dataframe, timeperiod=9)
        # Elliot
        dataframe['EWO'] = EWO(dataframe, self.fast_ewo, self.slow_ewo)

        # RSI
        dataframe['rsi'] = ta.RSI(dataframe, timeperiod=14)
        dataframe['rsi_fast'] = ta.RSI(dataframe, timeperiod=4)
        dataframe['rsi_slow'] = ta.RSI(dataframe, timeperiod=20)

        return dataframe
########################################################################################################################################################
# Entry Trend
########################################################################################################################################################
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe['enter_long'] = 0
        dataframe['enter_tag'] = None

        # Condition 1: EWO above high
        condition_ewo_high = (
            (dataframe['rsi_fast'] < 35) &
            (dataframe['close'] < (dataframe[f'ma_buy_{self.base_nb_candles_buy.value}'] * self.low_offset.value)) &
            (dataframe['EWO'] > self.ewo_high.value) &
            (dataframe['rsi'] < self.rsi_buy.value) &
            (dataframe['volume'] > 0) &
            (dataframe['close'] < (dataframe[f'ma_sell_{self.base_nb_candles_sell.value}'] * self.high_offset.value))
        )

        dataframe.loc[condition_ewo_high, ['enter_long', 'enter_tag']] = [1, 'ewo_high']

        # Condition 2: EWO below low
        condition_ewo_low = (
            (dataframe['rsi_fast'] < 35) &
            (dataframe['close'] < (dataframe[f'ma_buy_{self.base_nb_candles_buy.value}'] * self.low_offset.value)) &
            (dataframe['EWO'] < self.ewo_low.value) &
            (dataframe['volume'] > 0) &
            (dataframe['close'] < (dataframe[f'ma_sell_{self.base_nb_candles_sell.value}'] * self.high_offset.value))
        )

        dataframe.loc[condition_ewo_low, ['enter_long', 'enter_tag']] = [1, 'ewo_low']

        return dataframe
########################################################################################################################################################
# Exit Trend
########################################################################################################################################################
    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        conditions = []

        conditions.append(
            (
                (dataframe['close'] > dataframe['hma_50']) &
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
            dataframe.loc[
                reduce(lambda x, y: x | y, conditions),
                ['exit_long', 'exit_tag']
            ] = [1, 'hma_15']

        return dataframe
########################################################################################################################################################
# Custom to Sell unclog
########################################################################################################################################################
    def custom_exit(self, pair: str, trade: 'Trade', current_time: 'datetime', current_rate: float, current_profit: float, **kwargs):
        # Sell any positions at a loss if they are held for more than X days.
        if current_profit <= 0 and (current_time - trade.open_date_utc).days >= 10:
            return 'unclog'

        if current_profit >= 0 and (current_time - trade.open_date_utc).days >= 10:
            return 'unclog'