
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

from cinder.brick import exception
from cinder import test

import six


class BrickExceptionTestCase(test.TestCase):
    def test_default_error_msg(self):
        class FakeBrickException(exception.BrickException):
            message = "default message"

        exc = FakeBrickException()
        self.assertEqual(six.text_type(exc), 'default message')

    def test_error_msg(self):
        self.assertEqual(six.text_type(exception.BrickException('test')),
                         'test')

    def test_default_error_msg_with_kwargs(self):
        class FakeBrickException(exception.BrickException):
            message = "default message: %(code)s"

        exc = FakeBrickException(code=500)
        self.assertEqual(six.text_type(exc), 'default message: 500')

    def test_error_msg_exception_with_kwargs(self):
        # NOTE(dprince): disable format errors for this test
        self.flags(fatal_exception_format_errors=False)

        class FakeBrickException(exception.BrickException):
            message = "default message: %(mispelled_code)s"

        exc = FakeBrickException(code=500)
        self.assertEqual(six.text_type(exc),
                         'default message: %(mispelled_code)s')

    def test_default_error_code(self):
        class FakeBrickException(exception.BrickException):
            code = 404

        exc = FakeBrickException()
        self.assertEqual(exc.kwargs['code'], 404)

    def test_error_code_from_kwarg(self):
        class FakeBrickException(exception.BrickException):
            code = 500

        exc = FakeBrickException(code=404)
        self.assertEqual(exc.kwargs['code'], 404)
