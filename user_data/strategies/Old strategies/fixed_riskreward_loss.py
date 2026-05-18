# Custom Stoploss Strategy
import numpy as np
import pandas as pd
from pandas import DataFrame
from freqtrade.strategy.interface import IStrategy
import talib.abstract as ta
import freqtrade.vendor.qtpylib.indicators as qtpylib
from datetime import datetime
from freqtrade.persistence import Trade
import logging

logger = logging.getLogger(__name__)


class FixedRiskRewardLoss(IStrategy):
    """
    This strategy uses custom_stoploss() to enforce a fixed risk/reward ratio
    """

    custom_info = {
        'risk_reward_ratio': 3.5,
        'set_to_break_even_at_profit': 1,
    }
    use_custom_stoploss = True
    stoploss = -0.9

    def custom_stoploss(self, pair: str, trade: 'Trade', current_time: datetime,
                        current_rate: float, current_profit: float, **kwargs) -> float:
        """
        Custom stoploss using a risk/reward ratio.
        """
        result = break_even_sl = takeprofit_sl = -1
        custom_info_pair = self.custom_info.get(pair)
        if custom_info_pair is not None:
            # Find the closest date to the trade's open date
            closest_date = custom_info_pair.index.asof(trade.open_date_utc)
            if pd.isnull(closest_date):  # No valid date found
                return -1  # Don't update the current stoploss
            
            open_df = custom_info_pair.loc[[closest_date]]

            # Ensure we have the data for the opening candle
            if open_df.empty:
                return -1  # Won't update the current stoploss

            initial_sl_abs = open_df['stoploss_rate'].iloc[0]

            # Calculate initial stoploss at open_date
            initial_sl = initial_sl_abs / current_rate - 1

            # Calculate take profit threshold
            risk_distance = trade.open_rate - initial_sl_abs
            reward_distance = risk_distance * self.custom_info['risk_reward_ratio']
            take_profit_price_abs = trade.open_rate + reward_distance
            take_profit_pct = take_profit_price_abs / trade.open_rate - 1

            # Break-even stoploss adjustment
            break_even_profit_distance = risk_distance * self.custom_info['set_to_break_even_at_profit']
            break_even_profit_pct = (break_even_profit_distance + current_rate) / current_rate - 1

            result = initial_sl
            if current_profit >= break_even_profit_pct:
                break_even_sl = (trade.open_rate * (1 + trade.fee_open + trade.fee_close) / current_rate) - 1
                result = break_even_sl

            if current_profit >= take_profit_pct:
                takeprofit_sl = take_profit_price_abs / current_rate - 1
                result = takeprofit_sl

        return result

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe['atr'] = ta.ATR(dataframe)
        dataframe['stoploss_rate'] = dataframe['close'] - (dataframe['atr'] * 2)
        self.custom_info[metadata['pair']] = dataframe[['date', 'stoploss_rate']].copy().set_index('date')
        return dataframe

    def populate_buy_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[:, 'buy'] = 1  # Always buys
        return dataframe

    def populate_sell_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[:, 'sell'] = 0  # Never sells
        return dataframe
