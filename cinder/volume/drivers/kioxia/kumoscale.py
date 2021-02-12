#    (c)  Copyright  Kioxia Corporation 2021 All Rights Reserved.
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

"""Volume driver for KIOXIA KumoScale NVMeOF storage system."""


from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils.secretutils import md5

from cinder import exception
from cinder.i18n import _
from cinder import interface
from cinder.volume import driver
from cinder.volume.drivers.kioxia import entities
from cinder.volume.drivers.kioxia import rest_client

LOG = logging.getLogger(__name__)

KUMOSCALE_OPTS = [
    cfg.StrOpt("kioxia_url", help="KumoScale provisioner REST API URL"),
    cfg.StrOpt("kioxia_cafile", help="Cert for provisioner REST API SSL"),
    cfg.StrOpt("kioxia_token", help="KumoScale Provisioner auth token."),
    cfg.IntOpt(
        "kioxia_num_replicas", default=1,
        help="Number of volume replicas."),
    cfg.IntOpt(
        "kioxia_max_iops_per_gb", default=0, help="Upper limit for IOPS/GB."),
    cfg.IntOpt(
        "kioxia_desired_iops_per_gb", default=0, help="Desired IOPS/GB."),
    cfg.IntOpt(
        "kioxia_max_bw_per_gb", default=0,
        help="Upper limit for bandwidth in B/s per GB."),
    cfg.IntOpt(
        "kioxia_desired_bw_per_gb", default=0,
        help="Desired bandwidth in B/s per GB."),
    cfg.BoolOpt(
        "kioxia_same_rack_allowed", default=False,
        help="Can more than one replica be allocated to same rack."),
    cfg.IntOpt(
        "kioxia_block_size", default=4096,
        help="Volume block size in bytes - 512 or 4096 (Default)."),
    cfg.BoolOpt(
        "kioxia_writable", default=False,
        help="Volumes from snapshot writeable or not."),
    cfg.StrOpt(
        "kioxia_provisioning_type", default="THICK",
        choices=[
            ('THICK', 'Thick provisioning'), ('THIN', 'Thin provisioning')],
        help="Thin or thick volume, Default thick."),
    cfg.IntOpt(
        "kioxia_vol_reserved_space_percentage", default=0,
        help="Thin volume reserved capacity allocation percentage."),
    cfg.IntOpt(
        "kioxia_snap_reserved_space_percentage", default=0,
        help="Percentage of the parent volume to be used for log."),
    cfg.IntOpt(
        "kioxia_snap_vol_reserved_space_percentage", default=0,
        help="Writable snapshot percentage of parent volume used for log."),
    cfg.IntOpt(
        "kioxia_max_replica_down_time", default=0,
        help="Replicated volume max downtime for replica in minutes."),
    cfg.BoolOpt(
        "kioxia_span_allowed", default=True,
        help="Allow span - Default True."),
    cfg.BoolOpt(
        "kioxia_snap_vol_span_allowed", default=True,
        help="Allow span in snapshot volume - Default True.")
]

CONF = cfg.CONF
CONF.register_opts(KUMOSCALE_OPTS)


