# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

import math

from itertools import izip

from cinder.openstack.common.gettextutils import _
from cinder.openstack.common import log as logging
from cinder.openstack.common import processutils as putils

LOG = logging.getLogger(__name__)


class VolumeGroupNotFound(Exception):
    def __init__(self, vg_name):
        message = (_('Unable to find Volume Group: %s') % vg_name)
        super(VolumeGroupNotFound, self).__init__(message)


class VolumeGroupCreationFailed(Exception):
    def __init__(self, vg_name):
        message = (_('Failed to create Volume Group: %s') % vg_name)
        super(VolumeGroupCreationFailed, self).__init__(message)


class LVM(object):
    """LVM object to enable various LVM related operations."""

    def __init__(self, vg_name, create_vg=False,
                 physical_volumes=None):
        """Initialize the LVM object.

        The LVM object is based on an LVM VolumeGroup, one instantiation
        for each VolumeGroup you have/use.

        :param vg_name: Name of existing VG or VG to create
        :param create_vg: Indicates the VG doesn't exist
                          and we want to create it
        :param physical_volumes: List of PVs to build VG on

        """
        self.vg_name = vg_name
        self.pv_list = []
        self.lv_list = []
        self.vg_size = 0
        self.vg_available_space = 0
        self.vg_lv_count = 0
        self.vg_uuid = None

        if create_vg and physical_volumes is not None:
            self.pv_list = physical_volumes

            try:
                self._create_vg(physical_volumes)
            except putils.ProcessExecutionError as err:
                LOG.exception(_('Error creating Volume Group'))
                LOG.error(_('Cmd     :%s') % err.cmd)
                LOG.error(_('StdOut  :%s') % err.stdout)
                LOG.error(_('StdErr  :%s') % err.stderr)
                raise VolumeGroupCreationFailed(vg_name=self.vg_name)

        if self._vg_exists() is False:
            LOG.error(_('Unable to locate Volume Group %s') % vg_name)
            raise VolumeGroupNotFound(vg_name=vg_name)

    def _size_str(self, size_in_g):
        if '.00' in size_in_g:
            size_in_g = size_in_g.replace('.00', '')

        if int(size_in_g) == 0:
            return '100M'

        return '%sG' % size_in_g

    def _vg_exists(self):
        """Simple check to see if VG exists.

        :returns: True if vg specified in object exists, else False

        """
        exists = False
        cmd = ['vgs', '--noheadings', '-o', 'name']
        (out, err) = putils.execute(*cmd, root_helper='sudo', run_as_root=True)

        if out is not None:
            volume_groups = out.split()
            if self.vg_name in volume_groups:
                exists = True

        return exists

    def _create_vg(self, pv_list):
        cmd = ['vgcreate', self.vg_name, ','.join(pv_list)]
        putils.execute(*cmd, root_helper='sudo', run_as_root=True)

    def _get_vg_uuid(self):
        (out, err) = putils.execute('vgs', '--noheadings',
                                    '-o uuid', self.vg_name)
        if out is not None:
            return out.split()
        else:
            return []

    @staticmethod
    def supports_thin_provisioning():
        """Static method to check for thin LVM support on a system.

        :returns: True if supported, False otherwise

        """
        cmd = ['vgs', '--version']
        (out, err) = putils.execute(*cmd, root_helper='sudo', run_as_root=True)
        lines = out.split('\n')

        for line in lines:
            if 'LVM version' in line:
                version_list = line.split()
                version = version_list[2]
                if '(2)' in version:
                    version = version.replace('(2)', '')
                version_tuple = tuple(map(int, version.split('.')))
                if version_tuple >= (2, 2, 95):
                    return True
        return False

    @staticmethod
    def get_all_volumes(vg_name=None):
        """Static method to get all LV's on a system.

        :param vg_name: optional, gathers info for only the specified VG
        :returns: List of Dictionaries with LV info

        """
        cmd = ['lvs', '--noheadings', '-o', 'vg_name,name,size']
        if vg_name is not None:
            cmd += [vg_name]

        (out, err) = putils.execute(*cmd, root_helper='sudo', run_as_root=True)

        lv_list = []
        if out is not None:
            volumes = out.split()
            for vg, name, size in izip(*[iter(volumes)] * 3):
                lv_list.append({"vg": vg, "name": name, "size": size})

        return lv_list

    def get_volumes(self):
        """Get all LV's associated with this instantiation (VG).

        :returns: List of Dictionaries with LV info

        """
        self.lv_list = self.get_all_volumes(self.vg_name)
        return self.lv_list

    def get_volume(self, name):
        """Get reference object of volume specified by name.

        :returns: dict representation of Logical Volume if exists

        """
        ref_list = self.get_volumes()
        for r in ref_list:
            if r['name'] == name:
                return r

    @staticmethod
    def get_all_physical_volumes(vg_name=None):
        """Static method to get all PVs on a system.

        :param vg_name: optional, gathers info for only the specified VG
        :returns: List of Dictionaries with PV info

        """
        cmd = ['pvs', '--noheadings',
               '-o', 'vg_name,name,size,free',
               '--separator', ':']
        if vg_name is not None:
            cmd += [vg_name]

        (out, err) = putils.execute(*cmd, root_helper='sudo', run_as_root=True)

        pv_list = []
        if out is not None:
            pvs = out.split()
            for pv in pvs:
                fields = pv.split(':')
                pv_list.append({'vg': fields[0],
                                'name': fields[1],
                                'size': fields[2],
                                'available': fields[3]})

        return pv_list

    def get_physical_volumes(self):
        """Get all PVs associated with this instantiation (VG).

        :returns: List of Dictionaries with PV info

        """
        self.pv_list = self.get_all_physical_volumes(self.vg_name)
        return self.pv_list

    @staticmethod
    def get_all_volume_groups(vg_name=None):
        """Static method to get all VGs on a system.

        :param vg_name: optional, gathers info for only the specified VG
        :returns: List of Dictionaries with VG info

        """
        cmd = ['vgs', '--noheadings',
               '-o', 'name,size,free,lv_count,uuid',
               '--separator', ':']
        if vg_name is not None:
            cmd += [vg_name]

        (out, err) = putils.execute(*cmd, root_helper='sudo', run_as_root=True)

        vg_list = []
        if out is not None:
            vgs = out.split()
            for vg in vgs:
                fields = vg.split(':')
                vg_list.append({'name': fields[0],
                                'size': fields[1],
                                'available': fields[2],
                                'lv_count': fields[3],
                                'uuid': fields[4]})

        return vg_list

    def update_volume_group_info(self):
        """Update VG info for this instantiation.

        Used to update member fields of object and
        provide a dict of info for caller.

        :returns: Dictionaries of VG info

        """
        vg_list = self.get_all_volume_groups(self.vg_name)

        if len(vg_list) != 1:
            LOG.error(_('Unable to find VG: %s') % self.vg_name)
            raise VolumeGroupNotFound(vg_name=self.vg_name)

        self.vg_size = vg_list[0]['size']
        self.vg_available_space = vg_list[0]['available']
        self.vg_lv_count = vg_list[0]['lv_count']
        self.vg_uuid = vg_list[0]['uuid']

        return vg_list[0]

    def create_thin_pool(self, name=None, size_str=0):
        """Creates a thin provisioning pool for this VG.

        :param name: Name to use for pool, default is "<vg-name>-pool"
        :param size_str: Size to allocate for pool, default is entire VG

        """

        if not self.supports_thin_provisioning():
            LOG.error(_('Requested to setup thin provisioning, '
                        'however current LVM version does not '
                        'support it.'))
            return None

        if name is None:
            name = '%s-pool' % self.vg_name

        if size_str == 0:
            self.update_volume_group_info()
            size_str = self.vg_size

        self.create_volume(name, size_str, 'thin')

    def create_volume(self, name, size_str, lv_type='default', mirror_count=0):
        """Creates a logical volume on the object's VG.

        :param name: Name to use when creating Logical Volume
        :param size_str: Size to use when creating Logical Volume
        :param lv_type: Type of Volume (default or thin)
        :param mirror_count: Use LVM mirroring with specified count

        """
        size = self._size_str(size_str)
        cmd = ['lvcreate', '-n', name, self.vg_name]
        if lv_type == 'thin':
            cmd += ['-T', '-V', size]
        else:
            cmd += ['-L', size]

        if mirror_count > 0:
            cmd += ['-m', mirror_count, '--nosync']
            terras = int(size[:-1]) / 1024.0
            if terras >= 1.5:
                rsize = int(2 ** math.ceil(math.log(terras) / math.log(2)))
                # NOTE(vish): Next power of two for region size. See:
                #             http://red.ht/U2BPOD
                cmd += ['-R', str(rsize)]

        putils.execute(*cmd,
                       root_helper='sudo',
                       run_as_root=True)

    def create_lv_snapshot(self, name, source_lv_name, lv_type='default'):
        """Creates a snapshot of a logical volume.

        :param name: Name to assign to new snapshot
        :param source_lv_name: Name of Logical Volume to snapshot
        :param lv_type: Type of LV (default or thin)

        """
        source_lvref = self.get_volume(source_lv_name)
        if source_lvref is None:
            LOG.error(_("Unable to find LV: %s") % source_lv_name)
            return False
        cmd = ['lvcreate', '--name', name,
               '--snapshot', '%s/%s' % (self.vg_name, source_lv_name)]
        if lv_type != 'thin':
            size = source_lvref['size']
            cmd += ['-L', size]

        putils.execute(*cmd,
                       root_helper='sudo',
                       run_as_root=True)

    def delete(self, name):
        """Delete logical volume or snapshot.

        :param name: Name of LV to delete

        """
        putils.execute('lvremove',
                       '-f',
                       '%s/%s' % (self.vg_name, name),
                       root_helper='sudo', run_as_root=True)

    def revert(self, snapshot_name):
        """Revert an LV from snapshot.

        :param snapshot_name: Name of snapshot to revert

        """
        putils.execute('lvconvert', '--merge',
                       snapshot_name, root_helper='sudo',
                       run_as_root=True)
