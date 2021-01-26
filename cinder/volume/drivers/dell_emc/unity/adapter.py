# Copyright (c) 2016 - 2018 Dell Inc. or its subsidiaries.
# All Rights Reserved.
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

import contextlib
import copy
import functools
import os
import random

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import importutils

from cinder import exception
from cinder.i18n import _
from cinder.objects import fields
from cinder import utils as cinder_utils
from cinder.volume.drivers.dell_emc.unity import client
from cinder.volume.drivers.dell_emc.unity import utils
from cinder.volume import volume_types
from cinder.volume import volume_utils

storops = importutils.try_import('storops')
if storops:
    from storops import exception as storops_ex
    from storops.unity import enums
else:
    # Set storops_ex to be None for unit test
    storops_ex = None
    enums = None

LOG = logging.getLogger(__name__)

PROTOCOL_FC = 'FC'
PROTOCOL_ISCSI = 'iSCSI'


class VolumeParams(object):
    def __init__(self, adapter, volume, group_specs=None):
        self._adapter = adapter
        self._volume = volume

        self._volume_id = volume.id
        self._name = volume.name
        self._size = volume.size
        self._description = (volume.display_description
                             if volume.display_description
                             else volume.display_name)
        self._pool = None
        self._io_limit_policy = None
        self._is_thick = None
        self._is_compressed = None
        self._is_in_cg = None
        self._is_replication_enabled = None
        self._tiering_policy = None
        self.group_specs = group_specs if group_specs else {}

    @property
    def volume_id(self):
        return self._volume_id

    @property
    def name(self):
        return self._name

    @name.setter
    def name(self, value):
        self._name = value

    @property
    def size(self):
        return self._size

    @size.setter
    def size(self, value):
        self._size = value

    @property
    def description(self):
        return self._description

    @description.setter
    def description(self, value):
        self._description = value

    @property
    def pool(self):
        if self._pool is None:
            self._pool = self._adapter._get_target_pool(self._volume)
        return self._pool

    @pool.setter
    def pool(self, value):
        self._pool = value

    @property
    def io_limit_policy(self):
        if self._io_limit_policy is None:
            qos_specs = utils.get_backend_qos_specs(self._volume)
            self._io_limit_policy = self._adapter.client.get_io_limit_policy(
                qos_specs)
        return self._io_limit_policy

    @io_limit_policy.setter
    def io_limit_policy(self, value):
        self._io_limit_policy = value

    @property
    def is_thick(self):
        if self._is_thick is None:
            provision = utils.get_extra_spec(self._volume,
                                             utils.PROVISIONING_TYPE)
            support = utils.get_extra_spec(self._volume,
                                           'thick_provisioning_support')
            self._is_thick = (provision == 'thick' and support == '<is> True')
        return self._is_thick

    @property
    def is_compressed(self):
        if self._is_compressed is None:
            provision = utils.get_extra_spec(self._volume,
                                             utils.PROVISIONING_TYPE)
            compression = utils.get_extra_spec(self._volume,
                                               'compression_support')
            if (provision == utils.PROVISIONING_COMPRESSED and
                    compression == '<is> True'):
                self._is_compressed = True
        return self._is_compressed

    @is_compressed.setter
    def is_compressed(self, value):
        self._is_compressed = value

    @property
    def is_in_cg(self):
        if self._is_in_cg is None:
            self._is_in_cg = (self._volume.group and
                              volume_utils.is_group_a_cg_snapshot_type(
                                  self._volume.group))
        return self._is_in_cg

    @property
    def tiering_policy(self):
        tiering_policy_map = {'StartHighThenAuto':
                              enums.TieringPolicyEnum.AUTOTIER_HIGH,
                              'Auto':
                              enums.TieringPolicyEnum.AUTOTIER,
                              'HighestAvailable':
                              enums.TieringPolicyEnum.HIGHEST,
                              'LowestAvailable':
                              enums.TieringPolicyEnum.LOWEST}
        if not self._tiering_policy:
            tiering_value = utils.get_extra_spec(self._volume,
                                                 'storagetype:tiering')
            support = utils.get_extra_spec(self._volume,
                                           'fast_support') == '<is> True'

            if tiering_value and support:
                self._tiering_policy = tiering_policy_map.get(tiering_value)
            # if no value, unity sets StartHighThenAuto as default
        return self._tiering_policy

    @property
    def cg_id(self):
        if self.is_in_cg:
            return self._volume.group_id
        return None

    @property
    def is_replication_enabled(self):
        if self._is_replication_enabled is None:
            value = utils.get_extra_spec(self._volume, 'replication_enabled')
            self._is_replication_enabled = value == '<is> True'
        return self._is_replication_enabled

    def __eq__(self, other):
        return (self.volume_id == other.volume_id and
                self.name == other.name and
                self.size == other.size and
                self.io_limit_policy == other.io_limit_policy and
                self.is_thick == other.is_thick and
                self.is_compressed == other.is_compressed and
                self.is_in_cg == other.is_in_cg and
                self.cg_id == other.cg_id and
                self.tiering_policy == other.tiering_policy and
                self.is_replication_enabled == other.is_replication_enabled)


