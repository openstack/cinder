# Copyright 2022 Infinidat Ltd.
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

import collections
from contextlib import contextmanager
import functools
import math
import platform
import socket
import uuid

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import units

from cinder.common import constants
from cinder import context as cinder_context
from cinder import coordination
from cinder import exception
from cinder.i18n import _
from cinder import interface
from cinder import objects
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
        1.7 - fixed iSCSI to return all portals
        1.8 - added revert to snapshot
        1.9 - added manage/unmanage/manageable-list volume/snapshot
        1.10 - added support for TLS/SSL communication
        1.11 - fixed generic volume migration
        1.12 - fixed volume multi-attach
        1.13 - fixed consistency groups feature
        1.14 - added storage assisted volume migration
        1.15 - fixed backup for attached volume

    """

    VERSION = '1.15'

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
            'driver_use_ssl', 'suppress_requests_ssl_warnings',
            'max_over_subscription_ratio')
        return infinidat_opts + additional_opts

    def _setup_and_get_system_object(self, management_address, auth,
                                     use_ssl=False):
        system = infinisdk.InfiniBox(management_address, auth=auth,
                                     use_ssl=use_ssl)
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
        use_ssl = self.configuration.driver_use_ssl
        self.management_address = self.configuration.san_ip
        self._system = self._setup_and_get_system_object(
            self.management_address, auth, use_ssl=use_ssl)
        backend_name = self.configuration.safe_get('volume_backend_name')
        self._backend_name = backend_name or self.__class__.__name__
        self._volume_stats = None
        if self.configuration.infinidat_storage_protocol.lower() == 'iscsi':
            self._protocol = constants.ISCSI
            if len(self.configuration.infinidat_iscsi_netspaces) == 0:
                msg = _('No iSCSI network spaces configured')
                raise exception.VolumeDriverException(message=msg)
        else:
            self._protocol = constants.FC
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
        required = ('initiator' if self._protocol == constants.ISCSI
                    else 'wwpns')
        if required not in connector:
            LOG.error('The volume driver requires %(data)s '
                      'in the connector.', {'data': required})
            raise exception.InvalidConnectorException(missing=required)

    def _make_volume_name(self, cinder_volume, migration=False):
        """Return the Infinidat volume name.

        Use Cinder volume id in case of volume migration
        and use Cinder volume name_id for all other cases.
        """
        if migration:
            key = cinder_volume.id
        else:
            key = cinder_volume.name_id
        return 'openstack-vol-%s' % key

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

    def _get_infinidat_dataset_by_ref(self, existing_ref):
        if 'source-id' in existing_ref:
            kwargs = dict(id=existing_ref['source-id'])
        elif 'source-name' in existing_ref:
            kwargs = dict(name=existing_ref['source-name'])
        else:
            reason = _('dataset reference must contain '
                       'source-id or source-name key')
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_ref, reason=reason)
        return self._system.volumes.safe_get(**kwargs)

    def _get_infinidat_volume_by_ref(self, existing_ref):
        infinidat_volume = self._get_infinidat_dataset_by_ref(existing_ref)
        if infinidat_volume is None:
            raise exception.VolumeNotFound(volume_id=existing_ref)
        return infinidat_volume

    def _get_infinidat_snapshot_by_ref(self, existing_ref):
        infinidat_snapshot = self._get_infinidat_dataset_by_ref(existing_ref)
        if infinidat_snapshot is None:
            raise exception.SnapshotNotFound(snapshot_id=existing_ref)
        if not infinidat_snapshot.is_snapshot():
            reason = (_('reference %(existing_ref)s is a volume')
                      % {'existing_ref': existing_ref})
            raise exception.InvalidSnapshot(reason=reason)
        return infinidat_snapshot

    def _get_infinidat_volume_by_name(self, name):
        ref = {'source-name': name}
        return self._get_infinidat_volume_by_ref(ref)

    def _get_infinidat_snapshot_by_name(self, name):
        ref = {'source-name': name}
        return self._get_infinidat_snapshot_by_ref(ref)

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
            raise exception.GroupNotFound(group_id=group_name)
        return infinidat_cg

    def _get_infinidat_sg(self, group_snapshot):
        name = self._make_group_snapshot_name(group_snapshot)
        infinidat_sg = self._system.cons_groups.safe_get(name=name)
        if infinidat_sg is None:
            raise exception.GroupSnapshotNotFound(
                group_snapshot_id=group_snapshot.id)
        if not infinidat_sg.is_snapgroup():
            reason = (_('consistency group "%s" is not a snapshot group')
                      % name)
            raise exception.InvalidGroupSnapshot(reason=reason)
        return infinidat_sg

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

    def _initialize_connection_fc(self, infinidat_volume, connector):
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

    def _get_iscsi_portals(self, netspace):
        port = netspace.get_properties().iscsi_tcp_port
        portals = ["%s:%s" % (interface.ip_address, port) for interface
                   in netspace.get_ips() if interface.enabled]
        if portals:
            return portals
        # if we get here it means there are no enabled ports
        msg = (_('No available interfaces in iSCSI network space %s') %
               netspace.get_name())
        raise exception.VolumeDriverException(message=msg)

    def _initialize_connection_iscsi(self, infinidat_volume, connector):
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
            netspace_portals = self._get_iscsi_portals(netspace)
            target_portals.extend(netspace_portals)
            target_iqns.extend([netspace.get_properties().iscsi_iqn] *
                               len(netspace_portals))
            target_luns.extend([lun] * len(netspace_portals))

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
            if self._protocol == constants.FC:
                port_cls = wwn.WWN
            else:
                port_cls = iqn.IQN
            ports = []
            for lun_mapping in infinidat_volume.get_logical_units():
                host_ports = lun_mapping.get_host().get_ports()
                host_ports = [port for port in host_ports
                              if isinstance(port, port_cls)]
                ports.extend(host_ports)
        elif self._protocol == constants.FC:
            ports = [wwn.WWN(wwpn) for wwpn in connector['wwpns']]
        else:
            ports = [iqn.IQN(connector['initiator'])]
        return ports

    def _is_volume_multiattached(self, volume, connector):
        """Returns whether the volume is multiattached.

        Check if there are multiple attachments to the volume
        from the same connector. Terminate connection only for
        the last attachment from the corresponding host.
        """
        if not (connector and volume.multiattach and
                volume.volume_attachment):
            return False
        keys = ['system uuid']
        if self._protocol == constants.FC:
            keys.append('wwpns')
        else:
            keys.append('initiator')
        for key in keys:
            if not (key in connector and connector[key]):
                continue
            if sum(1 for attachment in volume.volume_attachment if
                   attachment.connector and key in attachment.connector and
                   attachment.connector[key] == connector[key]) > 1:
                LOG.debug('Volume %s is multiattached to %s %s',
                          volume.name_id, key, connector[key])
                return True
        return False

    def create_export_snapshot(self, context, snapshot, connector):
        """Exports the snapshot."""
        pass

    def remove_export_snapshot(self, context, snapshot):
        """Removes an export for a snapshot."""
        pass

    def backup_use_temp_snapshot(self):
        """Use a temporary snapshot for performing non-disruptive backups."""
        return True

    @coordination.synchronized('infinidat-{self.management_address}-lock')
    def _initialize_connection(self, infinidat_volume, connector):
        if self._protocol == constants.FC:
            initialize_connection = self._initialize_connection_fc
        else:
            initialize_connection = self._initialize_connection_iscsi
        return initialize_connection(infinidat_volume, connector)

    @infinisdk_to_cinder_exceptions
    def initialize_connection(self, volume, connector, **kwargs):
        """Map an InfiniBox volume to the host"""
        infinidat_volume = self._get_infinidat_volume(volume)
        return self._initialize_connection(infinidat_volume, connector)

    @infinisdk_to_cinder_exceptions
    def initialize_connection_snapshot(self, snapshot, connector, **kwargs):
        """Map an InfiniBox snapshot to the host"""
        infinidat_snapshot = self._get_infinidat_snapshot(snapshot)
        return self._initialize_connection(infinidat_snapshot, connector)

    @coordination.synchronized('infinidat-{self.management_address}-lock')
    def _terminate_connection(self, infinidat_volume, connector):
        if self._protocol == constants.FC:
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
                if self._protocol == constants.FC and connector is not None:
                    # Create initiator-target mapping to delete host entry
                    # this is only relevant for regular (specific host) detach
                    target_wwpns = list(self._get_online_fc_ports())
                    target_wwpns, target_map = (
                        self._build_initiator_target_map(connector,
                                                         target_wwpns))
                    result_data = dict(target_wwn=target_wwpns,
                                       initiator_target_map=target_map)
        if self._protocol == constants.FC:
            conn_info = dict(driver_volume_type=volume_type,
                             data=result_data)
            fczm_utils.remove_fc_zone(conn_info)

    @infinisdk_to_cinder_exceptions
    def terminate_connection(self, volume, connector, **kwargs):
        """Unmap an InfiniBox volume from the host"""
        if self._is_volume_multiattached(volume, connector):
            return True
        infinidat_volume = self._get_infinidat_volume(volume)
        self._terminate_connection(infinidat_volume, connector)
        return volume.volume_attachment and len(volume.volume_attachment) > 1

    @infinisdk_to_cinder_exceptions
    def terminate_connection_snapshot(self, snapshot, connector, **kwargs):
        """Unmap an InfiniBox snapshot from the host"""
        infinidat_snapshot = self._get_infinidat_snapshot(snapshot)
        self._terminate_connection(infinidat_snapshot, connector)

    @infinisdk_to_cinder_exceptions
    def get_volume_stats(self, refresh=False):
        if self._volume_stats is None or refresh:
            pool = self._get_infinidat_pool()
            location_info = '%(driver)s:%(serial)s:%(pool)s' % {
                'driver': self.__class__.__name__,
                'serial': self._system.get_serial(),
                'pool': self.configuration.infinidat_pool_name}
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
                                      location_info=location_info,
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
        if volume.group_id:
            group = volume_utils.group_get_by_id(volume.group_id)
            if volume_utils.is_group_a_cg_snapshot_type(group):
                infinidat_group = self._get_infinidat_cg(group)
                infinidat_group.add_member(infinidat_volume)
        return infinidat_volume

    @infinisdk_to_cinder_exceptions
    def create_volume(self, volume):
        """Create a new volume on the backend."""
        # this is the same as _create_volume but without the return statement
        self._create_volume(volume)

    @infinisdk_to_cinder_exceptions
    def delete_volume(self, volume):
        """Delete a volume from the backend."""
        try:
            infinidat_volume = self._get_infinidat_volume(volume)
        except exception.VolumeNotFound:
            return
        if infinidat_volume.has_children():
            # can't delete a volume that has a live snapshot
            raise exception.VolumeIsBusy(volume_name=volume.name)
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
    def _connection_context(self, infinidat_volume):
        use_multipath = self.configuration.use_multipath_for_image_xfer
        enforce_multipath = self.configuration.enforce_multipath_for_image_xfer
        connector = volume_utils.brick_get_connector_properties(
            use_multipath,
            enforce_multipath)
        connection = self._initialize_connection(infinidat_volume, connector)
        try:
            yield connection
        finally:
            self._terminate_connection(infinidat_volume, connector)

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
    def _device_connect_context(self, infinidat_volume):
        with self._connection_context(infinidat_volume) as connection:
            with self._attach_context(connection) as attach_info:
                yield attach_info

    @infinisdk_to_cinder_exceptions
    def create_volume_from_snapshot(self, volume, snapshot):
        """Create volume from snapshot.

        InfiniBox does not yet support detached clone so use dd to copy data.
        This could be a lengthy operation.

        - create destination volume
        - map source snapshot and destination volume
        - copy data from snapshot to volume
        - unmap volume and snapshot
        """
        infinidat_snapshot = self._get_infinidat_snapshot(snapshot)
        infinidat_volume = self._create_volume(volume)
        try:
            src_ctx = self._device_connect_context(infinidat_snapshot)
            dst_ctx = self._device_connect_context(infinidat_volume)
            with src_ctx as src_dev, dst_ctx as dst_dev:
                dd_block_size = self.configuration.volume_dd_blocksize
                volume_utils.copy_volume(src_dev['device']['path'],
                                         dst_dev['device']['path'],
                                         snapshot.volume.size * units.Ki,
                                         dd_block_size, sparse=True)
        except Exception:
            infinidat_volume.delete()
            raise

    @infinisdk_to_cinder_exceptions
    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        try:
            snapshot = self._get_infinidat_snapshot(snapshot)
        except exception.SnapshotNotFound:
            return
        snapshot.safe_delete()

    @infinisdk_to_cinder_exceptions
    def create_cloned_volume(self, volume, src_vref):
        """Create a clone from source volume.

        InfiniBox does not yet support detached clone so use dd to copy data.
        This could be a lengthy operation.

        * create temporary snapshot from source volume
        * map temporary snapshot
        * create and map new volume
        * copy data from temporary snapshot to new volume
        * unmap volume and temporary snapshot
        * delete temporary snapshot
        """
        attributes = ('id', 'name', 'volume')
        Snapshot = collections.namedtuple('Snapshot', attributes)
        snapshot_id = str(uuid.uuid4())
        snapshot_name = CONF.snapshot_name_template % snapshot_id
        snapshot = Snapshot(id=snapshot_id, name=snapshot_name,
                            volume=src_vref)
        try:
            self.create_snapshot(snapshot)
            self.create_volume_from_snapshot(volume, snapshot)
        finally:
            self.delete_snapshot(snapshot)

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
        """Creates a group.

        :param context: the context of the caller.
        :param group: the Group object of the group to be created.
        :returns: model_update
        """
        # let generic volume group support handle non-cgsnapshots
        if not volume_utils.is_group_a_cg_snapshot_type(group):
            raise NotImplementedError()
        name = self._make_cg_name(group)
        pool = self._get_infinidat_pool()
        infinidat_cg = self._system.cons_groups.create(name=name, pool=pool)
        self._set_cinder_object_metadata(infinidat_cg, group)
        return {'status': fields.GroupStatus.AVAILABLE}

    @infinisdk_to_cinder_exceptions
    def delete_group(self, context, group, volumes):
        """Deletes a group.

        :param context: the context of the caller.
        :param group: the Group object of the group to be deleted.
        :param volumes: a list of Volume objects in the group.
        :returns: model_update, volumes_model_update
        """
        # let generic volume group support handle non-cgsnapshots
        if not volume_utils.is_group_a_cg_snapshot_type(group):
            raise NotImplementedError()
        try:
            infinidat_cg = self._get_infinidat_cg(group)
        except exception.GroupNotFound:
            pass
        else:
            infinidat_cg.safe_delete()
        for volume in volumes:
            self.delete_volume(volume)
        return None, None

    @infinisdk_to_cinder_exceptions
    def update_group(self, context, group,
                     add_volumes=None, remove_volumes=None):
        """Updates a group.

        :param context: the context of the caller.
        :param group: the Group object of the group to be updated.
        :param add_volumes: a list of Volume objects to be added.
        :param remove_volumes: a list of Volume objects to be removed.
        :returns: model_update, add_volumes_update, remove_volumes_update
        """
        # let generic volume group support handle non-cgsnapshots
        if not volume_utils.is_group_a_cg_snapshot_type(group):
            raise NotImplementedError()
        add_volumes = add_volumes if add_volumes else []
        remove_volumes = remove_volumes if remove_volumes else []
        infinidat_cg = self._get_infinidat_cg(group)
        for volume in add_volumes:
            infinidat_volume = self._get_infinidat_volume(volume)
            infinidat_cg.add_member(infinidat_volume)
        for volume in remove_volumes:
            infinidat_volume = self._get_infinidat_volume(volume)
            infinidat_cg.remove_member(infinidat_volume)
        return None, None, None

    @infinisdk_to_cinder_exceptions
    def create_group_from_src(self, context, group, volumes,
                              group_snapshot=None, snapshots=None,
                              source_group=None, source_vols=None):
        """Creates a group from source.

        :param context: the context of the caller.
        :param group: the Group object to be created.
        :param volumes: a list of Volume objects in the group.
        :param group_snapshot: the GroupSnapshot object as source.
        :param snapshots: a list of Snapshot objects in group_snapshot.
        :param source_group: the Group object as source.
        :param source_vols: a list of Volume objects in the source_group.
        :returns: model_update, volumes_model_update

        The source can be group_snapshot or a source_group.
        """
        # let generic volume group support handle non-cgsnapshots
        if not volume_utils.is_group_a_cg_snapshot_type(group):
            raise NotImplementedError()
        self.create_group(context, group)
        if group_snapshot and snapshots:
            for volume, snapshot in zip(volumes, snapshots):
                self.create_volume_from_snapshot(volume, snapshot)
        elif source_group and source_vols:
            for volume, source_vol in zip(volumes, source_vols):
                self.create_cloned_volume(volume, source_vol)
        else:
            message = _('creating a group from source is possible '
                        'from an existing group or a group snapshot.')
            raise exception.InvalidInput(message=message)
        return None, None

    @infinisdk_to_cinder_exceptions
    def create_group_snapshot(self, context, group_snapshot, snapshots):
        """Creates a group_snapshot.

        :param context: the context of the caller.
        :param group_snapshot: the GroupSnapshot object to be created.
        :param snapshots: a list of Snapshot objects in the group_snapshot.
        :returns: model_update, snapshots_model_update
        """
        # let generic volume group support handle non-cgsnapshots
        if not volume_utils.is_group_a_cg_snapshot_type(group_snapshot):
            raise NotImplementedError()
        infinidat_cg = self._get_infinidat_cg(group_snapshot.group)
        group_snapshot_name = self._make_group_snapshot_name(group_snapshot)
        infinidat_sg = infinidat_cg.create_snapshot(name=group_snapshot_name)
        # update the names of the individual snapshots in the new snapgroup
        # to match the names we use for cinder snapshots
        for infinidat_snapshot in infinidat_sg.get_members():
            parent_name = infinidat_snapshot.get_parent().get_name()
            for snapshot in snapshots:
                if snapshot.volume.name_id in parent_name:
                    snapshot_name = self._make_snapshot_name(snapshot)
                    infinidat_snapshot.update_name(snapshot_name)
        return None, None

    @infinisdk_to_cinder_exceptions
    def delete_group_snapshot(self, context, group_snapshot, snapshots):
        """Deletes a group_snapshot.

        :param context: the context of the caller.
        :param group_snapshot: the GroupSnapshot object to be deleted.
        :param snapshots: a list of Snapshot objects in the group_snapshot.
        :returns: model_update, snapshots_model_update
        """
        # let generic volume group support handle non-cgsnapshots
        if not volume_utils.is_group_a_cg_snapshot_type(group_snapshot):
            raise NotImplementedError()
        try:
            infinidat_sg = self._get_infinidat_sg(group_snapshot)
        except exception.GroupSnapshotNotFound:
            pass
        else:
            infinidat_sg.safe_delete()
        for snapshot in snapshots:
            self.delete_snapshot(snapshot)
        return None, None

    def snapshot_revert_use_temp_snapshot(self):
        """Disable the use of a temporary snapshot on revert."""
        return False

    @infinisdk_to_cinder_exceptions
    def revert_to_snapshot(self, context, volume, snapshot):
        """Revert volume to snapshot.

        Note: the revert process should not change the volume's
        current size, that means if the driver shrank
        the volume during the process, it should extend the
        volume internally.
        """
        infinidat_snapshot = self._get_infinidat_snapshot(snapshot)
        infinidat_volume = self._get_infinidat_volume(snapshot.volume)
        infinidat_volume.restore(infinidat_snapshot)
        volume_size = infinidat_volume.get_size()
        snapshot_size = snapshot.volume.size * capacity.GiB
        if volume_size < snapshot_size:
            self.extend_volume(volume, snapshot.volume.size)

    @infinisdk_to_cinder_exceptions
    def manage_existing(self, volume, existing_ref):
        """Manage an existing Infinidat volume.

        Checks if the volume is already managed.
        Renames the Infinidat volume to match the expected name.
        Updates QoS and metadata.

        :param volume:       Cinder volume to manage
        :param existing_ref: dictionary of the forms:
                             {'source-name': 'Infinidat volume name'} or
                             {'source-id': 'Infinidat volume serial number'}
        """
        infinidat_volume = self._get_infinidat_volume_by_ref(existing_ref)
        infinidat_metadata = infinidat_volume.get_all_metadata()
        if 'cinder_id' in infinidat_metadata:
            cinder_id = infinidat_metadata['cinder_id']
            if volume_utils.check_already_managed_volume(cinder_id):
                raise exception.ManageExistingAlreadyManaged(
                    volume_ref=cinder_id)
        infinidat_pool = infinidat_volume.get_pool_name()
        if infinidat_pool != self.configuration.infinidat_pool_name:
            message = (_('unexpected pool name %(infinidat_pool)s')
                       % {'infinidat_pool': infinidat_pool})
            raise exception.InvalidConfigurationValue(message=message)
        cinder_name = self._make_volume_name(volume)
        infinidat_volume.update_name(cinder_name)
        self._set_qos(volume, infinidat_volume)
        self._set_cinder_object_metadata(infinidat_volume, volume)

    @infinisdk_to_cinder_exceptions
    def manage_existing_get_size(self, volume, existing_ref):
        """Return size of an existing Infinidat volume.

        When calculating the size, round up to the next GB.

        :param volume:       Cinder volume to manage
        :param existing_ref: dictionary of the forms:
                             {'source-name': 'Infinidat volume name'} or
                             {'source-id': 'Infinidat volume serial number'}
        :returns size:       Volume size in GiB (integer)
        """
        infinidat_volume = self._get_infinidat_volume_by_ref(existing_ref)
        return int(math.ceil(infinidat_volume.get_size() / capacity.GiB))

    @infinisdk_to_cinder_exceptions
    def get_manageable_volumes(self, cinder_volumes, marker, limit, offset,
                               sort_keys, sort_dirs):
        """List volumes on the Infinidat backend available for management.

        Returns a list of dictionaries, each specifying a volume on the
        Infinidat backend, with the following keys:
        - reference (dictionary): The reference for a volume, which can be
        passed to "manage_existing". Each reference contains keys:
        Infinidat volume name and Infinidat volume serial number.
        - size (int): The size of the volume according to the Infinidat
        storage backend, rounded up to the nearest GB.
        - safe_to_manage (boolean): Whether or not this volume is safe to
        manage according to the storage backend. For example, is the volume
        already managed, in use, has snapshots or active mappings.
        - reason_not_safe (string): If safe_to_manage is False, the reason why.
        - cinder_id (string): If already managed, provide the Cinder ID.
        - extra_info (string): Extra information (pool name, volume type,
        QoS and metadata) to return to the user.

        :param cinder_volumes: A list of volumes in this host that Cinder
                               currently manages, used to determine if
                               a volume is manageable or not.
        :param marker:    The last item of the previous page; we return the
                          next results after this value (after sorting)
        :param limit:     Maximum number of items to return
        :param offset:    Number of items to skip after marker
        :param sort_keys: List of keys to sort results by (valid keys are
                          'identifier' and 'size')
        :param sort_dirs: List of directions to sort by, corresponding to
                          sort_keys (valid directions are 'asc' and 'desc')
        """
        manageable_volumes = []
        cinder_ids = [cinder_volume.id for cinder_volume in cinder_volumes]
        infinidat_pool = self._get_infinidat_pool()
        infinidat_volumes = infinidat_pool.get_volumes()
        for infinidat_volume in infinidat_volumes:
            if infinidat_volume.is_snapshot():
                continue
            safe_to_manage = False
            reason_not_safe = None
            volume_id = infinidat_volume.get_id()
            volume_name = infinidat_volume.get_name()
            volume_size = infinidat_volume.get_size()
            volume_type = infinidat_volume.get_type()
            volume_pool = infinidat_volume.get_pool_name()
            volume_qos = infinidat_volume.get_qos_policy()
            volume_meta = infinidat_volume.get_all_metadata()
            cinder_id = volume_meta.get('cinder_id')
            volume_luns = infinidat_volume.get_logical_units()
            if cinder_id and cinder_id in cinder_ids:
                reason_not_safe = _('volume already managed')
            elif volume_luns:
                reason_not_safe = _('volume has mappings')
            elif infinidat_volume.has_children():
                reason_not_safe = _('volume has snapshots')
            else:
                safe_to_manage = True
            reference = {
                'source-name': volume_name,
                'source-id': str(volume_id)
            }
            extra_info = {
                'pool': volume_pool,
                'type': volume_type,
                'qos': str(volume_qos),
                'meta': str(volume_meta)
            }
            manageable_volume = {
                'reference': reference,
                'size': int(math.ceil(volume_size / capacity.GiB)),
                'safe_to_manage': safe_to_manage,
                'reason_not_safe': reason_not_safe,
                'cinder_id': cinder_id,
                'extra_info': extra_info
            }
            manageable_volumes.append(manageable_volume)
        return volume_utils.paginate_entries_list(
            manageable_volumes, marker, limit,
            offset, sort_keys, sort_dirs)

    @infinisdk_to_cinder_exceptions
    def unmanage(self, volume):
        """Removes the specified volume from Cinder management.

        Does not delete the underlying backend storage object.

        For most drivers, this will not need to do anything.  However, some
        drivers might use this call as an opportunity to clean up any
        Cinder-specific configuration that they have associated with the
        backend storage object.

        :param volume: Cinder volume to unmanage
        """
        infinidat_volume = self._get_infinidat_volume(volume)
        infinidat_volume.clear_metadata()

    def _check_already_managed_snapshot(self, snapshot_id):
        """Check cinder db for already managed snapshot.

        :param snapshot_id snapshot id parameter
        :returns: bool -- return True, if db entry with specified
                          snapshot id exists, otherwise return False
        """
        try:
            uuid.UUID(snapshot_id, version=4)
        except ValueError:
            return False
        ctxt = cinder_context.get_admin_context()
        return objects.Snapshot.exists(ctxt, snapshot_id)

    @infinisdk_to_cinder_exceptions
    def manage_existing_snapshot(self, snapshot, existing_ref):
        """Manage an existing Infinidat snapshot.

        Checks if the snapshot is already managed.
        Renames the Infinidat snapshot to match the expected name.
        Updates QoS and metadata.

        :param snapshot:     Cinder snapshot to manage
        :param existing_ref: dictionary of the forms:
                             {'source-name': 'Infinidat snapshot name'} or
                             {'source-id': 'Infinidat snapshot serial number'}
        """
        infinidat_snapshot = self._get_infinidat_snapshot_by_ref(existing_ref)
        infinidat_metadata = infinidat_snapshot.get_all_metadata()
        if 'cinder_id' in infinidat_metadata:
            cinder_id = infinidat_metadata['cinder_id']
            if self._check_already_managed_snapshot(cinder_id):
                raise exception.ManageExistingAlreadyManaged(
                    volume_ref=cinder_id)
        infinidat_pool = infinidat_snapshot.get_pool_name()
        if infinidat_pool != self.configuration.infinidat_pool_name:
            message = (_('unexpected pool name %(infinidat_pool)s')
                       % {'infinidat_pool': infinidat_pool})
            raise exception.InvalidConfigurationValue(message=message)
        cinder_name = self._make_snapshot_name(snapshot)
        infinidat_snapshot.update_name(cinder_name)
        self._set_qos(snapshot, infinidat_snapshot)
        self._set_cinder_object_metadata(infinidat_snapshot, snapshot)

    @infinisdk_to_cinder_exceptions
    def manage_existing_snapshot_get_size(self, snapshot, existing_ref):
        """Return size of an existing Infinidat snapshot.

        When calculating the size, round up to the next GB.

        :param snapshot:     Cinder snapshot to manage
        :param existing_ref: dictionary of the forms:
                             {'source-name': 'Infinidat snapshot name'} or
                             {'source-id': 'Infinidat snapshot serial number'}
        :returns size:       Snapshot size in GiB (integer)
        """
        infinidat_snapshot = self._get_infinidat_snapshot_by_ref(existing_ref)
        return int(math.ceil(infinidat_snapshot.get_size() / capacity.GiB))

    @infinisdk_to_cinder_exceptions
    def get_manageable_snapshots(self, cinder_snapshots, marker, limit, offset,
                                 sort_keys, sort_dirs):
        """List snapshots on the Infinidat backend available for management.

        Returns a list of dictionaries, each specifying a snapshot on the
        Infinidat backend, with the following keys:
        - reference (dictionary): The reference for a snapshot, which can be
        passed to "manage_existing_snapshot". Each reference contains keys:
        Infinidat snapshot name and Infinidat snapshot serial number.
        - size (int): The size of the snapshot according to the Infinidat
        storage backend, rounded up to the nearest GB.
        - safe_to_manage (boolean): Whether or not this snapshot is safe to
        manage according to the storage backend. For example, is the snapshot
        already managed, has clones or active mappings.
        - reason_not_safe (string): If safe_to_manage is False, the reason why.
        - cinder_id (string): If already managed, provide the Cinder ID.
        - extra_info (string): Extra information (pool name, snapshot type,
        QoS and metadata) to return to the user.
        - source_reference (string): Similar to "reference", but for the
        snapshot's source volume. The source reference contains two keys:
        Infinidat volume name and Infinidat volume serial number.

        :param cinder_snapshots: A list of snapshots in this host that Cinder
                                 currently manages, used to determine if
                                 a snapshot is manageable or not.
        :param marker:    The last item of the previous page; we return the
                          next results after this value (after sorting)
        :param limit:     Maximum number of items to return
        :param offset:    Number of items to skip after marker
        :param sort_keys: List of keys to sort results by (valid keys are
                          'identifier' and 'size')
        :param sort_dirs: List of directions to sort by, corresponding to
                          sort_keys (valid directions are 'asc' and 'desc')
        """
        manageable_snapshots = []
        cinder_ids = [cinder_snapshot.id for cinder_snapshot
                      in cinder_snapshots]
        infinidat_pool = self._get_infinidat_pool()
        infinidat_snapshots = infinidat_pool.get_volumes()
        for infinidat_snapshot in infinidat_snapshots:
            if not infinidat_snapshot.is_snapshot():
                continue
            safe_to_manage = False
            reason_not_safe = None
            parent = infinidat_snapshot.get_parent()
            parent_id = parent.get_id()
            parent_name = parent.get_name()
            snapshot_id = infinidat_snapshot.get_id()
            snapshot_name = infinidat_snapshot.get_name()
            snapshot_size = infinidat_snapshot.get_size()
            snapshot_type = infinidat_snapshot.get_type()
            snapshot_pool = infinidat_snapshot.get_pool_name()
            snapshot_qos = infinidat_snapshot.get_qos_policy()
            snapshot_meta = infinidat_snapshot.get_all_metadata()
            cinder_id = snapshot_meta.get('cinder_id')
            snapshot_luns = infinidat_snapshot.get_logical_units()
            if cinder_id and cinder_id in cinder_ids:
                reason_not_safe = _('snapshot already managed')
            elif snapshot_luns:
                reason_not_safe = _('snapshot has mappings')
            elif infinidat_snapshot.has_children():
                reason_not_safe = _('snapshot has clones')
            else:
                safe_to_manage = True
            reference = {
                'source-name': snapshot_name,
                'source-id': str(snapshot_id)
            }
            source_reference = {
                'source-name': parent_name,
                'source-id': str(parent_id)
            }
            extra_info = {
                'pool': snapshot_pool,
                'type': snapshot_type,
                'qos': str(snapshot_qos),
                'meta': str(snapshot_meta)
            }
            manageable_snapshot = {
                'reference': reference,
                'size': int(math.ceil(snapshot_size / capacity.GiB)),
                'safe_to_manage': safe_to_manage,
                'reason_not_safe': reason_not_safe,
                'cinder_id': cinder_id,
                'extra_info': extra_info,
                'source_reference': source_reference
            }
            manageable_snapshots.append(manageable_snapshot)
        return volume_utils.paginate_entries_list(
            manageable_snapshots, marker, limit,
            offset, sort_keys, sort_dirs)

    @infinisdk_to_cinder_exceptions
    def unmanage_snapshot(self, snapshot):
        """Removes the specified snapshot from Cinder management.

        Does not delete the underlying backend storage object.

        For most drivers, this will not need to do anything. However, some
        drivers might use this call as an opportunity to clean up any
        Cinder-specific configuration that they have associated with the
        backend storage object.

        :param snapshot: Cinder volume snapshot to unmanage
        """
        infinidat_snapshot = self._get_infinidat_snapshot(snapshot)
        infinidat_snapshot.clear_metadata()

    @infinisdk_to_cinder_exceptions
    def update_migrated_volume(self, ctxt, volume, new_volume,
                               original_volume_status):
        """Return model update from Infinidat for migrated volume.

        This method should rename the back-end volume name(id) on the
        destination host back to its original name(id) on the source host.

        :param ctxt: The context used to run the method update_migrated_volume
        :param volume: The original volume that was migrated to this backend
        :param new_volume: The migration volume object that was created on
                           this backend as part of the migration process
        :param original_volume_status: The status of the original volume
        :returns: model_update to update DB with any needed changes
        """
        model_update = {'_name_id': new_volume.name_id,
                        'provider_location': None}
        new_volume_name = self._make_volume_name(new_volume, migration=True)
        new_infinidat_volume = self._get_infinidat_volume(new_volume)
        self._set_cinder_object_metadata(new_infinidat_volume, volume)
        volume_name = self._make_volume_name(volume, migration=True)
        try:
            infinidat_volume = self._get_infinidat_volume(volume)
        except exception.VolumeNotFound:
            LOG.debug('Source volume %s not found', volume_name)
        else:
            volume_pool = infinidat_volume.get_pool_name()
            LOG.debug('Found source volume %s in pool %s',
                      volume_name, volume_pool)
            return model_update
        try:
            new_infinidat_volume.update_name(volume_name)
        except infinisdk.core.exceptions.InfiniSDKException as error:
            LOG.error('Failed to rename destination volume %s -> %s: %s',
                      new_volume_name, volume_name, error)
            return model_update
        return {'_name_id': None, 'provider_location': None}

    @infinisdk_to_cinder_exceptions
    def migrate_volume(self, ctxt, volume, host):
        """Migrate a volume within the same InfiniBox system."""
        LOG.debug('Starting volume migration for volume %s to host %s',
                  volume.name, host)
        if not (host and 'capabilities' in host):
            LOG.error('No capabilities found for host %s', host)
            return False, None
        capabilities = host['capabilities']
        if not (capabilities and 'location_info' in capabilities):
            LOG.error('No location info found for host %s', host)
            return False, None
        location = capabilities['location_info']
        try:
            driver, serial, pool = location.split(':')
            serial = int(serial)
        except (AttributeError, ValueError) as error:
            LOG.error('Invalid location info %s found for host %s: %s',
                      location, host, error)
            return False, None
        if driver != self.__class__.__name__:
            LOG.debug('Unsupported storage driver %s found for host %s',
                      driver, host)
            return False, None
        if serial != self._system.get_serial():
            LOG.error('Unable to migrate volume %s to remote host %s',
                      volume.name, host)
            return False, None
        infinidat_volume = self._get_infinidat_volume(volume)
        if pool == infinidat_volume.get_pool_name():
            LOG.debug('Volume %s already migrated to pool %s',
                      volume.name, pool)
            return True, None
        infinidat_pool = self._system.pools.safe_get(name=pool)
        if infinidat_pool is None:
            LOG.error('Destination pool %s not found on host %s', pool, host)
            return False, None
        infinidat_volume.move_pool(infinidat_pool)
        LOG.info('Migrated volume %s to pool %s', volume.name, pool)
        return True, None
