# Copyright 2012 IBM Corp.
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
from http import HTTPStatus
from unittest import mock

import ddt
import iso8601
from oslo_config import cfg

from cinder.api.contrib import services
from cinder.api import extensions
from cinder.api import microversions as mv
from cinder.api.openstack import api_version_request as api_version
from cinder.common import constants
from cinder import context
from cinder import exception
from cinder import objects
from cinder.tests.unit.api import fakes
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import test


CONF = cfg.CONF


fake_services_list = [
    {'binary': 'cinder-scheduler',
     'host': 'host1',
     'cluster_name': None,
     'availability_zone': 'cinder',
     'id': 1,
     'disabled': True,
     'updated_at': datetime.datetime(2012, 10, 29, 13, 42, 2),
     'created_at': datetime.datetime(2012, 9, 18, 2, 46, 27),
     'disabled_reason': 'test1',
     'modified_at': '',
     'uuid': 'a3a593da-7f8d-4bb7-8b4c-f2bc1e0b4824'},
    {'binary': 'cinder-volume',
     'host': 'host1',
     'cluster_name': None,
     'availability_zone': 'cinder',
     'id': 2,
     'disabled': True,
     'updated_at': datetime.datetime(2012, 10, 29, 13, 42, 5),
     'created_at': datetime.datetime(2012, 9, 18, 2, 46, 27),
     'disabled_reason': 'test2',
     'modified_at': '',
     'uuid': '4200b32b-0bf9-436c-86b2-0675f6ac218e'},
    {'binary': 'cinder-scheduler',
     'host': 'host2',
     'cluster_name': 'cluster1',
     'availability_zone': 'cinder',
     'id': 3,
     'disabled': False,
     'updated_at': datetime.datetime(2012, 9, 19, 6, 55, 34),
     'created_at': datetime.datetime(2012, 9, 18, 2, 46, 28),
     'disabled_reason': '',
     'modified_at': '',
     'uuid': '6d91e7f5-ca17-4e3b-bf4f-19ca77166dd7'},
    {'binary': 'cinder-volume',
     'host': 'host2',
     'cluster_name': 'cluster1',
     'availability_zone': 'cinder',
     'id': 4,
     'disabled': True,
     'updated_at': datetime.datetime(2012, 9, 18, 8, 3, 38),
     'created_at': datetime.datetime(2012, 9, 18, 2, 46, 28),
     'disabled_reason': 'test4',
     'modified_at': '',
     'uuid': '18417850-2ca9-43d1-9619-ae16bfb0f655'},
    {'binary': 'cinder-volume',
     'host': 'host2',
     'cluster_name': 'cluster2',
     'availability_zone': 'cinder',
     'id': 5,
     'disabled': True,
     'updated_at': datetime.datetime(2012, 9, 18, 8, 3, 38),
     'created_at': datetime.datetime(2012, 9, 18, 2, 46, 28),
     'disabled_reason': 'test5',
     'modified_at': datetime.datetime(2012, 10, 29, 13, 42, 5),
     'uuid': 'f838f35c-4035-464f-9792-ce60e390c13d'},
    {'binary': 'cinder-volume',
     'host': 'host2',
     'cluster_name': 'cluster2',
     'availability_zone': 'cinder',
     'id': 6,
     'disabled': False,
     'updated_at': datetime.datetime(2012, 9, 18, 8, 3, 38),
     'created_at': datetime.datetime(2012, 9, 18, 2, 46, 28),
     'disabled_reason': '',
     'modified_at': datetime.datetime(2012, 9, 18, 8, 1, 38),
     'uuid': 'f2825a00-cc2f-493d-9635-003e01db8b3d'},
    {'binary': 'cinder-scheduler',
     'host': 'host2',
     'cluster_name': None,
     'availability_zone': 'cinder',
     'id': 7,
     'disabled': False,
     'updated_at': None,
     'created_at': datetime.datetime(2012, 9, 18, 2, 46, 28),
     'disabled_reason': '',
     'modified_at': None,
     'uuid': '35fcf841-1974-4944-a798-1fb6d0a44972'},
]


class FakeRequest(object):
    environ = {"cinder.context": context.get_admin_context()}

    def __init__(self, version=mv.BASE_VERSION, **kwargs):
        self.GET = kwargs
        self.headers = mv.get_mv_header(version)
        self.api_version_request = mv.get_api_version(version)


class FakeRequestWithBinary(FakeRequest):
    def __init__(self, **kwargs):
        kwargs.setdefault('binary', constants.VOLUME_BINARY)
        super(FakeRequestWithBinary, self).__init__(**kwargs)


class FakeRequestWithHost(FakeRequest):
    def __init__(self, **kwargs):
        kwargs.setdefault('host', 'host1')
        super(FakeRequestWithHost, self).__init__(**kwargs)


class FakeRequestWithHostBinary(FakeRequestWithBinary):
    def __init__(self, **kwargs):
        kwargs.setdefault('host', 'host1')
        super(FakeRequestWithHostBinary, self).__init__(**kwargs)


