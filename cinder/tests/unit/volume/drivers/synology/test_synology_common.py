# Copyright (c) 2016 Synology Co., Ltd.
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

"""Tests for the Synology iSCSI volume driver."""

import copy
import json
import math
from unittest import mock

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric import rsa
import ddt
from oslo_utils import units
import requests
from six.moves import http_client
from six import string_types

from cinder import context
from cinder import exception
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder.tests.unit import test
from cinder.volume import configuration as conf
from cinder.volume.drivers.synology import synology_common as common

VOLUME_ID = fake.VOLUME_ID
TARGET_NAME_PREFIX = 'Cinder-Target-'
IP = '10.0.0.1'
IQN = 'iqn.2000-01.com.synology:' + TARGET_NAME_PREFIX + VOLUME_ID
TRG_ID = 1
CHAP_AUTH_USERNAME = 'username'
CHAP_AUTH_PASSWORD = 'password'
VOLUME = {
    '_name_id': '',
    'name': fake.VOLUME_NAME,
    'id': VOLUME_ID,
    'display_name': 'fake_volume',
    'size': 10,
    'provider_location': '%s:3260,%d %s 1' % (IP, TRG_ID, IQN),
    'provider_auth': 'CHAP %(user)s %(pass)s' % {
        'user': CHAP_AUTH_USERNAME,
        'pass': CHAP_AUTH_PASSWORD},
}
NEW_VOLUME_ID = fake.VOLUME2_ID
IQN2 = 'iqn.2000-01.com.synology:' + TARGET_NAME_PREFIX + NEW_VOLUME_ID
NEW_TRG_ID = 2
NEW_VOLUME = {
    'name': fake.VOLUME2_NAME,
    'id': NEW_VOLUME_ID,
    'display_name': 'new_fake_volume',
    'size': 10,
    'provider_location': '%s:3260,%d %s 1' % (IP, NEW_TRG_ID, IQN2),
}
SNAPSHOT_ID = fake.SNAPSHOT_ID
DS_SNAPSHOT_UUID = 'ca86a56a-40d8-4210-974c-ef15dbf01cba'
SNAPSHOT_METADATA = {
    'snap-meta1': 'value1',
    'snap-meta2': 'value2',
    'snap-meta3': 'value3',
}
SNAPSHOT = {
    'name': fake.SNAPSHOT_NAME,
    'id': SNAPSHOT_ID,
    'volume_id': VOLUME_ID,
    'volume_name': VOLUME['name'],
    'volume_size': 10,
    'display_name': 'fake_snapshot',
    'volume': VOLUME,
    'metadata': SNAPSHOT_METADATA,
}
SNAPSHOT_INFO = {
    'is_action_locked': False,
    'snapshot_id': 1,
    'status': 'Healthy',
    'uuid': DS_SNAPSHOT_UUID,
}
INITIATOR_IQN = 'iqn.1993-08.org.debian:01:604af6a341'
CONNECTOR = {
    'initiator': INITIATOR_IQN,
}
CONTEXT = {
}
LOCAL_PATH = '/dev/isda'
IMAGE_SERVICE = 'image_service'
IMAGE_ID = 1
IMAGE_META = {
    'id': IMAGE_ID
}
POOL_NAME = 'volume1'
NODE_UUID = '72003c93-2db2-4f00-a169-67c5eae86bb1'
NODE_UUID2 = '8e1e8b82-1ef9-4157-a4bf-e069355386c2'
HOST = {
    'capabilities': {
        'pool_name': 'volume2',
        'backend_info': 'Synology:iscsi:' + NODE_UUID,
    },
}
POOL_INFO = {
    'display_name': 'Volume 1',
    'raid_type': 'raid_1',
    'readonly': False,
    'fs_type': 'ext4',
    'location': 'internal',
    'eppool_used_byte': '139177984',
    'size_total_byte': '487262806016',
    'volume_id': 1,
    'size_free_byte': '486521139200',
    'container': 'internal',
    'volume_path': '/volume1',
    'single_volume': True
}
LUN_UUID = 'e1315f33-ba35-42c3-a3e7-5a06958eca30'
LUN_INFO = {
    'status': '',
    'is_action_locked': False,
    'name': VOLUME['name'],
    'extent_size': 0,
    'allocated_size': 0,
    'uuid': LUN_UUID,
    'is_mapped': True,
    'lun_id': 3,
    'location': '/volume2',
    'restored_time': 0,
    'type': 143,
    'size': 1073741824
}
FAKE_API = 'SYNO.Fake.API'
FAKE_METHOD = 'fake'
FAKE_PATH = 'fake.cgi'


class MockResponse(object):
    def __init__(self, json_data, status_code):
        self.json_data = json_data
        self.status_code = status_code

    def json(self):
        return self.json_data


