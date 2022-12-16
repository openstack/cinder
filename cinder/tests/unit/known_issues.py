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

# KNOWN ISSUES RUNNING UNIT TESTS

# We've seen tpool.killall method freeze everything.  The issue seems to be
# resolved by calling killall during the cleanup after stopping all remaining
# looping calls, but we cannot be 100% of it, so we have this flag to quickly
# disable the cleanup and the tests that would break with the change if
# necessary.
# If we find that an stestr child runner is blocking we can trigger the Guru
# Meditation Report (kill -USR2 <child_pid>) and look if a Green Thread is
# stuck on tpool.killall.
TPOOL_KILLALL_ISSUE = False
