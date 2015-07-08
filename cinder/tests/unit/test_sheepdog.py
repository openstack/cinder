
# Copyright (c) 2013 Zelin.io
# Copyright (C) 2015 Nippon Telegraph and Telephone Corporation.
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

import errno

import mock
from oslo_concurrency import processutils
from oslo_utils import importutils
from oslo_utils import units

from cinder import exception
from cinder.i18n import _, _LE
from cinder.image import image_utils
from cinder.openstack.common import fileutils
from cinder import test
from cinder import utils
from cinder.volume import configuration as conf
from cinder.volume.drivers import sheepdog

SHEEP_ADDR = '127.0.0.1'
SHEEP_PORT = 7000


class SheepdogDriverTestDataGenerator(object):
    def sheepdog_cmd_error(self, cmd, exit_code, stdout, stderr):
        return _('(Command: %(cmd)s) '
                 '(Return Code: %(exit_code)s) '
                 '(Stdout: %(stdout)s) '
                 '(Stderr: %(stderr)s)') % \
            {'cmd': cmd, 'exit_code': exit_code,
             'stdout': stdout.replace('\n', '\\n'),
             'stderr': stderr.replace('\n', '\\n')}

    def cmd_dog_vdi_create(self, name, size):
        return ('env', 'LC_ALL=C', 'LANG=C', 'dog', 'vdi', 'create', name,
                '%sG' % size, '-a', SHEEP_ADDR, '-p', str(SHEEP_PORT))

    def cmd_dog_vdi_delete(self, name):
        return ('env', 'LC_ALL=C', 'LANG=C', 'dog', 'vdi', 'delete', name,
                '-a', SHEEP_ADDR, '-p', str(SHEEP_PORT))

    def cmd_dog_vdi_create_snapshot(self, vdiname, snapname):
        return ('env', 'LC_ALL=C', 'LANG=C', 'dog', 'vdi', 'snapshot', '-s',
                snapname, '-a', SHEEP_ADDR, '-p', str(SHEEP_PORT), vdiname)

    def cmd_dog_vdi_delete_snapshot(self, vdiname, snapname):
        return ('env', 'LC_ALL=C', 'LANG=C', 'dog', 'vdi', 'delete', '-s',
                snapname, '-a', SHEEP_ADDR, '-p', str(SHEEP_PORT), vdiname)

    def cmd_qemuimg_vdi_clone(self, src_vdiname, src_snapname, dst_vdiname,
                              size):
        return ('env', 'LC_ALL=C', 'LANG=C', 'qemu-img', 'create', '-b',
                'sheepdog:%(addr)s:%(port)s:%(src_vdiname)s:%(src_snapname)s' %
                {'addr': SHEEP_ADDR, 'port': str(SHEEP_PORT),
                 'src_vdiname': src_vdiname, 'src_snapname': src_snapname},
                'sheepdog:%(addr)s:%(port)s:%(dst_vdiname)s' %
                {'addr': SHEEP_ADDR, 'port': str(SHEEP_PORT),
                 'dst_vdiname': dst_vdiname}, '%sG' % str(size))

    def cmd_dog_vdi_resize(self, name, size):
        return ('env', 'LC_ALL=C', 'LANG=C', 'dog', 'vdi', 'resize', name,
                size, '-a', SHEEP_ADDR, '-p', str(SHEEP_PORT))

    CMD_DOG_CLUSTER_INFO = ('env', 'LC_ALL=C', 'LANG=C', 'dog', 'cluster',
                            'info', '-a', SHEEP_ADDR, '-p', str(SHEEP_PORT))

    TEST_VOLUME = {
        'name': 'volume-00000001',
        'size': 1,
        'volume_name': '1',
        'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66',
        'provider_auth': None,
        'host': 'host@backendsec#unit_test_pool',
        'project_id': 'project',
        'provider_location': 'location',
        'display_name': 'vol1',
        'display_description': 'unit test volume',
        'volume_type_id': None,
        'consistencygroup_id': None,
    }

    TEST_CLONED_VOLUME = {
        'name': 'volume-000000011',
        'size': 1,
        'volume_name': '2',
        'id': 'c13d4599-3433-19ab-23ee-002d3ba50335',
        'provider_auth': None,
        'host': 'host@backendsec#unit_test_pool',
        'project_id': 'project',
        'provider_location': 'location',
        'display_name': 'vol2',
        'display_description': 'unit test cloned volume',
        'volume_type_id': None,
        'consistencygroup_id': None,
    }

    TEST_SNAPSHOT = {
        'volume_name': 'volume-00000002',
        'name': 'test_snap',
    }

    COLLIE_NODE_INFO = """
0 107287605248 3623897354 3%
Total 107287605248 3623897354 3% 54760833024
"""

    COLLIE_CLUSTER_INFO_0_5 = """\
Cluster status: running

Cluster created at Tue Jun 25 19:51:41 2013

Epoch Time           Version
2013-06-25 19:51:41      1 [127.0.0.1:7000, 127.0.0.1:7001, 127.0.0.1:7002]
"""

    COLLIE_CLUSTER_INFO_0_6 = """\
Cluster status: running, auto-recovery enabled

Cluster created at Tue Jun 25 19:51:41 2013

Epoch Time           Version
2013-06-25 19:51:41      1 [127.0.0.1:7000, 127.0.0.1:7001, 127.0.0.1:7002]
"""

    DOG_CLUSTER_RUNNING = """\
Cluster status: running, auto-recovery enabled

Cluster created at Thu Jun 18 17:24:56 2015

Epoch Time           Version [Host:Port:V-Nodes,,,]
2015-06-18 17:24:56      1 [127.0.0.1:7000:128, 127.0.0.1:7001:128,\
 127.0.0.1:7002:128]
"""

    DOG_CLUSTER_INFO_TO_BE_FORMATTED = """\
Cluster status: Waiting for cluster to be formatted
"""

    DOG_CLUSTER_INFO_WAITING_OTHER_NODES = """\
Cluster status: Waiting for other nodes to join cluster

Cluster created at Thu Jun 18 17:24:56 2015

Epoch Time           Version [Host:Port:V-Nodes,,,]
2015-06-18 17:24:56      1 [127.0.0.1:7000:128, 127.0.0.1:7001:128]
"""

    DOG_VDI_CREATE_VDI_ALREADY_EXISTS = """\
Failed to create VDI %(vdiname)s: VDI exists already
"""

    DOG_VDI_SNAPSHOT_VDI_NOT_FOUND = """\
Failed to create snapshot for volume-00000001: No VDI found
"""

    DOG_VDI_SNAPSHOT_ALREADY_EXISTED = """\
Failed to create snapshot for volume-00000002, \
maybe snapshot id (0) or tag (test_snap) is existed
"""

    DOG_VDI_SNAPSHOT_TAG_NOT_FOUND = """\
Failed to open VDI volume-00000002 \
(snapshot id: 0 snapshot tag: test_snap): Failed to find requested tag
"""

    DOG_VDI_SNAPSHOT_VOLUME_NOT_FOUND = """\
Failed to open VDI volume-00000002 \
(snapshot id: 0 snapshot tag: test_snap): No VDI found
"""

    DOG_VDI_RESIZE_SIZE_SHRINK = """\
Shrinking VDIs is not implemented
"""

    DOG_VDI_RESIZE_TOO_LARGE = """\
New VDI size is too large. This volume's max size is 4398046511104
"""

    DOG_COMMAND_ERROR_VDI_NOT_EXISTS = """\
Failed to open VDI vdiname (snapshot id: 0 snapshot tag: ): No VDI found
"""

    DOG_COMMAND_ERROR_FAIL_TO_CONNECT = """\
failed to connect to 127.0.0.1:7000: Connection refused
failed to connect to 127.0.0.1:7000: Connection refused
Failed to get node list
"""

    QEMU_IMG_VDI_ALREADY_EXISTS = """\
qemu-img: sheepdog:volume-00000001: VDI exists already,
"""

    QEMU_IMG_VDI_NOT_FOUND = """\
qemu-img: sheepdog:volume-00000001: cannot get vdi info, No vdi found, \
volume-00000002 test-snap
"""

    QEMU_IMG_SNAPSHOT_NOT_FOUND = """\
qemu-img: sheepdog:volume-00000001: cannot get vdi info, Failed to find \
the requested tag, volume-00000002 snap-name
"""

    QEMU_IMG_SIZE_TOO_LARGE = """\
qemu-img: sheepdog:volume-00000001: An image is too large. \
The maximum image size is 4096GB
"""

    QEMU_IMG_FAILED_TO_CONNECT = """\
qemu-img: sheepdog::volume-00000001: \
Failed to connect socket: Connection refused
"""

    QEMU_IMG_FILE_NOT_FOUND = """\
qemu-img: Could not open '/tmp/volume-00000001': \
Could not open '/tmp/volume-00000001': \
No such file or directory
"""

    QEMU_IMG_PERMISSION_DENIED = """\
qemu-img: Could not open '/tmp/volume-00000001': \
Could not open '/tmp/volume-00000001': \
Permission denied
"""

    QEMU_IMG_ERROR_INVALID_FORMAT = """\
qemu-img: Unknown file format 'dummy'
"""

    QEMU_IMG_INVALID_DRIVER = """\
qemu-img: Could not open '/tmp/volume-00000001': \
Unknown driver 'dummy'
"""

    IS_CLONEABLE_TRUE = """\
s a720b3c0-d1f0-11e1-9b23-0800200c9a66 1 1 1 1 1 1 1 glance-image 22
"""

    IS_CLONEABLE_FALSE = """\
  a720b3c0-d1f0-11e1-9b23-0800200c9a66 1 1 1 1 1 1 1 dummy-image 22
"""


class FakeImageService(object):
    def download(self, context, image_id, path):
        pass


