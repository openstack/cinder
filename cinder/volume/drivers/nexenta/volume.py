# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
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
:mod:`nexenta.volume` -- Driver to store volumes on Nexenta Appliance
=====================================================================

.. automodule:: nexenta.volume
.. moduleauthor:: Victor Rodionov <victor.rodionov@nexenta.com>
.. moduleauthor:: Mikhail Khodos <mikhail.khodos@nexenta.com>
.. moduleauthor:: Yuriy Taraday <yorik.sar@gmail.com>
"""

from oslo.config import cfg

from cinder import exception
from cinder.openstack.common import log as logging
from cinder import units
from cinder.volume import driver
from cinder.volume.drivers import nexenta
from cinder.volume.drivers.nexenta import jsonrpc
from cinder.volume.drivers.nexenta import options

LOG = logging.getLogger(__name__)

CONF = cfg.CONF
CONF.register_opts(options.NEXENTA_CONNECTION_OPTIONS)
CONF.register_opts(options.NEXENTA_ISCSI_OPTIONS)
CONF.register_opts(options.NEXENTA_VOLUME_OPTIONS)


class NexentaDriver(driver.ISCSIDriver):  # pylint: disable=R0921
    """Executes volume driver commands on Nexenta Appliance."""

    VERSION = '1.0.0'

    def __init__(self, *args, **kwargs):
        super(NexentaDriver, self).__init__(*args, **kwargs)
        self.nms = None
        if self.configuration:
            self.configuration.append_config_values(
                options.NEXENTA_CONNECTION_OPTIONS)
            self.configuration.append_config_values(
                options.NEXENTA_ISCSI_OPTIONS)
            self.configuration.append_config_values(
                options.NEXENTA_VOLUME_OPTIONS)

    def do_setup(self, context):
        protocol = self.configuration.nexenta_rest_protocol
        auto = protocol == 'auto'
        if auto:
            protocol = 'http'
        url = '%s://%s:%s/rest/nms/' % (protocol,
                                        self.configuration.nexenta_host,
                                        self.configuration.nexenta_rest_port)
        self.nms = jsonrpc.NexentaJSONProxy(
            url, self.configuration.nexenta_user,
            self.configuration.nexenta_password, auto=auto)

    def check_for_setup_error(self):
        """Verify that the volume for our zvols exists.

        :raise: :py:exc:`LookupError`
        """
        if not self.nms.volume.object_exists(
                self.configuration.nexenta_volume):
            raise LookupError(_("Volume %s does not exist in Nexenta SA"),
                              self.configuration.nexenta_volume)

    def _get_zvol_name(self, volume_name):
        """Return zvol name that corresponds given volume name."""
        return '%s/%s' % (self.configuration.nexenta_volume, volume_name)

    def _get_target_name(self, volume_name):
        """Return iSCSI target name to access volume."""
        return '%s%s' % (self.configuration.nexenta_target_prefix, volume_name)

    def _get_target_group_name(self, volume_name):
        """Return Nexenta iSCSI target group name for volume."""
        return '%s%s' % (self.configuration.nexenta_target_group_prefix,
                         volume_name)

    def _get_clone_snap_name(self, volume):
        """Return name for snapshot that will be used to clone the volume."""
        return 'cinder-clone-snap-%(id)s' % volume

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
        try:
            self.nms.zvol.destroy(self._get_zvol_name(volume['name']), '')
        except nexenta.NexentaException as exc:
            if "does not exist" in exc.args[0]:
                LOG.info(_('Volume %s does not exist, it seems it was already '
                           'deleted'), volume['name'])
                return
            if "zvol has children" in exc.args[0]:
                raise exception.VolumeIsBusy(volume_name=volume['name'])
            raise

    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume.

        :param volume: new volume reference
        :param src_vref: source volume reference
        """
        snapshot = {'volume_name': src_vref['name'],
                    'name': self._get_clone_snap_name(volume)}
        LOG.debug(_('Creating temp snapshot of the original volume: '
                    '%(volume_name)s@%(name)s'), snapshot)
        self.create_snapshot(snapshot)
        try:
            cmd = 'zfs send %(src_vol)s@%(src_snap)s | zfs recv %(volume)s' % {
                'src_vol': self._get_zvol_name(src_vref['name']),
                'src_snap': snapshot['name'],
                'volume': self._get_zvol_name(volume['name'])
            }
            LOG.debug(_('Executing zfs send/recv on the appliance'))
            self.nms.appliance.execute(cmd)
            LOG.debug(_('zfs send/recv done, new volume %s created'),
                      volume['name'])
        finally:
            try:
                # deleting temp snapshot of the original volume
                self.delete_snapshot(snapshot)
            except (nexenta.NexentaException, exception.SnapshotIsBusy):
                LOG.warning(_('Failed to delete temp snapshot '
                              '%(volume)s@%(snapshot)s'),
                            {'volume': src_vref['name'],
                             'snapshot': snapshot['name']})
        try:
            # deleting snapshot resulting from zfs recv
            self.delete_snapshot({'volume_name': volume['name'],
                                  'name': snapshot['name']})
        except (nexenta.NexentaException, exception.SnapshotIsBusy):
            LOG.warning(_('Failed to delete zfs recv snapshot '
                          '%(volume)s@%(snapshot)s'),
                        {'volume': volume['name'],
                         'snapshot': snapshot['name']})

    def create_snapshot(self, snapshot):
        """Create snapshot of existing zvol on appliance.

        :param snapshot: shapshot reference
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
        try:
            self.nms.snapshot.destroy(
                '%s@%s' % (self._get_zvol_name(snapshot['volume_name']),
                           snapshot['name']),
                '')
        except nexenta.NexentaException as exc:
            if "snapshot has dependent clones" in exc.args[0]:
                raise exception.SnapshotIsBusy(snapshot_name=snapshot['name'])
            else:
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
        return bool(self.nms.scsidisk.lu_exists(zvol_name))

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
            'host': self.configuration.nexenta_host,
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
        """Retrieve stats info for Nexenta device."""

        # NOTE(jdg): Aimon Bustardo was kind enough to point out the
        # info he had regarding Nexenta Capabilities, ideally it would
        # be great if somebody from Nexenta looked this over at some point

        LOG.debug(_("Updating volume stats"))
        data = {}
        backend_name = self.__class__.__name__
        if self.configuration:
            backend_name = self.configuration.safe_get('volume_backend_name')
        data["volume_backend_name"] = backend_name or self.__class__.__name__
        data["vendor_name"] = 'Nexenta'
        data["driver_version"] = self.VERSION
        data["storage_protocol"] = 'iSCSI'

        stats = self.nms.volume.get_child_props(
            self.configuration.nexenta_volume, 'health|size|used|available')
        total_unit = stats['size'][-1]
        total_amount = float(stats['size'][:-1])
        free_unit = stats['available'][-1]
        free_amount = float(stats['available'][:-1])

        if total_unit == "T":
            total_amount *= units.KiB
        elif total_unit == "M":
            total_amount /= units.KiB
        elif total_unit == "B":
            total_amount /= units.MiB

        if free_unit == "T":
            free_amount *= units.KiB
        elif free_unit == "M":
            free_amount /= units.KiB
        elif free_unit == "B":
            free_amount /= units.MiB

        data['total_capacity_gb'] = total_amount
        data['free_capacity_gb'] = free_amount

        data['reserved_percentage'] = 0
        data['QoS_support'] = False
        self._stats = data
