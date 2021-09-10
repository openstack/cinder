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

import collections
import datetime
import errno
import io
import re
import sys
import time
from unittest import mock

import ddt
import fixtures
import iso8601
from oslo_config import cfg
from oslo_db import exception as oslo_exception
from oslo_utils import timeutils

# Prevent load failures on macOS
if sys.platform == 'darwin':
    rtslib_fb = mock.MagicMock()
    cinder_rtstool = mock.MagicMock()
else:
    import rtslib_fb

from cinder.cmd import api as cinder_api
from cinder.cmd import backup as cinder_backup
from cinder.cmd import manage as cinder_manage
if sys.platform != 'darwin':
    from cinder.cmd import rtstool as cinder_rtstool
from cinder.cmd import scheduler as cinder_scheduler
from cinder.cmd import volume as cinder_volume
from cinder.cmd import volume_usage_audit
from cinder.common import constants
from cinder import context
from cinder.db.sqlalchemy import api as sqlalchemy_api
from cinder import exception
from cinder.objects import fields
from cinder.tests.unit import fake_cluster
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_service
from cinder.tests.unit import fake_volume
from cinder.tests.unit import test
from cinder.tests.unit import utils
from cinder import version
from cinder.volume import rpcapi

CONF = cfg.CONF


class TestCinderApiCmd(test.TestCase):
    """Unit test cases for python modules under cinder/cmd."""

    def setUp(self):
        super(TestCinderApiCmd, self).setUp()
        sys.argv = ['cinder-api']

    @mock.patch('cinder.service.WSGIService')
    @mock.patch('cinder.service.process_launcher')
    @mock.patch('cinder.rpc.init')
    @mock.patch('cinder.utils.monkey_patch')
    @mock.patch('oslo_log.log.setup')
    def test_main(self, log_setup, monkey_patch, rpc_init, process_launcher,
                  wsgi_service):
        launcher = process_launcher.return_value
        server = wsgi_service.return_value
        server.workers = mock.sentinel.worker_count

        cinder_api.main()

        self.assertEqual('cinder', CONF.project)
        self.assertEqual(CONF.version, version.version_string())
        log_setup.assert_called_once_with(CONF, "cinder")
        monkey_patch.assert_called_once_with()
        rpc_init.assert_called_once_with(CONF)
        process_launcher.assert_called_once_with()
        wsgi_service.assert_called_once_with('osapi_volume')
        launcher.launch_service.assert_called_once_with(
            server,
            workers=server.workers)
        launcher.wait.assert_called_once_with()


class TestCinderBackupCmd(test.TestCase):

    def setUp(self):
        super(TestCinderBackupCmd, self).setUp()
        sys.argv = ['cinder-backup']

    @mock.patch('cinder.utils.Semaphore')
    @mock.patch('cinder.service.get_launcher')
    @mock.patch('cinder.service.Service.create')
    @mock.patch('cinder.utils.monkey_patch')
    @mock.patch('oslo_log.log.setup')
    def test_main_multiprocess(self, log_setup, monkey_patch, service_create,
                               get_launcher, mock_semaphore):
        CONF.set_override('backup_workers', 2)
        mock_semaphore.side_effect = [mock.sentinel.semaphore1,
                                      mock.sentinel.semaphore2]
        cinder_backup.main()

        self.assertEqual('cinder', CONF.project)
        self.assertEqual(CONF.version, version.version_string())

        # Both calls must receive the same semaphore
        c1 = mock.call(binary=constants.BACKUP_BINARY,
                       coordination=True,
                       process_number=1,
                       semaphore=mock.sentinel.semaphore1,
                       service_name='backup')
        c2 = mock.call(binary=constants.BACKUP_BINARY,
                       coordination=True,
                       process_number=2,
                       semaphore=mock.sentinel.semaphore1,
                       service_name='backup')
        service_create.assert_has_calls([c1, c2])

        launcher = get_launcher.return_value
        self.assertEqual(2, launcher.launch_service.call_count)
        launcher.wait.assert_called_once_with()


class TestCinderSchedulerCmd(test.TestCase):

    def setUp(self):
        super(TestCinderSchedulerCmd, self).setUp()
        sys.argv = ['cinder-scheduler']

    @mock.patch('cinder.service.wait')
    @mock.patch('cinder.service.serve')
    @mock.patch('cinder.service.Service.create')
    @mock.patch('cinder.utils.monkey_patch')
    @mock.patch('oslo_log.log.setup')
    def test_main(self, log_setup, monkey_patch, service_create,
                  service_serve, service_wait):
        server = service_create.return_value

        cinder_scheduler.main()

        self.assertEqual('cinder', CONF.project)
        self.assertEqual(CONF.version, version.version_string())
        log_setup.assert_called_once_with(CONF, "cinder")
        monkey_patch.assert_called_once_with()
        service_create.assert_called_once_with(binary='cinder-scheduler')
        service_serve.assert_called_once_with(server)
        service_wait.assert_called_once_with()


class TestCinderVolumeCmdPosix(test.TestCase):

    def setUp(self):
        super(TestCinderVolumeCmdPosix, self).setUp()
        sys.argv = ['cinder-volume']

        self.patch('os.name', 'posix')

    @mock.patch('cinder.service.get_launcher')
    @mock.patch('cinder.service.Service.create')
    @mock.patch('cinder.utils.monkey_patch')
    @mock.patch('oslo_log.log.setup')
    def test_main(self, log_setup, monkey_patch, service_create,
                  get_launcher):
        CONF.set_override('enabled_backends', None)
        self.assertRaises(SystemExit, cinder_volume.main)
        self.assertFalse(service_create.called)

    @mock.patch('cinder.service.get_launcher')
    @mock.patch('cinder.service.Service.create')
    @mock.patch('cinder.utils.monkey_patch')
    @mock.patch('oslo_log.log.setup')
    def test_main_with_backends(self, log_setup, monkey_patch, service_create,
                                get_launcher):
        backends = ['', 'backend1', 'backend2', '']
        CONF.set_override('enabled_backends', backends)
        CONF.set_override('host', 'host')
        CONF.set_override('cluster', None)
        launcher = get_launcher.return_value

        cinder_volume.main()

        self.assertEqual('cinder', CONF.project)
        self.assertEqual(CONF.version, version.version_string())
        log_setup.assert_called_once_with(CONF, "cinder")
        monkey_patch.assert_called_once_with()
        get_launcher.assert_called_once_with()
        c1 = mock.call(binary=constants.VOLUME_BINARY, host='host@backend1',
                       service_name='backend1', coordination=True,
                       cluster=None)
        c2 = mock.call(binary=constants.VOLUME_BINARY, host='host@backend2',
                       service_name='backend2', coordination=True,
                       cluster=None)
        service_create.assert_has_calls([c1, c2])
        self.assertEqual(2, launcher.launch_service.call_count)
        launcher.wait.assert_called_once_with()


@ddt.ddt
@test.testtools.skipIf(sys.platform == 'darwin', 'Not supported on macOS')
class TestCinderVolumeCmdWin32(test.TestCase):

    def setUp(self):
        super(TestCinderVolumeCmdWin32, self).setUp()
        sys.argv = ['cinder-volume']

        self._mock_win32_proc_launcher = mock.Mock()

        self.patch('os.name', 'nt')
        self.patch('cinder.service.WindowsProcessLauncher',
                   lambda *args, **kwargs: self._mock_win32_proc_launcher)

    @mock.patch('cinder.service.get_launcher')
    @mock.patch('cinder.service.Service.create')
    @mock.patch('cinder.utils.monkey_patch')
    @mock.patch('oslo_log.log.setup')
    def test_main(self, log_setup, monkey_patch, service_create,
                  get_launcher):
        CONF.set_override('enabled_backends', None)
        self.assertRaises(SystemExit, cinder_volume.main)
        self.assertFalse(service_create.called)
        self.assertFalse(self._mock_win32_proc_launcher.called)

    @mock.patch('cinder.service.get_launcher')
    @mock.patch('cinder.service.Service.create')
    @mock.patch('cinder.utils.monkey_patch')
    @mock.patch('oslo_log.log.setup')
    def test_main_invalid_backend(self, log_setup, monkey_patch,
                                  service_create, get_launcher):
        CONF.set_override('enabled_backends', 'backend1')
        CONF.set_override('backend_name', 'backend2')
        self.assertRaises(exception.InvalidInput, cinder_volume.main)
        self.assertFalse(service_create.called)
        self.assertFalse(self._mock_win32_proc_launcher.called)

    @mock.patch('cinder.utils.monkey_patch')
    @mock.patch('oslo_log.log.setup')
    @ddt.data({},
              {'binary_path': 'cinder-volume-script.py',
               'exp_py_executable': True})
    @ddt.unpack
    def test_main_with_multiple_backends(self, log_setup, monkey_patch,
                                         binary_path='cinder-volume',
                                         exp_py_executable=False):
        # If multiple backends are used, we expect the Windows process
        # launcher to be used in order to create the child processes.
        backends = ['', 'backend1', 'backend2', '']
        CONF.set_override('enabled_backends', backends)
        CONF.set_override('host', 'host')
        launcher = self._mock_win32_proc_launcher

        # Depending on the setuptools version, '-script.py' and '.exe'
        # binary path extensions may be trimmed. We need to take this
        # into consideration when building the command that will be
        # used to spawn child subprocesses.
        sys.argv = [binary_path]

        cinder_volume.main()

        self.assertEqual('cinder', CONF.project)
        self.assertEqual(CONF.version, version.version_string())
        log_setup.assert_called_once_with(CONF, "cinder")
        monkey_patch.assert_called_once_with()

        exp_cmd_prefix = [sys.executable] if exp_py_executable else []
        exp_cmds = [
            exp_cmd_prefix + sys.argv + ['--backend_name=%s' % backend_name]
            for backend_name in ['backend1', 'backend2']]
        launcher.add_process.assert_has_calls(
            [mock.call(exp_cmd) for exp_cmd in exp_cmds])
        launcher.wait.assert_called_once_with()

    @mock.patch('cinder.service.get_launcher')
    @mock.patch('cinder.service.Service.create')
    @mock.patch('cinder.utils.monkey_patch')
    @mock.patch('oslo_log.log.setup')
    def test_main_with_multiple_backends_child(
            self, log_setup, monkey_patch, service_create, get_launcher):
        # We're testing the code expected to be run within child processes.
        backends = ['', 'backend1', 'backend2', '']
        CONF.set_override('enabled_backends', backends)
        CONF.set_override('host', 'host')
        CONF.set_override('cluster', None)
        launcher = get_launcher.return_value

        sys.argv += ['--backend_name', 'backend2']

        cinder_volume.main()

        self.assertEqual('cinder', CONF.project)
        self.assertEqual(CONF.version, version.version_string())
        log_setup.assert_called_once_with(CONF, "cinder")
        monkey_patch.assert_called_once_with()

        service_create.assert_called_once_with(
            binary=constants.VOLUME_BINARY, host='host@backend2',
            service_name='backend2', coordination=True,
            cluster=None)
        launcher.launch_service.assert_called_once_with(
            service_create.return_value)

    @mock.patch('cinder.service.get_launcher')
    @mock.patch('cinder.service.Service.create')
    @mock.patch('cinder.utils.monkey_patch')
    @mock.patch('oslo_log.log.setup')
    def test_main_with_single_backend(
            self, log_setup, monkey_patch, service_create, get_launcher):
        # We're expecting the service to be run within the same process.
        CONF.set_override('enabled_backends', ['backend2'])
        CONF.set_override('host', 'host')
        CONF.set_override('cluster', None)
        launcher = get_launcher.return_value

        cinder_volume.main()

        self.assertEqual('cinder', CONF.project)
        self.assertEqual(CONF.version, version.version_string())
        log_setup.assert_called_once_with(CONF, "cinder")
        monkey_patch.assert_called_once_with()

        service_create.assert_called_once_with(
            binary=constants.VOLUME_BINARY, host='host@backend2',
            service_name='backend2', coordination=True,
            cluster=None)
        launcher.launch_service.assert_called_once_with(
            service_create.return_value)


