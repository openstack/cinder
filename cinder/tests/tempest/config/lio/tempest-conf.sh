# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

# This script is executed in the OpenStack CI
# *tempest-dsvm-full-lio job.  It's used to configure which
# tempest tests actually get run.  You can find the CI job configuration here:
#
# http://git.openstack.org/cgit/openstack-infra/project-config/tree/jenkins/jobs/devstack-gate.yaml
#
# NOTE(sdague): tempest (because of testr) only supports and additive
# regex for specifying test selection. As such this is a series of
# negative assertions ?: for strings.
#
# Being a regex, an unescaped '.' matches any character, so those
# should be escaped. There is no need to specify .* at the end of a
# pattern, as it's handled by the final match.

# Test idempotent ids are used for specific tests because
# these are unchanged if the test name changes.

export DEVSTACK_GATE_TEMPEST_REGEX='(?!.*\[.*\bslow\b.*\])(^tempest\.(api|scenario)|(^cinder\.tests.tempest))'
