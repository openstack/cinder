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

import datetime

import ddt
import iso8601
import mock
from oslo_utils import versionutils

from cinder.api import extensions
from cinder.api import microversions as mv
from cinder.api.openstack import api_version_request as api_version
from cinder.api.v3 import clusters
from cinder import context
from cinder import exception
from cinder import test
from cinder.tests.unit import fake_cluster


CLUSTERS = [
    fake_cluster.fake_db_cluster(
        id=1,
        replication_status='error',
        frozen=False,
        active_backend_id='replication1',
        last_heartbeat=datetime.datetime(2016, 6, 1, 2, 46, 28),
        updated_at=datetime.datetime(2016, 6, 1, 2, 46, 28),
        created_at=datetime.datetime(2016, 6, 1, 2, 46, 28)),
    fake_cluster.fake_db_cluster(
        id=2, name='cluster2', num_hosts=2, num_down_hosts=1, disabled=True,
        replication_status='error',
        frozen=True,
        active_backend_id='replication2',
        updated_at=datetime.datetime(2016, 6, 1, 1, 46, 28),
        created_at=datetime.datetime(2016, 6, 1, 1, 46, 28))
]

CLUSTERS_ORM = [fake_cluster.fake_cluster_orm(**kwargs) for kwargs in CLUSTERS]

EXPECTED = [{'created_at': datetime.datetime(2016, 6, 1, 2, 46, 28),
             'disabled_reason': None,
             'last_heartbeat': datetime.datetime(2016, 6, 1, 2, 46, 28),
             'name': 'cluster_name',
             'binary': 'cinder-volume',
             'num_down_hosts': 0,
             'num_hosts': 0,
             'state': 'up',
             'status': 'enabled',
             'replication_status': 'error',
             'frozen': False,
             'active_backend_id': 'replication1',
             'updated_at': datetime.datetime(2016, 6, 1, 2, 46, 28)},
            {'created_at': datetime.datetime(2016, 6, 1, 1, 46, 28),
             'disabled_reason': None,
             'last_heartbeat': '',
             'name': 'cluster2',
             'binary': 'cinder-volume',
             'num_down_hosts': 1,
             'num_hosts': 2,
             'state': 'down',
             'status': 'disabled',
             'replication_status': 'error',
             'frozen': True,
             'active_backend_id': 'replication2',
             'updated_at': datetime.datetime(2016, 6, 1, 1, 46, 28)}]


class FakeRequest(object):
    def __init__(self, is_admin=True, version=mv.CLUSTER_SUPPORT, **kwargs):
        self.GET = kwargs
        self.headers = {'OpenStack-API-Version': 'volume ' + version}
        self.api_version_request = api_version.APIVersionRequest(version)
        self.environ = {
            'cinder.context': context.RequestContext(user_id=None,
                                                     project_id=None,
                                                     is_admin=is_admin,
                                                     read_deleted='no',
                                                     overwrite=False)
        }


def fake_utcnow(with_timezone=False):
    tzinfo = iso8601.UTC if with_timezone else None
    return datetime.datetime(2016, 6, 1, 2, 46, 30, tzinfo=tzinfo)


