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

"""
IBM Storage driver is a unified Volume driver for IBM XIV, Spectrum Accelerate,
FlashSystem A9000, FlashSystem A9000R and DS8000 storage systems.
"""

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import importutils

from cinder import exception
from cinder import interface
from cinder.volume import configuration
from cinder.volume import driver
from cinder.volume.drivers.san import san
from cinder.zonemanager import utils as fczm_utils

driver_opts = [
    cfg.StrOpt(
        'proxy',
        default='cinder.volume.drivers.ibm.ibm_storage.proxy.IBMStorageProxy',
        help='Proxy driver that connects to the IBM Storage Array'),
    cfg.StrOpt(
        'connection_type',
        default='iscsi',
        choices=['fibre_channel', 'iscsi'],
        help='Connection type to the IBM Storage Array'),
    cfg.StrOpt(
        'chap',
        default='disabled',
        choices=['disabled', 'enabled'],
        help='CHAP authentication mode, effective only for iscsi'
        ' (disabled|enabled)'),
    cfg.StrOpt(
        'management_ips',
        default='',
        help='List of Management IP addresses (separated by commas)'),
]

CONF = cfg.CONF
CONF.register_opts(driver_opts, group=configuration.SHARED_CONF_GROUP)

LOG = logging.getLogger(__name__)


