# vim: expandtab tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 VMware, Inc.
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
Session and API call management for VMware ESX/VC server.
Provides abstraction over cinder.volume.drivers.vmware.vim.Vim SOAP calls.
"""

from eventlet import event

from cinder.openstack.common import log as logging
from cinder.openstack.common import loopingcall
from cinder.volume.drivers.vmware import error_util
from cinder.volume.drivers.vmware import vim
from cinder.volume.drivers.vmware import vim_util

LOG = logging.getLogger(__name__)


class Retry(object):
    """Decorator for retrying a function upon suggested exceptions.

    The method retries for given number of times and the sleep
    time increments till the max sleep time is reached.
    If max retries is set to -1, then the decorated function is
    invoked indefinitely till no exception is thrown or if
    the caught exception is not in the list of suggested exceptions.
    """

    def __init__(self, max_retry_count=-1, inc_sleep_time=10,
                 max_sleep_time=60, exceptions=()):
        """Initialize retry object based on input params.

        :param max_retry_count: Max number of times, a function must be
                                retried when one of input 'exceptions'
                                is caught. The default -1 will always
                                retry the function till a non-exception
                                case, or an un-wanted error case arises.
        :param inc_sleep_time: Incremental time in seconds for sleep time
                               between retrial
        :param max_sleep_time: Max sleep time beyond which the sleep time will
                               not be incremented using param inc_sleep_time
                               and max_sleep_time will be used as sleep time
        :param exceptions: Suggested exceptions for which the function must be
                           retried
        """
        self._max_retry_count = max_retry_count
        self._inc_sleep_time = inc_sleep_time
        self._max_sleep_time = max_sleep_time
        self._exceptions = exceptions
        self._retry_count = 0
        self._sleep_time = 0

    def __call__(self, f):

        def _func(done, *args, **kwargs):
            try:
                result = f(*args, **kwargs)
                done.send(result)
            except self._exceptions as excep:
                LOG.exception(_("Failure while invoking function: "
                                "%(func)s. Error: %(excep)s.") %
                              {'func': f.__name__, 'excep': excep})
                if (self._max_retry_count != -1 and
                        self._retry_count >= self._max_retry_count):
                    done.send_exception(excep)
                else:
                    self._retry_count += 1
                    self._sleep_time += self._inc_sleep_time
                    return self._sleep_time
            except Exception as excep:
                done.send_exception(excep)
            return 0

        def func(*args, **kwargs):
            done = event.Event()
            loop = loopingcall.DynamicLoopingCall(_func, done, *args, **kwargs)
            loop.start(periodic_interval_max=self._max_sleep_time)
            result = done.wait()
            loop.stop()
            return result

        return func


class VMwareAPISession(object):
    """Sets up a session with the server and handles all calls made to it."""

    @Retry(exceptions=(Exception))
    def __init__(self, server_ip, server_username, server_password,
                 api_retry_count, task_poll_interval, scheme='https',
                 create_session=True, wsdl_loc=None):
        """Constructs session object.

        :param server_ip: IP address of ESX/VC server
        :param server_username: Username of ESX/VC server admin user
        :param server_password: Password for param server_username
        :param api_retry_count: Number of times an API must be retried upon
                                session/connection related errors
        :param task_poll_interval: Sleep time in seconds for polling an
                                   on-going async task as part of the API call
        :param scheme: http or https protocol
        :param create_session: Boolean whether to set up connection at the
                               time of instance creation
        :param wsdl_loc: WSDL file location for invoking SOAP calls on server
                         using suds
        """
        self._server_ip = server_ip
        self._server_username = server_username
        self._server_password = server_password
        self._wsdl_loc = wsdl_loc
        self._api_retry_count = api_retry_count
        self._task_poll_interval = task_poll_interval
        self._scheme = scheme
        self._session_id = None
        self._vim = None
        if create_session:
            self.create_session()

    @property
    def vim(self):
        if not self._vim:
            self._vim = vim.Vim(protocol=self._scheme, host=self._server_ip,
                                wsdl_loc=self._wsdl_loc)
        return self._vim

    def create_session(self):
        """Establish session with the server."""
        # Login and setup the session with the server for making
        # API calls
        session_manager = self.vim.service_content.sessionManager
        session = self.vim.Login(session_manager,
                                 userName=self._server_username,
                                 password=self._server_password)
        # Terminate the earlier session, if possible (For the sake of
        # preserving sessions as there is a limit to the number of
        # sessions we can have)
        if self._session_id:
            try:
                self.vim.TerminateSession(session_manager,
                                          sessionId=[self._session_id])
            except Exception as excep:
                # This exception is something we can live with. It is
                # just an extra caution on our side. The session may
                # have been cleared. We could have made a call to
                # SessionIsActive, but that is an overhead because we
                # anyway would have to call TerminateSession.
                LOG.exception(_("Error while terminating session: %s.") %
                              excep)
        self._session_id = session.key
        LOG.info(_("Successfully established connection to the server."))

    def __del__(self):
        """Logs-out the session."""
        try:
            self.vim.Logout(self.vim.service_content.sessionManager)
        except Exception as excep:
            LOG.exception(_("Error while logging out the user: %s.") %
                          excep)

    def invoke_api(self, module, method, *args, **kwargs):
        """Wrapper method for invoking APIs.

        Here we retry the API calls for exceptions which may come because
        of session overload.

        Make sure if a Vim instance is being passed here, this session's
        Vim (self.vim) instance is used, as we retry establishing session
        in case of session timedout.

        :param module: Module invoking the VI SDK calls
        :param method: Method in the module that invokes the VI SDK call
        :param args: Arguments to the method
        :param kwargs: Keyword arguments to the method
        :return: Response of the API call
        """

        @Retry(max_retry_count=self._api_retry_count,
               exceptions=(error_util.VimException))
        def _invoke_api(module, method, *args, **kwargs):
            last_fault_list = []
            while True:
                try:
                    api_method = getattr(module, method)
                    return api_method(*args, **kwargs)
                except error_util.VimFaultException as excep:
                    if error_util.NOT_AUTHENTICATED not in excep.fault_list:
                        raise excep
                    # If it is a not-authenticated fault, we re-authenticate
                    # the user and retry the API invocation.

                    # Because of the idle session returning an empty
                    # RetrieveProperties response and also the same is
                    # returned when there is an empty answer to a query
                    # (e.g. no VMs on the host), we have no way to
                    # differentiate.
                    # So if the previous response was also an empty
                    # response and after creating a new session, we get
                    # the same empty response, then we are sure of the
                    # response being an empty response.
                    if error_util.NOT_AUTHENTICATED in last_fault_list:
                        return []
                    last_fault_list = excep.fault_list
                    LOG.exception(_("Not authenticated error occurred. "
                                    "Will create session and try "
                                    "API call again: %s.") % excep)
                    self.create_session()

        return _invoke_api(module, method, *args, **kwargs)

    def wait_for_task(self, task):
        """Return a deferred that will give the result of the given task.

        The task is polled until it completes. The method returns the task
        information upon successful completion.

        :param task: Managed object reference of the task
        :return: Task info upon successful completion of the task
        """
        done = event.Event()
        loop = loopingcall.FixedIntervalLoopingCall(self._poll_task,
                                                    task, done)
        loop.start(self._task_poll_interval)
        task_info = done.wait()
        loop.stop()
        return task_info

    def _poll_task(self, task, done):
        """Poll the given task.

        If the task completes successfully then returns task info.
        In case of error sends back appropriate error.

        :param task: Managed object reference of the task
        :param event: Event that captures task status
        """
        try:
            task_info = self.invoke_api(vim_util, 'get_object_property',
                                        self.vim, task, 'info')
            if task_info.state in ['queued', 'running']:
                # If task already completed on server, it will not return
                # the progress.
                if hasattr(task_info, 'progress'):
                    LOG.debug(_("Task: %(task)s progress: %(prog)s.") %
                              {'task': task, 'prog': task_info.progress})
                return
            elif task_info.state == 'success':
                LOG.debug(_("Task %s status: success.") % task)
                done.send(task_info)
            else:
                error_msg = str(task_info.error.localizedMessage)
                LOG.exception(_("Task: %(task)s failed with error: %(err)s.") %
                              {'task': task, 'err': error_msg})
                done.send_exception(error_util.VimFaultException([],
                                    error_msg))
        except Exception as excep:
            LOG.exception(_("Task: %(task)s failed with error: %(err)s.") %
                          {'task': task, 'err': excep})
            done.send_exception(excep)
