# Standard Library Imports
from datetime import datetime, timedelta
from functools import reduce
from typing import Dict, List
import datetime

# Third-party Libraries
import numpy as np
import pandas as pd
import talib.abstract as ta

# Freqtrade and Technical Analysis
import freqtrade.vendor.qtpylib.indicators as qtpylib
from pandas import DataFrame
from technical.util import resample_to_interval, resampled_merge
import technical.indicators as ftt
from freqtrade.persistence import Trade
from freqtrade.strategy import (
    IStrategy,
    stoploss_from_open,
    merge_informative_pair,
    DecimalParameter,
    IntParameter,
    CategoricalParameter,
)
########################################################################################################################################################
def EWO(dataframe, ema_length=5, ema2_length=35):
    df = dataframe.copy()
    ema1 = ta.SMA(df, timeperiod=ema_length)
    ema2 = ta.SMA(df, timeperiod=ema2_length)
    emadif = (ema1 - ema2) / df['close'] * 100
    return emadif
########################################################################################################################################################
class DS_Liot_SMA_5m(IStrategy):
########################################################################################################################################################
# Hyperopt
########################################################################################################################################################
    buy_params = {
        "base_nb_candles_buy": 6,#22
        "ewo_high": 9.513,#3.71
        "ewo_low": -8.077,
        "low_offset": 0.93, #0.975, # 0.918,
        "rsi_buy": 58,
    }
    sell_params = {
        "base_nb_candles_sell": 43,
        "high_offset": 1.022
    }
########################################################################################################################################################
# Main
########################################################################################################################################################
    can_short = False

    minimal_roi = {
        "0": 0.215,
        "40": 0.132,
        "87": 0.086,
        "201": 0.03
    }
    ignore_roi_if_entry_signal = True

    stoploss = -0.25
    use_custom_stoploss = False

    trailing_stop = True
    trailing_stop_positive = 0.005
    trailing_stop_positive_offset = 0.03
    trailing_only_offset_is_reached = True

    use_entry_signal = True
    use_custom_entry = False

    use_exit_signal = True
    use_custom_exit = True

    exit_profit_only = False
    exit_profit_offset = 0.01
