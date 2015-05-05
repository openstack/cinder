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
from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log as logging

from cinder import test
from cinder import utils
from cinder.volume.drivers.hds import hnas_backend
from cinder.volume.drivers.hds import nfs

CONF = cfg.CONF

LOG = logging.getLogger(__name__)

HNAS_RESULT1 = "\n\
FS ID        FS Label        FS Permanent ID     EVS ID     EVS Label\n\
-----     -----------     ------------------     ------     ---------\n\
 1026            gold     0xaadee0e035cfc0b7          1      EVSTest1\n\
 1025      fs01-husvm     0xaada5dff78668800          1      EVSTest1\n\
 1027     large-files     0xaadee0ef012a0d54          1      EVSTest1\n\
 1028        platinun     0xaadee1ea49d1a32c          1      EVSTest1\n\
 1029        test_hdp     0xaadee09634acfcac          1      EVSTest1\n\
 1030         cinder1     0xaadfcf742fba644e          1      EVSTest1\n\
 1031         cinder2     0xaadfcf7e0769a6bc          1      EVSTest1\n\
 1024      fs02-husvm     0xaac8715e2e9406cd          2      EVSTest2\n\
\n"

HNAS_RESULT2 = "cluster MAC: 83-68-96-AA-DA-5D"

HNAS_RESULT3 = "\n\
Model: HNAS 4040                                             \n\
Software: 11.2.3319.14 (built 2013-09-19 12:34:24+01:00)     \n\
Hardware: NAS Platform (M2SEKW1339109)                       \n\
board        MMB1                                            \n\
mmb          11.2.3319.14 release (2013-09-19 12:34:24+01:00)\n\
board        MFB1                                            \n\
mfb1hw       MB v0883 WL v002F TD v002F FD v002F TC v0059      \
    RY v0059 TY v0059 IC v0059 WF v00E2 FS v00E2 OS v00E2      \
    WD v00E2 DI v001A FC v0002                               \n\
Serial no    B1339745 (Thu Jan  1 00:00:50 2009)             \n\
board        MCP                                             \n\
Serial no    B1339109 (Thu Jan  1 00:00:49 2009)             \n\
\n"

HNAS_RESULT4 = "\n\
EVS Type    Label            IP Address          Mask             Port  \n\
----------  ---------------  ------------------  ---------------  ------\n\
admin       hnas4040         192.0.2.2           255.255.255.0    eth1  \n\
admin       hnas4040         172.24.44.15        255.255.255.0    eth0  \n\
evs 1       EVSTest1         172.24.44.20        255.255.255.0    ag1   \n\
evs 1       EVSTest1         10.0.0.20           255.255.255.0    ag1   \n\
evs 2       EVSTest2         172.24.44.21        255.255.255.0    ag1   \n\
\n"

HNAS_RESULT5 = "\n\
 ID         Label  EVS     Size     Used       Snapshots  Deduped\
     Avail        Thin  ThinSize  ThinAvail                      \
            FS Type \n\
----  -----------  ---  ------- -------------  ---------  -------\
- -------------  ----  --------  ---------  ---------------------\
------------- \n\
1025   fs01-husvm    1   250 GB 21.4 GB (9%)  0 B (0%)   NA      \
   228 GB (91%)   No                                       32 KB,\
   WFS-2,128 DSBs\n\
1026         gold    1  19.9 GB 2.30 GB (12%    NA       0 B (0%)\
   17.6 GB (88%)  No                         4 KB,WFS-2,128 DSBs,\
   dedupe enabled\n\
1027  large-files    1  19.8 GB 2.43 GB (12%) 0 B (0%)   NA      \
   17.3 GB (88%)  No                                       32 KB,\
   WFS-2,128 DSBs\n\
1028     platinun    1  19.9 GB 2.30 GB (12%)   NA       0 B (0%)\
   17.6 GB (88%)  No                         4 KB,WFS-2,128 DSBs,\
   dedupe enabled\n\
1029       silver    1  19.9 GB 3.19 GB (16%) 0 B (0%)   NA      \
   6.7 GB (84%)   No                                        4 KB,\
   WFS-2,128 DSBs\n\
1030      cinder1    1  40.8 GB 2.24 GB (5%)  0 B (0%)   NA      \
   38.5 GB (95%)  No                                        4 KB,\
   WFS-2,128 DSBs\n\
1031      cinder2    1  39.8 GB 2.23 GB (6%)  0 B (0%)   NA      \
   37.6 GB (94%)  No                                        4 KB,\
   WFS-2,128 DSBs\n\
1024   fs02-husvm    2  49.8 GB 3.54 GB (7%)  0 B (0%)   NA      \
   46.2 GB (93%)  No                                       32 KB,\
   WFS-2,128 DSBs\n\
1032         test    2  3.97 GB 2.12 GB (53%) 0 B (0%)   NA      \
   1.85 GB (47%)  No                                        4 KB,\
   WFS-2,128 DSBs\n\
1058         huge_FS    7  1.50 TB  Not determined\n\
1053              fs-unmounted    4   108 GB     Not mounted \
   NA  943 MB (18%)  39.2 GB (36%)    No                    4 KB,\
   WFS-2,128 DSBs,dedupe enabled\n\
\n"

