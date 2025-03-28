# Copyright (C) 2020, 2024, Hitachi, Ltd.
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
"""Fibre channel module for Hitachi HBSD Driver."""

import os

from oslo_utils import excutils

from cinder import interface
from cinder.volume import driver
from cinder.volume.drivers.hitachi import hbsd_common as common
from cinder.volume.drivers.hitachi import hbsd_replication as replication
from cinder.volume.drivers.hitachi import hbsd_rest as rest
from cinder.volume.drivers.hitachi import hbsd_rest_fc as rest_fc
from cinder.volume.drivers.hitachi import hbsd_utils as utils
from cinder.volume import volume_utils

MSG = utils.HBSDMsg

_DRIVER_INFO = {
    'version': utils.VERSION,
    'proto': 'FC',
    'hba_id': 'wwpns',
    'hba_id_type': 'World Wide Name',
    'msg_id': {
        'target': MSG.CREATE_HOST_GROUP_FAILED,
    },
    'volume_backend_name': '%(prefix)sFC' % {
        'prefix': utils.DRIVER_PREFIX,
    },
    'volume_type': 'fibre_channel',
    'param_prefix': utils.PARAM_PREFIX,
    'vendor_name': utils.VENDOR_NAME,
    'driver_dir_name': utils.DRIVER_DIR_NAME,
    'driver_prefix': utils.DRIVER_PREFIX,
    'driver_file_prefix': utils.DRIVER_FILE_PREFIX,
    'target_prefix': utils.TARGET_PREFIX,
    'hdp_vol_attr': utils.HDP_VOL_ATTR,
    'hdt_vol_attr': utils.HDT_VOL_ATTR,
    'nvol_ldev_type': utils.NVOL_LDEV_TYPE,
    'target_iqn_suffix': utils.TARGET_IQN_SUFFIX,
    'pair_attr': utils.PAIR_ATTR,
    'mirror_attr': utils.MIRROR_ATTR,
    'driver_impl_class': rest_fc.HBSDRESTFC,
}


