# Copyright 2016 Datera
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
import re
import six
import time

from oslo_log import log as logging

from cinder import exception
from cinder.i18n import _, _LI, _LE


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

DEFAULT_SI_SLEEP = 10
DEFAULT_SNAP_SLEEP = 5
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
                raise exception.DateraAPIException(msg % (api_version, func))
            # Py27
            try:
                name = "_" + "_".join(
                    (func.func_name, api_version.replace(".", "_")))
            # Py3+
            except AttributeError:
                name = "_" + "_".join(
                    (func.__name__, api_version.replace(".", "_")))
            try:
                LOG.info(_LI("Trying method: %s"), name)
                return getattr(obj, name)(*args[1:], **kwargs)
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
                LOG.error(_LE("No supported API versions available, "
                              "Please upgrade your Datera EDF software"))
    return results
