# Freqtrade AIO Toolkit

A practical Freqtrade toolkit with two main parts:

| Part                                              | Purpose                                                                                                                                                                    |
| ------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Windows Freqtrade AIO UI Tool**                 | Main tool for running Docker-based Freqtrade Backtest, Hyperopt, Analysis, Data commands, job tracking, logs, saved defaults, and report opening.                          |
| **Raspberry Pi OS / Debian-Based Server Toolkit** | Optional server setup scripts for preparing live/dry-run Freqtrade machines with systemd, Tailscale, UFW, Netdata, ZRAM, fan control, maintenance timers, and pre-configs. |

The repository is built to reduce repeated command editing and make Freqtrade workflows cleaner, faster, and easier to repeat.

---

## 1. Windows Freqtrade AIO UI Tool

The AIO UI is the main helper in this repository.

It is designed for a Windows Freqtrade/Docker workstation where repeated Docker commands are used for:

- Backtesting
- Hyperopt
- Lookahead analysis
- Recursive analysis
- Data downloading
- Data audits/listing
- Opening generated reports/logs
- Tracking detached jobs

The goal is simple:

> Select options → generate the correct Docker command → run the job → track/open the result.

---

## AIO UI Features

| Feature                   | Description                                                                                                          |
| ------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| **Dark UI**               | Compact dark interface with tabs and scrollbars for smaller screens.                                                 |
| **Backtest**              | Builds and runs `freqtrade backtesting` commands.                                                                    |
| **Hyperopt**              | Builds and runs `freqtrade hyperopt` commands with spaces, workers, epochs, loss function, and random-state options. |
| **Analysis**              | Builds and runs `lookahead-analysis` and `recursive-analysis`.                                                       |
| **Data**                  | Builds and runs `download-data`, `list-data`, and timerange listing commands.                                        |
| **Paths**                 | Lets output folders be configured from the UI.                                                                       |
| **Jobs**                  | Tracks running/history jobs, follows logs, refreshes status, and opens related output files.                         |
| **Saved defaults**        | Saves common values so the same options do not need to be reselected every run.                                      |
| **Detached jobs**         | Docker/CMD jobs can continue after the main UI is closed.                                                            |
| **Portable project root** | The Freqtrade project folder can be changed and saved.                                                               |
| **Clean state JSON**      | Settings are saved compactly without storing large generated pairlists.                                              |

---

## AIO UI Tabs

| Tab          | Main use                                                                                            |
| ------------ | --------------------------------------------------------------------------------------------------- |
| **Backtest** | Timerange presets, cache toggle, max-market-position toggle, position stacking, and report opening. |
| **Hyperopt** | Spaces, epochs, workers, loss selection, seed presets, and output extraction.                       |
| **Analysis** | Lookahead/recursive analysis with config, recommended, or manual pair modes.                        |
| **Data**     | Download/list market data, validate timeframes, and open audit files.                               |
| **Paths**    | Configure output folders for reports, raw logs, extracts, and audits.                               |
| **Jobs**     | Track running/history jobs and open related logs/results.                                           |

---

## AIO Output Folders

| Output type               | Default folder                             |
| ------------------------- | ------------------------------------------ |
| Backtest reports          | `user_data/backtest_reports`               |
| Backtest raw logs         | `user_data/logs/backtest_raw_output`       |
| Hyperopt raw logs         | `user_data/logs/hyperopt_raw_output`       |
| Hyperopt extracts         | `user_data/hyperopt_extracts`              |
| Analysis raw logs         | `user_data/logs/analysis_raw_output`       |
| Analysis extracts         | `user_data/analysis_extracts`              |
| Data raw logs             | `user_data/logs/data_raw_output`           |
| Data audit/list CSV files | `user_data/data/data_audit`                |
| AIO state/jobs            | `user_data/tools/Main_Py/Freqtrade_AIO_UI` |

---

## AIO State and Jobs

The AIO tool stores settings inside the Freqtrade project:

```text
user_data/tools/Main_Py/Freqtrade_AIO_UI/Freqtrade_AIO_UI_state.json
user_data/tools/Main_Py/Freqtrade_AIO_UI/jobs/Freqtrade_AIO_UI_jobs.json
```

The state file stores:

```text
project_root
startup_use_defaults
current settings
saved defaults
path settings
```

Generated pairlists are not saved unless the pair source is manual. This keeps the state file smaller and avoids repeated giant `analysis_pairs` entries.

Job history is kept in one compact registry file instead of creating one JSON file per job.

---

## Hyperopt Random-State Options

