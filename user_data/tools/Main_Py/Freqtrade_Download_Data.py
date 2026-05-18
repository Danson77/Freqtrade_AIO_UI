#!/usr/bin/env python3
import csv
import ctypes
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any, Set

try:
    import pandas as pd
except ImportError:
    print("pandas is required. Install it with: pip install pandas pyarrow send2trash")
    sys.exit(1)

try:
    import pyarrow  # noqa: F401
except ImportError:
    print("pyarrow is required for reading .feather files. Install it with: pip install pyarrow")
    sys.exit(1)

try:
    from send2trash import send2trash
except ImportError:
    print("send2trash is required for recycle bin delete. Install it with: pip install send2trash")
    sys.exit(1)


# =====================================================================================
# Defaults
# =====================================================================================
EXPECTED_PATH = r"N:\Freqtrade"
CONTAINER_NAME = "Freqtrad_Data_Download"

DEFAULT_CONFIG = "user_data/data_download.json"
DEFAULT_EXCHANGE = "kucoin"
DEFAULT_DATA_FORMAT = "feather"
DEFAULT_EXPORT_DIR = os.path.join("user_data", "data", "data_audit")

DEFAULT_TIMERANGE = "20240101-20260410"
DEFAULT_INCLUDE_INACTIVE_PAIRS = False
DEFAULT_USE_ERASE = False
DEFAULT_DOWNLOAD_TIMEFRAMES = ["5m", "1h", "1d"]

# Coverage thresholds for clean pairlist
DEFAULT_MIN_COVERAGE_BY_TF = {
    "5m": 80.0,
    "1h": 80.0,
    "1d": 40.0,
}

DOCKER_SERVICE = "freqtrade"

TIMEFRAME_TO_MINUTES = {
    "1m": 1,
    "3m": 3,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "2h": 120,
    "4h": 240,
    "6h": 360,
    "8h": 480,
    "12h": 720,
    "1d": 1440,
}

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
TIMERANGE_ROW_RE = re.compile(
    r"^\s*│\s*(?P<pair>.*?)\s*│\s*(?P<timeframe>.*?)\s*│\s*(?P<type>.*?)\s*│\s*"
    r"(?P<start>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s*│\s*"
    r"(?P<end>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s*│\s*"
    r"(?P<count>\d+)\s*│\s*$"
)
LIST_DATA_ROW_RE = re.compile(
    r"^\s*│\s*(?P<pair>.*?)\s*│\s*(?P<timeframes>.*?)\s*│\s*(?P<type>.*?)\s*│\s*$"
)
LOG_PREFIX_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})\s*-\s*(?P<logger>.*?)\s*-\s*(?P<level>INFO|WARNING|ERROR|CRITICAL|DEBUG)\s*-\s*(?P<msg>.*)$"
)
DOCKER_TIME_WARNING_RE = re.compile(
    r'^(time=".*?")\s+(level=warning)\s+(msg=.*)$',
    re.IGNORECASE
)


# =====================================================================================
# Colors
# =====================================================================================
RESET = "\033[0m"
RED = "\033[31m"
WHITE = "\033[37m"
YELLOW = "\033[33m"
GREEN = "\033[32m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"


def enable_windows_ansi():
    if os.name != "nt":
        return
    try:
        kernel32 = ctypes.windll.kernel32
        for std_handle in (-11, -12):
            handle = kernel32.GetStdHandle(std_handle)
            if handle in (0, -1):
                continue
            mode = ctypes.c_uint32()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        pass


def c(text: str, color: str) -> str:
    return f"{color}{text}{RESET}"


def write_error_line(msg: str):
    print(c(msg, RED))


def write_info_line(msg: str):
    print(c(msg, WHITE))


def write_warning_line(msg: str):
    print(c(msg, YELLOW))


def write_action_line(msg: str):
    print(c(msg, GREEN))


def write_tell(msg: str):
    print(c(msg, BLUE))


def write_section_line(msg: str):
    print(c(msg, CYAN))


# =====================================================================================
# Models
# =====================================================================================
@dataclass
class ListDataRow:
    pair: str
    timeframes: str
    market_type: str


@dataclass
class TimerangeRow:
    pair: str
    timeframe: str
    market_type: str
    start: str
    end: str
    count: int


@dataclass
class AuditRow:
    pair: str
    timeframe: str
    exists: bool
    status: str
    first_candle: str
    last_candle: str
    first_delta_days: Optional[float]
    last_delta_days: Optional[float]
    candle_count: int
    expected_candles: int
    coverage_pct: Optional[float]
    file_path: str


# =====================================================================================
# Basic helpers
# =====================================================================================
def strip_ansi(value: str) -> str:
    value = ANSI_RE.sub("", value or "")
    return value.replace("\r", "").replace("\x00", "")


def ensure_working_directory():
    current = os.getcwd()
    if os.path.normcase(current) != os.path.normcase(EXPECTED_PATH):
        write_warning_line(f"Switching to expected working directory: {EXPECTED_PATH}")
        try:
            os.chdir(EXPECTED_PATH)
        except Exception as e:
            write_error_line(f"Failed to change directory to {EXPECTED_PATH}: {e}")
            sys.exit(1)


def ensure_export_dir() -> Path:
    p = Path(EXPECTED_PATH) / DEFAULT_EXPORT_DIR
    p.mkdir(parents=True, exist_ok=True)
    return p


def sanitize_pair_for_filename(pair: str) -> str:
    return pair.replace("/", "_").replace(":", "_")


