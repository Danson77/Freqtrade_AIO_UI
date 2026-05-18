import numpy as np
import pandas as pd
import talib.abstract as ta
import freqtrade.vendor.qtpylib.indicators as qtpylib
from freqtrade.strategy import IStrategy, stoploss_from_absolute, stoploss_from_open, DecimalParameter, IntParameter
from freqtrade.persistence import Trade
from datetime import datetime, timezone
# import logging  # remove after
# logger = logging.getLogger(__name__)  # remove after
########################################################################################################################################################
class Klodger_5m(IStrategy):
########################################################################################################################################################
# Hyperopt
########################################################################################################################################################
    buy_params = {
    "buy_1": 0.2,
    "buy_2": 0.05,
    }
    sell_params = {
    "sell_1": 0.9,
    "sell_2": 0.03,
    }
    # ROI table (config.json can't have this value as it will override): 
    minimal_roi = {
        "7200": 0.01, # After 5 days, take 1% profit
        "4320": 0.03, # After 3 days, take 2% profit
        "2880": 0.04, # After 2 days, take 3% profit
        "1440": 0.05, # After 1 day, take 4% profit
        "480":  0.08, # After 8 hours, take 5% profit
        "120":  0.10, # After 2 hours, take 8% profit
        "15":  0.15, # After 15 minutes, take 10% profit
        "0":   0.20 
    }
    stoploss = -0.40 #-0.20
    trailing_stop = True
    trailing_stop_positive = 0.013          # Offset from the highest profit point to activate the trailing stop.
    trailing_stop_positive_offset = 0.0205  # Profit necessary to trigger the trailing stop.
    trailing_only_offset_is_reached = True  # Keep stoploss static UNTIL the offset is reached then trigger trailing stop.
    use_custom_stoploss = False
########################################################################################################################################################
# Main
########################################################################################################################################################
    timeframe = '5m'  # The primary timeframe for analysis.
    #inf_1h = '1h'  # Informative timeframe to gather additional data.
    process_only_new_candles = True # Consider candles upon startup.
    startup_candle_count = 400 # Number of past candles to consider upon startup.

    can_short = False

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
    # Buy
    buy_1 = DecimalParameter(0.01, 1.0, default=buy_params['buy_1'], space='buy', optimize=False)
    buy_2 = DecimalParameter(0.01, 0.15, default=buy_params['buy_2'], space='buy', optimize=False)
    ## Sell
    sell_1 = DecimalParameter(0.01, 1.5, default=sell_params['sell_1'], space='sell', optimize=False)
    sell_2 = DecimalParameter(0.01, 0.10, default=sell_params['sell_2'], space='sell', optimize=False)
########################################################################################################################################################
# calc_stop_loss_pct
########################################################################################################################################################
    def calc_stop_loss_pct(self, current_rate: float, atr_multiplier: float) -> float:
        return -atr_multiplier * current_rate
########################################################################################################################################################
# max_profits
########################################################################################################################################################
    max_profits = {}
    def on_trade_update(self, trade: Trade, **kwargs):
        # Update max_profit for the trade
        if trade.pair not in self.max_profits:
            self.max_profits[trade.pair] = 0
        self.max_profits[trade.pair] = max(self.max_profits[trade.pair], trade.current_profit_ratio)
        
    def on_trade_close(self, trade: Trade, **kwargs):
        # Remove max_profit for the trade
        self.max_profits.pop(trade.pair, None)
