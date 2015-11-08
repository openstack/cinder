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

import datetime
import six
import sys

try:
    from unittest import mock
except ImportError:
    import mock
from oslo_config import cfg

try:
    import rtslib_fb
except ImportError:
    import rtslib as rtslib_fb


from cinder.cmd import all as cinder_all
from cinder.cmd import api as cinder_api
from cinder.cmd import backup as cinder_backup
from cinder.cmd import manage as cinder_manage
from cinder.cmd import rtstool as cinder_rtstool
from cinder.cmd import scheduler as cinder_scheduler
from cinder.cmd import volume as cinder_volume
from cinder.cmd import volume_usage_audit
from cinder import context
from cinder import test
from cinder import version

CONF = cfg.CONF


class TestCinderApiCmd(test.TestCase):
    """Unit test cases for python modules under cinder/cmd."""

    def setUp(self):
        super(TestCinderApiCmd, self).setUp()
        sys.argv = ['cinder-api']
        CONF(sys.argv[1:], project='cinder', version=version.version_string())

    def tearDown(self):
        super(TestCinderApiCmd, self).tearDown()

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
        launcher.launch_service.assert_called_once_with(server,
                                                        workers=server.workers)
        launcher.wait.assert_called_once_with()


class TestCinderBackupCmd(test.TestCase):

    def setUp(self):
        super(TestCinderBackupCmd, self).setUp()
        sys.argv = ['cinder-backup']
        CONF(sys.argv[1:], project='cinder', version=version.version_string())

    def tearDown(self):
        super(TestCinderBackupCmd, self).tearDown()

    @mock.patch('cinder.service.wait')
    @mock.patch('cinder.service.serve')
    @mock.patch('cinder.service.Service.create')
    @mock.patch('cinder.utils.monkey_patch')
    @mock.patch('oslo_log.log.setup')
    def test_main(self, log_setup, monkey_patch, service_create, service_serve,
                  service_wait):
        server = service_create.return_value

        cinder_backup.main()

        self.assertEqual('cinder', CONF.project)
        self.assertEqual(CONF.version, version.version_string())
        log_setup.assert_called_once_with(CONF, "cinder")
        monkey_patch.assert_called_once_with()
        service_create.assert_called_once_with(binary='cinder-backup')
        service_serve.assert_called_once_with(server)
        service_wait.assert_called_once_with()


