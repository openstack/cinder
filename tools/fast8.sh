#!/bin/bash

NUM_COMMITS=${FAST8_NUM_COMMITS:-1}

if [[ $NUM_COMMITS = "smart" ]]; then
    # Run on all commits not submitted yet
    # (sort of -- only checks vs. "master" since this is easy)
    NUM_COMMITS=$(git cherry master | wc -l)
fi

echo "Checking last $NUM_COMMITS commits."

cd $(dirname "$0")/..
CHANGED=""
CHANGED+="$(git diff --name-only HEAD~${NUM_COMMITS} \*.py | tr '\n' ' ')"

while [[ -z $CHANGED ]]; do
	# Search back until we find a commit containing python files
    NUM_COMMITS=$((NUM_COMMITS + 1))
    CHANGED+="$(git diff --name-only HEAD~${NUM_COMMITS} \*.py | tr '\n' ' ')" ;
done

# Skip files that don't exist
# (have been git rm'd)
CHECK=""
for FILE in $CHANGED; do
    if [ -f "$FILE" ]; then
        CHECK+="$FILE "
    fi
done

flake8 $CHECK
