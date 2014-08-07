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

from cinder.i18n import _
from cinder.openstack.common import log as logging
from cinder.openstack.common import loopingcall
from cinder.volume.drivers.vmware import error_util
from cinder.volume.drivers.vmware import pbm
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

        def _func(*args, **kwargs):
            try:
                result = f(*args, **kwargs)
            except self._exceptions as excep:
                LOG.exception(_("Failure while invoking function: "
                                "%(func)s. Error: %(excep)s.") %
                              {'func': f.__name__, 'excep': excep})
                if (self._max_retry_count != -1 and
                        self._retry_count >= self._max_retry_count):
                    raise excep
                else:
                    self._retry_count += 1
                    self._sleep_time += self._inc_sleep_time
                    return self._sleep_time
            except Exception as excep:
                raise excep
            # got result. Stop the loop.
            raise loopingcall.LoopingCallDone(result)

        def func(*args, **kwargs):
            loop = loopingcall.DynamicLoopingCall(_func, *args, **kwargs)
            timer = loop.start(periodic_interval_max=self._max_sleep_time)
            return timer.wait()

        return func


class VMwareAPISession(object):
    """Sets up a session with the server and handles all calls made to it."""

    def __init__(self, server_ip, server_username, server_password,
                 api_retry_count, task_poll_interval, scheme='https',
                 create_session=True, wsdl_loc=None, pbm_wsdl=None):
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
        :param wsdl_loc: VIM WSDL file location for invoking SOAP calls on
                         server using suds
        :param pbm_wsdl: PBM WSDL file location. If set to None the storage
                         policy related functionality will be disabled.
        """
        self._server_ip = server_ip
        self._server_username = server_username
        self._server_password = server_password
        self._wsdl_loc = wsdl_loc
        self._api_retry_count = api_retry_count
        self._task_poll_interval = task_poll_interval
        self._scheme = scheme
        self._session_id = None
        self._session_username = None
        self._vim = None
        self._pbm_wsdl = pbm_wsdl
        self._pbm = None
        if create_session:
            self.create_session()

    @property
    def vim(self):
        if not self._vim:
            self._vim = vim.Vim(protocol=self._scheme, host=self._server_ip,
                                wsdl_loc=self._wsdl_loc)
        return self._vim

    @property
    def pbm(self):
        if not self._pbm and self._pbm_wsdl:
            self._pbm = pbm.PBMClient(self.vim, self._pbm_wsdl,
                                      protocol=self._scheme,
                                      host=self._server_ip)
        return self._pbm

    @Retry(exceptions=(error_util.VimConnectionException,))
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

        # We need to save the username in the session since we may need it
        # later to check active session. The SessionIsActive method requires
        # the username parameter to be exactly same as that in the session
        # object. We can't use the username used for login since the Login
        # method ignores the case.
        self._session_username = session.userName

        if self.pbm:
            self.pbm.set_cookie()
        LOG.info(_("Successfully established connection to the server."))

    def __del__(self):
        """Logs-out the sessions."""
        try:
            self.vim.Logout(self.vim.service_content.sessionManager)
        except Exception as excep:
            LOG.exception(_("Error while logging out from vim session: %s."),
                          excep)
        if self._pbm:
            try:
                self.pbm.Logout(self.pbm.service_content.sessionManager)
            except Exception as excep:
                LOG.exception(_("Error while logging out from pbm session: "
                                "%s."), excep)

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
               exceptions=(error_util.SessionOverLoadException,
                           error_util.VimConnectionException))
        def _invoke_api(module, method, *args, **kwargs):
            while True:
                try:
                    api_method = getattr(module, method)
                    return api_method(*args, **kwargs)
                except error_util.VimFaultException as excep:
                    if error_util.NOT_AUTHENTICATED not in excep.fault_list:
                        raise excep
                    # If it is a not-authenticated fault, we re-authenticate
                    # the user and retry the API invocation.

                    # The not-authenticated fault is set by the fault checker
                    # due to an empty response. An empty response could be a
                    # valid response; for e.g., response for the query to
                    # return the VMs in an ESX server which has no VMs in it.
                    # Also, the server responds with an empty response in the
                    # case of an inactive session. Therefore, we need a way to
                    # differentiate between these two cases.
                    if self._is_current_session_active():
                        LOG.debug("Returning empty response for "
                                  "%(module)s.%(method)s invocation.",
                                  {'module': module,
                                   'method': method})
                        return []

                    # empty response is due to an inactive session
                    LOG.warn(_("Current session: %(session)s is inactive; "
                               "re-creating the session while invoking "
                               "method %(module)s.%(method)s."),
                             {'session': self._session_id,
                              'module': module,
                              'method': method},
                             exc_info=True)
                    self.create_session()

        return _invoke_api(module, method, *args, **kwargs)

    def _is_current_session_active(self):
        """Check if current session is active.

        :returns: True if the session is active; False otherwise
        """
        LOG.debug("Checking if the current session: %s is active.",
                  self._session_id)

        is_active = False
        try:
            is_active = self.vim.SessionIsActive(
                self.vim.service_content.sessionManager,
                sessionID=self._session_id,
                userName=self._session_username)
        except error_util.VimException:
            LOG.warn(_("Error occurred while checking whether the "
                       "current session: %s is active."),
                     self._session_id,
                     exc_info=True)

        return is_active

    def wait_for_task(self, task):
        """Return a deferred that will give the result of the given task.

        The task is polled until it completes. The method returns the task
        information upon successful completion.

        :param task: Managed object reference of the task
        :return: Task info upon successful completion of the task
        """
        loop = loopingcall.FixedIntervalLoopingCall(self._poll_task, task)
        return loop.start(self._task_poll_interval).wait()

    def _poll_task(self, task):
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
                    LOG.debug("Task: %(task)s progress: %(prog)s." %
                              {'task': task, 'prog': task_info.progress})
                return
            elif task_info.state == 'success':
                LOG.debug("Task %s status: success." % task)
            else:
                error_msg = str(task_info.error.localizedMessage)
                LOG.exception(_("Task: %(task)s failed with error: %(err)s.") %
                              {'task': task, 'err': error_msg})
                raise error_util.VimFaultException([], error_msg)
        except Exception as excep:
            LOG.exception(_("Task: %(task)s failed with error: %(err)s.") %
                          {'task': task, 'err': excep})
            raise excep
        # got the result. So stop the loop.
        raise loopingcall.LoopingCallDone(task_info)

    def wait_for_lease_ready(self, lease):
        loop = loopingcall.FixedIntervalLoopingCall(self._poll_lease, lease)
        return loop.start(self._task_poll_interval).wait()

    def _poll_lease(self, lease):
        try:
            state = self.invoke_api(vim_util, 'get_object_property',
                                    self.vim, lease, 'state')
            if state == 'ready':
                # done
                LOG.debug("Lease is ready.")
            elif state == 'initializing':
                LOG.debug("Lease initializing...")
                return
            elif state == 'error':
                error_msg = self.invoke_api(vim_util, 'get_object_property',
                                            self.vim, lease, 'error')
                LOG.exception(error_msg)
                excep = error_util.VimFaultException([], error_msg)
                raise excep
            else:
                # unknown state - complain
                error_msg = _("Error: unknown lease state %s.") % state
                raise error_util.VimFaultException([], error_msg)
        except Exception as excep:
            LOG.exception(excep)
            raise excep
        # stop the loop since state is ready
        raise loopingcall.LoopingCallDone()
