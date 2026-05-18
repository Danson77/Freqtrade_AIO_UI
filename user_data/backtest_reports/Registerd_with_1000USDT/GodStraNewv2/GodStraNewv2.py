# GodStraNew Strategy
# Author: @Mablue (Masoud Azizi)
# github: https://github.com/mablue/
# freqtrade hyperopt --hyperopt-loss SharpeHyperOptLoss --spaces buy roi trailing sell --strategy GodStraNew

from functools import reduce
import numpy as np
import talib.abstract as ta
import freqtrade.vendor.qtpylib.indicators as qtpylib
from freqtrade.strategy import CategoricalParameter, DecimalParameter
from freqtrade.strategy.interface import IStrategy
from pandas import DataFrame
import pandas as pd


#  TODO: this gene is removed 'MAVP' cuz or error on periods
all_god_genes = {
    'Overlap Studies': {
        'BBANDS-0',             # Bollinger Bands
        'BBANDS-1',             # Bollinger Bands
        'BBANDS-2',             # Bollinger Bands
        'DEMA',                 # Double Exponential Moving Average
        'EMA',                  # Exponential Moving Average
        'HT_TRENDLINE',         # Hilbert Transform - Instantaneous Trendline
        'KAMA',                 # Kaufman Adaptive Moving Average
        'MA',                   # Moving average
        'MAMA-0',               # MESA Adaptive Moving Average
        'MAMA-1',               # MESA Adaptive Moving Average
        # TODO: Fix this
        # 'MAVP',               # Moving average with variable period
        'MIDPOINT',             # MidPoint over period
        'MIDPRICE',             # Midpoint Price over period
        'SAR',                  # Parabolic SAR
        'SAREXT',               # Parabolic SAR - Extended
        'SMA',                  # Simple Moving Average
        'T3',                   # Triple Exponential Moving Average (T3)
        'TEMA',                 # Triple Exponential Moving Average
        'TRIMA',                # Triangular Moving Average
        'WMA',                  # Weighted Moving Average
    },
    'Momentum Indicators': {
        'ADX',                  # Average Directional Movement Index
        'ADXR',                 # Average Directional Movement Index Rating
        'APO',                  # Absolute Price Oscillator
        'AROON-0',              # Aroon
        'AROON-1',              # Aroon
        'AROONOSC',             # Aroon Oscillator
        'BOP',                  # Balance Of Power
        'CCI',                  # Commodity Channel Index
        'CMO',                  # Chande Momentum Oscillator
        'DX',                   # Directional Movement Index
        'MACD-0',               # Moving Average Convergence/Divergence
        'MACD-1',               # Moving Average Convergence/Divergence
        'MACD-2',               # Moving Average Convergence/Divergence
        'MACDEXT-0',            # MACD with controllable MA type
        'MACDEXT-1',            # MACD with controllable MA type
        'MACDEXT-2',            # MACD with controllable MA type
        'MACDFIX-0',            # Moving Average Convergence/Divergence Fix 12/26
        'MACDFIX-1',            # Moving Average Convergence/Divergence Fix 12/26
        'MACDFIX-2',            # Moving Average Convergence/Divergence Fix 12/26
        'MFI',                  # Money Flow Index
        'MINUS_DI',             # Minus Directional Indicator
        'MINUS_DM',             # Minus Directional Movement
        'MOM',                  # Momentum
        'PLUS_DI',              # Plus Directional Indicator
        'PLUS_DM',              # Plus Directional Movement
        'PPO',                  # Percentage Price Oscillator
        'ROC',                  # Rate of change : ((price/prevPrice)-1)*100
        # Rate of change Percentage: (price-prevPrice)/prevPrice
        'ROCP',
        'ROCR',                 # Rate of change ratio: (price/prevPrice)
        # Rate of change ratio 100 scale: (price/prevPrice)*100
        'ROCR100',
        'RSI',                  # Relative Strength Index
        'STOCH-0',              # Stochastic
        'STOCH-1',              # Stochastic
        'STOCHF-0',             # Stochastic Fast
        'STOCHF-1',             # Stochastic Fast
        'STOCHRSI-0',           # Stochastic Relative Strength Index
        'STOCHRSI-1',           # Stochastic Relative Strength Index
        # 1-day Rate-Of-Change (ROC) of a Triple Smooth EMA
        'TRIX',
        'ULTOSC',               # Ultimate Oscillator
        'WILLR',                # Williams' %R
    },
    'Volume Indicators': {
        'AD',                   # Chaikin A/D Line
        'ADOSC',                # Chaikin A/D Oscillator
        'OBV',                  # On Balance Volume
    },
    'Volatility Indicators': {
        'ATR',                  # Average True Range
        'NATR',                 # Normalized Average True Range
        'TRANGE',               # True Range
    },
    'Price Transform': {
        'AVGPRICE',             # Average Price
        'MEDPRICE',             # Median Price
        'TYPPRICE',             # Typical Price
        'WCLPRICE',             # Weighted Close Price
    },
    'Cycle Indicators': {
        'HT_DCPERIOD',          # Hilbert Transform - Dominant Cycle Period
        'HT_DCPHASE',           # Hilbert Transform - Dominant Cycle Phase
        'HT_PHASOR-0',          # Hilbert Transform - Phasor Components
        'HT_PHASOR-1',          # Hilbert Transform - Phasor Components
        'HT_SINE-0',            # Hilbert Transform - SineWave
        'HT_SINE-1',            # Hilbert Transform - SineWave
        'HT_TRENDMODE',         # Hilbert Transform - Trend vs Cycle Mode
    },
    'Pattern Recognition': {
        'CDL2CROWS',            # Two Crows
        'CDL3BLACKCROWS',       # Three Black Crows
        'CDL3INSIDE',           # Three Inside Up/Down
        'CDL3LINESTRIKE',       # Three-Line Strike
        'CDL3OUTSIDE',          # Three Outside Up/Down
        'CDL3STARSINSOUTH',     # Three Stars In The South
        'CDL3WHITESOLDIERS',    # Three Advancing White Soldiers
        'CDLABANDONEDBABY',     # Abandoned Baby
        'CDLADVANCEBLOCK',      # Advance Block
        'CDLBELTHOLD',          # Belt-hold
        'CDLBREAKAWAY',         # Breakaway
        'CDLCLOSINGMARUBOZU',   # Closing Marubozu
        'CDLCONCEALBABYSWALL',  # Concealing Baby Swallow
        'CDLCOUNTERATTACK',     # Counterattack
        'CDLDARKCLOUDCOVER',    # Dark Cloud Cover
        'CDLDOJI',              # Doji
        'CDLDOJISTAR',          # Doji Star
        'CDLDRAGONFLYDOJI',     # Dragonfly Doji
        'CDLENGULFING',         # Engulfing Pattern
        'CDLEVENINGDOJISTAR',   # Evening Doji Star
        'CDLEVENINGSTAR',       # Evening Star
        'CDLGAPSIDESIDEWHITE',  # Up/Down-gap side-by-side white lines
        'CDLGRAVESTONEDOJI',    # Gravestone Doji
        'CDLHAMMER',            # Hammer
        'CDLHANGINGMAN',        # Hanging Man
        'CDLHARAMI',            # Harami Pattern
        'CDLHARAMICROSS',       # Harami Cross Pattern
        'CDLHIGHWAVE',          # High-Wave Candle
        'CDLHIKKAKE',           # Hikkake Pattern
        'CDLHIKKAKEMOD',        # Modified Hikkake Pattern
        'CDLHOMINGPIGEON',      # Homing Pigeon
        'CDLIDENTICAL3CROWS',   # Identical Three Crows
        'CDLINNECK',            # In-Neck Pattern
        'CDLINVERTEDHAMMER',    # Inverted Hammer
        'CDLKICKING',           # Kicking
        'CDLKICKINGBYLENGTH',   # Kicking - bull/bear determined by the longer marubozu
        'CDLLADDERBOTTOM',      # Ladder Bottom
        'CDLLONGLEGGEDDOJI',    # Long Legged Doji
        'CDLLONGLINE',          # Long Line Candle
        'CDLMARUBOZU',          # Marubozu
        'CDLMATCHINGLOW',       # Matching Low
        'CDLMATHOLD',           # Mat Hold
        'CDLMORNINGDOJISTAR',   # Morning Doji Star
        'CDLMORNINGSTAR',       # Morning Star
        'CDLONNECK',            # On-Neck Pattern
        'CDLPIERCING',          # Piercing Pattern
        'CDLRICKSHAWMAN',       # Rickshaw Man
        'CDLRISEFALL3METHODS',  # Rising/Falling Three Methods
        'CDLSEPARATINGLINES',   # Separating Lines
        'CDLSHOOTINGSTAR',      # Shooting Star
        'CDLSHORTLINE',         # Short Line Candle
        'CDLSPINNINGTOP',       # Spinning Top
        'CDLSTALLEDPATTERN',    # Stalled Pattern
        'CDLSTICKSANDWICH',     # Stick Sandwich
        # Takuri (Dragonfly Doji with very long lower shadow)
        'CDLTAKURI',
        'CDLTASUKIGAP',         # Tasuki Gap
        'CDLTHRUSTING',         # Thrusting Pattern
        'CDLTRISTAR',           # Tristar Pattern
        'CDLUNIQUE3RIVER',      # Unique 3 River
        'CDLUPSIDEGAP2CROWS',   # Upside Gap Two Crows
        'CDLXSIDEGAP3METHODS',  # Upside/Downside Gap Three Methods

    },
    'Statistic Functions': {
        'BETA',                 # Beta
        'CORREL',               # Pearson's Correlation Coefficient (r)
        'LINEARREG',            # Linear Regression
        'LINEARREG_ANGLE',      # Linear Regression Angle
        'LINEARREG_INTERCEPT',  # Linear Regression Intercept
        'LINEARREG_SLOPE',      # Linear Regression Slope
        'STDDEV',               # Standard Deviation
        'TSF',                  # Time Series Forecast
        'VAR',                  # Variance
    }

}

