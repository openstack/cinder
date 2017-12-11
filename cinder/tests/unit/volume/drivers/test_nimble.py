# Nimble Storage, Inc. (c) 2013-2014
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


import mock
from six.moves import http_client
import sys

from cinder import context
from cinder import exception
from cinder.objects import volume as obj_volume
from cinder import test
from cinder.tests.unit import fake_constants as fake
from cinder.volume.drivers import nimble
from cinder.volume import volume_types

NIMBLE_CLIENT = 'cinder.volume.drivers.nimble.NimbleRestAPIExecutor'
NIMBLE_URLLIB2 = 'cinder.volume.drivers.nimble.requests'
NIMBLE_RANDOM = 'cinder.volume.drivers.nimble.random'
NIMBLE_ISCSI_DRIVER = 'cinder.volume.drivers.nimble.NimbleISCSIDriver'
NIMBLE_FC_DRIVER = 'cinder.volume.drivers.nimble.NimbleFCDriver'
DRIVER_VERSION = '4.0.1'
nimble.DEFAULT_SLEEP = 0

FAKE_POSITIVE_LOGIN_RESPONSE_1 = '2c20aad78a220ed1dae21dcd6f9446f5'

FAKE_POSITIVE_LOGIN_RESPONSE_2 = '2c20aad78a220ed1dae21dcd6f9446ff'

FAKE_POSITIVE_HEADERS = {'X-Auth-Token': FAKE_POSITIVE_LOGIN_RESPONSE_1}

FAKE_POSITIVE_NETCONFIG_RESPONSE = {
    'role': 'active',
    'subnet_list': [{'network': '172.18.212.0',
                     'discovery_ip': '172.18.108.21',
                     'type': 'data',
                     'allow_iscsi': True,
                     'label': 'data1',
                     'allow_group': True,
                     'vlan_id': 0}],
    'array_list': [{'nic_list': [{'subnet_label': 'data1',
                                  'tagged': False,
                                  'data_ip': '172.18.212.82',
                                  'name': 'eth3'}]}],
    'name': 'test-array'}

FAKE_NEGATIVE_NETCONFIG_RESPONSE = exception.VolumeDriverException(
    "Session expired")

FAKE_CREATE_VOLUME_POSITIVE_RESPONSE = {
    'clone': False,
    'name': "testvolume"}

FAKE_CREATE_VOLUME_POSITIVE_RESPONSE_ENCRYPTION = {
    'clone': False,
    'name': "testvolume-encryption"}

FAKE_CREATE_VOLUME_POSITIVE_RESPONSE_PERF_POLICY = {
    'clone': False,
    'name': "testvolume-perf-policy"}

FAKE_CREATE_VOLUME_POSITIVE_RESPONSE_MULTI_INITIATOR = {
    'clone': False,
    'name': "testvolume-multi-initiator"}

FAKE_CREATE_VOLUME_POSITIVE_RESPONSE_DEDUPE = {
    'clone': False,
    'name': "testvolume-dedupe"}

FAKE_CREATE_VOLUME_POSITIVE_RESPONSE_QOS = {
    'clone': False,
    'name': "testvolume-qos"}

FAKE_GET_VOL_INFO_RESPONSE = {'name': 'testvolume',
                              'clone': False,
                              'target_name': 'iqn.test',
                              'online': True,
                              'agent_type': 'openstack'}

FAKE_GET_VOL_INFO_RESPONSE_MANAGE = {'name': 'testvolume',
                                     'agent_type': 'none',
                                     'online': False,
                                     'target_name': 'iqn.test'}

FAKE_GET_VOL_INFO_ONLINE = {'name': 'testvolume',
                            'size': 2048,
                            'online': True,
                            'agent_type': 'none'}

FAKE_GET_VOL_INFO_BACKUP_RESPONSE = {'name': 'testvolume',
                                     'clone': True,
                                     'target_name': 'iqn.test',
                                     'online': False,
                                     'agent_type': 'openstack',
                                     'parent_vol_id': 'volume-' +
                                                      fake.VOLUME2_ID,
                                     'base_snap_id': 'test-backup-snap'}

FAKE_GET_SNAP_INFO_BACKUP_RESPONSE = {
    'description': "backup-vol-" + fake.VOLUME2_ID,
    'name': 'test-backup-snap',
    'id': fake.SNAPSHOT_ID,
    'vol_id': fake.VOLUME_ID,
    'volume_name': 'volume-' + fake.VOLUME_ID}

FAKE_POSITIVE_GROUP_CONFIG_RESPONSE = {
    'name': 'group-test',
    'version_current': '0.0.0.0',
    'access_protocol_list': ['iscsi']}

FAKE_LOGIN_POST_RESPONSE = {
    'data': {'session_token': FAKE_POSITIVE_LOGIN_RESPONSE_1}}

FAKE_EXTEND_VOLUME_PARAMS = {'data': {'size': 5120,
                                      'reserve': 0,
                                      'warn_level': 80,
                                      'limit': 100,
                                      'snap_limit': sys.maxsize}}

FAKE_IGROUP_LIST_RESPONSE = [
    {'iscsi_initiators': [{'iqn': 'test-initiator1'}],
     'name': 'test-igrp1'},
    {'iscsi_initiators': [{'iqn': 'test-initiator2'}],
     'name': 'test-igrp2'}]

FAKE_IGROUP_LIST_RESPONSE_FC = [
    {'fc_initiators': [{'wwpn': '10:00:00:00:00:00:00:00'}],
     'name': 'test-igrp1'},
    {'fc_initiators': [{'wwpn': '10:00:00:00:00:00:00:00'},
                       {'wwpn': '10:00:00:00:00:00:00:01'}],
     'name': 'test-igrp2'}]


FAKE_CREATE_VOLUME_NEGATIVE_RESPONSE = exception.VolumeBackendAPIException(
    "Volume testvolume not found")

FAKE_VOLUME_INFO_NEGATIVE_RESPONSE = exception.VolumeBackendAPIException(
    "Volume testvolume not found")

FAKE_CREATE_VOLUME_NEGATIVE_ENCRYPTION = exception.VolumeBackendAPIException(
    "Volume testvolume-encryption not found")

FAKE_CREATE_VOLUME_NEGATIVE_PERFPOLICY = exception.VolumeBackendAPIException(
    "Volume testvolume-perfpolicy not found")

FAKE_CREATE_VOLUME_NEGATIVE_DEDUPE = exception.VolumeBackendAPIException(
    "The specified pool is not capable of hosting deduplicated volumes")

FAKE_CREATE_VOLUME_NEGATIVE_QOS = exception.VolumeBackendAPIException(
    "Please set valid IOPS limitin the range [256, 4294967294]")

FAKE_POSITIVE_GROUP_INFO_RESPONSE = {
    'version_current': '3.0.0.0',
    'group_target_enabled': False,
    'name': 'group-nimble',
    'usage_valid': True,
    'usable_capacity_bytes': 8016883089408,
    'compressed_vol_usage_bytes': 2938311843,
    'compressed_snap_usage_bytes': 36189,
    'unused_reserve_bytes': 0}

FAKE_GENERIC_POSITIVE_RESPONSE = ""

FAKE_TYPE_ID = fake.VOLUME_TYPE_ID
FAKE_POOL_ID = fake.GROUP_ID
FAKE_PERFORMANCE_POLICY_ID = fake.OBJECT_ID
NIMBLE_MANAGEMENT_IP = "10.18.108.55"
NIMBLE_SAN_LOGIN = "nimble"
NIMBLE_SAN_PASS = "nimble_pass"


