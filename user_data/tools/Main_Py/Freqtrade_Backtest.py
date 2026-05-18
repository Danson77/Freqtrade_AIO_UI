#!/usr/bin/env python
import os
import re
import glob
import time
import ctypes
import subprocess
import sys
from typing import Optional, Set


# =====================================================================================
# Timerange windows
# =====================================================================================
WINDOWS = {
    "1": ("TRAIN", "20240101-20240701"),
    "2": ("VALID", "20240701-20241001"),
    "3": ("TEST", "20241001-20251201"),
    "4": ("LIVE_CHECK", "20251001-20260410"),
}

DEFAULT_USE_CACHE = False

CONTAINER_NAME_PREFIX = "Freqtrade_Backtest"

MAX_CONTAINER_NAME_ATTEMPTS = 20

# =====================================================================================
# Basic colored output
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

# Freqtrade-style log line:
# 2026-04-10 21:11:48,212 - freqtrade.data.dataprovider - INFO - message...
LOG_LINE_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})\s+-\s+([^-].*?)\s+-\s+(INFO|WARNING|ERROR|CRITICAL|DEBUG)\s+-\s+(.*)$"
)

CONTAINER_NAME_CONFLICT_RE = re.compile(
    r'The container name\s+"?/([^"\s]+)"?\s+is already in use',
    re.IGNORECASE,
)


def enable_windows_ansi():
    """
    Enable ANSI escape processing in Windows terminals.
    """
    if os.name != "nt":
        return

    try:
        kernel32 = ctypes.windll.kernel32

        for std_handle in (-11, -12):  # STD_OUTPUT_HANDLE, STD_ERROR_HANDLE
            handle = kernel32.GetStdHandle(std_handle)
            if handle == 0 or handle == -1:
                continue

            mode = ctypes.c_uint32()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
                kernel32.SetConsoleMode(
                    handle,
                    mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING,
                )
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


# =====================================================================================
# Paths
# =====================================================================================
EXPECTED_PATH = r"N:\Freqtrade"
CONFIG_FOLDER = "user_data"
REPORTS_FOLDER = os.path.join("user_data", "backtest_reports")


def ensure_working_directory():
    if os.getcwd() != EXPECTED_PATH:
        write_warning_line(f"Switching to expected working directory: {EXPECTED_PATH}")
        try:
            os.chdir(EXPECTED_PATH)
        except Exception as e:
            write_error_line(f"Failed to change directory to {EXPECTED_PATH}. {e}")
            sys.exit(1)


def ensure_reports_directory() -> str:
    report_dir = os.path.join(EXPECTED_PATH, REPORTS_FOLDER)
    os.makedirs(report_dir, exist_ok=True)
    return report_dir


# =====================================================================================
# Helpers
# =====================================================================================
def strip_ansi(value: str) -> str:
    value = ANSI_RE.sub("", value or "")
    return value.replace("\r", "").replace("\x00", "")


def sanitize_filename(value: str) -> str:
    value = value.strip()
    value = value.replace(" ", "_")
    value = re.sub(r'[<>:"/\\|?*\n\r\t]+', "_", value)
    value = re.sub(r"_+", "_", value)
    value = value.strip("._")
    return value or "UNKNOWN"


def sanitize_container_part(value: str) -> str:
    """
    Docker container names should be simple:
    letters, numbers, underscore, dash, dot.

    This keeps names stable and readable:
    config-hyperopt.json -> hyperopt
    config-analysis.json -> analysis
    """
    value = value.strip()
    value = value.replace(" ", "_")
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", value)
    value = re.sub(r"_+", "_", value)
    value = value.strip("._-")

    if not value:
        value = "config"

    # Docker names should start with alphanumeric.
    if not re.match(r"^[A-Za-z0-9]", value):
        value = f"cfg_{value}"

    return value


def config_name_to_label(config_name: str) -> str:
    """
    Turns config filename into a useful container suffix.

    Examples:
        config-1.json          -> 1
        config-2.json          -> 2
        config-hyperopt.json   -> hyperopt
        config-analysis.json   -> analysis
        config-my-test.json    -> my-test
    """
    base = os.path.basename(config_name)
    stem = os.path.splitext(base)[0]

    lower_stem = stem.lower()

    if lower_stem.startswith("config-"):
        label = stem[len("config-"):]
    elif lower_stem.startswith("config_"):
        label = stem[len("config_"):]
    elif lower_stem == "config":
        label = "default"
    else:
        label = stem

    return sanitize_container_part(label)