# Starting with only SMA selected as example
god_genes = {'SMA'}

timeperiods = [5, 6, 12, 15, 50, 55, 100, 110]

# number of candles to check up,don,off trend.
TREND_CHECK_CANDLES = 4
DECIMALS = 1

operators = [
    "D",  # Disabled gene
    ">",  # Indicator, bigger than cross indicator
    "<",  # Indicator, smaller than cross indicator
    "=",  # Indicator, equal with cross indicator
    "C",  # Indicator, crossed the cross indicator
    "CA",  # Indicator, crossed above the cross indicator
    "CB",  # Indicator, crossed below the cross indicator
    ">R",  # Normalized indicator, bigger than real number
    "=R",  # Normalized indicator, equal with real number
    "<R",  # Normalized indicator, smaller than real number
    "/>R",  # Normalized indicator devided to cross indicator, bigger than real number
    "/=R",  # Normalized indicator devided to cross indicator, equal with real number
    "/<R",  # Normalized indicator devided to cross indicator, smaller than real number
    "UT",  # Indicator, is in UpTrend status
    "DT",  # Indicator, is in DownTrend status
    "OT",  # Indicator, is in Off trend status(RANGE)
    "CUT",  # Indicator, Entered to UpTrend status
    "CDT",  # Indicator, Entered to DownTrend status
    "COT"  # Indicator, Entered to Off trend status(RANGE)
]