########################################################################################################################################################
# Indicators
########################################################################################################################################################
    def populate_indicators(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        """ Populates new indicators for given strategy
        Args:
            dataframe (pd.DataFrame): dataframe for the given pair
            metadata (dict): metadata for the given pair
        Returns:
            pd.DataFrame: dataframe with the defined indicators
        """
        # SMA
        dataframe['sma200'] = ta.SMA(dataframe, timeperiod=200)
        dataframe['sma50'] = ta.SMA(dataframe, timeperiod=50)
        dataframe['sma20'] = ta.SMA(dataframe, timeperiod=20)
        # Bollinger Bands #2
        bb_upper, bb_lower, bb_middle = ta.BBANDS(dataframe['close'], timeperiod=20)
        dataframe['bb_upper'] = bb_upper
        dataframe['bb_lower'] = bb_lower
        dataframe['bb_width'] = (bb_upper - bb_lower) / bb_middle
        # Bollinger Bands
        bollinger = qtpylib.bollinger_bands(qtpylib.typical_price(dataframe), window=20, stds=2)
        dataframe['bb_lowerband'] = bollinger['lower']
        dataframe['bb_middleband'] = bollinger['mid']
        dataframe['bb_upperband'] = bollinger['upper']
        dataframe['bb_percent'] = \
        (dataframe['close'] - dataframe['bb_lowerband']) / (dataframe['bb_upperband'] - dataframe['bb_lowerband'])
        dataframe['bb_width'] = (dataframe['bb_upperband'] - dataframe['bb_lowerband']) / dataframe['bb_middleband']
        # Candlestick patterns bullish
        dataframe['cdl3inside'] = ta.CDL3INSIDE(dataframe)
        dataframe['cdl3outside'] = ta.CDL3OUTSIDE(dataframe)
        dataframe['cdl3starsinsouth'] = ta.CDL3STARSINSOUTH(dataframe)
        dataframe['cdlhammer'] = ta.CDLHAMMER(dataframe)
        dataframe['cdlinvertedhammer'] = ta.CDLINVERTEDHAMMER(dataframe)
        # Candlestick patterns bearish
        dataframe['cdl3blackcrows'] = ta.CDL3BLACKCROWS(dataframe)
        dataframe['cdl3whitesoldiers'] = ta.CDL3WHITESOLDIERS(dataframe)
        dataframe['cdl3linestrike'] = ta.CDL3LINESTRIKE(dataframe)
        dataframe['cdlgravestonedoji'] = ta.CDLGRAVESTONEDOJI(dataframe)
        dataframe['cdlshootingstar'] = ta.CDLSHOOTINGSTAR(dataframe)
        # Bullish or bearish
        dataframe['cdlengulfing'] = ta.CDLENGULFING(dataframe)
        # Calclate ATR
        dataframe['ATR'] = ta.ATR(dataframe, timeperiod=150)
        # Calculate ATR stoploss
        dataframe['ATR_stoploss'] = dataframe['ATR'] * 6.5
        # MACD
        macd = ta.MACD(dataframe)
        dataframe['macd'] = macd['macd']
        dataframe['macdsignal'] = macd['macdsignal']
        dataframe['macdhist'] = macd['macdhist']
        return dataframe
########################################################################################################################################################
# Buy Trend
########################################################################################################################################################
    def populate_entry_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        """ Populate rules for the 'buy' signal """
        # Define bullish conditions based on SMA and Bollinger Bands
        bullish_conditions = (
            (dataframe['sma20'] > dataframe['sma50']) &  # Short-term trend
            (dataframe['sma50'] > dataframe['sma200']) &  # Long-term trend
            (dataframe['bb_percent'] < self.buy_1.value) &  # Price near the lower Bollinger Band
            (dataframe['bb_width'] < self.buy_2.value)  # Narrow Bollinger Bands
        )
        # Candlestick patterns
        candlestick_patterns = (
            (dataframe['cdl3inside'] == 100) | 
            (dataframe['cdl3outside'] == 100) | 
            (dataframe['cdl3starsinsouth'] == 100) |
            (dataframe['cdlhammer'] == 100) |
            (dataframe['cdlinvertedhammer'] == 100)
        )
        # MACD-based entry condition
        macd_condition = (
            (dataframe['macd'] > dataframe['macdsignal'])  # MACD line above signal line
        )

        # Apply buy conditions
        enter_conditions = (bullish_conditions | candlestick_patterns) & macd_condition
        dataframe.loc[enter_conditions, 'enter_long'] = 1

        # Set custom tag
        dataframe.loc[enter_conditions, 'enter_tag'] = "klodger_entry"

        return dataframe
########################################################################################################################################################
# Sell Trend
########################################################################################################################################################
    def populate_exit_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:

        # Define bearish conditions based on SMA and Bollinger Bands
        bearish_conditions = (
            (dataframe['sma50'] < dataframe['sma200']) &
            (dataframe['bb_percent'] > self.sell_1.value) &
            (dataframe['bb_width'] > self.sell_2.value)
        )
        # Candlestick patterns
        candlestick_patterns = (
            (dataframe['cdl3blackcrows'] == -100) |  # 3 Black Crows
            (dataframe['cdl3whitesoldiers'] == 100) |  # 3 White Soldiers
            (dataframe['cdl3linestrike'] == -100) |  # 3 Line Strike
            (dataframe['cdlgravestonedoji'] == -100) |  # Gravestone Doji
            (dataframe['cdlshootingstar'] == -100)  # Shooting Star
        )
        # MACD-based exit conditions
        macd_condition = (
        (dataframe['macd'] < dataframe['macdsignal'])  # MACD line below signal line
        )

        # Combine exit conditions
        exit_condition = (bearish_conditions & candlestick_patterns & macd_condition)

        # Apply exit conditions
        dataframe.loc[exit_condition, 'exit_long'] = 1

        # Set custom tag for backtests
        dataframe.loc[exit_condition, 'exit_tag'] = "klodger_exit"

        return dataframe
########################################################################################################################################################
# Custom Stoploss
########################################################################################################################################################        
    def custom_stoploss(self, pair: str, trade: 'Trade', current_profit: float, current_rate: float, **kwargs) -> float:
        # Retrieve max_profit for the current pair; default to current_profit if not found
        max_profit = self.max_profits.get(pair, current_profit)
        # Calculate the drawdown from the peak profit
        peak_profit_drawdown = max_profit - current_profit
        # Initial ATR-based stop loss adjustment
        atr_stoploss = self.calc_stop_loss_pct(current_rate, 6.5)
        # Adjust stop loss based on drawdown from peak profit
        if peak_profit_drawdown > 0.05:  # If drawdown from peak is greater than 5%
            atr_stoploss *= 0.8  # Tighten the stop loss by 20%
        elif peak_profit_drawdown > 0.1:  # If drawdown from peak is greater than 10%
            atr_stoploss *= 0.6  # Tighten the stop loss by 40%
        # Adjust stop loss based on current profit
        if current_profit > 0.05:  # If current profit is above 5%
            atr_stoploss *= 0.8  # Tighten the stop loss by 20%
        elif current_profit > 0.1:  # If current profit is above 10%
            atr_stoploss *= 0.6  # Tighten the stop loss by 40%
        # Ensure the custom stop loss is not looser than the initial stop loss
        adjusted_stoploss = max(atr_stoploss, self.stoploss)
        return adjusted_stoploss
########################################################################################################################################################
# Custom Sell
########################################################################################################################################################   
    #def custom_exit(self, pair: str, trade: 'Trade', current_time: 'datetime', current_rate: float, current_profit: float, **kwargs):
    #    # Sell any positions at a loss if they are held for more than 1 day.
    #    dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
    #    last_candle = dataframe.iloc[-1].squeeze()

    #    ## Above 20% profit, sell when rsi < 80
    #    #if current_profit > 0.2:
    #    #    if last_candle["rsi"] < 80:
    #    #        return "rsi_below_80"

    #    ## Between 2% and 10%, sell if EMA-long above EMA-short
    #    #if 0.02 < current_profit < 0.1:
    #    #    if last_candle["emalong"] > last_candle["emashort"]:
    #    #        return "ema_long_below_80"

    #    # Calculate the time held in hours
    #    time_held_in_hours = (current_time - trade.open_date_utc).total_seconds() / 3600

    #    # Sell any positions at a loss if they are held for more than specified time.
    #    if (
    #        (current_profit <= 0.00 and time_held_in_hours >= 64) or
    #        (current_profit <= 0.01 and time_held_in_hours >= 67) or
    #        (current_profit <= -0.01 and time_held_in_hours >= 64)
    #    ):
    #        return "unclog"