| Option                         | Behaviour                                                    |
| ------------------------------ | ------------------------------------------------------------ |
| `AUTO`                         | No `--random-state`; Freqtrade/Optuna chooses automatically. |
| `CUSTOM`                       | Unlocks seed input and uses the typed seed.                  |
| `7`, `42`, `101`, `202`, `909` | Locks seed input and adds that fixed `--random-state`.       |

---

## Recursive Analysis Pair Modes

Recursive analysis uses **per-pair execution only**. The old single all-pairs command mode was removed because it can fail too easily with recursive analysis.

| Pair source                  | Behaviour                                                                               |
| ---------------------------- | --------------------------------------------------------------------------------------- |
| `CONFIG_PAIRLIST_DOWNLOADED` | Uses selected config pairlist and downloaded data. Pairs field is generated and locked. |
| `RECOMMENDED`                | Uses `BTC/USDT ETH/USDT SOL/USDT XRP/USDT`. Pairs field is generated and locked.        |
| `MANUAL`                     | Unlocks the pairs field so pairs can be typed manually.                                 |

| Run mode                  | Behaviour                                                 |
| ------------------------- | --------------------------------------------------------- |
| `cmd_per_pair_parallel`   | One command per pair with slot-refill parallel execution. |
| `cmd_per_pair_sequential` | One command per pair, one at a time.                      |

| Display mode    | Behaviour                         |
| --------------- | --------------------------------- |
| `silent`        | No visible CMD controller window. |
| `minimized_cmd` | Opens minimized controller CMD.   |
| `visible_cmd`   | Opens visible controller CMD.     |

---

## Running the AIO UI from Python

Example source location:

```text
user_data/tools/Main_Py/To Build/Freqtrade_All_In_One_UI.py
```

Run with console:

```bat
python Freqtrade_All_In_One_UI.py
```

Run without the main Python console:

```bat
pythonw Freqtrade_All_In_One_UI.py
```

Or use the `.pyw` copy:

```bat
Freqtrade_AIO_UI.pyw
```

---

## Building the AIO UI EXE

Build script location example:

```text
user_data/tools/Main_Py/To Build/build_Freqtrade_AIO_UI_EXE.bat
```

Expected output:

```text
dist/Freqtrade_AIO_UI.exe
```

The build script is intended to:

- Start from its own folder
- Auto-detect available Python
- Build a one-file windowed executable
- Avoid the `To Build` folder-space issue by using a temporary no-space build folder
- Keep child CMD jobs working even when the main UI has no console window

---

## AIO Project Folder Detection

The selected Freqtrade project folder should contain one or more of:

```text
user_data
docker-compose.yml
docker-compose.yaml
compose.yml
compose.yaml
```

The project folder can be changed inside the UI with:

```text
Change project folder
```

---

# 2. Raspberry Pi OS / Debian-Based Server Toolkit

The server toolkit is mainly intended for **Raspberry Pi OS** and other **Debian-based systems** using `apt` and `systemd`.

Other Linux distributions may need adjustments, especially systems that do not use `apt`, do not use `systemd`, or have different boot/GPIO paths.

The server scripts are designed to auto-detect the Linux user instead of requiring a hardcoded username.

User detection priority:

```text
FT_USER override → SUDO_USER → USER → id -un
```

Normal use:

```bash
bash main.sh
```

Manual override if needed:

```bash
FT_USER=youruser bash main.sh
```

The detected user home folder is used for paths such as:

```text
$HOME/Scripts
$HOME/Servers
$HOME/Fan
$HOME/Servers/Freqtrade
```

---

## Server Toolkit Features

| Area              | Included                                                                 |
| ----------------- | ------------------------------------------------------------------------ |
| **Freqtrade**     | Install under `$HOME/Servers/Freqtrade`.                                 |
| **Services**      | Multi-instance systemd services using `start-1.sh` through `start-8.sh`. |
| **Remote access** | Tailscale setup.                                                         |
| **Firewall**      | UFW rules for detected LAN subnet, Tailscale, SSH, and Freqtrade ports.  |
| **Monitoring**    | Netdata parent/child setup.                                              |
| **Swap**          | ZRAM and fallback swapfile.                                              |
| **Fan**           | Raspberry Pi software-controlled 3-wire fan service.                     |
| **Maintenance**   | Weekly Debian update and Freqtrade log cleanup timers.                   |
| **Configs**       | Pre-config files and private templates.                                  |

---

## Server Entry Point

Main setup script:

```bash
main.sh
```

Recommended run:

```bash
cd "$HOME/Scripts"
bash main.sh
```

Manual user override:

```bash
FT_USER=youruser bash main.sh
```

