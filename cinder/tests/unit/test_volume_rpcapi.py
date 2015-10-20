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
import copy

from oslo_config import cfg
from oslo_serialization import jsonutils

from cinder import context
from cinder import db
from cinder import objects
from cinder import test
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder.tests.unit import utils as tests_utils
from cinder.volume import rpcapi as volume_rpcapi
from cinder.volume import utils


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
        vol['metadata'] = {"test_key": "test_val"}
        vol['size'] = 1
        volume = db.volume_create(self.context, vol)

        kwargs = {
            'status': "creating",
            'progress': '0%',
            'display_name': 'fake_name',
            'display_description': 'fake_description'}
        snapshot = tests_utils.create_snapshot(self.context, vol['id'],
                                               **kwargs)

        source_group = tests_utils.create_consistencygroup(
            self.context,
            availability_zone=CONF.storage_availability_zone,
            volume_type='type1,type2',
            host='fakehost@fakedrv#fakepool')

        cgsnapshot = tests_utils.create_cgsnapshot(
            self.context,
            consistencygroup_id=source_group.id)

        group = tests_utils.create_consistencygroup(
            self.context,
            availability_zone=CONF.storage_availability_zone,
            volume_type='type1,type2',
            host='fakehost@fakedrv#fakepool',
            cgsnapshot_id=cgsnapshot.id)

        group2 = tests_utils.create_consistencygroup(
            self.context,
            availability_zone=CONF.storage_availability_zone,
            volume_type='type1,type2',
            host='fakehost@fakedrv#fakepool',
            source_cgid=source_group.id)

        group = objects.ConsistencyGroup.get_by_id(self.context, group.id)
        group2 = objects.ConsistencyGroup.get_by_id(self.context, group2.id)
        cgsnapshot = objects.CGSnapshot.get_by_id(self.context, cgsnapshot.id)
        self.fake_volume = jsonutils.to_primitive(volume)
        self.fake_volume_metadata = volume["volume_metadata"]
        self.fake_snapshot = snapshot
        self.fake_reservations = ["RESERVATION"]
        self.fake_cg = group
        self.fake_cg2 = group2
        self.fake_src_cg = jsonutils.to_primitive(source_group)
        self.fake_cgsnap = cgsnapshot

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

        target = {
            "version": kwargs.pop('version', rpcapi.BASE_RPC_API_VERSION)
        }

        if 'request_spec' in kwargs:
            spec = jsonutils.to_primitive(kwargs['request_spec'])
            kwargs['request_spec'] = spec

        expected_msg = copy.deepcopy(kwargs)
        if 'volume' in expected_msg:
            volume = expected_msg['volume']
            del expected_msg['volume']
            expected_msg['volume_id'] = volume['id']
        if 'snapshot' in expected_msg:
            snapshot = expected_msg['snapshot']
            del expected_msg['snapshot']
            expected_msg['snapshot_id'] = snapshot.id
            expected_msg['snapshot'] = snapshot
        if 'cgsnapshot' in expected_msg:
            cgsnapshot = expected_msg['cgsnapshot']
            if cgsnapshot:
                cgsnapshot.consistencygroup
                kwargs['cgsnapshot'].consistencygroup
        if 'host' in expected_msg:
            del expected_msg['host']
        if 'dest_host' in expected_msg:
            dest_host = expected_msg['dest_host']
            dest_host_dict = {'host': dest_host.host,
                              'capabilities': dest_host.capabilities}
            del expected_msg['dest_host']
            expected_msg['host'] = dest_host_dict
        if 'new_volume' in expected_msg:
            volume = expected_msg['new_volume']
            del expected_msg['new_volume']
            expected_msg['new_volume_id'] = volume['id']

        if 'host' in kwargs:
            host = kwargs['host']
        elif 'group' in kwargs:
            host = kwargs['group']['host']
        elif 'volume' in kwargs:
            host = kwargs['volume']['host']
        elif 'snapshot' in kwargs:
            host = 'fake_host'
        elif 'cgsnapshot' in kwargs:
            host = kwargs['cgsnapshot'].consistencygroup.host

        target['server'] = utils.extract_host(host)
        target['topic'] = '%s.%s' % (CONF.volume_topic, host)

        self.fake_args = None
        self.fake_kwargs = None

        def _fake_prepare_method(*args, **kwds):
            for kwd in kwds:
                self.assertEqual(kwds[kwd], target[kwd])
            return rpcapi.client

        def _fake_rpc_method(*args, **kwargs):
            self.fake_args = args
            self.fake_kwargs = kwargs
            if expected_retval:
                return expected_retval

        self.stubs.Set(rpcapi.client, "prepare", _fake_prepare_method)
        self.stubs.Set(rpcapi.client, rpc_method, _fake_rpc_method)

        retval = getattr(rpcapi, method)(ctxt, **kwargs)

        self.assertEqual(expected_retval, retval)
        expected_args = [ctxt, method]

        for arg, expected_arg in zip(self.fake_args, expected_args):
            self.assertEqual(expected_arg, arg)

        for kwarg, value in self.fake_kwargs.items():
            if isinstance(value, objects.Snapshot):
                expected_snapshot = expected_msg[kwarg].obj_to_primitive()
                snapshot = value.obj_to_primitive()
                self.assertEqual(expected_snapshot, snapshot)
            elif isinstance(value, objects.ConsistencyGroup):
                expected_cg = expected_msg[kwarg].obj_to_primitive()
                cg = value.obj_to_primitive()
                self.assertEqual(expected_cg, cg)
            elif isinstance(value, objects.CGSnapshot):
                expected_cgsnapshot = expected_msg[kwarg].obj_to_primitive()
                cgsnapshot = value.obj_to_primitive()
                self.assertEqual(expected_cgsnapshot, cgsnapshot)
            else:
                self.assertEqual(expected_msg[kwarg], value)

    def test_create_consistencygroup(self):
        self._test_volume_api('create_consistencygroup', rpc_method='cast',
                              group=self.fake_cg, host='fake_host1',
                              version='1.26')

    def test_delete_consistencygroup(self):
        self._test_volume_api('delete_consistencygroup', rpc_method='cast',
                              group=self.fake_cg, version='1.26')

    def test_update_consistencygroup(self):
        self._test_volume_api('update_consistencygroup', rpc_method='cast',
                              group=self.fake_cg, add_volumes=['vol1'],
                              remove_volumes=['vol2'], version='1.26')

    def test_create_cgsnapshot(self):
        self._test_volume_api('create_cgsnapshot', rpc_method='cast',
                              cgsnapshot=self.fake_cgsnap, version='1.31')

    def test_delete_cgsnapshot(self):
        self._test_volume_api('delete_cgsnapshot', rpc_method='cast',
                              cgsnapshot=self.fake_cgsnap, version='1.31')

    def test_create_volume(self):
        self._test_volume_api('create_volume',
                              rpc_method='cast',
                              volume=self.fake_volume,
                              host='fake_host1',
                              request_spec='fake_request_spec',
                              filter_properties='fake_properties',
                              allow_reschedule=True,
                              version='1.24')

    def test_create_volume_serialization(self):
        request_spec = {"metadata": self.fake_volume_metadata}
        self._test_volume_api('create_volume',
                              rpc_method='cast',
                              volume=self.fake_volume,
                              host='fake_host1',
                              request_spec=request_spec,
                              filter_properties='fake_properties',
                              allow_reschedule=True,
                              version='1.24')

    def test_delete_volume(self):
        self._test_volume_api('delete_volume',
                              rpc_method='cast',
                              volume=self.fake_volume,
                              unmanage_only=False,
                              version='1.15')

    def test_create_snapshot(self):
        self._test_volume_api('create_snapshot',
                              rpc_method='cast',
                              volume=self.fake_volume,
                              snapshot=self.fake_snapshot)

    def test_delete_snapshot(self):
        self._test_volume_api('delete_snapshot',
                              rpc_method='cast',
                              snapshot=self.fake_snapshot,
                              host='fake_host',
                              unmanage_only=False)

    def test_delete_snapshot_with_unmanage_only(self):
        self._test_volume_api('delete_snapshot',
                              rpc_method='cast',
                              snapshot=self.fake_snapshot,
                              host='fake_host',
                              unmanage_only=True)

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
                              volume=self.fake_volume,
                              attachment_id='fake_uuid',
                              version="1.20")

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
                              rpc_method='call',
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
                              reservations=self.fake_reservations,
                              version='1.14')

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

    def test_retype(self):
        class FakeHost(object):
            def __init__(self):
                self.host = 'host'
                self.capabilities = {}
        dest_host = FakeHost()
        self._test_volume_api('retype',
                              rpc_method='cast',
                              volume=self.fake_volume,
                              new_type_id='fake',
                              dest_host=dest_host,
                              migration_policy='never',
                              reservations=None,
                              version='1.12')

    def test_manage_existing(self):
        self._test_volume_api('manage_existing',
                              rpc_method='cast',
                              volume=self.fake_volume,
                              ref={'lv_name': 'foo'},
                              version='1.15')

    def test_manage_existing_snapshot(self):
        volume_update = {'host': 'fake_host'}
        snpshot = {
            'id': 1,
            'volume_id': 'fake_id',
            'status': "creating",
            'progress': '0%',
            'volume_size': 0,
            'display_name': 'fake_name',
            'display_description': 'fake_description',
            'volume': fake_volume.fake_db_volume(**volume_update),
            'expected_attrs': ['volume'], }
        my_fake_snapshot_obj = fake_snapshot.fake_snapshot_obj(self.context,
                                                               **snpshot)
        self._test_volume_api('manage_existing_snapshot',
                              rpc_method='cast',
                              snapshot=my_fake_snapshot_obj,
                              ref='foo',
                              host='fake_host',
                              version='1.28')

    def test_promote_replica(self):
        self._test_volume_api('promote_replica',
                              rpc_method='cast',
                              volume=self.fake_volume,
                              version='1.17')

    def test_reenable_replica(self):
        self._test_volume_api('reenable_replication',
                              rpc_method='cast',
                              volume=self.fake_volume,
                              version='1.17')

    def test_create_consistencygroup_from_src_cgsnapshot(self):
        self._test_volume_api('create_consistencygroup_from_src',
                              rpc_method='cast',
                              group=self.fake_cg,
                              cgsnapshot=self.fake_cgsnap,
                              source_cg=None,
                              version='1.31')

    def test_create_consistencygroup_from_src_cg(self):
        self._test_volume_api('create_consistencygroup_from_src',
                              rpc_method='cast',
                              group=self.fake_cg2,
                              cgsnapshot=None,
                              source_cg=self.fake_src_cg,
                              version='1.31')

    def test_get_capabilities(self):
        self._test_volume_api('get_capabilities',
                              rpc_method='call',
                              host='fake_host',
                              discover=True,
                              version='1.29')

    def test_remove_export(self):
        self._test_volume_api('remove_export',
                              rpc_method='cast',
                              volume=self.fake_volume,
                              version='1.30')
