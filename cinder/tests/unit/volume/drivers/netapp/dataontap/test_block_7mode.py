# Copyright (c) 2014 Alex Meade.  All rights reserved.
# Copyright (c) 2014 Clinton Knight.  All rights reserved.
# Copyright (c) 2015 Tom Barron.  All rights reserved.
# Copyright (c) 2015 Goutham Pacha Ravi. All rights reserved.
# Copyright (c) 2016 Mike Rooney. All rights reserved.
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
Mock unit tests for the NetApp block storage 7-mode library
"""


import ddt
from lxml import etree
import mock

from oslo_utils import timeutils
from oslo_utils import units

from cinder import exception
from cinder.objects import fields
from cinder import test
import cinder.tests.unit.volume.drivers.netapp.dataontap.client.fakes \
    as client_fakes
import cinder.tests.unit.volume.drivers.netapp.dataontap.fakes as fake
import cinder.tests.unit.volume.drivers.netapp.fakes as na_fakes
from cinder.volume.drivers.netapp.dataontap import block_7mode
from cinder.volume.drivers.netapp.dataontap import block_base
from cinder.volume.drivers.netapp.dataontap.client import api as netapp_api
from cinder.volume.drivers.netapp.dataontap.client import client_base
from cinder.volume.drivers.netapp.dataontap.performance import perf_7mode
from cinder.volume.drivers.netapp.dataontap.utils import utils as dot_utils
from cinder.volume.drivers.netapp import utils as na_utils
from cinder.volume import utils as volume_utils


@ddt.ddt
class NetAppBlockStorage7modeLibraryTestCase(test.TestCase):
    """Test case for NetApp's 7-Mode iSCSI library."""

    def setUp(self):
        super(NetAppBlockStorage7modeLibraryTestCase, self).setUp()

        kwargs = {
            'configuration': self.get_config_7mode(),
            'host': 'openstack@7modeblock',
        }
        self.library = block_7mode.NetAppBlockStorage7modeLibrary(
            'driver', 'protocol', **kwargs)

        self.library.zapi_client = mock.Mock()
        self.zapi_client = self.library.zapi_client
        self.library.perf_library = mock.Mock()
        self.library.vfiler = mock.Mock()
        # Deprecated option
        self.library.configuration.netapp_volume_list = None

    def get_config_7mode(self):
        config = na_fakes.create_configuration_7mode()
        config.netapp_storage_protocol = 'iscsi'
        config.netapp_login = 'admin'
        config.netapp_password = 'pass'
        config.netapp_server_hostname = '127.0.0.1'
        config.netapp_transport_type = 'http'
        config.netapp_server_port = '80'
        return config

    @mock.patch.object(perf_7mode, 'Performance7modeLibrary', mock.Mock())
    @mock.patch.object(client_base.Client, 'get_ontapi_version',
                       mock.MagicMock(return_value=(1, 20)))
    @mock.patch.object(block_7mode.NetAppBlockStorage7modeLibrary,
                       '_get_root_volume_name')
    @mock.patch.object(block_7mode.NetAppBlockStorage7modeLibrary,
                       '_do_partner_setup')
    @mock.patch.object(block_base.NetAppBlockStorageLibrary, 'do_setup')
    def test_do_setup(self, super_do_setup, mock_do_partner_setup,
                      mock_get_root_volume_name):

        self.mock_object(client_base.Client, '_init_ssh_client')
        mock_get_root_volume_name.return_value = 'vol0'
        context = mock.Mock()

        self.library.do_setup(context)

        super_do_setup.assert_called_once_with(context)
        mock_do_partner_setup.assert_called_once_with()
        mock_get_root_volume_name.assert_called_once_with()

    @mock.patch.object(client_base.Client, 'get_ontapi_version',
                       mock.MagicMock(return_value=(1, 20)))
    def test_do_partner_setup(self):
        self.mock_object(client_base.Client, '_init_ssh_client')
        self.library.configuration.netapp_partner_backend_name = 'partner'

        self.library._do_partner_setup()

        self.assertIsNotNone(self.library.partner_zapi_client)

    @mock.patch.object(client_base.Client, 'get_ontapi_version',
                       mock.MagicMock(return_value=(1, 20)))
    def test_do_partner_setup_no_partner(self):
        self.mock_object(client_base.Client, '_init_ssh_client')
        self.library._do_partner_setup()

        self.assertFalse(hasattr(self.library, 'partner_zapi_client'))

    @mock.patch.object(
        block_base.NetAppBlockStorageLibrary, 'check_for_setup_error')
    def test_check_for_setup_error(self, super_check_for_setup_error):
        self.zapi_client.get_ontapi_version.return_value = (1, 9)
        self.mock_object(self.library, '_refresh_volume_info')
        self.library.volume_list = ['open1', 'open2']
        mock_add_looping_tasks = self.mock_object(
            self.library, '_add_looping_tasks')

        self.library.check_for_setup_error()

        mock_add_looping_tasks.assert_called_once_with()
        super_check_for_setup_error.assert_called_once_with()

    def test_check_for_setup_error_no_filtered_pools(self):
        self.zapi_client.get_ontapi_version.return_value = (1, 9)
        self.mock_object(self.library, '_refresh_volume_info')
        self.library.volume_list = []

        self.assertRaises(exception.NetAppDriverException,
                          self.library.check_for_setup_error)

    @ddt.data(None, (1, 8))
    def test_check_for_setup_error_unsupported_or_no_version(self, version):
        self.zapi_client.get_ontapi_version.return_value = version
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.library.check_for_setup_error)

    def test_handle_ems_logging(self):

        self.library.volume_list = ['vol0', 'vol1', 'vol2']
        self.mock_object(
            dot_utils, 'build_ems_log_message_0',
            return_value='fake_base_ems_log_message')
        self.mock_object(
            dot_utils, 'build_ems_log_message_1',
            return_value='fake_pool_ems_log_message')
        mock_send_ems_log_message = self.mock_object(
            self.zapi_client, 'send_ems_log_message')

        self.library._handle_ems_logging()

        mock_send_ems_log_message.assert_has_calls([
            mock.call('fake_base_ems_log_message'),
            mock.call('fake_pool_ems_log_message'),
        ])
        dot_utils.build_ems_log_message_0.assert_called_once_with(
            self.library.driver_name, self.library.app_version,
            self.library.driver_mode)
        dot_utils.build_ems_log_message_1.assert_called_once_with(
            self.library.driver_name, self.library.app_version, None,
            self.library.volume_list, [])

    def test__get_volume_model_update(self):
        """Driver is not expected to return a model update."""
        self.assertIsNone(
            self.library._get_volume_model_update(fake.VOLUME_REF))

    @ddt.data(None, fake.VFILER)
    def test__get_owner(self, vfiler):
        self.library.configuration.netapp_server_hostname = 'openstack'
        self.library.vfiler = vfiler
        expected_owner = 'openstack'

        retval = self.library._get_owner()

        if vfiler:
            expected_owner += ':' + vfiler

        self.assertEqual(expected_owner, retval)

    def test_find_mapped_lun_igroup(self):
        response = netapp_api.NaElement(etree.XML("""
<results status="passed">
    <initiator-groups>
      <initiator-group-info>
        <initiator-group-name>%(initiator-group-name)s</initiator-group-name>
        <initiator-group-type>%(initiator-group-type)s</initiator-group-type>
        <initiator-group-uuid>1477ee47-0e1f-4b35-a82c-dcca0b76fc44
        </initiator-group-uuid>
        <initiator-group-os-type>linux</initiator-group-os-type>
        <initiator-group-throttle-reserve>0</initiator-group-throttle-reserve>
        <initiator-group-throttle-borrow>false
        </initiator-group-throttle-borrow>
        <initiator-group-vsa-enabled>false</initiator-group-vsa-enabled>
        <initiator-group-alua-enabled>true</initiator-group-alua-enabled>
        <initiator-group-report-scsi-name-enabled>true
        </initiator-group-report-scsi-name-enabled>
        <initiator-group-use-partner>true</initiator-group-use-partner>
        <initiators>
          <initiator-info>
            <initiator-name>21:00:00:24:ff:40:6c:c3</initiator-name>
          </initiator-info>
          <initiator-info>
            <initiator-name>21:00:00:24:ff:40:6c:c2</initiator-name>
            <initiator-alias-info>
              <initiator-alias>Centos</initiator-alias>
            </initiator-alias-info>
          </initiator-info>
        </initiators>
        <lun-id>2</lun-id>
      </initiator-group-info>
    </initiator-groups>
  </results>""" % fake.IGROUP1))
        initiators = fake.FC_FORMATTED_INITIATORS
        self.zapi_client.get_lun_map.return_value = response

        (igroup, lun_id) = self.library._find_mapped_lun_igroup('path',
                                                                initiators)

        self.assertEqual(fake.IGROUP1_NAME, igroup)
        self.assertEqual('2', lun_id)

    def test_find_mapped_lun_igroup_initiator_mismatch(self):
        response = netapp_api.NaElement(etree.XML("""
<results status="passed">
    <initiator-groups>
      <initiator-group-info>
        <initiator-group-name>openstack-igroup1</initiator-group-name>
        <initiator-group-type>fcp</initiator-group-type>
        <initiator-group-uuid>1477ee47-0e1f-4b35-a82c-dcca0b76fc44
        </initiator-group-uuid>
        <initiator-group-os-type>linux</initiator-group-os-type>
        <initiator-group-throttle-reserve>0</initiator-group-throttle-reserve>
        <initiator-group-throttle-borrow>false
        </initiator-group-throttle-borrow>
        <initiator-group-vsa-enabled>false</initiator-group-vsa-enabled>
        <initiator-group-alua-enabled>true</initiator-group-alua-enabled>
        <initiator-group-report-scsi-name-enabled>true
        </initiator-group-report-scsi-name-enabled>
        <initiator-group-use-partner>true</initiator-group-use-partner>
        <initiators>
          <initiator-info>
            <initiator-name>21:00:00:24:ff:40:6c:c3</initiator-name>
          </initiator-info>
        </initiators>
        <lun-id>2</lun-id>
      </initiator-group-info>
    </initiator-groups>
  </results>"""))
        initiators = fake.FC_FORMATTED_INITIATORS
        self.zapi_client.get_lun_map.return_value = response

        (igroup, lun_id) = self.library._find_mapped_lun_igroup('path',
                                                                initiators)

        self.assertIsNone(igroup)
        self.assertIsNone(lun_id)

    def test_find_mapped_lun_igroup_no_igroups(self):
        response = netapp_api.NaElement(etree.XML("""
  <results status="passed">
    <initiator-groups />
  </results>"""))
        initiators = fake.FC_FORMATTED_INITIATORS
        self.zapi_client.get_lun_map.return_value = response

        (igroup, lun_id) = self.library._find_mapped_lun_igroup('path',
                                                                initiators)

        self.assertIsNone(igroup)
        self.assertIsNone(lun_id)

    def test_find_mapped_lun_igroup_raises(self):
        self.zapi_client.get_lun_map.side_effect = netapp_api.NaApiError
        initiators = fake.FC_FORMATTED_INITIATORS
        self.assertRaises(netapp_api.NaApiError,
                          self.library._find_mapped_lun_igroup,
                          'path',
                          initiators)

    def test_has_luns_mapped_to_initiators_local_map(self):
        initiator_list = fake.FC_FORMATTED_INITIATORS
        self.zapi_client.has_luns_mapped_to_initiators.return_value = True
        self.library.partner_zapi_client = mock.Mock()

        result = self.library._has_luns_mapped_to_initiators(initiator_list)

        self.assertTrue(result)
        self.zapi_client.has_luns_mapped_to_initiators.assert_called_once_with(
            initiator_list)
        self.assertEqual(0, self.library.partner_zapi_client.
                         has_luns_mapped_to_initiators.call_count)

    def test_has_luns_mapped_to_initiators_partner_map(self):
        initiator_list = fake.FC_FORMATTED_INITIATORS
        self.zapi_client.has_luns_mapped_to_initiators.return_value = False
        self.library.partner_zapi_client = mock.Mock()
        self.library.partner_zapi_client.has_luns_mapped_to_initiators.\
            return_value = True

        result = self.library._has_luns_mapped_to_initiators(initiator_list)

        self.assertTrue(result)
        self.zapi_client.has_luns_mapped_to_initiators.assert_called_once_with(
            initiator_list)
        self.library.partner_zapi_client.has_luns_mapped_to_initiators.\
            assert_called_with(initiator_list)

    def test_has_luns_mapped_to_initiators_no_maps(self):
        initiator_list = fake.FC_FORMATTED_INITIATORS
        self.zapi_client.has_luns_mapped_to_initiators.return_value = False
        self.library.partner_zapi_client = mock.Mock()
        self.library.partner_zapi_client.has_luns_mapped_to_initiators.\
            return_value = False

        result = self.library._has_luns_mapped_to_initiators(initiator_list)

        self.assertFalse(result)
        self.zapi_client.has_luns_mapped_to_initiators.assert_called_once_with(
            initiator_list)
        self.library.partner_zapi_client.has_luns_mapped_to_initiators.\
            assert_called_with(initiator_list)

    def test_has_luns_mapped_to_initiators_no_partner(self):
        initiator_list = fake.FC_FORMATTED_INITIATORS
        self.zapi_client.has_luns_mapped_to_initiators.return_value = False
        self.library.partner_zapi_client = mock.Mock()
        self.library.partner_zapi_client.has_luns_mapped_to_initiators.\
            return_value = True

        result = self.library._has_luns_mapped_to_initiators(
            initiator_list, include_partner=False)

        self.assertFalse(result)
        self.zapi_client.has_luns_mapped_to_initiators.assert_called_once_with(
            initiator_list)
        self.assertEqual(0, self.library.partner_zapi_client.
                         has_luns_mapped_to_initiators.call_count)

    @ddt.data(True, False)
    def test_clone_lun_zero_block_count(self, is_snapshot):
        """Test for when clone lun is not passed a block count."""
        self.library._get_lun_attr = mock.Mock(return_value={
            'Volume': 'fakeLUN', 'Path': '/vol/fake/fakeLUN'})
        self.library.zapi_client = mock.Mock()
        self.library.zapi_client.get_lun_by_args.return_value = [fake.FAKE_LUN]
        self.library._add_lun_to_table = mock.Mock()

        self.library._clone_lun('fakeLUN', 'newFakeLUN', 'false',
                                is_snapshot=is_snapshot)

        self.library.zapi_client.clone_lun.assert_called_once_with(
            '/vol/fake/fakeLUN', '/vol/fake/newFakeLUN', 'fakeLUN',
            'newFakeLUN', 'false', block_count=0, dest_block=0,
            source_snapshot=None, src_block=0)

    def test_clone_lun_blocks(self):
        """Test for when clone lun is passed block information."""
        block_count = 10
        src_block = 10
        dest_block = 30
        self.library._get_lun_attr = mock.Mock(return_value={
            'Volume': 'fakeLUN', 'Path': '/vol/fake/fakeLUN'})
        self.library.zapi_client = mock.Mock()
        self.library.zapi_client.get_lun_by_args.return_value = [fake.FAKE_LUN]
        self.library._add_lun_to_table = mock.Mock()

        self.library._clone_lun('fakeLUN', 'newFakeLUN', 'false',
                                block_count=block_count, src_block=src_block,
                                dest_block=dest_block)

        self.library.zapi_client.clone_lun.assert_called_once_with(
            '/vol/fake/fakeLUN', '/vol/fake/newFakeLUN', 'fakeLUN',
            'newFakeLUN', 'false', block_count=block_count,
            dest_block=dest_block, src_block=src_block,
            source_snapshot=None)

    def test_clone_lun_no_space_reservation(self):
        """Test for when space_reservation is not passed."""
        self.library._get_lun_attr = mock.Mock(return_value={
            'Volume': 'fakeLUN', 'Path': '/vol/fake/fakeLUN'})
        self.library.lun_space_reservation = 'false'
        self.library.zapi_client = mock.Mock()
        self.library.zapi_client.get_lun_by_args.return_value = [fake.FAKE_LUN]
        self.library._add_lun_to_table = mock.Mock()

        self.library._clone_lun('fakeLUN', 'newFakeLUN')

        self.library.zapi_client.clone_lun.assert_called_once_with(
            '/vol/fake/fakeLUN', '/vol/fake/newFakeLUN', 'fakeLUN',
            'newFakeLUN', 'false', block_count=0, dest_block=0, src_block=0,
            source_snapshot=None)

    def test_clone_lun_qos_supplied(self):
        """Test for qos supplied in clone lun invocation."""
        self.assertRaises(exception.VolumeDriverException,
                          self.library._clone_lun,
                          'fakeLUN',
                          'newFakeLUN',
                          qos_policy_group_name=fake.QOS_POLICY_GROUP_NAME)

    def test_get_fc_target_wwpns(self):
        ports1 = [fake.FC_FORMATTED_TARGET_WWPNS[0],
                  fake.FC_FORMATTED_TARGET_WWPNS[1]]
        ports2 = [fake.FC_FORMATTED_TARGET_WWPNS[2],
                  fake.FC_FORMATTED_TARGET_WWPNS[3]]
        self.zapi_client.get_fc_target_wwpns.return_value = ports1
        self.library.partner_zapi_client = mock.Mock()
        self.library.partner_zapi_client.get_fc_target_wwpns.return_value = \
            ports2

        result = self.library._get_fc_target_wwpns()

        self.assertSetEqual(set(fake.FC_FORMATTED_TARGET_WWPNS), set(result))

    def test_get_fc_target_wwpns_no_partner(self):
        ports1 = [fake.FC_FORMATTED_TARGET_WWPNS[0],
                  fake.FC_FORMATTED_TARGET_WWPNS[1]]
        ports2 = [fake.FC_FORMATTED_TARGET_WWPNS[2],
                  fake.FC_FORMATTED_TARGET_WWPNS[3]]
        self.zapi_client.get_fc_target_wwpns.return_value = ports1
        self.library.partner_zapi_client = mock.Mock()
        self.library.partner_zapi_client.get_fc_target_wwpns.return_value = \
            ports2

        result = self.library._get_fc_target_wwpns(include_partner=False)

        self.assertSetEqual(set(ports1), set(result))

    def test_create_lun(self):
        self.library.vol_refresh_voluntary = False

        self.library._create_lun(fake.VOLUME_ID, fake.LUN_ID,
                                 fake.LUN_SIZE, fake.LUN_METADATA)

        self.library.zapi_client.create_lun.assert_called_once_with(
            fake.VOLUME_ID, fake.LUN_ID, fake.LUN_SIZE, fake.LUN_METADATA,
            None)
        self.assertTrue(self.library.vol_refresh_voluntary)

    def test_create_lun_with_qos_policy_group(self):
        self.assertRaises(exception.VolumeDriverException,
                          self.library._create_lun, fake.VOLUME_ID,
                          fake.LUN_ID, fake.LUN_SIZE, fake.LUN_METADATA,
                          qos_policy_group_name=fake.QOS_POLICY_GROUP_NAME)

    def test_check_volume_type_for_lun_legacy_qos_not_supported(self):
        mock_get_volume_type = self.mock_object(na_utils,
                                                'get_volume_type_from_volume')

        self.assertRaises(exception.ManageExistingVolumeTypeMismatch,
                          self.library._check_volume_type_for_lun,
                          na_fakes.VOLUME, {}, {}, na_fakes.LEGACY_EXTRA_SPECS)

        self.assertEqual(0, mock_get_volume_type.call_count)

    def test_check_volume_type_for_lun_no_volume_type(self):
        mock_get_volume_type = self.mock_object(na_utils,
                                                'get_volume_type_from_volume')
        mock_get_volume_type.return_value = None
        mock_get_backend_spec = self.mock_object(
            na_utils, 'get_backend_qos_spec_from_volume_type')

        self.library._check_volume_type_for_lun(na_fakes.VOLUME, {}, {}, None)

        self.assertEqual(0, mock_get_backend_spec.call_count)

    def test_check_volume_type_for_lun_qos_spec_not_supported(self):
        mock_get_volume_type = self.mock_object(na_utils,
                                                'get_volume_type_from_volume')
        mock_get_volume_type.return_value = na_fakes.VOLUME_TYPE
        mock_get_backend_spec = self.mock_object(
            na_utils, 'get_backend_qos_spec_from_volume_type')
        mock_get_backend_spec.return_value = na_fakes.QOS_SPEC

        self.assertRaises(exception.ManageExistingVolumeTypeMismatch,
                          self.library._check_volume_type_for_lun,
                          na_fakes.VOLUME, {}, {}, na_fakes.EXTRA_SPECS)

    def test_get_preferred_target_from_list(self):

        result = self.library._get_preferred_target_from_list(
            fake.ISCSI_TARGET_DETAILS_LIST)

        self.assertEqual(fake.ISCSI_TARGET_DETAILS_LIST[0], result)

    def test_mark_qos_policy_group_for_deletion(self):
        result = self.library._mark_qos_policy_group_for_deletion(
            fake.QOS_POLICY_GROUP_INFO)

        self.assertIsNone(result)

    def test_setup_qos_for_volume(self):
        result = self.library._setup_qos_for_volume(fake.VOLUME,
                                                    fake.EXTRA_SPECS)

        self.assertIsNone(result)

    def test_manage_existing_lun_same_name(self):
        mock_lun = block_base.NetAppLun('handle', 'name', '1',
                                        {'Path': '/vol/FAKE_CMODE_VOL1/name'})
        self.library._get_existing_vol_with_manage_ref = mock.Mock(
            return_value=mock_lun)
        self.mock_object(na_utils, 'get_volume_extra_specs')
        self.mock_object(na_utils, 'log_extra_spec_warnings')
        self.library._check_volume_type_for_lun = mock.Mock()
        self.library._add_lun_to_table = mock.Mock()
        self.zapi_client.move_lun = mock.Mock()

        self.library.manage_existing({'name': 'name'}, {'ref': 'ref'})

        self.library._get_existing_vol_with_manage_ref.assert_called_once_with(
            {'ref': 'ref'})
        self.assertEqual(1, self.library._check_volume_type_for_lun.call_count)
        self.assertEqual(1, self.library._add_lun_to_table.call_count)
        self.assertEqual(0, self.zapi_client.move_lun.call_count)

    def test_manage_existing_lun_new_path(self):
        mock_lun = block_base.NetAppLun(
            'handle', 'name', '1', {'Path': '/vol/FAKE_CMODE_VOL1/name'})
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
            '/vol/FAKE_CMODE_VOL1/name', '/vol/FAKE_CMODE_VOL1/volume')

    def test_get_pool_stats_no_volumes(self):

        self.library.vols = []

        result = self.library._get_pool_stats()

        self.assertListEqual([], result)

    @ddt.data({'netapp_lun_space_reservation': 'enabled'},
              {'netapp_lun_space_reservation': 'disabled'})
    @ddt.unpack
    def test_get_pool_stats(self, netapp_lun_space_reservation):

        self.library.volume_list = ['vol0', 'vol1', 'vol2']
        self.library.root_volume_name = 'vol0'
        self.library.reserved_percentage = 5
        self.library.max_over_subscription_ratio = 10.0
        self.library.configuration.netapp_lun_space_reservation = (
            netapp_lun_space_reservation)
        self.library.vols = netapp_api.NaElement(
            client_fakes.VOLUME_LIST_INFO_RESPONSE).get_child_by_name(
            'volumes').get_children()
        self.library.perf_library.get_node_utilization = (
            mock.Mock(return_value=30.0))

        thick = netapp_lun_space_reservation == 'enabled'

        result = self.library._get_pool_stats(filter_function='filter',
                                              goodness_function='goodness')

        expected = [{
            'pool_name': 'vol1',
            'consistencygroup_support': True,
            'QoS_support': False,
            'thin_provisioning_support': not thick,
            'thick_provisioning_support': thick,
            'free_capacity_gb': 1339.27,
            'total_capacity_gb': 1342.21,
            'reserved_percentage': 5,
            'max_over_subscription_ratio': 10.0,
            'multiattach': False,
            'utilization': 30.0,
            'filter_function': 'filter',
            'goodness_function': 'goodness',
        }]

        self.assertEqual(expected, result)

    def test_get_filtered_pools_invalid_conf(self):
        """Verify an exception is raised if the regex pattern is invalid."""
        self.library.configuration.netapp_pool_name_search_pattern = '(.+'

        self.assertRaises(exception.InvalidConfigurationValue,
                          self.library._get_filtered_pools)

    @ddt.data('.*?3$|mix.+', '(.+?[0-9]+) ', '^.+3$', '^[a-z].*?[^4]$')
    def test_get_filtered_pools_match_select_pools(self, patterns):
        self.library.vols = fake.FAKE_7MODE_VOLUME['all']
        self.library.configuration.netapp_pool_name_search_pattern = patterns

        filtered_pools = self.library._get_filtered_pools()

        self.assertEqual(
            fake.FAKE_7MODE_VOLUME['all'][0].get_child_content('name'),
            filtered_pools[0]
        )
        self.assertEqual(
            fake.FAKE_7MODE_VOLUME['all'][1].get_child_content('name'),
            filtered_pools[1]
        )

    @ddt.data('', 'mix.+|open.+', '.+', 'open123, mixed3, open1234', '.+')
    def test_get_filtered_pools_match_all_pools(self, patterns):
        self.library.vols = fake.FAKE_7MODE_VOLUME['all']
        self.library.configuration.netapp_pool_name_search_pattern = patterns

        filtered_pools = self.library._get_filtered_pools()

        self.assertEqual(
            fake.FAKE_7MODE_VOLUME['all'][0].get_child_content('name'),
            filtered_pools[0]
        )
        self.assertEqual(
            fake.FAKE_7MODE_VOLUME['all'][1].get_child_content('name'),
            filtered_pools[1]
        )
        self.assertEqual(
            fake.FAKE_7MODE_VOLUME['all'][2].get_child_content('name'),
            filtered_pools[2]
        )

    @ddt.data('abc|stackopen|openstack|abc.*', 'abc',
              'stackopen, openstack, open', '^$')
    def test_get_filtered_pools_non_matching_patterns(self, patterns):

        self.library.vols = fake.FAKE_7MODE_VOLUME['all']
        self.library.configuration.netapp_pool_name_search_pattern = patterns

        filtered_pools = self.library._get_filtered_pools()

        self.assertListEqual([], filtered_pools)

    def test_get_pool_stats_no_ssc_vols(self):

        self.library.vols = {}

        pools = self.library._get_pool_stats()

        self.assertListEqual([], pools)

    def test_get_pool_stats_with_filtered_pools(self):

        self.library.vols = fake.FAKE_7MODE_VOL1
        self.library.volume_list = [
            fake.FAKE_7MODE_VOL1[0].get_child_content('name')
        ]
        self.library.root_volume_name = ''
        self.library.perf_library.get_node_utilization = (
            mock.Mock(return_value=30.0))

        pools = self.library._get_pool_stats(filter_function='filter',
                                             goodness_function='goodness')

        self.assertListEqual(fake.FAKE_7MODE_POOLS, pools)

    def test_get_pool_stats_no_filtered_pools(self):

        self.library.vols = fake.FAKE_7MODE_VOL1
        self.library.volume_list = ['open1', 'open2']
        self.library.root_volume_name = ''

        pools = self.library._get_pool_stats()

        self.assertListEqual([], pools)

    @ddt.data((None, False, False),
              (30, True, False),
              (30, False, True))
    @ddt.unpack
    def test__refresh_volume_info_already_running(self,
                                                  vol_refresh_time,
                                                  vol_refresh_voluntary,
                                                  is_newer):
        mock_warning_log = self.mock_object(block_7mode.LOG, 'warning')
        self.library.vol_refresh_time = vol_refresh_time
        self.library.vol_refresh_voluntary = vol_refresh_voluntary
        self.library.vol_refresh_interval = 30
        self.mock_object(timeutils, 'is_newer_than', return_value=is_newer)
        self.mock_object(na_utils, 'set_safe_attr', return_value=False)

        retval = self.library._refresh_volume_info()

        self.assertIsNone(retval)
        # Assert no values are unset by the method
        self.assertEqual(vol_refresh_voluntary,
                         self.library.vol_refresh_voluntary)
        self.assertEqual(vol_refresh_time, self.library.vol_refresh_time)
        if timeutils.is_newer_than.called:
            timeutils.is_newer_than.assert_called_once_with(
                vol_refresh_time, self.library.vol_refresh_interval)
        na_utils.set_safe_attr.assert_has_calls([
            mock.call(self.library, 'vol_refresh_running', True),
            mock.call(self.library, 'vol_refresh_running', False)])
        self.assertEqual(1, mock_warning_log.call_count)

    def test__refresh_volume_info(self):
        mock_warning_log = self.mock_object(block_7mode.LOG, 'warning')
        self.library.vol_refresh_time = None
        self.library.vol_refresh_voluntary = True
        self.mock_object(timeutils, 'is_newer_than')
        self.mock_object(self.library.zapi_client, 'get_filer_volumes')
        self.mock_object(self.library, '_get_filtered_pools',
                         return_value=['vol1', 'vol2'])
        self.mock_object(na_utils, 'set_safe_attr', return_value=True)

        retval = self.library._refresh_volume_info()

        self.assertIsNone(retval)
        self.assertEqual(False, self.library.vol_refresh_voluntary)
        self.assertEqual(['vol1', 'vol2'], self.library.volume_list)
        self.assertIsNotNone(self.library.vol_refresh_time)
        na_utils.set_safe_attr.assert_has_calls([
            mock.call(self.library, 'vol_refresh_running', True),
            mock.call(self.library, 'vol_refresh_running', False)])
        self.assertFalse(mock_warning_log.called)

    def test__refresh_volume_info_exception(self):
        mock_warning_log = self.mock_object(block_7mode.LOG, 'warning')
        self.library.vol_refresh_time = None
        self.library.vol_refresh_voluntary = True
        self.mock_object(timeutils, 'is_newer_than')
        self.mock_object(na_utils, 'set_safe_attr', return_value=True)
        self.mock_object(self.library.zapi_client,
                         'get_filer_volumes',
                         side_effect=exception.NetAppDriverException)
        self.mock_object(self.library, '_get_filtered_pools')

        retval = self.library._refresh_volume_info()

        self.assertIsNone(retval)
        self.assertFalse(self.library._get_filtered_pools.called)
        self.assertEqual(1, mock_warning_log.call_count)

    def test_delete_volume(self):
        self.library.vol_refresh_voluntary = False
        mock_super_delete_volume = self.mock_object(
            block_base.NetAppBlockStorageLibrary, 'delete_volume')

        self.library.delete_volume(fake.VOLUME)

        mock_super_delete_volume.assert_called_once_with(fake.VOLUME)
        self.assertTrue(self.library.vol_refresh_voluntary)

    def test_delete_snapshot(self):
        self.library.vol_refresh_voluntary = False
        mock_super_delete_snapshot = self.mock_object(
            block_base.NetAppBlockStorageLibrary, 'delete_snapshot')

        self.library.delete_snapshot(fake.SNAPSHOT)

        mock_super_delete_snapshot.assert_called_once_with(fake.SNAPSHOT)
        self.assertTrue(self.library.vol_refresh_voluntary)

    def test_add_looping_tasks(self):
        mock_super_add_looping_tasks = self.mock_object(
            block_base.NetAppBlockStorageLibrary, '_add_looping_tasks')

        self.library._add_looping_tasks()

        mock_super_add_looping_tasks.assert_called_once_with()

    def test_get_backing_flexvol_names(self):
        self.library.volume_list = ['vol0', 'vol1', 'vol2']

        result = self.library._get_backing_flexvol_names()

        self.assertEqual('vol2', result[2])

    def test_create_cgsnapshot(self):
        snapshot = fake.CG_SNAPSHOT
        snapshot['volume'] = fake.CG_VOLUME

        mock_extract_host = self.mock_object(
            volume_utils, 'extract_host', return_value=fake.POOL_NAME)

        mock_clone_lun = self.mock_object(self.library, '_clone_lun')
        mock_busy = self.mock_object(
            self.zapi_client, 'wait_for_busy_snapshot')
        mock_delete_snapshot = self.mock_object(
            self.zapi_client, 'delete_snapshot')

        self.library.create_cgsnapshot(fake.CG_SNAPSHOT, [snapshot])

        mock_extract_host.assert_called_once_with(fake.CG_VOLUME['host'],
                                                  level='pool')
        self.zapi_client.create_cg_snapshot.assert_called_once_with(
            set([fake.POOL_NAME]), fake.CG_SNAPSHOT_ID)
        mock_clone_lun.assert_called_once_with(
            fake.CG_VOLUME_NAME, fake.CG_SNAPSHOT_NAME,
            source_snapshot=fake.CG_SNAPSHOT_ID)
        mock_busy.assert_called_once_with(fake.POOL_NAME, fake.CG_SNAPSHOT_ID)
        mock_delete_snapshot.assert_called_once_with(
            fake.POOL_NAME, fake.CG_SNAPSHOT_ID)

    def test_create_cgsnapshot_busy_snapshot(self):
        snapshot = fake.CG_SNAPSHOT
        snapshot['volume'] = fake.CG_VOLUME

        mock_extract_host = self.mock_object(
            volume_utils, 'extract_host',
            return_value=fake.POOL_NAME)
        mock_clone_lun = self.mock_object(self.library, '_clone_lun')
        mock_busy = self.mock_object(
            self.zapi_client, 'wait_for_busy_snapshot')
        mock_busy.side_effect = exception.SnapshotIsBusy(snapshot['name'])
        mock_delete_snapshot = self.mock_object(
            self.zapi_client, 'delete_snapshot')
        mock_mark_snapshot_for_deletion = self.mock_object(
            self.zapi_client, 'mark_snapshot_for_deletion')

        self.library.create_cgsnapshot(fake.CG_SNAPSHOT, [snapshot])

        mock_extract_host.assert_called_once_with(
            fake.CG_VOLUME['host'], level='pool')
        self.zapi_client.create_cg_snapshot.assert_called_once_with(
            set([fake.POOL_NAME]), fake.CG_SNAPSHOT_ID)
        mock_clone_lun.assert_called_once_with(
            fake.CG_VOLUME_NAME, fake.CG_SNAPSHOT_NAME,
            source_snapshot=fake.CG_SNAPSHOT_ID)
        mock_delete_snapshot.assert_not_called()
        mock_mark_snapshot_for_deletion.assert_called_once_with(
            fake.POOL_NAME, fake.CG_SNAPSHOT_ID)

    def test_delete_cgsnapshot(self):

        mock_delete_snapshot = self.mock_object(
            self.library, '_delete_lun')

        self.library.delete_cgsnapshot(fake.CG_SNAPSHOT, [fake.CG_SNAPSHOT])

        mock_delete_snapshot.assert_called_once_with(fake.CG_SNAPSHOT['name'])

    def test_delete_cgsnapshot_not_found(self):
        self.mock_object(block_base, 'LOG')
        self.mock_object(self.library, '_get_lun_attr', return_value=None)

        self.library.delete_cgsnapshot(fake.CG_SNAPSHOT, [fake.CG_SNAPSHOT])

        self.assertEqual(0, block_base.LOG.error.call_count)
        self.assertEqual(1, block_base.LOG.warning.call_count)
        self.assertEqual(0, block_base.LOG.info.call_count)

    def test_create_volume_with_cg(self):
        volume_size_in_bytes = int(fake.CG_VOLUME_SIZE) * units.Gi
        self._create_volume_test_helper()

        self.library.create_volume(fake.CG_VOLUME)

        self.library._create_lun.assert_called_once_with(
            fake.POOL_NAME, fake.CG_VOLUME_NAME, volume_size_in_bytes,
            fake.CG_LUN_METADATA, None)
        self.library._get_volume_model_update.assert_called_once_with(
            fake.CG_VOLUME)
        self.assertEqual(0, self.library.
                         _mark_qos_policy_group_for_deletion.call_count)
        self.assertEqual(0, block_base.LOG.error.call_count)

    def _create_volume_test_helper(self):
        self.mock_object(na_utils, 'get_volume_extra_specs')
        self.mock_object(na_utils, 'log_extra_spec_warnings')
        self.mock_object(block_base, 'LOG')
        self.mock_object(volume_utils, 'extract_host',
                         return_value=fake.POOL_NAME)
        self.mock_object(self.library, '_setup_qos_for_volume',
                         return_value=None)
        self.mock_object(self.library, '_create_lun')
        self.mock_object(self.library, '_create_lun_handle')
        self.mock_object(self.library, '_add_lun_to_table')
        self.mock_object(self.library, '_mark_qos_policy_group_for_deletion')
        self.mock_object(self.library, '_get_volume_model_update')

    def test_create_consistency_group(self):
        model_update = self.library.create_consistencygroup(
            fake.CONSISTENCY_GROUP)
        self.assertEqual('available', model_update['status'])

    def test_delete_consistencygroup_volume_delete_failure(self):
        self.mock_object(block_7mode, 'LOG')
        self.mock_object(self.library, '_delete_lun', side_effect=Exception)

        model_update, volumes = self.library.delete_consistencygroup(
            fake.CONSISTENCY_GROUP, [fake.CG_VOLUME])

        self.assertEqual('deleted', model_update['status'])
        self.assertEqual('error_deleting', volumes[0]['status'])
        self.assertEqual(1, block_7mode.LOG.exception.call_count)

    def test_delete_consistencygroup_not_found(self):
        self.mock_object(block_7mode, 'LOG')
        self.mock_object(self.library, '_get_lun_attr', return_value=None)

        model_update, volumes = self.library.delete_consistencygroup(
            fake.CONSISTENCY_GROUP, [fake.CG_VOLUME])

        self.assertEqual(0, block_7mode.LOG.error.call_count)
        self.assertEqual(0, block_7mode.LOG.info.call_count)

        self.assertEqual('deleted', model_update['status'])
        self.assertEqual('deleted', volumes[0]['status'])

    @ddt.data(None,
              {'replication_status': fields.ReplicationStatus.ENABLED})
    def test_create_consistencygroup_from_src_cg_snapshot(self,
                                                          volume_model_update):
        mock_clone_source_to_destination = self.mock_object(
            self.library, '_clone_source_to_destination',
            return_value=volume_model_update)

        actual_return_value = self.library.create_consistencygroup_from_src(
            fake.CONSISTENCY_GROUP, [fake.VOLUME], cgsnapshot=fake.CG_SNAPSHOT,
            snapshots=[fake.CG_VOLUME_SNAPSHOT])

        clone_source_to_destination_args = {
            'name': fake.CG_SNAPSHOT['name'],
            'size': fake.CG_SNAPSHOT['volume_size'],
        }
        mock_clone_source_to_destination.assert_called_once_with(
            clone_source_to_destination_args, fake.VOLUME)
        if volume_model_update:
            volume_model_update['id'] = fake.VOLUME['id']
        expected_return_value = ((None, [volume_model_update])
                                 if volume_model_update else (None, []))
        self.assertEqual(expected_return_value, actual_return_value)

    @ddt.data(None,
              {'replication_status': fields.ReplicationStatus.ENABLED})
    def test_create_consistencygroup_from_src_cg(self, volume_model_update):
        lun_name = fake.SOURCE_CG_VOLUME['name']
        mock_lun = block_base.NetAppLun(
            lun_name, lun_name, '3', {'UUID': 'fake_uuid'})
        self.mock_object(self.library, '_get_lun_from_table',
                         return_value=mock_lun)
        mock_clone_source_to_destination = self.mock_object(
            self.library, '_clone_source_to_destination',
            return_value=volume_model_update)

        actual_return_value = self.library.create_consistencygroup_from_src(
            fake.CONSISTENCY_GROUP, [fake.VOLUME],
            source_cg=fake.SOURCE_CONSISTENCY_GROUP,
            source_vols=[fake.SOURCE_CG_VOLUME])

        clone_source_to_destination_args = {
            'name': fake.SOURCE_CG_VOLUME['name'],
            'size': fake.SOURCE_CG_VOLUME['size'],
        }
        if volume_model_update:
            volume_model_update['id'] = fake.VOLUME['id']
        expected_return_value = ((None, [volume_model_update])
                                 if volume_model_update else (None, []))
        mock_clone_source_to_destination.assert_called_once_with(
            clone_source_to_destination_args, fake.VOLUME)
        self.assertEqual(expected_return_value, actual_return_value)
