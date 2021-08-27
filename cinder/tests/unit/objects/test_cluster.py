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

from unittest import mock

import ddt
from oslo_utils import timeutils

import cinder.db
from cinder.db.sqlalchemy import models
from cinder import objects
from cinder.tests.unit import fake_cluster
from cinder.tests.unit import objects as test_objects
from cinder import utils


def _get_filters_sentinel():
    return {'session': mock.sentinel.session,
            'read_deleted': mock.sentinel.read_deleted,
            'get_services': mock.sentinel.get_services,
            'services_summary': mock.sentinel.services_summary,
            'name': mock.sentinel.name,
            'binary': mock.sentinel.binary,
            'is_up': mock.sentinel.is_up,
            'disabled': mock.sentinel.disabled,
            'disabled_reason': mock.sentinel.disabled_reason,
            'race_preventer': mock.sentinel.race_preventer,
            'last_heartbeat': mock.sentinel.last_heartbeat,
            'num_hosts': mock.sentinel.num_hosts,
            'name_match_level': mock.sentinel.name_match_level,
            'num_down_hosts': mock.sentinel.num_down_hosts}


@ddt.ddt
class TestCluster(test_objects.BaseObjectsTestCase):
    """Test Cluster Versioned Object methods."""
    cluster = fake_cluster.fake_cluster_orm()

    @mock.patch('cinder.db.sqlalchemy.api.cluster_get', return_value=cluster)
    def test_get_by_id(self, cluster_get_mock):
        filters = _get_filters_sentinel()
        cluster = objects.Cluster.get_by_id(self.context,
                                            mock.sentinel.cluster_id,
                                            **filters)
        self.assertIsInstance(cluster, objects.Cluster)
        self._compare(self, self.cluster, cluster)
        cluster_get_mock.assert_called_once_with(self.context,
                                                 mock.sentinel.cluster_id,
                                                 **filters)

    @mock.patch('cinder.db.sqlalchemy.api.cluster_create',
                return_value=cluster)
    def test_create(self, cluster_create_mock):
        cluster = objects.Cluster(context=self.context, name='cluster_name')
        cluster.create()
        self.assertEqual(self.cluster.id, cluster.id)
        cluster_create_mock.assert_called_once_with(self.context,
                                                    {'name': 'cluster_name'})

    @mock.patch('cinder.db.sqlalchemy.api.cluster_update',
                return_value=cluster)
    def test_save(self, cluster_update_mock):
        cluster = fake_cluster.fake_cluster_ovo(self.context)
        cluster.disabled = True
        cluster.save()
        cluster_update_mock.assert_called_once_with(self.context, cluster.id,
                                                    {'disabled': True})

    @mock.patch('cinder.db.sqlalchemy.api.cluster_destroy')
    def test_destroy(self, cluster_destroy_mock):
        cluster = fake_cluster.fake_cluster_ovo(self.context)
        cluster.destroy()
        cluster_destroy_mock.assert_called_once_with(mock.ANY, cluster.id)

    @mock.patch('cinder.db.sqlalchemy.api.cluster_get', return_value=cluster)
    def test_refresh(self, cluster_get_mock):
        cluster = fake_cluster.fake_cluster_ovo(self.context)
        cluster.refresh()
        cluster_get_mock.assert_called_once_with(self.context, cluster.id)

    def test_is_up_no_last_hearbeat(self):
        cluster = fake_cluster.fake_cluster_ovo(self.context,
                                                last_heartbeat=None)
        self.assertFalse(bool(cluster.is_up))

    def test_is_up(self):
        cluster = fake_cluster.fake_cluster_ovo(
            self.context,
            last_heartbeat=timeutils.utcnow(with_timezone=True))
        self.assertTrue(cluster.is_up)

    def test_is_up_limit(self):
        limit_expired = (utils.service_expired_time(True) +
                         timeutils.datetime.timedelta(seconds=1))
        cluster = fake_cluster.fake_cluster_ovo(self.context,
                                                last_heartbeat=limit_expired)
        self.assertTrue(cluster.is_up)

    def test_is_up_down(self):
        expired_time = (utils.service_expired_time(True) -
                        timeutils.datetime.timedelta(seconds=1))
        cluster = fake_cluster.fake_cluster_ovo(self.context,
                                                last_heartbeat=expired_time)
        self.assertFalse(cluster.is_up)

    @mock.patch.object(cinder.db, 'conditional_update')
    def test_reset_service_replication(self, mock_update):
        cluster = fake_cluster.fake_cluster_ovo(self.context)
        cluster.reset_service_replication()
        mock_update.assert_called_with(self.context, models.Service,
                                       {'replication_status': 'enabled',
                                        'active_backend_id': None},
                                       {'cluster_name': cluster.name})


class TestClusterList(test_objects.BaseObjectsTestCase):
    """Test ClusterList Versioned Object methods."""

    @mock.patch('cinder.db.sqlalchemy.api.cluster_get_all')
    def test_cluster_get_all(self, cluster_get_all_mock):
        orm_values = [
            fake_cluster.fake_cluster_orm(),
            fake_cluster.fake_cluster_orm(id=2, name='cluster_name2'),
        ]
        cluster_get_all_mock.return_value = orm_values
        filters = _get_filters_sentinel()

        result = objects.ClusterList.get_all(self.context, **filters)

        cluster_get_all_mock.assert_called_once_with(
            self.context, filters.pop('is_up'), filters.pop('get_services'),
            filters.pop('services_summary'), filters.pop('read_deleted'),
            filters.pop('name_match_level'), **filters)
        self.assertEqual(2, len(result))
        for i in range(len(result)):
            self.assertIsInstance(result[i], objects.Cluster)
            self._compare(self, orm_values[i], result[i])
