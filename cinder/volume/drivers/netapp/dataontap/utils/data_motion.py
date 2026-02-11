# Copyright (c) 2016 Alex Meade.  All rights reserved.
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
NetApp Data ONTAP data motion library.

This library handles transferring data from a source to a destination. Its
responsibility is to handle this as efficiently as possible given the
location of the data's source and destination. This includes cloning,
SnapMirror, and copy-offload as improvements to brute force data transfer.
"""

from oslo_log import log
from oslo_service import loopingcall
from oslo_utils import excutils
from oslo_utils import timeutils

from cinder import exception
from cinder.i18n import _
from cinder.objects import fields
from cinder import utils
from cinder.volume.drivers.netapp.dataontap.client import api as netapp_api
from cinder.volume.drivers.netapp.dataontap.utils import utils as config_utils
from cinder.volume.drivers.netapp import utils as na_utils
from cinder.volume import volume_utils

LOG = log.getLogger(__name__)
ENTRY_DOES_NOT_EXIST = "(entry doesn't exist)"
GEOMETRY_HAS_BEEN_CHANGED = (
    "Geometry of the destination",  # This intends to be a Tuple
    "has been changed since the SnapMirror relationship was created")
QUIESCE_RETRY_INTERVAL = 5

# Replication policy constants
REPLICATION_POLICY_AUTOMATED_FAILOVER = 'AutomatedFailOver'
REPLICATION_POLICY_AUTOMATED_FAILOVER_DUPLEX = 'AutomatedFailOverDuplex'

# Policy groupings
ACTIVE_SYNC_ASYMMETRIC_POLICIES = (
    REPLICATION_POLICY_AUTOMATED_FAILOVER,
    REPLICATION_POLICY_AUTOMATED_FAILOVER_DUPLEX,
)


class DataMotionMixin(object):

    def get_replication_backend_names(self, config):
        """Get the backend names for all configured replication targets."""

        backend_names = []

        replication_devices = config.safe_get('replication_device')
        if replication_devices:
            for replication_device in replication_devices:
                backend_id = replication_device.get('backend_id')
                if backend_id:
                    backend_names.append(backend_id)

        return backend_names

    def get_replication_backend_stats(self, config):
        """Get the driver replication info for merging into volume stats."""

        backend_names = self.get_replication_backend_names(config)

        if len(backend_names) > 0:
            stats = {
                'replication_enabled': True,
                'replication_count': len(backend_names),
                'replication_targets': backend_names,
                'replication_type': 'async',
            }
        else:
            stats = {'replication_enabled': False}

        return stats

    def _get_replication_aggregate_map(self, src_backend_name,
                                       target_backend_name):
        """Get the aggregate mapping config between src and destination."""

        aggregate_map = {}

        config = config_utils.get_backend_configuration(src_backend_name)

        all_replication_aggregate_maps = config.safe_get(
            'netapp_replication_aggregate_map')
        if all_replication_aggregate_maps:
            for replication_aggregate_map in all_replication_aggregate_maps:
                if (replication_aggregate_map.get('backend_id') ==
                        target_backend_name):
                    replication_aggregate_map.pop('backend_id')
                    aggregate_map = replication_aggregate_map
                    break
        return aggregate_map

    def get_replication_policy(self, config):
        """Get replication policy for the configured replication targets."""
        return config.safe_get('netapp_replication_policy') or \
            "MirrorAllSnapshots"

    def is_active_sync_asymmetric_policy(self, replication_policy):
        """Check if the policy is an active sync (asymmetric) policy."""
        return replication_policy in ACTIVE_SYNC_ASYMMETRIC_POLICIES

    def is_automated_failover_policy(self, snapmirror_policy):
        if (snapmirror_policy.get('type') in 'sync' and
                snapmirror_policy.get('sync_type') in 'automated_failover'):
            return True
        return False

    def is_active_sync_configured(self, configuration):
        replication_enabled = (
            True if self.get_replication_backend_names(
                configuration) else False)
        if replication_enabled:
            return self.get_replication_policy(configuration) == \
                "AutomatedFailOver"
        return False

    def is_consistent_replication_enabled(self, config):
        return config.safe_get('netapp_consistent_replication')

    def validate_no_conflicting_snapmirrors(self, config,
                                            src_backend_name,
                                            flexvol_names):
        """Validate no conflicting SnapMirror relationships exist.

        Checks if FlexVols matching netapp_pool_name_search_pattern already
        have SnapMirror relationships that were NOT created by Cinder.

        Cinder always creates SnapMirrors with matching volume names:
          Ex: source: vs0:volume1 -> destination: vs1:volume1

        If a SnapMirror exists with a DIFFERENT destination volume name,
        an exception is thrown.

        """
        backend_names = self.get_replication_backend_names(config)
        if not backend_names:
            # No replication configured, skip validation
            return

        src_backend_config = config_utils.get_backend_configuration(
            src_backend_name)
        src_vserver = src_backend_config.netapp_vserver
        src_client = config_utils.get_client_for_backend(
            src_backend_name, vserver_name=src_vserver)

        # Get all configured destination vservers for comparison
        # Cinder creates SnapMirrors with matching volume names
        configured_destinations = {}
        for dest_backend_name in backend_names:
            dest_backend_config = config_utils.get_backend_configuration(
                dest_backend_name)
            dest_vserver = dest_backend_config.netapp_vserver
            configured_destinations[dest_vserver] = dest_backend_name

        LOG.debug("Checking for pre-existing SnapMirror relationships on "
                  "pool volumes %(flexvols)s that may conflict with Cinder "
                  "replication. Configured destinations: %(dests)s",
                  {'flexvols': flexvol_names,
                   'dests': configured_destinations})

        conflicting_mirrors = []

        for flexvol_name in flexvol_names:
            try:
                # Query all existing SnapMirror relationships for this FlexVol
                existing_mirrors = src_client.get_snapmirrors(
                    src_vserver, flexvol_name, None, None)

                if not existing_mirrors:
                    continue

                LOG.debug("Found %(count)d existing SnapMirror "
                          "relationship(s) for FlexVol %(vol)s",
                          {'count': len(existing_mirrors),
                           'vol': flexvol_name})

                for mirror in existing_mirrors:
                    dest_vserver = mirror.get('destination-vserver')
                    dest_volume = mirror.get('destination-volume')
                    mirror_state = mirror.get('mirror-state')

                    # Cinder always creates SnapMirrors with SAME volume name
                    # Source: vs0:volume1 -> Dest: vs1:volume1
                    # If destination volume name is DIFFERENT, it was created
                    # outside of Cinder - this is a conflict
                    is_cinder_naming = (dest_volume == flexvol_name)
                    is_configured_vserver = dest_vserver in \
                        configured_destinations.keys()

                    if not is_cinder_naming:
                        # CONFLICT! SnapMirror has different destination name
                        # This was created outside of Cinder
                        conflict_info = {
                            'source_volume': flexvol_name,
                            'source_vserver': src_vserver,
                            'destination_volume': dest_volume,
                            'destination_vserver': dest_vserver,
                            'mirror_state': mirror_state,
                            'expected_dest_volume': flexvol_name,
                            'backend_id': configured_destinations.get(
                                dest_vserver, 'unknown')
                        }
                        conflicting_mirrors.append(conflict_info)
                        LOG.warning("Conflicting SnapMirror found: FlexVol "
                                    "%(src_vol)s has pre-existing "
                                    "SnapMirror %(src_vs)s:%(src_vol)s -> "
                                    "%(dest_vs)s:%(dest_vol)s. Cinder "
                                    "expects destination name: %(expected)s",
                                    {'src_vol': flexvol_name,
                                     'src_vs': src_vserver,
                                     'dest_vs': dest_vserver,
                                     'dest_vol': dest_volume,
                                     'expected': flexvol_name})
                    elif is_cinder_naming and is_configured_vserver:
                        # This SnapMirror matches Cinder's naming convention
                        # and points to a configured destination
                        # Cinder can adopt and manage this relationship
                        LOG.debug("Found existing SnapMirror "
                                  "%(src_vs)s:%(src_vol)s -> "
                                  "%(dest_vs)s:%(dest_vol)s with Cinder "
                                  "naming convention. Will be adopted.",
                                  {'src_vs': src_vserver,
                                   'src_vol': flexvol_name,
                                   'dest_vs': dest_vserver,
                                   'dest_vol': dest_volume})
                    else:
                        # SnapMirror to unconfigured destination
                        # but with Cinder naming - log for awareness
                        LOG.debug("Existing SnapMirror "
                                  "%(src_vs)s:%(src_vol)s -> "
                                  "%(dest_vs)s:%(dest_vol)s points to "
                                  "vserver not in replication_device config",
                                  {'src_vs': src_vserver,
                                   'src_vol': flexvol_name,
                                   'dest_vs': dest_vserver,
                                   'dest_vol': dest_volume})

            except netapp_api.NaApiError as e:
                # If we can't query SnapMirror relationships, log and continue
                # This shouldn't block setup - it might be a permissions issue
                LOG.warning("Could not query SnapMirror relationships for "
                            "FlexVol %(vol)s: %(error)s",
                            {'vol': flexvol_name, 'error': e})

        if conflicting_mirrors:
            # Build a detailed error message
            error_details = []
            for conflict in conflicting_mirrors:
                error_details.append(
                    "  - %(src_vs)s:%(src_vol)s -> %(dest_vs)s:%(dest_vol)s\n"
                    "    State: %(state)s\n"
                    "    Expected destination volume: %(expected)s\n"
                    "    Backend: %(backend)s" % {
                        'src_vs': conflict['source_vserver'],
                        'src_vol': conflict['source_volume'],
                        'dest_vs': conflict['destination_vserver'],
                        'dest_vol': conflict['destination_volume'],
                        'state': conflict['mirror_state'],
                        'expected': conflict['expected_dest_volume'],
                        'backend': conflict['backend_id']
                    })

            msg = _(
                "Manually-created SnapMirror relationships found:\n"
                "%(conflicts)s\n\n"
                "Configured replication destinations:\n%(configured)s\n\n"
                "These SnapMirrors were created manually (outside Cinder) "
                "and will prevent Cinder from creating its own SnapMirror "
                "relationships for replication.\n\n"
                "Please either:\n"
                "1. Delete the manually-created SnapMirror relationships "
                "before enabling Cinder replication, OR\n"
                "2. Rename the destination volumes to match the source "
                "volume "
                "names (if you want Cinder to adopt them), OR\n"
                "3. Change netapp_pool_name_search_pattern to exclude "
                "FlexVols with manually-created SnapMirror relationships"
            ) % {
                'conflicts': '\n\n'.join(error_details),
                'configured': '\n'.join(
                    ["  - backend_id: %s (vserver: %s)" % (v, k)
                     for k, v in configured_destinations.items()])
            }

            LOG.error(msg)
            raise na_utils.NetAppDriverException(msg)

        LOG.info("SnapMirror conflict validation passed.")

    def get_snapmirrors(self, src_backend_name, dest_backend_name,
                        src_flexvol_name=None, dest_flexvol_name=None):
        """Get info regarding SnapMirror relationship/s for given params."""
        dest_backend_config = config_utils.get_backend_configuration(
            dest_backend_name)
        dest_vserver = dest_backend_config.netapp_vserver
        dest_client = config_utils.get_client_for_backend(
            dest_backend_name, vserver_name=dest_vserver)

        src_backend_config = config_utils.get_backend_configuration(
            src_backend_name)
        src_vserver = src_backend_config.netapp_vserver

        snapmirrors = dest_client.get_snapmirrors(
            src_vserver, src_flexvol_name,
            dest_vserver, dest_flexvol_name,
            desired_attributes=[
                'relationship-status',
                'mirror-state',
                'source-vserver',
                'source-volume',
                'destination-vserver',
                'destination-volume',
                'last-transfer-end-timestamp',
                'lag-time',
            ])
        return snapmirrors

    def get_snapmirror_policy(self, backend_name, snapmirror_policy_name):
        """Get info regarding SnapMirror policy for given params."""

        LOG.debug("Fetching snapmirror policy %s from backend %s",
                  snapmirror_policy_name, backend_name)

        backend_config = config_utils.get_backend_configuration(
            backend_name)
        vserver = backend_config.netapp_vserver
        client = config_utils.get_client_for_backend(
            backend_name, vserver_name=vserver, force_rest=True)
        snapmirror_policy = client.get_snapmirror_policies(
            snapmirror_policy_name)

        if not snapmirror_policy:
            msg = _("SnapMirror policy %s does not exist.") % (
                snapmirror_policy_name)
            raise na_utils.NetAppDriverException(message=msg)

        return snapmirror_policy[0]

    def create_snapmirror(self, src_backend_name, dest_backend_name,
                          src_flexvol_name, dest_flexvol_name,
                          replication_policy):
        """Set up a SnapMirror relationship b/w two FlexVols (cinder pools)

        1. Create SnapMirror relationship
        2. Initialize data transfer asynchronously

        If a SnapMirror relationship already exists and is broken off or
        quiesced, resume and re-sync the mirror.
        """

        dest_backend_config = config_utils.get_backend_configuration(
            dest_backend_name)
        dest_vserver = dest_backend_config.netapp_vserver
        source_backend_config = config_utils.get_backend_configuration(
            src_backend_name)
        src_vserver = source_backend_config.netapp_vserver

        if replication_policy == "AutomatedFailOver":
            dest_client = config_utils.get_client_for_backend(
                dest_backend_name, vserver_name=dest_vserver, force_rest=True)
            src_client = config_utils.get_client_for_backend(
                src_backend_name, vserver_name=src_vserver, force_rest=True)
        else:
            dest_client = config_utils.get_client_for_backend(
                dest_backend_name, vserver_name=dest_vserver)
            src_client = config_utils.get_client_for_backend(
                src_backend_name, vserver_name=src_vserver)

        provisioning_options = (
            src_client.get_provisioning_options_from_flexvol(
                src_flexvol_name)
        )
        pool_is_flexgroup = provisioning_options.get('is_flexgroup', False)

        # 1. Create destination 'dp' FlexVol if it doesn't exist
        if not dest_client.flexvol_exists(dest_flexvol_name):
            self.create_destination_flexvol(
                src_backend_name,
                dest_backend_name,
                src_flexvol_name,
                dest_flexvol_name,
                pool_is_flexgroup=pool_is_flexgroup)

        active_sync_asymmetric_policy = self.is_active_sync_asymmetric_policy(
            replication_policy)
        src_cg = "cg_" + src_flexvol_name if active_sync_asymmetric_policy \
            else None
        dest_cg = "cg_" + dest_flexvol_name if active_sync_asymmetric_policy \
            else None
        src_cg_path = "/cg/" + str(src_cg)
        dest_cg_path = "/cg/" + str(dest_cg)

        # 2. Check if SnapMirror relationship exists
        if active_sync_asymmetric_policy:
            existing_mirrors = dest_client.get_snapmirrors(
                src_vserver, src_cg_path, dest_vserver, dest_cg_path)
        else:
            existing_mirrors = dest_client.get_snapmirrors(
                src_vserver, src_flexvol_name, dest_vserver, dest_flexvol_name)

        msg_payload = {
            'src_vserver': src_vserver,
            'src_volume': src_flexvol_name,
            'dest_vserver': dest_vserver,
            'dest_volume': dest_flexvol_name,
        }

        # 3. Create and initialize SnapMirror if it doesn't already exist
        if not existing_mirrors:
            # TODO(gouthamr): Change the schedule from hourly to config value
            msg = ("Creating a SnapMirror relationship between "
                   "%(src_vserver)s:%(src_flexvol_name)s and %(dest_vserver)s:"
                   "%(dest_volume)s.")
            LOG.debug(msg, msg_payload)

            try:
                if active_sync_asymmetric_policy:
                    src_client.create_ontap_consistency_group(
                        src_vserver, [src_flexvol_name], src_cg)

                dest_client.create_snapmirror(
                    src_vserver,
                    src_flexvol_name,
                    dest_vserver,
                    dest_flexvol_name,
                    src_cg,
                    dest_cg,
                    schedule=None
                    if active_sync_asymmetric_policy
                    else 'hourly',
                    policy=replication_policy,
                    relationship_type='extended_data_protection')

                # Initialize async transfer of the initial data
                if active_sync_asymmetric_policy:
                    src_flexvol_name = src_cg_path
                    dest_flexvol_name = dest_cg_path
                if not active_sync_asymmetric_policy:
                    msg = ("Initializing SnapMirror transfers between "
                           "%(src_vserver)s:%(src_volume)s and "
                           "%(dest_vserver)s:%(dest_volume)s.")
                    LOG.debug(msg, msg_payload)
                    dest_client.initialize_snapmirror(
                        src_vserver, src_flexvol_name, dest_vserver,
                        dest_flexvol_name, active_sync_asymmetric_policy)
            except netapp_api.NaApiError as e:
                with excutils.save_and_reraise_exception() as raise_ctxt:
                    if (e.code == netapp_api.EAPIERROR and
                        all(substr in e.message for
                            substr in GEOMETRY_HAS_BEEN_CHANGED)):
                        msg = _("Error creating SnapMirror. Geometry has "
                                "changed on destination volume.")
                        LOG.error(msg)
                        self.delete_snapmirror(src_backend_name,
                                               dest_backend_name,
                                               src_flexvol_name,
                                               dest_flexvol_name)
                        raise_ctxt.reraise = False
                        raise na_utils.GeometryHasChangedOnDestination(msg)

        # 4. Try to repair SnapMirror if existing
        else:
            snapmirror = existing_mirrors[0]
            if active_sync_asymmetric_policy:
                src_flexvol_name = src_cg_path
                dest_flexvol_name = dest_cg_path
            if snapmirror.get('mirror-state') != 'snapmirrored' and \
                    snapmirror.get('mirror-state') != 'in_sync':
                try:
                    msg = ("SnapMirror between %(src_vserver)s:%(src_volume)s "
                           "and %(dest_vserver)s:%(dest_volume)s is in "
                           "'%(state)s' state. Attempting to repair it.")
                    msg_payload['state'] = snapmirror.get('mirror-state')
                    LOG.debug(msg, msg_payload)

                    dest_client.resume_snapmirror(src_vserver,
                                                  src_flexvol_name,
                                                  dest_vserver,
                                                  dest_flexvol_name)
                    dest_client.resync_snapmirror(src_vserver,
                                                  src_flexvol_name,
                                                  dest_vserver,
                                                  dest_flexvol_name)
                except netapp_api.NaApiError:
                    LOG.exception("Could not re-sync SnapMirror")

    def create_snapmirror_for_cg(
            self,
            src_backend_name,
            dest_backend_name,
            src_cg_name,
            dest_cg_name,
            storage_object_type,
            storage_object_names,
            replication_policy):
        """Set up a SnapMirror relationship for a consistency group.

        This method ensures that a SnapMirror relationship is created and
        initialized for a given consistency group. If the relationship
        already exists but is not in a healthy state, it attempts to
        repair and re-sync the relationship.

        Args:
            src_backend_name (str): The name of the source backend.
            dest_backend_name (str): The name of the destination backend.
            src_cg_name (str): The name of the source consistency group.
            dest_cg_name (str): The name of the destination consistency
                group.
            storage_object_type (StorageObjectType): The type of storage
                objects ('volume' or 'lun').
            storage_object_names (list): List of storage object names
                within the CG.
            replication_policy (str): The replication policy to use for
                the SnapMirror relationship.

        Raises:
            netapp_api.NaApiError: If the SnapMirror creation or repair
                fails.
        """

        LOG.debug("Starting create_snapmirror_for_cg method")

        dest_backend_config = config_utils.get_backend_configuration(
            dest_backend_name)
        dest_vserver = dest_backend_config.netapp_vserver
        source_backend_config = config_utils.get_backend_configuration(
            src_backend_name)
        src_vserver = source_backend_config.netapp_vserver

        # CG can only be replicated using REST API
        dest_client = config_utils.get_client_for_backend(
            dest_backend_name, vserver_name=dest_vserver, force_rest=True)

        src_cg_path = na_utils.create_cg_path(src_cg_name)
        dest_cg_path = na_utils.create_cg_path(dest_cg_name)

        # Check if SnapMirror relationship exists
        existing_mirrors = dest_client.get_snapmirrors(src_vserver,
                                                       src_cg_path,
                                                       dest_vserver,
                                                       dest_cg_path)

        # Create and initialize SnapMirror if it doesn't already exist
        if not existing_mirrors:
            LOG.info("Creating snapmirror for cg from %s to %s on destination "
                     "backend %s for %s with replication policy %s",
                     src_cg_name, dest_cg_name, dest_backend_name,
                     storage_object_names, replication_policy)
            try:
                create_snapmirror_for_cg_client = (
                    self._get_create_snapmirror_for_cg_client(
                        dest_client,
                        storage_object_type))
                create_snapmirror_for_cg_client(
                    src_vserver,
                    src_cg_name,
                    dest_vserver,
                    dest_cg_name,
                    storage_object_names,
                    replication_policy)
            except netapp_api.NaApiError:
                LOG.exception("Failed to create SnapMirror for CG.")
                raise
        # Try to repair SnapMirror if existing
        else:
            LOG.debug("Updating snapmirror for cg from %s to %s on "
                      "destination backend %s for %s with "
                      "replication policy %s",
                      src_cg_name, dest_cg_name, dest_backend_name,
                      storage_object_names, replication_policy)
            snapmirror = existing_mirrors[0]
            # If existing transfer is ongoing, do not interfere.
            if snapmirror.get('mirror-state') != 'snapmirrored' and \
                    snapmirror.get('mirror-state') != 'in_sync' and \
                    snapmirror.get('mirror-state') != 'transferring':
                try:
                    msg = ("SnapMirror between %(src_vserver)s:%(src_cg)s "
                           "and %(dest_vserver)s:%(dest_cg)s is in "
                           "'%(state)s' state. Attempting to repair it.")
                    msg_payload = {'state': snapmirror.get('mirror-state'),
                                   'src_vserver': src_vserver,
                                   'src_volume': src_cg_name,
                                   'dest_vserver': dest_vserver,
                                   'dest_volume': dest_cg_name}
                    LOG.debug(msg, msg_payload)
                    dest_client.resume_snapmirror(src_vserver,
                                                  src_cg_path,
                                                  dest_vserver,
                                                  dest_cg_path)
                except netapp_api.NaApiError:
                    LOG.exception("Could not re-sync SnapMirror.")
        LOG.debug("Finished create_snapmirror_for_cg method")

    def _get_create_snapmirror_for_cg_client(self, dest_client,
                                             storage_object_type):
        if storage_object_type == na_utils.StorageObjectType.VOLUME:
            return dest_client.create_snapmirror_for_cg_with_flexvols
        else:
            raise na_utils.NetAppDriverException(
                message=_("Unsupported storage object type for CG "
                          "replication: %s") %
                storage_object_type.value)

    def delete_snapmirror(self, src_backend_name, dest_backend_name,
                          src_flexvol_name, dest_flexvol_name, release=True):
        """Ensure all information about a SnapMirror relationship is removed.

        1. Abort SnapMirror
        2. Delete the SnapMirror
        3. Release SnapMirror to cleanup SnapMirror metadata and snapshots
        """
        dest_backend_config = config_utils.get_backend_configuration(
            dest_backend_name)
        dest_vserver = dest_backend_config.netapp_vserver
        dest_client = config_utils.get_client_for_backend(
            dest_backend_name, vserver_name=dest_vserver)

        source_backend_config = config_utils.get_backend_configuration(
            src_backend_name)
        src_vserver = source_backend_config.netapp_vserver

        # 1. Abort any ongoing transfers
        try:
            dest_client.abort_snapmirror(src_vserver,
                                         src_flexvol_name,
                                         dest_vserver,
                                         dest_flexvol_name,
                                         clear_checkpoint=False)
        except netapp_api.NaApiError:
            # Snapmirror is already deleted
            pass

        # 2. Delete SnapMirror Relationship and cleanup destination snapshots
        try:
            dest_client.delete_snapmirror(src_vserver,
                                          src_flexvol_name,
                                          dest_vserver,
                                          dest_flexvol_name)
        except netapp_api.NaApiError as e:
            with excutils.save_and_reraise_exception() as exc_context:
                if (e.code == netapp_api.EOBJECTNOTFOUND or
                        e.code == netapp_api.ESOURCE_IS_DIFFERENT or
                        ENTRY_DOES_NOT_EXIST in e.message):
                    LOG.info('No SnapMirror relationship to delete.')
                    exc_context.reraise = False

        if release:
            # If the source is unreachable, do not perform the release
            try:
                src_client = config_utils.get_client_for_backend(
                    src_backend_name, vserver_name=src_vserver)
            except Exception:
                src_client = None
            # 3. Cleanup SnapMirror relationship on source
            try:
                if src_client:
                    src_client.release_snapmirror(src_vserver,
                                                  src_flexvol_name,
                                                  dest_vserver,
                                                  dest_flexvol_name)
            except netapp_api.NaApiError as e:
                with excutils.save_and_reraise_exception() as exc_context:
                    if (e.code == netapp_api.EOBJECTNOTFOUND or
                            e.code == netapp_api.ESOURCE_IS_DIFFERENT or
                            ENTRY_DOES_NOT_EXIST in e.message):
                        # Handle the case where the SnapMirror is already
                        # cleaned up
                        exc_context.reraise = False

    def update_snapmirror(self, src_backend_name, dest_backend_name,
                          src_flexvol_name, dest_flexvol_name):
        """Schedule a SnapMirror update on the backend."""
        dest_backend_config = config_utils.get_backend_configuration(
            dest_backend_name)
        dest_vserver = dest_backend_config.netapp_vserver
        dest_client = config_utils.get_client_for_backend(
            dest_backend_name, vserver_name=dest_vserver)

        source_backend_config = config_utils.get_backend_configuration(
            src_backend_name)
        src_vserver = source_backend_config.netapp_vserver

        # Update SnapMirror
        dest_client.update_snapmirror(src_vserver,
                                      src_flexvol_name,
                                      dest_vserver,
                                      dest_flexvol_name)

    def quiesce_then_abort(self, src_backend_name, dest_backend_name,
                           src_flexvol_name, dest_flexvol_name):
        """Quiesce a SnapMirror and wait with retries before aborting."""
        dest_backend_config = config_utils.get_backend_configuration(
            dest_backend_name)
        dest_vserver = dest_backend_config.netapp_vserver
        dest_client = config_utils.get_client_for_backend(
            dest_backend_name, vserver_name=dest_vserver)

        source_backend_config = config_utils.get_backend_configuration(
            src_backend_name)
        src_vserver = source_backend_config.netapp_vserver

        # 1. Attempt to quiesce, then abort
        dest_client.quiesce_snapmirror(src_vserver,
                                       src_flexvol_name,
                                       dest_vserver,
                                       dest_flexvol_name)

        retries = (source_backend_config.netapp_snapmirror_quiesce_timeout /
                   QUIESCE_RETRY_INTERVAL)

        @utils.retry(na_utils.NetAppDriverException,
                     interval=QUIESCE_RETRY_INTERVAL,
                     retries=retries, backoff_rate=1)
        def wait_for_quiesced():
            snapmirror = dest_client.get_snapmirrors(
                src_vserver, src_flexvol_name, dest_vserver,
                dest_flexvol_name,
                desired_attributes=['relationship-status', 'mirror-state'])[0]
            if (snapmirror.get('relationship-status') not in ['quiesced',
                                                              'paused']):
                msg = _("SnapMirror relationship is not quiesced.")
                raise na_utils.NetAppDriverException(msg)

        try:
            wait_for_quiesced()
        except na_utils.NetAppDriverException:
            dest_client.abort_snapmirror(src_vserver,
                                         src_flexvol_name,
                                         dest_vserver,
                                         dest_flexvol_name,
                                         clear_checkpoint=False)

    def break_snapmirror(self, src_backend_name, dest_backend_name,
                         src_flexvol_name, dest_flexvol_name):
        """Break SnapMirror relationship.

        1. Quiesce any ongoing SnapMirror transfers
        2. Wait until SnapMirror finishes transfers and enters quiesced state
        3. Break SnapMirror
        4. Mount the destination volume so it is given a junction path
        """
        dest_backend_config = config_utils.get_backend_configuration(
            dest_backend_name)
        dest_vserver = dest_backend_config.netapp_vserver
        dest_client = config_utils.get_client_for_backend(
            dest_backend_name, vserver_name=dest_vserver)

        source_backend_config = config_utils.get_backend_configuration(
            src_backend_name)
        src_vserver = source_backend_config.netapp_vserver

        # 1. Attempt to quiesce, then abort
        self.quiesce_then_abort(src_backend_name, dest_backend_name,
                                src_flexvol_name, dest_flexvol_name)

        # 2. Break SnapMirror
        dest_client.break_snapmirror(src_vserver,
                                     src_flexvol_name,
                                     dest_vserver,
                                     dest_flexvol_name)

        # 3. Mount the destination volume and create a junction path
        if not self.is_consistent_replication_enabled(self.configuration):
            dest_client.mount_flexvol(dest_flexvol_name)

    def resync_snapmirror(self, src_backend_name, dest_backend_name,
                          src_flexvol_name, dest_flexvol_name):
        """Re-sync (repair / re-establish) SnapMirror relationship."""
        dest_backend_config = config_utils.get_backend_configuration(
            dest_backend_name)
        dest_vserver = dest_backend_config.netapp_vserver
        dest_client = config_utils.get_client_for_backend(
            dest_backend_name, vserver_name=dest_vserver)

        source_backend_config = config_utils.get_backend_configuration(
            src_backend_name)
        src_vserver = source_backend_config.netapp_vserver

        dest_client.resync_snapmirror(src_vserver,
                                      src_flexvol_name,
                                      dest_vserver,
                                      dest_flexvol_name)

    def resume_snapmirror(self, src_backend_name, dest_backend_name,
                          src_flexvol_name, dest_flexvol_name):
        """Resume SnapMirror relationship from a quiesced state."""
        dest_backend_config = config_utils.get_backend_configuration(
            dest_backend_name)
        dest_vserver = dest_backend_config.netapp_vserver
        dest_client = config_utils.get_client_for_backend(
            dest_backend_name, vserver_name=dest_vserver)

        source_backend_config = config_utils.get_backend_configuration(
            src_backend_name)
        src_vserver = source_backend_config.netapp_vserver

        dest_client.resume_snapmirror(src_vserver,
                                      src_flexvol_name,
                                      dest_vserver,
                                      dest_flexvol_name)

    def create_destination_flexvol(self, src_backend_name, dest_backend_name,
                                   src_flexvol_name, dest_flexvol_name,
                                   pool_is_flexgroup=False):
        """Create a SnapMirror mirror target FlexVol for a given source."""
        dest_backend_config = config_utils.get_backend_configuration(
            dest_backend_name)
        dest_vserver = dest_backend_config.netapp_vserver
        dest_client = config_utils.get_client_for_backend(
            dest_backend_name, vserver_name=dest_vserver)

        source_backend_config = config_utils.get_backend_configuration(
            src_backend_name)
        src_vserver = source_backend_config.netapp_vserver
        src_client = config_utils.get_client_for_backend(
            src_backend_name, vserver_name=src_vserver)

        provisioning_options = (
            src_client.get_provisioning_options_from_flexvol(
                src_flexvol_name)
        )
        provisioning_options.pop('is_flexgroup')

        # If the source is encrypted then the destination needs to be
        # encrypted too. Using is_flexvol_encrypted because it includes
        # a simple check to ensure that the NVE feature is supported.
        if src_client.is_flexvol_encrypted(src_flexvol_name, src_vserver):
            provisioning_options['encrypt'] = 'true'

        # Remove size and volume_type
        size = provisioning_options.pop('size', None)
        if not size:
            msg = _("Unable to read the size of the source FlexVol (%s) "
                    "to create a SnapMirror destination.")
            raise na_utils.NetAppDriverException(msg % src_flexvol_name)
        provisioning_options.pop('volume_type', None)

        source_aggregate = provisioning_options.pop('aggregate')
        aggregate_map = self._get_replication_aggregate_map(
            src_backend_name, dest_backend_name)

        destination_aggregate = []
        for src_aggr in source_aggregate:
            dst_aggr = aggregate_map.get(src_aggr, None)
            if dst_aggr:
                destination_aggregate.append(dst_aggr)
            else:
                msg = _("Unable to find configuration matching the source "
                        "aggregate and the destination aggregate. Option "
                        "netapp_replication_aggregate_map may be incorrect.")
                raise na_utils.NetAppDriverException(message=msg)

        # NOTE(gouthamr): The volume is intentionally created as a Data
        # Protection volume; junction-path will be added on breaking
        # the mirror.
        provisioning_options['volume_type'] = 'dp'

        if pool_is_flexgroup:
            compression_enabled = provisioning_options.pop(
                'compression_enabled', False)
            # cDOT compression requires that deduplication be enabled.
            dedupe_enabled = provisioning_options.pop(
                'dedupe_enabled', False) or compression_enabled

            dest_client.create_volume_async(
                dest_flexvol_name,
                destination_aggregate,
                size,
                **provisioning_options)

            timeout = self._get_replication_volume_online_timeout()

            def _wait_volume_is_online():
                volume_state = dest_client.get_volume_state(
                    name=dest_flexvol_name)
                if volume_state and volume_state == 'online':
                    raise loopingcall.LoopingCallDone()

            try:
                wait_call = loopingcall.FixedIntervalWithTimeoutLoopingCall(
                    _wait_volume_is_online)
                wait_call.start(interval=5, timeout=timeout).wait()

                if dedupe_enabled:
                    dest_client.enable_volume_dedupe_async(
                        dest_flexvol_name)
                if compression_enabled:
                    dest_client.enable_volume_compression_async(
                        dest_flexvol_name)

            except loopingcall.LoopingCallTimeOut:
                msg = _("Timeout waiting destination FlexGroup "
                        "to come online.")
                raise na_utils.NetAppDriverException(msg)

        else:
            dest_client.create_flexvol(dest_flexvol_name,
                                       destination_aggregate[0],
                                       size,
                                       **provisioning_options)

            timeout = self._get_replication_volume_online_timeout()

            def _wait_volume_is_online():
                volume_state = dest_client.get_volume_state(
                    name=dest_flexvol_name)
                if volume_state and volume_state == 'online':
                    raise loopingcall.LoopingCallDone()

            try:
                wait_call = loopingcall.FixedIntervalWithTimeoutLoopingCall(
                    _wait_volume_is_online)
                wait_call.start(interval=5, timeout=timeout).wait()

            except loopingcall.LoopingCallTimeOut:
                msg = _("Timeout waiting destination FlexVol to to come "
                        "online.")
                raise na_utils.NetAppDriverException(msg)

    def ensure_snapmirrors(self, config, src_backend_name, src_flexvol_names):
        """Ensure all the SnapMirrors needed for whole-backend replication."""
        backend_names = self.get_replication_backend_names(config)
        replication_policy = self.get_replication_policy(config)
        for dest_backend_name in backend_names:
            for src_flexvol_name in src_flexvol_names:

                dest_flexvol_name = src_flexvol_name

                retry_exceptions = (
                    na_utils.GeometryHasChangedOnDestination,
                )

                @utils.retry(retry_exceptions,
                             interval=30, retries=6, backoff_rate=1)
                def _try_create_snapmirror():
                    self.create_snapmirror(src_backend_name,
                                           dest_backend_name,
                                           src_flexvol_name,
                                           dest_flexvol_name,
                                           replication_policy)
                try:
                    _try_create_snapmirror()
                except na_utils.NetAppDriverException as e:
                    with excutils.save_and_reraise_exception():
                        if isinstance(e, retry_exceptions):
                            LOG.error("Number of tries exceeded "
                                      "while trying to create SnapMirror.")

    def ensure_consistent_replication_snapmirrors(self, config,
                                                  src_backend_name,
                                                  storage_object_type,
                                                  storage_object_names):
        """Ensure all the SnapMirrors needed for whole-backend replication."""

        src_backend_config = (
            config_utils.get_backend_configuration(src_backend_name))
        src_vserver = src_backend_config.netapp_vserver
        src_client = (
            config_utils.get_client_for_backend(src_backend_name,
                                                vserver_name=src_vserver,
                                                force_rest=True))
        destination_backend_names = self.get_replication_backend_names(config)
        replication_policy = self.get_replication_policy(config)
        new_cg_created = False

        # Get the current datetime
        current_timestamp = int(timeutils.utcnow().timestamp())

        src_cg_name = "cg_cinder_pool_" + str(current_timestamp)

        if storage_object_type == na_utils.StorageObjectType.VOLUME:
            # Verify if Flexvols are part of a single CG
            cg_info = src_client.get_flexvols_cg_info(storage_object_names)
            cg_names = self._extract_cg_names_from_info(cg_info)
            if len(cg_names) == 1:
                LOG.info("Single Consistency Group %s is present across the "
                         "FlexVols. It will be used for CG protection.",
                         list(cg_names)[0])
                src_cg_name = list(cg_names)[0]
            elif len(cg_names) > 1:
                msg = _(
                    "FlexVols are part of multiple Consistency Groups: %s. "
                    "Please ensure all FlexVols are in a single CG "
                    "before proceeding.") % ', '.join(cg_names)
                raise na_utils.NetAppDriverException(msg)
            else:
                LOG.info(
                    "FlexVols are not part of any Consistency Group. "
                    "Proceeding to create a new CG %s.", src_cg_name)
                src_client.create_ontap_consistency_group(src_vserver,
                                                          storage_object_names,
                                                          src_cg_name)
                new_cg_created = True

            if not new_cg_created:
                self._expand_flexvols_not_in_cg(src_client, src_vserver,
                                                src_cg_name, cg_info)

        if replication_policy == "AutomatedFailOver":
            precheck = (
                self._consistent_replication_precheck_for_automated_failover_policy)  # noqa: E501
            precheck(src_backend_name, destination_backend_names,
                     storage_object_type, storage_object_names)

        for dest_backend_name in destination_backend_names:
            dest_cg_name = src_cg_name
            self.create_snapmirror_for_cg(src_backend_name,
                                          dest_backend_name,
                                          src_cg_name, dest_cg_name,
                                          storage_object_type,
                                          storage_object_names,
                                          replication_policy)

    def _extract_cg_names_from_info(self, cg_info):
        cg_names = set()
        for info in cg_info:
            cg_name = info.get('cg_name')
            if cg_name:
                cg_names.add(cg_name)
        return cg_names

    def _expand_flexvols_not_in_cg(self, src_client, src_vserver, src_cg_name,
                                   cg_info):
        """Expand the consistency group with FlexVols not already in a CG."""
        LOG.debug("Expanding Consistency Group %s with FlexVols not already "
                  "in a CG.", src_cg_name)
        flexvols_without_cg = []
        cg_names = set()
        for info in cg_info:
            cg_name = info.get('cg_name')
            if cg_name:
                cg_names.add(cg_name)
            else:
                flexvols_without_cg.append(info.get('flexvol_name'))
        if flexvols_without_cg:
            src_client.expand_ontap_consistency_group(src_vserver, src_cg_name,
                                                      flexvols_without_cg)

    def break_snapmirrors(self, config, src_backend_name, src_flexvol_names,
                          chosen_target):
        """Break all existing SnapMirror relationships for a given back end."""
        failed_to_break = []
        backend_names = self.get_replication_backend_names(config)
        for dest_backend_name in backend_names:
            for src_flexvol_name in src_flexvol_names:

                dest_flexvol_name = src_flexvol_name
                try:
                    self.break_snapmirror(src_backend_name,
                                          dest_backend_name,
                                          src_flexvol_name,
                                          dest_flexvol_name)
                except netapp_api.NaApiError:
                    msg = _("Unable to break SnapMirror between Source "
                            "%(src)s and Destination %(dest)s. Associated "
                            "volumes will have their replication state set "
                            "to error.")
                    payload = {
                        'src': ':'.join([src_backend_name, src_flexvol_name]),
                        'dest': ':'.join([dest_backend_name,
                                         dest_flexvol_name]),
                    }
                    if dest_backend_name == chosen_target:
                        failed_to_break.append(src_flexvol_name)
                    LOG.exception(msg, payload)

        return failed_to_break

    def update_snapmirrors(self, config, src_backend_name, src_flexvol_names):
        """Update all existing SnapMirror relationships on a given back end."""
        backend_names = self.get_replication_backend_names(config)
        for dest_backend_name in backend_names:
            for src_flexvol_name in src_flexvol_names:

                dest_flexvol_name = src_flexvol_name
                try:
                    self.update_snapmirror(src_backend_name,
                                           dest_backend_name,
                                           src_flexvol_name,
                                           dest_flexvol_name)
                except netapp_api.NaApiError:
                    # Ignore any errors since the current source may be
                    # unreachable
                    pass

    def create_vserver_peer(self, src_vserver, src_backend_name, dest_vserver,
                            peer_applications):
        """Create a vserver peer relationship"""
        src_client = config_utils.get_client_for_backend(
            src_backend_name, vserver_name=src_vserver)

        vserver_peers = src_client.get_vserver_peers(src_vserver, dest_vserver)
        if not vserver_peers:
            src_client.create_vserver_peer(
                src_vserver, dest_vserver,
                vserver_peer_application=peer_applications)
            LOG.debug("Vserver peer relationship created between %(src)s "
                      "and %(dest)s. Peering application set to %(app)s.",
                      {'src': src_vserver, 'dest': dest_vserver,
                       'app': peer_applications})
            return None

        for vserver_peer in vserver_peers:
            if all(app in vserver_peer['applications'] for app in
                   peer_applications):
                LOG.debug("Found vserver peer relationship between %s and %s.",
                          src_vserver, dest_vserver)
                return None

        msg = _("Vserver peer relationship found between %(src)s and %(dest)s "
                "but peering application %(app)s isn't defined.")
        raise na_utils.NetAppDriverException(msg % {'src': src_vserver,
                                                    'dest': dest_vserver,
                                                    'app': peer_applications})

    def _choose_failover_target(self, backend_name, flexvols,
                                replication_targets):
        target_lag_times = []

        for target in replication_targets:
            all_target_mirrors = self.get_snapmirrors(
                backend_name, target, None, None)
            flexvol_mirrors = self._filter_and_sort_mirrors(
                all_target_mirrors, flexvols)

            if not flexvol_mirrors:
                msg = ("Ignoring replication target %(target)s because no "
                       "SnapMirrors were found for any of the flexvols "
                       "in (%(flexvols)s).")
                payload = {
                    'flexvols': ', '.join(flexvols),
                    'target': target,
                }
                LOG.debug(msg, payload)
                continue

            target_lag_times.append(
                {
                    'target': target,
                    'highest-lag-time': flexvol_mirrors[0]['lag-time'],
                }
            )

        # The best target is one with the least 'worst' lag time.
        best_target = (sorted(target_lag_times,
                              key=lambda x: int(x['highest-lag-time']))[0]
                       if len(target_lag_times) > 0 else {})

        return best_target.get('target')

    def _choose_failover_target_of_cg_replication(
            self,
            backend_name,
            consistency_group_name,
            replication_targets):

        LOG.debug('data_motion::'
                  '_choose_failover_target_of_cg_replication start')

        target_lag_times = []

        for target in replication_targets:
            snapmirror_for_cg = self.get_snapmirrors(
                backend_name,
                target,
                na_utils.create_cg_path(consistency_group_name),
                na_utils.create_cg_path(consistency_group_name))

            target_lag_times.append(
                {
                    'target': target,
                    'highest-lag-time': snapmirror_for_cg[0]['lag-time'],
                }
            )

        # The best target is one with the least 'worst' lag time.
        best_target = (sorted(target_lag_times,
                              key=lambda x: int(x['highest-lag-time']))[0]
                       if len(target_lag_times) > 0 else {})

        LOG.debug('Best failover target: %s', best_target.get('target'))
        LOG.debug('data_motion::'
                  '_choose_failover_target_of_cg_replication completed')

        return best_target.get('target')

    def _filter_and_sort_mirrors(self, mirrors, flexvols):
        """Return mirrors reverse-sorted by lag time.

        The 'slowest' mirror determines the best update that occurred on a
        given replication target.
        """
        filtered_mirrors = [x for x in mirrors
                            if x.get('destination-volume') in flexvols]
        sorted_mirrors = sorted(filtered_mirrors,
                                key=lambda x: int(x.get('lag-time')),
                                reverse=True)

        return sorted_mirrors

    def _complete_failover(self, source_backend_name, replication_targets,
                           flexvols, volumes, failover_target=None):
        """Failover a backend to a secondary replication target."""
        volume_updates = []

        active_backend_name = failover_target or self._choose_failover_target(
            source_backend_name, flexvols, replication_targets)

        if active_backend_name is None:
            msg = _("No suitable host was found to failover.")
            raise na_utils.NetAppDriverException(msg)

        source_backend_config = config_utils.get_backend_configuration(
            source_backend_name)

        # 1. Start an update to try to get a last minute transfer before we
        # quiesce and break
        self.update_snapmirrors(source_backend_config, source_backend_name,
                                flexvols)
        # 2. Break SnapMirrors
        failed_to_break = self.break_snapmirrors(source_backend_config,
                                                 source_backend_name,
                                                 flexvols, active_backend_name)

        # 3. Update cinder volumes within this host
        for volume in volumes:
            replication_status = fields.ReplicationStatus.FAILED_OVER
            volume_pool = volume_utils.extract_host(volume['host'],
                                                    level='pool')
            if volume_pool in failed_to_break:
                replication_status = 'error'

            volume_update = {
                'volume_id': volume['id'],
                'updates': {
                    'replication_status': replication_status,
                },
            }
            volume_updates.append(volume_update)

        return active_backend_name, volume_updates

    def _complete_failover_consistent_rep_async(
            self,
            source_backend_name,
            replication_targets,
            volumes,
            failover_target=None):
        """Perform failover for consistent replication.

        This function performs failover for consistent replication for
        asynchronous replication policy.
        """

        LOG.debug('data_motion::_complete_failover_consistent_rep_async '
                  'started')

        volume_updates = []
        cg_list = []

        if not self.configuration.netapp_disaggregated_platform:
            flexvols = self.ssc_library.get_ssc_flexvol_names()
            src_client = config_utils.get_client_for_backend(
                backend_name=source_backend_name,
                force_rest=True)
            cg_info = src_client.get_flexvols_cg_info(flexvols[0])
            cg_name = cg_info[0].get('cg_name')
            cg_list.append(na_utils.create_cg_path(cg_name))
        else:
            LOG.error("ASAr2 platform is not supported for replication")
            raise na_utils.NetAppDriverException("ASAr2 platform is not "
                                                 "supported for replication")

        active_backend_name = (
            failover_target or
            self._choose_failover_target_of_cg_replication(
                source_backend_name, cg_name, replication_targets))

        if active_backend_name is None:
            msg = _("No suitable host was found to failover.")
            raise na_utils.NetAppDriverException(msg)

        source_backend_config = config_utils.get_backend_configuration(
            source_backend_name)

        # Start an update to try to get a last minute transfer before we
        # quiesce and break
        self.update_snapmirrors(source_backend_config, source_backend_name,
                                cg_list)
        # Break SnapMirrors
        failed_to_break = self.break_snapmirrors(
            source_backend_config,
            source_backend_name,
            cg_list, active_backend_name)

        # For NFS backend, mount the destination flexvols after break
        if (not failed_to_break and
                source_backend_config.safe_get(
                    'netapp_storage_protocol') == 'nfs'):
            LOG.debug('Mounting destination flexvols after snapmirror break')
            dest_client = (
                config_utils.get_client_for_backend(active_backend_name))
            for flexvol in flexvols:
                dest_client.mount_flexvol(flexvol)

        # Update cinder volumes within this host
        replication_status = fields.ReplicationStatus.FAILED_OVER
        if failed_to_break:
            replication_status = 'error'

        for volume in volumes:
            volume_update = {
                'volume_id': volume['id'],
                'updates': {
                    'replication_status': replication_status,
                },
            }
            volume_updates.append(volume_update)

        LOG.debug('data_motion::_complete_failover_consistent_rep_async '
                  'completed')

        return active_backend_name, volume_updates

    def _complete_failover_active_sync(self,
                                       source_backend_name,
                                       destination_backend_name,
                                       volumes):

        LOG.debug('data_motion::_complete_failover_active_sync started')
        LOG.debug("Source backend: %s, Destination backend: %s",
                  source_backend_name, destination_backend_name)

        src_client = None

        if destination_backend_name is None:
            msg = _("No suitable host was found to failover.")
            LOG.error(msg)
            raise na_utils.NetAppDriverException(msg)

        try:
            src_client = config_utils.get_client_for_backend(
                backend_name=source_backend_name,
                force_rest=True)
        except Exception:
            LOG.warning("Failed to connect to source backend during failover.")

        try:
            dst_client = config_utils.get_client_for_backend(
                backend_name=destination_backend_name,
                force_rest=True)
        except Exception:
            LOG.error("Failed to connect to "
                      "destination backend client "
                      "for failover.")
            raise na_utils.NetAppDriverException("Failed to connect to "
                                                 "destination backend client "
                                                 "for failover.")

        if not self.configuration.netapp_disaggregated_platform:
            flexvols = self.ssc_library.get_ssc_flexvol_names()
            if src_client:
                cg_info = src_client.get_flexvols_cg_info(flexvols[0])
            else:
                cg_info = dst_client.get_flexvols_cg_info(flexvols[0])
            cg_name = cg_info[0].get('cg_name')
        else:
            LOG.error("ASAr2 platform is not supported for replication")
            raise na_utils.NetAppDriverException("ASAr2 platform is not "
                                                 "supported for replication")

        if src_client:
            # This is a planned failover as the source is reachable
            LOG.info("Source backend is reachable during failover. "
                     "Proceeding with PLANNED failover.")
            src_backend_config = config_utils.get_backend_configuration(
                source_backend_name)
            src_vserver = src_backend_config.netapp_vserver
            dest_backend_config = config_utils.get_backend_configuration(
                destination_backend_name)
            dest_vserver = dest_backend_config.netapp_vserver
            dst_client.failover_snapmirror_active_sync(src_vserver,
                                                       cg_name, dest_vserver,
                                                       cg_name)
        else:
            # Unplanned failover, source is unreachable
            LOG.info("Source backend is unreachable during failover. "
                     "Proceeding with UNPLANNED failover.")
            LOG.info("Snapmirror relationship will automatically "
                     "failover to destination backend: %s",
                     destination_backend_name)

        """Failover a backend to a secondary replication target."""
        volume_updates = []

        # Update cinder volumes within this host
        for volume in volumes:
            replication_status = fields.ReplicationStatus.FAILED_OVER

            volume_update = {
                'volume_id': volume['id'],
                'updates': {
                    'replication_status': replication_status,
                },
            }
            volume_updates.append(volume_update)

        return destination_backend_name, volume_updates

    def _complete_failback(self, volumes):
        LOG.debug('data_motion::_complete_failback started')
        volume_updates = []
        volume_update = []
        # Update the ZAPI client to the backend we failed over to
        active_backend_name = self.backend_name
        self._update_zapi_client(active_backend_name)
        self.failed_over = False
        self.failed_over_backend_name = active_backend_name
        for volume in volumes:
            replication_status = fields.ReplicationStatus.ENABLED
            volume_update = {
                'volume_id': volume['id'],
                'updates': {'replication_status': replication_status},
            }
            volume_updates.append(volume_update)
        LOG.debug('data_motion::_complete_failback ended')
        return active_backend_name, volume_updates, []

    def _complete_failback_active_sync(self, primary_backend_name,
                                       secondary_backend_name, volumes):
        LOG.debug('data_motion::_complete_failback_active_sync started')

        if primary_backend_name:
            msg = _("Primary backend to which the replication will be "
                    "failed back to is required.")
            raise na_utils.NetAppDriverException(msg)

        if secondary_backend_name:
            msg = _("Secondary backend to which the replication is "
                    "failed over is required.")
            raise na_utils.NetAppDriverException(msg)

        try:
            src_client = config_utils.get_client_for_backend(
                backend_name=primary_backend_name, force_rest=True)
        except Exception:
            raise na_utils.NetAppDriverException(
                "Failed to connect to "
                "primary backend client %s for "
                "failback.",
                primary_backend_name)

        if not self.configuration.netapp_disaggregated_platform:
            flexvols = self.ssc_library.get_ssc_flexvol_names()
            cg_info = src_client.get_flexvols_cg_info(flexvols[0])
            cg_name = cg_info[0].get('cg_name')
        else:
            raise na_utils.NetAppDriverException(
                "ASAr2 platform is not supported for replication")

        LOG.info("Failing back replication from secondary backend %s "
                 "to primary backend %s. for consistency group %s",
                 secondary_backend_name, primary_backend_name, cg_name)
        src_backend_config = config_utils.get_backend_configuration(
            primary_backend_name)
        src_vserver = src_backend_config.netapp_vserver
        dest_backend_config = config_utils.get_backend_configuration(
            secondary_backend_name)
        dest_vserver = dest_backend_config.netapp_vserver

        # Failing back snapmirror from destination back to source
        src_client.failover_snapmirror_active_sync(dest_vserver, cg_name,
                                                   src_vserver, cg_name)

        volume_updates = []
        volume_update = []
        # Update the ZAPI client to the backend we failed over to
        active_backend_name = self.backend_name
        self._update_zapi_client(active_backend_name)
        self.failed_over = False
        self.failed_over_backend_name = active_backend_name
        for volume in volumes:
            replication_status = fields.ReplicationStatus.ENABLED
            volume_update = {
                'volume_id': volume['id'],
                'updates': {'replication_status': replication_status},
            }
            volume_updates.append(volume_update)
        LOG.debug('data_motion::_complete_failback_active_sync ended')
        return active_backend_name, volume_updates, []

    def _failover_host(self, volumes, secondary_id=None, groups=None):

        LOG.debug("data_motion::_failover_host started")

        if secondary_id == self.backend_name:
            msg = _("Cannot failover to the same host as the primary.")
            raise exception.InvalidReplicationTarget(reason=msg)

        # Added logic to handle failback from the secondary to old primary
        # This condition is needed when the DR/replication conditions are
        # restored back to normal state
        if secondary_id == "default":
            if (self.is_active_sync_configured(self.configuration)
                    and self.is_consistent_replication_enabled(
                        self.configuration)):
                replication_targets = (
                    self.get_replication_backend_names(self.configuration))
                destination_backend_name = replication_targets[0]
                return self._complete_failback_active_sync(
                    self.backend_name, destination_backend_name, volumes)
            else:
                return self._complete_failback(volumes)
        else:
            replication_targets = self.get_replication_backend_names(
                self.configuration)

            if not replication_targets:
                msg = _("No replication targets configured for backend "
                        "%s. Cannot failover.")
                raise exception.InvalidReplicationTarget(
                    reason=msg % self.host)
            if secondary_id and secondary_id not in replication_targets:
                msg = _("%(target)s is not among replication targets "
                        "configured for back end %(host)s. Cannot failover.")
                payload = {
                    'target': secondary_id,
                    'host': self.host,
                }
                raise exception.InvalidReplicationTarget(reason=msg % payload)

            flexvols = self.ssc_library.get_ssc_flexvol_names()

            try:
                if (self.is_active_sync_configured(self.configuration)
                        and self.is_consistent_replication_enabled(
                            self.configuration)):
                    # Active sync only supports single destination backend
                    destination_backend_name = (secondary_id or
                                                replication_targets[0])
                    self._complete_failover_active_sync(
                        self.backend_name,
                        destination_backend_name,
                        volumes)
                else:
                    active_backend_name, volume_updates = (
                        self._complete_failover(
                            self.backend_name, replication_targets,
                            flexvols, volumes,
                            failover_target=secondary_id))
            except na_utils.NetAppDriverException as e:
                msg = _("Could not complete failover: %s") % e
                raise exception.UnableToFailOver(reason=msg)

            # Update the ZAPI client to the backend we failed over to
            self._update_zapi_client(active_backend_name)

            self.failed_over = True
            self.failed_over_backend_name = active_backend_name

            LOG.debug("data_motion::_failover_host ended")

            return active_backend_name, volume_updates, []

    def _failover(self, context, volumes, secondary_id=None, groups=None):
        """Failover to replication target."""

        LOG.debug("data_motion::_failover started")
        LOG.debug("Secondary ID: %s", secondary_id)

        if secondary_id == self.backend_name:
            msg = _("Cannot failover to the same host as the primary.")
            raise exception.InvalidReplicationTarget(reason=msg)

        # Added logic to handle failback from the secondary to old primary
        # This condition is needed when the DR/replication conditions are
        # restored back to normal state
        if secondary_id == "default":
            if (self.is_active_sync_configured(
                    self.configuration) and
                    self.is_consistent_replication_enabled(
                        self.configuration)):
                replication_targets = (
                    self.get_replication_backend_names(
                        self.configuration))
                secondary_backend_name = replication_targets[0]
                return self._complete_failback_active_sync(
                    self.backend_name, secondary_backend_name, volumes)
            else:
                return self._complete_failback(volumes)
        else:
            replication_targets = self.get_replication_backend_names(
                self.configuration)

            if not replication_targets:
                msg = _("No replication targets configured for backend "
                        "%s. Cannot failover.")
                raise exception.InvalidReplicationTarget(
                    reason=msg % self.host)
            if secondary_id and secondary_id not in replication_targets:
                msg = _("%(target)s is not among replication targets "
                        "configured for back end %(host)s. Cannot failover.")
                payload = {
                    'target': secondary_id,
                    'host': self.host,
                }
                raise exception.InvalidReplicationTarget(reason=msg % payload)

            try:
                if (self.is_active_sync_configured(
                        self.configuration) and
                        self.is_consistent_replication_enabled(
                            self.configuration)):
                    LOG.debug(
                        "Failing over backend enabled with consistent "
                        "replication and active sync")
                    # Active sync only supports single destination backend
                    destination_backend_name = (secondary_id or
                                                replication_targets[0])
                    active_backend_name, volume_updates = (
                        self._complete_failover_active_sync(
                            self.backend_name,
                            destination_backend_name,
                            volumes))
                else:
                    flexvols = self.ssc_library.get_ssc_flexvol_names()

                    if (self.is_consistent_replication_enabled(
                            self.configuration)):
                        LOG.debug("Failing over backend enabled "
                                  "with consistent replication")
                        active_backend_name, volume_updates = (
                            self._complete_failover_consistent_rep_async(
                                self.backend_name,
                                replication_targets,
                                volumes,
                                failover_target=secondary_id))
                    else:
                        active_backend_name, volume_updates = (
                            self._complete_failover(
                                self.backend_name,
                                replication_targets,
                                flexvols,
                                volumes,
                                failover_target=secondary_id))
            except na_utils.NetAppDriverException as e:
                msg = _("Could not complete failover: %s") % e
                raise exception.UnableToFailOver(reason=msg)

            LOG.debug("data_motion::_failover ended")

            return active_backend_name, volume_updates, []

    def _failover_completed(self, context, secondary_id=None):
        """Update volume node when `failover` is completed."""
        # Update the ZAPI client to the backend we failed over to
        self._update_zapi_client(secondary_id)

        self.failed_over = True
        self.failed_over_backend_name = secondary_id

    def _get_replication_volume_online_timeout(self):
        return self.configuration.netapp_replication_volume_online_timeout

    def migrate_volume_ontap_assisted(self, volume, host, src_backend_name,
                                      src_vserver):
        """Migrate Cinder volume using ONTAP capabilities"""
        _, src_pool = volume.host.split('#')
        dest_backend, dest_pool = host["host"].split('#')
        _, dest_backend_name = dest_backend.split('@')

        # Check if migration occurs in the same backend. If so, a migration
        # between Cinder pools in the same vserver will be performed.
        if src_backend_name == dest_backend_name:
            # We should skip the operation in case source and destination pools
            # are the same.
            if src_pool == dest_pool:
                LOG.info('Skipping volume migration as source and destination '
                         'are the same.')
                return True, {}

            updates = self._migrate_volume_to_pool(
                volume, src_pool, dest_pool, src_vserver, dest_backend_name)
        else:
            if not self.using_cluster_credentials:
                LOG.info('Storage assisted volume migration across backends '
                         'requires ONTAP cluster-wide credentials. Falling '
                         'back to host assisted migration.')
                return False, {}

            dest_backend_config = config_utils.get_backend_configuration(
                dest_backend_name)
            dest_vserver = dest_backend_config.netapp_vserver
            dest_client = config_utils.get_client_for_backend(
                dest_backend_name)
            src_client = config_utils.get_client_for_backend(
                src_backend_name)

            # In case origin and destination backends are not pointing to the
            # same cluster, a host copy strategy using is required. Otherwise,
            # an intra-cluster operation can be done to complete the migration.
            src_cluster_name = src_client.get_cluster_name()
            dest_cluster_name = dest_client.get_cluster_name()
            if src_cluster_name != dest_cluster_name:
                LOG.info('Driver only supports storage assisted migration '
                         'between pools in a same cluster. Falling back to '
                         'host assisted migration.')
                return False, {}

            # if origin and destination vservers are the same, simply move
            # the cinder volume from one pool to the other.
            # Otherwise, an intra-cluster Vserver peer relationship
            # followed by a volume copy operation are required.
            # Both operations will copy data between ONTAP volumes
            # and won't finish in constant time as volume clones.
            if src_vserver == dest_vserver:
                # We should skip the operation in case source and
                # destination pools are the same
                if src_pool == dest_pool:
                    LOG.info('Skipping volume migration as source and '
                             'destination are the same.')
                    return True, {}

                updates = self._migrate_volume_to_pool(
                    volume, src_pool, dest_pool, src_vserver,
                    dest_backend_name)
            else:
                updates = self._migrate_volume_to_vserver(
                    volume, src_pool, src_vserver, dest_pool,
                    dest_backend_config.netapp_vserver,
                    dest_backend_name)

        LOG.info('Successfully migrated volume %s to host %s.',
                 volume.id, host['host'])
        return True, updates

    def _consistent_replication_precheck_for_automated_failover_policy(
            self,
            src_backend_name,
            destination_backend_names,
            storage_object_type,
            storage_object_names):

        LOG.debug("Starting pre-checks for automated "
                  "failover policy replication.")
        LOG.debug("Source backend: %s, Destination backends: %s",
                  src_backend_name, destination_backend_names)

        config = config_utils.get_backend_configuration(src_backend_name)

        # Verify if nfs protocol is selected for the storage backend
        if config.safe_get('netapp_storage_protocol') == 'nfs':
            msg = _("AutomatedFailOver policy is not supported for "
                    "NFS configured backends.")
            raise na_utils.NetAppDriverException(msg)

        # Verify if there are more than one destination backend configured
        if len(destination_backend_names) > 1:
            msg = _("There cannot be more than one destination backend "
                    "configured for automated failover policy.")
            raise na_utils.NetAppDriverException(msg)

        # Verify if Source FlexVol volumes are part of different CGs.
        # This happens when the FlexVol volumes configured previously
        # with a single CG replication
        # is not cleaned up.
        src_backend_config = (
            config_utils.get_backend_configuration(src_backend_name))
        src_vserver = src_backend_config.netapp_vserver
        src_client = (
            config_utils.get_client_for_backend(src_backend_name,
                                                vserver_name=src_vserver,
                                                force_rest=True))
        dest_backend_config = (
            config_utils.get_backend_configuration(
                destination_backend_names[0]))
        dest_vserver = dest_backend_config.netapp_vserver
        dest_client = (
            config_utils.get_client_for_backend(destination_backend_names[0],
                                                vserver_name=dest_vserver,
                                                force_rest=True))

        cg_info = []
        if storage_object_type == na_utils.StorageObjectType.VOLUME:
            cg_info = src_client.get_flexvols_cg_info(
                storage_object_names)
            LOG.debug("Consistency group info for source FlexVols: %s",
                      cg_info)

        cg_names = set()

        # Collect all unique CG names from the cg_info results
        for info in cg_info:
            cg_name = info.get('cg_name')
            if cg_name:
                cg_names.add(cg_name)

        if len(cg_names) > 1:
            msg = _("Remove the following consistency groups "
                    "before configuring consistent "
                    "replication with automated failover "
                    "policy: %s") % ', '.join(cg_names)
            raise na_utils.NetAppDriverException(msg)

        cg_name = cg_names.pop() if cg_names else None

        # Check if SnapMirror relationships exist for the given source
        # and destination consistency group paths.
        src_cg_path = na_utils.create_cg_path(cg_name)
        dest_cg_path = na_utils.create_cg_path(cg_name)
        existing_mirrors = (
            dest_client.get_snapmirrors(src_vserver, src_cg_path,
                                        dest_vserver, dest_cg_path))

        LOG.debug("Existing SnapMirror relationships for CG %s: %s",
                  cg_name, existing_mirrors)

        # If no SnapMirror relationships exist, verify that there are no
        # naming conflicts for FlexVol volumes
        # and consistency groups in the destination backend.
        # This ensures that creating new consistency groups
        # and FlexVol volumes in the destination backend
        # will not encounter conflicts.
        if not existing_mirrors:
            LOG.info("No existing SnapMirror relationships found for CG %s. "
                     "Checking for CG and FlexVol naming conflicts in"
                     " destination backend.", cg_name)
            if storage_object_type == na_utils.StorageObjectType.VOLUME:
                self._check_flexvol_name_conflicts(
                    dest_client, dest_vserver, storage_object_names,
                    destination_backend_names[0])
            self._check_cg_name_conflicts(
                dest_client, dest_vserver, cg_name,
                destination_backend_names[0])

        LOG.debug("Completed pre-checks for automated "
                  "failover policy replication.")

    def _check_flexvol_name_conflicts(self, dest_client,
                                      svm_name,
                                      flexvol_names,
                                      dest_backend_name):
        # Verify if there are FlexVol volumes with the same name
        # already present in destination
        for flexvol_name in flexvol_names:
            LOG.debug("Checking for FlexVol name conflict for "
                      "volume %s in destination backend %s.",)
            flexvol_exists = dest_client.flexvol_exists_in_svm(
                svm_name, flexvol_name)
            if flexvol_exists:
                msg = (_("FlexVol volume with name %s already "
                         "exists in destination backend %s. "
                         "Please remove it before proceeding.")
                       % (flexvol_name, dest_backend_name))
                raise na_utils.NetAppDriverException(msg)

    def _check_cg_name_conflicts(self, dest_client,
                                 svm_name, cg_name,
                                 dest_backend_name):
        # Verify if there is a CG with the same name already
        # present in destination
        LOG.debug("Checking for Consistency Group name "
                  "conflict for CG %s in destination backend %s.",
                  cg_name, dest_backend_name)
        if cg_name:
            cg_exists = dest_client.consistency_group_exists(svm_name, cg_name)
            if cg_exists:
                msg = (_("Consistency Group with name %s already "
                         "exists in destination backend %s. "
                         "Please remove it before proceeding.")
                       % (cg_name, dest_backend_name))
                raise na_utils.NetAppDriverException(msg)
