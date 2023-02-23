# Copyright 2022 Red Hat, Inc
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
"""
FAKE the nvmet library if it's not installed.
This must be imported before cinder/volume/targets/nvmet.py and
cinder/privsep/targets/nvmet.py
"""

import sys
from unittest import mock

from cinder import exception

try:
    import nvmet  # noqa
    reset_mock = lambda: None  # noqa
except ImportError:
    mock_nvmet_lib = mock.Mock(name='nvmet',
                               Root=type('Root', (mock.Mock, ), {}),
                               Subsystem=type('Subsystem', (mock.Mock, ), {}),
                               Port=type('Port', (mock.Mock, ), {}),
                               Namespace=type('Namespace', (mock.Mock, ),
                                              {'MAX_NSID': 8192}),
                               Host=type('Host', (mock.Mock, ), {}),
                               ANAGroup=type('ANAGroup', (mock.Mock, ), {}),
                               Referral=type('Referral', (mock.Mock, ), {}),
                               nvme=mock.Mock(CFSNotFound=exception.NotFound))

    sys.modules['nvmet'] = mock_nvmet_lib
    reset_mock = mock_nvmet_lib.reset_mock
