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
import ddt
import mock

from oslo_config import cfg
from oslo_serialization import jsonutils

from cinder import db
from cinder import exception
from cinder import objects
from cinder.objects import fields
from cinder import test
from cinder.tests.unit.backup import fake_backup
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_service
from cinder.tests.unit import fake_volume
from cinder.tests.unit import utils as tests_utils
from cinder.volume import rpcapi as volume_rpcapi


CONF = cfg.CONF


@ddt.ddt
class VolumeRPCAPITestCase(test.RPCAPITestCase):

    def setUp(self):
        super(VolumeRPCAPITestCase, self).setUp()
        self.rpcapi = volume_rpcapi.VolumeAPI
        self.base_version = '3.0'
        vol = {}
        vol['host'] = 'fake_host'
        vol['availability_zone'] = CONF.storage_availability_zone
        vol['status'] = "available"
        vol['attach_status'] = "detached"
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

        generic_group = tests_utils.create_group(
            self.context,
            availability_zone=CONF.storage_availability_zone,
            group_type_id='group_type1',
            host='fakehost@fakedrv#fakepool')

        group_snapshot = tests_utils.create_group_snapshot(
            self.context,
            group_id=generic_group.id,
            group_type_id=fake.GROUP_TYPE_ID)

        self.fake_volume = jsonutils.to_primitive(volume)
        self.fake_volume_obj = fake_volume.fake_volume_obj(self.context, **vol)
        self.fake_snapshot = snapshot
        self.fake_reservations = ["RESERVATION"]
        self.fake_backup_obj = fake_backup.fake_backup_obj(self.context)
        self.fake_group = generic_group
        self.fake_group_snapshot = group_snapshot

        self.can_send_version_mock = self.patch(
            'oslo_messaging.RPCClient.can_send_version', return_value=True)

    def tearDown(self):
        super(VolumeRPCAPITestCase, self).tearDown()
        self.fake_snapshot.destroy()
        self.fake_volume_obj.destroy()
        self.fake_group_snapshot.destroy()
        self.fake_group.destroy()
        self.fake_backup_obj.destroy()

    def _change_cluster_name(self, resource, cluster_name):
        resource.cluster_name = cluster_name
        resource.obj_reset_changes()

    def test_create_volume(self):
        self._test_rpc_api('create_volume',
                           rpc_method='cast',
                           server='fake_host',
                           volume=self.fake_volume_obj,
                           request_spec=objects.RequestSpec.from_primitives(
                               {}),
                           filter_properties={'availability_zone': 'fake_az'},
                           allow_reschedule=True)

    @ddt.data(None, 'my_cluster')
    def test_delete_volume(self, cluster_name):
        self._change_cluster_name(self.fake_volume_obj, cluster_name)
        self._test_rpc_api('delete_volume',
                           rpc_method='cast',
                           server=cluster_name or self.fake_volume_obj.host,
                           volume=self.fake_volume_obj,
                           unmanage_only=False,
                           cascade=False)

    def test_delete_volume_cascade(self):
        self._test_rpc_api('delete_volume',
                           rpc_method='cast',
                           server=self.fake_volume_obj.host,
                           volume=self.fake_volume_obj,
                           unmanage_only=False,
                           cascade=True)

    @ddt.data(None, 'mycluster')
    def test_create_snapshot(self, cluster_name):
        self._change_cluster_name(self.fake_volume_obj, cluster_name)
        self._test_rpc_api('create_snapshot',
                           rpc_method='cast',
                           server=cluster_name or self.fake_volume_obj.host,
                           volume=self.fake_volume_obj,
                           snapshot=self.fake_snapshot)

    @ddt.data(None, 'mycluster')
    def test_delete_snapshot(self, cluster_name):
        self._change_cluster_name(self.fake_snapshot.volume, cluster_name)
        self._test_rpc_api(
            'delete_snapshot', rpc_method='cast',
            server=cluster_name or self.fake_snapshot.volume.host,
            snapshot=self.fake_snapshot, unmanage_only=False)

    def test_delete_snapshot_with_unmanage_only(self):
        self._test_rpc_api('delete_snapshot',
                           rpc_method='cast',
                           server=self.fake_snapshot.volume.host,
                           snapshot=self.fake_snapshot,
                           unmanage_only=True)

    @ddt.data('3.0', '3.3')
    def test_attach_volume_to_instance(self, version):
        self.can_send_version_mock.return_value = (version == '3.3')
        self._test_rpc_api('attach_volume',
                           rpc_method='call',
                           server=self.fake_volume_obj.host,
                           volume=self.fake_volume_obj,
                           instance_uuid=fake.INSTANCE_ID,
                           host_name=None,
                           mountpoint='fake_mountpoint',
                           mode='ro',
                           expected_kwargs_diff={
                               'volume_id': self.fake_volume_obj.id},
                           retval=fake_volume.fake_db_volume_attachment(),
                           version=version)

    @ddt.data('3.0', '3.3')
    def test_attach_volume_to_host(self, version):
        self.can_send_version_mock.return_value = (version == '3.3')
        self._test_rpc_api('attach_volume',
                           rpc_method='call',
                           server=self.fake_volume_obj.host,
                           volume=self.fake_volume_obj,
                           instance_uuid=None,
                           host_name='fake_host',
                           mountpoint='fake_mountpoint',
                           mode='rw',
                           expected_kwargs_diff={
                               'volume_id': self.fake_volume_obj.id},
                           retval=fake_volume.fake_db_volume_attachment(),
                           version=version)

    @ddt.data('3.0', '3.3')
    def test_attach_volume_cluster(self, version):
        self.can_send_version_mock.return_value = (version == '3.3')
        self._change_cluster_name(self.fake_volume_obj, 'mycluster')
        self._test_rpc_api('attach_volume',
                           rpc_method='call',
                           server=self.fake_volume_obj.cluster_name,
                           volume=self.fake_volume_obj,
                           instance_uuid=None,
                           host_name='fake_host',
                           mountpoint='fake_mountpoint',
                           mode='rw',
                           expected_kwargs_diff={
                               'volume_id': self.fake_volume_obj.id},
                           retval=fake_volume.fake_db_volume_attachment(),
                           version=version)

    @ddt.data('3.0', '3.4')
    def test_detach_volume(self, version):
        self.can_send_version_mock.return_value = (version == '3.4')
        self._test_rpc_api('detach_volume',
                           rpc_method='call',
                           server=self.fake_volume_obj.host,
                           volume=self.fake_volume_obj,
                           attachment_id=fake.ATTACHMENT_ID,
                           expected_kwargs_diff={
                               'volume_id': self.fake_volume_obj.id},
                           # NOTE(dulek): Detach isn't returning anything, but
                           # it's a call and it is synchronous.
                           retval=None,
                           version=version)

    @ddt.data('3.0', '3.4')
    def test_detach_volume_cluster(self, version):
        self.can_send_version_mock.return_value = (version == '3.4')
        self._change_cluster_name(self.fake_volume_obj, 'mycluster')
        self._test_rpc_api('detach_volume',
                           rpc_method='call',
                           server=self.fake_volume_obj.cluster_name,
                           volume=self.fake_volume_obj,
                           attachment_id='fake_uuid',
                           expected_kwargs_diff={
                               'volume_id': self.fake_volume_obj.id},
                           # NOTE(dulek): Detach isn't returning anything, but
                           # it's a call and it is synchronous.
                           retval=None,
                           version=version)

    @ddt.data(None, 'mycluster')
    def test_copy_volume_to_image(self, cluster_name):
        self._change_cluster_name(self.fake_volume_obj, cluster_name)
        self._test_rpc_api('copy_volume_to_image',
                           rpc_method='cast',
                           server=cluster_name or self.fake_volume_obj.host,
                           volume=self.fake_volume_obj,
                           expected_kwargs_diff={
                               'volume_id': self.fake_volume_obj.id},
                           image_meta={'id': fake.IMAGE_ID,
                                       'container_format': 'fake_type',
                                       'disk_format': 'fake_format'})

    @ddt.data(None, 'mycluster')
    def test_initialize_connection(self, cluster_name):
        self._change_cluster_name(self.fake_volume_obj, cluster_name)
        self._test_rpc_api('initialize_connection',
                           rpc_method='call',
                           server=cluster_name or self.fake_volume_obj.host,
                           connector='fake_connector',
                           volume=self.fake_volume_obj)

    @ddt.data(None, 'mycluster')
    def test_terminate_connection(self, cluster_name):
        self._change_cluster_name(self.fake_volume_obj, cluster_name)
        self._test_rpc_api('terminate_connection',
                           rpc_method='call',
                           server=cluster_name or self.fake_volume_obj.host,
                           volume=self.fake_volume_obj,
                           connector='fake_connector',
                           force=False,
                           # NOTE(dulek): Terminate isn't returning anything,
                           # but it's a call and it is synchronous.
                           retval=None,
                           expected_kwargs_diff={
                               'volume_id': self.fake_volume_obj.id})

    @ddt.data(None, 'mycluster')
    def test_accept_transfer(self, cluster_name):
        self._change_cluster_name(self.fake_volume_obj, cluster_name)
        self._test_rpc_api('accept_transfer',
                           rpc_method='call',
                           server=cluster_name or self.fake_volume_obj.host,
                           volume=self.fake_volume_obj,
                           new_user=fake.USER_ID,
                           new_project=fake.PROJECT_ID,
                           expected_kwargs_diff={
                               'volume_id': self.fake_volume_obj.id})

    @ddt.data(None, 'mycluster')
    def test_extend_volume(self, cluster_name):
        self._change_cluster_name(self.fake_volume_obj, cluster_name)
        self._test_rpc_api('extend_volume',
                           rpc_method='cast',
                           server=cluster_name or self.fake_volume_obj.host,
                           volume=self.fake_volume_obj,
                           new_size=1,
                           reservations=self.fake_reservations)

    def test_migrate_volume(self):
        class FakeBackend(object):

            def __init__(self):
                self.host = 'fake_host'
                self.cluster_name = 'cluster_name'
                self.capabilities = {}
        dest_backend = FakeBackend()
        self._test_rpc_api('migrate_volume',
                           rpc_method='cast',
                           server=self.fake_volume_obj.host,
                           volume=self.fake_volume_obj,
                           dest_backend=dest_backend,
                           force_host_copy=True,
                           expected_kwargs_diff={
                               'host': {'host': 'fake_host',
                                        'cluster_name': 'cluster_name',
                                        'capabilities': {}}},
                           version='3.5')

    def test_migrate_volume_completion(self):
        self._test_rpc_api('migrate_volume_completion',
                           rpc_method='call',
                           server=self.fake_volume_obj.host,
                           volume=self.fake_volume_obj,
                           new_volume=self.fake_volume_obj,
                           error=False,
                           retval=fake.VOLUME_ID)

    def test_retype(self):
        class FakeBackend(object):

            def __init__(self):
                self.host = 'fake_host'
                self.cluster_name = 'cluster_name'
                self.capabilities = {}
        dest_backend = FakeBackend()
        self._test_rpc_api('retype',
                           rpc_method='cast',
                           server=self.fake_volume_obj.host,
                           volume=self.fake_volume_obj,
                           new_type_id=fake.VOLUME_TYPE_ID,
                           dest_backend=dest_backend,
                           migration_policy='never',
                           reservations=self.fake_reservations,
                           old_reservations=self.fake_reservations,
                           expected_kwargs_diff={
                               'host': {'host': 'fake_host',
                                        'cluster_name': 'cluster_name',
                                        'capabilities': {}}},
                           version='3.5')

    def test_manage_existing(self):
        self._test_rpc_api('manage_existing',
                           rpc_method='cast',
                           server=self.fake_volume_obj.host,
                           volume=self.fake_volume_obj,
                           ref={'lv_name': 'foo'})

    def test_manage_existing_snapshot(self):
        self._test_rpc_api('manage_existing_snapshot',
                           rpc_method='cast',
                           server=self.fake_snapshot.volume.host,
                           snapshot=self.fake_snapshot,
                           ref='foo',
                           backend='fake_host')

    def test_freeze_host(self):
        service = fake_service.fake_service_obj(self.context,
                                                host='fake_host',
                                                binary='cinder-volume')
        self._test_rpc_api('freeze_host',
                           rpc_method='call',
                           server='fake_host',
                           service=service,
                           retval=True)

    def test_thaw_host(self):
        service = fake_service.fake_service_obj(self.context,
                                                host='fake_host',
                                                binary='cinder-volume')
        self._test_rpc_api('thaw_host',
                           rpc_method='call',
                           server='fake_host',
                           service=service,
                           retval=True)

    @ddt.data('3.0', '3.8')
    def test_failover(self, version):
        self.can_send_version_mock.side_effect = lambda x: x == version
        service = objects.Service(self.context, host='fake_host',
                                  cluster_name=None)
        expected_method = 'failover' if version == '3.8' else 'failover_host'
        self._test_rpc_api('failover', rpc_method='cast',
                           expected_method=expected_method, server='fake_host',
                           service=service,
                           secondary_backend_id='fake_backend',
                           version=version)

    @mock.patch('cinder.volume.rpcapi.VolumeAPI._get_cctxt')
    def test_failover_completed(self, cctxt_mock):
        service = objects.Service(self.context, host='fake_host',
                                  cluster_name='cluster_name')
        self._test_rpc_api('failover_completed', rpc_method='cast',
                           fanout=True, server='fake_host', service=service,
                           updates=mock.sentinel.updates)

    def test_get_capabilities(self):
        self._test_rpc_api('get_capabilities',
                           rpc_method='call',
                           server='fake_host',
                           backend_id='fake_host',
                           discover=True,
                           retval={'foo': 'bar'})

    def test_remove_export(self):
        self._test_rpc_api('remove_export',
                           rpc_method='cast',
                           server=self.fake_volume_obj.host,
                           volume=self.fake_volume_obj,
                           expected_kwargs_diff={
                               'volume_id': self.fake_volume_obj.id})

    @ddt.data(None, 'mycluster')
    def test_get_backup_device(self, cluster_name):
        self._change_cluster_name(self.fake_volume_obj, cluster_name)
        backup_device_dict = {'backup_device': self.fake_volume,
                              'is_snapshot': False,
                              'secure_enabled': True}
        backup_device_obj = objects.BackupDeviceInfo.from_primitive(
            backup_device_dict, self.context)
        self._test_rpc_api('get_backup_device',
                           rpc_method='call',
                           server=cluster_name or self.fake_volume_obj.host,
                           backup=self.fake_backup_obj,
                           volume=self.fake_volume_obj,
                           expected_kwargs_diff={
                               'want_objects': True,
                           },
                           retval=backup_device_obj,
                           version='3.2')

    @ddt.data(None, 'mycluster')
    def test_get_backup_device_old(self, cluster_name):
        self.can_send_version_mock.side_effect = (True, False, False)
        self._change_cluster_name(self.fake_volume_obj, cluster_name)
        backup_device_dict = {'backup_device': self.fake_volume,
                              'is_snapshot': False,
                              'secure_enabled': True}
        backup_device_obj = objects.BackupDeviceInfo.from_primitive(
            backup_device_dict, self.context)

        self._test_rpc_api('get_backup_device',
                           rpc_method='call',
                           server=cluster_name or self.fake_volume_obj.host,
                           backup=self.fake_backup_obj,
                           volume=self.fake_volume_obj,
                           retval=backup_device_dict,
                           expected_retval=backup_device_obj,
                           version='3.0')

    @ddt.data(None, 'mycluster')
    def test_secure_file_operations_enabled(self, cluster_name):
        self._change_cluster_name(self.fake_volume_obj, cluster_name)
        self._test_rpc_api('secure_file_operations_enabled',
                           rpc_method='call',
                           server=cluster_name or self.fake_volume_obj.host,
                           volume=self.fake_volume_obj,
                           retval=True)

    def test_create_group(self):
        self._test_rpc_api('create_group', rpc_method='cast',
                           server='fakehost@fakedrv', group=self.fake_group)

    @ddt.data(None, 'mycluster')
    def test_delete_group(self, cluster_name):
        self._change_cluster_name(self.fake_group, cluster_name)
        self._test_rpc_api('delete_group', rpc_method='cast',
                           server=cluster_name or self.fake_group.host,
                           group=self.fake_group)

    @ddt.data(None, 'mycluster')
    def test_update_group(self, cluster_name):
        self._change_cluster_name(self.fake_group, cluster_name)
        self._test_rpc_api('update_group', rpc_method='cast',
                           server=cluster_name or self.fake_group.host,
                           group=self.fake_group,
                           add_volumes=[fake.VOLUME2_ID],
                           remove_volumes=[fake.VOLUME3_ID])

    def test_create_group_from_src(self):
        self._test_rpc_api('create_group_from_src', rpc_method='cast',
                           server=self.fake_group.host, group=self.fake_group,
                           group_snapshot=self.fake_group_snapshot,
                           source_group=None)

    def test_create_group_snapshot(self):
        self._test_rpc_api('create_group_snapshot', rpc_method='cast',
                           server=self.fake_group_snapshot.group.host,
                           group_snapshot=self.fake_group_snapshot)

    def test_delete_group_snapshot(self):
        self._test_rpc_api('delete_group_snapshot', rpc_method='cast',
                           server=self.fake_group_snapshot.group.host,
                           group_snapshot=self.fake_group_snapshot)

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

    @ddt.data(('myhost', None, '3.10'), ('myhost', 'mycluster', '3.10'),
              ('myhost', None, '3.0'))
    @ddt.unpack
    @mock.patch('oslo_messaging.RPCClient.can_send_version')
    def test_get_manageable_volumes(
            self,
            host,
            cluster_name,
            version,
            can_send_version):
        can_send_version.side_effect = lambda x: x == version
        service = objects.Service(self.context, host=host,
                                  cluster_name=cluster_name)
        expected_kwargs_diff = {
            'want_objects': True} if version == '3.10' else {}
        self._test_rpc_api('get_manageable_volumes',
                           rpc_method='call',
                           service=service,
                           server=cluster_name or host,
                           marker=5,
                           limit=20,
                           offset=5,
                           sort_keys='fake_keys',
                           sort_dirs='fake_dirs',
                           expected_kwargs_diff=expected_kwargs_diff,
                           version=version)
        can_send_version.assert_has_calls([mock.call('3.10')])

    @ddt.data(('myhost', None, '3.10'), ('myhost', 'mycluster', '3.10'),
              ('myhost', None, '3.0'))
    @ddt.unpack
    @mock.patch('oslo_messaging.RPCClient.can_send_version')
    def test_get_manageable_snapshots(
            self,
            host,
            cluster_name,
            version,
            can_send_version):
        can_send_version.side_effect = lambda x: x == version
        service = objects.Service(self.context, host=host,
                                  cluster_name=cluster_name)
        expected_kwargs_diff = {
            'want_objects': True} if version == '3.10' else {}
        self._test_rpc_api('get_manageable_snapshots',
                           rpc_method='call',
                           service=service,
                           server=cluster_name or host,
                           marker=5,
                           limit=20,
                           offset=5,
                           sort_keys='fake_keys',
                           sort_dirs='fake_dirs',
                           expected_kwargs_diff=expected_kwargs_diff,
                           version=version)
        can_send_version.assert_has_calls([mock.call('3.10')])

    @mock.patch('oslo_messaging.RPCClient.can_send_version', mock.Mock())
    def test_set_log_levels(self):
        service = objects.Service(self.context, host='host1')
        self._test_rpc_api('set_log_levels',
                           rpc_method='cast',
                           server=service.host,
                           service=service,
                           log_request='log_request',
                           version='3.12')

    @mock.patch('oslo_messaging.RPCClient.can_send_version', mock.Mock())
    def test_get_log_levels(self):
        service = objects.Service(self.context, host='host1')
        self._test_rpc_api('get_log_levels',
                           rpc_method='call',
                           server=service.host,
                           service=service,
                           log_request='log_request',
                           version='3.12')

    @ddt.data(None, 'mycluster')
    def test_initialize_connection_snapshot(self, cluster_name):
        self._change_cluster_name(self.fake_snapshot.volume, cluster_name)
        self._test_rpc_api('initialize_connection_snapshot',
                           rpc_method='call',
                           server=(cluster_name or
                                   self.fake_snapshot.volume.host),
                           connector='fake_connector',
                           snapshot=self.fake_snapshot,
                           expected_kwargs_diff={
                               'snapshot_id': self.fake_snapshot.id},
                           version='3.13')

    @ddt.data(None, 'mycluster')
    def test_terminate_connection_snapshot(self, cluster_name):
        self._change_cluster_name(self.fake_snapshot.volume, cluster_name)
        self._test_rpc_api('terminate_connection_snapshot',
                           rpc_method='call',
                           server=(cluster_name or
                                   self.fake_snapshot.volume.host),
                           snapshot=self.fake_snapshot,
                           connector='fake_connector',
                           force=False,
                           retval=None,
                           expected_kwargs_diff={
                               'snapshot_id': self.fake_snapshot.id},
                           version='3.13')

    def test_remove_export_snapshot(self):
        self._test_rpc_api('remove_export_snapshot',
                           rpc_method='cast',
                           server=self.fake_volume_obj.host,
                           snapshot=self.fake_snapshot,
                           expected_kwargs_diff={
                               'snapshot_id': self.fake_snapshot.id},
                           version='3.13')

    def test_enable_replication(self):
        self._test_rpc_api('enable_replication', rpc_method='cast',
                           server=self.fake_group.host,
                           group=self.fake_group,
                           version='3.14')

    def test_disable_replication(self):
        self._test_rpc_api('disable_replication', rpc_method='cast',
                           server=self.fake_group.host,
                           group=self.fake_group,
                           version='3.14')

    def test_failover_replication(self):
        self._test_rpc_api('failover_replication', rpc_method='cast',
                           server=self.fake_group.host,
                           group=self.fake_group,
                           allow_attached_volume=False,
                           secondary_backend_id=None,
                           version='3.14')

    def test_list_replication_targets(self):
        self._test_rpc_api('list_replication_targets', rpc_method='call',
                           server=self.fake_group.host,
                           group=self.fake_group,
                           version='3.14')