def build_base_container_name(config_name: str) -> str:
    config_label = config_name_to_label(config_name)
    return f"{CONTAINER_NAME_PREFIX}_{config_label}"


def natural_sort_key(path: str):
    base = os.path.basename(path)
    return [
        int(part) if part.isdigit() else part.lower()
        for part in re.split(r"(\d+)", base)
    ]


def extract_strategy_name(full_output: str) -> Optional[str]:
    clean_output = strip_ansi(full_output)
    match = re.search(r"Result for strategy\s+([^\r\n]+)", clean_output)
    if match:
        return match.group(1).strip()
    return None


def extract_report_chunk(full_output: str) -> Optional[str]:
    clean_output = strip_ansi(full_output)

    pattern = re.compile(
        r"(\s*BACKTESTING REPORT.*?\n\s*Backtested .*?\n\s*STRATEGY SUMMARY.*?┘)",
        re.DOTALL,
    )

    match = pattern.search(clean_output)
    if match:
        return match.group(1).strip()

    return None


def get_window_name_from_timerange(timerange: str) -> str:
    for _, (name, tr) in WINDOWS.items():
        if tr == timerange:
            return name
    return "CUSTOM"


def build_window_section(window_name: str, timerange: str, report_chunk: str) -> str:
    return (
        f"===== WINDOW {window_name} | TIMERANGE {timerange} =====\n"
        f"{report_chunk.strip()}\n"
        f"===== END WINDOW {window_name} ====="
    )


def replace_or_add_window_section(
    existing_text: str,
    window_name: str,
    timerange: str,
    report_chunk: str,
) -> str:
    new_section = build_window_section(window_name, timerange, report_chunk)

    pattern = re.compile(
        rf"^===== WINDOW {re.escape(window_name)} \| TIMERANGE .*?^===== END WINDOW {re.escape(window_name)} =====\s*",
        re.DOTALL | re.MULTILINE,
    )

    if pattern.search(existing_text):
        updated = pattern.sub(new_section + "\n\n", existing_text, count=1).strip()
    else:
        existing_text = existing_text.strip()
        if existing_text:
            updated = existing_text + "\n\n" + new_section
        else:
            updated = new_section

    return reorder_window_sections(updated)


def reorder_window_sections(text: str) -> str:
    section_pattern = re.compile(
        r"(===== WINDOW (TRAIN|VALID|TEST|LIVE_CHECK|CUSTOM) \| TIMERANGE .*?^===== END WINDOW \2 =====)",
        re.DOTALL | re.MULTILINE,
    )

    sections = section_pattern.findall(text)

    if not sections:
        return text.strip()

    mapping = {}
    extras = []

    for full_section, name in sections:
        if name in ("TRAIN", "VALID", "TEST", "LIVE_CHECK") and name not in mapping:
            mapping[name] = full_section.strip()
        else:
            extras.append(full_section.strip())

    ordered = []

    for name in ("TRAIN", "VALID", "TEST", "LIVE_CHECK"):
        if name in mapping:
            ordered.append(mapping[name])

    ordered.extend(extras)

    return "\n\n".join(ordered).strip() + "\n"


# =====================================================================================
# Docker container name helpers
# =====================================================================================
def get_existing_docker_container_names() -> Set[str]:
    """
    Reads all Docker container names, running and stopped.

    This prevents:
        Error response from daemon: Conflict. The container name is already in use.
    """
    try:
        result = subprocess.run(
            ["docker", "ps", "-a", "--format", "{{.Names}}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=EXPECTED_PATH,
        )

        if result.returncode != 0:
            clean_error = strip_ansi(result.stderr).strip()
            if clean_error:
                write_warning_line(f"Could not read Docker container names: {clean_error}")
            return set()

        names = set()

        for line in result.stdout.splitlines():
            name = line.strip().lstrip("/")
            if name:
                names.add(name)

        return names

    except Exception as e:
        write_warning_line(f"Could not read Docker container names: {e}")
        return set()


def make_unique_container_name(
    base_container_name: str,
    extra_taken_names: Optional[Set[str]] = None,
) -> str:
    """
    Returns:
        Freqtrade_Backtest_x
        Freqtrade_Backtest_x-1
        Freqtrade_Backtest_x-2

    depending on existing Docker containers.
    """
    existing_names = get_existing_docker_container_names()

    if extra_taken_names:
        existing_names.update(extra_taken_names)

    if base_container_name not in existing_names:
        return base_container_name

    counter = 1

    while True:
        candidate = f"{base_container_name}-{counter}"

        if candidate not in existing_names:
            return candidate

        counter += 1


def output_has_container_name_conflict(full_output: str) -> bool:
    clean_output = strip_ansi(full_output)
    return bool(CONTAINER_NAME_CONFLICT_RE.search(clean_output)) or (
        "container name" in clean_output.lower()
        and "is already in use" in clean_output.lower()
    )


# =====================================================================================
# Lock + atomic write
# =====================================================================================
def acquire_lock(lock_path: str, timeout_seconds: int = 30, poll_interval: float = 0.25):
    start = time.time()

    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode("utf-8"))
            os.close(fd)
            return

        except FileExistsError:
            if time.time() - start > timeout_seconds:
                raise TimeoutError(f"Timed out waiting for lock: {lock_path}")

            time.sleep(poll_interval)


