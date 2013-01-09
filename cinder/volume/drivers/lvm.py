# vim: tabstop=4 shiftwidth=4 softtabstop=4

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
import re

from cinder import exception
from cinder import flags
from cinder.image import image_utils
from cinder.openstack.common import cfg
from cinder.openstack.common import log as logging
from cinder import utils
from cinder.volume import driver
from cinder.volume import iscsi

LOG = logging.getLogger(__name__)

volume_opts = [
    cfg.StrOpt('volume_group',
               default='cinder-volumes',
               help='Name for the VG that will contain exported volumes'),
    cfg.IntOpt('lvm_mirrors',
               default=0,
               help='If set, create lvms with multiple mirrors. Note that '
                    'this requires lvm_mirrors + 2 pvs with available space'),
    cfg.IntOpt('iscsi_num_targets',
               default=100,
               help='Number of iscsi target ids per host'),
    cfg.StrOpt('iscsi_target_prefix',
               default='iqn.2010-10.org.openstack:',
               help='prefix for iscsi volumes'),
    cfg.StrOpt('iscsi_ip_address',
               default='$my_ip',
               help='The port that the iSCSI daemon is listening on'),
    cfg.IntOpt('iscsi_port',
               default=3260,
               help='The port that the iSCSI daemon is listening on'), ]

FLAGS = flags.FLAGS
FLAGS.register_opts(volume_opts)


