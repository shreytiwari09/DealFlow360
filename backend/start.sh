#!/bin/sh
# Render's dockerCommand field does not reliably parse an inline
# `sh -c "cmd1 && cmd2 && cmd3"` string (it mangled the quoting/&&, producing
# a literal "not found" for the entire string as one token). Isolating the
# startup sequence in its own script sidesteps that entirely - render.yaml's
# dockerCommand becomes the single, unambiguous token `sh start.sh`, nothing
# for a naive argv splitter to get wrong.
set -e

alembic upgrade head
python -m app.seed
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
