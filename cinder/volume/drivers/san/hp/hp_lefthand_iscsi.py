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
from cinder import exception
from cinder.i18n import _
from cinder.openstack.common import log as logging
from cinder import utils
from cinder.volume.driver import VolumeDriver
from cinder.volume.drivers.san.hp import hp_lefthand_cliq_proxy as cliq_proxy
from cinder.volume.drivers.san.hp import hp_lefthand_rest_proxy as rest_proxy

LOG = logging.getLogger(__name__)


class HPLeftHandISCSIDriver(VolumeDriver):
    """Executes commands relating to HP/LeftHand SAN ISCSI volumes.

    Version history:
        1.0.0 - Initial driver
        1.0.1 - Added support for retype
        1.0.2 - Added support for volume migrate
        1.0.3 - Fix for no handler for logger during tests
    """

    VERSION = "1.0.3"

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

    @utils.synchronized('lefthand', external=True)
    def check_for_setup_error(self):
        self.proxy.check_for_setup_error()

    @utils.synchronized('lefthand', external=True)
    def do_setup(self, context):
        self.proxy = self._create_proxy(*self.args, **self.kwargs)
        self.proxy.do_setup(context)

        LOG.info(_("HPLeftHand driver %(driver_ver)s, proxy %(proxy_ver)s") % {
            "driver_ver": self.VERSION,
            "proxy_ver": self.proxy.get_version_string()})

    @utils.synchronized('lefthand', external=True)
    def create_volume(self, volume):
        """Creates a volume."""
        return self.proxy.create_volume(volume)

    @utils.synchronized('lefthand', external=True)
    def extend_volume(self, volume, new_size):
        """Extend the size of an existing volume."""
        self.proxy.extend_volume(volume, new_size)

    @utils.synchronized('lefthand', external=True)
    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""
        return self.proxy.create_volume_from_snapshot(volume, snapshot)

    @utils.synchronized('lefthand', external=True)
    def create_snapshot(self, snapshot):
        """Creates a snapshot."""
        self.proxy.create_snapshot(snapshot)

    @utils.synchronized('lefthand', external=True)
    def delete_volume(self, volume):
        """Deletes a volume."""
        self.proxy.delete_volume(volume)

    @utils.synchronized('lefthand', external=True)
    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        self.proxy.delete_snapshot(snapshot)

    @utils.synchronized('lefthand', external=True)
    def initialize_connection(self, volume, connector):
        """Assigns the volume to a server."""
        return self.proxy.initialize_connection(volume, connector)

    @utils.synchronized('lefthand', external=True)
    def terminate_connection(self, volume, connector, **kwargs):
        """Unassign the volume from the host."""
        self.proxy.terminate_connection(volume, connector)

    @utils.synchronized('lefthand', external=True)
    def get_volume_stats(self, refresh):
        data = self.proxy.get_volume_stats(refresh)
        data['driver_version'] = self.VERSION
        return data

    @utils.synchronized('lefthand', external=True)
    def create_cloned_volume(self, volume, src_vref):
        return self.proxy.create_cloned_volume(volume, src_vref)

    @utils.synchronized('lefthand', external=True)
    def create_export(self, context, volume):
        return self.proxy.create_export(context, volume)

    @utils.synchronized('lefthand', external=True)
    def ensure_export(self, context, volume):
        return self.proxy.ensure_export(context, volume)

    @utils.synchronized('lefthand', external=True)
    def remove_export(self, context, volume):
        return self.proxy.remove_export(context, volume)

    @utils.synchronized('lefthand', external=True)
    def retype(self, context, volume, new_type, diff, host):
        """Convert the volume to be of the new type."""
        return self.proxy.retype(context, volume, new_type, diff, host)

    @utils.synchronized('lefthand', external=True)
    def migrate_volume(self, ctxt, volume, host):
        """Migrate directly if source and dest are managed by same storage."""
        return self.proxy.migrate_volume(ctxt, volume, host)
