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

    """

    VERSION = "1.0.1"

    def __init__(self, *args, **kwargs):
        super(HPE3PARDriverBase, self).__init__(*args, **kwargs)
        self._active_backend_id = kwargs.get('active_backend_id', None)
        self.configuration.append_config_values(hpecommon.hpe3par_opts)
        self.configuration.append_config_values(san.san_opts)
        self.protocol = None

    def _init_common(self):
        return hpecommon.HPE3PARCommon(self.configuration,
                                       self._active_backend_id)

    def _login(self, timeout=None):
        common = self._init_common()
        # If replication is enabled and we cannot login, we do not want to
        # raise an exception so a failover can still be executed.
        try:
            common.do_setup(None, timeout=timeout, stats=self._stats)
            common.client_login()
        except Exception:
            if common._replication_enabled:
                LOG.warning("The primary array is not reachable at this "
                            "time. Since replication is enabled, "
                            "listing replication targets and failing over "
                            "a volume can still be performed.")
                pass
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

    @utils.trace
    def get_volume_stats(self, refresh=False):
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
            common.create_group(context, group)
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
            LOG.debug("3PAR %(protocol)s driver cannot migrate in-use volume "
                      "to a host with storage_protocol=%(protocol)s",
                      {'protocol': self.protocol})
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
    def failover_host(self, context, volumes, secondary_id=None):
        """Force failover to a secondary replication target."""
        common = self._login(timeout=30)
        try:
            # Update the active_backend_id in the driver and return it.
            active_backend_id, volume_updates = common.failover_host(
                context, volumes, secondary_id)
            self._active_backend_id = active_backend_id
            return active_backend_id, volume_updates, []
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
