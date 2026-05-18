import re
import tkinter as tk
from tkinter import ttk, filedialog
from pathlib import Path
from typing import Dict, List, Tuple, Optional

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAS_DND = True
except Exception:
    DND_FILES = None
    TkinterDnD = None
    HAS_DND = False


ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
SECTION_START_RE = re.compile(r"BACKTESTING REPORT", re.IGNORECASE)
BACKTESTED_RE = re.compile(
    r"Backtested\s+(\d{4}-\d{2}-\d{2})\s+\d{2}:\d{2}:\d{2}\s*->\s*(\d{4}-\d{2}-\d{2})\s+\d{2}:\d{2}:\d{2}",
    re.IGNORECASE,
)
TIMERANGE_RE = re.compile(r"TIMERANGE\s+(\d{8}-\d{8})", re.IGNORECASE)

TIMERANGE_PREFIX_MAP = {
    "20240101-20240701": "W1",
    "20240701-20241001": "W2",
    "20241001-20251201": "W3",
    "20251001-20260410": "W4",
}

DATE_RANGE_PREFIX_MAP = {
    ("2024-01-01", "2024-07-01"): "W1",
    ("2024-07-01", "2024-10-01"): "W2",
    ("2024-10-01", "2025-12-01"): "W3",
    ("2025-10-01", "2026-04-10"): "W4",
}


def clean_text(text: str) -> str:
    text = ANSI_RE.sub("", text or "")
    return text.replace("−", "-").replace("\xa0", " ")


def clean_num(value: str) -> str:
    if value is None:
        return ""
    value = clean_text(value).strip()
    value = value.replace("USDT", "").replace("%", "").replace(",", "").strip()
    return value


def safe_float(value: str) -> Optional[float]:
    value = clean_num(value)
    if not value:
        return None
    try:
        return float(value)
    except Exception:
        return None


def float_str(value: Optional[float], decimals: int = 2) -> str:
    if value is None:
        return ""
    s = f"{value:.{decimals}f}"
    s = s.rstrip("0").rstrip(".") if "." in s else s
    return s


def read_text_file(filepath: str) -> str:
    filepath = filepath.strip()
    if not filepath:
        raise ValueError("Empty file path")

    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {filepath}")

    encodings = ["utf-8", "utf-8-sig", "cp1252", "latin-1"]
    last_error = None

    for enc in encodings:
        try:
            return path.read_text(encoding=enc)
        except Exception as e:
            last_error = e

    raise ValueError(f"Could not read file as text: {filepath}. Last error: {last_error}")


def split_pipe_line(line: str, keep_empty: bool = False) -> List[str]:
    sep = "│" if "│" in line else ("|" if "|" in line else None)
    if not sep:
        return []

    raw_parts = [part.strip() for part in line.split(sep)]

    if raw_parts and raw_parts[0] == "":
        raw_parts = raw_parts[1:]
    if raw_parts and raw_parts[-1] == "":
        raw_parts = raw_parts[:-1]

    if keep_empty:
        return raw_parts
    return [part for part in raw_parts if part != ""]


def extract_sections(full_text: str) -> List[str]:
    text = clean_text(full_text)
    starts = [m.start() for m in SECTION_START_RE.finditer(text)]
    if not starts:
        return []

    sections: List[str] = []
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(text)
        sections.append(text[start:end])
    return sections


def find_metric(section: str, metric_name: str) -> str:
    pattern = rf"│\s*{re.escape(metric_name)}\s*│\s*(.*?)\s*│"
    m = re.search(pattern, section, re.MULTILINE)
    return m.group(1).strip() if m else ""


def parse_expectancy(value: str) -> str:
    m = re.match(r"\s*([-+]?\d+(?:\.\d+)?)", clean_text(value))
    return m.group(1) if m else ""


def parse_trade_pct(value: str) -> str:
    m = re.search(r"([-+]?\d+(?:\.\d+)?)\s*%$", clean_text(value))
    return m.group(1) if m else ""


def parse_days_win_draw_lose(value: str) -> Tuple[str, str, str]:
    nums = re.findall(r"-?\d+", clean_text(value))
    if len(nums) >= 3:
        return nums[0], nums[1], nums[2]
    return "", "", ""


def parse_max_consecutive(value: str) -> Tuple[str, str]:
    nums = re.findall(r"-?\d+", clean_text(value))
    if len(nums) >= 2:
        return nums[0], nums[1]
    return "", ""


def duration_to_days(value: str) -> str:
    value = clean_text(value).strip()
    if not value:
        return ""

    value = re.sub(r"\s*,\s*", " ", value)
    value = re.sub(r"(?i)(\d)\s*days?", r"\1 days", value)
    value = re.sub(r"(?i)(\d)\s*day", r"\1 day", value)
    value = re.sub(r"\s+", " ", value).strip()

    m = re.search(r"(?i)^(?:(\d+)\s*days?\s*)?(\d{1,2}):(\d{2}):(\d{2})$", value)
    if not m:
        m = re.search(r"(?i)^(?:(\d+)days?)?(\d{1,2}):(\d{2}):(\d{2})$", value.replace(" ", ""))
        if not m:
            return value

    days = int(m.group(1)) if m.group(1) is not None else 0
    hh = m.group(2).zfill(2)
    mm = m.group(3).zfill(2)
    ss = m.group(4).zfill(2)

    return f"{days} days {hh}:{mm}:{ss}"


