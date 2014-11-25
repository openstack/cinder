# Copyright (c) 2014 Alex Meade.  All rights reserved.
# Copyright (c) 2014 Clinton Knight.  All rights reserved.
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
Mock unit tests for the NetApp block storage C-mode library
"""

import uuid

import mock
import six

from cinder import test
from cinder.volume.drivers.netapp.dataontap import block_cmode
from cinder.volume.drivers.netapp.dataontap.client import api as netapp_api
from cinder.volume.drivers.netapp.dataontap import ssc_cmode

FAKE_VOLUME = six.text_type(uuid.uuid4())
FAKE_LUN = six.text_type(uuid.uuid4())
FAKE_SIZE = '1024'
FAKE_METADATA = {'OsType': 'linux', 'SpaceReserved': 'true'}


class NetAppBlockStorageCmodeLibraryTestCase(test.TestCase):
    """Test case for NetApp's C-Mode iSCSI library."""

    def setUp(self):
        super(NetAppBlockStorageCmodeLibraryTestCase, self).setUp()

        kwargs = {'configuration': mock.Mock()}
        self.library = block_cmode.NetAppBlockStorageCmodeLibrary('driver',
                                                                  'protocol',
                                                                  **kwargs)
        self.library.zapi_client = mock.Mock()
        self.library.vserver = mock.Mock()
        self.library.ssc_vols = None

    def tearDown(self):
        super(NetAppBlockStorageCmodeLibraryTestCase, self).tearDown()

    def test_clone_lun_zero_block_count(self):
        """Test for when clone lun is not passed a block count."""

        self.library._get_lun_attr = mock.Mock(return_value={'Volume':
                                                             'fakeLUN'})
        self.library.zapi_client = mock.Mock()
        self.library.zapi_client.get_lun_by_args.return_value = [
            mock.Mock(spec=netapp_api.NaElement)]
        lun = netapp_api.NaElement.create_node_with_children(
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
        self.library._get_lun_by_args = mock.Mock(return_value=[lun])
        self.library._add_lun_to_table = mock.Mock()
        self.library._update_stale_vols = mock.Mock()

        self.library._clone_lun('fakeLUN', 'newFakeLUN')

        self.library.zapi_client.clone_lun.assert_called_once_with(
            'fakeLUN', 'fakeLUN', 'newFakeLUN', 'true', block_count=0,
            dest_block=0, src_block=0)

    @mock.patch.object(ssc_cmode, 'refresh_cluster_ssc', mock.Mock())
    @mock.patch.object(block_cmode.NetAppBlockStorageCmodeLibrary,
                       '_get_pool_stats', mock.Mock())
    def test_vol_stats_calls_provide_ems(self):
        self.library.zapi_client.provide_ems = mock.Mock()
        self.library.get_volume_stats(refresh=True)
        self.assertEqual(self.library.zapi_client.provide_ems.call_count, 1)

    def test_create_lun(self):
        self.library._update_stale_vols = mock.Mock()

        self.library._create_lun(FAKE_VOLUME,
                                 FAKE_LUN,
                                 FAKE_SIZE,
                                 FAKE_METADATA)

        self.library.zapi_client.create_lun.assert_called_once_with(
            FAKE_VOLUME, FAKE_LUN, FAKE_SIZE,
            FAKE_METADATA, None)

        self.assertEqual(1, self.library._update_stale_vols.call_count)
