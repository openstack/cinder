# Copyright 2017 Datera
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

import functools
import json
import re
import six
import time
import types
import uuid

import eventlet
import requests

from oslo_log import log as logging
from six.moves import http_client

from cinder import context
from cinder import exception
from cinder.i18n import _
from cinder.volume import qos_specs
from cinder.volume import volume_types


LOG = logging.getLogger(__name__)
OS_PREFIX = "OS-"
UNMANAGE_PREFIX = "UNMANAGED-"

# Taken from this SO post :
# http://stackoverflow.com/a/18516125
# Using old-style string formatting because of the nature of the regex
# conflicting with new-style curly braces
UUID4_STR_RE = ("%s[a-f0-9]{8}-?[a-f0-9]{4}-?4[a-f0-9]{3}-?[89ab]"
                "[a-f0-9]{3}-?[a-f0-9]{12}")
UUID4_RE = re.compile(UUID4_STR_RE % OS_PREFIX)

# Recursive dict to assemble basic url structure for the most common
# API URL endpoints. Most others are constructed from these
URL_TEMPLATES = {
    'ai': lambda: 'app_instances',
    'ai_inst': lambda: (URL_TEMPLATES['ai']() + '/{}'),
    'si': lambda: (URL_TEMPLATES['ai_inst']() + '/storage_instances'),
    'si_inst': lambda storage_name: (
        (URL_TEMPLATES['si']() + '/{}').format(
            '{}', storage_name)),
    'vol': lambda storage_name: (
        (URL_TEMPLATES['si_inst'](storage_name) + '/volumes')),
    'vol_inst': lambda storage_name, volume_name: (
        (URL_TEMPLATES['vol'](storage_name) + '/{}').format(
            '{}', volume_name)),
    'at': lambda: 'app_templates/{}'}

DEFAULT_SI_SLEEP = 1
DEFAULT_SI_SLEEP_API_2 = 5
DEFAULT_SNAP_SLEEP = 1
INITIATOR_GROUP_PREFIX = "IG-"
API_VERSIONS = ["2", "2.1"]
API_TIMEOUT = 20

###############
# METADATA KEYS
###############

M_TYPE = 'cinder_volume_type'
M_CALL = 'cinder_calls'
M_CLONE = 'cinder_clone_from'
M_MANAGED = 'cinder_managed'

M_KEYS = [M_TYPE, M_CALL, M_CLONE, M_MANAGED]


def _get_name(name):
    return "".join((OS_PREFIX, name))


def _get_unmanaged(name):
    return "".join((UNMANAGE_PREFIX, name))


def _authenticated(func):
    """Ensure the driver is authenticated to make a request.

    In do_setup() we fetch an auth token and store it. If that expires when
    we do API request, we'll fetch a new one.
    """
    @functools.wraps(func)
    def func_wrapper(driver, *args, **kwargs):
        try:
            return func(driver, *args, **kwargs)
        except exception.NotAuthorized:
            # Prevent recursion loop. After the driver arg is the
            # resource_type arg from _issue_api_request(). If attempt to
            # login failed, we should just give up.
            if args[0] == 'login':
                raise

            # Token might've expired, get a new one, try again.
            driver.login()
            return func(driver, *args, **kwargs)
    return func_wrapper


