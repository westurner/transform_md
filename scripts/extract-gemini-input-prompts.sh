#!/bin/sh

chatpath=${1:-./transform_md.py_chat1.copilot.json}
jq -r '.requests[] | (.message.text | split("\n")[] | "- " + .), ""' "$chatpath" \
    | sed 's/^- -/- \\-/'