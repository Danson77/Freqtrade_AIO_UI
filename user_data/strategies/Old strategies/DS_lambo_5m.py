from datetime import datetime, timedelta, timezone
from freqtrade.persistence import Trade, PairLocks
from freqtrade.strategy import (BooleanParameter, DecimalParameter, IntParameter, RealParameter, stoploss_from_open, merge_informative_pair, CategoricalParameter)
from freqtrade.strategy.interface import IStrategy
from functools import reduce
from logging import FATAL
from pandas import DataFrame, Series
from skopt.space import Dimension, Integer
from technical.util import resample_to_interval, resampled_merge
from typing import Dict, List, Optional, Union
import freqtrade.vendor.qtpylib.indicators as qtpylib
import logging
import math
import numpy as np
import pandas as pd
import pandas_ta as pta
import talib.abstract as ta

logger = logging.getLogger(__name__)

############################################################################
# Custom indicators and helper functions
############################################################################
def bollinger_bands(stock_price, window_size, num_of_std):
    rolling_mean = stock_price.rolling(window=window_size).mean()
    rolling_std = stock_price.rolling(window=window_size).std()
    lower_band = rolling_mean - (rolling_std * num_of_std)
    return np.nan_to_num(rolling_mean), np.nan_to_num(lower_band)
    
def ha_typical_price(bars):
    res = (bars['ha_high'] + bars['ha_low'] + bars['ha_close']) / 3.
    return Series(index=bars.index, data=res)
    
########################################################################################################################################################
class DS_lambo_5m(IStrategy):
########################################################################################################################################################
# Main
########################################################################################################################################################
    timeframe = '5m'  # The primary timeframe for analysis.
    inf_1h = '1h'  # Informative timeframe to gather additional data.
    
    # Sell signal configuration.
    use_exit_signal = True  # Whether to use the strategy's exit signal.
    # Custom stoploss configuration.
    use_custom_stoploss = False  # Whether to use a custom stoploss function.

    exit_profit_only = True  # If True, only sell when in profit.
    exit_profit_offset = 0.01  # Offset added to exit signal (profitable threshold).
    ignore_roi_if_entry_signal = False  # If True, ignore ROI when the buy signal is still present.

    # Trailing stop configuration.
    trailing_stop = False  # Whether to use a trailing stop.
    trailing_stop_positive = 0.001  # Positive offset for trailing stop.
    trailing_stop_positive_offset = 0.016  # Offset for triggering the trailing stop.
    trailing_only_offset_is_reached = False  # Only trigger trailing stop if the offset is reached.

    # Whether to process only new candles.
    process_only_new_candles = True
    
    # Number of past candles to consider upon startup.
    startup_candle_count = 100
    
    # Define the initial settings for the strategy.
    initial_safety_order_trigger = -0.018  # Initial trigger for the first safety order.
    max_safety_orders = 8  # Maximum number of safety orders to prevent overexposure.
    safety_order_step_scale = 1.2  # How much to increase the trigger for each additional safety order.
    safety_order_volume_scale = 1.4  # How much to increase the volume of each safety order.
    
    # Configuration of order types.
    order_types = {
        'buy': 'market',
        'sell': 'market',
        'emergencysell': 'market',
        'forcebuy': 'market',
        'forcesell': 'market',
        'stoploss': 'market',
        'stoploss_on_exchange': False,
        'stoploss_on_exchange_interval': 60,
        'stoploss_on_exchange_limit_ratio': 0.99
    }
    
    # Slippage protection to avoid selling at a too low price.
    slippage_protection = {
        'retries': 3,  # Number of retries to avoid slippage.
        'max_slippage': -0.02  # Maximum allowed slippage.
    }
    
    # Plotting configuration for visualizing indicators in backtesting.
    plot_config = {
        'main_plot': {
            'ma_buy': {'color': 'green'},  # Color for the buy moving average.
            'ma_sell': {'color': 'orange'},  # Color for the sell moving average.
        },
    }
    
    # Order Time-In-Force defines how long an order will remain active before it is executed or expired.
    order_time_in_force = {
        'buy': 'gtc',  # Good-Til-Cancelled for buy orders.
        'sell': 'ioc'  # Immediate-Or-Cancel for sell orders.
    }
    
