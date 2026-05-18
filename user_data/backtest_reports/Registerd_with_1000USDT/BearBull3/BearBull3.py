from freqtrade.strategy import stoploss_from_open, merge_informative_pair, DecimalParameter, IntParameter, CategoricalParameter
from freqtrade.strategy import IStrategy, merge_informative_pair
from pandas import DataFrame
import talib.abstract as ta
import freqtrade.vendor.qtpylib.indicators as qtpylib
from functools import reduce
from freqtrade.persistence import Trade

from datetime import datetime, timedelta

# based on BinHV45 strategy: https://github.com/freqtrade/freqtrade-strategies/blob/master/user_data/strategies/berlinguyinca/BinHV45.py
# use at own risk

########################################################################################################################################################
class BearBull3(IStrategy):
########################################################################################################################################################
# Hyperopt
########################################################################################################################################################
    buy_params = {
        "bbdelta_close": 0.023,
        "bbdelta_close_2": 0.05,
        "closedelta_close": 0.014,
        "closedelta_close_2": 0.003,
        "tail_bbdelta": 0.104,
        "tail_bbdelta_2": 0.21,
    }
    sell_params = {
        "base_nb_candles_sell": 16,
        "high_offset": 1.084,
        "high_offset_2": 1.401,
    }
########################################################################################################################################################
# Main
########################################################################################################################################################
    can_short = False

    minimal_roi = {
        #"0": 0.15,
    }
    ignore_roi_if_entry_signal = False

    stoploss = -0.25
    use_custom_stoploss = False

    trailing_stop = True
    trailing_stop_positive = 0.001
    trailing_stop_positive_offset = 0.01
    trailing_only_offset_is_reached = True

    use_entry_signal = True
    use_exit_signal = True

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
    ## Buy_params
    #is_optimize_buy1 = True
    #is_optimize_buy2 = True
    #bbdelta_close = DecimalParameter(0.004, 0.024, default=buy_params['bbdelta_close'], space='buy', optimize=is_optimize_buy1)
    #closedelta_close = DecimalParameter(0.001, 0.014, default=buy_params['closedelta_close'], space='buy', optimize=is_optimize_buy1)
    #tail_bbdelta = DecimalParameter(0.05, 0.30, default=buy_params['tail_bbdelta'], space='buy', optimize=is_optimize_buy1)
    #bbdelta_close_2 = DecimalParameter(0.010, 0.055, default=buy_params['bbdelta_close_2'], space='buy', optimize=is_optimize_buy2)
    #closedelta_close_2 = DecimalParameter(0.001, 0.015, default=buy_params['closedelta_close_2'], space='buy', optimize=is_optimize_buy2)
    #tail_bbdelta_2 = DecimalParameter(0.1, 0.4, default=buy_params['tail_bbdelta_2'], space='buy', optimize=is_optimize_buy2)

    ## Sell_params
    #is_optimize_sell = True
    #base_nb_candles_sell = IntParameter(2, 25, default=sell_params['base_nb_candles_sell'], space='sell', optimize=is_optimize_sell)
    #high_offset = DecimalParameter(0.95, 1.1, default=sell_params['high_offset'], space='sell', optimize=is_optimize_sell)
    #high_offset_2 = DecimalParameter(0.99, 1.5, default=sell_params['high_offset_2'], space='sell', optimize=is_optimize_sell)
    ## = IntParameter(5, 80, default=sell_params['base_nb_candles_sell'], space='sell', optimize=is_optimize_sell)
    ## = DecimalParameter(0.99, 1.1, default=sell_params['high_offset'], space='sell', optimize=is_optimize_sell)

    ## Unclog params (sell space – exits)
    #is_optimize_unclog = True
    #unclog_max_days = IntParameter(3, 30, default=10, space='sell', optimize=is_optimize_unclog)
    ## exit losers only below this profit threshold
    #unclog_min_profit = DecimalParameter(-0.20, 0.05, default=0.0, space='sell', optimize=is_optimize_unclog)


    is_optimize_buy1 = True
    is_optimize_buy2 = True
    is_optimize_sell = True
    is_optimize_unclog = True

    bbdelta_close = DecimalParameter(0.016, 0.030,# around 0.023
        default=buy_params['bbdelta_close'], space='buy', optimize=is_optimize_buy1)

    closedelta_close = DecimalParameter(0.010, 0.020,# around 0.014
        default=buy_params['closedelta_close'], space='buy', optimize=is_optimize_buy1)

    tail_bbdelta = DecimalParameter(0.08, 0.15,# around 0.104
        default=buy_params['tail_bbdelta'], space='buy', optimize=is_optimize_buy1)

    bbdelta_close_2 = DecimalParameter(0.035, 0.065,# around 0.05
        default=buy_params['bbdelta_close_2'], space='buy', optimize=is_optimize_buy2)

    closedelta_close_2 = DecimalParameter(0.0015, 0.0045,# around 0.003
        default=buy_params['closedelta_close_2'], space='buy', optimize=is_optimize_buy2)

    tail_bbdelta_2 = DecimalParameter(0.16, 0.28,# around 0.21
        default=buy_params['tail_bbdelta_2'], space='buy', optimize=is_optimize_buy2)

    base_nb_candles_sell = IntParameter(10, 24,# around 16
        default=sell_params['base_nb_candles_sell'], space='sell', optimize=is_optimize_sell)

    high_offset = DecimalParameter(1.02, 1.14,# around 1.084
        default=sell_params['high_offset'], space='sell', optimize=is_optimize_sell)

    high_offset_2 = DecimalParameter(1.25, 1.55,# around 1.401
        default=sell_params['high_offset_2'], space='sell', optimize=is_optimize_sell)

    unclog_max_days = IntParameter(7, 18,# around 10
        default=10, space='sell', optimize=is_optimize_unclog)

    unclog_min_profit = DecimalParameter(-0.08, 0.02,# small loss up to slight profit
        default=0.0, space='sell', optimize=is_optimize_unclog)

