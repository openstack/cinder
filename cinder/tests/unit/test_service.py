
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
Unit Tests for remote procedure calls using queue
"""

import ddt
import mock
from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_db import exception as db_exc

from cinder.common import constants
from cinder import context
from cinder import db
from cinder import exception
from cinder import manager
from cinder import objects
from cinder.objects import fields
from cinder import rpc
from cinder import service
from cinder import test


test_service_opts = [
    cfg.StrOpt("fake_manager",
               default="cinder.tests.unit.test_service.FakeManager",
               help="Manager for testing"),
    cfg.StrOpt("test_service_listen",
               help="Host to bind test service to"),
    cfg.IntOpt("test_service_listen_port",
               default=0,
               help="Port number to bind test service to"), ]

CONF = cfg.CONF
CONF.register_opts(test_service_opts)


class FakeManager(manager.Manager):
    """Fake manager for tests."""
    def __init__(self, host=None,
                 db_driver=None, service_name=None, cluster=None):
        super(FakeManager, self).__init__(host=host,
                                          db_driver=db_driver,
                                          cluster=cluster)

    def test_method(self):
        return 'manager'


class ExtendedService(service.Service):
    def test_method(self):
        return 'service'


class ServiceManagerTestCase(test.TestCase):
    """Test cases for Services."""

    def test_message_gets_to_manager(self):
        serv = service.Service('test',
                               'test',
                               'test',
                               'cinder.tests.unit.test_service.FakeManager')
        serv.start()
        self.assertEqual('manager', serv.test_method())

    def test_override_manager_method(self):
        serv = ExtendedService('test',
                               'test',
                               'test',
                               'cinder.tests.unit.test_service.FakeManager')
        serv.start()
        self.assertEqual('service', serv.test_method())

    @mock.patch('cinder.rpc.LAST_OBJ_VERSIONS', {'test': '1.5'})
    @mock.patch('cinder.rpc.LAST_RPC_VERSIONS', {'test': '1.3'})
    def test_reset(self):
        serv = service.Service('test',
                               'test',
                               'test',
                               'cinder.tests.unit.test_service.FakeManager')
        serv.start()
        serv.reset()
        self.assertEqual({}, rpc.LAST_OBJ_VERSIONS)
        self.assertEqual({}, rpc.LAST_RPC_VERSIONS)

    def test_start_refresh_serivce_id(self):
        serv = service.Service('test',
                               'test',
                               'test',
                               'cinder.tests.unit.test_service.FakeManager')
        # records the original service id
        serv_id = serv.service_id
        self.assertEqual(serv.origin_service_id, service.Service.service_id)
        # update service id to other value
        service.Service.service_id = serv_id + 1
        # make sure the class attr service_id have been changed
        self.assertNotEqual(serv.origin_service_id,
                            service.Service.service_id)
        # call start method
        serv.start()
        # After start, the service id is refreshed to original service_id
        self.assertEqual(serv_id, service.Service.service_id)


class ServiceFlagsTestCase(test.TestCase):
    def test_service_enabled_on_create_based_on_flag(self):
        ctxt = context.get_admin_context()
        self.flags(enable_new_services=True)
        host = 'foo'
        binary = 'cinder-fake'
        cluster = 'cluster'
        app = service.Service.create(host=host, binary=binary, cluster=cluster)
        ref = db.service_get(ctxt, app.service_id)
        db.service_destroy(ctxt, app.service_id)
        self.assertFalse(ref.disabled)

        # Check that the cluster is also enabled
        db_cluster = objects.ClusterList.get_all(ctxt)[0]
        self.assertFalse(db_cluster.disabled)
        db.cluster_destroy(ctxt, db_cluster.id)

    def test_service_disabled_on_create_based_on_flag(self):
        ctxt = context.get_admin_context()
        self.flags(enable_new_services=False)
        host = 'foo'
        binary = 'cinder-fake'
        cluster = 'cluster'
        app = service.Service.create(host=host, binary=binary, cluster=cluster)
        ref = db.service_get(ctxt, app.service_id)
        db.service_destroy(ctxt, app.service_id)
        self.assertTrue(ref.disabled)

        # Check that the cluster is also enabled
        db_cluster = objects.ClusterList.get_all(ctxt)[0]
        self.assertTrue(db_cluster.disabled)
        db.cluster_destroy(ctxt, db_cluster.id)


@ddt.ddt
class ServiceTestCase(test.TestCase):
    """Test cases for Services."""

    def setUp(self):
        super(ServiceTestCase, self).setUp()
        self.host = 'foo'
        self.binary = 'cinder-fake'
        self.topic = 'fake'
        self.service_ref = {'host': self.host,
                            'binary': self.binary,
                            'topic': self.topic,
                            'report_count': 0,
                            'availability_zone': 'nova',
                            'id': 1,
                            'uuid': 'a3a593da-7f8d-4bb7-8b4c-f2bc1e0b4824'}
        self.ctxt = context.get_admin_context()

    def _check_app(self, app, cluster=None, cluster_exists=None,
                   svc_id=None, added_to_cluster=True):
        """Check that Service instance and DB service and cluster are ok."""
        self.assertIsNotNone(app)

        # Check that we have the service ID
        self.assertTrue(hasattr(app, 'service_id'))

        if svc_id:
            self.assertEqual(svc_id, app.service_id)

        # Check that cluster has been properly set
        self.assertEqual(cluster, app.cluster)
        # Check that the entry has been really created in the DB
        svc = objects.Service.get_by_id(self.ctxt, app.service_id)

        cluster_name = cluster if cluster_exists is not False else None

        # Check that cluster name matches
        self.assertEqual(cluster_name, svc.cluster_name)

        clusters = objects.ClusterList.get_all(self.ctxt)

        if cluster_name:
            # Make sure we have created the cluster in the DB
            self.assertEqual(1, len(clusters))
            cluster = clusters[0]
            self.assertEqual(cluster_name, cluster.name)
            self.assertEqual(self.binary, cluster.binary)
        else:
            # Make sure we haven't created any cluster in the DB
            self.assertListEqual([], clusters.objects)

        self.assertEqual(added_to_cluster, app.added_to_cluster)

    def test_create_with_cluster_not_upgrading(self):
        """Test DB cluster creation when service is created."""
        cluster_name = 'cluster'
        app = service.Service.create(host=self.host, binary=self.binary,
                                     cluster=cluster_name, topic=self.topic)
        self._check_app(app, cluster_name)

    def test_create_svc_exists_upgrade_cluster(self):
        """Test that we update cluster_name field when cfg has changed."""
        # Create the service in the DB
        db_svc = db.service_create(context.get_admin_context(),
                                   {'host': self.host, 'binary': self.binary,
                                    'topic': self.topic,
                                    'cluster_name': None})
        cluster_name = 'cluster'
        app = service.Service.create(host=self.host, binary=self.binary,
                                     cluster=cluster_name, topic=self.topic)
        self._check_app(app, cluster_name, svc_id=db_svc.id,
                        added_to_cluster=cluster_name)

    @mock.patch.object(objects.service.Service, 'get_by_args')
    @mock.patch.object(objects.service.Service, 'get_by_id')
    def test_report_state_newly_disconnected(self, get_by_id, get_by_args):
        get_by_args.side_effect = exception.NotFound()
        get_by_id.side_effect = db_exc.DBConnectionError()
        with mock.patch.object(objects.service, 'db') as mock_db:
            mock_db.service_create.return_value = self.service_ref

            serv = service.Service(
                self.host,
                self.binary,
                self.topic,
                'cinder.tests.unit.test_service.FakeManager'
            )
            serv.start()
            serv.report_state()
            self.assertTrue(serv.model_disconnected)
            self.assertFalse(mock_db.service_update.called)

    @mock.patch.object(objects.service.Service, 'get_by_args')
    @mock.patch.object(objects.service.Service, 'get_by_id')
    def test_report_state_disconnected_DBError(self, get_by_id, get_by_args):
        get_by_args.side_effect = exception.NotFound()
        get_by_id.side_effect = db_exc.DBError()
        with mock.patch.object(objects.service, 'db') as mock_db:
            mock_db.service_create.return_value = self.service_ref

            serv = service.Service(
                self.host,
                self.binary,
                self.topic,
                'cinder.tests.unit.test_service.FakeManager'
            )
            serv.start()
            serv.report_state()
            self.assertTrue(serv.model_disconnected)
            self.assertFalse(mock_db.service_update.called)

    @mock.patch('cinder.db.sqlalchemy.api.service_update')
    @mock.patch('cinder.db.sqlalchemy.api.service_get')
    def test_report_state_newly_connected(self, get_by_id, service_update):
        get_by_id.return_value = self.service_ref

        serv = service.Service(
            self.host,
            self.binary,
            self.topic,
            'cinder.tests.unit.test_service.FakeManager'
        )
        serv.start()
        serv.model_disconnected = True
        serv.report_state()

        self.assertFalse(serv.model_disconnected)
        self.assertTrue(service_update.called)

    def test_report_state_manager_not_working(self):
        with mock.patch('cinder.db') as mock_db:
            mock_db.service_get.return_value = self.service_ref

            serv = service.Service(
                self.host,
                self.binary,
                self.topic,
                'cinder.tests.unit.test_service.FakeManager'
            )
            serv.manager.is_working = mock.Mock(return_value=False)
            serv.start()
            serv.report_state()

            serv.manager.is_working.assert_called_once_with()
            self.assertFalse(mock_db.service_update.called)

    def test_service_with_long_report_interval(self):
        self.override_config('service_down_time', 10)
        self.override_config('report_interval', 10)
        service.Service.create(
            binary="test_service",
            manager="cinder.tests.unit.test_service.FakeManager")
        self.assertEqual(25, CONF.service_down_time)

    @mock.patch.object(rpc, 'get_server')
    @mock.patch('cinder.db')
    def test_service_stop_waits_for_rpcserver(self, mock_db, mock_rpc):
        serv = service.Service(
            self.host,
            self.binary,
            self.topic,
            'cinder.tests.unit.test_service.FakeManager'
        )
        serv.start()
        serv.stop()
        serv.wait()
        serv.rpcserver.start.assert_called_once_with()
        serv.rpcserver.stop.assert_called_once_with()
        serv.rpcserver.wait.assert_called_once_with()

    @mock.patch('cinder.service.Service.report_state')
    @mock.patch('cinder.service.Service.periodic_tasks')
    @mock.patch.object(rpc, 'get_server')
    @mock.patch('cinder.db')
    def test_service_stop_wait(self, mock_db, mock_rpc,
                               mock_periodic, mock_report):
        """Test that we wait for loopcalls only if stop succeeds."""
        serv = service.Service(
            self.host,
            self.binary,
            self.topic,
            'cinder.tests.unit.test_service.FakeManager',
            report_interval=5,
            periodic_interval=10,
        )

        serv.start()
        serv.stop()
        serv.wait()
        serv.rpcserver.start.assert_called_once_with()
        serv.rpcserver.stop.assert_called_once_with()
        serv.rpcserver.wait.assert_called_once_with()

    @mock.patch('cinder.manager.Manager.init_host')
    @mock.patch('oslo_messaging.Target')
    @mock.patch.object(rpc, 'get_server')
    def _check_rpc_servers_and_init_host(self, app, added_to_cluster, cluster,
                                         rpc_mock, target_mock,
                                         init_host_mock):
        app.start()

        # Since we have created the service entry we call init_host with
        # added_to_cluster=True
        init_host_mock.assert_called_once_with(
            added_to_cluster=added_to_cluster,
            service_id=self.service_ref['id'])

        expected_target_calls = [mock.call(topic=self.topic, server=self.host)]
        expected_rpc_calls = [mock.call(target_mock.return_value, mock.ANY,
                                        mock.ANY),
                              mock.call().start()]

        if cluster and added_to_cluster:
            self.assertIsNotNone(app.cluster_rpcserver)
            expected_target_calls.append(mock.call(
                topic=self.topic + '.' + cluster,
                server=cluster.split('@')[0]))
            expected_rpc_calls.extend(expected_rpc_calls[:])

        # Check that we create message targets for host and cluster
        target_mock.assert_has_calls(expected_target_calls)

        # Check we get and start rpc services for host and cluster
        rpc_mock.assert_has_calls(expected_rpc_calls)

        self.assertIsNotNone(app.rpcserver)

        app.stop()

    @mock.patch('cinder.objects.Service.get_minimum_obj_version',
                return_value='1.6')
    def test_start_rpc_and_init_host_no_cluster(self, is_upgrading_mock):
        """Test that without cluster we don't create rpc service."""
        app = service.Service.create(host=self.host,
                                     binary=constants.VOLUME_BINARY,
                                     cluster=None, topic=self.topic)
        self._check_rpc_servers_and_init_host(app, False, None)

    @mock.patch('cinder.objects.Service.get_minimum_obj_version')
    def test_start_rpc_and_init_host_cluster(self, get_min_obj_mock):
        """Test that with cluster we create the rpc service."""
        get_min_obj_mock.return_value = '1.7'
        cluster = 'cluster@backend#pool'
        self.host = 'host@backend#pool'
        app = service.Service.create(host=self.host,
                                     binary=constants.VOLUME_BINARY,
                                     cluster=cluster, topic=self.topic)
        self._check_rpc_servers_and_init_host(app, True, cluster)

    @mock.patch('cinder.objects.Cluster.get_by_id')
    def test_ensure_cluster_exists_no_cluster(self, get_mock):
        app = service.Service.create(host=self.host,
                                     binary=self.binary,
                                     topic=self.topic)
        svc = objects.Service.get_by_id(self.ctxt, app.service_id)
        app._ensure_cluster_exists(self.ctxt, svc)
        get_mock.assert_not_called()
        self.assertEqual({}, svc.cinder_obj_get_changes())

    @mock.patch('cinder.objects.Cluster.get_by_id')
    def test_ensure_cluster_exists_cluster_exists_non_relicated(self,
                                                                get_mock):
        cluster = objects.Cluster(
            name='cluster_name', active_backend_id=None, frozen=False,
            replication_status=fields.ReplicationStatus.NOT_CAPABLE)
        get_mock.return_value = cluster

        app = service.Service.create(host=self.host,
                                     binary=self.binary,
                                     topic=self.topic)
        svc = objects.Service.get_by_id(self.ctxt, app.service_id)
        app.cluster = cluster.name
        app._ensure_cluster_exists(self.ctxt, svc)
        get_mock.assert_called_once_with(self.ctxt, None, name=cluster.name,
                                         binary=app.binary)
        self.assertEqual({}, svc.cinder_obj_get_changes())

    @mock.patch('cinder.objects.Cluster.get_by_id')
    def test_ensure_cluster_exists_cluster_change(self, get_mock):
        """We copy replication fields from the cluster to the service."""
        changes = dict(replication_status=fields.ReplicationStatus.FAILED_OVER,
                       active_backend_id='secondary',
                       frozen=True)
        cluster = objects.Cluster(name='cluster_name', **changes)
        get_mock.return_value = cluster

        app = service.Service.create(host=self.host,
                                     binary=self.binary,
                                     topic=self.topic)
        svc = objects.Service.get_by_id(self.ctxt, app.service_id)
        app.cluster = cluster.name
        app._ensure_cluster_exists(self.ctxt, svc)
        get_mock.assert_called_once_with(self.ctxt, None, name=cluster.name,
                                         binary=app.binary)
        self.assertEqual(changes, svc.cinder_obj_get_changes())

    @mock.patch('cinder.objects.Cluster.get_by_id')
    def test_ensure_cluster_exists_cluster_no_change(self, get_mock):
        """Don't copy replication fields from cluster if replication error."""
        changes = dict(replication_status=fields.ReplicationStatus.FAILED_OVER,
                       active_backend_id='secondary',
                       frozen=True)
        cluster = objects.Cluster(name='cluster_name', **changes)
        get_mock.return_value = cluster

        app = service.Service.create(host=self.host,
                                     binary=self.binary,
                                     topic=self.topic)
        svc = objects.Service.get_by_id(self.ctxt, app.service_id)
        svc.replication_status = fields.ReplicationStatus.ERROR
        svc.obj_reset_changes()
        app.cluster = cluster.name
        app._ensure_cluster_exists(self.ctxt, svc)
        get_mock.assert_called_once_with(self.ctxt, None, name=cluster.name,
                                         binary=app.binary)
        self.assertEqual({}, svc.cinder_obj_get_changes())

    def test_ensure_cluster_exists_cluster_create_replicated_and_non(self):
        """We use service replication fields to create the cluster."""
        changes = dict(replication_status=fields.ReplicationStatus.FAILED_OVER,
                       active_backend_id='secondary',
                       frozen=True)

        app = service.Service.create(host=self.host,
                                     binary=self.binary,
                                     topic=self.topic)
        svc = objects.Service.get_by_id(self.ctxt, app.service_id)
        for key, value in changes.items():
            setattr(svc, key, value)

        app.cluster = 'cluster_name'
        app._ensure_cluster_exists(self.ctxt, svc)

        cluster = objects.Cluster.get_by_id(self.ctxt, None, name=app.cluster)
        for key, value in changes.items():
            self.assertEqual(value, getattr(cluster, key))


