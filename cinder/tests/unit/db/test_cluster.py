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

"""Tests for cluster table related operations."""

import datetime

import mock
from oslo_config import cfg
from oslo_utils import timeutils
from sqlalchemy.orm import exc

from cinder import db
from cinder import exception
from cinder.tests.unit import test_db_api


CONF = cfg.CONF


class ClusterTestCase(test_db_api.BaseTest):
    """Unit tests for cinder.db.api.cluster_*."""

    def _default_cluster_values(self):
        return {
            'name': 'cluster_name',
            'binary': 'cinder-volume',
            'disabled': False,
            'disabled_reason': None,
            'deleted': False,
            'updated_at': None,
            'deleted_at': None,
        }

    def _create_cluster(self, **values):
        create_values = self._default_cluster_values()
        create_values.update(values)
        cluster = db.cluster_create(self.ctxt, create_values)
        return db.cluster_get(self.ctxt, cluster.id, services_summary=True)

    def _create_populated_cluster(self, num_services, num_down_svcs=0,
                                  **values):
        """Helper method that creates a cluster with up and down services."""
        up_time = timeutils.utcnow()
        down_time = (up_time -
                     datetime.timedelta(seconds=CONF.service_down_time + 1))
        cluster = self._create_cluster(**values)

        svcs = [
            db.service_create(
                self.ctxt,
                {'cluster_name': cluster.name,
                 'updated_at': down_time if i < num_down_svcs else up_time})
            for i in range(num_services)
        ]
        return cluster, svcs

    def test_cluster_create_and_get(self):
        """Basic cluster creation test."""
        values = self._default_cluster_values()
        cluster = db.cluster_create(self.ctxt, values)
        values['last_heartbeat'] = None
        self.assertEqual(0, cluster.race_preventer)
        for k, v in values.items():
            self.assertEqual(v, getattr(cluster, k))

        db_cluster = db.cluster_get(self.ctxt, cluster.id,
                                    services_summary=True)
        for k, v in values.items():
            self.assertEqual(v, getattr(db_cluster, k))
        self.assertEqual(0, db_cluster.race_preventer)

    def test_cluster_create_cfg_disabled(self):
        """Test that create uses enable_new_services configuration option."""
        self.override_config('enable_new_services', False)
        cluster = self._create_cluster(disabled=None)
        self.assertTrue(cluster.disabled)

    def test_cluster_create_disabled_preference(self):
        """Test that provided disabled value has highest priority on create."""
        self.override_config('enable_new_services', False)
        cluster = self._create_cluster()
        self.assertFalse(cluster.disabled)

    def test_cluster_create_duplicate(self):
        """Test that unique constraints are working.

        To remove potential races on creation we have a constraint set on name
        and race_preventer fields, and we set value on creation to 0, so 2
        clusters with the same name will fail this constraint.  On deletion we
        change this field to the same value as the id which will be unique and
        will not conflict with the creation of another cluster with the same
        name.
        """
        cluster = self._create_cluster()
        self.assertRaises(exception.ClusterExists,
                          self._create_cluster,
                          name=cluster.name)

    def test_cluster_create_not_duplicate(self):
        """Test that unique constraints will work with delete operation.

        To remove potential races on creation we have a constraint set on name
        and race_preventer fields, and we set value on creation to 0, so 2
        clusters with the same name will fail this constraint.  On deletion we
        change this field to the same value as the id which will be unique and
        will not conflict with the creation of another cluster with the same
        name.
        """
        cluster = self._create_cluster()
        self.assertIsNone(db.cluster_destroy(self.ctxt, cluster.id))
        self.assertIsNotNone(self._create_cluster(name=cluster.name))

    def test_cluster_get_fail(self):
        """Test that cluster get will fail if the cluster doesn't exists."""
        self._create_cluster(name='cluster@backend')
        self.assertRaises(exception.ClusterNotFound,
                          db.cluster_get, self.ctxt, 'name=cluster@backend2')

    def test_cluster_get_by_name(self):
        """Getting a cluster by name will include backends if not specified."""
        cluster = self._create_cluster(name='cluster@backend')
        # Get without the backend
        db_cluster = db.cluster_get(self.ctxt, name='cluster')
        self.assertEqual(cluster.id, db_cluster.id)
        # Get with the backend detail
        db_cluster = db.cluster_get(self.ctxt, name='cluster@backend')
        self.assertEqual(cluster.id, db_cluster.id)

    def test_cluster_get_without_summary(self):
        """Test getting cluster without summary information."""
        cluster = self._create_cluster()
        db_cluster = db.cluster_get(self.ctxt, cluster.id)
        self.assertRaises(exc.DetachedInstanceError,
                          getattr, db_cluster, 'num_hosts')
        self.assertRaises(exc.DetachedInstanceError,
                          getattr, db_cluster, 'num_down_hosts')
        self.assertIsNone(db_cluster.last_heartbeat)

    def test_cluster_get_with_summary_empty_cluster(self):
        """Test getting empty cluster with summary information."""
        cluster = self._create_cluster()
        db_cluster = db.cluster_get(self.ctxt, cluster.id,
                                    services_summary=True)
        self.assertEqual(0, db_cluster.num_hosts)
        self.assertEqual(0, db_cluster.num_down_hosts)
        self.assertIsNone(db_cluster.last_heartbeat)

    def test_cluster_get_with_summary(self):
        """Test getting cluster with summary information."""
        cluster, svcs = self._create_populated_cluster(3, 1)
        db_cluster = db.cluster_get(self.ctxt, cluster.id,
                                    services_summary=True)
        self.assertEqual(3, db_cluster.num_hosts)
        self.assertEqual(1, db_cluster.num_down_hosts)
        self.assertEqual(svcs[1].updated_at, db_cluster.last_heartbeat)

    def test_cluster_get_is_up_on_empty_cluster(self):
        """Test is_up filter works on empty clusters."""
        cluster = self._create_cluster()
        db_cluster = db.cluster_get(self.ctxt, cluster.id, is_up=False)
        self.assertEqual(cluster.id, db_cluster.id)
        self.assertRaises(exception.ClusterNotFound,
                          db.cluster_get, self.ctxt, cluster.id, is_up=True)

    def test_cluster_get_services_on_empty_cluster(self):
        """Test get_services filter works on empty clusters."""
        cluster = self._create_cluster()
        db_cluster = db.cluster_get(self.ctxt, cluster.id, get_services=True)
        self.assertEqual(cluster.id, db_cluster.id)
        self.assertListEqual([], db_cluster.services)

    def test_cluster_get_services(self):
        """Test services is properly populated on non empty cluster."""
        # We create another cluster to see we do the selection correctly
        self._create_populated_cluster(2, name='cluster2')
        # We create our cluster with 2 up nodes and 1 down
        cluster, svcs = self._create_populated_cluster(3, 1)
        # Add a deleted service to the cluster
        db.service_create(self.ctxt,
                          {'cluster_name': cluster.name,
                           'deleted': True})
        db_cluster = db.cluster_get(self.ctxt, name=cluster.name,
                                    get_services=True)
        self.assertEqual(3, len(db_cluster.services))
        self.assertSetEqual({svc.id for svc in svcs},
                            {svc.id for svc in db_cluster.services})

    def test_cluster_get_is_up_all_are_down(self):
        """Test that is_up filter works when all services are down."""
        cluster, svcs = self._create_populated_cluster(3, 3)
        self.assertRaises(exception.ClusterNotFound,
                          db.cluster_get, self.ctxt, cluster.id, is_up=True)
        db_cluster = db.cluster_get(self.ctxt, name=cluster.name, is_up=False)
        self.assertEqual(cluster.id, db_cluster.id)

    def test_cluster_get_by_num_down_hosts(self):
        """Test cluster_get by subquery field num_down_hosts."""
        cluster, svcs = self._create_populated_cluster(3, 2)
        result = db.cluster_get(self.ctxt, num_down_hosts=2)
        self.assertEqual(cluster.id, result.id)

    def test_cluster_get_by_num_hosts(self):
        """Test cluster_get by subquery field num_hosts."""
        cluster, svcs = self._create_populated_cluster(3, 2)
        result = db.cluster_get(self.ctxt, num_hosts=3)
        self.assertEqual(cluster.id, result.id)

    def test_cluster_destroy(self):
        """Test basic cluster destroy."""
        cluster = self._create_cluster()
        # On creation race_preventer is marked with a 0
        self.assertEqual(0, cluster.race_preventer)
        db.cluster_destroy(self.ctxt, cluster.id)
        db_cluster = db.cluster_get(self.ctxt, cluster.id, read_deleted='yes')
        self.assertTrue(db_cluster.deleted)
        self.assertIsNotNone(db_cluster.deleted_at)
        # On deletion race_preventer is marked with the id
        self.assertEqual(cluster.id, db_cluster.race_preventer)

    def test_cluster_destroy_non_existent(self):
        """Test destroying non existent cluster."""
        self.assertRaises(exception.ClusterNotFound,
                          db.cluster_destroy, self.ctxt, 0)

    def test_cluster_destroy_has_services(self):
        """Test that we cannot delete a cluster with non deleted services."""
        cluster, svcs = self._create_populated_cluster(3, 1)
        self.assertRaises(exception.ClusterHasHosts,
                          db.cluster_destroy, self.ctxt, cluster.id)

    def test_cluster_update_non_existent(self):
        """Test that we raise an exception on updating non existent cluster."""
        self.assertRaises(exception.ClusterNotFound,
                          db.cluster_update, self.ctxt, 0, {'disabled': True})

    def test_cluster_update(self):
        """Test basic cluster update."""
        cluster = self._create_cluster()
        self.assertFalse(cluster.disabled)
        db.cluster_update(self.ctxt, cluster.id, {'disabled': True})
        db_cluster = db.cluster_get(self.ctxt, cluster.id)
        self.assertTrue(db_cluster.disabled)

    def test_cluster_get_all_empty(self):
        """Test basic empty cluster get_all."""
        self.assertListEqual([], db.cluster_get_all(self.ctxt))

    def test_cluster_get_all_matches(self):
        """Basic test of get_all with a matching filter."""
        cluster1, svcs = self._create_populated_cluster(3, 1)
        cluster2, svcs = self._create_populated_cluster(3, 2, name='cluster2')
        cluster3, svcs = self._create_populated_cluster(3, 3, name='cluster3')

        expected = {cluster1.id, cluster2.id}
        result = db.cluster_get_all(self.ctxt, is_up=True)
        self.assertEqual(len(expected), len(result))
        self.assertSetEqual(expected, {cluster.id for cluster in result})

    def test_cluster_get_all_no_match(self):
        """Basic test of get_all with a non matching filter."""
        cluster1, svcs = self._create_populated_cluster(3, 3)
        result = db.cluster_get_all(self.ctxt, is_up=True)
        self.assertListEqual([], result)

    @mock.patch('cinder.db.sqlalchemy.api._cluster_query')
    def test_cluster_get_all_passes_parameters(self, cluster_query_mock):
        """Test that get_all passes all parameters.

        Since we have already tested all filters and parameters with
        cluster_get method all we have to do for get_all is to check that we
        are passing them to the query building method.
        """
        args = (mock.sentinel.read_deleted, mock.sentinel.get_services,
                mock.sentinel.services_summary, mock.sentinel.is_up,
                mock.sentinel.name_match_level)
        filters = {'session': mock.sentinel.session,
                   'name': mock.sentinel.name,
                   'disabled': mock.sentinel.disabled,
                   'disabled_reason': mock.sentinel.disabled_reason,
                   'race_preventer': mock.sentinel.race_preventer,
                   'last_heartbeat': mock.sentinel.last_heartbeat,
                   'num_hosts': mock.sentinel.num_hosts,
                   'num_down_hosts': mock.sentinel.num_down_hosts}
        db.cluster_get_all(self.ctxt, *args, **filters)
        cluster_query_mock.assert_called_once_with(self.ctxt, *args, **filters)
