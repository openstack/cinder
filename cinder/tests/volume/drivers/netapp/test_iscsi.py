# Copyright (c) - 2014, Alex Meade.  All rights reserved.
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

import uuid

import mock
import six

from cinder import exception
from cinder.i18n import _
from cinder import test
from cinder.tests.test_netapp import create_configuration
import cinder.volume.drivers.netapp.api as ntapi
import cinder.volume.drivers.netapp.iscsi as ntap_iscsi
from cinder.volume.drivers.netapp.iscsi import NetAppDirect7modeISCSIDriver \
    as iscsi7modeDriver
from cinder.volume.drivers.netapp.iscsi import NetAppDirectCmodeISCSIDriver \
    as iscsiCmodeDriver
from cinder.volume.drivers.netapp.iscsi import NetAppDirectISCSIDriver \
    as iscsiDriver
import cinder.volume.drivers.netapp.ssc_utils as ssc_utils
import cinder.volume.drivers.netapp.utils as na_utils


FAKE_VOLUME = six.text_type(uuid.uuid4())
FAKE_LUN = six.text_type(uuid.uuid4())
FAKE_SIZE = '1024'
FAKE_METADATA = {'OsType': 'linux', 'SpaceReserved': 'true'}


class NetAppDirectISCSIDriverTestCase(test.TestCase):

    def setUp(self):
        super(NetAppDirectISCSIDriverTestCase, self).setUp()
        configuration = self._set_config(create_configuration())
        self.driver = ntap_iscsi.NetAppDirectISCSIDriver(
            configuration=configuration)
        self.driver.client = mock.Mock()
        self.driver.zapi_client = mock.Mock()
        self.mock_request = mock.Mock()

    def _set_config(self, configuration):
        configuration.netapp_storage_protocol = 'iscsi'
        configuration.netapp_login = 'admin'
        configuration.netapp_password = 'pass'
        configuration.netapp_server_hostname = '127.0.0.1'
        configuration.netapp_transport_type = 'http'
        configuration.netapp_server_port = '80'
        return configuration

    def tearDown(self):
        super(NetAppDirectISCSIDriverTestCase, self).tearDown()

    @mock.patch.object(iscsiDriver, '_get_lun_attr',
                       mock.Mock(return_value={'Volume': 'vol1'}))
    def test_get_pool(self):
        pool = self.driver.get_pool({'name': 'volume-fake-uuid'})
        self.assertEqual(pool, 'vol1')

    @mock.patch.object(iscsiDriver, '_get_lun_attr',
                       mock.Mock(return_value=None))
    def test_get_pool_no_metadata(self):
        pool = self.driver.get_pool({'name': 'volume-fake-uuid'})
        self.assertEqual(pool, None)

    @mock.patch.object(iscsiDriver, '_get_lun_attr',
                       mock.Mock(return_value=dict()))
    def test_get_pool_volume_unknown(self):
        pool = self.driver.get_pool({'name': 'volume-fake-uuid'})
        self.assertEqual(pool, None)

    @mock.patch.object(iscsiDriver, 'create_lun', mock.Mock())
    @mock.patch.object(iscsiDriver, '_create_lun_handle', mock.Mock())
    @mock.patch.object(iscsiDriver, '_add_lun_to_table', mock.Mock())
    @mock.patch.object(ntap_iscsi, 'LOG', mock.Mock())
    @mock.patch.object(ntap_iscsi, 'get_volume_extra_specs',
                       mock.Mock(return_value=None))
    def test_create_volume(self):
        self.driver.create_volume({'name': 'lun1', 'size': 100,
                                   'id': uuid.uuid4(),
                                   'host': 'hostname@backend#vol1'})
        self.driver.create_lun.assert_called_once_with(
            'vol1', 'lun1', 107374182400, mock.ANY, None)
        self.assertEqual(0, ntap_iscsi.LOG.warn.call_count)

    def test_create_volume_no_pool_provided_by_scheduler(self):
        self.assertRaises(exception.InvalidHost, self.driver.create_volume,
                          {'name': 'lun1', 'size': 100,
                           'id': uuid.uuid4(),
                           'host': 'hostname@backend'})  # missing pool

    @mock.patch.object(iscsiDriver, 'create_lun', mock.Mock())
    @mock.patch.object(iscsiDriver, '_create_lun_handle', mock.Mock())
    @mock.patch.object(iscsiDriver, '_add_lun_to_table', mock.Mock())
    @mock.patch.object(na_utils, 'LOG', mock.Mock())
    @mock.patch.object(ntap_iscsi, 'get_volume_extra_specs',
                       mock.Mock(return_value={'netapp:raid_type': 'raid4'}))
    def test_create_volume_obsolete_extra_spec(self):

        self.driver.create_volume({'name': 'lun1', 'size': 100,
                                   'id': uuid.uuid4(),
                                   'host': 'hostname@backend#vol1'})
        warn_msg = 'Extra spec netapp:raid_type is obsolete.  ' \
                   'Use netapp_raid_type instead.'
        na_utils.LOG.warning.assert_called_once_with(warn_msg)

    @mock.patch.object(iscsiDriver, 'create_lun', mock.Mock())
    @mock.patch.object(iscsiDriver, '_create_lun_handle', mock.Mock())
    @mock.patch.object(iscsiDriver, '_add_lun_to_table', mock.Mock())
    @mock.patch.object(na_utils, 'LOG', mock.Mock())
    @mock.patch.object(ntap_iscsi, 'get_volume_extra_specs',
                       mock.Mock(return_value={'netapp_thick_provisioned':
                                               'true'}))
    def test_create_volume_deprecated_extra_spec(self):

        self.driver.create_volume({'name': 'lun1', 'size': 100,
                                   'id': uuid.uuid4(),
                                   'host': 'hostname@backend#vol1'})
        warn_msg = 'Extra spec netapp_thick_provisioned is deprecated.  ' \
                   'Use netapp_thin_provisioned instead.'
        na_utils.LOG.warning.assert_called_once_with(warn_msg)

    def test_update_volume_stats_is_abstract(self):
        self.assertRaises(NotImplementedError,
                          self.driver._update_volume_stats)

    def test_initialize_connection_no_target_details_found(self):
        fake_volume = {'name': 'mock-vol'}
        fake_connector = {'initiator': 'iqn.mock'}
        self.driver._map_lun = mock.Mock(return_value='mocked-lun-id')
        self.driver.zapi_client.get_iscsi_service_details = mock.Mock(
            return_value='mocked-iqn')
        self.driver.zapi_client.get_target_details = mock.Mock(return_value=[])
        expected = (_('No iscsi target details were found for LUN %s')
                    % fake_volume['name'])
        try:
            self.driver.initialize_connection(fake_volume, fake_connector)
        except exception.VolumeBackendAPIException as exc:
            if expected not in six.text_type(exc):
                self.fail(_('Expected exception message is missing'))
        else:
            self.fail(_('VolumeBackendAPIException not raised'))


