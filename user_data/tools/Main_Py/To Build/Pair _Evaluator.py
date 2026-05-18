import json
import tkinter as tk
from tkinter import scrolledtext, messagebox, filedialog
import re
from dataclasses import dataclass
from typing import Dict, Tuple, Set, List, Optional


# =========================
# py -m PyInstaller --onefile --noconsole --name PairEvaluator pair_ev14_single_run.py
# =========================

# ---------- Defaults ----------
DEFAULT_MIN_TOTAL_TRADES_ALL_WINDOWS = 25
DEFAULT_MIN_AVG_PROFIT_PCT = 0.35
DEFAULT_MIN_SCORE = 55.0

# Output mode
OUTPUT_MODE_MERGE = "Merge"
OUTPUT_MODE_REPLACE = "Replace"
OUTPUT_MODE_INTERSECT = "Intersect"
DEFAULT_OUTPUT_MODE = OUTPUT_MODE_MERGE

# Export formats
EXPORT_WHITELIST_JSON = "whitelist_json"
EXPORT_BLACKLIST_JSON = "blacklist_json"
EXPORT_WATCHLIST_JSON = "watchlist_json"
EXPORT_PLAIN_TXT = "plain_txt"

# Group titles
TITLE_GA = "Group A: ✅ 3/3 Positive"
TITLE_GB = "Group B: 🟡 2/3 Positive, 0 Negative"
TITLE_GC = "Group C: 🟠 1 Positive, 0 Negative"
TITLE_GD = "Group D: 🔵 2/3 Positive, 1 Negative"
TITLE_GE = "Group E: 📍 1 Positive, 1 Negative"
TITLE_GF = "Group F: 🚫 0 Positive, Has Negative"
TITLE_BL = "⛔ Blacklist"
TITLE_WL = "👀 Watchlist"
TITLE_FINAL = "📦 Whitelist"

EXPECTED_WINDOWS = {
    "TRAIN": ("2024-01-01", "2024-07-01"),
    "VALID": ("2024-07-01", "2024-10-01"),
    "TEST": ("2024-10-01", "2025-12-01"),
}

# ---------- Globals ----------
root: tk.Tk
result_win: Optional[tk.Toplevel] = None
text_widgets: Dict[str, tk.Text] = {}
last_scroll_positions: Dict[tk.Text, Tuple[Optional[str], Optional[str]]] = {}

min_total_trades_var: tk.IntVar
min_avg_profit_pct_var: tk.DoubleVar
min_score_var: tk.DoubleVar
output_mode_var: tk.StringVar

text_area: scrolledtext.ScrolledText
list_area: scrolledtext.ScrolledText

last_output_whitelist: List[str] = []
last_output_blacklist: List[str] = []
last_output_watchlist: List[str] = []
last_output_scores: List[str] = []


# ---------- Clipboard / Context menus ----------
def paste_text(text_widget: tk.Text) -> None:
    try:
        clipboard = root.clipboard_get()
        text_widget.insert(tk.INSERT, clipboard)
    except tk.TclError:
        pass


def copy_all(text_widget: tk.Text) -> None:
    try:
        text = text_widget.get("1.0", tk.END)
        root.clipboard_clear()
        root.clipboard_append(text)
    except tk.TclError:
        pass


def delete_selection(text_widget: tk.Text) -> None:
    try:
        text_widget.delete("sel.first", "sel.last")
    except tk.TclError:
        pass


def delete_all(text_widget: tk.Text) -> None:
    text_widget.delete("1.0", tk.END)


def create_context_menu(text_widget: tk.Text, paste: bool = True, copy_all_opt: bool = False) -> None:
    menu = tk.Menu(root, tearoff=0)
    if paste:
        menu.add_command(label="Paste", command=lambda: paste_text(text_widget))
    menu.add_command(label="Delete Selected", command=lambda: delete_selection(text_widget))
    menu.add_command(label="Delete All", command=lambda: delete_all(text_widget))
    if copy_all_opt:
        menu.add_command(label="Copy All", command=lambda: copy_all(text_widget))

    def show_menu(event: tk.Event) -> None:
        menu.tk_popup(event.x_root, event.y_root)

    text_widget.bind("<Button-3>", show_menu)


def create_context_menu_valid(text_widget: tk.Text) -> None:
    menu = tk.Menu(root, tearoff=0)
    menu.add_command(label="Copy All", command=lambda: copy_all(text_widget))

    def show_menu(event: tk.Event) -> None:
        menu.tk_popup(event.x_root, event.y_root)

    text_widget.bind("<Button-3>", show_menu)


# ---------- Universal config helpers ----------
PAIR_LITERAL_RE = re.compile(r'"([A-Z0-9]+/USDT)"')
PAIR_LINE_RE = re.compile(r'^\s*"([A-Z0-9]+/USDT)"\s*,?\s*$')
PAIR_BLOCK_RE = re.compile(r'"pair_(whitelist|blacklist)"\s*:\s*\[(.*?)\]', re.DOTALL | re.IGNORECASE)


def strip_json_comments(text: str) -> str:
    # removes // comments only, enough for your config style
    return re.sub(r'(?m)//.*$', '', text)


def extract_pairs_from_named_block(text: str, block_name: str) -> List[str]:
    pattern = re.compile(rf'"{re.escape(block_name)}"\s*:\s*\[(.*?)\]', re.DOTALL | re.IGNORECASE)
    m = pattern.search(text)
    if not m:
        return []

    inner = m.group(1)
    found = []
    seen = set()

    for pair in PAIR_LITERAL_RE.findall(inner):
        if pair not in seen:
            seen.add(pair)
            found.append(pair)
    return found


def parse_existing_universal(text: str) -> Tuple[Set[str], Set[str]]:
    whitelist_pairs = set(extract_pairs_from_named_block(text, "pair_whitelist"))
    blacklist_pairs = set(extract_pairs_from_named_block(text, "pair_blacklist"))

    # fallback for old plain pasted whitelist/list
    if not whitelist_pairs and not blacklist_pairs:
        for match in PAIR_LITERAL_RE.finditer(text):
            whitelist_pairs.add(match.group(1))

        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("//"):
                continue
            line = line.rstrip(",").strip().strip('"').strip("'")
            if re.fullmatch(r"[A-Z0-9]+/USDT", line):
                whitelist_pairs.add(line)

    return whitelist_pairs, blacklist_pairs


def make_exchange_config(whitelist: List[str], blacklist: List[str]) -> Dict:
    return {
        "exchange": {
            "pair_whitelist": whitelist,
            "pair_blacklist": blacklist,
        }
    }


