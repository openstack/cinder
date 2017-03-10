# Copyright (c) 2014 Hitachi Data Systems, Inc.
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

import mock
import os
import paramiko
import time

from oslo_concurrency import processutils as putils

from cinder import exception
from cinder import test
from cinder import utils
from cinder.volume.drivers.hitachi import hnas_backend


evsfs_list = "\n\
FS ID        FS Label        FS Permanent ID     EVS ID     EVS Label\n\
-----     -----------     ------------------     ------     ---------\n\
 1026            gold     0xaadee0e035cfc0b7          1      EVS-Manila\n\
 1029        test_hdp     0xaadee09634acfcac          1      EVS-Manila\n\
 1030       fs-cinder     0xaadfcf742fba644e          2      EVS-Cinder\n\
 1031         cinder2     0xaadfcf7e0769a6bc          3      EVS-Test\n\
 1024      fs02-husvm     0xaac8715e2e9406cd          3      EVS-Test\n\
\n"

cluster_getmac = "cluster MAC: 83-68-96-AA-DA-5D"

version = "\n\
Model: HNAS 4040                                             \n\n\
Software: 11.2.3319.14 (built 2013-09-19 12:34:24+01:00)     \n\n\
Hardware: NAS Platform (M2SEKW1339109)                       \n\n\
board        MMB1                                            \n\
mmb          11.2.3319.14 release (2013-09-19 12:34:24+01:00)\n\n\
board        MFB1                                            \n\
mfb1hw       MB v0883 WL v002F TD v002F FD v002F TC v0059      \
    RY v0059 TY v0059 IC v0059 WF v00E2 FS v00E2 OS v00E2      \
    WD v00E2 DI v001A FC v0002                               \n\
Serial no    B1339745 (Thu Jan  1 00:00:50 2009)             \n\n\
board        MCP                                             \n\
Serial no    B1339109 (Thu Jan  1 00:00:49 2009)             \n\
\n"

evsipaddr = "\n\
EVS Type    Label            IP Address          Mask             Port  \n\
----------  ---------------  ------------------  ---------------  ------\n\
admin       hnas4040         192.0.2.2           255.255.255.0    eth1  \n\
admin       hnas4040         172.24.44.15        255.255.255.0    eth0  \n\
evs 1       EVSTest1         172.24.44.20        255.255.255.0    ag1   \n\
evs 1       EVSTest1         10.0.0.20           255.255.255.0    ag1   \n\
evs 2       EVSTest2         172.24.44.21        255.255.255.0    ag1   \n\
\n"

df_f = "\n\
ID       Label   EVS    Size          Used  Snapshots  Deduped         Avail  \
Thin  ThinSize  ThinAvail               FS Type\n\
----  ---------- ---  ------  ------------  ---------  -------  ------------  \
----  --------  ---------  --------------------\n\
1025  fs-cinder   2  250 GB  21.4 GB (9%)   0 B (0%)       NA  228 GB (91%)  \
  No                       32 KB,WFS-2,128 DSBs\n\
\n"

df_f_tb = "\n\
ID       Label   EVS    Size          Used  Snapshots  Deduped         Avail  \
Thin  ThinSize  ThinAvail               FS Type\n\
----  ---------- ---  ------  ------------  ---------  -------  ------------  \
----  --------  ---------  --------------------\n\
1025  fs-cinder   2  250 TB  21.4 TB (9%)   0 B (0%)       NA  228 TB (91%)  \
  No                       32 KB,WFS-2,128 DSBs\n\
\n"

nfs_export = "\n\
Export name: /export01-husvm                \n\
Export path: /export01-husvm                \n\
File system label: fs-cinder                \n\
File system size: 250 GB                    \n\
File system free space: 228 GB              \n\
File system state:                          \n\
formatted = Yes                             \n\
mounted = Yes                               \n\
failed = No                                 \n\
thin provisioned = No                       \n\
Access snapshots: Yes                       \n\
Display snapshots: Yes                      \n\
Read Caching: Disabled                      \n\
Disaster recovery setting:                  \n\
Recovered = No                              \n\
Transfer setting = Use file system default  \n\n\
Export configuration:                       \n\
127.0.0.1                                   \n\
\n"