class TestWSGIService(test.TestCase):

    @mock.patch('oslo_service.wsgi.Loader')
    def test_service_random_port(self, mock_loader):
        test_service = service.WSGIService("test_service")
        self.assertEqual(0, test_service.port)
        test_service.start()
        self.assertNotEqual(0, test_service.port)
        test_service.stop()
        self.assertTrue(mock_loader.called)

    @mock.patch('oslo_service.wsgi.Loader')
    def test_reset_pool_size_to_default(self, mock_loader):
        test_service = service.WSGIService("test_service")
        test_service.start()

        # Stopping the service, which in turn sets pool size to 0
        test_service.stop()
        self.assertEqual(0, test_service.server._pool.size)

        # Resetting pool size to default
        test_service.reset()
        test_service.start()
        self.assertEqual(cfg.CONF.wsgi_default_pool_size,
                         test_service.server._pool.size)
        self.assertTrue(mock_loader.called)

    @mock.patch('oslo_service.wsgi.Loader')
    def test_workers_set_default(self, mock_loader):
        self.override_config('osapi_volume_listen_port',
                             CONF.test_service_listen_port)
        test_service = service.WSGIService("osapi_volume")
        self.assertEqual(processutils.get_worker_count(),
                         test_service.workers)
        self.assertTrue(mock_loader.called)

    @mock.patch('oslo_service.wsgi.Loader')
    def test_workers_set_good_user_setting(self, mock_loader):
        self.override_config('osapi_volume_listen_port',
                             CONF.test_service_listen_port)
        self.override_config('osapi_volume_workers', 8)
        test_service = service.WSGIService("osapi_volume")
        self.assertEqual(8, test_service.workers)
        self.assertTrue(mock_loader.called)

    @mock.patch('oslo_service.wsgi.Loader')
    def test_workers_set_zero_user_setting(self, mock_loader):
        self.override_config('osapi_volume_listen_port',
                             CONF.test_service_listen_port)
        self.override_config('osapi_volume_workers', 0)
        test_service = service.WSGIService("osapi_volume")
        # If a value less than 1 is used, defaults to number of procs
        # available
        self.assertEqual(processutils.get_worker_count(),
                         test_service.workers)
        self.assertTrue(mock_loader.called)

    @mock.patch('oslo_service.wsgi.Loader')
    def test_workers_set_negative_user_setting(self, mock_loader):
        self.override_config('osapi_volume_workers', -1)
        self.assertRaises(exception.InvalidConfigurationValue,
                          service.WSGIService, "osapi_volume")
        self.assertTrue(mock_loader.called)

    @mock.patch('oslo_service.wsgi.Server')
    @mock.patch('oslo_service.wsgi.Loader')
    def test_ssl_enabled(self, mock_loader, mock_server):
        self.override_config('osapi_volume_use_ssl', True)

        service.WSGIService("osapi_volume")
        mock_server.assert_called_once_with(mock.ANY, mock.ANY, mock.ANY,
                                            port=mock.ANY, host=mock.ANY,
                                            use_ssl=True)

        self.assertTrue(mock_loader.called)


