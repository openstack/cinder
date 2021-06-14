# Copyright (c) 2020 Dell Inc. or its subsidiaries.
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

import json
import re
import sys
import time

from oslo_log import log as logging
from oslo_service import loopingcall
import requests
import requests.auth
import requests.exceptions as r_exc
# pylint: disable=E0401
import requests.packages.urllib3.util.retry as requests_retry
import six

from cinder import exception
from cinder.i18n import _
from cinder.utils import retry
from cinder.volume.drivers.dell_emc.powermax import utils

LOG = logging.getLogger(__name__)
SLOPROVISIONING = 'sloprovisioning'
REPLICATION = 'replication'
SYSTEM = 'system'
U4V_VERSION = '92'
MIN_U4P_VERSION = '9.2.0.0'
UCODE_5978 = '5978'
retry_exc_tuple = (exception.VolumeBackendAPIException,)
u4p_failover_max_wait = 120
# HTTP constants
GET = 'GET'
POST = 'POST'
PUT = 'PUT'
DELETE = 'DELETE'
STATUS_200 = 200
STATUS_201 = 201
STATUS_202 = 202
STATUS_204 = 204
SERVER_ERROR_STATUS_CODES = [408, 501, 502, 503, 504]
ITERATOR_EXPIRATION = 180
# Job constants
INCOMPLETE_LIST = ['created', 'unscheduled', 'scheduled', 'running',
                   'validating', 'validated']
CREATED = 'created'
SUCCEEDED = 'succeeded'
CREATE_VOL_STRING = "Creating new Volumes"
POPULATE_SG_LIST = "Populating Storage Group(s) with volumes"