def release_lock(lock_path: str):
    try:
        if os.path.exists(lock_path):
            os.remove(lock_path)
    except Exception:
        pass


def atomic_write_text(file_path: str, content: str):
    temp_path = file_path + ".tmp"

    with open(temp_path, "w", encoding="utf-8", errors="replace") as f:
        f.write(content)

    os.replace(temp_path, file_path)


# =====================================================================================
# Warning suppression / streaming helpers
# =====================================================================================
def is_suppressed_data_warning(line: str) -> bool:
    """
    Suppress only spammy history availability warnings.
    Keep exchange warnings, price jumps, fillup, and other useful logs visible.
    """
    line = strip_ansi(line).strip().lower()

    if not line or "warning" not in line:
        return False

    looks_like_history_warning = (
        "data.history" in line
        or "datahandlers.idatahandler" in line
        or "idatahandler" in line
    )

    if not looks_like_history_warning:
        return False

    return ("data starts at" in line) or ("no history for" in line)


def print_suppressed_warning_counter(count: int):
    sys.stdout.write(f"\r{CYAN}Suppressed data warnings: {count}{RESET}")
    sys.stdout.flush()


def clear_suppressed_warning_counter():
    sys.stdout.write("\r" + " " * 100 + "\r")
    sys.stdout.flush()


def colorize_log_line(raw_line: str) -> str:
    """
    Apply manual colors to captured Docker/Freqtrade lines since native ANSI colors
    are lost when piping stdout on this setup.
    """
    clean = strip_ansi(raw_line).rstrip("\n")

    match = LOG_LINE_RE.match(clean)

    if not match:
        # Docker compose / container lifecycle / table lines / generic output
        if clean.startswith("time="):
            return f"{CYAN}{clean}{RESET}"

        if clean.startswith("Container "):
            return f"{GREEN}{clean}{RESET}"

        if clean.startswith("Result for strategy"):
            return f"{BRIGHT_WHITE}{clean}{RESET}"

        if (
            "BACKTESTING REPORT" in clean
            or "SUMMARY METRICS" in clean
            or "STRATEGY SUMMARY" in clean
        ):
            return f"{BRIGHT_WHITE}{clean}{RESET}"

        return clean

    timestamp, logger_name, level, message = match.groups()

    if level == "INFO":
        level_color = BLUE
    elif level == "WARNING":
        level_color = YELLOW
    elif level in ("ERROR", "CRITICAL"):
        level_color = RED
    else:
        level_color = CYAN

    return (
        f"{YELLOW}{timestamp}{RESET} - "
        f"{MAGENTA}{logger_name}{RESET} - "
        f"{level_color}{level}{RESET} - "
        f"{WHITE}{message}{RESET}"
    )


# =====================================================================================
# Save report into one strategy file with per-window replacement
# =====================================================================================
def save_report_to_strategy_file(full_output: str, timerange: str):
    report_dir = ensure_reports_directory()

    strategy_name = extract_strategy_name(full_output)

    if not strategy_name:
        write_warning_line("Could not detect strategy name from output.")
        strategy_name = "UNKNOWN_STRATEGY"

    report_chunk = extract_report_chunk(full_output)

    if not report_chunk:
        write_warning_line("Could not extract report block from output.")
        return

    safe_strategy = sanitize_filename(strategy_name)

    file_path = os.path.join(report_dir, f"{safe_strategy}__BACKTESTING_REPORT.ini")
    lock_path = file_path + ".lock"

    window_name = get_window_name_from_timerange(timerange)

    try:
        acquire_lock(lock_path)

        existing_text = ""

        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                existing_text = f.read()

        updated_text = replace_or_add_window_section(
            existing_text=existing_text,
            window_name=window_name,
            timerange=timerange,
            report_chunk=report_chunk,
        )

        atomic_write_text(file_path, updated_text)

        write_action_line(f"Saved window '{window_name}' into: {file_path}")

    except TimeoutError as e:
        write_error_line(str(e))

    except Exception as e:
        write_error_line(f"Failed to save report file: {e}")

    finally:
        release_lock(lock_path)


