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

import errno
import os
import posixpath
import uuid

from oslo_log import log as logging
from oslo_utils.secretutils import md5
from oslo_utils import units
import six

from cinder import context
from cinder import coordination
from cinder.i18n import _
from cinder import interface
from cinder import objects
from cinder.privsep import fs
from cinder.volume.drivers.nexenta.ns5 import jsonrpc
from cinder.volume.drivers.nexenta import options
from cinder.volume.drivers import nfs
from cinder.volume import volume_utils

LOG = logging.getLogger(__name__)


@interface.volumedriver
class NexentaNfsDriver(nfs.NfsDriver):
    """Executes volume driver commands on Nexenta Appliance.

    Version history:

    .. code-block:: none

        1.0.0 - Initial driver version.
        1.1.0 - Support for extend volume.
        1.2.0 - Added HTTPS support.
              - Added use of sessions for REST calls.
              - Added abandoned volumes and snapshots cleanup.
        1.3.0 - Failover support.
        1.4.0 - Migrate volume support and new NEF API calls.
        1.5.0 - Revert to snapshot support.
        1.6.0 - Get mountPoint from API to support old style mount points.
              - Mount and umount shares on each operation to avoid mass
                mounts on controller. Clean up mount folders on delete.
        1.6.1 - Fixed volume from image creation.
        1.6.2 - Removed redundant share mount from initialize_connection.
        1.6.3 - Adapted NexentaException for the latest Cinder.
        1.6.4 - Fixed volume mount/unmount.
        1.6.5 - Added driver_ssl_cert_verify for HA failover.
        1.6.6 - Destroy unused snapshots after deletion of it's last clone.
        1.6.7 - Fixed volume migration for HA environment.
        1.6.8 - Added deferred deletion for snapshots.
        1.6.9 - Fixed race between volume/clone deletion.
        1.7.0 - Added consistency group support.
        1.7.1 - Removed redundant hpr/activate call from initialize_connection.
        1.7.2 - Merged upstream changes for umount.
        1.8.0 - Refactored NFS driver.
              - Added pagination support.
              - Added configuration parameters for REST API connect/read
                timeouts, connection retries and backoff factor.
              - Fixed HA failover.
              - Added retries on EBUSY errors.
              - Fixed HTTP authentication.
              - Disabled non-blocking mandatory locks.
              - Added coordination for dataset operations.
        1.8.1 - Support for NexentaStor tenants.
        1.8.2 - Added manage/unmanage/manageable-list volume/snapshot support.
        1.8.3 - Added consistency group capability to generic volume group.
        1.8.4 - Disabled SmartCompression feature.
    """

    VERSION = '1.8.3'
    CI_WIKI_NAME = "Nexenta_CI"

    vendor_name = 'Nexenta'
    product_name = 'NexentaStor5'
    storage_protocol = 'NFS'
    driver_volume_type = 'nfs'

    def __init__(self, *args, **kwargs):
        super(NexentaNfsDriver, self).__init__(*args, **kwargs)
        if not self.configuration:
            message = (_('%(product_name)s %(storage_protocol)s '
                         'backend configuration not found')
                       % {'product_name': self.product_name,
                          'storage_protocol': self.storage_protocol})
            raise jsonrpc.NefException(code='ENODATA', message=message)
        self.configuration.append_config_values(
            options.NEXENTA_CONNECTION_OPTS)
        self.configuration.append_config_values(
            options.NEXENTA_NFS_OPTS)
        self.configuration.append_config_values(
            options.NEXENTA_DATASET_OPTS)
        self.nef = None
        self.volume_backend_name = (
            self.configuration.safe_get('volume_backend_name') or
            '%s_%s' % (self.product_name, self.storage_protocol))
        self.nas_host = self.configuration.nas_host
        self.root_path = self.configuration.nas_share_path
        self.sparsed_volumes = self.configuration.nexenta_sparsed_volumes
        self.deduplicated_volumes = self.configuration.nexenta_dataset_dedup
        self.compressed_volumes = (
            self.configuration.nexenta_dataset_compression)
        self.dataset_description = (
            self.configuration.nexenta_dataset_description)
        self.mount_point_base = self.configuration.nexenta_mount_point_base
        self.group_snapshot_template = (
            self.configuration.nexenta_group_snapshot_template)
        self.origin_snapshot_template = (
            self.configuration.nexenta_origin_snapshot_template)

    @staticmethod
    def get_driver_options():
        return (
            options.NEXENTA_CONNECTION_OPTS +
            options.NEXENTA_NFS_OPTS +
            options.NEXENTA_DATASET_OPTS
        )

    def do_setup(self, context):
        self.nef = jsonrpc.NefProxy(self.driver_volume_type,
                                    self.root_path,
                                    self.configuration)

    def check_for_setup_error(self):
        """Check root filesystem, NFS service and NFS share."""
        filesystem = self.nef.filesystems.get(self.root_path)
        if filesystem['mountPoint'] == 'none':
            message = (_('NFS root filesystem %(path)s is not writable')
                       % {'path': filesystem['mountPoint']})
            raise jsonrpc.NefException(code='ENOENT', message=message)
        if not filesystem['isMounted']:
            message = (_('NFS root filesystem %(path)s is not mounted')
                       % {'path': filesystem['mountPoint']})
            raise jsonrpc.NefException(code='ENOTDIR', message=message)
        payload = {}
        if filesystem['nonBlockingMandatoryMode']:
            payload['nonBlockingMandatoryMode'] = False
        if filesystem['smartCompression']:
            payload['smartCompression'] = False
        if payload:
            self.nef.filesystems.set(self.root_path, payload)
        service = self.nef.services.get('nfs')
        if service['state'] != 'online':
            message = (_('NFS server service is not online: %(state)s')
                       % {'state': service['state']})
            raise jsonrpc.NefException(code='ESRCH', message=message)
        share = self.nef.nfs.get(self.root_path)
        if share['shareState'] != 'online':
            message = (_('NFS share %(share)s is not online: %(state)s')
                       % {'share': self.root_path,
                          'state': share['shareState']})
            raise jsonrpc.NefException(code='ESRCH', message=message)

    def create_volume(self, volume):
        """Creates a volume.

        :param volume: volume reference
        """
        volume_path = self._get_volume_path(volume)
        payload = {'path': volume_path, 'compressionMode': 'off'}
        self.nef.filesystems.create(payload)
        try:
            self._set_volume_acl(volume)
            self._mount_volume(volume)
            volume_file = self.local_path(volume)
            if self.sparsed_volumes:
                self._create_sparsed_file(volume_file, volume['size'])
            else:
                self._create_regular_file(volume_file, volume['size'])
            if self.compressed_volumes != 'off':
                payload = {'compressionMode': self.compressed_volumes}
                self.nef.filesystems.set(volume_path, payload)
        except jsonrpc.NefException as create_error:
            try:
                payload = {'force': True}
                self.nef.filesystems.delete(volume_path, payload)
            except jsonrpc.NefException as delete_error:
                LOG.debug('Failed to delete volume %(path)s: %(error)s',
                          {'path': volume_path, 'error': delete_error})
            raise create_error
        finally:
            self._unmount_volume(volume)

    def copy_image_to_volume(self, context, volume, image_service, image_id):
        LOG.debug('Copy image %(image)s to volume %(volume)s',
                  {'image': image_id, 'volume': volume['name']})
        self._mount_volume(volume)
        super(NexentaNfsDriver, self).copy_image_to_volume(
            context, volume, image_service, image_id)
        self._unmount_volume(volume)

    def copy_volume_to_image(self, context, volume, image_service, image_meta):
        LOG.debug('Copy volume %(volume)s to image %(image)s',
                  {'volume': volume['name'], 'image': image_meta['id']})
        self._mount_volume(volume)
        super(NexentaNfsDriver, self).copy_volume_to_image(
            context, volume, image_service, image_meta)
        self._unmount_volume(volume)

    def _ensure_share_unmounted(self, share):
        """Ensure that NFS share is unmounted on the host.

        :param share: share path
        """
        attempts = max(1, self.configuration.nfs_mount_attempts)
        path = self._get_mount_point_for_share(share)
        if path not in self._remotefsclient._read_mounts():
            LOG.debug('NFS share %(share)s is not mounted at %(path)s',
                      {'share': share, 'path': path})
            return
        for attempt in range(0, attempts):
            try:
                fs.umount(path)
                LOG.debug('NFS share %(share)s has been unmounted at %(path)s',
                          {'share': share, 'path': path})
                break
            except Exception as error:
                if attempt == (attempts - 1):
                    LOG.error('Failed to unmount NFS share %(share)s '
                              'after %(attempts)s attempts',
                              {'share': share, 'attempts': attempts})
                    raise
                LOG.debug('Unmount attempt %(attempt)s failed: %(error)s, '
                          'retrying unmount %(share)s from %(path)s',
                          {'attempt': attempt, 'error': error,
                           'share': share, 'path': path})
                self.nef.delay(attempt)
        self._delete(path)

    def _mount_volume(self, volume):
        """Ensure that volume is activated and mounted on the host."""
        volume_path = self._get_volume_path(volume)
        payload = {'fields': 'mountPoint,isMounted'}
        filesystem = self.nef.filesystems.get(volume_path, payload)
        if filesystem['mountPoint'] == 'none':
            payload = {'datasetName': volume_path}
            self.nef.hpr.activate(payload)
            filesystem = self.nef.filesystems.get(volume_path)
        elif not filesystem['isMounted']:
            self.nef.filesystems.mount(volume_path)
        share = '%s:%s' % (self.nas_host, filesystem['mountPoint'])
        self._ensure_share_mounted(share)

    def _remount_volume(self, volume):
        """Workaround for NEX-16457."""
        volume_path = self._get_volume_path(volume)
        self.nef.filesystems.unmount(volume_path)
        self.nef.filesystems.mount(volume_path)

    def _unmount_volume(self, volume):
        """Ensure that volume is unmounted on the host."""
        share = self._get_volume_share(volume)
        self._ensure_share_unmounted(share)

    def _create_sparsed_file(self, path, size):
        """Creates file with 0 disk usage."""
        if self.configuration.nexenta_qcow2_volumes:
            self._create_qcow2_file(path, size)
        else:
            super(NexentaNfsDriver, self)._create_sparsed_file(path, size)

    def migrate_volume(self, context, volume, host):
        """Migrate if volume and host are managed by Nexenta appliance.

        :param context: context
        :param volume: a dictionary describing the volume to migrate
        :param host: a dictionary describing the host to migrate to
        """
        LOG.debug('Migrate volume %(volume)s to host %(host)s',
                  {'volume': volume['name'], 'host': host})

        false_ret = (False, None)

        if volume['status'] not in ('available', 'retyping'):
            LOG.error('Volume %(volume)s status must be available or '
                      'retyping, current volume status is %(status)s',
                      {'volume': volume['name'], 'status': volume['status']})
            return false_ret

        if 'capabilities' not in host:
            LOG.error('Unsupported host %(host)s: no capabilities found',
                      {'host': host})
            return false_ret

        capabilities = host['capabilities']

        if not ('location_info' in capabilities and
                'vendor_name' in capabilities and
                'free_capacity_gb' in capabilities):
            LOG.error('Unsupported host %(host)s: required NFS '
                      'and vendor capabilities are not found',
                      {'host': host})
            return false_ret

        driver_name = capabilities['location_info'].split(':')[0]
        dst_root = capabilities['location_info'].split(':/')[1]

        if not (capabilities['vendor_name'] == 'Nexenta' and
                driver_name == self.__class__.__name__):
            LOG.error('Unsupported host %(host)s: incompatible '
                      'vendor %(vendor)s or driver %(driver)s',
                      {'host': host,
                       'vendor': capabilities['vendor_name'],
                       'driver': driver_name})
            return false_ret

        if capabilities['free_capacity_gb'] < volume['size']:
            LOG.error('There is not enough space available on the '
                      'host %(host)s to migrate volume %(volume)s, '
                      'free space: %(free)d, required: %(size)d',
                      {'host': host, 'volume': volume['name'],
                       'free': capabilities['free_capacity_gb'],
                       'size': volume['size']})
            return false_ret

        src_path = self._get_volume_path(volume)
        dst_path = posixpath.join(dst_root, volume['name'])
        nef_ips = capabilities['nef_url'].split(',')
        nef_ips.append(None)
        svc = 'cinder-migrate-%s' % volume['name']
        for nef_ip in nef_ips:
            payload = {'name': svc,
                       'sourceDataset': src_path,
                       'destinationDataset': dst_path,
                       'type': 'scheduled',
                       'sendShareNfs': True}
            if nef_ip is not None:
                payload['isSource'] = True
                payload['remoteNode'] = {
                    'host': nef_ip,
                    'port': capabilities['nef_port']
                }
            try:
                self.nef.hpr.create(payload)
                break
            except jsonrpc.NefException as error:
                if nef_ip is None or error.code not in ('EINVAL', 'ENOENT'):
                    LOG.error('Failed to create replication '
                              'service %(payload)s: %(error)s',
                              {'payload': payload, 'error': error})
                    return false_ret

        try:
            self.nef.hpr.start(svc)
        except jsonrpc.NefException as error:
            LOG.error('Failed to start replication '
                      'service %(svc)s: %(error)s',
                      {'svc': svc, 'error': error})
            try:
                payload = {'force': True}
                self.nef.hpr.delete(svc, payload)
            except jsonrpc.NefException as error:
                LOG.error('Failed to delete replication '
                          'service %(svc)s: %(error)s',
                          {'svc': svc, 'error': error})
            return false_ret

        payload = {'destroySourceSnapshots': True,
                   'destroyDestinationSnapshots': True}
        progress = True
        retry = 0
        while progress:
            retry += 1
            hpr = self.nef.hpr.get(svc)
            state = hpr['state']
            if state == 'disabled':
                progress = False
            elif state == 'enabled':
                self.nef.delay(retry)
            else:
                self.nef.hpr.delete(svc, payload)
                return false_ret
        self.nef.hpr.delete(svc, payload)

        try:
            self.delete_volume(volume)
        except jsonrpc.NefException as error:
            LOG.debug('Failed to delete source volume %(volume)s: %(error)s',
                      {'volume': volume['name'], 'error': error})
        return True, None

    def terminate_connection(self, volume, connector, **kwargs):
        """Terminate a connection to a volume.

        :param volume: a volume object
        :param connector: a connector object
        :returns: dictionary of connection information
        """
        LOG.debug('Terminate volume connection for %(volume)s',
                  {'volume': volume['name']})
        self._unmount_volume(volume)

    def initialize_connection(self, volume, connector):
        """Terminate a connection to a volume.

        :param volume: a volume object
        :param connector: a connector object
        :returns: dictionary of connection information
        """
        LOG.debug('Initialize volume connection for %(volume)s',
                  {'volume': volume['name']})
        share = self._get_volume_share(volume)
        return {
            'driver_volume_type': self.driver_volume_type,
            'mount_point_base': self.mount_point_base,
            'data': {
                'export': share,
                'name': 'volume'
            }
        }

    def ensure_export(self, context, volume):
        """Synchronously recreate an export for a volume."""
        pass

    @coordination.synchronized('{self.nef.lock}')
    def delete_volume(self, volume):
        """Deletes a volume.

        :param volume: volume reference
        """
        volume_path = self._get_volume_path(volume)
        self._unmount_volume(volume)
        delete_payload = {'force': True, 'snapshots': True}
        try:
            self.nef.filesystems.delete(volume_path, delete_payload)
        except jsonrpc.NefException as error:
            if error.code != 'EEXIST':
                raise
            snapshots_tree = {}
            snapshots_payload = {'parent': volume_path, 'fields': 'path'}
            snapshots = self.nef.snapshots.list(snapshots_payload)
            for snapshot in snapshots:
                clones_payload = {'fields': 'clones,creationTxg'}
                data = self.nef.snapshots.get(snapshot['path'], clones_payload)
                if data['clones']:
                    snapshots_tree[data['creationTxg']] = data['clones'][0]
            if snapshots_tree:
                clone_path = snapshots_tree[max(snapshots_tree)]
                self.nef.filesystems.promote(clone_path)
            self.nef.filesystems.delete(volume_path, delete_payload)

    def _delete(self, path):
        """Override parent method for safe remove mountpoint."""
        try:
            os.rmdir(path)
            LOG.debug('The mountpoint %(path)s has been successfully removed',
                      {'path': path})
        except OSError as error:
            LOG.debug('Failed to remove mountpoint %(path)s: %(error)s',
                      {'path': path, 'error': error.strerror})

    def extend_volume(self, volume, new_size):
        """Extend an existing volume.

        :param volume: volume reference
        :param new_size: volume new size in GB
        """
        LOG.info('Extend volume %(volume)s, new size: %(size)sGB',
                 {'volume': volume['name'], 'size': new_size})
        self._mount_volume(volume)
        volume_file = self.local_path(volume)
        if self.sparsed_volumes:
            self._execute('truncate', '-s',
                          '%dG' % new_size,
                          volume_file,
                          run_as_root=True)
        else:
            seek = volume['size'] * units.Ki
            count = (new_size - volume['size']) * units.Ki
            self._execute('dd',
                          'if=/dev/zero',
                          'of=%s' % volume_file,
                          'bs=%d' % units.Mi,
                          'seek=%d' % seek,
                          'count=%d' % count,
                          run_as_root=True)
        self._unmount_volume(volume)

    @coordination.synchronized('{self.nef.lock}')
    def create_snapshot(self, snapshot):
        """Creates a snapshot.

        :param snapshot: snapshot reference
        """
        snapshot_path = self._get_snapshot_path(snapshot)
        payload = {'path': snapshot_path}
        self.nef.snapshots.create(payload)

    @coordination.synchronized('{self.nef.lock}')
    def delete_snapshot(self, snapshot):
        """Deletes a snapshot.

        :param snapshot: snapshot reference
        """
        snapshot_path = self._get_snapshot_path(snapshot)
        payload = {'defer': True}
        self.nef.snapshots.delete(snapshot_path, payload)

    def snapshot_revert_use_temp_snapshot(self):
        # Considering that NexentaStor based drivers use COW images
        # for storing snapshots, having chains of such images,
        # creating a backup snapshot when reverting one is not
        # actually helpful.
        return False

    def revert_to_snapshot(self, context, volume, snapshot):
        """Revert volume to snapshot."""
        volume_path = self._get_volume_path(volume)
        payload = {'snapshot': snapshot['name']}
        self.nef.filesystems.rollback(volume_path, payload)

    @coordination.synchronized('{self.nef.lock}')
    def create_volume_from_snapshot(self, volume, snapshot):
        """Create new volume from other's snapshot on appliance.

        :param volume: reference of volume to be created
        :param snapshot: reference of source snapshot
        """
        LOG.debug('Create volume %(volume)s from snapshot %(snapshot)s',
                  {'volume': volume['name'], 'snapshot': snapshot['name']})
        snapshot_path = self._get_snapshot_path(snapshot)
        clone_path = self._get_volume_path(volume)
        payload = {'targetPath': clone_path}
        self.nef.snapshots.clone(snapshot_path, payload)
        self._remount_volume(volume)
        self._set_volume_acl(volume)
        if volume['size'] > snapshot['volume_size']:
            new_size = volume['size']
            volume['size'] = snapshot['volume_size']
            self.extend_volume(volume, new_size)
            volume['size'] = new_size

    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume.

        :param volume: new volume reference
        :param src_vref: source volume reference
        """
        snapshot = {
            'name': self.origin_snapshot_template % volume['id'],
            'volume_id': src_vref['id'],
            'volume_name': src_vref['name'],
            'volume_size': src_vref['size']
        }
        self.create_snapshot(snapshot)
        try:
            self.create_volume_from_snapshot(volume, snapshot)
        except jsonrpc.NefException as error:
            LOG.debug('Failed to create clone %(clone)s '
                      'from volume %(volume)s: %(error)s',
                      {'clone': volume['name'],
                       'volume': src_vref['name'],
                       'error': error})
            raise
        finally:
            try:
                self.delete_snapshot(snapshot)
            except jsonrpc.NefException as error:
                LOG.debug('Failed to delete temporary snapshot '
                          '%(volume)s@%(snapshot)s: %(error)s',
                          {'volume': src_vref['name'],
                           'snapshot': snapshot['name'],
                           'error': error})

    def create_consistencygroup(self, context, group):
        """Creates a consistency group.

        :param context: the context of the caller.
        :param group: the dictionary of the consistency group to be created.
        :returns: group_model_update
        """
        group_model_update = {}
        return group_model_update

    def create_group(self, context, group):
        """Creates a group.

        :param context: the context of the caller.
        :param group: the group object.
        :returns: model_update
        """
        return self.create_consistencygroup(context, group)

    def delete_consistencygroup(self, context, group, volumes):
        """Deletes a consistency group.

        :param context: the context of the caller.
        :param group: the dictionary of the consistency group to be deleted.
        :param volumes: a list of volume dictionaries in the group.
        :returns: group_model_update, volumes_model_update
        """
        group_model_update = {}
        volumes_model_update = []
        for volume in volumes:
            self.delete_volume(volume)
        return group_model_update, volumes_model_update

    def delete_group(self, context, group, volumes):
        """Deletes a group.

        :param context: the context of the caller.
        :param group: the group object.
        :param volumes: a list of volume objects in the group.
        :returns: model_update, volumes_model_update
        """
        return self.delete_consistencygroup(context, group, volumes)

    def update_consistencygroup(self, context, group, add_volumes=None,
                                remove_volumes=None):
        """Updates a consistency group.

        :param context: the context of the caller.
        :param group: the dictionary of the consistency group to be updated.
        :param add_volumes: a list of volume dictionaries to be added.
        :param remove_volumes: a list of volume dictionaries to be removed.
        :returns: group_model_update, add_volumes_update, remove_volumes_update
        """
        group_model_update = {}
        add_volumes_update = []
        remove_volumes_update = []
        return group_model_update, add_volumes_update, remove_volumes_update

    def update_group(self, context, group, add_volumes=None,
                     remove_volumes=None):
        """Updates a group.

        :param context: the context of the caller.
        :param group: the group object.
        :param add_volumes: a list of volume objects to be added.
        :param remove_volumes: a list of volume objects to be removed.
        :returns: model_update, add_volumes_update, remove_volumes_update
        """
        return self.update_consistencygroup(context, group, add_volumes,
                                            remove_volumes)

    def create_cgsnapshot(self, context, cgsnapshot, snapshots):
        """Creates a consistency group snapshot.

        :param context: the context of the caller.
        :param cgsnapshot: the dictionary of the cgsnapshot to be created.
        :param snapshots: a list of snapshot dictionaries in the cgsnapshot.
        :returns: group_model_update, snapshots_model_update
        """
        group_model_update = {}
        snapshots_model_update = []
        cgsnapshot_name = self.group_snapshot_template % cgsnapshot['id']
        cgsnapshot_path = '%s@%s' % (self.root_path, cgsnapshot_name)
        create_payload = {'path': cgsnapshot_path, 'recursive': True}
        self.nef.snapshots.create(create_payload)
        for snapshot in snapshots:
            volume_name = snapshot['volume_name']
            volume_path = posixpath.join(self.root_path, volume_name)
            snapshot_name = snapshot['name']
            snapshot_path = '%s@%s' % (volume_path, cgsnapshot_name)
            rename_payload = {'newName': snapshot_name}
            self.nef.snapshots.rename(snapshot_path, rename_payload)
        delete_payload = {'defer': True, 'recursive': True}
        self.nef.snapshots.delete(cgsnapshot_path, delete_payload)
        return group_model_update, snapshots_model_update

    def create_group_snapshot(self, context, group_snapshot, snapshots):
        """Creates a group_snapshot.

        :param context: the context of the caller.
        :param group_snapshot: the GroupSnapshot object to be created.
        :param snapshots: a list of Snapshot objects in the group_snapshot.
        :returns: model_update, snapshots_model_update
        """
        return self.create_cgsnapshot(context, group_snapshot, snapshots)

    def delete_cgsnapshot(self, context, cgsnapshot, snapshots):
        """Deletes a consistency group snapshot.

        :param context: the context of the caller.
        :param cgsnapshot: the dictionary of the cgsnapshot to be created.
        :param snapshots: a list of snapshot dictionaries in the cgsnapshot.
        :returns: group_model_update, snapshots_model_update
        """
        group_model_update = {}
        snapshots_model_update = []
        for snapshot in snapshots:
            self.delete_snapshot(snapshot)
        return group_model_update, snapshots_model_update

    def delete_group_snapshot(self, context, group_snapshot, snapshots):
        """Deletes a group_snapshot.

        :param context: the context of the caller.
        :param group_snapshot: the GroupSnapshot object to be deleted.
        :param snapshots: a list of snapshot objects in the group_snapshot.
        :returns: model_update, snapshots_model_update
        """
        return self.delete_cgsnapshot(context, group_snapshot, snapshots)

    def create_consistencygroup_from_src(self, context, group, volumes,
                                         cgsnapshot=None, snapshots=None,
                                         source_cg=None, source_vols=None):
        """Creates a consistency group from source.

        :param context: the context of the caller.
        :param group: the dictionary of the consistency group to be created.
        :param volumes: a list of volume dictionaries in the group.
        :param cgsnapshot: the dictionary of the cgsnapshot as source.
        :param snapshots: a list of snapshot dictionaries in the cgsnapshot.
        :param source_cg: the dictionary of a consistency group as source.
        :param source_vols: a list of volume dictionaries in the source_cg.
        :returns: group_model_update, volumes_model_update
        """
        group_model_update = {}
        volumes_model_update = []
        if cgsnapshot and snapshots:
            for volume, snapshot in zip(volumes, snapshots):
                self.create_volume_from_snapshot(volume, snapshot)
        elif source_cg and source_vols:
            snapshot_name = self.origin_snapshot_template % group['id']
            snapshot_path = '%s@%s' % (self.root_path, snapshot_name)
            create_payload = {'path': snapshot_path, 'recursive': True}
            self.nef.snapshots.create(create_payload)
            for volume, source_vol in zip(volumes, source_vols):
                snapshot = {
                    'name': snapshot_name,
                    'volume_id': source_vol['id'],
                    'volume_name': source_vol['name'],
                    'volume_size': source_vol['size']
                }
                self.create_volume_from_snapshot(volume, snapshot)
            delete_payload = {'defer': True, 'recursive': True}
            self.nef.snapshots.delete(snapshot_path, delete_payload)
        return group_model_update, volumes_model_update

    def create_group_from_src(self, context, group, volumes,
                              group_snapshot=None, snapshots=None,
                              source_group=None, source_vols=None):
        """Creates a group from source.

        :param context: the context of the caller.
        :param group: the Group object to be created.
        :param volumes: a list of Volume objects in the group.
        :param group_snapshot: the GroupSnapshot object as source.
        :param snapshots: a list of snapshot objects in group_snapshot.
        :param source_group: the Group object as source.
        :param source_vols: a list of volume objects in the source_group.
        :returns: model_update, volumes_model_update
        """
        return self.create_consistencygroup_from_src(context, group, volumes,
                                                     group_snapshot, snapshots,
                                                     source_group, source_vols)

    def _local_volume_dir(self, volume):
        """Get volume dir (mounted locally fs path) for given volume.

        :param volume: volume reference
        """
        share = self._get_volume_share(volume)
        if isinstance(share, six.text_type):
            share = share.encode('utf-8')
        path = md5(share, usedforsecurity=False).hexdigest()
        return os.path.join(self.mount_point_base, path)

    def local_path(self, volume):
        """Get volume path (mounted locally fs path) for given volume.

        :param volume: volume reference
        """
        volume_dir = self._local_volume_dir(volume)
        return os.path.join(volume_dir, 'volume')

    def _set_volume_acl(self, volume):
        """Sets access permissions for given volume.

        :param volume: volume reference
        """
        volume_path = self._get_volume_path(volume)
        payload = {
            'type': 'allow',
            'principal': 'everyone@',
            'permissions': [
                'full_set'
            ],
            'flags': [
                'file_inherit',
                'dir_inherit'
            ]
        }
        self.nef.filesystems.acl(volume_path, payload)

    def _get_volume_share(self, volume):
        """Return NFS share path for the volume."""
        volume_path = self._get_volume_path(volume)
        payload = {'fields': 'mountPoint'}
        filesystem = self.nef.filesystems.get(volume_path, payload)
        return '%s:%s' % (self.nas_host, filesystem['mountPoint'])

    def _get_volume_path(self, volume):
        """Return ZFS dataset path for the volume."""
        return posixpath.join(self.root_path, volume['name'])

    def _get_snapshot_path(self, snapshot):
        """Return ZFS snapshot path for the snapshot."""
        volume_name = snapshot['volume_name']
        snapshot_name = snapshot['name']
        volume_path = posixpath.join(self.root_path, volume_name)
        return '%s@%s' % (volume_path, snapshot_name)

    def _update_volume_stats(self):
        """Retrieve stats info for NexentaStor Appliance."""
        LOG.debug('Updating volume backend %(volume_backend_name)s stats',
                  {'volume_backend_name': self.volume_backend_name})
        payload = {'fields': 'mountPoint,bytesAvailable,bytesUsed'}
        dataset = self.nef.filesystems.get(self.root_path, payload)
        free = dataset['bytesAvailable'] // units.Gi
        used = dataset['bytesUsed'] // units.Gi
        total = free + used
        share = '%s:%s' % (self.nas_host, dataset['mountPoint'])
        location_info = '%(driver)s:%(share)s' % {
            'driver': self.__class__.__name__,
            'share': share
        }
        self._stats = {
            'vendor_name': self.vendor_name,
            'dedup': self.deduplicated_volumes,
            'compression': self.compressed_volumes,
            'description': self.dataset_description,
            'nef_url': self.nef.host,
            'nef_port': self.nef.port,
            'driver_version': self.VERSION,
            'storage_protocol': self.storage_protocol,
            'sparsed_volumes': self.sparsed_volumes,
            'total_capacity_gb': total,
            'free_capacity_gb': free,
            'reserved_percentage': self.configuration.reserved_percentage,
            'QoS_support': False,
            'multiattach': True,
            'consistencygroup_support': True,
            'consistent_group_snapshot_enabled': True,
            'location_info': location_info,
            'volume_backend_name': self.volume_backend_name,
            'nfs_mount_point_base': self.mount_point_base
        }

    def _get_existing_volume(self, existing_ref):
        types = {
            'source-name': 'path',
            'source-guid': 'guid'
        }
        if not any(key in types for key in existing_ref):
            keys = ', '.join(types.keys())
            message = (_('Manage existing volume failed '
                         'due to invalid backend reference. '
                         'Volume reference must contain '
                         'at least one valid key: %(keys)s')
                       % {'keys': keys})
            raise jsonrpc.NefException(code='EINVAL', message=message)
        payload = {
            'parent': self.root_path,
            'fields': 'path',
            'recursive': False
        }
        for key, value in types.items():
            if key in existing_ref:
                if value == 'path':
                    path = posixpath.join(self.root_path,
                                          existing_ref[key])
                else:
                    path = existing_ref[key]
                payload[value] = path
        existing_volumes = self.nef.filesystems.list(payload)
        if len(existing_volumes) == 1:
            volume_path = existing_volumes[0]['path']
            volume_name = posixpath.basename(volume_path)
            existing_volume = {
                'name': volume_name,
                'path': volume_path
            }
            vid = volume_utils.extract_id_from_volume_name(volume_name)
            if volume_utils.check_already_managed_volume(vid):
                message = (_('Volume %(name)s already managed')
                           % {'name': volume_name})
                raise jsonrpc.NefException(code='EBUSY', message=message)
            return existing_volume
        elif not existing_volumes:
            code = 'ENOENT'
            reason = _('no matching volumes were found')
        else:
            code = 'EINVAL'
            reason = _('too many volumes were found')
        message = (_('Unable to manage existing volume by '
                     'reference %(reference)s: %(reason)s')
                   % {'reference': existing_ref, 'reason': reason})
        raise jsonrpc.NefException(code=code, message=message)

    def _check_already_managed_snapshot(self, snapshot_id):
        """Check cinder database for already managed snapshot.

        :param snapshot_id: snapshot id parameter
        :returns: return True, if database entry with specified
                  snapshot id exists, otherwise return False
        """
        if not isinstance(snapshot_id, six.string_types):
            return False
        try:
            uuid.UUID(snapshot_id, version=4)
        except ValueError:
            return False
        ctxt = context.get_admin_context()
        return objects.Snapshot.exists(ctxt, snapshot_id)

    def _get_existing_snapshot(self, snapshot, existing_ref):
        types = {
            'source-name': 'name',
            'source-guid': 'guid'
        }
        if not any(key in types for key in existing_ref):
            keys = ', '.join(types.keys())
            message = (_('Manage existing snapshot failed '
                         'due to invalid backend reference. '
                         'Snapshot reference must contain '
                         'at least one valid key: %(keys)s')
                       % {'keys': keys})
            raise jsonrpc.NefException(code='EINVAL', message=message)
        volume_name = snapshot['volume_name']
        volume_size = snapshot['volume_size']
        volume = {'name': volume_name}
        volume_path = self._get_volume_path(volume)
        payload = {
            'parent': volume_path,
            'fields': 'name,path',
            'recursive': False
        }
        for key, value in types.items():
            if key in existing_ref:
                payload[value] = existing_ref[key]
        existing_snapshots = self.nef.snapshots.list(payload)
        if len(existing_snapshots) == 1:
            name = existing_snapshots[0]['name']
            path = existing_snapshots[0]['path']
            existing_snapshot = {
                'name': name,
                'path': path,
                'volume_name': volume_name,
                'volume_size': volume_size
            }
            sid = volume_utils.extract_id_from_snapshot_name(name)
            if self._check_already_managed_snapshot(sid):
                message = (_('Snapshot %(name)s already managed')
                           % {'name': name})
                raise jsonrpc.NefException(code='EBUSY', message=message)
            return existing_snapshot
        elif not existing_snapshots:
            code = 'ENOENT'
            reason = _('no matching snapshots were found')
        else:
            code = 'EINVAL'
            reason = _('too many snapshots were found')
        message = (_('Unable to manage existing snapshot by '
                     'reference %(reference)s: %(reason)s')
                   % {'reference': existing_ref, 'reason': reason})
        raise jsonrpc.NefException(code=code, message=message)

    @coordination.synchronized('{self.nef.lock}')
    def manage_existing(self, volume, existing_ref):
        """Brings an existing backend storage object under Cinder management.

        existing_ref is passed straight through from the API request's
        manage_existing_ref value, and it is up to the driver how this should
        be interpreted.  It should be sufficient to identify a storage object
        that the driver should somehow associate with the newly-created cinder
        volume structure.

        There are two ways to do this:

        1. Rename the backend storage object so that it matches the,
           volume['name'] which is how drivers traditionally map between a
           cinder volume and the associated backend storage object.

        2. Place some metadata on the volume, or somewhere in the backend, that
           allows other driver requests (e.g. delete, clone, attach, detach...)
           to locate the backend storage object when required.

        If the existing_ref doesn't make sense, or doesn't refer to an existing
        backend storage object, raise a ManageExistingInvalidReference
        exception.

        The volume may have a volume_type, and the driver can inspect that and
        compare against the properties of the referenced backend storage
        object.  If they are incompatible, raise a
        ManageExistingVolumeTypeMismatch, specifying a reason for the failure.

        :param volume:       Cinder volume to manage
        :param existing_ref: Driver-specific information used to identify a
                             volume
        """
        existing_volume = self._get_existing_volume(existing_ref)
        existing_volume_path = existing_volume['path']
        if existing_volume['name'] != volume['name']:
            volume_path = self._get_volume_path(volume)
            payload = {'newPath': volume_path}
            self.nef.filesystems.rename(existing_volume_path, payload)

    def manage_existing_get_size(self, volume, existing_ref):
        """Return size of volume to be managed by manage_existing.

        When calculating the size, round up to the next GB.

        :param volume:       Cinder volume to manage
        :param existing_ref: Driver-specific information used to identify a
                             volume
        :returns size:       Volume size in GiB (integer)
        """
        existing_volume = self._get_existing_volume(existing_ref)
        self._set_volume_acl(existing_volume)
        self._mount_volume(existing_volume)
        local_path = self.local_path(existing_volume)
        try:
            volume_size = os.path.getsize(local_path)
        except OSError as error:
            code = errno.errorcode[error.errno]
            message = (_('Manage existing volume %(name)s failed: '
                         'unable to get size of volume data file '
                         '%(file)s: %(error)s')
                       % {'name': existing_volume['name'],
                          'file': local_path,
                          'error': error.strerror})
            raise jsonrpc.NefException(code=code, message=message)
        finally:
            self._unmount_volume(existing_volume)
        return volume_size // units.Gi

    def get_manageable_volumes(self, cinder_volumes, marker, limit, offset,
                               sort_keys, sort_dirs):
        """List volumes on the backend available for management by Cinder.

        Returns a list of dictionaries, each specifying a volume in the host,
        with the following keys:
        - reference (dictionary): The reference for a volume, which can be
          passed to "manage_existing".
        - size (int): The size of the volume according to the storage
          backend, rounded up to the nearest GB.
        - safe_to_manage (boolean): Whether or not this volume is safe to
          manage according to the storage backend. For example, is the volume
          in use or invalid for any reason.
        - reason_not_safe (string): If safe_to_manage is False, the reason why.
        - cinder_id (string): If already managed, provide the Cinder ID.
        - extra_info (string): Any extra information to return to the user

        :param cinder_volumes: A list of volumes in this host that Cinder
                               currently manages, used to determine if
                               a volume is manageable or not.
        :param marker:    The last item of the previous page; we return the
                          next results after this value (after sorting)
        :param limit:     Maximum number of items to return
        :param offset:    Number of items to skip after marker
        :param sort_keys: List of keys to sort results by (valid keys are
                          'identifier' and 'size')
        :param sort_dirs: List of directions to sort by, corresponding to
                          sort_keys (valid directions are 'asc' and 'desc')
        """
        manageable_volumes = []
        cinder_volume_names = {}
        for cinder_volume in cinder_volumes:
            key = cinder_volume['name']
            value = cinder_volume['id']
            cinder_volume_names[key] = value
        payload = {
            'parent': self.root_path,
            'fields': 'guid,parent,path,bytesUsed',
            'recursive': False
        }
        volumes = self.nef.filesystems.list(payload)
        for volume in volumes:
            safe_to_manage = True
            reason_not_safe = None
            cinder_id = None
            extra_info = None
            path = volume['path']
            guid = volume['guid']
            parent = volume['parent']
            size = volume['bytesUsed'] // units.Gi
            name = posixpath.basename(path)
            if path == self.root_path:
                continue
            if parent != self.root_path:
                continue
            if name in cinder_volume_names:
                cinder_id = cinder_volume_names[name]
                safe_to_manage = False
                reason_not_safe = _('Volume already managed')
            reference = {
                'source-name': name,
                'source-guid': guid
            }
            manageable_volumes.append({
                'reference': reference,
                'size': size,
                'safe_to_manage': safe_to_manage,
                'reason_not_safe': reason_not_safe,
                'cinder_id': cinder_id,
                'extra_info': extra_info
            })
        return volume_utils.paginate_entries_list(manageable_volumes,
                                                  marker, limit, offset,
                                                  sort_keys, sort_dirs)

    def unmanage(self, volume):
        """Removes the specified volume from Cinder management.

        Does not delete the underlying backend storage object.

        For most drivers, this will not need to do anything.  However, some
        drivers might use this call as an opportunity to clean up any
        Cinder-specific configuration that they have associated with the
        backend storage object.

        :param volume: Cinder volume to unmanage
        """
        pass

    @coordination.synchronized('{self.nef.lock}')
    def manage_existing_snapshot(self, snapshot, existing_ref):
        """Brings an existing backend storage object under Cinder management.

        existing_ref is passed straight through from the API request's
        manage_existing_ref value, and it is up to the driver how this should
        be interpreted.  It should be sufficient to identify a storage object
        that the driver should somehow associate with the newly-created cinder
        snapshot structure.

        There are two ways to do this:

        1. Rename the backend storage object so that it matches the
           snapshot['name'] which is how drivers traditionally map between a
           cinder snapshot and the associated backend storage object.

        2. Place some metadata on the snapshot, or somewhere in the backend,
           that allows other driver requests (e.g. delete) to locate the
           backend storage object when required.

        If the existing_ref doesn't make sense, or doesn't refer to an existing
        backend storage object, raise a ManageExistingInvalidReference
        exception.

        :param snapshot:     Cinder volume snapshot to manage
        :param existing_ref: Driver-specific information used to identify a
                             volume snapshot
        """
        existing_snapshot = self._get_existing_snapshot(snapshot, existing_ref)
        existing_snapshot_path = existing_snapshot['path']
        if existing_snapshot['name'] != snapshot['name']:
            payload = {'newName': snapshot['name']}
            self.nef.snapshots.rename(existing_snapshot_path, payload)

    def manage_existing_snapshot_get_size(self, snapshot, existing_ref):
        """Return size of snapshot to be managed by manage_existing.

        When calculating the size, round up to the next GB.

        :param snapshot:     Cinder volume snapshot to manage
        :param existing_ref: Driver-specific information used to identify a
                             volume snapshot
        :returns size:       Volume snapshot size in GiB (integer)
        """
        existing_snapshot = self._get_existing_snapshot(snapshot, existing_ref)
        return existing_snapshot['volume_size']

    def get_manageable_snapshots(self, cinder_snapshots, marker, limit, offset,
                                 sort_keys, sort_dirs):
        """List snapshots on the backend available for management by Cinder.

        Returns a list of dictionaries, each specifying a snapshot in the host,
        with the following keys:
        - reference (dictionary): The reference for a snapshot, which can be
          passed to "manage_existing_snapshot".
        - size (int): The size of the snapshot according to the storage
          backend, rounded up to the nearest GB.
        - safe_to_manage (boolean): Whether or not this snapshot is safe to
          manage according to the storage backend. For example, is the snapshot
          in use or invalid for any reason.
        - reason_not_safe (string): If safe_to_manage is False, the reason why.
        - cinder_id (string): If already managed, provide the Cinder ID.
        - extra_info (string): Any extra information to return to the user
        - source_reference (string): Similar to "reference", but for the
          snapshot's source volume.

        :param cinder_snapshots: A list of snapshots in this host that Cinder
                                 currently manages, used to determine if
                                 a snapshot is manageable or not.
        :param marker:    The last item of the previous page; we return the
                          next results after this value (after sorting)
        :param limit:     Maximum number of items to return
        :param offset:    Number of items to skip after marker
        :param sort_keys: List of keys to sort results by (valid keys are
                          'identifier' and 'size')
        :param sort_dirs: List of directions to sort by, corresponding to
                          sort_keys (valid directions are 'asc' and 'desc')

        """
        manageable_snapshots = []
        cinder_volume_names = {}
        cinder_snapshot_names = {}
        ctxt = context.get_admin_context()
        cinder_volumes = objects.VolumeList.get_all_by_host(ctxt, self.host)
        for cinder_volume in cinder_volumes:
            key = self._get_volume_path(cinder_volume)
            value = {
                'name': cinder_volume['name'],
                'size': cinder_volume['size']
            }
            cinder_volume_names[key] = value
        for cinder_snapshot in cinder_snapshots:
            key = cinder_snapshot['name']
            value = {
                'id': cinder_snapshot['id'],
                'size': cinder_snapshot['volume_size'],
                'parent': cinder_snapshot['volume_name']
            }
            cinder_snapshot_names[key] = value
        payload = {
            'parent': self.root_path,
            'fields': 'name,guid,path,parent,hprService,snaplistId',
            'recursive': True
        }
        snapshots = self.nef.snapshots.list(payload)
        for snapshot in snapshots:
            safe_to_manage = True
            reason_not_safe = None
            cinder_id = None
            extra_info = None
            name = snapshot['name']
            guid = snapshot['guid']
            path = snapshot['path']
            parent = snapshot['parent']
            if parent not in cinder_volume_names:
                LOG.debug('Skip snapshot %(path)s: parent '
                          'volume %(parent)s is unmanaged',
                          {'path': path, 'parent': parent})
                continue
            if name.startswith(self.origin_snapshot_template):
                LOG.debug('Skip temporary origin snapshot %(path)s',
                          {'path': path})
                continue
            if name.startswith(self.group_snapshot_template):
                LOG.debug('Skip temporary group snapshot %(path)s',
                          {'path': path})
                continue
            if snapshot['hprService'] or snapshot['snaplistId']:
                LOG.debug('Skip HPR/snapping snapshot %(path)s',
                          {'path': path})
                continue
            if name in cinder_snapshot_names:
                size = cinder_snapshot_names[name]['size']
                cinder_id = cinder_snapshot_names[name]['id']
                safe_to_manage = False
                reason_not_safe = _('Snapshot already managed')
            else:
                size = cinder_volume_names[parent]['size']
                payload = {'fields': 'clones'}
                props = self.nef.snapshots.get(path)
                clones = props['clones']
                unmanaged_clones = []
                for clone in clones:
                    if clone not in cinder_volume_names:
                        unmanaged_clones.append(clone)
                if unmanaged_clones:
                    safe_to_manage = False
                    dependent_clones = ', '.join(unmanaged_clones)
                    reason_not_safe = (_('Snapshot has unmanaged '
                                         'dependent clone(s) %(clones)s')
                                       % {'clones': dependent_clones})
            reference = {
                'source-name': name,
                'source-guid': guid
            }
            source_reference = {
                'name': cinder_volume_names[parent]['name']
            }
            manageable_snapshots.append({
                'reference': reference,
                'size': size,
                'safe_to_manage': safe_to_manage,
                'reason_not_safe': reason_not_safe,
                'cinder_id': cinder_id,
                'extra_info': extra_info,
                'source_reference': source_reference
            })
        return volume_utils.paginate_entries_list(manageable_snapshots,
                                                  marker, limit, offset,
                                                  sort_keys, sort_dirs)

    def unmanage_snapshot(self, snapshot):
        """Removes the specified snapshot from Cinder management.

        Does not delete the underlying backend storage object.

        For most drivers, this will not need to do anything. However, some
        drivers might use this call as an opportunity to clean up any
        Cinder-specific configuration that they have associated with the
        backend storage object.

        :param snapshot: Cinder volume snapshot to unmanage
        """
        pass