god_genes = set()
########################### SETTINGS ##############################

god_genes = {'SMA'}
# god_genes |= all_god_genes['Overlap Studies']
# god_genes |= all_god_genes['Momentum Indicators']
# god_genes |= all_god_genes['Volume Indicators']
# god_genes |= all_god_genes['Volatility Indicators']
# god_genes |= all_god_genes['Price Transform']
# god_genes |= all_god_genes['Cycle Indicators']
# god_genes |= all_god_genes['Pattern Recognition']
# god_genes |= all_god_genes['Statistic Functions']

timeperiods = [5, 6, 12, 15, 50, 55, 100, 110]
operators = [
    "D",  # Disabled gene
    ">",  # Indicator, bigger than cross indicator
    "<",  # Indicator, smaller than cross indicator
    "=",  # Indicator, equal with cross indicator
    "C",  # Indicator, crossed the cross indicator
    "CA",  # Indicator, crossed above the cross indicator
    "CB",  # Indicator, crossed below the cross indicator
    ">R",  # Normalized indicator, bigger than real number
    "=R",  # Normalized indicator, equal with real number
    "<R",  # Normalized indicator, smaller than real number
    "/>R",  # Normalized indicator devided to cross indicator, bigger than real number
    "/=R",  # Normalized indicator devided to cross indicator, equal with real number
    "/<R",  # Normalized indicator devided to cross indicator, smaller than real number
    "UT",  # Indicator, is in UpTrend status
    "DT",  # Indicator, is in DownTrend status
    "OT",  # Indicator, is in Off trend status(RANGE)
    "CUT",  # Indicator, Entered to UpTrend status
    "CDT",  # Indicator, Entered to DownTrend status
    "COT"  # Indicator, Entered to Off trend status(RANGE)
]
########################### END SETTINGS ##########################
# DATAFRAME = DataFrame()