class SynoSessionTestCase(test.TestCase):
    @mock.patch('requests.post', return_value=MockResponse(
        {'data': {'sid': 'sid'}, 'success': True}, http_client.OK))
    def setUp(self, _mock_post):
        super(SynoSessionTestCase, self).setUp()

        self.host = '127.0.0.1'
        self.port = 5001
        self.username = 'admin'
        self.password = 'admin'
        self.https = True
        self.ssl_verify = False
        self.one_time_pass = None
        self.device_id = None
        self.session = common.Session(self.host,
                                      self.port,
                                      self.username,
                                      self.password,
                                      self.https,
                                      self.ssl_verify,
                                      self.one_time_pass,
                                      self.device_id)
        self.session.__class__.__del__ = lambda x: x

    def test_query(self):
        out = {
            'maxVersion': 3,
            'minVersion': 1,
            'path': FAKE_PATH,
            'requestFormat': 'JSON'
        }
        data = {
            'api': 'SYNO.API.Info',
            'version': 1,
            'method': 'query',
            'query': FAKE_API
        }
        requests.post = mock.Mock(side_effect=[
            MockResponse({
                'data': {
                    FAKE_API: out
                },
                'success': True
            }, http_client.OK),
            MockResponse({
                'data': {
                    FAKE_API: out
                }
            }, http_client.OK),
        ])

        result = self.session.query(FAKE_API)
        requests.post.assert_called_once_with(
            'https://127.0.0.1:5001/webapi/query.cgi',
            data=data,
            verify=self.ssl_verify)
        self.assertDictEqual(out, result)

        result = self.session.query(FAKE_API)
        self.assertIsNone(result)

    def test__random_AES_passphrase(self):
        lengths_to_test = [0, 1, 10, 128, 501, 1024, 4096]
        for test_length in lengths_to_test:
            self.assertEqual(
                test_length,
                len(self.session._random_AES_passphrase(test_length))
            )

    def test__encrypt_RSA(self):
        # Initialize a fixed 1024 bit public/private key pair
        public_numbers = rsa.RSAPublicNumbers(
            int('10001', 16),
            int('c42eadf905d47388d84baeec2d5391ba7f91b35912933032c9c8a32d6358'
                '9cef1dfe532138adfad41fd41910cd12fbc05b8876f70aa1340fccf3227d'
                '087d1e47256c60ae49abee7c779815ec085265518791da38168a0597091d'
                '4c6ff10c0fa6616f250b85edfb4066f655695e304c0dc40c26fc11541e4c'
                '1be47771fcc1d257cccbb656015c5daed64aad7c8ae024f82531b7e637f4'
                '87530b77498d1bc7247687541fbbaa01112866da06f30185dde15131e89e'
                '27b30f07f10ddef23dd4da7bf3e216c733a4004415c9d1dd9bd5032e8b55'
                '4eb56efa9cd5cd1b416e0e55c903536787454ca3d3aba87edb70768f630c'
                'beab3781848ff5ee40edfaee57ac87c9', 16)
        )
        private_numbers = rsa.RSAPrivateNumbers(
            int('f0aa7e45ffb23ca683e1b01a9e1d77e5affaf9afa0094fb1eb89a3c8672b'
                '43ab9beb11e4ecdd2c8f88738db56be4149c55c28379480ac68a5727ba28'
                '4a47565579dbf083167a2845f5f267598febde3f7b12ba10da32ad2edff8'
                '4efd019498e0d8e03f6ddb8a5e80cdb862da9c0c921571fdb56ae7e0480a'
                'de846e328517aa23', 16),
            int('d0ae9ce41716c4bdac074423d57e540b6f48ee42d9b06bdac3b3421ea2ae'
                'e21088b3ae50acfe168edefda722dc15bc456bba76a98b8035ffa4da12dc'
                'a92bad582c935791f9a48b416f53c728fd1866c8ecf2ca00dfa667a962d3'
                'c9818cce540c5e9d2ef8843c5adfde0938ac8b5e2c592838c422ffac43ff'
                '4a4907c129de7723', 16),
            int('3733cf5e58069cefefb4f4269ee67a0619695d26fe340e86ec0299efe699'
                '83a741305421eff9fcaf7db947c8537c38fcba84debccaefeb5f5ad33b6c'
                '255c578dbb7910875a5197cccc362e4cf9567e0dfff0c98fa8bff3acb932'
                'd6545566886ccfd3df7fab92f874f9c3eceab6472ecf5ccff2945127f352'
                '8532b76d8aaadb4dbcf0e5bae8c9c8597511e0771942f12e29bbee1ceef5'
                '4a6ba97e0096354b13ae4ca22e9be1a551a1bc8db9392de6bbad99b956b5'
                'bb4b7f5094086e6eefd432066102a228bc18012cc31a7777e2e657eb115a'
                '9d718d413f2bd7a448a783c049afaaf127486b2c17feebb930e7ac8e6a07'
                'd9c843beedfa8cec52e1aba98099baa5', 16),
            int('c8ab1050e36c457ffe550f56926235d7b18d8de5af86340a413fe9edae80'
                '77933e9599bd0cf73a318feff1c7c4e74f7c2f51d9f82566beb71906ca04'
                'd0327d3d16379a6a633286241778004ec05f46581e11b64d58f28a4e9c77'
                '59bd423519e7d94dd9f58ae9ebf47013ff71124eb4fbe6a94a3c928d02e4'
                'f536ecff78d40b8b', 16),
            int('5bb873a2d8f71bf015dd77b89c4c931a1786a19a665de179dccc3c4284d4'
                '82ee2b7776256573a46c955c3d8ad7db01ce2d645e6574b81c83c96c4420'
                '1286ed00b54ee98d72813ce7bccbc0dca629847bc99188f1cb5b3372c2ca'
                '3d6620824b74c85d23d8fd1e1dff09735a22947b06d90511b63b7fceb270'
                '51b139a45007c4ab', 16),
            int('cfeff2a88112512b327999eb926a0564c431ebed2e1456f51d274e4e6d7d'
                'd75d5b26339bbca2807aa71008e9a08bd9fa0e53e3960e3b6e8c6e1a46d2'
                'b8e89b218d3b453f7ed0020504d1679374cd884ae3bb3b88b54fb429f082'
                'fa4e9d3f296c59d5d89fe16b0931dcf062bc309cf122c722c13ffb0fa0c5'
                '77d0abddcc655017', 16),
            public_numbers
        )
        private_key = private_numbers.private_key(default_backend())

        # run the _encrypt_RSA method
        original_text = 'test _encrypt_RSA'
        encrypted_text = self.session._encrypt_RSA(
            public_numbers.n,
            public_numbers.e,
            original_text
        )

        # decrypt the output using the corresponding private key
        decrypted_bytes = private_key.decrypt(
            encrypted_text,
            padding.PKCS1v15()
        )
        decrypted_text = decrypted_bytes.decode('ascii')
        self.assertEqual(original_text, decrypted_text)

    def test__encrypt_params(self):
        # setup mock
        cipherkey = 'cipherkey'
        self.session._get_enc_info = mock.Mock(return_value={
            'public_key': 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
            'cipherkey': cipherkey,
            'ciphertoken': 'ciphertoken',
            'server_time': 1111111111,
        })
        self.session._encrypt_RSA = mock.Mock(
            return_value=b'1234567890abcdef'
        )
        self.session._encrypt_AES = mock.Mock(
            return_value=b'fedcba0987654321'
        )

        # call the method
        params = {
            'account': 'account',
            'passwd': 'passwd',
            'session': 'sessionid',
            'format': 'sid'
        }
        encrypted_data = self.session._encrypt_params(params)

        # check the format of the output
        self.assertDictEqual(
            json.loads(encrypted_data[cipherkey]),
            {'rsa': 'MTIzNDU2Nzg5MGFiY2RlZg==',
             'aes': 'ZmVkY2JhMDk4NzY1NDMyMQ=='}
        )


@ddt.ddt
class SynoAPIRequestTestCase(test.TestCase):
    @mock.patch('requests.post')
    def setUp(self, _mock_post):
        super(SynoAPIRequestTestCase, self).setUp()

        self.host = '127.0.0.1'
        self.port = 5001
        self.username = 'admin'
        self.password = 'admin'
        self.https = True
        self.ssl_verify = False
        self.one_time_pass = None
        self.device_id = None
        self.request = common.APIRequest(self.host,
                                         self.port,
                                         self.username,
                                         self.password,
                                         self.https,
                                         self.ssl_verify,
                                         self.one_time_pass,
                                         self.device_id)
        self.request._APIRequest__session._sid = 'sid'
        self.request._APIRequest__session.__class__.__del__ = lambda x: x

    @mock.patch.object(common, 'Session')
    def test_new_session(self, _mock_session):
        self.device_id = 'did'
        self.request = common.APIRequest(self.host,
                                         self.port,
                                         self.username,
                                         self.password,
                                         self.https,
                                         self.ssl_verify,
                                         self.one_time_pass,
                                         self.device_id)

        result = self.request.new_session()
        self.assertIsNone(result)

    def test__start(self):
        out = {
            'maxVersion': 3,
            'minVersion': 1,
            'path': FAKE_PATH,
            'requestFormat': 'JSON'
        }
        self.request._APIRequest__session.query = mock.Mock(return_value=out)

        result = self.request._start(FAKE_API, 3)
        (self.request._APIRequest__session.query.
            assert_called_once_with(FAKE_API))
        self.assertEqual(FAKE_PATH, result)

        out.update(maxVersion=2)
        self.assertRaises(exception.APIException,
                          self.request._start,
                          FAKE_API,
                          3)

    def test__encode_param(self):
        param = {
            'api': FAKE_API,
            'method': FAKE_METHOD,
            'version': 1,
            '_sid': 'sid'
        }
        self.request._jsonFormat = True
        result = self.request._encode_param(param)
        self.assertIsInstance(result, string_types)

    def test_request(self):
        version = 1

        self.request._start = mock.Mock(return_value='fake.cgi')
        self.request._encode_param = mock.Mock(side_effect=lambda x: x)
        self.request.new_session = mock.Mock()
        requests.post = mock.Mock(side_effect=[
            MockResponse({'success': True}, http_client.OK),
            MockResponse({'error': {'code': http_client.SWITCHING_PROTOCOLS},
                          'success': False}, http_client.OK),
            MockResponse({'error': {'code': http_client.SWITCHING_PROTOCOLS}},
                         http_client.OK),
            MockResponse({}, http_client.INTERNAL_SERVER_ERROR)
        ])

        result = self.request.request(FAKE_API, FAKE_METHOD, version)
        self.assertDictEqual({'success': True}, result)

        result = self.request.request(FAKE_API, FAKE_METHOD, version)
        self.assertDictEqual(
            {'error': {'code': http_client.SWITCHING_PROTOCOLS},
             'success': False}, result)

        self.assertRaises(exception.MalformedResponse,
                          self.request.request,
                          FAKE_API,
                          FAKE_METHOD,
                          version)

        result = self.request.request(FAKE_API, FAKE_METHOD, version)
        self.assertDictEqual(
            {'http_status': http_client.INTERNAL_SERVER_ERROR}, result)

    @mock.patch.object(common.LOG, 'debug')
    @ddt.data(105, 119)
    def test_request_auth_error(self, _code, _log):
        version = 1

        self.request._start = mock.Mock(return_value='fake.cgi')
        self.request._encode_param = mock.Mock(side_effect=lambda x: x)
        self.request.new_session = mock.Mock()
        requests.post = mock.Mock(return_value=
                                  MockResponse({
                                      'error': {'code': _code},
                                      'success': False
                                  }, http_client.OK))

        self.assertRaises(common.SynoAuthError,
                          self.request.request,
                          FAKE_API,
                          FAKE_METHOD,
                          version)