class SheepdogIOWrapperTestCase(test.TestCase):
    def setUp(self):
        super(SheepdogIOWrapperTestCase, self).setUp()
        self.volume = {'name': 'volume-2f9b2ff5-987b-4412-a91c-23caaf0d5aff'}
        self.snapshot_name = 'snapshot-bf452d80-068a-43d7-ba9f-196cf47bd0be'

        self.vdi_wrapper = sheepdog.SheepdogIOWrapper(
            self.volume)
        self.snapshot_wrapper = sheepdog.SheepdogIOWrapper(
            self.volume, self.snapshot_name)

        self.execute = mock.MagicMock()
        self.stubs.Set(processutils, 'execute', self.execute)

    def test_init(self):
        self.assertEqual(self.volume['name'], self.vdi_wrapper._vdiname)
        self.assertIsNone(self.vdi_wrapper._snapshot_name)
        self.assertEqual(0, self.vdi_wrapper._offset)

        self.assertEqual(self.snapshot_name,
                         self.snapshot_wrapper._snapshot_name)

    def test_inc_offset_tell(self):
        self.vdi_wrapper._inc_offset(10)
        self.vdi_wrapper._inc_offset(10)
        self.assertEqual(20, self.vdi_wrapper.tell())

    def test_execute(self):
        cmd = ('cmd1', 'arg1')
        data = 'data1'

        self.vdi_wrapper._execute(cmd, data)

        self.execute.assert_called_once_with(*cmd, process_input=data)

    def test_execute_error(self):
        cmd = ('cmd1', 'arg1')
        data = 'data1'
        self.stubs.Set(processutils, 'execute',
                       mock.MagicMock(side_effect=OSError))

        args = (cmd, data)
        self.assertRaises(exception.VolumeDriverException,
                          self.vdi_wrapper._execute,
                          *args)

    def test_read_vdi(self):
        self.vdi_wrapper.read()
        self.execute.assert_called_once_with(
            'dog', 'vdi', 'read', self.volume['name'], 0, process_input=None)

    def test_write_vdi(self):
        data = 'data1'

        self.vdi_wrapper.write(data)

        self.execute.assert_called_once_with(
            'dog', 'vdi', 'write',
            self.volume['name'], 0, len(data),
            process_input=data)
        self.assertEqual(len(data), self.vdi_wrapper.tell())

    def test_read_snapshot(self):
        self.snapshot_wrapper.read()
        self.execute.assert_called_once_with(
            'dog', 'vdi', 'read', '-s', self.snapshot_name,
            self.volume['name'], 0,
            process_input=None)

    def test_seek(self):
        self.vdi_wrapper.seek(12345)
        self.assertEqual(12345, self.vdi_wrapper.tell())

        self.vdi_wrapper.seek(-2345, whence=1)
        self.assertEqual(10000, self.vdi_wrapper.tell())

        # This results in negative offset.
        self.assertRaises(IOError, self.vdi_wrapper.seek, -20000, whence=1)

    def test_flush(self):
        # flush does noting.
        self.vdi_wrapper.flush()
        self.assertFalse(self.execute.called)

    def test_fileno(self):
        self.assertRaises(IOError, self.vdi_wrapper.fileno)


