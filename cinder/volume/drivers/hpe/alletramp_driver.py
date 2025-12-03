#    (c) Copyright 2025 Hewlett Packard Enterprise Development LP
#    All Rights Reserved.
#
#    Copyright 2012 OpenStack Foundation
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
#
from oslo_log import log as logging

from cinder.common import constants
from cinder import coordination
from cinder import exception
from cinder.i18n import _
from cinder import interface
from cinder.volume import driver
from cinder.volume.drivers.san import san
from cinder.volume import volume_utils
from cinder.zonemanager import utils as fczm_utils

try:
    from . import alletramp_constants
except ImportError:
    import alletramp_constants

LOG = logging.getLogger(__name__)

FLOWKIT_IMPORT_ERROR_MESSAGE = _(
    "You must install hpe-storage-flowkit-py before using HPE "
    "Alletra MP drivers. Please execute \"pip install "
    "hpe-storage-flowkit-py\" to install the "
    "hpe-storage-flowkit-py package.")

try:
    try:
        from . import alletramp_service
    except ImportError:
        import alletramp_service
    flowkit_exceptions = alletramp_service.flowkit_exceptions
except ImportError:
    alletramp_service = None
    flowkit_exceptions = None


class HPEAlletraMPDriverBase(driver.ManageableVD,
                             driver.ManageableSnapshotsVD,
                             driver.MigrateVD,
                             driver.BaseVD):
    """OpenStack base driver to enable Alletra MP storage array.

    Version history:

    .. code-block:: none

        1.0 - Initial base driver

    """

    VERSION = "1.0"

    def __init__(self, *args, **kwargs):
        """Initialize the HPE Alletra MP driver base."""
        super(HPEAlletraMPDriverBase, self).__init__(*args, **kwargs)
        self._active_backend_id = kwargs.get('active_backend_id', None)
        self.protocol = None
        self.alletra_mp_service = None
        # Ensure 'pools' key always exists so Cinder's
        # _update_allocated_capacity (called in a finally block) never
        # crashes with KeyError: 'pools' when the driver fails to initialize.
        self._stats = {'pools': {}}

    @staticmethod
    def get_driver_options():
        """Retrieve driver configuration options from the HPE flowkit."""
        if alletramp_service is None:
            return []

        try:
            return alletramp_service.AlletraMPService.get_driver_options()
        except AttributeError as exc:
            LOG.warning("Failed to retrieve driver options: %(err)s",
                        {'err': str(exc)})
            return []

    def _login(self, timeout=None, array_id=None):
        """Login to the storage array and initialize the alletra_mp_service.

        Handles replication-enabled failover scenarios.
        """
        # return if self.alletra_mp_service is already created
        if self.alletra_mp_service:
            return

        try:
            self.alletra_mp_service = alletramp_service.AlletraMPService(
                self.configuration, self._active_backend_id)
        except exception.InvalidInput as ex:
            msg = (_("Failed to login to array. %(err)s") % {'err': ex})
            LOG.error(msg)
            raise exception.InvalidInput(reason=msg) from ex

        # If replication is enabled, we do not want to
        # raise an exception so a failover can still be executed.
        try:
            self.alletra_mp_service.do_setup(
                None, timeout=timeout, stats=self._stats, array_id=array_id)
        except flowkit_exceptions.HPEStorageException:
            if self.alletra_mp_service._replication_enabled:
                LOG.warning("The primary array is not reachable at this "
                            "time. Since replication is enabled, "
                            "listing replication targets and failing over "
                            "a volume can still be performed.")
            else:
                raise

    def _logout(self, alletra_mp_service):
        """Logout from the storage array client session."""
        # If replication is enabled and we do not have a client ID, we did not
        # login, but can still failover. There is no need to logout.
        session_mgr = alletra_mp_service.session_mgr
        replication_enabled = alletra_mp_service._replication_enabled
        if session_mgr is None and replication_enabled:
            return
        alletra_mp_service.client_logout()

    def _check_flags(self):
        """Sanity check to ensure required options are set."""
        required_flags = ['hpe3par_api_url', 'hpe3par_username',
                          'hpe3par_password', 'san_ip', 'san_login',
                          'san_password']
        alletramp_service.AlletraMPService.check_flags(
            self.configuration, required_flags)

    @volume_utils.trace
    def get_volume_stats(self, refresh=False):
        """Retrieve volume statistics from the storage backend.

        Capacity, protocol, driver version, etc.
        """
        LOG.debug("get_volume_stats: refresh: %(refresh)s",
                  {'refresh': refresh})
        if not refresh:
            return self._stats

        self._login()
        self._stats = self.alletra_mp_service.get_volume_stats(
            refresh,
            self.get_filter_function(),
            self.get_goodness_function())

        self._stats['storage_protocol'] = self.protocol
        self._stats['driver_version'] = self.VERSION
        backend_name = self.configuration.safe_get('volume_backend_name')
        self._stats['volume_backend_name'] = (backend_name or
                                              self.__class__.__name__)
        return self._stats

    def check_for_setup_error(self):
        """Verify that the HPE storage flowkit package is installed."""
        if alletramp_service is None:
            raise exception.VolumeDriverException(
                message=FLOWKIT_IMPORT_ERROR_MESSAGE)

        if alletramp_service.flowkit is None:
            msg = alletramp_service._get_flowkit_import_error_message()
            raise exception.VolumeDriverException(message=msg)

    def do_setup(self, context):
        """Perform driver setup.

        Verify installation, load configuration, initialize alletra_mp_service
        client.
        """
        self.check_for_setup_error()
        self.configuration.append_config_values(
            alletramp_service.hpe3par_opts)
        self.configuration.append_config_values(san.san_opts)
        self._check_flags()
        self._login()
        self._do_setup()

    def _do_setup(self):
        """Perform protocol-specific setup in child classes."""
        pass

    @volume_utils.trace
    def create_volume(self, volume, perform_replica=True):
        """Create a new volume on the storage array."""
        return self.alletra_mp_service.create_volume(volume)

    @volume_utils.trace
    def delete_volume(self, volume):
        """Delete a volume from the storage array."""
        return self.alletra_mp_service.delete_volume(volume)

    @volume_utils.trace
    def extend_volume(self, volume, new_size):
        """Extend an existing volume to a new size."""
        return self.alletra_mp_service.extend_volume(volume, new_size)

    @volume_utils.trace
    def create_volume_from_snapshot(self, volume, snapshot):
        """Create a new volume from an existing snapshot."""
        return self.alletra_mp_service.create_volume_from_snapshot(
            volume, snapshot)

    @volume_utils.trace
    def create_snapshot(self, snapshot):
        """Create a snapshot of a volume."""
        return self.alletra_mp_service.create_snapshot(snapshot)

    @volume_utils.trace
    def delete_snapshot(self, snapshot):
        """Delete a snapshot from the storage array."""
        return self.alletra_mp_service.delete_snapshot(snapshot)

    @volume_utils.trace
    def revert_to_snapshot(self, context, volume, snapshot):
        """Revert a volume to a previous snapshot state."""
        return self.alletra_mp_service.revert_to_snapshot(volume, snapshot)

    @volume_utils.trace
    def get_pool(self, volume):
        """Get the storage pool (CPG) for a volume."""
        return self.alletra_mp_service.get_cpg(volume)

    def create_export(self, context, volume, connector):
        """Create an export for a volume.

        Protocol-specific implementation in subclasses.
        """
        pass

    def ensure_export(self, context, volume):
        """Ensure that a volume export still exists.

        Protocol-specific implementation in subclasses.
        """
        pass

    def remove_export(self, context, volume):
        """Remove an export for a volume.

        Protocol-specific implementation in subclasses.
        """
        pass

    def initialize_connection(self, volume, connector):
        """Initialize connection between volume and host.

        Protocol-specific implementation in subclasses.
        """
        pass

    def terminate_connection(self, volume, connector, **kwargs):
        """Terminate connection between volume and host.

        Protocol-specific implementation in subclasses.
        """
        pass

    @volume_utils.trace
    def create_group(self, context, group):
        """Create a consistency group on the storage array."""
        return self.alletra_mp_service.create_group(context, group)

    @volume_utils.trace
    def update_group(self, context, group, add_volumes=None,
                     remove_volumes=None):
        """Update a consistency group by adding or removing volumes."""
        return self.alletra_mp_service.update_group(
            context, group, add_volumes, remove_volumes)

    @volume_utils.trace
    def delete_group(self, context, group, volumes):
        """Delete a consistency group and its volumes from storage."""
        return self.alletra_mp_service.delete_group(context, group, volumes)

    @volume_utils.trace
    def create_group_from_src(self, context, group, volumes,
                              group_snapshot=None, snapshots=None,
                              source_group=None, source_vols=None):
        """Create a new consistency group from a source."""
        return self.alletra_mp_service.create_group_from_src(
            context, group, volumes, group_snapshot, snapshots,
            source_group, source_vols)

    @volume_utils.trace
    def create_group_snapshot(self, context, group_snapshot, snapshots):
        """Create a snapshot of a consistency group."""
        return self.alletra_mp_service.create_group_snapshot(
            context, group_snapshot, snapshots)

    @volume_utils.trace
    def delete_group_snapshot(self, context, group_snapshot, snapshots):
        """Delete a consistency group snapshot from the storage array."""
        return self.alletra_mp_service.delete_group_snapshot(
            context, group_snapshot, snapshots)

    @volume_utils.trace
    def create_cloned_volume(self, volume, src_vref):
        """Create a clone of an existing volume."""
        return self.alletra_mp_service.create_cloned_volume(volume, src_vref)

    @volume_utils.trace
    def failover_host(self, context, volumes, secondary_id=None, groups=None):
        """Force failover to a secondary replication target."""
        alletra_mp_service = self.alletra_mp_service
        try:
            # Update the active_backend_id in the driver and return it.
            active_backend_id, volume_updates, group_update_list = (
                alletra_mp_service.failover_host(
                    context, volumes, secondary_id, groups))
            self._active_backend_id = active_backend_id
            return active_backend_id, volume_updates, group_update_list
        except flowkit_exceptions.HPEStorageException as e:
            msg = (_("Failover host failed: %(err)s") %
                   {'err': str(e)})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(msg) from e

    def failover_replication(self, context, group, volumes,
                             secondary_backend_id=None):
        """Failover replication for a group.

        :param context: the context
        :param group: the group object
        :param volumes: the list of volumes
        :param secondary_backend_id: the secondary backend id - default None
        :returns: model_update, vol_model_updates
        """
        alletra_mp_service = self.alletra_mp_service
        try:
            return alletra_mp_service.failover_replication(
                context, group, volumes, secondary_backend_id)
        except flowkit_exceptions.HPEStorageException as e:
            msg = (_("Failover replication failed: %(err)s") %
                   {'err': str(e)})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(msg) from e

    @volume_utils.trace
    def manage_existing(self, volume, existing_ref):
        """Import an existing volume on the storage array into Cinder."""
        return self.alletra_mp_service.manage_existing(volume, existing_ref)

    @volume_utils.trace
    def manage_existing_snapshot(self, snapshot, existing_ref):
        """Import an existing snapshot on the storage array into Cinder."""
        return self.alletra_mp_service.manage_existing_snapshot(
            snapshot, existing_ref)

    @volume_utils.trace
    def manage_existing_get_size(self, volume, existing_ref):
        """Get the size of an existing volume to be managed by Cinder."""
        return self.alletra_mp_service.manage_existing_get_size(
            volume, existing_ref)

    @volume_utils.trace
    def manage_existing_snapshot_get_size(self, snapshot, existing_ref):
        """Get the size of an existing snapshot to be managed by Cinder."""
        return self.alletra_mp_service.manage_existing_snapshot_get_size(
            snapshot, existing_ref)

    @volume_utils.trace
    def unmanage(self, volume):
        """Remove a volume from Cinder without deleting it from storage."""
        return self.alletra_mp_service.unmanage(volume)

    @volume_utils.trace
    def get_manageable_volumes(self, cinder_volumes, marker, limit, offset,
                               sort_keys, sort_dirs):
        """Get storage volumes that can be imported into Cinder."""
        return self.alletra_mp_service.get_manageable_volumes(
            cinder_volumes, marker, limit, offset, sort_keys, sort_dirs)

    @volume_utils.trace
    def get_manageable_snapshots(self, cinder_snapshots, marker, limit, offset,
                                 sort_keys, sort_dirs):
        """Get storage snapshots that can be imported into Cinder."""
        return self.alletra_mp_service.get_manageable_snapshots(
            cinder_snapshots, marker, limit, offset, sort_keys, sort_dirs)

    @volume_utils.trace
    def unmanage_snapshot(self, snapshot):
        """Remove a snapshot from Cinder without deleting it from storage."""
        return self.alletra_mp_service.unmanage_snapshot(snapshot)

    @volume_utils.trace
    def retype(self, context, volume, new_type, diff, host):
        """Convert the volume to be of the new type."""
        return self.alletra_mp_service.retype(volume, new_type, diff, host)

    @volume_utils.trace
    def migrate_volume(self, context, volume, host):
        """Migrate a volume to a different host or backend."""
        if volume['status'] == 'in-use':
            protocol = host['capabilities']['storage_protocol']
            if protocol != self.protocol:
                LOG.warning("Alletra MP %(protocol)s driver cannot migrate "
                            "in-use volume to a host with "
                            "storage_protocol=%(storage_protocol)s",
                            {'protocol': self.protocol,
                             'storage_protocol': protocol})
                return False, None

        return self.alletra_mp_service.migrate_volume(volume, host)

    @volume_utils.trace
    def update_migrated_volume(self, context, volume, new_volume,
                               original_volume_status):
        """Update the name of the migrated volume to it's new ID."""
        return self.alletra_mp_service.update_migrated_volume(
            context, volume, new_volume, original_volume_status)

    @volume_utils.trace
    def _init_vendor_properties(self):
        """Initialize and return vendor-specific properties.

        This method creates a dictionary of vendor unique properties
        and returns both created dictionary and vendor name.
        Returned vendor name is used to check for name of vendor
        unique properties.

        - Vendor name shouldn't include colon(:) because of the separator
          and it is automatically replaced by underscore(_).
          ex. abc:d -> abc_d
        - Vendor prefix is equal to vendor name.
          ex. abcd
        - Vendor unique properties must start with vendor prefix + ':'.
          ex. abcd:maxIOPS

        Each backend driver needs to override this method to expose
        its own properties using _set_property() like this:

        self._set_property(
            properties,
            "vendorPrefix:specific_property",
            "Title of property",
            _("Description of property"),
            "type")

        : return dictionary of vendor unique properties
        : return vendor name

        prefix: HPE:AlletraMP --> HPE_AlletraMP
        """

        properties = {}

        self._set_property(
            properties,
            "HPE:AlletraMP:hpe3par:snap_cpg",
            "Snap CPG Extra-specs.",
            _("Specifies the Snap CPG for a volume type. It overrides the "
              "hpe3par_cpg_snap setting. Defaults to the hpe3par_cpg_snap "
              "setting in the cinder.conf file. If hpe3par_cpg_snap is not "
              "set, it defaults to the hpe3par_cpg setting."),
            "string")

        self._set_property(
            properties,
            "HPE:AlletraMP:hpe3par:persona",
            "Host Persona Extra-specs.",
            _("Specifies the host persona property for a volume type. "
              "If not specified, it defaults to 2 - Generic-ALUA."),
            "string",
            enum=alletramp_constants.valid_persona_values,
            default="2 - Generic-ALUA")

        self._set_property(
            properties,
            "HPE:AlletraMP:hpe3par:vvs",
            "Virtual Volume Set Extra-specs.",
            _("The virtual volume set name that has been set up by the "
              "administrator that would have predefined QoS rules "
              "associated with it. If you specify extra_specs "
              "hpe3par:vvs, the qos_specs minIOPS, maxIOPS, minBWS, "
              "and maxBWS settings are ignored."),
            "string")

        self._set_property(
            properties,
            "HPE:AlletraMP:hpe3par:flash_cache",
            "Flash cache Extra-specs.",
            _("Enables Flash cache setting for a volume type."),
            "boolean",
            default=False)

        self._set_property(
            properties,
            "HPE:AlletraMP:hpe3par:provisioning",
            "Storage Provisioning Extra-specs.",
            _("Specifies the provisioning for a volume type."),
            "string",
            enum=alletramp_constants.valid_prov_values,
            default="thin")

        self._set_property(
            properties,
            "HPE:AlletraMP:hpe3par:compression",
            "Storage Provisioning Extra-specs.",
            _("Enables compression for a volume type. "
              "Volume size must have > 16 GB to enable "
              "compression on volume. "),
            "boolean",
            default=False)

        self._set_property(
            properties,
            "HPE:AlletraMP:replication_enabled",
            "Volume Replication Extra-specs.",
            _("The valid value is: <is> True "
              "If True, the volume is to be replicated, if supported, "
              "by the backend driver. If the option is not specified or "
              "false, then replication is not enabled. This option is "
              "required to enable replication."),
            "string",
            enum=["<is> True"],
            default=False)

        self._set_property(
            properties,
            "HPE:AlletraMP:replication:mode",
            "Replication Mode Extra-specs.",
            _("Sets the replication mode for AlletraMP."),
            "string",
            enum=["sync", "periodic"],
            default="periodic")

        self._set_property(
            properties,
            "HPE:AlletraMP:replication:sync_period",
            "Sync Period for Volume Replication Extra-specs.",
            _("Sets the time interval for synchronization. "
              "Only needed if replication:mode is periodic."),
            "integer",
            default=900)

        self._set_property(
            properties,
            "HPE:AlletraMP:replication:policy",
            "Replication Policy for Alletra MP.",
            _("Sets the replication policy for Alletra MP. "
              "Currently, only the 'active-active' policy is supported."),
            "string",
            default="active-active")

        self._set_property(
            properties,
            "HPE:AlletraMP:replication:retention_count",
            "Retention Count for Replication Extra-specs.",
            _("Sets the number of snapshots that will be  "
              "saved on the primary array."),
            "integer",
            default=5)

        self._set_property(
            properties,
            "HPE:AlletraMP:replication:remote_retention_count",
            "Remote Retention Count for Replication Extra-specs.",
            _("Sets the number of snapshots that will be  "
              "saved on the secondary array."),
            "integer",
            default=5)

        # ###### QoS Settings ###### #

        self._set_property(
            properties,
            "HPE:AlletraMP:minIOPS",
            "Minimum IOPS QoS.",
            _("Sets the QoS, I/O issue count minimum goal. "
              "If not specified, there is no limit on I/O issue count."),
            "integer")

        self._set_property(
            properties,
            "HPE:AlletraMP:maxIOPS",
            "Maximum IOPS QoS.",
            _("Sets the QoS, I/O issue count rate limit. "
              "If not specified, there is no limit on I/O issue count."),
            "integer")

        self._set_property(
            properties,
            "HPE:AlletraMP:minBWS",
            "Minimum Bandwidth QoS.",
            _("Sets the QoS, I/O issue bandwidth minimum goal. "
              "If not specified, there is no limit on "
              "I/O issue bandwidth rate."),
            "integer")

        self._set_property(
            properties,
            "HPE:AlletraMP:maxBWS",
            "Maximum Bandwidth QoS.",
            _("Sets the QoS, I/O issue bandwidth rate limit. "
              "If not specified, there is no limit on I/O issue "
              "bandwidth rate."),
            "integer")

        self._set_property(
            properties,
            "HPE:AlletraMP:latency",
            "Latency QoS.",
            _("Sets the latency goal in milliseconds."),
            "integer")

        self._set_property(
            properties,
            "HPE:AlletraMP:priority",
            "Priority QoS.",
            _("Sets the priority of the QoS rule over other rules."),
            "string",
            enum=["low", "normal", "high"],
            default="normal")

        return properties, 'HPE:AlletraMP'

    def _is_multiattach(self, volume, hostname):
        """Determine whether VLUN cleanup should be skipped."""
        if not volume.multiattach:
            return False

        # volume.multiattach is True
        attachment_list = volume.volume_attachment
        LOG.debug("Volume attachment list: %(atl)s",
                  {'atl': attachment_list})

        try:
            attachment_list = attachment_list.objects
        except AttributeError:
            pass

        if attachment_list is None or len(attachment_list) <= 1:
            # volume is attached to only one instance
            # i.e last volume attachment
            return False
        else:
            # volume is attached to two or more instances
            #
            # There are two possibilities: the instances can reside:
            # [1] either on same host.
            # [2] or on different hosts.
            #
            # case [1]:
            # In such case, vlun is not deleted now
            # i.e skip remainder of terminate volume connection.
            #
            # case [2]:
            # In such case, vlun of that host on 3par array should
            # be deleted now. Otherwise, it remains as stale entry on
            # 3par array; which later leads to error during volume
            # deletion.

            same_host = False
            num_hosts = len(attachment_list)
            all_hostnames = []
            all_hostnames.append(hostname)

            count = 0
            for i in range(num_hosts):
                hostname_i = str(attachment_list[i].attached_host)
                if hostname == hostname_i:
                    # current host
                    count = count + 1
                    if count > 1:
                        # volume attached to multiple instances on
                        # current host
                        same_host = True
                else:
                    # different host
                    all_hostnames.append(hostname_i)

            if same_host:
                LOG.info("Volume %(volume)s is attached to multiple "
                         "instances on same host %(host_name)s, "
                         "skip terminate volume connection",
                         {'volume': volume.name,
                          'host_name': (volume.host or '').split('@')[0]})
                return True
            else:
                hostnames = ",".join(all_hostnames)
                LOG.info("Volume %(volume)s is attached to instances "
                         "on multiple hosts %(hostnames)s. Proceed with "
                         "deletion of vlun on this host.",
                         {'volume': volume.name, 'hostnames': hostnames})
                return False