def parse_strategy_summary_row(section: str) -> Dict[str, str]:
    in_table = False

    for raw_line in section.splitlines():
        line = clean_text(raw_line)
        upper = line.upper()

        if "STRATEGY SUMMARY" in upper:
            in_table = True
            continue

        if not in_table or "│" not in line:
            continue

        if "Strategy" in line and "Trades" in line:
            continue

        if "TOTAL" in line:
            continue

        parts = split_pipe_line(line)
        if len(parts) < 8:
            continue

        strategy_name = parts[0]
        trades = clean_num(parts[1])

        if not re.fullmatch(r"\d+", trades):
            continue

        avg_profit_pct = clean_num(parts[2])
        total_profit_pct = clean_num(parts[4])
        avg_duration = duration_to_days(parts[5].strip())

        win_nums = re.findall(r"[-+]?\d+(?:\.\d+)?", parts[6])
        total_win = win_nums[0] if len(win_nums) > 0 else ""
        total_loss = win_nums[2] if len(win_nums) > 2 else ""
        winrate = win_nums[3] if len(win_nums) > 3 else ""

        drawdown_match = re.search(r"([-+]?\d+(?:\.\d+)?)\s*%$", parts[7])
        drawdown_pct = drawdown_match.group(1) if drawdown_match else ""

        return {
            "Strategy Name": strategy_name,
            "Trades": trades,
            "Avg Profit %": avg_profit_pct,
            "Total Profit %": total_profit_pct,
            "Total Win": total_win,
            "Total Loss": total_loss,
            "Winrate %": winrate,
            "Drawdown %": drawdown_pct,
            "Avg Trade Duration": avg_duration,
        }

    raise ValueError("Could not find STRATEGY SUMMARY row in one section.")


def normalize_reason(reason: str) -> str:
    r = clean_text(reason).strip().lower()
    r = r.replace("-", "_").replace(" ", "_")
    r = re.sub(r"_+", "_", r)
    return r


def is_roi_reason(r: str) -> bool:
    return r == "roi"


def is_force_exit_reason(r: str) -> bool:
    return r == "force_exit"


def is_trailing_reason(r: str) -> bool:
    return r in {"trailing_stop_loss", "trailingstoploss", "trailing_stop"}


def is_plain_stoploss_reason(r: str) -> bool:
    return r in {"stop_loss", "stoploss"}


def is_stoploss_family_reason(r: str) -> bool:
    stoploss_tokens = (
        "stoploss",
        "stop_loss",
        "sell_stoploss",
        "custom_stoploss",
        "signal_stoploss",
        "_stoploss_",
        "_stop_loss_",
        "deadfish",
    )
    return any(token in r for token in stoploss_tokens)


def is_plain_exit_signal_reason(r: str) -> bool:
    return r == "exit_signal"


def is_custom_exit_reason(r: str) -> bool:
    custom_prefixes = (
        "signal_profit",
        "custom_exit",
        "profit_",
        "tp_",
        "take_profit",
        "sell_",
    )
    if r.startswith(custom_prefixes):
        return True

    if "_profit_" in r or r.endswith("_profit"):
        return True

    if r.startswith("exit_") and r != "exit_signal":
        return True

    return False


def canonical_exit_reason(reason: str) -> str:
    r = normalize_reason(reason)

    if is_force_exit_reason(r):
        return "ignore"
    if is_roi_reason(r):
        return "roi"
    if is_trailing_reason(r):
        return "trailing_stop_loss"
    if is_plain_stoploss_reason(r) or is_stoploss_family_reason(r):
        return "stop_loss"
    if is_plain_exit_signal_reason(r):
        return "exit_signal"
    if is_custom_exit_reason(r):
        return "custom_exit_signal"

    return "custom_exit_signal"


def _empty_agg_bucket() -> Dict[str, float]:
    return {
        "trades": 0.0,
        "weighted_profit_sum": 0.0,
        "wins": 0.0,
        "draws": 0.0,
        "losses": 0.0,
    }


def _finalize_agg_rows(rows: Dict[str, Dict[str, float]]) -> Dict[str, Dict[str, str]]:
    result: Dict[str, Dict[str, str]] = {}

    for reason, vals in rows.items():
        trades = vals["trades"]
        wins = vals["wins"]
        avg_profit_pct = vals["weighted_profit_sum"] / trades if trades > 0 else None
        winrate = (wins / trades * 100.0) if trades > 0 else None

        result[reason] = {
            "trades": str(int(trades)) if float(trades).is_integer() else float_str(trades),
            "avg_profit_pct": float_str(avg_profit_pct),
            "winrate": float_str(winrate),
        }

    return result