# test for SheeepdogClient Class
class SheepdogClientTestCase(test.TestCase):
    def setUp(self):
        super(SheepdogClientTestCase, self).setUp()
        self._cfg = conf.Configuration(None)
        self._cfg.sheepdog_store_address = SHEEP_ADDR
        self._cfg.sheepdog_store_port = SHEEP_PORT
        self.driver = sheepdog.SheepdogDriver(configuration=self._cfg)
        db_driver = self.driver.configuration.db_driver
        self.db = importutils.import_module(db_driver)
        self.driver.db = self.db
        self.driver.do_setup(None)
        self.test_data = SheepdogDriverTestDataGenerator()
        self.client = self.driver.client
        self._vdiname = self.test_data.TEST_VOLUME['name']
        self._vdisize = self.test_data.TEST_VOLUME['size']
        self._src_vdiname = self.test_data.TEST_SNAPSHOT['volume_name']
        self._snapname = self.test_data.TEST_SNAPSHOT['name']

    @mock.patch.object(utils, 'execute')
    @mock.patch.object(sheepdog, 'LOG')
    def test_run_dog(self, fake_logger, fake_execute):
        args = ('cluster', 'info')

        # Test1: success
        expected_cmd = self.test_data.CMD_DOG_CLUSTER_INFO
        fake_execute.return_value = ('', '')
        self.client._run_dog(*args)
        fake_execute.assert_called_once_with(*expected_cmd)

        # Test2: os_error because dog command is not found
        fake_logger.reset_mock()
        fake_execute.reset_mock()
        expected_msg = 'No such file or directory'
        expected_errno = errno.ENOENT
        fake_execute.side_effect = OSError(expected_errno, expected_msg)
        self.assertRaises(OSError, self.client._run_dog, *args)
        self.assertTrue(fake_logger.error.called)

    @mock.patch.object(utils, 'execute')
    @mock.patch.object(sheepdog, 'LOG')
    def test_run_qemu_img(self, fake_logger, fake_execute):
        # Test1: success pattern
        # multiple part of args mathches the prefix and
        # volume name is matched the prefix unfortunately
        expected_cmd = ('env', 'LC_ALL=C', 'LANG=C',
                        'qemu-img', 'create', '-b',
                        'sheepdog:%(addr)s:%(port)s:sheepdog:snap' %
                        {'addr': SHEEP_ADDR, 'port': SHEEP_PORT},
                        'sheepdog:%(addr)s:%(port)s:clone' %
                        {'addr': SHEEP_ADDR, 'port': SHEEP_PORT}, '10G')
        fake_execute.return_value = ('', '')
        self.client._run_qemu_img('create', '-b', 'sheepdog:sheepdog:snap',
                                  'sheepdog:clone', '10G')
        fake_execute.assert_called_once_with(*expected_cmd)

        # Test2: os_error because qemu-img command is not found
        fake_logger.reset_mock()
        fake_execute.reset_mock()
        args = ('create', 'dummy')
        expected_msg = 'No such file or directory'
        expected_errno = errno.ENOENT
        fake_execute.side_effect = OSError(expected_errno, expected_msg)
        self.assertRaises(OSError, self.client._run_qemu_img, *args)
        self.assertTrue(fake_logger.error.called)

        # Test3: os_error caused by unknown error
        fake_logger.reset_mock()
        fake_execute.reset_mock()
        expected_msg = 'unknown'
        expected_errno = errno.EPERM
        fake_execute.side_effect = OSError(expected_errno, expected_msg)
        self.assertRaises(OSError, self.client._run_qemu_img, *args)
        self.assertTrue(fake_logger.error.called)

        # Test4: process execution error
        fake_logger.reset_mock()
        fake_execute.reset_mock()
        cmd = ('qemu-img', 'create', 'dummy')
        exit_code = 1
        stdout = 'stdout dummy'
        stderr = 'stderr dummy'
        expected_msg = self.test_data.sheepdog_cmd_error(
            cmd=cmd, exit_code=exit_code, stdout=stdout, stderr=stderr)
        fake_execute.side_effect = processutils.ProcessExecutionError(
            cmd=cmd, exit_code=exit_code, stdout=stdout, stderr=stderr)
        ex = self.assertRaises(exception.SheepdogCmdError,
                               self.client._run_qemu_img, *args)
        self.assertEqual(expected_msg, ex.msg)

    @mock.patch.object(sheepdog.SheepdogClient, '_run_dog')
    @mock.patch.object(sheepdog, 'LOG')
    def test_check_cluster_status(self, fake_logger, fake_execute):
        cmd = self.test_data.CMD_DOG_CLUSTER_INFO

        # Test1: cluster status is running with latest version
        expected_cmd = ('cluster', 'info')
        stdout = self.test_data.DOG_CLUSTER_RUNNING
        stderr = ''
        fake_execute.return_value = (stdout, stderr)
        self.client.check_cluster_status()
        fake_execute.assert_called_once_with(*expected_cmd)
        self.assertTrue(fake_logger.debug.called)

        # Test2: cluster status is runnning with version 0.5
        fake_logger.reset_mock()
        fake_execute.reset_mock()
        stdout = self.test_data.COLLIE_CLUSTER_INFO_0_5
        fake_execute.return_value = (stdout, stderr)
        self.client.check_cluster_status()

        # Test3: cluster status is runnning with version 0.6
        fake_logger.reset_mock()
        fake_execute.reset_mock()
        stdout = self.test_data.COLLIE_CLUSTER_INFO_0_6
        fake_execute.return_value = (stdout, stderr)
        self.client.check_cluster_status()

        # Test4: cluster status is waiting to be formatted
        fake_logger.reset_mock()
        fake_execute.reset_mock()
        stdout = self.test_data.DOG_CLUSTER_INFO_TO_BE_FORMATTED
        expected_reason = _LE('Cluster is not formatted. '
                              'You should probably perform '
                              '"dog cluster format".')
        fake_execute.return_value = (stdout, stderr)
        ex = self.assertRaises(exception.SheepdogError,
                               self.client.check_cluster_status)
        self.assertEqual(expected_reason, ex.kwargs['reason'])

        # Test5: cluster status is waiting for all node to join cluster
        fake_logger.reset_mock()
        fake_execute.reset_mock()
        stdout = self.test_data.DOG_CLUSTER_INFO_WAITING_OTHER_NODES
        expected_reason = _LE('Waiting for all nodes to join cluster. '
                              'Ensure all sheep daemons are running.')
        fake_execute.return_value = (stdout, stderr)
        ex = self.assertRaises(exception.SheepdogError,
                               self.client.check_cluster_status)
        self.assertEqual(expected_reason, ex.kwargs['reason'])

        # Test6: error is caused by failing to connect to sheep process
        fake_logger.reset_mock()
        fake_execute.reset_mock()
        exit_code = 2
        stdout = 'stdout_dummy'
        stderr = self.test_data.DOG_COMMAND_ERROR_FAIL_TO_CONNECT
        expected_msg = self.test_data.sheepdog_cmd_error(cmd=cmd,
                                                         exit_code=exit_code,
                                                         stdout=stdout,
                                                         stderr=stderr)
        fake_execute.side_effect = exception.SheepdogCmdError(
            cmd=cmd, exit_code=exit_code, stdout=stdout.replace('\n', '\\n'),
            stderr=stderr.replace('\n', '\\n'))
        ex = self.assertRaises(exception.SheepdogCmdError,
                               self.client.check_cluster_status)
        self.assertTrue(fake_logger.error.called)
        self.assertEqual(expected_msg, ex.msg)

        # Test7: unknown error
        fake_logger.reset_mock()
        fake_execute.reset_mock()
        exit_code = 2
        stdout = 'stdout_dummy'
        stderr = 'stdout_dummy'
        expected_msg = self.test_data.sheepdog_cmd_error(cmd=cmd,
                                                         exit_code=exit_code,
                                                         stdout=stdout,
                                                         stderr=stderr)
        fake_execute.side_effect = exception.SheepdogCmdError(
            cmd=cmd, exit_code=exit_code, stdout=stdout, stderr=stderr)
        ex = self.assertRaises(exception.SheepdogCmdError,
                               self.client.check_cluster_status)
        self.assertEqual(expected_msg, ex.msg)

    @mock.patch.object(sheepdog.SheepdogClient, '_run_dog')
    @mock.patch.object(sheepdog, 'LOG')
    def test_create(self, fake_logger, fake_execute):
        cmd = self.test_data.cmd_dog_vdi_create(self._vdiname, self._vdisize)

        # Test1: create a Sheepdog VDI successfully
        expected_cmd = ('vdi', 'create', self._vdiname, '%sG' % self._vdisize)
        fake_execute.return_value = ('', '')
        self.client.create(self._vdiname, self._vdisize)
        fake_execute.assert_called_once_with(*expected_cmd)

        # Test2: fail to connect to sheep process
        fake_logger.reset_mock()
        fake_execute.reset_mock()
        exit_code = 2
        stdout = ''
        stderr = self.test_data.DOG_COMMAND_ERROR_FAIL_TO_CONNECT
        expected_msg = self.test_data.sheepdog_cmd_error(
            cmd=cmd, exit_code=exit_code, stdout=stdout, stderr=stderr)
        fake_execute.side_effect = exception.SheepdogCmdError(
            cmd=cmd, exit_code=exit_code, stdout=stdout.replace('\n', '\\n'),
            stderr=stderr.replace('\n', '\\n'))
        ex = self.assertRaises(exception.SheepdogCmdError, self.client.create,
                               self._vdiname, self._vdisize)
        self.assertTrue(fake_logger.error.called)
        self.assertEqual(expected_msg, ex.msg)

        # Test3: the VDI which has the same vdiname is already exists
        fake_logger.reset_mock()
        fake_execute.reset_mock()
        exit_code = 1
        stdout = ''
        stderr = self.test_data.DOG_VDI_CREATE_VDI_ALREADY_EXISTS % \
            {'vdiname': self._vdiname}
        expected_msg = self.test_data.sheepdog_cmd_error(
            cmd=cmd, exit_code=exit_code, stdout=stdout, stderr=stderr)
        fake_execute.side_effect = exception.SheepdogCmdError(
            cmd=cmd, exit_code=exit_code, stdout=stdout.replace('\n', '\\n'),
            stderr=stderr.replace('\n', '\\n'))
        ex = self.assertRaises(exception.SheepdogCmdError, self.client.create,
                               self._vdiname, self._vdisize)
        self.assertTrue(fake_logger.error.called)
        self.assertEqual(expected_msg, ex.msg)

        # Test4: unknown error
        fake_logger.reset_mock()
        fake_execute.reset_mock()
        exit_code = 1
        stdout = 'stdout_dummy'
        stderr = 'stderr_dummy'
        expected_msg = self.test_data.sheepdog_cmd_error(
            cmd=cmd, exit_code=exit_code, stdout=stdout, stderr=stderr)
        fake_execute.side_effect = exception.SheepdogCmdError(
            cmd=cmd, exit_code=exit_code, stdout=stdout.replace('\n', '\\n'),
            stderr=stderr.replace('\n', '\\n'))
        ex = self.assertRaises(exception.SheepdogCmdError, self.client.create,
                               self._vdiname, self._vdisize)
        self.assertTrue(fake_logger.error.called)
        self.assertEqual(expected_msg, ex.msg)

    @mock.patch.object(sheepdog.SheepdogClient, '_run_dog')
    @mock.patch.object(sheepdog, 'LOG')
    def test_delete(self, fake_logger, fake_execute):
        cmd = self.test_data.cmd_dog_vdi_delete(self._vdiname)

        # Test1: delete a Sheepdog VDI successfully
        expected_cmd = ('vdi', 'delete', self._vdiname)
        fake_execute.return_value = ('', '')
        self.client.delete(self._vdiname)
        fake_execute.assert_called_once_with(*expected_cmd)

        # Test2: the target VDI does not exist
        fake_logger.reset_mock()
        fake_execute.reset_mock()
        stdout = ''
        stderr = self.test_data.DOG_COMMAND_ERROR_VDI_NOT_EXISTS
        fake_execute.return_value = (stdout, stderr)
        self.client.delete(self._vdiname)
        self.assertTrue(fake_logger.warning.called)

        # XXX (tishizaki) Sheepdog's bug case.
        # details was written to Sheepdog driver code.
        # Test3: failed to connect sheep process
        fake_logger.reset_mock()
        fake_execute.reset_mock()
        stdout = ''
        stderr = self.test_data.DOG_COMMAND_ERROR_FAIL_TO_CONNECT
        expected_reason = (_LE('Failed to connect sheep daemon. '
                           'addr: %(addr)s, port: %(port)s'),
                           {'addr': SHEEP_ADDR, 'port': SHEEP_PORT})
        fake_execute.return_value = (stdout, stderr)
        ex = self.assertRaises(exception.SheepdogError,
                               self.client.delete, self._vdiname)
        self.assertEqual(expected_reason, ex.kwargs['reason'])

        # Test4: failed to connect sheep process
        fake_logger.reset_mock()
        fake_execute.reset_mock()
        exit_code = 2
        stdout = 'stdout_dummy'
        stderr = self.test_data.DOG_COMMAND_ERROR_FAIL_TO_CONNECT
        expected_msg = self.test_data.sheepdog_cmd_error(cmd=cmd,
                                                         exit_code=exit_code,
                                                         stdout=stdout,
                                                         stderr=stderr)
        fake_execute.side_effect = exception.SheepdogCmdError(
            cmd=cmd, exit_code=exit_code, stdout=stdout.replace('\n', '\\n'),
            stderr=stderr.replace('\n', '\\n'))
        ex = self.assertRaises(exception.SheepdogCmdError,
                               self.client.delete, self._vdiname)
        self.assertTrue(fake_logger.error.called)
        self.assertEqual(expected_msg, ex.msg)

        # Test5: unknown error
        fake_logger.reset_mock()
        fake_execute.reset_mock()
        exit_code = 2
        stdout = 'stdout_dummy'
        stderr = 'stderr_dummy'
        expected_msg = self.test_data.sheepdog_cmd_error(cmd=cmd,
                                                         exit_code=exit_code,
                                                         stdout=stdout,
                                                         stderr=stderr)
        fake_execute.side_effect = exception.SheepdogCmdError(
            cmd=cmd, exit_code=exit_code, stdout=stdout.replace('\n', '\\n'),
            stderr=stderr.replace('\n', '\\n'))
        ex = self.assertRaises(exception.SheepdogCmdError,
                               self.client.delete, self._vdiname)
        self.assertTrue(fake_logger.error.called)
        self.assertEqual(expected_msg, ex.msg)

    @mock.patch.object(sheepdog.SheepdogClient, '_run_dog')
    @mock.patch.object(sheepdog, 'LOG')
    def test_create_snapshot(self, fake_logger, fake_execute):
        args = (self._src_vdiname, self._snapname)
        cmd = self.test_data.cmd_dog_vdi_create_snapshot(*args)

        # Test1: create a snapshot of a VDI successfully
        expected_cmd = ('vdi', 'snapshot', '-s', self._snapname,
                        self._src_vdiname)
        fake_execute.return_value = ('', '')
        self.client.create_snapshot(*args)
        fake_execute.assert_called_once_with(*expected_cmd)

        # Test2: failed to connect sheep process
        fake_logger.reset_mock()
        fake_execute.reset_mock()
        exit_code = 2
        stdout = ''
        stderr = self.test_data.DOG_COMMAND_ERROR_FAIL_TO_CONNECT
        expected_msg = self.test_data.sheepdog_cmd_error(cmd=cmd,
                                                         exit_code=exit_code,
                                                         stdout=stdout,
                                                         stderr=stderr)
        fake_execute.side_effect = exception.SheepdogCmdError(
            cmd=cmd, exit_code=exit_code, stdout=stdout.replace('\n', '\\n'),
            stderr=stderr.replace('\n', '\\n'))
        ex = self.assertRaises(exception.SheepdogCmdError,
                               self.client.create_snapshot, *args)
        self.assertTrue(fake_logger.error.called)
        self.assertEqual(expected_msg, ex.msg)

        # Test3: src VDI is not found
        fake_logger.reset_mock()
        fake_execute.reset_mock()
        exit_code = 1
        stderr = self.test_data.DOG_VDI_SNAPSHOT_VDI_NOT_FOUND
        expected_msg = self.test_data.sheepdog_cmd_error(cmd=cmd,
                                                         exit_code=exit_code,
                                                         stdout=stdout,
                                                         stderr=stderr)
        fake_execute.side_effect = exception.SheepdogCmdError(
            cmd=cmd, exit_code=exit_code, stdout=stdout.replace('\n', '\\n'),
            stderr=stderr.replace('\n', '\\n'))
        ex = self.assertRaises(exception.SheepdogCmdError,
                               self.client.create_snapshot, *args)
        self.assertTrue(fake_logger.error.called)
        self.assertEqual(expected_msg, ex.msg)

        # Test4: snapshot name is already used
        fake_logger.reset_mock()
        fake_execute.reset_mock()
        exit_code = 1
        stdout = 'stdout_dummy'
        stderr = self.test_data.DOG_VDI_SNAPSHOT_ALREADY_EXISTED
        expected_msg = self.test_data.sheepdog_cmd_error(cmd=cmd,
                                                         exit_code=exit_code,
                                                         stdout=stdout,
                                                         stderr=stderr)
        fake_execute.side_effect = exception.SheepdogCmdError(
            cmd=cmd, exit_code=exit_code, stdout=stdout.replace('\n', '\\n'),
            stderr=stderr.replace('\n', '\\n'))
        ex = self.assertRaises(exception.SheepdogCmdError,
                               self.client.create_snapshot, *args)
        self.assertTrue(fake_logger.error.called)
        self.assertEqual(expected_msg, ex.msg)

        # Test5: snapshot name is already used
        fake_logger.reset_mock()
        fake_execute.reset_mock()
        exit_code = 1
        stdout = 'stdout_dummy'
        stderr = 'unknown_error'
        expected_msg = self.test_data.sheepdog_cmd_error(cmd=cmd,
                                                         exit_code=exit_code,
                                                         stdout=stdout,
                                                         stderr=stderr)
        fake_execute.side_effect = exception.SheepdogCmdError(
            cmd=cmd, exit_code=exit_code, stdout=stdout.replace('\n', '\\n'),
            stderr=stderr.replace('\n', '\\n'))
        ex = self.assertRaises(exception.SheepdogCmdError,
                               self.client.create_snapshot, *args)
        self.assertTrue(fake_logger.error.called)
        self.assertEqual(expected_msg, ex.msg)

    @mock.patch.object(sheepdog.SheepdogClient, '_run_dog')
    @mock.patch.object(sheepdog, 'LOG')
    def test_delete_snapshot(self, fake_logger, fake_execute):
        args = (self._src_vdiname, self._snapname)
        cmd = self.test_data.cmd_dog_vdi_delete_snapshot(*args)

        # Test1: delete a snapshot of a VDI successfully
        expected_cmd = ('vdi', 'delete', '-s', self._snapname,
                        self._src_vdiname)
        fake_execute.return_value = ('', '')
        self.client.delete_snapshot(*args)
        fake_execute.assert_called_once_with(*expected_cmd)

        # Test2: the snapshot name is not found
        fake_logger.reset_mock()
        fake_execute.reset_mock()
        stdout = ''
        stderr = self.test_data.DOG_VDI_SNAPSHOT_TAG_NOT_FOUND
        fake_execute.return_value = (stdout, stderr)
        self.client.delete_snapshot(*args)
        self.assertTrue(fake_logger.warning.called)

        # Test3: the src VDI name of the snapshot is not found
        fake_logger.reset_mock()
        fake_execute.reset_mock()
        stdout = ''
        stderr = self.test_data.DOG_VDI_SNAPSHOT_VOLUME_NOT_FOUND
        fake_execute.return_value = (stdout, stderr)
        self.client.delete_snapshot(*args)
        self.assertTrue(fake_logger.warning.called)

        # Test4: failed to connect sheep process
        fake_logger.reset_mock()
        fake_execute.reset_mock()
        exit_code = 2
        stderr = self.test_data.DOG_COMMAND_ERROR_FAIL_TO_CONNECT
        expected_msg = self.test_data.sheepdog_cmd_error(cmd=cmd,
                                                         exit_code=exit_code,
                                                         stdout=stdout,
                                                         stderr=stderr)
        fake_execute.side_effect = exception.SheepdogCmdError(
            cmd=cmd, exit_code=exit_code, stdout=stdout.replace('\n', '\\n'),
            stderr=stderr.replace('\n', '\\n'))
        ex = self.assertRaises(exception.SheepdogCmdError,
                               self.client.delete_snapshot, *args)
        self.assertTrue(fake_logger.error.called)
        self.assertEqual(expected_msg, ex.msg)

        # Test5: unknown error
        fake_logger.reset_mock()
        fake_execute.reset_mock()
        stdout = 'stdout_dummy'
        stderr = 'unknown_error'
        expected_msg = self.test_data.sheepdog_cmd_error(cmd=cmd,
                                                         exit_code=exit_code,
                                                         stdout=stdout,
                                                         stderr=stderr)
        fake_execute.side_effect = exception.SheepdogCmdError(
            cmd=cmd, exit_code=exit_code, stdout=stdout.replace('\n', '\\n'),
            stderr=stderr.replace('\n', '\\n'))
        ex = self.assertRaises(exception.SheepdogCmdError,
                               self.client.delete_snapshot, *args)
        self.assertTrue(fake_logger.error.called)
        self.assertEqual(expected_msg, ex.msg)

    @mock.patch.object(sheepdog.SheepdogClient, '_run_qemu_img')
    @mock.patch.object(sheepdog, 'LOG')
    def test_clone(self, fake_logger, fake_execute):
        args = (self._src_vdiname, self._snapname,
                self._vdiname, self._vdisize)
        cmd = self.test_data.cmd_qemuimg_vdi_clone(*args)

        # Test1: clone a Sheepdog VDI from snapshot successfully
        src_volume = 'sheepdog:%(src_vdiname)s:%(snapname)s' % {
            'src_vdiname': self._src_vdiname,
            'snapname': self._snapname
        }
        dst_volume = 'sheepdog:%s' % self._vdiname
        expected_cmd = ('create', '-b', src_volume, dst_volume,
                        '%sG' % self._vdisize)
        fake_execute.return_code = ("", "")
        self.client.clone(*args)
        fake_execute.assert_called_once_with(*expected_cmd)

        # Test2: fail to connect sheep process
        fake_logger.reset_mock()
        fake_execute.reset_mock()
        exit_code = 2
        stdout = 'stdout_dummy'
        stderr = self.test_data.QEMU_IMG_FAILED_TO_CONNECT
        expected_msg = self.test_data.sheepdog_cmd_error(cmd=cmd,
                                                         exit_code=exit_code,
                                                         stdout=stdout,
                                                         stderr=stderr)
        fake_execute.side_effect = exception.SheepdogCmdError(
            cmd=cmd, exit_code=exit_code, stdout=stdout.replace('\n', '\\n'),
            stderr=stderr.replace('\n', '\\n'))
        ex = self.assertRaises(exception.SheepdogCmdError, self.client.clone,
                               *args)
        self.assertTrue(fake_logger.error.called)
        self.assertEqual(expected_msg, ex.msg)

        # Test3: dst vdiname already exists
        fake_logger.reset_mock()
        fake_execute.reset_mock()
        stderr = self.test_data.QEMU_IMG_VDI_ALREADY_EXISTS
        expected_msg = self.test_data.sheepdog_cmd_error(cmd=cmd,
                                                         exit_code=exit_code,
                                                         stdout=stdout,
                                                         stderr=stderr)
        fake_execute.side_effect = exception.SheepdogCmdError(
            cmd=cmd, exit_code=exit_code, stdout=stdout.replace('\n', '\\n'),
            stderr=stderr.replace('\n', '\\n'))
        ex = self.assertRaises(exception.SheepdogCmdError, self.client.clone,
                               *args)
        self.assertTrue(fake_logger.error.called)
        self.assertEqual(expected_msg, ex.msg)

        # Test4: src vdi is not found
        fake_logger.reset_mock()
        fake_execute.reset_mock()
        stderr = self.test_data.QEMU_IMG_VDI_NOT_FOUND
        expected_msg = self.test_data.sheepdog_cmd_error(cmd=cmd,
                                                         exit_code=exit_code,
                                                         stdout=stdout,
                                                         stderr=stderr)
        fake_execute.side_effect = exception.SheepdogCmdError(
            cmd=cmd, exit_code=exit_code, stdout=stdout.replace('\n', '\\n'),
            stderr=stderr.replace('\n', '\\n'))
        ex = self.assertRaises(exception.SheepdogCmdError, self.client.clone,
                               *args)
        self.assertTrue(fake_logger.error.called)
        self.assertEqual(expected_msg, ex.msg)

        # Test5: src snapshot is not found
        fake_logger.reset_mock()
        fake_execute.reset_mock()
        stderr = self.test_data.QEMU_IMG_SNAPSHOT_NOT_FOUND
        expected_msg = self.test_data.sheepdog_cmd_error(cmd=cmd,
                                                         exit_code=exit_code,
                                                         stdout=stdout,
                                                         stderr=stderr)
        fake_execute.side_effect = exception.SheepdogCmdError(
            cmd=cmd, exit_code=exit_code, stdout=stdout.replace('\n', '\\n'),
            stderr=stderr.replace('\n', '\\n'))
        ex = self.assertRaises(exception.SheepdogCmdError, self.client.clone,
                               *args)
        self.assertTrue(fake_logger.error.called)
        self.assertEqual(expected_msg, ex.msg)

        # Test6: the size of the cloned volume is too large
        fake_logger.reset_mock()
        fake_execute.reset_mock()
        stderr = self.test_data.QEMU_IMG_SIZE_TOO_LARGE
        expected_msg = self.test_data.sheepdog_cmd_error(cmd=cmd,
                                                         exit_code=exit_code,
                                                         stdout=stdout,
                                                         stderr=stderr)
        fake_execute.side_effect = exception.SheepdogCmdError(
            cmd=cmd, exit_code=exit_code, stdout=stdout.replace('\n', '\\n'),
            stderr=stderr.replace('\n', '\\n'))
        ex = self.assertRaises(exception.SheepdogCmdError, self.client.clone,
                               *args)
        self.assertTrue(fake_logger.error.called)
        self.assertEqual(expected_msg, ex.msg)

        # Test7: unknown error
        fake_logger.reset_mock()
        fake_execute.reset_mock()
        stderr = 'stderr_dummy'
        expected_msg = self.test_data.sheepdog_cmd_error(cmd=cmd,
                                                         exit_code=exit_code,
                                                         stdout=stdout,
                                                         stderr=stderr)
        fake_execute.side_effect = exception.SheepdogCmdError(
            cmd=cmd, exit_code=exit_code, stdout=stdout.replace('\n', '\\n'),
            stderr=stderr.replace('\n', '\\n'))
        ex = self.assertRaises(exception.SheepdogCmdError, self.client.clone,
                               *args)
        self.assertTrue(fake_logger.error.called)
        self.assertEqual(expected_msg, ex.msg)

    @mock.patch.object(sheepdog.SheepdogClient, '_run_dog')
    @mock.patch.object(sheepdog, 'LOG')
    def test_resize(self, fake_logger, fake_execute):

        # Test1: resize a Sheepdog VDI successfully
        expected_cmd = ('vdi', 'resize', self._vdiname, 10 * 1024 ** 3)
        fake_execute.return_value = ('', '')
        self.client.resize(self._vdiname, 10)
        fake_execute.assert_called_once_with(*expected_cmd)

        # Test2: failed to connect sheep process
        fake_logger.reset_mock()
        fake_execute.reset_mock()
        cmd = self.test_data.cmd_dog_vdi_resize(self._vdiname, 10 * 1024 ** 3)
        exit_code = 2
        stdout = 'stdout_dummy'
        stderr = self.test_data.DOG_COMMAND_ERROR_FAIL_TO_CONNECT
        expected_msg = self.test_data.sheepdog_cmd_error(cmd=cmd,
                                                         exit_code=exit_code,
                                                         stdout=stdout,
                                                         stderr=stderr)
        fake_execute.side_effect = exception.SheepdogCmdError(
            cmd=cmd, exit_code=exit_code, stdout=stdout.replace('\n', '\\n'),
            stderr=stderr.replace('\n', '\\n'))
        ex = self.assertRaises(exception.SheepdogCmdError,
                               self.client.resize, self._vdiname, 10)
        self.assertTrue(fake_logger.error.called)
        self.assertEqual(expected_msg, ex.msg)

        # Test3: os_error because dog command is not found
        fake_logger.reset_mock()
        fake_execute.reset_mock()
        cmd = self.test_data.cmd_dog_vdi_resize(self._vdiname, 10 * 1024 ** 3)
        exit_code = 1
        stderr = self.test_data.DOG_COMMAND_ERROR_VDI_NOT_EXISTS
        expected_msg = self.test_data.sheepdog_cmd_error(cmd=cmd,
                                                         exit_code=exit_code,
                                                         stdout=stdout,
                                                         stderr=stderr)
        fake_execute.side_effect = exception.SheepdogCmdError(
            cmd=cmd, exit_code=exit_code, stdout=stdout.replace('\n', '\\n'),
            stderr=stderr.replace('\n', '\\n'))
        ex = self.assertRaises(exception.SheepdogCmdError,
                               self.client.resize, self._vdiname, 1)
        self.assertTrue(fake_logger.error.called)
        self.assertEqual(expected_msg, ex.msg)

        # Test4: shrinking vdi is not supported
        fake_logger.reset_mock()
        fake_execute.reset_mock()
        cmd = self.test_data.cmd_dog_vdi_resize(self._vdiname, 1 * 1024 ** 3)
        stderr = self.test_data.DOG_VDI_RESIZE_SIZE_SHRINK
        expected_msg = self.test_data.sheepdog_cmd_error(cmd=cmd,
                                                         exit_code=exit_code,
                                                         stdout=stdout,
                                                         stderr=stderr)
        fake_execute.side_effect = exception.SheepdogCmdError(
            cmd=cmd, exit_code=exit_code, stdout=stdout.replace('\n', '\\n'),
            stderr=stderr.replace('\n', '\\n'))
        ex = self.assertRaises(exception.SheepdogCmdError,
                               self.client.resize, self._vdiname, 1)
        self.assertTrue(fake_logger.error.called)
        self.assertEqual(expected_msg, ex.msg)

        # Test5: the size is too large
        fake_logger.reset_mock()
        fake_execute.reset_mock()
        cmd = self.test_data.cmd_dog_vdi_resize(self._vdiname, 5 * 1024 ** 4)
        exit_code = 64
        stderr = self.test_data.DOG_VDI_RESIZE_TOO_LARGE
        expected_msg = self.test_data.sheepdog_cmd_error(cmd=cmd,
                                                         exit_code=exit_code,
                                                         stdout=stdout,
                                                         stderr=stderr)
        fake_execute.side_effect = exception.SheepdogCmdError(
            cmd=cmd, exit_code=exit_code, stdout=stdout.replace('\n', '\\n'),
            stderr=stderr.replace('\n', '\\n'))
        ex = self.assertRaises(exception.SheepdogCmdError,
                               self.client.resize, self._vdiname, 5120)
        self.assertTrue(fake_logger.error.called)
        self.assertEqual(expected_msg, ex.msg)

        # Test6: unknown error
        fake_logger.reset_mock()
        fake_execute.reset_mock()
        cmd = self.test_data.cmd_dog_vdi_resize(self._vdiname, 10 * 1024 ** 3)
        exit_code = 2
        stderr = 'stderr_dummy'
        expected_msg = self.test_data.sheepdog_cmd_error(cmd=cmd,
                                                         exit_code=exit_code,
                                                         stdout=stdout,
                                                         stderr=stderr)
        fake_execute.side_effect = exception.SheepdogCmdError(
            cmd=cmd, exit_code=exit_code, stdout=stdout.replace('\n', '\\n'),
            stderr=stderr.replace('\n', '\\n'))
        ex = self.assertRaises(exception.SheepdogCmdError,
                               self.client.resize, self._vdiname, 10)
        self.assertTrue(fake_logger.error.called)
        self.assertEqual(expected_msg, ex.msg)

    @mock.patch.object(sheepdog.SheepdogClient, '_run_qemu_img')
    def test_export_image(self, fake_execute):
        expected_path = 'dummy_path'
        expected_cmd = ('convert', '-f', 'raw', '-t', 'none', '-O', 'raw',
                        'sheepdog:%s' % self._vdiname, expected_path)
        fake_execute.return_value = ('', '')
        self.client.export_image(self._vdiname, expected_path)
        fake_execute.assert_called_once_with(*expected_cmd)

    @mock.patch.object(sheepdog.SheepdogClient, '_run_qemu_img')
    @mock.patch.object(sheepdog, 'LOG')
    def test_export_image_failed_to_connect(self, fake_logger, fake_execute):
        expected_path = 'dummy_path'
        cmd = ('convert', '-f', 'raw', '-t', 'none', '-O', 'raw',
               'sheepdog:%s' % self._vdiname, expected_path)
        exit_code = 1
        stdout = 'stdout_dummy'
        stderr = self.test_data.QEMU_IMG_FAILED_TO_CONNECT
        expected_msg = self.test_data.sheepdog_cmd_error(cmd=cmd,
                                                         exit_code=exit_code,
                                                         stdout=stdout,
                                                         stderr=stderr)
        fake_execute.side_effect = exception.SheepdogCmdError(
            cmd=cmd, exit_code=exit_code,
            stdout=stdout.replace('\n', '\\n'),
            stderr=stderr.replace('\n', '\\n'))
        ex = self.assertRaises(exception.SheepdogCmdError,
                               self.client.export_image, self._vdiname,
                               expected_path)
        self.assertTrue(fake_logger.error.called)
        self.assertEqual(expected_msg, ex.msg)

    @mock.patch.object(sheepdog.SheepdogClient, '_run_qemu_img')
    @mock.patch.object(sheepdog, 'LOG')
    def test_export_image_vdi_not_found(self, fake_logger, fake_execute):
        expected_path = 'dummy_path'
        cmd = ('convert', '-f', 'raw', '-t', 'none', '-O', 'raw',
               'sheepdog:%s' % self._vdiname, expected_path)
        exit_code = 1
        stdout = 'stdout_dummy'
        stderr = self.test_data.QEMU_IMG_VDI_NOT_FOUND
        expected_msg = self.test_data.sheepdog_cmd_error(cmd=cmd,
                                                         exit_code=exit_code,
                                                         stdout=stdout,
                                                         stderr=stderr)
        fake_execute.side_effect = exception.SheepdogCmdError(
            cmd=cmd, exit_code=exit_code,
            stdout=stdout.replace('\n', '\\n'),
            stderr=stderr.replace('\n', '\\n'))
        ex = self.assertRaises(exception.SheepdogCmdError,
                               self.client.export_image, self._vdiname,
                               expected_path)
        self.assertTrue(fake_logger.error.called)
        self.assertEqual(expected_msg, ex.msg)

    @mock.patch.object(sheepdog.SheepdogClient, '_run_qemu_img')
    @mock.patch.object(sheepdog, 'LOG')
    def test_export_image_permission_denied(self, fake_logger, fake_execute):
        expected_path = 'dummy_path'
        cmd = ('convert', '-f', 'raw', '-t', 'none', '-O', 'raw',
               'sheepdog:%s' % self._vdiname, expected_path)
        exit_code = 1
        stdout = 'stdout_dummy'
        stderr = self.test_data.QEMU_IMG_PERMISSION_DENIED
        expected_msg = self.test_data.sheepdog_cmd_error(cmd=cmd,
                                                         exit_code=exit_code,
                                                         stdout=stdout,
                                                         stderr=stderr)
        fake_execute.side_effect = exception.SheepdogCmdError(
            cmd=cmd, exit_code=exit_code,
            stdout=stdout.replace('\n', '\\n'),
            stderr=stderr.replace('\n', '\\n'))
        ex = self.assertRaises(exception.SheepdogCmdError,
                               self.client.export_image, self._vdiname,
                               expected_path)
        self.assertTrue(fake_logger.error.called)
        self.assertEqual(expected_msg, ex.msg)

    @mock.patch.object(sheepdog.SheepdogClient, '_run_qemu_img')
    @mock.patch.object(sheepdog, 'LOG')
    def test_export_image_invalid_format(self, fake_logger, fake_execute):
        expected_path = 'dummy_path'
        cmd = ('convert', '-f', 'raw', '-t', 'none', '-O', 'dummy',
               'sheepdog:%s' % self._vdiname, expected_path)
        exit_code = 1
        stdout = 'stdout_dummy'
        stderr = self.test_data.QEMU_IMG_ERROR_INVALID_FORMAT
        expected_msg = self.test_data.sheepdog_cmd_error(cmd=cmd,
                                                         exit_code=exit_code,
                                                         stdout=stdout,
                                                         stderr=stderr)
        fake_execute.side_effect = exception.SheepdogCmdError(
            cmd=cmd, exit_code=exit_code,
            stdout=stdout.replace('\n', '\\n'),
            stderr=stderr.replace('\n', '\\n'))
        ex = self.assertRaises(exception.SheepdogCmdError,
                               self.client.export_image, self._vdiname,
                               expected_path)
        self.assertTrue(fake_logger.error.called)
        self.assertEqual(expected_msg, ex.msg)

    @mock.patch.object(sheepdog.SheepdogClient, '_run_qemu_img')
    @mock.patch.object(sheepdog, 'LOG')
    def test_export_image_failed(self, fake_logger, fake_execute):
        expected_path = 'dummy_path'
        cmd = ('convert', '-f', 'raw', '-t', 'none', '-O', 'raw',
               'sheepdog:%s' % self._vdiname, expected_path)
        exit_code = 1
        stdout = 'stdout_dummy'
        stderr = 'stderr_dummy'
        expected_msg = self.test_data.sheepdog_cmd_error(cmd=cmd,
                                                         exit_code=exit_code,
                                                         stdout=stdout,
                                                         stderr=stderr)
        fake_execute.side_effect = exception.SheepdogCmdError(
            cmd=cmd, exit_code=exit_code,
            stdout=stdout.replace('\n', '\\n'),
            stderr=stderr.replace('\n', '\\n'))
        ex = self.assertRaises(exception.SheepdogCmdError,
                               self.client.export_image, self._vdiname,
                               expected_path)
        self.assertTrue(fake_logger.error.called)
        self.assertEqual(expected_msg, ex.msg)

    @mock.patch.object(sheepdog.SheepdogClient, '_run_qemu_img')
    def test_import_image(self, fake_execute):
        expected_path = 'dummy_path'
        expected_cmd = ('convert', '-f', 'raw', '-t', 'none', '-O', 'raw',
                        expected_path, 'sheepdog:%s' % self._vdiname)
        fake_execute.return_value = ('', '')
        self.client.import_image(self._vdiname, expected_path)
        fake_execute.assert_called_once_with(*expected_cmd)

    @mock.patch.object(sheepdog.SheepdogClient, '_run_qemu_img')
    @mock.patch.object(sheepdog, 'LOG')
    def test_import_image_failed_to_connect(self, fake_logger, fake_execute):
        expected_path = 'dummy_path'
        cmd = ('convert', '-f', 'raw', '-t', 'none', '-O', 'raw',
               expected_path, 'sheepdog:%s' % self._vdiname)
        exit_code = 1
        stdout = 'stdout_dummy'
        stderr = self.test_data.QEMU_IMG_FAILED_TO_CONNECT
        expected_msg = self.test_data.sheepdog_cmd_error(cmd=cmd,
                                                         exit_code=exit_code,
                                                         stdout=stdout,
                                                         stderr=stderr)
        fake_execute.side_effect = exception.SheepdogCmdError(
            cmd=cmd, exit_code=exit_code,
            stdout=stdout.replace('\n', '\\n'),
            stderr=stderr.replace('\n', '\\n'))
        ex = self.assertRaises(exception.SheepdogCmdError,
                               self.client.import_image, self._vdiname,
                               expected_path)
        self.assertTrue(fake_logger.error.called)
        self.assertEqual(expected_msg, ex.msg)

    @mock.patch.object(sheepdog.SheepdogClient, '_run_qemu_img')
    @mock.patch.object(sheepdog, 'LOG')
    def test_import_image_file_not_found(self, fake_logger, fake_execute):
        expected_path = 'dummy_path'
        cmd = ('convert', '-f', 'raw', '-t', 'none', '-O', 'raw',
               expected_path, 'sheepdog:%s' % self._vdiname)
        exit_code = 1
        stdout = 'stdout_dummy'
        stderr = self.test_data.QEMU_IMG_FILE_NOT_FOUND
        expected_msg = self.test_data.sheepdog_cmd_error(cmd=cmd,
                                                         exit_code=exit_code,
                                                         stdout=stdout,
                                                         stderr=stderr)
        fake_execute.side_effect = exception.SheepdogCmdError(
            cmd=cmd, exit_code=exit_code,
            stdout=stdout.replace('\n', '\\n'),
            stderr=stderr.replace('\n', '\\n'))
        ex = self.assertRaises(exception.SheepdogCmdError,
                               self.client.import_image, self._vdiname,
                               expected_path)
        self.assertTrue(fake_logger.error.called)
        self.assertEqual(expected_msg, ex.msg)

    @mock.patch.object(sheepdog.SheepdogClient, '_run_qemu_img')
    @mock.patch.object(sheepdog, 'LOG')
    def test_import_image_permission_denied(self, fake_logger, fake_execute):
        expected_path = 'dummy_path'
        cmd = ('convert', '-f', 'raw', '-t', 'none', '-O', 'raw',
               expected_path, 'sheepdog:%s' % self._vdiname)
        exit_code = 1
        stdout = 'stdout_dummy'
        stderr = self.test_data.QEMU_IMG_PERMISSION_DENIED
        expected_msg = self.test_data.sheepdog_cmd_error(cmd=cmd,
                                                         exit_code=exit_code,
                                                         stdout=stdout,
                                                         stderr=stderr)
        fake_execute.side_effect = exception.SheepdogCmdError(
            cmd=cmd, exit_code=exit_code,
            stdout=stdout.replace('\n', '\\n'),
            stderr=stderr.replace('\n', '\\n'))
        ex = self.assertRaises(exception.SheepdogCmdError,
                               self.client.import_image, self._vdiname,
                               expected_path)
        self.assertTrue(fake_logger.error.called)
        self.assertEqual(expected_msg, ex.msg)

    @mock.patch.object(sheepdog.SheepdogClient, '_run_qemu_img')
    @mock.patch.object(sheepdog, 'LOG')
    def test_import_image_invalid_format(self, fake_logger, fake_execute):
        expected_path = 'dummy_path'
        cmd = ('convert', '-f', 'dummy', '-t', 'none', '-O', 'raw',
               expected_path, 'sheepdog:%s' % self._vdiname)
        exit_code = 1
        stdout = 'stdout_dummy'
        stderr = self.test_data.QEMU_IMG_INVALID_DRIVER
        expected_msg = self.test_data.sheepdog_cmd_error(cmd=cmd,
                                                         exit_code=exit_code,
                                                         stdout=stdout,
                                                         stderr=stderr)
        fake_execute.side_effect = exception.SheepdogCmdError(
            cmd=cmd, exit_code=exit_code,
            stdout=stdout.replace('\n', '\\n'),
            stderr=stderr.replace('\n', '\\n'))
        ex = self.assertRaises(exception.SheepdogCmdError,
                               self.client.import_image, self._vdiname,
                               expected_path)
        self.assertTrue(fake_logger.error.called)
        self.assertEqual(expected_msg, ex.msg)

    @mock.patch.object(sheepdog.SheepdogClient, '_run_qemu_img')
    @mock.patch.object(sheepdog, 'LOG')
    def test_import_image_already_exist(self, fake_logger, fake_execute):
        expected_path = 'dummy_path'
        cmd = ('convert', '-f', 'dummy', '-t', 'none', '-O', 'raw',
               expected_path, 'sheepdog:%s' % self._vdiname)
        exit_code = 1
        stdout = 'stdout_dummy'
        stderr = self.test_data.QEMU_IMG_VDI_ALREADY_EXISTS
        expected_msg = self.test_data.sheepdog_cmd_error(cmd=cmd,
                                                         exit_code=exit_code,
                                                         stdout=stdout,
                                                         stderr=stderr)
        fake_execute.side_effect = exception.SheepdogCmdError(
            cmd=cmd, exit_code=exit_code,
            stdout=stdout.replace('\n', '\\n'),
            stderr=stderr.replace('\n', '\\n'))
        ex = self.assertRaises(exception.SheepdogCmdError,
                               self.client.import_image, self._vdiname,
                               expected_path)
        self.assertTrue(fake_logger.error.called)
        self.assertEqual(expected_msg, ex.msg)

    @mock.patch.object(sheepdog.SheepdogClient, '_run_qemu_img')
    @mock.patch.object(sheepdog, 'LOG')
    def test_import_image_failed_else(self, fake_logger, fake_execute):
        expected_path = 'dummy_path'
        cmd = ('convert', '-f', 'dummy', '-t', 'none', '-O', 'raw',
               expected_path, 'sheepdog:%s' % self._vdiname)
        exit_code = 1
        stdout = 'stdout_dummy'
        stderr = 'stderr_dummy'
        expected_msg = self.test_data.sheepdog_cmd_error(cmd=cmd,
                                                         exit_code=exit_code,
                                                         stdout=stdout,
                                                         stderr=stderr)
        fake_execute.side_effect = exception.SheepdogCmdError(
            cmd=cmd, exit_code=exit_code,
            stdout=stdout.replace('\n', '\\n'),
            stderr=stderr.replace('\n', '\\n'))
        ex = self.assertRaises(exception.SheepdogCmdError,
                               self.client.import_image, self._vdiname,
                               expected_path)
        self.assertTrue(fake_logger.error.called)
        self.assertEqual(expected_msg, ex.msg)

    @mock.patch.object(sheepdog.SheepdogClient, '_parse_location')
    @mock.patch.object(sheepdog.SheepdogClient, '_run_dog')
    @mock.patch.object(sheepdog, 'LOG')
    def test_is_cloneable(self, fake_logger, fake_execute, fake_parse_loc):
        uuid = 'a720b3c0-d1f0-11e1-9b23-0800200c9a66'
        location = 'sheepdog://%s' % uuid
        image_meta = {'id': uuid, 'size': 1, 'disk_format': 'raw'}
        invalid_image_meta = {'id': uuid, 'size': 1, 'disk_format': 'iso'}
        stdout = self.test_data.IS_CLONEABLE_TRUE
        stderr = ''
        expected_cmd = ('vdi', 'list', '-r', uuid)

        fake_execute.return_value = (stdout, stderr)
        fake_parse_loc.return_value = uuid
        self.assertTrue(
            self.client._is_cloneable(location, image_meta))
        fake_execute.assert_called_once_with(*expected_cmd)

        self.assertFalse(
            self.client._is_cloneable(location, invalid_image_meta))
        self.assertEqual(1, fake_execute.call_count)
        self.assertTrue(fake_logger.debug.called)

        error = exception.ImageUnacceptable(image_id = 'invalid_image',
                                            reason = _('invalid'))
        fake_parse_loc.side_effect = error
        # check returning False without executing a command
        self.assertFalse(
            self.client._is_cloneable(location, image_meta))
        self.assertTrue(fake_logger.debug.called)

    @mock.patch.object(sheepdog.SheepdogClient, '_parse_location')
    @mock.patch.object(sheepdog.SheepdogClient, '_run_dog')
    @mock.patch.object(sheepdog, 'LOG')
    def test_is_cloneable_volume_not_found(self, fake_logger,
                                           fake_execute, fake_parse_loc):
        uuid = 'a720b3c0-d1f0-11e1-9b23-0800200c9a66'
        location = 'sheepdog://%s' % uuid
        image_meta = {'id': uuid, 'size': 1, 'disk_format': 'raw'}
        stdout = ''
        stderr = ''
        expected_cmd = ('vdi', 'list', '-r', uuid)

        fake_execute.return_value = (stdout, stderr)
        fake_parse_loc.return_value = uuid
        self.assertFalse(
            self.client._is_cloneable(location, image_meta))
        fake_execute.assert_called_once_with(*expected_cmd)
        self.assertTrue(fake_logger.debug.called)

    @mock.patch.object(sheepdog.SheepdogClient, '_parse_location')
    @mock.patch.object(sheepdog.SheepdogClient, '_run_dog')
    @mock.patch.object(sheepdog, 'LOG')
    def test_is_cloneable_volume_is_not_valid(self, fake_logger,
                                              fake_execute, fake_parse_loc):
        uuid = 'a720b3c0-d1f0-11e1-9b23-0800200c9a66'
        location = 'sheepdog://%s' % uuid
        image_meta = {'id': uuid, 'size': 1, 'disk_format': 'raw'}
        stdout = self.test_data.IS_CLONEABLE_FALSE
        stderr = ''
        expected_cmd = ('vdi', 'list', '-r', uuid)

        fake_execute.return_value = (stdout, stderr)
        fake_parse_loc.return_value = uuid
        self.assertFalse(
            self.client._is_cloneable(location, image_meta))
        fake_execute.assert_called_once_with(*expected_cmd)
        self.assertTrue(fake_logger.debug.called)

    def test_parse_location(self):
        uuid = '87f1b01c-f46c-4537-bd5d-23962f5f4316'
        location = 'sheepdog://%s' % uuid
        loc_none = None
        loc_not_found = 'fail'
        loc_format_err = 'sheepdog://'
        loc_format_err2 = 'sheepdog://f/f'

        exc = self.assertRaises(exception.ImageUnacceptable,
                                self.client._parse_location, loc_none)
        self.assertEqual('Image None is unacceptable: image_location is NULL',
                         exc.msg)

        exc = self.assertRaises(exception.ImageUnacceptable,
                                self.client._parse_location, loc_not_found)
        self.assertEqual('Image fail is unacceptable: Not stored in sheepdog',
                         exc.msg)

        exc = self.assertRaises(exception.ImageUnacceptable,
                                self.client._parse_location, loc_format_err)
        self.assertEqual('Image sheepdog:// is unacceptable: Blank components',
                         exc.msg)

        exc = self.assertRaises(exception.ImageUnacceptable,
                                self.client._parse_location, loc_format_err2)
        self.assertEqual('Image sheepdog://f/f is unacceptable:'
                         ' Not a sheepdog image', exc.msg)

        name = self.client._parse_location(location)
        self.assertEqual(uuid, name)


