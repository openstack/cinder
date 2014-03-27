# Copyright (c) 2014 VMware, Inc.
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

"""
Unit tests for session management and API invocation classes.
"""

from eventlet import greenthread
import mock

from cinder import test
from cinder.volume.drivers.vmware import api
from cinder.volume.drivers.vmware import error_util


class RetryTest(test.TestCase):
    """Tests for retry decorator class."""

    def test_retry(self):
        result = "RESULT"

        @api.Retry()
        def func(*args, **kwargs):
            return result

        self.assertEqual(result, func())

        def func2(*args, **kwargs):
            return result

        retry = api.Retry()
        self.assertEqual(result, retry(func2)())
        self.assertTrue(retry._retry_count == 0)

    def test_retry_with_expected_exceptions(self):
        result = "RESULT"
        responses = [error_util.SessionOverLoadException(None),
                     error_util.SessionOverLoadException(None),
                     result]

        def func(*args, **kwargs):
            response = responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response

        sleep_time_incr = 0.01
        retry_count = 2
        retry = api.Retry(10, sleep_time_incr, 10,
                          (error_util.SessionOverLoadException,))
        self.assertEqual(result, retry(func)())
        self.assertTrue(retry._retry_count == retry_count)
        self.assertEqual(retry_count * sleep_time_incr, retry._sleep_time)

    def test_retry_with_max_retries(self):
        responses = [error_util.SessionOverLoadException(None),
                     error_util.SessionOverLoadException(None),
                     error_util.SessionOverLoadException(None)]

        def func(*args, **kwargs):
            response = responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response

        retry = api.Retry(2, 0, 0, (error_util.SessionOverLoadException,))
        self.assertRaises(error_util.SessionOverLoadException, retry(func))
        self.assertTrue(retry._retry_count == 2)

    def test_retry_with_unexpected_exception(self):

        def func(*args, **kwargs):
            raise error_util.VimException(None)

        retry = api.Retry()
        self.assertRaises(error_util.VimException, retry(func))
        self.assertTrue(retry._retry_count == 0)


class VMwareAPISessionTest(test.TestCase):
    """Tests for VMwareAPISession."""

    SERVER_IP = '10.1.2.3'
    USERNAME = 'admin'
    PASSWORD = 'password'

    def setUp(self):
        super(VMwareAPISessionTest, self).setUp()
        patcher = mock.patch('cinder.volume.drivers.vmware.vim.Vim')
        self.addCleanup(patcher.stop)
        self.VimMock = patcher.start()
        self.VimMock.side_effect = lambda *args, **kw: mock.Mock()

    def _create_api_session(self, _create_session, retry_count=10,
                            task_poll_interval=1):
        return api.VMwareAPISession(VMwareAPISessionTest.SERVER_IP,
                                    VMwareAPISessionTest.USERNAME,
                                    VMwareAPISessionTest.PASSWORD,
                                    retry_count,
                                    task_poll_interval,
                                    'https',
                                    _create_session)

    def test_create_session(self):
        session = mock.Mock()
        session.key = "12345"
        api_session = self._create_api_session(False)
        vim_obj = api_session.vim
        vim_obj.Login.return_value = session
        pbm_client = mock.Mock()
        api_session._pbm = pbm_client

        api_session.create_session()
        session_manager = vim_obj.service_content.sessionManager
        vim_obj.Login.assert_called_once_with(
            session_manager, userName=VMwareAPISessionTest.USERNAME,
            password=VMwareAPISessionTest.PASSWORD)
        self.assertFalse(vim_obj.TerminateSession.called)
        self.assertEqual(session.key, api_session._session_id)
        pbm_client.set_cookie.assert_called_once_with()

    def test_create_session_with_existing_session(self):
        old_session_key = '12345'
        new_session_key = '67890'
        session = mock.Mock()
        session.key = new_session_key
        api_session = self._create_api_session(False)
        api_session._session_id = old_session_key
        vim_obj = api_session.vim
        vim_obj.Login.return_value = session

        api_session.create_session()
        session_manager = vim_obj.service_content.sessionManager
        vim_obj.Login.assert_called_once_with(
            session_manager, userName=VMwareAPISessionTest.USERNAME,
            password=VMwareAPISessionTest.PASSWORD)
        vim_obj.TerminateSession.assert_called_once_with(
            session_manager, sessionId=[old_session_key])
        self.assertEqual(new_session_key, api_session._session_id)

    def test_invoke_api(self):
        api_session = self._create_api_session(True)
        response = mock.Mock()

        def api(*args, **kwargs):
            return response

        module = mock.Mock()
        module.api = api
        ret = api_session.invoke_api(module, 'api')
        self.assertEqual(response, ret)

    def test_invoke_api_with_expected_exception(self):
        api_session = self._create_api_session(True)
        ret = mock.Mock()
        responses = [error_util.VimException(None), ret]

        def api(*args, **kwargs):
            response = responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response

        module = mock.Mock()
        module.api = api
        with mock.patch.object(greenthread, 'sleep'):
            self.assertEqual(ret, api_session.invoke_api(module, 'api'))

    def test_invoke_api_with_vim_fault_exception(self):
        api_session = self._create_api_session(True)

        def api(*args, **kwargs):
            raise error_util.VimFaultException([], "error")

        module = mock.Mock()
        module.api = api
        self.assertRaises(error_util.VimFaultException,
                          lambda: api_session.invoke_api(module, 'api'))

    def test_invoke_api_with_empty_response(self):
        api_session = self._create_api_session(True)
        vim_obj = api_session.vim
        vim_obj.SessionIsActive.return_value = True

        def api(*args, **kwargs):
            raise error_util.VimFaultException(
                [error_util.NOT_AUTHENTICATED], "error")

        module = mock.Mock()
        module.api = api
        ret = api_session.invoke_api(module, 'api')
        self.assertEqual([], ret)
        vim_obj.SessionIsActive.assert_called_once_with(
            vim_obj.service_content.sessionManager,
            sessionID=api_session._session_id,
            userName=api_session._session_username)

    def test_invoke_api_with_stale_session(self):
        api_session = self._create_api_session(True)
        api_session.create_session = mock.Mock()
        vim_obj = api_session.vim
        vim_obj.SessionIsActive.return_value = False
        result = mock.Mock()
        responses = [error_util.VimFaultException(
            [error_util.NOT_AUTHENTICATED], "error"), result]

        def api(*args, **kwargs):
            response = responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response

        module = mock.Mock()
        module.api = api
        ret = api_session.invoke_api(module, 'api')
        self.assertEqual(result, ret)
        vim_obj.SessionIsActive.assert_called_once_with(
            vim_obj.service_content.sessionManager,
            sessionID=api_session._session_id,
            userName=api_session._session_username)
        api_session.create_session.assert_called_once_with()
