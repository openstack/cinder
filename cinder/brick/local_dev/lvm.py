# Copyright 2013 OpenStack Foundation.
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
LVM class for performing LVM operations.
"""

import itertools
import math
import os
import re

from os_brick import executor
from oslo_concurrency import processutils as putils
from oslo_log import log as logging
from oslo_utils import excutils

from cinder import exception
from cinder.i18n import _LE, _LI
from cinder import utils


LOG = logging.getLogger(__name__)


class LVM(executor.Executor):
    """LVM object to enable various LVM related operations."""
    LVM_CMD_PREFIX = ['env', 'LC_ALL=C']

    def __init__(self, vg_name, root_helper, create_vg=False,
                 physical_volumes=None, lvm_type='default',
                 executor=putils.execute, lvm_conf=None):

        """Initialize the LVM object.

        The LVM object is based on an LVM VolumeGroup, one instantiation
        for each VolumeGroup you have/use.

        :param vg_name: Name of existing VG or VG to create
        :param root_helper: Execution root_helper method to use
        :param create_vg: Indicates the VG doesn't exist
                          and we want to create it
        :param physical_volumes: List of PVs to build VG on
        :param lvm_type: VG and Volume type (default, or thin)
        :param executor: Execute method to use, None uses common/processutils

        """
        super(LVM, self).__init__(execute=executor, root_helper=root_helper)
        self.vg_name = vg_name
        self.pv_list = []
        self.vg_size = 0.0
        self.vg_free_space = 0.0
        self.vg_lv_count = 0
        self.vg_uuid = None
        self.vg_thin_pool = None
        self.vg_thin_pool_size = 0.0
        self.vg_thin_pool_free_space = 0.0
        self._supports_snapshot_lv_activation = None
        self._supports_lvchange_ignoreskipactivation = None
        self.vg_provisioned_capacity = 0.0

        if create_vg and physical_volumes is not None:
            self.pv_list = physical_volumes

            try:
                self._create_vg(physical_volumes)
            except putils.ProcessExecutionError as err:
                LOG.exception(_LE('Error creating Volume Group'))
                LOG.error(_LE('Cmd     :%s'), err.cmd)
                LOG.error(_LE('StdOut  :%s'), err.stdout)
                LOG.error(_LE('StdErr  :%s'), err.stderr)
                raise exception.VolumeGroupCreationFailed(vg_name=self.vg_name)

        if self._vg_exists() is False:
            LOG.error(_LE('Unable to locate Volume Group %s'), vg_name)
            raise exception.VolumeGroupNotFound(vg_name=vg_name)

        # NOTE: we assume that the VG has been activated outside of Cinder

        if lvm_type == 'thin':
            pool_name = "%s-pool" % self.vg_name
            if self.get_volume(pool_name) is None:
                try:
                    self.create_thin_pool(pool_name)
                except putils.ProcessExecutionError:
                    # Maybe we just lost the race against another copy of
                    # this driver being in init in parallel - e.g.
                    # cinder-volume and cinder-backup starting in parallel
                    if self.get_volume(pool_name) is None:
                        raise

            self.vg_thin_pool = pool_name
            self.activate_lv(self.vg_thin_pool)
        self.pv_list = self.get_all_physical_volumes(root_helper, vg_name)
        if lvm_conf and os.path.isfile(lvm_conf):
            LVM.LVM_CMD_PREFIX = ['env',
                                  'LC_ALL=C',
                                  'LVM_SYSTEM_DIR=/etc/cinder']

    def _vg_exists(self):
        """Simple check to see if VG exists.

        :returns: True if vg specified in object exists, else False

        """
        exists = False
        cmd = LVM.LVM_CMD_PREFIX + ['vgs', '--noheadings',
                                    '-o', 'name', self.vg_name]
        (out, _err) = self._execute(*cmd,
                                    root_helper=self._root_helper,
                                    run_as_root=True)

        if out is not None:
            volume_groups = out.split()
            if self.vg_name in volume_groups:
                exists = True

        return exists

    def _create_vg(self, pv_list):
        cmd = ['vgcreate', self.vg_name, ','.join(pv_list)]
        self._execute(*cmd, root_helper=self._root_helper, run_as_root=True)

    def _get_vg_uuid(self):
        cmd = LVM.LVM_CMD_PREFIX + ['vgs', '--noheadings',
                                    '-o', 'uuid', self.vg_name]
        (out, _err) = self._execute(*cmd,
                                    root_helper=self._root_helper,
                                    run_as_root=True)
        if out is not None:
            return out.split()
        else:
            return []

    def _get_thin_pool_free_space(self, vg_name, thin_pool_name):
        """Returns available thin pool free space.

        :param vg_name: the vg where the pool is placed
        :param thin_pool_name: the thin pool to gather info for
        :returns: Free space in GB (float), calculated using data_percent

        """
        cmd = LVM.LVM_CMD_PREFIX +\
            ['lvs', '--noheadings', '--unit=g',
             '-o', 'size,data_percent', '--separator',
             ':', '--nosuffix']
        # NOTE(gfidente): data_percent only applies to some types of LV so we
        # make sure to append the actual thin pool name
        cmd.append("/dev/%s/%s" % (vg_name, thin_pool_name))

        free_space = 0.0

        try:
            (out, err) = self._execute(*cmd,
                                       root_helper=self._root_helper,
                                       run_as_root=True)
            if out is not None:
                out = out.strip()
                data = out.split(':')
                pool_size = float(data[0])
                data_percent = float(data[1])
                consumed_space = pool_size / 100 * data_percent
                free_space = pool_size - consumed_space
                free_space = round(free_space, 2)
        except putils.ProcessExecutionError as err:
            LOG.exception(_LE('Error querying thin pool about data_percent'))
            LOG.error(_LE('Cmd     :%s'), err.cmd)
            LOG.error(_LE('StdOut  :%s'), err.stdout)
            LOG.error(_LE('StdErr  :%s'), err.stderr)

        return free_space

    @staticmethod
    def get_lvm_version(root_helper):
        """Static method to get LVM version from system.

        :param root_helper: root_helper to use for execute
        :returns: version 3-tuple

        """

        cmd = LVM.LVM_CMD_PREFIX + ['vgs', '--version']
        (out, _err) = putils.execute(*cmd,
                                     root_helper=root_helper,
                                     run_as_root=True)
        lines = out.split('\n')

        for line in lines:
            if 'LVM version' in line:
                version_list = line.split()
                # NOTE(gfidente): version is formatted as follows:
                # major.minor.patchlevel(library API version)[-customisation]
                version = version_list[2]
                version_filter = r"(\d+)\.(\d+)\.(\d+).*"
                r = re.search(version_filter, version)
                version_tuple = tuple(map(int, r.group(1, 2, 3)))
                return version_tuple

    @staticmethod
    def supports_thin_provisioning(root_helper):
        """Static method to check for thin LVM support on a system.

        :param root_helper: root_helper to use for execute
        :returns: True if supported, False otherwise

        """

        return LVM.get_lvm_version(root_helper) >= (2, 2, 95)

    @property
    def supports_snapshot_lv_activation(self):
        """Property indicating whether snap activation changes are supported.

        Check for LVM version >= 2.02.91.
        (LVM2 git: e8a40f6 Allow to activate snapshot)

        :returns: True/False indicating support
        """

        if self._supports_snapshot_lv_activation is not None:
            return self._supports_snapshot_lv_activation

        self._supports_snapshot_lv_activation = (
            self.get_lvm_version(self._root_helper) >= (2, 2, 91))

        return self._supports_snapshot_lv_activation

    @property
    def supports_lvchange_ignoreskipactivation(self):
        """Property indicating whether lvchange can ignore skip activation.

        Check for LVM version >= 2.02.99.
        (LVM2 git: ab789c1bc add --ignoreactivationskip to lvchange)
        """

        if self._supports_lvchange_ignoreskipactivation is not None:
            return self._supports_lvchange_ignoreskipactivation

        self._supports_lvchange_ignoreskipactivation = (
            self.get_lvm_version(self._root_helper) >= (2, 2, 99))

        return self._supports_lvchange_ignoreskipactivation

    @staticmethod
    def get_lv_info(root_helper, vg_name=None, lv_name=None):
        """Retrieve info about LVs (all, in a VG, or a single LV).

        :param root_helper: root_helper to use for execute
        :param vg_name: optional, gathers info for only the specified VG
        :param lv_name: optional, gathers info for only the specified LV
        :returns: List of Dictionaries with LV info

        """

        cmd = LVM.LVM_CMD_PREFIX + ['lvs', '--noheadings', '--unit=g',
                                    '-o', 'vg_name,name,size', '--nosuffix']
        if lv_name is not None and vg_name is not None:
            cmd.append("%s/%s" % (vg_name, lv_name))
        elif vg_name is not None:
            cmd.append(vg_name)

        try:
            (out, _err) = putils.execute(*cmd,
                                         root_helper=root_helper,
                                         run_as_root=True)
        except putils.ProcessExecutionError as err:
            with excutils.save_and_reraise_exception(reraise=True) as ctx:
                if "not found" in err.stderr:
                    ctx.reraise = False
                    LOG.info(_LI("'Not found' when querying LVM info. "
                                 "(vg_name=%(vg)s, lv_name=%(lv)s"),
                             {'vg': vg_name, 'lv': lv_name})
                    out = None

        lv_list = []
        if out is not None:
            volumes = out.split()
            for vg, name, size in itertools.izip(*[iter(volumes)] * 3):
                lv_list.append({"vg": vg, "name": name, "size": size})

        return lv_list

    def get_volumes(self, lv_name=None):
        """Get all LV's associated with this instantiation (VG).

        :returns: List of Dictionaries with LV info

        """
        return self.get_lv_info(self._root_helper,
                                self.vg_name,
                                lv_name)

    def get_volume(self, name):
        """Get reference object of volume specified by name.

        :returns: dict representation of Logical Volume if exists

        """
        ref_list = self.get_volumes(name)
        for r in ref_list:
            if r['name'] == name:
                return r
        return None

    @staticmethod
    def get_all_physical_volumes(root_helper, vg_name=None):
        """Static method to get all PVs on a system.

        :param root_helper: root_helper to use for execute
        :param vg_name: optional, gathers info for only the specified VG
        :returns: List of Dictionaries with PV info

        """
        field_sep = '|'
        cmd = LVM.LVM_CMD_PREFIX + ['pvs', '--noheadings',
                                    '--unit=g',
                                    '-o', 'vg_name,name,size,free',
                                    '--separator', field_sep,
                                    '--nosuffix']
        (out, _err) = putils.execute(*cmd,
                                     root_helper=root_helper,
                                     run_as_root=True)

        pvs = out.split()
        if vg_name is not None:
            pvs = [pv for pv in pvs if vg_name == pv.split(field_sep)[0]]

        pv_list = []
        for pv in pvs:
            fields = pv.split(field_sep)
            pv_list.append({'vg': fields[0],
                            'name': fields[1],
                            'size': float(fields[2]),
                            'available': float(fields[3])})
        return pv_list

    def get_physical_volumes(self):
        """Get all PVs associated with this instantiation (VG).

        :returns: List of Dictionaries with PV info

        """
        self.pv_list = self.get_all_physical_volumes(self._root_helper,
                                                     self.vg_name)
        return self.pv_list

    @staticmethod
    def get_all_volume_groups(root_helper, vg_name=None):
        """Static method to get all VGs on a system.

        :param root_helper: root_helper to use for execute
        :param vg_name: optional, gathers info for only the specified VG
        :returns: List of Dictionaries with VG info

        """
        cmd = LVM.LVM_CMD_PREFIX + ['vgs', '--noheadings',
                                    '--unit=g', '-o',
                                    'name,size,free,lv_count,uuid',
                                    '--separator', ':',
                                    '--nosuffix']
        if vg_name is not None:
            cmd.append(vg_name)

        (out, _err) = putils.execute(*cmd,
                                     root_helper=root_helper,
                                     run_as_root=True)
        vg_list = []
        if out is not None:
            vgs = out.split()
            for vg in vgs:
                fields = vg.split(':')
                vg_list.append({'name': fields[0],
                                'size': float(fields[1]),
                                'available': float(fields[2]),
                                'lv_count': int(fields[3]),
                                'uuid': fields[4]})

        return vg_list

    def update_volume_group_info(self):
        """Update VG info for this instantiation.

        Used to update member fields of object and
        provide a dict of info for caller.

        :returns: Dictionaries of VG info

        """
        vg_list = self.get_all_volume_groups(self._root_helper, self.vg_name)

        if len(vg_list) != 1:
            LOG.error(_LE('Unable to find VG: %s'), self.vg_name)
            raise exception.VolumeGroupNotFound(vg_name=self.vg_name)

        self.vg_size = float(vg_list[0]['size'])
        self.vg_free_space = float(vg_list[0]['available'])
        self.vg_lv_count = int(vg_list[0]['lv_count'])
        self.vg_uuid = vg_list[0]['uuid']

        total_vols_size = 0.0
        if self.vg_thin_pool is not None:
            # NOTE(xyang): If providing only self.vg_name,
            # get_lv_info will output info on the thin pool and all
            # individual volumes.
            # get_lv_info(self._root_helper, 'stack-vg')
            # sudo lvs --noheadings --unit=g -o vg_name,name,size
            # --nosuffix stack-vg
            # stack-vg stack-pool               9.51
            # stack-vg volume-13380d16-54c3-4979-9d22-172082dbc1a1  1.00
            # stack-vg volume-629e13ab-7759-46a5-b155-ee1eb20ca892  1.00
            # stack-vg volume-e3e6281c-51ee-464c-b1a7-db6c0854622c  1.00
            #
            # If providing both self.vg_name and self.vg_thin_pool,
            # get_lv_info will output only info on the thin pool, but not
            # individual volumes.
            # get_lv_info(self._root_helper, 'stack-vg', 'stack-pool')
            # sudo lvs --noheadings --unit=g -o vg_name,name,size
            # --nosuffix stack-vg/stack-pool
            # stack-vg stack-pool               9.51
            #
            # We need info on both the thin pool and the volumes,
            # therefore we should provide only self.vg_name, but not
            # self.vg_thin_pool here.
            for lv in self.get_lv_info(self._root_helper,
                                       self.vg_name):
                lvsize = lv['size']
                # get_lv_info runs "lvs" command with "--nosuffix".
                # This removes "g" from "1.00g" and only outputs "1.00".
                # Running "lvs" command without "--nosuffix" will output
                # "1.00g" if "g" is the unit.
                # Remove the unit if it is in lv['size'].
                if not lv['size'][-1].isdigit():
                    lvsize = lvsize[:-1]
                if lv['name'] == self.vg_thin_pool:
                    self.vg_thin_pool_size = lvsize
                    tpfs = self._get_thin_pool_free_space(self.vg_name,
                                                          self.vg_thin_pool)
                    self.vg_thin_pool_free_space = tpfs
                else:
                    total_vols_size = total_vols_size + float(lvsize)
            total_vols_size = round(total_vols_size, 2)

        self.vg_provisioned_capacity = total_vols_size

    def _calculate_thin_pool_size(self):
        """Calculates the correct size for a thin pool.

        Ideally we would use 100% of the containing volume group and be done.
        But the 100%VG notation to lvcreate is not implemented and thus cannot
        be used.  See https://bugzilla.redhat.com/show_bug.cgi?id=998347

        Further, some amount of free space must remain in the volume group for
        metadata for the contained logical volumes.  The exact amount depends
        on how much volume sharing you expect.

        :returns: An lvcreate-ready string for the number of calculated bytes.
        """

        # make sure volume group information is current
        self.update_volume_group_info()

        # leave 5% free for metadata
        return "%sg" % (self.vg_free_space * 0.95)

    def create_thin_pool(self, name=None, size_str=None):
        """Creates a thin provisioning pool for this VG.

        The syntax here is slightly different than the default
        lvcreate -T, so we'll just write a custom cmd here
        and do it.

        :param name: Name to use for pool, default is "<vg-name>-pool"
        :param size_str: Size to allocate for pool, default is entire VG
        :returns: The size string passed to the lvcreate command

        """

        if not self.supports_thin_provisioning(self._root_helper):
            LOG.error(_LE('Requested to setup thin provisioning, '
                          'however current LVM version does not '
                          'support it.'))
            return None

        if name is None:
            name = '%s-pool' % self.vg_name

        vg_pool_name = '%s/%s' % (self.vg_name, name)

        if not size_str:
            size_str = self._calculate_thin_pool_size()

        cmd = ['lvcreate', '-T', '-L', size_str, vg_pool_name]
        LOG.debug("Creating thin pool '%(pool)s' with size %(size)s of "
                  "total %(free)sg", {'pool': vg_pool_name,
                                      'size': size_str,
                                      'free': self.vg_free_space})

        self._execute(*cmd,
                      root_helper=self._root_helper,
                      run_as_root=True)

        self.vg_thin_pool = name
        return size_str

    def create_volume(self, name, size_str, lv_type='default', mirror_count=0):
        """Creates a logical volume on the object's VG.

        :param name: Name to use when creating Logical Volume
        :param size_str: Size to use when creating Logical Volume
        :param lv_type: Type of Volume (default or thin)
        :param mirror_count: Use LVM mirroring with specified count

        """

        if lv_type == 'thin':
            pool_path = '%s/%s' % (self.vg_name, self.vg_thin_pool)
            cmd = ['lvcreate', '-T', '-V', size_str, '-n', name, pool_path]
        else:
            cmd = ['lvcreate', '-n', name, self.vg_name, '-L', size_str]

        if mirror_count > 0:
            cmd.extend(['-m', mirror_count, '--nosync',
                        '--mirrorlog', 'mirrored'])
            terras = int(size_str[:-1]) / 1024.0
            if terras >= 1.5:
                rsize = int(2 ** math.ceil(math.log(terras) / math.log(2)))
                # NOTE(vish): Next power of two for region size. See:
                #             http://red.ht/U2BPOD
                cmd.extend(['-R', str(rsize)])

        try:
            self._execute(*cmd,
                          root_helper=self._root_helper,
                          run_as_root=True)
        except putils.ProcessExecutionError as err:
            LOG.exception(_LE('Error creating Volume'))
            LOG.error(_LE('Cmd     :%s'), err.cmd)
            LOG.error(_LE('StdOut  :%s'), err.stdout)
            LOG.error(_LE('StdErr  :%s'), err.stderr)
            raise

    @utils.retry(putils.ProcessExecutionError)
    def create_lv_snapshot(self, name, source_lv_name, lv_type='default'):
        """Creates a snapshot of a logical volume.

        :param name: Name to assign to new snapshot
        :param source_lv_name: Name of Logical Volume to snapshot
        :param lv_type: Type of LV (default or thin)

        """
        source_lvref = self.get_volume(source_lv_name)
        if source_lvref is None:
            LOG.error(_LE("Trying to create snapshot by non-existent LV: %s"),
                      source_lv_name)
            raise exception.VolumeDeviceNotFound(device=source_lv_name)
        cmd = ['lvcreate', '--name', name,
               '--snapshot', '%s/%s' % (self.vg_name, source_lv_name)]
        if lv_type != 'thin':
            size = source_lvref['size']
            cmd.extend(['-L', '%sg' % (size)])

        try:
            self._execute(*cmd,
                          root_helper=self._root_helper,
                          run_as_root=True)
        except putils.ProcessExecutionError as err:
            LOG.exception(_LE('Error creating snapshot'))
            LOG.error(_LE('Cmd     :%s'), err.cmd)
            LOG.error(_LE('StdOut  :%s'), err.stdout)
            LOG.error(_LE('StdErr  :%s'), err.stderr)
            raise

    def _mangle_lv_name(self, name):
        # Linux LVM reserves name that starts with snapshot, so that
        # such volume name can't be created. Mangle it.
        if not name.startswith('snapshot'):
            return name
        return '_' + name

    def activate_lv(self, name, is_snapshot=False):
        """Ensure that logical volume/snapshot logical volume is activated.

        :param name: Name of LV to activate
        :raises: putils.ProcessExecutionError
        """

        # This is a no-op if requested for a snapshot on a version
        # of LVM that doesn't support snapshot activation.
        # (Assume snapshot LV is always active.)
        if is_snapshot and not self.supports_snapshot_lv_activation:
            return

        lv_path = self.vg_name + '/' + self._mangle_lv_name(name)

        # Must pass --yes to activate both the snap LV and its origin LV.
        # Otherwise lvchange asks if you would like to do this interactively,
        # and fails.
        cmd = ['lvchange', '-a', 'y', '--yes']

        if self.supports_lvchange_ignoreskipactivation:
            cmd.append('-K')

        cmd.append(lv_path)

        try:
            self._execute(*cmd,
                          root_helper=self._root_helper,
                          run_as_root=True)
        except putils.ProcessExecutionError as err:
            LOG.exception(_LE('Error activating LV'))
            LOG.error(_LE('Cmd     :%s'), err.cmd)
            LOG.error(_LE('StdOut  :%s'), err.stdout)
            LOG.error(_LE('StdErr  :%s'), err.stderr)
            raise

    @utils.retry(putils.ProcessExecutionError)
    def delete(self, name):
        """Delete logical volume or snapshot.

        :param name: Name of LV to delete

        """

        def run_udevadm_settle():
            self._execute('udevadm', 'settle',
                          root_helper=self._root_helper, run_as_root=True,
                          check_exit_code=False)

        # LV removal seems to be a race with other writers or udev in
        # some cases (see LP #1270192), so we enable retry deactivation
        LVM_CONFIG = 'activation { retry_deactivation = 1} '

        try:
            self._execute(
                'lvremove',
                '--config', LVM_CONFIG,
                '-f',
                '%s/%s' % (self.vg_name, name),
                root_helper=self._root_helper, run_as_root=True)
        except putils.ProcessExecutionError as err:
            LOG.debug('Error reported running lvremove: CMD: %(command)s, '
                      'RESPONSE: %(response)s',
                      {'command': err.cmd, 'response': err.stderr})

            LOG.debug('Attempting udev settle and retry of lvremove...')
            run_udevadm_settle()

            # The previous failing lvremove -f might leave behind
            # suspended devices; when lvmetad is not available, any
            # further lvm command will block forever.
            # Therefore we need to skip suspended devices on retry.
            LVM_CONFIG += 'devices { ignore_suspended_devices = 1}'

            self._execute(
                'lvremove',
                '--config', LVM_CONFIG,
                '-f',
                '%s/%s' % (self.vg_name, name),
                root_helper=self._root_helper, run_as_root=True)
            LOG.debug('Successfully deleted volume: %s after '
                      'udev settle.', name)

    def revert(self, snapshot_name):
        """Revert an LV from snapshot.

        :param snapshot_name: Name of snapshot to revert

        """
        self._execute('lvconvert', '--merge',
                      snapshot_name, root_helper=self._root_helper,
                      run_as_root=True)

    def lv_has_snapshot(self, name):
        cmd = LVM.LVM_CMD_PREFIX + ['lvdisplay', '--noheading', '-C', '-o',
                                    'Attr', '%s/%s' % (self.vg_name, name)]
        out, _err = self._execute(*cmd,
                                  root_helper=self._root_helper,
                                  run_as_root=True)
        if out:
            out = out.strip()
            if (out[0] == 'o') or (out[0] == 'O'):
                return True
        return False

    def extend_volume(self, lv_name, new_size):
        """Extend the size of an existing volume."""

        try:
            self._execute('lvextend', '-L', new_size,
                          '%s/%s' % (self.vg_name, lv_name),
                          root_helper=self._root_helper,
                          run_as_root=True)
        except putils.ProcessExecutionError as err:
            LOG.exception(_LE('Error extending Volume'))
            LOG.error(_LE('Cmd     :%s'), err.cmd)
            LOG.error(_LE('StdOut  :%s'), err.stdout)
            LOG.error(_LE('StdErr  :%s'), err.stderr)
            raise

    def vg_mirror_free_space(self, mirror_count):
        free_capacity = 0.0

        disks = []
        for pv in self.pv_list:
            disks.append(float(pv['available']))

        while True:
            disks = sorted([a for a in disks if a > 0.0], reverse=True)
            if len(disks) <= mirror_count:
                break
            # consume the smallest disk
            disk = disks[-1]
            disks = disks[:-1]
            # match extents for each mirror on the largest disks
            for index in list(range(mirror_count)):
                disks[index] -= disk
            free_capacity += disk

        return free_capacity

    def vg_mirror_size(self, mirror_count):
        return (self.vg_free_space / (mirror_count + 1))

    def rename_volume(self, lv_name, new_name):
        """Change the name of an existing volume."""

        try:
            self._execute('lvrename', self.vg_name, lv_name, new_name,
                          root_helper=self._root_helper,
                          run_as_root=True)
        except putils.ProcessExecutionError as err:
            LOG.exception(_LE('Error renaming logical volume'))
            LOG.error(_LE('Cmd     :%s'), err.cmd)
            LOG.error(_LE('StdOut  :%s'), err.stdout)
            LOG.error(_LE('StdErr  :%s'), err.stderr)
            raise