def normalize_path_for_compare(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def read_yes_no(prompt: str, default: Optional[bool] = None) -> bool:
    while True:
        suffix = " [y/n]"
        if default is True:
            suffix = " [Y/n]"
        elif default is False:
            suffix = " [y/N]"

        write_warning_line(prompt + suffix)
        raw = input().strip().lower()

        if raw == "" and default is not None:
            return default
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False

        write_error_line("Invalid input. Enter yes or no.")


def read_timerange_custom(default_value: str = DEFAULT_TIMERANGE) -> str:
    while True:
        write_action_line(f"Enter custom timerange (YYYYMMDD-YYYYMMDD) [{default_value}]")
        raw = input().strip()
        if raw == "":
            raw = default_value
        if re.fullmatch(r"\d{8}-\d{8}", raw):
            return raw
        write_error_line("Invalid timerange format.")


def select_timerange() -> str:
    while True:
        write_action_line("Select timerange:")
        write_info_line("1. DEFAULT  [20240101-20260410]")
        write_info_line("2. CUSTOM")

        choice = input("Enter your choice (1-2): ").strip()

        if choice == "1":
            write_info_line(f"Selected: DEFAULT ({DEFAULT_TIMERANGE})")
            return DEFAULT_TIMERANGE

        if choice == "2":
            tr = read_timerange_custom(DEFAULT_TIMERANGE)
            write_info_line(f"Selected: CUSTOM ({tr})")
            return tr

        write_error_line("Invalid input. Choose 1 or 2.")


def select_timeframes(defaults: List[str]) -> List[str]:
    valid_sorted = sorted(TIMEFRAME_TO_MINUTES.keys(), key=lambda x: TIMEFRAME_TO_MINUTES[x])

    while True:
        write_action_line("Select timeframe mode:")
        write_info_line("1. STANDARD [5m 1h 1d]")
        write_info_line("2. CUSTOM")

        choice = input("Enter your choice (1-2): ").strip()

        if choice == "1":
            return list(defaults)

        if choice == "2":
            write_action_line(f"Enter timeframes separated by spaces. Available: 1m 3m 5m 15m 30m 1h 2h 4h 6h 8h 12h 1d")
            raw = input().strip().lower()
            if raw == "":
                raw = " ".join(defaults)

            items = [x for x in raw.split() if x]
            if not items:
                write_error_line("At least one timeframe required.")
                continue

            bad = [x for x in items if x not in TIMEFRAME_TO_MINUTES]
            if bad:
                write_error_line(
                    f"Invalid timeframe(s): {', '.join(bad)}. Allowed: {', '.join(valid_sorted)}"
                )
                continue
            return items

        write_error_line("Invalid input. Choose 1 or 2.")


def parse_timerange(timerange: str) -> Tuple[datetime, datetime]:
    m = re.fullmatch(r"(\d{8})-(\d{8})", timerange)
    if not m:
        raise ValueError("Timerange must be YYYYMMDD-YYYYMMDD")
    start = datetime.strptime(m.group(1), "%Y%m%d").replace(tzinfo=timezone.utc)
    end = datetime.strptime(m.group(2), "%Y%m%d").replace(tzinfo=timezone.utc)
    return start, end


def timeframe_to_timedelta(tf: str) -> timedelta:
    if tf not in TIMEFRAME_TO_MINUTES:
        raise ValueError(f"Unsupported timeframe: {tf}")
    return timedelta(minutes=TIMEFRAME_TO_MINUTES[tf])


def expected_candles_for_range(start: datetime, end: datetime, tf: str) -> int:
    step = timeframe_to_timedelta(tf)
    total_seconds = (end - start).total_seconds()
    if total_seconds <= 0:
        return 0
    return int(total_seconds // step.total_seconds())


def make_unique_export_name(prefix: str, suffix: str) -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{ts}{suffix}"


def choose_file_from_folder(folder: Path, patterns: List[str], title: str) -> Optional[Path]:
    found: List[Path] = []
    seen = set()

    for pattern in patterns:
        for p in sorted(folder.glob(pattern), key=lambda x: x.stat().st_mtime, reverse=True):
            rp = str(p.resolve()).lower()
            if rp not in seen and p.is_file():
                seen.add(rp)
                found.append(p)

    if not found:
        write_warning_line(f"No matching export files found in: {folder}")
        return None

    write_action_line(title)
    for idx, file in enumerate(found, start=1):
        ts = datetime.fromtimestamp(file.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        write_info_line(f"{idx}. {file.name}   [{ts}]")
    write_info_line("0. Cancel")

    while True:
        raw = input(f"Choose file (0-{len(found)}): ").strip()
        if raw == "0":
            return None
        if raw.isdigit():
            i = int(raw)
            if 1 <= i <= len(found):
                chosen = found[i - 1]
                write_tell(f"Selected file: {chosen}")
                return chosen
        write_error_line("Invalid choice.")


# =====================================================================================
# Loose JSON loader for freqtrade config files
# =====================================================================================
def strip_json_comments_and_trailing_commas(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)

    cleaned_lines = []
    for line in text.splitlines():
        in_string = False
        escaped = False
        out = []
        i = 0
        while i < len(line):
            ch = line[i]
            if escaped:
                out.append(ch)
                escaped = False
            elif ch == "\\" and in_string:
                out.append(ch)
                escaped = True
            elif ch == '"':
                out.append(ch)
                in_string = not in_string
            elif not in_string and i + 1 < len(line) and line[i] == "/" and line[i + 1] == "/":
                break
            else:
                out.append(ch)
            i += 1
        cleaned_lines.append("".join(out))

    text = "\n".join(cleaned_lines)
    text = re.sub(r",(\s*[}\]])", r"\1", text)
    return text


def load_json_loose(path: Path) -> Dict[str, Any]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    cleaned = strip_json_comments_and_trailing_commas(raw)
    return json.loads(cleaned)


# =====================================================================================
# Docker commands
# =====================================================================================
def build_download_command(
    timerange: str,
    timeframes: List[str],
    include_inactive_pairs: bool,
    erase: bool,
) -> List[str]:
    cmd = [
        "docker-compose",
        "run",
        "--name",
        CONTAINER_NAME,
        "--rm",
        DOCKER_SERVICE,
        "download-data",
        "--exchange",
        DEFAULT_EXCHANGE,
        "--config",
        DEFAULT_CONFIG,
        "--data-format-ohlcv",
        DEFAULT_DATA_FORMAT,
        "--timerange",
        timerange,
        "--timeframes",
    ] + timeframes

    if include_inactive_pairs:
        cmd.append("--include-inactive-pairs")
    if erase:
        cmd.append("--erase")

    return cmd


def build_list_data_command() -> List[str]:
    return [
        "docker-compose",
        "run",
        "--name",
        CONTAINER_NAME,
        "--rm",
        DOCKER_SERVICE,
        "list-data",
        "--exchange",
        DEFAULT_EXCHANGE,
    ]


def build_list_timerange_command() -> List[str]:
    return [
        "docker-compose",
        "run",
        "--name",
        CONTAINER_NAME,
        "--rm",
        DOCKER_SERVICE,
        "list-data",
        "--show-timerange",
        "--exchange",
        DEFAULT_EXCHANGE,
    ]


# =====================================================================================
# Streaming / colorized output
# =====================================================================================
def colorize_docker_line(raw_line: str) -> str:
    line = raw_line.rstrip("\n")
    clean = strip_ansi(line)

    if not clean.strip():
        return ""

    m = DOCKER_TIME_WARNING_RE.match(clean)
    if m:
        ts, lvl, msg = m.groups()
        return f"{c(ts, CYAN)} {c(lvl, YELLOW)} {c(msg, WHITE)}"

    lm = LOG_PREFIX_RE.match(clean)
    if lm:
        ts = c(lm.group("ts"), YELLOW)
        logger = c(lm.group("logger"), MAGENTA)

        lvl_raw = lm.group("level")
        if lvl_raw == "INFO":
            lvl = c(lvl_raw, BLUE)
        elif lvl_raw == "WARNING":
            lvl = c(lvl_raw, YELLOW)
        elif lvl_raw in ("ERROR", "CRITICAL"):
            lvl = c(lvl_raw, RED)
        else:
            lvl = c(lvl_raw, WHITE)

        msg = c(lm.group("msg"), WHITE)
        return f"{ts} - {logger} - {lvl} - {msg}"

    if clean.startswith(" Container "):
        out = clean
        out = out.replace(" Creating", c(" Creating", GREEN))
        out = out.replace(" Created", c(" Created", GREEN))
        out = out.replace(" Starting", c(" Starting", GREEN))
        out = out.replace(" Started", c(" Started", GREEN))
        out = out.replace(" Removing", c(" Removing", YELLOW))
        out = out.replace(" Removed", c(" Removed", YELLOW))
        return out

    if clean.startswith("┏") or clean.startswith("┡") or clean.startswith("└") or clean.startswith("│"):
        return c(clean, WHITE)

    if "ERROR -" in clean or clean.startswith("ERROR"):
        return c(clean, RED)

    if "WARNING -" in clean or "level=warning" in clean.lower():
        return c(clean, YELLOW)

    return c(clean, WHITE)


def run_command_live_tty(cmd: List[str]) -> int:
    write_action_line("Running command:")
    print(c(" ".join(cmd), GREEN))
    write_section_line("-" * 100)

    env = os.environ.copy()
    env["PY_COLORS"] = "1"
    env["CLICOLOR"] = "1"
    env["CLICOLOR_FORCE"] = "1"
    env["FORCE_COLOR"] = "1"
    env["TERM"] = env.get("TERM", "xterm-256color")

    try:
        process = subprocess.Popen(
            cmd,
            cwd=EXPECTED_PATH,
            env=env,
            stdout=None,   # inherit real terminal
            stderr=None,   # inherit real terminal
            stdin=None,
        )
        rc = process.wait()
        write_section_line("-" * 100)
        return rc

    except Exception as e:
        write_error_line(f"Failed to run docker command: {e}")
        return 1

def run_command_stream_capture(cmd: List[str], log_file: Optional[Path] = None) -> Tuple[int, str]:
    write_action_line("Running command:")
    print(c(" ".join(cmd), GREEN))
    write_section_line("-" * 100)

    env = os.environ.copy()
    env["PY_COLORS"] = "1"
    env["CLICOLOR"] = "1"
    env["CLICOLOR_FORCE"] = "1"
    env["FORCE_COLOR"] = "1"
    env["TERM"] = env.get("TERM", "xterm-256color")

    log_handle = None
    try:
        if log_file is not None:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            log_handle = log_file.open("w", encoding="utf-8", newline="")

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            universal_newlines=True,
            cwd=EXPECTED_PATH,
            env=env,
        )

        if process.stdout is None:
            raise RuntimeError("Could not open process stdout")

        captured: List[str] = []

        for raw_line in process.stdout:
            captured.append(raw_line)
            if log_handle is not None:
                log_handle.write(raw_line)
                log_handle.flush()

            colored = colorize_docker_line(raw_line)
            if colored:
                print(colored)

        rc = process.wait()
        write_section_line("-" * 100)
        return rc, "".join(captured)

    except Exception as e:
        write_error_line(f"Failed to run docker command: {e}")
        return 1, f"ERROR: {e}"

    finally:
        if log_handle is not None:
            log_handle.close()


# =====================================================================================
# Parsers
# =====================================================================================
def parse_list_data_output(output: str) -> List[ListDataRow]:
    rows: List[ListDataRow] = []
    for line in strip_ansi(output).splitlines():
        m = LIST_DATA_ROW_RE.match(line)
        if not m:
            continue
        pair = m.group("pair").strip()
        timeframes = m.group("timeframes").strip()
        market_type = m.group("type").strip()
        if pair.lower() == "pair":
            continue
        rows.append(ListDataRow(pair=pair, timeframes=timeframes, market_type=market_type))
    return rows


def parse_list_data_timerange_output(output: str) -> List[TimerangeRow]:
    rows: List[TimerangeRow] = []
    for line in strip_ansi(output).splitlines():
        m = TIMERANGE_ROW_RE.match(line)
        if not m:
            continue
        rows.append(
            TimerangeRow(
                pair=m.group("pair").strip(),
                timeframe=m.group("timeframe").strip(),
                market_type=m.group("type").strip(),
                start=m.group("start").strip(),
                end=m.group("end").strip(),
                count=int(m.group("count").strip()),
            )
        )
    return rows


def normalize_timerange_csv_columns(df: pd.DataFrame) -> pd.DataFrame:
    rename_map = {}
    for col in df.columns:
        orig = str(col)
        clean = orig.strip().lower().replace(" ", "_")

        if clean in {"market_ty", "market_t", "market", "markettype"}:
            clean = "market_type"
        elif clean in {"tf", "time_frame"}:
            clean = "timeframe"

        rename_map[orig] = clean

    return df.rename(columns=rename_map)


def load_timerange_csv(csv_path: Path) -> List[TimerangeRow]:
    df = pd.read_csv(csv_path)
    df = normalize_timerange_csv_columns(df)

    required = {"pair", "timeframe", "market_type", "start", "end", "count"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"CSV missing required columns: {', '.join(sorted(missing))}")

    rows: List[TimerangeRow] = []
    for _, r in df.iterrows():
        pair = str(r["pair"]).strip()
        timeframe = str(r["timeframe"]).strip()
        market_type = str(r["market_type"]).strip()
        start = str(r["start"]).strip()
        end = str(r["end"]).strip()

        try:
            count = int(float(r["count"]))
        except Exception:
            count = 0

        if not pair or not timeframe:
            continue

        rows.append(
            TimerangeRow(
                pair=pair,
                timeframe=timeframe,
                market_type=market_type,
                start=start,
                end=end,
                count=count,
            )
        )
    return rows


# =====================================================================================
# Exports
# =====================================================================================
def export_list_data_rows(rows: List[ListDataRow], export_dir: Path, filename: str) -> Path:
    path = export_dir / filename
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["pair", "timeframes", "market_type"])
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))
    return path


