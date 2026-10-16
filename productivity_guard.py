#!/usr/bin/env python3
"""
productivity_guard.py
Monitors Steam and nags/force-closes it after configurable time thresholds.
Run once a minute via launchd (see com.user.productivityguard.plist).
"""
import datetime
import json
import os
import re
import subprocess
import sys
import tempfile
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

STATE_FILE = "/tmp/steam_timer_start"
FLAG_FILE = "/tmp/steam_timer_fired"

# Playtime stats live inside the repo (gitignored) so everything stays
# contained in one place instead of scattered across /tmp and dotfiles.
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
PLAYTIME_FILE = os.path.join(DATA_DIR, "playtime.json")

# Minutes played before this log existed (2026-10-01 through 2026-10-14) were
# never recorded per-day, so that span is a fixed constant -- the log itself
# starts with a real entry for 2026-10-15 and tracks every day after precisely.
TRACKING_START_DATE = "2026-10-01"
HISTORICAL_MINUTES = 1467

# Steam's macOS client process is named "steam_osx" (Contents/MacOS/steam_osx
# inside Steam.AppBundle), not "steam". Its helper processes are named
# "Steam Helper", not "steamwebhelper". Verify on your machine with:
#   ps -axo comm | grep -i steam
STEAM_PROCESS = "steam_osx"
STEAM_HELPER_PROCESS = "Steam Helper"

# Matches any currently running game launched from Steam's library, e.g.
# .../Steam/steamapps/common/Ticket to Ride/TicketToRide.app/... -- this is
# Steam's standard install layout, so it catches any game, not just one title.
GAME_PROCESS_PATTERN = "/steamapps/common/"

# Thresholds in minutes. Lower these for testing (see README.md).
WARN_MINUTES_1 = 10
WARN_MINUTES_2 = 12
WARN_MINUTES_3 = 17
KILL_MINUTES = 18

# (threshold, fire_once tag), highest first -- the tags are just distinct
# identifiers for "has this one fired yet", unrelated to the minute values.
WARNING_TIERS = [(WARN_MINUTES_3, "15"), (WARN_MINUTES_2, "10"), (WARN_MINUTES_1, "5")]

# How long the final dialog is shown before the kill actually happens.
KILL_WARNING_SECONDS = 20

DIALOG_TITLE = "Productivity Guard"


def user_name():
    """First name for personalized messages, e.g. "Bradley Dettmer" -> "Bradley".
    Falls back to the short login name if the full name can't be read."""
    try:
        full = subprocess.run(["id", "-F"], capture_output=True, text=True).stdout.strip()
        if full:
            return full.split()[0]
    except OSError:
        pass
    return subprocess.run(["whoami"], capture_output=True, text=True).stdout.strip()


def notify(message):
    script = (
        f'display dialog "Hey {user_name()}, {message}" '
        f'with title "{DIALOG_TITLE}" with icon caution giving up after 30'
    )
    # Popen (not run) so launchd never blocks waiting on the dialog.
    subprocess.Popen(["osascript", "-e", script])


def format_minutes(total_minutes):
    """Formats a minute count as "Xh Ym" once it passes an hour, else "Xm"."""
    h, m = divmod(total_minutes, 60)
    return f"{h}h {m}m" if h else f"{m}m"


def format_date_long(date_str):
    """"Oct 1, 2026" from a "2026-10-01" date."""
    d = datetime.date.fromisoformat(date_str)
    return f"{d.strftime('%b')} {d.day}, {d.year}"


def current_game_name():
    """Name of the currently running game, e.g. "Ticket to Ride", taken from
    the folder Steam installs it under (.../steamapps/common/<Game Name>/...).
    Empty if no game is currently running (e.g. Steam client open, idle)."""
    result = subprocess.run(
        ["pgrep", "-fl", GAME_PROCESS_PATTERN], capture_output=True, text=True
    )
    first_line = result.stdout.splitlines()[0] if result.stdout else ""
    match = re.search(r"/steamapps/common/([^/]+)/", first_line)
    return match.group(1) if match else ""


def pgrep_matches(*args):
    return subprocess.run(["pgrep", *args], capture_output=True).returncode == 0


def steam_active():
    """"Active" means the Steam client OR a game launched from it is running.
    Quitting the client UI doesn't kill an already-running game on macOS, so
    checking steam_osx alone would let a game run forever once Steam quits."""
    return pgrep_matches("-x", STEAM_PROCESS) or pgrep_matches("-f", GAME_PROCESS_PATTERN)


def load_playtime_entries():
    if not os.path.exists(PLAYTIME_FILE):
        return []
    try:
        with open(PLAYTIME_FILE) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [
        e for e in data
        if isinstance(e, dict) and isinstance(e.get("date"), str)
        and isinstance(e.get("minutes_played"), int)
    ]