---

## Expected Server Folder Layout

```text
/home/<user>/
├── Scripts/
│   ├── main.sh
│   ├── cleanup_logs.sh
│   ├── deb_update.sh
│   ├── fan_install.sh
│   ├── firewall_setup.sh
│   ├── freq_install.sh
│   ├── freq_services.sh
│   ├── netdata_parent_install.sh
│   ├── stats_install.sh
│   ├── tail_install.sh
│   └── zram_install.sh
│
├── Servers/
│   ├── start-1.sh
│   ├── start-2.sh
│   ├── start-3.sh
│   ├── start-4.sh
│   ├── start-5.sh
│   ├── start-6.sh
│   ├── start-7.sh
│   ├── start-8.sh
│   └── Freqtrade/
│       └── user_data/
│
└── Fan/
    ├── fan-control.service
    └── fan_ctrl.py
```

---

## Server Quick Start

```bash
mkdir -p "$HOME/Scripts"
cd "$HOME/Scripts"

chmod +x *.sh
chmod +x "$HOME"/Servers/start-*.sh 2>/dev/null || true

bash main.sh
```

If running as root or if user detection is wrong:

```bash
FT_USER=youruser bash main.sh
```

---

## Main Setup Flow

`main.sh` does the following:

| Step | Action                                                 |
| ---: | ------------------------------------------------------ |
|    1 | Makes the scripts folder `.sh` files executable.       |
|    2 | Makes `$HOME/Servers/start-*.sh` executable.           |
|    3 | Checks required maintenance scripts.                   |
|    4 | Creates `/opt/pi-maintenance`.                         |
|    5 | Copies maintenance scripts into `/opt/pi-maintenance`. |
|    6 | Creates cleanup logs service/timer.                    |
|    7 | Creates Debian update service/timer.                   |
|    8 | Enables maintenance timers.                            |
|    9 | Runs fan installer.                                    |
|   10 | Runs Tailscale installer.                              |
|   11 | Runs firewall installer.                               |
|   12 | Runs ZRAM installer.                                   |
|   13 | Runs Netdata child/stats installer.                    |
|   14 | Runs Freqtrade installer.                              |
|   15 | Runs Freqtrade services installer.                     |
|   16 | Prints verification/status output.                     |

---

## Included Server Scripts

| Script                      | Purpose                                                                                  |
| --------------------------- | ---------------------------------------------------------------------------------------- |
| `main.sh`                   | All-in-one setup runner with automatic user/home detection.                              |
| `cleanup_logs.sh`           | Removes old `freq-*.log` files from `$HOME/Servers/Freqtrade/user_data/logs`.            |
| `deb_update.sh`             | Runs Debian update, full-upgrade, fix-broken, autoremove, and clean.                     |
| `fan_install.sh`            | Installs fan control and frees GPIO14/UART0 TX for control signal.                       |
| `tail_install.sh`           | Installs/enables Tailscale and runs `tailscale up`.                                      |
| `firewall_setup.sh`         | Configures UFW for detected LAN SSH, detected LAN Freqtrade ports, and Tailscale access. |
| `zram_install.sh`           | Configures ZRAM using `zstd` and creates fallback `/swapfile`.                           |
| `stats_install.sh`          | Installs Tailscale + Netdata as a child node and streams metrics to parent.              |
| `netdata_parent_install.sh` | Configures a Netdata parent node and stream API key.                                     |
| `freq_install.sh`           | Installs Freqtrade, checks out stable branch, runs setup, and prepares services.         |
| `freq_services.sh`          | Creates hardened systemd services for `start-1.sh` through `start-8.sh`.                 |

---

## Services and Timers

| Unit                                          | Purpose                                                    |
| --------------------------------------------- | ---------------------------------------------------------- |
| `freqtrade-1.service` → `freqtrade-8.service` | Freqtrade bot instances using `start-1.sh` → `start-8.sh`. |
| `fan-control.service`                         | Software-controlled Raspberry Pi fan.                      |
| `tailscaled.service`                          | Tailscale daemon.                                          |
| `netdata.service`                             | Netdata monitoring agent/parent.                           |
| `zramswap.service`                            | ZRAM compressed swap.                                      |
| `cleanup-logs.timer`                          | Scheduled Freqtrade log cleanup.                           |
| `deb-update.timer`                            | Scheduled Debian package update.                           |

Common commands:

```bash
sudo systemctl daemon-reload
sudo systemctl enable freqtrade-1
sudo systemctl start freqtrade-1
sudo systemctl stop freqtrade-1
sudo systemctl restart freqtrade-1
systemctl status freqtrade-1 --no-pager
journalctl -u freqtrade-1 -f
systemctl list-timers --all
```

