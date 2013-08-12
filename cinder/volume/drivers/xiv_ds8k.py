# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 IBM Corp.
# Copyright (c) 2013 OpenStack LLC.
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
Unified Volume driver for IBM XIV and DS8K Storage Systems.
"""

from oslo.config import cfg

from cinder import exception
from cinder.openstack.common import importutils
from cinder.openstack.common import log as logging
from cinder.volume.drivers.san import san

xiv_ds8k_opts = [
    cfg.StrOpt(
        'xiv_ds8k_proxy',
        default='xiv_ds8k_openstack.nova_proxy.XIVDS8KNovaProxy',
        help='Proxy driver that connects to the IBM Storage Array'),
    cfg.StrOpt(
        'xiv_ds8k_connection_type',
        default='iscsi',
        help='Connection type to the IBM Storage Array'
        ' (fibre_channel|iscsi)'),
]

CONF = cfg.CONF
CONF.register_opts(xiv_ds8k_opts)

LOG = logging.getLogger(__name__)


class XIVDS8KDriver(san.SanDriver):
    """Unified IBM XIV and DS8K volume driver."""

    def __init__(self, *args, **kwargs):
        """Initialize the driver."""

        super(XIVDS8KDriver, self).__init__(*args, **kwargs)

        self.configuration.append_config_values(xiv_ds8k_opts)

        proxy = importutils.import_class(self.configuration.xiv_ds8k_proxy)

        #NOTE: All Array specific configurations are prefixed with:
        #"xiv_ds8k_array_"
        #These additional flags should be specified in the cinder.conf
        #preferably in each backend configuration.

        self.xiv_ds8k_proxy = proxy(
            {
                "xiv_ds8k_user": self.configuration.san_login,
                "xiv_ds8k_pass": self.configuration.san_password,
                "xiv_ds8k_address": self.configuration.san_ip,
                "xiv_ds8k_vol_pool": self.configuration.san_clustername,
                "xiv_ds8k_connection_type":
                self.configuration.xiv_ds8k_connection_type
            },
            LOG,
            exception,
            driver=self)

    def do_setup(self, context):
        """Setup and verify IBM XIV and DS8K Storage connection."""

        self.xiv_ds8k_proxy.setup(context)

    def ensure_export(self, context, volume):
        """Ensure an export."""

        return self.xiv_ds8k_proxy.ensure_export(context, volume)

    def create_export(self, context, volume):
        """Create an export."""

        return self.xiv_ds8k_proxy.create_export(context, volume)

    def create_volume(self, volume):
        """Create a volume on the IBM XIV and DS8K Storage system."""

        return self.xiv_ds8k_proxy.create_volume(volume)

    def delete_volume(self, volume):
        """Delete a volume on the IBM XIV and DS8K Storage system."""

        self.xiv_ds8k_proxy.delete_volume(volume)

    def remove_export(self, context, volume):
        """Disconnect a volume from an attached instance."""

        return self.xiv_ds8k_proxy.remove_export(context, volume)

    def initialize_connection(self, volume, connector):
        """Map the created volume."""

        return self.xiv_ds8k_proxy.initialize_connection(volume, connector)

    def terminate_connection(self, volume, connector, **kwargs):
        """Terminate a connection to a volume."""

        return self.xiv_ds8k_proxy.terminate_connection(volume, connector)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Create a volume from a snapshot."""

        return self.xiv_ds8k_proxy.create_volume_from_snapshot(
            volume,
            snapshot)

    def create_snapshot(self, snapshot):
        """Create a snapshot."""

        return self.xiv_ds8k_proxy.create_snapshot(snapshot)

    def delete_snapshot(self, snapshot):
        """Delete a snapshot."""

        return self.xiv_ds8k_proxy.delete_snapshot(snapshot)

    def get_volume_stats(self, refresh=False):
        """Get volume stats."""

        return self.xiv_ds8k_proxy.get_volume_stats(refresh)

    def create_cloned_volume(self, tgt_volume, src_volume):
        """Create Cloned Volume."""

        return self.xiv_ds8k_proxy.create_cloned_volume(tgt_volume, src_volume)

    def extend_volume(self, volume, new_size):
        """Extend Created Volume."""

        self.xiv_ds8k_proxy.extend_volume(volume, new_size)

    def migrate_volume(self, context, volume, host):
        """Migrate the volume to the specified host."""

        return self.xiv_ds8k_proxy.migrate_volume(context, volume, host)
