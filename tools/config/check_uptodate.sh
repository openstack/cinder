#!/usr/bin/env bash

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

# This script is used to check if there have been configuration changes that
# have not been checked in.

# The opts file needs to be present in order to compare it
if [ ! -e cinder/opts.py ]; then
    echo ""
    echo "#################################################"
    echo "ERROR: cinder/opts.py file is missing."
    echo "#################################################"
    exit 1
fi

# Rename the existing file so we can generate a new one to compare
mv cinder/opts.py cinder/opts.py.orig
python tools/config/generate_cinder_opts.py &> tox-genops.log
if [ $? -ne 0 ]; then
    cat tox-genops.log >&2
    echo ""
    echo "#################################################"
    echo "ERROR: Non-zero exit from generate_cinder_opts.py."
    echo "       See output above for details."
    echo "#################################################"
    mv cinder/opts.py.orig cinder/opts.py
    exit 1
fi

diff cinder/opts.py.orig cinder/opts.py
if [ $? -ne 0 ]; then
    echo ""
    echo "########################################################"
    echo "ERROR: Configuration options change detected."
    echo "       A new cinder/opts.py file must be generated."
    echo "       Run 'tox -e genopts' from the base directory"
    echo "       and add the result to your commit."
    echo "########################################################"
    rm cinder/opts.py
    mv cinder/opts.py.orig cinder/opts.py
    exit 1
fi

rm cinder/opts.py.orig