---

## Freqtrade Start Scripts

Each Freqtrade service points to one start script:

```text
$HOME/Servers/start-1.sh
$HOME/Servers/start-2.sh
...
$HOME/Servers/start-8.sh
```

Example `start-1.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

cd "$HOME/Servers/Freqtrade"
source ./.venv/bin/activate

freqtrade trade \
  --config user_data/config-1.json
```

Make all start scripts executable:

```bash
chmod +x "$HOME"/Servers/start-*.sh
```

View logs:

```bash
journalctl -u freqtrade-1 -f
```

---

## Raspberry Pi Fan Wiring

Supports a software-controlled 3-wire fan.

```text
Fan red wire   → Raspberry Pi 5V
Fan black wire → Raspberry Pi GND
Fan blue wire  → Raspberry Pi GPIO14 / UART0 TX control signal
```

Example Raspberry Pi header pins:

| Fan wire | Pi pin | Pi function       |
| -------- | -----: | ----------------- |
| Red      |  Pin 4 | 5V power          |
| Black    |  Pin 6 | Ground            |
| Blue     |  Pin 8 | GPIO14 / UART0 TX |

Required files:

```text
$HOME/Fan/fan-control.service
$HOME/Fan/fan_ctrl.py
```

The fan installer patches any old `User=`, `Group=`, or `/home/<user>` references in the fan service file during install, so the service is installed for the detected Linux user.

The fan installer frees GPIO14/UART0 TX from serial console use. Reboot may be required after UART/GPIO changes.

Check fan service:

```bash
systemctl status fan-control.service --no-pager
journalctl -u fan-control.service -n 100 --no-pager
```

---

## Tailscale Access

After setup:

```bash
tailscale ip -4
tailscale status
```

SSH through Tailscale:

```bash
ssh <user>@TAILSCALE_IP
```

Tailscale is used so Freqtrade/API/Netdata access does not need to be exposed directly to the public internet.

---

## Firewall Defaults

The firewall setup uses UFW and auto-detects the LAN subnet from the active default network interface. On a Raspberry Pi using Wi-Fi this is usually `wlan0`; on wired Ethernet this is usually `eth0`. The script avoids treating `tailscale0` as the LAN interface.

| Setting              | Default                          |
| -------------------- | -------------------------------- |
| Incoming traffic     | Denied                           |
| Outgoing traffic     | Allowed                          |
| LAN SSH              | Allowed from detected LAN subnet |
| LAN Freqtrade ports  | Allowed from detected LAN subnet |
| LAN subnet           | Auto-detected                    |
| Freqtrade port range | `8010-8040`                      |
| Tailscale interface  | `tailscale0`                     |

Optional overrides:

```bash
LAN_CIDR=192.168.1.0/24 bash firewall_setup.sh
LAN_IFACE=wlan0 bash firewall_setup.sh
FREQ_PORT_RANGE=8010:8040 bash firewall_setup.sh
TAILSCALE_IFACE=tailscale0 bash firewall_setup.sh
```

Check firewall:

```bash
sudo ufw status verbose
```

---

## ZRAM / Swap

Check status:

```bash
sudo systemctl status zramswap.service --no-pager
swapon --show
cat /proc/swaps
zramctl
```

ZRAM helps small servers handle memory spikes. It is not a replacement for enough physical RAM.

---

## Netdata Parent / Child Monitoring

| Role   | Script                      | Purpose                                               |
| ------ | --------------------------- | ----------------------------------------------------- |
| Parent | `netdata_parent_install.sh` | Receives metric streams from child nodes.             |
| Child  | `stats_install.sh`          | Streams metrics to the Netdata parent over Tailscale. |

Parent:

```bash
bash netdata_parent_install.sh
```

Child:

```bash
bash stats_install.sh
```

Default Netdata port:

```text
19999
```

Check Netdata:

```bash
systemctl status netdata --no-pager
journalctl -u netdata -n 100 --no-pager
```

---

## Freqtrade Pre-Configs

| Config type            | Purpose                                       |
| ---------------------- | --------------------------------------------- |
| Base configs           | Main Freqtrade bot settings.                  |
| Pairlist configs       | Pair filtering and whitelist/blacklist logic. |
| Private templates      | Empty credential templates.                   |
| Multi-instance configs | Separate config files for multiple services.  |
| API/UI configs         | Port/API settings for Freqtrade UI access.    |
| Strategy configs       | Strategy-specific runtime presets.            |

Private config templates should keep secrets blank:

