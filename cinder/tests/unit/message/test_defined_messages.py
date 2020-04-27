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
from oslo_config import cfg

from cinder.message import defined_messages
from cinder.tests.unit import test

CONF = cfg.CONF


class DefinedMessagesTest(test.TestCase):
    def test_event_id_formats(self):
        """Assert all cinder event ids start with VOLUME_."""
        for attr_name in dir(defined_messages.EventIds):
            if not attr_name.startswith('_'):
                value = getattr(defined_messages.EventIds, attr_name)
                self.assertTrue(value.startswith('VOLUME_'))

    def test_unique_event_ids(self):
        """Assert that no event_id is duplicated."""
        event_ids = []
        for attr_name in dir(defined_messages.EventIds):
            if not attr_name.startswith('_'):
                value = getattr(defined_messages.EventIds, attr_name)
                event_ids.append(value)

        self.assertEqual(len(event_ids), len(set(event_ids)))

    def test_event_id_has_message(self):
        for attr_name in dir(defined_messages.EventIds):
            if not attr_name.startswith('_'):
                value = getattr(defined_messages.EventIds, attr_name)
                msg = defined_messages.event_id_message_map.get(value)
                self.assertGreater(len(msg), 1)
