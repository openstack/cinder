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
Driver for Linux servers running LVM.

"""

import math
import os
import socket

from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import importutils
from oslo_utils import units
import six

from cinder.brick.local_dev import lvm
from cinder import exception
from cinder.i18n import _
from cinder.image import image_utils
from cinder import interface
from cinder import utils
from cinder.volume import configuration
from cinder.volume import driver
from cinder.volume import volume_utils

LOG = logging.getLogger(__name__)

# FIXME(jdg):  We'll put the lvm_ prefix back on these when we
# move over to using this as the real LVM driver, for now we'll
# rename them so that the config generation utility doesn't barf
# on duplicate entries.
volume_opts = [
    cfg.StrOpt('volume_group',
               default='cinder-volumes',
               help='Name for the VG that will contain exported volumes'),
    cfg.IntOpt('lvm_mirrors',
               default=0,
               help='If >0, create LVs with multiple mirrors. Note that '
                    'this requires lvm_mirrors + 2 PVs with available space'),
    cfg.StrOpt('lvm_type',
               default='auto',
               choices=[('default', 'Thick-provisioned LVM.'),
                        ('thin', 'Thin-provisioned LVM.'),
                        ('auto', 'Defaults to thin when supported.')],
               help='Type of LVM volumes to deploy; (default, thin, or auto). '
                    'Auto defaults to thin if thin is supported.'),
    cfg.StrOpt('lvm_conf_file',
               default='/etc/cinder/lvm.conf',
               help='LVM conf file to use for the LVM driver in Cinder; '
                    'this setting is ignored if the specified file does '
                    'not exist (You can also specify \'None\' to not use '
                    'a conf file even if one exists).'),
    cfg.BoolOpt('lvm_suppress_fd_warnings',
                default=False,
                help='Suppress leaked file descriptor warnings in LVM '
                     'commands.')
]

CONF = cfg.CONF
CONF.register_opts(volume_opts, group=configuration.SHARED_CONF_GROUP)


@interface.volumedriver
class LVMVolumeDriver(driver.VolumeDriver):
    """Executes commands relating to Volumes."""

    VERSION = '3.0.0'

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "Cinder_Jenkins"

    def __init__(self, vg_obj=None, *args, **kwargs):
        # Parent sets db, host, _execute and base config
        super(LVMVolumeDriver, self).__init__(*args, **kwargs)

        self.configuration.append_config_values(volume_opts)
        self.hostname = socket.gethostname()
        self.vg = vg_obj
        self.backend_name =\
            self.configuration.safe_get('volume_backend_name') or 'LVM'

        # Target Driver is what handles data-transport
        # Transport specific code should NOT be in
        # the driver (control path), this way
        # different target drivers can be added (iscsi, FC etc)
        target_driver = \
            self.target_mapping[self.configuration.safe_get('target_helper')]

        LOG.debug('Attempting to initialize LVM driver with the '
                  'following target_driver: %s',
                  target_driver)

        self.target_driver = importutils.import_object(
            target_driver,
            configuration=self.configuration,
            executor=self._execute)
        self.protocol = self.target_driver.protocol
        self._sparse_copy_volume = False

    @classmethod
    def get_driver_options(cls):
        # Imports required to have config options
        from cinder.volume.targets import spdknvmf  # noqa

        additional_opts = cls._get_oslo_driver_opts(
            'target_ip_address', 'target_helper', 'target_protocol',
            'volume_clear', 'volume_clear_size', 'reserved_percentage',
            'max_over_subscription_ratio', 'volume_dd_blocksize',
            'target_prefix', 'volumes_dir', 'iscsi_secondary_ip_addresses',
            'target_port',
            'iscsi_write_cache', 'iscsi_target_flags',  # TGT
            'iet_conf', 'iscsi_iotype',  # IET
            'nvmet_port_id',  # NVMET
            'scst_target_iqn_name', 'scst_target_driver',  # SCST
            'spdk_rpc_ip', 'spdk_rpc_port', 'spdk_rpc_username',   # SPDKNVMF
            'spdk_rpc_password', 'spdk_max_queue_depth',  # SPDKNVMF
        )
        return volume_opts + additional_opts

    def _sizestr(self, size_in_g):
        return '%sg' % size_in_g

    def _volume_not_present(self, volume_name):
        return self.vg.get_volume(volume_name) is None

    def _delete_volume(self, volume, is_snapshot=False):
        """Deletes a logical volume."""
        if self.configuration.volume_clear != 'none' and \
                self.configuration.lvm_type != 'thin':
            self._clear_volume(volume, is_snapshot)

        name = volume['name']
        if is_snapshot:
            name = self._escape_snapshot(volume['name'])
        self.vg.delete(name)

    def _clear_volume(self, volume, is_snapshot=False):
        # zero out old volumes to prevent data leaking between users
        # TODO(ja): reclaiming space should be done lazy and low priority
        if is_snapshot:
            # if the volume to be cleared is a snapshot of another volume
            # we need to clear out the volume using the -cow instead of the
            # directly volume path.  We need to skip this if we are using
            # thin provisioned LVs.
            # bug# lp1191812
            dev_path = self.local_path(volume) + "-cow"
        else:
            dev_path = self.local_path(volume)

        # TODO(jdg): Maybe we could optimize this for snaps by looking at
        # the cow table and only overwriting what's necessary?
        # for now we're still skipping on snaps due to hang issue
        if not os.path.exists(dev_path):
            msg = (_('Volume device file path %s does not exist.')
                   % dev_path)
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        size_in_g = (volume.get('volume_size') if is_snapshot
                     else volume.get('size'))
        if size_in_g is None:
            msg = (_("Size for volume: %s not found, cannot secure delete.")
                   % volume['id'])
            LOG.error(msg)
            raise exception.InvalidParameterValue(msg)

        # clear_volume expects sizes in MiB, we store integer GiB
        # be sure to convert before passing in
        vol_sz_in_meg = size_in_g * units.Ki

        volume_utils.clear_volume(
            vol_sz_in_meg, dev_path,
            volume_clear=self.configuration.volume_clear,
            volume_clear_size=self.configuration.volume_clear_size)

    def _escape_snapshot(self, snapshot_name):
        # Linux LVM reserves name that starts with snapshot, so that
        # such volume name can't be created. Mangle it.
        if not snapshot_name.startswith('snapshot'):
            return snapshot_name
        return '_' + snapshot_name

    def _unescape_snapshot(self, snapshot_name):
        # Undo snapshot name change done by _escape_snapshot()
        if not snapshot_name.startswith('_snapshot'):
            return snapshot_name
        return snapshot_name[1:]

    def _create_volume(self, name, size, lvm_type, mirror_count, vg=None):
        vg_ref = self.vg
        if vg is not None:
            vg_ref = vg

        vg_ref.create_volume(name, size, lvm_type, mirror_count)

    def _update_volume_stats(self):
        """Retrieve stats info from volume group."""

        LOG.debug("Updating volume stats")
        if self.vg is None:
            LOG.warning('Unable to update stats on non-initialized '
                        'Volume Group: %s',
                        self.configuration.volume_group)
            return

        self.vg.update_volume_group_info()
        data = {}

        # Note(zhiteng): These information are driver/backend specific,
        # each driver may define these values in its own config options
        # or fetch from driver specific configuration file.
        data["volume_backend_name"] = self.backend_name
        data["vendor_name"] = 'Open Source'
        data["driver_version"] = self.VERSION
        data["storage_protocol"] = self.protocol
        data["pools"] = []

        total_capacity = 0
        free_capacity = 0

        if self.configuration.lvm_mirrors > 0:
            total_capacity =\
                self.vg.vg_mirror_size(self.configuration.lvm_mirrors)
            free_capacity =\
                self.vg.vg_mirror_free_space(self.configuration.lvm_mirrors)
            provisioned_capacity = round(
                float(total_capacity) - float(free_capacity), 2)
        elif self.configuration.lvm_type == 'thin':
            total_capacity = self.vg.vg_thin_pool_size
            free_capacity = self.vg.vg_thin_pool_free_space
            provisioned_capacity = self.vg.vg_provisioned_capacity
        else:
            total_capacity = self.vg.vg_size
            free_capacity = self.vg.vg_free_space
            provisioned_capacity = round(
                float(total_capacity) - float(free_capacity), 2)

        location_info = \
            ('LVMVolumeDriver:%(hostname)s:%(vg)s'
             ':%(lvm_type)s:%(lvm_mirrors)s' %
             {'hostname': self.hostname,
              'vg': self.configuration.volume_group,
              'lvm_type': self.configuration.lvm_type,
              'lvm_mirrors': self.configuration.lvm_mirrors})

        thin_enabled = self.configuration.lvm_type == 'thin'

        # Calculate the total volumes used by the VG group.
        # This includes volumes and snapshots.
        total_volumes = len(self.vg.get_volumes())

        # Skip enabled_pools setting, treat the whole backend as one pool
        # XXX FIXME if multipool support is added to LVM driver.
        single_pool = {}
        single_pool.update(dict(
            pool_name=data["volume_backend_name"],
            total_capacity_gb=total_capacity,
            free_capacity_gb=free_capacity,
            reserved_percentage=self.configuration.reserved_percentage,
            location_info=location_info,
            QoS_support=False,
            provisioned_capacity_gb=provisioned_capacity,
            max_over_subscription_ratio=(
                self.configuration.max_over_subscription_ratio),
            thin_provisioning_support=thin_enabled,
            thick_provisioning_support=not thin_enabled,
            total_volumes=total_volumes,
            filter_function=self.get_filter_function(),
            goodness_function=self.get_goodness_function(),
            multiattach=True,
            backend_state='up'
        ))
        data["pools"].append(single_pool)
        data["shared_targets"] = False

        # Check availability of sparse volume copy.
        data['sparse_copy_volume'] = self._sparse_copy_volume

        self._stats = data

    def check_for_setup_error(self):
        """Verify that requirements are in place to use LVM driver."""
        if self.vg is None:
            root_helper = utils.get_root_helper()

            lvm_conf_file = self.configuration.lvm_conf_file
            if lvm_conf_file.lower() == 'none':
                lvm_conf_file = None

            try:
                lvm_type = self.configuration.lvm_type
                if lvm_type == 'auto':
                    if volume_utils.supports_thin_provisioning():
                        lvm_type = 'thin'
                    else:
                        lvm_type = 'default'
                self.vg = lvm.LVM(
                    self.configuration.volume_group,
                    root_helper,
                    lvm_type=lvm_type,
                    executor=self._execute,
                    lvm_conf=lvm_conf_file,
                    suppress_fd_warn=(
                        self.configuration.lvm_suppress_fd_warnings))

            except exception.VolumeGroupNotFound:
                message = (_("Volume Group %s does not exist") %
                           self.configuration.volume_group)
                raise exception.VolumeBackendAPIException(data=message)

        vg_list = volume_utils.get_all_volume_groups(
            self.configuration.volume_group)
        vg_dict = next(vg for vg in vg_list if vg['name'] == self.vg.vg_name)
        if vg_dict is None:
            message = (_("Volume Group %s does not exist") %
                       self.configuration.volume_group)
            raise exception.VolumeBackendAPIException(data=message)

        pool_name = "%s-pool" % self.configuration.volume_group

        if self.configuration.lvm_type == 'auto':
            # Default to thin provisioning if it is supported and
            # the volume group is empty, or contains a thin pool
            # for us to use.
            self.vg.update_volume_group_info()

            self.configuration.lvm_type = 'default'

            if volume_utils.supports_thin_provisioning():
                if self.vg.get_volume(pool_name) is not None:
                    LOG.info('Enabling LVM thin provisioning by default '
                             'because a thin pool exists.')
                    self.configuration.lvm_type = 'thin'
                elif len(self.vg.get_volumes()) == 0:
                    LOG.info('Enabling LVM thin provisioning by default '
                             'because no LVs exist.')
                    self.configuration.lvm_type = 'thin'

        if self.configuration.lvm_type == 'thin':
            # Specific checks for using Thin provisioned LV's
            if not volume_utils.supports_thin_provisioning():
                message = _("Thin provisioning not supported "
                            "on this version of LVM.")
                raise exception.VolumeBackendAPIException(data=message)

            if self.vg.get_volume(pool_name) is None:
                try:
                    self.vg.create_thin_pool(pool_name)
                except processutils.ProcessExecutionError as exc:
                    exception_message = (_("Failed to create thin pool, "
                                           "error message was: %s")
                                         % six.text_type(exc.stderr))
                    raise exception.VolumeBackendAPIException(
                        data=exception_message)

            # Enable sparse copy since lvm_type is 'thin'
            self._sparse_copy_volume = True

    def create_volume(self, volume):
        """Creates a logical volume."""
        mirror_count = 0
        if self.configuration.lvm_mirrors:
            mirror_count = self.configuration.lvm_mirrors

        self._create_volume(volume['name'],
                            self._sizestr(volume['size']),
                            self.configuration.lvm_type,
                            mirror_count)

    def update_migrated_volume(self, ctxt, volume, new_volume,
                               original_volume_status):
        """Return model update from LVM for migrated volume.

        This method should rename the back-end volume name(id) on the
        destination host back to its original name(id) on the source host.

        :param ctxt: The context used to run the method update_migrated_volume
        :param volume: The original volume that was migrated to this backend
        :param new_volume: The migration volume object that was created on
                           this backend as part of the migration process
        :param original_volume_status: The status of the original volume
        :returns: model_update to update DB with any needed changes
        """
        name_id = None
        provider_location = None
        if original_volume_status == 'available':
            current_name = CONF.volume_name_template % new_volume['id']
            original_volume_name = CONF.volume_name_template % volume['id']
            try:
                self.vg.rename_volume(current_name, original_volume_name)
            except processutils.ProcessExecutionError:
                LOG.error('Unable to rename the logical volume '
                          'for volume: %s', volume['id'])
                # If the rename fails, _name_id should be set to the new
                # volume id and provider_location should be set to the
                # one from the new volume as well.
                name_id = new_volume['_name_id'] or new_volume['id']
                provider_location = new_volume['provider_location']
        else:
            # The back-end will not be renamed.
            name_id = new_volume['_name_id'] or new_volume['id']
            provider_location = new_volume['provider_location']
        return {'_name_id': name_id, 'provider_location': provider_location}

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""
        if self.configuration.lvm_type == 'thin':
            self.vg.create_lv_snapshot(volume['name'],
                                       self._escape_snapshot(snapshot['name']),
                                       self.configuration.lvm_type)
            if volume['size'] > snapshot['volume_size']:
                LOG.debug("Resize the new volume to %s.", volume['size'])
                self.extend_volume(volume, volume['size'])
            # Some configurations of LVM do not automatically activate
            # ThinLVM snapshot LVs.
            self.vg.activate_lv(snapshot['name'], is_snapshot=True)
            self.vg.activate_lv(volume['name'], is_snapshot=True,
                                permanent=True)
            return
        self._create_volume(volume['name'],
                            self._sizestr(volume['size']),
                            self.configuration.lvm_type,
                            self.configuration.lvm_mirrors)

        # Some configurations of LVM do not automatically activate
        # ThinLVM snapshot LVs.
        self.vg.activate_lv(snapshot['name'], is_snapshot=True)

        # copy_volume expects sizes in MiB, we store integer GiB
        # be sure to convert before passing in
        volume_utils.copy_volume(self.local_path(snapshot),
                                 self.local_path(volume),
                                 snapshot['volume_size'] * units.Ki,
                                 self.configuration.volume_dd_blocksize,
                                 execute=self._execute,
                                 sparse=self._sparse_copy_volume)

    def delete_volume(self, volume):
        """Deletes a logical volume."""

        # NOTE(jdg):  We don't need to explicitly call
        # remove export here because we already did it
        # in the manager before we got here.

        if self._volume_not_present(volume['name']):
            # If the volume isn't present, then don't attempt to delete
            return True

        if self.vg.lv_has_snapshot(volume['name']):
            LOG.error('Unable to delete due to existing snapshot '
                      'for volume: %s', volume['name'])
            raise exception.VolumeIsBusy(volume_name=volume['name'])

        self._delete_volume(volume)
        LOG.info('Successfully deleted volume: %s', volume['id'])

    def create_snapshot(self, snapshot):
        """Creates a snapshot."""

        self.vg.create_lv_snapshot(self._escape_snapshot(snapshot['name']),
                                   snapshot['volume_name'],
                                   self.configuration.lvm_type)

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        if self._volume_not_present(self._escape_snapshot(snapshot['name'])):
            # If the snapshot isn't present, then don't attempt to delete
            LOG.warning("snapshot: %s not found, "
                        "skipping delete operations", snapshot['name'])
            LOG.info('Successfully deleted snapshot: %s', snapshot['id'])
            return True

        # TODO(yamahata): zeroing out the whole snapshot triggers COW.
        # it's quite slow.
        self._delete_volume(snapshot, is_snapshot=True)

    def revert_to_snapshot(self, context, volume, snapshot):
        """Revert a volume to a snapshot"""

        # NOTE(tommylikehu): We still can revert the volume because Cinder
        # will try the alternative approach if 'NotImplementedError'
        # is raised here.
        if self.configuration.lvm_type == 'thin':
            msg = _("Revert volume to snapshot not implemented for thin LVM.")
            raise NotImplementedError(msg)
        else:
            self.vg.revert(self._escape_snapshot(snapshot.name))
            self.vg.deactivate_lv(volume.name)
            self.vg.activate_lv(volume.name)
            # Recreate the snapshot that was destroyed by the revert
            self.create_snapshot(snapshot)

    def local_path(self, volume, vg=None):
        if vg is None:
            vg = self.configuration.volume_group
        # NOTE(vish): stops deprecation warning
        escaped_group = vg.replace('-', '--')
        escaped_name = self._escape_snapshot(volume['name']).replace('-', '--')
        return "/dev/mapper/%s-%s" % (escaped_group, escaped_name)

    def copy_image_to_volume(self, context, volume, image_service, image_id):
        """Fetch the image from image_service and write it to the volume."""
        image_utils.fetch_to_raw(context,
                                 image_service,
                                 image_id,
                                 self.local_path(volume),
                                 self.configuration.volume_dd_blocksize,
                                 size=volume['size'])

    def copy_volume_to_image(self, context, volume, image_service, image_meta):
        """Copy the volume to the specified image."""
        volume_utils.upload_volume(context,
                                   image_service,
                                   image_meta,
                                   self.local_path(volume),
                                   volume)

    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume."""
        if self.configuration.lvm_type == 'thin':
            self.vg.create_lv_snapshot(volume['name'],
                                       src_vref['name'],
                                       self.configuration.lvm_type)
            if volume['size'] > src_vref['size']:
                LOG.debug("Resize the new volume to %s.", volume['size'])
                self.extend_volume(volume, volume['size'])
            self.vg.activate_lv(volume['name'], is_snapshot=True,
                                permanent=True)
            return

        mirror_count = 0
        if self.configuration.lvm_mirrors:
            mirror_count = self.configuration.lvm_mirrors
        LOG.info('Creating clone of volume: %s', src_vref['id'])
        volume_name = src_vref['name']
        temp_id = 'tmp-snap-%s' % volume['id']
        temp_snapshot = {'volume_name': volume_name,
                         'size': src_vref['size'],
                         'volume_size': src_vref['size'],
                         'name': 'clone-snap-%s' % volume['id'],
                         'id': temp_id}

        self.create_snapshot(temp_snapshot)

        # copy_volume expects sizes in MiB, we store integer GiB
        # be sure to convert before passing in
        try:
            self._create_volume(volume['name'],
                                self._sizestr(volume['size']),
                                self.configuration.lvm_type,
                                mirror_count)

            self.vg.activate_lv(temp_snapshot['name'], is_snapshot=True)
            volume_utils.copy_volume(
                self.local_path(temp_snapshot),
                self.local_path(volume),
                src_vref['size'] * units.Ki,
                self.configuration.volume_dd_blocksize,
                execute=self._execute,
                sparse=self._sparse_copy_volume)
        finally:
            self.delete_snapshot(temp_snapshot)

    def clone_image(self, context, volume,
                    image_location, image_meta,
                    image_service):
        return None, False

    def extend_volume(self, volume, new_size):
        """Extend an existing volume's size."""
        self.vg.extend_volume(volume['name'],
                              self._sizestr(new_size))
        try:
            self.target_driver.extend_target(volume)
        except Exception:
            LOG.exception('Error extending target after volume resize.')
            raise exception.TargetUpdateFailed(volume_id=volume.id)

    def manage_existing(self, volume, existing_ref):
        """Manages an existing LV.

        Renames the LV to match the expected name for the volume.
        Error checking done by manage_existing_get_size is not repeated.
        """
        lv_name = existing_ref['source-name']
        self.vg.get_volume(lv_name)

        vol_id = volume_utils.extract_id_from_volume_name(lv_name)
        if volume_utils.check_already_managed_volume(vol_id):
            raise exception.ManageExistingAlreadyManaged(volume_ref=lv_name)

        # Attempt to rename the LV to match the OpenStack internal name.
        try:
            self.vg.rename_volume(lv_name, volume['name'])
        except processutils.ProcessExecutionError as exc:
            exception_message = (_("Failed to rename logical volume %(name)s, "
                                   "error message was: %(err_msg)s")
                                 % {'name': lv_name,
                                    'err_msg': exc.stderr})
            raise exception.VolumeBackendAPIException(
                data=exception_message)

    def manage_existing_object_get_size(self, existing_object, existing_ref,
                                        object_type):
        """Return size of an existing LV for manage existing volume/snapshot.

        existing_ref is a dictionary of the form:
        {'source-name': <name of LV>}
        """

        # Check that the reference is valid
        if 'source-name' not in existing_ref:
            reason = _('Reference must contain source-name element.')
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_ref, reason=reason)
        lv_name = existing_ref['source-name']
        lv = self.vg.get_volume(lv_name)

        # Raise an exception if we didn't find a suitable LV.
        if not lv:
            kwargs = {'existing_ref': lv_name,
                      'reason': 'Specified logical volume does not exist.'}
            raise exception.ManageExistingInvalidReference(**kwargs)

        # LV size is returned in gigabytes.  Attempt to parse size as a float
        # and round up to the next integer.
        try:
            lv_size = int(math.ceil(float(lv['size'])))
        except ValueError:
            exception_message = (_("Failed to manage existing %(type)s "
                                   "%(name)s, because reported size %(size)s "
                                   "was not a floating-point number.")
                                 % {'type': object_type,
                                    'name': lv_name,
                                    'size': lv['size']})
            raise exception.VolumeBackendAPIException(
                data=exception_message)
        return lv_size

    def manage_existing_get_size(self, volume, existing_ref):
        return self.manage_existing_object_get_size(volume, existing_ref,
                                                    "volume")

    def manage_existing_snapshot_get_size(self, snapshot, existing_ref):
        if not isinstance(existing_ref, dict):
            existing_ref = {"source-name": existing_ref}
        return self.manage_existing_object_get_size(snapshot, existing_ref,
                                                    "snapshot")

    def manage_existing_snapshot(self, snapshot, existing_ref):
        dest_name = self._escape_snapshot(snapshot['name'])
        snapshot_temp = {"name": dest_name}
        if not isinstance(existing_ref, dict):
            existing_ref = {"source-name": existing_ref}
        return self.manage_existing(snapshot_temp, existing_ref)

    def _get_manageable_resource_info(self, cinder_resources, resource_type,
                                      marker, limit, offset, sort_keys,
                                      sort_dirs):
        entries = []
        lvs = self.vg.get_volumes()
        cinder_ids = [resource['id'] for resource in cinder_resources]

        for lv in lvs:
            is_snap = self.vg.lv_is_snapshot(lv['name'])
            if ((resource_type == 'volume' and is_snap) or
                    (resource_type == 'snapshot' and not is_snap)):
                continue

            if resource_type == 'volume':
                potential_id = volume_utils.extract_id_from_volume_name(
                    lv['name'])
            else:
                unescape = self._unescape_snapshot(lv['name'])
                potential_id = volume_utils.extract_id_from_snapshot_name(
                    unescape)
            lv_info = {'reference': {'source-name': lv['name']},
                       'size': int(math.ceil(float(lv['size']))),
                       'cinder_id': None,
                       'extra_info': None}

            if potential_id in cinder_ids:
                lv_info['safe_to_manage'] = False
                lv_info['reason_not_safe'] = 'already managed'
                lv_info['cinder_id'] = potential_id
            elif self.vg.lv_is_open(lv['name']):
                lv_info['safe_to_manage'] = False
                lv_info['reason_not_safe'] = '%s in use' % resource_type
            else:
                lv_info['safe_to_manage'] = True
                lv_info['reason_not_safe'] = None

            if resource_type == 'snapshot':
                origin = self.vg.lv_get_origin(lv['name'])
                lv_info['source_reference'] = {'source-name': origin}

            entries.append(lv_info)

        return volume_utils.paginate_entries_list(entries, marker, limit,
                                                  offset, sort_keys, sort_dirs)

    def get_manageable_volumes(self, cinder_volumes, marker, limit, offset,
                               sort_keys, sort_dirs):
        return self._get_manageable_resource_info(cinder_volumes, 'volume',
                                                  marker, limit,
                                                  offset, sort_keys, sort_dirs)

    def get_manageable_snapshots(self, cinder_snapshots, marker, limit, offset,
                                 sort_keys, sort_dirs):
        return self._get_manageable_resource_info(cinder_snapshots, 'snapshot',
                                                  marker, limit,
                                                  offset, sort_keys, sort_dirs)

    def retype(self, context, volume, new_type, diff, host):
        """Retypes a volume, allow QoS and extra_specs change."""

        LOG.debug('LVM retype called for volume %s. No action '
                  'required for LVM volumes.',
                  volume['id'])
        return True

    def migrate_volume(self, ctxt, volume, host, thin=False, mirror_count=0):
        """Optimize the migration if the destination is on the same server.

        If the specified host is another back-end on the same server, and
        the volume is not attached, we can do the migration locally without
        going through iSCSI.
        """

        false_ret = (False, None)
        if volume['status'] != 'available':
            return false_ret
        if 'location_info' not in host['capabilities']:
            return false_ret
        info = host['capabilities']['location_info']
        try:
            (dest_type, dest_hostname, dest_vg, lvm_type, lvm_mirrors) =\
                info.split(':')
            lvm_mirrors = int(lvm_mirrors)
        except ValueError:
            return false_ret
        if (dest_type != 'LVMVolumeDriver' or dest_hostname != self.hostname):
            return false_ret

        if dest_vg == self.vg.vg_name:
            message = (_("Refusing to migrate volume ID: %(id)s. Please "
                         "check your configuration because source and "
                         "destination are the same Volume Group: %(name)s.") %
                       {'id': volume['id'], 'name': self.vg.vg_name})
            LOG.error(message)
            raise exception.VolumeBackendAPIException(data=message)

        vg_list = volume_utils.get_all_volume_groups()
        try:
            next(vg for vg in vg_list if vg['name'] == dest_vg)
        except StopIteration:
            LOG.error("Destination Volume Group %s does not exist",
                      dest_vg)
            return false_ret

        helper = utils.get_root_helper()

        lvm_conf_file = self.configuration.lvm_conf_file
        if lvm_conf_file.lower() == 'none':
            lvm_conf_file = None

        dest_vg_ref = lvm.LVM(dest_vg, helper,
                              lvm_type=lvm_type,
                              executor=self._execute,
                              lvm_conf=lvm_conf_file)

        self._create_volume(volume['name'],
                            self._sizestr(volume['size']),
                            lvm_type,
                            lvm_mirrors,
                            dest_vg_ref)
        # copy_volume expects sizes in MiB, we store integer GiB
        # be sure to convert before passing in
        size_in_mb = int(volume['size']) * units.Ki
        try:
            volume_utils.copy_volume(self.local_path(volume),
                                     self.local_path(volume, vg=dest_vg),
                                     size_in_mb,
                                     self.configuration.volume_dd_blocksize,
                                     execute=self._execute,
                                     sparse=self._sparse_copy_volume)
        except Exception as e:
            with excutils.save_and_reraise_exception():
                LOG.error("Volume migration failed due to "
                          "exception: %(reason)s.",
                          {'reason': six.text_type(e)}, resource=volume)
                dest_vg_ref.delete(volume)
        self._delete_volume(volume)
        return (True, None)

    def get_pool(self, volume):
        return self.backend_name

    # #######  Interface methods for DataPath (Target Driver) ########

    def ensure_export(self, context, volume):
        volume_path = "/dev/%s/%s" % (self.configuration.volume_group,
                                      volume['name'])

        self.vg.activate_lv(volume['name'])

        model_update = \
            self.target_driver.ensure_export(context, volume, volume_path)
        return model_update

    def create_export(self, context, volume, connector, vg=None):
        if vg is None:
            vg = self.configuration.volume_group

        volume_path = "/dev/%s/%s" % (vg, volume['name'])

        self.vg.activate_lv(volume['name'])

        export_info = self.target_driver.create_export(
            context,
            volume,
            volume_path)
        return {'provider_location': export_info['location'],
                'provider_auth': export_info['auth'], }

    def remove_export(self, context, volume):
        self.target_driver.remove_export(context, volume)

    def initialize_connection(self, volume, connector):
        return self.target_driver.initialize_connection(volume, connector)

    def validate_connector(self, connector):
        return self.target_driver.validate_connector(connector)

    def terminate_connection(self, volume, connector, **kwargs):
        # NOTE(jdg):  LVM has a single export for each volume, so what
        # we need to do here is check if there is more than one attachment for
        # the volume, if there is; let the caller know that they should NOT
        # remove the export.
        # NOTE(jdg): For the TGT driver this is a noop, for LIO this removes
        # the initiator IQN from the targets access list, so we're good
        # NOTE(lyarwood): Given the above note we should only call
        # terminate_connection for the target lioadm driver when there is only
        # one attachment left for the host specified by the connector to
        # remove, otherwise the ACL will be removed prematurely while other
        # attachments on the same host are still accessing the volume.
        attachments = volume.volume_attachment
        if volume.multiattach:
            if sum(1 for a in attachments if a.connector and
                    a.connector['initiator'] == connector['initiator']) > 1:
                return True

        self.target_driver.terminate_connection(volume, connector, **kwargs)
        return len(attachments) > 1