def export_timerange_rows(rows: List[TimerangeRow], export_dir: Path, filename: str) -> Path:
    path = export_dir / filename
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["pair", "timeframe", "market_type", "start", "end", "count"],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))
    return path


def export_audit(rows: List[AuditRow], export_dir: Path, prefix: str):
    csv_name = make_unique_export_name(prefix, "_audit.csv")
    json_name = make_unique_export_name(prefix, "_audit.json")

    csv_path = export_dir / csv_name
    json_path = export_dir / json_name

    df = pd.DataFrame([asdict(r) for r in rows])
    df.to_csv(csv_path, index=False)
    df.to_json(json_path, orient="records", indent=2)

    write_tell(f"Exported audit CSV: {csv_path}")
    write_tell(f"Exported audit JSON: {json_path}")


def export_clean_pairlist(
    rows: List[AuditRow],
    export_path: Path,
    min_coverage_by_tf: Optional[Dict[str, float]] = None,
):
    if min_coverage_by_tf is None:
        min_coverage_by_tf = dict(DEFAULT_MIN_COVERAGE_BY_TF)

    grouped: Dict[str, Dict[str, AuditRow]] = {}
    for row in rows:
        grouped.setdefault(row.pair, {})[row.timeframe] = row

    good_pairs: List[str] = []

    for pair, tf_rows in grouped.items():
        keep_pair = True

        for tf, min_cov in min_coverage_by_tf.items():
            row = tf_rows.get(tf)

            if row is None:
                keep_pair = False
                break

            if not row.exists:
                keep_pair = False
                break

            if row.status == "EMPTY":
                keep_pair = False
                break
            if row.status.startswith("READ_ERROR"):
                keep_pair = False
                break
            if row.status.startswith("BAD_DATE_COL"):
                keep_pair = False
                break
            if row.status == "NO_VALID_DATES":
                keep_pair = False
                break

            if row.coverage_pct is None or row.coverage_pct < min_cov:
                keep_pair = False
                break

        if keep_pair:
            good_pairs.append(pair)

    good_pairs = sorted(set(good_pairs))
    export_path.write_text(json.dumps({"pairs": good_pairs}, indent=2), encoding="utf-8")
    write_tell(f"Clean pairlist written: {export_path}")
    write_tell(f"Pairs kept: {len(good_pairs)}")
    if good_pairs:
        write_tell(f"Coverage thresholds used: {min_coverage_by_tf}")
    else:
        write_warning_line(f"No pairs met thresholds: {min_coverage_by_tf}")


