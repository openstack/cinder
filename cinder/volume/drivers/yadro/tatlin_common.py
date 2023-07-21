#  Copyright (C) 2021-2022 YADRO.
#  All rights reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"); you may
#  not use this file except in compliance with the License. You may obtain
#  a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#  WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#  License for the specific language governing permissions and limitations
#  under the License.

import os
import time

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import units

from cinder import context as cinder_context
from cinder import exception
from cinder.i18n import _
from cinder import objects
from cinder import utils
from cinder.volume import configuration
from cinder.volume import driver
from cinder.volume.drivers.san import san
from cinder.volume.drivers.yadro.tatlin_client import InitTatlinClient
from cinder.volume.drivers.yadro.tatlin_exception import TatlinAPIException
from cinder.volume.drivers.yadro.tatlin_utils import TatlinVolumeConnections
from cinder.volume import qos_specs
from cinder.volume import volume_types
from cinder.volume import volume_utils
from cinder.volume.volume_utils import brick_get_connector_properties
from cinder.zonemanager import utils as fczm_utils


LOG = logging.getLogger(__name__)

tatlin_opts = [
    cfg.StrOpt('pool_name',
               default='',
               help='storage pool name'),
    cfg.PortOpt('api_port',
                default=443,
                help='Port to use to access the Tatlin API'),
    cfg.StrOpt('export_ports',
               default='',
               help='Ports to export Tatlin resource through'),
    cfg.StrOpt('host_group',
               default='',
               help='Tatlin host group name'),
    cfg.IntOpt('max_resource_count',
               default=500,
               help='Max resource count allowed for Tatlin'),
    cfg.IntOpt('pool_max_resource_count',
               default=250,
               help='Max resource count allowed for single pool'),
    cfg.IntOpt('tat_api_retry_count',
               default=10,
               help='Number of retry on Tatlin API'),
    cfg.StrOpt('auth_method',
               default='CHAP',
               help='Authentication method for iSCSI (CHAP)'),
    cfg.StrOpt('lba_format',
               default='512e',
               help='LBA Format for new volume'),
    cfg.IntOpt('wait_retry_count',
               default=15,
               help='Number of checks for a lengthy operation to finish'),
    cfg.IntOpt('wait_interval',
               default=30,
               help='Wait number of seconds before re-checking'),
]

CONF = cfg.CONF
CONF.register_opts(tatlin_opts, group=configuration.SHARED_CONF_GROUP)