def fake_service_get_all(context, **filters):
    result = []
    host = filters.pop('host', None)
    for service in fake_services_list:
        if (host and service['host'] != host and
                not service['host'].startswith(host + '@')):
            continue

        if all(v is None or service.get(k) == v for k, v in filters.items()):
            result.append(service)
    return result


def fake_service_get(context, service_id=None, **filters):
    result = fake_service_get_all(context, id=service_id, **filters)
    if not result:
        raise exception.ServiceNotFound(service_id=service_id)
    return result[0]


def fake_service_get_by_id(value):
    for service in fake_services_list:
        if service['id'] == value:
            return service
    return None


def fake_service_update(context, service_id, values):
    service = fake_service_get_by_id(service_id)
    if service is None:
        raise exception.ServiceNotFound(service_id=service_id)
    else:
        {'host': 'host1', 'service': constants.VOLUME_BINARY,
         'disabled': values['disabled']}


def fake_policy_authorize(context, action, target,
                          do_raise=True, exc=exception.PolicyNotAuthorized):
    pass


def fake_utcnow(with_timezone=False):
    tzinfo = iso8601.UTC if with_timezone else None
    return datetime.datetime(2012, 10, 29, 13, 42, 11, tzinfo=tzinfo)


def fake_get_pools(ctxt, filters=None):
    return [{"name": "host1", "capabilities": {"backend_state": "up"}},
            {"name": "host2", "capabilities": {"backend_state": "down"}}]


