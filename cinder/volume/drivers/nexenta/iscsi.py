# Copyright 2016 Nexenta Systems, Inc. All Rights Reserved.
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

from oslo_log import log as logging
from oslo_utils import excutils
import six

from cinder import exception
from cinder.i18n import _
from cinder import interface
from cinder.volume import driver
from cinder.volume.drivers.nexenta import jsonrpc
from cinder.volume.drivers.nexenta import options
from cinder.volume.drivers.nexenta import utils

VERSION = '1.3.1'
LOG = logging.getLogger(__name__)


@interface.volumedriver
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
    """

    VERSION = VERSION

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "Nexenta_CI"

    def __init__(self, *args, **kwargs):
        super(NexentaISCSIDriver, self).__init__(*args, **kwargs)
        self.nms = None
        self.targets = {}
        if self.configuration:
            self.configuration.append_config_values(
                options.NEXENTA_CONNECTION_OPTS)
            self.configuration.append_config_values(
                options.NEXENTA_ISCSI_OPTS)
            self.configuration.append_config_values(
                options.NEXENTA_DATASET_OPTS)
            self.configuration.append_config_values(
                options.NEXENTA_RRMGR_OPTS)
        self.nms_protocol = self.configuration.nexenta_rest_protocol
        self.nms_host = self.configuration.nexenta_host
        self.nms_port = self.configuration.nexenta_rest_port
        self.nms_user = self.configuration.nexenta_user
        self.nms_password = self.configuration.nexenta_password
        self.volume = self.configuration.nexenta_volume
        self.volume_compression = (
            self.configuration.nexenta_dataset_compression)
        self.volume_deduplication = self.configuration.nexenta_dataset_dedup
        self.volume_description = (
            self.configuration.nexenta_dataset_description)
        self.rrmgr_compression = self.configuration.nexenta_rrmgr_compression
        self.rrmgr_tcp_buf_size = self.configuration.nexenta_rrmgr_tcp_buf_size
        self.rrmgr_connections = self.configuration.nexenta_rrmgr_connections
        self.iscsi_target_portal_port = (
            self.configuration.nexenta_iscsi_target_portal_port)

        self._needless_objects = set()

    @staticmethod
    def get_driver_options():
        return (options.NEXENTA_CONNECTION_OPTS + options.NEXENTA_ISCSI_OPTS +
                options.NEXENTA_DATASET_OPTS + options.NEXENTA_RRMGR_OPTS)

    @property
    def backend_name(self):
        backend_name = None
        if self.configuration:
            backend_name = self.configuration.safe_get('volume_backend_name')
        if not backend_name:
            backend_name = self.__class__.__name__
        return backend_name

    def do_setup(self, context):
        if self.nms_protocol == 'auto':
            protocol, auto = 'http', True
        else:
            protocol, auto = self.nms_protocol, False
        self.nms = jsonrpc.NexentaJSONProxy(
            protocol, self.nms_host, self.nms_port, '/rest/nms', self.nms_user,
            self.nms_password, auto=auto)

    def check_for_setup_error(self):
        """Verify that the volume for our zvols exists.

        :raise: :py:exc:`LookupError`
        """
        if not self.nms.volume.object_exists(self.volume):
            raise LookupError(_("Volume %s does not exist in Nexenta SA") %
                              self.volume)

    def _get_zvol_name(self, volume_name):
        """Return zvol name that corresponds given volume name."""
        return '%s/%s' % (self.volume, volume_name)

    def _create_target(self, target_idx):
        target_name = '%s%s-%i' % (
            self.configuration.nexenta_target_prefix,
            self.nms_host,
            target_idx
        )
        target_group_name = self._get_target_group_name(target_name)

        if not self._target_exists(target_name):
            try:
                self.nms.iscsitarget.create_target({
                    'target_name': target_name})
            except utils.NexentaException as exc:
                if 'already' in exc.args[0]:
                    LOG.info('Ignored target creation error "%s" while '
                             'ensuring export.',
                             exc)
                else:
                    raise
        if not self._target_group_exists(target_group_name):
            try:
                self.nms.stmf.create_targetgroup(target_group_name)
            except utils.NexentaException as exc:
                if ('already' in exc.args[0]):
                    LOG.info('Ignored target group creation error "%s" '
                             'while ensuring export.',
                             exc)
                else:
                    raise
        if not self._target_member_in_target_group(target_group_name,
                                                   target_name):
            try:
                self.nms.stmf.add_targetgroup_member(target_group_name,
                                                     target_name)
            except utils.NexentaException as exc:
                if ('already' in exc.args[0]):
                    LOG.info('Ignored target group member addition error '
                             '"%s" while ensuring export.',
                             exc)
                else:
                    raise

        self.targets[target_name] = []
        return target_name

    def _get_target_name(self, volume):
        """Return iSCSI target name with least LUs."""
        provider_location = volume.get('provider_location')
        target_names = self.targets.keys()
        if provider_location:
            target_name = provider_location.split(',1 ')[1].split(' ')[0]
            if not(self.targets.get(target_name)):
                self.targets[target_name] = []
            if not(volume['name'] in self.targets[target_name]):
                self.targets[target_name].append(volume['name'])
        elif not(target_names):
            # create first target and target group
            target_name = self._create_target(0)
            self.targets[target_name].append(volume['name'])
        else:
            target_name = target_names[0]
            for target in target_names:
                if len(self.targets[target]) < len(self.targets[target_name]):
                    target_name = target
            if len(self.targets[target_name]) >= 20:
                # create new target and target group
                target_name = self._create_target(len(target_names))
            if not(volume['name'] in self.targets[target_name]):
                self.targets[target_name].append(volume['name'])
        return target_name

    def _get_target_group_name(self, target_name):
        """Return Nexenta iSCSI target group name for volume."""
        return target_name.replace(
            self.configuration.nexenta_target_prefix,
            self.configuration.nexenta_target_group_prefix
        )

    @staticmethod
    def _get_clone_snapshot_name(volume):
        """Return name for snapshot that will be used to clone the volume."""
        return 'cinder-clone-snapshot-%(id)s' % volume

    @staticmethod
    def _is_clone_snapshot_name(snapshot):
        """Check if snapshot is created for cloning."""
        name = snapshot.split('@')[-1]
        return name.startswith('cinder-clone-snapshot-')

    def create_volume(self, volume):
        """Create a zvol on appliance.

        :param volume: volume reference
        :return: model update dict for volume reference
        """
        self.nms.zvol.create(
            self._get_zvol_name(volume['name']),
            '%sG' % (volume['size'],),
            six.text_type(self.configuration.nexenta_blocksize),
            self.configuration.nexenta_sparse)

    def extend_volume(self, volume, new_size):
        """Extend an existing volume.

        :param volume: volume reference
        :param new_size: volume new size in GB
        """
        LOG.info('Extending volume: %(id)s New size: %(size)s GB',
                 {'id': volume['id'], 'size': new_size})
        self.nms.zvol.set_child_prop(self._get_zvol_name(volume['name']),
                                     'volsize', '%sG' % new_size)

    def delete_volume(self, volume):
        """Destroy a zvol on appliance.

        :param volume: volume reference
        """
        volume_name = self._get_zvol_name(volume['name'])
        try:
            props = self.nms.zvol.get_child_props(volume_name, 'origin') or {}
            self.nms.zvol.destroy(volume_name, '')
        except utils.NexentaException as exc:
            if 'does not exist' in exc.args[0]:
                LOG.info('Volume %s does not exist, it '
                         'seems it was already deleted.', volume_name)
                return
            if 'zvol has children' in exc.args[0]:
                self._mark_as_garbage(volume_name)
                LOG.info('Volume %s will be deleted later.', volume_name)
                return
            raise
        origin = props.get('origin')
        self._collect_garbage(origin)

    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume.

        :param volume: new volume reference
        :param src_vref: source volume reference
        """
        snapshot = {'volume_name': src_vref['name'],
                    'name': self._get_clone_snapshot_name(volume),
                    'volume_size': src_vref['size']}
        LOG.debug('Creating temp snapshot of the original volume: '
                  '%(volume_name)s@%(name)s', snapshot)
        # We don't delete this snapshot, because this snapshot will be origin
        # of new volume. This snapshot will be automatically promoted by NMS
        # when user will delete origin volume. But when cloned volume deleted
        # we check its origin property and delete source snapshot if needed.
        self.create_snapshot(snapshot)
        try:
            self.create_volume_from_snapshot(volume, snapshot)
            self._mark_as_garbage('@'.join(
                (self._get_zvol_name(src_vref['name']), snapshot['name'])))
        except utils.NexentaException:
            with excutils.save_and_reraise_exception():
                LOG.exception(
                    'Volume creation failed, deleting created snapshot '
                    '%(volume_name)s@%(name)s', snapshot)
            try:
                self.delete_snapshot(snapshot)
            except (utils.NexentaException, exception.SnapshotIsBusy):
                LOG.warning('Failed to delete zfs snapshot '
                            '%(volume_name)s@%(name)s', snapshot)
            raise

    def _get_zfs_send_recv_cmd(self, src, dst):
        """Returns rrmgr command for source and destination."""
        return utils.get_rrmgr_cmd(src, dst,
                                   compression=self.rrmgr_compression,
                                   tcp_buf_size=self.rrmgr_tcp_buf_size,
                                   connections=self.rrmgr_connections)

    @staticmethod
    def get_nms_for_url(url):
        """Returns initialized nms object for url."""
        auto, scheme, user, password, host, port, path = (
            utils.parse_nms_url(url))
        return jsonrpc.NexentaJSONProxy(scheme, host, port, path, user,
                                        password, auto=auto)

    def migrate_volume(self, ctxt, volume, host):
        """Migrate if volume and host are managed by Nexenta appliance.

        :param ctxt: context
        :param volume: a dictionary describing the volume to migrate
        :param host: a dictionary describing the host to migrate to
        """
        LOG.debug('Enter: migrate_volume: id=%(id)s, host=%(host)s',
                  {'id': volume['id'], 'host': host})
        false_ret = (False, None)

        if volume['status'] not in ('available', 'retyping'):
            return false_ret

        if 'capabilities' not in host:
            return false_ret

        capabilities = host['capabilities']

        if ('location_info' not in capabilities or
                'iscsi_target_portal_port' not in capabilities or
                'nms_url' not in capabilities):
            return false_ret

        nms_url = capabilities['nms_url']
        dst_parts = capabilities['location_info'].split(':')

        if (capabilities.get('vendor_name') != 'Nexenta' or
                dst_parts[0] != self.__class__.__name__ or
                capabilities['free_capacity_gb'] < volume['size']):
            return false_ret

        dst_host, dst_volume = dst_parts[1:]

        ssh_bound = False
        ssh_bindings = self.nms.appliance.ssh_list_bindings()
        for bind in ssh_bindings:
            if dst_host.startswith(ssh_bindings[bind][3]):
                ssh_bound = True
                break
        if not ssh_bound:
            LOG.warning("Remote NexentaStor appliance at %s should be "
                        "SSH-bound.", dst_host)

        # Create temporary snapshot of volume on NexentaStor Appliance.
        snapshot = {
            'volume_name': volume['name'],
            'name': utils.get_migrate_snapshot_name(volume)
        }
        self.create_snapshot(snapshot)

        src = '%(volume)s/%(zvol)s@%(snapshot)s' % {
            'volume': self.volume,
            'zvol': volume['name'],
            'snapshot': snapshot['name']
        }
        dst = ':'.join([dst_host, dst_volume])

        try:
            self.nms.appliance.execute(self._get_zfs_send_recv_cmd(src, dst))
        except utils.NexentaException as exc:
            LOG.warning("Cannot send source snapshot %(src)s to "
                        "destination %(dst)s. Reason: %(exc)s",
                        {'src': src, 'dst': dst, 'exc': exc})
            return false_ret
        finally:
            try:
                self.delete_snapshot(snapshot)
            except utils.NexentaException as exc:
                LOG.warning("Cannot delete temporary source snapshot "
                            "%(src)s on NexentaStor Appliance: %(exc)s",
                            {'src': src, 'exc': exc})
        try:
            self.delete_volume(volume)
        except utils.NexentaException as exc:
            LOG.warning("Cannot delete source volume %(volume)s on "
                        "NexentaStor Appliance: %(exc)s",
                        {'volume': volume['name'], 'exc': exc})

        dst_nms = self.get_nms_for_url(nms_url)
        dst_snapshot = '%s/%s@%s' % (dst_volume, volume['name'],
                                     snapshot['name'])
        try:
            dst_nms.snapshot.destroy(dst_snapshot, '')
        except utils.NexentaException as exc:
            LOG.warning("Cannot delete temporary destination snapshot "
                        "%(dst)s on NexentaStor Appliance: %(exc)s",
                        {'dst': dst_snapshot, 'exc': exc})
        return True, None

    def retype(self, context, volume, new_type, diff, host):
        """Convert the volume to be of the new type.

        :param context: Context
        :param volume: A dictionary describing the volume to migrate
        :param new_type: A dictionary describing the volume type to convert to
        :param diff: A dictionary with the difference between the two types
        :param host: A dictionary describing the host to migrate to, where
                     host['host'] is its name, and host['capabilities'] is a
                     dictionary of its reported capabilities.
        """
        LOG.debug('Retype volume request %(vol)s to be %(type)s '
                  '(host: %(host)s), diff %(diff)s.',
                  {'vol': volume['name'],
                   'type': new_type,
                   'host': host,
                   'diff': diff})

        options = dict(
            compression='compression',
            dedup='dedup',
            description='nms:description'
        )

        retyped = False
        migrated = False

        capabilities = host['capabilities']
        src_backend = self.__class__.__name__
        dst_backend = capabilities['location_info'].split(':')[0]
        if src_backend != dst_backend:
            LOG.warning('Cannot retype from %(src_backend)s to '
                        '%(dst_backend)s.',
                        {'src_backend': src_backend,
                         'dst_backend': dst_backend})
            return False

        hosts = (volume['host'], host['host'])
        old, new = hosts
        if old != new:
            migrated, provider_location = self.migrate_volume(
                context, volume, host)

        if not migrated:
            nms = self.nms
        else:
            nms_url = capabilities['nms_url']
            nms = self.get_nms_for_url(nms_url)

        zvol = '%s/%s' % (
            capabilities['location_info'].split(':')[-1], volume['name'])

        for opt in options:
            old, new = diff.get('extra_specs').get(opt, (False, False))
            if old != new:
                LOG.debug('Changing %(opt)s from %(old)s to %(new)s.',
                          {'opt': opt, 'old': old, 'new': new})
                try:
                    nms.zvol.set_child_prop(
                        zvol, options[opt], new)
                    retyped = True
                except utils.NexentaException:
                    LOG.error('Error trying to change %(opt)s'
                              ' from %(old)s to %(new)s',
                              {'opt': opt, 'old': old, 'new': new})
                    return False, None
        return retyped or migrated, None

    def create_snapshot(self, snapshot):
        """Create snapshot of existing zvol on appliance.

        :param snapshot: snapshot reference
        """
        self.nms.zvol.create_snapshot(
            self._get_zvol_name(snapshot['volume_name']),
            snapshot['name'], '')

    def create_volume_from_snapshot(self, volume, snapshot):
        """Create new volume from other's snapshot on appliance.

        :param volume: reference of volume to be created
        :param snapshot: reference of source snapshot
        """
        self.nms.zvol.clone(
            '%s@%s' % (self._get_zvol_name(snapshot['volume_name']),
                       snapshot['name']),
            self._get_zvol_name(volume['name']))
        if (('size' in volume) and (
                volume['size'] > snapshot['volume_size'])):
            self.extend_volume(volume, volume['size'])

    def delete_snapshot(self, snapshot):
        """Delete volume's snapshot on appliance.

        :param snapshot: snapshot reference
        """
        volume_name = self._get_zvol_name(snapshot['volume_name'])
        snapshot_name = '%s@%s' % (volume_name, snapshot['name'])
        try:
            self.nms.snapshot.destroy(snapshot_name, '')
        except utils.NexentaException as exc:
            if "does not exist" in exc.args[0]:
                LOG.info('Snapshot %s does not exist, it seems it was '
                         'already deleted.', snapshot_name)
                return
            elif "snapshot has dependent clones" in exc.args[0]:
                self._mark_as_garbage(snapshot_name)
                LOG.info('Snapshot %s has dependent clones, will be '
                         'deleted later.', snapshot_name)
                return
            raise
        self._collect_garbage(volume_name)

    def local_path(self, volume):
        """Return local path to existing local volume.

        We never have local volumes, so it raises NotImplementedError.

        :raise: :py:exc:`NotImplementedError`
        """
        raise NotImplementedError

    def _target_exists(self, target):
        """Check if iSCSI target exist.

        :param target: target name
        :return: True if target exist, else False
        """
        targets = self.nms.stmf.list_targets()
        if not targets:
            return False
        return (target in self.nms.stmf.list_targets())

    def _target_group_exists(self, target_group):
        """Check if target group exist.

        :param target_group: target group
        :return: True if target group exist, else False
        """
        groups = self.nms.stmf.list_targetgroups()
        if not groups:
            return False
        return target_group in groups

    def _target_member_in_target_group(self, target_group, target_member):
        """Check if target member in target group.

        :param target_group: target group
        :param target_member: target member
        :return: True if target member in target group, else False
        :raises NexentaException: if target group doesn't exist
        """
        members = self.nms.stmf.list_targetgroup_members(target_group)
        if not members:
            return False
        return target_member in members

    def _lu_exists(self, zvol_name):
        """Check if LU exists on appliance.

        :param zvol_name: Zvol name
        :raises NexentaException: if zvol not exists
        :return: True if LU exists, else False
        """
        try:
            return bool(self.nms.scsidisk.lu_exists(zvol_name))
        except utils.NexentaException as exc:
            if 'does not exist' not in exc.args[0]:
                raise
            return False

    def _is_lu_shared(self, zvol_name):
        """Check if LU exists on appliance and shared.

        :param zvol_name: Zvol name
        :raises NexentaException: if Zvol not exist
        :return: True if LU exists and shared, else False
        """
        try:
            shared = self.nms.scsidisk.lu_shared(zvol_name) > 0
        except utils.NexentaException as exc:
            if 'does not exist for zvol' not in exc.args[0]:
                raise  # Zvol does not exists
            shared = False  # LU does not exist
        return shared

    def create_export(self, _ctx, volume, connector):
        """Create new export for zvol.

        :param volume: reference of volume to be exported
        :return: iscsiadm-formatted provider location string
        """
        model_update = self._do_export(_ctx, volume)
        return model_update

    def ensure_export(self, _ctx, volume):
        self._do_export(_ctx, volume)

    def _do_export(self, _ctx, volume):
        """Recreate parts of export if necessary.

        :param volume: reference of volume to be exported
        """
        zvol_name = self._get_zvol_name(volume['name'])
        target_name = self._get_target_name(volume)
        target_group_name = self._get_target_group_name(target_name)

        entry = None
        if not self._lu_exists(zvol_name):
            try:
                entry = self.nms.scsidisk.create_lu(zvol_name, {})
            except utils.NexentaException as exc:
                if 'in use' not in exc.args[0]:
                    raise
                LOG.info('Ignored LU creation error "%s" while ensuring '
                         'export.', exc)
        if not self._is_lu_shared(zvol_name):
            try:
                entry = self.nms.scsidisk.add_lun_mapping_entry(zvol_name, {
                    'target_group': target_group_name})
            except utils.NexentaException as exc:
                if 'view entry exists' not in exc.args[0]:
                    raise
                LOG.info('Ignored LUN mapping entry addition error "%s" '
                         'while ensuring export.', exc)
        model_update = {}
        if entry:
            provider_location = '%(host)s:%(port)s,1 %(name)s %(lun)s' % {
                'host': self.nms_host,
                'port': self.configuration.nexenta_iscsi_target_portal_port,
                'name': target_name,
                'lun': entry['lun'],
            }
            model_update = {'provider_location': provider_location}
        return model_update

    def remove_export(self, _ctx, volume):
        """Destroy all resources created to export zvol.

        :param volume: reference of volume to be unexported
        """
        target_name = self._get_target_name(volume)
        self.targets[target_name].remove(volume['name'])
        zvol_name = self._get_zvol_name(volume['name'])
        self.nms.scsidisk.delete_lu(zvol_name)

    def _update_volume_stats(self):
        """Retrieve stats info for NexentaStor appliance."""
        LOG.debug('Updating volume stats')

        stats = self.nms.volume.get_child_props(
            self.configuration.nexenta_volume, 'health|size|used|available')

        total_amount = utils.str2gib_size(stats['size'])
        free_amount = utils.str2gib_size(stats['available'])

        location_info = '%(driver)s:%(host)s:%(volume)s' % {
            'driver': self.__class__.__name__,
            'host': self.nms_host,
            'volume': self.volume
        }
        self._stats = {
            'vendor_name': 'Nexenta',
            'dedup': self.volume_deduplication,
            'compression': self.volume_compression,
            'description': self.volume_description,
            'driver_version': self.VERSION,
            'storage_protocol': 'iSCSI',
            'total_capacity_gb': total_amount,
            'free_capacity_gb': free_amount,
            'reserved_percentage': self.configuration.reserved_percentage,
            'QoS_support': False,
            'volume_backend_name': self.backend_name,
            'location_info': location_info,
            'iscsi_target_portal_port': self.iscsi_target_portal_port,
            'nms_url': self.nms.url
        }

    def _collect_garbage(self, zfs_object):
        """Destroys ZFS parent objects

        Recursively destroys ZFS parent volumes and snapshots if they are
        marked as garbage

        :param zfs_object: full path to a volume or a snapshot
        """
        if zfs_object and zfs_object in self._needless_objects:
            sp = zfs_object.split('/')
            path = '/'.join(sp[:-1])
            name = sp[-1]
            if '@' in name:  # it's a snapshot:
                volume, snap = name.split('@')
                parent = '/'.join((path, volume))
                try:
                    self.nms.snapshot.destroy(zfs_object, '')
                except utils.NexentaException as exc:
                    LOG.debug('Error occurred while trying to delete a '
                              'snapshot: %s', exc)
                    return
            else:
                try:
                    props = self.nms.zvol.get_child_props(
                        zfs_object, 'origin') or {}
                except utils.NexentaException:
                    props = {}
                parent = (props['origin'] if 'origin' in props and
                                             props['origin'] else '')
                try:
                    self.nms.zvol.destroy(zfs_object, '')
                except utils.NexentaException as exc:
                    LOG.debug('Error occurred while trying to delete a '
                              'volume: %s', exc)
                    return
            self._needless_objects.remove(zfs_object)
            self._collect_garbage(parent)

    def _mark_as_garbage(self, zfs_object):
        """Puts ZFS object into list for further removal

        :param zfs_object: full path to a volume or a snapshot
        """
        self._needless_objects.add(zfs_object)
