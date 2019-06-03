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
#
"""Fake rbd-iscsi-client for testing without installing the client."""

import sys
from unittest import mock

from cinder.tests.unit.volume.drivers.ceph \
    import fake_rbd_iscsi_client_exceptions as clientexceptions

rbdclient = mock.MagicMock()
rbdclient.version = "0.1.5"
rbdclient.exceptions = clientexceptions

sys.modules['rbd_iscsi_client'] = rbdclient
