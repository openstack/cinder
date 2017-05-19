# Copyright 2016 Infinidat Ltd.
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
INFINIDAT InfiniBox Volume Driver
"""

from contextlib import contextmanager
import functools

import mock
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import units

from cinder import exception
from cinder.i18n import _
from cinder import interface
from cinder import utils
from cinder.volume.drivers.san import san
from cinder.volume import utils as vol_utils
from cinder.zonemanager import utils as fczm_utils

try:
    # capacity is a dependency of infinisdk, so if infinisdk is available
    # then capacity should be available too
    import capacity
    import infinisdk
except ImportError:
    capacity = None
    infinisdk = None


LOG = logging.getLogger(__name__)

VENDOR_NAME = 'INFINIDAT'

infinidat_opts = [
    cfg.StrOpt('infinidat_pool_name',
               help='Name of the pool from which volumes are allocated'),
]

CONF = cfg.CONF
CONF.register_opts(infinidat_opts)


def infinisdk_to_cinder_exceptions(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except infinisdk.core.exceptions.InfiniSDKException as ex:
            # string formatting of 'ex' includes http code and url
            msg = _('Caught exception from infinisdk: %s') % ex
            LOG.exception(msg)
            raise exception.VolumeBackendAPIException(data=msg)
    return wrapper


@interface.volumedriver
class InfiniboxVolumeDriver(san.SanDriver):
    VERSION = '1.1'

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "INFINIDAT_Cinder_CI"

    def __init__(self, *args, **kwargs):
        super(InfiniboxVolumeDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(infinidat_opts)
        self._lookup_service = fczm_utils.create_lookup_service()

    def do_setup(self, context):
        """Driver initialization"""
        if infinisdk is None:
            msg = _("Missing 'infinisdk' python module, ensure the library"
                    " is installed and available.")
            raise exception.VolumeDriverException(message=msg)
        auth = (self.configuration.san_login,
                self.configuration.san_password)
        management_address = self.configuration.san_ip
        self._system = infinisdk.InfiniBox(management_address, auth=auth)
        self._system.login()
        backend_name = self.configuration.safe_get('volume_backend_name')
        self._backend_name = backend_name or self.__class__.__name__
        self._volume_stats = None
        LOG.debug('setup complete')

    def _cleanup_wwpn(self, wwpn):
        return wwpn.replace(':', '')

    def _make_volume_name(self, cinder_volume):
        return 'openstack-vol-%s' % cinder_volume.id

    def _make_snapshot_name(self, cinder_snapshot):
        return 'openstack-snap-%s' % cinder_snapshot.id

    def _make_host_name(self, wwpn):
        wwn_for_name = self._cleanup_wwpn(wwpn)
        return 'openstack-host-%s' % wwn_for_name

    def _get_infinidat_volume_by_name(self, name):
        volume = self._system.volumes.safe_get(name=name)
        if volume is None:
            msg = _('Volume "%s" not found') % name
            LOG.error(msg)
            raise exception.InvalidVolume(reason=msg)
        return volume

    def _get_infinidat_snapshot_by_name(self, name):
        snapshot = self._system.volumes.safe_get(name=name)
        if snapshot is None:
            msg = _('Snapshot "%s" not found') % name
            LOG.error(msg)
            raise exception.InvalidSnapshot(reason=msg)
        return snapshot

    def _get_infinidat_volume(self, cinder_volume):
        volume_name = self._make_volume_name(cinder_volume)
        return self._get_infinidat_volume_by_name(volume_name)

    def _get_infinidat_snapshot(self, cinder_snapshot):
        snap_name = self._make_snapshot_name(cinder_snapshot)
        return self._get_infinidat_snapshot_by_name(snap_name)

    def _get_infinidat_pool(self):
        pool_name = self.configuration.infinidat_pool_name
        pool = self._system.pools.safe_get(name=pool_name)
        if pool is None:
            msg = _('Pool "%s" not found') % pool_name
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)
        return pool

    def _get_or_create_host(self, wwpn):
        host_name = self._make_host_name(wwpn)
        infinidat_host = self._system.hosts.safe_get(name=host_name)
        if infinidat_host is None:
            infinidat_host = self._system.hosts.create(name=host_name)
            infinidat_host.add_port(self._cleanup_wwpn(wwpn))
        return infinidat_host

    def _get_mapping(self, host, volume):
        existing_mapping = host.get_luns()
        for mapping in existing_mapping:
            if mapping.get_volume() == volume:
                return mapping

    def _get_or_create_mapping(self, host, volume):
        mapping = self._get_mapping(host, volume)
        if mapping:
            return mapping
        # volume not mapped. map it
        return host.map_volume(volume)

    def _get_online_fc_ports(self):
        nodes = self._system.components.nodes.get_all()
        for node in nodes:
            for port in node.get_fc_ports():
                if (port.get_link_state().lower() == 'up' and
                   port.get_state() == 'OK'):
                    yield str(port.get_wwpn())

    @fczm_utils.add_fc_zone
    @infinisdk_to_cinder_exceptions
    def initialize_connection(self, volume, connector):
        """Map an InfiniBox volume to the host"""
        volume_name = self._make_volume_name(volume)
        infinidat_volume = self._get_infinidat_volume_by_name(volume_name)
        for wwpn in connector['wwpns']:
            infinidat_host = self._get_or_create_host(wwpn)
            mapping = self._get_or_create_mapping(infinidat_host,
                                                  infinidat_volume)
            lun = mapping.get_lun()

        # Create initiator-target mapping.
        target_wwpns = list(self._get_online_fc_ports())
        target_wwpns, init_target_map = self._build_initiator_target_map(
            connector, target_wwpns)
        return dict(driver_volume_type='fibre_channel',
                    data=dict(target_discovered=False,
                              target_wwn=target_wwpns,
                              target_lun=lun,
                              initiator_target_map=init_target_map))

    @fczm_utils.remove_fc_zone
    @infinisdk_to_cinder_exceptions
    def terminate_connection(self, volume, connector, **kwargs):
        """Unmap an InfiniBox volume from the host"""
        infinidat_volume = self._get_infinidat_volume(volume)
        result_data = dict()
        for wwpn in connector['wwpns']:
            host_name = self._make_host_name(wwpn)
            host = self._system.hosts.safe_get(name=host_name)
            if host is None:
                # not found. ignore.
                continue
            # unmap
            try:
                host.unmap_volume(infinidat_volume)
            except KeyError:
                continue      # volume mapping not found
        # check if the host now doesn't have mappings, to delete host_entry
        # if needed
        if len(host.get_luns()) == 0:
            host.safe_delete()
            # Create initiator-target mapping.
            target_wwpns = list(self._get_online_fc_ports())
            target_wwpns, init_target_map = self._build_initiator_target_map(
                connector, target_wwpns)
            result_data = dict(target_wwn=target_wwpns,
                               initiator_target_map=init_target_map)
        return dict(driver_volume_type='fibre_channel',
                    data=result_data)

    @infinisdk_to_cinder_exceptions
    def get_volume_stats(self, refresh=False):
        if self._volume_stats is None or refresh:
            pool = self._get_infinidat_pool()
            free_capacity_bytes = (pool.get_free_physical_capacity() /
                                   capacity.byte)
            physical_capacity_bytes = (pool.get_physical_capacity() /
                                       capacity.byte)
            free_capacity_gb = float(free_capacity_bytes) / units.Gi
            total_capacity_gb = float(physical_capacity_bytes) / units.Gi
            self._volume_stats = dict(volume_backend_name=self._backend_name,
                                      vendor_name=VENDOR_NAME,
                                      driver_version=self.VERSION,
                                      storage_protocol='FC',
                                      consistencygroup_support='False',
                                      total_capacity_gb=total_capacity_gb,
                                      free_capacity_gb=free_capacity_gb)
        return self._volume_stats

    def _create_volume(self, volume):
        pool = self._get_infinidat_pool()
        volume_name = self._make_volume_name(volume)
        provtype = "THIN" if self.configuration.san_thin_provision else "THICK"
        size = volume.size * capacity.GiB
        return self._system.volumes.create(name=volume_name,
                                           pool=pool,
                                           provtype=provtype,
                                           size=size)

    @infinisdk_to_cinder_exceptions
    def create_volume(self, volume):
        """Create a new volume on the backend."""
        # this is the same as _create_volume but without the return statement
        self._create_volume(volume)

    @infinisdk_to_cinder_exceptions
    def delete_volume(self, volume):
        """Delete a volume from the backend."""
        volume_name = self._make_volume_name(volume)
        try:
            infinidat_volume = self._get_infinidat_volume_by_name(volume_name)
        except exception.InvalidVolume:
            return      # volume not found
        if infinidat_volume.has_children():
            # can't delete a volume that has a live snapshot
            raise exception.VolumeIsBusy(volume_name=volume_name)
        infinidat_volume.safe_delete()

    @infinisdk_to_cinder_exceptions
    def extend_volume(self, volume, new_size):
        """Extend the size of a volume."""
        volume = self._get_infinidat_volume(volume)
        volume.resize(new_size * capacity.GiB)

    @infinisdk_to_cinder_exceptions
    def create_snapshot(self, snapshot):
        """Creates a snapshot."""
        volume = self._get_infinidat_volume(snapshot.volume)
        name = self._make_snapshot_name(snapshot)
        volume.create_snapshot(name=name)

    @contextmanager
    def _device_connect_context(self, volume):
        connector = utils.brick_get_connector_properties()
        connection = self.initialize_connection(volume, connector)
        try:
            yield self._connect_device(connection)
        finally:
            self.terminate_connection(volume, connector)

    @infinisdk_to_cinder_exceptions
    def create_volume_from_snapshot(self, volume, snapshot):
        """Create volume from snapshot.

        InfiniBox does not yet support detached clone so use dd to copy data.
        This could be a lengthy operation.

        - create a clone from snapshot and map it
        - create a volume and map it
        - copy data from clone to volume
        - unmap volume and clone and delete the clone
        """
        infinidat_snapshot = self._get_infinidat_snapshot(snapshot)
        clone_name = self._make_volume_name(volume) + '-internal'
        infinidat_clone = infinidat_snapshot.create_child(name=clone_name)
        # we need a cinder-volume-like object to map the clone by name
        # (which is derived from the cinder id) but the clone is internal
        # so there is no such object. mock one
        clone = mock.Mock(id=str(volume.id) + '-internal')
        try:
            infinidat_volume = self._create_volume(volume)
            try:
                src_ctx = self._device_connect_context(clone)
                dst_ctx = self._device_connect_context(volume)
                with src_ctx as src_dev, dst_ctx as dst_dev:
                    dd_block_size = self.configuration.volume_dd_blocksize
                    vol_utils.copy_volume(src_dev['device']['path'],
                                          dst_dev['device']['path'],
                                          snapshot.volume.size * units.Ki,
                                          dd_block_size,
                                          sparse=True)
            except Exception:
                infinidat_volume.delete()
                raise
        finally:
            infinidat_clone.delete()

    @infinisdk_to_cinder_exceptions
    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        try:
            snapshot = self._get_infinidat_snapshot(snapshot)
        except exception.InvalidSnapshot:
            return      # snapshot not found
        snapshot.safe_delete()

    def _asssert_volume_not_mapped(self, volume):
        # copy is not atomic so we can't clone while the volume is mapped
        infinidat_volume = self._get_infinidat_volume(volume)
        if len(infinidat_volume.get_logical_units()) == 0:
            return

        # volume has mappings
        msg = _("INFINIDAT Cinder driver does not support clone of an "
                "attached volume. "
                "To get this done, create a snapshot from the attached "
                "volume and then create a volume from the snapshot.")
        LOG.error(msg)
        raise exception.VolumeBackendAPIException(data=msg)

    @infinisdk_to_cinder_exceptions
    def create_cloned_volume(self, volume, src_vref):
        """Create a clone from source volume.

        InfiniBox does not yet support detached clone so use dd to copy data.
        This could be a lengthy operation.

        * map source volume
        * create and map new volume
        * copy data from source to new volume
        * unmap both volumes
        """
        self._asssert_volume_not_mapped(src_vref)
        infinidat_volume = self._create_volume(volume)
        try:
            src_ctx = self._device_connect_context(src_vref)
            dst_ctx = self._device_connect_context(volume)
            with src_ctx as src_dev, dst_ctx as dst_dev:
                dd_block_size = self.configuration.volume_dd_blocksize
                vol_utils.copy_volume(src_dev['device']['path'],
                                      dst_dev['device']['path'],
                                      src_vref.size * units.Ki,
                                      dd_block_size,
                                      sparse=True)
        except Exception:
            infinidat_volume.delete()
            raise

    def _build_initiator_target_map(self, connector, all_target_wwns):
        """Build the target_wwns and the initiator target map."""
        target_wwns = []
        init_targ_map = {}

        if self._lookup_service is not None:
            # use FC san lookup.
            dev_map = self._lookup_service.get_device_mapping_from_network(
                connector.get('wwpns'),
                all_target_wwns)

            for fabric_name in dev_map:
                fabric = dev_map[fabric_name]
                target_wwns += fabric['target_port_wwn_list']
                for initiator in fabric['initiator_port_wwn_list']:
                    if initiator not in init_targ_map:
                        init_targ_map[initiator] = []
                    init_targ_map[initiator] += fabric['target_port_wwn_list']
                    init_targ_map[initiator] = list(set(
                        init_targ_map[initiator]))
            target_wwns = list(set(target_wwns))
        else:
            initiator_wwns = connector.get('wwpns', [])
            target_wwns = all_target_wwns

            for initiator in initiator_wwns:
                init_targ_map[initiator] = target_wwns

        return target_wwns, init_targ_map
