# Copyright (C) 2016, Hitachi, Ltd.
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
"""iSCSI module for Hitachi VSP Driver."""

from oslo_config import cfg

from cinder import interface
from cinder.volume import configuration
from cinder.volume import driver
from cinder.volume.drivers.hitachi import vsp_common as common
from cinder.volume.drivers.hitachi import vsp_utils as utils

iscsi_opts = [
    cfg.BoolOpt(
        'vsp_use_chap_auth',
        default=False,
        help='If True, CHAP authentication will be applied to communication '
        'between hosts and any of the iSCSI targets on the storage ports.'),
    cfg.StrOpt(
        'vsp_auth_user',
        help='Name of the user used for CHAP authentication performed in '
        'communication between hosts and iSCSI targets on the storage ports.'),
    cfg.StrOpt(
        'vsp_auth_password',
        secret=True,
        help='Password corresponding to vsp_auth_user.'),
]

MSG = utils.VSPMsg

_DRIVER_INFO = {
    'proto': 'iSCSI',
    'hba_id': 'initiator',
    'hba_id_type': 'iSCSI initiator IQN',
    'msg_id': {
        'target': MSG.CREATE_ISCSI_TARGET_FAILED,
    },
    'volume_backend_name': utils.DRIVER_PREFIX + 'iSCSI',
    'volume_opts': iscsi_opts,
    'volume_type': 'iscsi',
}

CONF = cfg.CONF
CONF.register_opts(iscsi_opts, group=configuration.SHARED_CONF_GROUP)


@interface.volumedriver
class VSPISCSIDriver(driver.ISCSIDriver):
    """iSCSI class for Hitachi VSP Driver.

    Version history:

    .. code-block:: none

        1.0.0 - Initial driver.

    """

    VERSION = common.VERSION

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "Hitachi_VSP_CI"

    SUPPORTED = False

    def __init__(self, *args, **kwargs):
        """Initialize instance variables."""
        utils.output_log(MSG.DRIVER_INITIALIZATION_START,
                         driver=self.__class__.__name__,
                         version=self.get_version())
        super(VSPISCSIDriver, self).__init__(*args, **kwargs)

        self.configuration.append_config_values(common.common_opts)
        self.configuration.append_config_values(iscsi_opts)
        self.common = utils.import_object(
            self.configuration, _DRIVER_INFO, kwargs.get('db'))

    def check_for_setup_error(self):
        """Error are checked in do_setup() instead of this method."""
        pass

    @utils.output_start_end_log
    def create_volume(self, volume):
        """Create a volume and return its properties."""
        return self.common.create_volume(volume)

    @utils.output_start_end_log
    def create_volume_from_snapshot(self, volume, snapshot):
        """Create a volume from a snapshot and return its properties."""
        return self.common.create_volume_from_snapshot(volume, snapshot)

    @utils.output_start_end_log
    def create_cloned_volume(self, volume, src_vref):
        """Create a clone of the specified volume and return its properties."""
        return self.common.create_cloned_volume(volume, src_vref)

    @utils.output_start_end_log
    def delete_volume(self, volume):
        """Delete the specified volume."""
        self.common.delete_volume(volume)

    @utils.output_start_end_log
    def create_snapshot(self, snapshot):
        """Create a snapshot from a volume and return its properties."""
        return self.common.create_snapshot(snapshot)

    @utils.output_start_end_log
    def delete_snapshot(self, snapshot):
        """Delete the specified snapshot."""
        self.common.delete_snapshot(snapshot)

    def get_volume_stats(self, refresh=False):
        """Return properties, capabilities and current states of the driver."""
        return self.common.get_volume_stats(refresh)

    @utils.output_start_end_log
    def update_migrated_volume(
            self, ctxt, volume, new_volume, original_volume_status):
        """Do any remaining jobs after migration."""
        self.common.discard_zero_page(new_volume)
        super(VSPISCSIDriver, self).update_migrated_volume(
            ctxt, volume, new_volume, original_volume_status)

    @utils.output_start_end_log
    def copy_image_to_volume(self, context, volume, image_service, image_id):
        """Fetch the image from image_service and write it to the volume."""
        super(VSPISCSIDriver, self).copy_image_to_volume(
            context, volume, image_service, image_id)
        self.common.discard_zero_page(volume)

    @utils.output_start_end_log
    def extend_volume(self, volume, new_size):
        """Extend the specified volume to the specified size."""
        self.common.extend_volume(volume, new_size)

    @utils.output_start_end_log
    def manage_existing(self, volume, existing_ref):
        """Return volume properties which Cinder needs to manage the volume."""
        return self.common.manage_existing(existing_ref)

    @utils.output_start_end_log
    def manage_existing_get_size(self, volume, existing_ref):
        """Return the size[GB] of the specified volume."""
        return self.common.manage_existing_get_size(existing_ref)

    @utils.output_start_end_log
    def unmanage(self, volume):
        """Prepare the volume for removing it from Cinder management."""
        self.common.unmanage(volume)

    @utils.output_start_end_log
    def do_setup(self, context):
        """Prepare for the startup of the driver."""
        self.common.do_setup(context)

    def ensure_export(self, context, volume):
        """Synchronously recreate an export for a volume."""
        pass

    def create_export(self, context, volume, connector):
        """Export the volume."""
        pass

    def remove_export(self, context, volume):
        """Remove an export for a volume."""
        pass

    @utils.output_start_end_log
    def initialize_connection(self, volume, connector):
        """Initialize connection between the server and the volume."""
        return self.common.initialize_connection(volume, connector)

    @utils.output_start_end_log
    def terminate_connection(self, volume, connector, **kwargs):
        """Terminate connection between the server and the volume."""
        self.common.terminate_connection(volume, connector)
