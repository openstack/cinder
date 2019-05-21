# Copyright 2019 Nexenta Systems, Inc. All Rights Reserved.
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
import ipaddress
import posixpath
import random
import uuid

from eventlet import greenthread
from oslo_log import log as logging
from oslo_utils import strutils
from oslo_utils import timeutils
from oslo_utils import units
import six

from cinder import context
from cinder.i18n import _
from cinder import objects
from cinder.volume import driver
from cinder.volume.drivers.nexenta import jsonrpc
from cinder.volume.drivers.nexenta import options

LOG = logging.getLogger(__name__)


class NexentaISCSIDriver(driver.ISCSIDriver):
    """Executes volume driver commands on Nexenta Appliance.

    Version history:

    .. code-block:: none

        1.0.0 - Initial driver version.
        1.0.1 - Fixed bug #1236626: catch "does not exist" exception of
                lu_exists.
        1.1.0 - Changed class name to NexentaISCSIDriver.
        1.1.1 - Ignore "does not exist" exception of nms.snapshot.destroy.
        1.1.2 - Optimized create_cloned_volume, replaced zfs send recv with zfs
                clone.
        1.1.3 - Extended volume stats provided by _update_volume_stats method.
        1.2.0 - Added volume migration with storage assist method.
        1.2.1 - Fixed bug #1263258: now migrate_volume update provider_location
                of migrated volume; after migrating volume migrate_volume
                destroy snapshot on migration destination.
        1.3.0 - Added retype method.
        1.3.0.1 - Target creation refactor.
        1.3.1 - Added ZFS cleanup.
        1.3.2 - Added support for target_portal_group and zvol folder.
        1.3.3 - Added synchronization for Comstar API calls.
        1.4.0 - Fixed automatic mode for nexenta_rest_protocol.
              - Fixed compatibility with initial driver version.
              - Fixed deletion of temporary snapshots.
              - Fixed creation of volumes with enabled compression option.
              - Refactored LUN creation, use host group for LUN mappings.
              - Refactored storage assisted volume migration.
              - Added deferred deletion for snapshots.
              - Added volume multi-attach.
              - Added report discard support.
              - Added informative exception messages for REST API.
              - Added configuration parameters for REST API connect/read.
                timeouts, connection retries and backoff factor.
              - Added configuration parameter for LUN writeback cache.
              - Improved collection of backend statistics.
        1.4.1 - Added retries on timeouts, network connection errors,
                SSL errors, proxy and NMS errors.
    """

    VERSION = '1.4.1'
    CI_WIKI_NAME = "Nexenta_CI"

    vendor_name = 'Nexenta'
    product_name = 'NexentaStor4'
    storage_protocol = 'iSCSI'
    driver_volume_type = 'iscsi'

    def __init__(self, *args, **kwargs):
        super(NexentaISCSIDriver, self).__init__(*args, **kwargs)
        if not self.configuration:
            message = (_('%(product_name)s %(storage_protocol)s '
                         'backend configuration not found')
                       % {'product_name': self.product_name,
                          'storage_protocol': self.storage_protocol})
            raise jsonrpc.NmsException(code='EINVAL', message=message)
        self.configuration.append_config_values(
            options.NEXENTA_CONNECTION_OPTS)
        self.configuration.append_config_values(options.NEXENTA_ISCSI_OPTS)
        self.configuration.append_config_values(options.NEXENTA_DATASET_OPTS)
        required_options = ['nexenta_host', 'nexenta_volume', 'nexenta_user',
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
        self.mappings = {}
        self.driver_name = self.__class__.__name__
        self.san_host = self.configuration.nexenta_host
        self.volume = self.configuration.nexenta_volume
        self.folder = self.configuration.nexenta_folder
        self.volume_compression = (
            self.configuration.nexenta_dataset_compression)
        self.volume_blocksize = self.configuration.nexenta_blocksize
        self.volume_sparse = self.configuration.nexenta_sparse
        self.tpgs = self.configuration.nexenta_iscsi_target_portal_groups
        self.target_prefix = self.configuration.nexenta_target_prefix
        self.target_group_prefix = (
            self.configuration.nexenta_target_group_prefix)
        self.host_group_prefix = self.configuration.nexenta_host_group_prefix
        self.lpt = self.configuration.nexenta_luns_per_target
        self.portal_port = self.configuration.nexenta_iscsi_target_portal_port
        self.origin_snapshot_template = (
            self.configuration.nexenta_origin_snapshot_template)
        self.migration_snapshot_prefix = (
            self.configuration.nexenta_migration_snapshot_prefix)
        self.migration_service_prefix = (
            self.configuration.nexenta_migration_service_prefix)
        self.migration_throttle = (
            self.configuration.nexenta_migration_throttle)
        if self.folder:
            self.root_path = posixpath.join(self.volume, self.folder)
        else:
            self.root_path = self.volume

    def do_setup(self, context):
        self.nms = jsonrpc.NmsProxy(self.driver_volume_type,
                                    self.root_path,
                                    self.configuration)

    def check_for_setup_error(self):
        """Verify that the volume, folder and tpgs exists."""
        if not self.nms.volume.object_exists(self.volume):
            message = (_('Volume %(volume)s not found')
                       % {'volume': self.volume})
            raise jsonrpc.NmsException(code='ENOENT', message=message)
        if not self.nms.folder.object_exists(self.root_path):
            message = (_('Folder %(folder)s not found')
                       % {'folder': self.root_path})
            raise jsonrpc.NmsException(code='ENOENT', message=message)
        host_tpgs = self.nms.iscsitarget.list_tpg()
        for tpg in self.tpgs:
            if tpg in host_tpgs:
                continue
            message = (_('Target portal group %(tpg)s not found')
                       % {'tpg': tpg})
            raise jsonrpc.NmsException(code='ENOENT', message=message)

    def _get_volume_path(self, volume):
        """Return ZFS datset path for the volume."""
        return posixpath.join(self.root_path, volume['name'])

    def _get_snapshot_path(self, snapshot):
        """Return ZFS snapshot path for the snapshot."""
        volume_name = snapshot['volume_name']
        snapshot_name = snapshot['name']
        volume_path = posixpath.join(self.root_path, volume_name)
        return '%s@%s' % (volume_path, snapshot_name)

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

    def _create_target_group(self, group, target):
        """Create a new target group with target member.

        :param group: group name
        :param target: group member
        """
        if not self._target_exists(target):
            tpgs = ','.join(self.tpgs)
            payload = {
                'target_name': target,
                'tpgs': tpgs
            }
            self.nms.iscsitarget.create_target(payload)
        if not self._target_group_exists(group):
            self.nms.stmf.create_targetgroup(group)
        if not self._target_member_in_target_group(group, target):
            self.nms.stmf.add_targetgroup_member(group, target)

    def create_volume(self, volume):
        """Create a zvol on appliance.

        :param volume: volume reference
        :return: model update dict for volume reference
        """
        volume_path = self._get_volume_path(volume)
        volume_size = '%sG' % volume['size']
        volume_blocksize = six.text_type(self.volume_blocksize)
        volume_sparsed = self.volume_sparse
        volume_options = {'compression': self.volume_compression}
        self.nms.zvol.create_with_props(volume_path, volume_size,
                                        volume_blocksize,
                                        volume_sparsed,
                                        volume_options)

    def extend_volume(self, volume, new_size):
        """Extend an existing volume.

        :param volume: volume reference
        :param new_size: volume new size in GB
        """
        volume_path = self._get_volume_path(volume)
        volume_size = '%sG' % new_size
        self.nms.zvol.set_child_prop(volume_path, 'volsize', volume_size)

    def delete_volume(self, volume):
        """Deletes a logical volume.

        :param volume: volume reference
        """
        volume_path = self._get_volume_path(volume)
        try:
            origin = self.nms.zvol.get_child_prop(volume_path, 'origin')
        except jsonrpc.NmsException as error:
            if error.code == 'ENOENT':
                return
            raise
        self.nms.zvol.destroy(volume_path, '-r')
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
            driver, san_host, san_path = location.split(':')
        except ValueError as error:
            LOG.error('Failed to parse location info %(location)s '
                      'for the destination host %(host)s: %(error)s',
                      {'location': location, 'host': host['host'],
                       'error': error})
            return false_ret
        if not (driver and san_host and san_path):
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
        if self._migrate_volume(volume, san_host, san_path):
            return (True, None)
        return false_ret

    def retype(self, context, volume, new_type, diff, host):
        """Convert the volume to be of the new type."""
        pass

    def create_snapshot(self, snapshot):
        """Creates a snapshot.

        :param snapshot: snapshot reference
        """
        snapshot_path = self._get_snapshot_path(snapshot)
        volume_path, snapshot_name = snapshot_path.split('@')
        self.nms.zvol.create_snapshot(volume_path, snapshot_name, '')

    def create_volume_from_snapshot(self, volume, snapshot):
        """Create new volume from other's snapshot on appliance.

        :param volume: reference of volume to be created
        :param snapshot: reference of source snapshot
        """
        snapshot_path = self._get_snapshot_path(snapshot)
        clone_path = self._get_volume_path(volume)
        self.nms.zvol.clone(snapshot_path, clone_path)
        if volume['size'] > snapshot['volume_size']:
            self.extend_volume(volume, volume['size'])

    def delete_snapshot(self, snapshot):
        """Delete volume's snapshot on appliance.

        :param snapshot: snapshot reference
        """
        snapshot_path = self._get_snapshot_path(snapshot)
        self.nms.snapshot.destroy(snapshot_path, '-d')

    def local_path(self, volume):
        """Return local path to existing local volume."""
        raise NotImplementedError

    def _target_exists(self, target):
        """Check if iSCSI target exist.

        :param target: target name
        :return: True if target exist, else False
        """
        targets = self.nms.stmf.list_targets()
        return target in targets

    def _target_group_exists(self, group):
        """Check if target group exist.

        :param group: target group
        :return: True if target group exist, else False
        """
        groups = self.nms.stmf.list_targetgroups()
        return group in groups

    def _target_member_in_target_group(self, group, member):
        """Check if target member in target group.

        :param group: target group
        :param member: target member
        :return: True if target member in target group, else False
        :raises: NexentaException if target group doesn't exist
        """
        members = self.nms.stmf.list_targetgroup_members(group)
        return member in members

    def _lu_exists(self, volume_path):
        """Check if LU exists on appliance.

        :param volume_path: volume path
        :raises: NmsException if volume not exists
        :return: True if LU exists, else False
        """
        try:
            return bool(self.nms.scsidisk.lu_exists(volume_path))
        except jsonrpc.NmsException as error:
            if error.code == 'ENOENT':
                return False
            raise

    def _is_lu_shared(self, volume_path):
        """Check if LU exists on appliance and shared.

        :param volume_path: volume path
        :raises: NmsException if volume not exist
        :return: True if LU exists and shared, else False
        """
        try:
            return bool(self.nms.scsidisk.lu_shared(volume_path))
        except jsonrpc.NmsException as error:
            if error.code == 'ENOENT':
                return False
            raise

    def create_export(self, context, volume, connector):
        """Driver entry point to get the export info for a new volume."""
        pass

    def ensure_export(self, context, volume):
        """Driver entry point to get the export info for an existing volume."""
        pass

    def remove_export(self, context, volume):
        """Driver entry point to remove an export for a volume."""
        pass

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

    def _get_host_portals(self):
        """Return NexentaStor iSCSI portals list."""
        portals = []
        addresses = self._get_host_addresses()
        for address in addresses:
            portal = '%s:%s' % (address, self.portal_port)
            portals.append(portal)
        LOG.debug('Configured iSCSI portals: %(portals)s',
                  {'portals': portals})
        return portals

    def _get_host_portal_groups(self):
        """Return NexentaStor iSCSI portal groups dictionary."""
        portal_groups = {}
        default_portal = '%s:%s' % (self.san_host, self.portal_port)
        host_portals = self._get_host_portals()
        host_portal_groups = self.nms.iscsitarget.list_tpg()
        for group in host_portal_groups:
            group_portals = host_portal_groups[group]
            if not self.tpgs:
                if default_portal in group_portals:
                    LOG.debug('Use default portal %(portal)s '
                              'for portal group %(group)s',
                              {'portal': default_portal,
                               'group': group})
                    portal_groups[group] = [default_portal]
                continue
            if group not in self.tpgs:
                LOG.debug('Skip existing but not configured '
                          'target portal group %(group)s',
                          {'group': group})
                continue
            portals = []
            for portal in group_portals:
                if portal not in host_portals:
                    LOG.debug('Skip non-existing '
                              'portal %(portal)s',
                              {'portal': portal})
                    continue
                portals.append(portal)
            if portals:
                portal_groups[group] = portals
        LOG.debug('Configured host target '
                  'portal groups: %(groups)s',
                  {'groups': portal_groups})
        return portal_groups

    def _get_host_targets(self):
        """Return NexentaStor iSCSI targets dictionary."""
        targets = {}
        default_portal = '%s:%s' % (self.san_host, self.portal_port)
        host_portal_groups = self._get_host_portal_groups()
        stmf_targets = self.nms.stmf.list_targets()
        for name in stmf_targets:
            if not name.startswith(self.target_prefix):
                LOG.debug('Skip not a cinder target %(name)s',
                          {'name': name})
                continue
            target = stmf_targets[name]
            if not ('protocol' in target and target['protocol'] == 'iSCSI'):
                LOG.debug('Skip non-iSCSI target %(target)s',
                          {'target': target})
                continue
            if not ('status' in target and target['status'] == 'Online'):
                LOG.debug('Skip non-online iSCSI target %(target)s',
                          {'target': target})
                continue
            target_portals = []
            props = self.nms.iscsitarget.get_target_props(name)
            if 'tpgs' in props:
                target_portal_groups = props['tpgs'].split(',')
                for group in target_portal_groups:
                    if group not in host_portal_groups:
                        LOG.debug('Skip existing but unsuitable target portal '
                                  'group %(group)s for iSCSI target %(name)s',
                                  {'group': group, 'name': name})
                        continue
                    portals = host_portal_groups[group]
                    target_portals += portals
            else:
                portals = [default_portal]
                target_portals += portals
            if target_portals:
                targets[name] = target_portals
        LOG.debug('Configured iSCSI targets: %(targets)s',
                  {'targets': targets})
        return targets

    def _target_group_props(self, group_name, host_targets):
        """Check existing targets/portals for the given target group.

        :param group_name: target group name
        :param host_targets: host targets dictionary
        :returns: dictionary of portals per target
        """
        if not group_name.startswith(self.target_group_prefix):
            LOG.debug('Skip not a cinder target group %(group)s',
                      {'group': group_name})
            return {}
        group_targets = self.nms.stmf.list_targetgroup_members(group_name)
        if not group_targets:
            LOG.debug('Skip target group %(group)s: group has no members',
                      {'group': group_name})
            return {}
        group_props = {}
        for target_name in group_targets:
            if target_name not in host_targets:
                LOG.debug('Skip existing but unsuitable member '
                          'of target group %(group)s: %(target)s',
                          {'group': group_name,
                           'target': target_name})
                continue
            portals = host_targets[target_name]
            if not portals:
                LOG.debug('Skip existing but unsuitable member '
                          'of target group %(group)s: %(target)s',
                          {'group': group_name,
                           'target': target_name})
                continue
            LOG.debug('Found member of target group %(group)s: '
                      'iSCSI target %(target)s listening on '
                      'portals %(portals)s',
                      {'group': group_name,
                       'target': target_name,
                       'portals': portals})
            group_props[target_name] = portals
        LOG.debug('Target group %(group)s members: %(members)s',
                  {'group': group_name,
                   'members': group_props})
        return group_props

    def initialize_connection(self, volume, connector):
        """Do all steps to get zfs volume exported at separate target.

        :param volume: volume reference
        :param connector: connector reference
        :returns: dictionary of connection information
        """
        volume_path = self._get_volume_path(volume)
        host_iqn = connector.get('initiator')
        LOG.debug('Initialize connection for volume: %(volume)s and '
                  'initiator: %(initiator)s',
                  {'volume': volume['name'], 'initiator': host_iqn})
        suffix = uuid.uuid4().hex
        host_targets = self._get_host_targets()
        host_groups = ['All']
        host_group = self._get_host_group(host_iqn)
        if host_group:
            host_groups.append(host_group)
        props_portals = []
        props_iqns = []
        props_luns = []
        mappings = []
        if self._is_lu_shared(volume_path):
            mappings = self.nms.scsidisk.list_lun_mapping_entries(volume_path)
        for mapping in mappings:
            mapping_lu = int(mapping['lun'])
            mapping_hg = mapping['host_group']
            mapping_tg = mapping['target_group']
            mapping_id = mapping['entry_number']
            if mapping_tg == 'All':
                LOG.debug('Delete LUN mapping %(id)s for target group %(tg)s',
                          {'id': mapping_id, 'tg': mapping_tg})
                self.nms.scsidisk.remove_lun_mapping_entry(volume_path,
                                                           mapping_id)
                continue
            if mapping_hg not in host_groups:
                LOG.debug('Skip LUN mapping %(id)s for host group %(hg)s',
                          {'id': mapping_id, 'hg': mapping_hg})
                continue
            group_props = self._target_group_props(mapping_tg,
                                                   host_targets)
            if not group_props:
                LOG.debug('Skip LUN mapping %(id)s for target group %(tg)s',
                          {'id': mapping_id, 'tg': mapping_tg})
                continue
            for target_iqn in group_props:
                target_portals = group_props[target_iqn]
                props_portals += target_portals
                props_iqns += [target_iqn] * len(target_portals)
                props_luns += [mapping_lu] * len(target_portals)

        props = {}
        props['discard'] = True
        props['target_discovered'] = False
        props['encrypted'] = False
        props['qos_specs'] = None
        props['volume_id'] = volume['id']
        props['access_mode'] = 'rw'
        multipath = connector.get('multipath', False)
        if props_luns:
            if multipath:
                props['target_portals'] = props_portals
                props['target_iqns'] = props_iqns
                props['target_luns'] = props_luns
            else:
                index = random.randrange(len(props_luns))
                props['target_portal'] = props_portals[index]
                props['target_iqn'] = props_iqns[index]
                props['target_lun'] = props_luns[index]
            LOG.debug('Use existing LUN mapping %(props)s',
                      {'props': props})
            return {'driver_volume_type': self.driver_volume_type,
                    'data': props}

        if host_group is None:
            host_group = '%s-%s' % (self.host_group_prefix, suffix)
            self._create_host_group(host_group, host_iqn)
        else:
            LOG.debug('Use existing host group %(group)s',
                      {'group': host_group})

        mappings_stat = {}
        group_targets = {}
        target_groups = self.nms.stmf.list_targetgroups()
        for target_group in target_groups:
            if (target_group in self.mappings and
                    self.mappings[target_group] >= self.lpt):
                LOG.debug('Skip existing target group %(group)s: '
                          '%(count)s LUN mappings limit reached',
                          {'group': target_group,
                           'count': self.mappings[target_group]})
                continue
            group_props = self._target_group_props(target_group,
                                                   host_targets)
            if not group_props:
                LOG.debug('Skip unsuitable target group %(group)s',
                          {'group': target_group})
                continue
            group_targets[target_group] = group_props
            if target_group in self.mappings:
                mappings_stat[target_group] = self.mappings[target_group]
            else:
                mappings_stat[target_group] = self.mappings[target_group] = 0

        if mappings_stat:
            target_group = min(mappings_stat, key=mappings_stat.get)
            LOG.debug('Use existing target group %(group)s with '
                      '%(count)s LUN mappings created',
                      {'group': target_group,
                       'count': mappings_stat[target_group]})
        else:
            target = '%s:%s' % (self.target_prefix, suffix)
            target_group = '%s-%s' % (self.target_group_prefix, suffix)
            self._create_target_group(target_group, target)
            host_targets = self._get_host_targets()
            group_props = self._target_group_props(target_group, host_targets)
            group_targets[target_group] = group_props
            self.mappings[target_group] = 0
        if not self._lu_exists(volume_path):
            payload = {'serial': volume['id']}
            self.nms.scsidisk.create_lu(volume_path, payload)
        if not self.configuration.nexenta_lu_writebackcache_disabled:
            self.nms.scsidisk.writeback_cache_enable(volume_path)
        payload = {
            'target_group': target_group,
            'host_group': host_group
        }
        entry = self.nms.scsidisk.add_lun_mapping_entry(volume_path, payload)
        self.mappings[target_group] += 1
        lun = int(entry['lun'])
        targets = group_targets[target_group]
        for target in targets:
            portals = targets[target]
            props_portals += portals
            props_iqns += [target] * len(portals)
            props_luns += [lun] * len(portals)

        if multipath:
            props['target_portals'] = props_portals
            props['target_iqns'] = props_iqns
            props['target_luns'] = props_luns
        else:
            index = random.randrange(len(props_luns))
            props['target_portal'] = props_portals[index]
            props['target_iqn'] = props_iqns[index]
            props['target_lun'] = props_luns[index]
        LOG.debug('Created new LUN mapping: %(props)s',
                  {'props': props})
        return {'driver_volume_type': self.driver_volume_type,
                'data': props}

    def _get_host_group(self, member):
        """Find existing host group by group member.

        :param member: host group member
        :returns: host group name
        """
        groups = self.nms.stmf.list_hostgroups()
        for group in groups:
            members = self.nms.stmf.list_hostgroup_members(group)
            if member in members:
                LOG.debug('Found host group %(group)s for member %(member)s',
                          {'group': group, 'member': member})
                return group
        return None

    def _create_host_group(self, group, member):
        """Create a new host group.

        :param group: host group name
        :param member: host group member
        """
        LOG.debug('Create new host group %(group)s',
                  {'group': group})
        self.nms.stmf.create_hostgroup(group)
        LOG.debug('Add member %(member)s to host group %(group)s',
                  {'member': member, 'group': group})
        self.nms.stmf.add_hostgroup_member(group, member)

    def terminate_connection(self, volume, connector, **kwargs):
        """Terminate a connection to a volume.

        :param volume: a volume object
        :param connector: a connector object
        :returns: dictionary of connection information
        """
        info = {'driver_volume_type': self.driver_volume_type, 'data': {}}
        volume_path = self._get_volume_path(volume)
        host_groups = []
        host_iqn = None
        if isinstance(connector, dict) and 'initiator' in connector:
            connectors = []
            if 'volume_attachment' in volume:
                if isinstance(volume['volume_attachment'], list):
                    for attachment in volume['volume_attachment']:
                        if not isinstance(attachment, dict):
                            continue
                        if 'connector' not in attachment:
                            continue
                        connectors.append(attachment['connector'])
            if connectors.count(connector) > 1:
                LOG.debug('Detected %(count)s connections from host '
                          '%(host_name)s (IP:%(host_ip)s) to volume '
                          '%(volume)s, skip terminating connection',
                          {'count': connectors.count(connector),
                           'host_name': connector.get('host', 'unknown'),
                           'host_ip': connector.get('ip', 'unknown'),
                           'volume': volume['name']})
                return True
            host_iqn = connector['initiator']
            host_groups.append('All')
            host_group = self._get_host_group(host_iqn)
            if host_group is not None:
                host_groups.append(host_group)
            LOG.debug('Terminate connection for volume %(volume)s and '
                      'initiator %(initiator)s',
                      {'volume': volume['name'],
                       'initiator': host_iqn})
        else:
            LOG.debug('Terminate all connections for volume %(volume)s',
                      {'volume': volume['name']})

        if not self._is_lu_shared(volume_path):
            LOG.debug('No LUN mappings found for volume %(volume)s',
                      {'volume': volume['name']})
            return info
        mappings = self.nms.scsidisk.list_lun_mapping_entries(volume_path)
        for mapping in mappings:
            mapping_hg = mapping['host_group']
            mapping_tg = mapping['target_group']
            mapping_id = mapping['entry_number']
            if host_iqn is None or mapping_hg in host_groups:
                LOG.debug('Delete LUN mapping %(id)s for volume %(volume)s, '
                          'arget group %(tg)s and host group %(hg)s',
                          {'id': mapping_id, 'volume': volume['name'],
                           'tg': mapping_tg, 'hg': mapping_hg})
                if (mapping_tg in self.mappings and
                        self.mappings[mapping_tg] > 0):
                    self.mappings[mapping_tg] -= 1
                else:
                    self.mappings[mapping_tg] = 0
                self.nms.scsidisk.remove_lun_mapping_entry(volume_path,
                                                           mapping_id)
            else:
                LOG.debug('Keep LUN mapping %(id)s for volume %(volume)s, '
                          'target group %(tg)s and host group %(hg)s',
                          {'id': mapping_id, 'volume': volume['name'],
                           'tg': mapping_tg, 'hg': mapping_hg})
        return info

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
        payload = 'zfs rename %(new_volume)s %(volume)s' % {
            'new_volume': new_volume_path,
            'volume': volume_path
        }
        try:
            self.nms.appliance.execute(payload)
        except jsonrpc.NmsException as error:
            LOG.error('Failed to rename volume %(new_volume)s '
                      'to %(volume)s after migration: %(error)s',
                      {'new_volume': new_volume['name'],
                       'volume': volume['name'],
                       'error': error})
            name_id = new_volume._name_id or new_volume.id
        model_update = {'_name_id': name_id}
        return model_update

    def get_volume_stats(self, refresh=False):
        """Get volume stats.

        If 'refresh' is True, run update the stats first.
        """
        if refresh or not self._stats:
            self._update_volume_stats()

        return self._stats

    def _update_volume_stats(self):
        """Retrieve stats info for NexentaStor appliance."""
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
            description = '%(product)s %(host)s:%(pool)s/%(group)s' % {
                'product': self.product_name,
                'host': self.configuration.nexenta_host,
                'pool': self.configuration.nexenta_volume,
                'group': self.configuration.nexenta_folder
            }
        max_over_subscription_ratio = (
            self.configuration.safe_get('max_over_subscription_ratio'))
        reserved_percentage = (
            self.configuration.safe_get('reserved_percentage'))
        if reserved_percentage is None:
            reserved_percentage = 0
        location_info = '%(driver)s:%(host)s:%(path)s' % {
            'driver': self.driver_name,
            'host': self.configuration.nexenta_host,
            'path': self.root_path
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
            'pool_name': self.configuration.nexenta_volume,
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
            'iscsi_target_portal_port': self.portal_port,
            'nms_url': self.nms.url
        }
        LOG.debug('Updated volume backend statistics for host %(host)s '
                  'and volume backend %(volume_backend_name)s: %(stats)s',
                  {'host': self.host,
                   'volume_backend_name': volume_backend_name,
                   'stats': self._stats})