class NetAppiSCSICModeTestCase(test.TestCase):
    """Test case for NetApp's C-Mode iSCSI driver."""

    def setUp(self):
        super(NetAppiSCSICModeTestCase, self).setUp()
        self.driver = ntap_iscsi.NetAppDirectCmodeISCSIDriver(
            configuration=mock.Mock())
        self.driver.client = mock.Mock()
        self.driver.zapi_client = mock.Mock()
        self.driver.vserver = mock.Mock()
        self.driver.ssc_vols = None

    def tearDown(self):
        super(NetAppiSCSICModeTestCase, self).tearDown()

    def test_clone_lun_zero_block_count(self):
        """Test for when clone lun is not passed a block count."""

        self.driver._get_lun_attr = mock.Mock(return_value={'Volume':
                                                            'fakeLUN'})
        self.driver.zapi_client = mock.Mock()
        self.driver.zapi_client.get_lun_by_args.return_value = [
            mock.Mock(spec=ntapi.NaElement)]
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

        self.driver._clone_lun('fakeLUN', 'newFakeLUN')

        self.driver.zapi_client.clone_lun.assert_called_once_with(
            'fakeLUN', 'fakeLUN', 'newFakeLUN', 'true', block_count=0,
            dest_block=0, src_block=0)

    @mock.patch.object(ssc_utils, 'refresh_cluster_ssc', mock.Mock())
    @mock.patch.object(iscsiCmodeDriver, '_get_pool_stats', mock.Mock())
    @mock.patch.object(na_utils, 'provide_ems', mock.Mock())
    def test_vol_stats_calls_provide_ems(self):
        self.driver.get_volume_stats(refresh=True)
        self.assertEqual(na_utils.provide_ems.call_count, 1)

    def test_create_lun(self):
        self.driver._update_stale_vols = mock.Mock()

        self.driver.create_lun(FAKE_VOLUME,
                               FAKE_LUN,
                               FAKE_SIZE,
                               FAKE_METADATA)

        self.driver.zapi_client.create_lun.assert_called_once_with(
            FAKE_VOLUME, FAKE_LUN, FAKE_SIZE,
            FAKE_METADATA, None)

        self.assertEqual(1, self.driver._update_stale_vols.call_count)


