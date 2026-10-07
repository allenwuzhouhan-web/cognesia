#!/bin/zsh
set -u
cd -- "$(dirname -- "$0")"
if [[ ! -x .venv/bin/flybrain ]]; then
    uv venv --python 3.12 .venv || exit $?
    uv pip install --python .venv/bin/python -e '.[test]' || exit $?
fi
.venv/bin/flybrain run dark
flybrain_result=$?
.venv/bin/flybrain report
printf '\nThe run evidence is saved in REPORT.md. Exit status: %s\n' "$flybrain_result"
exit "$flybrain_result"