# =====================================================================================
# Config helpers
# =====================================================================================
def merge_dicts(base: dict, override: dict) -> dict:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge_dicts(result[key], value)
        else:
            result[key] = value
    return result


def resolve_config_chain(config_path: Path, seen: Optional[Set[Path]] = None) -> List[Path]:
    if seen is None:
        seen = set()

    config_path = config_path.resolve()
    if config_path in seen:
        return []

    seen.add(config_path)
    chain = [config_path]

    try:
        cfg = load_json_loose(config_path)
    except Exception:
        return chain

    add_files = cfg.get("add_config_files", []) or []
    for rel in add_files:
        child = (config_path.parent / rel).resolve()
        chain.extend(resolve_config_chain(child, seen))

    return chain


def load_resolved_config(config_path: Path) -> dict:
    chain = resolve_config_chain(config_path)
    merged: Dict[str, Any] = {}
    for p in reversed(chain):
        merged = merge_dicts(merged, load_json_loose(p))
    return merged


def extract_pairs_from_config(config: dict, config_path: Path) -> List[str]:
    pairs: List[str] = []

    exchange = config.get("exchange", {})
    pair_whitelist = exchange.get("pair_whitelist", []) or []
    pairs.extend(pair_whitelist)

    pairs_file = config.get("pairs_file") or exchange.get("pairs_file")
    if pairs_file:
        pf = (config_path.parent / pairs_file).resolve()
        if pf.exists():
            try:
                data = load_json_loose(pf)
                if isinstance(data, list):
                    pairs.extend(data)
                elif isinstance(data, dict) and isinstance(data.get("pairs"), list):
                    pairs.extend(data["pairs"])
            except Exception:
                pass

    out = []
    seen = set()
    for pair in pairs:
        if pair not in seen:
            seen.add(pair)
            out.append(pair)
    return out


