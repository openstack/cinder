#    (c) Copyright 2013-2015 Hewlett Packard Enterprise Development LP
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
"""
Base class for HPE Storage Drivers.
This driver requires 3.1.3 or later firmware on the 3PAR array, using
the 4.x version of the hpe3parclient.

You will need to install the python hpe3parclient.
sudo pip install --upgrade "hpe3parclient>=4.0"

"""

try:
    from hpe3parclient import exceptions as hpeexceptions
except ImportError:
    hpeexceptions = None

from oslo_log import log as logging

from cinder import exception
from cinder.i18n import _
from cinder import utils
from cinder.volume import driver
from cinder.volume.drivers.hpe import hpe_3par_common as hpecommon
from cinder.volume.drivers.san import san

LOG = logging.getLogger(__name__)


class HPE3PARDriverBase(driver.ManageableVD,
                        driver.ManageableSnapshotsVD,
                        driver.MigrateVD,
                        driver.BaseVD):
    """OpenStack base driver to enable 3PAR storage array.

    Version history:

    .. code-block:: none

        1.0.0 - Initial base driver
        1.0.1 - Adds consistency group capability in generic volume groups.
        1.0.2 - Adds capability.
        1.0.3 - Added Tiramisu feature on 3PAR.
        1.0.4 - Fixed Volume migration for "in-use" volume. bug #1744021
        1.0.5 - Set proper backend on subsequent operation, after group
                failover. bug #1773069

    """

    VERSION = "1.0.5"

    def __init__(self, *args, **kwargs):
        super(HPE3PARDriverBase, self).__init__(*args, **kwargs)
        self._active_backend_id = kwargs.get('active_backend_id', None)
        self.configuration.append_config_values(hpecommon.hpe3par_opts)
        self.configuration.append_config_values(san.san_opts)
        self.protocol = None

    @staticmethod
    def get_driver_options():
        return hpecommon.HPE3PARCommon.get_driver_options()

    def _init_common(self):
        return hpecommon.HPE3PARCommon(self.configuration,
                                       self._active_backend_id)

    def _login(self, timeout=None, array_id=None):
        common = self._init_common()
        # If replication is enabled and we cannot login, we do not want to
        # raise an exception so a failover can still be executed.
        try:
            common.do_setup(None, timeout=timeout, stats=self._stats,
                            array_id=array_id)
            common.client_login()
        except Exception:
            if common._replication_enabled:
                LOG.warning("The primary array is not reachable at this "
                            "time. Since replication is enabled, "
                            "listing replication targets and failing over "
                            "a volume can still be performed.")
            else:
                raise
        return common

    def _logout(self, common):
        # If replication is enabled and we do not have a client ID, we did not
        # login, but can still failover. There is no need to logout.
        if common.client is None and common._replication_enabled:
            return
        common.client_logout()

    def _check_flags(self, common):
        """Sanity check to ensure we have required options set."""
        required_flags = ['hpe3par_api_url', 'hpe3par_username',
                          'hpe3par_password', 'san_ip', 'san_login',
                          'san_password']
        common.check_flags(self.configuration, required_flags)

    def get_volume_replication_driver_data(self, volume):
        if (volume.get("group_id") and volume.get("replication_status") and
           volume.get("replication_status") == "failed-over"):
            return int(volume.get("replication_driver_data"))
        return None

    @utils.trace
    def get_volume_stats(self, refresh=False):
        # NOTE(geguileo): We don't need to login to the backed if we are not
        # going to refresh the stats, furthermore if we login, then we'll
        # return an empty dict, because the _login method calls calls
        # _init_common which returns a new HPE3PARCommon instance each time,
        # so it won't have any cached values.
        if not refresh:
            return self._stats

        common = self._login()
        try:
            self._stats = common.get_volume_stats(
                refresh,
                self.get_filter_function(),
                self.get_goodness_function())
            self._stats['storage_protocol'] = self.protocol
            self._stats['driver_version'] = self.VERSION
            backend_name = self.configuration.safe_get('volume_backend_name')
            self._stats['volume_backend_name'] = (backend_name or
                                                  self.__class__.__name__)
            return self._stats
        finally:
            self._logout(common)

    def check_for_setup_error(self):
        """Setup errors are already checked for in do_setup so return pass."""
        pass

    @utils.trace
    def create_volume(self, volume):
        common = self._login()
        try:
            return common.create_volume(volume)
        finally:
            self._logout(common)

    @utils.trace
    def create_cloned_volume(self, volume, src_vref):
        """Clone an existing volume."""
        common = self._login()
        try:
            return common.create_cloned_volume(volume, src_vref)
        finally:
            self._logout(common)

    @utils.trace
    def delete_volume(self, volume):
        common = self._login()
        try:
            common.delete_volume(volume)
        finally:
            self._logout(common)

    @utils.trace
    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot.

        TODO: support using the size from the user.
        """
        common = self._login()
        try:
            return common.create_volume_from_snapshot(volume, snapshot)
        finally:
            self._logout(common)

    @utils.trace
    def create_snapshot(self, snapshot):
        common = self._login()
        try:
            common.create_snapshot(snapshot)
        finally:
            self._logout(common)

    @utils.trace
    def delete_snapshot(self, snapshot):
        common = self._login()
        try:
            common.delete_snapshot(snapshot)
        finally:
            self._logout(common)

    @utils.trace
    def extend_volume(self, volume, new_size):
        common = self._login()
        try:
            common.extend_volume(volume, new_size)
        finally:
            self._logout(common)

    @utils.trace
    def create_group(self, context, group):
        common = self._login()
        try:
            return common.create_group(context, group)
        finally:
            self._logout(common)

    @utils.trace
    def create_group_from_src(self, context, group, volumes,
                              group_snapshot=None, snapshots=None,
                              source_group=None, source_vols=None):
        common = self._login()
        try:
            return common.create_group_from_src(
                context, group, volumes, group_snapshot, snapshots,
                source_group, source_vols)
        finally:
            self._logout(common)

    @utils.trace
    def delete_group(self, context, group, volumes):
        common = self._login()
        try:
            return common.delete_group(context, group, volumes)
        finally:
            self._logout(common)

    @utils.trace
    def update_group(self, context, group, add_volumes=None,
                     remove_volumes=None):
        common = self._login()
        try:
            return common.update_group(context, group, add_volumes,
                                       remove_volumes)
        finally:
            self._logout(common)

    @utils.trace
    def create_group_snapshot(self, context, group_snapshot, snapshots):
        common = self._login()
        try:
            return common.create_group_snapshot(context, group_snapshot,
                                                snapshots)
        finally:
            self._logout(common)

    @utils.trace
    def delete_group_snapshot(self, context, group_snapshot, snapshots):
        common = self._login()
        try:
            return common.delete_group_snapshot(context, group_snapshot,
                                                snapshots)
        finally:
            self._logout(common)

    @utils.trace
    def manage_existing(self, volume, existing_ref):
        common = self._login()
        try:
            return common.manage_existing(volume, existing_ref)
        finally:
            self._logout(common)

    @utils.trace
    def manage_existing_snapshot(self, snapshot, existing_ref):
        common = self._login()
        try:
            return common.manage_existing_snapshot(snapshot, existing_ref)
        finally:
            self._logout(common)

    @utils.trace
    def manage_existing_get_size(self, volume, existing_ref):
        common = self._login()
        try:
            return common.manage_existing_get_size(volume, existing_ref)
        finally:
            self._logout(common)

    @utils.trace
    def manage_existing_snapshot_get_size(self, snapshot, existing_ref):
        common = self._login()
        try:
            return common.manage_existing_snapshot_get_size(snapshot,
                                                            existing_ref)
        finally:
            self._logout(common)

    @utils.trace
    def unmanage(self, volume):
        common = self._login()
        try:
            common.unmanage(volume)
        finally:
            self._logout(common)

    @utils.trace
    def unmanage_snapshot(self, snapshot):
        common = self._login()
        try:
            common.unmanage_snapshot(snapshot)
        finally:
            self._logout(common)

    @utils.trace
    def retype(self, context, volume, new_type, diff, host):
        """Convert the volume to be of the new type."""
        common = self._login()
        try:
            return common.retype(volume, new_type, diff, host)
        finally:
            self._logout(common)

    @utils.trace
    def migrate_volume(self, context, volume, host):
        if volume['status'] == 'in-use':
            protocol = host['capabilities']['storage_protocol']
            if protocol != self.protocol:
                LOG.debug("3PAR %(protocol)s driver cannot migrate in-use "
                          "volume to a host with "
                          "storage_protocol=%(storage_protocol)s",
                          {'protocol': self.protocol,
                           'storage_protocol': protocol})
                return False, None

        common = self._login()
        try:
            return common.migrate_volume(volume, host)
        finally:
            self._logout(common)

    @utils.trace
    def update_migrated_volume(self, context, volume, new_volume,
                               original_volume_status):
        """Update the name of the migrated volume to it's new ID."""
        common = self._login()
        try:
            return common.update_migrated_volume(context, volume, new_volume,
                                                 original_volume_status)
        finally:
            self._logout(common)

    @utils.trace
    def get_pool(self, volume):
        common = self._login()
        try:
            return common.get_cpg(volume)
        except hpeexceptions.HTTPNotFound:
            reason = (_("Volume %s doesn't exist on array.") % volume)
            LOG.error(reason)
            raise exception.InvalidVolume(reason)
        finally:
            self._logout(common)

    @utils.trace
    def revert_to_snapshot(self, context, volume, snapshot):
        """Revert volume to snapshot."""
        common = self._login()
        try:
            common.revert_to_snapshot(volume, snapshot)
        finally:
            self._logout(common)

    @utils.trace
    def failover_host(self, context, volumes, secondary_id=None, groups=None):
        """Force failover to a secondary replication target."""
        common = self._login(timeout=30)
        try:
            # Update the active_backend_id in the driver and return it.
            active_backend_id, volume_updates, group_update_list = (
                common.failover_host(
                    context, volumes, secondary_id, groups))
            self._active_backend_id = active_backend_id
            return active_backend_id, volume_updates, group_update_list
        finally:
            self._logout(common)

    def enable_replication(self, context, group, volumes):
        """Enable replication for a group.

        :param context: the context
        :param group: the group object
        :param volumes: the list of volumes
        :returns: model_update, None
        """
        common = self._login()
        try:
            return common.enable_replication(context, group, volumes)
        finally:
            self._logout(common)

    def disable_replication(self, context, group, volumes):
        """Disable replication for a group.

        :param context: the context
        :param group: the group object
        :param volumes: the list of volumes
        :returns: model_update, None
        """
        common = self._login()
        try:
            return common.disable_replication(context, group, volumes)
        finally:
            self._logout(common)

    def failover_replication(self, context, group, volumes,
                             secondary_backend_id=None):
        """Failover replication for a group.

        :param context: the context
        :param group: the group object
        :param volumes: the list of volumes
        :param secondary_backend_id: the secondary backend id - default None
        :returns: model_update, vol_model_updates
        """
        common = self._login()
        try:
            return common.failover_replication(
                context, group, volumes, secondary_backend_id)
        finally:
            self._logout(common)

    def do_setup(self, context):
        common = self._init_common()
        common.do_setup(context)
        self._check_flags(common)
        common.check_for_setup_error()
        self._do_setup(common)

    def _do_setup(self, common):
        pass

    def create_export(self, context, volume, connector):
        pass

    def ensure_export(self, context, volume):
        pass

    def remove_export(self, context, volume):
        pass

    def terminate_connection(self, volume, connector, **kwargs):
        pass

    def initialize_connection(self, volume, connector):
        pass

    @utils.trace
    def _init_vendor_properties(self):
        """Create a dictionary of vendor unique properties.

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

        prefix: HPE:3PAR --> HPE_3PAR
        """

        properties = {}
        valid_prov_values = ['thin', 'full', 'dedup']
        valid_persona_values = ['2 - Generic-ALUA',
                                '1 - Generic',
                                '3 - Generic-legacy',
                                '4 - HPEUX-legacy',
                                '5 - AIX-legacy',
                                '6 - EGENERA',
                                '7 - ONTAP-legacy',
                                '8 - VMware',
                                '9 - OpenVMS',
                                '10 - HPEUX',
                                '11 - WindowsServer']

        self._set_property(
            properties,
            "HPE:3PAR:hpe3par:snap_cpg",
            "Snap CPG Extra-specs.",
            _("Specifies the Snap CPG for a volume type. It overrides the "
              "hpe3par_cpg_snap setting. Defaults to the hpe3par_cpg_snap "
              "setting in the cinder.conf file. If hpe3par_cpg_snap is not "
              "set, it defaults to the hpe3par_cpg setting."),
            "string")

        self._set_property(
            properties,
            "HPE:3PAR:hpe3par:persona",
            "Host Persona Extra-specs.",
            _("Specifies the host persona property for a volume type. It "
              "overrides the hpe3par_cpg_snap setting. Defaults to the "
              "hpe3par_cpg_snap setting in the cinder.conf file. "
              "If hpe3par_cpg_snap is not set, "
              "it defaults to the hpe3par_cpg setting."),
            "string",
            enum=valid_persona_values,
            default="2 - Generic-ALUA")

        self._set_property(
            properties,
            "HPE:3PAR:hpe3par:vvs",
            "Virtual Volume Set Extra-specs.",
            _("The virtual volume set name that has been set up by the "
              "administrator that would have predefined QoS rules "
              "associated with it. If you specify extra_specs "
              "hpe3par:vvs, the qos_specs minIOPS, maxIOPS, minBWS, "
              "and maxBWS settings are ignored."),
            "string")

        self._set_property(
            properties,
            "HPE:3PAR:hpe3par:flash_cache",
            "Flash cache Extra-specs.",
            _("Enables Flash cache setting for a volume type."),
            "boolean",
            default=False)

        self._set_property(
            properties,
            "HPE:3PAR:hpe3par:provisioning",
            "Storage Provisioning Extra-specs.",
            _("Specifies the provisioning for a volume type."),
            "string",
            enum=valid_prov_values,
            default="thin")

        self._set_property(
            properties,
            "HPE:3PAR:hpe3par:compression",
            "Storage Provisioning Extra-specs.",
            _("Enables compression for a volume type. "
              "Minimum requirement of 3par OS version is 3.3.1 "
              "with SSD drives only. "
              "Volume size must have > 16 GB to enable "
              "compression on volume. "
              "A full provisioned volume cannot be compressed."),
            "boolean",
            default=False)

        self._set_property(
            properties,
            "HPE:3PAR:replication_enabled",
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
            "HPE:3PAR:replication:mode",
            "Replication Mode Extra-specs.",
            _("Sets the replication mode for 3par."),
            "string",
            enum=["sync", "periodic"],
            default="periodic")

        self._set_property(
            properties,
            "HPE:3PAR:replication:sync_period",
            "Sync Period for Volume Replication Extra-specs.",
            _("Sets the time interval for synchronization. "
              "Only needed if replication:mode is periodic."),
            "integer",
            default=900)

        self._set_property(
            properties,
            "HPE:3PAR:replication:retention_count",
            "Retention Count for Replication Extra-specs.",
            _("Sets the number of snapshots that will be  "
              "saved on the primary array."),
            "integer",
            default=5)

        self._set_property(
            properties,
            "HPE:3PAR:replication:remote_retention_count",
            "Remote Retention Count for Replication Extra-specs.",
            _("Sets the number of snapshots that will be  "
              "saved on the secondary array."),
            "integer",
            default=5)

        # ###### QoS Settings ###### #

        self._set_property(
            properties,
            "HPE:3PAR:minIOPS",
            "Minimum IOPS QoS.",
            _("Sets the QoS, I/O issue count minimum goal. "
              "If not specified, there is no limit on I/O issue count."),
            "integer")

        self._set_property(
            properties,
            "HPE:3PAR:maxIOPS",
            "Maximum IOPS QoS.",
            _("Sets the QoS, I/O issue count rate limit. "
              "If not specified, there is no limit on I/O issue count."),
            "integer")

        self._set_property(
            properties,
            "HPE:3PAR:minBWS",
            "Minimum Bandwidth QoS.",
            _("Sets the QoS, I/O issue bandwidth minimum goal. "
              "If not specified, there is no limit on "
              "I/O issue bandwidth rate."),
            "integer")

        self._set_property(
            properties,
            "HPE:3PAR:maxBWS",
            "Maximum Bandwidth QoS.",
            _("Sets the QoS, I/O issue bandwidth rate limit. "
              "If not specified, there is no limit on I/O issue "
              "bandwidth rate."),
            "integer")

        self._set_property(
            properties,
            "HPE:3PAR:latency",
            "Latency QoS.",
            _("Sets the latency goal in milliseconds."),
            "integer")

        self._set_property(
            properties,
            "HPE:3PAR:priority",
            "Priority QoS.",
            _("Sets the priority of the QoS rule over other rules."),
            "string",
            enum=["low", "normal", "high"],
            default="normal")

        return properties, 'HPE:3PAR'