df_f_single_evs = "\n\
ID       Label      Size          Used  Snapshots  Deduped         Avail  \
Thin  ThinSize  ThinAvail               FS Type\n\
----  ----------  ------  ------------  ---------  -------  ------------  \
----  --------  ---------  --------------------\n\
1025  fs-cinder  250 GB  21.4 GB (9%)   0 B (0%)       NA  228 GB (91%)  \
  No                       32 KB,WFS-2,128 DSBs\n\
\n"

nfs_export_tb = "\n\
Export name: /export01-husvm                \n\
Export path: /export01-husvm                \n\
File system label: fs-cinder                \n\
File system size: 250 TB                    \n\
File system free space: 228 TB              \n\
\n"

nfs_export_not_available = "\n\
Export name: /export01-husvm                \n\
Export path: /export01-husvm                \n\
File system label: fs-cinder                \n\
        *** not available ***               \n\
\n"

evs_list = "\n\
Node EVS ID    Type           Label Enabled Status          IP Address Port \n\
---- ------ ------- --------------- ------- ------ ------------------- ---- \n\
   1        Cluster        hnas4040     Yes Online     192.0.2.200     eth1 \n\
   1      0   Admin        hnas4040     Yes Online       192.0.2.2     eth1 \n\
                                                      172.24.44.15     eth0 \n\
                                                     172.24.49.101      ag2 \n\
   1      1 Service      EVS-Manila     Yes Online    172.24.49.32      ag2 \n\
                                                      172.24.48.32      ag4 \n\
   1      2 Service      EVS-Cinder     Yes Online    172.24.49.21      ag2 \n\
   1      3 Service        EVS-Test     Yes Online 192.168.100.100      ag2 \n\
\n"

lu_list = "Name   : cinder-lu         \n\
Comment:                              \n\
Path   : /.cinder/cinder-lu           \n\
Size   : 2 GB                         \n\
File System : fs-cinder               \n\
File System Mounted : YES             \n\
Logical Unit Mounted: No"

lu_list_tb = "Name   : test-lu        \n\
Comment:                              \n\
Path   : /.cinder/test-lu             \n\
Size   : 2 TB                         \n\
File System : fs-cinder               \n\
File System Mounted : YES             \n\
Logical Unit Mounted: No"

hnas_fs_list = "%(l1)s\n\n%(l2)s\n\n " % {'l1': lu_list,
                                          'l2': lu_list_tb}

add_targetsecret = "Target created successfully."

backend_opts = {'mgmt_ip0': '0.0.0.0',
                'cluster_admin_ip0': None,
                'ssh_port': '22',
                'username': 'supervisor',
                'password': 'supervisor',
                'ssh_private_key': 'test_key'}

target_chap_disable = "\n\
Alias               : cinder-default                                  \n\
Globally unique name: iqn.2014-12.10.10.10.10:evstest1.cinder-default \n\
Comment             :                                                 \n\
Secret              :                                                 \n\
Authentication      : Disabled                                        \n\
Logical units       : No logical units.                               \n\
\n\
  LUN   Logical Unit                                                  \n\
  ----  --------------------------------                              \n\
  0     cinder-lu                                                     \n\
  1     volume-99da7ae7-1e7f-4d57-8bf...                              \n\
\n\
Access configuration:                                                 \n\
"

file_clone_stat = "Clone: /nfs_cinder/cinder-lu                      \n\
  SnapshotFile: FileHandle[00000000004010000d20116826ffffffffffffff] \n\
\n\
  SnapshotFile: FileHandle[00000000004029000d81f26826ffffffffffffff] \n\
"

file_clone_stat_snap_file1 = "\
FileHandle[00000000004010000d20116826ffffffffffffff]                  \n\n\
References:                                                           \n\
  Clone: /nfs_cinder/cinder-lu                                        \n\
  Clone: /nfs_cinder/snapshot-lu-1                                    \n\
  Clone: /nfs_cinder/snapshot-lu-2                                    \n\
"

file_clone_stat_snap_file2 = "\
FileHandle[00000000004010000d20116826ffffffffffffff]                  \n\n\
References:                                                           \n\
  Clone: /nfs_cinder/volume-not-used                                  \n\
  Clone: /nfs_cinder/snapshot-1                                       \n\
  Clone: /nfs_cinder/snapshot-2                                       \n\
"

