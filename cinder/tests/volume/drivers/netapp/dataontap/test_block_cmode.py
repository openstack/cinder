# Copyright (c) 2014 Alex Meade.  All rights reserved.
# Copyright (c) 2014 Clinton Knight.  All rights reserved.
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


import mock

from cinder import exception
from cinder import test
import cinder.tests.volume.drivers.netapp.dataontap.fakes as fake
import cinder.tests.volume.drivers.netapp.fakes as na_fakes
from cinder.volume.drivers.netapp.dataontap import block_base
from cinder.volume.drivers.netapp.dataontap import block_cmode
from cinder.volume.drivers.netapp.dataontap.client import api as netapp_api
from cinder.volume.drivers.netapp.dataontap.client import client_base
from cinder.volume.drivers.netapp.dataontap import ssc_cmode
from cinder.volume.drivers.netapp import utils as na_utils


class NetAppBlockStorageCmodeLibraryTestCase(test.TestCase):
    """Test case for NetApp's C-Mode iSCSI library."""

    def setUp(self):
        super(NetAppBlockStorageCmodeLibraryTestCase, self).setUp()

        kwargs = {'configuration': self.get_config_cmode()}
        self.library = block_cmode.NetAppBlockStorageCmodeLibrary(
            'driver', 'protocol', **kwargs)

        self.library.zapi_client = mock.Mock()
        self.zapi_client = self.library.zapi_client
        self.library.vserver = mock.Mock()
        self.library.ssc_vols = None

    def tearDown(self):
        super(NetAppBlockStorageCmodeLibraryTestCase, self).tearDown()

    def get_config_cmode(self):
        config = na_fakes.create_configuration_cmode()
        config.netapp_storage_protocol = 'iscsi'
        config.netapp_login = 'admin'
        config.netapp_password = 'pass'
        config.netapp_server_hostname = '127.0.0.1'
        config.netapp_transport_type = 'https'
        config.netapp_server_port = '443'
        config.netapp_vserver = 'openstack'
        return config

    @mock.patch.object(client_base.Client, 'get_ontapi_version',
                       mock.MagicMock(return_value=(1, 20)))
    @mock.patch.object(na_utils, 'check_flags')
    @mock.patch.object(block_base.NetAppBlockStorageLibrary, 'do_setup')
    def test_do_setup(self, super_do_setup, mock_check_flags):
        context = mock.Mock()

        self.library.do_setup(context)

        super_do_setup.assert_called_once_with(context)
        self.assertEqual(1, mock_check_flags.call_count)

    @mock.patch.object(block_base.NetAppBlockStorageLibrary,
                       'check_for_setup_error')
    @mock.patch.object(ssc_cmode, 'check_ssc_api_permissions')
    def test_check_for_setup_error(self, mock_check_ssc_api_permissions,
                                   super_check_for_setup_error):

        self.library.check_for_setup_error()

        super_check_for_setup_error.assert_called_once_with()
        mock_check_ssc_api_permissions.assert_called_once_with(
            self.library.zapi_client)

    def test_find_mapped_lun_igroup(self):
        igroups = [fake.IGROUP1]
        self.zapi_client.get_igroup_by_initiators.return_value = igroups

        lun_maps = [{'initiator-group': fake.IGROUP1_NAME,
                     'lun-id': '1',
                     'vserver': fake.VSERVER1_NAME}]
        self.zapi_client.get_lun_map.return_value = lun_maps

        (igroup, lun_id) = self.library._find_mapped_lun_igroup(
            fake.LUN1, fake.FC_FORMATTED_INITIATORS)

        self.assertEqual(fake.IGROUP1_NAME, igroup)
        self.assertEqual('1', lun_id)

    def test_find_mapped_lun_igroup_initiator_mismatch(self):
        self.zapi_client.get_igroup_by_initiators.return_value = []

        lun_maps = [{'initiator-group': fake.IGROUP1_NAME,
                     'lun-id': '1',
                     'vserver': fake.VSERVER1_NAME}]
        self.zapi_client.get_lun_map.return_value = lun_maps

        (igroup, lun_id) = self.library._find_mapped_lun_igroup(
            fake.LUN1, fake.FC_FORMATTED_INITIATORS)

        self.assertIsNone(igroup)
        self.assertIsNone(lun_id)

    def test_find_mapped_lun_igroup_name_mismatch(self):
        igroups = [{'initiator-group-os-type': 'linux',
                    'initiator-group-type': 'fcp',
                    'initiator-group-name': 'igroup2'}]
        self.zapi_client.get_igroup_by_initiators.return_value = igroups

        lun_maps = [{'initiator-group': fake.IGROUP1_NAME,
                     'lun-id': '1',
                     'vserver': fake.VSERVER1_NAME}]
        self.zapi_client.get_lun_map.return_value = lun_maps

        (igroup, lun_id) = self.library._find_mapped_lun_igroup(
            fake.LUN1, fake.FC_FORMATTED_INITIATORS)

        self.assertIsNone(igroup)
        self.assertIsNone(lun_id)

    def test_find_mapped_lun_igroup_no_igroup_prefix(self):
        igroups = [{'initiator-group-os-type': 'linux',
                    'initiator-group-type': 'fcp',
                    'initiator-group-name': 'igroup2'}]
        self.zapi_client.get_igroup_by_initiators.return_value = igroups

        lun_maps = [{'initiator-group': 'igroup2',
                     'lun-id': '1',
                     'vserver': fake.VSERVER1_NAME}]
        self.zapi_client.get_lun_map.return_value = lun_maps

        (igroup, lun_id) = self.library._find_mapped_lun_igroup(
            fake.LUN1, fake.FC_FORMATTED_INITIATORS)

        self.assertIsNone(igroup)
        self.assertIsNone(lun_id)

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

    def test_get_fc_target_wwpns(self):
        ports = [fake.FC_FORMATTED_TARGET_WWPNS[0],
                 fake.FC_FORMATTED_TARGET_WWPNS[1]]
        self.zapi_client.get_fc_target_wwpns.return_value = ports

        result = self.library._get_fc_target_wwpns()

        self.assertSetEqual(set(ports), set(result))

    @mock.patch.object(ssc_cmode, 'refresh_cluster_ssc', mock.Mock())
    @mock.patch.object(block_cmode.NetAppBlockStorageCmodeLibrary,
                       '_get_pool_stats', mock.Mock())
    def test_vol_stats_calls_provide_ems(self):
        self.library.zapi_client.provide_ems = mock.Mock()

        self.library.get_volume_stats(refresh=True)

        self.assertEqual(self.library.zapi_client.provide_ems.call_count, 1)

    def test_create_lun(self):
        self.library._update_stale_vols = mock.Mock()

        self.library._create_lun(fake.VOLUME, fake.LUN,
                                 fake.SIZE, fake.METADATA)

        self.library.zapi_client.create_lun.assert_called_once_with(
            fake.VOLUME, fake.LUN, fake.SIZE, fake.METADATA, None)
        self.assertEqual(1, self.library._update_stale_vols.call_count)

    @mock.patch.object(ssc_cmode, 'get_volumes_for_specs')
    @mock.patch.object(ssc_cmode, 'get_cluster_latest_ssc')
    @mock.patch.object(na_utils, 'get_volume_extra_specs')
    def test_check_volume_type_for_lun_fail(
            self, get_specs, get_ssc, get_vols):
        self.library.ssc_vols = ['vol']
        get_specs.return_value = {'specs': 's'}
        get_vols.return_value = [ssc_cmode.NetAppVolume(name='name',
                                                        vserver='vs')]
        mock_lun = block_base.NetAppLun('handle', 'name', '1',
                                        {'Volume': 'fake', 'Path': '/vol/lun'})
        self.assertRaises(exception.ManageExistingVolumeTypeMismatch,
                          self.library._check_volume_type_for_lun,
                          {'vol': 'vol'}, mock_lun, {'ref': 'ref'})
        get_specs.assert_called_once_with({'vol': 'vol'})
        get_vols.assert_called_with(['vol'], {'specs': 's'})
        self.assertEqual(1, get_ssc.call_count)

    @mock.patch.object(block_cmode.LOG, 'error')
    @mock.patch.object(ssc_cmode, 'get_volumes_for_specs')
    @mock.patch.object(ssc_cmode, 'get_cluster_latest_ssc')
    @mock.patch.object(na_utils, 'get_volume_extra_specs')
    def test_check_volume_type_for_lun_qos_fail(
            self, get_specs, get_ssc, get_vols, driver_log):
        self.zapi_client.connection.set_api_version(1, 20)
        self.library.ssc_vols = ['vol']
        get_specs.return_value = {'specs': 's',
                                  'netapp:qos_policy_group': 'qos'}
        get_vols.return_value = [ssc_cmode.NetAppVolume(name='name',
                                                        vserver='vs')]
        mock_lun = block_base.NetAppLun('handle', 'name', '1',
                                        {'Volume': 'name', 'Path': '/vol/lun'})
        self.zapi_client.set_lun_qos_policy_group = mock.Mock(
            side_effect=netapp_api.NaApiError)
        self.assertRaises(exception.ManageExistingVolumeTypeMismatch,
                          self.library._check_volume_type_for_lun,
                          {'vol': 'vol'}, mock_lun, {'ref': 'ref'})
        get_specs.assert_called_once_with({'vol': 'vol'})
        get_vols.assert_called_with(['vol'], {'specs': 's'})
        self.assertEqual(0, get_ssc.call_count)
        self.zapi_client.set_lun_qos_policy_group.assert_called_once_with(
            '/vol/lun', 'qos')
        self.assertEqual(1, driver_log.call_count)

    def test_get_preferred_target_from_list(self):
        target_details_list = fake.ISCSI_TARGET_DETAILS_LIST
        operational_addresses = [
            target['address']
            for target in target_details_list[2:]]
        self.zapi_client.get_operational_network_interface_addresses = (
            mock.Mock(return_value=operational_addresses))

        result = self.library._get_preferred_target_from_list(
            target_details_list)

        self.assertEqual(target_details_list[2], result)
