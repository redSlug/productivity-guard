#!/bin/bash
#
# stop_steam.sh
# Monitors Steam and nags/force-closes it after configurable time thresholds.
# Written for macOS Sonoma 14.7's default /bin/bash (bash 3.2) - no bash 4+ features.

STATE_FILE="/tmp/steam_timer_start"
FLAG_FILE="/tmp/steam_timer_fired"

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
WARN_MINUTES_2=10
WARN_MINUTES_3=15
KILL_MINUTES=20

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

# Not running: clear all state and exit.
if ! pgrep -x "$STEAM_PROCESS" > /dev/null 2>&1; then
    rm -f "$STATE_FILE" "$FLAG_FILE"
    exit 0
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
    notify "Steam has been running for ${KILL_MINUTES} minutes. Closing it now."
    sleep 1
    pkill -9 -f "$GAME_PROCESS_PATTERN" 2>/dev/null
    pkill -9 -x "$STEAM_PROCESS" 2>/dev/null
    pkill -9 -x "$STEAM_HELPER_PROCESS" 2>/dev/null
    rm -f "$STATE_FILE" "$FLAG_FILE"
    exit 0
elif [ "$ELAPSED_MIN" -ge "$WARN_MINUTES_3" ]; then
    fire_once "15" "Steam has been running for ${WARN_MINUTES_3} minutes. It will be closed at ${KILL_MINUTES} minutes."
elif [ "$ELAPSED_MIN" -ge "$WARN_MINUTES_2" ]; then
    fire_once "10" "Steam has been running for ${WARN_MINUTES_2} minutes. It will be closed at ${KILL_MINUTES} minutes."
elif [ "$ELAPSED_MIN" -ge "$WARN_MINUTES_1" ]; then
    fire_once "5" "Steam has been running for ${WARN_MINUTES_1} minutes. It will be closed at ${KILL_MINUTES} minutes."
fi

exit 0