def get_datadir(config: dict, exchange: str) -> Path:
    datadir = config.get("datadir")
    if datadir:
        return Path(datadir).resolve()
    return (Path(EXPECTED_PATH) / "user_data" / "data" / exchange).resolve()


# =====================================================================================
# Audit
# =====================================================================================
def parse_timestamp_col(df: pd.DataFrame) -> pd.Series:
    for col in ("date", "timestamp"):
        if col in df.columns:
            s = df[col]
            if pd.api.types.is_datetime64_any_dtype(s):
                return pd.to_datetime(s, utc=True)
            if pd.api.types.is_integer_dtype(s):
                return pd.to_datetime(s, unit="ms", utc=True)
            return pd.to_datetime(s, utc=True, errors="coerce")
    raise ValueError("No date/timestamp column found")


def locate_data_file(datadir: Path, pair: str, timeframe: str) -> Optional[Path]:
    safe_pair = sanitize_pair_for_filename(pair)
    candidates = [
        datadir / f"{safe_pair}-{timeframe}.feather",
        datadir / f"{safe_pair}-{timeframe}-spot.feather",
    ]
    for cpath in candidates:
        if cpath.exists():
            return cpath

    prefix = f"{safe_pair}-{timeframe}"
    for p in datadir.glob("*.feather"):
        if p.name.startswith(prefix):
            return p
    return None


def audit_pair_timeframe(datadir: Path, pair: str, timeframe: str, start: datetime, end: datetime) -> AuditRow:
    path = locate_data_file(datadir, pair, timeframe)
    expected = expected_candles_for_range(start, end, timeframe)

    if path is None or not path.exists():
        return AuditRow(pair, timeframe, False, "MISSING", "", "", None, None, 0, expected, 0.0 if expected else None, "")

    try:
        df = pd.read_feather(path)
    except Exception as e:
        return AuditRow(pair, timeframe, True, f"READ_ERROR: {e}", "", "", None, None, 0, expected, 0.0 if expected else None, str(path))

    if df.empty:
        return AuditRow(pair, timeframe, True, "EMPTY", "", "", None, None, 0, expected, 0.0 if expected else None, str(path))

    try:
        dates = parse_timestamp_col(df).dropna().sort_values()
    except Exception as e:
        return AuditRow(pair, timeframe, True, f"BAD_DATE_COL: {e}", "", "", None, None, len(df), expected, None, str(path))

    if dates.empty:
        return AuditRow(pair, timeframe, True, "NO_VALID_DATES", "", "", None, None, len(df), expected, None, str(path))

    first = dates.iloc[0].to_pydatetime()
    last = dates.iloc[-1].to_pydatetime()

    first_delta = (first - start).total_seconds() / 86400.0
    last_delta = (end - last).total_seconds() / 86400.0

    candles_in_range = int(((dates >= start) & (dates < end)).sum())
    coverage = round((candles_in_range / expected) * 100.0, 2) if expected > 0 else None

    flags = []
    tf_step = timeframe_to_timedelta(timeframe)
    if first > start + tf_step:
        flags.append("LATE_START")
    if last < end - tf_step:
        flags.append("EARLY_END")
    if coverage is not None and coverage < 95:
        flags.append("SHORT_COVERAGE")

    status = "OK" if not flags else "|".join(flags)

    return AuditRow(
        pair=pair,
        timeframe=timeframe,
        exists=True,
        status=status,
        first_candle=first.isoformat(),
        last_candle=last.isoformat(),
        first_delta_days=round(first_delta, 3),
        last_delta_days=round(last_delta, 3),
        candle_count=candles_in_range,
        expected_candles=expected,
        coverage_pct=coverage,
        file_path=str(path),
    )