@ddt.ddt
@mock.patch('oslo_utils.timeutils.utcnow', fake_utcnow)
class ClustersTestCase(test.TestCase):
    """Test Case for Clusters."""
    LIST_FILTERS = ({}, {'is_up': True}, {'disabled': False}, {'num_hosts': 2},
                    {'num_down_hosts': 1}, {'binary': 'cinder-volume'},
                    {'is_up': True, 'disabled': False, 'num_hosts': 2,
                     'num_down_hosts': 1, 'binary': 'cinder-volume'})

    REPLICATION_FILTERS = ({'replication_status': 'error'}, {'frozen': True},
                           {'active_backend_id': 'replication'})

    def _get_expected(self,
                      version=mv.get_prior_version(mv.REPLICATION_CLUSTER)):
        if (versionutils.convert_version_to_tuple(version) >=
                versionutils.convert_version_to_tuple(mv.REPLICATION_CLUSTER)):
            return EXPECTED

        expect = []
        for cluster in EXPECTED:
            cluster = cluster.copy()
            for key in ('replication_status', 'frozen', 'active_backend_id'):
                cluster.pop(key)
            expect.append(cluster)
        return expect

    def setUp(self):
        super(ClustersTestCase, self).setUp()

        self.context = context.get_admin_context()
        self.ext_mgr = extensions.ExtensionManager()
        self.ext_mgr.extensions = {}
        self.controller = clusters.ClusterController(self.ext_mgr)

    @mock.patch('cinder.db.cluster_get_all', return_value=CLUSTERS_ORM)
    def _test_list(self, get_all_mock, detailed, filters=None, expected=None,
                   version=mv.get_prior_version(mv.REPLICATION_CLUSTER)):
        filters = filters or {}
        req = FakeRequest(version=version, **filters)
        method = getattr(self.controller, 'detail' if detailed else 'index')
        clusters = method(req)

        filters = filters.copy()
        filters.setdefault('is_up', None)
        filters.setdefault('read_deleted', 'no')
        self.assertEqual(expected, clusters)
        get_all_mock.assert_called_once_with(
            req.environ['cinder.context'],
            get_services=False,
            services_summary=detailed,
            **filters)

    @ddt.data(*LIST_FILTERS)
    def test_index_detail(self, filters):
        """Verify that we get all clusters with detailed data."""
        expected = {'clusters': self._get_expected()}
        self._test_list(detailed=True, filters=filters, expected=expected)

    @ddt.data(*LIST_FILTERS)
    def test_index_summary(self, filters):
        """Verify that we get all clusters with summary data."""
        expected = {'clusters': [{'name': 'cluster_name',
                                  'binary': 'cinder-volume',
                                  'state': 'up',
                                  'status': 'enabled'},
                                 {'name': 'cluster2',
                                  'binary': 'cinder-volume',
                                  'state': 'down',
                                  'status': 'disabled'}]}
        self._test_list(detailed=False, filters=filters, expected=expected)

    @ddt.data(*REPLICATION_FILTERS)
    def test_index_detail_fail_old(self, filters):
        self.assertRaises(exception.InvalidInput, self._test_list,
                          detailed=True, filters=filters)

    @ddt.data(*REPLICATION_FILTERS)
    def test_index_summary_fail_old(self, filters):
        self.assertRaises(exception.InvalidInput, self._test_list,
                          detailed=False, filters=filters)

    @ddt.data(True, False)
    def test_index_unauthorized(self, detailed):
        """Verify that unauthorized user can't list clusters."""
        self.assertRaises(exception.PolicyNotAuthorized,
                          self._test_list, detailed=detailed,
                          filters={'is_admin': False})

    @ddt.data(True, False)
    def test_index_wrong_version(self, detailed):
        """Verify the wrong version so that user can't list clusters."""
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
                          self._test_list, detailed=detailed,
                          version=mv.get_prior_version(mv.CLUSTER_SUPPORT))

    @ddt.data(*REPLICATION_FILTERS)
    def test_index_detail_replication_new_fields(self, filters):
        expected = {'clusters': self._get_expected(mv.REPLICATION_CLUSTER)}
        self._test_list(detailed=True, filters=filters, expected=expected,
                        version=mv.REPLICATION_CLUSTER)

    @ddt.data(*REPLICATION_FILTERS)
    def test_index_summary_replication_new_fields(self, filters):
        expected = {'clusters': [{'name': 'cluster_name',
                                  'binary': 'cinder-volume',
                                  'state': 'up',
                                  'replication_status': 'error',
                                  'status': 'enabled'},
                                 {'name': 'cluster2',
                                  'binary': 'cinder-volume',
                                  'state': 'down',
                                  'replication_status': 'error',
                                  'status': 'disabled'}]}
        self._test_list(detailed=False, filters=filters, expected=expected,
                        version=mv.REPLICATION_CLUSTER)

    @mock.patch('cinder.db.sqlalchemy.api.cluster_get',
                return_value=CLUSTERS_ORM[0])
    def test_show(self, get_mock):
        req = FakeRequest()
        expected = {'cluster': self._get_expected()[0]}
        cluster = self.controller.show(req, 'cluster_name',
                                       'cinder-volume')
        self.assertEqual(expected, cluster)
        get_mock.assert_called_once_with(
            req.environ['cinder.context'],
            None,
            services_summary=True,
            name='cluster_name',
            binary='cinder-volume')

    def test_show_unauthorized(self):
        req = FakeRequest(is_admin=False)
        self.assertRaises(exception.PolicyNotAuthorized,
                          self.controller.show, req, 'name')

    def test_show_wrong_version(self):
        req = FakeRequest(version=mv.get_prior_version(mv.CLUSTER_SUPPORT))
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
                          self.controller.show, req, 'name')

    @mock.patch('cinder.db.sqlalchemy.api.cluster_update')
    @mock.patch('cinder.db.sqlalchemy.api.cluster_get',
                return_value=CLUSTERS_ORM[1])
    def test_update_enable(self, get_mock, update_mock):
        req = FakeRequest()
        expected = {'cluster': {'name': u'cluster2',
                                'binary': 'cinder-volume',
                                'state': 'down',
                                'status': 'enabled',
                                'disabled_reason': None}}
        res = self.controller.update(req, 'enable',
                                     body={'name': 'cluster_name',
                                           'binary': 'cinder-volume'})
        self.assertEqual(expected, res)
        ctxt = req.environ['cinder.context']
        get_mock.assert_called_once_with(ctxt,
                                         None, binary='cinder-volume',
                                         name='cluster_name')
        update_mock.assert_called_once_with(ctxt, get_mock.return_value.id,
                                            {'disabled': False,
                                             'disabled_reason': None})

    @mock.patch('cinder.db.sqlalchemy.api.cluster_update')
    @mock.patch('cinder.db.sqlalchemy.api.cluster_get',
                return_value=CLUSTERS_ORM[0])
    def test_update_disable(self, get_mock, update_mock):
        req = FakeRequest()
        disabled_reason = 'For testing'
        expected = {'cluster': {'name': u'cluster_name',
                                'state': 'up',
                                'binary': 'cinder-volume',
                                'status': 'disabled',
                                'disabled_reason': disabled_reason}}
        res = self.controller.update(req, 'disable',
                                     body={'name': 'cluster_name',
                                           'binary': 'cinder-volume',
                                           'disabled_reason': disabled_reason})
        self.assertEqual(expected, res)
        ctxt = req.environ['cinder.context']
        get_mock.assert_called_once_with(ctxt,
                                         None, binary='cinder-volume',
                                         name='cluster_name')
        update_mock.assert_called_once_with(
            ctxt, get_mock.return_value.id,
            {'disabled': True, 'disabled_reason': disabled_reason})

    def test_update_wrong_action(self):
        req = FakeRequest()
        self.assertRaises(exception.NotFound, self.controller.update,
                          req, 'action', body={'name': 'cluster_name'})

    @ddt.data('enable', 'disable')
    def test_update_missing_name(self, action):
        req = FakeRequest()
        self.assertRaises(exception.ValidationError, self.controller.update,
                          req, action, body={'binary': 'cinder-volume'})

    def test_update_with_binary_more_than_255_characters(self):
        req = FakeRequest()
        self.assertRaises(exception.ValidationError, self.controller.update,
                          req, 'enable', body={'name': 'cluster_name',
                                               'binary': 'a' * 256})

    def test_update_with_name_more_than_255_characters(self):
        req = FakeRequest()
        self.assertRaises(exception.ValidationError, self.controller.update,
                          req, 'enable', body={'name': 'a' * 256,
                                               'binary': 'cinder-volume'})

    @ddt.data('a' * 256, '   ')
    def test_update_wrong_disabled_reason(self, disabled_reason):
        req = FakeRequest()
        self.assertRaises(exception.ValidationError, self.controller.update,
                          req, 'disable',
                          body={'name': 'cluster_name',
                                'disabled_reason': disabled_reason})

    @ddt.data('enable', 'disable')
    def test_update_unauthorized(self, action):
        req = FakeRequest(is_admin=False)
        self.assertRaises(exception.PolicyNotAuthorized,
                          self.controller.update, req, action,
                          body={'name': 'fake_name'})

    @ddt.data('enable', 'disable')
    def test_update_wrong_version(self, action):
        req = FakeRequest(version=mv.get_prior_version(mv.CLUSTER_SUPPORT))
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
                          self.controller.update, req, action, {})