@ddt.ddt
class TestCinderManageCmd(test.TestCase):

    def setUp(self):
        super(TestCinderManageCmd, self).setUp()
        sys.argv = ['cinder-manage']

    def _test_purge_invalid_age_in_days(self, age_in_days):
        db_cmds = cinder_manage.DbCommands()
        ex = self.assertRaises(SystemExit, db_cmds.purge, age_in_days)
        self.assertEqual(1, ex.code)

    @mock.patch('cinder.objects.ServiceList.get_all')
    @mock.patch('cinder.db.migration.db_sync')
    def test_db_commands_sync(self, db_sync, service_get_mock):
        version = 11
        db_cmds = cinder_manage.DbCommands()
        db_cmds.sync(version=version)
        db_sync.assert_called_once_with(version)
        service_get_mock.assert_not_called()

    @mock.patch('cinder.objects.Service.save')
    @mock.patch('cinder.objects.ServiceList.get_all')
    @mock.patch('cinder.db.migration.db_sync')
    def test_db_commands_sync_bump_versions(self, db_sync, service_get_mock,
                                            service_save):
        ctxt = context.get_admin_context()
        services = [fake_service.fake_service_obj(ctxt,
                                                  binary='cinder-' + binary,
                                                  rpc_current_version='0.1',
                                                  object_current_version='0.2')
                    for binary in ('volume', 'scheduler', 'backup')]
        service_get_mock.return_value = services

        version = 11
        db_cmds = cinder_manage.DbCommands()
        db_cmds.sync(version=version, bump_versions=True)
        db_sync.assert_called_once_with(version)

        self.assertEqual(3, service_save.call_count)
        for service in services:
            self.assertEqual(cinder_manage.RPC_VERSIONS[service.binary],
                             service.rpc_current_version)
            self.assertEqual(cinder_manage.OVO_VERSION,
                             service.object_current_version)

    @mock.patch('cinder.db.migration.db_version')
    def test_db_commands_version(self, db_version):
        db_cmds = cinder_manage.DbCommands()
        with mock.patch('sys.stdout', new=io.StringIO()):
            db_cmds.version()
            self.assertEqual(1, db_version.call_count)

    def test_db_commands_upgrade_out_of_range(self):
        version = 2147483647
        db_cmds = cinder_manage.DbCommands()
        exit = self.assertRaises(SystemExit, db_cmds.sync, version + 1)
        self.assertEqual(1, exit.code)

    @mock.patch('cinder.db.migration.db_sync')
    def test_db_commands_script_not_present(self, db_sync):
        db_sync.side_effect = oslo_exception.DBMigrationError(None)
        db_cmds = cinder_manage.DbCommands()
        exit = self.assertRaises(SystemExit, db_cmds.sync, 101)
        self.assertEqual(1, exit.code)

    @mock.patch('cinder.cmd.manage.DbCommands.online_migrations',
                (mock.Mock(side_effect=((2, 2), (0, 0)), __name__='foo'),))
    def test_db_commands_online_data_migrations(self):
        db_cmds = cinder_manage.DbCommands()
        exit = self.assertRaises(SystemExit, db_cmds.online_data_migrations)
        self.assertEqual(0, exit.code)
        cinder_manage.DbCommands.online_migrations[0].assert_has_calls(
            (mock.call(mock.ANY, 50),) * 2)

    def _fake_db_command(self, migrations=None):
        if migrations is None:
            mock_mig_1 = mock.MagicMock(__name__="mock_mig_1")
            mock_mig_2 = mock.MagicMock(__name__="mock_mig_2")
            mock_mig_1.return_value = (5, 4)
            mock_mig_2.return_value = (6, 6)
            migrations = (mock_mig_1, mock_mig_2)

        class _CommandSub(cinder_manage.DbCommands):
            online_migrations = migrations

        return _CommandSub

    @mock.patch('cinder.context.get_admin_context')
    def test_online_migrations(self, mock_get_context):
        self.useFixture(fixtures.MonkeyPatch('sys.stdout', io.StringIO()))
        ctxt = mock_get_context.return_value
        db_cmds = self._fake_db_command()
        command = db_cmds()
        exit = self.assertRaises(SystemExit,
                                 command.online_data_migrations, 10)
        self.assertEqual(1, exit.code)
        command.online_migrations[0].assert_has_calls([mock.call(ctxt,
                                                                 10)])
        command.online_migrations[1].assert_has_calls([mock.call(ctxt,
                                                                 6)])

        output = sys.stdout.getvalue()
        matches = re.findall(
            '5 rows matched query mock_mig_1, 4 migrated',
            output, re.MULTILINE)
        self.assertEqual(len(matches), 1)
        matches = re.findall(
            '6 rows matched query mock_mig_2, 6 migrated',
            output, re.MULTILINE)
        self.assertEqual(len(matches), 1)
        matches = re.findall(
            'mock_mig_1 .* 5 .* 4',
            output, re.MULTILINE)
        self.assertEqual(len(matches), 1)
        matches = re.findall(
            'mock_mig_2 .* 6 .* 6',
            output, re.MULTILINE)
        self.assertEqual(len(matches), 1)

    @mock.patch('cinder.context.get_admin_context')
    def test_online_migrations_no_max_count(self, mock_get_context):
        self.useFixture(fixtures.MonkeyPatch('sys.stdout', io.StringIO()))
        fake_remaining = [120]

        def fake_migration(context, count):
            self.assertEqual(mock_get_context.return_value, context)
            found = 120
            done = min(fake_remaining[0], count)
            fake_remaining[0] -= done
            return found, done

        command_cls = self._fake_db_command((fake_migration,))
        command = command_cls()

        exit = self.assertRaises(SystemExit,
                                 command.online_data_migrations, None)
        self.assertEqual(0, exit.code)
        output = sys.stdout.getvalue()
        self.assertIn('Running batches of 50 until complete.', output)
        matches = re.findall(
            '120 rows matched query fake_migration, 50 migrated',
            output, re.MULTILINE)
        self.assertEqual(len(matches), 2)
        matches = re.findall(
            '120 rows matched query fake_migration, 20 migrated',
            output, re.MULTILINE)
        self.assertEqual(len(matches), 1)
        matches = re.findall(
            '120 rows matched query fake_migration, 0 migrated',
            output, re.MULTILINE)
        self.assertEqual(len(matches), 1)
        matches = re.findall(
            'fake_migration .* 120 .* 120',
            output, re.MULTILINE)
        self.assertEqual(len(matches), 1)

    @mock.patch('cinder.context.get_admin_context')
    def test_online_migrations_error(self, mock_get_context):
        self.useFixture(fixtures.MonkeyPatch('sys.stdout', io.StringIO()))
        good_remaining = [50]

        def good_migration(context, count):
            self.assertEqual(mock_get_context.return_value, context)
            found = 50
            done = min(good_remaining[0], count)
            good_remaining[0] -= done
            return found, done

        bad_migration = mock.MagicMock()
        bad_migration.side_effect = test.TestingException
        bad_migration.__name__ = 'bad_migration'

        command_cls = self._fake_db_command((bad_migration, good_migration))
        command = command_cls()

        # bad_migration raises an exception, but it could be because
        # good_migration had not completed yet. We should get 1 in this case,
        # because some work was done, and the command should be reiterated.
        exit = self.assertRaises(SystemExit,
                                 command.online_data_migrations, max_count=50)
        self.assertEqual(1, exit.code)

        # When running this for the second time, there's no work left for
        # good_migration to do, but bad_migration still fails - should
        # get 2 this time.
        exit = self.assertRaises(SystemExit,
                                 command.online_data_migrations, max_count=50)
        self.assertEqual(2, exit.code)

        # When --max_count is not used, we should get 2 if all possible
        # migrations completed but some raise exceptions
        good_remaining = [50]
        exit = self.assertRaises(SystemExit,
                                 command.online_data_migrations, None)
        self.assertEqual(2, exit.code)

    @mock.patch('cinder.cmd.manage.DbCommands.online_migrations',
                (mock.Mock(side_effect=((2, 2), (0, 0)), __name__='foo'),))
    def test_db_commands_online_data_migrations_ignore_state_and_max(self):
        db_cmds = cinder_manage.DbCommands()
        exit = self.assertRaises(SystemExit, db_cmds.online_data_migrations,
                                 2)
        self.assertEqual(1, exit.code)
        cinder_manage.DbCommands.online_migrations[0].assert_called_once_with(
            mock.ANY, 2)

    @mock.patch('cinder.cmd.manage.DbCommands.online_migrations',
                (mock.Mock(side_effect=((2, 2), (0, 0)), __name__='foo'),))
    def test_db_commands_online_data_migrations_max_negative(self):
        db_cmds = cinder_manage.DbCommands()
        exit = self.assertRaises(SystemExit, db_cmds.online_data_migrations,
                                 -1)
        self.assertEqual(127, exit.code)
        cinder_manage.DbCommands.online_migrations[0].assert_not_called()

    @mock.patch('cinder.db.reset_active_backend')
    @mock.patch('cinder.context.get_admin_context')
    def test_db_commands_reset_active_backend(self, admin_ctxt_mock,
                                              reset_backend_mock):
        db_cmds = cinder_manage.DbCommands()
        db_cmds.reset_active_backend(True, 'fake-backend-id', 'fake-host')
        reset_backend_mock.assert_called_with(admin_ctxt_mock.return_value,
                                              True, 'fake-backend-id',
                                              'fake-host')

    @mock.patch('cinder.version.version_string')
    def test_versions_commands_list(self, version_string):
        version_cmds = cinder_manage.VersionCommands()
        with mock.patch('sys.stdout', new=io.StringIO()):
            version_cmds.list()
            version_string.assert_called_once_with()

    @mock.patch('cinder.version.version_string')
    def test_versions_commands_call(self, version_string):
        version_cmds = cinder_manage.VersionCommands()
        with mock.patch('sys.stdout', new=io.StringIO()):
            version_cmds.__call__()
            version_string.assert_called_once_with()

    def test_purge_with_negative_age_in_days(self):
        age_in_days = -1
        self._test_purge_invalid_age_in_days(age_in_days)

    def test_purge_exceeded_age_in_days_limit(self):
        age_in_days = int(time.time() / 86400) + 1
        self._test_purge_invalid_age_in_days(age_in_days)

    @mock.patch('cinder.db.sqlalchemy.api.purge_deleted_rows')
    @mock.patch('cinder.context.get_admin_context')
    def test_purge_less_than_age_in_days_limit(self, get_admin_context,
                                               purge_deleted_rows):
        age_in_days = int(time.time() / 86400) - 1
        ctxt = context.RequestContext(fake.USER_ID, fake.PROJECT_ID,
                                      is_admin=True)
        get_admin_context.return_value = ctxt

        purge_deleted_rows.return_value = None

        db_cmds = cinder_manage.DbCommands()
        db_cmds.purge(age_in_days)

        get_admin_context.assert_called_once_with()
        purge_deleted_rows.assert_called_once_with(
            ctxt, age_in_days=age_in_days)

    @mock.patch('cinder.db.service_get_all')
    @mock.patch('cinder.context.get_admin_context')
    def test_host_commands_list(self, get_admin_context, service_get_all):
        get_admin_context.return_value = mock.sentinel.ctxt
        service_get_all.return_value = [
            {'host': 'fake-host',
             'availability_zone': 'fake-az',
             'uuid': 'a3a593da-7f8d-4bb7-8b4c-f2bc1e0b4824'}]

        with mock.patch('sys.stdout', new=io.StringIO()) as fake_out:
            expected_out = ("%(host)-25s\t%(zone)-15s\n" %
                            {'host': 'host', 'zone': 'zone'})
            expected_out += ("%(host)-25s\t%(availability_zone)-15s\n" %
                             {'host': 'fake-host',
                              'availability_zone': 'fake-az'})
            host_cmds = cinder_manage.HostCommands()
            host_cmds.list()

            get_admin_context.assert_called_once_with()
            service_get_all.assert_called_once_with(mock.sentinel.ctxt)
            self.assertEqual(expected_out, fake_out.getvalue())

    @mock.patch('cinder.db.service_get_all')
    @mock.patch('cinder.context.get_admin_context')
    def test_host_commands_list_with_zone(self, get_admin_context,
                                          service_get_all):
        get_admin_context.return_value = mock.sentinel.ctxt
        service_get_all.return_value = [
            {'host': 'fake-host',
             'availability_zone': 'fake-az1',
             'uuid': 'a3a593da-7f8d-4bb7-8b4c-f2bc1e0b4824'},
            {'host': 'fake-host',
             'availability_zone': 'fake-az2',
             'uuid': '4200b32b-0bf9-436c-86b2-0675f6ac218e'}]

        with mock.patch('sys.stdout', new=io.StringIO()) as fake_out:
            expected_out = ("%(host)-25s\t%(zone)-15s\n" %
                            {'host': 'host', 'zone': 'zone'})
            expected_out += ("%(host)-25s\t%(availability_zone)-15s\n" %
                             {'host': 'fake-host',
                              'availability_zone': 'fake-az1'})
            host_cmds = cinder_manage.HostCommands()
            host_cmds.list(zone='fake-az1')

            get_admin_context.assert_called_once_with()
            service_get_all.assert_called_once_with(mock.sentinel.ctxt)
            self.assertEqual(expected_out, fake_out.getvalue())

    @mock.patch('cinder.db.sqlalchemy.api.volume_get')
    @mock.patch('cinder.context.get_admin_context')
    @mock.patch('cinder.rpc.get_client')
    @mock.patch('cinder.rpc.init')
    def test_volume_commands_delete(self, rpc_init, get_client,
                                    get_admin_context, volume_get):
        ctxt = context.RequestContext('admin', 'fake', True)
        get_admin_context.return_value = ctxt
        mock_client = mock.MagicMock()
        cctxt = mock.MagicMock()
        mock_client.prepare.return_value = cctxt
        get_client.return_value = mock_client
        host = 'fake@host'
        db_volume = {'host': host + '#pool1'}
        volume = fake_volume.fake_db_volume(**db_volume)
        volume_obj = fake_volume.fake_volume_obj(ctxt, **volume)
        volume_id = volume['id']
        volume_get.return_value = volume

        volume_cmds = cinder_manage.VolumeCommands()
        volume_cmds._client = mock_client
        volume_cmds.delete(volume_id)

        volume_get.assert_called_once_with(ctxt, volume_id)
        mock_client.prepare.assert_called_once_with(
            server="fake",
            topic="cinder-volume.fake@host",
            version="3.0")

        cctxt.cast.assert_called_once_with(
            ctxt, 'delete_volume',
            cascade=False,
            unmanage_only=False,
            volume=volume_obj)

    @mock.patch('cinder.db.volume_destroy')
    @mock.patch('cinder.db.sqlalchemy.api.volume_get')
    @mock.patch('cinder.context.get_admin_context')
    @mock.patch('cinder.rpc.init')
    def test_volume_commands_delete_no_host(self, rpc_init, get_admin_context,
                                            volume_get, volume_destroy):
        ctxt = context.RequestContext(fake.USER_ID, fake.PROJECT_ID,
                                      is_admin=True)
        get_admin_context.return_value = ctxt
        volume = fake_volume.fake_db_volume()
        volume_id = volume['id']
        volume_get.return_value = volume

        with mock.patch('sys.stdout', new=io.StringIO()) as fake_out:
            expected_out = ('Volume not yet assigned to host.\n'
                            'Deleting volume from database and skipping'
                            ' rpc.\n')
            volume_cmds = cinder_manage.VolumeCommands()
            volume_cmds.delete(volume_id)

            get_admin_context.assert_called_once_with()
            volume_get.assert_called_once_with(ctxt, volume_id)
            self.assertTrue(volume_destroy.called)
            admin_context = volume_destroy.call_args[0][0]
            self.assertTrue(admin_context.is_admin)
            self.assertEqual(expected_out, fake_out.getvalue())

    @mock.patch('cinder.db.volume_destroy')
    @mock.patch('cinder.db.sqlalchemy.api.volume_get')
    @mock.patch('cinder.context.get_admin_context')
    @mock.patch('cinder.rpc.init')
    def test_volume_commands_delete_volume_in_use(self, rpc_init,
                                                  get_admin_context,
                                                  volume_get, volume_destroy):
        ctxt = context.RequestContext(fake.USER_ID, fake.PROJECT_ID)
        get_admin_context.return_value = ctxt
        db_volume = {'status': 'in-use', 'host': 'fake-host'}
        volume = fake_volume.fake_db_volume(**db_volume)
        volume_id = volume['id']
        volume_get.return_value = volume

        with mock.patch('sys.stdout', new=io.StringIO()) as fake_out:
            expected_out = ('Volume is in-use.\n'
                            'Detach volume from instance and then try'
                            ' again.\n')
            volume_cmds = cinder_manage.VolumeCommands()
            volume_cmds.delete(volume_id)

            volume_get.assert_called_once_with(ctxt, volume_id)
            self.assertEqual(expected_out, fake_out.getvalue())

    def test_config_commands_list(self):
        with mock.patch('sys.stdout', new=io.StringIO()) as fake_out:
            expected_out = ''
            for key, value in CONF.items():
                expected_out += '%s = %s' % (key, value) + '\n'

            config_cmds = cinder_manage.ConfigCommands()
            config_cmds.list()

            self.assertEqual(expected_out, fake_out.getvalue())

    def test_config_commands_list_param(self):
        with mock.patch('sys.stdout', new=io.StringIO()) as fake_out:
            CONF.set_override('host', 'fake')
            expected_out = 'host = fake\n'

            config_cmds = cinder_manage.ConfigCommands()
            config_cmds.list(param='host')

            self.assertEqual(expected_out, fake_out.getvalue())

    @mock.patch('cinder.db.backup_get_all')
    @mock.patch('cinder.context.get_admin_context')
    def test_backup_commands_list(self, get_admin_context, backup_get_all):
        ctxt = context.RequestContext(fake.USER_ID, fake.PROJECT_ID)
        get_admin_context.return_value = ctxt
        backup = {'id': fake.BACKUP_ID,
                  'user_id': fake.USER_ID,
                  'project_id': fake.PROJECT_ID,
                  'host': 'fake-host',
                  'display_name': 'fake-display-name',
                  'container': 'fake-container',
                  'status': fields.BackupStatus.AVAILABLE,
                  'size': 123,
                  'object_count': 1,
                  'volume_id': fake.VOLUME_ID,
                  'backup_metadata': {},
                  }
        backup_get_all.return_value = [backup]
        with mock.patch('sys.stdout', new=io.StringIO()) as fake_out:
            hdr = ('%-32s\t%-32s\t%-32s\t%-24s\t%-24s\t%-12s\t%-12s\t%-12s'
                   '\t%-12s')
            header = hdr % ('ID',
                            'User ID',
                            'Project ID',
                            'Host',
                            'Name',
                            'Container',
                            'Status',
                            'Size',
                            'Object Count')
            res = ('%-32s\t%-32s\t%-32s\t%-24s\t%-24s\t%-12s\t%-12s\t%-12d'
                   '\t%-12s')
            resource = res % (backup['id'],
                              backup['user_id'],
                              backup['project_id'],
                              backup['host'],
                              backup['display_name'],
                              backup['container'],
                              backup['status'],
                              backup['size'],
                              1)
            expected_out = header + '\n' + resource + '\n'

            backup_cmds = cinder_manage.BackupCommands()
            backup_cmds.list()

            get_admin_context.assert_called_once_with()
            backup_get_all.assert_called_once_with(ctxt, None, None, None,
                                                   None, None, None)
            self.assertEqual(expected_out, fake_out.getvalue())

    @mock.patch('cinder.db.backup_update')
    @mock.patch('cinder.db.backup_get_all_by_host')
    @mock.patch('cinder.context.get_admin_context')
    def test_update_backup_host(self, get_admin_context,
                                backup_get_by_host,
                                backup_update):
        ctxt = context.RequestContext(fake.USER_ID, fake.PROJECT_ID)
        get_admin_context.return_value = ctxt
        backup = {'id': fake.BACKUP_ID,
                  'user_id': fake.USER_ID,
                  'project_id': fake.PROJECT_ID,
                  'host': 'fake-host',
                  'display_name': 'fake-display-name',
                  'container': 'fake-container',
                  'status': fields.BackupStatus.AVAILABLE,
                  'size': 123,
                  'object_count': 1,
                  'volume_id': fake.VOLUME_ID,
                  'backup_metadata': {},
                  }
        backup_get_by_host.return_value = [backup]
        backup_cmds = cinder_manage.BackupCommands()
        backup_cmds.update_backup_host('fake_host', 'fake_host2')

        get_admin_context.assert_called_once_with()
        backup_get_by_host.assert_called_once_with(ctxt, 'fake_host')
        backup_update.assert_called_once_with(ctxt, fake.BACKUP_ID,
                                              {'host': 'fake_host2'})

    @mock.patch('cinder.db.consistencygroup_update')
    @mock.patch('cinder.db.consistencygroup_get_all')
    @mock.patch('cinder.context.get_admin_context')
    def test_update_consisgroup_host(self, get_admin_context,
                                     consisgroup_get_all,
                                     consisgroup_update):
        ctxt = context.RequestContext(fake.USER_ID, fake.PROJECT_ID)
        get_admin_context.return_value = ctxt
        consisgroup = {'id': fake.CONSISTENCY_GROUP_ID,
                       'user_id': fake.USER_ID,
                       'project_id': fake.PROJECT_ID,
                       'host': 'fake-host',
                       'status': fields.ConsistencyGroupStatus.AVAILABLE
                       }
        consisgroup_get_all.return_value = [consisgroup]
        consisgrup_cmds = cinder_manage.ConsistencyGroupCommands()
        consisgrup_cmds.update_cg_host('fake_host', 'fake_host2')

        get_admin_context.assert_called_once_with()
        consisgroup_get_all.assert_called_once_with(
            ctxt, filters={'host': 'fake_host'}, limit=None, marker=None,
            offset=None, sort_dirs=None, sort_keys=None)
        consisgroup_update.assert_called_once_with(
            ctxt, fake.CONSISTENCY_GROUP_ID, {'host': 'fake_host2'})

    @mock.patch('cinder.objects.service.Service.is_up',
                new_callable=mock.PropertyMock)
    @mock.patch('cinder.db.service_get_all')
    @mock.patch('cinder.context.get_admin_context')
    def _test_service_commands_list(self, service, get_admin_context,
                                    service_get_all, service_is_up):
        ctxt = context.RequestContext(fake.USER_ID, fake.PROJECT_ID)
        get_admin_context.return_value = ctxt
        service_get_all.return_value = [service]
        service_is_up.return_value = True
        with mock.patch('sys.stdout', new=io.StringIO()) as fake_out:
            format = "%-16s %-36s %-16s %-10s %-5s %-20s %-12s %-15s %-36s"
            print_format = format % ('Binary',
                                     'Host',
                                     'Zone',
                                     'Status',
                                     'State',
                                     'Updated At',
                                     'RPC Version',
                                     'Object Version',
                                     'Cluster')
            rpc_version = service['rpc_current_version']
            object_version = service['object_current_version']
            cluster = service.get('cluster_name', '')
            service_format = format % (service['binary'],
                                       service['host'],
                                       service['availability_zone'],
                                       'enabled',
                                       ':-)',
                                       service['updated_at'],
                                       rpc_version,
                                       object_version,
                                       cluster)
            expected_out = print_format + '\n' + service_format + '\n'

            service_cmds = cinder_manage.ServiceCommands()
            service_cmds.list()

            self.assertEqual(expected_out, fake_out.getvalue())
            get_admin_context.assert_called_with()
            service_get_all.assert_called_with(ctxt)

    def test_service_commands_list(self):
        service = {'binary': 'cinder-binary',
                   'host': 'fake-host.fake-domain',
                   'availability_zone': 'fake-zone',
                   'updated_at': '2014-06-30 11:22:33',
                   'disabled': False,
                   'rpc_current_version': '1.1',
                   'object_current_version': '1.1',
                   'cluster_name': 'my_cluster',
                   'uuid': 'a3a593da-7f8d-4bb7-8b4c-f2bc1e0b4824'}
        for binary in ('volume', 'scheduler', 'backup'):
            service['binary'] = 'cinder-%s' % binary
            self._test_service_commands_list(service)

    def test_service_commands_list_no_updated_at_or_cluster(self):
        service = {'binary': 'cinder-binary',
                   'host': 'fake-host.fake-domain',
                   'availability_zone': 'fake-zone',
                   'updated_at': None,
                   'disabled': False,
                   'rpc_current_version': '1.1',
                   'object_current_version': '1.1',
                   'uuid': 'a3a593da-7f8d-4bb7-8b4c-f2bc1e0b4824'}
        for binary in ('volume', 'scheduler', 'backup'):
            service['binary'] = 'cinder-%s' % binary
            self._test_service_commands_list(service)

    @ddt.data(('foobar', 'foobar'), ('-foo bar', 'foo bar'),
              ('--foo bar', 'foo bar'), ('--foo-bar', 'foo_bar'),
              ('---foo-bar', '_foo_bar'))
    @ddt.unpack
    def test_get_arg_string(self, arg, expected):
        self.assertEqual(expected, cinder_manage.get_arg_string(arg))

    def test_fetch_func_args(self):
        @cinder_manage.args('--full-rename')
        @cinder_manage.args('--different-dest', dest='my_dest')
        @cinder_manage.args('current')
        def my_func():
            pass

        expected = {'full_rename': mock.sentinel.full_rename,
                    'my_dest': mock.sentinel.my_dest,
                    'current': mock.sentinel.current}

        with mock.patch.object(cinder_manage, 'CONF') as mock_conf:
            mock_conf.category = mock.Mock(**expected)
            self.assertDictEqual(expected,
                                 cinder_manage.fetch_func_args(my_func))

    def test_args_decorator(self):
        @cinder_manage.args('host-name')
        @cinder_manage.args('cluster-name', metavar='cluster')
        @cinder_manage.args('--debug')
        def my_func():
            pass

        expected = [
            (['host_name'], {'metavar': 'host-name'}),
            (['cluster_name'], {'metavar': 'cluster'}),
            (['--debug'], {})]
        self.assertEqual(expected, my_func.args)

    @mock.patch('cinder.context.get_admin_context')
    @mock.patch('cinder.db.cluster_get_all')
    def tests_cluster_commands_list(self, get_all_mock, get_admin_mock,
                                    ):
        now = timeutils.utcnow()
        cluster = fake_cluster.fake_cluster_orm(num_hosts=4, num_down_hosts=2,
                                                created_at=now,
                                                last_heartbeat=now)
        get_all_mock.return_value = [cluster]

        ctxt = context.RequestContext(fake.USER_ID, fake.PROJECT_ID)
        get_admin_mock.return_value = ctxt

        with mock.patch('sys.stdout', new=io.StringIO()) as fake_out:
            format_ = "%-36s %-16s %-10s %-5s %-20s %-7s %-12s %-20s"
            print_format = format_ % ('Name',
                                      'Binary',
                                      'Status',
                                      'State',
                                      'Heartbeat',
                                      'Hosts',
                                      'Down Hosts',
                                      'Updated At')
            cluster_format = format_ % (cluster.name, cluster.binary,
                                        'enabled', ':-)',
                                        cluster.last_heartbeat,
                                        cluster.num_hosts,
                                        cluster.num_down_hosts,
                                        None)
            expected_out = print_format + '\n' + cluster_format + '\n'

            cluster_cmds = cinder_manage.ClusterCommands()
            cluster_cmds.list()

            self.assertEqual(expected_out, fake_out.getvalue())
            get_admin_mock.assert_called_with()
            get_all_mock.assert_called_with(ctxt, is_up=None,
                                            get_services=False,
                                            services_summary=True,
                                            read_deleted='no')

    @mock.patch('cinder.db.sqlalchemy.api.cluster_get', auto_specs=True)
    @mock.patch('cinder.context.get_admin_context')
    def test_cluster_commands_remove_not_found(self, admin_ctxt_mock,
                                               cluster_get_mock):
        cluster_get_mock.side_effect = exception.ClusterNotFound(id=1)
        cluster_commands = cinder_manage.ClusterCommands()
        exit = cluster_commands.remove(False, 'abinary', 'acluster')
        self.assertEqual(2, exit)
        cluster_get_mock.assert_called_once_with(admin_ctxt_mock.return_value,
                                                 None, name='acluster',
                                                 binary='abinary',
                                                 get_services=False)

    @mock.patch('cinder.db.sqlalchemy.api.service_destroy', auto_specs=True)
    @mock.patch('cinder.db.sqlalchemy.api.cluster_destroy', auto_specs=True)
    @mock.patch('cinder.db.sqlalchemy.api.cluster_get', auto_specs=True)
    @mock.patch('cinder.context.get_admin_context')
    def test_cluster_commands_remove_fail_has_hosts(self, admin_ctxt_mock,
                                                    cluster_get_mock,
                                                    cluster_destroy_mock,
                                                    service_destroy_mock):
        cluster = fake_cluster.fake_cluster_ovo(mock.Mock())
        cluster_get_mock.return_value = cluster
        cluster_destroy_mock.side_effect = exception.ClusterHasHosts(id=1)
        cluster_commands = cinder_manage.ClusterCommands()
        exit = cluster_commands.remove(False, 'abinary', 'acluster')
        self.assertEqual(2, exit)
        cluster_get_mock.assert_called_once_with(admin_ctxt_mock.return_value,
                                                 None, name='acluster',
                                                 binary='abinary',
                                                 get_services=False)
        cluster_destroy_mock.assert_called_once_with(
            admin_ctxt_mock.return_value.elevated.return_value, cluster.id)
        service_destroy_mock.assert_not_called()

    @mock.patch('cinder.db.sqlalchemy.api.service_destroy', auto_specs=True)
    @mock.patch('cinder.db.sqlalchemy.api.cluster_destroy', auto_specs=True)
    @mock.patch('cinder.db.sqlalchemy.api.cluster_get', auto_specs=True)
    @mock.patch('cinder.context.get_admin_context')
    def test_cluster_commands_remove_success_no_hosts(self, admin_ctxt_mock,
                                                      cluster_get_mock,
                                                      cluster_destroy_mock,
                                                      service_destroy_mock):
        cluster = fake_cluster.fake_cluster_orm()
        cluster_get_mock.return_value = cluster
        cluster_commands = cinder_manage.ClusterCommands()
        exit = cluster_commands.remove(False, 'abinary', 'acluster')
        self.assertIsNone(exit)
        cluster_get_mock.assert_called_once_with(admin_ctxt_mock.return_value,
                                                 None, name='acluster',
                                                 binary='abinary',
                                                 get_services=False)
        cluster_destroy_mock.assert_called_once_with(
            admin_ctxt_mock.return_value.elevated.return_value, cluster.id)
        service_destroy_mock.assert_not_called()

    @mock.patch('cinder.db.sqlalchemy.api.service_destroy', auto_specs=True)
    @mock.patch('cinder.db.sqlalchemy.api.cluster_destroy', auto_specs=True)
    @mock.patch('cinder.db.sqlalchemy.api.cluster_get', auto_specs=True)
    @mock.patch('cinder.context.get_admin_context')
    def test_cluster_commands_remove_recursive(self, admin_ctxt_mock,
                                               cluster_get_mock,
                                               cluster_destroy_mock,
                                               service_destroy_mock):
        cluster = fake_cluster.fake_cluster_orm()
        cluster.services = [fake_service.fake_service_orm()]
        cluster_get_mock.return_value = cluster
        cluster_commands = cinder_manage.ClusterCommands()
        exit = cluster_commands.remove(True, 'abinary', 'acluster')
        self.assertIsNone(exit)
        cluster_get_mock.assert_called_once_with(admin_ctxt_mock.return_value,
                                                 None, name='acluster',
                                                 binary='abinary',
                                                 get_services=True)
        cluster_destroy_mock.assert_called_once_with(
            admin_ctxt_mock.return_value.elevated.return_value, cluster.id)
        service_destroy_mock.assert_called_once_with(
            admin_ctxt_mock.return_value.elevated.return_value,
            cluster.services[0]['id'])

    @mock.patch('cinder.db.sqlalchemy.api.volume_include_in_cluster',
                auto_specs=True, return_value=1)
    @mock.patch('cinder.db.sqlalchemy.api.consistencygroup_include_in_cluster',
                auto_specs=True, return_value=2)
    @mock.patch('cinder.context.get_admin_context')
    def test_cluster_commands_rename(self, admin_ctxt_mock,
                                     volume_include_mock, cg_include_mock):
        """Test that cluster rename changes volumes and cgs."""
        current_cluster_name = mock.sentinel.old_cluster_name
        new_cluster_name = mock.sentinel.new_cluster_name
        partial = mock.sentinel.partial
        cluster_commands = cinder_manage.ClusterCommands()
        exit = cluster_commands.rename(partial, current_cluster_name,
                                       new_cluster_name)

        self.assertIsNone(exit)
        volume_include_mock.assert_called_once_with(
            admin_ctxt_mock.return_value, new_cluster_name, partial,
            cluster_name=current_cluster_name)
        cg_include_mock.assert_called_once_with(
            admin_ctxt_mock.return_value, new_cluster_name, partial,
            cluster_name=current_cluster_name)

    @mock.patch('cinder.db.sqlalchemy.api.volume_include_in_cluster',
                auto_specs=True, return_value=0)
    @mock.patch('cinder.db.sqlalchemy.api.consistencygroup_include_in_cluster',
                auto_specs=True, return_value=0)
    @mock.patch('cinder.context.get_admin_context')
    def test_cluster_commands_rename_no_changes(self, admin_ctxt_mock,
                                                volume_include_mock,
                                                cg_include_mock):
        """Test that we return an error when cluster rename has no effect."""
        cluster_commands = cinder_manage.ClusterCommands()
        exit = cluster_commands.rename(False, 'cluster', 'new_cluster')
        self.assertEqual(2, exit)

    @mock.patch('cinder.objects.Cluster.get_by_id')
    @mock.patch('cinder.context.get_admin_context')
    def test_main_remove_cluster(self, get_admin_mock, get_cluster_mock):
        script_name = 'cinder-manage'
        sys.argv = [script_name, 'cluster', 'remove', 'abinary', 'acluster']

        cinder_manage.CONF = cfg.ConfigOpts()
        cinder_manage.main()

        expected_argument = (['cluster_name'],
                             {'type': str,
                              'help': 'Cluster to delete.',
                              'metavar': 'cluster-name'})
        self.assertIn(expected_argument,
                      cinder_manage.CONF.category.action_fn.args)
        self.assertTrue(hasattr(cinder_manage.CONF.category, 'cluster_name'))
        get_admin_mock.assert_called_with()
        get_cluster_mock.assert_called_with(get_admin_mock.return_value,
                                            None, name='acluster',
                                            binary='abinary',
                                            get_services=False)
        cluster = get_cluster_mock.return_value
        cluster.destroy.assert_called()

    @mock.patch('oslo_config.cfg.ConfigOpts.register_cli_opt')
    def test_main_argv_lt_2(self, register_cli_opt):
        script_name = 'cinder-manage'
        sys.argv = [script_name]
        CONF(sys.argv[1:], project='cinder', version=version.version_string())

        with mock.patch('sys.stdout', new=io.StringIO()):
            exit = self.assertRaises(SystemExit, cinder_manage.main)
            self.assertTrue(register_cli_opt.called)
            self.assertEqual(2, exit.code)

    def test_main_missing_action(self):
        sys.argv = ['cinder-manage', 'backup']
        cinder_manage.CONF = cfg.ConfigOpts()

        stdout = io.StringIO()
        with mock.patch('sys.stdout', new=stdout):
            exit = self.assertRaises(SystemExit, cinder_manage.main)
            self.assertEqual(2, exit.code)

        stdout.seek(0)
        output = stdout.read()
        self.assertTrue(output.startswith('usage: '))

    @mock.patch('oslo_config.cfg.ConfigOpts.__call__')
    @mock.patch('oslo_log.log.setup')
    @mock.patch('oslo_config.cfg.ConfigOpts.register_cli_opt')
    def test_main_sudo_failed(self, register_cli_opt, log_setup,
                              config_opts_call):
        script_name = 'cinder-manage'
        sys.argv = [script_name, 'fake_category', 'fake_action']
        config_opts_call.side_effect = cfg.ConfigFilesNotFoundError(
            mock.sentinel._namespace)

        with mock.patch('sys.stdout', new=io.StringIO()):
            exit = self.assertRaises(SystemExit, cinder_manage.main)

            self.assertTrue(register_cli_opt.called)
            config_opts_call.assert_called_once_with(
                sys.argv[1:], project='cinder',
                version=version.version_string())
            self.assertFalse(log_setup.called)
            self.assertEqual(2, exit.code)

    @mock.patch('oslo_config.cfg.ConfigOpts.__call__')
    @mock.patch('oslo_config.cfg.ConfigOpts.register_cli_opt')
    def test_main(self, register_cli_opt, config_opts_call):
        script_name = 'cinder-manage'
        sys.argv = [script_name, 'config', 'list']
        action_fn = mock.MagicMock()
        CONF.category = mock.MagicMock(action_fn=action_fn)

        cinder_manage.main()

        self.assertTrue(register_cli_opt.called)
        config_opts_call.assert_called_once_with(
            sys.argv[1:], project='cinder', version=version.version_string())
        self.assertTrue(action_fn.called)

    @mock.patch('oslo_config.cfg.ConfigOpts.__call__')
    @mock.patch('oslo_log.log.setup')
    @mock.patch('oslo_config.cfg.ConfigOpts.register_cli_opt')
    def test_main_invalid_dir(self, register_cli_opt, log_setup,
                              config_opts_call):
        script_name = 'cinder-manage'
        fake_dir = 'fake-dir'
        invalid_dir = 'Invalid directory:'
        sys.argv = [script_name, '--config-dir', fake_dir]
        config_opts_call.side_effect = cfg.ConfigDirNotFoundError(fake_dir)

        with mock.patch('sys.stdout', new=io.StringIO()) as fake_out:
            exit = self.assertRaises(SystemExit, cinder_manage.main)
            self.assertTrue(register_cli_opt.called)
            config_opts_call.assert_called_once_with(
                sys.argv[1:], project='cinder',
                version=version.version_string())
            self.assertIn(invalid_dir, fake_out.getvalue())
            self.assertIn(fake_dir, fake_out.getvalue())
            self.assertFalse(log_setup.called)
            self.assertEqual(2, exit.code)

    @mock.patch('cinder.db')
    def test_remove_service_failure(self, mock_db):
        mock_db.service_destroy.side_effect = SystemExit(1)
        service_commands = cinder_manage.ServiceCommands()
        exit = service_commands.remove('abinary', 'ahost')
        self.assertEqual(2, exit)

    @mock.patch('cinder.db.service_destroy')
    @mock.patch(
        'cinder.db.service_get',
        return_value = {'id': '12',
                        'uuid': 'a3a593da-7f8d-4bb7-8b4c-f2bc1e0b4824'})
    def test_remove_service_success(self, mock_get_by_args,
                                    mock_service_destroy):
        service_commands = cinder_manage.ServiceCommands()
        self.assertIsNone(service_commands.remove('abinary', 'ahost'))

    @mock.patch('glob.glob')
    def test_util__get_resources_locks(self, mock_glob):
        cinder_manage.cfg.CONF.set_override('lock_path', '/locks',
                                            group='oslo_concurrency')
        cinder_manage.cfg.CONF.set_override('backend_url', 'file:///dlm',
                                            group='coordination')

        vol1 = fake.VOLUME_ID
        vol2 = fake.VOLUME2_ID
        snap = fake.SNAPSHOT_ID
        attach = fake.ATTACHMENT_ID

        files = [
            'cinder-something',  # Non UUID files are ignored
            f'/locks/cinder-{vol1}-delete_volume',
            f'/locks/cinder-{vol2}-delete_volume',
            f'/locks/cinder-{vol2}',
            f'/locks/cinder-{vol2}-detach_volume',
            f'/locks/cinder-{snap}-delete_snapshot',
            '/locks/cinder-cleanup_incomplete_backups_12345',
            '/locks/cinder-unrelated-backup-named-file',
        ]
        dlm_locks = [
            f'/dlm/cinder-attachment_update-{vol2}-{attach}',
        ]
        mock_glob.side_effect = [files, dlm_locks]

        commands = cinder_manage.UtilCommands()
        res = commands._get_resources_locks()

        self.assertEqual(2, mock_glob.call_count)
        mock_glob.assert_has_calls([
            mock.call('/locks/cinder-*'),
            mock.call('/dlm/cinder-*')
        ])

        expected_vols = {
            vol1: [f'/locks/cinder-{vol1}-delete_volume'],
            vol2: [f'/locks/cinder-{vol2}-delete_volume',
                   f'/locks/cinder-{vol2}',
                   f'/locks/cinder-{vol2}-detach_volume',
                   f'/dlm/cinder-attachment_update-{vol2}-{attach}'],
        }
        expected_snaps = {
            snap: [f'/locks/cinder-{snap}-delete_snapshot']
        }
        expected_backups = {
            '12345': ['/locks/cinder-cleanup_incomplete_backups_12345']
        }
        expected = (expected_vols, expected_snaps, expected_backups)
        self.assertEqual(expected, res)

    @mock.patch.object(cinder_manage, 'open')
    def test__exclude_running_backups(self, mock_open):
        mock_running = mock.mock_open(read_data='cinder-backup --config-file '
                                      '/etc/cinder/cinder.conf')
        file_running = mock_running.return_value.__enter__.return_value
        mock_other = mock.mock_open(read_data='python')
        file_other = mock_other.return_value.__enter__.return_value

        mock_open.side_effect = (FileNotFoundError, mock_running.return_value,
                                 mock_other.return_value,
                                 ValueError)

        backups = {'12341': '/locks/cinder-cleanup_incomplete_backups_12341',
                   '12342': '/locks/cinder-cleanup_incomplete_backups_12342',
                   '12343': '/locks/cinder-cleanup_incomplete_backups_12343',
                   '12344': '/locks/cinder-cleanup_incomplete_backups_12344'}

        expected = {'12341': '/locks/cinder-cleanup_incomplete_backups_12341',
                    '12343': '/locks/cinder-cleanup_incomplete_backups_12343'}

        commands = cinder_manage.UtilCommands()
        res = commands._exclude_running_backups(backups)

        self.assertIsNone(res)
        self.assertEqual(expected, backups)

        self.assertEqual(4, mock_open.call_count)
        mock_open.assert_has_calls([mock.call('/proc/12341/cmdline', 'r'),
                                    mock.call('/proc/12342/cmdline', 'r'),
                                    mock.call('/proc/12343/cmdline', 'r'),
                                    mock.call('/proc/12344/cmdline', 'r')])
        file_running.read.assert_called_once_with()
        file_other.read.assert_called_once_with()

    @ddt.data(True, False)
    @mock.patch.object(cinder_manage, 'print')
    @mock.patch.object(cinder_manage.os, 'remove')
    @mock.patch.object(cinder_manage.UtilCommands, '_exclude_running_backups')
    @mock.patch('cinder.objects.Snapshot.exists')
    @mock.patch('cinder.objects.Volume.exists')
    @mock.patch.object(cinder_manage.UtilCommands, '_get_resources_locks')
    @mock.patch.object(cinder_manage.context, 'get_admin_context')
    def test_clean_locks(self, online, mock_ctxt, mock_get_locks,
                         mock_vol_exists, mock_snap_exists, mock_exclude_backs,
                         mock_remove, mock_print):
        vol1_files = [f'/locks/cinder-{fake.VOLUME_ID}-delete_volume']
        vol2_files = [f'/locks/cinder-{fake.VOLUME2_ID}-delete_volume',
                      f'/locks/cinder-{fake.VOLUME2_ID}',
                      f'/locks/cinder-{fake.VOLUME2_ID}-detach_volume',
                      f'/dlm/cinder-attachment_update-{fake.VOLUME2_ID}-'
                      f'{fake.ATTACHMENT_ID}']
        vols = collections.OrderedDict(((fake.VOLUME_ID, vol1_files),
                                        (fake.VOLUME2_ID, vol2_files)))
        snap_files = [f'/locks/cinder-{fake.SNAPSHOT_ID}-delete_snapshot']
        snaps = {fake.SNAPSHOT_ID: snap_files}
        back_files = ['/locks/cinder-cleanup_incomplete_backups_12345']
        backs = {'12345': back_files}
        mock_get_locks.return_value = (vols, snaps, backs)
        mock_vol_exists.side_effect = (True, False)
        mock_snap_exists.return_value = False
        mock_remove.side_effect = [None, errno.ENOENT, None, None,
                                   errno.ENOENT, ValueError, None]

        commands = cinder_manage.UtilCommands()
        commands.clean_locks(online=online)

        mock_ctxt.assert_called_once_with()
        mock_get_locks.assert_called_once_with()
        expected_calls = ([mock.call(v) for v in vol1_files] +
                          [mock.call(v) for v in vol2_files] +
                          [mock.call(s) for s in snap_files] +
                          [mock.call(b) for b in back_files])
        if online:
            self.assertEqual(2, mock_vol_exists.call_count)
            mock_vol_exists.assert_has_calls(
                (mock.call(mock_ctxt.return_value, fake.VOLUME_ID),
                 mock.call(mock_ctxt.return_value, fake.VOLUME2_ID)))
            mock_snap_exists.assert_called_once_with(mock_ctxt.return_value,
                                                     fake.SNAPSHOT_ID)
            mock_exclude_backs.assert_called_once_with(backs)
            # If services are online we'll check resources that still exist
            # and then we won't delete those that do. In this case the files
            # for the first volume.
            del expected_calls[0]
        else:
            mock_vol_exists.assert_not_called()
            mock_snap_exists.assert_not_called()
            mock_exclude_backs.assert_not_called()

        self.assertEqual(len(expected_calls), mock_remove.call_count)
        mock_remove.assert_has_calls(expected_calls)

        # Only the ValueError exception should be logged
        self.assertEqual(1, mock_print.call_count)


