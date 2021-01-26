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

"""Driver for RackScale Design."""

from distutils import version
import json

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import units
try:
    from rsd_lib import RSDLib
    from sushy import exceptions as sushy_exceptions
except ImportError:
    # Used for tests, when no rsd-lib is installed
    RSDLib = None
    sushy_exceptions = None

from cinder import exception
from cinder.i18n import _
from cinder import interface
from cinder import utils
from cinder.volume import driver
from cinder.volume import volume_utils

LOG = logging.getLogger(__name__)

RSD_OPTS = [
    cfg.StrOpt('podm_url',
               default='',
               help='URL of PODM service'),
    cfg.StrOpt('podm_username',
               default='',
               help='Username of PODM service'),
    cfg.StrOpt('podm_password',
               default='',
               help='Password of PODM service',
               secret=True),
]


class RSDRetryableException(exception.VolumeDriverException):
    message = _("RSD retryable exception: %(reason)s")


def get_volume_metadata(volume):
    metadata = volume.get('volume_metadata')
    if metadata:
        ret = {data['key']: data['value'] for data in metadata}
    else:
        ret = volume.get('metadata', {})
    return ret


class RSDClient(object):
    def __init__(self, rsdlib):
        self.rsdlib = rsdlib

    @classmethod
    def initialize(cls, url, username, password, verify):
        if not RSDLib:
            raise exception.VolumeBackendAPIException(
                data=(_("RSDLib is not available, please install rsd-lib.")))

        try:
            rsdlib = RSDLib(url, username, password, verify=verify).factory()
        except Exception:
            # error credentials may throw unexpected exception
            LOG.exception("Cannot connect to RSD PODM")
            raise exception.VolumeBackendAPIException(
                data=_("initialize: Cannot connect to RSD PODM."))

        rsd_api_version = version.LooseVersion(rsdlib._rsd_api_version)
        if rsd_api_version < version.LooseVersion("2.4.0"):
            raise exception.VolumeBackendAPIException(
                data=(_("initialize: Unsupported rsd_api version: "
                        "%(current)s < %(expected)s.")
                      % {'current': rsdlib._rsd_api_version,
                         'expected': "2.4.0"}))

        if rsdlib._redfish_version < version.LooseVersion("1.1.0"):
            raise exception.VolumeBackendAPIException(
                data=(_("initialize: Unsupported rsd_lib version: "
                        "%(current)s < %(expected)s.")
                      % {'current': rsdlib._redfish_version,
                         'expected': "1.1.0"}))

        LOG.info("initialize: Connected to %s at version %s.",
                 url, rsdlib._rsd_api_version)
        return cls(rsdlib)

    def _get_storage(self, storage_url):
        ss_url = "/".join(storage_url.split("/", 5)[:5])
        storage_service = self.rsdlib.get_storage_service(ss_url)
        return storage_service

    def _get_storages(self, filter_nvme=True):
        ret = []
        for storage in (self.rsdlib
                        .get_storage_service_collection().get_members()):
            if filter_nvme:
                drives = storage.drives.get_members()
                if drives and (any(map(lambda drive:
                                       False if not drive.protocol
                                       else 'nvme' in drive.protocol.lower(),
                                       drives))):
                    ret.append(storage)
            else:
                ret.append(storage)
        return ret

    def _get_node(self, node_url):
        return self.rsdlib.get_node(node_url)

    def _get_volume(self, volume_url):
        ss = self._get_storage(volume_url)
        volume = ss.volumes.get_member(volume_url)
        return volume

    def _get_providing_pool(self, volume):
        len_cs = len(volume.capacity_sources)
        if len_cs != 1:
            raise exception.ValidationError(
                detail=(_("Volume %(vol)s has %(len_cs)d capacity_sources!")
                        % {'vol': volume.path,
                           'len_cs': len_cs}))
        len_pp = len(volume.capacity_sources[0].providing_pools)
        if len_pp != 1:
            raise exception.ValidationError(
                detail=(_("Volume %(vol)s has %(len_pp)d providing_pools!")
                        % {'vol': volume.path,
                           'len_pp': len_pp}))
        providing_pool = volume.capacity_sources[0].providing_pools[0]
        return providing_pool.get_members()[0].path

    def _create_vol_or_snap(self,
                            storage,
                            size_in_bytes,
                            pool_url=None,
                            source_snap=None,
                            source_vol=None):
        capacity_sources = None
        if pool_url:
            capacity_sources = [{
                "ProvidingPools": [{
                    "@odata.id": pool_url
                }]
            }]

        replica_infos = None
        if source_snap:
            replica_infos = [{
                "ReplicaType": "Clone",
                "Replica": {"@odata.id": source_snap}
            }]
            if source_vol:
                raise exception.InvalidInput(
                    reason=(_("Cannot specify both source_snap=%(snap)s and "
                              "source_vol=%(vol)s!")
                            % {'snap': source_snap,
                               'vol': source_vol}))
        elif source_vol:
            replica_infos = [{
                "ReplicaType": "Snapshot",
                "Replica": {"@odata.id": source_vol}
            }]

        LOG.debug("Creating... with size_byte=%s, "
                  "capacity_sources=%s, replica_infos=%s",
                  size_in_bytes, capacity_sources, replica_infos)
        volume_url = storage.volumes.create_volume(
            size_in_bytes,
            capacity_sources=capacity_sources,
            replica_infos=replica_infos)
        LOG.debug("Created volume_url=%s", volume_url)
        return volume_url

    def create_volume(self, size_in_gb):
        size_in_bytes = size_in_gb * units.Gi
        try:
            for storage in self._get_storages():
                try:
                    volume_url = self._create_vol_or_snap(
                        storage, size_in_bytes)
                    LOG.info("RSD volume %s created, with size %s GiB",
                             volume_url, size_in_gb)
                    return volume_url
                # NOTE(Yingxin): Currently, we capture sushy_exception to
                # identify that volume creation is failed at RSD backend.
                except (sushy_exceptions.HTTPError,
                        sushy_exceptions.ConnectionError) as e:
                    LOG.warning("skipped storage %s for creation error %s",
                                storage.path, e)
        except Exception:
            LOG.exception("Create volume failed")

        raise exception.VolumeBackendAPIException(
            data=(_('Unable to create new volume with %d GiB') % size_in_gb))

    def create_snap(self, volume_url):
        try:
            ss = self._get_storage(volume_url)
            volume = self._get_volume(volume_url)
            pool_url = self._get_providing_pool(volume)
            snap_url = self._create_vol_or_snap(
                ss, volume.capacity_bytes,
                pool_url=pool_url,
                source_vol=volume_url)
            LOG.info("RSD snapshot %s created, from volume %s",
                     snap_url, volume_url)
            return snap_url
        except Exception:
            LOG.exception("Create snapshot failed")
            raise exception.VolumeBackendAPIException(
                data=(_('Unable to create snapshot from volume %s')
                      % volume_url))

    def create_volume_from_snap(self, snap_url, size_in_gb=None):
        try:
            ss = self._get_storage(snap_url)
            snap = self._get_volume(snap_url)
            if not size_in_gb:
                size_in_bytes = snap.capacity_bytes
            else:
                size_in_bytes = size_in_gb * units.Gi
            pool_url = self._get_providing_pool(snap)
            volume_url = self._create_vol_or_snap(
                ss, size_in_bytes,
                pool_url=pool_url,
                source_snap=snap_url)
            LOG.info("RSD volume %s created, from snap %s, "
                     "with size %s GiB.",
                     volume_url, snap_url,
                     size_in_bytes / units.Gi)
            return volume_url
        except Exception:
            LOG.exception("Create volume from snapshot failed")
            raise exception.VolumeBackendAPIException(
                data=(_('Unable to create volume from snapshot %s')
                      % snap_url))

    def clone_volume(self, volume_url, size_in_gb=None):
        try:
            ss = self._get_storage(volume_url)
            origin_volume = self._get_volume(volume_url)
            pool_url = self._get_providing_pool(origin_volume)
            snap_url = self._create_vol_or_snap(
                ss, origin_volume.capacity_bytes,
                pool_url=pool_url,
                source_vol=volume_url)
        except Exception:
            LOG.exception("Clone volume failed (create snapshot phase)")
            raise exception.VolumeBackendAPIException(
                data=(_('Unable to create volume from volume %s, snapshot '
                        'creation failed.')
                      % volume_url))
        try:
            if not size_in_gb:
                size_in_bytes = origin_volume.capacity_bytes
            else:
                size_in_bytes = size_in_gb * units.Gi
            new_vol_url = self._create_vol_or_snap(
                ss, size_in_bytes,
                pool_url=pool_url,
                source_snap=snap_url)
            LOG.info("RSD volume %s created, from volume %s and snap %s, "
                     "with size %s GiB.",
                     new_vol_url, volume_url, snap_url,
                     size_in_bytes / units.Gi)
            return new_vol_url, snap_url
        except Exception:
            LOG.exception("Clone volume failed (clone volume phase)")
            try:
                self.delete_vol_or_snap(snap_url)
            except Exception:
                LOG.exception("Clone volume failed (undo snapshot)")
                raise exception.VolumeBackendAPIException(
                    data=(_('Unable to delete the temp snapshot %(snap)s, '
                            'during a failure to clone volume %(vol)s.')
                          % {'snap': snap_url,
                             'vol': volume_url}))
            raise exception.VolumeBackendAPIException(
                data=(_('Unable to create volume from volume %s, volume '
                        'creation failed.')
                      % volume_url))

    def extend_volume(self, volume_url, size_in_gb):
        size_in_bytes = size_in_gb * units.Gi
        try:
            volume = self._get_volume(volume_url)
            volume.resize(size_in_bytes)
            LOG.info("RSD volume %s resized to %s Bytes",
                     volume.path, size_in_bytes)
        except Exception:
            LOG.exception("Extend volume failed")
            raise exception.VolumeBackendAPIException(
                data=(_('Unable to extend volume %s.') % volume_url))

    def delete_vol_or_snap(self, volume_url,
                           volume_name='', ignore_non_exist=False):
        try:
            try:
                volume = self._get_volume(volume_url)
            except sushy_exceptions.ResourceNotFoundError:
                if ignore_non_exist:
                    LOG.warning("Deleted non existent vol/snap %s", volume_url)
                else:
                    raise
            if volume.links.endpoints:
                LOG.warning("Delete vol/snap failed, attached: %s", volume_url)
                raise exception.VolumeIsBusy(_("Volume is already attached"),
                                             volume_name=volume_name)
            volume.delete()
        except sushy_exceptions.BadRequestError as e:
            try:
                msg = e.body['@Message.ExtendedInfo'][0]['Message']
                if (msg == "Cannot delete source snapshot volume when "
                           "other clone volumes are based on this snapshot."):
                    LOG.warning("Delete vol/snap failed, has-deps: %s",
                                volume_url)
                    raise exception.SnapshotIsBusy(snapshot_name=volume_name)
            except Exception:
                LOG.exception("Delete vol/snap failed")
                raise exception.VolumeBackendAPIException(
                    data=(_('Unable to delete volume %s.') % volume_url))
        except Exception:
            LOG.exception("Delete vol/snap failed")
            raise exception.VolumeBackendAPIException(
                data=(_('Unable to delete volume %s.') % volume_url))
        LOG.info("RSD volume deleted: %s", volume_url)

    def get_node_url_by_uuid(self, uuid):
        uuid = uuid.upper()
        try:
            nodes = self.rsdlib.get_node_collection().get_members()
            for node in nodes:
                node_system = None
                if node:
                    node_system = self.rsdlib.get_system(
                        node.links.computer_system)
                if (node and
                        node_system and
                        node_system.uuid and
                        node_system.uuid.upper() == uuid):
                    return node.path
        except Exception:
            LOG.exception("Get node url failed")
        return ""

    def get_stats(self):
        free_capacity_gb = 0
        total_capacity_gb = 0
        allocated_capacity_gb = 0
        total_volumes = 0
        try:
            storages = self._get_storages()
            for storage in storages:
                for pool in storage.storage_pools.get_members():
                    total_capacity_gb += (
                        float(pool.capacity.allocated_bytes or 0) / units.Gi)
                    allocated_capacity_gb += (
                        float(pool.capacity.consumed_bytes or 0) / units.Gi)
                total_volumes += len(storage.volumes.members_identities)
            free_capacity_gb = total_capacity_gb - allocated_capacity_gb
            LOG.info("Got RSD stats: free_gb:%s, total_gb:%s, "
                     "allocated_gb:%s, volumes:%s",
                     free_capacity_gb,
                     total_capacity_gb,
                     allocated_capacity_gb,
                     total_volumes)
        except Exception:
            LOG.exception("Get stats failed")

        return (free_capacity_gb,
                total_capacity_gb,
                allocated_capacity_gb,
                total_volumes)

    def _get_nqn_endpoints(self, endpoint_urls):
        ret = []
        for endpoint_url in endpoint_urls:
            endpoint_json = (
                json.loads(self.rsdlib._conn.get(endpoint_url).text))
            for ident in endpoint_json["Identifiers"]:
                if ident["DurableNameFormat"] == "NQN":
                    nqn = ident["DurableName"]
                    ret.append((nqn, endpoint_json))
                    break
        return ret

    @utils.retry(RSDRetryableException,
                 interval=4,
                 retries=5,
                 backoff_rate=2)
    def attach_volume_to_node(self, volume_url, node_url):
        LOG.info('Trying attach from node %s to volume %s',
                 node_url, volume_url)
        try:
            volume = self._get_volume(volume_url)
            node = self._get_node(node_url)
            if len(volume.links.endpoints) > 0:
                raise exception.ValidationError(
                    detail=(_("Volume %s already attached") % volume_url))

            node.attach_endpoint(volume.path)
        except sushy_exceptions.InvalidParameterValueError:
            LOG.exception("Attach volume failed (not allowable)")
            raise RSDRetryableException(
                reason=(_("Not allowed to attach from "
                          "%(node)s to %(volume)s.")
                        % {'node': node_url,
                           'volume': volume_url}))
        except Exception:
            LOG.exception("Attach volume failed (attach phase)")
            raise exception.VolumeBackendAPIException(
                data=(_("Attach failed from %(node)s to %(volume)s.")
                      % {'node': node_url,
                         'volume': volume_url}))
        try:
            volume.refresh()
            node.refresh()

            v_endpoints = volume.links.endpoints
            v_endpoints = self._get_nqn_endpoints(v_endpoints)
            if len(v_endpoints) != 1:
                raise exception.ValidationError(
                    detail=(_("Attach volume error: %d target nqns")
                            % len(v_endpoints)))
            target_nqn, v_endpoint = v_endpoints[0]
            ip_transports = v_endpoint["IPTransportDetails"]
            if len(ip_transports) != 1:
                raise exception.ValidationError(
                    detail=(_("Attach volume error: %d target ips")
                            % len(ip_transports)))
            ip_transport = ip_transports[0]
            target_ip = ip_transport["IPv4Address"]["Address"]
            target_port = ip_transport["Port"]

            node_system = self.rsdlib.get_system(node.links.computer_system)
            n_endpoints = tuple(
                val["@odata.id"]
                for val in node_system.json["Links"]["Endpoints"])
            n_endpoints = self._get_nqn_endpoints(n_endpoints)
            if len(n_endpoints) == 0:
                raise exception.ValidationError(
                    detail=(_("Attach volume error: %d host nqns")
                            % len(n_endpoints)))
            host_nqn, v_endpoint = n_endpoints[0]

            LOG.info('Attachment successful: Retrieved target IP %s, '
                     'target Port %s, target NQN %s and initiator NQN %s',
                     target_ip, target_port, target_nqn, host_nqn)
            return (target_ip, target_port, target_nqn, host_nqn)
        except Exception as e:
            LOG.exception("Attach volume failed (post-attach)")
            try:
                node.refresh()
                node.detach_endpoint(volume.path)
                LOG.info('Detached from node %s to volume %s',
                         node_url, volume_url)
            except Exception:
                LOG.exception("Attach volume failed (undo attach)")
                raise exception.VolumeBackendAPIException(
                    data=(_("Undo-attach failed from %(node)s to %(volume)s.")
                          % {'node': node_url,
                             'volume': volume_url}))
            if isinstance(e, exception.ValidationError):
                raise RSDRetryableException(
                    reason=(_("Validation error during post-attach from "
                              "%(node)s to %(volume)s.")
                            % {'node': node_url,
                               'volume': volume_url}))
            else:
                raise exception.VolumeBackendAPIException(
                    data=(_("Post-attach failed from %(node)s to %(volume)s.")
                          % {'node': node_url,
                             'volume': volume_url}))

    def detach_volume_from_node(self, volume_url, node_url):
        LOG.info('Trying detach from node %s for volume %s',
                 node_url, volume_url)
        try:
            volume = self._get_volume(volume_url)
            node = self._get_node(node_url)
            node.detach_endpoint(volume.path)
        except Exception:
            LOG.exception("Detach volume failed")
            raise exception.VolumeBackendAPIException(
                data=(_("Detach failed from %(node)s for %(volume)s.")
                      % {'node': node_url,
                         'volume': volume_url}))

    def detach_all_node_connections_for_volume(self, volume_url):
        try:
            volume = self._get_volume(volume_url)
            nodes = self.rsdlib.get_node_collection().get_members()
            for node in nodes:
                if node:
                    if volume.path in node.get_allowed_detach_endpoints():
                        node.detach_endpoint(volume.path)
        except Exception:
            LOG.exception("Detach failed for volume from all host "
                          "connections")
            raise exception.VolumeBackendAPIException(
                data=(_("Detach failed for %(volume)s from all host "
                        "connections.")
                      % {'volume': volume_url}))


