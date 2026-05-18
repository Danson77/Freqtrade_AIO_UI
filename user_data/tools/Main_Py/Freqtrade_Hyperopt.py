#!/usr/bin/env python
import os
import re
import glob
import subprocess
import sys
from datetime import datetime

# =====================================================================================
# Basic colored output
# =====================================================================================
RESET = "\033[0m"
RED = "\033[31m"
WHITE = "\033[37m"
YELLOW = "\033[33m"
GREEN = "\033[32m"
BLUE = "\033[34m"


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
# Config / path constants
# =====================================================================================
PROJECT_ROOT = r"N:\Freqtrade"
CONFIG_FOLDER = "user_data"

HYPEROPTS_FOLDER = os.path.join(PROJECT_ROOT, "user_data", "hyperopts")
EXTRACT_FOLDER = os.path.join(PROJECT_ROOT, "user_data", "hyperopt_extracts")
RAW_OUTPUT_FOLDER = os.path.join(PROJECT_ROOT, "user_data", "logs", "hyperopt_raw_output")

CONTAINER_NAME = "Freqtrade_Hyperopt"

TIME_WINDOWS = {
    "1": ("TRAIN", "20240101-20240701"),
    "2": ("VALID", "20240701-20241001"),
    "3": ("TEST", "20241001-20251201"),
    "4": ("LIVE_CHECK", "20251001-20260410"),
}


# =====================================================================================
# Helpers
# =====================================================================================
def ensure_working_directory():
    if os.getcwd().lower() != PROJECT_ROOT.lower():
        write_warning_line(f"Switching to expected working directory: {PROJECT_ROOT}")
        try:
            os.chdir(PROJECT_ROOT)
        except Exception as e:
            write_error_line(f"Failed to change directory to {PROJECT_ROOT}. {e}")
            sys.exit(1)