def parse_exit_reason_stats(section: str) -> Dict[str, Dict[str, str]]:
    rows: Dict[str, Dict[str, float]] = {}
    in_table = False

    for raw_line in section.splitlines():
        line = clean_text(raw_line)
        upper = line.upper()

        if "EXIT REASON STATS" in upper:
            in_table = True
            continue

        if not in_table:
            continue

        if "MIXED TAG STATS" in upper or "SUMMARY METRICS" in upper:
            break

        if "│" not in line:
            continue

        if "Exit Reason" in line and "Exits" in line:
            continue

        parts = split_pipe_line(line)
        if len(parts) < 7:
            continue

        reason_raw = parts[0].strip()
        if reason_raw.upper() == "TOTAL":
            continue

        canonical = canonical_exit_reason(reason_raw)
        if canonical in {"ignore", "other"}:
            continue

        exits = safe_float(parts[1])
        avg_profit_pct = safe_float(parts[2])

        if exits is None or exits <= 0:
            continue

        wdl_nums = re.findall(r"[-+]?\d+(?:\.\d+)?", parts[6])
        wins = safe_float(wdl_nums[0]) if len(wdl_nums) > 0 else 0.0
        draws = safe_float(wdl_nums[1]) if len(wdl_nums) > 1 else 0.0
        losses = safe_float(wdl_nums[2]) if len(wdl_nums) > 2 else 0.0

        if canonical not in rows:
            rows[canonical] = _empty_agg_bucket()

        rows[canonical]["trades"] += exits
        rows[canonical]["weighted_profit_sum"] += (avg_profit_pct or 0.0) * exits
        rows[canonical]["wins"] += wins or 0.0
        rows[canonical]["draws"] += draws or 0.0
        rows[canonical]["losses"] += losses or 0.0

    return _finalize_agg_rows(rows)


def parse_mixed_tag_stats(section: str) -> List[Dict[str, str]]:
    mixed_rows: List[Dict[str, str]] = []
    in_table = False

    for raw_line in section.splitlines():
        line = clean_text(raw_line)
        upper = line.upper()

        if "MIXED TAG STATS" in upper:
            in_table = True
            continue

        if not in_table:
            continue

        if "SUMMARY METRICS" in upper:
            break

        if "│" not in line:
            continue

        if "Enter Tag" in line and "Exit Reason" in line and "Trades" in line:
            continue

        parts = split_pipe_line(line, keep_empty=True)
        if len(parts) < 8:
            continue

        enter_tag = parts[0].strip()
        exit_reason_raw = parts[1].strip()

        if enter_tag.upper() == "TOTAL" or exit_reason_raw.upper() == "TOTAL":
            continue

        trades = clean_num(parts[2])
        if not trades or not re.fullmatch(r"\d+(?:\.\d+)?", trades):
            continue

        canonical = canonical_exit_reason(exit_reason_raw)
        if canonical in {"ignore", "other"}:
            continue

        wdl_source = parts[7] if len(parts) > 7 else ""
        wdl_nums = re.findall(r"[-+]?\d+(?:\.\d+)?", wdl_source)

        mixed_rows.append({
            "enter_tag": enter_tag,
            "exit_reason_raw": exit_reason_raw,
            "canonical_exit_reason": canonical,
            "trades": trades,
            "avg_profit_pct": clean_num(parts[3]) if len(parts) > 3 else "",
            "winrate": wdl_nums[3] if len(wdl_nums) > 3 else "",
        })

    return mixed_rows


def aggregate_mixed_tag_stats(mixed_rows: List[Dict[str, str]]) -> Dict[str, Dict[str, str]]:
    rows: Dict[str, Dict[str, float]] = {}

    for row in mixed_rows:
        canonical = row["canonical_exit_reason"]
        if canonical not in {"roi", "stop_loss", "trailing_stop_loss", "exit_signal", "custom_exit_signal"}:
            continue

        trades = safe_float(row["trades"])
        avg_profit_pct = safe_float(row["avg_profit_pct"])
        winrate = safe_float(row["winrate"])

        if trades is None or trades <= 0:
            continue

        wins = (winrate / 100.0) * trades if winrate is not None else 0.0

        if canonical not in rows:
            rows[canonical] = _empty_agg_bucket()

        rows[canonical]["trades"] += trades
        rows[canonical]["weighted_profit_sum"] += (avg_profit_pct or 0.0) * trades
        rows[canonical]["wins"] += wins

    return _finalize_agg_rows(rows)


def parse_window_key(section: str) -> Tuple[str, str]:
    m = BACKTESTED_RE.search(section)
    if m:
        return m.group(1), m.group(2)

    start = find_metric(section, "Backtesting from")
    end = find_metric(section, "Backtesting to")
    if start and end:
        return start[:10], end[:10]

    return "", ""