########################################################################################################################################################
# Hyperopt
########################################################################################################################################################
    buy_params = {
        "lambo_2_enabled": True,        # (*DD* 22.93%) Cum Profit %  589.00  - Warning!! High drawdown!!!
        
########################################################################################################################################################
        # Calculate moving averages for buying and selling.
        "base_nb_candles_buy": 8,          # Base number of candles to analyze for buy signals
        
########################################################################################################################################################        
        # Anti Pump
        "antipump_threshold": 0.133,       # Threshold to protect against buying in pump and dump scenarios
        
########################################################################################################################################################        
        #Lambo2
        "lambo2_ema_14_factor": 0.981,
        "lambo2_rsi_14_limit": 39,
        "lambo2_rsi_4_limit": 44,
    }
    
    # Sell hyperspace params: Define parameters related to selling strategies
    sell_params = {
        # Calculate moving average sell values using EMA and other types of moving averages for trend analysis and to determine overbought conditions.
        "base_nb_candles_sell": 22,  # Number of candles to analyze for sell signals, a higher number gives a longer-term view
                
        "high_offset_2": 1.01,
        "high_offset": 1.014,
        
        # Sell signal params
        "sell_fisher": 0.39075,
        "sell_bbmiddle_close": 0.99754,
        
        # Custom Stoploos
        "pHSL": -0.35,
        "pPF_1": 0.011,
        "pPF_2": 0.064,
        "pSL_1": 0.011,
        "pSL_2": 0.062,
    }
    
    # ROI table: Defines the desired profit targets at different time intervals
    minimal_roi = {
       "0": 0.99,
    }
    
    # Stoploss: Defines the maximum tolerated loss before the trade is closed
    stoploss = -0.15

########################################################################################################################################################
# Parameters
########################################################################################################################################################
    is_optimize_base_nb_candles = False

    base_nb_candles_buy = IntParameter(8, 20, default=buy_params['base_nb_candles_buy'], space='buy', optimize=is_optimize_base_nb_candles)
    base_nb_candles_sell = IntParameter(8, 20, default=sell_params['base_nb_candles_sell'], space='sell', optimize=is_optimize_base_nb_candles)
    
    #Anti Dump and Pump
    is_optimize_antipump = True
    antipump_threshold = DecimalParameter(0, 0.4, default=buy_params['antipump_threshold'], space='buy', optimize=is_optimize_antipump)
    
############################################################################################################################################################################
    # lambo2
    is_optimize_lambo2 = True
    lambo2_ema_14_factor = DecimalParameter(0.8, 1.2, decimals=3,  default=buy_params['lambo2_ema_14_factor'], space='buy', optimize=is_optimize_lambo2)
    lambo2_rsi_4_limit = IntParameter(5, 60, default=buy_params['lambo2_rsi_4_limit'], space='buy', optimize=is_optimize_lambo2)
    lambo2_rsi_14_limit = IntParameter(5, 60, default=buy_params['lambo2_rsi_14_limit'], space='buy', optimize=is_optimize_lambo2)
    
############################################################################################################################################################################
    # Trailing Stoploss Parameters
    is_optimize_stoploss = True
    # Hard Stoploss Profit
    # These parameters help to dynamically adjust the stop loss to lock in profits as the price moves favorably.
    pHSL = DecimalParameter(-0.200, -0.040, default=-0.15, decimals=3, space='sell', optimize=is_optimize_stoploss, load=True)
    # profit threshold 1, trigger point, SL_1 is used
    pPF_1 = DecimalParameter(0.008, 0.020, default=0.016, decimals=3, space='sell', optimize=is_optimize_stoploss, load=True)
    pSL_1 = DecimalParameter(0.008, 0.020, default=0.014, decimals=3, space='sell', optimize=is_optimize_stoploss, load=True)
    # profit threshold 2, SL_2 is used
    pPF_2 = DecimalParameter(0.040, 0.100, default=0.024, decimals=3, space='sell', optimize=is_optimize_stoploss, load=True)
    pSL_2 = DecimalParameter(0.020, 0.070, default=0.022, decimals=3, space='sell', optimize=is_optimize_stoploss, load=True)
    
