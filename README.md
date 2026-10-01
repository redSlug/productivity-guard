# stop-steam

A macOS LaunchAgent that watches for Steam and nags/force-quits it after a
time limit. Tested for compatibility with **macOS Sonoma 14.7**.

## What it does

`stop_steam.sh` runs once a minute (via launchd) and checks whether the
`steam` process is active:

- When Steam starts, it records the launch time in `/tmp/steam_timer_start`.
- At **5, 10, and 15 minutes**, it pops up a modal alert (via `osascript`)
  warning that Steam will be closed soon. Each alert fires only once per
  Steam session and auto-dismisses after 30 seconds if ignored.
- At **20 minutes**, it shows a final alert and force-terminates the Steam
  client (`steam_osx`, `Steam Helper`) with `pkill -9`, along with any game
  currently running from Steam's library (matched by `/steamapps/common/`
  in the process path, so this covers any title, not just one game).
- If Steam isn't running, all timer state is cleared so the next launch
  starts a fresh countdown.

## Prerequisites

- macOS Sonoma 14.7 (or later) with the default `/bin/bash` (bash 3.2).
- Steam installed. On macOS, Steam's client process is named `steam_osx`
  (not `steam`) and its helpers are named `Steam Helper` (not
  `steamwebhelper`) — confirm on your machine with
  `ps -axo comm | grep -i steam` while Steam is running. If your install
  reports different names, update `STEAM_PROCESS` / `STEAM_HELPER_PROCESS`
  at the top of `stop_steam.sh` to match.
- You may need to grant your terminal/launchd's `osascript` permission to
  show notifications/dialogs the first time it runs (System Settings →
  Privacy & Security → Automation / Notifications).

## Manual installation (launchctl)

1. Make the script executable:
   ```bash
   chmod +x stop_steam.sh
   ```
2. Copy the plist into your LaunchAgents directory, substituting the real
   path to `stop_steam.sh` (plists can't expand `~`):
   ```bash
   sed "s|__SCRIPT_PATH__|$HOME/Development/stop-steam/stop_steam.sh|g" \
       com.user.stopsteam.plist > ~/Library/LaunchAgents/com.user.stopsteam.plist
   ```
3. Load it:
   ```bash
   launchctl load ~/Library/LaunchAgents/com.user.stopsteam.plist
   ```
4. Verify it's loaded:
   ```bash
   launchctl list | grep com.user.stopsteam
   ```

## Automated installation

```bash
./install.sh
```

This substitutes the correct absolute path into the plist, copies it to
`~/Library/LaunchAgents/`, and loads it with `launchctl`. Safe to re-run
(it unloads any previous copy first).

## Verifying it's installed and running

Quick checks to confirm the LaunchAgent is actually active, without
waiting for a Steam session:

```bash
# Is it loaded? ("-" in the PID column just means it's idle between runs,
# not that it's broken. The number after it is the last exit code.)
launchctl list | grep com.user.stopsteam

# Full status: confirms the script path launchd is using, how many times
# it has run, and its last exit code (0 = success).
launchctl print gui/$(id -u)/com.user.stopsteam

# Any errors logged by the script or launchd itself?
cat /tmp/com.user.stopsteam.out.log
cat /tmp/com.user.stopsteam.err.log

# Current timer state (only present while Steam is running):
cat /tmp/steam_timer_start    # epoch seconds Steam was first seen
cat /tmp/steam_timer_fired    # which warning thresholds already fired

# Is Steam actually being detected? (must match STEAM_PROCESS in the script)
pgrep -x steam_osx && echo "steam IS running" || echo "steam is NOT running"
```

`launchctl print` showing `runs = N` with `N` increasing roughly once a
minute, and `last exit code = 0`, confirms launchd is calling the script
on schedule and it's exiting cleanly. If `/tmp/steam_timer_start` appears
and updates while Steam is open, the detection logic is working too.

## Testing

The default thresholds (5/10/15/20 minutes) are slow to verify by hand.
Edit the variables at the top of `stop_steam.sh` to shrink them, e.g. to
use seconds-scale minutes for a quick test:

```bash
WARN_MINUTES_1=1
WARN_MINUTES_2=2
WARN_MINUTES_3=3
KILL_MINUTES=4
```

Then reload the agent so launchd picks up the change:

```bash
launchctl unload ~/Library/LaunchAgents/com.user.stopsteam.plist
launchctl load ~/Library/LaunchAgents/com.user.stopsteam.plist
```

Launch Steam and watch for dialogs at each threshold. You can also run the
script directly, bypassing launchd, to see its behavior immediately:

```bash
./stop_steam.sh
```

Check `/tmp/steam_timer_start` and `/tmp/steam_timer_fired` to inspect
state, and `/tmp/com.user.stopsteam.out.log` /
`/tmp/com.user.stopsteam.err.log` for launchd output.

Remember to restore the original threshold values (or reinstall from a
clean checkout) once you're done testing.

## Uninstallation

```bash
launchctl unload ~/Library/LaunchAgents/com.user.stopsteam.plist
rm ~/Library/LaunchAgents/com.user.stopsteam.plist
rm -f /tmp/steam_timer_start /tmp/steam_timer_fired
```