def detect_timerange_raw(section: str) -> str:
    m = TIMERANGE_RE.search(section)
    return m.group(1) if m else ""


def choose_exit_stats(section: str) -> Dict[str, Dict[str, str]]:
    exit_stats = parse_exit_reason_stats(section)
    mixed_rows = parse_mixed_tag_stats(section)
    mixed_stats = aggregate_mixed_tag_stats(mixed_rows)

    if not exit_stats and mixed_stats:
        return mixed_stats

    return exit_stats


def get_drawdown_header(prefix: str) -> str:
    if prefix in {"W1", "W4"}:
        return f"{prefix} Max Drawdown %"
    return f"{prefix} Drawdown %"


def build_window_metrics(section: str, prefix: str) -> Tuple[str, Dict[str, str], bool]:
    strat = parse_strategy_summary_row(section)
    exits = choose_exit_stats(section)

    profit_factor = clean_num(find_metric(section, "Profit factor"))
    expectancy = parse_expectancy(find_metric(section, "Expectancy (Ratio)"))
    sortino = clean_num(find_metric(section, "Sortino"))
    sharpe = clean_num(find_metric(section, "Sharpe"))
    calmar = clean_num(find_metric(section, "Calmar"))
    sqn = clean_num(find_metric(section, "SQN"))
    avg_daily_profit = clean_num(find_metric(section, "Avg. daily profit"))
    best_trade_pct = parse_trade_pct(find_metric(section, "Best trade"))
    worst_trade_pct = parse_trade_pct(find_metric(section, "Worst trade"))
    best_day_usdt = clean_num(find_metric(section, "Best day"))
    worst_day_usdt = clean_num(find_metric(section, "Worst day"))
    days_win, _, days_lose = parse_days_win_draw_lose(find_metric(section, "Days win/draw/lose"))
    max_consecutive_win, max_consecutive_loss = parse_max_consecutive(find_metric(section, "Max Consecutive Wins / Loss"))
    rejected_entry_sig = clean_num(find_metric(section, "Rejected Entry signals"))

    total_daily = clean_text(find_metric(section, "Total/Daily Avg Trades"))
    total_daily_match = re.search(r"([-+]?\d+(?:\.\d+)?)\s*/\s*([-+]?\d+(?:\.\d+)?)", total_daily)
    trades_per_day = total_daily_match.group(2) if total_daily_match else ""

    drawdown_duration_days = duration_to_days(find_metric(section, "Drawdown duration"))
    market_change = clean_num(find_metric(section, "Market change"))

    stop_loss_row = exits.get("stop_loss", {})
    trailing_stop_loss_row = exits.get("trailing_stop_loss", {})
    exit_signal_row = exits.get("exit_signal", {})
    custom_exit_signal_row = exits.get("custom_exit_signal", {})
    roi_row = exits.get("roi", {})

    trailing_stop_enabled = bool(trailing_stop_loss_row)

    exit_signal_avg_profit = exit_signal_row.get("avg_profit_pct") or "N/A"
    exit_signal_winrate = exit_signal_row.get("winrate") or "N/A"
    exit_signal_trades = exit_signal_row.get("trades") or "N/A"

    custom_exit_signal_avg_profit = custom_exit_signal_row.get("avg_profit_pct") or "N/A"
    custom_exit_signal_winrate = custom_exit_signal_row.get("winrate") or "N/A"
    custom_exit_signal_trades = custom_exit_signal_row.get("trades") or "N/A"

    roi_avg_profit = roi_row.get("avg_profit_pct") or "N/A"
    roi_winrate = roi_row.get("winrate") or "N/A"
    roi_trades = roi_row.get("trades") or "N/A"

    stoploss_avg_profit = stop_loss_row.get("avg_profit_pct") or "N/A"
    stoploss_winrate = stop_loss_row.get("winrate") or "N/A"
    stoploss_trades = stop_loss_row.get("trades") or "N/A"

    trailing_stop_avg_profit = trailing_stop_loss_row.get("avg_profit_pct") or "N/A"
    trailing_stop_winrate = trailing_stop_loss_row.get("winrate") or "N/A"
    trailing_stop_trades = trailing_stop_loss_row.get("trades") or "N/A"

    drawdown_header = get_drawdown_header(prefix)

    data = {
        f"{prefix} Trades": strat["Trades"],
        f"{prefix} Avg Profit %": strat["Avg Profit %"],
        f"{prefix} Total Profit %": strat["Total Profit %"],
        f"{prefix} Total Win": strat["Total Win"],
        f"{prefix} Total Loss": strat["Total Loss"],
        f"{prefix} Winrate %": strat["Winrate %"],
        drawdown_header: strat["Drawdown %"],
        f"{prefix} Profit Factor": profit_factor,
        f"{prefix} Expectancy": expectancy,
        f"{prefix} Sortino": sortino,
        f"{prefix} Sharpe": sharpe,
        f"{prefix} Calmar": calmar,
        f"{prefix} SQN": sqn,
        f"{prefix} Avg Daily Profit USDT": avg_daily_profit,
        f"{prefix} Best Trade %": best_trade_pct,
        f"{prefix} Worst Trade %": worst_trade_pct,
        f"{prefix} Best Day USDT": best_day_usdt,
        f"{prefix} Worst Day USDT": worst_day_usdt,
        f"{prefix} Days Win": days_win,
        f"{prefix} Days Lose": days_lose,
        f"{prefix} Max Consecutive Wins": max_consecutive_win,
        f"{prefix} Max Consecutive Losses": max_consecutive_loss,

        f"{prefix} Exit Signal Avg Profit %": exit_signal_avg_profit,
        f"{prefix} Exit Signal Winrate %": exit_signal_winrate,
        f"{prefix} Exit Signal Trades": exit_signal_trades,

        f"{prefix} Custom Exit Signal Avg Profit %": custom_exit_signal_avg_profit,
        f"{prefix} Custom Exit Signal Winrate %": custom_exit_signal_winrate,
        f"{prefix} Custom Exit Signal Trades": custom_exit_signal_trades,

        f"{prefix} ROI Avg Profit %": roi_avg_profit,
        f"{prefix} ROI Winrate %": roi_winrate,
        f"{prefix} ROI Trades": roi_trades,

        f"{prefix} Stoploss Avg Profit %": stoploss_avg_profit,
        f"{prefix} Stoploss Winrate %": stoploss_winrate,
        f"{prefix} Stoploss Trades": stoploss_trades,

        f"{prefix} Trailing Stop Avg Profit %": trailing_stop_avg_profit,
        f"{prefix} Trailing Stop Winrate %": trailing_stop_winrate,
        f"{prefix} Trailing Stop Trades": trailing_stop_trades,

        f"{prefix} Rejected Entry Signals": rejected_entry_sig,
        f"{prefix} Trades per Day": trades_per_day,
        f"{prefix} Avg Trade Duration": strat["Avg Trade Duration"],
        f"{prefix} Drawdown Duration (days)": drawdown_duration_days,
        f"{prefix} Market change %": market_change,
    }

    return strat["Strategy Name"], data, trailing_stop_enabled


