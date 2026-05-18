# --- Do not remove these libs ---
from freqtrade.strategy import (
    IStrategy,
    merge_informative_pair,
    DecimalParameter,
    IntParameter,
)
from pandas import DataFrame
import talib.abstract as ta
import freqtrade.vendor.qtpylib.indicators as qtpylib
from freqtrade.persistence import Trade
from datetime import datetime
# --- Do not remove these libs ---


########################################################################################################################################################
class BearBull4(IStrategy):
########################################################################################################################################################
    """
    FIXED VERSION (preserves the "old good" trailing behavior, adds a rare backstop)

    What was fixed:
    - Keep trailing as the primary exit engine (do NOT tighten further).
    - Make thesis invalidation strict and data-safe (no reliance on analyzed inf columns that may not exist).
    - Do NOT accidentally create extra losing exits from trailing by changing offsets.
    - Keep existing entry logic and exit_hint logic unchanged.
    """

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
        "high_offset": 1.02,
        "high_offset_2": 1.04,

        "tp_min_profit": 0.012,
        "runner_arm_profit": 0.04,
        "runner_retrace": 0.02,

        # backstop params (kept, but logic is stricter below)
        "dead_max_days": 3,
        "dead_min_loss": -0.06,
        "dead_recover_profit": -0.02,
    }

    can_short = False

    minimal_roi = {}
    ignore_roi_if_entry_signal = False

    # Keep the wide hard stop (this strategy relies on trailing for exits)
    stoploss = -0.25
    use_custom_stoploss = False

    # IMPORTANT: keep trailing exactly at the "good" baseline
    trailing_stop = True
    trailing_stop_positive = 0.0015
    trailing_stop_positive_offset = 0.008
    trailing_only_offset_is_reached = True

    use_entry_signal = True
    use_exit_signal = False  # exits via custom_exit + trailing_stop_loss

    exit_profit_only = False
    exit_profit_offset = 0.0

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
            'mid': {},
            'lower': {},
            'upper': {},
            'ema_50': {},
            'ema_200': {},
        },
        'subplots': {
            'rsi': {
                'rsi': {},
                'rsi_fast': {},
                'rsi_slow': {},
            },
            'macd_inf': {
                f'macdhist_{informative}': {},
            },
            'exit': {
                'exit_hint': {},
            }
        }
    }

########################################################################################################################################################
# Trade Protections
########################################################################################################################################################
    @property
    def protections(self):
        return [
            {"method": "CooldownPeriod", "stop_duration_candles": 5},
            {
                "method": "MaxDrawdown",
                "lookback_period_candles": 72,
                "trade_limit": 20,
                "stop_duration_candles": 6,
                "max_allowed_drawdown": 0.03
            },
            {
                "method": "StoplossGuard",
                "lookback_period_candles": 48,
                "trade_limit": 4,
                "stop_duration_candles": 4,
                "only_per_pair": False
            },
            {
                "method": "LowProfitPairs",
                "lookback_period_candles": 24,
                "trade_limit": 2,
                "stop_duration_candles": 12,
                "required_profit": 0.02
            },
            {
                "method": "LowProfitPairs",
                "lookback_period_candles": 144,
                "trade_limit": 4,
                "stop_duration_candles": 24,
                "required_profit": 0.04
            }
        ]

########################################################################################################################################################
# Parameters
########################################################################################################################################################
    is_optimize_buy1 = True
    is_optimize_buy2 = True
    is_optimize_sell = True
    is_optimize_backstop = True

    bbdelta_close = DecimalParameter(0.016, 0.030, default=buy_params['bbdelta_close'], space='buy', optimize=is_optimize_buy1)
    closedelta_close = DecimalParameter(0.010, 0.020, default=buy_params['closedelta_close'], space='buy', optimize=is_optimize_buy1)
    tail_bbdelta = DecimalParameter(0.08, 0.15, default=buy_params['tail_bbdelta'], space='buy', optimize=is_optimize_buy1)

    bbdelta_close_2 = DecimalParameter(0.035, 0.065, default=buy_params['bbdelta_close_2'], space='buy', optimize=is_optimize_buy2)
    closedelta_close_2 = DecimalParameter(0.0015, 0.0045, default=buy_params['closedelta_close_2'], space='buy', optimize=is_optimize_buy2)
    tail_bbdelta_2 = DecimalParameter(0.16, 0.28, default=buy_params['tail_bbdelta_2'], space='buy', optimize=is_optimize_buy2)

    base_nb_candles_sell = IntParameter(10, 24, default=sell_params['base_nb_candles_sell'], space='sell', optimize=is_optimize_sell)
    high_offset = DecimalParameter(1.005, 1.06, default=sell_params['high_offset'], space='sell', optimize=is_optimize_sell)
    high_offset_2 = DecimalParameter(1.01, 1.10, default=sell_params['high_offset_2'], space='sell', optimize=is_optimize_sell)

    tp_min_profit = DecimalParameter(0.003, 0.03, default=sell_params['tp_min_profit'], space='sell', optimize=is_optimize_sell)
    runner_arm_profit = DecimalParameter(0.02, 0.10, default=sell_params['runner_arm_profit'], space='sell', optimize=is_optimize_sell)
    runner_retrace = DecimalParameter(0.008, 0.05, default=sell_params['runner_retrace'], space='sell', optimize=is_optimize_sell)

    dead_max_days = IntParameter(2, 10, default=sell_params['dead_max_days'], space='sell', optimize=is_optimize_backstop)
    dead_min_loss = DecimalParameter(-0.15, -0.03, default=sell_params['dead_min_loss'], space='sell', optimize=is_optimize_backstop)
    dead_recover_profit = DecimalParameter(-0.05, 0.0, default=sell_params['dead_recover_profit'], space='sell', optimize=is_optimize_backstop)