def audit_local_data(datadir: Path, pairs: List[str], timeframes: List[str], timerange: str) -> List[AuditRow]:
    start, end = parse_timerange(timerange)
    rows: List[AuditRow] = []
    for pair in pairs:
        for tf in timeframes:
            rows.append(audit_pair_timeframe(datadir, pair, tf, start, end))
    return rows


def delete_bad_files(rows: List[AuditRow]):
    removed = 0
    seen_paths: Set[str] = set()

    for row in rows:
        if not row.file_path:
            continue

        status = row.status or ""
        truly_bad = (
            status == "EMPTY"
            or status.startswith("READ_ERROR")
            or status.startswith("BAD_DATE_COL")
            or status == "NO_VALID_DATES"
        )

        if not truly_bad:
            continue

        norm = normalize_path_for_compare(row.file_path)
        if norm in seen_paths:
            continue
        seen_paths.add(norm)

        try:
            p = Path(row.file_path)
            if p.exists():
                send2trash(str(p))
                removed += 1
        except Exception as e:
            write_warning_line(f"Could not move to recycle bin: {row.file_path}: {e}")

    write_tell(f"Moved {removed} local data files to Recycle Bin.")


# =====================================================================================
# Timerange export support
# =====================================================================================
def pairs_from_timerange_rows(
    rows: List[TimerangeRow],
    timeframes: List[str],
    require_all_selected_timeframes: bool = False,
) -> List[str]:
    wanted_timeframes = set(timeframes)
    pair_tf_map: Dict[str, set] = {}

    for row in rows:
        tf = str(row.timeframe).strip()
        pair = str(row.pair).strip()

        if not pair or tf not in wanted_timeframes:
            continue

        if pair not in pair_tf_map:
            pair_tf_map[pair] = set()

        pair_tf_map[pair].add(tf)

    matched_pairs: List[str] = []

    if require_all_selected_timeframes:
        for pair, tfset in pair_tf_map.items():
            if all(tf in tfset for tf in timeframes):
                matched_pairs.append(pair)
    else:
        primary_tf = timeframes[0]
        for pair, tfset in pair_tf_map.items():
            if primary_tf in tfset:
                matched_pairs.append(pair)

    return sorted(matched_pairs)


def choose_pairs_for_audit(timerange: str, timeframes: List[str]) -> Tuple[List[str], str, Path]:
    export_dir = ensure_export_dir()

    write_action_line("Choose pairs source for audit:")
    write_info_line("1. Use existing exported timerange CSV")
    write_info_line("2. Generate new export from current data")

    choice = input("Enter choice (1-2): ").strip()

    if choice == "1":
        csv_file = choose_file_from_folder(
            export_dir,
            patterns=[
                "*list_data_timeranges*.csv",
                "*timerange*.csv",
                "*timeranges*.csv",
            ],
            title="Select existing exported timerange CSV:",
        )

        if csv_file is not None:
            rows = load_timerange_csv(csv_file)
            pairs = pairs_from_timerange_rows(
                rows,
                timeframes,
                require_all_selected_timeframes=False,
            )

            write_tell(f"Loaded export file: {csv_file}")
            write_tell(f"Export file rows loaded: {len(rows)}")

            if pairs:
                write_tell(
                    f"Export found {len(pairs)} candidate pairs using primary timeframe "
                    f"{timeframes[0]}. Audit will now check real coverage."
                )
                return pairs, "existing_timerange_export", csv_file

            write_warning_line("Export file loaded successfully.")
            write_warning_line(
                f"But it contains no pairs for primary timeframe {timeframes[0]}."
            )

        write_warning_line(f"No usable existing timerange export found in: {export_dir}")
        if not read_yes_no("Generate a new export from current data now?", True):
            raise RuntimeError("Cancelled.")

        choice = "2"

    if choice == "2":
        cmd = build_list_timerange_command()
        log_file = export_dir / make_unique_export_name("generated_timerange_live", ".log")

        rc, output = run_command_stream_capture(cmd, log_file)
        if rc != 0:
            raise RuntimeError("Generating fresh timerange export failed.")

        rows = parse_list_data_timerange_output(output)
        if not rows:
            raise RuntimeError("Fresh timerange export ran, but no timerange rows were parsed.")

        export_name = make_unique_export_name(
            f"{DEFAULT_EXCHANGE}_{timerange}_{'_'.join(timeframes)}_list_data_timeranges",
            ".csv",
        )
        export_path = export_timerange_rows(rows, export_dir, export_name)

        write_tell(f"Fresh timerange export created successfully: {export_path}")
        write_tell(f"Exported timerange rows: {len(rows)}")

        pairs = pairs_from_timerange_rows(
            rows,
            timeframes,
            require_all_selected_timeframes=False,
        )

        if not pairs:
            write_warning_line("Fresh timerange export was created successfully.")
            write_warning_line(
                f"But it contains no pairs for primary timeframe {timeframes[0]}."
            )
            raise RuntimeError("Audit stopped because the generated export had no usable pair rows.")

        write_tell(
            f"Fresh export found {len(pairs)} candidate pairs using primary timeframe "
            f"{timeframes[0]}. Audit will now check real coverage."
        )

        return pairs, "generated_timerange_export", export_path

    raise RuntimeError("Invalid choice.")


