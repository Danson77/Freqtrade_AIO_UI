import freqtrade.vendor.qtpylib.indicators as qtpylib
import numpy as np
import talib.abstract as ta
from freqtrade.persistence import Trade
from freqtrade.strategy.interface import IStrategy
from freqtrade.strategy import merge_informative_pair, DecimalParameter, stoploss_from_open, RealParameter, IntParameter
from pandas import DataFrame, Series
from datetime import datetime
########################################################################################################################################################
# bollinger_bands
########################################################################################################################################################
def bollinger_bands(stock_price, window_size, num_of_std):
    rolling_mean = stock_price.rolling(window=window_size).mean()
    rolling_std = stock_price.rolling(window=window_size).std()
    lower_band = rolling_mean - (rolling_std * num_of_std)
    return np.nan_to_num(rolling_mean), np.nan_to_num(lower_band)
########################################################################################################################################################
# ha_typical_price
########################################################################################################################################################
def ha_typical_price(bars):
    res = (bars['ha_high'] + bars['ha_low'] + bars['ha_close']) / 3.
    return Series(index=bars.index, data=res)
########################################################################################################################################################
class DS_cha6_5m(IStrategy):
########################################################################################################################################################
# Hyperopt
########################################################################################################################################################
    buy_params = {
        # Data fram
        "rocr_1h": 0.51901,
        # Buy
        "bbdelta_close": 0.01965,
        "closedelta_close": 0.01466,
        "bbdelta_tail": 0.95089,
        "close_bblower": 0.00799,
    }
    sell_params = {
        # custom stoploss params, come from BB_RPB_TSL
        "pHSL": -0.32, #-0.35
        "pPF_1": 0.02,
        "pPF_2": 0.047, #0.05
        "pSL_1": 0.02,
        "pSL_2": 0.046,
        # Sell
        'sell_fisher': 0.38414, 
        'sell_bbmiddle_close': 0.96094,
        'volume': 26,
    }
########################################################################################################################################################
# Main
########################################################################################################################################################
    can_short = False

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
    ignore_roi_if_entry_signal = False

    stoploss = -0.25
    use_custom_stoploss = False

    trailing_stop = True
    trailing_stop_positive = 0.001
    trailing_stop_positive_offset = 0.01
    trailing_only_offset_is_reached = True

    use_entry_signal = True
    use_exit_signal = False

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
# Hyperopt Parameters
########################################################################################################################################################
    # Buy
    rocr_1h = DecimalParameter(0.5, 1.0, default=buy_params['rocr_1h'], space='buy', optimize=False) # 0.54904
    is_optimize_buy = False
    bbdelta_close = DecimalParameter(0.0005, 0.02, default=buy_params['bbdelta_close'], space='buy', optimize=True)
    closedelta_close = DecimalParameter(0.0005, 0.02, default=buy_params['closedelta_close'], space='buy', optimize=is_optimize_buy) # 0.00556
    bbdelta_tail = DecimalParameter(0.7, 1.0, default=buy_params['bbdelta_tail'], space='buy', optimize=is_optimize_buy)
    close_bblower = DecimalParameter(0.0005, 0.02, default=buy_params['close_bblower'], space='buy', optimize=is_optimize_buy)
    # Sell
    is_optimize_exit = False
    sell_fisher = DecimalParameter(0.1, 0.5, default=sell_params['sell_fisher'], space='sell', optimize=is_optimize_exit) # 0.38414
    sell_bbmiddle_close = DecimalParameter(0.97, 1.1, default=sell_params['sell_bbmiddle_close'], space='sell', optimize=is_optimize_exit) # 1.07634
    volume = IntParameter(7, 30, default=sell_params['volume'], space='sell', optimize=is_optimize_exit) # 27
############################################################################################################################################################################
    # Custom Stoploss
    is_optimize_stoploss = False
    # Hard stoploss profit
    pHSL = DecimalParameter(-0.500, -0.040, default=-0.08, decimals=3, space='sell', optimize=is_optimize_stoploss, load=True)
    # profit threshold 1, trigger point, SL_1 is used
    pPF_1 = DecimalParameter(0.008, 0.020, default=0.016, decimals=3, space='sell', optimize=is_optimize_stoploss, load=True)
    pSL_1 = DecimalParameter(0.008, 0.020, default=0.011, decimals=3, space='sell', optimize=is_optimize_stoploss, load=True)
    # profit threshold 2, SL_2 is used
    pPF_2 = DecimalParameter(0.040, 0.100, default=0.080, decimals=3, space='sell',optimize=is_optimize_stoploss, load=True)
    pSL_2 = DecimalParameter(0.020, 0.070, default=0.040, decimals=3, space='sell', optimize=is_optimize_stoploss,load=True)
