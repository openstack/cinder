
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

import contextlib
import errno

import mock
from oslo_concurrency import processutils
from oslo_utils import importutils
from oslo_utils import units
import six

from cinder import exception
from cinder.i18n import _, _LW, _LE
from cinder.image import image_utils
from cinder import test
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

    CMD_DOG_CLUSTER_INFO = ('dog', 'cluster', 'info',
                            '-a', SHEEP_ADDR, '-p', str(SHEEP_PORT))

    def cmd_dog_vdi_create(self, name, size):
        return ('dog', 'vdi', 'create', name, '%sG' % size, '-a', SHEEP_ADDR,
                '-p', str(SHEEP_PORT))

    def cmd_dog_vdi_delete(self, name):
        return ('dog', 'vdi', 'delete', name,
                '-a', SHEEP_ADDR, '-p', str(SHEEP_PORT))

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
        'consistencygroup_id': None
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

    DOG_VDI_CREATE_VDI_EXISTS_ALREADY = """\
Failed to create VDI %(volname)s: VDI exists already
"""

    DOG_VDI_CREATE_FAILD_TO_WRITE_OBJECT = """\
Failed to create VDI %(volname)s: Failed to write to requested VDI
"""

    DOG_VDI_DELETE_VDI_NOT_EXISTS = """\
Failed to open VDI vdiname (snapshot id: 0 snapshot tag: ): No VDI found
"""

    DOG_COMMAND_ERROR_FAIL_TO_CONNECT = """\
failed to connect to 127.0.0.1:7000: Connection refused
failed to connect to 127.0.0.1:7000: Connection refused
Failed to get node list
"""