########################################################################################################################################################
# Infromative
########################################################################################################################################################
    def informative_pairs(self):
        pairs = self.dp.current_whitelist()
        informative_pairs = [(pair, self.informative) for pair in pairs]
        return informative_pairs
########################################################################################################################################################
# Indicators
########################################################################################################################################################
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:

        # macd timeframe for trend detection (informative TF)
        inf_tf = self.informative  # e.g. '1h'
        macd_df = self.dp.get_pair_dataframe(pair=metadata['pair'], timeframe=inf_tf)

        # Safety: if informative data missing, just skip (prevents crashes)
        if macd_df is None or macd_df.empty or 'close' not in macd_df.columns:
            dataframe['macdhist_' + inf_tf] = 0.0
        else:
            macd_df['macdhist'] = ta.MACD(macd_df, fastperiod=10, slowperiod=20, signalperiod=10)['macdhist']
            dataframe = merge_informative_pair(dataframe, macd_df, self.timeframe, inf_tf, ffill=True)

        # Calculate all ma_sell values
        for val in self.base_nb_candles_sell.range:
            dataframe[f'ma_sell_{val}'] = ta.EMA(dataframe, timeperiod=val)

        dataframe['sma_9'] = ta.SMA(dataframe, timeperiod=9)
        dataframe['hma_50'] = qtpylib.hull_moving_average(dataframe['close'], window=50)

        dataframe['rsi'] = ta.RSI(dataframe, timeperiod=14)
        dataframe['rsi_slow'] = ta.RSI(dataframe, timeperiod=20)
        dataframe['rsi_fast'] = ta.RSI(dataframe, timeperiod=4)

        # normal timeframe
        bb = ta.BBANDS(dataframe, timeperiod=40, nbdevup=2.0, nbdevdn=2.0)
        dataframe['mid'] = bb['middleband']
        dataframe['lower'] = bb['lowerband']
        dataframe['bbdelta'] = (dataframe['mid'] - dataframe['lower']).abs()
        #dataframe['pricedelta'] = (dataframe['open'] - dataframe['close']).abs()
        dataframe['closedelta'] = (dataframe['close'] - dataframe['close'].shift()).abs()
        dataframe['tail'] = (dataframe['close'] - dataframe['low']).abs()
        return dataframe