class SynoCommonTestCase(test.TestCase):

    @mock.patch.object(common.SynoCommon,
                       '_get_node_uuid',
                       return_value=NODE_UUID)
    @mock.patch.object(common, 'APIRequest')
    def setUp(self, _request, _get_node_uuid):
        super(SynoCommonTestCase, self).setUp()

        self.conf = self.setup_configuration()
        self.common = common.SynoCommon(self.conf, 'iscsi')
        self.common.vendor_name = 'Synology'
        self.common.driver_type = 'iscsi'
        self.common.volume_backend_name = 'DiskStation'
        self.common.target_port = 3260

    def setup_configuration(self):
        config = mock.Mock(spec=conf.Configuration)
        config.use_chap_auth = False
        config.target_protocol = 'iscsi'
        config.target_ip_address = IP
        config.target_port = 3260
        config.synology_admin_port = 5000
        config.synology_username = 'admin'
        config.synology_password = 'admin'
        config.synology_ssl_verify = True
        config.synology_one_time_pass = '123456'
        config.synology_pool_name = POOL_NAME
        config.volume_dd_blocksize = 1
        config.target_prefix = 'iqn.2000-01.com.synology:'
        config.chap_username = 'abcd'
        config.chap_password = 'qwerty'
        config.reserved_percentage = 0
        config.max_over_subscription_ratio = 20

        return config

    @mock.patch.object(common.SynoCommon,
                       '_get_node_uuid',
                       return_value=NODE_UUID)
    @mock.patch.object(common, 'APIRequest')
    def test___init__(self, _request, _get_node_uuid):
        self.conf.safe_get = (mock.Mock(side_effect=[
            self.conf.target_ip_address,
            '',
            '']))

        self.assertRaises(exception.InvalidConfigurationValue,
                          self.common.__init__,
                          self.conf,
                          'iscsi')

        self.assertRaises(exception.InvalidConfigurationValue,
                          self.common.__init__,
                          self.conf,
                          'iscsi')

    def test__get_node_uuid(self):
        out = {
            'data': {
                'nodes': [{
                    'uuid': NODE_UUID
                }]
            },
            'success': True
        }
        self.common.exec_webapi = (
            mock.Mock(side_effect=[
                      out,
                      out,
                      common.SynoAuthError(message='dont care')]))

        result = self.common._get_node_uuid()
        (self.common.exec_webapi.
            assert_called_with('SYNO.Core.ISCSI.Node',
                               'list',
                               mock.ANY))
        self.assertEqual(NODE_UUID, result)

        del out['data']['nodes']
        self.assertRaises(exception.VolumeDriverException,
                          self.common._get_node_uuid)

        self.assertRaises(common.SynoAuthError,
                          self.common._get_node_uuid)

    def test__get_pool_info(self):
        out = {
            'data': {
                'volume': POOL_INFO
            },
            'success': True
        }
        self.common.exec_webapi = (
            mock.Mock(side_effect=[
                      out,
                      out,
                      common.SynoAuthError(message='dont care')]))
        result = self.common._get_pool_info()
        (self.common.exec_webapi.
            assert_called_with('SYNO.Core.Storage.Volume',
                               'get',
                               mock.ANY,
                               volume_path='/' + POOL_NAME))
        self.assertDictEqual(POOL_INFO, result)

        del out['data']['volume']
        self.assertRaises(exception.MalformedResponse,
                          self.common._get_pool_info)

        self.assertRaises(common.SynoAuthError,
                          self.common._get_pool_info)

        self.conf.synology_pool_name = ''
        self.assertRaises(exception.InvalidConfigurationValue,
                          self.common._get_pool_info)

    def test__get_pool_size(self):
        pool_info = copy.deepcopy(POOL_INFO)
        self.common._get_pool_info = mock.Mock(return_value=pool_info)

        result = self.common._get_pool_size()

        self.assertEqual((int(int(POOL_INFO['size_free_byte']) / units.Gi),
                          int(int(POOL_INFO['size_total_byte']) / units.Gi),
                          math.ceil((float(POOL_INFO['size_total_byte']) -
                                     float(POOL_INFO['size_free_byte']) -
                                     float(POOL_INFO['eppool_used_byte'])) /
                                    units.Gi)),
                         result)

        del pool_info['size_free_byte']
        self.assertRaises(exception.MalformedResponse,
                          self.common._get_pool_size)

    def test__get_pool_lun_provisioned_size(self):
        out = {
            'data': {
                'luns': [{
                    'lun_id': 1,
                    'location': '/' + POOL_NAME,
                    'size': 5368709120
                }, {
                    'lun_id': 2,
                    'location': '/' + POOL_NAME,
                    'size': 3221225472
                }]
            },
            'success': True
        }
        self.common.exec_webapi = mock.Mock(return_value=out)

        result = self.common._get_pool_lun_provisioned_size()
        (self.common.exec_webapi.
            assert_called_with('SYNO.Core.ISCSI.LUN',
                               'list',
                               mock.ANY,
                               location='/' + POOL_NAME))
        self.assertEqual(int(math.ceil(float(5368709120 + 3221225472) /
                             units.Gi)),
                         result)

    def test__get_pool_lun_provisioned_size_error(self):
        out = {
            'data': {},
            'success': True
        }
        self.common.exec_webapi = mock.Mock(return_value=out)

        self.assertRaises(exception.MalformedResponse,
                          self.common._get_pool_lun_provisioned_size)

        self.conf.synology_pool_name = ''
        self.assertRaises(exception.InvalidConfigurationValue,
                          self.common._get_pool_lun_provisioned_size)

    def test__get_lun_info(self):
        out = {
            'data': {
                'lun': LUN_INFO
            },
            'success': True
        }
        self.common.exec_webapi = (
            mock.Mock(side_effect=[
                      out,
                      out,
                      common.SynoAuthError(message='dont care')]))
        result = self.common._get_lun_info(VOLUME['name'],
                                           ['is_mapped'])
        (self.common.exec_webapi.
            assert_called_with('SYNO.Core.ISCSI.LUN',
                               'get',
                               mock.ANY,
                               uuid=VOLUME['name'],
                               additional=['is_mapped']))
        self.assertDictEqual(LUN_INFO, result)

        del out['data']['lun']
        self.assertRaises(exception.MalformedResponse,
                          self.common._get_lun_info,
                          VOLUME['name'])

        self.assertRaises(common.SynoAuthError,
                          self.common._get_lun_info,
                          VOLUME['name'])

        self.assertRaises(exception.InvalidParameterValue,
                          self.common._get_lun_info,
                          '')

    def test__get_lun_uuid(self):
        lun_info = copy.deepcopy(LUN_INFO)
        self.common._get_lun_info = (
            mock.Mock(side_effect=[
                      lun_info,
                      lun_info,
                      common.SynoAuthError(message='dont care')]))

        result = self.common._get_lun_uuid(VOLUME['name'])
        self.assertEqual(LUN_UUID, result)

        del lun_info['uuid']
        self.assertRaises(exception.MalformedResponse,
                          self.common._get_lun_uuid,
                          VOLUME['name'])

        self.assertRaises(common.SynoAuthError,
                          self.common._get_lun_uuid,
                          VOLUME['name'])

        self.assertRaises(exception.InvalidParameterValue,
                          self.common._get_lun_uuid,
                          '')

    def test__get_lun_status(self):
        lun_info = copy.deepcopy(LUN_INFO)
        self.common._get_lun_info = (
            mock.Mock(side_effect=[
                      lun_info,
                      lun_info,
                      lun_info,
                      common.SynoAuthError(message='dont care')]))

        result = self.common._get_lun_status(VOLUME['name'])
        self.assertEqual((lun_info['status'], lun_info['is_action_locked']),
                         result)

        del lun_info['is_action_locked']
        self.assertRaises(exception.MalformedResponse,
                          self.common._get_lun_status,
                          VOLUME['name'])

        del lun_info['status']
        self.assertRaises(exception.MalformedResponse,
                          self.common._get_lun_status,
                          VOLUME['name'])

        self.assertRaises(common.SynoAuthError,
                          self.common._get_lun_status,
                          VOLUME['name'])

        self.assertRaises(exception.InvalidParameterValue,
                          self.common._get_lun_status,
                          '')

    def test__get_snapshot_info(self):
        out = {
            'data': {
                'snapshot': SNAPSHOT_INFO
            },
            'success': True
        }
        self.common.exec_webapi = (
            mock.Mock(side_effect=[
                      out,
                      out,
                      common.SynoAuthError(message='dont care')]))
        result = self.common._get_snapshot_info(DS_SNAPSHOT_UUID,
                                                additional=['status'])
        (self.common.exec_webapi.
            assert_called_with('SYNO.Core.ISCSI.LUN',
                               'get_snapshot',
                               mock.ANY,
                               snapshot_uuid=DS_SNAPSHOT_UUID,
                               additional=['status']))
        self.assertDictEqual(SNAPSHOT_INFO, result)

        del out['data']['snapshot']
        self.assertRaises(exception.MalformedResponse,
                          self.common._get_snapshot_info,
                          DS_SNAPSHOT_UUID)

        self.assertRaises(common.SynoAuthError,
                          self.common._get_snapshot_info,
                          DS_SNAPSHOT_UUID)

        self.assertRaises(exception.InvalidParameterValue,
                          self.common._get_snapshot_info,
                          '')

    def test__get_snapshot_status(self):
        snapshot_info = copy.deepcopy(SNAPSHOT_INFO)
        self.common._get_snapshot_info = (
            mock.Mock(side_effect=[
                      snapshot_info,
                      snapshot_info,
                      snapshot_info,
                      common.SynoAuthError(message='dont care')]))

        result = self.common._get_snapshot_status(DS_SNAPSHOT_UUID)
        self.assertEqual((snapshot_info['status'],
                          snapshot_info['is_action_locked']),
                         result)

        del snapshot_info['is_action_locked']
        self.assertRaises(exception.MalformedResponse,
                          self.common._get_snapshot_status,
                          DS_SNAPSHOT_UUID)

        del snapshot_info['status']
        self.assertRaises(exception.MalformedResponse,
                          self.common._get_snapshot_status,
                          DS_SNAPSHOT_UUID)

        self.assertRaises(common.SynoAuthError,
                          self.common._get_snapshot_status,
                          DS_SNAPSHOT_UUID)

        self.assertRaises(exception.InvalidParameterValue,
                          self.common._get_snapshot_status,
                          '')

    def test__get_metadata_value(self):
        ctxt = context.get_admin_context()
        fake_vol_obj = fake_volume.fake_volume_obj(ctxt)
        self.assertRaises(exception.VolumeMetadataNotFound,
                          self.common._get_metadata_value,
                          fake_vol_obj,
                          'no_such_key')

        fake_snap_obj = (fake_snapshot.
                         fake_snapshot_obj(ctxt,
                                           expected_attrs=['metadata']))
        self.assertRaises(exception.SnapshotMetadataNotFound,
                          self.common._get_metadata_value,
                          fake_snap_obj,
                          'no_such_key')

        meta = {'snapshot_metadata': [{'key': 'ds_snapshot_UUID',
                                       'value': DS_SNAPSHOT_UUID}],
                'expected_attrs': ['metadata']}

        fake_snap_obj = fake_snapshot.fake_snapshot_obj(ctxt,
                                                        **meta)
        result = self.common._get_metadata_value(fake_snap_obj,
                                                 'ds_snapshot_UUID')
        self.assertEqual(DS_SNAPSHOT_UUID, result)

        self.assertRaises(exception.MetadataAbsent,
                          self.common._get_metadata_value,
                          SNAPSHOT,
                          'no_such_key')

    def test__target_create_with_chap_auth(self):
        out = {
            'data': {
                'target_id': TRG_ID
            },
            'success': True
        }
        trg_name = self.common.TARGET_NAME_PREFIX + VOLUME['id']
        iqn = self.conf.target_prefix + trg_name
        self.conf.use_chap_auth = True
        self.common.exec_webapi = mock.Mock(return_value=out)
        self.conf.safe_get = (
            mock.Mock(side_effect=[
                      self.conf.use_chap_auth,
                      'abcd',
                      'qwerty',
                      self.conf.target_prefix]))
        result = self.common._target_create(VOLUME['id'])
        (self.common.exec_webapi.
            assert_called_with('SYNO.Core.ISCSI.Target',
                               'create',
                               mock.ANY,
                               name=trg_name,
                               iqn=iqn,
                               auth_type=1,
                               user='abcd',
                               password='qwerty',
                               max_sessions=0))
        self.assertEqual((IQN, TRG_ID, 'CHAP abcd qwerty'), result)

    def test__target_create_without_chap_auth(self):
        out = {
            'data': {
                'target_id': TRG_ID
            },
            'success': True
        }
        trg_name = self.common.TARGET_NAME_PREFIX + VOLUME['id']
        iqn = self.conf.target_prefix + trg_name
        self.common.exec_webapi = mock.Mock(return_value=out)
        self.conf.safe_get = (
            mock.Mock(side_effect=[
                      self.conf.use_chap_auth,
                      self.conf.target_prefix]))
        result = self.common._target_create(VOLUME['id'])
        (self.common.exec_webapi.
            assert_called_with('SYNO.Core.ISCSI.Target',
                               'create',
                               mock.ANY,
                               name=trg_name,
                               iqn=iqn,
                               auth_type=0,
                               user='',
                               password='',
                               max_sessions=0))
        self.assertEqual((IQN, TRG_ID, ''), result)

    def test__target_create_error(self):
        out = {
            'data': {
            },
            'success': True
        }
        self.common.exec_webapi = (
            mock.Mock(side_effect=[
                      out,
                      common.SynoAuthError(message='dont care')]))
        self.conf.safe_get = (
            mock.Mock(side_effect=[
                      self.conf.use_chap_auth,
                      self.conf.target_prefix,
                      self.conf.use_chap_auth,
                      self.conf.target_prefix]))

        self.assertRaises(exception.VolumeDriverException,
                          self.common._target_create,
                          VOLUME['id'])

        self.assertRaises(common.SynoAuthError,
                          self.common._target_create,
                          VOLUME['id'])

        self.assertRaises(exception.InvalidParameterValue,
                          self.common._target_create,
                          '')

    def test__target_delete(self):
        out = {
            'success': True
        }
        self.common.exec_webapi = (
            mock.Mock(side_effect=[
                      out,
                      common.SynoAuthError(message='dont care')]))

        result = self.common._target_delete(TRG_ID)
        (self.common.exec_webapi.
            assert_called_with('SYNO.Core.ISCSI.Target',
                               'delete',
                               mock.ANY,
                               target_id=str(TRG_ID)))
        self.assertIsNone(result)

        self.assertRaises(common.SynoAuthError,
                          self.common._target_delete,
                          TRG_ID)

        self.assertRaises(exception.InvalidParameterValue,
                          self.common._target_delete,
                          -1)

    def test__lun_map_unmap_target(self):
        out = {
            'success': True
        }
        self.common.exec_webapi = (
            mock.Mock(side_effect=[
                      out,
                      out,
                      common.SynoAuthError(message='dont care')]))
        self.common._get_lun_uuid = mock.Mock(return_value=LUN_UUID)

        result = self.common._lun_map_unmap_target(VOLUME['name'],
                                                   True,
                                                   TRG_ID)
        self.common._get_lun_uuid.assert_called_with(VOLUME['name'])
        (self.common.exec_webapi.
            assert_called_with('SYNO.Core.ISCSI.LUN',
                               'map_target',
                               mock.ANY,
                               uuid=LUN_UUID,
                               target_ids=[str(TRG_ID)]))
        self.assertIsNone(result)

        result = self.common._lun_map_unmap_target(VOLUME['name'],
                                                   False,
                                                   TRG_ID)
        (self.common.exec_webapi.
            assert_called_with('SYNO.Core.ISCSI.LUN',
                               'unmap_target',
                               mock.ANY,
                               uuid=LUN_UUID,
                               target_ids=[str(TRG_ID)]))
        self.assertIsNone(result)

        self.assertRaises(common.SynoAuthError,
                          self.common._lun_map_unmap_target,
                          VOLUME['name'],
                          True,
                          TRG_ID)

        self.assertRaises(exception.InvalidParameterValue,
                          self.common._lun_map_unmap_target,
                          mock.ANY,
                          mock.ANY,
                          -1)

    def test__lun_map_target(self):
        self.common._lun_map_unmap_target = mock.Mock()

        result = self.common._lun_map_target(VOLUME, TRG_ID)

        self.common._lun_map_unmap_target.assert_called_with(VOLUME,
                                                             True,
                                                             TRG_ID)
        self.assertIsNone(result)

    def test__lun_ummap_target(self):
        self.common._lun_map_unmap_target = mock.Mock()

        result = self.common._lun_unmap_target(VOLUME, TRG_ID)

        self.common._lun_map_unmap_target.assert_called_with(VOLUME,
                                                             False,
                                                             TRG_ID)
        self.assertIsNone(result)

    def test__modify_lun_name(self):
        out = {
            'success': True
        }
        self.common.exec_webapi = (
            mock.Mock(side_effect=[
                      out,
                      common.SynoAuthError(message='dont care')]))

        result = self.common._modify_lun_name(VOLUME['name'],
                                              NEW_VOLUME['name'])
        self.assertIsNone(result)

        self.assertRaises(common.SynoAuthError,
                          self.common._modify_lun_name,
                          VOLUME['name'],
                          NEW_VOLUME['name'])

    @mock.patch('eventlet.sleep')
    def test__check_lun_status_normal(self, _patched_sleep):
        self.common._get_lun_status = (
            mock.Mock(side_effect=[
                      ('normal', True),
                      ('normal', False),
                      ('cloning', False),
                      common.SynoLUNNotExist(message='dont care')]))

        result = self.common._check_lun_status_normal(VOLUME['name'])
        self.assertEqual(1, _patched_sleep.call_count)
        self.assertEqual([mock.call(2)], _patched_sleep.call_args_list)
        self.common._get_lun_status.assert_called_with(VOLUME['name'])
        self.assertTrue(result)

        result = self.common._check_lun_status_normal(VOLUME['name'])
        self.assertFalse(result)

        self.assertRaises(common.SynoLUNNotExist,
                          self.common._check_lun_status_normal,
                          VOLUME['name'])

    @mock.patch('eventlet.sleep')
    def test__check_snapshot_status_healthy(self, _patched_sleep):
        self.common._get_snapshot_status = (
            mock.Mock(side_effect=[
                      ('Healthy', True),
                      ('Healthy', False),
                      ('Unhealthy', False),
                      common.SynoLUNNotExist(message='dont care')]))

        result = self.common._check_snapshot_status_healthy(DS_SNAPSHOT_UUID)
        self.assertEqual(1, _patched_sleep.call_count)
        self.assertEqual([mock.call(2)], _patched_sleep.call_args_list)
        self.common._get_snapshot_status.assert_called_with(DS_SNAPSHOT_UUID)
        self.assertTrue(result)

        result = self.common._check_snapshot_status_healthy(DS_SNAPSHOT_UUID)
        self.assertFalse(result)

        self.assertRaises(common.SynoLUNNotExist,
                          self.common._check_snapshot_status_healthy,
                          DS_SNAPSHOT_UUID)

    def test__check_storage_response(self):
        out = {
            'success': False
        }
        result = self.common._check_storage_response(out)
        self.assertEqual('Internal error', result[0])
        self.assertIsInstance(result[1],
                              (exception.VolumeBackendAPIException))

    def test__check_iscsi_response(self):
        out = {
            'success': False,
            'error': {
            }
        }
        self.assertRaises(exception.MalformedResponse,
                          self.common._check_iscsi_response,
                          out)

        out['error'].update(code=18990505)
        result = self.common._check_iscsi_response(out, uuid=LUN_UUID)
        self.assertEqual('Bad LUN UUID [18990505]', result[0])
        self.assertIsInstance(result[1],
                              (common.SynoLUNNotExist))

        out['error'].update(code=18990532)
        result = self.common._check_iscsi_response(out,
                                                   snapshot_id=SNAPSHOT_ID)
        self.assertEqual('No such snapshot [18990532]', result[0])
        self.assertIsInstance(result[1],
                              (exception.SnapshotNotFound))

        out['error'].update(code=12345678)
        result = self.common._check_iscsi_response(out, uuid=LUN_UUID)
        self.assertEqual('Internal error [12345678]', result[0])
        self.assertIsInstance(result[1],
                              (exception.VolumeBackendAPIException))

    def test__check_ds_pool_status(self):
        info = copy.deepcopy(POOL_INFO)
        self.common._get_pool_info = mock.Mock(return_value=info)

        result = self.common._check_ds_pool_status()
        self.assertIsNone(result)

        info['readonly'] = True
        self.assertRaises(exception.VolumeDriverException,
                          self.common._check_ds_pool_status)

        del info['readonly']
        self.assertRaises(exception.MalformedResponse,
                          self.common._check_ds_pool_status)

    def test__check_ds_version(self):
        ver1 = 'DSM 6.1-9999'
        ver2 = 'DSM UC 1.0-9999 Update 2'
        ver3 = 'DSM 6.0.1-9999 Update 2'
        ver4 = 'DSM 6.0-9999 Update 2'
        ver5 = 'DSM 5.2-9999'
        out = {
            'data': {
            },
            'success': True
        }
        self.common.exec_webapi = mock.Mock(return_value=out)
        self.assertRaises(exception.MalformedResponse,
                          self.common._check_ds_version)
        (self.common.exec_webapi.
            assert_called_with('SYNO.Core.System',
                               'info',
                               mock.ANY,
                               type='firmware'))

        out['data'].update(firmware_ver=ver1)
        result = self.common._check_ds_version()
        self.assertIsNone(result)

        out['data'].update(firmware_ver=ver2)
        result = self.common._check_ds_version()
        self.assertIsNone(result)

        out['data'].update(firmware_ver=ver3)
        self.assertRaises(exception.VolumeDriverException,
                          self.common._check_ds_version)

        out['data'].update(firmware_ver=ver4)
        self.assertRaises(exception.VolumeDriverException,
                          self.common._check_ds_version)

        out['data'].update(firmware_ver=ver5)
        self.assertRaises(exception.VolumeDriverException,
                          self.common._check_ds_version)

        self.common.exec_webapi = (
            mock.Mock(side_effect=
                      common.SynoAuthError(message='dont care')))
        self.assertRaises(common.SynoAuthError,
                          self.common._check_ds_version)

    def test__check_ds_ability(self):
        out = {
            'data': {
                'support_storage_mgr': 'yes',
                'support_iscsi_target': 'yes',
                'support_vaai': 'yes',
                'supportsnapshot': 'yes',
            },
            'success': True
        }
        self.common.exec_webapi = mock.Mock(return_value=out)
        result = self.common._check_ds_ability()
        self.assertIsNone(result)
        (self.common.exec_webapi.
            assert_called_with('SYNO.Core.System',
                               'info',
                               mock.ANY,
                               type='define'))

        out['data'].update(supportsnapshot='no')
        self.assertRaises(exception.VolumeDriverException,
                          self.common._check_ds_ability)

        out['data'].update(support_vaai='no')
        self.assertRaises(exception.VolumeDriverException,
                          self.common._check_ds_ability)

        out['data'].update(support_iscsi_target='no')
        self.assertRaises(exception.VolumeDriverException,
                          self.common._check_ds_ability)

        out['data'].update(support_storage_mgr='no')
        self.assertRaises(exception.VolumeDriverException,
                          self.common._check_ds_ability)

        out['data'].update(usbstation='yes')
        self.assertRaises(exception.VolumeDriverException,
                          self.common._check_ds_ability)

        del out['data']
        self.assertRaises(exception.MalformedResponse,
                          self.common._check_ds_ability)

        self.common.exec_webapi = (
            mock.Mock(side_effect=
                      common.SynoAuthError(message='dont care')))
        self.assertRaises(common.SynoAuthError,
                          self.common._check_ds_ability)

    @mock.patch.object(common.LOG, 'exception')
    def test_check_response(self, _logexc):
        out = {
            'success': True
        }
        bad_out1 = {
            'api_info': {
                'api': 'SYNO.Core.ISCSI.LUN',
                'method': 'create',
                'version': 1
            },
            'success': False
        }
        bad_out2 = {
            'api_info': {
                'api': 'SYNO.Core.Storage.Volume',
                'method': 'get',
                'version': 1
            },
            'success': False
        }
        bad_out3 = {
            'api_info': {
                'api': 'SYNO.Core.System',
                'method': 'info',
                'version': 1
            },
            'success': False
        }
        self.common._check_iscsi_response = (
            mock.Mock(return_value=
                      ('Bad LUN UUID',
                       common.SynoLUNNotExist(message='dont care'))))
        self.common._check_storage_response = (
            mock.Mock(return_value=
                      ('Internal error',
                       exception.
                       VolumeBackendAPIException(message='dont care'))))

        result = self.common.check_response(out)
        self.assertEqual(0, _logexc.call_count)
        self.assertIsNone(result)

        self.assertRaises(common.SynoLUNNotExist,
                          self.common.check_response,
                          bad_out1)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.common.check_response,
                          bad_out2)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.common.check_response,
                          bad_out3)

    def test_exec_webapi(self):
        api = 'SYNO.Fake.WebAPI'
        method = 'fake'
        version = 1
        resp = {}
        bad_resp = {
            'http_status': http_client.INTERNAL_SERVER_ERROR
        }
        expected = copy.deepcopy(resp)
        expected.update(api_info={'api': api,
                                  'method': method,
                                  'version': version})
        self.common.synoexec = mock.Mock(side_effect=[resp, bad_resp])

        result = self.common.exec_webapi(api,
                                         method,
                                         version,
                                         param1='value1',
                                         param2='value2')

        self.common.synoexec.assert_called_once_with(api,
                                                     method,
                                                     version,
                                                     param1='value1',
                                                     param2='value2')
        self.assertDictEqual(expected, result)

        self.assertRaises(common.SynoAPIHTTPError,
                          self.common.exec_webapi,
                          api,
                          method,
                          version,
                          param1='value1',
                          param2='value2')

    def test_get_ip(self):
        result = self.common.get_ip()
        self.assertEqual(self.conf.target_ip_address, result)

    def test_get_provider_location(self):
        self.common.get_ip = (
            mock.Mock(return_value=self.conf.target_ip_address))
        self.conf.safe_get = (
            mock.Mock(return_value=['10.0.0.2', '10.0.0.3']))
        expected = ('10.0.0.1:3260;10.0.0.2:3260;10.0.0.3:3260' +
                    ',%(tid)d %(iqn)s 0') % {'tid': TRG_ID, 'iqn': IQN}

        result = self.common.get_provider_location(IQN, TRG_ID)

        self.assertEqual(expected, result)

    def test_is_lun_mapped(self):
        bad_lun_info = copy.deepcopy(LUN_INFO)
        del bad_lun_info['is_mapped']
        self.common._get_lun_info = (
            mock.Mock(side_effect=[
                      LUN_INFO,
                      common.SynoAuthError(message='dont care'),
                      bad_lun_info]))

        result = self.common.is_lun_mapped(VOLUME['name'])
        self.assertEqual(LUN_INFO['is_mapped'], result)

        self.assertRaises(common.SynoAuthError,
                          self.common.is_lun_mapped,
                          VOLUME['name'])

        self.assertRaises(exception.MalformedResponse,
                          self.common.is_lun_mapped,
                          VOLUME['name'])

        self.assertRaises(exception.InvalidParameterValue,
                          self.common.is_lun_mapped,
                          '')

    def test_check_for_setup_error(self):
        self.common._check_ds_pool_status = mock.Mock()
        self.common._check_ds_version = mock.Mock()
        self.common._check_ds_ability = mock.Mock()

        result = self.common.check_for_setup_error()

        self.common._check_ds_pool_status.assert_called_once_with()
        self.common._check_ds_version.assert_called_once_with()
        self.common._check_ds_ability.assert_called_once_with()
        self.assertIsNone(result)

    def test_update_volume_stats(self):
        self.common._get_pool_size = mock.Mock(return_value=(10, 100, 50))
        self.common._get_pool_lun_provisioned_size = (
            mock.Mock(return_value=300))

        data = {
            'volume_backend_name': 'DiskStation',
            'vendor_name': 'Synology',
            'storage_protocol': 'iscsi',
            'consistencygroup_support': False,
            'QoS_support': False,
            'thin_provisioning_support': True,
            'thick_provisioning_support': False,
            'reserved_percentage': 0,
            'free_capacity_gb': 10,
            'total_capacity_gb': 100,
            'provisioned_capacity_gb': 350,
            'max_over_subscription_ratio': 20,
            'target_ip_address': '10.0.0.1',
            'pool_name': 'volume1',
            'backend_info':
                'Synology:iscsi:72003c93-2db2-4f00-a169-67c5eae86bb1'
        }

        result = self.common.update_volume_stats()

        self.assertDictEqual(data, result)

    def test_create_volume(self):
        out = {
            'success': True
        }
        self.common.exec_webapi = (
            mock.Mock(side_effect=[
                      out,
                      out,
                      common.SynoAuthError(message='dont care')]))
        self.common._check_lun_status_normal = (
            mock.Mock(side_effect=[True, False, True]))

        result = self.common.create_volume(VOLUME)
        (self.common.exec_webapi.
            assert_called_with('SYNO.Core.ISCSI.LUN',
                               'create',
                               mock.ANY,
                               name=VOLUME['name'],
                               type=self.common.CINDER_LUN,
                               location='/' + self.conf.synology_pool_name,
                               size=VOLUME['size'] * units.Gi))
        self.assertIsNone(result)

        self.assertRaises(exception.VolumeDriverException,
                          self.common.create_volume,
                          VOLUME)

        self.assertRaises(common.SynoAuthError,
                          self.common.create_volume,
                          VOLUME)

    def test_delete_volume(self):
        out = {
            'success': True
        }
        self.common._get_lun_uuid = mock.Mock(return_value=LUN_UUID)
        self.common.exec_webapi = (
            mock.Mock(side_effect=[
                      out,
                      common.SynoLUNNotExist(message='dont care'),
                      common.SynoAuthError(message='dont care')]))

        result = self.common.delete_volume(VOLUME)
        self.common._get_lun_uuid.assert_called_with(VOLUME['name'])
        (self.common.exec_webapi.
            assert_called_with('SYNO.Core.ISCSI.LUN',
                               'delete',
                               mock.ANY,
                               uuid=LUN_UUID))
        self.assertIsNone(result)

        result = self.common.delete_volume(VOLUME)
        self.assertIsNone(result)

        self.assertRaises(common.SynoAuthError,
                          self.common.delete_volume,
                          VOLUME)

    def test_create_cloned_volume(self):
        out = {
            'success': True
        }
        new_volume = copy.deepcopy(NEW_VOLUME)
        new_volume['size'] = 20
        self.common.exec_webapi = mock.Mock(return_value=out)
        self.common._get_lun_uuid = (
            mock.Mock(side_effect=[
                      LUN_UUID,
                      LUN_UUID,
                      LUN_UUID,
                      exception.InvalidParameterValue('dont care')]))
        self.common.extend_volume = mock.Mock()
        self.common._check_lun_status_normal = (
            mock.Mock(side_effect=[True, True, False, False]))
        result = self.common.create_cloned_volume(new_volume, VOLUME)
        self.common._get_lun_uuid.assert_called_with(VOLUME['name'])
        (self.common.exec_webapi.
            assert_called_with('SYNO.Core.ISCSI.LUN',
                               'clone',
                               mock.ANY,
                               src_lun_uuid=LUN_UUID,
                               dst_lun_name=new_volume['name'],
                               is_same_pool=True,
                               clone_type='CINDER'))
        (self.common._check_lun_status_normal.
            assert_called_with(new_volume['name']))
        self.common.extend_volume.assert_called_once_with(new_volume,
                                                          new_volume['size'])
        self.assertIsNone(result)

        new_volume['size'] = 10
        result = self.common.create_cloned_volume(new_volume, VOLUME)
        self.assertIsNone(result)

        self.assertRaises(exception.VolumeDriverException,
                          self.common.create_cloned_volume,
                          new_volume,
                          VOLUME)

        self.assertRaises(exception.InvalidParameterValue,
                          self.common.create_cloned_volume,
                          new_volume,
                          VOLUME)

    def test_extend_volume(self):
        new_size = 20
        out = {
            'success': True
        }
        self.common.exec_webapi = mock.Mock(return_value=out)
        self.common._get_lun_uuid = (
            mock.Mock(side_effect=[
                      LUN_UUID,
                      exception.InvalidParameterValue('dont care')]))

        result = self.common.extend_volume(VOLUME, new_size)

        (self.common.exec_webapi.
            assert_called_with('SYNO.Core.ISCSI.LUN',
                               'set',
                               mock.ANY,
                               uuid=LUN_UUID,
                               new_size=new_size * units.Gi))
        self.assertIsNone(result)
        self.assertRaises(exception.ExtendVolumeError,
                          self.common.extend_volume,
                          VOLUME,
                          new_size)

    def test_update_migrated_volume(self):
        expected = {
            '_name_id': None
        }
        self.common._modify_lun_name = mock.Mock(side_effect=[None, Exception])

        result = self.common.update_migrated_volume(VOLUME,
                                                    NEW_VOLUME)

        self.common._modify_lun_name.assert_called_with(NEW_VOLUME['name'],
                                                        VOLUME['name'])
        self.assertDictEqual(expected, result)

        self.assertRaises(exception.VolumeMigrationFailed,
                          self.common.update_migrated_volume,
                          VOLUME,
                          NEW_VOLUME)

    def test_create_snapshot(self):
        expected_result = {
            'metadata': {
                self.common.METADATA_DS_SNAPSHOT_UUID: DS_SNAPSHOT_UUID
            }
        }
        expected_result['metadata'].update(SNAPSHOT['metadata'])

        out = {
            'data': {
                'snapshot_uuid': DS_SNAPSHOT_UUID,
                'snapshot_id': SNAPSHOT_ID
            },
            'success': True
        }
        self.common.exec_webapi = mock.Mock(return_value=out)
        self.common._check_snapshot_status_healthy = (
            mock.Mock(side_effect=[True, False]))

        result = self.common.create_snapshot(SNAPSHOT)

        (self.common.exec_webapi.
            assert_called_with('SYNO.Core.ISCSI.LUN',
                               'take_snapshot',
                               mock.ANY,
                               src_lun_uuid=SNAPSHOT['volume']['name'],
                               is_app_consistent=False,
                               is_locked=False,
                               taken_by='Cinder',
                               description='(Cinder) ' +
                               SNAPSHOT['id']))
        self.assertDictEqual(expected_result, result)

        self.assertRaises(exception.VolumeDriverException,
                          self.common.create_snapshot,
                          SNAPSHOT)

    def test_create_snapshot_error(self):
        out = {
            'data': {
                'snapshot_uuid': 1,
                'snapshot_id': SNAPSHOT_ID
            },
            'success': True
        }
        self.common.exec_webapi = mock.Mock(return_value=out)

        self.assertRaises(exception.MalformedResponse,
                          self.common.create_snapshot,
                          SNAPSHOT)

        self.common.exec_webapi = (
            mock.Mock(side_effect=common.SynoAuthError(reason='dont care')))

        self.assertRaises(common.SynoAuthError,
                          self.common.create_snapshot,
                          SNAPSHOT)

    def test_delete_snapshot(self):
        out = {
            'success': True
        }
        self.common.exec_webapi = mock.Mock(return_value=out)
        self.common._get_metadata_value = (
            mock.Mock(side_effect=[
                      DS_SNAPSHOT_UUID,
                      exception.SnapshotMetadataNotFound(message='dont care'),
                      exception.MetadataAbsent]))

        result = self.common.delete_snapshot(SNAPSHOT)
        (self.common._get_metadata_value.
            assert_called_with(SNAPSHOT,
                               self.common.METADATA_DS_SNAPSHOT_UUID))
        (self.common.exec_webapi.
            assert_called_with('SYNO.Core.ISCSI.LUN',
                               'delete_snapshot',
                               mock.ANY,
                               snapshot_uuid=DS_SNAPSHOT_UUID,
                               deleted_by='Cinder'))
        self.assertIsNone(result)

        result = self.common.delete_snapshot(SNAPSHOT)
        self.assertIsNone(result)

        self.assertRaises(exception.MetadataAbsent,
                          self.common.delete_snapshot,
                          SNAPSHOT)

    def test_create_volume_from_snapshot(self):
        out = {
            'success': True
        }
        new_volume = copy.deepcopy(NEW_VOLUME)
        new_volume['size'] = 20
        self.common.exec_webapi = mock.Mock(return_value=out)
        self.common._get_metadata_value = (
            mock.Mock(side_effect=[
                      DS_SNAPSHOT_UUID,
                      DS_SNAPSHOT_UUID,
                      exception.SnapshotMetadataNotFound(message='dont care'),
                      common.SynoAuthError(message='dont care')]))
        self.common._check_lun_status_normal = (
            mock.Mock(side_effect=[True, False, True, True]))
        self.common.extend_volume = mock.Mock()

        result = self.common.create_volume_from_snapshot(new_volume, SNAPSHOT)

        (self.common._get_metadata_value.
            assert_called_with(SNAPSHOT,
                               self.common.METADATA_DS_SNAPSHOT_UUID))
        (self.common.exec_webapi.
            assert_called_with('SYNO.Core.ISCSI.LUN',
                               'clone_snapshot',
                               mock.ANY,
                               src_lun_uuid=SNAPSHOT['volume']['name'],
                               snapshot_uuid=DS_SNAPSHOT_UUID,
                               cloned_lun_name=new_volume['name'],
                               clone_type='CINDER'))
        self.common.extend_volume.assert_called_once_with(new_volume,
                                                          new_volume['size'])
        self.assertIsNone(result)

        self.assertRaises(exception.VolumeDriverException,
                          self.common.create_volume_from_snapshot,
                          new_volume,
                          SNAPSHOT)

        self.assertRaises(exception.SnapshotMetadataNotFound,
                          self.common.create_volume_from_snapshot,
                          new_volume,
                          SNAPSHOT)

        self.assertRaises(common.SynoAuthError,
                          self.common.create_volume_from_snapshot,
                          new_volume,
                          SNAPSHOT)

    def test_get_iqn_and_trgid(self):
        location = '%s:3260,%d %s 1' % (IP, 1, IQN)

        result = self.common.get_iqn_and_trgid(location)

        self.assertEqual((IQN, 1), result)

        location = ''
        self.assertRaises(exception.InvalidParameterValue,
                          self.common.get_iqn_and_trgid,
                          location)

        location = 'BADINPUT'
        self.assertRaises(exception.InvalidInput,
                          self.common.get_iqn_and_trgid,
                          location)

        location = '%s:3260 %s 1' % (IP, IQN)
        self.assertRaises(exception.InvalidInput,
                          self.common.get_iqn_and_trgid,
                          location)

    def test_get_iscsi_properties(self):
        volume = copy.deepcopy(VOLUME)
        iscsi_properties = {
            'target_discovered': False,
            'target_iqn': IQN,
            'target_portal': '%s:3260' % IP,
            'volume_id': VOLUME['id'],
            'access_mode': 'rw',
            'discard': False,
            'auth_method': 'CHAP',
            'auth_username': CHAP_AUTH_USERNAME,
            'auth_password': CHAP_AUTH_PASSWORD
        }
        self.common.get_ip = mock.Mock(return_value=IP)
        self.conf.safe_get = mock.Mock(return_value=[])

        result = self.common.get_iscsi_properties(volume)
        self.assertDictEqual(iscsi_properties, result)

        volume['provider_location'] = ''
        self.assertRaises(exception.InvalidParameterValue,
                          self.common.get_iscsi_properties,
                          volume)

    def test_get_iscsi_properties_multipath(self):
        volume = copy.deepcopy(VOLUME)
        iscsi_properties = {
            'target_discovered': False,
            'target_iqn': IQN,
            'target_iqns': [IQN] * 3,
            'target_lun': 0,
            'target_luns': [0] * 3,
            'target_portal': '%s:3260' % IP,
            'target_portals':
                ['%s:3260' % IP, '10.0.0.2:3260', '10.0.0.3:3260'],
            'volume_id': VOLUME['id'],
            'access_mode': 'rw',
            'discard': False,
            'auth_method': 'CHAP',
            'auth_username': CHAP_AUTH_USERNAME,
            'auth_password': CHAP_AUTH_PASSWORD
        }
        self.common.get_ip = mock.Mock(return_value=IP)
        self.conf.safe_get = mock.Mock(return_value=['10.0.0.2', '10.0.0.3'])

        result = self.common.get_iscsi_properties(volume)
        self.assertDictEqual(iscsi_properties, result)

        volume['provider_location'] = ''
        self.assertRaises(exception.InvalidParameterValue,
                          self.common.get_iscsi_properties,
                          volume)

    def test_get_iscsi_properties_without_chap(self):
        volume = copy.deepcopy(VOLUME)
        iscsi_properties = {
            'target_discovered': False,
            'target_iqn': IQN,
            'target_portal': '%s:3260' % IP,
            'volume_id': VOLUME['id'],
            'access_mode': 'rw',
            'discard': False
        }
        self.common.get_ip = mock.Mock(return_value=IP)
        self.conf.safe_get = mock.Mock(return_value=[])

        volume['provider_auth'] = 'abcde'
        result = self.common.get_iscsi_properties(volume)
        self.assertDictEqual(iscsi_properties, result)

        volume['provider_auth'] = ''
        result = self.common.get_iscsi_properties(volume)
        self.assertDictEqual(iscsi_properties, result)

        del volume['provider_auth']
        result = self.common.get_iscsi_properties(volume)
        self.assertDictEqual(iscsi_properties, result)

    def test_create_iscsi_export(self):
        self.common._target_create = (
            mock.Mock(return_value=(IQN, TRG_ID, VOLUME['provider_auth'])))
        self.common._lun_map_target = mock.Mock()

        iqn, trg_id, provider_auth = (
            self.common.create_iscsi_export(VOLUME['name'], VOLUME['id']))

        self.common._target_create.assert_called_with(VOLUME['id'])
        self.common._lun_map_target.assert_called_with(VOLUME['name'], trg_id)
        self.assertEqual((IQN, TRG_ID, VOLUME['provider_auth']),
                         (iqn, trg_id, provider_auth))

    def test_remove_iscsi_export(self):
        trg_id = TRG_ID
        self.common._lun_unmap_target = mock.Mock()
        self.common._target_delete = mock.Mock()

        result = self.common.remove_iscsi_export(VOLUME['name'], trg_id)

        self.assertIsNone(result)
        self.common._lun_unmap_target.assert_called_with(VOLUME['name'],
                                                         TRG_ID)
        self.common._target_delete.assert_called_with(TRG_ID)
