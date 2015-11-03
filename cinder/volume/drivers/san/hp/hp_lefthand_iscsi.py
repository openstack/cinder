#    (c) Copyright 2014 Hewlett-Packard Development Company, L.P.
#    All Rights Reserved.
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
Volume driver for HP LeftHand Storage array.
This driver requires 11.5 or greater firmware on the LeftHand array, using
the 1.0 or greater version of the hplefthandclient.

You will need to install the python hplefthandclient.
sudo pip install hplefthandclient

Set the following in the cinder.conf file to enable the
LeftHand Channel Driver along with the required flags:

volume_driver=cinder.volume.drivers.san.hp.hp_lefthand_iscsi.
    HPLeftHandISCSIDriver

It also requires the setting of hplefthand_api_url, hplefthand_username,
hplefthand_password for credentials to talk to the REST service on the
LeftHand array.
"""

from oslo_log import log as logging

from cinder import exception
from cinder.i18n import _, _LI
from cinder.volume import driver
from cinder.volume.drivers.san.hp import hp_lefthand_cliq_proxy as cliq_proxy
from cinder.volume.drivers.san.hp import hp_lefthand_rest_proxy as rest_proxy

LOG = logging.getLogger(__name__)

MIN_CLIENT_VERSION = '1.0.4'


class HPLeftHandISCSIDriver(driver.TransferVD,
                            driver.ManageableVD,
                            driver.ExtendVD,
                            driver.SnapshotVD,
                            driver.MigrateVD,
                            driver.BaseVD,
                            driver.ConsistencyGroupVD):
    """Executes commands relating to HP/LeftHand SAN ISCSI volumes.

    Version history:
        1.0.0 - Initial driver
        1.0.1 - Added support for retype
        1.0.2 - Added support for volume migrate
        1.0.3 - Fix for no handler for logger during tests
        1.0.4 - Removing locks bug #1395953
        1.0.5 - Adding support for manage/unmanage.
        1.0.6 - Updated minimum client version. bug #1432757
        1.0.7 - Update driver to use ABC metaclasses
        1.0.8 - Adds consistency group support
        1.0.9 - Added update_migrated_volume #1493546
    """

    VERSION = "1.0.9"

    def __init__(self, *args, **kwargs):
        super(HPLeftHandISCSIDriver, self).__init__(*args, **kwargs)
        self.proxy = None
        self.args = args
        self.kwargs = kwargs

    def _create_proxy(self, *args, **kwargs):
        try:
            proxy = rest_proxy.HPLeftHandRESTProxy(*args, **kwargs)
        except exception.NotFound:
            proxy = cliq_proxy.HPLeftHandCLIQProxy(*args, **kwargs)

        return proxy

    def check_for_setup_error(self):
        self.proxy.check_for_setup_error()

    def do_setup(self, context):
        self.proxy = self._create_proxy(*self.args, **self.kwargs)

        LOG.info(_LI("HPLeftHand driver %(driver_ver)s, "
                     "proxy %(proxy_ver)s"), {
            "driver_ver": self.VERSION,
            "proxy_ver": self.proxy.get_version_string()})

        if isinstance(self.proxy, cliq_proxy.HPLeftHandCLIQProxy):
            self.proxy.do_setup(context)
        else:
            # Check minimum client version for REST proxy
            client_version = rest_proxy.hplefthandclient.version

            if client_version < MIN_CLIENT_VERSION:
                ex_msg = (_("Invalid hplefthandclient version found ("
                            "%(found)s). Version %(minimum)s or greater "
                            "required.")
                          % {'found': client_version,
                             'minimum': MIN_CLIENT_VERSION})
                LOG.error(ex_msg)
                raise exception.InvalidInput(reason=ex_msg)

    def create_volume(self, volume):
        """Creates a volume."""
        return self.proxy.create_volume(volume)

    def extend_volume(self, volume, new_size):
        """Extend the size of an existing volume."""
        self.proxy.extend_volume(volume, new_size)

    def create_consistencygroup(self, context, group):
        """Creates a consistency group."""
        return self.proxy.create_consistencygroup(context, group)

    def create_consistencygroup_from_src(self, context, group, volumes,
                                         cgsnapshot=None, snapshots=None,
                                         source_cg=None, source_vols=None):
        """Creates a consistency group from a source"""
        return self.proxy.create_consistencygroup_from_src(
            context, group, volumes, cgsnapshot, snapshots, source_cg,
            source_vols)

    def delete_consistencygroup(self, context, group):
        """Deletes a consistency group."""
        return self.proxy.delete_consistencygroup(context, group)

    def update_consistencygroup(self, context, group,
                                add_volumes=None, remove_volumes=None):
        """Updates a consistency group."""
        return self.proxy.update_consistencygroup(context, group, add_volumes,
                                                  remove_volumes)

    def create_cgsnapshot(self, context, cgsnapshot):
        """Creates a consistency group snapshot."""
        return self.proxy.create_cgsnapshot(context, cgsnapshot)

    def delete_cgsnapshot(self, context, cgsnapshot):
        """Deletes a consistency group snapshot."""
        return self.proxy.delete_cgsnapshot(context, cgsnapshot)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""
        return self.proxy.create_volume_from_snapshot(volume, snapshot)

    def create_snapshot(self, snapshot):
        """Creates a snapshot."""
        self.proxy.create_snapshot(snapshot)

    def delete_volume(self, volume):
        """Deletes a volume."""
        self.proxy.delete_volume(volume)

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        self.proxy.delete_snapshot(snapshot)

    def initialize_connection(self, volume, connector):
        """Assigns the volume to a server."""
        return self.proxy.initialize_connection(volume, connector)

    def terminate_connection(self, volume, connector, **kwargs):
        """Unassign the volume from the host."""
        self.proxy.terminate_connection(volume, connector)

    def get_volume_stats(self, refresh=False):
        data = self.proxy.get_volume_stats(refresh)
        data['driver_version'] = self.VERSION
        return data

    def create_cloned_volume(self, volume, src_vref):
        return self.proxy.create_cloned_volume(volume, src_vref)

    def create_export(self, context, volume, connector):
        return self.proxy.create_export(context, volume, connector)

    def ensure_export(self, context, volume):
        return self.proxy.ensure_export(context, volume)

    def remove_export(self, context, volume):
        return self.proxy.remove_export(context, volume)

    def retype(self, context, volume, new_type, diff, host):
        """Convert the volume to be of the new type."""
        return self.proxy.retype(context, volume, new_type, diff, host)

    def migrate_volume(self, ctxt, volume, host):
        """Migrate directly if source and dest are managed by same storage."""
        return self.proxy.migrate_volume(ctxt, volume, host)

    def update_migrated_volume(self, context, volume, new_volume,
                               original_volume_status):
        return self.proxy.update_migrated_volume(context, volume, new_volume,
                                                 original_volume_status)

    def manage_existing(self, volume, existing_ref):
        return self.proxy.manage_existing(volume, existing_ref)

    def manage_existing_get_size(self, volume, existing_ref):
        return self.proxy.manage_existing_get_size(volume, existing_ref)

    def unmanage(self, volume):
        return self.proxy.unmanage(volume)