############################################################################################################################################################################
    # Sell params
    is_optimize_sell = True
    sell_fisher = RealParameter(0.1, 0.5, default=0.38414, space='sell', optimize=is_optimize_sell)
    sell_bbmiddle_close = RealParameter(0.97, 1.1, default=1.07634, space='sell', optimize=is_optimize_sell)
    high_offset_2 = DecimalParameter(1.010, 1.020, default=sell_params['high_offset_2'], space='sell', optimize=True)
    high_offset = DecimalParameter(1.005, 1.015, default=sell_params['high_offset'], space='sell', optimize=True)
############################################################################################################################################################################
    # Enabled
    lambo_2_enabled = BooleanParameter(default=buy_params['lambo_2_enabled'], space='buy', optimize=is_optimize_lambo2)

########################################################################################################################################################
# Informative Pairs
########################################################################################################################################################
    def informative_pairs(self):
        # Get the current whitelist from the data provider.
        pairs = self.dp.current_whitelist()
        informative_pairs = [(pair, '1h') for pair in pairs]  # Define informative pairs with a 1-hour timeframe.
    
        return informative_pairs
    
    def informative_1h_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        assert self.dp, "DataProvider is required for multiple timeframes."
    
        # Retrieve the 1-hour dataframe for the given pair from the data provider.
        informative_1h = self.dp.get_pair_dataframe(pair=metadata['pair'], timeframe=self.inf_1h)
    
        # Calculate various indicators on the 1-hour dataframe. Uncomment or add as needed.
        # Example of adding EMAs and RSI on the 1-hour timeframe.
        # informative_1h['ema_50'] = ta.EMA(informative_1h, timeperiod=50)
        # informative_1h['ema_200'] = ta.EMA(informative_1h, timeperiod=200)
        # informative_1h['rsi'] = ta.RSI(informative_1h, timeperiod=14)
    
        # Example of adding Bollinger Bands on the 1-hour timeframe.
        #bollinger = qtpylib.bollinger_bands(qtpylib.typical_price(informative_1h), window=20, stds=2)
        #informative_1h['bb_lowerband'] = bollinger['lower']
        #informative_1h['bb_middleband'] = bollinger['mid']
        #informative_1h['bb_upperband'] = bollinger['upper']
    
        return informative_1h
        