def merge_blacklist_into_existing_config_text(existing_text: str, new_pairs: List[str]) -> str:
    """
    Preserves user's existing config text and comments as much as possible.
    Adds exported blacklist entries before the closing ] of pair_blacklist.
    """
    if not new_pairs:
        return existing_text

    block_pattern = re.compile(r'("pair_blacklist"\s*:\s*\[)(.*?)(\n\s*\])', re.DOTALL | re.IGNORECASE)
    match = block_pattern.search(existing_text)

    if not match:
        # No blacklist block found -> build full JSON-ish config from extracted data
        existing_whitelist, existing_blacklist = parse_existing_universal(existing_text)
        merged_blacklist = sorted(existing_blacklist | set(new_pairs))
        data = make_exchange_config(sorted(existing_whitelist), merged_blacklist)
        return json.dumps(data, indent=2)

    block_start = match.group(1)
    block_body = match.group(2)
    block_end = match.group(3)

    existing_pairs_in_block = extract_pairs_from_named_block(existing_text, "pair_blacklist")
    merged_new = [p for p in new_pairs if p not in set(existing_pairs_in_block)]

    if not merged_new:
        return existing_text

    indent_match = re.search(r'(\n[ \t]*)"[^"\n]+?"', block_body)
    item_indent = indent_match.group(1)[1:] if indent_match else "      "

    body_rstripped = block_body.rstrip()

    if body_rstripped:
        stripped = body_rstripped
        if not stripped.endswith(","):
            stripped += ","

        exported_lines = [f'{item_indent}// Exported']
        for i, pair in enumerate(merged_new):
            comma = "," if i < len(merged_new) - 1 else ""
            exported_lines.append(f'{item_indent}"{pair}"{comma}')

        new_body = stripped + "\n" + "\n".join(exported_lines)
    else:
        exported_lines = [f'{item_indent}// Exported']
        for i, pair in enumerate(merged_new):
            comma = "," if i < len(merged_new) - 1 else ""
            exported_lines.append(f'{item_indent}"{pair}"{comma}')
        new_body = "\n" + "\n".join(exported_lines)

    return existing_text[:match.start()] + block_start + new_body + block_end + existing_text[match.end():]


def merge_watchlist_into_existing_config_text(existing_text: str, new_pairs: List[str]) -> str:
    if not new_pairs:
        return existing_text

    clean_text = strip_json_comments(existing_text).strip()

    try:
        parsed = json.loads(clean_text)
        exchange = parsed.setdefault("exchange", {})
        existing = exchange.get("watchlist_pairs", [])
        if not isinstance(existing, list):
            existing = []
        merged = []
        seen = set()
        for p in existing + new_pairs:
            if isinstance(p, str) and p not in seen:
                seen.add(p)
                merged.append(p)
        exchange["watchlist_pairs"] = merged
        return json.dumps(parsed, indent=2)
    except Exception:
        existing_whitelist, existing_blacklist = parse_existing_universal(existing_text)
        data = make_exchange_config(sorted(existing_whitelist), sorted(existing_blacklist))
        data["exchange"]["watchlist_pairs"] = sorted(set(new_pairs))
        return json.dumps(data, indent=2)


# ---------- Parsing ----------
@dataclass(frozen=True)
class PairMetrics:
    trades: int
    avg_profit_pct: float
    tot_profit_usdt: float


WindowKey = Tuple[str, str]

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
PAIR_TOKEN_RE = re.compile(r"^[A-Z0-9]+/USDT$")
BACKTESTED_LINE_RE = re.compile(
    r"Backtested\s+(\d{4}-\d{2}-\d{2})\s+\d{2}:\d{2}:\d{2}\s+->\s+(\d{4}-\d{2}-\d{2})\s+\d{2}:\d{2}:\d{2}",
    re.IGNORECASE,
)
SUMMARY_FROM_RE = re.compile(
    r"Backtesting from\s*[│|]\s*(\d{4}-\d{2}-\d{2})",
    re.IGNORECASE,
)
SUMMARY_TO_RE = re.compile(
    r"Backtesting to\s*[│|]\s*(\d{4}-\d{2}-\d{2})",
    re.IGNORECASE,
)


def _clean_line(text: str) -> str:
    text = ANSI_RE.sub("", text)
    return text.replace("−", "-").replace("\xa0", " ").rstrip()


def _norm_num_token(text: str) -> str:
    text = _clean_line(text).strip()
    return text.replace("%", "").replace(",", "")


def _safe_int(text: str) -> Optional[int]:
    text = _norm_num_token(text)
    if not text:
        return None
    if re.fullmatch(r"[+-]?\d+", text):
        try:
            return int(text)
        except Exception:
            return None
    return None


def _safe_float(text: str) -> Optional[float]:
    text = _norm_num_token(text)
    if not text:
        return None
    try:
        value = float(text)
        if value != value:
            return None
        return value
    except Exception:
        return None


def _split_table_parts(raw_line: str) -> List[str]:
    sep = "│" if "│" in raw_line else ("|" if "|" in raw_line else None)
    if not sep:
        return []
    parts = [x.strip() for x in raw_line.split(sep)]
    return [x for x in parts if x != ""]


def _extract_main_report_table(section_text: str) -> str:
    lines = section_text.splitlines()

    started = False
    captured: List[str] = []

    for raw_line in lines:
        line = _clean_line(raw_line)

        if not started:
            if "BACKTESTING REPORT" in line.upper():
                started = True
            continue

        upper = line.upper()
        if (
            "LEFT OPEN TRADES REPORT" in upper
            or "ENTER TAG STATS" in upper
            or "EXIT REASON STATS" in upper
            or "MIXED TAG STATS" in upper
            or "SUMMARY METRICS" in upper
            or upper.startswith("BACKTESTED ")
            or "STRATEGY SUMMARY" in upper
        ):
            break

        captured.append(line)

    return "\n".join(captured)


