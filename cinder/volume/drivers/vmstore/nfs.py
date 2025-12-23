# Copyright 2026 DDN, Inc. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""VMstore NFS Volume Driver for Cinder."""

import hashlib
import os
import re
import time
from typing import List

from os_brick import encryptors
from os_brick.remotefs import remotefs
from oslo_concurrency import processutils
from oslo_log import log as logging
from oslo_utils import units

from cinder import context
from cinder import coordination
from cinder import db
from cinder import exception
from cinder.i18n import _
from cinder.image import image_utils
from cinder import interface
from cinder import objects
from cinder import utils as cinder_utils
from cinder.volume.drivers import nfs
from cinder.volume.drivers.vmstore import api
from cinder.volume.drivers.vmstore import options
from cinder.volume.drivers.vmstore import utils
from cinder.volume import volume_utils

LOG = logging.getLogger(__name__)


@interface.volumedriver
class VmstoreNfsDriver(nfs.NfsDriver):
    """Executes volume driver commands on VMstore Appliance.

    Version history:

    .. code-block:: none

        3.0-beta - Initial driver version.
        3.0.2 - Added vmstore_refresh_openstack_region parameter for
              hypervisor refresh API.
              - Added vmstore_refresh_retry_count specific for hypervisor
              refresh API.
        3.0.3 - refresh_hypervisor: poll for virtual disk after the API call
              to cinder/refresh and retry if not available.
    """

    VERSION = '3.0.3'
    CI_WIKI_NAME = 'Vmstore_CI'

    vendor_name = 'DDN'
    product_name = 'VMstore'
    storage_protocol = 'NFS'
    driver_prefix = 'vmstore'
    driver_volume_type = 'nfs'

    def __init__(self, execute=processutils.execute, *args, **kwargs):

        self._remotefsclient = None
        super(VmstoreNfsDriver, self).__init__(*args, **kwargs)
        if not self.configuration:
            code = 'ENODATA'
            message = (_('%(product_name)s %(storage_protocol)s '
                         'backend configuration not found')
                       % {'product_name': self.product_name,
                          'storage_protocol': self.storage_protocol})
            raise api.VmstoreException(code=code, message=message)

        self.configuration.append_config_values(options.VMSTORE_NFS_OPTS)
        root_helper = cinder_utils.get_root_helper()
        mount_point_base = self.configuration.vmstore_mount_point_base
        self.mount_point_base = os.path.realpath(mount_point_base)
        self.mount_options = self.configuration.safe_get('nfs_mount_options')
        self._mounted_shares = []

        required_mount_opts = [
            'lookupcache=pos', 'nolock', 'noacl', 'proto=tcp']
        for option in required_mount_opts:
            if option not in self.mount_options.split(','):
                if not self.mount_options:
                    self.mount_options = option
                else:
                    self.mount_options += ',%s' % option

        self._remotefsclient = remotefs.RemoteFsClient(
            self.driver_volume_type,
            root_helper, execute=execute,
            nfs_mount_point_base=self.mount_point_base,
            nfs_mount_options=self.mount_options)
        self.nas_driver = self.__class__.__name__
        self.ctxt = None
        self.backend_name = self._get_backend_name()
        self.nas_host = self.configuration.nas_host
        self.nas_path = self.configuration.nas_share_path
        self.nas_stat = None
        self.nas_share = None
        self.nas_mntpoint = None
        self.vmstore = None

    @staticmethod
    def get_driver_options():
        return options.VMSTORE_NFS_OPTS

    def do_setup(self, ctxt) -> None:
        self.ctxt = ctxt
        self._validate_required_options()
        retries = 0
        while not self._do_setup():
            retries += 1
            self.vmstore.delay(retries)

    def _validate_required_options(self) -> None:
        """Validate that required configuration options are set."""
        required_opts = ['vmstore_password', 'vmstore_rest_address']
        missing = []
        for opt in required_opts:
            if not getattr(self.configuration, opt, None):
                missing.append(opt)
        if missing:
            raise exception.InvalidConfigurationValue(
                option=', '.join(missing),
                value='<not set>',
                reason=_('Required VMstore configuration options are missing')
            )

    def _do_setup(self) -> bool:
        try:
            self.vmstore = api.VmstoreProxy(self.driver_volume_type,
                                            self.backend_name,
                                            self.configuration)
        except api.VmstoreException as error:
            LOG.error('Failed to initialize RESTful API for backend '
                      '%(backend_name)s on host %(host)s: %(error)s',
                      {'backend_name': self.backend_name,
                       'host': self.host,
                       'error': error})
            return False
        return True

    def check_for_setup_error(self) -> None:
        retries = 0
        while not self._check_for_setup_error():
            retries += 1
            self.vmstore.delay(retries)

    def _check_for_setup_error(self):
        appliance = self.vmstore.appliance.get(None)
        if appliance:
            return True
        return False

    def _get_backend_name(self) -> str:
        backend_name = self.configuration.safe_get('volume_backend_name')
        if not backend_name:
            LOG.error('Failed to get configured volume backend name')
            backend_name = '%(product)s_%(protocol)s' % {
                'product': self.product_name,
                'protocol': self.storage_protocol
            }
        return backend_name

    def _ensure_shares_mounted(self) -> None:
        """Look for remote shares in the flags and mount them locally."""
        mounted_shares: List[str] = []
        self._load_shares()

        for share in self.shares:
            try:
                self._ensure_share_mounted(share)
                mounted_shares.append(share)
            except Exception as exc:
                LOG.error('Exception during mounting %s', exc)

        self._mounted_shares = mounted_shares

        LOG.debug('Available shares %s', self._mounted_shares)

    def _load_shares(self) -> None:
        self.shares = {}

        if all((self.configuration.nas_host,
                self.configuration.nas_share_path)):
            LOG.debug('Using nas_host and nas_share_path configuration.')

            nas_host = self.configuration.nas_host
            nas_share_path = self.configuration.nas_share_path

            share_address = '%s:%s' % (nas_host, nas_share_path)

            if not re.match(self.SHARE_FORMAT_REGEX, share_address):
                msg = _('Share %(share)s ignored due to invalid format. '
                        'Must be of form address:/export. Please check '
                        'the nas_host and nas_share_path settings.'
                        ) % {'share': share_address}
                raise exception.InvalidConfigurationValue(msg)

            self.shares[share_address] = self.mount_options

        else:
            msg = 'nas_host or nas_share_path not configured.'
            LOG.error(msg)
            raise exception.InvalidConfigurationValue(msg)

        LOG.debug('shares loaded: %s', self.shares)

    def _mount_share(self, share) -> str:
        """Ensure that share is mounted on the host.

        :param share: nfs share
        :returns: mount point
        """
        attempts = max(1, self.configuration.nfs_mount_attempts)
        for attempt in range(1, attempts + 1):
            try:
                self._remotefsclient.mount(share)
            except Exception as error:
                LOG.debug('Mount attempt %(attempt)s failed: %(error)s, '
                          'retrying mount NFS share %(share)s',
                          {'attempt': attempt, 'error': error,
                           'share': share})
                if attempt == attempts:
                    LOG.error('Failed to mount NFS share %(share)s '
                              'after %(attempt)s attempts: %(error)s',
                              {'share': share, 'attempt': attempt,
                               'error': error})
                    raise
                self.vmstore.delay(attempt)
            else:
                mntpoint = self._get_mount_point_for_share(share)
                LOG.debug('NFS share %(share)s has been mounted at '
                          '%(mntpoint)s after %(attempt)s attempts',
                          {'share': share, 'mntpoint': mntpoint,
                           'attempt': attempt})
                return mntpoint

    def _ensure_share_mounted(self, nfs_share) -> None:
        num_attempts = max(1, self.configuration.nfs_mount_attempts)
        for attempt in range(num_attempts):
            try:
                self._remotefsclient.mount(nfs_share)
                self._mounted_shares.append(nfs_share)
                return
            except Exception as e:
                if attempt == (num_attempts - 1):
                    LOG.error('Mount failure for %(share)s after '
                              '%(count)d attempts.',
                              {'share': nfs_share,
                               'count': num_attempts})
                    raise exception.NfsException(str(e))
                LOG.debug('Mount attempt %(attempt)d failed: %(exc)s.\n'
                          'Retrying mount ...',
                          {'attempt': attempt, 'exc': e})
                time.sleep(1)

    def refresh_hypervisor(self, volume):
        """Refresh VMstore hypervisor for the given volume.

        :param volume: volume reference
        """
        try:
            vmstore_subdir = self.nas_path.removeprefix('/tintri/')
            volume_path = os.path.join(vmstore_subdir, volume['name'])

            hostname = self.configuration.safe_get(
                'vmstore_openstack_hostname')
            if not hostname:
                hostname = utils.get_keystone_hostname()
            if not hostname:
                LOG.warning("No OpenStack hostname configured and "
                            "auto-discovery failed. Skipping refresh.")
                return
            payload = {
                'typeId': ('com.tintri.api.rest.v310.dto.domain.'
                           'beans.cinder.OpenStackHostRefreshSpec'),
                'hostname': hostname,
                'volumeFilePath': volume_path,
                'region': self.configuration.vmstore_refresh_openstack_region,
            }
            self.vmstore.cinder_refresh.create(payload)
            vd = self.vmstore.virtual_disk.get(volume.name_id)
            timeout = 30
            current = 1
            while len(vd) < 1:
                if current < timeout:
                    LOG.debug('VirtualDisk for %s not found, sleeping %d',
                              volume.name_id, current)
                    time.sleep(current)
                    self.vmstore.cinder_refresh.create(payload)
                    current += 2
                    vd = self.vmstore.virtual_disk.get(volume.name_id)
                else:
                    raise api.VmstoreException(
                        code='NotFound',
                        message=('Could not find VirtualDisk for %s' %
                                 volume['name']))
        except Exception as e:
            LOG.warning("Failed to refresh hypervisor, error: %s", e)

    def create_volume(self, volume: objects.Volume) -> dict:
        """Creates a volume.

        :param volume: volume reference
        :returns: provider_location update dict for database
        """

        if volume.encryption_key_id and not self._supports_encryption:
            message = _('Encryption is not yet supported.')
            raise exception.VolumeDriverException(message=message)

        LOG.debug('Creating volume %(vol)s', {'vol': volume.name_id})
        self._ensure_shares_mounted()

        volume.provider_location = self._find_share(volume)

        LOG.debug('casted to %s', volume.provider_location)

        self._do_create_volume(volume)
        self.refresh_hypervisor(volume)
        return {'provider_location': volume.provider_location}

    def _do_create_volume(self, volume: objects.Volume) -> None:
        """Create a volume on given remote share.

        :param volume: volume reference
        """
        volume_path = self.local_path(volume)
        volume_size = volume.size

        encrypted = volume.encryption_key_id is not None

        if encrypted:
            encryption = self.check_encryption_provider(
                volume,
                volume.obj_context)

            self._create_encrypted_volume_file(volume_path,
                                               volume_size,
                                               encryption,
                                               volume.obj_context)
        elif getattr(self.configuration,
                     self.driver_prefix + '_qcow2_volumes', False):
            # QCOW2 volumes are inherently sparse, so this setting
            # will override the _sparsed_volumes setting.
            self._create_qcow2_file(volume_path, volume_size)
            self.format = 'qcow2'
        elif getattr(self.configuration,
                     self.driver_prefix + '_sparsed_volumes', False):
            self._create_sparsed_file(volume_path, volume_size)
        else:
            self._create_regular_file(volume_path, volume_size)

        self._set_rw_permissions(volume_path)
        volume.admin_metadata['format'] = self.format
        with volume.obj_as_admin():
            volume.save()

    def check_encryption_provider(
        self,
        volume: 'objects.Volume',
        context: context.RequestContext,
    ) -> dict:
        """Check that this is a LUKS encryption provider.

        :returns: encryption dict
        """

        encryption = db.volume_encryption_metadata_get(context, volume.id)

        if 'provider' not in encryption:
            message = _("Invalid encryption spec.")
            raise exception.VolumeDriverException(message=message)

        provider = encryption['provider']
        if provider in encryptors.LEGACY_PROVIDER_CLASS_TO_FORMAT_MAP:
            provider = encryptors.LEGACY_PROVIDER_CLASS_TO_FORMAT_MAP[provider]
            encryption['provider'] = provider

        if 'cipher' not in encryption or 'key_size' not in encryption:
            msg = _('encryption spec must contain "cipher" and '
                    '"key_size"')
            raise exception.VolumeDriverException(message=msg)

        return encryption

    def delete_volume(self, volume):
        """Deletes a logical volume."""

        LOG.debug('Deleting volume %(vol)s, provider_location: %(loc)s',
                  {'vol': volume.name_id, 'loc': volume.provider_location})

        if not volume.provider_location:
            LOG.warning('Volume %s does not have provider_location '
                        'specified, skipping', volume.name)
            return

        # Delete all VMstore snapshots associated with this volume
        self._delete_volume_snapshots(volume)

        info_path = self._local_path_volume_info(volume)
        info = self._read_info_file(info_path, empty_if_missing=True)

        if info:
            base_volume_path = os.path.join(self._local_volume_dir(volume),
                                            info['active'])
            self._delete(info_path)
        else:
            base_volume_path = self._local_path_volume(volume)

        volume_path = base_volume_path
        self._delete(volume_path)
        try:
            self.refresh_hypervisor(volume)
        except Exception as exc:
            LOG.debug(
                'Received an error on attempt to refresh hypervisor after '
                'delete_volume %(exc)s', {'exc': exc})

    def _delete_volume_snapshots(self, volume):
        """Delete all VMstore snapshots associated with the volume.

        :param volume: volume reference
        """
        volume_id = volume.name_id
        LOG.debug('Checking for VMstore snapshots associated with '
                  'volume %(vol)s', {'vol': volume_id})
        try:
            snapshots = self.vmstore.snapshots.list()
            for vmstore_snapshot in snapshots:
                if vmstore_snapshot.get('vmName') == volume_id:
                    snap_uuid = vmstore_snapshot['uuid']['uuid']
                    LOG.debug('Deleting VMstore snapshot %(snap_uuid)s '
                              'for volume %(vol)s',
                              {'snap_uuid': snap_uuid, 'vol': volume_id})
                    try:
                        self.vmstore.snapshots.delete(snap_uuid)
                    except api.VmstoreException as e:
                        LOG.warning('Failed to delete snapshot %(snap)s '
                                    'for volume %(vol)s: %(err)s',
                                    {'snap': snap_uuid, 'vol': volume_id,
                                     'err': e})
        except api.VmstoreException as e:
            LOG.warning('Failed to list snapshots for volume %(vol)s: %(err)s',
                        {'vol': volume_id, 'err': e})

    def _get_share_path(self):
        nas_host = self.configuration.nas_host
        nas_share_path = self.configuration.nas_share_path

        return '%s:%s' % (nas_host, nas_share_path)

    @coordination.synchronized('{self.vmstore.lock}')
    def initialize_connection(self, volume, connector):
        """Allow connection to connector and return connection info.

        :param volume: volume reference
        :param connector: connector reference
        :returns: dictionary of connection information
        """
        LOG.debug('Initialize volume connection for %(volume)s',
                  {'volume': volume['name']})
        volume_name = volume['name']
        volume_dir = self._local_volume_dir(volume)
        path_to_vol = os.path.join(volume_dir, volume_name)
        info = self._qemu_img_info(path_to_vol, volume_name)

        if info.file_format not in ['raw', 'qcow2']:
            msg = _('nfs volume must be a valid raw or qcow2 image.')
            raise exception.InvalidVolume(reason=msg)

        data = {
            'export': self._get_share_path(),
            'name': volume_name,
            'format': info.file_format
        }
        encryption_key_id = volume.get('encryption_key_id', None)
        data['encrypted'] = encryption_key_id is not None

        if self.mount_options:
            data['options'] = '-o %s' % self.mount_options
        info = {
            'driver_volume_type': self.driver_volume_type,
            'mount_point_base': self.mount_point_base,
            'data': data
        }
        LOG.debug('conn_info: %s', info)
        return info

    def _local_volume_dir(self, volume):
        """Get volume dir (mounted locally fs path) for given volume.

        :param volume: volume reference
        """
        share = volume.provider_location
        if isinstance(share, str):
            share = share.encode('utf-8')
        path = hashlib.md5(share, usedforsecurity=False).hexdigest()
        return os.path.join(self.mount_point_base, path)

    def _check_snapshot_support(self, setup_checking=False):
        return True

    @coordination.synchronized('{self.vmstore.lock}')
    def create_snapshot(self, snapshot):
        """Creates a snapshot.

        :param snapshot: snapshot reference
        """
        volume = snapshot.volume
        vmstore_subdir = self.nas_path.removeprefix('/tintri/')
        volume_path = os.path.join(vmstore_subdir, volume['name'])
        # Use volume.name_id for backend storage identification
        # per Cinder guidelines
        volume_name_id = volume.name_id
        vd = self.vmstore.virtual_disk.get(volume_name_id)
        timeout = 30
        current = 1
        while len(vd) < 1:
            if current < timeout:
                LOG.debug('VirtualDisk for %s not found, sleeping %d',
                          volume_name_id, current)
                time.sleep(current)
                self.refresh_hypervisor(volume)
                current += 2
                vd = self.vmstore.virtual_disk.get(volume_name_id)
            else:
                raise api.VmstoreException(
                    code='NotFound',
                    message=('Could not find VirtualDisk for %s' %
                             volume['name']))
        payload = {
            'typeId': ('com.tintri.api.rest.v310.dto.domain.'
                       'beans.cinder.CinderSnapshotSpec'),
            'file': volume_path,
            'vmName': vd[0]['vmName'],
            'description': snapshot['name'],
            'vmTintriUuid': vd[0]['vmUuid']['uuid'],
            'instanceId': vd[0]['instanceUuid'],
            'snapshotCreator': 'Vmstore cinder driver',
            'deletionPolicy': 'DELETE_ON_EXPIRATION'
        }
        self.vmstore.snapshots.create(payload)

    @coordination.synchronized('{self.vmstore.lock}')
    def delete_snapshot(self, snapshot):
        """Deletes a snapshot.

        :param snapshot: snapshot reference
        """
        snapshots = self.vmstore.snapshots.list()
        snap_uuid = ''
        for vmstore_snapshot in snapshots:
            if snapshot['name'] == vmstore_snapshot['description']:
                snap_uuid = vmstore_snapshot['uuid']['uuid']
        if not snap_uuid:
            LOG.info('Did not find snapshot %(name)s, '
                     'this is ok for deletion.',
                     {'name': snapshot['name']})
            return
        try:
            self.vmstore.snapshots.delete(snap_uuid)
        except api.VmstoreException as e:
            if 'VM is still present' in str(e):
                LOG.warning(e)
            else:
                raise

    @coordination.synchronized('{self.vmstore.lock}')
    def create_volume_from_snapshot(self, volume, snapshot):
        """Create new volume from other's snapshot on appliance.

        :param volume: reference of volume to be created
        :param snapshot: reference of source snapshot
        """
        snapshots = self.vmstore.snapshots.list()
        snap_uuid = ''
        for vmstore_snapshot in snapshots:
            if snapshot['name'] == vmstore_snapshot['description']:
                snap_uuid = vmstore_snapshot['uuid']['uuid']
        timeout = 30
        current = 1
        while not snap_uuid:
            if current < timeout:
                snapshots = self.vmstore.snapshots.list()
                for vmstore_snapshot in snapshots:
                    if snapshot['name'] == vmstore_snapshot['description']:
                        snap_uuid = vmstore_snapshot['uuid']['uuid']
            else:
                msg = 'Did not find snapshot %s' % snapshot['name']
                raise api.VmstoreException(code='NotFound', message=msg)
        vmstore_subdir = self.nas_path.removeprefix('/tintri')
        clone_path = os.path.join(
            vmstore_subdir, snapshot['name'])

        payload = {
            'typeId': ('com.tintri.api.rest.v310.dto.domain.'
                       'beans.cinder.CinderCloneSpec'),
            'tintriSnapshotUuid': snap_uuid,
            'destinationPaths': clone_path,
        }
        self.vmstore.clones.create(payload)
        mount_dir = self._get_mount_point_for_share(self._get_share_path())
        temp_clone_dir = os.path.join(mount_dir, snapshot['name'])
        temp_clone_path = os.path.join(temp_clone_dir, snapshot['volume_name'])
        clone_destination = os.path.join(
            mount_dir, volume['name'])
        os.rename(temp_clone_path, clone_destination)
        os.rmdir(temp_clone_dir)

        self.refresh_hypervisor(volume)
        volume.provider_location = self._find_share(volume)
        return {'provider_location': volume.provider_location}

    def copy_image_to_volume(self,
                             context: context.RequestContext,
                             volume: objects.Volume,
                             image_service,
                             image_id: str,
                             disable_sparse: bool = False) -> None:
        """Fetch the image from image_service and write it to the volume."""

        volpath = self.local_path(volume)
        image_utils.fetch_to_raw(context,
                                 image_service,
                                 image_id,
                                 volpath,
                                 self.configuration.volume_dd_blocksize,
                                 size=volume.size,
                                 run_as_root=self._execute_as_root,
                                 disable_sparse=disable_sparse)

        image_utils.resize_image(volpath, volume.size,
                                 run_as_root=self._execute_as_root)

        data = image_utils.qemu_img_info(volpath,
                                         run_as_root=self._execute_as_root)
        virt_size = data.virtual_size // units.Gi
        if virt_size != volume.size:
            raise exception.ImageUnacceptable(
                image_id=image_id,
                reason=(_("Expected volume size was %d") % volume.size)
                + (_(" but size is now %d") % virt_size))

    def copy_volume_to_image(self,
                             context: context.RequestContext,
                             volume: objects.Volume,
                             image_service,
                             image_meta: dict) -> None:
        """Copy the volume to the specified image."""
        volpath = self.local_path(volume)
        volume_utils.upload_volume(context,
                                   image_service,
                                   image_meta,
                                   volpath,
                                   volume,
                                   run_as_root=self._execute_as_root)

    @coordination.synchronized('{self.vmstore.lock}')
    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume.

        Create a snapshot with DELETE_ON_ZERO_CLONE_REFERENCES.
        Create a cloned volume from that snapshot.
        When the cloned volume is deleted, snapshot will get deleted from
        Vmstore automatically due to deletionPolicy

        :param volume: new volume reference
        :param src_vref: source volume reference
        """
        src_name = src_vref['name']
        src_id = src_vref.name_id
        vd = self.vmstore.virtual_disk.get(src_id)
        timeout = 30
        current = 1
        while len(vd) < 1:
            if current < timeout:
                LOG.debug('VirtualDisk for %s not found, sleeping %d',
                          src_id, current)
                time.sleep(current)
                current += 2
                vd = self.vmstore.virtual_disk.get(src_id)
            else:
                raise api.VmstoreException(
                    code='NotFound',
                    message=('Could not find VirtualDisk for %s' %
                             src_name))
        vmstore_subdir = self.nas_path.removeprefix('/tintri/')
        clone_name = 'clone-%s' % src_name
        payload = {
            'typeId': ('com.tintri.api.rest.v310.dto.domain.'
                       'beans.cinder.CinderSnapshotSpec'),
            'file': os.path.join(vmstore_subdir, src_name),
            'vmName': vd[0]['vmName'],
            'description': clone_name,
            'vmTintriUuid': vd[0]['vmUuid']['uuid'],
            'instanceId': vd[0]['instanceUuid'],
            'snapshotCreator': 'Vmstore cinder driver',
            'deletionPolicy': 'DELETE_ON_ZERO_CLONE_REFERENCES'
        }
        self.vmstore.snapshots.create(payload)

        snapshots = self.vmstore.snapshots.list()
        snap_uuid = ''
        for vmstore_snapshot in snapshots:
            if clone_name == vmstore_snapshot['description']:
                snap_uuid = vmstore_snapshot['uuid']['uuid']
        if not snap_uuid:
            msg = 'Did not find snapshot %s' % clone_name
            raise api.VmstoreException(code='NotFound', message=msg)
        vmstore_subdir = self.nas_path.removeprefix('/tintri')
        clone_path = os.path.join(
            vmstore_subdir, clone_name)

        payload = {
            'typeId': ('com.tintri.api.rest.v310.dto.domain.'
                       'beans.cinder.CinderCloneSpec'),
            'tintriSnapshotUuid': snap_uuid,
            'destinationPaths': clone_path,
        }
        self.vmstore.clones.create(payload)
        mount_dir = self._get_mount_point_for_share(self._get_share_path())
        temp_clone_dir = os.path.join(mount_dir, clone_name)
        temp_clone_path = os.path.join(temp_clone_dir, src_name)
        clone_destination = os.path.join(
            mount_dir, volume['name'])
        os.rename(temp_clone_path, clone_destination)
        os.rmdir(temp_clone_dir)

        self.refresh_hypervisor(volume)
        volume.provider_location = self._find_share(volume)
        return {'provider_location': volume.provider_location}

    def extend_volume(self, volume, new_size):
        """Extend an existing volume to the new size."""
        if self._is_volume_attached(volume):
            msg = (_("Cannot extend volume %s while it is attached.")
                   % volume.name_id)
            raise exception.ExtendVolumeError(msg)

        LOG.info('Extending volume %s.', volume.name_id)
        extend_by = int(new_size) - volume.size
        if not self._is_share_eligible(volume.provider_location,
                                       extend_by):
            raise exception.ExtendVolumeError(reason='Insufficient space to'
                                              ' extend volume %s to %sG'
                                              % (volume.name_id, new_size))
        # Use the active image file because this volume might have snapshot(s).
        active_file = self.get_active_image_from_info(volume)
        active_file_path = os.path.join(self._local_volume_dir(volume),
                                        active_file)
        LOG.info('Resizing file to %sG...', new_size)
        file_format = None
        admin_metadata = objects.Volume.get_by_id(
            context.get_admin_context(), volume.id).admin_metadata

        if admin_metadata and 'format' in admin_metadata:
            file_format = admin_metadata['format']
        image_utils.resize_image(
            active_file_path, new_size,
            run_as_root=self._execute_as_root,
            file_format=file_format)
        if file_format == 'qcow2' and not self._is_file_size_equal(
                active_file_path, new_size):
            raise exception.ExtendVolumeError(
                reason='Resizing image file failed.')

    def get_volume_stats(self, refresh=False) -> dict:
        """Get volume stats.

        If 'refresh' is True, run update the stats first.
        """
        if refresh or not self._stats:
            self._update_volume_stats()
        return self._stats

    def _update_volume_stats(self) -> None:
        """Retrieve stats info for Red cluster."""
        provisioned_capacity_gb = total_volumes = 0
        volumes = objects.VolumeList.get_all_by_host(self.ctxt, self.host)
        for volume in volumes:
            provisioned_capacity_gb += volume['size']
            total_volumes += 1
        max_over_subscription_ratio = (
            self.configuration.safe_get('max_over_subscription_ratio'))
        reserved_percentage = (
            self.configuration.safe_get('reserved_percentage'))
        if reserved_percentage is None:
            reserved_percentage = 0
        location_info = '%(driver)s:%(host)s:%(path)s' % {
            'driver': self.nas_driver,
            'host': self.nas_host,
            'path': self.nas_path
        }
        description = (
            self.configuration.safe_get('vmstore_dataset_description'))
        if not description:
            description = '%(product)s %(host)s:%(path)s' % {
                'product': self.product_name,
                'host': self.nas_host,
                'path': self.nas_path
            }
        display_name = 'Capabilities of %(product)s %(protocol)s driver' % {
            'product': self.product_name,
            'protocol': self.storage_protocol
        }

        stats = {
            'backend_state': 'up',
            'driver_version': self.VERSION,
            'vendor_name': self.vendor_name,
            'storage_protocol': self.storage_protocol,
            'volume_backend_name': self.backend_name,
            'location_info': location_info,
            'display_name': display_name,
            'multiattach': False,
            'QoS_support': False,
            'consistencygroup_support': False,
            'consistent_group_snapshot_enabled': False,
            'online_extend_support': False,
            'sparse_copy_volume': False,
            'thin_provisioning_support': True,
            'thick_provisioning_support': False,
            'total_volumes': total_volumes,
            'provisioned_capacity_gb': provisioned_capacity_gb,
            'max_over_subscription_ratio': max_over_subscription_ratio,
        }
        self._ensure_shares_mounted()

        pools = []
        for share in self._mounted_shares:
            pool = dict()
            capacity, free, _used = self._get_capacity_info(share)
            pool['pool_name'] = share
            pool['total_capacity_gb'] = capacity / float(units.Gi)
            pool['free_capacity_gb'] = free / float(units.Gi)
            pool['reserved_percentage'] = 0
            pool['QoS_support'] = True
            pools.append(pool)
        stats['pools'] = pools

        self._stats = stats
        LOG.debug('Updated volume backend statistics for host %(host)s '
                  'and volume backend %(backend_name)s: %(stats)s',
                  {'host': self.host,
                   'backend_name': self.backend_name,
                   'stats': self._stats})
