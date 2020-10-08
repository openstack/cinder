
# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

from http import client as http_client
from unittest import mock

import fixtures
import webob.util

from cinder import exception
from cinder.tests.unit import test


class CinderExceptionReraiseFormatError(object):
    real_log_exception = exception.CinderException._log_exception

    @classmethod
    def patch(cls):
        exception.CinderException._log_exception = cls._wrap_log_exception

    @staticmethod
    def _wrap_log_exception(self):
        CinderExceptionReraiseFormatError.real_log_exception(self)
        raise


# NOTE(melwitt) This needs to be done at import time in order to also catch
# CinderException format errors that are in mock decorators. In these cases,
# the errors will be raised during test listing, before tests actually run.
CinderExceptionReraiseFormatError.patch()


class CinderExceptionTestCase(test.TestCase):
    def test_default_error_msg(self):
        class FakeCinderException(exception.CinderException):
            message = "default message"

        exc = FakeCinderException()
        self.assertEqual('default message', str(exc))

    def test_error_msg(self):
        self.assertEqual('test', str(exception.CinderException('test')))

    def test_default_error_msg_with_kwargs(self):
        class FakeCinderException(exception.CinderException):
            message = "default message: %(code)s"

        exc = FakeCinderException(code=int(http_client.INTERNAL_SERVER_ERROR))
        self.assertEqual('default message: 500', str(exc))

    def test_error_msg_exception_with_kwargs(self):
        # NOTE(dprince): disable format errors for this test
        self.useFixture(fixtures.MonkeyPatch(
            'cinder.exception.CinderException._log_exception',
            CinderExceptionReraiseFormatError.real_log_exception))

        class FakeCinderException(exception.CinderException):
            message = "default message: %(misspelled_code)s"

        exc = FakeCinderException(code=http_client.INTERNAL_SERVER_ERROR)
        self.assertEqual('default message: %(misspelled_code)s', str(exc))

    def test_default_error_code(self):
        class FakeCinderException(exception.CinderException):
            code = http_client.NOT_FOUND

        exc = FakeCinderException()
        self.assertEqual(http_client.NOT_FOUND, exc.kwargs['code'])

    def test_error_code_from_kwarg(self):
        class FakeCinderException(exception.CinderException):
            code = http_client.INTERNAL_SERVER_ERROR

        exc = FakeCinderException(code=http_client.NOT_FOUND)
        self.assertEqual(http_client.NOT_FOUND, exc.kwargs['code'])

    def test_error_msg_is_exception_to_string(self):
        msg = 'test message'
        exc1 = Exception(msg)
        exc2 = exception.CinderException(exc1)
        self.assertEqual(msg, exc2.msg)

    def test_exception_kwargs_to_string(self):
        msg = 'test message'
        exc1 = Exception(msg)
        exc2 = exception.CinderException(kwarg1=exc1)
        self.assertEqual(msg, exc2.kwargs['kwarg1'])

    def test_message_in_format_string(self):
        class FakeCinderException(exception.CinderException):
            message = 'FakeCinderException: %(message)s'

        exc = FakeCinderException(message='message')
        self.assertEqual('FakeCinderException: message', str(exc))

    def test_message_and_kwarg_in_format_string(self):
        class FakeCinderException(exception.CinderException):
            message = 'Error %(code)d: %(message)s'

        exc = FakeCinderException(message='message',
                                  code=http_client.NOT_FOUND)
        self.assertEqual('Error 404: message', str(exc))

    def test_message_is_exception_in_format_string(self):
        class FakeCinderException(exception.CinderException):
            message = 'Exception: %(message)s'

        msg = 'test message'
        exc1 = Exception(msg)
        exc2 = FakeCinderException(message=exc1)
        self.assertEqual('Exception: test message', str(exc2))


class CinderConvertedExceptionTestCase(test.TestCase):
    def test_default_args(self):
        exc = exception.ConvertedException()
        self.assertNotEqual('', exc.title)
        self.assertEqual(http_client.INTERNAL_SERVER_ERROR, exc.code)
        self.assertEqual('', exc.explanation)

    def test_standard_status_code(self):
        with mock.patch.dict(webob.util.status_reasons,
                             {http_client.OK: 'reason'}):
            exc = exception.ConvertedException(code=int(http_client.OK))
            self.assertEqual('reason', exc.title)

    @mock.patch.dict(webob.util.status_reasons, {
        http_client.INTERNAL_SERVER_ERROR: 'reason'})
    def test_generic_status_code(self):
        with mock.patch.dict(webob.util.status_generic_reasons,
                             {5: 'generic_reason'}):
            exc = exception.ConvertedException(code=599)
            self.assertEqual('generic_reason', exc.title)
