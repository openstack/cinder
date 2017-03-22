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

from oslo_config import cfg

from cinder import exception
from cinder.message import message_field
from cinder import test

CONF = cfg.CONF


@ddt.ddt
class MessageFieldTest(test.TestCase):

    @ddt.data({'id': '001', 'content': 'schedule allocate volume'},
              {'id': '002', 'content': 'attach volume'},
              {'id': 'invalid', 'content': None})
    @ddt.unpack
    def test_translate_action(self, id, content):
        result = message_field.translate_action(id)
        if content is None:
            content = 'unknown action'
        self.assertEqual(content, result)

    @ddt.data({'id': '001',
               'content': 'An unknown error occurred.'},
              {'id': '002',
               'content': 'Driver is not initialized at present.'},
              {'id': 'invalid', 'content': None})
    @ddt.unpack
    def test_translate_detail(self, id, content):
        result = message_field.translate_detail(id)
        if content is None:
            content = 'An unknown error occurred.'
        self.assertEqual(content, result)

    @ddt.data({'exception': exception.DriverNotInitialized(),
               'detail': '',
               'expected': '002'},
              {'exception': exception.CinderException(),
               'detail': '',
               'expected': '001'},
              {'exception': exception.CinderException(),
               'detail': message_field.Detail.QUOTA_EXCEED,
               'expected': '007'},
              {'exception': '', 'detail': message_field.Detail.QUOTA_EXCEED,
               'expected': '007'})
    @ddt.unpack
    def translate_detail_id(self, exception, detail, expected):
        result = message_field.translate_detail_id(exception, detail)
        self.assertEqual(expected, result)