# number of candles to check up,don,off trend.
TREND_CHECK_CANDLES = 4
DECIMALS = 1

# === Normalize Utility === #
def normalize(series: pd.Series) -> pd.Series:
    return (series - series.min()) / (series.max() - series.min())

# === Generate Indicator List with Time Periods === #
# Ensures all indicator + timeperiod combinations exist
god_genes = list(god_genes)
# print('selected indicators for optimzatin: \n', god_genes)
god_genes_with_timeperiod = [f"{g}-{t}" for g in god_genes for t in timeperiods]

# === Ensure enough items for categorical parameters === #
# If any list has only one item, repeat it to avoid CategoricalParameter issues
if len(god_genes) == 1:
    god_genes *= 2
if len(timeperiods) == 1:
    timeperiods *= 2
if len(operators) == 1:
    operators *= 2
########################################################################################################################################################
# === Gene Calculator === #
########################################################################################################################################################
def gene_calculator(dataframe: pd.DataFrame, indicator: str) -> pd.Series:
    try:
        if indicator.startswith("CDL"):
            # Candle patterns must be single-output series (CDLXXXXXXX-0)
            parts = indicator.split("-")
            if len(parts) > 1:
                parts[1] = "0"
                indicator = "-".join(parts)

        if indicator in dataframe.columns:
            return dataframe[indicator]

        parts = indicator.split("-")
        name = parts[0]

        if len(parts) == 1:
            dataframe[indicator] = normalize(getattr(ta, name)(dataframe))
        elif len(parts) == 2:
            timeperiod = int(parts[1])
            dataframe[indicator] = normalize(getattr(ta, name)(dataframe, timeperiod=timeperiod))
        elif len(parts) == 3:
            index = int(parts[1])
            timeperiod = int(parts[2])
            result = getattr(ta, name)(dataframe, timeperiod=timeperiod).iloc[:, index]
            dataframe[indicator] = normalize(result)
        elif len(parts) == 4:
            # Special: Indicator with SMA smoothing
            timeperiod = int(parts[1])
            base = f"{name}-{timeperiod}"
            if base not in dataframe.columns:
                dataframe[base] = getattr(ta, name)(dataframe, timeperiod=timeperiod)
            dataframe[indicator] = normalize(ta.SMA(dataframe[base].fillna(0), TREND_CHECK_CANDLES))
        elif len(parts) == 5:
            index = int(parts[1])
            timeperiod = int(parts[2])
            base = f"{name}-{index}-{timeperiod}"
            if base not in dataframe.columns:
                dataframe[base] = getattr(ta, name)(dataframe, timeperiod=timeperiod).iloc[:, index]
            dataframe[indicator] = normalize(ta.SMA(dataframe[base].fillna(0), TREND_CHECK_CANDLES))
        else:
            return pd.Series(False, index=dataframe.index)

        return dataframe[indicator]

    except Exception as e:
        print(f"[gene_calculator] Error with '{indicator}': {e}")
        return pd.Series(False, index=dataframe.index)
