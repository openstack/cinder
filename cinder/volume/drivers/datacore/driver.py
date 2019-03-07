# Copyright (c) 2017 DataCore Software Corp. All Rights Reserved.
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

"""Base Driver for DataCore SANsymphony storage array."""

import time

from oslo_config import cfg
from oslo_log import log as logging
from oslo_service import loopingcall
from oslo_utils import excutils
from oslo_utils import units
import six

from cinder import context as cinder_context
from cinder import exception as cinder_exception
from cinder.i18n import _
from cinder import utils as cinder_utils
from cinder.volume import driver
from cinder.volume.drivers.datacore import api
from cinder.volume.drivers.datacore import exception as datacore_exception
from cinder.volume.drivers.datacore import utils as datacore_utils
from cinder.volume.drivers.san import san
from cinder.volume import volume_types


LOG = logging.getLogger(__name__)

datacore_opts = [
    cfg.StrOpt('datacore_disk_type',
               default='single',
               choices=['single', 'mirrored'],
               help='DataCore virtual disk type (single/mirrored). '
                    'Mirrored virtual disks require two storage servers in '
                    'the server group.'),
    cfg.StrOpt('datacore_storage_profile',
               default=None,
               help='DataCore virtual disk storage profile.'),
    cfg.ListOpt('datacore_disk_pools',
                default=[],
                help='List of DataCore disk pools that can be used '
                     'by volume driver.'),
    cfg.IntOpt('datacore_api_timeout',
               default=300,
               min=1,
               help='Seconds to wait for a response from a '
                    'DataCore API call.'),
    cfg.IntOpt('datacore_disk_failed_delay',
               default=15,
               min=0,
               help='Seconds to wait for DataCore virtual '
                    'disk to come out of the "Failed" state.'),
]

CONF = cfg.CONF
CONF.register_opts(datacore_opts)


