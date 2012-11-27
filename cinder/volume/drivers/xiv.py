# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2012 IBM, Inc.
# Copyright (c) 2012 OpenStack LLC.
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
#
# Authors:
#   Erik Zaadi <erikz@il.ibm.com>
#   Avishay Traeger <avishay@il.ibm.com>

"""
Volume driver for IBM XIV storage systems.
"""

from cinder import exception
from cinder import flags
from cinder.openstack.common import cfg
from cinder.openstack.common import importutils
from cinder.openstack.common import log as logging
from cinder.volume.drivers.san import san

ibm_xiv_opts = [
    cfg.StrOpt('xiv_proxy',
               default='xiv_openstack.nova_proxy.XIVNovaProxy',
               help='Proxy driver'),
]

FLAGS = flags.FLAGS
FLAGS.register_opts(ibm_xiv_opts)

LOG = logging.getLogger('cinder.volume.xiv')


class XIVDriver(san.SanISCSIDriver):
    """IBM XIV volume driver."""

    def __init__(self, *args, **kwargs):
        """Initialize the driver."""

        proxy = importutils.import_class(FLAGS.xiv_proxy)

        self.xiv_proxy = proxy({"xiv_user": FLAGS.san_login,
                                "xiv_pass": FLAGS.san_password,
                                "xiv_address": FLAGS.san_ip,
                                "xiv_vol_pool": FLAGS.san_clustername},
                               LOG,
                               exception)
        san.SanISCSIDriver.__init__(self, *args, **kwargs)

    def do_setup(self, context):
        """Setup and verify IBM XIV storage connection."""

        self.xiv_proxy.setup(context)

    def ensure_export(self, context, volume):
        """Ensure an export."""

        return self.xiv_proxy.ensure_export(context, volume)

    def create_export(self, context, volume):
        """Create an export."""

        return self.xiv_proxy.create_export(context, volume)

    def create_volume(self, volume):
        """Create a volume on the IBM XIV storage system."""

        return self.xiv_proxy.create_volume(volume)

    def delete_volume(self, volume):
        """Delete a volume on the IBM XIV storage system."""

        self.xiv_proxy.delete_volume(volume)

    def remove_export(self, context, volume):
        """Disconnect a volume from an attached instance."""

        return self.xiv_proxy.remove_export(context, volume)

    def initialize_connection(self, volume, connector):
        """Map the created volume."""

        return self.xiv_proxy.initialize_connection(volume, connector)

    def terminate_connection(self, volume, connector, **kwargs):
        """Terminate a connection to a volume."""

        return self.xiv_proxy.terminate_connection(volume, connector)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Create a volume from a snapshot."""

        return self.xiv_proxy.create_volume_from_snapshot(volume,
                                                          snapshot)

    def create_snapshot(self, snapshot):
        """Create a snapshot."""

        return self.xiv_proxy.create_snapshot(snapshot)

    def delete_snapshot(self, snapshot):
        """Delete a snapshot."""

        return self.xiv_proxy.delete_snapshot(snapshot)

    def get_volume_stats(self, refresh=False):
        """Get volume stats."""

        return self.xiv_proxy.get_volume_stats(refresh)
