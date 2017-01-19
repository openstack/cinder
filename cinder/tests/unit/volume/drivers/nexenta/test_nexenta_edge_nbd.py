# Copyright 2016 Nexenta Systems, Inc.
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

import socket

import mock
from mock import patch
from oslo_serialization import jsonutils
from oslo_utils import units

from cinder import context
from cinder import exception
from cinder import test
from cinder.volume import configuration as conf
from cinder.volume.drivers.nexenta.nexentaedge import jsonrpc
from cinder.volume.drivers.nexenta.nexentaedge import nbd


class FakeResponse(object):

    def __init__(self, response):
        self.response = response
        super(FakeResponse, self).__init__()

    def json(self):
        return self.response

    def close(self):
        pass


class RequestParams(object):
    def __init__(self, scheme, host, port, user, password):
        self.scheme = scheme.lower()
        self.host = host
        self.port = port
        self.user = user
        self.password = password

    def url(self, path=''):
        return '%s://%s:%s/%s' % (
            self.scheme, self.host, self.port, path)

    def build_post_args(self, args):
        return jsonutils.dumps(args)


class TestNexentaEdgeNBDDriver(test.TestCase):

    def setUp(self):
        def _safe_get(opt):
            return getattr(self.cfg, opt)
        super(TestNexentaEdgeNBDDriver, self).setUp()
        self.cfg = mock.Mock(spec=conf.Configuration)
        self.cfg.safe_get = mock.Mock(side_effect=_safe_get)
        self.cfg.trace_flags = 'fake_trace_flags'
        self.cfg.driver_data_namespace = 'fake_driver_data_namespace'
        self.cfg.nexenta_rest_protocol = 'http'
        self.cfg.nexenta_rest_address = '127.0.0.1'
        self.cfg.nexenta_rest_port = 8080
        self.cfg.nexenta_rest_user = 'admin'
        self.cfg.nexenta_rest_password = '0'
        self.cfg.nexenta_lun_container = 'cluster/tenant/bucket'
        self.cfg.nexenta_nbd_symlinks_dir = '/dev/disk/by-path'
        self.cfg.volume_dd_blocksize = 512
        self.cfg.nexenta_blocksize = 512
        self.cfg.nexenta_chunksize = 4096
        self.cfg.reserved_percentage = 0
        self.cfg.replication_device = []

        self.ctx = context.get_admin_context()
        self.drv = nbd.NexentaEdgeNBDDriver(configuration=self.cfg)

        session = mock.Mock()
        session.get = mock.Mock()
        session.post = mock.Mock()
        session.put = mock.Mock()
        session.delete = mock.Mock()
        self.drv.do_setup(self.ctx)
        self.drv.restapi.session = session
        self.mock_api = session

        self.request_params = RequestParams(
            'http', self.cfg.nexenta_rest_address, self.cfg.nexenta_rest_port,
            self.cfg.nexenta_rest_user, self.cfg.nexenta_rest_password)

    def test_check_do_setup__symlinks_dir_not_specified(self):
        self.drv.symlinks_dir = None
        self.assertRaises(
            exception.NexentaException, self.drv.check_for_setup_error)

    def test_check_do_setup__symlinks_dir_doesnt_exist(self):
        self.drv.symlinks_dir = '/some/random/path'
        self.assertRaises(
            exception.NexentaException, self.drv.check_for_setup_error)

    @patch('os.path.exists')
    def test_check_do_setup__empty_response(self, exists):
        self.mock_api.get.return_value = FakeResponse({})
        exists.return_value = True
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.drv.check_for_setup_error)

    @patch('os.path.exists')
    def test_check_do_setup(self, exists):
        self.mock_api.get.return_value = FakeResponse({'response': 'OK'})
        exists.return_value = True
        self.drv.check_for_setup_error()
        self.mock_api.get.assert_any_call(
            self.request_params.url(self.drv.bucket_url + '/objects/'),
            timeout=jsonrpc.TIMEOUT)

    def test_local_path__error(self):
        self.drv._get_nbd_number = lambda volume_: -1
        volume = {'name': 'volume'}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.drv.local_path, volume)

    def test_local_path(self):
        volume = {
            'name': 'volume',
            'host': 'myhost@backend#pool'
        }
        _get_host_info__response = {
            'stats': {
                'servers': {
                    'host1': {
                        'hostname': 'host1',
                        'ipv6addr': 'fe80::fc16:3eff:fedb:bd69'},
                    'host2': {
                        'hostname': 'myhost',
                        'ipv6addr': 'fe80::fc16:3eff:fedb:bd68'}
                }
            }
        }
        _get_nbd_devices__response = {
            'value': jsonutils.dumps([
                {
                    'objectPath': '/'.join(
                        (self.cfg.nexenta_lun_container, 'some_volume')),
                    'number': 1
                },
                {
                    'objectPath': '/'.join(
                        (self.cfg.nexenta_lun_container, volume['name'])),
                    'number': 2
                }
            ])
        }

        def my_side_effect(*args, **kwargs):
            if args[0] == self.request_params.url('system/stats'):
                return FakeResponse({'response': _get_host_info__response})
            elif args[0].startswith(
                    self.request_params.url('sysconfig/nbd/devices')):
                return FakeResponse({'response': _get_nbd_devices__response})
            else:
                raise Exception('Unexpected request')

        self.mock_api.get.side_effect = my_side_effect
        self.drv.local_path(volume)

    def test_local_path__host_not_found(self):
        volume = {
            'name': 'volume',
            'host': 'unknown-host@backend#pool'
        }
        _get_host_info__response = {
            'stats': {
                'servers': {
                    'host1': {
                        'hostname': 'host1',
                        'ipv6addr': 'fe80::fc16:3eff:fedb:bd69'},
                    'host2': {
                        'hostname': 'myhost',
                        'ipv6addr': 'fe80::fc16:3eff:fedb:bd68'}
                }
            }
        }
        _get_nbd_devices__response = {
            'value': jsonutils.dumps([
                {
                    'objectPath': '/'.join(
                        (self.cfg.nexenta_lun_container, 'some_volume')),
                    'number': 1
                },
                {
                    'objectPath': '/'.join(
                        (self.cfg.nexenta_lun_container, volume['name'])),
                    'number': 2
                }
            ])
        }

        def my_side_effect(*args, **kwargs):
            if args[0] == self.request_params.url('system/stats'):
                return FakeResponse({'response': _get_host_info__response})
            elif args[0].startswith(
                    self.request_params.url('sysconfig/nbd/devices')):
                return FakeResponse({'response': _get_nbd_devices__response})
            else:
                raise Exception('Unexpected request')

        self.mock_api.get.side_effect = my_side_effect
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.drv.local_path, volume)

    @patch('cinder.utils.execute')
    def test_create_volume(self, execute):
        self.mock_api.post.returning_value = FakeResponse({})
        volume = {
            'host': 'host@backend#pool info',
            'size': 1,
            'name': 'volume'
        }
        number = 5
        remote_url = ''
        self.drv._get_remote_url = lambda host_: remote_url
        self.drv._get_nbd_number = lambda volume_: number
        self.drv.create_volume(volume)
        self.mock_api.post.assert_called_with(
            self.request_params.url('nbd' + remote_url),
            data=self.request_params.build_post_args({
                'objectPath': '/'.join((self.cfg.nexenta_lun_container,
                                        volume['name'])),
                'volSizeMB': volume['size'] * units.Ki,
                'blockSize': self.cfg.nexenta_blocksize,
                'chunkSize': self.cfg.nexenta_chunksize}),
            timeout=jsonrpc.TIMEOUT)

    def test_delete_volume(self):
        self.mock_api.delete.returning_value = FakeResponse({})
        volume = {
            'host': 'host@backend#pool info',
            'size': 1,
            'name': 'volume'
        }
        number = 5
        remote_url = ''
        self.drv._get_remote_url = lambda host_: remote_url
        self.drv._get_nbd_number = lambda volume_: number
        self.drv.delete_volume(volume)
        self.mock_api.delete.assert_called_with(
            self.request_params.url('nbd' + remote_url),
            data=self.request_params.build_post_args({
                'objectPath': '/'.join((self.cfg.nexenta_lun_container,
                                        volume['name'])),
                'number': number}),
            timeout=jsonrpc.TIMEOUT)

    def test_delete_volume__not_found(self):
        self.mock_api.delete.returning_value = FakeResponse({})
        volume = {
            'host': 'host@backend#pool info',
            'size': 1,
            'name': 'volume'
        }
        remote_url = ''
        self.drv._get_remote_url = lambda host_: remote_url
        self.drv._get_nbd_number = lambda volume_: -1
        self.drv.delete_volume(volume)
        self.mock_api.delete.assert_not_called()

    def test_extend_volume(self):
        self.mock_api.put.returning_value = FakeResponse({})
        volume = {
            'host': 'host@backend#pool info',
            'size': 1,
            'name': 'volume'
        }
        new_size = 5
        remote_url = ''
        self.drv._get_remote_url = lambda host_: remote_url
        self.drv.extend_volume(volume, new_size)
        self.mock_api.put.assert_called_with(
            self.request_params.url('nbd/resize' + remote_url),
            data=self.request_params.build_post_args({
                'objectPath': '/'.join((self.cfg.nexenta_lun_container,
                                        volume['name'])),
                'newSizeMB': new_size * units.Ki}),
            timeout=jsonrpc.TIMEOUT)

    def test_create_snapshot(self):
        self.mock_api.post.returning_value = FakeResponse({})
        snapshot = {
            'name': 'dsfsdsdgfdf',
            'volume_name': 'volume'
        }
        self.drv.create_snapshot(snapshot)
        self.mock_api.post.assert_called_with(
            self.request_params.url('nbd/snapshot'),
            data=self.request_params.build_post_args({
                'objectPath': '/'.join((self.cfg.nexenta_lun_container,
                                        snapshot['volume_name'])),
                'snapName': snapshot['name']}),
            timeout=jsonrpc.TIMEOUT)

    def test_delete_snapshot(self):
        self.mock_api.delete.returning_value = FakeResponse({})
        snapshot = {
            'name': 'dsfsdsdgfdf',
            'volume_name': 'volume'
        }
        self.drv.delete_snapshot(snapshot)
        self.mock_api.delete.assert_called_with(
            self.request_params.url('nbd/snapshot'),
            data=self.request_params.build_post_args({
                'objectPath': '/'.join((self.cfg.nexenta_lun_container,
                                        snapshot['volume_name'])),
                'snapName': snapshot['name']}),
            timeout=jsonrpc.TIMEOUT)

    def test_create_volume_from_snapshot(self):
        self.mock_api.put.returning_value = FakeResponse({})
        snapshot = {
            'name': 'dsfsdsdgfdf',
            'volume_size': 1,
            'volume_name': 'volume'
        }
        volume = {
            'host': 'host@backend#pool info',
            'size': 2,
            'name': 'volume'
        }
        remote_url = ''
        self.drv._get_remote_url = lambda host_: remote_url
        self.drv.extend_volume = lambda v, s: None
        self.drv.create_volume_from_snapshot(volume, snapshot)
        self.mock_api.put.assert_called_with(
            self.request_params.url('nbd/snapshot/clone' + remote_url),
            data=self.request_params.build_post_args({
                'objectPath': '/'.join((self.cfg.nexenta_lun_container,
                                        snapshot['volume_name'])),
                'snapName': snapshot['name'],
                'clonePath': '/'.join((self.cfg.nexenta_lun_container,
                                       volume['name']))
            }),
            timeout=jsonrpc.TIMEOUT)

    def test_create_cloned_volume(self):
        self.mock_api.post.returning_value = FakeResponse({})
        volume = {
            'host': 'host@backend#pool info',
            'size': 1,
            'name': 'volume'
        }
        src_vref = {
            'size': 1,
            'name': 'qwerty'
        }
        container = self.cfg.nexenta_lun_container
        remote_url = ''
        self.drv._get_remote_url = lambda host_: remote_url
        self.drv.create_cloned_volume(volume, src_vref)
        self.mock_api.post.assert_called_with(
            self.request_params.url('nbd' + remote_url),
            data=self.request_params.build_post_args({
                'objectPath': '/'.join((container, volume['name'])),
                'volSizeMB': src_vref['size'] * units.Ki,
                'blockSize': self.cfg.nexenta_blocksize,
                'chunkSize': self.cfg.nexenta_chunksize
            }),
            timeout=jsonrpc.TIMEOUT)

    def test_create_cloned_volume_gt_src(self):
        self.mock_api.post.returning_value = FakeResponse({})
        volume = {
            'host': 'host@backend#pool info',
            'size': 2,
            'name': 'volume'
        }
        src_vref = {
            'size': 1,
            'name': 'qwerty'
        }
        container = self.cfg.nexenta_lun_container
        remote_url = ''
        self.drv._get_remote_url = lambda host_: remote_url
        self.drv.create_cloned_volume(volume, src_vref)
        self.mock_api.post.assert_called_with(
            self.request_params.url('nbd' + remote_url),
            data=self.request_params.build_post_args({
                'objectPath': '/'.join((container, volume['name'])),
                'volSizeMB': volume['size'] * units.Ki,
                'blockSize': self.cfg.nexenta_blocksize,
                'chunkSize': self.cfg.nexenta_chunksize
            }),
            timeout=jsonrpc.TIMEOUT)

    def test_get_volume_stats(self):
        self.cfg.volume_backend_name = None
        self.mock_api.get.return_value = FakeResponse({
            'response': {
                'stats': {
                    'summary': {
                        'total_capacity': units.Gi,
                        'total_available': units.Gi
                    }
                }
            }
        })
        location_info = '%(driver)s:%(host)s:%(bucket)s' % {
            'driver': self.drv.__class__.__name__,
            'host': socket.gethostname(),
            'bucket': self.cfg.nexenta_lun_container
        }
        expected = {
            'vendor_name': 'Nexenta',
            'driver_version': self.drv.VERSION,
            'storage_protocol': 'NBD',
            'reserved_percentage': self.cfg.reserved_percentage,
            'total_capacity_gb': 1,
            'free_capacity_gb': 1,
            'QoS_support': False,
            'volume_backend_name': self.drv.__class__.__name__,
            'location_info': location_info,
            'restapi_url': '%s://%s:%s/' % (
                'http', self.cfg.nexenta_rest_address,
                self.cfg.nexenta_rest_port)
        }

        self.assertEqual(expected, self.drv.get_volume_stats())

    @patch('cinder.image.image_utils.fetch_to_raw')
    def test_copy_image_to_volume(self, fetch_to_raw):
        volume = {
            'host': 'host@backend#pool info',
            'size': 1,
            'name': 'volume'
        }
        self.drv.local_path = lambda host: 'local_path'
        self.drv.copy_image_to_volume(self.ctx, volume, 'image_service',
                                      'image_id')
        fetch_to_raw.assert_called_with(
            self.ctx, 'image_service', 'image_id', 'local_path',
            self.cfg.volume_dd_blocksize, size=volume['size'])

    @patch('cinder.image.image_utils.upload_volume')
    def test_copy_volume_to_image(self, upload_volume):
        volume = {
            'host': 'host@backend#pool info',
            'size': 1,
            'name': 'volume'
        }
        self.drv.local_path = lambda host: 'local_path'
        self.drv.copy_volume_to_image(self.ctx, volume, 'image_service',
                                      'image_meta')
        upload_volume.assert_called_with(
            self.ctx, 'image_service', 'image_meta', 'local_path')

    def test_validate_connector(self):
        connector = {'host': 'host2'}
        r = {
            'stats': {
                'servers': {
                    'host1': {'hostname': 'host1'},
                    'host2': {'hostname': 'host2'}
                }
            }
        }
        self.mock_api.get.return_value = FakeResponse({'response': r})
        self.drv.validate_connector(connector)
        self.mock_api.get.assert_called_with(
            self.request_params.url('system/stats'),
            timeout=jsonrpc.TIMEOUT)

    def test_validate_connector__host_not_found(self):
        connector = {'host': 'host3'}
        r = {
            'stats': {
                'servers': {
                    'host1': {'hostname': 'host1'},
                    'host2': {'hostname': 'host2'}
                }
            }
        }
        self.mock_api.get.return_value = FakeResponse({'response': r})
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.drv.validate_connector, connector)

    def test_initialize_connection(self):
        connector = {'host': 'host'}
        volume = {
            'host': 'host@backend#pool info',
            'size': 1,
            'name': 'volume'
        }
        self.drv.local_path = lambda host: 'local_path'
        self.assertEqual({
            'driver_volume_type': 'local',
            'data': {'device_path': 'local_path'}},
            self.drv.initialize_connection(volume, connector))