@interface.volumedriver
class HBSDFCDriver(driver.FibreChannelDriver):
    """Fibre channel class for Hitachi HBSD Driver.

    Version history:

    .. code-block:: none

        1.0.0 - Initial driver.
        1.1.0 - Add manage_existing/manage_existing_get_size/unmanage methods
        2.0.0 - Major redesign of the driver. This version requires the REST
                API for communication with the storage backend.
        2.1.0 - Add Cinder generic volume groups.
        2.2.0 - Add maintenance parameters.
        2.2.1 - Make the parameters name variable for supporting OEM storages.
        2.2.2 - Add Target Port Assignment.
        2.2.3 - Add port scheduler.
        2.3.0 - Support multi pool.
        2.3.1 - Update retype and support storage assisted migration.
        2.3.2 - Add specifies format of the names HostGroups/iSCSI Targets.
        2.3.3 - Add GAD volume support.
        2.3.4 - Support data deduplication and compression.
        2.3.5 - Fix key error when backend is down.

    """

    VERSION = utils.VERSION

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = utils.CI_WIKI_NAME

    driver_info = dict(_DRIVER_INFO)

    def __init__(self, *args, **kwargs):
        """Initialize instance variables."""
        utils.output_log(MSG.DRIVER_INITIALIZATION_START,
                         driver=self.__class__.__name__,
                         version=self.get_version())
        super(HBSDFCDriver, self).__init__(*args, **kwargs)

        self.configuration.append_config_values(common.COMMON_VOLUME_OPTS)
        self.configuration.append_config_values(common.COMMON_PAIR_OPTS)
        self.configuration.append_config_values(common.COMMON_PORT_OPTS)
        self.configuration.append_config_values(common.COMMON_NAME_OPTS)
        self.configuration.append_config_values(rest_fc.FC_VOLUME_OPTS)
        self.configuration.append_config_values(
            replication.COMMON_MIRROR_OPTS)
        os.environ['LANG'] = 'C'
        kwargs.setdefault('driver_info', _DRIVER_INFO)
        self.driver_info = dict(kwargs['driver_info'])
        self.driver_info['driver_class'] = self.__class__
        if self.configuration.safe_get('hitachi_mirror_storage_id'):
            self.common = replication.HBSDREPLICATION(
                self.configuration, self.driver_info, kwargs.get('db'))
        elif not hasattr(self, '_init_common'):
            self.common = self.driver_info['driver_impl_class'](
                self.configuration, self.driver_info, kwargs.get('db'))
        else:
            self.common = self._init_common(
                self.configuration, kwargs.get('db'))

    @staticmethod
    def get_driver_options():
        additional_opts = HBSDFCDriver._get_oslo_driver_opts(
            *(common._INHERITED_VOLUME_OPTS +
              rest._REQUIRED_REST_OPTS +
              ['driver_ssl_cert_verify', 'driver_ssl_cert_path',
               'san_api_port', ]))
        return (common.COMMON_VOLUME_OPTS +
                common.COMMON_PORT_OPTS +
                common.COMMON_PAIR_OPTS +
                common.COMMON_NAME_OPTS +
                rest.REST_VOLUME_OPTS +
                rest.REST_PAIR_OPTS +
                rest_fc.FC_VOLUME_OPTS +
                replication._REP_OPTS +
                replication.COMMON_MIRROR_OPTS +
                replication.ISCSI_MIRROR_OPTS +
                replication.REST_MIRROR_OPTS +
                replication.REST_MIRROR_API_OPTS +
                replication.REST_MIRROR_SSL_OPTS +
                additional_opts)

    def check_for_setup_error(self):
        pass

    @volume_utils.trace
    def create_volume(self, volume):
        """Create a volume and return its properties."""
        return self.common.create_volume(volume)

    @volume_utils.trace
    def create_volume_from_snapshot(self, volume, snapshot):
        """Create a volume from a snapshot and return its properties."""
        return self.common.create_volume_from_snapshot(volume, snapshot)

    @volume_utils.trace
    def create_cloned_volume(self, volume, src_vref):
        """Create a clone of the specified volume and return its properties."""
        return self.common.create_cloned_volume(volume, src_vref)

    @volume_utils.trace
    def delete_volume(self, volume):
        """Delete the specified volume."""
        self.common.delete_volume(volume)

    @volume_utils.trace
    def create_snapshot(self, snapshot):
        """Create a snapshot from a volume and return its properties."""
        return self.common.create_snapshot(snapshot)

    @volume_utils.trace
    def delete_snapshot(self, snapshot):
        """Delete the specified snapshot."""
        self.common.delete_snapshot(snapshot)

    def local_path(self, volume):
        pass

    def _update_volume_stats(self):
        """Return properties, capabilities and current states of the driver."""
        data = self.common.update_volume_stats()
        if 'pools' in data:
            for pool in data['pools']:
                pool["filter_function"] = self.get_filter_function()
                pool["goodness_function"] = (
                    self.get_goodness_function())
        self._stats = data

    @volume_utils.trace
    def update_migrated_volume(
            self, ctxt, volume, new_volume, original_volume_status):
        """Do any remaining jobs after migration."""
        self.common.discard_zero_page(new_volume)
        return self.common.update_migrated_volume(new_volume)

    @volume_utils.trace
    def copy_image_to_volume(self, context, volume, image_service, image_id,
                             disable_sparse=False):
        """Fetch the image from image_service and write it to the volume."""
        super(HBSDFCDriver, self).copy_image_to_volume(
            context, volume, image_service, image_id,
            disable_sparse=disable_sparse)
        self.common.discard_zero_page(volume)

    @volume_utils.trace
    def extend_volume(self, volume, new_size):
        """Extend the specified volume to the specified size."""
        self.common.extend_volume(volume, new_size)

    @volume_utils.trace
    def manage_existing(self, volume, existing_ref):
        """Return volume properties which Cinder needs to manage the volume."""
        return self.common.manage_existing(volume, existing_ref)

    @volume_utils.trace
    def manage_existing_get_size(self, volume, existing_ref):
        """Return the size[GB] of the specified volume."""
        return self.common.manage_existing_get_size(volume, existing_ref)

    @volume_utils.trace
    def unmanage(self, volume):
        """Prepare the volume for removing it from Cinder management."""
        self.common.unmanage(volume)

    @volume_utils.trace
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

    def create_export_snapshot(self, context, snapshot, connector):
        pass

    def remove_export_snapshot(self, context, snapshot):
        pass

    @volume_utils.trace
    def initialize_connection(self, volume, connector):
        """Initialize connection between the server and the volume."""
        return self.common.initialize_connection(volume, connector)

    @volume_utils.trace
    def terminate_connection(self, volume, connector, **kwargs):
        """Terminate connection between the server and the volume."""
        if connector is None:
            connector = {}
        if utils.is_shared_connection(volume, connector):
            return
        self.common.terminate_connection(volume, connector)

    @volume_utils.trace
    def initialize_connection_snapshot(self, snapshot, connector, **kwargs):
        """Initialize connection between the server and the snapshot."""
        return self.common.initialize_connection(
            snapshot, connector, is_snapshot=True)

    @volume_utils.trace
    def terminate_connection_snapshot(self, snapshot, connector, **kwargs):
        """Terminate connection between the server and the snapshot."""
        self.common.terminate_connection(snapshot, connector)

    @volume_utils.trace
    def unmanage_snapshot(self, snapshot):
        """Prepare the snapshot for removing it from Cinder management."""
        return self.common.unmanage_snapshot(snapshot)

    @volume_utils.trace
    def retype(self, ctxt, volume, new_type, diff, host):
        """Retype the specified volume."""
        return self.common.retype(ctxt, volume, new_type, diff, host)

    @volume_utils.trace
    def migrate_volume(self, ctxt, volume, host):
        """Migrate the specified volume."""
        return self.common.migrate_volume(volume, host)

    def backup_use_temp_snapshot(self):
        return True

    @volume_utils.trace
    def revert_to_snapshot(self, context, volume, snapshot):
        """Rollback the specified snapshot"""
        return self.common.revert_to_snapshot(volume, snapshot)

    @volume_utils.trace
    def create_group(self, context, group):
        return self.common.create_group()

    @volume_utils.trace
    def delete_group(self, context, group, volumes):
        return self.common.delete_group(group, volumes)

    @volume_utils.trace
    def create_group_from_src(
            self, context, group, volumes, group_snapshot=None, snapshots=None,
            source_group=None, source_vols=None):
        return self.common.create_group_from_src(
            context, group, volumes, snapshots, source_vols)

    @volume_utils.trace
    def update_group(
            self, context, group, add_volumes=None, remove_volumes=None):
        try:
            return self.common.update_group(group, add_volumes)
        except Exception:
            with excutils.save_and_reraise_exception():
                for remove_volume in remove_volumes:
                    utils.cleanup_cg_in_volume(remove_volume)

    @volume_utils.trace
    def create_group_snapshot(self, context, group_snapshot, snapshots):
        return self.common.create_group_snapshot(
            context, group_snapshot, snapshots)

    @volume_utils.trace
    def delete_group_snapshot(self, context, group_snapshot, snapshots):
        return self.common.delete_group_snapshot(group_snapshot, snapshots)