@ddt.ddt
@mock.patch('cinder.scheduler.rpcapi.SchedulerAPI.get_pools', fake_get_pools)
@mock.patch('cinder.db.service_get_all', fake_service_get_all)
@mock.patch('cinder.db.service_get', fake_service_get)
@mock.patch('oslo_utils.timeutils.utcnow', fake_utcnow)
@mock.patch('cinder.db.sqlalchemy.api.service_update', fake_service_update)
@mock.patch('cinder.policy.authorize', fake_policy_authorize)
class ServicesTest(test.TestCase):

    def setUp(self):
        super(ServicesTest, self).setUp()

        self.context = context.get_admin_context()
        self.ext_mgr = extensions.ExtensionManager()
        self.ext_mgr.extensions = {}
        self.controller = services.ServiceController(self.ext_mgr)

    def test_services_list(self):
        req = FakeRequest()
        res_dict = self.controller.index(req)

        response = {'services': [{'binary': 'cinder-scheduler',
                                  'host': 'host1', 'zone': 'cinder',
                                  'status': 'disabled', 'state': 'up',
                                  'updated_at': datetime.datetime(
                                      2012, 10, 29, 13, 42, 2)},
                                 {'binary': 'cinder-volume',
                                  'host': 'host1', 'zone': 'cinder',
                                  'status': 'disabled', 'state': 'up',
                                  'updated_at': datetime.datetime(
                                      2012, 10, 29, 13, 42, 5)},
                                 {'binary': 'cinder-scheduler',
                                  'host': 'host2',
                                  'zone': 'cinder',
                                  'status': 'enabled', 'state': 'down',
                                  'updated_at': datetime.datetime(
                                      2012, 9, 19, 6, 55, 34)},
                                 {'binary': 'cinder-volume',
                                  'host': 'host2',
                                  'zone': 'cinder',
                                  'status': 'disabled', 'state': 'down',
                                  'updated_at': datetime.datetime(
                                      2012, 9, 18, 8, 3, 38)},
                                 {'binary': 'cinder-volume',
                                  'host': 'host2',
                                  'zone': 'cinder',
                                  'status': 'disabled', 'state': 'down',
                                  'updated_at': datetime.datetime(
                                      2012, 10, 29, 13, 42, 5)},
                                 {'binary': 'cinder-volume',
                                  'host': 'host2',
                                  'zone': 'cinder',
                                  'status': 'enabled', 'state': 'down',
                                  'updated_at': datetime.datetime(
                                      2012, 9, 18, 8, 3, 38)},
                                 {'binary': 'cinder-scheduler',
                                  'host': 'host2',
                                  'zone': 'cinder',
                                  'status': 'enabled', 'state': 'down',
                                  'updated_at': None},
                                 ]}
        self.assertEqual(response, res_dict)

    def test_failover_old_version(self):
        req = FakeRequest(version=mv.BACKUP_PROJECT)
        self.assertRaises(exception.InvalidInput, self.controller.update, req,
                          'failover', {'cluster': 'cluster1'})

    def test_failover_no_values(self):
        req = FakeRequest(version=mv.REPLICATION_CLUSTER)
        self.assertRaises(exception.InvalidInput,
                          self.controller.update, req,
                          'failover', {'backend_id': 'replica1'})

    @ddt.data({'host': 'hostname'}, {'cluster': 'mycluster'})
    @mock.patch('cinder.volume.api.API.failover')
    def test_failover(self, body, failover_mock):
        req = FakeRequest(version=mv.REPLICATION_CLUSTER)
        body['backend_id'] = 'replica1'
        res = self.controller.update(req, 'failover', body)
        self.assertEqual(202, res.status_code)
        failover_mock.assert_called_once_with(req.environ['cinder.context'],
                                              body.get('host'),
                                              body.get('cluster'), 'replica1')

    @ddt.data({}, {'host': 'hostname', 'cluster': 'mycluster'})
    @mock.patch('cinder.volume.api.API.failover')
    def test_failover_invalid_input(self, body, failover_mock):
        req = FakeRequest(version=mv.REPLICATION_CLUSTER)
        body['backend_id'] = 'replica1'
        self.assertRaises(exception.InvalidInput,
                          self.controller.update, req, 'failover', body)
        failover_mock.assert_not_called()

    def test_services_list_with_cluster_name(self):
        req = FakeRequest(version=mv.CLUSTER_SUPPORT)
        res_dict = self.controller.index(req)

        response = {'services': [{'binary': 'cinder-scheduler',
                                  'cluster': None,
                                  'host': 'host1', 'zone': 'cinder',
                                  'status': 'disabled', 'state': 'up',
                                  'updated_at': datetime.datetime(
                                      2012, 10, 29, 13, 42, 2)},
                                 {'binary': 'cinder-volume',
                                  'cluster': None,
                                  'host': 'host1', 'zone': 'cinder',
                                  'status': 'disabled', 'state': 'up',
                                  'updated_at': datetime.datetime(
                                      2012, 10, 29, 13, 42, 5)},
                                 {'binary': 'cinder-scheduler',
                                  'cluster': 'cluster1',
                                  'host': 'host2',
                                  'zone': 'cinder',
                                  'status': 'enabled', 'state': 'down',
                                  'updated_at': datetime.datetime(
                                      2012, 9, 19, 6, 55, 34)},
                                 {'binary': 'cinder-volume',
                                  'cluster': 'cluster1',
                                  'host': 'host2',
                                  'zone': 'cinder',
                                  'status': 'disabled', 'state': 'down',
                                  'updated_at': datetime.datetime(
                                      2012, 9, 18, 8, 3, 38)},
                                 {'binary': 'cinder-volume',
                                  'cluster': 'cluster2',
                                  'host': 'host2',
                                  'zone': 'cinder',
                                  'status': 'disabled', 'state': 'down',
                                  'updated_at': datetime.datetime(
                                      2012, 10, 29, 13, 42, 5)},
                                 {'binary': 'cinder-volume',
                                  'cluster': 'cluster2',
                                  'host': 'host2',
                                  'zone': 'cinder',
                                  'status': 'enabled', 'state': 'down',
                                  'updated_at': datetime.datetime(
                                      2012, 9, 18, 8, 3, 38)},
                                 {'binary': 'cinder-scheduler',
                                  'cluster': None,
                                  'host': 'host2',
                                  'zone': 'cinder',
                                  'status': 'enabled', 'state': 'down',
                                  'updated_at': None},
                                 ]}
        self.assertEqual(response, res_dict)

    def test_services_list_with_backend_state(self):
        req = FakeRequest(version=mv.BACKEND_STATE_REPORT)
        res_dict = self.controller.index(req)

        response = {'services': [{'binary': 'cinder-scheduler',
                                  'cluster': None,
                                  'host': 'host1', 'zone': 'cinder',
                                  'status': 'disabled', 'state': 'up',
                                  'updated_at': datetime.datetime(
                                      2012, 10, 29, 13, 42, 2)},
                                 {'binary': 'cinder-volume',
                                  'cluster': None,
                                  'host': 'host1', 'zone': 'cinder',
                                  'status': 'disabled', 'state': 'up',
                                  'updated_at': datetime.datetime(
                                      2012, 10, 29, 13, 42, 5),
                                  'backend_state': 'up'},
                                 {'binary': 'cinder-scheduler',
                                  'cluster': 'cluster1',
                                  'host': 'host2',
                                  'zone': 'cinder',
                                  'status': 'enabled', 'state': 'down',
                                  'updated_at': datetime.datetime(
                                      2012, 9, 19, 6, 55, 34)},
                                 {'binary': 'cinder-volume',
                                  'cluster': 'cluster1',
                                  'host': 'host2',
                                  'zone': 'cinder',
                                  'status': 'disabled', 'state': 'down',
                                  'updated_at': datetime.datetime(
                                      2012, 9, 18, 8, 3, 38),
                                  'backend_state': 'down'},
                                 {'binary': 'cinder-volume',
                                  'cluster': 'cluster2',
                                  'host': 'host2',
                                  'zone': 'cinder',
                                  'status': 'disabled', 'state': 'down',
                                  'updated_at': datetime.datetime(
                                      2012, 10, 29, 13, 42, 5),
                                  'backend_state': 'down'},
                                 {'binary': 'cinder-volume',
                                  'cluster': 'cluster2',
                                  'host': 'host2',
                                  'zone': 'cinder',
                                  'status': 'enabled', 'state': 'down',
                                  'updated_at': datetime.datetime(
                                      2012, 9, 18, 8, 3, 38),
                                  'backend_state': 'down'},
                                 {'binary': 'cinder-scheduler',
                                  'cluster': None,
                                  'host': 'host2',
                                  'zone': 'cinder',
                                  'status': 'enabled', 'state': 'down',
                                  'updated_at': None},
                                 ]}
        self.assertEqual(response, res_dict)

    def test_services_detail(self):
        self.ext_mgr.extensions['os-extended-services'] = True
        self.controller = services.ServiceController(self.ext_mgr)
        req = FakeRequest()
        res_dict = self.controller.index(req)

        response = {'services': [{'binary': 'cinder-scheduler',
                                  'host': 'host1', 'zone': 'cinder',
                                  'status': 'disabled', 'state': 'up',
                                  'updated_at': datetime.datetime(
                                      2012, 10, 29, 13, 42, 2),
                                  'disabled_reason': 'test1'},
                                 {'binary': 'cinder-volume',
                                  'replication_status': None,
                                  'active_backend_id': None,
                                  'frozen': False,
                                  'host': 'host1', 'zone': 'cinder',
                                  'status': 'disabled', 'state': 'up',
                                  'updated_at': datetime.datetime(
                                      2012, 10, 29, 13, 42, 5),
                                  'disabled_reason': 'test2'},
                                 {'binary': 'cinder-scheduler',
                                  'host': 'host2',
                                  'zone': 'cinder',
                                  'status': 'enabled', 'state': 'down',
                                  'updated_at': datetime.datetime(
                                      2012, 9, 19, 6, 55, 34),
                                  'disabled_reason': ''},
                                 {'binary': 'cinder-volume',
                                  'replication_status': None,
                                  'active_backend_id': None,
                                  'frozen': False,
                                  'host': 'host2',
                                  'zone': 'cinder',
                                  'status': 'disabled', 'state': 'down',
                                  'updated_at': datetime.datetime(
                                      2012, 9, 18, 8, 3, 38),
                                  'disabled_reason': 'test4'},
                                 {'binary': 'cinder-volume',
                                  'replication_status': None,
                                  'active_backend_id': None,
                                  'frozen': False,
                                  'host': 'host2',
                                  'zone': 'cinder',
                                  'status': 'disabled', 'state': 'down',
                                  'updated_at': datetime.datetime(
                                      2012, 10, 29, 13, 42, 5),
                                  'disabled_reason': 'test5'},
                                 {'binary': 'cinder-volume',
                                  'replication_status': None,
                                  'active_backend_id': None,
                                  'frozen': False,
                                  'host': 'host2',
                                  'zone': 'cinder',
                                  'status': 'enabled', 'state': 'down',
                                  'updated_at': datetime.datetime(
                                      2012, 9, 18, 8, 3, 38),
                                  'disabled_reason': ''},
                                 {'binary': 'cinder-scheduler',
                                  'host': 'host2',
                                  'zone': 'cinder',
                                  'status': 'enabled', 'state': 'down',
                                  'updated_at': None,
                                  'disabled_reason': ''},
                                 ]}
        self.assertEqual(response, res_dict)

    def test_services_list_with_host(self):
        req = FakeRequestWithHost()
        res_dict = self.controller.index(req)

        response = {'services': [
            {'binary': 'cinder-scheduler',
             'host': 'host1',
             'zone': 'cinder',
             'status': 'disabled', 'state': 'up',
             'updated_at': datetime.datetime(2012, 10,
                                             29, 13, 42, 2)},
            {'binary': 'cinder-volume',
             'host': 'host1',
             'zone': 'cinder',
             'status': 'disabled', 'state': 'up',
             'updated_at': datetime.datetime(2012, 10, 29,
                                             13, 42, 5)}]}
        self.assertEqual(response, res_dict)

    def test_services_detail_with_host(self):
        self.ext_mgr.extensions['os-extended-services'] = True
        self.controller = services.ServiceController(self.ext_mgr)
        req = FakeRequestWithHost()
        res_dict = self.controller.index(req)

        response = {'services': [
            {'binary': 'cinder-scheduler',
             'host': 'host1',
             'zone': 'cinder',
             'status': 'disabled', 'state': 'up',
             'updated_at': datetime.datetime(2012, 10,
                                             29, 13, 42, 2),
             'disabled_reason': 'test1'},
            {'binary': 'cinder-volume',
             'frozen': False,
             'replication_status': None,
             'active_backend_id': None,
             'host': 'host1',
             'zone': 'cinder',
             'status': 'disabled', 'state': 'up',
             'updated_at': datetime.datetime(2012, 10, 29,
                                             13, 42, 5),
             'disabled_reason': 'test2'}]}
        self.assertEqual(response, res_dict)

    def test_services_list_with_binary(self):
        req = FakeRequestWithBinary()
        res_dict = self.controller.index(req)

        response = {'services': [
            {'binary': 'cinder-volume',
             'host': 'host1',
             'zone': 'cinder',
             'status': 'disabled',
             'state': 'up',
             'updated_at': datetime.datetime(2012, 10, 29,
                                             13, 42, 5)},
            {'binary': 'cinder-volume',
             'host': 'host2',
             'zone': 'cinder',
             'status': 'disabled',
             'state': 'down',
             'updated_at': datetime.datetime(2012, 9, 18,
                                             8, 3, 38)},
            {'binary': 'cinder-volume',
             'host': 'host2',
             'zone': 'cinder',
             'status': 'disabled',
             'state': 'down',
             'updated_at': datetime.datetime(2012, 10, 29,
                                             13, 42, 5)},
            {'binary': 'cinder-volume',
             'host': 'host2',
             'zone': 'cinder',
             'status': 'enabled',
             'state': 'down',
             'updated_at': datetime.datetime(2012, 9, 18,
                                             8, 3, 38)}]}
        self.assertEqual(response, res_dict)

    def test_services_detail_with_binary(self):
        self.ext_mgr.extensions['os-extended-services'] = True
        self.controller = services.ServiceController(self.ext_mgr)
        req = FakeRequestWithBinary()
        res_dict = self.controller.index(req)

        response = {'services': [
            {'binary': 'cinder-volume',
             'replication_status': None,
             'active_backend_id': None,
             'host': 'host1',
             'zone': 'cinder',
             'status': 'disabled',
             'state': 'up',
             'frozen': False,
             'updated_at': datetime.datetime(2012, 10, 29,
                                             13, 42, 5),
             'disabled_reason': 'test2'},
            {'binary': 'cinder-volume',
             'replication_status': None,
             'active_backend_id': None,
             'host': 'host2',
             'zone': 'cinder',
             'status': 'disabled',
             'state': 'down',
             'frozen': False,
             'updated_at': datetime.datetime(2012, 9, 18,
                                             8, 3, 38),
             'disabled_reason': 'test4'},
            {'binary': 'cinder-volume',
             'replication_status': None,
             'active_backend_id': None,
             'host': 'host2',
             'zone': 'cinder',
             'status': 'disabled',
             'state': 'down',
             'frozen': False,
             'updated_at': datetime.datetime(2012, 10, 29,
                                             13, 42, 5),
             'disabled_reason': 'test5'},
            {'binary': 'cinder-volume',
             'replication_status': None,
             'active_backend_id': None,
             'host': 'host2',
             'zone': 'cinder',
             'status': 'enabled',
             'state': 'down',
             'frozen': False,
             'updated_at': datetime.datetime(2012, 9, 18,
                                             8, 3, 38),
             'disabled_reason': ''}]}
        self.assertEqual(response, res_dict)

    def test_services_list_with_host_binary(self):
        req = FakeRequestWithHostBinary()
        res_dict = self.controller.index(req)

        response = {'services': [
            {'binary': 'cinder-volume',
             'host': 'host1',
             'zone': 'cinder',
             'status': 'disabled',
             'state': 'up',
             'updated_at': datetime.datetime(2012, 10, 29,
                                             13, 42, 5)}]}
        self.assertEqual(response, res_dict)

    def test_services_detail_with_host_binary(self):
        self.ext_mgr.extensions['os-extended-services'] = True
        self.controller = services.ServiceController(self.ext_mgr)
        req = FakeRequestWithHostBinary()
        res_dict = self.controller.index(req)

        response = {'services': [
            {'binary': 'cinder-volume',
             'replication_status': None,
             'active_backend_id': None,
             'frozen': False,
             'host': 'host1',
             'zone': 'cinder',
             'status': 'disabled',
             'state': 'up',
             'updated_at': datetime.datetime(2012, 10, 29,
                                             13, 42, 5),
             'disabled_reason': 'test2'}]}
        self.assertEqual(response, res_dict)

    def test_services_enable_with_service_key(self):
        body = {'host': 'host1', 'service': constants.VOLUME_BINARY}
        req = fakes.HTTPRequest.blank(
            '/v3/%s/os-services/enable' % fake.PROJECT_ID)
        res_dict = self.controller.update(req, "enable", body)

        self.assertEqual('enabled', res_dict['status'])

    def test_services_enable_with_binary_key(self):
        body = {'host': 'host1', 'binary': constants.VOLUME_BINARY}
        req = fakes.HTTPRequest.blank(
            '/v3/%s/os-services/enable' % fake.PROJECT_ID)
        res_dict = self.controller.update(req, "enable", body)

        self.assertEqual('enabled', res_dict['status'])

    def test_services_disable_with_service_key(self):
        req = fakes.HTTPRequest.blank(
            '/v3/%s/os-services/disable' % fake.PROJECT_ID)
        body = {'host': 'host1', 'service': constants.VOLUME_BINARY}
        res_dict = self.controller.update(req, "disable", body)

        self.assertEqual('disabled', res_dict['status'])

    def test_services_disable_with_binary_key(self):
        req = fakes.HTTPRequest.blank(
            '/v3/%s/os-services/disable' % fake.PROJECT_ID)
        body = {'host': 'host1', 'binary': constants.VOLUME_BINARY}
        res_dict = self.controller.update(req, "disable", body)

        self.assertEqual('disabled', res_dict['status'])

    def test_services_disable_log_reason(self):
        self.ext_mgr.extensions['os-extended-services'] = True
        self.controller = services.ServiceController(self.ext_mgr)
        req = (
            fakes.HTTPRequest.blank('v1/fake/os-services/disable-log-reason'))
        body = {'host': 'host1',
                'binary': 'cinder-scheduler',
                'disabled_reason': 'test-reason',
                }
        res_dict = self.controller.update(req, "disable-log-reason", body)

        self.assertEqual('disabled', res_dict['status'])
        self.assertEqual('test-reason', res_dict['disabled_reason'])

    def test_services_disable_log_reason_unicode(self):
        self.ext_mgr.extensions['os-extended-services'] = True
        self.controller = services.ServiceController(self.ext_mgr)
        req = (
            fakes.HTTPRequest.blank('v1/fake/os-services/disable-log-reason'))
        body = {'host': 'host1',
                'binary': 'cinder-scheduler',
                'disabled_reason': 'test-reason',
                }
        res_dict = self.controller.update(req, "disable-log-reason", body)

        self.assertEqual('disabled', res_dict['status'])
        self.assertEqual('test-reason', res_dict['disabled_reason'])

    def test_services_disable_log_reason_none(self):
        self.ext_mgr.extensions['os-extended-services'] = True
        self.controller = services.ServiceController(self.ext_mgr)
        req = (
            fakes.HTTPRequest.blank('v1/fake/os-services/disable-log-reason'))
        body = {'host': 'host1',
                'binary': 'cinder-scheduler',
                'disabled_reason': None,
                }
        self.assertRaises(exception.ValidationError,
                          self.controller.update,
                          req, "disable-log-reason", body)

    @ddt.data(' ' * 10, 'a' * 256, None)
    def test_invalid_reason_field(self, reason):
        # # Check that empty strings are not allowed
        self.ext_mgr.extensions['os-extended-services'] = True
        self.controller = services.ServiceController(self.ext_mgr)
        req = (
            fakes.HTTPRequest.blank('v3/fake/os-services/disable-log-reason'))
        body = {'host': 'host1',
                'binary': 'cinder-volume',
                'disabled_reason': reason,
                }
        self.assertRaises(exception.ValidationError,
                          self.controller.update,
                          req, "disable-log-reason", body)

    def test_services_failover_host(self):
        url = '/v3/%s/os-services/failover_host' % fake.PROJECT_ID
        req = fakes.HTTPRequest.blank(url)
        body = {'host': 'fake_host',
                'backend_id': 'fake_backend'}
        with mock.patch.object(self.controller.volume_api, 'failover') \
                as failover_mock:
            res = self.controller.update(req, 'failover_host', body)
        failover_mock.assert_called_once_with(req.environ['cinder.context'],
                                              'fake_host',
                                              None,
                                              'fake_backend')
        self.assertEqual(HTTPStatus.ACCEPTED, res.status_code)

    @ddt.data(('failover_host', {'host': 'fake_host',
                                 'backend_id': 'fake_backend'}),
              ('freeze', {'host': 'fake_host'}),
              ('thaw', {'host': 'fake_host'}))
    @ddt.unpack
    @mock.patch('cinder.objects.ServiceList.get_all')
    def test_services_action_host_not_found(self, method, body,
                                            mock_get_all_services):
        url = '/v3/%s/os-services/%s' % (fake.PROJECT_ID, method)
        req = fakes.HTTPRequest.blank(url)
        mock_get_all_services.return_value = []
        msg = 'No service found with host=%s' % 'fake_host'
        result = self.assertRaises(exception.InvalidInput,
                                   self.controller.update,
                                   req, method, body)
        self.assertEqual(msg, result.msg)

    @ddt.data(('failover', {'cluster': 'fake_cluster',
                            'backend_id': 'fake_backend'}),
              ('freeze', {'cluster': 'fake_cluster'}),
              ('thaw', {'cluster': 'fake_cluster'}))
    @ddt.unpack
    @mock.patch('cinder.objects.ServiceList.get_all')
    def test_services_action_cluster_not_found(self, method, body,
                                               mock_get_all_services):
        url = '/v3/%s/os-services/%s' % (fake.PROJECT_ID, method)
        req = fakes.HTTPRequest.blank(url, version=mv.REPLICATION_CLUSTER)
        mock_get_all_services.return_value = []
        msg = "No service found with cluster=fake_cluster"
        result = self.assertRaises(exception.InvalidInput,
                                   self.controller.update, req,
                                   method, body)
        self.assertEqual(msg, result.msg)

    def test_services_freeze(self):
        url = '/v3/%s/os-services/freeze' % fake.PROJECT_ID
        req = fakes.HTTPRequest.blank(url)
        body = {'host': 'fake_host'}
        with mock.patch.object(self.controller.volume_api, 'freeze_host') \
                as freeze_mock:
            res = self.controller.update(req, 'freeze', body)
        freeze_mock.assert_called_once_with(req.environ['cinder.context'],
                                            'fake_host', None)
        self.assertEqual(freeze_mock.return_value, res)

    def test_services_thaw(self):
        url = '/v3/%s/os-services/thaw' % fake.PROJECT_ID
        req = fakes.HTTPRequest.blank(url)
        body = {'host': 'fake_host'}
        with mock.patch.object(self.controller.volume_api, 'thaw_host') \
                as thaw_mock:
            res = self.controller.update(req, 'thaw', body)
        thaw_mock.assert_called_once_with(req.environ['cinder.context'],
                                          'fake_host', None)
        self.assertEqual(thaw_mock.return_value, res)

    @ddt.data('freeze', 'thaw', 'failover_host')
    def test_services_replication_calls_no_host(self, method):
        url = '/v3/%s/os-services/%s' % (fake.PROJECT_ID, method)
        req = fakes.HTTPRequest.blank(url)
        self.assertRaises(exception.InvalidInput,
                          self.controller.update, req, method, {})

    @mock.patch('cinder.api.contrib.services.ServiceController._set_log')
    def test_set_log(self, set_log_mock):
        set_log_mock.return_value = None
        req = FakeRequest(version=mv.LOG_LEVEL)
        body = mock.sentinel.body
        res = self.controller.update(req, 'set-log', body)
        self.assertEqual(set_log_mock.return_value, res)
        set_log_mock.assert_called_once_with(req, mock.ANY, body=body)

    @mock.patch('cinder.api.contrib.services.ServiceController._get_log')
    def test_get_log(self, get_log_mock):
        get_log_mock.return_value = None
        req = FakeRequest(version=mv.LOG_LEVEL)
        body = mock.sentinel.body
        res = self.controller.update(req, 'get-log', body)
        self.assertEqual(get_log_mock.return_value, res)
        get_log_mock.assert_called_once_with(req, mock.ANY, body=body)

    def test_get_log_wrong_binary(self):
        req = FakeRequest(version=mv.LOG_LEVEL)
        body = {'binary': 'wrong-binary'}
        self.assertRaises(exception.ValidationError,
                          self.controller._get_log, req, self.context,
                          body=body)

    def test_get_log_w_server_filter_same_host(self):
        server_filter = 'controller-0'
        CONF.set_override('host', server_filter)
        body = {'binary': constants.API_BINARY, 'server': server_filter}
        req = FakeRequest(version=mv.LOG_LEVEL)

        log_levels = self.controller._get_log(
            req=req, context=mock.sentinel.context, body=body)
        log_levels = log_levels['log_levels']

        self.assertEqual(1, len(log_levels))
        self.assertEqual('controller-0', log_levels[0]['host'])
        self.assertEqual('cinder-api', log_levels[0]['binary'])
        # since there are a lot of log levels, we just check if the key-value
        # exists for levels
        self.assertIsNotNone(log_levels[0]['levels'])

    def test_get_log_w_server_filter_different_host(self):
        server_filter = 'controller-0'
        CONF.set_override('host', 'controller-different-host')
        body = {'binary': constants.API_BINARY, 'server': server_filter}
        req = FakeRequest(version=mv.LOG_LEVEL)

        log_levels = self.controller._get_log(
            req=req, context=mock.sentinel.context, body=body)
        log_levels = log_levels['log_levels']

        self.assertEqual(0, len(log_levels))

    @ddt.data(None, '', '*')
    @mock.patch('cinder.objects.ServiceList.get_all')
    def test__log_params_binaries_service_all(self, binary, service_list_mock):
        body = {'binary': binary, 'server': 'host1'}
        binaries, services = self.controller._log_params_binaries_services(
            mock.sentinel.context, body)
        self.assertEqual(constants.LOG_BINARIES, binaries)
        self.assertEqual(service_list_mock.return_value, services)
        service_list_mock.assert_called_once_with(
            mock.sentinel.context, filters={'host_or_cluster': body['server'],
                                            'is_up': True})

    @ddt.data('cinder-api', 'cinder-volume', 'cinder-scheduler',
              'cinder-backup')
    @mock.patch('cinder.objects.ServiceList.get_all')
    def test__log_params_binaries_service_one(self, binary, service_list_mock):
        body = {'binary': binary, 'server': 'host1'}
        binaries, services = self.controller._log_params_binaries_services(
            mock.sentinel.context, body)
        self.assertEqual([binary], binaries)

        if binary == constants.API_BINARY:
            self.assertEqual([], services)
            service_list_mock.assert_not_called()
        else:
            self.assertEqual(service_list_mock.return_value, services)
            service_list_mock.assert_called_once_with(
                mock.sentinel.context,
                filters={'host_or_cluster': body['server'], 'binary': binary,
                         'is_up': True})

    @ddt.data((None, exception.InvalidInput),
              ('', exception.InvalidInput),
              ('wronglevel', exception.InvalidInput))
    @ddt.unpack
    def test__set_log_invalid_level(self, level, exceptions):
        body = {'level': level}
        url = '/v3/%s/os-services/set-log' % fake.PROJECT_ID
        req = fakes.HTTPRequest.blank(url)
        req.api_version_request = api_version.APIVersionRequest("3.32")
        self.assertRaises(exceptions,
                          self.controller._set_log, req, self.context,
                          body=body)

    @mock.patch('cinder.utils.get_log_method')
    @mock.patch('cinder.objects.ServiceList.get_all')
    @mock.patch('cinder.utils.set_log_levels')
    @mock.patch('cinder.scheduler.rpcapi.SchedulerAPI.set_log_levels')
    @mock.patch('cinder.volume.rpcapi.VolumeAPI.set_log_levels')
    @mock.patch('cinder.backup.rpcapi.BackupAPI.set_log_levels')
    def test__set_log(self, backup_rpc_mock, vol_rpc_mock, sch_rpc_mock,
                      set_log_mock, get_all_mock, get_log_mock):
        services = [
            objects.Service(self.context, binary=constants.SCHEDULER_BINARY),
            objects.Service(self.context, binary=constants.VOLUME_BINARY),
            objects.Service(self.context, binary=constants.BACKUP_BINARY),
        ]
        get_all_mock.return_value = services
        url = '/v3/%s/os-services/set-log' % fake.PROJECT_ID
        req = fakes.HTTPRequest.blank(url)
        body = {'binary': '*', 'prefix': 'eventlet.', 'level': 'debug'}
        log_level = objects.LogLevel(prefix=body['prefix'],
                                     level=body['level'])
        with mock.patch('cinder.objects.LogLevel') as log_level_mock:
            log_level_mock.return_value = log_level
            res = self.controller._set_log(req, mock.sentinel.context,
                                           body=body)
            log_level_mock.assert_called_once_with(mock.sentinel.context,
                                                   prefix=body['prefix'],
                                                   level=body['level'])

        self.assertEqual(202, res.status_code)

        set_log_mock.assert_called_once_with(body['prefix'], body['level'])
        sch_rpc_mock.assert_called_once_with(mock.sentinel.context,
                                             services[0], log_level)
        vol_rpc_mock.assert_called_once_with(mock.sentinel.context,
                                             services[1], log_level)
        backup_rpc_mock.assert_called_once_with(mock.sentinel.context,
                                                services[2], log_level)
        get_log_mock.assert_called_once_with(body['level'])

    @mock.patch('cinder.objects.ServiceList.get_all')
    @mock.patch('cinder.utils.get_log_levels')
    @mock.patch('cinder.scheduler.rpcapi.SchedulerAPI.get_log_levels')
    @mock.patch('cinder.volume.rpcapi.VolumeAPI.get_log_levels')
    @mock.patch('cinder.backup.rpcapi.BackupAPI.get_log_levels')
    def test__get_log(self, backup_rpc_mock, vol_rpc_mock, sch_rpc_mock,
                      get_log_mock, get_all_mock):
        get_log_mock.return_value = mock.sentinel.api_levels
        backup_rpc_mock.return_value = [
            objects.LogLevel(prefix='p1', level='l1'),
            objects.LogLevel(prefix='p2', level='l2')
        ]
        vol_rpc_mock.return_value = [
            objects.LogLevel(prefix='p3', level='l3'),
            objects.LogLevel(prefix='p4', level='l4')
        ]
        sch_rpc_mock.return_value = [
            objects.LogLevel(prefix='p5', level='l5'),
            objects.LogLevel(prefix='p6', level='l6')
        ]

        services = [
            objects.Service(self.context, binary=constants.SCHEDULER_BINARY,
                            host='host'),
            objects.Service(self.context, binary=constants.VOLUME_BINARY,
                            host='host@backend#pool'),
            objects.Service(self.context, binary=constants.BACKUP_BINARY,
                            host='host'),
        ]
        get_all_mock.return_value = services
        url = '/v3/%s/os-services/get-log' % fake.PROJECT_ID
        req = fakes.HTTPRequest.blank(url)
        body = {'binary': '*', 'prefix': 'eventlet.'}

        log_level = objects.LogLevel(prefix=body['prefix'])
        with mock.patch('cinder.objects.LogLevel') as log_level_mock:
            log_level_mock.return_value = log_level
            res = self.controller._get_log(req, mock.sentinel.context,
                                           body=body)
            log_level_mock.assert_called_once_with(mock.sentinel.context,
                                                   prefix=body['prefix'])

        expected = {'log_levels': [
            {'binary': 'cinder-api',
             'host': CONF.host,
             'levels': mock.sentinel.api_levels},
            {'binary': 'cinder-scheduler', 'host': 'host',
             'levels': {'p5': 'l5', 'p6': 'l6'}},
            {'binary': constants.VOLUME_BINARY,
             'host': 'host@backend#pool',
             'levels': {'p3': 'l3', 'p4': 'l4'}},
            {'binary': 'cinder-backup', 'host': 'host',
             'levels': {'p1': 'l1', 'p2': 'l2'}},
        ]}

        self.assertDictEqual(expected, res)

        get_log_mock.assert_called_once_with(body['prefix'])
        sch_rpc_mock.assert_called_once_with(mock.sentinel.context,
                                             services[0], log_level)
        vol_rpc_mock.assert_called_once_with(mock.sentinel.context,
                                             services[1], log_level)
        backup_rpc_mock.assert_called_once_with(mock.sentinel.context,
                                                services[2], log_level)
