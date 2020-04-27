# Copyright (c) 2011 OpenStack Foundation
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
from unittest import mock

import iso8601
from oslo_utils import timeutils
import webob.exc

from cinder.api.contrib import hosts as os_hosts
from cinder.common import constants
from cinder import context
from cinder import exception
from cinder.objects import service
from cinder.tests.unit import fake_constants
from cinder.tests.unit import test
from cinder.tests.unit import utils as test_utils


created_time = datetime.datetime(2012, 11, 14, 1, 20, 41, 95099)
curr_time = datetime.datetime(2013, 7, 3, 0, 0, 1)

SERVICE_LIST = [
    {'created_at': created_time, 'updated_at': curr_time,
     'host': 'test.host.1', 'topic': 'cinder-volume', 'disabled': 0,
     'availability_zone': 'cinder',
     'uuid': 'a3a593da-7f8d-4bb7-8b4c-f2bc1e0b4824'},
    {'created_at': created_time, 'updated_at': curr_time,
     'host': 'test.host.1', 'topic': 'cinder-volume', 'disabled': 0,
     'availability_zone': 'cinder',
     'uuid': '4200b32b-0bf9-436c-86b2-0675f6ac218e'},
    {'created_at': created_time, 'updated_at': curr_time,
     'host': 'test.host.1', 'topic': 'cinder-volume', 'disabled': 0,
     'availability_zone': 'cinder',
     'uuid': '6d91e7f5-ca17-4e3b-bf4f-19ca77166dd7'},
    {'created_at': created_time, 'updated_at': curr_time,
     'host': 'test.host.1', 'topic': 'cinder-volume', 'disabled': 0,
     'availability_zone': 'cinder',
     'uuid': '18417850-2ca9-43d1-9619-ae16bfb0f655'},
    {'created_at': created_time, 'updated_at': None,
     'host': 'test.host.1', 'topic': 'cinder-volume', 'disabled': 0,
     'availability_zone': 'cinder',
     'uuid': 'f838f35c-4035-464f-9792-ce60e390c13d'},
]

LIST_RESPONSE = [{'service-status': 'available', 'service': 'cinder-volume',
                  'zone': 'cinder', 'service-state': 'enabled',
                  'host_name': 'test.host.1', 'last-update': curr_time,
                  },
                 {'service-status': 'available', 'service': 'cinder-volume',
                  'zone': 'cinder', 'service-state': 'enabled',
                  'host_name': 'test.host.1', 'last-update': curr_time,
                  },
                 {'service-status': 'available', 'service': 'cinder-volume',
                  'zone': 'cinder', 'service-state': 'enabled',
                  'host_name': 'test.host.1', 'last-update': curr_time,
                  },
                 {'service-status': 'available', 'service': 'cinder-volume',
                  'zone': 'cinder', 'service-state': 'enabled',
                  'host_name': 'test.host.1', 'last-update': curr_time,
                  },
                 {'service-status': 'unavailable', 'service': 'cinder-volume',
                  'zone': 'cinder', 'service-state': 'enabled',
                  'host_name': 'test.host.1', 'last-update': None,
                  }, ]


def stub_utcnow(with_timezone=False):
    tzinfo = iso8601.UTC if with_timezone else None
    return datetime.datetime(2013, 7, 3, 0, 0, 2, tzinfo=tzinfo)


class FakeRequest(object):
    environ = {'cinder.context': context.get_admin_context()}
    GET = {}


class FakeRequestWithcinderZone(object):
    environ = {'cinder.context': context.get_admin_context()}
    GET = {'zone': 'cinder'}


