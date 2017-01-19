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

import ddt
import mock
from oslo_config import cfg
from oslo_serialization import jsonutils

from cinder.common import constants
from cinder import context
from cinder import db
from cinder import exception
from cinder import objects
from cinder.objects import base as ovo_base
from cinder.objects import fields
from cinder import test
from cinder.tests.unit.backup import fake_backup
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_service
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder.tests.unit import utils as tests_utils
from cinder.volume import rpcapi as volume_rpcapi
from cinder.volume import utils


CONF = cfg.CONF


@ddt.ddt
class VolumeRpcAPITestCase(test.TestCase):

    def setUp(self):
        super(VolumeRpcAPITestCase, self).setUp()
        self.context = context.get_admin_context()
        vol = {}
        vol['host'] = 'fake_host'
        vol['availability_zone'] = CONF.storage_availability_zone
        vol['status'] = "available"
        vol['attach_status'] = fields.VolumeAttachStatus.DETACHED
        vol['metadata'] = {"test_key": "test_val"}
        vol['size'] = 1
        volume = db.volume_create(self.context, vol)

        kwargs = {
            'status': fields.SnapshotStatus.CREATING,
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

        cg = tests_utils.create_consistencygroup(
            self.context,
            availability_zone=CONF.storage_availability_zone,
            volume_type='type1,type2',
            host='fakehost@fakedrv#fakepool',
            cgsnapshot_id=cgsnapshot.id)

        cg2 = tests_utils.create_consistencygroup(
            self.context,
            availability_zone=CONF.storage_availability_zone,
            volume_type='type1,type2',
            host='fakehost@fakedrv#fakepool',
            source_cgid=source_group.id)

        generic_group = tests_utils.create_group(
            self.context,
            availability_zone=CONF.storage_availability_zone,
            group_type_id=fake.GROUP_TYPE_ID,
            host='fakehost@fakedrv#fakepool')

        group_snapshot = tests_utils.create_group_snapshot(
            self.context,
            group_id=generic_group.id,
            group_type_id=fake.GROUP_TYPE_ID)

        cg = objects.ConsistencyGroup.get_by_id(self.context, cg.id)
        cg2 = objects.ConsistencyGroup.get_by_id(self.context, cg2.id)
        cgsnapshot = objects.CGSnapshot.get_by_id(self.context, cgsnapshot.id)
        self.fake_volume = jsonutils.to_primitive(volume)
        self.fake_volume_obj = fake_volume.fake_volume_obj(self.context, **vol)
        self.fake_volume_metadata = volume["volume_metadata"]
        self.fake_snapshot = snapshot
        self.fake_reservations = ["RESERVATION"]
        self.fake_cg = cg
        self.fake_cg2 = cg2
        self.fake_src_cg = source_group
        self.fake_cgsnap = cgsnapshot
        self.fake_backup_obj = fake_backup.fake_backup_obj(self.context)
        self.fake_group = generic_group
        self.fake_group_snapshot = group_snapshot

        self.addCleanup(self._cleanup)

        self.can_send_version_mock = self.patch(
            'oslo_messaging.RPCClient.can_send_version',
            return_value=True)

    def _cleanup(self):
        self.fake_snapshot.destroy()
        self.fake_volume_obj.destroy()
        self.fake_group_snapshot.destroy()
        self.fake_group.destroy()
        self.fake_cgsnap.destroy()
        self.fake_cg2.destroy()
        self.fake_cg.destroy()

    def test_serialized_volume_has_id(self):
        self.assertIn('id', self.fake_volume)

    def _get_expected_msg(self, kwargs):
        update = kwargs.pop('_expected_msg', {})
        expected_msg = copy.deepcopy(kwargs)
        if 'volume' in expected_msg:
            volume = expected_msg.pop('volume')
            # NOTE(thangp): copy.deepcopy() is making oslo_versionedobjects
            # think that 'metadata' was changed.
            if isinstance(volume, objects.Volume):
                volume.obj_reset_changes()
            expected_msg['volume_id'] = volume['id']
            expected_msg['volume'] = volume
        if 'snapshot' in expected_msg:
            snapshot = expected_msg['snapshot']
            if isinstance(snapshot, objects.Snapshot) and 'volume' in snapshot:
                snapshot.volume.obj_reset_changes()
            expected_msg['snapshot_id'] = snapshot.id
        if 'cgsnapshot' in expected_msg:
            cgsnapshot = expected_msg['cgsnapshot']
            if cgsnapshot:
                cgsnapshot.consistencygroup
                kwargs['cgsnapshot'].consistencygroup
        if 'backup' in expected_msg:
            backup = expected_msg.pop('backup')
            expected_msg['backup_id'] = backup.id
            expected_msg['backup'] = backup

        if 'host' in expected_msg:
            del expected_msg['host']
        if 'dest_backend' in expected_msg:
            dest_backend = expected_msg.pop('dest_backend')
            dest_backend_dict = {'host': dest_backend.host,
                                 'cluster_name': dest_backend.cluster_name,
                                 'capabilities': dest_backend.capabilities}
            expected_msg['host'] = dest_backend_dict
        if 'force_copy' in expected_msg:
            expected_msg['force_host_copy'] = expected_msg.pop('force_copy')
        if 'new_volume' in expected_msg:
            volume = expected_msg['new_volume']
            expected_msg['new_volume_id'] = volume['id']
        expected_msg.update(update)
        return expected_msg

    def _test_volume_api(self, method, rpc_method, _expected_method=None,
                         **kwargs):
        ctxt = context.RequestContext('fake_user', 'fake_project')

        if 'rpcapi_class' in kwargs:
            rpcapi_class = kwargs.pop('rpcapi_class')
        else:
            rpcapi_class = volume_rpcapi.VolumeAPI
        rpcapi = rpcapi_class()
        expected_retval = {} if rpc_method == 'call' else None

        target = {
            "version": kwargs.pop('version', rpcapi.RPC_API_VERSION)
        }

        if 'request_spec' in kwargs:
            spec = jsonutils.to_primitive(kwargs['request_spec'])
            kwargs['request_spec'] = spec

        expected_msg = self._get_expected_msg(kwargs)

        if 'host' in kwargs:
            host = kwargs['host']
        elif 'backend_id' in kwargs:
            host = kwargs['backend_id']
        elif 'group' in kwargs:
            host = kwargs['group'].service_topic_queue
        elif 'volume' in kwargs:
            vol = kwargs['volume']
            host = vol.service_topic_queue
        elif 'snapshot' in kwargs:
            host = 'fake_host'
        elif 'cgsnapshot' in kwargs:
            host = kwargs['cgsnapshot'].consistencygroup.service_topic_queue
        elif 'service' in kwargs:
            host = kwargs['service'].service_topic_queue

        target['server'] = utils.extract_host(host, 'host')
        target['topic'] = '%s.%s' % (constants.VOLUME_TOPIC,
                                     utils.extract_host(host))

        self.fake_args = None
        self.fake_kwargs = None

        def _fake_prepare_method(*args, **kwds):
            for kwd in kwds:
                self.assertEqual(kwds[kwd], target[kwd])
            return rpcapi.client

        def _fake_rpc_method(*args, **kwargs):
            self.fake_args = args
            kwargs.pop('want_objects', None)
            self.fake_kwargs = kwargs
            if expected_retval is not None:
                return expected_retval

        self.mock_object(rpcapi.client, "prepare", _fake_prepare_method)
        self.mock_object(rpcapi.client, rpc_method, _fake_rpc_method)

        retval = getattr(rpcapi, method)(ctxt, **kwargs)

        self.assertEqual(expected_retval, retval)
        expected_args = [ctxt, _expected_method or method]

        for arg, expected_arg in zip(self.fake_args, expected_args):
            self.assertEqual(expected_arg, arg)

        for kwarg, value in self.fake_kwargs.items():
            if isinstance(value, ovo_base.CinderObject):
                expected = expected_msg[kwarg].obj_to_primitive()
                primitive = value.obj_to_primitive()
                self.assertEqual(expected, primitive)

            else:
                self.assertEqual(expected_msg[kwarg], value)

    def _test_group_api(self, method, rpc_method, **kwargs):
        ctxt = context.RequestContext('fake_user', 'fake_project')

        if 'rpcapi_class' in kwargs:
            rpcapi_class = kwargs['rpcapi_class']
            del kwargs['rpcapi_class']
        else:
            rpcapi_class = volume_rpcapi.VolumeAPI
        rpcapi = rpcapi_class()
        expected_retval = 'foo' if method == 'call' else None

        target = {
            "version": kwargs.pop('version', rpcapi.RPC_API_VERSION)
        }

        if 'request_spec' in kwargs:
            spec = jsonutils.to_primitive(kwargs['request_spec'])
            kwargs['request_spec'] = spec

        expected_msg = copy.deepcopy(kwargs)
        if 'host' in expected_msg:
            del expected_msg['host']
        if 'group_snapshot' in expected_msg:
            group_snapshot = expected_msg['group_snapshot']
            if group_snapshot:
                group_snapshot.group
                kwargs['group_snapshot'].group

        if 'host' in kwargs:
            host = kwargs['host']
        elif 'group' in kwargs:
            host = kwargs['group'].service_topic_queue
        elif 'group_snapshot' in kwargs:
            host = kwargs['group_snapshot'].service_topic_queue

        target['server'] = utils.extract_host(host, 'host')
        target['topic'] = '%s.%s' % (constants.VOLUME_TOPIC,
                                     utils.extract_host(host))

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
            if isinstance(value, objects.Group):
                expected_group = expected_msg[kwarg].obj_to_primitive()
                group = value.obj_to_primitive()
                self.assertEqual(expected_group, group)
            elif isinstance(value, objects.GroupSnapshot):
                expected_grp_snap = expected_msg[kwarg].obj_to_primitive()
                grp_snap = value.obj_to_primitive()
                self.assertEqual(expected_grp_snap, grp_snap)
            else:
                self.assertEqual(expected_msg[kwarg], value)

    def test_create_consistencygroup(self):
        self._test_volume_api('create_consistencygroup', rpc_method='cast',
                              group=self.fake_cg, version='3.0')

    def test_delete_consistencygroup(self):
        self._test_volume_api('delete_consistencygroup', rpc_method='cast',
                              group=self.fake_cg, version='3.0')

    def test_delete_consistencygroup_cluster(self):
        self._set_cluster()
        self._test_volume_api('delete_consistencygroup', rpc_method='cast',
                              group=self.fake_src_cg, version='3.0')

    @ddt.data(None, 'my_cluster')
    def test_update_consistencygroup(self, cluster_name):
        self._change_cluster_name(self.fake_cg, cluster_name)
        self._test_volume_api('update_consistencygroup', rpc_method='cast',
                              group=self.fake_cg, add_volumes=['vol1'],
                              remove_volumes=['vol2'], version='3.0')

    @ddt.data(None, 'my_cluster')
    def test_create_cgsnapshot(self, cluster_name):
        self._change_cluster_name(self.fake_cgsnap.consistencygroup,
                                  cluster_name)
        self._test_volume_api('create_cgsnapshot', rpc_method='cast',
                              cgsnapshot=self.fake_cgsnap, version='3.0')

    def test_delete_cgsnapshot(self):
        self._set_cluster()
        self._test_volume_api('delete_cgsnapshot', rpc_method='cast',
                              cgsnapshot=self.fake_cgsnap, version='3.0')

    def test_create_volume(self):
        self._test_volume_api('create_volume',
                              rpc_method='cast',
                              volume=self.fake_volume_obj,
                              request_spec='fake_request_spec',
                              filter_properties='fake_properties',
                              allow_reschedule=True,
                              version='3.0')

    def test_delete_volume(self):
        self._test_volume_api('delete_volume',
                              rpc_method='cast',
                              volume=self.fake_volume_obj,
                              unmanage_only=False,
                              cascade=False,
                              version='3.0')

    def test_delete_volume_cluster(self):
        self._set_cluster()
        self._test_volume_api('delete_volume',
                              rpc_method='cast',
                              volume=self.fake_volume_obj,
                              unmanage_only=False,
                              cascade=False,
                              version='3.0')

    def test_delete_volume_cascade(self):
        self._test_volume_api('delete_volume',
                              rpc_method='cast',
                              volume=self.fake_volume_obj,
                              unmanage_only=False,
                              cascade=True,
                              version='3.0')

    @ddt.data(None, 'mycluster')
    def test_create_snapshot(self, cluster_name):
        self._change_cluster_name(self.fake_volume_obj, cluster_name)
        self._test_volume_api('create_snapshot',
                              rpc_method='cast',
                              volume=self.fake_volume_obj,
                              snapshot=self.fake_snapshot,
                              version='3.0')

    def test_delete_snapshot(self):
        self.fake_snapshot.volume
        self._test_volume_api('delete_snapshot',
                              rpc_method='cast',
                              snapshot=self.fake_snapshot,
                              unmanage_only=False,
                              version='3.0')

    def test_delete_snapshot_cluster(self):
        self._set_cluster()
        self.fake_snapshot.volume
        self._test_volume_api('delete_snapshot',
                              rpc_method='cast',
                              snapshot=self.fake_snapshot,
                              unmanage_only=False,
                              version='3.0')

    def test_delete_snapshot_with_unmanage_only(self):
        self.fake_snapshot.volume.metadata
        self._test_volume_api('delete_snapshot',
                              rpc_method='cast',
                              snapshot=self.fake_snapshot,
                              unmanage_only=True,
                              version='3.0')

    @ddt.data('3.0', '3.3')
    def test_attach_volume_to_instance(self, version):
        self.can_send_version_mock.return_value = (version == '3.3')
        self._test_volume_api('attach_volume',
                              rpc_method='call',
                              volume=self.fake_volume_obj,
                              instance_uuid='fake_uuid',
                              host_name=None,
                              mountpoint='fake_mountpoint',
                              mode='ro',
                              version=version)

    @ddt.data('3.0', '3.3')
    def test_attach_volume_to_host(self, version):
        self.can_send_version_mock.return_value = (version == '3.3')
        self._test_volume_api('attach_volume',
                              rpc_method='call',
                              volume=self.fake_volume_obj,
                              instance_uuid=None,
                              host_name='fake_host',
                              mountpoint='fake_mountpoint',
                              mode='rw',
                              version=version)

    def _set_cluster(self):
        self.fake_volume_obj.cluster_name = 'my_cluster'
        self.fake_volume_obj.obj_reset_changes(['cluster_name'])
        self.fake_src_cg.cluster_name = 'my_cluster'
        self.fake_src_cg.obj_reset_changes(['my_cluster'])

    @ddt.data('3.0', '3.3')
    def test_attach_volume_to_cluster(self, version):
        self.can_send_version_mock.return_value = (version == '3.3')
        self._set_cluster()
        self._test_volume_api('attach_volume',
                              rpc_method='call',
                              volume=self.fake_volume_obj,
                              instance_uuid=None,
                              host_name='fake_host',
                              mountpoint='fake_mountpoint',
                              mode='rw',
                              version=version)

    @ddt.data('3.0', '3.4')
    def test_detach_volume(self, version):
        self.can_send_version_mock.return_value = (version == '3.4')
        self._test_volume_api('detach_volume',
                              rpc_method='call',
                              volume=self.fake_volume_obj,
                              attachment_id='fake_uuid',
                              version=version)

    @ddt.data('3.0', '3.4')
    def test_detach_volume_cluster(self, version):
        self.can_send_version_mock.return_value = (version == '3.4')
        self._set_cluster()
        self._test_volume_api('detach_volume',
                              rpc_method='call',
                              volume=self.fake_volume_obj,
                              attachment_id='fake_uuid',
                              version=version)

    @ddt.data(None, 'mycluster')
    def test_copy_volume_to_image(self, cluster_name):
        self._change_cluster_name(self.fake_volume_obj, cluster_name)
        self._test_volume_api('copy_volume_to_image',
                              rpc_method='cast',
                              volume=self.fake_volume_obj,
                              image_meta={'id': 'fake_image_id',
                                          'container_format': 'fake_type',
                                          'disk_format': 'fake_type'},
                              version='3.0')

    def test_initialize_connection(self):
        self._test_volume_api('initialize_connection',
                              rpc_method='call',
                              volume=self.fake_volume_obj,
                              connector='fake_connector',
                              version='3.0')

    def test_initialize_connection_cluster(self):
        self._set_cluster()
        self._test_volume_api('initialize_connection',
                              rpc_method='call',
                              volume=self.fake_volume_obj,
                              connector='fake_connector',
                              version='3.0')

    def test_terminate_connection(self):
        self._test_volume_api('terminate_connection',
                              rpc_method='call',
                              volume=self.fake_volume_obj,
                              connector='fake_connector',
                              force=False,
                              version='3.0')

    def test_terminate_connection_cluster(self):
        self._set_cluster()
        self._test_volume_api('terminate_connection',
                              rpc_method='call',
                              volume=self.fake_volume_obj,
                              connector='fake_connector',
                              force=False,
                              version='3.0')

    @ddt.data(None, 'mycluster')
    def test_accept_transfer(self, cluster_name):
        self._change_cluster_name(self.fake_volume_obj, cluster_name)
        self._test_volume_api('accept_transfer',
                              rpc_method='call',
                              volume=self.fake_volume_obj,
                              new_user='e5565fd0-06c8-11e3-'
                                       '8ffd-0800200c9b77',
                              new_project='e4465fd0-06c8-11e3'
                                          '-8ffd-0800200c9a66',
                              version='3.0')

    def _change_cluster_name(self, resource, cluster_name):
        resource.cluster_name = cluster_name
        resource.obj_reset_changes()

    @ddt.data(None, 'mycluster')
    def test_extend_volume(self, cluster_name):
        self._change_cluster_name(self.fake_volume_obj, cluster_name)
        self._test_volume_api('extend_volume',
                              rpc_method='cast',
                              volume=self.fake_volume_obj,
                              new_size=1,
                              reservations=self.fake_reservations,
                              version='3.0')

    @mock.patch('oslo_messaging.RPCClient.can_send_version', return_value=True)
    def test_migrate_volume(self, can_send_version):
        class FakeBackend(object):
            def __init__(self):
                self.host = 'host'
                self.cluster_name = 'cluster_name'
                self.capabilities = {}
        dest_backend = FakeBackend()
        self._test_volume_api('migrate_volume',
                              rpc_method='cast',
                              volume=self.fake_volume_obj,
                              dest_backend=dest_backend,
                              force_host_copy=True,
                              version='3.5')

    def test_migrate_volume_completion(self):
        self._test_volume_api('migrate_volume_completion',
                              rpc_method='call',
                              volume=self.fake_volume_obj,
                              new_volume=self.fake_volume_obj,
                              error=False,
                              version='3.0')

    @mock.patch('oslo_messaging.RPCClient.can_send_version', return_value=True)
    def test_retype(self, can_send_version):
        class FakeBackend(object):
            def __init__(self):
                self.host = 'host'
                self.cluster_name = 'cluster_name'
                self.capabilities = {}
        dest_backend = FakeBackend()
        self._test_volume_api('retype',
                              rpc_method='cast',
                              volume=self.fake_volume_obj,
                              new_type_id='fake',
                              dest_backend=dest_backend,
                              migration_policy='never',
                              reservations=self.fake_reservations,
                              old_reservations=self.fake_reservations,
                              version='3.5')

    def test_manage_existing(self):
        self._test_volume_api('manage_existing',
                              rpc_method='cast',
                              volume=self.fake_volume_obj,
                              ref={'lv_name': 'foo'},
                              version='3.0')

    def test_manage_existing_snapshot(self):
        volume_update = {'host': 'fake_host'}
        snpshot = {
            'id': fake.SNAPSHOT_ID,
            'volume_id': fake.VOLUME_ID,
            'status': fields.SnapshotStatus.CREATING,
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
                              backend='fake_host',
                              version='3.0')

    def test_freeze_host(self):
        service = fake_service.fake_service_obj(self.context,
                                                host='fake_host',
                                                binary='cinder-volume')
        self._test_volume_api('freeze_host', rpc_method='call',
                              service=service, version='3.0')

    def test_thaw_host(self):
        service = fake_service.fake_service_obj(self.context,
                                                host='fake_host',
                                                binary='cinder-volume')
        self._test_volume_api('thaw_host', rpc_method='call', service=service,
                              version='3.0')

    @ddt.data('3.0', '3.8')
    @mock.patch('oslo_messaging.RPCClient.can_send_version')
    def test_failover(self, version, can_send_version):
        can_send_version.side_effect = lambda x: x == version
        service = objects.Service(self.context, host='fake_host',
                                  cluster_name=None)
        _expected_method = 'failover' if version == '3.8' else 'failover_host'
        self._test_volume_api('failover', rpc_method='cast',
                              service=service,
                              secondary_backend_id='fake_backend',
                              version=version,
                              _expected_method=_expected_method)

    @mock.patch('cinder.volume.rpcapi.VolumeAPI._get_cctxt')
    def test_failover_completed(self, cctxt_mock):
        service = objects.Service(self.context, host='fake_host',
                                  cluster_name='cluster_name')
        rpcapi = volume_rpcapi.VolumeAPI()
        rpcapi.failover_completed(self.context, service, mock.sentinel.updates)
        cctxt_mock.assert_called_once_with(service.cluster_name, '3.8',
                                           fanout=True)
        cctxt_mock.return_value.cast(self.context, 'failover_completed',
                                     updates=mock.sentinel.updates)

    def test_create_consistencygroup_from_src_cgsnapshot(self):
        self._test_volume_api('create_consistencygroup_from_src',
                              rpc_method='cast',
                              group=self.fake_cg,
                              cgsnapshot=self.fake_cgsnap,
                              source_cg=None,
                              version='3.0')

    def test_create_consistencygroup_from_src_cg(self):
        self._test_volume_api('create_consistencygroup_from_src',
                              rpc_method='cast',
                              group=self.fake_cg2,
                              cgsnapshot=None,
                              source_cg=self.fake_src_cg,
                              version='3.0')

    def test_get_capabilities(self):
        self._test_volume_api('get_capabilities',
                              rpc_method='call',
                              backend_id='fake_host',
                              discover=True,
                              version='3.0')

    def test_remove_export(self):
        self._test_volume_api('remove_export',
                              rpc_method='cast',
                              volume=self.fake_volume_obj,
                              version='3.0')

    @ddt.data(None, 'mycluster')
    @mock.patch('oslo_messaging.RPCClient.can_send_version',
                return_value=True)
    def test_get_backup_device(self, cluster_name, mock_can_send_version):
        self._change_cluster_name(self.fake_volume_obj, cluster_name)
        self._test_volume_api('get_backup_device',
                              rpc_method='call',
                              backup=self.fake_backup_obj,
                              volume=self.fake_volume_obj,
                              version='3.2')

    @ddt.data(None, 'mycluster')
    @mock.patch('cinder.objects.backup.BackupDeviceInfo.from_primitive',
                return_value={})
    def test_get_backup_device_old(self, cluster_name, mock_from_primitive):
        self.can_send_version_mock.return_value = False
        self._change_cluster_name(self.fake_volume_obj, cluster_name)
        self._test_volume_api('get_backup_device',
                              rpc_method='call',
                              backup=self.fake_backup_obj,
                              volume=self.fake_volume_obj,
                              version='3.0')

    @ddt.data(None, 'mycluster')
    def test_secure_file_operations_enabled(self, cluster_name):
        self._change_cluster_name(self.fake_volume_obj, cluster_name)
        self._test_volume_api('secure_file_operations_enabled',
                              rpc_method='call',
                              volume=self.fake_volume_obj,
                              version='3.0')

    def test_create_group(self):
        self._test_group_api('create_group', rpc_method='cast',
                             group=self.fake_group, version='3.0')

    def test_delete_group(self):
        self._test_group_api('delete_group', rpc_method='cast',
                             group=self.fake_group, version='3.0')

    def test_delete_group_cluster(self):
        self.fake_group.cluster_name = 'mycluster'
        self._test_group_api('delete_group', rpc_method='cast',
                             group=self.fake_group, version='3.0')

    @ddt.data(None, 'mycluster')
    def test_update_group(self, cluster_name):
        self._change_cluster_name(self.fake_group, cluster_name)
        self._test_group_api('update_group', rpc_method='cast',
                             group=self.fake_group, add_volumes=['vol1'],
                             remove_volumes=['vol2'], version='3.0')

    def test_create_group_from_src(self):
        self._test_group_api('create_group_from_src', rpc_method='cast',
                             group=self.fake_group,
                             group_snapshot=self.fake_group_snapshot,
                             source_group=None,
                             version='3.0')

    def test_create_group_snapshot(self):
        self._test_group_api('create_group_snapshot', rpc_method='cast',
                             group_snapshot=self.fake_group_snapshot,
                             version='3.0')

    def test_delete_group_snapshot(self):
        self._test_group_api('delete_group_snapshot', rpc_method='cast',
                             group_snapshot=self.fake_group_snapshot,
                             version='3.0')

    @ddt.data(('myhost', None), ('myhost', 'mycluster'))
    @ddt.unpack
    @mock.patch('cinder.volume.rpcapi.VolumeAPI._get_cctxt')
    def test_do_cleanup(self, host, cluster, get_cctxt_mock):
        cleanup_request = objects.CleanupRequest(self.context,
                                                 host=host,
                                                 cluster_name=cluster)
        rpcapi = volume_rpcapi.VolumeAPI()
        rpcapi.do_cleanup(self.context, cleanup_request)
        get_cctxt_mock.assert_called_once_with(
            cleanup_request.service_topic_queue, '3.7')
        get_cctxt_mock.return_value.cast.assert_called_once_with(
            self.context, 'do_cleanup', cleanup_request=cleanup_request)

    def test_do_cleanup_too_old(self):
        cleanup_request = objects.CleanupRequest(self.context)
        rpcapi = volume_rpcapi.VolumeAPI()
        with mock.patch.object(rpcapi.client, 'can_send_version',
                               return_value=False) as can_send_mock:
            self.assertRaises(exception.ServiceTooOld,
                              rpcapi.do_cleanup,
                              self.context,
                              cleanup_request)
            can_send_mock.assert_called_once_with('3.7')
