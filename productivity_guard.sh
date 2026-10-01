#!/bin/bash
#
# productivity_guard.sh
# Monitors Steam and nags/force-closes it after configurable time thresholds.
# Written for macOS Sonoma 14.7's default /bin/bash (bash 3.2) - no bash 4+ features.

STATE_FILE="/tmp/steam_timer_start"
FLAG_FILE="/tmp/steam_timer_fired"

# Playtime stats live inside the repo (gitignored) so everything stays
# contained in one place instead of scattered across /tmp and dotfiles.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DATA_DIR="$SCRIPT_DIR/data"
PLAYTIME_FILE="$DATA_DIR/playtime.json"

# Steam's macOS client process is named "steam_osx" (Contents/MacOS/steam_osx
# inside Steam.AppBundle), not "steam". Its helper processes are named
# "Steam Helper", not "steamwebhelper". Verify on your machine with:
#   ps -axo comm | grep -i steam
STEAM_PROCESS="steam_osx"
STEAM_HELPER_PROCESS="Steam Helper"

# Matches any currently running game launched from Steam's library, e.g.
# .../Steam/steamapps/common/Ticket to Ride/TicketToRide.app/... -- this is
# Steam's standard install layout, so it catches any game, not just one title.
GAME_PROCESS_PATTERN="/steamapps/common/"

# Thresholds in minutes. Lower these for testing (see README.md).
WARN_MINUTES_1=5
WARN_MINUTES_2=6
WARN_MINUTES_3=7
KILL_MINUTES=8

# How long the final dialog is shown before the kill actually happens.
KILL_WARNING_SECONDS=20

DIALOG_TITLE="Productivity Guard"

# First name for personalized messages, e.g. "Bradley Dettmer" -> "Bradley".
# Falls back to the short login name if the full name can't be read.
USER_NAME="$(id -F 2>/dev/null | awk '{print $1}')"
if [ -z "$USER_NAME" ]; then
    USER_NAME="$(whoami)"
fi

notify() {
    local message="$1"
    # Run async (&) so launchd never blocks waiting on the dialog.
    osascript -e "display dialog \"Hey ${USER_NAME}, ${message}\" with title \"${DIALOG_TITLE}\" with icon caution giving up after 30" &
}

# Formats a minute count as "Xh Ym" once it passes an hour, else "Xm".
format_minutes() {
    local total_min="$1"
    local h=$(( total_min / 60 ))
    local m=$(( total_min % 60 ))
    if [ "$h" -gt 0 ]; then
        echo "${h}h ${m}m"
    else
        echo "${m}m"
    fi
}

# "Oct 1, 2026" from a "2026-10-01" date.
format_date_long() {
    date -j -f "%Y-%m-%d" "$1" "+%b %-d, %Y" 2>/dev/null
}

# Name of the currently running game, e.g. "Ticket to Ride", taken from the
# folder Steam installs it under (.../steamapps/common/<Game Name>/...).
# Empty if no game is currently running (e.g. Steam client open, idle).
current_game_name() {
    local full_path
    full_path="$(pgrep -fl "$GAME_PROCESS_PATTERN" 2>/dev/null | head -1 | sed -E 's/^[0-9]+ //')"
    if [ -n "$full_path" ]; then
        echo "$full_path" | sed -E 's#.*/steamapps/common/([^/]+)/.*#\1#'
    fi
}

