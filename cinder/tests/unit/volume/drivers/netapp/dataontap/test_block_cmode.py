# Copyright (c) 2014 Alex Meade.  All rights reserved.
# Copyright (c) 2014 Clinton Knight.  All rights reserved.
# Copyright (c) 2015 Tom Barron.  All rights reserved.
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
from cinder.openstack.common import loopingcall
from cinder import test
import cinder.tests.unit.volume.drivers.netapp.dataontap.fakes as fake
import cinder.tests.unit.volume.drivers.netapp.fakes as na_fakes
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
        self.fake_lun = block_base.NetAppLun(fake.LUN_HANDLE, fake.LUN_NAME,
                                             fake.SIZE, None)
        self.mock_object(self.library, 'lun_table')
        self.library.lun_table = {fake.LUN_NAME: self.fake_lun}
        self.mock_object(block_base.NetAppBlockStorageLibrary, 'delete_volume')

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

    def test_check_for_setup_error(self):
        super_check_for_setup_error = self.mock_object(
            block_base.NetAppBlockStorageLibrary, 'check_for_setup_error')
        mock_check_ssc_api_permissions = self.mock_object(
            ssc_cmode, 'check_ssc_api_permissions')
        mock_start_periodic_tasks = self.mock_object(
            self.library, '_start_periodic_tasks')

        self.library.check_for_setup_error()

        self.assertEqual(1, super_check_for_setup_error.call_count)
        mock_check_ssc_api_permissions.assert_called_once_with(
            self.library.zapi_client)
        self.assertEqual(1, mock_start_periodic_tasks.call_count)

    def test_find_mapped_lun_igroup(self):
        igroups = [fake.IGROUP1]
        self.zapi_client.get_igroup_by_initiators.return_value = igroups

        lun_maps = [{'initiator-group': fake.IGROUP1_NAME,
                     'lun-id': '1',
                     'vserver': fake.VSERVER_NAME}]
        self.zapi_client.get_lun_map.return_value = lun_maps

        (igroup, lun_id) = self.library._find_mapped_lun_igroup(
            fake.LUN_PATH, fake.FC_FORMATTED_INITIATORS)

        self.assertEqual(fake.IGROUP1_NAME, igroup)
        self.assertEqual('1', lun_id)

    def test_find_mapped_lun_igroup_initiator_mismatch(self):
        self.zapi_client.get_igroup_by_initiators.return_value = []

        lun_maps = [{'initiator-group': fake.IGROUP1_NAME,
                     'lun-id': '1',
                     'vserver': fake.VSERVER_NAME}]
        self.zapi_client.get_lun_map.return_value = lun_maps

        (igroup, lun_id) = self.library._find_mapped_lun_igroup(
            fake.LUN_PATH, fake.FC_FORMATTED_INITIATORS)

        self.assertIsNone(igroup)
        self.assertIsNone(lun_id)

    def test_find_mapped_lun_igroup_name_mismatch(self):
        igroups = [{'initiator-group-os-type': 'linux',
                    'initiator-group-type': 'fcp',
                    'initiator-group-name': 'igroup2'}]
        self.zapi_client.get_igroup_by_initiators.return_value = igroups

        lun_maps = [{'initiator-group': fake.IGROUP1_NAME,
                     'lun-id': '1',
                     'vserver': fake.VSERVER_NAME}]
        self.zapi_client.get_lun_map.return_value = lun_maps

        (igroup, lun_id) = self.library._find_mapped_lun_igroup(
            fake.LUN_PATH, fake.FC_FORMATTED_INITIATORS)

        self.assertIsNone(igroup)
        self.assertIsNone(lun_id)

    def test_find_mapped_lun_igroup_no_igroup_prefix(self):
        igroups = [{'initiator-group-os-type': 'linux',
                    'initiator-group-type': 'fcp',
                    'initiator-group-name': 'igroup2'}]
        self.zapi_client.get_igroup_by_initiators.return_value = igroups

        lun_maps = [{'initiator-group': 'igroup2',
                     'lun-id': '1',
                     'vserver': fake.VSERVER_NAME}]
        self.zapi_client.get_lun_map.return_value = lun_maps

        (igroup, lun_id) = self.library._find_mapped_lun_igroup(
            fake.LUN_PATH, fake.FC_FORMATTED_INITIATORS)

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
            dest_block=0, src_block=0, qos_policy_group_name=None)

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

        self.library._create_lun(fake.VOLUME_ID, fake.LUN_ID,
                                 fake.LUN_SIZE, fake.LUN_METADATA)

        self.library.zapi_client.create_lun.assert_called_once_with(
            fake.VOLUME_ID, fake.LUN_ID, fake.LUN_SIZE, fake.LUN_METADATA,
            None)
        self.assertEqual(1, self.library._update_stale_vols.call_count)

    @mock.patch.object(ssc_cmode, 'get_volumes_for_specs')
    @mock.patch.object(ssc_cmode, 'get_cluster_latest_ssc')
    def test_check_volume_type_for_lun_fail(self, get_ssc, get_vols):
        self.library.ssc_vols = ['vol']
        fake_extra_specs = {'specs': 's'}
        get_vols.return_value = [ssc_cmode.NetAppVolume(name='name',
                                                        vserver='vs')]
        mock_lun = block_base.NetAppLun('handle', 'name', '1',
                                        {'Volume': 'fake', 'Path': '/vol/lun'})
        self.assertRaises(exception.ManageExistingVolumeTypeMismatch,
                          self.library._check_volume_type_for_lun,
                          {'vol': 'vol'}, mock_lun, {'ref': 'ref'},
                          fake_extra_specs)
        get_vols.assert_called_with(['vol'], {'specs': 's'})
        self.assertEqual(1, get_ssc.call_count)

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

    def test_delete_volume(self):
        self.mock_object(block_base.NetAppLun, 'get_metadata_property',
                         mock.Mock(return_value=fake.POOL_NAME))
        self.mock_object(self.library, '_update_stale_vols')
        self.mock_object(na_utils, 'get_valid_qos_policy_group_info',
                         mock.Mock(
                             return_value=fake.QOS_POLICY_GROUP_INFO))
        self.mock_object(self.library, '_mark_qos_policy_group_for_deletion')

        self.library.delete_volume(fake.VOLUME)

        self.assertEqual(1,
                         block_base.NetAppLun.get_metadata_property.call_count)
        block_base.NetAppBlockStorageLibrary.delete_volume\
            .assert_called_once_with(fake.VOLUME)
        na_utils.get_valid_qos_policy_group_info.assert_called_once_with(
            fake.VOLUME)
        self.library._mark_qos_policy_group_for_deletion\
            .assert_called_once_with(fake.QOS_POLICY_GROUP_INFO)
        self.assertEqual(1, self.library._update_stale_vols.call_count)

    def test_delete_volume_no_netapp_vol(self):
        self.mock_object(block_base.NetAppLun, 'get_metadata_property',
                         mock.Mock(return_value=None))
        self.mock_object(self.library, '_update_stale_vols')
        self.mock_object(na_utils, 'get_valid_qos_policy_group_info',
                         mock.Mock(
                             return_value=fake.QOS_POLICY_GROUP_INFO))
        self.mock_object(self.library, '_mark_qos_policy_group_for_deletion')

        self.library.delete_volume(fake.VOLUME)

        block_base.NetAppLun.get_metadata_property.assert_called_once_with(
            'Volume')
        block_base.NetAppBlockStorageLibrary.delete_volume\
            .assert_called_once_with(fake.VOLUME)
        self.library._mark_qos_policy_group_for_deletion\
            .assert_called_once_with(fake.QOS_POLICY_GROUP_INFO)
        self.assertEqual(0, self.library._update_stale_vols.call_count)

    def test_delete_volume_get_valid_qos_policy_group_info_exception(self):
        self.mock_object(block_base.NetAppLun, 'get_metadata_property',
                         mock.Mock(return_value=fake.NETAPP_VOLUME))
        self.mock_object(self.library, '_update_stale_vols')
        self.mock_object(na_utils, 'get_valid_qos_policy_group_info',
                         mock.Mock(side_effect=exception.Invalid))
        self.mock_object(self.library, '_mark_qos_policy_group_for_deletion')

        self.library.delete_volume(fake.VOLUME)

        block_base.NetAppLun.get_metadata_property.assert_called_once_with(
            'Volume')
        block_base.NetAppBlockStorageLibrary.delete_volume\
            .assert_called_once_with(fake.VOLUME)
        self.library._mark_qos_policy_group_for_deletion\
            .assert_called_once_with(None)
        self.assertEqual(1, self.library._update_stale_vols.call_count)

    def test_setup_qos_for_volume(self):
        self.mock_object(na_utils, 'get_valid_qos_policy_group_info',
                         mock.Mock(
                             return_value=fake.QOS_POLICY_GROUP_INFO))
        self.mock_object(self.zapi_client, 'provision_qos_policy_group')

        result = self.library._setup_qos_for_volume(fake.VOLUME,
                                                    fake.EXTRA_SPECS)

        self.assertEqual(fake.QOS_POLICY_GROUP_INFO, result)
        self.zapi_client.provision_qos_policy_group.\
            assert_called_once_with(fake.QOS_POLICY_GROUP_INFO)

    def test_setup_qos_for_volume_exception_path(self):
        self.mock_object(na_utils, 'get_valid_qos_policy_group_info',
                         mock.Mock(
                             side_effect=exception.Invalid))
        self.mock_object(self.zapi_client, 'provision_qos_policy_group')

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.library._setup_qos_for_volume, fake.VOLUME,
                          fake.EXTRA_SPECS)

        self.assertEqual(0,
                         self.zapi_client.
                         provision_qos_policy_group.call_count)

    def test_mark_qos_policy_group_for_deletion(self):
        self.mock_object(self.zapi_client,
                         'mark_qos_policy_group_for_deletion')

        self.library._mark_qos_policy_group_for_deletion(
            fake.QOS_POLICY_GROUP_INFO)

        self.zapi_client.mark_qos_policy_group_for_deletion\
            .assert_called_once_with(fake.QOS_POLICY_GROUP_INFO)

    def test_unmanage(self):
        self.mock_object(na_utils, 'get_valid_qos_policy_group_info',
                         mock.Mock(return_value=fake.QOS_POLICY_GROUP_INFO))
        self.mock_object(self.library, '_mark_qos_policy_group_for_deletion')
        self.mock_object(block_base.NetAppBlockStorageLibrary, 'unmanage')

        self.library.unmanage(fake.VOLUME)

        na_utils.get_valid_qos_policy_group_info.assert_called_once_with(
            fake.VOLUME)
        self.library._mark_qos_policy_group_for_deletion\
            .assert_called_once_with(fake.QOS_POLICY_GROUP_INFO)
        block_base.NetAppBlockStorageLibrary.unmanage.assert_called_once_with(
            fake.VOLUME)

    def test_unmanage_w_invalid_qos_policy(self):
        self.mock_object(na_utils, 'get_valid_qos_policy_group_info',
                         mock.Mock(side_effect=exception.Invalid))
        self.mock_object(self.library, '_mark_qos_policy_group_for_deletion')
        self.mock_object(block_base.NetAppBlockStorageLibrary, 'unmanage')

        self.library.unmanage(fake.VOLUME)

        na_utils.get_valid_qos_policy_group_info.assert_called_once_with(
            fake.VOLUME)
        self.library._mark_qos_policy_group_for_deletion\
            .assert_called_once_with(None)
        block_base.NetAppBlockStorageLibrary.unmanage.assert_called_once_with(
            fake.VOLUME)

    def test_manage_existing_lun_same_name(self):
        mock_lun = block_base.NetAppLun('handle', 'name', '1',
                                        {'Path': '/vol/vol1/name'})
        self.library._get_existing_vol_with_manage_ref = mock.Mock(
            return_value=mock_lun)
        self.mock_object(na_utils, 'get_volume_extra_specs')
        self.mock_object(na_utils, 'log_extra_spec_warnings')
        self.library._check_volume_type_for_lun = mock.Mock()
        self.library._setup_qos_for_volume = mock.Mock()
        self.mock_object(na_utils, 'get_qos_policy_group_name_from_info',
                         mock.Mock(return_value=fake.QOS_POLICY_GROUP_NAME))
        self.library._add_lun_to_table = mock.Mock()
        self.zapi_client.move_lun = mock.Mock()
        mock_set_lun_qos_policy_group = self.mock_object(
            self.zapi_client, 'set_lun_qos_policy_group')

        self.library.manage_existing({'name': 'name'}, {'ref': 'ref'})

        self.library._get_existing_vol_with_manage_ref.assert_called_once_with(
            {'ref': 'ref'})
        self.assertEqual(1, self.library._check_volume_type_for_lun.call_count)
        self.assertEqual(1, self.library._add_lun_to_table.call_count)
        self.assertEqual(0, self.zapi_client.move_lun.call_count)
        self.assertEqual(1, mock_set_lun_qos_policy_group.call_count)

    def test_manage_existing_lun_new_path(self):
        mock_lun = block_base.NetAppLun(
            'handle', 'name', '1', {'Path': '/vol/vol1/name'})
        self.library._get_existing_vol_with_manage_ref = mock.Mock(
            return_value=mock_lun)
        self.mock_object(na_utils, 'get_volume_extra_specs')
        self.mock_object(na_utils, 'log_extra_spec_warnings')
        self.library._check_volume_type_for_lun = mock.Mock()
        self.library._add_lun_to_table = mock.Mock()
        self.zapi_client.move_lun = mock.Mock()

        self.library.manage_existing({'name': 'volume'}, {'ref': 'ref'})

        self.assertEqual(
            2, self.library._get_existing_vol_with_manage_ref.call_count)
        self.assertEqual(1, self.library._check_volume_type_for_lun.call_count)
        self.assertEqual(1, self.library._add_lun_to_table.call_count)
        self.zapi_client.move_lun.assert_called_once_with(
            '/vol/vol1/name', '/vol/vol1/volume')

    def test_start_periodic_tasks(self):

        mock_remove_unused_qos_policy_groups = self.mock_object(
            self.zapi_client,
            'remove_unused_qos_policy_groups')

        harvest_qos_periodic_task = mock.Mock()
        mock_loopingcall = self.mock_object(
            loopingcall,
            'FixedIntervalLoopingCall',
            mock.Mock(side_effect=[harvest_qos_periodic_task]))

        self.library._start_periodic_tasks()

        mock_loopingcall.assert_has_calls([
            mock.call(mock_remove_unused_qos_policy_groups)])
        self.assertTrue(harvest_qos_periodic_task.start.called)