class OSCompatibilityTestCase(test.TestCase):
    def _test_service_launcher(self, fake_os):
        # Note(lpetrut): The cinder-volume service needs to be spawned
        # differently on Windows due to an eventlet bug. For this reason,
        # we must check the process launcher used.
        fake_process_launcher = mock.MagicMock()
        with mock.patch('os.name', fake_os):
            with mock.patch('cinder.service.process_launcher',
                            fake_process_launcher):
                launcher = service.get_launcher()
                if fake_os == 'nt':
                    self.assertEqual(service.Launcher, type(launcher))
                else:
                    self.assertEqual(fake_process_launcher(), launcher)

    def test_process_launcher_on_windows(self):
        self._test_service_launcher('nt')

    def test_process_launcher_on_linux(self):
        self._test_service_launcher('posix')


class WindowsProcessLauncherTestCase(test.TestCase):
    @mock.patch.object(service, 'os_win_utilsfactory', create=True)
    @mock.patch('oslo_service.service.SignalHandler')
    def setUp(self, mock_signal_handler_cls, mock_utilsfactory):
        super(WindowsProcessLauncherTestCase, self).setUp()

        self._signal_handler = mock_signal_handler_cls.return_value
        self._processutils = mock_utilsfactory.get_processutils.return_value

        self._launcher = service.WindowsProcessLauncher()

    def test_setup_signal_handlers(self):
        exp_signal_map = {'SIGINT': self._launcher._terminate,
                          'SIGTERM': self._launcher._terminate}
        self._signal_handler.add_handler.assert_has_calls(
            [mock.call(signal, handler)
             for signal, handler in exp_signal_map.items()],
            any_order=True)

    @mock.patch('sys.exit')
    def test_terminate_handler(self, mock_exit):
        self._launcher._terminate(mock.sentinel.signum, mock.sentinel.frame)
        mock_exit.assert_called_once_with(1)

    @mock.patch('subprocess.Popen')
    def test_launch(self, mock_popen):
        mock_workers = [mock.Mock(), mock.Mock(), mock.Mock()]

        mock_popen.side_effect = mock_workers
        self._processutils.kill_process_on_job_close.side_effect = [
            exception.CinderException, None, None]

        # We expect the first process to be cleaned up after failing
        # to setup a job object.
        self.assertRaises(exception.CinderException,
                          self._launcher.add_process,
                          mock.sentinel.cmd1)
        mock_workers[0].kill.assert_called_once_with()

        self._launcher.add_process(mock.sentinel.cmd2)
        self._launcher.add_process(mock.sentinel.cmd3)

        mock_popen.assert_has_calls(
            [mock.call(cmd)
             for cmd in [mock.sentinel.cmd1,
                         mock.sentinel.cmd2,
                         mock.sentinel.cmd3]])
        self._processutils.kill_process_on_job_close.assert_has_calls(
            [mock.call(worker.pid) for worker in mock_workers[1:]])

        self._launcher.wait()

        wait_processes = self._processutils.wait_for_multiple_processes
        wait_processes.assert_called_once_with(
            [worker.pid for worker in mock_workers[1:]],
            wait_all=True)
