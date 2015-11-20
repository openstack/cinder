#!/bin/bash

cd $(dirname "$0")/..
CHANGED=$(git diff --name-only HEAD~2 | tr '\n' ' ')

# Skip files that don't exist
# (have been git rm'd)
CHECK=""
for FILE in $CHANGED; do
    if [ -f "$f" ]; then
        CHECK="$CHECK $FILE"
    fi
done

diff -u --from-file /dev/null $CHECK | flake8 --diff