def _parse_pairs_from_table_text(table_text: str) -> Dict[str, PairMetrics]:
    pairs: Dict[str, PairMetrics] = {}

    for raw_line in table_text.splitlines():
        line = _clean_line(raw_line)
        if "/USDT" not in line:
            continue

        parts = _split_table_parts(line)
        if not parts:
            continue

        pair_idx = -1
        pair_token: Optional[str] = None

        for idx, token in enumerate(parts):
            token = _clean_line(token).strip()
            if PAIR_TOKEN_RE.fullmatch(token):
                pair_token = token
                pair_idx = idx
                break

        if pair_token is None:
            continue

        if pair_idx + 3 >= len(parts):
            continue

        trades = _safe_int(parts[pair_idx + 1])
        avg_profit = _safe_float(parts[pair_idx + 2])
        total_profit = _safe_float(parts[pair_idx + 3])

        if trades is None or total_profit is None:
            continue
        if avg_profit is None:
            avg_profit = 0.0

        pairs[pair_token] = PairMetrics(
            trades=trades,
            avg_profit_pct=avg_profit,
            tot_profit_usdt=total_profit,
        )

    return pairs


def _extract_window_key(section_text: str) -> Optional[WindowKey]:
    m = BACKTESTED_LINE_RE.search(section_text)
    if m:
        return m.group(1), m.group(2)

    fm = SUMMARY_FROM_RE.search(section_text)
    tm = SUMMARY_TO_RE.search(section_text)
    if fm and tm:
        return fm.group(1), tm.group(1)

    return None


def split_windows_robust(full_text: str) -> Dict[WindowKey, str]:
    text = _clean_line(full_text)

    marker = "BACKTESTING REPORT"
    starts = [m.start() for m in re.finditer(re.escape(marker), text, re.IGNORECASE)]
    if not starts:
        return {}

    windows: Dict[WindowKey, str] = {}

    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(text)
        section = text[start:end]

        window_key = _extract_window_key(section)
        if window_key is None:
            continue

        table_text = _extract_main_report_table(section)
        if not table_text.strip():
            continue

        existing = windows.get(window_key)
        if existing is None or len(table_text) > len(existing):
            windows[window_key] = table_text

    return windows


def parse_all_windows(full_text: str) -> Dict[WindowKey, Dict[str, PairMetrics]]:
    windows = split_windows_robust(full_text)
    return {wk: _parse_pairs_from_table_text(txt) for wk, txt in windows.items()}


def _norm_date(date_str: str) -> str:
    date_str = date_str.strip()
    if re.fullmatch(r"\d{8}", date_str):
        return f"{date_str[0:4]}-{date_str[4:6]}-{date_str[6:8]}"
    return date_str


def infer_train_valid_test_keys(
    all_windows: Dict[WindowKey, Dict[str, PairMetrics]]
) -> Tuple[Optional[WindowKey], Optional[WindowKey], Optional[WindowKey]]:
    if not all_windows:
        return None, None, None

    keys = list(all_windows.keys())
    norm_map: Dict[Tuple[str, str], WindowKey] = {(_norm_date(k[0]), _norm_date(k[1])): k for k in keys}

    train_k = norm_map.get((_norm_date(EXPECTED_WINDOWS["TRAIN"][0]), _norm_date(EXPECTED_WINDOWS["TRAIN"][1])))
    valid_k = norm_map.get((_norm_date(EXPECTED_WINDOWS["VALID"][0]), _norm_date(EXPECTED_WINDOWS["VALID"][1])))
    test_k = norm_map.get((_norm_date(EXPECTED_WINDOWS["TEST"][0]), _norm_date(EXPECTED_WINDOWS["TEST"][1])))

    used = {k for k in (train_k, valid_k, test_k) if k is not None}
    remaining = sorted([k for k in keys if k not in used], key=lambda x: _norm_date(x[0]))

    slots: List[Optional[WindowKey]] = [train_k, valid_k, test_k]
    for i in range(3):
        if slots[i] is None and remaining:
            slots[i] = remaining.pop(0)

    return slots[0], slots[1], slots[2]


def title_for_window(label: str, window_key: Optional[WindowKey]) -> str:
    if window_key is None:
        return f"{label}: (missing)"
    start = window_key[0].replace("-", "")
    end = window_key[1].replace("-", "")
    return f"{label}: {start}-{end}"


# ---------- Metrics helpers ----------
def metrics_or_default(window_map: Dict[str, PairMetrics], pair: str) -> PairMetrics:
    return window_map.get(pair, PairMetrics(trades=0, avg_profit_pct=0.0, tot_profit_usdt=0.0))


def pair_present_count(pair: str, train_map: Dict[str, PairMetrics], valid_map: Dict[str, PairMetrics], test_map: Dict[str, PairMetrics]) -> int:
    return int(pair in train_map) + int(pair in valid_map) + int(pair in test_map)


def pair_total_trades_across_windows(pair: str, train_map: Dict[str, PairMetrics], valid_map: Dict[str, PairMetrics], test_map: Dict[str, PairMetrics]) -> int:
    return (
        metrics_or_default(train_map, pair).trades
        + metrics_or_default(valid_map, pair).trades
        + metrics_or_default(test_map, pair).trades
    )


def pair_profit_list_existing(pair: str, train_map: Dict[str, PairMetrics], valid_map: Dict[str, PairMetrics], test_map: Dict[str, PairMetrics]) -> List[float]:
    profits: List[float] = []
    if pair in train_map:
        profits.append(train_map[pair].tot_profit_usdt)
    if pair in valid_map:
        profits.append(valid_map[pair].tot_profit_usdt)
    if pair in test_map:
        profits.append(test_map[pair].tot_profit_usdt)
    return profits


def pair_avg_profit_list_existing(pair: str, train_map: Dict[str, PairMetrics], valid_map: Dict[str, PairMetrics], test_map: Dict[str, PairMetrics]) -> List[float]:
    avgs: List[float] = []
    if pair in train_map:
        avgs.append(train_map[pair].avg_profit_pct)
    if pair in valid_map:
        avgs.append(valid_map[pair].avg_profit_pct)
    if pair in test_map:
        avgs.append(test_map[pair].avg_profit_pct)
    return avgs


