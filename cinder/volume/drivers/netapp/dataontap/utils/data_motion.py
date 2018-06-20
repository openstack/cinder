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
from oslo_utils import excutils

from cinder import exception
from cinder.i18n import _
from cinder.objects import fields
from cinder import utils
from cinder.volume.drivers.netapp.dataontap.client import api as netapp_api
from cinder.volume.drivers.netapp.dataontap.utils import utils as config_utils
from cinder.volume import utils as volume_utils

LOG = log.getLogger(__name__)
ENTRY_DOES_NOT_EXIST = "(entry doesn't exist)"
QUIESCE_RETRY_INTERVAL = 5


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

    def create_snapmirror(self, src_backend_name, dest_backend_name,
                          src_flexvol_name, dest_flexvol_name):
        """Set up a SnapMirror relationship b/w two FlexVols (cinder pools)

        1. Create SnapMirror relationship
        2. Initialize data transfer asynchronously

        If a SnapMirror relationship already exists and is broken off or
        quiesced, resume and re-sync the mirror.
        """
        dest_backend_config = config_utils.get_backend_configuration(
            dest_backend_name)
        dest_vserver = dest_backend_config.netapp_vserver
        dest_client = config_utils.get_client_for_backend(
            dest_backend_name, vserver_name=dest_vserver)

        source_backend_config = config_utils.get_backend_configuration(
            src_backend_name)
        src_vserver = source_backend_config.netapp_vserver

        # 1. Create destination 'dp' FlexVol if it doesn't exist
        if not dest_client.flexvol_exists(dest_flexvol_name):
            self.create_destination_flexvol(src_backend_name,
                                            dest_backend_name,
                                            src_flexvol_name,
                                            dest_flexvol_name)

        # 2. Check if SnapMirror relationship exists
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
            # TODO(gouthamr): Change the schedule from hourly to a config value
            msg = ("Creating a SnapMirror relationship between "
                   "%(src_vserver)s:%(src_volume)s and %(dest_vserver)s:"
                   "%(dest_volume)s.")
            LOG.debug(msg, msg_payload)

            dest_client.create_snapmirror(src_vserver,
                                          src_flexvol_name,
                                          dest_vserver,
                                          dest_flexvol_name,
                                          schedule='hourly')

            msg = ("Initializing SnapMirror transfers between "
                   "%(src_vserver)s:%(src_volume)s and %(dest_vserver)s:"
                   "%(dest_volume)s.")
            LOG.debug(msg, msg_payload)

            # Initialize async transfer of the initial data
            dest_client.initialize_snapmirror(src_vserver,
                                              src_flexvol_name,
                                              dest_vserver,
                                              dest_flexvol_name)

        # 4. Try to repair SnapMirror if existing
        else:
            snapmirror = existing_mirrors[0]
            if snapmirror.get('mirror-state') != 'snapmirrored':
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
                    LOG.exception("Could not re-sync SnapMirror.")

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

        @utils.retry(exception.NetAppDriverException,
                     interval=QUIESCE_RETRY_INTERVAL,
                     retries=retries, backoff_rate=1)
        def wait_for_quiesced():
            snapmirror = dest_client.get_snapmirrors(
                src_vserver, src_flexvol_name, dest_vserver,
                dest_flexvol_name,
                desired_attributes=['relationship-status', 'mirror-state'])[0]
            if snapmirror.get('relationship-status') != 'quiesced':
                msg = _("SnapMirror relationship is not quiesced.")
                raise exception.NetAppDriverException(reason=msg)

        try:
            wait_for_quiesced()
        except exception.NetAppDriverException:
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
                                   src_flexvol_name, dest_flexvol_name):
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
            raise exception.NetAppDriverException(msg % src_flexvol_name)
        provisioning_options.pop('volume_type', None)

        source_aggregate = provisioning_options.pop('aggregate')
        aggregate_map = self._get_replication_aggregate_map(
            src_backend_name, dest_backend_name)

        if not aggregate_map.get(source_aggregate):
            msg = _("Unable to find configuration matching the source "
                    "aggregate (%s) and the destination aggregate. Option "
                    "netapp_replication_aggregate_map may be incorrect.")
            raise exception.NetAppDriverException(
                message=msg % source_aggregate)

        destination_aggregate = aggregate_map[source_aggregate]

        # NOTE(gouthamr): The volume is intentionally created as a Data
        # Protection volume; junction-path will be added on breaking
        # the mirror.
        provisioning_options['volume_type'] = 'dp'
        dest_client.create_flexvol(dest_flexvol_name,
                                   destination_aggregate,
                                   size,
                                   **provisioning_options)

    def ensure_snapmirrors(self, config, src_backend_name, src_flexvol_names):
        """Ensure all the SnapMirrors needed for whole-backend replication."""
        backend_names = self.get_replication_backend_names(config)
        for dest_backend_name in backend_names:
            for src_flexvol_name in src_flexvol_names:

                dest_flexvol_name = src_flexvol_name

                self.create_snapmirror(src_backend_name,
                                       dest_backend_name,
                                       src_flexvol_name,
                                       dest_flexvol_name)

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
                    msg = _("Unable to break SnapMirror between FlexVol "
                            "%(src)s and Flexvol %(dest)s. Associated volumes "
                            "will have their replication state set to error.")
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

    def _filter_and_sort_mirrors(self, mirrors, flexvols):
        """Return mirrors reverse-sorted by lag time.

        The 'slowest' mirror determines the best update that occurred on a
        given replication target.
        """
        filtered_mirrors = [x for x in mirrors
                            if x.get('destination-volume')in flexvols]
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
            raise exception.NetAppDriverException(msg)

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

    def _failover_host(self, volumes, secondary_id=None, groups=None):

        if secondary_id == self.backend_name:
            msg = _("Cannot failover to the same host as the primary.")
            raise exception.InvalidReplicationTarget(reason=msg)

        replication_targets = self.get_replication_backend_names(
            self.configuration)

        if not replication_targets:
            msg = _("No replication targets configured for backend "
                    "%s. Cannot failover.")
            raise exception.InvalidReplicationTarget(reason=msg % self.host)
        elif secondary_id and secondary_id not in replication_targets:
            msg = _("%(target)s is not among replication targets configured "
                    "for back end %(host)s. Cannot failover.")
            payload = {
                'target': secondary_id,
                'host': self.host,
            }
            raise exception.InvalidReplicationTarget(reason=msg % payload)

        flexvols = self.ssc_library.get_ssc_flexvol_names()

        try:
            active_backend_name, volume_updates = self._complete_failover(
                self.backend_name, replication_targets, flexvols, volumes,
                failover_target=secondary_id)
        except exception.NetAppDriverException as e:
            msg = _("Could not complete failover: %s") % e
            raise exception.UnableToFailOver(reason=msg)

        # Update the ZAPI client to the backend we failed over to
        self._update_zapi_client(active_backend_name)

        self.failed_over = True
        self.failed_over_backend_name = active_backend_name

        return active_backend_name, volume_updates, []