########################################################################################################################################################
# === Condition Generator === #
########################################################################################################################################################
def condition_generator(dataframe, operator, indicator, crossed_indicator, real_num):
    condition = (dataframe['volume'] > 10)

    # Calculate indicators
    dataframe[indicator] = gene_calculator(dataframe, indicator)
    dataframe[crossed_indicator] = gene_calculator(dataframe, crossed_indicator)

    # Calculate trend smoothed version if needed
    trend_key = f"{indicator}-SMA-{TREND_CHECK_CANDLES}"
    if operator in {"UT", "DT", "OT", "CUT", "CDT", "COT"}:
        dataframe[trend_key] = gene_calculator(dataframe, trend_key)

    # Core logical operations
    if operator == ">":
        condition &= dataframe[indicator] > dataframe[crossed_indicator]
    elif operator == "<":
        condition &= dataframe[indicator] < dataframe[crossed_indicator]
    elif operator == "=":
        condition &= np.isclose(dataframe[indicator], dataframe[crossed_indicator])
    elif operator == "C":
        condition &= qtpylib.crossed_above(dataframe[indicator], dataframe[crossed_indicator]) | qtpylib.crossed_below(dataframe[indicator], dataframe[crossed_indicator])
    elif operator == "CA":
        condition &= qtpylib.crossed_above(dataframe[indicator], dataframe[crossed_indicator])
    elif operator == "CB":
        condition &= qtpylib.crossed_below(dataframe[indicator], dataframe[crossed_indicator])
    elif operator == ">R":
        condition &= dataframe[indicator] > real_num
    elif operator == "<R":
        condition &= dataframe[indicator] < real_num
    elif operator == "=R":
        condition &= np.isclose(dataframe[indicator], real_num)
    elif operator == "/>R":
        condition &= dataframe[indicator].div(dataframe[crossed_indicator]) > real_num
    elif operator == "/<R":
        condition &= dataframe[indicator].div(dataframe[crossed_indicator]) < real_num
    elif operator == "/=R":
        condition &= np.isclose(dataframe[indicator].div(dataframe[crossed_indicator]), real_num)
    elif operator == "UT":
        condition &= dataframe[indicator] > dataframe[trend_key]
    elif operator == "DT":
        condition &= dataframe[indicator] < dataframe[trend_key]
    elif operator == "OT":
        condition &= np.isclose(dataframe[indicator], dataframe[trend_key])
    elif operator == "CUT":
        condition &= qtpylib.crossed_above(dataframe[indicator], dataframe[trend_key]) & (dataframe[indicator] > dataframe[trend_key])
    elif operator == "CDT":
        condition &= qtpylib.crossed_below(dataframe[indicator], dataframe[trend_key]) & (dataframe[indicator] < dataframe[trend_key])
    elif operator == "COT":
        condition &= (
            qtpylib.crossed_above(dataframe[indicator], dataframe[trend_key]) |
            qtpylib.crossed_below(dataframe[indicator], dataframe[trend_key])
        ) & np.isclose(dataframe[indicator], dataframe[trend_key])

    return condition, dataframe
########################################################################################################################################################
class GodStraNewv2(IStrategy):
########################################################################################################################################################
# Hyperopt
########################################################################################################################################################
    buy_params = {
        "buy_crossed_indicator0": "SMA-15",
        "buy_crossed_indicator1": "SMA-12",
        "buy_crossed_indicator2": "SMA-15",
        "buy_indicator0": "SMA-6",
        "buy_indicator1": "SMA-15",
        "buy_indicator2": "SMA-5",
        "buy_operator0": "<R",
        "buy_operator1": "D",
        "buy_operator2": "CB",
        "buy_real_num0": 0.2,
        "buy_real_num1": 1.0,
        "buy_real_num2": 0.7,
    }
    sell_params = {
        "sell_crossed_indicator0": "SMA-55",
        "sell_crossed_indicator1": "SMA-110",
        "sell_crossed_indicator2": "SMA-5",
        "sell_indicator0": "SMA-15",
        "sell_indicator1": "SMA-6",
        "sell_indicator2": "SMA-15",
        "sell_operator0": "CUT",
        "sell_operator1": "OT",
        "sell_operator2": "CB",
        "sell_real_num0": 0.3,
        "sell_real_num1": 0.4,
        "sell_real_num2": 0.3,
    }