HNAS_RESULT6 = "\n\
ID       Label   EVS    Size          Used  Snapshots  Deduped         Avail  \
Thin  ThinSize  ThinAvail               FS Type\n\
----  ---------- ---  ------  ------------  ---------  -------  ------------  \
----  --------  ---------  --------------------\n\
1025  fs01-husvm   1  250 GB  21.4 GB (9%)   0 B (0%)       NA  228 GB (91%)  \
  No                       32 KB,WFS-2,128 DSBs\n\
\n"

HNAS_RESULT7 = "\n\
Export configuration:                       \n\
Export name: /export01-husvm                \n\
Export path: /export01-husvm                \n\
File system label: test_hdp                 \n\
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
Transfer setting = Use file system default  \n\
\n"

HNAS_RESULT8 = "Logical unit creation started at 2014-12-24 00:38:30+00:00."
HNAS_RESULT9 = "Logical unit deleted successfully."
HNAS_RESULT10 = ""
HNAS_RESULT11 = "Logical unit expansion started at 2014-12-24 01:25:03+00:00."

HNAS_RESULT12 = "\n\
Alias               : test_iqn                                       \n\
Globally unique name: iqn.2014-12.10.10.10.10:evstest1.cinder-silver \n\
Comment             :                                                \n\
Secret              : test_secret                                    \n\
Authentication      : Enabled                                        \n\
Logical units       : No logical units.                              \n\
\n"

HNAS_RESULT13 = "Logical unit added successfully."
HNAS_RESULT14 = "Logical unit removed successfully."
HNAS_RESULT15 = "Target created successfully."
HNAS_RESULT16 = ""

HNAS_RESULT17 = "\n\
EVS Type    Label            IP Address          Mask             Port  \n\
----------  ---------------  ------------------  ---------------  ------\n\
evs 1       EVSTest1         172.24.44.20        255.255.255.0    ag1   \n\
evs 2       EVSTest1         10.0.0.20           255.255.255.0    ag1   \n\
\n"

HNAS_RESULT18 = "Version: 11.1.3225.01\n\
Directory: /u/u60/_Eng_Axalon_SMU/OfficialBuilds/fish/angel/3225.01/main/bin/\
x86_64_linux-bart_libc-2.7_release\n\
Date: Feb 22 2013, 04:10:09\n\
\n"

HNAS_RESULT19 = "  ID          Label     Size           Used  Snapshots  \
Deduped          Avail  Thin  ThinSize  ThinAvail              FS Type\n\
----  -------------  -------  -------------  ---------  -------  -------------\
----  --------  ---------  -------------------\n\
1025     fs01-husvm   250 GB  47.1 GB (19%)   0 B (0%)       NA   203 GB (81%)\
  No                       4 KB,WFS-2,128 DSBs\n\
1047  manage_test02  19.9 GB  9.29 GB (47%)   0 B (0%)       NA  10.6 GB (53%)\
  No                       4 KB,WFS-2,128 DSBs\n\
1058         huge_FS    7  1.50 TB  Not determined\n\
1053              fs-unmounted    4   108 GB     Not mounted \
   NA  943 MB (18%)  39.2 GB (36%)    No                 4 KB,\
   WFS-2,128 DSBs,dedupe enabled\n\
\n"

HNAS_RESULT20 = "\n\
Alias               : test_iqn                                       \n\
Globally unique name: iqn.2014-12.10.10.10.10:evstest1.cinder-silver \n\
Comment             :                                                \n\
Secret              :                                                \n\
Authentication      : Enabled                                        \n\
Logical units       : No logical units.                              \n\
\n"

HNAS_RESULT20 = "Target does not exist."

HNAS_RESULT21 = "Target created successfully."

