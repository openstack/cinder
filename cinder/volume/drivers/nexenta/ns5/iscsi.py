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
.. moduleauthor:: Alexey Khodos <alexey.khodos@nexenta.com>
"""

from oslo_log import log as logging
from oslo_utils import units

from cinder import context, db
from cinder import exception
from cinder.i18n import _, _LE, _LI, _LW
from cinder.volume import driver
from cinder.volume.drivers import nexenta
from cinder.volume.drivers.nexenta.ns5 import jsonrpc
from cinder.volume.drivers.nexenta import options
from cinder.volume.drivers.nexenta import utils

VERSION = '1.0.0'
LOG = logging.getLogger(__name__)


class NexentaISCSIDriver(driver.ISCSIDriver):  # pylint: disable=R0921
    """Executes volume driver commands on Nexenta Appliance.

    Version history:
        1.0.0 - Initial driver version.
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
        self.nef_protocol = self.configuration.nexenta_rest_protocol
        self.nef_host = self.configuration.nexenta_host
        self.nef_port = self.configuration.nexenta_rest_port
        self.nef_user = self.configuration.nexenta_user
        self.nef_password = self.configuration.nexenta_password
        self.volume = self.configuration.nexenta_volume
        self.volume_compression = self.configuration.nexenta_volume_compression
        self.volume_deduplication = self.configuration.nexenta_volume_dedup
        self.volume_description = self.configuration.nexenta_volume_description
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
        if self.nef_protocol == 'auto':
            protocol, auto = 'http', True
        else:
            protocol, auto = self.nef_protocol, False
        self.nef = jsonrpc.NexentaJSONProxy(
            protocol, self.nef_host, self.nef_port, self.nef_user,
            self.nef_password, auto=auto)
        pool, dataset = self.volume.split('/')
        url = 'storage/pools/%s/datasetGroups' % pool
        data = {
            'name': dataset,
            'defaultVolumeBlockSize': self.configuration.nexenta_blocksize
        }
        try:
            self.nef(url, data)
        except:
            pass
        url = 'services/iscsit'
        data = {'enabled': True}
        self.nef(url, data, method='PUT')

    def check_for_setup_error(self):
        """Verify that the volume for our zvols exists.

        :raise: :py:exc:`LookupError`
        """
        pool, dataset = self.volume.split('/')
        url = 'storage/pools/%s/datasetGroups/%s' % (pool, dataset)
        try:
            self.nef(url)
        except jsonrpc.NexentaJSONException:
            raise LookupError(_("Volume %s does not exist in Nexenta SA"),
                              self.volume)
        services = self.nef('services')
        for service in services['data']:
            if service['id'] == 'iscsit':
                if service['status'] == 'disabled':
                    raise nexenta.NexentaException(
                        'iSCSI service is not running on NS appliance')
                break

    def _get_zvol_name(self, volume_name):
        """Return zvol name that corresponds given volume name."""
        return '%s/%s' % (self.volume, volume_name)

    def _get_target_name(self, volume_name):
        """Return iSCSI target name to access volume."""
        url = 'san/iscsi/targets?alias=%s' % volume_name
        return self.nef(url)['data'][0]['name']

    def _get_target_group_name(self, volume_name):
        """Return Nexenta iSCSI target group name for volume."""
        return 'cinder_%s' % volume_name

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
        pool, dataset = self.volume.split('/')
        url = 'storage/pools/%s/datasetGroups/%s/volumes' % (
            pool, dataset)
        data = {
                'name': volume['name'],
                'volumeSize': volume['size'] * units.Gi,
                'volumeBlockSize': 512,
                'volumeBlockSize': self.configuration.nexenta_ns5_blocksize,
                'sparseVolume': self.configuration.nexenta_sparse
            }
        self.nef(url, data)
        return self.create_export(None, volume)

    def delete_volume(self, volume):
        """Destroy a zvol on appliance.

        :param volume: volume reference
        """
        volume_name = self._get_zvol_name(volume['name'])
        pool, group, name = volume_name.split('/')
        url = ('storage/pools/%s/datasetGroups/%s'
               '/volumes/%s?snapshots=true') % (
               pool, group, name)
        try:
            self.nef(url, method='DELETE')
        except nexenta.NexentaException as exc:
            # We assume that volume is gone
            LOG.warn(_LW('Got error trying to delete volume %(volume)s,'
                         ' assuming it is already gone: %(exc)s'),
                     {'volume': volume, 'exc': exc})

    # def extend_volume(self, volume, new_size):
    #     """Extend an existing volume.

    #     :param volume: volume reference
    #     :param new_size: volume new size in GB
    #     """
    #     LOG.info(_LI('Extending volume: %(id)s New size: %(size)s GB'),
    #              {'id': volume['id'], 'size': new_size})
    #     self.nms.zvol.set_child_prop(self._get_zvol_name(volume['name']),
    #                                  'volsize', '%sG' % new_size)

    def create_snapshot(self, snapshot):
        """Creates a snapshot.

        :param snapshot: snapshot reference
        """
        volume = self._get_snapshot_volume(snapshot)
        volume_name = self._get_zvol_name(volume['name'])
        pool, group, volume = volume_name.split('/')
        url = 'storage/pools/%(pool)s/datasetGroups/%(group)s/' \
              'volumes/%(volume)s/snapshots' % {
                  'pool': pool,
                  'group': group,
                  'volume': volume
              }
        data = {'name': snapshot['name']}
        self.nef(url, data)

    def delete_snapshot(self, snapshot):
        """Delete volume's snapshot on appliance.

        :param snapshot: snapshot reference
        """
        volume = self._get_snapshot_volume(snapshot)
        volume_name = self._get_zvol_name(volume['name'])
        pool, group, volume = volume_name.split('/')
        url = ('storage/pools/%(pool)s/datasetGroups/%(group)s/'
               'volumes/%(volume)s/snapshots/%(snapshot)s') % {
                  'pool': pool,
                  'group': group,
                  'volume': volume,
                  'snapshot': snapshot['name']
              }
        self.nef(url, method='DELETE')

    def _get_snapshot_volume(self, snapshot):
        ctxt = context.get_admin_context()
        return db.volume_get(ctxt, snapshot['volume_id'])

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
            LOG.error(_LE('Volume creation failed, deleting created snapshot '
                          '%(volume_name)s@%(name)s'), snapshot)
            try:
                self.delete_snapshot(snapshot)
            except (nexenta.NexentaException, exception.SnapshotIsBusy):
                LOG.warning(_LW('Failed to delete zfs snapshot '
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

        if volume['status'] not in ('available', 'retyping'):
            return false_ret

        if 'capabilities' not in host:
            return false_ret

        capabilities = host['capabilities']

        if 'location_info' not in capabilities or \
                'iscsi_target_portal_port' not in capabilities or \
                'nms_url' not in capabilities:
            return false_ret

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
            if dst_host.startswith(ssh_bindings[bind][3]):
                ssh_bound = True
                break
        if not ssh_bound:
            LOG.warning(_LW("Remote NexentaStor appliance at %s should be "
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
            LOG.warning(_LW("Cannot send source snapshot %(src)s to "
                            "destination %(dst)s. Reason: %(exc)s"),
                        {'src': src, 'dst': dst, 'exc': exc})
            return false_ret
        finally:
            try:
                self.delete_snapshot(snapshot)
            except nexenta.NexentaException as exc:
                LOG.warning(_LW("Cannot delete temporary source snapshot "
                                "%(src)s on NexentaStor Appliance: %(exc)s"),
                            {'src': src, 'exc': exc})
        try:
            self.delete_volume(volume)
        except nexenta.NexentaException as exc:
            LOG.warning(_LW("Cannot delete source volume %(volume)s on "
                            "NexentaStor Appliance: %(exc)s"),
                        {'volume': volume['name'], 'exc': exc})

        dst_nms = self.get_nms_for_url(nms_url)
        dst_snapshot = '%s/%s@%s' % (dst_volume, volume['name'],
                                     snapshot['name'])
        try:
            dst_nms.snapshot.destroy(dst_snapshot, '')
        except nexenta.NexentaException as exc:
            LOG.warning(_LW("Cannot delete temporary destination snapshot "
                            "%(dst)s on NexentaStor Appliance: %(exc)s"),
                        {'dst': dst_snapshot, 'exc': exc})
        return True, None

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

    def _get_lun(self, volume_name, host=None):
        """Get lu mapping number for Zvol.

        :param zvol_name: Zvol name
        :raises: LookupError if Zvol not exist or not mapped to LU
        :return: LUN
        """
        zvol_name = self._get_zvol_name(volume_name)
        target_group_name = self._get_target_group_name(volume_name)
        url = 'san/targetgroups/%s/luns?volume=%s' % (
            target_group_name, zvol_name.replace('/', '%2F'))
        if not self.nef(url)['data']:
            raise LookupError(_("LU does not exist for ZVol: %s"), zvol_name)
        else:
            return self.nef(url)['data'][0]['viewCount']

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
        LOG.warning('%(host)s:%(port)s,1 %(name)s' % {
            'host': self.nef_host,
            'port': self.configuration.nexenta_iscsi_target_portal_port,
            'name': self._get_target_name(volume['name']),
            'lun': self._get_lun(volume['name'])
        })
        return '%(host)s:%(port)s,1 %(name)s' % {
            'host': self.nef_host,
            'port': self.configuration.nexenta_iscsi_target_portal_port,
            'name': self._get_target_name(volume['name']),
            'lun': self._get_lun(volume['name'])
        }

    def _do_export(self, _ctx, volume, ensure=False):
        """Do all steps to get zvol exported at separate target.

        :param volume: reference of volume to be exported
        :param ensure: if True, ignore errors caused by already existing
            resources
        """
        zvol_name = self._get_zvol_name(volume['name'])
        target_group_name = self._get_target_group_name(volume['name'])

        url = 'san/iscsi/targets'
        data = {'alias': volume['name']}
        self.nef(url, data)
        target_name = self._get_target_name(volume['name'])

        url = 'san/targetgroups'
        data = {'name': target_group_name,
                'targets': [target_name]}
        self.nef(url, data)

        url = 'san/targetgroups/%s/luns' % target_group_name
        data = {'volume': zvol_name}
        self.nef(url, data)

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
        volume_name = self._get_zvol_name(volume['name'])
        pool, group, name = volume_name.split('/')
        target = self._get_target_name(volume['name'])
        try:
            url = 'san/iscsi/targets/%s' % target
            self.nef(url, method='DELETE')
        except nexenta.NexentaException as exc:
            # We assume that target is gone as well
            LOG.warn(_LW('Got error trying to delete target %(target)s,'
                         ' assuming it is already gone: %(exc)s'),
                     {'target': target, 'exc': exc})

        tg_name = self._get_target_group_name(volume['name'])
        try:
            url = 'san/targetgroups/%s' % (tg_name)
            self.nef(url, method='DELETE')
        except nexenta.NexentaException as exc:
            # We assume that target group is already gone
            LOG.warn(_LW('Got error trying to destroy target group'
                         ' %(target_group)s, assuming it is '
                         'already gone: %(exc)s'),
                     {'target_group': tg_name, 'exc': exc})

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

        pool, dataset = self.volume.split('/')
        url = 'storage/pools/%s/datasetGroups/%s' % (
            pool, dataset)
        stats = self.nef(url)
        total_amount = utils.str2gib_size(
            stats['bytesAvailable'] + stats['bytesUsed'])
        free_amount = utils.str2gib_size(stats['bytesAvailable'])

        location_info = '%(driver)s:%(host)s:%(volume)s' % {
            'driver': self.__class__.__name__,
            'host': self.nef_host,
            'volume': self.volume
        }
        reserve = 100 - self.configuration.nexenta_capacitycheck
        self._stats = {
            'vendor_name': 'Nexenta',
            'dedup': self.volume_deduplication,
            'compression': self.volume_compression,
            'description': self.volume_description,
            'driver_version': self.VERSION,
            'storage_protocol': 'iSCSI',
            'total_capacity_gb': total_amount,
            'free_capacity_gb': free_amount,
            'reserved_percentage': reserve,
            'QoS_support': False,
            'volume_backend_name': self.backend_name,
            'location_info': location_info,
            'iscsi_target_portal_port': self.iscsi_target_portal_port,
            'nef_url': self.nef.url
        }
