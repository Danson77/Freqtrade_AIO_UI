# --- Do not remove these libs ---
from freqtrade.strategy.interface import IStrategy
from pandas import DataFrame
import talib.abstract as ta
import freqtrade.vendor.qtpylib.indicators as qtpylib
import pandas as pd  # noqa
pd.options.mode.chained_assignment = None  # default='warn'
import technical.indicators as ftt
from functools import reduce


class ichiV2(IStrategy):
    """
    Trend + pullback + reclaim Ichimoku strategy.

    Goal:
    - Stop buying late into extension
    - Buy only when trend is valid AND a pullback has happened
    - Enter when price reclaims short-term strength
    - Exit on confirmed weakness, not every small wobble
    """

    INTERFACE_VERSION = 3

    buy_params = {
        "buy_trend_above_senkou_level": 1,
        "buy_trend_bullish_level": 4,
        "buy_fan_magnitude_shift_value": 2,
        "buy_min_fan_magnitude_gain": 1.001,
        "buy_max_rsi": 68,
        "buy_max_close_to_trend": 1.03,
    }

    sell_params = {
        "sell_trend_indicator": "trend_close_1h",
        "sell_fan_magnitude_gain": 0.995,
        "sell_min_rsi": 43,
    }

    minimal_roi = {
        "0": 0.059,
        "10": 0.037,
        "41": 0.012,
        "114": 0
    }

    stoploss = -0.07

    timeframe = '5m'
    startup_candle_count = 120
    process_only_new_candles = True

    trailing_stop = True
    trailing_stop_positive = 0.01
    trailing_stop_positive_offset = 0.02
    trailing_only_offset_is_reached = True

    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    plot_config = {
        'main_plot': {
            'senkou_a': {
                'color': 'green',
                'fill_to': 'senkou_b',
                'fill_label': 'Ichimoku Cloud',
                'fill_color': 'rgba(255,76,46,0.2)',
            },
            'senkou_b': {},
            'trend_close_5m': {'color': '#FF5733'},
            'trend_close_15m': {'color': '#FF8333'},
            'trend_close_30m': {'color': '#FFB533'},
            'trend_close_1h': {'color': '#FFE633'},
            'trend_close_2h': {'color': '#E3FF33'},
            'trend_close_4h': {'color': '#C4FF33'},
            'trend_close_6h': {'color': '#61FF33'},
            'trend_close_8h': {'color': '#33FF7D'},
            'ema_entry': {'color': '#00D1FF'},
            'ema_trend': {'color': '#B388FF'},
        },
        'subplots': {
            'fan_magnitude': {
                'fan_magnitude': {}
            },
            'fan_magnitude_gain': {
                'fan_magnitude_gain': {}
            },
            'rsi': {
                'rsi': {},
                'rsi_fast': {}
            }
        }
    }

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        if dataframe.empty:
            return dataframe

        heikinashi = qtpylib.heikinashi(dataframe)

        # Keep real close; smooth the rest a bit
        dataframe['open'] = heikinashi['open']
        dataframe['high'] = heikinashi['high']
        dataframe['low'] = heikinashi['low']

        # Trend stack
        dataframe['trend_close_5m'] = dataframe['close']
        dataframe['trend_close_15m'] = ta.EMA(dataframe['close'], timeperiod=3)
        dataframe['trend_close_30m'] = ta.EMA(dataframe['close'], timeperiod=6)
        dataframe['trend_close_1h'] = ta.EMA(dataframe['close'], timeperiod=12)
        dataframe['trend_close_2h'] = ta.EMA(dataframe['close'], timeperiod=24)
        dataframe['trend_close_4h'] = ta.EMA(dataframe['close'], timeperiod=48)
        dataframe['trend_close_6h'] = ta.EMA(dataframe['close'], timeperiod=72)
        dataframe['trend_close_8h'] = ta.EMA(dataframe['close'], timeperiod=96)

        dataframe['trend_open_5m'] = dataframe['open']
        dataframe['trend_open_15m'] = ta.EMA(dataframe['open'], timeperiod=3)
        dataframe['trend_open_30m'] = ta.EMA(dataframe['open'], timeperiod=6)
        dataframe['trend_open_1h'] = ta.EMA(dataframe['open'], timeperiod=12)
        dataframe['trend_open_2h'] = ta.EMA(dataframe['open'], timeperiod=24)
        dataframe['trend_open_4h'] = ta.EMA(dataframe['open'], timeperiod=48)
        dataframe['trend_open_6h'] = ta.EMA(dataframe['open'], timeperiod=72)
        dataframe['trend_open_8h'] = ta.EMA(dataframe['open'], timeperiod=96)

        # Fan magnitude
        dataframe['fan_magnitude'] = dataframe['trend_close_1h'] / dataframe['trend_close_8h']
        dataframe['fan_magnitude_gain'] = dataframe['fan_magnitude'] / dataframe['fan_magnitude'].shift(1)

        # Ichimoku
        ichimoku = ftt.ichimoku(
            dataframe,
            conversion_line_period=20,
            base_line_periods=60,
            laggin_span=120,
            displacement=30
        )
        dataframe['chikou_span'] = ichimoku['chikou_span']
        dataframe['tenkan_sen'] = ichimoku['tenkan_sen']
        dataframe['kijun_sen'] = ichimoku['kijun_sen']
        dataframe['senkou_a'] = ichimoku['senkou_span_a']
        dataframe['senkou_b'] = ichimoku['senkou_span_b']
        dataframe['leading_senkou_span_a'] = ichimoku['leading_senkou_span_a']
        dataframe['leading_senkou_span_b'] = ichimoku['leading_senkou_span_b']
        dataframe['cloud_green'] = ichimoku['cloud_green']
        dataframe['cloud_red'] = ichimoku['cloud_red']

        # Helpers
        dataframe['atr'] = ta.ATR(dataframe, timeperiod=14)
        dataframe['rsi'] = ta.RSI(dataframe, timeperiod=14)
        dataframe['rsi_fast'] = ta.RSI(dataframe, timeperiod=7)

        dataframe['ema_entry'] = ta.EMA(dataframe['close'], timeperiod=9)
        dataframe['ema_fast'] = ta.EMA(dataframe['close'], timeperiod=12)
        dataframe['ema_trend'] = ta.EMA(dataframe['close'], timeperiod=21)
        dataframe['ema_slow'] = ta.EMA(dataframe['close'], timeperiod=26)

        dataframe['volume_mean_24'] = dataframe['volume'].rolling(24).mean()

        # Pullback happened recently near short EMA
        dataframe['pullback_ok'] = (
            (dataframe['low'].shift(1) <= dataframe['ema_entry'].shift(1)) |
            (dataframe['close'].shift(1) <= dataframe['ema_entry'].shift(1) * 1.002) |
            (dataframe['rsi_fast'].shift(1) < 52)
        )

        # Reclaim / bounce after pullback
        dataframe['reclaim_ema'] = qtpylib.crossed_above(dataframe['close'], dataframe['ema_entry'])

        # Small recovery candle after pullback
        dataframe['rebound_ok'] = (
            (dataframe['close'] > dataframe['open']) &
            (dataframe['close'] > dataframe['close'].shift(1)) &
            (dataframe['rsi_fast'] > dataframe['rsi_fast'].shift(1))
        )

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        if dataframe.empty:
            return dataframe

        conditions = []

        # Trend above cloud
        if self.buy_params['buy_trend_above_senkou_level'] >= 1:
            conditions.append(dataframe['trend_close_5m'] > dataframe['senkou_a'])
            conditions.append(dataframe['trend_close_5m'] > dataframe['senkou_b'])

        if self.buy_params['buy_trend_above_senkou_level'] >= 2:
            conditions.append(dataframe['trend_close_15m'] > dataframe['senkou_a'])
            conditions.append(dataframe['trend_close_15m'] > dataframe['senkou_b'])

        if self.buy_params['buy_trend_above_senkou_level'] >= 3:
            conditions.append(dataframe['trend_close_30m'] > dataframe['senkou_a'])
            conditions.append(dataframe['trend_close_30m'] > dataframe['senkou_b'])

        if self.buy_params['buy_trend_above_senkou_level'] >= 4:
            conditions.append(dataframe['trend_close_1h'] > dataframe['senkou_a'])
            conditions.append(dataframe['trend_close_1h'] > dataframe['senkou_b'])

        if self.buy_params['buy_trend_above_senkou_level'] >= 5:
            conditions.append(dataframe['trend_close_2h'] > dataframe['senkou_a'])
            conditions.append(dataframe['trend_close_2h'] > dataframe['senkou_b'])

        if self.buy_params['buy_trend_above_senkou_level'] >= 6:
            conditions.append(dataframe['trend_close_4h'] > dataframe['senkou_a'])
            conditions.append(dataframe['trend_close_4h'] > dataframe['senkou_b'])

        if self.buy_params['buy_trend_above_senkou_level'] >= 7:
            conditions.append(dataframe['trend_close_6h'] > dataframe['senkou_a'])
            conditions.append(dataframe['trend_close_6h'] > dataframe['senkou_b'])

        if self.buy_params['buy_trend_above_senkou_level'] >= 8:
            conditions.append(dataframe['trend_close_8h'] > dataframe['senkou_a'])
            conditions.append(dataframe['trend_close_8h'] > dataframe['senkou_b'])

        # Bullish structure, but less stacked than before
        if self.buy_params['buy_trend_bullish_level'] >= 1:
            conditions.append(dataframe['trend_close_5m'] > dataframe['trend_open_5m'])

        if self.buy_params['buy_trend_bullish_level'] >= 2:
            conditions.append(dataframe['trend_close_15m'] > dataframe['trend_open_15m'])

        if self.buy_params['buy_trend_bullish_level'] >= 3:
            conditions.append(dataframe['trend_close_30m'] > dataframe['trend_open_30m'])

        if self.buy_params['buy_trend_bullish_level'] >= 4:
            conditions.append(dataframe['trend_close_1h'] > dataframe['trend_open_1h'])

        if self.buy_params['buy_trend_bullish_level'] >= 5:
            conditions.append(dataframe['trend_close_2h'] > dataframe['trend_open_2h'])

        if self.buy_params['buy_trend_bullish_level'] >= 6:
            conditions.append(dataframe['trend_close_4h'] > dataframe['trend_open_4h'])

        if self.buy_params['buy_trend_bullish_level'] >= 7:
            conditions.append(dataframe['trend_close_6h'] > dataframe['trend_open_6h'])

        if self.buy_params['buy_trend_bullish_level'] >= 8:
            conditions.append(dataframe['trend_close_8h'] > dataframe['trend_open_8h'])

        # Trend still needs to be strengthening, but not extreme
        conditions.append(dataframe['fan_magnitude'] > 1.0)
        conditions.append(dataframe['fan_magnitude_gain'] >= self.buy_params['buy_min_fan_magnitude_gain'])

        for x in range(self.buy_params['buy_fan_magnitude_shift_value']):
            conditions.append(dataframe['fan_magnitude'].shift(x + 1) < dataframe['fan_magnitude'])

        # Anti-chase / pullback logic
        conditions.append(dataframe['ema_fast'] > dataframe['ema_slow'])
        conditions.append(dataframe['close'] > dataframe['ema_trend'])
        conditions.append(dataframe['close'] <= dataframe['ema_trend'] * self.buy_params['buy_max_close_to_trend'])

        conditions.append(dataframe['rsi'] < self.buy_params['buy_max_rsi'])
        conditions.append(dataframe['rsi_fast'] > 45)
        conditions.append(dataframe['rsi_fast'] < 68)

        conditions.append(dataframe['volume'] > 0)
        conditions.append(dataframe['volume'] > dataframe['volume_mean_24'] * 0.25)

        # Key fix: require recent pullback, then reclaim
        conditions.append(dataframe['pullback_ok'])
        conditions.append(dataframe['reclaim_ema'] | dataframe['rebound_ok'])

        if conditions:
            entry_cond = reduce(lambda x, y: x & y, conditions).fillna(False)
            dataframe.loc[entry_cond, ['enter_long', 'enter_tag']] = (1, 'ichi_pullback_reclaim')

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        if dataframe.empty:
            return dataframe

        trend_break = qtpylib.crossed_below(
            dataframe['trend_close_5m'],
            dataframe[self.sell_params['sell_trend_indicator']]
        )

        fan_rollover = dataframe['fan_magnitude_gain'] < self.sell_params['sell_fan_magnitude_gain']

        rsi_loss = (
            (dataframe['rsi'] < self.sell_params['sell_min_rsi']) &
            (dataframe['rsi'] < dataframe['rsi'].shift(1))
        )

        cloud_loss = (
            (dataframe['close'] < dataframe['senkou_a']) &
            (dataframe['close'] < dataframe['senkou_b'])
        )

        ema_weakness = (
            (dataframe['ema_fast'] < dataframe['ema_trend']) &
            (dataframe['close'] < dataframe['ema_entry'])
        )

        # Need real weakness confirmation
        exit_cond = (
            (trend_break & rsi_loss) |
            (cloud_loss & fan_rollover & rsi_loss) |
            (ema_weakness & fan_rollover & rsi_loss)
        ).fillna(False)

        dataframe.loc[exit_cond, ['exit_long', 'exit_tag']] = (1, 'trend_rollover')

        return dataframe