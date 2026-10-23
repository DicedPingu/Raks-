#!/bin/sh
# Raks launcher.
#   ./run.sh                 run in the foreground (extra args go to raks_host.py, e.g. --demo)
#   ./run.sh start|stop|status|restart   background service (pidfile + logfile)
DIR="$(cd "$(dirname "$0")" && pwd)"
PIDFILE="${RAKS_PIDFILE:-/tmp/raks.pid}"
LOGFILE="${RAKS_LOG:-/tmp/raks.log}"
PY="$(command -v python3 || command -v python)"

if [ -z "$PY" ]; then echo "python3 not found" >&2; exit 1; fi

ensure_uinput() {
  if [ ! -e /dev/uinput ] && [ "$(id -u)" = "0" ]; then
    modprobe uinput 2>/dev/null || true
    sleep 1
  fi
}

is_running() { [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; }

case "$1" in
  start)
    shift
    if is_running; then echo "Raks already running (pid $(cat "$PIDFILE"))"; exit 0; fi
    ensure_uinput
    cd "$DIR" || exit 1
    nohup "$PY" "$DIR/host/raks_host.py" "$@" >"$LOGFILE" 2>&1 &
    echo $! >"$PIDFILE"
    echo "Raks started (pid $!, log $LOGFILE)"
    ;;
  stop)
    if is_running; then kill "$(cat "$PIDFILE")"; rm -f "$PIDFILE"; echo "Raks stopped"; else echo "Raks not running"; fi
    ;;
  restart)
    shift; "$0" stop; sleep 1; "$0" start "$@"
    ;;
  status)
    if is_running; then echo "Raks running (pid $(cat "$PIDFILE"))"; else echo "Raks not running"; exit 1; fi
    ;;
  *)
    ensure_uinput
    cd "$DIR" || exit 1
    exec "$PY" "$DIR/host/raks_host.py" "$@"
    ;;
esac
