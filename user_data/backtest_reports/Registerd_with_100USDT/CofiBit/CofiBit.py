# --- Do not remove these libs ---
import freqtrade.vendor.qtpylib.indicators as qtpylib
import talib.abstract as ta
from freqtrade.strategy.interface import IStrategy
from pandas import DataFrame
from datetime import datetime
# --- Do not remove these libs ---


class CofiBit(IStrategy):
    can_short = False
    timeframe = "5m"
    process_only_new_candles = True
    startup_candle_count = 300  # needs EMA200 stable

    minimal_roi = {
        "40": 0.05,
        "30": 0.06,
        "20": 0.07,
        "0": 0.10,
    }

    # Make this less suicidal. -25% is what caused your stoploss nukes.
    stoploss = -0.12

    trailing_stop = True
    trailing_stop_positive = 0.001
    trailing_stop_positive_offset = 0.01
    trailing_only_offset_is_reached = True

    use_entry_signal = True
    use_exit_signal = True
    exit_profit_only = True
    exit_profit_offset = 0.01  # 0.03 is quite high, it delays profit exits unnecessarily

    # If you use custom_exit, set this True.
    use_custom_stoploss = False

    def informative_pairs(self):
        return []

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        stoch_fast = ta.STOCHF(dataframe, 5, 3, 0, 3, 0)
        dataframe["fastd"] = stoch_fast["fastd"]
        dataframe["fastk"] = stoch_fast["fastk"]

        dataframe["ema_high"] = ta.EMA(dataframe, timeperiod=5, price="high")
        dataframe["ema_close"] = ta.EMA(dataframe, timeperiod=5, price="close")
        dataframe["ema_low"] = ta.EMA(dataframe, timeperiod=5, price="low")

        dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)

        # Regime filter
        dataframe["ema200"] = ta.EMA(dataframe, timeperiod=200, price="close")
        dataframe["ema200_slope"] = dataframe["ema200"].diff()

        # Volatility filter
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["atr_pct"] = dataframe["atr"] / dataframe["close"]

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["enter_long"] = 0

        # Regime: only longs when above EMA200 and EMA200 not falling
        regime_ok = (
            (dataframe["close"] > dataframe["ema200"]) &
            (dataframe["ema200_slope"] >= 0)
        )

        # Avoid extreme volatility dumps
        vol_ok = (dataframe["atr_pct"] < 0.02)  # tune per market; 2% is a reasonable start

        # Dip + reclaim rather than "open < ema_low"
        dip_reclaim = (
            (dataframe["low"] < dataframe["ema_low"]) &
            (dataframe["close"] > dataframe["ema_low"])
        )

        stoch_signal = (
            qtpylib.crossed_above(dataframe["fastk"], dataframe["fastd"]) &
            (dataframe["fastk"] < 25) &
            (dataframe["fastd"] < 25)
        )

        # ADX window: trend exists but not mega-exhausted
        trend_ok = (dataframe["adx"] > 18) & (dataframe["adx"] < 45)

        entry_cond = (
            (dataframe["volume"] > 0) &
            regime_ok &
            vol_ok &
            dip_reclaim &
            stoch_signal &
            trend_ok
        )

        dataframe.loc[entry_cond, "enter_long"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0

        # Exit signals remain, but profit-only will control them.
        exit_cond = (
            (dataframe["volume"] > 0) &
            (
                (dataframe["close"] >= dataframe["ema_high"]) |
                (qtpylib.crossed_above(dataframe["fastk"], 75)) |
                (qtpylib.crossed_above(dataframe["fastd"], 75))
            )
        )

        dataframe.loc[exit_cond, "exit_long"] = 1
        return dataframe

    def custom_exit(self, pair: str, trade, current_time: datetime, current_rate: float,
                    current_profit: float, **kwargs):
        """
        Kill dead trades that would otherwise drift for days and slam stoploss.
        This is the biggest improvement after profit-only exits.
        """
        # minutes in trade
        dur_min = (current_time - trade.open_date_utc).total_seconds() / 60.0

        # Cut losers early: still red after 12 hours
        if dur_min > 12 * 60 and current_profit < -0.01:
            return "time_stop_-1pct"

        # Cut harder: still red after 48 hours
        if dur_min > 48 * 60 and current_profit < -0.005:
            return "time_stop_48h"

        return None