class PowerMaxRest(object):
    """Rest class based on Unisphere for PowerMax Rest API."""

    def __init__(self):
        self.utils = utils.PowerMaxUtils()
        self.session = None
        self.base_uri = None
        self.user = None
        self.passwd = None
        self.verify = None
        self.cert = None
        # Failover Unisphere configuration
        self.primary_u4p = None
        self.u4p_failover_enabled = False
        self.u4p_failover_autofailback = True
        self.u4p_failover_targets = list()
        self.u4p_failover_retries = 3
        self.u4p_failover_timeout = 30
        self.u4p_failover_backoff_factor = 1
        self.u4p_in_failover = False
        self.u4p_failover_lock = False
        self.ucode_major_level = None
        self.ucode_minor_level = None
        self.is_snap_id = False

    def set_rest_credentials(self, array_info):
        """Given the array record set the rest server credentials.

        :param array_info: record
        """
        ip = array_info['RestServerIp']
        port = array_info['RestServerPort']
        self.user = array_info['RestUserName']
        self.passwd = array_info['RestPassword']
        self.verify = array_info['SSLVerify']
        ip_port = "%(ip)s:%(port)s" % {'ip': ip, 'port': port}
        self.base_uri = ("https://%(ip_port)s/univmax/restapi" % {
            'ip_port': ip_port})
        self.session = self._establish_rest_session()
        self.ucode_major_level, self.ucode_minor_level = (
            self.get_major_minor_ucode(array_info['SerialNumber']))
        self.is_snap_id = self._is_snapid_enabled()

    def set_u4p_failover_config(self, failover_info):
        """Set the environment failover Unisphere targets and configuration..

        :param failover_info: failover target record
        """
        self.u4p_failover_enabled = True
        self.primary_u4p = failover_info['u4p_primary']
        self.u4p_failover_targets = failover_info['u4p_failover_targets']

        if failover_info['u4p_failover_retries']:
            self.u4p_failover_retries = failover_info['u4p_failover_retries']
        if failover_info['u4p_failover_timeout']:
            self.u4p_failover_timeout = failover_info['u4p_failover_timeout']
        if failover_info['u4p_failover_backoff_factor']:
            self.u4p_failover_backoff_factor = failover_info[
                'u4p_failover_backoff_factor']
        if failover_info['u4p_failover_autofailback']:
            self.u4p_failover_autofailback = failover_info[
                'u4p_failover_autofailback']

    def _establish_rest_session(self):
        """Establish the rest session.

        :returns: requests.session() -- session, the rest session
        """
        LOG.info("Establishing REST session with %(base_uri)s",
                 {'base_uri': self.base_uri})
        if self.session:
            self.session.close()
        session = requests.session()
        session.headers = {'content-type': 'application/json',
                           'accept': 'application/json',
                           'Application-Type': 'openstack'}
        session.auth = requests.auth.HTTPBasicAuth(self.user, self.passwd)

        if self.verify is not None:
            session.verify = self.verify

        # SESSION FAILOVER CONFIGURATION
        if self.u4p_failover_enabled:
            timeout = self.u4p_failover_timeout

            class MyHTTPAdapter(requests.adapters.HTTPAdapter):
                def send(self, *args, **kwargs):
                    kwargs['timeout'] = timeout
                    return super(MyHTTPAdapter, self).send(*args, **kwargs)

            retry = requests_retry.Retry(
                total=self.u4p_failover_retries,
                backoff_factor=self.u4p_failover_backoff_factor,
                status_forcelist=SERVER_ERROR_STATUS_CODES)
            adapter = MyHTTPAdapter(max_retries=retry)
            session.mount('https://', adapter)
            session.mount('http://', adapter)

        return session

    def _handle_u4p_failover(self):
        """Handle the failover process to secondary instance of Unisphere.

        :raises: VolumeBackendAPIException
        """
        if self.u4p_failover_targets:
            LOG.error("Unisphere failure at %(prim)s, switching to next "
                      "backup instance of Unisphere at %(sec)s", {
                          'prim': self.base_uri,
                          'sec': self.u4p_failover_targets[0][
                              'RestServerIp']})
            self.set_rest_credentials(self.u4p_failover_targets[0])
            self.u4p_failover_targets.pop(0)
            if self.u4p_in_failover:
                LOG.warning("PowerMax driver still in u4p failover mode. A "
                            "periodic check will be made to see if primary "
                            "Unisphere comes back online for seamless "
                            "restoration.")
            else:
                LOG.warning("PowerMax driver set to u4p failover mode. A "
                            "periodic check will be made to see if primary "
                            "Unisphere comes back online for seamless "
                            "restoration.")
            self.u4p_in_failover = True
        else:
            msg = _("A connection could not be established with the "
                    "primary instance of Unisphere or any of the "
                    "specified failover instances of Unisphere. Please "
                    "check your local environment setup and restart "
                    "Cinder Volume service to revert back to the primary "
                    "Unisphere instance.")
            self.u4p_failover_lock = False
            raise exception.VolumeBackendAPIException(message=msg)

    def request(self, target_uri, method, params=None, request_object=None,
                u4p_check=False, retry=False):
        """Sends a request (GET, POST, PUT, DELETE) to the target api.

        :param target_uri: target uri (string)
        :param method: The method (GET, POST, PUT, or DELETE)
        :param params: Additional URL parameters
        :param request_object: request payload (dict)
        :param u4p_check: if request is testing connection (boolean)
        :param retry: if request is retry from prior failed request (boolean)
        :returns: server response object (dict)
        :raises: VolumeBackendAPIException, Timeout, ConnectionError,
                 HTTPError, SSLError
        """
        waiting_time = 0
        while self.u4p_failover_lock and not retry and (
                waiting_time < u4p_failover_max_wait):
            LOG.warning("Unisphere failover lock in process, holding request "
                        "until lock is released when Unisphere connection "
                        "re-established.")
            sleeptime = 10
            time.sleep(sleeptime)
            waiting_time += sleeptime
            if waiting_time >= u4p_failover_max_wait:
                self.u4p_failover_lock = False

        url, message, status_code, response = None, None, None, None
        if not self.session:
            self.session = self._establish_rest_session()

        try:
            url = ("%(self.base_uri)s%(target_uri)s" % {
                'self.base_uri': self.base_uri,
                'target_uri': target_uri})

            if request_object:
                response = self.session.request(
                    method=method, url=url,
                    data=json.dumps(request_object, sort_keys=True,
                                    indent=4))
            elif params:
                response = self.session.request(
                    method=method, url=url, params=params)
            else:
                response = self.session.request(
                    method=method, url=url)

            status_code = response.status_code
            if retry and status_code and status_code in [STATUS_200,
                                                         STATUS_201,
                                                         STATUS_202,
                                                         STATUS_204]:
                self.u4p_failover_lock = False

            try:
                message = response.json()
            except ValueError:
                LOG.debug("No response received from API. Status code "
                          "received is: %(status_code)s", {
                              'status_code': status_code})
                message = None
                if retry:
                    self.u4p_failover_lock = False

            LOG.debug("%(method)s request to %(url)s has returned with "
                      "a status code of: %(status_code)s.", {
                          'method': method, 'url': url,
                          'status_code': status_code})

        except r_exc.SSLError as e:
            if retry:
                self.u4p_failover_lock = False
            msg = _("The connection to %(base_uri)s has encountered an "
                    "SSL error. Please check your SSL config or supplied "
                    "SSL cert in Cinder configuration. SSL Exception "
                    "message: %(e)s")
            raise r_exc.SSLError(msg % {'base_uri': self.base_uri, 'e': e})

        except (r_exc.Timeout, r_exc.ConnectionError,
                r_exc.HTTPError) as e:
            if self.u4p_failover_enabled or u4p_check:
                if not u4p_check:
                    # Failover process
                    LOG.warning("Running failover to backup instance "
                                "of Unisphere")
                    self.u4p_failover_lock = True
                    self._handle_u4p_failover()
                    # Failover complete, re-run failed operation
                    LOG.info("Running request again to backup instance of "
                             "Unisphere")
                    status_code, message = self.request(
                        target_uri, method, params, request_object, retry=True)
            elif not self.u4p_failover_enabled:
                exc_class, __, __ = sys.exc_info()
                msg = _("The %(method)s to Unisphere server %(base)s has "
                        "experienced a %(error)s error. Please check your "
                        "Unisphere server connection/availability. "
                        "Exception message: %(exc_msg)s")
                raise exc_class(msg % {'method': method,
                                       'base': self.base_uri,
                                       'error': e.__class__.__name__,
                                       'exc_msg': e})

        except Exception as e:
            if retry:
                self.u4p_failover_lock = False
            msg = _("The %s request to URL %s failed with exception "
                    "%s" % (method, url, six.text_type(e)))
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(message=msg)

        return status_code, message

    def wait_for_job_complete(self, job, extra_specs):
        """Given the job wait for it to complete.

        :param job: the job dict
        :param extra_specs: the extra_specs dict.
        :returns: rc -- int, result -- string, status -- string,
                  task -- list of dicts detailing tasks in the job
        :raises: VolumeBackendAPIException
        """
        res, tasks = None, None
        if job['status'].lower == CREATED:
            try:
                res, tasks = job['result'], job['task']
            except KeyError:
                pass
            return 0, res, job['status'], tasks

        def _wait_for_job_complete():
            result = None
            # Called at an interval until the job is finished.
            retries = kwargs['retries']
            try:
                kwargs['retries'] = retries + 1
                if not kwargs['wait_for_job_called']:
                    is_complete, result, rc, status, task = (
                        self._is_job_finished(job_id))
                    if is_complete is True:
                        kwargs['wait_for_job_called'] = True
                        kwargs['rc'], kwargs['status'] = rc, status
                        kwargs['result'], kwargs['task'] = result, task
            except Exception:
                exception_message = (_("Issue encountered waiting for job."))
                LOG.error(exception_message)
                raise exception.VolumeBackendAPIException(
                    message=exception_message)

            if retries > int(extra_specs[utils.RETRIES]):
                LOG.error("_wait_for_job_complete failed after "
                          "%(retries)d tries.", {'retries': retries})
                kwargs['rc'], kwargs['result'] = -1, result

                raise loopingcall.LoopingCallDone()
            if kwargs['wait_for_job_called']:
                raise loopingcall.LoopingCallDone()

        job_id = job['jobId']
        kwargs = {'retries': 0, 'wait_for_job_called': False,
                  'rc': 0, 'result': None}

        timer = loopingcall.FixedIntervalLoopingCall(_wait_for_job_complete)
        timer.start(interval=int(extra_specs[utils.INTERVAL])).wait()
        LOG.debug("Return code is: %(rc)lu. Result is %(res)s.",
                  {'rc': kwargs['rc'], 'res': kwargs['result']})
        return (kwargs['rc'], kwargs['result'],
                kwargs['status'], kwargs['task'])

    def _is_job_finished(self, job_id):
        """Check if the job is finished.

        :param job_id: the id of the job
        :returns: complete -- bool, result -- string,
                  rc -- int, status -- string, task -- list of dicts
        """
        complete, rc, status, result, task = False, 0, None, None, None
        job_url = "/%s/system/job/%s" % (U4V_VERSION, job_id)
        job = self.get_request(job_url, 'job')
        if job:
            status = job['status']
            try:
                result, task = job['result'], job['task']
            except KeyError:
                pass
            if status.lower() == SUCCEEDED:
                complete = True
            elif status.lower() in INCOMPLETE_LIST:
                complete = False
            else:
                rc, complete = -1, True
        return complete, result, rc, status, task

    @staticmethod
    def check_status_code_success(operation, status_code, message):
        """Check if a status code indicates success.

        :param operation: the operation
        :param status_code: the status code
        :param message: the server response
        :raises: VolumeBackendAPIException
        """
        if status_code not in [STATUS_200, STATUS_201,
                               STATUS_202, STATUS_204]:
            exception_message = (
                _("Error %(operation)s. The status code received is %(sc)s "
                  "and the message is %(message)s.") % {
                    'operation': operation, 'sc': status_code,
                    'message': message})
            raise exception.VolumeBackendAPIException(
                message=exception_message)

    def wait_for_job(self, operation, status_code, job, extra_specs):
        """Check if call is async, wait for it to complete.

        :param operation: the operation being performed
        :param status_code: the status code
        :param job: the job
        :param extra_specs: the extra specifications
        :returns: task -- list of dicts detailing tasks in the job
        :raises: VolumeBackendAPIException
        """
        task = None
        if status_code == STATUS_202:
            rc, result, status, task = self.wait_for_job_complete(
                job, extra_specs)
            if rc != 0:
                exception_message = (
                    _("Error %(operation)s. Status code: %(sc)lu. Error: "
                      "%(error)s. Status: %(status)s.") % {
                        'operation': operation, 'sc': rc,
                        'error': six.text_type(result), 'status': status})
                LOG.error(exception_message)
                raise exception.VolumeBackendAPIException(
                    message=exception_message)
        return task

    def build_uri(self, *args, **kwargs):
        """Build the target url.

        :param args: input args, see _build_uri_legacy_args() for input
                     breakdown
        :param kwargs: input keyword args, see _build_uri_kwargs() for input
                       breakdown
        :return: target uri -- str
        """
        if args:
            target_uri = self._build_uri_legacy_args(*args, **kwargs)
        else:
            target_uri = self._build_uri_kwargs(**kwargs)

        return target_uri

    @staticmethod
    def _build_uri_legacy_args(*args, **kwargs):
        """Build the target URI using legacy args & kwargs.

        Expected format:
            arg[0]: the array serial number: the array serial number -- str
            arg[1]: the resource category e.g. 'sloprovisioning' -- str
            arg[2]: the resource type e.g. 'maskingview' -- str
            kwarg resource_name: the name of a specific resource -- str
            kwarg private: if endpoint is private -- bool
            kwarg version: U4V REST endpoint version -- int/str
            kwarg no_version: if endpoint should be versionless -- bool

        :param args: input args -- see above
        :param kwargs: input keyword args -- see above
        :return: target URI -- str
        """
        # Extract args following legacy _build_uri() format
        array_id, category, resource_type = args[0], args[1], args[2]
        # Extract keyword args following legacy _build_uri() format
        resource_name = kwargs.get('resource_name')
        private = kwargs.get('private')
        version = kwargs.get('version', U4V_VERSION)
        if kwargs.get('no_version'):
            version = None

        # Build URI
        target_uri = ''
        if private:
            target_uri += '/private'
        if version:
            target_uri += '/%(version)s' % {'version': version}
        target_uri += (
            '/{cat}/symmetrix/{array_id}/{res_type}'.format(
                cat=category, array_id=array_id, res_type=resource_type))
        if resource_name:
            target_uri += '/{resource_name}'.format(
                resource_name=kwargs.get('resource_name'))

        return target_uri

    @staticmethod
    def _build_uri_kwargs(**kwargs):
        """Build the target URI using kwargs.

        Expected kwargs:
            private: if endpoint is private (optional) -- bool
            version: U4P REST endpoint version (optional) -- int/None
            no_version: if endpoint should be versionless (optional) -- bool

            category: U4P REST category eg. 'common', 'replication'-- str

            resource_level: U4P REST resource level eg. 'symmetrix'
                            (optional) -- str
            resource_level_id: U4P REST resource level id (optional) -- str

            resource_type: U4P REST resource type eg. 'rdf_director', 'host'
                           (optional) -- str
            resource_type_id: U4P REST resource type id (optional) -- str

            resource: U4P REST resource eg. 'port' (optional) -- str
            resource_id: U4P REST resource id (optional) -- str

            object_type: U4P REST resource eg. 'rdf_group' (optional) -- str
            object_type_id: U4P REST resource id (optional) -- str

        :param kwargs: input keyword args -- see above
        :return: target URI -- str
        """
        version = kwargs.get('version', U4V_VERSION)
        if kwargs.get('no_version'):
            version = None

        target_uri = ''

        if kwargs.get('private'):
            target_uri += '/private'

        if version:
            target_uri += '/%(ver)s' % {'ver': version}

        target_uri += '/%(cat)s' % {'cat': kwargs.get('category')}

        if kwargs.get('resource_level'):
            target_uri += '/%(res_level)s' % {
                'res_level': kwargs.get('resource_level')}

        if kwargs.get('resource_level_id'):
            target_uri += '/%(res_level_id)s' % {
                'res_level_id': kwargs.get('resource_level_id')}

        if kwargs.get('resource_type'):
            target_uri += '/%(res_type)s' % {
                'res_type': kwargs.get('resource_type')}
            if kwargs.get('resource_type_id'):
                target_uri += '/%(res_type_id)s' % {
                    'res_type_id': kwargs.get('resource_type_id')}

        if kwargs.get('resource'):
            target_uri += '/%(res)s' % {
                'res': kwargs.get('resource')}
            if kwargs.get('resource_id'):
                target_uri += '/%(res_id)s' % {
                    'res_id': kwargs.get('resource_id')}

        if kwargs.get('object_type'):
            target_uri += '/%(object_type)s' % {
                'object_type': kwargs.get('object_type')}
            if kwargs.get('object_type_id'):
                target_uri += '/%(object_type_id)s' % {
                    'object_type_id': kwargs.get('object_type_id')}

        return target_uri

    def get_request(self, target_uri, resource_type, params=None):
        """Send a GET request to the array.

        :param target_uri: the target uri
        :param resource_type: the resource type, e.g. maskingview
        :param params: optional dict of filter params
        :returns: resource_object -- dict or None
        """
        resource_object = None
        sc, message = self.request(target_uri, GET, params=params)
        operation = 'get %(res)s' % {'res': resource_type}
        try:
            self.check_status_code_success(operation, sc, message)
        except Exception as e:
            LOG.debug("Get resource failed with %(e)s",
                      {'e': e})
        if sc == STATUS_200:
            resource_object = message
            resource_object = self.list_pagination(resource_object)
        return resource_object

    def post_request(self, target_uri, resource_type, request_body):
        """Send a POST request to the array.

        :param target_uri: the target uri -- str
        :param resource_type: the resource type -- str
        :param request_body: the POST request body -- dict
        :return: resource object -- dict or None
        """
        resource_object = None
        sc, msg = self.request(target_uri, POST, request_object=request_body)

        operation = 'POST %(res)s' % {'res': resource_type}
        try:
            self.check_status_code_success(operation, sc, msg)
        except Exception as e:
            LOG.debug("POST resource failed with %(e)s", {'e': e})

        if sc == STATUS_200:
            resource_object = msg

        return resource_object

    def get_resource(self, array, category, resource_type,
                     resource_name=None, params=None, private=False,
                     version=U4V_VERSION):
        """Get resource details from array.

        :param array: the array serial number
        :param category: the resource category e.g. sloprovisioning
        :param resource_type: the resource type e.g. maskingview
        :param resource_name: the name of a specific resource
        :param params: query parameters
        :param private: empty string or '/private' if private url
        :param version: None or specific version number if required
        :returns: resource object -- dict or None
        """
        target_uri = self.build_uri(
            array, category, resource_type, resource_name=resource_name,
            private=private, version=version)
        return self.get_request(target_uri, resource_type, params)

    def create_resource(self, array, category, resource_type, payload,
                        private=False):
        """Create a provisioning resource.

        :param array: the array serial number
        :param category: the category
        :param resource_type: the resource type
        :param payload: the payload
        :param private: empty string or '/private' if private url
        :returns: status_code -- int, message -- string, server response
        """
        target_uri = self.build_uri(
            array, category, resource_type, private=private)
        status_code, message = self.request(target_uri, POST,
                                            request_object=payload)
        operation = 'Create %(res)s resource' % {'res': resource_type}
        self.check_status_code_success(
            operation, status_code, message)
        return status_code, message

    def modify_resource(
            self, array, category, resource_type, payload, version=U4V_VERSION,
            resource_name=None, private=False):
        """Modify a resource.

        :param version: the uv4 version
        :param array: the array serial number
        :param category: the category
        :param resource_type: the resource type
        :param payload: the payload
        :param resource_name: the resource name
        :param private: empty string or '/private' if private url
        :returns: status_code -- int, message -- string (server response)
        """
        target_uri = self.build_uri(
            array, category, resource_type, resource_name=resource_name,
            private=private, version=version)
        status_code, message = self.request(target_uri, PUT,
                                            request_object=payload)
        operation = 'modify %(res)s resource' % {'res': resource_type}
        self.check_status_code_success(operation, status_code, message)
        return status_code, message

    @retry(retry_exc_tuple, interval=2, retries=3)
    def delete_resource(
            self, array, category, resource_type, resource_name,
            payload=None, private=False, params=None):
        """Delete a provisioning resource.

        :param array: the array serial number
        :param category: the resource category e.g. sloprovisioning
        :param resource_type: the type of resource to be deleted
        :param resource_name: the name of the resource to be deleted
        :param payload: the payload, optional
        :param private: empty string or '/private' if private url
        :param params: dict of optional query params
        """
        target_uri = self.build_uri(
            array, category, resource_type, resource_name=resource_name,
            private=private)
        status_code, message = self.request(target_uri, DELETE,
                                            request_object=payload,
                                            params=params)
        operation = 'delete %(res)s resource' % {'res': resource_type}
        self.check_status_code_success(operation, status_code, message)

    def get_arrays_list(self):
        """Get a list of all arrays on U4P instance.

        :returns arrays -- list
        """
        target_uri = '/%s/sloprovisioning/symmetrix' % U4V_VERSION
        array_details = self.get_request(target_uri, 'sloprovisioning')
        if not array_details:
            LOG.error("Could not get array details from Unisphere instance.")
        arrays = array_details.get('symmetrixId', list())
        return arrays

    def get_array_detail(self, array):
        """Get an array from its serial number.

        :param array: the array serial number
        :returns: array_details -- dict or None
        """
        target_uri = '/%s/system/symmetrix/%s' % (U4V_VERSION, array)
        array_details = self.get_request(target_uri, 'system')
        if not array_details:
            LOG.error("Cannot connect to array %(array)s.",
                      {'array': array})
        return array_details

    def get_array_tags(self, array):
        """Get the tags from its serial number.

        :param array: the array serial number
        :returns: tag list -- list or empty list
        """
        target_uri = '/%s/system/tag?array_id=%s' % (U4V_VERSION, array)
        array_tags = self.get_request(target_uri, 'system')
        return array_tags.get('tag_name')

    def is_next_gen_array(self, array):
        """Check to see if array is a next gen array(ucode 5978 or greater).

        :param array: the array serial number
        :returns: bool
        """
        is_next_gen = False
        array_details = self.get_array_detail(array)
        if array_details:
            ucode_version = array_details['ucode'].split('.')[0]
            if ucode_version >= UCODE_5978:
                is_next_gen = True
        return is_next_gen

    def get_uni_version(self):
        """Get the unisphere version from the server.

        :returns: version and major_version(e.g. ("V8.4.0.16", "84"))
        """
        version, major_version = None, None
        response = self.get_unisphere_version()
        if response and response.get('version'):
            version = response['version']
            version_list = version.split('.')
            major_version = version_list[0][1] + version_list[1]
        return version, major_version

    def get_unisphere_version(self):
        """Get the unisphere version from the server.

        :returns: version dict
        """
        post_90_endpoint = '/version'
        pre_91_endpoint = '/system/version'

        status_code, version_dict = self.request(post_90_endpoint, GET)
        if status_code is not STATUS_200:
            status_code, version_dict = self.request(pre_91_endpoint, GET)

        if not version_dict:
            LOG.error("Unisphere version info not found.")
        return version_dict

    def get_srp_by_name(self, array, srp=None):
        """Returns the details of a storage pool.

        :param array: the array serial number
        :param srp: the storage resource pool name
        :returns: SRP_details -- dict or None
        """
        LOG.debug("storagePoolName: %(srp)s, array: %(array)s.",
                  {'srp': srp, 'array': array})
        srp_details = self.get_resource(array, SLOPROVISIONING, 'srp',
                                        resource_name=srp, params=None)
        return srp_details

    def get_slo_list(self, array, is_next_gen, array_model):
        """Retrieve the list of slo's from the array

        :param array: the array serial number
        :param is_next_gen: next generation flag
        :param array_model
        :returns: slo_list -- list of service level names
        """
        slo_list = []
        slo_dict = self.get_resource(array, SLOPROVISIONING, 'slo')
        if slo_dict and slo_dict.get('sloId'):
            if not is_next_gen and (
                    any(array_model in x for x in
                        utils.VMAX_AFA_MODELS)):
                if 'Optimized' in slo_dict.get('sloId'):
                    slo_dict['sloId'].remove('Optimized')
            for slo in slo_dict['sloId']:
                if slo and slo not in slo_list:
                    slo_list.append(slo)
        return slo_list

    def get_workload_settings(self, array, is_next_gen):
        """Get valid workload options from array.

        Workloads are no longer supported from HyperMaxOS 5978 onwards.
        :param array: the array serial number
        :param is_next_gen: is next generation flag
        :returns: workload_setting -- list of workload names
        """
        workload_setting = []
        if is_next_gen:
            workload_setting.append('None')
        else:
            wl_details = self.get_resource(
                array, SLOPROVISIONING, 'workloadtype')
            if wl_details:
                workload_setting = wl_details['workloadId']
        return workload_setting

    def get_vmax_model(self, array):
        """Get the PowerMax/VMAX model.

        :param array: the array serial number
        :returns: the PowerMax/VMAX model
        """
        vmax_version = None
        system_info = self.get_array_detail(array)
        if system_info and system_info.get('model'):
            vmax_version = system_info.get('model')
        return vmax_version

    def get_array_model_info(self, array):
        """Get the PowerMax/VMAX model.

        :param array: the array serial number
        :returns: the PowerMax/VMAX model
        """
        array_model = None
        is_next_gen = False
        system_info = self.get_array_detail(array)
        if system_info and system_info.get('model'):
            array_model = system_info.get('model')
        if system_info:
            ucode_version = system_info['ucode'].split('.')[0]
            if ucode_version >= UCODE_5978:
                is_next_gen = True
        return array_model, is_next_gen

    def get_array_ucode_version(self, array):
        """Get the PowerMax/VMAX uCode version.

        :param array: the array serial number
        :returns: the PowerMax/VMAX uCode version
        """
        ucode_version = None
        system_info = self.get_array_detail(array)
        if system_info:
            ucode_version = system_info['ucode']
        return ucode_version

    def is_compression_capable(self, array):
        """Check if array is compression capable.

        :param array: array serial number
        :returns: bool
        """
        is_compression_capable = False
        target_uri = ("/%s/sloprovisioning/symmetrix?compressionCapable=true"
                      % U4V_VERSION)
        status_code, message = self.request(target_uri, GET)
        self.check_status_code_success(
            "Check if compression enabled", status_code, message)
        if message.get('symmetrixId'):
            if array in message['symmetrixId']:
                is_compression_capable = True
        return is_compression_capable

    def get_storage_group(self, array, storage_group_name):
        """Given a name, return storage group details.

        :param array: the array serial number
        :param storage_group_name: the name of the storage group
        :returns: storage group dict or None
        """
        return self.get_resource(
            array, SLOPROVISIONING, 'storagegroup',
            resource_name=storage_group_name)

    def get_storage_group_list(self, array, params=None):
        """Given a name, return storage group details.

        :param array: the array serial number
        :param params: dict of optional filters
        :returns: storage group dict or None
        """
        return self.get_resource(
            array, SLOPROVISIONING, 'storagegroup', params=params)

    def get_num_vols_in_sg(self, array, storage_group_name):
        """Get the number of volumes in a storage group.

        :param array: the array serial number
        :param storage_group_name: the storage group name
        :returns: num_vols -- int
        """
        num_vols = 0
        storagegroup = self.get_storage_group(array, storage_group_name)
        try:
            num_vols = int(storagegroup['num_of_vols'])
        except (KeyError, TypeError):
            pass
        return num_vols

    def is_child_sg_in_parent_sg(self, array, child_name, parent_name):
        """Check if a child storage group is a member of a parent group.

        :param array: the array serial number
        :param child_name: the child sg name
        :param parent_name: the parent sg name
        :returns: bool
        """
        parent_sg = self.get_storage_group(array, parent_name)
        if parent_sg and parent_sg.get('child_storage_group'):
            child_sg_list = parent_sg['child_storage_group']
            if child_name.lower() in (
                    child.lower() for child in child_sg_list):
                return True
        return False

    def add_child_sg_to_parent_sg(
            self, array, child_sg, parent_sg, extra_specs):
        """Add a storage group to a parent storage group.

        This method adds an existing storage group to another storage
        group, i.e. cascaded storage groups.
        :param array: the array serial number
        :param child_sg: the name of the child sg
        :param parent_sg: the name of the parent sg
        :param extra_specs: the extra specifications
        """
        payload = {"editStorageGroupActionParam": {
            "expandStorageGroupParam": {
                "addExistingStorageGroupParam": {
                    "storageGroupId": [child_sg]}}}}

        sc, job = self.modify_storage_group(array, parent_sg, payload)
        self.wait_for_job('Add child sg to parent sg', sc, job, extra_specs)

    def remove_child_sg_from_parent_sg(
            self, array, child_sg, parent_sg, extra_specs):
        """Remove a storage group from its parent storage group.

        This method removes a child storage group from its parent group.
        :param array: the array serial number
        :param child_sg: the name of the child sg
        :param parent_sg: the name of the parent sg
        :param extra_specs: the extra specifications
        """
        payload = {"editStorageGroupActionParam": {
            "removeStorageGroupParam": {
                "storageGroupId": [child_sg], "force": 'true'}}}
        status_code, job = self.modify_storage_group(
            array, parent_sg, payload)
        self.wait_for_job(
            'Remove child sg from parent sg', status_code, job, extra_specs)

    def _create_storagegroup(self, array, payload):
        """Create a storage group.

        :param array: the array serial number
        :param payload: the payload -- dict
        :returns: status_code -- int, message -- string, server response
        """
        return self.create_resource(
            array, SLOPROVISIONING, 'storagegroup', payload)

    def create_storage_group(self, array, storagegroup_name,
                             srp, slo, workload, extra_specs,
                             do_disable_compression=False):
        """Create the volume in the specified storage group.

        :param array: the array serial number
        :param storagegroup_name: the group name (String)
        :param srp: the SRP (String)
        :param slo: the SLO (String)
        :param workload: the workload (String)
        :param do_disable_compression: flag for disabling compression
        :param extra_specs: additional info
        :returns: storagegroup_name - string
        """
        srp_id = srp if slo else "None"
        payload = ({"srpId": srp_id,
                    "storageGroupId": storagegroup_name,
                    "emulation": "FBA"})

        if slo:
            if self.is_next_gen_array(array):
                workload = 'NONE'
            slo_param = {"sloId": slo,
                         "workloadSelection": workload,
                         "volumeAttributes": [{
                             "volume_size": "0",
                             "capacityUnit": "GB",
                             "num_of_vols": 0}]}
            if do_disable_compression:
                slo_param.update({"noCompression": "true"})
            elif self.is_compression_capable(array):
                slo_param.update({"noCompression": "false"})

            payload.update({"sloBasedStorageGroupParam": [slo_param]})

        status_code, job = self._create_storagegroup(array, payload)
        self.wait_for_job('Create storage group', status_code,
                          job, extra_specs)
        return storagegroup_name

    def modify_storage_group(self, array, storagegroup, payload,
                             version=U4V_VERSION):
        """Modify a storage group (PUT operation).

        :param version: the uv4 version
        :param array: the array serial number
        :param storagegroup: storage group name
        :param payload: the request payload
        :returns: status_code -- int, message -- string, server response
        """
        return self.modify_resource(
            array, SLOPROVISIONING, 'storagegroup', payload, version,
            resource_name=storagegroup)

    def modify_storage_array(self, array, payload):
        """Modify a storage array (PUT operation).

        :param array: the array serial number
        :param payload: the request payload
        :returns: status_code -- int, message -- string, server response
        """
        target_uri = '/%s/sloprovisioning/symmetrix/%s' % (U4V_VERSION, array)
        status_code, message = self.request(target_uri, PUT,
                                            request_object=payload)
        operation = 'modify %(res)s resource' % {'res': 'symmetrix'}
        self.check_status_code_success(operation, status_code, message)
        return status_code, message

    def create_volume_from_sg(self, array, volume_name, storagegroup_name,
                              volume_size, extra_specs, rep_info=None):
        """Create a new volume in the given storage group.

        :param array: the array serial number
        :param volume_name: the volume name (String)
        :param storagegroup_name: the storage group name
        :param volume_size: volume size (String)
        :param extra_specs: the extra specifications
        :param rep_info: replication info dict if volume is replication enabled
        :returns: dict -- volume_dict - the volume dict
        :raises: VolumeBackendAPIException
        """
        payload = (
            {"executionOption": "ASYNCHRONOUS",
             "editStorageGroupActionParam": {
                 "expandStorageGroupParam": {
                     "addVolumeParam": {
                         "emulation": "FBA",
                         "create_new_volumes": "False",
                         "volumeAttributes": [
                             {
                                 "num_of_vols": 1,
                                 "volumeIdentifier": {
                                     "identifier_name": volume_name,
                                     "volumeIdentifierChoice":
                                         "identifier_name"
                                 },
                                 "volume_size": volume_size,
                                 "capacityUnit": "GB"}]}}}})

        if rep_info:
            payload = self.utils.update_payload_for_rdf_vol_create(
                payload, rep_info[utils.REMOTE_ARRAY], storagegroup_name)

        status_code, job = self.modify_storage_group(
            array, storagegroup_name, payload)

        LOG.debug("Create Volume: %(volumename)s. Status code: %(sc)lu.",
                  {'volumename': volume_name,
                   'sc': status_code})

        task = self.wait_for_job('Create volume', status_code,
                                 job, extra_specs)

        # Find the newly created volume.
        device_id = None
        if rep_info:
            updated_device_list = self.get_volume_list(
                array, {'storageGroupId': storagegroup_name,
                        'rdf_group_number': rep_info['rdf_group_no']})
            unique_devices = self.utils.get_unique_device_ids_from_lists(
                rep_info['initial_device_list'], updated_device_list)

            if 0 < len(unique_devices) < 2:
                device_id = unique_devices[0]
                self.rename_volume(array, device_id, volume_name)
            else:
                raise exception.VolumeBackendAPIException(_(
                    "There has been more than one volume created in the "
                    "SRDF protected Storage Group since the current create "
                    "volume process begun. Not possible to discern what "
                    "volume has been created by PowerMax Cinder driver."))

        # Find the newly created volume if not located as part of replication
        # OPT workaround
        if not device_id and task:
            for t in task:
                try:
                    desc = t["description"]
                    if CREATE_VOL_STRING in desc:
                        t_list = desc.split()
                        device_id = t_list[(len(t_list) - 1)]
                        device_id = device_id[1:-1]
                        break
                    elif POPULATE_SG_LIST in desc:
                        regex_str = (r'Populating Storage Group\(s\) ' +
                                     r'with volumes : \[(.+)\]$')
                        full_str = re.compile(regex_str)
                        match = full_str.match(desc)
                        device_id = match.group(1) if match else None
                    if device_id:
                        self.get_volume(array, device_id)
                except Exception as e:
                    LOG.info("Could not retrieve device id from job. "
                             "Exception received was %(e)s. Attempting "
                             "retrieval by volume_identifier.", {'e': e})

        if not device_id:
            device_id = self.find_volume_device_id(array, volume_name)

        volume_dict = {utils.ARRAY: array, utils.DEVICE_ID: device_id}
        return volume_dict

    def add_storage_group_tag(self, array, storagegroup_name,
                              tag_list, extra_specs):
        """Create a new tag(s) on a storage group

        :param array: the array serial number
        :param storagegroup_name: the storage group name
        :param tag_list: comma delimited list
        :param extra_specs: the extra specifications
        """
        payload = (
            {"executionOption": "ASYNCHRONOUS",
             "editStorageGroupActionParam": {
                 "tagManagementParam": {
                     "addTagsParam": {
                         "tag_name": tag_list
                     }}}})
        status_code, job = self.modify_storage_group(
            array, storagegroup_name, payload)

        LOG.debug("Add tag to storage group: %(sg_name)s. "
                  "Status code: %(sc)lu.",
                  {'sg_name': storagegroup_name,
                   'sc': status_code})

        self.wait_for_job(
            'Add tag to storage group', status_code, job, extra_specs)

    def add_storage_array_tags(self, array, tag_list, extra_specs):
        """Create a new tag(s) on a storage group

        :param array: the array serial number
        :param tag_list: comma delimited list
        :param extra_specs: the extra specifications
        """
        payload = (
            {"executionOption": "ASYNCHRONOUS",
             "editSymmetrixActionParam": {
                 "tagManagementParam": {
                     "addTagsParam": {
                         "tag_name": tag_list
                     }}}})
        status_code, job = self.modify_storage_array(
            array, payload)

        LOG.debug("Add tag to storage array: %(array)s. "
                  "Status code: %(sc)lu.",
                  {'array': array,
                   'sc': status_code})

        self.wait_for_job(
            'Add tag to storage array', status_code, job, extra_specs)

    def check_volume_device_id(self, array, device_id, volume_id,
                               name_id=None):
        """Check if the identifiers match for a given volume.

        :param array: the array serial number
        :param device_id: the device id
        :param volume_id: cinder volume id
        :param name_id: name id - used in host_assisted migration, optional
        :returns: found_device_id
        """
        found_device_id = None
        if not device_id:
            return found_device_id
        element_name = self.utils.get_volume_element_name(volume_id)
        vol_details = self.get_volume(array, device_id)
        if vol_details:
            vol_identifier = vol_details.get('volume_identifier', None)
            LOG.debug('Element name = %(en)s, Vol identifier = %(vi)s, '
                      'Device id = %(di)s',
                      {'en': element_name, 'vi': vol_identifier,
                       'di': device_id})
            if vol_identifier:
                if vol_identifier in element_name:
                    found_device_id = device_id
                    if vol_identifier != element_name:
                        LOG.debug("Device %(di)s is a legacy volume created "
                                  "using SMI-S.",
                                  {'di': device_id})
                elif name_id:
                    # This may be host-assisted migration case
                    element_name = self.utils.get_volume_element_name(name_id)
                    if vol_identifier == element_name:
                        found_device_id = device_id
        return found_device_id

    def add_vol_to_sg(self, array, storagegroup_name, device_id, extra_specs,
                      force=False):
        """Add a volume to a storage group.

        :param array: the array serial number
        :param storagegroup_name: storage group name
        :param device_id: the device id
        :param extra_specs: extra specifications
        :param force: add force argument to call
        """
        if not isinstance(device_id, list):
            device_id = [device_id]

        force_add = "true" if force else "false"

        payload = ({"executionOption": "ASYNCHRONOUS",
                    "editStorageGroupActionParam": {
                        "expandStorageGroupParam": {
                            "addSpecificVolumeParam": {
                                "volumeId": device_id,
                                "remoteSymmSGInfoParam": {
                                    "force": force_add}}}}})
        status_code, job = self.modify_storage_group(
            array, storagegroup_name, payload)

        self.wait_for_job('Add volume to sg', status_code, job, extra_specs)

    @retry(retry_exc_tuple, interval=2, retries=3)
    def remove_vol_from_sg(self, array, storagegroup_name,
                           device_id, extra_specs):
        """Remove a volume from a storage group.

        :param array: the array serial number
        :param storagegroup_name: storage group name
        :param device_id: the device id
        :param extra_specs: the extra specifications
        """

        force_vol_edit = (
            "true" if utils.FORCE_VOL_EDIT in extra_specs else "false")
        if not isinstance(device_id, list):
            device_id = [device_id]
        payload = ({"executionOption": "ASYNCHRONOUS",
                    "editStorageGroupActionParam": {
                        "removeVolumeParam": {
                            "volumeId": device_id,
                            "remoteSymmSGInfoParam": {
                                "force": force_vol_edit}}}})
        status_code, job = self.modify_storage_group(
            array, storagegroup_name, payload)

        self.wait_for_job('Remove vol from sg', status_code, job, extra_specs)

    def update_storagegroup_qos(self, array, storage_group_name, extra_specs):
        """Update the storagegroupinstance with qos details.

        If maxIOPS or maxMBPS is in extra_specs, then DistributionType can be
        modified in addition to maxIOPS or/and maxMBPS
        If maxIOPS or maxMBPS is NOT in extra_specs, we check to see if
        either is set in StorageGroup. If so, then DistributionType can be
        modified
        :param array: the array serial number
        :param storage_group_name: the storagegroup instance name
        :param extra_specs: extra specifications
        :returns: bool, True if updated, else False
        """
        return_value = False
        sg_details = self.get_storage_group(array, storage_group_name)
        sg_qos_details = None
        sg_maxiops = None
        sg_maxmbps = None
        sg_distribution_type = None
        property_dict = {}
        try:
            sg_qos_details = sg_details['hostIOLimit']
            sg_maxiops = sg_qos_details['host_io_limit_io_sec']
            sg_maxmbps = sg_qos_details['host_io_limit_mb_sec']
            sg_distribution_type = sg_qos_details['dynamicDistribution']
        except KeyError:
            LOG.debug("Unable to get storage group QoS details.")
        if 'total_iops_sec' in extra_specs.get('qos'):
            property_dict = self.utils.validate_qos_input(
                'total_iops_sec', sg_maxiops, extra_specs.get('qos'),
                property_dict)
        if 'total_bytes_sec' in extra_specs.get('qos'):
            property_dict = self.utils.validate_qos_input(
                'total_bytes_sec', sg_maxmbps, extra_specs.get('qos'),
                property_dict)
        if 'DistributionType' in extra_specs.get('qos') and property_dict:
            property_dict = self.utils.validate_qos_distribution_type(
                sg_distribution_type, extra_specs.get('qos'), property_dict)

        if property_dict:
            payload = {"editStorageGroupActionParam": {
                "setHostIOLimitsParam": property_dict}}
            status_code, message = (
                self.modify_storage_group(array, storage_group_name, payload))
            try:
                self.check_status_code_success('Add qos specs', status_code,
                                               message)
                return_value = True
            except Exception as e:
                LOG.error("Error setting qos. Exception received was: "
                          "%(e)s", {'e': e})
                return_value = False
        return return_value

    def set_storagegroup_srp(
            self, array, storagegroup_name, srp_name, extra_specs):
        """Modify a storage group's srp value.

        :param array: the array serial number
        :param storagegroup_name: the storage group name
        :param srp_name: the srp pool name
        :param extra_specs: the extra specifications
        """
        payload = {"editStorageGroupActionParam": {
            "editStorageGroupSRPParam": {"srpId": srp_name}}}
        status_code, job = self.modify_storage_group(
            array, storagegroup_name, payload)
        self.wait_for_job("Set storage group srp", status_code,
                          job, extra_specs)

    def get_vmax_default_storage_group(
            self, array, srp, slo, workload,
            do_disable_compression=False, is_re=False, rep_mode=None):
        """Get the default storage group.

        :param array: the array serial number
        :param srp: the pool name
        :param slo: the SLO
        :param workload: the workload
        :param do_disable_compression: flag for disabling compression
        :param is_re: flag for replication
        :param rep_mode: flag to indicate replication mode
        :returns: the storage group dict (or None), the storage group name
        """
        if self.is_next_gen_array(array):
            workload = 'NONE'
        storagegroup_name = self.utils.get_default_storage_group_name(
            srp, slo, workload, do_disable_compression, is_re, rep_mode)
        storagegroup = self.get_storage_group(array, storagegroup_name)
        return storagegroup, storagegroup_name

    def delete_storage_group(self, array, storagegroup_name):
        """Delete a storage group.

        :param array: the array serial number
        :param storagegroup_name: storage group name
        """
        self.delete_resource(
            array, SLOPROVISIONING, 'storagegroup', storagegroup_name)
        LOG.debug("Storage Group successfully deleted.")

    def move_volume_between_storage_groups(
            self, array, device_id, source_storagegroup_name,
            target_storagegroup_name, extra_specs, force=False):
        """Move a volume to a different storage group.

        :param array: the array serial number
        :param source_storagegroup_name: the originating storage group name
        :param target_storagegroup_name: the destination storage group name
        :param device_id: the device id
        :param extra_specs: extra specifications
        :param force: force flag (necessary on a detach)
        """
        force_flag = "true" if force else "false"
        payload = ({"executionOption": "ASYNCHRONOUS",
                    "editStorageGroupActionParam": {
                        "moveVolumeToStorageGroupParam": {
                            "volumeId": [device_id],
                            "storageGroupId": target_storagegroup_name,
                            "force": force_flag}}})
        status_code, job = self.modify_storage_group(
            array, source_storagegroup_name, payload)
        self.wait_for_job('move volume between storage groups', status_code,
                          job, extra_specs)

    def get_volume(self, array, device_id):
        """Get a PowerMax/VMAX volume from array.

        :param array: the array serial number
        :param device_id: the volume device id
        :returns: volume dict
        :raises: VolumeBackendAPIException
        """
        version = self.get_uni_version()[1]
        volume_dict = self.get_resource(
            array, SLOPROVISIONING, 'volume', resource_name=device_id,
            version=version)
        if not volume_dict:
            exception_message = (_("Volume %(deviceID)s not found.")
                                 % {'deviceID': device_id})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(
                message=exception_message)
        return volume_dict

    def _get_private_volume(self, array, device_id):
        """Get a more detailed list of attributes of a volume.

        :param array: the array serial number
        :param device_id: the volume device id
        :returns: volume dict
        :raises: VolumeBackendAPIException
        """
        try:
            wwn = (self.get_volume(array, device_id))['wwn']
            params = {'wwn': wwn}
            volume_info = self.get_resource(
                array, SLOPROVISIONING, 'volume', params=params,
                private='/private')
            volume_dict = volume_info[0]
        except (KeyError, TypeError):
            exception_message = (_("Volume %(deviceID)s not found.")
                                 % {'deviceID': device_id})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(
                message=exception_message)
        return volume_dict

    def get_volume_list(self, array, params):
        """Get a filtered list of PowerMax/VMAX volumes from array.

        Filter parameters are required as the unfiltered volume list could be
        very large and could affect performance if called often.
        :param array: the array serial number
        :param params: filter parameters
        :returns: device_ids -- list
        """
        device_ids = []
        volume_dict_list = self.get_resource(
            array, SLOPROVISIONING, 'volume', params=params)
        try:
            for vol_dict in volume_dict_list:
                device_id = vol_dict['volumeId']
                device_ids.append(device_id)
        except (KeyError, TypeError):
            pass
        return device_ids

    def get_private_volume_list(self, array, params=None):
        """Retrieve list with volume details.

        :param array: the array serial number
        :param params: filter parameters
        :returns: list -- dicts with volume information
        """
        if isinstance(params, dict):
            params['expiration_time_mins'] = ITERATOR_EXPIRATION
        elif isinstance(params, str):
            params += '&expiration_time_mins=%(expire)s' % {
                'expire': ITERATOR_EXPIRATION}
        else:
            params = {'expiration_time_mins': ITERATOR_EXPIRATION}

        return self.get_resource(
            array, SLOPROVISIONING, 'volume', params=params,
            private='/private')

    def _modify_volume(self, array, device_id, payload):
        """Modify a volume (PUT operation).

        :param array: the array serial number
        :param device_id: volume device id
        :param payload: the request payload
        """
        return self.modify_resource(array, SLOPROVISIONING, 'volume',
                                    payload, resource_name=device_id)

    def extend_volume(self, array, device_id, new_size, extra_specs,
                      rdf_grp_no=None):
        """Extend a PowerMax/VMAX volume.

        :param array: the array serial number
        :param device_id: volume device id
        :param new_size: the new required size for the device
        :param extra_specs: the extra specifications
        :param rdf_grp_no: the RDG group number
        """
        extend_vol_payload = {'executionOption': 'ASYNCHRONOUS',
                              'editVolumeActionParam': {
                                  'expandVolumeParam': {
                                      'volumeAttribute': {
                                          'volume_size': new_size,
                                          'capacityUnit': 'GB'}}}}

        if rdf_grp_no:
            extend_vol_payload['editVolumeActionParam'][
                'expandVolumeParam'].update({'rdfGroupNumber': rdf_grp_no})

        status_code, job = self._modify_volume(
            array, device_id, extend_vol_payload)
        LOG.debug("Extend Device: %(device_id)s. Status code: %(sc)lu.",
                  {'device_id': device_id, 'sc': status_code})
        self.wait_for_job('Extending volume', status_code, job, extra_specs)

    def rename_volume(self, array, device_id, new_name):
        """Rename a volume.

        :param array: the array serial number
        :param device_id: the volume device id
        :param new_name: the new name for the volume, can be None
        """
        if new_name is not None:
            vol_identifier_dict = {
                "identifier_name": new_name,
                "volumeIdentifierChoice": "identifier_name"}
        else:
            vol_identifier_dict = {"volumeIdentifierChoice": "none"}
        rename_vol_payload = {"editVolumeActionParam": {
            "modifyVolumeIdentifierParam": {
                "volumeIdentifier": vol_identifier_dict}}}
        self._modify_volume(array, device_id, rename_vol_payload)

    def delete_volume(self, array, device_id):
        """Delete a volume.

        :param array: the array serial number
        :param device_id: volume device id
        """

        if ((self.ucode_major_level >= utils.UCODE_5978)
                and (self.ucode_minor_level > utils.UCODE_5978_ELMSR)):
            # Use Rapid TDEV Deallocation to delete after ELMSR
            try:
                # Rename volume, removing the OS-<cinderUUID>
                self.rename_volume(array, device_id, None)
                self.delete_resource(array, SLOPROVISIONING,
                                     "volume", device_id)
            except Exception as e:
                LOG.warning('Delete volume failed with %(e)s.', {'e': e})
                raise
        else:
            # Pre-Foxtail, deallocation and delete are separate calls
            payload = {"editVolumeActionParam": {
                "freeVolumeParam": {"free_volume": 'true'}}}
            try:
                # Rename volume, removing the OS-<cinderUUID>
                self.rename_volume(array, device_id, None)
                self._modify_volume(array, device_id, payload)
                pass
            except Exception as e:
                LOG.warning('Deallocate volume failed with %(e)s.'
                            'Attempting delete.', {'e': e})
                # Try to delete the volume if deallocate failed.
                self.delete_resource(array, SLOPROVISIONING,
                                     "volume", device_id)

    def find_mv_connections_for_vol(self, array, maskingview, device_id):
        """Find the host_lun_id for a volume in a masking view.

        :param array: the array serial number
        :param maskingview: the masking view name
        :param device_id: the device ID
        :returns: host_lun_id -- int
        """
        host_lun_id = None
        resource_name = ('%(maskingview)s/connections'
                         % {'maskingview': maskingview})
        params = {'volume_id': device_id}
        connection_info = self.get_resource(
            array, SLOPROVISIONING, 'maskingview',
            resource_name=resource_name, params=params)
        if not connection_info:
            LOG.error('Cannot retrieve masking view connection information '
                      'for %(mv)s.', {'mv': maskingview})
        else:
            try:
                host_lun_id = (
                    connection_info[
                        'maskingViewConnection'][0]['host_lun_address'])
                host_lun_id = int(host_lun_id, 16)
            except Exception as e:
                LOG.error("Unable to retrieve connection information "
                          "for volume %(vol)s in masking view %(mv)s. "
                          "Exception received: %(e)s.",
                          {'vol': device_id, 'mv': maskingview,
                           'e': e})
        return host_lun_id

    def get_storage_groups_from_volume(self, array, device_id):
        """Returns all the storage groups for a particular volume.

        :param array: the array serial number
        :param device_id: the volume device id
        :returns: storagegroup_list
        """
        sg_list = []
        vol = self.get_volume(array, device_id)
        if vol and vol.get('storageGroupId'):
            sg_list = vol['storageGroupId']
        num_storage_groups = len(sg_list)
        LOG.debug("There are %(num)d storage groups associated "
                  "with volume %(deviceId)s.",
                  {'num': num_storage_groups, 'deviceId': device_id})
        return sg_list

    def is_volume_in_storagegroup(self, array, device_id, storagegroup):
        """See if a volume is a member of the given storage group.

        :param array: the array serial number
        :param device_id: the device id
        :param storagegroup: the storage group name
        :returns: bool
        """
        is_vol_in_sg = False
        sg_list = self.get_storage_groups_from_volume(array, device_id)
        if storagegroup in sg_list:
            is_vol_in_sg = True
        return is_vol_in_sg

    def find_volume_device_id(self, array, volume_name):
        """Given a volume identifier, find the corresponding device_id.

        :param array: the array serial number
        :param volume_name: the volume name (OS-<UUID>)
        :returns: device_id
        """
        device_id = None
        params = {"volume_identifier": volume_name}

        volume_list = self.get_volume_list(array, params)
        if not volume_list:
            LOG.debug("Cannot find record for volume %(volumeId)s.",
                      {'volumeId': volume_name})
        else:
            device_id = volume_list[0]
        return device_id

    def find_volume_identifier(self, array, device_id):
        """Get the volume identifier of a PowerMax/VMAX volume.

        :param array: array serial number
        :param device_id: the device id
        :returns: the volume identifier -- string
        """
        vol = self.get_volume(array, device_id)
        return vol['volume_identifier']

    def get_size_of_device_on_array(self, array, device_id):
        """Get the size of the volume from the array.

        :param array: the array serial number
        :param device_id: the volume device id
        :returns: size --  or None
        """
        cap = None
        try:
            vol = self.get_volume(array, device_id)
            cap = vol['cap_gb']
        except Exception as e:
            LOG.error("Error retrieving size of volume %(vol)s. "
                      "Exception received was %(e)s.",
                      {'vol': device_id, 'e': e})
        return cap

    def get_portgroup(self, array, portgroup):
        """Get a portgroup from the array.

        :param array: array serial number
        :param portgroup: the portgroup name
        :returns: portgroup dict or None
        """
        return self.get_resource(
            array, SLOPROVISIONING, 'portgroup', resource_name=portgroup)

    def get_port_ids(self, array, port_group_name):
        """Get a list of port identifiers from a port group.

        :param array: the array serial number
        :param port_group_name: the name of the portgroup
        :returns: list of port ids, e.g. ['FA-3D:35', 'FA-4D:32']
        """
        portlist = []
        portgroup_info = self.get_portgroup(array, port_group_name)
        if portgroup_info:
            port_key = portgroup_info["symmetrixPortKey"]
            for key in port_key:
                port = "%s:%s" % (key['directorId'], key['portId'])
                portlist.append(port)
        else:
            exception_message = (_("Cannot find port group %(pg)s.")
                                 % {'pg': port_group_name})
            raise exception.VolumeBackendAPIException(exception_message)
        return portlist

    def get_port(self, array, port_id):
        """Get director port details.

        :param array: the array serial number
        :param port_id: the port id
        :returns: port dict, or None
        """
        dir_id = port_id.split(':')[0]
        port_no = port_id.split(':')[1]

        resource_name = ('%(directorId)s/port/%(port_number)s'
                         % {'directorId': dir_id, 'port_number': port_no})
        return self.get_resource(array, SYSTEM, 'director',
                                 resource_name=resource_name)

    def get_iscsi_ip_address_and_iqn(self, array, port_id):
        """Get the IPv4Address from the director port.

        :param array: the array serial number
        :param port_id: the director port identifier
        :returns: (list of ip_addresses, iqn)
        """
        ip_addresses, iqn = None, None
        port_details = self.get_port(array, port_id)
        if port_details:
            ip_addresses = port_details['symmetrixPort']['ip_addresses']
            iqn = port_details['symmetrixPort']['identifier']
        return ip_addresses, iqn

    def get_ip_interface_physical_port(self, array_id, virtual_port,
                                       ip_address):
        """Get the physical port associated with a virtual port and IP address.

        :param array_id: the array serial number -- str
        :param virtual_port: the director & virtual port identifier -- str
        :param ip_address: the ip address associated with the port -- str
        :returns: physical director:port -- str
        """
        director_id = virtual_port.split(':')[0]
        params = {'ip_list': ip_address, 'iscsi_target': False}
        target_uri = self.build_uri(
            category=SYSTEM, resource_level='symmetrix',
            resource_level_id=array_id, resource_type='director',
            resource_type_id=director_id, resource='port')

        port_info = self.get_request(
            target_uri, 'port IP interface', params)
        port_key = port_info.get('symmetrixPortKey', [])

        if len(port_key) == 1:
            port_info = port_key[0]
            port_id = port_info.get('portId')
            dir_port = '%(d)s:%(p)s' % {'d': director_id, 'p': port_id}
        else:
            if len(port_key) == 0:
                msg = (_(
                    "Virtual port %(vp)s and IP address %(ip)s are not "
                    "associated a physical director:port. Please check "
                    "iSCSI configuration of backend array %(arr)s." % {
                        'vp': virtual_port, 'ip': ip_address, 'arr': array_id}
                ))
            else:
                msg = (_(
                    "Virtual port %(vp)s and IP address %(ip)s are associated "
                    "with more than one physical director:port. Please check "
                    "iSCSI configuration of backend array %(arr)s." % {
                        'vp': virtual_port, 'ip': ip_address, 'arr': array_id}
                ))
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(message=msg)

        return dir_port

    def get_target_wwns(self, array, portgroup):
        """Get the director ports' wwns.

        :param array: the array serial number
        :param portgroup: portgroup
        :returns: target_wwns -- the list of target wwns for the masking view
        """
        target_wwns = []
        port_ids = self.get_port_ids(array, portgroup)
        for port in port_ids:
            port_info = self.get_port(array, port)
            if port_info:
                wwn = port_info['symmetrixPort']['identifier']
                target_wwns.append(wwn)
            else:
                LOG.error("Error retrieving port %(port)s "
                          "from portgroup %(portgroup)s.",
                          {'port': port, 'portgroup': portgroup})
        return target_wwns

    def get_initiator_group(self, array, initiator_group=None, params=None):
        """Retrieve initiator group details from the array.

        :param array: the array serial number
        :param initiator_group: the initaitor group name
        :param params: optional filter parameters
        :returns: initiator group dict, or None
        """
        return self.get_resource(
            array, SLOPROVISIONING, 'host',
            resource_name=initiator_group, params=params)

    def get_initiator(self, array, initiator_id):
        """Retrieve initiator details from the array.

        :param array: the array serial number
        :param initiator_id: the initiator id
        :returns: initiator dict, or None
        """
        return self.get_resource(
            array, SLOPROVISIONING, 'initiator',
            resource_name=initiator_id)

    def get_initiator_list(self, array, params=None):
        """Retrieve initiator list from the array.

        :param array: the array serial number
        :param params: dict of optional params
        :returns: list of initiators
        """
        init_dict = self.get_resource(array, SLOPROVISIONING, 'initiator',
                                      params=params)
        try:
            init_list = init_dict['initiatorId']
        except (KeyError, TypeError):
            init_list = []
        return init_list

    def get_initiator_group_from_initiator(self, array, initiator):
        """Given an initiator, get its corresponding initiator group, if any.

        :param array: the array serial number
        :param initiator: the initiator id
        :returns: found_init_group_name -- string
        """
        found_init_group_name = None
        init_details = self.get_initiator(array, initiator)
        if init_details:
            found_init_group_name = init_details.get('host')
        else:
            LOG.error("Unable to retrieve initiator details for "
                      "%(init)s.", {'init': initiator})
        return found_init_group_name

    def create_initiator_group(self, array, init_group_name,
                               init_list, extra_specs):
        """Create a new initiator group containing the given initiators.

        :param array: the array serial number
        :param init_group_name: the initiator group name
        :param init_list: the list of initiators
        :param extra_specs: extra specifications
        """
        new_ig_data = ({"executionOption": "ASYNCHRONOUS",
                        "hostId": init_group_name, "initiatorId": init_list})
        sc, job = self.create_resource(array, SLOPROVISIONING,
                                       'host', new_ig_data)
        self.wait_for_job('create initiator group', sc, job, extra_specs)

    def delete_initiator_group(self, array, initiatorgroup_name):
        """Delete an initiator group.

        :param array: the array serial number
        :param initiatorgroup_name: initiator group name
        """
        self.delete_resource(
            array, SLOPROVISIONING, 'host', initiatorgroup_name)
        LOG.debug("Initiator Group successfully deleted.")

    def get_masking_view(self, array, masking_view_name):
        """Get details of a masking view.

        :param array: array serial number
        :param masking_view_name: the masking view name
        :returns: masking view dict
        """
        return self.get_resource(
            array, SLOPROVISIONING, 'maskingview', masking_view_name)

    def get_masking_view_list(self, array, params):
        """Get a list of masking views from the array.

        :param array: array serial number
        :param params: optional GET parameters
        :returns: masking view list
        """
        masking_view_list = []
        masking_view_details = self.get_resource(
            array, SLOPROVISIONING, 'maskingview', params=params)
        try:
            masking_view_list = masking_view_details['maskingViewId']
        except (KeyError, TypeError):
            pass
        return masking_view_list

    def get_masking_views_from_storage_group(self, array, storagegroup):
        """Return any masking views associated with a storage group.

        :param array: the array serial number
        :param storagegroup: the storage group name
        :returns: masking view list
        """
        maskingviewlist = []
        storagegroup = self.get_storage_group(array, storagegroup)
        if storagegroup and storagegroup.get('maskingview'):
            maskingviewlist = storagegroup['maskingview']
        return maskingviewlist

    def get_masking_views_by_initiator_group(
            self, array, initiatorgroup_name):
        """Given initiator group, retrieve the masking view instance name.

        Retrieve the list of masking view instances associated with the
        given initiator group.
        :param array: the array serial number
        :param initiatorgroup_name: the name of the initiator group
        :returns: list of masking view names
        """
        masking_view_list = []
        ig_details = self.get_initiator_group(
            array, initiatorgroup_name)
        if ig_details:
            if ig_details.get('maskingview'):
                masking_view_list = ig_details['maskingview']
        else:
            LOG.error("Error retrieving initiator group %(ig_name)s",
                      {'ig_name': initiatorgroup_name})
        return masking_view_list

    def get_element_from_masking_view(
            self, array, maskingview_name, portgroup=False, host=False,
            storagegroup=False):
        """Return the name of the specified element from a masking view.

        :param array: the array serial number
        :param maskingview_name: the masking view name
        :param portgroup: the port group name - optional
        :param host: the host name - optional
        :param storagegroup: the storage group name - optional
        :returns: name of the specified element -- string
        :raises: VolumeBackendAPIException
        """
        element = None
        masking_view_details = self.get_masking_view(array, maskingview_name)
        if masking_view_details:
            if portgroup:
                element = masking_view_details['portGroupId']
            elif host:
                element = masking_view_details['hostId']
            elif storagegroup:
                element = masking_view_details['storageGroupId']
        else:
            exception_message = (_("Error retrieving masking group."))
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(
                message=exception_message)
        return element

    def get_common_masking_views(self, array, portgroup_name, ig_name):
        """Get common masking views for a given portgroup and initiator group.

        :param array: the array serial number
        :param portgroup_name: the port group name
        :param ig_name: the initiator group name
        :returns: masking view list
        """
        params = {'port_group_name': portgroup_name,
                  'host_or_host_group_name': ig_name}
        masking_view_list = self.get_masking_view_list(array, params)
        if not masking_view_list:
            LOG.info("No common masking views found for %(pg_name)s "
                     "and %(ig_name)s.",
                     {'pg_name': portgroup_name, 'ig_name': ig_name})
        return masking_view_list

    def create_masking_view(self, array, maskingview_name, storagegroup_name,
                            port_group_name, init_group_name, extra_specs):
        """Create a new masking view.

        :param array: the array serial number
        :param maskingview_name: the masking view name
        :param storagegroup_name: the storage group name
        :param port_group_name: the port group
        :param init_group_name: the initiator group
        :param extra_specs: extra specifications
        """
        payload = ({"executionOption": "ASYNCHRONOUS",
                    "portGroupSelection": {
                        "useExistingPortGroupParam": {
                            "portGroupId": port_group_name}},
                    "maskingViewId": maskingview_name,
                    "hostOrHostGroupSelection": {
                        "useExistingHostParam": {
                            "hostId": init_group_name}},
                    "storageGroupSelection": {
                        "useExistingStorageGroupParam": {
                            "storageGroupId": storagegroup_name}}})

        status_code, job = self.create_resource(
            array, SLOPROVISIONING, 'maskingview', payload)

        self.wait_for_job('Create masking view', status_code, job, extra_specs)

    def delete_masking_view(self, array, maskingview_name):
        """Delete a masking view.

        :param array: the array serial number
        :param maskingview_name: the masking view name
        """
        return self.delete_resource(
            array, SLOPROVISIONING, 'maskingview', maskingview_name)

    def get_replication_capabilities(self, array):
        """Check what replication features are licensed and enabled.

        Example return value for this method:

        .. code:: python

          {"symmetrixId": "000197800128",
           "snapVxCapable": true,
           "rdfCapable": true}

        :param array
        :returns: capabilities dict for the given array
        """
        array_capabilities = None
        target_uri = ("/%s/replication/capabilities/symmetrix"
                      % U4V_VERSION)
        capabilities = self.get_request(
            target_uri, 'replication capabilities')
        if capabilities:
            symm_list = capabilities['symmetrixCapability']
            for symm in symm_list:
                if symm['symmetrixId'] == array:
                    array_capabilities = symm
                    break
        return array_capabilities

    def is_snapvx_licensed(self, array):
        """Check if the snapVx feature is licensed and enabled.

        :param array: the array serial number
        :returns: True if licensed and enabled; False otherwise.
        """
        snap_capability = False
        capabilities = self.get_replication_capabilities(array)
        if capabilities:
            snap_capability = capabilities['snapVxCapable']
        else:
            LOG.error("Cannot access replication capabilities "
                      "for array %(array)s", {'array': array})
        return snap_capability

    def create_volume_snap(self, array, snap_name, device_id,
                           extra_specs, ttl=0):
        """Create a snapVx snapshot of a volume.

        :param array: the array serial number
        :param snap_name: the name of the snapshot
        :param device_id: the source device id
        :param extra_specs: the extra specifications
        :param ttl: time to live in hours, defaults to 0
        """
        payload = {"deviceNameListSource": [{"name": device_id}],
                   "bothSides": 'false', "star": 'false',
                   "force": 'false'}
        if int(ttl) > 0:
            payload['timeToLive'] = ttl
            payload['timeInHours'] = 'true'
        resource_type = 'snapshot/%(snap)s' % {'snap': snap_name}
        status_code, job = self.create_resource(
            array, REPLICATION, resource_type,
            payload, private='/private')
        self.wait_for_job('Create volume snapVx', status_code,
                          job, extra_specs)

    def modify_volume_snap(self, array, source_id, target_id, snap_name,
                           extra_specs, snap_id=None, link=False, unlink=False,
                           rename=False, new_snap_name=None, restore=False,
                           list_volume_pairs=None, copy=False):
        """Modify a snapvx snapshot

        :param array: the array serial number
        :param source_id: the source device id
        :param target_id: the target device id
        :param snap_name: the snapshot name
        :param extra_specs: extra specifications
        :param snap_id: the unique snap id of the snapVX
        :param link: Flag to indicate action = Link
        :param unlink: Flag to indicate action = Unlink
        :param rename: Flag to indicate action = Rename
        :param new_snap_name: Optional new snapshot name
        :param restore: Flag to indicate action = Restore
        :param list_volume_pairs: list of volume pairs to link, optional
        :param copy: If copy mode should be used for SnapVX target links
        """
        action, operation, payload = '', '', {}
        copy = 'true' if copy else 'false'
        force = (
            "true" if utils.FORCE_VOL_EDIT in extra_specs else "false")

        if link:
            action = "Link"
        elif unlink:
            action = "Unlink"
        elif rename:
            action = "Rename"
        elif restore:
            action = "Restore"

        if action == "Restore":
            operation = 'Restore snapVx snapshot'
            payload = {"deviceNameListSource": [{"name": source_id}],
                       "deviceNameListTarget": [{"name": source_id}],
                       "action": action,
                       "star": 'false', "force": 'false'}
        elif action in ('Link', 'Unlink'):
            operation = 'Modify snapVx relationship to target'
            src_list, tgt_list = [], []
            if list_volume_pairs:
                for a, b in list_volume_pairs:
                    src_list.append({'name': a})
                    tgt_list.append({'name': b})
            else:
                src_list.append({'name': source_id})
                tgt_list.append({'name': target_id})
            payload = {"deviceNameListSource": src_list,
                       "deviceNameListTarget": tgt_list,
                       "copy": copy, "action": action,
                       "star": 'false', "force": force,
                       "exact": 'false', "remote": 'false',
                       "symforce": 'false'}
        elif action == "Rename":
            operation = 'Rename snapVx snapshot'
            payload = {"deviceNameListSource": [{"name": source_id}],
                       "deviceNameListTarget": [{"name": source_id}],
                       "action": action, "newsnapshotname": new_snap_name}
        if self.is_snap_id:
            payload.update({"snap_id": snap_id}) if snap_id else (
                payload.update({"generation": "0"}))
        else:
            payload.update({"generation": snap_id}) if snap_id else (
                payload.update({"generation": "0"}))
        if action:
            status_code, job = self.modify_resource(
                array, REPLICATION, 'snapshot', payload,
                resource_name=snap_name, private='/private')
            self.wait_for_job(operation, status_code, job, extra_specs)

    def delete_volume_snap(self, array, snap_name,
                           source_device_ids, snap_id=None, restored=False):
        """Delete the snapshot of a volume or volumes.

        :param array: the array serial number
        :param snap_name: the name of the snapshot
        :param source_device_ids: the source device ids
        :param snap_id: the unique snap id of the snapVX
        :param restored: Flag to indicate terminate restore session
        """
        device_list = []
        if not isinstance(source_device_ids, list):
            source_device_ids = [source_device_ids]
        for dev in source_device_ids:
            device_list.append({"name": dev})
        payload = {"deviceNameListSource": device_list}
        if self.is_snap_id:
            payload.update({"snap_id": snap_id}) if snap_id else (
                payload.update({"generation": 0}))
        else:
            payload.update({"generation": snap_id}) if snap_id else (
                payload.update({"generation": 0}))

        if restored:
            payload.update({"restore": True})
        LOG.debug("The payload is %(payload)s.",
                  {'payload': payload})
        return self.delete_resource(
            array, REPLICATION, 'snapshot', snap_name, payload=payload,
            private='/private')

    def get_volume_snap_info(self, array, source_device_id):
        """Get snapVx information associated with a volume.

        :param array: the array serial number
        :param source_device_id: the source volume device ID
        :returns: message -- dict, or None
        """
        resource_name = ("%(device_id)s/snapshot"
                         % {'device_id': source_device_id})
        return self.get_resource(array, REPLICATION, 'volume',
                                 resource_name, private='/private')

    def get_volume_snap(self, array, device_id, snap_name, snap_id):
        """Given a volume snap info, retrieve the snapVx object.

        :param array: the array serial number
        :param device_id: the source volume device id
        :param snap_name: the name of the snapshot
        :param snap_id: the unique snap id of the snapVX
        :returns: snapshot dict, or None
        """
        snapshot = None
        snap_info = self.get_volume_snap_info(array, device_id)
        if snap_info:
            if (snap_info.get('snapshotSrcs', None) and
                    bool(snap_info['snapshotSrcs'])):
                for snap in snap_info['snapshotSrcs']:
                    if snap['snapshotName'] == snap_name:
                        if self.is_snap_id:
                            if snap['snap_id'] == snap_id:
                                snapshot = snap
                                break
                        else:
                            if snap['generation'] == snap_id:
                                snapshot = snap
                                break
        return snapshot

    def get_volume_snaps(self, array, device_id, snap_name):
        """Given a volume snap info, retrieve the snapVx object.

        :param array: the array serial number
        :param device_id: the source volume device id
        :param snap_name: the name of the snapshot
        :returns: snapshot dict, or None
        """
        snapshots = list()
        snap_info = self.get_volume_snap_info(array, device_id)
        if snap_info:
            if (snap_info.get('snapshotSrcs', None) and
                    bool(snap_info['snapshotSrcs'])):
                for snap in snap_info['snapshotSrcs']:
                    if snap['snapshotName'] == snap_name:
                        snapshots.append(snap)
        return snapshots

    def get_volume_snapshot_list(self, array, source_device_id):
        """Get a list of snapshot details for a particular volume.

        :param array: the array serial number
        :param source_device_id: the osurce device id
        :returns: snapshot list or None
        """
        snapshot_list = []
        snap_info = self.get_volume_snap_info(array, source_device_id)
        if snap_info:
            if (snap_info.get('snapshotSrcs', None) and
                    bool(snap_info['snapshotSrcs'])):
                snapshot_list = snap_info['snapshotSrcs']
        return snapshot_list

    def is_vol_in_rep_session(self, array, device_id):
        """Check if a volume is in a replication session.

        :param array: the array serial number
        :param device_id: the device id
        :returns: snapvx_tgt -- bool, snapvx_src -- bool,
                 rdf_grp -- list or None
        """
        snapvx_src = False
        snapvx_tgt = False
        rdf_grp = None
        volume_details = self.get_volume(array, device_id)
        if volume_details and isinstance(volume_details, dict):
            if volume_details.get('snapvx_target'):
                snapvx_tgt = volume_details['snapvx_target']
            if volume_details.get('snapvx_source'):
                snapvx_src = volume_details['snapvx_source']
            if volume_details.get('rdfGroupId'):
                rdf_grp = volume_details['rdfGroupId']
        return snapvx_tgt, snapvx_src, rdf_grp

    def is_sync_complete(self, array, source_device_id,
                         target_device_id, snap_name, extra_specs, snap_id):
        """Check if a sync session is complete.

        :param array: the array serial number
        :param source_device_id: source device id
        :param target_device_id: target device id
        :param snap_name: snapshot name
        :param extra_specs: extra specifications
        :param snap_id: the unique snap id of the SnapVX
        :returns: bool
        """

        def _wait_for_sync():
            """Called at an interval until the synchronization is finished.

            :raises: loopingcall.LoopingCallDone
            :raises: VolumeBackendAPIException
            """
            retries = kwargs['retries']
            try:
                kwargs['retries'] = retries + 1
                if not kwargs['wait_for_sync_called']:
                    if self._is_sync_complete(
                            array, source_device_id, snap_name,
                            target_device_id, snap_id):
                        kwargs['wait_for_sync_called'] = True
            except Exception:
                exception_message = (_("Issue encountered waiting for "
                                       "synchronization."))
                LOG.error(exception_message)
                raise exception.VolumeBackendAPIException(
                    message=exception_message)

            if kwargs['retries'] > int(extra_specs[utils.RETRIES]):
                LOG.error("_wait_for_sync failed after %(retries)d "
                          "tries.", {'retries': retries})
                raise loopingcall.LoopingCallDone(
                    retvalue=int(extra_specs[utils.RETRIES]))
            if kwargs['wait_for_sync_called']:
                raise loopingcall.LoopingCallDone()

        kwargs = {'retries': 0,
                  'wait_for_sync_called': False}
        timer = loopingcall.FixedIntervalLoopingCall(_wait_for_sync)
        rc = timer.start(interval=int(extra_specs[utils.INTERVAL])).wait()
        return rc

    def _is_sync_complete(self, array, source_device_id, snap_name,
                          target_device_id, snap_id):
        """Helper function to check if snapVx sync session is complete.

        :param array: the array serial number
        :param source_device_id: source device id
        :param snap_name: the snapshot name
        :param target_device_id: the target device id
        :param snap_id: the unique snap id of the SnapVX
        :returns: defined -- bool
        """
        defined = True
        session = self.get_sync_session(
            array, source_device_id, snap_name, target_device_id, snap_id)
        if session:
            defined = session['defined']
        return defined

    def get_sync_session(self, array, source_device_id, snap_name,
                         target_device_id, snap_id):
        """Get a particular sync session.

        :param array: the array serial number
        :param source_device_id: source device id
        :param snap_name: the snapshot name
        :param target_device_id: the target device id
        :param snap_id: the unique snapid of the snapshot
        :returns: sync session -- dict, or None
        """
        session = None
        linked_device_list = self.get_snap_linked_device_list(
            array, source_device_id, snap_name, snap_id)
        for target in linked_device_list:
            if target_device_id == target['targetDevice']:
                session = target
                break
        return session

    def _find_snap_vx_source_sessions(self, array, source_device_id):
        """Find all snap sessions for a given source volume.

        :param array: the array serial number
        :param source_device_id: the source device id
        :returns: list of snapshot dicts
        """
        snap_dict_list = []
        snapshots = self.get_volume_snapshot_list(array, source_device_id)
        for snapshot in snapshots:
            try:
                snap_id = snapshot['snap_id'] if self.is_snap_id else (
                    snapshot['generation'])
                if bool(snapshot['linkedDevices']):
                    link_info = {'linked_vols': snapshot['linkedDevices'],
                                 'snap_name': snapshot['snapshotName'],
                                 'snapid': snap_id}
                    snap_dict_list.append(link_info)
            except KeyError:
                pass
        return snap_dict_list

    def get_snap_linked_device_list(self, array, source_device_id,
                                    snap_name, snap_id, state=None):
        """Get the list of linked devices for a particular snapVx snapshot.

        :param array: the array serial number
        :param source_device_id: source device id
        :param snap_name: the snapshot name
        :param snap_id: the unique snapid of the snapshot
        :param state: filter for state of the link
        :returns: linked_device_list or empty list
        """
        snap_dict_list = None
        linked_device_list = []
        snap_dict_list = self._get_snap_linked_device_dict_list(
            array, source_device_id, snap_name, state=state)
        for snap_dict in snap_dict_list:
            if snap_id == snap_dict['snapid']:
                linked_device_list = snap_dict['linked_vols']
                break
        return linked_device_list

    def _get_snap_linked_device_dict_list(
            self, array, source_device_id, snap_name, state=None):
        """Get list of linked devices for all snap ids for a snapVx snapshot

        :param array: the array serial number
        :param source_device_id: source device id
        :param snap_name: the snapshot name
        :param state: filter for state of the link
        :returns: list of dict of snapids with linked devices
        """
        snap_dict_list = []
        snap_list = self._find_snap_vx_source_sessions(
            array, source_device_id)
        for snap in snap_list:
            if snap['snap_name'] == snap_name:
                for linked_vol in snap['linked_vols']:
                    snap_state = linked_vol.get('state', None)
                    # If state is None or
                    # both snap_state and state are not None and are equal
                    if not state or (snap_state and state
                                     and snap_state == state):
                        snap_id = snap['snapid']
                        found = False
                        for snap_dict in snap_dict_list:
                            if snap_id == snap_dict['snapid']:
                                snap_dict['linked_vols'].append(
                                    linked_vol)
                                found = True
                                break
                        if not found:
                            snap_dict_list.append(
                                {'snapid': snap_id,
                                 'linked_vols': [linked_vol]})
        return snap_dict_list

    def find_snap_vx_sessions(self, array, device_id, tgt_only=False):
        """Find all snapVX sessions for a device (source and target).

        :param array: the array serial number
        :param device_id: the device id
        :param tgt_only: Flag - return only sessions where device is target
        :returns: list of snapshot dicts
        """
        snap_tgt_dict, snap_src_dict_list = dict(), list()
        s_in = self.get_volume_snap_info(array, device_id)
        snap_src = (
            s_in['snapshotSrcs'] if s_in and s_in.get(
                'snapshotSrcs') else list())
        snap_tgt = (
            s_in['snapshotLnks'][0] if s_in and s_in.get(
                'snapshotLnks') else dict())
        if snap_src and not tgt_only:
            for session in snap_src:
                snap_src_dict = dict()

                snap_src_dict['source_vol_id'] = device_id
                snap_src_dict['snapid'] = session.get(
                    'snap_id') if self.is_snap_id else session.get(
                    'generation')
                snap_src_dict['snap_name'] = session.get('snapshotName')
                snap_src_dict['expired'] = session.get('expired')

                if session.get('linkedDevices'):
                    snap_src_link = session.get('linkedDevices')[0]
                    snap_src_dict['target_vol_id'] = snap_src_link.get(
                        'targetDevice')
                    snap_src_dict['copy_mode'] = snap_src_link.get('copy')
                    snap_src_dict['state'] = snap_src_link.get('state')

                snap_src_dict_list.append(snap_src_dict)

        if snap_tgt:
            snap_tgt_dict['source_vol_id'] = snap_tgt.get('linkSourceName')
            snap_tgt_dict['target_vol_id'] = device_id
            snap_tgt_dict['state'] = snap_tgt.get('state')
            snap_tgt_dict['copy_mode'] = snap_tgt.get('copy')

            vol_info = self._get_private_volume(array, device_id)
            if vol_info.get('timeFinderInfo'):
                vol_tf_sessions = vol_info.get(
                    'timeFinderInfo').get('snapVXSession')
                if vol_tf_sessions:
                    for session in vol_tf_sessions:
                        if session.get('tgtSrcSnapshotGenInfo'):
                            snap_tgt_link = session.get(
                                'tgtSrcSnapshotGenInfo')
                            snap_tgt_dict['snap_name'] = snap_tgt_link.get(
                                'snapshotName')
                            snap_tgt_dict['expired'] = snap_tgt_link.get(
                                'expired')
                            snap_tgt_dict['snapid'] = snap_tgt_link.get(
                                'snapid') if self.is_snap_id else (
                                snap_tgt_link.get('generation'))

        return snap_src_dict_list, snap_tgt_dict

    def get_rdf_group(self, array, rdf_number):
        """Get specific rdf group details.

        :param array: the array serial number
        :param rdf_number: the rdf number
        """
        return self.get_resource(array, REPLICATION, 'rdf_group',
                                 rdf_number)

    def get_storage_group_rdf_group_state(self, array, storage_group,
                                          rdf_group_no):
        """Get the RDF group state from a replication enabled Storage Group.

        :param array: the array serial number
        :param storage_group: the storage group name
        :param rdf_group_no: the RDF group number
        :returns: storage group RDF group state
        """
        resource = ('storagegroup/%(sg)s/rdf_group/%(rdfg)s' % {
            'sg': storage_group, 'rdfg': rdf_group_no})

        rdf_group = self.get_resource(array, REPLICATION, resource)

        return rdf_group.get('states', list()) if rdf_group else dict()

    def get_storage_group_rdf_groups(self, array, storage_group):
        """Get a list of rdf group numbers used by a storage group.

        :param array: the array serial number -- str
        :param storage_group: the storage group name to check -- str
        :return: RDFGs associated with the storage group -- dict
        """
        resource = ('storagegroup/%(storage_group)s/rdf_group' % {
            'storage_group': storage_group})
        storage_group_details = self.get_resource(array, REPLICATION, resource)
        return storage_group_details['rdfgs']

    def get_rdf_group_list(self, array):
        """Get rdf group list from array.

        :param array: the array serial number
        """
        return self.get_resource(array, REPLICATION, 'rdf_group')

    def get_rdf_group_volume_list(self, array, rdf_group_no):
        """Get a list of all volumes in an RDFG.

        :param array: the array serial number -- str
        :param rdf_group_no: the RDF group number -- str
        :return: RDFG volume list -- list
        """
        resource = ('rdf_group/%(rdf_group)s/volume' % {
            'rdf_group': rdf_group_no})
        rdf_group_volumes = self.get_resource(array, REPLICATION, resource)
        return rdf_group_volumes['name']

    def get_rdf_group_volume(self, array, src_device_id):
        """Get the RDF details for a volume.

        :param array: the array serial number
        :param src_device_id: the source device id
        :returns: rdf_session
        """
        rdf_session = None
        volume = self._get_private_volume(array, src_device_id)
        try:
            rdf_session = volume['rdfInfo']['RDFSession'][0]
        except (KeyError, TypeError, IndexError):
            LOG.warning("Cannot locate source RDF volume %s", src_device_id)
        return rdf_session

    def get_rdf_pair_volume(self, array, rdf_group_no, device_id):
        """Get information on an RDF pair from the source volume.

        :param array: the array serial number
        :param rdf_group_no: the RDF group number
        :param device_id: the source device ID
        :returns: RDF pair information -- dict
        """
        resource = ('rdf_group/%(rdf_group)s/volume/%(device)s' % {
            'rdf_group': rdf_group_no, 'device': device_id})

        return self.get_resource(array, REPLICATION, resource)

    def are_vols_rdf_paired(self, array, remote_array,
                            device_id, target_device):
        """Check if a pair of volumes are RDF paired.

        :param array: the array serial number
        :param remote_array: the remote array serial number
        :param device_id: the device id
        :param target_device: the target device id
        :returns: paired -- bool, local_vol_state, rdf_pair_state
        """
        paired, local_vol_state, rdf_pair_state = False, '', ''
        rdf_session = self.get_rdf_group_volume(array, device_id)
        if rdf_session:
            remote_volume = rdf_session['remoteDeviceID']
            remote_symm = rdf_session['remoteSymmetrixID']
            if (remote_volume == target_device
                    and remote_array == remote_symm):
                paired = True
                local_vol_state = rdf_session['SRDFStatus']
                rdf_pair_state = rdf_session['pairState']
        else:
            LOG.warning("Cannot locate RDF session for volume %s", device_id)
        return paired, local_vol_state, rdf_pair_state

    def wait_for_rdf_group_sync(self, array, storage_group, rdf_group_no,
                                rep_extra_specs):
        """Wait for an RDF group to reach 'Synchronised' state.

        :param array: the array serial number
        :param storage_group: the storage group name
        :param rdf_group_no: the RDF group number
        :param rep_extra_specs: replication extra specifications
        :raises: exception.VolumeBackendAPIException
        """
        def _wait_for_synced_state():
            try:
                kwargs['retries'] -= 1
                if not kwargs['synced']:
                    rdf_group_state = self.get_storage_group_rdf_group_state(
                        array, storage_group, rdf_group_no)
                    if rdf_group_state:
                        kwargs['state'] = rdf_group_state[0]
                        if kwargs['state'].lower() in utils.RDF_SYNCED_STATES:
                            kwargs['synced'] = True
                            kwargs['rc'] = 0
            except Exception as e_msg:
                ex_msg = _("Issue encountered waiting for job: %(e)s" % {
                    'e': e_msg})
                LOG.error(ex_msg)
                raise exception.VolumeBackendAPIException(message=ex_msg)
            if kwargs['retries'] == 0:
                ex_msg = _("Wait for RDF Sync State failed after %(r)d "
                           "tries." % {'r': rep_extra_specs['sync_retries']})
                LOG.error(ex_msg)
                raise exception.VolumeBackendAPIException(message=ex_msg)

            if kwargs['synced']:
                raise loopingcall.LoopingCallDone()

        kwargs = {'retries': rep_extra_specs['sync_retries'],
                  'synced': False, 'rc': 0, 'state': 'syncinprog'}

        timer = loopingcall.FixedIntervalLoopingCall(_wait_for_synced_state)
        timer.start(interval=rep_extra_specs['sync_interval']).wait()
        LOG.debug("Return code is: %(rc)lu. State is %(state)s",
                  {'rc': kwargs['rc'], 'state': kwargs['state']})

    def wait_for_rdf_pair_sync(self, array, rdf_group_no, device_id,
                               rep_extra_specs):
        """Wait for an RDF device pair to reach 'Synchronised' state.

        :param array: the array serial number
        :param rdf_group_no: the RDF group number
        :param device_id: the source device ID
        :param rep_extra_specs: replication extra specifications
        :raises: exception.VolumeBackendAPIException
        """
        def _wait_for_synced_state():
            try:
                kwargs['retries'] -= 1
                if not kwargs['synced']:
                    rdf_pair = self.get_rdf_pair_volume(array, rdf_group_no,
                                                        device_id)
                    kwargs['state'] = rdf_pair['rdfpairState']

                    if kwargs['state'].lower() in utils.RDF_SYNCED_STATES:
                        kwargs['synced'] = True
                        kwargs['rc'] = 0

            except Exception as e_msg:
                ex_msg = _("Issue encountered waiting for job: %(e)s" % {
                    'e': e_msg})
                LOG.error(ex_msg)
                raise exception.VolumeBackendAPIException(message=ex_msg)

            if kwargs['retries'] == 0:
                ex_msg = _("Wait for RDF Sync State failed after %(r)d "
                           "tries." % {'r': rep_extra_specs['sync_retries']})
                LOG.error(ex_msg)
                raise exception.VolumeBackendAPIException(message=ex_msg)

            if kwargs['synced']:
                raise loopingcall.LoopingCallDone()

        kwargs = {'retries': rep_extra_specs['sync_retries'],
                  'synced': False, 'rc': 0, 'state': 'syncinprog'}

        timer = loopingcall.FixedIntervalLoopingCall(_wait_for_synced_state)
        timer.start(interval=rep_extra_specs['sync_interval']).wait()
        LOG.debug("Return code is: %(rc)lu. State is %(state)s",
                  {'rc': kwargs['rc'], 'state': kwargs['state']})

    def rdf_resume_with_retries(self, array, rep_extra_specs):
        """Resume RDF on a RDF group with retry operator included.

        The retry operator is required here because on occassion when we are
        waiting on a snap copy session to complete we have no way of
        determining if the copy is complete, operation is retried until
        either the copy completes or the max interval/retries has been met.

        :param array: the array serial number
        :param rep_extra_specs: replication extra specifications
        :raises: exception.VolumeBackendAPIException
        """

        def wait_for_copy_complete():
            kwargs['retries'] -= 1
            if not kwargs['copied']:
                try:
                    self.srdf_resume_replication(
                        array, rep_extra_specs['sg_name'],
                        rep_extra_specs['rdf_group_no'], rep_extra_specs,
                        async_call=False)
                    kwargs['copied'] = True
                    kwargs['state'] = 'copy_complete'
                    kwargs['rc'] = 0
                    raise loopingcall.LoopingCallDone()

                except exception.VolumeBackendAPIException:
                    LOG.debug('Snapshot copy process still ongoing, Cinder '
                              'will retry again in %(interval)s seconds. '
                              'There are %(retries)s remaining.', {
                                  'interval': rep_extra_specs['sync_interval'],
                                  'retries': kwargs['retries']})

            if kwargs['retries'] == 0:
                ex_msg = _("Wait for snapshot copy complete failed after "
                           "%(r)d tries." % {
                               'r': rep_extra_specs['sync_retries']})
                LOG.error(ex_msg)
                raise exception.VolumeBackendAPIException(message=ex_msg)

        kwargs = {'retries': rep_extra_specs['sync_retries'],
                  'copied': False, 'rc': 0, 'state': 'copy_in_progress'}

        timer = loopingcall.FixedIntervalLoopingCall(wait_for_copy_complete)
        timer.start(interval=rep_extra_specs['sync_interval']).wait()
        LOG.debug("Return code: %(rc)lu. State: %(state)s",
                  {'rc': kwargs['rc'], 'state': kwargs['state']})

    def get_rdf_group_number(self, array, rdf_group_label):
        """Given an rdf_group_label, return the associated group number.

        :param array: the array serial number
        :param rdf_group_label: the group label
        :returns: rdf_group_number
        """
        number = None
        rdf_list = self.get_rdf_group_list(array)
        if rdf_list and rdf_list.get('rdfGroupID'):
            number_list = [rdf['rdfgNumber'] for rdf in rdf_list['rdfGroupID']
                           if rdf['label'] == rdf_group_label]
            number = number_list[0] if len(number_list) > 0 else None
        if number:
            rdf_group = self.get_rdf_group(array, number)
            if not rdf_group:
                number = None
        return number

    def _get_async_payload_info(self, array, rdf_group_no):
        """Get the payload details for an async create pair.

        :param array: the array serial number
        :param rdf_group_no: the rdf group number
        :returns: payload_update
        """
        num_vols, payload_update = 0, {}
        rdfg_details = self.get_rdf_group(array, rdf_group_no)
        if rdfg_details is not None and rdfg_details.get('numDevices'):
            num_vols = int(rdfg_details['numDevices'])
        if num_vols > 0:
            payload_update = {'exempt': 'true'}
        return payload_update

    def get_metro_payload_info(self, array, payload,
                               rdf_group_no, extra_specs, next_gen):
        """Get the payload details for a metro active create pair.

        :param array: the array serial number
        :param payload: the payload
        :param rdf_group_no: the rdf group number
        :param extra_specs: the replication configuration
        :param next_gen: if the array is next gen uCode
        :returns: updated payload
        """
        num_vols = 0
        payload["rdfMode"] = "Active"
        payload['rdfType'] = "RDF1"

        rdfg_details = self.get_rdf_group(array, rdf_group_no)
        if rdfg_details is not None and rdfg_details.get('numDevices'):
            num_vols = int(rdfg_details['numDevices'])

        if num_vols == 0:
            # First volume - set bias if required
            if extra_specs.get(utils.METROBIAS):
                payload.update({"metroBias": "true"})
        else:
            if next_gen:
                payload["exempt"] = "true"
            if payload.get('establish'):
                payload.pop('establish')
        return payload

    def srdf_protect_storage_group(
            self, array_id, remote_array_id, rdf_group_no, replication_mode,
            sg_name, service_level, extra_specs, target_sg=None):
        """SRDF protect a storage group.

        :param array_id: local array serial number
        :param remote_array_id: remote array serial number
        :param rdf_group_no: RDF group number
        :param replication_mode: replication mode
        :param sg_name: storage group name
        :param service_level: service level
        :param extra_specs: extra specifications
        :param target_sg: target storage group -- optional
        """
        remote_sg = target_sg if target_sg else sg_name

        payload = {
            "executionOption": "ASYNCHRONOUS",
            "replicationMode": replication_mode, "remoteSLO": service_level,
            "remoteSymmId": remote_array_id, "rdfgNumber": rdf_group_no,
            "remoteStorageGroupName": remote_sg, "establish": "true"}

        # Metro specific configuration
        if replication_mode == utils.REP_METRO:
            bias = "true" if extra_specs.get(utils.METROBIAS) else "false"
            payload.update({
                "replicationMode": "Active", "metroBias": bias})

        LOG.debug('SRDF Protect Payload: %(pay)s', {'pay': payload})
        resource = 'storagegroup/%(sg_name)s/rdf_group' % {'sg_name': sg_name}
        status_code, job = self.create_resource(array_id, REPLICATION,
                                                resource, payload)
        self.wait_for_job('SRDF Protect Storage Group', status_code,
                          job, extra_specs)

    def srdf_modify_group(self, array, rdf_group_no, storage_group, payload,
                          extra_specs, msg, async_call=True):
        """Modify RDF enabled storage group replication options.

        :param array: array serial number
        :param rdf_group_no: RDF group number
        :param storage_group: storage group name
        :param payload: REST request payload dict
        :param extra_specs: extra specifications
        :param msg: message to use for logs when waiting on job to complete
        :param async_call: if the REST call should be run, this only comes into
                           effect when trying to resume replication and
                           interval/retries are a factor.
        """
        resource = ('storagegroup/%(sg_name)s/rdf_group/%(rdf_group_no)s' % {
            'sg_name': storage_group, 'rdf_group_no': rdf_group_no})

        if async_call:
            payload.update({"executionOption": "ASYNCHRONOUS"})
            status_code, job = self.modify_resource(array, REPLICATION,
                                                    resource, payload)
            self.wait_for_job(msg, status_code, job, extra_specs)
        else:
            self.modify_resource(array, REPLICATION, resource, payload)

    def srdf_suspend_replication(self, array_id, storage_group, rdf_group_no,
                                 rep_extra_specs):
        """Suspend replication on a RDF group.

        :param array_id: array serial number
        :param storage_group: storage group name
        :param rdf_group_no: RDF group number
        :param rep_extra_specs: replication extra specifications
        """
        group_state = self.get_storage_group_rdf_group_state(
            array_id, storage_group, rdf_group_no)

        if group_state:
            group_state = [x.lower() for x in group_state]

        if len(group_state) == 1 and utils.RDF_SUSPENDED_STATE in group_state:
            LOG.info('SRDF Group %(grp_num)s is already in a suspended state',
                     {'grp_num': rdf_group_no})
        else:
            self.srdf_modify_group(
                array_id, rdf_group_no, storage_group,
                {"suspend": {"force": "true"}, "action": "Suspend"},
                rep_extra_specs, 'Suspend SRDF Group Replication')

    def srdf_resume_replication(self, array_id, storage_group, rdf_group_no,
                                rep_extra_specs, async_call=True):
        """Resume replication on a RDF group.

        :param array_id: array serial number
        :param storage_group: storage group name
        :param rdf_group_no: RDF group number
        :param rep_extra_specs: replication extra specifications
        :param async_call: if the REST call should be run, this only comes into
                           effect when trying to resume replication and
                           interval/retries are a factor.
        """
        if self.get_storage_group(array_id, storage_group):
            group_state = self.get_storage_group_rdf_group_state(
                array_id, storage_group, rdf_group_no)
            if group_state:
                group_state = [x.lower() for x in group_state]
            if utils.RDF_SUSPENDED_STATE in group_state:
                payload = {"action": "Resume"}
                if rep_extra_specs['rep_mode'] == utils.REP_METRO:
                    payload = {"action": "Establish"}
                    if rep_extra_specs.get(utils.METROBIAS):
                        payload.update({"establish": {"metroBias": "true"}})

                self.srdf_modify_group(
                    array_id, rdf_group_no, storage_group, payload,
                    rep_extra_specs, 'Resume SRDF Group Replication',
                    async_call)
            else:
                LOG.debug('SRDF Group %(grp_num)s is already in a resumed '
                          'state.', {'grp_num': rdf_group_no})
        else:
            LOG.debug('Storage Group %(sg)s not present on array '
                      '%(array)s, no resume required.', {
                          'sg': storage_group, 'array': array_id})

    def srdf_establish_replication(self, array_id, storage_group, rdf_group_no,
                                   rep_extra_specs):
        """Establish replication on a RDF group.

        :param array_id: array serial number
        :param storage_group: storage group name
        :param rdf_group_no: RDF group number
        :param rep_extra_specs: replication extra specifications
        """
        group_state = self.get_storage_group_rdf_group_state(
            array_id, storage_group, rdf_group_no)

        if utils.RDF_SUSPENDED_STATE not in group_state:
            LOG.info('Suspending SRDF Group %(grp_num)s', {
                'grp_num': rdf_group_no})
            self.srdf_modify_group(
                array_id, rdf_group_no, storage_group, {"action": "Suspend"},
                rep_extra_specs, 'Suspend SRDF Group Replication')

        wait_msg = 'Incremental Establish SRDF Group Replication'
        LOG.info('Initiating incremental establish on SRDF Group %(grp_num)s',
                 {'grp_num': rdf_group_no})
        self.srdf_modify_group(
            array_id, rdf_group_no, storage_group, {"action": "Establish"},
            rep_extra_specs, wait_msg)

    def srdf_failover_group(self, array_id, storage_group, rdf_group_no,
                            rep_extra_specs):
        """Failover a RDFG/SG volume group to replication target.

        :param array_id: array serial number
        :param storage_group: storage group name
        :param rdf_group_no: RDF group number
        :param rep_extra_specs: replication extra specifications
        """
        self.srdf_modify_group(
            array_id, rdf_group_no, storage_group, {"action": "Failover"},
            rep_extra_specs, 'Failing over SRDF group replication')

    def srdf_failback_group(self, array_id, storage_group, rdf_group_no,
                            rep_extra_specs):
        """Failback a RDFG/SG volume group from replication target.

        :param array_id:
        :param storage_group:
        :param rdf_group_no:
        :param rep_extra_specs:
        """
        self.srdf_modify_group(
            array_id, rdf_group_no, storage_group, {"action": "Failback"},
            rep_extra_specs, 'Failing back SRDF group replication')

    def srdf_remove_device_pair_from_storage_group(
            self, array_id, storage_group, remote_array_id, device_id,
            rep_extra_specs):
        """Remove a volume from local and remote storage groups simultaneously.

        :param array_id: local array serial number
        :param storage_group: storage group name
        :param remote_array_id: remote array serial number
        :param device_id: source device id
        :param rep_extra_specs: replication extra specifications
        """
        payload = {
            "editStorageGroupActionParam": {
                "removeVolumeParam": {
                    "volumeId": [device_id],
                    "remoteSymmSGInfoParam": {
                        "remote_symmetrix_1_id": remote_array_id,
                        "remote_symmetrix_1_sgs": [storage_group]}}}}

        status_code, job = self.modify_storage_group(array_id, storage_group,
                                                     payload)
        self.wait_for_job('SRDF Group remove device pair', status_code,
                          job, rep_extra_specs)

    def srdf_delete_device_pair(self, array, rdf_group_no, local_device_id):
        """Delete a RDF device pair.

        :param array: array serial number
        :param rdf_group_no: RDF group number
        :param local_device_id: local device id
        """
        resource = ('%(rdfg)s/volume/%(dev)s' % {
            'rdfg': rdf_group_no, 'dev': local_device_id})

        self.delete_resource(array, REPLICATION, 'rdf_group', resource)
        LOG.debug("Device Pair successfully deleted.")

    def srdf_create_device_pair(self, array, rdf_group_no, mode, device_id,
                                rep_extra_specs, next_gen):
        """Create a RDF device pair in an existing RDF group.

        :param array: array serial number
        :param rdf_group_no: RDF group number
        :param mode: replication mode
        :param device_id: local device ID
        :param rep_extra_specs: replication extra specifications
        :param next_gen: if the array is next gen uCode
        :returns: replication session info -- dict
        """
        payload = {
            "executionOption": "ASYNCHRONOUS", "rdfMode": mode,
            "localDeviceListCriteriaParam": {"localDeviceList": [device_id]},
            "rdfType": "RDF1"}

        if mode == utils.REP_SYNC:
            payload.update({"establish": "true"})
        elif mode == utils.REP_ASYNC:
            payload.update({"invalidateR2": "true", "exempt": "true"})
        elif mode.lower() in [utils.REP_METRO.lower(),
                              utils.RDF_ACTIVE.lower()]:
            payload = self.get_metro_payload_info(
                array, payload, rdf_group_no, rep_extra_specs, next_gen)

        LOG.debug('Create Pair Payload: %(pay)s', {'pay': payload})
        resource = 'rdf_group/%(rdfg)s/volume' % {'rdfg': rdf_group_no}
        status_code, job = self.create_resource(
            array, REPLICATION, resource, payload)
        self.wait_for_job('SRDF Group remove device pair', status_code,
                          job, rep_extra_specs)

        session_info = self.get_rdf_pair_volume(array, rdf_group_no, device_id)
        r2_device_id = session_info['remoteVolumeName']

        return {'array': session_info['localSymmetrixId'],
                'remote_array': session_info['remoteSymmetrixId'],
                'src_device': device_id, 'tgt_device': r2_device_id,
                'session_info': session_info}

    def get_storage_group_rep(self, array, storage_group_name):
        """Given a name, return storage group details wrt replication.

        :param array: the array serial number
        :param storage_group_name: the name of the storage group
        :returns: storage group dict or None
        """
        return self.get_resource(
            array, REPLICATION, 'storagegroup',
            resource_name=storage_group_name)

    def get_volumes_in_storage_group(self, array, storagegroup_name):
        """Given a volume identifier, find the corresponding device_id.

        :param array: the array serial number
        :param storagegroup_name: the storage group name
        :returns: volume_list
        """
        params = {"storageGroupId": storagegroup_name}

        volume_list = self.get_volume_list(array, params)
        if not volume_list:
            LOG.debug("Cannot find record for storage group %(storageGrpId)s",
                      {'storageGrpId': storagegroup_name})
        return volume_list

    def create_storagegroup_snap(self, array, source_group,
                                 snap_name, extra_specs):
        """Create a snapVx snapshot of a storage group.

        :param array: the array serial number
        :param source_group: the source group name
        :param snap_name: the name of the snapshot
        :param extra_specs: the extra specifications
        """
        payload = {"snapshotName": snap_name}
        resource_type = ('storagegroup/%(sg_name)s/snapshot'
                         % {'sg_name': source_group})
        status_code, job = self.create_resource(
            array, REPLICATION, resource_type, payload)
        self.wait_for_job('Create storage group snapVx', status_code,
                          job, extra_specs)

    def delete_storagegroup_snap(self, array, source_group,
                                 snap_name, snap_id):
        """Delete a snapVx snapshot of a storage group.

        :param array: the array serial number
        :param source_group: the source group name
        :param snap_name: the name of the snapshot
        :param snap_id: the unique snap id of the SnapVX
        """
        postfix_uri = "/snapid/%s" % snap_id if self.is_snap_id else (
            "/generation/%s" % snap_id)

        resource_name = ("%(sg_name)s/snapshot/%(snap_name)s"
                         "%(postfix_uri)s"
                         % {'sg_name': source_group, 'snap_name': snap_name,
                            'postfix_uri': postfix_uri})

        self.delete_resource(
            array, REPLICATION, 'storagegroup', resource_name=resource_name)

    def get_storage_group_snap_id_list(
            self, array, source_group, snap_name):
        """Get a snapshot and its snapid count information for an sg.

        :param array: name of the array -- str
        :param source_group: name of the storage group -- str
        :param snap_name: the name of the snapshot -- str
        :returns: snapids -- list
        """
        postfix_uri = "snapid" if self.is_snap_id else "generation"
        resource_name = ("%(sg_name)s/snapshot/%(snap_name)s/%(postfix_uri)s"
                         % {'sg_name': source_group, 'snap_name': snap_name,
                            'postfix_uri': postfix_uri})
        response = self.get_resource(array, REPLICATION, 'storagegroup',
                                     resource_name=resource_name)
        if self.is_snap_id:
            return response.get('snapids', list()) if response else list()
        else:
            return response.get('generations', list()) if response else list()

    def get_storagegroup_rdf_details(self, array, storagegroup_name,
                                     rdf_group_num):
        """Get the remote replication details of a storage group.

        :param array: the array serial number
        :param storagegroup_name: the storage group name
        :param rdf_group_num: the rdf group number
        """
        resource_name = ("%(sg_name)s/rdf_group/%(rdf_num)s"
                         % {'sg_name': storagegroup_name,
                            'rdf_num': rdf_group_num})
        return self.get_resource(array, REPLICATION, 'storagegroup',
                                 resource_name=resource_name)

    def replicate_group(self, array, storagegroup_name,
                        rdf_group_num, remote_array, extra_specs):
        """Create a target group on the remote array and enable replication.

        :param array: the array serial number
        :param storagegroup_name: the name of the group
        :param rdf_group_num: the rdf group number
        :param remote_array: the remote array serial number
        :param extra_specs: the extra specifications
        """
        resource_name = ("storagegroup/%(sg_name)s/rdf_group"
                         % {'sg_name': storagegroup_name})
        payload = {"executionOption": "ASYNCHRONOUS",
                   "replicationMode": utils.REP_SYNC,
                   "remoteSymmId": remote_array,
                   "remoteStorageGroupName": storagegroup_name,
                   "rdfgNumber": rdf_group_num, "establish": 'true'}
        status_code, job = self.create_resource(
            array, REPLICATION, resource_name, payload)
        self.wait_for_job('Create storage group rdf', status_code,
                          job, extra_specs)

    def _verify_rdf_state(self, array, storagegroup_name,
                          rdf_group_num, action):
        """Verify if a storage group requires the requested state change.

        :param array: the array serial number
        :param storagegroup_name: the storage group name
        :param rdf_group_num: the rdf group number
        :param action: the requested action
        :returns: bool
        """
        mod_rqd = False
        sg_rdf_details = self.get_storagegroup_rdf_details(
            array, storagegroup_name, rdf_group_num)
        if sg_rdf_details:
            state_list = sg_rdf_details['states']
            LOG.debug("RDF state: %(sl)s; Action required: %(action)s",
                      {'sl': state_list, 'action': action})
            for state in state_list:
                if (action.lower() in ["establish", "failback", "resume"] and
                        state.lower() in [utils.RDF_SUSPENDED_STATE,
                                          utils.RDF_FAILEDOVER_STATE]):
                    mod_rqd = True
                    break
                elif (action.lower() in ["split", "failover", "suspend"] and
                      state.lower() in [utils.RDF_SYNC_STATE,
                                        utils.RDF_SYNCINPROG_STATE,
                                        utils.RDF_CONSISTENT_STATE,
                                        utils.RDF_ACTIVE,
                                        utils.RDF_ACTIVEACTIVE,
                                        utils.RDF_ACTIVEBIAS]):
                    mod_rqd = True
                    break
        return mod_rqd

    def delete_storagegroup_rdf(self, array, storagegroup_name,
                                rdf_group_num):
        """Delete the rdf pairs for a storage group.

        :param array: the array serial number
        :param storagegroup_name: the name of the storage group
        :param rdf_group_num: the number of the rdf group
        """
        resource_name = ('%(sg_name)s/rdf_group/%(rdf_num)s'
                         % {'sg_name': storagegroup_name,
                            'rdf_num': rdf_group_num})
        query_params = {'force': 'true'}
        self.delete_resource(
            array, REPLICATION, 'storagegroup', resource_name=resource_name,
            params=query_params)

    def list_pagination(self, list_info):
        """Process lists under or over the maxPageSize

        :param list_info: the object list information
        :returns: the result list
        """
        result_list = []
        try:
            result_list = list_info['resultList']['result']
            iterator_id = list_info['id']
            list_count = list_info['count']
            max_page_size = list_info['maxPageSize']
            start_position = list_info['resultList']['from']
            end_position = list_info['resultList']['to']
        except (KeyError, TypeError):
            return list_info
        if list_count > max_page_size:
            LOG.info("More entries exist in the result list, retrieving "
                     "remainder of results from iterator.")

            start_position = end_position + 1
            if list_count < (end_position + max_page_size):
                end_position = list_count
            else:
                end_position += max_page_size
            iterator_response = self.get_iterator_page_list(
                iterator_id, list_count, start_position, end_position,
                max_page_size)

            result_list += iterator_response
        return result_list

    def get_iterator_page_list(self, iterator_id, result_count, start_position,
                               end_position, max_page_size):
        """Iterate through response if more than one page available.

        :param iterator_id: the iterator ID
        :param result_count: the amount of results in the iterator
        :param start_position: position to begin iterator from
        :param end_position: position to stop iterator
        :param max_page_size: the max page size
        :returns: list -- merged results from multiple pages
        """
        LOG.debug('Iterator %(it)s contains %(cnt)s results.', {
            'it': iterator_id, 'cnt': result_count})

        iterator_result = []
        has_more_entries = True

        while has_more_entries:
            if start_position <= result_count <= end_position:
                end_position = result_count
                has_more_entries = False

            params = {'to': end_position, 'from': start_position}
            LOG.debug('Retrieving iterator %(it)s page %(st)s to %(fn)s', {
                'it': iterator_id, 'st': start_position, 'fn': end_position})

            target_uri = ('/common/Iterator/%(iterator_id)s/page' % {
                'iterator_id': iterator_id})
            iterator_response = self.get_request(target_uri, 'iterator',
                                                 params)
            try:
                iterator_result += iterator_response['result']
                start_position += max_page_size
                end_position += max_page_size
            except (KeyError, TypeError):
                pass

        LOG.info('All results extracted, deleting iterator %(it)s', {
            'it': iterator_id})
        self._delete_iterator(iterator_id)

        return iterator_result

    def _delete_iterator(self, iterator_id):
        """Delete an iterator containing full request result list.

        Note: This should only be called once all required results have been
        extracted from the iterator.

        :param iterator_id: the iterator ID -- str
        """
        target_uri = self.build_uri(
            category='common', resource_level='Iterator',
            resource_level_id=iterator_id, no_version=True)
        status_code, message = self.request(target_uri, DELETE)
        operation = 'delete iterator'
        self.check_status_code_success(operation, status_code, message)
        LOG.info('Successfully deleted iterator %(it)s', {'it': iterator_id})

    def validate_unisphere_version(self):
        """Validate that the running Unisphere version meets min requirement

        :returns: unisphere_meets_min_req -- boolean
        """
        running_version, major_version = self.get_uni_version()
        minimum_version = MIN_U4P_VERSION
        unisphere_meets_min_req = False

        if running_version and (running_version[0].isalpha()):
            # remove leading letter
            if running_version.lower()[0] == 'v':
                version = running_version[1:]
                unisphere_meets_min_req = (
                    self.utils.version_meet_req(version, minimum_version))
            elif running_version.lower()[0] == 't':
                LOG.warning("%(version)s This is not a official release of "
                            "Unisphere.", {'version': running_version})
                return major_version >= U4V_VERSION

        if unisphere_meets_min_req:
            LOG.info("Unisphere version %(running_version)s meets minimum "
                     "requirement of version %(minimum_version)s.",
                     {'running_version': running_version,
                      'minimum_version': minimum_version})
        elif running_version:
            LOG.error("Unisphere version %(running_version)s does not meet "
                      "minimum requirement for use with this release, please "
                      "upgrade to Unisphere %(minimum_version)s at minimum.",
                      {'running_version': running_version,
                       'minimum_version': minimum_version})
        else:
            LOG.warning("Unable to validate Unisphere instance meets minimum "
                        "requirements.")

        return unisphere_meets_min_req

    def get_snap_id(self, array, device_id, snap_name):
        """Get the unique snap id for a particular snap name

        :param array: the array serial number
        :param device_id: the source device ID
        :param snap_name: the user supplied snapVX name
        :raises: VolumeBackendAPIException
        :returns: snap_id -- str
        """
        snapshots = self.get_volume_snaps(array, device_id, snap_name)
        if not snapshots:
            exception_message = (_(
                "Snapshot %(snap_name)s is not associated with "
                "specified volume %(device_id)s.") % {
                'device_id': device_id, 'snap_name': snap_name})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(
                message=exception_message)
        elif len(snapshots) > 1:
            exception_message = (_(
                "Snapshot %(snap_name)s is associated with more than "
                "one snap id. No information available to choose "
                "which one.") % {
                'device_id': device_id, 'snap_name': snap_name})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(
                message=exception_message)
        else:
            return snapshots[0].get('snap_id') if self.is_snap_id else (
                snapshots[0].get('generation'))

    def get_major_minor_ucode(self, array):
        """Get the major and minor parts of the ucode

        :param array: the array serial number
        :returns: ucode_major_level, ucode_minor_level -- str, str
        """
        array_details = self.get_array_detail(array)
        ucode_major_level = 0
        ucode_minor_level = 0

        if array_details:
            split_ucode_level = array_details['ucode'].split('.')
            ucode_level = [int(level) for level in split_ucode_level]
            ucode_major_level = ucode_level[0]
            ucode_minor_level = ucode_level[1]
        return ucode_major_level, ucode_minor_level

    def _is_snapid_enabled(self):
        """Check if array is snap_id enabled

        :returns: boolean
        """
        return (self.ucode_major_level >= utils.UCODE_5978 and
                self.ucode_minor_level >= utils.UCODE_5978_HICKORY)