########################################################################################################################################################
# Indicators
########################################################################################################################################################
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        Calculate and append various technical indicators to the dataframe. These indicators are used
        to determine buy/sell signals according to the strategy's logic.
        """
        # Calculate moving average buy values using Exponential Moving Average (EMA) for trend detection.
        for val in self.base_nb_candles_buy.range:
            dataframe[f'ma_buy_{val}'] = ta.EMA(dataframe, timeperiod=val)
        
        # Calculate moving average sell values using EMA and other types of moving averages for trend analysis and to determine overbought conditions.
        for val in self.base_nb_candles_sell.range:
            dataframe[f'ma_sell_{val}'] = ta.EMA(dataframe, timeperiod=val)
            
        # Calculate Heikin Ashi Candles for a smoother representation of price action and trend.
        heikinashi = qtpylib.heikinashi(dataframe)
        dataframe['ha_open'] = heikinashi['open']
        dataframe['ha_close'] = heikinashi['close']
        dataframe['ha_high'] = heikinashi['high']
        dataframe['ha_low'] = heikinashi['low']
        
        # Pump
        dataframe['dema_30'] = ta.DEMA(dataframe, period=30)
        dataframe['dema_200'] = ta.DEMA(dataframe, period=200)
        dataframe['pump_strength'] = (dataframe['dema_30'] - dataframe['dema_200']) / dataframe['dema_30']
        
######################## Buy Side 
        #lambo2
        dataframe['ema_14'] = ta.EMA(dataframe, timeperiod=14)
        dataframe['rsi_4'] = ta.RSI(dataframe, timeperiod=4)
        dataframe['rsi_14'] = ta.RSI(dataframe, timeperiod=14)
        
######################## Sell Side    
        dataframe['hma_50'] = qtpylib.hull_moving_average(dataframe['close'], window=50)
        
        # RSI
        dataframe['rsi'] = ta.RSI(dataframe, timeperiod=14)
        dataframe['rsi_fast'] = ta.RSI(dataframe, timeperiod=4)
        dataframe['rsi_slow'] = ta.RSI(dataframe, timeperiod=20)
        
        # Apply Fisher Transform to identify potential price reversals more clearly.
        rsi = ta.RSI(dataframe)
        dataframe["rsi"] = rsi
        rsi = 0.1 * (rsi - 50)
        dataframe["fisher"] = (np.exp(2 * rsi) - 1) / (np.exp(2 * rsi) + 1)
        
        # Bollinger Bands
        mid, lower = bollinger_bands(ha_typical_price(dataframe), window_size=40, num_of_std=2)
        dataframe['lower'] = lower
        dataframe['mid'] = mid

        dataframe['bbdelta'] = (mid - dataframe['lower']).abs()
        dataframe['closedelta'] = (dataframe['ha_close'] - dataframe['ha_close'].shift()).abs()
        dataframe['tail'] = (dataframe['ha_close'] - dataframe['ha_low']).abs()

        dataframe['bb_lowerband'] = dataframe['lower']
        dataframe['bb_middleband'] = dataframe['mid']

        dataframe['ema_fast'] = ta.EMA(dataframe['ha_close'], timeperiod=3)
        dataframe['ema_slow'] = ta.EMA(dataframe['ha_close'], timeperiod=50)
        dataframe['volume_mean_slow'] = dataframe['volume'].rolling(window=30).mean()
        dataframe['rocr'] = ta.ROCR(dataframe['ha_close'], timeperiod=28)
        
######################## Informative    
        # Informative
        inf_tf = '1h'
        
        informative = self.dp.get_pair_dataframe(pair=metadata['pair'], timeframe=inf_tf)
        
        inf_heikinashi = qtpylib.heikinashi(informative)
        
        informative['ha_close'] = inf_heikinashi['close']
        informative['rocr'] = ta.ROCR(informative['ha_close'], timeperiod=168)
        
        informative_1h = self.informative_1h_indicators(dataframe, metadata)
        dataframe = self.pump_dump_protection(dataframe, metadata)
        
        # Merging
        dataframe = merge_informative_pair(dataframe, informative, self.timeframe, inf_tf, ffill=True)
        dataframe = merge_informative_pair(dataframe, informative_1h, self.timeframe, self.inf_1h, ffill=True)
    
        return dataframe
        
########################################################################################################################################################
# Pump Dump Protection
########################################################################################################################################################
    def pump_dump_protection(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        Analyze and append a pump/dump warning indicator based on abnormal volume changes.
        This function aims to identify sudden and significant changes in trading volume which often precede or accompany
        price manipulation or strong market movements (pumps/dumps).
        """
        # Shift the dataframe to get 36-hour and 24-hour historical data.
        df36h = dataframe.copy().shift(432)  # Assumes 5m timeframe
        df24h = dataframe.copy().shift(288)  # Assumes 5m timeframe
    
        # Calculate short, long, and base mean volumes.
        dataframe['volume_mean_short'] = dataframe['volume'].rolling(4).mean()
        dataframe['volume_mean_long'] = df24h['volume'].rolling(48).mean()
        dataframe['volume_mean_base'] = df36h['volume'].rolling(288).mean()
    
        # Calculate the percentage change in volume compared to the base.
        dataframe['volume_change_percentage'] = (dataframe['volume_mean_long'] / dataframe['volume_mean_base'])
    
        # Calculate the mean RSI over the last 48 periods.
        dataframe['rsi_mean'] = dataframe['rsi'].rolling(48).mean()
    
        # Warn if the short mean volume is significantly higher than the long mean volume.
        dataframe['pnd_volume_warn'] = np.where((dataframe['volume_mean_short'] / dataframe['volume_mean_long'] > 5.0), -1, 0)
    
        return dataframe