# Adds one minute (this tick) to today's and the all-time running total,
# resetting the daily count on a new calendar day. START_DATE never changes
# once set. Sets DAILY_MINUTES, TOTAL_MINUTES, and START_DATE for the caller.
update_playtime() {
    local today
    today="$(date +%Y-%m-%d)"
    local game
    game="$(current_game_name)"

    DAILY_MINUTES=0
    TOTAL_MINUTES=0
    START_DATE="$today"

    if [ -f "$PLAYTIME_FILE" ]; then
        local file_date
        file_date="$(sed -E 's/.*"date":"([^"]*)".*/\1/' "$PLAYTIME_FILE")"
        local file_daily
        file_daily="$(sed -E 's/.*"daily_minutes":([0-9]+).*/\1/' "$PLAYTIME_FILE")"
        local file_total
        file_total="$(sed -E 's/.*"total_minutes":([0-9]+).*/\1/' "$PLAYTIME_FILE")"
        local file_start
        file_start="$(sed -E 's/.*"start_date":"([^"]*)".*/\1/' "$PLAYTIME_FILE")"

        if [[ "$file_total" =~ ^[0-9]+$ ]]; then
            TOTAL_MINUTES="$file_total"
        fi
        if [ "$file_date" = "$today" ] && [[ "$file_daily" =~ ^[0-9]+$ ]]; then
            DAILY_MINUTES="$file_daily"
        fi
        if [[ "$file_start" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
            START_DATE="$file_start"
        fi
    fi

    DAILY_MINUTES=$(( DAILY_MINUTES + 1 ))
    TOTAL_MINUTES=$(( TOTAL_MINUTES + 1 ))

    mkdir -p "$DATA_DIR"
    echo "{\"start_date\":\"${START_DATE}\",\"date\":\"${today}\",\"daily_minutes\":${DAILY_MINUTES},\"total_minutes\":${TOTAL_MINUTES},\"game\":\"${game}\"}" > "$PLAYTIME_FILE"
}

# "Active" means the Steam client OR a game launched from it is running.
# Quitting the client UI doesn't kill an already-running game on macOS, so
# checking steam_osx alone would let a game run forever once Steam quits.
steam_active() {
    pgrep -x "$STEAM_PROCESS" > /dev/null 2>&1 && return 0
    pgrep -f "$GAME_PROCESS_PATTERN" > /dev/null 2>&1 && return 0
    return 1
}

# Prints current timer state and exits, without touching playtime stats or
# firing any dialogs. Invoked via `./productivity_guard.sh status`.
print_status() {
    if ! steam_active; then
        echo "Steam/game: not running"
        exit 0
    fi

    local label
    label="$(current_game_name)"
    [ -z "$label" ] && label="Steam"
    echo "Steam/game: ACTIVE (${label})"

    if [ ! -f "$STATE_FILE" ]; then
        echo "Timer: not started yet (starts on next run, within 60s)"
        exit 0
    fi

    local start now elapsed elapsed_min fired kill_at to_kill
    start="$(cat "$STATE_FILE")"
    now=$(date +%s)
    elapsed=$(( now - start ))
    elapsed_min=$(( elapsed / 60 ))
    fired="none"
    [ -f "$FLAG_FILE" ] && [ -s "$FLAG_FILE" ] && fired="$(cat "$FLAG_FILE")"

    echo "Running for: $(format_minutes "$elapsed_min") (${elapsed}s)"
    echo "Warnings fired: ${fired}"

    kill_at=$(( start + KILL_MINUTES * 60 ))
    to_kill=$(( kill_at - now ))
    if [ "$to_kill" -le 0 ]; then
        echo "Kill threshold: already passed $(( -to_kill ))s ago -- should fire on next run (within 60s)"
    else
        echo "Time to kill: ${to_kill}s (~$(( (to_kill + 59) / 60 ))m)"
    fi
    exit 0
}

if [ "$1" = "status" ]; then
    print_status
fi

# Not running: clear all state and exit.
if ! steam_active; then
    rm -f "$STATE_FILE" "$FLAG_FILE"
    exit 0
fi

update_playtime
PLAYTIME_SUMMARY="Played ${DAILY_MINUTES}m today, $(format_minutes "$TOTAL_MINUTES") total since $(format_date_long "$START_DATE")."

# Name the actual game in messages when one is running (e.g. "Ticket to
# Ride"), falling back to "Steam" if only the client itself is active.
ACTIVE_LABEL="$(current_game_name)"
if [ -z "$ACTIVE_LABEL" ]; then
    ACTIVE_LABEL="Steam"
fi

NOW=$(date +%s)

# First sighting: record launch time and reset fired-alert tracking.
if [ ! -f "$STATE_FILE" ]; then
    echo "$NOW" > "$STATE_FILE"
    : > "$FLAG_FILE"
    exit 0
fi

START=$(cat "$STATE_FILE")
if ! [[ "$START" =~ ^[0-9]+$ ]]; then
    echo "$NOW" > "$STATE_FILE"
    START=$NOW
fi

ELAPSED=$(( NOW - START ))
ELAPSED_MIN=$(( ELAPSED / 60 ))

FIRED=""
if [ -f "$FLAG_FILE" ]; then
    FIRED=$(cat "$FLAG_FILE")
fi

fire_once() {
    local tag="$1"
    local message="$2"
    case ",$FIRED," in
        *",$tag,"*)
            ;;
        *)
            notify "$message"
            FIRED="${FIRED}${tag},"
            echo "$FIRED" > "$FLAG_FILE"
            ;;
    esac
}

if [ "$ELAPSED_MIN" -ge "$KILL_MINUTES" ]; then
    notify "${ACTIVE_LABEL} has been running for ${KILL_MINUTES} minutes. Closing it in ${KILL_WARNING_SECONDS} seconds. ${PLAYTIME_SUMMARY}"
    sleep "$KILL_WARNING_SECONDS"
    pkill -9 -f "$GAME_PROCESS_PATTERN" 2>/dev/null
    pkill -9 -x "$STEAM_PROCESS" 2>/dev/null
    pkill -9 -x "$STEAM_HELPER_PROCESS" 2>/dev/null
    rm -f "$STATE_FILE" "$FLAG_FILE"
    exit 0
elif [ "$ELAPSED_MIN" -ge "$WARN_MINUTES_3" ]; then
    fire_once "15" "${ACTIVE_LABEL} has been running for ${WARN_MINUTES_3} minutes. It will be closed at ${KILL_MINUTES} minutes. ${PLAYTIME_SUMMARY}"
elif [ "$ELAPSED_MIN" -ge "$WARN_MINUTES_2" ]; then
    fire_once "10" "${ACTIVE_LABEL} has been running for ${WARN_MINUTES_2} minutes. It will be closed at ${KILL_MINUTES} minutes. ${PLAYTIME_SUMMARY}"
elif [ "$ELAPSED_MIN" -ge "$WARN_MINUTES_1" ]; then
    fire_once "5" "${ACTIVE_LABEL} has been running for ${WARN_MINUTES_1} minutes. It will be closed at ${KILL_MINUTES} minutes. ${PLAYTIME_SUMMARY}"
fi

exit 0