# =====================================================================================
# Select config
# =====================================================================================
def select_backtest_order():
    ensure_working_directory()

    config_folder_path = os.path.join(EXPECTED_PATH, CONFIG_FOLDER)

    if not os.path.isdir(config_folder_path):
        write_error_line(
            f"Directory '{CONFIG_FOLDER}' does not exist. Current path: {os.getcwd()}"
        )
        return None

    pattern = os.path.join(config_folder_path, "config-*.json")
    config_files = sorted(glob.glob(pattern), key=natural_sort_key)

    if not config_files:
        write_error_line(f"No config-*.json files found in '{CONFIG_FOLDER}'.")
        return None

    while True:
        write_action_line("Available Backtest Configs:")

        for index, cfg in enumerate(config_files, start=1):
            config_name = os.path.basename(cfg)
            write_info_line(f"{index}. {config_name}")

        choice = input(f"Enter your choice (1-{len(config_files)}): ").strip()

        if choice.isdigit():
            idx = int(choice)

            if 1 <= idx <= len(config_files):
                chosen_path = config_files[idx - 1]
                config_name = os.path.basename(chosen_path)
                base_container_name = build_base_container_name(config_name)
                config_rel = f"{CONFIG_FOLDER}/{config_name}"

                return {
                    "BaseContainerName": base_container_name,
                    "ConfigFile": config_rel,
                    "ConfigName": config_name,
                }

        write_error_line(
            f"Invalid input. Please enter a number between 1 and {len(config_files)}."
        )

# =====================================================================================
# Select timerange
# =====================================================================================
def select_timerange_window():
    while True:
        write_action_line("Select timerange window:")

        for key, (name, tr) in WINDOWS.items():
            write_info_line(f"{key}. {name}  [{tr}]")

        write_info_line("5. CUSTOM  [enter any freqtrade timerange]")

        choice = input("Enter your choice (1-5): ").strip()

        if choice.lower() in ("train", "t"):
            choice = "1"
        elif choice.lower() in ("valid", "v", "val"):
            choice = "2"
        elif choice.lower() in ("test", "x"):
            choice = "3"
        elif choice.lower() in ("live_check", "live", "l"):
            choice = "4"
        elif choice.lower() in ("custom", "c"):
            choice = "5"

        if choice in WINDOWS:
            name, tr = WINDOWS[choice]
            write_info_line(f"Selected window: {name} ({tr})")
            return tr

        if choice == "5":
            tr_custom = input(
                "Enter custom timerange (e.g. 20230101-20240601): "
            ).strip()

            if re.fullmatch(r"\d{8}-\d{8}", tr_custom):
                write_info_line(f"Selected custom timerange: {tr_custom}")
                return tr_custom

            write_error_line("Invalid format. Use YYYYMMDD-YYYYMMDD.")
            continue

        write_error_line("Invalid input. Please choose 1-5.")


# =====================================================================================
# Docker command runner
# =====================================================================================
def stream_process_output(cmd):
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
    )

    if process.stdout is None:
        raise RuntimeError("Failed to open process stdout stream.")

    full_output_lines = []
    suppressed_warning_count = 0
    counter_visible = False

    for raw_line in process.stdout:
        full_output_lines.append(raw_line)

        line_clean = strip_ansi(raw_line)

        if is_suppressed_data_warning(line_clean):
            suppressed_warning_count += 1
            print_suppressed_warning_counter(suppressed_warning_count)
            counter_visible = True
            continue

        if counter_visible:
            clear_suppressed_warning_counter()
            counter_visible = False

        colored_line = colorize_log_line(raw_line)
        sys.stdout.write(colored_line + "\n")
        sys.stdout.flush()

    return_code = process.wait()

    if counter_visible:
        clear_suppressed_warning_counter()
        write_warning_line(f"Suppressed data warnings total: {suppressed_warning_count}")

    full_output = "".join(full_output_lines)

    return return_code, full_output