########################################################################################################################################################
# Entry
########################################################################################################################################################
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe['enter_long'] = 0
        dataframe['enter_tag'] = None

        bearish = (
            (dataframe[f'macdhist_{self.informative}'] < 0) &
            (dataframe['lower'].shift() > 0) &
            (dataframe['bbdelta'] > dataframe['close'] * self.bbdelta_close.value) &
            (dataframe['closedelta'] > dataframe['close'] * self.closedelta_close.value) &
            (dataframe['tail'] < dataframe['bbdelta'] * self.tail_bbdelta.value) &
            (dataframe['close'] < dataframe['lower'].shift()) &
            (dataframe['close'] <= dataframe['close'].shift())
        )

        bullish = (
            (dataframe[f'macdhist_{self.informative}'] > 0) &
            (dataframe['lower'].shift() > 0) &
            (dataframe['bbdelta'] > dataframe['close'] * self.bbdelta_close_2.value) &
            (dataframe['closedelta'] > dataframe['close'] * self.closedelta_close_2.value) &
            (dataframe['tail'] < dataframe['bbdelta'] * self.tail_bbdelta_2.value) &
            (dataframe['close'] < dataframe['lower'].shift()) &
            (dataframe['close'] <= dataframe['close'].shift())
        )

        entry_condition = (bearish | bullish) & (dataframe['volume'] > 0)

        dataframe.loc[entry_condition, ['enter_long', 'enter_tag']] = [1, 'macdhist']

        return dataframe
########################################################################################################################################################
# Exit
########################################################################################################################################################
    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe['exit_long'] = 0
        dataframe['exit_tag'] = None

        exit_sma = (
            (dataframe['close'] > dataframe['sma_9']) &
            (dataframe['close'] > (dataframe[f'ma_sell_{self.base_nb_candles_sell.value}'] * self.high_offset_2.value)) &
            (dataframe['rsi'] > 50) &
            (dataframe['volume'] > 0) &
            (dataframe['rsi_fast'] > dataframe['rsi_slow'])
        )

        exit_hma = (
            (dataframe['close'] < dataframe['hma_50']) &
            (dataframe['close'] > (dataframe[f'ma_sell_{self.base_nb_candles_sell.value}'] * self.high_offset.value)) &
            (dataframe['volume'] > 0) &
            (dataframe['rsi_fast'] > dataframe['rsi_slow']) &
            (dataframe['exit_long'] == 0)
        )

        dataframe.loc[exit_sma, ['exit_long', 'exit_tag']] = [1, 'sma_9']
        dataframe.loc[exit_hma, ['exit_long', 'exit_tag']] = [1, 'hma_50']

        return dataframe
########################################################################################################################################################
# Custom to Sell unclog
########################################################################################################################################################
#    def custom_exit(self, pair: str, trade: 'Trade', current_time: 'datetime', current_rate: float, current_profit: float, **kwargs):
#        # Sell any positions at a loss if they are held for more than X days.
#        # Hyperopted unclog parameters
#        max_days = int(self.unclog_max_days.value)
#        min_profit = float(self.unclog_min_profit.value)
#
#        held_days = (current_time - trade.open_date_utc).days
#
#        # If position is stuck longer than max_days and profit is below threshold,
#        # force-exit to unclog capital.
#        if held_days >= max_days and current_profit <= min_profit:
#            return 'unclog'
#
#        # otherwise: no custom exit
#        return None