########################################################################################################################################################
# Informative pairs
########################################################################################################################################################
    def informative_pairs(self):
        pairs = self.dp.current_whitelist()
        return [(pair, self.informative) for pair in pairs]

########################################################################################################################################################
# Indicators
########################################################################################################################################################
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        inf_tf = self.informative
        macd_df = self.dp.get_pair_dataframe(pair=metadata['pair'], timeframe=inf_tf)

        if macd_df is None or macd_df.empty or 'close' not in macd_df.columns:
            dataframe[f'macdhist_{inf_tf}'] = 0.0
        else:
            macd = ta.MACD(macd_df, fastperiod=10, slowperiod=20, signalperiod=10)
            macd_df['macdhist'] = macd['macdhist']
            dataframe = merge_informative_pair(dataframe, macd_df, self.timeframe, inf_tf, ffill=True)

        mh = dataframe[f'macdhist_{inf_tf}']
        dataframe[f'macdhist_rising_{inf_tf}'] = mh > mh.shift(1)
        dataframe[f'macdhist_falling_{inf_tf}'] = mh < mh.shift(1)

        for val in self.base_nb_candles_sell.range:
            dataframe[f'ma_sell_{val}'] = ta.EMA(dataframe, timeperiod=val)

        dataframe['ema_50'] = ta.EMA(dataframe, timeperiod=50)
        dataframe['ema_200'] = ta.EMA(dataframe, timeperiod=200)

        dataframe['rsi'] = ta.RSI(dataframe, timeperiod=14)
        dataframe['rsi_slow'] = ta.RSI(dataframe, timeperiod=20)
        dataframe['rsi_fast'] = ta.RSI(dataframe, timeperiod=4)

        bb = ta.BBANDS(dataframe, timeperiod=40, nbdevup=2.0, nbdevdn=2.0)
        dataframe['mid'] = bb['middleband']
        dataframe['lower'] = bb['lowerband']
        dataframe['upper'] = bb['upperband']

        dataframe['bbdelta'] = (dataframe['mid'] - dataframe['lower']).abs()
        dataframe['closedelta'] = (dataframe['close'] - dataframe['close'].shift()).abs()
        dataframe['tail'] = (dataframe['close'] - dataframe['low']).abs()

        dataframe['atr'] = ta.ATR(dataframe, timeperiod=14)

        dataframe['sma_9'] = ta.SMA(dataframe, timeperiod=9)
        dataframe['hma_50'] = qtpylib.hull_moving_average(dataframe['close'], window=50)

        return dataframe

########################################################################################################################################################
# Entry
########################################################################################################################################################
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe['enter_long'] = 0
        dataframe['enter_tag'] = None

        inf_tf = self.informative
        mh = dataframe[f'macdhist_{inf_tf}']

        # Hardened regime:
        # - If mh > 0: OK
        # - If mh < 0: require mh rising for 2 consecutive informative steps
        mh_r1 = mh > mh.shift(1)
        mh_r2 = mh.shift(1) > mh.shift(2)
        regime_ok = (mh > 0) | ((mh < 0) & mh_r1 & mh_r2)

        bearish = (
            (mh < 0) &
            (dataframe['lower'].shift() > 0) &
            (dataframe['bbdelta'] > dataframe['close'] * self.bbdelta_close.value) &
            (dataframe['closedelta'] > dataframe['close'] * self.closedelta_close.value) &
            (dataframe['tail'] < dataframe['bbdelta'] * self.tail_bbdelta.value) &
            (dataframe['close'] < dataframe['lower'].shift()) &
            (dataframe['close'] <= dataframe['close'].shift())
        )

        bullish = (
            (mh > 0) &
            (dataframe['lower'].shift() > 0) &
            (dataframe['bbdelta'] > dataframe['close'] * self.bbdelta_close_2.value) &
            (dataframe['closedelta'] > dataframe['close'] * self.closedelta_close_2.value) &
            (dataframe['tail'] < dataframe['bbdelta'] * self.tail_bbdelta_2.value) &
            (dataframe['close'] < dataframe['lower'].shift()) &
            (dataframe['close'] <= dataframe['close'].shift())
        )

        entry_condition = (bearish | bullish) & regime_ok & (dataframe['volume'] > 0)
        dataframe.loc[entry_condition, ['enter_long', 'enter_tag']] = [1, 'dip_macdhist_regime_v2']

        return dataframe