class DataCoreVolumeDriver(driver.BaseVD):
    """DataCore SANsymphony base volume driver."""

    STORAGE_PROTOCOL = 'N/A'

    AWAIT_DISK_ONLINE_INTERVAL = 10
    AWAIT_SNAPSHOT_ONLINE_INTERVAL = 10
    AWAIT_SNAPSHOT_ONLINE_INITIAL_DELAY = 5

    DATACORE_SINGLE_DISK = 'single'
    DATACORE_MIRRORED_DISK = 'mirrored'

    DATACORE_DISK_TYPE_KEY = 'datacore:disk_type'
    DATACORE_STORAGE_PROFILE_KEY = 'datacore:storage_profile'
    DATACORE_DISK_POOLS_KEY = 'datacore:disk_pools'

    VALID_VOLUME_TYPE_KEYS = (DATACORE_DISK_TYPE_KEY,
                              DATACORE_STORAGE_PROFILE_KEY,
                              DATACORE_DISK_POOLS_KEY,)

    def __init__(self, *args, **kwargs):
        super(DataCoreVolumeDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(san.san_opts)
        self.configuration.append_config_values(datacore_opts)
        self._api = None
        self._default_volume_options = None

    @staticmethod
    def get_driver_options():
        return datacore_opts

    def do_setup(self, context):
        """Perform validations and establish connection to server.

        :param context: Context information
        """

        required_params = [
            'san_ip',
            'san_login',
            'san_password',
        ]
        for param in required_params:
            if not getattr(self.configuration, param, None):
                raise cinder_exception.InvalidInput(_("%s not set.") % param)

        self._api = api.DataCoreClient(
            self.configuration.san_ip,
            self.configuration.san_login,
            self.configuration.san_password,
            self.configuration.datacore_api_timeout)

        disk_type = self.configuration.datacore_disk_type
        if disk_type:
            disk_type = disk_type.lower()
        storage_profile = self.configuration.datacore_storage_profile
        if storage_profile:
            storage_profile = storage_profile.lower()
        disk_pools = self.configuration.datacore_disk_pools
        if disk_pools:
            disk_pools = [pool.lower() for pool in disk_pools]

        self._default_volume_options = {
            self.DATACORE_DISK_TYPE_KEY: disk_type,
            self.DATACORE_STORAGE_PROFILE_KEY: storage_profile,
            self.DATACORE_DISK_POOLS_KEY: disk_pools,
        }

    def check_for_setup_error(self):
        pass

    def get_volume_backend_name(self):
        """Get volume backend name of the volume service.

        :return: Volume backend name
        """

        backend_name = self.configuration.safe_get('volume_backend_name')
        return (backend_name or
                'datacore_' + self.get_storage_protocol().lower())

    def get_storage_protocol(self):
        """Get storage protocol of the volume backend.

        :return: Storage protocol
        """

        return self.STORAGE_PROTOCOL

    def get_volume_stats(self, refresh=False):
        """Obtain status of the volume service.

        :param refresh: Whether to get refreshed information
        """

        if refresh:
            self._update_volume_stats()
        return self._stats

    def create_volume(self, volume):
        """Creates a volume.

        :param volume: Volume object
        :return: Dictionary of changes to the volume object to be persisted
        """

        volume_options = self._get_volume_options(volume)

        disk_type = volume_options[self.DATACORE_DISK_TYPE_KEY]
        if disk_type == self.DATACORE_MIRRORED_DISK:
            logical_disk_count = 2
            virtual_disk_type = 'MultiPathMirrored'
        elif disk_type == self.DATACORE_SINGLE_DISK:
            logical_disk_count = 1
            virtual_disk_type = 'NonMirrored'
        else:
            msg = _("Virtual disk type '%s' is not valid.") % disk_type
            LOG.error(msg)
            raise cinder_exception.VolumeDriverException(message=msg)

        profile_id = self._get_storage_profile_id(
            volume_options[self.DATACORE_STORAGE_PROFILE_KEY])

        pools = datacore_utils.get_distinct_by(
            lambda pool: pool.ServerId,
            self._get_available_disk_pools(
                volume_options[self.DATACORE_DISK_POOLS_KEY]))

        if len(pools) < logical_disk_count:
            msg = _("Suitable disk pools were not found for "
                    "creating virtual disk.")
            LOG.error(msg)
            raise cinder_exception.VolumeDriverException(message=msg)

        disk_size = self._get_size_in_bytes(volume['size'])

        logical_disks = []
        virtual_disk = None
        try:
            for logical_disk_pool in pools[:logical_disk_count]:
                logical_disks.append(
                    self._api.create_pool_logical_disk(
                        logical_disk_pool.Id, 'Striped', disk_size))

            virtual_disk_data = self._api.build_virtual_disk_data(
                volume['id'],
                virtual_disk_type,
                disk_size,
                volume['display_name'],
                profile_id)

            virtual_disk = self._api.create_virtual_disk_ex2(
                virtual_disk_data,
                logical_disks[0].Id,
                logical_disks[1].Id if logical_disk_count == 2 else None,
                True)

            virtual_disk = self._await_virtual_disk_online(virtual_disk.Id)

        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception("Creation of volume %(volume)s failed.",
                              {'volume': volume['id']})
                try:
                    if virtual_disk:
                        self._api.delete_virtual_disk(virtual_disk.Id, True)
                    else:
                        for logical_disk in logical_disks:
                            self._api.delete_logical_disk(logical_disk.Id)
                except datacore_exception.DataCoreException as e:
                    LOG.warning("An error occurred on a cleanup after failed "
                                "creation of volume %(volume)s: %(error)s.",
                                {'volume': volume['id'], 'error': e})

        return {'provider_location': virtual_disk.Id}

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot.

        :param volume: Volume object
        :param snapshot: Snapshot object
        :return: Dictionary of changes to the volume object to be persisted
        """

        return self._create_volume_from(volume, snapshot)

    def create_cloned_volume(self, volume, src_vref):
        """Creates volume clone.

        :param volume: New Volume object
        :param src_vref: Volume object that must be cloned
        :return: Dictionary of changes to the volume object to be persisted
        """

        return self._create_volume_from(volume, src_vref)

    def extend_volume(self, volume, new_size):
        """Extend an existing volume's size.

        :param volume: Volume object
        :param new_size: new size in GB to extend this volume to
        """

        virtual_disk = self._get_virtual_disk_for(volume, raise_not_found=True)
        self._set_virtual_disk_size(virtual_disk,
                                    self._get_size_in_bytes(new_size))

    def delete_volume(self, volume):
        """Deletes a volume.

        :param volume: Volume object
        """

        virtual_disk = self._get_virtual_disk_for(volume)
        if virtual_disk:
            if virtual_disk.IsServed:
                logical_disks = self._api.get_logical_disks()
                logical_units = self._api.get_logical_units()
                target_devices = self._api.get_target_devices()
                logical_disks = [disk.Id for disk in logical_disks
                                 if disk.VirtualDiskId == virtual_disk.Id]
                logical_unit_devices = [unit.VirtualTargetDeviceId
                                        for unit in logical_units
                                        if unit.LogicalDiskId in logical_disks]
                initiator_ports = set(device.InitiatorPortId
                                      for device in target_devices
                                      if device.Id in logical_unit_devices)
                for port in initiator_ports:
                    self._api.unserve_virtual_disks_from_port(
                        port, [virtual_disk.Id])
            self._api.delete_virtual_disk(virtual_disk.Id, True)

    def create_snapshot(self, snapshot):
        """Creates a snapshot.

        :param snapshot: Snapshot object
        :return: Dictionary of changes to the snapshot object to be persisted
        """

        src_virtual_disk = self._get_virtual_disk_for(snapshot['volume'],
                                                      raise_not_found=True)

        volume_options = self._get_volume_options(snapshot['volume'])
        profile_name = volume_options[self.DATACORE_STORAGE_PROFILE_KEY]
        profile_id = self._get_storage_profile_id(profile_name)
        pool_names = volume_options[self.DATACORE_DISK_POOLS_KEY]

        if src_virtual_disk.DiskStatus != 'Online':
            LOG.warning("Attempting to make a snapshot from virtual disk "
                        "%(disk)s that is in %(state)s state.",
                        {'disk': src_virtual_disk.Id,
                         'state': src_virtual_disk.DiskStatus})

        snapshot_virtual_disk = self._create_virtual_disk_copy(
            src_virtual_disk,
            snapshot['id'],
            snapshot['display_name'],
            profile_id=profile_id,
            pool_names=pool_names)

        return {'provider_location': snapshot_virtual_disk.Id}

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot.

        :param snapshot: Snapshot object
        """

        snapshot_virtual_disk = self._get_virtual_disk_for(snapshot)
        if snapshot_virtual_disk:
            self._api.delete_virtual_disk(snapshot_virtual_disk.Id, True)

    def ensure_export(self, context, volume):
        pass

    def create_export(self, context, volume, connector):
        pass

    def remove_export(self, context, volume):
        pass

    def terminate_connection(self, volume, connector, **kwargs):
        """Disallow connection from connector.

        :param volume: Volume object
        :param connector: Connector information
        """

        virtual_disk = self._get_virtual_disk_for(volume)
        if virtual_disk:
            if connector:
                clients = [self._get_client(connector['host'],
                                            create_new=False)]
            else:
                clients = self._api.get_clients()

            server_group = self._get_our_server_group()

            @cinder_utils.synchronized(
                'datacore-backend-%s' % server_group.Id, external=True)
            def unserve_virtual_disk(client_id):
                self._api.unserve_virtual_disks_from_host(
                    client_id, [virtual_disk.Id])

            for client in clients:
                unserve_virtual_disk(client.Id)

    def _update_volume_stats(self):
        performance_data = self._api.get_performance_by_type(
            ['DiskPoolPerformance'])
        total = 0
        available = 0
        reserved = 0
        for performance in performance_data:
            missing_perf_data = []

            if hasattr(performance.PerformanceData, 'BytesTotal'):
                total += performance.PerformanceData.BytesTotal
            else:
                missing_perf_data.append('BytesTotal')

            if hasattr(performance.PerformanceData, 'BytesAvailable'):
                available += performance.PerformanceData.BytesAvailable
            else:
                missing_perf_data.append('BytesAvailable')

            if hasattr(performance.PerformanceData, 'BytesReserved'):
                reserved += performance.PerformanceData.BytesReserved
            else:
                missing_perf_data.append('BytesReserved')

            if missing_perf_data:
                LOG.warning("Performance data %(data)s is missing for "
                            "disk pool %(pool)s",
                            {'data': missing_perf_data,
                             'pool': performance.ObjectId})
        provisioned = 0
        logical_disks = self._api.get_logical_disks()
        for disk in logical_disks:
            if getattr(disk, 'PoolId', None):
                provisioned += disk.Size.Value
        total_capacity_gb = self._get_size_in_gigabytes(total)
        free = available + reserved
        free_capacity_gb = self._get_size_in_gigabytes(free)
        provisioned_capacity_gb = self._get_size_in_gigabytes(provisioned)
        reserved_percentage = 100.0 * reserved / total if total else 0.0
        ratio = self.configuration.max_over_subscription_ratio
        stats_data = {
            'vendor_name': 'DataCore',
            'QoS_support': False,
            'volume_backend_name': self.get_volume_backend_name(),
            'driver_version': self.get_version(),
            'storage_protocol': self.get_storage_protocol(),
            'total_capacity_gb': total_capacity_gb,
            'free_capacity_gb': free_capacity_gb,
            'provisioned_capacity_gb': provisioned_capacity_gb,
            'reserved_percentage': reserved_percentage,
            'max_over_subscription_ratio': ratio,
            'thin_provisioning_support': True,
            'thick_provisioning_support': False,
        }
        self._stats = stats_data

    def _get_our_server_group(self):
        server_group = datacore_utils.get_first(lambda group: group.OurGroup,
                                                self._api.get_server_groups())

        return server_group

    def _get_volume_options_from_type(self, type_id, default_options):
        options = dict(default_options.items())
        if type_id:
            admin_context = cinder_context.get_admin_context()
            volume_type = volume_types.get_volume_type(admin_context, type_id)
            specs = dict(volume_type).get('extra_specs')

            for key, value in six.iteritems(specs):
                if key in self.VALID_VOLUME_TYPE_KEYS:
                    if key == self.DATACORE_DISK_POOLS_KEY:
                        options[key] = [v.strip().lower()
                                        for v in value.split(',')]
                    else:
                        options[key] = value.lower()

        return options

    def _get_volume_options(self, volume):
        type_id = volume['volume_type_id']

        volume_options = self._get_volume_options_from_type(
            type_id, self._default_volume_options)

        return volume_options

    def _get_online_servers(self):
        servers = self._api.get_servers()
        online_servers = [server for server in servers
                          if server.State == 'Online']
        return online_servers

    def _get_available_disk_pools(self, disk_pool_names=None):
        online_servers = [server.Id for server in self._get_online_servers()]

        pool_performance = {
            performance.ObjectId: performance.PerformanceData for performance
            in self._api.get_performance_by_type(['DiskPoolPerformance'])}

        disk_pools = self._api.get_disk_pools()

        lower_disk_pool_names = ([name.lower() for name in disk_pool_names]
                                 if disk_pool_names else [])

        available_disk_pools = [
            pool for pool in disk_pools
            if (self._is_pool_healthy(pool, pool_performance, online_servers)
                and (not lower_disk_pool_names
                     or pool.Caption.lower() in lower_disk_pool_names))]

        available_disk_pools.sort(
            key=lambda p: pool_performance[p.Id].BytesAvailable, reverse=True)

        return available_disk_pools

    def _get_virtual_disk_for(self, obj, raise_not_found=False):
        disk_id = obj.get('provider_location')

        virtual_disk = datacore_utils.get_first_or_default(
            lambda disk: disk.Id == disk_id,
            self._api.get_virtual_disks(),
            None)
        if not virtual_disk:
            msg = (_("Virtual disk not found for %(object)s %(object_id)s.")
                   % {'object': obj.__class__.__name__.lower(),
                      'object_id': obj['id']})
            if raise_not_found:
                LOG.error(msg)
                raise cinder_exception.VolumeDriverException(message=msg)
            else:
                LOG.warning(msg)

        return virtual_disk

    def _set_virtual_disk_size(self, virtual_disk, new_size):
        return self._api.set_virtual_disk_size(virtual_disk.Id, new_size)

    def _get_storage_profile(self, profile_name, raise_not_found=False):
        profiles = self._api.get_storage_profiles()
        profile = datacore_utils.get_first_or_default(
            lambda p: p.Caption.lower() == profile_name.lower(),
            profiles,
            None)
        if not profile and raise_not_found:
            msg = (_("Specified storage profile %s not found.")
                   % profile_name)
            LOG.error(msg)
            raise cinder_exception.VolumeDriverException(message=msg)

        return profile

    def _get_storage_profile_id(self, profile_name):
        profile_id = None
        if profile_name:
            profile = self._get_storage_profile(profile_name,
                                                raise_not_found=True)
            profile_id = profile.Id
        return profile_id

    def _await_virtual_disk_online(self, virtual_disk_id):
        def inner(start_time):
            disk_failed_delay = self.configuration.datacore_disk_failed_delay
            virtual_disk = datacore_utils.get_first(
                lambda disk: disk.Id == virtual_disk_id,
                self._api.get_virtual_disks())
            if virtual_disk.DiskStatus == 'Online':
                raise loopingcall.LoopingCallDone(virtual_disk)
            elif (virtual_disk.DiskStatus != 'FailedRedundancy'
                  and time.time() - start_time >= disk_failed_delay):
                msg = (_("Virtual disk %(disk)s did not come out of the "
                         "%(state)s state after %(timeout)s seconds.")
                       % {'disk': virtual_disk.Id,
                          'state': virtual_disk.DiskStatus,
                          'timeout': disk_failed_delay})
                LOG.error(msg)
                raise cinder_exception.VolumeDriverException(message=msg)

        inner_loop = loopingcall.FixedIntervalLoopingCall(inner, time.time())
        return inner_loop.start(self.AWAIT_DISK_ONLINE_INTERVAL).wait()

    def _create_volume_from(self, volume, src_obj):
        src_virtual_disk = self._get_virtual_disk_for(src_obj,
                                                      raise_not_found=True)

        if src_virtual_disk.DiskStatus != 'Online':
            LOG.warning("Attempting to create a volume from virtual disk "
                        "%(disk)s that is in %(state)s state.",
                        {'disk': src_virtual_disk.Id,
                         'state': src_virtual_disk.DiskStatus})

        volume_options = self._get_volume_options(volume)
        profile_id = self._get_storage_profile_id(
            volume_options[self.DATACORE_STORAGE_PROFILE_KEY])
        pool_names = volume_options[self.DATACORE_DISK_POOLS_KEY]

        volume_virtual_disk = self._create_virtual_disk_copy(
            src_virtual_disk,
            volume['id'],
            volume['display_name'],
            profile_id=profile_id,
            pool_names=pool_names)

        volume_logical_disk = datacore_utils.get_first(
            lambda disk: disk.VirtualDiskId == volume_virtual_disk.Id,
            self._api.get_logical_disks())

        try:
            volume_virtual_disk = self._set_virtual_disk_size(
                volume_virtual_disk,
                self._get_size_in_bytes(volume['size']))

            disk_type = volume_options[self.DATACORE_DISK_TYPE_KEY]
            if disk_type == self.DATACORE_MIRRORED_DISK:
                pools = self._get_available_disk_pools(pool_names)
                selected_pool = datacore_utils.get_first_or_default(
                    lambda pool: (
                        pool.ServerId != volume_logical_disk.ServerHostId
                        and pool.Id != volume_logical_disk.PoolId),
                    pools,
                    None)
                if selected_pool:
                    logical_disk = self._api.create_pool_logical_disk(
                        selected_pool.Id,
                        'Striped',
                        volume_virtual_disk.Size.Value)
                    self._api.bind_logical_disk(volume_virtual_disk.Id,
                                                logical_disk.Id,
                                                'Second',
                                                True,
                                                False,
                                                True)
                else:
                    msg = _("Can not create mirrored virtual disk. "
                            "Suitable disk pools not found.")
                    LOG.error(msg)
                    raise cinder_exception.VolumeDriverException(message=msg)

            volume_virtual_disk = self._await_virtual_disk_online(
                volume_virtual_disk.Id)

        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception("Creation of volume %(volume)s failed.",
                              {'volume': volume['id']})
                try:
                    self._api.delete_virtual_disk(volume_virtual_disk.Id, True)
                except datacore_exception.DataCoreException as e:
                    LOG.warning("An error occurred on a cleanup after failed "
                                "creation of volume %(volume)s: %(error)s.",
                                {'volume': volume['id'], 'error': e})

        return {'provider_location': volume_virtual_disk.Id}

    def _create_full_snapshot(self, description, name, pool_names, profile_id,
                              src_virtual_disk):
        pools = self._get_available_disk_pools(pool_names)
        destination_pool = datacore_utils.get_first_or_default(
            lambda pool: (pool.ServerId == src_virtual_disk.FirstHostId
                          or pool.ServerId == src_virtual_disk.SecondHostId),
            pools,
            None)

        if not destination_pool:
            msg = _("Suitable snapshot destination disk pool not found for "
                    "virtual disk %s.") % src_virtual_disk.Id
            LOG.error(msg)
            raise cinder_exception.VolumeDriverException(message=msg)
        server = datacore_utils.get_first(
            lambda srv: srv.Id == destination_pool.ServerId,
            self._api.get_servers())
        if not server.SnapshotMapStorePoolId:
            self._api.designate_map_store(destination_pool.Id)
        snapshot = self._api.create_snapshot(src_virtual_disk.Id,
                                             name,
                                             description,
                                             destination_pool.Id,
                                             'Full',
                                             False,
                                             profile_id)
        return snapshot

    def _await_snapshot_migrated(self, snapshot_id):
        def inner():
            snapshot_data = datacore_utils.get_first(
                lambda snapshot: snapshot.Id == snapshot_id,
                self._api.get_snapshots())
            if snapshot_data.State == 'Migrated':
                raise loopingcall.LoopingCallDone(snapshot_data)
            elif (snapshot_data.State != 'Healthy'
                  and snapshot_data.Failure != 'NoFailure'):
                msg = (_("Full migration of snapshot %(snapshot)s failed. "
                         "Snapshot is in %(state)s state.")
                       % {'snapshot': snapshot_data.Id,
                          'state': snapshot_data.State})
                LOG.error(msg)
                raise cinder_exception.VolumeDriverException(message=msg)

        loop = loopingcall.FixedIntervalLoopingCall(inner)
        return loop.start(self.AWAIT_SNAPSHOT_ONLINE_INTERVAL,
                          self.AWAIT_SNAPSHOT_ONLINE_INITIAL_DELAY).wait()

    def _create_virtual_disk_copy(self, src_virtual_disk, name, description,
                                  profile_id=None, pool_names=None):
        snapshot = self._create_full_snapshot(
            description, name, pool_names, profile_id, src_virtual_disk)

        try:
            snapshot = self._await_snapshot_migrated(snapshot.Id)
            self._api.delete_snapshot(snapshot.Id)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception("Split operation failed for snapshot "
                              "%(snapshot)s.", {'snapshot': snapshot.Id})
                try:
                    logical_disk_copy = datacore_utils.get_first(
                        lambda disk: (
                            disk.Id == snapshot.DestinationLogicalDiskId),
                        self._api.get_logical_disks())

                    virtual_disk_copy = datacore_utils.get_first(
                        lambda disk: (
                            disk.Id == logical_disk_copy.VirtualDiskId),
                        self._api.get_virtual_disks())

                    self._api.delete_virtual_disk(virtual_disk_copy.Id, True)
                except datacore_exception.DataCoreException as e:
                    LOG.warning("An error occurred on a cleanup after failed "
                                "split of snapshot %(snapshot)s: %(error)s.",
                                {'snapshot': snapshot.Id, 'error': e})

        logical_disk_copy = datacore_utils.get_first(
            lambda disk: disk.Id == snapshot.DestinationLogicalDiskId,
            self._api.get_logical_disks())

        virtual_disk_copy = datacore_utils.get_first(
            lambda disk: disk.Id == logical_disk_copy.VirtualDiskId,
            self._api.get_virtual_disks())

        return virtual_disk_copy

    def _get_client(self, name, create_new=False):
        client_hosts = self._api.get_clients()

        client = datacore_utils.get_first_or_default(
            lambda host: host.HostName == name, client_hosts, None)

        if create_new:
            if not client:
                client = self._api.register_client(
                    name, None, 'Other', 'PreferredServer', None)
            self._api.set_client_capabilities(client.Id, True, True)

        return client

    @staticmethod
    def _is_pool_healthy(pool, pool_performance, online_servers):
        if (pool.PoolStatus == 'Running'
                and hasattr(pool_performance[pool.Id], 'BytesAvailable')
                and pool.ServerId in online_servers):
            return True
        return False

    @staticmethod
    def _get_size_in_bytes(size_in_gigabytes):
        return size_in_gigabytes * units.Gi

    @staticmethod
    def _get_size_in_gigabytes(size_in_bytes):
        return size_in_bytes / float(units.Gi)
