#!/usr/bin/env python
"""
Freqtrade All-In-One UI Tool

Version: v31 colored jobs + right-click job actions

Tabs:
- Backtest
- Hyperopt
- Analysis
- Data

Design:
- UI never blocks while a job is running.
- Every Run click opens a separate CMD terminal.
- Current field values stay on screen and are saved to disk.
- Each run gets a unique Docker container name, so you can run the same config again.
- Child terminal streams colored output and saves raw/extracted output where possible.

Place this file inside N:\\Freqtrade or run it from anywhere.
Default PROJECT_ROOT is N:\\Freqtrade.
"""
from __future__ import annotations

import base64
import csv
import ctypes
import glob
import json
import os
import random
import re
import shlex
import subprocess
import sys
import time
import tkinter as tk
import zlib
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

# =====================================================================================
# Project defaults
# =====================================================================================
DEFAULT_PROJECT_ROOT = r"N:\Freqtrade"

# Keep the project-root setting inside the normal AIO state file instead of creating
# Freqtrade_AIO_UI_launcher.json next to the script/exe.
EARLY_TOOL_FOLDER_REL = "user_data/tools/Main_Py/Freqtrade_AIO_UI"
STATE_FILE_NAME = "Freqtrade_AIO_UI_state.json"
LEGACY_LAUNCHER_CONFIG_NAME = "Freqtrade_AIO_UI_launcher.json"