def make_window_headers(prefix: str) -> List[str]:
    drawdown_header = get_drawdown_header(prefix)
    return [
        f"{prefix} Trades",
        f"{prefix} Avg Profit %",
        f"{prefix} Total Profit %",
        f"{prefix} Total Win",
        f"{prefix} Total Loss",
        f"{prefix} Winrate %",
        drawdown_header,
        f"{prefix} Profit Factor",
        f"{prefix} Expectancy",
        f"{prefix} Sortino",
        f"{prefix} Sharpe",
        f"{prefix} Calmar",
        f"{prefix} SQN",
        f"{prefix} Avg Daily Profit USDT",
        f"{prefix} Best Trade %",
        f"{prefix} Worst Trade %",
        f"{prefix} Best Day USDT",
        f"{prefix} Worst Day USDT",
        f"{prefix} Days Win",
        f"{prefix} Days Lose",
        f"{prefix} Max Consecutive Wins",
        f"{prefix} Max Consecutive Losses",
        f"{prefix} Exit Signal Avg Profit %",
        f"{prefix} Exit Signal Winrate %",
        f"{prefix} Exit Signal Trades",
        f"{prefix} Custom Exit Signal Avg Profit %",
        f"{prefix} Custom Exit Signal Winrate %",
        f"{prefix} Custom Exit Signal Trades",
        f"{prefix} ROI Avg Profit %",
        f"{prefix} ROI Winrate %",
        f"{prefix} ROI Trades",
        f"{prefix} Stoploss Avg Profit %",
        f"{prefix} Stoploss Winrate %",
        f"{prefix} Stoploss Trades",
        f"{prefix} Trailing Stop Avg Profit %",
        f"{prefix} Trailing Stop Winrate %",
        f"{prefix} Trailing Stop Trades",
        f"{prefix} Rejected Entry Signals",
        f"{prefix} Trades per Day",
        f"{prefix} Avg Trade Duration",
        f"{prefix} Drawdown Duration (days)",
        f"{prefix} Market change %",
    ]


HEADERS: List[str] = (
    ["Strategy Name", "Trailing Stop Enabled"]
    + make_window_headers("W1")
    + make_window_headers("W2")
    + make_window_headers("W3")
    + make_window_headers("W4")
)


