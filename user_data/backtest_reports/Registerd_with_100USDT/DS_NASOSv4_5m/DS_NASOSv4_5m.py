# === Standard Library ===
from functools import reduce
from datetime import datetime, timedelta
import logging
# === Third-Party Libraries ===
import numpy as np
from pandas import DataFrame
import talib.abstract as ta
import freqtrade.vendor.qtpylib.indicators as qtpylib
# === Freqtrade Core ===
from freqtrade.strategy.interface import IStrategy
from freqtrade.persistence import Trade
from freqtrade.strategy import (
    stoploss_from_open,
    merge_informative_pair,
    DecimalParameter,
    IntParameter,
    CategoricalParameter
)

from logging import FATAL
from typing import Dict, List
from technical.util import resample_to_interval, resampled_merge
import technical.indicators as ftt


def EWO(dataframe, ema_length=5, ema2_length=35):
    df = dataframe.copy()
    ema1 = ta.EMA(df, timeperiod=ema_length)
    ema2 = ta.EMA(df, timeperiod=ema2_length)
    emadif = (ema1 - ema2) / df['low'] * 100
    return emadif

class DS_NASOSv4_5m(IStrategy):
########################################################################################################################################################
# Hyperopt
# for live trailing_stop = False and use_custom_stoploss = True
# for backtest trailing_stop = True and use_custom_stoploss = False
########################################################################################################################################################
    buy_params = {
        "base_nb_candles_buy": 8,
        "ewo_high": 2.403,
        "ewo_high_2": -5.585,
        "ewo_low": -14.378,
        "lookback_candles": 3,
        "low_offset": 0.984,
        "low_offset_2": 0.942,
        "profit_threshold": 1.008,
        "rsi_buy": 72
    }
    sell_params = {
        "base_nb_candles_sell": 16,
        "high_offset": 1.084,
        "high_offset_2": 1.401,
        "pHSL": -0.15,
        "pPF_1": 0.016,
        "pPF_2": 0.024,
        "pSL_1": 0.014,
        "pSL_2": 0.022
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
        "0": 10
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
    use_custom_exit = False

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
    base_nb_candles_buy = IntParameter(2, 20, default=buy_params['base_nb_candles_buy'], space='buy', optimize=True)
    base_nb_candles_sell = IntParameter(2, 25, default=sell_params['base_nb_candles_sell'], space='sell', optimize=True)
    low_offset = DecimalParameter(0.9, 0.99, default=buy_params['low_offset'], space='buy', optimize=False)
    low_offset_2 = DecimalParameter(0.9, 0.99, default=buy_params['low_offset_2'], space='buy', optimize=False)
    high_offset = DecimalParameter(0.95, 1.1, default=sell_params['high_offset'], space='sell', optimize=True)
    high_offset_2 = DecimalParameter(0.99, 1.5, default=sell_params['high_offset_2'], space='sell', optimize=True)

    # Protection
    fast_ewo = 50
    slow_ewo = 200

    lookback_candles = IntParameter(1, 24, default=buy_params['lookback_candles'], space='buy', optimize=True)
    profit_threshold = DecimalParameter(1.0, 1.03, default=buy_params['profit_threshold'], space='buy', optimize=True)
    ewo_low = DecimalParameter(-20.0, -8.0, default=buy_params['ewo_low'], space='buy', optimize=False)
    ewo_high = DecimalParameter(2.0, 12.0, default=buy_params['ewo_high'], space='buy', optimize=False)
    ewo_high_2 = DecimalParameter(-6.0, 12.0, default=buy_params['ewo_high_2'], space='buy', optimize=False)
    rsi_buy = IntParameter(50, 100, default=buy_params['rsi_buy'], space='buy', optimize=False)

    # trailing stoploss hyperopt parameters
    # hard stoploss profit
    pHSL = DecimalParameter(-0.200, -0.040, default=-0.15, decimals=3, space='sell', optimize=False, load=True)
    # profit threshold 1, trigger point, SL_1 is used
    pPF_1 = DecimalParameter(0.008, 0.020, default=0.016, decimals=3, space='sell', optimize=False, load=True)
    pSL_1 = DecimalParameter(0.008, 0.020, default=0.014, decimals=3, space='sell', optimize=False, load=True)
    # profit threshold 2, SL_2 is used
    pPF_2 = DecimalParameter(0.040, 0.100, default=0.024, decimals=3, space='sell', optimize=False, load=True)
    pSL_2 = DecimalParameter(0.020, 0.070, default=0.022, decimals=3, space='sell', optimize=False, load=True)
########################################################################################################################################################
# Custom Stoploss
########################################################################################################################################################
    def custom_stoploss(self, pair: str, trade: 'Trade', current_time: datetime, current_rate: float, current_profit: float, **kwargs) -> float:

        # # hard stoploss profit
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
            sl_profit = SL_1 + ((current_profit - PF_1)*(SL_2 - SL_1)/(PF_2 - PF_1))
        else:
            sl_profit = HSL

        # if current_profit < 0.001 and current_time - timedelta(minutes=600) > trade.open_date_utc:
        #     return -0.005

        return stoploss_from_open(sl_profit, current_profit)

########################################################################################################################################################
# Infromative
########################################################################################################################################################
    def informative_pairs(self) -> List[tuple]:
        pairs = self.dp.current_whitelist()
        return [(pair, self.informative) for pair in pairs]
########################################################################################################################################################
# Indicators
########################################################################################################################################################
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        if self.dp:
            inf = self.dp.get_pair_dataframe(pair=metadata['pair'], timeframe=self.informative).copy()

            inf['rsi_1h'] = ta.RSI(inf, timeperiod=14)
            inf['close_1h'] = inf['close']

            lb = int(self.lookback_candles.value)
            inf['close_1h_rollmax'] = inf['close'].rolling(lb, min_periods=lb).max()

            dataframe = merge_informative_pair(dataframe, inf, self.timeframe, self.informative, ffill=True)

        # Local timeframe indicators
        dataframe[f'ma_buy_{self.base_nb_candles_buy.value}'] = ta.EMA(dataframe, timeperiod=self.base_nb_candles_buy.value)
        dataframe[f'ma_sell_{self.base_nb_candles_sell.value}'] = ta.EMA(dataframe, timeperiod=self.base_nb_candles_sell.value)

        dataframe['hma_50'] = qtpylib.hull_moving_average(dataframe['close'], window=50)
        dataframe['ema_100'] = ta.EMA(dataframe, timeperiod=100)
        dataframe['sma_9'] = ta.SMA(dataframe, timeperiod=9)

        dataframe['EWO'] = EWO(dataframe, self.fast_ewo, self.slow_ewo)
        dataframe['rsi'] = ta.RSI(dataframe, timeperiod=14)
        dataframe['rsi_fast'] = ta.RSI(dataframe, timeperiod=4)
        dataframe['rsi_slow'] = ta.RSI(dataframe, timeperiod=20)

        return dataframe
########################################################################################################
# Entry Trade Logic
########################################################################################################
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe['enter_long'] = 0
        dataframe['enter_tag'] = None

        profit_filter = (
            dataframe['close_1h_rollmax_1h'].notna() &
            (dataframe['close_1h_rollmax_1h'] < (dataframe['close'] * self.profit_threshold.value))
        )

        # --- EWO Setup 2: Strongest Signal ---
        ewo2 = (
            (dataframe['rsi_fast'] < 35) &
            (dataframe['close'] < (dataframe[f'ma_buy_{self.base_nb_candles_buy.value}'] * self.low_offset_2.value)) &
            (dataframe['EWO'] > self.ewo_high_2.value) &
            (dataframe['rsi'] < self.rsi_buy.value) &
            (dataframe['rsi'] < 25) &
            (dataframe['volume'] > 0) &
            (dataframe['close'] < (dataframe[f'ma_sell_{self.base_nb_candles_sell.value}'] * self.high_offset.value))
        )
        dataframe.loc[profit_filter & ewo2, ['enter_long', 'enter_tag']] = [1, 'ewo2']

        # --- EWO Setup 1: Moderate Signal ---
        ewo1 = (
            (dataframe['rsi_fast'] < 35) &
            (dataframe['close'] < (dataframe[f'ma_buy_{self.base_nb_candles_buy.value}'] * self.low_offset.value)) &
            (dataframe['EWO'] > self.ewo_high.value) &
            (dataframe['rsi'] < self.rsi_buy.value) &
            (dataframe['volume'] > 0) &
            (dataframe['close'] < (dataframe[f'ma_sell_{self.base_nb_candles_sell.value}'] * self.high_offset.value))
        )
        dataframe.loc[(dataframe['enter_long'] == 0) & profit_filter & ewo1, ['enter_long', 'enter_tag']] = [1, 'ewo1']

        # --- EWO Low Setup: Weak Reversal Signal ---
        ewolow = (
            (dataframe['rsi_fast'] < 35) &
            (dataframe['close'] < (dataframe[f'ma_buy_{self.base_nb_candles_buy.value}'] * self.low_offset.value)) &
            (dataframe['EWO'] < self.ewo_low.value) &
            (dataframe['volume'] > 0) &
            (dataframe['close'] < (dataframe[f'ma_sell_{self.base_nb_candles_sell.value}'] * self.high_offset.value))
        )
        dataframe.loc[(dataframe['enter_long'] == 0) & profit_filter & ewolow, ['enter_long', 'enter_tag']] = [1, 'ewolow']

        return dataframe
########################################################################################################################################################
# Exit Trade
########################################################################################################################################################
    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe['exit_long'] = 0
        dataframe['exit_tag'] = None

        # --- Exit 1: Overbought RSI + SMA confirmation ---
        exit1 = (
            (dataframe['close'] > dataframe['sma_9']) &
            (dataframe['close'] > (dataframe[f'ma_sell_{self.base_nb_candles_sell.value}'] * self.high_offset_2.value)) &
            (dataframe['rsi'] > 50) &
            (dataframe['volume'] > 0) &
            (dataframe['rsi_fast'] > dataframe['rsi_slow'])
        )
        dataframe.loc[exit1, ['exit_long', 'exit_tag']] = [1, 'sma_9']

        # --- Exit 2: Price breaks HMA support, but still above trend MA ---
        exit2 = (
            (dataframe['close'] < dataframe['hma_50']) &
            (dataframe['close'] > (dataframe[f'ma_sell_{self.base_nb_candles_sell.value}'] * self.high_offset.value)) &
            (dataframe['volume'] > 0) &
            (dataframe['rsi_fast'] > dataframe['rsi_slow']) &
            (dataframe['exit_long'] == 0)  # Prevent overwrite
        )
        dataframe.loc[exit2, ['exit_long', 'exit_tag']] = [1, 'hma_50']

        return dataframe
########################################################################################################################################################
# CTE
########################################################################################################################################################
    def confirm_trade_exit(self, pair: str, trade: Trade, order_type: str, amount: float, rate: float, time_in_force: str, sell_reason: str, current_time: datetime, **kwargs) -> bool:

        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        last_candle = dataframe.iloc[-1]

        if (last_candle is not None):
            if (sell_reason in ['sell_signal']):
                if (last_candle['hma_50']*1.149 > last_candle['ema_100']) and (last_candle['close'] < last_candle['ema_100']*0.951):  # *1.2
                    return False

        # slippage
        try:
            state = self.slippage_protection['__pair_retries']
        except KeyError:
            state = self.slippage_protection['__pair_retries'] = {}

        candle = dataframe.iloc[-1].squeeze()

        slippage = (rate / candle['close']) - 1
        if slippage < self.slippage_protection['max_slippage']:
            pair_retries = state.get(pair, 0)
            if pair_retries < self.slippage_protection['retries']:
                state[pair] = pair_retries + 1
                return False

        state[pair] = 0

        return True
########################################################################################################################################################
# Custom to Sell unclog
########################################################################################################################################################
#    def custom_exit(self, pair: str, trade: 'Trade', current_time: 'datetime', current_rate: float, current_profit: float, **kwargs):
#        # Sell any positions at a loss if they are held for more than X days.
#        if current_profit <= 0 and (current_time - trade.open_date_utc).days >= 10:
#            return 'unclog'
#
#        if current_profit >= 0 and (current_time - trade.open_date_utc).days >= 10:
#            return 'unclog'