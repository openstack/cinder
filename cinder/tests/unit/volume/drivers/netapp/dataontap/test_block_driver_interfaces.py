# Copyright (c) 2015 Clinton Knight.  All rights reserved.
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
Mock unit tests for the NetApp block storage driver interfaces
"""


import mock

from cinder import test
from cinder.volume.drivers.netapp.dataontap import block_7mode
from cinder.volume.drivers.netapp.dataontap import block_cmode
from cinder.volume.drivers.netapp.dataontap import fc_7mode
from cinder.volume.drivers.netapp.dataontap import fc_cmode
from cinder.volume.drivers.netapp.dataontap import iscsi_7mode
from cinder.volume.drivers.netapp.dataontap import iscsi_cmode


class NetAppBlockStorageDriverInterfaceTestCase(test.TestCase):

    def setUp(self):
        super(NetAppBlockStorageDriverInterfaceTestCase, self).setUp()

        self.mock_object(block_cmode.NetAppBlockStorageCmodeLibrary,
                         '__init__',
                         mock.Mock(return_value=None))
        self.mock_object(block_7mode.NetAppBlockStorage7modeLibrary,
                         '__init__',
                         mock.Mock(return_value=None))

        self.iscsi_7mode_driver = iscsi_7mode.NetApp7modeISCSIDriver()
        self.iscsi_cmode_driver = iscsi_cmode.NetAppCmodeISCSIDriver()
        self.fc_7mode_driver = fc_7mode.NetApp7modeFibreChannelDriver()
        self.fc_cmode_driver = fc_cmode.NetAppCmodeFibreChannelDriver()

    def test_driver_interfaces_match(self):
        """Ensure the NetApp block storage driver interfaces match.

        The four block storage Cinder drivers from NetApp (iSCSI/FC,
        7-mode/C-mode) are merely passthrough shim layers atop a common
        block storage library. Bugs have been introduced when a Cinder
        method was exposed via a subset of those driver shims.  This test
        ensures they remain in sync and the library features are uniformly
        available in the four drivers.
        """

        # Get local functions of each driver interface
        iscsi_7mode = self._get_local_functions(self.iscsi_7mode_driver)
        iscsi_cmode = self._get_local_functions(self.iscsi_cmode_driver)
        fc_7mode = self._get_local_functions(self.fc_7mode_driver)
        fc_cmode = self._get_local_functions(self.fc_cmode_driver)

        # Ensure NetApp block storage driver shims are identical
        self.assertSetEqual(iscsi_7mode, iscsi_cmode)
        self.assertSetEqual(iscsi_7mode, fc_7mode)
        self.assertSetEqual(iscsi_7mode, fc_cmode)

    def _get_local_functions(self, obj):
        """Get function names of an object without superclass functions."""
        return set([key for key, value in type(obj).__dict__.items()
                    if callable(value)])
