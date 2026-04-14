#!/usr/bin/env bash
set -e

python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt

if [ -f .env ]; then
  export $(grep -v '^#' .env | xargs)
fi

python run.py
