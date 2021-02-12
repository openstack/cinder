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
"""INFINIDAT InfiniBox Volume Driver."""

from contextlib import contextmanager
import functools
import platform
import socket
from unittest import mock

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import units

from cinder import coordination
from cinder import exception
from cinder.i18n import _
from cinder import interface
from cinder.objects import fields
from cinder import version
from cinder.volume import configuration
from cinder.volume.drivers.san import san
from cinder.volume import volume_types
from cinder.volume import volume_utils
from cinder.zonemanager import utils as fczm_utils

try:
    # we check that infinisdk is installed. the other imported modules
    # are dependencies, so if any of the dependencies are not importable
    # we assume infinisdk is not installed
    import capacity
    from infi.dtypes import iqn
    from infi.dtypes import wwn
    import infinisdk
except ImportError:
    from oslo_utils import units as capacity
    infinisdk = None
    iqn = None
    wwn = None


LOG = logging.getLogger(__name__)

VENDOR_NAME = 'INFINIDAT'
BACKEND_QOS_CONSUMERS = frozenset(['back-end', 'both'])
QOS_MAX_IOPS = 'maxIOPS'
QOS_MAX_BWS = 'maxBWS'

# Max retries for the REST API client in case of a failure:
_API_MAX_RETRIES = 5
_INFINIDAT_CINDER_IDENTIFIER = (
    "cinder/%s" % version.version_info.release_string())

infinidat_opts = [
    cfg.StrOpt('infinidat_pool_name',
               help='Name of the pool from which volumes are allocated'),
    # We can't use the existing "storage_protocol" option because its default
    # is "iscsi", but for backward-compatibility our default must be "fc"
    cfg.StrOpt('infinidat_storage_protocol',
               ignore_case=True,
               default='fc',
               choices=['iscsi', 'fc'],
               help='Protocol for transferring data between host and '
                    'storage back-end.'),
    cfg.ListOpt('infinidat_iscsi_netspaces',
                default=[],
                help='List of names of network spaces to use for iSCSI '
                     'connectivity'),
    cfg.BoolOpt('infinidat_use_compression',
                default=False,
                help='Specifies whether to turn on compression for newly '
                     'created volumes.'),
]

