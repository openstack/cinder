#!/bin/bash

# Copyright (c) 2016, Hitachi, Erlon Cruz <erlon.cruz@fit-tecnologia.org.br>
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

set -x
export TEMPEST_USER=${TEMPEST_USER:-tempest}
chmod +w $BASE/new/tempest
cd $BASE/new/tempest
source $BASE/new/devstack/functions
source $BASE/new/devstack/functions-common
source $WORKSPACE/devstack-gate/functions.sh
source $BASE/new/cinder/tools/hooks/utils.sh
export TEMPEST_CONFIG=$BASE/new/tempest/etc/tempest.conf

# Disable bash verbose so we have a cleaner output. Also, exit on error must
# be disable as we will run several tests that can return error.
set +x +e

function configure_tempest_backends {
    be1=$1
    be2=$2
    echo "Configuring tempest conf in ${TEMPEST_CONFIG}"
    iniset -sudo $TEMPEST_CONFIG 'volume' 'backend_names' ${be1},${be2}

}

BACKENDS='lvm ceph nfs'
RGEX="(.*test_volume_retype_with_migration.*|.*test_volume_migrate_attached.*)"
final_result=0
final_message='Migrations tests finished SUCCESSFULLY!'
declare -A TEST_RESULTS
start_time=`date +%s`
for be1 in ${BACKENDS}; do
    for be2 in ${BACKENDS}; do
        if [ ${be1} != ${be2} ]; then
            configure_tempest_backends ${be1} ${be2}
            echo "============================================================"
            echo "Testing multibackend features: ${be1} vs ${be2}"
            echo "============================================================"
            run_tempest "${be1} vs ${be2}" ${RGEX}
            result=$?
            # If any of the test fail, we keep running but return failure as
            # the final result
            if [ ${result} -ne 0 ]; then
                TEST_RESULTS[${be1},${be2}]="FAILURE"
                final_message='Migrations tests FAILED!'
                final_result=1
            else
                TEST_RESULTS[${be1},${be2}]="SUCCESS"
            fi
        fi
    done
done
end_time=`date +%s`
elapsed=$(expr $(expr ${end_time} - ${start_time}) / 60)

# Print the results
num_rows=$(echo $BACKENDS | wc -w)
fmt=" %15s"
echo "============================================================"
echo " ${final_message} In ${elapsed} minutes."
echo "============================================================"

printf "$fmt" ''
for be1 in ${BACKENDS}; do
    printf "$fmt" ${be1}
done
echo
for be1 in ${BACKENDS}; do
    printf "$fmt" ${be1}
    for be2 in ${BACKENDS}; do
        if [ ${be1} == ${be2} ]; then
            printf "$fmt" '---'
        else
            printf "$fmt" ${TEST_RESULTS[${be1},${be2}]}
        fi
    done
    echo
done

exit ${final_result}
