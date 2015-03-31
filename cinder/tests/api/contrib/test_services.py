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

from oslo_utils import timeutils
import webob.exc

from cinder.api.contrib import services
from cinder.api import extensions
from cinder import context
from cinder import db
from cinder import exception
from cinder import policy
from cinder import test
from cinder.tests.api import fakes


fake_services_list = [
    {'binary': 'cinder-scheduler',
     'host': 'host1',
     'availability_zone': 'cinder',
     'id': 1,
     'disabled': True,
     'updated_at': datetime.datetime(2012, 10, 29, 13, 42, 2),
     'created_at': datetime.datetime(2012, 9, 18, 2, 46, 27),
     'disabled_reason': 'test1',
     'modified_at': ''},
    {'binary': 'cinder-volume',
     'host': 'host1',
     'availability_zone': 'cinder',
     'id': 2,
     'disabled': True,
     'updated_at': datetime.datetime(2012, 10, 29, 13, 42, 5),
     'created_at': datetime.datetime(2012, 9, 18, 2, 46, 27),
     'disabled_reason': 'test2',
     'modified_at': ''},
    {'binary': 'cinder-scheduler',
     'host': 'host2',
     'availability_zone': 'cinder',
     'id': 3,
     'disabled': False,
     'updated_at': datetime.datetime(2012, 9, 19, 6, 55, 34),
     'created_at': datetime.datetime(2012, 9, 18, 2, 46, 28),
     'disabled_reason': '',
     'modified_at': ''},
    {'binary': 'cinder-volume',
     'host': 'host2',
     'availability_zone': 'cinder',
     'id': 4,
     'disabled': True,
     'updated_at': datetime.datetime(2012, 9, 18, 8, 3, 38),
     'created_at': datetime.datetime(2012, 9, 18, 2, 46, 28),
     'disabled_reason': 'test4',
     'modified_at': ''},
    {'binary': 'cinder-volume',
     'host': 'host2',
     'availability_zone': 'cinder',
     'id': 5,
     'disabled': True,
     'updated_at': datetime.datetime(2012, 9, 18, 8, 3, 38),
     'created_at': datetime.datetime(2012, 9, 18, 2, 46, 28),
     'disabled_reason': 'test5',
     'modified_at': datetime.datetime(2012, 10, 29, 13, 42, 5)},
    {'binary': 'cinder-volume',
     'host': 'host2',
     'availability_zone': 'cinder',
     'id': 6,
     'disabled': False,
     'updated_at': datetime.datetime(2012, 9, 18, 8, 3, 38),
     'created_at': datetime.datetime(2012, 9, 18, 2, 46, 28),
     'disabled_reason': '',
     'modified_at': datetime.datetime(2012, 9, 18, 8, 1, 38)},
]


class FakeRequest(object):
    environ = {"cinder.context": context.get_admin_context()}
    GET = {}


# NOTE(uni): deprecating service request key, binary takes precedence
# Still keeping service key here for API compatibility sake.
class FakeRequestWithService(object):
    environ = {"cinder.context": context.get_admin_context()}
    GET = {"service": "cinder-volume"}


class FakeRequestWithBinary(object):
    environ = {"cinder.context": context.get_admin_context()}
    GET = {"binary": "cinder-volume"}


class FakeRequestWithHost(object):
    environ = {"cinder.context": context.get_admin_context()}
    GET = {"host": "host1"}


# NOTE(uni): deprecating service request key, binary takes precedence
# Still keeping service key here for API compatibility sake.
class FakeRequestWithHostService(object):
    environ = {"cinder.context": context.get_admin_context()}
    GET = {"host": "host1", "service": "cinder-volume"}


class FakeRequestWithHostBinary(object):
    environ = {"cinder.context": context.get_admin_context()}
    GET = {"host": "host1", "binary": "cinder-volume"}


def fake_service_get_all(context):
    return fake_services_list


def fake_service_get_by_host_binary(context, host, binary):
    for service in fake_services_list:
        if service['host'] == host and service['binary'] == binary:
            return service
    return None


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
        {'host': 'host1', 'service': 'cinder-volume',
         'disabled': values['disabled']}


def fake_policy_enforce(context, action, target):
    pass


def fake_utcnow():
    return datetime.datetime(2012, 10, 29, 13, 42, 11)


