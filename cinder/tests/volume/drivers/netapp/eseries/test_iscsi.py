# Copyright (c) 2014 Andrew Kerr.  All rights reserved.
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