@interface.volumedriver
class RSDDriver(driver.VolumeDriver):
    """Openstack driver to perform NVMe-oF volume management in RSD Solution

    .. code-block:: none

    Version History:
        1.0.0: Initial driver
    """

    VERSION = '1.0.0'
    CI_WIKI_NAME = 'INTEL-RSD-CI'

    def __init__(self, *args, **kwargs):
        super(RSDDriver, self).__init__(*args, **kwargs)

        self.configuration.append_config_values(RSD_OPTS)
        self.rsdClient = None

    @staticmethod
    def get_driver_options():
        return RSD_OPTS

    @volume_utils.trace
    def do_setup(self, context):
        self.rsdClient = RSDClient.initialize(
            self.configuration.podm_url,
            self.configuration.podm_username,
            self.configuration.podm_password,
            self.configuration.suppress_requests_ssl_warnings)

    def check_for_setup_error(self):
        pass

    @volume_utils.trace
    def create_volume(self, volume):
        size_in_gb = int(volume['size'])
        volume_url = self.rsdClient.create_volume(size_in_gb)
        return {'provider_location': volume_url}

    @volume_utils.trace
    def delete_volume(self, volume):
        volume_url = volume['provider_location']
        if not volume_url:
            return
        self.rsdClient.delete_vol_or_snap(volume_url,
                                          volume_name=volume.name,
                                          ignore_non_exist=True)
        provider_snap_url = volume.metadata.get("rsd_provider_snap")
        if provider_snap_url:
            self.rsdClient.delete_vol_or_snap(provider_snap_url,
                                              volume_name=volume.name,
                                              ignore_non_exist=True)

    @volume_utils.trace
    def _update_volume_stats(self):
        backend_name = (
            self.configuration.safe_get('volume_backend_name') or 'RSD')

        ret = self.rsdClient.get_stats()
        (free_capacity_gb,
         total_capacity_gb,
         allocated_capacity_gb,
         total_volumes) = ret

        spool = {}
        spool['pool_name'] = backend_name
        spool['total_capacity_gb'] = total_capacity_gb
        spool['free_capacity_gb'] = free_capacity_gb
        spool['allocated_capacity_gb'] = allocated_capacity_gb
        spool['thin_provisioning_support'] = True
        spool['thick_provisioning_support'] = True
        spool['multiattach'] = False

        self._stats['volume_backend_name'] = backend_name
        self._stats['vendor_name'] = 'Intel'
        self._stats['driver_version'] = self.VERSION
        self._stats['storage_protocol'] = 'nvmeof'
        # SinglePool
        self._stats['pools'] = [spool]

    @volume_utils.trace
    def initialize_connection(self, volume, connector, **kwargs):
        uuid = connector.get("system uuid")
        if not uuid:
            msg = _("initialize_connection error: no uuid available!")
            LOG.exception(msg)
            raise exception.VolumeBackendAPIException(msg)
        node_url = self.rsdClient.get_node_url_by_uuid(uuid)
        if not node_url:
            msg = (_("initialize_connection error: no node_url from uuid %s!")
                   % uuid)
            LOG.exception(msg)
            raise exception.VolumeBackendAPIException(msg)

        volume_url = volume['provider_location']
        target_ip, target_port, target_nqn, initiator_nqn = (
            self.rsdClient.attach_volume_to_node(volume_url, node_url))
        conn_info = {
            'driver_volume_type': 'nvmeof',
            'data': {
                'transport_type': 'rdma',
                'host_nqn': initiator_nqn,
                'nqn': target_nqn,
                'target_port': target_port,
                'target_portal': target_ip,
            }
        }
        return conn_info

    @volume_utils.trace
    def terminate_connection(self, volume, connector, **kwargs):
        if connector is None:
            # None connector means force-detach
            volume_url = volume['provider_location']
            self.rsdClient.detach_all_node_connections_for_volume(volume_url)
            return

        uuid = connector.get("system uuid")
        if not uuid:
            msg = _("terminate_connection error: no uuid available!")
            LOG.exception(msg)
            raise exception.VolumeBackendAPIException(msg)
        node_url = self.rsdClient.get_node_url_by_uuid(uuid)
        if not node_url:
            msg = (_("terminate_connection error: no node_url from uuid %s!")
                   % uuid)
            LOG.exception(msg)
            raise exception.VolumeBackendAPIException(msg)

        volume_url = volume['provider_location']
        self.rsdClient.detach_volume_from_node(volume_url, node_url)

    def ensure_export(self, context, volume):
        pass

    def create_export(self, context, volume, connector):
        pass

    def remove_export(self, context, volume):
        pass

    @volume_utils.trace
    def create_volume_from_snapshot(self, volume, snapshot):
        snap_url = snapshot.provider_location
        old_size_in_gb = snapshot.volume_size
        size_in_gb = volume.size
        volume_url = self.rsdClient.create_volume_from_snap(snap_url)
        if size_in_gb != old_size_in_gb:
            try:
                self.rsdClient.extend_volume(volume_url, size_in_gb)
            except Exception:
                self.rsdClient.delete_vol_or_snap(volume_url,
                                                  volume_name=volume.name)
                raise
        return {'provider_location': volume_url}

    @volume_utils.trace
    def create_snapshot(self, snapshot):
        volume_url = snapshot.volume.provider_location
        snap_url = self.rsdClient.create_snap(volume_url)
        snapshot.provider_location = snap_url
        snapshot.save()

    @volume_utils.trace
    def delete_snapshot(self, snapshot):
        snap_url = snapshot.provider_location
        if not snap_url:
            return
        self.rsdClient.delete_vol_or_snap(snap_url,
                                          volume_name=snapshot.name,
                                          ignore_non_exist=True)

    @volume_utils.trace
    def extend_volume(self, volume, new_size):
        volume_url = volume.provider_location
        self.rsdClient.extend_volume(volume_url, new_size)

    def clone_image(self, context, volume,
                    image_location, image_meta,
                    image_service):
        return None, False

    @volume_utils.trace
    def create_cloned_volume(self, volume, src_vref):
        volume_url = src_vref.provider_location
        old_size_in_gb = src_vref.size
        size_in_gb = volume.size
        new_vol_url, provider_snap_url = self.rsdClient.clone_volume(
            volume_url)
        metadata = get_volume_metadata(volume)
        metadata["rsd_provider_snap"] = provider_snap_url
        if size_in_gb != old_size_in_gb:
            try:
                self.rsdClient.extend_volume(new_vol_url, size_in_gb)
            except Exception:
                self.rsdClient.delete_vol_or_snap(new_vol_url,
                                                  volume_name=volume.name)
                self.rsdClient.delete_vol_or_snap(provider_snap_url,
                                                  volume_name=volume.name)
                raise
        return {'provider_location': new_vol_url,
                'metadata': metadata}