@interface.volumedriver
class IBMStorageDriver(san.SanDriver,
                       driver.ManageableVD,
                       driver.MigrateVD,
                       driver.CloneableImageVD):
    """IBM Storage driver

    IBM Storage driver is a unified Volume driver for IBM XIV, Spectrum
    Accelerate, FlashSystem A9000, FlashSystem A9000R and DS8000 storage
    systems.

    Version history:

    .. code-block:: none

        2.0 - First open source driver version
        2.1.0 - Support Consistency groups through Generic volume groups
              - Support XIV/A9000 Volume independent QoS
              - Support Consistency groups replication
        2.3.0 - Support Report backend state
    """

    VERSION = "2.3.0"

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "IBM_STORAGE_CI"

    def __init__(self, *args, **kwargs):
        """Initialize the driver."""

        super(IBMStorageDriver, self).__init__(*args, **kwargs)

        self.configuration.append_config_values(driver_opts)

        proxy = importutils.import_class(self.configuration.proxy)

        active_backend_id = kwargs.get('active_backend_id', None)

        # Driver additional flags should be specified in the cinder.conf
        # preferably in each backend configuration.

        self.proxy = proxy(
            {
                "user": self.configuration.san_login,
                "password": self.configuration.san_password,
                "address": self.configuration.san_ip,
                "vol_pool": self.configuration.san_clustername,
                "connection_type": self.configuration.connection_type,
                "chap": self.configuration.chap,
                "management_ips": self.configuration.management_ips
            },
            LOG,
            exception,
            driver=self,
            active_backend_id=active_backend_id,
            host=self.host)

    @staticmethod
    def get_driver_options():
        return driver_opts

    def do_setup(self, context):
        """Setup and verify connection to IBM Storage."""

        self.proxy.setup(context)

    def ensure_export(self, context, volume):
        """Ensure an export."""

        return self.proxy.ensure_export(context, volume)

    def create_export(self, context, volume, connector):
        """Create an export."""

        return self.proxy.create_export(context, volume)

    def create_volume(self, volume):
        """Create a volume on the IBM Storage system."""

        return self.proxy.create_volume(volume)

    def delete_volume(self, volume):
        """Delete a volume on the IBM Storage system."""

        self.proxy.delete_volume(volume)

    def remove_export(self, context, volume):
        """Disconnect a volume from an attached instance."""

        return self.proxy.remove_export(context, volume)

    def initialize_connection(self, volume, connector):
        """Map the created volume."""

        conn_info = self.proxy.initialize_connection(volume, connector)
        fczm_utils.add_fc_zone(conn_info)
        return conn_info

    def terminate_connection(self, volume, connector, **kwargs):
        """Terminate a connection to a volume."""

        conn_info = self.proxy.terminate_connection(volume, connector)
        fczm_utils.remove_fc_zone(conn_info)
        return conn_info

    def create_volume_from_snapshot(self, volume, snapshot):
        """Create a volume from a snapshot."""

        return self.proxy.create_volume_from_snapshot(
            volume,
            snapshot)

    def create_snapshot(self, snapshot):
        """Create a snapshot."""

        return self.proxy.create_snapshot(snapshot)

    def delete_snapshot(self, snapshot):
        """Delete a snapshot."""

        return self.proxy.delete_snapshot(snapshot)

    def get_volume_stats(self, refresh=False):
        """Get volume stats."""

        return self.proxy.get_volume_stats(refresh)

    def create_cloned_volume(self, tgt_volume, src_volume):
        """Create Cloned Volume."""

        return self.proxy.create_cloned_volume(tgt_volume, src_volume)

    def extend_volume(self, volume, new_size):
        """Extend Created Volume."""

        self.proxy.extend_volume(volume, new_size)

    def migrate_volume(self, context, volume, host):
        """Migrate the volume to the specified host."""

        return self.proxy.migrate_volume(context, volume, host)

    def manage_existing(self, volume, existing_ref):
        """Brings an existing backend storage object to Cinder management."""

        return self.proxy.manage_volume(volume, existing_ref)

    def manage_existing_get_size(self, volume, existing_ref):
        """Return size of volume to be managed by manage_existing."""

        return self.proxy.manage_volume_get_size(volume, existing_ref)

    def unmanage(self, volume):
        """Removes the specified volume from Cinder management."""

        return self.proxy.unmanage_volume(volume)

    def freeze_backend(self, context):
        """Notify the backend that it's frozen. """

        return self.proxy.freeze_backend(context)

    def thaw_backend(self, context):
        """Notify the backend that it's unfrozen/thawed. """

        return self.proxy.thaw_backend(context)

    def failover_host(self, context, volumes, secondary_id=None, groups=None):
        """Failover a backend to a secondary replication target. """

        return self.proxy.failover_host(
            context, volumes, secondary_id, groups)

    def get_replication_status(self, context, volume):
        """Return replication status."""

        return self.proxy.get_replication_status(context, volume)

    def retype(self, ctxt, volume, new_type, diff, host):
        """Convert the volume to be of the new type."""

        return self.proxy.retype(ctxt, volume, new_type, diff, host)

    def create_group(self, context, group):
        """Creates a group."""

        return self.proxy.create_group(context, group)

    def delete_group(self, context, group, volumes):
        """Deletes a group."""

        return self.proxy.delete_group(context, group, volumes)

    def create_group_snapshot(self, context, group_snapshot, snapshots):
        """Creates a group snapshot."""

        return self.proxy.create_group_snapshot(
            context, group_snapshot, snapshots)

    def delete_group_snapshot(self, context, group_snapshot, snapshots):
        """Deletes a group snapshot."""

        return self.proxy.delete_group_snapshot(
            context, group_snapshot, snapshots)

    def update_group(self, context, group, add_volumes, remove_volumes):
        """Adds or removes volume(s) to/from an existing group."""

        return self.proxy.update_group(
            context, group, add_volumes, remove_volumes)

    def create_group_from_src(
            self, context, group, volumes, group_snapshot, snapshots,
            source_cg=None, source_vols=None):
        """Creates a group from source."""

        return self.proxy.create_group_from_src(
            context, group, volumes, group_snapshot, snapshots,
            source_cg, source_vols)

    def enable_replication(self, context, group, volumes):
        """Enable replication."""

        return self.proxy.enable_replication(context, group, volumes)

    def disable_replication(self, context, group, volumes):
        """Disable replication."""

        return self.proxy.disable_replication(context, group, volumes)

    def failover_replication(self, context, group, volumes,
                             secondary_backend_id):
        """Failover replication."""

        return self.proxy.failover_replication(context, group, volumes,
                                               secondary_backend_id)

    def get_replication_error_status(self, context, groups):
        """Returns error info for replicated groups and its volumes."""

        return self.proxy.get_replication_error_status(context, groups)
