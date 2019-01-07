# Copyright 2018 Inspur Corp.
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
Volume driver test for Inspur AS13000
"""

import json
import mock
import random
import time

import ddt
import eventlet
from oslo_config import cfg
import requests

from cinder import context
from cinder import exception
from cinder import test
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder.volume import configuration
from cinder.volume.drivers.inspur.as13000 import as13000_driver
from cinder.volume import utils as volume_utils


CONF = cfg.CONF

test_config = configuration.Configuration(None)
test_config.san_ip = 'some_ip'
test_config.san_api_port = 'as13000_api_port'
test_config.san_login = 'username'
test_config.san_password = 'password'
test_config.as13000_ipsan_pools = ['fakepool']
test_config.as13000_meta_pool = 'meta_pool'
test_config.use_chap_auth = True
test_config.chap_username = 'fakeuser'
test_config.chap_password = 'fakepass'


class FakeResponse(object):
    def __init__(self, status, output):
        self.status_code = status
        self.text = 'return message'
        self._json = output

    def json(self):
        return self._json

    def close(self):
        pass


@ddt.ddt
class RestAPIExecutorTestCase(test.TestCase):
    def setUp(self):
        self.rest_api = as13000_driver.RestAPIExecutor(
            test_config.san_ip,
            test_config.san_api_port,
            test_config.san_login,
            test_config.san_password)
        super(RestAPIExecutorTestCase, self).setUp()

    def test_login(self):
        mock__login = self.mock_object(self.rest_api, '_login',
                                       mock.Mock(return_value='fake_token'))
        self.rest_api.login()
        mock__login.assert_called_once()
        self.assertEqual('fake_token', self.rest_api._token)

    def test__login(self):
        response = {'token': 'fake_token', 'expireTime': '7200', 'type': 0}
        mock_sra = self.mock_object(self.rest_api, 'send_rest_api',
                                    mock.Mock(return_value=response))

        result = self.rest_api._login()

        self.assertEqual('fake_token', result)

        login_params = {'name': test_config.san_login,
                        'password': test_config.san_password}
        mock_sra.assert_called_once_with(method='security/token',
                                         params=login_params,
                                         request_type='post')

    def test_send_rest_api(self):
        expected = {'value': 'abc'}
        mock_sa = self.mock_object(self.rest_api, 'send_api',
                                   mock.Mock(return_value=expected))
        result = self.rest_api.send_rest_api(
            method='fake_method',
            params='fake_params',
            request_type='fake_type')
        self.assertEqual(expected, result)
        mock_sa.assert_called_once_with(
            'fake_method',
            'fake_params',
            'fake_type')

    def test_send_rest_api_retry(self):
        expected = {'value': 'abc'}
        mock_sa = self.mock_object(
            self.rest_api,
            'send_api',
            mock.Mock(side_effect=(exception.VolumeDriverException, expected)))
        mock_login = self.mock_object(self.rest_api, 'login', mock.Mock())
        result = self.rest_api.send_rest_api(
            method='fake_method',
            params='fake_params',
            request_type='fake_type'
        )
        self.assertEqual(expected, result)

        mock_sa.assert_called_with(
            'fake_method',
            'fake_params',
            'fake_type')
        mock_login.assert_called_once()

    def test_send_rest_api_3times_fail(self):
        mock_sa = self.mock_object(
            self.rest_api, 'send_api', mock.Mock(
                side_effect=(exception.VolumeDriverException)))
        mock_login = self.mock_object(self.rest_api, 'login', mock.Mock())
        self.assertRaises(
            exception.VolumeDriverException,
            self.rest_api.send_rest_api,
            method='fake_method',
            params='fake_params',
            request_type='fake_type')
        mock_sa.assert_called_with('fake_method',
                                   'fake_params',
                                   'fake_type')
        mock_login.assert_called()

    def test_send_rest_api_backend_error_fail(self):
        side_effect = exception.VolumeBackendAPIException('fake_err_msg')
        mock_sa = self.mock_object(self.rest_api,
                                   'send_api',
                                   mock.Mock(side_effect=side_effect))
        mock_login = self.mock_object(self.rest_api, 'login')

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.rest_api.send_rest_api,
                          method='fake_method',
                          params='fake_params',
                          request_type='fake_type')
        mock_sa.assert_called_with('fake_method',
                                   'fake_params',
                                   'fake_type')
        mock_login.assert_not_called()

    @ddt.data(
        {'method': 'fake_method', 'request_type': 'post', 'params':
            {'fake_param': 'fake_value'}},
        {'method': 'fake_method', 'request_type': 'get', 'params':
            {'fake_param': 'fake_value'}},
        {'method': 'fake_method', 'request_type': 'delete', 'params':
            {'fake_param': 'fake_value'}},
        {'method': 'fake_method', 'request_type': 'put', 'params':
            {'fake_param': 'fake_value'}}, )
    @ddt.unpack
    def test_send_api(self, method, params, request_type):
        self.rest_api._token = 'fake_token'
        if request_type in ('post', 'delete', 'put'):
            fake_output = {'code': 0, 'message': 'success'}
        elif request_type == 'get':
            fake_output = {'code': 0, 'data': 'fake_date'}
        mock_request = self.mock_object(
            requests, request_type, mock.Mock(
                return_value=FakeResponse(
                    200, fake_output)))
        self.rest_api.send_api(
            method,
            params=params,
            request_type=request_type)
        mock_request.assert_called_once_with(
            'http://%s:%s/rest/%s' %
            (test_config.san_ip,
             test_config.san_api_port,
             method),
            data=json.dumps(params),
            headers={'X-Auth-Token': 'fake_token'})

    @ddt.data({'method': r'security/token',
               'params': {'name': test_config.san_login,
                          'password': test_config.san_password},
               'request_type': 'post'},
              {'method': r'security/token',
               'params': None,
               'request_type': 'delete'})
    @ddt.unpack
    def test_send_api_access_success(self, method, params, request_type):
        if request_type == 'post':
            fake_value = {'code': 0, 'data': {
                'token': 'fake_token',
                'expireTime': '7200',
                'type': 0}}
            mock_requests = self.mock_object(
                requests, 'post', mock.Mock(
                    return_value=FakeResponse(
                        200, fake_value)))
            result = self.rest_api.send_api(method, params, request_type)
            self.assertEqual(fake_value['data'], result)
            mock_requests.assert_called_once_with(
                'http://%s:%s/rest/%s' %
                (test_config.san_ip,
                 test_config.san_api_port,
                 method),
                data=json.dumps(params),
                headers=None)
        if request_type == 'delete':
            fake_value = {'code': 0, 'message': 'Success!'}
            self.rest_api._token = 'fake_token'
            mock_requests = self.mock_object(
                requests, 'delete', mock.Mock(
                    return_value=FakeResponse(
                        200, fake_value)))
            self.rest_api.send_api(method, params, request_type)
            mock_requests.assert_called_once_with(
                'http://%s:%s/rest/%s' %
                (test_config.san_ip,
                 test_config.san_api_port,
                 method),
                data=None,
                headers={'X-Auth-Token': 'fake_token'})

    def test_send_api_wrong_access_fail(self):
        req_params = {'method': r'security/token',
                      'params': {'name': test_config.san_login,
                                 'password': 'fake_password'},
                      'request_type': 'post'}
        fake_value = {'message': ' User name or password error.', 'code': 400}
        mock_request = self.mock_object(
            requests, 'post', mock.Mock(
                return_value=FakeResponse(
                    200, fake_value)))
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.rest_api.send_api,
            method=req_params['method'],
            params=req_params['params'],
            request_type=req_params['request_type'])
        mock_request.assert_called_once_with(
            'http://%s:%s/rest/%s' %
            (test_config.san_ip,
             test_config.san_api_port,
             req_params['method']),
            data=json.dumps(
                req_params['params']),
            headers=None)

    def test_send_api_token_overtime_fail(self):
        self.rest_api._token = 'fake_token'
        fake_value = {'method': 'fake_url',
                      'params': 'fake_params',
                      'reuest_type': 'post'}
        fake_out_put = {'message': 'Unauthorized access!', 'code': 301}
        mock_requests = self.mock_object(
            requests, 'post', mock.Mock(
                return_value=FakeResponse(
                    200, fake_out_put)))
        self.assertRaises(exception.VolumeDriverException,
                          self.rest_api.send_api,
                          method='fake_url',
                          params='fake_params',
                          request_type='post')
        mock_requests.assert_called_once_with(
            'http://%s:%s/rest/%s' %
            (test_config.san_ip,
             test_config.san_api_port,
             fake_value['method']),
            data=json.dumps('fake_params'),
            headers={
                'X-Auth-Token': 'fake_token'})

    def test_send_api_fail(self):
        self.rest_api._token = 'fake_token'
        fake_output = {'code': 999, 'message': 'fake_message'}
        mock_request = self.mock_object(
            requests, 'post', mock.Mock(
                return_value=FakeResponse(
                    200, fake_output)))
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.rest_api.send_api,
            method='fake_method',
            params='fake_params',
            request_type='post')
        mock_request.assert_called_once_with(
            'http://%s:%s/rest/%s' %
            (test_config.san_ip,
             test_config.san_api_port,
             'fake_method'),
            data=json.dumps('fake_params'),
            headers={'X-Auth-Token': 'fake_token'}
        )


@ddt.ddt
class AS13000DriverTestCase(test.TestCase):
    def __init__(self, *args, **kwds):
        super(AS13000DriverTestCase, self).__init__(*args, **kwds)
        self._ctxt = context.get_admin_context()
        self.configuration = test_config

    def setUp(self):
        self.rest_api = as13000_driver.RestAPIExecutor(
            test_config.san_ip,
            test_config.san_api_port,
            test_config.san_login,
            test_config.san_password)
        self.as13000_san = as13000_driver.AS13000Driver(
            configuration=self.configuration)
        super(AS13000DriverTestCase, self).setUp()

    @ddt.data(None, 'pool1')
    def test_do_setup(self, meta_pool):
        mock_login = self.mock_object(as13000_driver.RestAPIExecutor,
                                      'login', mock.Mock())
        fake_nodes = [{'healthStatus': 1, 'ip': 'fakeip1'},
                      {'healthStatus': 1, 'ip': 'fakeip2'},
                      {'healthStatus': 1, 'ip': 'fakeip3'}]
        mock_gcs = self.mock_object(self.as13000_san,
                                    '_get_cluster_status',
                                    mock.Mock(return_value=fake_nodes))
        fake_pools = {
            'pool1': {'name': 'pool1', 'type': '1'},
            'pool2': {'name': 'pool2', 'type': 2}
        }
        mock_gpi = self.mock_object(self.as13000_san,
                                    '_get_pools_info',
                                    mock.Mock(return_value=fake_pools))
        mock_cp = self.mock_object(self.as13000_san,
                                   '_check_pools',
                                   mock.Mock())
        mock_cmp = self.mock_object(self.as13000_san,
                                    '_check_meta_pool',
                                    mock.Mock())

        self.as13000_san.meta_pool = meta_pool
        self.as13000_san.pools = ['pool1', 'pool2']
        self.as13000_san.do_setup(self._ctxt)

        mock_login.assert_called_once()
        mock_gcs.assert_called_once()
        if meta_pool:
            mock_gpi.assert_called_with(['pool1', 'pool2', 'pool1'])
        else:
            mock_gpi.assert_called_with(['pool1', 'pool2'])
            self.assertEqual('pool1', self.as13000_san.meta_pool)
        mock_cp.assert_called_once()
        mock_cmp.assert_called_once()

    def test_check_for_setup_error(self):
        mock_sg = self.mock_object(configuration.Configuration, 'safe_get',
                                   mock.Mock(return_value='fake_config'))
        self.as13000_san.nodes = [{'fakenode': 'fake_name'}]
        self.as13000_san.check_for_setup_error()
        mock_sg.assert_called()

    def test_check_for_setup_error_no_healthy_node_fail(self):
        mock_sg = self.mock_object(configuration.Configuration, 'safe_get',
                                   mock.Mock(return_value='fake_config'))
        self.as13000_san.nodes = []
        self.assertRaises(exception.VolumeDriverException,
                          self.as13000_san.check_for_setup_error)
        mock_sg.assert_called()

    def test_check_for_setup_error_no_config_fail(self):
        mock_sg = self.mock_object(configuration.Configuration, 'safe_get',
                                   mock.Mock(return_value=None))
        self.as13000_san.nodes = []
        self.assertRaises(exception.InvalidConfigurationValue,
                          self.as13000_san.check_for_setup_error)
        mock_sg.assert_called()

    def test__check_pools(self):
        fake_pools_info = {
            'pool1': {'name': 'pool1', 'type': '1'},
            'pool2': {'name': 'pool2', 'type': 1}
        }
        self.as13000_san.pools = ['pool1']
        self.as13000_san.pools_info = fake_pools_info
        self.as13000_san._check_pools()

    def test__check_pools_fail(self):
        fake_pools_info = {
            'pool1': {'name': 'pool1', 'type': '1'},
            'pool2': {'name': 'pool2', 'type': 1}
        }
        self.as13000_san.pools = ['pool0, pool1']
        self.as13000_san.pools_info = fake_pools_info
        self.assertRaises(exception.InvalidInput,
                          self.as13000_san._check_pools)

    def test__check_meta_pool(self):
        fake_pools_info = {
            'pool1': {'name': 'pool1', 'type': 2},
            'pool2': {'name': 'pool2', 'type': 1}
        }
        self.as13000_san.meta_pool = 'pool2'
        self.as13000_san.pools_info = fake_pools_info
        self.as13000_san._check_meta_pool()

    @ddt.data(None, 'pool0', 'pool1')
    def test__check_meta_pool_failed(self, meta_pool):
        fake_pools_info = {
            'pool1': {'name': 'pool1', 'type': 2},
            'pool2': {'name': 'pool2', 'type': 1}
        }

        self.as13000_san.meta_pool = meta_pool
        self.as13000_san.pools_info = fake_pools_info
        self.assertRaises(exception.InvalidInput,
                          self.as13000_san._check_meta_pool)

    @mock.patch.object(as13000_driver.RestAPIExecutor,
                       'send_rest_api')
    def test_create_volume(self, mock_rest):
        volume = fake_volume.fake_volume_obj(self._ctxt, host='H@B#P')
        self.as13000_san.pools_info = {'P': {'name': 'P', 'type': 1}}
        self.as13000_san.meta_pool = 'meta_pool'
        self.as13000_san.create_volume(volume)

        mock_rest.assert_called_once_with(
            method='block/lvm',
            params={
                "name": volume.name.replace('-', '_'),
                "capacity": volume.size * 1024,
                "dataPool": 'P',
                "dataPoolType": 1,
                "metaPool": 'meta_pool'
            },
            request_type='post')

    @ddt.data(1, 2)
    def test_create_volume_from_snapshot(self, size):
        volume = fake_volume.fake_volume_obj(self._ctxt, size=size)
        volume2 = fake_volume.fake_volume_obj(self._ctxt)
        snapshot = fake_snapshot.fake_snapshot_obj(self._ctxt, volume=volume2)

        mock_eh = self.mock_object(volume_utils,
                                   'extract_host',
                                   mock.Mock(return_value='fake_pool'))
        _tnd_mock = mock.Mock(side_effect=('source_volume',
                                           'dest_volume',
                                           'snapshot'))
        mock_tnd = self.mock_object(self.as13000_san,
                                    '_trans_name_down',
                                    _tnd_mock)
        mock_lock_op = self.mock_object(self.as13000_san,
                                        '_snapshot_lock_op',
                                        mock.Mock())
        mock_rest = self.mock_object(as13000_driver.RestAPIExecutor,
                                     'send_rest_api',
                                     mock.Mock())
        mock_fv = self.mock_object(self.as13000_san,
                                   '_filling_volume',
                                   mock.Mock())
        mock_wvf = self.mock_object(self.as13000_san,
                                    '_wait_volume_filled',
                                    mock.Mock())
        mock_ev = self.mock_object(self.as13000_san, 'extend_volume',
                                   mock.Mock())

        self.as13000_san.create_volume_from_snapshot(volume, snapshot)

        lock_op_calls = [
            mock.call('lock', 'source_volume', 'snapshot', 'fake_pool'),
            mock.call('unlock', 'source_volume', 'snapshot', 'fake_pool')
        ]
        mock_lock_op.assert_has_calls(lock_op_calls)
        mock_fv.assert_called_once_with('dest_volume', 'fake_pool')
        mock_wvf.assert_called_once_with('dest_volume', 'fake_pool')

        mock_eh.assert_called()
        mock_tnd.assert_called()
        params = {
            'originalLvm': 'source_volume',
            'originalPool': 'fake_pool',
            'originalSnap': 'snapshot',
            'name': 'dest_volume',
            'pool': 'fake_pool'}
        mock_rest.assert_called_once_with(method='snapshot/volume/cloneLvm',
                                          params=params,
                                          request_type='post')
        if size == 2:
            mock_ev.assert_called_once_with(volume, size)

    def test_create_volume_from_snapshot_fail(self):
        volume = fake_volume.fake_volume_obj(self._ctxt)
        snapshot = fake_snapshot.fake_snapshot_obj(self._ctxt, volume_size=10)
        self.assertRaises(
            exception.InvalidInput,
            self.as13000_san.create_volume_from_snapshot, volume, snapshot)

    @ddt.data(1, 2)
    def test_create_cloned_volume(self, size):
        volume = fake_volume.fake_volume_obj(self._ctxt, size=size)
        volume_src = fake_volume.fake_volume_obj(self._ctxt)
        mock_eh = self.mock_object(volume_utils,
                                   'extract_host',
                                   mock.Mock(return_value='fake_pool'))
        mock_tnd = self.mock_object(
            self.as13000_san, '_trans_name_down', mock.Mock(
                side_effect=('fake_name1', 'fake_name2')))
        mock_rest = self.mock_object(as13000_driver.RestAPIExecutor,
                                     'send_rest_api',
                                     mock.Mock())
        mock_ev = self.mock_object(self.as13000_san,
                                   'extend_volume',
                                   mock.Mock())
        self.as13000_san.create_cloned_volume(volume, volume_src)
        mock_eh.assert_called()
        mock_tnd.assert_called()
        method = 'block/lvm/clone'
        params = {
            'srcVolumeName': 'fake_name2',
            'srcPoolName': 'fake_pool',
            'destVolumeName': 'fake_name1',
            'destPoolName': 'fake_pool'}
        request_type = 'post'
        mock_rest.assert_called_once_with(
            method=method, params=params, request_type=request_type)
        if size == 2:
            mock_ev.assert_called_once_with(volume, size)

    def test_create_clone_volume_fail(self):
        volume = fake_volume.fake_volume_obj(self._ctxt)
        volume_source = fake_volume.fake_volume_obj(self._ctxt, size=2)
        self.assertRaises(
            exception.InvalidInput,
            self.as13000_san.create_cloned_volume, volume, volume_source)

    def test_extend_volume(self):
        volume = fake_volume.fake_volume_obj(self._ctxt)
        mock_tnd = self.mock_object(
            self.as13000_san, '_trans_name_down', mock.Mock(
                return_value='fake_name'))
        mock_cv = self.mock_object(self.as13000_san,
                                   '_check_volume',
                                   mock.Mock(return_value=True))
        mock_eh = self.mock_object(volume_utils,
                                   'extract_host',
                                   mock.Mock(return_value='fake_pool'))
        mock_rest = self.mock_object(as13000_driver.RestAPIExecutor,
                                     'send_rest_api',
                                     mock.Mock())
        self.as13000_san.extend_volume(volume, 10)
        mock_tnd.assert_called_once_with(volume.name)
        mock_cv.assert_called_once_with(volume)
        mock_eh.assert_called_once_with(volume.host, level='pool')
        method = 'block/lvm'
        request_type = 'put'
        params = {'pool': 'fake_pool',
                  'name': 'fake_name',
                  'newCapacity': 10240}
        mock_rest.assert_called_once_with(method=method,
                                          request_type=request_type,
                                          params=params)

    def test_extend_volume_fail(self):
        volume = fake_volume.fake_volume_obj(self._ctxt)
        mock_tnd = self.mock_object(
            self.as13000_san, '_trans_name_down', mock.Mock(
                return_value='fake_name'))
        mock_cv = self.mock_object(self.as13000_san,
                                   '_check_volume',
                                   mock.Mock(return_value=False))
        self.assertRaises(exception.VolumeDriverException,
                          self.as13000_san.extend_volume, volume, 10)
        mock_tnd.assert_called_once_with(volume.name)
        mock_cv.assert_called_once_with(volume)

    @ddt.data(True, False)
    def test_delete_volume(self, volume_exist):
        volume = fake_volume.fake_volume_obj(self._ctxt)
        mock_eh = self.mock_object(volume_utils,
                                   'extract_host',
                                   mock.Mock(return_value='fake_pool'))
        mock_tnd = self.mock_object(
            self.as13000_san, '_trans_name_down', mock.Mock(
                return_value='fake_name'))
        mock_cv = self.mock_object(self.as13000_san,
                                   '_check_volume',
                                   mock.Mock(return_value=volume_exist))
        mock_rest = self.mock_object(as13000_driver.RestAPIExecutor,
                                     'send_rest_api',
                                     mock.Mock())
        self.as13000_san.delete_volume(volume)
        mock_tnd.assert_called_once_with(volume.name)
        mock_cv.assert_called_once_with(volume)

        if volume_exist:
            mock_eh.assert_called_once_with(volume.host, level='pool')

            method = 'block/lvm?pool=%s&lvm=%s' % ('fake_pool', 'fake_name')
            request_type = 'delete'
            mock_rest.assert_called_once_with(method=method,
                                              request_type=request_type)

    def test_create_snapshot(self):
        volume = fake_volume.fake_volume_obj(self._ctxt)
        snapshot = fake_snapshot.fake_snapshot_obj(self._ctxt, volume=volume)
        mock_eh = self.mock_object(volume_utils,
                                   'extract_host',
                                   mock.Mock(return_value='fake_pool'))
        mock_cv = self.mock_object(self.as13000_san,
                                   '_check_volume',
                                   mock.Mock(return_value=True))
        mock_tnd = self.mock_object(
            self.as13000_san, '_trans_name_down', mock.Mock(
                side_effect=('fake_name', 'fake_snap')))
        mock_rest = self.mock_object(as13000_driver.RestAPIExecutor,
                                     'send_rest_api',
                                     mock.Mock())
        self.as13000_san.create_snapshot(snapshot)

        mock_eh.assert_called_once_with(volume.host, level='pool')
        mock_tnd.assert_called()
        mock_cv.assert_called_once_with(snapshot.volume)
        method = 'snapshot/volume'
        params = {'snapName': 'fake_snap',
                  'volumeName': 'fake_name',
                  'poolName': 'fake_pool',
                  'snapType': 'r'}
        request_type = 'post'
        mock_rest.assert_called_once_with(method=method,
                                          params=params,
                                          request_type=request_type)

    def test_create_snapshot_fail(self):
        volume = fake_volume.fake_volume_obj(self._ctxt)
        snapshot = fake_snapshot.fake_snapshot_obj(self._ctxt, volume=volume)
        mock_cv = self.mock_object(self.as13000_san,
                                   '_check_volume',
                                   mock.Mock(return_value=False))
        self.assertRaises(exception.VolumeDriverException,
                          self.as13000_san.create_snapshot, snapshot)
        mock_cv.assert_called_once_with(snapshot.volume)

    def test_delete_snapshot(self):
        volume = fake_volume.fake_volume_obj(self._ctxt)
        snapshot = fake_snapshot.fake_snapshot_obj(self._ctxt, volume=volume)
        mock_eh = self.mock_object(volume_utils,
                                   'extract_host',
                                   mock.Mock(return_value='fake_pool'))
        mock_cv = self.mock_object(self.as13000_san,
                                   '_check_volume',
                                   mock.Mock(return_value=True))
        mock_tnd = self.mock_object(
            self.as13000_san, '_trans_name_down', mock.Mock(
                side_effect=('fake_name', 'fake_snap')))
        mock_rest = self.mock_object(as13000_driver.RestAPIExecutor,
                                     'send_rest_api',
                                     mock.Mock())
        self.as13000_san.delete_snapshot(snapshot)

        mock_eh.assert_called_once_with(volume.host, level='pool')
        mock_tnd.assert_called()
        mock_cv.assert_called_once_with(snapshot.volume)

        method = ('snapshot/volume?snapName=%s&volumeName=%s&poolName=%s'
                  % ('fake_snap', 'fake_name', 'fake_pool'))
        request_type = 'delete'
        mock_rest.assert_called_once_with(method=method,
                                          request_type=request_type)

    def test_delete_snapshot_fail(self):
        volume = fake_volume.fake_volume_obj(self._ctxt)
        snapshot = fake_snapshot.fake_snapshot_obj(self._ctxt, volume=volume)
        mock_cv = self.mock_object(self.as13000_san,
                                   '_check_volume',
                                   mock.Mock(return_value=False))
        self.assertRaises(exception.VolumeDriverException,
                          self.as13000_san.delete_snapshot, snapshot)
        mock_cv.assert_called_once_with(snapshot.volume)

    @ddt.data((time.time() - 3000), (time.time() - 4000))
    def test__update_volume_stats(self, time_token):
        self.as13000_san.VENDOR = 'INSPUR'
        self.as13000_san.VERSION = 'V1.3.1'
        self.as13000_san.PROTOCOL = 'iSCSI'
        mock_sg = self.mock_object(configuration.Configuration, 'safe_get',
                                   mock.Mock(return_value='fake_backend_name'))
        fake_pool_backend = [{'pool_name': 'fake_pool'},
                             {'pool_name': 'fake_pool1'}]
        self.as13000_san.pools = ['fake_pool']
        mock_gps = self.mock_object(self.as13000_san, '_get_pools_stats',
                                    mock.Mock(return_value=fake_pool_backend))
        self.as13000_san._stats = None
        self.as13000_san._token_time = time_token
        self.as13000_san.token_available_time = 3600
        mock_login = self.mock_object(as13000_driver.RestAPIExecutor,
                                      'login')

        self.as13000_san._update_volume_stats()
        backend_data = {'driver_version': 'V1.3.1',
                        'pools': [{'pool_name': 'fake_pool'}],
                        'storage_protocol': 'iSCSI',
                        'vendor_name': 'INSPUR',
                        'volume_backend_name': 'fake_backend_name'}

        self.assertEqual(backend_data, self.as13000_san._stats)
        mock_sg.assert_called_once_with('volume_backend_name')
        mock_gps.assert_called_once()
        if (time.time() - time_token) > 3600:
            mock_login.assert_called_once()
        else:
            mock_login.assert_not_called()

    @ddt.data((4, u'127.0.0.1', '3260'),
              (6, u'FF01::101', '3260'))
    @ddt.unpack
    def test__build_target_portal(self, version, ip, port):
        portal = self.as13000_san._build_target_portal(ip, port)
        if version == 4:
            self.assertEqual(portal, '127.0.0.1:3260')
        else:
            self.assertEqual(portal, '[FF01::101]:3260')

    @ddt.data((True, True, True),
              (True, True, False),
              (False, True, True),
              (False, True, False),
              (False, False, True),
              (False, False, False),
              (True, False, True),
              (True, False, False))
    @ddt.unpack
    def test_initialize_connection(self, host_exist, multipath, chap_enabled):
        volume = fake_volume.fake_volume_obj(self._ctxt)
        connector = {'multipath': multipath,
                     'ip': 'fake_ip',
                     'host': 'fake_host'}
        self.as13000_san.configuration.use_chap_auth = chap_enabled
        fakenode = [{'name': 'fake_name1', 'ip': 'node_ip1'},
                    {'name': 'fake_name2', 'ip': 'node_ip2'},
                    {'name': 'fake_name3', 'ip': 'node_ip3'}]
        self.as13000_san.nodes = fakenode
        if multipath:
            mock_gtfc = self.mock_object(
                self.as13000_san,
                '_get_target_from_conn',
                mock.Mock(return_value=(host_exist,
                                        'target_name',
                                        ['fake_name1', 'fake_name2'])))
        else:
            mock_gtfc = self.mock_object(
                self.as13000_san,
                '_get_target_from_conn',
                mock.Mock(return_value=(host_exist,
                                        'target_name',
                                        ['fake_name1'])))

        mock_altt = self.mock_object(self.as13000_san,
                                     '_add_lun_to_target',
                                     mock.Mock())
        mock_ct = self.mock_object(self.as13000_san,
                                   '_create_target',
                                   mock.Mock())
        mock_ahtt = self.mock_object(self.as13000_san,
                                     '_add_host_to_target',
                                     mock.Mock())
        mock_actt = self.mock_object(self.as13000_san,
                                     '_add_chap_to_target',
                                     mock.Mock())
        mock_gli = self.mock_object(self.as13000_san,
                                    '_get_lun_id',
                                    mock.Mock(return_value='1'))
        mock_rr = self.mock_object(random, 'randint',
                                   mock.Mock(return_value='12345678'))
        mock_btp = self.mock_object(self.as13000_san,
                                    '_build_target_portal',
                                    mock.Mock(side_effect=['node_ip1:3260',
                                                           'node_ip2:3260',
                                                           'node_ip3:3260']))

        connect_info = self.as13000_san.initialize_connection(
            volume, connector)

        expect_conn_data = {
            'target_discovered': True,
            'volume_id': volume.id,
        }
        if host_exist:
            if multipath:
                expect_conn_data.update({
                    'target_portals': ['node_ip1:3260', 'node_ip2:3260'],
                    'target_luns': [1] * 2,
                    'target_iqns': ['target_name'] * 2
                })
            else:
                expect_conn_data.update({
                    'target_portal': 'node_ip1:3260',
                    'target_lun': 1,
                    'target_iqn': 'target_name'
                })
        else:
            target_name = 'target.inspur.fake_host-12345678'
            if multipath:
                expect_conn_data.update({
                    'target_portals': ['node_ip1:3260',
                                       'node_ip2:3260',
                                       'node_ip3:3260'],
                    'target_luns': [1] * 3,
                    'target_iqns': [target_name] * 3
                })
            else:
                expect_conn_data.update({
                    'target_portal': 'node_ip1:3260',
                    'target_lun': 1,
                    'target_iqn': target_name
                })

        if chap_enabled:
            expect_conn_data['auth_method'] = 'CHAP'
            expect_conn_data['auth_username'] = 'fakeuser'
            expect_conn_data['auth_password'] = 'fakepass'

        expect_datas = {
            'driver_volume_type': 'iscsi',
            'data': expect_conn_data
        }

        self.assertEqual(expect_datas, connect_info)
        mock_gtfc.assert_called_once_with('fake_ip')
        mock_altt.assert_called_once()
        if not host_exist:
            mock_ct.assert_called_once()
            mock_ahtt.assert_called_once()
            mock_rr.assert_called_once()
        if chap_enabled:
            mock_actt.assert_called_once()

        mock_gli.assert_called_once()
        mock_btp.assert_called()

    @ddt.data(True, False)
    def test_terminate_connection(self, delete_target):
        volume = fake_volume.fake_volume_obj(self._ctxt, host='fakehost')
        connector = {'multipath': False,
                     'ip': 'fake_ip',
                     'host': 'fake_host'}
        mock_tnd = self.mock_object(self.as13000_san, '_trans_name_down',
                                    mock.Mock(return_value='fake_volume'))
        fake_target_list = [{'hostIp': ['fake_ip'],
                             'name': 'target_name',
                             'lun': [
                                 {'lvm': 'fake_volume', 'lunID': 'fake_id'}]}]
        mock_gtl = self.mock_object(self.as13000_san, '_get_target_list',
                                    mock.Mock(return_value=fake_target_list))
        mock_dlft = self.mock_object(self.as13000_san,
                                     '_delete_lun_from_target',
                                     mock.Mock())
        if delete_target:
            mock_gll = self.mock_object(self.as13000_san, '_get_lun_list',
                                        mock.Mock(return_value=[]))
        else:
            mock_gll = self.mock_object(self.as13000_san, '_get_lun_list',
                                        mock.Mock(return_value=[1, 2]))
        mock_dt = self.mock_object(self.as13000_san, '_delete_target',
                                   mock.Mock())
        self.as13000_san.terminate_connection(volume, connector)
        mock_tnd.assert_called_once_with(volume.name)
        mock_gtl.assert_called_once()
        mock_dlft.assert_called_once_with(lun_id='fake_id',
                                          target_name='target_name')
        mock_gll.assert_called_once_with('target_name')
        if delete_target:
            mock_dt.assert_called_once_with('target_name')
        else:
            mock_dt.assert_not_called()

    @ddt.data(True, False)
    def test_terminate_connection_force(self, delete_target):
        volume = fake_volume.fake_volume_obj(self._ctxt, host='fakehost')
        connector = {}
        mock_tnd = self.mock_object(self.as13000_san, '_trans_name_down',
                                    mock.Mock(return_value='fake_volume'))
        fake_target_list = [{'hostIp': ['fake_hostIp'],
                             'name':'target_name',
                             'lun':[{'lvm': 'fake_volume',
                                     'lunID': 'fake_id'}]}]
        mock_gtl = self.mock_object(self.as13000_san, '_get_target_list',
                                    mock.Mock(return_value=fake_target_list))
        mock_dlft = self.mock_object(self.as13000_san,
                                     '_delete_lun_from_target',
                                     mock.Mock())
        if delete_target:
            mock_gll = self.mock_object(self.as13000_san, '_get_lun_list',
                                        mock.Mock(return_value=[]))
        else:
            mock_gll = self.mock_object(self.as13000_san, '_get_lun_list',
                                        mock.Mock(return_value=[1, 2]))
        mock_dt = self.mock_object(self.as13000_san, '_delete_target',
                                   mock.Mock())

        self.as13000_san.terminate_connection(volume, connector)

        mock_tnd.assert_called_once_with(volume.name)
        mock_gtl.assert_called_once()
        mock_dlft.assert_called_once_with(lun_id='fake_id',
                                          target_name='target_name')
        mock_gll.assert_called_once_with('target_name')
        if delete_target:
            mock_dt.assert_called_once_with('target_name')
        else:
            mock_dt.assert_not_called()

    @mock.patch.object(as13000_driver.RestAPIExecutor,
                       'send_rest_api')
    def test__get_pools_info(self, mock_rest):
        fake_pools_data = [{'name': 'pool1', 'type': 1},
                           {'name': 'pool2', 'type': 2}]
        mock_rest.return_value = fake_pools_data

        # get a partial of pools
        result_pools_info = self.as13000_san._get_pools_info(['pool1'])
        self.assertEqual(result_pools_info,
                         {'pool1': {'name': 'pool1', 'type': 1}})

        # get both exist pools
        result_pools_info = self.as13000_san._get_pools_info(['pool1',
                                                              'pool2'])
        self.assertEqual(result_pools_info,
                         {'pool1': {'name': 'pool1', 'type': 1},
                          'pool2': {'name': 'pool2', 'type': 2}})

        # get pools not exist
        result_pools_info = self.as13000_san._get_pools_info(['pool1',
                                                              'pool2',
                                                              'pool3'])
        self.assertEqual(result_pools_info,
                         {'pool1': {'name': 'pool1', 'type': 1},
                          'pool2': {'name': 'pool2', 'type': 2}})

    def test__get_pools_stats(self):
        pool_date = [{'ID': 'fake_id',
                      'name': 'fake_name',
                      'totalCapacity': '2t',
                      'usedCapacity': '300g'}]
        self.as13000_san.pools = ['fake_name']
        mock_rest = self.mock_object(as13000_driver.RestAPIExecutor,
                                     'send_rest_api',
                                     mock.Mock(return_value=pool_date))
        mock_uc = self.mock_object(self.as13000_san, '_unit_convert',
                                   mock.Mock(side_effect=(2000, 300)))
        pool_info = {
            'pool_name': 'fake_name',
            'total_capacity_gb': 2000,
            'free_capacity_gb': 1700,
            'thin_provisioning_support': True,
            'thick_provisioning_support': False,
        }

        result_pools = self.as13000_san._get_pools_stats()

        expect_pools = [pool_info]
        self.assertEqual(expect_pools, result_pools)
        mock_rest.assert_called_once_with(method='block/pool?type=2',
                                          request_type='get')
        mock_uc.assert_called()

    @ddt.data('fake_ip3', 'fake_ip5')
    def test__get_target_from_conn(self, host_ip):
        target_list = [
            {
                'hostIp': ['fake_ip1', 'fake_ip2'],
                'name':'fake_target_1',
                'node':['fake_node1', 'fake_node2']
            },
            {
                'hostIp': ['fake_ip3', 'fake_ip4'],
                'name': 'fake_target_2',
                'node': ['fake_node4', 'fake_node3']
            }
        ]
        mock_gtl = self.mock_object(self.as13000_san,
                                    '_get_target_list',
                                    mock.Mock(return_value=target_list))

        host_exist, target_name, node = (
            self.as13000_san._get_target_from_conn(host_ip))

        if host_ip is 'fake_ip3':
            self.assertEqual((True, 'fake_target_2',
                              ['fake_node4', 'fake_node3']),
                             (host_exist, target_name, node))
        else:
            self.assertEqual((False, None, None),
                             (host_exist, target_name, node))
        mock_gtl.assert_called_once()

    def test__get_target_list(self):
        mock_rest = self.mock_object(as13000_driver.RestAPIExecutor,
                                     'send_rest_api',
                                     mock.Mock(return_value='fake_date'))
        method = 'block/target/detail'
        request_type = 'get'
        result = self.as13000_san._get_target_list()
        self.assertEqual('fake_date', result)
        mock_rest.assert_called_once_with(method=method,
                                          request_type=request_type)

    def test__create_target(self):
        mock_rest = self.mock_object(as13000_driver.RestAPIExecutor,
                                     'send_rest_api',
                                     mock.Mock())
        target_name = 'fake_name'
        target_node = 'fake_node'
        method = 'block/target'
        params = {'name': target_name, 'nodeName': target_node}
        request_type = 'post'
        self.as13000_san._create_target(target_name, target_node)
        mock_rest.assert_called_once_with(method=method,
                                          params=params,
                                          request_type=request_type)

    def test__delete_target(self):
        mock_rest = self.mock_object(as13000_driver.RestAPIExecutor,
                                     'send_rest_api',
                                     mock.Mock())
        target_name = 'fake_name'
        method = 'block/target?name=%s' % target_name
        request_type = 'delete'
        self.as13000_san._delete_target(target_name)
        mock_rest.assert_called_once_with(method=method,
                                          request_type=request_type)

    def test__add_chap_to_target(self):
        mock_rest = self.mock_object(as13000_driver.RestAPIExecutor,
                                     'send_rest_api',
                                     mock.Mock())
        target_name = 'fake_name'
        chap_username = 'fake_user'
        chap_password = 'fake_pass'
        self.as13000_san._add_chap_to_target(target_name,
                                             chap_username,
                                             chap_password)

        method = 'block/chap/bond'
        params = {'target': target_name,
                  'user': chap_username,
                  'password': chap_password}
        request_type = 'post'
        mock_rest.assert_called_once_with(method=method,
                                          params=params,
                                          request_type=request_type)

    def test__add_host_to_target(self):
        mock_rest = self.mock_object(as13000_driver.RestAPIExecutor,
                                     'send_rest_api',
                                     mock.Mock())
        target_name = 'fake_name'
        host_ip = 'fake_ip'
        method = 'block/host'
        params = {'name': target_name, 'hostIp': host_ip}
        request_type = 'post'
        self.as13000_san._add_host_to_target(host_ip, target_name)
        mock_rest.assert_called_once_with(method=method,
                                          params=params,
                                          request_type=request_type)

    def test__add_lun_to_target(self):
        volume = fake_volume.fake_volume_obj(self._ctxt, host='fakehost')
        mock_eh = self.mock_object(volume_utils,
                                   'extract_host',
                                   mock.Mock(return_value='fake_pool'))
        mock_tnd = self.mock_object(self.as13000_san,
                                    '_trans_name_down',
                                    mock.Mock(return_value='fake_name'))
        mock_rest = self.mock_object(as13000_driver.RestAPIExecutor,
                                     'send_rest_api',
                                     mock.Mock())

        target_name = 'fake_target'
        self.as13000_san._add_lun_to_target(target_name, volume)
        method = 'block/lun'
        params = {'name': target_name,
                  'pool': 'fake_pool',
                  'lvm': 'fake_name'}
        request_type = 'post'
        mock_eh.assert_called_once_with(volume.host, level='pool')
        mock_tnd.assert_called_once_with(volume.name)
        mock_rest.assert_called_once_with(method=method,
                                          params=params,
                                          request_type=request_type)

    def test__add_lun_to_target_retry_3times(self):
        volume = fake_volume.fake_volume_obj(self._ctxt, host='fakehost')
        mock_eh = self.mock_object(volume_utils,
                                   'extract_host',
                                   mock.Mock(return_value='fake_pool'))
        mock_tnd = self.mock_object(self.as13000_san,
                                    '_trans_name_down',
                                    mock.Mock(return_value='fake_name'))
        mock_rest = self.mock_object(
            as13000_driver.RestAPIExecutor,
            'send_rest_api',
            mock.Mock(side_effect=(exception.VolumeDriverException,
                                   mock.MagicMock())))

        target_name = 'fake_target'
        self.as13000_san._add_lun_to_target(target_name, volume)
        method = 'block/lun'
        params = {'name': target_name,
                  'pool': 'fake_pool',
                  'lvm': 'fake_name'}
        request_type = 'post'
        mock_eh.assert_called_with(volume.host, level='pool')
        mock_tnd.assert_called_with(volume.name)
        mock_rest.assert_called_with(method=method,
                                     params=params,
                                     request_type=request_type)

    def test__add_lun_to_target_fail(self):
        volume = fake_volume.fake_volume_obj(self._ctxt, host='fakehost')
        mock_eh = self.mock_object(volume_utils,
                                   'extract_host',
                                   mock.Mock(return_value='fake_pool'))
        mock_tnd = self.mock_object(self.as13000_san,
                                    '_trans_name_down',
                                    mock.Mock(return_value='fake_name'))
        mock_rest = self.mock_object(
            as13000_driver.RestAPIExecutor,
            'send_rest_api',
            mock.Mock(side_effect=exception.VolumeDriverException))

        target_name = 'fake_target'
        self.assertRaises(exception.VolumeDriverException,
                          self.as13000_san._add_lun_to_target,
                          target_name=target_name,
                          volume=volume)
        method = 'block/lun'
        params = {'name': target_name,
                  'pool': 'fake_pool',
                  'lvm': 'fake_name'}
        request_type = 'post'
        mock_eh.assert_called_with(volume.host, level='pool')
        mock_tnd.assert_called_with(volume.name)
        mock_rest.assert_called_with(method=method,
                                     params=params,
                                     request_type=request_type)

    def test__delete_lun_from_target(self):
        mock_rest = self.mock_object(as13000_driver.RestAPIExecutor,
                                     'send_rest_api',
                                     mock.Mock())
        target_name = 'fake_target'
        lun_id = 'fake_id'
        self.as13000_san._delete_lun_from_target(target_name, lun_id)
        method = 'block/lun?name=%s&id=%s&force=1' % (target_name, lun_id)
        request_type = 'delete'
        mock_rest.assert_called_once_with(method=method,
                                          request_type=request_type)

    @ddt.data('lock', 'unlock')
    def test__snapshot_lock_op(self, operation):
        mock_rest = self.mock_object(as13000_driver.RestAPIExecutor,
                                     'send_rest_api',
                                     mock.Mock())
        vol_name = 'fake_volume'
        snap_name = 'fake_snapshot'
        pool_name = "fake_pool"
        self.as13000_san._snapshot_lock_op(operation,
                                           vol_name,
                                           snap_name,
                                           pool_name)

        method = 'snapshot/volume/' + operation
        request_type = 'post'
        params = {'snapName': snap_name,
                  'volumeName': vol_name,
                  'poolName': pool_name}
        mock_rest.assert_called_once_with(method=method,
                                          params=params,
                                          request_type=request_type)

    def test__filling_volume(self):
        mock_rest = self.mock_object(as13000_driver.RestAPIExecutor,
                                     'send_rest_api',
                                     mock.Mock())
        vol_name = 'fake_volume'
        pool_name = 'fake_pool'
        self.as13000_san._filling_volume(vol_name, pool_name)
        params = {'pool': 'fake_pool', 'name': 'fake_volume'}
        mock_rest.assert_called_once_with(method='block/lvm/filling',
                                          params=params,
                                          request_type='post')

    def test__wait_volume_filled(self):
        # Need to mock sleep as it is called by @utils.retry
        self.mock_object(time, 'sleep')

        expected = [{'name': 'fake_v1', 'lvmType': 1}]
        mock_gv = self.mock_object(self.as13000_san, '_get_volumes',
                                   mock.Mock(return_value=expected))
        self.as13000_san._wait_volume_filled('fake_v1', 'fake_pool')
        mock_gv.assert_called_with('fake_pool')

    def test__wait_volume_filled_failed(self):
        # Need to mock sleep as it is called by @utils.retry
        self.mock_object(time, 'sleep')

        expected = [{'name': 'fake_v1', 'lvmType': 2}]
        mock_gv = self.mock_object(self.as13000_san, '_get_volumes',
                                   mock.Mock(return_value=expected))
        self.assertRaises(exception.VolumeDriverException,
                          self.as13000_san._wait_volume_filled,
                          'fake_v1',
                          'fake_pool')
        mock_gv.assert_called_with('fake_pool')

    def test__get_lun_list(self):
        target_name = 'fake_name'
        lun_list = ['lun_1', 'lun_2']
        mock_rest = self.mock_object(as13000_driver.RestAPIExecutor,
                                     'send_rest_api',
                                     mock.Mock(return_value=lun_list))
        lun_result = self.as13000_san._get_lun_list(target_name)
        self.assertEqual(lun_list, lun_result)
        method = 'block/lun?name=%s' % target_name
        request_type = 'get'
        mock_rest.assert_called_once_with(method=method,
                                          request_type=request_type)

    @ddt.data(True, False)
    def test__check_volume(self, exist):
        volume = fake_volume.fake_volume_obj(self._ctxt, host='fakehost')
        mock_eh = self.mock_object(volume_utils,
                                   'extract_host',
                                   mock.Mock(return_value='fake_pool'))
        mock_tnd = self.mock_object(self.as13000_san,
                                    '_trans_name_down',
                                    mock.Mock(return_value='fake_name'))
        mock_el = self.mock_object(eventlet, 'sleep',
                                   mock.Mock(return_value=None))
        if exist:
            mock_gv = self.mock_object(self.as13000_san, '_get_volumes',
                                       mock.Mock(return_value=[
                                           {'name': 'fake_name'},
                                           {'name': 'fake_name2'}]))
        else:
            mock_gv = self.mock_object(self.as13000_san, '_get_volumes',
                                       mock.Mock(return_value=[
                                           {'name': 'fake_name2'},
                                           {'name': 'fake_name3'}]))
        expect = self.as13000_san._check_volume(volume)
        self.assertEqual(exist, expect)
        mock_eh.assert_called_once_with(volume.host, 'pool')
        mock_tnd.assert_called_once_with(volume.name)
        if exist:
            mock_gv.assert_called_once_with('fake_pool')
        else:
            mock_gv.assert_called()
            mock_el.assert_called()

    def test__get_volumes(self):
        volumes = [{'name': 'fake_name1'},
                   {'name': 'fake_name2'},
                   {'name': 'fake_name3'}]
        pool = 'fake_pool'
        mock_rest = self.mock_object(as13000_driver.RestAPIExecutor,
                                     'send_rest_api',
                                     mock.Mock(return_value=volumes))
        result = self.as13000_san._get_volumes(pool)
        method = 'block/lvm?pool=%s' % pool
        request_type = 'get'
        self.assertEqual(volumes, result)
        mock_rest.assert_called_once_with(method=method,
                                          request_type=request_type)

    def test__get_cluster_status(self):
        method = 'cluster/node'
        request_type = 'get'
        cluster = 'fake_cluster'
        mock_rest = self.mock_object(as13000_driver.RestAPIExecutor,
                                     'send_rest_api',
                                     mock.Mock(return_value=cluster))
        result = self.as13000_san._get_cluster_status()
        self.assertEqual(cluster, result)
        mock_rest.assert_called_once_with(method=method,
                                          request_type=request_type)

    @ddt.data(True, False)
    def test__get_lun_id(self, lun_exist):
        volume = fake_volume.fake_volume_obj(self._ctxt, host='fakehost')
        if lun_exist:
            lun_list = [{'id': '01', 'mappingLvm': r'fake_pool/fake_volume1'},
                        {'id': '02', 'mappingLvm': r'fake_pool/fake_volume2'}]
        else:
            lun_list = [{'id': '01', 'mappingLvm': r'fake_pool/fake_volume1'},
                        {'id': '02', 'mappingLvm': r'fake_pool/fake_volume0'}]

        mock_eh = self.mock_object(volume_utils,
                                   'extract_host',
                                   mock.Mock(return_value='fake_pool'))
        mock_tnd = self.mock_object(self.as13000_san,
                                    '_trans_name_down',
                                    mock.Mock(return_value='fake_volume2'))
        mock_gll = self.mock_object(self.as13000_san, '_get_lun_list',
                                    mock.Mock(return_value=lun_list))

        lun_id = self.as13000_san._get_lun_id(volume, 'fake_target')
        if lun_exist:
            self.assertEqual('02', lun_id)
        else:
            self.assertIsNone(lun_id)

        mock_eh.assert_called_once_with(volume.host, level='pool')
        mock_tnd.assert_called_once_with(volume.name)
        mock_gll.assert_called_once_with('fake_target')

    def test__trans_name_down(self):
        fake_name = 'test-abcd-1234_1234-234'
        expect = 'test_abcd_1234_1234_234'
        result = self.as13000_san._trans_name_down(fake_name)
        self.assertEqual(expect, result)

    @ddt.data('5000000000', '5000000k', '5000mb', '50G', '5TB', '5PB', '5EB')
    def test__unit_convert(self, capacity):
        trans = {'5000000000': '%.0f' % (float(5000000000) / (1024 ** 3)),
                 '5000000k': '%.0f' % (float(5000000) / (1024 ** 2)),
                 '5000mb': '%.0f' % (float(5000) / 1024),
                 '50G': '%.0f' % float(50),
                 '5TB': '%.0f' % (float(5) * 1024),
                 '5PB': '%.0f' % (float(5) * (1024 ** 2)),
                 '5EB': '%.0f' % (float(5) * (1024 ** 3))}
        expect = float(trans[capacity])
        result = self.as13000_san._unit_convert(capacity)
        self.assertEqual(expect, result)
