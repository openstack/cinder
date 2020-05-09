# Copyright 2020 Thomas Goirand <zigo@debian.org>
# Copyright 2020 Infomaniak Networks.
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

from oslo_serialization import jsonutils
import requests

from cinder.tests.functional import functional_helpers


class TestHealthCheckMiddleware(functional_helpers._FunctionalTestBase):

    def test_healthcheck(self):
        # We verify that we return a HTTP200 when calling api_get
        url = 'http://%s:%s/healthcheck' % (self.osapi.host, self.osapi.port)
        response = requests.request(
            'GET',
            url,
            headers={'Accept': 'application/json'})
        output = jsonutils.loads(response.content)
        self.assertEqual(['OK'], output['reasons'])
