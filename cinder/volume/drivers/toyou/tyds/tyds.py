# Copyright 2023 toyou Corp.
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
Cinder driver for Toyou distributed storage.
"""

import re
import time

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import units

from cinder.common import constants
from cinder import coordination
from cinder import exception
from cinder.i18n import _
from cinder import interface
from cinder import utils as cinder_utils
from cinder.volume import configuration
from cinder.volume import driver
from cinder.volume.drivers.san import san
from cinder.volume.drivers.toyou.tyds import tyds_client
from cinder.volume import volume_utils

LOG = logging.getLogger(__name__)
tyds_opts = [
    cfg.ListOpt('tyds_pools',
                default=['pool01'],
                help='The pool name where volumes are stored.'),
    cfg.PortOpt('tyds_http_port',
                default=80,
                help='The port that connects to the http api.'),
    cfg.StrOpt('tyds_stripe_size',
               default='4M',
               help='Volume stripe size.'),
    cfg.IntOpt('tyds_clone_progress_interval',
               default=3,
               help='Interval (in seconds) for retrieving clone progress.'),
    cfg.IntOpt('tyds_copy_progress_interval',
               default=3,
               help='Interval (in seconds) for retrieving copy progress.')
]
CONF = cfg.CONF
CONF.register_opts(tyds_opts, group=configuration.SHARED_CONF_GROUP)


class TYDSDriverException(exception.VolumeDriverException):
    message = _("TYDS Cinder toyou failure: %(reason)s")


CREATE_VOLUME_SUCCESS = ('[Success] Cinder: Create Block Device, '
                         'Block Name: %s, Size in MB: %s, Pool Name: %s, '
                         'Stripe Size: %s.')
CREATE_VOLUME_FAILED = ('[Failed] Cinder: Create Block Device, '
                        'Block Name: %s, Size in MB: %s, Pool Name: %s, '
                        'Stripe Size: %s.')
DELETE_VOLUME_SUCCESS = ('[Success] Cinder: Delete Block Device, Block Name: '
                         '%s.')
DELETE_VOLUME_FAILED = ('[Failed] Cinder: delete failed, the volume: %s '
                        'has normal_snaps: %s, please delete '
                        'normal_snaps first.')
ATTACH_VOLUME_SUCCESS = ('[Success] Cinder: Attach Block Device, Block Name: '
                         '%s, IP Address: %s, Host: %s.')
DETACH_VOLUME_SUCCESS = ('[Success] Cinder: Detach Block Device, Block Name: '
                         '%s, IP Address: %s, Host: %s.')
EXTEND_VOLUME_SUCCESS = ('[Success] Cinder: Extend volume: %s from %sMB to '
                         '%sMB.')
CREATE_SNAPSHOT_SUCCESS = '[Success] Cinder: Create snapshot: %s, volume: %s.'
DELETE_SNAPSHOT_SUCCESS = '[Success] Cinder: Delete snapshot: %s, volume: %s.'
CREATE_VOLUME_FROM_SNAPSHOT_SUCCESS = ('[Success] Cinder: Create volume: %s, '
                                       'pool name: %s; from snapshot: %s '
                                       'source volume: %s, source pool name: '
                                       '%s.')
CREATE_VOLUME_FROM_SNAPSHOT_DONE = ('[Success] Cinder: Create volume: %s '
                                    'done, pool name: %s; from snapshot:'
                                    ' %s source volume: %s, source pool '
                                    'name: %s.')
COPY_VOLUME_DONE = ('[Success] Cinder: Copy volume done, '
                    'pool_name: %s; block_name: %s '
                    'target_pool_name: %s, target_block_name: %s.')
COPY_VOLUME_FAILED = ('[Failed] Cinder: Copy volume failed, '
                      'pool_name: %s; block_name: %s '
                      'target_pool_name: %s, target_block_name: %s.')


@interface.volumedriver
class TYDSDriver(driver.MigrateVD, driver.BaseVD):
    """TOYOU distributed storage abstract common class.

    .. code-block:: none

      Version history:
          1.0.0 - Initial TOYOU NetStor TYDS Driver

    """
    VENDOR = 'TOYOU'
    VERSION = '1.0.0'
    CI_WIKI_NAME = 'TOYOU_TYDS_CI'

    def __init__(self, *args, **kwargs):
        super(TYDSDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(tyds_opts)
        self.configuration.append_config_values(san.san_opts)
        self.ip = self.configuration.san_ip
        self.port = self.configuration.tyds_http_port
        self.username = self.configuration.san_login
        self.password = self.configuration.san_password
        self.pools = self.configuration.tyds_pools
        self.client = None
        self.storage_protocol = constants.ISCSI

    @staticmethod
    def get_driver_options():
        additional_opts = driver.BaseVD._get_oslo_driver_opts(
            'san_ip', 'san_login', 'san_password'
        )
        return tyds_opts + additional_opts

    def do_setup(self, context):
        LOG.debug("Start setup Tyds client")
        self.client = tyds_client.TydsClient(self.ip,
                                             self.port,
                                             self.username,
                                             self.password)
        LOG.info("Initialized Tyds Driver Client.")

    def check_for_setup_error(self):
        required = [
            'san_ip',
            'san_login',
            'san_password',
            'tyds_pools'
        ]
        missing_params = [param for param in required if
                          not self.configuration.safe_get(param)]
        if missing_params:
            missing_params_str = ', '.join(missing_params)
            msg = _("The following parameters are not set: %s" %
                    missing_params_str)
            raise exception.InvalidInput(
                reason=msg)

    def _update_volume_stats(self):
        """Update the backend stats including TOYOU info and pools info."""
        backend_name = self.configuration.safe_get('volume_backend_name')

        self._stats = {
            'vendor_name': self.VENDOR,
            'driver_version': self.VERSION,
            'volume_backend_name': backend_name,
            'pools': self._get_pools_stats(),
            'storage_protocol': self.storage_protocol,
        }

        LOG.debug('Update volume stats: %s.', self._stats)

    def _get_pools_stats(self):
        """Get pools statistics."""
        pools_data = self.client.get_pools()
        volumes_list = self.client.get_volumes()
        pools_stats = []

        for pool_name in self.pools:
            pool_info = next(
                (data for data in pools_data if data['name'] == pool_name),
                None
            )
            if pool_info:
                max_avail = int(pool_info['stats']['max_avail'])
                stored = int(pool_info['stats']['stored'])
                free_capacity = self._convert_gb(max_avail - stored, "B")
                total_capacity = self._convert_gb(max_avail, "B")

                allocated_capacity = 0
                total_volumes = 0
                for vol in volumes_list:
                    if vol['poolName'] == pool_name:
                        allocated_capacity += self._convert_gb(
                            int(vol['sizeMB']), "MB")
                        total_volumes += 1

                pools_stats.append({
                    'pool_name': pool_name,
                    'total_capacity_gb': total_capacity,
                    'free_capacity_gb': free_capacity,
                    'provisioned_capacity_gb': allocated_capacity,
                    'thin_provisioning_support': True,
                    'QoS_support': False,
                    'consistencygroup_support': False,
                    'total_volumes': total_volumes,
                    'multiattach': False
                })
            else:
                raise TYDSDriverException(
                    reason=_(
                        'Backend storage pool "%s" not found.') % pool_name
                )

        return pools_stats

    def _get_volume_by_name(self, volume_name):
        """Get volume information by name."""
        volume_list = self.client.get_volumes()

        for vol in volume_list:
            if vol.get('blockName') == volume_name:
                return vol
        # Returns an empty dictionary indicating that the volume with the
        # corresponding name was not found
        return {}

    def _get_snapshot_by_name(self, snapshot_name, volume_id=None):
        """Get snapshot information by name and optional volume ID."""
        snapshot_list = self.client.get_snapshot(volume_id)

        for snap in snapshot_list:
            if snap.get('snapShotName') == snapshot_name:
                return snap
        # Returns an empty dictionary indicating that a snapshot with the
        # corresponding name was not found
        return {}

    @staticmethod
    def _convert_gb(size, unit):
        """Convert size from the given unit to GB."""
        size_gb = 0
        if unit in ['B', '']:
            size_gb = size / units.Gi
        elif unit in ['M', 'MB']:
            size_gb = size / units.Ki
        return float('%.0f' % size_gb)

    def _clone_volume(self, pool_name, block_name, block_id, target_pool_name,
                      target_pool_id, target_block_name):
        self.client.create_clone_volume(
            pool_name,
            block_name,
            block_id,
            target_pool_name,
            target_pool_id,
            target_block_name
        )

        @coordination.synchronized('tyds-copy-{lun_name}-progress')
        def _wait_copy_progress(lun_id, lun_name, target_block):
            try:
                ret = False
                while_exit = False
                rescan = 0
                interval = self.configuration.tyds_copy_progress_interval
                while True:
                    rescan += 1
                    progress_data = self.client.get_copy_progress(
                        lun_id, lun_name, target_block)
                    progress = progress_data.get('progress')
                    # finished clone
                    if progress == '100%':
                        # check new volume existence
                        target = self._get_volume_by_name(target_block)
                        if not target:
                            LOG.info(
                                'Clone rescan: %(rescan)s, target volume '
                                'completed delayed, from %(block_name)s to '
                                '%(target_block_name)s.',
                                {'rescan': rescan, 'block_name': lun_name,
                                 'target_block_name': target_block})
                            time.sleep(interval)
                            continue
                        LOG.info(
                            'Clone rescan: %(rescan)s, task done from '
                            '%(block_name)s to %(target_block_name)s.',
                            {'rescan': rescan, 'block_name': lun_name,
                             'target_block_name': target_block})
                        while_exit = True
                        ret = True
                    elif progress:
                        LOG.info(
                            "Clone rescan: %(rescan)s, progress: %(progress)s,"
                            " block_name: %(block_name)s, target_block_name: "
                            "%(target_block_name)s",
                            {"rescan": rescan, "progress": progress,
                             "block_name": lun_name,
                             "target_block_name": target_block})
                    else:
                        LOG.error(
                            'Copy: rescan: %(rescan)s, task error from '
                            '%(block_name)s to %(target_block_name)s.',
                            {'rescan': rescan, 'block_name': lun_name,
                             'target_block_name': target_block_name})
                        while_exit = True
                    if while_exit:
                        break
                    time.sleep(interval)
                return ret
            except Exception as err:
                LOG.error('Copy volume failed reason: %s', err)
                return False

        if _wait_copy_progress(block_id, block_name, target_block_name):
            LOG.debug(COPY_VOLUME_DONE, pool_name,
                      block_name, target_pool_name, target_block_name)
        else:
            self._delete_volume_if_clone_failed(target_block_name, pool_name,
                                                block_name, target_block_name)
            msg = _("copy volume failed from %s to %s") % (
                block_name, target_block_name)
            raise TYDSDriverException(reason=msg)

    def _delete_volume_if_clone_failed(self, target_block_name, pool_name,
                                       block_name, target_pool_name):
        target_volume = self._get_volume_by_name(target_block_name)

        if target_volume:
            self.client.delete_volume(target_volume.get('id'))

        LOG.debug(COPY_VOLUME_FAILED, pool_name, block_name,
                  target_pool_name, target_block_name)

    def create_export(self, context, volume, connector):
        pass

    def create_volume(self, volume):
        LOG.info("Creating volume '%s'", volume.name)
        vol_name = cinder_utils.convert_str(volume.name)
        size = int(volume.size) * 1024
        pool_name = volume_utils.extract_host(volume.host, 'pool')
        stripe_size = self.configuration.tyds_stripe_size
        self.client.create_volume(vol_name, size, pool_name, stripe_size)

        LOG.debug(CREATE_VOLUME_SUCCESS, vol_name, size, pool_name,
                  stripe_size)

    def retype(self, context, volume, new_type, diff, host):
        # success
        return True, None

    def delete_volume(self, volume):
        LOG.debug("deleting volume '%s'", volume.name)
        vol_name = cinder_utils.convert_str(volume.name)
        vol = self._get_volume_by_name(vol_name)
        if vol and vol.get('id'):
            self.client.delete_volume(vol.get('id'))
            LOG.debug(DELETE_VOLUME_SUCCESS, vol_name)
        else:
            LOG.info('Delete volume %s not found.', vol_name)

    def ensure_export(self, context, volume):
        pass

    def remove_export(self, context, volume):
        pass

    def initialize_connection(self, volume, connector):
        LOG.debug('initialize_connection: volume %(vol)s with connector '
                  '%(conn)s', {'vol': volume.name, 'conn': connector})
        pool_name = volume_utils.extract_host(volume.host, 'pool')
        volume_name = cinder_utils.convert_str(volume.name)
        group_name = "initiator-group-" + cinder_utils.convert_str(
            connector['uuid'])
        vol_info = {"name": volume_name, "size": volume.size,
                    "pool": pool_name}

        # Check initiator existence
        initiator_list = self.client.get_initiator_list()
        initiator_existence = False
        if initiator_list:
            initiator_existence = any(
                initiator['group_name'] == group_name for initiator in
                initiator_list
            )
        if not initiator_existence:
            # Create initiator
            client = [{"ip": connector["ip"], "iqn": connector["initiator"]}]
            self.client.create_initiator_group(group_name=group_name,
                                               client=client)
        # Check Initiator-Target connection existence
        # add new volume to existing Initiator-Target connection
        it_list = self.client.get_initiator_target_connections()
        it_info = None
        if it_list:
            it_info = next((it for it in it_list if group_name in
                            it['target_name']), None)
        if it_info:
            target_iqn = it_info['target_iqn']
            lun_info = next((lun for lun in it_info['block'] if
                             lun['name'] == volume_name), None)

            if not lun_info:
                # Add new volume to existing Initiator-Target connection
                target_name_list = it_info['hostName']
                vols_info = it_info['block']
                vols_info.append(vol_info)
                self.client.modify_target(target_iqn, target_name_list,
                                          vols_info)
        else:
            # Create new Initiator-Target connection
            target_node_list = self.client.get_target()
            target_name_list = [target['name'] for target in target_node_list]
            self.client.create_target(group_name, target_name_list, [vol_info])

        it_list = self.client.get_initiator_target_connections()
        if it_list:
            it_info = next(
                (it for it in it_list if group_name in it['target_name']),
                None)
        if it_info:
            target_name = it_info['target_name']
            target_iqn = it_info['target_iqn']
            lun_info = next((lun for lun in it_info['block'] if lun['name']
                             == volume_name), None)
            lun_id = lun_info['lunid'] if lun_info else 0

            # Generate config
            self.client.generate_config(target_iqn)

            # Generate return info
            target_node_list = self.client.get_target()
            target_node = target_node_list[0]
            target_ip = target_node['ipAddr']
            target_portal = '[%s]:3260' % target_ip if ':' in target_ip \
                else '%s:3260' % target_ip
            target_iqns = [target_name] * len(target_node_list)
            target_portals = ['[%s]:3260' % p['ipAddr'] if ':' in p['ipAddr']
                              else '%s:3260' % p['ipAddr']
                              for p in target_node_list]
            target_luns = [lun_id] * len(target_node_list)

            properties = {
                'target_discovered': False,
                'target_portal': target_portal,
                'target_lun': lun_id,
                'target_iqns': target_iqns,
                'target_portals': target_portals,
                'target_luns': target_luns
            }

            LOG.debug('connection properties: %s', properties)
            LOG.debug(ATTACH_VOLUME_SUCCESS, volume_name,
                      connector.get('ip'), connector.get('host'))

            return {'driver_volume_type': 'iscsi', 'data': properties}
        else:
            raise exception.VolumeBackendAPIException(
                data=_('initialize_connection: Failed to create IT '
                       'connection for volume %s') % volume_name)

    def terminate_connection(self, volume, connector, **kwargs):
        if not connector:
            # If the connector is empty, the info log is recorded and
            # returned directly, without subsequent separation operations
            LOG.info(
                "Connector is None. Skipping termination for volume %s.",
                volume.name)
            return
        volume_name = cinder_utils.convert_str(volume.name)
        group_name = "initiator-group-" + cinder_utils.convert_str(
            connector['uuid'])
        data = {}
        # Check Initiator-Target connection existence and remove volume from
        # Initiator-Target connection if it exists
        it_list = self.client.get_initiator_target_connections()
        it_info = next((it for it in it_list if group_name in
                        it['target_name']), None)
        if it_info:
            target_iqn = it_info['target_iqn']
            target_name_list = it_info['hostName']
            vols_info = it_info['block']
            vols_info = [vol for vol in vols_info if
                         vol['name'] != volume_name]
            if not vols_info:
                self.client.delete_target(it_info['target_iqn'])
                initiator_list = self.client.get_initiator_list()
                initiator_to_delete = None
                if initiator_list:
                    initiator_to_delete = next(
                        (initiator for initiator in initiator_list if
                         initiator['group_name'] == group_name), None)
                if initiator_to_delete:
                    self.client.delete_initiator_group(
                        initiator_to_delete['group_id'])
                self.client.restart_service(host_name=it_info['hostName'])
            else:
                self.client.modify_target(target_iqn, target_name_list,
                                          vols_info)
        # record log
        LOG.debug(DETACH_VOLUME_SUCCESS, volume_name, connector.get(
            'ip'), connector.get('host'))
        LOG.info('Detach volume %s successfully', volume_name)
        target_node_list = self.client.get_target()
        target_portals = ['%s:3260' % p['ipAddr']
                          for p in target_node_list]
        data['ports'] = target_portals
        return {'driver_volume_type': 'iscsi', 'data': data}

    def migrate_volume(self):
        pass

    def extend_volume(self, volume, new_size):
        volume_name = cinder_utils.convert_str(volume.name)
        pool_name = volume_utils.extract_host(volume.host, 'pool')
        size_mb = int(new_size) * 1024
        self.client.extend_volume(volume_name, pool_name, size_mb)
        LOG.debug(EXTEND_VOLUME_SUCCESS, volume_name, volume.size *
                  1024, size_mb)

    def create_cloned_volume(self, volume, src_vref):
        """Clone a volume."""
        # find pool_id to create clone volume
        try:
            target_pool_name = volume_utils.extract_host(volume.host, 'pool')
        except Exception as err:
            msg = _('target_pool_name must be specified. '
                    'extra err msg was: %s') % err
            raise TYDSDriverException(reason=msg)
        target_pool_id = None
        pool_list = self.client.get_pools()
        for pool in pool_list:
            if target_pool_name == pool.get('name'):
                target_pool_id = pool.get('id')
                break
        if not target_pool_id:
            msg = _('target_pool_id: must be specified.')
            raise TYDSDriverException(reason=msg)
        # find volume id to create
        volume_list = self.client.get_volumes()
        block_name = cinder_utils.convert_str(src_vref.name)
        pool_name = None
        block_id = None
        for vol in volume_list:
            if block_name == vol.get('blockName'):
                pool_name = vol.get('poolName')
                block_id = vol.get('id')
                break
        if (not pool_name) or (not block_id):
            msg = _('block_name: %(block_name)s does not matched a '
                    'pool_name or a block_id.') % {'block_name': block_name}
            raise TYDSDriverException(reason=msg)
        # get a name from new volume
        target_block_name = cinder_utils.convert_str(volume.name)
        # ready to create clone volume
        self._clone_volume(pool_name, block_name, block_id, target_pool_name,
                           target_pool_id, target_block_name)
        # handle the case where the new volume size is larger than the source
        if volume['size'] > src_vref.get('size'):
            size_mb = int(volume['size']) * 1024
            self.client.extend_volume(target_block_name, target_pool_name,
                                      size_mb)
            LOG.debug(EXTEND_VOLUME_SUCCESS, target_block_name,
                      src_vref.get('size') * 1024, size_mb)

    def create_snapshot(self, snapshot):
        """Creates a snapshot."""
        volume_name = cinder_utils.convert_str(snapshot.volume_name)
        snapshot_name = cinder_utils.convert_str(snapshot.name)
        vol = self._get_volume_by_name(volume_name)
        if vol and vol.get('id'):
            comment = '%s/%s' % (volume_name, snapshot_name)
            self.client.create_snapshot(snapshot_name, vol.get('id'), comment)
            LOG.debug(CREATE_SNAPSHOT_SUCCESS, snapshot_name,
                      volume_name)
        else:
            msg = _('Volume "%s" not found.') % volume_name
            raise TYDSDriverException(reason=msg)

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        snapshot_name = cinder_utils.convert_str(snapshot.name)
        volume_name = cinder_utils.convert_str(snapshot.volume_name)
        snap = self._get_snapshot_by_name(snapshot_name)
        if snap and snap.get('id'):
            self.client.delete_snapshot(snap.get('id'))
            LOG.debug(DELETE_SNAPSHOT_SUCCESS, snapshot_name,
                      volume_name)
        else:
            LOG.info('Delete snapshot %s not found.', snapshot_name)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""
        snapshot_name = cinder_utils.convert_str(snapshot.name)
        volume_name = cinder_utils.convert_str(volume.name)
        pool_name = volume_utils.extract_host(volume.host, 'pool')
        source_volume = cinder_utils.convert_str(snapshot.volume_name)
        src_vol = self._get_volume_by_name(source_volume)
        if not src_vol:
            msg = _('Volume "%s" not found in '
                    'create_volume_from_snapshot.') % volume_name
            raise TYDSDriverException(reason=msg)

        self.client.create_volume_from_snapshot(volume_name, pool_name,
                                                snapshot_name, source_volume,
                                                src_vol.get('poolName'))
        LOG.debug(CREATE_VOLUME_FROM_SNAPSHOT_SUCCESS, volume_name,
                  pool_name, snapshot_name, source_volume,
                  src_vol.get('poolName'))

        @coordination.synchronized('tyds-clone-{source_name}-progress')
        def _wait_clone_progress(task_id, source_name, target_name):
            ret = False
            while_exit = False
            rescan = 0
            interval = self.configuration.tyds_clone_progress_interval
            while True:
                rescan += 1
                progress = self.client.get_clone_progress(
                    task_id, source_name).get('progress', '')
                if progress == '100%':
                    target = self._get_volume_by_name(target_name)
                    if not target:
                        LOG.info('Clone: rescan: %(rescan)s, task not begin, '
                                 'from %(source)s to %(target)s.',
                                 {'rescan': rescan,
                                  'source': source_name,
                                  'target': target_name})
                        time.sleep(interval)
                        continue
                    LOG.info('Clone: rescan: %(rescan)s, task done from '
                             '%(source)s to %(target)s.',
                             {'rescan': rescan,
                              'source': source_name,
                              'target': target_name})
                    while_exit = True
                    ret = True
                elif re.fullmatch(r'^\d{1,2}%$', progress):
                    LOG.info('Clone: rescan: %(rescan)s, task progress: '
                             '%(progress)s, from %(source)s to %(target)s.',
                             {'rescan': rescan,
                              'progress': progress,
                              'source': source_name,
                              'target': target_name})
                else:
                    while_exit = True
                    LOG.error('Clone: rescan: %(rescan)s, task error from '
                              '%(source)s to %(target)s.',
                              {'rescan': rescan,
                               'source': source_name,
                               'target': target_name})
                if while_exit:
                    break
                time.sleep(interval)
            return ret

        if _wait_clone_progress(src_vol.get('id'), source_volume, volume_name):
            LOG.debug(CREATE_VOLUME_FROM_SNAPSHOT_DONE,
                      volume_name, pool_name, snapshot_name, source_volume,
                      src_vol.get('poolName'))
        # handle the case where the new volume size is larger than the source
        new_size = volume.size * 1024
        old_size = int(src_vol['sizeMB'])
        if new_size > old_size:
            self.client.extend_volume(volume_name, pool_name, new_size)
            LOG.debug(EXTEND_VOLUME_SUCCESS, volume_name, old_size,
                      new_size)
