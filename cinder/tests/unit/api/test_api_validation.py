# Copyright (C) 2017 NTT DATA
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

from http import client as http
import re

import fixtures

from cinder.api.openstack import api_version_request as api_version
from cinder.api import validation
from cinder.api.validation import parameter_types
from cinder import exception
from cinder.tests.unit import test


class FakeRequest(object):
    api_version_request = api_version.APIVersionRequest("3.0")
    environ = {}


class ValidationRegex(test.TestCase):

    def test_build_regex_range(self):

        def _get_all_chars():
            for i in range(0x7F):
                yield chr(i)

        self.useFixture(fixtures.MonkeyPatch(
            'cinder.api.validation.parameter_types._get_all_chars',
            _get_all_chars))

        r = parameter_types._build_regex_range(ws=False)
        self.assertEqual(re.escape('!') + '-' + re.escape('~'), r)

        # if we allow whitespace the range starts earlier
        r = parameter_types._build_regex_range(ws=True)
        self.assertEqual(re.escape(' ') + '-' + re.escape('~'), r)

        # excluding a character will give us 2 ranges
        r = parameter_types._build_regex_range(ws=True, exclude=['A'])
        self.assertEqual(re.escape(' ') + '-' + re.escape('@') +
                         'B' + '-' + re.escape('~'), r)

        # inverting which gives us all the initial unprintable characters.
        r = parameter_types._build_regex_range(ws=False, invert=True)
        self.assertEqual(re.escape('\x00') + '-' + re.escape(' '), r)

        # excluding characters that create a singleton. Naively this would be:
        # ' -@B-BD-~' which seems to work, but ' -@BD-~' is more natural.
        r = parameter_types._build_regex_range(ws=True, exclude=['A', 'C'])
        self.assertEqual(re.escape(' ') + '-' + re.escape('@') +
                         'B' + 'D' + '-' + re.escape('~'), r)

        # ws=True means the positive regex has printable whitespaces,
        # so the inverse will not. The inverse will include things we
        # exclude.
        r = parameter_types._build_regex_range(
            ws=True, exclude=['A', 'B', 'C', 'Z'], invert=True)
        self.assertEqual(re.escape('\x00') + '-' + re.escape('\x1f') +
                         'A-CZ', r)


class APIValidationTestCase(test.TestCase):

    def setUp(self, schema=None):
        super(APIValidationTestCase, self).setUp()
        self.post = None

        if schema is not None:
            @validation.schema(request_body_schema=schema)
            def post(req, body):
                return 'Validation succeeded.'

            self.post = post

    def check_validation_error(self, method, body, expected_detail, req=None):
        if not req:
            req = FakeRequest()
        try:
            method(body=body, req=req,)
        except exception.ValidationError as ex:
            self.assertEqual(http.BAD_REQUEST, ex.kwargs['code'])
            if isinstance(expected_detail, list):
                self.assertIn(ex.kwargs['detail'], expected_detail,
                              'Exception details did not match expected')
            elif not re.match(expected_detail, ex.kwargs['detail']):
                self.assertEqual(expected_detail, ex.kwargs['detail'],
                                 'Exception details did not match expected')
        except Exception as ex:
            self.fail('An unexpected exception happens: %s' % ex)
        else:
            self.fail('Any exception did not happen.')


class RequiredDisableTestCase(APIValidationTestCase):

    def setUp(self):
        schema = {
            'type': 'object',
            'properties': {
                'foo': {
                    'type': 'integer',
                },
            },
        }
        super(RequiredDisableTestCase, self).setUp(schema=schema)

    def test_validate_required_disable(self):
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': 1}, req=FakeRequest()))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'abc': 1}, req=FakeRequest()))


class RequiredEnableTestCase(APIValidationTestCase):

    def setUp(self):
        schema = {
            'type': 'object',
            'properties': {
                'foo': {
                    'type': 'integer',
                },
            },
            'required': ['foo']
        }
        super(RequiredEnableTestCase, self).setUp(schema=schema)

    def test_validate_required_enable(self):
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': 1}, req=FakeRequest()))

    def test_validate_required_enable_fails(self):
        detail = "'foo' is a required property"
        self.check_validation_error(self.post, body={'abc': 1},
                                    expected_detail=detail)


class AdditionalPropertiesEnableTestCase(APIValidationTestCase):

    def setUp(self):
        schema = {
            'type': 'object',
            'properties': {
                'foo': {
                    'type': 'integer',
                },
            },
            'required': ['foo'],
        }
        super(AdditionalPropertiesEnableTestCase, self).setUp(schema=schema)

    def test_validate_additionalProperties_enable(self):
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': 1}, req=FakeRequest()))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': 1, 'ext': 1},
                                   req=FakeRequest()))


