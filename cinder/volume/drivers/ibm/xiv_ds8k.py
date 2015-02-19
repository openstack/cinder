# Copyright 2013 IBM Corp.
# Copyright (c) 2013 OpenStack Foundation
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

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import importutils

from cinder import exception
from cinder.volume.drivers.san import san

xiv_ds8k_opts = [
    cfg.StrOpt(
        'xiv_ds8k_proxy',
        default='xiv_ds8k_openstack.nova_proxy.XIVDS8KNovaProxy',
        help='Proxy driver that connects to the IBM Storage Array'),
    cfg.StrOpt(
        'xiv_ds8k_connection_type',
        default='iscsi',
        choices=['fibre_channel', 'iscsi'],
        help='Connection type to the IBM Storage Array'),
    cfg.StrOpt(
        'xiv_chap',
        default='disabled',
        choices=['disabled', 'enabled'],
        help='CHAP authentication mode, effective only for iscsi'
        ' (disabled|enabled)'),
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

        # NOTE: All Array specific configurations are prefixed with:
        # "xiv_ds8k_array_"
        # These additional flags should be specified in the cinder.conf
        # preferably in each backend configuration.

        self.xiv_ds8k_proxy = proxy(
            {
                "xiv_ds8k_user": self.configuration.san_login,
                "xiv_ds8k_pass": self.configuration.san_password,
                "xiv_ds8k_address": self.configuration.san_ip,
                "xiv_ds8k_vol_pool": self.configuration.san_clustername,
                "xiv_ds8k_connection_type":
                self.configuration.xiv_ds8k_connection_type,
                "xiv_chap": self.configuration.xiv_chap
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

    def manage_existing(self, volume, existing_ref):
        """Brings an existing backend storage object under Cinder management.

        existing_ref is passed straight through from the API request's
        manage_existing_ref value, and it is up to the driver how this should
        be interpreted.  It should be sufficient to identify a storage object
        that the driver should somehow associate with the newly-created cinder
        volume structure.
        In the case of XIV, the existing_ref consists of a single field named
        'existing_ref' representing the name of the volume on the storage.

        There are two ways to do this:

        1. Rename the backend storage object so that it matches the,
           volume['name'] which is how drivers traditionally map between a
           cinder volume and the associated backend storage object.

        2. Place some metadata on the volume, or somewhere in the backend, that
           allows other driver requests (e.g. delete, clone, attach, detach...)
           to locate the backend storage object when required.

        If the existing_ref doesn't make sense, or doesn't refer to an existing
        backend storage object, raise a ManageExistingInvalidReference
        exception.

        The volume may have a volume_type, and the driver can inspect that and
        compare against the properties of the referenced backend storage
        object.  If they are incompatible, raise a
        ManageExistingVolumeTypeMismatch, specifying a reason for the failure.
        """
        return self.xiv_ds8k_proxy.manage_volume(volume, existing_ref)

    def manage_existing_get_size(self, volume, existing_ref):
        """Return size of volume to be managed by manage_existing."""

        return self.xiv_ds8k_proxy.manage_volume_get_size(volume, existing_ref)

    def unmanage(self, volume):
        """Removes the specified volume from Cinder management."""

        return self.xiv_ds8k_proxy.unmanage_volume(volume)

    def reenable_replication(self, context, volume):
        """Re-enable volume replication. """

        return self.xiv_ds8k_proxy.reenable_replication(context, volume)

    def get_replication_status(self, context, volume):
        """Return replication status."""

        return self.xiv_ds8k_proxy.get_replication_status(context, volume)

    def promote_replica(self, context, volume):
        """Promote the replica to be the primary volume."""

        return self.xiv_ds8k_proxy.promote_replica(context, volume)

    def create_replica_test_volume(self, volume, src_vref):
        """Creates a test replica clone of the specified replicated volume."""

        return self.xiv_ds8k_proxy.create_replica_test_volume(volume, src_vref)

    def retype(self, ctxt, volume, new_type, diff, host):
        """Convert the volume to be of the new type."""

        return self.xiv_ds8k_proxy.retype(ctxt, volume, new_type, diff, host)

    def create_consistencygroup(self, context, group):
        """Creates a consistency group."""

        return self.xiv_ds8k_proxy.create_consistencygroup(context, group)

    def delete_consistencygroup(self, context, group):
        """Deletes a consistency group."""

        return self.xiv_ds8k_proxy.delete_consistencygroup(context, group)

    def create_cgsnapshot(self, context, cgsnapshot):
        """Creates a consistency group snapshot."""

        return self.xiv_ds8k_proxy.create_cgsnapshot(context, cgsnapshot)

    def delete_cgsnapshot(self, context, cgsnapshot):
        """Deletes a consistency group snapshot."""

        return self.xiv_ds8k_proxy.delete_cgsnapshot(context, cgsnapshot)