def write_playtime_entries(entries):
    os.makedirs(DATA_DIR, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=DATA_DIR)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(entries, f)
        os.replace(tmp_path, PLAYTIME_FILE)
    except Exception:
        os.unlink(tmp_path)
        raise


def update_playtime(game):
    """Adds one minute (this tick) to today's entry in the playtime log,
    appending a new entry when the date rolls over. Returns
    (minutes_played_today, total_minutes_all_time)."""
    today = datetime.date.today().isoformat()
    entries = load_playtime_entries()

    today_entry = next((e for e in entries if e["date"] == today), None)
    if today_entry is None:
        today_entry = {"date": today, "minutes_played": 0, "game": game}
        entries.append(today_entry)

    today_entry["minutes_played"] += 1
    today_entry["game"] = game

    write_playtime_entries(entries)

    minutes_played = today_entry["minutes_played"]
    total_minutes = HISTORICAL_MINUTES + sum(e["minutes_played"] for e in entries)
    return minutes_played, total_minutes


def playtime_summary(minutes_played, total_minutes):
    return (
        f"Played {minutes_played}m today, {format_minutes(total_minutes)} total "
        f"since {format_date_long(TRACKING_START_DATE)}."
    )


def read_fired():
    try:
        with open(FLAG_FILE) as f:
            return f.read().strip()
    except OSError:
        return ""


def fire_once(tag, message, fired):
    """Sends `message` and records `tag` as fired, unless `tag` already was."""
    if f",{tag}," in f",{fired},":
        return fired
    notify(message)
    fired = f"{fired}{tag},"
    with open(FLAG_FILE, "w") as f:
        f.write(fired)
    return fired


def kill_steam():
    subprocess.run(["pkill", "-9", "-f", GAME_PROCESS_PATTERN])
    subprocess.run(["pkill", "-9", "-x", STEAM_PROCESS])
    subprocess.run(["pkill", "-9", "-x", STEAM_HELPER_PROCESS])


def clear_state():
    for path in (STATE_FILE, FLAG_FILE):
        if os.path.exists(path):
            os.remove(path)


def print_status():
    """Prints current timer state and returns, without touching playtime
    stats or firing any dialogs. Invoked via `./productivity_guard.py status`."""
    if not steam_active():
        print("Steam/game: not running")
        return

    label = current_game_name() or "Steam"
    print(f"Steam/game: ACTIVE ({label})")

    try:
        with open(STATE_FILE) as f:
            start = int(f.read().strip())
    except (OSError, ValueError):
        print("Timer: not started yet (starts on next run, within 60s)")
        return

    now = int(time.time())
    elapsed = now - start
    elapsed_min = elapsed // 60
    fired = read_fired() or "none"

    print(f"Running for: {format_minutes(elapsed_min)} ({elapsed}s)")
    print(f"Warnings fired: {fired}")

    kill_at = start + KILL_MINUTES * 60
    to_kill = kill_at - now
    if to_kill <= 0:
        print(f"Kill threshold: already passed {-to_kill}s ago -- should fire on next run (within 60s)")
    else:
        print(f"Time to kill: {to_kill}s (~{(to_kill + 59) // 60}m)")


def run():
    if not steam_active():
        clear_state()
        return

    game = current_game_name()
    minutes_played, total_minutes = update_playtime(game)
    summary = playtime_summary(minutes_played, total_minutes)
    active_label = game or "Steam"

    now = int(time.time())

    # First sighting: record launch time and reset fired-alert tracking.
    if not os.path.exists(STATE_FILE):
        with open(STATE_FILE, "w") as f:
            f.write(str(now))
        with open(FLAG_FILE, "w") as f:
            f.write("")
        return

    try:
        with open(STATE_FILE) as f:
            start = int(f.read().strip())
    except (OSError, ValueError):
        start = now
        with open(STATE_FILE, "w") as f:
            f.write(str(now))

    elapsed_min = (now - start) // 60
    fired = read_fired()

    if elapsed_min >= KILL_MINUTES:
        notify(
            f"{active_label} has been running for {KILL_MINUTES} minutes. "
            f"Closing it in {KILL_WARNING_SECONDS} seconds. {summary}"
        )
        time.sleep(KILL_WARNING_SECONDS)
        kill_steam()
        clear_state()
        return

    # Highest tier first, so e.g. crossing WARN_MINUTES_3 on the first check
    # after launch fires only that tier's alert, not all three.
    for minutes, tag in WARNING_TIERS:
        if elapsed_min >= minutes:
            fire_once(
                tag,
                f"{active_label} has been running for {minutes} minutes. "
                f"It will be closed at {KILL_MINUTES} minutes. {summary}",
                fired,
            )
            break


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "status":
        print_status()
        return
    run()


if __name__ == "__main__":
    main()