def load_config_pairs_and_datadir() -> Tuple[List[str], Path]:
    config_path = Path(EXPECTED_PATH) / DEFAULT_CONFIG
    config = load_resolved_config(config_path)
    pairs = extract_pairs_from_config(config, config_path)
    datadir = get_datadir(config, DEFAULT_EXCHANGE)
    return pairs, datadir


# =====================================================================================
# Actions
# =====================================================================================
def get_download_settings():
    timerange = select_timerange()
    timeframes = select_timeframes(DEFAULT_DOWNLOAD_TIMEFRAMES)
    include_inactive = read_yes_no("Include inactive pairs?", DEFAULT_INCLUDE_INACTIVE_PAIRS)
    erase = read_yes_no("Use --erase before download?", DEFAULT_USE_ERASE)

    return {
        "timerange": timerange,
        "timeframes": timeframes,
        "include_inactive": include_inactive,
        "erase": erase,
    }


def action_download():
    s = get_download_settings()
    export_dir = ensure_export_dir()

    cmd = build_download_command(
        timerange=s["timerange"],
        timeframes=s["timeframes"],
        include_inactive_pairs=s["include_inactive"],
        erase=s["erase"],
    )

    rc = run_command_live_tty(cmd)
    if rc == 0:
        write_tell("Download completed.")
    else:
        write_error_line(f"Download exited with code {rc}.")


def action_list_data():
    export_dir = ensure_export_dir()
    cmd = build_list_data_command()
    rc, output = run_command_stream_capture(
        cmd,
        export_dir / make_unique_export_name("list_data_live", ".log"),
    )

    if rc != 0:
        write_error_line(f"list-data exited with code {rc}.")
        return

    rows = parse_list_data_output(output)
    if not rows:
        write_warning_line("No rows parsed from list-data output.")
        return

    outpath = export_list_data_rows(
        rows,
        export_dir,
        make_unique_export_name("list_data_pairs", ".csv"),
    )
    write_tell(f"Exported list-data pairs: {outpath}")
    write_tell(f"Parsed rows: {len(rows)}")


def action_list_timeranges():
    export_dir = ensure_export_dir()
    cmd = build_list_timerange_command()
    rc, output = run_command_stream_capture(
        cmd,
        export_dir / make_unique_export_name("list_timerange_live", ".log"),
    )

    if rc != 0:
        write_error_line(f"list-data --show-timerange exited with code {rc}.")
        return

    rows = parse_list_data_timerange_output(output)
    if not rows:
        write_warning_line("No timerange rows parsed from output.")
        return

    outpath = export_timerange_rows(
        rows,
        export_dir,
        make_unique_export_name("list_data_timeranges", ".csv"),
    )
    write_tell(f"Exported timerange data: {outpath}")
    write_tell(f"Parsed rows: {len(rows)}")


def action_audit():
    timerange = select_timerange()
    timeframes = select_timeframes(DEFAULT_DOWNLOAD_TIMEFRAMES)
    export_dir = ensure_export_dir()

    try:
        pairs, source_kind, source_path = choose_pairs_for_audit(timerange, timeframes)
    except Exception as e:
        write_error_line(str(e))
        return

    try:
        config_path = Path(EXPECTED_PATH) / DEFAULT_CONFIG
        config = load_resolved_config(config_path)
        datadir = get_datadir(config, DEFAULT_EXCHANGE)
    except Exception as e:
        write_error_line(f"Failed loading config/datadir: {e}")
        return

    write_info_line(f"Pairs source: {source_kind}")
    write_info_line(f"Source file: {source_path}")
    write_info_line(f"Candidate pairs for audit: {len(pairs)}")
    write_info_line(f"Selected timeframes: {' '.join(timeframes)}")
    write_info_line(f"Requested timerange: {timerange}")
    write_info_line(f"Data directory: {datadir}")

    if not datadir.exists():
        write_error_line(f"Data directory does not exist: {datadir}")
        return

    rows = audit_local_data(datadir, pairs, timeframes, timerange)
    prefix = f"{DEFAULT_EXCHANGE}_{timerange}_{'_'.join(timeframes)}"
    export_audit(rows, export_dir, prefix)

    df = pd.DataFrame([asdict(r) for r in rows])
    write_info_line("")
    write_info_line("Audit summary:")
    write_info_line(df["status"].value_counts(dropna=False).to_string())


def action_audit_and_clean():
    timerange = select_timerange()
    timeframes = select_timeframes(DEFAULT_DOWNLOAD_TIMEFRAMES)
    export_dir = ensure_export_dir()

    try:
        pairs, source_kind, source_path = choose_pairs_for_audit(timerange, timeframes)
    except Exception as e:
        write_error_line(str(e))
        return

    try:
        config_path = Path(EXPECTED_PATH) / DEFAULT_CONFIG
        config = load_resolved_config(config_path)
        datadir = get_datadir(config, DEFAULT_EXCHANGE)
    except Exception as e:
        write_error_line(f"Failed loading config/datadir: {e}")
        return

    write_info_line(f"Pairs source: {source_kind}")
    write_info_line(f"Source file: {source_path}")
    write_info_line(f"Candidate pairs for audit: {len(pairs)}")
    write_info_line(f"Selected timeframes: {' '.join(timeframes)}")
    write_info_line(f"Requested timerange: {timerange}")
    write_info_line(f"Data directory: {datadir}")

    if not datadir.exists():
        write_error_line(f"Data directory does not exist: {datadir}")
        return

    rows = audit_local_data(datadir, pairs, timeframes, timerange)
    prefix = f"{DEFAULT_EXCHANGE}_{timerange}_{'_'.join(timeframes)}"
    export_audit(rows, export_dir, prefix)

    if read_yes_no("Move truly broken local files to Recycle Bin?", False):
        delete_bad_files(rows)

    if read_yes_no("Export clean pairlist JSON using coverage thresholds?", True):
        clean_name = make_unique_export_name(f"{prefix}_pairs_clean", ".json")
        export_clean_pairlist(
            rows,
            export_dir / clean_name,
            min_coverage_by_tf={
                "5m": 80.0,
                "1h": 80.0,
                "1d": 40.0,
            },
        )