class CommonAdapter(object):
    protocol = 'unknown'
    driver_name = 'UnityAbstractDriver'
    driver_volume_type = 'unknown'

    def __init__(self, version=None):
        self.is_setup = False
        self.version = version
        self.driver = None
        self.config = None
        self.configured_pool_names = None
        self.reserved_percentage = None
        self.max_over_subscription_ratio = None
        self.volume_backend_name = None
        self.ip = None
        self.username = None
        self.password = None
        self.array_cert_verify = None
        self.array_ca_cert_path = None

        self._serial_number = None
        self.storage_pools_map = None
        self._client = None
        self.allowed_ports = None
        self.remove_empty_host = False
        self.to_lock_host = False
        self.replication_manager = None

    def do_setup(self, driver, conf):
        """Sets up the attributes of adapter.

        :param driver: the unity driver.
        :param conf: the driver configurations.
        """
        self.driver = driver
        self.config = self.normalize_config(conf)
        self.replication_manager = driver.replication_manager
        self.configured_pool_names = self.config.unity_storage_pool_names
        self.reserved_percentage = self.config.reserved_percentage
        self.max_over_subscription_ratio = (
            self.config.max_over_subscription_ratio)
        self.volume_backend_name = (self.config.safe_get('volume_backend_name')
                                    or self.driver_name)
        self.ip = self.config.san_ip
        self.username = self.config.san_login
        self.password = self.config.san_password
        # Allow for customized CA
        self.array_cert_verify = self.config.driver_ssl_cert_verify
        self.array_ca_cert_path = self.config.driver_ssl_cert_path

        sys_version = self.client.system.system_version
        if utils.is_before_4_1(sys_version):
            raise exception.VolumeBackendAPIException(
                data=_('Unity driver does not support array OE version: %s. '
                       'Upgrade to 4.1 or later.') % sys_version)

        self.storage_pools_map = self.get_managed_pools()

        self.allowed_ports = self.validate_ports(self.config.unity_io_ports)

        self.remove_empty_host = self.config.remove_empty_host
        self.to_lock_host = self.remove_empty_host

        group_name = (self.config.config_group if self.config.config_group
                      else 'DEFAULT')
        folder_name = '%(group)s.%(sys_name)s' % {
            'group': group_name, 'sys_name': self.client.system.info.name}
        persist_path = os.path.join(cfg.CONF.state_path, 'unity', folder_name)
        storops.TCHelper.set_up(persist_path)

        self.is_setup = True

    def normalize_config(self, config):
        config.unity_storage_pool_names = utils.remove_empty(
            '%s.unity_storage_pool_names' % config.config_group,
            config.unity_storage_pool_names)

        config.unity_io_ports = utils.remove_empty(
            '%s.unity_io_ports' % config.config_group,
            config.unity_io_ports)

        return config

    def get_all_ports(self):
        raise NotImplementedError()

    def validate_ports(self, ports_whitelist):
        all_ports = self.get_all_ports()
        # After normalize_config, `ports_whitelist` could be only None or valid
        # list in which the items are stripped.
        if ports_whitelist is None:
            return all_ports.id

        # For iSCSI port, the format is 'spa_eth0', and 'spa_iom_0_fc0' for FC.
        # Unix style glob like 'spa_*' is supported.
        whitelist = set(ports_whitelist)

        matched, _ignored, unmatched_whitelist = utils.match_any(all_ports.id,
                                                                 whitelist)
        if not matched:
            LOG.error('No matched ports filtered by all patterns: %s',
                      whitelist)
            raise exception.InvalidConfigurationValue(
                option='%s.unity_io_ports' % self.config.config_group,
                value=self.config.unity_io_ports)

        if unmatched_whitelist:
            LOG.error('No matched ports filtered by below patterns: %s',
                      unmatched_whitelist)
            raise exception.InvalidConfigurationValue(
                option='%s.unity_io_ports' % self.config.config_group,
                value=self.config.unity_io_ports)

        LOG.info('These ports %(matched)s will be used based on '
                 'the option unity_io_ports: %(config)s',
                 {'matched': matched,
                  'config': self.config.unity_io_ports})
        return matched

    @property
    def verify_cert(self):
        verify_cert = self.array_cert_verify
        if verify_cert and self.array_ca_cert_path is not None:
            verify_cert = self.array_ca_cert_path
        return verify_cert

    @property
    def client(self):
        if self._client is None:
            self._client = client.UnityClient(
                self.ip,
                self.username,
                self.password,
                verify_cert=self.verify_cert)
        return self._client

    @property
    def serial_number(self):
        if self._serial_number is None:
            self._serial_number = self.client.get_serial()
        return self._serial_number

    def get_managed_pools(self):
        names = self.configured_pool_names
        array_pools = self.client.get_pools()
        valid_names = utils.validate_pool_names(names, array_pools.name)
        return {p.name: p for p in array_pools if p.name in valid_names}

    def makeup_model(self, lun_id, is_snap_lun=False):
        lun_type = 'snap_lun' if is_snap_lun else 'lun'
        location = self._build_provider_location(lun_id=lun_id,
                                                 lun_type=lun_type)
        return {
            'provider_location': location,
            'provider_id': lun_id
        }

    def setup_replications(self, lun, model_update):
        if not self.replication_manager.is_replication_configured:
            LOG.debug('Replication device not configured, '
                      'skip setting up replication for lun %s',
                      lun.name)
            return model_update

        rep_data = {}
        rep_devices = self.replication_manager.replication_devices
        for backend_id, dst in rep_devices.items():
            remote_serial_number = dst.adapter.serial_number
            LOG.debug('Setting up replication to remote system %s',
                      remote_serial_number)
            remote_system = self.client.get_remote_system(remote_serial_number)
            if remote_system is None:
                raise exception.VolumeBackendAPIException(
                    data=_('Setup replication to remote system %s failed.'
                           'Cannot find it.') % remote_serial_number)
            rep_session = self.client.create_replication(
                lun, dst.max_time_out_of_sync,
                dst.destination_pool.get_id(), remote_system)
            rep_data[backend_id] = rep_session.name
        return utils.enable_replication_status(model_update, rep_data)

    def create_volume(self, volume):
        """Creates a volume.

        :param volume: volume information
        """
        params = VolumeParams(self, volume)
        log_params = {
            'name': params.name,
            'size': params.size,
            'description': params.description,
            'pool': params.pool,
            'io_limit_policy': params.io_limit_policy,
            'is_thick': params.is_thick,
            'is_compressed': params.is_compressed,
            'cg_id': params.cg_id,
            'is_replication_enabled': params.is_replication_enabled,
            'tiering_policy': params.tiering_policy
        }

        LOG.info('Create Volume: %(name)s, size: %(size)s, description: '
                 '%(description)s, pool: %(pool)s, io limit policy: '
                 '%(io_limit_policy)s, thick: %(is_thick)s, '
                 'compressed: %(is_compressed)s, cg_group: %(cg_id)s, '
                 'replication_enabled: %(is_replication_enabled)s.',
                 log_params)

        lun = self.client.create_lun(
            name=params.name,
            size=params.size,
            pool=params.pool,
            description=params.description,
            io_limit_policy=params.io_limit_policy,
            is_thin=False if params.is_thick else None,
            is_compressed=params.is_compressed,
            tiering_policy=params.tiering_policy)
        if params.cg_id:
            if self.client.is_cg_replicated(params.cg_id):
                msg = (_('Consistency group %(cg_id)s is in '
                         'replication status, cannot add lun to it.')
                       % {'cg_id': params.cg_id})
                raise exception.InvalidGroupStatus(reason=msg)
            LOG.info('Adding lun %(lun)s to cg %(cg)s.',
                     {'lun': lun.get_id(), 'cg': params.cg_id})
            self.client.update_cg(params.cg_id, [lun.get_id()], ())

        model_update = self.makeup_model(lun.get_id())

        if params.is_replication_enabled:
            if not params.cg_id:
                model_update = self.setup_replications(
                    lun, model_update)
            else:
                # Volume replication_status need be disabled
                # And be controlled by group replication
                model_update['replication_status'] = (
                    fields.ReplicationStatus.DISABLED)
        return model_update

    def delete_volume(self, volume):
        lun_id = self.get_lun_id(volume)
        if lun_id is None:
            LOG.info('Backend LUN not found, skipping the deletion. '
                     'Volume: %(volume_name)s.',
                     {'volume_name': volume.name})
        else:
            self.client.delete_lun(lun_id)

    def retype(self, ctxt, volume, new_type, diff, host):
        """Changes volume from one type to another."""
        old_qos_specs = {utils.QOS_SPECS: None}
        old_provision = None
        new_specs = volume_types.get_volume_type_extra_specs(
            new_type.get(utils.QOS_ID))
        new_qos_specs = volume_types.get_volume_type_qos_specs(
            new_type.get(utils.QOS_ID))
        lun = self.client.get_lun(name=volume.name)
        volume_type_id = volume.volume_type_id
        if volume_type_id:
            old_provision = utils.get_extra_spec(volume,
                                                 utils.PROVISIONING_TYPE)
            old_qos_specs = volume_types.get_volume_type_qos_specs(
                volume_type_id)

        need_migration = utils.retype_need_migration(
            volume, old_provision,
            new_specs.get(utils.PROVISIONING_TYPE), host)
        need_change_compress = utils.retype_need_change_compression(
            old_provision, new_specs.get(utils.PROVISIONING_TYPE))
        need_change_qos = utils.retype_need_change_qos(
            old_qos_specs, new_qos_specs)

        if need_migration or need_change_compress[0] or need_change_qos:
            if self.client.lun_has_snapshot(lun):
                LOG.warning('Driver is not able to do retype because '
                            'the volume %s has snapshot(s).',
                            volume.id)
                return False

        new_qos_dict = new_qos_specs.get(utils.QOS_SPECS)
        if need_change_qos:
            new_io_policy = (self.client.get_io_limit_policy(new_qos_dict)
                             if need_change_qos else None)
            # Modify lun to change qos settings
            if new_io_policy:
                lun.modify(io_limit_policy=new_io_policy)
            else:
                # remove current qos settings
                old_qos_dict = old_qos_specs.get(utils.QOS_SPECS)
                old_io_policy = self.client.get_io_limit_policy(old_qos_dict)
                old_io_policy.remove_from_storage(lun)

        if need_migration:
            LOG.debug('Driver needs to use storage-assisted migration '
                      'to retype the volume.')
            return self.migrate_volume(volume, host, new_specs)

        if need_change_compress[0]:
            # Modify lun to change compression
            lun.modify(is_compression=need_change_compress[1])
        return True

    def _create_host_and_attach(self, host_name, lun_or_snap):
        @utils.lock_if(self.to_lock_host, '{lock_name}')
        def _lock_helper(lock_name):
            if not self.to_lock_host:
                host = self.client.create_host(host_name)
            else:
                # Use the lock in the decorator
                host = self.client.create_host_wo_lock(host_name)
            hlu = self.client.attach(host, lun_or_snap)
            return host, hlu

        return _lock_helper('{unity}-{host}'.format(unity=self.client.host,
                                                    host=host_name))

    def _initialize_connection(self, lun_or_snap, connector, vol_id):
        host, hlu = self._create_host_and_attach(connector['host'],
                                                 lun_or_snap)
        self.client.update_host_initiators(
            host, self.get_connector_uids(connector))
        data = self.get_connection_info(hlu, host, connector)
        data['target_discovered'] = True
        if vol_id is not None:
            data['volume_id'] = vol_id
        conn_info = {
            'driver_volume_type': self.driver_volume_type,
            'data': data,
        }
        return conn_info

    @volume_utils.trace
    def initialize_connection(self, volume, connector):
        lun = self.client.get_lun(lun_id=self.get_lun_id(volume))
        return self._initialize_connection(lun, connector, volume.id)

    @staticmethod
    def filter_targets_by_host(host):
        # No target info for iSCSI driver
        return []

    def _detach_and_delete_host(self, host_name, lun_or_snap,
                                is_multiattach_to_host=False):
        @utils.lock_if(self.to_lock_host, '{lock_name}')
        def _lock_helper(lock_name):
            # Only get the host from cache here
            host = self.client.create_host_wo_lock(host_name)
            if not is_multiattach_to_host:
                self.client.detach(host, lun_or_snap)
            host.update()  # need update to get the latest `host_luns`
            targets = self.filter_targets_by_host(host)
            if self.remove_empty_host and not host.host_luns:
                self.client.delete_host_wo_lock(host)
            return targets

        return _lock_helper('{unity}-{host}'.format(unity=self.client.host,
                                                    host=host_name))

    @staticmethod
    def get_terminate_connection_info(connector, targets):
        # No return data from terminate_connection for iSCSI driver
        return {}

    def _terminate_connection(self, lun_or_snap, connector,
                              is_multiattach_to_host=False):
        is_force_detach = connector is None
        data = {}
        if is_force_detach:
            self.client.detach_all(lun_or_snap)
        else:
            targets = self._detach_and_delete_host(
                connector['host'], lun_or_snap,
                is_multiattach_to_host=is_multiattach_to_host)
            data = self.get_terminate_connection_info(connector, targets)
        return {
            'driver_volume_type': self.driver_volume_type,
            'data': data,
        }

    @volume_utils.trace
    def terminate_connection(self, volume, connector):
        lun = self.client.get_lun(lun_id=self.get_lun_id(volume))
        # None `connector` indicates force detach, then detach all even the
        # volume is multi-attached.
        multiattach_flag = (connector is not None and
                            utils.is_multiattach_to_host(
                                volume.volume_attachment,
                                connector['host']))
        return self._terminate_connection(
            lun, connector, is_multiattach_to_host=multiattach_flag)

    def get_connector_uids(self, connector):
        return None

    def get_connection_info(self, hlu, host, connector):
        return {}

    def extend_volume(self, volume, new_size):
        lun_id = self.get_lun_id(volume)
        if lun_id is None:
            msg = (_('Backend LUN not found for Volume: %(volume_name)s.') %
                   {'volume_name': volume.name})
            raise exception.VolumeBackendAPIException(data=msg)
        else:
            self.client.extend_lun(lun_id, new_size)

    def _get_target_pool(self, volume):
        return self.storage_pools_map[utils.get_pool_name(volume)]

    def _build_provider_location(self, lun_id=None, lun_type=None):
        return utils.build_provider_location(
            system=self.serial_number,
            lun_type=lun_type,
            lun_id=lun_id,
            version=self.version)

    @utils.append_capabilities
    def update_volume_stats(self):
        return {
            'volume_backend_name': self.volume_backend_name,
            'storage_protocol': self.protocol,
            'pools': self.get_pools_stats(),
            'replication_enabled':
                self.replication_manager.is_replication_configured,
            'replication_targets':
                list(self.replication_manager.replication_devices),
        }

    def get_pools_stats(self):
        self.storage_pools_map = self.get_managed_pools()
        return [self._get_pool_stats(pool) for pool in self.pools]

    @property
    def pools(self):
        return self.storage_pools_map.values()

    @utils.append_capabilities
    def _get_pool_stats(self, pool):
        return {
            'pool_name': pool.name,
            'total_capacity_gb': utils.byte_to_gib(pool.size_total),
            'provisioned_capacity_gb': utils.byte_to_gib(
                pool.size_subscribed),
            'free_capacity_gb': utils.byte_to_gib(pool.size_free),
            'reserved_percentage': self.reserved_percentage,
            'location_info': ('%(pool_name)s|%(array_serial)s' %
                              {'pool_name': pool.name,
                               'array_serial': self.serial_number}),
            'compression_support': pool.is_all_flash,
            'max_over_subscription_ratio': (
                self.max_over_subscription_ratio),
            'multiattach': True,
            'replication_enabled':
                self.replication_manager.is_replication_configured,
            'replication_targets':
                list(self.replication_manager.replication_devices),
        }

    def get_lun_id(self, volume):
        """Retrieves id of the volume's backing LUN.

        :param volume: volume information
        """
        if volume.provider_location:
            return utils.extract_provider_location(volume.provider_location,
                                                   'id')
        else:
            # In some cases, cinder will not update volume info in DB with
            # provider_location returned by us. We need to retrieve the id
            # from array.
            lun = self.client.get_lun(name=volume.name)
            return lun.get_id() if lun is not None else None

    def create_snapshot(self, snapshot):
        """Creates a snapshot.

        :param snapshot: snapshot information.
        """
        src_lun_id = self.get_lun_id(snapshot.volume)
        snap = self.client.create_snap(src_lun_id, snapshot.name)
        location = self._build_provider_location(lun_type='snapshot',
                                                 lun_id=snap.get_id())
        return {'provider_location': location,
                'provider_id': snap.get_id()}

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot.

        :param snapshot: the snapshot to delete.
        """
        snap = self.client.get_snap(name=snapshot.name)
        self.client.delete_snap(snap)

    def _get_referenced_lun(self, existing_ref):
        if 'source-id' in existing_ref:
            lun = self.client.get_lun(lun_id=existing_ref['source-id'])
        elif 'source-name' in existing_ref:
            lun = self.client.get_lun(name=existing_ref['source-name'])
        else:
            reason = _('Reference must contain source-id or source-name key.')
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_ref, reason=reason)
        if lun is None or not lun.existed:
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_ref,
                reason=_("LUN doesn't exist."))
        return lun

    def manage_existing(self, volume, existing_ref):
        """Manages an existing LUN in the array.

        The LUN should be in a manageable pool backend, otherwise return error.
        Rename the backend storage object so that it matches the
        `volume['name']` which is how drivers traditionally map between a
        cinder volume and the associated backend storage object.

        LUN ID or name are supported in `existing_ref`, like:

        .. code-block:: none

        existing_ref:{

            'source-id':<LUN id in Unity>

        }

        or

        .. code-block:: none

        existing_ref:{

            'source-name':<LUN name in Unity>

        }
        """
        lun = self._get_referenced_lun(existing_ref)
        lun.modify(name=volume.name)
        return {
            'provider_location':
                self._build_provider_location(lun_id=lun.get_id(),
                                              lun_type='lun'),
            'provider_id': lun.get_id()
        }

    def manage_existing_get_size(self, volume, existing_ref):
        """Returns size of volume to be managed by `manage_existing`.

        The driver does some check here:
        1. The LUN `existing_ref` should be managed by the `volume.host`.
        """
        lun = self._get_referenced_lun(existing_ref)
        target_pool_name = utils.get_pool_name(volume)
        lun_pool_name = lun.pool.name
        if target_pool_name and lun_pool_name != target_pool_name:
            reason = (_('The imported LUN is in pool %(pool_name)s '
                        'which is not managed by the host %(host)s.') %
                      {'pool_name': lun_pool_name,
                       'host': volume.host})
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_ref, reason=reason)

        return utils.byte_to_gib(lun.size_total)

    def _disconnect_device(self, conn):
        conn['connector'].disconnect_volume(conn['conn']['data'],
                                            conn['device'])

    def _connect_device(self, conn):
        return self.driver._connect_device(conn)

    @contextlib.contextmanager
    def _connect_resource(self, lun_or_snap, connector, res_id):
        """Connects to LUN or snapshot, and makes sure disconnect finally.

        :param lun_or_snap: the LUN or snapshot to connect/disconnect.
        :param connector: the host connector information.
        :param res_id: the ID of the LUN or snapshot.

        :return: the connection information, in a dict with format
         like (same as the one returned by `_connect_device`):
         {
            'conn': <info returned by `initialize_connection`>,
            'device': <value returned by `connect_volume`>,
            'connector': <host connector info>
         }
        """
        init_conn_func = functools.partial(self._initialize_connection,
                                           lun_or_snap, connector, res_id)
        term_conn_func = functools.partial(self._terminate_connection,
                                           lun_or_snap, connector)
        with utils.assure_cleanup(init_conn_func, term_conn_func,
                                  False) as conn_info:
            conn_device_func = functools.partial(self._connect_device,
                                                 conn_info)
            with utils.assure_cleanup(conn_device_func,
                                      self._disconnect_device,
                                      True) as attach_info:
                yield attach_info

    def _dd_copy(self, vol_params, src_snap, src_lun=None):
        """Creates a volume via copying a Unity snapshot.

        It attaches the `volume` and `snap`, then use `dd` to copy the
        data from the Unity snapshot to the `volume`.
        """
        dest_lun = self.client.create_lun(
            name=vol_params.name, size=vol_params.size, pool=vol_params.pool,
            description=vol_params.description,
            io_limit_policy=vol_params.io_limit_policy,
            is_thin=False if vol_params.is_thick else None,
            is_compressed=vol_params.is_compressed)
        src_id = src_snap.get_id()
        try:
            conn_props = volume_utils.brick_get_connector_properties()

            with self._connect_resource(dest_lun, conn_props,
                                        vol_params.volume_id) as dest_info, \
                    self._connect_resource(src_snap, conn_props,
                                           src_id) as src_info:
                if src_lun is None:
                    # If size is not specified, need to get the size from LUN
                    # of snapshot.
                    size_in_m = utils.byte_to_mib(src_snap.size)
                else:
                    size_in_m = utils.byte_to_mib(src_lun.size_total)
                volume_utils.copy_volume(
                    src_info['device']['path'],
                    dest_info['device']['path'],
                    size_in_m,
                    self.driver.configuration.volume_dd_blocksize,
                    sparse=True)
        except Exception:
            with excutils.save_and_reraise_exception():
                utils.ignore_exception(self.client.delete_lun,
                                       dest_lun.get_id())
                LOG.error('Failed to create cloned volume: %(vol_id)s, '
                          'from source unity snapshot: %(snap_name)s.',
                          {'vol_id': vol_params.volume_id,
                           'snap_name': src_snap.name})

        return dest_lun

    def _thin_clone(self, vol_params, src_snap, src_lun=None):
        tc_src = src_snap if src_lun is None else src_lun
        try:
            LOG.debug('Try to thin clone from %s.', tc_src.name)
            lun = self.client.thin_clone(
                tc_src, vol_params.name,
                description=vol_params.description,
                io_limit_policy=vol_params.io_limit_policy,
                new_size_gb=vol_params.size)
        except storops_ex.UnityThinCloneLimitExceededError:
            LOG.info('Number of thin clones of base LUN exceeds system '
                     'limit, dd-copy a new one and thin clone from it.')
            # Copy via dd if thin clone meets the system limit
            hidden = copy.copy(vol_params)
            hidden.name = 'hidden-%s' % vol_params.name
            hidden.description = 'hidden-%s' % vol_params.description
            copied_lun = self._dd_copy(hidden, src_snap, src_lun=src_lun)
            LOG.debug('Notify storops the dd action of lun: %(src_name)s. And '
                      'the newly copied lun is: %(copied)s.',
                      {'src_name': tc_src.name, 'copied': copied_lun.name})
            storops.TCHelper.notify(tc_src,
                                    storops.ThinCloneActionEnum.DD_COPY,
                                    copied_lun)
            lun = self.client.thin_clone(
                copied_lun, vol_params.name,
                description=vol_params.description,
                io_limit_policy=vol_params.io_limit_policy,
                new_size_gb=vol_params.size)
        except storops_ex.SystemAPINotSupported:
            # Thin clone not support on array version before Merlin
            lun = self._dd_copy(vol_params, src_snap, src_lun=src_lun)
            LOG.debug(
                'Volume copied via dd because array OE is too old to support '
                'thin clone api. source snap: %(src_snap)s, lun: %(src_lun)s.',
                {'src_snap': src_snap.name,
                 'src_lun': 'Unknown' if src_lun is None else src_lun.name})
        except storops_ex.UnityThinCloneNotAllowedError:
            # Thin clone not allowed on some resources,
            # like thick luns and their snaps
            lun = self._dd_copy(vol_params, src_snap, src_lun=src_lun)
            LOG.debug(
                'Volume copied via dd because source snap/lun is not allowed '
                'to thin clone, i.e. it is thick. source snap: %(src_snap)s, '
                'lun: %(src_lun)s.',
                {'src_snap': src_snap.name,
                 'src_lun': 'Unknown' if src_lun is None else src_lun.name})
        return lun

    def create_volume_from_snapshot(self, volume, snapshot):
        snap = self.client.get_snap(snapshot.name)
        params = VolumeParams(self, volume)
        lun = self._thin_clone(params, snap)
        model_update = self.makeup_model(lun.get_id(), is_snap_lun=True)

        if params.is_replication_enabled:
            model_update = self.setup_replications(lun, model_update)
        return model_update

    def create_cloned_volume(self, volume, src_vref):
        """Creates cloned volume.

        1. Take an internal snapshot of source volume, and attach it.
        2. Thin clone from the snapshot to a new volume.
           Note: there are several cases the thin clone will downgrade to `dd`,
           2.1 Source volume is attached (in-use).
           2.2 Array OE version doesn't support thin clone.
           2.3 The current LUN family reaches the thin clone limits.
        3. Delete the internal snapshot created in step 1.
        """

        src_lun_id = self.get_lun_id(src_vref)
        if src_lun_id is None:
            raise exception.VolumeBackendAPIException(
                data=_(
                    "LUN ID of source volume: %s not found.") % src_vref.name)
        src_lun = self.client.get_lun(lun_id=src_lun_id)
        src_snap_name = 'snap_clone_%s' % volume.id

        create_snap_func = functools.partial(self.client.create_snap,
                                             src_lun_id, src_snap_name)
        vol_params = VolumeParams(self, volume)
        with utils.assure_cleanup(create_snap_func,
                                  self.client.delete_snap,
                                  True) as src_snap:
            LOG.debug('Internal snapshot for clone is created, '
                      'name: %(name)s, id: %(id)s.',
                      {'name': src_snap_name,
                       'id': src_snap.get_id()})
            if src_vref.volume_attachment:
                lun = self._dd_copy(vol_params, src_snap, src_lun=src_lun)
                LOG.debug('Volume copied using dd because source volume: '
                          '%(name)s is attached: %(attach)s.',
                          {'name': src_vref.name,
                           'attach': src_vref.volume_attachment})
                model_update = self.makeup_model(lun.get_id())
            else:
                lun = self._thin_clone(vol_params, src_snap, src_lun=src_lun)
                model_update = self.makeup_model(lun.get_id(),
                                                 is_snap_lun=True)

            if vol_params.is_replication_enabled:
                model_update = self.setup_replications(lun, model_update)
            return model_update

    def get_pool_name(self, volume):
        return self.client.get_pool_name(volume.name)

    def get_pool_id_by_name(self, name):
        return self.client.get_pool_id_by_name(name=name)

    @volume_utils.trace
    def initialize_connection_snapshot(self, snapshot, connector):
        snap = self.client.get_snap(snapshot.name)
        return self._initialize_connection(snap, connector, snapshot.id)

    @volume_utils.trace
    def terminate_connection_snapshot(self, snapshot, connector):
        snap = self.client.get_snap(snapshot.name)
        return self._terminate_connection(snap, connector)

    @volume_utils.trace
    def restore_snapshot(self, volume, snapshot):
        return self.client.restore_snapshot(snapshot.name)

    def migrate_volume(self, volume, host, extra_specs=None):
        """Leverage the Unity move session functionality.

        This method is invoked at the source backend.

        :param extra_specs: Instance of ExtraSpecs. The new volume will be
            changed to align with the new extra specs.
        """
        log_params = {
            'name': volume.name,
            'src_host': volume.host,
            'dest_host': host['host'],
            'extra_specs': extra_specs,
        }
        LOG.info('Migrate Volume: %(name)s, host: %(src_host)s, destination: '
                 '%(dest_host)s, extra_specs: %(extra_specs)s', log_params)

        src_backend = utils.get_backend_name_from_volume(volume)
        dest_backend = utils.get_backend_name_from_host(host)

        if src_backend != dest_backend:
            LOG.debug('Cross-backends migration not supported by Unity '
                      'driver. Falling back to host-assisted migration.')
            return False, None

        lun_id = self.get_lun_id(volume)
        provision = None
        if extra_specs:
            provision = extra_specs.get(utils.PROVISIONING_TYPE)
        dest_pool_name = utils.get_pool_name_from_host(host)
        dest_pool_id = self.get_pool_id_by_name(dest_pool_name)
        if self.client.migrate_lun(lun_id, dest_pool_id, provision):
            LOG.debug('Volume migrated successfully.')
            model_update = {}
            return True, model_update

        LOG.debug('Volume migrated failed. Falling back to '
                  'host-assisted migration.')
        return False, None

    def create_group(self, group):
        """Creates a generic group.

        :param group: group information
        """
        cg_name = group.id
        description = group.description if group.description else group.name

        LOG.info('Create group: %(name)s, description: %(description)s',
                 {'name': cg_name, 'description': description})

        self.client.create_cg(cg_name, description=description)
        return {'status': fields.GroupStatus.AVAILABLE}

    def delete_group(self, group):
        """Deletes the generic group.

        :param group: the group to delete
        """

        # Deleting cg will also delete all the luns in it.
        group_id = group.id
        if self.client.is_cg_replicated(group_id):
            self.client.delete_cg_rep_session(group_id)
        self.client.delete_cg(group_id)
        return None, None

    def update_group(self, group, add_volumes, remove_volumes):
        add_lun_ids = (set(map(self.get_lun_id, add_volumes)) if add_volumes
                       else set())
        remove_lun_ids = (set(map(self.get_lun_id, remove_volumes))
                          if remove_volumes else set())
        self.client.update_cg(group.id, add_lun_ids, remove_lun_ids)
        return {'status': fields.GroupStatus.AVAILABLE}, None, None

    def copy_luns_in_group(self, group, volumes, src_cg_snap, src_volumes):
        # Use dd to copy data here. The reason why not using thinclone is:
        # 1. Cannot use cg thinclone due to the tight couple between source
        # group and cloned one.
        # 2. Cannot use lun thinclone due to clone lun in cg is not supported.

        lun_snaps = self.client.filter_snaps_in_cg_snap(src_cg_snap.id)

        # Make sure the `lun_snaps` is as order of `src_volumes`
        src_lun_ids = [self.get_lun_id(volume) for volume in src_volumes]
        lun_snaps.sort(key=lambda snap: src_lun_ids.index(snap.lun.id))

        dest_luns = [self._dd_copy(VolumeParams(self, dest_volume), lun_snap)
                     for dest_volume, lun_snap in zip(volumes, lun_snaps)]

        self.client.create_cg(group.id, lun_add=dest_luns)
        return ({'status': fields.GroupStatus.AVAILABLE},
                [{'id': dest_volume.id, 'status': fields.GroupStatus.AVAILABLE}
                 for dest_volume in volumes])

    def create_group_from_snap(self, group, volumes,
                               group_snapshot, snapshots):
        src_cg_snap = self.client.get_snap(group_snapshot.id)
        src_vols = ([snap.volume for snap in snapshots] if snapshots else [])
        return self.copy_luns_in_group(group, volumes, src_cg_snap, src_vols)

    def create_cloned_group(self, group, volumes, source_group, source_vols):
        src_group_snap_name = 'snap_clone_group_{}'.format(source_group.id)
        create_snap_func = functools.partial(self.client.create_cg_snap,
                                             source_group.id,
                                             src_group_snap_name)
        with utils.assure_cleanup(create_snap_func,
                                  self.client.delete_snap,
                                  True) as src_cg_snap:
            LOG.debug('Internal group snapshot for clone is created, '
                      'name: %(name)s, id: %(id)s.',
                      {'name': src_group_snap_name,
                       'id': src_cg_snap.get_id()})
            source_vols = source_vols if source_vols else []
            return self.copy_luns_in_group(group, volumes, src_cg_snap,
                                           source_vols)

    def create_group_snapshot(self, group_snapshot, snapshots):
        self.client.create_cg_snap(group_snapshot.group_id,
                                   snap_name=group_snapshot.id)

        model_update = {'status': fields.GroupStatus.AVAILABLE}
        snapshots_model_update = [{'id': snapshot.id,
                                   'status': fields.SnapshotStatus.AVAILABLE}
                                  for snapshot in snapshots]
        return model_update, snapshots_model_update

    def delete_group_snapshot(self, group_snapshot):
        cg_snap = self.client.get_snap(group_snapshot.id)
        self.client.delete_snap(cg_snap)
        return None, None

    def enable_replication(self, context, group, volumes):
        """Enable the group replication."""

        @cinder_utils.retry(exception.InvalidGroup, interval=20, retries=6)
        def _wait_until_cg_not_replicated(_client, _cg_id):
            cg = _client.get_cg(name=_cg_id)
            if cg.check_cg_is_replicated():
                msg = _('The remote cg (%s) is still in replication status, '
                        'maybe the source cg was just deleted, '
                        'retrying.') % group_id
                LOG.info(msg)
                raise exception.InvalidGroup(reason=msg)

            return cg

        group_update = {}
        group_id = group.id
        if not volumes:
            LOG.warning('There is no Volume in group: %s, cannot enable '
                        'group replication', group_id)
            return group_update, []
        # check whether the group was created as cg in unity
        group_is_cg = utils.group_is_cg(group)
        if not group_is_cg:
            msg = (_('Cannot enable replication on generic group '
                     '%(group_id)s, need to use CG type instead '
                     '(need to enable consistent_group_snapshot_enabled in '
                     'the group type).')
                   % {'group_id': group_id})
            raise exception.InvalidGroupType(reason=msg)

        cg = self.client.get_cg(name=group_id)
        try:
            if not cg.check_cg_is_replicated():
                rep_devices = self.replication_manager.replication_devices
                for backend_id, dst in rep_devices.items():
                    remote_serial_number = dst.adapter.serial_number
                    max_time = dst.max_time_out_of_sync
                    pool_id = dst.destination_pool.get_id()
                    _client = dst.adapter.client
                    remote_system = self.client.get_remote_system(
                        remote_serial_number)
                    # check if remote cg exists and delete it
                    # before enable replication
                    remote_cg = _wait_until_cg_not_replicated(_client,
                                                              group_id)
                    remote_cg.delete()
                    # create cg replication session
                    self.client.create_cg_replication(
                        group_id, pool_id, remote_system, max_time)
                    group_update.update({
                        'replication_status':
                            fields.ReplicationStatus.ENABLED})
            else:
                LOG.info('group: %s is already in replication, no need to '
                         'enable again.', group_id)
        except Exception as e:
            group_update.update({
                'replication_status': fields.ReplicationStatus.ERROR})
            LOG.error("Error enabling replication on group %(group)s. "
                      "Exception received: %(e)s.",
                      {'group': group.id, 'e': e})
        return group_update, None

    def disable_replication(self, context, group, volumes):
        """Disable the group replication."""
        group_update = {}
        group_id = group.id
        if not volumes:
            # Return if empty group
            LOG.warning('There is no Volume in group: %s, cannot disable '
                        'group replication', group_id)
            return group_update, []
        group_is_cg = utils.group_is_cg(group)
        if not group_is_cg:
            msg = (_('Cannot disable replication on generic group '
                     '%(group_id)s, need use CG type instead of '
                     'that (need enable '
                     'consistent_group_snapshot_enabled in '
                     'group type).')
                   % {'group_id': group_id})
            raise exception.InvalidGroupType(reason=msg)
        try:
            if self.client.is_cg_replicated(group_id):
                # delete rep session if exists
                self.client.delete_cg_rep_session(group_id)
            if not self.client.is_cg_replicated(group_id):
                LOG.info('Group is not in replication, '
                         'not need to disable replication again.')

            group_update.update({
                'replication_status': fields.ReplicationStatus.DISABLED})
        except Exception as e:
            group_update.update({
                'replication_status': fields.ReplicationStatus.ERROR})
            LOG.error("Error disabling replication on group %(group)s. "
                      "Exception received: %(e)s.",
                      {'group': group.id, 'e': e})
        return group_update, None

    def failover_replication(self, context, group, volumes,
                             secondary_id):
        """"Fail-over the consistent group."""
        group_update = {}
        volume_update_list = []
        if not volumes:
            # Return if empty group
            return group_update, volume_update_list

        group_is_cg = utils.group_is_cg(group)
        group_id = group.id
        if not group_is_cg:
            msg = (_('Cannot failover replication on generic group '
                     '%(group_id)s, need use CG type instead of '
                     'that (need enable '
                     'consistent_group_snapshot_enabled in '
                     'group type).')
                   % {'group_id': group_id})
            raise exception.InvalidGroupType(reason=msg)

        real_secondary_id = random.choice(
            list(self.replication_manager.replication_devices))

        group_update = {'replication_status': group.replication_status}
        if self.client.is_cg_replicated(group_id):
            try:
                if secondary_id != 'default':
                    try:
                        # Planed failover after sync date when the source unity
                        # is in health status
                        self.client.failover_cg_rep_session(group_id, True)
                    except Exception as ex:
                        LOG.warning('ERROR happened when failover from source '
                                    'unity, issue details: %s. Try failover '
                                    'from target unity', ex)
                        # Something wrong with the source unity, try failover
                        # from target unity without sync date
                        _adapter = self.replication_manager.replication_devices
                        [real_secondary_id].adapter
                        _client = _adapter.client
                        _client.failover_cg_rep_session(group_id, False)
                    rep_status = fields.ReplicationStatus.FAILED_OVER
                else:
                    # start failback when secondary_id is 'default'
                    _adapter = self.replication_manager.replication_devices[
                        real_secondary_id].adapter
                    _client = _adapter.client
                    _client.failback_cg_rep_session(group_id)
                    rep_status = fields.ReplicationStatus.ENABLED
            except Exception as ex:
                rep_status = fields.ReplicationStatus.ERROR
                LOG.error("Error failover replication on group %(group)s. "
                          "Exception received: %(e)s.",
                          {'group': group_id, 'e': ex})

            group_update['replication_status'] = rep_status
            for volume in volumes:
                volume_update = {
                    'id': volume.id,
                    'replication_status': rep_status}
                volume_update_list.append(volume_update)
        return group_update, volume_update_list

    def get_replication_error_status(self, context, groups):
        """The failover only happens manually, no need to update the status."""
        return [], []

    @volume_utils.trace
    def failover(self, volumes, secondary_id=None, groups=None):
        # TODO(ryan) support group failover after group bp merges
        # https://review.opendev.org/#/c/574119/

        if secondary_id is None:
            LOG.debug('No secondary specified when failover. '
                      'Randomly choose a secondary')
            secondary_id = random.choice(
                list(self.replication_manager.replication_devices))
            LOG.debug('Chose %s as secondary', secondary_id)

        is_failback = secondary_id == 'default'

        def _failover_or_back(volume):
            LOG.debug('Failing over volume: %(vol)s to secondary id: '
                      '%(sec_id)s', vol=volume.name, sec_id=secondary_id)
            model_update = {
                'volume_id': volume.id,
                'updates': {}
            }

            if not volume.replication_driver_data:
                LOG.error('Empty replication_driver_data of volume: %s, '
                          'replication session name should be in it.',
                          volume.name)
                return utils.error_replication_status(model_update)
            rep_data = utils.load_replication_data(
                volume.replication_driver_data)

            if is_failback:
                # Failback executed on secondary backend which is currently
                # active.
                _adapter = self.replication_manager.default_device.adapter
                _client = self.replication_manager.active_adapter.client
                rep_name = rep_data[self.replication_manager.active_backend_id]
            else:
                # Failover executed on secondary backend because primary could
                # die.
                _adapter = self.replication_manager.replication_devices[
                    secondary_id].adapter
                _client = _adapter.client
                rep_name = rep_data[secondary_id]

            try:
                rep_session = _client.get_replication_session(name=rep_name)

                if is_failback:
                    _client.failback_replication(rep_session)
                    new_model = _adapter.makeup_model(
                        rep_session.src_resource_id)
                else:
                    _client.failover_replication(rep_session)
                    new_model = _adapter.makeup_model(
                        rep_session.dst_resource_id)

                model_update['updates'].update(new_model)
                self.replication_manager.failover_service(secondary_id)
                return model_update
            except client.ClientReplicationError as ex:
                LOG.error('Failover failed, volume: %(vol)s, secondary id: '
                          '%(sec_id)s, error: %(err)s',
                          vol=volume.name, sec_id=secondary_id, err=ex)
                return utils.error_replication_status(model_update)

        return (secondary_id,
                [_failover_or_back(volume) for volume in volumes],
                [])


