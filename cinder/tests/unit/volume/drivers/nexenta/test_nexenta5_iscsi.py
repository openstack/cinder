# Copyright 2019 Nexenta Systems, Inc.
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
"""Unit tests for OpenStack Cinder volume driver."""
from unittest import mock
import uuid

from oslo_utils import units

from cinder import context
from cinder import db
from cinder.tests.unit.consistencygroup.fake_cgsnapshot import (
    fake_cgsnapshot_obj as fake_cgsnapshot)
from cinder.tests.unit.consistencygroup.fake_consistencygroup import (
    fake_consistencyobject_obj as fake_cgroup)
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit.fake_snapshot import fake_snapshot_obj as fake_snapshot
from cinder.tests.unit.fake_volume import fake_volume_obj as fake_volume
from cinder.tests.unit import test
from cinder.volume import configuration as conf
from cinder.volume.drivers.nexenta.ns5 import iscsi
from cinder.volume.drivers.nexenta.ns5 import jsonrpc


class TestNexentaISCSIDriver(test.TestCase):

    def setUp(self):
        super(TestNexentaISCSIDriver, self).setUp()
        self.ctxt = context.get_admin_context()
        self.cfg = mock.Mock(spec=conf.Configuration)
        self.cfg.volume_backend_name = 'nexenta_iscsi'
        self.cfg.nexenta_group_snapshot_template = 'group-snapshot-%s'
        self.cfg.nexenta_origin_snapshot_template = 'origin-snapshot-%s'
        self.cfg.nexenta_dataset_description = ''
        self.cfg.nexenta_host = '1.1.1.1'
        self.cfg.nexenta_user = 'admin'
        self.cfg.nexenta_password = 'nexenta'
        self.cfg.nexenta_volume = 'cinder'
        self.cfg.nexenta_rest_port = 8443
        self.cfg.nexenta_use_https = False
        self.cfg.nexenta_iscsi_target_portal_port = 3260
        self.cfg.nexenta_target_prefix = 'iqn:cinder'
        self.cfg.nexenta_target_group_prefix = 'cinder'
        self.cfg.nexenta_ns5_blocksize = 32
        self.cfg.nexenta_sparse = True
        self.cfg.nexenta_lu_writebackcache_disabled = True
        self.cfg.nexenta_dataset_compression = 'on'
        self.cfg.nexenta_dataset_dedup = 'off'
        self.cfg.reserved_percentage = 20
        self.cfg.nexenta_host_group_prefix = 'hg'
        self.cfg.nexenta_volume = 'pool'
        self.cfg.driver_ssl_cert_verify = False
        self.cfg.nexenta_luns_per_target = 20
        self.cfg.driver_ssl_cert_verify = False
        self.cfg.nexenta_iscsi_target_portals = '1.1.1.1:3260,2.2.2.2:3260'
        self.cfg.nexenta_iscsi_target_host_group = 'all'
        self.cfg.nexenta_rest_address = '1.1.1.1'
        self.cfg.nexenta_rest_backoff_factor = 1
        self.cfg.nexenta_rest_retry_count = 3
        self.cfg.nexenta_rest_connect_timeout = 1
        self.cfg.nexenta_rest_read_timeout = 1
        self.cfg.nexenta_volume_group = 'vg'
        self.cfg.safe_get = self.fake_safe_get
        self.nef_mock = mock.Mock()
        self.mock_object(jsonrpc, 'NefRequest',
                         return_value=self.nef_mock)
        self.drv = iscsi.NexentaISCSIDriver(
            configuration=self.cfg)
        self.drv.db = db
        self.drv.do_setup(self.ctxt)

    def fake_safe_get(self, key):
        try:
            value = getattr(self.cfg, key)
        except AttributeError:
            value = None
        return value

    def fake_uuid4():
        return uuid.UUID('38d18a48-b791-4046-b523-a84aad966310')

    def test_do_setup(self):
        self.assertIsNone(self.drv.do_setup(self.ctxt))

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefServices.get')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefVolumeGroups.create')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefVolumeGroups.get')
    def test_check_for_setup_error(self, volume_group_get,
                                   volume_group_create,
                                   service_get):
        path = self.drv.root_path
        bs = self.cfg.nexenta_ns5_blocksize * units.Ki
        name = 'iscsit'
        state = 'online'
        volume_group_get.return_value = {'path': path}
        service_get.return_value = {'name': name, 'state': state}
        self.assertIsNone(self.drv.check_for_setup_error())
        volume_group_get.assert_called_with(path)
        service_get.assert_called_with(name)

        volume_group_get.side_effect = jsonrpc.NefException({
            'message': 'Failed to open dataset',
            'code': 'ENOENT'
        })
        volume_group_create.return_value = {}
        self.assertIsNone(self.drv.check_for_setup_error())
        volume_group_get.assert_called_with(path)
        payload = {'path': path, 'volumeBlockSize': bs}
        volume_group_create.assert_called_with(payload)
        service_get.assert_called_with(name)

        state = 'offline'
        volume_group_get.return_value = {'path': path}
        service_get.return_value = {'name': name, 'state': state}
        self.assertRaises(jsonrpc.NefException,
                          self.drv.check_for_setup_error)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefVolumes.create')
    def test_create_volume(self, create_volume):
        volume = fake_volume(self.ctxt)
        self.assertIsNone(self.drv.create_volume(volume))
        path = self.drv._get_volume_path(volume)
        size = volume['size'] * units.Gi
        bs = self.cfg.nexenta_ns5_blocksize * units.Ki
        payload = {
            'path': path,
            'volumeSize': size,
            'volumeBlockSize': bs,
            'compressionMode': self.cfg.nexenta_dataset_compression,
            'sparseVolume': self.cfg.nexenta_sparse
        }
        create_volume.assert_called_with(payload)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefVolumes.delete')
    def test_delete_volume(self, delete_volume):
        volume = fake_volume(self.ctxt)
        self.assertIsNone(self.drv.delete_volume(volume))
        path = self.drv._get_volume_path(volume)
        payload = {'snapshots': True}
        delete_volume.assert_called_with(path, payload)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefVolumes.set')
    def test_extend_volume(self, extend_volume):
        volume = fake_volume(self.ctxt)
        size = volume['size'] * 2
        self.assertIsNone(self.drv.extend_volume(volume, size))
        path = self.drv._get_volume_path(volume)
        size = size * units.Gi
        payload = {'volumeSize': size}
        extend_volume.assert_called_with(path, payload)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefSnapshots.delete')
    def test_delete_snapshot(self, delete_snapshot):
        volume = fake_volume(self.ctxt)
        snapshot = fake_snapshot(self.ctxt)
        snapshot.volume = volume
        delete_snapshot.return_value = {}
        self.assertIsNone(self.drv.delete_snapshot(snapshot))
        path = self.drv._get_snapshot_path(snapshot)
        payload = {'defer': True}
        delete_snapshot.assert_called_with(path, payload)

    def test_snapshot_revert_use_temp_snapshot(self):
        result = self.drv.snapshot_revert_use_temp_snapshot()
        expected = False
        self.assertEqual(expected, result)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefVolumes.rollback')
    def test_revert_to_snapshot(self, rollback_volume):
        volume = fake_volume(self.ctxt)
        snapshot = fake_snapshot(self.ctxt)
        snapshot.volume = volume
        rollback_volume.return_value = {}
        self.assertIsNone(
            self.drv.revert_to_snapshot(self.ctxt, volume, snapshot)
        )
        path = self.drv._get_volume_path(volume)
        payload = {'snapshot': snapshot['name']}
        rollback_volume.assert_called_with(path, payload)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.iscsi.'
                'NexentaISCSIDriver.delete_snapshot')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.iscsi.'
                'NexentaISCSIDriver.create_volume_from_snapshot')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.iscsi.'
                'NexentaISCSIDriver.create_snapshot')
    def test_create_cloned_volume(self, create_snapshot, create_volume,
                                  delete_snapshot):
        volume = fake_volume(self.ctxt)
        clone_spec = {'id': fake.VOLUME2_ID}
        clone = fake_volume(self.ctxt, **clone_spec)
        create_snapshot.return_value = {}
        create_volume.return_value = {}
        delete_snapshot.return_value = {}
        self.assertIsNone(self.drv.create_cloned_volume(clone, volume))
        snapshot = {
            'name': self.drv.origin_snapshot_template % clone['id'],
            'volume_id': volume['id'],
            'volume_name': volume['name'],
            'volume_size': volume['size']
        }
        create_snapshot.assert_called_with(snapshot)
        create_volume.assert_called_with(clone, snapshot)
        create_volume.side_effect = jsonrpc.NefException({
            'message': 'Failed to create volume',
            'code': 'EBUSY'
        })
        self.assertRaises(jsonrpc.NefException,
                          self.drv.create_cloned_volume,
                          clone, volume)
        create_snapshot.side_effect = jsonrpc.NefException({
            'message': 'Failed to open dataset',
            'code': 'ENOENT'
        })
        self.assertRaises(jsonrpc.NefException,
                          self.drv.create_cloned_volume,
                          clone, volume)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefSnapshots.create')
    def test_create_snapshot(self, create_snapshot):
        volume = fake_volume(self.ctxt)
        snapshot = fake_snapshot(self.ctxt)
        snapshot.volume = volume
        create_snapshot.return_value = {}
        self.assertIsNone(self.drv.create_snapshot(snapshot))
        path = self.drv._get_snapshot_path(snapshot)
        payload = {'path': path}
        create_snapshot.assert_called_with(payload)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'iscsi.NexentaISCSIDriver.extend_volume')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefSnapshots.clone')
    def test_create_volume_from_snapshot(self, clone_snapshot,
                                         extend_volume):
        volume = fake_volume(self.ctxt)
        snapshot = fake_snapshot(self.ctxt)
        snapshot.volume = volume
        clone_size = 10
        clone_spec = {
            'id': fake.VOLUME2_ID,
            'size': clone_size
        }
        clone = fake_volume(self.ctxt, **clone_spec)
        snapshot_path = self.drv._get_snapshot_path(snapshot)
        clone_path = self.drv._get_volume_path(clone)
        clone_snapshot.return_value = {}
        extend_volume.return_value = None
        self.assertIsNone(
            self.drv.create_volume_from_snapshot(clone, snapshot)
        )
        clone_payload = {'targetPath': clone_path}
        clone_snapshot.assert_called_with(snapshot_path, clone_payload)
        extend_volume.assert_called_with(clone, clone_size)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefLunMappings.list')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'iscsi.NexentaISCSIDriver._create_target_group')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'iscsi.NexentaISCSIDriver._create_target')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'iscsi.NexentaISCSIDriver._target_group_props')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'iscsi.NexentaISCSIDriver._get_host_portals')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'iscsi.NexentaISCSIDriver._get_host_group')
    @mock.patch('uuid.uuid4', fake_uuid4)
    def test_initialize_connection(self, get_host_group, get_host_portals,
                                   get_target_group_props, create_target,
                                   create_target_group, list_mappings):
        volume = fake_volume(self.ctxt)
        host_iqn = 'iqn:cinder-client'
        target_iqn = 'iqn:cinder-target'
        connector = {'initiator': host_iqn, 'multipath': True}
        host_group = 'cinder-host-group'
        target_group = 'cinder-target-group'
        target_portals = self.cfg.nexenta_iscsi_target_portals.split(',')
        get_host_group.return_value = host_group
        get_host_portals.return_value = {
            target_iqn: target_portals
        }
        list_mappings.return_value = [{
            'id': '309F9B9013CF627A00000000',
            'lun': 0,
            'hostGroup': host_group,
            'targetGroup': target_group
        }]
        get_target_group_props.return_value = {
            target_iqn: target_portals
        }
        create_target.return_value = {}
        create_target_group.return_value = {}
        result = self.drv.initialize_connection(volume, connector)
        expected = {
            'driver_volume_type': 'iscsi',
            'data': {
                'target_discovered': False,
                'encrypted': False,
                'qos_specs': None,
                'target_luns': [0] * len(target_portals),
                'access_mode': 'rw',
                'volume_id': volume['id'],
                'target_portals': target_portals,
                'target_iqns': [target_iqn] * len(target_portals)
            }
        }
        self.assertEqual(expected, result)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefLunMappings.delete')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefLunMappings.list')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'iscsi.NexentaISCSIDriver._get_host_group')
    def test_terminate_connection(self, get_host_group,
                                  list_mappings, delete_mapping):
        volume = fake_volume(self.ctxt)
        host_group = 'cinder-host-group'
        target_group = 'cinder-target-group'
        connector = {'initiator': 'iqn:test'}
        get_host_group.return_value = host_group
        list_mappings.return_value = [{
            'id': '309F9B9013CF627A00000000',
            'lun': 0,
            'hostGroup': host_group,
            'targetGroup': target_group
        }]
        delete_mapping.return_value = {}
        expected = {'driver_volume_type': 'iscsi', 'data': {}}
        result = self.drv.terminate_connection(volume, connector)
        self.assertEqual(expected, result)

    def test_create_export(self):
        volume = fake_volume(self.ctxt)
        connector = {'initiator': 'iqn:test'}
        self.assertIsNone(
            self.drv.create_export(self.ctxt, volume, connector)
        )

    def test_ensure_export(self):
        volume = fake_volume(self.ctxt)
        self.assertIsNone(
            self.drv.ensure_export(self.ctxt, volume)
        )

    def test_remove_export(self):
        volume = fake_volume(self.ctxt)
        self.assertIsNone(
            self.drv.remove_export(self.ctxt, volume)
        )

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefVolumeGroups.get')
    def test_get_volume_stats(self, get_volume_group):
        available = 100
        used = 75
        get_volume_group.return_value = {
            'bytesAvailable': available * units.Gi,
            'bytesUsed': used * units.Gi
        }
        result = self.drv.get_volume_stats(True)
        payload = {'fields': 'bytesAvailable,bytesUsed'}
        get_volume_group.assert_called_with(self.drv.root_path, payload)
        self.assertEqual(self.drv._stats, result)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefVolumeGroups.get')
    def test_update_volume_stats(self, get_volume_group):
        available = 8
        used = 2
        get_volume_group.return_value = {
            'bytesAvailable': available * units.Gi,
            'bytesUsed': used * units.Gi
        }
        location_info = '%(driver)s:%(host)s:%(pool)s/%(group)s' % {
            'driver': self.drv.__class__.__name__,
            'host': self.cfg.nexenta_host,
            'pool': self.cfg.nexenta_volume,
            'group': self.cfg.nexenta_volume_group,
        }
        expected = {
            'vendor_name': 'Nexenta',
            'dedup': self.cfg.nexenta_dataset_dedup,
            'compression': self.cfg.nexenta_dataset_compression,
            'description': self.cfg.nexenta_dataset_description,
            'driver_version': self.drv.VERSION,
            'storage_protocol': 'iSCSI',
            'sparsed_volumes': self.cfg.nexenta_sparse,
            'total_capacity_gb': used + available,
            'free_capacity_gb': available,
            'reserved_percentage': self.cfg.reserved_percentage,
            'QoS_support': False,
            'multiattach': True,
            'consistencygroup_support': True,
            'consistent_group_snapshot_enabled': True,
            'volume_backend_name': self.cfg.volume_backend_name,
            'location_info': location_info,
            'iscsi_target_portal_port': (
                self.cfg.nexenta_iscsi_target_portal_port),
            'nef_url': self.cfg.nexenta_rest_address,
            'nef_port': self.cfg.nexenta_rest_port
        }
        self.assertIsNone(self.drv._update_volume_stats())
        self.assertEqual(expected, self.drv._stats)

    def test__get_volume_path(self):
        volume = fake_volume(self.ctxt)
        result = self.drv._get_volume_path(volume)
        expected = '%s/%s/%s' % (self.cfg.nexenta_volume,
                                 self.cfg.nexenta_volume_group,
                                 volume['name'])
        self.assertEqual(expected, result)

    def test__get_snapshot_path(self):
        volume = fake_volume(self.ctxt)
        snapshot = fake_snapshot(self.ctxt)
        snapshot.volume = volume
        result = self.drv._get_snapshot_path(snapshot)
        expected = '%s/%s/%s@%s' % (self.cfg.nexenta_volume,
                                    self.cfg.nexenta_volume_group,
                                    snapshot['volume_name'],
                                    snapshot['name'])
        self.assertEqual(expected, result)

    def test__get_target_group_name(self):
        target_iqn = '%s-test' % self.cfg.nexenta_target_prefix
        result = self.drv._get_target_group_name(target_iqn)
        expected = '%s-test' % self.cfg.nexenta_target_group_prefix
        self.assertEqual(expected, result)

    def test__get_target_name(self):
        target_group = '%s-test' % self.cfg.nexenta_target_group_prefix
        result = self.drv._get_target_name(target_group)
        expected = '%s-test' % self.cfg.nexenta_target_prefix
        self.assertEqual(expected, result)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefNetAddresses.list')
    def test__get_host_addresses(self, list_addresses):
        expected = ['1.1.1.1', '2.2.2.2', '3.3.3.3']
        return_value = []
        for address in expected:
            return_value.append({
                'addressType': 'static',
                'address': '%s/24' % address
            })
        list_addresses.return_value = return_value
        result = self.drv._get_host_addresses()
        self.assertEqual(expected, result)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'iscsi.NexentaISCSIDriver._get_host_addresses')
    def test__get_host_portals(self, list_addresses):
        list_addresses.return_value = ['1.1.1.1', '2.2.2.2', '3.3.3.3']
        expected = ['1.1.1.1:3260', '2.2.2.2:3260']
        result = self.drv._get_host_portals()
        self.assertEqual(expected, result)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefTargets.list')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefTargetsGroups.list')
    def test__target_group_props(self, list_target_groups, list_targets):
        host_portals = ['1.1.1.1:3260', '2.2.2.2:3260']
        target_group = 'cinder-test'
        list_target_groups.return_value = [{
            'name': target_group,
            'members': [
                'iqn:cinder-test'
            ]
        }]
        list_targets.return_value = [{
            'name': 'iqn:cinder-test',
            'portals': [
                {
                    'address': '1.1.1.1',
                    'port': 3260
                },
                {
                    'address': '2.2.2.2',
                    'port': 3260
                }
            ]
        }]
        expected = {'iqn:cinder-test': host_portals}
        result = self.drv._target_group_props(target_group, host_portals)
        self.assertEqual(expected, result)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefTargetsGroups.create')
    def test__create_target_group(self, create_target_group):
        name = 'name'
        members = ['a', 'b', 'c']
        create_target_group.return_value = {}
        self.assertIsNone(self.drv._create_target_group(name, members))
        payload = {'name': name, 'members': members}
        create_target_group.assert_called_with(payload)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefTargetsGroups.set')
    def test__update_target_group(self, update_target_group):
        name = 'name'
        members = ['a', 'b', 'c']
        update_target_group.return_value = {}
        self.assertIsNone(self.drv._update_target_group(name, members))
        payload = {'members': members}
        update_target_group.assert_called_with(name, payload)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefLunMappings.delete')
    def test__delete_lun_mapping(self, delete_mapping):
        name = 'name'
        delete_mapping.return_value = {}
        self.assertIsNone(self.drv._delete_lun_mapping(name))
        delete_mapping.assert_called_with(name)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefTargets.create')
    def test__create_target(self, create_target):
        name = 'name'
        portals = ['1.1.1.1:3260', '2.2.2.2:3260']
        create_target.return_value = {}
        self.assertIsNone(self.drv._create_target(name, portals))
        payload = {
            'name': name,
            'portals': [
                {
                    'address': '1.1.1.1',
                    'port': 3260
                },
                {
                    'address': '2.2.2.2',
                    'port': 3260
                }
            ]
        }
        create_target.assert_called_with(payload)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefHostGroups.list')
    def test__get_host_group(self, get_hostgroup):
        member = 'member1'
        get_hostgroup.return_value = [
            {
                'name': 'name1',
                'members': [
                    'member1',
                    'member2',
                    'member3'
                ]
            },
            {
                'name': 'name2',
                'members': [
                    'member4',
                    'member5',
                    'member6'
                ]
            }
        ]
        expected = 'name1'
        result = self.drv._get_host_group(member)
        self.assertEqual(expected, result)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefHostGroups.create')
    def test__create_host_group(self, create_host_group):
        name = 'name'
        members = ['a', 'b', 'c']
        create_host_group.return_value = {}
        self.assertIsNone(self.drv._create_host_group(name, members))
        payload = {'name': name, 'members': members}
        create_host_group.assert_called_with(payload)

    def test__s2d(self):
        portals = ['1.1.1.1:3260', '2.2.2.2:3260']
        expected = [
            {
                'address': '1.1.1.1',
                'port': 3260
            },
            {
                'address': '2.2.2.2',
                'port': 3260
            }
        ]
        result = self.drv._s2d(portals)
        self.assertEqual(expected, result)

    def test__d2s(self):
        portals = [
            {
                'address': '1.1.1.1',
                'port': 3260
            },
            {
                'address': '2.2.2.2',
                'port': 3260
            }
        ]
        expected = ['1.1.1.1:3260', '2.2.2.2:3260']
        result = self.drv._d2s(portals)
        self.assertEqual(expected, result)

    def test_create_consistencygroup(self):
        cgroup = fake_cgroup(self.ctxt)
        result = self.drv.create_consistencygroup(self.ctxt, cgroup)
        expected = {}
        self.assertEqual(expected, result)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'iscsi.NexentaISCSIDriver.delete_volume')
    def test_delete_consistencygroup(self, delete_volume):
        cgroup = fake_cgroup(self.ctxt)
        volume1 = fake_volume(self.ctxt)
        volume2_spec = {'id': fake.VOLUME2_ID}
        volume2 = fake_volume(self.ctxt, **volume2_spec)
        volumes = [volume1, volume2]
        delete_volume.return_value = {}
        result = self.drv.delete_consistencygroup(self.ctxt,
                                                  cgroup,
                                                  volumes)
        expected = ({}, [])
        self.assertEqual(expected, result)

    def test_update_consistencygroup(self):
        cgroup = fake_cgroup(self.ctxt)
        volume1 = fake_volume(self.ctxt)
        volume2_spec = {'id': fake.VOLUME2_ID}
        volume2 = fake_volume(self.ctxt, **volume2_spec)
        volume3_spec = {'id': fake.VOLUME3_ID}
        volume3 = fake_volume(self.ctxt, **volume3_spec)
        volume4_spec = {'id': fake.VOLUME4_ID}
        volume4 = fake_volume(self.ctxt, **volume4_spec)
        add_volumes = [volume1, volume2]
        remove_volumes = [volume3, volume4]
        result = self.drv.update_consistencygroup(self.ctxt,
                                                  cgroup,
                                                  add_volumes,
                                                  remove_volumes)
        expected = ({}, [], [])
        self.assertEqual(expected, result)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefSnapshots.delete')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefSnapshots.rename')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefSnapshots.create')
    def test_create_cgsnapshot(self, create_snapshot,
                               rename_snapshot,
                               delete_snapshot):
        cgsnapshot = fake_cgsnapshot(self.ctxt)
        volume = fake_volume(self.ctxt)
        snapshot = fake_snapshot(self.ctxt)
        snapshot.volume = volume
        snapshots = [snapshot]
        cgsnapshot_name = (
            self.cfg.nexenta_group_snapshot_template % cgsnapshot['id'])
        cgsnapshot_path = '%s@%s' % (self.drv.root_path, cgsnapshot_name)
        snapshot_path = '%s/%s@%s' % (self.drv.root_path,
                                      snapshot['volume_name'],
                                      cgsnapshot_name)
        create_snapshot.return_value = {}
        rename_snapshot.return_value = {}
        delete_snapshot.return_value = {}
        result = self.drv.create_cgsnapshot(self.ctxt,
                                            cgsnapshot,
                                            snapshots)
        create_payload = {'path': cgsnapshot_path, 'recursive': True}
        create_snapshot.assert_called_with(create_payload)
        rename_payload = {'newName': snapshot['name']}
        rename_snapshot.assert_called_with(snapshot_path, rename_payload)
        delete_payload = {'defer': True, 'recursive': True}
        delete_snapshot.assert_called_with(cgsnapshot_path, delete_payload)
        expected = ({}, [])
        self.assertEqual(expected, result)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'iscsi.NexentaISCSIDriver.delete_snapshot')
    def test_delete_cgsnapshot(self, delete_snapshot):
        cgsnapshot = fake_cgsnapshot(self.ctxt)
        volume = fake_volume(self.ctxt)
        snapshot = fake_snapshot(self.ctxt)
        snapshot.volume = volume
        snapshots = [snapshot]
        delete_snapshot.return_value = {}
        result = self.drv.delete_cgsnapshot(self.ctxt,
                                            cgsnapshot,
                                            snapshots)
        delete_snapshot.assert_called_with(snapshot)
        expected = ({}, [])
        self.assertEqual(expected, result)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'iscsi.NexentaISCSIDriver.create_volume_from_snapshot')
    def test_create_consistencygroup_from_src_snapshots(self, create_volume):
        cgroup = fake_cgroup(self.ctxt)
        cgsnapshot = fake_cgsnapshot(self.ctxt)
        volume = fake_volume(self.ctxt)
        snapshot = fake_snapshot(self.ctxt)
        snapshot.volume = volume
        snapshots = [snapshot]
        clone_spec = {'id': fake.VOLUME2_ID}
        clone = fake_volume(self.ctxt, **clone_spec)
        clones = [clone]
        create_volume.return_value = {}
        result = self.drv.create_consistencygroup_from_src(self.ctxt, cgroup,
                                                           clones, cgsnapshot,
                                                           snapshots, None,
                                                           None)
        create_volume.assert_called_with(clone, snapshot)
        expected = ({}, [])
        self.assertEqual(expected, result)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefSnapshots.delete')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'iscsi.NexentaISCSIDriver.create_volume_from_snapshot')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefSnapshots.create')
    def test_create_consistencygroup_from_src_volumes(self,
                                                      create_snapshot,
                                                      create_volume,
                                                      delete_snapshot):
        src_cgroup = fake_cgroup(self.ctxt)
        dst_cgroup_spec = {'id': fake.CONSISTENCY_GROUP2_ID}
        dst_cgroup = fake_cgroup(self.ctxt, **dst_cgroup_spec)
        src_volume = fake_volume(self.ctxt)
        src_volumes = [src_volume]
        dst_volume_spec = {'id': fake.VOLUME2_ID}
        dst_volume = fake_volume(self.ctxt, **dst_volume_spec)
        dst_volumes = [dst_volume]
        create_snapshot.return_value = {}
        create_volume.return_value = {}
        delete_snapshot.return_value = {}
        result = self.drv.create_consistencygroup_from_src(self.ctxt,
                                                           dst_cgroup,
                                                           dst_volumes,
                                                           None, None,
                                                           src_cgroup,
                                                           src_volumes)
        snapshot_name = (
            self.cfg.nexenta_origin_snapshot_template % dst_cgroup['id'])
        snapshot_path = '%s@%s' % (self.drv.root_path, snapshot_name)
        create_payload = {'path': snapshot_path, 'recursive': True}
        create_snapshot.assert_called_with(create_payload)
        snapshot = {
            'name': snapshot_name,
            'volume_id': src_volume['id'],
            'volume_name': src_volume['name'],
            'volume_size': src_volume['size']
        }
        create_volume.assert_called_with(dst_volume, snapshot)
        delete_payload = {'defer': True, 'recursive': True}
        delete_snapshot.assert_called_with(snapshot_path, delete_payload)
        expected = ({}, [])
        self.assertEqual(expected, result)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefVolumes.list')
    def test__get_existing_volume(self, list_volumes):
        volume = fake_volume(self.ctxt)
        parent = self.drv.root_path
        name = volume['name']
        size = volume['size']
        path = self.drv._get_volume_path(volume)
        list_volumes.return_value = [{
            'name': name,
            'path': path,
            'volumeSize': size * units.Gi
        }]
        result = self.drv._get_existing_volume({'source-name': name})
        payload = {
            'parent': parent,
            'fields': 'name,path,volumeSize',
            'name': name
        }
        list_volumes.assert_called_with(payload)
        expected = {
            'name': name,
            'path': path,
            'size': size
        }
        self.assertEqual(expected, result)

    def test__check_already_managed_snapshot(self):
        volume = fake_volume(self.ctxt)
        snapshot = fake_snapshot(self.ctxt)
        snapshot.volume = volume
        result = self.drv._check_already_managed_snapshot(snapshot)
        expected = False
        self.assertEqual(expected, result)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefSnapshots.list')
    def test__get_existing_snapshot(self, list_snapshots):
        volume = fake_volume(self.ctxt)
        snapshot = fake_snapshot(self.ctxt)
        snapshot.volume = volume
        name = snapshot['name']
        path = self.drv._get_snapshot_path(snapshot)
        parent = self.drv._get_volume_path(volume)
        list_snapshots.return_value = [{
            'name': name,
            'path': path
        }]
        payload = {'source-name': name}
        result = self.drv._get_existing_snapshot(snapshot, payload)
        payload = {
            'parent': parent,
            'fields': 'name,path',
            'recursive': False,
            'name': name
        }
        list_snapshots.assert_called_with(payload)
        expected = {
            'name': name,
            'path': path,
            'volume_name': volume['name'],
            'volume_size': volume['size']
        }
        self.assertEqual(expected, result)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefVolumes.rename')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefLunMappings.list')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'iscsi.NexentaISCSIDriver._get_existing_volume')
    def test_manage_existing(self, get_existing_volume,
                             list_mappings, rename_volume):
        existing_volume = fake_volume(self.ctxt)
        manage_volume_spec = {'id': fake.VOLUME2_ID}
        manage_volume = fake_volume(self.ctxt, **manage_volume_spec)
        existing_name = existing_volume['name']
        existing_path = self.drv._get_volume_path(existing_volume)
        existing_size = existing_volume['size']
        manage_path = self.drv._get_volume_path(manage_volume)
        get_existing_volume.return_value = {
            'name': existing_name,
            'path': existing_path,
            'size': existing_size
        }
        list_mappings.return_value = []
        payload = {'source-name': existing_name}
        self.assertIsNone(self.drv.manage_existing(manage_volume, payload))
        get_existing_volume.assert_called_with(payload)
        payload = {'volume': existing_path}
        list_mappings.assert_called_with(payload)
        payload = {'newPath': manage_path}
        rename_volume.assert_called_with(existing_path, payload)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.iscsi.'
                'NexentaISCSIDriver._get_existing_volume')
    def test_manage_existing_get_size(self, get_volume):
        volume = fake_volume(self.ctxt)
        name = volume['name']
        size = volume['size']
        path = self.drv._get_volume_path(volume)
        get_volume.return_value = {
            'name': name,
            'path': path,
            'size': size
        }
        payload = {'source-name': name}
        result = self.drv.manage_existing_get_size(volume, payload)
        expected = size
        self.assertEqual(expected, result)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefVolumes.list')
    def test_get_manageable_volumes(self, list_volumes):
        volume = fake_volume(self.ctxt)
        volumes = [volume]
        name = volume['name']
        size = volume['size']
        path = self.drv._get_volume_path(volume)
        guid = 12345
        parent = self.drv.root_path
        list_volumes.return_value = [{
            'name': name,
            'path': path,
            'guid': guid,
            'volumeSize': size * units.Gi
        }]
        result = self.drv.get_manageable_volumes(volumes, None, 1,
                                                 0, 'size', 'asc')
        payload = {
            'parent': parent,
            'fields': 'name,guid,path,volumeSize',
            'recursive': False
        }
        list_volumes.assert_called_with(payload)
        expected = [{
            'cinder_id': volume['id'],
            'extra_info': None,
            'reason_not_safe': 'Volume already managed',
            'reference': {
                'source-guid': guid,
                'source-name': volume['name']
            },
            'safe_to_manage': False,
            'size': volume['size']
        }]
        self.assertEqual(expected, result)

    def test_unmanage(self):
        volume = fake_volume(self.ctxt)
        self.assertIsNone(self.drv.unmanage(volume))

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefSnapshots.rename')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'iscsi.NexentaISCSIDriver._get_existing_snapshot')
    def test_manage_existing_snapshot(self, get_existing_snapshot,
                                      rename_snapshot):
        volume = fake_volume(self.ctxt)
        existing_snapshot = fake_snapshot(self.ctxt)
        existing_snapshot.volume = volume
        manage_snapshot_spec = {'id': fake.SNAPSHOT2_ID}
        manage_snapshot = fake_snapshot(self.ctxt, **manage_snapshot_spec)
        manage_snapshot.volume = volume
        existing_name = existing_snapshot['name']
        manage_name = manage_snapshot['name']
        volume_name = volume['name']
        volume_size = volume['size']
        existing_path = self.drv._get_snapshot_path(existing_snapshot)
        get_existing_snapshot.return_value = {
            'name': existing_name,
            'path': existing_path,
            'volume_name': volume_name,
            'volume_size': volume_size
        }
        rename_snapshot.return_value = {}
        payload = {'source-name': existing_name}
        self.assertIsNone(
            self.drv.manage_existing_snapshot(manage_snapshot, payload)
        )
        get_existing_snapshot.assert_called_with(manage_snapshot, payload)
        payload = {'newName': manage_name}
        rename_snapshot.assert_called_with(existing_path, payload)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'iscsi.NexentaISCSIDriver._get_existing_snapshot')
    def test_manage_existing_snapshot_get_size(self, get_snapshot):
        volume = fake_volume(self.ctxt)
        snapshot = fake_snapshot(self.ctxt)
        snapshot.volume = volume
        snapshot_name = snapshot['name']
        volume_name = volume['name']
        volume_size = volume['size']
        snapshot_path = self.drv._get_snapshot_path(snapshot)
        get_snapshot.return_value = {
            'name': snapshot_name,
            'path': snapshot_path,
            'volume_name': volume_name,
            'volume_size': volume_size
        }
        payload = {'source-name': snapshot_name}
        result = self.drv.manage_existing_snapshot_get_size(volume, payload)
        expected = volume['size']
        self.assertEqual(expected, result)

    @mock.patch('cinder.objects.VolumeList.get_all_by_host')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefSnapshots.list')
    def test_get_manageable_snapshots(self, list_snapshots, list_volumes):
        volume = fake_volume(self.ctxt)
        volumes = [volume]
        snapshot = fake_snapshot(self.ctxt)
        snapshot.volume = volume
        snapshots = [snapshot]
        guid = 12345
        name = snapshot['name']
        path = self.drv._get_snapshot_path(snapshot)
        parent = self.drv._get_volume_path(volume)
        list_snapshots.return_value = [{
            'name': name,
            'path': path,
            'guid': guid,
            'parent': parent,
            'hprService': '',
            'snaplistId': ''
        }]
        list_volumes.return_value = volumes
        result = self.drv.get_manageable_snapshots(snapshots, None, 1,
                                                   0, 'size', 'asc')
        payload = {
            'parent': self.drv.root_path,
            'fields': 'name,guid,path,parent,hprService,snaplistId',
            'recursive': True
        }
        list_snapshots.assert_called_with(payload)
        expected = [{
            'cinder_id': snapshot['id'],
            'extra_info': None,
            'reason_not_safe': 'Snapshot already managed',
            'source_reference': {
                'name': volume['name']
            },
            'reference': {
                'source-guid': guid,
                'source-name': snapshot['name']
            },
            'safe_to_manage': False,
            'size': volume['size']
        }]
        self.assertEqual(expected, result)

    def test_unmanage_snapshot(self):
        volume = fake_volume(self.ctxt)
        snapshot = fake_snapshot(self.ctxt)
        snapshot.volume = volume
        self.assertIsNone(self.drv.unmanage_snapshot(snapshot))