def create_configuration(username, password, ip_address,
                         pool_name=None, subnet_label=None,
                         thin_provision=True):
    configuration = mock.Mock()
    configuration.san_login = username
    configuration.san_password = password
    configuration.san_ip = ip_address
    configuration.san_thin_provision = thin_provision
    configuration.nimble_pool_name = pool_name
    configuration.nimble_subnet_label = subnet_label
    configuration.safe_get.return_value = 'NIMBLE'
    return configuration


class NimbleDriverBaseTestCase(test.TestCase):

    """Base Class for the NimbleDriver Tests."""

    def setUp(self):
        super(NimbleDriverBaseTestCase, self).setUp()
        self.mock_client_service = None
        self.mock_client_class = None
        self.driver = None

    @staticmethod
    def client_mock_decorator(configuration):
        def client_mock_wrapper(func):
            def inner_client_mock(
                    self, mock_client_class, mock_urllib2, *args, **kwargs):
                self.mock_client_class = mock_client_class
                self.mock_client_service = mock.MagicMock(name='Client')
                self.mock_client_class.return_value = self.mock_client_service
                self.driver = nimble.NimbleISCSIDriver(
                    configuration=configuration)
                mock_login_response = mock_urllib2.post.return_value
                mock_login_response = mock.MagicMock()
                mock_login_response.status_code.return_value = http_client.OK
                mock_login_response.json.return_value = (
                    FAKE_LOGIN_POST_RESPONSE)
                self.driver.do_setup(context.get_admin_context())
                self.driver.APIExecutor.login()
                func(self, *args, **kwargs)
            return inner_client_mock
        return client_mock_wrapper

    @staticmethod
    def client_mock_decorator_fc(configuration):
        def client_mock_wrapper(func):
            def inner_clent_mock(
                    self, mock_client_class, mock_urllib2, *args, **kwargs):
                self.mock_client_class = mock_client_class
                self.mock_client_service = mock.MagicMock(name='Client')
                self.mock_client_class.return_value = (
                    self.mock_client_service)
                self.driver = nimble.NimbleFCDriver(
                    configuration=configuration)
                mock_login_response = mock_urllib2.post.return_value
                mock_login_response = mock.MagicMock()
                mock_login_response.status_code.return_value = http_client.OK
                mock_login_response.json.return_value = (
                    FAKE_LOGIN_POST_RESPONSE)
                self.driver.do_setup(context.get_admin_context())
                self.driver.APIExecutor.login()
                func(self, *args, **kwargs)
            return inner_clent_mock
        return client_mock_wrapper

    def tearDown(self):
        super(NimbleDriverBaseTestCase, self).tearDown()


class NimbleDriverLoginTestCase(NimbleDriverBaseTestCase):

    """Tests do_setup api."""

    @mock.patch(NIMBLE_URLLIB2)
    @mock.patch(NIMBLE_CLIENT)
    @mock.patch.object(obj_volume.VolumeList, 'get_all_by_host',
                       mock.Mock(return_value=[]))
    @NimbleDriverBaseTestCase.client_mock_decorator(create_configuration(
        "nimble", "nimble_pass", "10.18.108.55", 'default', '*'))
    def test_do_setup_positive(self):
        expected_call_list = [mock.call.login()]
        self.mock_client_service.assert_has_calls(expected_call_list)

    @mock.patch(NIMBLE_URLLIB2)
    @mock.patch(NIMBLE_CLIENT)
    @mock.patch.object(obj_volume.VolumeList, 'get_all_by_host',
                       mock.Mock(return_value=[]))
    @NimbleDriverBaseTestCase.client_mock_decorator(create_configuration(
        'nimble', 'nimble_pass', '10.18.108.55', 'default', '*'))
    def test_expire_session_id(self):
        expected_call_list = [mock.call.login()]
        self.mock_client_service.assert_has_calls(expected_call_list)

        self.driver.APIExecutor.get("groups")
        expected_call_list = [mock.call.get_group_info(),
                              mock.call.login(),
                              mock.call.get("groups")]

        self.assertEqual(
            self.mock_client_service.method_calls,
            expected_call_list)


