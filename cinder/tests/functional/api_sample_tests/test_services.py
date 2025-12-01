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

from cinder.api import microversions as mv
from cinder import context
from cinder import objects
from cinder.tests.functional import api_samples_test_base as test_base
from cinder.tests.unit.api.contrib import test_services


def fake_volume_api_freeze_host(*args, **kwargs):
    pass


def fake_volume_api_thaw_host(*args, **kwargs):
    pass


def fake_volume_api_failover(*args, **kwargs):
    pass


def fake_volume_rpc_api_get_log_levels(*args, **kwargs):
    fake_context = context.RequestContext('user', 'project')
    return objects.LogLevelList(
        fake_context,
        objects=[
            objects.LogLevel(
                fake_context, prefix="cinder.volume.api", level='DEBUG',
            )
        ],
    )


class ServicesSampleJsonTest(test_base.ApiSampleTestBase):
    sample_dir = 'os-services'

    def setUp(self):
        super().setUp()
        self.stub_out(
            'cinder.db.sqlalchemy.api.service_get_all',
            test_services.fake_db_api_service_get_all,
        )
        self.stub_out(
            'cinder.db.sqlalchemy.api.service_get',
            test_services.fake_db_api_service_get,
        )
        self.stub_out(
            'cinder.db.sqlalchemy.api.service_update',
            test_services.fake_db_api_service_update,
        )
        self.stub_out(
            'cinder.volume.api.API.freeze_host',
            fake_volume_api_freeze_host,
        )
        self.stub_out(
            'cinder.volume.api.API.thaw_host',
            fake_volume_api_thaw_host,
        )
        self.stub_out(
            'cinder.volume.api.API.failover',
            fake_volume_api_failover,
        )
        self.stub_out(
            'cinder.volume.rpcapi.VolumeAPI.get_log_levels',
            fake_volume_rpc_api_get_log_levels,
        )
        self.subs = {}

    @test_base.VolumesSampleBase.override_mv(mv.BACKEND_STATE_REPORT)
    def test_service_list(self):
        response = self._do_get('os-services')
        self._verify_response(
            'services-list-response', {}, response, 200
        )

    def test_service_enable(self):
        subs = {'host': 'host1', 'binary': 'cinder-volume'}
        response = self._do_put(
            'os-services/enable', 'service-enable-request', subs
        )
        self._verify_response(
            'service-enable-response', subs, response, 200
        )

    def test_service_disable(self):
        subs = {'host': 'host1', 'binary': 'cinder-volume'}
        response = self._do_put(
            'os-services/disable', 'service-disable-request', subs
        )
        self._verify_response(
            'service-disable-response', subs, response, 200
        )

    def test_service_disable_log_reason(self):
        subs = {
            'host': 'host1',
            'binary': 'cinder-volume',
            'disabled_reason': 'test2',
        }
        response = self._do_put(
            'os-services/disable-log-reason',
            'service-disable-log-reason-request',
            subs
        )
        self._verify_response(
            'service-disable-log-reason-response', subs, response, 200
        )

    def test_service_freeze(self):
        subs = {'host': 'host1'}
        response = self._do_put(
            'os-services/freeze', 'service-freeze-request', subs
        )
        self.assertEqual(200, response.status_code)
        self.assertEqual('', response.text)

    def test_service_thaw(self):
        subs = {'host': 'host1'}
        response = self._do_put(
            'os-services/thaw', 'service-thaw-request', subs
        )
        self.assertEqual(200, response.status_code)
        self.assertEqual('', response.text)

    def test_service_failover_host(self):
        subs = {'host': 'host1'}
        response = self._do_put(
            'os-services/failover_host', 'service-failover-host-request', subs
        )
        self.assertEqual(202, response.status_code)
        self.assertEqual('', response.text)

    @test_base.VolumesSampleBase.override_mv(mv.LOG_LEVEL)
    def test_service_set_log(self):
        response = self._do_put(
            'os-services/set-log', 'service-set-log-request'
        )
        self.assertEqual(202, response.status_code)
        self.assertEqual('', response.text)

    @test_base.VolumesSampleBase.override_mv(mv.LOG_LEVEL)
    def test_service_get_log(self):
        subs = {'host': 'host2'}
        response = self._do_put(
            'os-services/get-log', 'service-get-log-request', subs
        )
        self._verify_response(
            'service-get-log-response', {}, response, 200
        )
