# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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
Driver for Linux servers running LVM.

"""

import math
import os
import socket

from oslo.config import cfg

from cinder.brick import exception as brick_exception
from cinder.brick.local_dev import lvm as lvm
from cinder import exception
from cinder.i18n import _
from cinder.image import image_utils
from cinder.openstack.common import fileutils
from cinder.openstack.common import log as logging
from cinder.openstack.common import processutils
from cinder.openstack.common import units
from cinder import utils
from cinder.volume import driver
from cinder.volume import utils as volutils

LOG = logging.getLogger(__name__)

volume_opts = [
    cfg.StrOpt('volume_group',
               default='cinder-volumes',
               help='Name for the VG that will contain exported volumes'),
    cfg.IntOpt('lvm_mirrors',
               default=0,
               help='If >0, create LVs with multiple mirrors. Note that '
                    'this requires lvm_mirrors + 2 PVs with available space'),
    cfg.StrOpt('lvm_type',
               default='default',
               help='Type of LVM volumes to deploy; (default or thin)'),
]

CONF = cfg.CONF
CONF.register_opts(volume_opts)


class LVMVolumeDriver(driver.VolumeDriver):
    """Executes commands relating to Volumes."""

    VERSION = '2.0.0'

    def __init__(self, vg_obj=None, *args, **kwargs):
        super(LVMVolumeDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(volume_opts)
        self.hostname = socket.gethostname()
        self.vg = vg_obj
        self.backend_name =\
            self.configuration.safe_get('volume_backend_name') or 'LVM'
        self.protocol = 'local'

    def set_execute(self, execute):
        self._execute = execute

    def check_for_setup_error(self):
        """Verify that requirements are in place to use LVM driver."""
        if self.vg is None:
            root_helper = utils.get_root_helper()
            try:
                self.vg = lvm.LVM(self.configuration.volume_group,
                                  root_helper,
                                  lvm_type=self.configuration.lvm_type,
                                  executor=self._execute)
            except brick_exception.VolumeGroupNotFound:
                message = ("Volume Group %s does not exist" %
                           self.configuration.volume_group)
                raise exception.VolumeBackendAPIException(data=message)

        vg_list = volutils.get_all_volume_groups(
            self.configuration.volume_group)
        vg_dict = \
            (vg for vg in vg_list if vg['name'] == self.vg.vg_name).next()
        if vg_dict is None:
            message = ("Volume Group %s does not exist" %
                       self.configuration.volume_group)
            raise exception.VolumeBackendAPIException(data=message)

        if self.configuration.lvm_type == 'thin':
            # Specific checks for using Thin provisioned LV's
            if not volutils.supports_thin_provisioning():
                message = ("Thin provisioning not supported "
                           "on this version of LVM.")
                raise exception.VolumeBackendAPIException(data=message)

            pool_name = "%s-pool" % self.configuration.volume_group
            if self.vg.get_volume(pool_name) is None:
                try:
                    self.vg.create_thin_pool(pool_name)
                except processutils.ProcessExecutionError as exc:
                    exception_message = ("Failed to create thin pool, "
                                         "error message was: %s"
                                         % exc.stderr)
                    raise exception.VolumeBackendAPIException(
                        data=exception_message)

    def _sizestr(self, size_in_g):
        if int(size_in_g) == 0:
            return '100m'
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

        size_in_g = volume.get('size', volume.get('volume_size', None))
        if size_in_g is None:
            msg = (_("Size for volume: %s not found, "
                     "cannot secure delete.") % volume['id'])
            LOG.error(msg)
            raise exception.InvalidParameterValue(msg)

        # clear_volume expects sizes in MiB, we store integer GiB
        # be sure to convert before passing in
        vol_sz_in_meg = size_in_g * units.Ki

        volutils.clear_volume(
            vol_sz_in_meg, dev_path,
            volume_clear=self.configuration.volume_clear,
            volume_clear_size=self.configuration.volume_clear_size)

    def _escape_snapshot(self, snapshot_name):
        # Linux LVM reserves name that starts with snapshot, so that
        # such volume name can't be created. Mangle it.
        if not snapshot_name.startswith('snapshot'):
            return snapshot_name
        return '_' + snapshot_name

    def _create_volume(self, name, size, lvm_type, mirror_count, vg=None):
        vg_ref = self.vg
        if vg is not None:
            vg_ref = vg

        vg_ref.create_volume(name, size, lvm_type, mirror_count)

    def create_volume(self, volume):
        """Creates a logical volume."""
        mirror_count = 0
        if self.configuration.lvm_mirrors:
            mirror_count = self.configuration.lvm_mirrors

        self._create_volume(volume['name'],
                            self._sizestr(volume['size']),
                            self.configuration.lvm_type,
                            mirror_count)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""
        self._create_volume(volume['name'],
                            self._sizestr(volume['size']),
                            self.configuration.lvm_type,
                            self.configuration.lvm_mirrors)

        # Some configurations of LVM do not automatically activate
        # ThinLVM snapshot LVs.
        self.vg.activate_lv(snapshot['name'], is_snapshot=True)

        # copy_volume expects sizes in MiB, we store integer GiB
        # be sure to convert before passing in
        volutils.copy_volume(self.local_path(snapshot),
                             self.local_path(volume),
                             snapshot['volume_size'] * units.Ki,
                             self.configuration.volume_dd_blocksize,
                             execute=self._execute)

    def delete_volume(self, volume):
        """Deletes a logical volume."""

        # NOTE(jdg):  We don't need to explicitly call
        # remove export here because we already did it
        # in the manager before we got here.

        if self._volume_not_present(volume['name']):
            # If the volume isn't present, then don't attempt to delete
            return True

        if self.vg.lv_has_snapshot(volume['name']):
            LOG.error(_('Unabled to delete due to existing snapshot '
                        'for volume: %s') % volume['name'])
            raise exception.VolumeIsBusy(volume_name=volume['name'])

        self._delete_volume(volume)

    def create_snapshot(self, snapshot):
        """Creates a snapshot."""

        self.vg.create_lv_snapshot(self._escape_snapshot(snapshot['name']),
                                   snapshot['volume_name'],
                                   self.configuration.lvm_type)

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        if self._volume_not_present(self._escape_snapshot(snapshot['name'])):
            # If the snapshot isn't present, then don't attempt to delete
            LOG.warning(_("snapshot: %s not found, "
                          "skipping delete operations") % snapshot['name'])
            return True

        # TODO(yamahata): zeroing out the whole snapshot triggers COW.
        # it's quite slow.
        self._delete_volume(snapshot, is_snapshot=True)

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
        image_utils.upload_volume(context,
                                  image_service,
                                  image_meta,
                                  self.local_path(volume))

    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume."""

        mirror_count = 0
        if self.configuration.lvm_mirrors:
            mirror_count = self.configuration.lvm_mirrors
        LOG.info(_('Creating clone of volume: %s') % src_vref['id'])
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

            volutils.copy_volume(
                self.local_path(temp_snapshot),
                self.local_path(volume),
                src_vref['size'] * units.Ki,
                self.configuration.volume_dd_blocksize,
                execute=self._execute)
        finally:
            self.delete_snapshot(temp_snapshot)

    def clone_image(self, volume, image_location, image_id, image_meta):
        return None, False

    def backup_volume(self, context, backup, backup_service):
        """Create a new backup from an existing volume."""
        volume = self.db.volume_get(context, backup['volume_id'])
        volume_path = self.local_path(volume)
        with utils.temporary_chown(volume_path):
            with fileutils.file_open(volume_path) as volume_file:
                backup_service.backup(backup, volume_file)

    def restore_backup(self, context, backup, volume, backup_service):
        """Restore an existing backup to a new or existing volume."""
        volume_path = self.local_path(volume)
        with utils.temporary_chown(volume_path):
            with fileutils.file_open(volume_path, 'wb') as volume_file:
                backup_service.restore(backup, volume['id'], volume_file)

    def get_volume_stats(self, refresh=False):
        """Get volume status.

        If 'refresh' is True, run update the stats first.
        """

        if refresh:
            self._update_volume_stats()

        return self._stats

    def _update_volume_stats(self):
        """Retrieve stats info from volume group."""

        LOG.debug("Updating volume stats")
        if self.vg is None:
            LOG.warning(_('Unable to update stats on non-initialized '
                          'Volume Group: %s'), self.configuration.volume_group)
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
            total_capacity = \
                self.vg.vg_mirror_size(self.configuration.lvm_mirrors)
            free_capacity = \
                self.vg.vg_mirror_free_space(self.configuration.lvm_mirrors)
        elif self.configuration.lvm_type == 'thin':
            total_capacity = self.vg.vg_thin_pool_size
            free_capacity = self.vg.vg_thin_pool_free_space
        else:
            total_capacity = self.vg.vg_size
            free_capacity = self.vg.vg_free_space

        location_info = \
            ('LVMVolumeDriver:%(hostname)s:%(vg)s'
             ':%(lvm_type)s:%(lvm_mirrors)s' %
             {'hostname': self.hostname,
              'vg': self.configuration.volume_group,
              'lvm_type': self.configuration.lvm_type,
              'lvm_mirrors': self.configuration.lvm_mirrors})

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
        ))
        data["pools"].append(single_pool)

        self._stats = data

    def extend_volume(self, volume, new_size):
        """Extend an existing volume's size."""
        self.vg.extend_volume(volume['name'],
                              self._sizestr(new_size))

    def manage_existing(self, volume, existing_ref):
        """Manages an existing LV.

        Renames the LV to match the expected name for the volume.
        Error checking done by manage_existing_get_size is not repeated.
        """
        lv_name = existing_ref['source-name']
        self.vg.get_volume(lv_name)

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

    def manage_existing_get_size(self, volume, existing_ref):
        """Return size of an existing LV for manage_existing.

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
            exception_message = (_("Failed to manage existing volume "
                                   "%(name)s, because reported size %(size)s "
                                   "was not a floating-point number.")
                                 % {'name': lv_name,
                                    'size': lv['size']})
            raise exception.VolumeBackendAPIException(
                data=exception_message)
        return lv_size

    def get_pool(self, volume):
        return self.backend_name


class LVMISCSIDriver(LVMVolumeDriver, driver.ISCSIDriver):
    """Executes commands relating to ISCSI volumes.

    We make use of model provider properties as follows:

    ``provider_location``
      if present, contains the iSCSI target information in the same
      format as an ietadm discovery
      i.e. '<ip>:<port>,<portal> <target IQN>'

    ``provider_auth``
      if present, contains a space-separated triple:
      '<auth method> <auth username> <auth password>'.
      `CHAP` is the only auth_method in use at the moment.
    """

    def __init__(self, *args, **kwargs):
        self.db = kwargs.get('db')
        self.target_helper = self.get_target_helper(self.db)
        super(LVMISCSIDriver, self).__init__(*args, **kwargs)
        self.backend_name =\
            self.configuration.safe_get('volume_backend_name') or 'LVM_iSCSI'
        self.protocol = 'iSCSI'

    def set_execute(self, execute):
        super(LVMISCSIDriver, self).set_execute(execute)
        if self.target_helper is not None:
            self.target_helper.set_execute(execute)

    def _create_target(self, iscsi_name, iscsi_target,
                       volume_path, chap_auth, lun=0,
                       check_exit_code=False, old_name=None):
        # NOTE(jdg): tgt driver has an issue where with a lot of activity
        # (or sometimes just randomly) it will get *confused* and attempt
        # to reuse a target ID, resulting in a target already exists error
        # Typically a simple retry will address this

        # For now we have this while loop, might be useful in the
        # future to throw a retry decorator in common or utils
        attempts = 2
        while attempts > 0:
            attempts -= 1
            try:
                # NOTE(jdg): For TgtAdm case iscsi_name is all we need
                # should clean this all up at some point in the future

                tid = self.target_helper.create_iscsi_target(
                    iscsi_name,
                    iscsi_target,
                    0,
                    volume_path,
                    chap_auth,
                    check_exit_code=check_exit_code,
                    old_name=old_name)
                break

            except brick_exception.ISCSITargetCreateFailed:
                if attempts == 0:
                    raise
                else:
                    LOG.warning(_('Error creating iSCSI target, retrying '
                                  'creation for target: %s') % iscsi_name)
        return tid

    def ensure_export(self, context, volume):
        volume_name = volume['name']
        iscsi_name = "%s%s" % (self.configuration.iscsi_target_prefix,
                               volume_name)
        volume_path = "/dev/%s/%s" % (self.configuration.volume_group,
                                      volume_name)
        # NOTE(jdg): For TgtAdm case iscsi_name is the ONLY param we need
        # should clean this all up at some point in the future
        model_update = self.target_helper.ensure_export(
            context, volume,
            iscsi_name,
            volume_path,
            self.configuration.volume_group,
            self.configuration)
        if model_update:
            self.db.volume_update(context, volume['id'], model_update)

    def create_export(self, context, volume):
        return self._create_export(context, volume)

    def _create_export(self, context, volume, vg=None):
        """Creates an export for a logical volume."""
        if vg is None:
            vg = self.configuration.volume_group

        volume_path = "/dev/%s/%s" % (vg, volume['name'])

        data = self.target_helper.create_export(context,
                                                volume,
                                                volume_path,
                                                self.configuration)
        return {
            'provider_location': data['location'],
            'provider_auth': data['auth'],
        }

    def remove_export(self, context, volume):
        self.target_helper.remove_export(context, volume)

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

        if dest_vg != self.vg.vg_name:
            vg_list = volutils.get_all_volume_groups()
            try:
                (vg for vg in vg_list if vg['name'] == dest_vg).next()
            except StopIteration:
                message = (_("Destination Volume Group %s does not exist") %
                           dest_vg)
                LOG.error(message)
                return false_ret

            helper = utils.get_root_helper()
            dest_vg_ref = lvm.LVM(dest_vg, helper,
                                  lvm_type=lvm_type,
                                  executor=self._execute)
            self.remove_export(ctxt, volume)
            self._create_volume(volume['name'],
                                self._sizestr(volume['size']),
                                lvm_type,
                                lvm_mirrors,
                                dest_vg_ref)

        volutils.copy_volume(self.local_path(volume),
                             self.local_path(volume, vg=dest_vg),
                             volume['size'],
                             self.configuration.volume_dd_blocksize,
                             execute=self._execute)
        self._delete_volume(volume)
        model_update = self._create_export(ctxt, volume, vg=dest_vg)

        return (True, model_update)

    def _iscsi_location(self, ip, target, iqn, lun=None):
        return "%s:%s,%s %s %s" % (ip, self.configuration.iscsi_port,
                                   target, iqn, lun)

    def _iscsi_authentication(self, chap, name, password):
        return "%s %s %s" % (chap, name, password)


class LVMISERDriver(LVMISCSIDriver, driver.ISERDriver):
    """Executes commands relating to ISER volumes.

    We make use of model provider properties as follows:

    ``provider_location``
      if present, contains the iSER target information in the same
      format as an ietadm discovery
      i.e. '<ip>:<port>,<portal> <target IQN>'

    ``provider_auth``
      if present, contains a space-separated triple:
      '<auth method> <auth username> <auth password>'.
      `CHAP` is the only auth_method in use at the moment.
    """

    def __init__(self, *args, **kwargs):
        self.target_helper = self.get_target_helper(kwargs.get('db'))
        LVMVolumeDriver.__init__(self, *args, **kwargs)
        self.backend_name =\
            self.configuration.safe_get('volume_backend_name') or 'LVM_iSER'
        self.protocol = 'iSER'
