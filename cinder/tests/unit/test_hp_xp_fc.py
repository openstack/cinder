# Copyright (C) 2015, Hitachi, Ltd.
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
#

import mock

from cinder import exception
from cinder import test
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder.volume import configuration as conf
from cinder.volume import driver
from cinder.volume.drivers.san.hp import hp_xp_fc
from cinder.volume.drivers.san.hp import hp_xp_opts

from oslo_config import cfg
from oslo_utils import importutils
CONF = cfg.CONF

NORMAL_LDEV_TYPE = 'Normal'
POOL_INFO = {'30': {'total_gb': 'infinite', 'free_gb': 'infinite'}}
EXISTING_POOL_REF = {
    '101': {'size': 128}
}


class HPXPFakeCommon(object):
    """Fake HPXP Common."""

    def __init__(self, conf, storage_protocol, **kwargs):
        self.conf = conf
        self.volumes = {}
        self.snapshots = {}
        self._stats = {}
        self.POOL_SIZE = 1000
        self.LDEV_MAX = 1024

        self.driver_info = {
            'hba_id': 'wwpns',
            'hba_id_type': 'World Wide Name',
            'msg_id': {'target': 308},
            'volume_backend_name': 'HPXPFC',
            'volume_opts': hp_xp_opts.FC_VOLUME_OPTS,
            'volume_type': 'fibre_channel',
        }

        self.storage_info = {
            'protocol': storage_protocol,
            'pool_id': None,
            'ldev_range': None,
            'ports': [],
            'compute_ports': [],
            'wwns': {},
            'output_first': True
        }

    def create_volume(self, volume):
        if volume['size'] > self.POOL_SIZE:
            raise exception.VolumeBackendAPIException(
                data='The volume size (%s) exceeds the pool size (%s).' %
                (volume['size'], self.POOL_SIZE))

        newldev = self._available_ldev()
        self.volumes[newldev] = volume

        return {
            'provider_location': newldev,
            'metadata': {
                'ldev': newldev,
                'type': NORMAL_LDEV_TYPE
            }
        }

    def _available_ldev(self):
        for i in range(1, self.LDEV_MAX):
            if self.volume_exists({'provider_location': str(i)}) is False:
                return str(i)

        raise exception.VolumeBackendAPIException(
            data='Failed to get an available logical device.')

    def volume_exists(self, volume):
        return self.volumes.get(volume['provider_location'], None) is not None

    def delete_volume(self, volume):
        vol = self.volumes.get(volume['provider_location'], None)
        if vol is not None:
            if vol.get('is_busy') is True:
                raise exception.VolumeIsBusy(volume_name=volume['name'])
            del self.volumes[volume['provider_location']]

    def create_snapshot(self, snapshot):
        src_vref = self.volumes.get(snapshot["volume_id"])
        if not src_vref:
            raise exception.VolumeBackendAPIException(
                data='The %(type)s %(id)s source to be replicated was not '
                'found.' % {'type': 'snapshot', 'id': (snapshot.get('id'))})

        newldev = self._available_ldev()
        self.volumes[newldev] = snapshot

        return {'provider_location': newldev}

    def delete_snapshot(self, snapshot):
        snap = self.volumes.get(snapshot['provider_location'], None)
        if snap is not None:
            if snap.get('is_busy') is True:
                raise exception.SnapshotIsBusy(snapshot_name=snapshot['name'])
            del self.volumes[snapshot['provider_location']]

    def get_volume_stats(self, refresh=False):
        if refresh:
            d = {}
            d['volume_backend_name'] = self.driver_info['volume_backend_name']
            d['vendor_name'] = 'Hewlett-Packard'
            d['driver_version'] = '1.3.0-0_2015.1'
            d['storage_protocol'] = self.storage_info['protocol']
            pool_info = POOL_INFO.get(self.conf.hpxp_pool)
            if pool_info is None:
                return self._stats
            d['total_capacity_gb'] = pool_info['total_gb']
            d['free_capacity_gb'] = pool_info['free_gb']
            d['allocated_capacity_gb'] = 0
            d['reserved_percentage'] = 0
            d['QoS_support'] = False
            self._stats = d
        return self._stats

    def create_volume_from_snapshot(self, volume, snapshot):
        ldev = snapshot.get('provider_location')
        if self.volumes.get(ldev) is None:
            raise exception.VolumeBackendAPIException(
                data='The %(type)s %(id)s source to be replicated '
                'was not found.' % {'type': 'snapshot', 'id': snapshot['id']})
        if volume['size'] != snapshot['volume_size']:
            raise exception.VolumeBackendAPIException(
                data='The specified operation is not supported. '
                'The volume size must be the same as the source %(type)s. '
                '(volume: %(volume_id)s)'
                % {'type': 'snapshot', 'volume_id': volume['id']})

        newldev = self._available_ldev()
        self.volumes[newldev] = volume

        return {
            'provider_location': newldev,
            'metadata': {
                'ldev': newldev,
                'type': NORMAL_LDEV_TYPE,
                'snapshot': snapshot['id']
            }
        }

    def create_cloned_volume(self, volume, src_vref):
        ldev = src_vref.get('provider_location')
        if self.volumes.get(ldev) is None:
            raise exception.VolumeBackendAPIException(
                data='The %(type)s %(id)s source to be replicated was not '
                'found.' % {'type': 'volume', 'id': src_vref.get('id')})
        if volume['size'] != src_vref['size']:
            raise exception.VolumeBackendAPIException(
                data='The specified operation is not supported. '
                'The volume size must be the same as the source %(type)s. '
                '(volume: %(volume_id)s)' %
                {'type': 'volume', 'volume_id': volume['id']})

        newldev = self._available_ldev()
        self.volumes[newldev] = volume

        return {
            'provider_location': newldev,
            'metadata': {
                'ldev': newldev,
                'type': NORMAL_LDEV_TYPE,
                'volume': src_vref['id']
            }
        }

    def extend_volume(self, volume, new_size):
        ldev = volume.get('provider_location')
        if not self.volumes.get(ldev):
            raise exception.VolumeBackendAPIException(
                data='The volume %(volume_id)s to be extended was not found.' %
                {'volume_id': volume['id']})
        if new_size > self.POOL_SIZE:
            raise exception.VolumeBackendAPIException(
                data='The volume size (%s) exceeds the pool size (%s).' %
                (new_size, self.POOL_SIZE))

        self.volumes[ldev]['size'] = new_size

    def manage_existing(self, volume, existing_ref):
        ldev = existing_ref.get('source-id')

        return {
            'provider_location': ldev,
            'metadata': {
                'ldev': ldev,
                'type': NORMAL_LDEV_TYPE
            }
        }

    def manage_existing_get_size(self, dummy_volume, existing_ref):
        ldev = existing_ref.get('source-id')
        if not EXISTING_POOL_REF.get(ldev):
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_ref, reason='No valid value is '
                'specified for "source-id". A valid value '
                'must be specified for "source-id" to manage the volume.')

        size = EXISTING_POOL_REF[ldev]['size']
        return size

    def unmanage(self, volume):
        vol = self.volumes.get(volume['provider_location'], None)
        if vol is not None:
            if vol.get('is_busy') is True:
                raise exception.VolumeIsBusy(
                    volume_name=volume['provider_location'])
            del self.volumes[volume['provider_location']]

    def get_pool_id(self):
        pool = self.conf.hpxp_pool
        if pool.isdigit():
            return int(pool)
        return None

    def do_setup(self, context):
        self.ctxt = context
        self.storage_info['pool_id'] = self.get_pool_id()
        if self.storage_info['pool_id'] is None:
            raise exception.VolumeBackendAPIException(
                data='A pool could not be found. (pool: %(pool)s)' %
                {'pool': self.conf.hpxp_pool})

    def initialize_connection(self, volume, connector):
        ldev = volume.get('provider_location')
        if not self.volumes.get(ldev):
            raise exception.VolumeBackendAPIException(
                data='The volume %(volume_id)s to be mapped was not found.' %
                {'volume_id': volume['id']})

        self.volumes[ldev]['attached'] = connector

        return {
            'driver_volume_type': self.driver_info['volume_type'],
            'data': {
                'target_discovered': True,
                'target_lun': volume['id'],
                'access_mode': 'rw',
                'multipath': True,
                'target_wwn': ['50060E801053C2E0'],
                'initiator_target_map': {
                    u'2388000087e1a2e0': ['50060E801053C2E0']},
            }
        }

    def terminate_connection(self, volume, connector):
        ldev = volume.get('provider_location')
        if not self.volumes.get(ldev):
            return
        if not self.is_volume_attached(volume, connector):
            raise exception.VolumeBackendAPIException(
                data='Volume not found for %s' % ldev)

        del self.volumes[volume['provider_location']]['attached']

        for vol in self.volumes:
            if 'attached' in self.volumes[vol]:
                return

        return {
            'driver_volume_type': self.driver_info['volume_type'],
            'data': {
                'target_lun': volume['id'],
                'target_wwn': ['50060E801053C2E0'],
                'initiator_target_map': {
                    u'2388000087e1a2e0': ['50060E801053C2E0']},
            }
        }

    def is_volume_attached(self, volume, connector):
        if not self.volume_exists(volume):
            return False
        return (self.volumes[volume['provider_location']].get('attached', None)
                == connector)

    def copy_volume_data(self, context, src_vol, dest_vol, remote=None):
        pass

    def copy_image_to_volume(self, context, volume, image_service, image_id):
        pass

    def restore_backup(self, context, backup, volume, backup_service):
        pass


