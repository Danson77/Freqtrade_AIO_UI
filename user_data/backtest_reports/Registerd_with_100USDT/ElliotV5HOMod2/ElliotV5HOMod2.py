# --- Do not remove these libs ---
from freqtrade.strategy.interface import IStrategy
from pandas import DataFrame
import talib.abstract as ta
import numpy as np
import freqtrade.vendor.qtpylib.indicators as qtpylib
from freqtrade.strategy import DecimalParameter, IntParameter
# --------------------------------


def EWO(dataframe: DataFrame, ema_length: int = 5, ema2_length: int = 35) -> DataFrame:
    """
    Elliot Wave Oscillator (EWO) = (EMA(fast) - EMA(slow)) / close * 100
    """
    ema1 = ta.EMA(dataframe["close"], timeperiod=int(ema_length))
    ema2 = ta.EMA(dataframe["close"], timeperiod=int(ema2_length))
    return (ema1 - ema2) / dataframe["close"] * 100


class ElliotV5HOMod2(IStrategy):
    """
    Fixed / cleaned for your current intent:
    - No informative timeframe overhead (removed, since unused).
    - No EMA precompute loops (massive speed + RAM win).
    - Entry logic unchanged.
    - Exit signal logic kept but DISABLED by default (use_exit_signal=False), so it cannot hurt.
    - Plot columns maintained.
    """

    can_short = False

    # ROI / risk (kept)
    minimal_roi = {
        "0": 0.05,
        "40": 0.04,
        "201": 0.03
    }
    ignore_roi_if_entry_signal = False

    stoploss = -0.25
    use_custom_stoploss = False

    trailing_stop = True
    trailing_stop_positive = 0.001
    trailing_stop_positive_offset = 0.01
    trailing_only_offset_is_reached = True

    use_entry_signal = True

    # You are explicitly running on ROI+trailing+stoploss exits:
    use_exit_signal = False
    exit_profit_only = False
    exit_profit_offset = 0.03

    timeframe = "5m"
    process_only_new_candles = False
    startup_candle_count = 200

    order_types = {
        "entry": "market",
        "exit": "market",
        "trailing_stop_loss": "market",
        "emergency_exit": "market",
        "force_entry": "market",
        "force_exit": "market",
        "stoploss": "market",
        "stoploss_on_exchange": False,
        "stoploss_on_exchange_interval": 60,
        "stoploss_on_exchange_limit_ratio": 0.99,
    }
    order_time_in_force = {"entry": "gtc", "exit": "gtc"}

    plot_config = {
        "main_plot": {
            "ma_buy": {"color": "orange"},
            "ma_sell": {"color": "orange"},
        }
    }

    @property
    def protections(self):
        return [
            {"method": "CooldownPeriod", "stop_duration_candles": 5},
            {
                "method": "MaxDrawdown",
                "lookback_period_candles": 72,   # 6h on 5m
                "trade_limit": 20,
                "stop_duration_candles": 6,      # 30m
                "max_allowed_drawdown": 0.03,
            },
            {
                "method": "StoplossGuard",
                "lookback_period_candles": 48,   # 4h
                "trade_limit": 4,
                "stop_duration_candles": 4,      # 20m
                "only_per_pair": False,
            },
            {
                "method": "LowProfitPairs",
                "lookback_period_candles": 24,   # 2h
                "trade_limit": 2,
                "stop_duration_candles": 12,     # 1h
                "required_profit": 0.02,
            },
            {
                "method": "LowProfitPairs",
                "lookback_period_candles": 144,  # 12h
                "trade_limit": 4,
                "stop_duration_candles": 24,     # 2h
                "required_profit": 0.04,
            },
        ]

    # -------- Parameters (keep ranges, but compute only what we use) --------
    fast_ewo = 50
    slow_ewo = 200

    enable_opt_buy = True

    base_nb_candles_buy = IntParameter(5, 80, default=19, space="buy", optimize=enable_opt_buy)
    ewo_high = DecimalParameter(2.0, 12.0, default=5.417, space="buy", optimize=enable_opt_buy)
    ewo_low = DecimalParameter(-20.0, -8.0, default=-17.251, space="buy", optimize=enable_opt_buy)
    low_offset = DecimalParameter(0.9, 0.99, default=0.983, space="buy", optimize=enable_opt_buy)
    rsi_buy = IntParameter(30, 70, default=61, space="buy", optimize=enable_opt_buy)

    # These sell params are only useful if you later enable use_exit_signal=True
    base_nb_candles_sell = IntParameter(5, 80, default=24, space="sell", optimize=False)
    high_offset = DecimalParameter(0.99, 1.1, default=1.011, space="sell", optimize=False)

    # ----------------------------------------------------------------------

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Only compute the EMA periods actually used right now (FAST + clean)
        buy_len = int(self.base_nb_candles_buy.value)
        sell_len = int(self.base_nb_candles_sell.value)

        dataframe["ma_buy"] = ta.EMA(dataframe["close"], timeperiod=buy_len)
        dataframe["ma_sell"] = ta.EMA(dataframe["close"], timeperiod=sell_len)

        dataframe["EWO"] = EWO(dataframe, self.fast_ewo, self.slow_ewo)

        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["rsi_fast"] = ta.RSI(dataframe, timeperiod=4)
        dataframe["rsi_slow"] = ta.RSI(dataframe, timeperiod=20)

        dataframe["hma_50"] = qtpylib.hull_moving_average(dataframe["close"], window=50)

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["enter_long"] = 0
        dataframe["enter_tag"] = None

        ma_buy = dataframe["ma_buy"]

        cond_high = (
            (dataframe["close"] < ma_buy * self.low_offset.value)
            & (dataframe["EWO"] > self.ewo_high.value)
            & (dataframe["rsi"] < self.rsi_buy.value)
            & (dataframe["volume"] > 0)
        )

        cond_low = (
            (dataframe["close"] < ma_buy * self.low_offset.value)
            & (dataframe["EWO"] < self.ewo_low.value)
            & (dataframe["rsi"] < self.rsi_buy.value)
            & (dataframe["volume"] > 0)
        )

        dataframe.loc[cond_high, ["enter_long", "enter_tag"]] = [1, "ewo_high"]
        dataframe.loc[cond_low, ["enter_long", "enter_tag"]] = [1, "ewo_low"]

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        Kept for debugging / future toggling.
        NOTE: Disabled unless you set use_exit_signal = True.
        """
        dataframe["exit_long"] = 0
        dataframe["exit_tag"] = None

        ma_sell = dataframe["ma_sell"]

        exit_tp_rollover = (
            (dataframe["close"] > ma_sell * self.high_offset.value)
            & (dataframe["rsi_fast"] < dataframe["rsi_slow"])
            & (dataframe["rsi"] > 50)
            & (dataframe["volume"] > 0)
        )

        dataframe.loc[exit_tp_rollover, ["exit_long", "exit_tag"]] = [1, "tp_rollover"]
        return dataframe