@interface.volumedriver
class HPEAlletraMPFCDriver(HPEAlletraMPDriverBase):
    """OpenStack FC driver to enable Alletra MP storage array.

    Version history:

    .. code-block:: none

        1.0   - Initial driver
    """

    VERSION = "1.0"

    # The name of the CI wiki page.
    CI_WIKI_NAME = "HPE_AlletraMP_FC_CI"

    def __init__(self, *args, **kwargs):
        """Initialize the HPE Alletra MP Fibre Channel driver."""
        super(HPEAlletraMPFCDriver, self).__init__(*args, **kwargs)
        self.lookup_service = fczm_utils.create_lookup_service()
        self.protocol = constants.FC

    @volume_utils.trace
    @coordination.synchronized('3par-{volume.id}')
    def initialize_connection(self, volume, connector):
        """Assigns the volume to a server.

        Assign any created volume to a compute node/host so that it can be
        used from that host.

        The  driver returns a driver_volume_type of 'fibre_channel'.
        The target_wwn can be a single entry or a list of wwns that
        correspond to the list of remote wwn(s) that will export the volume.
        Example return values:

            {
                'driver_volume_type': 'fibre_channel'
                'data': {
                    'encrypted': False,
                    'target_discovered': True,
                    'target_lun': 1,
                    'target_wwn': '1234567890123',
                }
            }

            or

             {
                'driver_volume_type': 'fibre_channel'
                'data': {
                    'encrypted': False,
                    'target_discovered': True,
                    'target_lun': 1,
                    'target_wwn': ['1234567890123', '0987654321321'],
                }
            }


        Steps to export a volume on storage
          * Create a host on the storage with the target wwn
          * Create a VLUN for that HOST with the volume we want to export.
        """
        LOG.debug("volume id: %(id)s, connector: %(conn)s",
                  {'id': volume['id'], 'conn': connector})
        multipath = connector.get('multipath')
        LOG.debug("multipath: %(multipath)s", {'multipath': multipath})

        alletra_mp_service = self.alletra_mp_service

        try:
            connection_data = alletra_mp_service.initialize_fc_connection(
                volume, connector, self.lookup_service, self.configuration)
        except flowkit_exceptions.HPEStorageException as e:
            msg = (_("Failed to initialize connection for volume: "
                     "%(err)s") % {'err': str(e)})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(msg)

        info = {'driver_volume_type': 'fibre_channel',
                'data': connection_data}

        encryption_key_id = volume.get('encryption_key_id')
        info['data']['encrypted'] = encryption_key_id is not None
        fczm_utils.add_fc_zone(info)

        return info

    @volume_utils.trace
    @coordination.synchronized('3par-{volume.id}')
    def terminate_connection(self, volume, connector, **kwargs):
        """Driver entry point to detach a volume from an instance."""
        LOG.debug("volume id: %(id)s, connector: %(conn)s",
                  {'id': volume['id'], 'conn': connector})
        alletra_mp_service = self.alletra_mp_service
        try:
            zone_data = alletra_mp_service.terminate_fc_connection(
                volume, connector, self.lookup_service,
                self.configuration, self._is_multiattach)

            info = {'driver_volume_type': 'fibre_channel',
                    'data': {}}

            if not zone_data:
                return info

            for zone_entry in zone_data:
                zone_info = {'driver_volume_type': 'fibre_channel',
                             'data': zone_entry}
                fczm_utils.remove_fc_zone(zone_info)

            merged_target_wwns = []
            merged_init_targ_map = {}
            for zone_entry in zone_data:
                merged_target_wwns.extend(zone_entry['target_wwn'])
                merged_init_targ_map = alletra_mp_service.merge_dicts(
                    merged_init_targ_map,
                    zone_entry['initiator_target_map'])

            info['data'] = {'target_wwn': merged_target_wwns,
                            'initiator_target_map': merged_init_targ_map}

            return info

        except flowkit_exceptions.HPEStorageException as e:
            msg = (_("Terminate connection failed: %(err)s") %
                   {'err': str(e)})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(msg)