def app_base_dir() -> str:
    """Folder where the .py/.pyw or frozen .exe lives."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    try:
        return os.path.dirname(os.path.abspath(__file__))
    except Exception:
        return os.getcwd()


def cleanup_legacy_launcher_config() -> None:
    """Remove the old next-to-exe launcher json if this tool created it.

    The selected project root is now stored in:
        <project_root>/user_data/tools/Main_Py/Freqtrade_AIO_UI/Freqtrade_AIO_UI_state.json
    """
    try:
        path = os.path.join(app_base_dir(), LEGACY_LAUNCHER_CONFIG_NAME)
        if not os.path.isfile(path):
            return

        text = Path(path).read_text(encoding="utf-8", errors="replace").strip()
        data = json.loads(text) if text else {}
        if isinstance(data, dict) and set(data.keys()).issubset({"project_root"}):
            os.remove(path)
    except Exception:
        pass


def looks_like_freqtrade_root(path_value: str) -> bool:
    """A usable Freqtrade root normally has user_data and docker-compose.yml/compose file.

    Keep this tolerant because some setups use docker compose.yaml, custom compose
    names, or a fresh repo where only user_data exists yet.
    """
    if not path_value:
        return False
    path = os.path.abspath(os.path.expanduser(path_value))
    user_data = os.path.isdir(os.path.join(path, "user_data"))
    compose = any(
        os.path.isfile(os.path.join(path, name))
        for name in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml")
    )
    freqtrade_project = os.path.isdir(os.path.join(path, ".git")) or os.path.isfile(os.path.join(path, "pyproject.toml"))
    return user_data or compose or freqtrade_project


def parent_candidates(start_path: str) -> List[str]:
    """Return start_path and every parent folder up to the drive/root."""
    out: List[str] = []
    current = os.path.abspath(os.path.expanduser(start_path or os.getcwd()))
    if os.path.isfile(current):
        current = os.path.dirname(current)

    while current and current not in out:
        out.append(current)
        parent = os.path.dirname(current)
        if not parent or parent == current:
            break
        current = parent
    return out


def state_path_for_root(root_path: str) -> str:
    return os.path.join(os.path.abspath(os.path.expanduser(root_path)), EARLY_TOOL_FOLDER_REL, STATE_FILE_NAME)


def read_project_root_from_state_at(candidate_root: str) -> str:
    try:
        state_path = state_path_for_root(candidate_root)
        if not os.path.isfile(state_path):
            return ""
        data = json.loads(Path(state_path).read_text(encoding="utf-8", errors="replace"))
        if not isinstance(data, dict):
            return ""
        value = str(data.get("project_root", "")).strip()
        if value:
            return os.path.abspath(os.path.expanduser(value))
    except Exception:
        pass
    return ""


def write_project_root_to_state(path_value: str) -> None:
    """Persist project root inside the normal AIO state file under the Freqtrade root."""
    try:
        root_path = os.path.abspath(os.path.expanduser(path_value))
        state_path = state_path_for_root(root_path)
        os.makedirs(os.path.dirname(state_path), exist_ok=True)

        data: Dict[str, Any] = {}
        if os.path.isfile(state_path):
            try:
                loaded = json.loads(Path(state_path).read_text(encoding="utf-8", errors="replace"))
                if isinstance(loaded, dict):
                    data = loaded
            except Exception:
                data = {}

        data["project_root"] = root_path
        Path(state_path).write_text(json.dumps(data, indent=2), encoding="utf-8", newline="\n")
    except Exception:
        pass


def cli_project_root() -> str:
    # Optional advanced override for shortcuts/scripts:
    #   Freqtrade_AIO_UI.exe --project-root D:\Freqtrade
    # or environment variable:
    #   set FREQTRADE_PROJECT_ROOT=D:\Freqtrade
    for idx, arg in enumerate(sys.argv[:-1]):
        if arg == "--project-root":
            return os.path.abspath(os.path.expanduser(sys.argv[idx + 1]))
    env_root = os.environ.get("FREQTRADE_PROJECT_ROOT", "").strip()
    if env_root:
        return os.path.abspath(os.path.expanduser(env_root))
    return ""


def detect_project_root() -> str:
    cleanup_legacy_launcher_config()

    base_dir = app_base_dir()
    direct_candidates: List[str] = []

    for candidate in [
        DEFAULT_PROJECT_ROOT,
        base_dir,
        os.getcwd(),
    ]:
        direct_candidates.extend(parent_candidates(candidate))

    # Deduplicate while preserving order.
    seen = set()
    direct_candidates = [
        os.path.abspath(x)
        for x in direct_candidates
        if not (os.path.abspath(x).lower() in seen or seen.add(os.path.abspath(x).lower()))
    ]

    cli_root = cli_project_root()
    if cli_root and looks_like_freqtrade_root(cli_root):
        return cli_root

    # First read project_root from the normal AIO state file if present.
    for candidate in direct_candidates:
        remembered = read_project_root_from_state_at(candidate)
        if remembered and looks_like_freqtrade_root(remembered):
            return remembered

    # Then auto-detect from the script/exe folder, parents, default root, or CWD.
    for candidate in direct_candidates:
        if looks_like_freqtrade_root(candidate):
            return candidate

    # Return a sensible candidate even if it does not exist yet; the GUI will ask.
    return os.path.abspath(os.path.expanduser(cli_root or DEFAULT_PROJECT_ROOT or base_dir or os.getcwd()))


PROJECT_ROOT = detect_project_root()


def set_project_root(path_value: str, persist: bool = True) -> None:
    global PROJECT_ROOT
    PROJECT_ROOT = os.path.abspath(os.path.expanduser(path_value))
    if persist:
        write_project_root_to_state(PROJECT_ROOT)


CONFIG_FOLDER = "user_data"
STRATEGY_FOLDER_REL = "user_data/strategies"
HYPEROPTS_FOLDER_REL = "user_data/hyperopts"

DOCKER_COMPOSE = "docker-compose"
DOCKER_SERVICE = "freqtrade"
DATA_FORMAT_OHLCV = "feather"

TOOL_FOLDER_REL = EARLY_TOOL_FOLDER_REL
STATE_FILE_REL = f"{TOOL_FOLDER_REL}/Freqtrade_AIO_UI_state.json"
OLD_STATE_FILE_REL = "user_data/all_in_one_ui_state.json"
UI_JOBS_FOLDER_REL = f"{TOOL_FOLDER_REL}/jobs"
JOB_REGISTRY_FILE_REL = f"{UI_JOBS_FOLDER_REL}/Freqtrade_AIO_UI_jobs.json"

# Output defaults now follow your original helper scripts instead of dumping reports
# inside the UI tool folder. These can still be changed in the Paths tab.
BACKTEST_REPORTS_FOLDER_REL = "user_data/backtest_reports"
BACKTEST_RAW_OUTPUT_FOLDER_REL = "user_data/logs/backtest_raw_output"
HYPEROPT_RAW_OUTPUT_FOLDER_REL = "user_data/logs/hyperopt_raw_output"
HYPEROPT_EXTRACT_FOLDER_REL = "user_data/hyperopt_extracts"
ANALYSIS_RAW_OUTPUT_FOLDER_REL = "user_data/logs/analysis_raw_output"
ANALYSIS_EXTRACT_FOLDER_REL = "user_data/analysis_extracts"
DATA_RAW_OUTPUT_FOLDER_REL = "user_data/logs/data_raw_output"
DATA_AUDIT_FOLDER_REL = "user_data/data/data_audit"

# Legacy aliases used by generic folder buttons.
RAW_OUTPUT_FOLDER_REL = "user_data/logs"
EXTRACT_FOLDER_REL = "user_data/analysis_extracts"

DEFAULT_OUTPUT_PATHS = {
    "backtest_reports": BACKTEST_REPORTS_FOLDER_REL,
    "backtest_raw": BACKTEST_RAW_OUTPUT_FOLDER_REL,
    "hyperopt_raw": HYPEROPT_RAW_OUTPUT_FOLDER_REL,
    "hyperopt_extracts": HYPEROPT_EXTRACT_FOLDER_REL,
    "analysis_raw": ANALYSIS_RAW_OUTPUT_FOLDER_REL,
    "analysis_extracts": ANALYSIS_EXTRACT_FOLDER_REL,
    "data_raw": DATA_RAW_OUTPUT_FOLDER_REL,
    "data_audit": DATA_AUDIT_FOLDER_REL,
}

DEFAULT_DATA_CONFIG = "user_data/data_download.json"
DEFAULT_EXCHANGE = "kucoin"
DEFAULT_DATA_FORMAT = "feather"

TIME_WINDOWS = {
    "TRAIN": "20240101-20240701",
    "VALID": "20240701-20241001",
    "TEST": "20241001-20251201",
    "LIVE_CHECK": "20251001-20260410",
    "FULL": "20240101-20251201",
    "CUSTOM": "",
}

HYPEROPT_LOSSES = [
    "ShortTradeDurHyperOptLoss",
    "OnlyProfitHyperOptLoss",
    "SharpeHyperOptLoss",
    "SharpeHyperOptLossDaily",
    "SortinoHyperOptLoss",
    "SortinoHyperOptLossDaily",
    "MaxDrawDownHyperOptLoss",
    "MaxDrawDownRelativeHyperOptLoss",
    "MaxDrawDownPerPairHyperOptLoss",
    "CalmarHyperOptLoss",
    "ProfitDrawDownHyperOptLoss",
    "MultiMetricHyperOptLoss",
]

VALID_SPACES = [
    "buy",
    "sell",
    "roi",
    "stoploss",
    "trailing",
    "trades",
    "protection",
    "all",
    "default",
]

PRESET_RANDOM_SEEDS = ["7", "42", "101", "202", "909"]
RANDOM_STATE_MODE_VALUES = ["AUTO", "CUSTOM", *PRESET_RANDOM_SEEDS]

SPACE_DETAILS = """buy/sell = entry and exit parameters
roi = minimal_roi table
stoploss = strategy stoploss
trailing = trailing stop parameters
trades = max_open_trades
protection = protection parameters
all = every optimizable space
default = Freqtrade default spaces"""

HYPEROPT_LOSS_DETAILS = {
    "ShortTradeDurHyperOptLoss": "Short trade duration and avoiding losses.",
    "OnlyProfitHyperOptLoss": "Only total profit. Fast but can ignore risk quality.",
    "SharpeHyperOptLoss": "Sharpe ratio on trade returns.",
    "SharpeHyperOptLossDaily": "Sharpe ratio on daily returns. Stable scalping default.",
    "SortinoHyperOptLoss": "Sortino ratio on trade returns / downside deviation.",
    "SortinoHyperOptLossDaily": "Sortino ratio on daily returns / downside deviation.",
    "MaxDrawDownHyperOptLoss": "Minimizes maximum absolute drawdown.",
    "MaxDrawDownRelativeHyperOptLoss": "Uses absolute drawdown plus relative drawdown.",
    "MaxDrawDownPerPairHyperOptLoss": "Penalizes worst pair profit/drawdown behavior.",
    "CalmarHyperOptLoss": "Calmar ratio: profit versus maximum drawdown.",
    "ProfitDrawDownHyperOptLoss": "Balances maximum profit and minimum drawdown.",
    "MultiMetricHyperOptLoss": "Profit, drawdown, profit factor, expectancy, winrate, and trade count.",
}

RANDOM_STATE_DETAILS = """AUTO = omit --random-state and let Freqtrade/Optuna choose
CUSTOM = unlock seed field and use your typed fixed number
7 / 42 / 101 / 202 / 909 = preset fixed seeds for repeatable comparison runs"""

TIMEFRAMES = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d"]

RECOMMENDED_RECURSIVE_PAIRS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT"]
ANALYSIS_PAIR_SOURCE_VALUES = [
    "CONFIG_PAIRLIST_DOWNLOADED",
    "RECOMMENDED",
    "MANUAL",
]
ANALYSIS_RUN_MODE_VALUES = [
    "single_command",
    "cmd_per_pair_parallel",
    "cmd_per_pair_sequential",
]
ANALYSIS_DISPLAY_MODE_VALUES = [
    "silent",
    "minimized_cmd",
    "visible_cmd",
]

# =====================================================================================
# Dark UI theme
# =====================================================================================
DARK_BG = "#0f1117"
DARK_PANEL = "#161b22"
DARK_PANEL_2 = "#1f2630"
DARK_FIELD = "#0b0f14"
DARK_BORDER = "#303844"
DARK_TEXT = "#e6edf3"
DARK_MUTED = "#9aa7b3"
DARK_ACCENT = "#2f81f7"
DARK_ACCENT_ACTIVE = "#58a6ff"
DARK_DANGER = "#ff6b6b"
DARK_SUCCESS = "#3fb950"

# =====================================================================================
# Colors / console helpers for runner mode
# =====================================================================================
RESET = "\033[0m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"
WHITE = "\033[37m"
BRIGHT_WHITE = "\033[97m"

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
LOG_LINE_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})\s+-\s+([^-].*?)\s+-\s+(INFO|WARNING|ERROR|CRITICAL|DEBUG)\s+-\s+(.*)$"
)
LIST_DATA_ROW_RE = re.compile(r"^\s*│\s*(?P<pair>.*?)\s*│\s*(?P<timeframes>.*?)\s*│\s*(?P<type>.*?)\s*│\s*$")
TIMERANGE_ROW_RE = re.compile(
    r"^\s*│\s*(?P<pair>.*?)\s*│\s*(?P<timeframe>.*?)\s*│\s*(?P<type>.*?)\s*│\s*"
    r"(?P<start>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s*│\s*"
    r"(?P<end>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s*│\s*"
    r"(?P<count>\d+)\s*│\s*$"
)

# =====================================================================================
# Generic helpers
# =====================================================================================
def project_path(*parts: str) -> str:
    return os.path.join(PROJECT_ROOT, *parts)


def rel_to_project(path: str) -> str:
    try:
        return os.path.relpath(path, PROJECT_ROOT).replace(os.sep, "/")
    except Exception:
        return path.replace(os.sep, "/")


def stamp_now() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def short_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def strip_ansi(value: str) -> str:
    value = ANSI_RE.sub("", value or "")
    return value.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")


def safe_filename(value: str) -> str:
    value = str(value or "").strip()
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", value)
    value = re.sub(r"_+", "_", value)
    value = value.strip("._-")
    return value or "unknown"


def safe_container_part(value: str) -> str:
    value = safe_filename(value)
    if not re.match(r"^[A-Za-z0-9]", value):
        value = "x_" + value
    return value[:80]


def config_name_to_label(config_rel_or_name: str) -> str:
    base = os.path.basename(config_rel_or_name)
    stem = os.path.splitext(base)[0]
    lower = stem.lower()
    if lower.startswith("config-"):
        stem = stem[len("config-"):]
    elif lower.startswith("config_"):
        stem = stem[len("config_"):]
    elif lower == "config":
        stem = "default"
    return safe_container_part(stem)


def unique_container_name(prefix: str, label: str) -> str:
    suffix = f"{short_stamp()}_{random.randint(1000, 9999)}"
    return safe_container_part(f"{prefix}_{label}_{suffix}")


def command_to_string(cmd: List[str]) -> str:
    try:
        return shlex.join(cmd)
    except Exception:
        return " ".join(cmd)


def quote_cmd_arg(value: Any) -> str:
    """Quote one argument safely for a Windows .cmd line.

    subprocess.list2cmdline is Windows-aware and also behaves safely enough for
    the generated CMD launcher files used by this tool.
    """
    try:
        return subprocess.list2cmdline([str(value)])
    except Exception:
        value = str(value).replace('"', r'\"')
        return f'"{value}"'


def resolve_project_or_abs(path_value: str) -> str:
    value = str(path_value or "").strip().replace("/", os.sep)
    if not value:
        value = TOOL_FOLDER_REL
    if os.path.isabs(value):
        return os.path.normpath(value)
    return project_path(value)


def output_folder_from_metadata(metadata: Dict[str, Any], key: str) -> str:
    output_paths = metadata.get("output_paths", {}) if isinstance(metadata, dict) else {}
    if not isinstance(output_paths, dict):
        output_paths = {}
    selected = output_paths.get(key) or DEFAULT_OUTPUT_PATHS.get(key) or TOOL_FOLDER_REL
    folder = resolve_project_or_abs(str(selected))
    os.makedirs(folder, exist_ok=True)
    return folder


def ensure_dirs() -> None:
    required = [TOOL_FOLDER_REL, UI_JOBS_FOLDER_REL]
    required.extend(DEFAULT_OUTPUT_PATHS.values())
    required.extend([RAW_OUTPUT_FOLDER_REL, EXTRACT_FOLDER_REL])
    for rel in required:
        os.makedirs(resolve_project_or_abs(rel), exist_ok=True)


def remove_docker_container(container_name: str) -> None:
    """Remove a Docker container if it exists. Safe to call before/after jobs."""
    container_name = str(container_name or "").strip()
    if not container_name:
        return
    try:
        subprocess.run(
            ["docker", "rm", "-f", container_name],
            cwd=PROJECT_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except Exception:
        pass


def read_docker_container_logs(container_name: str) -> str:
    """Read logs from a stopped/running Docker container."""
    container_name = str(container_name or "").strip()
    if not container_name:
        return ""
    try:
        result = subprocess.run(
            ["docker", "logs", container_name],
            cwd=PROJECT_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        return result.stdout or ""
    except Exception as e:
        return f"Failed to read docker logs for {container_name}: {e}\n"


def command_without_rm(cmd: List[str]) -> List[str]:
    """Return command without --rm so logs remain available after the job finishes."""
    return [part for part in cmd if part != "--rm"]


def ensure_windows_ansi() -> None:
    if os.name != "nt":
        return
    try:
        os.system("")
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


def write_color(text: str, color: str = WHITE) -> None:
    print(f"{color}{text}{RESET}")


def colorize_log_line(raw_line: str) -> str:
    clean = strip_ansi(raw_line).rstrip("\n")
    if not clean:
        return ""

    stripped = clean.strip()
    if stripped.startswith(("┏", "┓", "┗", "┛", "┡", "┩", "└", "┘", "┃", "│", "╇", "━", "─")):
        return clean

    match = LOG_LINE_RE.match(clean)
    if match:
        timestamp, logger_name, level, message = match.groups()
        level_color = BLUE if level == "INFO" else YELLOW if level == "WARNING" else RED if level in ("ERROR", "CRITICAL") else CYAN
        return f"{YELLOW}{timestamp}{RESET} - {MAGENTA}{logger_name}{RESET} - {level_color}{level}{RESET} - {WHITE}{message}{RESET}"

    upper = clean.upper()
    if clean.startswith("time="):
        return f"{CYAN}{clean}{RESET}"
    if clean.lstrip().startswith("Container "):
        return f"{GREEN}{clean}{RESET}"
    if any(x in upper for x in ["ERROR", "CRITICAL", "FAILED", "NO DATA FOUND", "CONFIGURATION ERROR"]):
        return f"{RED}{clean}{RESET}"
    if any(x in upper for x in ["WARNING", "NO HISTORY FOR", "DATA STARTS AT"]):
        return f"{YELLOW}{clean}{RESET}"
    if any(x in upper for x in ["BACKTESTING REPORT", "HYPEROPT RESULTS", "BEST RESULT", "LOOKAHEAD ANALYSIS", "RECURSIVE ANALYSIS", "STRATEGY SUMMARY"]):
        return f"{BRIGHT_WHITE}{clean}{RESET}"
    return f"{WHITE}{clean}{RESET}"


def is_suppressed_data_warning(line: str) -> bool:
    line = strip_ansi(line).strip().lower()
    if "warning" not in line:
        return False
    looks_like_history_warning = "data.history" in line or "datahandlers.idatahandler" in line or "idatahandler" in line
    return looks_like_history_warning and (("data starts at" in line) or ("no history for" in line))

# =====================================================================================
# Discovery helpers used by GUI
# =====================================================================================
def natural_sort_key(path: str) -> List[Any]:
    base = os.path.basename(path)
    return [int(x) if x.isdigit() else x.lower() for x in re.split(r"(\d+)", base)]


def list_config_files() -> List[str]:
    folder = project_path(CONFIG_FOLDER)
    found: List[str] = []
    main_cfg = os.path.join(folder, "config.json")
    if os.path.isfile(main_cfg):
        found.append(rel_to_project(main_cfg))
    found.extend(rel_to_project(x) for x in sorted(glob.glob(os.path.join(folder, "config-*.json")), key=natural_sort_key))
    # Keep order while deduping.
    out: List[str] = []
    seen = set()
    for item in found:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def list_data_config_files() -> List[str]:
    """Return config choices useful for the Data tab.

    download-data can use a dedicated data_download.json, but sometimes normal
    Freqtrade configs are useful too. Keep data-looking files first, then add
    regular bot configs as fallbacks.
    """
    folder = project_path(CONFIG_FOLDER)
    patterns = [
        "data_download.json",
        "data*.json",
        "*data*.json",
        "config-data*.json",
        "config-download*.json",
        "config-*.json",
        "config.json",
    ]

    found: List[str] = []
    for pattern in patterns:
        found.extend(
            rel_to_project(path)
            for path in sorted(glob.glob(os.path.join(folder, pattern)), key=natural_sort_key)
            if os.path.isfile(path)
        )

    if DEFAULT_DATA_CONFIG not in found:
        found.insert(0, DEFAULT_DATA_CONFIG)

    out: List[str] = []
    seen = set()
    for item in found:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def extract_strategy_classes_from_file(path: str) -> List[str]:
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    return re.findall(r"class\s+([A-Za-z_][A-Za-z0-9_]*)\s*\([^)]*IStrategy[^)]*\)\s*:", text)


def list_strategy_classes() -> List[str]:
    folder = project_path(STRATEGY_FOLDER_REL)
    found: List[str] = []
    for path in sorted(glob.glob(os.path.join(folder, "*.py")), key=natural_sort_key):
        found.extend(extract_strategy_classes_from_file(path))
    return sorted(set(found), key=str.lower)


def find_strategy_file(strategy_name: str) -> Optional[str]:
    folder = project_path(STRATEGY_FOLDER_REL)
    for path in sorted(glob.glob(os.path.join(folder, "*.py")), key=natural_sort_key):
        if strategy_name in extract_strategy_classes_from_file(path):
            return path
    return None


def extract_strategy_timeframe(strategy_name: str) -> str:
    path = find_strategy_file(strategy_name)
    if not path:
        return "5m"
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return "5m"
    m = re.search(r"^\s*timeframe\s*(?::\s*str\s*)?=\s*[\"']([^\"']+)[\"']", text, flags=re.MULTILINE)
    return m.group(1).strip() if m else "5m"


def extract_startup_candle_count(strategy_name: str) -> Optional[int]:
    path = find_strategy_file(strategy_name)
    if not path:
        return None
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None
    for pattern in [r"^\s*startup_candle_count\s*:\s*int\s*=\s*(\d+)\b", r"^\s*startup_candle_count\s*=\s*(\d+)\b"]:
        m = re.search(pattern, text, flags=re.MULTILINE)
        if m:
            return int(m.group(1))
    return None


def auto_startup_candles(strategy_name: str) -> str:
    value = extract_startup_candle_count(strategy_name)
    if not value:
        return "199 399 499 999 1999"
    values: List[int] = []
    for mult in [1.0, 1.25, 2.0, 3.0, 5.0]:
        v = max(value, int(round(value * mult)))
        if v not in values:
            values.append(v)
    while len(values) < 5:
        values.append(values[-1] + value)
    return " ".join(str(x) for x in values[:5])


def startup_candles_looks_auto(value: str) -> bool:
    """Return True for old/helper-generated startup-candle sequences.

    This lets the UI replace stale fallback values like 199 399 499 999 1999,
    or previous strategy auto-values like 240 300 480 720 1200, when the selected
    strategy changes. Manual edits are still safe after the strategy is selected,
    because replacement is only triggered on strategy change.
    """
    clean = str(value or "").strip()
    if not clean:
        return True
    if clean == "199 399 499 999 1999":
        return True
    tokens = split_tokens(clean)
    return len(tokens) == 5 and all(token.isdigit() for token in tokens)


def remove_json_comments(text: str) -> str:
    result: List[str] = []
    i = 0
    in_string = False
    escape = False
    while i < len(text):
        char = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if in_string:
            result.append(char)
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            i += 1
            continue
        if char == '"':
            in_string = True
            result.append(char)
            i += 1
            continue
        if char == "/" and nxt == "/":
            i += 2
            while i < len(text) and text[i] not in "\r\n":
                i += 1
            if i < len(text):
                result.append(text[i])
                i += 1
            continue
        if char == "/" and nxt == "*":
            i += 2
            while i + 1 < len(text) and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        result.append(char)
        i += 1
    return "".join(result)


def load_jsonc_file(path: str) -> Dict[str, Any]:
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
        data = json.loads(remove_json_comments(text))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def deep_merge(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(base)
    for key, value in overlay.items():
        if isinstance(result.get(key), dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def resolve_add_config_path(add_config_file: str, base_dir: str) -> str:
    clean = add_config_file.replace("/", os.sep)
    if os.path.isabs(clean):
        return clean
    candidates = [
        os.path.join(base_dir, clean),
        project_path(clean),
        project_path(CONFIG_FOLDER, clean),
    ]
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return candidates[0]


def load_config_with_addons(path: str, visited: Optional[set[str]] = None) -> Dict[str, Any]:
    if visited is None:
        visited = set()
    abs_path = os.path.abspath(path)
    if abs_path in visited:
        return {}
    visited.add(abs_path)
    config = load_jsonc_file(abs_path)
    add_files = config.get("add_config_files", [])
    if not isinstance(add_files, list):
        return config
    base_dir = os.path.dirname(abs_path)
    for add_file in add_files:
        if not isinstance(add_file, str) or not add_file.strip():
            continue
        add_config = load_config_with_addons(resolve_add_config_path(add_file, base_dir), visited)
        if add_config:
            config = deep_merge(config, add_config)
    return config


def collect_config_chain_files(path: str, visited: Optional[set[str]] = None) -> List[str]:
    """Return selected config plus nested include files in display order."""
    if visited is None:
        visited = set()

    abs_path = os.path.abspath(path)
    if abs_path in visited:
        return []
    visited.add(abs_path)

    chain = [abs_path]
    data = load_jsonc_file(abs_path)
    add_files = data.get("add_config_files", [])
    if isinstance(add_files, list):
        base_dir = os.path.dirname(abs_path)
        for item in add_files:
            if isinstance(item, str) and item.strip():
                chain.extend(collect_config_chain_files(resolve_add_config_path(item, base_dir), visited))
    return chain


def pairlist_source_label(config_file: str) -> str:
    """User-facing pairlist source label for recursive CONFIG_PAIRLIST_DOWNLOADED.

    Avoids exposing implementation wording like add_config_files. Prefer a real
    pairlist filename when one can be detected; otherwise use a clean generic
    label.
    """
    try:
        config_path = project_path(config_file.replace("/", os.sep)) if not os.path.isabs(config_file) else config_file
        chain = collect_config_chain_files(config_path)
    except Exception:
        return "selected config pairlist"

    candidates: List[str] = []
    for path in chain:
        data = load_jsonc_file(path)
        base = os.path.basename(path)
        lower = base.lower()

        pairs_file = data.get("pairs_file")
        exchange = data.get("exchange", {}) if isinstance(data, dict) else {}
        if isinstance(exchange, dict) and not pairs_file:
            pairs_file = exchange.get("pairs_file")

        if isinstance(pairs_file, str) and pairs_file.strip():
            candidates.append(os.path.basename(pairs_file.replace("/", os.sep)))

        has_pairlist = False
        if isinstance(exchange, dict):
            has_pairlist = isinstance(exchange.get("pair_whitelist"), list) or isinstance(exchange.get("pair_blacklist"), list)

        if has_pairlist and any(token in lower for token in ("pair", "list", "analysis", "whitelist")):
            candidates.append(base)

    if candidates:
        # Prefer analysis/pair/list-looking files over generic config names.
        candidates = sorted(set(candidates), key=lambda x: (0 if any(t in x.lower() for t in ("analysis", "pair", "list")) else 1, x.lower()))
        return candidates[0]

    return "selected config pairlist"


def get_exchange_name(config: Dict[str, Any]) -> str:
    exchange = config.get("exchange", {})
    if isinstance(exchange, dict):
        name = exchange.get("name")
        if isinstance(name, str):
            return name.strip()
    return ""


def is_regex_pair_pattern(value: str) -> bool:
    return any(char in value for char in "*^$[](){}\\|+?")


def pattern_matches_pair(pattern: str, pair: str) -> bool:
    pattern = str(pattern or "").strip()
    if not pattern:
        return False
    if not is_regex_pair_pattern(pattern):
        return pattern.upper() == pair.upper()
    try:
        return bool(re.fullmatch(pattern, pair)) or bool(re.match(pattern, pair))
    except re.error:
        return False


def pair_allowed_by_config(pair: str, config: Dict[str, Any]) -> bool:
    exchange = config.get("exchange", {})
    whitelist: List[str] = []
    blacklist: List[str] = []
    if isinstance(exchange, dict):
        wl = exchange.get("pair_whitelist", [])
        bl = exchange.get("pair_blacklist", [])
        if isinstance(wl, list):
            whitelist = [x for x in wl if isinstance(x, str)]
        if isinstance(bl, list):
            blacklist = [x for x in bl if isinstance(x, str)]
    if not whitelist:
        return False
    if not any(pattern_matches_pair(pattern, pair) for pattern in whitelist):
        return False
    if any(pattern_matches_pair(pattern, pair) for pattern in blacklist):
        return False
    return True


def pair_from_data_filename(path: str, timeframe: str) -> Optional[str]:
    filename = os.path.basename(path)
    base = None
    for ext in (".feather", ".json", ".json.gz", ".parquet"):
        suffix = f"-{timeframe}{ext}"
        if filename.endswith(suffix):
            base = filename[: -len(suffix)]
            break
    if not base or "_" not in base:
        return None
    left, right = base.rsplit("_", 1)
    if not left or not right:
        return None
    return f"{left}/{right}".upper()


def scan_downloaded_pairs(timeframe: str, exchange_name: str = "") -> List[str]:
    data_root = project_path("user_data", "data")
    if not os.path.isdir(data_root):
        return []
    search_roots: List[str] = []
    if exchange_name:
        exchange_root = os.path.join(data_root, exchange_name)
        if os.path.isdir(exchange_root):
            search_roots.append(exchange_root)
    search_roots.append(data_root)
    files: List[str] = []
    for root in search_roots:
        for ext in ("feather", "json", "json.gz", "parquet"):
            files.extend(glob.glob(os.path.join(root, "**", f"*-{timeframe}.{ext}"), recursive=True))
    pairs = [pair_from_data_filename(path, timeframe) for path in files]
    return sorted({pair for pair in pairs if pair})


def expand_config_pairlist_to_downloaded_pairs(config_file: str, timeframe: str) -> List[str]:
    config_path = project_path(config_file.replace("/", os.sep)) if not os.path.isabs(config_file) else config_file
    config = load_config_with_addons(config_path)
    exchange_name = get_exchange_name(config)
    downloaded_pairs = scan_downloaded_pairs(timeframe=timeframe, exchange_name=exchange_name)
    return [pair for pair in downloaded_pairs if pair_allowed_by_config(pair, config)]


def list_custom_hyperopt_losses() -> List[str]:
    folder = project_path(HYPEROPTS_FOLDER_REL)
    found: List[str] = []
    for path in sorted(glob.glob(os.path.join(folder, "*.py")), key=natural_sort_key):
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for class_name in re.findall(r"class\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(\s*IHyperOptLoss\s*\)\s*:", text):
            found.append(class_name)
    return sorted(set(found), key=str.lower)


def split_tokens(value: str) -> List[str]:
    return [x.strip() for x in re.split(r"[,\s]+", value.strip()) if x.strip()]


def parse_positive_int(value: str, default: int) -> int:
    try:
        out = int(str(value).strip())
        return out if out > 0 else default
    except Exception:
        return default

# =====================================================================================
# Command builders
# =====================================================================================
def timerange_from_vars(window: str, custom: str) -> str:
    if window == "CUSTOM":
        return custom.strip()
    return TIME_WINDOWS.get(window, custom.strip())


def build_backtest_command(settings: Dict[str, Any]) -> Tuple[List[str], str]:
    config = settings["config"]
    timerange = timerange_from_vars(settings["window"], settings["custom_timerange"])
    label = config_name_to_label(config)
    container = unique_container_name("Freqtrade_Backtest", label)
    cmd = [
        DOCKER_COMPOSE,
        "run",
        "--name",
        container,
        "--rm",
        DOCKER_SERVICE,
        "backtesting",
        "--config",
        config,
        "--data-format-ohlcv",
        DATA_FORMAT_OHLCV,
        "--export",
        "trades",
        "--timerange",
        timerange,
    ]
    if not settings.get("use_cache", False):
        cmd.extend(["--cache", "none"])
    if settings.get("disable_max_market_positions", False):
        cmd.append("--disable-max-market-positions")
    if settings.get("enable_position_stacking", False):
        cmd.append("--enable-position-stacking")
    return cmd, container


def build_hyperopt_command(settings: Dict[str, Any]) -> Tuple[List[str], str]:
    config = settings["config"]
    timerange = timerange_from_vars(settings["window"], settings["custom_timerange"])
    label = config_name_to_label(config)
    container = unique_container_name("Freqtrade_Hyperopt", label)
    spaces = split_tokens(settings.get("spaces", "buy sell roi stoploss trailing"))
    loss = settings.get("hyperopt_loss", "SharpeHyperOptLossDaily").strip() or "SharpeHyperOptLossDaily"
    cmd = [
        DOCKER_COMPOSE,
        "run",
        "--name",
        container,
        # No --rm for hyperopt. We need the stopped container after completion
        # so docker logs can be read while the live terminal output remains direct.
        DOCKER_SERVICE,
        "hyperopt",
        "--config",
        config,
        "--data-format-ohlcv",
        DATA_FORMAT_OHLCV,
        "--timerange",
        timerange,
        "--spaces",
        *spaces,
        "-e",
        str(parse_positive_int(settings.get("epochs", "100"), 100)),
        "-j",
        str(parse_positive_int(settings.get("workers", "1"), 1)),
        "--hyperopt-loss",
        loss,
    ]
    seed_mode = str(settings.get("random_state_mode", "AUTO")).strip().upper() or "AUTO"
    if seed_mode == "CUSTOM":
        seed = str(settings.get("random_state", "")).strip()
        if seed and seed.upper() != "AUTO":
            cmd.extend(["--random-state", seed])
    elif seed_mode.isdigit():
        cmd.extend(["--random-state", seed_mode])
    return cmd, container


def build_analysis_command(settings: Dict[str, Any], pair_override: Optional[str] = None) -> Tuple[List[str], str]:
    mode = settings.get("analysis_mode", "lookahead-analysis")
    config = settings["config"]
    strategy = settings.get("strategy", "").strip()
    timerange = timerange_from_vars(settings["window"], settings["custom_timerange"])
    label_bits = [mode.replace("-analysis", ""), safe_container_part(strategy or "manual")]
    if pair_override:
        label_bits.append(pair_override.replace("/", "_"))
    container = unique_container_name("Freqtrade_Analysis", "_".join(label_bits))
    cmd = [
        DOCKER_COMPOSE,
        "run",
        "--name",
        container,
        "--rm",
        DOCKER_SERVICE,
        mode,
        "--config",
        config,
        "--strategy",
        strategy,
        "--timerange",
        timerange,
    ]
    if mode == "lookahead-analysis":
        cmd.extend([
            "--minimum-trade-amount",
            str(parse_positive_int(settings.get("minimum_trade_amount", "300"), 300)),
            "--targeted-trade-amount",
            str(parse_positive_int(settings.get("targeted_trade_amount", "1000"), 1000)),
        ])
    else:
        pairs = [pair_override] if pair_override else split_tokens(settings.get("pairs", "BTC/USDT"))
        if pairs:
            cmd.extend(["-p", *pairs])
        startup = split_tokens(settings.get("startup_candles", "199 399 499 999 1999"))
        if startup:
            cmd.extend(["--startup-candle", *startup])
    return cmd, container


def build_data_command(settings: Dict[str, Any]) -> Tuple[List[str], str]:
    action = settings.get("data_action", "download-data")
    label = safe_container_part(action)
    container = unique_container_name("Freqtrade_Data", label)
    exchange = settings.get("exchange", DEFAULT_EXCHANGE).strip() or DEFAULT_EXCHANGE

    if action == "download-data":
        timerange = timerange_from_vars(settings["window"], settings["custom_timerange"])
        tfs = split_tokens(settings.get("timeframes", "5m 1h 1d"))
        cmd = [
            DOCKER_COMPOSE,
            "run",
            "--name",
            container,
            "--rm",
            DOCKER_SERVICE,
            "download-data",
            "--exchange",
            exchange,
            "--config",
            settings.get("data_config", DEFAULT_DATA_CONFIG).strip() or DEFAULT_DATA_CONFIG,
            "--data-format-ohlcv",
            settings.get("data_format", DEFAULT_DATA_FORMAT).strip() or DEFAULT_DATA_FORMAT,
            "--timerange",
            timerange,
            "--timeframes",
            *tfs,
        ]
        if settings.get("include_inactive", False):
            cmd.append("--include-inactive-pairs")
        if settings.get("erase", False):
            cmd.append("--erase")
        return cmd, container

    if action == "list-data-timeranges":
        cmd = [
            DOCKER_COMPOSE,
            "run",
            "--name",
            container,
            "--rm",
            DOCKER_SERVICE,
            "list-data",
            "--show-timerange",
            "--exchange",
            exchange,
        ]
        return cmd, container

    cmd = [
        DOCKER_COMPOSE,
        "run",
        "--name",
        container,
        "--rm",
        DOCKER_SERVICE,
        "list-data",
        "--exchange",
        exchange,
    ]
    return cmd, container

# =====================================================================================
# Extractors / reports for runner mode
# =====================================================================================
def extract_strategy_name_from_backtest(text: str) -> str:
    clean = strip_ansi(text)
    m = re.search(r"Result for strategy\s+([^\r\n]+)", clean)
    return safe_filename(m.group(1).strip()) if m else "UNKNOWN_STRATEGY"


def extract_backtest_report(text: str) -> str:
    clean = strip_ansi(text)
    pattern = re.compile(r"(\s*BACKTESTING REPORT.*?\n\s*Backtested .*?\n\s*STRATEGY SUMMARY.*?┘)", re.DOTALL)
    m = pattern.search(clean)
    return m.group(1).strip() if m else ""


def get_window_name_from_timerange(timerange: str) -> str:
    for name, tr in TIME_WINDOWS.items():
        if name != "CUSTOM" and tr == timerange:
            return name
    return "CUSTOM"


def build_window_section(window_name: str, timerange: str, report: str) -> str:
    return f"===== WINDOW {window_name} | TIMERANGE {timerange} =====\n{report.strip()}\n===== END WINDOW {window_name} ====="


def reorder_backtest_sections(text: str) -> str:
    section_pattern = re.compile(r"(===== WINDOW (TRAIN|VALID|TEST|LIVE_CHECK|FULL|CUSTOM) \| TIMERANGE .*?^===== END WINDOW \2 =====)", re.DOTALL | re.MULTILINE)
    sections = section_pattern.findall(text)
    if not sections:
        return text.strip() + "\n"
    mapping: Dict[str, str] = {}
    extras: List[str] = []
    for full, name in sections:
        if name in ["TRAIN", "VALID", "TEST", "LIVE_CHECK", "FULL"] and name not in mapping:
            mapping[name] = full.strip()
        else:
            extras.append(full.strip())
    ordered = [mapping[x] for x in ["TRAIN", "VALID", "TEST", "LIVE_CHECK", "FULL"] if x in mapping]
    ordered.extend(extras)
    return "\n\n".join(ordered).strip() + "\n"


def save_backtest_report(raw_text: str, timerange: str, output_dir: Optional[str] = None) -> Optional[str]:
    report = extract_backtest_report(raw_text)
    if not report:
        return None
    strategy = extract_strategy_name_from_backtest(raw_text)
    folder = resolve_project_or_abs(output_dir or BACKTEST_REPORTS_FOLDER_REL)
    os.makedirs(folder, exist_ok=True)
    file_path = os.path.join(folder, f"{strategy}__BACKTESTING_REPORT.ini")
    window = get_window_name_from_timerange(timerange)
    new_section = build_window_section(window, timerange, report)
    existing = ""
    if os.path.isfile(file_path):
        existing = Path(file_path).read_text(encoding="utf-8", errors="replace")
    pattern = re.compile(rf"^===== WINDOW {re.escape(window)} \| TIMERANGE .*?^===== END WINDOW {re.escape(window)} =====\s*", re.DOTALL | re.MULTILINE)
    if pattern.search(existing):
        updated = pattern.sub(new_section + "\n\n", existing, count=1)
    else:
        updated = (existing.strip() + "\n\n" + new_section) if existing.strip() else new_section
    Path(file_path).write_text(reorder_backtest_sections(updated), encoding="utf-8", newline="\n")
    return file_path


def extract_strategy_name_from_hyperopt(text: str) -> str:
    clean = strip_ansi(text)
    patterns = [
        r"strategy_([A-Za-z0-9_]+)_\d{4}-\d{2}-\d{2}",
        r"Dumping parameters to\s+.*?[\\/]+([A-Za-z0-9_]+)\.json",
        r"Loading parameters from file\s+.*?[\\/]+([A-Za-z0-9_]+)\.json",
        r"Using resolved strategy\s+([A-Za-z0-9_]+)",
    ]
    for pattern in patterns:
        m = re.search(pattern, clean)
        if m:
            return safe_filename(m.group(1))
    return "hyperopt"


def extract_random_state(text: str) -> str:
    clean = strip_ansi(text)
    m = re.search(r"Using optimizer random state:\s*(\d+)", clean)
    if m:
        return m.group(1)
    m = re.search(r"--random-state\s+(\d+)", clean)
    if m:
        return m.group(1)
    return "UNKNOWN"


def extract_hyperopt_summary(text: str) -> str:
    clean = strip_ansi(text)
    best_match = re.search(r"Best result:", clean, flags=re.IGNORECASE)
    if best_match:
        before = clean[:best_match.start()]
        table_matches = list(re.finditer(r"Hyperopt results", before, flags=re.IGNORECASE))
        start = table_matches[-1].start() if table_matches else best_match.start()
    else:
        table_matches = list(re.finditer(r"Hyperopt results", clean, flags=re.IGNORECASE))
        if not table_matches:
            return ""
        start = table_matches[-1].start()
    summary = clean[start:].strip()
    for pattern in [
        r"# max_open_trades parameters:\s*\n\s*max_open_trades\s*=\s*.*?(?:\n\s*\n|\Z)",
        r"max_open_trades\s*=\s*.*?(?:\n\s*\n|\Z)",
        r"trailing_only_offset_is_reached\s*=\s*.*?(?:\n\s*\n|\Z)",
    ]:
        m = re.search(pattern, summary, flags=re.DOTALL)
        if m:
            return summary[:m.end()].strip()
    return summary


def save_hyperopt_extract(raw_text: str, metadata: Dict[str, Any], raw_file: str) -> Optional[str]:
    summary = extract_hyperopt_summary(raw_text)
    if not summary:
        return None
    strategy = extract_strategy_name_from_hyperopt(raw_text)
    stamp = stamp_now()
    loss = metadata.get("hyperopt_loss", "hyperopt")
    timerange = metadata.get("timerange", "")
    file_path = os.path.join(output_folder_from_metadata(metadata, "hyperopt_extracts"), safe_filename(f"Hyperopt_{strategy}_{loss}_{stamp}.txt"))
    lines = [
        "# Hyperopt Extract Metadata",
        f"strategy = {strategy}",
        f"timerange = {timerange}",
        f"hyperopt_loss = {loss}",
        f"random_state = {extract_random_state(raw_text)}",
        f"raw_output_file = {raw_file}",
        f"created_at = {stamp}",
        f"command = {metadata.get('command', '')}",
        "",
        summary,
        "",
    ]
    Path(file_path).write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return file_path


def extract_section_from_title(text: str, title: str, fallback: bool = True) -> str:
    clean = strip_ansi(text)
    lines = clean.splitlines()
    title_lower = title.lower()
    start = None
    for i, line in enumerate(lines):
        if line.strip().lower() == title_lower:
            start = i
            break
    if start is None:
        return clean.strip() if fallback else ""
    captured: List[str] = []
    for line in lines[start:]:
        stripped = line.strip()
        if captured and stripped.startswith("====="):
            break
        if captured and re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}\s+-\s+", stripped):
            break
        captured.append(line)
    return "\n".join(captured).strip()


def save_analysis_extract(raw_text: str, metadata: Dict[str, Any], raw_file: str) -> Optional[str]:
    mode = metadata.get("analysis_mode", "analysis")
    strategy = safe_filename(metadata.get("strategy", "strategy"))
    title = "Lookahead Analysis" if mode == "lookahead-analysis" else "Recursive Analysis"
    summary = extract_section_from_title(raw_text, title, fallback=True if mode == "lookahead-analysis" else False)
    if not summary:
        return None
    stamp = stamp_now()
    file_path = os.path.join(output_folder_from_metadata(metadata, "analysis_extracts"), safe_filename(f"{title.replace(' ', '-')}_{strategy}_{stamp}.txt"))
    lines = [
        "# Freqtrade Analysis Extract Metadata",
        f"mode = {mode}",
        f"strategy = {metadata.get('strategy', '')}",
        f"config = {metadata.get('config', '')}",
        f"timerange = {metadata.get('timerange', '')}",
        f"raw_output_file = {raw_file}",
        f"created_at = {stamp}",
        f"command = {metadata.get('command', '')}",
        "",
        summary,
        "",
    ]
    Path(file_path).write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return file_path


def parse_list_data_output(text: str) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for line in strip_ansi(text).splitlines():
        m = LIST_DATA_ROW_RE.match(line)
        if not m:
            continue
        pair = m.group("pair").strip()
        if pair.lower() == "pair" or not pair:
            continue
        rows.append({"pair": pair, "timeframes": m.group("timeframes").strip(), "market_type": m.group("type").strip()})
    return rows


def parse_timerange_output(text: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for line in strip_ansi(text).splitlines():
        m = TIMERANGE_ROW_RE.match(line)
        if not m:
            continue
        rows.append({
            "pair": m.group("pair").strip(),
            "timeframe": m.group("timeframe").strip(),
            "market_type": m.group("type").strip(),
            "start": m.group("start").strip(),
            "end": m.group("end").strip(),
            "count": int(m.group("count").strip()),
        })
    return rows


def write_csv(path: str, rows: List[Dict[str, Any]], fieldnames: List[str]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def update_job_record_file(path: str, updates: Dict[str, Any]) -> None:
    """Best-effort merge into the single jobs registry.

    This intentionally does NOT create per-job JSON sidecar files anymore.
    The only persistent job JSON should be:
        user_data/tools/Main_Py/Freqtrade_AIO_UI/jobs/Freqtrade_AIO_UI_jobs.json

    ``updates`` must contain ``id`` or ``job_id`` so the child runner can update
    its existing registry row.
    """
    if not path:
        return

    try:
        updates = dict(updates or {})
        job_id = str(updates.get("id") or updates.get("job_id") or "").strip()
        if not job_id:
            return

        os.makedirs(os.path.dirname(path), exist_ok=True)

        data: Dict[str, Any] = {
            "schema_version": 2,
            "project_root": PROJECT_ROOT,
            "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "jobs": [],
        }

        if os.path.isfile(path):
            try:
                loaded = json.loads(Path(path).read_text(encoding="utf-8", errors="replace"))
                if isinstance(loaded, dict):
                    data.update(loaded)
                elif isinstance(loaded, list):
                    data["jobs"] = loaded
            except Exception:
                pass

        jobs = data.get("jobs", [])
        if not isinstance(jobs, list):
            jobs = []

        cleaned_updates = {
            k: v
            for k, v in updates.items()
            if k not in {"job_id"} and v not in (None, "")
        }
        cleaned_updates["id"] = job_id
        cleaned_updates["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cleaned_updates["json_file"] = ""

        matched = False
        for idx, item in enumerate(jobs):
            if isinstance(item, dict) and str(item.get("id", "")).strip() == job_id:
                item.update(cleaned_updates)
                item["json_file"] = ""
                jobs[idx] = item
                matched = True
                break

        if not matched:
            jobs.append(cleaned_updates)

        data["schema_version"] = 2
        data["project_root"] = PROJECT_ROOT
        data["saved_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        data["jobs"] = jobs[-300:]

        Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8", newline="\n")
    except Exception:
        pass


def save_data_extract(raw_text: str, metadata: Dict[str, Any], raw_file: str) -> Optional[str]:
    action = metadata.get("data_action", "data")
    stamp = stamp_now()
    out_dir = output_folder_from_metadata(metadata, "data_audit")
    os.makedirs(out_dir, exist_ok=True)
    if action == "list-data":
        rows = parse_list_data_output(raw_text)
        if not rows:
            return None
        file_path = os.path.join(out_dir, safe_filename(f"list_data_pairs_{stamp}.csv"))
        write_csv(file_path, rows, ["pair", "timeframes", "market_type"])
        return file_path
    if action == "list-data-timeranges":
        rows = parse_timerange_output(raw_text)
        if not rows:
            return None
        file_path = os.path.join(out_dir, safe_filename(f"list_data_timeranges_{stamp}.csv"))
        write_csv(file_path, rows, ["pair", "timeframe", "market_type", "start", "end", "count"])
        return file_path
    return None

# =====================================================================================
# Runner mode
# =====================================================================================
def decode_payload(value: str) -> Dict[str, Any]:
    raw = base64.urlsafe_b64decode(value.encode("ascii"))
    text = zlib.decompress(raw).decode("utf-8")
    return json.loads(text)


def encode_payload(data: Dict[str, Any]) -> str:
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    compressed = zlib.compress(raw, level=9)
    return base64.urlsafe_b64encode(compressed).decode("ascii")


def run_analysis_batch_job(payload: Dict[str, Any]) -> int:
    ensure_windows_ansi()
    os.chdir(PROJECT_ROOT)
    ensure_dirs()

    jobs = payload.get("jobs", [])
    metadata = payload.get("metadata", {})
    job_registry_file = str(payload.get("job_registry_file", ""))
    job_id = str(payload.get("job_id", ""))
    update_job_record_file(job_registry_file, {
        "id": job_id,
        "status": "RUNNING",
        "started_child_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })
    max_parallel = max(1, parse_positive_int(str(metadata.get("max_parallel", "1")), 1))
    title = metadata.get("title", "Recursive analysis batch")
    stamp = stamp_now()
    raw_root = output_folder_from_metadata(metadata, "analysis_raw")
    extract_root = output_folder_from_metadata(metadata, "analysis_extracts")
    os.makedirs(raw_root, exist_ok=True)
    os.makedirs(extract_root, exist_ok=True)
    print_lock = threading.Lock()

    write_color("=" * 100, CYAN)
    write_color(f"START: ANALYSIS BATCH | {title}", GREEN)
    write_color(f"jobs={len(jobs)} | max_parallel={max_parallel}", WHITE)
    write_color("=" * 100, CYAN)

    def run_one(job: Dict[str, Any]) -> Dict[str, Any]:
        pair = str(job.get("pair", job.get("label", "job")))
        cmd = job["cmd"]
        container = job.get("container_name", safe_container_part(pair))
        safe_pair = safe_filename(pair.replace("/", "_"))
        raw_file = os.path.join(raw_root, safe_filename(f"raw_analysis_{safe_pair}_{container}_{stamp}.txt"))
        child_meta = dict(metadata)
        child_meta.update({
            "title": f"{metadata.get('analysis_mode', 'recursive-analysis')} {metadata.get('strategy', '')} {pair}",
            "container_name": container,
            "pair": pair,
            "raw_file": raw_file,
            "command": command_to_string(cmd),
        })
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["PY_COLORS"] = "1"
        env["CLICOLOR"] = "1"
        env["CLICOLOR_FORCE"] = "1"
        env["FORCE_COLOR"] = "1"
        env["TERM"] = env.get("TERM", "xterm-256color")
        captured: List[str] = []
        rc = 1
        with print_lock:
            write_color(f"===== START {pair} =====", CYAN)
            write_color(command_to_string(cmd), GREEN)
        try:
            with open(raw_file, "w", encoding="utf-8", newline="\n") as raw_handle:
                proc = subprocess.Popen(
                    cmd,
                    cwd=PROJECT_ROOT,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    stdin=None,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                )
                if proc.stdout is None:
                    raise RuntimeError("Could not open process stdout stream.")
                for raw_line in proc.stdout:
                    captured.append(raw_line)
                    raw_handle.write(strip_ansi(raw_line))
                    raw_handle.flush()
                    line = colorize_log_line(raw_line)
                    if line:
                        with print_lock:
                            print(f"[{pair}] {line}")
                rc = proc.wait()
        except Exception as e:
            captured.append(f"Runner failed for {pair}: {e}\n")
            with print_lock:
                write_color(f"Runner failed for {pair}: {e}", RED)
            rc = 98

        raw_text = "".join(captured)
        extract_file = None
        try:
            extract_file = save_analysis_extract(raw_text, child_meta, raw_file)
        except Exception as e:
            with print_lock:
                write_color(f"Extract/save failed for {pair}: {e}", RED)
        with print_lock:
            color = GREEN if rc == 0 else RED
            write_color(f"===== DONE {pair} | returncode={rc} =====", color)
        return {"pair": pair, "returncode": rc, "raw_file": raw_file, "extract_file": extract_file or "", "command": command_to_string(cmd)}

    results: List[Dict[str, Any]] = []
    if jobs:
        with ThreadPoolExecutor(max_workers=max_parallel) as pool:
            futures = [pool.submit(run_one, job) for job in jobs]
            for future in as_completed(futures):
                results.append(future.result())

    ok = sum(1 for row in results if int(row.get("returncode", 1)) == 0)
    failed = len(results) - ok
    report_file = os.path.join(extract_root, safe_filename(f"Recursive-Analysis_Batch_Report_{metadata.get('strategy', 'strategy')}_{stamp}.txt"))
    with open(report_file, "w", encoding="utf-8", newline="\n") as f:
        f.write("# Recursive Analysis Batch Report\n\n")
        f.write(f"title = {title}\n")
        f.write(f"jobs = {len(results)}\n")
        f.write(f"ok = {ok}\n")
        f.write(f"failed = {failed}\n")
        f.write(f"max_parallel = {max_parallel}\n")
        f.write(f"created_at = {stamp}\n\n")
        for row in sorted(results, key=lambda x: str(x.get("pair", ""))):
            f.write(f"pair = {row.get('pair')} | returncode = {row.get('returncode')} | extract = {row.get('extract_file')} | raw = {row.get('raw_file')}\n")

    update_job_record_file(job_registry_file, {
        "id": job_id,
        "status": "DONE" if failed == 0 else "FAILED",
        "returncode": 0 if failed == 0 else 1,
        "extract_file": report_file,
        "related_file": report_file,
        "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "cmd_file": "",
        "json_file": "",
    })

    write_color("=" * 100, CYAN)
    write_color(f"BATCH DONE | total={len(results)} | OK={ok} | FAILED={failed}", GREEN if failed == 0 else YELLOW)
    write_color(f"Batch report: {report_file}", GREEN)
    write_color("=" * 100, CYAN)
    return 0 if failed == 0 else 1


def run_hyperopt_child_job_direct(cmd: List[str], metadata: Dict[str, Any], raw_file: str) -> int:
    """Run hyperopt with direct console passthrough so Freqtrade progress renders normally.

    Hyperopt uses progress bars / live table redraws. If stdout is captured with
    subprocess.PIPE, Freqtrade no longer sees a real terminal and the progress UI
    degrades into the broken/static table seen in the screenshots.

    This mirrors the standalone Hyperopt helper style: run the docker command
    directly in the CMD window, then read docker logs from the named container for
    extraction/reporting, then remove the container.
    """
    container_name = str(metadata.get("container_name", "")).strip()
    job_registry_file = str(metadata.get("job_registry_file", "")).strip()
    job_id = str(metadata.get("job_id", "")).strip()
    update_job_record_file(job_registry_file, {
        "id": job_id,
        "status": "RUNNING",
        "started_child_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })
    cmd = command_without_rm(cmd)
    if container_name:
        remove_docker_container(container_name)

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PY_COLORS"] = "1"
    env["CLICOLOR"] = "1"
    env["CLICOLOR_FORCE"] = "1"
    env["FORCE_COLOR"] = "1"
    env["TERM"] = env.get("TERM", "xterm-256color")

    write_color("=" * 100, CYAN)
    write_color(f"START: HYPEROPT | {metadata.get('title', '')}", GREEN)
    write_color(f"PROJECT_ROOT: {PROJECT_ROOT}", WHITE)
    write_color("COMMAND:", GREEN)
    write_color(command_to_string(cmd), GREEN)
    write_color("=" * 100, CYAN)

    rc = 1
    raw_text = ""
    extract_file = None

    try:
        result = subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            env=env,
            check=False,
        )
        rc = int(result.returncode)

        raw_text = read_docker_container_logs(container_name)
        if raw_text.strip():
            os.makedirs(os.path.dirname(raw_file), exist_ok=True)
            Path(raw_file).write_text(strip_ansi(raw_text) + "\n", encoding="utf-8", newline="\n")
            try:
                extract_file = save_hyperopt_extract(raw_text, metadata, raw_file)
            except Exception as e:
                write_color(f"Extract/save step failed: {e}", RED)
        else:
            write_color("Docker logs were empty. Hyperopt extract not produced.", YELLOW)

    except KeyboardInterrupt:
        write_color("Interrupted by user.", YELLOW)
        rc = 130
    except Exception as e:
        err = f"Hyperopt direct runner failed: {e}"
        write_color(err, RED)
        try:
            os.makedirs(os.path.dirname(raw_file), exist_ok=True)
            Path(raw_file).write_text(err + "\n", encoding="utf-8", newline="\n")
        except Exception:
            pass
        rc = 98
    finally:
        if container_name:
            remove_docker_container(container_name)

    write_color("=" * 100, CYAN)
    if rc == 0:
        write_color(f"DONE: HYPEROPT | OK | returncode={rc}", GREEN)
    else:
        write_color(f"DONE: HYPEROPT | FAILED | returncode={rc}", RED)
    write_color(f"Raw output: {raw_file}", YELLOW)
    if extract_file:
        write_color(f"Extract/report: {extract_file}", GREEN)
    else:
        write_color("Extract/report: not produced for this run/output.", YELLOW)
    update_job_record_file(job_registry_file, {
        "id": job_id,
        "status": "DONE" if rc == 0 else "FAILED",
        "returncode": rc,
        "raw_file": raw_file,
        "extract_file": extract_file or "",
        "related_file": extract_file or raw_file,
        "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "cmd_file": "",
        "json_file": "",
    })
    write_color("=" * 100, CYAN)
    return rc


def run_child_job(payload: Dict[str, Any]) -> int:
    ensure_windows_ansi()
    os.makedirs(PROJECT_ROOT, exist_ok=True) if not os.path.exists(PROJECT_ROOT) else None
    os.chdir(PROJECT_ROOT)
    ensure_dirs()

    category = payload.get("category", "job")
    cmd = payload["cmd"]
    metadata = payload.get("metadata", {})
    job_registry_file = str(payload.get("job_registry_file", "")).strip()
    job_id = str(payload.get("job_id", "")).strip()
    if isinstance(metadata, dict):
        metadata["job_registry_file"] = job_registry_file
        metadata["job_id"] = job_id
    update_job_record_file(job_registry_file, {
        "id": job_id,
        "status": "RUNNING",
        "started_child_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })
    stamp = stamp_now()
    raw_key = {
        "backtest": "backtest_raw",
        "hyperopt": "hyperopt_raw",
        "analysis": "analysis_raw",
        "data": "data_raw",
    }.get(category, "data_raw")
    raw_dir = output_folder_from_metadata(metadata, raw_key)
    raw_file = os.path.join(raw_dir, safe_filename(f"raw_{category}_{metadata.get('container_name', 'job')}_{stamp}.txt"))
    metadata["raw_file"] = raw_file
    metadata["command"] = command_to_string(cmd)

    # Hyperopt must inherit the real CMD console. Capturing stdout with PIPE breaks
    # Freqtrade's live progress/table rendering. Direct mode still saves raw/extracts
    # by reading docker logs from the named container after completion.
    if category == "hyperopt":
        return run_hyperopt_child_job_direct(cmd, metadata, raw_file)

    write_color("=" * 100, CYAN)
    write_color(f"START: {category.upper()} | {metadata.get('title', '')}", GREEN)
    write_color(f"PROJECT_ROOT: {PROJECT_ROOT}", WHITE)
    write_color("COMMAND:", GREEN)
    write_color(command_to_string(cmd), GREEN)
    write_color("=" * 100, CYAN)

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PY_COLORS"] = "1"
    env["CLICOLOR"] = "1"
    env["CLICOLOR_FORCE"] = "1"
    env["FORCE_COLOR"] = "1"
    env["TERM"] = env.get("TERM", "xterm-256color")

    captured: List[str] = []
    suppressed = 0
    rc = 1
    try:
        with open(raw_file, "w", encoding="utf-8", newline="\n") as raw_handle:
            process = subprocess.Popen(
                cmd,
                cwd=PROJECT_ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=None,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
            if process.stdout is None:
                raise RuntimeError("Could not open process stdout stream.")
            for raw_line in process.stdout:
                captured.append(raw_line)
                raw_handle.write(strip_ansi(raw_line))
                raw_handle.flush()
                if is_suppressed_data_warning(raw_line):
                    suppressed += 1
                    sys.stdout.write(f"\r{CYAN}Suppressed data warnings: {suppressed}{RESET}")
                    sys.stdout.flush()
                    continue
                if suppressed:
                    sys.stdout.write("\r" + " " * 120 + "\r")
                    sys.stdout.flush()
                    suppressed = 0
                line = colorize_log_line(raw_line)
                if line:
                    print(line)
            rc = process.wait()
    except KeyboardInterrupt:
        write_color("Interrupted by user.", YELLOW)
        rc = 130
    except Exception as e:
        err = f"Runner failed: {e}"
        captured.append(err + "\n")
        write_color(err, RED)
        rc = 98

    raw_text = "".join(captured)
    extract_file = None
    try:
        if category == "backtest":
            extract_file = save_backtest_report(raw_text, metadata.get("timerange", ""), output_folder_from_metadata(metadata, "backtest_reports"))
        elif category == "hyperopt":
            extract_file = save_hyperopt_extract(raw_text, metadata, raw_file)
        elif category == "analysis":
            extract_file = save_analysis_extract(raw_text, metadata, raw_file)
        elif category == "data":
            extract_file = save_data_extract(raw_text, metadata, raw_file)
    except Exception as e:
        write_color(f"Extract/save step failed: {e}", RED)

    write_color("=" * 100, CYAN)
    if rc == 0:
        write_color(f"DONE: {category.upper()} | OK | returncode={rc}", GREEN)
    else:
        write_color(f"DONE: {category.upper()} | FAILED | returncode={rc}", RED)
    write_color(f"Raw output: {raw_file}", YELLOW)
    if extract_file:
        write_color(f"Extract/report: {extract_file}", GREEN)
    else:
        write_color("Extract/report: not produced for this run/output.", YELLOW)
    update_job_record_file(job_registry_file, {
        "id": job_id,
        "status": "DONE" if rc == 0 else "FAILED",
        "returncode": rc,
        "raw_file": raw_file,
        "extract_file": extract_file or "",
        "related_file": extract_file or raw_file,
        "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "cmd_file": "",
        "json_file": "",
    })
    write_color("=" * 100, CYAN)
    return rc

# =====================================================================================
# Tkinter UI
# =====================================================================================
@dataclass
class TabRefs:
    frame: ttk.Frame
    preview: tk.Text


class ToolTip:
    def __init__(self, widget: tk.Widget, text: str):
        self.widget = widget
        self.text = text
        self.tip: Optional[tk.Toplevel] = None
        widget.bind("<Enter>", self.show)
        widget.bind("<Leave>", self.hide)

    def show(self, _event: Any = None) -> None:
        if self.tip or not self.text:
            return
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + 20
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        label = tk.Label(self.tip, text=self.text, background=DARK_PANEL_2, foreground=DARK_TEXT, relief="solid", borderwidth=1, padx=8, pady=4)
        label.pack()

    def hide(self, _event: Any = None) -> None:
        if self.tip:
            self.tip.destroy()
            self.tip = None



class ScrollableFrame(ttk.Frame):
    """Reusable dark scroll container for notebook tabs.

    Keeps the layout usable on smaller screens by giving every long tab
    vertical and horizontal scrollbars instead of cutting off buttons/previews.
    """

    def __init__(self, parent: tk.Widget):
        super().__init__(parent)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self.canvas = tk.Canvas(
            self,
            background=DARK_BG,
            highlightthickness=0,
            borderwidth=0,
        )
        self.vbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.hbar = ttk.Scrollbar(self, orient="horizontal", command=self.canvas.xview)

        self.canvas.configure(
            yscrollcommand=self.vbar.set,
            xscrollcommand=self.hbar.set,
        )

        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.vbar.grid(row=0, column=1, sticky="ns")
        self.hbar.grid(row=1, column=0, sticky="ew")

        self.inner = ttk.Frame(self.canvas)
        self.window_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")

        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        # Mouse wheel works only while the pointer is over this tab.
        self.canvas.bind("<Enter>", self._bind_mousewheel)
        self.canvas.bind("<Leave>", self._unbind_mousewheel)
        self.inner.bind("<Enter>", self._bind_mousewheel)
        self.inner.bind("<Leave>", self._unbind_mousewheel)

    def _on_inner_configure(self, _event: Any = None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event: Any) -> None:
        # Keep the inner frame at least as wide as the visible canvas. If the tab
        # needs more width, the horizontal scrollbar still exposes it.
        try:
            requested = max(self.inner.winfo_reqwidth(), int(event.width))
            self.canvas.itemconfigure(self.window_id, width=requested)
        except Exception:
            pass

    def _bind_mousewheel(self, _event: Any = None) -> None:
        if os.name == "nt":
            self.canvas.bind_all("<MouseWheel>", self._on_mousewheel_windows)
            self.canvas.bind_all("<Shift-MouseWheel>", self._on_shift_mousewheel_windows)
        else:
            self.canvas.bind_all("<Button-4>", self._on_mousewheel_linux_up)
            self.canvas.bind_all("<Button-5>", self._on_mousewheel_linux_down)
            self.canvas.bind_all("<Shift-Button-4>", self._on_shift_mousewheel_linux_left)
            self.canvas.bind_all("<Shift-Button-5>", self._on_shift_mousewheel_linux_right)

    def _unbind_mousewheel(self, _event: Any = None) -> None:
        if os.name == "nt":
            self.canvas.unbind_all("<MouseWheel>")
            self.canvas.unbind_all("<Shift-MouseWheel>")
        else:
            self.canvas.unbind_all("<Button-4>")
            self.canvas.unbind_all("<Button-5>")
            self.canvas.unbind_all("<Shift-Button-4>")
            self.canvas.unbind_all("<Shift-Button-5>")

    def _on_mousewheel_windows(self, event: Any) -> None:
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _on_shift_mousewheel_windows(self, event: Any) -> None:
        self.canvas.xview_scroll(int(-1 * (event.delta / 120)), "units")

    def _on_mousewheel_linux_up(self, _event: Any) -> None:
        self.canvas.yview_scroll(-3, "units")

    def _on_mousewheel_linux_down(self, _event: Any) -> None:
        self.canvas.yview_scroll(3, "units")

    def _on_shift_mousewheel_linux_left(self, _event: Any) -> None:
        self.canvas.xview_scroll(-3, "units")

    def _on_shift_mousewheel_linux_right(self, _event: Any) -> None:
        self.canvas.xview_scroll(3, "units")


class FreqtradeAllInOneUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Freqtrade All-In-One UI Tool")
        self.root.geometry("1280x900")
        self.root.minsize(850, 620)
        self.root.configure(bg=DARK_BG)

        ensure_dirs()
        self.state_path = project_path(STATE_FILE_REL)
        self.state = self.load_state()
        self.configs = list_config_files()
        self.data_configs = list_data_config_files()
        self.strategies = list_strategy_classes()
        self.custom_losses = list_custom_hyperopt_losses()
        self.jobs: List[Dict[str, Any]] = self.load_jobs_registry()
        self._job_list_index_map: List[int] = []

        self.vars: Dict[str, tk.Variable] = {}
        self.previews: Dict[str, tk.Text] = {}
        self.field_widgets: Dict[str, tk.Widget] = {}
        self.analysis_recursive_buttons: List[tk.Widget] = []
        self._last_analysis_strategy_for_startup = ""
        self._last_analysis_auto_startup = ""
        self._last_analysis_pair_source = ""

        self.setup_style()
        self.build_ui()
        # Refresh registry immediately on startup so reopened UI does not show stale STARTED/RUNNING jobs.
        self.refresh_job_statuses()
        self.refresh_job_listbox()
        self.load_state_into_vars()
        self.sync_locked_fields()
        self.refresh_all_previews()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.schedule_job_status_refresh()

    # ---------------------------------------------------------------------------------
    # State
    # ---------------------------------------------------------------------------------
    def load_state(self) -> Dict[str, Any]:
        # Primary state now lives with the AIO tool files:
        # N:\FreqTrade\user_data\tools\Main_Py\Freqtrade_AIO_UI
        # Old state is still imported once when present, so previous defaults are not lost.
        try:
            if os.path.isfile(self.state_path):
                return json.loads(Path(self.state_path).read_text(encoding="utf-8"))
        except Exception:
            pass
        try:
            old_path = project_path(OLD_STATE_FILE_REL)
            if os.path.isfile(old_path):
                return json.loads(Path(old_path).read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def current_var_state(self) -> Dict[str, Any]:
        current: Dict[str, Any] = {}
        for key, var in self.vars.items():
            try:
                current[key] = var.get()
            except Exception:
                pass
        return current

    def clean_values_for_state(self, values: Dict[str, Any]) -> Dict[str, Any]:
        """Return a compact state/current/defaults payload.

        Older builds wrote every widget twice: once under ``current`` and again as
        flat root-level keys. Recursive pair expansion could also dump hundreds of
        generated pairs into ``analysis_pairs`` even when Pair source was CONFIG or
        RECOMMENDED. Those generated pairs are not real defaults; they can be
        re-created from the selected pair source.
        """
        reserved = {
            "schema_version",
            "project_root",
            "jobs",
            "current",
            "defaults",
            "startup_use_defaults",
            "saved_at",
        }
        cleaned: Dict[str, Any] = {
            key: value
            for key, value in dict(values or {}).items()
            if key not in reserved
        }

        pair_source = str(cleaned.get("analysis_pair_source", "")).strip().upper()
        if pair_source != "MANUAL":
            cleaned.pop("analysis_pairs", None)

        return cleaned

    def clean_defaults_for_state(self, defaults: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        cleaned_defaults: Dict[str, Dict[str, Any]] = {}
        if not isinstance(defaults, dict):
            return cleaned_defaults

        for tab, values in defaults.items():
            if isinstance(values, dict):
                cleaned_defaults[str(tab)] = self.clean_values_for_state(values)
        return cleaned_defaults

    def state_current_values(self) -> Dict[str, Any]:
        current = self.state.get("current", {})
        if isinstance(current, dict):
            out = dict(current)
        else:
            out = {}

        # Backward compatibility with old state files that stored widget values as
        # flat root-level keys. Read them once, but do not write them back.
        reserved = {"schema_version", "project_root", "jobs", "current", "defaults", "startup_use_defaults", "saved_at"}
        for key, value in self.state.items():
            if key not in reserved:
                out.setdefault(key, value)

        return self.clean_values_for_state(out)

    def state_defaults(self) -> Dict[str, Dict[str, Any]]:
        defaults = self.state.get("defaults", {})
        return self.clean_defaults_for_state(defaults) if isinstance(defaults, dict) else {}

    def save_state(self) -> None:
        current = self.clean_values_for_state(self.current_var_state())
        defaults = self.clean_defaults_for_state(self.state_defaults())
        startup_use_defaults = bool(self.vars.get("startup_use_defaults", tk.BooleanVar(value=True)).get())

        data: Dict[str, Any] = {
            "schema_version": 2,
            "project_root": PROJECT_ROOT,
            "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "jobs": [],  # job records live only in Freqtrade_AIO_UI_jobs.json
            "startup_use_defaults": startup_use_defaults,
            "current": current,
            "defaults": defaults,
        }

        try:
            Path(self.state_path).write_text(json.dumps(data, indent=2), encoding="utf-8", newline="\n")
            self.state = data
        except Exception as e:
            messagebox.showwarning("State save failed", str(e))

    def load_state_into_vars(self) -> None:
        current = self.state_current_values()
        defaults = self.state_defaults()
        startup_use_defaults = bool(self.state.get("startup_use_defaults", True))

        if "startup_use_defaults" in self.vars:
            try:
                self.vars["startup_use_defaults"].set(startup_use_defaults)
            except Exception:
                pass

        for key, var in self.vars.items():
            if key == "startup_use_defaults":
                continue

            tab = key.split("_", 1)[0] if "_" in key else ""
            value_set = False

            if startup_use_defaults and tab in defaults and key in defaults[tab]:
                try:
                    var.set(defaults[tab][key])
                    value_set = True
                except Exception:
                    pass

            if not value_set and key in current:
                try:
                    var.set(current[key])
                    value_set = True
                except Exception:
                    pass

            if not value_set and tab in defaults and key in defaults[tab]:
                try:
                    var.set(defaults[tab][key])
                except Exception:
                    pass

        # Backward compatibility: older AIO versions only had a raw seed box.
        # Convert that into the new AUTO/CUSTOM/preset seed selector once.
        if "hyperopt_random_state_mode" in self.vars:
            has_new_mode = (
                "hyperopt_random_state_mode" in current
                or any(
                    isinstance(v, dict) and "hyperopt_random_state_mode" in v
                    for v in defaults.values()
                )
            )
            if not has_new_mode:
                old_seed = str(current.get("hyperopt_random_state", "")).strip()
                if old_seed in PRESET_RANDOM_SEEDS:
                    self.vars["hyperopt_random_state_mode"].set(old_seed)
                elif old_seed.isdigit():
                    self.vars["hyperopt_random_state_mode"].set("CUSTOM")
                else:
                    self.vars["hyperopt_random_state_mode"].set("AUTO")

        self.refresh_job_listbox()

    def keys_for_tab(self, tab: str) -> List[str]:
        prefix = f"{tab}_"
        return [key for key in self.vars if key.startswith(prefix)]

    def save_defaults_for_tab(self, tab: str, show_message: bool = True) -> None:
        defaults = self.state_defaults()
        tab_values: Dict[str, Any] = {}
        for key in self.keys_for_tab(tab):
            try:
                tab_values[key] = self.vars[key].get()
            except Exception:
                pass
        defaults[tab] = self.clean_values_for_state(tab_values)
        self.state["defaults"] = defaults
        self.save_state()
        if show_message:
            messagebox.showinfo("Defaults saved", f"Saved {tab} defaults.")

    def save_defaults_for_all(self) -> None:
        defaults = self.state_defaults()
        for tab in ("backtest", "hyperopt", "analysis", "data"):
            tab_values: Dict[str, Any] = {}
            for key in self.keys_for_tab(tab):
                try:
                    tab_values[key] = self.vars[key].get()
                except Exception:
                    pass
            defaults[tab] = self.clean_values_for_state(tab_values)
        self.state["defaults"] = defaults
        self.save_state()
        messagebox.showinfo("Defaults saved", "Saved compact defaults for Backtest, Hyperopt, Analysis, and Data.")

    def load_defaults_for_tab(self, tab: str) -> None:
        defaults = self.state_defaults().get(tab, {})
        if not defaults:
            messagebox.showwarning("No defaults", f"No saved defaults found for {tab}.")
            return
        for key, value in defaults.items():
            if key in self.vars:
                try:
                    self.vars[key].set(value)
                except Exception:
                    pass
        self.save_state()
        self.refresh_all_previews()

    # ---------------------------------------------------------------------------------
    # Style / layout helpers
    # ---------------------------------------------------------------------------------
    def setup_style(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure(".", background=DARK_BG, foreground=DARK_TEXT, font=("Segoe UI", 10))
        style.configure("TFrame", background=DARK_BG)
        style.configure("TLabelframe", background=DARK_BG, foreground=DARK_TEXT, bordercolor=DARK_BORDER)
        style.configure("TLabelframe.Label", background=DARK_BG, foreground=DARK_TEXT, font=("Segoe UI", 10, "bold"))
        style.configure("TLabel", background=DARK_BG, foreground=DARK_TEXT)
        style.configure("Header.TLabel", background=DARK_BG, foreground=DARK_TEXT, font=("Segoe UI", 12, "bold"))
        style.configure("Small.TLabel", background=DARK_BG, foreground=DARK_MUTED)
        style.configure("Detail.TLabel", background=DARK_BG, foreground=DARK_MUTED, font=("Segoe UI", 9))

        style.configure("TButton", padding=(10, 5), background=DARK_PANEL_2, foreground=DARK_TEXT, bordercolor=DARK_BORDER)
        style.map("TButton", background=[("active", DARK_BORDER), ("pressed", DARK_FIELD)], foreground=[("disabled", DARK_MUTED)])

        style.configure("Run.TButton", padding=(16, 7), font=("Segoe UI", 10, "bold"), background=DARK_ACCENT, foreground="#ffffff", bordercolor=DARK_ACCENT)
        style.map("Run.TButton", background=[("active", DARK_ACCENT_ACTIVE), ("pressed", DARK_ACCENT)], foreground=[("disabled", DARK_MUTED)])

        style.configure("TNotebook", background=DARK_BG, borderwidth=0)
        style.configure("TNotebook.Tab", padding=(14, 8), font=("Segoe UI", 10, "bold"), background=DARK_PANEL, foreground=DARK_MUTED, bordercolor=DARK_BORDER)
        style.map("TNotebook.Tab", background=[("selected", DARK_PANEL_2), ("active", DARK_BORDER)], foreground=[("selected", DARK_TEXT), ("active", DARK_TEXT)])

        style.configure("TEntry", fieldbackground=DARK_FIELD, foreground=DARK_TEXT, insertcolor=DARK_TEXT, bordercolor=DARK_BORDER, lightcolor=DARK_BORDER, darkcolor=DARK_BORDER)
        style.configure("Locked.TEntry", fieldbackground=DARK_PANEL_2, foreground=DARK_MUTED, insertcolor=DARK_MUTED, bordercolor=DARK_BORDER, lightcolor=DARK_BORDER, darkcolor=DARK_BORDER)
        style.configure("TCombobox", fieldbackground=DARK_FIELD, foreground=DARK_TEXT, background=DARK_PANEL_2, arrowcolor=DARK_TEXT, bordercolor=DARK_BORDER, lightcolor=DARK_BORDER, darkcolor=DARK_BORDER)
        style.map(
            "TCombobox",
            fieldbackground=[("disabled", DARK_PANEL_2), ("readonly", DARK_FIELD), ("active", DARK_FIELD)],
            foreground=[("disabled", DARK_MUTED), ("readonly", DARK_TEXT), ("active", DARK_TEXT)],
            background=[("disabled", DARK_PANEL_2), ("readonly", DARK_PANEL_2), ("active", DARK_PANEL_2)],
            arrowcolor=[("disabled", DARK_MUTED), ("readonly", DARK_TEXT), ("active", DARK_TEXT)],
            selectbackground=[("disabled", DARK_PANEL_2), ("readonly", DARK_FIELD)],
            selectforeground=[("disabled", DARK_MUTED), ("readonly", DARK_TEXT)],
        )
        style.configure("TCheckbutton", background=DARK_BG, foreground=DARK_TEXT)
        style.map("TCheckbutton", background=[("active", DARK_BG)], foreground=[("active", DARK_TEXT), ("disabled", DARK_MUTED)])

    def var(self, key: str, default: Any = "", kind: str = "str") -> tk.Variable:
        if key in self.vars:
            return self.vars[key]
        if kind == "bool":
            v: tk.Variable = tk.BooleanVar(value=bool(default))
        else:
            v = tk.StringVar(value=str(default))
        self.vars[key] = v
        v.trace_add("write", lambda *_args: self.on_var_change())
        return v

    def make_row(self, parent: ttk.Frame, row: int, label: str, widget: tk.Widget, help_text: str = "") -> None:
        # Legacy helper retained for any future simple rows. New tabs use compact field cards.
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=8, pady=5)
        widget.grid(row=row, column=1, sticky="ew", padx=8, pady=5)
        if help_text:
            detail = ttk.Label(parent, text=help_text, style="Detail.TLabel", wraplength=420, justify="left")
            detail.grid(row=row + 1, column=1, sticky="w", padx=8, pady=(0, 6))

    def combo(self, parent: ttk.Frame, key: str, values: List[str], default: str, width: int = 28, readonly: bool = False) -> ttk.Combobox:
        cb = ttk.Combobox(parent, textvariable=self.var(key, default), values=values, width=width, state="readonly" if readonly else "normal")
        self.field_widgets[key] = cb
        return cb

    def entry(self, parent: ttk.Frame, key: str, default: str, width: int = 28) -> ttk.Entry:
        ent = ttk.Entry(parent, textvariable=self.var(key, default), width=width)
        self.field_widgets[key] = ent
        return ent

    def check(self, parent: ttk.Frame, key: str, text: str, default: bool = False) -> ttk.Checkbutton:
        chk = ttk.Checkbutton(parent, text=text, variable=self.var(key, default, kind="bool"))
        self.field_widgets[key] = chk
        return chk

    def clone_widget_into(self, target: ttk.Frame, widget: tk.Widget) -> tk.Widget:
        """
        Recreate a widget inside the card that will display it.

        Tk widgets cannot be re-parented after creation. The first compact layout
        accidentally created inputs with the outer form as their parent, then tried
        to grid them inside inner cards. Tk gridded them against the outer form,
        which made fields overlap and appear under the wrong labels. This helper
        keeps the compact card layout while creating the actual visible control
        inside the correct card.
        """
        key = next((name for name, stored in self.field_widgets.items() if stored is widget), "")
        var = self.vars.get(key) if key else None

        try:
            width = int(widget.cget("width"))
        except Exception:
            width = 28

        new_widget: tk.Widget

        if isinstance(widget, ttk.Combobox):
            try:
                values = list(widget.cget("values"))
            except Exception:
                values = []
            try:
                state = str(widget.cget("state"))
            except Exception:
                state = "normal"
            new_widget = ttk.Combobox(
                target,
                textvariable=var,
                values=values,
                width=width,
                state=state,
            )

        elif isinstance(widget, ttk.Entry):
            new_widget = ttk.Entry(target, textvariable=var, width=width)

        elif isinstance(widget, ttk.Checkbutton):
            try:
                text = str(widget.cget("text"))
            except Exception:
                text = ""
            new_widget = ttk.Checkbutton(target, text=text, variable=var)

        else:
            # Unknown widget type. Keep it usable in its original parent.
            return widget

        if key:
            self.field_widgets[key] = new_widget

        try:
            widget.destroy()
        except Exception:
            pass

        return new_widget

    def field_card(self, parent: ttk.Frame, row: int, col: int, label: str, widget: tk.Widget, detail: str = "", colspan: int = 1, wrap: int = 600) -> ttk.Frame:
        card = ttk.Frame(parent, padding=(6, 4, 6, 4))
        card.grid(row=row, column=col, columnspan=colspan, sticky="nsew", padx=5, pady=4)
        card.columnconfigure(0, weight=1)

        fixed_widget = self.clone_widget_into(card, widget)

        ttk.Label(card, text=label).grid(row=0, column=0, sticky="w", pady=(0, 3))
        fixed_widget.grid(row=1, column=0, sticky="ew")
        if detail:
            ttk.Label(card, text=detail, style="Detail.TLabel", justify="left", wraplength=wrap).grid(row=2, column=0, sticky="w", pady=(4, 0))
        return card

    def check_card(self, parent: ttk.Frame, row: int, col: int, key: str, text: str, default: bool = False, detail: str = "") -> ttk.Frame:
        outer_widget = self.check(parent, key, text, default)
        card = ttk.Frame(parent, padding=(6, 4, 6, 4))
        card.grid(row=row, column=col, sticky="nsew", padx=5, pady=4)
        card.columnconfigure(0, weight=1)

        widget = self.clone_widget_into(card, outer_widget)
        widget.grid(row=0, column=0, sticky="w")
        if detail:
            ttk.Label(card, text=detail, style="Detail.TLabel", justify="left", wraplength=600).grid(row=1, column=0, sticky="w", pady=(4, 0))
        return card

    def preview_box(self, parent: ttk.Frame, key: str) -> tk.Text:
        box = tk.Text(
            parent,
            height=7,
            wrap="word",
            font=("Consolas", 9),
            background=DARK_FIELD,
            foreground=DARK_TEXT,
            insertbackground=DARK_TEXT,
            selectbackground=DARK_ACCENT,
            selectforeground="#ffffff",
            relief="flat",
            borderwidth=1,
            highlightthickness=1,
            highlightbackground=DARK_BORDER,
            highlightcolor=DARK_ACCENT,
        )
        self.previews[key] = box
        return box

    # ---------------------------------------------------------------------------------
    # Dynamic field locking / displayed selected values
    # ---------------------------------------------------------------------------------
    def configure_widget_state(self, key: str, enabled: bool, readonly: bool = False) -> None:
        widget = self.field_widgets.get(key)
        if widget is None:
            return
        try:
            if isinstance(widget, ttk.Combobox):
                widget.configure(state="readonly" if enabled and readonly else "normal" if enabled else "disabled")
            elif isinstance(widget, ttk.Entry):
                widget.configure(state="normal" if enabled else "disabled", style="TEntry" if enabled else "Locked.TEntry")
            elif isinstance(widget, ttk.Checkbutton):
                widget.configure(state="normal" if enabled else "disabled")
            else:
                widget.configure(state="normal" if enabled else "disabled")
        except Exception:
            pass

    def sync_analysis_recursive_controls(self) -> None:
        if "analysis_mode" not in self.vars:
            return

        is_recursive = str(self.vars["analysis_mode"].get() or "").strip() == "recursive-analysis"
        pair_source = str(self.vars.get("analysis_pair_source", tk.StringVar(value="MANUAL")).get() or "MANUAL").strip().upper()
        run_mode = str(self.vars.get("analysis_recursive_run_mode", tk.StringVar(value="single_command")).get() or "single_command").strip()

        # Recursive-only dropdowns. They are hard-disabled in lookahead mode.
        for key in ("analysis_pair_source", "analysis_recursive_run_mode", "analysis_display_mode"):
            self.configure_widget_state(key, is_recursive, readonly=True)

        # Recursive-only entries. Pairs is writable only in MANUAL mode.
        self.configure_widget_state("analysis_startup_candles", is_recursive)
        self.configure_widget_state("analysis_pairs", is_recursive and pair_source == "MANUAL")
        self.configure_widget_state("analysis_max_parallel", is_recursive and run_mode == "cmd_per_pair_parallel")

        # Lookahead-only controls stay enabled only for lookahead.
        self.configure_widget_state("analysis_minimum_trade_amount", not is_recursive)
        self.configure_widget_state("analysis_targeted_trade_amount", not is_recursive)

        # Button rules: source loading is useful only for CONFIG/RECOMMENDED; manual means type in Pairs.
        try:
            self.analysis_load_pairs_button.configure(state="normal" if (is_recursive and pair_source != "MANUAL") else "disabled")
        except Exception:
            pass
        try:
            self.analysis_auto_startup_button.configure(state="normal" if is_recursive else "disabled")
        except Exception:
            pass

        if is_recursive:
            # Auto-refresh Pairs when source changes, so CONFIG/RECOMMENDED immediately updates the greyed list.
            if pair_source != self._last_analysis_pair_source:
                self._last_analysis_pair_source = pair_source
                if pair_source == "RECOMMENDED":
                    self.vars["analysis_pairs"].set(" ".join(RECOMMENDED_RECURSIVE_PAIRS))
                elif pair_source == "CONFIG_PAIRLIST_DOWNLOADED":
                    try:
                        settings = self.collect_analysis()
                        pairs = self.resolve_analysis_pairs(settings)
                        if pairs:
                            self.vars["analysis_pairs"].set(" ".join(pairs))
                    except Exception:
                        # Keep the previous visible list if scanning config/downloaded data fails.
                        pass

            strategy = str(self.vars.get("analysis_strategy", tk.StringVar(value="")).get() or "").strip()
            if strategy and strategy != self._last_analysis_strategy_for_startup:
                auto = auto_startup_candles(strategy)
                current = str(self.vars.get("analysis_startup_candles", tk.StringVar(value="")).get() or "").strip()

                # Replace only values that look like previous auto-generated startup lists.
                # This removes stale values such as 199 399 499 999 1999 or 240 300 480 720 1200
                # when the selected strategy's startup_candle_count is different.
                if current == self._last_analysis_auto_startup or startup_candles_looks_auto(current):
                    self.vars["analysis_startup_candles"].set(auto)

                self._last_analysis_strategy_for_startup = strategy
                self._last_analysis_auto_startup = auto
        else:
            self._last_analysis_pair_source = pair_source

    def sync_locked_fields(self) -> None:
        syncing_before = getattr(self, "_syncing_ui", False)
        self._syncing_ui = True
        try:
            for prefix in ("backtest", "hyperopt", "analysis", "data"):
                window_key = f"{prefix}_window"
                timerange_key = f"{prefix}_custom_timerange"
                if window_key not in self.vars or timerange_key not in self.vars:
                    continue
                window = str(self.vars[window_key].get() or "TRAIN")
                entry = self.field_widgets.get(timerange_key)
                if window != "CUSTOM":
                    preset = TIME_WINDOWS.get(window, "")
                    if preset:
                        self.vars[timerange_key].set(preset)
                    if entry is not None:
                        try:
                            entry.configure(state="readonly", style="Locked.TEntry")
                        except Exception:
                            entry.configure(state="disabled")
                else:
                    # CUSTOM must stay freely editable. Do not auto-replace partial input
                    # like 20240101-2026041 while the user is typing/deleting digits.
                    # Validation happens only when Run/Copy/Preview command generation needs it.
                    current = str(self.vars[timerange_key].get() or "").strip()
                    if current.upper() == "AUTO":
                        self.vars[timerange_key].set(TIME_WINDOWS.get("TRAIN", "20240101-20240701"))
                    if entry is not None:
                        try:
                            entry.configure(state="normal", style="TEntry")
                        except Exception:
                            entry.configure(state="normal")

            mode_key = "hyperopt_random_state_mode"
            seed_key = "hyperopt_random_state"
            if mode_key in self.vars and seed_key in self.vars:
                mode = str(self.vars[mode_key].get() or "AUTO").strip().upper()
                if mode == "TEST_FUNCTION_42":
                    mode = "42"
                    self.vars[mode_key].set("42")
                entry = self.field_widgets.get(seed_key)
                if mode == "AUTO":
                    self.vars[seed_key].set("AUTO")
                    if entry is not None:
                        entry.configure(state="readonly", style="Locked.TEntry")
                elif mode == "CUSTOM":
                    current = str(self.vars[seed_key].get() or "").strip()
                    if current.upper() == "AUTO" or not current:
                        self.vars[seed_key].set("42")
                    if entry is not None:
                        entry.configure(state="normal", style="TEntry")
                elif mode.isdigit():
                    self.vars[seed_key].set(mode)
                    if entry is not None:
                        entry.configure(state="readonly", style="Locked.TEntry")
                else:
                    self.vars[mode_key].set("AUTO")
                    self.vars[seed_key].set("AUTO")
                    if entry is not None:
                        entry.configure(state="readonly", style="Locked.TEntry")

            self.sync_analysis_recursive_controls()
        finally:
            self._syncing_ui = syncing_before

    def on_var_change(self) -> None:
        if getattr(self, "_syncing_ui", False):
            return
        if hasattr(self, "_preview_after"):
            try:
                self.root.after_cancel(self._preview_after)  # type: ignore[attr-defined]
            except Exception:
                pass
        self._preview_after = self.root.after(150, self.sync_ui_and_refresh)  # type: ignore[attr-defined]

    def sync_ui_and_refresh(self) -> None:
        self.sync_locked_fields()
        self.refresh_all_previews()

    # ---------------------------------------------------------------------------------
    # Build UI
    # ---------------------------------------------------------------------------------
    def build_ui(self) -> None:
        top = ttk.Frame(self.root, padding=10)
        top.pack(fill="x")

        # Left side expands. Right side keeps buttons fixed.
        top.columnconfigure(0, weight=1)
        top.columnconfigure(1, weight=0)

        # =================================================================================
        # LEFT HEADER
        # Title on top. Project and Files directly underneath the title.
        # =================================================================================
        header_left = ttk.Frame(top)
        header_left.grid(row=0, column=0, sticky="nw", padx=(0, 14))
        header_left.columnconfigure(0, weight=1)

        ttk.Label(
            header_left,
            text="Freqtrade All-In-One UI Tool",
            style="Header.TLabel",
        ).grid(row=0, column=0, sticky="w")

        self.project_root_label_var = tk.StringVar(value=f"Project: {PROJECT_ROOT}")
        ttk.Label(
            header_left,
            textvariable=self.project_root_label_var,
            style="Small.TLabel",
            wraplength=560,
            justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

        ttk.Label(
            header_left,
            text=f"Files: {TOOL_FOLDER_REL}",
            style="Small.TLabel",
            wraplength=560,
            justify="left",
        ).grid(row=2, column=0, sticky="w", pady=(2, 0))

        # =================================================================================
        # RIGHT HEADER BUTTONS
        # Two rows so buttons don't crush/cut each other.
        # =================================================================================
        header_right = ttk.Frame(top)
        header_right.grid(row=0, column=1, sticky="ne")

        header_right_top = ttk.Frame(header_right)
        header_right_top.grid(row=0, column=0, sticky="e")

        header_right_bottom = ttk.Frame(header_right)
        header_right_bottom.grid(row=1, column=0, sticky="e", pady=(6, 0))

        ttk.Checkbutton(
            header_right_top,
            text="Open with saved defaults",
            variable=self.var("startup_use_defaults", True, kind="bool"),
        ).pack(side="left", padx=(0, 10))

        ttk.Button(
            header_right_top,
            text="Save settings",
            command=self.save_state,
        ).pack(side="left", padx=4)

        ttk.Button(
            header_right_top,
            text="Save ALL defaults",
            command=self.save_defaults_for_all,
        ).pack(side="left", padx=4)

        ttk.Button(
            header_right_bottom,
            text="Open user_data folder",
            command=lambda: self.open_folder(project_path("user_data")),
        ).pack(side="left", padx=4)

        ttk.Button(
            header_right_bottom,
            text="Change project folder",
            command=self.change_project_folder,
        ).pack(side="left", padx=4)

        ttk.Button(
            header_right_bottom,
            text="Refresh files",
            command=self.refresh_discovery,
        ).pack(side="left", padx=4)

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self.build_backtest_tab()
        self.build_hyperopt_tab()
        self.build_analysis_tab()
        self.build_data_tab()
        self.build_paths_tab()
        self.build_jobs_tab()

    def build_standard_tab_shell(self, title: str) -> Tuple[ttk.Frame, ttk.Frame, ttk.Frame, ttk.Frame]:
        outer = ttk.Frame(self.notebook, padding=0)
        self.notebook.add(outer, text=title)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(0, weight=1)

        scroller = ScrollableFrame(outer)
        scroller.grid(row=0, column=0, sticky="nsew")

        frame = scroller.inner
        frame.configure(padding=10)
        frame.columnconfigure(0, weight=1)

        form = ttk.LabelFrame(frame, text="Parameters", padding=10)
        form.grid(row=0, column=0, sticky="ew")
        form.columnconfigure(0, weight=1, uniform="params")
        form.columnconfigure(1, weight=1, uniform="params")

        actions = ttk.Frame(frame, padding=(0, 8, 0, 0))
        actions.grid(row=1, column=0, sticky="ew")

        preview_frame = ttk.LabelFrame(frame, text="Command Preview", padding=8)
        preview_frame.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(0, weight=1)
        return frame, form, actions, preview_frame

    def add_window_cards(self, form: ttk.Frame, prefix: str, row: int, include_full: bool = False) -> int:
        values = ["TRAIN", "VALID", "TEST", "LIVE_CHECK"]
        if include_full:
            values.insert(0, "FULL")
        values.append("CUSTOM")
        self.field_card(
            form,
            row,
            0,
            "Time window",
            self.combo(form, f"{prefix}_window", values, "TRAIN", width=26, readonly=True),
            "Select a preset. The timerange field shows the active value.",
        )
        self.field_card(
            form,
            row,
            1,
            "Timerange selected",
            self.entry(form, f"{prefix}_custom_timerange", "20240101-20260410", width=28),
            "Locked for presets. Select CUSTOM to unlock and type YYYYMMDD-YYYYMMDD.",
        )
        return row + 1

    def build_backtest_tab(self) -> None:
        frame, form, actions, preview_frame = self.build_standard_tab_shell("Backtest")
        row = 0
        self.field_card(form, row, 0, "Config", self.combo(form, "backtest_config", self.configs, self.configs[0] if self.configs else "user_data/config-1.json", width=30), "Usual backtest config. Save as default if you mostly use one.")
        row = self.add_window_cards(form, "backtest", row + 1)
        self.check_card(form, row, 0, "backtest_use_cache", "Use cache", False, "Unchecked adds --cache none, matching your current default.")
        self.check_card(form, row, 1, "backtest_disable_max_market_positions", "Disable max market positions", False)
        row += 1
        self.check_card(form, row, 0, "backtest_enable_position_stacking", "Enable position stacking", False)
        self.check_card(form, row, 1, "backtest_pause", "Keep CMD open after finish", True)

        ttk.Button(actions, text="Run Backtest in new CMD", style="Run.TButton", command=self.run_backtest).pack(side="left", padx=4)
        ttk.Button(actions, text="Copy command", command=lambda: self.copy_preview("backtest")).pack(side="left", padx=4)
        ttk.Button(actions, text="Open latest report", command=self.open_latest_backtest_report).pack(side="left", padx=4)
        ttk.Button(actions, text="Open reports folder", command=lambda: self.open_folder(resolve_project_or_abs(self.collect_output_paths().get("backtest_reports", BACKTEST_REPORTS_FOLDER_REL)))).pack(side="left", padx=4)
        ttk.Button(actions, text="Save Backtest defaults", command=lambda: self.save_defaults_for_tab("backtest")).pack(side="left", padx=4)
        ttk.Button(actions, text="Load Backtest defaults", command=lambda: self.load_defaults_for_tab("backtest")).pack(side="left", padx=4)
        self.preview_box(preview_frame, "backtest").grid(row=0, column=0, sticky="nsew")

    def build_hyperopt_tab(self) -> None:
        frame, form, actions, preview_frame = self.build_standard_tab_shell("Hyperopt")

        # Hyperopt uses compact left/right columns. Random-state mode now sits
        # directly above Random state selected on the right side, so the two
        # controls read as one block. Spaces is moved up on the left to avoid
        # pushing the bottom buttons out of view.
        left = ttk.Frame(form)
        right = ttk.Frame(form)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        right.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        form.rowconfigure(0, weight=1)
        form.columnconfigure(0, weight=1, uniform="hyper_cols")
        form.columnconfigure(1, weight=1, uniform="hyper_cols")
        left.columnconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)

        losses = HYPEROPT_LOSSES + self.custom_losses
        loss_default = "SharpeHyperOptLossDaily"

        lrow = 0
        self.field_card(left, lrow, 0, "Time window", self.combo(left, "hyperopt_window", ["TRAIN", "VALID", "TEST", "LIVE_CHECK", "CUSTOM"], "TRAIN", width=26, readonly=True), "Select a preset. The timerange field shows the active value.")
        lrow += 1
        self.field_card(left, lrow, 0, "Config", self.combo(left, "hyperopt_config", self.configs, self.configs[0] if self.configs else "user_data/config-hyperopt.json", width=30), "Save your normal hyperopt config as default to avoid reselecting it.")
        lrow += 1
        self.field_card(left, lrow, 0, "Epochs (-e)", self.entry(left, "hyperopt_epochs", "100", width=16), "Number of epochs for this run.")
        lrow += 1
        self.field_card(left, lrow, 0, "Workers (-j)", self.entry(left, "hyperopt_workers", "1", width=16), "Parallel workers. Keep sensible for CPU/RAM.")
        lrow += 1
        self.field_card(left, lrow, 0, "Spaces", self.entry(left, "hyperopt_spaces", "buy sell roi stoploss trailing", width=32), SPACE_DETAILS, wrap=470)
        lrow += 1
        self.check_card(left, lrow, 0, "hyperopt_pause", "Keep CMD open after finish", True)

        rrow = 0
        self.field_card(right, rrow, 0, "Timerange selected", self.entry(right, "hyperopt_custom_timerange", "20240101-20260410", width=28), "Locked for presets. Select CUSTOM to unlock and type YYYYMMDD-YYYYMMDD.")
        rrow += 1
        self.field_card(right, rrow, 0, "Hyperopt loss", self.combo(right, "hyperopt_loss", losses, loss_default, width=34), "Selected loss decides what Hyperopt optimizes. Common: SharpeHyperOptLossDaily.\n\n" + "\n".join(f"{k}: {v}" for k, v in HYPEROPT_LOSS_DETAILS.items()), wrap=510)
        rrow += 1
        self.field_card(right, rrow, 0, "Random state mode", self.combo(right, "hyperopt_random_state_mode", RANDOM_STATE_MODE_VALUES, "AUTO", width=24, readonly=True), RANDOM_STATE_DETAILS, wrap=510)
        rrow += 1
        self.field_card(right, rrow, 0, "Random state selected", self.entry(right, "hyperopt_random_state", "AUTO", width=18), "Locked for AUTO and preset seeds. Writable only in CUSTOM mode.")

        ttk.Button(actions, text="Run Hyperopt in new CMD", style="Run.TButton", command=self.run_hyperopt).pack(side="left", padx=4)
        ttk.Button(actions, text="Copy command", command=lambda: self.copy_preview("hyperopt")).pack(side="left", padx=4)
        ttk.Button(actions, text="Open latest extract", command=self.open_latest_hyperopt_extract).pack(side="left", padx=4)
        ttk.Button(actions, text="Open extracts folder", command=lambda: self.open_folder(resolve_project_or_abs(self.collect_output_paths().get("hyperopt_extracts", HYPEROPT_EXTRACT_FOLDER_REL)))).pack(side="left", padx=4)
        ttk.Button(actions, text="Save Hyperopt defaults", command=lambda: self.save_defaults_for_tab("hyperopt")).pack(side="left", padx=4)
        ttk.Button(actions, text="Load Hyperopt defaults", command=lambda: self.load_defaults_for_tab("hyperopt")).pack(side="left", padx=4)
        self.preview_box(preview_frame, "hyperopt").grid(row=0, column=0, sticky="nsew")

    def build_analysis_tab(self) -> None:
        frame, form, actions, preview_frame = self.build_standard_tab_shell("Analysis")
        row = 0
        self.field_card(form, row, 0, "Mode", self.combo(form, "analysis_mode", ["lookahead-analysis", "recursive-analysis"], "lookahead-analysis", width=28, readonly=True), "Lookahead checks future leakage. Recursive checks indicator startup stability.", colspan=2)
        row += 1
        self.field_card(form, row, 0, "Strategy", self.combo(form, "analysis_strategy", self.strategies, self.strategies[0] if self.strategies else "", width=30), "Strategy class name. Recursive auto-startup uses this file.")
        self.field_card(form, row, 1, "Config", self.combo(form, "analysis_config", self.configs, self.configs[0] if self.configs else "user_data/config-analysis.json", width=30), "Analysis config.")
        row = self.add_window_cards(form, "analysis", row + 1, include_full=True)
        self.field_card(form, row, 0, "Minimum trades", self.entry(form, "analysis_minimum_trade_amount", "300", width=16), "Lookahead-analysis only.")
        self.field_card(form, row, 1, "Targeted trades", self.entry(form, "analysis_targeted_trade_amount", "1000", width=16), "Lookahead-analysis only.")
        row += 1

        recursive = ttk.LabelFrame(form, text="Recursive options", padding=8)
        recursive.grid(row=row, column=0, columnspan=2, sticky="nsew", padx=5, pady=(10, 4))
        recursive.columnconfigure(0, weight=1, uniform="recursive_cols")
        recursive.columnconfigure(1, weight=1, uniform="recursive_cols")

        rrow = 0
        pair_source_detail = (
            "CONFIG_PAIRLIST_DOWNLOADED = use selected config pairlist and downloaded data.\n"
            "RECOMMENDED = BTC/ETH/SOL/XRP.\n"
            "MANUAL = use Pairs field."
        )
        self.field_card(recursive, rrow, 0, "Pair source", self.combo(recursive, "analysis_pair_source", ANALYSIS_PAIR_SOURCE_VALUES, "RECOMMENDED", width=30, readonly=True), pair_source_detail)
        self.field_card(recursive, rrow, 1, "Pairs", self.entry(recursive, "analysis_pairs", "BTC/USDT ETH/USDT SOL/USDT XRP/USDT", width=34), "Resolved pair list used by recursive-analysis.\nWritable only when Pair source = MANUAL.")
        rrow += 1
        self.field_card(recursive, rrow, 0, "Startup candles", self.entry(recursive, "analysis_startup_candles", "199 399 499 999 1999", width=34), "Auto-detected from strategy startup_candle_count. Example: 240 -> 240 300 480 720 1200.")
        self.field_card(recursive, rrow, 1, "Recursive run mode", self.combo(recursive, "analysis_recursive_run_mode", ANALYSIS_RUN_MODE_VALUES, "single_command", width=30, readonly=True), "single_command = one Freqtrade command with all pairs; cmd_per_pair_parallel = slot-refill worker; cmd_per_pair_sequential = one pair at a time.")
        rrow += 1
        self.field_card(recursive, rrow, 0, "Recursive display mode", self.combo(recursive, "analysis_display_mode", ANALYSIS_DISPLAY_MODE_VALUES, "minimized_cmd", width=30, readonly=True), "silent = no CMD window; minimized_cmd = open minimized controller; visible_cmd = show controller window.")
        self.field_card(recursive, rrow, 1, "Max parallel", self.entry(recursive, "analysis_max_parallel", "5", width=12), "Used only by cmd_per_pair_parallel. Keeps only this many recursive pair jobs running.")

        row += 1
        self.check_card(form, row, 0, "analysis_pause", "Keep CMD open after finish", True)

        ttk.Button(actions, text="Run Analysis in new CMD", style="Run.TButton", command=self.run_analysis).pack(side="left", padx=4)
        ttk.Button(actions, text="Open latest analysis extract", command=self.open_latest_analysis_extract).pack(side="left", padx=4)
        self.analysis_load_pairs_button = ttk.Button(actions, text="Load pairs from source", command=self.load_analysis_pairs_from_source)
        self.analysis_load_pairs_button.pack(side="left", padx=4)
        self.analysis_auto_startup_button = ttk.Button(actions, text="Auto startup from strategy", command=self.fill_auto_startup)
        self.analysis_auto_startup_button.pack(side="left", padx=4)
        self.analysis_recursive_buttons = [self.analysis_load_pairs_button, self.analysis_auto_startup_button]
        ttk.Button(actions, text="Copy command", command=lambda: self.copy_preview("analysis")).pack(side="left", padx=4)
        ttk.Button(actions, text="Save Analysis defaults", command=lambda: self.save_defaults_for_tab("analysis")).pack(side="left", padx=4)
        ttk.Button(actions, text="Load Analysis defaults", command=lambda: self.load_defaults_for_tab("analysis")).pack(side="left", padx=4)
        self.preview_box(preview_frame, "analysis").grid(row=0, column=0, sticky="nsew")

    def build_data_tab(self) -> None:
        frame, form, actions, preview_frame = self.build_standard_tab_shell("Data")
        row = 0
        self.field_card(form, row, 0, "Action", self.combo(form, "data_action", ["download-data", "list-data", "list-data-timeranges"], "download-data", width=28, readonly=True), "Download, list pair/timeframe combos, or list available timeranges.")
        self.field_card(form, row, 1, "Exchange", self.entry(form, "data_exchange", DEFAULT_EXCHANGE, width=18), "Default: kucoin.")
        row += 1
        self.field_card(form, row, 0, "Data config", self.combo(form, "data_config", self.data_configs, self.data_configs[0] if self.data_configs else DEFAULT_DATA_CONFIG, width=34), "Used by download-data. Pick data_download.json or another config.")
        self.field_card(form, row, 1, "Data format", self.entry(form, "data_format", DEFAULT_DATA_FORMAT, width=18), "Default: feather.")
        row = self.add_window_cards(form, "data", row + 1)
        self.field_card(form, row, 0, "Timeframes", self.entry(form, "data_timeframes", "5m 1h 1d", width=28), "Download-data only. Available: 1m 3m 5m 15m 30m 1h 2h 4h 6h 8h 12h 1d.")
        self.check_card(form, row, 1, "data_include_inactive", "Include inactive pairs", False)
        row += 1
        self.check_card(form, row, 0, "data_erase", "Use --erase before download", False, "Dangerous: removes existing data before download.")
        self.check_card(form, row, 1, "data_pause", "Keep CMD open after finish", True)

        ttk.Button(actions, text="Run Data command in new CMD", style="Run.TButton", command=self.run_data).pack(side="left", padx=4)
        ttk.Button(actions, text="Copy command", command=lambda: self.copy_preview("data")).pack(side="left", padx=4)
        ttk.Button(actions, text="Open latest data audit", command=self.open_latest_data_audit).pack(side="left", padx=4)
        ttk.Button(actions, text="Open data audit folder", command=lambda: self.open_folder(resolve_project_or_abs(self.collect_output_paths().get("data_audit", DATA_AUDIT_FOLDER_REL)))).pack(side="left", padx=4)
        ttk.Button(actions, text="Save Data defaults", command=lambda: self.save_defaults_for_tab("data")).pack(side="left", padx=4)
        ttk.Button(actions, text="Load Data defaults", command=lambda: self.load_defaults_for_tab("data")).pack(side="left", padx=4)
        self.preview_box(preview_frame, "data").grid(row=0, column=0, sticky="nsew")

    def path_row(self, parent: ttk.Frame, row: int, key: str, label: str, detail: str) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=8, pady=(5, 2))
        ent = ttk.Entry(parent, textvariable=self.var(key, DEFAULT_OUTPUT_PATHS.get(key.replace("path_", ""), "")), width=70)
        ent.grid(row=row, column=1, sticky="ew", padx=8, pady=(5, 2))
        self.field_widgets[key] = ent
        ttk.Button(parent, text="Browse", command=lambda k=key: self.browse_folder(k)).grid(row=row, column=2, sticky="ew", padx=4, pady=(5, 2))
        ttk.Button(parent, text="Open", command=lambda k=key: self.open_path_var(k)).grid(row=row, column=3, sticky="ew", padx=4, pady=(5, 2))
        ttk.Label(parent, text=detail, style="Detail.TLabel", justify="left", wraplength=760).grid(row=row + 1, column=1, columnspan=3, sticky="w", padx=8, pady=(0, 6))

    def build_paths_tab(self) -> None:
        outer = ttk.Frame(self.notebook, padding=0)
        self.notebook.add(outer, text="Paths")
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(0, weight=1)

        scroller = ScrollableFrame(outer)
        scroller.grid(row=0, column=0, sticky="nsew")

        frame = scroller.inner
        frame.configure(padding=10)
        frame.columnconfigure(0, weight=1)

        info = ttk.LabelFrame(frame, text="Output folders", padding=10)
        info.grid(row=0, column=0, sticky="ew")
        info.columnconfigure(1, weight=1)

        row = 0
        self.path_row(info, row, "path_backtest_reports", "Backtest reports", "Default: user_data/backtest_reports — same as the Backtest helper.")
        row += 2
        self.path_row(info, row, "path_backtest_raw", "Backtest raw logs", "Default: user_data/logs/backtest_raw_output — AIO raw capture for backtests.")
        row += 2
        self.path_row(info, row, "path_hyperopt_raw", "Hyperopt raw logs", "Default: user_data/logs/hyperopt_raw_output — same as the Hyperopt helper.")
        row += 2
        self.path_row(info, row, "path_hyperopt_extracts", "Hyperopt extracts", "Default: user_data/hyperopt_extracts — same as the Hyperopt helper.")
        row += 2
        self.path_row(info, row, "path_analysis_raw", "Analysis raw logs", "Default: user_data/logs/analysis_raw_output — same as the Analysis helper.")
        row += 2
        self.path_row(info, row, "path_analysis_extracts", "Analysis extracts", "Default: user_data/analysis_extracts — same as the Analysis helper.")
        row += 2
        self.path_row(info, row, "path_data_raw", "Data raw logs", "Default: user_data/logs/data_raw_output — AIO raw capture for data commands.")
        row += 2
        self.path_row(info, row, "path_data_audit", "Data audit / list CSV", "Default: user_data/data/data_audit — same as the Data utility.")

        buttons = ttk.Frame(frame, padding=(0, 8, 0, 0))
        buttons.grid(row=1, column=0, sticky="ew")
        ttk.Button(buttons, text="Save path settings", command=self.save_state).pack(side="left", padx=4)
        ttk.Button(buttons, text="Clean settings JSON", command=self.clean_settings_json_now).pack(side="left", padx=4)
        ttk.Button(buttons, text="Reset to original helper folders", command=self.reset_output_paths).pack(side="left", padx=4)
        ttk.Button(buttons, text="Open user_data folder", command=lambda: self.open_folder(project_path("user_data"))).pack(side="left", padx=4)

    def build_jobs_tab(self) -> None:
        frame = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(frame, text="Jobs")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)

        header = ttk.Frame(frame)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="Running + job history", style="Header.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text="Right-click a job for actions. Failed jobs are red; running/created are highlighted; categories use their own colors.",
            style="Detail.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(3, 0))

        self.job_listbox = tk.Listbox(
            frame,
            font=("Consolas", 9),
            background=DARK_FIELD,
            foreground=DARK_TEXT,
            selectbackground=DARK_ACCENT,
            selectforeground="#ffffff",
            relief="flat",
            highlightthickness=1,
            highlightbackground=DARK_BORDER,
            highlightcolor=DARK_ACCENT,
            activestyle="dotbox",
        )
        self.job_listbox.grid(row=1, column=0, sticky="nsew")

        buttons = ttk.Frame(frame)
        buttons.grid(row=2, column=0, sticky="ew", pady=8)

        self.jobs_refresh_button = ttk.Button(buttons, text="Refresh job status", command=self.refresh_jobs_now)
        self.jobs_refresh_button.pack(side="left", padx=4)

        self.jobs_follow_logs_button = ttk.Button(buttons, text="Follow selected logs", command=self.follow_selected_job_logs)
        self.jobs_follow_logs_button.pack(side="left", padx=4)

        self.jobs_open_result_button = ttk.Button(buttons, text="Open selected result", command=self.open_selected_job_related_file)
        self.jobs_open_result_button.pack(side="left", padx=4)

        self.jobs_delete_selected_button = ttk.Button(buttons, text="Delete selected history", command=self.delete_selected_job_history)
        self.jobs_delete_selected_button.pack(side="left", padx=4)

        ttk.Button(buttons, text="Open jobs folder", command=lambda: self.open_folder(project_path(UI_JOBS_FOLDER_REL))).pack(side="left", padx=4)
        ttk.Button(buttons, text="Open logs", command=lambda: self.open_folder(project_path(RAW_OUTPUT_FOLDER_REL))).pack(side="left", padx=4)
        ttk.Button(buttons, text="Clear history", command=self.clear_jobs).pack(side="left", padx=4)

        self.job_context_menu = tk.Menu(
            self.root,
            tearoff=0,
            background=DARK_PANEL_2,
            foreground=DARK_TEXT,
            activebackground=DARK_ACCENT,
            activeforeground="#ffffff",
            borderwidth=1,
            relief="solid",
        )

        self.job_listbox.bind("<<ListboxSelect>>", lambda _event: self.update_job_action_buttons())
        self.job_listbox.bind("<Button-3>", self.show_job_context_menu)
        self.job_listbox.bind("<Button-2>", self.show_job_context_menu)
        self.job_listbox.bind("<Delete>", lambda _event: self.delete_selected_job_history())
        self.job_listbox.bind("<Double-Button-1>", lambda _event: self.open_selected_job_related_file())
        self.update_job_action_buttons()

    def collect_output_paths(self) -> Dict[str, str]:
        return {
            "backtest_reports": self.vars.get("path_backtest_reports", tk.StringVar(value=BACKTEST_REPORTS_FOLDER_REL)).get(),
            "backtest_raw": self.vars.get("path_backtest_raw", tk.StringVar(value=BACKTEST_RAW_OUTPUT_FOLDER_REL)).get(),
            "hyperopt_raw": self.vars.get("path_hyperopt_raw", tk.StringVar(value=HYPEROPT_RAW_OUTPUT_FOLDER_REL)).get(),
            "hyperopt_extracts": self.vars.get("path_hyperopt_extracts", tk.StringVar(value=HYPEROPT_EXTRACT_FOLDER_REL)).get(),
            "analysis_raw": self.vars.get("path_analysis_raw", tk.StringVar(value=ANALYSIS_RAW_OUTPUT_FOLDER_REL)).get(),
            "analysis_extracts": self.vars.get("path_analysis_extracts", tk.StringVar(value=ANALYSIS_EXTRACT_FOLDER_REL)).get(),
            "data_raw": self.vars.get("path_data_raw", tk.StringVar(value=DATA_RAW_OUTPUT_FOLDER_REL)).get(),
            "data_audit": self.vars.get("path_data_audit", tk.StringVar(value=DATA_AUDIT_FOLDER_REL)).get(),
        }

    def browse_folder(self, key: str) -> None:
        current = self.vars[key].get() if key in self.vars else ""
        initial = resolve_project_or_abs(current or TOOL_FOLDER_REL)
        selected = filedialog.askdirectory(initialdir=initial, title="Choose output folder")
        if not selected:
            return
        try:
            value = rel_to_project(selected) if os.path.normcase(selected).startswith(os.path.normcase(PROJECT_ROOT)) else selected
        except Exception:
            value = selected
        self.vars[key].set(value.replace(os.sep, "/"))
        self.save_state()

    def open_path_var(self, key: str) -> None:
        if key not in self.vars:
            return
        self.open_folder(resolve_project_or_abs(self.vars[key].get()))

    def reset_output_paths(self) -> None:
        mapping = {
            "path_backtest_reports": BACKTEST_REPORTS_FOLDER_REL,
            "path_backtest_raw": BACKTEST_RAW_OUTPUT_FOLDER_REL,
            "path_hyperopt_raw": HYPEROPT_RAW_OUTPUT_FOLDER_REL,
            "path_hyperopt_extracts": HYPEROPT_EXTRACT_FOLDER_REL,
            "path_analysis_raw": ANALYSIS_RAW_OUTPUT_FOLDER_REL,
            "path_analysis_extracts": ANALYSIS_EXTRACT_FOLDER_REL,
            "path_data_raw": DATA_RAW_OUTPUT_FOLDER_REL,
            "path_data_audit": DATA_AUDIT_FOLDER_REL,
        }
        for key, value in mapping.items():
            if key in self.vars:
                self.vars[key].set(value)
        self.save_state()

    def clean_settings_json_now(self) -> None:
        """Rewrite the settings file using the compact v2 schema."""
        self.save_state()
        messagebox.showinfo(
            "Settings JSON cleaned",
            "Settings were rewritten without flat duplicate keys and without generated analysis_pairs unless Pair source = MANUAL.",
        )

    # ---------------------------------------------------------------------------------
    # Collect settings
    # ---------------------------------------------------------------------------------
    def collect_backtest(self) -> Dict[str, Any]:
        return {
            "config": self.vars["backtest_config"].get(),
            "window": self.vars["backtest_window"].get(),
            "custom_timerange": self.vars["backtest_custom_timerange"].get(),
            "use_cache": bool(self.vars["backtest_use_cache"].get()),
            "disable_max_market_positions": bool(self.vars["backtest_disable_max_market_positions"].get()),
            "enable_position_stacking": bool(self.vars["backtest_enable_position_stacking"].get()),
        }

    def collect_hyperopt(self) -> Dict[str, Any]:
        return {
            "config": self.vars["hyperopt_config"].get(),
            "window": self.vars["hyperopt_window"].get(),
            "custom_timerange": self.vars["hyperopt_custom_timerange"].get(),
            "spaces": self.vars["hyperopt_spaces"].get(),
            "epochs": self.vars["hyperopt_epochs"].get(),
            "workers": self.vars["hyperopt_workers"].get(),
            "hyperopt_loss": self.vars["hyperopt_loss"].get(),
            "random_state_mode": self.vars["hyperopt_random_state_mode"].get(),
            "random_state": self.vars["hyperopt_random_state"].get(),
        }

    def collect_analysis(self) -> Dict[str, Any]:
        return {
            "analysis_mode": self.vars["analysis_mode"].get(),
            "config": self.vars["analysis_config"].get(),
            "strategy": self.vars["analysis_strategy"].get(),
            "window": self.vars["analysis_window"].get(),
            "custom_timerange": self.vars["analysis_custom_timerange"].get(),
            "minimum_trade_amount": self.vars["analysis_minimum_trade_amount"].get(),
            "targeted_trade_amount": self.vars["analysis_targeted_trade_amount"].get(),
            "pair_source": self.vars["analysis_pair_source"].get(),
            "pairs": self.vars["analysis_pairs"].get(),
            "startup_candles": self.vars["analysis_startup_candles"].get(),
            "recursive_run_mode": self.vars["analysis_recursive_run_mode"].get(),
            "display_mode": self.vars["analysis_display_mode"].get(),
            "max_parallel": self.vars["analysis_max_parallel"].get(),
        }

    def collect_data(self) -> Dict[str, Any]:
        return {
            "data_action": self.vars["data_action"].get(),
            "exchange": self.vars["data_exchange"].get(),
            "data_config": self.vars["data_config"].get(),
            "data_format": self.vars["data_format"].get(),
            "window": self.vars["data_window"].get(),
            "custom_timerange": self.vars["data_custom_timerange"].get(),
            "timeframes": self.vars["data_timeframes"].get(),
            "include_inactive": bool(self.vars["data_include_inactive"].get()),
            "erase": bool(self.vars["data_erase"].get()),
        }

    # ---------------------------------------------------------------------------------
    # Preview / actions
    # ---------------------------------------------------------------------------------
    def refresh_all_previews(self) -> None:
        builders: Dict[str, Callable[[], Tuple[List[str], str]]] = {
            "backtest": lambda: build_backtest_command(self.collect_backtest()),
            "hyperopt": lambda: build_hyperopt_command(self.collect_hyperopt()),
            "analysis": lambda: build_analysis_command(self.collect_analysis()),
            "data": lambda: build_data_command(self.collect_data()),
        }
        for key, builder in builders.items():
            box = self.previews.get(key)
            if not box:
                continue
            try:
                cmd, _container = builder()
                text = command_to_string(cmd)
            except Exception as e:
                text = f"Preview error: {e}"
            box.configure(state="normal")
            box.delete("1.0", "end")
            box.insert("1.0", text)
            box.configure(state="disabled")

    def copy_preview(self, key: str) -> None:
        box = self.previews.get(key)
        if not box:
            return
        text = box.get("1.0", "end").strip()
        self.root.clipboard_clear()
        self.root.clipboard_append(text)

    def validate_timerange(self, timerange: str) -> bool:
        return bool(re.fullmatch(r"\d{8}-\d{8}", timerange.strip()))

    def validate_before_run(self, category: str, settings: Dict[str, Any]) -> bool:
        if category in ["backtest", "hyperopt", "analysis", "data"]:
            tr = timerange_from_vars(settings.get("window", "CUSTOM"), settings.get("custom_timerange", ""))
            if category != "data" or settings.get("data_action") == "download-data":
                if not self.validate_timerange(tr):
                    messagebox.showerror("Invalid timerange", "Timerange must be YYYYMMDD-YYYYMMDD.")
                    return False
        if category == "data" and settings.get("data_action") == "download-data":
            selected_timeframes = split_tokens(settings.get("timeframes", ""))
            invalid_timeframes = [tf for tf in selected_timeframes if tf not in TIMEFRAMES]
            if not selected_timeframes:
                messagebox.showerror("Missing timeframes", "Enter at least one timeframe. Available: " + " ".join(TIMEFRAMES))
                return False
            if invalid_timeframes:
                messagebox.showerror(
                    "Invalid timeframes",
                    "Invalid: " + ", ".join(invalid_timeframes) + "\nAvailable: " + " ".join(TIMEFRAMES),
                )
                return False
        if category == "analysis" and not settings.get("strategy", "").strip():
            messagebox.showerror("Missing strategy", "Choose or type a strategy class name.")
            return False
        return True

    def launch_payload(self, category: str, payload: Dict[str, Any], title: str, pause: bool, display_mode: str = "visible_cmd") -> None:
        ensure_dirs()

        # Child jobs update ONLY the single registry file. No per-job JSON sidecars.
        payload = dict(payload)
        payload["_display_mode"] = display_mode
        payload["project_root"] = PROJECT_ROOT

        job_record = self.make_job_record(category, payload, title, pause, display_mode)
        payload["job_id"] = job_record["id"]
        payload["job_registry_file"] = self.job_registry_path()

        cmd_file = ""
        if os.name == "nt" and display_mode != "silent":
            cmd_file = os.path.join(project_path(UI_JOBS_FOLDER_REL), safe_filename(f"run_{category}_{job_record['id']}.cmd"))
        job_record["cmd_file"] = cmd_file
        job_record["json_file"] = ""

        payload_b64 = encode_payload(payload)

        # Save the registry BEFORE launching so a fast child process can update its row.
        self.jobs.append(job_record)
        self.jobs = self.dedupe_jobs(self.jobs)[-300:]
        self.save_jobs_registry()
        self.refresh_job_listbox()

        if cmd_file:
            pause_line = "pause" if pause else ""
            child_line = frozen_self_batch_line(payload_b64)
            content = (
                "@echo off\r\n"
                f"title Freqtrade {category} - {title}\r\n"
                f"cd /d \"{PROJECT_ROOT}\"\r\n"
                f"{child_line}\r\n"
                "set EXITCODE=%ERRORLEVEL%\r\n"
                "del \"%~f0\" >nul 2>nul\r\n"
                "echo.\r\n"
                f"{pause_line}\r\n"
                "exit /b %EXITCODE%\r\n"
            )
            Path(cmd_file).write_text(content, encoding="utf-8", newline="\r\n")

        try:
            if os.name == "nt":
                if display_mode == "silent":
                    creationflags = (
                        getattr(subprocess, "CREATE_NO_WINDOW", 0)
                        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                        | getattr(subprocess, "DETACHED_PROCESS", 0)
                    )
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    subprocess.Popen(
                        frozen_self_command(payload_b64),
                        cwd=PROJECT_ROOT,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        stdin=subprocess.DEVNULL,
                        creationflags=creationflags,
                        startupinfo=startupinfo,
                        shell=False,
                    )
                else:
                    flag = "/min " if display_mode == "minimized_cmd" else ""
                    start_cmd = f'start "" /D "{PROJECT_ROOT}" {flag}cmd.exe /c call "{cmd_file}"'
                    subprocess.Popen(start_cmd, cwd=PROJECT_ROOT, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                subprocess.Popen(
                    frozen_self_command(payload_b64),
                    cwd=PROJECT_ROOT,
                    start_new_session=True,
                    stdout=subprocess.DEVNULL if display_mode == "silent" else None,
                    stderr=subprocess.DEVNULL if display_mode == "silent" else None,
                    stdin=subprocess.DEVNULL,
                )
        except Exception as e:
            # Launch failed: remove only this not-running row and its temporary CMD.
            self.jobs = [job for job in self.jobs if str(job.get("id", "")) != str(job_record.get("id", ""))]
            if cmd_file and os.path.isfile(cmd_file):
                try:
                    os.remove(cmd_file)
                except Exception:
                    pass
            self.save_jobs_registry()
            self.refresh_job_listbox()
            messagebox.showerror("Launch failed", str(e))
            return

        job_record["status"] = "STARTED"
        for idx, job in enumerate(self.jobs):
            if str(job.get("id", "")) == str(job_record.get("id", "")):
                self.jobs[idx] = job_record
                break
        self.save_jobs_registry()
        self.refresh_job_listbox()
        self.save_state()

    def launch_job(self, category: str, cmd: List[str], metadata: Dict[str, Any], pause: bool, display_mode: str = "visible_cmd") -> None:
        metadata = dict(metadata)
        metadata["container_name"] = metadata.get("container_name") or next((cmd[i + 1] for i, x in enumerate(cmd[:-1]) if x == "--name"), "")
        metadata["command"] = command_to_string(cmd)
        payload = {
            "category": category,
            "cmd": cmd,
            "metadata": metadata,
        }
        self.launch_payload(category, payload, str(metadata.get("title", metadata.get("container_name", "job"))), pause, display_mode)


    def resolve_analysis_pairs(self, settings: Dict[str, Any]) -> List[str]:
        source = str(settings.get("pair_source", "MANUAL")).upper()
        if settings.get("analysis_mode") != "recursive-analysis":
            return split_tokens(settings.get("pairs", ""))
        if source == "RECOMMENDED":
            return RECOMMENDED_RECURSIVE_PAIRS.copy()
        if source == "CONFIG_PAIRLIST_DOWNLOADED":
            timeframe = extract_strategy_timeframe(settings.get("strategy", ""))
            return expand_config_pairlist_to_downloaded_pairs(settings.get("config", ""), timeframe)
        return split_tokens(settings.get("pairs", ""))

    def load_analysis_pairs_from_source(self) -> None:
        settings = self.collect_analysis()
        if settings.get("analysis_mode") != "recursive-analysis":
            messagebox.showinfo("Pair source", "Pair source is used by recursive-analysis only.")
            return
        pairs = self.resolve_analysis_pairs(settings)
        if not pairs:
            messagebox.showerror("No pairs found", "No pairs were found for the selected pair source. Check downloaded data or use MANUAL.")
            return
        self.vars["analysis_pairs"].set(" ".join(pairs))
        if settings.get("pair_source") == "CONFIG_PAIRLIST_DOWNLOADED":
            timeframe = extract_strategy_timeframe(settings.get("strategy", ""))
            source_label = pairlist_source_label(settings.get("config", ""))
            messagebox.showinfo("Pairs loaded", f"Loaded {len(pairs)} downloaded pair(s) using {source_label} with timeframe {timeframe}.")
        else:
            messagebox.showinfo("Pairs loaded", f"Loaded {len(pairs)} pair(s) from {settings.get('pair_source')}.")

    def launch_analysis_batch(self, settings: Dict[str, Any], pairs: List[str]) -> None:
        run_mode = str(settings.get("recursive_run_mode", "single_command"))
        max_parallel = 1 if run_mode == "cmd_per_pair_sequential" else parse_positive_int(settings.get("max_parallel", "5"), 5)
        max_parallel = max(1, min(max_parallel, len(pairs))) if pairs else 1
        timerange = timerange_from_vars(settings["window"], settings["custom_timerange"])
        jobs: List[Dict[str, Any]] = []
        for pair in pairs:
            cmd, container = build_analysis_command(settings, pair_override=pair)
            jobs.append({"pair": pair, "cmd": cmd, "container_name": container})
        metadata = {
            "title": f"Recursive batch {settings['strategy']} {len(pairs)} pair(s)",
            "analysis_mode": settings["analysis_mode"],
            "pair_source": settings.get("pair_source", ""),
            "config": settings["config"],
            "strategy": settings["strategy"],
            "timerange": timerange,
            "max_parallel": max_parallel,
            "output_paths": self.collect_output_paths(),
            "command": f"batch recursive-analysis jobs={len(pairs)} max_parallel={max_parallel}",
        }
        payload = {"category": "analysis_batch", "jobs": jobs, "metadata": metadata}
        self.launch_payload("analysis_batch", payload, metadata["title"], bool(self.vars["analysis_pause"].get()), str(settings.get("display_mode", "minimized_cmd")))

    def run_backtest(self) -> None:
        settings = self.collect_backtest()
        if not self.validate_before_run("backtest", settings):
            return
        cmd, container = build_backtest_command(settings)
        timerange = timerange_from_vars(settings["window"], settings["custom_timerange"])
        metadata = {"title": f"Backtest {settings['config']} {timerange}", "config": settings["config"], "timerange": timerange, "container_name": container, "output_paths": self.collect_output_paths()}
        self.launch_job("backtest", cmd, metadata, bool(self.vars["backtest_pause"].get()))

    def run_hyperopt(self) -> None:
        settings = self.collect_hyperopt()
        if not self.validate_before_run("hyperopt", settings):
            return
        invalid_spaces = [x for x in split_tokens(settings["spaces"]) if x not in VALID_SPACES]
        if invalid_spaces:
            messagebox.showerror("Invalid spaces", "Invalid spaces: " + ", ".join(invalid_spaces))
            return
        if settings.get("random_state_mode") == "CUSTOM" and not str(settings.get("random_state", "")).strip().isdigit():
            messagebox.showerror("Invalid random state", "CUSTOM random state must be zero or a positive integer.")
            return
        cmd, container = build_hyperopt_command(settings)
        timerange = timerange_from_vars(settings["window"], settings["custom_timerange"])
        metadata = {"title": f"Hyperopt {settings['config']} {timerange}", "config": settings["config"], "timerange": timerange, "hyperopt_loss": settings["hyperopt_loss"], "container_name": container, "output_paths": self.collect_output_paths()}
        self.launch_job("hyperopt", cmd, metadata, bool(self.vars["hyperopt_pause"].get()))

    def run_analysis(self) -> None:
        settings = self.collect_analysis()
        if not self.validate_before_run("analysis", settings):
            return

        display_mode = str(settings.get("display_mode", "visible_cmd"))
        timerange = timerange_from_vars(settings["window"], settings["custom_timerange"])

        if settings["analysis_mode"] == "recursive-analysis":
            pairs = self.resolve_analysis_pairs(settings)
            if not pairs:
                messagebox.showerror("Missing pairs", "Recursive-analysis needs pairs. Use Pair source + Load pairs from source, or select MANUAL and type pairs.")
                return
            settings = dict(settings)
            settings["pairs"] = " ".join(pairs)
            self.vars["analysis_pairs"].set(settings["pairs"])
            run_mode = str(settings.get("recursive_run_mode", "single_command"))
            if run_mode in {"cmd_per_pair_parallel", "cmd_per_pair_sequential"}:
                self.launch_analysis_batch(settings, pairs)
                return

        cmd, container = build_analysis_command(settings)
        metadata = {"title": f"{settings['analysis_mode']} {settings['strategy']} {timerange}", "analysis_mode": settings["analysis_mode"], "config": settings["config"], "strategy": settings["strategy"], "timerange": timerange, "container_name": container, "output_paths": self.collect_output_paths()}
        self.launch_job("analysis", cmd, metadata, bool(self.vars["analysis_pause"].get()), display_mode)

    def run_data(self) -> None:
        settings = self.collect_data()
        if not self.validate_before_run("data", settings):
            return
        cmd, container = build_data_command(settings)
        timerange = timerange_from_vars(settings["window"], settings["custom_timerange"])
        metadata = {"title": f"Data {settings['data_action']} {timerange}", "data_action": settings["data_action"], "timerange": timerange, "container_name": container, "output_paths": self.collect_output_paths()}
        self.launch_job("data", cmd, metadata, bool(self.vars["data_pause"].get()))

    def fill_auto_startup(self) -> None:
        strategy = self.vars["analysis_strategy"].get().strip()
        if not strategy:
            messagebox.showwarning("Missing strategy", "Choose a strategy first.")
            return
        auto = auto_startup_candles(strategy)
        self.vars["analysis_startup_candles"].set(auto)
        self._last_analysis_strategy_for_startup = strategy
        self._last_analysis_auto_startup = auto

    def refresh_discovery(self) -> None:
        self.configs = list_config_files()
        self.data_configs = list_data_config_files()
        self.strategies = list_strategy_classes()
        self.custom_losses = list_custom_hyperopt_losses()
        # Rebuild is overkill; just update every combobox we can find.
        def walk(widget: tk.Widget) -> Iterable[tk.Widget]:
            yield widget
            for child in widget.winfo_children():
                yield from walk(child)
        for widget in walk(self.root):
            if isinstance(widget, ttk.Combobox):
                var_name = str(widget.cget("textvariable"))
                # Tk variable names are not the same as our keys, so infer by current contents/default domain.
                current = widget.get()
                if widget is self.field_widgets.get("data_config"):
                    widget.configure(values=self.data_configs)
                elif widget in (self.field_widgets.get("backtest_config"), self.field_widgets.get("hyperopt_config"), self.field_widgets.get("analysis_config")):
                    widget.configure(values=self.configs)
                elif current in HYPEROPT_LOSSES or current in self.custom_losses:
                    widget.configure(values=HYPEROPT_LOSSES + self.custom_losses)
                elif current in self.strategies:
                    widget.configure(values=self.strategies)
        self.refresh_all_previews()

    # ---------------------------------------------------------------------------------
    # Jobs / folders / close
    # ---------------------------------------------------------------------------------
    def job_registry_path(self) -> str:
        return project_path(JOB_REGISTRY_FILE_REL)

    def normalize_job_record(self, item: Any) -> Optional[Dict[str, Any]]:
        """Convert old string jobs and new dict jobs into one compact JSON shape."""
        if isinstance(item, dict):
            record = dict(item)
            record.setdefault("id", safe_filename(f"job_{record.get('started_at', short_stamp())}_{random.randint(1000, 9999)}"))
            record.setdefault("started_at", record.get("created_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            record.setdefault("category", str(record.get("category", "job")).lower())
            record.setdefault("title", record.get("title", record.get("container_name", "job")))
            record.setdefault("status", record.get("last_status", "UNKNOWN"))
            record.setdefault("raw_file", "")
            record.setdefault("extract_file", "")
            record.setdefault("related_file", "")
            record.setdefault("containers", [])
            if record.get("container_name") and record["container_name"] not in record["containers"]:
                record["containers"] = [record["container_name"], *list(record.get("containers", []))]
            return record

        if isinstance(item, str) and item.strip():
            parts = [part.strip() for part in item.split(" | ", 3)]
            started = parts[0] if parts else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            category = parts[1].lower() if len(parts) > 1 else "legacy"
            title = parts[2] if len(parts) > 2 else "legacy job"
            command = parts[3] if len(parts) > 3 else item.strip()
            containers = re.findall(r"--name\s+([^\s]+)", command)
            return {
                "id": safe_filename(f"legacy_{started}_{random.randint(1000, 9999)}"),
                "started_at": started,
                "category": category,
                "title": title,
                "status": "LEGACY_IMPORTED",
                "command": command,
                "container_name": containers[0] if containers else "",
                "containers": containers,
                "cmd_file": "",
                "json_file": "",
                "display_mode": "unknown",
                "legacy": True,
            }
        return None

    def job_identity_keys(self, job: Dict[str, Any]) -> List[str]:
        """Stable identities used to prevent duplicate job rows after reopening.

        v25 imported run_*.cmd files as extra history records. That was useful for
        migration, but it caused duplicates when the same job already existed in
        Freqtrade_AIO_UI_jobs.json. The Docker container name is the strongest
        identity for normal runs, so duplicates are collapsed by container first,
        then by cmd/json file and command.
        """
        keys: List[str] = []

        for container in job.get("containers", []) or []:
            container = str(container).strip()
            if container:
                keys.append(f"container::{container.lower()}")

        container_name = str(job.get("container_name", "")).strip()
        if container_name:
            keys.append(f"container::{container_name.lower()}")

        for file_key in ("cmd_file", "json_file"):
            value = str(job.get(file_key, "")).strip()
            if value:
                try:
                    value = os.path.normcase(os.path.abspath(value))
                except Exception:
                    pass
                keys.append(f"{file_key}::{value.lower()}")

        command = str(job.get("command", "")).strip()
        if command:
            keys.append(f"command::{command.lower()}")

        job_id = str(job.get("id", "")).strip()
        if job_id:
            keys.append(f"id::{job_id.lower()}")

        # Preserve order while removing duplicates.
        out: List[str] = []
        seen = set()
        for key in keys:
            if key not in seen:
                seen.add(key)
                out.append(key)
        return out

    def job_record_priority(self, job: Dict[str, Any]) -> int:
        """Higher priority wins when two records describe the same Docker job."""
        status = str(job.get("status", "")).upper()
        priority = 0
        if not job.get("legacy") and not status.startswith("IMPORTED") and status != "LEGACY_IMPORTED":
            priority += 100
        if job.get("json_file"):
            priority += 20
        if job.get("cmd_file"):
            priority += 10
        if status in {"RUNNING", "EXITED", "FINISHED/REMOVED", "STARTED", "CREATED"}:
            priority += 5
        if job.get("containers") or job.get("container_name"):
            priority += 3
        return priority

    def merge_job_records(self, base: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
        """Merge duplicate records without losing useful file paths or containers."""
        merged = dict(base)

        for key, value in extra.items():
            if key == "containers":
                containers: List[str] = []
                for container in list(merged.get("containers", []) or []) + list(value or []):
                    container = str(container).strip()
                    if container and container not in containers:
                        containers.append(container)
                merged["containers"] = containers
                if not merged.get("container_name") and containers:
                    merged["container_name"] = containers[0]
                continue

            if key in {"legacy"}:
                # Once a real registry record exists, do not let imported CMD status
                # downgrade it back into legacy/imported history.
                merged[key] = bool(merged.get(key, False) and value)
                continue

            if key == "status":
                # Keep the non-import status when possible. Actual docker refresh will
                # update it again immediately after load.
                current = str(merged.get("status", ""))
                incoming = str(value or "")
                if current.startswith("IMPORTED") or current == "LEGACY_IMPORTED" or not current:
                    merged[key] = incoming
                continue

            if (not merged.get(key)) and value not in (None, "", []):
                merged[key] = value

        return merged

    def dedupe_jobs(self, jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Collapse duplicate registry/state/CMD records into one row per job.

        Main rule: one Docker container == one UI row. This fixes the reopen bug
        where a durable registry row and its generated run_*.cmd file both showed
        as separate RUNNING rows.
        """
        out: List[Dict[str, Any]] = []
        key_to_index: Dict[str, int] = {}

        for raw_job in jobs:
            job = self.normalize_job_record(raw_job)
            if not job:
                continue

            keys = self.job_identity_keys(job)
            if not keys:
                keys = [f"fallback::{len(out)}::{random.random()}"]

            existing_indexes = [key_to_index[key] for key in keys if key in key_to_index]
            if existing_indexes:
                idx = existing_indexes[0]
                existing = out[idx]
                if self.job_record_priority(job) > self.job_record_priority(existing):
                    merged = self.merge_job_records(job, existing)
                else:
                    merged = self.merge_job_records(existing, job)
                out[idx] = merged

                # Register every identity from both merged records to the same row.
                for key in self.job_identity_keys(merged):
                    key_to_index[key] = idx
                continue

            idx = len(out)
            out.append(job)
            for key in keys:
                key_to_index[key] = idx

        return out

    def load_jobs_registry(self) -> List[Dict[str, Any]]:
        jobs: List[Dict[str, Any]] = []

        # Single durable registry only. Do not import run_*.cmd files back into
        # history, otherwise cleared jobs reappear after restart.
        try:
            path = self.job_registry_path()
            if os.path.isfile(path):
                data = json.loads(Path(path).read_text(encoding="utf-8", errors="replace"))
                raw_jobs = data.get("jobs", data) if isinstance(data, dict) else data
                if isinstance(raw_jobs, list):
                    for item in raw_jobs:
                        record = self.normalize_job_record(item)
                        if record:
                            record["json_file"] = ""
                            jobs.append(record)
        except Exception:
            pass

        jobs = self.dedupe_jobs(jobs)[-300:]
        try:
            self.cleanup_job_temp_files(jobs)
        except Exception:
            pass
        return jobs

    def job_is_active(self, job: Dict[str, Any], statuses: Optional[Dict[str, str]] = None) -> bool:
        """True for jobs that should survive Clear history and keep their CMD file."""
        statuses = statuses or {}
        status = str(job.get("status", "")).upper().strip()

        containers = [str(x).strip() for x in job.get("containers", []) if str(x).strip()]
        if not containers and job.get("container_name"):
            containers = [str(job.get("container_name")).strip()]

        for container in containers:
            docker_status = statuses.get(container, "")
            if docker_status.lower().startswith(("up", "created")):
                return True

        if status == "RUNNING":
            return True

        if status in {"STARTED", "CREATED"}:
            cmd_file = str(job.get("cmd_file", "")).strip()
            if cmd_file and os.path.isfile(cmd_file):
                return True

            # Grace window for very freshly launched silent jobs where Docker may not
            # have appeared in docker ps yet.
            raw = str(job.get("started_at", "")).strip()[:19]
            try:
                started = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
                return (datetime.now() - started).total_seconds() < 600
            except Exception:
                return False

        return False

    def cleanup_job_temp_files(self, jobs: Optional[List[Dict[str, Any]]] = None) -> None:
        """Remove stale temp job files without touching active run CMDs.

        Persistent job history lives only in Freqtrade_AIO_UI_jobs.json.
        Per-job JSON sidecars are always deleted. run_*.cmd files are temporary
        launchers and are kept only while their job is still active.
        """
        folder = project_path(UI_JOBS_FOLDER_REL)
        if not os.path.isdir(folder):
            return

        jobs = jobs if jobs is not None else self.jobs
        statuses = self.docker_status_map() if hasattr(self, "docker_status_map") else {}
        active_cmds: set[str] = set()

        for job in jobs:
            if self.job_is_active(job, statuses):
                cmd_file = str(job.get("cmd_file", "")).strip()
                if cmd_file:
                    try:
                        active_cmds.add(os.path.normcase(os.path.abspath(cmd_file)))
                    except Exception:
                        active_cmds.add(cmd_file.lower())

        # Sidecar JSON files are obsolete and should not exist anymore.
        for pattern in ("job_*.json", "job_cmd_*.json"):
            for path in glob.glob(os.path.join(folder, pattern)):
                try:
                    # Never delete the single registry file.
                    if os.path.basename(path).lower() == os.path.basename(self.job_registry_path()).lower():
                        continue
                    os.remove(path)
                except Exception:
                    pass

        # Temporary CMDs remain only while actively referenced by a running/pending job.
        for path in glob.glob(os.path.join(folder, "run_*.cmd")):
            try:
                norm = os.path.normcase(os.path.abspath(path))
            except Exception:
                norm = path.lower()

            if norm in active_cmds:
                continue

            # Extra safety for very old/current CMDs not in registry: keep them only
            # if their Docker container is still running/created.
            keep = False
            try:
                text = Path(path).read_text(encoding="utf-8", errors="replace")
                for container in re.findall(r"--name\s+([^\s]+)", text):
                    status = statuses.get(container, "")
                    if status.lower().startswith(("up", "created")):
                        keep = True
                        break
            except Exception:
                keep = False

            if not keep:
                try:
                    os.remove(path)
                except Exception:
                    pass

    def import_legacy_cmd_jobs(self) -> List[Dict[str, Any]]:
        # Disabled on purpose. Old run_*.cmd files are temp launchers, not durable
        # history. Importing them made cleared jobs reappear after restart.
        return []

    def make_job_record(self, category: str, payload: Dict[str, Any], title: str, pause: bool, display_mode: str) -> Dict[str, Any]:
        metadata = payload.get("metadata", {}) if isinstance(payload.get("metadata", {}), dict) else {}
        containers: List[str] = []
        if metadata.get("container_name"):
            containers.append(str(metadata.get("container_name")))
        if isinstance(payload.get("jobs"), list):
            for child in payload.get("jobs", []):
                if isinstance(child, dict) and child.get("container_name"):
                    containers.append(str(child.get("container_name")))
        command = str(metadata.get("command", ""))
        if not command and isinstance(payload.get("cmd"), list):
            command = command_to_string(payload["cmd"])
        job_id = safe_filename(f"{short_stamp()}_{category}_{safe_container_part(title)}_{random.randint(1000, 9999)}")
        return {
            "id": job_id,
            "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "category": category,
            "title": title,
            "status": "CREATED",
            "command": command,
            "container_name": containers[0] if containers else "",
            "containers": sorted(set(containers)),
            "cmd_file": "",
            "json_file": "",
            "display_mode": display_mode,
            "pause": bool(pause),
            "project_root": PROJECT_ROOT,
            "config": metadata.get("config", ""),
            "strategy": metadata.get("strategy", ""),
            "timerange": metadata.get("timerange", ""),
            "hyperopt_loss": metadata.get("hyperopt_loss", ""),
            "analysis_mode": metadata.get("analysis_mode", ""),
            "data_action": metadata.get("data_action", ""),
            "output_paths": metadata.get("output_paths", {}),
        }

    def write_job_record_file(self, record: Dict[str, Any]) -> str:
        # Per-job JSON sidecars are disabled. Return the single registry file.
        record["json_file"] = ""
        self.save_jobs_registry()
        return self.job_registry_path()

    def write_missing_job_json_files(self, jobs: List[Dict[str, Any]]) -> None:
        # No-op. Only Freqtrade_AIO_UI_jobs.json should exist.
        return

    def write_jobs_registry_direct(self) -> None:
        """Write the current in-memory job list without merging old registry rows.

        Used by Clear history. Without this direct write, save_jobs_registry() first
        reads the old registry and re-adds deleted finished jobs, making them come
        back on the next Refresh.
        """
        try:
            os.makedirs(project_path(UI_JOBS_FOLDER_REL), exist_ok=True)
            self.jobs = self.dedupe_jobs(self.jobs)[-300:]

            cleaned_jobs: List[Dict[str, Any]] = []
            for job in self.jobs[-300:]:
                item = dict(job)
                item["json_file"] = ""
                if not self.job_is_active(item):
                    item["cmd_file"] = ""
                cleaned_jobs.append(item)

            self.jobs = cleaned_jobs
            data = {
                "schema_version": 2,
                "project_root": PROJECT_ROOT,
                "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "jobs": self.jobs[-300:],
            }
            Path(self.job_registry_path()).write_text(json.dumps(data, indent=2), encoding="utf-8", newline="\n")
            self.cleanup_job_temp_files(self.jobs)
        except Exception:
            pass

    def save_jobs_registry(self) -> None:
        if getattr(self, "_saving_jobs_registry", False):
            return
        self._saving_jobs_registry = True
        try:
            # Pull child-runner updates from the single registry before writing,
            # so closing the main UI cannot overwrite a finished job with stale
            # STARTED/RUNNING data.
            self.merge_job_json_updates()

            os.makedirs(project_path(UI_JOBS_FOLDER_REL), exist_ok=True)
            self.jobs = self.dedupe_jobs(self.jobs)[-300:]

            cleaned_jobs: List[Dict[str, Any]] = []
            for job in self.jobs[-300:]:
                item = dict(job)
                item["json_file"] = ""
                if not self.job_is_active(item):
                    item["cmd_file"] = ""
                cleaned_jobs.append(item)

            self.jobs = cleaned_jobs
            data = {
                "schema_version": 2,
                "project_root": PROJECT_ROOT,
                "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "jobs": self.jobs[-300:],
            }
            Path(self.job_registry_path()).write_text(json.dumps(data, indent=2), encoding="utf-8", newline="\n")
            self.cleanup_job_temp_files(self.jobs)
        except Exception:
            pass
        finally:
            self._saving_jobs_registry = False

    def compact_jobs_for_state(self) -> List[Dict[str, Any]]:
        compact: List[Dict[str, Any]] = []
        for job in self.jobs[-50:]:
            compact.append({
                "id": job.get("id", ""),
                "started_at": job.get("started_at", ""),
                "category": job.get("category", ""),
                "title": job.get("title", ""),
                "status": job.get("status", ""),
                "container_name": job.get("container_name", ""),
                "containers": job.get("containers", []),
                "cmd_file": job.get("cmd_file", "") if self.job_is_active(job) else "",
                "json_file": "",
            })
        return compact

    def docker_status_map(self) -> Dict[str, str]:
        try:
            result = subprocess.run(
                ["docker", "ps", "-a", "--format", "{{.Names}}\t{{.Status}}"],
                cwd=PROJECT_ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
            )
            statuses: Dict[str, str] = {}
            for line in (result.stdout or "").splitlines():
                if "\t" in line:
                    name, status = line.split("\t", 1)
                    statuses[name.strip()] = status.strip()
            return statuses
        except Exception:
            return {}

    def merge_job_json_updates(self) -> None:
        """Merge child-runner updates from the single registry file."""
        try:
            path = self.job_registry_path()
            if not os.path.isfile(path):
                return

            data = json.loads(Path(path).read_text(encoding="utf-8", errors="replace"))
            raw_jobs = data.get("jobs", []) if isinstance(data, dict) else data
            if not isinstance(raw_jobs, list):
                return

            by_id: Dict[str, Dict[str, Any]] = {
                str(job.get("id", "")): job
                for job in self.jobs
                if isinstance(job, dict) and str(job.get("id", ""))
            }

            changed = False
            for item in raw_jobs:
                if not isinstance(item, dict):
                    continue
                job_id = str(item.get("id", "")).strip()
                if not job_id:
                    continue
                item = dict(item)
                item["json_file"] = ""
                if job_id in by_id:
                    by_id[job_id].update({k: v for k, v in item.items() if v not in (None, "")})
                    by_id[job_id]["json_file"] = ""
                    changed = True
                else:
                    self.jobs.append(item)
                    changed = True

            if changed:
                self.jobs = self.dedupe_jobs(self.jobs)[-300:]
        except Exception:
            pass

    def refresh_job_statuses(self) -> None:
        self.merge_job_json_updates()
        statuses = self.docker_status_map()
        changed = False
        terminal_statuses = {"DONE", "FAILED", "CANCELLED", "ERROR", "FINISHED/REMOVED"}

        for job in self.jobs:
            containers = [str(x) for x in job.get("containers", []) if str(x).strip()]
            if not containers and job.get("container_name"):
                containers = [str(job.get("container_name"))]
                job["containers"] = containers

            found = [(name, statuses.get(name, "")) for name in containers]
            running = [item for item in found if item[1].lower().startswith("up")]
            exited = [item for item in found if item[1].lower().startswith("exited")]
            created = [item for item in found if item[1].lower().startswith("created")]
            old_status = str(job.get("status", ""))

            if running:
                job["status"] = "RUNNING"
                job["docker_status"] = "; ".join(f"{n}: {s}" for n, s in running[:3])
            elif exited:
                job["status"] = "EXITED"
                job["docker_status"] = "; ".join(f"{n}: {s}" for n, s in exited[:3])
            elif created:
                job["status"] = "CREATED"
                job["docker_status"] = "; ".join(f"{n}: {s}" for n, s in created[:3])
            elif old_status.upper() in terminal_statuses or job.get("finished_at") or job.get("returncode") not in (None, ""):
                # Child runner already wrote final status to the registry.
                job["status"] = old_status or ("DONE" if str(job.get("returncode", "")) == "0" else "FAILED")
                job["docker_status"] = job.get("docker_status", "finished")
                job["cmd_file"] = ""
                job["json_file"] = ""
            elif containers:
                # Most normal runs use --rm, so finished containers disappear.
                job["status"] = "FINISHED/REMOVED"
                job["docker_status"] = "container not present; likely finished or removed"
                job["cmd_file"] = ""
                job["json_file"] = ""
            else:
                job["status"] = job.get("status") or "HISTORY"
                job["json_file"] = ""

            if old_status != str(job.get("status", "")):
                changed = True

        self.cleanup_job_temp_files(self.jobs)
        if changed:
            self.save_jobs_registry()

    def format_job_for_list(self, job: Dict[str, Any]) -> str:
        status = str(job.get("status", "UNKNOWN"))
        started = str(job.get("started_at", ""))[:19]
        category = str(job.get("category", "job")).upper()
        title = str(job.get("title", job.get("container_name", "job")))
        container = str(job.get("container_name", ""))
        suffix = f" | {container}" if container else ""
        return f"[{status:<16}] {started} | {category:<14} | {title}{suffix}"

    def job_has_explicit_result_file(self, job: Dict[str, Any]) -> bool:
        """True only when this exact job record has a concrete result/log path.

        This intentionally does not scan folders for "latest" files. Folder scans
        caused wrong-result opens when another run was still active.
        """
        for key in ("related_file", "extract_file", "raw_file"):
            path = str(job.get(key, "")).strip()
            if path and os.path.isfile(path):
                return True
        return False

    def job_raw_file_path(self, job: Dict[str, Any]) -> str:
        path = str(job.get("raw_file", "")).strip()
        return path if path and os.path.isfile(path) else ""

    def job_result_path(self, job: Dict[str, Any]) -> str:
        for key in ("related_file", "extract_file", "raw_file"):
            path = str(job.get(key, "")).strip()
            if path and os.path.isfile(path):
                return path
        return ""

    def job_visual_colors(self, job: Dict[str, Any]) -> Tuple[str, str]:
        """Return foreground/background colors for one Jobs-list row.

        Failure states override category colors. Active/created states get their
        own warning/running colors. Finished neutral rows fall back to category
        color so Hyperopt/Backtest/Data/Analysis are easy to scan.
        """
        status = str(job.get("status", "UNKNOWN")).upper().strip()
        category = str(job.get("category", "job")).lower().strip()

        category_fg = {
            "hyperopt": "#d2a8ff",        # purple
            "backtest": "#56d364",        # green
            "analysis": "#79c0ff",        # blue
            "analysis_batch": "#a5d6ff",  # light blue
            "data": "#ffa657",            # orange
        }.get(category, DARK_TEXT)

        # Hard failures should always stand out, regardless of category.
        if any(token in status for token in ("FAILED", "ERROR", "CRITICAL", "CANCELLED")):
            return "#ff7b72", "#2d1117"

        if status in {"RUNNING"}:
            return "#79c0ff", "#0d2233"

        if status in {"CREATED", "STARTED"}:
            return "#f2cc60", "#2b2111"

        if status in {"EXITED"}:
            return "#ffa657", "#2b1d0e"

        if status in {"DONE", "OK", "SUCCESS"}:
            # Keep category identity visible, but use a success-tinted background.
            return category_fg if category_fg != DARK_TEXT else "#3fb950", "#0f2617"

        if status in {"FINISHED/REMOVED", "HISTORY", "LEGACY_IMPORTED", "UNKNOWN"}:
            return category_fg if category_fg != DARK_TEXT else "#8b949e", DARK_FIELD

        return category_fg, DARK_FIELD

    def update_job_action_buttons(self) -> None:
        """Enable/disable selected-job buttons based on real job state."""
        if not hasattr(self, "job_listbox"):
            return

        job = self.selected_job_record(show_message=False)

        def set_state(name: str, enabled: bool) -> None:
            widget = getattr(self, name, None)
            if widget is not None:
                try:
                    widget.configure(state="normal" if enabled else "disabled")
                except Exception:
                    pass

        if not job:
            set_state("jobs_follow_logs_button", False)
            set_state("jobs_open_result_button", False)
            set_state("jobs_delete_selected_button", False)
            return

        statuses = self.docker_status_map()
        active = self.job_is_active(job, statuses)
        has_container = bool(job.get("container_name") or job.get("containers"))

        set_state("jobs_follow_logs_button", has_container)
        set_state("jobs_open_result_button", (not active) and self.job_has_explicit_result_file(job))
        set_state("jobs_delete_selected_button", not active)

    def refresh_job_listbox(self) -> None:
        # Always keep the visible registry deduped; no manual cleanup button needed.
        self.jobs = self.dedupe_jobs(self.jobs)[-300:]
        if not hasattr(self, "job_listbox"):
            return
        old_selection_id = ""
        try:
            selection = self.job_listbox.curselection()
            if selection and int(selection[0]) < len(self._job_list_index_map):
                old_selection_id = str(self.jobs[self._job_list_index_map[int(selection[0])]].get("id", ""))
        except Exception:
            old_selection_id = ""

        self.job_listbox.delete(0, "end")
        self._job_list_index_map = []
        restore_index = None
        for list_row, idx in enumerate(range(len(self.jobs) - 1, -1, -1)):
            self._job_list_index_map.append(idx)
            row_text = self.format_job_for_list(self.jobs[idx])
            self.job_listbox.insert("end", row_text)
            fg, bg = self.job_visual_colors(self.jobs[idx])
            try:
                self.job_listbox.itemconfig(list_row, foreground=fg, background=bg)
            except Exception:
                pass
            if old_selection_id and str(self.jobs[idx].get("id", "")) == old_selection_id:
                restore_index = list_row

        if restore_index is not None:
            try:
                self.job_listbox.selection_set(restore_index)
                self.job_listbox.activate(restore_index)
                self.job_listbox.see(restore_index)
            except Exception:
                pass
        self.update_job_action_buttons()

    def select_job_by_listbox_index(self, list_index: int) -> Optional[Dict[str, Any]]:
        if not hasattr(self, "job_listbox"):
            return None
        if list_index < 0 or list_index >= len(self._job_list_index_map):
            return None
        try:
            self.job_listbox.selection_clear(0, "end")
            self.job_listbox.selection_set(list_index)
            self.job_listbox.activate(list_index)
            self.job_listbox.focus_set()
        except Exception:
            pass
        self.update_job_action_buttons()
        return self.selected_job_record(show_message=False)

    def show_job_context_menu(self, event: Any) -> str:
        """Right-click menu that selects the clicked row first."""
        if not hasattr(self, "job_listbox"):
            return "break"

        try:
            list_index = self.job_listbox.nearest(event.y)
            bbox = self.job_listbox.bbox(list_index)
            if bbox is None:
                return "break"
            # Ignore right-clicks clearly outside the visible row rectangle.
            if event.y < bbox[1] or event.y > (bbox[1] + bbox[3]):
                return "break"
        except Exception:
            return "break"

        job = self.select_job_by_listbox_index(int(list_index))
        if not job:
            return "break"

        try:
            self.refresh_job_statuses()
        except Exception:
            pass

        job = self.selected_job_record(show_message=False) or job
        active = self.job_is_active(job, self.docker_status_map())
        has_container = bool(job.get("container_name") or job.get("containers"))
        has_result = (not active) and self.job_has_explicit_result_file(job)
        has_raw = bool(self.job_raw_file_path(job))

        menu = self.job_context_menu
        menu.delete(0, "end")
        menu.add_command(
            label="Follow logs",
            command=self.follow_selected_job_logs,
            state="normal" if has_container else "disabled",
        )
        menu.add_command(
            label="Open result",
            command=self.open_selected_job_related_file,
            state="normal" if has_result else "disabled",
        )
        menu.add_command(
            label="Open raw log",
            command=self.open_selected_job_raw_log,
            state="normal" if has_raw else "disabled",
        )
        menu.add_separator()
        menu.add_command(
            label="Delete selected history",
            command=self.delete_selected_job_history,
            state="normal" if not active else "disabled",
        )
        menu.add_separator()
        menu.add_command(label="Refresh job status", command=self.refresh_jobs_now)
        menu.add_command(label="Open jobs folder", command=lambda: self.open_folder(project_path(UI_JOBS_FOLDER_REL)))

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            try:
                menu.grab_release()
            except Exception:
                pass
        return "break"

    def clean_duplicate_jobs_now(self) -> None:
        before = len(self.jobs)
        self.jobs = self.dedupe_jobs(self.jobs)[-300:]
        self.refresh_job_statuses()
        self.refresh_job_listbox()
        self.save_jobs_registry()
        self.save_state()
        removed = before - len(self.jobs)
        messagebox.showinfo("Duplicate cleanup", f"Cleaned job history. Removed {removed} duplicate row(s).")

    def refresh_jobs_now(self) -> None:
        self.merge_job_json_updates()
        self.jobs = self.dedupe_jobs(self.jobs)[-300:]
        self.refresh_job_statuses()
        self.refresh_job_listbox()
        self.save_jobs_registry()
        self.save_state()

    def open_file_path(self, path: str, title: str = "Open file") -> None:
        path = str(path or "").strip()
        if not path or not os.path.isfile(path):
            messagebox.showwarning(title, f"File not found:\n{path}")
            return
        try:
            if os.name == "nt":
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as e:
            messagebox.showerror(f"{title} failed", str(e))

    def _parse_job_started_datetime(self, job: Dict[str, Any]) -> Optional[datetime]:
        raw = str(job.get("started_at", "")).strip()[:19]
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y%m%d_%H%M%S"):
            try:
                return datetime.strptime(raw, fmt)
            except Exception:
                pass
        return None

    def latest_file_in_folder(self, folder: str, patterns: List[str], after: Optional[datetime] = None) -> str:
        folder = resolve_project_or_abs(folder)
        candidates: List[str] = []
        for pattern in patterns:
            candidates.extend(glob.glob(os.path.join(folder, pattern)))
        files = [path for path in candidates if os.path.isfile(path)]
        if after is not None:
            after_ts = after.timestamp() - 120
            newer = [path for path in files if os.path.getmtime(path) >= after_ts]
            if newer:
                files = newer
        if not files:
            return ""
        return max(files, key=lambda path: os.path.getmtime(path))

    def latest_related_file_from_jobs(self, category_prefixes: Tuple[str, ...]) -> str:
        """Return the newest exact result path from finished jobs of a category."""
        try:
            self.refresh_job_statuses()
        except Exception:
            pass

        statuses = self.docker_status_map()
        for job in reversed(self.jobs):
            category = str(job.get("category", "")).lower()
            if not any(category.startswith(prefix) for prefix in category_prefixes):
                continue
            if self.job_is_active(job, statuses):
                continue
            path = self.related_file_for_job(job)
            if path:
                return path
        return ""

    def open_latest_backtest_report(self) -> None:
        path = self.latest_related_file_from_jobs(("backtest",))
        if path:
            self.open_file_path(path, "Open backtest report")
            return

        folder = self.collect_output_paths().get("backtest_reports", BACKTEST_REPORTS_FOLDER_REL)
        path = self.latest_file_in_folder(folder, ["*__BACKTESTING_REPORT.ini", "*.ini"])
        if not path:
            messagebox.showwarning("No backtest report", f"No report found in:\n{resolve_project_or_abs(folder)}")
            return
        self.open_file_path(path, "Open backtest report")

    def open_latest_hyperopt_extract(self) -> None:
        path = self.latest_related_file_from_jobs(("hyperopt",))
        if path:
            self.open_file_path(path, "Open hyperopt extract")
            return

        folder = self.collect_output_paths().get("hyperopt_extracts", HYPEROPT_EXTRACT_FOLDER_REL)
        loss = str(self.vars.get("hyperopt_loss", tk.StringVar(value="")).get() or "").strip()
        patterns = [f"*{safe_filename(loss)}*.txt", "*.txt"] if loss else ["*.txt"]
        path = self.latest_file_in_folder(folder, patterns)
        if not path:
            messagebox.showwarning("No hyperopt extract", f"No extract found in:\n{resolve_project_or_abs(folder)}")
            return
        self.open_file_path(path, "Open hyperopt extract")

    def open_latest_analysis_extract(self) -> None:
        path = self.latest_related_file_from_jobs(("analysis", "analysis_batch"))
        if path:
            self.open_file_path(path, "Open analysis extract")
            return

        folder = self.collect_output_paths().get("analysis_extracts", ANALYSIS_EXTRACT_FOLDER_REL)
        path = self.latest_file_in_folder(folder, ["*.txt"])
        if not path:
            messagebox.showwarning("No analysis extract", f"No extract found in:\n{resolve_project_or_abs(folder)}")
            return
        self.open_file_path(path, "Open analysis extract")

    def open_latest_data_audit(self) -> None:
        path = self.latest_related_file_from_jobs(("data",))
        if path:
            self.open_file_path(path, "Open data audit file")
            return

        folder = self.collect_output_paths().get("data_audit", DATA_AUDIT_FOLDER_REL)
        path = self.latest_file_in_folder(folder, ["*.csv", "*.txt", "*.json"])
        if not path:
            messagebox.showwarning("No data audit file", f"No audit/list file found in:\n{resolve_project_or_abs(folder)}")
            return
        self.open_file_path(path, "Open data audit file")

    def related_file_for_job(self, job: Dict[str, Any]) -> str:
        """Return only the exact file recorded for this job.

        Do not guess from "latest file" in output folders. Guessing was opening
        unrelated files when a selected job was still running or when a filename
        happened to contain the same seed/loss text.
        """
        for key in ("related_file", "extract_file", "raw_file"):
            path = str(job.get(key, "")).strip()
            if path and os.path.isfile(path):
                return path
        return ""

    def open_selected_job_related_file(self) -> None:
        job = self.selected_job_record()
        if not job:
            return

        self.refresh_job_statuses()
        if self.job_is_active(job, self.docker_status_map()):
            messagebox.showinfo(
                "Job still running",
                "This job is still running. Open result is disabled until the job finishes and writes its exact result path.",
            )
            self.refresh_job_listbox()
            return

        path = self.related_file_for_job(job)
        if not path:
            messagebox.showwarning(
                "No related result file",
                "No exact result/extract/audit/raw file is recorded for this selected job yet.\n\n"
                "Refresh job status after the job finishes. I will not open a guessed/latest file because that can point to the wrong run.",
            )
            return
        self.open_file_path(path, "Open selected result")

    def open_selected_job_raw_log(self) -> None:
        job = self.selected_job_record()
        if not job:
            return
        path = self.job_raw_file_path(job)
        if not path:
            messagebox.showwarning("No raw log", "This selected job has no recorded raw log file yet.")
            return
        self.open_file_path(path, "Open raw log")

    def selected_job_record(self, show_message: bool = True) -> Optional[Dict[str, Any]]:
        if not hasattr(self, "job_listbox"):
            return None
        selection = self.job_listbox.curselection()
        if not selection:
            if show_message:
                messagebox.showinfo("No job selected", "Select a job first, or right-click a row.")
            return None
        list_index = int(selection[0])
        if list_index >= len(self._job_list_index_map):
            return None
        job_index = self._job_list_index_map[list_index]
        if job_index < 0 or job_index >= len(self.jobs):
            return None
        return self.jobs[job_index]

    def follow_selected_job_logs(self) -> None:
        job = self.selected_job_record()
        if not job:
            return
        self.refresh_job_statuses()
        containers = [str(x) for x in job.get("containers", []) if str(x).strip()]
        if not containers and job.get("container_name"):
            containers = [str(job.get("container_name"))]
        if not containers:
            messagebox.showwarning("No container", "This job has no Docker container recorded. Refresh status or open the raw logs folder instead.")
            return
        container = containers[0]
        if os.name == "nt":
            cmd = f'start "" /D "{PROJECT_ROOT}" cmd.exe /k docker logs -f {quote_cmd_arg(container)}'
            subprocess.Popen(cmd, cwd=PROJECT_ROOT, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.Popen(["docker", "logs", "-f", container], cwd=PROJECT_ROOT)

    def delete_selected_job_history(self) -> None:
        """Delete only the selected non-active job-history row."""
        job = self.selected_job_record()
        if not job:
            return

        self.refresh_job_statuses()
        statuses = self.docker_status_map()
        if self.job_is_active(job, statuses):
            messagebox.showinfo(
                "Job still active",
                "This job is still running/starting, so it will not be removed from history yet.",
            )
            self.refresh_job_listbox()
            return

        title = str(job.get("title", job.get("container_name", "selected job")))
        confirm = messagebox.askyesno(
            "Delete selected history",
            f"Delete this finished/history job row?\n\n{title}\n\nResult/log files are not deleted.",
        )
        if not confirm:
            return

        job_id = str(job.get("id", "")).strip()
        container_name = str(job.get("container_name", "")).strip()
        cmd_file = str(job.get("cmd_file", "")).strip()

        def same_job(candidate: Dict[str, Any]) -> bool:
            if job_id and str(candidate.get("id", "")).strip() == job_id:
                return True
            if container_name and str(candidate.get("container_name", "")).strip() == container_name:
                return True
            return False

        self.jobs = [candidate for candidate in self.jobs if not same_job(candidate)]

        if cmd_file and os.path.isfile(cmd_file):
            try:
                os.remove(cmd_file)
            except Exception:
                pass

        self.cleanup_job_temp_files(self.jobs)
        self.refresh_job_listbox()
        self.write_jobs_registry_direct()
        self.save_state()

    def open_selected_job_json(self) -> None:
        # Kept only for backward compatibility if called by old shortcuts.
        path = self.job_registry_path()
        self.save_jobs_registry()
        self.open_file_path(path, "Open job registry")

    def open_selected_job_cmd(self) -> None:
        # Kept only for backward compatibility if called by old shortcuts.
        job = self.selected_job_record()
        if not job:
            return
        path = str(job.get("cmd_file", ""))
        if not path or not os.path.isfile(path):
            messagebox.showwarning("CMD not found", "This job does not have an active temporary CMD file.")
            return
        self.open_file_path(path, "Open selected CMD")

    def schedule_job_status_refresh(self) -> None:
        try:
            self.root.after(12000, self.periodic_job_status_refresh)
        except Exception:
            pass

    def periodic_job_status_refresh(self) -> None:
        try:
            if hasattr(self, "notebook") and hasattr(self, "job_listbox"):
                current_tab = self.notebook.tab(self.notebook.select(), "text")
                if current_tab == "Jobs":
                    self.refresh_job_statuses()
                    self.refresh_job_listbox()
                    self.save_jobs_registry()
        except Exception:
            pass
        self.schedule_job_status_refresh()

    def clear_jobs(self) -> None:
        """Clear finished/history rows only.

        Running/just-started jobs stay in the registry and their temporary CMD
        launchers are kept until the job finishes. Stale sidecar JSON and stale
        finished CMD files are deleted.
        """
        self.refresh_job_statuses()
        statuses = self.docker_status_map()

        kept: List[Dict[str, Any]] = []
        for job in self.jobs:
            if self.job_is_active(job, statuses):
                kept.append(job)

        self.jobs = self.dedupe_jobs(kept)[-300:]
        self.cleanup_job_temp_files(self.jobs)
        self.refresh_job_listbox()
        self.write_jobs_registry_direct()
        self.save_state()

    def open_folder(self, path: str) -> None:
        os.makedirs(path, exist_ok=True)
        try:
            if os.name == "nt":
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as e:
            messagebox.showerror("Open folder failed", str(e))

    def change_project_folder(self) -> None:
        selected = filedialog.askdirectory(
            initialdir=PROJECT_ROOT if os.path.isdir(PROJECT_ROOT) else app_base_dir(),
            title="Select Freqtrade project root folder",
        )
        if not selected:
            return
        selected = os.path.abspath(selected)
        if not looks_like_freqtrade_root(selected):
            use_anyway = messagebox.askyesno(
                "Folder does not look like Freqtrade root",
                "That folder does not contain user_data or a compose file.\n\n"
                "Use it anyway?",
            )
            if not use_anyway:
                return

        # Save current state to the old project before switching, then switch.
        self.save_state()
        set_project_root(selected, persist=True)
        self.state_path = project_path(STATE_FILE_REL)
        ensure_dirs()

        # Reload discovery from the new root and point comboboxes at the new files.
        self.configs = list_config_files()
        self.data_configs = list_data_config_files()
        self.strategies = list_strategy_classes()
        self.custom_losses = list_custom_hyperopt_losses()

        self.project_root_label_var.set(f"Project: {PROJECT_ROOT}")

        for key in ("backtest_config", "hyperopt_config", "analysis_config"):
            widget = self.field_widgets.get(key)
            if isinstance(widget, ttk.Combobox):
                widget.configure(values=self.configs)
            if self.configs and str(self.vars.get(key, tk.StringVar()).get() or "") not in self.configs:
                self.vars[key].set(self.configs[0])

        widget = self.field_widgets.get("data_config")
        if isinstance(widget, ttk.Combobox):
            widget.configure(values=self.data_configs)
        if self.data_configs and str(self.vars.get("data_config", tk.StringVar()).get() or "") not in self.data_configs:
            self.vars["data_config"].set(self.data_configs[0])

        widget = self.field_widgets.get("analysis_strategy")
        if isinstance(widget, ttk.Combobox):
            widget.configure(values=self.strategies)
        if self.strategies and not str(self.vars.get("analysis_strategy", tk.StringVar()).get() or "").strip():
            self.vars["analysis_strategy"].set(self.strategies[0])

        widget = self.field_widgets.get("hyperopt_loss")
        if isinstance(widget, ttk.Combobox):
            widget.configure(values=HYPEROPT_LOSSES + self.custom_losses)

        self.save_state()
        self.sync_locked_fields()
        self.refresh_all_previews()
        messagebox.showinfo("Project folder changed", f"Using project root:\n{PROJECT_ROOT}")

    def on_close(self) -> None:
        # Deliberately only close the control UI. Launched CMD/Docker jobs are
        # detached and tracked through the jobs registry, so they keep running.
        self.save_jobs_registry()
        self.save_state()
        self.root.destroy()


# =====================================================================================
# PyInstaller / frozen executable helpers
# =====================================================================================
def frozen_self_command(payload_b64: str) -> List[str]:
    """
    Return the correct command to relaunch this tool in child-job mode.

    Normal .py run:
        python Freqtrade_AIO_UI.py --run-job <payload>

    PyInstaller .exe run:
        Freqtrade_AIO_UI.exe --run-job <payload>

    This is critical because a frozen .exe cannot execute a separate .py script by
    calling sys.executable script.py. In a frozen app, sys.executable is the .exe.
    """
    if getattr(sys, "frozen", False):
        return [sys.executable, "--run-job", payload_b64]
    return [sys.executable, os.path.abspath(__file__), "--run-job", payload_b64]


def frozen_self_batch_line(payload_b64: str) -> str:
    cmd = frozen_self_command(payload_b64)
    return " ".join(quote_cmd_arg(x) for x in cmd)


def attach_console_for_child_job(display_mode: str = "visible_cmd") -> None:
    """Attach a --run-job child to the parent CMD console when built as --windowed.

    A --windowed PyInstaller exe has no console by default, which is exactly what
    we want for the main GUI. Child jobs are different: visible/minimized modes
    are launched through a CMD file, so this child process attaches to that CMD
    console and rebinds stdout/stderr to CONOUT$ so colored logs print normally.
    Silent mode intentionally does not attach or allocate any console.
    """
    if os.name != "nt":
        return
    if str(display_mode or "").lower() == "silent":
        return

    try:
        kernel32 = ctypes.windll.kernel32
        ATTACH_PARENT_PROCESS = ctypes.c_uint32(-1).value

        attached = bool(kernel32.AttachConsole(ATTACH_PARENT_PROCESS))
        if not attached:
            # If someone runs --run-job directly without the generated CMD parent,
            # give it a console instead of failing silently.
            kernel32.AllocConsole()

        # Rebind std streams. In --windowed builds sys.stdout/sys.stderr are often
        # None, so print()/tracebacks vanish unless these are restored.
        sys.stdout = open("CONOUT$", "w", encoding="utf-8", errors="replace", buffering=1)
        sys.stderr = open("CONOUT$", "w", encoding="utf-8", errors="replace", buffering=1)
        try:
            sys.stdin = open("CONIN$", "r", encoding="utf-8", errors="replace")
        except Exception:
            pass

        ensure_windows_ansi()
    except Exception:
        pass


def hide_console_for_frozen_main_ui() -> None:
    """Hide console for legacy console-built exe main GUI only.

    Current build uses --windowed, so this usually does nothing. It remains as a
    safety net if someone builds without --windowed.
    """
    if os.name != "nt":
        return
    if "--run-job" in sys.argv:
        return
    if not getattr(sys, "frozen", False):
        return
    try:
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)
    except Exception:
        pass