########################################################################################################################################################
# Main
########################################################################################################################################################
    timeframe = '5m'
    inf_1h = '1h'
    informative_timeframe = '1h'
    process_only_new_candles = True
    startup_candle_count = 300

    order_types = {
        'entry': 'market',
        'exit': 'market',
        'trailing_stop_loss': 'market',
        'emergency_exit': 'market',
        'force_entry': 'market',
        'force_exit': 'market',
        'stoploss': 'market',
        'stoploss_on_exchange': True,
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
# Parameters
########################################################################################################################################################
    fast_ewo = 50
    slow_ewo = 200
    # Buy_params
    is_optimize_buy = False
    base_nb_candles_buy = IntParameter(5, 80, default=buy_params['base_nb_candles_buy'], space='buy', optimize=is_optimize_buy)
    ewo_low = DecimalParameter(-20.0, -8.0, default=buy_params['ewo_low'], space='buy', optimize=is_optimize_buy)
    ewo_high = DecimalParameter(2.0, 12.0, default=buy_params['ewo_high'], space='buy', optimize=is_optimize_buy)
    rsi_buy = IntParameter(30, 70, default=buy_params['rsi_buy'], space='buy', optimize=is_optimize_buy)
    low_offset = DecimalParameter(0.800, 1.000, default=buy_params['low_offset'], space='buy', optimize=True)
    # Sell_params
    is_optimize_sell = True
    base_nb_candles_sell = IntParameter(5, 80, default=sell_params['base_nb_candles_sell'], space='sell', optimize=is_optimize_sell)
    high_offset = DecimalParameter(0.99, 1.1, default=sell_params['high_offset'], space='sell', optimize=is_optimize_sell)
############################################################################################################################################################################
# Informative
############################################################################################################################################################################
    def informative_pairs(self):
        pairs = self.dp.current_whitelist()
        informative_pairs = [(pair, self.informative_timeframe) for pair in pairs]
        return informative_pairs

    def get_informative_indicators(self, metadata: dict):
        dataframe = self.dp.get_pair_dataframe(pair=metadata['pair'], timeframe=self.informative_timeframe)
        return dataframe    
########################################################################################################################################################
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
            dataframe['adx'] = ta.ADX(dataframe)
            dataframe['plus_dm'] = ta.PLUS_DM(dataframe)
            dataframe['plus_di'] = ta.PLUS_DI(dataframe)
            dataframe['minus_dm'] = ta.MINUS_DM(dataframe)
            dataframe['minus_di'] = ta.MINUS_DI(dataframe)

            aroon = ta.AROON(dataframe)
            dataframe['aroonup'] = aroon['aroonup']
            dataframe['aroondown'] = aroon['aroondown']
            dataframe['aroonosc'] = ta.AROONOSC(dataframe)
            dataframe['ao'] = qtpylib.awesome_oscillator(dataframe)

            keltner = qtpylib.keltner_channel(dataframe)
            dataframe["kc_upperband"] = keltner["upper"]
            dataframe["kc_lowerband"] = keltner["lower"]
            dataframe["kc_middleband"] = keltner["mid"]
            dataframe["kc_percent"] = ((dataframe["close"] - dataframe["kc_lowerband"]) / (dataframe["kc_upperband"] - dataframe["kc_lowerband"]))
            dataframe["kc_width"] = ((dataframe["kc_upperband"] - dataframe["kc_lowerband"]) / dataframe["kc_middleband"])

            dataframe['uo'] = ta.ULTOSC(dataframe)
            dataframe['cci'] = ta.CCI(dataframe)

            dataframe['EWO'] = EWO(dataframe, self.fast_ewo, self.slow_ewo)

            dataframe['rsi'] = ta.RSI(dataframe)
            dataframe['rsi_fast'] = ta.RSI(dataframe)
            dataframe['rsi_slow'] = ta.RSI(dataframe)

            rsi = 0.1 * (dataframe['rsi'] - 50)
            dataframe['fisher_rsi'] = (np.exp(2 * rsi) - 1) / (np.exp(2 * rsi) + 1)
            dataframe['fisher_rsi_norma'] = 50 * (dataframe['fisher_rsi'] + 1)

            stoch = ta.STOCH(dataframe)
            dataframe['slowd'] = stoch['slowd']
            dataframe['slowk'] = stoch['slowk']

            stoch_fast = ta.STOCHF(dataframe)
            dataframe['fastd'] = stoch_fast['fastd']
            dataframe['fastk'] = stoch_fast['fastk']

            stoch_rsi = ta.STOCHRSI(dataframe)
            dataframe['fastd_rsi'] = stoch_rsi['fastd']
            dataframe['fastk_rsi'] = stoch_rsi['fastk']

            macd = ta.MACD(dataframe)
            dataframe['macd'] = macd['macd']
            dataframe['macdsignal'] = macd['macdsignal']
            dataframe['macdhist'] = macd['macdhist']

            dataframe['mfi'] = ta.MFI(dataframe)
            dataframe['roc'] = ta.ROC(dataframe)

            bollinger = qtpylib.bollinger_bands(qtpylib.typical_price(dataframe), window=20, stds=2)
            dataframe['bb_lowerband'] = bollinger['lower']
            dataframe['bb_middleband'] = bollinger['mid']
            dataframe['bb_upperband'] = bollinger['upper']
            dataframe["bb_percent"] = ((dataframe["close"] - dataframe["bb_lowerband"]) / (dataframe["bb_upperband"] - dataframe["bb_lowerband"]))
            dataframe["bb_width"] = ((dataframe["bb_upperband"] - dataframe["bb_lowerband"]) / dataframe["bb_middleband"])

            dataframe['sar'] = ta.SAR(dataframe)
            dataframe['tema'] = ta.TEMA(dataframe, timeperiod=9)

            hilbert = ta.HT_SINE(dataframe)
            dataframe['htsine'] = hilbert['sine']
            dataframe['htleadsine'] = hilbert['leadsine']

            dataframe['CDLHAMMER'] = ta.CDLHAMMER(dataframe)
            dataframe['CDLINVERTEDHAMMER'] = ta.CDLINVERTEDHAMMER(dataframe)
            dataframe['CDLDRAGONFLYDOJI'] = ta.CDLDRAGONFLYDOJI(dataframe)
            dataframe['CDLPIERCING'] = ta.CDLPIERCING(dataframe) # values [0, 100]
            dataframe['CDLMORNINGSTAR'] = ta.CDLMORNINGSTAR(dataframe) # values [0, 100]
            dataframe['CDL3WHITESOLDIERS'] = ta.CDL3WHITESOLDIERS(dataframe) # values [0, 100]

            dataframe['CDLHANGINGMAN'] = ta.CDLHANGINGMAN(dataframe)
            dataframe['CDLSHOOTINGSTAR'] = ta.CDLSHOOTINGSTAR(dataframe)
            dataframe['CDLGRAVESTONEDOJI'] = ta.CDLGRAVESTONEDOJI(dataframe)
            dataframe['CDLDARKCLOUDCOVER'] = ta.CDLDARKCLOUDCOVER(dataframe)
            dataframe['CDLEVENINGDOJISTAR'] = ta.CDLEVENINGDOJISTAR(dataframe)
            dataframe['CDLEVENINGSTAR'] = ta.CDLEVENINGSTAR(dataframe)

            dataframe['CDL3LINESTRIKE'] = ta.CDL3LINESTRIKE(dataframe)
            dataframe['CDLSPINNINGTOP'] = ta.CDLSPINNINGTOP(dataframe) # values [0, -100, 100]
            dataframe['CDLENGULFING'] = ta.CDLENGULFING(dataframe) # values [0, -100, 100]
            dataframe['CDLHARAMI'] = ta.CDLHARAMI(dataframe) # values [0, -100, 100]
            dataframe['CDL3OUTSIDE'] = ta.CDL3OUTSIDE(dataframe) # values [0, -100, 100]
            dataframe['CDL3INSIDE'] = ta.CDL3INSIDE(dataframe) # values [0, -100, 100]

            heikinashi = qtpylib.heikinashi(dataframe)
            dataframe['ha_open'] = heikinashi['open']
            dataframe['ha_close'] = heikinashi['close']
            dataframe['ha_high'] = heikinashi['high']
            dataframe['ha_low'] = heikinashi['low']

            # Collect EMA columns into dictionaries
            ema_buy_cols = {f'ma_buy_{val}': ta.EMA(dataframe, timeperiod=val) for val in self.base_nb_candles_buy.range}
            ema_sell_cols = {f'ma_sell_{val}': ta.EMA(dataframe, timeperiod=val) for val in self.base_nb_candles_sell.range}

            # Concatenate and merge with dataframe at once
            dataframe = pd.concat([dataframe, pd.DataFrame(ema_buy_cols, index=dataframe.index)], axis=1)
            dataframe = pd.concat([dataframe, pd.DataFrame(ema_sell_cols, index=dataframe.index)], axis=1)

            return dataframe
########################################################################################################################################################
# Enter Trade
########################################################################################################################################################
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Ensure 'enter_long' and 'enter_tag' columns exist
        dataframe['enter_long'] = 0
        dataframe['enter_tag'] = None

        # --- Condition 1: Strong EWO breakout ---
        condition_1 = (
            (dataframe['close'] < (dataframe[f'ma_buy_{self.base_nb_candles_buy.value}'] * self.low_offset.value)) &
            (dataframe['EWO'] > self.ewo_high.value) &
            (dataframe['rsi'] < self.rsi_buy.value) &
            (dataframe['volume'] > 0)
        )
        dataframe.loc[condition_1, ['enter_long', 'enter_tag']] = [1, 'condition_1']

        # --- EWO Setup 1: Moderate Signal ---
        ewo1 = (
            (dataframe['rsi_fast'] < 35) &
            (dataframe['close'] < (dataframe[f'ma_buy_{self.base_nb_candles_buy.value}'] * self.low_offset.value)) &
            (dataframe['EWO'] > self.ewo_high.value) &
            (dataframe['rsi'] < self.rsi_buy.value) &
            (dataframe['volume'] > 0) &
            (dataframe['close'] < (dataframe[f'ma_sell_{self.base_nb_candles_sell.value}'] * self.high_offset.value))
        )
        dataframe.loc[ewo1, ['enter_long', 'enter_tag']] = [1, 'ewo1']

        return dataframe
########################################################################################################################################################
# Exit Trade
########################################################################################################################################################
    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe['exit_long'] = 0
        dataframe['exit_tag'] = None

        # Dummy condition that never triggers
        dummy_exit = (
            (dataframe['volume'] < 0)  # volume can't be negative
        )
        dataframe.loc[dummy_exit, ['exit_long', 'exit_tag']] = [1, 'dummy']

        return dataframe
########################################################################################################################################################
# Custom to Sell unclog
########################################################################################################################################################
    def custom_exit(self, pair: str, trade: 'Trade', current_time: 'datetime', current_rate: float, current_profit: float, **kwargs):
        # Sell any positions at a loss if they are held for more than X days.
        if current_profit <= 0 and (current_time - trade.open_date_utc).days >= 10:
            return 'unclog'

        if current_profit >= 0 and (current_time - trade.open_date_utc).days >= 10:
            return 'unclog'