@interface.volumedriver
class HPEAlletraMPISCSIDriver(HPEAlletraMPDriverBase):
    """OpenStack iSCSI driver to enable Alletra MP storage array.

    Version history:

    .. code-block:: none

        1.0   - Initial driver
    """

    VERSION = "1.0"

    # The name of the CI wiki page.
    CI_WIKI_NAME = "HPE_AlletraMP_iSCSI_CI"

    def __init__(self, *args, **kwargs):
        """Initialize the HPE Alletra MP iSCSI driver."""
        super(HPEAlletraMPISCSIDriver, self).__init__(*args, **kwargs)
        self.protocol = constants.ISCSI

    def _do_setup(self):
        """Perform iSCSI-specific setup."""
        self.iscsi_ips = {}

        try:
            self.initialize_iscsi_ports(self.alletra_mp_service)
        except flowkit_exceptions.HPEStorageException as e:
            msg = (_("Initialize iscsi ips and ports failed: %(err)s") %
                   {'err': str(e)})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(msg)

    def initialize_iscsi_ports(self, alletra_mp_service,
                               remote_target=None, remote_client=None):
        """Map iSCSI IP addresses to ports, IQNs, and NSPs."""
        if remote_target:
            backend_conf = remote_target
        else:
            backend_conf = alletra_mp_service._client_conf

        iscsi_ip_list = alletra_mp_service.get_configured_iscsi_ip_map(
            backend_conf, remote_client)

        if remote_target:
            self.iscsi_ips[remote_target['hpe3par_api_url']] = iscsi_ip_list
        else:
            self.iscsi_ips[alletra_mp_service._client_conf
                           ['hpe3par_api_url']] = (iscsi_ip_list)

    def _initialize_iscsi_multipath_connection(
            self,
            volume,
            connector,
            alletra_mp_service,
            host,
            iscsi_ips,
            username,
            password,
            cpg):
        """Initialize multipath iSCSI connection with optional replication."""
        try:
            connection_targets = (
                alletra_mp_service.initialize_iscsi_multipath_targets(
                    volume, connector, host, iscsi_ips, cpg))
        except flowkit_exceptions.HPEStorageException as e:
            msg = (_("Failed to initialize multipath iSCSI connection: "
                     "%(err)s") %
                   {'err': str(e)})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(msg)

        info = {
            'driver_volume_type': 'iscsi',
            'data': {
                'target_portals': connection_targets['target_portals'],
                'target_iqns': connection_targets['target_iqns'],
                'target_luns': connection_targets['target_luns'],
                'target_discovered': True}}

        if alletra_mp_service._client_conf['hpe3par_iscsi_chap_enabled']:
            info['data']['auth_method'] = 'CHAP'
            info['data']['auth_username'] = username
            info['data']['auth_password'] = password

        return info

    def _initialize_iscsi_single_path_connection(
            self,
            volume,
            alletra_mp_service,
            host,
            iscsi_ips,
            username,
            password,
            connector=None,
            cpg=None):
        """Initialize single path iSCSI connection."""
        try:
            single_path_target = (
                alletra_mp_service.initialize_iscsi_single_path_target(
                    volume, host, iscsi_ips, connector=connector, cpg=cpg))
        except flowkit_exceptions.HPEStorageException as e:
            msg = (_("Failed to initialize single path iSCSI connection: "
                     "%(err)s") % {'err': str(e)})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(msg)

        info = {'driver_volume_type': 'iscsi',
                'data': {'target_portal': single_path_target['target_portal'],
                         'target_iqn': single_path_target['target_iqn'],
                         'target_lun': single_path_target['target_lun'],
                         'target_discovered': True
                         }
                }

        if alletra_mp_service._client_conf['hpe3par_iscsi_chap_enabled']:
            info['data']['auth_method'] = 'CHAP'
            info['data']['auth_username'] = username
            info['data']['auth_password'] = password

        return info

    @volume_utils.trace
    @coordination.synchronized('3par-{volume.id}')
    def initialize_connection(self, volume, connector):
        """Assigns the volume to a server.

        Assign any created volume to a compute node/host so that it can be
        used from that host.

        This driver returns a driver_volume_type of 'iscsi'.
        The format of the driver data is defined in _get_iscsi_properties.
        Example return value:

        .. code-block:: default

            {
                'driver_volume_type': 'iscsi',
                'data': {
                    'encrypted': False,
                    'target_discovered': True,
                    'target_iqn': 'iqn.2010-10.org.openstack:volume-00000001',
                    'target_portal': '127.0.0.1:3260',
                    'volume_id': 1,
                }
            }

        Steps to export a volume on storage
          * Get the iSCSI iqn
          * Create a host on the storage
          * create vlun on the storage
        """
        LOG.debug("volume id: %(id)s, connector: %(conn)s",
                  {'id': volume['id'], 'conn': connector})
        multipath = connector.get('multipath')
        LOG.debug("multipath: %(multipath)s", {'multipath': multipath})
        alletra_mp_service = self.alletra_mp_service
        api_url = alletra_mp_service._client_conf['hpe3par_api_url']
        failed_over = volume.get('replication_status') == 'failed-over'

        # Step 1: Initialize iSCSI ports if needed (for failed-over volumes)
        if failed_over and api_url not in self.iscsi_ips:
            try:
                self.initialize_iscsi_ports(alletra_mp_service)
            except flowkit_exceptions.HPEStorageException as e:
                msg = (_("Failed to initialize iSCSI ports after failover: "
                         "%(err)s") % {'err': str(e)})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(msg)

        # Grab the correct iSCSI ports
        iscsi_ips = self.iscsi_ips[alletra_mp_service._client_conf
                                   ['hpe3par_api_url']]

        # Step 2: Create iSCSI host
        try:
            host, username, password, cpg = (
                alletra_mp_service._create_host_iscsi(
                    self.configuration, volume, connector))
        except flowkit_exceptions.HPEStorageException as e:
            msg = (_("Failed to create iSCSI host: %(err)s") %
                   {'err': str(e)})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(msg)

        # Step 3: Initialize connection based on multipath setting
        if multipath:
            info = self._initialize_iscsi_multipath_connection(
                volume, connector, alletra_mp_service, host, iscsi_ips,
                username, password, cpg)
        else:
            info = self._initialize_iscsi_single_path_connection(
                volume, alletra_mp_service, host, iscsi_ips, username,
                password, connector, cpg)

        encryption_key_id = volume.get('encryption_key_id', None)
        info['data']['encrypted'] = encryption_key_id is not None

        return info

    @volume_utils.trace
    @coordination.synchronized('3par-{volume.id}')
    def terminate_connection(self, volume, connector, **kwargs):
        """Driver entry point to detach a volume from an instance."""
        LOG.debug("volume id: %(id)s, connector: %(conn)s",
                  {'id': volume['id'], 'conn': connector})
        alletra_mp_service = self.alletra_mp_service
        try:
            alletra_mp_service.terminate_iscsi_connection(volume, connector)
        except flowkit_exceptions.HPEStorageException as e:
            msg = (_("Terminate connection failed: %(err)s") %
                   {'err': str(e)})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(msg)

    def _do_export(self, alletra_mp_service, volume, connector):
        """Generate CHAP credentials and update volume metadata."""
        return alletra_mp_service.create_iscsi_export(volume, connector)

    @volume_utils.trace
    def create_export(self, context, volume, connector):
        """Create an iSCSI export by generating CHAP credentials."""
        return self._do_export(self.alletra_mp_service, volume, connector)

    @volume_utils.trace
    def ensure_export(self, context, volume):
        """Ensure the volume exists and retrieve CHAP credentials."""
        return self.alletra_mp_service.ensure_iscsi_export(volume)


