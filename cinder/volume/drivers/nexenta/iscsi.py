# Copyright 2011 Nexenta Systems, Inc.
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
"""
:mod:`nexenta.iscsi` -- Driver to store volumes on Nexenta Appliance
=====================================================================

.. automodule:: nexenta.volume
.. moduleauthor:: Victor Rodionov <victor.rodionov@nexenta.com>
.. moduleauthor:: Mikhail Khodos <mikhail.khodos@nexenta.com>
.. moduleauthor:: Yuriy Taraday <yorik.sar@gmail.com>
"""

from cinder import exception
from cinder.i18n import _
from cinder.openstack.common import log as logging
from cinder.volume import driver
from cinder.volume.drivers import nexenta
from cinder.volume.drivers.nexenta import jsonrpc
from cinder.volume.drivers.nexenta import options
from cinder.volume.drivers.nexenta import utils

VERSION = '1.2.1'
LOG = logging.getLogger(__name__)


class NexentaISCSIDriver(driver.ISCSIDriver):  # pylint: disable=R0921
    """Executes volume driver commands on Nexenta Appliance.

    Version history:
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
    """

    VERSION = VERSION

    def __init__(self, *args, **kwargs):
        super(NexentaISCSIDriver, self).__init__(*args, **kwargs)
        self.nms = None
        if self.configuration:
            self.configuration.append_config_values(
                options.NEXENTA_CONNECTION_OPTIONS)
            self.configuration.append_config_values(
                options.NEXENTA_ISCSI_OPTIONS)
            self.configuration.append_config_values(
                options.NEXENTA_VOLUME_OPTIONS)
            self.configuration.append_config_values(
                options.NEXENTA_RRMGR_OPTIONS)
        self.nms_protocol = self.configuration.nexenta_rest_protocol
        self.nms_host = self.configuration.nexenta_host
        self.nms_port = self.configuration.nexenta_rest_port
        self.nms_user = self.configuration.nexenta_user
        self.nms_password = self.configuration.nexenta_password
        self.volume = self.configuration.nexenta_volume
        self.rrmgr_compression = self.configuration.nexenta_rrmgr_compression
        self.rrmgr_tcp_buf_size = self.configuration.nexenta_rrmgr_tcp_buf_size
        self.rrmgr_connections = self.configuration.nexenta_rrmgr_connections
        self.iscsi_target_portal_port = \
            self.configuration.nexenta_iscsi_target_portal_port

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
            raise LookupError(_("Volume %s does not exist in Nexenta SA"),
                              self.volume)

    def _get_zvol_name(self, volume_name):
        """Return zvol name that corresponds given volume name."""
        return '%s/%s' % (self.volume, volume_name)

    def _get_target_name(self, volume_name):
        """Return iSCSI target name to access volume."""
        return '%s%s' % (self.configuration.nexenta_target_prefix, volume_name)

    def _get_target_group_name(self, volume_name):
        """Return Nexenta iSCSI target group name for volume."""
        return '%s%s' % (self.configuration.nexenta_target_group_prefix,
                         volume_name)

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
            self.configuration.nexenta_blocksize,
            self.configuration.nexenta_sparse)
        return self.create_export(None, volume)

    def extend_volume(self, volume, new_size):
        """Extend an existing volume.

        :param volume: volume reference
        :param new_size: volume new size in GB
        """
        LOG.info(_('Extending volume: %(id)s New size: %(size)s GB'),
                 {'id': volume['id'], 'size': new_size})
        self.nms.zvol.set_child_prop(self._get_zvol_name(volume['name']),
                                     'volsize', '%sG' % new_size)

    def delete_volume(self, volume):
        """Destroy a zvol on appliance.

        :param volume: volume reference
        """
        volume_name = self._get_zvol_name(volume['name'])
        props = self.nms.zvol.get_child_props(volume_name, 'origin') or {}
        try:
            self.nms.zvol.destroy(volume_name, '')
        except nexenta.NexentaException as exc:
            if 'does not exist' in exc.args[0]:
                LOG.info(_('Volume %s does not exist, it seems it was already '
                           'deleted.'), volume_name)
                return
            if 'zvol has children' in exc.args[0]:
                raise exception.VolumeIsBusy(volume_name=volume_name)
            raise
        origin = props.get('origin')
        if origin and self._is_clone_snapshot_name(origin):
            volume, snapshot = origin.split('@')
            volume = volume.lstrip('%s/' % self.configuration.nexenta_volume)
            try:
                self.delete_snapshot({'volume_name': volume, 'name': snapshot})
            except nexenta.NexentaException as exc:
                LOG.warning(_('Cannot delete snapshot %(origin)s: %(exc)s'),
                            {'origin': origin, 'exc': exc})

    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume.

        :param volume: new volume reference
        :param src_vref: source volume reference
        """
        snapshot = {'volume_name': src_vref['name'],
                    'name': self._get_clone_snapshot_name(volume)}
        LOG.debug('Creating temp snapshot of the original volume: '
                  '%(volume_name)s@%(name)s', snapshot)
        # We don't delete this snapshot, because this snapshot will be origin
        # of new volume. This snapshot will be automatically promoted by NMS
        # when user will delete origin volume. But when cloned volume deleted
        # we check its origin property and delete source snapshot if needed.
        self.create_snapshot(snapshot)
        try:
            self.create_volume_from_snapshot(volume, snapshot)
        except nexenta.NexentaException:
            LOG.error(_('Volume creation failed, deleting created snapshot '
                        '%(volume_name)s@%(name)s'), snapshot)
            try:
                self.delete_snapshot(snapshot)
            except (nexenta.NexentaException, exception.SnapshotIsBusy):
                LOG.warning(_('Failed to delete zfs snapshot '
                              '%(volume_name)s@%(name)s'), snapshot)
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
        auto, scheme, user, password, host, port, path =\
            utils.parse_nms_url(url)
        return jsonrpc.NexentaJSONProxy(scheme, host, port, path, user,
                                        password, auto=auto)

    def migrate_volume(self, ctxt, volume, host):
        """Migrate if volume and host are managed by Nexenta appliance.

        :param ctxt: context
        :param volume: a dictionary describing the volume to migrate
        :param host: a dictionary describing the host to migrate to
        """
        LOG.debug('Enter: migrate_volume: id=%(id)s, host=%(host)s' %
                  {'id': volume['id'], 'host': host})

        false_ret = (False, None)

        if volume['status'] != 'available':
            return false_ret

        if 'capabilities' not in host:
            return false_ret

        capabilities = host['capabilities']

        if 'location_info' not in capabilities or \
                'iscsi_target_portal_port' not in capabilities or \
                'nms_url' not in capabilities:
            return false_ret

        iscsi_target_portal_port = capabilities['iscsi_target_portal_port']
        nms_url = capabilities['nms_url']
        dst_parts = capabilities['location_info'].split(':')

        if capabilities.get('vendor_name') != 'Nexenta' or \
                dst_parts[0] != self.__class__.__name__ or \
                capabilities['free_capacity_gb'] < volume['size']:
            return false_ret

        dst_host, dst_volume = dst_parts[1:]

        ssh_bound = False
        ssh_bindings = self.nms.appliance.ssh_list_bindings()
        for bind in ssh_bindings:
            if bind.index(dst_host) != -1:
                ssh_bound = True
                break
        if not ssh_bound:
            LOG.warning(_("Remote NexentaStor appliance at %s should be "
                          "SSH-bound."), dst_host)

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
        except nexenta.NexentaException as exc:
            LOG.warning(_("Cannot send source snapshot %(src)s to "
                          "destination %(dst)s. Reason: %(exc)s"),
                        {'src': src, 'dst': dst, 'exc': exc})
            return false_ret
        finally:
            try:
                self.delete_snapshot(snapshot)
            except nexenta.NexentaException as exc:
                LOG.warning(_("Cannot delete temporary source snapshot "
                              "%(src)s on NexentaStor Appliance: %(exc)s"),
                            {'src': src, 'exc': exc})
        try:
            self.delete_volume(volume)
        except nexenta.NexentaException as exc:
            LOG.warning(_("Cannot delete source volume %(volume)s on "
                          "NexentaStor Appliance: %(exc)s"),
                        {'volume': volume['name'], 'exc': exc})

        dst_nms = self.get_nms_for_url(nms_url)
        dst_snapshot = '%s/%s@%s' % (dst_volume, volume['name'],
                                     snapshot['name'])
        try:
            dst_nms.snapshot.destroy(dst_snapshot, '')
        except nexenta.NexentaException as exc:
            LOG.warning(_("Cannot delete temporary destination snapshot "
                          "%(dst)s on NexentaStor Appliance: %(exc)s"),
                        {'dst': dst_snapshot, 'exc': exc})

        provider_location = '%(host)s:%(port)s,1 %(name)s 0' % {
            'host': dst_host,
            'port': iscsi_target_portal_port,
            'name': self._get_target_name(volume['name'])
        }

        return True, {'provider_location': provider_location}

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

    def delete_snapshot(self, snapshot):
        """Delete volume's snapshot on appliance.

        :param snapshot: snapshot reference
        """
        volume_name = self._get_zvol_name(snapshot['volume_name'])
        snapshot_name = '%s@%s' % (volume_name, snapshot['name'])
        try:
            self.nms.snapshot.destroy(snapshot_name, '')
        except nexenta.NexentaException as exc:
            if "does not exist" in exc.args[0]:
                LOG.info(_('Snapshot %s does not exist, it seems it was '
                           'already deleted.'), snapshot_name)
                return
            if "snapshot has dependent clones" in exc.args[0]:
                raise exception.SnapshotIsBusy(snapshot_name=snapshot['name'])
            raise

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
        return target in self.nms.stmf.list_targets()

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
        :raises: NexentaException if target group doesn't exist
        """
        members = self.nms.stmf.list_targetgroup_members(target_group)
        if not members:
            return False
        return target_member in members

    def _lu_exists(self, zvol_name):
        """Check if LU exists on appliance.

        :param zvol_name: Zvol name
        :raises: NexentaException if zvol not exists
        :return: True if LU exists, else False
        """
        try:
            return bool(self.nms.scsidisk.lu_exists(zvol_name))
        except nexenta.NexentaException as exc:
            if 'does not exist' not in exc.args[0]:
                raise
            return False

    def _is_lu_shared(self, zvol_name):
        """Check if LU exists on appliance and shared.

        :param zvol_name: Zvol name
        :raises: NexentaException if Zvol not exist
        :return: True if LU exists and shared, else False
        """
        try:
            shared = self.nms.scsidisk.lu_shared(zvol_name) > 0
        except nexenta.NexentaException as exc:
            if 'does not exist for zvol' not in exc.args[0]:
                raise  # Zvol does not exists
            shared = False  # LU does not exist
        return shared

    def _is_volume_exported(self, volume):
        """Check if volume exported.

        :param volume: volume object
        :return: True if volume exported, else False
        """
        zvol_name = self._get_zvol_name(volume['name'])
        target_name = self._get_target_name(volume['name'])
        target_group_name = self._get_target_group_name(volume['name'])
        return (self._target_exists(target_name) and
                self._target_group_exists(target_group_name) and
                self._target_member_in_target_group(target_group_name,
                                                    target_name) and
                self._lu_exists(zvol_name) and
                self._is_lu_shared(zvol_name))

    def _get_provider_location(self, volume):
        """Returns volume iscsiadm-formatted provider location string."""
        return '%(host)s:%(port)s,1 %(name)s 0' % {
            'host': self.nms_host,
            'port': self.configuration.nexenta_iscsi_target_portal_port,
            'name': self._get_target_name(volume['name'])
        }

    def _do_export(self, _ctx, volume, ensure=False):
        """Do all steps to get zvol exported as LUN 0 at separate target.

        :param volume: reference of volume to be exported
        :param ensure: if True, ignore errors caused by already existing
            resources
        """
        zvol_name = self._get_zvol_name(volume['name'])
        target_name = self._get_target_name(volume['name'])
        target_group_name = self._get_target_group_name(volume['name'])

        if not self._target_exists(target_name):
            try:
                self.nms.iscsitarget.create_target({
                    'target_name': target_name})
            except nexenta.NexentaException as exc:
                if ensure and 'already configured' in exc.args[0]:
                    LOG.info(_('Ignored target creation error "%s" while '
                               'ensuring export'), exc)
                else:
                    raise
        if not self._target_group_exists(target_group_name):
            try:
                self.nms.stmf.create_targetgroup(target_group_name)
            except nexenta.NexentaException as exc:
                if ((ensure and 'already exists' in exc.args[0]) or
                        'target must be offline' in exc.args[0]):
                    LOG.info(_('Ignored target group creation error "%s" '
                               'while ensuring export'), exc)
                else:
                    raise
        if not self._target_member_in_target_group(target_group_name,
                                                   target_name):
            try:
                self.nms.stmf.add_targetgroup_member(target_group_name,
                                                     target_name)
            except nexenta.NexentaException as exc:
                if ((ensure and 'already exists' in exc.args[0]) or
                        'target must be offline' in exc.args[0]):
                    LOG.info(_('Ignored target group member addition error '
                               '"%s" while ensuring export'), exc)
                else:
                    raise
        if not self._lu_exists(zvol_name):
            try:
                self.nms.scsidisk.create_lu(zvol_name, {})
            except nexenta.NexentaException as exc:
                if not ensure or 'in use' not in exc.args[0]:
                    raise
                LOG.info(_('Ignored LU creation error "%s" while ensuring '
                           'export'), exc)
        if not self._is_lu_shared(zvol_name):
            try:
                self.nms.scsidisk.add_lun_mapping_entry(zvol_name, {
                    'target_group': target_group_name,
                    'lun': '0'})
            except nexenta.NexentaException as exc:
                if not ensure or 'view entry exists' not in exc.args[0]:
                    raise
                LOG.info(_('Ignored LUN mapping entry addition error "%s" '
                           'while ensuring export'), exc)

    def create_export(self, _ctx, volume):
        """Create new export for zvol.

        :param volume: reference of volume to be exported
        :return: iscsiadm-formatted provider location string
        """
        self._do_export(_ctx, volume, ensure=False)
        return {'provider_location': self._get_provider_location(volume)}

    def ensure_export(self, _ctx, volume):
        """Recreate parts of export if necessary.

        :param volume: reference of volume to be exported
        """
        self._do_export(_ctx, volume, ensure=True)

    def remove_export(self, _ctx, volume):
        """Destroy all resources created to export zvol.

        :param volume: reference of volume to be unexported
        """
        zvol_name = self._get_zvol_name(volume['name'])
        target_name = self._get_target_name(volume['name'])
        target_group_name = self._get_target_group_name(volume['name'])
        self.nms.scsidisk.delete_lu(zvol_name)

        try:
            self.nms.stmf.destroy_targetgroup(target_group_name)
        except nexenta.NexentaException as exc:
            # We assume that target group is already gone
            LOG.warn(_('Got error trying to destroy target group'
                       ' %(target_group)s, assuming it is '
                       'already gone: %(exc)s'),
                     {'target_group': target_group_name, 'exc': exc})
        try:
            self.nms.iscsitarget.delete_target(target_name)
        except nexenta.NexentaException as exc:
            # We assume that target is gone as well
            LOG.warn(_('Got error trying to delete target %(target)s,'
                       ' assuming it is already gone: %(exc)s'),
                     {'target': target_name, 'exc': exc})

    def get_volume_stats(self, refresh=False):
        """Get volume stats.

        If 'refresh' is True, run update the stats first.
        """
        if refresh:
            self._update_volume_stats()

        return self._stats

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
            'driver_version': self.VERSION,
            'storage_protocol': 'iSCSI',
            'total_capacity_gb': total_amount,
            'free_capacity_gb': free_amount,
            'reserved_percentage': 0,
            'QoS_support': False,
            'volume_backend_name': self.backend_name,
            'location_info': location_info,
            'iscsi_target_portal_port': self.iscsi_target_portal_port,
            'nms_url': self.nms.url
        }