############################################################################################################################################################################
# Informative
############################################################################################################################################################################
    def informative_pairs(self):
        pairs = self.dp.current_whitelist()
        informative_pairs = [(pair, '1h') for pair in pairs]
        
        return informative_pairs
########################################################################################################################################################
# Indicators
########################################################################################################################################################
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # # Heikin Ashi Candles
        heikinashi = qtpylib.heikinashi(dataframe)
        dataframe['ha_open'] = heikinashi['open']
        dataframe['ha_close'] = heikinashi['close']
        dataframe['ha_high'] = heikinashi['high']
        dataframe['ha_low'] = heikinashi['low']
        # Set Up Bollinger Bands
        mid, lower = bollinger_bands(ha_typical_price(dataframe), window_size=40, num_of_std=2)
        dataframe['lower'] = lower
        dataframe['mid'] = mid
        dataframe['bbdelta'] = (mid - dataframe['lower']).abs()
        dataframe['closedelta'] = (dataframe['ha_close'] - dataframe['ha_close'].shift()).abs()
        dataframe['tail'] = (dataframe['ha_close'] - dataframe['ha_low']).abs()
        dataframe['bb_lowerband'] = dataframe['lower']
        dataframe['bb_middleband'] = dataframe['mid']
        # Ewa
        dataframe['ema_fast'] = ta.EMA(dataframe['ha_close'], timeperiod=3)
        dataframe['ema_slow'] = ta.EMA(dataframe['ha_close'], timeperiod=50)
        dataframe['volume_mean_slow'] = dataframe['volume'].rolling(window=30).mean()
        dataframe['rocr'] = ta.ROCR(dataframe['ha_close'], timeperiod=28)
        #RSI
        rsi = ta.RSI(dataframe)
        dataframe["rsi"] = rsi
        rsi = 0.1 * (rsi - 50)
        dataframe["fisher"] = (np.exp(2 * rsi) - 1) / (np.exp(2 * rsi) + 1)
        # Informative
        informative = self.dp.get_pair_dataframe(pair=metadata['pair'], timeframe=self.informative)

        # Guard: missing / too short informative data -> make pair "non-tradable"
        if informative is None or informative.empty or len(informative) < 200:
            # Ensure column exists so later logic doesn't crash.
            # Set to 0 so rocr_1h.gt(threshold) is False (no entries).
            dataframe['rocr_1h'] = 0.0
            return dataframe

        inf_heikinashi = qtpylib.heikinashi(informative)
        informative['ha_close'] = inf_heikinashi['close']
        informative['rocr'] = ta.ROCR(informative['ha_close'], timeperiod=168)

        dataframe = merge_informative_pair(dataframe, informative, self.timeframe, self.informative, ffill=True)

        return dataframe
########################################################################################################################################################
# Buy
########################################################################################################################################################
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Initialize 'enter_tag' and 'enter_long' columns
        dataframe['enter_tag'] = ''
        dataframe['enter_long'] = 0

        # Define the single condition for the buy signal
        buy_condition = (
            dataframe['rocr_1h'].gt(self.rocr_1h.value) &
            (
                (
                    (dataframe['lower'].shift().gt(0)) &
                    (dataframe['bbdelta'].gt(dataframe['ha_close'] * self.bbdelta_close.value)) &
                    (dataframe['closedelta'].gt(dataframe['ha_close'] * self.closedelta_close.value)) &
                    (dataframe['tail'].lt(dataframe['bbdelta'] * self.bbdelta_tail.value)) &
                    (dataframe['ha_close'].lt(dataframe['lower'].shift())) &
                    (dataframe['ha_close'].le(dataframe['ha_close'].shift()))
                ) |
                (
                    (dataframe['ha_close'] < dataframe['ema_slow']) &
                    (dataframe['ha_close'] < self.close_bblower.value * dataframe['bb_lowerband'])
                )
            )
        )

        # Apply the condition to set 'enter_long' and tag the entry
        dataframe.loc[buy_condition, 'enter_long'] = 1
        dataframe.loc[buy_condition, 'enter_tag'] = 'ema_slow_entry'

        return dataframe