class HostTestCase(test.TestCase):
    """Test Case for hosts."""

    def setUp(self):
        super(HostTestCase, self).setUp()
        self.controller = os_hosts.HostController()
        self.req = FakeRequest()
        self.patch('cinder.db.service_get_all', autospec=True,
                   return_value=SERVICE_LIST)
        self.mock_object(timeutils, 'utcnow', stub_utcnow)

    def _test_host_update(self, host, key, val, expected_value):
        body = {key: val}
        result = self.controller.update(self.req, host, body=body)
        self.assertEqual(expected_value, result[key])

    def test_list_hosts(self):
        """Verify that the volume hosts are returned."""
        hosts = os_hosts._list_hosts(self.req)
        self.assertEqual(LIST_RESPONSE, hosts)

        cinder_hosts = os_hosts._list_hosts(self.req, constants.VOLUME_BINARY)
        expected = [host for host in LIST_RESPONSE
                    if host['service'] == constants.VOLUME_BINARY]
        self.assertEqual(expected, cinder_hosts)

    def test_list_hosts_with_zone(self):
        req = FakeRequestWithcinderZone()
        hosts = os_hosts._list_hosts(req)
        self.assertEqual(LIST_RESPONSE, hosts)

    def test_bad_status_value(self):
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          self.req, 'test.host.1', body={'status': 'bad'})
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.update,
                          self.req,
                          'test.host.1',
                          body={'status': 'disablabc'})

    def test_bad_update_key(self):
        bad_body = {'crazy': 'bad'}
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          self.req, 'test.host.1', body=bad_body)

    def test_bad_update_key_and_correct_udpate_key(self):
        bad_body = {'status': 'disable', 'crazy': 'bad'}
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          self.req, 'test.host.1', body=bad_body)

    def test_good_udpate_keys(self):
        body = {'status': 'disable'}
        self.assertRaises(NotImplementedError, self.controller.update,
                          self.req, 'test.host.1', body=body)

    def test_bad_host(self):
        self.assertRaises(exception.HostNotFound,
                          self.controller.update,
                          self.req,
                          'bogus_host_name',
                          body={'disabled': 0})

    @mock.patch.object(service.Service, 'get_by_host_and_topic')
    def test_show_host(self, mock_get_host):
        host = 'test_host'
        test_service = service.Service(id=1, host=host,
                                       binary=constants.VOLUME_BINARY,
                                       topic=constants.VOLUME_TOPIC)
        mock_get_host.return_value = test_service

        ctxt1 = context.RequestContext(project_id=fake_constants.PROJECT_ID,
                                       is_admin=True)
        ctxt2 = context.RequestContext(project_id=fake_constants.PROJECT2_ID,
                                       is_admin=True)
        # Create two volumes with different project.
        volume1 = test_utils.create_volume(ctxt1,
                                           host=host, size=1)
        test_utils.create_volume(ctxt2, host=host, size=1)
        # This volume is not on the same host. It should not be counted.
        test_utils.create_volume(ctxt2, host='fake_host', size=1)
        test_utils.create_snapshot(ctxt1, volume_id=volume1.id)

        resp = self.controller.show(self.req, host)

        host_resp = resp['host']
        # There are 3 resource list: total, project1, project2
        self.assertEqual(3, len(host_resp))
        expected = [
            {
                "resource": {
                    "volume_count": "2",
                    "total_volume_gb": "2",
                    "host": "test_host",
                    "total_snapshot_gb": "1",
                    "project": "(total)",
                    "snapshot_count": "1"}
            },
            {
                "resource": {
                    "volume_count": "1",
                    "total_volume_gb": "1",
                    "host": "test_host",
                    "project": fake_constants.PROJECT2_ID,
                    "total_snapshot_gb": "0",
                    "snapshot_count": "0"}
            },
            {
                "resource": {
                    "volume_count": "1",
                    "total_volume_gb": "1",
                    "host": "test_host",
                    "total_snapshot_gb": "1",
                    "project": fake_constants.PROJECT_ID,
                    "snapshot_count": "1"}
            }
        ]
        self.assertListEqual(expected, sorted(
            host_resp, key=lambda h: h['resource']['project']))

    def test_show_forbidden(self):
        self.req.environ['cinder.context'].is_admin = False
        dest = 'dummydest'
        self.assertRaises(exception.PolicyNotAuthorized,
                          self.controller.show,
                          self.req, dest)
        self.req.environ['cinder.context'].is_admin = True

    def test_show_host_not_exist(self):
        """A host given as an argument does not exists."""
        self.req.environ['cinder.context'].is_admin = True
        dest = 'dummydest'
        self.assertRaises(exception.ServiceNotFound,
                          self.controller.show,
                          self.req, dest)