########################################################################################################################################################
# Buy Trend
########################################################################################################################################################
    def populate_buy_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        if 'buy_tag' not in dataframe:
            dataframe['buy_tag'] = ''
        
        dont_buy_conditions = dataframe['pnd_volume_warn'] < 0.0
        is_pump_safe = dataframe['pump_strength'] < self.antipump_threshold.value
    
        # Define conditions for each buy tag
        conditions_and_tags = [
            (self.check_lambo_2(dataframe), 'lambo_2_'),
        ]
    
        # Initialize buy column
        dataframe['buy'] = 0
    
        for condition, tag in conditions_and_tags:
            # Apply tag to rows where condition is met
            dataframe.loc[condition, 'buy_tag'] += tag
            # Set buy to 1 if condition is met and it's safe to buy
            dataframe.loc[condition & is_pump_safe & ~dont_buy_conditions, 'buy'] = 1
    
        # Apply the dont_buy condition last to overwrite previous buy signals if necessary
        dataframe.loc[dont_buy_conditions, 'buy'] = 0
        
        return dataframe
        
    def check_lambo_2(self, dataframe):
        condition = (
            bool(self.lambo_2_enabled.value) &
            #(dataframe['pump_warning'] == 0) &
            (dataframe['close'] < (dataframe['ema_14'] * self.lambo2_ema_14_factor.value)) &
            (dataframe['rsi_4'] < int(self.lambo2_rsi_4_limit.value)) &
            (dataframe['rsi_14'] < int(self.lambo2_rsi_14_limit.value))
        )
        return condition
        
########################################################################################################################################################
# Sell Trend
########################################################################################################################################################
    def populate_sell_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        conditions = []
    
        conditions.append(
            (   (dataframe['close']>dataframe['hma_50'])&
                (dataframe['close'] > (dataframe[f'ma_sell_{self.base_nb_candles_sell.value}'] * self.high_offset_2.value)) &
                (dataframe['rsi']>50)&
                (dataframe['volume'] > 0)&
                (dataframe['rsi_fast']>dataframe['rsi_slow'])

            )
            |
            (
                (dataframe['close']<dataframe['hma_50'])&
                (dataframe['close'] > (dataframe[f'ma_sell_{self.base_nb_candles_sell.value}'] * self.high_offset.value)) &
                (dataframe['volume'] > 0)&
                (dataframe['rsi_fast']>dataframe['rsi_slow'])
            )
        )
        
        # Apply all conditions
        if conditions:
            combined_condition = reduce(lambda x, y: x | y, conditions)
            dataframe.loc[combined_condition, 'sell'] = 1
    
        return dataframe
        
########################################################################################################################################################
# Confirm Trade Exit
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
# Trade Protections
########################################################################################################################################################
    @property
    def protections(self):
        return [
            {
                "method": "CooldownPeriod",
                "stop_duration_candles": 5
            },
            {
                "method": "MaxDrawdown",
                "lookback_period_candles": 48,
                "trade_limit": 20,
                "stop_duration_candles": 4,
                "max_allowed_drawdown": 0.2
            },
            {
                "method": "StoplossGuard",
                "lookback_period_candles": 24,
                "trade_limit": 4,
                "stop_duration_candles": 2,
                "only_per_pair": False
            },
            {
                "method": "LowProfitPairs",
                "lookback_period_candles": 6,
                "trade_limit": 2,
                "stop_duration_candles": 60,
                "required_profit": 0.02
            },
            {
                "method": "LowProfitPairs",
                "lookback_period_candles": 24,
                "trade_limit": 4,
                "stop_duration_candles": 2,
                "required_profit": 0.01
            }
        ]
        
########################################################################################################################################################
# Adjust Trade Position
########################################################################################################################################################
    def adjust_trade_position(self, trade: Trade, current_time: datetime, current_rate: float, current_profit: float, min_stake: float, max_stake: float, **kwargs):
            if current_profit > self.initial_safety_order_trigger:
                return None
    
            # credits to reinuvader for not blindly executing safety orders
            # Obtain pair dataframe.
            dataframe, _ = self.dp.get_analyzed_dataframe(trade.pair, self.timeframe)
            # Only buy when it seems it's climbing back up
            last_candle = dataframe.iloc[-1].squeeze()
            previous_candle = dataframe.iloc[-2].squeeze()
            if last_candle['close'] < previous_candle['close']:
                return None
    
            count_of_buys = 0
            for order in trade.orders:
                if order.ft_is_open or order.ft_order_side != 'buy':
                    continue
                if order.status == "closed":
                    count_of_buys += 1
    
            if 1 <= count_of_buys <= self.max_safety_orders:
                
                safety_order_trigger = abs(self.initial_safety_order_trigger) + (abs(self.initial_safety_order_trigger) * self.safety_order_step_scale * (math.pow(self.safety_order_step_scale,(count_of_buys - 1)) - 1) / (self.safety_order_step_scale - 1))
    
                if current_profit <= (-1 * abs(safety_order_trigger)):
                    try:
                        stake_amount = self.wallets.get_trade_stake_amount(trade.pair, None)
                        stake_amount = stake_amount * math.pow(self.safety_order_volume_scale,(count_of_buys - 1))
                        amount = stake_amount / current_rate
                        logger.info(f"Initiating safety order buy #{count_of_buys} for {trade.pair} with stake amount of {stake_amount} which equals {amount}")
                        return stake_amount
                    except Exception as exception:
                        logger.info(f'Error occured while trying to get stake amount for {trade.pair}: {str(exception)}') 
                        return None
    
            return None
        