def strip_ansi(text: str) -> str:
    text = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", text)
    text = text.replace("\x00", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text


def safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_")
    return cleaned or "unknown"


def extract_strategy_name(text: str) -> str:
    clean = strip_ansi(text)

    patterns = [
        r"strategy_([A-Za-z0-9_]+)_\d{4}-\d{2}-\d{2}",
        r"Dumping parameters to\s+/freqtrade/user_data/strategies/([A-Za-z0-9_]+)\.json",
        r"Loading parameters from file\s+/freqtrade/user_data/strategies/([A-Za-z0-9_]+)\.json",
        r"Dumping parameters to\s+.*?[\\/]+([A-Za-z0-9_]+)\.json",
        r"Loading parameters from file\s+.*?[\\/]+([A-Za-z0-9_]+)\.json",
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


def extract_loaded_strategy_json(text: str) -> str:
    clean = strip_ansi(text)

    m = re.search(
        r"Loading parameters from file\s+(.+?\.json)",
        clean,
        flags=re.IGNORECASE,
    )

    if m:
        return m.group(1).strip()

    return "False"


def extract_effective_hyperopt_loss(text: str, selected_hyperopt_loss: str) -> str:
    clean = strip_ansi(text)

    patterns = [
        r"Using Hyperopt loss class name:\s*([A-Za-z_][A-Za-z0-9_]*)",
        r"Using resolved hyperoptloss\s+([A-Za-z_][A-Za-z0-9_]*)",
        r"--hyperopt-loss\s+([A-Za-z_][A-Za-z0-9_]*)",
    ]

    for pattern in patterns:
        m = re.search(pattern, clean)
        if m:
            return m.group(1)

    return selected_hyperopt_loss


def extract_hyperopt_summary(text: str) -> str:
    clean = strip_ansi(text)

    best_match = re.search(r"Best result:", clean, flags=re.IGNORECASE)

    if best_match:
        before_best = clean[:best_match.start()]
        table_matches = list(
            re.finditer(r"Hyperopt results", before_best, flags=re.IGNORECASE)
        )
        start = table_matches[-1].start() if table_matches else best_match.start()
    else:
        table_matches = list(
            re.finditer(r"Hyperopt results", clean, flags=re.IGNORECASE)
        )

        if not table_matches:
            return ""

        start = table_matches[-1].start()

    summary = clean[start:].strip()

    end_patterns = [
        r"# max_open_trades parameters:\s*\n\s*max_open_trades\s*=\s*.*?(?:\n\s*\n|\Z)",
        r"max_open_trades\s*=\s*.*?(?:\n\s*\n|\Z)",
        r"trailing_only_offset_is_reached\s*=\s*.*?(?:\n\s*\n|\Z)",
    ]

    for pattern in end_patterns:
        m = re.search(pattern, summary, flags=re.DOTALL)
        if m:
            return summary[:m.end()].strip()

    return summary.strip()


def save_raw_output(
    raw_text: str,
    strategy_name: str,
    time_window_label: str,
    timerange: str,
    hyperopt_loss: str,
    random_state: str,
    stamp: str,
) -> str:
    os.makedirs(RAW_OUTPUT_FOLDER, exist_ok=True)

    raw_file = os.path.join(
        RAW_OUTPUT_FOLDER,
        safe_filename(
            f"raw_{strategy_name}_{time_window_label}_{timerange}_{hyperopt_loss}_rs-{random_state}_{stamp}.txt"
        ),
    )

    with open(raw_file, "w", encoding="utf-8", newline="\n") as f:
        f.write(strip_ansi(raw_text) + "\n")

    return raw_file


def save_extract(
    raw_text: str,
    time_window_label: str,
    timerange: str,
    selected_hyperopt_loss: str,
):
    os.makedirs(EXTRACT_FOLDER, exist_ok=True)

    summary = extract_hyperopt_summary(raw_text)

    if not summary:
        write_error_line("Could not find Hyperopt results / Best result in docker logs.")
        return

    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    strategy_name = extract_strategy_name(raw_text)
    random_state = extract_random_state(raw_text)
    effective_hyperopt_loss = extract_effective_hyperopt_loss(raw_text, selected_hyperopt_loss)
    loaded_strategy_json = extract_loaded_strategy_json(raw_text)

    raw_file = save_raw_output(
        raw_text=raw_text,
        strategy_name=strategy_name,
        time_window_label=time_window_label,
        timerange=timerange,
        hyperopt_loss=effective_hyperopt_loss,
        random_state=random_state,
        stamp=stamp,
    )

    metadata = (
        "# Hyperopt Extract Metadata\n"
        f"strategy = {strategy_name}\n"
        f"time_window = {time_window_label}\n"
        f"timerange = {timerange}\n"
        f"hyperopt_loss = {effective_hyperopt_loss}\n"
        f"random_state = {random_state}\n"
        f"strategy_json_loaded = {loaded_strategy_json}\n"
        f"raw_output_file = {raw_file}\n"
        f"created_at = {stamp}\n"
        "\n"
    )

    extract_file = os.path.join(
        EXTRACT_FOLDER,
        safe_filename(
            f"{strategy_name}_{effective_hyperopt_loss}_{stamp}.txt"
        ),
    )

    with open(extract_file, "w", encoding="utf-8", newline="\n") as f:
        f.write(metadata)
        f.write(summary + "\n")

    write_action_line(f"Raw output saved to: {raw_file}")
    write_action_line(f"Hyperopt extract saved to: {extract_file}")


def remove_old_container():
    subprocess.run(
        ["docker", "rm", "-f", CONTAINER_NAME],
        cwd=PROJECT_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def read_container_logs() -> str:
    result = subprocess.run(
        ["docker", "logs", CONTAINER_NAME],
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    return result.stdout or ""


# =====================================================================================
# Config selection
# =====================================================================================
def natural_config_sort_key(path: str):
    name = os.path.basename(path).lower()

    # Makes config-1.json, config-2.json, config-10.json sort correctly
    m = re.match(r"config-(\d+)\.json$", name)
    if m:
        return (0, int(m.group(1)), name)

    # Other config names like config-analysis.json / config-hyperopt.json after numbered ones
    return (1, name)


def get_config_file() -> str:
    ensure_working_directory()

    config_folder_path = os.path.join(PROJECT_ROOT, CONFIG_FOLDER)

    if not os.path.isdir(config_folder_path):
        write_error_line(
            f"Directory '{config_folder_path}' does not exist. Current path: {os.getcwd()}"
        )
        sys.exit(1)

    configs = sorted(
        glob.glob(os.path.join(config_folder_path, "config-*.json")),
        key=natural_config_sort_key,
    )

    if not configs:
        write_error_line(f"No config-*.json files found in '{config_folder_path}'.")
        sys.exit(1)

    while True:
        write_action_line("Available Backtest Configs:")

        for idx, cfg in enumerate(configs, start=1):
            config_name = os.path.basename(cfg)
            write_info_line(f"{idx}. {config_name}")

        choice = input(f"Enter your choice (1-{len(configs)}): ").strip()

        if choice.isdigit():
            index = int(choice)

            if 1 <= index <= len(configs):
                config_name = os.path.basename(configs[index - 1])
                return f"{CONFIG_FOLDER}/{config_name}"

        write_error_line(f"Invalid input. Enter a number between 1 and {len(configs)}.")


# =====================================================================================
# Timerange / time-window selection
# =====================================================================================
def get_custom_timerange() -> tuple[str, str]:
    pattern = re.compile(r"^\d{8}-\d{8}$")

    while True:
        write_action_line("Enter custom timerange, example: 20240101-20250601")
        timerange = input("Custom timerange: ").strip()

        if pattern.match(timerange):
            return "CUSTOM", timerange

        write_error_line("Invalid timerange. Use YYYYMMDD-YYYYMMDD.")


def get_timerange() -> tuple[str, str]:
    while True:
        write_action_line("Choose time-window:")
        write_warning_line("1: TRAIN       20240101-20240701")
        write_warning_line("2: VALID       20240701-20241001")
        write_warning_line("3: TEST        20241001-20251201")
        write_warning_line("4: LIVE_CHECK  20251001-20260410")
        write_warning_line("5: CUSTOM      Manual YYYYMMDD-YYYYMMDD")

        choice = input("Enter your choice: ").strip()

        if choice in TIME_WINDOWS:
            label, timerange = TIME_WINDOWS[choice]
            write_tell(f"Selected {label}: {timerange}")
            return label, timerange

        if choice == "5":
            label, timerange = get_custom_timerange()
            write_tell(f"Selected {label}: {timerange}")
            return label, timerange

        write_error_line("Invalid choice. Enter 1, 2, 3, 4, or 5.")


# =====================================================================================
# Spaces / epochs / workers / loss / random state
# =====================================================================================
def get_spaces() -> str:
    valid_spaces = {
        "all",
        "buy",
        "sell",
        "roi",
        "stoploss",
        "trailing",
        "trades",
        "protection",
        "default",
    }

    while True:
        write_action_line("Choose spaces, separated by space:")
        write_warning_line(
            "buy, sell, stoploss, trailing, roi, trades, protection, all, default"
        )

        spaces_input = input("Spaces: ").strip().lower()
        space_list = [s for s in spaces_input.split() if s]

        if not space_list:
            write_error_line("Enter at least one space.")
            continue

        invalid = [s for s in space_list if s not in valid_spaces]

        if invalid:
            write_error_line(f"Invalid spaces: {', '.join(invalid)}")
            continue

        return " ".join(space_list)


def get_positive_int(prompt: str) -> int:
    while True:
        write_action_line(prompt)
        value = input("> ").strip()

        if value.isdigit() and int(value) > 0:
            return int(value)

        write_error_line("Invalid input. Enter a positive integer.")


def get_epochs() -> int:
    return get_positive_int("Enter the number of epochs (-e):")


def get_workers() -> int:
    return get_positive_int("Enter the number of workers (-j):")


def get_random_state() -> int | None:
    while True:
        write_action_line("Random state option:")
        write_warning_line("1: Auto random state      - Let Freqtrade/Optuna choose automatically")
        write_warning_line("2: Custom random state    - Enter fixed seed for repeatable tests")
        write_warning_line("3: Test Function          - Use --random-state 42")

        choice = input("Enter your choice: ").strip()

        if choice == "1":
            write_tell("Selected: no random state")
            return None

        if choice == "2":
            while True:
                seed = input("Enter random-state number: ").strip()

                if seed.isdigit() and int(seed) >= 0:
                    write_tell(f"Selected random-state: {seed}")
                    return int(seed)

                write_error_line("Invalid random-state. Enter zero or a positive integer.")

        if choice == "3":
            write_tell("Selected random-state: 42")
            return 42

        write_error_line("Invalid choice. Enter 1, 2, or 3.")


def get_hyperopt_loss() -> str:
    losses = {
        "1": "ShortTradeDurHyperOptLoss",
        "2": "OnlyProfitHyperOptLoss",
        "3": "SharpeHyperOptLoss",
        "4": "SharpeHyperOptLossDaily",
        "5": "SortinoHyperOptLoss",
        "6": "SortinoHyperOptLossDaily",
        "7": "MaxDrawDownHyperOptLoss",
        "8": "MaxDrawDownRelativeHyperOptLoss",
        "9": "MaxDrawDownPerPairHyperOptLoss",
        "10": "CalmarHyperOptLoss",
        "11": "ProfitDrawDownHyperOptLoss",
        "12": "MultiMetricHyperOptLoss",
        "13": "Custom",
    }

    while True:
        write_action_line("Choose the hyperopt-loss type:")
        write_warning_line("1:   Short Trade Duration       - Short trade duration and avoiding losses.")
        write_warning_line("2:   Only Profit                - Only total profit.")
        write_warning_line("3:   Sharpe                     - Sharpe Ratio on trade returns.")
        write_warning_line("4:   Sharpe Daily               - Sharpe Ratio on daily trade returns.")
        write_warning_line("5:   Sortino                    - Sortino Ratio on trade returns/downside deviation.")
        write_warning_line("6:   Sortino Daily              - Sortino Ratio on daily returns/downside deviation.")
        write_warning_line("7:   Max DrawDown               - Maximum absolute drawdown.")
        write_warning_line("8:   Max DrawDown Relative      - Absolute drawdown + relative drawdown.")
        write_warning_line("9:   Max DrawDown Per Pair      - Worst pair profit/drawdown ratio.")
        write_warning_line("10:  Calmar                     - Calmar Ratio vs max drawdown.")
        write_warning_line("11:  Profit DrawDown            - Max profit and min drawdown.")
        write_warning_line("12:  Multi Metric               - Profit, drawdown, profit factor, expectancy, winrate, trade count.")
        write_warning_line("13:  Custom Loss Function       - Custom loss from user_data/hyperopts")

        choice = input("Enter your choice: ").strip()

        if choice in losses:
            return losses[choice]

        write_error_line("Invalid choice. Enter a number between 1 and 13.")


def get_custom_hyperopt_loss(folder_path: str):
    write_action_line("Available custom hyperopt loss files:")

    loss_files = sorted(glob.glob(os.path.join(folder_path, "*.py")))

    if not loss_files:
        write_error_line("No custom hyperopt loss files found.")
        return None

    for i, path in enumerate(loss_files, start=1):
        write_warning_line(f"{i}: {os.path.basename(path)}")

    choice = input("Choose custom hyperopt loss file number: ").strip()

    if not choice.isdigit():
        write_error_line("Invalid choice.")
        return None

    index = int(choice)

    if not (1 <= index <= len(loss_files)):
        write_error_line("Invalid choice.")
        return None

    chosen_file = loss_files[index - 1]

    try:
        with open(chosen_file, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        write_error_line(f"Failed to read {chosen_file}: {e}")
        return None

    m = re.search(
        r"class\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(\s*IHyperOptLoss\s*\)\s*:",
        content,
    )

    if not m:
        write_error_line("No class inheriting from IHyperOptLoss found.")
        return None

    return m.group(1)


def resolve_hyperopt_loss(hyperopt_loss: str) -> str:
    if hyperopt_loss != "Custom":
        return hyperopt_loss

    custom_loss = get_custom_hyperopt_loss(HYPEROPTS_FOLDER)

    if not custom_loss:
        write_error_line("No valid custom loss selected.")
        sys.exit(1)

    return custom_loss


# =====================================================================================
# Docker command
# =====================================================================================
def build_hyperopt_command(
    timerange: str,
    spaces: str,
    epochs: int,
    workers: int,
    hyperopt_loss: str,
    config_file: str,
    random_state: int | None,
) -> list[str]:
    spaces_list = [s for s in spaces.split() if s]

    cmd = [
        "docker-compose",
        "run",
        "--name",
        CONTAINER_NAME,
        "freqtrade",
        "hyperopt",
        "--config",
        config_file,
        "--data-format-ohlcv",
        "feather",
        "--timerange",
        timerange,
        "--spaces",
        *spaces_list,
        "-e",
        str(epochs),
        "-j",
        str(workers),
        "--hyperopt-loss",
        hyperopt_loss,
    ]

    if random_state is not None:
        cmd.extend(["--random-state", str(random_state)])

    return cmd


# =====================================================================================
# Main hyperopt runner
# =====================================================================================
def run_docker_command(
    time_window_label: str,
    timerange: str,
    spaces: str,
    epochs: int,
    workers: int,
    hyperopt_loss: str,
    config_file: str,
    random_state: int | None,
):
    ensure_working_directory()

    remove_old_container()

    cmd = build_hyperopt_command(
        timerange=timerange,
        spaces=spaces,
        epochs=epochs,
        workers=workers,
        hyperopt_loss=hyperopt_loss,
        config_file=config_file,
        random_state=random_state,
    )

    write_action_line("Running command:")
    write_action_line(" ".join(cmd))

    try:
        result = subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            check=False,
        )

        raw_logs = read_container_logs()

        if raw_logs.strip():
            save_extract(
                raw_text=raw_logs,
                time_window_label=time_window_label,
                timerange=timerange,
                selected_hyperopt_loss=hyperopt_loss,
            )
        else:
            write_error_line("Docker logs were empty. Nothing to extract.")

        remove_old_container()

        if result.returncode != 0:
            write_error_line(f"Hyperopt finished with exit code: {result.returncode}")

    except KeyboardInterrupt:
        write_warning_line("Interrupted by user.")
        remove_old_container()

    except Exception as e:
        write_error_line(f"Failed to run docker command: {e}")
        remove_old_container()


# =====================================================================================
# Parameter collection
# =====================================================================================
def collect_parameters():
    time_window_label, timerange = get_timerange()
    config_file = get_config_file()
    spaces = get_spaces()
    epochs = get_epochs()
    workers = get_workers()
    random_state = get_random_state()
    hyperopt_loss = resolve_hyperopt_loss(get_hyperopt_loss())

    return (
        time_window_label,
        timerange,
        config_file,
        spaces,
        epochs,
        workers,
        random_state,
        hyperopt_loss,
    )


# =====================================================================================
# Main flow
# =====================================================================================
def main():
    ensure_working_directory()

    (
        time_window_label,
        timerange,
        config_file,
        spaces,
        epochs,
        workers,
        random_state,
        hyperopt_loss,
    ) = collect_parameters()

    run_docker_command(
        time_window_label=time_window_label,
        timerange=timerange,
        spaces=spaces,
        epochs=epochs,
        workers=workers,
        hyperopt_loss=hyperopt_loss,
        config_file=config_file,
        random_state=random_state,
    )

    while True:
        write_action_line(
            "Type 'retry'/'r' to use same parameters, 'new'/'n' for new parameters, or 'exit'/'e' to close."
        )

        user_input = input("> ").strip().lower()

        aliases = {
            "retry": "r",
            "new": "n",
            "exit": "e",
        }

        user_input = aliases.get(user_input, user_input)

        if user_input == "r":
            write_tell("Retrying with same parameters...")

            run_docker_command(
                time_window_label=time_window_label,
                timerange=timerange,
                spaces=spaces,
                epochs=epochs,
                workers=workers,
                hyperopt_loss=hyperopt_loss,
                config_file=config_file,
                random_state=random_state,
            )

        elif user_input == "n":
            (
                time_window_label,
                timerange,
                config_file,
                spaces,
                epochs,
                workers,
                random_state,
                hyperopt_loss,
            ) = collect_parameters()

            write_warning_line("Running command with new parameters...")

            run_docker_command(
                time_window_label=time_window_label,
                timerange=timerange,
                spaces=spaces,
                epochs=epochs,
                workers=workers,
                hyperopt_loss=hyperopt_loss,
                config_file=config_file,
                random_state=random_state,
            )

        elif user_input == "e":
            write_info_line("Exiting...")
            break

        else:
            write_error_line("Invalid input. Type retry, new, or exit.")


if __name__ == "__main__":
    main()