class NimbleDriverVolumeTestCase(NimbleDriverBaseTestCase):

    """Tests volume related api's."""

    @mock.patch(NIMBLE_URLLIB2)
    @mock.patch(NIMBLE_CLIENT)
    @mock.patch.object(obj_volume.VolumeList, 'get_all_by_host',
                       mock.Mock(return_value=[]))
    @mock.patch.object(volume_types, 'get_volume_type_extra_specs',
                       mock.Mock(type_id=FAKE_TYPE_ID, return_value={
                                 'nimble:perfpol-name': 'default',
                                 'nimble:encryption': 'yes'}))
    @NimbleDriverBaseTestCase.client_mock_decorator(create_configuration(
        NIMBLE_SAN_LOGIN, NIMBLE_SAN_PASS, NIMBLE_MANAGEMENT_IP,
        'default', '*'))
    def test_create_volume_positive(self):
        self.mock_client_service.get_vol_info.return_value = (
            FAKE_GET_VOL_INFO_RESPONSE)
        self.mock_client_service.get_netconfig.return_value = (
            FAKE_POSITIVE_NETCONFIG_RESPONSE)

        self.assertEqual({
            'provider_location': '172.18.108.21:3260 iqn.test',
            'provider_auth': None},
            self.driver.create_volume({'name': 'testvolume',
                                       'size': 1,
                                       'volume_type_id': None,
                                       'display_name': '',
                                       'display_description': ''}))

        self.mock_client_service.create_vol.assert_called_once_with(
            {'name': 'testvolume',
             'size': 1,
             'volume_type_id': None,
             'display_name': '',
             'display_description': ''},
            'default',
            False,
            'iSCSI',
            False)

    @mock.patch(NIMBLE_URLLIB2)
    @mock.patch(NIMBLE_CLIENT)
    @mock.patch.object(obj_volume.VolumeList, 'get_all_by_host',
                       mock.Mock(return_value=[]))
    @mock.patch.object(volume_types, 'get_volume_type_extra_specs',
                       mock.Mock(type_id=FAKE_TYPE_ID, return_value={
                                 'nimble:perfpol-name': 'default',
                                 'nimble:encryption': 'yes'}))
    @NimbleDriverBaseTestCase.client_mock_decorator(create_configuration(
        NIMBLE_SAN_LOGIN, NIMBLE_SAN_PASS, NIMBLE_MANAGEMENT_IP,
        'default', '*'))
    def test_create_volume_with_unicode(self):
        self.mock_client_service.get_vol_info.return_value = (
            FAKE_GET_VOL_INFO_RESPONSE)
        self.mock_client_service.get_netconfig.return_value = (
            FAKE_POSITIVE_NETCONFIG_RESPONSE)

        self.assertEqual({
            'provider_location': '172.18.108.21:3260 iqn.test',
            'provider_auth': None},
            self.driver.create_volume({'name': 'testvolume',
                                       'size': 1,
                                       'volume_type_id': None,
                                       'display_name': u'unicode_name',
                                       'display_description': ''}))

        self.mock_client_service.create_vol.assert_called_once_with(
            {'name': 'testvolume',
             'size': 1,
             'volume_type_id': None,
             'display_name': u'unicode_name',
             'display_description': ''},
            'default',
            False,
            'iSCSI',
            False)

    @mock.patch(NIMBLE_URLLIB2)
    @mock.patch(NIMBLE_CLIENT)
    @mock.patch.object(obj_volume.VolumeList, 'get_all_by_host',
                       mock.Mock(return_value=[]))
    @mock.patch.object(volume_types, 'get_volume_type_extra_specs',
                       mock.Mock(type_id=FAKE_TYPE_ID, return_value={
                           'nimble:perfpol-name': 'default',
                           'nimble:encryption': 'yes',
                           'nimble:multi-initiator': 'false'}))
    @NimbleDriverBaseTestCase.client_mock_decorator(create_configuration(
        'nimble', 'nimble_pass', '10.18.108.55', 'default', '*'))
    def test_create_volume_encryption_positive(self):
        self.mock_client_service._execute_create_vol.return_value = (
            FAKE_CREATE_VOLUME_POSITIVE_RESPONSE_ENCRYPTION)
        self.mock_client_service.get_vol_info.return_value = (
            FAKE_GET_VOL_INFO_RESPONSE)
        self.mock_client_service.get_netconfig.return_value = (
            FAKE_POSITIVE_NETCONFIG_RESPONSE)

        volume = {'name': 'testvolume-encryption',
                  'size': 1,
                  'volume_type_id': FAKE_TYPE_ID,
                  'display_name': '',
                  'display_description': ''}
        self.assertEqual({
            'provider_location': '172.18.108.21:3260 iqn.test',
            'provider_auth': None},
            self.driver.create_volume(volume))

        self.mock_client_service.create_vol.assert_called_once_with(
            {'name': 'testvolume-encryption',
             'size': 1,
             'volume_type_id': FAKE_TYPE_ID,
             'display_name': '',
             'display_description': '',
             },
            'default',
            False,
            'iSCSI',
            False)

    @mock.patch(NIMBLE_URLLIB2)
    @mock.patch(NIMBLE_CLIENT)
    @mock.patch.object(obj_volume.VolumeList, 'get_all_by_host',
                       mock.Mock(return_value=[]))
    @mock.patch.object(volume_types, 'get_volume_type_extra_specs',
                       mock.Mock(type_id=FAKE_TYPE_ID, return_value={
                           'nimble:perfpol-name': 'VMware ESX',
                           'nimble:encryption': 'no',
                           'nimble:multi-initiator': 'false'}))
    @NimbleDriverBaseTestCase.client_mock_decorator(create_configuration(
        'nimble', 'nimble_pass', '10.18.108.55', 'default', '*'))
    def test_create_volume_perfpolicy_positive(self):
        self.mock_client_service._execute_create_vol.return_value = (
            FAKE_CREATE_VOLUME_POSITIVE_RESPONSE_PERF_POLICY)
        self.mock_client_service.get_vol_info.return_value = (
            FAKE_GET_VOL_INFO_RESPONSE)
        self.mock_client_service.get_netconfig.return_value = (
            FAKE_POSITIVE_NETCONFIG_RESPONSE)

        self.assertEqual(
            {'provider_location': '172.18.108.21:3260 iqn.test',
             'provider_auth': None},
            self.driver.create_volume({'name': 'testvolume-perfpolicy',
                                       'size': 1,
                                       'volume_type_id': FAKE_TYPE_ID,
                                       'display_name': '',
                                       'display_description': ''}))

        self.mock_client_service.create_vol.assert_called_once_with(
            {'name': 'testvolume-perfpolicy',
             'size': 1,
             'volume_type_id': FAKE_TYPE_ID,
             'display_name': '',
             'display_description': '',
             },
            'default',
            False,
            'iSCSI',
            False)

    @mock.patch(NIMBLE_URLLIB2)
    @mock.patch(NIMBLE_CLIENT)
    @mock.patch.object(obj_volume.VolumeList, 'get_all_by_host',
                       mock.Mock(return_value=[]))
    @mock.patch.object(volume_types, 'get_volume_type_extra_specs',
                       mock.Mock(type_id=FAKE_TYPE_ID, return_value={
                           'nimble:perfpol-name': 'default',
                           'nimble:encryption': 'no',
                           'nimble:multi-initiator': 'true'}))
    @NimbleDriverBaseTestCase.client_mock_decorator(create_configuration(
        'nimble', 'nimble_pass', '10.18.108.55', 'default', '*'))
    def test_create_volume_multi_initiator_positive(self):
        self.mock_client_service._execute_create_vol.return_value = (
            FAKE_CREATE_VOLUME_POSITIVE_RESPONSE_MULTI_INITIATOR)
        self.mock_client_service.get_vol_info.return_value = (
            FAKE_GET_VOL_INFO_RESPONSE)
        self.mock_client_service.get_netconfig.return_value = (
            FAKE_POSITIVE_NETCONFIG_RESPONSE)

        self.assertEqual(
            {'provider_location': '172.18.108.21:3260 iqn.test',
             'provider_auth': None},
            self.driver.create_volume({'name': 'testvolume-multi-initiator',
                                       'size': 1,
                                       'volume_type_id': FAKE_TYPE_ID,
                                       'display_name': '',
                                       'display_description': ''}))

        self.mock_client_service.create_vol.assert_called_once_with(
            {'name': 'testvolume-multi-initiator',
             'size': 1,
             'volume_type_id': FAKE_TYPE_ID,
             'display_name': '',
             'display_description': '',
             },
            'default',
            False,
            'iSCSI',
            False)

    @mock.patch(NIMBLE_URLLIB2)
    @mock.patch(NIMBLE_CLIENT)
    @mock.patch.object(obj_volume.VolumeList, 'get_all_by_host',
                       mock.Mock(return_value=[]))
    @mock.patch.object(volume_types, 'get_volume_type_extra_specs',
                       mock.Mock(type_id=FAKE_TYPE_ID, return_value={
                           'nimble:perfpol-name': 'default',
                           'nimble:encryption': 'no',
                           'nimble:dedupe': 'true'}))
    @NimbleDriverBaseTestCase.client_mock_decorator(create_configuration(
        'nimble', 'nimble_pass', '10.18.108.55', 'default', '*'))
    def test_create_volume_dedupe_positive(self):
        self.mock_client_service._execute_create_vol.return_value = (
            FAKE_CREATE_VOLUME_POSITIVE_RESPONSE_DEDUPE)
        self.mock_client_service.get_vol_info.return_value = (
            FAKE_GET_VOL_INFO_RESPONSE)
        self.mock_client_service.get_netconfig.return_value = (
            FAKE_POSITIVE_NETCONFIG_RESPONSE)

        self.assertEqual(
            {'provider_location': '172.18.108.21:3260 iqn.test',
             'provider_auth': None},
            self.driver.create_volume({'name': 'testvolume-dedupe',
                                       'size': 1,
                                       'volume_type_id': FAKE_TYPE_ID,
                                       'display_name': '',
                                       'display_description': ''}))

        self.mock_client_service.create_vol.assert_called_once_with(
            {'name': 'testvolume-dedupe',
             'size': 1,
             'volume_type_id': FAKE_TYPE_ID,
             'display_name': '',
             'display_description': '',
             },
            'default',
            False,
            'iSCSI',
            False)

    @mock.patch(NIMBLE_URLLIB2)
    @mock.patch(NIMBLE_CLIENT)
    @mock.patch.object(obj_volume.VolumeList, 'get_all_by_host',
                       mock.Mock(return_value=[]))
    @mock.patch.object(volume_types, 'get_volume_type_extra_specs',
                       mock.Mock(type_id=FAKE_TYPE_ID, return_value={
                           'nimble:perfpol-name': 'default',
                           'nimble:iops-limit': '1024'}))
    @NimbleDriverBaseTestCase.client_mock_decorator(create_configuration(
        'nimble', 'nimble_pass', '10.18.108.55', 'default', '*'))
    def test_create_volume_qos_positive(self):
        self.mock_client_service._execute_create_vol.return_value = (
            FAKE_CREATE_VOLUME_POSITIVE_RESPONSE_QOS)
        self.mock_client_service.get_vol_info.return_value = (
            FAKE_GET_VOL_INFO_RESPONSE)
        self.mock_client_service.get_netconfig.return_value = (
            FAKE_POSITIVE_NETCONFIG_RESPONSE)

        self.assertEqual(
            {'provider_location': '172.18.108.21:3260 iqn.test',
             'provider_auth': None},
            self.driver.create_volume({'name': 'testvolume-qos',
                                       'size': 1,
                                       'volume_type_id': FAKE_TYPE_ID,
                                       'display_name': '',
                                       'display_description': ''}))

        self.mock_client_service.create_vol.assert_called_once_with(
            {'name': 'testvolume-qos',
             'size': 1,
             'volume_type_id': FAKE_TYPE_ID,
             'display_name': '',
             'display_description': '',
             },
            'default',
            False,
            'iSCSI',
            False)

    @mock.patch(NIMBLE_URLLIB2)
    @mock.patch(NIMBLE_CLIENT)
    @mock.patch.object(obj_volume.VolumeList, 'get_all_by_host',
                       mock.Mock(return_value=[]))
    @NimbleDriverBaseTestCase.client_mock_decorator(create_configuration(
        'nimble', 'nimble_pass', '10.18.108.55', 'default', '*'))
    @mock.patch.object(volume_types, 'get_volume_type_extra_specs',
                       mock.Mock(type_id=FAKE_TYPE_ID, return_value={
                           'nimble:perfpol-name': 'default',
                           'nimble:encryption': 'no',
                           'nimble:multi-initiator': 'true'}))
    def test_create_volume_negative(self):
        self.mock_client_service.get_vol_info.side_effect = (
            FAKE_CREATE_VOLUME_NEGATIVE_RESPONSE)

        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.driver.create_volume,
            {'name': 'testvolume',
             'size': 1,
             'volume_type_id': FAKE_TYPE_ID,
             'display_name': '',
             'display_description': ''})

    @mock.patch(NIMBLE_URLLIB2)
    @mock.patch(NIMBLE_CLIENT)
    @mock.patch.object(obj_volume.VolumeList, 'get_all_by_host',
                       mock.Mock(return_value=[]))
    @NimbleDriverBaseTestCase.client_mock_decorator(create_configuration(
        'nimble', 'nimble_pass', '10.18.108.55', 'default', '*'))
    def test_create_volume_encryption_negative(self):
        self.mock_client_service.get_vol_info.side_effect = (
            FAKE_CREATE_VOLUME_NEGATIVE_ENCRYPTION)
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.driver.create_volume,
            {'name': 'testvolume-encryption',
             'size': 1,
             'volume_type_id': None,
             'display_name': '',
             'display_description': ''})

    @mock.patch(NIMBLE_URLLIB2)
    @mock.patch(NIMBLE_CLIENT)
    @mock.patch.object(obj_volume.VolumeList, 'get_all_by_host',
                       mock.Mock(return_value=[]))
    @NimbleDriverBaseTestCase.client_mock_decorator(create_configuration(
        'nimble', 'nimble_pass', '10.18.108.55', 'default', '*'))
    def test_create_volume_perfpolicy_negative(self):
        self.mock_client_service.get_vol_info.side_effect = (
            FAKE_CREATE_VOLUME_NEGATIVE_PERFPOLICY)
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.driver.create_volume,
            {'name': 'testvolume-perfpolicy',
             'size': 1,
             'volume_type_id': None,
             'display_name': '',
             'display_description': ''})

    @mock.patch(NIMBLE_URLLIB2)
    @mock.patch(NIMBLE_CLIENT)
    @mock.patch.object(obj_volume.VolumeList, 'get_all_by_host',
                       mock.Mock(return_value=[]))
    @NimbleDriverBaseTestCase.client_mock_decorator(create_configuration(
        'nimble', 'nimble_pass', '10.18.108.55', 'default', '*'))
    def test_create_volume_dedupe_negative(self):
        self.mock_client_service.get_vol_info.side_effect = (
            FAKE_CREATE_VOLUME_NEGATIVE_DEDUPE)
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.driver.create_volume,
            {'name': 'testvolume-dedupe',
             'size': 1,
             'volume_type_id': None,
             'display_name': '',
             'display_description': ''})

    @mock.patch(NIMBLE_URLLIB2)
    @mock.patch(NIMBLE_CLIENT)
    @mock.patch.object(obj_volume.VolumeList, 'get_all_by_host',
                       mock.Mock(return_value=[]))
    @NimbleDriverBaseTestCase.client_mock_decorator(create_configuration(
        'nimble', 'nimble_pass', '10.18.108.55', 'default', '*'))
    @mock.patch.object(volume_types, 'get_volume_type_extra_specs',
                       mock.Mock(type_id=FAKE_TYPE_ID, return_value={
                           'nimble:perfpol-name': 'default',
                           'nimble:iops-limit': '200'}))
    def test_create_volume_qos_negative(self):
        self.mock_client_service.get_vol_info.side_effect = (
            FAKE_CREATE_VOLUME_NEGATIVE_QOS)
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.driver.create_volume,
            {'name': 'testvolume-qos',
             'size': 1,
             'volume_type_id': None,
             'display_name': '',
             'display_description': ''})

    @mock.patch(NIMBLE_URLLIB2)
    @mock.patch(NIMBLE_CLIENT)
    @mock.patch.object(obj_volume.VolumeList, 'get_all_by_host',
                       mock.Mock(return_value=[]))
    @NimbleDriverBaseTestCase.client_mock_decorator(create_configuration(
        'nimble', 'nimble_pass', '10.18.108.55', 'default', '*'))
    @mock.patch(NIMBLE_ISCSI_DRIVER + ".is_volume_backup_clone", mock.Mock(
        return_value = ['', '']))
    def test_delete_volume(self):
        self.mock_client_service.online_vol.return_value = (
            FAKE_GENERIC_POSITIVE_RESPONSE)
        self.mock_client_service.delete_vol.return_value = (
            FAKE_GENERIC_POSITIVE_RESPONSE)
        self.driver.delete_volume({'name': 'testvolume'})
        expected_calls = [mock.call.online_vol(
            'testvolume', False),
            mock.call.delete_vol('testvolume')]

        self.mock_client_service.assert_has_calls(expected_calls)

    @mock.patch(NIMBLE_URLLIB2)
    @mock.patch(NIMBLE_CLIENT)
    @NimbleDriverBaseTestCase.client_mock_decorator(create_configuration(
        'nimble', 'nimble_pass', '10.18.108.55', 'default', '*'))
    @mock.patch(NIMBLE_ISCSI_DRIVER + ".is_volume_backup_clone", mock.Mock(
        return_value=['test-backup-snap', 'volume-' + fake.VOLUME_ID]))
    @mock.patch.object(obj_volume.VolumeList, 'get_all_by_host')
    def test_delete_volume_with_backup(self, mock_volume_list):
        mock_volume_list.return_value = []
        self.mock_client_service.online_vol.return_value = (
            FAKE_GENERIC_POSITIVE_RESPONSE)
        self.mock_client_service.delete_vol.return_value = (
            FAKE_GENERIC_POSITIVE_RESPONSE)
        self.mock_client_service.online_snap.return_value = (
            FAKE_GENERIC_POSITIVE_RESPONSE)
        self.mock_client_service.delete_snap.return_value = (
            FAKE_GENERIC_POSITIVE_RESPONSE)

        self.driver.delete_volume({'name': 'testvolume'})
        expected_calls = [mock.call.online_vol(
            'testvolume', False),
            mock.call.delete_vol('testvolume'),
            mock.call.online_snap('volume-' + fake.VOLUME_ID,
                                  False,
                                  'test-backup-snap'),
            mock.call.delete_snap('volume-' + fake.VOLUME_ID,
                                  'test-backup-snap')]

        self.mock_client_service.assert_has_calls(expected_calls)

    @mock.patch(NIMBLE_URLLIB2)
    @mock.patch(NIMBLE_CLIENT)
    @mock.patch.object(obj_volume.VolumeList, 'get_all_by_host',
                       mock.Mock(return_value=[]))
    @NimbleDriverBaseTestCase.client_mock_decorator(create_configuration(
        'nimble', 'nimble_pass', '10.18.108.55', 'default', '*'))
    def test_extend_volume(self):
        self.mock_client_service.edit_vol.return_value = (
            FAKE_CREATE_VOLUME_POSITIVE_RESPONSE)
        self.driver.extend_volume({'name': 'testvolume'}, 5)

        self.mock_client_service.edit_vol.assert_called_once_with(
            'testvolume', FAKE_EXTEND_VOLUME_PARAMS)

    @mock.patch(NIMBLE_URLLIB2)
    @mock.patch(NIMBLE_CLIENT)
    @mock.patch.object(volume_types, 'get_volume_type_extra_specs',
                       mock.Mock(type_id=FAKE_TYPE_ID,
                                 return_value=
                                 {'nimble:perfpol-name': 'default',
                                  'nimble:encryption': 'yes',
                                  'nimble:multi-initiator': 'false',
                                  'nimble:iops-limit': '1024'}))
    @NimbleDriverBaseTestCase.client_mock_decorator(create_configuration(
        'nimble', 'nimble_pass', '10.18.108.55', 'default', '*', False))
    @mock.patch.object(obj_volume.VolumeList, 'get_all_by_host')
    @mock.patch(NIMBLE_RANDOM)
    def test_create_cloned_volume(self, mock_random, mock_volume_list):
        mock_random.sample.return_value = fake.VOLUME_ID
        mock_volume_list.return_value = []
        self.mock_client_service.snap_vol.return_value = (
            FAKE_GENERIC_POSITIVE_RESPONSE)
        self.mock_client_service.clone_vol.return_value = (
            FAKE_GENERIC_POSITIVE_RESPONSE)
        self.mock_client_service.get_vol_info.return_value = (
            FAKE_GET_VOL_INFO_RESPONSE)
        self.mock_client_service.get_netconfig.return_value = (
            FAKE_POSITIVE_NETCONFIG_RESPONSE)

        volume = obj_volume.Volume(context.get_admin_context(),
                                   id=fake.VOLUME_ID,
                                   size=5.0,
                                   _name_id=None,
                                   display_name='',
                                   volume_type_id=FAKE_TYPE_ID
                                   )
        src_volume = obj_volume.Volume(context.get_admin_context(),
                                       id=fake.VOLUME2_ID,
                                       _name_id=None,
                                       size=5.0)
        self.assertEqual({
            'provider_location': '172.18.108.21:3260 iqn.test',
            'provider_auth': None},
            self.driver.create_cloned_volume(volume, src_volume))

        expected_calls = [mock.call.snap_vol(
            {'volume_name': "volume-" + fake.VOLUME2_ID,
                'name': 'openstack-clone-volume-' + fake.VOLUME_ID + "-" +
                        fake.VOLUME_ID,
                'volume_size': src_volume['size'],
                'display_name': volume['display_name'],
                'display_description': ''}),
            mock.call.clone_vol(volume,
                                {'volume_name': "volume-" + fake.VOLUME2_ID,
                                 'name': 'openstack-clone-volume-' +
                                         fake.VOLUME_ID + "-" +
                                         fake.VOLUME_ID,
                                 'volume_size': src_volume['size'],
                                 'display_name': volume['display_name'],
                                 'display_description': ''},
                                True, False, 'iSCSI', 'default')]

        self.mock_client_service.assert_has_calls(expected_calls)

    @mock.patch(NIMBLE_URLLIB2)
    @mock.patch(NIMBLE_CLIENT)
    @mock.patch.object(obj_volume.VolumeList, 'get_all_by_host',
                       mock.Mock(return_value=[]))
    @NimbleDriverBaseTestCase.client_mock_decorator(create_configuration(
        'nimble', 'nimble_pass', '10.18.108.55', 'default', '*'))
    def test_manage_volume_positive(self):
        self.mock_client_service.get_netconfig.return_value = (
            FAKE_POSITIVE_NETCONFIG_RESPONSE)
        self.mock_client_service.get_vol_info.return_value = (
            FAKE_GET_VOL_INFO_RESPONSE_MANAGE)
        self.mock_client_service.online_vol.return_value = (
            FAKE_GENERIC_POSITIVE_RESPONSE)
        self.mock_client_service.edit_vol.return_value = (
            FAKE_CREATE_VOLUME_POSITIVE_RESPONSE)
        self.assertEqual({
            'provider_location': '172.18.108.21:3260 iqn.test',
            'provider_auth': None},
            self.driver.manage_existing({'name': 'volume-abcdef',
                                         'id': fake.VOLUME_ID,
                                         'agent_type': None},
                                        {'source-name': 'test-vol'}))
        expected_calls = [mock.call.edit_vol(
            'test-vol', {'data': {'agent_type': 'openstack',
                                  'name': 'volume-abcdef'}}),
            mock.call.online_vol('volume-abcdef', True)]
        self.mock_client_service.assert_has_calls(expected_calls)

    @mock.patch(NIMBLE_URLLIB2)
    @mock.patch(NIMBLE_CLIENT)
    @mock.patch.object(obj_volume.VolumeList, 'get_all_by_host',
                       mock.Mock(return_value=[]))
    @NimbleDriverBaseTestCase.client_mock_decorator(create_configuration(
        'nimble', 'nimble_pass', '10.18.108.55', 'default', '*'))
    def test_manage_volume_which_is_online(self):
        self.mock_client_service.get_netconfig.return_value = (
            FAKE_POSITIVE_NETCONFIG_RESPONSE)
        self.mock_client_service.get_vol_info.return_value = (
            FAKE_GET_VOL_INFO_ONLINE)
        self.assertRaises(
            exception.InvalidVolume,
            self.driver.manage_existing,
            {'name': 'volume-abcdef'},
            {'source-name': 'test-vol'})

    @mock.patch(NIMBLE_URLLIB2)
    @mock.patch(NIMBLE_CLIENT)
    @mock.patch.object(obj_volume.VolumeList, 'get_all_by_host',
                       mock.Mock(return_value=[]))
    @NimbleDriverBaseTestCase.client_mock_decorator(create_configuration(
        'nimble', 'nimble_pass', '10.18.108.55', 'default', '*'))
    def test_manage_volume_get_size(self):
        self.mock_client_service.get_netconfig.return_value = (
            FAKE_POSITIVE_NETCONFIG_RESPONSE)
        self.mock_client_service.get_vol_info.return_value = (
            FAKE_GET_VOL_INFO_ONLINE)
        size = self.driver.manage_existing_get_size(
            {'name': 'volume-abcdef'}, {'source-name': 'test-vol'})
        self.assertEqual(2, size)

    @mock.patch(NIMBLE_URLLIB2)
    @mock.patch(NIMBLE_CLIENT)
    @mock.patch.object(obj_volume.VolumeList, 'get_all',
                       mock.Mock(return_value=[]))
    @NimbleDriverBaseTestCase.client_mock_decorator(create_configuration(
        'nimble', 'nimble_pass', '10.18.108.55', 'default', '*'))
    def test_manage_volume_with_improper_ref(self):
        self.assertRaises(
            exception.ManageExistingInvalidReference,
            self.driver.manage_existing,
            {'name': 'volume-abcdef'},
            {'source-id': 'test-vol'})

    @mock.patch(NIMBLE_URLLIB2)
    @mock.patch(NIMBLE_CLIENT)
    @mock.patch.object(obj_volume.VolumeList, 'get_all_by_host',
                       mock.Mock(return_value=[]))
    @NimbleDriverBaseTestCase.client_mock_decorator(create_configuration(
        'nimble', 'nimble_pass', '10.18.108.55', 'default', '*'))
    def test_manage_volume_with_nonexistant_volume(self):
        self.mock_client_service.get_vol_info.side_effect = (
            FAKE_VOLUME_INFO_NEGATIVE_RESPONSE)
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.driver.manage_existing,
            {'name': 'volume-abcdef'},
            {'source-name': 'test-vol'})

    @mock.patch(NIMBLE_URLLIB2)
    @mock.patch(NIMBLE_CLIENT)
    @mock.patch.object(obj_volume.VolumeList, 'get_all_by_host',
                       mock.Mock(return_value=[]))
    @NimbleDriverBaseTestCase.client_mock_decorator(create_configuration(
        'nimble', 'nimble_pass', '10.18.108.55', 'default', '*'))
    def test_manage_volume_with_wrong_agent_type(self):
        self.mock_client_service.get_vol_info.return_value = (
            FAKE_GET_VOL_INFO_RESPONSE)
        self.assertRaises(
            exception.ManageExistingAlreadyManaged,
            self.driver.manage_existing,
            {'id': 'abcdef', 'name': 'volume-abcdef'},
            {'source-name': 'test-vol'})

    @mock.patch(NIMBLE_URLLIB2)
    @mock.patch(NIMBLE_CLIENT)
    @mock.patch.object(obj_volume.VolumeList, 'get_all_by_host',
                       mock.Mock(return_value=[]))
    @NimbleDriverBaseTestCase.client_mock_decorator(create_configuration(
        'nimble', 'nimble_pass', '10.18.108.55', 'default', '*'))
    def test_unmanage_volume_positive(self):
        self.mock_client_service.get_vol_info.return_value = (
            FAKE_GET_VOL_INFO_RESPONSE)
        self.mock_client_service.edit_vol.return_value = (
            FAKE_CREATE_VOLUME_POSITIVE_RESPONSE)
        self.driver.unmanage({'name': 'volume-abcdef'})
        expected_calls = [
            mock.call.edit_vol(
                'volume-abcdef',
                {'data': {'agent_type': 'none'}}),

            mock.call.online_vol('volume-abcdef', False)]

        self.mock_client_service.assert_has_calls(expected_calls)

    @mock.patch(NIMBLE_URLLIB2)
    @mock.patch(NIMBLE_CLIENT)
    @mock.patch.object(obj_volume.VolumeList, 'get_all_by_host',
                       mock.Mock(return_value=[]))
    @NimbleDriverBaseTestCase.client_mock_decorator(create_configuration(
        'nimble', 'nimble_pass', '10.18.108.55', 'default', '*'))
    def test_unmanage_with_invalid_volume(self):
        self.mock_client_service.get_vol_info.side_effect = (
            FAKE_VOLUME_INFO_NEGATIVE_RESPONSE)
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.driver.unmanage,
            {'name': 'volume-abcdef'}
        )

    @mock.patch(NIMBLE_URLLIB2)
    @mock.patch(NIMBLE_CLIENT)
    @mock.patch.object(obj_volume.VolumeList, 'get_all_by_host',
                       mock.Mock(return_value=[]))
    @NimbleDriverBaseTestCase.client_mock_decorator(create_configuration(
        'nimble', 'nimble_pass', '10.18.108.55', 'default', '*'))
    def test_unmanage_with_invalid_agent_type(self):
        self.mock_client_service.get_vol_info.return_value = (
            FAKE_GET_VOL_INFO_ONLINE)
        self.assertRaises(
            exception.InvalidVolume,
            self.driver.unmanage,
            {'name': 'volume-abcdef'}
        )

    @mock.patch(NIMBLE_URLLIB2)
    @mock.patch(NIMBLE_CLIENT)
    @mock.patch.object(obj_volume.VolumeList, 'get_all_by_host',
                       mock.Mock(return_value=[]))
    @NimbleDriverBaseTestCase.client_mock_decorator(create_configuration(
        'nimble', 'nimble_pass', '10.18.108.55', 'default', '*'))
    def test_get_volume_stats(self):
        self.mock_client_service.get_group_info.return_value = (
            FAKE_POSITIVE_GROUP_INFO_RESPONSE)
        expected_res = {'driver_version': DRIVER_VERSION,
                        'vendor_name': 'Nimble',
                        'volume_backend_name': 'NIMBLE',
                        'storage_protocol': 'iSCSI',
                        'pools': [{'pool_name': 'NIMBLE',
                                   'total_capacity_gb': 7466.30419921875,
                                   'free_capacity_gb': 7463.567649364471,
                                   'reserved_percentage': 0,
                                   'QoS_support': False}]}
        self.assertEqual(
            expected_res,
            self.driver.get_volume_stats(refresh=True))

    @mock.patch(NIMBLE_URLLIB2)
    @mock.patch(NIMBLE_CLIENT)
    @mock.patch.object(obj_volume.VolumeList, 'get_all_by_host',
                       mock.Mock(return_value=[]))
    @NimbleDriverBaseTestCase.client_mock_decorator(create_configuration(
        'nimble', 'nimble_pass', '10.18.108.55', 'default', '*'))
    def test_is_volume_backup_clone(self):
        self.mock_client_service.get_vol_info.return_value = (
            FAKE_GET_VOL_INFO_BACKUP_RESPONSE)
        self.mock_client_service.get_snap_info_by_id.return_value = (
            FAKE_GET_SNAP_INFO_BACKUP_RESPONSE)
        self.mock_client_service.get_snap_info_detail.return_value = (
            FAKE_GET_SNAP_INFO_BACKUP_RESPONSE)
        self.mock_client_service.get_volume_name.return_value = (
            'volume-' + fake.VOLUME2_ID)

        volume = obj_volume.Volume(context.get_admin_context(),
                                   id=fake.VOLUME_ID,
                                   _name_id=None)
        self.assertEqual(("test-backup-snap", "volume-" + fake.VOLUME2_ID),
                         self.driver.is_volume_backup_clone(volume))
        expected_calls = [
            mock.call.get_vol_info('volume-' + fake.VOLUME_ID),
            mock.call.get_snap_info_by_id('test-backup-snap',
                                          'volume-' + fake.VOLUME2_ID)
        ]
        self.mock_client_service.assert_has_calls(expected_calls)