@test.testtools.skipIf(sys.platform == 'darwin', 'Not supported on macOS')
class TestCinderRtstoolCmd(test.TestCase):

    def setUp(self):
        super(TestCinderRtstoolCmd, self).setUp()
        sys.argv = ['cinder-rtstool']

        self.INITIATOR_IQN = 'iqn.2015.12.com.example.openstack.i:UNIT1'
        self.TARGET_IQN = 'iqn.2015.12.com.example.openstack.i:TARGET1'

    @mock.patch.object(rtslib_fb.root, 'RTSRoot')
    def test_create_rtslib_error(self, rtsroot):
        rtsroot.side_effect = rtslib_fb.utils.RTSLibError()

        with mock.patch('sys.stdout', new=io.StringIO()):
            self.assertRaises(rtslib_fb.utils.RTSLibError,
                              cinder_rtstool.create,
                              mock.sentinel.backing_device,
                              mock.sentinel.name,
                              mock.sentinel.userid,
                              mock.sentinel.password,
                              mock.sentinel.iser_enabled)

    def _test_create_rtslib_error_network_portal(self, ip):
        with mock.patch.object(rtslib_fb, 'NetworkPortal') as network_portal, \
                mock.patch.object(rtslib_fb, 'LUN') as lun, \
                mock.patch.object(rtslib_fb, 'TPG') as tpg, \
                mock.patch.object(rtslib_fb, 'FabricModule') as fabric_mod, \
                mock.patch.object(rtslib_fb, 'Target') as target, \
                mock.patch.object(rtslib_fb, 'BlockStorageObject') as \
                block_storage_object, \
                mock.patch.object(rtslib_fb.root, 'RTSRoot') as rts_root:
            root_new = mock.MagicMock(storage_objects=mock.MagicMock())
            rts_root.return_value = root_new
            block_storage_object.return_value = mock.sentinel.so_new
            target.return_value = mock.sentinel.target_new
            fabric_mod.return_value = mock.sentinel.fabric_new
            tpg_new = tpg.return_value
            lun.return_value = mock.sentinel.lun_new

            if ip == '0.0.0.0':
                network_portal.side_effect = rtslib_fb.utils.RTSLibError()
                self.assertRaises(rtslib_fb.utils.RTSLibError,
                                  cinder_rtstool.create,
                                  mock.sentinel.backing_device,
                                  mock.sentinel.name,
                                  mock.sentinel.userid,
                                  mock.sentinel.password,
                                  mock.sentinel.iser_enabled)
            else:
                cinder_rtstool.create(mock.sentinel.backing_device,
                                      mock.sentinel.name,
                                      mock.sentinel.userid,
                                      mock.sentinel.password,
                                      mock.sentinel.iser_enabled)

            rts_root.assert_called_once_with()
            block_storage_object.assert_called_once_with(
                name=mock.sentinel.name, dev=mock.sentinel.backing_device)
            target.assert_called_once_with(mock.sentinel.fabric_new,
                                           mock.sentinel.name, 'create')
            fabric_mod.assert_called_once_with('iscsi')
            tpg.assert_called_once_with(mock.sentinel.target_new,
                                        mode='create')
            tpg_new.set_attribute.assert_called_once_with('authentication',
                                                          '1')
            lun.assert_called_once_with(tpg_new,
                                        storage_object=mock.sentinel.so_new)
            self.assertEqual(1, tpg_new.enable)

            if ip == '::0':
                ip = '[::0]'

            network_portal.assert_any_call(tpg_new, ip, 3260, mode='any')

    def test_create_rtslib_error_network_portal_ipv4(self):
        with mock.patch('sys.stdout', new=io.StringIO()):
            self._test_create_rtslib_error_network_portal('0.0.0.0')

    def test_create_rtslib_error_network_portal_ipv6(self):
        with mock.patch('sys.stdout', new=io.StringIO()):
            self._test_create_rtslib_error_network_portal('::0')

    def _test_create(self, ip):
        with mock.patch.object(rtslib_fb, 'NetworkPortal') as network_portal, \
                mock.patch.object(rtslib_fb, 'LUN') as lun, \
                mock.patch.object(rtslib_fb, 'TPG') as tpg, \
                mock.patch.object(rtslib_fb, 'FabricModule') as fabric_mod, \
                mock.patch.object(rtslib_fb, 'Target') as target, \
                mock.patch.object(rtslib_fb, 'BlockStorageObject') as \
                block_storage_object, \
                mock.patch.object(rtslib_fb.root, 'RTSRoot') as rts_root:
            root_new = mock.MagicMock(storage_objects=mock.MagicMock())
            rts_root.return_value = root_new
            block_storage_object.return_value = mock.sentinel.so_new
            target.return_value = mock.sentinel.target_new
            fabric_mod.return_value = mock.sentinel.fabric_new
            tpg_new = tpg.return_value
            lun.return_value = mock.sentinel.lun_new

            cinder_rtstool.create(mock.sentinel.backing_device,
                                  mock.sentinel.name,
                                  mock.sentinel.userid,
                                  mock.sentinel.password,
                                  mock.sentinel.iser_enabled)

            rts_root.assert_called_once_with()
            block_storage_object.assert_called_once_with(
                name=mock.sentinel.name, dev=mock.sentinel.backing_device)
            target.assert_called_once_with(mock.sentinel.fabric_new,
                                           mock.sentinel.name, 'create')
            fabric_mod.assert_called_once_with('iscsi')
            tpg.assert_called_once_with(mock.sentinel.target_new,
                                        mode='create')
            tpg_new.set_attribute.assert_called_once_with('authentication',
                                                          '1')
            lun.assert_called_once_with(tpg_new,
                                        storage_object=mock.sentinel.so_new)
            self.assertEqual(1, tpg_new.enable)

            if ip == '::0':
                ip = '[::0]'

            network_portal.assert_any_call(tpg_new, ip, 3260, mode='any')

    def test_create_ipv4(self):
        self._test_create('0.0.0.0')

    def test_create_ipv6(self):
        self._test_create('::0')

    def _test_create_ips_and_port(self, mock_rtslib, port, ips, expected_ips):
        mock_rtslib.BlockStorageObject.return_value = mock.sentinel.bso
        mock_rtslib.Target.return_value = mock.sentinel.target_new
        mock_rtslib.FabricModule.return_value = mock.sentinel.iscsi_fabric
        tpg_new = mock_rtslib.TPG.return_value

        cinder_rtstool.create(mock.sentinel.backing_device,
                              mock.sentinel.name,
                              mock.sentinel.userid,
                              mock.sentinel.password,
                              mock.sentinel.iser_enabled,
                              portals_ips=ips,
                              portals_port=port)

        mock_rtslib.Target.assert_called_once_with(mock.sentinel.iscsi_fabric,
                                                   mock.sentinel.name,
                                                   'create')
        mock_rtslib.TPG.assert_called_once_with(mock.sentinel.target_new,
                                                mode='create')
        mock_rtslib.LUN.assert_called_once_with(
            tpg_new,
            storage_object=mock.sentinel.bso)

        mock_rtslib.NetworkPortal.assert_has_calls(
            map(lambda ip: mock.call(tpg_new, ip, port, mode='any'),
                expected_ips), any_order=True
        )

    @mock.patch.object(cinder_rtstool, 'rtslib_fb', autospec=True)
    def test_create_ips_and_port_ipv4(self, mock_rtslib):
        ips = ['10.0.0.2', '10.0.0.3', '10.0.0.4']
        port = 3261
        self._test_create_ips_and_port(mock_rtslib, port, ips, ips)

    @mock.patch.object(cinder_rtstool, 'rtslib_fb', autospec=True)
    def test_create_ips_and_port_ipv6(self, mock_rtslib):
        ips = ['fe80::fc16:3eff:fecb:ad2f']
        expected_ips = ['[fe80::fc16:3eff:fecb:ad2f]']
        port = 3261
        self._test_create_ips_and_port(mock_rtslib, port, ips,
                                       expected_ips)

    @mock.patch.object(rtslib_fb.root, 'RTSRoot')
    def test_add_initiator_rtslib_error(self, rtsroot):
        rtsroot.side_effect = rtslib_fb.utils.RTSLibError()

        with mock.patch('sys.stdout', new=io.StringIO()):
            self.assertRaises(rtslib_fb.utils.RTSLibError,
                              cinder_rtstool.add_initiator,
                              mock.sentinel.target_iqn,
                              self.INITIATOR_IQN,
                              mock.sentinel.userid,
                              mock.sentinel.password)

    @mock.patch.object(rtslib_fb.root, 'RTSRoot')
    def test_add_initiator_rtstool_error(self, rtsroot):
        rtsroot.targets.return_value = {}

        self.assertRaises(cinder_rtstool.RtstoolError,
                          cinder_rtstool.add_initiator,
                          mock.sentinel.target_iqn,
                          self.INITIATOR_IQN,
                          mock.sentinel.userid,
                          mock.sentinel.password)

    @mock.patch.object(rtslib_fb, 'MappedLUN')
    @mock.patch.object(rtslib_fb, 'NodeACL')
    @mock.patch.object(rtslib_fb.root, 'RTSRoot')
    def test_add_initiator_acl_exists(self, rtsroot, node_acl, mapped_lun):
        target_iqn = mock.MagicMock()
        target_iqn.tpgs.return_value = \
            [{'node_acls': self.INITIATOR_IQN}]
        acl = mock.MagicMock(node_wwn=self.INITIATOR_IQN)
        tpg = mock.MagicMock(node_acls=[acl])
        tpgs = iter([tpg])
        target = mock.MagicMock(tpgs=tpgs, wwn=self.TARGET_IQN)
        rtsroot.return_value = mock.MagicMock(targets=[target])

        cinder_rtstool.add_initiator(self.TARGET_IQN,
                                     self.INITIATOR_IQN,
                                     mock.sentinel.userid,
                                     mock.sentinel.password)
        self.assertFalse(node_acl.called)
        self.assertFalse(mapped_lun.called)

    @mock.patch.object(rtslib_fb, 'MappedLUN')
    @mock.patch.object(rtslib_fb, 'NodeACL')
    @mock.patch.object(rtslib_fb.root, 'RTSRoot')
    def test_add_initiator_acl_exists_case_1(self,
                                             rtsroot,
                                             node_acl,
                                             mapped_lun):
        """Ensure initiator iqns are handled in a case-insensitive manner."""
        target_iqn = mock.MagicMock()
        target_iqn.tpgs.return_value = \
            [{'node_acls': self.INITIATOR_IQN.lower()}]
        acl = mock.MagicMock(node_wwn=self.INITIATOR_IQN)
        tpg = mock.MagicMock(node_acls=[acl])
        tpgs = iter([tpg])
        target = mock.MagicMock(tpgs=tpgs, wwn=target_iqn)
        rtsroot.return_value = mock.MagicMock(targets=[target])

        cinder_rtstool.add_initiator(target_iqn,
                                     self.INITIATOR_IQN,
                                     mock.sentinel.userid,
                                     mock.sentinel.password)
        self.assertFalse(node_acl.called)
        self.assertFalse(mapped_lun.called)

    @mock.patch.object(rtslib_fb, 'MappedLUN')
    @mock.patch.object(rtslib_fb, 'NodeACL')
    @mock.patch.object(rtslib_fb.root, 'RTSRoot')
    def test_add_initiator_acl_exists_case_2(self,
                                             rtsroot,
                                             node_acl,
                                             mapped_lun):
        """Ensure initiator iqns are handled in a case-insensitive manner."""
        iqn_lower = self.INITIATOR_IQN.lower()
        target_iqn = mock.MagicMock()
        target_iqn.tpgs.return_value = \
            [{'node_acls': self.INITIATOR_IQN}]
        acl = mock.MagicMock(node_wwn=iqn_lower)
        tpg = mock.MagicMock(node_acls=[acl])
        tpgs = iter([tpg])
        target = mock.MagicMock(tpgs=tpgs, wwn=target_iqn)
        rtsroot.return_value = mock.MagicMock(targets=[target])

        cinder_rtstool.add_initiator(target_iqn,
                                     self.INITIATOR_IQN,
                                     mock.sentinel.userid,
                                     mock.sentinel.password)
        self.assertFalse(node_acl.called)
        self.assertFalse(mapped_lun.called)

    @mock.patch.object(rtslib_fb, 'MappedLUN')
    @mock.patch.object(rtslib_fb, 'NodeACL')
    @mock.patch.object(rtslib_fb.root, 'RTSRoot')
    def test_add_initiator(self, rtsroot, node_acl, mapped_lun):
        target_iqn = mock.MagicMock()
        target_iqn.tpgs.return_value = \
            [{'node_acls': self.INITIATOR_IQN}]
        tpg = mock.MagicMock()
        tpgs = iter([tpg])
        target = mock.MagicMock(tpgs=tpgs, wwn=target_iqn)
        rtsroot.return_value = mock.MagicMock(targets=[target])

        acl_new = mock.MagicMock(chap_userid=mock.sentinel.userid,
                                 chap_password=mock.sentinel.password)
        node_acl.return_value = acl_new

        cinder_rtstool.add_initiator(target_iqn,
                                     self.INITIATOR_IQN,
                                     mock.sentinel.userid,
                                     mock.sentinel.password)
        node_acl.assert_called_once_with(tpg,
                                         self.INITIATOR_IQN,
                                         mode='create')
        mapped_lun.assert_called_once_with(acl_new, 0, tpg_lun=0)

    @mock.patch.object(rtslib_fb.root, 'RTSRoot')
    def test_get_targets(self, rtsroot):
        target = mock.MagicMock()
        target.dump.return_value = {'wwn': 'fake-wwn'}
        rtsroot.return_value = mock.MagicMock(targets=[target])

        with mock.patch('sys.stdout', new=io.StringIO()) as fake_out:
            cinder_rtstool.get_targets()

            self.assertEqual(str(target.wwn), fake_out.getvalue().strip())

    @mock.patch.object(rtslib_fb.root, 'RTSRoot')
    def test_delete(self, rtsroot):
        target = mock.MagicMock(wwn=mock.sentinel.iqn)
        storage_object = mock.MagicMock()
        name = mock.PropertyMock(return_value=mock.sentinel.iqn)
        type(storage_object).name = name
        rtsroot.return_value = mock.MagicMock(
            targets=[target], storage_objects=[storage_object])

        cinder_rtstool.delete(mock.sentinel.iqn)

        target.delete.assert_called_once_with()
        storage_object.delete.assert_called_once_with()

    @mock.patch.object(rtslib_fb, 'MappedLUN')
    @mock.patch.object(rtslib_fb, 'NodeACL')
    @mock.patch.object(rtslib_fb.root, 'RTSRoot')
    def test_delete_initiator(self, rtsroot, node_acl, mapped_lun):
        target_iqn = mock.MagicMock()
        target_iqn.tpgs.return_value = \
            [{'node_acls': self.INITIATOR_IQN}]
        acl = mock.MagicMock(node_wwn=self.INITIATOR_IQN)
        tpg = mock.MagicMock(node_acls=[acl])
        tpgs = iter([tpg])
        target = mock.MagicMock(tpgs=tpgs, wwn=target_iqn)
        rtsroot.return_value = mock.MagicMock(targets=[target])

        cinder_rtstool.delete_initiator(target_iqn,
                                        self.INITIATOR_IQN)

    @mock.patch.object(rtslib_fb, 'MappedLUN')
    @mock.patch.object(rtslib_fb, 'NodeACL')
    @mock.patch.object(rtslib_fb.root, 'RTSRoot')
    def test_delete_initiator_case(self, rtsroot, node_acl, mapped_lun):
        """Ensure iqns are handled in a case-insensitive manner."""
        initiator_iqn_lower = self.INITIATOR_IQN.lower()
        target_iqn = mock.MagicMock()
        target_iqn.tpgs.return_value = \
            [{'node_acls': initiator_iqn_lower}]
        acl = mock.MagicMock(node_wwn=self.INITIATOR_IQN)
        tpg = mock.MagicMock(node_acls=[acl])
        tpgs = iter([tpg])
        target = mock.MagicMock(tpgs=tpgs, wwn=target_iqn)
        rtsroot.return_value = mock.MagicMock(targets=[target])

        cinder_rtstool.delete_initiator(target_iqn,
                                        self.INITIATOR_IQN)

    @mock.patch.object(cinder_rtstool, 'os', autospec=True)
    @mock.patch.object(cinder_rtstool, 'rtslib_fb', autospec=True)
    def test_save_with_filename(self, mock_rtslib, mock_os):
        filename = mock.sentinel.filename
        cinder_rtstool.save_to_file(filename)
        rtsroot = mock_rtslib.root.RTSRoot
        rtsroot.assert_called_once_with()
        self.assertEqual(0, mock_os.path.dirname.call_count)
        self.assertEqual(0, mock_os.path.exists.call_count)
        self.assertEqual(0, mock_os.makedirs.call_count)
        rtsroot.return_value.save_to_file.assert_called_once_with(filename)

    @mock.patch.object(cinder_rtstool, 'os',
                       **{'path.exists.return_value': True,
                          'path.dirname.return_value': mock.sentinel.dirname})
    @mock.patch.object(cinder_rtstool, 'rtslib_fb',
                       **{'root.default_save_file': mock.sentinel.filename})
    def test_save(self, mock_rtslib, mock_os):
        """Test that we check path exists with default file."""
        cinder_rtstool.save_to_file(None)
        rtsroot = mock_rtslib.root.RTSRoot
        rtsroot.assert_called_once_with()
        rtsroot.return_value.save_to_file.assert_called_once_with(
            mock.sentinel.filename)
        mock_os.path.dirname.assert_called_once_with(mock.sentinel.filename)
        mock_os.path.exists.assert_called_once_with(mock.sentinel.dirname)
        self.assertEqual(0, mock_os.makedirs.call_count)

    @mock.patch.object(cinder_rtstool, 'os',
                       **{'path.exists.return_value': False,
                          'path.dirname.return_value': mock.sentinel.dirname})
    @mock.patch.object(cinder_rtstool, 'rtslib_fb',
                       **{'root.default_save_file': mock.sentinel.filename})
    def test_save_no_targetcli(self, mock_rtslib, mock_os):
        """Test that we create path if it doesn't exist with default file."""
        cinder_rtstool.save_to_file(None)
        rtsroot = mock_rtslib.root.RTSRoot
        rtsroot.assert_called_once_with()
        rtsroot.return_value.save_to_file.assert_called_once_with(
            mock.sentinel.filename)
        mock_os.path.dirname.assert_called_once_with(mock.sentinel.filename)
        mock_os.path.exists.assert_called_once_with(mock.sentinel.dirname)
        mock_os.makedirs.assert_called_once_with(mock.sentinel.dirname, 0o755)

    @mock.patch.object(cinder_rtstool, 'os', autospec=True)
    @mock.patch.object(cinder_rtstool, 'rtslib_fb', autospec=True)
    def test_save_error_creating_dir(self, mock_rtslib, mock_os):
        mock_os.path.dirname.return_value = 'dirname'
        mock_os.path.exists.return_value = False
        mock_os.makedirs.side_effect = OSError('error')

        regexp = (r'targetcli not installed and could not create default '
                  r'directory \(dirname\): error$')
        self.assertRaisesRegex(cinder_rtstool.RtstoolError, regexp,
                               cinder_rtstool.save_to_file, None)

    @mock.patch.object(cinder_rtstool, 'os', autospec=True)
    @mock.patch.object(cinder_rtstool, 'rtslib_fb', autospec=True)
    def test_save_error_saving(self, mock_rtslib, mock_os):
        save = mock_rtslib.root.RTSRoot.return_value.save_to_file
        save.side_effect = OSError('error')
        regexp = r'Could not save configuration to myfile: error'
        self.assertRaisesRegex(cinder_rtstool.RtstoolError, regexp,
                               cinder_rtstool.save_to_file, 'myfile')

    @mock.patch.object(cinder_rtstool, 'rtslib_fb',
                       **{'root.default_save_file': mock.sentinel.filename})
    def test_restore(self, mock_rtslib):
        """Test that we restore target configuration with default file."""
        cinder_rtstool.restore_from_file(None)
        rtsroot = mock_rtslib.root.RTSRoot
        rtsroot.assert_called_once_with()
        rtsroot.return_value.restore_from_file.assert_called_once_with(
            mock.sentinel.filename)

    @mock.patch.object(cinder_rtstool, 'rtslib_fb')
    def test_restore_with_file(self, mock_rtslib):
        """Test that we restore target configuration with specified file."""
        cinder_rtstool.restore_from_file('saved_file')
        rtsroot = mock_rtslib.root.RTSRoot
        rtsroot.return_value.restore_from_file.assert_called_once_with(
            'saved_file')

    @mock.patch('cinder.cmd.rtstool.restore_from_file')
    def test_restore_error(self, restore_from_file):
        """Test that we fail to restore target configuration."""
        restore_from_file.side_effect = OSError
        self.assertRaises(OSError,
                          cinder_rtstool.restore_from_file,
                          mock.sentinel.filename)

    def test_usage(self):
        with mock.patch('sys.stdout', new=io.StringIO()):
            exit = self.assertRaises(SystemExit, cinder_rtstool.usage)
            self.assertEqual(1, exit.code)

    @mock.patch('cinder.cmd.rtstool.usage')
    def test_main_argc_lt_2(self, usage):
        usage.side_effect = SystemExit(1)
        sys.argv = ['cinder-rtstool']

        exit = self.assertRaises(SystemExit, cinder_rtstool.usage)

        self.assertTrue(usage.called)
        self.assertEqual(1, exit.code)

    def test_main_create_argv_lt_6(self):
        sys.argv = ['cinder-rtstool', 'create']
        self._test_main_check_argv()

    def test_main_create_argv_gt_7(self):
        sys.argv = ['cinder-rtstool', 'create', 'fake-arg1', 'fake-arg2',
                    'fake-arg3', 'fake-arg4', 'fake-arg5', 'fake-arg6']
        self._test_main_check_argv()

    def test_main_add_initiator_argv_lt_6(self):
        sys.argv = ['cinder-rtstool', 'add-initiator']
        self._test_main_check_argv()

    def test_main_delete_argv_lt_3(self):
        sys.argv = ['cinder-rtstool', 'delete']
        self._test_main_check_argv()

    def test_main_no_action(self):
        sys.argv = ['cinder-rtstool']
        self._test_main_check_argv()

    def _test_main_check_argv(self):
        with mock.patch('cinder.cmd.rtstool.usage') as usage:
            usage.side_effect = SystemExit(1)
            sys.argv = ['cinder-rtstool', 'create']

            exit = self.assertRaises(SystemExit, cinder_rtstool.main)

            self.assertTrue(usage.called)
            self.assertEqual(1, exit.code)

    @mock.patch('cinder.cmd.rtstool.save_to_file')
    def test_main_save(self, mock_save):
        sys.argv = ['cinder-rtstool',
                    'save']
        rc = cinder_rtstool.main()
        mock_save.assert_called_once_with(None)
        self.assertEqual(0, rc)

    @mock.patch('cinder.cmd.rtstool.save_to_file')
    def test_main_save_with_file(self, mock_save):
        sys.argv = ['cinder-rtstool',
                    'save',
                    mock.sentinel.filename]
        rc = cinder_rtstool.main()
        mock_save.assert_called_once_with(mock.sentinel.filename)
        self.assertEqual(0, rc)

    def test_main_create(self):
        with mock.patch('cinder.cmd.rtstool.create') as create:
            sys.argv = ['cinder-rtstool',
                        'create',
                        mock.sentinel.backing_device,
                        mock.sentinel.name,
                        mock.sentinel.userid,
                        mock.sentinel.password,
                        mock.sentinel.iser_enabled,
                        str(mock.sentinel.initiator_iqns)]

            rc = cinder_rtstool.main()

            create.assert_called_once_with(
                mock.sentinel.backing_device,
                mock.sentinel.name,
                mock.sentinel.userid,
                mock.sentinel.password,
                mock.sentinel.iser_enabled,
                initiator_iqns=str(mock.sentinel.initiator_iqns))
            self.assertEqual(0, rc)

    @mock.patch('cinder.cmd.rtstool.create')
    def test_main_create_ips_and_port(self, mock_create):
        sys.argv = ['cinder-rtstool',
                    'create',
                    mock.sentinel.backing_device,
                    mock.sentinel.name,
                    mock.sentinel.userid,
                    mock.sentinel.password,
                    mock.sentinel.iser_enabled,
                    str(mock.sentinel.initiator_iqns),
                    '-p3261',
                    '-aip1,ip2,ip3']

        rc = cinder_rtstool.main()

        mock_create.assert_called_once_with(
            mock.sentinel.backing_device,
            mock.sentinel.name,
            mock.sentinel.userid,
            mock.sentinel.password,
            mock.sentinel.iser_enabled,
            initiator_iqns=str(mock.sentinel.initiator_iqns),
            portals_ips=['ip1', 'ip2', 'ip3'],
            portals_port=3261)
        self.assertEqual(0, rc)

    def test_main_add_initiator(self):
        with mock.patch('cinder.cmd.rtstool.add_initiator') as add_initiator:
            sys.argv = ['cinder-rtstool',
                        'add-initiator',
                        mock.sentinel.target_iqn,
                        mock.sentinel.userid,
                        mock.sentinel.password,
                        mock.sentinel.initiator_iqns]

            rc = cinder_rtstool.main()

            add_initiator.assert_called_once_with(
                mock.sentinel.target_iqn, mock.sentinel.initiator_iqns,
                mock.sentinel.userid, mock.sentinel.password)
            self.assertEqual(0, rc)

    def test_main_get_targets(self):
        with mock.patch('cinder.cmd.rtstool.get_targets') as get_targets:
            sys.argv = ['cinder-rtstool', 'get-targets']

            rc = cinder_rtstool.main()

            get_targets.assert_called_once_with()
            self.assertEqual(0, rc)

    def test_main_delete(self):
        with mock.patch('cinder.cmd.rtstool.delete') as delete:
            sys.argv = ['cinder-rtstool', 'delete', mock.sentinel.iqn]

            rc = cinder_rtstool.main()

            delete.assert_called_once_with(mock.sentinel.iqn)
            self.assertEqual(0, rc)

    @mock.patch.object(cinder_rtstool, 'verify_rtslib')
    def test_main_verify(self, mock_verify_rtslib):
        sys.argv = ['cinder-rtstool', 'verify']

        rc = cinder_rtstool.main()

        mock_verify_rtslib.assert_called_once_with()
        self.assertEqual(0, rc)


