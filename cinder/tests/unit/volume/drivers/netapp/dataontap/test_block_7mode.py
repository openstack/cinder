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
Mock unit tests for the NetApp block storage 7-mode library
"""


from lxml import etree
import mock

from cinder import exception
from cinder import test
import cinder.tests.unit.volume.drivers.netapp.dataontap.fakes as fake
import cinder.tests.unit.volume.drivers.netapp.fakes as na_fakes
from cinder.volume.drivers.netapp.dataontap import block_7mode
from cinder.volume.drivers.netapp.dataontap import block_base
from cinder.volume.drivers.netapp.dataontap.client import api as netapp_api
from cinder.volume.drivers.netapp.dataontap.client import client_base
from cinder.volume.drivers.netapp import utils as na_utils


class NetAppBlockStorage7modeLibraryTestCase(test.TestCase):
    """Test case for NetApp's 7-Mode iSCSI library."""

    def setUp(self):
        super(NetAppBlockStorage7modeLibraryTestCase, self).setUp()

        kwargs = {'configuration': self.get_config_7mode()}
        self.library = block_7mode.NetAppBlockStorage7modeLibrary(
            'driver', 'protocol', **kwargs)

        self.library.zapi_client = mock.Mock()
        self.zapi_client = self.library.zapi_client
        self.library.vfiler = mock.Mock()

    def tearDown(self):
        super(NetAppBlockStorage7modeLibraryTestCase, self).tearDown()

    def get_config_7mode(self):
        config = na_fakes.create_configuration_7mode()
        config.netapp_storage_protocol = 'iscsi'
        config.netapp_login = 'admin'
        config.netapp_password = 'pass'
        config.netapp_server_hostname = '127.0.0.1'
        config.netapp_transport_type = 'http'
        config.netapp_server_port = '80'
        return config

    @mock.patch.object(client_base.Client, 'get_ontapi_version',
                       mock.MagicMock(return_value=(1, 20)))
    @mock.patch.object(block_7mode.NetAppBlockStorage7modeLibrary,
                       '_get_root_volume_name')
    @mock.patch.object(block_7mode.NetAppBlockStorage7modeLibrary,
                       '_do_partner_setup')
    @mock.patch.object(block_base.NetAppBlockStorageLibrary, 'do_setup')
    def test_do_setup(self, super_do_setup, mock_do_partner_setup,
                      mock_get_root_volume_name):
        mock_get_root_volume_name.return_value = 'vol0'
        context = mock.Mock()

        self.library.do_setup(context)

        super_do_setup.assert_called_once_with(context)
        mock_do_partner_setup.assert_called_once_with()
        mock_get_root_volume_name.assert_called_once_with()

    @mock.patch.object(client_base.Client, 'get_ontapi_version',
                       mock.MagicMock(return_value=(1, 20)))
    def test_do_partner_setup(self):
        self.library.configuration.netapp_partner_backend_name = 'partner'

        self.library._do_partner_setup()

        self.assertIsNotNone(self.library.partner_zapi_client)

    @mock.patch.object(client_base.Client, 'get_ontapi_version',
                       mock.MagicMock(return_value=(1, 20)))
    def test_do_partner_setup_no_partner(self):

        self.library._do_partner_setup()

        self.assertFalse(hasattr(self.library, 'partner_zapi_client'))

    @mock.patch.object(
        block_base.NetAppBlockStorageLibrary, 'check_for_setup_error')
    def test_check_for_setup_error(self, super_check_for_setup_error):
        self.zapi_client.get_ontapi_version.return_value = (1, 9)

        self.library.check_for_setup_error()

        super_check_for_setup_error.assert_called_once_with()

    def test_check_for_setup_error_too_old(self):
        self.zapi_client.get_ontapi_version.return_value = (1, 8)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.library.check_for_setup_error)

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

    def test_clone_lun_zero_block_count(self):
        """Test for when clone lun is not passed a block count."""
        self.library._get_lun_attr = mock.Mock(return_value={
            'Volume': 'fakeLUN', 'Path': '/vol/fake/fakeLUN'})
        self.library.zapi_client = mock.Mock()
        self.library.zapi_client.get_lun_by_args.return_value = [fake.FAKE_LUN]
        self.library._add_lun_to_table = mock.Mock()

        self.library._clone_lun('fakeLUN', 'newFakeLUN', 'false')

        self.library.zapi_client.clone_lun.assert_called_once_with(
            '/vol/fake/fakeLUN', '/vol/fake/newFakeLUN', 'fakeLUN',
            'newFakeLUN', 'false', block_count=0, dest_block=0, src_block=0)

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
            'newFakeLUN', 'false', block_count=0, dest_block=0, src_block=0)

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

    @mock.patch.object(block_7mode.NetAppBlockStorage7modeLibrary,
                       '_refresh_volume_info', mock.Mock())
    @mock.patch.object(block_7mode.NetAppBlockStorage7modeLibrary,
                       '_get_pool_stats', mock.Mock())
    def test_vol_stats_calls_provide_ems(self):
        self.library.zapi_client.provide_ems = mock.Mock()

        self.library.get_volume_stats(refresh=True)

        self.assertEqual(1, self.library.zapi_client.provide_ems.call_count)

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

        self.assertEqual(None, result)

    def test_setup_qos_for_volume(self):
        result = self.library._setup_qos_for_volume(fake.VOLUME,
                                                    fake.EXTRA_SPECS)

        self.assertEqual(None, result)

    def test_manage_existing_lun_same_name(self):
        mock_lun = block_base.NetAppLun('handle', 'name', '1',
                                        {'Path': '/vol/vol1/name'})
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