def run_docker_command(
    base_container_name: str,
    timerange: str,
    use_cache: bool,
    disable_max_market_positions: bool,
    enable_position_stacking: bool,
    config_file: str,
):
    ensure_working_directory()

    cache_option = [] if use_cache else ["--cache", "none"]

    max_market_positions_option = (
        ["--disable-max-market-positions"] if disable_max_market_positions else []
    )

    position_stacking_option = (
        ["--enable-position-stacking"] if enable_position_stacking else []
    )

    tried_container_names: Set[str] = set()

    for attempt in range(1, MAX_CONTAINER_NAME_ATTEMPTS + 1):
        container_name = make_unique_container_name(
            base_container_name=base_container_name,
            extra_taken_names=tried_container_names,
        )

        tried_container_names.add(container_name)

        cmd = [
            "docker-compose",
            "run",
            "--name",
            container_name,
            "--rm",
            "freqtrade",
            "backtesting",
            "--config",
            config_file,
            "--data-format-ohlcv",
            "feather",
            "--export",
            "trades",
            "--timerange",
            timerange,
        ] + cache_option + max_market_positions_option + position_stacking_option

        if attempt > 1:
            write_warning_line(
                f"Retrying with new container name: {container_name}"
            )

        write_action_line("Running command: " + " ".join(cmd))

        try:
            return_code, full_output = stream_process_output(cmd)

            if return_code != 0 and output_has_container_name_conflict(full_output):
                write_warning_line(
                    "Docker container name conflict detected. Trying next numbered name..."
                )
                time.sleep(0.25)
                continue

            save_report_to_strategy_file(
                full_output=full_output,
                timerange=timerange,
            )

            if return_code != 0:
                write_warning_line(f"Command exited with code: {return_code}")

            return

        except Exception as e:
            write_error_line(f"Failed to run docker command: {e}")
            return

    write_error_line(
        f"Failed after {MAX_CONTAINER_NAME_ATTEMPTS} container-name attempts."
    )


# =====================================================================================
# Main flow
# =====================================================================================
def main():
    enable_windows_ansi()
    ensure_working_directory()
    ensure_reports_directory()

    backtest = select_backtest_order()

    if not backtest:
        write_error_line("No backtest option selected. Exiting...")
        return

    base_container_name = backtest["BaseContainerName"]
    config_file = backtest["ConfigFile"]

    timerange = select_timerange_window()
    use_cache = DEFAULT_USE_CACHE

    disable_max_market_positions = False
    enable_position_stacking = False

    write_info_line(f"Selected Config: {config_file}")
    write_info_line(f"Timerange: {timerange}")

    run_docker_command(
        base_container_name=base_container_name,
        timerange=timerange,
        use_cache=use_cache,
        disable_max_market_positions=disable_max_market_positions,
        enable_position_stacking=enable_position_stacking,
        config_file=config_file,
    )

    exit_loop = False

    while not exit_loop:
        write_action_line("Select 'retry' (r), 'new' (n), 'window' (w), 'exit' (e)")
        user_input = input().strip().lower()

        if user_input in ("retry", "r"):
            write_tell("Retrying with the same parameters...")

            run_docker_command(
                base_container_name=base_container_name,
                timerange=timerange,
                use_cache=use_cache,
                disable_max_market_positions=disable_max_market_positions,
                enable_position_stacking=enable_position_stacking,
                config_file=config_file,
            )

        elif user_input in ("new", "n"):
            backtest = select_backtest_order()

            if not backtest:
                write_error_line("No backtest option selected. Exiting...")
                return

            base_container_name = backtest["BaseContainerName"]
            config_file = backtest["ConfigFile"]
            timerange = select_timerange_window()
            use_cache = DEFAULT_USE_CACHE
            disable_max_market_positions = False
            enable_position_stacking = False

            write_info_line(f"Selected Container Base: {base_container_name}")
            write_info_line(f"Config File: {config_file}")
            write_info_line(f"Timerange: {timerange}")

            write_warning_line("Running command with selected parameters...")

            run_docker_command(
                base_container_name=base_container_name,
                timerange=timerange,
                use_cache=use_cache,
                disable_max_market_positions=disable_max_market_positions,
                enable_position_stacking=enable_position_stacking,
                config_file=config_file,
            )

        elif user_input in ("window", "w"):
            timerange = select_timerange_window()
            write_info_line(f"Updated timerange to: {timerange}")

        elif user_input in ("exit", "e"):
            write_info_line("Exiting...")
            exit_loop = True

        else:
            write_error_line(
                "Invalid input. Select 'retry' (r), 'new' (n), 'window' (w), or 'exit' (e)."
            )


if __name__ == "__main__":
    main()