class TestCinderVolumeUsageAuditCmd(test.TestCase):

    def setUp(self):
        super(TestCinderVolumeUsageAuditCmd, self).setUp()
        sys.argv = ['cinder-volume-usage-audit']

    @mock.patch('cinder.utils.last_completed_audit_period')
    @mock.patch('cinder.rpc.init')
    @mock.patch('cinder.version.version_string')
    @mock.patch('oslo_log.log.getLogger')
    @mock.patch('oslo_log.log.setup')
    @mock.patch('cinder.context.get_admin_context')
    def test_main_time_error(self, get_admin_context, log_setup, get_logger,
                             version_string, rpc_init,
                             last_completed_audit_period):
        CONF.set_override('start_time', '2014-01-01 01:00:00')
        CONF.set_override('end_time', '2013-01-01 01:00:00')
        last_completed_audit_period.return_value = (mock.sentinel.begin,
                                                    mock.sentinel.end)

        exit = self.assertRaises(SystemExit, volume_usage_audit.main)

        get_admin_context.assert_called_once_with()
        self.assertEqual('cinder', CONF.project)
        self.assertEqual(CONF.version, version.version_string())
        log_setup.assert_called_once_with(CONF, "cinder")
        get_logger.assert_called_once_with('cinder')
        self.assertEqual(-1, exit.code)
        rpc_init.assert_called_once_with(CONF)
        last_completed_audit_period.assert_called_once_with()

    @mock.patch('cinder.volume.volume_utils.notify_about_volume_usage')
    @mock.patch('cinder.objects.volume.VolumeList.get_all_active_by_window')
    @mock.patch('cinder.utils.last_completed_audit_period')
    @mock.patch('cinder.rpc.init')
    @mock.patch('cinder.version.version_string')
    @mock.patch('oslo_log.log.getLogger')
    @mock.patch('oslo_log.log.setup')
    @mock.patch('cinder.context.get_admin_context')
    def test_main_send_create_volume_error(self, get_admin_context, log_setup,
                                           get_logger, version_string,
                                           rpc_init,
                                           last_completed_audit_period,
                                           volume_get_all_active_by_window,
                                           notify_about_volume_usage):
        CONF.set_override('send_actions', True)
        CONF.set_override('start_time', '2014-01-01 01:00:00')
        CONF.set_override('end_time', '2014-02-02 02:00:00')
        begin = datetime.datetime(2014, 1, 1, 1, 0, tzinfo=iso8601.UTC)
        end = datetime.datetime(2014, 2, 2, 2, 0, tzinfo=iso8601.UTC)
        ctxt = context.RequestContext(fake.USER_ID, fake.PROJECT_ID)
        get_admin_context.return_value = ctxt
        last_completed_audit_period.return_value = (begin, end)
        volume1_created = datetime.datetime(2014, 1, 1, 2, 0,
                                            tzinfo=iso8601.UTC)
        volume1_deleted = datetime.datetime(2014, 1, 1, 3, 0,
                                            tzinfo=iso8601.UTC)
        volume1 = mock.MagicMock(id=fake.VOLUME_ID, project_id=fake.PROJECT_ID,
                                 created_at=volume1_created,
                                 deleted_at=volume1_deleted)
        volume_get_all_active_by_window.return_value = [volume1]
        extra_info = {
            'audit_period_beginning': str(begin),
            'audit_period_ending': str(end),
        }
        local_extra_info = {
            'audit_period_beginning': str(volume1.created_at),
            'audit_period_ending': str(volume1.created_at),
        }

        def _notify_about_volume_usage(*args, **kwargs):
            if 'create.end' in args:
                raise Exception()
            else:
                pass

        notify_about_volume_usage.side_effect = _notify_about_volume_usage

        volume_usage_audit.main()

        get_admin_context.assert_called_once_with()
        self.assertEqual('cinder', CONF.project)
        self.assertEqual(CONF.version, version.version_string())
        log_setup.assert_called_once_with(CONF, "cinder")
        get_logger.assert_called_once_with('cinder')
        rpc_init.assert_called_once_with(CONF)
        last_completed_audit_period.assert_called_once_with()
        volume_get_all_active_by_window.assert_called_once_with(ctxt, begin,
                                                                end)
        notify_about_volume_usage.assert_has_calls([
            mock.call(ctxt, volume1, 'exists', extra_usage_info=extra_info),
            mock.call(ctxt, volume1, 'create.start',
                      extra_usage_info=local_extra_info),
            mock.call(ctxt, volume1, 'create.end',
                      extra_usage_info=local_extra_info)
        ])

    @mock.patch('cinder.volume.volume_utils.notify_about_volume_usage')
    @mock.patch('cinder.objects.volume.VolumeList.get_all_active_by_window')
    @mock.patch('cinder.utils.last_completed_audit_period')
    @mock.patch('cinder.rpc.init')
    @mock.patch('cinder.version.version_string')
    @mock.patch('oslo_log.log.getLogger')
    @mock.patch('oslo_log.log.setup')
    @mock.patch('cinder.context.get_admin_context')
    def test_main_send_delete_volume_error(self, get_admin_context, log_setup,
                                           get_logger, version_string,
                                           rpc_init,
                                           last_completed_audit_period,
                                           volume_get_all_active_by_window,
                                           notify_about_volume_usage):
        CONF.set_override('send_actions', True)
        CONF.set_override('start_time', '2014-01-01 01:00:00')
        CONF.set_override('end_time', '2014-02-02 02:00:00')
        begin = datetime.datetime(2014, 1, 1, 1, 0, tzinfo=iso8601.UTC)
        end = datetime.datetime(2014, 2, 2, 2, 0, tzinfo=iso8601.UTC)
        ctxt = context.RequestContext(fake.USER_ID, fake.PROJECT_ID)
        get_admin_context.return_value = ctxt
        last_completed_audit_period.return_value = (begin, end)
        volume1_created = datetime.datetime(2014, 1, 1, 2, 0,
                                            tzinfo=iso8601.UTC)
        volume1_deleted = datetime.datetime(2014, 1, 1, 3, 0,
                                            tzinfo=iso8601.UTC)
        volume1 = mock.MagicMock(id=fake.VOLUME_ID, project_id=fake.PROJECT_ID,
                                 created_at=volume1_created,
                                 deleted_at=volume1_deleted)
        volume_get_all_active_by_window.return_value = [volume1]
        extra_info = {
            'audit_period_beginning': str(begin),
            'audit_period_ending': str(end),
        }
        local_extra_info_create = {
            'audit_period_beginning': str(volume1.created_at),
            'audit_period_ending': str(volume1.created_at),
        }
        local_extra_info_delete = {
            'audit_period_beginning': str(volume1.deleted_at),
            'audit_period_ending': str(volume1.deleted_at),
        }

        def _notify_about_volume_usage(*args, **kwargs):
            if 'delete.end' in args:
                raise Exception()
            else:
                pass

        notify_about_volume_usage.side_effect = _notify_about_volume_usage

        volume_usage_audit.main()

        get_admin_context.assert_called_once_with()
        self.assertEqual('cinder', CONF.project)
        self.assertEqual(CONF.version, version.version_string())
        log_setup.assert_called_once_with(CONF, "cinder")
        get_logger.assert_called_once_with('cinder')
        rpc_init.assert_called_once_with(CONF)
        last_completed_audit_period.assert_called_once_with()
        volume_get_all_active_by_window.assert_called_once_with(ctxt, begin,
                                                                end)
        notify_about_volume_usage.assert_has_calls([
            mock.call(ctxt, volume1, 'exists', extra_usage_info=extra_info),
            mock.call(ctxt, volume1, 'create.start',
                      extra_usage_info=local_extra_info_create),
            mock.call(ctxt, volume1, 'create.end',
                      extra_usage_info=local_extra_info_create),
            mock.call(ctxt, volume1, 'delete.start',
                      extra_usage_info=local_extra_info_delete),
            mock.call(ctxt, volume1, 'delete.end',
                      extra_usage_info=local_extra_info_delete)
        ])

    @mock.patch('cinder.volume.volume_utils.notify_about_snapshot_usage')
    @mock.patch('cinder.objects.snapshot.SnapshotList.'
                'get_all_active_by_window')
    @mock.patch('cinder.volume.volume_utils.notify_about_volume_usage')
    @mock.patch('cinder.objects.volume.VolumeList.get_all_active_by_window')
    @mock.patch('cinder.utils.last_completed_audit_period')
    @mock.patch('cinder.rpc.init')
    @mock.patch('cinder.version.version_string')
    @mock.patch('oslo_log.log.getLogger')
    @mock.patch('oslo_log.log.setup')
    @mock.patch('cinder.context.get_admin_context')
    def test_main_send_snapshot_error(self, get_admin_context,
                                      log_setup, get_logger,
                                      version_string, rpc_init,
                                      last_completed_audit_period,
                                      volume_get_all_active_by_window,
                                      notify_about_volume_usage,
                                      snapshot_get_all_active_by_window,
                                      notify_about_snapshot_usage):
        CONF.set_override('send_actions', True)
        CONF.set_override('start_time', '2014-01-01 01:00:00')
        CONF.set_override('end_time', '2014-02-02 02:00:00')
        begin = datetime.datetime(2014, 1, 1, 1, 0, tzinfo=iso8601.UTC)
        end = datetime.datetime(2014, 2, 2, 2, 0, tzinfo=iso8601.UTC)
        ctxt = context.RequestContext(fake.USER_ID, fake.PROJECT_ID)
        get_admin_context.return_value = ctxt
        last_completed_audit_period.return_value = (begin, end)
        snapshot1_created = datetime.datetime(2014, 1, 1, 2, 0,
                                              tzinfo=iso8601.UTC)
        snapshot1_deleted = datetime.datetime(2014, 1, 1, 3, 0,
                                              tzinfo=iso8601.UTC)
        snapshot1 = mock.MagicMock(id=fake.VOLUME_ID,
                                   project_id=fake.PROJECT_ID,
                                   created_at=snapshot1_created,
                                   deleted_at=snapshot1_deleted)
        volume_get_all_active_by_window.return_value = []
        snapshot_get_all_active_by_window.return_value = [snapshot1]
        extra_info = {
            'audit_period_beginning': str(begin),
            'audit_period_ending': str(end),
        }
        local_extra_info_create = {
            'audit_period_beginning': str(snapshot1.created_at),
            'audit_period_ending': str(snapshot1.created_at),
        }
        local_extra_info_delete = {
            'audit_period_beginning': str(snapshot1.deleted_at),
            'audit_period_ending': str(snapshot1.deleted_at),
        }

        def _notify_about_snapshot_usage(*args, **kwargs):
            # notify_about_snapshot_usage raises an exception, but does not
            # block
            raise Exception()

        notify_about_snapshot_usage.side_effect = _notify_about_snapshot_usage

        volume_usage_audit.main()

        get_admin_context.assert_called_once_with()
        self.assertEqual('cinder', CONF.project)
        self.assertEqual(CONF.version, version.version_string())
        log_setup.assert_called_once_with(CONF, "cinder")
        get_logger.assert_called_once_with('cinder')
        rpc_init.assert_called_once_with(CONF)
        last_completed_audit_period.assert_called_once_with()
        volume_get_all_active_by_window.assert_called_once_with(ctxt, begin,
                                                                end)
        self.assertFalse(notify_about_volume_usage.called)
        notify_about_snapshot_usage.assert_has_calls([
            mock.call(ctxt, snapshot1, 'exists', extra_info),
            mock.call(ctxt, snapshot1, 'create.start',
                      extra_usage_info=local_extra_info_create),
            mock.call(ctxt, snapshot1, 'delete.start',
                      extra_usage_info=local_extra_info_delete)
        ])

    @mock.patch('cinder.volume.volume_utils.notify_about_backup_usage')
    @mock.patch('cinder.objects.backup.BackupList.get_all_active_by_window')
    @mock.patch('cinder.volume.volume_utils.notify_about_volume_usage')
    @mock.patch('cinder.objects.volume.VolumeList.get_all_active_by_window')
    @mock.patch('cinder.utils.last_completed_audit_period')
    @mock.patch('cinder.rpc.init')
    @mock.patch('cinder.version.version_string')
    @mock.patch('cinder.context.get_admin_context')
    def test_main_send_backup_error(self, get_admin_context,
                                    version_string, rpc_init,
                                    last_completed_audit_period,
                                    volume_get_all_active_by_window,
                                    notify_about_volume_usage,
                                    backup_get_all_active_by_window,
                                    notify_about_backup_usage):
        CONF.set_override('send_actions', True)
        CONF.set_override('start_time', '2014-01-01 01:00:00')
        CONF.set_override('end_time', '2014-02-02 02:00:00')
        begin = datetime.datetime(2014, 1, 1, 1, 0, tzinfo=iso8601.UTC)
        end = datetime.datetime(2014, 2, 2, 2, 0, tzinfo=iso8601.UTC)
        ctxt = context.RequestContext('fake-user', 'fake-project')
        get_admin_context.return_value = ctxt
        last_completed_audit_period.return_value = (begin, end)
        backup1_created = datetime.datetime(2014, 1, 1, 2, 0,
                                            tzinfo=iso8601.UTC)
        backup1_deleted = datetime.datetime(2014, 1, 1, 3, 0,
                                            tzinfo=iso8601.UTC)
        backup1 = mock.MagicMock(id=fake.BACKUP_ID,
                                 project_id=fake.PROJECT_ID,
                                 created_at=backup1_created,
                                 deleted_at=backup1_deleted)
        volume_get_all_active_by_window.return_value = []
        backup_get_all_active_by_window.return_value = [backup1]
        extra_info = {
            'audit_period_beginning': str(begin),
            'audit_period_ending': str(end),
        }
        local_extra_info_create = {
            'audit_period_beginning': str(backup1.created_at),
            'audit_period_ending': str(backup1.created_at),
        }
        local_extra_info_delete = {
            'audit_period_beginning': str(backup1.deleted_at),
            'audit_period_ending': str(backup1.deleted_at),
        }

        notify_about_backup_usage.side_effect = Exception()

        volume_usage_audit.main()

        get_admin_context.assert_called_once_with()
        self.assertEqual('cinder', CONF.project)
        self.assertEqual(CONF.version, version.version_string())
        rpc_init.assert_called_once_with(CONF)
        last_completed_audit_period.assert_called_once_with()
        volume_get_all_active_by_window.assert_called_once_with(ctxt,
                                                                begin, end)
        self.assertFalse(notify_about_volume_usage.called)
        notify_about_backup_usage.assert_any_call(ctxt, backup1, 'exists',
                                                  extra_info)
        notify_about_backup_usage.assert_any_call(
            ctxt, backup1, 'create.start',
            extra_usage_info=local_extra_info_create)
        notify_about_backup_usage.assert_any_call(
            ctxt, backup1, 'delete.start',
            extra_usage_info=local_extra_info_delete)

    @mock.patch('cinder.volume.volume_utils.notify_about_backup_usage')
    @mock.patch('cinder.objects.backup.BackupList.get_all_active_by_window')
    @mock.patch('cinder.volume.volume_utils.notify_about_snapshot_usage')
    @mock.patch('cinder.objects.snapshot.SnapshotList.'
                'get_all_active_by_window')
    @mock.patch('cinder.volume.volume_utils.notify_about_volume_usage')
    @mock.patch('cinder.objects.volume.VolumeList.get_all_active_by_window')
    @mock.patch('cinder.utils.last_completed_audit_period')
    @mock.patch('cinder.rpc.init')
    @mock.patch('cinder.version.version_string')
    @mock.patch('oslo_log.log.getLogger')
    @mock.patch('oslo_log.log.setup')
    @mock.patch('cinder.context.get_admin_context')
    def test_main(self, get_admin_context, log_setup, get_logger,
                  version_string, rpc_init, last_completed_audit_period,
                  volume_get_all_active_by_window, notify_about_volume_usage,
                  snapshot_get_all_active_by_window,
                  notify_about_snapshot_usage, backup_get_all_active_by_window,
                  notify_about_backup_usage):
        CONF.set_override('send_actions', True)
        CONF.set_override('start_time', '2014-01-01 01:00:00')
        CONF.set_override('end_time', '2014-02-02 02:00:00')
        begin = datetime.datetime(2014, 1, 1, 1, 0, tzinfo=iso8601.UTC)
        end = datetime.datetime(2014, 2, 2, 2, 0, tzinfo=iso8601.UTC)
        ctxt = context.RequestContext(fake.USER_ID, fake.PROJECT_ID)
        get_admin_context.return_value = ctxt
        last_completed_audit_period.return_value = (begin, end)

        volume1_created = datetime.datetime(2014, 1, 1, 2, 0,
                                            tzinfo=iso8601.UTC)
        volume1_deleted = datetime.datetime(2014, 1, 1, 3, 0,
                                            tzinfo=iso8601.UTC)
        volume1 = mock.MagicMock(id=fake.VOLUME_ID, project_id=fake.PROJECT_ID,
                                 created_at=volume1_created,
                                 deleted_at=volume1_deleted)
        volume_get_all_active_by_window.return_value = [volume1]
        extra_info = {
            'audit_period_beginning': str(begin),
            'audit_period_ending': str(end),
        }
        extra_info_volume_create = {
            'audit_period_beginning': str(volume1.created_at),
            'audit_period_ending': str(volume1.created_at),
        }
        extra_info_volume_delete = {
            'audit_period_beginning': str(volume1.deleted_at),
            'audit_period_ending': str(volume1.deleted_at),
        }

        snapshot1_created = datetime.datetime(2014, 1, 1, 2, 0,
                                              tzinfo=iso8601.UTC)
        snapshot1_deleted = datetime.datetime(2014, 1, 1, 3, 0,
                                              tzinfo=iso8601.UTC)
        snapshot1 = mock.MagicMock(id=fake.VOLUME_ID,
                                   project_id=fake.PROJECT_ID,
                                   created_at=snapshot1_created,
                                   deleted_at=snapshot1_deleted)
        snapshot_get_all_active_by_window.return_value = [snapshot1]
        extra_info_snapshot_create = {
            'audit_period_beginning': str(snapshot1.created_at),
            'audit_period_ending': str(snapshot1.created_at),
        }
        extra_info_snapshot_delete = {
            'audit_period_beginning': str(snapshot1.deleted_at),
            'audit_period_ending': str(snapshot1.deleted_at),
        }

        backup1_created = datetime.datetime(2014, 1, 1, 2, 0,
                                            tzinfo=iso8601.UTC)
        backup1_deleted = datetime.datetime(2014, 1, 1, 3, 0,
                                            tzinfo=iso8601.UTC)
        backup1 = mock.MagicMock(id=fake.BACKUP_ID,
                                 project_id=fake.PROJECT_ID,
                                 created_at=backup1_created,
                                 deleted_at=backup1_deleted)
        backup_get_all_active_by_window.return_value = [backup1]
        extra_info_backup_create = {
            'audit_period_beginning': str(backup1.created_at),
            'audit_period_ending': str(backup1.created_at),
        }
        extra_info_backup_delete = {
            'audit_period_beginning': str(backup1.deleted_at),
            'audit_period_ending': str(backup1.deleted_at),
        }

        volume_usage_audit.main()

        get_admin_context.assert_called_once_with()
        self.assertEqual('cinder', CONF.project)
        self.assertEqual(CONF.version, version.version_string())
        log_setup.assert_called_once_with(CONF, "cinder")
        get_logger.assert_called_once_with('cinder')
        rpc_init.assert_called_once_with(CONF)
        last_completed_audit_period.assert_called_once_with()
        volume_get_all_active_by_window.assert_called_once_with(ctxt,
                                                                begin, end)
        notify_about_volume_usage.assert_has_calls([
            mock.call(ctxt, volume1, 'exists', extra_usage_info=extra_info),
            mock.call(ctxt, volume1, 'create.start',
                      extra_usage_info=extra_info_volume_create),
            mock.call(ctxt, volume1, 'create.end',
                      extra_usage_info=extra_info_volume_create),
            mock.call(ctxt, volume1, 'delete.start',
                      extra_usage_info=extra_info_volume_delete),
            mock.call(ctxt, volume1, 'delete.end',
                      extra_usage_info=extra_info_volume_delete)
        ])

        notify_about_snapshot_usage.assert_has_calls([
            mock.call(ctxt, snapshot1, 'exists', extra_info),
            mock.call(ctxt, snapshot1, 'create.start',
                      extra_usage_info=extra_info_snapshot_create),
            mock.call(ctxt, snapshot1, 'create.end',
                      extra_usage_info=extra_info_snapshot_create),
            mock.call(ctxt, snapshot1, 'delete.start',
                      extra_usage_info=extra_info_snapshot_delete),
            mock.call(ctxt, snapshot1, 'delete.end',
                      extra_usage_info=extra_info_snapshot_delete)
        ])

        notify_about_backup_usage.assert_has_calls([
            mock.call(ctxt, backup1, 'exists', extra_info),
            mock.call(ctxt, backup1, 'create.start',
                      extra_usage_info=extra_info_backup_create),
            mock.call(ctxt, backup1, 'create.end',
                      extra_usage_info=extra_info_backup_create),
            mock.call(ctxt, backup1, 'delete.start',
                      extra_usage_info=extra_info_backup_delete),
            mock.call(ctxt, backup1, 'delete.end',
                      extra_usage_info=extra_info_backup_delete)
        ])