def assign_prefixes_to_sections(sections: List[str]) -> List[Tuple[str, str]]:
    """
    Returns list of (prefix, section).
    First tries explicit timerange/date mapping.
    Then fills remaining sections in order W1..W4.
    """
    assigned: Dict[str, str] = {}
    unassigned_sections: List[str] = []

    for section in sections[:4]:
        timerange_raw = detect_timerange_raw(section)
        if timerange_raw and timerange_raw in TIMERANGE_PREFIX_MAP:
            prefix = TIMERANGE_PREFIX_MAP[timerange_raw]
            if prefix not in assigned:
                assigned[prefix] = section
                continue

        start_date, end_date = parse_window_key(section)
        mapped_prefix = DATE_RANGE_PREFIX_MAP.get((start_date, end_date))
        if mapped_prefix and mapped_prefix not in assigned:
            assigned[mapped_prefix] = section
            continue

        unassigned_sections.append(section)

    ordered_prefixes = ["W1", "W2", "W3", "W4"]
    remaining_prefixes = [p for p in ordered_prefixes if p not in assigned]

    for prefix, section in zip(remaining_prefixes, unassigned_sections):
        assigned[prefix] = section

    result: List[Tuple[str, str]] = []
    for prefix in ordered_prefixes:
        if prefix in assigned:
            result.append((prefix, assigned[prefix]))

    return result