class NimbleDriverSnapshotTestCase(NimbleDriverBaseTestCase):

    """Tests snapshot related api's."""

    @mock.patch(NIMBLE_URLLIB2)
    @mock.patch(NIMBLE_CLIENT)
    @mock.patch.object(obj_volume.VolumeList, 'get_all_by_host',
                       mock.Mock(return_value=[]))
    @NimbleDriverBaseTestCase.client_mock_decorator(create_configuration(
        'nimble', 'nimble_pass', '10.18.108.55', 'default', '*'))
    def test_create_snapshot(self):
        self.mock_client_service.snap_vol.return_value = (
            FAKE_GENERIC_POSITIVE_RESPONSE)
        self.driver.create_snapshot(
            {'volume_name': 'testvolume',
             'name': 'testvolume-snap1',
             'display_name': ''})
        self.mock_client_service.snap_vol.assert_called_once_with(
            {'volume_name': 'testvolume',
             'name': 'testvolume-snap1',
             'display_name': ''})

    @mock.patch(NIMBLE_URLLIB2)
    @mock.patch(NIMBLE_CLIENT)
    @mock.patch.object(obj_volume.VolumeList, 'get_all_by_host',
                       mock.Mock(return_value=[]))
    @NimbleDriverBaseTestCase.client_mock_decorator(create_configuration(
        'nimble', 'nimble_pass', '10.18.108.55', 'default', '*'))
    def test_delete_snapshot(self):
        self.mock_client_service.online_snap.return_value = (
            FAKE_GENERIC_POSITIVE_RESPONSE)
        self.mock_client_service.delete_snap.return_value = (
            FAKE_GENERIC_POSITIVE_RESPONSE)
        self.driver.delete_snapshot(
            {'volume_name': 'testvolume',
             'name': 'testvolume-snap1'})
        expected_calls = [mock.call.online_snap(
            'testvolume', False, 'testvolume-snap1'),
            mock.call.delete_snap('testvolume',
                                  'testvolume-snap1')]
        self.mock_client_service.assert_has_calls(expected_calls)

    @mock.patch(NIMBLE_URLLIB2)
    @mock.patch(NIMBLE_CLIENT)
    @mock.patch.object(obj_volume.VolumeList, 'get_all_by_host',
                       mock.Mock(return_value=[]))
    @mock.patch.object(volume_types, 'get_volume_type_extra_specs',
                       mock.Mock(type_id=FAKE_TYPE_ID, return_value={
                                 'nimble:perfpol-name': 'default',
                                 'nimble:encryption': 'yes',
                                 'nimble:multi-initiator': 'false'}))
    @NimbleDriverBaseTestCase.client_mock_decorator(create_configuration(
        'nimble', 'nimble_pass', '10.18.108.55', 'default', '*'))
    def test_create_volume_from_snapshot(self):
        self.mock_client_service.clone_vol.return_value = (
            FAKE_GENERIC_POSITIVE_RESPONSE)
        self.mock_client_service.get_vol_info.return_value = (
            FAKE_GET_VOL_INFO_RESPONSE)
        self.mock_client_service.get_netconfig.return_value = (
            FAKE_POSITIVE_NETCONFIG_RESPONSE)
        self.assertEqual({
            'provider_location': '172.18.108.21:3260 iqn.test',
            'provider_auth': None},
            self.driver.create_volume_from_snapshot(
                {'name': 'clone-testvolume',
                 'size': 2,
                 'volume_type_id': FAKE_TYPE_ID},
                {'volume_name': 'testvolume',
                 'name': 'testvolume-snap1',
                 'volume_size': 1}))
        expected_calls = [
            mock.call.clone_vol(
                {'name': 'clone-testvolume',
                 'volume_type_id': FAKE_TYPE_ID,
                 'size': 2},
                {'volume_name': 'testvolume',
                 'name': 'testvolume-snap1',
                 'volume_size': 1},
                False,
                False,
                'iSCSI',
                'default'),
            mock.call.edit_vol('clone-testvolume',
                               {'data': {'size': 2048,
                                         'snap_limit': sys.maxsize,
                                         'warn_level': 80,
                                         'reserve': 0,
                                         'limit': 100}})]
        self.mock_client_service.assert_has_calls(expected_calls)


