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
from oslo_serialization import jsonutils
from six.moves import http_client
import webob

from cinder.api import microversions as mv
from cinder.api.v3 import router as router_v3
from cinder.api.v3 import workers
from cinder.common import constants
from cinder import context
from cinder import objects
from cinder import test
from cinder.tests.unit.api import fakes
from cinder.tests.unit import fake_constants as fake


SERVICES = (
    [objects.Service(id=1, host='host1', binary=constants.VOLUME_BINARY,
                     cluster_name='mycluster'),
     objects.Service(id=2, host='host2', binary=constants.VOLUME_BINARY,
                     cluster_name='mycluster')],
    [objects.Service(id=3, host='host3', binary=constants.VOLUME_BINARY,
                     cluster_name='mycluster'),
     objects.Service(id=4, host='host4', binary=constants.VOLUME_BINARY,
                     cluster_name='mycluster')],
)


def app():
    # no auth, just let environ['cinder.context'] pass through
    api = router_v3.APIRouter()
    mapper = fakes.urlmap.URLMap()
    mapper['/v3'] = api
    return mapper


@ddt.ddt
class WorkersTestCase(test.TestCase):
    """Tes Case for the cleanup of Workers entries."""
    def setUp(self):
        super(WorkersTestCase, self).setUp()

        self.context = context.RequestContext(user_id=None,
                                              project_id=fake.PROJECT_ID,
                                              is_admin=True,
                                              read_deleted='no',
                                              overwrite=False)
        self.controller = workers.create_resource()

    def _get_resp_post(self, body, version=mv.WORKERS_CLEANUP, ctxt=None):
        """Helper to execute a POST workers API call."""
        req = webob.Request.blank('/v3/%s/workers/cleanup' % fake.PROJECT_ID)
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.headers['OpenStack-API-Version'] = 'volume ' + version
        req.environ['cinder.context'] = ctxt or self.context
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(app())
        return res

    @mock.patch('cinder.scheduler.rpcapi.SchedulerAPI.work_cleanup')
    def test_cleanup_old_api_version(self, rpc_mock):
        res = self._get_resp_post({}, mv.get_prior_version(mv.WORKERS_CLEANUP))
        self.assertEqual(http_client.NOT_FOUND, res.status_code)
        rpc_mock.assert_not_called()

    @mock.patch('cinder.scheduler.rpcapi.SchedulerAPI.work_cleanup')
    def test_cleanup_not_authorized(self, rpc_mock):
        ctxt = context.RequestContext(user_id=None,
                                      project_id=fake.PROJECT_ID,
                                      is_admin=False,
                                      read_deleted='no',
                                      overwrite=False)
        res = self._get_resp_post({}, ctxt=ctxt)
        self.assertEqual(http_client.FORBIDDEN, res.status_code)
        rpc_mock.assert_not_called()

    @ddt.data({'binary': 'nova-scheduler'},
              {'disabled': 'sure'}, {'is_up': 'nop'},
              {'resource_type': 'service'}, {'resource_id': 'non UUID'},
              {'is_up': 11}, {'disabled': 11},
              {'is_up': '   true  '}, {'disabled': '   false  '})
    @mock.patch('cinder.scheduler.rpcapi.SchedulerAPI.work_cleanup')
    def test_cleanup_wrong_param(self, body, rpc_mock):
        res = self._get_resp_post(body)
        self.assertEqual(http_client.BAD_REQUEST, res.status_code)
        expected = 'Invalid input'
        self.assertIn(expected, res.json['badRequest']['message'])
        rpc_mock.assert_not_called()

    @ddt.data({'fake_key': 'value'})
    @mock.patch('cinder.scheduler.rpcapi.SchedulerAPI.work_cleanup')
    def test_cleanup_with_additional_properties(self, body, rpc_mock):
        res = self._get_resp_post(body)
        self.assertEqual(http_client.BAD_REQUEST, res.status_code)
        expected = 'Additional properties are not allowed'
        self.assertIn(expected, res.json['badRequest']['message'])
        rpc_mock.assert_not_called()

    def _expected_services(self, cleaning, unavailable):
        def service_view(service):
            return {'id': service.id, 'host': service.host,
                    'binary': service.binary,
                    'cluster_name': service.cluster_name}
        return {'cleaning': [service_view(s) for s in cleaning],
                'unavailable': [service_view(s) for s in unavailable]}

    @ddt.data({'service_id': 10}, {'binary': 'cinder-volume'},
              {'binary': 'cinder-scheduler'}, {'disabled': 'false'},
              {'is_up': 'no'}, {'resource_type': 'Volume'},
              {'resource_id': fake.VOLUME_ID, 'host': 'host@backend'},
              {'host': 'host@backend#pool'},
              {'cluster_name': 'cluster@backend'},
              {'cluster_name': 'cluster@backend#pool'},
              {'service_id': None},
              {'cluster_name': None}, {'host': None},
              {'resource_type': ''}, {'resource_type': None},
              {'resource_id': None})
    @mock.patch('cinder.scheduler.rpcapi.SchedulerAPI.work_cleanup',
                return_value=SERVICES)
    def test_cleanup_params(self, body, rpc_mock):
        res = self._get_resp_post(body)
        self.assertEqual(http_client.ACCEPTED, res.status_code)
        rpc_mock.assert_called_once_with(self.context, mock.ANY)
        cleanup_request = rpc_mock.call_args[0][1]
        for key, value in body.items():
            if key in ('disabled', 'is_up'):
                if value is not None:
                    value = value == 'true'
            self.assertEqual(value, getattr(cleanup_request, key))
        self.assertEqual(self._expected_services(*SERVICES), res.json)

    @mock.patch('cinder.db.worker_get_all',
                return_value=[mock.Mock(service_id=1, resource_type='Volume')])
    @mock.patch('cinder.scheduler.rpcapi.SchedulerAPI.work_cleanup',
                return_value=SERVICES)
    def test_cleanup_missing_location_ok(self, rpc_mock, worker_mock):
        res = self._get_resp_post({'resource_id': fake.VOLUME_ID})
        self.assertEqual(http_client.ACCEPTED, res.status_code)
        rpc_mock.assert_called_once_with(self.context, mock.ANY)
        cleanup_request = rpc_mock.call_args[0][1]
        self.assertEqual(fake.VOLUME_ID, cleanup_request.resource_id)
        self.assertEqual(1, cleanup_request.service_id)
        self.assertEqual('Volume', cleanup_request.resource_type)
        self.assertEqual(self._expected_services(*SERVICES), res.json)

    @mock.patch('cinder.scheduler.rpcapi.SchedulerAPI.work_cleanup')
    def test_cleanup_missing_location_fail_none(self, rpc_mock):
        res = self._get_resp_post({'resource_id': fake.VOLUME_ID})
        self.assertEqual(http_client.BAD_REQUEST, res.status_code)
        self.assertIn('Invalid input', res.json['badRequest']['message'])
        rpc_mock.assert_not_called()

    @mock.patch('cinder.scheduler.rpcapi.SchedulerAPI.work_cleanup',
                return_value=[1, 2])
    def test_cleanup_missing_location_fail_multiple(self, rpc_mock):
        res = self._get_resp_post({'resource_id': fake.VOLUME_ID})
        self.assertEqual(http_client.BAD_REQUEST, res.status_code)
        self.assertIn('Invalid input', res.json['badRequest']['message'])
        rpc_mock.assert_not_called()
