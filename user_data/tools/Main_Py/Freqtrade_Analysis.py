#!/usr/bin/env python
import os
import re
import glob
import json
import ctypes
import base64
import zlib
import subprocess
import sys
import time
from datetime import datetime
from typing import Any

# =====================================================================================
# Colors
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

# =====================================================================================
# Project constants
# =====================================================================================
PROJECT_ROOT = r"N:\Freqtrade"
DOCKER_COMPOSE = "docker-compose"
DOCKER_SERVICE = "freqtrade"
CONFIG_FOLDER = "user_data"
STRATEGY_FOLDER = os.path.join(PROJECT_ROOT, "user_data", "strategies")
RAW_OUTPUT_FOLDER = os.path.join(PROJECT_ROOT, "user_data", "logs", "analysis_raw_output")
EXTRACT_FOLDER = os.path.join(PROJECT_ROOT, "user_data", "analysis_extracts")
JOBS_FOLDER = os.path.join(PROJECT_ROOT, "user_data", "logs", "analysis_jobs")
EXTRACT_FOLDER_REL = "user_data/analysis_extracts"

TIME_WINDOWS = {
    "1": ("FULL", "20240101-20251201"),
    "2": ("TRAIN", "20240101-20240701"),
    "3": ("VALID", "20240701-20241001"),
    "4": ("TEST", "20241001-20251201"),
    "5": ("LIVE_CHECK", "20251001-20260410"),
}

CONTAINER_NAMES = {
    "lookahead-analysis": "Freqtrade_Lookahead_Analysis",
    "recursive-analysis": "Freqtrade_Recursive_Analysis",
}

RECOMMENDED_RECURSIVE_PAIRS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT"]
FALLBACK_STARTUP_CANDLES = [199, 399, 499, 999, 1999]

# Watchdog settings for detached CMD/silent jobs.
# These prevent the final report staying IN PROGRESS forever if a child CMD closes
# before writing its final status file, or if Docker removes the --rm container first.
JOB_LAUNCH_GRACE_SECONDS = 60
JOB_MISSING_CONTAINER_GRACE_SECONDS = 120
JOB_MAX_RUNTIME_SECONDS = 60 * 60


# =====================================================================================
# Console helpers
# =====================================================================================
def enable_windows_ansi():
    if os.name != "nt":
        return
    try:
        kernel32 = ctypes.windll.kernel32
        for std_handle in (-11, -12):
            handle = kernel32.GetStdHandle(std_handle)
            if handle == 0 or handle == -1:
                continue
            mode = ctypes.c_uint32()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        pass


def write_error_line(msg: str):
    print(f"{RED}{msg}{RESET}")


def write_info_line(msg: str):
    print(f"{WHITE}{msg}{RESET}")


def write_warning_line(msg: str):
    print(f"{YELLOW}{msg}{RESET}")


def write_action_line(msg: str):
    print(f"{GREEN}{msg}{RESET}")


def write_tell(msg: str):
    print(f"{BLUE}{msg}{RESET}")


def stamp_now() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


# =====================================================================================
# Generic helpers
# =====================================================================================
def ensure_working_directory():
    if os.getcwd().lower() != PROJECT_ROOT.lower():
        write_warning_line(f"Switching to expected working directory: {PROJECT_ROOT}")
        try:
            os.chdir(PROJECT_ROOT)
        except Exception as e:
            write_error_line(f"Failed to change directory to {PROJECT_ROOT}. {e}")
            sys.exit(1)


def ensure_analysis_directories():
    os.makedirs(RAW_OUTPUT_FOLDER, exist_ok=True)
    os.makedirs(EXTRACT_FOLDER, exist_ok=True)
    os.makedirs(JOBS_FOLDER, exist_ok=True)


def strip_ansi(value: str) -> str:
    value = ANSI_RE.sub("", value or "")
    value = value.replace("\x00", "")
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    return value


def safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_")
    return cleaned or "unknown"


def rel_to_project(path: str) -> str:
    return os.path.relpath(path, PROJECT_ROOT).replace(os.sep, "/")


def project_path_from_rel(path: str) -> str:
    return os.path.join(PROJECT_ROOT, path.replace("/", os.sep))


def command_to_string(cmd: list[str]) -> str:
    return " ".join(cmd)


def get_container_name(mode: str) -> str:
    return CONTAINER_NAMES.get(mode, "Freqtrade_Analysis")


def get_analysis_file_prefix(mode: str) -> str:
    if mode in {"lookahead-analysis", "lookahead"}:
        return "Lookahead-Analysis"
    if mode in {"recursive-analysis", "recursive"}:
        return "Recursive-Analysis"
    return "Analysis"


