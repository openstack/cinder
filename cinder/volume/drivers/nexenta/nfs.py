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

import datetime
import difflib
import hashlib
import ipaddress
import os
import posixpath

from eventlet import greenthread
from oslo_log import log as logging
from oslo_utils import strutils
from oslo_utils import timeutils
from oslo_utils import units
import six

from cinder import context
from cinder.i18n import _
from cinder import objects
from cinder.volume.drivers.nexenta import jsonrpc
from cinder.volume.drivers.nexenta import options
from cinder.volume.drivers import nfs

LOG = logging.getLogger(__name__)


class NexentaNfsDriver(nfs.NfsDriver):
    """Executes volume driver commands on Nexenta Appliance.

    Version history:

    .. code-block:: none

        1.0.0 - Initial driver version.
        1.1.0 - Auto sharing for enclosing folder.
        1.1.1 - Added caching for NexentaStor appliance 'volroot' value.
        1.1.2 - Ignore "folder does not exist" error in delete_volume and
                delete_snapshot method.
        1.1.3 - Redefined volume_backend_name attribute inherited from
                RemoteFsDriver.
        1.2.0 - Added migrate and retype methods.
        1.3.0 - Extend volume method.
        1.3.1 - Cache capacity info and check shared folders on setup.
        1.3.2 - Pass mount_point_base in init_conn to support host-based
                migration.
        1.4.0 - Refactored NFS driver.
              - Improved storage assisted volume migration.
              - Added volume multi-attach.
              - Fixed automatic mode for nexenta_rest_protocol.
              - Added deferred deletion for snapshots.
              - Added synchronization for NMS REST API calls.
              - Added configuration parameters for REST API connect/read
                timeouts, connection retries and backoff factor.
              - Disabled non-blocking mandatory locks.
              - Added informative exception messages for REST API.
              - Improved collection of backend statistics.
        1.4.1 - Added retries on timeouts, network connection errors,
                SSL errors, proxy and NMS errors.
    """

    VERSION = '1.4.1'
    CI_WIKI_NAME = 'Nexenta_CI'

    vendor_name = 'Nexenta'
    product_name = 'NexentaStor4'
    storage_protocol = 'NFS'
    driver_volume_type = 'nfs'

    def __init__(self, *args, **kwargs):
        super(NexentaNfsDriver, self).__init__(*args, **kwargs)
        if not self.configuration:
            message = (_('%(product_name)s %(storage_protocol)s '
                         'backend configuration not found')
                       % {'product_name': self.product_name,
                          'storage_protocol': self.storage_protocol})
            raise jsonrpc.NmsException(code='EINVAL', message=message)
        self.configuration.append_config_values(
            options.NEXENTA_CONNECTION_OPTS)
        self.configuration.append_config_values(options.NEXENTA_NFS_OPTS)
        self.configuration.append_config_values(options.NEXENTA_DATASET_OPTS)
        required_options = ['nas_host', 'nas_share_path', 'nexenta_user',
                            'nexenta_password']
        for option in required_options:
            if not self.configuration.safe_get(option):
                message = (_('%(product_name)s %(storage_protocol)s '
                             'backend configuration is missing '
                             'required option: %(option)s')
                           % {'product_name': self.product_name,
                              'storage_protocol': self.storage_protocol,
                              'option': option})
                raise jsonrpc.NmsException(code='EINVAL', message=message)
        self.nms = None
        self.driver_name = self.__class__.__name__
        self.nas_host = self.configuration.nas_host
        self.root_path = self.configuration.nas_share_path
        self.mount_point_base = self.configuration.nexenta_mount_point_base
        self.volume_compression = (
            self.configuration.nexenta_dataset_compression)
        self.sparsed_volumes = self.configuration.nexenta_sparsed_volumes
        self.origin_snapshot_template = (
            self.configuration.nexenta_origin_snapshot_template)
        self.migration_snapshot_prefix = (
            self.configuration.nexenta_migration_snapshot_prefix)
        self.migration_service_prefix = (
            self.configuration.nexenta_migration_service_prefix)
        self.migration_throttle = (
            self.configuration.nexenta_migration_throttle)

    def do_setup(self, context):
        self.nms = jsonrpc.NmsProxy(self.driver_volume_type,
                                    self.root_path,
                                    self.configuration)

    def check_for_setup_error(self):
        """Check root filesystem, NFS service and NFS share."""
        if not self.nms.folder.object_exists(self.root_path):
            message = (_('NFS root filesystem %(path)s not found')
                       % {'path': self.root_path})
            raise jsonrpc.NmsException(code='ENOENT', message=message)
        filesystem = self.nms.folder.get_child_props(self.root_path, '')
        if filesystem['mountpoint'] == 'none':
            message = (_('NFS root filesystem %(path)s is not writable')
                       % {'path': self.root_path})
            raise jsonrpc.NefException(code='ENOENT', message=message)
        if filesystem['mounted'] == 'no':
            message = (_('NFS root filesystem %(path)s is not mounted')
                       % {'path': self.root_path})
            raise jsonrpc.NefException(code='ENOTDIR', message=message)
        if filesystem['nbmand'] == 'on':
            self.nms.folder.set_child_prop(self.root_path, 'nbmand', 'off')
        fmri = 'svc:/network/nfs/server:default'
        state = self.nms.netsvc.get_state(fmri)
        if state != 'online':
            message = (_('NFS service is not online: %(state)s')
                       % {'state': state})
            raise jsonrpc.NmsException(code='ESRCH', message=message)
        shared = self.nms.netstorsvc.is_folder_shared(fmri, self.root_path)
        if not shared:
            message = (_('NFS root filesystem %(path)s is not shared')
                       % {'path': self.root_path})
            raise jsonrpc.NmsException(code='ENOENT', message=message)

    def create_volume(self, volume):
        """Creates a volume.

        :param volume: volume reference
        :return: model update dict for volume reference
        """
        volume_path = self._get_volume_path(volume)
        volume_options = {
            'compression': self.volume_compression
        }
        self.nms.folder.create_with_props(self.root_path,
                                          volume['name'],
                                          volume_options)
        try:
            self._set_volume_acl(volume)
            self._mount_volume(volume)
            volume_file = self.local_path(volume)
            volume_size = volume['size']
            if self.sparsed_volumes:
                self._create_sparsed_file(volume_file, volume_size)
            else:
                compression = self.nms.folder.get_child_prop(volume_path,
                                                             'compression')
                if compression != 'off':
                    self.nms.folder.set_child_prop(volume_file,
                                                   'compression',
                                                   'off')
                self._create_regular_file(volume_file, volume_size)
                if compression != 'off':
                    self.nms.folder.set_child_prop(volume_path,
                                                   'compression',
                                                   compression)
        except jsonrpc.NmsException as create_error:
            try:
                self.nms.folder.destroy(volume_path, '-rf')
            except jsonrpc.NmsException as delete_error:
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

    def extend_volume(self, volume, new_size):
        """Extend an existing volume.

        :param volume: volume reference
        :param new_size: volume new size in GB
        """
        LOG.debug('Extend volume %(volume)s, new size: %(size)sGB',
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

    def delete_volume(self, volume):
        """Deletes a logical volume.

        :param volume: volume reference
        """
        volume_path = self._get_volume_path(volume)
        try:
            origin = self.nms.folder.get_child_prop(volume_path, 'origin')
        except jsonrpc.NmsException as error:
            if error.code == 'ENOENT':
                return
            raise
        self.nms.folder.destroy(volume_path, '-rf')
        if not origin:
            return
        template = self.origin_snapshot_template
        parent_path, snapshot_name = origin.split('@')
        if not self._match_template(template, snapshot_name):
            return
        try:
            self.nms.snapshot.destroy(origin, '-d')
        except jsonrpc.NmsException as error:
            LOG.error('Failed to delete origin snapshot %(origin)s '
                      'of volume %(volume)s: %(error)s',
                      {'origin': origin,
                       'volume': volume['name'],
                       'error': error})

    def create_volume_from_snapshot(self, volume, snapshot):
        """Create new volume from other's snapshot on appliance.

        :param volume: reference of volume to be created
        :param snapshot: reference of source snapshot
        """
        LOG.debug('Create volume %(volume)s from snapshot %(snapshot)s',
                  {'volume': volume['name'], 'snapshot': snapshot['name']})
        snapshot_path = self._get_snapshot_path(snapshot)
        clone_path = self._get_volume_path(volume)
        self.nms.folder.clone(snapshot_path, clone_path)
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
        except jsonrpc.NmsException as error:
            LOG.error('Failed to create clone %(clone)s '
                      'from volume %(volume)s: %(error)s',
                      {'clone': volume['name'],
                       'volume': src_vref['name'],
                       'error': error})
            raise
        finally:
            try:
                self.delete_snapshot(snapshot)
            except jsonrpc.NmsException as error:
                LOG.error('Failed to delete temporary snapshot '
                          '%(volume)s@%(snapshot)s: %(error)s',
                          {'volume': src_vref['name'],
                           'snapshot': snapshot['name'],
                           'error': error})

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
        for attempt in range(attempts):
            try:
                self._execute('umount', path, run_as_root=True)
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
                greenthread.sleep(1)
        self._delete(path)

    def _delete(self, path):
        """Override parent method for safe remove mountpoint."""
        try:
            os.rmdir(path)
            LOG.debug('The mountpoint %(path)s has been successfully removed',
                      {'path': path})
        except OSError as error:
            LOG.debug('Failed to remove mountpoint %(path)s: %(error)s',
                      {'path': path, 'error': error.strerror})

    def _mount_volume(self, volume):
        """Ensure that volume is activated and mounted on the host."""
        share = self._get_volume_share(volume)
        self._ensure_share_mounted(share)

    def _unmount_volume(self, volume):
        """Ensure that volume is unmounted on the host."""
        try:
            share = self._get_volume_share(volume)
        except jsonrpc.NmsException as error:
            if error.code == 'ENOENT':
                return
        self._ensure_share_unmounted(share)

    def create_export(self, context, volume, connector):
        """Driver entry point to get the export info for a new volume."""
        pass

    def ensure_export(self, context, volume):
        """Driver entry point to get the export info for an existing volume."""
        pass

    def remove_export(self, context, volume):
        """Driver entry point to remove an export for a volume."""
        pass

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
        """Allow connection to connector and return connection info.

        :param volume: volume reference
        :param connector: connector reference
        :returns: dictionary of connection information
        """
        LOG.debug('Initialize volume connection for %(volume)s',
                  {'volume': volume['name']})
        share = self._get_volume_share(volume)
        data = {
            'export': share,
            'name': 'volume'
        }
        nfs_options = self.configuration.safe_get('nfs_mount_options')
        nas_options = self.configuration.safe_get('nas_mount_options')
        if nfs_options and nas_options:
            LOG.debug('Overriding NFS mount options for volume %(volume)s: '
                      'nfs_mount_options = "%(nfs_options)s" with '
                      'nas_mount_options = "%(nas_options)s"',
                      {'volume': volume['name'],
                       'nfs_options': nfs_options,
                       'nas_options': nas_options})
        if nas_options:
            data['options'] = '-o %s' % nas_options
        elif nfs_options:
            data['options'] = '-o %s' % nfs_options
        info = {
            'driver_volume_type': self.driver_volume_type,
            'mount_point_base': self.mount_point_base,
            'data': data
        }
        return info

    def _get_bound_host(self, host):
        """Get user@host:port from SSH bindings."""
        try:
            bindings = self.nms.appliance.ssh_list_bindings()
        except jsonrpc.NmsException as error:
            LOG.error('Failed to get SSH bindings: %(error)s',
                      {'error': error})
            return None
        for user_host_port in bindings:
            binding = bindings[user_host_port]
            if not (isinstance(binding, list) and len(binding) == 4):
                LOG.warning('Skip incompatible SSH binding: %(binding)s',
                            {'binding': binding})
                continue
            data = binding[2]
            items = data.split(',')
            for item in items:
                if host == item.strip():
                    return user_host_port
        return None

    def _svc_state(self, fmri, state):
        retries = 10
        delay = 30
        while retries:
            greenthread.sleep(delay)
            retries -= 1
            try:
                status = self.nms.autosvc.get_state(fmri)
            except jsonrpc.NmsException as error:
                LOG.error('Failed to get state of migration '
                          'service %(fmri)s: %(error)s',
                          {'fmri': fmri, 'error': error})
                continue
            if status == 'uninitialized':
                continue
            elif status == state:
                return True
            if state == 'online':
                method = getattr(self.nms.autosvc, 'enable')
            elif state == 'disabled':
                method = getattr(self.nms.autosvc, 'disable')
            else:
                LOG.error('Request unknown service state: %(state)s',
                          {'state': state})
                return False
            try:
                method(fmri)
            except jsonrpc.NmsException as error:
                LOG.error('Failed to change state of migration service '
                          '%(fmri)s to %(state)s: %(error)s',
                          {'fmri': fmri, 'state': state, 'error': error})
        LOG.error('Unable to change state of migration service %(fmri)s '
                  'to %(state)s: maximum retries exceeded',
                  {'fmri': fmri, 'state': state})
        return False

    def _svc_progress(self, fmri):
        """Get progress for SMF service."""
        progress = 0
        try:
            estimations = self.nms.autosync.get_estimations(fmri)
        except jsonrpc.NmsException as error:
            LOG.error('Failed to get estimations for migration '
                      'service %(fmri)s: %(error)s',
                      {'fmri': fmri, 'error': error})
            return progress
        size = estimations.get('curt_siz')
        sent = estimations.get('curt_sen')
        try:
            size = float(size)
            sent = float(sent)
            if size > 0:
                progress = int(100 * sent / size)
        except (TypeError, ValueError) as error:
            LOG.error('Failed to parse estimations statistics '
                      '%(estimations)s for migration service '
                      '%(fmri)s: %(error)s',
                      {'estimations': estimations,
                       'fmri': fmri, 'error': error})
        return progress

    def _svc_result(self, fmri):
        try:
            props = self.nms.autosvc.get_child_props(fmri, '')
        except jsonrpc.NmsException as error:
            LOG.error('Failed to get properties of migration service '
                      '%(fmri)s: %(error)s',
                      {'fmri': fmri, 'error': error})
            return False
        history = props.get('zfs/run_history')
        if not history:
            LOG.error('Failed to get history of migration service '
                      '%(fmri)s: %(props)s',
                      {'fmri': fmri, 'props': props})
            return False
        results = history.split()
        if len(results) > 1:
            LOG.warning('Found unexpected replication sessions for '
                        'migration service %(fmri)s: %(history)s',
                        {'fmri': fmri, 'history': history})
        latest = results.pop()
        start, stop, code = latest.split('::')
        try:
            start = int(start)
            stop = int(stop)
            code = int(code)
        except (TypeError, ValueError) as error:
            LOG.error('Failed to parse history %(history)s for migration '
                      'service %(fmri)s: %(error)s',
                      {'history': history, 'fmri': fmri, 'error': error})
            return False
        delta = stop - start
        if code != 1:
            LOG.error('Migration service %(fmri)s failed after %(delta)s '
                      'seconds, please check the service log below',
                      {'fmri': fmri, 'delta': delta})
            return False
        LOG.info('Migration service %(fmri)s successfully finished in '
                 '%(delta)s seconds',
                 {'fmri': fmri, 'delta': delta})
        return True

    def _svc_cleanup(self, fmri, migrated=False):
        props = None
        flags = {
            'src_properties': '1',
            'dst_properties': '1',
            'src_snapshots': '1',
            'dst_snapshots': '1'
        }
        if not migrated:
            flags['dst_datasets'] = '1'
        try:
            props = self.nms.autosvc.get_child_props(fmri, '')
            props['zfs/sync-recursive'] = '1'
        except jsonrpc.NmsException as error:
            LOG.error('Failed to get properties of migration '
                      'service %(fmri)s: %(error)s',
                      {'fmri': fmri, 'error': error})
        try:
            self.nms.autosvc.unschedule(fmri)
        except jsonrpc.NmsException as error:
            LOG.error('Failed to unschedule migration service '
                      '%(fmri)s: %(error)s',
                      {'fmri': fmri, 'error': error})
        self._svc_state(fmri, 'disabled')
        try:
            self.nms.autosvc.destroy(fmri)
        except jsonrpc.NmsException as error:
            LOG.error('Failed to destroy migration service '
                      '%(fmri)s: %(error)s',
                      {'fmri': fmri, 'error': error})
        if not props:
            return
        try:
            src_pid, dst_pid = self.nms.autosync.cleanup(props, flags)
        except jsonrpc.NmsException as error:
            src_pid = dst_pid = 0
            LOG.error('Failed to cleanup migration service %(fmri)s: '
                      '%(error)s',
                      {'fmri': fmri, 'error': error})
        for pid in [src_pid, dst_pid]:
            while pid:
                try:
                    self.nms.job.get_jobparams(pid)
                except jsonrpc.NmsException as error:
                    if error.code == 'ENOENT':
                        break
                greenthread.sleep(30)
        if migrated:
            return
        path = props.get('restarter/logfile')
        if not path:
            return
        try:
            content = self.nms.logviewer.get_tail(path, units.Mi)
        except jsonrpc.NmsException as error:
            LOG.error('Failed to get log file content for migration '
                      'service %(fmri)s: %(error)s',
                      {'fmri': fmri, 'error': error})
            return
        log = '\n'.join(content)
        LOG.error('Migration service %(fmri)s log: %(log)s',
                  {'fmri': fmri, 'log': log})

    def _migrate_volume(self, volume, host, path):
        delay = 30
        retries = 10
        src_path = self._get_volume_path(volume)
        dst_path = posixpath.join(path, volume['name'])
        hosts = self._get_host_addresses()
        if host in hosts:
            dst_host = 'localhost'
            service_direction = '0'
            service_proto = 'zfs'
            if src_path == dst_path:
                LOG.info('Skip local to local replication: source '
                         'volume %(src_path)s and destination volume '
                         '%(dst_path)s are the same local volume',
                         {'src_path': src_path, 'dst_path': dst_path})
                return True
        else:
            service_direction = '1'
            service_proto = 'zfs+rr'
            dst_host = self._get_bound_host(host)
            if not dst_host:
                LOG.error('Storage assisted volume migration is '
                          'unavailable: the destination host '
                          '%(host)s should be SSH bound',
                          {'host': host})
                return False
        service_name = '%(prefix)s-%(volume)s' % {
            'prefix': self.migration_service_prefix,
            'volume': volume['name']
        }
        comment = 'Migrate %(src)s to %(host)s:%(dst)s' % {
            'src': src_path,
            'host': dst_host,
            'dst': dst_path
        }
        yesterday = timeutils.utcnow() - datetime.timedelta(days=1)
        dst_path = path
        rate_limit = 0
        if self.migration_throttle:
            rate_limit = self.migration_throttle * units.Ki
        payload = {
            'comment': comment,
            'custom_name': service_name,
            'from-fs': src_path,
            'to-host': dst_host,
            'to-fs': dst_path,
            'direction': service_direction,
            'marker_name': self.migration_snapshot_prefix,
            'proto': service_proto,
            'day': six.text_type(yesterday.day),
            'rate_limit': six.text_type(rate_limit),
            '_unique': 'type from-host from-fs to-host to-fs',
            'method': 'sync',
            'from-host': 'localhost',
            'period_multiplier': '1',
            'keep_src': '1',
            'keep_dst': '1',
            'trace_level': '30',
            'type': 'monthly',
            'nconn': '2',
            'period': '12',
            'mbuffer_size': '16',
            'minute': '0',
            'hour': '0',
            'flags': '0',
            'estimations': '0',
            'force': '0',
            'reverse_capable': '0',
            'sync-recursive': '0',
            'auto-clone': '0',
            'flip_options': '0',
            'direction_flipped': '0',
            'retry': '0',
            'success_counter': '0',
            'dircontent': '0',
            'zip_level': '0',
            'auto-mount': '0',
            'marker': '',
            'exclude': '',
            'run_history': '',
            'progress-marker': '',
            'from-snapshot': '',
            'latest-suffix': '',
            'trunk': '',
            'options': ''
        }
        try:
            fmri = self.nms.autosvc.fmri_create('auto-sync', comment,
                                                src_path, 0, payload)
        except jsonrpc.NmsException as error:
            LOG.error('Failed to create migration service '
                      'with payload %(payload)s: %(error)s',
                      {'payload': payload, 'error': error})
            return False
        if not self._svc_state(fmri, 'online'):
            self._svc_cleanup(fmri)
            return False
        service_running = False
        try:
            self.nms.autosvc.execute(fmri)
            service_running = True
            LOG.info('Migration service %(fmri)s successfully started',
                     {'fmri': fmri})
        except jsonrpc.NmsException as error:
            LOG.error('Failed to start migration service %(fmri)s: %(error)s',
                      {'fmri': fmri, 'error': error})
        if not service_running:
            LOG.error('Migration service %(fmri)s is offline',
                      {'fmri': fmri})
            self._svc_cleanup(fmri)
            return False
        service_history = None
        service_retries = retries
        service_progress = 0
        while service_retries and not service_history:
            greenthread.sleep(delay)
            service_retries -= 1
            try:
                service_props = self.nms.autosvc.get_child_props(fmri, '')
            except jsonrpc.NmsException as error:
                LOG.error('Failed to get properties of migration service '
                          '%(fmri)s: %(error)s',
                          {'fmri': fmri, 'error': error})
                continue
            service_history = service_props.get('zfs/run_history')
            service_started = service_props.get('zfs/time_started')
            if service_started == 'N/A':
                continue
            progress = self._svc_progress(fmri)
            if progress > service_progress:
                service_progress = progress
                service_retries = retries
            LOG.info('Migration service %(fmri)s replication progress: '
                     '%(service_progress)s%%',
                     {'fmri': fmri, 'service_progress': service_progress})
        if not service_history:
            self._svc_cleanup(fmri)
            return False
        volume_migrated = self._svc_result(fmri)
        self._svc_cleanup(fmri, volume_migrated)
        if volume_migrated:
            try:
                self.delete_volume(volume)
            except jsonrpc.NmsException as error:
                LOG.error('Failed to delete source volume %(volume)s '
                          'after successful migration: %(error)s',
                          {'volume': volume['name'], 'error': error})
        return volume_migrated

    def migrate_volume(self, context, volume, host):
        """Migrate the volume to the specified host.

        Returns a boolean indicating whether the migration occurred,
        as well as model_update.

        :param context: Security context
        :param volume: A dictionary describing the volume to migrate
        :param host: A dictionary describing the host to migrate to, where
                     host['host'] is its name, and host['capabilities'] is a
                     dictionary of its reported capabilities.
        """
        LOG.info('Start storage assisted volume migration '
                 'for volume %(volume)s to host %(host)s',
                 {'volume': volume['name'],
                  'host': host['host']})
        false_ret = (False, None)
        if 'capabilities' not in host:
            LOG.error('No host capabilities found for '
                      'the destination host %(host)s',
                      {'host': host['host']})
            return false_ret
        capabilities = host['capabilities']
        required_capabilities = [
            'vendor_name',
            'location_info',
            'storage_protocol',
            'free_capacity_gb'
        ]
        for capability in required_capabilities:
            if capability not in capabilities:
                LOG.error('Required host capability %(capability)s not '
                          'found for the destination host %(host)s',
                          {'capability': capability, 'host': host['host']})
                return false_ret
        vendor = capabilities['vendor_name']
        if vendor != self.vendor_name:
            LOG.error('Unsupported vendor %(vendor)s found '
                      'for the destination host %(host)s',
                      {'vendor': vendor, 'host': host['host']})
            return false_ret
        location = capabilities['location_info']
        try:
            driver, nas_host, nas_path = location.split(':')
        except ValueError as error:
            LOG.error('Failed to parse location info %(location)s '
                      'for the destination host %(host)s: %(error)s',
                      {'location': location, 'host': host['host'],
                       'error': error})
            return false_ret
        if not (driver and nas_host and nas_path):
            LOG.error('Incomplete location info %(location)s '
                      'found for the destination host %(host)s',
                      {'location': location, 'host': host['host']})
            return false_ret
        if driver != self.driver_name:
            LOG.error('Unsupported storage driver %(driver)s '
                      'found for the destination host %(host)s',
                      {'driver': driver, 'host': host['host']})
            return false_ret
        storage_protocol = capabilities['storage_protocol']
        if storage_protocol != self.storage_protocol:
            LOG.error('Unsupported storage protocol %(protocol)s '
                      'found for the destination host %(host)s',
                      {'protocol': storage_protocol,
                       'host': host['host']})
            return false_ret
        free_capacity_gb = capabilities['free_capacity_gb']
        if free_capacity_gb < volume['size']:
            LOG.error('There is not enough space available on the '
                      'destination host %(host)s to migrate volume '
                      '%(volume)s, available space: %(free)sG, '
                      'required space: %(required)sG',
                      {'host': host['host'], 'volume': volume['name'],
                       'free': free_capacity_gb,
                       'required': volume['size']})
            return false_ret
        if self._migrate_volume(volume, nas_host, nas_path):
            return (True, None)
        return false_ret

    def update_migrated_volume(self, context, volume, new_volume,
                               original_volume_status):
        """Return model update for migrated volume.

        This method should rename the back-end volume name on the
        destination host back to its original name on the source host.

        :param context: The context of the caller
        :param volume: The original volume that was migrated to this backend
        :param new_volume: The migration volume object that was created on
                           this backend as part of the migration process
        :param original_volume_status: The status of the original volume
        :returns: model_update to update DB with any needed changes
        """
        name_id = None
        volume_path = self._get_volume_path(volume)
        new_volume_path = self._get_volume_path(new_volume)
        try:
            self.terminate_connection(new_volume, None)
        except jsonrpc.NmsException as error:
            LOG.error('Failed to terminate all connections '
                      'to migrated volume %(volume)s before '
                      'renaming: %(error)s',
                      {'volume': new_volume['name'],
                       'error': error})
        cmd = 'zfs rename %(new_volume)s %(volume)s' % {
            'new_volume': new_volume_path,
            'volume': volume_path
        }
        try:
            self.nms.appliance.execute(cmd)
        except jsonrpc.NmsException as error:
            LOG.error('Failed to rename volume %(new_volume)s '
                      'to %(volume)s after migration: %(error)s',
                      {'new_volume': new_volume['name'],
                       'volume': volume['name'],
                       'error': error})
            name_id = new_volume._name_id or new_volume.id
        model_update = {'_name_id': name_id}
        return model_update

    def retype(self, context, volume, new_type, diff, host):
        """Convert the volume to be of the new type."""
        pass

    def create_snapshot(self, snapshot):
        """Creates a snapshot.

        :param snapshot: snapshot reference
        """
        snapshot_path = self._get_snapshot_path(snapshot)
        volume_path, snapshot_name = snapshot_path.split('@')
        self.nms.folder.create_snapshot(volume_path, snapshot_name, '')

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot.

        :param snapshot: snapshot reference
        """
        snapshot_path = self._get_snapshot_path(snapshot)
        self.nms.snapshot.destroy(snapshot_path, '-d')

    def _set_volume_acl(self, volume):
        volume_path = self._get_volume_path(volume)
        group = 'everyone@'
        acl = {
            'allow': [
                'full_set',
                'dir_inherit',
                'file_inherit'
            ]
        }
        self.nms.folder.set_group_acl(volume_path, group, acl)

    def _get_volume_share(self, volume):
        """Return NFS share path for the volume."""
        volume_path = self._get_volume_path(volume)
        filesystem = self.nms.folder.get_child_props(volume_path, '')
        if filesystem['mountpoint'] == 'none':
            self.nms.folder.inherit_prop(volume_path, 'mountpoint', 0)
            filesystem = self.nms.folder.get_child_props(volume_path, '')
        if filesystem['mounted'] != 'yes':
            self.nms.folder.mount(volume_path, 0)
        share = '%s:%s' % (self.nas_host, filesystem['mountpoint'])
        return share

    def _local_volume_dir(self, volume):
        """Get volume dir (mounted locally fs path) for given volume.

        :param volume: volume reference
        """
        share = self._get_volume_share(volume)
        if six.PY3:
            share = share.encode('utf-8')
        path = hashlib.md5(share).hexdigest()
        return os.path.join(self.mount_point_base, path)

    def local_path(self, volume):
        """Get volume path (mounted locally fs path) for given volume.

        :param volume: volume reference
        """
        volume_dir = self._local_volume_dir(volume)
        return os.path.join(volume_dir, 'volume')

    def get_volume_stats(self, refresh=False):
        """Get volume stats.

        If 'refresh' is True, update the stats first.
        """
        if refresh or not self._stats:
            self._update_volume_stats()

        return self._stats

    def _update_volume_stats(self):
        """Retrieve stats info for NexentaStor appliance."""
        pool_name = self.root_path.split('/')[0]
        stats = {'available': None, 'used': None}
        payload = '|'.join(stats.keys())
        props = self.nms.folder.get_child_props(self.root_path, payload)
        for key in stats:
            if not props.get(key):
                LOG.error('Unable to get %(key)s statistics for %(path)s '
                          'from properties %(props)s',
                          {'path': self.root_path, 'props': props})
                continue
            text = '%sB' % props[key]
            try:
                value = strutils.string_to_bytes(text, return_int=True)
                stats[key] = value
            except ValueError as error:
                LOG.error('Failed to convert text value %(text)s to '
                          'bytes for the %(key)s property: %(error)s',
                          {'text': text, 'key': key, 'error': error})
        if None in stats.values():
            allocated_capacity_gb = 'unknown'
            free_capacity_gb = 'unknown'
            total_capacity_gb = 'unknown'
        else:
            free_capacity_gb = stats['available'] // units.Gi
            allocated_capacity_gb = stats['used'] // units.Gi
            total_capacity_gb = free_capacity_gb + allocated_capacity_gb
        provisioned_capacity_gb = total_volumes = 0
        ctxt = context.get_admin_context()
        volumes = objects.VolumeList.get_all_by_host(ctxt, self.host)
        for volume in volumes:
            provisioned_capacity_gb += volume['size']
            total_volumes += 1
        volume_backend_name = (
            self.configuration.safe_get('volume_backend_name'))
        if not volume_backend_name:
            LOG.error('Failed to get configured volume backend name')
            volume_backend_name = '%(product)s_%(protocol)s' % {
                'product': self.product_name,
                'protocol': self.storage_protocol
            }
        description = (
            self.configuration.safe_get('nexenta_dataset_description'))
        if not description:
            description = '%(product)s %(host)s:%(path)s' % {
                'product': self.product_name,
                'host': self.configuration.nas_host,
                'path': self.configuration.nas_share_path
            }
        max_over_subscription_ratio = (
            self.configuration.safe_get('max_over_subscription_ratio'))
        reserved_percentage = (
            self.configuration.safe_get('reserved_percentage'))
        if reserved_percentage is None:
            reserved_percentage = 0
        location_info = '%(driver)s:%(host)s:%(path)s' % {
            'driver': self.driver_name,
            'host': self.configuration.nas_host,
            'path': self.configuration.nas_share_path
        }
        display_name = 'Capabilities of %(product)s %(protocol)s driver' % {
            'product': self.product_name,
            'protocol': self.storage_protocol
        }
        visibility = 'public'
        self._stats = {
            'driver_version': self.VERSION,
            'vendor_name': self.vendor_name,
            'storage_protocol': self.storage_protocol,
            'volume_backend_name': volume_backend_name,
            'location_info': location_info,
            'description': description,
            'display_name': display_name,
            'pool_name': pool_name,
            'multiattach': True,
            'QoS_support': False,
            'consistencygroup_support': False,
            'consistent_group_snapshot_enabled': False,
            'online_extend_support': True,
            'sparse_copy_volume': True,
            'thin_provisioning_support': True,
            'thick_provisioning_support': True,
            'total_capacity_gb': total_capacity_gb,
            'allocated_capacity_gb': allocated_capacity_gb,
            'free_capacity_gb': free_capacity_gb,
            'provisioned_capacity_gb': provisioned_capacity_gb,
            'total_volumes': total_volumes,
            'max_over_subscription_ratio': max_over_subscription_ratio,
            'reserved_percentage': reserved_percentage,
            'visibility': visibility,
            'dedup': self.configuration.nexenta_dataset_dedup,
            'compression': self.configuration.nexenta_dataset_compression,
            'nms_url': self.nms.url
        }
        LOG.debug('Updated volume backend statistics for host %(host)s '
                  'and volume backend %(volume_backend_name)s: %(stats)s',
                  {'host': self.host,
                   'volume_backend_name': volume_backend_name,
                   'stats': self._stats})

    def _get_volume_path(self, volume):
        """Return ZFS datset path for the volume."""
        return posixpath.join(self.root_path, volume['name'])

    def _get_snapshot_path(self, snapshot):
        """Return ZFS snapshot path for the snapshot."""
        volume_name = snapshot['volume_name']
        snapshot_name = snapshot['name']
        volume_path = posixpath.join(self.root_path, volume_name)
        return '%s@%s' % (volume_path, snapshot_name)

    def _get_host_addresses(self):
        """Return NexentaStor IP addresses list."""
        addresses = []
        items = self.nms.appliance.execute('ipadm show-addr -p -o addr')
        for item in items:
            cidr = six.text_type(item)
            addr, mask = cidr.split('/')
            obj = ipaddress.ip_address(addr)
            if not obj.is_loopback:
                addresses.append(obj.exploded)
        LOG.debug('Configured IP addresses: %(addresses)s',
                  {'addresses': addresses})
        return addresses

    @staticmethod
    def _match_template(template, name):
        sequence = difflib.SequenceMatcher(None, name, template)
        added = deleted = result = ''
        for tag, a1, a2, b1, b2 in sequence.get_opcodes():
            if tag == 'equal':
                result += ''.join(sequence.a[a1:a2])
            elif tag == 'delete':
                deleted += ''.join(sequence.a[a1:a2])
            elif tag == 'insert':
                added += ''.join(sequence.b[b1:b2])
            elif tag == 'replace':
                result += ''.join(sequence.b[b1:b2])
        if result == template and not (added or deleted):
            return True
        return False
