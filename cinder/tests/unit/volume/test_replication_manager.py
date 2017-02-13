# Copyright (c) 2016 Red Hat, Inc.
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

import ddt

import mock

from oslo_config import cfg
from oslo_utils import timeutils

from cinder.common import constants
from cinder import exception
from cinder import objects
from cinder.objects import fields
from cinder.tests.unit import fake_service
from cinder.tests.unit import utils
from cinder.tests.unit import volume as base
import cinder.volume
from cinder.volume import manager
from cinder.volume import rpcapi as volume_rpcapi


CONF = cfg.CONF


@ddt.ddt
class ReplicationTestCase(base.BaseVolumeTestCase):
    def setUp(self):
        super(ReplicationTestCase, self).setUp()
        self.host = 'host@backend#pool'
        self.manager = manager.VolumeManager(host=self.host)

    @mock.patch('cinder.objects.VolumeList.get_all')
    @mock.patch('cinder.volume.driver.BaseVD.failover_host',
                side_effect=exception.InvalidReplicationTarget(''))
    @ddt.data(('backend2', 'default', fields.ReplicationStatus.FAILED_OVER),
              ('backend2', 'backend3', fields.ReplicationStatus.FAILED_OVER),
              (None, 'backend2', fields.ReplicationStatus.ENABLED),
              ('', 'backend2', fields.ReplicationStatus.ENABLED))
    @ddt.unpack
    def test_failover_host_invalid_target(self, svc_backend, new_backend,
                                          expected, mock_failover,
                                          mock_getall):
        """Test replication failover_host with invalid_target.

        When failingover fails due to an invalid target exception we return
        replication_status to its previous status, and we decide what that is
        depending on the currect active backend.
        """
        svc = utils.create_service(
            self.context,
            {'host': self.host,
             'binary': constants.VOLUME_BINARY,
             'active_backend_id': svc_backend,
             'replication_status': fields.ReplicationStatus.FAILING_OVER})

        self.manager.failover_host(self.context, new_backend)
        mock_getall.assert_called_once_with(self.context,
                                            filters={'host': self.host})
        mock_failover.assert_called_once_with(self.context,
                                              mock_getall.return_value,
                                              secondary_id=new_backend)

        db_svc = objects.Service.get_by_id(self.context, svc.id)
        self.assertEqual(expected, db_svc.replication_status)

    @mock.patch('cinder.volume.driver.BaseVD.failover_host',
                mock.Mock(side_effect=exception.VolumeDriverException('')))
    def test_failover_host_driver_exception(self):
        svc = utils.create_service(
            self.context,
            {'host': self.host,
             'binary': constants.VOLUME_BINARY,
             'active_backend_id': None,
             'replication_status': fields.ReplicationStatus.FAILING_OVER})

        self.manager.failover_host(self.context, mock.sentinel.backend_id)

        db_svc = objects.Service.get_by_id(self.context, svc.id)
        self.assertEqual(fields.ReplicationStatus.FAILOVER_ERROR,
                         db_svc.replication_status)

    @mock.patch('cinder.objects.Service.is_up', True)
    @mock.patch.object(volume_rpcapi.VolumeAPI, 'failover')
    @mock.patch.object(cinder.db, 'conditional_update')
    @mock.patch.object(objects.ServiceList, 'get_all')
    def test_failover(self, mock_get_all, mock_db_update, mock_failover):
        """Test replication failover."""

        service = fake_service.fake_service_obj(self.context,
                                                binary='cinder-volume')
        mock_get_all.return_value = [service]
        mock_db_update.return_value = {'replication_status': 'enabled'}
        volume_api = cinder.volume.api.API()
        volume_api.failover(self.context, host=CONF.host, cluster_name=None)
        mock_failover.assert_called_once_with(self.context, service, None)

    @mock.patch.object(volume_rpcapi.VolumeAPI, 'failover')
    @mock.patch.object(cinder.db, 'conditional_update')
    @mock.patch.object(cinder.db, 'service_get_all')
    def test_failover_unexpected_status(self, mock_db_get_all, mock_db_update,
                                        mock_failover):
        """Test replication failover unxepected status."""

        mock_db_get_all.return_value = [fake_service.fake_service_obj(
            self.context,
            binary='cinder-volume')]
        mock_db_update.return_value = None
        volume_api = cinder.volume.api.API()
        self.assertRaises(exception.InvalidInput,
                          volume_api.failover,
                          self.context,
                          host=CONF.host,
                          cluster_name=None)

    @mock.patch.object(volume_rpcapi.VolumeAPI, 'freeze_host')
    @mock.patch.object(cinder.db, 'conditional_update', return_value=1)
    @mock.patch.object(cinder.objects.ServiceList, 'get_all')
    def test_freeze_host(self, mock_get_all, mock_db_update,
                         mock_freeze):
        """Test replication freeze_host."""

        service = fake_service.fake_service_obj(self.context,
                                                binary='cinder-volume')
        mock_get_all.return_value = [service]
        mock_freeze.return_value = True
        volume_api = cinder.volume.api.API()
        volume_api.freeze_host(self.context, host=CONF.host, cluster_name=None)
        mock_freeze.assert_called_once_with(self.context, service)

    @mock.patch.object(volume_rpcapi.VolumeAPI, 'freeze_host')
    @mock.patch.object(cinder.db, 'conditional_update')
    @mock.patch.object(cinder.db, 'service_get_all')
    def test_freeze_host_unexpected_status(self, mock_get_all,
                                           mock_db_update,
                                           mock_freeze):
        """Test replication freeze_host unexpected status."""

        mock_get_all.return_value = [fake_service.fake_service_obj(
            self.context,
            binary='cinder-volume')]
        mock_db_update.return_value = None
        volume_api = cinder.volume.api.API()
        self.assertRaises(exception.InvalidInput,
                          volume_api.freeze_host,
                          self.context,
                          host=CONF.host,
                          cluster_name=None)

    @mock.patch.object(volume_rpcapi.VolumeAPI, 'thaw_host')
    @mock.patch.object(cinder.db, 'conditional_update', return_value=1)
    @mock.patch.object(cinder.objects.ServiceList, 'get_all')
    def test_thaw_host(self, mock_get_all, mock_db_update,
                       mock_thaw):
        """Test replication thaw_host."""

        service = fake_service.fake_service_obj(self.context,
                                                binary='cinder-volume')
        mock_get_all.return_value = [service]
        mock_thaw.return_value = True
        volume_api = cinder.volume.api.API()
        volume_api.thaw_host(self.context, host=CONF.host, cluster_name=None)
        mock_thaw.assert_called_once_with(self.context, service)

    @mock.patch.object(volume_rpcapi.VolumeAPI, 'thaw_host')
    @mock.patch.object(cinder.db, 'conditional_update')
    @mock.patch.object(cinder.db, 'service_get_all')
    def test_thaw_host_unexpected_status(self, mock_get_all,
                                         mock_db_update,
                                         mock_thaw):
        """Test replication thaw_host unexpected status."""

        mock_get_all.return_value = [fake_service.fake_service_obj(
            self.context,
            binary='cinder-volume')]
        mock_db_update.return_value = None
        volume_api = cinder.volume.api.API()
        self.assertRaises(exception.InvalidInput,
                          volume_api.thaw_host,
                          self.context,
                          host=CONF.host, cluster_name=None)

    @mock.patch('cinder.volume.driver.BaseVD.failover_completed')
    def test_failover_completed(self, completed_mock):
        rep_field = fields.ReplicationStatus
        svc = objects.Service(self.context, host=self.volume.host,
                              binary=constants.VOLUME_BINARY,
                              replication_status=rep_field.ENABLED)
        svc.create()
        self.volume.failover_completed(
            self.context,
            {'active_backend_id': 'secondary',
             'replication_status': rep_field.FAILED_OVER})
        service = objects.Service.get_by_id(self.context, svc.id)
        self.assertEqual('secondary', service.active_backend_id)
        self.assertEqual('failed-over', service.replication_status)
        completed_mock.assert_called_once_with(self.context, 'secondary')

    @mock.patch('cinder.volume.driver.BaseVD.failover_completed', wraps=True)
    def test_failover_completed_driver_failure(self, completed_mock):
        rep_field = fields.ReplicationStatus
        svc = objects.Service(self.context, host=self.volume.host,
                              binary=constants.VOLUME_BINARY,
                              replication_status=rep_field.ENABLED)
        svc.create()
        self.volume.failover_completed(
            self.context,
            {'active_backend_id': 'secondary',
             'replication_status': rep_field.FAILED_OVER})
        service = objects.Service.get_by_id(self.context, svc.id)
        self.assertEqual('secondary', service.active_backend_id)
        self.assertEqual(rep_field.ERROR, service.replication_status)
        self.assertTrue(service.disabled)
        self.assertIsNotNone(service.disabled_reason)
        completed_mock.assert_called_once_with(self.context, 'secondary')

    @mock.patch('cinder.volume.rpcapi.VolumeAPI.failover_completed')
    def test_finish_failover_non_clustered(self, completed_mock):
        svc = mock.Mock(is_clustered=None)
        self.volume.finish_failover(self.context, svc, mock.sentinel.updates)
        svc.update.assert_called_once_with(mock.sentinel.updates)
        svc.save.assert_called_once_with()
        completed_mock.assert_not_called()

    @mock.patch('cinder.volume.rpcapi.VolumeAPI.failover_completed')
    def test_finish_failover_clustered(self, completed_mock):
        svc = mock.Mock(cluster_name='cluster_name')
        updates = {'status': 'error'}
        self.volume.finish_failover(self.context, svc, updates)
        completed_mock.assert_called_once_with(self.context, svc, updates)
        svc.cluster.status = 'error'
        svc.cluster.save.assert_called_once()

    @ddt.data(None, 'cluster_name')
    @mock.patch('cinder.volume.manager.VolumeManager.finish_failover')
    @mock.patch('cinder.volume.manager.VolumeManager._get_my_volumes')
    def test_failover_manager(self, cluster, get_vols_mock, finish_mock):
        """Test manager's failover method for clustered and not clustered."""
        rep_field = fields.ReplicationStatus
        svc = objects.Service(self.context, host=self.volume.host,
                              binary=constants.VOLUME_BINARY,
                              cluster_name=cluster,
                              replication_status=rep_field.ENABLED)
        svc.create()

        vol = objects.Volume(self.context, host=self.volume.host)
        vol.create()

        get_vols_mock.return_value = [vol]

        with mock.patch.object(self.volume, 'driver') as driver:
            called, not_called = driver.failover_host, driver.failover
            if cluster:
                called, not_called = not_called, called

            called.return_value = ('secondary', [{'volume_id': vol.id,
                                   'updates': {'status': 'error'}}])

            self.volume.failover(self.context,
                                 secondary_backend_id='secondary')

        not_called.assert_not_called()
        called.assert_called_once_with(self.context, [vol],
                                       secondary_id='secondary')

        expected_update = {'replication_status': rep_field.FAILED_OVER,
                           'active_backend_id': 'secondary',
                           'disabled': True,
                           'disabled_reason': 'failed-over'}
        finish_mock.assert_called_once_with(self.context, svc, expected_update)

        volume = objects.Volume.get_by_id(self.context, vol.id)
        self.assertEqual('error', volume.status)

    @ddt.data(('host1', None), (None, 'mycluster'))
    @ddt.unpack
    def test_failover_api_fail_multiple_results(self, host, cluster):
        """Fail if we try to failover multiple backends in the same request."""
        rep_field = fields.ReplicationStatus
        clusters = [
            objects.Cluster(self.context,
                            name='mycluster@backend1',
                            replication_status=rep_field.ENABLED,
                            binary=constants.VOLUME_BINARY),
            objects.Cluster(self.context,
                            name='mycluster@backend2',
                            replication_status=rep_field.ENABLED,
                            binary=constants.VOLUME_BINARY)
        ]
        clusters[0].create()
        clusters[1].create()
        services = [
            objects.Service(self.context, host='host1@backend1',
                            cluster_name=clusters[0].name,
                            replication_status=rep_field.ENABLED,
                            binary=constants.VOLUME_BINARY),
            objects.Service(self.context, host='host1@backend2',
                            cluster_name=clusters[1].name,
                            replication_status=rep_field.ENABLED,
                            binary=constants.VOLUME_BINARY),
        ]
        services[0].create()
        services[1].create()
        self.assertRaises(exception.Invalid,
                          self.volume_api.failover, self.context, host,
                          cluster)

    def test_failover_api_not_found(self):
        self.assertRaises(exception.ServiceNotFound, self.volume_api.failover,
                          self.context, 'host1', None)

    @mock.patch('cinder.volume.rpcapi.VolumeAPI.failover')
    def test_failover_api_success_multiple_results(self, failover_mock):
        """Succeed to failover multiple services for the same backend."""
        rep_field = fields.ReplicationStatus
        cluster_name = 'mycluster@backend1'
        cluster = objects.Cluster(self.context,
                                  name=cluster_name,
                                  replication_status=rep_field.ENABLED,
                                  binary=constants.VOLUME_BINARY)
        cluster.create()
        services = [
            objects.Service(self.context, host='host1@backend1',
                            cluster_name=cluster_name,
                            replication_status=rep_field.ENABLED,
                            binary=constants.VOLUME_BINARY),
            objects.Service(self.context, host='host2@backend1',
                            cluster_name=cluster_name,
                            replication_status=rep_field.ENABLED,
                            binary=constants.VOLUME_BINARY),
        ]
        services[0].create()
        services[1].create()

        self.volume_api.failover(self.context, None, cluster_name,
                                 mock.sentinel.secondary_id)

        for service in services + [cluster]:
            self.assertEqual(rep_field.ENABLED, service.replication_status)
            service.refresh()
            self.assertEqual(rep_field.FAILING_OVER,
                             service.replication_status)

        failover_mock.assert_called_once_with(self.context, mock.ANY,
                                              mock.sentinel.secondary_id)
        self.assertEqual(services[0].id, failover_mock.call_args[0][1].id)

    @mock.patch('cinder.volume.rpcapi.VolumeAPI.failover')
    def test_failover_api_success_multiple_results_not_updated(self,
                                                               failover_mock):
        """Succeed to failover even if a service is not updated."""
        rep_field = fields.ReplicationStatus
        cluster_name = 'mycluster@backend1'
        cluster = objects.Cluster(self.context,
                                  name=cluster_name,
                                  replication_status=rep_field.ENABLED,
                                  binary=constants.VOLUME_BINARY)
        cluster.create()
        services = [
            objects.Service(self.context, host='host1@backend1',
                            cluster_name=cluster_name,
                            replication_status=rep_field.ENABLED,
                            binary=constants.VOLUME_BINARY),
            objects.Service(self.context, host='host2@backend1',
                            cluster_name=cluster_name,
                            replication_status=rep_field.ERROR,
                            binary=constants.VOLUME_BINARY),
        ]
        services[0].create()
        services[1].create()

        self.volume_api.failover(self.context, None, cluster_name,
                                 mock.sentinel.secondary_id)

        for service in services[:1] + [cluster]:
            service.refresh()
            self.assertEqual(rep_field.FAILING_OVER,
                             service.replication_status)

        services[1].refresh()
        self.assertEqual(rep_field.ERROR, services[1].replication_status)

        failover_mock.assert_called_once_with(self.context, mock.ANY,
                                              mock.sentinel.secondary_id)
        self.assertEqual(services[0].id, failover_mock.call_args[0][1].id)

    @mock.patch('cinder.volume.rpcapi.VolumeAPI.failover')
    def test_failover_api_fail_multiple_results_not_updated(self,
                                                            failover_mock):
        """Fail if none of the services could be updated."""
        rep_field = fields.ReplicationStatus
        cluster_name = 'mycluster@backend1'
        cluster = objects.Cluster(self.context,
                                  name=cluster_name,
                                  replication_status=rep_field.ENABLED,
                                  binary=constants.VOLUME_BINARY)
        cluster.create()
        down_time = timeutils.datetime.datetime(1970, 1, 1)
        services = [
            # This service is down
            objects.Service(self.context, host='host1@backend1',
                            cluster_name=cluster_name,
                            replication_status=rep_field.ENABLED,
                            created_at=down_time,
                            updated_at=down_time,
                            modified_at=down_time,
                            binary=constants.VOLUME_BINARY),
            # This service is not with the right replication status
            objects.Service(self.context, host='host2@backend1',
                            cluster_name=cluster_name,
                            replication_status=rep_field.ERROR,
                            binary=constants.VOLUME_BINARY),
        ]
        services[0].create()
        services[1].create()

        self.assertRaises(exception.InvalidInput,
                          self.volume_api.failover, self.context, None,
                          cluster_name, mock.sentinel.secondary_id)

        for service in services:
            svc = objects.Service.get_by_id(self.context, service.id)
            self.assertEqual(service.replication_status,
                             svc.replication_status)

        cluster.refresh()
        self.assertEqual(rep_field.ENABLED, cluster.replication_status)

        failover_mock.assert_not_called()