class LVMVolumeDriver(driver.VolumeDriver):
    """Executes commands relating to Volumes."""
    def __init__(self, *args, **kwargs):
        super(LVMVolumeDriver, self).__init__(*args, **kwargs)

    def check_for_setup_error(self):
        """Returns an error if prerequisites aren't met"""
        out, err = self._execute('vgs', '--noheadings', '-o', 'name',
                                 run_as_root=True)
        volume_groups = out.split()
        if not FLAGS.volume_group in volume_groups:
            exception_message = (_("volume group %s doesn't exist")
                                 % FLAGS.volume_group)
            raise exception.VolumeBackendAPIException(data=exception_message)

    def _create_volume(self, volume_name, sizestr):
        cmd = ['lvcreate', '-L', sizestr, '-n', volume_name,
               FLAGS.volume_group]
        if FLAGS.lvm_mirrors:
            cmd += ['-m', FLAGS.lvm_mirrors, '--nosync']
            terras = int(sizestr[:-1]) / 1024.0
            if terras >= 1.5:
                rsize = int(2 ** math.ceil(math.log(terras) / math.log(2)))
                # NOTE(vish): Next power of two for region size. See:
                #             http://red.ht/U2BPOD
                cmd += ['-R', str(rsize)]

        self._try_execute(*cmd, run_as_root=True)

    def _copy_volume(self, srcstr, deststr, size_in_g):
        # Use O_DIRECT to avoid thrashing the system buffer cache
        direct_flags = ('iflag=direct', 'oflag=direct')

        # Check whether O_DIRECT is supported
        try:
            self._execute('dd', 'count=0', 'if=%s' % srcstr, 'of=%s' % deststr,
                          *direct_flags, run_as_root=True)
        except exception.ProcessExecutionError:
            direct_flags = ()

        # Perform the copy
        self._execute('dd', 'if=%s' % srcstr, 'of=%s' % deststr,
                      'count=%d' % (size_in_g * 1024), 'bs=1M',
                      *direct_flags, run_as_root=True)

    def _volume_not_present(self, volume_name):
        path_name = '%s/%s' % (FLAGS.volume_group, volume_name)
        try:
            self._try_execute('lvdisplay', path_name, run_as_root=True)
        except Exception as e:
            # If the volume isn't present
            return True
        return False

    def _delete_volume(self, volume, size_in_g):
        """Deletes a logical volume."""
        # zero out old volumes to prevent data leaking between users
        # TODO(ja): reclaiming space should be done lazy and low priority
        dev_path = self.local_path(volume)
        if FLAGS.secure_delete and os.path.exists(dev_path):
            LOG.info(_("Performing secure delete on volume: %s")
                     % volume['id'])
            self._copy_volume('/dev/zero', dev_path, size_in_g)

        self._try_execute('lvremove', '-f', "%s/%s" %
                          (FLAGS.volume_group,
                           self._escape_snapshot(volume['name'])),
                          run_as_root=True)

    def _sizestr(self, size_in_g):
        if int(size_in_g) == 0:
            return '100M'
        return '%sG' % size_in_g

    # Linux LVM reserves name that starts with snapshot, so that
    # such volume name can't be created. Mangle it.
    def _escape_snapshot(self, snapshot_name):
        if not snapshot_name.startswith('snapshot'):
            return snapshot_name
        return '_' + snapshot_name

    def create_volume(self, volume):
        """Creates a logical volume. Can optionally return a Dictionary of
        changes to the volume object to be persisted."""
        self._create_volume(volume['name'], self._sizestr(volume['size']))

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""
        self._create_volume(volume['name'], self._sizestr(volume['size']))
        self._copy_volume(self.local_path(snapshot), self.local_path(volume),
                          snapshot['volume_size'])

    def delete_volume(self, volume):
        """Deletes a logical volume."""
        if self._volume_not_present(volume['name']):
            # If the volume isn't present, then don't attempt to delete
            return True

        # TODO(yamahata): lvm can't delete origin volume only without
        # deleting derived snapshots. Can we do something fancy?
        out, err = self._execute('lvdisplay', '--noheading',
                                 '-C', '-o', 'Attr',
                                 '%s/%s' % (FLAGS.volume_group,
                                            volume['name']),
                                 run_as_root=True)
        # fake_execute returns None resulting unit test error
        if out:
            out = out.strip()
            if (out[0] == 'o') or (out[0] == 'O'):
                raise exception.VolumeIsBusy(volume_name=volume['name'])

        self._delete_volume(volume, volume['size'])

    def create_snapshot(self, snapshot):
        """Creates a snapshot."""
        orig_lv_name = "%s/%s" % (FLAGS.volume_group, snapshot['volume_name'])
        self._try_execute('lvcreate', '-L',
                          self._sizestr(snapshot['volume_size']),
                          '--name', self._escape_snapshot(snapshot['name']),
                          '--snapshot', orig_lv_name, run_as_root=True)

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        if self._volume_not_present(self._escape_snapshot(snapshot['name'])):
            # If the snapshot isn't present, then don't attempt to delete
            return True

        # TODO(yamahata): zeroing out the whole snapshot triggers COW.
        # it's quite slow.
        self._delete_volume(snapshot, snapshot['volume_size'])

    def local_path(self, volume):
        # NOTE(vish): stops deprecation warning
        escaped_group = FLAGS.volume_group.replace('-', '--')
        escaped_name = self._escape_snapshot(volume['name']).replace('-', '--')
        return "/dev/mapper/%s-%s" % (escaped_group, escaped_name)

    def copy_image_to_volume(self, context, volume, image_service, image_id):
        """Fetch the image from image_service and write it to the volume."""
        image_utils.fetch_to_raw(context,
                                 image_service,
                                 image_id,
                                 self.local_path(volume))

    def copy_volume_to_image(self, context, volume, image_service, image_id):
        """Copy the volume to the specified image."""
        volume_path = self.local_path(volume)
        with utils.temporary_chown(volume_path):
            with utils.file_open(volume_path) as volume_file:
                image_service.update(context, image_id, {}, volume_file)

    def clone_image(self, volume, image_location):
        return False


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
        self.tgtadm = iscsi.get_target_admin()
        super(LVMISCSIDriver, self).__init__(*args, **kwargs)

    def set_execute(self, execute):
        super(LVMISCSIDriver, self).set_execute(execute)
        self.tgtadm.set_execute(execute)

    def ensure_export(self, context, volume):
        """Synchronously recreates an export for a logical volume."""
        # NOTE(jdg): tgtadm doesn't use the iscsi_targets table
        # TODO(jdg): In the future move all of the dependent stuff into the
        # cooresponding target admin class
        if not isinstance(self.tgtadm, iscsi.TgtAdm):
            try:
                iscsi_target = self.db.volume_get_iscsi_target_num(
                    context,
                    volume['id'])
            except exception.NotFound:
                LOG.info(_("Skipping ensure_export. No iscsi_target "
                           "provisioned for volume: %s"), volume['id'])
                return
        else:
            iscsi_target = 1  # dummy value when using TgtAdm

        # Check for https://bugs.launchpad.net/cinder/+bug/1065702
        old_name = None
        volume_name = volume['name']
        if (volume['provider_location'] is not None and
                volume['name'] not in volume['provider_location']):

            msg = _('Detected inconsistency in provider_location id')
            LOG.debug(msg)
            old_name = self._fix_id_migration(context, volume)
            if 'in-use' in volume['status']:
                volume_name = old_name
                old_name = None

        iscsi_name = "%s%s" % (FLAGS.iscsi_target_prefix, volume_name)
        volume_path = "/dev/%s/%s" % (FLAGS.volume_group, volume_name)

        # NOTE(jdg): For TgtAdm case iscsi_name is the ONLY param we need
        # should clean this all up at some point in the future
        self.tgtadm.create_iscsi_target(iscsi_name, iscsi_target,
                                        0, volume_path,
                                        check_exit_code=False,
                                        old_name=old_name)

    def _fix_id_migration(self, context, volume):
        """Fix provider_location and dev files to address bug 1065702.

        For volumes that the provider_location has NOT been updated
        and are not currently in-use we'll create a new iscsi target
        and remove the persist file.

        If the volume is in-use, we'll just stick with the old name
        and when detach is called we'll feed back into ensure_export
        again if necessary and fix things up then.

        Details at: https://bugs.launchpad.net/cinder/+bug/1065702
        """

        model_update = {}
        pattern = re.compile(r":|\s")
        fields = pattern.split(volume['provider_location'])
        old_name = fields[3]

        volume['provider_location'] = \
            volume['provider_location'].replace(old_name, volume['name'])
        model_update['provider_location'] = volume['provider_location']

        self.db.volume_update(context, volume['id'], model_update)

        start = os.getcwd()
        os.chdir('/dev/%s' % FLAGS.volume_group)

        try:
            (out, err) = self._execute('readlink', old_name)
        except exception.ProcessExecutionError:
            link_path = '/dev/%s/%s' % (FLAGS.volume_group, old_name)
            LOG.debug(_('Symbolic link %s not found') % link_path)
            os.chdir(start)
            return

        rel_path = out.rstrip()
        self._execute('ln',
                      '-s',
                      rel_path, volume['name'],
                      run_as_root=True)
        os.chdir(start)
        return old_name

    def _ensure_iscsi_targets(self, context, host):
        """Ensure that target ids have been created in datastore."""
        # NOTE(jdg): tgtadm doesn't use the iscsi_targets table
        # TODO(jdg): In the future move all of the dependent stuff into the
        # cooresponding target admin class
        if not isinstance(self.tgtadm, iscsi.TgtAdm):
            host_iscsi_targets = self.db.iscsi_target_count_by_host(context,
                                                                    host)
            if host_iscsi_targets >= FLAGS.iscsi_num_targets:
                return

            # NOTE(vish): Target ids start at 1, not 0.
            for target_num in xrange(1, FLAGS.iscsi_num_targets + 1):
                target = {'host': host, 'target_num': target_num}
                self.db.iscsi_target_create_safe(context, target)

    def create_export(self, context, volume):
        """Creates an export for a logical volume."""

        iscsi_name = "%s%s" % (FLAGS.iscsi_target_prefix, volume['name'])
        volume_path = "/dev/%s/%s" % (FLAGS.volume_group, volume['name'])
        model_update = {}

        # TODO(jdg): In the future move all of the dependent stuff into the
        # cooresponding target admin class
        if not isinstance(self.tgtadm, iscsi.TgtAdm):
            lun = 0
            self._ensure_iscsi_targets(context, volume['host'])
            iscsi_target = self.db.volume_allocate_iscsi_target(context,
                                                                volume['id'],
                                                                volume['host'])
        else:
            lun = 1  # For tgtadm the controller is lun 0, dev starts at lun 1
            iscsi_target = 0  # NOTE(jdg): Not used by tgtadm

        # Use the same method to generate the username and the password.
        chap_username = utils.generate_username()
        chap_password = utils.generate_password()
        chap_auth = self._iscsi_authentication('IncomingUser', chap_username,
                                               chap_password)
        # NOTE(jdg): For TgtAdm case iscsi_name is the ONLY param we need
        # should clean this all up at some point in the future
        tid = self.tgtadm.create_iscsi_target(iscsi_name,
                                              iscsi_target,
                                              0,
                                              volume_path,
                                              chap_auth)
        model_update['provider_location'] = self._iscsi_location(
            FLAGS.iscsi_ip_address, tid, iscsi_name, lun)
        model_update['provider_auth'] = self._iscsi_authentication(
            'CHAP', chap_username, chap_password)
        return model_update

    def remove_export(self, context, volume):
        """Removes an export for a logical volume."""
        # NOTE(jdg): tgtadm doesn't use the iscsi_targets table
        # TODO(jdg): In the future move all of the dependent stuff into the
        # cooresponding target admin class
        if not isinstance(self.tgtadm, iscsi.TgtAdm):
            try:
                iscsi_target = self.db.volume_get_iscsi_target_num(
                    context,
                    volume['id'])
            except exception.NotFound:
                LOG.info(_("Skipping remove_export. No iscsi_target "
                           "provisioned for volume: %s"), volume['id'])
                return
        else:
            iscsi_target = 0

        try:

            # NOTE: provider_location may be unset if the volume hasn't
            # been exported
            location = volume['provider_location'].split(' ')
            iqn = location[1]

            # ietadm show will exit with an error
            # this export has already been removed
            self.tgtadm.show_target(iscsi_target, iqn=iqn)

        except Exception as e:
            LOG.info(_("Skipping remove_export. No iscsi_target "
                       "is presently exported for volume: %s"), volume['id'])
            return

        self.tgtadm.remove_iscsi_target(iscsi_target, 0, volume['id'])

    def get_volume_stats(self, refresh=False):
        """Get volume status.

        If 'refresh' is True, run update the stats first."""
        if refresh:
            self._update_volume_status()

        return self._stats

    def _update_volume_status(self):
        """Retrieve status info from volume group."""

        LOG.debug(_("Updating volume status"))
        data = {}

        # Note(zhiteng): These information are driver/backend specific,
        # each driver may define these values in its own config options
        # or fetch from driver specific configuration file.
        data["volume_backend_name"] = 'LVM_iSCSI'
        data["vendor_name"] = 'Open Source'
        data["driver_version"] = '1.0'
        data["storage_protocol"] = 'iSCSI'

        data['total_capacity_gb'] = 0
        data['free_capacity_gb'] = 0
        data['reserved_percentage'] = FLAGS.reserved_percentage
        data['QoS_support'] = False

        try:
            out, err = self._execute('vgs', '--noheadings', '--nosuffix',
                                     '--unit=G', '-o', 'name,size,free',
                                     FLAGS.volume_group, run_as_root=True)
        except exception.ProcessExecutionError as exc:
            LOG.error(_("Error retrieving volume status: "), exc.stderr)
            out = False

        if out:
            volume = out.split()
            data['total_capacity_gb'] = float(volume[1])
            data['free_capacity_gb'] = float(volume[2])

        self._stats = data

    def _iscsi_location(self, ip, target, iqn, lun=None):
        return "%s:%s,%s %s %s" % (ip, FLAGS.iscsi_port, target, iqn, lun)

    def _iscsi_authentication(self, chap, name, password):
        return "%s %s %s" % (chap, name, password)