class HPXPFCDriverTest(test.TestCase):
    """Test HPXPFCDriver."""

    _VOLUME = {'size': 128,
               'name': 'test1',
               'id': 'id1',
               'status': 'available'}

    _VOLUME2 = {'size': 128,
                'name': 'test2',
                'id': 'id2',
                'status': 'available'}

    _VOLUME3 = {'size': 256,
                'name': 'test2',
                'id': 'id3',
                'status': 'available'}

    _VOLUME_BACKUP = {'size': 128,
                      'name': 'backup-test',
                      'id': 'id-backup',
                      'provider_location': '0',
                      'status': 'available'}

    _TEST_SNAPSHOT = {'volume_name': 'test',
                      'size': 128,
                      'volume_size': 128,
                      'name': 'test-snap',
                      'volume_id': '1',
                      'id': 'test-snap-0',
                      'status': 'available'}

    _TOO_BIG_VOLUME_SIZE = 100000

    def __init__(self, *args, **kwargs):
        super(HPXPFCDriverTest, self).__init__(*args, **kwargs)

    def setUp(self):
        self._setup_config()
        self._setup_driver()
        super(HPXPFCDriverTest, self).setUp()

    def _setup_config(self):
        self.configuration = mock.Mock(conf.Configuration)
        self.configuration.hpxp_storage_id = "00000"
        self.configuration.hpxp_pool = "30"

    @mock.patch.object(importutils, 'import_object', return_value=None)
    def _setup_driver(self, arg1):
        self.driver = hp_xp_fc.HPXPFCDriver(configuration=self.configuration)
        self.driver.common = HPXPFakeCommon(self.configuration, 'FC')
        self.driver.do_setup(None)

    # API test cases
    def test_create_volume(self):
        """Test create_volume."""
        volume = fake_volume.fake_db_volume(**self._VOLUME)
        rc = self.driver.create_volume(volume)
        volume['provider_location'] = rc['provider_location']

        has_volume = self.driver.common.volume_exists(volume)
        self.assertTrue(has_volume)

    def test_create_volume_error_on_no_pool_space(self):
        """Test create_volume is error on no pool space."""
        update = {
            'size': self._TOO_BIG_VOLUME_SIZE,
            'name': 'test',
            'id': 'id1',
            'status': 'available'
        }
        volume = fake_volume.fake_db_volume(**update)

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume, volume)

    def test_create_volume_error_on_no_available_ldev(self):
        """Test create_volume is error on no available ldev."""
        for i in range(1, 1024):
            volume = fake_volume.fake_db_volume(**self._VOLUME)
            rc = self.driver.create_volume(volume)
            self.assertEqual(str(i), rc['provider_location'])

        volume = fake_volume.fake_db_volume(**self._VOLUME)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume, volume)

    def test_delete_volume(self):
        """Test delete_volume."""
        volume = fake_volume.fake_db_volume(**self._VOLUME)
        rc = self.driver.create_volume(volume)
        volume['provider_location'] = rc['provider_location']

        self.driver.delete_volume(volume)

        has_volume = self.driver.common.volume_exists(volume)
        self.assertFalse(has_volume)

    def test_delete_volume_on_non_existing_volume(self):
        """Test delete_volume on non existing volume."""
        volume = fake_volume.fake_db_volume(**self._VOLUME)
        volume['provider_location'] = '1'
        has_volume = self.driver.common.volume_exists(volume)
        self.assertFalse(has_volume)

        self.driver.delete_volume(volume)

    def test_delete_volume_error_on_busy_volume(self):
        """Test delete_volume is error on busy volume."""
        volume = fake_volume.fake_db_volume(**self._VOLUME)
        rc = self.driver.create_volume(volume)
        self.driver.common.volumes[rc['provider_location']]['is_busy'] = True

        volume['provider_location'] = rc['provider_location']

        self.assertRaises(exception.VolumeIsBusy,
                          self.driver.delete_volume, volume)

    def test_create_snapshot(self):
        """Test create_snapshot."""
        volume = fake_volume.fake_db_volume(**self._VOLUME)
        self.driver.create_volume(volume)

        snapshot = fake_snapshot.fake_db_snapshot(**self._TEST_SNAPSHOT)
        rc = self.driver.create_snapshot(snapshot)
        snapshot['provider_location'] = rc['provider_location']

        has_volume = self.driver.common.volume_exists(snapshot)
        self.assertTrue(has_volume)

    def test_create_snapshot_error_on_non_src_ref(self):
        """Test create_snapshot is error on non source reference."""
        snapshot = fake_snapshot.fake_db_snapshot(**self._TEST_SNAPSHOT)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_snapshot,
                          snapshot)

    def test_delete_snapshot(self):
        """Test delete_snapshot."""
        volume = fake_volume.fake_db_volume(**self._VOLUME)
        self.driver.create_volume(volume)

        snapshot = fake_snapshot.fake_db_snapshot(**self._TEST_SNAPSHOT)
        rc = self.driver.create_snapshot(snapshot)
        snapshot['provider_location'] = rc['provider_location']

        rc = self.driver.delete_snapshot(snapshot)

        has_volume = self.driver.common.volume_exists(snapshot)
        self.assertFalse(has_volume)

    def test_delete_snapshot_error_on_busy_snapshot(self):
        """Test delete_snapshot is error on busy snapshot."""
        volume = fake_volume.fake_db_volume(**self._VOLUME)
        self.driver.create_volume(volume)

        snapshot = fake_snapshot.fake_db_snapshot(**self._TEST_SNAPSHOT)
        rc = self.driver.create_snapshot(snapshot)
        self.driver.common.volumes[rc['provider_location']]['is_busy'] = True
        snapshot['provider_location'] = rc['provider_location']

        self.assertRaises(exception.SnapshotIsBusy,
                          self.driver.delete_snapshot,
                          snapshot)

    def test_delete_snapshot_on_non_existing_snapshot(self):
        """Test delete_snapshot on non existing snapshot."""
        snapshot = fake_snapshot.fake_db_snapshot(**self._TEST_SNAPSHOT)
        snapshot['provider_location'] = '1'

        self.driver.delete_snapshot(snapshot)

    def test_create_volume_from_snapshot(self):
        """Test create_volume_from_snapshot."""
        volume = fake_volume.fake_db_volume(**self._VOLUME)
        self.driver.create_volume(volume)

        snapshot = fake_snapshot.fake_db_snapshot(**self._TEST_SNAPSHOT)
        rc_snap = self.driver.create_snapshot(snapshot)
        snapshot['provider_location'] = rc_snap['provider_location']

        volume2 = fake_volume.fake_db_volume(**self._VOLUME2)
        rc = self.driver.create_volume_from_snapshot(volume2, snapshot)
        volume2['provider_location'] = rc['provider_location']

        has_volume = self.driver.common.volume_exists(volume2)
        self.assertTrue(has_volume)

    def test_create_volume_from_snapshot_error_on_non_existing_snapshot(self):
        """Test create_volume_from_snapshot.

        Test create_volume_from_snapshot is error on non existing snapshot.
        """
        volume2 = fake_volume.fake_db_volume(**self._VOLUME2)
        snapshot = fake_snapshot.fake_db_snapshot(**self._TEST_SNAPSHOT)
        snapshot['provider_location'] = '1'

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume_from_snapshot,
                          volume2, snapshot)

    def test_create_volume_from_snapshot_error_on_diff_size(self):
        """Test create_volume_from_snapshot is error on different size."""
        volume = fake_volume.fake_db_volume(**self._VOLUME)
        self.driver.create_volume(volume)

        snapshot = fake_snapshot.fake_db_snapshot(**self._TEST_SNAPSHOT)
        rc_snap = self.driver.create_snapshot(snapshot)
        snapshot['provider_location'] = rc_snap['provider_location']

        volume3 = fake_volume.fake_db_volume(**self._VOLUME3)

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume_from_snapshot,
                          volume3, snapshot)

    def test_create_cloned_volume(self):
        """Test create_cloned_volume."""
        volume = fake_volume.fake_db_volume(**self._VOLUME)
        rc_vol = self.driver.create_volume(volume)
        volume['provider_location'] = rc_vol['provider_location']

        volume2 = fake_volume.fake_db_volume(**self._VOLUME2)
        rc = self.driver.create_cloned_volume(volume2, volume)

        volume2['provider_location'] = rc['provider_location']

        has_volume = self.driver.common.volume_exists(volume2)
        self.assertTrue(has_volume)

    def test_create_cloned_volume_error_on_non_existing_volume(self):
        """Test create_cloned_volume is error on non existing volume."""
        volume = fake_volume.fake_db_volume(**self._VOLUME)
        volume['provider_location'] = '1'
        volume2 = fake_volume.fake_db_volume(**self._VOLUME2)

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_cloned_volume,
                          volume2, volume)

    def test_create_cloned_volume_error_on_diff_size(self):
        """Test create_cloned_volume is error on different size."""
        volume = fake_volume.fake_db_volume(**self._VOLUME)
        rc_vol = self.driver.create_volume(volume)
        volume['provider_location'] = rc_vol['provider_location']

        volume3 = fake_volume.fake_db_volume(**self._VOLUME3)

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_cloned_volume,
                          volume3, volume)

    def test_get_volume_stats(self):
        """Test get_volume_stats."""
        rc = self.driver.get_volume_stats(True)
        self.assertEqual("Hewlett-Packard", rc['vendor_name'])

    def test_get_volume_stats_error_on_non_existing_pool_id(self):
        """Test get_volume_stats is error on non existing pool id."""
        self.configuration.hpxp_pool = 29
        rc = self.driver.get_volume_stats(True)
        self.assertEqual({}, rc)

    @mock.patch.object(driver.FibreChannelDriver, 'copy_volume_data')
    def test_copy_volume_data(self, arg1):
        """Test copy_volume_data."""
        volume = fake_volume.fake_db_volume(**self._VOLUME)
        rc_vol = self.driver.create_volume(volume)
        volume['provider_location'] = rc_vol['provider_location']

        volume2 = fake_volume.fake_db_volume(**self._VOLUME2)
        rc_vol2 = self.driver.create_volume(volume2)
        volume2['provider_location'] = rc_vol2['provider_location']

        self.driver.copy_volume_data(None, volume, volume2, None)

        arg1.assert_called_with(None, volume, volume2, None)

    @mock.patch.object(driver.FibreChannelDriver, 'copy_volume_data',
                       side_effect=exception.CinderException)
    def test_copy_volume_data_error(self, arg1):
        """Test copy_volume_data is error."""
        volume = fake_volume.fake_db_volume(**self._VOLUME)
        rc_vol = self.driver.create_volume(volume)
        volume['provider_location'] = rc_vol['provider_location']

        volume2 = fake_volume.fake_db_volume(**self._VOLUME2)
        volume2['provider_location'] = '2'

        self.assertRaises(exception.CinderException,
                          self.driver.copy_volume_data,
                          None, volume, volume2, None)

        arg1.assert_called_with(None, volume, volume2, None)

    @mock.patch.object(driver.FibreChannelDriver, 'copy_image_to_volume')
    def test_copy_image_to_volume(self, arg1):
        """Test copy_image_to_volume."""
        volume = fake_volume.fake_db_volume(**self._VOLUME)
        rc_vol = self.driver.create_volume(volume)
        volume['provider_location'] = rc_vol['provider_location']

        self.driver.copy_image_to_volume(None, volume, None, None)

        arg1.assert_called_with(None, volume, None, None)

    @mock.patch.object(driver.FibreChannelDriver, 'copy_image_to_volume',
                       side_effect=exception.CinderException)
    def test_copy_image_to_volume_error(self, arg1):
        """Test copy_image_to_volume is error."""
        volume = fake_volume.fake_db_volume(**self._VOLUME)
        volume['provider_location'] = '1'

        self.assertRaises(exception.CinderException,
                          self.driver.copy_image_to_volume,
                          None, volume, None, None)
        arg1.assert_called_with(None, volume, None, None)

    @mock.patch.object(driver.FibreChannelDriver, 'restore_backup')
    def test_restore_backup(self, arg1):
        """Test restore_backup."""
        volume = fake_volume.fake_db_volume(**self._VOLUME)
        rc_vol = self.driver.create_volume(volume)
        volume['provider_location'] = rc_vol['provider_location']

        volume_backup = fake_volume.fake_db_volume(**self._VOLUME_BACKUP)
        self.driver.restore_backup(None, volume_backup, volume, None)
        arg1.assert_called_with(None, volume_backup, volume, None)

    @mock.patch.object(driver.FibreChannelDriver, 'restore_backup',
                       side_effect=exception.CinderException)
    def test_restore_backup_error(self, arg1):
        """Test restore_backup is error."""
        volume = fake_volume.fake_db_volume(**self._VOLUME)
        volume['provider_location'] = '1'

        volume_backup = fake_volume.fake_db_volume(**self._VOLUME_BACKUP)

        self.assertRaises(exception.CinderException,
                          self.driver.restore_backup,
                          None, volume_backup, volume, None)
        arg1.assert_called_with(None, volume_backup, volume, None)

    def test_extend_volume(self):
        """Test extend_volume."""
        volume = fake_volume.fake_db_volume(**self._VOLUME)
        rc = self.driver.create_volume(volume)
        volume['provider_location'] = rc['provider_location']

        new_size = 256
        self.driver.extend_volume(volume, new_size)

        actual = self.driver.common.volumes[rc['provider_location']]['size']
        self.assertEqual(new_size, actual)

    def test_extend_volume_error_on_non_existing_volume(self):
        """Test extend_volume is error on non existing volume."""
        volume = fake_volume.fake_db_volume(**self._VOLUME)
        volume['provider_location'] = '1'

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.extend_volume, volume, 256)

    def test_extend_volume_error_on_no_pool_space(self):
        """Test extend_volume is error on no pool space."""
        volume = fake_volume.fake_db_volume(**self._VOLUME)
        rc = self.driver.create_volume(volume)
        volume['provider_location'] = rc['provider_location']

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.extend_volume,
                          volume, self._TOO_BIG_VOLUME_SIZE)

    def test_manage_existing(self):
        """Test manage_existing."""
        existing_ref = {'source-id': '101'}
        volume = fake_volume.fake_db_volume(**self._VOLUME)
        rc = self.driver.manage_existing(volume, existing_ref)

        self.assertEqual('101', rc['provider_location'])

    def test_manage_existing_with_none_sourceid(self):
        """Test manage_existing is error with no source-id."""
        existing_ref = {'source-id': None}
        volume = fake_volume.fake_db_volume(**self._VOLUME)
        rc = self.driver.manage_existing(volume, existing_ref)

        self.assertEqual(None, rc['provider_location'])

    def test_manage_existing_get_size(self):
        """Test manage_existing_get_size."""
        existing_ref = {'source-id': '101'}
        volume = fake_volume.fake_db_volume(**self._VOLUME)
        return_size = self.driver.manage_existing_get_size(
            volume, existing_ref)
        self.assertEqual(EXISTING_POOL_REF['101']['size'], return_size)

    def test_manage_existing_get_size_with_none_sourceid(self):
        """Test manage_existing_get_size is error with no source-id."""
        existing_ref = {'source-id': None}
        volume = fake_volume.fake_db_volume(**self._VOLUME)
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size,
                          volume, existing_ref)

    def test_unmanage(self):
        """Test unmanage."""
        volume = fake_volume.fake_db_volume(**self._VOLUME)
        rc = self.driver.create_volume(volume)
        volume['provider_location'] = rc['provider_location']
        self.assertTrue(self.driver.common.volume_exists(volume))

        self.driver.unmanage(volume)
        self.assertFalse(self.driver.common.volume_exists(volume))

    def test_unmanage_error_on_busy_volume(self):
        """Test unmanage is error on busy volume."""
        volume = fake_volume.fake_db_volume(**self._VOLUME)
        rc = self.driver.create_volume(volume)
        ldev = rc['provider_location']
        self.driver.common.volumes[ldev]['is_busy'] = True

        self.assertRaises(exception.VolumeIsBusy,
                          self.driver.unmanage,
                          {'provider_location': ldev})

    def test_initialize_connection(self):
        """Test initialize_connection."""
        connector = {'wwpns': ['12345678912345aa', '12345678912345bb'],
                     'ip': '127.0.0.1'}

        volume = fake_volume.fake_db_volume(**self._VOLUME)
        rc_vol = self.driver.create_volume(volume)
        volume['provider_location'] = rc_vol['provider_location']
        conn_info = self.driver.initialize_connection(volume, connector)
        self.assertIn('data', conn_info)
        self.assertIn('initiator_target_map', conn_info['data'])

        is_attached = self.driver.common.is_volume_attached(volume, connector)
        self.assertTrue(is_attached)

        self.driver.terminate_connection(volume, connector)
        self.driver.delete_volume(volume)

    def test_initialize_connection_error_on_non_exisiting_volume(self):
        """Test initialize_connection is error on non existing volume."""
        connector = {'wwpns': ['12345678912345aa', '12345678912345bb'],
                     'ip': '127.0.0.1'}

        volume = fake_volume.fake_db_volume(**self._VOLUME)
        volume['provider_location'] = '1'

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection,
                          volume, connector)

    def test_terminate_connection_on_non_last_volume(self):
        """Test terminate_connection on non last volume."""
        connector = {'wwpns': ['12345678912345aa', '12345678912345bb'],
                     'ip': '127.0.0.1'}
        last_volume = fake_volume.fake_db_volume(**self._VOLUME)
        last_rc_vol = self.driver.create_volume(last_volume)
        last_volume['provider_location'] = last_rc_vol['provider_location']
        self.driver.initialize_connection(last_volume, connector)

        volume = fake_volume.fake_db_volume(**self._VOLUME)
        rc_vol = self.driver.create_volume(volume)
        volume['provider_location'] = rc_vol['provider_location']

        self.driver.initialize_connection(volume, connector)
        conn_info = self.driver.terminate_connection(volume, connector)
        self.assertNotIn('data', conn_info)

        is_attached = self.driver.common.is_volume_attached(volume, connector)
        self.assertFalse(is_attached)

        self.driver.delete_volume(volume)

        self.driver.terminate_connection(last_volume, connector)
        self.driver.delete_volume(last_volume)

    def test_terminate_connection_on_non_existing_volume(self):
        """Test terminate_connection on non existing volume."""
        connector = {'wwpns': ['12345678912345aa', '12345678912345bb'],
                     'ip': '127.0.0.1'}

        volume = fake_volume.fake_db_volume(**self._VOLUME)
        volume['provider_location'] = '1'

        self.driver.terminate_connection(volume, connector)

    def test_terminate_connection_error_on_non_initialized_volume(self):
        """Test terminate_connection is error on non initialized volume."""
        connector = {'wwpns': ['12345678912345aa', '12345678912345bb'],
                     'ip': '127.0.0.1'}
        volume = fake_volume.fake_db_volume(**self._VOLUME)
        rc_vol = self.driver.create_volume(volume)
        volume['provider_location'] = rc_vol['provider_location']

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.terminate_connection,
                          volume, connector)

    def test_terminate_connection_last_volume(self):
        """Test terminate_connection on last volume on a host."""
        connector = {'wwpns': ['12345678912345aa', '12345678912345bb'],
                     'ip': '127.0.0.1'}
        volume = fake_volume.fake_db_volume(**self._VOLUME)
        rc_vol = self.driver.create_volume(volume)
        volume['provider_location'] = rc_vol['provider_location']

        self.driver.initialize_connection(volume, connector)
        conn_info = self.driver.terminate_connection(volume, connector)
        self.assertIn('data', conn_info)
        self.assertIn('initiator_target_map', conn_info['data'])

        is_attached = self.driver.common.is_volume_attached(volume, connector)
        self.assertFalse(is_attached)

        self.driver.delete_volume(volume)

    def test_do_setup_error_on_invalid_pool_id(self):
        """Test do_setup is error on invalid pool id."""
        self.configuration.hpxp_pool = 'invalid'

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.do_setup, None)