class NimbleDriverConnectionTestCase(NimbleDriverBaseTestCase):

    """Tests Connection related api's."""

    @mock.patch(NIMBLE_URLLIB2)
    @mock.patch(NIMBLE_CLIENT)
    @mock.patch.object(obj_volume.VolumeList, 'get_all_by_host',
                       mock.Mock(return_value=[]))
    @NimbleDriverBaseTestCase.client_mock_decorator(create_configuration(
        'nimble', 'nimble_pass', '10.18.108.55', 'default', '*'))
    def test_initialize_connection_igroup_exist(self):
        self.mock_client_service.get_initiator_grp_list.return_value = (
            FAKE_IGROUP_LIST_RESPONSE)
        expected_res = {
            'driver_volume_type': 'iscsi',
            'data': {
                'volume_id': 12,
                'target_iqn': '13',
                'target_lun': 0,
                'target_portal': '12'}}
        self.assertEqual(
            expected_res,
            self.driver.initialize_connection(
                {'name': 'test-volume',
                 'provider_location': '12 13',
                 'id': 12},
                {'initiator': 'test-initiator1'}))

    @mock.patch(NIMBLE_URLLIB2)
    @mock.patch(NIMBLE_CLIENT)
    @mock.patch.object(obj_volume.VolumeList, 'get_all_by_host',
                       mock.Mock(return_value=[]))
    @NimbleDriverBaseTestCase.client_mock_decorator(create_configuration(
        'nimble', 'nimble_pass', '10.18.108.55', 'default', '*'))
    def test_initialize_connection_live_migration(self):
        self.mock_client_service.get_initiator_grp_list.return_value = (
            FAKE_IGROUP_LIST_RESPONSE)
        expected_res = {
            'driver_volume_type': 'iscsi',
            'data': {
                'volume_id': 12,
                'target_iqn': '13',
                'target_lun': 0,
                'target_portal': '12'}}

        self.assertEqual(
            expected_res,
            self.driver.initialize_connection(
                {'name': 'test-volume',
                 'provider_location': '12 13',
                 'id': 12},
                {'initiator': 'test-initiator1'}))

        self.driver.initialize_connection(
            {'name': 'test-volume',
             'provider_location': '12 13',
             'id': 12},
            {'initiator': 'test-initiator1'})

        # 2 or more calls to initialize connection and add_acl for live
        # migration to work
        expected_calls = [
            mock.call.get_initiator_grp_list(),
            mock.call.add_acl({'name': 'test-volume',
                               'provider_location': '12 13',
                               'id': 12},
                              'test-igrp1'),
            mock.call.get_initiator_grp_list(),
            mock.call.add_acl({'name': 'test-volume',
                               'provider_location': '12 13',
                               'id': 12},
                              'test-igrp1')]
        self.mock_client_service.assert_has_calls(expected_calls)

    @mock.patch(NIMBLE_URLLIB2)
    @mock.patch(NIMBLE_CLIENT)
    @mock.patch.object(obj_volume.VolumeList, 'get_all_by_host',
                       mock.Mock(return_value=[]))
    @NimbleDriverBaseTestCase.client_mock_decorator_fc(create_configuration(
        'nimble', 'nimble_pass', '10.18.108.55', 'default', '*'))
    @mock.patch(NIMBLE_FC_DRIVER + ".get_lun_number")
    @mock.patch(NIMBLE_FC_DRIVER + ".get_wwpns_from_array")
    def test_initialize_connection_fc_igroup_exist(self, mock_wwpns,
                                                   mock_lun_number):
        mock_lun_number.return_value = 13
        mock_wwpns.return_value = ["1111111111111101"]
        self.mock_client_service.get_initiator_grp_list.return_value = (
            FAKE_IGROUP_LIST_RESPONSE_FC)
        expected_res = {
            'driver_volume_type': 'fibre_channel',
            'data': {
                'target_lun': 13,
                'target_discovered': True,
                'target_wwn': ["1111111111111101"],
                'initiator_target_map': {'1000000000000000':
                                         ['1111111111111101']}}}
        self.assertEqual(
            expected_res,
            self.driver.initialize_connection(
                {'name': 'test-volume',
                 'provider_location': 'array1',
                 'id': 12},
                {'initiator': 'test-initiator1',
                 'wwpns': ['1000000000000000']}))

    @mock.patch(NIMBLE_URLLIB2)
    @mock.patch(NIMBLE_CLIENT)
    @mock.patch.object(obj_volume.VolumeList, 'get_all_by_host',
                       mock.Mock(return_value=[]))
    @NimbleDriverBaseTestCase.client_mock_decorator(create_configuration(
        'nimble', 'nimble_pass', '10.18.108.55', 'default', '*'))
    @mock.patch(NIMBLE_RANDOM)
    def test_initialize_connection_igroup_not_exist(self, mock_random):
        mock_random.sample.return_value = 'abcdefghijkl'
        self.mock_client_service.get_initiator_grp_list.return_value = (
            FAKE_IGROUP_LIST_RESPONSE)
        expected_res = {
            'driver_volume_type': 'iscsi',
            'data': {
                'target_lun': 0,
                'volume_id': 12,
                'target_iqn': '13',
                'target_portal': '12'}}
        self.assertEqual(
            expected_res,
            self.driver.initialize_connection(
                {'name': 'test-volume',
                 'provider_location': '12 13',
                 'id': 12},
                {'initiator': 'test-initiator3'}))

    @mock.patch(NIMBLE_URLLIB2)
    @mock.patch(NIMBLE_CLIENT)
    @mock.patch.object(obj_volume.VolumeList, 'get_all_by_host',
                       mock.Mock(return_value=[]))
    @NimbleDriverBaseTestCase.client_mock_decorator_fc(create_configuration(
        'nimble', 'nimble_pass', '10.18.108.55', 'default', '*'))
    @mock.patch(NIMBLE_FC_DRIVER + ".get_wwpns_from_array")
    @mock.patch(NIMBLE_FC_DRIVER + ".get_lun_number")
    @mock.patch(NIMBLE_RANDOM)
    def test_initialize_connection_fc_igroup_not_exist(self, mock_random,
                                                       mock_lun_number,
                                                       mock_wwpns):
        mock_random.sample.return_value = 'abcdefghijkl'
        mock_lun_number.return_value = 13
        mock_wwpns.return_value = ["1111111111111101"]
        self.mock_client_service.get_initiator_grp_list.return_value = (
            FAKE_IGROUP_LIST_RESPONSE_FC)
        expected_res = {
            'driver_volume_type': 'fibre_channel',
            'data': {
                'target_lun': 13,
                'target_discovered': True,
                'target_wwn': ["1111111111111101"],
                'initiator_target_map': {'1000000000000000':
                                         ['1111111111111101']}}}

        self.driver._create_igroup_for_initiator("test-initiator3",
                                                 [1111111111111101])
        self.assertEqual(
            expected_res,
            self.driver.initialize_connection(
                {'name': 'test-volume',
                 'provider_location': 'array1',
                 'id': 12},
                {'initiator': 'test-initiator3',
                 'wwpns': ['1000000000000000']}))

        expected_calls = [mock.call.create_initiator_group_fc(
            'openstack-abcdefghijkl'),
            mock.call.add_initiator_to_igroup_fc('openstack-abcdefghijkl',
                                                 1111111111111101)]
        self.mock_client_service.assert_has_calls(expected_calls)

    @mock.patch(NIMBLE_URLLIB2)
    @mock.patch(NIMBLE_CLIENT)
    @mock.patch.object(obj_volume.VolumeList, 'get_all_by_host',
                       mock.Mock(return_value=[]))
    @NimbleDriverBaseTestCase.client_mock_decorator(create_configuration(
        'nimble', 'nimble_pass', '10.18.108.55', 'default', '*'))
    def test_terminate_connection_positive(self):
        self.mock_client_service.get_initiator_grp_list.return_value = (
            FAKE_IGROUP_LIST_RESPONSE)
        self.driver.terminate_connection(
            {'name': 'test-volume',
             'provider_location': '12 13',
             'id': 12},
            {'initiator': 'test-initiator1'})
        expected_calls = [mock.call._get_igroupname_for_initiator(
            'test-initiator1'),
            mock.call.remove_acl({'name': 'test-volume'},
                                 'test-igrp1')]
        self.mock_client_service.assert_has_calls(
            self.mock_client_service.method_calls,
            expected_calls)

    @mock.patch(NIMBLE_URLLIB2)
    @mock.patch(NIMBLE_CLIENT)
    @mock.patch.object(obj_volume.VolumeList, 'get_all_by_host',
                       mock.Mock(return_value=[]))
    @NimbleDriverBaseTestCase.client_mock_decorator_fc(create_configuration(
        'nimble', 'nimble_pass', '10.18.108.55', 'default', '*'))
    @mock.patch(NIMBLE_FC_DRIVER + ".get_wwpns_from_array")
    def test_terminate_connection_positive_fc(self, mock_wwpns):
        mock_wwpns.return_value = ["1111111111111101"]
        self.mock_client_service.get_initiator_grp_list.return_value = (
            FAKE_IGROUP_LIST_RESPONSE_FC)
        self.driver.terminate_connection(
            {'name': 'test-volume',
             'provider_location': 'array1',
             'id': 12},
            {'initiator': 'test-initiator1',
             'wwpns': ['1000000000000000']})
        expected_calls = [
            mock.call.get_igroupname_for_initiator_fc(
                "10:00:00:00:00:00:00:00"),
            mock.call.remove_acl({'name': 'test-volume'},
                                 'test-igrp1')]
        self.mock_client_service.assert_has_calls(
            self.mock_client_service.method_calls,
            expected_calls)

    @mock.patch(NIMBLE_URLLIB2)
    @mock.patch(NIMBLE_CLIENT)
    @mock.patch.object(obj_volume.VolumeList, 'get_all_by_host',
                       mock.Mock(return_value=[]))
    @NimbleDriverBaseTestCase.client_mock_decorator(create_configuration(
        'nimble', 'nimble_pass', '10.18.108.55', 'default', '*'))
    def test_terminate_connection_negative(self):
        self.mock_client_service.get_initiator_grp_list.return_value = (
            FAKE_IGROUP_LIST_RESPONSE)
        self.assertRaises(
            exception.VolumeDriverException,
            self.driver.terminate_connection,
            {'name': 'test-volume',
             'provider_location': '12 13', 'id': 12},
            {'initiator': 'test-initiator3'})