class NetAppiSCSI7ModeTestCase(test.TestCase):
    """Test case for NetApp's 7-Mode iSCSI driver."""

    def setUp(self):
        super(NetAppiSCSI7ModeTestCase, self).setUp()
        self.driver = ntap_iscsi.NetAppDirect7modeISCSIDriver(
            configuration=mock.Mock())
        self.driver.client = mock.Mock()
        self.driver.zapi_client = mock.Mock()
        self.driver.vfiler = mock.Mock()

    def tearDown(self):
        super(NetAppiSCSI7ModeTestCase, self).tearDown()

    def test_clone_lun_zero_block_count(self):
        """Test for when clone lun is not passed a block count."""

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
               'path': '/vol/fakeLUN/fakeLUN',
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
        self.driver._get_lun_attr = mock.Mock(return_value={
            'Volume': 'fakeLUN', 'Path': '/vol/fake/fakeLUN'})
        self.driver.zapi_client = mock.Mock()
        self.driver.zapi_client.get_lun_by_args.return_value = [lun]
        self.driver._add_lun_to_table = mock.Mock()

        self.driver._clone_lun('fakeLUN', 'newFakeLUN')

        self.driver.zapi_client.clone_lun.assert_called_once_with(
            '/vol/fake/fakeLUN', '/vol/fake/newFakeLUN', 'fakeLUN',
            'newFakeLUN', 'true', block_count=0, dest_block=0, src_block=0)

    @mock.patch.object(iscsi7modeDriver, '_refresh_volume_info', mock.Mock())
    @mock.patch.object(iscsi7modeDriver, '_get_pool_stats', mock.Mock())
    @mock.patch.object(na_utils, 'provide_ems', mock.Mock())
    def test_vol_stats_calls_provide_ems(self):
        self.driver.get_volume_stats(refresh=True)
        self.assertEqual(na_utils.provide_ems.call_count, 1)

    def test_create_lun(self):
        self.driver.vol_refresh_voluntary = False

        self.driver.create_lun(FAKE_VOLUME,
                               FAKE_LUN,
                               FAKE_SIZE,
                               FAKE_METADATA)

        self.driver.zapi_client.create_lun.assert_called_once_with(
            FAKE_VOLUME, FAKE_LUN, FAKE_SIZE,
            FAKE_METADATA, None)

        self.assertTrue(self.driver.vol_refresh_voluntary)