HNAS_CMDS = {
    ('ssh', '0.0.0.0', 'supervisor', 'supervisor', 'evsfs', 'list'):
        ["%s" % HNAS_RESULT1, ""],
    ('ssh', '0.0.0.0', 'supervisor', 'supervisor', 'cluster-getmac',):
        ["%s" % HNAS_RESULT2, ""],
    ('ssh', '-version',): ["%s" % HNAS_RESULT18, ""],
    ('ssh', '-u', 'supervisor', '-p', 'supervisor', '0.0.0.0', 'ver',):
    ["%s" % HNAS_RESULT3, ""],
    ('ssh', '0.0.0.0', 'supervisor', 'supervisor', 'ver',):
        ["%s" % HNAS_RESULT3, ""],
    ('ssh', '0.0.0.0', 'supervisor', 'supervisor', 'evsipaddr', '-l'):
        ["%s" % HNAS_RESULT4, ""],
    ('ssh', '0.0.0.0', 'supervisor', 'supervisor', 'df', '-a'):
        ["%s" % HNAS_RESULT5, ""],
    ('ssh', '0.0.0.0', 'supervisor', 'supervisor', 'df', '-f', 'test_hdp'):
        ["%s" % HNAS_RESULT6, ""],
    ('ssh', '0.0.0.0', 'supervisor', 'supervisor', 'for-each-evs', '-q',
     'nfs-export', 'list'):
        ["%s" % HNAS_RESULT7, ""],
    ('ssh', '0.0.0.0', 'supervisor', 'supervisor',
     'console-context', '--evs', '1', 'iscsi-lu', 'add', '-e', 'test_name',
     'test_hdp', '/.cinder/test_name.iscsi',
     '1M'):
        ["%s" % HNAS_RESULT8, ""],
    ('ssh', '0.0.0.0', 'supervisor', 'supervisor',
     'console-context', '--evs', '1', 'iscsi-lu', 'del', '-d', '-f',
     'test_lun'):
        ["%s" % HNAS_RESULT9, ""],
    ('ssh', '0.0.0.0', 'supervisor', 'supervisor',
     'console-context', '--evs', '1', 'file-clone-create', '-f', 'fs01-husvm',
     '/.cinder/test_lu.iscsi', 'cloned_lu'):
        ["%s" % HNAS_RESULT10, ""],
    ('ssh', '0.0.0.0', 'supervisor', 'supervisor',
     'console-context', '--evs', '1', 'iscsi-lu', 'expand', 'expanded_lu',
     '1M'):
        ["%s" % HNAS_RESULT11, ""],
    ('ssh', '0.0.0.0', 'supervisor', 'supervisor',
     'console-context', '--evs', '1', 'iscsi-target', 'list', 'test_iqn'):
        ["%s" % HNAS_RESULT12, ""],
    ('ssh', '0.0.0.0', 'supervisor', 'supervisor',
     'console-context', '--evs', '1', 'iscsi-target', 'addlu', 'test_iqn',
     'test_lun', '0'):
        ["%s" % HNAS_RESULT13, ""],
    ('ssh', '0.0.0.0', 'supervisor', 'supervisor',
     'console-context', '--evs', '1', 'iscsi-target', 'dellu', 'test_iqn',
     0):
        ["%s" % HNAS_RESULT14, ""],
    ('ssh', '0.0.0.0', 'supervisor', 'supervisor',
     'console-context', '--evs', '1', 'iscsi-target', 'add', 'myTarget',
     'secret'):
        ["%s" % HNAS_RESULT15, ""],
    ('ssh', '0.0.0.0', 'supervisor', 'supervisor',
     'console-context', '--evs', '1', 'iscsi-target', 'mod', '-s',
     'test_secret', '-a', 'enable', 'test_iqn'): ["%s" % HNAS_RESULT15, ""],
    ('ssh', '0.0.0.0', 'supervisor', 'supervisor',
     'console-context', '--evs', '1', 'iscsi-lu', 'clone', '-e', 'test_lu',
     'test_clone',
     '/.cinder/test_clone.iscsi'):
        ["%s" % HNAS_RESULT16, ""],
    ('ssh', '0.0.0.0', 'supervisor', 'supervisor', 'evsipaddr', '-e', '1'):
        ["%s" % HNAS_RESULT17, ""]
}

DRV_CONF = {'ssh_enabled': 'True',
            'mgmt_ip0': '0.0.0.0',
            'cluster_admin_ip0': None,
            'ssh_port': '22',
            'ssh_private_key': 'test_key',
            'username': 'supervisor',
            'password': 'supervisor'}

UTILS_EXEC_OUT = ["output: test_cmd", ""]


def m_run_cmd(*args, **kargs):
    print(args)  # noqa
    print(HNAS_CMDS.get(args))  # noqa
    return HNAS_CMDS.get(args)


