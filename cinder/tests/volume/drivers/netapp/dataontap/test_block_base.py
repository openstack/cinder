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
Mock unit tests for the NetApp block storage library
"""

import uuid

import mock

from cinder import exception
from cinder import test
from cinder.volume.drivers.netapp.dataontap import block_base
from cinder.volume.drivers.netapp import utils as na_utils


class NetAppBlockStorageLibraryTestCase(test.TestCase):

    def setUp(self):
        super(NetAppBlockStorageLibraryTestCase, self).setUp()

        kwargs = {'configuration': mock.Mock()}
        self.library = block_base.NetAppBlockStorageLibrary('driver',
                                                            'protocol',
                                                            **kwargs)
        self.library.zapi_client = mock.Mock()
        self.mock_request = mock.Mock()

    def tearDown(self):
        super(NetAppBlockStorageLibraryTestCase, self).tearDown()

    @mock.patch.object(block_base.NetAppBlockStorageLibrary, '_get_lun_attr',
                       mock.Mock(return_value={'Volume': 'vol1'}))
    def test_get_pool(self):
        pool = self.library.get_pool({'name': 'volume-fake-uuid'})
        self.assertEqual(pool, 'vol1')

    @mock.patch.object(block_base.NetAppBlockStorageLibrary, '_get_lun_attr',
                       mock.Mock(return_value=None))
    def test_get_pool_no_metadata(self):
        pool = self.library.get_pool({'name': 'volume-fake-uuid'})
        self.assertEqual(pool, None)

    @mock.patch.object(block_base.NetAppBlockStorageLibrary, '_get_lun_attr',
                       mock.Mock(return_value=dict()))
    def test_get_pool_volume_unknown(self):
        pool = self.library.get_pool({'name': 'volume-fake-uuid'})
        self.assertEqual(pool, None)

    @mock.patch.object(block_base.NetAppBlockStorageLibrary, '_create_lun',
                       mock.Mock())
    @mock.patch.object(block_base.NetAppBlockStorageLibrary,
                       '_create_lun_handle',
                       mock.Mock())
    @mock.patch.object(block_base.NetAppBlockStorageLibrary,
                       '_add_lun_to_table',
                       mock.Mock())
    @mock.patch.object(na_utils, 'get_volume_extra_specs',
                       mock.Mock(return_value=None))
    @mock.patch.object(block_base, 'LOG',
                       mock.Mock())
    def test_create_volume(self):
        self.library.create_volume({'name': 'lun1', 'size': 100,
                                    'id': uuid.uuid4(),
                                    'host': 'hostname@backend#vol1'})
        self.library._create_lun.assert_called_once_with(
            'vol1', 'lun1', 107374182400, mock.ANY, None)
        self.assertEqual(0, block_base.LOG.warn.call_count)

    def test_create_volume_no_pool_provided_by_scheduler(self):
        self.assertRaises(exception.InvalidHost, self.library.create_volume,
                          {'name': 'lun1', 'size': 100,
                           'id': uuid.uuid4(),
                           'host': 'hostname@backend'})  # missing pool

    @mock.patch.object(block_base.NetAppBlockStorageLibrary,
                       '_create_lun', mock.Mock())
    @mock.patch.object(block_base.NetAppBlockStorageLibrary,
                       '_create_lun_handle', mock.Mock())
    @mock.patch.object(block_base.NetAppBlockStorageLibrary,
                       '_add_lun_to_table', mock.Mock())
    @mock.patch.object(na_utils, 'LOG', mock.Mock())
    @mock.patch.object(na_utils, 'get_volume_extra_specs',
                       mock.Mock(return_value={'netapp:raid_type': 'raid4'}))
    def test_create_volume_obsolete_extra_spec(self):

        self.library.create_volume({'name': 'lun1', 'size': 100,
                                    'id': uuid.uuid4(),
                                    'host': 'hostname@backend#vol1'})
        warn_msg = 'Extra spec netapp:raid_type is obsolete.  ' \
                   'Use netapp_raid_type instead.'
        na_utils.LOG.warn.assert_called_once_with(warn_msg)

    @mock.patch.object(block_base.NetAppBlockStorageLibrary,
                       '_create_lun', mock.Mock())
    @mock.patch.object(block_base.NetAppBlockStorageLibrary,
                       '_create_lun_handle', mock.Mock())
    @mock.patch.object(block_base.NetAppBlockStorageLibrary,
                       '_add_lun_to_table', mock.Mock())
    @mock.patch.object(na_utils, 'LOG', mock.Mock())
    @mock.patch.object(na_utils, 'get_volume_extra_specs',
                       mock.Mock(return_value={'netapp_thick_provisioned':
                                               'true'}))
    def test_create_volume_deprecated_extra_spec(self):

        self.library.create_volume({'name': 'lun1', 'size': 100,
                                    'id': uuid.uuid4(),
                                    'host': 'hostname@backend#vol1'})
        warn_msg = 'Extra spec netapp_thick_provisioned is deprecated.  ' \
                   'Use netapp_thin_provisioned instead.'
        na_utils.LOG.warn.assert_called_once_with(warn_msg)