# test for SheeepdogDriver Class
class SheepdogDriverTestCase(test.TestCase):
    def setUp(self):
        super(SheepdogDriverTestCase, self).setUp()
        self._cfg = conf.Configuration(None)
        self._cfg.sheepdog_store_address = SHEEP_ADDR
        self._cfg.sheepdog_store_port = SHEEP_PORT
        self.driver = sheepdog.SheepdogDriver(configuration=self._cfg)
        db_driver = self.driver.configuration.db_driver
        self.db = importutils.import_module(db_driver)
        self.driver.db = self.db
        self.driver.do_setup(None)
        self.test_data = SheepdogDriverTestDataGenerator()
        self.client = self.driver.client
        self._vdiname = self.test_data.TEST_VOLUME['name']
        self._vdisize = self.test_data.TEST_VOLUME['size']
        self._src_vdiname = self.test_data.TEST_SNAPSHOT['volume_name']
        self._snapname = self.test_data.TEST_SNAPSHOT['name']

    @mock.patch.object(sheepdog.SheepdogClient, 'check_cluster_status')
    def test_check_for_setup_error(self, fake_execute):
        self.driver.check_for_setup_error()
        fake_execute.assert_called_once_with()

    @mock.patch.object(sheepdog.SheepdogClient, 'create')
    def test_create_volume(self, fake_execute):
        self.driver.create_volume(self.test_data.TEST_VOLUME)
        fake_execute.assert_called_once_with(self._vdiname, self._vdisize)

    @mock.patch.object(sheepdog.SheepdogClient, 'delete')
    def test_delete_volume(self, fake_execute):
        self.driver.delete_volume(self.test_data.TEST_VOLUME)
        fake_execute.assert_called_once_with(self._vdiname)

    def test_update_volume_stats(self):
        def fake_stats(*args):
            return self.test_data.COLLIE_NODE_INFO, ''
        self.stubs.Set(self.driver, '_execute', fake_stats)
        expected = dict(
            volume_backend_name='sheepdog',
            vendor_name='Open Source',
            dirver_version=self.driver.VERSION,
            storage_protocol='sheepdog',
            total_capacity_gb=float(107287605248) / units.Gi,
            free_capacity_gb=float(107287605248 - 3623897354) / units.Gi,
            reserved_percentage=0,
            QoS_support=False)
        actual = self.driver.get_volume_stats(True)
        self.assertDictMatch(expected, actual)

    def test_update_volume_stats_error(self):
        def fake_stats(*args):
            raise processutils.ProcessExecutionError()
        self.stubs.Set(self.driver, '_execute', fake_stats)
        expected = dict(
            volume_backend_name='sheepdog',
            vendor_name='Open Source',
            dirver_version=self.driver.VERSION,
            storage_protocol='sheepdog',
            total_capacity_gb='unknown',
            free_capacity_gb='unknown',
            reserved_percentage=0,
            QoS_support=False)
        actual = self.driver.get_volume_stats(True)
        self.assertDictMatch(expected, actual)

    @mock.patch.object(image_utils, 'temporary_file')
    @mock.patch.object(image_utils, 'fetch_verify_image')
    @mock.patch.object(sheepdog.SheepdogClient, 'delete')
    @mock.patch.object(sheepdog.SheepdogClient, 'resize')
    @mock.patch.object(sheepdog.SheepdogClient, 'import_image')
    def test_copy_image_to_volume(self, fake_import_image, fake_resize,
                                  fake_delete, fake_fetch_verify_image,
                                  fake_temp_file):
        fake_context = {}
        fake_volume = {'name': 'volume-00000001', 'size': 1}
        fake_image_service = mock.Mock()
        fake_image_meta = {'id': '10958016-e196-42e3-9e7f-5d8927ae3099'}

        # check execute correctly.
        self.driver.copy_image_to_volume(fake_context, fake_volume,
                                         fake_image_service,
                                         fake_image_meta['id'])
        fake_delete.assert_called_once_with(fake_volume['name'])
        fake_import_image.assert_called_once_with(fake_volume['name'],
                                                  mock.ANY)
        fake_resize.assert_called_once_with(fake_volume['name'],
                                            fake_volume['size'])

        # check resize failed.
        fake_delete.reset_mock()
        fake_resize.reset_mock()
        fake_import_image.reset_mock()

        fake_resize.side_effect = exception.SheepdogCmdError(
            cmd='dummy', exit_code=1, stdout='dummy', stderr='dummy')
        self.assertRaises(exception.SheepdogCmdError,
                          self.driver.copy_image_to_volume,
                          fake_context, fake_volume,
                          fake_image_service, fake_image_meta['id'])
        fake_delete.assert_called_with(fake_volume['name'])
        self.assertEqual(2, fake_delete.call_count)

    @mock.patch.object(fileutils, 'file_open')
    @mock.patch.object(image_utils, 'temporary_file')
    @mock.patch.object(sheepdog.SheepdogClient, 'export_image')
    def test_copy_volume_to_image(self, fake_execute,
                                  fake_temporary_file, fake_file_open):
        fake_context = {}
        fake_volume = {'name': 'volume-00000001'}
        image_service = mock.Mock()
        fake_image_meta = {'id': '10958016-e196-42e3-9e7f-5d8927ae3099'}

        self.driver.copy_volume_to_image(fake_context,
                                         fake_volume,
                                         image_service,
                                         fake_image_meta)

        expected_cmd = (fake_volume['name'], mock.ANY)
        fake_execute.assert_called_once_with(*expected_cmd)

    @mock.patch.object(sheepdog.SheepdogClient, 'export_image')
    @mock.patch.object(sheepdog, 'LOG')
    def test_copy_volume_to_image_nonexistent_volume(self, fake_logger,
                                                     fake_execute):
        fake_context = {}
        fake_volume = {
            'name': 'nonexistent-volume-82c4539e-c2a5-11e4-a293-0aa186c60fe0'}
        fake_image_service = mock.Mock()
        fake_image_meta = {'id': '10958016-e196-42e3-9e7f-5d8927ae3099'}
        cmd = (fake_volume['name'], mock.ANY)

        fake_execute.side_effect = exception.SheepdogCmdError(
            cmd=cmd, exit_code=1, stdout='dummy', stderr='dummy')

        self.assertRaises(exception.SheepdogCmdError,
                          self.driver.copy_volume_to_image,
                          fake_context, fake_volume,
                          fake_image_service, fake_image_meta)
        self.assertTrue(fake_logger.error.called)

    @mock.patch.object(fileutils, 'file_open')
    @mock.patch.object(sheepdog.SheepdogClient, 'export_image')
    @mock.patch.object(sheepdog, 'LOG')
    def test_copy_volume_to_image_update_failed(self, fake_logger,
                                                fake_execute, fake_file_open):
        fake_context = {}
        fake_volume = {'name': 'volume-00000001'}
        image_service = mock.Mock()
        fake_image_meta = {'id': '10958016-e196-42e3-9e7f-5d8927ae3099'}

        image_service.update.side_effect = exception.SheepdogCmdError(
            cmd=mock.ANY, exit_code=1, stdout='dummy', stderr='dummy')

        self.assertRaises(exception.SheepdogCmdError,
                          self.driver.copy_volume_to_image,
                          fake_context, fake_volume,
                          image_service, fake_image_meta)
        self.assertTrue(fake_logger.error.called)

    @mock.patch.object(sheepdog.SheepdogClient, 'create_snapshot')
    @mock.patch.object(sheepdog.SheepdogClient, 'clone')
    @mock.patch.object(sheepdog.SheepdogClient, 'delete_snapshot')
    def test_create_cloned_volume(self, fake_delete_snapshot,
                                  fake_clone, fake_create_snapshot):
        src_vol = self.test_data.TEST_VOLUME
        cloned_vol = self.test_data.TEST_CLONED_VOLUME

        self.driver.create_cloned_volume(cloned_vol, src_vol)
        snapshot_name = src_vol['name'] + '-temp-snapshot'
        fake_create_snapshot.assert_called_once_with(src_vol['name'],
                                                     snapshot_name)
        fake_clone.assert_called_once_with(src_vol['name'],
                                           snapshot_name,
                                           cloned_vol['name'],
                                           cloned_vol['size'])
        fake_delete_snapshot.assert_called_once_with(src_vol['name'],
                                                     snapshot_name)

    @mock.patch.object(sheepdog.SheepdogClient, 'create_snapshot')
    @mock.patch.object(sheepdog.SheepdogClient, 'clone')
    @mock.patch.object(sheepdog.SheepdogClient, 'delete_snapshot')
    @mock.patch.object(sheepdog, 'LOG')
    def test_create_cloned_volume_failure(self, fake_logger,
                                          fake_delete_snapshot,
                                          fake_clone, fake_create_snapshot):
        src_vol = self.test_data.TEST_VOLUME
        cloned_vol = self.test_data.TEST_CLONED_VOLUME
        snapshot_name = src_vol['name'] + '-temp-snapshot'

        fake_clone.side_effect = exception.SheepdogCmdError(
            cmd='dummy', exit_code=1, stdout='dummy', stderr='dummy')
        self.assertRaises(exception.SheepdogCmdError,
                          self.driver.create_cloned_volume,
                          cloned_vol, src_vol)
        fake_delete_snapshot.assert_called_once_with(src_vol['name'],
                                                     snapshot_name)
        self.assertTrue(fake_logger.error.called)

    @mock.patch.object(sheepdog.SheepdogClient, 'create_snapshot')
    def test_create_snapshot(self, fake_create_snapshot):
        snapshot = self.test_data.TEST_SNAPSHOT
        self.driver.create_snapshot(snapshot)
        fake_create_snapshot.assert_called_once_with(snapshot['volume_name'],
                                                     snapshot['name'])

    @mock.patch.object(sheepdog.SheepdogClient, 'delete_snapshot')
    def test_delete_snapshot(self, fake_delete_snapshot):
        snapshot = self.test_data.TEST_SNAPSHOT
        self.driver.delete_snapshot(snapshot)
        fake_delete_snapshot.assert_called_once_with(snapshot['volume_name'],
                                                     snapshot['name'])

    @mock.patch.object(sheepdog.SheepdogClient, '_run_dog')
    @mock.patch.object(sheepdog.SheepdogClient, 'resize')
    @mock.patch.object(sheepdog.SheepdogDriver, 'create_cloned_volume')
    def test_clone_image_success(self, fake_create_cloned_volume, fake_resize,
                                 fake_execute):
        context = {}
        fake_name = self.test_data.TEST_VOLUME['name']
        fake_vol = {'project_id': self.test_data.TEST_VOLUME['project_id'],
                    'name': self.test_data.TEST_VOLUME['name'],
                    'size': self.test_data.TEST_VOLUME['size'],
                    'id': self.test_data.TEST_VOLUME['id']}
        stdout = self.test_data.IS_CLONEABLE_TRUE
        stderr = ''

        fake_location = 'sheepdog://%s' % self.test_data.TEST_VOLUME['id']
        image_location = (fake_location, None)
        image_meta = {'id': self.test_data.TEST_VOLUME['id'],
                      'size': self.test_data.TEST_VOLUME['size'],
                      'disk_format': 'raw'}
        image_service = ''

        fake_execute.return_value = (stdout, stderr)
        model_updated, cloned = self.driver.clone_image(
            context, fake_vol, image_location, image_meta, image_service)

        self.assertTrue(cloned)
        self.assertEqual("sheepdog://%s" % fake_name,
                         model_updated['provider_location'])

    @mock.patch.object(sheepdog.SheepdogClient, '_is_cloneable')
    def test_clone_image_failure(self, fake_is_cloneable):
        context = {}
        fake_vol = {}
        image_location = ('image_location', None)
        image_meta = {}
        image_service = ''

        fake_is_cloneable.side_effect = lambda *args: False
        result = self.driver.clone_image(
            context, fake_vol, image_location, image_meta, image_service)
        self.assertEqual(({}, False), result)

    @mock.patch.object(sheepdog.SheepdogClient, '_run_dog')
    @mock.patch.object(sheepdog.SheepdogDriver, 'create_cloned_volume')
    @mock.patch.object(sheepdog, 'LOG')
    def test_clone_image_create_volume_fail(self, fake_logger,
                                            fake_create_volume, fake_execute):
        context = {}
        fake_vol = {'project_id': self.test_data.TEST_VOLUME['project_id'],
                    'name': self.test_data.TEST_VOLUME['name'],
                    'size': self.test_data.TEST_VOLUME['size'],
                    'id': self.test_data.TEST_VOLUME['id']}
        fake_location = 'sheepdog://%s' % self.test_data.TEST_VOLUME['id']
        image_location = (fake_location, None)
        image_meta = {'id': self.test_data.TEST_VOLUME['id'],
                      'size': self.test_data.TEST_VOLUME['size'],
                      'disk_format': 'raw'}
        image_service = ''
        stdout = self.test_data.IS_CLONEABLE_TRUE
        stderr = ''

        error = exception.VolumeBackendAPIException(data='error')
        fake_create_volume.side_effect = error
        fake_execute.return_value = (stdout, stderr)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.clone_image,
                          context, fake_vol, image_location,
                          image_meta, image_service)
        self.assertEqual(1, fake_create_volume.call_count)
        self.assertTrue(fake_logger.error.called)

    @mock.patch.object(sheepdog.SheepdogClient, '_run_dog')
    @mock.patch.object(sheepdog.SheepdogClient, 'resize')
    @mock.patch.object(sheepdog.SheepdogDriver, 'create_cloned_volume')
    @mock.patch.object(sheepdog, 'LOG')
    def test_clone_image_resize_fail(self, fake_logger,
                                     fake_create_cloned_volume, fake_resize,
                                     fake_execute):
        context = {}
        fake_vol = {'project_id': self.test_data.TEST_VOLUME['project_id'],
                    'name': self.test_data.TEST_VOLUME['name'],
                    'size': self.test_data.TEST_VOLUME['size'],
                    'id': self.test_data.TEST_VOLUME['id']}
        fake_location = 'sheepdog://%s' % self.test_data.TEST_VOLUME['id']
        image_location = (fake_location, None)
        image_meta = {'id': self.test_data.TEST_VOLUME['id'],
                      'size': self.test_data.TEST_VOLUME['size'],
                      'disk_format': 'raw'}
        image_service = ''
        stdout = self.test_data.IS_CLONEABLE_TRUE
        stderr = ''

        error = exception.VolumeBackendAPIException(data='error')
        fake_resize.side_effect = error
        fake_execute.return_value = (stdout, stderr)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.clone_image,
                          context, fake_vol, image_location,
                          image_meta, image_service)
        self.assertEqual(1, fake_resize.call_count)
        self.assertTrue(fake_logger.error.called)

    @mock.patch.object(sheepdog.SheepdogClient, '_run_dog')
    @mock.patch.object(sheepdog.SheepdogClient, 'resize')
    @mock.patch.object(sheepdog.SheepdogClient, 'delete')
    @mock.patch.object(sheepdog.SheepdogDriver, 'create_cloned_volume')
    @mock.patch.object(sheepdog, 'LOG')
    def test_clone_image_delete_fail(self, fake_logger,
                                     fake_create_clone_volume,
                                     fake_delete, fake_resize,
                                     fake_execute):
        context = {}
        fake_vol = {'project_id': self.test_data.TEST_VOLUME['project_id'],
                    'name': self.test_data.TEST_VOLUME['name'],
                    'size': self.test_data.TEST_VOLUME['size'],
                    'id': self.test_data.TEST_VOLUME['id']}
        fake_location = 'sheepdog://%s' % self.test_data.TEST_VOLUME['id']
        image_location = (fake_location, None)
        image_meta = {'id': self.test_data.TEST_VOLUME['id'],
                      'size': self.test_data.TEST_VOLUME['size'],
                      'disk_format': 'raw'}
        image_service = ''
        stdout_d = self.test_data.IS_CLONEABLE_TRUE
        stderr_d = 'dummy'
        cmd = self.test_data.cmd_dog_vdi_delete(fake_vol['name'])
        exit_code = 2

        error1 = exception.VolumeBackendAPIException(data='error')
        error2 = exception.SheepdogCmdError(cmd=cmd, exit_code=exit_code,
                                            stdout=stdout_d, stderr=stderr_d)
        fake_resize.side_effect = error1
        fake_delete.side_effect = error2
        fake_execute.return_value = (stdout_d, stderr_d)
        self.assertRaises(
            exception.SheepdogCmdError, self.driver.clone_image,
            context, fake_vol, image_location, image_meta, image_service)
        self.assertEqual(1, fake_delete.call_count)
        self.assertTrue(fake_logger.error.called)

    def test_create_volume_from_snapshot(self):
        volume = self.test_data.TEST_VOLUME
        snapshot = self.test_data.TEST_SNAPSHOT
        with mock.patch.object(self.client, 'clone') as fake_execute:
            self.driver.create_volume_from_snapshot(volume, snapshot)
            fake_execute.assert_called_once_with(self._src_vdiname,
                                                 self._snapname,
                                                 self._vdiname,
                                                 self._vdisize)

    def test_local_path(self):
        fake_vol = {'project_id': self.test_data.TEST_VOLUME['project_id'],
                    'name': self.test_data.TEST_VOLUME['name'],
                    'size': self.test_data.TEST_VOLUME['size'],
                    'id': self.test_data.TEST_VOLUME['id']}
        expected_path = 'sheepdog://%s' % fake_vol['name']

        ret = self.driver.local_path(fake_vol)
        self.assertEqual(ret, expected_path)

    @mock.patch.object(sheepdog, 'LOG')
    def test_local_path_failed(self, fake_logger):
        fake_vol = {'project_id': self.test_data.TEST_VOLUME['project_id'],
                    'name': '',
                    'size': self.test_data.TEST_VOLUME['size'],
                    'id': self.test_data.TEST_VOLUME['id']}

        self.assertRaises(exception.SheepdogError,
                          self.driver.local_path, fake_vol)
        self.assertTrue(fake_logger.error.called)

    @mock.patch.object(sheepdog.SheepdogClient, 'resize')
    @mock.patch.object(sheepdog, 'LOG')
    def test_extend_volume(self, fake_logger, fake_execute):
        self.driver.extend_volume(self.test_data.TEST_VOLUME, 10)
        fake_execute.assert_called_once_with(self._vdiname, 10)
        self.assertTrue(fake_logger.debug.called)

    def test_backup_volume(self):
        fake_context = {}
        fake_backup = {'volume_id': '2926efe0-24ab-45b7-95e1-ff66e0646a33'}
        fake_backup_service = mock.Mock()

        fake_db = mock.MagicMock()
        fake_try_execute = mock.Mock()
        fake_create_snapshot = mock.Mock()
        fake_delete_snapshot = mock.Mock()
        self.stubs.Set(self.driver, 'db', fake_db)
        self.stubs.Set(self.driver, '_try_execute', fake_try_execute)
        self.stubs.Set(self.driver, 'create_snapshot', fake_create_snapshot)
        self.stubs.Set(self.driver, 'delete_snapshot', fake_delete_snapshot)

        self.driver.backup_volume(fake_context,
                                  fake_backup,
                                  fake_backup_service)

        # check that temporary snapshot was created and deleted.
        self.assertEqual(1, fake_create_snapshot.call_count)
        self.assertEqual(1, fake_delete_snapshot.call_count)
        self.assertEqual(fake_create_snapshot.call_args,
                         fake_delete_snapshot.call_args)

        # check that backup_service was called.
        call_args, call_kwargs = fake_backup_service.backup.call_args
        call_backup, call_sheepdog_fd = call_args
        self.assertEqual(fake_backup, call_backup)
        self.assertIsInstance(call_sheepdog_fd, sheepdog.SheepdogIOWrapper)

    def test_backup_volume_failure(self):
        fake_context = {}
        fake_backup = {'volume_id': '2926efe0-24ab-45b7-95e1-ff66e0646a33'}
        fake_backup_service = mock.Mock()

        fake_db = mock.MagicMock()
        fake_try_execute = mock.Mock()
        fake_create_snapshot = mock.Mock()
        fake_delete_snapshot = mock.Mock()
        self.stubs.Set(self.driver, 'db', fake_db)
        self.stubs.Set(self.driver, '_try_execute', fake_try_execute)
        self.stubs.Set(self.driver, 'create_snapshot', fake_create_snapshot)
        self.stubs.Set(self.driver, 'delete_snapshot', fake_delete_snapshot)

        # check that the snapshot gets deleted in case of a backup error.
        class BackupError(Exception):
            pass
        backup_failure = mock.Mock(side_effect=BackupError)
        self.stubs.Set(fake_backup_service, 'backup', backup_failure)

        self.assertRaises(BackupError,
                          self.driver.backup_volume,
                          fake_context,
                          fake_backup,
                          fake_backup_service)

        self.assertEqual(1, fake_create_snapshot.call_count)
        self.assertEqual(1, fake_delete_snapshot.call_count)
        self.assertEqual(fake_create_snapshot.call_args,
                         fake_delete_snapshot.call_args)

    def test_restore_backup(self):
        fake_context = {}
        fake_backup = {}
        fake_volume = {'id': '2926efe0-24ab-45b7-95e1-ff66e0646a33',
                       'name': 'volume-2926efe0-24ab-45b7-95e1-ff66e0646a33'}
        fake_backup_service = mock.Mock()

        self.driver.restore_backup(
            fake_context, fake_backup, fake_volume, fake_backup_service)

        call_args, call_kwargs = fake_backup_service.restore.call_args
        call_backup, call_volume_id, call_sheepdog_fd = call_args
        self.assertEqual(fake_backup, call_backup)
        self.assertEqual(fake_volume['id'], call_volume_id)
        self.assertIsInstance(call_sheepdog_fd, sheepdog.SheepdogIOWrapper)
