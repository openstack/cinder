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
from cinder import utils as cinder_utils
from cinder.volume.drivers.dell_emc.unity import client
from cinder.volume.drivers.dell_emc.unity import utils
from cinder.volume import utils as vol_utils

storops = importutils.try_import('storops')
if storops:
    from storops import exception as storops_ex
else:
    # Set storops_ex to be None for unit test
    storops_ex = None

LOG = logging.getLogger(__name__)

PROTOCOL_FC = 'FC'
PROTOCOL_ISCSI = 'iSCSI'


class VolumeParams(object):
    def __init__(self, adapter, volume):
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
            provision = utils.get_extra_spec(self._volume, 'provisioning:type')
            support = utils.get_extra_spec(self._volume,
                                           'thick_provisioning_support')
            self._is_thick = (provision == 'thick' and support == '<is> True')
        return self._is_thick

    @property
    def is_compressed(self):
        if self._is_compressed is None:
            provision = utils.get_extra_spec(self._volume, 'provisioning:type')
            compression = utils.get_extra_spec(self._volume,
                                               'compression_support')
            if provision == 'compressed' and compression == '<is> True':
                self._is_compressed = True
        return self._is_compressed

    @is_compressed.setter
    def is_compressed(self, value):
        self._is_compressed = value

    def __eq__(self, other):
        return (self.volume_id == other.volume_id and
                self.name == other.name and
                self.size == other.size and
                self.io_limit_policy == other.io_limit_policy and
                self.is_thick == other.is_thick and
                self.is_compressed == other.is_compressed)


class CommonAdapter(object):
    protocol = 'unknown'
    driver_name = 'UnityAbstractDriver'
    driver_volume_type = 'unknown'

    def __init__(self, version=None):
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

    def do_setup(self, driver, conf):
        self.driver = driver
        self.config = self.normalize_config(conf)
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

    def makeup_model(self, lun, is_snap_lun=False):
        lun_type = 'snap_lun' if is_snap_lun else 'lun'
        location = self._build_provider_location(lun_id=lun.get_id(),
                                                 lun_type=lun_type)
        return {
            'provider_location': location,
            'provider_id': lun.get_id()
        }

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
            'is_compressed': params.is_compressed
        }

        LOG.info('Create Volume: %(name)s, size: %(size)s, description: '
                 '%(description)s, pool: %(pool)s, io limit policy: '
                 '%(io_limit_policy)s, thick: %(is_thick)s, '
                 '%(is_compressed)s.', log_params)

        return self.makeup_model(
            self.client.create_lun(name=params.name,
                                   size=params.size,
                                   pool=params.pool,
                                   description=params.description,
                                   io_limit_policy=params.io_limit_policy,
                                   is_thin=False if params.is_thick else None,
                                   is_compressed=params.is_compressed))

    def delete_volume(self, volume):
        lun_id = self.get_lun_id(volume)
        if lun_id is None:
            LOG.info('Backend LUN not found, skipping the deletion. '
                     'Volume: %(volume_name)s.',
                     {'volume_name': volume.name})
        else:
            self.client.delete_lun(lun_id)

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

    @cinder_utils.trace
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

    @cinder_utils.trace
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

    def update_volume_stats(self):
        return {
            'volume_backend_name': self.volume_backend_name,
            'storage_protocol': self.protocol,
            'thin_provisioning_support': True,
            'thick_provisioning_support': True,
            'pools': self.get_pools_stats(),
        }

    def get_pools_stats(self):
        self.storage_pools_map = self.get_managed_pools()
        return [self._get_pool_stats(pool) for pool in self.pools]

    @property
    def pools(self):
        return self.storage_pools_map.values()

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
            'thin_provisioning_support': True,
            'thick_provisioning_support': True,
            'compression_support': pool.is_all_flash,
            'max_over_subscription_ratio': (
                self.max_over_subscription_ratio),
            'multiattach': True
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
            conn_props = cinder_utils.brick_get_connector_properties()

            with self._connect_resource(dest_lun, conn_props,
                                        vol_params.volume_id) as dest_info, \
                    self._connect_resource(src_snap, conn_props,
                                           src_id) as src_info:
                if src_lun is None:
                    # If size is not specified, need to get the size from LUN
                    # of snapshot.
                    lun = self.client.get_lun(
                        lun_id=src_snap.storage_resource.get_id())
                    size_in_m = utils.byte_to_mib(lun.size_total)
                else:
                    size_in_m = utils.byte_to_mib(src_lun.size_total)
                vol_utils.copy_volume(
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
        return self.makeup_model(
            self._thin_clone(VolumeParams(self, volume), snap),
            is_snap_lun=True)

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
                return self.makeup_model(lun)
            else:
                lun = self._thin_clone(vol_params, src_snap, src_lun=src_lun)
                return self.makeup_model(lun, is_snap_lun=True)

    def get_pool_name(self, volume):
        return self.client.get_pool_name(volume.name)

    def get_pool_id_by_name(self, name):
        return self.client.get_pool_id_by_name(name=name)

    @cinder_utils.trace
    def initialize_connection_snapshot(self, snapshot, connector):
        snap = self.client.get_snap(snapshot.name)
        return self._initialize_connection(snap, connector, snapshot.id)

    @cinder_utils.trace
    def terminate_connection_snapshot(self, snapshot, connector):
        snap = self.client.get_snap(snapshot.name)
        return self._terminate_connection(snap, connector)

    @cinder_utils.trace
    def restore_snapshot(self, volume, snapshot):
        return self.client.restore_snapshot(snapshot.name)

    def migrate_volume(self, volume, host):
        """Leverage the Unity move session functionality.

        This method is invoked at the source backend.
        """
        log_params = {
            'name': volume.name,
            'src_host': volume.host,
            'dest_host': host['host']
        }
        LOG.info('Migrate Volume: %(name)s, host: %(src_host)s, destination: '
                 '%(dest_host)s', log_params)

        src_backend = utils.get_backend_name_from_volume(volume)
        dest_backend = utils.get_backend_name_from_host(host)

        if src_backend != dest_backend:
            LOG.debug('Cross-backends migration not supported by Unity '
                      'driver. Falling back to host-assisted migration.')
            return False, None

        lun_id = self.get_lun_id(volume)
        dest_pool_name = utils.get_pool_name_from_host(host)
        dest_pool_id = self.get_pool_id_by_name(dest_pool_name)

        if self.client.migrate_lun(lun_id, dest_pool_id):
            LOG.debug('Volume migrated successfully.')
            model_update = {}
            return True, model_update

        LOG.debug('Volume migrated failed. Falling back to '
                  'host-assisted migration.')
        return False, None


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
