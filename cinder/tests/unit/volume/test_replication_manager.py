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

import uuid

import ddt

import mock

from oslo_config import cfg
from oslo_utils import timeutils

from cinder.common import constants
from cinder import exception
from cinder import objects
from cinder.objects import fields
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_service
from cinder.tests.unit import utils
from cinder.tests.unit import volume as base
import cinder.volume
from cinder.volume import manager
from cinder.volume import rpcapi as volume_rpcapi
from cinder.volume import utils as vol_utils


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
                                            filters={'host': self.host},
                                            limit=None, offset=None)
        mock_failover.assert_called_once_with(self.context,
                                              [],
                                              secondary_id=new_backend,
                                              groups=[])

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
        """Test replication failover unexpected status."""

        mock_db_get_all.return_value = [fake_service.fake_service_obj(
            self.context,
            binary=constants.VOLUME_BINARY)]
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
                                                binary=constants.VOLUME_BINARY)
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
            binary=constants.VOLUME_BINARY)]
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
                                                binary=constants.VOLUME_BINARY)
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
            binary=constants.VOLUME_BINARY)]
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
                                   'updates': {'status': 'error'}}], [])

            self.volume.failover(self.context,
                                 secondary_backend_id='secondary')

        not_called.assert_not_called()
        called.assert_called_once_with(self.context, [vol],
                                       secondary_id='secondary', groups=[])

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

    def _check_failover_db(self, get_method, expected_results):
        db_data = get_method.get_all(self.context, None)
        db_data = {e.id: e for e in db_data}
        for expected in expected_results:
            id_ = expected['id']
            for key, value in expected.items():
                self.assertEqual(value, getattr(db_data[id_], key),
                                 '(%s) ref=%s != act=%s' % (
                                     key, expected, dict(db_data[id_])))

    def _test_failover_model_updates(self, in_volumes, in_snapshots,
                                     driver_volumes, driver_result,
                                     out_volumes, out_snapshots,
                                     in_groups=None, out_groups=None,
                                     driver_group_result=None,
                                     secondary_id=None):
        host = vol_utils.extract_host(self.manager.host)
        utils.create_service(self.context, {'host': host,
                                            'binary': constants.VOLUME_BINARY})
        for volume in in_volumes:
            utils.create_volume(self.context, self.manager.host, **volume)

        for snapshot in in_snapshots:
            utils.create_snapshot(self.context, **snapshot)

        for group in in_groups:
            utils.create_group(self.context, self.manager.host, **group)

        with mock.patch.object(
                self.manager.driver, 'failover_host',
                return_value=(secondary_id, driver_result,
                              driver_group_result)) as driver_mock:
            self.manager.failover_host(self.context, secondary_id)

            self.assertSetEqual(driver_volumes,
                                {v.id for v in driver_mock.call_args[0][1]})

        self._check_failover_db(objects.VolumeList, out_volumes)
        self._check_failover_db(objects.SnapshotList, out_snapshots)
        self._check_failover_db(objects.GroupList, out_groups)

    @mock.patch('cinder.volume.utils.is_group_a_type')
    def test_failover_host_model_updates(self, mock_group_type):
        status = fields.ReplicationStatus
        mock_group_type.return_value = True
        in_groups = [
            {'id': str(uuid.uuid4()), 'status': 'available',
             'group_type_id': fake.GROUP_TYPE_ID,
             'volume_type_ids': [fake.VOLUME_TYPE_ID],
             'replication_status': status.FAILOVER_ERROR},
            {'id': str(uuid.uuid4()), 'status': 'available',
             'group_type_id': fake.GROUP_TYPE_ID,
             'volume_type_ids': [fake.VOLUME_TYPE_ID],
             'replication_status': status.ENABLED},
        ]
        driver_group_result = [
            {'group_id': in_groups[0]['id'],
             'updates': {'replication_status': status.FAILOVER_ERROR}},
            {'group_id': in_groups[1]['id'],
             'updates': {'replication_status': status.FAILED_OVER}},
        ]
        out_groups = [
            {'id': in_groups[0]['id'], 'status': 'error',
             'replication_status': status.FAILOVER_ERROR},
            {'id': in_groups[1]['id'], 'status': in_groups[1]['status'],
             'replication_status': status.FAILED_OVER},
        ]

        # test volumes
        in_volumes = [
            {'id': str(uuid.uuid4()), 'status': 'available',
             'replication_status': status.DISABLED},
            {'id': str(uuid.uuid4()), 'status': 'in-use',
             'replication_status': status.NOT_CAPABLE},
            {'id': str(uuid.uuid4()), 'status': 'available',
             'replication_status': status.FAILOVER_ERROR},
            {'id': str(uuid.uuid4()), 'status': 'in-use',
             'replication_status': status.ENABLED},
            {'id': str(uuid.uuid4()), 'status': 'available',
             'replication_status': status.FAILOVER_ERROR},
            {'id': str(uuid.uuid4()), 'status': 'in-use',
             'replication_status': status.ENABLED},
            {'id': str(uuid.uuid4()), 'status': 'available',
             'group_id': in_groups[0]['id'],
             'replication_status': status.FAILOVER_ERROR},
            {'id': str(uuid.uuid4()), 'status': 'available',
             'group_id': in_groups[1]['id'],
             'replication_status': status.ENABLED},
        ]
        in_snapshots = [
            {'id': v['id'], 'volume_id': v['id'], 'status': 'available'}
            for v in in_volumes
        ]
        driver_volumes = {
            v['id'] for v in in_volumes
            if v['replication_status'] not in (status.DISABLED,
                                               status.NOT_CAPABLE)}
        driver_result = [
            {'volume_id': in_volumes[3]['id'],
             'updates': {'status': 'error'}},
            {'volume_id': in_volumes[4]['id'],
             'updates': {'replication_status': status.FAILOVER_ERROR}},
            {'volume_id': in_volumes[5]['id'],
             'updates': {'replication_status': status.FAILED_OVER}},
            {'volume_id': in_volumes[6]['id'],
             'updates': {'replication_status': status.FAILOVER_ERROR}},
            {'volume_id': in_volumes[7]['id'],
             'updates': {'replication_status': status.FAILED_OVER}},
        ]
        out_volumes = [
            {'id': in_volumes[0]['id'], 'status': 'error',
             'replication_status': status.NOT_CAPABLE,
             'previous_status': in_volumes[0]['status']},
            {'id': in_volumes[1]['id'], 'status': 'error',
             'replication_status': status.NOT_CAPABLE,
             'previous_status': in_volumes[1]['status']},
            {'id': in_volumes[2]['id'], 'status': in_volumes[2]['status'],
             'replication_status': status.FAILED_OVER},
            {'id': in_volumes[3]['id'], 'status': 'error',
             'previous_status': in_volumes[3]['status'],
             'replication_status': status.FAILOVER_ERROR},
            {'id': in_volumes[4]['id'], 'status': 'error',
             'previous_status': in_volumes[4]['status'],
             'replication_status': status.FAILOVER_ERROR},
            {'id': in_volumes[5]['id'], 'status': in_volumes[5]['status'],
             'replication_status': status.FAILED_OVER},
            {'id': in_volumes[6]['id'], 'status': 'error',
             'previous_status': in_volumes[6]['status'],
             'replication_status': status.FAILOVER_ERROR},
            {'id': in_volumes[7]['id'], 'status': in_volumes[7]['status'],
             'replication_status': status.FAILED_OVER},
        ]
        out_snapshots = [
            {'id': ov['id'],
             'status': 'error' if ov['status'] == 'error' else 'available'}
            for ov in out_volumes
        ]

        self._test_failover_model_updates(in_volumes, in_snapshots,
                                          driver_volumes, driver_result,
                                          out_volumes, out_snapshots,
                                          in_groups, out_groups,
                                          driver_group_result)

    def test_failback_host_model_updates(self):
        status = fields.ReplicationStatus
        # IDs will be overwritten with UUIDs, but they help follow the code
        in_volumes = [
            {'id': 0, 'status': 'available',
             'replication_status': status.DISABLED},
            {'id': 1, 'status': 'in-use',
             'replication_status': status.NOT_CAPABLE},
            {'id': 2, 'status': 'available',
             'replication_status': status.FAILOVER_ERROR},
            {'id': 3, 'status': 'in-use',
             'replication_status': status.ENABLED},
            {'id': 4, 'status': 'available',
             'replication_status': status.FAILOVER_ERROR},
            {'id': 5, 'status': 'in-use',
             'replication_status': status.FAILED_OVER},
        ]
        # Generate real volume IDs
        for volume in in_volumes:
            volume['id'] = str(uuid.uuid4())
        in_snapshots = [
            {'id': in_volumes[0]['id'], 'volume_id': in_volumes[0]['id'],
             'status': fields.SnapshotStatus.ERROR_DELETING},
            {'id': in_volumes[1]['id'], 'volume_id': in_volumes[1]['id'],
             'status': fields.SnapshotStatus.AVAILABLE},
            {'id': in_volumes[2]['id'], 'volume_id': in_volumes[2]['id'],
             'status': fields.SnapshotStatus.CREATING},
            {'id': in_volumes[3]['id'], 'volume_id': in_volumes[3]['id'],
             'status': fields.SnapshotStatus.DELETING},
            {'id': in_volumes[4]['id'], 'volume_id': in_volumes[4]['id'],
             'status': fields.SnapshotStatus.CREATING},
            {'id': in_volumes[5]['id'], 'volume_id': in_volumes[5]['id'],
             'status': fields.SnapshotStatus.CREATING},
        ]
        driver_volumes = {
            v['id'] for v in in_volumes
            if v['replication_status'] not in (status.DISABLED,
                                               status.NOT_CAPABLE)}
        driver_result = [
            {'volume_id': in_volumes[3]['id'],
             'updates': {'status': 'error'}},
            {'volume_id': in_volumes[4]['id'],
             'updates': {'replication_status': status.FAILOVER_ERROR}},
            {'volume_id': in_volumes[5]['id'],
             'updates': {'replication_status': status.FAILED_OVER}},
        ]
        out_volumes = [
            {'id': in_volumes[0]['id'], 'status': in_volumes[0]['status'],
             'replication_status': in_volumes[0]['replication_status'],
             'previous_status': None},
            {'id': in_volumes[1]['id'], 'status': in_volumes[1]['status'],
             'replication_status': in_volumes[1]['replication_status'],
             'previous_status': None},
            {'id': in_volumes[2]['id'], 'status': in_volumes[2]['status'],
             'replication_status': status.ENABLED},
            {'id': in_volumes[3]['id'], 'status': 'error',
             'previous_status': in_volumes[3]['status'],
             'replication_status': status.FAILOVER_ERROR},
            {'id': in_volumes[4]['id'], 'status': 'error',
             'previous_status': in_volumes[4]['status'],
             'replication_status': status.FAILOVER_ERROR},
            {'id': in_volumes[5]['id'], 'status': in_volumes[5]['status'],
             'replication_status': status.ENABLED},
        ]
        # Snapshot status is preserved except for those that error the failback
        out_snapshots = in_snapshots[:]
        out_snapshots[3]['status'] = fields.SnapshotStatus.ERROR
        out_snapshots[4]['status'] = fields.SnapshotStatus.ERROR

        self._test_failover_model_updates(in_volumes, in_snapshots,
                                          driver_volumes, driver_result,
                                          out_volumes, out_snapshots,
                                          [], [], [],
                                          self.manager.FAILBACK_SENTINEL)

    @mock.patch('cinder.utils.log_unsupported_driver_warning', mock.Mock())
    @mock.patch('cinder.utils.require_driver_initialized', mock.Mock())
    def test_init_host_with_rpc_clustered_replication(self):
        # These are not OVOs but ORM instances
        cluster = utils.create_cluster(self.context)
        service = utils.create_service(self.context,
                                       {'cluster_name': cluster.name,
                                        'binary': cluster.binary})
        self.assertNotEqual(fields.ReplicationStatus.ENABLED,
                            cluster.replication_status)
        self.assertNotEqual(fields.ReplicationStatus.ENABLED,
                            service.replication_status)

        vol_manager = manager.VolumeManager(
            'cinder.tests.fake_driver.FakeHAReplicatedLoggingVolumeDriver',
            host=service.host, cluster=cluster.name)
        vol_manager.driver = mock.Mock()
        vol_manager.driver.get_volume_stats.return_value = {
            'replication_enabled': True
        }
        vol_manager.init_host_with_rpc()

        cluster_ovo = objects.Cluster.get_by_id(self.context, cluster.id)
        service_ovo = objects.Service.get_by_id(self.context, service.id)

        self.assertEqual(fields.ReplicationStatus.ENABLED,
                         cluster_ovo.replication_status)
        self.assertEqual(fields.ReplicationStatus.ENABLED,
                         service_ovo.replication_status)