class TestVolumeSharedTargetsOnlineMigration(test.TestCase):
    """Unit tests for cinder.db.api.service_*."""

    def setUp(self):
        super(TestVolumeSharedTargetsOnlineMigration, self).setUp()

        def _get_minimum_rpc_version_mock(ctxt, binary):
            binary_map = {
                'cinder-volume': rpcapi.VolumeAPI,
            }
            return binary_map[binary].RPC_API_VERSION

        self.patch('cinder.objects.Service.get_minimum_rpc_version',
                   side_effect=_get_minimum_rpc_version_mock)

        ctxt = context.get_admin_context()
        # default value in db for shared_targets on a volume
        # is True, so don't need to set it here explicitly
        for i in range(3):
            sqlalchemy_api.volume_create(
                ctxt,
                {'host': 'host1@lvm-driver1#lvm-driver1',
                 'service_uuid': 'f080f895-cff2-4eb3-9c61-050c060b59ad',
                 'volume_type_id': fake.VOLUME_TYPE_ID})

        values = {
            'host': 'host1@lvm-driver1',
            'binary': constants.VOLUME_BINARY,
            'topic': constants.VOLUME_TOPIC,
            'uuid': 'f080f895-cff2-4eb3-9c61-050c060b59ad'}
        utils.create_service(ctxt, values)
        self.ctxt = ctxt