########################################################################################################################################################
# Exit hints (NOT actual exits)
########################################################################################################################################################
    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe['exit_long'] = 0
        dataframe['exit_tag'] = None
        dataframe['exit_hint'] = 0

        ma_key = f'ma_sell_{self.base_nb_candles_sell.value}'
        exit_reversion_hint = (
            (dataframe['close'] > dataframe['mid']) &
            (dataframe['close'] > dataframe[ma_key] * self.high_offset.value) &
            (dataframe['rsi_fast'] < dataframe['rsi_slow']) &
            (dataframe['volume'] > 0)
        )

        dataframe.loc[exit_reversion_hint, 'exit_hint'] = 1
        return dataframe

########################################################################################################################################################
# Custom exit (actual exits)
########################################################################################################################################################
    def custom_exit(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs
    ):
        tp_min = float(self.tp_min_profit.value)

        # Peak profit tracking
        max_rate = trade.max_rate if trade.max_rate else trade.open_rate
        peak_profit = (max_rate / trade.open_rate) - 1.0

        arm = float(self.runner_arm_profit.value)
        retr = float(self.runner_retrace.value)

        # 1) Runner retrace: profit-gated + giveback-based
        if peak_profit >= arm and current_profit > 0:
            giveback = peak_profit - current_profit
            if giveback >= retr:
                return 'runner_retrace'

        # 2) Profit-take on exit_hint (profit-gated)
        if current_profit >= tp_min:
            df, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
            if df is not None and not df.empty:
                if int(df.iloc[-1].get('exit_hint', 0)) == 1:
                    return 'reversion_takeprofit'

        # 3) Thesis invalidation (STRICT + RARE)
        # Goal: reduce worst-tail WITHOUT touching the trailing engine.
        held_days = (current_time - trade.open_date_utc).total_seconds() / 86400.0

        # Make this stricter than before to avoid killing good trades:
        # - Must be held for at least max_days
        # - Must still be meaningfully red
        # - Must be below EMA200 on 5m
        # - Must have worsening bearish MACD hist for TWO consecutive 1h steps
        max_days = float(self.dead_max_days.value)
        min_loss = float(self.dead_min_loss.value)

        # "recover_floor" as a guard: if it has recovered above this, do not kill it
        recover_floor = float(self.dead_recover_profit.value)

        if held_days >= max_days and current_profit <= min_loss and current_profit <= recover_floor:

            # 5m condition: below EMA200
            df_5m, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
            if df_5m is None or len(df_5m) < 2:
                return None
            last_5m = df_5m.iloc[-1]
            close_5m = float(last_5m.get('close', 0.0))
            ema200_5m = float(last_5m.get('ema_200', 0.0))
            below_ema200 = close_5m > 0.0 and ema200_5m > 0.0 and (close_5m < ema200_5m)

            if not below_ema200:
                return None

            # 1h MACD hist: compute directly from raw 1h df (robust in backtest/live)
            inf_tf = self.informative
            inf_df = self.dp.get_pair_dataframe(pair=pair, timeframe=inf_tf)
            if inf_df is None or len(inf_df) < 60 or 'close' not in inf_df.columns:
                return None

            macd = ta.MACD(inf_df, fastperiod=10, slowperiod=20, signalperiod=10)
            mh = macd.get('macdhist', None)
            if mh is None or len(mh) < 4:
                return None

            mh_now = float(mh.iloc[-1])
            mh_prev = float(mh.iloc[-2])
            mh_prev2 = float(mh.iloc[-3])

            macd_bearish_and_worsening = (mh_now < 0) and (mh_now < mh_prev) and (mh_prev < mh_prev2)

            if macd_bearish_and_worsening:
                return 'thesis_invalidation'

        return None
