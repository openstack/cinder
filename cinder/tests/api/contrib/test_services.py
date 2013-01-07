# Copyright 2012 IBM
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


from cinder.api.contrib import services
from cinder import context
from cinder import db
from cinder import exception
from cinder.openstack.common import timeutils
from cinder import policy
from cinder import test
from cinder.tests.api import fakes
from datetime import datetime


fake_services_list = [{'binary': 'cinder-scheduler',
                       'host': 'host1',
                       'availability_zone': 'cinder',
                       'id': 1,
                       'disabled': True,
                       'updated_at': datetime(2012, 10, 29, 13, 42, 2),
                       'created_at': datetime(2012, 9, 18, 2, 46, 27)},
                      {'binary': 'cinder-volume',
                       'host': 'host1',
                       'availability_zone': 'cinder',
                       'id': 2,
                       'disabled': True,
                       'updated_at': datetime(2012, 10, 29, 13, 42, 5),
                       'created_at': datetime(2012, 9, 18, 2, 46, 27)},
                      {'binary': 'cinder-scheduler',
                       'host': 'host2',
                       'availability_zone': 'cinder',
                       'id': 3,
                       'disabled': False,
                       'updated_at': datetime(2012, 9, 19, 6, 55, 34),
                       'created_at': datetime(2012, 9, 18, 2, 46, 28)},
                      {'binary': 'cinder-volume',
                       'host': 'host2',
                       'availability_zone': 'cinder',
                       'id': 4,
                       'disabled': True,
                       'updated_at': datetime(2012, 9, 18, 8, 3, 38),
                       'created_at': datetime(2012, 9, 18, 2, 46, 28)},
                      ]


class FakeRequest(object):
        environ = {"cinder.context": context.get_admin_context()}
        GET = {}


class FakeRequestWithSevice(object):
        environ = {"cinder.context": context.get_admin_context()}
        GET = {"service": "cinder-volume"}


class FakeRequestWithHost(object):
        environ = {"cinder.context": context.get_admin_context()}
        GET = {"host": "host1"}


class FakeRequestWithHostService(object):
        environ = {"cinder.context": context.get_admin_context()}
        GET = {"host": "host1", "service": "cinder-volume"}


def fake_servcie_get_all(context):
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
    return datetime(2012, 10, 29, 13, 42, 11)


class ServicesTest(test.TestCase):

    def setUp(self):
        super(ServicesTest, self).setUp()

        self.stubs.Set(db, "service_get_all", fake_servcie_get_all)
        self.stubs.Set(timeutils, "utcnow", fake_utcnow)
        self.stubs.Set(db, "service_get_by_args",
                       fake_service_get_by_host_binary)
        self.stubs.Set(db, "service_update", fake_service_update)
        self.stubs.Set(policy, "enforce", fake_policy_enforce)

        self.context = context.get_admin_context()
        self.controller = services.ServiceController()

    def tearDown(self):
        super(ServicesTest, self).tearDown()

    def test_services_list(self):
        req = FakeRequest()
        res_dict = self.controller.index(req)

        response = {'services': [{'binary': 'cinder-scheduler',
                    'host': 'host1', 'zone': 'cinder',
                    'status': 'disabled', 'state': 'up',
                    'updated_at': datetime(2012, 10, 29, 13, 42, 2)},
                    {'binary': 'cinder-volume',
                     'host': 'host1', 'zone': 'cinder',
                     'status': 'disabled', 'state': 'up',
                     'updated_at': datetime(2012, 10, 29, 13, 42, 5)},
                    {'binary': 'cinder-scheduler', 'host': 'host2',
                     'zone': 'cinder',
                     'status': 'enabled', 'state': 'up',
                     'updated_at': datetime(2012, 9, 19, 6, 55, 34)},
                    {'binary': 'cinder-volume', 'host': 'host2',
                     'zone': 'cinder',
                     'status': 'disabled', 'state': 'up',
                     'updated_at': datetime(2012, 9, 18, 8, 3, 38)}]}
        self.assertEqual(res_dict, response)

    def test_services_list_with_host(self):
        req = FakeRequestWithHost()
        res_dict = self.controller.index(req)

        response = {'services': [{'binary': 'cinder-scheduler',
                                  'host': 'host1',
                                  'zone': 'cinder',
                                  'status': 'disabled', 'state': 'up',
                                  'updated_at': datetime(2012, 10,
                                                         29, 13, 42, 2)},
                                 {'binary': 'cinder-volume', 'host': 'host1',
                                  'zone': 'cinder',
                                  'status': 'disabled', 'state': 'up',
                                  'updated_at': datetime(2012, 10, 29,
                                                         13, 42, 5)}]}
        self.assertEqual(res_dict, response)

    def test_services_list_with_service(self):
        req = FakeRequestWithSevice()
        res_dict = self.controller.index(req)

        response = {'services': [{'binary': 'cinder-volume',
                                  'host': 'host1',
                                  'zone': 'cinder',
                                  'status': 'disabled',
                                  'state': 'up',
                                  'updated_at': datetime(2012, 10, 29,
                                                         13, 42, 5)},
                                 {'binary': 'cinder-volume',
                                  'host': 'host2',
                                  'zone': 'cinder',
                                  'status': 'disabled',
                                  'state': 'up',
                                  'updated_at': datetime(2012, 9, 18,
                                                         8, 3, 38)}]}
        self.assertEqual(res_dict, response)

    def test_services_list_with_host_service(self):
        req = FakeRequestWithHostService()
        res_dict = self.controller.index(req)

        response = {'services': [{'binary': 'cinder-volume',
                                  'host': 'host1',
                                  'zone': 'cinder',
                                  'status': 'disabled',
                                  'state': 'up',
                                  'updated_at': datetime(2012, 10, 29,
                                                         13, 42, 5)}]}
        self.assertEqual(res_dict, response)

    def test_services_enable(self):
        body = {'host': 'host1', 'service': 'cinder-volume'}
        req = fakes.HTTPRequest.blank('/v1/fake/os-services/enable')
        res_dict = self.controller.update(req, "enable", body)

        self.assertEqual(res_dict['disabled'], False)

    def test_services_disable(self):
        req = fakes.HTTPRequest.blank('/v1/fake/os-services/disable')
        body = {'host': 'host1', 'service': 'cinder-volume'}
        res_dict = self.controller.update(req, "disable", body)

        self.assertEqual(res_dict['disabled'], True)