class TestCinderAllCmd(test.TestCase):

    def setUp(self):
        super(TestCinderAllCmd, self).setUp()
        sys.argv = ['cinder-all']
        CONF(sys.argv[1:], project='cinder', version=version.version_string())

    def tearDown(self):
        super(TestCinderAllCmd, self).tearDown()

    @mock.patch('cinder.rpc.init')
    @mock.patch('cinder.service.Service.create')
    @mock.patch('cinder.service.WSGIService')
    @mock.patch('cinder.service.process_launcher')
    @mock.patch('cinder.utils.monkey_patch')
    @mock.patch('oslo_log.log.getLogger')
    @mock.patch('oslo_log.log.setup')
    def test_main(self, log_setup, get_logger, monkey_patch, process_launcher,
                  wsgi_service, service_create, rpc_init):
        CONF.set_override('enabled_backends', None)
        launcher = process_launcher.return_value
        server = wsgi_service.return_value
        server.workers = mock.sentinel.worker_count
        service = service_create.return_value

        cinder_all.main()

        self.assertEqual('cinder', CONF.project)
        self.assertEqual(CONF.version, version.version_string())
        log_setup.assert_called_once_with(CONF, "cinder")
        get_logger.assert_called_once_with('cinder.all')
        monkey_patch.assert_called_once_with()
        rpc_init.assert_called_once_with(CONF)
        process_launcher.assert_called_once_with()
        wsgi_service.assert_called_once_with('osapi_volume')
        launcher.launch_service.assert_any_call(server, workers=server.workers)

        service_create.assert_has_calls([mock.call(binary='cinder-scheduler'),
                                         mock.call(binary='cinder-backup'),
                                         mock.call(binary='cinder-volume')])
        self.assertEqual(3, service_create.call_count)
        launcher.launch_service.assert_has_calls([mock.call(service)] * 3)
        self.assertEqual(4, launcher.launch_service.call_count)

        launcher.wait.assert_called_once_with()

    @mock.patch('cinder.rpc.init')
    @mock.patch('cinder.service.Service.create')
    @mock.patch('cinder.service.WSGIService')
    @mock.patch('cinder.service.process_launcher')
    @mock.patch('cinder.utils.monkey_patch')
    @mock.patch('oslo_log.log.getLogger')
    @mock.patch('oslo_log.log.setup')
    def test_main_with_backend(self, log_setup, get_logger, monkey_patch,
                               process_launcher, wsgi_service, service_create,
                               rpc_init):
        CONF.set_override('enabled_backends', ['backend1'])
        CONF.set_override('host', 'host')
        launcher = process_launcher.return_value
        server = wsgi_service.return_value
        server.workers = mock.sentinel.worker_count
        service = service_create.return_value

        cinder_all.main()

        self.assertEqual('cinder', CONF.project)
        self.assertEqual(CONF.version, version.version_string())
        log_setup.assert_called_once_with(CONF, "cinder")
        get_logger.assert_called_once_with('cinder.all')
        monkey_patch.assert_called_once_with()
        rpc_init.assert_called_once_with(CONF)
        process_launcher.assert_called_once_with()
        wsgi_service.assert_called_once_with('osapi_volume')
        launcher.launch_service.assert_any_call(server, workers=server.workers)

        service_create.assert_has_calls([mock.call(binary='cinder-scheduler'),
                                         mock.call(binary='cinder-backup'),
                                         mock.call(binary='cinder-volume',
                                                   host='host@backend1',
                                                   service_name='backend1')])
        self.assertEqual(3, service_create.call_count)
        launcher.launch_service.assert_has_calls([mock.call(service)] * 3)
        self.assertEqual(4, launcher.launch_service.call_count)

        launcher.wait.assert_called_once_with()

    @mock.patch('cinder.rpc.init')
    @mock.patch('cinder.service.Service.create')
    @mock.patch('cinder.service.WSGIService')
    @mock.patch('cinder.service.process_launcher')
    @mock.patch('cinder.utils.monkey_patch')
    @mock.patch('oslo_log.log.getLogger')
    @mock.patch('oslo_log.log.setup')
    def test_main_load_osapi_volume_exception(self, log_setup, get_logger,
                                              monkey_patch, process_launcher,
                                              wsgi_service, service_create,
                                              rpc_init):
        launcher = process_launcher.return_value
        server = wsgi_service.return_value
        server.workers = mock.sentinel.worker_count
        mock_log = get_logger.return_value

        for ex in (Exception(), SystemExit()):
            launcher.launch_service.side_effect = ex

            cinder_all.main()

            self.assertEqual('cinder', CONF.project)
            self.assertEqual(CONF.version, version.version_string())
            log_setup.assert_called_once_with(CONF, "cinder")
            get_logger.assert_called_once_with('cinder.all')
            monkey_patch.assert_called_once_with()
            process_launcher.assert_called_once_with()
            wsgi_service.assert_called_once_with('osapi_volume')
            rpc_init.assert_called_with(CONF)
            launcher.launch_service.assert_any_call(server,
                                                    workers=server.workers)
            self.assertTrue(mock_log.exception.called)

            # Reset for the next exception
            log_setup.reset_mock()
            get_logger.reset_mock()
            monkey_patch.reset_mock()
            process_launcher.reset_mock()
            wsgi_service.reset_mock()
            mock_log.reset_mock()

    @mock.patch('cinder.rpc.init')
    @mock.patch('cinder.service.Service.create')
    @mock.patch('cinder.service.WSGIService')
    @mock.patch('cinder.service.process_launcher')
    @mock.patch('cinder.utils.monkey_patch')
    @mock.patch('oslo_log.log.getLogger')
    @mock.patch('oslo_log.log.setup')
    def test_main_load_binary_exception(self, log_setup, get_logger,
                                        monkey_patch, process_launcher,
                                        wsgi_service, service_create,
                                        rpc_init):
        CONF.set_override('enabled_backends', None)
        launcher = process_launcher.return_value
        server = wsgi_service.return_value
        server.workers = mock.sentinel.worker_count
        service = service_create.return_value
        mock_log = get_logger.return_value

        def launch_service(*args, **kwargs):
            if service in args:
                raise Exception()

        launcher.launch_service.side_effect = launch_service

        cinder_all.main()

        self.assertEqual('cinder', CONF.project)
        self.assertEqual(CONF.version, version.version_string())
        log_setup.assert_called_once_with(CONF, "cinder")
        get_logger.assert_called_once_with('cinder.all')
        monkey_patch.assert_called_once_with()
        process_launcher.assert_called_once_with()
        wsgi_service.assert_called_once_with('osapi_volume')
        launcher.launch_service.assert_any_call(server,
                                                workers=server.workers)
        for binary in ['cinder-volume', 'cinder-scheduler', 'cinder-backup']:
            service_create.assert_any_call(binary=binary)
            launcher.launch_service.assert_called_with(service)
        rpc_init.assert_called_once_with(CONF)
        self.assertTrue(mock_log.exception.called)


class TestCinderSchedulerCmd(test.TestCase):

    def setUp(self):
        super(TestCinderSchedulerCmd, self).setUp()
        sys.argv = ['cinder-scheduler']
        CONF(sys.argv[1:], project='cinder', version=version.version_string())

    def tearDown(self):
        super(TestCinderSchedulerCmd, self).tearDown()

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


class TestCinderVolumeCmd(test.TestCase):

    def setUp(self):
        super(TestCinderVolumeCmd, self).setUp()
        sys.argv = ['cinder-volume']
        CONF(sys.argv[1:], project='cinder', version=version.version_string())

    def tearDown(self):
        super(TestCinderVolumeCmd, self).tearDown()

    @mock.patch('cinder.service.get_launcher')
    @mock.patch('cinder.service.Service.create')
    @mock.patch('cinder.utils.monkey_patch')
    @mock.patch('oslo_log.log.setup')
    def test_main(self, log_setup, monkey_patch, service_create,
                  get_launcher):
        CONF.set_override('enabled_backends', None)
        launcher = get_launcher.return_value
        server = service_create.return_value

        cinder_volume.main()

        self.assertEqual('cinder', CONF.project)
        self.assertEqual(CONF.version, version.version_string())
        log_setup.assert_called_once_with(CONF, "cinder")
        monkey_patch.assert_called_once_with()
        get_launcher.assert_called_once_with()
        service_create.assert_called_once_with(binary='cinder-volume')
        launcher.launch_service.assert_called_once_with(server)
        launcher.wait.assert_called_once_with()

    @mock.patch('cinder.service.get_launcher')
    @mock.patch('cinder.service.Service.create')
    @mock.patch('cinder.utils.monkey_patch')
    @mock.patch('oslo_log.log.setup')
    def test_main_with_backends(self, log_setup, monkey_patch, service_create,
                                get_launcher):
        backends = ['backend1', 'backend2']
        CONF.set_override('enabled_backends', backends)
        launcher = get_launcher.return_value

        cinder_volume.main()

        self.assertEqual('cinder', CONF.project)
        self.assertEqual(CONF.version, version.version_string())
        log_setup.assert_called_once_with(CONF, "cinder")
        monkey_patch.assert_called_once_with()
        get_launcher.assert_called_once_with()
        self.assertEqual(len(backends), service_create.call_count)
        self.assertEqual(len(backends), launcher.launch_service.call_count)
        launcher.wait.assert_called_once_with()