def remove_old_container(container_name: str):
    subprocess.run(
        ["docker", "rm", "-f", container_name],
        cwd=PROJECT_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def dedupe_preserve_order(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def split_tokens(value: str) -> list[str]:
    return [x.strip() for x in re.split(r"[,\s]+", value.strip()) if x.strip()]


def read_text_file(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return ""


def write_json_atomic(path: str, data: dict[str, Any]):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def read_json_file(path: str) -> dict[str, Any] | None:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return json.load(f)
    except Exception:
        return None


def get_positive_int_default(prompt: str, default: int) -> int:
    while True:
        write_action_line(f"{prompt} [default: {default}]")
        value = input("> ").strip()
        if not value:
            return default
        if value.isdigit() and int(value) > 0:
            return int(value)
        write_error_line("Invalid input. Enter a positive integer.")


def get_parallel_workers(pair_count: int) -> int:
    if pair_count <= 1:
        return 1
    default = min(pair_count, 5)
    while True:
        write_action_line(f"Max parallel recursive CMD windows [default: {default}]")
        if pair_count > 12:
            write_warning_line(f"You selected {pair_count} pairs. Too many parallel containers can hammer CPU/RAM/Docker.")
        value = input("> ").strip()
        if not value:
            return default
        if value.isdigit() and 1 <= int(value) <= pair_count:
            return int(value)
        write_error_line(f"Invalid input. Enter a number between 1 and {pair_count}.")


def get_recursive_job_display_mode() -> str:
    while True:
        write_action_line("Choose recursive job display mode:")
        write_warning_line("1: Silent background jobs    - no CMD windows opened, cleanest")
        write_warning_line("2: Minimized CMD windows     - colored live logs, may still be annoying")
        write_warning_line("3: Visible CMD windows       - colored live logs, can steal focus")
        choice = input("Enter your choice [default: 1]: ").strip() or "1"

        if choice == "1":
            return "silent"

        if choice == "2":
            return "minimized_cmd"

        if choice == "3":
            return "visible_cmd"

        write_error_line("Invalid choice. Enter 1, 2, or 3.")


# =====================================================================================
# JSONC config loading and pairlist expansion
# =====================================================================================
def remove_json_comments(text: str) -> str:
    result = []
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


def load_jsonc_file(path: str) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
        data = json.loads(remove_json_comments(text))
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        write_warning_line(f"Config file not found: {path}")
        return {}
    except json.JSONDecodeError as e:
        write_error_line(f"Failed to parse JSON/JSONC file: {path}")
        write_error_line(str(e))
        return {}
    except Exception as e:
        write_error_line(f"Failed to read config file: {path}")
        write_error_line(str(e))
        return {}


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def resolve_add_config_path(add_config_file: str, base_dir: str) -> str:
    clean = add_config_file.replace("/", os.sep)
    if os.path.isabs(clean):
        return clean
    candidate_base = os.path.join(base_dir, clean)
    if os.path.isfile(candidate_base):
        return candidate_base
    candidate_project = os.path.join(PROJECT_ROOT, clean)
    if os.path.isfile(candidate_project):
        return candidate_project
    candidate_user_data = os.path.join(PROJECT_ROOT, CONFIG_FOLDER, clean)
    if os.path.isfile(candidate_user_data):
        return candidate_user_data
    return candidate_base


def load_config_with_addons(path: str, visited: set[str] | None = None) -> dict[str, Any]:
    if visited is None:
        visited = set()
    abs_path = os.path.abspath(path)
    if abs_path in visited:
        return {}
    visited.add(abs_path)
    config = load_jsonc_file(abs_path)
    base_dir = os.path.dirname(abs_path)
    add_files = config.get("add_config_files", [])
    if not isinstance(add_files, list):
        return config
    for add_file in add_files:
        if not isinstance(add_file, str) or not add_file.strip():
            continue
        add_path = resolve_add_config_path(add_file, base_dir)
        add_config = load_config_with_addons(add_path, visited)
        if add_config:
            config = deep_merge(config, add_config)
    return config


def get_exchange_name(config: dict[str, Any]) -> str:
    exchange = config.get("exchange", {})
    if isinstance(exchange, dict):
        name = exchange.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return ""


def is_regex_pair_pattern(value: str) -> bool:
    return any(char in value for char in "*^$[](){}\\|+?")


def normalize_pair_value(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    pair = value.strip().upper()
    if not pair or "/" not in pair:
        return None
    if is_regex_pair_pattern(pair):
        return None
    if not re.match(r"^[A-Z0-9][A-Z0-9_.-]*/[A-Z0-9][A-Z0-9_.-]*$", pair):
        return None
    return pair


def pattern_matches_pair(pattern: str, pair: str) -> bool:
    pattern = pattern.strip()
    if not pattern:
        return False
    if not is_regex_pair_pattern(pattern):
        return pattern.upper() == pair.upper()
    try:
        return bool(re.fullmatch(pattern, pair)) or bool(re.match(pattern, pair))
    except re.error:
        return False


def pair_allowed_by_config(pair: str, config: dict[str, Any]) -> bool:
    exchange = config.get("exchange", {})
    whitelist = []
    blacklist = []
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


def pair_from_data_filename(path: str, timeframe: str) -> str | None:
    filename = os.path.basename(path)
    known_exts = [".feather", ".json", ".json.gz", ".parquet"]
    base = None
    for ext in known_exts:
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


def scan_downloaded_pairs(timeframe: str, exchange_name: str = "") -> list[str]:
    data_root = os.path.join(PROJECT_ROOT, "user_data", "data")
    if not os.path.isdir(data_root):
        return []
    search_roots = []
    if exchange_name:
        ex_root = os.path.join(data_root, exchange_name)
        if os.path.isdir(ex_root):
            search_roots.append(ex_root)
    search_roots.append(data_root)
    files = []
    for root in search_roots:
        for ext in ("feather", "json", "json.gz", "parquet"):
            files.extend(glob.glob(os.path.join(root, "**", f"*-{timeframe}.{ext}"), recursive=True))
    pairs = []
    for path in files:
        pair = pair_from_data_filename(path, timeframe)
        if pair:
            pairs.append(pair)
    return dedupe_preserve_order(sorted(set(pairs)))


def expand_config_pairlist_to_downloaded_pairs(config_file: str, timeframe: str) -> list[str]:
    config = load_config_with_addons(project_path_from_rel(config_file))
    exchange_name = get_exchange_name(config)
    downloaded_pairs = scan_downloaded_pairs(timeframe=timeframe, exchange_name=exchange_name)
    selected = [pair for pair in downloaded_pairs if pair_allowed_by_config(pair, config)]
    return dedupe_preserve_order(selected)


# =====================================================================================
# Strategy detection
# =====================================================================================
def extract_strategy_classes_from_file(path: str) -> list[str]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception:
        return []
    return re.findall(r"class\s+([A-Za-z_][A-Za-z0-9_]*)\s*\([^)]*IStrategy[^)]*\)\s*:", content)


def find_strategy_file_for_class(strategy_name: str) -> str | None:
    for path in sorted(glob.glob(os.path.join(STRATEGY_FOLDER, "*.py"))):
        if strategy_name in extract_strategy_classes_from_file(path):
            return path
    return None


def extract_class_block(content: str, class_name: str) -> str:
    class_match = re.search(rf"^class\s+{re.escape(class_name)}\s*\([^)]*\)\s*:", content, flags=re.MULTILINE)
    if not class_match:
        return content
    start = class_match.start()
    next_class = re.search(r"^class\s+[A-Za-z_][A-Za-z0-9_]*\s*\([^)]*\)\s*:", content[class_match.end():], flags=re.MULTILINE)
    if not next_class:
        return content[start:]
    return content[start : class_match.end() + next_class.start()]


def read_strategy_class_block(strategy_name: str) -> tuple[str, str | None]:
    path = find_strategy_file_for_class(strategy_name)
    if not path:
        return "", None
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception:
        return "", path
    return extract_class_block(content, strategy_name), path


def extract_strategy_timeframe(strategy_name: str) -> tuple[str, str | None]:
    block, path = read_strategy_class_block(strategy_name)
    match = re.search(r"^\s*timeframe\s*(?::\s*str\s*)?=\s*[\"']([^\"']+)[\"']", block, flags=re.MULTILINE)
    if match:
        return match.group(1).strip(), path
    return "5m", path


def extract_startup_candle_count(strategy_name: str) -> tuple[int | None, str | None]:
    block, path = read_strategy_class_block(strategy_name)
    if not block:
        return None, path
    for pattern in (r"^\s*startup_candle_count\s*:\s*int\s*=\s*(\d+)\b", r"^\s*startup_candle_count\s*=\s*(\d+)\b"):
        match = re.search(pattern, block, flags=re.MULTILINE)
        if match:
            return int(match.group(1)), path
    return None, path


def build_auto_startup_candles(startup_count: int | None) -> list[int]:
    if startup_count is None or startup_count <= 0:
        return FALLBACK_STARTUP_CANDLES.copy()
    base = int(startup_count)
    values = [max(base, int(round(base * x))) for x in [1.0, 1.25, 2.0, 3.0, 5.0]]
    values = dedupe_preserve_order(values)
    while len(values) < 5:
        values.append(values[-1] + base)
    return values[:5]


def get_auto_startup_candles(strategy_name: str) -> tuple[list[int], int | None, str | None]:
    startup, path = extract_startup_candle_count(strategy_name)
    values = build_auto_startup_candles(startup)
    if startup is None:
        write_warning_line(f"Could not detect startup_candle_count. Using fallback: {' '.join(str(x) for x in values)}")
        if path:
            write_warning_line(f"Checked strategy file: {path}")
        return values, None, path
    rel = rel_to_project(path) if path else "unknown"
    write_tell(f"Detected startup_candle_count = {startup} from {rel}")
    write_tell(f"Auto startup candles: {' '.join(str(x) for x in values)}")
    return values, startup, path


# =====================================================================================
# Terminal line formatting
# =====================================================================================
def is_table_line(clean: str) -> bool:
    stripped = clean.strip()
    if not stripped:
        return False
    table_start_chars = ("┏", "┓", "┗", "┛", "┡", "┩", "└", "┘", "┃", "│", "╇", "━", "─", "┴", "┬", "├", "┤")
    return stripped.startswith(table_start_chars) or any(c in clean for c in ("┃", "│", "╇", "└", "┘", "┏", "┗"))


def colorize_log_line(raw_line: str) -> str:
    clean = strip_ansi(raw_line).rstrip("\n")
    if is_table_line(clean):
        return clean
    match = LOG_LINE_RE.match(clean)
    if not match:
        upper = clean.upper()
        if clean.startswith("time="):
            return f"{CYAN}{clean}{RESET}"
        if clean.startswith("Container "):
            return f"{GREEN}{clean}{RESET}"
        if clean.strip() in {"Lookahead Analysis", "Recursive Analysis"}:
            return f"{BRIGHT_WHITE}{clean}{RESET}"
        if any(x in upper for x in ["CRITICAL", "FAILED", "ERROR", "NO DATA FOUND"]):
            return f"{RED}{clean}{RESET}"
        if any(x in upper for x in ["WARNING", "NO HISTORY FOR", "DATA STARTS AT"]):
            return f"{YELLOW}{clean}{RESET}"
        return clean
    timestamp, logger_name, level, message = match.groups()
    level_color = BLUE if level == "INFO" else YELLOW if level == "WARNING" else RED if level in ("ERROR", "CRITICAL") else CYAN
    return f"{YELLOW}{timestamp}{RESET} - {MAGENTA}{logger_name}{RESET} - {level_color}{level}{RESET} - {WHITE}{message}{RESET}"


def is_suppressed_data_warning(line: str) -> bool:
    line = strip_ansi(line).strip().lower()
    if not line or "warning" not in line:
        return False
    looks_like_history_warning = "data.history" in line or "datahandlers.idatahandler" in line or "idatahandler" in line
    return looks_like_history_warning and (("data starts at" in line) or ("no history for" in line))


def print_suppressed_warning_counter(count: int):
    sys.stdout.write(f"\r{CYAN}Suppressed data warnings: {count}{RESET}")
    sys.stdout.flush()


def clear_suppressed_warning_counter():
    sys.stdout.write("\r" + " " * 120 + "\r")
    sys.stdout.flush()


# =====================================================================================
# Output extraction and classification
# =====================================================================================
def extract_section_from_title(text: str, title: str, fallback_to_full_text: bool = True) -> str:
    clean = strip_ansi(text)
    lines = clean.splitlines()
    title_lower = title.lower()
    start_index = None

    for index, line in enumerate(lines):
        if line.strip().lower() == title_lower:
            start_index = index
            break

    if start_index is None:
        # Critical: do not return the full raw log for recursive failed jobs.
        # Raw logs are saved separately; reports must stay clean.
        return clean.strip() if fallback_to_full_text else ""

    # Return from the title through the table only. Stop before wrapper/footer/log blocks.
    captured: list[str] = []
    for line in lines[start_index:]:
        stripped = line.strip()

        if captured and stripped.startswith("====="):
            break

        # If another log block starts after the table, stop.
        if captured and re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}\s+-\s+", stripped):
            break

        captured.append(line)

    return "\n".join(captured).strip()


def extract_lookahead_summary(text: str) -> str:
    return extract_section_from_title(text, "Lookahead Analysis", fallback_to_full_text=True)


def extract_recursive_summary(text: str, include_title: bool = True) -> str:
    # Never fallback to full logs. Missing table means missing table.
    summary = extract_section_from_title(text, "Recursive Analysis", fallback_to_full_text=False)

    if not summary or include_title:
        return summary

    lines = summary.splitlines()

    # Final report sections already have their own pair/run heading, so repeating
    # the generic Freqtrade title for every OK job adds noise.
    if lines and lines[0].strip().lower() == "recursive analysis":
        lines = lines[1:]

    while lines and not lines[0].strip():
        lines = lines[1:]

    return "\n".join(lines).strip()


def extract_loaded_strategy_json(text: str) -> str:
    match = re.search(r"Loading parameters from file\s+(.+?\.json)", strip_ansi(text), flags=re.IGNORECASE)
    return match.group(1).strip() if match else "False"


def classify_freqtrade_output(raw_text: str, docker_returncode: int | None, pair: str = "", timeframe: str = "") -> tuple[int, str]:
    clean = strip_ansi(raw_text)
    lower = clean.lower()
    pair_text = pair or "selected pair"
    timeframe_text = timeframe or "selected timeframe"

    no_history_match = re.search(r"No history for\s+([^,\n]+),\s*([^,\n]+),\s*([^,\n]+)\s+found", clean, flags=re.IGNORECASE)
    data_starts_match = re.search(r"([A-Z0-9_.-]+/[A-Z0-9_.-]+),\s*spot,\s*([0-9a-zA-Z]+),\s*data starts at\s+([0-9]{4}-[0-9]{2}-[0-9]{2}\s+[0-9]{2}:[0-9]{2}:[0-9]{2})", clean, flags=re.IGNORECASE)

    if "no pair in whitelist" in lower:
        return 2, "No pair in whitelist."

    if "no data found" in lower or no_history_match:
        if no_history_match:
            pair_text = no_history_match.group(1).strip()
            timeframe_text = no_history_match.group(3).strip()
        if data_starts_match:
            starts_at = data_starts_match.group(3).strip()
            return 2, f"No usable {timeframe_text} data for {pair_text} in this timerange. Downloaded data starts at {starts_at}. Download wider data or exclude this pair."
        return 2, f"No usable {timeframe_text} data for {pair_text}. Run freqtrade download-data for this pair/timeframe/timerange or exclude it."

    if "configuration error" in lower or "failed validating" in lower or "invalid configuration" in lower:
        for line in clean.splitlines():
            if any(x in line.lower() for x in ["configuration error", "failed validating", "invalid configuration"]):
                return 3, line.strip()
        return 3, "Freqtrade configuration error."

    error_line = ""
    for line in clean.splitlines():
        if " - ERROR - " in line or " - CRITICAL - " in line:
            error_line = line.strip()
            break

    docker_code = int(docker_returncode) if docker_returncode is not None else 1
    if docker_code != 0:
        return docker_code, error_line or f"Docker/Freqtrade exited with code {docker_code}."
    if error_line:
        return 1, error_line
    return 0, "OK"


# =====================================================================================
# Selection menus
# =====================================================================================
def get_config_file() -> str:
    ensure_working_directory()
    config_folder_path = os.path.join(PROJECT_ROOT, CONFIG_FOLDER)
    if not os.path.isdir(config_folder_path):
        write_error_line(f"Directory '{config_folder_path}' does not exist. Current path: {os.getcwd()}")
        sys.exit(1)

    configs = []
    main_config = os.path.join(config_folder_path, "config.json")
    if os.path.isfile(main_config):
        configs.append(main_config)
    configs.extend(sorted(glob.glob(os.path.join(config_folder_path, "config-*.json"))))
    configs = list(dict.fromkeys(configs))
    if not configs:
        write_error_line(f"No config.json or config-*.json files found in '{config_folder_path}'.")
        sys.exit(1)

    while True:
        write_action_line("Available configs:")
        for idx, cfg in enumerate(configs, start=1):
            write_info_line(f"{idx}. {os.path.basename(cfg)}")
        choice = input(f"Enter your choice (1-{len(configs)}): ").strip()
        if choice.isdigit():
            index = int(choice)
            if 1 <= index <= len(configs):
                return rel_to_project(configs[index - 1])
        write_error_line(f"Invalid input. Enter a number between 1 and {len(configs)}.")


def get_strategy_name() -> str:
    if not os.path.isdir(STRATEGY_FOLDER):
        write_error_line(f"Strategy folder does not exist: {STRATEGY_FOLDER}")
        sys.exit(1)
    found = []
    for path in sorted(glob.glob(os.path.join(STRATEGY_FOLDER, "*.py"))):
        for class_name in extract_strategy_classes_from_file(path):
            found.append((class_name, os.path.basename(path)))
    found = sorted(set(found), key=lambda x: x[0].lower())

    while True:
        write_action_line("Available strategies:")
        if found:
            for idx, (class_name, file_name) in enumerate(found, start=1):
                write_info_line(f"{idx}. {class_name}    [{file_name}]")
        else:
            write_warning_line("No IStrategy classes auto-detected.")
        manual_index = len(found) + 1
        write_warning_line(f"{manual_index}. Manual strategy name")
        choice = input(f"Enter your choice (1-{manual_index}): ").strip()
        if choice.isdigit():
            index = int(choice)
            if 1 <= index <= len(found):
                strategy_name = found[index - 1][0]
                write_tell(f"Selected strategy: {strategy_name}")
                return strategy_name
            if index == manual_index:
                strategy_name = input("Enter strategy class name: ").strip()
                if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", strategy_name):
                    write_tell(f"Selected strategy: {strategy_name}")
                    return strategy_name
                write_error_line("Invalid strategy class name.")
                continue
        write_error_line(f"Invalid input. Enter a number between 1 and {manual_index}.")


def get_timerange() -> tuple[str, str]:
    while True:
        write_action_line("Choose time-window:")
        write_warning_line("1: FULL        20240101-20251201")
        write_warning_line("2: TRAIN       20240101-20240701")
        write_warning_line("3: VALID       20240701-20241001")
        write_warning_line("4: TEST        20241001-20251201")
        write_warning_line("5: LIVE_CHECK  20251001-20260410")
        write_warning_line("6: CUSTOM      Manual YYYYMMDD-YYYYMMDD")
        choice = input("Enter your choice: ").strip()
        if choice in TIME_WINDOWS:
            label, timerange = TIME_WINDOWS[choice]
            write_tell(f"Selected {label}: {timerange}")
            return label, timerange
        if choice == "6":
            while True:
                timerange = input("Custom timerange, example 20240101-20251201: ").strip()
                if re.match(r"^\d{8}-\d{8}$", timerange):
                    write_tell(f"Selected CUSTOM: {timerange}")
                    return "CUSTOM", timerange
                write_error_line("Invalid timerange. Use YYYYMMDD-YYYYMMDD.")
        write_error_line("Invalid choice. Enter 1, 2, 3, 4, 5, or 6.")


def get_analysis_mode() -> str:
    while True:
        write_action_line("Choose analysis type:")
        write_warning_line("1: Lookahead-Analysis   - Check strategy for lookahead bias")
        write_warning_line("2: Recursive-Analysis   - Check indicator stability across startup candles")
        choice = input("Enter your choice: ").strip()
        if choice == "1":
            return "lookahead-analysis"
        if choice == "2":
            return "recursive-analysis"
        write_error_line("Invalid choice. Enter 1 or 2.")


def get_manual_pairs() -> list[str]:
    while True:
        write_action_line("Enter pair/pairs for recursive-analysis.")
        write_warning_line("Example single: BTC/USDT")
        write_warning_line("Example multi:  BTC/USDT ETH/USDT SOL/USDT")
        value = input("Pairs [default: BTC/USDT]: ").strip()
        if not value:
            return ["BTC/USDT"]
        tokens = split_tokens(value)
        valid, invalid = [], []
        for token in tokens:
            pair = normalize_pair_value(token)
            if pair:
                valid.append(pair)
            else:
                invalid.append(token)
        if invalid:
            write_error_line(f"Invalid pairs: {', '.join(invalid)}")
            write_warning_line("Use real pairs like BTC/USDT, not regex like .*/USDT.")
            continue
        return dedupe_preserve_order(valid)


def get_pair_source(config_file: str, timeframe: str) -> tuple[str, list[str]]:
    while True:
        write_action_line("Choose recursive pair source:")
        write_warning_line("1: Expand selected config/add_config_files pairlist into real downloaded pairs")
        write_warning_line("2: Use recommended pairs - BTC/USDT ETH/USDT SOL/USDT XRP/USDT")
        write_warning_line("3: Enter pairs manually")
        choice = input("Enter your choice [default: 1]: ").strip() or "1"
        if choice == "1":
            pairs = expand_config_pairlist_to_downloaded_pairs(config_file, timeframe)
            if not pairs:
                write_error_line("No downloaded pairs matched the selected config/add_config_files pairlist.")
                write_warning_line(f"Checked downloaded data for timeframe {timeframe}. Use option 2/3 or download data first.")
                continue
            write_tell(f"Expanded config pairlist into {len(pairs)} downloaded pair(s) using timeframe {timeframe}.")
            preview = " ".join(pairs[:30]) + (" ..." if len(pairs) > 30 else "")
            write_info_line(f"Pairs preview: {preview}")
            return "expanded_config_pairlist", pairs
        if choice == "2":
            pairs = RECOMMENDED_RECURSIVE_PAIRS.copy()
            write_tell(f"Using recommended pairs: {' '.join(pairs)}")
            return "recommended", pairs
        if choice == "3":
            pairs = get_manual_pairs()
            write_tell(f"Selected {len(pairs)} manual pair(s): {' '.join(pairs)}")
            return "manual", pairs
        write_error_line("Invalid choice. Enter 1, 2, or 3.")


def get_recursive_run_mode(pair_count: int) -> str:
    if pair_count <= 1:
        return "cmd_per_pair_sequential"
    while True:
        write_action_line("Choose recursive run mode:")
        write_warning_line("1: One CMD terminal per pair, parallel slot-refill - keeps N jobs running")
        write_warning_line("2: One CMD terminal per pair, sequential")
        choice = input("Enter your choice [default: 1]: ").strip() or "1"
        if choice == "1":
            return "cmd_per_pair_parallel"
        if choice == "2":
            return "cmd_per_pair_sequential"
        write_error_line("Invalid choice. Enter 1 or 2.")


# =====================================================================================
# Command builders
# =====================================================================================
def build_base_command(mode: str, config_file: str, strategy_name: str, timerange: str, container_name: str | None = None) -> list[str]:
    if container_name is None:
        container_name = get_container_name(mode)
    return [
        DOCKER_COMPOSE,
        "run",
        "--name",
        container_name,
        "--rm",
        DOCKER_SERVICE,
        mode,
        "--config",
        config_file,
        "--strategy",
        strategy_name,
        "--timerange",
        timerange,
    ]


def build_lookahead_command(config_file: str, strategy_name: str, timerange: str, minimum_trade_amount: int, targeted_trade_amount: int) -> list[str]:
    cmd = build_base_command("lookahead-analysis", config_file, strategy_name, timerange)
    cmd.extend(["--minimum-trade-amount", str(minimum_trade_amount), "--targeted-trade-amount", str(targeted_trade_amount)])
    return cmd


def build_recursive_command(config_file: str, strategy_name: str, timerange: str, pairs: list[str], startup_candles: list[int], container_name: str) -> list[str]:
    cmd = build_base_command("recursive-analysis", config_file, strategy_name, timerange, container_name)
    if pairs:
        cmd.extend(["-p", *pairs])
    cmd.extend(["--startup-candle", *[str(x) for x in startup_candles]])
    return cmd


# =====================================================================================
# Reports
# =====================================================================================
def save_raw_output(raw_text: str, mode: str, strategy_name: str, stamp: str) -> str:
    os.makedirs(RAW_OUTPUT_FOLDER, exist_ok=True)
    prefix = get_analysis_file_prefix(mode)
    raw_file = os.path.join(RAW_OUTPUT_FOLDER, safe_filename(f"raw_{prefix}_{strategy_name}__{stamp}.txt"))
    with open(raw_file, "w", encoding="utf-8", newline="\n") as f:
        f.write(strip_ansi(raw_text) + "\n")
    return raw_file


def save_extract(raw_text: str, cmd: list[str], mode: str, strategy_name: str, config_file: str, time_window_label: str, timerange: str, extra_metadata: dict[str, Any]):
    os.makedirs(EXTRACT_FOLDER, exist_ok=True)
    clean = strip_ansi(raw_text)
    if mode == "lookahead-analysis":
        summary = extract_lookahead_summary(clean)
    elif mode == "recursive-analysis":
        summary = extract_recursive_summary(clean)
    else:
        summary = clean.strip()
    if not summary:
        write_error_line("Could not extract useful output from docker output.")
        return
    stamp = stamp_now()
    prefix = get_analysis_file_prefix(mode)
    raw_file = save_raw_output(raw_text, mode, strategy_name, stamp)
    metadata_lines = [
        "# Freqtrade Analysis Extract Metadata",
        f"mode = {mode}",
        f"strategy = {strategy_name}",
        f"config = {config_file}",
        f"time_window = {time_window_label}",
        f"timerange = {timerange}",
        f"strategy_json_loaded = {extract_loaded_strategy_json(raw_text)}",
        f"raw_output_file = {raw_file}",
        f"created_at = {stamp}",
        f"command = {command_to_string(cmd)}",
    ]
    for key, value in extra_metadata.items():
        metadata_lines.append(f"{key} = {value}")
    extract_file = os.path.join(EXTRACT_FOLDER, safe_filename(f"{prefix}_{strategy_name}__{stamp}.txt"))
    with open(extract_file, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(metadata_lines) + "\n\n")
        f.write(summary + "\n")
    write_action_line(f"Raw output saved to: {raw_file}")
    write_action_line(f"Analysis extract saved to: {extract_file}")


def get_clean_recursive_table_or_notice(result: dict[str, Any]) -> str:
    """
    Return only the Recursive Analysis table/section for report files.

    Important: never fall back to full raw logs here. Raw logs are already saved
    separately in user_data/analysis_raw_output.
    """
    raw_text = read_text_file(result.get("raw_file", ""))
    summary = extract_recursive_summary(raw_text)

    if summary:
        return summary.strip()

    try:
        effective = int(result.get("effective_returncode", 1))
    except Exception:
        effective = 1

    if effective == 0:
        return (
            "No Recursive Analysis table was found in the captured output. "
            "The raw output was saved separately for debugging."
        )

    return (
        "No Recursive Analysis table was produced because this job failed. "
        f"reason_code={reason_code(result)}; "
        f"reason={report_clean(result.get('reason'))}"
    )


def save_recursive_job_extract(result: dict[str, Any], params: dict[str, Any], stamp: str) -> str:
    os.makedirs(EXTRACT_FOLDER, exist_ok=True)
    prefix = get_analysis_file_prefix("recursive-analysis")
    safe_strategy = safe_filename(params["strategy_name"])
    safe_label = safe_filename(result["label"])
    summary = get_clean_recursive_table_or_notice(result)
    extract_file = os.path.join(EXTRACT_FOLDER, safe_filename(f"{prefix}_{safe_strategy}_{safe_label}__{stamp}.txt"))
    metadata_lines = [
        "# Freqtrade Recursive-Analysis Job Extract",
        f"label = {result['label']}",
        f"pair = {result.get('pair', result['label'])}",
        f"strategy = {params['strategy_name']}",
        f"config = {params['config_file']}",
        f"time_window = {params['time_window_label']}",
        f"timerange = {params['timerange']}",
        f"timeframe = {params['extra'].get('timeframe', '')}",
        f"docker_returncode = {result.get('docker_returncode')}",
        f"effective_returncode = {result.get('effective_returncode')}",
        f"status = {result.get('status_text')}",
        f"reason_code = {reason_code(result)}",
        f"reason = {report_clean(result.get('reason'))}",
        f"raw_capture = temporary / merged into combined_raw_output_file",
        f"status_file = {result.get('status_file')}",
        f"created_at = {stamp_now()}",
        f"command = {command_to_string(result['cmd'])}",
    ]
    with open(extract_file, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(metadata_lines) + "\n\n")
        f.write(summary.strip() + "\n")
    return extract_file


def make_official_recursive_report_file(strategy_name: str, stamp: str) -> str:
    prefix = get_analysis_file_prefix("recursive-analysis")
    safe_strategy = safe_filename(strategy_name)
    return os.path.join(
        EXTRACT_FOLDER,
        safe_filename(f"{prefix}_Report_{safe_strategy}__{stamp}.txt"),
    )


def make_combined_recursive_raw_file(strategy_name: str, stamp: str) -> str:
    prefix = get_analysis_file_prefix("recursive-analysis")
    safe_strategy = safe_filename(strategy_name)
    return os.path.join(
        RAW_OUTPUT_FOLDER,
        safe_filename(f"raw_{prefix}_{safe_strategy}__{stamp}.txt"),
    )


def report_clean(value: Any) -> str:
    """Single-line safe text for report tables."""
    text = strip_ansi(str(value or ""))
    text = text.replace("|", "/")
    text = text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def shorten_middle(value: Any, limit: int) -> str:
    text = report_clean(value)
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    left = (limit - 3) // 2
    right = limit - 3 - left
    return text[:left] + "..." + text[-right:]


def reason_code(result: dict[str, Any]) -> str:
    try:
        effective = int(result.get("effective_returncode", 1))
    except Exception:
        effective = 1

    if effective == 0:
        return "OK"

    reason = report_clean(result.get("reason", "")).lower()

    if "no pair in whitelist" in reason:
        return "NO_PAIR_IN_WHITELIST"
    if "no usable" in reason and "data" in reason:
        return "NO_DATA"
    if "no history" in reason or "no data found" in reason:
        return "NO_DATA"
    if "configuration" in reason or "failed validating" in reason or "invalid configuration" in reason:
        return "CONFIG"
    if "timed out" in reason or "stale" in reason or "no longer exists" in reason:
        return "STALE_JOB"
    if "failed to launch" in reason:
        return "LAUNCH"
    if "before writing running/done status" in reason or "no status" in reason:
        return "NO_STATUS"
    if "docker/freqtrade exited" in reason or "docker" in reason:
        return "DOCKER"

    return "ERROR"


def fixed_width_table(headers: list[str], rows: list[list[Any]], widths: list[int]) -> list[str]:
    """Plain-text table. Stable in VS Code/Notepad/CMD, unlike markdown with long cells."""
    normalized_headers = [shorten_middle(h, w).ljust(w) for h, w in zip(headers, widths)]
    border = "+-" + "-+-".join("-" * w for w in widths) + "-+"
    lines = [border, "| " + " | ".join(normalized_headers) + " |", border]

    for row in rows:
        cells = []
        for idx, width in enumerate(widths):
            cell = row[idx] if idx < len(row) else ""
            cells.append(shorten_middle(cell, width).ljust(width))
        lines.append("| " + " | ".join(cells) + " |")

    lines.append(border)
    return lines


def format_pair_sample(pairs: list[str], max_items: int | None = None, per_line: int = 10) -> list[str]:
    if not pairs:
        return ["none"]

    # User asked for the full pair/pending list.
    # max_items=None means no shortening and no "... more not shown" line.
    shown = pairs if max_items is None else pairs[:max_items]

    lines = []
    for idx in range(0, len(shown), per_line):
        lines.append(" ".join(shown[idx:idx + per_line]))

    if max_items is not None:
        remaining = len(pairs) - len(shown)
        if remaining > 0:
            lines.append(f"... {remaining} more not shown")

    return lines



def save_recursive_combined_extract(
    finished_results: list[dict[str, Any]],
    pending_labels: list[str],
    params: dict[str, Any],
    stamp: str,
) -> tuple[str, str]:
    """
    Writes one clean Recursive-Analysis report file for the whole run.

    Main fixes:
    - File name no longer starts with OFFICIAL_REPORT.
    - No giant one-line pair/pending dumps.
    - No markdown table with huge cells. Uses fixed-width text tables.
    - Pending rows are summarized, not dumped one row per pair.
    - No individual per-pair raw files are kept in analysis_raw_output.
    - Failed jobs are summarized only in Jobs Without Extracted Recursive Table.
    - No separate OK Jobs block. OK pairs stay visible in Job Summary and Recursive tables.
    """
    os.makedirs(EXTRACT_FOLDER, exist_ok=True)
    os.makedirs(RAW_OUTPUT_FOLDER, exist_ok=True)

    prefix = get_analysis_file_prefix("recursive-analysis")
    strategy_name = params["strategy_name"]
    official_report_file = make_official_recursive_report_file(strategy_name, stamp)
    combined_raw_file = make_combined_recursive_raw_file(strategy_name, stamp)

    # Preserve pair queue order instead of sorting alphabetically. This makes the report match run order.
    pair_order = {str(label): idx for idx, label in enumerate(params["extra"].get("pairs", []))}
    finished_results = sorted(
        finished_results,
        key=lambda x: pair_order.get(str(x.get("label", "")), 999999),
    )
    pending_labels = list(pending_labels)

    with open(combined_raw_file, "w", encoding="utf-8", newline="\n") as f:
        for result in finished_results:
            # Per-job raw captures live temporarily in analysis_jobs only.
            # This writes the single combined raw file, then temp files are deleted after the final report.
            raw_path = str(result.get("raw_file", ""))
            if int(result.get("effective_returncode", 1)) != 0 or not raw_path or not os.path.isfile(raw_path):
                continue

            raw_text = read_text_file(raw_path)
            f.write(
                f"===== RAW RUN {result['label']} | "
                f"{result.get('status_text')} =====\n"
            )
            f.write(strip_ansi(raw_text).rstrip() + "\n")
            f.write(f"===== END RAW RUN {result['label']} =====\n\n")

    ok_count = sum(1 for x in finished_results if int(x.get("effective_returncode", 1)) == 0)
    failed_count = sum(1 for x in finished_results if int(x.get("effective_returncode", 1)) != 0)
    finished_count = len(finished_results)
    pending_count = len(pending_labels)
    total_count = finished_count + pending_count

    if total_count == 0:
        run_status = "NO JOBS"
    elif pending_count > 0:
        run_status = "IN PROGRESS"
    elif failed_count > 0:
        run_status = "FINISHED WITH FAILURES"
    else:
        run_status = "FINISHED OK"

    strategy_file = params["extra"].get("strategy_startup_source_file")
    strategy_file_text = rel_to_project(strategy_file) if strategy_file else "not_found"
    pairs = params["extra"].get("pairs", [])

    metadata_lines = [
        "# Freqtrade Recursive-Analysis Report",
        "",
        "## Run Metadata",
        "",
        f"run_status = {run_status}",
        f"strategy = {strategy_name}",
        f"config = {params['config_file']}",
        f"time_window = {params['time_window_label']}",
        f"timerange = {params['timerange']}",
        f"timeframe = {params['extra'].get('timeframe', '')}",
        f"pair_source = {params['extra'].get('pair_source')}",
        f"pair_count = {len(pairs)}",
        f"finished_count = {finished_count}",
        f"ok_count = {ok_count}",
        f"failed_count = {failed_count}",
        f"pending_count = {pending_count}",
        f"strategy_startup_candle_count = {params['extra'].get('strategy_startup_candle_count')}",
        f"strategy_startup_source_file = {strategy_file_text}",
        f"startup_candles = {' '.join(str(x) for x in params['extra'].get('startup_candles', []))}",
        f"max_parallel = {params['extra'].get('max_parallel')}",
        f"report_file = {official_report_file}",
        f"updated_at = {stamp_now()}",
    ]

    pair_lines = ["", "## Pair Queue", ""]
    pair_lines.append(f"total_pairs = {len(pairs)}")
    pair_lines.append("all_pairs:")
    pair_lines.extend(format_pair_sample([str(x) for x in pairs], max_items=None, per_line=10))
    pair_lines.append("")
    pair_lines.append(f"pending_count = {pending_count}")
    pair_lines.append("pending_pairs:")
    pair_lines.extend(format_pair_sample([str(x) for x in pending_labels], max_items=None, per_line=10))

    summary_lines = ["", "## Job Summary", ""]
    summary_lines.extend(
        [
            f"finished = {finished_count}",
            f"ok       = {ok_count}",
            f"failed   = {failed_count}",
            f"pending  = {pending_count}",
            "",
        ]
    )

    if not finished_results:
        summary_lines.append("No finished jobs yet. This file updates after each completed job.")
    else:
        rows: list[list[Any]] = []
        for result in finished_results:
            rows.append(
                [
                    result.get("label", ""),
                    result.get("status_text", ""),
                    result.get("effective_returncode", ""),
                    result.get("docker_returncode", ""),
                    reason_code(result),
                ]
            )

        summary_lines.extend(
            fixed_width_table(
                headers=["Pair/Run", "Status", "Eff", "Docker", "Reason"],
                rows=rows,
                widths=[18, 8, 5, 6, 24],
            )
        )

    result_lines = ["", "## Recursive-Analysis Tables", ""]

    if not finished_results:
        result_lines.append("No jobs have finished yet. This report will update after each job completes.")
    else:
        table_results: list[tuple[dict[str, Any], str]] = []
        no_table_results: list[dict[str, Any]] = []

        for result in finished_results:
            raw_text = read_text_file(result.get("raw_file", ""))
            summary = extract_recursive_summary(raw_text, include_title=False)

            if summary:
                table_results.append((result, summary.strip()))
            else:
                no_table_results.append(result)

        if table_results:
            for result, summary in table_results:
                result_lines.append(
                    f"===== RUN {result['label']} | {result.get('status_text')} =====\n"
                    f"{summary.strip()}\n"
                    f"===== END RUN {result['label']} =====\n"
                )
        else:
            result_lines.append("No Recursive Analysis tables have been extracted yet.")

        if no_table_results:
            result_lines.append("")
            result_lines.append("## Jobs Without Extracted Recursive Table")
            result_lines.append("")
            no_table_rows = []

            for result in no_table_results:
                no_table_rows.append(
                    [
                        result.get("label", ""),
                        result.get("status_text", ""),
                        result.get("effective_returncode", ""),
                        reason_code(result),
                    ]
                )

            result_lines.extend(
                fixed_width_table(
                    headers=["Pair/Run", "Status", "Eff", "Reason"],
                    rows=no_table_rows,
                    widths=[18, 8, 5, 22],
                )
            )

    with open(official_report_file, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(metadata_lines))
        f.write("\n")
        f.write("\n".join(pair_lines))
        f.write("\n")
        f.write("\n".join(summary_lines))
        f.write("\n")
        f.write("\n".join(result_lines))
        f.write("\n")

    return official_report_file, combined_raw_file


# =====================================================================================
# Direct live runner for lookahead
# =====================================================================================
def run_command_live_capture(cmd: list[str]) -> tuple[int, str]:
    output_lines = []
    suppressed = 0
    counter_visible = False
    try:
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        process = subprocess.Popen(cmd, cwd=PROJECT_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", bufsize=1, env=env)
        if process.stdout is None:
            raise RuntimeError("Failed to open process stdout stream.")
        for raw_line in process.stdout:
            output_lines.append(raw_line)
            if is_suppressed_data_warning(raw_line):
                suppressed += 1
                print_suppressed_warning_counter(suppressed)
                counter_visible = True
                continue
            if counter_visible:
                clear_suppressed_warning_counter()
                counter_visible = False
            sys.stdout.write(colorize_log_line(raw_line) + "\n")
            sys.stdout.flush()
        return_code = process.wait()
        if counter_visible:
            clear_suppressed_warning_counter()
            write_warning_line(f"Suppressed data warnings total: {suppressed}")
        return return_code, "".join(output_lines)
    except Exception as e:
        write_error_line(f"Failed while streaming docker output: {e}")
        return 1, "".join(output_lines)


# =====================================================================================
# Child CMD job runner file
# =====================================================================================
JOB_RUNNER_CODE = r'''
#!/usr/bin/env python
import ctypes
import base64
import json
import os
import re
import subprocess
import zlib
import sys
from datetime import datetime

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
LOG_LINE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})\s+-\s+([^-].*?)\s+-\s+(INFO|WARNING|ERROR|CRITICAL|DEBUG)\s+-\s+(.*)$")

def stamp_now():
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

def enable_windows_ansi():
    """Enable ANSI color handling in spawned CMD/Windows Terminal windows."""
    if os.name != "nt":
        return
    try:
        # This helps some Windows builds initialise ANSI handling.
        os.system("")

        kernel32 = ctypes.windll.kernel32
        ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004

        for std_handle in (-11, -12):  # STD_OUTPUT_HANDLE, STD_ERROR_HANDLE
            handle = kernel32.GetStdHandle(std_handle)
            if handle == 0 or handle == -1:
                continue

            mode = ctypes.c_uint32()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                kernel32.SetConsoleMode(
                    handle,
                    mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING,
                )
    except Exception:
        # Do not fail the job just because the console cannot enable colors.
        pass

def strip_ansi(value):
    value = ANSI_RE.sub("", value or "")
    value = value.replace("\x00", "")
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    return value

def write_json_atomic(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)

def is_table_line(clean):
    stripped = clean.strip()
    if not stripped:
        return False
    table_start_chars = ("┏", "┓", "┗", "┛", "┡", "┩", "└", "┘", "┃", "│", "╇", "━", "─", "┴", "┬", "├", "┤")
    return stripped.startswith(table_start_chars) or any(c in clean for c in ("┃", "│", "╇", "└", "┘", "┏", "┗"))

def colorize_log_line(raw_line):
    clean = strip_ansi(raw_line).rstrip("\n")
    if is_table_line(clean):
        return clean
    match = LOG_LINE_RE.match(clean)
    if not match:
        upper = clean.upper()
        if clean.startswith("time="):
            return f"{CYAN}{clean}{RESET}"
        if clean.startswith("Container "):
            return f"{GREEN}{clean}{RESET}"
        if clean.strip() in {"Lookahead Analysis", "Recursive Analysis"}:
            return f"{BRIGHT_WHITE}{clean}{RESET}"
        if any(x in upper for x in ["CRITICAL", "FAILED", "ERROR", "NO DATA FOUND"]):
            return f"{RED}{clean}{RESET}"
        if any(x in upper for x in ["WARNING", "NO HISTORY FOR", "DATA STARTS AT"]):
            return f"{YELLOW}{clean}{RESET}"
        return clean
    timestamp, logger_name, level, message = match.groups()
    level_color = BLUE if level == "INFO" else YELLOW if level == "WARNING" else RED if level in ("ERROR", "CRITICAL") else CYAN
    return f"{YELLOW}{timestamp}{RESET} - {MAGENTA}{logger_name}{RESET} - {level_color}{level}{RESET} - {WHITE}{message}{RESET}"

def classify_freqtrade_output(raw_text, docker_returncode, pair="", timeframe=""):
    clean = strip_ansi(raw_text)
    lower = clean.lower()
    pair_text = pair or "selected pair"
    timeframe_text = timeframe or "selected timeframe"
    no_history_match = re.search(r"No history for\s+([^,\n]+),\s*([^,\n]+),\s*([^,\n]+)\s+found", clean, flags=re.IGNORECASE)
    data_starts_match = re.search(r"([A-Z0-9_.-]+/[A-Z0-9_.-]+),\s*spot,\s*([0-9a-zA-Z]+),\s*data starts at\s+([0-9]{4}-[0-9]{2}-[0-9]{2}\s+[0-9]{2}:[0-9]{2}:[0-9]{2})", clean, flags=re.IGNORECASE)
    if "no pair in whitelist" in lower:
        return 2, "No pair in whitelist."
    if "no data found" in lower or no_history_match:
        if no_history_match:
            pair_text = no_history_match.group(1).strip()
            timeframe_text = no_history_match.group(3).strip()
        if data_starts_match:
            starts_at = data_starts_match.group(3).strip()
            return 2, f"No usable {timeframe_text} data for {pair_text} in this timerange. Downloaded data starts at {starts_at}. Download wider data or exclude this pair."
        return 2, f"No usable {timeframe_text} data for {pair_text}. Run freqtrade download-data for this pair/timeframe/timerange or exclude it."
    if "configuration error" in lower or "failed validating" in lower or "invalid configuration" in lower:
        for line in clean.splitlines():
            if any(x in line.lower() for x in ["configuration error", "failed validating", "invalid configuration"]):
                return 3, line.strip()
        return 3, "Freqtrade configuration error."
    error_line = ""
    for line in clean.splitlines():
        if " - ERROR - " in line or " - CRITICAL - " in line:
            error_line = line.strip()
            break
    if int(docker_returncode) != 0:
        return int(docker_returncode), error_line or f"Docker/Freqtrade exited with code {docker_returncode}."
    if error_line:
        return 1, error_line
    return 0, "OK"

def decode_job_from_args(argv):
    if len(argv) >= 3 and argv[1] == "--job-b64":
        payload = base64.urlsafe_b64decode(argv[2].encode("ascii"))
        text = zlib.decompress(payload).decode("utf-8")
        return json.loads(text)

    # Legacy fallback only. New parent script does not create job_*.json files.
    if len(argv) >= 2:
        with open(argv[1], "r", encoding="utf-8") as f:
            return json.load(f)

    raise RuntimeError("Missing --job-b64 payload.")

def main():
    enable_windows_ansi()
    try:
        job = decode_job_from_args(sys.argv)
    except Exception as e:
        print(f"{RED}Missing or invalid job payload: {e}{RESET}")
        return 99

    project_root = job["project_root"]
    raw_file = job["raw_file"]
    status_file = job["status_file"]
    cmd = job["cmd"]
    label = job["label"]
    pair = job.get("pair", label)
    timeframe = job.get("timeframe", "")
    container_name = job.get("container_name", "")
    status = {
        "status": "running",
        "label": label,
        "pair": pair,
        "container_name": container_name,
        "cmd": cmd,
        "raw_file": raw_file,
        "status_file": status_file,
        "docker_returncode": None,
        "effective_returncode": None,
        "status_text": "RUNNING",
        "reason": "Running",
        "started_at": stamp_now(),
        "finished_at": None,
        "last_heartbeat_at": stamp_now(),
        "last_output_at": None,
    }
    write_json_atomic(status_file, status)
    os.makedirs(os.path.dirname(raw_file), exist_ok=True)
    print(f"{CYAN}{'=' * 80}{RESET}")
    print(f"{GREEN}START: {label}{RESET}")
    print(f"{WHITE}Command: {' '.join(cmd)}{RESET}")
    print(f"{CYAN}{'=' * 80}{RESET}")
    docker_returncode = 1
    raw_parts = []
    try:
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        process = subprocess.Popen(cmd, cwd=project_root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", bufsize=1, env=env)
        with open(raw_file, "w", encoding="utf-8", newline="\n") as raw:
            if process.stdout is None:
                raise RuntimeError("Could not open child stdout.")
            last_status_write = 0.0
            import time
            for raw_line in process.stdout:
                raw_parts.append(raw_line)
                raw.write(strip_ansi(raw_line))
                raw.flush()
                sys.stdout.write(colorize_log_line(raw_line) + "\n")
                sys.stdout.flush()

                now = time.monotonic()
                if now - last_status_write >= 15:
                    status.update({
                        "status": "running",
                        "status_text": "RUNNING",
                        "last_heartbeat_at": stamp_now(),
                        "last_output_at": stamp_now(),
                    })
                    write_json_atomic(status_file, status)
                    last_status_write = now
        docker_returncode = process.wait()
    except Exception as e:
        error_text = f"Job runner failed before/while running docker command: {e}\n"
        raw_parts.append(error_text)
        with open(raw_file, "a", encoding="utf-8", newline="\n") as raw:
            raw.write(error_text)
        print(f"{RED}{error_text.strip()}{RESET}")
        docker_returncode = 98
    raw_text = "".join(raw_parts)
    if not raw_text:
        try:
            with open(raw_file, "r", encoding="utf-8", errors="replace") as f:
                raw_text = f.read()
        except Exception:
            raw_text = ""
    effective_returncode, reason = classify_freqtrade_output(raw_text, docker_returncode, pair, timeframe)
    status_text = "OK" if effective_returncode == 0 else "FAILED"

    # Failed jobs do not keep raw logs. The reason/status is already parsed before deletion.
    if effective_returncode != 0:
        try:
            if os.path.isfile(raw_file):
                os.remove(raw_file)
        except Exception:
            pass
        raw_file_for_status = ""
    else:
        raw_file_for_status = raw_file

    status.update({
        "status": "done",
        "docker_returncode": docker_returncode,
        "effective_returncode": effective_returncode,
        "status_text": status_text,
        "reason": reason,
        "raw_file": raw_file_for_status,
        "finished_at": stamp_now(),
    })
    write_json_atomic(status_file, status)
    print(f"{CYAN}{'=' * 80}{RESET}")
    if effective_returncode == 0:
        print(f"{GREEN}DONE: {label} | OK | docker_returncode={docker_returncode}{RESET}")
    else:
        print(f"{RED}DONE: {label} | FAILED | effective_returncode={effective_returncode} | docker_returncode={docker_returncode}{RESET}")
        print(f"{YELLOW}Reason: {reason}{RESET}")
    print(f"{YELLOW}Status file: {status_file}{RESET}")
    if effective_returncode == 0:
        print(f"{YELLOW}Raw captured for combined report.{RESET}")
    else:
        print(f"{YELLOW}Temporary raw capture removed for failed job.{RESET}")
    print(f"{CYAN}{'=' * 80}{RESET}")
    return int(effective_returncode)

if __name__ == "__main__":
    raise SystemExit(main())
'''


def ensure_job_runner_file() -> str:
    runner_file = os.path.join(JOBS_FOLDER, "freqtrade_analysis_job_runner.py")
    with open(runner_file, "w", encoding="utf-8", newline="\n") as f:
        f.write(JOB_RUNNER_CODE)
    return runner_file


def make_recursive_container_name(label: str, stamp: str) -> str:
    return safe_filename(f"{get_container_name('recursive-analysis')}_{label}_{stamp}")


def make_job_paths(label: str, strategy_name: str, stamp: str) -> dict[str, str]:
    prefix = get_analysis_file_prefix("recursive-analysis")
    base = safe_filename(f"{prefix}_{strategy_name}_{label}__{stamp}")
    return {
        "raw_file": os.path.join(JOBS_FOLDER, f"tmp_raw_{base}.txt"),
        "status_file": os.path.join(JOBS_FOLDER, f"status_{base}.json"),
        "cmd_file": os.path.join(JOBS_FOLDER, f"run_{base}.cmd"),
    }


def encode_job_payload(job: dict[str, Any]) -> str:
    """Encode job config directly into the child command. Avoids job_*.json files."""
    payload = json.dumps(job, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    compressed = zlib.compress(payload, level=9)
    return base64.urlsafe_b64encode(compressed).decode("ascii")


def build_initial_status(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "launching",
        "label": job["label"],
        "pair": job.get("pair", job["label"]),
        "container_name": job["container_name"],
        "cmd": job["cmd"],
        "raw_file": job["raw_file"],
        "status_file": job["status_file"],
        "docker_returncode": None,
        "effective_returncode": None,
        "status_text": "LAUNCHING",
        "reason": "CMD window launched, waiting for job runner to start.",
        "created_at": stamp_now(),
        "started_at": None,
        "finished_at": None,
        "last_heartbeat_at": None,
        "last_output_at": None,
    }


def create_recursive_job(params: dict[str, Any], label: str, pairs: list[str], stamp: str, runner_file: str) -> dict[str, Any]:
    container_name = make_recursive_container_name(label, stamp)
    paths = make_job_paths(label, params["strategy_name"], stamp)
    cmd = build_recursive_command(
        params["config_file"],
        params["strategy_name"],
        params["timerange"],
        pairs,
        params["extra"]["startup_candles"],
        container_name,
    )
    pair_for_status = pairs[0] if len(pairs) == 1 else label

    job = {
        "label": label,
        "pair": pair_for_status,
        "project_root": PROJECT_ROOT,
        "container_name": container_name,
        "cmd": cmd,
        "raw_file": paths["raw_file"],
        "status_file": paths["status_file"],
        "cmd_file": paths["cmd_file"],
        "timeframe": params["extra"].get("timeframe", ""),
        "launched_at_monotonic": None,
    }

    # No job_*.json file is created. The child runner receives this encoded payload.
    job_payload = encode_job_payload(job)
    job["job_b64"] = job_payload

    python_exe = sys.executable
    cmd_content = (
        "@echo off\n"
        f"title Freqtrade Recursive {label}\n"
        f"cd /d \"{PROJECT_ROOT}\"\n"
        f"\"{python_exe}\" \"{runner_file}\" --job-b64 \"{job_payload}\"\n"
        "exit\n"
    )

    with open(paths["cmd_file"], "w", encoding="utf-8", newline="\r\n") as f:
        f.write(cmd_content)

    write_json_atomic(paths["status_file"], build_initial_status(job))
    return job

def launch_visible_or_minimized_cmd_job(job: dict[str, Any], minimized: bool) -> bool:
    try:
        remove_old_container(job["container_name"])

        window_flag = "/min " if minimized else ""
        # Use cmd /d /c and call the job .cmd. The child .cmd ends with plain "exit".
        # This is the most reliable close-after-finish pattern for classic CMD.
        start_cmd = f'start "" {window_flag}%ComSpec% /d /c "call \"{job["cmd_file"]}\""'

        subprocess.Popen(
            start_cmd,
            cwd=PROJECT_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=True,
        )

        job["launched_at_monotonic"] = time.monotonic()
        return True

    except Exception as e:
        status = read_json_file(job["status_file"]) or build_initial_status(job)
        status.update({
            "status": "done",
            "status_text": "FAILED",
            "docker_returncode": None,
            "effective_returncode": 97,
            "reason": f"Failed to launch CMD window: {e}",
            "finished_at": stamp_now(),
        })
        write_json_atomic(job["status_file"], status)
        return False


def launch_silent_job(job: dict[str, Any], runner_file: str) -> bool:
    try:
        remove_old_container(job["container_name"])

        creationflags = 0
        startupinfo = None

        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        subprocess.Popen(
            [sys.executable, runner_file, "--job-b64", job["job_b64"]],
            cwd=PROJECT_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
            startupinfo=startupinfo,
            shell=False,
        )

        job["launched_at_monotonic"] = time.monotonic()
        return True

    except Exception as e:
        status = read_json_file(job["status_file"]) or build_initial_status(job)
        status.update({
            "status": "done",
            "status_text": "FAILED",
            "docker_returncode": None,
            "effective_returncode": 97,
            "reason": f"Failed to launch silent background job: {e}",
            "finished_at": stamp_now(),
        })
        write_json_atomic(job["status_file"], status)
        return False


def launch_recursive_job(job: dict[str, Any], display_mode: str, runner_file: str) -> bool:
    if display_mode == "silent":
        return launch_silent_job(job, runner_file)

    if display_mode == "visible_cmd":
        return launch_visible_or_minimized_cmd_job(job, minimized=False)

    # Default: minimized CMD. This avoids most focus stealing and closes after the task.
    return launch_visible_or_minimized_cmd_job(job, minimized=True)


def docker_container_exists(container_name: str) -> bool:
    """Return True while the docker container still exists.

    Recursive jobs use docker-compose run --rm, so the container disappears after
    completion. If the status file is still RUNNING after the container vanished,
    the child CMD probably closed before writing final status.
    """
    if not container_name:
        return False

    try:
        completed = subprocess.run(
            [
                "docker",
                "ps",
                "-a",
                "--filter",
                f"name={container_name}",
                "--format",
                "{{.Names}}",
            ],
            cwd=PROJECT_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )

        names = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
        return container_name in names

    except Exception:
        # Do not fail the monitor just because docker ps had a transient issue.
        return True


def mark_job_done_from_raw(job: dict[str, Any], reason_override: str | None = None):
    """Finalize a job whose child status did not get written cleanly.

    This reads the temporary raw capture if available, classifies the output,
    removes failed-job raw captures, and writes a normal DONE status so the
    scheduler can finish the report instead of hanging forever.
    """
    status = read_json_file(job["status_file"]) or build_initial_status(job)
    raw_text = read_text_file(job.get("raw_file", ""))
    docker_code = status.get("docker_returncode")

    if docker_code is None:
        # If the child CMD died after Freqtrade printed a complete Recursive Analysis
        # table, treat it as an OK result. Otherwise classify as a failed/stale job.
        docker_code = 0 if extract_recursive_summary(raw_text) else 1

    effective, parsed_reason = classify_freqtrade_output(
        raw_text,
        docker_code,
        job.get("pair", ""),
        job.get("timeframe", ""),
    )

    reason = parsed_reason if int(effective) == 0 else (reason_override or parsed_reason)

    raw_file = job.get("raw_file", "")
    if int(effective) != 0 and raw_file and os.path.isfile(raw_file):
        try:
            os.remove(raw_file)
        except Exception:
            pass
        raw_file = ""

    status.update({
        "status": "done",
        "status_text": "OK" if int(effective) == 0 else "FAILED",
        "docker_returncode": docker_code,
        "effective_returncode": effective,
        "reason": reason,
        "raw_file": raw_file,
        "finished_at": stamp_now(),
    })
    write_json_atomic(job["status_file"], status)


def mark_job_timed_out(job: dict[str, Any], reason: str):
    remove_old_container(job.get("container_name", ""))
    status = read_json_file(job["status_file"]) or build_initial_status(job)

    raw_file = job.get("raw_file", "")
    if raw_file and os.path.isfile(raw_file):
        try:
            os.remove(raw_file)
        except Exception:
            pass

    status.update({
        "status": "done",
        "status_text": "FAILED",
        "docker_returncode": None,
        "effective_returncode": 95,
        "reason": reason,
        "raw_file": "",
        "finished_at": stamp_now(),
    })
    write_json_atomic(job["status_file"], status)


def mark_job_failed_no_status(job: dict[str, Any], reason: str):
    status = read_json_file(job["status_file"]) or build_initial_status(job)
    status.update({
        "status": "done",
        "status_text": "FAILED",
        "docker_returncode": None,
        "effective_returncode": 96,
        "reason": reason,
        "finished_at": stamp_now(),
    })
    write_json_atomic(job["status_file"], status)
    # Do not create raw output for failed/no-status jobs.


def result_from_status(job: dict[str, Any], status: dict[str, Any]) -> dict[str, Any]:
    effective = status.get("effective_returncode")
    docker_code = status.get("docker_returncode")
    reason = status.get("reason", "")
    if effective is None:
        effective, reason = classify_freqtrade_output(read_text_file(job["raw_file"]), docker_code or 1, job.get("pair", ""), job.get("timeframe", ""))
    status_text = "OK" if int(effective) == 0 else "FAILED"

    raw_file = status.get("raw_file", job.get("raw_file", ""))
    if int(effective) != 0:
        # Failed jobs do not keep raw output files.
        try:
            fallback_raw = job.get("raw_file", "")
            if fallback_raw and os.path.isfile(fallback_raw):
                os.remove(fallback_raw)
        except Exception:
            pass
        raw_file = ""

    return {
        "label": job["label"],
        "pair": job.get("pair", job["label"]),
        "container_name": job["container_name"],
        "cmd": job["cmd"],
        "raw_file": raw_file,
        "status_file": job["status_file"],
        "cmd_file": job["cmd_file"],
        "docker_returncode": docker_code,
        "effective_returncode": effective,
        "status_text": status_text,
        "reason": reason,
    }


def cleanup_job_control_files(job: dict[str, Any]):
    """Remove temporary files used only to launch/monitor one child job."""
    for key in ("cmd_file", "status_file"):
        path = job.get(key, "")
        if not path:
            continue
        try:
            if os.path.isfile(path):
                os.remove(path)
        except Exception:
            pass


def cleanup_runner_file(runner_file: str):
    try:
        if runner_file and os.path.isfile(runner_file):
            os.remove(runner_file)
    except Exception:
        pass

def cleanup_recursive_temp_raw_files(results: list[dict[str, Any]]):
    """Delete per-job temporary raw captures after final report and combined raw are written."""
    jobs_root = os.path.abspath(JOBS_FOLDER).lower()
    for result in results:
        path = str(result.get("raw_file", ""))
        if not path:
            continue
        try:
            abs_path = os.path.abspath(path)
            if os.path.isfile(abs_path) and abs_path.lower().startswith(jobs_root):
                os.remove(abs_path)
        except Exception:
            pass


def cleanup_analysis_job_folder(strategy_name: str | None = None, stamp: str | None = None):
    """Delete temporary job-control files from analysis_jobs.

    These files are only used for child-job launch/monitoring. The final report and
    combined raw output live in analysis_extracts / analysis_raw_output, so nothing
    important is lost here.
    """
    if not os.path.isdir(JOBS_FOLDER):
        return

    patterns = [
        "tmp_raw_*.txt",
        "status_*.json",
        "run_*.cmd",
        "job_*.json",
        "*.tmp",
        "freqtrade_analysis_job_runner.py",
        "__pycache__",
    ]

    for pattern in patterns:
        for path in glob.glob(os.path.join(JOBS_FOLDER, pattern)):
            if stamp and stamp not in os.path.basename(path) and not path.endswith("freqtrade_analysis_job_runner.py"):
                continue
            try:
                if os.path.isdir(path):
                    import shutil
                    shutil.rmtree(path, ignore_errors=True)
                elif os.path.isfile(path):
                    os.remove(path)
            except Exception:
                pass



# =====================================================================================
# Parameter collection
# =====================================================================================
def collect_lookahead_options(strategy_name: str) -> dict[str, Any]:
    minimum_trade_amount = get_positive_int_default("Enter --minimum-trade-amount", 300)
    targeted_trade_amount = get_positive_int_default("Enter --targeted-trade-amount", 1000)
    return {"minimum_trade_amount": minimum_trade_amount, "targeted_trade_amount": targeted_trade_amount}


def collect_recursive_options(config_file: str, strategy_name: str) -> dict[str, Any]:
    timeframe, tf_file = extract_strategy_timeframe(strategy_name)
    if tf_file:
        write_tell(f"Detected timeframe = {timeframe} from {rel_to_project(tf_file)}")
    else:
        write_warning_line(f"Could not detect timeframe. Using default {timeframe}.")
    pair_source, pairs = get_pair_source(config_file, timeframe)
    startup_candles, strategy_startup, strategy_file = get_auto_startup_candles(strategy_name)
    run_mode = get_recursive_run_mode(len(pairs))
    max_parallel = get_parallel_workers(len(pairs)) if run_mode == "cmd_per_pair_parallel" else 1
    job_display_mode = get_recursive_job_display_mode()

    return {
        "timeframe": timeframe,
        "pair_source": pair_source,
        "pairs": pairs,
        "startup_candles": startup_candles,
        "strategy_startup_candle_count": strategy_startup,
        "strategy_startup_source_file": strategy_file,
        "run_mode": run_mode,
        "max_parallel": max_parallel,
        "job_display_mode": job_display_mode,
    }


def collect_parameters() -> dict[str, Any]:
    mode = get_analysis_mode()
    time_window_label, timerange = get_timerange()
    config_file = get_config_file()
    strategy_name = get_strategy_name()
    params = {"mode": mode, "time_window_label": time_window_label, "timerange": timerange, "config_file": config_file, "strategy_name": strategy_name}
    if mode == "lookahead-analysis":
        params["extra"] = collect_lookahead_options(strategy_name)
    elif mode == "recursive-analysis":
        params["extra"] = collect_recursive_options(config_file, strategy_name)
    else:
        write_error_line(f"Unsupported mode: {mode}")
        sys.exit(1)
    return params


# =====================================================================================
# Runners
# =====================================================================================
def run_lookahead_analysis(params: dict[str, Any]):
    container_name = get_container_name("lookahead-analysis")
    remove_old_container(container_name)
    cmd = build_lookahead_command(
        params["config_file"],
        params["strategy_name"],
        params["timerange"],
        params["extra"]["minimum_trade_amount"],
        params["extra"]["targeted_trade_amount"],
    )
    write_action_line("Running command:")
    write_action_line(command_to_string(cmd))
    try:
        returncode, raw_output = run_command_live_capture(cmd)
        if raw_output.strip():
            save_extract(raw_output, cmd, params["mode"], params["strategy_name"], params["config_file"], params["time_window_label"], params["timerange"], {
                "minimum_trade_amount": params["extra"]["minimum_trade_amount"],
                "targeted_trade_amount": params["extra"]["targeted_trade_amount"],
            })
        effective, reason = classify_freqtrade_output(raw_output, returncode)
        if effective != 0:
            write_error_line(f"{params['mode']} finished with effective exit code: {effective}")
            write_error_line(f"Reason: {reason}")
        else:
            write_action_line(f"{params['mode']} finished successfully.")
    except KeyboardInterrupt:
        write_warning_line("Interrupted by user.")
        remove_old_container(container_name)
    except Exception as e:
        write_error_line(f"Failed to run docker command: {e}")
        remove_old_container(container_name)


def build_recursive_jobs(params: dict[str, Any], stamp: str, runner_file: str) -> list[dict[str, Any]]:
    pairs = params["extra"]["pairs"]
    return [create_recursive_job(params, pair, [pair], stamp, runner_file) for pair in pairs]


def print_job_finish(result: dict[str, Any]):
    code = reason_code(result)
    if result["status_text"] == "OK":
        write_action_line(f"Finished job: {result['label']} | OK")
    else:
        write_error_line(f"Finished job: {result['label']} | FAILED | {code}")


def run_recursive_analysis(params: dict[str, Any]):
    pairs = params["extra"]["pairs"]
    if not pairs:
        write_error_line("No pairs selected for recursive-analysis.")
        return

    # Clear old temp job files before starting. These files are disposable and
    # are the reason analysis_jobs gets filled with status/tmp_raw/run files.
    cleanup_analysis_job_folder()

    run_mode = params["extra"]["run_mode"]
    max_parallel = params["extra"]["max_parallel"]

    if run_mode == "cmd_per_pair_sequential":
        max_parallel = 1

    stamp = stamp_now()
    runner_file = ensure_job_runner_file()
    jobs = build_recursive_jobs(params, stamp, runner_file)
    pending = jobs.copy()
    active: list[dict[str, Any]] = []
    finished: list[dict[str, Any]] = []

    initial_pending_labels = [job["label"] for job in jobs]
    combined_extract_file, combined_raw_file = save_recursive_combined_extract(
        finished_results=[],
        pending_labels=initial_pending_labels,
        params=params,
        stamp=stamp,
    )

    last_progress = 0.0
    display_mode = params["extra"].get("job_display_mode", "minimized_cmd")

    write_action_line(f"Running Recursive-Analysis: jobs={len(jobs)}, max_parallel={max_parallel}")
    write_tell(f"Official report file: {combined_extract_file}")

    if run_mode == "cmd_per_pair_parallel":
        write_tell(
            f"Slot-refill scheduler enabled: it will keep up to {max_parallel} job(s) running. "
            "When one finishes, the next pending pair starts immediately."
        )

    if display_mode == "silent":
        write_warning_line("Silent mode: no CMD windows will open.")
    elif display_mode == "visible_cmd":
        write_warning_line("Visible CMD mode: windows may take focus.")
    else:
        write_warning_line("Minimized CMD mode: windows open minimized; use silent if Windows still steals focus.")

    def launch_until_slots_full():
        """Start pending jobs until active slots reach max_parallel."""
        nonlocal pending, active

        started = 0

        while pending and len(active) < max_parallel:
            job = pending.pop(0)
            slot_number = len(active) + 1

            if display_mode == "silent":
                write_action_line(f"Starting silent job [{slot_number}/{max_parallel}]: {job['label']}")
            elif display_mode == "visible_cmd":
                write_action_line(f"Opening visible CMD [{slot_number}/{max_parallel}]: {job['label']}")
            else:
                write_action_line(f"Opening minimized CMD [{slot_number}/{max_parallel}]: {job['label']}")

            launch_recursive_job(job, display_mode, runner_file)
            active.append(job)
            started += 1

        return started

    try:
        # Fill the first batch of slots.
        launch_until_slots_full()

        while pending or active:
            still_active: list[dict[str, Any]] = []
            finished_this_poll = 0

            for job in active:
                status = read_json_file(job["status_file"])

                if status and status.get("status") == "done":
                    result = result_from_status(job, status)
                    result["job_extract_file"] = ""
                    finished.append(result)
                    finished_this_poll += 1

                    print_job_finish(result)

                    pending_labels = [x["label"] for x in pending] + [x["label"] for x in active if x["label"] != job["label"]]
                    combined_extract_file, combined_raw_file = save_recursive_combined_extract(finished, pending_labels, params, stamp)
                    cleanup_job_control_files(job)
                    continue

                launched_at = job.get("launched_at_monotonic")
                elapsed = time.monotonic() - launched_at if launched_at else 0

                if launched_at and elapsed > JOB_LAUNCH_GRACE_SECONDS:
                    if not status or status.get("status") == "launching":
                        reason = f"Child job closed or failed before writing running/done status. Check job CMD file: {job['cmd_file']}"
                        mark_job_failed_no_status(job, reason)
                        status = read_json_file(job["status_file"]) or {}
                        result = result_from_status(job, status)
                        result["job_extract_file"] = ""
                        finished.append(result)
                        finished_this_poll += 1

                        print_job_finish(result)

                        pending_labels = [x["label"] for x in pending] + [x["label"] for x in active if x["label"] != job["label"]]
                        combined_extract_file, combined_raw_file = save_recursive_combined_extract(finished, pending_labels, params, stamp)
                        cleanup_job_control_files(job)
                        continue

                if launched_at and status and status.get("status") == "running":
                    if elapsed > JOB_MISSING_CONTAINER_GRACE_SECONDS and not docker_container_exists(job.get("container_name", "")):
                        reason = "Docker container no longer exists but child job did not write final DONE status."
                        mark_job_done_from_raw(job, reason_override=reason)
                        status = read_json_file(job["status_file"]) or {}
                        result = result_from_status(job, status)
                        result["job_extract_file"] = ""
                        finished.append(result)
                        finished_this_poll += 1

                        print_job_finish(result)

                        pending_labels = [x["label"] for x in pending] + [x["label"] for x in active if x["label"] != job["label"]]
                        combined_extract_file, combined_raw_file = save_recursive_combined_extract(finished, pending_labels, params, stamp)
                        cleanup_job_control_files(job)
                        continue

                    if elapsed > JOB_MAX_RUNTIME_SECONDS:
                        reason = f"Job timed out after {int(elapsed)} seconds. Docker container was stopped and job was marked failed."
                        mark_job_timed_out(job, reason)
                        status = read_json_file(job["status_file"]) or {}
                        result = result_from_status(job, status)
                        result["job_extract_file"] = ""
                        finished.append(result)
                        finished_this_poll += 1

                        print_job_finish(result)

                        pending_labels = [x["label"] for x in pending] + [x["label"] for x in active if x["label"] != job["label"]]
                        combined_extract_file, combined_raw_file = save_recursive_combined_extract(finished, pending_labels, params, stamp)
                        cleanup_job_control_files(job)
                        continue

                still_active.append(job)

            active = still_active

            # Critical behavior: refill freed slots immediately, not after all currently active jobs finish.
            started_now = launch_until_slots_full()

            if finished_this_poll or started_now:
                write_info_line(
                    f"Slots: active={len(active)}/{max_parallel} | pending={len(pending)} | "
                    f"finished={len(finished)}/{len(jobs)}"
                )

            now = time.monotonic()
            if now - last_progress >= 10:
                ok_count = sum(1 for r in finished if int(r.get("effective_returncode", 1)) == 0)
                fail_count = sum(1 for r in finished if int(r.get("effective_returncode", 1)) != 0)
                write_info_line(
                    f"Progress: done={len(finished)}/{len(jobs)} | OK={ok_count} | FAILED={fail_count} | "
                    f"active={len(active)} | pending={len(pending)}"
                )
                last_progress = now

            if active or pending:
                time.sleep(1)

    except KeyboardInterrupt:
        write_warning_line("Interrupted by user. Existing CMD windows may keep running.")
        write_warning_line("Close the analysis CMD windows manually if you want to stop all jobs.")
        return

    # Final write: rebuild the clean report and the single combined raw file before deleting temp raw captures.
    combined_extract_file, combined_raw_file = save_recursive_combined_extract(finished, [], params, stamp)

    cleanup_recursive_temp_raw_files(finished)
    cleanup_runner_file(runner_file)
    cleanup_analysis_job_folder(stamp=stamp)

    failed = [r for r in finished if int(r.get("effective_returncode", 1)) != 0]
    ok_count = len(finished) - len(failed)

    if combined_extract_file:
        write_action_line(f"Recursive-Analysis report saved to: {combined_extract_file}")
    if combined_raw_file:
        write_action_line(f"Combined raw output saved to: {combined_raw_file}")

    write_action_line(
        f"Finished: total={len(finished)} | OK={ok_count} | FAILED={len(failed)} | temp job files cleaned"
    )


def run_analysis(params: dict[str, Any]):
    ensure_working_directory()
    ensure_analysis_directories()
    if params["mode"] == "lookahead-analysis":
        run_lookahead_analysis(params)
        return
    if params["mode"] == "recursive-analysis":
        run_recursive_analysis(params)
        return
    write_error_line(f"Unsupported mode: {params['mode']}")


# =====================================================================================
# Main flow
# =====================================================================================
def main():
    enable_windows_ansi()
    ensure_working_directory()
    ensure_analysis_directories()
    params = collect_parameters()
    run_analysis(params)
    while True:
        write_action_line("Type 'retry'/'r' to use same parameters, 'new'/'n' for new parameters, or 'exit'/'e' to close.")
        user_input = input("> ").strip().lower()
        user_input = {"retry": "r", "new": "n", "exit": "e"}.get(user_input, user_input)
        if user_input == "r":
            write_tell("Retrying with same parameters...")
            run_analysis(params)
        elif user_input == "n":
            params = collect_parameters()
            write_warning_line("Running command with new parameters...")
            run_analysis(params)
        elif user_input == "e":
            write_info_line("Exiting...")
            break
        else:
            write_error_line("Invalid input. Type retry, new, or exit.")


if __name__ == "__main__":
    main()
