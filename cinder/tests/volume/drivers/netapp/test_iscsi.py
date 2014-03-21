# Copyright (c) 2014 NetApp, Inc.
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
"""
Mock unit tests for the NetApp iSCSI driver
"""

import mock

from cinder import test
import cinder.volume.drivers.netapp.api as ntapi
import cinder.volume.drivers.netapp.iscsi as ntap_iscsi


class NetAppiSCSICModeTestCase(test.TestCase):
    """Test case for NetApp's C-Mode iSCSI driver."""

    def setUp(self):
        super(NetAppiSCSICModeTestCase, self).setUp()
        self.driver = ntap_iscsi.NetAppDirectCmodeISCSIDriver(
            configuration=mock.Mock())
        self.driver.client = mock.Mock()
        self.driver.vserver = mock.Mock()

    def tearDown(self):
        super(NetAppiSCSICModeTestCase, self).tearDown()

    def test_clone_lun_multiple_zapi_calls(self):
        """Test for when lun clone requires more than one zapi call."""

        # Max block-ranges per call = 32, max blocks per range = 2^24
        # Force 2 calls
        bc = 2 ** 24 * 32 * 2
        self.driver._get_lun_attr = mock.Mock(return_value={'Volume':
                                                            'fakeLUN'})
        self.driver.client.invoke_successfully = mock.Mock()
        lun = ntapi.NaElement.create_node_with_children(
            'lun-info',
            **{'alignment': 'indeterminate',
               'block-size': '512',
               'comment': '',
               'creation-timestamp': '1354536362',
               'is-space-alloc-enabled': 'false',
               'is-space-reservation-enabled': 'true',
               'mapped': 'false',
               'multiprotocol-type': 'linux',
               'online': 'true',
               'path': '/vol/fakeLUN/lun1',
               'prefix-size': '0',
               'qtree': '',
               'read-only': 'false',
               'serial-number': '2FfGI$APyN68',
               'share-state': 'none',
               'size': '20971520',
               'size-used': '0',
               'staging': 'false',
               'suffix-size': '0',
               'uuid': 'cec1f3d7-3d41-11e2-9cf4-123478563412',
               'volume': 'fakeLUN',
               'vserver': 'fake_vserver'})
        self.driver._get_lun_by_args = mock.Mock(return_value=[lun])
        self.driver._add_lun_to_table = mock.Mock()
        self.driver._update_stale_vols = mock.Mock()

        self.driver._clone_lun('fakeLUN', 'newFakeLUN', block_count=bc)

        self.assertEqual(2, self.driver.client.invoke_successfully.call_count)


class NetAppiSCSI7ModeTestCase(test.TestCase):
    """Test case for NetApp's 7-Mode iSCSI driver."""

    def setUp(self):
        super(NetAppiSCSI7ModeTestCase, self).setUp()
        self.driver = ntap_iscsi.NetAppDirect7modeISCSIDriver(
            configuration=mock.Mock())
        self.driver.client = mock.Mock()
        self.driver.vfiler = mock.Mock()

    def tearDown(self):
        super(NetAppiSCSI7ModeTestCase, self).tearDown()

    def test_clone_lun_multiple_zapi_calls(self):
        """Test for when lun clone requires more than one zapi call."""

        # Max block-ranges per call = 32, max blocks per range = 2^24
        # Force 2 calls
        bc = 2 ** 24 * 32 * 2
        self.driver._get_lun_attr = mock.Mock(return_value={'Volume':
                                                            'fakeLUN',
                                                            'Path':
                                                            '/vol/fake/lun1'})
        self.driver.client.invoke_successfully = mock.Mock(
            return_value=mock.MagicMock())
        lun = ntapi.NaElement.create_node_with_children(
            'lun-info',
            **{'alignment': 'indeterminate',
               'block-size': '512',
               'comment': '',
               'creation-timestamp': '1354536362',
               'is-space-alloc-enabled': 'false',
               'is-space-reservation-enabled': 'true',
               'mapped': 'false',
               'multiprotocol-type': 'linux',
               'online': 'true',
               'path': '/vol/fakeLUN/lun1',
               'prefix-size': '0',
               'qtree': '',
               'read-only': 'false',
               'serial-number': '2FfGI$APyN68',
               'share-state': 'none',
               'size': '20971520',
               'size-used': '0',
               'staging': 'false',
               'suffix-size': '0',
               'uuid': 'cec1f3d7-3d41-11e2-9cf4-123478563412',
               'volume': 'fakeLUN',
               'vserver': 'fake_vserver'})
        self.driver._get_lun_by_args = mock.Mock(return_value=[lun])
        self.driver._add_lun_to_table = mock.Mock()
        self.driver._update_stale_vols = mock.Mock()
        self.driver._check_clone_status = mock.Mock()
        self.driver._set_space_reserve = mock.Mock()

        self.driver._clone_lun('fakeLUN', 'newFakeLUN', block_count=bc)

        self.assertEqual(2, self.driver.client.invoke_successfully.call_count)
