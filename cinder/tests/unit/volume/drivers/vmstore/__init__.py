# Copyright 2026 DDN, Inc. All rights reserved.
#
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

"""Unit tests for VMstore Cinder driver."""

from oslo_config import cfg

CONF = cfg.CONF


def set_vmstore_overrides():
    """Set vmstore config options for tests.

    Sets fake values for vmstore_password and vmstore_rest_address
    which are validated by the driver during do_setup().
    """
    CONF.set_override('vmstore_password', 'fake_password',
                      group='backend_defaults')
    CONF.set_override('vmstore_rest_address', 'fake_address',
                      group='backend_defaults')
