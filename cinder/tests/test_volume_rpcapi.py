# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012, Intel, Inc.
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
Unit Tests for cinder.volume.rpcapi
"""


from oslo.config import cfg

from cinder import context
from cinder import db
from cinder.openstack.common import jsonutils
from cinder.openstack.common import rpc
from cinder import test
from cinder.volume import rpcapi as volume_rpcapi


CONF = cfg.CONF


class VolumeRpcAPITestCase(test.TestCase):

    def setUp(self):
        super(VolumeRpcAPITestCase, self).setUp()
        self.context = context.get_admin_context()
        vol = {}
        vol['host'] = 'fake_host'
        vol['availability_zone'] = CONF.storage_availability_zone
        vol['status'] = "available"
        vol['attach_status'] = "detached"
        volume = db.volume_create(self.context, vol)

        snpshot = {
            'volume_id': 'fake_id',
            'status': "creating",
            'progress': '0%',
            'volume_size': 0,
            'display_name': 'fake_name',
            'display_description': 'fake_description'}
        snapshot = db.snapshot_create(self.context, snpshot)
        self.fake_volume = jsonutils.to_primitive(volume)
        self.fake_snapshot = jsonutils.to_primitive(snapshot)

    def test_serialized_volume_has_id(self):
        self.assertIn('id', self.fake_volume)

    def _test_volume_api(self, method, rpc_method, **kwargs):
        ctxt = context.RequestContext('fake_user', 'fake_project')

        if 'rpcapi_class' in kwargs:
            rpcapi_class = kwargs['rpcapi_class']
            del kwargs['rpcapi_class']
        else:
            rpcapi_class = volume_rpcapi.VolumeAPI
        rpcapi = rpcapi_class()
        expected_retval = 'foo' if method == 'call' else None

        expected_version = kwargs.pop('version', rpcapi.BASE_RPC_API_VERSION)
        expected_msg = rpcapi.make_msg(method, **kwargs)
        if 'volume' in expected_msg['args']:
            volume = expected_msg['args']['volume']
            del expected_msg['args']['volume']
            expected_msg['args']['volume_id'] = volume['id']
        if 'snapshot' in expected_msg['args']:
            snapshot = expected_msg['args']['snapshot']
            del expected_msg['args']['snapshot']
            expected_msg['args']['snapshot_id'] = snapshot['id']
        if 'host' in expected_msg['args']:
            del expected_msg['args']['host']
        if 'dest_host' in expected_msg['args']:
            dest_host = expected_msg['args']['dest_host']
            dest_host_dict = {'host': dest_host.host,
                              'capabilities': dest_host.capabilities}
            del expected_msg['args']['dest_host']
            expected_msg['args']['host'] = dest_host_dict
        if 'new_volume' in expected_msg['args']:
            volume = expected_msg['args']['new_volume']
            del expected_msg['args']['new_volume']
            expected_msg['args']['new_volume_id'] = volume['id']

        expected_msg['version'] = expected_version

        if 'host' in kwargs:
            host = kwargs['host']
        else:
            host = kwargs['volume']['host']
        expected_topic = '%s:%s' % (CONF.volume_topic, host)

        self.fake_args = None
        self.fake_kwargs = None

        def _fake_rpc_method(*args, **kwargs):
            self.fake_args = args
            self.fake_kwargs = kwargs
            if expected_retval:
                return expected_retval

        self.stubs.Set(rpc, rpc_method, _fake_rpc_method)

        retval = getattr(rpcapi, method)(ctxt, **kwargs)

        self.assertEqual(retval, expected_retval)
        expected_args = [ctxt, expected_topic, expected_msg]
        for arg, expected_arg in zip(self.fake_args, expected_args):
            self.assertEqual(arg, expected_arg)

    def test_create_volume(self):
        self._test_volume_api('create_volume',
                              rpc_method='cast',
                              volume=self.fake_volume,
                              host='fake_host1',
                              request_spec='fake_request_spec',
                              filter_properties='fake_properties',
                              allow_reschedule=True,
                              snapshot_id='fake_snapshot_id',
                              image_id='fake_image_id',
                              source_volid='fake_src_id',
                              version='1.4')

    def test_delete_volume(self):
        self._test_volume_api('delete_volume',
                              rpc_method='cast',
                              volume=self.fake_volume)

    def test_create_snapshot(self):
        self._test_volume_api('create_snapshot',
                              rpc_method='cast',
                              volume=self.fake_volume,
                              snapshot=self.fake_snapshot)

    def test_delete_snapshot(self):
        self._test_volume_api('delete_snapshot',
                              rpc_method='cast',
                              snapshot=self.fake_snapshot,
                              host='fake_host')

    def test_attach_volume_to_instance(self):
        self._test_volume_api('attach_volume',
                              rpc_method='call',
                              volume=self.fake_volume,
                              instance_uuid='fake_uuid',
                              host_name=None,
                              mountpoint='fake_mountpoint',
                              mode='ro',
                              version='1.11')

    def test_attach_volume_to_host(self):
        self._test_volume_api('attach_volume',
                              rpc_method='call',
                              volume=self.fake_volume,
                              instance_uuid=None,
                              host_name='fake_host',
                              mountpoint='fake_mountpoint',
                              mode='rw',
                              version='1.11')

    def test_detach_volume(self):
        self._test_volume_api('detach_volume',
                              rpc_method='call',
                              volume=self.fake_volume)

    def test_copy_volume_to_image(self):
        self._test_volume_api('copy_volume_to_image',
                              rpc_method='cast',
                              volume=self.fake_volume,
                              image_meta={'id': 'fake_image_id',
                                          'container_format': 'fake_type',
                                          'disk_format': 'fake_type'},
                              version='1.3')

    def test_initialize_connection(self):
        self._test_volume_api('initialize_connection',
                              rpc_method='call',
                              volume=self.fake_volume,
                              connector='fake_connector')

    def test_terminate_connection(self):
        self._test_volume_api('terminate_connection',
                              rpc_method='call',
                              volume=self.fake_volume,
                              connector='fake_connector',
                              force=False)

    def test_accept_transfer(self):
        self._test_volume_api('accept_transfer',
                              rpc_method='cast',
                              volume=self.fake_volume,
                              new_user='e5565fd0-06c8-11e3-'
                                       '8ffd-0800200c9b77',
                              new_project='e4465fd0-06c8-11e3'
                                          '-8ffd-0800200c9a66',
                              version='1.9')

    def test_extend_volume(self):
        self._test_volume_api('extend_volume',
                              rpc_method='cast',
                              volume=self.fake_volume,
                              new_size=1,
                              version='1.6')

    def test_migrate_volume(self):
        class FakeHost(object):
            def __init__(self):
                self.host = 'host'
                self.capabilities = {}
        dest_host = FakeHost()
        self._test_volume_api('migrate_volume',
                              rpc_method='cast',
                              volume=self.fake_volume,
                              dest_host=dest_host,
                              force_host_copy=True,
                              version='1.8')

    def test_migrate_volume_completion(self):
        self._test_volume_api('migrate_volume_completion',
                              rpc_method='call',
                              volume=self.fake_volume,
                              new_volume=self.fake_volume,
                              error=False,
                              version='1.10')
