# Copyright 2025 VAST Data Inc.
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
from datetime import timedelta
import random

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import timeutils
from oslo_utils import units

from cinder.common import constants
from cinder import coordination
from cinder import exception
from cinder.i18n import _
from cinder import interface
from cinder.volume import configuration as config
from cinder.volume import driver
from cinder.volume.drivers.san import san
import cinder.volume.drivers.vastdata.rest as vast_rest
import cinder.volume.drivers.vastdata.utils as vast_utils
from cinder.volume import volume_utils


LOG = logging.getLogger(__name__)


VASTDATA_OPTS = [
    cfg.StrOpt(
        "vast_vippool_name",
        help="Name of Virtual IP pool"
    ),
    cfg.StrOpt(
        "vast_subsystem",
        help="VAST subsystem name"
    ),
    cfg.StrOpt(
        "vast_tenant_name",
        help="VAST tenant name – "
             "required for additional filtering when "
             "multiple subsystems share the same name."
    ),
    cfg.StrOpt(
        "vast_volume_prefix",
        help="Volume name prefix",
        default="openstack-vol-"
    ),
    cfg.StrOpt(
        "vast_snapshot_prefix",
        help="Snapshot name prefix",
        default="openstack-snap-"
    ),
    cfg.StrOpt(
        "vast_api_token",
        default="",
        secret=True,
        help=(
            "API token for accessing VAST mgmt. "
            "If provided, it will be used instead "
            "of 'san_login' and 'san_password'."
        )
    ),
]

CONF = cfg.CONF
CONF.register_opts(VASTDATA_OPTS, group=config.SHARED_CONF_GROUP)


