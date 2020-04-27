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

import inspect
from itertools import chain

import ddt
from oslo_config import cfg

from cinder import exception
from cinder.message import message_field
from cinder.tests.unit import test

CONF = cfg.CONF


@ddt.ddt
class MessageFieldTest(test.TestCase):
    def test_unique_action_ids(self):
        """Assert that no action_id is duplicated."""
        action_ids = [x[0] for x in message_field.Action.ALL]
        self.assertEqual(len(action_ids), len(set(action_ids)))

    def test_all_action_fields_in_ALL(self):
        """Assert that all and only defined fields are in the ALL tuple"""
        defined_fields = [k for k in message_field.Action.__dict__.keys()
                          if k != 'ALL' and not k.startswith('__')]
        for d in defined_fields:
            self.assertIn(getattr(message_field.Action, d),
                          message_field.Action.ALL)
        self.assertEqual(len(message_field.Action.ALL),
                         len(defined_fields))

    def test_unique_detail_ids(self):
        """Assert that no detail_id is duplicated."""
        detail_ids = [x[0] for x in message_field.Detail.ALL]
        self.assertEqual(len(detail_ids), len(set(detail_ids)))

    def test_all_detail_fields_in_ALL(self):
        """Assert that all and only defined fields are in the ALL tuple"""
        defined_fields = [k for k in message_field.Detail.__dict__.keys()
                          if k != 'ALL' and not k.startswith('__')
                          and k != 'EXCEPTION_DETAIL_MAPPINGS']
        for d in defined_fields:
            self.assertIn(getattr(message_field.Detail, d),
                          message_field.Detail.ALL)
        self.assertEqual(len(message_field.Detail.ALL),
                         len(defined_fields))

    known_exceptions = [
        name for name, _ in
        inspect.getmembers(exception, inspect.isclass)]
    mapped_exceptions = list(chain.from_iterable(
        message_field.Detail.EXCEPTION_DETAIL_MAPPINGS.values()))

    @ddt.idata(mapped_exceptions)
    def test_exception_detail_map_no_unknown_exceptions(self, exc):
        """Assert that only known exceptions are in the map."""
        self.assertIn(exc, self.known_exceptions)


@ddt.ddt
class MessageFieldFunctionsTest(test.TestCase):

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
