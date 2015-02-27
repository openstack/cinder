# Copyright (c) 2014 Andrew Kerr.  All rights reserved.
# Copyright (c) 2015 Alex Meade.  All rights reserved.
# Copyright (c) 2015 Rushil Chugh.  All rights reserved.
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
Mock unit tests for the NetApp E-series iscsi driver
"""

import mock

from cinder import test
from cinder.tests.volume.drivers.netapp import fakes as na_fakes
from cinder.volume.drivers.netapp.eseries import client as es_client
from cinder.volume.drivers.netapp.eseries import iscsi as es_iscsi
from cinder.volume.drivers.netapp import utils as na_utils


class NetAppEseriesISCSIDriverTestCase(test.TestCase):
    def setUp(self):
        super(NetAppEseriesISCSIDriverTestCase, self).setUp()

        kwargs = {'configuration': self.get_config_eseries()}

        self.driver = es_iscsi.NetAppEseriesISCSIDriver(**kwargs)
        self.driver._client = mock.Mock()

    def get_config_eseries(self):
        config = na_fakes.create_configuration_eseries()
        config.netapp_storage_protocol = 'iscsi'
        config.netapp_login = 'rw'
        config.netapp_password = 'rw'
        config.netapp_server_hostname = '127.0.0.1'
        config.netapp_transport_type = 'http'
        config.netapp_server_port = '8080'
        config.netapp_storage_pools = 'DDP'
        config.netapp_storage_family = 'eseries'
        config.netapp_sa_password = 'saPass'
        config.netapp_controller_ips = '10.11.12.13,10.11.12.14'
        config.netapp_webservice_path = '/devmgr/v2'
        return config

    @mock.patch.object(es_iscsi.NetAppEseriesISCSIDriver,
                       '_check_mode_get_or_register_storage_system')
    @mock.patch.object(es_client, 'RestClient', mock.Mock())
    @mock.patch.object(na_utils, 'check_flags', mock.Mock())
    def test_do_setup(self, mock_check_flags):
        self.driver.do_setup(mock.Mock())

        self.assertTrue(mock_check_flags.called)

    def test_update_ssc_info(self):
        drives = [{'currentVolumeGroupRef': 'test_vg1',
                   'driveMediaType': 'ssd'}]

        self.driver._objects["disk_pool_refs"] = ['test_vg1']
        self.driver._client.list_storage_pools = mock.Mock(return_value=[])
        self.driver._client.list_drives = mock.Mock(return_value=drives)

        self.driver._update_ssc_info()

        self.assertEqual({'test_vg1': {'netapp_disk_type': 'SSD'}},
                         self.driver._ssc_stats)

    def test_update_ssc_disk_types_ssd(self):
        drives = [{'currentVolumeGroupRef': 'test_vg1',
                   'driveMediaType': 'ssd'}]
        self.driver._client.list_drives = mock.Mock(return_value=drives)

        ssc_stats = self.driver._update_ssc_disk_types(['test_vg1'])

        self.assertEqual({'test_vg1': {'netapp_disk_type': 'SSD'}},
                         ssc_stats)

    def test_update_ssc_disk_types_scsi(self):
        drives = [{'currentVolumeGroupRef': 'test_vg1',
                   'interfaceType': {'driveType': 'scsi'}}]
        self.driver._client.list_drives = mock.Mock(return_value=drives)

        ssc_stats = self.driver._update_ssc_disk_types(['test_vg1'])

        self.assertEqual({'test_vg1': {'netapp_disk_type': 'SCSI'}},
                         ssc_stats)

    def test_update_ssc_disk_types_fcal(self):
        drives = [{'currentVolumeGroupRef': 'test_vg1',
                   'interfaceType': {'driveType': 'fibre'}}]
        self.driver._client.list_drives = mock.Mock(return_value=drives)

        ssc_stats = self.driver._update_ssc_disk_types(['test_vg1'])

        self.assertEqual({'test_vg1': {'netapp_disk_type': 'FCAL'}},
                         ssc_stats)

    def test_update_ssc_disk_types_sata(self):
        drives = [{'currentVolumeGroupRef': 'test_vg1',
                   'interfaceType': {'driveType': 'sata'}}]
        self.driver._client.list_drives = mock.Mock(return_value=drives)

        ssc_stats = self.driver._update_ssc_disk_types(['test_vg1'])

        self.assertEqual({'test_vg1': {'netapp_disk_type': 'SATA'}},
                         ssc_stats)

    def test_update_ssc_disk_types_sas(self):
        drives = [{'currentVolumeGroupRef': 'test_vg1',
                   'interfaceType': {'driveType': 'sas'}}]
        self.driver._client.list_drives = mock.Mock(return_value=drives)

        ssc_stats = self.driver._update_ssc_disk_types(['test_vg1'])

        self.assertEqual({'test_vg1': {'netapp_disk_type': 'SAS'}},
                         ssc_stats)

    def test_update_ssc_disk_types_unknown(self):
        drives = [{'currentVolumeGroupRef': 'test_vg1',
                   'interfaceType': {'driveType': 'unknown'}}]
        self.driver._client.list_drives = mock.Mock(return_value=drives)

        ssc_stats = self.driver._update_ssc_disk_types(['test_vg1'])

        self.assertEqual({'test_vg1': {'netapp_disk_type': 'unknown'}},
                         ssc_stats)

    def test_update_ssc_disk_types_undefined(self):
        drives = [{'currentVolumeGroupRef': 'test_vg1',
                   'interfaceType': {'driveType': '__UNDEFINED'}}]
        self.driver._client.list_drives = mock.Mock(return_value=drives)

        ssc_stats = self.driver._update_ssc_disk_types(['test_vg1'])

        self.assertEqual({'test_vg1': {'netapp_disk_type': 'unknown'}},
                         ssc_stats)

    def test_update_ssc_disk_encryption_SecType_enabled(self):
        pools = [{'volumeGroupRef': 'test_vg1', 'securityType': 'enabled'}]
        self.driver._client.list_storage_pools = mock.Mock(return_value=pools)

        ssc_stats = self.driver._update_ssc_disk_encryption(['test_vg1'])

        self.assertEqual({'test_vg1': {'netapp_disk_encryption': 'true'}},
                         ssc_stats)

    def test_update_ssc_disk_encryption_SecType_unknown(self):
        pools = [{'volumeGroupRef': 'test_vg1', 'securityType': 'unknown'}]
        self.driver._client.list_storage_pools = mock.Mock(return_value=pools)

        ssc_stats = self.driver._update_ssc_disk_encryption(['test_vg1'])

        self.assertEqual({'test_vg1': {'netapp_disk_encryption': 'false'}},
                         ssc_stats)

    def test_update_ssc_disk_encryption_SecType_none(self):
        pools = [{'volumeGroupRef': 'test_vg1', 'securityType': 'none'}]
        self.driver._client.list_storage_pools = mock.Mock(return_value=pools)

        ssc_stats = self.driver._update_ssc_disk_encryption(['test_vg1'])

        self.assertEqual({'test_vg1': {'netapp_disk_encryption': 'false'}},
                         ssc_stats)

    def test_update_ssc_disk_encryption_SecType_capable(self):
        pools = [{'volumeGroupRef': 'test_vg1', 'securityType': 'capable'}]
        self.driver._client.list_storage_pools = mock.Mock(return_value=pools)

        ssc_stats = self.driver._update_ssc_disk_encryption(['test_vg1'])

        self.assertEqual({'test_vg1': {'netapp_disk_encryption': 'false'}},
                         ssc_stats)

    def test_update_ssc_disk_encryption_SecType_garbage(self):
        pools = [{'volumeGroupRef': 'test_vg1', 'securityType': 'garbage'}]
        self.driver._client.list_storage_pools = mock.Mock(return_value=pools)

        ssc_stats = self.driver._update_ssc_disk_encryption(['test_vg1'])

        self.assertRaises(TypeError, 'test_vg1',
                          {'netapp_disk_encryption': 'false'}, ssc_stats)

    def test_update_ssc_disk_encryption_multiple(self):
        pools = [{'volumeGroupRef': 'test_vg1', 'securityType': 'none'},
                 {'volumeGroupRef': 'test_vg2', 'securityType': 'enabled'}]
        self.driver._client.list_storage_pools = mock.Mock(return_value=pools)

        ssc_stats = self.driver._update_ssc_disk_encryption(['test_vg1',
                                                            'test_vg2'])

        self.assertEqual({'test_vg1': {'netapp_disk_encryption': 'false'},
                          'test_vg2': {'netapp_disk_encryption': 'true'}},
                         ssc_stats)