def action_full_flow():
    s = get_download_settings()
    export_dir = ensure_export_dir()

    download_cmd = build_download_command(
        timerange=s["timerange"],
        timeframes=s["timeframes"],
        include_inactive_pairs=s["include_inactive"],
        erase=s["erase"],
    )

    rc = run_command_live_tty(download_cmd)
    if rc != 0:
        write_error_line("Download failed. Stopping full flow.")
        return

    timerange_rows: List[TimerangeRow] = []
    timerange_cmd = build_list_timerange_command()
    timerange_rc, timerange_output = run_command_stream_capture(
        timerange_cmd,
        export_dir / make_unique_export_name("fullflow_timerange_live", ".log"),
    )

    selected_export_path: Optional[Path] = None
    if timerange_rc == 0:
        timerange_rows = parse_list_data_timerange_output(timerange_output)
        if timerange_rows:
            selected_export_path = export_timerange_rows(
                timerange_rows,
                export_dir,
                make_unique_export_name(
                    f"{DEFAULT_EXCHANGE}_{s['timerange']}_{'_'.join(s['timeframes'])}_list_data_timeranges",
                    ".csv",
                ),
            )
            write_tell(f"Fresh timerange export created successfully: {selected_export_path}")
            write_tell(f"Exported timerange rows: {len(timerange_rows)}")
        else:
            write_warning_line("Timerange listing ran, but no rows were parsed.")
    else:
        write_warning_line("Timerange listing failed. Continuing with config pairlist.")

    try:
        config = load_resolved_config(Path(EXPECTED_PATH) / DEFAULT_CONFIG)
        datadir = get_datadir(config, DEFAULT_EXCHANGE)

        if timerange_rows:
            pairs = pairs_from_timerange_rows(
                timerange_rows,
                s["timeframes"],
                require_all_selected_timeframes=False,
            )
            if pairs:
                source_kind = "timerange_export"
                source_path = selected_export_path if selected_export_path is not None else Path(EXPECTED_PATH) / DEFAULT_EXPORT_DIR
            else:
                write_warning_line("Timerange export succeeded, but found no candidate pairs for the primary timeframe.")
                write_warning_line("Falling back to config pairlist.")
                pairs, _ = load_config_pairs_and_datadir()
                source_kind = "config_pairlist"
                source_path = Path(EXPECTED_PATH) / DEFAULT_CONFIG
        else:
            pairs, _ = load_config_pairs_and_datadir()
            source_kind = "config_pairlist"
            source_path = Path(EXPECTED_PATH) / DEFAULT_CONFIG

    except Exception as e:
        write_error_line(str(e))
        return

    write_info_line(f"Pairs source: {source_kind}")
    write_info_line(f"Source file: {source_path}")
    write_info_line(f"Resolved pairs: {len(pairs)}")
    write_info_line(f"Data directory: {datadir}")

    if not datadir.exists():
        write_error_line(f"Data directory does not exist: {datadir}")
        return

    rows = audit_local_data(datadir, pairs, s["timeframes"], s["timerange"])
    prefix = f"{DEFAULT_EXCHANGE}_{s['timerange']}_{'_'.join(s['timeframes'])}"
    export_audit(rows, export_dir, prefix)

    if read_yes_no("Move truly broken local files to Recycle Bin after audit?", False):
        delete_bad_files(rows)

    if read_yes_no("Write clean pairlist JSON using coverage thresholds?", True):
        clean_name = make_unique_export_name(f"{prefix}_pairs_clean", ".json")
        export_clean_pairlist(
            rows,
            export_dir / clean_name,
            min_coverage_by_tf={
                "5m": 80.0,
                "1h": 80.0,
                "1d": 40.0,
            },
        )


# =====================================================================================
# Main
# =====================================================================================
def main():
    enable_windows_ansi()
    ensure_working_directory()
    ensure_export_dir()

    while True:
        write_info_line("")
        write_info_line("========== Freqtrade Data Utility ==========")
        write_info_line("1. Download data")
        write_info_line("2. List pair / timeframe combos")
        write_info_line("3. List pair / timeframe timeranges and export CSV")
        write_info_line("4. Audit local data coverage and export report")
        write_info_line("5. Audit + export + optional recycle broken files")
        write_info_line("6. Full flow: download -> timeranges -> audit -> export -> optional clean")
        write_info_line("7. Exit")
        write_action_line("Choose option:")

        choice = input().strip()

        if choice == "1":
            action_download()
        elif choice == "2":
            action_list_data()
        elif choice == "3":
            action_list_timeranges()
        elif choice == "4":
            action_audit()
        elif choice == "5":
            action_audit_and_clean()
        elif choice == "6":
            action_full_flow()
        elif choice == "7":
            write_info_line("Exiting...")
            break
        else:
            write_error_line("Invalid choice.")


if __name__ == "__main__":
    main()