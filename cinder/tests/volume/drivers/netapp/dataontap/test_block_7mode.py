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
Mock unit tests for the NetApp block storage 7-mode library
"""


from lxml import etree
import mock

from cinder import exception
from cinder import test
import cinder.tests.volume.drivers.netapp.dataontap.fakes as fake
import cinder.tests.volume.drivers.netapp.fakes as na_fakes
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

        self.assertEqual(igroup, fake.IGROUP1_NAME)
        self.assertEqual(lun_id, '2')

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
        self.library._get_lun_attr = mock.Mock(return_value={
            'Volume': 'fakeLUN', 'Path': '/vol/fake/fakeLUN'})
        self.library.zapi_client = mock.Mock()
        self.library.zapi_client.get_lun_by_args.return_value = [lun]
        self.library._add_lun_to_table = mock.Mock()

        self.library._clone_lun('fakeLUN', 'newFakeLUN')

        self.library.zapi_client.clone_lun.assert_called_once_with(
            '/vol/fake/fakeLUN', '/vol/fake/newFakeLUN', 'fakeLUN',
            'newFakeLUN', 'true', block_count=0, dest_block=0, src_block=0)

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

        self.assertEqual(self.library.zapi_client.provide_ems.call_count, 1)

    def test_create_lun(self):
        self.library.vol_refresh_voluntary = False

        self.library._create_lun(fake.VOLUME, fake.LUN,
                                 fake.SIZE, fake.METADATA)

        self.library.zapi_client.create_lun.assert_called_once_with(
            fake.VOLUME, fake.LUN, fake.SIZE, fake.METADATA, None)
        self.assertTrue(self.library.vol_refresh_voluntary)

    @mock.patch.object(na_utils, 'get_volume_extra_specs')
    def test_check_volume_type_for_lun_qos_not_supported(self, get_specs):
        get_specs.return_value = {'specs': 's',
                                  'netapp:qos_policy_group': 'qos'}
        mock_lun = block_base.NetAppLun('handle', 'name', '1',
                                        {'Volume': 'name', 'Path': '/vol/lun'})
        self.assertRaises(exception.ManageExistingVolumeTypeMismatch,
                          self.library._check_volume_type_for_lun,
                          {'vol': 'vol'}, mock_lun, {'ref': 'ref'})
        get_specs.assert_called_once_with({'vol': 'vol'})

    def test_get_preferred_target_from_list(self):

        result = self.library._get_preferred_target_from_list(
            fake.ISCSI_TARGET_DETAILS_LIST)

        self.assertEqual(fake.ISCSI_TARGET_DETAILS_LIST[0], result)
