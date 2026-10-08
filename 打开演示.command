#!/bin/zsh
cd "${0:A:h}" || exit 1
/usr/bin/python3 scripts/macos-demo.py && open "http://127.0.0.1:8765"