########################################################################################################################################################
# Sell
########################################################################################################################################################
    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Initialize 'exit_long' to 0 for all rows
        dataframe['exit_long'] = 0
        dataframe['exit_tag'] = 'no_exit'  # Default tag

        # Define your sell conditions
        sell_conditions = (
            (dataframe['fisher'] > self.sell_fisher.value) &
            (dataframe['ha_high'].le(dataframe['ha_high'].shift(1))) &
            (dataframe['ha_high'].shift(1).le(dataframe['ha_high'].shift(2))) &
            (dataframe['ha_close'].le(dataframe['ha_close'].shift(1))) &
            (dataframe['ema_fast'] > dataframe['ha_close']) &
            ((dataframe['ha_close'] * self.sell_bbmiddle_close.value) > dataframe['bb_middleband']) &
            (dataframe['volume'] > 0)
        )

        # Apply the condition to set 'exit_long' and tag the exit
        dataframe.loc[sell_conditions, 'exit_long'] = 1
        dataframe.loc[sell_conditions, 'exit_tag'] = 'fisher_ema_bearish'
    
        return dataframe
########################################################################################################################################################
# come from BB_RPB_TSL     # Custom Trailing stoploss ( credit to Perkmeister for this custom stoploss to help the strategy ride a green candle )
########################################################################################################################################################
    def custom_stoploss(self, pair: str, trade: 'Trade', current_time: datetime, current_rate: float, current_profit: float, **kwargs) -> float:
        # hard stoploss profit
        HSL = self.pHSL.value
        PF_1 = self.pPF_1.value
        SL_1 = self.pSL_1.value
        PF_2 = self.pPF_2.value
        SL_2 = self.pSL_2.value
        
        # For profits between PF_1 and PF_2 the stoploss (sl_profit) used is linearly interpolated
        # between the values of SL_1 and SL_2. For all profits above PF_2 the sl_profit value
        # rises linearly with current profit, for profits below PF_1 the hard stoploss profit is used.
        
        if current_profit > PF_2:
            sl_profit = SL_2 + (current_profit - PF_2)
        elif current_profit > PF_1:
            sl_profit = SL_1 + ((current_profit - PF_1) * (SL_2 - SL_1) / (PF_2 - PF_1))
        else:
            sl_profit = HSL
    
        # Only for hyperopt invalid return
        if sl_profit >= current_profit:
            return -0.99
    
        return stoploss_from_open(sl_profit, current_profit)
########################################################################################################################################################
# Exchnage 
########################################################################################################################################################
# Etheriu
########################################################################################################################################################
class DS_cha6_1m_ETH(DS_cha6_1m):
    buy_params = {
        'bbdelta-close': 0.01566,
        'bbdelta-tail': 0.8478,
        'close-bblower': 0.00998,
        'closedelta-close': 0.00614,
        'rocr-1h': 0.61579,
    }
    sell_params = {
        'sell_bbmiddle_close': 1.02894,
		'sell_fisher': 0.38414,
        'volume': 27
    }
    minimal_roi = {
        "0": 0.14414,
        "13": 0.10123,
        "20": 0.03256,
        "47": 0.0177,
        "132": 0.01016,
        "177": 0.00328,
        "277": 0
    }
    stoploss = -0.02
    trailing_stop = True
    trailing_stop_positive = 0.01
    trailing_stop_positive_offset = 0.0116
    trailing_only_offset_is_reached = False
########################################################################################################################################################
# Bitcoin
########################################################################################################################################################
class DS_cha6_1m_BTC(DS_cha6_1m):
    buy_params = {
        'bbdelta-close': 0.01192,
        'bbdelta-tail': 0.96183,
        'close-bblower': 0.01212,
        'closedelta-close': 0.01039,
        'rocr-1h': 0.53422,
        'volume': 27
    }
    sell_params = {
        'sell_bbmiddle_close': 0.98016, 
		'sell_fisher': 0.38414
    }
    minimal_roi = {
        "0": 0.19724,
        "15": 0.14323,
        "33": 0.07688,
        "52": 0.03011,
        "144": 0.01616,
        "307": 0.0063,
        "449": 0
    }
    stoploss = -0.11356
    trailing_stop = True
    trailing_stop_positive = 0.01544
    trailing_stop_positive_offset = 0.11438
    trailing_only_offset_is_reached = False
########################################################################################################################################################
# USDT
########################################################################################################################################################
class DS_cha6_1m_USD(DS_cha6_1m):
    buy_params = {
        'bbdelta-close': 0.01806,
        'bbdelta-tail': 0.85912,
        'close-bblower': 0.01158,
        'closedelta-close': 0.01466,
        'rocr-1h': 0.51901,
        'volume': 26
    }
    sell_params = {
        'sell_bbmiddle_close': 0.96094, 
        'sell_fisher': 0.38414
    }
    minimal_roi = {
        "0": 0.16139,
        "11": 0.12608,
        "54": 0.08335,
        "140": 0.03423,
        "197": 0.0123,
        "325": 0.00649,
        "417": 0
    }
    stoploss = -0.17654
    trailing_stop = True
    trailing_stop_positive = 0.0101
    trailing_stop_positive_offset = 0.02952
    trailing_only_offset_is_reached = False