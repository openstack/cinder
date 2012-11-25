# vim: tabstop=4 shiftwidth=4 softtabstop=4

#  Copyright 2012 Pedro Navarro Perez
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
Windows storage classes to be used in testing.
"""

import os
import sys

from cinder import flags

# Check needed for unit testing on Unix
if os.name == 'nt':
    import wmi

FLAGS = flags.FLAGS


class WindowsUtils(object):
    def __init__(self):
        self.__conn_cimv2 = None
        self.__conn_wmi = None

    @property
    def _conn_cimv2(self):
        if self.__conn_cimv2 is None:
            self.__conn_cimv2 = wmi.WMI(moniker='//./root/cimv2')
        return self.__conn_cimv2

    @property
    def _conn_wmi(self):
        if self.__conn_wmi is None:
            self.__conn_wmi = wmi.WMI(moniker='//./root/wmi')
        return self.__conn_wmi

    def find_vhd_by_name(self, name):
        '''Finds a volume by its name.'''

        wt_disks = self._conn_wmi.WT_Disk(Description=name)
        return wt_disks

    def volume_exists(self, name):
        '''Checks if a volume exists.'''

        wt_disks = self.find_vhd_by_name(name)
        if len(wt_disks) > 0:
            return True
        return False

    def snapshot_exists(self, name):
        '''Checks if a snapshot exists.'''

        wt_snapshots = self.find_snapshot_by_name(name)
        if len(wt_snapshots) > 0:
            return True
        return False

    def find_snapshot_by_name(self, name):
        '''Finds a snapshot by its name.'''

        wt_snapshots = self._conn_wmi.WT_Snapshot(Description=name)
        return wt_snapshots

    def delete_volume(self, name):
        '''Deletes a volume.'''

        wt_disk = self._conn_wmi.WT_Disk(Description=name)[0]
        wt_disk.Delete_()
        vhdfiles = self._conn_cimv2.query(
            "Select * from CIM_DataFile where Name = '" +
            self._get_vhd_path(name) + "'")
        if len(vhdfiles) > 0:
            vhdfiles[0].Delete()

    def _get_vhd_path(self, volume_name):
        '''Gets the path disk of the volume.'''

        base_vhd_folder = FLAGS.windows_iscsi_lun_path
        return os.path.join(base_vhd_folder, volume_name + ".vhd")

    def delete_snapshot(self, name):
        '''Deletes a snapshot.'''

        wt_snapshot = self._conn_wmi.WT_Snapshot(Description=name)[0]
        wt_snapshot.Delete_()
        vhdfile = self._conn_cimv2.query(
            "Select * from CIM_DataFile where Name = '" +
            self._get_vhd_path(name) + "'")[0]
        vhdfile.Delete()

    def find_initiator_ids(self, target_name, initiator_name):
        '''Finds a initiator id by its name.'''
        wt_idmethod = self._conn_wmi.WT_IDMethod(HostName=target_name,
                                                 Method=4,
                                                 Value=initiator_name)
        return wt_idmethod

    def initiator_id_exists(self, target_name, initiator_name):
        '''Checks if  a initiatorId exists.'''

        wt_idmethod = self.find_initiator_ids(target_name, initiator_name)
        if len(wt_idmethod) > 0:
            return True
        return False

    def find_exports(self, target_name):
        '''Finds a export id by its name.'''

        wt_host = self._conn_wmi.WT_Host(HostName=target_name)
        return wt_host

    def export_exists(self, target_name):
        '''Checks if  a export exists.'''

        wt_host = self.find_exports(target_name)
        if len(wt_host) > 0:
            return True
        return False

    def delete_initiator_id(self, target_name, initiator_name):
        '''Deletes a initiatorId.'''

        wt_init_id = self.find_initiator_ids(target_name, initiator_name)[0]
        wt_init_id.Delete_()

    def delete_export(self, target_name):
        '''Deletes an export.'''

        wt_host = self.find_exports(target_name)[0]
        wt_host.RemoveAllWTDisks()
        wt_host.Delete_()