class AdditionalPropertiesDisableTestCase(APIValidationTestCase):

    def setUp(self):
        schema = {
            'type': 'object',
            'properties': {
                'foo': {
                    'type': 'integer',
                },
            },
            'required': ['foo'],
            'additionalProperties': False,
        }
        super(AdditionalPropertiesDisableTestCase, self).setUp(schema=schema)

    def test_validate_additionalProperties_disable(self):
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': 1}, req=FakeRequest()))

    def test_validate_additionalProperties_disable_fails(self):
        detail = "Additional properties are not allowed ('ext' was unexpected)"
        self.check_validation_error(self.post, body={'foo': 1, 'ext': 1},
                                    expected_detail=detail)


class PatternPropertiesTestCase(APIValidationTestCase):

    def setUp(self):
        schema = {
            'patternProperties': {
                '^[a-zA-Z0-9]{1,10}$': {
                    'type': 'string'
                },
            },
            'additionalProperties': False,
        }
        super(PatternPropertiesTestCase, self).setUp(schema=schema)

    def test_validate_patternProperties(self):
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': 'bar'}, req=FakeRequest()))

    def test_validate_patternProperties_fails(self):
        details = [
            "Additional properties are not allowed ('__' was unexpected)",
            "'__' does not match any of the regexes: '^[a-zA-Z0-9]{1,10}$'"
        ]
        self.check_validation_error(self.post, body={'__': 'bar'},
                                    expected_detail=details)

        details = [
            "'' does not match any of the regexes: '^[a-zA-Z0-9]{1,10}$'",
            "Additional properties are not allowed ('' was unexpected)"
        ]
        self.check_validation_error(self.post, body={'': 'bar'},
                                    expected_detail=details)

        details = [
            ("'0123456789a' does not match any of the regexes: "
             "'^[a-zA-Z0-9]{1,10}$'"),
            ("Additional properties are not allowed ('0123456789a' was"
             " unexpected)")
        ]
        self.check_validation_error(self.post, body={'0123456789a': 'bar'},
                                    expected_detail=details)

        detail = "expected string or bytes-like object"
        self.check_validation_error(self.post, body={None: 'bar'},
                                    expected_detail=detail)


class StringTestCase(APIValidationTestCase):

    def setUp(self):
        schema = {
            'type': 'object',
            'properties': {
                'foo': {
                    'type': 'string',
                },
            },
        }
        super(StringTestCase, self).setUp(schema=schema)

    def test_validate_string(self):
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': 'abc'}, req=FakeRequest()))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': '0'}, req=FakeRequest()))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': ''}, req=FakeRequest()))

    def test_validate_string_fails(self):
        detail = ("Invalid input for field/attribute foo. Value: 1."
                  " 1 is not of type 'string'")
        self.check_validation_error(self.post, body={'foo': 1},
                                    expected_detail=detail)

        detail = ("Invalid input for field/attribute foo. Value: 1.5."
                  " 1.5 is not of type 'string'")
        self.check_validation_error(self.post, body={'foo': 1.5},
                                    expected_detail=detail)

        detail = ("Invalid input for field/attribute foo. Value: True."
                  " True is not of type 'string'")
        self.check_validation_error(self.post, body={'foo': True},
                                    expected_detail=detail)


class StringLengthTestCase(APIValidationTestCase):

    def setUp(self):
        schema = {
            'type': 'object',
            'properties': {
                'foo': {
                    'type': 'string',
                    'minLength': 1,
                    'maxLength': 10,
                },
            },
        }
        super(StringLengthTestCase, self).setUp(schema=schema)

    def test_validate_string_length(self):
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': '0'}, req=FakeRequest()))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': '0123456789'},
                                   req=FakeRequest()))

    def test_validate_string_length_fails(self):
        detail = ("Invalid input for field/attribute foo. Value: ."
                  " '' is too short")
        self.check_validation_error(self.post, body={'foo': ''},
                                    expected_detail=detail)

        detail = ("Invalid input for field/attribute foo. Value: 0123456789a."
                  " '0123456789a' is too long")
        self.check_validation_error(self.post, body={'foo': '0123456789a'},
                                    expected_detail=detail)


