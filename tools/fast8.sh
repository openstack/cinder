#!/bin/bash

cd $(dirname "$0")/..
CHANGED=$(git diff --name-only HEAD~2 | tr '\n' ' ')
diff -u --from-file /dev/null $CHANGED | flake8 --diff