def avg(values: List[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def clamp(val: float, low: float, high: float) -> float:
    return max(low, min(high, val))


def stdev(values: List[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((x - mean) ** 2 for x in values) / len(values)
    return variance ** 0.5


def window_is_positive(pm: PairMetrics, min_avg_profit_pct: float) -> bool:
    return pm.trades > 0 and pm.tot_profit_usdt > 0


def window_is_negative(pm: PairMetrics) -> bool:
    return pm.trades > 0 and pm.tot_profit_usdt < 0


def window_is_weak_neutral(pm: PairMetrics, min_avg_profit_pct: float) -> bool:
    return pm.trades > 0 and pm.tot_profit_usdt >= 0 and pm.avg_profit_pct < min_avg_profit_pct


def raw_window_state(pm: PairMetrics) -> str:
    if pm.trades <= 0:
        return "neutral"
    if pm.tot_profit_usdt > 0:
        return "positive"
    if pm.tot_profit_usdt < 0:
        return "negative"
    return "neutral"


def classify_pair_simple(
    pair: str,
    train_map: Dict[str, PairMetrics],
    valid_map: Dict[str, PairMetrics],
    test_map: Dict[str, PairMetrics],
) -> Tuple[str, int, int, int]:
    windows = [
        metrics_or_default(train_map, pair),
        metrics_or_default(valid_map, pair),
        metrics_or_default(test_map, pair),
    ]

    positive_count = 0
    negative_count = 0
    neutral_count = 0

    for pm in windows:
        state = raw_window_state(pm)
        if state == "positive":
            positive_count += 1
        elif state == "negative":
            negative_count += 1
        else:
            neutral_count += 1

    if positive_count == 3:
        return "A", positive_count, negative_count, neutral_count

    if positive_count == 2 and negative_count == 0:
        return "B", positive_count, negative_count, neutral_count

    if positive_count == 1 and negative_count == 0:
        return "C", positive_count, negative_count, neutral_count

    if positive_count == 2 and negative_count == 1:
        return "D", positive_count, negative_count, neutral_count

    if positive_count == 1 and negative_count == 1:
        return "E", positive_count, negative_count, neutral_count

    if negative_count >= 1:
        return "F", positive_count, negative_count, neutral_count

    return "C", positive_count, negative_count, neutral_count


def build_score_line(
    pair: str,
    score: float,
    positives: int,
    negatives: int,
    present_count: int,
    total_trades: int,
    total_profit: float,
    mean_avg_profit_pct: float,
) -> str:
    return (
        f"{pair:<14}  |  "
        f"score: {score:>7.2f}  |  "
        f"+w: {positives:<1}  |  "
        f"-w: {negatives:<1}  |  "
        f"present: {present_count:<1}  |  "
        f"trades: {total_trades:>4}  |  "
        f"total: {total_profit:>9.2f}  |  "
        f"avg%: {mean_avg_profit_pct:>6.2f}"
    )


def pair_score(
    pair: str,
    train_map: Dict[str, PairMetrics],
    valid_map: Dict[str, PairMetrics],
    test_map: Dict[str, PairMetrics],
    min_avg_profit_pct: float,
) -> Tuple[float, int, int, int, int, float, float]:
    present_count = pair_present_count(pair, train_map, valid_map, test_map)
    total_trades = pair_total_trades_across_windows(pair, train_map, valid_map, test_map)
    profits = pair_profit_list_existing(pair, train_map, valid_map, test_map)
    avg_pcts = pair_avg_profit_list_existing(pair, train_map, valid_map, test_map)

    positives = 0
    negatives = 0
    weak_neutral = 0
    windows = [
        metrics_or_default(train_map, pair),
        metrics_or_default(valid_map, pair),
        metrics_or_default(test_map, pair),
    ]

    for pm in windows:
        if window_is_positive(pm, min_avg_profit_pct):
            positives += 1
        elif window_is_negative(pm):
            negatives += 1
        elif window_is_weak_neutral(pm, min_avg_profit_pct):
            weak_neutral += 1

    total_profit = sum(profits)
    mean_avg_profit_pct = avg(avg_pcts)
    volatility = stdev(profits)
    worst_window = min(profits) if profits else 0.0
    best_window = max(profits) if profits else 0.0
    imbalance = best_window - worst_window

    score = 0.0
    score += positives * 26.0
    score -= negatives * 28.0
    score -= weak_neutral * 8.0
    score += present_count * 6.0
    score += clamp(total_trades / 6.0, 0.0, 24.0)
    score += clamp(mean_avg_profit_pct * 9.0, -18.0, 20.0)
    score += clamp(total_profit / 12.0, -18.0, 16.0)

    if present_count < 3:
        score -= 20.0
    if positives < 2:
        score -= 14.0
    if negatives >= 2:
        score -= 18.0
    if total_trades < 50:
        score -= 6.0
    if total_trades < 25:
        score -= 10.0
    if worst_window < -20.0:
        score -= 12.0
    elif worst_window < -10.0:
        score -= 6.0
    if volatility > 25.0:
        score -= 10.0
    elif volatility > 15.0:
        score -= 5.0
    if imbalance > 45.0:
        score -= 8.0
    elif imbalance > 25.0:
        score -= 4.0
    if positives == 3 and negatives == 0 and weak_neutral == 0:
        score += 14.0

    return score, positives, negatives, present_count, total_trades, total_profit, mean_avg_profit_pct


# ---------- Export helpers ----------
def export_pairs(format_kind: str) -> None:
    existing_text = list_area.get("1.0", tk.END).strip()

    if format_kind == EXPORT_WHITELIST_JSON:
        existing_whitelist, existing_blacklist = parse_existing_universal(existing_text)

        merged_whitelist = []
        seen = set()
        source = list(existing_whitelist) + list(last_output_whitelist) if existing_text else list(last_output_whitelist)

        for pair in source:
            if pair not in seen:
                seen.add(pair)
                merged_whitelist.append(pair)

        data = make_exchange_config(merged_whitelist, sorted(existing_blacklist))
        output_text = json.dumps(data, indent=2)
        default_name = "pair_whitelist.json"

    elif format_kind == EXPORT_BLACKLIST_JSON:
        if existing_text and '"pair_blacklist"' in existing_text:
            output_text = merge_blacklist_into_existing_config_text(existing_text, last_output_blacklist)
        else:
            existing_whitelist, existing_blacklist = parse_existing_universal(existing_text)
            merged_blacklist = []
            seen = set()
            for pair in list(existing_blacklist) + list(last_output_blacklist):
                if pair not in seen:
                    seen.add(pair)
                    merged_blacklist.append(pair)

            data = make_exchange_config(sorted(existing_whitelist), merged_blacklist)
            output_text = json.dumps(data, indent=2)

        default_name = "pair_blacklist.json"

    elif format_kind == EXPORT_WATCHLIST_JSON:
        if existing_text:
            output_text = merge_watchlist_into_existing_config_text(existing_text, last_output_watchlist)
        else:
            output_text = json.dumps({"watchlist_pairs": last_output_watchlist}, indent=2)
        default_name = "pair_watchlist.json"

    else:
        output_text = "\n".join(last_output_whitelist)
        default_name = "pairs.txt"

    path = filedialog.asksaveasfilename(
        title="Export file",
        initialfile=default_name,
        defaultextension=".json" if format_kind != EXPORT_PLAIN_TXT else ".txt",
        filetypes=[("JSON", "*.json"), ("Text", "*.txt"), ("All Files", "*.*")],
    )
    if not path:
        return

    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(output_text)
        messagebox.showinfo("Exported", f"Saved:\n{path}")
    except Exception as exc:
        messagebox.showerror("Export Error", str(exc))


# ---------- Result window helpers ----------
def _attach_scrollbars(container: tk.Frame, txt: tk.Text, *, width_px: int = 18) -> None:
    sb_y = tk.Scrollbar(
        container,
        orient="vertical",
        width=width_px,
        command=txt.yview,
        troughcolor="#222222",
        bg="#3a3a3a",
        activebackground="#555555",
        highlightthickness=0,
        bd=0,
        relief="flat",
    )
    txt.configure(yscrollcommand=sb_y.set)
    sb_y.pack(side="right", fill="y")
    txt.pack(side="left", fill="both", expand=True)


def create_result_section(
    parent: tk.Widget,
    title: str,
    color: str,
    items: List[str],
    row: int,
    col: int,
    rowspan: int = 1,
    height_lines: int = 22,
) -> Tuple[tk.Frame, tk.Text]:
    frame = tk.Frame(parent, bg="#222222")
    frame.grid(row=row, column=col, sticky="nsew", padx=6, pady=6, rowspan=rowspan)
    parent.grid_rowconfigure(row, weight=1)
    parent.grid_columnconfigure(col, weight=1)

    header = tk.Frame(frame, bg="#222222")
    header.pack(anchor="w", fill="x")

    tk.Label(header, text=title, font=("Arial", 12, "bold"), fg=color, bg="#222222").pack(side="left")

    body = tk.Frame(frame, bg="#222222")
    body.pack(fill="both", expand=True)

    txt = tk.Text(
        body,
        height=height_lines,
        wrap="none",
        font=("Consolas", 10),
        bg="#121212",
        fg="#e0e0e0",
        insertbackground="white",
        relief="flat",
        highlightthickness=0,
        bd=0,
    )
    txt.insert("1.0", "\n".join(items) if items else "(none)")
    txt.config(state="disabled")

    _attach_scrollbars(body, txt, width_px=18)
    text_widgets[title] = txt
    return frame, txt


def highlight_and_cycle(text_widget: tk.Text, pattern: str) -> None:
    text_widget.config(state="normal")
    text_widget.tag_remove("highlight", "1.0", tk.END)

    pattern = (pattern or "").strip()
    if not pattern:
        text_widget.config(state="disabled")
        last_scroll_positions.pop(text_widget, None)
        return

    matches: List[str] = []
    start_pos = "1.0"
    while True:
        pos = text_widget.search(pattern, start_pos, nocase=True, stopindex=tk.END)
        if not pos:
            break
        end_pos = f"{pos}+{len(pattern)}c"
        matches.append(pos)
        text_widget.tag_add("highlight", pos, end_pos)
        start_pos = end_pos

    text_widget.tag_config("highlight", background="#FF8C4F", foreground="black")

    if not matches:
        last_scroll_positions.pop(text_widget, None)
        text_widget.config(state="disabled")
        return

    last_pattern, last_pos = last_scroll_positions.get(text_widget, (None, None))
    if last_pattern != pattern or last_pos not in matches:
        next_pos = matches[0]
    else:
        idx = matches.index(last_pos)
        next_pos = matches[(idx + 1) % len(matches)]

    text_widget.see(next_pos)
    last_scroll_positions[text_widget] = (pattern, next_pos)
    text_widget.after(10, lambda: text_widget.config(state="disabled"))


def create_export_bar(parent: tk.Widget) -> None:
    bar = tk.Frame(parent, bg="#121212")
    bar.pack(fill="x", padx=10, pady=(0, 8))

    tk.Button(
        bar,
        text="Export Whitelist JSON",
        command=lambda: export_pairs(EXPORT_WHITELIST_JSON),
        bg="#2E7D32",
        fg="white",
        relief="flat",
    ).pack(side="left", padx=(0, 6))

    tk.Button(
        bar,
        text="Export Blacklist JSON",
        command=lambda: export_pairs(EXPORT_BLACKLIST_JSON),
        bg="#8E2424",
        fg="white",
        relief="flat",
    ).pack(side="left", padx=(0, 6))

    tk.Button(
        bar,
        text="Export Watchlist JSON",
        command=lambda: export_pairs(EXPORT_WATCHLIST_JSON),
        bg="#7B5C00",
        fg="white",
        relief="flat",
    ).pack(side="left", padx=(0, 6))

    tk.Button(
        bar,
        text="Export Plain TXT",
        command=lambda: export_pairs(EXPORT_PLAIN_TXT),
        bg="#444444",
        fg="white",
        relief="flat",
    ).pack(side="left", padx=(0, 6))


# ---------- Evaluate ----------
def evaluate_pairs() -> None:
    global result_win, text_widgets, last_scroll_positions
    global last_output_whitelist, last_output_blacklist, last_output_watchlist, last_output_scores

    if result_win and result_win.winfo_exists():
        result_win.destroy()

    text_widgets.clear()
    last_scroll_positions.clear()

    raw_report = text_area.get("1.0", tk.END).strip()
    if not raw_report:
        messagebox.showwarning("Missing Input", "Paste full backtest / trade history first.")
        return

    try:
        min_total_trades = int(min_total_trades_var.get())
        min_avg_profit_pct = float(min_avg_profit_pct_var.get())
        min_score = float(min_score_var.get())
        output_mode = output_mode_var.get().strip()
    except Exception:
        messagebox.showerror("Invalid Config", "One or more config values are invalid.")
        return

    if output_mode not in {OUTPUT_MODE_MERGE, OUTPUT_MODE_REPLACE, OUTPUT_MODE_INTERSECT}:
        output_mode = OUTPUT_MODE_REPLACE

    existing_whitelist, existing_blacklist = parse_existing_universal(list_area.get("1.0", tk.END))

    all_windows = parse_all_windows(raw_report)
    if not all_windows:
        messagebox.showerror("Parse Error", "Could not detect any valid backtest windows from the pasted text.")
        return

    train_k, valid_k, test_k = infer_train_valid_test_keys(all_windows)
    train_title = title_for_window("TRAIN", train_k)
    valid_title = title_for_window("VALID", valid_k)
    test_title = title_for_window("TEST", test_k)

    train_map = all_windows.get(train_k, {}) if train_k is not None else {}
    valid_map = all_windows.get(valid_k, {}) if valid_k is not None else {}
    test_map = all_windows.get(test_k, {}) if test_k is not None else {}

    train_pairs = sorted(train_map.keys())
    valid_pairs = sorted(valid_map.keys())
    test_pairs = sorted(test_map.keys())

    all_pairs = set(train_map.keys()) | set(valid_map.keys()) | set(test_map.keys())

    group_a: List[str] = []
    group_b: List[str] = []
    group_c: List[str] = []
    group_d: List[str] = []
    group_e: List[str] = []
    group_f: List[str] = []

    blacklist_candidates: List[str] = []
    watchlist_candidates: List[str] = []
    score_lines: List[str] = []

    for pair in sorted(all_pairs):
        total_trades = pair_total_trades_across_windows(pair, train_map, valid_map, test_map)
        present_count = pair_present_count(pair, train_map, valid_map, test_map)
        profits_existing = pair_profit_list_existing(pair, train_map, valid_map, test_map)
        total_profit = sum(profits_existing)
        mean_avg_profit_pct = avg(pair_avg_profit_list_existing(pair, train_map, valid_map, test_map))

        assigned_group, raw_positive_count, raw_negative_count, raw_neutral_count = classify_pair_simple(
            pair, train_map, valid_map, test_map
        )

        score, _, _, _, _, _, _ = pair_score(
            pair, train_map, valid_map, test_map, min_avg_profit_pct
        )

        score_lines.append(
            build_score_line(
                pair,
                score,
                raw_positive_count,
                raw_negative_count,
                present_count,
                total_trades,
                total_profit,
                mean_avg_profit_pct,
            )
        )

        if assigned_group == "A":
            suffix = "   # 3 positive"
            if total_trades < min_total_trades:
                suffix += f" | trades={total_trades}"
            group_a.append(f'"{pair}",{suffix}')

        elif assigned_group == "B":
            suffix = "   # 2 positive, 0 negative"
            if total_trades < min_total_trades:
                suffix += f" | trades={total_trades}"
            group_b.append(f'"{pair}",{suffix}')

        elif assigned_group == "C":
            comment = "1 positive, 0 negative, incomplete"
            if total_trades < min_total_trades:
                comment += f" | trades={total_trades}"
            group_c.append(f'"{pair}",   # {comment}')

        elif assigned_group == "D":
            suffix = "   # 2 positive, 1 negative"
            if total_trades < min_total_trades:
                suffix += f" | trades={total_trades}"
            group_d.append(f'"{pair}",{suffix}')
            watchlist_candidates.append(pair)

        elif assigned_group == "E":
            suffix = "   # 1 positive, 1 negative"
            if total_trades < min_total_trades:
                suffix += f" | trades={total_trades}"
            group_e.append(f'"{pair}",{suffix}')
            watchlist_candidates.append(pair)

        elif assigned_group == "F":
            comment = f"{raw_positive_count} positive, {raw_negative_count} negative"
            if total_trades < min_total_trades:
                comment += f" | trades={total_trades}"
            group_f.append(f'"{pair}",   # {comment}')
            blacklist_candidates.append(pair)

    blacklist_candidates = sorted(set(blacklist_candidates))
    watchlist_candidates = sorted(set(watchlist_candidates) - set(blacklist_candidates))
    score_lines = sorted(set(score_lines), reverse=True)

    group_a_clean = sorted({item.split(",")[0].strip().strip('"') for item in group_a})
    group_b_clean = sorted({item.split(",")[0].strip().strip('"') for item in group_b})
    group_c_clean = sorted({item.split(",")[0].strip().strip('"') for item in group_c})
    blacklist_set = set(blacklist_candidates) | set(existing_blacklist)

    # Whitelist = A + B + C
    selected = set(group_a_clean) | set(group_b_clean) | set(group_c_clean)
    selected -= blacklist_set

    if output_mode == OUTPUT_MODE_REPLACE:
        final_pairs = sorted(selected)
    elif output_mode == OUTPUT_MODE_INTERSECT:
        final_pairs = sorted(existing_whitelist & selected)
    else:
        final_pairs = sorted(existing_whitelist | selected)

    last_output_whitelist = final_pairs
    last_output_blacklist = blacklist_candidates
    last_output_watchlist = watchlist_candidates
    last_output_scores = score_lines

    # ---------- Result window ----------
    WINDOWS_W = 240
    GROUPS_W = 520
    OUTPUTS_W = 360
    SCORES_W = 960

    OUTER_PAD_X = 10
    INNER_GAP = 6
    RESULT_H = 1040

    exact_width = (
        WINDOWS_W
        + GROUPS_W
        + OUTPUTS_W
        + SCORES_W
        + (INNER_GAP * 6)
        + (OUTER_PAD_X * 2)
    )

    result_win = tk.Toplevel(root)
    result_win.title("Evaluation Result")
    result_win.geometry(f"{exact_width}x{RESULT_H}+0+0")
    result_win.minsize(exact_width, 820)
    result_win.config(bg="#121212")

    result_parent = result_win

    search_frame = tk.Frame(result_parent, bg="#121212")
    search_frame.pack(fill="x", padx=10, pady=(8, 4))

    tk.Label(search_frame, text="Search Pair:", font=("Arial", 9), fg="#e0e0e0", bg="#121212").pack(side="left")

    search_var = tk.StringVar()
    search_entry = tk.Entry(
        search_frame,
        textvariable=search_var,
        font=("Arial", 9),
        fg="#e0e0e0",
        bg="#222222",
        insertbackground="white",
        relief="flat",
        bd=1,
    )
    search_entry.pack(side="left", fill="x", expand=True, padx=(6, 6))

    search_btn = tk.Button(search_frame, text="Highlight", bg="#444444", fg="#eeeeee", relief="flat", bd=1)
    search_btn.pack(side="left")

    summary_label = tk.Label(
        search_frame,
        text=(
            f"Mode: {output_mode} | Min total trades: {min_total_trades} | "
            f"Min avg profit %: {min_avg_profit_pct:.2f} | Min score: {min_score:.2f}"
        ),
        font=("Arial", 9),
        fg="#a8a8a8",
        bg="#121212",
    )
    summary_label.pack(side="left", padx=(12, 0))

    create_export_bar(result_parent)

    columns = tk.Frame(result_parent, bg="#121212")
    columns.pack(fill="both", expand=True, padx=10, pady=(2, 10))
    columns.grid_rowconfigure(0, weight=1)

    columns.grid_columnconfigure(0, minsize=WINDOWS_W, weight=0)
    columns.grid_columnconfigure(1, minsize=GROUPS_W, weight=0)
    columns.grid_columnconfigure(2, minsize=OUTPUTS_W, weight=0)
    columns.grid_columnconfigure(3, minsize=SCORES_W, weight=0)

    col_windows = tk.Frame(columns, bg="#121212", width=WINDOWS_W)
    col_groups = tk.Frame(columns, bg="#121212", width=GROUPS_W)
    col_outputs = tk.Frame(columns, bg="#121212", width=OUTPUTS_W)
    col_scores = tk.Frame(columns, bg="#121212", width=SCORES_W)

    for col in (col_windows, col_groups, col_outputs, col_scores):
        col.grid_propagate(False)
        col.pack_propagate(False)

    col_windows.grid(row=0, column=0, sticky="ns", padx=(0, 6))
    col_groups.grid(row=0, column=1, sticky="ns", padx=(6, 6))
    col_outputs.grid(row=0, column=2, sticky="ns", padx=(6, 6))
    col_scores.grid(row=0, column=3, sticky="ns", padx=(6, 0))

    win_parent = tk.Frame(col_windows, bg="#121212")
    win_parent.pack(fill="both", expand=True)
    win_parent.grid_columnconfigure(0, weight=1)
    for row in range(3):
        win_parent.grid_rowconfigure(row, weight=1)

    create_result_section(win_parent, train_title, "#4aa3ff", [f'"{p}",' for p in train_pairs], 0, 0, height_lines=13)
    create_result_section(win_parent, valid_title, "#763dfd", [f'"{p}",' for p in valid_pairs], 1, 0, height_lines=13)
    create_result_section(win_parent, test_title, "#eb016e", [f'"{p}",' for p in test_pairs], 2, 0, height_lines=13)

    group_defs = [
        {"title": TITLE_GA, "color": "#09ff00", "items": group_a},
        {"title": TITLE_GB, "color": "#ffd166", "items": group_b},
        {"title": TITLE_GC, "color": "#66d9ef", "items": group_c},
        {"title": TITLE_GD, "color": "#ff9f43", "items": group_d},
        {"title": TITLE_GE, "color": "#c77dff", "items": group_e},
        {"title": TITLE_GF, "color": "#ff5555", "items": group_f},
    ]

    stack = tk.Frame(col_groups, bg="#121212")
    stack.pack(fill="both", expand=True)
    stack.grid_columnconfigure(0, weight=1)
    for row in range(len(group_defs)):
        stack.grid_rowconfigure(row, weight=1)

    out_stack = tk.Frame(col_outputs, bg="#121212")
    out_stack.pack(fill="both", expand=True)
    out_stack.grid_columnconfigure(0, weight=1)
    for row in range(3):
        out_stack.grid_rowconfigure(row, weight=1)

    score_stack = tk.Frame(col_scores, bg="#121212")
    score_stack.pack(fill="both", expand=True)
    score_stack.grid_columnconfigure(0, weight=1)
    score_stack.grid_rowconfigure(0, weight=1)

    _, out_text = create_result_section(out_stack, TITLE_FINAL, "cyan", [f'"{p}",' for p in final_pairs], 0, 0, height_lines=14)
    _, wl_text = create_result_section(out_stack, TITLE_WL, "#ffd166", [f'"{p}",' for p in watchlist_candidates], 1, 0, height_lines=12)
    _, bl_text = create_result_section(out_stack, TITLE_BL, "#ff5555", [f'"{p}",' for p in blacklist_candidates], 2, 0, height_lines=12)

    create_result_section(score_stack, "📊 Pair Scores", "#77ddff", score_lines, 0, 0, height_lines=48)

    for idx, group in enumerate(group_defs):
        create_result_section(
            stack,
            group["title"],
            group["color"],
            group["items"],
            idx,
            0,
            height_lines=10,
        )

    for widget in text_widgets.values():
        create_context_menu_valid(widget)
    create_context_menu_valid(out_text)
    create_context_menu_valid(wl_text)
    create_context_menu_valid(bl_text)

    def on_search(event: Optional[tk.Event] = None) -> None:
        pattern = search_var.get().strip()
        widgets = list(text_widgets.values()) + [out_text, bl_text, wl_text]
        for widget in widgets:
            highlight_and_cycle(widget, pattern)

    search_entry.bind("<Return>", on_search)
    search_btn.config(command=on_search)
    result_parent.bind("<F3>", on_search)


# ---------- Main UI ----------
def clear_input_boxes() -> None:
    text_area.delete("1.0", tk.END)
    list_area.delete("1.0", tk.END)


def style_panel_grid(panel: tk.Frame) -> None:
    panel.grid_columnconfigure(0, weight=1)
    panel.grid_columnconfigure(1, weight=0)


root = tk.Tk()
root.title("Pair Evaluator")
root.config(bg="#121212")

window_width, window_height = 900, 1180
screen_width = root.winfo_screenwidth()
x = max(screen_width - window_width, 0)
root.geometry(f"{window_width}x{window_height}+{x}+0")

top_frame = tk.Frame(root, bg="#121212")
top_frame.pack(fill="x", padx=10, pady=8)

tk.Button(
    top_frame,
    text="Evaluate",
    command=evaluate_pairs,
    font=("Arial", 12, "bold"),
    bg="#4CAF50",
    fg="white",
).grid(row=0, column=0, padx=(0, 12), sticky="w")

tk.Button(
    top_frame,
    text="Clear Boxes",
    command=clear_input_boxes,
    font=("Arial", 12),
    bg="#D32F2F",
    fg="white",
).grid(row=0, column=1, padx=(12, 18), sticky="w")

tk.Label(
    top_frame,
    text="Paste Full Trade History Here:",
    font=("Arial", 12),
    fg="#e0e0e0",
    bg="#121212",
).grid(row=0, column=2, sticky="ew")

top_frame.grid_columnconfigure(2, weight=1)

# UI vars
min_total_trades_var = tk.IntVar(value=DEFAULT_MIN_TOTAL_TRADES_ALL_WINDOWS)
min_avg_profit_pct_var = tk.DoubleVar(value=DEFAULT_MIN_AVG_PROFIT_PCT)
min_score_var = tk.DoubleVar(value=DEFAULT_MIN_SCORE)
output_mode_var = tk.StringVar(value=DEFAULT_OUTPUT_MODE)

config_row = tk.Frame(root, bg="#121212")
config_row.pack(fill="x", padx=10, pady=(0, 4))
for col in range(3):
    config_row.grid_columnconfigure(col, weight=1)

panel_base = tk.Frame(config_row, bg="#1b1b1b", highlightthickness=1, highlightbackground="#3a3a3a")
panel_bl = tk.Frame(config_row, bg="#1b1b1b", highlightthickness=1, highlightbackground="#3a3a3a")
panel_out = tk.Frame(config_row, bg="#1b1b1b", highlightthickness=1, highlightbackground="#3a3a3a")

panel_base.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
panel_bl.grid(row=0, column=1, sticky="nsew", padx=(6, 6))
panel_out.grid(row=0, column=2, sticky="nsew", padx=(6, 0))

style_panel_grid(panel_base)
tk.Label(panel_base, text="BASE / Survivor Rules", font=("Arial", 10, "bold"), fg="#9fd3ff", bg="#1b1b1b").grid(row=0, column=0, columnspan=2, sticky="w", padx=8, pady=(4, 2))
tk.Label(panel_base, text="Min total trades:", fg="#e0e0e0", bg="#1b1b1b", font=("Arial", 9)).grid(row=1, column=0, sticky="w", padx=10, pady=(0, 3))
tk.Spinbox(panel_base, from_=0, to=999999, width=8, textvariable=min_total_trades_var, bg="#222222", fg="#e0e0e0", insertbackground="white", relief="flat").grid(row=1, column=1, sticky="w", padx=(6, 10), pady=(0, 3))
tk.Label(panel_base, text="Min avg profit %:", fg="#e0e0e0", bg="#1b1b1b", font=("Arial", 9)).grid(row=2, column=0, sticky="w", padx=10, pady=(0, 3))
tk.Spinbox(panel_base, from_=-100.0, to=100.0, increment=0.05, width=8, textvariable=min_avg_profit_pct_var, bg="#222222", fg="#e0e0e0", insertbackground="white", relief="flat").grid(row=2, column=1, sticky="w", padx=(6, 10), pady=(0, 3))
tk.Label(panel_base, text="Min score (display only):", fg="#e0e0e0", bg="#1b1b1b", font=("Arial", 9)).grid(row=3, column=0, sticky="w", padx=10, pady=(0, 3))
tk.Spinbox(panel_base, from_=-999.0, to=999.0, increment=1.0, width=8, textvariable=min_score_var, bg="#222222", fg="#e0e0e0", insertbackground="white", relief="flat").grid(row=3, column=1, sticky="w", padx=(6, 10), pady=(0, 3))
tk.Label(panel_base, text="Whitelist = A + B + C", fg="#a8a8a8", bg="#1b1b1b", font=("Arial", 9)).grid(row=5, column=0, columnspan=2, sticky="w", padx=10, pady=(0, 4))

style_panel_grid(panel_bl)
tk.Label(panel_bl, text="WATCH / BLACKLIST", font=("Arial", 10, "bold"), fg="#ff9f9f", bg="#1b1b1b").grid(row=0, column=0, columnspan=2, sticky="w", padx=8, pady=(4, 2))
tk.Label(panel_bl, text="Group D + E => Watchlist", fg="#e0e0e0", bg="#1b1b1b", font=("Arial", 9)).grid(row=1, column=0, columnspan=2, sticky="w", padx=10, pady=(0, 3))
tk.Label(panel_bl, text="Group F => Blacklist", fg="#e0e0e0", bg="#1b1b1b", font=("Arial", 9)).grid(row=2, column=0, columnspan=2, sticky="w", padx=10, pady=(0, 3))
tk.Label(panel_bl, text="A+B+C whitelist | D+E watchlist | F blacklist", fg="#a8a8a8", bg="#1b1b1b", font=("Arial", 9)).grid(row=3, column=0, columnspan=2, sticky="w", padx=10, pady=(0, 3))

style_panel_grid(panel_out)
tk.Label(panel_out, text="OUTPUT / Final Merge Mode", font=("Arial", 10, "bold"), fg="#9fffb3", bg="#1b1b1b").grid(row=0, column=0, columnspan=2, sticky="w", padx=8, pady=(4, 2))
tk.Label(panel_out, text="Final output mode:", fg="#e0e0e0", bg="#1b1b1b", font=("Arial", 9)).grid(row=1, column=0, sticky="w", padx=10, pady=(0, 3))
mode_menu = tk.OptionMenu(panel_out, output_mode_var, OUTPUT_MODE_MERGE, OUTPUT_MODE_REPLACE, OUTPUT_MODE_INTERSECT)
mode_menu.config(bg="#222222", fg="#e0e0e0", activebackground="#333333", relief="flat", highlightthickness=0)
mode_menu["menu"].config(bg="#222222", fg="#e0e0e0", activebackground="#333333")
mode_menu.grid(row=1, column=1, sticky="w", padx=(6, 10), pady=(0, 3))
tk.Label(panel_out, text="Merge = old + selected", fg="#a8a8a8", bg="#1b1b1b", font=("Arial", 9)).grid(row=2, column=0, columnspan=2, sticky="w", padx=10)
tk.Label(panel_out, text="Replace = selected only", fg="#a8a8a8", bg="#1b1b1b", font=("Arial", 9)).grid(row=3, column=0, columnspan=2, sticky="w", padx=10)
tk.Label(panel_out, text="Intersect = old ∩ selected", fg="#a8a8a8", bg="#1b1b1b", font=("Arial", 9)).grid(row=4, column=0, columnspan=2, sticky="w", padx=10)
tk.Label(panel_out, text="Single strategy mode only.", fg="#a8a8a8", bg="#1b1b1b", font=("Arial", 9)).grid(row=5, column=0, columnspan=2, sticky="w", padx=10, pady=(0, 4))

text_area = scrolledtext.ScrolledText(root, width=160, height=28, font=("Consolas", 10), bg="#121212", fg="#e0e0e0", insertbackground="white")
text_area.pack(padx=10, pady=(0, 4), fill="both", expand=True)

tk.Label(root, text="Paste Existing Pair Config / Universal List:", font=("Arial", 12), fg="#e0e0e0", bg="#121212").pack(fill="x", padx=10, pady=(0, 4))
list_area = scrolledtext.ScrolledText(root, width=120, height=6, font=("Consolas", 10), bg="#121212", fg="#e0e0e0", insertbackground="white")
list_area.pack(padx=10, pady=(0, 4), fill="x")

create_context_menu(text_area)
create_context_menu(list_area)

root.mainloop()