@interface.volumedriver
class KumoScaleBaseVolumeDriver(driver.BaseVD):
    """Performs volume management on KumoScale Provisioner.

    Version history:

    .. code-block:: none

        1.0.0 - Initial driver version.
    """

    VERSION = '1.0.0'
    CI_WIKI_NAME = 'KIOXIA_CI'
    SUPPORTED_REST_API_VERSIONS = ['1.0', '1.1']

    def __init__(self, *args, **kwargs):
        super(KumoScaleBaseVolumeDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(KUMOSCALE_OPTS)
        self._backend_name = (
            self.configuration.volume_backend_name or self.__class__.__name__)
        self.kumoscale = self._get_kumoscale(
            self.configuration.safe_get("kioxia_url"),
            self.configuration.safe_get("kioxia_token"),
            self.configuration.safe_get("kioxia_cafile"))

        self.num_replicas = self.configuration.safe_get("kioxia_num_replicas")
        self.same_rack_allowed = self.configuration.safe_get(
            "kioxia_same_rack_allowed")
        self.max_iops_per_gb = self.configuration.safe_get(
            "kioxia_max_iops_per_gb")
        self.desired_iops_per_gb = self.configuration.safe_get(
            "kioxia_desired_iops_per_gb")
        self.max_bw_per_gb = self.configuration.safe_get(
            "kioxia_max_bw_per_gb")
        self.desired_bw_per_gb = self.configuration.safe_get(
            "kioxia_desired_bw_per_gb")
        self.block_size = self.configuration.safe_get("kioxia_block_size")
        self.writable = self.configuration.safe_get("kioxia_writable")
        self.provisioning_type = self.configuration.safe_get(
            "kioxia_provisioning_type")
        self.vol_reserved_space_percentage = self.configuration.safe_get(
            "kioxia_vol_reserved_space_percentage")
        self.snap_vol_reserved_space_percentage = self.configuration.safe_get(
            "kioxia_snap_vol_reserved_space_percentage")
        self.snap_reserved_space_percentage = self.configuration.safe_get(
            "kioxia_snap_reserved_space_percentage")
        self.max_replica_down_time = self.configuration.safe_get(
            "kioxia_max_replica_down_time")
        self.span_allowed = self.configuration.safe_get("kioxia_span_allowed")
        self.snap_vol_span_allowed = self.configuration.safe_get(
            "kioxia_snap_vol_span_allowed")

    @staticmethod
    def get_driver_options():
        return KUMOSCALE_OPTS

    def _get_kumoscale(self, url, token, cert):
        """Returns an initialized rest client"""
        url_strs = url.split(":")
        ip_str = url_strs[1]
        ip_strs = ip_str.split("//")
        ip = ip_strs[1]
        port = url_strs[2]
        kumoscale = rest_client.KioxiaProvisioner([ip], cert, token, port)
        return kumoscale

    def create_volume(self, volume):
        """Create the volume"""
        volume_name = volume["name"]
        volume_uuid = volume["id"]
        volume_size = volume["size"]
        zone_list = None if 'availability_zone' not in volume else [
            volume['availability_zone']]

        if self.num_replicas > 1 and len(volume_name) > 27:
            volume_name = volume_name[:27]  # workaround for limitation
        storage_class = entities.StorageClass(
            self.num_replicas, None, None, zone_list, self.block_size,
            self.max_iops_per_gb, self.desired_iops_per_gb, self.max_bw_per_gb,
            self.desired_bw_per_gb, self.same_rack_allowed,
            self.max_replica_down_time, None, self.span_allowed)
        ks_volume = entities.VolumeCreate(
            volume_name, volume_size, storage_class, self.provisioning_type,
            self.vol_reserved_space_percentage, 'NVMeoF', volume_uuid)

        try:
            result = self.kumoscale.create_volume(ks_volume)
        except Exception as e:
            msg = (_("Volume %(volname)s creation exception: %(txt)s") %
                   {'volname': volume_name, 'txt': str(e)})
            raise exception.VolumeBackendAPIException(data=msg)

        if result.status != 'Success':
            raise exception.VolumeBackendAPIException(data=result.description)

    def delete_volume(self, volume):
        """Delete the volume"""
        volume_uuid = volume["id"]

        try:
            result = self.kumoscale.delete_volume(volume_uuid)
        except Exception as e:
            msg = (_("Volume %(voluuid)s deletion exception: %(txt)s") %
                   {'voluuid': volume_uuid, 'txt': str(e)})
            raise exception.VolumeBackendAPIException(data=msg)

        if result.status not in ('Success', 'DeviceNotFound', 'NotExists'):
            raise exception.VolumeBackendAPIException(data=result.description)

    def create_snapshot(self, snapshot):

        snapshot_name = snapshot['name']
        snapshot_uuid = snapshot['id']
        volume_uuid = snapshot['volume_id']
        ks_snapshot = entities.SnapshotCreate(
            snapshot_name, volume_uuid,
            self.snap_reserved_space_percentage, snapshot_uuid)

        try:
            result = self.kumoscale.create_snapshot(ks_snapshot)
        except Exception as e:
            msg = (_("Snapshot %(snapname)s creation exception: %(txt)s") %
                   {'snapname': snapshot_name, 'txt': str(e)})
            raise exception.VolumeBackendAPIException(data=msg)

        if result.status != 'Success':
            raise exception.VolumeBackendAPIException(data=result.description)

    def delete_snapshot(self, snapshot):

        snapshot_uuid = snapshot['id']

        try:
            result = self.kumoscale.delete_snapshot(snapshot_uuid)
        except Exception as e:
            msg = (_("Snapshot %(snapuuid)s deletion exception: %(txt)s") %
                   {'snapuuid': snapshot_uuid, 'txt': str(e)})
            raise exception.VolumeBackendAPIException(data=msg)

        if result.status not in ('Success', 'DeviceNotFound', 'NotExists'):
            raise exception.VolumeBackendAPIException(data=result.description)

    def create_volume_from_snapshot(self, volume, snapshot):

        volume_name = volume["name"]
        volume_uuid = volume["id"]
        snapshot_uuid = snapshot["id"]
        if self.writable:
            reserved_space_percentage = self.snap_vol_reserved_space_percentage
        else:
            reserved_space_percentage = 0

        ks_snapshot_volume = entities.SnapshotVolumeCreate(
            volume_name, snapshot_uuid, self.writable,
            reserved_space_percentage, volume_uuid,
            self.max_iops_per_gb, self.max_bw_per_gb, 'NVMeoF',
            self.snap_vol_span_allowed)

        try:
            result = self.kumoscale.create_snapshot_volume(ks_snapshot_volume)
        except Exception as e:
            msg = (_("Volume %(volname)s from snapshot exception: %(txt)s") %
                   {'volname': volume_name, 'txt': str(e)})
            raise exception.VolumeBackendAPIException(data=msg)

        if result.status != 'Success':
            raise exception.VolumeBackendAPIException(data=result.description)

    def initialize_connection(self, volume, connector, initiator_data=None):
        """Connect the initiator to a volume"""
        host_uuid = connector['uuid']
        ks_volume = None
        targets = []
        volume_replicas = []
        volume_uuid = volume['id']
        volume_name = volume['name']

        try:
            result = self.kumoscale.host_probe(
                connector['nqn'], connector['uuid'],
                KumoScaleBaseVolumeDriver._convert_host_name(
                    connector['host']),
                'Agent', 'cinder-driver-0.1', 30)
        except Exception as e:
            msg = (_("Host %(uuid)s host_probe exception: %(txt)s") %
                   {'uuid': connector['uuid'], 'txt': str(e)})
            raise exception.VolumeBackendAPIException(data=msg)

        if result.status != 'Success':
            msg = (_("host_probe for %(uuid)s failed with %(txt)s") %
                   {'uuid': connector['uuid'], 'txt': result.description})
            raise exception.VolumeBackendAPIException(data=msg)

        try:
            result = self.kumoscale.publish(host_uuid, volume_uuid)
        except Exception as e:
            msg = (_("Volume %(voluuid)s publish exception: %(txt)s") %
                   {'voluuid': volume_uuid, 'txt': str(e)})
            raise exception.VolumeBackendAPIException(data=msg)

        if result.status != "Success" and result.status != 'AlreadyPublished':
            raise exception.VolumeBackendAPIException(data=result.description)

        try:
            result = self.kumoscale.get_volumes_by_uuid(volume_uuid)
        except Exception as e:
            msg = (_("Volume %(voluuid)s fetch exception: %(txt)s") %
                   {'voluuid': volume_uuid, 'txt': str(e)})
            raise exception.VolumeBackendAPIException(data=msg)

        if result.status == "Success":
            if len(result.prov_entities) == 0:
                raise exception.VolumeBackendAPIException(
                    data=_("Volume %s not found") % volume_uuid)
            else:
                ks_volume = result.prov_entities[0]
        else:
            msg = (_("get_volumes_by_uuid for %(uuid)s failed with %(txt)s") %
                   {'uuid': volume_uuid, 'txt': result.description})
            raise exception.VolumeBackendAPIException(data=msg)

        try:
            result = self.kumoscale.get_targets(host_uuid, ks_volume.uuid)
        except Exception as e:
            msg = (_("Volume %(voluuid)s get targets exception: %(txt)s") %
                   {'voluuid': volume_uuid, 'txt': str(e)})
            raise exception.VolumeBackendAPIException(data=msg)

        if result.status == "Success":
            if len(result.prov_entities) == 0:
                raise exception.VolumeBackendAPIException(
                    data=_("Volume %s targets not found") % ks_volume.uuid)
            else:
                targets = result.prov_entities

        ks_volume_replicas = ks_volume.location
        for i in range(len(targets)):
            persistent_id = str(targets[i].backend.persistentID)

            try:
                result = self.kumoscale.get_backend_by_id(persistent_id)
            except Exception as e:
                msg = (_("Backend %(backpid)s exception: %(txt)s") %
                       {'backpid': persistent_id, 'txt': str(e)})
                raise exception.VolumeBackendAPIException(data=msg)

            if result.status == "Success":
                if len(result.prov_entities) == 0:
                    raise exception.VolumeBackendAPIException(
                        data=_("Backend %s not found") % persistent_id)
                else:
                    backend = result.prov_entities[0]
            else:
                msg = (_("get_backend_by_id for %(pid)s failed with %(txt)s") %
                       {'pid': persistent_id, 'txt': result.description})
                raise exception.VolumeBackendAPIException(data=msg)

            str_portals = []
            for p in range(len(backend.portals)):
                portal = backend.portals[p]
                portal_ip = str(portal.ip)
                portal_port = str(portal.port)
                portal_transport = str(portal.transport)
                str_portals.append(
                    (portal_ip, portal_port, portal_transport))

            for j in range(len(ks_volume_replicas)):
                ks_replica = ks_volume_replicas[j]
                if str(ks_replica.backend.persistentID) == persistent_id:
                    break

            replica = dict()
            replica['vol_uuid'] = ks_replica.uuid
            replica['target_nqn'] = str(targets[i].targetName)
            replica['portals'] = str_portals

            volume_replicas.append(replica)

        if len(volume_replicas) > 1:  # workaround for limitation
            volume_name = volume_name[:27]

        data = {
            'vol_uuid': volume_uuid,
            'alias': volume_name,
            'writable': ks_volume.writable,
            'volume_replicas': volume_replicas
        }

        if result.status != 'Success':
            raise exception.VolumeBackendAPIException(data=result.description)

        return {
            'driver_volume_type': 'nvmeof',
            'data': data
        }

    @staticmethod
    def _convert_host_name(name):
        if name is None:
            return ""
        if len(name) > 32:
            name = md5(name.encode('utf-8'), usedforsecurity=False).hexdigest()
        else:
            name = name.replace('.', '-').lower()
        return name

    def terminate_connection(self, volume, connector, **kwargs):
        """Terminate connection."""
        volume_uuid = volume['id']
        if connector:
            host_uuid = connector['uuid']
        else:
            host_uuid = None

        try:
            result = self.kumoscale.unpublish(host_uuid, volume_uuid)
        except Exception as e:
            msg = (_("Volume %(voluuid)s unpublish exception: %(txt)s") %
                   {'voluuid': volume_uuid, 'txt': str(e)})
            raise exception.VolumeBackendAPIException(data=msg)

        if result.status != 'Success' and (
                result.status != 'VolumeNotPublished'):
            raise exception.VolumeBackendAPIException(data=result.description)

    def _update_volume_stats(self):
        data = dict(
            volume_backend_name=self._backend_name,
            vendor_name='KIOXIA',
            driver_version=self.VERSION,
            storage_protocol='NVMeOF',
        )
        data['total_capacity_gb'] = 'unknown'
        data['free_capacity_gb'] = 'unknown'
        data['consistencygroup_support'] = False
        data['thin_provisioning_support'] = True
        data['multiattach'] = False

        result = None
        tenants = []
        try:
            result = self.kumoscale.get_tenants()
        except Exception as e:
            msg = _("Get tenants exception: %s") % str(e)
            LOG.exception(msg)

        if result and result.status == "Success":
            if len(result.prov_entities) == 0:
                LOG.error("No kumoscale tenants")
            else:
                tenants = result.prov_entities
        elif result:
            LOG.error("Get tenants API error: %s", result.description)

        default_tenant = None
        for i in range(len(tenants)):
            if tenants[i].tenantId == "0":
                default_tenant = tenants[i]
                break

        if default_tenant:
            total_capacity = default_tenant.capacity
            consumed_capacity = default_tenant.consumedCapacity
            free_capacity = total_capacity - consumed_capacity
            data['total_capacity_gb'] = total_capacity
            data['free_capacity_gb'] = free_capacity

        self._stats = data

    def extend_volume(self, volume, new_size):
        try:
            result = self.kumoscale.expand_volume(
                new_size, volume["id"])
        except Exception as e:
            msg = (_("Volume %(volid)s expand exception: %(txt)s") %
                   {'volid': volume["id"], 'txt': str(e)})
            raise exception.VolumeBackendAPIException(data=msg)
        if result.status != 'Success':
            raise exception.VolumeBackendAPIException(data=result.description)

    def create_cloned_volume(self, volume, src_vref):
        clone_entity = entities.CloneEntity(
            src_vref['id'], volume['name'],
            volumeId=volume['id'],
            capacity=volume['size'])
        try:
            result = self.kumoscale.clone_volume(clone_entity)
        except Exception as e:
            msg = (_("Volume %(volid)s clone exception: %(txt)s") %
                   {'volid': volume["id"], 'txt': str(e)})
            raise exception.VolumeBackendAPIException(data=msg)
        if result.status != 'Success':
            raise exception.VolumeBackendAPIException(data=result.description)

    def create_export(self, context, volume, connector):
        pass

    def ensure_export(self, context, volume):
        pass

    def remove_export(self, context, volume):
        pass

    def check_for_setup_error(self):
        pass