class ISCSIAdapter(CommonAdapter):
    protocol = PROTOCOL_ISCSI
    driver_name = 'UnityISCSIDriver'
    driver_volume_type = 'iscsi'

    def get_all_ports(self):
        return self.client.get_ethernet_ports()

    def get_connector_uids(self, connector):
        return utils.extract_iscsi_uids(connector)

    def get_connection_info(self, hlu, host, connector):
        targets = self.client.get_iscsi_target_info(self.allowed_ports)
        if not targets:
            msg = _("There is no accessible iSCSI targets on the system.")
            raise exception.VolumeBackendAPIException(data=msg)
        one_target = random.choice(targets)
        portals = [a['portal'] for a in targets]
        iqns = [a['iqn'] for a in targets]
        data = {
            'target_luns': [hlu] * len(portals),
            'target_iqns': iqns,
            'target_portals': portals,
            'target_lun': hlu,
            'target_portal': one_target['portal'],
            'target_iqn': one_target['iqn'],
        }
        return data


class FCAdapter(CommonAdapter):
    protocol = PROTOCOL_FC
    driver_name = 'UnityFCDriver'
    driver_volume_type = 'fibre_channel'

    def __init__(self, version=None):
        super(FCAdapter, self).__init__(version=version)
        self.lookup_service = None

    def do_setup(self, driver, config):
        super(FCAdapter, self).do_setup(driver, config)
        self.lookup_service = utils.create_lookup_service()

    def get_all_ports(self):
        return self.client.get_fc_ports()

    def get_connector_uids(self, connector):
        return utils.extract_fc_uids(connector)

    @property
    def auto_zone_enabled(self):
        return self.lookup_service is not None

    def get_connection_info(self, hlu, host, connector):
        targets = self.client.get_fc_target_info(
            host, logged_in_only=(not self.auto_zone_enabled),
            allowed_ports=self.allowed_ports)

        if not targets:
            msg = _("There is no accessible fibre channel targets on the "
                    "system.")
            raise exception.VolumeBackendAPIException(data=msg)

        if self.auto_zone_enabled:
            data = self._get_fc_zone_info(connector['wwpns'], targets)
        else:
            data = {
                'target_wwn': targets,
            }
        data['target_lun'] = hlu
        return data

    def filter_targets_by_host(self, host):
        if self.auto_zone_enabled and not host.host_luns:
            return self.client.get_fc_target_info(
                host=host, logged_in_only=False,
                allowed_ports=self.allowed_ports)
        return []

    def get_terminate_connection_info(self, connector, targets):
        # For FC, terminate_connection needs to return data to zone manager
        # which would clean the zone based on the data.
        if targets:
            return self._get_fc_zone_info(connector['wwpns'], targets)
        return {}

    def _get_fc_zone_info(self, initiator_wwns, target_wwns):
        mapping = self.lookup_service.get_device_mapping_from_network(
            initiator_wwns, target_wwns)
        targets, itor_tgt_map = utils.convert_to_itor_tgt_map(mapping)
        return {
            'target_wwn': targets,
            'initiator_target_map': itor_tgt_map,
        }