def _api_lookup(func):
    """Perform a dynamic API implementation lookup for a call

    Naming convention follows this pattern:

        # original_func(args) --> _original_func_X_?Y?(args)
        # where X and Y are the major and minor versions of the latest
        # supported API version

        # From the Datera box we've determined that it supports API
        # versions ['2', '2.1']
        # This is the original function call
        @_api_lookup
        def original_func(arg1, arg2):
            print("I'm a shim, this won't get executed!")
            pass

        # This is the function that is actually called after determining
        # the correct API version to use
        def _original_func_2_1(arg1, arg2):
            some_version_2_1_implementation_here()

        # This is the function that would be called if the previous function
        # did not exist:
        def _original_func_2(arg1, arg2):
            some_version_2_implementation_here()

        # This function would NOT be called, because the connected Datera box
        # does not support the 1.5 version of the API
        def _original_func_1_5(arg1, arg2):
            some_version_1_5_implementation_here()
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        obj = args[0]
        api_versions = _get_supported_api_versions(obj)
        api_version = None
        index = -1
        while True:
            try:
                api_version = api_versions[index]
            except (IndexError, KeyError):
                msg = _("No compatible API version found for this product: "
                        "api_versions -> %(api_version)s, %(func)s")
                LOG.error(msg, api_version=api_version, func=func)
                raise exception.DateraAPIException(msg % {
                    'api_version': api_version, 'func': func})
            # Py27
            try:
                name = "_" + "_".join(
                    (func.func_name, api_version.replace(".", "_")))
            # Py3+
            except AttributeError:
                name = "_" + "_".join(
                    (func.__name__, api_version.replace(".", "_")))
            try:
                if obj.do_profile:
                    LOG.info("Trying method: %s", name)
                    call_id = uuid.uuid4()
                    LOG.debug("Profiling method: %s, id %s", name, call_id)
                    t1 = time.time()
                    obj.thread_local.trace_id = call_id
                result = getattr(obj, name)(*args[1:], **kwargs)
                if obj.do_profile:
                    t2 = time.time()
                    timedelta = round(t2 - t1, 3)
                    LOG.debug("Profile for method %s, id %s: %ss",
                              name, call_id, timedelta)
                return result
            except AttributeError as e:
                # If we find the attribute name in the error message
                # then we continue otherwise, raise to prevent masking
                # errors
                if name not in six.text_type(e):
                    raise
                else:
                    LOG.info(e)
                    index -= 1
            except exception.DateraAPIException as e:
                if "UnsupportedVersionError" in six.text_type(e):
                    index -= 1
                else:
                    raise

    return wrapper


def _get_supported_api_versions(driver):
    t = time.time()
    if driver.api_cache and driver.api_timeout - t < API_TIMEOUT:
        return driver.api_cache
    driver.api_timeout = t + API_TIMEOUT
    results = []
    host = driver.configuration.san_ip
    port = driver.configuration.datera_api_port
    client_cert = driver.configuration.driver_client_cert
    client_cert_key = driver.configuration.driver_client_cert_key
    cert_data = None
    header = {'Content-Type': 'application/json; charset=utf-8',
              'Datera-Driver': 'OpenStack-Cinder-{}'.format(driver.VERSION)}
    protocol = 'http'
    if client_cert:
        protocol = 'https'
        cert_data = (client_cert, client_cert_key)
    try:
        url = '%s://%s:%s/api_versions' % (protocol, host, port)
        resp = driver._request(url, "get", None, header, cert_data)
        data = resp.json()
        results = [elem.strip("v") for elem in data['api_versions']]
    except (exception.DateraAPIException, KeyError):
        # Fallback to pre-endpoint logic
        for version in API_VERSIONS[0:-1]:
            url = '%s://%s:%s/v%s' % (protocol, host, port, version)
            resp = driver._request(url, "get", None, header, cert_data)
            if ("api_req" in resp.json() or
                    str(resp.json().get("code")) == "99"):
                results.append(version)
            else:
                LOG.error("No supported API versions available, "
                          "Please upgrade your Datera EDF software")
    return results


def _get_volume_type_obj(driver, resource):
    type_id = resource.get('volume_type_id', None)
    # Handle case of volume with no type.  We still want the
    # specified defaults from above
    if type_id:
        ctxt = context.get_admin_context()
        volume_type = volume_types.get_volume_type(ctxt, type_id)
    else:
        volume_type = None
    return volume_type


def _get_policies_for_resource(driver, resource):
    """Get extra_specs and qos_specs of a volume_type.

    This fetches the scoped keys from the volume type. Anything set from
     qos_specs will override key/values set from extra_specs.
    """
    volume_type = driver._get_volume_type_obj(resource)
    # Handle case of volume with no type.  We still want the
    # specified defaults from above
    if volume_type:
        specs = volume_type.get('extra_specs')
    else:
        specs = {}

    # Set defaults:
    policies = {k.lstrip('DF:'): str(v['default']) for (k, v)
                in driver._init_vendor_properties()[0].items()}

    if volume_type:
        # Populate updated value
        for key, value in specs.items():
            if ':' in key:
                fields = key.split(':')
                key = fields[1]
                policies[key] = value

        qos_specs_id = volume_type.get('qos_specs_id')
        if qos_specs_id is not None:
            ctxt = context.get_admin_context()
            qos_kvs = qos_specs.get_qos_specs(ctxt, qos_specs_id)['specs']
            if qos_kvs:
                policies.update(qos_kvs)
    # Cast everything except booleans int that can be cast
    for k, v in policies.items():
        # Handle String Boolean case
        if v == 'True' or v == 'False':
            policies[k] = policies[k] == 'True'
            continue
        # Int cast
        try:
            policies[k] = int(v)
        except ValueError:
            pass
    return policies


# ================
# = API Requests =
# ================

def _request(driver, connection_string, method, payload, header, cert_data):
    LOG.debug("Endpoint for Datera API call: %s", connection_string)
    LOG.debug("Payload for Datera API call: %s", payload)
    try:
        response = getattr(requests, method)(connection_string,
                                             data=payload, headers=header,
                                             verify=False, cert=cert_data)
        return response
    except requests.exceptions.RequestException as ex:
        msg = _(
            'Failed to make a request to Datera cluster endpoint due '
            'to the following reason: %s') % six.text_type(
            ex.message)
        LOG.error(msg)
        raise exception.DateraAPIException(msg)


def _raise_response(driver, response):
    msg = _('Request to Datera cluster returned bad status:'
            ' %(status)s | %(reason)s') % {
                'status': response.status_code,
                'reason': response.reason}
    LOG.error(msg)
    raise exception.DateraAPIException(msg)


def _handle_bad_status(driver,
                       response,
                       connection_string,
                       method,
                       payload,
                       header,
                       cert_data,
                       sensitive=False,
                       conflict_ok=False):
    if (response.status_code == http_client.BAD_REQUEST and
            connection_string.endswith("api_versions")):
        # Raise the exception, but don't log any error.  We'll just fall
        # back to the old style of determining API version.  We make this
        # request a lot, so logging it is just noise
        raise exception.DateraAPIException
    if response.status_code == http_client.NOT_FOUND:
        raise exception.NotFound(response.json()['message'])
    elif response.status_code in [http_client.FORBIDDEN,
                                  http_client.UNAUTHORIZED]:
        raise exception.NotAuthorized()
    elif response.status_code == http_client.CONFLICT and conflict_ok:
        # Don't raise, because we're expecting a conflict
        pass
    elif response.status_code == http_client.SERVICE_UNAVAILABLE:
        current_retry = 0
        while current_retry <= driver.retry_attempts:
            LOG.debug("Datera 503 response, trying request again")
            eventlet.sleep(driver.interval)
            resp = driver._request(connection_string,
                                   method,
                                   payload,
                                   header,
                                   cert_data)
            if resp.ok:
                return response.json()
            elif resp.status_code != http_client.SERVICE_UNAVAILABLE:
                driver._raise_response(resp)
    else:
        driver._raise_response(response)


@_authenticated
def _issue_api_request(driver, resource_url, method='get', body=None,
                       sensitive=False, conflict_ok=False,
                       api_version='2', tenant=None):
    """All API requests to Datera cluster go through this method.

    :param resource_url: the url of the resource
    :param method: the request verb
    :param body: a dict with options for the action_type
    :param sensitive: Bool, whether request should be obscured from logs
    :param conflict_ok: Bool, True to suppress ConflictError exceptions
    during this request
    :param api_version: The Datera api version for the request
    :param tenant: The tenant header value for the request (only applicable
    to 2.1 product versions and later)
    :returns: a dict of the response from the Datera cluster
    """
    host = driver.configuration.san_ip
    port = driver.configuration.datera_api_port
    api_token = driver.datera_api_token

    payload = json.dumps(body, ensure_ascii=False)
    payload.encode('utf-8')

    header = {'Content-Type': 'application/json; charset=utf-8'}
    header.update(driver.HEADER_DATA)

    protocol = 'http'
    if driver.configuration.driver_use_ssl:
        protocol = 'https'

    if api_token:
        header['Auth-Token'] = api_token

    if tenant == "all":
        header['tenant'] = tenant
    elif tenant and '/root' not in tenant:
        header['tenant'] = "".join(("/root/", tenant))
    elif tenant and '/root' in tenant:
        header['tenant'] = tenant
    elif driver.tenant_id and driver.tenant_id.lower() != "map":
        header['tenant'] = driver.tenant_id

    client_cert = driver.configuration.driver_client_cert
    client_cert_key = driver.configuration.driver_client_cert_key
    cert_data = None

    if client_cert:
        protocol = 'https'
        cert_data = (client_cert, client_cert_key)

    connection_string = '%s://%s:%s/v%s/%s' % (protocol, host, port,
                                               api_version, resource_url)

    request_id = uuid.uuid4()

    if driver.do_profile:
        t1 = time.time()
    if not sensitive:
        LOG.debug("\nDatera Trace ID: %(tid)s\n"
                  "Datera Request ID: %(rid)s\n"
                  "Datera Request URL: /v%(api)s/%(url)s\n"
                  "Datera Request Method: %(method)s\n"
                  "Datera Request Payload: %(payload)s\n"
                  "Datera Request Headers: %(header)s\n",
                  {'tid': driver.thread_local.trace_id,
                   'rid': request_id,
                   'api': api_version,
                   'url': resource_url,
                   'method': method,
                   'payload': payload,
                   'header': header})
    response = driver._request(connection_string,
                               method,
                               payload,
                               header,
                               cert_data)

    data = response.json()

    timedelta = "Profiling disabled"
    if driver.do_profile:
        t2 = time.time()
        timedelta = round(t2 - t1, 3)
    if not sensitive:
        LOG.debug("\nDatera Trace ID: %(tid)s\n"
                  "Datera Response ID: %(rid)s\n"
                  "Datera Response TimeDelta: %(delta)ss\n"
                  "Datera Response URL: %(url)s\n"
                  "Datera Response Payload: %(payload)s\n"
                  "Datera Response Object: %(obj)s\n",
                  {'tid': driver.thread_local.trace_id,
                   'rid': request_id,
                   'delta': timedelta,
                   'url': response.url,
                   'payload': payload,
                   'obj': vars(response)})
    if not response.ok:
        driver._handle_bad_status(response,
                                  connection_string,
                                  method,
                                  payload,
                                  header,
                                  cert_data,
                                  conflict_ok=conflict_ok)

    return data


def register_driver(driver):
    for func in [_get_supported_api_versions,
                 _get_volume_type_obj,
                 _get_policies_for_resource,
                 _request,
                 _raise_response,
                 _handle_bad_status,
                 _issue_api_request]:
        # PY27

        f = types.MethodType(func, driver)
        try:
            setattr(driver, func.func_name, f)
        # PY3+
        except AttributeError:
            setattr(driver, func.__name__, f)