########################################################################################################################################################
# Main
########################################################################################################################################################
    can_short = False

    minimal_roi = {
        "0": 0.13,
        "33": 0.075,
        "50": 0.034,
        "1440": 0.013
    }
    ignore_roi_if_entry_signal = True

    stoploss = -0.25
    use_custom_stoploss = False

    trailing_stop = True
    trailing_stop_positive = 0.339
    trailing_stop_positive_offset = 0.393
    trailing_only_offset_is_reached = False

    use_entry_signal = True
    use_custom_entry = False

    use_exit_signal = True
    use_custom_exit = False

    exit_profit_only = False
    exit_profit_offset = 0.01
########################################################################################################################################################
# Timeframe and order settings
########################################################################################################################################################
    timeframe = '5m'
    process_only_new_candles = True
    startup_candle_count = 0

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
    # Buy hyperopt params
    buy_crossed_indicator0 = CategoricalParameter(god_genes_with_timeperiod, default="ADD-20", space='buy')
    buy_crossed_indicator1 = CategoricalParameter(god_genes_with_timeperiod, default="ASIN-6", space='buy')
    buy_crossed_indicator2 = CategoricalParameter(god_genes_with_timeperiod, default="CDLEVENINGSTAR-50", space='buy')

    buy_indicator0 = CategoricalParameter(god_genes_with_timeperiod, default="SMA-100", space='buy')
    buy_indicator1 = CategoricalParameter(god_genes_with_timeperiod, default="WILLR-50", space='buy')
    buy_indicator2 = CategoricalParameter(god_genes_with_timeperiod, default="CDLHANGINGMAN-20", space='buy')

    buy_operator0 = CategoricalParameter(operators, default="/<R", space='buy')
    buy_operator1 = CategoricalParameter(operators, default="<R", space='buy')
    buy_operator2 = CategoricalParameter(operators, default="CB", space='buy')

    buy_real_num0 = DecimalParameter(0, 1, decimals=DECIMALS, default=0.89009, space='buy')
    buy_real_num1 = DecimalParameter(0, 1, decimals=DECIMALS, default=0.56953, space='buy')
    buy_real_num2 = DecimalParameter(0, 1, decimals=DECIMALS, default=0.38365, space='buy')

    # Sell hyperopt params
    sell_crossed_indicator0 = CategoricalParameter(god_genes_with_timeperiod, default="CDLSHOOTINGSTAR-150", space='sell')
    sell_crossed_indicator1 = CategoricalParameter(god_genes_with_timeperiod, default="MAMA-1-100", space='sell')
    sell_crossed_indicator2 = CategoricalParameter(god_genes_with_timeperiod, default="CDLMATHOLD-6", space='sell')

    sell_indicator0 = CategoricalParameter(god_genes_with_timeperiod, default="CDLUPSIDEGAP2CROWS-5", space='sell')
    sell_indicator1 = CategoricalParameter(god_genes_with_timeperiod, default="CDLHARAMICROSS-150", space='sell')
    sell_indicator2 = CategoricalParameter(god_genes_with_timeperiod, default="CDL2CROWS-5", space='sell')

    sell_operator0 = CategoricalParameter(operators, default="<R", space='sell')
    sell_operator1 = CategoricalParameter(operators, default="D", space='sell')
    sell_operator2 = CategoricalParameter(operators, default="/>R", space='sell')

    sell_real_num0 = DecimalParameter(0, 1, decimals=DECIMALS, default=0.09731, space='sell')
    sell_real_num1 = DecimalParameter(0, 1, decimals=DECIMALS, default=0.81657, space='sell')
    sell_real_num2 = DecimalParameter(0, 1, decimals=DECIMALS, default=0.87267, space='sell')
########################################################################################################################################################
# Infromative
########################################################################################################################################################
    def _generate_conditions(self, dataframe: DataFrame, prefix: str = 'buy'):
        """Helper to generate conditions for buy/sell based on parameter sets."""
        conditions = []
        for i in range(3):
            indicator = getattr(self, f"{prefix}_indicator{i}").value
            crossed_indicator = getattr(self, f"{prefix}_crossed_indicator{i}").value
            operator = getattr(self, f"{prefix}_operator{i}").value
            real_num = getattr(self, f"{prefix}_real_num{i}").value
            condition, dataframe = condition_generator(dataframe, operator, indicator, crossed_indicator, real_num)
            conditions.append(condition)
        return conditions, dataframe