class ServicesTest(test.TestCase):

    def setUp(self):
        super(ServicesTest, self).setUp()

        self.stubs.Set(db, "service_get_all", fake_service_get_all)
        self.stubs.Set(timeutils, "utcnow", fake_utcnow)
        self.stubs.Set(db, "service_get_by_args",
                       fake_service_get_by_host_binary)
        self.stubs.Set(db, "service_update", fake_service_update)
        self.stubs.Set(policy, "enforce", fake_policy_enforce)

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
                                      2012, 9, 18, 8, 3, 38)}]}
        self.assertEqual(res_dict, response)

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
                                  'host': 'host2',
                                  'zone': 'cinder',
                                  'status': 'disabled', 'state': 'down',
                                  'updated_at': datetime.datetime(
                                      2012, 9, 18, 8, 3, 38),
                                  'disabled_reason': 'test4'},
                                 {'binary': 'cinder-volume',
                                  'host': 'host2',
                                  'zone': 'cinder',
                                  'status': 'disabled', 'state': 'down',
                                  'updated_at': datetime.datetime(
                                      2012, 10, 29, 13, 42, 5),
                                  'disabled_reason': 'test5'},
                                 {'binary': 'cinder-volume',
                                  'host': 'host2',
                                  'zone': 'cinder',
                                  'status': 'enabled', 'state': 'down',
                                  'updated_at': datetime.datetime(
                                      2012, 9, 18, 8, 3, 38),
                                  'disabled_reason': ''}]}
        self.assertEqual(res_dict, response)

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
        self.assertEqual(res_dict, response)

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
             'host': 'host1',
             'zone': 'cinder',
             'status': 'disabled', 'state': 'up',
             'updated_at': datetime.datetime(2012, 10, 29,
                                             13, 42, 5),
             'disabled_reason': 'test2'}]}
        self.assertEqual(res_dict, response)

    def test_services_list_with_service(self):
        req = FakeRequestWithService()
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
        self.assertEqual(res_dict, response)

    def test_services_detail_with_service(self):
        self.ext_mgr.extensions['os-extended-services'] = True
        self.controller = services.ServiceController(self.ext_mgr)
        req = FakeRequestWithService()
        res_dict = self.controller.index(req)

        response = {'services': [
            {'binary': 'cinder-volume',
             'host': 'host1',
             'zone': 'cinder',
             'status': 'disabled',
             'state': 'up',
             'updated_at': datetime.datetime(2012, 10, 29,
                                             13, 42, 5),
             'disabled_reason': 'test2'},
            {'binary': 'cinder-volume',
             'host': 'host2',
             'zone': 'cinder',
             'status': 'disabled',
             'state': 'down',
             'updated_at': datetime.datetime(2012, 9, 18,
                                             8, 3, 38),
             'disabled_reason': 'test4'},
            {'binary': 'cinder-volume',
             'host': 'host2',
             'zone': 'cinder',
             'status': 'disabled',
             'state': 'down',
             'updated_at': datetime.datetime(2012, 10, 29,
                                             13, 42, 5),
             'disabled_reason': 'test5'},
            {'binary': 'cinder-volume',
             'host': 'host2',
             'zone': 'cinder',
             'status': 'enabled',
             'state': 'down',
             'updated_at': datetime.datetime(2012, 9, 18,
                                             8, 3, 38),
             'disabled_reason': ''}]}
        self.assertEqual(res_dict, response)

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
        self.assertEqual(res_dict, response)

    def test_services_detail_with_binary(self):
        self.ext_mgr.extensions['os-extended-services'] = True
        self.controller = services.ServiceController(self.ext_mgr)
        req = FakeRequestWithBinary()
        res_dict = self.controller.index(req)

        response = {'services': [
            {'binary': 'cinder-volume',
             'host': 'host1',
             'zone': 'cinder',
             'status': 'disabled',
             'state': 'up',
             'updated_at': datetime.datetime(2012, 10, 29,
                                             13, 42, 5),
             'disabled_reason': 'test2'},
            {'binary': 'cinder-volume',
             'host': 'host2',
             'zone': 'cinder',
             'status': 'disabled',
             'state': 'down',
             'updated_at': datetime.datetime(2012, 9, 18,
                                             8, 3, 38),
             'disabled_reason': 'test4'},
            {'binary': 'cinder-volume',
             'host': 'host2',
             'zone': 'cinder',
             'status': 'disabled',
             'state': 'down',
             'updated_at': datetime.datetime(2012, 10, 29,
                                             13, 42, 5),
             'disabled_reason': 'test5'},
            {'binary': 'cinder-volume',
             'host': 'host2',
             'zone': 'cinder',
             'status': 'enabled',
             'state': 'down',
             'updated_at': datetime.datetime(2012, 9, 18,
                                             8, 3, 38),
             'disabled_reason': ''}]}
        self.assertEqual(res_dict, response)

    def test_services_list_with_host_service(self):
        req = FakeRequestWithHostService()
        res_dict = self.controller.index(req)

        response = {'services': [
            {'binary': 'cinder-volume',
             'host': 'host1',
             'zone': 'cinder',
             'status': 'disabled',
             'state': 'up',
             'updated_at': datetime.datetime(2012, 10, 29,
                                             13, 42, 5)}]}
        self.assertEqual(res_dict, response)

    def test_services_detail_with_host_service(self):
        self.ext_mgr.extensions['os-extended-services'] = True
        self.controller = services.ServiceController(self.ext_mgr)
        req = FakeRequestWithHostService()
        res_dict = self.controller.index(req)

        response = {'services': [
            {'binary': 'cinder-volume',
             'host': 'host1',
             'zone': 'cinder',
             'status': 'disabled',
             'state': 'up',
             'updated_at': datetime.datetime(2012, 10, 29,
                                             13, 42, 5),
             'disabled_reason': 'test2'}]}
        self.assertEqual(res_dict, response)

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
        self.assertEqual(res_dict, response)

    def test_services_detail_with_host_binary(self):
        self.ext_mgr.extensions['os-extended-services'] = True
        self.controller = services.ServiceController(self.ext_mgr)
        req = FakeRequestWithHostBinary()
        res_dict = self.controller.index(req)

        response = {'services': [
            {'binary': 'cinder-volume',
             'host': 'host1',
             'zone': 'cinder',
             'status': 'disabled',
             'state': 'up',
             'updated_at': datetime.datetime(2012, 10, 29,
                                             13, 42, 5),
             'disabled_reason': 'test2'}]}
        self.assertEqual(res_dict, response)

    def test_services_enable_with_service_key(self):
        body = {'host': 'host1', 'service': 'cinder-volume'}
        req = fakes.HTTPRequest.blank('/v2/fake/os-services/enable')
        res_dict = self.controller.update(req, "enable", body)

        self.assertEqual(res_dict['status'], 'enabled')

    def test_services_enable_with_binary_key(self):
        body = {'host': 'host1', 'binary': 'cinder-volume'}
        req = fakes.HTTPRequest.blank('/v2/fake/os-services/enable')
        res_dict = self.controller.update(req, "enable", body)

        self.assertEqual(res_dict['status'], 'enabled')

    def test_services_disable_with_service_key(self):
        req = fakes.HTTPRequest.blank('/v2/fake/os-services/disable')
        body = {'host': 'host1', 'service': 'cinder-volume'}
        res_dict = self.controller.update(req, "disable", body)

        self.assertEqual(res_dict['status'], 'disabled')

    def test_services_disable_with_binary_key(self):
        req = fakes.HTTPRequest.blank('/v2/fake/os-services/disable')
        body = {'host': 'host1', 'binary': 'cinder-volume'}
        res_dict = self.controller.update(req, "disable", body)

        self.assertEqual(res_dict['status'], 'disabled')

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

        self.assertEqual(res_dict['status'], 'disabled')
        self.assertEqual(res_dict['disabled_reason'], 'test-reason')

    def test_services_disable_log_reason_none(self):
        self.ext_mgr.extensions['os-extended-services'] = True
        self.controller = services.ServiceController(self.ext_mgr)
        req = (
            fakes.HTTPRequest.blank('v1/fake/os-services/disable-log-reason'))
        body = {'host': 'host1',
                'binary': 'cinder-scheduler',
                'disabled_reason': None,
                }
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.update,
                          req, "disable-log-reason", body)

    def test_invalid_reason_field(self):
        reason = ' '
        self.assertFalse(self.controller._is_valid_as_reason(reason))
        reason = 'a' * 256
        self.assertFalse(self.controller._is_valid_as_reason(reason))
        reason = 'it\'s a valid reason.'
        self.assertTrue(self.controller._is_valid_as_reason(reason))
        reason = None
        self.assertFalse(self.controller._is_valid_as_reason(reason))