@interface.volumedriver
class VASTVolumeDriver(driver.BaseVD):
    """VAST Data Volume Driver.

    .. code-block:: default

      Version history:
        1.0.0 - Initial version
    """

    VERSION = "1.0.0"
    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "VASTData_CI"

    driver_prefix = "vastdata"

    def __init__(self, *args, **kwargs):
        super(VASTVolumeDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(san.san_opts)
        self.configuration.append_config_values(VASTDATA_OPTS)
        self.backend_name = None
        self.rest = None
        self.subsystem = None
        self.vippool_name = None

    @volume_utils.trace
    def do_setup(self, context):
        """Driver initialization"""
        backend_name = self.configuration.safe_get("volume_backend_name")
        self.backend_name = backend_name or self.__class__.__name__
        self.subsystem = self.configuration.safe_get("vast_subsystem")
        self.tenant_name = self.configuration.safe_get("vast_tenant_name")
        if not self.subsystem:
            raise exception.InvalidConfigurationValue(
                option='vast_subsystem',
                value=self.subsystem
            )
        self.vippool_name = self.configuration.safe_get("vast_vippool_name")
        if not self.vippool_name:
            raise exception.InvalidConfigurationValue(
                option='vast_vippool_name',
                value=self.vippool_name
            )
        self.rest = vast_rest.RestApi(
            self.configuration,
            plugin_version=self.VERSION,
        )
        self.rest.do_setup()

    @classmethod
    def get_driver_options(cls):
        additional_opts = driver.BaseVD._get_oslo_driver_opts(
            "san_ip",
            "san_login",
            "san_password",
            "san_api_port",
            "driver_ssl_cert_verify",
            "driver_ssl_cert_path",
            "reserved_percentage",
        )
        return VASTDATA_OPTS + additional_opts

    def check_for_setup_error(self):
        """Verify that requirements are in place to use"""
        pass

    def _get_vast_volume(self, volume, fail_if_missing=True):
        """Get VAST volume by Cinder volume object.

        This method search by name__endswith
        because volume group and volume prefix
        are part of the name, and they can be modified
        manually by the user in cinder.conf.
        """
        vast_volume = self.rest.volumes.one(name__endswith=volume.id)
        if not vast_volume and fail_if_missing:
            raise exception.VolumeNotFound(volume_id=volume.id)
        return vast_volume

    def _get_vast_snapshot(self, snapshot, fail_if_missing=True):
        """Get VAST snapshot by Cinder snapshot object.

        This method search by name__endswith because  snap prefix
        are part of the name, and they can be modified
        manually by the user in cinder.conf.
        """
        vast_snap = self.rest.snapshots.one(name__endswith=snapshot.id)
        if not vast_snap and fail_if_missing:
            raise exception.SnapshotNotFound(snapshot_id=snapshot.id)
        return vast_snap

    def _is_multiattach(self, volume, host_name):
        """Returns True if the volume is attached to multiple instances"""
        if volume.multiattach:
            attachment_list = volume.volume_attachment
            if not attachment_list:
                return False
            attachment = [
                a for a in attachment_list
                if a.attach_status == "attached" and
                a.attached_host == host_name
            ]
            if len(attachment) > 1:
                LOG.info("Volume %(volume)s is attached to multiple "
                         "instances on host %(host_name)s, "
                         "skip terminate volume connection",
                         {'volume': volume.name,
                          'host_name': volume.host})
                return True
        return False

    @volume_utils.trace
    def create_volume(self, volume):
        """Driver entry point for creating a new volume."""
        volume_name = vast_utils.make_volume_name(
            volume,
            self.configuration,
        )
        capacity = volume.size * units.Gi
        subsystem = self.rest.views.get_subsystem(
            subsystem=self.subsystem,
            tenant_name=self.tenant_name,
        )
        self.rest.volumes.ensure(
            name=volume_name,
            view_id=subsystem.id,
            size=capacity,
        )

    @volume_utils.trace
    def delete_volume(self, volume):
        """Driver entry point for deleting a volume."""
        vast_volume = self._get_vast_volume(volume, False)
        if vast_volume:
            # Delete GSS if volume was cloned from snapshot or another volume.
            delete_gss = False
            if volume.source_volid:
                delete_gss = True
                LOG.info(
                    "Deleting GSS sourced from volume: %s",
                    volume.source_volid
                )
            elif volume.snapshot_id:
                delete_gss = True
                LOG.info(
                    "Deleting GSS sourced from snapshot: %s",
                    volume.snapshot_id
                )
            if delete_gss:
                self.rest.globalsnapstreams.ensure_snapshot_stream_deleted(
                    volume_id=volume.id
                )
            self.rest.volumes.delete_by_id(vast_volume.id)

    def ensure_export(self, context, volume):
        """Ensures that a volume is exported.

        For the VAST Data driver, this method only verifies that the
        specified volume exists. The actual export configuration is
        handled dynamically during connection initialization and does
        not require persistent export setup.
        """
        self._get_vast_volume(volume)

    def remove_export(self, context, volume):
        """Removes the export configuration for a volume.

        This method is intentionally left as a no-op to align with the
        implementation of the `create_export` method. Export-related
        operations are handled during the connection initialization
        and termination processes.
        """
        pass

    def create_export(self, context, volume, connector):
        """Driver entry point to get export info for new volume."""
        pass

    @volume_utils.trace
    def extend_volume(self, volume, new_size):
        """Extend the size of a volume."""
        vast_volume = self._get_vast_volume(volume)
        new_size = new_size * units.Gi
        self.rest.volumes.update(vast_volume.id, size=new_size)

    @volume_utils.trace
    def _update_volume_stats(self):
        """Retrieve stats info"""
        data = dict(
            volume_backend_name=self.backend_name,
            vendor_name="VAST Data",
            driver_version=self.VERSION,
            storage_protocol=constants.NVMEOF_VARIANT_2,
        )
        metrics = self.rest.capacity_metrics.get()
        total_capacity_gb = "unknown"
        free_capacity_gb = "unknown"
        if metrics:
            total_capacity_gb = float(metrics.logical_space) / units.Gi
            free_capacity_gb = (
                float(
                    metrics.logical_space - metrics.logical_space_in_use
                ) / units.Gi
            )
        single_pool = dict(
            pool_name=self.backend_name,
            total_capacity_gb=total_capacity_gb,
            free_capacity_gb=free_capacity_gb,
            reserved_percentage=self.configuration.reserved_percentage,
            QoS_support=False,
            multiattach=True,
            thin_provisioning_support=False,
            consistent_group_snapshot_enabled=False,

        )
        data["pools"] = [single_pool]
        self._stats = data

    @volume_utils.trace
    @coordination.synchronized('{self.driver_prefix}-{volume.id}')
    def initialize_connection(self, volume, connector, **kwargs):
        """Establishes a connection to the volume.

        Associates the specified volume with
         a compute node or host, enabling it
        to be accessed from that host. Example return values:

        .. code-block:: default

           {
               'driver_volume_type': 'nvmeof',
               'data': {
                   'target_nqn': 'nqn.2025-01.example.storage:subsystem',
                   'initiator_nqn': 'nqn.2025-01.example.client:string',
                   'portals': [
                       ('192.168.1.1', '4430', 'tcp')
                   ],
                   'volume_nguid': 'b2134f8e-9378-4d2b-af12-5dfe7c9a84bc',
                   'volume_uuid': 'b2134f8e-9378-4d2b-af12-5dfe7c9a84bc',
               }
           }
        """
        vast_volume = self._get_vast_volume(volume)
        subsystem = self.rest.views.get_subsystem_by_id(
            entry_id=vast_volume.view_id
        )
        vol_id = vast_volume.id
        vol_uuid = vast_volume.uuid
        vol_nguid = vast_volume.nguid
        target_nqn = subsystem.nqn
        tenant_id = subsystem.tenant_id
        host_nqn = connector.get("nqn")
        host_name = connector.get("host")
        if not host_nqn:
            # nvmet helper is missing?
            # Check if cinder was properly configured to use nvme cli
            # See options: CINDER_TARGET_PROTOCOL and CINDER_TARGET_HELPER
            raise exception.VolumeDriverException(
                message=_(
                    "Initialize connection error: no host nqn available!"
                )
            )
        target_ips = self.rest.vip_pools.get_vips(self.vippool_name)
        blockhost = self.rest.blockhosts.ensure(
            name=host_name,
            nqn=host_nqn,
            tenant_id=tenant_id,
        )
        self.rest.blockhostmappings.ensure_map(
            volume_id=vol_id,
            host_id=blockhost.id,
        )
        # Shuffle IPs consistently using host_nqn as the seed
        random.seed(host_nqn)  # Use host_nqn as the random seed
        shuffled_ips = random.sample(target_ips, min(len(target_ips), 16))
        portals = [
            (
                ip,
                vast_utils.NVME_CONNECT_PORT,
                vast_utils.NVME_CONNECT_PROTOCOL,
            )
            for ip in shuffled_ips
        ]
        # Preparing connection info dict to return
        data = {
            "target_nqn": target_nqn,
            "host_nqn": blockhost.nqn,
            "portals": portals,
            "volume_nguid": vol_nguid,
            "volume_uuid": vol_uuid,
        }
        conn_info = {
            "driver_volume_type": constants.NVMEOF_VARIANT_2,
            "data": data
        }
        LOG.info("initialize_connection - conn_info=%s", conn_info)
        return conn_info

    @volume_utils.trace
    @coordination.synchronized('{self.driver_prefix}-{volume.id}')
    def terminate_connection(self, volume, connector, **kwargs):
        """Terminates a connection to the volume."""
        vast_volume = self._get_vast_volume(volume, False)
        host = connector.get("host")
        if vast_volume:
            if self._is_multiattach(volume=volume, host_name=host):
                return
            self.rest.blockhostmappings.ensure_unmap(
                volume__id=vast_volume.id,
                block_host__name=host,
            )

    @volume_utils.trace
    def create_volume_from_snapshot(self, volume, snapshot):
        """Create Volume from snapshot.

         Args:
             volume: volume to be created
             snapshot: source snapshot from which the volume to be created.
         """
        volume_name = vast_utils.make_volume_name(
            volume,
            self.configuration,
        )
        subsystem = self.rest.views.get_subsystem(
            subsystem=self.subsystem,
            tenant_name=self.tenant_name,
        )
        vast_snapshot = self._get_vast_snapshot(snapshot)
        # Ensuring destination volume exists
        dest_vast_volume = self._get_vast_volume(
            volume,
            fail_if_missing=False,
        )
        if not dest_vast_volume:
            dest_vast_volume = self.rest.snapshots.clone_volume(
                snapshot_id=vast_snapshot.id,
                target_subsystem_id=subsystem.id,
                target_volume_path=volume_name,
            )
        # Resize destination volume if needed
        dest_capacity = volume.size * units.Gi
        src_capacity = snapshot.volume_size * units.Gi
        if dest_capacity > src_capacity:
            LOG.info(
                "Resizing volume %s to %d GiB",
                volume_name,
                dest_capacity,
            )
            self.rest.volumes.update(
                dest_vast_volume.id,
                size=dest_capacity,
            )

    @volume_utils.trace
    def create_cloned_volume(self, volume, src_vref):
        """Create volume from source volume

        Args:
            volume: volume to be created
            src_vref: source volume from which the volume to be created.
        """
        volume_name = vast_utils.make_volume_name(
            volume,
            self.configuration,
        )
        source_vast_volume = self._get_vast_volume(src_vref)
        source_subsystem = self.rest.views.get_subsystem_by_id(
            entry_id=source_vast_volume.view_id,
        )
        # Might be a different subsystem than the source subsystem
        # if the driver has been reconfigured.
        target_subsystem = self.rest.views.get_subsystem(
            subsystem=self.subsystem,
            tenant_name=self.tenant_name,
        )
        # Create intermediate snapshot with limited expiration time
        snap_name = vast_utils.make_snapshot_name(
            src_vref,
            self.configuration,
        )
        source_path = vast_utils.concatenate_paths_abs(
            source_subsystem.path,
            source_vast_volume.name,
        )
        # Set a 5-minute expiration time for the temporary snapshot.
        # If the cloning process exceeds this time,
        # the snapshot will be preserved and not deleted during processing.
        expiration_delta = timedelta(minutes=5)
        expiration_time = timeutils.utcnow() + expiration_delta
        vast_snapshot = self.rest.snapshots.ensure(
            name=snap_name,
            path=source_path,
            tenant_id=source_subsystem.tenant_id,
            expiration_time=expiration_time.isoformat(),
        )
        dest_vast_volume = self._get_vast_volume(
            volume,
            fail_if_missing=False,
        )
        if not dest_vast_volume:
            dest_vast_volume = self.rest.snapshots.clone_volume(
                snapshot_id=vast_snapshot.id,
                target_subsystem_id=target_subsystem.id,
                target_volume_path=volume_name,
            )
        # Resize destination volume if needed
        dest_capacity = volume.size * units.Gi
        src_capacity = src_vref.size * units.Gi
        if dest_capacity > src_capacity:
            LOG.info(
                "Resizing volume %s to %d GiB",
                volume_name,
                dest_capacity,
            )
            self.rest.volumes.update(
                dest_vast_volume.id,
                size=dest_capacity,
            )

    @volume_utils.trace
    def create_snapshot(self, snapshot):
        """Creates a snapshot from volume."""
        volume = snapshot.volume
        vast_volume = self._get_vast_volume(volume)
        subsystem = self.rest.views.get_subsystem_by_id(
            entry_id=vast_volume.view_id,
        )
        # Full path is concatenation of subsystem path and volume name.
        destination_path = vast_utils.concatenate_paths_abs(
            subsystem.path,
            vast_volume.name,
        )
        snap_name = vast_utils.make_snapshot_name(snapshot, self.configuration)
        self.rest.snapshots.ensure(
            name=snap_name,
            path=destination_path,
            tenant_id=subsystem.tenant_id,
        )

    @volume_utils.trace
    def delete_snapshot(self, snapshot):
        """Deletes a snapshot.

        Before deletion, checks if the snapshot has any active cloning streams
        (Global Snapshot Streams) that are not yet finished. If active streams
        exist, the snapshot cannot be safely deleted as it may be in the
        process of being cloned to a volume.
        """
        vast_snap = self._get_vast_snapshot(snapshot, False)
        if vast_snap:
            # Check if snapshot has active cloning streams before deletion.
            # Active streams indicate ongoing clone operations that depend
            # on this snapshot.
            if self.rest.snapshots.has_not_finished_streams(vast_snap.id):
                msg = _(
                    "Cannot delete snapshot %(name)s: "
                    "snapshot has active streams."
                ) % {"name": snapshot.name}
                raise exception.VolumeDriverException(message=msg)
            self.rest.snapshots.delete_by_id(vast_snap.id)
