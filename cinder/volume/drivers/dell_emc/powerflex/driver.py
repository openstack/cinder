# Copyright (c) 2017-2020 Dell Inc. or its subsidiaries.
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
Driver for Dell EMC PowerFlex (formerly named Dell EMC VxFlex OS).
"""

import math
from operator import xor

from os_brick import initiator
from oslo_config import cfg
from oslo_log import log as logging
from oslo_log import versionutils
from oslo_service import loopingcall
from oslo_utils import excutils
from oslo_utils import units
import six
from six.moves import http_client

from cinder import context
from cinder import exception
from cinder.i18n import _
from cinder.image import image_utils
from cinder import interface
from cinder import objects
from cinder.objects import fields
from cinder import utils
from cinder.volume import configuration
from cinder.volume import driver
from cinder.volume.drivers.dell_emc.powerflex import options
from cinder.volume.drivers.dell_emc.powerflex import rest_client
from cinder.volume.drivers.dell_emc.powerflex import utils as flex_utils
from cinder.volume.drivers.san import san
from cinder.volume import manager
from cinder.volume import qos_specs
from cinder.volume import volume_types
from cinder.volume import volume_utils

CONF = cfg.CONF

powerflex_opts = options.deprecated_opts + options.actual_opts

CONF.register_opts(powerflex_opts, group=configuration.SHARED_CONF_GROUP)

LOG = logging.getLogger(__name__)


PROVISIONING_KEY = "provisioning:type"
REPLICATION_CG_KEY = "powerflex:replication_cg"
QOS_IOPS_LIMIT_KEY = "maxIOPS"
QOS_BANDWIDTH_LIMIT = "maxBWS"
QOS_IOPS_PER_GB = "maxIOPSperGB"
QOS_BANDWIDTH_PER_GB = "maxBWSperGB"

BLOCK_SIZE = 8
VOLUME_NOT_FOUND_ERROR = 79
# This code belongs to older versions of PowerFlex
VOLUME_NOT_MAPPED_ERROR = 84
VOLUME_ALREADY_MAPPED_ERROR = 81
MIN_BWS_SCALING_SIZE = 128
POWERFLEX_MAX_OVERSUBSCRIPTION_RATIO = 10.0


@interface.volumedriver
class PowerFlexDriver(driver.VolumeDriver):
    """Cinder PowerFlex(formerly named Dell EMC VxFlex OS) Driver

    .. code-block:: none

      Version history:
          2.0.1 - Added support for SIO 1.3x in addition to 2.0.x
          2.0.2 - Added consistency group support to generic volume groups
          2.0.3 - Added cache for storage pool and protection domains info
          2.0.4 - Added compatibility with os_brick>1.15.3
          2.0.5 - Change driver name, rename config file options
          3.0.0 - Add support for VxFlex OS 3.0.x and for volumes compression
          3.5.0 - Add support for PowerFlex 3.5.x
          3.5.1 - Add volume replication v2.1 support for PowerFlex 3.5.x
          3.5.2 - Add volume migration support
          3.5.3 - Add revert volume to snapshot support
          3.5.4 - Fix for Bug #1823200. See OSSN-0086 for details.
          3.5.5 - Rebrand VxFlex OS to PowerFlex.
          3.5.6 - Fix for Bug #1897598 when volume can be migrated without
                  conversion of its type.
    """

    VERSION = "3.5.6"
    # ThirdPartySystems wiki
    CI_WIKI_NAME = "DellEMC_PowerFlex_CI"

    powerflex_qos_keys = (QOS_IOPS_LIMIT_KEY,
                          QOS_BANDWIDTH_LIMIT,
                          QOS_IOPS_PER_GB,
                          QOS_BANDWIDTH_PER_GB)

    def __init__(self, *args, **kwargs):
        super(PowerFlexDriver, self).__init__(*args, **kwargs)

        self.active_backend_id = kwargs.get("active_backend_id")
        self.configuration.append_config_values(san.san_opts)
        self.configuration.append_config_values(powerflex_opts)
        self.statisticProperties = None
        self.storage_pools = None
        self.provisioning_type = None
        self.connector = None
        self.replication_enabled = None
        self.replication_device = None
        self.failover_choices = None
        self.primary_client = None
        self.secondary_client = None

    def _init_vendor_properties(self):
        properties = {}
        self._set_property(
            properties,
            "powerflex:replication_cg",
            "PowerFlex Replication Consistency Group.",
            _("Specifies the PowerFlex Replication Consistency group for a "
              "volume type. Source and target volumes will be added to the "
              "specified RCG during creation."),
            "string")
        return properties, "powerflex"

    @staticmethod
    def get_driver_options():
        return powerflex_opts

    @staticmethod
    def _extract_domain_and_pool_from_host(host):
        pd_sp = volume_utils.extract_host(host, "pool")
        protection_domain_name = pd_sp.split(":")[0]
        storage_pool_name = pd_sp.split(":")[1]
        return protection_domain_name, storage_pool_name

    @property
    def _available_failover_choices(self):
        """Available choices to failover/failback host."""

        return self.failover_choices.difference({self.active_backend_id})

    @property
    def _is_failed_over(self):
        """Check if storage backend is in FAILED_OVER state.

        :return: storage backend failover state
        """

        return bool(self.active_backend_id and
                    self.active_backend_id != "default")

    def _get_client(self, secondary=False):
        """Get appropriate REST client for storage backend.

        :param secondary: primary or secondary client
        :return: REST client for storage backend
        """

        if xor(self._is_failed_over, secondary):
            return self.secondary_client
        else:
            return self.primary_client

    def do_setup(self, context):
        if not self.active_backend_id:
            self.active_backend_id = manager.VolumeManager.FAILBACK_SENTINEL
        if not self.failover_choices:
            self.failover_choices = {manager.VolumeManager.FAILBACK_SENTINEL}
        powerflex_storage_pools = (
            self.configuration.safe_get("powerflex_storage_pools")
        )
        if powerflex_storage_pools:
            self.storage_pools = [
                e.strip() for e in powerflex_storage_pools.split(",")
            ]
        LOG.info("Storage pools names: %s.", self.storage_pools)
        self.provisioning_type = (
            "thin" if self.configuration.san_thin_provision else "thick"
        )
        LOG.info("Default provisioning type: %s.", self.provisioning_type)
        self.configuration.max_over_subscription_ratio = (
            self.configuration.powerflex_max_over_subscription_ratio
        )
        self.connector = initiator.connector.InitiatorConnector.factory(
            initiator.SCALEIO,
            utils.get_root_helper(),
            self.configuration.num_volume_device_scan_tries
        )
        self.primary_client = rest_client.RestClient(self.configuration)
        self.secondary_client = rest_client.RestClient(self.configuration,
                                                       is_primary=False)
        self.primary_client.do_setup()
        self.secondary_client.do_setup()

    def check_for_setup_error(self):
        client = self._get_client()

        # validate oversubscription ratio
        if (self.configuration.max_over_subscription_ratio >
                POWERFLEX_MAX_OVERSUBSCRIPTION_RATIO):
            msg = (_("Max over subscription is configured to %(ratio)1f "
                     "while PowerFlex support up to %(powerflex_ratio)s.") %
                   {"ratio": self.configuration.max_over_subscription_ratio,
                    "powerflex_ratio": POWERFLEX_MAX_OVERSUBSCRIPTION_RATIO})
            raise exception.InvalidInput(reason=msg)
        # validate that version of PowerFlex is supported
        if not flex_utils.version_gte(client.query_rest_api_version(), "2.0"):
            # we are running against a pre-2.0.0 PowerFlex(ScaleIO) instance
            msg = (_("Using PowerFlex versions less "
                     "than v2.0 has been deprecated and will be "
                     "removed in a future version."))
            versionutils.report_deprecated_feature(LOG, msg)
        if not self.storage_pools:
            msg = (_("Must specify storage pools. "
                     "Option: powerflex_storage_pools."))
            raise exception.InvalidInput(reason=msg)
        # validate the storage pools and check if zero padding is enabled
        for pool in self.storage_pools:
            try:
                pd, sp = pool.split(":")
            except (ValueError, IndexError):
                msg = (_("Invalid storage pool name. The correct format is: "
                         "protection_domain:storage_pool. "
                         "Value supplied was: %s.") % pool)
                raise exception.InvalidInput(reason=msg)
            try:
                properties = client.get_storage_pool_properties(pd, sp)
                padded = properties["zeroPaddingEnabled"]
            except Exception:
                msg = _("Failed to query properties for pool %s.") % pool
                raise exception.InvalidInput(reason=msg)
            if not padded:
                LOG.warning("Zero padding is disabled for pool %s. "
                            "This could lead to existing data being "
                            "accessible on new provisioned volumes. "
                            "Consult the PowerFlex product documentation "
                            "for information on how to enable zero padding "
                            "and prevent this from occurring.", pool)
        # validate replication configuration
        if self.secondary_client.is_configured:
            self.replication_device = self.configuration.replication_device[0]
            self.failover_choices.add(self.replication_device["backend_id"])
            if self._is_failed_over:
                LOG.warning("Storage backend is in FAILED_OVER state. "
                            "Replication is DISABLED.")
                self.replication_enabled = False
            else:
                primary_version = self.primary_client.query_rest_api_version()
                secondary_version = (
                    self.secondary_client.query_rest_api_version()
                )
                if not (flex_utils.version_gte(primary_version, "3.5") and
                        flex_utils.version_gte(secondary_version, "3.5")):
                    LOG.info("PowerFlex versions less than v3.5 do not "
                             "support replication.")
                    self.replication_enabled = False
                else:
                    self.replication_enabled = True
        else:
            self.replication_enabled = False

    @property
    def replication_targets(self):
        """Replication targets for storage backend.

        :return: replication targets
        """

        if self.replication_enabled and not self._is_failed_over:
            return [self.replication_device]
        else:
            return []

    def _get_queryable_statistics(self, sio_type, sio_id):
        """Get statistic properties that can be obtained from PowerFlex.

        :param sio_type: PowerFlex resource type
        :param sio_id: PowerFlex resource id
        :return: statistic properties
        """

        url = "/types/%(sio_type)s/instances/action/querySelectedStatistics"
        client = self._get_client()

        if self.statisticProperties is None:
            # in PowerFlex 3.5 snapCapacityInUseInKb is replaced by
            # snapshotCapacityInKb
            if flex_utils.version_gte(client.query_rest_api_version(), "3.5"):
                self.statisticProperties = [
                    "snapshotCapacityInKb",
                    "thickCapacityInUseInKb",
                ]
            else:
                self.statisticProperties = [
                    "snapCapacityInUseInKb",
                    "thickCapacityInUseInKb",
                ]
            # PowerFlex 3.0 provide useful precomputed stats
            if flex_utils.version_gte(client.query_rest_api_version(), "3.0"):
                self.statisticProperties.extend([
                    "netCapacityInUseInKb",
                    "netUnusedCapacityInKb",
                    "thinCapacityAllocatedInKb",
                ])
                return self.statisticProperties
            self.statisticProperties.extend([
                "capacityLimitInKb",
                "spareCapacityInKb",
                "capacityAvailableForVolumeAllocationInKb",
            ])
            # version 2.0 of SIO introduced thin volumes
            if flex_utils.version_gte(client.query_rest_api_version(), "2.0"):
                # check to see if thinCapacityAllocatedInKb is valid
                # needed due to non-backwards compatible API
                params = {
                    "ids": [
                        sio_id,
                    ],
                    "properties": [
                        "thinCapacityAllocatedInKb",
                    ],
                }
                r, response = client.execute_powerflex_post_request(
                    url=url,
                    params=params,
                    sio_type=sio_type
                )
                if r.status_code == http_client.OK:
                    # is it valid, use it
                    self.statisticProperties.append(
                        "thinCapacityAllocatedInKb"
                    )
                else:
                    # it is not valid, assume use of thinCapacityAllocatedInKm
                    self.statisticProperties.append(
                        "thinCapacityAllocatedInKm"
                    )
        return self.statisticProperties

    def _setup_volume_replication(self, vol_or_snap, source_provider_id):
        """Configure replication for volume or snapshot.

        Create volume on secondary PowerFlex storage backend.
        Pair volumes and add replication pair to replication consistency group.

        :param vol_or_snap: source volume/snapshot
        :param source_provider_id: primary PowerFlex volume id
        """
        try:
            # If vol_or_snap has 'volume' attribute we are dealing
            # with snapshot. Necessary parameters is stored in volume object.
            entity = vol_or_snap.volume
            entity_type = "snapshot"
        except AttributeError:
            entity = vol_or_snap
            entity_type = "volume"
        LOG.info("Configure replication for %(entity_type)s %(id)s. ",
                 {"entity_type": entity_type, "id": vol_or_snap.id})
        try:
            protection_domain_name, storage_pool_name = (
                self._extract_domain_and_pool_from_host(entity.host)
            )
            self._check_volume_creation_safe(protection_domain_name,
                                             storage_pool_name,
                                             secondary=True)
            storage_type = self._get_volumetype_extraspecs(entity)
            rcg_name = storage_type.get(REPLICATION_CG_KEY)
            LOG.info("Replication Consistency Group name: %s.", rcg_name)
            provisioning, compression = self._get_provisioning_and_compression(
                storage_type,
                protection_domain_name,
                storage_pool_name,
                secondary=True
            )
            dest_provider_id = self._get_client(secondary=True).create_volume(
                protection_domain_name,
                storage_pool_name,
                vol_or_snap.id,
                entity.size,
                provisioning,
                compression)
            self._get_client().create_volumes_pair(rcg_name,
                                                   source_provider_id,
                                                   dest_provider_id)
            LOG.info("Successfully configured replication for %(entity_type)s "
                     "%(id)s.",
                     {"entity_type": entity_type, "id": vol_or_snap.id})
        except exception.VolumeBackendAPIException:
            with excutils.save_and_reraise_exception():
                LOG.error("Failed to configure replication for "
                          "%(entity_type)s %(id)s.",
                          {"entity_type": entity_type, "id": vol_or_snap.id})

    def _teardown_volume_replication(self, provider_id):
        """Stop volume/snapshot replication.

        Unpair volumes/snapshot and remove volume/snapshot from PowerFlex
        secondary storage backend.
        """

        if not provider_id:
            LOG.warning("Volume or snapshot does not have provider_id thus "
                        "does not map to PowerFlex volume.")
            return
        try:
            pair_id, remote_pair_id, vol_id, remote_vol_id = (
                self._get_client().get_volumes_pair_attrs("localVolumeId",
                                                          provider_id)
            )
        except exception.VolumeBackendAPIException:
            LOG.info("Replication pair for volume %s is not found. "
                     "Replication for volume was not configured or was "
                     "modified from storage side.", provider_id)
            return
        self._get_client().remove_volumes_pair(pair_id)
        if not self._is_failed_over:
            self._get_client(secondary=True).remove_volume(remote_vol_id)

    def failover_host(self, context, volumes, secondary_id=None, groups=None):
        if secondary_id not in self._available_failover_choices:
            msg = (_("Target %(target)s is not valid choice. "
                     "Valid choices: %(choices)s.") %
                   {"target": secondary_id,
                    "choices": ', '.join(self._available_failover_choices)})
            LOG.error(msg)
            raise exception.InvalidReplicationTarget(reason=msg)
        is_failback = secondary_id == manager.VolumeManager.FAILBACK_SENTINEL
        failed_over_rcgs = {}
        model_updates = []
        for volume in volumes:
            storage_type = self._get_volumetype_extraspecs(volume)
            rcg_name = storage_type.get(REPLICATION_CG_KEY)
            if not rcg_name:
                LOG.error("Replication Consistency Group is not specified in "
                          "volume %s VolumeType.", volume.id)
                failover_status = fields.ReplicationStatus.FAILOVER_ERROR
                updates = self._generate_model_updates(volume,
                                                       failover_status,
                                                       is_failback)
                model_updates.append(updates)
                continue
            if rcg_name in failed_over_rcgs:
                failover_status = failed_over_rcgs[rcg_name]
            else:
                failover_status = self._failover_replication_cg(
                    rcg_name, is_failback
                )
                failed_over_rcgs[rcg_name] = failover_status
            updates = self._generate_model_updates(volume,
                                                   failover_status,
                                                   is_failback)
            model_updates.append({"volume_id": volume.id, "updates": updates})
        self.active_backend_id = secondary_id
        self.replication_enabled = is_failback
        return secondary_id, model_updates, []

    def _failover_replication_cg(self, rcg_name, is_failback):
        """Failover/failback Replication Consistency Group on storage backend.

        :param rcg_name: name of PowerFlex Replication Consistency Group
        :param is_failback: is failover or failback
        :return: failover status of Replication Consistency Group
        """

        action = "failback" if is_failback else "failover"
        LOG.info("Perform %(action)s of Replication Consistency Group "
                 "%(rcg_name)s.", {"action": action, "rcg_name": rcg_name})
        try:
            self._get_client(secondary=True).failover_failback_replication_cg(
                rcg_name, is_failback
            )
            failover_status = fields.ReplicationStatus.FAILED_OVER
            LOG.info("Successfully performed %(action)s of Replication "
                     "Consistency Group %(rcg_name)s.",
                     {"action": action, "rcg_name": rcg_name})
        except exception.VolumeBackendAPIException:
            LOG.error("Failed to perform %(action)s of Replication "
                      "Consistency Group %(rcg_name)s.",
                      {"action": action, "rcg_name": rcg_name})
            failover_status = fields.ReplicationStatus.FAILOVER_ERROR
        return failover_status

    def _generate_model_updates(self, volume, failover_status, is_failback):
        """Generate volume model updates after failover/failback.

        Get new provider_id for volume and update volume snapshots if
        presented.
        """

        LOG.info("Generate model updates for volume %s and its snapshots.",
                 volume.id)
        error_status = (fields.ReplicationStatus.ERROR if is_failback else
                        fields.ReplicationStatus.FAILOVER_ERROR)
        updates = {}
        if failover_status == fields.ReplicationStatus.FAILED_OVER:
            client = self._get_client(secondary=True)
            try:
                LOG.info("Query new provider_id for volume %s.", volume.id)
                pair_id, remote_pair_id, vol_id, remote_vol_id = (
                    client.get_volumes_pair_attrs("remoteVolumeId",
                                                  volume.provider_id)
                )
                LOG.info("New provider_id for volume %(vol_id)s: "
                         "%(provider_id)s.",
                         {"vol_id": volume.id, "provider_id": vol_id})
                updates["provider_id"] = vol_id
            except exception.VolumeBackendAPIException:
                LOG.error("Failed to query new provider_id for volume "
                          "%(vol_id)s. Volume status will be changed to "
                          "%(status)s.",
                          {"vol_id": volume.id, "status": error_status})
                updates["replication_status"] = error_status
            for snapshot in volume.snapshots:
                try:
                    LOG.info("Query new provider_id for snapshot %(snap_id)s "
                             "of volume %(vol_id)s.",
                             {"snap_id": snapshot.id, "vol_id": volume.id})
                    pair_id, remote_pair_id, snap_id, remote_snap_id = (
                        client.get_volumes_pair_attrs(
                            "remoteVolumeId", snapshot.provider_id)
                    )
                    LOG.info("New provider_id for snapshot %(snap_id)s "
                             "of volume %(vol_id)s: %(provider_id)s.",
                             {
                                 "snap_id": snapshot.id,
                                 "vol_id": volume.id,
                                 "provider_id": snap_id,
                             })
                    snapshot.update({"provider_id": snap_id})
                except exception.VolumeBackendAPIException:
                    LOG.error("Failed to query new provider_id for snapshot "
                              "%(snap_id)s of volume %(vol_id)s. "
                              "Snapshot status will be changed to "
                              "%(status)s.",
                              {
                                  "vol_id": volume.id,
                                  "snap_id": snapshot.id,
                                  "status": fields.SnapshotStatus.ERROR,
                              })
                    snapshot.update({"status": fields.SnapshotStatus.ERROR})
                finally:
                    snapshot.save()
        else:
            updates["replication_status"] = error_status
        return updates

    def _get_provisioning_and_compression(self,
                                          storage_type,
                                          protection_domain_name,
                                          storage_pool_name,
                                          secondary=False):
        """Get volume provisioning and compression from VolumeType extraspecs.

        :param storage_type: extraspecs
        :param protection_domain_name: name of PowerFlex Protection Domain
        :param storage_pool_name: name of PowerFlex Storage Pool
        :param secondary: primary or secondary client
        :return: volume provisioning and compression
        """

        provisioning_type = storage_type.get(PROVISIONING_KEY)
        if provisioning_type is not None:
            if provisioning_type not in ("thick", "thin", "compressed"):
                msg = _("Illegal provisioning type. The supported "
                        "provisioning types are 'thick', 'thin' "
                        "or 'compressed'.")
                raise exception.VolumeBackendAPIException(data=msg)
        else:
            provisioning_type = self.provisioning_type
        provisioning = "ThinProvisioned"
        if (provisioning_type == "thick" and
                self._check_pool_support_thick_vols(protection_domain_name,
                                                    storage_pool_name,
                                                    secondary)):
            provisioning = "ThickProvisioned"
        compression = "None"
        if self._check_pool_support_compression(protection_domain_name,
                                                storage_pool_name,
                                                secondary):
            if provisioning_type == "compressed":
                compression = "Normal"
        return provisioning, compression

    def create_volume(self, volume):
        """Create volume on PowerFlex storage backend.

        :param volume: volume to be created
        :return: volume model updates
        """

        client = self._get_client()

        self._check_volume_size(volume.size)
        protection_domain_name, storage_pool_name = (
            self._extract_domain_and_pool_from_host(volume.host)
        )
        self._check_volume_creation_safe(protection_domain_name,
                                         storage_pool_name)
        storage_type = self._get_volumetype_extraspecs(volume)
        LOG.info("Create volume %(vol_id)s. Volume type: %(volume_type)s, "
                 "Storage Pool name: %(pool_name)s, Protection Domain name: "
                 "%(domain_name)s.",
                 {
                     "vol_id": volume.id,
                     "volume_type": storage_type,
                     "pool_name": storage_pool_name,
                     "domain_name": protection_domain_name,
                 })
        provisioning, compression = self._get_provisioning_and_compression(
            storage_type,
            protection_domain_name,
            storage_pool_name
        )
        provider_id = client.create_volume(protection_domain_name,
                                           storage_pool_name,
                                           volume.id,
                                           volume.size,
                                           provisioning,
                                           compression)
        real_size = int(flex_utils.round_to_num_gran(volume.size))
        model_updates = {
            "provider_id": provider_id,
            "size": real_size,
            "replication_status": fields.ReplicationStatus.DISABLED,
        }
        LOG.info("Successfully created volume %(vol_id)s. "
                 "Volume size: %(size)s. PowerFlex volume name: %(vol_name)s, "
                 "id: %(provider_id)s.",
                 {
                     "vol_id": volume.id,
                     "size": real_size,
                     "vol_name": flex_utils.id_to_base64(volume.id),
                     "provider_id": provider_id,
                 })
        if volume.is_replicated():
            self._setup_volume_replication(volume, provider_id)
            model_updates["replication_status"] = (
                fields.ReplicationStatus.ENABLED
            )
        return model_updates

    def _check_volume_size(self, size):
        """Check volume size to be multiple of 8GB.

        :param size: volume size in GB
        """

        if size % 8 != 0:
            round_volume_capacity = (
                self.configuration.powerflex_round_volume_capacity
            )
            if not round_volume_capacity:
                msg = (_("Cannot create volume of size %s: "
                         "not multiple of 8GB.") % size)
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

    def _check_volume_creation_safe(self,
                                    protection_domain_name,
                                    storage_pool_name,
                                    secondary=False):
        allowed = self._get_client(secondary).is_volume_creation_safe(
            protection_domain_name,
            storage_pool_name
        )
        if not allowed:
            # Do not allow volume creation on this backend.
            # Volumes may leak data between tenants.
            LOG.error("Volume creation rejected due to "
                      "zero padding being disabled for pool, %s:%s. "
                      "This behaviour can be changed by setting "
                      "the configuration option "
                      "powerflex_allow_non_padded_volumes = True.",
                      protection_domain_name, storage_pool_name)
            msg = _("Volume creation rejected due to "
                    "unsafe backend configuration.")
            raise exception.VolumeBackendAPIException(data=msg)

    def create_snapshot(self, snapshot):
        """Create volume snapshot on PowerFlex storage backend.

        :param snapshot: volume snapshot to be created
        :return: snapshot model updates
        """

        client = self._get_client()

        LOG.info("Create snapshot %(snap_id)s for volume %(vol_id)s.",
                 {"snap_id": snapshot.id, "vol_id": snapshot.volume.id})
        provider_id = client.snapshot_volume(snapshot.volume.provider_id,
                                             snapshot.id)
        model_updates = {"provider_id": provider_id}
        LOG.info("Successfully created snapshot %(snap_id)s "
                 "for volume %(vol_id)s. PowerFlex volume name: %(vol_name)s, "
                 "id: %(vol_provider_id)s, snapshot name: %(snap_name)s, "
                 "snapshot id: %(snap_provider_id)s.",
                 {
                     "snap_id": snapshot.id,
                     "vol_id": snapshot.volume.id,
                     "vol_name": flex_utils.id_to_base64(snapshot.volume.id),
                     "vol_provider_id": snapshot.volume.provider_id,
                     "snap_name": flex_utils.id_to_base64(provider_id),
                     "snap_provider_id": provider_id,
                 })
        if snapshot.volume.is_replicated():
            self._setup_volume_replication(snapshot, provider_id)
        return model_updates

    def _create_volume_from_source(self, volume, source):
        """Create volume from volume or snapshot on PowerFlex storage backend.

        We interchange 'volume' and 'snapshot' because in PowerFlex
        snapshot is a volume: once a snapshot is generated it
        becomes a new unmapped volume in the system and the user
        may manipulate it in the same manner as any other volume
        exposed by the system.

        :param volume: volume to be created
        :param source: snapshot or volume from which volume will be created
        :return: volume model updates
        """

        client = self._get_client()

        provider_id = client.snapshot_volume(source.provider_id, volume.id)
        model_updates = {
            "provider_id": provider_id,
            "replication_status": fields.ReplicationStatus.DISABLED,
        }
        LOG.info("Successfully created volume %(vol_id)s "
                 "from source %(source_id)s. PowerFlex volume name: "
                 "%(vol_name)s, id: %(vol_provider_id)s, source name: "
                 "%(source_name)s, source id: %(source_provider_id)s.",
                 {
                     "vol_id": volume.id,
                     "source_id": source.id,
                     "vol_name": flex_utils.id_to_base64(volume.id),
                     "vol_provider_id": provider_id,
                     "source_name": flex_utils.id_to_base64(source.id),
                     "source_provider_id": source.provider_id,
                 })
        try:
            # Snapshot object does not have 'size' attribute.
            source_size = source.volume_size
        except AttributeError:
            source_size = source.size
        if volume.size > source_size:
            real_size = flex_utils.round_to_num_gran(volume.size)
            client.extend_volume(provider_id, real_size)
        if volume.is_replicated():
            self._setup_volume_replication(volume, provider_id)
            model_updates["replication_status"] = (
                fields.ReplicationStatus.ENABLED
            )
        return model_updates

    def create_volume_from_snapshot(self, volume, snapshot):
        """Create volume from snapshot on PowerFlex storage backend.

        :param volume: volume to be created
        :param snapshot: snapshot from which volume will be created
        :return: volume model updates
        """

        LOG.info("Create volume %(vol_id)s from snapshot %(snap_id)s.",
                 {"vol_id": volume.id, "snap_id": snapshot.id})
        return self._create_volume_from_source(volume, snapshot)

    def extend_volume(self, volume, new_size):
        """Extend size of existing and available PowerFlex volume.

        This action will round up volume to nearest size that is
        granularity of 8 GBs.

        :param volume: volume to be extended
        :param new_size: volume size after extending
        """

        LOG.info("Extend volume %(vol_id)s to size %(size)s.",
                 {"vol_id": volume.id, "size": new_size})
        volume_new_size = flex_utils.round_to_num_gran(new_size)
        volume_real_old_size = flex_utils.round_to_num_gran(volume.size)
        if volume_real_old_size == volume_new_size:
            return
        if volume.is_replicated():
            pair_id, remote_pair_id, vol_id, remote_vol_id = (
                self._get_client().get_volumes_pair_attrs("localVolumeId",
                                                          volume.provider_id)
            )
            self._get_client(secondary=True).extend_volume(remote_vol_id,
                                                           volume_new_size)
        self._get_client().extend_volume(volume.provider_id, volume_new_size)

    def create_cloned_volume(self, volume, src_vref):
        """Create cloned volume on PowerFlex storage backend.

        :param volume: volume to be created
        :param src_vref: source volume from which volume will be cloned
        :return: volume model updates
        """

        LOG.info("Clone volume %(vol_id)s to %(target_vol_id)s.",
                 {"vol_id": src_vref.id, "target_vol_id": volume.id})
        return self._create_volume_from_source(volume, src_vref)

    def delete_volume(self, volume):
        """Delete volume from PowerFlex storage backend.

        If volume is replicated, replication will be stopped first.

        :param volume: volume to be deleted
        """

        LOG.info("Delete volume %s.", volume.id)
        if volume.is_replicated():
            self._teardown_volume_replication(volume.provider_id)
        self._get_client().remove_volume(volume.provider_id)

    def delete_snapshot(self, snapshot):
        """Delete snapshot from PowerFlex storage backend.

        :param snapshot: snapshot to be deleted
        """

        LOG.info("Delete snapshot %s.", snapshot.id)
        if snapshot.volume.is_replicated():
            self._teardown_volume_replication(snapshot.provider_id)
        self._get_client().remove_volume(snapshot.provider_id)

    def initialize_connection(self, volume, connector, **kwargs):
        return self._initialize_connection(volume, connector, volume.size)

    def _initialize_connection(self, vol_or_snap, connector, vol_size):
        """Initialize connection and return connection info.

        PowerFlex driver returns a driver_volume_type of 'scaleio'.
        """

        try:
            ip = connector["ip"]
        except Exception:
            ip = "unknown"
        LOG.info("Initialize connection for %(vol_id)s to SDC at %(sdc)s.",
                 {"vol_id": vol_or_snap.id, "sdc": ip})
        connection_properties = self._get_client().connection_properties
        volume_name = flex_utils.id_to_base64(vol_or_snap.id)
        connection_properties["scaleIO_volname"] = volume_name
        connection_properties["scaleIO_volume_id"] = vol_or_snap.provider_id
        connection_properties["config_group"] = self.configuration.config_group
        connection_properties["failed_over"] = self._is_failed_over

        if vol_size is not None:
            extra_specs = self._get_volumetype_extraspecs(vol_or_snap)
            qos_specs = self._get_volumetype_qos(vol_or_snap)
            storage_type = extra_specs.copy()
            storage_type.update(qos_specs)
            round_volume_size = flex_utils.round_to_num_gran(vol_size)
            iops_limit = self._get_iops_limit(round_volume_size, storage_type)
            bandwidth_limit = self._get_bandwidth_limit(round_volume_size,
                                                        storage_type)
            LOG.info("IOPS limit: %s.", iops_limit)
            LOG.info("Bandwidth limit: %s.", bandwidth_limit)
            connection_properties["iopsLimit"] = iops_limit
            connection_properties["bandwidthLimit"] = bandwidth_limit

        return {
            "driver_volume_type": "scaleio",
            "data": connection_properties,
        }

    @staticmethod
    def _get_bandwidth_limit(size, storage_type):
        try:
            max_bandwidth = storage_type.get(QOS_BANDWIDTH_LIMIT)
            if max_bandwidth is not None:
                max_bandwidth = flex_utils.round_to_num_gran(
                    int(max_bandwidth),
                    units.Ki
                )
                max_bandwidth = six.text_type(max_bandwidth)
            LOG.info("Max bandwidth: %s.", max_bandwidth)
            bw_per_gb = storage_type.get(QOS_BANDWIDTH_PER_GB)
            LOG.info("Bandwidth per GB: %s.", bw_per_gb)
            if bw_per_gb is None:
                return max_bandwidth
            # Since PowerFlex volumes size is in 8GB granularity
            # and BWS limitation is in 1024 KBs granularity, we need to make
            # sure that scaled_bw_limit is in 128 granularity.
            scaled_bw_limit = (
                size * flex_utils.round_to_num_gran(int(bw_per_gb),
                                                    MIN_BWS_SCALING_SIZE)
            )
            if max_bandwidth is None or scaled_bw_limit < int(max_bandwidth):
                return six.text_type(scaled_bw_limit)
            else:
                return six.text_type(max_bandwidth)
        except ValueError:
            msg = _("None numeric BWS QoS limitation.")
            raise exception.InvalidInput(reason=msg)

    @staticmethod
    def _get_iops_limit(size, storage_type):
        max_iops = storage_type.get(QOS_IOPS_LIMIT_KEY)
        LOG.info("Max IOPS: %s.", max_iops)
        iops_per_gb = storage_type.get(QOS_IOPS_PER_GB)
        LOG.info("IOPS per GB: %s.", iops_per_gb)
        try:
            if iops_per_gb is None:
                if max_iops is not None:
                    return six.text_type(max_iops)
                else:
                    return None
            scaled_iops_limit = size * int(iops_per_gb)
            if max_iops is None or scaled_iops_limit < int(max_iops):
                return six.text_type(scaled_iops_limit)
            else:
                return six.text_type(max_iops)
        except ValueError:
            msg = _("None numeric IOPS QoS limitation.")
            raise exception.InvalidInput(reason=msg)

    def terminate_connection(self, volume, connector, **kwargs):
        self._terminate_connection(volume, connector)

    @staticmethod
    def _terminate_connection(volume_or_snap, connector):
        """Terminate connection to volume or snapshot.

        With PowerFlex, snaps and volumes are terminated identically.
        """

        try:
            ip = connector["ip"]
        except Exception:
            ip = "unknown"
        LOG.info("Terminate connection for %(vol_id)s to SDC at %(sdc)s.",
                 {"vol_id": volume_or_snap.id, "sdc": ip})

    def _update_volume_stats(self):
        """Update storage backend driver statistics."""

        stats = {}

        backend_name = self.configuration.safe_get("volume_backend_name")
        stats["volume_backend_name"] = backend_name or "powerflex"
        stats["vendor_name"] = "Dell EMC"
        stats["driver_version"] = self.VERSION
        stats["storage_protocol"] = "scaleio"
        stats["reserved_percentage"] = 0
        stats["QoS_support"] = True
        stats["consistent_group_snapshot_enabled"] = True
        stats["thick_provisioning_support"] = True
        stats["thin_provisioning_support"] = True
        stats["multiattach"] = True
        stats["replication_enabled"] = (
            self.replication_enabled and not self._is_failed_over
        )
        stats["replication_targets"] = self.replication_targets
        pools = []

        backend_free_capacity = 0
        backend_total_capacity = 0
        backend_provisioned_capacity = 0

        for sp_name in self.storage_pools:
            splitted_name = sp_name.split(":")
            domain_name = splitted_name[0]
            pool_name = splitted_name[1]
            total_capacity_gb, free_capacity_gb, provisioned_capacity = (
                self._query_pool_stats(domain_name, pool_name)
            )
            pool_support_thick_vols = self._check_pool_support_thick_vols(
                domain_name,
                pool_name
            )
            pool_support_thin_vols = self._check_pool_support_thin_vols(
                domain_name,
                pool_name
            )
            pool_support_compression = self._check_pool_support_compression(
                domain_name,
                pool_name
            )
            pool = {
                "pool_name": sp_name,
                "total_capacity_gb": total_capacity_gb,
                "free_capacity_gb": free_capacity_gb,
                "QoS_support": True,
                "consistent_group_snapshot_enabled": True,
                "reserved_percentage": 0,
                "thin_provisioning_support": pool_support_thin_vols,
                "thick_provisioning_support": pool_support_thick_vols,
                "replication_enabled": stats["replication_enabled"],
                "replication_targets": stats["replication_targets"],
                "multiattach": True,
                "provisioned_capacity_gb": provisioned_capacity,
                "max_over_subscription_ratio":
                    self.configuration.max_over_subscription_ratio,
                "compression_support": pool_support_compression,
            }
            pools.append(pool)
            backend_free_capacity += free_capacity_gb
            backend_total_capacity += total_capacity_gb
            backend_provisioned_capacity += provisioned_capacity
        stats["total_capacity_gb"] = backend_total_capacity
        stats["free_capacity_gb"] = backend_free_capacity
        stats["provisioned_capacity_gb"] = backend_provisioned_capacity
        LOG.info("Free capacity for backend '%(backend)s': %(free)s, "
                 "total capacity: %(total)s, "
                 "provisioned capacity: %(prov)s.",
                 {
                     "backend": stats["volume_backend_name"],
                     "free": backend_free_capacity,
                     "total": backend_total_capacity,
                     "prov": backend_provisioned_capacity,
                 })
        stats["pools"] = pools
        self._stats = stats

    def _query_pool_stats(self, domain_name, pool_name):
        """Get PowerFlex Storage Pool statistics.

        :param domain_name: name of PowerFlex Protection Domain
        :param pool_name: name of PowerFlex Storage Pool
        :return: total, free and provisioned capacity in GB
        """

        client = self._get_client()
        url = "/types/StoragePool/instances/action/querySelectedStatistics"

        LOG.info("Query stats for Storage Pool %s.", pool_name)
        pool_id = client.get_storage_pool_id(domain_name, pool_name)
        props = self._get_queryable_statistics("StoragePool", pool_id)
        params = {"ids": [pool_id], "properties": props}
        r, response = client.execute_powerflex_post_request(url, params)
        if r.status_code != http_client.OK:
            msg = (_("Failed to query stats for Storage Pool %s.") % pool_name)
            raise exception.VolumeBackendAPIException(data=msg)
        # there is always exactly one value in response
        raw_pool_stats, = response.values()
        total_capacity_gb, free_capacity_gb, provisioned_capacity = (
            self._compute_pool_stats(raw_pool_stats)
        )
        LOG.info("Free capacity of Storage Pool %(pool)s: %(free)s, "
                 "total capacity: %(total)s, "
                 "provisioned capacity: %(prov)s.",
                 {
                     "pool": "%s:%s" % (domain_name, pool_name),
                     "free": free_capacity_gb,
                     "total": total_capacity_gb,
                     "prov": provisioned_capacity,
                 })

        return total_capacity_gb, free_capacity_gb, provisioned_capacity

    def _compute_pool_stats(self, stats):
        client = self._get_client()

        if flex_utils.version_gte(client.query_rest_api_version(), "3.0"):
            return self._compute_pool_stats_v3(stats)
        # Divide by two because PowerFlex creates
        # a copy for each volume
        total_capacity_raw = flex_utils.convert_kb_to_gib(
            (stats["capacityLimitInKb"] - stats["spareCapacityInKb"]) / 2
        )
        total_capacity_gb = flex_utils.round_down_to_num_gran(
            total_capacity_raw
        )
        # This property is already rounded
        # to 8 GB granularity in backend
        free_capacity_gb = flex_utils.convert_kb_to_gib(
            stats["capacityAvailableForVolumeAllocationInKb"]
        )
        # some versions of the API had a typo in the response
        thin_capacity_allocated = stats.get("thinCapacityAllocatedInKm")
        if thin_capacity_allocated is None:
            thin_capacity_allocated = stats.get("thinCapacityAllocatedInKb", 0)
        # Divide by two because PowerFlex creates
        # a copy for each volume
        provisioned_capacity = flex_utils.convert_kb_to_gib(
            (stats["thickCapacityInUseInKb"] +
             stats["snapCapacityInUseInKb"] +
             thin_capacity_allocated) / 2
        )
        return total_capacity_gb, free_capacity_gb, provisioned_capacity

    @staticmethod
    def _compute_pool_stats_v3(stats):
        # in PowerFlex 3.5 snapCapacityInUseInKb is replaced by
        # snapshotCapacityInKb
        snap_capacity_allocated = stats.get("snapshotCapacityInKb")
        if snap_capacity_allocated is None:
            snap_capacity_allocated = stats.get("snapCapacityInUseInKb", 0)
        total_capacity_gb = flex_utils.convert_kb_to_gib(
            stats["netCapacityInUseInKb"] + stats["netUnusedCapacityInKb"]
        )
        free_capacity_gb = flex_utils.convert_kb_to_gib(
            stats["netUnusedCapacityInKb"]
        )
        provisioned_capacity_gb = flex_utils.convert_kb_to_gib(
            (stats["thickCapacityInUseInKb"] +
             snap_capacity_allocated +
             stats["thinCapacityAllocatedInKb"]) / 2
        )
        return total_capacity_gb, free_capacity_gb, provisioned_capacity_gb

    def _check_pool_support_thick_vols(self,
                                       domain_name,
                                       pool_name,
                                       secondary=False):
        # storage pools with fine granularity doesn't support
        # thick volumes
        return not self._is_fine_granularity_pool(domain_name,
                                                  pool_name,
                                                  secondary)

    def _check_pool_support_thin_vols(self,
                                      domain_name,
                                      pool_name,
                                      secondary=False):
        # thin volumes available since PowerFlex 2.x
        client = self._get_client(secondary)

        return flex_utils.version_gte(client.query_rest_api_version(), "2.0")

    def _check_pool_support_compression(self,
                                        domain_name,
                                        pool_name,
                                        secondary=False):
        # volume compression available only in storage pools
        # with fine granularity
        return self._is_fine_granularity_pool(domain_name,
                                              pool_name,
                                              secondary)

    def _is_fine_granularity_pool(self,
                                  domain_name,
                                  pool_name,
                                  secondary=False):
        client = self._get_client(secondary)

        if flex_utils.version_gte(client.query_rest_api_version(), "3.0"):
            r = client.get_storage_pool_properties(domain_name, pool_name)
            if r and "dataLayout" in r:
                return r["dataLayout"] == "FineGranularity"
        return False

    @staticmethod
    def _get_volumetype_extraspecs(volume):
        specs = {}
        ctxt = context.get_admin_context()
        type_id = volume["volume_type_id"]
        if type_id:
            volume_type = volume_types.get_volume_type(ctxt, type_id)
            specs = volume_type.get("extra_specs")
            for key, value in specs.items():
                specs[key] = value
        return specs

    def _get_volumetype_qos(self, volume):
        qos = {}
        ctxt = context.get_admin_context()
        type_id = volume["volume_type_id"]
        if type_id:
            volume_type = volume_types.get_volume_type(ctxt, type_id)
            qos_specs_id = volume_type.get("qos_specs_id")
            if qos_specs_id is not None:
                specs = qos_specs.get_qos_specs(ctxt, qos_specs_id)["specs"]
            else:
                specs = {}
            for key, value in specs.items():
                if key in self.powerflex_qos_keys:
                    qos[key] = value
        return qos

    def _sio_attach_volume(self, volume):
        """Call connector.connect_volume() and return the path."""

        LOG.info("Call os-brick to attach PowerFlex volume.")
        connection_properties = self._get_client().connection_properties
        connection_properties["scaleIO_volname"] = flex_utils.id_to_base64(
            volume.id
        )
        connection_properties["scaleIO_volume_id"] = volume.provider_id
        connection_properties["config_group"] = self.configuration.config_group
        connection_properties["failed_over"] = self._is_failed_over
        device_info = self.connector.connect_volume(connection_properties)
        return device_info["path"]

    def _sio_detach_volume(self, volume):
        """Call the connector.disconnect()."""

        LOG.info("Call os-brick to detach PowerFlex volume.")
        connection_properties = self._get_client().connection_properties
        connection_properties["scaleIO_volname"] = flex_utils.id_to_base64(
            volume.id
        )
        connection_properties["scaleIO_volume_id"] = volume.provider_id
        connection_properties["config_group"] = self.configuration.config_group
        connection_properties["failed_over"] = self._is_failed_over

        self.connector.disconnect_volume(connection_properties, volume)

    def copy_image_to_volume(self, context, volume, image_service, image_id):
        """Fetch image from image service and write it to volume."""

        LOG.info("Copy image %(image_id)s from image service %(service)s "
                 "to volume %(vol_id)s.",
                 {
                     "image_id": image_id,
                     "service": image_service,
                     "vol_id": volume.id,
                 })
        try:
            image_utils.fetch_to_raw(context,
                                     image_service,
                                     image_id,
                                     self._sio_attach_volume(volume),
                                     BLOCK_SIZE,
                                     size=volume.size)
        finally:
            self._sio_detach_volume(volume)

    def copy_volume_to_image(self, context, volume, image_service, image_meta):
        """Copy volume to image on image service."""

        LOG.info("Copy volume %(vol_id)s to image on "
                 "image service %(service)s. Image meta: %(meta)s.",
                 {
                     "vol_id": volume.id,
                     "service": image_service,
                     "meta": image_meta,
                 })
        try:
            volume_utils.upload_volume(context,
                                       image_service,
                                       image_meta,
                                       self._sio_attach_volume(volume),
                                       volume)
        finally:
            self._sio_detach_volume(volume)

    def migrate_volume(self, ctxt, volume, host):
        """Migrate PowerFlex volume within the same backend."""

        LOG.info("Migrate volume %(vol_id)s to %(host)s.",
                 {"vol_id": volume.id, "host": host["host"]})

        client = self._get_client()

        def fall_back_to_host_assisted():
            LOG.debug("Falling back to host-assisted migration.")
            return False, None

        if volume.is_replicated():
            msg = _("Migration of replicated volumes is not allowed.")
            LOG.error(msg)
            raise exception.InvalidVolume(reason=msg)

        # Check migration between different backends
        src_backend = volume_utils.extract_host(volume.host, "backend")
        dst_backend = volume_utils.extract_host(host["host"], "backend")
        if src_backend != dst_backend:
            LOG.debug("Cross-backends migration is not supported "
                      "by PowerFlex.")
            return fall_back_to_host_assisted()

        # Check migration is supported by storage API
        if not flex_utils.version_gte(client.query_rest_api_version(), "3.0"):
            LOG.debug("PowerFlex versions less than v3.0 do not "
                      "support volume migration.")
            return fall_back_to_host_assisted()

        # Check storage pools compatibility
        src_pd, src_sp = self._extract_domain_and_pool_from_host(volume.host)
        dst_pd, dst_sp = self._extract_domain_and_pool_from_host(host["host"])
        if not self._pools_compatible_for_migration(src_pd,
                                                    src_sp,
                                                    dst_pd,
                                                    dst_sp):
            return fall_back_to_host_assisted()

        real_provisioning, vtree_id = (
            self._get_real_provisioning_and_vtree(volume.provider_id)
        )
        params = self._get_volume_migration_params(volume,
                                                   dst_pd,
                                                   dst_sp,
                                                   real_provisioning)
        client.migrate_vtree(volume, params)
        try:
            self._wait_for_volume_migration_to_complete(vtree_id, volume.id)
        except loopingcall.LoopingCallTimeOut:
            # Volume migration is still in progress but timeout has expired.
            # Volume status is set to maintenance to prevent performing other
            # operations with volume. Migration status should be checked on the
            # storage side. If the migration successfully completed, volume
            # status should be manually changed to AVAILABLE.
            updates = {
                "status": fields.VolumeStatus.MAINTENANCE,
            }
            msg = (_("Migration of volume %s is still in progress "
                     "but timeout has expired. Volume status is set to "
                     "maintenance to prevent performing operations with this "
                     "volume. Check the migration status "
                     "on the storage side and set volume status manually if "
                     "migration succeeded.") % volume.id)
            LOG.warning(msg)
            return True, updates
        return True, {}

    def _pools_compatible_for_migration(self, src_pd, src_sp, dst_pd, dst_sp):
        """Compare storage pools properties to determine migration possibility.

        Limitations:
         - For migration from Medium Granularity (MG) to Fine Granularity (FG)
           storage pool zero padding must be enabled on the MG pool.
         - For migration from MG to MG pool zero padding must be either enabled
           or disabled on both pools.
        """

        client = self._get_client()
        src_zero_padding_enabled = client.is_volume_creation_safe(src_pd,
                                                                  src_sp)
        dst_zero_padding_enabled = client.is_volume_creation_safe(dst_pd,
                                                                  dst_sp)
        src_is_fg_pool = self._is_fine_granularity_pool(src_pd, src_sp)
        dst_is_fg_pool = self._is_fine_granularity_pool(dst_pd, dst_sp)
        if src_is_fg_pool:
            return True
        elif dst_is_fg_pool:
            if not src_zero_padding_enabled:
                LOG.debug("Migration from Medium Granularity storage pool "
                          "with zero padding disabled to Fine Granularity one "
                          "is not allowed.")
                return False
            return True
        elif not src_zero_padding_enabled == dst_zero_padding_enabled:
            LOG.debug("Zero padding must be either enabled or disabled on "
                      "both storage pools.")
            return False
        return True

    def _get_real_provisioning_and_vtree(self, provider_id):
        """Get volume real provisioning type and vtree_id."""

        response = self._get_client().query_volume(provider_id)
        try:
            provisioning = response["volumeType"]
            vtree_id = response["vtreeId"]
            return provisioning, vtree_id
        except KeyError:
            msg = (_("Query volume response does not contain "
                     "required fields: volumeType and vtreeId."))
            LOG.error(msg)
            raise exception.MalformedResponse(
                cmd="_get_real_provisioning_and_vtree",
                reason=msg
            )

    def _get_volume_migration_params(self,
                                     volume,
                                     dst_domain_name,
                                     dst_pool_name,
                                     real_provisioning):
        client = self._get_client()

        dst_pool_id = client.get_storage_pool_id(dst_domain_name,
                                                 dst_pool_name)
        params = {
            "destSPId": dst_pool_id,
            "volTypeConversion": "NoConversion",
            "compressionMethod": "None",
            "allowDuringRebuild": six.text_type(
                self.configuration.powerflex_allow_migration_during_rebuild
            ),
        }
        storage_type = self._get_volumetype_extraspecs(volume)
        provisioning, compression = self._get_provisioning_and_compression(
            storage_type,
            dst_domain_name,
            dst_pool_name
        )
        pool_supports_thick_vols = self._check_pool_support_thick_vols(
            dst_domain_name,
            dst_pool_name
        )
        if (
                real_provisioning == "ThickProvisioned" and
                (provisioning == "ThinProvisioned" or
                 not pool_supports_thick_vols)
        ):
            params["volTypeConversion"] = "ThickToThin"
        elif (
                real_provisioning == "ThinProvisioned" and
                provisioning == "ThickProvisioned" and
                pool_supports_thick_vols
        ):
            params["volTypeConversion"] = "ThinToThick"
        params["compressionMethod"] = compression
        return params

    @utils.retry(exception.VolumeBackendAPIException,
                 interval=5, backoff_rate=1, retries=3)
    def _wait_for_volume_migration_to_complete(self, vtree_id, vol_id):
        """Check volume migration status."""

        LOG.debug("Wait for migration of volume %s to complete.", vol_id)

        def _inner():
            response = self._get_client().query_vtree(vtree_id, vol_id)
            try:
                migration_status = (
                    response["vtreeMigrationInfo"]["migrationStatus"]
                )
                migration_pause_reason = (
                    response["vtreeMigrationInfo"]["migrationPauseReason"]
                )
                if (
                        migration_status == "NotInMigration" and
                        not migration_pause_reason
                ):
                    # Migration completed successfully.
                    raise loopingcall.LoopingCallDone()
                elif migration_pause_reason:
                    # Migration failed or paused on the storage side.
                    # Volume remains on the source backend.
                    msg = (_("Migration of volume %(vol_id)s failed or "
                             "paused on the storage side. "
                             "Migration status: %(status)s, "
                             "pause reason: %(reason)s.") %
                           {"vol_id": vol_id,
                            "status": migration_status,
                            "reason": migration_pause_reason})
                    LOG.error(msg)
                    raise exception.VolumeMigrationFailed(msg)
            except KeyError:
                msg = (_("Check Migration status response does not contain "
                         "required fields: migrationStatus and "
                         "migrationPauseReason."))
                LOG.error(msg)
                raise exception.MalformedResponse(
                    cmd="_wait_for_volume_migration_to_complete",
                    reason=msg
                )
        timer = loopingcall.FixedIntervalWithTimeoutLoopingCall(_inner)
        timer.start(interval=30, timeout=3600).wait()

    def update_migrated_volume(self,
                               ctxt,
                               volume,
                               new_volume,
                               original_volume_status):
        """Update volume name of new PowerFlex volume to match updated ID.

        Original volume is renamed first since PowerFlex does not allow
        multiple volumes to have same name.
        """

        client = self._get_client()

        name_id = None
        location = None
        if original_volume_status == fields.VolumeStatus.AVAILABLE:
            # During migration, a new volume is created and will replace
            # the original volume at the end of the migration. We need to
            # rename the new volume. The current_name of the new volume,
            # which is the id of the new volume, will be changed to the
            # new_name, which is the id of the original volume.
            current_name = new_volume.id
            new_name = volume.id
            vol_id = new_volume.id
            LOG.info("Rename volume %(vol_id)s from %(current_name)s to "
                     "%(new_name)s.",
                     {
                         "vol_id": vol_id,
                         "current_name": current_name,
                         "new_name": new_name,
                     })
            # Original volume needs to be renamed first
            client.rename_volume(volume, "ff" + new_name)
            client.rename_volume(new_volume, new_name)
            LOG.info("Successfully renamed volume %(vol_id)s to %(new_name)s.",
                     {"vol_id": vol_id, "new_name": new_name})
        else:
            # The back-end will not be renamed.
            name_id = getattr(new_volume, "_name_id", None) or new_volume.id
            location = new_volume.provider_location
        return {"_name_id": name_id, "provider_location": location}

    def revert_to_snapshot(self, context, volume, snapshot):
        """Revert PowerFlex volume to the specified snapshot."""

        LOG.info("Revert volume %(vol_id)s to snapshot %(snap_id)s.",
                 {"vol_id": volume.id, "snap_id": snapshot.id})

        client = self._get_client()

        if not flex_utils.version_gte(client.query_rest_api_version(), "3.0"):
            LOG.debug("PowerFlex versions less than v3.0 do not "
                      "support reverting volume to snapshot. "
                      "Falling back to generic revert to snapshot method.")
            raise NotImplementedError
        elif volume.is_replicated():
            msg = _("Reverting replicated volume is not allowed.")
            LOG.error(msg)
            raise exception.InvalidVolume(reason=msg)
        elif snapshot.volume_size != volume.size:
            msg = (_("Volume %(vol_id)s size is not equal to snapshot "
                     "%(snap_id)s size. Revert to snapshot operation is not "
                     "allowed.") %
                   {"vol_id": volume.id, "snap_id": snapshot.id})
            LOG.error(msg)
            raise exception.InvalidVolume(reason=msg)

        client.overwrite_volume_content(volume, snapshot)

    def _query_powerflex_volume(self, volume, existing_ref):
        type_id = volume.get("volume_type_id")
        if "source-id" not in existing_ref:
            reason = _("Reference must contain source-id.")
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_ref,
                reason=reason
            )
        if type_id is None:
            reason = _("Volume must have a volume type.")
            raise exception.ManageExistingVolumeTypeMismatch(
                existing_ref=existing_ref,
                reason=reason
            )
        vol_id = existing_ref["source-id"]
        LOG.info("Query volume %(vol_id)s with PowerFlex id %(provider_id)s.",
                 {"vol_id": volume.id, "provider_id": vol_id})
        response = self._get_client().query_volume(vol_id)
        self._manage_existing_check_legal_response(response, existing_ref)
        return response

    def _get_all_powerflex_volumes(self):
        """Get all volumes in configured PowerFlex Storage Pools."""

        client = self._get_client()
        url = ("/instances/StoragePool::%(storage_pool_id)s"
               "/relationships/Volume")

        all_volumes = []
        # check for every storage pool configured
        for sp_name in self.storage_pools:
            splitted_name = sp_name.split(":")
            domain_name = splitted_name[0]
            pool_name = splitted_name[1]
            sp_id = client.get_storage_pool_id(domain_name, pool_name)
            r, volumes = client.execute_powerflex_get_request(
                url,
                storage_pool_id=sp_id
            )
            if r.status_code != http_client.OK:
                msg = (_("Failed to query volumes in Storage Pool "
                         "%(pool_name)s of Protection Domain "
                         "%(domain_name)s.") %
                       {"pool_name": pool_name, "domain_name": domain_name})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
            all_volumes.extend(volumes)
        return all_volumes

    def get_manageable_volumes(self, cinder_volumes, marker, limit, offset,
                               sort_keys, sort_dirs):
        """List volumes on storage backend available for management by Cinder.

        Rule out volumes that are mapped to SDC or
        are already in list of cinder_volumes.
        Return references of volume ids for any others.
        """

        all_sio_volumes = self._get_all_powerflex_volumes()
        # Put together a map of existing cinder volumes on the array
        # so we can lookup cinder id's to SIO id
        existing_vols = {}
        for cinder_vol in cinder_volumes:
            provider_id = cinder_vol.provider_id
            existing_vols[provider_id] = cinder_vol.name_id
        manageable_volumes = []
        for sio_vol in all_sio_volumes:
            cinder_id = existing_vols.get(sio_vol["id"])
            is_safe = True
            reason = None
            if sio_vol["mappedSdcInfo"]:
                is_safe = False
                hosts_connected = len(sio_vol["mappedSdcInfo"])
                reason = _("Volume mapped to %d host(s).") % hosts_connected
            if cinder_id:
                is_safe = False
                reason = _("Volume already managed.")
            if sio_vol["volumeType"] != "Snapshot":
                manageable_volumes.append(
                    {
                        "reference": {
                            "source-id": sio_vol["id"],
                        },
                        "size": flex_utils.convert_kb_to_gib(
                            sio_vol["sizeInKb"]
                        ),
                        "safe_to_manage": is_safe,
                        "reason_not_safe": reason,
                        "cinder_id": cinder_id,
                        "extra_info": {
                            "volumeType": sio_vol["volumeType"],
                            "name": sio_vol["name"],
                        },
                    })
        return volume_utils.paginate_entries_list(manageable_volumes,
                                                  marker,
                                                  limit,
                                                  offset,
                                                  sort_keys,
                                                  sort_dirs)

    def _is_managed(self, volume_id):
        lst = objects.VolumeList.get_all_by_host(context.get_admin_context(),
                                                 self.host)
        for vol in lst:
            if vol.provider_id == volume_id:
                return True
        return False

    def manage_existing(self, volume, existing_ref):
        """Manage existing PowerFlex volume.

        :param volume: volume to be managed
        :param existing_ref: dictionary of form
                             {'source-id': 'id of PowerFlex volume'}
        """

        response = self._query_powerflex_volume(volume, existing_ref)
        return {"provider_id": response["id"]}

    def manage_existing_get_size(self, volume, existing_ref):
        return self._get_volume_size(volume, existing_ref)

    def manage_existing_snapshot(self, snapshot, existing_ref):
        """Manage existing PowerFlex snapshot.

        :param snapshot: snapshot to be managed
        :param existing_ref: dictionary of form
                             {'source-id': 'id of PowerFlex snapshot'}
        """

        response = self._query_powerflex_volume(snapshot, existing_ref)
        not_real_parent = (response.get("orig_parent_overriden") or
                           response.get("is_source_deleted"))
        if not_real_parent:
            reason = (_("Snapshot's parent is not original parent due "
                        "to deletion or revert action, therefore "
                        "this snapshot cannot be managed."))
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_ref,
                reason=reason
            )
        ancestor_id = response["ancestorVolumeId"]
        volume_id = snapshot.volume.provider_id
        if ancestor_id != volume_id:
            reason = (_("Snapshot's parent in PowerFlex is %(ancestor_id)s "
                        "and not %(vol_id)s.") %
                      {"ancestor_id": ancestor_id, "vol_id": volume_id})
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_ref,
                reason=reason
            )
        return {"provider_id": response["id"]}

    def manage_existing_snapshot_get_size(self, snapshot, existing_ref):
        return self._get_volume_size(snapshot, existing_ref)

    def _get_volume_size(self, volume, existing_ref):
        response = self._query_powerflex_volume(volume, existing_ref)
        return int(math.ceil(float(response["sizeInKb"]) / units.Mi))

    def _manage_existing_check_legal_response(self, response, existing_ref):
        # check if it is already managed
        if self._is_managed(response["id"]):
            reason = _("Failed to manage volume. Volume is already managed.")
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_ref,
                reason=reason
            )
        if response["mappedSdcInfo"] is not None:
            reason = _("Failed to manage volume. "
                       "Volume is connected to hosts. "
                       "Please disconnect volume from existing hosts "
                       "before importing.")
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_ref,
                reason=reason
            )

    def create_group(self, context, group):
        """Create Consistency Group.

        PowerFlex won't create CG until cg-snapshot creation,
        db will maintain the volumes and CG relationship.
        """

        # let generic volume group support handle non-cgsnapshots
        if not volume_utils.is_group_a_cg_snapshot_type(group):
            raise NotImplementedError()
        LOG.info("Create Consistency Group %s.", group.id)
        model_updates = {"status": fields.GroupStatus.AVAILABLE}
        return model_updates

    def delete_group(self, context, group, volumes):
        """Delete Consistency Group.

        PowerFlex will delete volumes of CG.
        """

        # let generic volume group support handle non-cgsnapshots
        if not volume_utils.is_group_a_cg_snapshot_type(group):
            raise NotImplementedError()
        LOG.info("Delete Consistency Group %s.", group.id)
        model_updates = {"status": fields.GroupStatus.DELETED}
        error_statuses = [
            fields.GroupStatus.ERROR,
            fields.GroupStatus.ERROR_DELETING,
        ]
        volume_model_updates = []
        for volume in volumes:
            update_item = {"id": volume.id}
            try:
                self.delete_volume(volume)
                update_item["status"] = "deleted"
            except exception.VolumeBackendAPIException:
                update_item["status"] = fields.VolumeStatus.ERROR_DELETING
                if model_updates["status"] not in error_statuses:
                    model_updates["status"] = fields.GroupStatus.ERROR_DELETING
                    LOG.error("Failed to delete volume %(vol_id)s of "
                              "group %(group_id)s.",
                              {"vol_id": volume.id, "group_id": group.id})
            volume_model_updates.append(update_item)
        return model_updates, volume_model_updates

    def create_group_snapshot(self, context, group_snapshot, snapshots):
        """Create Consistency Group snapshot."""

        # let generic volume group support handle non-cgsnapshots
        if not volume_utils.is_group_a_cg_snapshot_type(group_snapshot):
            raise NotImplementedError()

        snapshot_model_updates = []
        for snapshot in snapshots:
            update_item = self.create_snapshot(snapshot)
            update_item["id"] = snapshot.id
            update_item["status"] = fields.SnapshotStatus.AVAILABLE
            snapshot_model_updates.append(update_item)
        model_updates = {"status": fields.GroupStatus.AVAILABLE}
        return model_updates, snapshot_model_updates

    def delete_group_snapshot(self, context, group_snapshot, snapshots):
        """Delete Consistency Group snapshot."""

        # let generic volume group support handle non-cgsnapshots
        if not volume_utils.is_group_a_cg_snapshot_type(group_snapshot):
            raise NotImplementedError()
        LOG.info("Delete Consistency Group Snapshot %s.", group_snapshot.id)
        model_updates = {"status": fields.SnapshotStatus.DELETED}
        error_statuses = [
            fields.SnapshotStatus.ERROR,
            fields.SnapshotStatus.ERROR_DELETING,
        ]
        snapshot_model_updates = []
        for snapshot in snapshots:
            update_item = {"id": snapshot.id}
            try:
                self.delete_snapshot(snapshot)
                update_item["status"] = fields.SnapshotStatus.DELETED
            except exception.VolumeBackendAPIException:
                update_item["status"] = fields.SnapshotStatus.ERROR_DELETING
                if model_updates["status"] not in error_statuses:
                    model_updates["status"] = (
                        fields.SnapshotStatus.ERROR_DELETING
                    )
                LOG.error("Failed to delete snapshot %(snap_id)s "
                          "of group snapshot %(group_snap_id)s.",
                          {
                              "snap_id": snapshot.id,
                              "group_snap_id": group_snapshot.id,

                          })
            snapshot_model_updates.append(update_item)
        return model_updates, snapshot_model_updates

    def create_group_from_src(self, context, group, volumes,
                              group_snapshot=None, snapshots=None,
                              source_group=None, source_vols=None):
        """Create Consistency Group from source."""

        # let generic volume group support handle non-cgsnapshots
        if not volume_utils.is_group_a_cg_snapshot_type(group):
            raise NotImplementedError()

        if group_snapshot and snapshots:
            sources = snapshots
        else:
            sources = source_vols
        volume_model_updates = []
        for source, volume in zip(sources, volumes):
            update_item = self.create_cloned_volume(volume, source)
            update_item["id"] = volume.id
            update_item["status"] = fields.VolumeStatus.AVAILABLE
            volume_model_updates.append(update_item)
        model_updates = {"status": fields.GroupStatus.AVAILABLE}
        return model_updates, volume_model_updates

    def update_group(self,
                     context,
                     group,
                     add_volumes=None,
                     remove_volumes=None):
        """Update Consistency Group.

        PowerFlex does not handle volume grouping.
        Cinder maintains volumes and CG relationship.
        """

        if volume_utils.is_group_a_cg_snapshot_type(group):
            return None, None, None

        # we'll rely on the generic group implementation if it is not a
        # consistency group request.
        raise NotImplementedError()

    def ensure_export(self, context, volume):
        """Driver entry point to get export info for existing volume."""
        pass

    def create_export(self, context, volume, connector):
        """Driver entry point to get export info for new volume."""
        pass

    def remove_export(self, context, volume):
        """Driver entry point to remove export for volume."""
        pass

    def check_for_export(self, context, volume_id):
        """Make sure volume is exported."""
        pass

    def initialize_connection_snapshot(self, snapshot, connector, **kwargs):
        """Initialize connection and return connection info."""

        try:
            vol_size = snapshot.volume_size
        except Exception:
            vol_size = None
        return self._initialize_connection(snapshot, connector, vol_size)

    def terminate_connection_snapshot(self, snapshot, connector, **kwargs):
        """Terminate connection to snapshot."""

        return self._terminate_connection(snapshot, connector)

    def create_export_snapshot(self, context, volume, connector):
        """Driver entry point to get export info for snapshot."""
        pass

    def remove_export_snapshot(self, context, volume):
        """Driver entry point to remove export for snapshot."""
        pass

    def backup_use_temp_snapshot(self):
        return True