@interface.volumedriver
class HPEAlletraMPNVMETCPDriver(HPEAlletraMPDriverBase):
    """OpenStack NVMe TCP driver to enable Alletra MP storage array.

    Version history:

    .. code-block:: none

        1.0   - Initial driver
    """

    VERSION = "1.0"

    # The name of the CI wiki page.
    CI_WIKI_NAME = "HPE_AlletraMP_NVMeTCP_CI"

    def __init__(self, *args, **kwargs):
        """Initialize the HPE Alletra MP NVMe-oF TCP driver."""
        super(HPEAlletraMPNVMETCPDriver, self).__init__(*args, **kwargs)
        self.protocol = constants.NVMEOF_TCP

    def _do_setup(self):
        """Perform NVMe-oF TCP-specific setup."""
        self.nvme_ips = {}
        try:
            self.initialize_nvme_ips_and_ports(self.alletra_mp_service)
        except Exception as e:
            msg = (_("Initialize nvme ips and ports failed: %(err)s") %
                   {'err': str(e)})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(msg)

    def initialize_nvme_ips_and_ports(self, alletra_mp_service):
        """Map NVMe-oF TCP IP addresses to ports and NSPs."""
        nvme_ip_list, _nvme_port_list = (
            alletra_mp_service.get_configured_nvme_ip_map())
        storage_system_id = alletra_mp_service._client_conf['hpe3par_api_url']
        self.nvme_ips[storage_system_id] = nvme_ip_list

    @volume_utils.trace
    @coordination.synchronized('3par-{volume.id}')
    def initialize_connection(self, volume, connector):
        """Assigns the volume to a server.

        Steps to export a volume on array:
          * Ensure that host is present on array
          * Create a VLUN with the volume we want to export.
        """
        LOG.debug("volume id: %(id)s, connector: %(conn)s",
                  {'id': volume['id'], 'conn': connector})
        alletra_mp_service = self.alletra_mp_service

        try:
            storage_system_id = (
                alletra_mp_service._client_conf['hpe3par_api_url'])
            host_nqn = connector.get('nqn')
            hostname = connector.get('host')

            if not host_nqn or not hostname:
                msg = _("Connector is missing required NVMe fields: "
                        "'nqn' and/or 'host'.")
                raise exception.InvalidInput(reason=msg)

            if (volume.get('replication_status') == 'failed-over' and
               storage_system_id not in self.nvme_ips):
                self.initialize_nvme_ips_and_ports(alletra_mp_service)

            nvme_ips = self.nvme_ips[storage_system_id]

            try:
                connection_data = (
                    alletra_mp_service.initialize_nvme_connection(
                        volume, connector, nvme_ips))
            except LookupError:
                LOG.error("Host with nqn %(nqn)s not found. "
                          "Please create new host with name %(name)s and "
                          "nqn %(nqn)s",
                          {'name': hostname, 'nqn': host_nqn})
                msg = (_("Host not found with nqn: %(nqn)s") %
                       {'nqn': host_nqn})
                raise exception.VolumeBackendAPIException(msg)

            info = {'driver_volume_type': 'nvmeof',
                    'data': connection_data}
            LOG.debug("info: %(info)s", {'info': info})
            return info
        except flowkit_exceptions.HPEStorageException as e:
            msg = (_("Initialize connection failed: %(err)s") %
                   {'err': str(e)})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(msg)

    @volume_utils.trace
    @coordination.synchronized('3par-{volume.id}')
    def terminate_connection(self, volume, connector, **kwargs):
        """Driver entry point to detach a volume from an instance."""
        LOG.debug("volume id: %(id)s, connector: %(conn)s",
                  {'id': volume['id'], 'conn': connector})

        alletra_mp_service = self.alletra_mp_service

        def is_multiattach(_vol_name, hostname):
            return self._is_multiattach(volume, hostname)

        try:
            alletra_mp_service.terminate_nvme_connection(
                volume,
                connector,
                is_multiattach)
        except flowkit_exceptions.HPEStorageException as e:
            msg = (_("Terminate connection failed: %(err)s") %
                   {'err': str(e)})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(msg)