########################################################################################################################################################
# Indicators
########################################################################################################################################################
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        It's good to calculate all indicators in all time periods here and so optimize the strategy.
        But this strategy can take much time to generate anything that may not use in his optimization.
        I just calculate the specific indicators in specific time period inside buy and sell strategy populator methods if needed.
        Also, this method (populate_indicators) just calculates default value of hyperoptable params
        so using this method have not big benefits instade of calculating useable things inside buy and sell trand populators
        """
        # Skipping bulk indicator calculations for speed; calculated on demand
        return dataframe
########################################################################################################################################################
# Entry
########################################################################################################################################################
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        conditions = []
    
        # === Entry Condition 0 ===
        buy_indicator = self.buy_indicator0.value
        buy_crossed_indicator = self.buy_crossed_indicator0.value
        buy_operator = self.buy_operator0.value
        buy_real_num = self.buy_real_num0.value
    
        condition, dataframe = condition_generator(
            dataframe,
            buy_operator,
            buy_indicator,
            buy_crossed_indicator,
            buy_real_num
        )
        conditions.append(condition)
    
        # === Entry Condition 1 ===
        buy_indicator = self.buy_indicator1.value
        buy_crossed_indicator = self.buy_crossed_indicator1.value
        buy_operator = self.buy_operator1.value
        buy_real_num = self.buy_real_num1.value
    
        condition, dataframe = condition_generator(
            dataframe,
            buy_operator,
            buy_indicator,
            buy_crossed_indicator,
            buy_real_num
        )
        conditions.append(condition)
    
        # === Entry Condition 2 ===
        buy_indicator = self.buy_indicator2.value
        buy_crossed_indicator = self.buy_crossed_indicator2.value
        buy_operator = self.buy_operator2.value
        buy_real_num = self.buy_real_num2.value
    
        condition, dataframe = condition_generator(
            dataframe,
            buy_operator,
            buy_indicator,
            buy_crossed_indicator,
            buy_real_num
        )
        conditions.append(condition)
    
        # === Entry Signal with Tag ===
        if conditions:
            entry_mask = reduce(lambda x, y: x & y, conditions)
            dataframe.loc[entry_mask, 'enter_long'] = 1
            dataframe.loc[entry_mask, 'enter_tag'] = 'BUY_TAG_0_1_2'
    
        return dataframe
########################################################################################################################################################
# Exit
########################################################################################################################################################
    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        conditions = []

        # === Exit Condition 0 ===
        sell_indicator = self.sell_indicator0.value
        sell_crossed_indicator = self.sell_crossed_indicator0.value
        sell_operator = self.sell_operator0.value
        sell_real_num = self.sell_real_num0.value

        condition, dataframe = condition_generator(
            dataframe,
            sell_operator,
            sell_indicator,
            sell_crossed_indicator,
            sell_real_num
        )
        conditions.append(condition)

        # === Exit Condition 1 ===
        sell_indicator = self.sell_indicator1.value
        sell_crossed_indicator = self.sell_crossed_indicator1.value
        sell_operator = self.sell_operator1.value
        sell_real_num = self.sell_real_num1.value

        condition, dataframe = condition_generator(
            dataframe,
            sell_operator,
            sell_indicator,
            sell_crossed_indicator,
            sell_real_num
        )
        conditions.append(condition)

        # === Exit Condition 2 ===
        sell_indicator = self.sell_indicator2.value
        sell_crossed_indicator = self.sell_crossed_indicator2.value
        sell_operator = self.sell_operator2.value
        sell_real_num = self.sell_real_num2.value

        condition, dataframe = condition_generator(
            dataframe,
            sell_operator,
            sell_indicator,
            sell_crossed_indicator,
            sell_real_num
        )
        conditions.append(condition)

        # === Exit Signal with Tag ===
        if conditions:
            exit_mask = reduce(lambda x, y: x & y, conditions)
            dataframe.loc[exit_mask, 'exit_long'] = 1
            dataframe.loc[exit_mask, 'exit_tag'] = 'SELL_TAG_0_1_2'

        return dataframe