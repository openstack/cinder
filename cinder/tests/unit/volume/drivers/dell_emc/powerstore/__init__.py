# Copyright (c) 2020 Dell Inc. or its subsidiaries.
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import json
from unittest import mock

import requests

from cinder import context
from cinder.tests.unit import test
from cinder.volume import configuration
from cinder.volume.drivers.dell_emc.powerstore import driver
from cinder.volume.drivers.dell_emc.powerstore import options


class MockResponse(requests.Response):
    def __init__(self, content=None, rc=200):
        super(MockResponse, self).__init__()

        if content is None:
            content = []
        if isinstance(content, str):
            content = content.encode()
        self._content = content
        self.request = mock.MagicMock()
        self.status_code = rc

    def json(self, **kwargs):
        if isinstance(self._content, bytes):
            return super(MockResponse, self).json(**kwargs)
        return self._content

    @property
    def text(self):
        if not isinstance(self._content, bytes):
            return json.dumps(self._content)
        return super(MockResponse, self).text


class TestPowerStoreDriver(test.TestCase):
    def setUp(self):
        super(TestPowerStoreDriver, self).setUp()
        self.context = context.RequestContext('fake', 'fake', auth_token=True)
        self.configuration = configuration.Configuration(
            options.POWERSTORE_OPTS,
            configuration.SHARED_CONF_GROUP
        )
        self._set_overrides()
        self.driver = driver.PowerStoreDriver(configuration=self.configuration)
        self.driver.do_setup({})
        self.iscsi_driver = self.driver

        self._override_shared_conf("storage_protocol", override="FC")
        self.fc_driver = driver.PowerStoreDriver(
            configuration=self.configuration
        )
        self.fc_driver.do_setup({})

    def _override_shared_conf(self, *args, **kwargs):
        return self.override_config(*args,
                                    **kwargs,
                                    group=configuration.SHARED_CONF_GROUP)

    def _set_overrides(self):
        # Override the defaults to fake values
        self._override_shared_conf("san_ip", override="127.0.0.1")
        self._override_shared_conf("san_login", override="test")
        self._override_shared_conf("san_password", override="test")