class FakeImageService(object):
    def download(self, context, image_id, path):
        pass


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

    # test for _run_dog method
    def test_run_dog(self):
        expected_cmd = self.test_data.CMD_DOG_CLUSTER_INFO
        with mock.patch.object(self.client, '_execute') as fake_execute:
                fake_execute.return_value = ('', '')
                self.client._run_dog('cluster', 'info')
        fake_execute.assert_called_once_with(*expected_cmd)

    def test_run_dog_os_error(self):
        args = ('cluster', 'info')
        expected_msg = 'No such file or directory'
        expected_errno = errno.ENOENT
        with mock.patch.object(self.client, '_execute') as fake_execute:
            with mock.patch.object(sheepdog, 'LOG') as fake_logger:
                fake_execute.side_effect = OSError(expected_errno,
                                                   expected_msg)
                self.assertRaises(OSError, self.client._run_dog, *args)
                self.assertTrue(fake_logger.error.called)

    # test for check_cluster_status method
    def test_check_cluster_status(self):
        stdout = self.test_data.DOG_CLUSTER_RUNNING
        stderr = ''
        expected_cmd = ('cluster', 'info')
        expected_log = _('Sheepdog cluster is running.')

        with mock.patch.object(self.client, '_run_dog') as fake_execute:
            with mock.patch.object(sheepdog, 'LOG') as fake_logger:
                fake_execute.return_value = (stdout, stderr)
                self.client.check_cluster_status()
            fake_execute.assert_called_once_with(*expected_cmd)
            fake_logger.debug.assert_called_with(expected_log)

    def test_check_cluster_status_0_5(self):
        def fake_stats(*args):
            return self.test_data.COLLIE_CLUSTER_INFO_0_5, ''
        self.stubs.Set(self.client, '_execute', fake_stats)
        self.client.check_cluster_status()

    def test_check_cluster_status_0_6(self):
        def fake_stats(*args):
            return self.test_data.COLLIE_CLUSTER_INFO_0_6, ''
        self.stubs.Set(self.client, '_execute', fake_stats)
        self.client.check_cluster_status()

    def test_check_cluster_status_error_waiting_formatted(self):
        stdout = self.test_data.DOG_CLUSTER_INFO_TO_BE_FORMATTED
        stderr = ''
        expected_reason = _LE('Cluster is not formatted. '
                              'You should probably perform '
                              '"dog cluster format".')

        with mock.patch.object(self.client, '_run_dog') as fake_execute:
            fake_execute.return_value = (stdout, stderr)
            ex = self.assertRaises(exception.SheepdogError,
                                   self.client.check_cluster_status)
            self.assertEqual(expected_reason, ex.kwargs['reason'])

    def test_check_cluster_status_error_waiting_other_nodes(self):
        stdout = self.test_data.DOG_CLUSTER_INFO_WAITING_OTHER_NODES
        stderr = ''
        expected_reason = _LE('Waiting for all nodes to join cluster. '
                              'Ensure all sheep daemons are running.')

        with mock.patch.object(self.client, '_run_dog') as fake_execute:
            fake_execute.return_value = (stdout, stderr)
            ex = self.assertRaises(exception.SheepdogError,
                                   self.client.check_cluster_status)
            self.assertEqual(expected_reason, ex.kwargs['reason'])

    def test_check_cluster_status_error_fail_to_coonect(self):
        cmd = self.test_data.CMD_DOG_CLUSTER_INFO
        exit_code = 2
        stdout = 'stdout_dummy'
        stderr = self.test_data.DOG_COMMAND_ERROR_FAIL_TO_CONNECT
        expected_msg = self.test_data.sheepdog_cmd_error(cmd=cmd,
                                                         exit_code=exit_code,
                                                         stdout=stdout,
                                                         stderr=stderr)
        expected_log = _LE('Failed to connect sheep daemon. '
                           'addr: %(addr)s, port: %(port)s')
        with mock.patch.object(self.client, '_run_dog') as fake_execute:
            with mock.patch.object(sheepdog, 'LOG') as fake_logger:
                fake_execute.side_effect = exception.SheepdogCmdError(
                    cmd=cmd, exit_code=exit_code,
                    stdout=stdout.replace('\n', '\\n'),
                    stderr=stderr.replace('\n', '\\n'))
                ex = self.assertRaises(exception.SheepdogCmdError,
                                       self.client.check_cluster_status)
                fake_logger.error.assert_called_with(expected_log,
                                                     {'addr': SHEEP_ADDR,
                                                      'port': SHEEP_PORT})
                self.assertEqual(expected_msg, ex.msg)

    def test_check_cluster_status_error_unknown(self):
        cmd = self.test_data.CMD_DOG_CLUSTER_INFO
        exit_code = 2
        stdout = 'stdout_dummy'
        stderr = 'stdout_dummy'
        expected_msg = self.test_data.sheepdog_cmd_error(cmd=cmd,
                                                         exit_code=exit_code,
                                                         stdout=stdout,
                                                         stderr=stderr)
        with mock.patch.object(self.client, '_run_dog') as fake_execute:
            fake_execute.side_effect = exception.SheepdogCmdError(
                cmd=cmd, exit_code=exit_code, stdout=stdout, stderr=stderr)
            ex = self.assertRaises(exception.SheepdogCmdError,
                                   self.client.check_cluster_status)
            self.assertEqual(expected_msg, ex.msg)

    # test for create method
    def test_create_success(self):
        expected_cmd = ('vdi', 'create', self.test_data.TEST_VOLUME['name'],
                        '%sG' % self.test_data.TEST_VOLUME['size'])
        with mock.patch.object(self.client, '_run_dog') as fake_execute:
            fake_execute.return_value = ('', '')
            self.client.create(self.test_data.TEST_VOLUME)
            fake_execute.assert_called_once_with(*expected_cmd)

    def test_create_failed_connected(self):
        cmd = self.test_data.cmd_dog_vdi_create(
            self.test_data.TEST_VOLUME['name'],
            self.test_data.TEST_VOLUME['size'])
        exit_code = 2
        stdout = ''
        stderr = self.test_data.DOG_COMMAND_ERROR_FAIL_TO_CONNECT
        expected_msg = self.test_data.sheepdog_cmd_error(
            cmd=cmd, exit_code=exit_code, stdout=stdout, stderr=stderr)
        expected_err = _LE('Failed to connect sheep daemon. '
                           'addr: %(addr)s, port: %(port)s') % \
            {'addr': SHEEP_ADDR, 'port': SHEEP_PORT}
        with mock.patch.object(self.client, '_run_dog') as fake_execute:
            fake_execute.side_effect = exception.SheepdogCmdError(
                cmd=cmd, exit_code=exit_code,
                stdout=stdout.replace('\n', '\\n'),
                stderr=stderr.replace('\n', '\\n'))
            with mock.patch.object(sheepdog, 'LOG') as fake_logger:
                ex = self.assertRaises(exception.SheepdogCmdError,
                                       self.client.create,
                                       self.test_data.TEST_VOLUME)
                fake_logger.error.assert_called_with(expected_err)
                self.assertEqual(expected_msg, ex.msg)

    def test_create_failed_vdi_already_exist(self):
        cmd = self.test_data.cmd_dog_vdi_create(
            self.test_data.TEST_VOLUME['name'],
            self.test_data.TEST_VOLUME['size'])
        exit_code = 1
        stdout = ''
        stderr = self.test_data.DOG_VDI_CREATE_VDI_EXISTS_ALREADY % \
            {'volname': self.test_data.TEST_VOLUME['name']}
        expected_msg = self.test_data.sheepdog_cmd_error(
            cmd=cmd, exit_code=exit_code, stdout=stdout, stderr=stderr)
        expected_err = _LE('Volume already exists. %s') % \
            self.test_data.TEST_VOLUME['name']
        with mock.patch.object(self.client, '_run_dog') as fake_execute:
            fake_execute.side_effect = exception.SheepdogCmdError(
                cmd=cmd, exit_code=exit_code,
                stdout=stdout.replace('\n', '\\n'),
                stderr=stderr.replace('\n', '\\n'))
            with mock.patch.object(sheepdog, 'LOG') as fake_logger:
                ex = self.assertRaises(exception.SheepdogCmdError,
                                       self.client.create,
                                       self.test_data.TEST_VOLUME)
                fake_logger.error.assert_called_with(expected_err)
                self.assertEqual(expected_msg, ex.msg)

    def test_create_failed_to_write_object(self):
        cmd = self.test_data.cmd_dog_vdi_create(
            self.test_data.TEST_VOLUME['name'],
            self.test_data.TEST_VOLUME['size'])
        exit_code = 1
        stdout = ''
        stderr = self.test_data.DOG_VDI_CREATE_FAILD_TO_WRITE_OBJECT % \
            {'volname': self.test_data.TEST_VOLUME['name']}
        expected_msg = self.test_data.sheepdog_cmd_error(
            cmd=cmd, exit_code=exit_code, stdout=stdout, stderr=stderr)
        expected_err = _LE('Failed to write object to any sheep node. %s') % \
            self.test_data.TEST_VOLUME['name']
        with mock.patch.object(self.client, '_run_dog') as fake_execute:
            fake_execute.side_effect = exception.SheepdogCmdError(
                cmd=cmd, exit_code=exit_code,
                stdout=stdout.replace('\n', '\\n'),
                stderr=stderr.replace('\n', '\\n'))
            with mock.patch.object(sheepdog, 'LOG') as fake_logger:
                ex = self.assertRaises(exception.SheepdogCmdError,
                                       self.client.create,
                                       self.test_data.TEST_VOLUME)
                fake_logger.error.assert_called_with(expected_err)
                self.assertEqual(expected_msg, ex.msg)

    def test_create_failed_unknown(self):
        cmd = self.test_data.cmd_dog_vdi_create(
            self.test_data.TEST_VOLUME['name'],
            self.test_data.TEST_VOLUME['size'])
        exit_code = 1
        stdout = 'stdout_dummy'
        stderr = 'stderr_dummy'
        expected_msg = self.test_data.sheepdog_cmd_error(
            cmd=cmd, exit_code=exit_code, stdout=stdout, stderr=stderr)
        expected_err = _LE('Failed to create volume. %s') % \
            self.test_data.TEST_VOLUME['name']
        with mock.patch.object(self.client, '_run_dog') as fake_execute:
            fake_execute.side_effect = exception.SheepdogCmdError(
                cmd=cmd, exit_code=exit_code,
                stdout=stdout.replace('\n', '\\n'),
                stderr=stderr.replace('\n', '\\n'))
            with mock.patch.object(sheepdog, 'LOG') as fake_logger:
                ex = self.assertRaises(exception.SheepdogCmdError,
                                       self.client.create,
                                       self.test_data.TEST_VOLUME)
                fake_logger.error.assert_called_with(expected_err)
                self.assertEqual(expected_msg, ex.msg)

    # test for delete method
    def test_delete_success(self):
        expected_cmd = ('vdi', 'delete', self.test_data.TEST_VOLUME['name'])
        with mock.patch.object(self.client, '_run_dog') as fake_execute:
            fake_execute.return_value = ('', '')
            self.client.delete(self.test_data.TEST_VOLUME)
            fake_execute.assert_called_once_with(*expected_cmd)

    def test_delete_not_found(self):
        expected_cmd = ('vdi', 'delete', self.test_data.TEST_VOLUME['name'])
        stdout = ''
        stderr = self.test_data.DOG_VDI_DELETE_VDI_NOT_EXISTS
        expected_log = _LW('Volume not found. %(volname)s') % \
            {'volname': self.test_data.TEST_VOLUME['name']}
        with mock.patch.object(self.client, '_run_dog') as fake_execute:
            with mock.patch.object(sheepdog, 'LOG') as fake_logger:
                fake_execute.return_value = (stdout, stderr)
                self.client.delete(self.test_data.TEST_VOLUME)
                fake_execute.assert_called_once_with(*expected_cmd)
                fake_logger.warning.assert_called_with(expected_log)

    def test_delete_failed_to_connect(self):
        cmd = self.test_data.cmd_dog_vdi_delete(
            self.test_data.TEST_VOLUME['name'])
        exit_code = 2
        stdout = 'stdout_dummy'
        stderr = self.test_data.DOG_COMMAND_ERROR_FAIL_TO_CONNECT
        expected_msg = self.test_data.sheepdog_cmd_error(cmd=cmd,
                                                         exit_code=exit_code,
                                                         stdout=stdout,
                                                         stderr=stderr)
        expected_log = _LE('Failed to connect sheep daemon. '
                           'addr: %(addr)s, port: %(port)s') % \
            {'addr': SHEEP_ADDR, 'port': SHEEP_PORT}
        with mock.patch.object(self.client, '_run_dog') as fake_execute:
            with mock.patch.object(sheepdog, 'LOG') as fake_logger:
                fake_execute.side_effect = exception.SheepdogCmdError(
                    cmd=cmd, exit_code=exit_code,
                    stdout=stdout.replace('\n', '\\n'),
                    stderr=stderr.replace('\n', '\\n'))
                ex = self.assertRaises(exception.SheepdogCmdError,
                                       self.client.delete,
                                       self.test_data.TEST_VOLUME)
                fake_logger.error.assert_called_with(expected_log)
                self.assertEqual(expected_msg, ex.msg)

    def test_delete_failed_unknown(self):
        cmd = self.test_data.cmd_dog_vdi_delete(
            self.test_data.TEST_VOLUME['name'])
        exit_code = 2
        stdout = 'stdout_dummy'
        stderr = 'stderr_dummy'
        expected_msg = self.test_data.sheepdog_cmd_error(cmd=cmd,
                                                         exit_code=exit_code,
                                                         stdout=stdout,
                                                         stderr=stderr)
        expected_log = _LE('Failed to delete volume. %(volume)s') % \
            {'volume': self.test_data.TEST_VOLUME['name']}
        with mock.patch.object(self.client, '_run_dog') as fake_execute:
            with mock.patch.object(sheepdog, 'LOG') as fake_logger:
                fake_execute.side_effect = exception.SheepdogCmdError(
                    cmd=cmd, exit_code=exit_code,
                    stdout=stdout.replace('\n', '\\n'),
                    stderr=stderr.replace('\n', '\\n'))
                ex = self.assertRaises(exception.SheepdogCmdError,
                                       self.client.delete,
                                       self.test_data.TEST_VOLUME)
                fake_logger.error.assert_called_with(expected_log)
                self.assertEqual(expected_msg, ex.msg)


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

    def test_check_for_setup_error(self):
        with mock.patch.object(self.client, 'check_cluster_status') \
                as fake_execute:
            self.driver.check_for_setup_error()
        fake_execute.assert_called_once_with()

    def test_create_volume(self):
        with mock.patch.object(self.client, 'create') as fake_execute:
            self.driver.create_volume(self.test_data.TEST_VOLUME)
            fake_execute.assert_called_once_with(self.test_data.TEST_VOLUME)

    def test_delete_volume(self):
        with mock.patch.object(self.client, 'delete') as fake_execute:
            self.driver.delete_volume(self.test_data.TEST_VOLUME)
            fake_execute.assert_called_once_with(self.test_data.TEST_VOLUME)

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

    def test_copy_image_to_volume(self):
        @contextlib.contextmanager
        def fake_temp_file():
            class FakeTmp(object):
                def __init__(self, name):
                    self.name = name
            yield FakeTmp('test').name

        def fake_try_execute(obj, *command, **kwargs):
            return True

        def fake_run_dog(obj, command, subcommand, *params):
            return ('fake_stdout', 'fake_stderr')

        self.stubs.Set(image_utils, 'temporary_file', fake_temp_file)
        self.stubs.Set(image_utils, 'fetch_verify_image',
                       lambda w, x, y, z: None)
        self.stubs.Set(image_utils, 'convert_image',
                       lambda x, y, z: None)
        self.stubs.Set(sheepdog.SheepdogDriver,
                       '_try_execute',
                       fake_try_execute)
        self.stubs.Set(sheepdog.SheepdogClient,
                       '_run_dog',
                       fake_run_dog)
        self.driver.copy_image_to_volume(None, {'name': 'test',
                                                'size': 1},
                                         FakeImageService(), None)

    def test_copy_volume_to_image(self):
        fake_context = {}
        fake_volume = {'name': 'volume-00000001'}
        fake_image_service = mock.Mock()
        fake_image_service_update = mock.Mock()
        fake_image_meta = {'id': '10958016-e196-42e3-9e7f-5d8927ae3099'}

        patch = mock.patch.object
        with patch(self.driver, '_try_execute') as fake_try_execute:
            with patch(fake_image_service,
                       'update') as fake_image_service_update:
                self.driver.copy_volume_to_image(fake_context,
                                                 fake_volume,
                                                 fake_image_service,
                                                 fake_image_meta)

                expected_cmd = ('qemu-img',
                                'convert',
                                '-f', 'raw',
                                '-t', 'none',
                                '-O', 'raw',
                                'sheepdog:%s' % fake_volume['name'],
                                mock.ANY)
                fake_try_execute.assert_called_once_with(*expected_cmd)
                fake_image_service_update.assert_called_once_with(
                    fake_context, fake_image_meta['id'], mock.ANY, mock.ANY)

    def test_copy_volume_to_image_nonexistent_volume(self):
        fake_context = {}
        fake_volume = {
            'name': 'nonexistent-volume-82c4539e-c2a5-11e4-a293-0aa186c60fe0'}
        fake_image_service = mock.Mock()
        fake_image_meta = {'id': '10958016-e196-42e3-9e7f-5d8927ae3099'}

        # The command is expected to fail, so we don't want to retry it.
        self.driver._try_execute = self.driver._execute

        args = (fake_context, fake_volume, fake_image_service, fake_image_meta)
        expected_errors = (processutils.ProcessExecutionError, OSError)
        self.assertRaises(expected_errors,
                          self.driver.copy_volume_to_image,
                          *args)

    def test_create_cloned_volume(self):
        src_vol = {
            'project_id': 'testprjid',
            'name': six.text_type('volume-00000001'),
            'size': '20',
            'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66',
        }
        target_vol = {
            'project_id': 'testprjid',
            'name': six.text_type('volume-00000002'),
            'size': '20',
            'id': '582a1efa-be6a-11e4-a73b-0aa186c60fe0',
        }

        with mock.patch.object(self.driver,
                               '_try_execute') as mock_exe:
            self.driver.create_cloned_volume(target_vol, src_vol)

            snapshot_name = src_vol['name'] + '-temp-snapshot'
            qemu_src_volume_name = "sheepdog:%s" % src_vol['name']
            qemu_snapshot_name = '%s:%s' % (qemu_src_volume_name,
                                            snapshot_name)
            qemu_target_volume_name = "sheepdog:%s" % target_vol['name']
            calls = [
                mock.call('qemu-img', 'snapshot', '-c',
                          snapshot_name, qemu_src_volume_name),
                mock.call('qemu-img', 'create', '-b',
                          qemu_snapshot_name,
                          qemu_target_volume_name,
                          '%sG' % target_vol['size']),
            ]
            mock_exe.assert_has_calls(calls)

    def test_create_cloned_volume_failure(self):
        fake_name = six.text_type('volume-00000001')
        fake_size = '20'
        fake_vol = {'project_id': 'testprjid', 'name': fake_name,
                    'size': fake_size,
                    'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66'}
        src_vol = fake_vol

        patch = mock.patch.object
        with patch(self.driver, '_try_execute',
                   side_effect=processutils.ProcessExecutionError):
            with patch(self.driver, 'create_snapshot'):
                with patch(self.driver, 'delete_snapshot'):
                    self.assertRaises(exception.VolumeBackendAPIException,
                                      self.driver.create_cloned_volume,
                                      fake_vol,
                                      src_vol)

    def test_clone_image_success(self):
        context = {}
        fake_name = six.text_type('volume-00000001')
        fake_size = '2'
        fake_vol = {'project_id': 'testprjid', 'name': fake_name,
                    'size': fake_size,
                    'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66'}

        image_location = ('sheepdog:192.168.1.111:7000:Alice', None)
        image_id = "caa4ffd0-fake-fake-fake-f8631a807f5a"
        image_meta = {'id': image_id, 'size': 1, 'disk_format': 'raw'}
        image_service = ''

        patch = mock.patch.object
        with patch(self.driver, '_try_execute', return_value=True):
            with patch(self.driver, 'create_cloned_volume'):
                with patch(self.driver, '_resize'):
                    model_updated, cloned = self.driver.clone_image(
                        context, fake_vol, image_location,
                        image_meta, image_service)

        self.assertTrue(cloned)
        self.assertEqual("sheepdog:%s" % fake_name,
                         model_updated['provider_location'])

    def test_clone_image_failure(self):
        context = {}
        fake_vol = {}
        image_location = ('image_location', None)
        image_meta = {}
        image_service = ''

        with mock.patch.object(self.driver, '_is_cloneable',
                               lambda *args: False):
            result = self.driver.clone_image(
                context, fake_vol, image_location, image_meta, image_service)
            self.assertEqual(({}, False), result)

    def test_is_cloneable(self):
        uuid = '87f1b01c-f46c-4537-bd5d-23962f5f4316'
        location = 'sheepdog:ip:port:%s' % uuid
        image_meta = {'id': uuid, 'size': 1, 'disk_format': 'raw'}
        invalid_image_meta = {'id': uuid, 'size': 1, 'disk_format': 'iso'}

        with mock.patch.object(self.driver, '_try_execute') as try_execute:
            self.assertTrue(
                self.driver._is_cloneable(location, image_meta))
            expected_cmd = ('dog', 'vdi', 'list',
                            '--address', 'ip',
                            '--port', 'port',
                            uuid)
            try_execute.assert_called_once_with(*expected_cmd)

            # check returning False without executing a command
            self.assertFalse(
                self.driver._is_cloneable('invalid-location', image_meta))
            self.assertFalse(
                self.driver._is_cloneable(location, invalid_image_meta))
            self.assertEqual(1, try_execute.call_count)

        error = processutils.ProcessExecutionError
        with mock.patch.object(self.driver, '_try_execute',
                               side_effect=error) as fail_try_execute:
            self.assertFalse(
                self.driver._is_cloneable(location, image_meta))
            fail_try_execute.assert_called_once_with(*expected_cmd)

    def test_extend_volume(self):
        fake_name = u'volume-00000001'
        fake_size = '20'
        fake_vol = {'project_id': 'testprjid', 'name': fake_name,
                    'size': fake_size,
                    'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66'}

        self.mox.StubOutWithMock(self.driver, '_resize')
        size = int(fake_size) * units.Gi
        self.driver._resize(fake_vol, size=size)

        self.mox.ReplayAll()
        self.driver.extend_volume(fake_vol, fake_size)

        self.mox.VerifyAll()

    def test_create_volume_from_snapshot(self):
        fake_name = u'volume-00000001'
        fake_size = '10'
        fake_vol = {'project_id': 'testprjid', 'name': fake_name,
                    'size': fake_size,
                    'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66'}

        ss_uuid = '00000000-0000-0000-0000-c3aa7ee01536'
        fake_snapshot = {'volume_name': fake_name,
                         'name': 'volume-%s' % ss_uuid,
                         'id': ss_uuid,
                         'size': fake_size}

        with mock.patch.object(sheepdog.SheepdogDriver,
                               '_try_execute') as mock_exe:
            self.driver.create_volume_from_snapshot(fake_vol, fake_snapshot)
            args = ['qemu-img', 'create', '-b',
                    "sheepdog:%s:%s" % (fake_snapshot['volume_name'],
                                        fake_snapshot['name']),
                    "sheepdog:%s" % fake_vol['name'],
                    "%sG" % fake_vol['size']]
            mock_exe.assert_called_once_with(*args)