########################################################################################################################################################
# Custom Trailing Stoploss by Perkmeister
########################################################################################################################################################
    def custom_stoploss(self, pair: str, trade: 'Trade', current_time: datetime, current_rate: float, current_profit: float, **kwargs) -> float:
        """
        Define a custom stoploss function to dynamically adjust stop-loss levels based on the current profit and predefined parameters.
        This approach aims to protect gains and minimize losses in a more adaptive manner compared to a fixed stop-loss.
        """
        # Define hard stoploss profit (HSL) and progressive stoploss thresholds and values (PF_1, PF_2, SL_1, SL_2).
        HSL = self.pHSL.value  # Hard stoploss - maximum loss tolerance.
        PF_1 = self.pPF_1.value  # Profit threshold 1 - when to start adjusting stoploss.
        SL_1 = self.pSL_1.value  # Stoploss for profits between PF_1 and PF_2.
        PF_2 = self.pPF_2.value  # Profit threshold 2 - when to further adjust stoploss.
        SL_2 = self.pSL_2.value  # Stoploss for profits above PF_2.
    
        # Calculate the stoploss based on the current profit level.
        if (current_profit > PF_2):
            # For profits above PF_2, increase stoploss linearly with profit.
            sl_profit = SL_2 + (current_profit - PF_2)
        elif (current_profit > PF_1):
            # For profits between PF_1 and PF_2, interpolate stoploss between SL_1 and SL_2.
            sl_profit = SL_1 + ((current_profit - PF_1) * (SL_2 - SL_1) / (PF_2 - PF_1))
        else:
            # For profits below PF_1, use the hard stoploss profit.
            sl_profit = HSL
    
        # Uncomment the following line to set a tighter stoploss if the trade has been open for a long time and is barely profitable.
        # if current_profit < 0.001 and current_time - timedelta(minutes=600) > trade.open_date_utc:
        #     return -0.005
    
        # Calculate and return the stoploss price using the stoploss_from_open utility, which considers the current profit and stoploss percentage.
        return stoploss_from_open(sl_profit, current_profit)
        
########################################################################################################################################################
# Custom to Sell 
########################################################################################################################################################
    def get_max_loss_threshold(self) -> float:
        """
        Implement logic to determine the maximum loss threshold.
        This value could be static or dynamic based on conditions or parameters.
        """
        return -0.04  # Example static value
        
    def get_max_holding_days(self) -> int:
        """
        Implement logic to determine the maximum holding days.
        This value could be static or dynamic based on conditions or parameters.
        """
        return 7  # Example static value    
    
    def custom_sell(self, pair: str, trade: 'Trade', current_time: 'datetime', current_rate: float, current_profit: float, **kwargs):
        """
        Define custom selling logic to unclog positions that have been held at a loss for too long.
        This method is called to evaluate if an open trade should be sold regardless of the normal selling strategy.
        """
        max_loss_threshold = self.get_max_loss_threshold()  # Dynamic threshold for maximum loss
        max_holding_days = self.get_max_holding_days()      # Dynamic threshold for maximum holding days
    
        days_held = (current_time - trade.open_date_utc).days  # Calculate the number of days the trade has been held
    
        if current_profit < max_loss_threshold and days_held >= max_holding_days:
            # If the current profit is below the loss threshold and the trade has been held for longer than allowed
            logger.info(f"Custom sell for {pair}: Held for {days_held} days with a profit of {current_profit}.")
            return 'unclog'  # 'unclog' is a custom sell reason indicating a forced sell to release the trade.
    
        return None  # Return None if no custom sell condition is met.