# Copyright 2016 Mirantis Inc.
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

import mock

from cinder.common import constants
from cinder import service
from cinder import test


class SetupProfilerTestCase(test.TestCase):
    def setUp(self):
        super(SetupProfilerTestCase, self).setUp()
        service.osprofiler_initializer = mock.MagicMock()
        service.profiler = mock.MagicMock()
        service.profiler_opts = mock.MagicMock()
        service.osprofiler_initializer.init_from_conf = mock.MagicMock()

    def test_profiler_not_present(self):
        service.profiler = None
        service.LOG.debug = mock.MagicMock()
        service.setup_profiler(constants.VOLUME_BINARY, "localhost")
        service.LOG.debug.assert_called_once_with("osprofiler is not present")

    @mock.patch("cinder.service.context")
    def test_profiler_enabled(self, context):
        service.CONF.profiler.enabled = True
        return_value = {"Meaning Of Life": 42}
        context.get_admin_context().to_dict.return_value = return_value
        service.setup_profiler(constants.VOLUME_BINARY, "localhost")
        service.osprofiler_initializer.init_from_conf.assert_called_once_with(
            conf=service.CONF,
            context=return_value,
            project="cinder",
            service=constants.VOLUME_BINARY,
            host="localhost")

    def test_profiler_disabled(self):
        service.CONF.profiler.enabled = False
        service.setup_profiler(constants.VOLUME_BINARY, "localhost")
        service.osprofiler_initializer.init_from_conf.assert_not_called()