not_a_clone = "\
file-clone-stat: failed to get predecessor snapshot-files: File is not a clone"

file_relatives =\
    [' /nfs_cinder/snapshot-lu-1                                    ',
     ' /nfs_cinder/snapshot-lu-2                                    ',
     ' /nfs_cinder/volume-not-used                                  ',
     ' /nfs_cinder/snapshot-1                                       ',
     ' /nfs_cinder/snapshot-2                                       ']


class HDSHNASBackendTest(test.TestCase):

    def __init__(self, *args, **kwargs):
        super(HDSHNASBackendTest, self).__init__(*args, **kwargs)

    def setUp(self):
        super(HDSHNASBackendTest, self).setUp()
        self.hnas_backend = hnas_backend.HNASSSHBackend(backend_opts)

    def test_run_cmd(self):
        self.mock_object(os.path, 'isfile', return_value=True)
        self.mock_object(utils, 'execute')
        self.mock_object(time, 'sleep')
        self.mock_object(paramiko, 'SSHClient')
        self.mock_object(paramiko.RSAKey, 'from_private_key_file')
        self.mock_object(putils, 'ssh_execute',
                         return_value=(df_f, ''))

        out, err = self.hnas_backend._run_cmd('ssh', '0.0.0.0',
                                              'supervisor', 'supervisor',
                                              'df', '-a')

        self.assertIn('fs-cinder', out)
        self.assertIn('WFS-2,128 DSBs', out)

    def test_run_cmd_retry_exception(self):
        self.hnas_backend.cluster_admin_ip0 = '172.24.44.11'

        exceptions = [putils.ProcessExecutionError(stderr='Connection reset'),
                      putils.ProcessExecutionError(stderr='Failed to establish'
                                                          ' SSC connection'),
                      putils.ProcessExecutionError(stderr='Connection reset'),
                      putils.ProcessExecutionError(stderr='Connection reset'),
                      putils.ProcessExecutionError(stderr='Connection reset')]

        self.mock_object(os.path, 'isfile',
                         return_value=True)
        self.mock_object(utils, 'execute')
        self.mock_object(time, 'sleep')
        self.mock_object(paramiko, 'SSHClient')
        self.mock_object(paramiko.RSAKey, 'from_private_key_file')
        self.mock_object(putils, 'ssh_execute',
                         side_effect=exceptions)

        self.assertRaises(exception.HNASConnError, self.hnas_backend._run_cmd,
                          'ssh', '0.0.0.0', 'supervisor', 'supervisor', 'df',
                          '-a')

    def test_run_cmd_exception_without_retry(self):
        self.mock_object(os.path, 'isfile',
                         return_value=True)
        self.mock_object(utils, 'execute')
        self.mock_object(time, 'sleep')
        self.mock_object(paramiko, 'SSHClient')
        self.mock_object(paramiko.RSAKey, 'from_private_key_file')
        self.mock_object(putils, 'ssh_execute',
                         side_effect=putils.ProcessExecutionError(
                             stderr='Error'))

        self.assertRaises(putils.ProcessExecutionError,
                          self.hnas_backend._run_cmd, 'ssh', '0.0.0.0',
                          'supervisor', 'supervisor', 'df', '-a')

    def test_get_version(self):
        expected_out = {
            'hardware': 'NAS Platform (M2SEKW1339109)',
            'mac': '83-68-96-AA-DA-5D',
            'version': '11.2.3319.14',
            'model': 'HNAS 4040',
            'serial': 'B1339745'
        }

        self.mock_object(self.hnas_backend, '_run_cmd',
                         side_effect=[(cluster_getmac, ''), (version, '')])

        out = self.hnas_backend.get_version()

        self.assertEqual(expected_out, out)

    def test_get_evs(self):
        self.mock_object(self.hnas_backend, '_run_cmd',
                         return_value=(evsfs_list, ''))

        out = self.hnas_backend.get_evs('fs-cinder')

        self.assertEqual('2', out)

    def test_get_export_list(self):
        self.mock_object(self.hnas_backend, '_run_cmd',
                         side_effect=[(nfs_export, ''),
                                      (evsfs_list, ''),
                                      (evs_list, '')])

        out = self.hnas_backend.get_export_list()

        self.assertEqual('fs-cinder', out[0]['fs'])
        self.assertEqual(250.0, out[0]['size'])
        self.assertEqual(228.0, out[0]['free'])
        self.assertEqual('/export01-husvm', out[0]['path'])

    def test_get_export_list_data_not_available(self):
        self.mock_object(self.hnas_backend, '_run_cmd',
                         side_effect=[(nfs_export_not_available, ''),
                                      (evsfs_list, ''),
                                      (evs_list, '')])

        out = self.hnas_backend.get_export_list()

        self.assertEqual('fs-cinder', out[0]['fs'])
        self.assertEqual('/export01-husvm', out[0]['path'])
        self.assertEqual(-1, out[0]['size'])
        self.assertEqual(-1, out[0]['free'])

    def test_get_export_list_tb(self):
        size = float(250 * 1024)
        free = float(228 * 1024)
        self.mock_object(self.hnas_backend, '_run_cmd',
                         side_effect=[(nfs_export_tb, ''),
                                      (evsfs_list, ''),
                                      (evs_list, '')])

        out = self.hnas_backend.get_export_list()

        self.assertEqual('fs-cinder', out[0]['fs'])
        self.assertEqual(size, out[0]['size'])
        self.assertEqual(free, out[0]['free'])
        self.assertEqual('/export01-husvm', out[0]['path'])

    def test_file_clone(self):
        path1 = '/.cinder/path1'
        path2 = '/.cinder/path2'

        self.mock_object(self.hnas_backend, '_run_cmd',
                         return_value=(evsfs_list, ''))

        self.hnas_backend.file_clone('fs-cinder', path1, path2)

        calls = [mock.call('evsfs', 'list'), mock.call('console-context',
                                                       '--evs', '2',
                                                       'file-clone-create',
                                                       '-f', 'fs-cinder',
                                                       path1, path2)]
        self.hnas_backend._run_cmd.assert_has_calls(calls, any_order=False)

    def test_file_clone_wrong_fs(self):
        self.mock_object(self.hnas_backend, '_run_cmd',
                         return_value=(evsfs_list, ''))

        self.assertRaises(exception.InvalidParameterValue,
                          self.hnas_backend.file_clone, 'fs-fake', 'src',
                          'dst')

    def test_get_evs_info(self):
        expected_out = {'evs_number': '1'}
        expected_out2 = {'evs_number': '2'}

        self.mock_object(self.hnas_backend, '_run_cmd',
                         return_value=(evsipaddr, ''))

        out = self.hnas_backend.get_evs_info()

        self.hnas_backend._run_cmd.assert_called_with('evsipaddr', '-l')
        self.assertEqual(expected_out, out['10.0.0.20'])
        self.assertEqual(expected_out, out['172.24.44.20'])
        self.assertEqual(expected_out2, out['172.24.44.21'])

    def test_get_fs_info(self):
        self.mock_object(self.hnas_backend, '_run_cmd',
                         side_effect=[(df_f, ''), (evsfs_list, ''),
                                      (hnas_fs_list, '')])

        out = self.hnas_backend.get_fs_info('fs-cinder')

        self.assertEqual('2', out['evs_id'])
        self.assertEqual('fs-cinder', out['label'])
        self.assertEqual('228', out['available_size'])
        self.assertEqual('250', out['total_size'])
        self.assertEqual(0, out['provisioned_capacity'])

    def test_get_fs_empty_return(self):
        self.mock_object(self.hnas_backend, '_run_cmd',
                         return_value=('Not mounted', ''))

        out = self.hnas_backend.get_fs_info('fs-cinder')
        self.assertEqual({}, out)

    def test_get_fs_info_single_evs(self):
        self.mock_object(self.hnas_backend, '_run_cmd',
                         side_effect=[(df_f_single_evs, ''), (evsfs_list, ''),
                                      (hnas_fs_list, '')])

        out = self.hnas_backend.get_fs_info('fs-cinder')

        self.assertEqual('fs-cinder', out['label'])
        self.assertEqual('228', out['available_size'])
        self.assertEqual('250', out['total_size'])
        self.assertEqual(0, out['provisioned_capacity'])

    def test_get_fs_tb(self):
        available_size = float(228 * 1024 ** 2)
        total_size = float(250 * 1024 ** 2)

        self.mock_object(self.hnas_backend, '_run_cmd',
                         side_effect=[(df_f_tb, ''), (evsfs_list, ''),
                                      (hnas_fs_list, '')])

        out = self.hnas_backend.get_fs_info('fs-cinder')

        self.assertEqual('fs-cinder', out['label'])
        self.assertEqual(str(available_size), out['available_size'])
        self.assertEqual(str(total_size), out['total_size'])
        self.assertEqual(0, out['provisioned_capacity'])

    def test_get_fs_single_evs_tb(self):
        available_size = float(228 * 1024 ** 2)
        total_size = float(250 * 1024 ** 2)

        self.mock_object(self.hnas_backend, '_run_cmd',
                         side_effect=[(df_f_tb, ''), (evsfs_list, ''),
                                      (hnas_fs_list, '')])

        out = self.hnas_backend.get_fs_info('fs-cinder')

        self.assertEqual('fs-cinder', out['label'])
        self.assertEqual(str(available_size), out['available_size'])
        self.assertEqual(str(total_size), out['total_size'])
        self.assertEqual(0, out['provisioned_capacity'])

    def test_get_cloned_file_relatives(self):
        self.mock_object(self.hnas_backend, '_run_cmd',
                         side_effect=[(evsfs_list, ''), (file_clone_stat, ''),
                                      (file_clone_stat_snap_file1, ''),
                                      (file_clone_stat_snap_file2, '')])
        out = self.hnas_backend.get_cloned_file_relatives('cinder-lu',
                                                          'fs-cinder')
        self.assertEqual(file_relatives, out)
        self.hnas_backend._run_cmd.assert_called_with('console-context',
                                                      '--evs', '2',
                                                      'file-clone-stat-'
                                                      'snapshot-file',
                                                      '-f', 'fs-cinder',
                                                      '00000000004029000d81'
                                                      'f26826ffffffffffffff]')

    def test_get_cloned_file_relatives_not_clone_except(self):
        exc = putils.ProcessExecutionError(stderr='File is not a clone')
        self.mock_object(self.hnas_backend, '_run_cmd',
                         side_effect=[(evsfs_list, ''), exc])

        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.hnas_backend.get_cloned_file_relatives,
                          'cinder-lu', 'fs-cinder', True)

    def test_get_cloned_file_relatives_not_clone_no_except(self):
        exc = putils.ProcessExecutionError(stderr='File is not a clone')
        self.mock_object(self.hnas_backend, '_run_cmd',
                         side_effect=[(evsfs_list, ''), exc])

        out = self.hnas_backend.get_cloned_file_relatives('cinder-lu',
                                                          'fs-cinder')

        self.assertEqual([], out)

    def test_check_snapshot_parent_true(self):
        self.mock_object(self.hnas_backend, '_run_cmd',
                         side_effect=[(evsfs_list, ''),
                                      (file_clone_stat, ''),
                                      (file_clone_stat_snap_file1, ''),
                                      (file_clone_stat_snap_file2, '')])
        out = self.hnas_backend.check_snapshot_parent('cinder-lu',
                                                      'snapshot-lu-1',
                                                      'fs-cinder')

        self.assertTrue(out)

    def test_check_snapshot_parent_false(self):
        self.mock_object(self.hnas_backend, '_run_cmd',
                         side_effect=[(evsfs_list, ''),
                                      (file_clone_stat, ''),
                                      (file_clone_stat_snap_file1, ''),
                                      (file_clone_stat_snap_file2, '')])
        out = self.hnas_backend.check_snapshot_parent('cinder-lu',
                                                      'snapshot-lu-3',
                                                      'fs-cinder')

        self.assertFalse(out)

    def test_get_export_path(self):
        export_out = '/export01-husvm'

        self.mock_object(self.hnas_backend, '_run_cmd',
                         side_effect=[(evsfs_list, ''), (nfs_export, '')])

        out = self.hnas_backend.get_export_path(export_out, 'fs-cinder')

        self.assertEqual(export_out, out)
        self.hnas_backend._run_cmd.assert_called_with('console-context',
                                                      '--evs', '2',
                                                      'nfs-export', 'list',
                                                      export_out)