```json
{
  "key": "",
  "secret": "",
  "password": "",
  "jwt_secret_key": "",
  "ws_token": "",
  "username": "",
  "password": ""
}
```

---

## Requirements

### Windows AIO UI

| Requirement                    | Notes                                          |
| ------------------------------ | ---------------------------------------------- |
| Windows                        | Main AIO UI target.                            |
| Docker Desktop / Docker engine | Required for Docker-based Freqtrade commands.  |
| Freqtrade project folder       | Should include `user_data` and a compose file. |
| Python 3                       | Required if running/building from source.      |
| PyInstaller                    | Required only for building the `.exe`.         |

### Raspberry Pi OS / Debian-Based Toolkit

| Requirement                          | Notes                                     |
| ------------------------------------ | ----------------------------------------- |
| Raspberry Pi OS / Debian-based Linux | Server setup target.                      |
| Bash                                 | Scripts are shell-based.                  |
| Git                                  | Used by Freqtrade install.                |
| Python 3                             | Required by Freqtrade and helper scripts. |
| `apt`                                | Debian package manager.                   |
| `systemd`                            | Services and timers.                      |
| Internet access                      | Package/Freqtrade/Tailscale installs.     |
| Sudo access                          | Required for system changes.              |

Suggested:

| Suggested                                 | Why                             |
| ----------------------------------------- | ------------------------------- |
| Raspberry Pi 4 / 5 or Debian-based server | Better reliability/performance. |
| Tailscale account                         | Remote private access.          |
| Existing Freqtrade configs                | Faster deployment.              |
| Enough storage                            | Freqtrade data/logs can grow.   |

---

## Current Status

| Area                                             | Status     |
| ------------------------------------------------ | ---------- |
| Windows AIO UI Tool                              | Main focus |
| Backtest / Hyperopt / Analysis / Data UI helpers | Included   |
| Recursive per-pair analysis mode                 | Included   |
| Detached job tracking and result-file opening    | Included   |
| Raspberry Pi OS / Debian-based setup             | Included   |
| Automatic Linux user/home detection              | Included   |
| Auto-detected LAN subnet firewall setup          | Included   |
| Freqtrade install automation                     | Included   |
| Multi-instance systemd services                  | Included   |
| Tailscale remote access                          | Included   |
| UFW firewall hardening                           | Included   |
| Netdata monitoring and streaming                 | Included   |
| ZRAM + fallback swapfile                         | Included   |
| Software fan control                             | Included   |
| Weekly cleanup/update timers                     | Included   |
| Freqtrade pre-config organisation                | Included   |

Possible future improvements:

| Improvement                   | Reason                                  |
| ----------------------------- | --------------------------------------- |
| Interactive server setup menu | Select only needed Linux components.    |
| Server dry-run mode           | Preview system changes before applying. |
| Config validation             | Catch missing files before install.     |
| Better Pi model detection     | Safer fan/ZRAM defaults.                |
| Automatic backups             | Safer before changing system files.     |
| Cleaner uninstall mode        | Remove services/configs if needed.      |
| More AIO UI report viewers    | Faster browsing of generated output.    |

---

## Notes

Server scripts auto-detect the target Linux user and home directory.

The server scripts are not generic installers for every Linux distribution. They are designed around Raspberry Pi OS / Debian-style systems using:

```text
apt
systemd
/boot/firmware/
/etc/systemd/system/
```

Non-Debian distributions such as Arch, Fedora, Alpine, openSUSE, or non-systemd systems will likely need adjustments.

Override user detection only if needed:

```bash
FT_USER=youruser bash main.sh
```

Override firewall detection only if needed:

```bash
LAN_CIDR=192.168.1.0/24 bash firewall_setup.sh
LAN_IFACE=wlan0 bash firewall_setup.sh
```

Use Tailscale/VPN or strict firewall rules for Freqtrade UI/API access.

---

## Summary

This repository is mainly a **Freqtrade Windows AIO UI + automation toolkit**.

The Windows AIO UI handles repeated Docker-based Freqtrade work: Backtest, Hyperopt, Analysis, Data download/listing, recursive per-pair analysis, job tracking, saved defaults, output paths, and related report opening.

The Raspberry Pi OS / Debian-based scripts prepare live bot machines with Freqtrade services, automatic Linux user detection, auto-detected LAN firewall rules, Tailscale access, Netdata monitoring, ZRAM, maintenance timers, and software-controlled fan support.

---

## License

This project is licensed under the MIT License.

See the `LICENSE` file for details.

Freqtrade itself and any third-party tools or dependencies remain under their own licenses.