def build_output(text: str, include_strategy_name: bool = True) -> Tuple[str, str]:
    sections = extract_sections(text)
    if len(sections) < 1:
        raise ValueError("Could not detect any BACKTESTING REPORT sections.")

    mapped_sections = assign_prefixes_to_sections(sections)
    if not mapped_sections:
        raise ValueError("Could not assign any report windows.")

    strategy_name = ""
    merged: Dict[str, str] = {}
    trailing_any = False

    for prefix, section in mapped_sections:
        parsed_strategy_name, data, trailing_enabled = build_window_metrics(section, prefix)
        if not strategy_name:
            strategy_name = parsed_strategy_name
        merged.update(data)
        trailing_any = trailing_any or trailing_enabled

    merged["Strategy Name"] = strategy_name
    merged["Trailing Stop Enabled"] = "TRUE" if trailing_any else "FALSE"

    headers = HEADERS.copy()
    values = [merged.get(h, "") for h in headers]

    if not include_strategy_name:
        headers = headers[1:]
        values = values[1:]

    return "\t".join(headers), "\t".join(values)


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("Freqtrade 4-Window Backtest Parser")
        self.root.geometry("900x1080")
        self.root.minsize(900, 1000)
        self.root.configure(bg="#111827")

        self.toast_after_id = None
        self.auto_parse_after_id = None
        self.include_strategy_name = tk.BooleanVar(value=True)

        self.setup_style()

        main = tk.Frame(root, bg="#111827")
        main.pack(fill="both", expand=True, padx=14, pady=14)

        title = tk.Label(
            main,
            text="Freqtrade Backtest Parser → Excel 4-Window Row",
            font=("Segoe UI", 18, "bold"),
            fg="#F9FAFB",
            bg="#111827"
        )
        title.pack(anchor="w", pady=(0, 6))

        dnd_status = "Drag & drop: ENABLED" if HAS_DND else "Drag & drop: DISABLED (install tkinterdnd2 into this Python)"
        dnd_color = "#10B981" if HAS_DND else "#F59E0B"

        info = tk.Label(
            main,
            text="Paste text, open a file, or drag in a file. Supports W1/W2/W3/W4 and timerange mapping.",
            font=("Segoe UI", 10),
            fg="#9CA3AF",
            bg="#111827"
        )
        info.pack(anchor="w", pady=(0, 2))

        dnd_label = tk.Label(
            main,
            text=dnd_status,
            font=("Segoe UI", 10, "bold"),
            fg=dnd_color,
            bg="#111827"
        )
        dnd_label.pack(anchor="w", pady=(0, 12))

        top_bar = tk.Frame(main, bg="#111827")
        top_bar.pack(fill="x", pady=(0, 12))

        left_btns = tk.Frame(top_bar, bg="#111827")
        left_btns.pack(side="left")

        self.make_button(left_btns, "Paste from Clipboard", self.paste_input, "#2563EB").pack(side="left", padx=(0, 8))
        self.make_button(left_btns, "Open File", self.open_file, "#7C3AED").pack(side="left", padx=(0, 8))
        self.make_button(left_btns, "Parse", self.parse_text, "#059669").pack(side="left", padx=(0, 8))
        self.make_button(left_btns, "Clear", self.clear_all, "#DC2626").pack(side="left", padx=(0, 8))

        chk = tk.Checkbutton(
            top_bar,
            text="Include Strategy Name",
            variable=self.include_strategy_name,
            command=self.refresh_output_if_possible,
            font=("Segoe UI", 10),
            fg="#E5E7EB",
            bg="#111827",
            activebackground="#111827",
            activeforeground="#E5E7EB",
            selectcolor="#1F2937",
            bd=0,
            highlightthickness=0
        )
        chk.pack(side="left")

        input_label = tk.Label(main, text="Input block", font=("Segoe UI", 11, "bold"), fg="#E5E7EB", bg="#111827")
        input_label.pack(anchor="w", pady=(0, 6))

        self.input_box = self.make_textbox(main, height=18)
        self.input_box.pack(fill="both", expand=True, pady=(0, 12))

        if HAS_DND:
            for widget in (self.root, self.input_box, self.input_box.text_widget):
                try:
                    widget.drop_target_register(DND_FILES)
                    widget.dnd_bind("<<Drop>>", self.on_file_drop)
                except Exception:
                    pass

        self.input_box.text_widget.bind("<<Paste>>", self.on_input_changed_event, add="+")
        self.input_box.text_widget.bind("<KeyRelease>", self.on_input_changed_event, add="+")
        self.input_box.text_widget.bind("<ButtonRelease-3>", self.on_input_changed_event, add="+")
        self.input_box.text_widget.bind("<Control-v>", self.on_input_changed_event, add="+")
        self.input_box.text_widget.bind("<Control-V>", self.on_input_changed_event, add="+")

        headers_label = tk.Label(main, text="Headers — click inside box to copy", font=("Segoe UI", 11, "bold"), fg="#E5E7EB", bg="#111827")
        headers_label.pack(anchor="w", pady=(0, 6))

        self.headers_box = self.make_textbox(main, height=4, readonly=True)
        self.headers_box.pack(fill="x", expand=False, pady=(0, 6))
        self.bind_copy_box(self.headers_box, self.copy_headers)

        headers_btn_row = tk.Frame(main, bg="#111827")
        headers_btn_row.pack(fill="x", pady=(0, 12))
        self.make_button(headers_btn_row, "Copy Headers", self.copy_headers, "#D97706").pack(anchor="e")

        row_label = tk.Label(main, text="Excel-ready row — click inside box to copy", font=("Segoe UI", 11, "bold"), fg="#E5E7EB", bg="#111827")
        row_label.pack(anchor="w", pady=(0, 6))

        self.row_box = self.make_textbox(main, height=8, readonly=True)
        self.row_box.pack(fill="both", expand=True, pady=(0, 6))
        self.bind_copy_box(self.row_box, self.copy_row)

        row_btn_row = tk.Frame(main, bg="#111827")
        row_btn_row.pack(fill="x", pady=(0, 10))
        self.make_button(row_btn_row, "Copy Row", self.copy_row, "#7C3AED").pack(anchor="e")

        self.toast = tk.Label(
            main,
            text="",
            font=("Segoe UI", 10, "bold"),
            fg="#F9FAFB",
            bg="#1F2937",
            bd=0,
            padx=14,
            pady=8
        )
        self.toast.place_forget()

    def setup_style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

    def make_button(self, parent, text, command, bg):
        return tk.Button(
            parent,
            text=text,
            command=command,
            font=("Segoe UI", 10, "bold"),
            fg="#FFFFFF",
            bg=bg,
            activebackground=bg,
            activeforeground="#FFFFFF",
            relief="flat",
            bd=0,
            padx=14,
            pady=8,
            cursor="hand2"
        )

    def make_textbox(self, parent, height=8, readonly=False):
        outer = tk.Frame(parent, bg="#1F2937", highlightthickness=1, highlightbackground="#374151")
        text = tk.Text(
            outer,
            wrap="none",
            height=height,
            font=("Consolas", 10),
            bg="#0F172A",
            fg="#E5E7EB",
            insertbackground="#F9FAFB",
            relief="flat",
            bd=0,
            undo=not readonly,
            padx=10,
            pady=10
        )
        xscroll = tk.Scrollbar(outer, orient="horizontal", command=text.xview)
        yscroll = tk.Scrollbar(outer, orient="vertical", command=text.yview)
        text.configure(xscrollcommand=xscroll.set, yscrollcommand=yscroll.set)
        outer.rowconfigure(0, weight=1)
        outer.columnconfigure(0, weight=1)
        text.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")

        if readonly:
            text.configure(state="disabled")

        outer.text_widget = text
        return outer

    def bind_copy_box(self, outer, callback):
        outer.bind("<Button-1>", lambda e: self.handle_copy_click(callback))
        outer.text_widget.bind("<Button-1>", lambda e: self.handle_copy_click(callback))
        outer.text_widget.bind("<ButtonRelease-1>", lambda e: "break")
        outer.text_widget.bind("<B1-Motion>", lambda e: "break")
        outer.text_widget.bind("<Double-Button-1>", lambda e: "break")
        outer.text_widget.bind("<Triple-Button-1>", lambda e: "break")

    def handle_copy_click(self, callback):
        callback()
        return "break"

    def get_textbox_text(self, outer):
        return outer.text_widget.get("1.0", "end").strip()

    def set_textbox_text(self, outer, value):
        widget = outer.text_widget
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        if outer in (self.headers_box, self.row_box):
            widget.configure(state="disabled")

    def clear_textbox(self, outer):
        widget = outer.text_widget
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        if outer in (self.headers_box, self.row_box):
            widget.configure(state="disabled")

    def show_toast(self, message, bg="#1F2937"):
        self.toast.configure(text=message, bg=bg)
        self.toast.place(relx=1.0, rely=1.0, x=-20, y=-20, anchor="se")
        if self.toast_after_id is not None:
            self.root.after_cancel(self.toast_after_id)
        self.toast_after_id = self.root.after(5000, self.hide_toast)

    def hide_toast(self):
        self.toast.place_forget()
        self.toast_after_id = None

    def copy_to_clipboard(self, text, label="Copied"):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.root.update()
        self.show_toast(label, bg="#065F46")

    def schedule_auto_parse(self):
        if self.auto_parse_after_id is not None:
            self.root.after_cancel(self.auto_parse_after_id)
        self.auto_parse_after_id = self.root.after(250, self.auto_parse_now)

    def auto_parse_now(self):
        self.auto_parse_after_id = None
        text = self.get_textbox_text(self.input_box)
        if not text:
            return
        try:
            headers, row = build_output(text, include_strategy_name=self.include_strategy_name.get())
            self.set_textbox_text(self.headers_box, headers)
            self.set_textbox_text(self.row_box, row)
            self.show_toast("Parsed automatically", bg="#065F46")
        except Exception:
            pass

    def on_input_changed_event(self, event=None):
        self.schedule_auto_parse()

    def _extract_dropped_filepaths(self, data: str) -> List[str]:
        try:
            paths = list(self.root.tk.splitlist(data))
        except Exception:
            paths = [data]

        cleaned = []
        for p in paths:
            p = p.strip().strip("{}").strip()
            if p:
                cleaned.append(p)
        return cleaned

    def paste_input(self):
        try:
            text = self.root.clipboard_get()
            self.set_textbox_text(self.input_box, text)
            self.show_toast("Pasted from clipboard", bg="#1D4ED8")
            self.schedule_auto_parse()
        except Exception:
            self.show_toast("Clipboard text not available", bg="#991B1B")

    def open_file(self):
        file_path = filedialog.askopenfilename(
            title="Open backtest report",
            filetypes=[
                ("Backtest text files", "*.txt *.log *.md *.ini"),
                ("All files", "*.*"),
            ]
        )
        if not file_path:
            return

        try:
            text = read_text_file(file_path)
            self.set_textbox_text(self.input_box, text)
            self.show_toast(f"Loaded file: {Path(file_path).name}", bg="#1D4ED8")
            self.schedule_auto_parse()
        except Exception as e:
            self.show_toast(f"File load error: {e}", bg="#991B1B")

    def on_file_drop(self, event):
        try:
            paths = self._extract_dropped_filepaths(event.data)
            if not paths:
                return "break"

            file_path = paths[0]
            text = read_text_file(file_path)
            self.set_textbox_text(self.input_box, text)
            self.show_toast(f"Loaded dropped file: {Path(file_path).name}", bg="#1D4ED8")
            self.schedule_auto_parse()
        except Exception as e:
            self.show_toast(f"Drop load error: {e}", bg="#991B1B")
        return "break"

    def parse_text(self):
        text = self.get_textbox_text(self.input_box)
        if not text:
            self.show_toast("Paste the full 4-window backtest block first", bg="#92400E")
            return
        try:
            headers, row = build_output(text, include_strategy_name=self.include_strategy_name.get())
        except Exception as e:
            self.show_toast(f"Parse error: {e}", bg="#991B1B")
            return
        self.set_textbox_text(self.headers_box, headers)
        self.set_textbox_text(self.row_box, row)
        self.show_toast("Parsed successfully", bg="#065F46")

    def refresh_output_if_possible(self):
        text = self.get_textbox_text(self.input_box)
        if text:
            try:
                headers, row = build_output(text, include_strategy_name=self.include_strategy_name.get())
                self.set_textbox_text(self.headers_box, headers)
                self.set_textbox_text(self.row_box, row)
                self.show_toast("Column layout updated", bg="#1D4ED8")
            except Exception:
                pass

    def copy_row(self):
        row = self.get_textbox_text(self.row_box)
        if not row:
            self.show_toast("Nothing to copy in row box", bg="#92400E")
            return
        self.copy_to_clipboard(row, "Excel row copied")

    def copy_headers(self):
        headers = self.get_textbox_text(self.headers_box)
        if not headers:
            self.show_toast("Nothing to copy in headers box", bg="#92400E")
            return
        self.copy_to_clipboard(headers, "Headers copied")

    def clear_all(self):
        if self.auto_parse_after_id is not None:
            self.root.after_cancel(self.auto_parse_after_id)
            self.auto_parse_after_id = None
        self.clear_textbox(self.input_box)
        self.clear_textbox(self.headers_box)
        self.clear_textbox(self.row_box)
        self.show_toast("Cleared", bg="#991B1B")


if __name__ == "__main__":
    root = TkinterDnD.Tk() if HAS_DND else tk.Tk()
    app = App(root)
    root.mainloop()