class TestCinderManageCmd(test.TestCase):

    def setUp(self):
        super(TestCinderManageCmd, self).setUp()
        sys.argv = ['cinder-manage']
        CONF(sys.argv[1:], project='cinder', version=version.version_string())

    def tearDown(self):
        super(TestCinderManageCmd, self).tearDown()

    @mock.patch('oslo_utils.uuidutils.is_uuid_like')
    def test_param2id(self, is_uuid_like):
        mock_object_id = mock.MagicMock()
        is_uuid_like.return_value = True

        object_id = cinder_manage.param2id(mock_object_id)
        self.assertEqual(mock_object_id, object_id)
        is_uuid_like.assert_called_once_with(mock_object_id)

    @mock.patch('oslo_utils.uuidutils.is_uuid_like')
    def test_param2id_int_string(self, is_uuid_like):
        object_id_str = '10'
        is_uuid_like.return_value = False

        object_id = cinder_manage.param2id(object_id_str)
        self.assertEqual(10, object_id)
        is_uuid_like.assert_called_once_with(object_id_str)

    @mock.patch('cinder.db.migration.db_sync')
    def test_db_commands_sync(self, db_sync):
        version = mock.MagicMock()
        db_cmds = cinder_manage.DbCommands()
        db_cmds.sync(version=version)
        db_sync.assert_called_once_with(version)

    @mock.patch('oslo_db.sqlalchemy.migration.db_version')
    def test_db_commands_version(self, db_version):
        db_cmds = cinder_manage.DbCommands()
        with mock.patch('sys.stdout', new=six.StringIO()):
            db_cmds.version()
            self.assertEqual(1, db_version.call_count)

    @mock.patch('cinder.version.version_string')
    def test_versions_commands_list(self, version_string):
        version_cmds = cinder_manage.VersionCommands()
        with mock.patch('sys.stdout', new=six.StringIO()):
            version_cmds.list()
            version_string.assert_called_once_with()

    @mock.patch('cinder.version.version_string')
    def test_versions_commands_call(self, version_string):
        version_cmds = cinder_manage.VersionCommands()
        with mock.patch('sys.stdout', new=six.StringIO()):
            version_cmds.__call__()
            version_string.assert_called_once_with()

    @mock.patch('cinder.db.service_get_all')
    @mock.patch('cinder.context.get_admin_context')
    def test_host_commands_list(self, get_admin_context, service_get_all):
        get_admin_context.return_value = mock.sentinel.ctxt
        service_get_all.return_value = [{'host': 'fake-host',
                                         'availability_zone': 'fake-az'}]

        with mock.patch('sys.stdout', new=six.StringIO()) as fake_out:
            expected_out = ("%(host)-25s\t%(zone)-15s\n" %
                            {'host': 'host', 'zone': 'zone'})
            expected_out += ("%(host)-25s\t%(availability_zone)-15s\n" %
                             {'host': 'fake-host',
                              'availability_zone': 'fake-az'})
            host_cmds = cinder_manage.HostCommands()
            host_cmds.list()

            get_admin_context.assert_called_once_with()
            service_get_all.assert_called_once_with(mock.sentinel.ctxt, None)
            self.assertEqual(expected_out, fake_out.getvalue())

    @mock.patch('cinder.db.service_get_all')
    @mock.patch('cinder.context.get_admin_context')
    def test_host_commands_list_with_zone(self, get_admin_context,
                                          service_get_all):
        get_admin_context.return_value = mock.sentinel.ctxt
        service_get_all.return_value = [{'host': 'fake-host',
                                         'availability_zone': 'fake-az1'},
                                        {'host': 'fake-host',
                                         'availability_zone': 'fake-az2'}]

        with mock.patch('sys.stdout', new=six.StringIO()) as fake_out:
            expected_out = ("%(host)-25s\t%(zone)-15s\n" %
                            {'host': 'host', 'zone': 'zone'})
            expected_out += ("%(host)-25s\t%(availability_zone)-15s\n" %
                             {'host': 'fake-host',
                              'availability_zone': 'fake-az1'})
            host_cmds = cinder_manage.HostCommands()
            host_cmds.list(zone='fake-az1')

            get_admin_context.assert_called_once_with()
            service_get_all.assert_called_once_with(mock.sentinel.ctxt, None)
            self.assertEqual(expected_out, fake_out.getvalue())

    @mock.patch('cinder.objects.base.CinderObjectSerializer')
    @mock.patch('cinder.rpc.get_client')
    @mock.patch('cinder.rpc.init')
    @mock.patch('cinder.rpc.initialized', return_value=False)
    @mock.patch('oslo_messaging.Target')
    def test_volume_commands_init(self, messaging_target, rpc_initialized,
                                  rpc_init, get_client, object_serializer):
        CONF.set_override('volume_topic', 'fake-topic')
        mock_target = messaging_target.return_value
        mock_rpc_client = get_client.return_value

        volume_cmds = cinder_manage.VolumeCommands()
        rpc_client = volume_cmds._rpc_client()

        rpc_initialized.assert_called_once_with()
        rpc_init.assert_called_once_with(CONF)
        messaging_target.assert_called_once_with(topic='fake-topic')
        get_client.assert_called_once_with(mock_target,
                                           serializer=object_serializer())
        self.assertEqual(mock_rpc_client, rpc_client)

    @mock.patch('cinder.db.volume_get')
    @mock.patch('cinder.context.get_admin_context')
    @mock.patch('cinder.rpc.get_client')
    @mock.patch('cinder.rpc.init')
    def test_volume_commands_delete(self, rpc_init, get_client,
                                    get_admin_context, volume_get):
        ctxt = context.RequestContext('fake-user', 'fake-project')
        get_admin_context.return_value = ctxt
        mock_client = mock.MagicMock()
        cctxt = mock.MagicMock()
        mock_client.prepare.return_value = cctxt
        get_client.return_value = mock_client
        volume_id = '123'
        host = 'fake@host'
        volume = {'id': volume_id,
                  'host': host + '#pool1',
                  'status': 'available'}
        volume_get.return_value = volume

        volume_cmds = cinder_manage.VolumeCommands()
        volume_cmds._client = mock_client
        volume_cmds.delete(volume_id)

        volume_get.assert_called_once_with(ctxt, 123)
        # NOTE prepare called w/o pool part in host
        mock_client.prepare.assert_called_once_with(server=host)
        cctxt.cast.assert_called_once_with(ctxt, 'delete_volume',
                                           volume_id=volume['id'])

    @mock.patch('cinder.db.volume_destroy')
    @mock.patch('cinder.db.volume_get')
    @mock.patch('cinder.context.get_admin_context')
    @mock.patch('cinder.rpc.init')
    def test_volume_commands_delete_no_host(self, rpc_init, get_admin_context,
                                            volume_get, volume_destroy):
        ctxt = context.RequestContext('fake-user', 'fake-project')
        get_admin_context.return_value = ctxt
        volume_id = '123'
        volume = {'id': volume_id, 'host': None, 'status': 'available'}
        volume_get.return_value = volume

        with mock.patch('sys.stdout', new=six.StringIO()) as fake_out:
            expected_out = ('Volume not yet assigned to host.\n'
                            'Deleting volume from database and skipping'
                            ' rpc.\n')
            volume_cmds = cinder_manage.VolumeCommands()
            volume_cmds.delete(volume_id)

            get_admin_context.assert_called_once_with()
            volume_get.assert_called_once_with(ctxt, 123)
            volume_destroy.assert_called_once_with(ctxt, 123)
            self.assertEqual(expected_out, fake_out.getvalue())

    @mock.patch('cinder.db.volume_destroy')
    @mock.patch('cinder.db.volume_get')
    @mock.patch('cinder.context.get_admin_context')
    @mock.patch('cinder.rpc.init')
    def test_volume_commands_delete_volume_in_use(self, rpc_init,
                                                  get_admin_context,
                                                  volume_get, volume_destroy):
        ctxt = context.RequestContext('fake-user', 'fake-project')
        get_admin_context.return_value = ctxt
        volume_id = '123'
        volume = {'id': volume_id, 'host': 'fake-host', 'status': 'in-use'}
        volume_get.return_value = volume

        with mock.patch('sys.stdout', new=six.StringIO()) as fake_out:
            expected_out = ('Volume is in-use.\n'
                            'Detach volume from instance and then try'
                            ' again.\n')
            volume_cmds = cinder_manage.VolumeCommands()
            volume_cmds.delete(volume_id)

            volume_get.assert_called_once_with(ctxt, 123)
            self.assertEqual(expected_out, fake_out.getvalue())

    def test_config_commands_list(self):
        with mock.patch('sys.stdout', new=six.StringIO()) as fake_out:
            expected_out = ''
            for key, value in CONF.items():
                expected_out += '%s = %s' % (key, value) + '\n'

            config_cmds = cinder_manage.ConfigCommands()
            config_cmds.list()

            self.assertEqual(expected_out, fake_out.getvalue())

    def test_config_commands_list_param(self):
        with mock.patch('sys.stdout', new=six.StringIO()) as fake_out:
            CONF.set_override('host', 'fake')
            expected_out = 'host = fake\n'

            config_cmds = cinder_manage.ConfigCommands()
            config_cmds.list(param='host')

            self.assertEqual(expected_out, fake_out.getvalue())

    def test_get_log_commands_no_errors(self):
        with mock.patch('sys.stdout', new=six.StringIO()) as fake_out:
            CONF.set_override('log_dir', None)
            expected_out = 'No errors in logfiles!\n'

            get_log_cmds = cinder_manage.GetLogCommands()
            get_log_cmds.errors()

            self.assertEqual(expected_out, fake_out.getvalue())

    @mock.patch('six.moves.builtins.open')
    @mock.patch('os.listdir')
    def test_get_log_commands_errors(self, listdir, open):
        CONF.set_override('log_dir', 'fake-dir')
        listdir.return_value = ['fake-error.log']

        with mock.patch('sys.stdout', new=six.StringIO()) as fake_out:
            open.return_value = six.StringIO(
                '[ ERROR ] fake-error-message')
            expected_out = ('fake-dir/fake-error.log:-\n'
                            'Line 1 : [ ERROR ] fake-error-message\n')

            get_log_cmds = cinder_manage.GetLogCommands()
            get_log_cmds.errors()

            self.assertEqual(expected_out, fake_out.getvalue())
            open.assert_called_once_with('fake-dir/fake-error.log', 'r')
            listdir.assert_called_once_with(CONF.log_dir)

    @mock.patch('six.moves.builtins.open')
    @mock.patch('os.path.exists')
    def test_get_log_commands_syslog_no_log_file(self, path_exists, open):
        path_exists.return_value = False

        get_log_cmds = cinder_manage.GetLogCommands()
        with mock.patch('sys.stdout', new=six.StringIO()):
            exit = self.assertRaises(SystemExit, get_log_cmds.syslog)
            self.assertEqual(1, exit.code)

            path_exists.assert_any_call('/var/log/syslog')
            path_exists.assert_any_call('/var/log/messages')

    @mock.patch('cinder.db.backup_get_all')
    @mock.patch('cinder.context.get_admin_context')
    def test_backup_commands_list(self, get_admin_context, backup_get_all):
        ctxt = context.RequestContext('fake-user', 'fake-project')
        get_admin_context.return_value = ctxt
        backup = {'id': 1,
                  'user_id': 'fake-user-id',
                  'project_id': 'fake-project-id',
                  'host': 'fake-host',
                  'display_name': 'fake-display-name',
                  'container': 'fake-container',
                  'status': 'fake-status',
                  'size': 123,
                  'object_count': 1,
                  'volume_id': 'fake-volume-id',
                  }
        backup_get_all.return_value = [backup]
        with mock.patch('sys.stdout', new=six.StringIO()) as fake_out:
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

    @mock.patch('cinder.utils.service_is_up')
    @mock.patch('cinder.db.service_get_all')
    @mock.patch('cinder.context.get_admin_context')
    def _test_service_commands_list(self, service, get_admin_context,
                                    service_get_all, service_is_up):
        ctxt = context.RequestContext('fake-user', 'fake-project')
        get_admin_context.return_value = ctxt
        service_get_all.return_value = [service]
        service_is_up.return_value = True
        with mock.patch('sys.stdout', new=six.StringIO()) as fake_out:
            format = "%-16s %-36s %-16s %-10s %-5s %-10s"
            print_format = format % ('Binary',
                                     'Host',
                                     'Zone',
                                     'Status',
                                     'State',
                                     'Updated At')
            service_format = format % (service['binary'],
                                       service['host'].partition('.')[0],
                                       service['availability_zone'],
                                       'enabled',
                                       ':-)',
                                       service['updated_at'])
            expected_out = print_format + '\n' + service_format + '\n'

            service_cmds = cinder_manage.ServiceCommands()
            service_cmds.list()

            self.assertEqual(expected_out, fake_out.getvalue())
            get_admin_context.assert_called_with()
            service_get_all.assert_called_with(ctxt, None)

    def test_service_commands_list(self):
        service = {'binary': 'cinder-binary',
                   'host': 'fake-host.fake-domain',
                   'availability_zone': 'fake-zone',
                   'updated_at': '2014-06-30 11:22:33',
                   'disabled': False}
        self._test_service_commands_list(service)

    def test_service_commands_list_no_updated_at(self):
        service = {'binary': 'cinder-binary',
                   'host': 'fake-host.fake-domain',
                   'availability_zone': 'fake-zone',
                   'updated_at': None,
                   'disabled': False}
        self._test_service_commands_list(service)

    def test_get_arg_string(self):
        args1 = "foobar"
        args2 = "-foo bar"
        args3 = "--foo bar"

        self.assertEqual("foobar", cinder_manage.get_arg_string(args1))
        self.assertEqual("foo bar", cinder_manage.get_arg_string(args2))
        self.assertEqual("foo bar", cinder_manage.get_arg_string(args3))

    @mock.patch('oslo_config.cfg.ConfigOpts.register_cli_opt')
    def test_main_argv_lt_2(self, register_cli_opt):
        script_name = 'cinder-manage'
        sys.argv = [script_name]
        CONF(sys.argv[1:], project='cinder', version=version.version_string())

        with mock.patch('sys.stdout', new=six.StringIO()):
            exit = self.assertRaises(SystemExit, cinder_manage.main)
            self.assertTrue(register_cli_opt.called)
            self.assertEqual(2, exit.code)

    @mock.patch('oslo_config.cfg.ConfigOpts.__call__')
    @mock.patch('oslo_log.log.setup')
    @mock.patch('oslo_config.cfg.ConfigOpts.register_cli_opt')
    def test_main_sudo_failed(self, register_cli_opt, log_setup,
                              config_opts_call):
        script_name = 'cinder-manage'
        sys.argv = [script_name, 'fake_category', 'fake_action']
        config_opts_call.side_effect = cfg.ConfigFilesNotFoundError(
            mock.sentinel._namespace)

        with mock.patch('sys.stdout', new=six.StringIO()):
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

        with mock.patch('sys.stdout', new=six.StringIO()) as fake_out:
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
    @mock.patch('cinder.db.service_get_by_args',
                return_value = {'id': '12'})
    def test_remove_service_success(self, mock_get_by_args,
                                    mock_service_destroy):
        service_commands = cinder_manage.ServiceCommands()
        self.assertIsNone(service_commands.remove('abinary', 'ahost'))


