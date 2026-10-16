#!/usr/bin/env python3
import datetime
import json
import os
import re
import subprocess
import sys
import tempfile
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

SESSION_FILE = "/tmp/steam_timer_session.json"

DATA_DIR = os.path.join(SCRIPT_DIR, "data")
PLAYTIME_FILE = os.path.join(DATA_DIR, "playtime.json")

CONFIG_FILE = os.path.join(SCRIPT_DIR, "config.json")

STEAM_PROCESS = "steam_osx"
STEAM_HELPER_PROCESS = "Steam Helper"

GAME_PROCESS_PATTERN = "/steamapps/common/"

with open(CONFIG_FILE) as f:
    _config = json.load(f)

SESSION_WARN_MINUTES_1 = _config["session_warn_minutes_1"]
SESSION_WARN_MINUTES_2 = _config["session_warn_minutes_2"]
SESSION_WARN_MINUTES_3 = _config["session_warn_minutes_3"]
SESSION_KILL_MINUTES = _config["session_kill_minutes"]
KILL_WARNING_SECONDS = _config["kill_warning_seconds"]
TODAY_ESCALATION_MINUTES = _config["today_escalation_minutes"]
TODAY_ESCALATION_ALERT_INTERVAL = _config["today_escalation_alert_interval"]
TODAY_ESCALATION_KILL_INTERVAL = _config["today_escalation_kill_interval"]
TODAY_HARD_ESCALATION_MINUTES = _config["today_hard_escalation_minutes"]
TODAY_HARD_ESCALATION_KILL_INTERVAL = _config["today_hard_escalation_kill_interval"]

SESSION_WARNING_TIERS = [SESSION_WARN_MINUTES_3, SESSION_WARN_MINUTES_2, SESSION_WARN_MINUTES_1]

DIALOG_TITLE = "Productivity Guard"


def user_name():
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
    subprocess.Popen(["osascript", "-e", script])


def format_minutes(total_minutes):
    h, m = divmod(total_minutes, 60)
    return f"{h}h {m}m" if h else f"{m}m"


def format_date_long(date_str):
    d = datetime.date.fromisoformat(date_str)
    return f"{d.strftime('%b')} {d.day}, {d.year}"


def current_game_name():
    result = subprocess.run(
        ["pgrep", "-fl", GAME_PROCESS_PATTERN], capture_output=True, text=True
    )
    first_line = result.stdout.splitlines()[0] if result.stdout else ""
    match = re.search(r"/steamapps/common/([^/]+)/", first_line)
    return match.group(1) if match else ""


def pgrep_matches(*args):
    return subprocess.run(["pgrep", *args], capture_output=True).returncode == 0


def steam_active():
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


def update_playtime(game, session_start, now):
    today = datetime.date.today().isoformat()
    entries = load_playtime_entries()

    today_entry = next((e for e in entries if e["date"] == today), None)
    if today_entry is None:
        today_entry = {"date": today, "minutes_played": 0, "game": game}
        entries.append(today_entry)

    # Assumes this tick is ~1 real minute after the last one; not guaranteed by launchd,
    # so this can undercount (never overcount) if a tick is missed or delayed.
    today_entry["minutes_played"] += 1
    today_entry["game"] = game

    write_playtime_entries(entries)

    today_minutes = today_entry["minutes_played"]
    session_minutes = (now - session_start) // 60
    total_minutes = sum(e["minutes_played"] for e in entries)
    start_date = min(e["date"] for e in entries)
    return today_minutes, session_minutes, total_minutes, start_date


def playtime_summary(today_minutes, total_minutes, start_date):
    return (
        f"Played {today_minutes}m today, {format_minutes(total_minutes)} total "
        f"since {format_date_long(start_date)}."
    )


def load_session():
    try:
        with open(SESSION_FILE) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(data, dict) and isinstance(data.get("start"), int) and isinstance(data.get("fired"), list):
        return data
    return None


def save_session(start, fired):
    with open(SESSION_FILE, "w") as f:
        json.dump({"start": start, "fired": fired}, f)


def clear_state():
    if os.path.exists(SESSION_FILE):
        os.remove(SESSION_FILE)


def kill_steam():
    subprocess.run(["pkill", "-9", "-f", GAME_PROCESS_PATTERN])
    subprocess.run(["pkill", "-9", "-x", STEAM_PROCESS])
    subprocess.run(["pkill", "-9", "-x", STEAM_HELPER_PROCESS])


def fire(reason, summary, kill, session=None, tag=None):
    if session is not None and tag in session["fired"]:
        return
    if kill:
        notify(f"{reason} Closing it in {KILL_WARNING_SECONDS} seconds. {summary}")
        time.sleep(KILL_WARNING_SECONDS)
        kill_steam()
        clear_state()
        return
    notify(f"{reason} {summary}")
    if session is not None:
        session["fired"].append(tag)
        save_session(session["start"], session["fired"])


def print_status():
    if not steam_active():
        print("Steam/game: not running")
        return

    label = current_game_name() or "Steam"
    print(f"Steam/game: ACTIVE ({label})")

    session = load_session()
    if session is None:
        print("Timer: not started yet (starts on next run, within 60s)")
        return

    now = int(time.time())
    elapsed = now - session["start"]
    elapsed_min = elapsed // 60

    print(f"Running for: {format_minutes(elapsed_min)} ({elapsed}s)")
    print(f"Warnings fired: {', '.join(map(str, session['fired'])) or 'none'}")

    kill_at = session["start"] + SESSION_KILL_MINUTES * 60
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
    active_label = game or "Steam"

    now = int(time.time())
    session = load_session()
    today_minutes, session_minutes, total_minutes, start_date = update_playtime(
        game, session["start"] if session else now, now
    )
    summary = playtime_summary(today_minutes, total_minutes, start_date)

    if session is None:
        save_session(now, [])
        return

    if today_minutes >= TODAY_ESCALATION_MINUTES:
        kill_interval = (
            TODAY_HARD_ESCALATION_KILL_INTERVAL
            if today_minutes >= TODAY_HARD_ESCALATION_MINUTES
            else TODAY_ESCALATION_KILL_INTERVAL
        )
        reason = f"{active_label} has been running a lot today -- {today_minutes} minutes so far."
        if today_minutes % kill_interval == 0:
            fire(reason, summary, kill=True)
        elif today_minutes % TODAY_ESCALATION_ALERT_INTERVAL == 0:
            fire(reason, summary, kill=False)
        return

    if session_minutes >= SESSION_KILL_MINUTES:
        fire(f"{active_label} has been running for {SESSION_KILL_MINUTES} minutes.", summary, kill=True)
        return

    for minutes in SESSION_WARNING_TIERS:
        if session_minutes >= minutes:
            fire(
                f"{active_label} has been running for {minutes} minutes. "
                f"It will be closed at {SESSION_KILL_MINUTES} minutes.",
                summary,
                kill=False,
                session=session,
                tag=minutes,
            )
            break


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "status":
        print_status()
        return
    run()


if __name__ == "__main__":
    main()
