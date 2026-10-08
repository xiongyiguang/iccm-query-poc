#!/bin/zsh
cd "${0:A:h}" || exit 1
PY="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
if [[ ! -x "$PY" ]]; then
  PY="$(command -v python3)"
fi
if ! "$PY" -c 'import sys; sys.exit(sys.version_info < (3, 11))'; then
  print "智能体需要 Python 3.11 或更高版本，请先恢复本机 Python 运行环境。"
  exit 1
fi
exec "$PY" server.py --port 8771