class TatlinCommonVolumeDriver(driver.VolumeDriver, object):

    def __init__(self, *args, **kwargs):
        super(TatlinCommonVolumeDriver, self).__init__(*args, **kwargs)
        self._ip = None
        self._port = 443
        self._user = None
        self._password = None
        self._pool_name = None
        self._pool_id = None
        self.configuration.append_config_values(san.san_opts)
        self.configuration.append_config_values(tatlin_opts)
        self._auth_method = 'CHAP'
        self._chap_username = ''
        self._chap_password = ''
        self.backend_name = None
        self.DRIVER_VOLUME_TYPE = None
        self._export_ports = None
        self._host_group = None
        self.verify = None
        self.DEFAULT_FILTER_FUNCTION = None
        self.DEFAULT_GOODNESS_FUNCTION = None
        self._use_multipath = True
        self._enforce_multipath = False
        self._lba_format = '512e'
        self._ssl_cert_path = None
        self._max_pool_resource_count = 250

    def do_setup(self, context):
        """Initial driver setup"""
        required_config = ['san_ip',
                           'san_login',
                           'san_password',
                           'pool_name',
                           'host_group']
        for attr in required_config:
            if not getattr(self.configuration, attr, None):
                message = (_('config option %s is not set.') % attr)
                raise exception.InvalidInput(message=message)

        self._ip = self.configuration.san_ip
        self._user = self.configuration.san_login
        self._password = self.configuration.san_password
        self._port = self.configuration.api_port
        self._pool_name = self.configuration.pool_name
        self._export_ports = self.configuration.export_ports
        self._host_group = self.configuration.host_group
        self._auth_method = self.configuration.auth_method
        self._chap_username = self.configuration.chap_username
        self._chap_password = self.configuration.chap_password
        self._wait_interval = self.configuration.wait_interval
        self._wait_retry_count = self.configuration.wait_retry_count

        self._ssl_cert_path = (self.configuration.
                               safe_get('driver_ssl_cert_path') or None)

        self.verify = (self.configuration.
                       safe_get('driver_ssl_cert_verify') or False)

        if self.verify and self._ssl_cert_path:
            self.verify = self._ssl_cert_path

        LOG.info('Tatlin driver version: %s', self.VERSION)

        self.tatlin_api = self._get_tatlin_client()
        self.ctx = context
        self.MAX_ALLOWED_RESOURCES = self.configuration.max_resource_count
        self._max_pool_resource_count = \
            self.configuration.pool_max_resource_count
        self.DEFAULT_FILTER_FUNCTION = \
            'capabilities.pool_resource_count < ' +\
            str(self._max_pool_resource_count) +\
            ' and capabilities.overall_resource_count < ' +\
            str(self.MAX_ALLOWED_RESOURCES)
        self.DEFAULT_GOODNESS_FUNCTION = '100 - capabilities.utilization'
        self._use_multipath = \
            (self.configuration.safe_get(
                'use_multipath_for_image_xfer') or False)
        self._enforce_multipath = \
            (self.configuration.safe_get(
                'enforce_multipath_for_image_xfer') or False)
        self._lba_format = self.configuration.lba_format
        self._wait_interval = self.configuration.wait_interval
        self._wait_retry_count = self.configuration.wait_retry_count
        self._connections = TatlinVolumeConnections(
            os.path.join(CONF.state_path,
                         'tatlin-volume-connections'))

    def check_for_setup_error(self):
        pass

    @volume_utils.trace
    def create_volume(self, volume):
        """Entry point for create new volume"""

        if not self.pool_id:
            raise exception.VolumeBackendAPIException(
                message='Wrong Tatlin pool configuration')

        pool_res_count, cluster_res_count = \
            self.tatlin_api.get_resource_count(self.pool_id)
        LOG.debug('Current pool %(pool)s has %(pool_res)s res.'
                  'Whole cluster has %(cluster_res)s',
                  {'pool': self.pool_id,
                   'pool_res': pool_res_count,
                   'cluster_res': cluster_res_count})

        self._stats['pool_resource_count'] = pool_res_count
        self._stats['overall_resource_count'] = cluster_res_count

        if pool_res_count > 255:
            message = _('TatlinVolumeDriver create volume failed. '
                        'Too many resources per pool created')
            LOG.error(message)
            raise exception.VolumeBackendAPIException(message=message)

        if cluster_res_count + 1 > self.MAX_ALLOWED_RESOURCES:
            message = _('TatlinVolumeDriver create volume failed. '
                        'Too many resources per cluster created')
            LOG.error(message)
            raise exception.VolumeBackendAPIException(message=message)

        LOG.debug('Create volume %(vol_id)s started',
                  {'vol_id': volume.name_id})
        self._create_volume_storage(volume)
        LOG.debug('Create volume %s finished', volume.name_id)

    def _create_volume_storage(self, volume):
        """Create a volume with a specific name in Tatlin"""
        size = volume.size * units.Gi
        vol_type = 'snapshot' if 'snapshot_volume' in volume.metadata \
            else 'volume'
        name = 'cinder-%s-%s' % (vol_type, volume.name_id)
        LOG.debug('Creating Tatlin resource %(name)s '
                  'with %(size)s size in pool %(pool)s',
                  {'name': name, 'size': size, 'pool': self.pool_id})
        self.tatlin_api.create_volume(volume.name_id,
                                      name,
                                      size,
                                      self.pool_id,
                                      lbaFormat=self._lba_format)

        self.wait_volume_ready(volume)

        self._update_qos(volume)

    def wait_volume_ready(self, volume):
        for counter in range(self._wait_retry_count):
            if self.tatlin_api.is_volume_ready(volume.name_id):
                return
            LOG.warning('Volume %s is not ready', volume.name_id)
            time.sleep(self._wait_interval)
        message = _('Volume %s still not ready') % volume.name_id
        LOG.error(message)
        raise exception.VolumeBackendAPIException(message=message)

    def wait_volume_online(self, volume):
        for counter in range(self._wait_retry_count):
            if self.tatlin_api.get_volume_status(volume.name_id) == 'online':
                return
            LOG.warning('Volume %s still not online', volume.name_id)
            time.sleep(self._wait_interval)
        message = _('Volume %s unable to become online' % volume.name_id)
        raise exception.VolumeBackendAPIException(message=message)

    @volume_utils.trace
    def delete_volume(self, volume):
        """Entry point for delete volume"""
        LOG.debug('Delete volume started for %s', volume.name_id)
        if not self.tatlin_api.is_volume_exists(volume.name_id):
            LOG.debug('Volume %s does not exist', volume.name_id)
            return
        try:
            self.tatlin_api.delete_volume(volume.name_id)
        except TatlinAPIException as e:
            message = _('Unable to delete volume %s due to %s' %
                        (volume.name_id, e))
            raise exception.VolumeBackendAPIException(message=message)

        for counter in range(self._wait_retry_count):
            if not self.tatlin_api.is_volume_exists(volume.name_id):
                LOG.debug('Delete volume finished for %s', volume.name_id)
                return
            LOG.debug('Volume %s still exists, waiting for delete...',
                      volume.name_id)
            time.sleep(self._wait_interval)

        if self.tatlin_api.is_volume_exists(volume.name_id):
            message = _('Unable to delete volume %s' % volume.name_id)
            LOG.error(message)
            raise exception.VolumeBackendAPIException(message=message)

    @volume_utils.trace
    def extend_volume(self, volume, new_size):
        size = new_size * units.Gi
        LOG.debug('Extending volume %s to %s', volume.name_id, size)
        self.tatlin_api.extend_volume(volume.name_id, size)
        self.wait_volume_ready(volume)
        self._update_qos(volume)

    @volume_utils.trace
    def create_cloned_volume(self, volume, src_vol):
        """Entry point for clone existing volume"""
        LOG.debug('Create cloned volume %(target)s from %(source)s started',
                  {'target': volume.name_id, 'source': src_vol.name_id})
        self.create_volume(volume)
        self._clone_volume_data(volume, src_vol)
        LOG.debug('Create cloned volume %(target)s from %(source)s finished',
                  {'target': volume.name_id, 'source': src_vol.name_id})

    def _clone_volume_data(self, volume, src_vol):
        props = brick_get_connector_properties(
            self._use_multipath,
            self._enforce_multipath)

        LOG.debug('Volume %s Connection properties %s',
                  volume.name_id, props)
        dest_attach_info = None
        src_attach_info = None

        size_in_mb = int(src_vol['size']) * units.Ki

        try:
            src_attach_info, volume_src = self._attach_volume(
                self.ctx, src_vol, props)
            LOG.debug('Source attach info: %s volume: %s',
                      src_attach_info, volume_src)

        except Exception as e:
            LOG.error('Unable to attach src volume due to %s', e)
            raise

        try:
            dest_attach_info, volume_dest = self._attach_volume(
                self.ctx, volume, props)
            LOG.debug('Dst attach info: %s volume: %s',
                      dest_attach_info, volume_dest)

        except Exception as e:
            LOG.error('Unable to attach dst volume due to %s', e)
            self._detach_volume(self.ctx, src_attach_info, src_vol, props)
            raise

        try:
            LOG.debug('Begin copy to %s from %s',
                      volume.name_id, src_vol.name_id)
            volume_utils.copy_volume(src_attach_info['device']['path'],
                                     dest_attach_info['device']['path'],
                                     size_in_mb,
                                     self.configuration.volume_dd_blocksize,
                                     sparse=False)
            LOG.debug('End copy to %s from %s',
                      volume.name_id, src_vol.name_id)
        except Exception as e:
            LOG.error('Unable to clone volume source: %s dst: %s due to %s',
                      src_vol.name_id, volume.name_id, e)
            raise
        finally:
            try:
                self._detach_volume(self.ctx, src_attach_info, src_vol, props)
            finally:
                self._detach_volume(self.ctx, dest_attach_info, volume, props)

    @volume_utils.trace
    def _attach_volume(self, context, volume, properties, remote=False):
        @utils.synchronized('tatlin-volume-attachments-%s' % volume.name_id)
        def _do_attach_volume():
            LOG.debug('Start Tatlin attach volume %s properties %s',
                      volume.name_id, properties)
            return super(driver.VolumeDriver, self)._attach_volume(
                context, volume, properties, remote=remote)
        return _do_attach_volume()

    @volume_utils.trace
    def _detach_volume(self, context, attach_info, volume, properties,
                       force=False, remote=False, ignore_errors=False):
        @utils.synchronized('tatlin-volume-attachments-%s' % volume.name_id)
        def _do_detach_volume():
            LOG.debug('Start Tatlin detach for %s', volume.name_id)
            connection_count = self._connections.get(volume.name_id)
            if connection_count > 1:
                LOG.debug('There are still other connections to volume %s,'
                          ' not detaching', volume.name_id)
                self._connections.decrement(volume.name_id)
                return
            # decrement of connections will happen in terminate_connection()
            super(driver.VolumeDriver, self).\
                _detach_volume(context, attach_info, volume, properties,
                               force=force,
                               remote=remote,
                               ignore_errors=ignore_errors)
        _do_detach_volume()

    @volume_utils.trace
    def initialize_connection(self, volume, connector):
        @utils.synchronized("tatlin-volume-connections-%s" % volume.name_id)
        def _initialize_connection():
            LOG.debug('Init %s with connector %s', volume.name_id, connector)
            current_host = self.find_current_host(connector)
            self.add_volume_to_host(volume, current_host)
            if self._is_cinder_host_connection(connector):
                self._connections.increment(volume.name_id)
            connection_info = self._create_connection_info(volume, connector)
            fczm_utils.add_fc_zone(connection_info)
            return connection_info
        return _initialize_connection()

    @volume_utils.trace
    def terminate_connection(self, volume, connector, **kwargs):
        @utils.synchronized("tatlin-volume-connections-%s" % volume.name_id)
        def _terminate_connection():
            LOG.debug('Terminate connection for %s with connector  %s',
                      volume.name_id, connector)
            connection_info = self._create_connection_info(volume, connector)
            if not connector:
                self.remove_volume_from_all_hosts(volume)
                return connection_info
            if self._is_cinder_host_connection(connector):
                connections = self._connections.decrement(volume.name_id)
                if connections > 0:
                    LOG.debug('Not terminating connection: '
                              'volume %s, existing connections: %s',
                              volume.name_id, connections)
                    return connection_info
            hostname = connector['host']
            if self._is_nova_multiattached(volume, hostname):
                LOG.debug('Volume %s is attached on host %s to multiple VMs.'
                          ' Not terminating connection', volume.name_id,
                          hostname)
                return connection_info
            host_id = self.find_current_host(connector)
            self.remove_volume_from_host(volume, host_id)
            resources = [r for r in self.tatlin_api.get_resource_mapping()
                         if r.get('host_id', '') == host_id]
            if not resources:
                fczm_utils.remove_fc_zone(connection_info)
            return connection_info
        _terminate_connection()

    def _is_cinder_host_connection(self, connector):
        # Check if attachment happens on this Cinder host
        properties = brick_get_connector_properties()
        return properties['initiator'] == connector['initiator']

    def _is_nova_multiattached(self, volume, hostname):
        # Check if connection to the volume happens to multiple VMs
        # on the same Nova Compute host
        if not volume.volume_attachment:
            return False
        attachments = [a for a in volume.volume_attachment
                       if a.attach_status ==
                       objects.fields.VolumeAttachStatus.ATTACHED and
                       a.attached_host == hostname]
        return len(attachments) > 1

    def _create_temp_volume_for_snapshot(self, snapshot):
        return self._create_temp_volume(
            self.ctx,
            snapshot.volume,
            {
                'name_id': snapshot.id,
                'display_name': 'snap-vol-%s' % snapshot.id,
                'metadata': {'snapshot_volume': 'yes'},
            })

    @volume_utils.trace
    def create_snapshot(self, snapshot):
        LOG.debug('Create snapshot for volume %s, snap id %s',
                  snapshot.volume.name_id,
                  snapshot.id)
        temp_volume = self._create_temp_volume_for_snapshot(snapshot)
        try:
            self.create_cloned_volume(temp_volume, snapshot.volume)
        finally:
            temp_volume.destroy()

    @volume_utils.trace
    def create_volume_from_snapshot(self, volume, snapshot):
        LOG.debug('Create volume from snapshot %s', snapshot.id)
        temp_volume = self._create_temp_volume_for_snapshot(snapshot)
        try:
            self.create_volume(volume)
            self._clone_volume_data(volume, temp_volume)
        finally:
            temp_volume.destroy()

    @volume_utils.trace
    def delete_snapshot(self, snapshot):
        LOG.debug('Delete snapshot %s', snapshot.id)
        temp_volume = self._create_temp_volume_for_snapshot(snapshot)
        try:
            self.delete_volume(temp_volume)
        finally:
            temp_volume.destroy()

    @volume_utils.trace
    def get_volume_stats(self, refresh=False):
        if not self._stats or refresh:
            self._update_volume_stats()

        return self._stats

    def _update_qos(self, volume):
        type_id = volume.volume_type_id
        LOG.debug('VOL_TYPE %s', type_id)
        if type_id:
            ctx = cinder_context.get_admin_context()
            volume_type = volume_types.get_volume_type(ctx, type_id)
            qos_specs_id = volume_type.get('qos_specs_id')
            LOG.debug('VOL_TYPE %s QOS_SPEC %s', volume_type, qos_specs_id)
            specs = {}
            if qos_specs_id is not None:
                sp = qos_specs.get_qos_specs(ctx, qos_specs_id)
                if sp.get('consumer') != 'front-end':
                    specs = qos_specs.get_qos_specs(ctx, qos_specs_id)['specs']
            LOG.debug('QoS spec: %s', specs)
            param_specs = volume_type.get('extra_specs')
            LOG.debug('Param spec is: %s', param_specs)

            iops = specs["total_iops_sec_max"] \
                if 'total_iops_sec_max' in specs \
                else param_specs["YADRO:total_iops_sec_max"] \
                if 'YADRO:total_iops_sec_max' in param_specs else '0'

            bandwidth = specs["total_bytes_sec_max"] \
                if 'total_bytes_sec_max' in specs \
                else param_specs["YADRO:total_bytes_sec_max"] \
                if 'YADRO:total_bytes_sec_max' in param_specs else '0'

            LOG.debug('QOS spec IOPS: %s BANDWIDTH %s', iops, bandwidth)

            self.tatlin_api.update_qos(
                volume.name_id, int(iops), int(bandwidth))

    @volume_utils.trace
    def _update_volume_stats(self):
        """Retrieve pool info"""
        LOG.debug('Update volume stats for pool: %s', self.pool_name)
        if not self.pool_id:
            LOG.error('Could not retrieve pool id for %s', self.pool_name)
            return
        try:
            pool_stat = self.tatlin_api.get_pool_detail(self.pool_id)
        except TatlinAPIException as exp:
            message = (_('TatlinVolumeDriver get volume stats '
                       'failed %s due to %s') %
                       (self.pool_name, exp.message))
            LOG.error(message)
            return

        try:
            sys_stat = self.tatlin_api.get_sys_statistic()
        except TatlinAPIException as exp:
            message = (_('TatlinVolumeDriver get system stats detail '
                       'failed %s due to %s') %
                       (self.pool_name, exp.message))
            LOG.error(message)
            return

        if sys_stat['iops_bandwidth'] is not None and \
                len(sys_stat['iops_bandwidth']) > 0:
            self._stats['read_iops'] = \
                sys_stat['iops_bandwidth'][0]['value']['read_iops']
            self._stats['write_iops'] = \
                sys_stat['iops_bandwidth'][0]['value']['write_iops']
            self._stats['total_iops'] = \
                sys_stat['iops_bandwidth'][0]['value']['total_iops']
            self._stats['read_bytes_ps'] = \
                sys_stat['iops_bandwidth'][0]['value']['read_bytes_ps']
            self._stats['write_bytes_ps'] = \
                sys_stat['iops_bandwidth'][0]['value']['write_bytes_ps']
            self._stats['total_bytes_ps'] = \
                sys_stat['iops_bandwidth'][0]['value']['total_bytes_ps']

        self._stats["volume_backend_name"] = self.backend_name
        self._stats["vendor_name"] = 'YADRO'
        self._stats["driver_version"] = self.VERSION
        self._stats["storage_protocol"] = self.DRIVER_VOLUME_TYPE
        self._stats["thin_provisioning_support"] = pool_stat['thinProvision']
        self._stats["consistencygroup_support"] = False
        self._stats["consistent_group_snapshot_enabled"] = False
        self._stats["QoS_support"] = True
        self._stats["multiattach"] = True
        self._stats['total_capacity_gb'] = \
            (int(pool_stat['capacity']) - int(pool_stat['failed'])) / units.Gi
        self._stats['tatlin_pool'] = self.pool_name
        self._stats['tatlin_ip'] = self._ip
        pool_res_count, cluster_res_count = \
            self.tatlin_api.get_resource_count(self.pool_id)
        self._stats['overall_resource_count'] = cluster_res_count
        self._stats['pool_resource_count'] = pool_res_count
        if pool_stat['thinProvision']:
            self._stats['provisioned_capacity_gb'] = \
                (int(pool_stat['capacity']) -
                 int(pool_stat['failed'])) / units.Gi
            self._stats['free_capacity_gb'] = \
                self._stats['provisioned_capacity_gb']
        else:
            self._stats['provisioned_capacity_gb'] = \
                (int(pool_stat['available']) -
                 int(pool_stat['failed'])) / units.Gi
            self._stats['free_capacity_gb'] = \
                self._stats['provisioned_capacity_gb']

        self._stats['utilization'] = \
            (float(self._stats['total_capacity_gb']) -
             float(self._stats['free_capacity_gb'])) / \
            float(self._stats['total_capacity_gb']) * 100

        LOG.debug(
            'Total capacity: %s Free capacity: %s '
            'Provisioned capacity: %s '
            'Thin provisioning: %s '
            'Resource count: %s '
            'Pool resource count %s '
            'Utilization %s',
            self._stats['total_capacity_gb'],
            self._stats['free_capacity_gb'],
            self._stats['provisioned_capacity_gb'],
            pool_stat['thinProvision'], self._stats['overall_resource_count'],
            self._stats['pool_resource_count'],
            self._stats['utilization'])

    def _init_vendor_properties(self):
        LOG.debug('Initializing YADRO vendor properties')
        properties = {}
        self._set_property(
            properties,
            "YADRO:total_bytes_sec_max",
            "YADRO QoS Max bytes Write",
            _("Max write iops setting for volume qos, "
              "use 0 for unlimited"),
            "integer",
            minimum=0,
            default=0)
        self._set_property(
            properties,
            "YADRO:total_iops_sec_max",
            "YADRO QoS Max IOPS Write",
            _("Max write iops setting for volume qos, "
              "use 0 for unlimited"),
            "integer",
            minimum=0,
            default=0)
        LOG.debug('YADRO vendor properties: %s', properties)
        return properties, 'YADRO'

    def migrate_volume(self, context, volume, host):
        """Migrate volume

        Method checks if target volume will be on the same Tatlin/Pool
        If not, re-type should be executed.
        """
        if 'tatlin_pool' not in host['capabilities']:
            return False, None
        self._update_qos(volume)
        LOG.debug('Migrating volume from pool %s ip %s to pool %s ip %s',
                  self.pool_name, self._ip,
                  host['capabilities']['tatlin_pool'],
                  host['capabilities']['tatlin_ip'])
        if host['capabilities']['tatlin_ip'] == self._ip and \
                host['capabilities']['tatlin_pool'] == self.pool_name:
            return True, None

        return False, None

    def manage_existing(self, volume, external_ref):
        """Entry point to manage existing resource"""
        source_name = external_ref.get('source-name', None)
        if source_name is None:
            raise exception.ManageExistingInvalidReference(
                _('source_name should be provided'))
        try:
            result = self.tatlin_api.get_volume_info(source_name)
        except Exception:
            raise exception.ManageExistingInvalidReference(
                _('Unable to get resource with %s name' % source_name))

        existing_vol = result[0]
        existing_vol['name'] = volume.name_id
        volume.name_id = existing_vol['id']

        pool_id = existing_vol['poolId']

        if pool_id != self.pool_id:
            raise exception.ManageExistingInvalidReference(
                _('Existing volume should be in %s pool' % self.pool_name))

        self._update_qos(volume)

    def manage_existing_get_size(self, volume, external_ref):
        source_name = external_ref.get('source-name', None)
        if source_name is None:
            raise exception.ManageExistingInvalidReference(
                _('source_name should be provided'))

        try:
            result = self.tatlin_api.get_volume_info(source_name)
        except TatlinAPIException:
            raise exception.ManageExistingInvalidReference(
                _('Unable to get resource with %s name' % source_name))

        size = int(result[0]['size']) / units.G
        return size

    def add_volume_to_host(self, volume, host_id):
        self.tatlin_api.add_vol_to_host(volume.name_id, host_id)
        self._update_qos(volume)

    def remove_volume_from_host(self, volume, host_id):
        self.tatlin_api.remove_vol_from_host(volume.name_id, host_id)

    def remove_volume_from_all_hosts(self, volume):
        mappings = self.tatlin_api.get_resource_mapping()
        hosts = [m['host_id'] for m in mappings
                 if 'resource_id' in m and m['resource_id'] == volume.name_id]
        for host_id in hosts:
            self.tatlin_api.remove_vol_from_host(volume.name_id, host_id)

    def _is_port_assigned(self, volume_id, port):
        LOG.debug('VOLUME %s: Checking port %s ', volume_id, port)
        cur_ports = self.tatlin_api.get_resource_ports_array(volume_id)
        res = port in cur_ports
        LOG.debug('VOLUME %s: port %s assigned %s',
                  volume_id, port, str(res))
        return res

    def _get_ports_portals(self):
        return {}

    def _create_connection_info(self, volume, connector):
        return {}

    def _find_mapped_lun(self, volume_id, connector):
        host_id = self.find_current_host(connector)
        result = self.tatlin_api.get_resource_mapping()
        for r in result:
            if 'host_id' in r:
                if r['resource_id'] == volume_id and r['host_id'] == host_id:
                    return r['mapped_lun_id']
        mess = (_('Unable to get mapped lun for volume %s on host %s') %
                 (volume_id, host_id))
        LOG.error(mess)
        raise exception.VolumeBackendAPIException(message=mess)

    @staticmethod
    def get_driver_options():
        return tatlin_opts

    @volume_utils.trace
    def ensure_export(self, context, volume):
        LOG.debug('Tatlin ensure export')
        ports = self._get_ports_portals()
        self.tatlin_api.export_volume(volume.name_id, ports)

    @volume_utils.trace
    def create_export(self, context, volume, connector):
        LOG.debug('Create export for %s started', volume.name_id)
        self.ensure_export(context, volume)
        LOG.debug('Create export for %s finished', volume.name_id)

    def remove_export(self, context, volume):
        return

    def _get_tatlin_client(self):
        return InitTatlinClient(
            self._ip, self._port, self._user,
            self._password, verify=self.verify,
            api_retry_count=self.configuration.tat_api_retry_count,
            wait_interval=self._wait_interval,
            wait_retry_count=self._wait_retry_count)

    def find_current_host(self, connector):
        return ''

    @property
    def pool_id(self):
        if not self._pool_id:
            try:
                self._pool_id = self.tatlin_api.get_pool_id_by_name(
                    self.pool_name)
            except exception.VolumeBackendAPIException:
                LOG.error('Unable to get current Tatlin pool')
        return self._pool_id

    @pool_id.setter
    def pool_id(self, value):
        self._pool_id = value

    @property
    def pool_name(self):
        return self._pool_name

    @pool_name.setter
    def pool_name(self, value):
        self._pool_name = value

    def get_default_filter_function(self):
        return self.DEFAULT_FILTER_FUNCTION

    def get_default_goodness_function(self):
        return self.DEFAULT_GOODNESS_FUNCTION

    @volume_utils.trace
    def get_backup_device(self, context, backup):
        """Get a backup device from an existing volume.

        We currently return original device where possible
        due to absence of instant clones and snapshots
        """
        if backup.snapshot_id:
            return super().get_backup_device(context, backup)

        volume = objects.Volume.get_by_id(context, backup.volume_id)
        return (volume, False)

    def backup_use_temp_snapshot(self):
        return False

    def snapshot_revert_use_temp_snapshot(self):
        return False