CONF = cfg.CONF
CONF.register_opts(infinidat_opts, group=configuration.SHARED_CONF_GROUP)


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
class InfiniboxVolumeDriver(san.SanISCSIDriver):
    """INFINIDAT InfiniBox Cinder driver.

    Version history:

    .. code-block:: none

        1.0 - initial release
        1.1 - switched to use infinisdk package
        1.2 - added support for iSCSI protocol
        1.3 - added generic volume groups support
        1.4 - added support for QoS
        1.5 - added support for volume compression
        1.6 - added support for volume multi-attach

    """

    VERSION = '1.6'

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "INFINIDAT_CI"

    def __init__(self, *args, **kwargs):
        super(InfiniboxVolumeDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(infinidat_opts)
        self._lookup_service = fczm_utils.create_lookup_service()

    @classmethod
    def get_driver_options(cls):
        additional_opts = cls._get_oslo_driver_opts(
            'san_ip', 'san_login', 'san_password', 'use_chap_auth',
            'chap_username', 'chap_password', 'san_thin_provision',
            'use_multipath_for_image_xfer', 'enforce_multipath_for_image_xfer',
            'num_volume_device_scan_tries', 'volume_dd_blocksize',
            'max_over_subscription_ratio')
        return infinidat_opts + additional_opts

    def _setup_and_get_system_object(self, management_address, auth):
        system = infinisdk.InfiniBox(management_address, auth=auth)
        system.api.add_auto_retry(
            lambda e: isinstance(
                e, infinisdk.core.exceptions.APITransportFailure) and
            "Interrupted system call" in e.error_desc, _API_MAX_RETRIES)
        system.api.set_source_identifier(_INFINIDAT_CINDER_IDENTIFIER)
        system.login()
        return system

    def do_setup(self, context):
        """Driver initialization"""
        if infinisdk is None:
            msg = _("Missing 'infinisdk' python module, ensure the library"
                    " is installed and available.")
            raise exception.VolumeDriverException(message=msg)
        auth = (self.configuration.san_login,
                self.configuration.san_password)
        self.management_address = self.configuration.san_ip
        self._system = (
            self._setup_and_get_system_object(self.management_address, auth))
        backend_name = self.configuration.safe_get('volume_backend_name')
        self._backend_name = backend_name or self.__class__.__name__
        self._volume_stats = None
        if self.configuration.infinidat_storage_protocol.lower() == 'iscsi':
            self._protocol = 'iSCSI'
            if len(self.configuration.infinidat_iscsi_netspaces) == 0:
                msg = _('No iSCSI network spaces configured')
                raise exception.VolumeDriverException(message=msg)
        else:
            self._protocol = 'FC'
        if (self.configuration.infinidat_use_compression and
           not self._system.compat.has_compression()):
            # InfiniBox systems support compression only from v3.0 and up
            msg = _('InfiniBox system does not support volume compression.\n'
                    'Compression is available on InfiniBox 3.0 onward.\n'
                    'Please disable volume compression by setting '
                    'infinidat_use_compression to False in the Cinder '
                    'configuration file.')
            raise exception.VolumeDriverException(message=msg)
        LOG.debug('setup complete')

    def validate_connector(self, connector):
        required = 'initiator' if self._protocol == 'iSCSI' else 'wwpns'
        if required not in connector:
            LOG.error('The volume driver requires %(data)s '
                      'in the connector.', {'data': required})
            raise exception.InvalidConnectorException(missing=required)

    def _make_volume_name(self, cinder_volume):
        return 'openstack-vol-%s' % cinder_volume.id

    def _make_snapshot_name(self, cinder_snapshot):
        return 'openstack-snap-%s' % cinder_snapshot.id

    def _make_host_name(self, port):
        return 'openstack-host-%s' % str(port).replace(":", ".")

    def _make_cg_name(self, cinder_group):
        return 'openstack-cg-%s' % cinder_group.id

    def _make_group_snapshot_name(self, cinder_group_snap):
        return 'openstack-group-snap-%s' % cinder_group_snap.id

    def _set_cinder_object_metadata(self, infinidat_object, cinder_object):
        data = {"system": "openstack",
                "openstack_version": version.version_info.release_string(),
                "cinder_id": cinder_object.id,
                "cinder_name": cinder_object.name,
                "host.created_by": _INFINIDAT_CINDER_IDENTIFIER}
        infinidat_object.set_metadata_from_dict(data)

    def _set_host_metadata(self, infinidat_object):
        data = {"system": "openstack",
                "openstack_version": version.version_info.release_string(),
                "hostname": socket.gethostname(),
                "platform": platform.platform(),
                "host.created_by": _INFINIDAT_CINDER_IDENTIFIER}
        infinidat_object.set_metadata_from_dict(data)

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

    def _get_infinidat_cg(self, cinder_group):
        group_name = self._make_cg_name(cinder_group)
        infinidat_cg = self._system.cons_groups.safe_get(name=group_name)
        if infinidat_cg is None:
            msg = _('Consistency group "%s" not found') % group_name
            LOG.error(msg)
            raise exception.InvalidGroup(message=msg)
        return infinidat_cg

    def _get_or_create_host(self, port):
        host_name = self._make_host_name(port)
        infinidat_host = self._system.hosts.safe_get(name=host_name)
        if infinidat_host is None:
            infinidat_host = self._system.hosts.create(name=host_name)
            infinidat_host.add_port(port)
            self._set_host_metadata(infinidat_host)
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

    def _get_backend_qos_specs(self, cinder_volume):
        type_id = cinder_volume.volume_type_id
        if type_id is None:
            return None
        qos_specs = volume_types.get_volume_type_qos_specs(type_id)
        if qos_specs is None:
            return None
        qos_specs = qos_specs['qos_specs']
        if qos_specs is None:
            return None
        consumer = qos_specs['consumer']
        # Front end QoS specs are handled by nova. We ignore them here.
        if consumer not in BACKEND_QOS_CONSUMERS:
            return None
        max_iops = qos_specs['specs'].get(QOS_MAX_IOPS)
        max_bws = qos_specs['specs'].get(QOS_MAX_BWS)
        if max_iops is None and max_bws is None:
            return None
        return {
            'id': qos_specs['id'],
            QOS_MAX_IOPS: max_iops,
            QOS_MAX_BWS: max_bws,
        }

    def _get_or_create_qos_policy(self, qos_specs):
        qos_policy = self._system.qos_policies.safe_get(name=qos_specs['id'])
        if qos_policy is None:
            qos_policy = self._system.qos_policies.create(
                name=qos_specs['id'],
                type="VOLUME",
                max_ops=qos_specs[QOS_MAX_IOPS],
                max_bps=qos_specs[QOS_MAX_BWS])
        return qos_policy

    def _set_qos(self, cinder_volume, infinidat_volume):
        if (hasattr(self._system.compat, "has_qos") and
           self._system.compat.has_qos()):
            qos_specs = self._get_backend_qos_specs(cinder_volume)
            if qos_specs:
                policy = self._get_or_create_qos_policy(qos_specs)
                policy.assign_entity(infinidat_volume)

    def _get_online_fc_ports(self):
        nodes = self._system.components.nodes.get_all()
        for node in nodes:
            for port in node.get_fc_ports():
                if (port.get_link_state().lower() == 'up' and
                   port.get_state() == 'OK'):
                    yield str(port.get_wwpn())

    def _initialize_connection_fc(self, volume, connector):
        volume_name = self._make_volume_name(volume)
        infinidat_volume = self._get_infinidat_volume_by_name(volume_name)
        ports = [wwn.WWN(wwpn) for wwpn in connector['wwpns']]
        for port in ports:
            infinidat_host = self._get_or_create_host(port)
            mapping = self._get_or_create_mapping(infinidat_host,
                                                  infinidat_volume)
            lun = mapping.get_lun()
        # Create initiator-target mapping.
        target_wwpns = list(self._get_online_fc_ports())
        target_wwpns, init_target_map = self._build_initiator_target_map(
            connector, target_wwpns)
        conn_info = dict(driver_volume_type='fibre_channel',
                         data=dict(target_discovered=False,
                                   target_wwn=target_wwpns,
                                   target_lun=lun,
                                   initiator_target_map=init_target_map))
        fczm_utils.add_fc_zone(conn_info)
        return conn_info

    def _get_iscsi_network_space(self, netspace_name):
        netspace = self._system.network_spaces.safe_get(
            service='ISCSI_SERVICE',
            name=netspace_name)
        if netspace is None:
            msg = (_('Could not find iSCSI network space with name "%s"') %
                   netspace_name)
            raise exception.VolumeDriverException(message=msg)
        return netspace

    def _get_iscsi_portal(self, netspace):
        for netpsace_interface in netspace.get_ips():
            if netpsace_interface.enabled:
                port = netspace.get_properties().iscsi_tcp_port
                return "%s:%s" % (netpsace_interface.ip_address, port)
        # if we get here it means there are no enabled ports
        msg = (_('No available interfaces in iSCSI network space %s') %
               netspace.get_name())
        raise exception.VolumeDriverException(message=msg)

    def _initialize_connection_iscsi(self, volume, connector):
        volume_name = self._make_volume_name(volume)
        infinidat_volume = self._get_infinidat_volume_by_name(volume_name)
        port = iqn.IQN(connector['initiator'])
        infinidat_host = self._get_or_create_host(port)
        if self.configuration.use_chap_auth:
            chap_username = (self.configuration.chap_username or
                             volume_utils.generate_username())
            chap_password = (self.configuration.chap_password or
                             volume_utils.generate_password())
            infinidat_host.update_fields(
                security_method='CHAP',
                security_chap_inbound_username=chap_username,
                security_chap_inbound_secret=chap_password)
        mapping = self._get_or_create_mapping(infinidat_host,
                                              infinidat_volume)
        lun = mapping.get_lun()
        netspace_names = self.configuration.infinidat_iscsi_netspaces
        target_portals = []
        target_iqns = []
        target_luns = []
        for netspace_name in netspace_names:
            netspace = self._get_iscsi_network_space(netspace_name)
            target_portals.append(self._get_iscsi_portal(netspace))
            target_iqns.append(netspace.get_properties().iscsi_iqn)
            target_luns.append(lun)

        result_data = dict(target_discovered=True,
                           target_portal=target_portals[0],
                           target_iqn=target_iqns[0],
                           target_lun=target_luns[0],
                           target_portals=target_portals,
                           target_iqns=target_iqns,
                           target_luns=target_luns)
        if self.configuration.use_chap_auth:
            result_data.update(dict(auth_method='CHAP',
                                    auth_username=chap_username,
                                    auth_password=chap_password))
        return dict(driver_volume_type='iscsi',
                    data=result_data)

    def _get_ports_from_connector(self, infinidat_volume, connector):
        if connector is None:
            # If no connector was provided it is a force-detach - remove all
            # host connections for the volume
            if self._protocol == 'FC':
                port_cls = wwn.WWN
            else:
                port_cls = iqn.IQN
            ports = []
            for lun_mapping in infinidat_volume.get_logical_units():
                host_ports = lun_mapping.get_host().get_ports()
                host_ports = [port for port in host_ports
                              if isinstance(port, port_cls)]
                ports.extend(host_ports)
        elif self._protocol == 'FC':
            ports = [wwn.WWN(wwpn) for wwpn in connector['wwpns']]
        else:
            ports = [iqn.IQN(connector['initiator'])]
        return ports

    @infinisdk_to_cinder_exceptions
    @coordination.synchronized('infinidat-{self.management_address}-lock')
    def initialize_connection(self, volume, connector):
        """Map an InfiniBox volume to the host"""
        if self._protocol == 'FC':
            return self._initialize_connection_fc(volume, connector)
        else:
            return self._initialize_connection_iscsi(volume, connector)

    @infinisdk_to_cinder_exceptions
    @coordination.synchronized('infinidat-{self.management_address}-lock')
    def terminate_connection(self, volume, connector, **kwargs):
        """Unmap an InfiniBox volume from the host"""
        infinidat_volume = self._get_infinidat_volume(volume)
        if self._protocol == 'FC':
            volume_type = 'fibre_channel'
        else:
            volume_type = 'iscsi'
        result_data = dict()
        ports = self._get_ports_from_connector(infinidat_volume, connector)
        for port in ports:
            host_name = self._make_host_name(port)
            host = self._system.hosts.safe_get(name=host_name)
            if host is None:
                # not found. ignore.
                continue
            # unmap
            try:
                host.unmap_volume(infinidat_volume)
            except KeyError:
                continue      # volume mapping not found
            # check if the host now doesn't have mappings
            if host is not None and len(host.get_luns()) == 0:
                host.safe_delete()
                if self._protocol == 'FC' and connector is not None:
                    # Create initiator-target mapping to delete host entry
                    # this is only relevant for regular (specific host) detach
                    target_wwpns = list(self._get_online_fc_ports())
                    target_wwpns, target_map = (
                        self._build_initiator_target_map(connector,
                                                         target_wwpns))
                    result_data = dict(target_wwn=target_wwpns,
                                       initiator_target_map=target_map)
        conn_info = dict(driver_volume_type=volume_type,
                         data=result_data)
        if self._protocol == 'FC':
            fczm_utils.remove_fc_zone(conn_info)
        return conn_info

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
            qos_support = (hasattr(self._system.compat, "has_qos") and
                           self._system.compat.has_qos())
            max_osr = self.configuration.max_over_subscription_ratio
            thin = self.configuration.san_thin_provision
            self._volume_stats = dict(volume_backend_name=self._backend_name,
                                      vendor_name=VENDOR_NAME,
                                      driver_version=self.VERSION,
                                      storage_protocol=self._protocol,
                                      consistencygroup_support=False,
                                      total_capacity_gb=total_capacity_gb,
                                      free_capacity_gb=free_capacity_gb,
                                      consistent_group_snapshot_enabled=True,
                                      QoS_support=qos_support,
                                      thin_provisioning_support=thin,
                                      thick_provisioning_support=not thin,
                                      max_over_subscription_ratio=max_osr,
                                      multiattach=True)
        return self._volume_stats

    def _create_volume(self, volume):
        pool = self._get_infinidat_pool()
        volume_name = self._make_volume_name(volume)
        provtype = "THIN" if self.configuration.san_thin_provision else "THICK"
        size = volume.size * capacity.GiB
        create_kwargs = dict(name=volume_name,
                             pool=pool,
                             provtype=provtype,
                             size=size)
        if self._system.compat.has_compression():
            create_kwargs["compression_enabled"] = (
                self.configuration.infinidat_use_compression)
        infinidat_volume = self._system.volumes.create(**create_kwargs)
        self._set_qos(volume, infinidat_volume)
        self._set_cinder_object_metadata(infinidat_volume, volume)
        return infinidat_volume

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
        infinidat_volume = self._get_infinidat_volume(volume)
        size_delta = new_size * capacity.GiB - infinidat_volume.get_size()
        infinidat_volume.resize(size_delta)

    @infinisdk_to_cinder_exceptions
    def create_snapshot(self, snapshot):
        """Creates a snapshot."""
        volume = self._get_infinidat_volume(snapshot.volume)
        name = self._make_snapshot_name(snapshot)
        infinidat_snapshot = volume.create_snapshot(name=name)
        self._set_cinder_object_metadata(infinidat_snapshot, snapshot)

    @contextmanager
    def _connection_context(self, volume):
        use_multipath = self.configuration.use_multipath_for_image_xfer
        enforce_multipath = self.configuration.enforce_multipath_for_image_xfer
        connector = volume_utils.brick_get_connector_properties(
            use_multipath,
            enforce_multipath)
        connection = self.initialize_connection(volume, connector)
        try:
            yield connection
        finally:
            self.terminate_connection(volume, connector)

    @contextmanager
    def _attach_context(self, connection):
        use_multipath = self.configuration.use_multipath_for_image_xfer
        device_scan_attempts = self.configuration.num_volume_device_scan_tries
        protocol = connection['driver_volume_type']
        connector = volume_utils.brick_get_connector(
            protocol,
            use_multipath=use_multipath,
            device_scan_attempts=device_scan_attempts,
            conn=connection)
        attach_info = None
        try:
            attach_info = self._connect_device(connection)
            yield attach_info
        except exception.DeviceUnavailable as exc:
            attach_info = exc.kwargs.get('attach_info', None)
            raise
        finally:
            if attach_info:
                connector.disconnect_volume(attach_info['conn']['data'],
                                            attach_info['device'])

    @contextmanager
    def _device_connect_context(self, volume):
        with self._connection_context(volume) as connection:
            with self._attach_context(connection) as attach_info:
                yield attach_info

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
        infinidat_clone = infinidat_snapshot.create_snapshot(name=clone_name)
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
                    volume_utils.copy_volume(src_dev['device']['path'],
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
                volume_utils.copy_volume(src_dev['device']['path'],
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

    @infinisdk_to_cinder_exceptions
    def create_group(self, context, group):
        """Creates a group."""
        # let generic volume group support handle non-cgsnapshots
        if not volume_utils.is_group_a_cg_snapshot_type(group):
            raise NotImplementedError()
        obj = self._system.cons_groups.create(name=self._make_cg_name(group),
                                              pool=self._get_infinidat_pool())
        self._set_cinder_object_metadata(obj, group)
        return {'status': fields.GroupStatus.AVAILABLE}

    @infinisdk_to_cinder_exceptions
    def delete_group(self, context, group, volumes):
        """Deletes a group."""
        # let generic volume group support handle non-cgsnapshots
        if not volume_utils.is_group_a_cg_snapshot_type(group):
            raise NotImplementedError()
        try:
            infinidat_cg = self._get_infinidat_cg(group)
        except exception.InvalidGroup:
            pass      # group not found
        else:
            infinidat_cg.safe_delete()
        for volume in volumes:
            self.delete_volume(volume)
        return None, None

    @infinisdk_to_cinder_exceptions
    def update_group(self, context, group,
                     add_volumes=None, remove_volumes=None):
        """Updates a group."""
        # let generic volume group support handle non-cgsnapshots
        if not volume_utils.is_group_a_cg_snapshot_type(group):
            raise NotImplementedError()
        add_volumes = add_volumes if add_volumes else []
        remove_volumes = remove_volumes if remove_volumes else []
        infinidat_cg = self._get_infinidat_cg(group)
        for vol in add_volumes:
            infinidat_volume = self._get_infinidat_volume(vol)
            infinidat_cg.add_member(infinidat_volume)
        for vol in remove_volumes:
            infinidat_volume = self._get_infinidat_volume(vol)
            infinidat_cg.remove_member(infinidat_volume)
        return None, None, None

    @infinisdk_to_cinder_exceptions
    def create_group_from_src(self, context, group, volumes,
                              group_snapshot=None, snapshots=None,
                              source_group=None, source_vols=None):
        """Creates a group from source."""
        # The source is either group_snapshot+snapshots or
        # source_group+source_vols. The target is group+volumes
        # we assume the source (source_vols / snapshots) are in the same
        # order as the target (volumes)

        # let generic volume group support handle non-cgsnapshots
        if not volume_utils.is_group_a_cg_snapshot_type(group):
            raise NotImplementedError()
        self.create_group(context, group)
        new_infinidat_group = self._get_infinidat_cg(group)
        if group_snapshot is not None and snapshots is not None:
            for volume, snapshot in zip(volumes, snapshots):
                self.create_volume_from_snapshot(volume, snapshot)
                new_infinidat_volume = self._get_infinidat_volume(volume)
                new_infinidat_group.add_member(new_infinidat_volume)
        elif source_group is not None and source_vols is not None:
            for volume, src_vol in zip(volumes, source_vols):
                self.create_cloned_volume(volume, src_vol)
                new_infinidat_volume = self._get_infinidat_volume(volume)
                new_infinidat_group.add_member(new_infinidat_volume)
        return None, None

    @infinisdk_to_cinder_exceptions
    def create_group_snapshot(self, context, group_snapshot, snapshots):
        """Creates a group_snapshot."""
        # let generic volume group support handle non-cgsnapshots
        if not volume_utils.is_group_a_cg_snapshot_type(group_snapshot):
            raise NotImplementedError()
        infinidat_cg = self._get_infinidat_cg(group_snapshot.group)
        group_snap_name = self._make_group_snapshot_name(group_snapshot)
        new_group = infinidat_cg.create_snapshot(name=group_snap_name)
        # update the names of the individual snapshots in the new snapgroup
        # to match the names we use for cinder snapshots
        for infinidat_snapshot in new_group.get_members():
            parent_name = infinidat_snapshot.get_parent().get_name()
            for cinder_snapshot in snapshots:
                if cinder_snapshot.volume_id in parent_name:
                    snapshot_name = self._make_snapshot_name(cinder_snapshot)
                    infinidat_snapshot.update_name(snapshot_name)
        return None, None

    @infinisdk_to_cinder_exceptions
    def delete_group_snapshot(self, context, group_snapshot, snapshots):
        """Deletes a group_snapshot."""
        # let generic volume group support handle non-cgsnapshots
        if not volume_utils.is_group_a_cg_snapshot_type(group_snapshot):
            raise NotImplementedError()
        cgsnap_name = self._make_group_snapshot_name(group_snapshot)
        infinidat_cgsnap = self._system.cons_groups.safe_get(name=cgsnap_name)
        if infinidat_cgsnap is not None:
            if not infinidat_cgsnap.is_snapgroup():
                msg = _('Group "%s" is not a snapshot group') % cgsnap_name
                LOG.error(msg)
                raise exception.InvalidGroupSnapshot(message=msg)
            infinidat_cgsnap.safe_delete()
        for snapshot in snapshots:
            self.delete_snapshot(snapshot)
        return None, None