# =====================================================================================
# Entrypoint
# =====================================================================================
def ensure_project_root_for_gui(root: tk.Tk) -> bool:
    """Ask for the Freqtrade folder if the remembered/default root is unusable."""
    if looks_like_freqtrade_root(PROJECT_ROOT):
        # Persist auto-detected valid roots too, so the exe becomes portable after
        # first launch on a different PC.
        write_project_root_to_state(PROJECT_ROOT)
        return True

    root.withdraw()
    messagebox.showwarning(
        "Select Freqtrade project root",
        "The saved/default project root was not found or does not look like a Freqtrade folder.\n\n"
        "Select the folder that contains your user_data and docker-compose/compose file.",
    )

    while True:
        selected = filedialog.askdirectory(
            initialdir=app_base_dir(),
            title="Select Freqtrade project root folder",
        )
        if not selected:
            root.destroy()
            return False
        selected = os.path.abspath(selected)
        if looks_like_freqtrade_root(selected):
            set_project_root(selected, persist=True)
            root.deiconify()
            return True
        use_anyway = messagebox.askyesno(
            "Folder does not look like Freqtrade root",
            "That folder does not contain user_data or a compose file.\n\nUse it anyway?",
        )
        if use_anyway:
            set_project_root(selected, persist=True)
            root.deiconify()
            return True


def main() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == "--run-job":
        payload = decode_payload(sys.argv[2])
        payload_root = str(payload.get("project_root", "")).strip()
        if payload_root:
            set_project_root(payload_root, persist=False)
        attach_console_for_child_job(str(payload.get("_display_mode", "visible_cmd")))
        if payload.get("category") == "analysis_batch":
            return run_analysis_batch_job(payload)
        return run_child_job(payload)

    hide_console_for_frozen_main_ui()
    root = tk.Tk()
    if not ensure_project_root_for_gui(root):
        return 1
    app = FreqtradeAllInOneUI(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