class TestCinderRtstoolCmd(test.TestCase):

    def setUp(self):
        super(TestCinderRtstoolCmd, self).setUp()
        sys.argv = ['cinder-rtstool']
        CONF(sys.argv[1:], project='cinder', version=version.version_string())

    def tearDown(self):
        super(TestCinderRtstoolCmd, self).tearDown()

    @mock.patch.object(rtslib_fb.root, 'RTSRoot')
    def test_create_rtslib_error(self, rtsroot):
        rtsroot.side_effect = rtslib_fb.utils.RTSLibError()

        with mock.patch('sys.stdout', new=six.StringIO()):
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
                mock.patch.object(rtslib_fb, 'FabricModule') as fabric_module, \
                mock.patch.object(rtslib_fb, 'Target') as target, \
                mock.patch.object(rtslib_fb, 'BlockStorageObject') as \
                block_storage_object, \
                mock.patch.object(rtslib_fb.root, 'RTSRoot') as rts_root:
            root_new = mock.MagicMock(storage_objects=mock.MagicMock())
            rts_root.return_value = root_new
            block_storage_object.return_value = mock.sentinel.so_new
            target.return_value = mock.sentinel.target_new
            fabric_module.return_value = mock.sentinel.fabric_new
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
            fabric_module.assert_called_once_with('iscsi')
            tpg.assert_called_once_with(mock.sentinel.target_new,
                                        mode='create')
            tpg_new.set_attribute.assert_called_once_with('authentication',
                                                          '1')
            lun.assert_called_once_with(tpg_new,
                                        storage_object=mock.sentinel.so_new)
            self.assertEqual(1, tpg_new.enable)
            network_portal.assert_any_call(tpg_new, ip, 3260,
                                           mode='any')

            if ip == '::0':
                network_portal.assert_any_call(tpg_new, ip, 3260, mode='any')

    def test_create_rtslib_error_network_portal_ipv4(self):
        with mock.patch('sys.stdout', new=six.StringIO()):
            self._test_create_rtslib_error_network_portal('0.0.0.0')

    def test_create_rtslib_error_network_portal_ipv6(self):
        with mock.patch('sys.stdout', new=six.StringIO()):
            self._test_create_rtslib_error_network_portal('::0')

    def _test_create(self, ip):
        with mock.patch.object(rtslib_fb, 'NetworkPortal') as network_portal, \
                mock.patch.object(rtslib_fb, 'LUN') as lun, \
                mock.patch.object(rtslib_fb, 'TPG') as tpg, \
                mock.patch.object(rtslib_fb, 'FabricModule') as fabric_module, \
                mock.patch.object(rtslib_fb, 'Target') as target, \
                mock.patch.object(rtslib_fb, 'BlockStorageObject') as \
                block_storage_object, \
                mock.patch.object(rtslib_fb.root, 'RTSRoot') as rts_root:
            root_new = mock.MagicMock(storage_objects=mock.MagicMock())
            rts_root.return_value = root_new
            block_storage_object.return_value = mock.sentinel.so_new
            target.return_value = mock.sentinel.target_new
            fabric_module.return_value = mock.sentinel.fabric_new
            tpg_new = tpg.return_value
            lun.return_value = mock.sentinel.lun_new

            def network_portal_exception(*args, **kwargs):
                if set([tpg_new, '::0', 3260]).issubset(list(args)):
                    raise rtslib_fb.utils.RTSLibError()
                else:
                    pass

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
            fabric_module.assert_called_once_with('iscsi')
            tpg.assert_called_once_with(mock.sentinel.target_new,
                                        mode='create')
            tpg_new.set_attribute.assert_called_once_with('authentication',
                                                          '1')
            lun.assert_called_once_with(tpg_new,
                                        storage_object=mock.sentinel.so_new)
            self.assertEqual(1, tpg_new.enable)
            network_portal.assert_any_call(tpg_new, ip, 3260,
                                           mode='any')

            if ip == '::0':
                network_portal.assert_any_call(tpg_new, ip, 3260, mode='any')

    def test_create_ipv4(self):
        self._test_create('0.0.0.0')

    def test_create_ipv6(self):
        self._test_create('::0')

    @mock.patch.object(cinder_rtstool, 'rtslib_fb', autospec=True)
    def test_create_ips_and_port(self, mock_rtslib):
        port = 3261
        ips = ['ip1', 'ip2', 'ip3']

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
            map(lambda ip: mock.call(tpg_new, ip, port, mode='any'), ips),
            any_order=True
        )

    @mock.patch.object(rtslib_fb.root, 'RTSRoot')
    def test_add_initiator_rtslib_error(self, rtsroot):
        rtsroot.side_effect = rtslib_fb.utils.RTSLibError()

        with mock.patch('sys.stdout', new=six.StringIO()):
            self.assertRaises(rtslib_fb.utils.RTSLibError,
                              cinder_rtstool.add_initiator,
                              mock.sentinel.target_iqn,
                              mock.sentinel.initiator_iqn,
                              mock.sentinel.userid,
                              mock.sentinel.password)

    @mock.patch.object(rtslib_fb.root, 'RTSRoot')
    def test_add_initiator_rtstool_error(self, rtsroot):
        rtsroot.targets.return_value = {}

        self.assertRaises(cinder_rtstool.RtstoolError,
                          cinder_rtstool.add_initiator,
                          mock.sentinel.target_iqn,
                          mock.sentinel.initiator_iqn,
                          mock.sentinel.userid,
                          mock.sentinel.password)

    @mock.patch.object(rtslib_fb, 'MappedLUN')
    @mock.patch.object(rtslib_fb, 'NodeACL')
    @mock.patch.object(rtslib_fb.root, 'RTSRoot')
    def test_add_initiator_acl_exists(self, rtsroot, node_acl, mapped_lun):
        target_iqn = mock.MagicMock()
        target_iqn.tpgs.return_value = \
            [{'node_acls': mock.sentinel.initiator_iqn}]
        acl = mock.MagicMock(node_wwn=mock.sentinel.initiator_iqn)
        tpg = mock.MagicMock(node_acls=[acl])
        tpgs = iter([tpg])
        target = mock.MagicMock(tpgs=tpgs, wwn=target_iqn)
        rtsroot.return_value = mock.MagicMock(targets=[target])

        cinder_rtstool.add_initiator(target_iqn,
                                     mock.sentinel.initiator_iqn,
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
            [{'node_acls': mock.sentinel.initiator_iqn}]
        tpg = mock.MagicMock()
        tpgs = iter([tpg])
        target = mock.MagicMock(tpgs=tpgs, wwn=target_iqn)
        rtsroot.return_value = mock.MagicMock(targets=[target])

        acl_new = mock.MagicMock(chap_userid=mock.sentinel.userid,
                                 chap_password=mock.sentinel.password)
        node_acl.return_value = acl_new

        cinder_rtstool.add_initiator(target_iqn,
                                     mock.sentinel.initiator_iqn,
                                     mock.sentinel.userid,
                                     mock.sentinel.password)
        node_acl.assert_called_once_with(tpg,
                                         mock.sentinel.initiator_iqn,
                                         mode='create')
        mapped_lun.assert_called_once_with(acl_new, 0, tpg_lun=0)

    @mock.patch.object(rtslib_fb.root, 'RTSRoot')
    def test_get_targets(self, rtsroot):
        target = mock.MagicMock()
        target.dump.return_value = {'wwn': 'fake-wwn'}
        rtsroot.return_value = mock.MagicMock(targets=[target])

        with mock.patch('sys.stdout', new=six.StringIO()) as fake_out:
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

    def test_usage(self):
        with mock.patch('sys.stdout', new=six.StringIO()):
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
        CONF(sys.argv[1:], project='cinder', version=version.version_string())

    def tearDown(self):
        super(TestCinderVolumeUsageAuditCmd, self).tearDown()

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

    @mock.patch('cinder.volume.utils.notify_about_volume_usage')
    @mock.patch('cinder.db.volume_get_active_by_window')
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
                                           volume_get_active_by_window,
                                           notify_about_volume_usage):
        CONF.set_override('send_actions', True)
        CONF.set_override('start_time', '2014-01-01 01:00:00')
        CONF.set_override('end_time', '2014-02-02 02:00:00')
        begin = datetime.datetime(2014, 1, 1, 1, 0)
        end = datetime.datetime(2014, 2, 2, 2, 0)
        ctxt = context.RequestContext('fake-user', 'fake-project')
        get_admin_context.return_value = ctxt
        last_completed_audit_period.return_value = (begin, end)
        volume1_created = datetime.datetime(2014, 1, 1, 2, 0)
        volume1_deleted = datetime.datetime(2014, 1, 1, 3, 0)
        volume1 = mock.MagicMock(id='1', project_id='fake-project',
                                 created_at=volume1_created,
                                 deleted_at=volume1_deleted)
        volume_get_active_by_window.return_value = [volume1]
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
        volume_get_active_by_window.assert_called_once_with(ctxt, begin, end)
        notify_about_volume_usage.assert_any_call(ctxt, volume1, 'exists',
                                                  extra_usage_info=extra_info)
        notify_about_volume_usage.assert_any_call(
            ctxt, volume1, 'create.start', extra_usage_info=local_extra_info)
        notify_about_volume_usage.assert_any_call(
            ctxt, volume1, 'create.end', extra_usage_info=local_extra_info)

    @mock.patch('cinder.volume.utils.notify_about_volume_usage')
    @mock.patch('cinder.db.volume_get_active_by_window')
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
                                           volume_get_active_by_window,
                                           notify_about_volume_usage):
        CONF.set_override('send_actions', True)
        CONF.set_override('start_time', '2014-01-01 01:00:00')
        CONF.set_override('end_time', '2014-02-02 02:00:00')
        begin = datetime.datetime(2014, 1, 1, 1, 0)
        end = datetime.datetime(2014, 2, 2, 2, 0)
        ctxt = context.RequestContext('fake-user', 'fake-project')
        get_admin_context.return_value = ctxt
        last_completed_audit_period.return_value = (begin, end)
        volume1_created = datetime.datetime(2014, 1, 1, 2, 0)
        volume1_deleted = datetime.datetime(2014, 1, 1, 3, 0)
        volume1 = mock.MagicMock(id='1', project_id='fake-project',
                                 created_at=volume1_created,
                                 deleted_at=volume1_deleted)
        volume_get_active_by_window.return_value = [volume1]
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
        volume_get_active_by_window.assert_called_once_with(ctxt, begin, end)
        notify_about_volume_usage.assert_any_call(
            ctxt, volume1, 'exists', extra_usage_info=extra_info)
        notify_about_volume_usage.assert_any_call(
            ctxt, volume1, 'create.start',
            extra_usage_info=local_extra_info_create)
        notify_about_volume_usage.assert_any_call(
            ctxt, volume1, 'create.end',
            extra_usage_info=local_extra_info_create)
        notify_about_volume_usage.assert_any_call(
            ctxt, volume1, 'delete.start',
            extra_usage_info=local_extra_info_delete)
        notify_about_volume_usage.assert_any_call(
            ctxt, volume1, 'delete.end',
            extra_usage_info=local_extra_info_delete)

    @mock.patch('cinder.volume.utils.notify_about_snapshot_usage')
    @mock.patch('cinder.objects.snapshot.SnapshotList.get_active_by_window')
    @mock.patch('cinder.volume.utils.notify_about_volume_usage')
    @mock.patch('cinder.db.volume_get_active_by_window')
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
                                      volume_get_active_by_window,
                                      notify_about_volume_usage,
                                      snapshot_get_active_by_window,
                                      notify_about_snapshot_usage):
        CONF.set_override('send_actions', True)
        CONF.set_override('start_time', '2014-01-01 01:00:00')
        CONF.set_override('end_time', '2014-02-02 02:00:00')
        begin = datetime.datetime(2014, 1, 1, 1, 0)
        end = datetime.datetime(2014, 2, 2, 2, 0)
        ctxt = context.RequestContext('fake-user', 'fake-project')
        get_admin_context.return_value = ctxt
        last_completed_audit_period.return_value = (begin, end)
        snapshot1_created = datetime.datetime(2014, 1, 1, 2, 0)
        snapshot1_deleted = datetime.datetime(2014, 1, 1, 3, 0)
        snapshot1 = mock.MagicMock(id='1', project_id='fake-project',
                                   created_at=snapshot1_created,
                                   deleted_at=snapshot1_deleted)
        volume_get_active_by_window.return_value = []
        snapshot_get_active_by_window.return_value = [snapshot1]
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
        volume_get_active_by_window.assert_called_once_with(ctxt, begin, end)
        self.assertFalse(notify_about_volume_usage.called)
        notify_about_snapshot_usage.assert_any_call(ctxt, snapshot1, 'exists',
                                                    extra_info)
        notify_about_snapshot_usage.assert_any_call(
            ctxt, snapshot1, 'create.start',
            extra_usage_info=local_extra_info_create)
        notify_about_snapshot_usage.assert_any_call(
            ctxt, snapshot1, 'delete.start',
            extra_usage_info=local_extra_info_delete)

    @mock.patch('cinder.volume.utils.notify_about_snapshot_usage')
    @mock.patch('cinder.objects.snapshot.SnapshotList.get_active_by_window')
    @mock.patch('cinder.volume.utils.notify_about_volume_usage')
    @mock.patch('cinder.db.volume_get_active_by_window')
    @mock.patch('cinder.utils.last_completed_audit_period')
    @mock.patch('cinder.rpc.init')
    @mock.patch('cinder.version.version_string')
    @mock.patch('oslo_log.log.getLogger')
    @mock.patch('oslo_log.log.setup')
    @mock.patch('cinder.context.get_admin_context')
    def test_main(self, get_admin_context, log_setup, get_logger,
                  version_string, rpc_init, last_completed_audit_period,
                  volume_get_active_by_window, notify_about_volume_usage,
                  snapshot_get_active_by_window, notify_about_snapshot_usage):
        CONF.set_override('send_actions', True)
        CONF.set_override('start_time', '2014-01-01 01:00:00')
        CONF.set_override('end_time', '2014-02-02 02:00:00')
        begin = datetime.datetime(2014, 1, 1, 1, 0)
        end = datetime.datetime(2014, 2, 2, 2, 0)
        ctxt = context.RequestContext('fake-user', 'fake-project')
        get_admin_context.return_value = ctxt
        last_completed_audit_period.return_value = (begin, end)

        volume1_created = datetime.datetime(2014, 1, 1, 2, 0)
        volume1_deleted = datetime.datetime(2014, 1, 1, 3, 0)
        volume1 = mock.MagicMock(id='1', project_id='fake-project',
                                 created_at=volume1_created,
                                 deleted_at=volume1_deleted)
        volume_get_active_by_window.return_value = [volume1]
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

        snapshot1_created = datetime.datetime(2014, 1, 1, 2, 0)
        snapshot1_deleted = datetime.datetime(2014, 1, 1, 3, 0)
        snapshot1 = mock.MagicMock(id='1', project_id='fake-project',
                                   created_at=snapshot1_created,
                                   deleted_at=snapshot1_deleted)
        snapshot_get_active_by_window.return_value = [snapshot1]
        extra_info_snapshot_create = {
            'audit_period_beginning': str(snapshot1.created_at),
            'audit_period_ending': str(snapshot1.created_at),
        }
        extra_info_snapshot_delete = {
            'audit_period_beginning': str(snapshot1.deleted_at),
            'audit_period_ending': str(snapshot1.deleted_at),
        }

        volume_usage_audit.main()

        get_admin_context.assert_called_once_with()
        self.assertEqual('cinder', CONF.project)
        self.assertEqual(CONF.version, version.version_string())
        log_setup.assert_called_once_with(CONF, "cinder")
        get_logger.assert_called_once_with('cinder')
        rpc_init.assert_called_once_with(CONF)
        last_completed_audit_period.assert_called_once_with()
        volume_get_active_by_window.assert_called_once_with(ctxt, begin, end)
        notify_about_volume_usage.assert_any_call(
            ctxt, volume1, 'exists', extra_usage_info=extra_info)
        notify_about_volume_usage.assert_any_call(
            ctxt, volume1, 'create.start',
            extra_usage_info=extra_info_volume_create)
        notify_about_volume_usage.assert_any_call(
            ctxt, volume1, 'create.end',
            extra_usage_info=extra_info_volume_create)
        notify_about_volume_usage.assert_any_call(
            ctxt, volume1, 'delete.start',
            extra_usage_info=extra_info_volume_delete)
        notify_about_volume_usage.assert_any_call(
            ctxt, volume1, 'delete.end',
            extra_usage_info=extra_info_volume_delete)

        notify_about_snapshot_usage.assert_any_call(ctxt, snapshot1,
                                                    'exists', extra_info)
        notify_about_snapshot_usage.assert_any_call(
            ctxt, snapshot1, 'create.start',
            extra_usage_info=extra_info_snapshot_create)
        notify_about_snapshot_usage.assert_any_call(
            ctxt, snapshot1, 'create.end',
            extra_usage_info=extra_info_snapshot_create)
        notify_about_snapshot_usage.assert_any_call(
            ctxt, snapshot1, 'delete.start',
            extra_usage_info=extra_info_snapshot_delete)
        notify_about_snapshot_usage.assert_any_call(
            ctxt, snapshot1, 'delete.end',
            extra_usage_info=extra_info_snapshot_delete)
