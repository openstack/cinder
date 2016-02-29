# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

import fixtures as fx
from oslo_log import log as logging
import testtools

from cinder.tests import fixtures


class TestLogging(testtools.TestCase):
    def test_default_logging(self):
        stdlog = self.useFixture(fixtures.StandardLogging())
        root = logging.getLogger()
        # there should be a null handler as well at DEBUG
        self.assertEqual(2, len(root.handlers), root.handlers)
        log = logging.getLogger(__name__)
        log.info("at info")
        log.debug("at debug")
        self.assertIn("at info", stdlog.logger.output)
        self.assertNotIn("at debug", stdlog.logger.output)

        # broken debug messages should still explode, even though we
        # aren't logging them in the regular handler
        self.assertRaises(TypeError, log.debug, "this is broken %s %s", "foo")

        # and, ensure that one of the terrible log messages isn't
        # output at info
        warn_log = logging.getLogger('migrate.versioning.api')
        warn_log.info("warn_log at info, should be skipped")
        warn_log.error("warn_log at error")
        self.assertIn("warn_log at error", stdlog.logger.output)
        self.assertNotIn("warn_log at info", stdlog.logger.output)

    def test_debug_logging(self):
        self.useFixture(fx.EnvironmentVariable('OS_DEBUG', '1'))

        stdlog = self.useFixture(fixtures.StandardLogging())
        root = logging.getLogger()
        # there should no longer be a null handler
        self.assertEqual(1, len(root.handlers), root.handlers)
        log = logging.getLogger(__name__)
        log.info("at info")
        log.debug("at debug")
        self.assertIn("at info", stdlog.logger.output)
        self.assertIn("at debug", stdlog.logger.output)
