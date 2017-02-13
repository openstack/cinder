#!/bin/bash

function run_tempest {
    local message=$1
    local tempest_regex=$2
    sudo -H -u ${TEMPEST_USER}  tox -eall -- $tempest_regex \
    --concurrency=${TEMPEST_CONCURRENCY}
    exitcode=$?
    return ${exitcode}
}