class IntegerTestCase(APIValidationTestCase):

    def setUp(self):
        schema = {
            'type': 'object',
            'properties': {
                'foo': {
                    'type': ['integer', 'string'],
                    'pattern': '^[0-9]+$',
                },
            },
        }
        super(IntegerTestCase, self).setUp(schema=schema)

    def test_validate_integer(self):
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': 1}, req=FakeRequest()))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': '1'}, req=FakeRequest()))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': '0123456789'},
                                   req=FakeRequest()))

    def test_validate_integer_fails(self):
        detail = ("Invalid input for field/attribute foo. Value: abc."
                  " 'abc' does not match '^[0-9]+$'")
        self.check_validation_error(self.post, body={'foo': 'abc'},
                                    expected_detail=detail)

        detail = ("Invalid input for field/attribute foo. Value: True."
                  " True is not of type 'integer', 'string'")
        self.check_validation_error(self.post, body={'foo': True},
                                    expected_detail=detail)

        detail = ("Invalid input for field/attribute foo. Value: 0xffff."
                  " '0xffff' does not match '^[0-9]+$'")
        self.check_validation_error(self.post, body={'foo': '0xffff'},
                                    expected_detail=detail)

        detail = ("Invalid input for field/attribute foo. Value: 1.0."
                  " 1.0 is not of type 'integer', 'string'")
        self.check_validation_error(self.post, body={'foo': 1.0},
                                    expected_detail=detail)

        detail = ("Invalid input for field/attribute foo. Value: 1.0."
                  " '1.0' does not match '^[0-9]+$'")
        self.check_validation_error(self.post, body={'foo': '1.0'},
                                    expected_detail=detail)


class IntegerRangeTestCase(APIValidationTestCase):

    def setUp(self):
        schema = {
            'type': 'object',
            'properties': {
                'foo': {
                    'type': ['integer', 'string'],
                    'pattern': '^[0-9]+$',
                    'minimum': 1,
                    'maximum': 10,
                },
            },
        }
        super(IntegerRangeTestCase, self).setUp(schema=schema)

    def test_validate_integer_range(self):
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': 1}, req=FakeRequest()))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': 10}, req=FakeRequest()))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': '1'}, req=FakeRequest()))

    def test_validate_integer_range_fails(self):
        detail = ("Invalid input for field/attribute foo. Value: 0."
                  " 0(.0)? is less than the minimum of 1")
        self.check_validation_error(self.post, body={'foo': 0},
                                    expected_detail=detail)

        detail = ("Invalid input for field/attribute foo. Value: 11."
                  " 11(.0)? is greater than the maximum of 10")
        self.check_validation_error(self.post, body={'foo': 11},
                                    expected_detail=detail)

        detail = ("Invalid input for field/attribute foo. Value: 0."
                  " 0(.0)? is less than the minimum of 1")
        self.check_validation_error(self.post, body={'foo': '0'},
                                    expected_detail=detail)

        detail = ("Invalid input for field/attribute foo. Value: 11."
                  " 11(.0)? is greater than the maximum of 10")
        self.check_validation_error(self.post, body={'foo': '11'},
                                    expected_detail=detail)


class BooleanTestCase(APIValidationTestCase):

    def setUp(self):
        schema = {
            'type': 'object',
            'properties': {
                'foo': parameter_types.boolean,
            },
        }
        super(BooleanTestCase, self).setUp(schema=schema)

    def test_validate_boolean(self):
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': True}, req=FakeRequest()))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': False}, req=FakeRequest()))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': 'True'}, req=FakeRequest()))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': 'False'}, req=FakeRequest()))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': '1'}, req=FakeRequest()))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': '0'}, req=FakeRequest()))

    def test_validate_boolean_fails(self):
        enum_boolean = ("[True, 'True', 'TRUE', 'true', '1', 'ON', 'On',"
                        " 'on', 'YES', 'Yes', 'yes', 'y', 't',"
                        " False, 'False', 'FALSE', 'false', '0', 'OFF', 'Off',"
                        " 'off', 'NO', 'No', 'no', 'n', 'f']")

        detail = ("Invalid input for field/attribute foo. Value: bar."
                  " 'bar' is not one of %s") % enum_boolean
        self.check_validation_error(self.post, body={'foo': 'bar'},
                                    expected_detail=detail)

        detail = ("Invalid input for field/attribute foo. Value: 2."
                  " '2' is not one of %s") % enum_boolean
        self.check_validation_error(self.post, body={'foo': '2'},
                                    expected_detail=detail)


class NameTestCase(APIValidationTestCase):

    def setUp(self):
        schema = {
            'type': 'object',
            'properties': {
                'foo': parameter_types.name,
            },
        }
        super(NameTestCase, self).setUp(schema=schema)

    def test_validate_name(self):
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': 'volume.1'},
                                   req=FakeRequest()))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': 'volume 1'},
                                   req=FakeRequest()))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': 'a'}, req=FakeRequest()))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': u'\u0434'}, req=FakeRequest()))
        self.assertEqual('Validation succeeded.',
                         self.post(body={'foo': u'\u0434\u2006\ufffd'},
                                   req=FakeRequest()))


class DatetimeTestCase(APIValidationTestCase):

    def setUp(self):
        schema = {
            'type': 'object',
            'properties': {
                'foo': {
                    'type': 'string',
                    'format': 'date-time',
                },
            },
        }
        super(DatetimeTestCase, self).setUp(schema=schema)

    def test_validate_datetime(self):
        self.assertEqual('Validation succeeded.',
                         self.post(body={
                             'foo': '2017-01-14T01:00:00Z'}, req=FakeRequest()
                         ))