class HDSHNASBendTest(test.TestCase):

    def __init__(self, *args, **kwargs):
        super(HDSHNASBendTest, self).__init__(*args, **kwargs)

    @mock.patch.object(nfs, 'factory_bend')
    def setUp(self, m_factory_bend):
        super(HDSHNASBendTest, self).setUp()
        self.hnas_bend = hnas_backend.HnasBackend(DRV_CONF)

    @mock.patch('__builtin__.open')
    @mock.patch('os.path.isfile', return_value=True)
    @mock.patch('paramiko.RSAKey.from_private_key_file')
    @mock.patch('paramiko.SSHClient')
    @mock.patch.object(processutils, 'ssh_execute',
                       return_value=(HNAS_RESULT5, ''))
    def test_run_cmd(self, m_ssh_exec, m_ssh_cli, m_pvt_key, m_file, m_open):
        save_hkey_file = CONF.ssh_hosts_key_file
        save_spath = CONF.state_path
        CONF.ssh_hosts_key_file = '/var/lib/cinder/ssh_known_hosts'
        CONF.state_path = '/var/lib/cinder'

        out, err = self.hnas_bend.run_cmd('ssh', '0.0.0.0',
                                          'supervisor', 'supervisor',
                                          'df', '-a')
        self.assertIn('fs01-husvm', out)
        self.assertIn('WFS-2,128 DSBs', out)

        CONF.state_path = save_spath
        CONF.ssh_hosts_key_file = save_hkey_file

    @mock.patch.object(hnas_backend.HnasBackend, 'run_cmd',
                       side_effect=m_run_cmd)
    @mock.patch.object(utils, 'execute', return_value=UTILS_EXEC_OUT)
    def test_get_version(self, m_cmd, m_exec):
        out = self.hnas_bend.get_version("ssh", "1.0", "0.0.0.0", "supervisor",
                                         "supervisor")
        self.assertIn('11.2.3319.14', out)
        self.assertIn('83-68-96-AA-DA-5D', out)

    @mock.patch.object(hnas_backend.HnasBackend, 'run_cmd',
                       side_effect=m_run_cmd)
    def test_get_iscsi_info(self, m_execute):
        out = self.hnas_bend.get_iscsi_info("ssh", "0.0.0.0", "supervisor",
                                            "supervisor")

        self.assertIn('172.24.44.20', out)
        self.assertIn('172.24.44.21', out)
        self.assertIn('10.0.0.20', out)
        self.assertEqual(len(out.split('\n')), 4)

    @mock.patch.object(hnas_backend.HnasBackend, 'run_cmd')
    def test_get_hdp_info(self, m_run_cmd):
        # tests when there is two or more evs
        m_run_cmd.return_value = (HNAS_RESULT5, "")
        out = self.hnas_bend.get_hdp_info("ssh", "0.0.0.0", "supervisor",
                                          "supervisor")

        self.assertEqual(len(out.split('\n')), 10)
        self.assertIn('gold', out)
        self.assertIn('silver', out)
        line1 = out.split('\n')[0]
        self.assertEqual(len(line1.split()), 12)

        # test when there is only one evs
        m_run_cmd.return_value = (HNAS_RESULT19, "")
        out = self.hnas_bend.get_hdp_info("ssh", "0.0.0.0", "supervisor",
                                          "supervisor")
        self.assertEqual(len(out.split('\n')), 3)
        self.assertIn('fs01-husvm', out)
        self.assertIn('manage_test02', out)
        line1 = out.split('\n')[0]
        self.assertEqual(len(line1.split()), 12)

    @mock.patch.object(hnas_backend.HnasBackend, 'run_cmd',
                       side_effect=m_run_cmd)
    def test_get_nfs_info(self, m_run_cmd):
        out = self.hnas_bend.get_nfs_info("ssh", "0.0.0.0", "supervisor",
                                          "supervisor")

        self.assertEqual(len(out.split('\n')), 2)
        self.assertIn('/export01-husvm', out)
        self.assertIn('172.24.44.20', out)
        self.assertIn('10.0.0.20', out)

    @mock.patch.object(hnas_backend.HnasBackend, 'run_cmd',
                       side_effect=m_run_cmd)
    def test_create_lu(self, m_cmd):
        out = self.hnas_bend.create_lu("ssh", "0.0.0.0", "supervisor",
                                       "supervisor", "test_hdp", "1",
                                       "test_name")

        self.assertIn('successfully created', out)

    @mock.patch.object(hnas_backend.HnasBackend, 'run_cmd',
                       side_effect=m_run_cmd)
    def test_delete_lu(self, m_cmd):
        out = self.hnas_bend.delete_lu("ssh", "0.0.0.0", "supervisor",
                                       "supervisor", "test_hdp", "test_lun")

        self.assertIn('deleted successfully', out)

    @mock.patch.object(hnas_backend.HnasBackend, 'run_cmd',
                       side_effect=m_run_cmd)
    def test_create_dup(self, m_cmd):

        out = self.hnas_bend.create_dup("ssh", "0.0.0.0", "supervisor",
                                        "supervisor", "test_lu", "test_hdp",
                                        "1", "test_clone")

        self.assertIn('successfully created', out)

    @mock.patch.object(hnas_backend.HnasBackend, 'run_cmd',
                       side_effect=m_run_cmd)
    def test_file_clone(self, m_cmd):
        out = self.hnas_bend.file_clone("ssh", "0.0.0.0", "supervisor",
                                        "supervisor", "fs01-husvm",
                                        "/.cinder/test_lu.iscsi", "cloned_lu")

        self.assertIn('LUN cloned_lu HDP', out)

    @mock.patch.object(hnas_backend.HnasBackend, 'run_cmd',
                       side_effect=m_run_cmd)
    def test_extend_vol(self, m_cmd):
        out = self.hnas_bend.extend_vol("ssh", "0.0.0.0", "supervisor",
                                        "supervisor", "test_hdp", "test_lun",
                                        "1", "expanded_lu")

        self.assertIn('successfully extended', out)

    @mock.patch.object(hnas_backend.HnasBackend, 'run_cmd',
                       side_effect=m_run_cmd)
    def test_add_iscsi_conn(self, m_cmd):
        out = self.hnas_bend.add_iscsi_conn("ssh", "0.0.0.0", "supervisor",
                                            "supervisor", "test_lun",
                                            "test_hdp", "test_port",
                                            "test_iqn", "test_init")

        self.assertIn('successfully paired', out)

    @mock.patch.object(hnas_backend.HnasBackend, 'run_cmd',
                       side_effect=m_run_cmd)
    def test_del_iscsi_conn(self, m_cmd):
        out = self.hnas_bend.del_iscsi_conn("ssh", "0.0.0.0", "supervisor",
                                            "supervisor", "1", "test_iqn", 0)

        self.assertIn('already deleted', out)

    @mock.patch.object(hnas_backend.HnasBackend, '_get_evs', return_value=0)
    @mock.patch.object(hnas_backend.HnasBackend, 'run_cmd')
    def test_get_targetiqn(self, m_cmd, m_get_evs):

        m_cmd.side_effect = [[HNAS_RESULT12, '']]
        out = self.hnas_bend.get_targetiqn("ssh", "0.0.0.0", "supervisor",
                                           "supervisor", "test_iqn",
                                           "test_hdp", "test_secret")

        self.assertEqual('test_iqn', out)

        m_cmd.side_effect = [[HNAS_RESULT20, ''], [HNAS_RESULT21, '']]
        out = self.hnas_bend.get_targetiqn("ssh", "0.0.0.0", "supervisor",
                                           "supervisor", "test_iqn2",
                                           "test_hdp", "test_secret")

        self.assertEqual('test_iqn2', out)

        m_cmd.side_effect = [[HNAS_RESULT20, ''], [HNAS_RESULT21, '']]
        out = self.hnas_bend.get_targetiqn("ssh", "0.0.0.0", "supervisor",
                                           "supervisor", "test_iqn3",
                                           "test_hdp", "")

        self.assertEqual('test_iqn3', out)

    @mock.patch.object(hnas_backend.HnasBackend, 'run_cmd',
                       side_effect=m_run_cmd)
    def test_set_targetsecret(self, m_execute):
        self.hnas_bend.set_targetsecret("ssh", "0.0.0.0", "supervisor",
                                        "supervisor", "test_iqn",
                                        "test_hdp", "test_secret")

    @mock.patch.object(hnas_backend.HnasBackend, 'run_cmd')
    def test_get_targetsecret(self, m_run_cmd):
        # test when target has secret
        m_run_cmd.return_value = (HNAS_RESULT12, "")
        out = self.hnas_bend.get_targetsecret("ssh", "0.0.0.0", "supervisor",
                                              "supervisor", "test_iqn",
                                              "test_hdp")

        self.assertEqual('test_secret', out)

        # test when target don't have secret
        m_run_cmd.return_value = (HNAS_RESULT20, "")
        out = self.hnas_bend.get_targetsecret("ssh", "0.0.0.0", "supervisor",
                                              "supervisor", "test_iqn",
                                              "test_hdp")
        self.assertEqual('', out)
