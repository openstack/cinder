#!/usr/bin/python3
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

# Print a list and return with error if any executable files are found.
# Compatible with both python 2 and 3.

import os.path
import stat
import sys

if len(sys.argv) < 2:
    print("Usage: %s <directory>" % sys.argv[0])
    sys.exit(1)

directories = sys.argv[1:]

executable = []

for d in directories:
    for root, mydir, myfile in os.walk(d):
        for f in myfile:
            path = os.path.join(root, f)
            mode = os.lstat(path).st_mode
            if stat.S_IXUSR & mode:
                executable.append(path)

if executable:
    print("Executable files found:")
    for f in executable:
        print(f)

    sys.exit(1)
