#    (c)  Copyright 2022 Fungible, Inc. All rights reserved.
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

from __future__ import absolute_import

import copy
import datetime
import http.client as httplib
import io
import json
import logging
import mimetypes
import multiprocessing
from multiprocessing.pool import ThreadPool
import os
import pprint
import re
import ssl
import sys
import tempfile
from urllib.parse import quote
from urllib.parse import urlencode

import certifi

try:
    import urllib3
except ImportError:
    raise ImportError('Swagger python client requires urllib3.')


logger = logging.getLogger(__name__)


class RESTResponse(io.IOBase):

    def __init__(self, resp):
        self.urllib3_response = resp
        self.status = resp.status
        self.reason = resp.reason
        self.data = resp.data

    def getheaders(self):
        """Returns a dictionary of the response headers."""
        return self.urllib3_response.getheaders()

    def getheader(self, name, default=None):
        """Returns a given response header."""
        return self.urllib3_response.getheader(name, default)


class RESTClientObject(object):

    def __init__(self, configuration, pools_size=4, maxsize=None):
        # urllib3.PoolManager will pass all kw parameters to connectionpool
        # https://github.com/shazow/urllib3/blob/f9409436f83aeb79fbaf090181cd81b784f1b8ce/urllib3/poolmanager.py#L75  # noqa: E501
        # https://github.com/shazow/urllib3/blob/f9409436f83aeb79fbaf090181cd81b784f1b8ce/urllib3/connectionpool.py#L680  # noqa: E501
        # maxsize is the number of requests to host that are allowed in parallel  # noqa: E501
        # Custom SSL certificates and client certificates: http://urllib3.readthedocs.io/en/latest/advanced-usage.html  # noqa: E501

        # cert_reqs
        if configuration.verify_ssl:
            cert_reqs = ssl.CERT_REQUIRED
        else:
            cert_reqs = ssl.CERT_NONE

        # ca_certs
        if configuration.ssl_ca_cert:
            ca_certs = configuration.ssl_ca_cert
        else:
            # if not set certificate file, use Mozilla's root certificates.
            ca_certs = certifi.where()

        addition_pool_args = {}
        if configuration.assert_hostname is not None:
            addition_pool_args['assert_hostname'] = configuration.assert_hostname  # noqa: E501

        if maxsize is None:
            if configuration.connection_pool_maxsize is not None:
                maxsize = configuration.connection_pool_maxsize
            else:
                maxsize = 4

        # https pool manager
        if configuration.proxy:
            self.pool_manager = urllib3.ProxyManager(
                num_pools=pools_size,
                maxsize=maxsize,
                cert_reqs=cert_reqs,
                ca_certs=ca_certs,
                cert_file=configuration.cert_file,
                key_file=configuration.key_file,
                proxy_url=configuration.proxy,
                **addition_pool_args
            )
        else:
            self.pool_manager = urllib3.PoolManager(
                num_pools=pools_size,
                maxsize=maxsize,
                cert_reqs=cert_reqs,
                ca_certs=ca_certs,
                cert_file=configuration.cert_file,
                key_file=configuration.key_file,
                **addition_pool_args
            )

    def request(self, method, url, query_params=None, headers=None,
                body=None, post_params=None, _preload_content=True,
                _request_timeout=None):
        """Perform requests.

        :param method: http request method
        :param url: http request url
        :param query_params: query parameters in the url
        :param headers: http request headers
        :param body: request json body, for `application/json`
        :param post_params: request post parameters,
                            `application/x-www-form-urlencoded`
                            and `multipart/form-data`
        :param _preload_content: if False, the urllib3.HTTPResponse object will
                                 be returned without reading/decoding response
                                 data. Default is True.
        :param _request_timeout: timeout setting for this request. If one
                                 number provided, it will be total request
                                 timeout. It can also be a pair (tuple) of
                                 (connection, read) timeouts.
        """
        method = method.upper()
        assert method in ['GET', 'HEAD', 'DELETE', 'POST', 'PUT',
                          'PATCH', 'OPTIONS']

        if post_params and body:
            raise ValueError(
                "body parameter cannot be used with post_params parameter."
            )

        post_params = post_params or {}
        headers = headers or {}

        timeout = None
        if _request_timeout:
            if isinstance(_request_timeout, (int, )):  # noqa: E501,F821
                timeout = urllib3.Timeout(total=_request_timeout)
            elif (isinstance(_request_timeout, tuple) and
                  len(_request_timeout) == 2):
                timeout = urllib3.Timeout(
                    connect=_request_timeout[0], read=_request_timeout[1])

        if 'Content-Type' not in headers:
            headers['Content-Type'] = 'application/json'

        try:
            # For `POST`, `PUT`, `PATCH`, `OPTIONS`, `DELETE`
            if method in ['POST', 'PUT', 'PATCH', 'OPTIONS', 'DELETE']:
                if query_params:
                    url += '?' + urlencode(query_params)
                if re.search('json', headers['Content-Type'], re.IGNORECASE):
                    request_body = '{}'
                    if body is not None:
                        request_body = json.dumps(body)
                    r = self.pool_manager.request(
                        method, url,
                        body=request_body,
                        preload_content=_preload_content,
                        timeout=timeout,
                        headers=headers)
                elif headers['Content-Type'] == 'application/x-www-form-urlencoded':  # noqa: E501
                    r = self.pool_manager.request(
                        method, url,
                        fields=post_params,
                        encode_multipart=False,
                        preload_content=_preload_content,
                        timeout=timeout,
                        headers=headers)
                elif headers['Content-Type'] == 'multipart/form-data':
                    # must del headers['Content-Type'], or the correct
                    # Content-Type which generated by urllib3 will be
                    # overwritten.
                    del headers['Content-Type']
                    r = self.pool_manager.request(
                        method, url,
                        fields=post_params,
                        encode_multipart=True,
                        preload_content=_preload_content,
                        timeout=timeout,
                        headers=headers)
                # Pass a `string` parameter directly in the body to support
                # other content types than Json when `body` argument is
                # provided in serialized form
                elif isinstance(body, str):
                    request_body = body
                    r = self.pool_manager.request(
                        method, url,
                        body=request_body,
                        preload_content=_preload_content,
                        timeout=timeout,
                        headers=headers)
                else:
                    # Cannot generate the request from given parameters
                    msg = """Cannot prepare a request message for provided
                             arguments. Please check that your arguments match
                             declared content type."""
                    raise ApiException(status=0, reason=msg)
            # For `GET`, `HEAD`
            else:
                r = self.pool_manager.request(method, url,
                                              fields=query_params,
                                              preload_content=_preload_content,
                                              timeout=timeout,
                                              headers=headers)
        except urllib3.exceptions.SSLError as e:
            msg = "{0}\n{1}".format(type(e).__name__, str(e))
            raise ApiException(status=0, reason=msg)

        if _preload_content:
            r = RESTResponse(r)

            # In the python 3, the response.data is bytes.
            # we need to decode it to string.
            r.data = r.data.decode('utf8')

            # log response body
            logger.debug("response body: %s", r.data)

        if not 200 <= r.status <= 299:
            raise ApiException(http_resp=r)

        return r

    def GET(self, url, headers=None, query_params=None, _preload_content=True,
            _request_timeout=None):
        return self.request("GET", url,
                            headers=headers,
                            _preload_content=_preload_content,
                            _request_timeout=_request_timeout,
                            query_params=query_params)

    def HEAD(self, url, headers=None, query_params=None, _preload_content=True,
             _request_timeout=None):
        return self.request("HEAD", url,
                            headers=headers,
                            _preload_content=_preload_content,
                            _request_timeout=_request_timeout,
                            query_params=query_params)

    def OPTIONS(self, url, headers=None, query_params=None, post_params=None,
                body=None, _preload_content=True, _request_timeout=None):
        return self.request("OPTIONS", url,
                            headers=headers,
                            query_params=query_params,
                            post_params=post_params,
                            _preload_content=_preload_content,
                            _request_timeout=_request_timeout,
                            body=body)

    def DELETE(self, url, headers=None, query_params=None, body=None,
               _preload_content=True, _request_timeout=None):
        return self.request("DELETE", url,
                            headers=headers,
                            query_params=query_params,
                            _preload_content=_preload_content,
                            _request_timeout=_request_timeout,
                            body=body)

    def POST(self, url, headers=None, query_params=None, post_params=None,
             body=None, _preload_content=True, _request_timeout=None):
        return self.request("POST", url,
                            headers=headers,
                            query_params=query_params,
                            post_params=post_params,
                            _preload_content=_preload_content,
                            _request_timeout=_request_timeout,
                            body=body)

    def PUT(self, url, headers=None, query_params=None, post_params=None,
            body=None, _preload_content=True, _request_timeout=None):
        return self.request("PUT", url,
                            headers=headers,
                            query_params=query_params,
                            post_params=post_params,
                            _preload_content=_preload_content,
                            _request_timeout=_request_timeout,
                            body=body)

    def PATCH(self, url, headers=None, query_params=None, post_params=None,
              body=None, _preload_content=True, _request_timeout=None):
        return self.request("PATCH", url,
                            headers=headers,
                            query_params=query_params,
                            post_params=post_params,
                            _preload_content=_preload_content,
                            _request_timeout=_request_timeout,
                            body=body)


class ApiException(Exception):

    def __init__(self, status=None, reason=None, http_resp=None):
        if http_resp:
            self.status = http_resp.status
            self.reason = http_resp.reason
            self.body = http_resp.data
            self.headers = http_resp.getheaders()
        else:
            self.status = status
            self.reason = reason
            self.body = None
            self.headers = None

    def __str__(self):
        """Custom error messages for exception"""
        error_message = "({0})\n"\
                        "Reason: {1}\n".format(self.status, self.reason)
        if self.headers:
            error_message += "HTTP response headers: {0}\n".format(
                self.headers)

        if self.body:
            error_message += "HTTP response body: {0}\n".format(self.body)

        return error_message


class Configuration(object):
    """NOTE: This class is auto generated by the swagger code generator program

    Ref: https://github.com/swagger-api/swagger-codegen
    Do not edit the class manually.
    """

    _default = None

    def __init__(self):
        """Constructor"""
        if self._default:
            for key in self._default.__dict__.keys():
                self.__dict__[key] = copy.copy(self._default.__dict__[key])
            return

        # Default Base url
        self.host = "http://localhost:50220/FunCC/v1"
        # Temp file folder for downloading files
        self.temp_folder_path = None

        # Authentication Settings
        # dict to store API key(s)
        self.api_key = {}
        # dict to store API prefix (e.g. Bearer)
        self.api_key_prefix = {}
        # function to refresh API key if expired
        self.refresh_api_key_hook = None
        # Username for HTTP basic authentication
        self.username = ""
        # Password for HTTP basic authentication
        self.password = ""

        # Logging Settings
        self.logger = {}
        self.logger["package_logger"] = logging.getLogger("swagger_client")
        self.logger["urllib3_logger"] = logging.getLogger("urllib3")
        # Log format
        self.logger_format = '%(asctime)s %(levelname)s %(message)s'
        # Log stream handler
        self.logger_stream_handler = None
        # Log file handler
        self.logger_file_handler = None
        # Debug file location
        self.logger_file = None
        # Debug switch
        self.debug = False

        # SSL/TLS verification
        # Set this to false to skip verifying SSL certificate when calling API
        # from https server.
        self.verify_ssl = True
        # Set this to customize the certificate file to verify the peer.
        self.ssl_ca_cert = None
        # client certificate file
        self.cert_file = None
        # client key file
        self.key_file = None
        # Set this to True/False to enable/disable SSL hostname verification.
        self.assert_hostname = None

        # urllib3 connection pool's maximum number of connections saved
        # per pool. urllib3 uses 1 connection as default value, but this is
        # not the best value when you are making a lot of possibly parallel
        # requests to the same host, which is often the case here.
        # cpu_count * 5 is used as default value to increase performance.
        self.connection_pool_maxsize = multiprocessing.cpu_count() * 5

        # Proxy URL
        self.proxy = None
        # Safe chars for path_param
        self.safe_chars_for_path_param = ''

        # Disable client side validation
        self.client_side_validation = True

    @classmethod
    def set_default(cls, default):
        cls._default = default

    @property
    def logger_file(self):
        """The logger file.

        If the logger_file is None, then add stream handler and remove file
        handler. Otherwise, add file handler and remove stream handler.

        :param value: The logger_file path.
        :type: str
        """
        return self.__logger_file

    @logger_file.setter
    def logger_file(self, value):
        """The logger file.

        If the logger_file is None, then add stream handler and remove file
        handler. Otherwise, add file handler and remove stream handler.

        :param value: The logger_file path.
        :type: str
        """
        self.__logger_file = value
        if self.__logger_file:
            # If set logging file,
            # then add file handler and remove stream handler.
            self.logger_file_handler = logging.FileHandler(self.__logger_file)
            self.logger_file_handler.setFormatter(self.logger_formatter)
            for _, logger in self.logger.items():
                logger.addHandler(self.logger_file_handler)
                if self.logger_stream_handler:
                    logger.removeHandler(self.logger_stream_handler)
        else:
            # If not set logging file,
            # then add stream handler and remove file handler.
            self.logger_stream_handler = logging.StreamHandler()
            self.logger_stream_handler.setFormatter(self.logger_formatter)
            for _, logger in self.logger.items():
                logger.addHandler(self.logger_stream_handler)
                if self.logger_file_handler:
                    logger.removeHandler(self.logger_file_handler)

    @property
    def debug(self):
        """Debug status

        :param value: The debug status, True or False.
        :type: bool
        """
        return self.__debug

    @debug.setter
    def debug(self, value):
        """Debug status

        :param value: The debug status, True or False.
        :type: bool
        """
        self.__debug = value
        if self.__debug:
            # if debug status is True, turn on debug logging
            for _, logger in self.logger.items():
                logger.setLevel(logging.DEBUG)
            # turn on httplib debug
            httplib.HTTPConnection.debuglevel = 1
        else:
            # if debug status is False, turn off debug logging,
            # setting log level to default `logging.WARNING`
            for _, logger in self.logger.items():
                logger.setLevel(logging.WARNING)
            # turn off httplib debug
            httplib.HTTPConnection.debuglevel = 0

    @property
    def logger_format(self):
        """The logger format.

        The logger_formatter will be updated when sets logger_format.

        :param value: The format string.
        :type: str
        """
        return self.__logger_format

    @logger_format.setter
    def logger_format(self, value):
        """The logger format.

        The logger_formatter will be updated when sets logger_format.

        :param value: The format string.
        :type: str
        """
        self.__logger_format = value
        self.logger_formatter = logging.Formatter(self.__logger_format)

    def get_api_key_with_prefix(self, identifier):
        """Gets API key (with prefix if set).

        :param identifier: The identifier of apiKey.
        :return: The token for api key authentication.
        """

        if self.refresh_api_key_hook:
            self.refresh_api_key_hook(self)

        key = self.api_key.get(identifier)
        if key:
            prefix = self.api_key_prefix.get(identifier)
            if prefix:
                return "%s %s" % (prefix, key)
            else:
                return key

    def get_basic_auth_token(self):
        """Gets HTTP basic authentication header (string).

        :return: The token for basic HTTP authentication.
        """
        return urllib3.util.make_headers(
            basic_auth=self.username + ':' + self.password
        ).get('authorization')

    def auth_settings(self):
        """Gets Auth Settings dict for api client.

        :return: The Auth Settings information dict.
        """
        return {
            'Basic':
                {
                    'type': 'basic',
                    'in': 'header',
                    'key': 'Authorization',
                    'value': self.get_basic_auth_token()
                },
            'Bearer':
                {
                    'type': 'api_key',
                    'in': 'header',
                    'key': 'Authorization',
                    'value': self.get_api_key_with_prefix('Authorization')
                },

        }

    def to_debug_report(self):
        """Gets the essential information for debugging.

        :return: The report for debugging.
        """
        return "Python SDK Debug Report:\n"\
               "OS: {env}\n"\
               "Python Version: {pyversion}\n"\
               "Version of the API: 2.2.10\n"\
               "SDK Package Version: 1.0.0".\
               format(env=sys.platform, pyversion=sys.version)


class ApiClient(object):
    """Generic API client for Swagger client library builds.

    Swagger generic API client. This client handles the client-
    server communication, and is invariant across implementations. Specifics of
    the methods and models for each application are generated from the Swagger
    templates.

    NOTE: This class is auto generated by the swagger code generator program
    Ref: https://github.com/swagger-api/swagger-codegen
    Do not edit the class manually.

    :param configuration: .Configuration object for this client
    :param header_name: a header to pass when making calls to the API.
    :param header_value: a header value to pass when making calls to
        the API.
    :param cookie: a cookie to include in the header when making calls
        to the API
    """

    PRIMITIVE_TYPES = (float, bool, bytes, str, int)
    NATIVE_TYPES_MAPPING = {
        'int': int,
        'long': int,  # noqa: F821
        'float': float,
        'str': str,
        'bool': bool,
        'date': datetime.date,
        'datetime': datetime.datetime,
        'object': object,
    }

    def __init__(self, configuration=None, header_name=None, header_value=None,
                 cookie=None):
        if configuration is None:
            configuration = Configuration()
        self.configuration = configuration

        # Use the pool property to lazily initialize the ThreadPool.
        self._pool = None
        self.rest_client = RESTClientObject(configuration)
        self.default_headers = {}
        if header_name is not None:
            self.default_headers[header_name] = header_value
        self.cookie = cookie
        # Set default User-Agent.
        self.user_agent = 'Swagger-Codegen/1.0.0/python'
        self.client_side_validation = configuration.client_side_validation

    def __del__(self):
        if self._pool is not None:
            self._pool.close()
            self._pool.join()

    @property
    def pool(self):
        if self._pool is None:
            self._pool = ThreadPool()
        return self._pool

    @property
    def user_agent(self):
        """User agent for this API client"""
        return self.default_headers['User-Agent']

    @user_agent.setter
    def user_agent(self, value):
        self.default_headers['User-Agent'] = value

    def set_default_header(self, header_name, header_value):
        self.default_headers[header_name] = header_value

    def __call_api(
            self, resource_path, method, path_params=None,
            query_params=None, header_params=None, body=None, post_params=None,
            files=None, response_type=None, auth_settings=None,
            _return_http_data_only=None, collection_formats=None,
            _preload_content=True, _request_timeout=None):

        config = self.configuration

        # header parameters
        header_params = header_params or {}
        header_params.update(self.default_headers)
        if self.cookie:
            header_params['Cookie'] = self.cookie
        if header_params:
            header_params = self.sanitize_for_serialization(header_params)
            header_params = dict(self.parameters_to_tuples(header_params,
                                                           collection_formats))

        # path parameters
        if path_params:
            path_params = self.sanitize_for_serialization(path_params)
            path_params = self.parameters_to_tuples(path_params,
                                                    collection_formats)
            for k, v in path_params:
                # specified safe chars, encode everything
                resource_path = resource_path.replace(
                    '{%s}' % k,
                    quote(str(v), safe=config.safe_chars_for_path_param)
                )

        # query parameters
        if query_params:
            query_params = self.sanitize_for_serialization(query_params)
            query_params = self.parameters_to_tuples(query_params,
                                                     collection_formats)

        # post parameters
        if post_params or files:
            post_params = self.prepare_post_parameters(post_params, files)
            post_params = self.sanitize_for_serialization(post_params)
            post_params = self.parameters_to_tuples(post_params,
                                                    collection_formats)

        # auth setting
        self.update_params_for_auth(header_params, query_params, auth_settings)

        # body
        if body:
            body = self.sanitize_for_serialization(body)

        # request url
        url = self.configuration.host + resource_path

        # perform request and return response
        response_data = self.request(
            method, url, query_params=query_params, headers=header_params,
            post_params=post_params, body=body,
            _preload_content=_preload_content,
            _request_timeout=_request_timeout)

        self.last_response = response_data

        return_data = response_data
        if _preload_content:
            # deserialize response data
            if response_type:
                return_data = self.deserialize(response_data, response_type)
            else:
                return_data = None

        if _return_http_data_only:
            return (return_data)
        else:
            return (return_data, response_data.status,
                    response_data.getheaders())

    def sanitize_for_serialization(self, obj):
        """Builds a JSON POST object.

        If obj is None, return None.
        If obj is str, int, long, float, bool, return directly.
        If obj is datetime.datetime, datetime.date
            convert to string in iso8601 format.
        If obj is list, sanitize each element in the list.
        If obj is dict, return the dict.
        If obj is swagger model, return the properties dict.

        :param obj: The data to serialize.
        :return: The serialized form of data.
        """
        if obj is None:
            return None
        elif isinstance(obj, self.PRIMITIVE_TYPES):
            return obj
        elif isinstance(obj, list):
            return [self.sanitize_for_serialization(sub_obj)
                    for sub_obj in obj]
        elif isinstance(obj, tuple):
            return tuple(self.sanitize_for_serialization(sub_obj)
                         for sub_obj in obj)
        elif isinstance(obj, (datetime.datetime, datetime.date)):
            return obj.isoformat()

        if isinstance(obj, dict):
            obj_dict = obj
        else:
            # Convert model obj to dict except
            # attributes `swagger_types`, `attribute_map`
            # and attributes which value is not None.
            # Convert attribute name to json key in
            # model definition for request.
            obj_dict = {obj.attribute_map[attr]: getattr(obj, attr)
                        for attr, _ in obj.swagger_types.items()
                        if getattr(obj, attr) is not None}

        return {key: self.sanitize_for_serialization(val)
                for key, val in obj_dict.items()}

    def deserialize(self, response, response_type):
        """Deserializes response into an object.

        :param response: RESTResponse object to be deserialized.
        :param response_type: class literal for
            deserialized object, or string of class name.

        :return: deserialized object.
        """
        # handle file downloading
        # save response body into a tmp file and return the instance
        if response_type == "file":
            return self.__deserialize_file(response)

        # fetch data from response object
        try:
            data = json.loads(response.data)
        except ValueError:
            data = response.data

        return self.__deserialize(data, response_type)

    def __deserialize(self, data, klass):
        """Deserializes dict, list, str into an object.

        :param data: dict, list or str.
        :param klass: class literal, or string of class name.

        :return: object.
        """
        if data is None:
            return None

        if type(klass) is str:
            if klass.startswith('list['):
                sub_kls = re.match(r'list\[(.*)\]', klass).group(1)
                return [self.__deserialize(sub_data, sub_kls)
                        for sub_data in data]

            if klass.startswith('dict('):
                sub_kls = re.match(r'dict\(([^,]*), (.*)\)', klass).group(2)
                return {k: self.__deserialize(v, sub_kls)
                        for k, v in data.items()}

            # convert str to class
            if klass in self.NATIVE_TYPES_MAPPING:
                klass = self.NATIVE_TYPES_MAPPING[klass]
            else:
                logger.debug("klass: %s", klass)
                klass = getattr(sys.modules[__name__], klass)

        if klass in self.PRIMITIVE_TYPES:
            return self.__deserialize_primitive(data, klass)
        elif klass == object:
            return self.__deserialize_object(data)
        elif klass == datetime.date:
            return self.__deserialize_date(data)
        elif klass == datetime.datetime:
            return self.__deserialize_datatime(data)
        else:
            return self.__deserialize_model(data, klass)

    def call_api(self, resource_path, method,
                 path_params=None, query_params=None, header_params=None,
                 body=None, post_params=None, files=None,
                 response_type=None, auth_settings=None, async_req=None,
                 _return_http_data_only=None, collection_formats=None,
                 _preload_content=True, _request_timeout=None):
        """Makes the HTTP request (synchronous) and returns deserialized data.

        To make an async request, set the async_req parameter.

        :param resource_path: Path to method endpoint.
        :param method: Method to call.
        :param path_params: Path parameters in the url.
        :param query_params: Query parameters in the url.
        :param header_params: Header parameters to be
            placed in the request header.
        :param body: Request body.
        :param post_params dict: Request post form parameters,
            for `application/x-www-form-urlencoded`, `multipart/form-data`.
        :param auth_settings list: Auth Settings names for the request.
        :param response: Response data type.
        :param files dict: key -> filename, value -> filepath,
            for `multipart/form-data`.
        :param async_req bool: execute request asynchronously
        :param _return_http_data_only: response data without head status code
                                       and headers
        :param collection_formats: dict of collection formats for path, query,
            header, and post parameters.
        :param _preload_content: if False, the urllib3.HTTPResponse object will
                                 be returned without reading/decoding response
                                 data. Default is True.
        :param _request_timeout: timeout setting for this request. If one
                                 number provided, it will be total request
                                 timeout. It can also be a pair (tuple) of
                                 (connection, read) timeouts.
        :return:
            If async_req parameter is True,
            the request will be called asynchronously.
            The method will return the request thread.
            If parameter async_req is False or missing,
            then the method will return the response directly.
        """
        if not async_req:
            return self.__call_api(resource_path, method,
                                   path_params, query_params, header_params,
                                   body, post_params, files,
                                   response_type, auth_settings,
                                   _return_http_data_only, collection_formats,
                                   _preload_content, _request_timeout)
        else:
            thread = self.pool.apply_async(self.__call_api, (resource_path,
                                           method, path_params, query_params,
                                           header_params, body,
                                           post_params, files,
                                           response_type, auth_settings,
                                           _return_http_data_only,
                                           collection_formats,
                                           _preload_content, _request_timeout))
        return thread

    def request(self, method, url, query_params=None, headers=None,
                post_params=None, body=None, _preload_content=True,
                _request_timeout=None):
        """Makes the HTTP request using RESTClient."""
        if method == "GET":
            return self.rest_client.GET(url,
                                        query_params=query_params,
                                        _preload_content=_preload_content,
                                        _request_timeout=_request_timeout,
                                        headers=headers)
        elif method == "HEAD":
            return self.rest_client.HEAD(url,
                                         query_params=query_params,
                                         _preload_content=_preload_content,
                                         _request_timeout=_request_timeout,
                                         headers=headers)
        elif method == "OPTIONS":
            return self.rest_client.OPTIONS(url,
                                            query_params=query_params,
                                            headers=headers,
                                            post_params=post_params,
                                            _preload_content=_preload_content,
                                            _request_timeout=_request_timeout,
                                            body=body)
        elif method == "POST":
            return self.rest_client.POST(url,
                                         query_params=query_params,
                                         headers=headers,
                                         post_params=post_params,
                                         _preload_content=_preload_content,
                                         _request_timeout=_request_timeout,
                                         body=body)
        elif method == "PUT":
            return self.rest_client.PUT(url,
                                        query_params=query_params,
                                        headers=headers,
                                        post_params=post_params,
                                        _preload_content=_preload_content,
                                        _request_timeout=_request_timeout,
                                        body=body)
        elif method == "PATCH":
            return self.rest_client.PATCH(url,
                                          query_params=query_params,
                                          headers=headers,
                                          post_params=post_params,
                                          _preload_content=_preload_content,
                                          _request_timeout=_request_timeout,
                                          body=body)
        elif method == "DELETE":
            return self.rest_client.DELETE(url,
                                           query_params=query_params,
                                           headers=headers,
                                           _preload_content=_preload_content,
                                           _request_timeout=_request_timeout,
                                           body=body)
        else:
            raise ValueError(
                "http method must be `GET`, `HEAD`, `OPTIONS`,"
                " `POST`, `PATCH`, `PUT` or `DELETE`."
            )

    def parameters_to_tuples(self, params, collection_formats):
        """Get parameters as list of tuples, formatting collections.

        :param params: Parameters as dict or list of two-tuples
        :param dict collection_formats: Parameter collection formats
        :return: Parameters as list of tuples, collections formatted
        """
        new_params = []
        if collection_formats is None:
            collection_formats = {}
        for k, v in params.items() if isinstance(params, dict) else params:  # noqa: E501
            if k in collection_formats:
                collection_format = collection_formats[k]
                if collection_format == 'multi':
                    new_params.extend((k, value) for value in v)
                else:
                    if collection_format == 'ssv':
                        delimiter = ' '
                    elif collection_format == 'tsv':
                        delimiter = '\t'
                    elif collection_format == 'pipes':
                        delimiter = '|'
                    else:  # csv is the default
                        delimiter = ','
                    new_params.append(
                        (k, delimiter.join(str(value) for value in v)))
            else:
                new_params.append((k, v))
        return new_params

    def prepare_post_parameters(self, post_params=None, files=None):
        """Builds form parameters.

        :param post_params: Normal form parameters.
        :param files: File parameters.
        :return: Form parameters with files.
        """
        params = []

        if post_params:
            params = post_params

        if files:
            for k, v in files.items():
                if not v:
                    continue
                file_names = v if type(v) is list else [v]
                for n in file_names:
                    with open(n, 'rb') as f:
                        filename = os.path.basename(f.name)
                        filedata = f.read()
                        mimetype = (mimetypes.guess_type(filename)[0] or
                                    'application/octet-stream')
                        params.append(
                            tuple([k, tuple([filename, filedata, mimetype])]))

        return params

    def select_header_accept(self, accepts):
        """Returns `Accept` based on an array of accepts provided.

        :param accepts: List of headers.
        :return: Accept (e.g. application/json).
        """
        if not accepts:
            return

        accepts = [x.lower() for x in accepts]

        if 'application/json' in accepts:
            return 'application/json'
        else:
            return ', '.join(accepts)

    def select_header_content_type(self, content_types):
        """Returns `Content-Type` based on an array of content_types provided.

        :param content_types: List of content-types.
        :return: Content-Type (e.g. application/json).
        """
        if not content_types:
            return 'application/json'

        content_types = [x.lower() for x in content_types]

        if 'application/json' in content_types or '*/*' in content_types:
            return 'application/json'
        else:
            return content_types[0]

    def update_params_for_auth(self, headers, querys, auth_settings):
        """Updates header and query params based on authentication setting.

        :param headers: Header parameters dict to be updated.
        :param querys: Query parameters tuple list to be updated.
        :param auth_settings: Authentication setting identifiers list.
        """
        if not auth_settings:
            return

        for auth in auth_settings:
            auth_setting = self.configuration.auth_settings().get(auth)
            if auth_setting:
                if not auth_setting['value']:
                    continue
                elif auth_setting['in'] == 'header':
                    headers[auth_setting['key']] = auth_setting['value']
                elif auth_setting['in'] == 'query':
                    querys.append((auth_setting['key'], auth_setting['value']))
                else:
                    raise ValueError(
                        'Authentication token must be in `query` or `header`'
                    )

    def __deserialize_file(self, response):
        """Deserializes body to file

        Saves response body into a file in a temporary folder,
        using the filename from the `Content-Disposition` header if provided.

        :param response:  RESTResponse.
        :return: file path.
        """
        fd, path = tempfile.mkstemp(dir=self.configuration.temp_folder_path)
        os.close(fd)
        os.remove(path)

        content_disposition = response.getheader("Content-Disposition")
        if content_disposition:
            filename = re.search(r'filename=[\'"]?([^\'"\s]+)[\'"]?',
                                 content_disposition).group(1)
            path = os.path.join(os.path.dirname(path), filename)

        with open(path, "w") as f:
            f.write(response.data)

        return path

    def __deserialize_primitive(self, data, klass):
        """Deserializes string to primitive type.

        :param data: str.
        :param klass: class literal.

        :return: int, long, float, str, bool.
        """
        try:
            return klass(data)
        except UnicodeEncodeError:
            return str(data)
        except TypeError:
            return data

    def __deserialize_object(self, value):
        """Return a original value.

        :return: object.
        """
        return value

    def __deserialize_date(self, string):
        """Deserializes string to date.

        :param string: str.
        :return: date.
        """
        try:
            from dateutil.parser import parse
            return parse(string).date()
        except ImportError:
            return string
        except ValueError:
            raise ApiException(
                status=0,
                reason="Failed to parse `{0}` as date object".format(string)
            )

    def __deserialize_datatime(self, string):
        """Deserializes string to datetime.

        The string should be in iso8601 datetime format.

        :param string: str.
        :return: datetime.
        """
        try:
            from dateutil.parser import parse
            return parse(string)
        except ImportError:
            return string
        except ValueError:
            raise ApiException(
                status=0,
                reason=(
                    "Failed to parse `{0}` as datetime object"
                    .format(string)
                )
            )

    def __hasattr(self, object, name):
        return name in object.__class__.__dict__

    def __deserialize_model(self, data, klass):
        """Deserializes list or dict to model.

        :param data: dict, list.
        :param klass: class literal.
        :return: model object.
        """

        if (not klass.swagger_types and
                not self.__hasattr(klass, 'get_real_child_model')):
            return data

        kwargs = {}
        if klass.swagger_types is not None:
            for attr, attr_type in klass.swagger_types.items():
                if (data is not None and
                        klass.attribute_map[attr] in data and
                        isinstance(data, (list, dict))):
                    value = data[klass.attribute_map[attr]]
                    kwargs[attr] = self.__deserialize(value, attr_type)

        instance = klass(**kwargs)

        if (isinstance(instance, dict) and
                klass.swagger_types is not None and
                isinstance(data, dict)):
            for key, value in data.items():
                if key not in klass.swagger_types:
                    instance[key] = value
        if self.__hasattr(instance, 'get_real_child_model'):
            klass_name = instance.get_real_child_model(data)
            if klass_name:
                instance = self.__deserialize(data, klass_name)
        return instance


class ApigatewayApi(object):
    """NOTE: This class is auto generated by the swagger code generator program

    Do not edit the class manually.
    Ref: https://github.com/swagger-api/swagger-codegen
    """

    def __init__(self, api_client=None):
        if api_client is None:
            api_client = ApiClient()
        self.api_client = api_client

    def get_fc_health(self, **kwargs):  # noqa: E501
        """Get health of the API gateway  # noqa: E501

        Retrieves the health of the API gateway  # noqa: E501
        This method makes a synchronous HTTP request by default. To make an
        asynchronous HTTP request, please pass async_req=True
        >>> thread = api.get_fc_health(async_req=True)
        >>> result = thread.get()

        :param async_req bool
        :return: CommonResponseFields
                 If the method is called asynchronously,
                 returns the request thread.
        """
        kwargs['_return_http_data_only'] = True
        if kwargs.get('async_req'):
            return self.get_fc_health_with_http_info(**kwargs)  # noqa: E501
        else:
            (data) = self.get_fc_health_with_http_info(**kwargs)  # noqa: E501
            return data

    def get_fc_health_with_http_info(self, **kwargs):  # noqa: E501
        """Get health of the API gateway  # noqa: E501

        Retrieves the health of the API gateway  # noqa: E501
        This method makes a synchronous HTTP request by default. To make an
        asynchronous HTTP request, please pass async_req=True
        >>> thread = api.get_fc_health_with_http_info(async_req=True)
        >>> result = thread.get()

        :param async_req bool
        :return: CommonResponseFields
                 If the method is called asynchronously,
                 returns the request thread.
        """

        all_params = []  # noqa: E501
        all_params.append('async_req')
        all_params.append('_return_http_data_only')
        all_params.append('_preload_content')
        all_params.append('_request_timeout')

        params = locals()
        for key, val in params['kwargs'].items():
            if key not in all_params:
                raise TypeError(
                    "Got an unexpected keyword argument '%s'"
                    " to method get_fc_health" % key
                )
            params[key] = val
        del params['kwargs']

        collection_formats = {}

        path_params = {}

        query_params = []

        header_params = {}

        form_params = []
        local_var_files = {}

        body_params = None
        # HTTP header `Accept`
        header_params['Accept'] = self.api_client.select_header_accept(
            ['application/json'])  # noqa: E501

        # HTTP header `Content-Type`
        header_params['Content-Type'] = self.api_client.select_header_content_type(  # noqa: E501
            ['application/json'])  # noqa: E501

        # Authentication setting
        auth_settings = ['Basic', 'Bearer']  # noqa: E501

        return self.api_client.call_api(
            '/api_server/health', 'GET',
            path_params,
            query_params,
            header_params,
            body=body_params,
            post_params=form_params,
            files=local_var_files,
            response_type='CommonResponseFields',  # noqa: E501
            auth_settings=auth_settings,
            async_req=params.get('async_req'),
            _return_http_data_only=params.get('_return_http_data_only'),
            _preload_content=params.get('_preload_content', True),
            _request_timeout=params.get('_request_timeout'),
            collection_formats=collection_formats)


class StorageApi(object):
    """NOTE: This class is auto generated by the swagger code generator program

    Do not edit the class manually.
    Ref: https://github.com/swagger-api/swagger-codegen
    """

    def __init__(self, api_client=None):
        if api_client is None:
            api_client = ApiClient()
        self.api_client = api_client

    def attach_volume(self, volume_uuid, body_volume_attach, **kwargs):  # noqa: E501
        """Attach a volume  # noqa: E501

        Attaches a volume to a host server, using the specified transport method  # noqa: E501
        This method makes a synchronous HTTP request by default. To make an
        asynchronous HTTP request, please pass async_req=True
        >>> thread = api.attach_volume(volume_uuid, body_volume_attach, async_req=True)
        >>> result = thread.get()

        :param async_req bool
        :param str volume_uuid: FC assigned volume UUID (required)
        :param BodyVolumeAttach body_volume_attach: (required)
        :return: ResponseDataWithCreateUuid
                 If the method is called asynchronously,
                 returns the request thread.
        """
        kwargs['_return_http_data_only'] = True
        if kwargs.get('async_req'):
            return self.attach_volume_with_http_info(volume_uuid, body_volume_attach, **kwargs)  # noqa: E501
        else:
            (data) = self.attach_volume_with_http_info(volume_uuid, body_volume_attach, **kwargs)  # noqa: E501
            return data

    def attach_volume_with_http_info(self, volume_uuid, body_volume_attach, **kwargs):  # noqa: E501
        """Attach a volume  # noqa: E501

        Attaches a volume to a host server, using the specified transport method  # noqa: E501
        This method makes a synchronous HTTP request by default. To make an
        asynchronous HTTP request, please pass async_req=True
        >>> thread = api.attach_volume_with_http_info(volume_uuid, body_volume_attach, async_req=True)
        >>> result = thread.get()

        :param async_req bool
        :param str volume_uuid: FC assigned volume UUID (required)
        :param BodyVolumeAttach body_volume_attach: (required)
        :return: ResponseDataWithCreateUuid
                 If the method is called asynchronously,
                 returns the request thread.
        """

        all_params = ['volume_uuid', 'body_volume_attach']  # noqa: E501
        all_params.append('async_req')
        all_params.append('_return_http_data_only')
        all_params.append('_preload_content')
        all_params.append('_request_timeout')

        params = locals()
        for key, val in params['kwargs'].items():
            if key not in all_params:
                raise TypeError(
                    "Got an unexpected keyword argument '%s'"
                    " to method attach_volume" % key
                )
            params[key] = val
        del params['kwargs']
        # verify the required parameter 'volume_uuid' is set
        if self.api_client.client_side_validation and ('volume_uuid' not in params or  # noqa: E501
                                                       params['volume_uuid'] is None):  # noqa: E501
            raise ValueError("Missing the required parameter `volume_uuid` when calling `attach_volume`")  # noqa: E501
        # verify the required parameter 'body_volume_attach' is set
        if self.api_client.client_side_validation and ('body_volume_attach' not in params or  # noqa: E501
                                                       params['body_volume_attach'] is None):  # noqa: E501
            raise ValueError("Missing the required parameter `body_volume_attach` when calling `attach_volume`")  # noqa: E501

        if self.api_client.client_side_validation and ('volume_uuid' in params and not re.search(r'^[A-Fa-f0-9\\-]+$', params['volume_uuid'])):  # noqa: E501
            raise ValueError("Invalid value for parameter `volume_uuid` when calling `attach_volume`, must conform to the pattern `/^[A-Fa-f0-9\\-]+$/`")  # noqa: E501
        collection_formats = {}

        path_params = {}
        if 'volume_uuid' in params:
            path_params['volume_uuid'] = params['volume_uuid']  # noqa: E501

        query_params = []

        header_params = {}

        form_params = []
        local_var_files = {}

        body_params = None
        if 'body_volume_attach' in params:
            body_params = params['body_volume_attach']
        # HTTP header `Accept`
        header_params['Accept'] = self.api_client.select_header_accept(
            ['application/json'])  # noqa: E501

        # HTTP header `Content-Type`
        header_params['Content-Type'] = self.api_client.select_header_content_type(  # noqa: E501
            ['application/json'])  # noqa: E501

        # Authentication setting
        auth_settings = ['Basic', 'Bearer']  # noqa: E501

        return self.api_client.call_api(
            '/storage/volumes/{volume_uuid}/ports', 'POST',
            path_params,
            query_params,
            header_params,
            body=body_params,
            post_params=form_params,
            files=local_var_files,
            response_type='ResponseDataWithCreateUuid',  # noqa: E501
            auth_settings=auth_settings,
            async_req=params.get('async_req'),
            _return_http_data_only=params.get('_return_http_data_only'),
            _preload_content=params.get('_preload_content', True),
            _request_timeout=params.get('_request_timeout'),
            collection_formats=collection_formats)

    def create_snapshot(self, volume_uuid, body_volume_snapshot_create, **kwargs):  # noqa: E501
        """Create a new snapshot of a volume  # noqa: E501

        Create new snapshot volume using the specified parameters  # noqa: E501
        This method makes a synchronous HTTP request by default. To make an
        asynchronous HTTP request, please pass async_req=True
        >>> thread = api.create_snapshot(volume_uuid, body_volume_snapshot_create, async_req=True)
        >>> result = thread.get()

        :param async_req bool
        :param str volume_uuid: FC assigned volume UUID (required)
        :param BodyVolumeSnapshotCreate body_volume_snapshot_create: (required)
        :return: ResponseDataWithCreateUuid
                 If the method is called asynchronously,
                 returns the request thread.
        """
        kwargs['_return_http_data_only'] = True
        if kwargs.get('async_req'):
            return self.create_snapshot_with_http_info(volume_uuid, body_volume_snapshot_create, **kwargs)  # noqa: E501
        else:
            (data) = self.create_snapshot_with_http_info(volume_uuid, body_volume_snapshot_create, **kwargs)  # noqa: E501
            return data

    def create_snapshot_with_http_info(self, volume_uuid, body_volume_snapshot_create, **kwargs):  # noqa: E501
        """Create a new snapshot of a volume  # noqa: E501

        Create new snapshot volume using the specified parameters  # noqa: E501
        This method makes a synchronous HTTP request by default. To make an
        asynchronous HTTP request, please pass async_req=True
        >>> thread = api.create_snapshot_with_http_info(volume_uuid, body_volume_snapshot_create, async_req=True)
        >>> result = thread.get()

        :param async_req bool
        :param str volume_uuid: FC assigned volume UUID (required)
        :param BodyVolumeSnapshotCreate body_volume_snapshot_create: (required)
        :return: ResponseDataWithCreateUuid
                 If the method is called asynchronously,
                 returns the request thread.
        """

        all_params = ['volume_uuid', 'body_volume_snapshot_create']  # noqa: E501
        all_params.append('async_req')
        all_params.append('_return_http_data_only')
        all_params.append('_preload_content')
        all_params.append('_request_timeout')

        params = locals()
        for key, val in params['kwargs'].items():
            if key not in all_params:
                raise TypeError(
                    "Got an unexpected keyword argument '%s'"
                    " to method create_snapshot" % key
                )
            params[key] = val
        del params['kwargs']
        # verify the required parameter 'volume_uuid' is set
        if self.api_client.client_side_validation and ('volume_uuid' not in params or  # noqa: E501
                                                       params['volume_uuid'] is None):  # noqa: E501
            raise ValueError("Missing the required parameter `volume_uuid` when calling `create_snapshot`")  # noqa: E501
        # verify the required parameter 'body_volume_snapshot_create' is set
        if self.api_client.client_side_validation and ('body_volume_snapshot_create' not in params or  # noqa: E501
                                                       params['body_volume_snapshot_create'] is None):  # noqa: E501
            raise ValueError("Missing the required parameter `body_volume_snapshot_create` when calling `create_snapshot`")  # noqa: E501

        if self.api_client.client_side_validation and ('volume_uuid' in params and not re.search(r'^[A-Fa-f0-9\\-]+$', params['volume_uuid'])):  # noqa: E501
            raise ValueError("Invalid value for parameter `volume_uuid` when calling `create_snapshot`, must conform to the pattern `/^[A-Fa-f0-9\\-]+$/`")  # noqa: E501
        collection_formats = {}

        path_params = {}
        if 'volume_uuid' in params:
            path_params['volume_uuid'] = params['volume_uuid']  # noqa: E501

        query_params = []

        header_params = {}

        form_params = []
        local_var_files = {}

        body_params = None
        if 'body_volume_snapshot_create' in params:
            body_params = params['body_volume_snapshot_create']
        # HTTP header `Accept`
        header_params['Accept'] = self.api_client.select_header_accept(
            ['application/json'])  # noqa: E501

        # HTTP header `Content-Type`
        header_params['Content-Type'] = self.api_client.select_header_content_type(  # noqa: E501
            ['application/json'])  # noqa: E501

        # Authentication setting
        auth_settings = ['Basic', 'Bearer']  # noqa: E501

        return self.api_client.call_api(
            '/storage/volumes/{volume_uuid}/snapshots', 'POST',
            path_params,
            query_params,
            header_params,
            body=body_params,
            post_params=form_params,
            files=local_var_files,
            response_type='ResponseDataWithCreateUuid',  # noqa: E501
            auth_settings=auth_settings,
            async_req=params.get('async_req'),
            _return_http_data_only=params.get('_return_http_data_only'),
            _preload_content=params.get('_preload_content', True),
            _request_timeout=params.get('_request_timeout'),
            collection_formats=collection_formats)

    def delete_snapshot(self, snapshot_uuid, **kwargs):  # noqa: E501
        """Delete snapshot  # noqa: E501

        Deletes the snapshot with specified uuid  # noqa: E501
        This method makes a synchronous HTTP request by default. To make an
        asynchronous HTTP request, please pass async_req=True
        >>> thread = api.delete_snapshot(snapshot_uuid, async_req=True)
        >>> result = thread.get()

        :param async_req bool
        :param str snapshot_uuid: FC assigned snapshot UUID (required)
        :return: SuccessResponseFields
                 If the method is called asynchronously,
                 returns the request thread.
        """
        kwargs['_return_http_data_only'] = True
        if kwargs.get('async_req'):
            return self.delete_snapshot_with_http_info(snapshot_uuid, **kwargs)  # noqa: E501
        else:
            (data) = self.delete_snapshot_with_http_info(snapshot_uuid, **kwargs)  # noqa: E501
            return data

    def delete_snapshot_with_http_info(self, snapshot_uuid, **kwargs):  # noqa: E501
        """Delete snapshot  # noqa: E501

        Deletes the snapshot with specified uuid  # noqa: E501
        This method makes a synchronous HTTP request by default. To make an
        asynchronous HTTP request, please pass async_req=True
        >>> thread = api.delete_snapshot_with_http_info(snapshot_uuid, async_req=True)
        >>> result = thread.get()

        :param async_req bool
        :param str snapshot_uuid: FC assigned snapshot UUID (required)
        :return: SuccessResponseFields
                 If the method is called asynchronously,
                 returns the request thread.
        """

        all_params = ['snapshot_uuid']  # noqa: E501
        all_params.append('async_req')
        all_params.append('_return_http_data_only')
        all_params.append('_preload_content')
        all_params.append('_request_timeout')

        params = locals()
        for key, val in params['kwargs'].items():
            if key not in all_params:
                raise TypeError(
                    "Got an unexpected keyword argument '%s'"
                    " to method delete_snapshot" % key
                )
            params[key] = val
        del params['kwargs']
        # verify the required parameter 'snapshot_uuid' is set
        if ('snapshot_uuid' not in params or
                params['snapshot_uuid'] is None):
            raise ValueError("Missing the required parameter `snapshot_uuid` when calling `delete_snapshot`")  # noqa: E501

        if 'snapshot_uuid' in params and not re.search(r'^[A-Fa-f0-9\\-]+$', params['snapshot_uuid']):  # noqa: E501
            raise ValueError("Invalid value for parameter `snapshot_uuid` when calling `delete_snapshot`, must conform to the pattern `/^[A-Fa-f0-9\\-]+$/`")  # noqa: E501
        collection_formats = {}

        path_params = {}
        if 'snapshot_uuid' in params:
            path_params['snapshot_uuid'] = params['snapshot_uuid']  # noqa: E501

        query_params = []

        header_params = {}

        form_params = []
        local_var_files = {}

        body_params = None
        # HTTP header `Accept`
        header_params['Accept'] = self.api_client.select_header_accept(
            ['application/json'])  # noqa: E501

        # HTTP header `Content-Type`
        header_params['Content-Type'] = self.api_client.select_header_content_type(  # noqa: E501
            ['application/json'])  # noqa: E501

        # Authentication setting
        auth_settings = ['Basic', 'Bearer']  # noqa: E501

        return self.api_client.call_api(
            '/storage/snapshots/{snapshot_uuid}', 'DELETE',
            path_params,
            query_params,
            header_params,
            body=body_params,
            post_params=form_params,
            files=local_var_files,
            response_type='SuccessResponseFields',  # noqa: E501
            auth_settings=auth_settings,
            async_req=params.get('async_req'),
            _return_http_data_only=params.get('_return_http_data_only'),
            _preload_content=params.get('_preload_content', True),
            _request_timeout=params.get('_request_timeout'),
            collection_formats=collection_formats)

    def create_volume(self, body_volume_intent_create, **kwargs):  # noqa: E501
        """Create a new volume  # noqa: E501

        Creates new volume using the specified parameters  # noqa: E501
        This method makes a synchronous HTTP request by default. To make an
        asynchronous HTTP request, please pass async_req=True
        >>> thread = api.create_volume(body_volume_intent_create, async_req=True)
        >>> result = thread.get()

        :param async_req bool
        :param BodyVolumeIntentCreate body_volume_intent_create: (required)
        :return: ResponseDataWithCreateUuid
                 If the method is called asynchronously,
                 returns the request thread.
        """
        kwargs['_return_http_data_only'] = True
        if kwargs.get('async_req'):
            return self.create_volume_with_http_info(body_volume_intent_create, **kwargs)  # noqa: E501
        else:
            (data) = self.create_volume_with_http_info(body_volume_intent_create, **kwargs)  # noqa: E501
            return data

    def create_volume_with_http_info(self, body_volume_intent_create, **kwargs):  # noqa: E501
        """Create a new volume  # noqa: E501

        Creates new volume using the specified parameters  # noqa: E501
        This method makes a synchronous HTTP request by default. To make an
        asynchronous HTTP request, please pass async_req=True
        >>> thread = api.create_volume_with_http_info(body_volume_intent_create, async_req=True)
        >>> result = thread.get()

        :param async_req bool
        :param BodyVolumeIntentCreate body_volume_intent_create: (required)
        :return: ResponseDataWithCreateUuid
                 If the method is called asynchronously,
                 returns the request thread.
        """

        all_params = ['body_volume_intent_create']  # noqa: E501
        all_params.append('async_req')
        all_params.append('_return_http_data_only')
        all_params.append('_preload_content')
        all_params.append('_request_timeout')

        params = locals()
        for key, val in params['kwargs'].items():
            if key not in all_params:
                raise TypeError(
                    "Got an unexpected keyword argument '%s'"
                    " to method create_volume" % key
                )
            params[key] = val
        del params['kwargs']
        # verify the required parameter 'body_volume_intent_create' is set
        if self.api_client.client_side_validation and ('body_volume_intent_create' not in params or  # noqa: E501
                                                       params['body_volume_intent_create'] is None):  # noqa: E501
            raise ValueError("Missing the required parameter `body_volume_intent_create` when calling `create_volume`")  # noqa: E501

        collection_formats = {}

        path_params = {}

        query_params = []

        header_params = {}

        form_params = []
        local_var_files = {}

        body_params = None
        if 'body_volume_intent_create' in params:
            body_params = params['body_volume_intent_create']
        # HTTP header `Accept`
        header_params['Accept'] = self.api_client.select_header_accept(
            ['application/json'])  # noqa: E501

        # HTTP header `Content-Type`
        header_params['Content-Type'] = self.api_client.select_header_content_type(  # noqa: E501
            ['application/json'])  # noqa: E501

        # Authentication setting
        auth_settings = ['Basic', 'Bearer']  # noqa: E501

        return self.api_client.call_api(
            '/storage/volumes', 'POST',
            path_params,
            query_params,
            header_params,
            body=body_params,
            post_params=form_params,
            files=local_var_files,
            response_type='ResponseDataWithCreateUuid',  # noqa: E501
            auth_settings=auth_settings,
            async_req=params.get('async_req'),
            _return_http_data_only=params.get('_return_http_data_only'),
            _preload_content=params.get('_preload_content', True),
            _request_timeout=params.get('_request_timeout'),
            collection_formats=collection_formats)

    def create_volume_copy_task(self, body_create_volume_copy_task, **kwargs):  # noqa: E501
        """Create a task to copy a volume  # noqa: E501

        Creates a task to copy a specified volume  # noqa: E501
        This method makes a synchronous HTTP request by default. To make an
        asynchronous HTTP request, please pass async_req=True
        >>> thread = api.create_volume_copy_task(body_create_volume_copy_task, async_req=True)
        >>> result = thread.get()

        :param async_req bool
        :param BodyCreateVolumeCopyTask body_create_volume_copy_task: (required)
        :return: ResponseCreateVolumeCopyTask
                 If the method is called asynchronously,
                 returns the request thread.
        """
        kwargs['_return_http_data_only'] = True
        if kwargs.get('async_req'):
            return self.create_volume_copy_task_with_http_info(body_create_volume_copy_task, **kwargs)  # noqa: E501
        else:
            (data) = self.create_volume_copy_task_with_http_info(body_create_volume_copy_task, **kwargs)  # noqa: E501
            return data

    def create_volume_copy_task_with_http_info(self, body_create_volume_copy_task, **kwargs):  # noqa: E501
        """Create a task to copy a volume  # noqa: E501

        Creates a task to copy a specified volume  # noqa: E501
        This method makes a synchronous HTTP request by default. To make an
        asynchronous HTTP request, please pass async_req=True
        >>> thread = api.create_volume_copy_task_with_http_info(body_create_volume_copy_task, async_req=True)
        >>> result = thread.get()

        :param async_req bool
        :param BodyCreateVolumeCopyTask body_create_volume_copy_task: (required)
        :return: ResponseCreateVolumeCopyTask
                 If the method is called asynchronously,
                 returns the request thread.
        """

        all_params = ['body_create_volume_copy_task']  # noqa: E501
        all_params.append('async_req')
        all_params.append('_return_http_data_only')
        all_params.append('_preload_content')
        all_params.append('_request_timeout')

        params = locals()
        for key, val in params['kwargs'].items():
            if key not in all_params:
                raise TypeError(
                    "Got an unexpected keyword argument '%s'"
                    " to method create_volume_copy_task" % key
                )
            params[key] = val
        del params['kwargs']
        # verify the required parameter 'body_create_volume_copy_task' is set
        if ('body_create_volume_copy_task' not in params or
                params['body_create_volume_copy_task'] is None):
            raise ValueError("Missing the required parameter `body_create_volume_copy_task` when calling `create_volume_copy_task`")  # noqa: E501

        collection_formats = {}

        path_params = {}

        query_params = []

        header_params = {}

        form_params = []
        local_var_files = {}

        body_params = None
        if 'body_create_volume_copy_task' in params:
            body_params = params['body_create_volume_copy_task']
        # HTTP header `Accept`
        header_params['Accept'] = self.api_client.select_header_accept(
            ['application/json'])  # noqa: E501

        # HTTP header `Content-Type`
        header_params['Content-Type'] = self.api_client.select_header_content_type(  # noqa: E501
            ['application/json'])  # noqa: E501

        # Authentication setting
        auth_settings = ['Basic', 'Bearer']  # noqa: E501

        return self.api_client.call_api(
            '/storage/volumes/copy', 'POST',
            path_params,
            query_params,
            header_params,
            body=body_params,
            post_params=form_params,
            files=local_var_files,
            response_type='ResponseCreateVolumeCopyTask',  # noqa: E501
            auth_settings=auth_settings,
            async_req=params.get('async_req'),
            _return_http_data_only=params.get('_return_http_data_only'),
            _preload_content=params.get('_preload_content', True),
            _request_timeout=params.get('_request_timeout'),
            collection_formats=collection_formats)

    def get_volume_copy_task(self, task_uuid, **kwargs):  # noqa: E501
        """Get the status of a task to copy a volume  # noqa: E501

        Retrieves the status of the specified task to copy a volume  # noqa: E501
        This method makes a synchronous HTTP request by default. To make an
        asynchronous HTTP request, please pass async_req=True
        >>> thread = api.get_volume_copy_task(task_uuid, async_req=True)
        >>> result = thread.get()

        :param async_req bool
        :param str task_uuid: FC assigned task UUID (required)
        :return: ResponseGetVolumeCopyTask
                 If the method is called asynchronously,
                 returns the request thread.
        """
        kwargs['_return_http_data_only'] = True
        if kwargs.get('async_req'):
            return self.get_volume_copy_task_with_http_info(task_uuid, **kwargs)  # noqa: E501
        else:
            (data) = self.get_volume_copy_task_with_http_info(task_uuid, **kwargs)  # noqa: E501
            return data

    def get_volume_copy_task_with_http_info(self, task_uuid, **kwargs):  # noqa: E501
        """Get the status of a task to copy a volume  # noqa: E501

        Retrieves the status of the specified task to copy a volume  # noqa: E501
        This method makes a synchronous HTTP request by default. To make an
        asynchronous HTTP request, please pass async_req=True
        >>> thread =
        api.get_volume_copy_task_with_http_info(task_uuid, async_req=True)
        >>> result = thread.get()

        :param async_req bool
        :param str task_uuid: FC assigned task UUID (required)
        :return: ResponseGetVolumeCopyTask
                 If the method is called asynchronously,
                 returns the request thread.
        """

        all_params = ['task_uuid']  # noqa: E501
        all_params.append('async_req')
        all_params.append('_return_http_data_only')
        all_params.append('_preload_content')
        all_params.append('_request_timeout')

        params = locals()
        for key, val in params['kwargs'].items():
            if key not in all_params:
                raise TypeError(
                    "Got an unexpected keyword argument '%s'"
                    " to method get_volume_copy_task" % key
                )
            params[key] = val
        del params['kwargs']
        # verify the required parameter 'task_uuid' is set
        if ('task_uuid' not in params or
                params['task_uuid'] is None):
            raise ValueError("Missing the required parameter `task_uuid` when calling `get_volume_copy_task`")  # noqa: E501

        collection_formats = {}

        path_params = {}
        if 'task_uuid' in params:
            path_params['task_uuid'] = params['task_uuid']  # noqa: E501

        query_params = []

        header_params = {}

        form_params = []
        local_var_files = {}

        body_params = None
        # HTTP header `Accept`
        header_params['Accept'] = self.api_client.select_header_accept(
            ['application/json'])  # noqa: E501

        # HTTP header `Content-Type`
        header_params['Content-Type'] = self.api_client.select_header_content_type(  # noqa: E501
            ['application/json'])  # noqa: E501

        # Authentication setting
        auth_settings = ['Basic', 'Bearer']  # noqa: E501

        return self.api_client.call_api(
            '/storage/volumes/copy/{task_uuid}', 'GET',
            path_params,
            query_params,
            header_params,
            body=body_params,
            post_params=form_params,
            files=local_var_files,
            response_type='ResponseGetVolumeCopyTask',  # noqa: E501
            auth_settings=auth_settings,
            async_req=params.get('async_req'),
            _return_http_data_only=params.get('_return_http_data_only'),
            _preload_content=params.get('_preload_content', True),
            _request_timeout=params.get('_request_timeout'),
            collection_formats=collection_formats)

    def delete_volume_copy_task(self, task_uuid, **kwargs):  # noqa: E501
        """Delete a task to copy a volume  # noqa: E501

        Deletes the specified task to copy a volume  # noqa: E501
        This method makes a synchronous HTTP request by default. To make an
        asynchronous HTTP request, please pass async_req=True
        >>> thread = api.delete_volume_copy_task(task_uuid, async_req=True)
        >>> result = thread.get()

        :param async_req bool
        :param str task_uuid: FC assigned task UUID (required)
        :return: SuccessResponseFields
                 If the method is called asynchronously,
                 returns the request thread.
        """
        kwargs['_return_http_data_only'] = True
        if kwargs.get('async_req'):
            return self.delete_volume_copy_task_with_http_info(task_uuid, **kwargs)  # noqa: E501
        else:
            (data) = self.delete_volume_copy_task_with_http_info(task_uuid, **kwargs)  # noqa: E501
            return data

    def delete_volume_copy_task_with_http_info(self, task_uuid, **kwargs):  # noqa: E501
        """Delete a task to copy a volume  # noqa: E501

        Deletes the specified task to copy a volume  # noqa: E501
        This method makes a synchronous HTTP request by default. To make an
        asynchronous HTTP request, please pass async_req=True
        >>> thread = api.delete_volume_copy_task_with_http_info(task_uuid, async_req=True) # noqa: E501
        >>> result = thread.get()

        :param async_req bool
        :param str task_uuid: FC assigned task UUID (required)
        :return: SuccessResponseFields
                 If the method is called asynchronously,
                 returns the request thread.
        """

        all_params = ['task_uuid']  # noqa: E501
        all_params.append('async_req')
        all_params.append('_return_http_data_only')
        all_params.append('_preload_content')
        all_params.append('_request_timeout')

        params = locals()
        for key, val in params['kwargs'].items():
            if key not in all_params:
                raise TypeError(
                    "Got an unexpected keyword argument '%s'"
                    " to method delete_volume_copy_task" % key
                )
            params[key] = val
        del params['kwargs']
        # verify the required parameter 'task_uuid' is set
        if ('task_uuid' not in params or
                params['task_uuid'] is None):
            raise ValueError("Missing the required parameter `task_uuid` when calling `delete_volume_copy_task`")  # noqa: E501

        collection_formats = {}

        path_params = {}
        if 'task_uuid' in params:
            path_params['task_uuid'] = params['task_uuid']  # noqa: E501

        query_params = []

        header_params = {}

        form_params = []
        local_var_files = {}

        body_params = None
        # HTTP header `Accept`
        header_params['Accept'] = self.api_client.select_header_accept(
            ['application/json'])  # noqa: E501

        # HTTP header `Content-Type`
        header_params['Content-Type'] = self.api_client.select_header_content_type(  # noqa: E501
            ['application/json'])  # noqa: E501

        # Authentication setting
        auth_settings = ['Basic', 'Bearer']  # noqa: E501

        return self.api_client.call_api(
            '/storage/volumes/copy/{task_uuid}', 'DELETE',
            path_params,
            query_params,
            header_params,
            body=body_params,
            post_params=form_params,
            files=local_var_files,
            response_type='SuccessResponseFields',  # noqa: E501
            auth_settings=auth_settings,
            async_req=params.get('async_req'),
            _return_http_data_only=params.get('_return_http_data_only'),
            _preload_content=params.get('_preload_content', True),
            _request_timeout=params.get('_request_timeout'),
            collection_formats=collection_formats)

    def delete_port(self, port_uuid, **kwargs):  # noqa: E501
        """Delete a port  # noqa: E501

        Deletes the specified port  # noqa: E501
        This method makes a synchronous HTTP request by default. To make an
        asynchronous HTTP request, please pass async_req=True
        >>> thread = api.delete_port(port_uuid, async_req=True)
        >>> result = thread.get()

        :param async_req bool
        :param str port_uuid: FC assigned port UUID (required)
        :param bool force_clean:
        :return: CommonResponseFields
                 If the method is called asynchronously,
                 returns the request thread.
        """
        kwargs['_return_http_data_only'] = True
        if kwargs.get('async_req'):
            return self.delete_port_with_http_info(port_uuid, **kwargs)  # noqa: E501
        else:
            (data) = self.delete_port_with_http_info(port_uuid, **kwargs)  # noqa: E501
            return data

    def delete_port_with_http_info(self, port_uuid, **kwargs):  # noqa: E501
        """Delete a port  # noqa: E501

        Deletes the specified port  # noqa: E501
        This method makes a synchronous HTTP request by default. To make an
        asynchronous HTTP request, please pass async_req=True
        >>> thread = api.delete_port_with_http_info(port_uuid, async_req=True)
        >>> result = thread.get()

        :param async_req bool
        :param str port_uuid: FC assigned port UUID (required)
        :param bool force_clean:
        :return: CommonResponseFields
                 If the method is called asynchronously,
                 returns the request thread.
        """

        all_params = ['port_uuid', 'force_clean']  # noqa: E501
        all_params.append('async_req')
        all_params.append('_return_http_data_only')
        all_params.append('_preload_content')
        all_params.append('_request_timeout')

        params = locals()
        for key, val in params['kwargs'].items():
            if key not in all_params:
                raise TypeError(
                    "Got an unexpected keyword argument '%s'"
                    " to method delete_port" % key
                )
            params[key] = val
        del params['kwargs']
        # verify the required parameter 'port_uuid' is set
        if self.api_client.client_side_validation and ('port_uuid' not in params or  # noqa: E501
                                                       params['port_uuid'] is None):  # noqa: E501
            raise ValueError("Missing the required parameter `port_uuid` when calling `delete_port`")  # noqa: E501

        if self.api_client.client_side_validation and ('port_uuid' in params and not re.search(r'^[A-Fa-f0-9\\-]+$', params['port_uuid'])):  # noqa: E501
            raise ValueError("Invalid value for parameter `port_uuid` when calling `delete_port`, must conform to the pattern `/^[A-Fa-f0-9\\-]+$/`")  # noqa: E501
        collection_formats = {}

        path_params = {}
        if 'port_uuid' in params:
            path_params['port_uuid'] = params['port_uuid']  # noqa: E501

        query_params = []
        if 'force_clean' in params:
            query_params.append(('force_clean', params['force_clean']))  # noqa: E501

        header_params = {}

        form_params = []
        local_var_files = {}

        body_params = None
        # HTTP header `Accept`
        header_params['Accept'] = self.api_client.select_header_accept(
            ['application/json'])  # noqa: E501

        # HTTP header `Content-Type`
        header_params['Content-Type'] = self.api_client.select_header_content_type(  # noqa: E501
            ['application/json'])  # noqa: E501

        # Authentication setting
        auth_settings = ['Basic', 'Bearer']  # noqa: E501

        return self.api_client.call_api(
            '/storage/ports/{port_uuid}', 'DELETE',
            path_params,
            query_params,
            header_params,
            body=body_params,
            post_params=form_params,
            files=local_var_files,
            response_type='CommonResponseFields',  # noqa: E501
            auth_settings=auth_settings,
            async_req=params.get('async_req'),
            _return_http_data_only=params.get('_return_http_data_only'),
            _preload_content=params.get('_preload_content', True),
            _request_timeout=params.get('_request_timeout'),
            collection_formats=collection_formats)

    def delete_volume(self, volume_uuid, **kwargs):  # noqa: E501
        """Delete a volume  # noqa: E501

        Deletes the specified volume  # noqa: E501
        This method makes a synchronous HTTP request by default. To make an
        asynchronous HTTP request, please pass async_req=True
        >>> thread = api.delete_volume(volume_uuid, async_req=True)
        >>> result = thread.get()

        :param async_req bool
        :param str volume_uuid: FC assigned volume UUID (required)
        :return: SuccessResponseFields
                 If the method is called asynchronously,
                 returns the request thread.
        """
        kwargs['_return_http_data_only'] = True
        if kwargs.get('async_req'):
            return self.delete_volume_with_http_info(volume_uuid, **kwargs)  # noqa: E501
        else:
            (data) = self.delete_volume_with_http_info(volume_uuid, **kwargs)  # noqa: E501
            return data

    def delete_volume_with_http_info(self, volume_uuid, **kwargs):  # noqa: E501
        """Delete a volume  # noqa: E501

        Deletes the specified volume  # noqa: E501
        This method makes a synchronous HTTP request by default. To make an
        asynchronous HTTP request, please pass async_req=True
        >>> thread = api.delete_volume_with_http_info(volume_uuid, async_req=True)
        >>> result = thread.get()

        :param async_req bool
        :param str volume_uuid: FC assigned volume UUID (required)
        :return: SuccessResponseFields
                 If the method is called asynchronously,
                 returns the request thread.
        """

        all_params = ['volume_uuid']  # noqa: E501
        all_params.append('async_req')
        all_params.append('_return_http_data_only')
        all_params.append('_preload_content')
        all_params.append('_request_timeout')

        params = locals()
        for key, val in params['kwargs'].items():
            if key not in all_params:
                raise TypeError(
                    "Got an unexpected keyword argument '%s'"
                    " to method delete_volume" % key
                )
            params[key] = val
        del params['kwargs']
        # verify the required parameter 'volume_uuid' is set
        if self.api_client.client_side_validation and ('volume_uuid' not in params or  # noqa: E501
                                                       params['volume_uuid'] is None):  # noqa: E501
            raise ValueError("Missing the required parameter `volume_uuid` when calling `delete_volume`")  # noqa: E501

        if self.api_client.client_side_validation and ('volume_uuid' in params and not re.search(r'^[A-Fa-f0-9\\-]+$', params['volume_uuid'])):  # noqa: E501
            raise ValueError("Invalid value for parameter `volume_uuid` when calling `delete_volume`, must conform to the pattern `/^[A-Fa-f0-9\\-]+$/`")  # noqa: E501
        collection_formats = {}

        path_params = {}
        if 'volume_uuid' in params:
            path_params['volume_uuid'] = params['volume_uuid']  # noqa: E501

        query_params = []

        header_params = {}

        form_params = []
        local_var_files = {}

        body_params = None
        # HTTP header `Accept`
        header_params['Accept'] = self.api_client.select_header_accept(
            ['application/json'])  # noqa: E501

        # HTTP header `Content-Type`
        header_params['Content-Type'] = self.api_client.select_header_content_type(  # noqa: E501
            ['application/json'])  # noqa: E501

        # Authentication setting
        auth_settings = ['Basic', 'Bearer']  # noqa: E501

        return self.api_client.call_api(
            '/storage/volumes/{volume_uuid}', 'DELETE',
            path_params,
            query_params,
            header_params,
            body=body_params,
            post_params=form_params,
            files=local_var_files,
            response_type='SuccessResponseFields',  # noqa: E501
            auth_settings=auth_settings,
            async_req=params.get('async_req'),
            _return_http_data_only=params.get('_return_http_data_only'),
            _preload_content=params.get('_preload_content', True),
            _request_timeout=params.get('_request_timeout'),
            collection_formats=collection_formats)

    def get_port(self, port_uuid, **kwargs):  # noqa: E501
        """Get port properties  # noqa: E501

        Retrieves properties of the specified port  # noqa: E501
        This method makes a synchronous HTTP request by default. To make an
        asynchronous HTTP request, please pass async_req=True
        >>> thread = api.get_port(port_uuid, async_req=True)
        >>> result = thread.get()

        :param async_req bool
        :param str port_uuid: FC assigned port UUID (required)
        :return: ResponseDataWithSinglePort
                 If the method is called asynchronously,
                 returns the request thread.
        """
        kwargs['_return_http_data_only'] = True
        if kwargs.get('async_req'):
            return self.get_port_with_http_info(port_uuid, **kwargs)  # noqa: E501
        else:
            (data) = self.get_port_with_http_info(port_uuid, **kwargs)  # noqa: E501
            return data

    def get_port_with_http_info(self, port_uuid, **kwargs):  # noqa: E501
        """Get port properties  # noqa: E501

        Retrieves properties of the specified port  # noqa: E501
        This method makes a synchronous HTTP request by default. To make an
        asynchronous HTTP request, please pass async_req=True
        >>> thread = api.get_port_with_http_info(port_uuid, async_req=True)
        >>> result = thread.get()

        :param async_req bool
        :param str port_uuid: FC assigned port UUID (required)
        :return: ResponseDataWithSinglePort
                 If the method is called asynchronously,
                 returns the request thread.
        """

        all_params = ['port_uuid']  # noqa: E501
        all_params.append('async_req')
        all_params.append('_return_http_data_only')
        all_params.append('_preload_content')
        all_params.append('_request_timeout')

        params = locals()
        for key, val in params['kwargs'].items():
            if key not in all_params:
                raise TypeError(
                    "Got an unexpected keyword argument '%s'"
                    " to method get_port" % key
                )
            params[key] = val
        del params['kwargs']
        # verify the required parameter 'port_uuid' is set
        if self.api_client.client_side_validation and ('port_uuid' not in params or  # noqa: E501
                                                       params['port_uuid'] is None):  # noqa: E501
            raise ValueError("Missing the required parameter `port_uuid` when calling `get_port`")  # noqa: E501

        if self.api_client.client_side_validation and ('port_uuid' in params and not re.search(r'^[A-Fa-f0-9\\-]+$', params['port_uuid'])):  # noqa: E501
            raise ValueError("Invalid value for parameter `port_uuid` when calling `get_port`, must conform to the pattern `/^[A-Fa-f0-9\\-]+$/`")  # noqa: E501
        collection_formats = {}

        path_params = {}
        if 'port_uuid' in params:
            path_params['port_uuid'] = params['port_uuid']  # noqa: E501

        query_params = []

        header_params = {}

        form_params = []
        local_var_files = {}

        body_params = None
        # HTTP header `Accept`
        header_params['Accept'] = self.api_client.select_header_accept(
            ['application/json'])  # noqa: E501

        # HTTP header `Content-Type`
        header_params['Content-Type'] = self.api_client.select_header_content_type(  # noqa: E501
            ['application/json'])  # noqa: E501

        # Authentication setting
        auth_settings = ['Basic', 'Bearer']  # noqa: E501

        return self.api_client.call_api(
            '/storage/ports/{port_uuid}', 'GET',
            path_params,
            query_params,
            header_params,
            body=body_params,
            post_params=form_params,
            files=local_var_files,
            response_type='ResponseDataWithSinglePort',  # noqa: E501
            auth_settings=auth_settings,
            async_req=params.get('async_req'),
            _return_http_data_only=params.get('_return_http_data_only'),
            _preload_content=params.get('_preload_content', True),
            _request_timeout=params.get('_request_timeout'),
            collection_formats=collection_formats)

    def get_volume(self, volume_uuid, **kwargs):  # noqa: E501
        """Get properties of a volume  # noqa: E501

        Retrieves properties of the specified volume  # noqa: E501
        This method makes a synchronous HTTP request by default. To make an
        asynchronous HTTP request, please pass async_req=True
        >>> thread = api.get_volume(volume_uuid, async_req=True)
        >>> result = thread.get()

        :param async_req bool
        :param str volume_uuid: FC assigned volume UUID (required)
        :return: ResponseDataWithSingleVolume
                 If the method is called asynchronously,
                 returns the request thread.
        """
        kwargs['_return_http_data_only'] = True
        if kwargs.get('async_req'):
            return self.get_volume_with_http_info(volume_uuid, **kwargs)  # noqa: E501
        else:
            (data) = self.get_volume_with_http_info(volume_uuid, **kwargs)  # noqa: E501
            return data

    def get_volume_with_http_info(self, volume_uuid, **kwargs):  # noqa: E501
        """Get properties of a volume  # noqa: E501

        Retrieves properties of the specified volume  # noqa: E501
        This method makes a synchronous HTTP request by default. To make an
        asynchronous HTTP request, please pass async_req=True
        >>> thread = api.get_volume_with_http_info(volume_uuid, async_req=True)
        >>> result = thread.get()

        :param async_req bool
        :param str volume_uuid: FC assigned volume UUID (required)
        :return: ResponseDataWithSingleVolume
                 If the method is called asynchronously,
                 returns the request thread.
        """

        all_params = ['volume_uuid']  # noqa: E501
        all_params.append('async_req')
        all_params.append('_return_http_data_only')
        all_params.append('_preload_content')
        all_params.append('_request_timeout')

        params = locals()
        for key, val in params['kwargs'].items():
            if key not in all_params:
                raise TypeError(
                    "Got an unexpected keyword argument '%s'"
                    " to method get_volume" % key
                )
            params[key] = val
        del params['kwargs']
        # verify the required parameter 'volume_uuid' is set
        if self.api_client.client_side_validation and ('volume_uuid' not in params or  # noqa: E501
                                                       params['volume_uuid'] is None):  # noqa: E501
            raise ValueError("Missing the required parameter `volume_uuid` when calling `get_volume`")  # noqa: E501

        if self.api_client.client_side_validation and ('volume_uuid' in params and not re.search(r'^[A-Fa-f0-9\\-]+$', params['volume_uuid'])):  # noqa: E501
            raise ValueError("Invalid value for parameter `volume_uuid` when calling `get_volume`, must conform to the pattern `/^[A-Fa-f0-9\\-]+$/`")  # noqa: E501
        collection_formats = {}

        path_params = {}
        if 'volume_uuid' in params:
            path_params['volume_uuid'] = params['volume_uuid']  # noqa: E501

        query_params = []

        header_params = {}

        form_params = []
        local_var_files = {}

        body_params = None
        # HTTP header `Accept`
        header_params['Accept'] = self.api_client.select_header_accept(
            ['application/json'])  # noqa: E501

        # HTTP header `Content-Type`
        header_params['Content-Type'] = self.api_client.select_header_content_type(  # noqa: E501
            ['application/json'])  # noqa: E501

        # Authentication setting
        auth_settings = ['Basic', 'Bearer']  # noqa: E501

        return self.api_client.call_api(
            '/storage/volumes/{volume_uuid}', 'GET',
            path_params,
            query_params,
            header_params,
            body=body_params,
            post_params=form_params,
            files=local_var_files,
            response_type='ResponseDataWithSingleVolume',  # noqa: E501
            auth_settings=auth_settings,
            async_req=params.get('async_req'),
            _return_http_data_only=params.get('_return_http_data_only'),
            _preload_content=params.get('_preload_content', True),
            _request_timeout=params.get('_request_timeout'),
            collection_formats=collection_formats)

    def update_volume(self, volume_uuid, body_volume_update, **kwargs):  # noqa: E501
        """Modify volume attributes  # noqa: E501

        Modify the attributes of an existing volume  # noqa: E501
        This method makes a synchronous HTTP request by default. To make an
        asynchronous HTTP request, please pass async_req=True
        >>> thread = api.update_volume(volume_uuid, body_volume_update, async_req=True)
        >>> result = thread.get()

        :param async_req bool
        :param str volume_uuid: FC assigned volume UUID (required)
        :param BodyVolumeUpdate body_volume_update: (required)
        :return: CommonResponseFields
                 If the method is called asynchronously,
                 returns the request thread.
        """
        kwargs['_return_http_data_only'] = True
        if kwargs.get('async_req'):
            return self.update_volume_with_http_info(volume_uuid, body_volume_update, **kwargs)  # noqa: E501
        else:
            (data) = self.update_volume_with_http_info(volume_uuid, body_volume_update, **kwargs)  # noqa: E501
            return data

    def update_volume_with_http_info(self, volume_uuid, body_volume_update, **kwargs):  # noqa: E501
        """Modify volume attributes  # noqa: E501

        Modify the attributes of an existing volume  # noqa: E501
        This method makes a synchronous HTTP request by default. To make an
        asynchronous HTTP request, please pass async_req=True
        >>> thread = api.update_volume_with_http_info(volume_uuid, body_volume_update, async_req=True) # noqa: E501
        >>> result = thread.get()

        :param async_req bool
        :param str volume_uuid: FC assigned volume UUID (required)
        :param BodyVolumeUpdate body_volume_update: (required)
        :return: CommonResponseFields
                 If the method is called asynchronously,
                 returns the request thread.
        """

        all_params = ['volume_uuid', 'body_volume_update']  # noqa: E501
        all_params.append('async_req')
        all_params.append('_return_http_data_only')
        all_params.append('_preload_content')
        all_params.append('_request_timeout')

        params = locals()
        for key, val in params['kwargs'].items():
            if key not in all_params:
                raise TypeError(
                    "Got an unexpected keyword argument '%s'"
                    " to method update_volume" % key
                )
            params[key] = val
        del params['kwargs']
        # verify the required parameter 'volume_uuid' is set
        if self.api_client.client_side_validation and ('volume_uuid' not in params or  # noqa: E501
                                                       params['volume_uuid'] is None):  # noqa: E501
            raise ValueError("Missing the required parameter `volume_uuid` when calling `update_volume`")  # noqa: E501
        # verify the required parameter 'body_volume_update' is set
        if self.api_client.client_side_validation and ('body_volume_update' not in params or  # noqa: E501
                                                       params['body_volume_update'] is None):  # noqa: E501
            raise ValueError("Missing the required parameter `body_volume_update` when calling `update_volume`")  # noqa: E501

        if self.api_client.client_side_validation and ('volume_uuid' in params and not re.search(r'^[A-Fa-f0-9\\-]+$', params['volume_uuid'])):  # noqa: E501
            raise ValueError("Invalid value for parameter `volume_uuid` when calling `update_volume`, must conform to the pattern `/^[A-Fa-f0-9\\-]+$/`")  # noqa: E501
        collection_formats = {}

        path_params = {}
        if 'volume_uuid' in params:
            path_params['volume_uuid'] = params['volume_uuid']  # noqa: E501

        query_params = []

        header_params = {}

        form_params = []
        local_var_files = {}

        body_params = None
        if 'body_volume_update' in params:
            body_params = params['body_volume_update']
        # HTTP header `Accept`
        header_params['Accept'] = self.api_client.select_header_accept(
            ['application/json'])  # noqa: E501

        # HTTP header `Content-Type`
        header_params['Content-Type'] = self.api_client.select_header_content_type(  # noqa: E501
            ['application/json'])  # noqa: E501

        # Authentication setting
        auth_settings = ['Basic', 'Bearer']  # noqa: E501

        return self.api_client.call_api(
            '/storage/volumes/{volume_uuid}', 'PATCH',
            path_params,
            query_params,
            header_params,
            body=body_params,
            post_params=form_params,
            files=local_var_files,
            response_type='CommonResponseFields',  # noqa: E501
            auth_settings=auth_settings,
            async_req=params.get('async_req'),
            _return_http_data_only=params.get('_return_http_data_only'),
            _preload_content=params.get('_preload_content', True),
            _request_timeout=params.get('_request_timeout'),
            collection_formats=collection_formats)


class TopologyApi(object):
    """NOTE: This class is auto generated by the swagger code generator program

    Do not edit the class manually.
    Ref: https://github.com/swagger-api/swagger-codegen
    """

    def __init__(self, api_client=None):
        if api_client is None:
            api_client = ApiClient()
        self.api_client = api_client

    def add_host(self, body_host_create, **kwargs):  # noqa: E501
        """Add a host  # noqa: E501

        Adds a host/server. The host/server may contain up to two FACs  # noqa: E501
        This method makes a synchronous HTTP request by default. To make an
        asynchronous HTTP request, please pass async_req=True
        >>> thread = api.add_host(body_host_create, async_req=True)
        >>> result = thread.get()

        :param async_req bool
        :param HostInfo body_host_create: (required)
        :return: ResponseDataWithCreateUuidString
                 If the method is called asynchronously,
                 returns the request thread.
        """
        kwargs['_return_http_data_only'] = True
        if kwargs.get('async_req'):
            return self.add_host_with_http_info(body_host_create, **kwargs)  # noqa: E501
        else:
            (data) = self.add_host_with_http_info(body_host_create, **kwargs)  # noqa: E501
            return data

    def add_host_with_http_info(self, body_host_create, **kwargs):  # noqa: E501
        """Add a host  # noqa: E501

        Adds a host/server. The host/server may contain up to two FACs  # noqa: E501
        This method makes a synchronous HTTP request by default. To make an
        asynchronous HTTP request, please pass async_req=True
        >>> thread = api.add_host_with_http_info(body_host_create, async_req=True) # noqa: E501
        >>> result = thread.get()

        :param async_req bool
        :param HostInfo body_host_create: (required)
        :return: ResponseDataWithCreateUuidString
                 If the method is called asynchronously,
                 returns the request thread.
        """

        all_params = ['body_host_create']  # noqa: E501
        all_params.append('async_req')
        all_params.append('_return_http_data_only')
        all_params.append('_preload_content')
        all_params.append('_request_timeout')

        params = locals()
        for key, val in params['kwargs'].items():
            if key not in all_params:
                raise TypeError(
                    "Got an unexpected keyword argument '%s'"
                    " to method add_host" % key
                )
            params[key] = val
        del params['kwargs']
        # verify the required parameter 'body_host_create' is set
        if self.api_client.client_side_validation and ('body_host_create' not in params or  # noqa: E501
                                                       params['body_host_create'] is None):  # noqa: E501
            raise ValueError("Missing the required parameter `body_host_create` when calling `add_host`")  # noqa: E501

        collection_formats = {}

        path_params = {}

        query_params = []

        header_params = {}

        form_params = []
        local_var_files = {}

        body_params = None
        if 'body_host_create' in params:
            body_params = params['body_host_create']
        # HTTP header `Accept`
        header_params['Accept'] = self.api_client.select_header_accept(
            ['application/json'])  # noqa: E501

        # HTTP header `Content-Type`
        header_params['Content-Type'] = self.api_client.select_header_content_type(  # noqa: E501
            ['application/json'])  # noqa: E501

        # Authentication setting
        auth_settings = ['Basic', 'Bearer']  # noqa: E501

        return self.api_client.call_api(
            '/topology/hosts', 'POST',
            path_params,
            query_params,
            header_params,
            body=body_params,
            post_params=form_params,
            files=local_var_files,
            response_type='ResponseDataWithCreateUuidString',  # noqa: E501
            auth_settings=auth_settings,
            async_req=params.get('async_req'),
            _return_http_data_only=params.get('_return_http_data_only'),
            _preload_content=params.get('_preload_content', True),
            _request_timeout=params.get('_request_timeout'),
            collection_formats=collection_formats)

    def delete_host(self, host_uuid, **kwargs):  # noqa: E501
        """Delete a host  # noqa: E501

        Deletes the specified host. The delete operation will fail if there are any volumes attached to this host.  # noqa: E501
        This method makes a synchronous HTTP request by default. To make an
        asynchronous HTTP request, please pass async_req=True
        >>> thread = api.delete_host(host_uuid, async_req=True)
        >>> result = thread.get()

        :param async_req bool
        :param str host_uuid: Host UUID (required)
        :return: CommonResponseFields
                 If the method is called asynchronously,
                 returns the request thread.
        """
        kwargs['_return_http_data_only'] = True
        if kwargs.get('async_req'):
            return self.delete_host_with_http_info(host_uuid, **kwargs)  # noqa: E501
        else:
            (data) = self.delete_host_with_http_info(host_uuid, **kwargs)  # noqa: E501
            return data

    def delete_host_with_http_info(self, host_uuid, **kwargs):  # noqa: E501
        """Delete a host  # noqa: E501

        Deletes the specified host. The delete operation will fail if there are any volumes attached to this host.  # noqa: E501
        This method makes a synchronous HTTP request by default. To make an
        asynchronous HTTP request, please pass async_req=True
        >>> thread = api.delete_host_with_http_info(host_uuid, async_req=True)
        >>> result = thread.get()

        :param async_req bool
        :param str host_uuid: Host UUID (required)
        :return: CommonResponseFields
                 If the method is called asynchronously,
                 returns the request thread.
        """

        all_params = ['host_uuid']  # noqa: E501
        all_params.append('async_req')
        all_params.append('_return_http_data_only')
        all_params.append('_preload_content')
        all_params.append('_request_timeout')

        params = locals()
        for key, val in params['kwargs'].items():
            if key not in all_params:
                raise TypeError(
                    "Got an unexpected keyword argument '%s'"
                    " to method delete_host" % key
                )
            params[key] = val
        del params['kwargs']
        # verify the required parameter 'host_uuid' is set
        if self.api_client.client_side_validation and ('host_uuid' not in params or  # noqa: E501
                                                       params['host_uuid'] is None):  # noqa: E501
            raise ValueError("Missing the required parameter `host_uuid` when calling `delete_host`")  # noqa: E501

        collection_formats = {}

        path_params = {}
        if 'host_uuid' in params:
            path_params['host_uuid'] = params['host_uuid']  # noqa: E501

        query_params = []

        header_params = {}

        form_params = []
        local_var_files = {}

        body_params = None
        # HTTP header `Accept`
        header_params['Accept'] = self.api_client.select_header_accept(
            ['application/json'])  # noqa: E501

        # HTTP header `Content-Type`
        header_params['Content-Type'] = self.api_client.select_header_content_type(  # noqa: E501
            ['application/json'])  # noqa: E501

        # Authentication setting
        auth_settings = ['Basic', 'Bearer']  # noqa: E501

        return self.api_client.call_api(
            '/topology/hosts/{host_uuid}', 'DELETE',
            path_params,
            query_params,
            header_params,
            body=body_params,
            post_params=form_params,
            files=local_var_files,
            response_type='CommonResponseFields',  # noqa: E501
            auth_settings=auth_settings,
            async_req=params.get('async_req'),
            _return_http_data_only=params.get('_return_http_data_only'),
            _preload_content=params.get('_preload_content', True),
            _request_timeout=params.get('_request_timeout'),
            collection_formats=collection_formats)

    def fetch_hosts_with_ids(self, body_fetch_hosts_with_ids, **kwargs):  # noqa: E501
        """Get properties for the specified hosts  # noqa: E501

        Retrieves the properties of up to 128 specified hosts  # noqa: E501
        This method makes a synchronous HTTP request by default. To make an
        asynchronous HTTP request, please pass async_req=True
        >>> thread = api.fetch_hosts_with_ids(body_fetch_hosts_with_ids, async_req=True)
        >>> result = thread.get()

        :param async_req bool
        :param BodyFetchHostsWithIds body_fetch_hosts_with_ids: (required)
        :return: ResponseDataWithListOfHosts
                 If the method is called asynchronously,
                 returns the request thread.
        """
        kwargs['_return_http_data_only'] = True
        if kwargs.get('async_req'):
            return self.fetch_hosts_with_ids_with_http_info(body_fetch_hosts_with_ids, **kwargs)  # noqa: E501
        else:
            (data) = self.fetch_hosts_with_ids_with_http_info(body_fetch_hosts_with_ids, **kwargs)  # noqa: E501
            return data

    def fetch_hosts_with_ids_with_http_info(self, body_fetch_hosts_with_ids, **kwargs):  # noqa: E501
        """Get properties for the specified hosts  # noqa: E501

        Retrieves the properties of up to 128 specified hosts  # noqa: E501
        This method makes a synchronous HTTP request by default. To make an
        asynchronous HTTP request, please pass async_req=True
        >>> thread = api.fetch_hosts_with_ids_with_http_info(body_fetch_hosts_with_ids, async_req=True)
        >>> result = thread.get()

        :param async_req bool
        :param BodyFetchHostsWithIds body_fetch_hosts_with_ids: (required)
        :return: ResponseDataWithListOfHosts
                 If the method is called asynchronously,
                 returns the request thread.
        """

        all_params = ['body_fetch_hosts_with_ids']  # noqa: E501
        all_params.append('async_req')
        all_params.append('_return_http_data_only')
        all_params.append('_preload_content')
        all_params.append('_request_timeout')

        params = locals()
        for key, val in params['kwargs'].items():
            if key not in all_params:
                raise TypeError(
                    "Got an unexpected keyword argument '%s'"
                    " to method fetch_hosts_with_ids" % key
                )
            params[key] = val
        del params['kwargs']
        # verify the required parameter 'body_fetch_hosts_with_ids' is set
        if self.api_client.client_side_validation and ('body_fetch_hosts_with_ids' not in params or  # noqa: E501
                                                       params['body_fetch_hosts_with_ids'] is None):  # noqa: E501
            raise ValueError("Missing the required parameter `body_fetch_hosts_with_ids` when calling `fetch_hosts_with_ids`")  # noqa: E501

        collection_formats = {}

        path_params = {}

        query_params = []

        header_params = {}

        form_params = []
        local_var_files = {}

        body_params = None
        if 'body_fetch_hosts_with_ids' in params:
            body_params = params['body_fetch_hosts_with_ids']
        # HTTP header `Accept`
        header_params['Accept'] = self.api_client.select_header_accept(
            ['application/json'])  # noqa: E501

        # HTTP header `Content-Type`
        header_params['Content-Type'] = self.api_client.select_header_content_type(  # noqa: E501
            ['application/json'])  # noqa: E501

        # Authentication setting
        auth_settings = ['Basic', 'Bearer']  # noqa: E501

        return self.api_client.call_api(
            '/topology/host_ids/subset', 'POST',
            path_params,
            query_params,
            header_params,
            body=body_params,
            post_params=form_params,
            files=local_var_files,
            response_type='ResponseDataWithListOfHosts',  # noqa: E501
            auth_settings=auth_settings,
            async_req=params.get('async_req'),
            _return_http_data_only=params.get('_return_http_data_only'),
            _preload_content=params.get('_preload_content', True),
            _request_timeout=params.get('_request_timeout'),
            collection_formats=collection_formats)

    def get_hierarchical_topology(self, **kwargs):  # noqa: E501
        """Get system topology  # noqa: E501

        Retrieve the hierarchal information of DPUs and their drives in the Fungible Storage Cluster  # noqa: E501
        This method makes a synchronous HTTP request by default. To make an
        asynchronous HTTP request, please pass async_req=True
        >>> thread = api.get_hierarchical_topology(async_req=True)
        >>> result = thread.get()

        :param async_req bool
        :param str node_class: The type of ndoes to return in the resulting list
        :param BodyGetHierarchicalTopology body_get_hierarchical_topology:
        :return: ResponseDpuDriveHierarchy
                 If the method is called asynchronously,
                 returns the request thread.
        """
        kwargs['_return_http_data_only'] = True
        if kwargs.get('async_req'):
            return self.get_hierarchical_topology_with_http_info(**kwargs)  # noqa: E501
        else:
            (data) = self.get_hierarchical_topology_with_http_info(**kwargs)  # noqa: E501
            return data

    def get_hierarchical_topology_with_http_info(self, **kwargs):  # noqa: E501
        """Get system topology  # noqa: E501

        Retrieve the hierarchal information of DPUs and their drives in the Fungible Storage Cluster  # noqa: E501
        This method makes a synchronous HTTP request by default. To make an
        asynchronous HTTP request, please pass async_req=True
        >>> thread = api.get_hierarchical_topology_with_http_info(async_req=True)
        >>> result = thread.get()

        :param async_req bool
        :param str node_class: The type of ndoes to return in the resulting list
        :param BodyGetHierarchicalTopology body_get_hierarchical_topology:
        :return: ResponseDpuDriveHierarchy
                 If the method is called asynchronously,
                 returns the request thread.
        """

        all_params = ['node_class', 'body_get_hierarchical_topology']  # noqa: E501
        all_params.append('async_req')
        all_params.append('_return_http_data_only')
        all_params.append('_preload_content')
        all_params.append('_request_timeout')

        params = locals()
        for key, val in params['kwargs'].items():
            if key not in all_params:
                raise TypeError(
                    "Got an unexpected keyword argument '%s'"
                    " to method get_hierarchical_topology" % key
                )
            params[key] = val
        del params['kwargs']

        collection_formats = {}

        path_params = {}

        query_params = []
        if 'node_class' in params:
            query_params.append(('node_class', params['node_class']))  # noqa: E501

        header_params = {}

        form_params = []
        local_var_files = {}

        body_params = None
        if 'body_get_hierarchical_topology' in params:
            body_params = params['body_get_hierarchical_topology']
        # HTTP header `Accept`
        header_params['Accept'] = self.api_client.select_header_accept(
            ['application/json'])  # noqa: E501

        # HTTP header `Content-Type`
        header_params['Content-Type'] = self.api_client.select_header_content_type(  # noqa: E501
            ['application/json'])  # noqa: E501

        # Authentication setting
        auth_settings = ['Basic', 'Bearer']  # noqa: E501

        return self.api_client.call_api(
            '/topology', 'GET',
            path_params,
            query_params,
            header_params,
            body=body_params,
            post_params=form_params,
            files=local_var_files,
            response_type='ResponseDpuDriveHierarchy',  # noqa: E501
            auth_settings=auth_settings,
            async_req=params.get('async_req'),
            _return_http_data_only=params.get('_return_http_data_only'),
            _preload_content=params.get('_preload_content', True),
            _request_timeout=params.get('_request_timeout'),
            collection_formats=collection_formats)

    def get_host_id_list(self, **kwargs):  # noqa: E501
        """Get list of host identifiers  # noqa: E501

        Retrieves a list of up to 36,864 identifiers for user-added hosts/servers. By default returns list of all host ids.  # noqa: E501
        This method makes a synchronous HTTP request by default. To make an
        asynchronous HTTP request, please pass async_req=True
        >>> thread = api.get_host_id_list(async_req=True)
        >>> result = thread.get()

        :param async_req bool
        :param str host_name_contains: Filter \"name\" parameter of hosts to only those than contain specified string
        :param str host_nqn_contains: Server/host's nqn name
        :param str fac_type: FAC type
        :param int limit_ids: The numbers of items to return in the resulting id list
        :param datetime start_date: List volumes starting from created time
        :param BodyGetHostIdList body_get_host_id_list:
        :return: ResponseDataWithListOfHostUuids
                 If the method is called asynchronously,
                 returns the request thread.
        """
        kwargs['_return_http_data_only'] = True
        if kwargs.get('async_req'):
            return self.get_host_id_list_with_http_info(**kwargs)  # noqa: E501
        else:
            (data) = self.get_host_id_list_with_http_info(**kwargs)  # noqa: E501
            return data

    def get_host_id_list_with_http_info(self, **kwargs):  # noqa: E501
        """Get list of host identifiers  # noqa: E501

        Retrieves a list of up to 36,864 identifiers for user-added hosts/servers. By default returns list of all host ids.  # noqa: E501
        This method makes a synchronous HTTP request by default. To make an
        asynchronous HTTP request, please pass async_req=True
        >>> thread = api.get_host_id_list_with_http_info(async_req=True)
        >>> result = thread.get()

        :param async_req bool
        :param str host_name_contains: Filter \"name\" parameter of hosts to only those than contain specified string
        :param str host_nqn_contains: Server/host's nqn name
        :param str fac_type: FAC type
        :param int limit_ids: The numbers of items to return in the resulting id list
        :param datetime start_date: List volumes starting from created time
        :param BodyGetHostIdList body_get_host_id_list:
        :return: ResponseDataWithListOfHostUuids
                 If the method is called asynchronously,
                 returns the request thread.
        """

        all_params = ['host_name_contains', 'host_nqn_contains', 'fac_type', 'limit_ids', 'start_date', 'body_get_host_id_list']  # noqa: E501
        all_params.append('async_req')
        all_params.append('_return_http_data_only')
        all_params.append('_preload_content')
        all_params.append('_request_timeout')

        params = locals()
        for key, val in params['kwargs'].items():
            if key not in all_params:
                raise TypeError(
                    "Got an unexpected keyword argument '%s'"
                    " to method get_host_id_list" % key
                )
            params[key] = val
        del params['kwargs']

        if self.api_client.client_side_validation and ('host_name_contains' in params and not re.search(r'^[A-Za-z0-9_\-\\.\\:]+$', params['host_name_contains'])):  # noqa: E501
            raise ValueError("Invalid value for parameter `host_name_contains` when calling `get_host_id_list`, must conform to the pattern `/^[A-Za-z0-9_\\-\\.\\:]+$/`")  # noqa: E501
        if self.api_client.client_side_validation and ('host_nqn_contains' in params and not re.search(r'^[A-Za-z0-9_\-\\.\\:]+$', params['host_nqn_contains'])):  # noqa: E501
            raise ValueError("Invalid value for parameter `host_nqn_contains` when calling `get_host_id_list`, must conform to the pattern `/^[A-Za-z0-9_\\-\\.\\:]+$/`")  # noqa: E501
        if self.api_client.client_side_validation and ('limit_ids' in params and params['limit_ids'] > 36864):  # noqa: E501
            raise ValueError("Invalid value for parameter `limit_ids` when calling `get_host_id_list`, must be a value less than or equal to `36864`")  # noqa: E501
        if self.api_client.client_side_validation and ('limit_ids' in params and params['limit_ids'] < 1):  # noqa: E501
            raise ValueError("Invalid value for parameter `limit_ids` when calling `get_host_id_list`, must be a value greater than or equal to `1`")  # noqa: E501
        collection_formats = {}

        path_params = {}

        query_params = []
        if 'host_name_contains' in params:
            query_params.append(('host_name_contains', params['host_name_contains']))  # noqa: E501
        if 'host_nqn_contains' in params:
            query_params.append(('host_nqn_contains', params['host_nqn_contains']))  # noqa: E501
        if 'fac_type' in params:
            query_params.append(('fac_type', params['fac_type']))  # noqa: E501
        if 'limit_ids' in params:
            query_params.append(('limit_ids', params['limit_ids']))  # noqa: E501
        if 'start_date' in params:
            query_params.append(('start_date', params['start_date']))  # noqa: E501

        header_params = {}

        form_params = []
        local_var_files = {}

        body_params = None
        if 'body_get_host_id_list' in params:
            body_params = params['body_get_host_id_list']
        # HTTP header `Accept`
        header_params['Accept'] = self.api_client.select_header_accept(
            ['application/json'])  # noqa: E501

        # HTTP header `Content-Type`
        header_params['Content-Type'] = self.api_client.select_header_content_type(  # noqa: E501
            ['application/json'])  # noqa: E501

        # Authentication setting
        auth_settings = ['Basic', 'Bearer']  # noqa: E501

        return self.api_client.call_api(
            '/topology/host_id_list', 'GET',
            path_params,
            query_params,
            header_params,
            body=body_params,
            post_params=form_params,
            files=local_var_files,
            response_type='ResponseDataWithListOfHostUuids',  # noqa: E501
            auth_settings=auth_settings,
            async_req=params.get('async_req'),
            _return_http_data_only=params.get('_return_http_data_only'),
            _preload_content=params.get('_preload_content', True),
            _request_timeout=params.get('_request_timeout'),
            collection_formats=collection_formats)

    def get_host_info(self, host_uuid, **kwargs):  # noqa: E501
        """Get details of a host  # noqa: E501

        Retrieves details of a host  # noqa: E501
        This method makes a synchronous HTTP request by default. To make an
        asynchronous HTTP request, please pass async_req=True
        >>> thread = api.get_host_info(host_uuid, async_req=True)
        >>> result = thread.get()

        :param async_req bool
        :param str host_uuid: Host UUID (required)
        :return: ResponseDataWithHostInfo
                 If the method is called asynchronously,
                 returns the request thread.
        """
        kwargs['_return_http_data_only'] = True
        if kwargs.get('async_req'):
            return self.get_host_info_with_http_info(host_uuid, **kwargs)  # noqa: E501
        else:
            (data) = self.get_host_info_with_http_info(host_uuid, **kwargs)  # noqa: E501
            return data

    def get_host_info_with_http_info(self, host_uuid, **kwargs):  # noqa: E501
        """Get details of a host  # noqa: E501

        Retrieves details of a host  # noqa: E501
        This method makes a synchronous HTTP request by default. To make an
        asynchronous HTTP request, please pass async_req=True
        >>> thread = api.get_host_info_with_http_info(host_uuid, async_req=True)
        >>> result = thread.get()

        :param async_req bool
        :param str host_uuid: Host UUID (required)
        :return: ResponseDataWithHostInfo
                 If the method is called asynchronously,
                 returns the request thread.
        """

        all_params = ['host_uuid']  # noqa: E501
        all_params.append('async_req')
        all_params.append('_return_http_data_only')
        all_params.append('_preload_content')
        all_params.append('_request_timeout')

        params = locals()
        for key, val in params['kwargs'].items():
            if key not in all_params:
                raise TypeError(
                    "Got an unexpected keyword argument '%s'"
                    " to method get_host_info" % key
                )
            params[key] = val
        del params['kwargs']
        # verify the required parameter 'host_uuid' is set
        if self.api_client.client_side_validation and ('host_uuid' not in params or  # noqa: E501
                                                       params['host_uuid'] is None):  # noqa: E501
            raise ValueError("Missing the required parameter `host_uuid` when calling `get_host_info`")  # noqa: E501

        collection_formats = {}

        path_params = {}
        if 'host_uuid' in params:
            path_params['host_uuid'] = params['host_uuid']  # noqa: E501

        query_params = []

        header_params = {}

        form_params = []
        local_var_files = {}

        body_params = None
        # HTTP header `Accept`
        header_params['Accept'] = self.api_client.select_header_accept(
            ['application/json'])  # noqa: E501

        # HTTP header `Content-Type`
        header_params['Content-Type'] = self.api_client.select_header_content_type(  # noqa: E501
            ['application/json'])  # noqa: E501

        # Authentication setting
        auth_settings = ['Basic', 'Bearer']  # noqa: E501

        return self.api_client.call_api(
            '/topology/hosts/{host_uuid}', 'GET',
            path_params,
            query_params,
            header_params,
            body=body_params,
            post_params=form_params,
            files=local_var_files,
            response_type='ResponseDataWithHostInfo',  # noqa: E501
            auth_settings=auth_settings,
            async_req=params.get('async_req'),
            _return_http_data_only=params.get('_return_http_data_only'),
            _preload_content=params.get('_preload_content', True),
            _request_timeout=params.get('_request_timeout'),
            collection_formats=collection_formats)

    def patch_host(self, host_uuid, body_host_patch, **kwargs):  # noqa: E501
        """Change selected properties of a host  # noqa: E501

        Changes the specified properties of the specified host. Can be used to update (add/delete/modify) the FAC information  # noqa: E501
        This method makes a synchronous HTTP request by default. To make an
        asynchronous HTTP request, please pass async_req=True
        >>> thread = api.patch_host(host_uuid, body_host_patch, async_req=True)
        >>> result = thread.get()

        :param async_req bool
        :param str host_uuid: Host UUID (required)
        :param HostInfo body_host_patch: (required)
        :return: SuccessResponseFields
                 If the method is called asynchronously,
                 returns the request thread.
        """
        kwargs['_return_http_data_only'] = True
        if kwargs.get('async_req'):
            return self.patch_host_with_http_info(host_uuid, body_host_patch, **kwargs)  # noqa: E501
        else:
            (data) = self.patch_host_with_http_info(host_uuid, body_host_patch, **kwargs)  # noqa: E501
            return data

    def patch_host_with_http_info(self, host_uuid, body_host_patch, **kwargs):  # noqa: E501
        """Change selected properties of a host  # noqa: E501

        Changes the specified properties of the specified host. Can be used to update (add/delete/modify) the FAC information  # noqa: E501
        This method makes a synchronous HTTP request by default. To make an
        asynchronous HTTP request, please pass async_req=True
        >>> thread = api.patch_host_with_http_info(host_uuid, body_host_patch, async_req=True)
        >>> result = thread.get()

        :param async_req bool
        :param str host_uuid: Host UUID (required)
        :param HostInfo body_host_patch: (required)
        :return: SuccessResponseFields
                 If the method is called asynchronously,
                 returns the request thread.
        """

        all_params = ['host_uuid', 'body_host_patch']  # noqa: E501
        all_params.append('async_req')
        all_params.append('_return_http_data_only')
        all_params.append('_preload_content')
        all_params.append('_request_timeout')

        params = locals()
        for key, val in params['kwargs'].items():
            if key not in all_params:
                raise TypeError(
                    "Got an unexpected keyword argument '%s'"
                    " to method patch_host" % key
                )
            params[key] = val
        del params['kwargs']
        # verify the required parameter 'host_uuid' is set
        if self.api_client.client_side_validation and ('host_uuid' not in params or  # noqa: E501
                                                       params['host_uuid'] is None):  # noqa: E501
            raise ValueError("Missing the required parameter `host_uuid` when calling `patch_host`")  # noqa: E501
        # verify the required parameter 'body_host_patch' is set
        if self.api_client.client_side_validation and ('body_host_patch' not in params or  # noqa: E501
                                                       params['body_host_patch'] is None):  # noqa: E501
            raise ValueError("Missing the required parameter `body_host_patch` when calling `patch_host`")  # noqa: E501

        collection_formats = {}

        path_params = {}
        if 'host_uuid' in params:
            path_params['host_uuid'] = params['host_uuid']  # noqa: E501

        query_params = []

        header_params = {}

        form_params = []
        local_var_files = {}

        body_params = None
        if 'body_host_patch' in params:
            body_params = params['body_host_patch']
        # HTTP header `Accept`
        header_params['Accept'] = self.api_client.select_header_accept(
            ['application/json'])  # noqa: E501

        # HTTP header `Content-Type`
        header_params['Content-Type'] = self.api_client.select_header_content_type(  # noqa: E501
            ['application/json'])  # noqa: E501

        # Authentication setting
        auth_settings = ['Basic', 'Bearer']  # noqa: E501

        return self.api_client.call_api(
            '/topology/hosts/{host_uuid}', 'PATCH',
            path_params,
            query_params,
            header_params,
            body=body_params,
            post_params=form_params,
            files=local_var_files,
            response_type='SuccessResponseFields',  # noqa: E501
            auth_settings=auth_settings,
            async_req=params.get('async_req'),
            _return_http_data_only=params.get('_return_http_data_only'),
            _preload_content=params.get('_preload_content', True),
            _request_timeout=params.get('_request_timeout'),
            collection_formats=collection_formats)


class AdditionalFields(object):
    """NOTE: This class is auto generated by the swagger code generator program

    Do not edit the class manually.
    """

    """
    Attributes:
      swagger_types (dict): The key is attribute name
                            and the value is attribute type.
      attribute_map (dict): The key is attribute name
                            and the value is json key in definition.
    """
    swagger_types = {
        'field_type': 'str',
        'field': 'object'
    }

    attribute_map = {
        'field_type': 'field_type',
        'field': 'field'
    }

    def __init__(self, field_type=None, field=None):  # noqa: E501
        """AdditionalFields - a model defined in Swagger"""  # noqa: E501

        self._field_type = None
        self._field = None
        self.discriminator = None

        self.field_type = field_type
        if field is not None:
            self.field = field

    @property
    def field_type(self):
        """Gets the field_type of this AdditionalFields.  # noqa: E501


        :return: The field_type of this AdditionalFields.  # noqa: E501
        :rtype: str
        """
        return self._field_type

    @field_type.setter
    def field_type(self, field_type):
        """Sets the field_type of this AdditionalFields.


        :param field_type: The field_type of this AdditionalFields.  # noqa: E501
        :type: str
        """
        if field_type is None:
            raise ValueError("Invalid value for `field_type`, must not be `None`")  # noqa: E501

        self._field_type = field_type

    @property
    def field(self):
        """Gets the field of this AdditionalFields.  # noqa: E501


        :return: The field of this AdditionalFields.  # noqa: E501
        :rtype: object
        """
        return self._field

    @field.setter
    def field(self, field):
        """Sets the field of this AdditionalFields.


        :param field: The field of this AdditionalFields.  # noqa: E501
        :type: object
        """

        self._field = field

    def to_dict(self):
        """Returns the model properties as a dict"""
        result = {}

        for attr, _ in self.swagger_types.items():
            value = getattr(self, attr)
            if isinstance(value, list):
                result[attr] = list(map(
                    lambda x: x.to_dict() if hasattr(x, "to_dict") else x,
                    value
                ))
            elif hasattr(value, "to_dict"):
                result[attr] = value.to_dict()
            elif isinstance(value, dict):
                result[attr] = dict(map(
                    lambda item: (item[0], item[1].to_dict())
                    if hasattr(item[1], "to_dict") else item,
                    value.items()
                ))
            else:
                result[attr] = value
        if issubclass(AdditionalFields, dict):
            for key, value in self.items():
                result[key] = value

        return result

    def to_str(self):
        """Returns the string representation of the model"""
        return pprint.pformat(self.to_dict())

    def __repr__(self):
        """For `print` and `pprint`"""
        return self.to_str()

    def __eq__(self, other):
        """Returns true if both objects are equal"""
        if not isinstance(other, AdditionalFields):
            return False

        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        """Returns true if both objects are not equal"""
        return not self == other

# coding: utf-8


"""
    Fungible Cluster Services Intent API

    Intent based REST API for interfacing between the management/orchestration system and Fungible Cluster Services   # noqa: E501

    OpenAPI spec version: 2.2.10
    Contact: support@fungible.com
    Generated by: https://github.com/swagger-api/swagger-codegen.git
"""


class BlockSize(object):
    """NOTE: This class is auto generated by the swagger code generator program

    Do not edit the class manually.
    """

    """
    allowed enum values
    """
    _4096 = "4096"
    _8192 = "8192"
    _16384 = "16384"

    """
    Attributes:
      swagger_types (dict): The key is attribute name
                            and the value is attribute type.
      attribute_map (dict): The key is attribute name
                            and the value is json key in definition.
    """
    swagger_types = {
    }

    attribute_map = {
    }

    def __init__(self):  # noqa: E501
        """BlockSize - a model defined in Swagger"""  # noqa: E501
        self.discriminator = None

    def to_dict(self):
        """Returns the model properties as a dict"""
        result = {}

        for attr, _ in self.swagger_types.items():
            value = getattr(self, attr)
            if isinstance(value, list):
                result[attr] = list(map(
                    lambda x: x.to_dict() if hasattr(x, "to_dict") else x,
                    value
                ))
            elif hasattr(value, "to_dict"):
                result[attr] = value.to_dict()
            elif isinstance(value, dict):
                result[attr] = dict(map(
                    lambda item: (item[0], item[1].to_dict())
                    if hasattr(item[1], "to_dict") else item,
                    value.items()
                ))
            else:
                result[attr] = value
        if issubclass(BlockSize, dict):
            for key, value in self.items():
                result[key] = value

        return result

    def to_str(self):
        """Returns the string representation of the model"""
        return pprint.pformat(self.to_dict())

    def __repr__(self):
        """For `print` and `pprint`"""
        return self.to_str()

    def __eq__(self, other):
        """Returns true if both objects are equal"""
        if not isinstance(other, BlockSize):
            return False

        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        """Returns true if both objects are not equal"""
        return not self == other


class BodyFetchHostsWithIds(object):
    """NOTE: This class is auto generated by the swagger code generator program

    Do not edit the class manually.
    """

    """
    Attributes:
      swagger_types (dict): The key is attribute name
                            and the value is attribute type.
      attribute_map (dict): The key is attribute name
                            and the value is json key in definition.
    """
    swagger_types = {
        'host_id_list': 'list[str]'
    }

    attribute_map = {
        'host_id_list': 'host_id_list'
    }

    def __init__(self, host_id_list=None):  # noqa: E501
        """BodyFetchHostsWithIds - a model defined in Swagger"""  # noqa: E501

        self._host_id_list = None
        self.discriminator = None

        self.host_id_list = host_id_list

    @property
    def host_id_list(self):
        """Gets the host_id_list of this BodyFetchHostsWithIds.  # noqa: E501


        :return: The host_id_list of this BodyFetchHostsWithIds.  # noqa: E501
        :rtype: list[str]
        """
        return self._host_id_list

    @host_id_list.setter
    def host_id_list(self, host_id_list):
        """Sets the host_id_list of this BodyFetchHostsWithIds.


        :param host_id_list: The host_id_list of this BodyFetchHostsWithIds.  # noqa: E501
        :type: list[str]
        """
        if host_id_list is None:
            raise ValueError("Invalid value for `host_id_list`, must not be `None`")  # noqa: E501

        self._host_id_list = host_id_list

    def to_dict(self):
        """Returns the model properties as a dict"""
        result = {}

        for attr, _ in self.swagger_types.items():
            value = getattr(self, attr)
            if isinstance(value, list):
                result[attr] = list(map(
                    lambda x: x.to_dict() if hasattr(x, "to_dict") else x,
                    value
                ))
            elif hasattr(value, "to_dict"):
                result[attr] = value.to_dict()
            elif isinstance(value, dict):
                result[attr] = dict(map(
                    lambda item: (item[0], item[1].to_dict())
                    if hasattr(item[1], "to_dict") else item,
                    value.items()
                ))
            else:
                result[attr] = value
        if issubclass(BodyFetchHostsWithIds, dict):
            for key, value in self.items():
                result[key] = value

        return result

    def to_str(self):
        """Returns the string representation of the model"""
        return pprint.pformat(self.to_dict())

    def __repr__(self):
        """For `print` and `pprint`"""
        return self.to_str()

    def __eq__(self, other):
        """Returns true if both objects are equal"""
        if not isinstance(other, BodyFetchHostsWithIds):
            return False

        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        """Returns true if both objects are not equal"""
        return not self == other


class BodyGetHierarchicalTopology(object):
    """NOTE: This class is auto generated by the swagger code generator program

    Do not edit the class manually.
    """

    """
    Attributes:
      swagger_types (dict): The key is attribute name
                            and the value is attribute type.
      attribute_map (dict): The key is attribute name
                            and the value is json key in definition.
    """
    swagger_types = {
        'node_class': 'str'
    }

    attribute_map = {
        'node_class': 'node_class'
    }

    def __init__(self, node_class=None):  # noqa: E501
        """BodyGetHierarchicalTopology - a model defined in Swagger"""  # noqa: E501

        self._node_class = None
        self.discriminator = None

        if node_class is not None:
            self.node_class = node_class

    @property
    def node_class(self):
        """Gets the node_class of this BodyGetHierarchicalTopology.  # noqa: E501

        Internally assigned from query parameter limit  # noqa: E501

        :return: The node_class of this BodyGetHierarchicalTopology.  # noqa: E501
        :rtype: str
        """
        return self._node_class

    @node_class.setter
    def node_class(self, node_class):
        """Sets the node_class of this BodyGetHierarchicalTopology.

        Internally assigned from query parameter limit  # noqa: E501

        :param node_class: The node_class of this BodyGetHierarchicalTopology.  # noqa: E501
        :type: str
        """

        self._node_class = node_class

    def to_dict(self):
        """Returns the model properties as a dict"""
        result = {}

        for attr, _ in self.swagger_types.items():
            value = getattr(self, attr)
            if isinstance(value, list):
                result[attr] = list(map(
                    lambda x: x.to_dict() if hasattr(x, "to_dict") else x,
                    value
                ))
            elif hasattr(value, "to_dict"):
                result[attr] = value.to_dict()
            elif isinstance(value, dict):
                result[attr] = dict(map(
                    lambda item: (item[0], item[1].to_dict())
                    if hasattr(item[1], "to_dict") else item,
                    value.items()
                ))
            else:
                result[attr] = value
        if issubclass(BodyGetHierarchicalTopology, dict):
            for key, value in self.items():
                result[key] = value

        return result

    def to_str(self):
        """Returns the string representation of the model"""
        return pprint.pformat(self.to_dict())

    def __repr__(self):
        """For `print` and `pprint`"""
        return self.to_str()

    def __eq__(self, other):
        """Returns true if both objects are equal"""
        if not isinstance(other, BodyGetHierarchicalTopology):
            return False

        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        """Returns true if both objects are not equal"""
        return not self == other


class BodyGetHostIdList(object):
    """NOTE: This class is auto generated by the swagger code generator program

    Do not edit the class manually.
    """

    """
    Attributes:
      swagger_types (dict): The key is attribute name
                            and the value is attribute type.
      attribute_map (dict): The key is attribute name
                            and the value is json key in definition.
    """
    swagger_types = {
        'limit_ids_param': 'int',
        'host_name_contains': 'str',
        'start_date_param': 'datetime',
        'host_nqn_contains': 'str',
        'fac_type': 'str'
    }

    attribute_map = {
        'limit_ids_param': 'limit_ids_param',
        'host_name_contains': 'host_name_contains',
        'start_date_param': 'start_date_param',
        'host_nqn_contains': 'host_nqn_contains',
        'fac_type': 'fac_type'
    }

    def __init__(self, limit_ids_param=None, host_name_contains=None, start_date_param=None, host_nqn_contains=None, fac_type=None):  # noqa: E501
        """BodyGetHostIdList - a model defined in Swagger"""  # noqa: E501

        self._limit_ids_param = None
        self._host_name_contains = None
        self._start_date_param = None
        self._host_nqn_contains = None
        self._fac_type = None
        self.discriminator = None

        if limit_ids_param is not None:
            self.limit_ids_param = limit_ids_param
        if host_name_contains is not None:
            self.host_name_contains = host_name_contains
        if start_date_param is not None:
            self.start_date_param = start_date_param
        if host_nqn_contains is not None:
            self.host_nqn_contains = host_nqn_contains
        if fac_type is not None:
            self.fac_type = fac_type

    @property
    def limit_ids_param(self):
        """Gets the limit_ids_param of this BodyGetHostIdList.  # noqa: E501

        Internally assigned from query parameter limit  # noqa: E501

        :return: The limit_ids_param of this BodyGetHostIdList.  # noqa: E501
        :rtype: int
        """
        return self._limit_ids_param

    @limit_ids_param.setter
    def limit_ids_param(self, limit_ids_param):
        """Sets the limit_ids_param of this BodyGetHostIdList.

        Internally assigned from query parameter limit  # noqa: E501

        :param limit_ids_param: The limit_ids_param of this BodyGetHostIdList.  # noqa: E501
        :type: int
        """

        self._limit_ids_param = limit_ids_param

    @property
    def host_name_contains(self):
        """Gets the host_name_contains of this BodyGetHostIdList.  # noqa: E501

        Filter \"name\" parameter of hosts to only those than contain specified string  # noqa: E501

        :return: The host_name_contains of this BodyGetHostIdList.  # noqa: E501
        :rtype: str
        """
        return self._host_name_contains

    @host_name_contains.setter
    def host_name_contains(self, host_name_contains):
        """Sets the host_name_contains of this BodyGetHostIdList.

        Filter \"name\" parameter of hosts to only those than contain specified string  # noqa: E501

        :param host_name_contains: The host_name_contains of this BodyGetHostIdList.  # noqa: E501
        :type: str
        """

        self._host_name_contains = host_name_contains

    @property
    def start_date_param(self):
        """Gets the start_date_param of this BodyGetHostIdList.  # noqa: E501

        Query parameter from created time  # noqa: E501

        :return: The start_date_param of this BodyGetHostIdList.  # noqa: E501
        :rtype: datetime
        """
        return self._start_date_param

    @start_date_param.setter
    def start_date_param(self, start_date_param):
        """Sets the start_date_param of this BodyGetHostIdList.

        Query parameter from created time  # noqa: E501

        :param start_date_param: The start_date_param of this BodyGetHostIdList.  # noqa: E501
        :type: datetime
        """

        self._start_date_param = start_date_param

    @property
    def host_nqn_contains(self):
        """Gets the host_nqn_contains of this BodyGetHostIdList.  # noqa: E501

        Host nqn name  # noqa: E501

        :return: The host_nqn_contains of this BodyGetHostIdList.  # noqa: E501
        :rtype: str
        """
        return self._host_nqn_contains

    @host_nqn_contains.setter
    def host_nqn_contains(self, host_nqn_contains):
        """Sets the host_nqn_contains of this BodyGetHostIdList.

        Host nqn name  # noqa: E501

        :param host_nqn_contains: The host_nqn_contains of this BodyGetHostIdList.  # noqa: E501
        :type: str
        """

        self._host_nqn_contains = host_nqn_contains

    @property
    def fac_type(self):
        """Gets the fac_type of this BodyGetHostIdList.  # noqa: E501

        FAC type  # noqa: E501

        :return: The fac_type of this BodyGetHostIdList.  # noqa: E501
        :rtype: str
        """
        return self._fac_type

    @fac_type.setter
    def fac_type(self, fac_type):
        """Sets the fac_type of this BodyGetHostIdList.

        FAC type  # noqa: E501

        :param fac_type: The fac_type of this BodyGetHostIdList.  # noqa: E501
        :type: str
        """

        self._fac_type = fac_type

    def to_dict(self):
        """Returns the model properties as a dict"""
        result = {}

        for attr, _ in self.swagger_types.items():
            value = getattr(self, attr)
            if isinstance(value, list):
                result[attr] = list(map(
                    lambda x: x.to_dict() if hasattr(x, "to_dict") else x,
                    value
                ))
            elif hasattr(value, "to_dict"):
                result[attr] = value.to_dict()
            elif isinstance(value, dict):
                result[attr] = dict(map(
                    lambda item: (item[0], item[1].to_dict())
                    if hasattr(item[1], "to_dict") else item,
                    value.items()
                ))
            else:
                result[attr] = value
        if issubclass(BodyGetHostIdList, dict):
            for key, value in self.items():
                result[key] = value

        return result

    def to_str(self):
        """Returns the string representation of the model"""
        return pprint.pformat(self.to_dict())

    def __repr__(self):
        """For `print` and `pprint`"""
        return self.to_str()

    def __eq__(self, other):
        """Returns true if both objects are equal"""
        if not isinstance(other, BodyGetHostIdList):
            return False

        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        """Returns true if both objects are not equal"""
        return not self == other


class BodyVolumeAttach(object):
    """NOTE: This class is auto generated by the swagger code generator program

    Do not edit the class manually.
    """

    """
    Attributes:
      swagger_types (dict): The key is attribute name
                            and the value is attribute type.
      attribute_map (dict): The key is attribute name
                            and the value is json key in definition.
    """
    swagger_types = {
        'transport': 'Transport',
        'host_uuid': 'str',
        'host_nqn': 'str',
        'remote_ip': 'str',
        'fnid': 'object',
        'huid': 'object',
        'ctlid': 'object',
        'pci_bus': 'int',
        'pci_device': 'int',
        'pci_function': 'int',
        'initiator_uuid': 'str',
        'persistent_attach': 'bool',
        'max_connections': 'int',
        'disable_crc_check': 'bool',
        'max_read_iops_ratio': 'int',
        'max_read_iops': 'int',
        'host_lba_size': 'int',
        'queue_depth': 'int'
    }

    attribute_map = {
        'transport': 'transport',
        'host_uuid': 'host_uuid',
        'host_nqn': 'host_nqn',
        'remote_ip': 'remote_ip',
        'fnid': 'fnid',
        'huid': 'huid',
        'ctlid': 'ctlid',
        'pci_bus': 'pci_bus',
        'pci_device': 'pci_device',
        'pci_function': 'pci_function',
        'initiator_uuid': 'initiator_uuid',
        'persistent_attach': 'persistent_attach',
        'max_connections': 'max_connections',
        'disable_crc_check': 'disable_crc_check',
        'max_read_iops_ratio': 'max_read_iops_ratio',
        'max_read_iops': 'max_read_iops',
        'host_lba_size': 'host_lba_size',
        'queue_depth': 'queue_depth'
    }

    def __init__(self, transport=None, host_uuid=None, host_nqn=None, remote_ip=None, fnid=None, huid=None, ctlid=None, pci_bus=None, pci_device=None, pci_function=None, initiator_uuid=None, persistent_attach=None, max_connections=None, disable_crc_check=None, max_read_iops_ratio=None, max_read_iops=0, host_lba_size=None, queue_depth=0):  # noqa: E501
        """BodyVolumeAttach - a model defined in Swagger"""  # noqa: E501

        self._transport = None
        self._host_uuid = None
        self._host_nqn = None
        self._remote_ip = None
        self._fnid = None
        self._huid = None
        self._ctlid = None
        self._pci_bus = None
        self._pci_device = None
        self._pci_function = None
        self._initiator_uuid = None
        self._persistent_attach = None
        self._max_connections = None
        self._disable_crc_check = None
        self._max_read_iops_ratio = None
        self._max_read_iops = None
        self._host_lba_size = None
        self._queue_depth = None
        self.discriminator = None

        if transport is not None:
            self.transport = transport
        if host_uuid is not None:
            self.host_uuid = host_uuid
        if host_nqn is not None:
            self.host_nqn = host_nqn
        if remote_ip is not None:
            self.remote_ip = remote_ip
        if fnid is not None:
            self.fnid = fnid
        if huid is not None:
            self.huid = huid
        if ctlid is not None:
            self.ctlid = ctlid
        if pci_bus is not None:
            self.pci_bus = pci_bus
        if pci_device is not None:
            self.pci_device = pci_device
        if pci_function is not None:
            self.pci_function = pci_function
        if initiator_uuid is not None:
            self.initiator_uuid = initiator_uuid
        if persistent_attach is not None:
            self.persistent_attach = persistent_attach
        if max_connections is not None:
            self.max_connections = max_connections
        if disable_crc_check is not None:
            self.disable_crc_check = disable_crc_check
        if max_read_iops_ratio is not None:
            self.max_read_iops_ratio = max_read_iops_ratio
        if max_read_iops is not None:
            self.max_read_iops = max_read_iops
        if host_lba_size is not None:
            self.host_lba_size = host_lba_size
        if queue_depth is not None:
            self.queue_depth = queue_depth

    @property
    def transport(self):
        """Gets the transport of this BodyVolumeAttach.  # noqa: E501


        :return: The transport of this BodyVolumeAttach.  # noqa: E501
        :rtype: Transport
        """
        return self._transport

    @transport.setter
    def transport(self, transport):
        """Sets the transport of this BodyVolumeAttach.


        :param transport: The transport of this BodyVolumeAttach.  # noqa: E501
        :type: Transport
        """

        self._transport = transport

    @property
    def host_uuid(self):
        """Gets the host_uuid of this BodyVolumeAttach.  # noqa: E501

        When specified, this field supercedes the host_nqn field  # noqa: E501

        :return: The host_uuid of this BodyVolumeAttach.  # noqa: E501
        :rtype: str
        """
        return self._host_uuid

    @host_uuid.setter
    def host_uuid(self, host_uuid):
        """Sets the host_uuid of this BodyVolumeAttach.

        When specified, this field supercedes the host_nqn field  # noqa: E501

        :param host_uuid: The host_uuid of this BodyVolumeAttach.  # noqa: E501
        :type: str
        """

        self._host_uuid = host_uuid

    @property
    def host_nqn(self):
        """Gets the host_nqn of this BodyVolumeAttach.  # noqa: E501

        This parameter is ignored if the host_uuid is specified  # noqa: E501

        :return: The host_nqn of this BodyVolumeAttach.  # noqa: E501
        :rtype: str
        """
        return self._host_nqn

    @host_nqn.setter
    def host_nqn(self, host_nqn):
        """Sets the host_nqn of this BodyVolumeAttach.

        This parameter is ignored if the host_uuid is specified  # noqa: E501

        :param host_nqn: The host_nqn of this BodyVolumeAttach.  # noqa: E501
        :type: str
        """
        if host_nqn is not None and len(host_nqn) > 223:
            raise ValueError("Invalid value for `host_nqn`, length must be less than or equal to `223`")  # noqa: E501
        if host_nqn is not None and len(host_nqn) < 5:
            raise ValueError("Invalid value for `host_nqn`, length must be greater than or equal to `5`")  # noqa: E501
        if host_nqn is not None and not re.search(r'^[A-Za-z0-9_\\-\\.\\:]+$', host_nqn):  # noqa: E501
            raise ValueError(r"Invalid value for `host_nqn`, must be a follow pattern or equal to `/^[A-Za-z0-9_\\-\\.\\:]+$/`")  # noqa: E501

        self._host_nqn = host_nqn

    @property
    def remote_ip(self):
        """Gets the remote_ip of this BodyVolumeAttach.  # noqa: E501


        :return: The remote_ip of this BodyVolumeAttach.  # noqa: E501
        :rtype: str
        """
        return self._remote_ip

    @remote_ip.setter
    def remote_ip(self, remote_ip):
        """Sets the remote_ip of this BodyVolumeAttach.


        :param remote_ip: The remote_ip of this BodyVolumeAttach.  # noqa: E501
        :type: str
        """

        self._remote_ip = remote_ip

    @property
    def fnid(self):
        """Gets the fnid of this BodyVolumeAttach.  # noqa: E501

        Valid for transport=PCI  # noqa: E501

        :return: The fnid of this BodyVolumeAttach.  # noqa: E501
        :rtype: object
        """
        return self._fnid

    @fnid.setter
    def fnid(self, fnid):
        """Sets the fnid of this BodyVolumeAttach.

        Valid for transport=PCI  # noqa: E501

        :param fnid: The fnid of this BodyVolumeAttach.  # noqa: E501
        :type: object
        """

        self._fnid = fnid

    @property
    def huid(self):
        """Gets the huid of this BodyVolumeAttach.  # noqa: E501

        Valid for transport=PCI  # noqa: E501

        :return: The huid of this BodyVolumeAttach.  # noqa: E501
        :rtype: object
        """
        return self._huid

    @huid.setter
    def huid(self, huid):
        """Sets the huid of this BodyVolumeAttach.

        Valid for transport=PCI  # noqa: E501

        :param huid: The huid of this BodyVolumeAttach.  # noqa: E501
        :type: object
        """

        self._huid = huid

    @property
    def ctlid(self):
        """Gets the ctlid of this BodyVolumeAttach.  # noqa: E501

        Valid for transport=PCI  # noqa: E501

        :return: The ctlid of this BodyVolumeAttach.  # noqa: E501
        :rtype: object
        """
        return self._ctlid

    @ctlid.setter
    def ctlid(self, ctlid):
        """Sets the ctlid of this BodyVolumeAttach.

        Valid for transport=PCI  # noqa: E501

        :param ctlid: The ctlid of this BodyVolumeAttach.  # noqa: E501
        :type: object
        """

        self._ctlid = ctlid

    @property
    def pci_bus(self):
        """Gets the pci_bus of this BodyVolumeAttach.  # noqa: E501

        Valid for transport=PCI_BDF  # noqa: E501

        :return: The pci_bus of this BodyVolumeAttach.  # noqa: E501
        :rtype: int
        """
        return self._pci_bus

    @pci_bus.setter
    def pci_bus(self, pci_bus):
        """Sets the pci_bus of this BodyVolumeAttach.

        Valid for transport=PCI_BDF  # noqa: E501

        :param pci_bus: The pci_bus of this BodyVolumeAttach.  # noqa: E501
        :type: int
        """

        self._pci_bus = pci_bus

    @property
    def pci_device(self):
        """Gets the pci_device of this BodyVolumeAttach.  # noqa: E501

        Valid for transport=PCI_BDF  # noqa: E501

        :return: The pci_device of this BodyVolumeAttach.  # noqa: E501
        :rtype: int
        """
        return self._pci_device

    @pci_device.setter
    def pci_device(self, pci_device):
        """Sets the pci_device of this BodyVolumeAttach.

        Valid for transport=PCI_BDF  # noqa: E501

        :param pci_device: The pci_device of this BodyVolumeAttach.  # noqa: E501
        :type: int
        """

        self._pci_device = pci_device

    @property
    def pci_function(self):
        """Gets the pci_function of this BodyVolumeAttach.  # noqa: E501

        Valid for transport=PCI_BDF  # noqa: E501

        :return: The pci_function of this BodyVolumeAttach.  # noqa: E501
        :rtype: int
        """
        return self._pci_function

    @pci_function.setter
    def pci_function(self, pci_function):
        """Sets the pci_function of this BodyVolumeAttach.

        Valid for transport=PCI_BDF  # noqa: E501

        :param pci_function: The pci_function of this BodyVolumeAttach.  # noqa: E501
        :type: int
        """

        self._pci_function = pci_function

    @property
    def initiator_uuid(self):
        """Gets the initiator_uuid of this BodyVolumeAttach.  # noqa: E501

        Storage initiator's unique identifier to attach volume to  # noqa: E501

        :return: The initiator_uuid of this BodyVolumeAttach.  # noqa: E501
        :rtype: str
        """
        return self._initiator_uuid

    @initiator_uuid.setter
    def initiator_uuid(self, initiator_uuid):
        """Sets the initiator_uuid of this BodyVolumeAttach.

        Storage initiator's unique identifier to attach volume to  # noqa: E501

        :param initiator_uuid: The initiator_uuid of this BodyVolumeAttach.  # noqa: E501
        :type: str
        """

        self._initiator_uuid = initiator_uuid

    @property
    def persistent_attach(self):
        """Gets the persistent_attach of this BodyVolumeAttach.  # noqa: E501

        Flag that indicates that volume needs to be reattached to the Storage Initiator after a reboot  # noqa: E501

        :return: The persistent_attach of this BodyVolumeAttach.  # noqa: E501
        :rtype: bool
        """
        return self._persistent_attach

    @persistent_attach.setter
    def persistent_attach(self, persistent_attach):
        """Sets the persistent_attach of this BodyVolumeAttach.

        Flag that indicates that volume needs to be reattached to the Storage Initiator after a reboot  # noqa: E501

        :param persistent_attach: The persistent_attach of this BodyVolumeAttach.  # noqa: E501
        :type: bool
        """

        self._persistent_attach = persistent_attach

    @property
    def max_connections(self):
        """Gets the max_connections of this BodyVolumeAttach.  # noqa: E501

        The number of connections allowed per controller. To be compatible with the Swagger Python client, the value '0' is accepted. The actual max_connections offered by the datapath to a host client is 4 if 0 <= max_connections < 4 Note: a. Users must ensure that the queue_depth * max_connections <= 1024 b. There's a finite pool of connections per DPU. Assigning an arbitrarily large number of connections to every volume may exhaust that pool, preventing new volumes from being attached.  # noqa: E501

        :return: The max_connections of this BodyVolumeAttach.  # noqa: E501
        :rtype: int
        """
        return self._max_connections

    @max_connections.setter
    def max_connections(self, max_connections):
        """Sets the max_connections of this BodyVolumeAttach.

        The number of connections allowed per controller. To be compatible with the Swagger Python client, the value '0' is accepted. The actual max_connections offered by the datapath to a host client is 4 if 0 <= max_connections < 4 Note: a. Users must ensure that the queue_depth * max_connections <= 1024 b. There's a finite pool of connections per DPU. Assigning an arbitrarily large number of connections to every volume may exhaust that pool, preventing new volumes from being attached.  # noqa: E501

        :param max_connections: The max_connections of this BodyVolumeAttach.  # noqa: E501
        :type: int
        """
        if max_connections is not None and max_connections > 144:  # noqa: E501
            raise ValueError("Invalid value for `max_connections`, must be a value less than or equal to `144`")  # noqa: E501
        if max_connections is not None and max_connections < 0:  # noqa: E501
            raise ValueError("Invalid value for `max_connections`, must be a value greater than or equal to `0`")  # noqa: E501

        self._max_connections = max_connections

    @property
    def disable_crc_check(self):
        """Gets the disable_crc_check of this BodyVolumeAttach.  # noqa: E501

        Disable crc check on a volume  # noqa: E501

        :return: The disable_crc_check of this BodyVolumeAttach.  # noqa: E501
        :rtype: bool
        """
        return self._disable_crc_check

    @disable_crc_check.setter
    def disable_crc_check(self, disable_crc_check):
        """Sets the disable_crc_check of this BodyVolumeAttach.

        Disable crc check on a volume  # noqa: E501

        :param disable_crc_check: The disable_crc_check of this BodyVolumeAttach.  # noqa: E501
        :type: bool
        """

        self._disable_crc_check = disable_crc_check

    @property
    def max_read_iops_ratio(self):
        """Gets the max_read_iops_ratio of this BodyVolumeAttach.  # noqa: E501

        This setting can be specified in addition to or in place of an absolute max_read_iops number. For qos critical volumes this is a percentage ratio of the intended max_read_iops compared to the default min_read_iops of the volume. For best effort volumes, it is a percentage ratio of the intended max_read_iops compared to the default max_read_iops of the volume. When specified in addition to the absolute max_read_iops, the greater computed value will be set.  # noqa: E501

        :return: The max_read_iops_ratio of this BodyVolumeAttach.  # noqa: E501
        :rtype: int
        """
        return self._max_read_iops_ratio

    @max_read_iops_ratio.setter
    def max_read_iops_ratio(self, max_read_iops_ratio):
        """Sets the max_read_iops_ratio of this BodyVolumeAttach.

        This setting can be specified in addition to or in place of an absolute max_read_iops number. For qos critical volumes this is a percentage ratio of the intended max_read_iops compared to the default min_read_iops of the volume. For best effort volumes, it is a percentage ratio of the intended max_read_iops compared to the default max_read_iops of the volume. When specified in addition to the absolute max_read_iops, the greater computed value will be set.  # noqa: E501

        :param max_read_iops_ratio: The max_read_iops_ratio of this BodyVolumeAttach.  # noqa: E501
        :type: int
        """
        if max_read_iops_ratio is not None and max_read_iops_ratio > 400:  # noqa: E501
            raise ValueError("Invalid value for `max_read_iops_ratio`, must be a value less than or equal to `400`")  # noqa: E501
        if max_read_iops_ratio is not None and max_read_iops_ratio < 100:  # noqa: E501
            raise ValueError("Invalid value for `max_read_iops_ratio`, must be a value greater than or equal to `100`")  # noqa: E501

        self._max_read_iops_ratio = max_read_iops_ratio

    @property
    def max_read_iops(self):
        """Gets the max_read_iops of this BodyVolumeAttach.  # noqa: E501

        If specified, the max_read_iops setting overrides the QoS settings used during volume creation. In release <= 4.1, this setting  also applies to the min_read_iops since max=min. In later releases however this setting refers exclusively to max_read_iops. When specified in addition to the max_read_iops_ratio, the greater computed value will be set. The datapath will deliver a minimum of 20 IOPS/GiB when this parameter has a value < 20. To be compatible with the Swagger Python client, the value '0' is accepted but the actual value applied is the default IOPS/GiB specified during volume creation.  # noqa: E501

        :return: The max_read_iops of this BodyVolumeAttach.  # noqa: E501
        :rtype: int
        """
        return self._max_read_iops

    @max_read_iops.setter
    def max_read_iops(self, max_read_iops):
        """Sets the max_read_iops of this BodyVolumeAttach.

        If specified, the max_read_iops setting overrides the QoS settings used during volume creation. In release <= 4.1, this setting  also applies to the min_read_iops since max=min. In later releases however this setting refers exclusively to max_read_iops. When specified in addition to the max_read_iops_ratio, the greater computed value will be set. The datapath will deliver a minimum of 20 IOPS/GiB when this parameter has a value < 20. To be compatible with the Swagger Python client, the value '0' is accepted but the actual value applied is the default IOPS/GiB specified during volume creation.  # noqa: E501

        :param max_read_iops: The max_read_iops of this BodyVolumeAttach.  # noqa: E501
        :type: int
        """
        if max_read_iops is not None and max_read_iops > 250000:  # noqa: E501
            raise ValueError("Invalid value for `max_read_iops`, must be a value less than or equal to `250000`")  # noqa: E501
        if max_read_iops is not None and max_read_iops < 0:  # noqa: E501
            raise ValueError("Invalid value for `max_read_iops`, must be a value greater than or equal to `0`")  # noqa: E501

        self._max_read_iops = max_read_iops

    @property
    def host_lba_size(self):
        """Gets the host_lba_size of this BodyVolumeAttach.  # noqa: E501

        Block size defaults to 4KiB when not specified. The 512Byte size is used by ESXi host.  # noqa: E501

        :return: The host_lba_size of this BodyVolumeAttach.  # noqa: E501
        :rtype: int
        """
        return self._host_lba_size

    @host_lba_size.setter
    def host_lba_size(self, host_lba_size):
        """Sets the host_lba_size of this BodyVolumeAttach.

        Block size defaults to 4KiB when not specified. The 512Byte size is used by ESXi host.  # noqa: E501

        :param host_lba_size: The host_lba_size of this BodyVolumeAttach.  # noqa: E501
        :type: int
        """
        allowed_values = [512, 4096]  # noqa: E501
        if host_lba_size not in allowed_values:
            raise ValueError(
                "Invalid value for `host_lba_size` ({0}), must be one of {1}"  # noqa: E501
                .format(host_lba_size, allowed_values)
            )

        self._host_lba_size = host_lba_size

    @property
    def queue_depth(self):
        """Gets the queue_depth of this BodyVolumeAttach.  # noqa: E501

        Indicates the max number of outstanding I/O requests per connection. To be compatible with the Swagger Python client, the value '0' is accepted. The actual queue_depth offered by the datapath to a host client is 4 if 0 <= queue_depth < 4 Note: Users must ensure that the queue_depth * max_connections <= 1024  # noqa: E501

        :return: The queue_depth of this BodyVolumeAttach.  # noqa: E501
        :rtype: int
        """
        return self._queue_depth

    @queue_depth.setter
    def queue_depth(self, queue_depth):
        """Sets the queue_depth of this BodyVolumeAttach.

        Indicates the max number of outstanding I/O requests per connection. To be compatible with the Swagger Python client, the value '0' is accepted. The actual queue_depth offered by the datapath to a host client is 4 if 0 <= queue_depth < 4 Note: Users must ensure that the queue_depth * max_connections <= 1024  # noqa: E501

        :param queue_depth: The queue_depth of this BodyVolumeAttach.  # noqa: E501
        :type: int
        """
        if queue_depth is not None and queue_depth > 128:  # noqa: E501
            raise ValueError("Invalid value for `queue_depth`, must be a value less than or equal to `128`")  # noqa: E501
        if queue_depth is not None and queue_depth < 0:  # noqa: E501
            raise ValueError("Invalid value for `queue_depth`, must be a value greater than or equal to `0`")  # noqa: E501

        self._queue_depth = queue_depth

    def to_dict(self):
        """Returns the model properties as a dict"""
        result = {}

        for attr, _ in self.swagger_types.items():
            value = getattr(self, attr)
            if isinstance(value, list):
                result[attr] = list(map(
                    lambda x: x.to_dict() if hasattr(x, "to_dict") else x,
                    value
                ))
            elif hasattr(value, "to_dict"):
                result[attr] = value.to_dict()
            elif isinstance(value, dict):
                result[attr] = dict(map(
                    lambda item: (item[0], item[1].to_dict())
                    if hasattr(item[1], "to_dict") else item,
                    value.items()
                ))
            else:
                result[attr] = value
        if issubclass(BodyVolumeAttach, dict):
            for key, value in self.items():
                result[key] = value

        return result

    def to_str(self):
        """Returns the string representation of the model"""
        return pprint.pformat(self.to_dict())

    def __repr__(self):
        """For `print` and `pprint`"""
        return self.to_str()

    def __eq__(self, other):
        """Returns true if both objects are equal"""
        if not isinstance(other, BodyVolumeAttach):
            return False

        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        """Returns true if both objects are not equal"""
        return not self == other


class BodyVolumeIntentCreate(object):
    """NOTE: This class is auto generated by the swagger code generator program

    Do not edit the class manually.
    """

    """
    Attributes:
      swagger_types (dict): The key is attribute name
                            and the value is attribute type.
      attribute_map (dict): The key is attribute name
                            and the value is json key in definition.
    """
    swagger_types = {
        'name': 'str',
        'vol_type': 'VolumeTypes',
        'capacity': 'int',
        'compression_effort': 'int',
        'qos_band': 'int',
        'data_protection': 'DataProtection',
        'encrypt': 'bool',
        'kmip_secret_key': 'str',
        'crc_enable': 'bool',
        'is_clone': 'bool',
        'clone_source_volume_uuid': 'str',
        'snap_support': 'bool',
        'space_allocation_policy': 'SpaceAllocationPolicy',
        'block_size': 'BlockSize',
        'initialize_to_zeros': 'bool',
        'additional_fields': 'AdditionalFields',
        'fd_op': 'str',
        'fault_domain_ids': 'list[str]'
    }

    attribute_map = {
        'name': 'name',
        'vol_type': 'vol_type',
        'capacity': 'capacity',
        'compression_effort': 'compression_effort',
        'qos_band': 'qos_band',
        'data_protection': 'data_protection',
        'encrypt': 'encrypt',
        'kmip_secret_key': 'kmip_secret_key',
        'crc_enable': 'crc_enable',
        'is_clone': 'is_clone',
        'clone_source_volume_uuid': 'clone_source_volume_uuid',
        'snap_support': 'snap_support',
        'space_allocation_policy': 'space_allocation_policy',
        'block_size': 'block_size',
        'initialize_to_zeros': 'initialize_to_zeros',
        'additional_fields': 'additional_fields',
        'fd_op': 'fd_op',
        'fault_domain_ids': 'fault_domain_ids'
    }

    def __init__(self, name=None, vol_type=None, capacity=None, compression_effort=None, qos_band=None, data_protection=None, encrypt=None, kmip_secret_key=None, crc_enable=None, is_clone=None, clone_source_volume_uuid=None, snap_support=None, space_allocation_policy=None, block_size=None, initialize_to_zeros=None, additional_fields=None, fd_op=None, fault_domain_ids=None):  # noqa: E501
        """BodyVolumeIntentCreate - a model defined in Swagger"""  # noqa: E501

        self._name = None
        self._vol_type = None
        self._capacity = None
        self._compression_effort = None
        self._qos_band = None
        self._data_protection = None
        self._encrypt = None
        self._kmip_secret_key = None
        self._crc_enable = None
        self._is_clone = None
        self._clone_source_volume_uuid = None
        self._snap_support = None
        self._space_allocation_policy = None
        self._block_size = None
        self._initialize_to_zeros = None
        self._additional_fields = None
        self._fd_op = None
        self._fault_domain_ids = None
        self.discriminator = None

        self.name = name
        self.vol_type = vol_type
        self.capacity = capacity
        if compression_effort is not None:
            self.compression_effort = compression_effort
        if qos_band is not None:
            self.qos_band = qos_band
        if data_protection is not None:
            self.data_protection = data_protection
        if encrypt is not None:
            self.encrypt = encrypt
        if kmip_secret_key is not None:
            self.kmip_secret_key = kmip_secret_key
        if crc_enable is not None:
            self.crc_enable = crc_enable
        if is_clone is not None:
            self.is_clone = is_clone
        if clone_source_volume_uuid is not None:
            self.clone_source_volume_uuid = clone_source_volume_uuid
        if snap_support is not None:
            self.snap_support = snap_support
        if space_allocation_policy is not None:
            self.space_allocation_policy = space_allocation_policy
        if block_size is not None:
            self.block_size = block_size
        if initialize_to_zeros is not None:
            self.initialize_to_zeros = initialize_to_zeros
        if additional_fields is not None:
            self.additional_fields = additional_fields
        if fd_op is not None:
            self.fd_op = fd_op
        if fault_domain_ids is not None:
            self.fault_domain_ids = fault_domain_ids

    @property
    def name(self):
        """Gets the name of this BodyVolumeIntentCreate.  # noqa: E501


        :return: The name of this BodyVolumeIntentCreate.  # noqa: E501
        :rtype: str
        """
        return self._name

    @name.setter
    def name(self, name):
        """Sets the name of this BodyVolumeIntentCreate.


        :param name: The name of this BodyVolumeIntentCreate.  # noqa: E501
        :type: str
        """
        if name is None:
            raise ValueError("Invalid value for `name`, must not be `None`")  # noqa: E501
        if name is not None and len(name) > 255:
            raise ValueError("Invalid value for `name`, length must be less than or equal to `255`")  # noqa: E501
        if name is not None and len(name) < 1:
            raise ValueError("Invalid value for `name`, length must be greater than or equal to `1`")  # noqa: E501
        if name is not None and not re.search(r'^[A-Za-z0-9_\\-\\.\\:]+$', name):  # noqa: E501
            raise ValueError(r"Invalid value for `name`, must be a follow pattern or equal to `/^[A-Za-z0-9_\\-\\.\\:]+$/`")  # noqa: E501

        self._name = name

    @property
    def vol_type(self):
        """Gets the vol_type of this BodyVolumeIntentCreate.  # noqa: E501


        :return: The vol_type of this BodyVolumeIntentCreate.  # noqa: E501
        :rtype: VolumeTypes
        """
        return self._vol_type

    @vol_type.setter
    def vol_type(self, vol_type):
        """Sets the vol_type of this BodyVolumeIntentCreate.


        :param vol_type: The vol_type of this BodyVolumeIntentCreate.  # noqa: E501
        :type: VolumeTypes
        """
        if vol_type is None:
            raise ValueError("Invalid value for `vol_type`, must not be `None`")  # noqa: E501

        self._vol_type = vol_type

    @property
    def capacity(self):
        """Gets the capacity of this BodyVolumeIntentCreate.  # noqa: E501


        :return: The capacity of this BodyVolumeIntentCreate.  # noqa: E501
        :rtype: int
        """
        return self._capacity

    @capacity.setter
    def capacity(self, capacity):
        """Sets the capacity of this BodyVolumeIntentCreate.


        :param capacity: The capacity of this BodyVolumeIntentCreate.  # noqa: E501
        :type: int
        """
        if capacity is None:
            raise ValueError("Invalid value for `capacity`, must not be `None`")  # noqa: E501

        self._capacity = capacity

    @property
    def compression_effort(self):
        """Gets the compression_effort of this BodyVolumeIntentCreate.  # noqa: E501


        :return: The compression_effort of this BodyVolumeIntentCreate.  # noqa: E501
        :rtype: int
        """
        return self._compression_effort

    @compression_effort.setter
    def compression_effort(self, compression_effort):
        """Sets the compression_effort of this BodyVolumeIntentCreate.


        :param compression_effort: The compression_effort of this BodyVolumeIntentCreate.  # noqa: E501
        :type: int
        """
        if compression_effort is not None and compression_effort > 8:  # noqa: E501
            raise ValueError("Invalid value for `compression_effort`, must be a value less than or equal to `8`")  # noqa: E501
        if compression_effort is not None and compression_effort < 0:  # noqa: E501
            raise ValueError("Invalid value for `compression_effort`, must be a value greater than or equal to `0`")  # noqa: E501

        self._compression_effort = compression_effort

    @property
    def qos_band(self):
        """Gets the qos_band of this BodyVolumeIntentCreate.  # noqa: E501

        index of the QoS band  # noqa: E501

        :return: The qos_band of this BodyVolumeIntentCreate.  # noqa: E501
        :rtype: int
        """
        return self._qos_band

    @qos_band.setter
    def qos_band(self, qos_band):
        """Sets the qos_band of this BodyVolumeIntentCreate.

        index of the QoS band  # noqa: E501

        :param qos_band: The qos_band of this BodyVolumeIntentCreate.  # noqa: E501
        :type: int
        """

        self._qos_band = qos_band

    @property
    def data_protection(self):
        """Gets the data_protection of this BodyVolumeIntentCreate.  # noqa: E501


        :return: The data_protection of this BodyVolumeIntentCreate.  # noqa: E501
        :rtype: DataProtection
        """
        return self._data_protection

    @data_protection.setter
    def data_protection(self, data_protection):
        """Sets the data_protection of this BodyVolumeIntentCreate.


        :param data_protection: The data_protection of this BodyVolumeIntentCreate.  # noqa: E501
        :type: DataProtection
        """

        self._data_protection = data_protection

    @property
    def encrypt(self):
        """Gets the encrypt of this BodyVolumeIntentCreate.  # noqa: E501


        :return: The encrypt of this BodyVolumeIntentCreate.  # noqa: E501
        :rtype: bool
        """
        return self._encrypt

    @encrypt.setter
    def encrypt(self, encrypt):
        """Sets the encrypt of this BodyVolumeIntentCreate.


        :param encrypt: The encrypt of this BodyVolumeIntentCreate.  # noqa: E501
        :type: bool
        """

        self._encrypt = encrypt

    @property
    def kmip_secret_key(self):
        """Gets the kmip_secret_key of this BodyVolumeIntentCreate.  # noqa: E501

        Key to the KMIP secret used for volume encryption  # noqa: E501

        :return: The kmip_secret_key of this BodyVolumeIntentCreate.  # noqa: E501
        :rtype: str
        """
        return self._kmip_secret_key

    @kmip_secret_key.setter
    def kmip_secret_key(self, kmip_secret_key):
        """Sets the kmip_secret_key of this BodyVolumeIntentCreate.

        Key to the KMIP secret used for volume encryption  # noqa: E501

        :param kmip_secret_key: The kmip_secret_key of this BodyVolumeIntentCreate.  # noqa: E501
        :type: str
        """

        self._kmip_secret_key = kmip_secret_key

    @property
    def crc_enable(self):
        """Gets the crc_enable of this BodyVolumeIntentCreate.  # noqa: E501


        :return: The crc_enable of this BodyVolumeIntentCreate.  # noqa: E501
        :rtype: bool
        """
        return self._crc_enable

    @crc_enable.setter
    def crc_enable(self, crc_enable):
        """Sets the crc_enable of this BodyVolumeIntentCreate.


        :param crc_enable: The crc_enable of this BodyVolumeIntentCreate.  # noqa: E501
        :type: bool
        """

        self._crc_enable = crc_enable

    @property
    def is_clone(self):
        """Gets the is_clone of this BodyVolumeIntentCreate.  # noqa: E501


        :return: The is_clone of this BodyVolumeIntentCreate.  # noqa: E501
        :rtype: bool
        """
        return self._is_clone

    @is_clone.setter
    def is_clone(self, is_clone):
        """Sets the is_clone of this BodyVolumeIntentCreate.


        :param is_clone: The is_clone of this BodyVolumeIntentCreate.  # noqa: E501
        :type: bool
        """

        self._is_clone = is_clone

    @property
    def clone_source_volume_uuid(self):
        """Gets the clone_source_volume_uuid of this BodyVolumeIntentCreate.  # noqa: E501


        :return: The clone_source_volume_uuid of this BodyVolumeIntentCreate.  # noqa: E501
        :rtype: str
        """
        return self._clone_source_volume_uuid

    @clone_source_volume_uuid.setter
    def clone_source_volume_uuid(self, clone_source_volume_uuid):
        """Sets the clone_source_volume_uuid of this BodyVolumeIntentCreate.


        :param clone_source_volume_uuid: The clone_source_volume_uuid of this BodyVolumeIntentCreate.  # noqa: E501
        :type: str
        """

        self._clone_source_volume_uuid = clone_source_volume_uuid

    @property
    def snap_support(self):
        """Gets the snap_support of this BodyVolumeIntentCreate.  # noqa: E501


        :return: The snap_support of this BodyVolumeIntentCreate.  # noqa: E501
        :rtype: bool
        """
        return self._snap_support

    @snap_support.setter
    def snap_support(self, snap_support):
        """Sets the snap_support of this BodyVolumeIntentCreate.


        :param snap_support: The snap_support of this BodyVolumeIntentCreate.  # noqa: E501
        :type: bool
        """

        self._snap_support = snap_support

    @property
    def space_allocation_policy(self):
        """Gets the space_allocation_policy of this BodyVolumeIntentCreate.  # noqa: E501


        :return: The space_allocation_policy of this BodyVolumeIntentCreate.  # noqa: E501
        :rtype: SpaceAllocationPolicy
        """
        return self._space_allocation_policy

    @space_allocation_policy.setter
    def space_allocation_policy(self, space_allocation_policy):
        """Sets the space_allocation_policy of this BodyVolumeIntentCreate.


        :param space_allocation_policy: The space_allocation_policy of this BodyVolumeIntentCreate.  # noqa: E501
        :type: SpaceAllocationPolicy
        """

        self._space_allocation_policy = space_allocation_policy

    @property
    def block_size(self):
        """Gets the block_size of this BodyVolumeIntentCreate.  # noqa: E501


        :return: The block_size of this BodyVolumeIntentCreate.  # noqa: E501
        :rtype: BlockSize
        """
        return self._block_size

    @block_size.setter
    def block_size(self, block_size):
        """Sets the block_size of this BodyVolumeIntentCreate.


        :param block_size: The block_size of this BodyVolumeIntentCreate.  # noqa: E501
        :type: BlockSize
        """

        self._block_size = block_size

    @property
    def initialize_to_zeros(self):
        """Gets the initialize_to_zeros of this BodyVolumeIntentCreate.  # noqa: E501

        After creation, volume contents should appear to be initialized to zero.  # noqa: E501

        :return: The initialize_to_zeros of this BodyVolumeIntentCreate.  # noqa: E501
        :rtype: bool
        """
        return self._initialize_to_zeros

    @initialize_to_zeros.setter
    def initialize_to_zeros(self, initialize_to_zeros):
        """Sets the initialize_to_zeros of this BodyVolumeIntentCreate.

        After creation, volume contents should appear to be initialized to zero.  # noqa: E501

        :param initialize_to_zeros: The initialize_to_zeros of this BodyVolumeIntentCreate.  # noqa: E501
        :type: bool
        """

        self._initialize_to_zeros = initialize_to_zeros

    @property
    def additional_fields(self):
        """Gets the additional_fields of this BodyVolumeIntentCreate.  # noqa: E501


        :return: The additional_fields of this BodyVolumeIntentCreate.  # noqa: E501
        :rtype: AdditionalFields
        """
        return self._additional_fields

    @additional_fields.setter
    def additional_fields(self, additional_fields):
        """Sets the additional_fields of this BodyVolumeIntentCreate.


        :param additional_fields: The additional_fields of this BodyVolumeIntentCreate.  # noqa: E501
        :type: AdditionalFields
        """

        self._additional_fields = additional_fields

    @property
    def fd_op(self):
        """Gets the fd_op of this BodyVolumeIntentCreate.  # noqa: E501


        :return: The fd_op of this BodyVolumeIntentCreate.  # noqa: E501
        :rtype: str
        """
        return self._fd_op

    @fd_op.setter
    def fd_op(self, fd_op):
        """Sets the fd_op of this BodyVolumeIntentCreate.


        :param fd_op: The fd_op of this BodyVolumeIntentCreate.  # noqa: E501
        :type: str
        """
        allowed_values = ["SUGGESTED_FD_IDS", "EXCLUDE_FD_IDS", "ASSIGNED_FD_ID"]  # noqa: E501
        if fd_op not in allowed_values:
            raise ValueError(
                "Invalid value for `fd_op` ({0}), must be one of {1}"  # noqa: E501
                .format(fd_op, allowed_values)
            )

        self._fd_op = fd_op

    @property
    def fault_domain_ids(self):
        """Gets the fault_domain_ids of this BodyVolumeIntentCreate.  # noqa: E501

        The new volume should be created in a fault zone different from those of the raw volume UUIDs listed in this array  # noqa: E501

        :return: The fault_domain_ids of this BodyVolumeIntentCreate.  # noqa: E501
        :rtype: list[str]
        """
        return self._fault_domain_ids

    @fault_domain_ids.setter
    def fault_domain_ids(self, fault_domain_ids):
        """Sets the fault_domain_ids of this BodyVolumeIntentCreate.

        The new volume should be created in a fault zone different from those of the raw volume UUIDs listed in this array  # noqa: E501

        :param fault_domain_ids: The fault_domain_ids of this BodyVolumeIntentCreate.  # noqa: E501
        :type: list[str]
        """

        self._fault_domain_ids = fault_domain_ids

    def to_dict(self):
        """Returns the model properties as a dict"""
        result = {}

        for attr, _ in self.swagger_types.items():
            value = getattr(self, attr)
            if isinstance(value, list):
                result[attr] = list(map(
                    lambda x: x.to_dict() if hasattr(x, "to_dict") else x,
                    value
                ))
            elif hasattr(value, "to_dict"):
                result[attr] = value.to_dict()
            elif isinstance(value, dict):
                result[attr] = dict(map(
                    lambda item: (item[0], item[1].to_dict())
                    if hasattr(item[1], "to_dict") else item,
                    value.items()
                ))
            else:
                result[attr] = value
        if issubclass(BodyVolumeIntentCreate, dict):
            for key, value in self.items():
                result[key] = value

        return result

    def to_str(self):
        """Returns the string representation of the model"""
        return pprint.pformat(self.to_dict())

    def __repr__(self):
        """For `print` and `pprint`"""
        return self.to_str()

    def __eq__(self, other):
        """Returns true if both objects are equal"""
        if not isinstance(other, BodyVolumeIntentCreate):
            return False

        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        """Returns true if both objects are not equal"""
        return not self == other


class BodyVolumeSnapshotCreate(object):
    """NOTE: This class is auto generated by the swagger code generator program

    Do not edit the class manually.
    """

    """
    Attributes:
      swagger_types (dict): The key is attribute name
                            and the value is attribute type.
      attribute_map (dict): The key is attribute name
                            and the value is json key in definition.
    """
    swagger_types = {
        'name': 'str'
    }

    attribute_map = {
        'name': 'name'
    }

    def __init__(self, name=None):  # noqa: E501
        """BodyVolumeSnapshotCreate - a model defined in Swagger"""  # noqa: E501

        self._name = None
        self.discriminator = None

        self.name = name

    @property
    def name(self):
        """Gets the name of this BodyVolumeSnapshotCreate.  # noqa: E501


        :return: The name of this BodyVolumeSnapshotCreate.  # noqa: E501
        :rtype: str
        """
        return self._name

    @name.setter
    def name(self, name):
        """Sets the name of this BodyVolumeSnapshotCreate.


        :param name: The name of this BodyVolumeSnapshotCreate.  # noqa: E501
        :type: str
        """
        if name is None:
            raise ValueError("Invalid value for `name`, must not be `None`")  # noqa: E501

        self._name = name

    def to_dict(self):
        """Returns the model properties as a dict"""
        result = {}

        for attr, _ in self.swagger_types.items():
            value = getattr(self, attr)
            if isinstance(value, list):
                result[attr] = list(map(
                    lambda x: x.to_dict() if hasattr(x, "to_dict") else x,
                    value
                ))
            elif hasattr(value, "to_dict"):
                result[attr] = value.to_dict()
            elif isinstance(value, dict):
                result[attr] = dict(map(
                    lambda item: (item[0], item[1].to_dict())
                    if hasattr(item[1], "to_dict") else item,
                    value.items()
                ))
            else:
                result[attr] = value
        if issubclass(BodyVolumeSnapshotCreate, dict):
            for key, value in self.items():
                result[key] = value

        return result

    def to_str(self):
        """Returns the string representation of the model"""
        return pprint.pformat(self.to_dict())

    def __repr__(self):
        """For `print` and `pprint`"""
        return self.to_str()

    def __eq__(self, other):
        """Returns true if both objects are equal"""
        if not isinstance(other, BodyVolumeSnapshotCreate):
            return False

        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        """Returns true if both objects are not equal"""
        return not self == other


class BodyVolumeUpdate(object):
    """NOTE: This class is auto generated by the swagger code generator program

    Do not edit the class manually.
    """

    """
    Attributes:
      swagger_types (dict): The key is attribute name
                            and the value is attribute type.
      attribute_map (dict): The key is attribute name
                            and the value is json key in definition.
    """
    swagger_types = {
        'op': 'VolumeUpdateOp',
        'issue_rebuild': 'bool',
        'failed_vol': 'str',
        'failed_uuid': 'str',
        'dpu_id': 'str',
        'state': 'ResourceState',
        'capacity': 'int',
        'qos_band': 'int',
        'vol_type': 'VolumeTypes',
        'data_protection': 'DataProtection',
        'new_vol_name': 'str'
    }

    attribute_map = {
        'op': 'op',
        'issue_rebuild': 'issue_rebuild',
        'failed_vol': 'failed_vol',
        'failed_uuid': 'failed_uuid',
        'dpu_id': 'dpu_id',
        'state': 'state',
        'capacity': 'capacity',
        'qos_band': 'qos_band',
        'vol_type': 'vol_type',
        'data_protection': 'data_protection',
        'new_vol_name': 'new_vol_name'
    }

    def __init__(self, op=None, issue_rebuild=None, failed_vol=None, failed_uuid=None, dpu_id=None, state=None, capacity=None, qos_band=None, vol_type=None, data_protection=None, new_vol_name=None):  # noqa: E501
        """BodyVolumeUpdate - a model defined in Swagger"""  # noqa: E501

        self._op = None
        self._issue_rebuild = None
        self._failed_vol = None
        self._failed_uuid = None
        self._dpu_id = None
        self._state = None
        self._capacity = None
        self._qos_band = None
        self._vol_type = None
        self._data_protection = None
        self._new_vol_name = None
        self.discriminator = None

        self.op = op
        if issue_rebuild is not None:
            self.issue_rebuild = issue_rebuild
        if failed_vol is not None:
            self.failed_vol = failed_vol
        if failed_uuid is not None:
            self.failed_uuid = failed_uuid
        if dpu_id is not None:
            self.dpu_id = dpu_id
        if state is not None:
            self.state = state
        if capacity is not None:
            self.capacity = capacity
        if qos_band is not None:
            self.qos_band = qos_band
        if vol_type is not None:
            self.vol_type = vol_type
        if data_protection is not None:
            self.data_protection = data_protection
        if new_vol_name is not None:
            self.new_vol_name = new_vol_name

    @property
    def op(self):
        """Gets the op of this BodyVolumeUpdate.  # noqa: E501


        :return: The op of this BodyVolumeUpdate.  # noqa: E501
        :rtype: VolumeUpdateOp
        """
        return self._op

    @op.setter
    def op(self, op):
        """Sets the op of this BodyVolumeUpdate.


        :param op: The op of this BodyVolumeUpdate.  # noqa: E501
        :type: VolumeUpdateOp
        """
        if op is None:
            raise ValueError("Invalid value for `op`, must not be `None`")  # noqa: E501

        self._op = op

    @property
    def issue_rebuild(self):
        """Gets the issue_rebuild of this BodyVolumeUpdate.  # noqa: E501


        :return: The issue_rebuild of this BodyVolumeUpdate.  # noqa: E501
        :rtype: bool
        """
        return self._issue_rebuild

    @issue_rebuild.setter
    def issue_rebuild(self, issue_rebuild):
        """Sets the issue_rebuild of this BodyVolumeUpdate.


        :param issue_rebuild: The issue_rebuild of this BodyVolumeUpdate.  # noqa: E501
        :type: bool
        """

        self._issue_rebuild = issue_rebuild

    @property
    def failed_vol(self):
        """Gets the failed_vol of this BodyVolumeUpdate.  # noqa: E501


        :return: The failed_vol of this BodyVolumeUpdate.  # noqa: E501
        :rtype: str
        """
        return self._failed_vol

    @failed_vol.setter
    def failed_vol(self, failed_vol):
        """Sets the failed_vol of this BodyVolumeUpdate.


        :param failed_vol: The failed_vol of this BodyVolumeUpdate.  # noqa: E501
        :type: str
        """

        self._failed_vol = failed_vol

    @property
    def failed_uuid(self):
        """Gets the failed_uuid of this BodyVolumeUpdate.  # noqa: E501


        :return: The failed_uuid of this BodyVolumeUpdate.  # noqa: E501
        :rtype: str
        """
        return self._failed_uuid

    @failed_uuid.setter
    def failed_uuid(self, failed_uuid):
        """Sets the failed_uuid of this BodyVolumeUpdate.


        :param failed_uuid: The failed_uuid of this BodyVolumeUpdate.  # noqa: E501
        :type: str
        """

        self._failed_uuid = failed_uuid

    @property
    def dpu_id(self):
        """Gets the dpu_id of this BodyVolumeUpdate.  # noqa: E501

        id of dpu to which this volume is to be moved  # noqa: E501

        :return: The dpu_id of this BodyVolumeUpdate.  # noqa: E501
        :rtype: str
        """
        return self._dpu_id

    @dpu_id.setter
    def dpu_id(self, dpu_id):
        """Sets the dpu_id of this BodyVolumeUpdate.

        id of dpu to which this volume is to be moved  # noqa: E501

        :param dpu_id: The dpu_id of this BodyVolumeUpdate.  # noqa: E501
        :type: str
        """

        self._dpu_id = dpu_id

    @property
    def state(self):
        """Gets the state of this BodyVolumeUpdate.  # noqa: E501


        :return: The state of this BodyVolumeUpdate.  # noqa: E501
        :rtype: ResourceState
        """
        return self._state

    @state.setter
    def state(self, state):
        """Sets the state of this BodyVolumeUpdate.


        :param state: The state of this BodyVolumeUpdate.  # noqa: E501
        :type: ResourceState
        """

        self._state = state

    @property
    def capacity(self):
        """Gets the capacity of this BodyVolumeUpdate.  # noqa: E501


        :return: The capacity of this BodyVolumeUpdate.  # noqa: E501
        :rtype: int
        """
        return self._capacity

    @capacity.setter
    def capacity(self, capacity):
        """Sets the capacity of this BodyVolumeUpdate.


        :param capacity: The capacity of this BodyVolumeUpdate.  # noqa: E501
        :type: int
        """

        self._capacity = capacity

    @property
    def qos_band(self):
        """Gets the qos_band of this BodyVolumeUpdate.  # noqa: E501

        index of the new QoS band  # noqa: E501

        :return: The qos_band of this BodyVolumeUpdate.  # noqa: E501
        :rtype: int
        """
        return self._qos_band

    @qos_band.setter
    def qos_band(self, qos_band):
        """Sets the qos_band of this BodyVolumeUpdate.

        index of the new QoS band  # noqa: E501

        :param qos_band: The qos_band of this BodyVolumeUpdate.  # noqa: E501
        :type: int
        """

        self._qos_band = qos_band

    @property
    def vol_type(self):
        """Gets the vol_type of this BodyVolumeUpdate.  # noqa: E501


        :return: The vol_type of this BodyVolumeUpdate.  # noqa: E501
        :rtype: VolumeTypes
        """
        return self._vol_type

    @vol_type.setter
    def vol_type(self, vol_type):
        """Sets the vol_type of this BodyVolumeUpdate.


        :param vol_type: The vol_type of this BodyVolumeUpdate.  # noqa: E501
        :type: VolumeTypes
        """

        self._vol_type = vol_type

    @property
    def data_protection(self):
        """Gets the data_protection of this BodyVolumeUpdate.  # noqa: E501


        :return: The data_protection of this BodyVolumeUpdate.  # noqa: E501
        :rtype: DataProtection
        """
        return self._data_protection

    @data_protection.setter
    def data_protection(self, data_protection):
        """Sets the data_protection of this BodyVolumeUpdate.


        :param data_protection: The data_protection of this BodyVolumeUpdate.  # noqa: E501
        :type: DataProtection
        """

        self._data_protection = data_protection

    @property
    def new_vol_name(self):
        """Gets the new_vol_name of this BodyVolumeUpdate.  # noqa: E501


        :return: The new_vol_name of this BodyVolumeUpdate.  # noqa: E501
        :rtype: str
        """
        return self._new_vol_name

    @new_vol_name.setter
    def new_vol_name(self, new_vol_name):
        """Sets the new_vol_name of this BodyVolumeUpdate.


        :param new_vol_name: The new_vol_name of this BodyVolumeUpdate.  # noqa: E501
        :type: str
        """
        if new_vol_name is not None and len(new_vol_name) > 255:
            raise ValueError("Invalid value for `new_vol_name`, length must be less than or equal to `255`")  # noqa: E501
        if new_vol_name is not None and len(new_vol_name) < 1:
            raise ValueError("Invalid value for `new_vol_name`, length must be greater than or equal to `1`")  # noqa: E501
        if new_vol_name is not None and not re.search(r'^[A-Za-z0-9_\\-\\.\\:]+$', new_vol_name):  # noqa: E501
            raise ValueError(r"Invalid value for `new_vol_name`, must be a follow pattern or equal to `/^[A-Za-z0-9_\\-\\.\\:]+$/`")  # noqa: E501

        self._new_vol_name = new_vol_name

    def to_dict(self):
        """Returns the model properties as a dict"""
        result = {}

        for attr, _ in self.swagger_types.items():
            value = getattr(self, attr)
            if isinstance(value, list):
                result[attr] = list(map(
                    lambda x: x.to_dict() if hasattr(x, "to_dict") else x,
                    value
                ))
            elif hasattr(value, "to_dict"):
                result[attr] = value.to_dict()
            elif isinstance(value, dict):
                result[attr] = dict(map(
                    lambda item: (item[0], item[1].to_dict())
                    if hasattr(item[1], "to_dict") else item,
                    value.items()
                ))
            else:
                result[attr] = value
        if issubclass(BodyVolumeUpdate, dict):
            for key, value in self.items():
                result[key] = value

        return result

    def to_str(self):
        """Returns the string representation of the model"""
        return pprint.pformat(self.to_dict())

    def __repr__(self):
        """For `print` and `pprint`"""
        return self.to_str()

    def __eq__(self, other):
        """Returns true if both objects are equal"""
        if not isinstance(other, BodyVolumeUpdate):
            return False

        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        """Returns true if both objects are not equal"""
        return not self == other


class CommonResponseFields(object):
    """NOTE: This class is auto generated by the swagger code generator program

    Do not edit the class manually.
    """

    """
    Attributes:
      swagger_types (dict): The key is attribute name
                            and the value is attribute type.
      attribute_map (dict): The key is attribute name
                            and the value is json key in definition.
    """
    swagger_types = {
        'status': 'bool',
        'message': 'str',
        'error_message': 'str',
        'warning': 'str'
    }

    attribute_map = {
        'status': 'status',
        'message': 'message',
        'error_message': 'error_message',
        'warning': 'warning'
    }

    def __init__(self, status=None, message=None, error_message=None, warning=None):  # noqa: E501
        """CommonResponseFields - a model defined in Swagger"""  # noqa: E501

        self._status = None
        self._message = None
        self._error_message = None
        self._warning = None
        self.discriminator = None

        self.status = status
        if message is not None:
            self.message = message
        if error_message is not None:
            self.error_message = error_message
        if warning is not None:
            self.warning = warning

    @property
    def status(self):
        """Gets the status of this CommonResponseFields.  # noqa: E501


        :return: The status of this CommonResponseFields.  # noqa: E501
        :rtype: bool
        """
        return self._status

    @status.setter
    def status(self, status):
        """Sets the status of this CommonResponseFields.


        :param status: The status of this CommonResponseFields.  # noqa: E501
        :type: bool
        """
        if status is None:
            raise ValueError("Invalid value for `status`, must not be `None`")  # noqa: E501

        self._status = status

    @property
    def message(self):
        """Gets the message of this CommonResponseFields.  # noqa: E501


        :return: The message of this CommonResponseFields.  # noqa: E501
        :rtype: str
        """
        return self._message

    @message.setter
    def message(self, message):
        """Sets the message of this CommonResponseFields.


        :param message: The message of this CommonResponseFields.  # noqa: E501
        :type: str
        """

        self._message = message

    @property
    def error_message(self):
        """Gets the error_message of this CommonResponseFields.  # noqa: E501


        :return: The error_message of this CommonResponseFields.  # noqa: E501
        :rtype: str
        """
        return self._error_message

    @error_message.setter
    def error_message(self, error_message):
        """Sets the error_message of this CommonResponseFields.


        :param error_message: The error_message of this CommonResponseFields.  # noqa: E501
        :type: str
        """

        self._error_message = error_message

    @property
    def warning(self):
        """Gets the warning of this CommonResponseFields.  # noqa: E501


        :return: The warning of this CommonResponseFields.  # noqa: E501
        :rtype: str
        """
        return self._warning

    @warning.setter
    def warning(self, warning):
        """Sets the warning of this CommonResponseFields.


        :param warning: The warning of this CommonResponseFields.  # noqa: E501
        :type: str
        """

        self._warning = warning

    def to_dict(self):
        """Returns the model properties as a dict"""
        result = {}

        for attr, _ in self.swagger_types.items():
            value = getattr(self, attr)
            if isinstance(value, list):
                result[attr] = list(map(
                    lambda x: x.to_dict() if hasattr(x, "to_dict") else x,
                    value
                ))
            elif hasattr(value, "to_dict"):
                result[attr] = value.to_dict()
            elif isinstance(value, dict):
                result[attr] = dict(map(
                    lambda item: (item[0], item[1].to_dict())
                    if hasattr(item[1], "to_dict") else item,
                    value.items()
                ))
            else:
                result[attr] = value
        if issubclass(CommonResponseFields, dict):
            for key, value in self.items():
                result[key] = value

        return result

    def to_str(self):
        """Returns the string representation of the model"""
        return pprint.pformat(self.to_dict())

    def __repr__(self):
        """For `print` and `pprint`"""
        return self.to_str()

    def __eq__(self, other):
        """Returns true if both objects are equal"""
        if not isinstance(other, CommonResponseFields):
            return False

        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        """Returns true if both objects are not equal"""
        return not self == other


class DataProtection(object):
    """NOTE: This class is auto generated by the swagger code generator program

    Do not edit the class manually.
    """

    """
    Attributes:
      swagger_types (dict): The key is attribute name
                            and the value is attribute type.
      attribute_map (dict): The key is attribute name
                            and the value is json key in definition.
    """
    swagger_types = {
        'num_redundant_dpus': 'int',
        'num_data_disks': 'int',
        'num_failed_disks': 'int'
    }

    attribute_map = {
        'num_redundant_dpus': 'num_redundant_dpus',
        'num_data_disks': 'num_data_disks',
        'num_failed_disks': 'num_failed_disks'
    }

    def __init__(self, num_redundant_dpus=None, num_data_disks=None, num_failed_disks=None):  # noqa: E501
        """DataProtection - a model defined in Swagger"""  # noqa: E501

        self._num_redundant_dpus = None
        self._num_data_disks = None
        self._num_failed_disks = None
        self.discriminator = None

        if num_redundant_dpus is not None:
            self.num_redundant_dpus = num_redundant_dpus
        if num_data_disks is not None:
            self.num_data_disks = num_data_disks
        if num_failed_disks is not None:
            self.num_failed_disks = num_failed_disks

    @property
    def num_redundant_dpus(self):
        """Gets the num_redundant_dpus of this DataProtection.  # noqa: E501


        :return: The num_redundant_dpus of this DataProtection.  # noqa: E501
        :rtype: int
        """
        return self._num_redundant_dpus

    @num_redundant_dpus.setter
    def num_redundant_dpus(self, num_redundant_dpus):
        """Sets the num_redundant_dpus of this DataProtection.


        :param num_redundant_dpus: The num_redundant_dpus of this DataProtection.  # noqa: E501
        :type: int
        """
        if num_redundant_dpus is not None and num_redundant_dpus < 0:  # noqa: E501
            raise ValueError("Invalid value for `num_redundant_dpus`, must be a value greater than or equal to `0`")  # noqa: E501

        self._num_redundant_dpus = num_redundant_dpus

    @property
    def num_data_disks(self):
        """Gets the num_data_disks of this DataProtection.  # noqa: E501


        :return: The num_data_disks of this DataProtection.  # noqa: E501
        :rtype: int
        """
        return self._num_data_disks

    @num_data_disks.setter
    def num_data_disks(self, num_data_disks):
        """Sets the num_data_disks of this DataProtection.


        :param num_data_disks: The num_data_disks of this DataProtection.  # noqa: E501
        :type: int
        """
        if num_data_disks is not None and num_data_disks < 0:  # noqa: E501
            raise ValueError("Invalid value for `num_data_disks`, must be a value greater than or equal to `0`")  # noqa: E501

        self._num_data_disks = num_data_disks

    @property
    def num_failed_disks(self):
        """Gets the num_failed_disks of this DataProtection.  # noqa: E501


        :return: The num_failed_disks of this DataProtection.  # noqa: E501
        :rtype: int
        """
        return self._num_failed_disks

    @num_failed_disks.setter
    def num_failed_disks(self, num_failed_disks):
        """Sets the num_failed_disks of this DataProtection.


        :param num_failed_disks: The num_failed_disks of this DataProtection.  # noqa: E501
        :type: int
        """
        if num_failed_disks is not None and num_failed_disks < 0:  # noqa: E501
            raise ValueError("Invalid value for `num_failed_disks`, must be a value greater than or equal to `0`")  # noqa: E501

        self._num_failed_disks = num_failed_disks

    def to_dict(self):
        """Returns the model properties as a dict"""
        result = {}

        for attr, _ in self.swagger_types.items():
            value = getattr(self, attr)
            if isinstance(value, list):
                result[attr] = list(map(
                    lambda x: x.to_dict() if hasattr(x, "to_dict") else x,
                    value
                ))
            elif hasattr(value, "to_dict"):
                result[attr] = value.to_dict()
            elif isinstance(value, dict):
                result[attr] = dict(map(
                    lambda item: (item[0], item[1].to_dict())
                    if hasattr(item[1], "to_dict") else item,
                    value.items()
                ))
            else:
                result[attr] = value
        if issubclass(DataProtection, dict):
            for key, value in self.items():
                result[key] = value

        return result

    def to_str(self):
        """Returns the string representation of the model"""
        return pprint.pformat(self.to_dict())

    def __repr__(self):
        """For `print` and `pprint`"""
        return self.to_str()

    def __eq__(self, other):
        """Returns true if both objects are equal"""
        if not isinstance(other, DataProtection):
            return False

        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        """Returns true if both objects are not equal"""
        return not self == other


class DataWithHostInfo(object):
    """NOTE: This class is auto generated by the swagger code generator program

    Do not edit the class manually.
    """

    """
    Attributes:
      swagger_types (dict): The key is attribute name
                            and the value is attribute type.
      attribute_map (dict): The key is attribute name
                            and the value is json key in definition.
    """
    swagger_types = {
        'data': 'HostInfo'
    }

    attribute_map = {
        'data': 'data'
    }

    def __init__(self, data=None):  # noqa: E501
        """DataWithHostInfo - a model defined in Swagger"""  # noqa: E501

        self._data = None
        self.discriminator = None

        if data is not None:
            self.data = data

    @property
    def data(self):
        """Gets the data of this DataWithHostInfo.  # noqa: E501


        :return: The data of this DataWithHostInfo.  # noqa: E501
        :rtype: HostInfo
        """
        return self._data

    @data.setter
    def data(self, data):
        """Sets the data of this DataWithHostInfo.


        :param data: The data of this DataWithHostInfo.  # noqa: E501
        :type: HostInfo
        """

        self._data = data

    def to_dict(self):
        """Returns the model properties as a dict"""
        result = {}

        for attr, _ in self.swagger_types.items():
            value = getattr(self, attr)
            if isinstance(value, list):
                result[attr] = list(map(
                    lambda x: x.to_dict() if hasattr(x, "to_dict") else x,
                    value
                ))
            elif hasattr(value, "to_dict"):
                result[attr] = value.to_dict()
            elif isinstance(value, dict):
                result[attr] = dict(map(
                    lambda item: (item[0], item[1].to_dict())
                    if hasattr(item[1], "to_dict") else item,
                    value.items()
                ))
            else:
                result[attr] = value
        if issubclass(DataWithHostInfo, dict):
            for key, value in self.items():
                result[key] = value

        return result

    def to_str(self):
        """Returns the string representation of the model"""
        return pprint.pformat(self.to_dict())

    def __repr__(self):
        """For `print` and `pprint`"""
        return self.to_str()

    def __eq__(self, other):
        """Returns true if both objects are equal"""
        if not isinstance(other, DataWithHostInfo):
            return False

        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        """Returns true if both objects are not equal"""
        return not self == other


class DataWithUuidData(object):
    """NOTE: This class is auto generated by the swagger code generator program

    Do not edit the class manually.
    """

    """
    Attributes:
      swagger_types (dict): The key is attribute name
                            and the value is attribute type.
      attribute_map (dict): The key is attribute name
                            and the value is json key in definition.
    """
    swagger_types = {
        'uuid': 'str'
    }

    attribute_map = {
        'uuid': 'uuid'
    }

    def __init__(self, uuid=None):  # noqa: E501
        """DataWithUuidData - a model defined in Swagger"""  # noqa: E501

        self._uuid = None
        self.discriminator = None

        self.uuid = uuid

    @property
    def uuid(self):
        """Gets the uuid of this DataWithUuidData.  # noqa: E501


        :return: The uuid of this DataWithUuidData.  # noqa: E501
        :rtype: str
        """
        return self._uuid

    @uuid.setter
    def uuid(self, uuid):
        """Sets the uuid of this DataWithUuidData.


        :param uuid: The uuid of this DataWithUuidData.  # noqa: E501
        :type: str
        """
        if uuid is None:
            raise ValueError("Invalid value for `uuid`, must not be `None`")  # noqa: E501

        self._uuid = uuid

    def to_dict(self):
        """Returns the model properties as a dict"""
        result = {}

        for attr, _ in self.swagger_types.items():
            value = getattr(self, attr)
            if isinstance(value, list):
                result[attr] = list(map(
                    lambda x: x.to_dict() if hasattr(x, "to_dict") else x,
                    value
                ))
            elif hasattr(value, "to_dict"):
                result[attr] = value.to_dict()
            elif isinstance(value, dict):
                result[attr] = dict(map(
                    lambda item: (item[0], item[1].to_dict())
                    if hasattr(item[1], "to_dict") else item,
                    value.items()
                ))
            else:
                result[attr] = value
        if issubclass(DataWithUuidData, dict):
            for key, value in self.items():
                result[key] = value

        return result

    def to_str(self):
        """Returns the string representation of the model"""
        return pprint.pformat(self.to_dict())

    def __repr__(self):
        """For `print` and `pprint`"""
        return self.to_str()

    def __eq__(self, other):
        """Returns true if both objects are equal"""
        if not isinstance(other, DataWithUuidData):
            return False

        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        """Returns true if both objects are not equal"""
        return not self == other


class DataWithListOfHostUuidsData(object):
    """NOTE: This class is auto generated by the swagger code generator program

    Do not edit the class manually.
    """

    """
    Attributes:
      swagger_types (dict): The key is attribute name
                            and the value is attribute type.
      attribute_map (dict): The key is attribute name
                            and the value is json key in definition.
    """
    swagger_types = {
        'total_hosts_with_fac': 'int',
        'total_hosts_without_fac': 'int',
        'last_uuid_datetime': 'datetime',
        'host_uuids': 'list[str]'
    }

    attribute_map = {
        'total_hosts_with_fac': 'total_hosts_with_fac',
        'total_hosts_without_fac': 'total_hosts_without_fac',
        'last_uuid_datetime': 'last_uuid_datetime',
        'host_uuids': 'host_uuids'
    }

    def __init__(self, total_hosts_with_fac=None, total_hosts_without_fac=None, last_uuid_datetime=None, host_uuids=None):  # noqa: E501
        """DataWithListOfHostUuidsData - a model defined in Swagger"""  # noqa: E501

        self._total_hosts_with_fac = None
        self._total_hosts_without_fac = None
        self._last_uuid_datetime = None
        self._host_uuids = None
        self.discriminator = None

        if total_hosts_with_fac is not None:
            self.total_hosts_with_fac = total_hosts_with_fac
        if total_hosts_without_fac is not None:
            self.total_hosts_without_fac = total_hosts_without_fac
        if last_uuid_datetime is not None:
            self.last_uuid_datetime = last_uuid_datetime
        if host_uuids is not None:
            self.host_uuids = host_uuids

    @property
    def total_hosts_with_fac(self):
        """Gets the total_hosts_with_fac of this DataWithListOfHostUuidsData.  # noqa: E501

        Count of hosts/servers which have at least one FAC card installed  # noqa: E501

        :return: The total_hosts_with_fac of this DataWithListOfHostUuidsData.  # noqa: E501
        :rtype: int
        """
        return self._total_hosts_with_fac

    @total_hosts_with_fac.setter
    def total_hosts_with_fac(self, total_hosts_with_fac):
        """Sets the total_hosts_with_fac of this DataWithListOfHostUuidsData.

        Count of hosts/servers which have at least one FAC card installed  # noqa: E501

        :param total_hosts_with_fac: The total_hosts_with_fac of this DataWithListOfHostUuidsData.  # noqa: E501
        :type: int
        """

        self._total_hosts_with_fac = total_hosts_with_fac

    @property
    def total_hosts_without_fac(self):
        """Gets the total_hosts_without_fac of this DataWithListOfHostUuidsData.  # noqa: E501

        Count of hosts/servers which use non-Fungible NIC interfaces  # noqa: E501

        :return: The total_hosts_without_fac of this DataWithListOfHostUuidsData.  # noqa: E501
        :rtype: int
        """
        return self._total_hosts_without_fac

    @total_hosts_without_fac.setter
    def total_hosts_without_fac(self, total_hosts_without_fac):
        """Sets the total_hosts_without_fac of this DataWithListOfHostUuidsData.

        Count of hosts/servers which use non-Fungible NIC interfaces  # noqa: E501

        :param total_hosts_without_fac: The total_hosts_without_fac of this DataWithListOfHostUuidsData.  # noqa: E501
        :type: int
        """

        self._total_hosts_without_fac = total_hosts_without_fac

    @property
    def last_uuid_datetime(self):
        """Gets the last_uuid_datetime of this DataWithListOfHostUuidsData.  # noqa: E501

        created time for the last host uuid from the list  # noqa: E501

        :return: The last_uuid_datetime of this DataWithListOfHostUuidsData.  # noqa: E501
        :rtype: datetime
        """
        return self._last_uuid_datetime

    @last_uuid_datetime.setter
    def last_uuid_datetime(self, last_uuid_datetime):
        """Sets the last_uuid_datetime of this DataWithListOfHostUuidsData.

        created time for the last host uuid from the list  # noqa: E501

        :param last_uuid_datetime: The last_uuid_datetime of this DataWithListOfHostUuidsData.  # noqa: E501
        :type: datetime
        """

        self._last_uuid_datetime = last_uuid_datetime

    @property
    def host_uuids(self):
        """Gets the host_uuids of this DataWithListOfHostUuidsData.  # noqa: E501

        List of Host UUIDs  # noqa: E501

        :return: The host_uuids of this DataWithListOfHostUuidsData.  # noqa: E501
        :rtype: list[str]
        """
        return self._host_uuids

    @host_uuids.setter
    def host_uuids(self, host_uuids):
        """Sets the host_uuids of this DataWithListOfHostUuidsData.

        List of Host UUIDs  # noqa: E501

        :param host_uuids: The host_uuids of this DataWithListOfHostUuidsData.  # noqa: E501
        :type: list[str]
        """

        self._host_uuids = host_uuids

    def to_dict(self):
        """Returns the model properties as a dict"""
        result = {}

        for attr, _ in self.swagger_types.items():
            value = getattr(self, attr)
            if isinstance(value, list):
                result[attr] = list(map(
                    lambda x: x.to_dict() if hasattr(x, "to_dict") else x,
                    value
                ))
            elif hasattr(value, "to_dict"):
                result[attr] = value.to_dict()
            elif isinstance(value, dict):
                result[attr] = dict(map(
                    lambda item: (item[0], item[1].to_dict())
                    if hasattr(item[1], "to_dict") else item,
                    value.items()
                ))
            else:
                result[attr] = value
        if issubclass(DataWithListOfHostUuidsData, dict):
            for key, value in self.items():
                result[key] = value

        return result

    def to_str(self):
        """Returns the string representation of the model"""
        return pprint.pformat(self.to_dict())

    def __repr__(self):
        """For `print` and `pprint`"""
        return self.to_str()

    def __eq__(self, other):
        """Returns true if both objects are equal"""
        if not isinstance(other, DataWithListOfHostUuidsData):
            return False

        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        """Returns true if both objects are not equal"""
        return not self == other


class DataWithListOfHostUuids(object):
    """NOTE: This class is auto generated by the swagger code generator program

    Do not edit the class manually.
    """

    """
    Attributes:
      swagger_types (dict): The key is attribute name
                            and the value is attribute type.
      attribute_map (dict): The key is attribute name
                            and the value is json key in definition.
    """
    swagger_types = {
        'data': 'DataWithListOfHostUuidsData'
    }

    attribute_map = {
        'data': 'data'
    }

    def __init__(self, data=None):  # noqa: E501
        """DataWithListOfHostUuids - a model defined in Swagger"""  # noqa: E501

        self._data = None
        self.discriminator = None

        if data is not None:
            self.data = data

    @property
    def data(self):
        """Gets the data of this DataWithListOfHostUuids.  # noqa: E501


        :return: The data of this DataWithListOfHostUuids.  # noqa: E501
        :rtype: DataWithListOfHostUuidsData
        """
        return self._data

    @data.setter
    def data(self, data):
        """Sets the data of this DataWithListOfHostUuids.


        :param data: The data of this DataWithListOfHostUuids.  # noqa: E501
        :type: DataWithListOfHostUuidsData
        """

        self._data = data

    def to_dict(self):
        """Returns the model properties as a dict"""
        result = {}

        for attr, _ in self.swagger_types.items():
            value = getattr(self, attr)
            if isinstance(value, list):
                result[attr] = list(map(
                    lambda x: x.to_dict() if hasattr(x, "to_dict") else x,
                    value
                ))
            elif hasattr(value, "to_dict"):
                result[attr] = value.to_dict()
            elif isinstance(value, dict):
                result[attr] = dict(map(
                    lambda item: (item[0], item[1].to_dict())
                    if hasattr(item[1], "to_dict") else item,
                    value.items()
                ))
            else:
                result[attr] = value
        if issubclass(DataWithListOfHostUuids, dict):
            for key, value in self.items():
                result[key] = value

        return result

    def to_str(self):
        """Returns the string representation of the model"""
        return pprint.pformat(self.to_dict())

    def __repr__(self):
        """For `print` and `pprint`"""
        return self.to_str()

    def __eq__(self, other):
        """Returns true if both objects are equal"""
        if not isinstance(other, DataWithListOfHostUuids):
            return False

        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        """Returns true if both objects are not equal"""
        return not self == other


class DataWithListOfHosts(object):
    """NOTE: This class is auto generated by the swagger code generator program

    Do not edit the class manually.
    """

    """
    Attributes:
      swagger_types (dict): The key is attribute name
                            and the value is attribute type.
      attribute_map (dict): The key is attribute name
                            and the value is json key in definition.
    """
    swagger_types = {
        'data': 'list[HostInfo]'
    }

    attribute_map = {
        'data': 'data'
    }

    def __init__(self, data=None):  # noqa: E501
        """DataWithListOfHosts - a model defined in Swagger"""  # noqa: E501

        self._data = None
        self.discriminator = None

        self.data = data

    @property
    def data(self):
        """Gets the data of this DataWithListOfHosts.  # noqa: E501


        :return: The data of this DataWithListOfHosts.  # noqa: E501
        :rtype: list[HostInfo]
        """
        return self._data

    @data.setter
    def data(self, data):
        """Sets the data of this DataWithListOfHosts.


        :param data: The data of this DataWithListOfHosts.  # noqa: E501
        :type: list[HostInfo]
        """
        if data is None:
            raise ValueError("Invalid value for `data`, must not be `None`")  # noqa: E501

        self._data = data

    def to_dict(self):
        """Returns the model properties as a dict"""
        result = {}

        for attr, _ in self.swagger_types.items():
            value = getattr(self, attr)
            if isinstance(value, list):
                result[attr] = list(map(
                    lambda x: x.to_dict() if hasattr(x, "to_dict") else x,
                    value
                ))
            elif hasattr(value, "to_dict"):
                result[attr] = value.to_dict()
            elif isinstance(value, dict):
                result[attr] = dict(map(
                    lambda item: (item[0], item[1].to_dict())
                    if hasattr(item[1], "to_dict") else item,
                    value.items()
                ))
            else:
                result[attr] = value
        if issubclass(DataWithListOfHosts, dict):
            for key, value in self.items():
                result[key] = value

        return result

    def to_str(self):
        """Returns the string representation of the model"""
        return pprint.pformat(self.to_dict())

    def __repr__(self):
        """For `print` and `pprint`"""
        return self.to_str()

    def __eq__(self, other):
        """Returns true if both objects are equal"""
        if not isinstance(other, DataWithListOfHosts):
            return False

        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        """Returns true if both objects are not equal"""
        return not self == other


class DataWithMapOfDpuDrives(object):
    """NOTE: This class is auto generated by the swagger code generator program

    Do not edit the class manually.
    """

    """
    Attributes:
      swagger_types (dict): The key is attribute name
                            and the value is attribute type.
      attribute_map (dict): The key is attribute name
                            and the value is json key in definition.
    """
    swagger_types = {
        'data': 'dict(str, NodeDpu)'
    }

    attribute_map = {
        'data': 'data'
    }

    def __init__(self, data=None):  # noqa: E501
        """DataWithMapOfDpuDrives - a model defined in Swagger"""  # noqa: E501

        self._data = None
        self.discriminator = None

        self.data = data

    @property
    def data(self):
        """Gets the data of this DataWithMapOfDpuDrives.  # noqa: E501


        :return: The data of this DataWithMapOfDpuDrives.  # noqa: E501
        :rtype: dict(str, NodeDpu)
        """
        return self._data

    @data.setter
    def data(self, data):
        """Sets the data of this DataWithMapOfDpuDrives.


        :param data: The data of this DataWithMapOfDpuDrives.  # noqa: E501
        :type: dict(str, NodeDpu)
        """
        if data is None:
            raise ValueError("Invalid value for `data`, must not be `None`")  # noqa: E501

        self._data = data

    def to_dict(self):
        """Returns the model properties as a dict"""
        result = {}

        for attr, _ in self.swagger_types.items():
            value = getattr(self, attr)
            if isinstance(value, list):
                result[attr] = list(map(
                    lambda x: x.to_dict() if hasattr(x, "to_dict") else x,
                    value
                ))
            elif hasattr(value, "to_dict"):
                result[attr] = value.to_dict()
            elif isinstance(value, dict):
                result[attr] = dict(map(
                    lambda item: (item[0], item[1].to_dict())
                    if hasattr(item[1], "to_dict") else item,
                    value.items()
                ))
            else:
                result[attr] = value
        if issubclass(DataWithMapOfDpuDrives, dict):
            for key, value in self.items():
                result[key] = value

        return result

    def to_str(self):
        """Returns the string representation of the model"""
        return pprint.pformat(self.to_dict())

    def __repr__(self):
        """For `print` and `pprint`"""
        return self.to_str()

    def __eq__(self, other):
        """Returns true if both objects are equal"""
        if not isinstance(other, DataWithMapOfDpuDrives):
            return False

        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        """Returns true if both objects are not equal"""
        return not self == other


class DataWithSinglePort(object):
    """NOTE: This class is auto generated by the swagger code generator program

    Do not edit the class manually.
    """

    """
    Attributes:
      swagger_types (dict): The key is attribute name
                            and the value is attribute type.
      attribute_map (dict): The key is attribute name
                            and the value is json key in definition.
    """
    swagger_types = {
        'data': 'Port'
    }

    attribute_map = {
        'data': 'data'
    }

    def __init__(self, data=None):  # noqa: E501
        """DataWithSinglePort - a model defined in Swagger"""  # noqa: E501

        self._data = None
        self.discriminator = None

        self.data = data

    @property
    def data(self):
        """Gets the data of this DataWithSinglePort.  # noqa: E501


        :return: The data of this DataWithSinglePort.  # noqa: E501
        :rtype: Port
        """
        return self._data

    @data.setter
    def data(self, data):
        """Sets the data of this DataWithSinglePort.


        :param data: The data of this DataWithSinglePort.  # noqa: E501
        :type: Port
        """
        if data is None:
            raise ValueError("Invalid value for `data`, must not be `None`")  # noqa: E501

        self._data = data

    def to_dict(self):
        """Returns the model properties as a dict"""
        result = {}

        for attr, _ in self.swagger_types.items():
            value = getattr(self, attr)
            if isinstance(value, list):
                result[attr] = list(map(
                    lambda x: x.to_dict() if hasattr(x, "to_dict") else x,
                    value
                ))
            elif hasattr(value, "to_dict"):
                result[attr] = value.to_dict()
            elif isinstance(value, dict):
                result[attr] = dict(map(
                    lambda item: (item[0], item[1].to_dict())
                    if hasattr(item[1], "to_dict") else item,
                    value.items()
                ))
            else:
                result[attr] = value
        if issubclass(DataWithSinglePort, dict):
            for key, value in self.items():
                result[key] = value

        return result

    def to_str(self):
        """Returns the string representation of the model"""
        return pprint.pformat(self.to_dict())

    def __repr__(self):
        """For `print` and `pprint`"""
        return self.to_str()

    def __eq__(self, other):
        """Returns true if both objects are equal"""
        if not isinstance(other, DataWithSinglePort):
            return False

        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        """Returns true if both objects are not equal"""
        return not self == other


class DataWithSingleVolume(object):
    """NOTE: This class is auto generated by the swagger code generator program

    Do not edit the class manually.
    """

    """
    Attributes:
      swagger_types (dict): The key is attribute name
                            and the value is attribute type.
      attribute_map (dict): The key is attribute name
                            and the value is json key in definition.
    """
    swagger_types = {
        'data': 'Volume'
    }

    attribute_map = {
        'data': 'data'
    }

    def __init__(self, data=None):  # noqa: E501
        """DataWithSingleVolume - a model defined in Swagger"""  # noqa: E501

        self._data = None
        self.discriminator = None

        self.data = data

    @property
    def data(self):
        """Gets the data of this DataWithSingleVolume.  # noqa: E501


        :return: The data of this DataWithSingleVolume.  # noqa: E501
        :rtype: Volume
        """
        return self._data

    @data.setter
    def data(self, data):
        """Sets the data of this DataWithSingleVolume.


        :param data: The data of this DataWithSingleVolume.  # noqa: E501
        :type: Volume
        """
        if data is None:
            raise ValueError("Invalid value for `data`, must not be `None`")  # noqa: E501

        self._data = data

    def to_dict(self):
        """Returns the model properties as a dict"""
        result = {}

        for attr, _ in self.swagger_types.items():
            value = getattr(self, attr)
            if isinstance(value, list):
                result[attr] = list(map(
                    lambda x: x.to_dict() if hasattr(x, "to_dict") else x,
                    value
                ))
            elif hasattr(value, "to_dict"):
                result[attr] = value.to_dict()
            elif isinstance(value, dict):
                result[attr] = dict(map(
                    lambda item: (item[0], item[1].to_dict())
                    if hasattr(item[1], "to_dict") else item,
                    value.items()
                ))
            else:
                result[attr] = value
        if issubclass(DataWithSingleVolume, dict):
            for key, value in self.items():
                result[key] = value

        return result

    def to_str(self):
        """Returns the string representation of the model"""
        return pprint.pformat(self.to_dict())

    def __repr__(self):
        """For `print` and `pprint`"""
        return self.to_str()

    def __eq__(self, other):
        """Returns true if both objects are equal"""
        if not isinstance(other, DataWithSingleVolume):
            return False

        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        """Returns true if both objects are not equal"""
        return not self == other


class DataWithUuidString(object):
    """NOTE: This class is auto generated by the swagger code generator program

    Do not edit the class manually.
    """

    """
    Attributes:
      swagger_types (dict): The key is attribute name
                            and the value is attribute type.
      attribute_map (dict): The key is attribute name
                            and the value is json key in definition.
    """
    swagger_types = {
        'data': 'DataWithUuidStringData'
    }

    attribute_map = {
        'data': 'data'
    }

    def __init__(self, data=None):  # noqa: E501
        """DataWithUuidString - a model defined in Swagger"""  # noqa: E501

        self._data = None
        self.discriminator = None

        self.data = data

    @property
    def data(self):
        """Gets the data of this DataWithUuidString.  # noqa: E501


        :return: The data of this DataWithUuidString.  # noqa: E501
        :rtype: DataWithUuidStringData
        """
        return self._data

    @data.setter
    def data(self, data):
        """Sets the data of this DataWithUuidString.


        :param data: The data of this DataWithUuidString.  # noqa: E501
        :type: DataWithUuidStringData
        """
        if data is None:
            raise ValueError("Invalid value for `data`, must not be `None`")  # noqa: E501

        self._data = data

    def to_dict(self):
        """Returns the model properties as a dict"""
        result = {}

        for attr, _ in self.swagger_types.items():
            value = getattr(self, attr)
            if isinstance(value, list):
                result[attr] = list(map(
                    lambda x: x.to_dict() if hasattr(x, "to_dict") else x,
                    value
                ))
            elif hasattr(value, "to_dict"):
                result[attr] = value.to_dict()
            elif isinstance(value, dict):
                result[attr] = dict(map(
                    lambda item: (item[0], item[1].to_dict())
                    if hasattr(item[1], "to_dict") else item,
                    value.items()
                ))
            else:
                result[attr] = value
        if issubclass(DataWithUuidString, dict):
            for key, value in self.items():
                result[key] = value

        return result

    def to_str(self):
        """Returns the string representation of the model"""
        return pprint.pformat(self.to_dict())

    def __repr__(self):
        """For `print` and `pprint`"""
        return self.to_str()

    def __eq__(self, other):
        """Returns true if both objects are equal"""
        if not isinstance(other, DataWithUuidString):
            return False

        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        """Returns true if both objects are not equal"""
        return not self == other


class DataWithUuid(object):
    """NOTE: This class is auto generated by the swagger code generator program

    Do not edit the class manually.
    """

    """
    Attributes:
      swagger_types (dict): The key is attribute name
                            and the value is attribute type.
      attribute_map (dict): The key is attribute name
                            and the value is json key in definition.
    """
    swagger_types = {
        'data': 'DataWithUuidData'
    }

    attribute_map = {
        'data': 'data'
    }

    def __init__(self, data=None):  # noqa: E501
        """DataWithUuid - a model defined in Swagger"""  # noqa: E501

        self._data = None
        self.discriminator = None

        self.data = data

    @property
    def data(self):
        """Gets the data of this DataWithUuid.  # noqa: E501


        :return: The data of this DataWithUuid.  # noqa: E501
        :rtype: DataWithUuidData
        """
        return self._data

    @data.setter
    def data(self, data):
        """Sets the data of this DataWithUuid.


        :param data: The data of this DataWithUuid.  # noqa: E501
        :type: DataWithUuidData
        """
        if data is None:
            raise ValueError("Invalid value for `data`, must not be `None`")  # noqa: E501

        self._data = data

    def to_dict(self):
        """Returns the model properties as a dict"""
        result = {}

        for attr, _ in self.swagger_types.items():
            value = getattr(self, attr)
            if isinstance(value, list):
                result[attr] = list(map(
                    lambda x: x.to_dict() if hasattr(x, "to_dict") else x,
                    value
                ))
            elif hasattr(value, "to_dict"):
                result[attr] = value.to_dict()
            elif isinstance(value, dict):
                result[attr] = dict(map(
                    lambda item: (item[0], item[1].to_dict())
                    if hasattr(item[1], "to_dict") else item,
                    value.items()
                ))
            else:
                result[attr] = value
        if issubclass(DataWithUuid, dict):
            for key, value in self.items():
                result[key] = value

        return result

    def to_str(self):
        """Returns the string representation of the model"""
        return pprint.pformat(self.to_dict())

    def __repr__(self):
        """For `print` and `pprint`"""
        return self.to_str()

    def __eq__(self, other):
        """Returns true if both objects are equal"""
        if not isinstance(other, DataWithUuid):
            return False

        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        """Returns true if both objects are not equal"""
        return not self == other


class DpIpSetup(object):
    """NOTE: This class is auto generated by the swagger code generator program

    Do not edit the class manually.
    """

    """
    Attributes:
      swagger_types (dict): The key is attribute name
                            and the value is attribute type.
      attribute_map (dict): The key is attribute name
                            and the value is json key in definition.
    """
    swagger_types = {
        'ip_assignment_dhcp': 'bool',
        'subnet_mask': 'str',
        'next_hop': 'str'
    }

    attribute_map = {
        'ip_assignment_dhcp': 'ip_assignment_dhcp',
        'subnet_mask': 'subnet_mask',
        'next_hop': 'next_hop'
    }

    def __init__(self, ip_assignment_dhcp=None, subnet_mask=None, next_hop=None):  # noqa: E501
        """DpIpSetup - a model defined in Swagger"""  # noqa: E501

        self._ip_assignment_dhcp = None
        self._subnet_mask = None
        self._next_hop = None
        self.discriminator = None

        if ip_assignment_dhcp is not None:
            self.ip_assignment_dhcp = ip_assignment_dhcp
        if subnet_mask is not None:
            self.subnet_mask = subnet_mask
        if next_hop is not None:
            self.next_hop = next_hop

    @property
    def ip_assignment_dhcp(self):
        """Gets the ip_assignment_dhcp of this DpIpSetup.  # noqa: E501


        :return: The ip_assignment_dhcp of this DpIpSetup.  # noqa: E501
        :rtype: bool
        """
        return self._ip_assignment_dhcp

    @ip_assignment_dhcp.setter
    def ip_assignment_dhcp(self, ip_assignment_dhcp):
        """Sets the ip_assignment_dhcp of this DpIpSetup.


        :param ip_assignment_dhcp: The ip_assignment_dhcp of this DpIpSetup.  # noqa: E501
        :type: bool
        """

        self._ip_assignment_dhcp = ip_assignment_dhcp

    @property
    def subnet_mask(self):
        """Gets the subnet_mask of this DpIpSetup.  # noqa: E501


        :return: The subnet_mask of this DpIpSetup.  # noqa: E501
        :rtype: str
        """
        return self._subnet_mask

    @subnet_mask.setter
    def subnet_mask(self, subnet_mask):
        """Sets the subnet_mask of this DpIpSetup.


        :param subnet_mask: The subnet_mask of this DpIpSetup.  # noqa: E501
        :type: str
        """

        self._subnet_mask = subnet_mask

    @property
    def next_hop(self):
        """Gets the next_hop of this DpIpSetup.  # noqa: E501


        :return: The next_hop of this DpIpSetup.  # noqa: E501
        :rtype: str
        """
        return self._next_hop

    @next_hop.setter
    def next_hop(self, next_hop):
        """Sets the next_hop of this DpIpSetup.


        :param next_hop: The next_hop of this DpIpSetup.  # noqa: E501
        :type: str
        """

        self._next_hop = next_hop

    def to_dict(self):
        """Returns the model properties as a dict"""
        result = {}

        for attr, _ in self.swagger_types.items():
            value = getattr(self, attr)
            if isinstance(value, list):
                result[attr] = list(map(
                    lambda x: x.to_dict() if hasattr(x, "to_dict") else x,
                    value
                ))
            elif hasattr(value, "to_dict"):
                result[attr] = value.to_dict()
            elif isinstance(value, dict):
                result[attr] = dict(map(
                    lambda item: (item[0], item[1].to_dict())
                    if hasattr(item[1], "to_dict") else item,
                    value.items()
                ))
            else:
                result[attr] = value
        if issubclass(DpIpSetup, dict):
            for key, value in self.items():
                result[key] = value

        return result

    def to_str(self):
        """Returns the string representation of the model"""
        return pprint.pformat(self.to_dict())

    def __repr__(self):
        """For `print` and `pprint`"""
        return self.to_str()

    def __eq__(self, other):
        """Returns true if both objects are equal"""
        if not isinstance(other, DpIpSetup):
            return False

        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        """Returns true if both objects are not equal"""
        return not self == other


class Dpu(object):
    """NOTE: This class is auto generated by the swagger code generator program

    Do not edit the class manually.
    """

    """
    Attributes:
      swagger_types (dict): The key is attribute name
                            and the value is attribute type.
      attribute_map (dict): The key is attribute name
                            and the value is json key in definition.
    """
    swagger_types = {
        'uuid': 'str',
        'name': 'str',
        'node_class': 'str',
        'mgmt_ip': 'str',
        'dpu_version': 'str',
        'dataplane_ip': 'str',
        'fpg_num': 'int',
        'storage_agent': 'str',
        'drives': 'list[Drive]',
        'fault_zones': 'list[str]',
        'capacity': 'int',
        'state': 'ResourceState',
        'available': 'bool',
        'dp_ip_setup': 'DpIpSetup',
        'additional_fields': 'AdditionalFields',
        'created_at': 'datetime',
        'modified_at': 'datetime',
        'sku': 'str',
        'product': 'str',
        'fault_domain_id': 'str'
    }

    attribute_map = {
        'uuid': 'uuid',
        'name': 'name',
        'node_class': 'node_class',
        'mgmt_ip': 'mgmt_ip',
        'dpu_version': 'dpu_version',
        'dataplane_ip': 'dataplane_ip',
        'fpg_num': 'fpg_num',
        'storage_agent': 'storage_agent',
        'drives': 'drives',
        'fault_zones': 'fault_zones',
        'capacity': 'capacity',
        'state': 'state',
        'available': 'available',
        'dp_ip_setup': 'dp_ip_setup',
        'additional_fields': 'additional_fields',
        'created_at': 'created_at',
        'modified_at': 'modified_at',
        'sku': 'sku',
        'product': 'product',
        'fault_domain_id': 'fault_domain_id'
    }

    def __init__(self, uuid=None, name=None, node_class=None, mgmt_ip=None, dpu_version=None, dataplane_ip=None, fpg_num=None, storage_agent=None, drives=None, fault_zones=None, capacity=None, state=None, available=None, dp_ip_setup=None, additional_fields=None, created_at=None, modified_at=None, sku=None, product='UNKNOWN', fault_domain_id=None):  # noqa: E501
        """Dpu - a model defined in Swagger"""  # noqa: E501

        self._uuid = None
        self._name = None
        self._node_class = None
        self._mgmt_ip = None
        self._dpu_version = None
        self._dataplane_ip = None
        self._fpg_num = None
        self._storage_agent = None
        self._drives = None
        self._fault_zones = None
        self._capacity = None
        self._state = None
        self._available = None
        self._dp_ip_setup = None
        self._additional_fields = None
        self._created_at = None
        self._modified_at = None
        self._sku = None
        self._product = None
        self._fault_domain_id = None
        self.discriminator = None

        self.uuid = uuid
        self.name = name
        if node_class is not None:
            self.node_class = node_class
        if mgmt_ip is not None:
            self.mgmt_ip = mgmt_ip
        if dpu_version is not None:
            self.dpu_version = dpu_version
        if dataplane_ip is not None:
            self.dataplane_ip = dataplane_ip
        if fpg_num is not None:
            self.fpg_num = fpg_num
        if storage_agent is not None:
            self.storage_agent = storage_agent
        if drives is not None:
            self.drives = drives
        if fault_zones is not None:
            self.fault_zones = fault_zones
        if capacity is not None:
            self.capacity = capacity
        if state is not None:
            self.state = state
        if available is not None:
            self.available = available
        if dp_ip_setup is not None:
            self.dp_ip_setup = dp_ip_setup
        if additional_fields is not None:
            self.additional_fields = additional_fields
        if created_at is not None:
            self.created_at = created_at
        if modified_at is not None:
            self.modified_at = modified_at
        if sku is not None:
            self.sku = sku
        if product is not None:
            self.product = product
        if fault_domain_id is not None:
            self.fault_domain_id = fault_domain_id

    @property
    def uuid(self):
        """Gets the uuid of this Dpu.  # noqa: E501

        unique id of dpu  # noqa: E501

        :return: The uuid of this Dpu.  # noqa: E501
        :rtype: str
        """
        return self._uuid

    @uuid.setter
    def uuid(self, uuid):
        """Sets the uuid of this Dpu.

        unique id of dpu  # noqa: E501

        :param uuid: The uuid of this Dpu.  # noqa: E501
        :type: str
        """
        if uuid is None:
            raise ValueError("Invalid value for `uuid`, must not be `None`")  # noqa: E501

        self._uuid = uuid

    @property
    def name(self):
        """Gets the name of this Dpu.  # noqa: E501

        Descriptive name of dpu  # noqa: E501

        :return: The name of this Dpu.  # noqa: E501
        :rtype: str
        """
        return self._name

    @name.setter
    def name(self, name):
        """Sets the name of this Dpu.

        Descriptive name of dpu  # noqa: E501

        :param name: The name of this Dpu.  # noqa: E501
        :type: str
        """
        if name is None:
            raise ValueError("Invalid value for `name`, must not be `None`")  # noqa: E501

        self._name = name

    @property
    def node_class(self):
        """Gets the node_class of this Dpu.  # noqa: E501


        :return: The node_class of this Dpu.  # noqa: E501
        :rtype: str
        """
        return self._node_class

    @node_class.setter
    def node_class(self, node_class):
        """Sets the node_class of this Dpu.


        :param node_class: The node_class of this Dpu.  # noqa: E501
        :type: str
        """

        self._node_class = node_class

    @property
    def mgmt_ip(self):
        """Gets the mgmt_ip of this Dpu.  # noqa: E501


        :return: The mgmt_ip of this Dpu.  # noqa: E501
        :rtype: str
        """
        return self._mgmt_ip

    @mgmt_ip.setter
    def mgmt_ip(self, mgmt_ip):
        """Sets the mgmt_ip of this Dpu.


        :param mgmt_ip: The mgmt_ip of this Dpu.  # noqa: E501
        :type: str
        """

        self._mgmt_ip = mgmt_ip

    @property
    def dpu_version(self):
        """Gets the dpu_version of this Dpu.  # noqa: E501


        :return: The dpu_version of this Dpu.  # noqa: E501
        :rtype: str
        """
        return self._dpu_version

    @dpu_version.setter
    def dpu_version(self, dpu_version):
        """Sets the dpu_version of this Dpu.


        :param dpu_version: The dpu_version of this Dpu.  # noqa: E501
        :type: str
        """

        self._dpu_version = dpu_version

    @property
    def dataplane_ip(self):
        """Gets the dataplane_ip of this Dpu.  # noqa: E501


        :return: The dataplane_ip of this Dpu.  # noqa: E501
        :rtype: str
        """
        return self._dataplane_ip

    @dataplane_ip.setter
    def dataplane_ip(self, dataplane_ip):
        """Sets the dataplane_ip of this Dpu.


        :param dataplane_ip: The dataplane_ip of this Dpu.  # noqa: E501
        :type: str
        """

        self._dataplane_ip = dataplane_ip

    @property
    def fpg_num(self):
        """Gets the fpg_num of this Dpu.  # noqa: E501


        :return: The fpg_num of this Dpu.  # noqa: E501
        :rtype: int
        """
        return self._fpg_num

    @fpg_num.setter
    def fpg_num(self, fpg_num):
        """Sets the fpg_num of this Dpu.


        :param fpg_num: The fpg_num of this Dpu.  # noqa: E501
        :type: int
        """

        self._fpg_num = fpg_num

    @property
    def storage_agent(self):
        """Gets the storage_agent of this Dpu.  # noqa: E501


        :return: The storage_agent of this Dpu.  # noqa: E501
        :rtype: str
        """
        return self._storage_agent

    @storage_agent.setter
    def storage_agent(self, storage_agent):
        """Sets the storage_agent of this Dpu.


        :param storage_agent: The storage_agent of this Dpu.  # noqa: E501
        :type: str
        """

        self._storage_agent = storage_agent

    @property
    def drives(self):
        """Gets the drives of this Dpu.  # noqa: E501


        :return: The drives of this Dpu.  # noqa: E501
        :rtype: list[Drive]
        """
        return self._drives

    @drives.setter
    def drives(self, drives):
        """Sets the drives of this Dpu.


        :param drives: The drives of this Dpu.  # noqa: E501
        :type: list[Drive]
        """

        self._drives = drives

    @property
    def fault_zones(self):
        """Gets the fault_zones of this Dpu.  # noqa: E501


        :return: The fault_zones of this Dpu.  # noqa: E501
        :rtype: list[str]
        """
        return self._fault_zones

    @fault_zones.setter
    def fault_zones(self, fault_zones):
        """Sets the fault_zones of this Dpu.


        :param fault_zones: The fault_zones of this Dpu.  # noqa: E501
        :type: list[str]
        """

        self._fault_zones = fault_zones

    @property
    def capacity(self):
        """Gets the capacity of this Dpu.  # noqa: E501


        :return: The capacity of this Dpu.  # noqa: E501
        :rtype: int
        """
        return self._capacity

    @capacity.setter
    def capacity(self, capacity):
        """Sets the capacity of this Dpu.


        :param capacity: The capacity of this Dpu.  # noqa: E501
        :type: int
        """

        self._capacity = capacity

    @property
    def state(self):
        """Gets the state of this Dpu.  # noqa: E501


        :return: The state of this Dpu.  # noqa: E501
        :rtype: ResourceState
        """
        return self._state

    @state.setter
    def state(self, state):
        """Sets the state of this Dpu.


        :param state: The state of this Dpu.  # noqa: E501
        :type: ResourceState
        """

        self._state = state

    @property
    def available(self):
        """Gets the available of this Dpu.  # noqa: E501


        :return: The available of this Dpu.  # noqa: E501
        :rtype: bool
        """
        return self._available

    @available.setter
    def available(self, available):
        """Sets the available of this Dpu.


        :param available: The available of this Dpu.  # noqa: E501
        :type: bool
        """

        self._available = available

    @property
    def dp_ip_setup(self):
        """Gets the dp_ip_setup of this Dpu.  # noqa: E501


        :return: The dp_ip_setup of this Dpu.  # noqa: E501
        :rtype: DpIpSetup
        """
        return self._dp_ip_setup

    @dp_ip_setup.setter
    def dp_ip_setup(self, dp_ip_setup):
        """Sets the dp_ip_setup of this Dpu.


        :param dp_ip_setup: The dp_ip_setup of this Dpu.  # noqa: E501
        :type: DpIpSetup
        """

        self._dp_ip_setup = dp_ip_setup

    @property
    def additional_fields(self):
        """Gets the additional_fields of this Dpu.  # noqa: E501


        :return: The additional_fields of this Dpu.  # noqa: E501
        :rtype: AdditionalFields
        """
        return self._additional_fields

    @additional_fields.setter
    def additional_fields(self, additional_fields):
        """Sets the additional_fields of this Dpu.


        :param additional_fields: The additional_fields of this Dpu.  # noqa: E501
        :type: AdditionalFields
        """

        self._additional_fields = additional_fields

    @property
    def created_at(self):
        """Gets the created_at of this Dpu.  # noqa: E501

        set on create  # noqa: E501

        :return: The created_at of this Dpu.  # noqa: E501
        :rtype: datetime
        """
        return self._created_at

    @created_at.setter
    def created_at(self, created_at):
        """Sets the created_at of this Dpu.

        set on create  # noqa: E501

        :param created_at: The created_at of this Dpu.  # noqa: E501
        :type: datetime
        """

        self._created_at = created_at

    @property
    def modified_at(self):
        """Gets the modified_at of this Dpu.  # noqa: E501

        set when modified  # noqa: E501

        :return: The modified_at of this Dpu.  # noqa: E501
        :rtype: datetime
        """
        return self._modified_at

    @modified_at.setter
    def modified_at(self, modified_at):
        """Sets the modified_at of this Dpu.

        set when modified  # noqa: E501

        :param modified_at: The modified_at of this Dpu.  # noqa: E501
        :type: datetime
        """

        self._modified_at = modified_at

    @property
    def sku(self):
        """Gets the sku of this Dpu.  # noqa: E501


        :return: The sku of this Dpu.  # noqa: E501
        :rtype: str
        """
        return self._sku

    @sku.setter
    def sku(self, sku):
        """Sets the sku of this Dpu.


        :param sku: The sku of this Dpu.  # noqa: E501
        :type: str
        """

        self._sku = sku

    @property
    def product(self):
        """Gets the product of this Dpu.  # noqa: E501


        :return: The product of this Dpu.  # noqa: E501
        :rtype: str
        """
        return self._product

    @product.setter
    def product(self, product):
        """Sets the product of this Dpu.


        :param product: The product of this Dpu.  # noqa: E501
        :type: str
        """
        allowed_values = ["UNKNOWN", "DS200", "FC200", "FC50", "FS800", "FC100", "FS1600"]  # noqa: E501
        if product not in allowed_values:
            raise ValueError(
                "Invalid value for `product` ({0}), must be one of {1}"  # noqa: E501
                .format(product, allowed_values)
            )

        self._product = product

    @property
    def fault_domain_id(self):
        """Gets the fault_domain_id of this Dpu.  # noqa: E501


        :return: The fault_domain_id of this Dpu.  # noqa: E501
        :rtype: str
        """
        return self._fault_domain_id

    @fault_domain_id.setter
    def fault_domain_id(self, fault_domain_id):
        """Sets the fault_domain_id of this Dpu.


        :param fault_domain_id: The fault_domain_id of this Dpu.  # noqa: E501
        :type: str
        """

        self._fault_domain_id = fault_domain_id

    def to_dict(self):
        """Returns the model properties as a dict"""
        result = {}

        for attr, _ in self.swagger_types.items():
            value = getattr(self, attr)
            if isinstance(value, list):
                result[attr] = list(map(
                    lambda x: x.to_dict() if hasattr(x, "to_dict") else x,
                    value
                ))
            elif hasattr(value, "to_dict"):
                result[attr] = value.to_dict()
            elif isinstance(value, dict):
                result[attr] = dict(map(
                    lambda item: (item[0], item[1].to_dict())
                    if hasattr(item[1], "to_dict") else item,
                    value.items()
                ))
            else:
                result[attr] = value
        if issubclass(Dpu, dict):
            for key, value in self.items():
                result[key] = value

        return result

    def to_str(self):
        """Returns the string representation of the model"""
        return pprint.pformat(self.to_dict())

    def __repr__(self):
        """For `print` and `pprint`"""
        return self.to_str()

    def __eq__(self, other):
        """Returns true if both objects are equal"""
        if not isinstance(other, Dpu):
            return False

        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        """Returns true if both objects are not equal"""
        return not self == other


class Drive(object):
    """NOTE: This class is auto generated by the swagger code generator program

    Do not edit the class manually.
    """

    """
    Attributes:
      swagger_types (dict): The key is attribute name
                            and the value is attribute type.
      attribute_map (dict): The key is attribute name
                            and the value is json key in definition.
    """
    swagger_types = {
        'uuid': 'str',
        'dpu': 'str',
        'fault_zone': 'str',
        'nguid_low': 'int',
        'nguid_high': 'int',
        'usage': 'int',
        'slot_id': 'int',
        'state': 'ResourceState',
        'plugged': 'bool',
        'capacity': 'int',
        'volumes': 'list[str]',
        'created_at': 'datetime',
        'modified_at': 'datetime',
        'smart': 'Smart',
        'identity': 'Identity'
    }

    attribute_map = {
        'uuid': 'uuid',
        'dpu': 'dpu',
        'fault_zone': 'fault_zone',
        'nguid_low': 'nguid_low',
        'nguid_high': 'nguid_high',
        'usage': 'usage',
        'slot_id': 'slot_id',
        'state': 'state',
        'plugged': 'plugged',
        'capacity': 'capacity',
        'volumes': 'volumes',
        'created_at': 'created_at',
        'modified_at': 'modified_at',
        'smart': 'smart',
        'identity': 'identity'
    }

    def __init__(self, uuid=None, dpu=None, fault_zone=None, nguid_low=None, nguid_high=None, usage=None, slot_id=None, state=None, plugged=None, capacity=None, volumes=None, created_at=None, modified_at=None, smart=None, identity=None):  # noqa: E501
        """Drive - a model defined in Swagger"""  # noqa: E501

        self._uuid = None
        self._dpu = None
        self._fault_zone = None
        self._nguid_low = None
        self._nguid_high = None
        self._usage = None
        self._slot_id = None
        self._state = None
        self._plugged = None
        self._capacity = None
        self._volumes = None
        self._created_at = None
        self._modified_at = None
        self._smart = None
        self._identity = None
        self.discriminator = None

        if uuid is not None:
            self.uuid = uuid
        self.dpu = dpu
        if fault_zone is not None:
            self.fault_zone = fault_zone
        if nguid_low is not None:
            self.nguid_low = nguid_low
        if nguid_high is not None:
            self.nguid_high = nguid_high
        if usage is not None:
            self.usage = usage
        self.slot_id = slot_id
        if state is not None:
            self.state = state
        if plugged is not None:
            self.plugged = plugged
        if capacity is not None:
            self.capacity = capacity
        if volumes is not None:
            self.volumes = volumes
        if created_at is not None:
            self.created_at = created_at
        if modified_at is not None:
            self.modified_at = modified_at
        if smart is not None:
            self.smart = smart
        if identity is not None:
            self.identity = identity

    @property
    def uuid(self):
        """Gets the uuid of this Drive.  # noqa: E501

        unique id of drive assigned by FS  # noqa: E501

        :return: The uuid of this Drive.  # noqa: E501
        :rtype: str
        """
        return self._uuid

    @uuid.setter
    def uuid(self, uuid):
        """Sets the uuid of this Drive.

        unique id of drive assigned by FS  # noqa: E501

        :param uuid: The uuid of this Drive.  # noqa: E501
        :type: str
        """

        self._uuid = uuid

    @property
    def dpu(self):
        """Gets the dpu of this Drive.  # noqa: E501

        id of dpu to which this drive is attached  # noqa: E501

        :return: The dpu of this Drive.  # noqa: E501
        :rtype: str
        """
        return self._dpu

    @dpu.setter
    def dpu(self, dpu):
        """Sets the dpu of this Drive.

        id of dpu to which this drive is attached  # noqa: E501

        :param dpu: The dpu of this Drive.  # noqa: E501
        :type: str
        """
        if dpu is None:
            raise ValueError("Invalid value for `dpu`, must not be `None`")  # noqa: E501

        self._dpu = dpu

    @property
    def fault_zone(self):
        """Gets the fault_zone of this Drive.  # noqa: E501


        :return: The fault_zone of this Drive.  # noqa: E501
        :rtype: str
        """
        return self._fault_zone

    @fault_zone.setter
    def fault_zone(self, fault_zone):
        """Sets the fault_zone of this Drive.


        :param fault_zone: The fault_zone of this Drive.  # noqa: E501
        :type: str
        """

        self._fault_zone = fault_zone

    @property
    def nguid_low(self):
        """Gets the nguid_low of this Drive.  # noqa: E501


        :return: The nguid_low of this Drive.  # noqa: E501
        :rtype: int
        """
        return self._nguid_low

    @nguid_low.setter
    def nguid_low(self, nguid_low):
        """Sets the nguid_low of this Drive.


        :param nguid_low: The nguid_low of this Drive.  # noqa: E501
        :type: int
        """
        if nguid_low is not None and nguid_low < 0:  # noqa: E501
            raise ValueError("Invalid value for `nguid_low`, must be a value greater than or equal to `0`")  # noqa: E501

        self._nguid_low = nguid_low

    @property
    def nguid_high(self):
        """Gets the nguid_high of this Drive.  # noqa: E501


        :return: The nguid_high of this Drive.  # noqa: E501
        :rtype: int
        """
        return self._nguid_high

    @nguid_high.setter
    def nguid_high(self, nguid_high):
        """Sets the nguid_high of this Drive.


        :param nguid_high: The nguid_high of this Drive.  # noqa: E501
        :type: int
        """
        if nguid_high is not None and nguid_high < 0:  # noqa: E501
            raise ValueError("Invalid value for `nguid_high`, must be a value greater than or equal to `0`")  # noqa: E501

        self._nguid_high = nguid_high

    @property
    def usage(self):
        """Gets the usage of this Drive.  # noqa: E501


        :return: The usage of this Drive.  # noqa: E501
        :rtype: int
        """
        return self._usage

    @usage.setter
    def usage(self, usage):
        """Sets the usage of this Drive.


        :param usage: The usage of this Drive.  # noqa: E501
        :type: int
        """
        if usage is not None and usage < 0:  # noqa: E501
            raise ValueError("Invalid value for `usage`, must be a value greater than or equal to `0`")  # noqa: E501

        self._usage = usage

    @property
    def slot_id(self):
        """Gets the slot_id of this Drive.  # noqa: E501

        dpu slot to which drive is connected  # noqa: E501

        :return: The slot_id of this Drive.  # noqa: E501
        :rtype: int
        """
        return self._slot_id

    @slot_id.setter
    def slot_id(self, slot_id):
        """Sets the slot_id of this Drive.

        dpu slot to which drive is connected  # noqa: E501

        :param slot_id: The slot_id of this Drive.  # noqa: E501
        :type: int
        """
        if slot_id is None:
            raise ValueError("Invalid value for `slot_id`, must not be `None`")  # noqa: E501

        self._slot_id = slot_id

    @property
    def state(self):
        """Gets the state of this Drive.  # noqa: E501


        :return: The state of this Drive.  # noqa: E501
        :rtype: ResourceState
        """
        return self._state

    @state.setter
    def state(self, state):
        """Sets the state of this Drive.


        :param state: The state of this Drive.  # noqa: E501
        :type: ResourceState
        """

        self._state = state

    @property
    def plugged(self):
        """Gets the plugged of this Drive.  # noqa: E501


        :return: The plugged of this Drive.  # noqa: E501
        :rtype: bool
        """
        return self._plugged

    @plugged.setter
    def plugged(self, plugged):
        """Sets the plugged of this Drive.


        :param plugged: The plugged of this Drive.  # noqa: E501
        :type: bool
        """

        self._plugged = plugged

    @property
    def capacity(self):
        """Gets the capacity of this Drive.  # noqa: E501


        :return: The capacity of this Drive.  # noqa: E501
        :rtype: int
        """
        return self._capacity

    @capacity.setter
    def capacity(self, capacity):
        """Sets the capacity of this Drive.


        :param capacity: The capacity of this Drive.  # noqa: E501
        :type: int
        """

        self._capacity = capacity

    @property
    def volumes(self):
        """Gets the volumes of this Drive.  # noqa: E501


        :return: The volumes of this Drive.  # noqa: E501
        :rtype: list[str]
        """
        return self._volumes

    @volumes.setter
    def volumes(self, volumes):
        """Sets the volumes of this Drive.


        :param volumes: The volumes of this Drive.  # noqa: E501
        :type: list[str]
        """

        self._volumes = volumes

    @property
    def created_at(self):
        """Gets the created_at of this Drive.  # noqa: E501

        set on create  # noqa: E501

        :return: The created_at of this Drive.  # noqa: E501
        :rtype: datetime
        """
        return self._created_at

    @created_at.setter
    def created_at(self, created_at):
        """Sets the created_at of this Drive.

        set on create  # noqa: E501

        :param created_at: The created_at of this Drive.  # noqa: E501
        :type: datetime
        """

        self._created_at = created_at

    @property
    def modified_at(self):
        """Gets the modified_at of this Drive.  # noqa: E501

        set when modified  # noqa: E501

        :return: The modified_at of this Drive.  # noqa: E501
        :rtype: datetime
        """
        return self._modified_at

    @modified_at.setter
    def modified_at(self, modified_at):
        """Sets the modified_at of this Drive.

        set when modified  # noqa: E501

        :param modified_at: The modified_at of this Drive.  # noqa: E501
        :type: datetime
        """

        self._modified_at = modified_at

    @property
    def smart(self):
        """Gets the smart of this Drive.  # noqa: E501


        :return: The smart of this Drive.  # noqa: E501
        :rtype: Smart
        """
        return self._smart

    @smart.setter
    def smart(self, smart):
        """Sets the smart of this Drive.


        :param smart: The smart of this Drive.  # noqa: E501
        :type: Smart
        """

        self._smart = smart

    @property
    def identity(self):
        """Gets the identity of this Drive.  # noqa: E501


        :return: The identity of this Drive.  # noqa: E501
        :rtype: Identity
        """
        return self._identity

    @identity.setter
    def identity(self, identity):
        """Sets the identity of this Drive.


        :param identity: The identity of this Drive.  # noqa: E501
        :type: Identity
        """

        self._identity = identity

    def to_dict(self):
        """Returns the model properties as a dict"""
        result = {}

        for attr, _ in self.swagger_types.items():
            value = getattr(self, attr)
            if isinstance(value, list):
                result[attr] = list(map(
                    lambda x: x.to_dict() if hasattr(x, "to_dict") else x,
                    value
                ))
            elif hasattr(value, "to_dict"):
                result[attr] = value.to_dict()
            elif isinstance(value, dict):
                result[attr] = dict(map(
                    lambda item: (item[0], item[1].to_dict())
                    if hasattr(item[1], "to_dict") else item,
                    value.items()
                ))
            else:
                result[attr] = value
        if issubclass(Drive, dict):
            for key, value in self.items():
                result[key] = value

        return result

    def to_str(self):
        """Returns the string representation of the model"""
        return pprint.pformat(self.to_dict())

    def __repr__(self):
        """For `print` and `pprint`"""
        return self.to_str()

    def __eq__(self, other):
        """Returns true if both objects are equal"""
        if not isinstance(other, Drive):
            return False

        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        """Returns true if both objects are not equal"""
        return not self == other


class ErrorResponseFields(object):
    """NOTE: This class is auto generated by the swagger code generator program

    Do not edit the class manually.
    """

    """
    Attributes:
      swagger_types (dict): The key is attribute name
                            and the value is attribute type.
      attribute_map (dict): The key is attribute name
                            and the value is json key in definition.
    """
    swagger_types = {
        'status': 'bool',
        'message': 'str',
        'error_message': 'str'
    }

    attribute_map = {
        'status': 'status',
        'message': 'message',
        'error_message': 'error_message'
    }

    def __init__(self, status=False, message=None, error_message=None):  # noqa: E501
        """ErrorResponseFields - a model defined in Swagger"""  # noqa: E501

        self._status = None
        self._message = None
        self._error_message = None
        self.discriminator = None

        self.status = status
        self.message = message
        if error_message is not None:
            self.error_message = error_message

    @property
    def status(self):
        """Gets the status of this ErrorResponseFields.  # noqa: E501


        :return: The status of this ErrorResponseFields.  # noqa: E501
        :rtype: bool
        """
        return self._status

    @status.setter
    def status(self, status):
        """Sets the status of this ErrorResponseFields.


        :param status: The status of this ErrorResponseFields.  # noqa: E501
        :type: bool
        """
        if status is None:
            raise ValueError("Invalid value for `status`, must not be `None`")  # noqa: E501

        self._status = status

    @property
    def message(self):
        """Gets the message of this ErrorResponseFields.  # noqa: E501


        :return: The message of this ErrorResponseFields.  # noqa: E501
        :rtype: str
        """
        return self._message

    @message.setter
    def message(self, message):
        """Sets the message of this ErrorResponseFields.


        :param message: The message of this ErrorResponseFields.  # noqa: E501
        :type: str
        """
        if message is None:
            raise ValueError("Invalid value for `message`, must not be `None`")  # noqa: E501

        self._message = message

    @property
    def error_message(self):
        """Gets the error_message of this ErrorResponseFields.  # noqa: E501


        :return: The error_message of this ErrorResponseFields.  # noqa: E501
        :rtype: str
        """
        return self._error_message

    @error_message.setter
    def error_message(self, error_message):
        """Sets the error_message of this ErrorResponseFields.


        :param error_message: The error_message of this ErrorResponseFields.  # noqa: E501
        :type: str
        """

        self._error_message = error_message

    def to_dict(self):
        """Returns the model properties as a dict"""
        result = {}

        for attr, _ in self.swagger_types.items():
            value = getattr(self, attr)
            if isinstance(value, list):
                result[attr] = list(map(
                    lambda x: x.to_dict() if hasattr(x, "to_dict") else x,
                    value
                ))
            elif hasattr(value, "to_dict"):
                result[attr] = value.to_dict()
            elif isinstance(value, dict):
                result[attr] = dict(map(
                    lambda item: (item[0], item[1].to_dict())
                    if hasattr(item[1], "to_dict") else item,
                    value.items()
                ))
            else:
                result[attr] = value
        if issubclass(ErrorResponseFields, dict):
            for key, value in self.items():
                result[key] = value

        return result

    def to_str(self):
        """Returns the string representation of the model"""
        return pprint.pformat(self.to_dict())

    def __repr__(self):
        """For `print` and `pprint`"""
        return self.to_str()

    def __eq__(self, other):
        """Returns true if both objects are equal"""
        if not isinstance(other, ErrorResponseFields):
            return False

        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        """Returns true if both objects are not equal"""
        return not self == other


class FacInfo(object):
    """NOTE: This class is auto generated by the swagger code generator program

    Do not edit the class manually.
    """

    """
    Attributes:
      swagger_types (dict): The key is attribute name
                            and the value is attribute type.
      attribute_map (dict): The key is attribute name
                            and the value is json key in definition.
    """
    swagger_types = {
        'fac_uuid': 'str'
    }

    attribute_map = {
        'fac_uuid': 'fac_uuid'
    }

    def __init__(self, fac_uuid=None):  # noqa: E501
        """FacInfo - a model defined in Swagger"""  # noqa: E501

        self._fac_uuid = None
        self.discriminator = None

        if fac_uuid is not None:
            self.fac_uuid = fac_uuid

    @property
    def fac_uuid(self):
        """Gets the fac_uuid of this FacInfo.  # noqa: E501


        :return: The fac_uuid of this FacInfo.  # noqa: E501
        :rtype: str
        """
        return self._fac_uuid

    @fac_uuid.setter
    def fac_uuid(self, fac_uuid):
        """Sets the fac_uuid of this FacInfo.


        :param fac_uuid: The fac_uuid of this FacInfo.  # noqa: E501
        :type: str
        """

        self._fac_uuid = fac_uuid

    def to_dict(self):
        """Returns the model properties as a dict"""
        result = {}

        for attr, _ in self.swagger_types.items():
            value = getattr(self, attr)
            if isinstance(value, list):
                result[attr] = list(map(
                    lambda x: x.to_dict() if hasattr(x, "to_dict") else x,
                    value
                ))
            elif hasattr(value, "to_dict"):
                result[attr] = value.to_dict()
            elif isinstance(value, dict):
                result[attr] = dict(map(
                    lambda item: (item[0], item[1].to_dict())
                    if hasattr(item[1], "to_dict") else item,
                    value.items()
                ))
            else:
                result[attr] = value
        if issubclass(FacInfo, dict):
            for key, value in self.items():
                result[key] = value

        return result

    def to_str(self):
        """Returns the string representation of the model"""
        return pprint.pformat(self.to_dict())

    def __repr__(self):
        """For `print` and `pprint`"""
        return self.to_str()

    def __eq__(self, other):
        """Returns true if both objects are equal"""
        if not isinstance(other, FacInfo):
            return False

        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        """Returns true if both objects are not equal"""
        return not self == other


class HostInfo(object):
    """NOTE: This class is auto generated by the swagger code generator program

    Do not edit the class manually.
    """

    """
    Attributes:
      swagger_types (dict): The key is attribute name
                            and the value is attribute type.
      attribute_map (dict): The key is attribute name
                            and the value is json key in definition.
    """
    swagger_types = {
        'host_uuid': 'str',
        'host_name': 'str',
        'host_location': 'str',
        'host_nqn': 'str',
        'created_at': 'datetime',
        'fac_enabled': 'bool',
        'facs': 'list[FacInfo]'
    }

    attribute_map = {
        'host_uuid': 'host_uuid',
        'host_name': 'host_name',
        'host_location': 'host_location',
        'host_nqn': 'host_nqn',
        'created_at': 'created_at',
        'fac_enabled': 'fac_enabled',
        'facs': 'facs'
    }

    def __init__(self, host_uuid=None, host_name=None, host_location=None, host_nqn=None, created_at=None, fac_enabled=None, facs=None):  # noqa: E501
        """HostInfo - a model defined in Swagger"""  # noqa: E501

        self._host_uuid = None
        self._host_name = None
        self._host_location = None
        self._host_nqn = None
        self._created_at = None
        self._fac_enabled = None
        self._facs = None
        self.discriminator = None

        if host_uuid is not None:
            self.host_uuid = host_uuid
        if host_name is not None:
            self.host_name = host_name
        if host_location is not None:
            self.host_location = host_location
        if host_nqn is not None:
            self.host_nqn = host_nqn
        if created_at is not None:
            self.created_at = created_at
        if fac_enabled is not None:
            self.fac_enabled = fac_enabled
        if facs is not None:
            self.facs = facs

    @property
    def host_uuid(self):
        """Gets the host_uuid of this HostInfo.  # noqa: E501

        This UUID is generated by the StorageService  # noqa: E501

        :return: The host_uuid of this HostInfo.  # noqa: E501
        :rtype: str
        """
        return self._host_uuid

    @host_uuid.setter
    def host_uuid(self, host_uuid):
        """Sets the host_uuid of this HostInfo.

        This UUID is generated by the StorageService  # noqa: E501

        :param host_uuid: The host_uuid of this HostInfo.  # noqa: E501
        :type: str
        """

        self._host_uuid = host_uuid

    @property
    def host_name(self):
        """Gets the host_name of this HostInfo.  # noqa: E501

        This is the user-friendly name assigned by an admin to this host.  # noqa: E501

        :return: The host_name of this HostInfo.  # noqa: E501
        :rtype: str
        """
        return self._host_name

    @host_name.setter
    def host_name(self, host_name):
        """Sets the host_name of this HostInfo.

        This is the user-friendly name assigned by an admin to this host.  # noqa: E501

        :param host_name: The host_name of this HostInfo.  # noqa: E501
        :type: str
        """
        if host_name is not None and len(host_name) > 223:
            raise ValueError("Invalid value for `host_name`, length must be less than or equal to `223`")  # noqa: E501

        self._host_name = host_name

    @property
    def host_location(self):
        """Gets the host_location of this HostInfo.  # noqa: E501

        Optional, location information assigned by admin such as Chassis, Rack or shelf IDs.  # noqa: E501

        :return: The host_location of this HostInfo.  # noqa: E501
        :rtype: str
        """
        return self._host_location

    @host_location.setter
    def host_location(self, host_location):
        """Sets the host_location of this HostInfo.

        Optional, location information assigned by admin such as Chassis, Rack or shelf IDs.  # noqa: E501

        :param host_location: The host_location of this HostInfo.  # noqa: E501
        :type: str
        """

        self._host_location = host_location

    @property
    def host_nqn(self):
        """Gets the host_nqn of this HostInfo.  # noqa: E501

        The nqn name used during NVME connect operations  # noqa: E501

        :return: The host_nqn of this HostInfo.  # noqa: E501
        :rtype: str
        """
        return self._host_nqn

    @host_nqn.setter
    def host_nqn(self, host_nqn):
        """Sets the host_nqn of this HostInfo.

        The nqn name used during NVME connect operations  # noqa: E501

        :param host_nqn: The host_nqn of this HostInfo.  # noqa: E501
        :type: str
        """
        if host_nqn is not None and len(host_nqn) > 223:
            raise ValueError("Invalid value for `host_nqn`, length must be less than or equal to `223`")  # noqa: E501

        self._host_nqn = host_nqn

    @property
    def created_at(self):
        """Gets the created_at of this HostInfo.  # noqa: E501

        Time at which this entry was created. Generated by StorageService and useful in paginating a list of hosts  # noqa: E501

        :return: The created_at of this HostInfo.  # noqa: E501
        :rtype: datetime
        """
        return self._created_at

    @created_at.setter
    def created_at(self, created_at):
        """Sets the created_at of this HostInfo.

        Time at which this entry was created. Generated by StorageService and useful in paginating a list of hosts  # noqa: E501

        :param created_at: The created_at of this HostInfo.  # noqa: E501
        :type: datetime
        """

        self._created_at = created_at

    @property
    def fac_enabled(self):
        """Gets the fac_enabled of this HostInfo.  # noqa: E501

        Set to true if this server/host contains at least one FAC cards.  # noqa: E501

        :return: The fac_enabled of this HostInfo.  # noqa: E501
        :rtype: bool
        """
        return self._fac_enabled

    @fac_enabled.setter
    def fac_enabled(self, fac_enabled):
        """Sets the fac_enabled of this HostInfo.

        Set to true if this server/host contains at least one FAC cards.  # noqa: E501

        :param fac_enabled: The fac_enabled of this HostInfo.  # noqa: E501
        :type: bool
        """

        self._fac_enabled = fac_enabled

    @property
    def facs(self):
        """Gets the facs of this HostInfo.  # noqa: E501

        Contains an array of FAC UUIDs, when fac_enabled is set to True  # noqa: E501

        :return: The facs of this HostInfo.  # noqa: E501
        :rtype: list[FacInfo]
        """
        return self._facs

    @facs.setter
    def facs(self, facs):
        """Sets the facs of this HostInfo.

        Contains an array of FAC UUIDs, when fac_enabled is set to True  # noqa: E501

        :param facs: The facs of this HostInfo.  # noqa: E501
        :type: list[FacInfo]
        """

        self._facs = facs

    def to_dict(self):
        """Returns the model properties as a dict"""
        result = {}

        for attr, _ in self.swagger_types.items():
            value = getattr(self, attr)
            if isinstance(value, list):
                result[attr] = list(map(
                    lambda x: x.to_dict() if hasattr(x, "to_dict") else x,
                    value
                ))
            elif hasattr(value, "to_dict"):
                result[attr] = value.to_dict()
            elif isinstance(value, dict):
                result[attr] = dict(map(
                    lambda item: (item[0], item[1].to_dict())
                    if hasattr(item[1], "to_dict") else item,
                    value.items()
                ))
            else:
                result[attr] = value
        if issubclass(HostInfo, dict):
            for key, value in self.items():
                result[key] = value

        return result

    def to_str(self):
        """Returns the string representation of the model"""
        return pprint.pformat(self.to_dict())

    def __repr__(self):
        """For `print` and `pprint`"""
        return self.to_str()

    def __eq__(self, other):
        """Returns true if both objects are equal"""
        if not isinstance(other, HostInfo):
            return False

        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        """Returns true if both objects are not equal"""
        return not self == other


class Identity(object):
    """NOTE: This class is auto generated by the swagger code generator program

    Do not edit the class manually.
    """

    """
    Attributes:
      swagger_types (dict): The key is attribute name
                            and the value is attribute type.
      attribute_map (dict): The key is attribute name
                            and the value is json key in definition.
    """
    swagger_types = {
        'firmware_revision': 'str',
        'pci_vendor_id': 'str',
        'serial_number': 'str',
        'model_number': 'str'
    }

    attribute_map = {
        'firmware_revision': 'firmware_revision',
        'pci_vendor_id': 'pci_vendor_id',
        'serial_number': 'serial_number',
        'model_number': 'model_number'
    }

    def __init__(self, firmware_revision=None, pci_vendor_id=None, serial_number=None, model_number=None):  # noqa: E501
        """Identity - a model defined in Swagger"""  # noqa: E501

        self._firmware_revision = None
        self._pci_vendor_id = None
        self._serial_number = None
        self._model_number = None
        self.discriminator = None

        if firmware_revision is not None:
            self.firmware_revision = firmware_revision
        if pci_vendor_id is not None:
            self.pci_vendor_id = pci_vendor_id
        if serial_number is not None:
            self.serial_number = serial_number
        if model_number is not None:
            self.model_number = model_number

    @property
    def firmware_revision(self):
        """Gets the firmware_revision of this Identity.  # noqa: E501


        :return: The firmware_revision of this Identity.  # noqa: E501
        :rtype: str
        """
        return self._firmware_revision

    @firmware_revision.setter
    def firmware_revision(self, firmware_revision):
        """Sets the firmware_revision of this Identity.


        :param firmware_revision: The firmware_revision of this Identity.  # noqa: E501
        :type: str
        """

        self._firmware_revision = firmware_revision

    @property
    def pci_vendor_id(self):
        """Gets the pci_vendor_id of this Identity.  # noqa: E501


        :return: The pci_vendor_id of this Identity.  # noqa: E501
        :rtype: str
        """
        return self._pci_vendor_id

    @pci_vendor_id.setter
    def pci_vendor_id(self, pci_vendor_id):
        """Sets the pci_vendor_id of this Identity.


        :param pci_vendor_id: The pci_vendor_id of this Identity.  # noqa: E501
        :type: str
        """

        self._pci_vendor_id = pci_vendor_id

    @property
    def serial_number(self):
        """Gets the serial_number of this Identity.  # noqa: E501


        :return: The serial_number of this Identity.  # noqa: E501
        :rtype: str
        """
        return self._serial_number

    @serial_number.setter
    def serial_number(self, serial_number):
        """Sets the serial_number of this Identity.


        :param serial_number: The serial_number of this Identity.  # noqa: E501
        :type: str
        """

        self._serial_number = serial_number

    @property
    def model_number(self):
        """Gets the model_number of this Identity.  # noqa: E501


        :return: The model_number of this Identity.  # noqa: E501
        :rtype: str
        """
        return self._model_number

    @model_number.setter
    def model_number(self, model_number):
        """Sets the model_number of this Identity.


        :param model_number: The model_number of this Identity.  # noqa: E501
        :type: str
        """

        self._model_number = model_number

    def to_dict(self):
        """Returns the model properties as a dict"""
        result = {}

        for attr, _ in self.swagger_types.items():
            value = getattr(self, attr)
            if isinstance(value, list):
                result[attr] = list(map(
                    lambda x: x.to_dict() if hasattr(x, "to_dict") else x,
                    value
                ))
            elif hasattr(value, "to_dict"):
                result[attr] = value.to_dict()
            elif isinstance(value, dict):
                result[attr] = dict(map(
                    lambda item: (item[0], item[1].to_dict())
                    if hasattr(item[1], "to_dict") else item,
                    value.items()
                ))
            else:
                result[attr] = value
        if issubclass(Identity, dict):
            for key, value in self.items():
                result[key] = value

        return result

    def to_str(self):
        """Returns the string representation of the model"""
        return pprint.pformat(self.to_dict())

    def __repr__(self):
        """For `print` and `pprint`"""
        return self.to_str()

    def __eq__(self, other):
        """Returns true if both objects are equal"""
        if not isinstance(other, Identity):
            return False

        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        """Returns true if both objects are not equal"""
        return not self == other


class MapOfPorts(object):
    """NOTE: This class is auto generated by the swagger code generator program

    Do not edit the class manually.
    """

    """
    Attributes:
      swagger_types (dict): The key is attribute name
                            and the value is attribute type.
      attribute_map (dict): The key is attribute name
                            and the value is json key in definition.
    """
    swagger_types = {
    }

    attribute_map = {
    }

    def __init__(self):  # noqa: E501
        """MapOfPorts - a model defined in Swagger"""  # noqa: E501
        self.discriminator = None

    def to_dict(self):
        """Returns the model properties as a dict"""
        result = {}

        for attr, _ in self.swagger_types.items():
            value = getattr(self, attr)
            if isinstance(value, list):
                result[attr] = list(map(
                    lambda x: x.to_dict() if hasattr(x, "to_dict") else x,
                    value
                ))
            elif hasattr(value, "to_dict"):
                result[attr] = value.to_dict()
            elif isinstance(value, dict):
                result[attr] = dict(map(
                    lambda item: (item[0], item[1].to_dict())
                    if hasattr(item[1], "to_dict") else item,
                    value.items()
                ))
            else:
                result[attr] = value
        if issubclass(MapOfPorts, dict):
            for key, value in self.items():
                result[key] = value

        return result

    def to_str(self):
        """Returns the string representation of the model"""
        return pprint.pformat(self.to_dict())

    def __repr__(self):
        """For `print` and `pprint`"""
        return self.to_str()

    def __eq__(self, other):
        """Returns true if both objects are equal"""
        if not isinstance(other, MapOfPorts):
            return False

        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        """Returns true if both objects are not equal"""
        return not self == other


class NodeDpu(object):
    """NOTE: This class is auto generated by the swagger code generator program

    Do not edit the class manually.
    """

    """
    Attributes:
      swagger_types (dict): The key is attribute name
                            and the value is attribute type.
      attribute_map (dict): The key is attribute name
                            and the value is json key in definition.
    """
    swagger_types = {
        'available': 'bool',
        'fault_zones': 'list[str]',
        'mgmt_ip': 'str',
        'mgmt_port': 'str',
        'name': 'str',
        'node_class': 'str',
        'state': 'str',
        'uuid': 'str',
        'version': 'str',
        'sku': 'str',
        'product': 'str',
        'dpus': 'list[Dpu]',
        'fault_domain_id': 'str',
        'host_uuid': 'str'
    }

    attribute_map = {
        'available': 'available',
        'fault_zones': 'fault_zones',
        'mgmt_ip': 'mgmt_ip',
        'mgmt_port': 'mgmt_port',
        'name': 'name',
        'node_class': 'node_class',
        'state': 'state',
        'uuid': 'uuid',
        'version': 'version',
        'sku': 'sku',
        'product': 'product',
        'dpus': 'dpus',
        'fault_domain_id': 'fault_domain_id',
        'host_uuid': 'host_uuid'
    }

    def __init__(self, available=None, fault_zones=None, mgmt_ip=None, mgmt_port=None, name=None, node_class=None, state=None, uuid=None, version=None, sku=None, product='UNKNOWN', dpus=None, fault_domain_id=None, host_uuid=None):  # noqa: E501
        """NodeDpu - a model defined in Swagger"""  # noqa: E501

        self._available = None
        self._fault_zones = None
        self._mgmt_ip = None
        self._mgmt_port = None
        self._name = None
        self._node_class = None
        self._state = None
        self._uuid = None
        self._version = None
        self._sku = None
        self._product = None
        self._dpus = None
        self._fault_domain_id = None
        self._host_uuid = None
        self.discriminator = None

        if available is not None:
            self.available = available
        if fault_zones is not None:
            self.fault_zones = fault_zones
        if mgmt_ip is not None:
            self.mgmt_ip = mgmt_ip
        if mgmt_port is not None:
            self.mgmt_port = mgmt_port
        if name is not None:
            self.name = name
        if node_class is not None:
            self.node_class = node_class
        if state is not None:
            self.state = state
        if uuid is not None:
            self.uuid = uuid
        if version is not None:
            self.version = version
        if sku is not None:
            self.sku = sku
        if product is not None:
            self.product = product
        if dpus is not None:
            self.dpus = dpus
        if fault_domain_id is not None:
            self.fault_domain_id = fault_domain_id
        if host_uuid is not None:
            self.host_uuid = host_uuid

    @property
    def available(self):
        """Gets the available of this NodeDpu.  # noqa: E501


        :return: The available of this NodeDpu.  # noqa: E501
        :rtype: bool
        """
        return self._available

    @available.setter
    def available(self, available):
        """Sets the available of this NodeDpu.


        :param available: The available of this NodeDpu.  # noqa: E501
        :type: bool
        """

        self._available = available

    @property
    def fault_zones(self):
        """Gets the fault_zones of this NodeDpu.  # noqa: E501


        :return: The fault_zones of this NodeDpu.  # noqa: E501
        :rtype: list[str]
        """
        return self._fault_zones

    @fault_zones.setter
    def fault_zones(self, fault_zones):
        """Sets the fault_zones of this NodeDpu.


        :param fault_zones: The fault_zones of this NodeDpu.  # noqa: E501
        :type: list[str]
        """

        self._fault_zones = fault_zones

    @property
    def mgmt_ip(self):
        """Gets the mgmt_ip of this NodeDpu.  # noqa: E501


        :return: The mgmt_ip of this NodeDpu.  # noqa: E501
        :rtype: str
        """
        return self._mgmt_ip

    @mgmt_ip.setter
    def mgmt_ip(self, mgmt_ip):
        """Sets the mgmt_ip of this NodeDpu.


        :param mgmt_ip: The mgmt_ip of this NodeDpu.  # noqa: E501
        :type: str
        """

        self._mgmt_ip = mgmt_ip

    @property
    def mgmt_port(self):
        """Gets the mgmt_port of this NodeDpu.  # noqa: E501


        :return: The mgmt_port of this NodeDpu.  # noqa: E501
        :rtype: str
        """
        return self._mgmt_port

    @mgmt_port.setter
    def mgmt_port(self, mgmt_port):
        """Sets the mgmt_port of this NodeDpu.


        :param mgmt_port: The mgmt_port of this NodeDpu.  # noqa: E501
        :type: str
        """

        self._mgmt_port = mgmt_port

    @property
    def name(self):
        """Gets the name of this NodeDpu.  # noqa: E501


        :return: The name of this NodeDpu.  # noqa: E501
        :rtype: str
        """
        return self._name

    @name.setter
    def name(self, name):
        """Sets the name of this NodeDpu.


        :param name: The name of this NodeDpu.  # noqa: E501
        :type: str
        """

        self._name = name

    @property
    def node_class(self):
        """Gets the node_class of this NodeDpu.  # noqa: E501


        :return: The node_class of this NodeDpu.  # noqa: E501
        :rtype: str
        """
        return self._node_class

    @node_class.setter
    def node_class(self, node_class):
        """Sets the node_class of this NodeDpu.


        :param node_class: The node_class of this NodeDpu.  # noqa: E501
        :type: str
        """

        self._node_class = node_class

    @property
    def state(self):
        """Gets the state of this NodeDpu.  # noqa: E501


        :return: The state of this NodeDpu.  # noqa: E501
        :rtype: str
        """
        return self._state

    @state.setter
    def state(self, state):
        """Sets the state of this NodeDpu.


        :param state: The state of this NodeDpu.  # noqa: E501
        :type: str
        """

        self._state = state

    @property
    def uuid(self):
        """Gets the uuid of this NodeDpu.  # noqa: E501


        :return: The uuid of this NodeDpu.  # noqa: E501
        :rtype: str
        """
        return self._uuid

    @uuid.setter
    def uuid(self, uuid):
        """Sets the uuid of this NodeDpu.


        :param uuid: The uuid of this NodeDpu.  # noqa: E501
        :type: str
        """

        self._uuid = uuid

    @property
    def version(self):
        """Gets the version of this NodeDpu.  # noqa: E501


        :return: The version of this NodeDpu.  # noqa: E501
        :rtype: str
        """
        return self._version

    @version.setter
    def version(self, version):
        """Sets the version of this NodeDpu.


        :param version: The version of this NodeDpu.  # noqa: E501
        :type: str
        """

        self._version = version

    @property
    def sku(self):
        """Gets the sku of this NodeDpu.  # noqa: E501


        :return: The sku of this NodeDpu.  # noqa: E501
        :rtype: str
        """
        return self._sku

    @sku.setter
    def sku(self, sku):
        """Sets the sku of this NodeDpu.


        :param sku: The sku of this NodeDpu.  # noqa: E501
        :type: str
        """

        self._sku = sku

    @property
    def product(self):
        """Gets the product of this NodeDpu.  # noqa: E501


        :return: The product of this NodeDpu.  # noqa: E501
        :rtype: str
        """
        return self._product

    @product.setter
    def product(self, product):
        """Sets the product of this NodeDpu.


        :param product: The product of this NodeDpu.  # noqa: E501
        :type: str
        """
        allowed_values = ["UNKNOWN", "DS200", "FC200", "FC50", "FS800", "FC100", "FS1600"]  # noqa: E501
        if product not in allowed_values:
            raise ValueError(
                "Invalid value for `product` ({0}), must be one of {1}"  # noqa: E501
                .format(product, allowed_values)
            )

        self._product = product

    @property
    def dpus(self):
        """Gets the dpus of this NodeDpu.  # noqa: E501


        :return: The dpus of this NodeDpu.  # noqa: E501
        :rtype: list[Dpu]
        """
        return self._dpus

    @dpus.setter
    def dpus(self, dpus):
        """Sets the dpus of this NodeDpu.


        :param dpus: The dpus of this NodeDpu.  # noqa: E501
        :type: list[Dpu]
        """

        self._dpus = dpus

    @property
    def fault_domain_id(self):
        """Gets the fault_domain_id of this NodeDpu.  # noqa: E501


        :return: The fault_domain_id of this NodeDpu.  # noqa: E501
        :rtype: str
        """
        return self._fault_domain_id

    @fault_domain_id.setter
    def fault_domain_id(self, fault_domain_id):
        """Sets the fault_domain_id of this NodeDpu.


        :param fault_domain_id: The fault_domain_id of this NodeDpu.  # noqa: E501
        :type: str
        """

        self._fault_domain_id = fault_domain_id

    @property
    def host_uuid(self):
        """Gets the host_uuid of this NodeDpu.  # noqa: E501

        UUID of the host to which the node is added to  # noqa: E501

        :return: The host_uuid of this NodeDpu.  # noqa: E501
        :rtype: str
        """
        return self._host_uuid

    @host_uuid.setter
    def host_uuid(self, host_uuid):
        """Sets the host_uuid of this NodeDpu.

        UUID of the host to which the node is added to  # noqa: E501

        :param host_uuid: The host_uuid of this NodeDpu.  # noqa: E501
        :type: str
        """

        self._host_uuid = host_uuid

    def to_dict(self):
        """Returns the model properties as a dict"""
        result = {}

        for attr, _ in self.swagger_types.items():
            value = getattr(self, attr)
            if isinstance(value, list):
                result[attr] = list(map(
                    lambda x: x.to_dict() if hasattr(x, "to_dict") else x,
                    value
                ))
            elif hasattr(value, "to_dict"):
                result[attr] = value.to_dict()
            elif isinstance(value, dict):
                result[attr] = dict(map(
                    lambda item: (item[0], item[1].to_dict())
                    if hasattr(item[1], "to_dict") else item,
                    value.items()
                ))
            else:
                result[attr] = value
        if issubclass(NodeDpu, dict):
            for key, value in self.items():
                result[key] = value

        return result

    def to_str(self):
        """Returns the string representation of the model"""
        return pprint.pformat(self.to_dict())

    def __repr__(self):
        """For `print` and `pprint`"""
        return self.to_str()

    def __eq__(self, other):
        """Returns true if both objects are equal"""
        if not isinstance(other, NodeDpu):
            return False

        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        """Returns true if both objects are not equal"""
        return not self == other


class Operation(object):
    """NOTE: This class is auto generated by the swagger code generator program

    Do not edit the class manually.
    """

    """
    Attributes:
      swagger_types (dict): The key is attribute name
                            and the value is attribute type.
      attribute_map (dict): The key is attribute name
                            and the value is json key in definition.
    """
    swagger_types = {
        'operation_name': 'str',
        'percentage_complete': 'int'
    }

    attribute_map = {
        'operation_name': 'operation_name',
        'percentage_complete': 'percentage_complete'
    }

    def __init__(self, operation_name=None, percentage_complete=None):  # noqa: E501
        """Operation - a model defined in Swagger"""  # noqa: E501

        self._operation_name = None
        self._percentage_complete = None
        self.discriminator = None

        if operation_name is not None:
            self.operation_name = operation_name
        if percentage_complete is not None:
            self.percentage_complete = percentage_complete

    @property
    def operation_name(self):
        """Gets the operation_name of this Operation.  # noqa: E501

        The name of the operation  # noqa: E501

        :return: The operation_name of this Operation.  # noqa: E501
        :rtype: str
        """
        return self._operation_name

    @operation_name.setter
    def operation_name(self, operation_name):
        """Sets the operation_name of this Operation.

        The name of the operation  # noqa: E501

        :param operation_name: The operation_name of this Operation.  # noqa: E501
        :type: str
        """
        allowed_values = ["rebuild", "expansion", "rebalance", "hydration"]  # noqa: E501
        if operation_name not in allowed_values:
            raise ValueError(
                "Invalid value for `operation_name` ({0}), must be one of {1}"  # noqa: E501
                .format(operation_name, allowed_values)
            )

        self._operation_name = operation_name

    @property
    def percentage_complete(self):
        """Gets the percentage_complete of this Operation.  # noqa: E501


        :return: The percentage_complete of this Operation.  # noqa: E501
        :rtype: int
        """
        return self._percentage_complete

    @percentage_complete.setter
    def percentage_complete(self, percentage_complete):
        """Sets the percentage_complete of this Operation.


        :param percentage_complete: The percentage_complete of this Operation.  # noqa: E501
        :type: int
        """
        if percentage_complete is not None and percentage_complete > 100:  # noqa: E501
            raise ValueError("Invalid value for `percentage_complete`, must be a value less than or equal to `100`")  # noqa: E501
        if percentage_complete is not None and percentage_complete < 0:  # noqa: E501
            raise ValueError("Invalid value for `percentage_complete`, must be a value greater than or equal to `0`")  # noqa: E501

        self._percentage_complete = percentage_complete

    def to_dict(self):
        """Returns the model properties as a dict"""
        result = {}

        for attr, _ in self.swagger_types.items():
            value = getattr(self, attr)
            if isinstance(value, list):
                result[attr] = list(map(
                    lambda x: x.to_dict() if hasattr(x, "to_dict") else x,
                    value
                ))
            elif hasattr(value, "to_dict"):
                result[attr] = value.to_dict()
            elif isinstance(value, dict):
                result[attr] = dict(map(
                    lambda item: (item[0], item[1].to_dict())
                    if hasattr(item[1], "to_dict") else item,
                    value.items()
                ))
            else:
                result[attr] = value
        if issubclass(Operation, dict):
            for key, value in self.items():
                result[key] = value

        return result

    def to_str(self):
        """Returns the string representation of the model"""
        return pprint.pformat(self.to_dict())

    def __repr__(self):
        """For `print` and `pprint`"""
        return self.to_str()

    def __eq__(self, other):
        """Returns true if both objects are equal"""
        if not isinstance(other, Operation):
            return False

        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        """Returns true if both objects are not equal"""
        return not self == other


class Port(object):
    """NOTE: This class is auto generated by the swagger code generator program

    Do not edit the class manually.
    """

    """
    Attributes:
      swagger_types (dict): The key is attribute name
                            and the value is attribute type.
      attribute_map (dict): The key is attribute name
                            and the value is json key in definition.
    """
    swagger_types = {
        'uuid': 'str',
        'transport': 'Transport',
        'host_nqn': 'str',
        'ip': 'str',
        'nsid': 'int',
        'remote_ip': 'str',
        'subsys_nqn': 'str',
        'fnid': 'object',
        'huid': 'object',
        'ctlid': 'object',
        'pci_bus': 'int',
        'pci_device': 'int',
        'pci_function': 'int',
        'ctrlr_uuid': 'str',
        'secondary_ctrlr_uuid': 'str',
        'host_uuid': 'str'
    }

    attribute_map = {
        'uuid': 'uuid',
        'transport': 'transport',
        'host_nqn': 'host_nqn',
        'ip': 'ip',
        'nsid': 'nsid',
        'remote_ip': 'remote_ip',
        'subsys_nqn': 'subsys_nqn',
        'fnid': 'fnid',
        'huid': 'huid',
        'ctlid': 'ctlid',
        'pci_bus': 'pci_bus',
        'pci_device': 'pci_device',
        'pci_function': 'pci_function',
        'ctrlr_uuid': 'ctrlr_uuid',
        'secondary_ctrlr_uuid': 'secondary_ctrlr_uuid',
        'host_uuid': 'host_uuid'
    }

    def __init__(self, uuid=None, transport=None, host_nqn=None, ip=None, nsid=None, remote_ip=None, subsys_nqn=None, fnid=None, huid=None, ctlid=None, pci_bus=None, pci_device=None, pci_function=None, ctrlr_uuid=None, secondary_ctrlr_uuid=None, host_uuid=None):  # noqa: E501
        """Port - a model defined in Swagger"""  # noqa: E501

        self._uuid = None
        self._transport = None
        self._host_nqn = None
        self._ip = None
        self._nsid = None
        self._remote_ip = None
        self._subsys_nqn = None
        self._fnid = None
        self._huid = None
        self._ctlid = None
        self._pci_bus = None
        self._pci_device = None
        self._pci_function = None
        self._ctrlr_uuid = None
        self._secondary_ctrlr_uuid = None
        self._host_uuid = None
        self.discriminator = None

        self.uuid = uuid
        self.transport = transport
        if host_nqn is not None:
            self.host_nqn = host_nqn
        if ip is not None:
            self.ip = ip
        if nsid is not None:
            self.nsid = nsid
        if remote_ip is not None:
            self.remote_ip = remote_ip
        if subsys_nqn is not None:
            self.subsys_nqn = subsys_nqn
        if fnid is not None:
            self.fnid = fnid
        if huid is not None:
            self.huid = huid
        if ctlid is not None:
            self.ctlid = ctlid
        if pci_bus is not None:
            self.pci_bus = pci_bus
        if pci_device is not None:
            self.pci_device = pci_device
        if pci_function is not None:
            self.pci_function = pci_function
        if ctrlr_uuid is not None:
            self.ctrlr_uuid = ctrlr_uuid
        if secondary_ctrlr_uuid is not None:
            self.secondary_ctrlr_uuid = secondary_ctrlr_uuid
        if host_uuid is not None:
            self.host_uuid = host_uuid

    @property
    def uuid(self):
        """Gets the uuid of this Port.  # noqa: E501

        assigned by FC  # noqa: E501

        :return: The uuid of this Port.  # noqa: E501
        :rtype: str
        """
        return self._uuid

    @uuid.setter
    def uuid(self, uuid):
        """Sets the uuid of this Port.

        assigned by FC  # noqa: E501

        :param uuid: The uuid of this Port.  # noqa: E501
        :type: str
        """
        if uuid is None:
            raise ValueError("Invalid value for `uuid`, must not be `None`")  # noqa: E501

        self._uuid = uuid

    @property
    def transport(self):
        """Gets the transport of this Port.  # noqa: E501


        :return: The transport of this Port.  # noqa: E501
        :rtype: Transport
        """
        return self._transport

    @transport.setter
    def transport(self, transport):
        """Sets the transport of this Port.


        :param transport: The transport of this Port.  # noqa: E501
        :type: Transport
        """
        if transport is None:
            raise ValueError("Invalid value for `transport`, must not be `None`")  # noqa: E501

        self._transport = transport

    @property
    def host_nqn(self):
        """Gets the host_nqn of this Port.  # noqa: E501


        :return: The host_nqn of this Port.  # noqa: E501
        :rtype: str
        """
        return self._host_nqn

    @host_nqn.setter
    def host_nqn(self, host_nqn):
        """Sets the host_nqn of this Port.


        :param host_nqn: The host_nqn of this Port.  # noqa: E501
        :type: str
        """

        self._host_nqn = host_nqn

    @property
    def ip(self):
        """Gets the ip of this Port.  # noqa: E501


        :return: The ip of this Port.  # noqa: E501
        :rtype: str
        """
        return self._ip

    @ip.setter
    def ip(self, ip):
        """Sets the ip of this Port.


        :param ip: The ip of this Port.  # noqa: E501
        :type: str
        """

        self._ip = ip

    @property
    def nsid(self):
        """Gets the nsid of this Port.  # noqa: E501


        :return: The nsid of this Port.  # noqa: E501
        :rtype: int
        """
        return self._nsid

    @nsid.setter
    def nsid(self, nsid):
        """Sets the nsid of this Port.


        :param nsid: The nsid of this Port.  # noqa: E501
        :type: int
        """

        self._nsid = nsid

    @property
    def remote_ip(self):
        """Gets the remote_ip of this Port.  # noqa: E501


        :return: The remote_ip of this Port.  # noqa: E501
        :rtype: str
        """
        return self._remote_ip

    @remote_ip.setter
    def remote_ip(self, remote_ip):
        """Sets the remote_ip of this Port.


        :param remote_ip: The remote_ip of this Port.  # noqa: E501
        :type: str
        """

        self._remote_ip = remote_ip

    @property
    def subsys_nqn(self):
        """Gets the subsys_nqn of this Port.  # noqa: E501


        :return: The subsys_nqn of this Port.  # noqa: E501
        :rtype: str
        """
        return self._subsys_nqn

    @subsys_nqn.setter
    def subsys_nqn(self, subsys_nqn):
        """Sets the subsys_nqn of this Port.


        :param subsys_nqn: The subsys_nqn of this Port.  # noqa: E501
        :type: str
        """

        self._subsys_nqn = subsys_nqn

    @property
    def fnid(self):
        """Gets the fnid of this Port.  # noqa: E501

        Valid for transport=PCI  # noqa: E501

        :return: The fnid of this Port.  # noqa: E501
        :rtype: object
        """
        return self._fnid

    @fnid.setter
    def fnid(self, fnid):
        """Sets the fnid of this Port.

        Valid for transport=PCI  # noqa: E501

        :param fnid: The fnid of this Port.  # noqa: E501
        :type: object
        """

        self._fnid = fnid

    @property
    def huid(self):
        """Gets the huid of this Port.  # noqa: E501

        Valid for transport=PCI  # noqa: E501

        :return: The huid of this Port.  # noqa: E501
        :rtype: object
        """
        return self._huid

    @huid.setter
    def huid(self, huid):
        """Sets the huid of this Port.

        Valid for transport=PCI  # noqa: E501

        :param huid: The huid of this Port.  # noqa: E501
        :type: object
        """

        self._huid = huid

    @property
    def ctlid(self):
        """Gets the ctlid of this Port.  # noqa: E501

        Valid for transport=PCI  # noqa: E501

        :return: The ctlid of this Port.  # noqa: E501
        :rtype: object
        """
        return self._ctlid

    @ctlid.setter
    def ctlid(self, ctlid):
        """Sets the ctlid of this Port.

        Valid for transport=PCI  # noqa: E501

        :param ctlid: The ctlid of this Port.  # noqa: E501
        :type: object
        """

        self._ctlid = ctlid

    @property
    def pci_bus(self):
        """Gets the pci_bus of this Port.  # noqa: E501

        Valid for transport=PCI_BDF  # noqa: E501

        :return: The pci_bus of this Port.  # noqa: E501
        :rtype: int
        """
        return self._pci_bus

    @pci_bus.setter
    def pci_bus(self, pci_bus):
        """Sets the pci_bus of this Port.

        Valid for transport=PCI_BDF  # noqa: E501

        :param pci_bus: The pci_bus of this Port.  # noqa: E501
        :type: int
        """

        self._pci_bus = pci_bus

    @property
    def pci_device(self):
        """Gets the pci_device of this Port.  # noqa: E501

        Valid for transport=PCI_BDF  # noqa: E501

        :return: The pci_device of this Port.  # noqa: E501
        :rtype: int
        """
        return self._pci_device

    @pci_device.setter
    def pci_device(self, pci_device):
        """Sets the pci_device of this Port.

        Valid for transport=PCI_BDF  # noqa: E501

        :param pci_device: The pci_device of this Port.  # noqa: E501
        :type: int
        """

        self._pci_device = pci_device

    @property
    def pci_function(self):
        """Gets the pci_function of this Port.  # noqa: E501

        Valid for transport=PCI_BDF  # noqa: E501

        :return: The pci_function of this Port.  # noqa: E501
        :rtype: int
        """
        return self._pci_function

    @pci_function.setter
    def pci_function(self, pci_function):
        """Sets the pci_function of this Port.

        Valid for transport=PCI_BDF  # noqa: E501

        :param pci_function: The pci_function of this Port.  # noqa: E501
        :type: int
        """

        self._pci_function = pci_function

    @property
    def ctrlr_uuid(self):
        """Gets the ctrlr_uuid of this Port.  # noqa: E501


        :return: The ctrlr_uuid of this Port.  # noqa: E501
        :rtype: str
        """
        return self._ctrlr_uuid

    @ctrlr_uuid.setter
    def ctrlr_uuid(self, ctrlr_uuid):
        """Sets the ctrlr_uuid of this Port.


        :param ctrlr_uuid: The ctrlr_uuid of this Port.  # noqa: E501
        :type: str
        """

        self._ctrlr_uuid = ctrlr_uuid

    @property
    def secondary_ctrlr_uuid(self):
        """Gets the secondary_ctrlr_uuid of this Port.  # noqa: E501


        :return: The secondary_ctrlr_uuid of this Port.  # noqa: E501
        :rtype: str
        """
        return self._secondary_ctrlr_uuid

    @secondary_ctrlr_uuid.setter
    def secondary_ctrlr_uuid(self, secondary_ctrlr_uuid):
        """Sets the secondary_ctrlr_uuid of this Port.


        :param secondary_ctrlr_uuid: The secondary_ctrlr_uuid of this Port.  # noqa: E501
        :type: str
        """

        self._secondary_ctrlr_uuid = secondary_ctrlr_uuid

    @property
    def host_uuid(self):
        """Gets the host_uuid of this Port.  # noqa: E501

        UUID of the host to which the volume is attached to  # noqa: E501

        :return: The host_uuid of this Port.  # noqa: E501
        :rtype: str
        """
        return self._host_uuid

    @host_uuid.setter
    def host_uuid(self, host_uuid):
        """Sets the host_uuid of this Port.

        UUID of the host to which the volume is attached to  # noqa: E501

        :param host_uuid: The host_uuid of this Port.  # noqa: E501
        :type: str
        """

        self._host_uuid = host_uuid

    def to_dict(self):
        """Returns the model properties as a dict"""
        result = {}

        for attr, _ in self.swagger_types.items():
            value = getattr(self, attr)
            if isinstance(value, list):
                result[attr] = list(map(
                    lambda x: x.to_dict() if hasattr(x, "to_dict") else x,
                    value
                ))
            elif hasattr(value, "to_dict"):
                result[attr] = value.to_dict()
            elif isinstance(value, dict):
                result[attr] = dict(map(
                    lambda item: (item[0], item[1].to_dict())
                    if hasattr(item[1], "to_dict") else item,
                    value.items()
                ))
            else:
                result[attr] = value
        if issubclass(Port, dict):
            for key, value in self.items():
                result[key] = value

        return result

    def to_str(self):
        """Returns the string representation of the model"""
        return pprint.pformat(self.to_dict())

    def __repr__(self):
        """For `print` and `pprint`"""
        return self.to_str()

    def __eq__(self, other):
        """Returns true if both objects are equal"""
        if not isinstance(other, Port):
            return False

        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        """Returns true if both objects are not equal"""
        return not self == other


class RebuildState(object):
    """NOTE: This class is auto generated by the swagger code generator program

    Do not edit the class manually.
    """

    """
    allowed enum values
    """
    STATE_NONE = "REBUILD_STATE_NONE"
    START = "REBUILD_START"
    ISSUE = "REBUILD_ISSUE"
    STATE_IN_PROGRESS = "REBUILD_STATE_IN_PROGRESS"
    STATE_DELETE_FAILED = "REBUILD_STATE_DELETE_FAILED"
    SUSPENDED_NO_SPACE = "REBUILD_SUSPENDED_NO_SPACE"

    """
    Attributes:
      swagger_types (dict): The key is attribute name
                            and the value is attribute type.
      attribute_map (dict): The key is attribute name
                            and the value is json key in definition.
    """
    swagger_types = {
    }

    attribute_map = {
    }

    def __init__(self):  # noqa: E501
        """RebuildState - a model defined in Swagger"""  # noqa: E501
        self.discriminator = None

    def to_dict(self):
        """Returns the model properties as a dict"""
        result = {}

        for attr, _ in self.swagger_types.items():
            value = getattr(self, attr)
            if isinstance(value, list):
                result[attr] = list(map(
                    lambda x: x.to_dict() if hasattr(x, "to_dict") else x,
                    value
                ))
            elif hasattr(value, "to_dict"):
                result[attr] = value.to_dict()
            elif isinstance(value, dict):
                result[attr] = dict(map(
                    lambda item: (item[0], item[1].to_dict())
                    if hasattr(item[1], "to_dict") else item,
                    value.items()
                ))
            else:
                result[attr] = value
        if issubclass(RebuildState, dict):
            for key, value in self.items():
                result[key] = value

        return result

    def to_str(self):
        """Returns the string representation of the model"""
        return pprint.pformat(self.to_dict())

    def __repr__(self):
        """For `print` and `pprint`"""
        return self.to_str()

    def __eq__(self, other):
        """Returns true if both objects are equal"""
        if not isinstance(other, RebuildState):
            return False

        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        """Returns true if both objects are not equal"""
        return not self == other


class ResourceState(object):
    """NOTE: This class is auto generated by the swagger code generator program

    Do not edit the class manually.
    """

    """
    allowed enum values
    """
    INIT = "Init"
    ONLINE = "Online"
    FAILED = "Failed"
    DEGRADED = "Degraded"
    STOPPED = "Stopped"
    UNKNOWN = "Unknown"

    """
    Attributes:
      swagger_types (dict): The key is attribute name
                            and the value is attribute type.
      attribute_map (dict): The key is attribute name
                            and the value is json key in definition.
    """
    swagger_types = {
    }

    attribute_map = {
    }

    def __init__(self):  # noqa: E501
        """ResourceState - a model defined in Swagger"""  # noqa: E501
        self.discriminator = None

    def to_dict(self):
        """Returns the model properties as a dict"""
        result = {}

        for attr, _ in self.swagger_types.items():
            value = getattr(self, attr)
            if isinstance(value, list):
                result[attr] = list(map(
                    lambda x: x.to_dict() if hasattr(x, "to_dict") else x,
                    value
                ))
            elif hasattr(value, "to_dict"):
                result[attr] = value.to_dict()
            elif isinstance(value, dict):
                result[attr] = dict(map(
                    lambda item: (item[0], item[1].to_dict())
                    if hasattr(item[1], "to_dict") else item,
                    value.items()
                ))
            else:
                result[attr] = value
        if issubclass(ResourceState, dict):
            for key, value in self.items():
                result[key] = value

        return result

    def to_str(self):
        """Returns the string representation of the model"""
        return pprint.pformat(self.to_dict())

    def __repr__(self):
        """For `print` and `pprint`"""
        return self.to_str()

    def __eq__(self, other):
        """Returns true if both objects are equal"""
        if not isinstance(other, ResourceState):
            return False

        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        """Returns true if both objects are not equal"""
        return not self == other


class ResponseDataWithCreateUuidString(object):
    """NOTE: This class is auto generated by the swagger code generator program

    Do not edit the class manually.
    """

    """
    Attributes:
      swagger_types (dict): The key is attribute name
                            and the value is attribute type.
      attribute_map (dict): The key is attribute name
                            and the value is json key in definition.
    """
    swagger_types = {
        'status': 'bool',
        'message': 'str',
        'error_message': 'str',
        'warning': 'str',
        'data': 'DataWithUuidStringData'
    }

    attribute_map = {
        'status': 'status',
        'message': 'message',
        'error_message': 'error_message',
        'warning': 'warning',
        'data': 'data'
    }

    def __init__(self, status=None, message=None, error_message=None, warning=None, data=None):  # noqa: E501
        """ResponseDataWithCreateUuidString - a model defined in Swagger"""  # noqa: E501

        self._status = None
        self._message = None
        self._error_message = None
        self._warning = None
        self._data = None
        self.discriminator = None

        self.status = status
        if message is not None:
            self.message = message
        if error_message is not None:
            self.error_message = error_message
        if warning is not None:
            self.warning = warning
        self.data = data

    @property
    def status(self):
        """Gets the status of this ResponseDataWithCreateUuidString.  # noqa: E501


        :return: The status of this ResponseDataWithCreateUuidString.  # noqa: E501
        :rtype: bool
        """
        return self._status

    @status.setter
    def status(self, status):
        """Sets the status of this ResponseDataWithCreateUuidString.


        :param status: The status of this ResponseDataWithCreateUuidString.  # noqa: E501
        :type: bool
        """
        if status is None:
            raise ValueError("Invalid value for `status`, must not be `None`")  # noqa: E501

        self._status = status

    @property
    def message(self):
        """Gets the message of this ResponseDataWithCreateUuidString.  # noqa: E501


        :return: The message of this ResponseDataWithCreateUuidString.  # noqa: E501
        :rtype: str
        """
        return self._message

    @message.setter
    def message(self, message):
        """Sets the message of this ResponseDataWithCreateUuidString.


        :param message: The message of this ResponseDataWithCreateUuidString.  # noqa: E501
        :type: str
        """

        self._message = message

    @property
    def error_message(self):
        """Gets the error_message of this ResponseDataWithCreateUuidString.  # noqa: E501


        :return: The error_message of this ResponseDataWithCreateUuidString.  # noqa: E501
        :rtype: str
        """
        return self._error_message

    @error_message.setter
    def error_message(self, error_message):
        """Sets the error_message of this ResponseDataWithCreateUuidString.


        :param error_message: The error_message of this ResponseDataWithCreateUuidString.  # noqa: E501
        :type: str
        """

        self._error_message = error_message

    @property
    def warning(self):
        """Gets the warning of this ResponseDataWithCreateUuidString.  # noqa: E501


        :return: The warning of this ResponseDataWithCreateUuidString.  # noqa: E501
        :rtype: str
        """
        return self._warning

    @warning.setter
    def warning(self, warning):
        """Sets the warning of this ResponseDataWithCreateUuidString.


        :param warning: The warning of this ResponseDataWithCreateUuidString.  # noqa: E501
        :type: str
        """

        self._warning = warning

    @property
    def data(self):
        """Gets the data of this ResponseDataWithCreateUuidString.  # noqa: E501


        :return: The data of this ResponseDataWithCreateUuidString.  # noqa: E501
        :rtype: DataWithUuidStringData
        """
        return self._data

    @data.setter
    def data(self, data):
        """Sets the data of this ResponseDataWithCreateUuidString.


        :param data: The data of this ResponseDataWithCreateUuidString.  # noqa: E501
        :type: DataWithUuidStringData
        """
        if data is None:
            raise ValueError("Invalid value for `data`, must not be `None`")  # noqa: E501

        self._data = data

    def to_dict(self):
        """Returns the model properties as a dict"""
        result = {}

        for attr, _ in self.swagger_types.items():
            value = getattr(self, attr)
            if isinstance(value, list):
                result[attr] = list(map(
                    lambda x: x.to_dict() if hasattr(x, "to_dict") else x,
                    value
                ))
            elif hasattr(value, "to_dict"):
                result[attr] = value.to_dict()
            elif isinstance(value, dict):
                result[attr] = dict(map(
                    lambda item: (item[0], item[1].to_dict())
                    if hasattr(item[1], "to_dict") else item,
                    value.items()
                ))
            else:
                result[attr] = value
        if issubclass(ResponseDataWithCreateUuidString, dict):
            for key, value in self.items():
                result[key] = value

        return result

    def to_str(self):
        """Returns the string representation of the model"""
        return pprint.pformat(self.to_dict())

    def __repr__(self):
        """For `print` and `pprint`"""
        return self.to_str()

    def __eq__(self, other):
        """Returns true if both objects are equal"""
        if not isinstance(other, ResponseDataWithCreateUuidString):
            return False

        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        """Returns true if both objects are not equal"""
        return not self == other


class ResponseDataWithCreateUuid(object):
    """NOTE: This class is auto generated by the swagger code generator program

    Do not edit the class manually.
    """

    """
    Attributes:
      swagger_types (dict): The key is attribute name
                            and the value is attribute type.
      attribute_map (dict): The key is attribute name
                            and the value is json key in definition.
    """
    swagger_types = {
        'status': 'bool',
        'message': 'str',
        'error_message': 'str',
        'warning': 'str',
        'data': 'DataWithUuidData'
    }

    attribute_map = {
        'status': 'status',
        'message': 'message',
        'error_message': 'error_message',
        'warning': 'warning',
        'data': 'data'
    }

    def __init__(self, status=None, message=None, error_message=None, warning=None, data=None):  # noqa: E501
        """ResponseDataWithCreateUuid - a model defined in Swagger"""  # noqa: E501

        self._status = None
        self._message = None
        self._error_message = None
        self._warning = None
        self._data = None
        self.discriminator = None

        self.status = status
        if message is not None:
            self.message = message
        if error_message is not None:
            self.error_message = error_message
        if warning is not None:
            self.warning = warning
        self.data = data

    @property
    def status(self):
        """Gets the status of this ResponseDataWithCreateUuid.  # noqa: E501


        :return: The status of this ResponseDataWithCreateUuid.  # noqa: E501
        :rtype: bool
        """
        return self._status

    @status.setter
    def status(self, status):
        """Sets the status of this ResponseDataWithCreateUuid.


        :param status: The status of this ResponseDataWithCreateUuid.  # noqa: E501
        :type: bool
        """
        if status is None:
            raise ValueError("Invalid value for `status`, must not be `None`")  # noqa: E501

        self._status = status

    @property
    def message(self):
        """Gets the message of this ResponseDataWithCreateUuid.  # noqa: E501


        :return: The message of this ResponseDataWithCreateUuid.  # noqa: E501
        :rtype: str
        """
        return self._message

    @message.setter
    def message(self, message):
        """Sets the message of this ResponseDataWithCreateUuid.


        :param message: The message of this ResponseDataWithCreateUuid.  # noqa: E501
        :type: str
        """

        self._message = message

    @property
    def error_message(self):
        """Gets the error_message of this ResponseDataWithCreateUuid.  # noqa: E501


        :return: The error_message of this ResponseDataWithCreateUuid.  # noqa: E501
        :rtype: str
        """
        return self._error_message

    @error_message.setter
    def error_message(self, error_message):
        """Sets the error_message of this ResponseDataWithCreateUuid.


        :param error_message: The error_message of this ResponseDataWithCreateUuid.  # noqa: E501
        :type: str
        """

        self._error_message = error_message

    @property
    def warning(self):
        """Gets the warning of this ResponseDataWithCreateUuid.  # noqa: E501


        :return: The warning of this ResponseDataWithCreateUuid.  # noqa: E501
        :rtype: str
        """
        return self._warning

    @warning.setter
    def warning(self, warning):
        """Sets the warning of this ResponseDataWithCreateUuid.


        :param warning: The warning of this ResponseDataWithCreateUuid.  # noqa: E501
        :type: str
        """

        self._warning = warning

    @property
    def data(self):
        """Gets the data of this ResponseDataWithCreateUuid.  # noqa: E501


        :return: The data of this ResponseDataWithCreateUuid.  # noqa: E501
        :rtype: DataWithUuidData
        """
        return self._data

    @data.setter
    def data(self, data):
        """Sets the data of this ResponseDataWithCreateUuid.


        :param data: The data of this ResponseDataWithCreateUuid.  # noqa: E501
        :type: DataWithUuidData
        """
        if data is None:
            raise ValueError("Invalid value for `data`, must not be `None`")  # noqa: E501

        self._data = data

    def to_dict(self):
        """Returns the model properties as a dict"""
        result = {}

        for attr, _ in self.swagger_types.items():
            value = getattr(self, attr)
            if isinstance(value, list):
                result[attr] = list(map(
                    lambda x: x.to_dict() if hasattr(x, "to_dict") else x,
                    value
                ))
            elif hasattr(value, "to_dict"):
                result[attr] = value.to_dict()
            elif isinstance(value, dict):
                result[attr] = dict(map(
                    lambda item: (item[0], item[1].to_dict())
                    if hasattr(item[1], "to_dict") else item,
                    value.items()
                ))
            else:
                result[attr] = value
        if issubclass(ResponseDataWithCreateUuid, dict):
            for key, value in self.items():
                result[key] = value

        return result

    def to_str(self):
        """Returns the string representation of the model"""
        return pprint.pformat(self.to_dict())

    def __repr__(self):
        """For `print` and `pprint`"""
        return self.to_str()

    def __eq__(self, other):
        """Returns true if both objects are equal"""
        if not isinstance(other, ResponseDataWithCreateUuid):
            return False

        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        """Returns true if both objects are not equal"""
        return not self == other


class ResponseDataWithHostInfo(object):
    """NOTE: This class is auto generated by the swagger code generator program

    Do not edit the class manually.
    """

    """
    Attributes:
      swagger_types (dict): The key is attribute name
                            and the value is attribute type.
      attribute_map (dict): The key is attribute name
                            and the value is json key in definition.
    """
    swagger_types = {
        'status': 'bool',
        'message': 'str',
        'error_message': 'str',
        'warning': 'str',
        'data': 'HostInfo'
    }

    attribute_map = {
        'status': 'status',
        'message': 'message',
        'error_message': 'error_message',
        'warning': 'warning',
        'data': 'data'
    }

    def __init__(self, status=None, message=None, error_message=None, warning=None, data=None):  # noqa: E501
        """ResponseDataWithHostInfo - a model defined in Swagger"""  # noqa: E501

        self._status = None
        self._message = None
        self._error_message = None
        self._warning = None
        self._data = None
        self.discriminator = None

        self.status = status
        if message is not None:
            self.message = message
        if error_message is not None:
            self.error_message = error_message
        if warning is not None:
            self.warning = warning
        if data is not None:
            self.data = data

    @property
    def status(self):
        """Gets the status of this ResponseDataWithHostInfo.  # noqa: E501


        :return: The status of this ResponseDataWithHostInfo.  # noqa: E501
        :rtype: bool
        """
        return self._status

    @status.setter
    def status(self, status):
        """Sets the status of this ResponseDataWithHostInfo.


        :param status: The status of this ResponseDataWithHostInfo.  # noqa: E501
        :type: bool
        """
        if status is None:
            raise ValueError("Invalid value for `status`, must not be `None`")  # noqa: E501

        self._status = status

    @property
    def message(self):
        """Gets the message of this ResponseDataWithHostInfo.  # noqa: E501


        :return: The message of this ResponseDataWithHostInfo.  # noqa: E501
        :rtype: str
        """
        return self._message

    @message.setter
    def message(self, message):
        """Sets the message of this ResponseDataWithHostInfo.


        :param message: The message of this ResponseDataWithHostInfo.  # noqa: E501
        :type: str
        """

        self._message = message

    @property
    def error_message(self):
        """Gets the error_message of this ResponseDataWithHostInfo.  # noqa: E501


        :return: The error_message of this ResponseDataWithHostInfo.  # noqa: E501
        :rtype: str
        """
        return self._error_message

    @error_message.setter
    def error_message(self, error_message):
        """Sets the error_message of this ResponseDataWithHostInfo.


        :param error_message: The error_message of this ResponseDataWithHostInfo.  # noqa: E501
        :type: str
        """

        self._error_message = error_message

    @property
    def warning(self):
        """Gets the warning of this ResponseDataWithHostInfo.  # noqa: E501


        :return: The warning of this ResponseDataWithHostInfo.  # noqa: E501
        :rtype: str
        """
        return self._warning

    @warning.setter
    def warning(self, warning):
        """Sets the warning of this ResponseDataWithHostInfo.


        :param warning: The warning of this ResponseDataWithHostInfo.  # noqa: E501
        :type: str
        """

        self._warning = warning

    @property
    def data(self):
        """Gets the data of this ResponseDataWithHostInfo.  # noqa: E501


        :return: The data of this ResponseDataWithHostInfo.  # noqa: E501
        :rtype: HostInfo
        """
        return self._data

    @data.setter
    def data(self, data):
        """Sets the data of this ResponseDataWithHostInfo.


        :param data: The data of this ResponseDataWithHostInfo.  # noqa: E501
        :type: HostInfo
        """

        self._data = data

    def to_dict(self):
        """Returns the model properties as a dict"""
        result = {}

        for attr, _ in self.swagger_types.items():
            value = getattr(self, attr)
            if isinstance(value, list):
                result[attr] = list(map(
                    lambda x: x.to_dict() if hasattr(x, "to_dict") else x,
                    value
                ))
            elif hasattr(value, "to_dict"):
                result[attr] = value.to_dict()
            elif isinstance(value, dict):
                result[attr] = dict(map(
                    lambda item: (item[0], item[1].to_dict())
                    if hasattr(item[1], "to_dict") else item,
                    value.items()
                ))
            else:
                result[attr] = value
        if issubclass(ResponseDataWithHostInfo, dict):
            for key, value in self.items():
                result[key] = value

        return result

    def to_str(self):
        """Returns the string representation of the model"""
        return pprint.pformat(self.to_dict())

    def __repr__(self):
        """For `print` and `pprint`"""
        return self.to_str()

    def __eq__(self, other):
        """Returns true if both objects are equal"""
        if not isinstance(other, ResponseDataWithHostInfo):
            return False

        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        """Returns true if both objects are not equal"""
        return not self == other


class ResponseDataWithListOfHostUuids(object):
    """NOTE: This class is auto generated by the swagger code generator program

    Do not edit the class manually.
    """

    """
    Attributes:
      swagger_types (dict): The key is attribute name
                            and the value is attribute type.
      attribute_map (dict): The key is attribute name
                            and the value is json key in definition.
    """
    swagger_types = {
        'status': 'bool',
        'message': 'str',
        'error_message': 'str',
        'warning': 'str',
        'data': 'DataWithListOfHostUuidsData'
    }

    attribute_map = {
        'status': 'status',
        'message': 'message',
        'error_message': 'error_message',
        'warning': 'warning',
        'data': 'data'
    }

    def __init__(self, status=None, message=None, error_message=None, warning=None, data=None):  # noqa: E501
        """ResponseDataWithListOfHostUuids - a model defined in Swagger"""  # noqa: E501

        self._status = None
        self._message = None
        self._error_message = None
        self._warning = None
        self._data = None
        self.discriminator = None

        self.status = status
        if message is not None:
            self.message = message
        if error_message is not None:
            self.error_message = error_message
        if warning is not None:
            self.warning = warning
        if data is not None:
            self.data = data

    @property
    def status(self):
        """Gets the status of this ResponseDataWithListOfHostUuids.  # noqa: E501


        :return: The status of this ResponseDataWithListOfHostUuids.  # noqa: E501
        :rtype: bool
        """
        return self._status

    @status.setter
    def status(self, status):
        """Sets the status of this ResponseDataWithListOfHostUuids.


        :param status: The status of this ResponseDataWithListOfHostUuids.  # noqa: E501
        :type: bool
        """
        if status is None:
            raise ValueError("Invalid value for `status`, must not be `None`")  # noqa: E501

        self._status = status

    @property
    def message(self):
        """Gets the message of this ResponseDataWithListOfHostUuids.  # noqa: E501


        :return: The message of this ResponseDataWithListOfHostUuids.  # noqa: E501
        :rtype: str
        """
        return self._message

    @message.setter
    def message(self, message):
        """Sets the message of this ResponseDataWithListOfHostUuids.


        :param message: The message of this ResponseDataWithListOfHostUuids.  # noqa: E501
        :type: str
        """

        self._message = message

    @property
    def error_message(self):
        """Gets the error_message of this ResponseDataWithListOfHostUuids.  # noqa: E501


        :return: The error_message of this ResponseDataWithListOfHostUuids.  # noqa: E501
        :rtype: str
        """
        return self._error_message

    @error_message.setter
    def error_message(self, error_message):
        """Sets the error_message of this ResponseDataWithListOfHostUuids.


        :param error_message: The error_message of this ResponseDataWithListOfHostUuids.  # noqa: E501
        :type: str
        """

        self._error_message = error_message

    @property
    def warning(self):
        """Gets the warning of this ResponseDataWithListOfHostUuids.  # noqa: E501


        :return: The warning of this ResponseDataWithListOfHostUuids.  # noqa: E501
        :rtype: str
        """
        return self._warning

    @warning.setter
    def warning(self, warning):
        """Sets the warning of this ResponseDataWithListOfHostUuids.


        :param warning: The warning of this ResponseDataWithListOfHostUuids.  # noqa: E501
        :type: str
        """

        self._warning = warning

    @property
    def data(self):
        """Gets the data of this ResponseDataWithListOfHostUuids.  # noqa: E501


        :return: The data of this ResponseDataWithListOfHostUuids.  # noqa: E501
        :rtype: DataWithListOfHostUuidsData
        """
        return self._data

    @data.setter
    def data(self, data):
        """Sets the data of this ResponseDataWithListOfHostUuids.


        :param data: The data of this ResponseDataWithListOfHostUuids.  # noqa: E501
        :type: DataWithListOfHostUuidsData
        """

        self._data = data

    def to_dict(self):
        """Returns the model properties as a dict"""
        result = {}

        for attr, _ in self.swagger_types.items():
            value = getattr(self, attr)
            if isinstance(value, list):
                result[attr] = list(map(
                    lambda x: x.to_dict() if hasattr(x, "to_dict") else x,
                    value
                ))
            elif hasattr(value, "to_dict"):
                result[attr] = value.to_dict()
            elif isinstance(value, dict):
                result[attr] = dict(map(
                    lambda item: (item[0], item[1].to_dict())
                    if hasattr(item[1], "to_dict") else item,
                    value.items()
                ))
            else:
                result[attr] = value
        if issubclass(ResponseDataWithListOfHostUuids, dict):
            for key, value in self.items():
                result[key] = value

        return result

    def to_str(self):
        """Returns the string representation of the model"""
        return pprint.pformat(self.to_dict())

    def __repr__(self):
        """For `print` and `pprint`"""
        return self.to_str()

    def __eq__(self, other):
        """Returns true if both objects are equal"""
        if not isinstance(other, ResponseDataWithListOfHostUuids):
            return False

        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        """Returns true if both objects are not equal"""
        return not self == other


class ResponseDataWithListOfHosts(object):
    """NOTE: This class is auto generated by the swagger code generator program

    Do not edit the class manually.
    """

    """
    Attributes:
      swagger_types (dict): The key is attribute name
                            and the value is attribute type.
      attribute_map (dict): The key is attribute name
                            and the value is json key in definition.
    """
    swagger_types = {
        'status': 'bool',
        'message': 'str',
        'error_message': 'str',
        'warning': 'str',
        'data': 'list[HostInfo]'
    }

    attribute_map = {
        'status': 'status',
        'message': 'message',
        'error_message': 'error_message',
        'warning': 'warning',
        'data': 'data'
    }

    def __init__(self, status=None, message=None, error_message=None, warning=None, data=None):  # noqa: E501
        """ResponseDataWithListOfHosts - a model defined in Swagger"""  # noqa: E501

        self._status = None
        self._message = None
        self._error_message = None
        self._warning = None
        self._data = None
        self.discriminator = None

        self.status = status
        if message is not None:
            self.message = message
        if error_message is not None:
            self.error_message = error_message
        if warning is not None:
            self.warning = warning
        self.data = data

    @property
    def status(self):
        """Gets the status of this ResponseDataWithListOfHosts.  # noqa: E501


        :return: The status of this ResponseDataWithListOfHosts.  # noqa: E501
        :rtype: bool
        """
        return self._status

    @status.setter
    def status(self, status):
        """Sets the status of this ResponseDataWithListOfHosts.


        :param status: The status of this ResponseDataWithListOfHosts.  # noqa: E501
        :type: bool
        """
        if status is None:
            raise ValueError("Invalid value for `status`, must not be `None`")  # noqa: E501

        self._status = status

    @property
    def message(self):
        """Gets the message of this ResponseDataWithListOfHosts.  # noqa: E501


        :return: The message of this ResponseDataWithListOfHosts.  # noqa: E501
        :rtype: str
        """
        return self._message

    @message.setter
    def message(self, message):
        """Sets the message of this ResponseDataWithListOfHosts.


        :param message: The message of this ResponseDataWithListOfHosts.  # noqa: E501
        :type: str
        """

        self._message = message

    @property
    def error_message(self):
        """Gets the error_message of this ResponseDataWithListOfHosts.  # noqa: E501


        :return: The error_message of this ResponseDataWithListOfHosts.  # noqa: E501
        :rtype: str
        """
        return self._error_message

    @error_message.setter
    def error_message(self, error_message):
        """Sets the error_message of this ResponseDataWithListOfHosts.


        :param error_message: The error_message of this ResponseDataWithListOfHosts.  # noqa: E501
        :type: str
        """

        self._error_message = error_message

    @property
    def warning(self):
        """Gets the warning of this ResponseDataWithListOfHosts.  # noqa: E501


        :return: The warning of this ResponseDataWithListOfHosts.  # noqa: E501
        :rtype: str
        """
        return self._warning

    @warning.setter
    def warning(self, warning):
        """Sets the warning of this ResponseDataWithListOfHosts.


        :param warning: The warning of this ResponseDataWithListOfHosts.  # noqa: E501
        :type: str
        """

        self._warning = warning

    @property
    def data(self):
        """Gets the data of this ResponseDataWithListOfHosts.  # noqa: E501


        :return: The data of this ResponseDataWithListOfHosts.  # noqa: E501
        :rtype: list[HostInfo]
        """
        return self._data

    @data.setter
    def data(self, data):
        """Sets the data of this ResponseDataWithListOfHosts.


        :param data: The data of this ResponseDataWithListOfHosts.  # noqa: E501
        :type: list[HostInfo]
        """
        if data is None:
            raise ValueError("Invalid value for `data`, must not be `None`")  # noqa: E501

        self._data = data

    def to_dict(self):
        """Returns the model properties as a dict"""
        result = {}

        for attr, _ in self.swagger_types.items():
            value = getattr(self, attr)
            if isinstance(value, list):
                result[attr] = list(map(
                    lambda x: x.to_dict() if hasattr(x, "to_dict") else x,
                    value
                ))
            elif hasattr(value, "to_dict"):
                result[attr] = value.to_dict()
            elif isinstance(value, dict):
                result[attr] = dict(map(
                    lambda item: (item[0], item[1].to_dict())
                    if hasattr(item[1], "to_dict") else item,
                    value.items()
                ))
            else:
                result[attr] = value
        if issubclass(ResponseDataWithListOfHosts, dict):
            for key, value in self.items():
                result[key] = value

        return result

    def to_str(self):
        """Returns the string representation of the model"""
        return pprint.pformat(self.to_dict())

    def __repr__(self):
        """For `print` and `pprint`"""
        return self.to_str()

    def __eq__(self, other):
        """Returns true if both objects are equal"""
        if not isinstance(other, ResponseDataWithListOfHosts):
            return False

        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        """Returns true if both objects are not equal"""
        return not self == other


class ResponseDataWithSinglePort(object):
    """NOTE: This class is auto generated by the swagger code generator program

    Do not edit the class manually.
    """

    """
    Attributes:
      swagger_types (dict): The key is attribute name
                            and the value is attribute type.
      attribute_map (dict): The key is attribute name
                            and the value is json key in definition.
    """
    swagger_types = {
        'status': 'bool',
        'message': 'str',
        'error_message': 'str',
        'warning': 'str',
        'data': 'Port'
    }

    attribute_map = {
        'status': 'status',
        'message': 'message',
        'error_message': 'error_message',
        'warning': 'warning',
        'data': 'data'
    }

    def __init__(self, status=None, message=None, error_message=None, warning=None, data=None):  # noqa: E501
        """ResponseDataWithSinglePort - a model defined in Swagger"""  # noqa: E501

        self._status = None
        self._message = None
        self._error_message = None
        self._warning = None
        self._data = None
        self.discriminator = None

        self.status = status
        if message is not None:
            self.message = message
        if error_message is not None:
            self.error_message = error_message
        if warning is not None:
            self.warning = warning
        self.data = data

    @property
    def status(self):
        """Gets the status of this ResponseDataWithSinglePort.  # noqa: E501


        :return: The status of this ResponseDataWithSinglePort.  # noqa: E501
        :rtype: bool
        """
        return self._status

    @status.setter
    def status(self, status):
        """Sets the status of this ResponseDataWithSinglePort.


        :param status: The status of this ResponseDataWithSinglePort.  # noqa: E501
        :type: bool
        """
        if status is None:
            raise ValueError("Invalid value for `status`, must not be `None`")  # noqa: E501

        self._status = status

    @property
    def message(self):
        """Gets the message of this ResponseDataWithSinglePort.  # noqa: E501


        :return: The message of this ResponseDataWithSinglePort.  # noqa: E501
        :rtype: str
        """
        return self._message

    @message.setter
    def message(self, message):
        """Sets the message of this ResponseDataWithSinglePort.


        :param message: The message of this ResponseDataWithSinglePort.  # noqa: E501
        :type: str
        """

        self._message = message

    @property
    def error_message(self):
        """Gets the error_message of this ResponseDataWithSinglePort.  # noqa: E501


        :return: The error_message of this ResponseDataWithSinglePort.  # noqa: E501
        :rtype: str
        """
        return self._error_message

    @error_message.setter
    def error_message(self, error_message):
        """Sets the error_message of this ResponseDataWithSinglePort.


        :param error_message: The error_message of this ResponseDataWithSinglePort.  # noqa: E501
        :type: str
        """

        self._error_message = error_message

    @property
    def warning(self):
        """Gets the warning of this ResponseDataWithSinglePort.  # noqa: E501


        :return: The warning of this ResponseDataWithSinglePort.  # noqa: E501
        :rtype: str
        """
        return self._warning

    @warning.setter
    def warning(self, warning):
        """Sets the warning of this ResponseDataWithSinglePort.


        :param warning: The warning of this ResponseDataWithSinglePort.  # noqa: E501
        :type: str
        """

        self._warning = warning

    @property
    def data(self):
        """Gets the data of this ResponseDataWithSinglePort.  # noqa: E501


        :return: The data of this ResponseDataWithSinglePort.  # noqa: E501
        :rtype: Port
        """
        return self._data

    @data.setter
    def data(self, data):
        """Sets the data of this ResponseDataWithSinglePort.


        :param data: The data of this ResponseDataWithSinglePort.  # noqa: E501
        :type: Port
        """
        if data is None:
            raise ValueError("Invalid value for `data`, must not be `None`")  # noqa: E501

        self._data = data

    def to_dict(self):
        """Returns the model properties as a dict"""
        result = {}

        for attr, _ in self.swagger_types.items():
            value = getattr(self, attr)
            if isinstance(value, list):
                result[attr] = list(map(
                    lambda x: x.to_dict() if hasattr(x, "to_dict") else x,
                    value
                ))
            elif hasattr(value, "to_dict"):
                result[attr] = value.to_dict()
            elif isinstance(value, dict):
                result[attr] = dict(map(
                    lambda item: (item[0], item[1].to_dict())
                    if hasattr(item[1], "to_dict") else item,
                    value.items()
                ))
            else:
                result[attr] = value
        if issubclass(ResponseDataWithSinglePort, dict):
            for key, value in self.items():
                result[key] = value

        return result

    def to_str(self):
        """Returns the string representation of the model"""
        return pprint.pformat(self.to_dict())

    def __repr__(self):
        """For `print` and `pprint`"""
        return self.to_str()

    def __eq__(self, other):
        """Returns true if both objects are equal"""
        if not isinstance(other, ResponseDataWithSinglePort):
            return False

        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        """Returns true if both objects are not equal"""
        return not self == other


class ResponseDataWithSingleVolume(object):
    """NOTE: This class is auto generated by the swagger code generator program

    Do not edit the class manually.
    """

    """
    Attributes:
      swagger_types (dict): The key is attribute name
                            and the value is attribute type.
      attribute_map (dict): The key is attribute name
                            and the value is json key in definition.
    """
    swagger_types = {
        'status': 'bool',
        'message': 'str',
        'error_message': 'str',
        'warning': 'str',
        'data': 'Volume'
    }

    attribute_map = {
        'status': 'status',
        'message': 'message',
        'error_message': 'error_message',
        'warning': 'warning',
        'data': 'data'
    }

    def __init__(self, status=None, message=None, error_message=None, warning=None, data=None):  # noqa: E501
        """ResponseDataWithSingleVolume - a model defined in Swagger"""  # noqa: E501

        self._status = None
        self._message = None
        self._error_message = None
        self._warning = None
        self._data = None
        self.discriminator = None

        self.status = status
        if message is not None:
            self.message = message
        if error_message is not None:
            self.error_message = error_message
        if warning is not None:
            self.warning = warning
        self.data = data

    @property
    def status(self):
        """Gets the status of this ResponseDataWithSingleVolume.  # noqa: E501


        :return: The status of this ResponseDataWithSingleVolume.  # noqa: E501
        :rtype: bool
        """
        return self._status

    @status.setter
    def status(self, status):
        """Sets the status of this ResponseDataWithSingleVolume.


        :param status: The status of this ResponseDataWithSingleVolume.  # noqa: E501
        :type: bool
        """
        if status is None:
            raise ValueError("Invalid value for `status`, must not be `None`")  # noqa: E501

        self._status = status

    @property
    def message(self):
        """Gets the message of this ResponseDataWithSingleVolume.  # noqa: E501


        :return: The message of this ResponseDataWithSingleVolume.  # noqa: E501
        :rtype: str
        """
        return self._message

    @message.setter
    def message(self, message):
        """Sets the message of this ResponseDataWithSingleVolume.


        :param message: The message of this ResponseDataWithSingleVolume.  # noqa: E501
        :type: str
        """

        self._message = message

    @property
    def error_message(self):
        """Gets the error_message of this ResponseDataWithSingleVolume.  # noqa: E501


        :return: The error_message of this ResponseDataWithSingleVolume.  # noqa: E501
        :rtype: str
        """
        return self._error_message

    @error_message.setter
    def error_message(self, error_message):
        """Sets the error_message of this ResponseDataWithSingleVolume.


        :param error_message: The error_message of this ResponseDataWithSingleVolume.  # noqa: E501
        :type: str
        """

        self._error_message = error_message

    @property
    def warning(self):
        """Gets the warning of this ResponseDataWithSingleVolume.  # noqa: E501


        :return: The warning of this ResponseDataWithSingleVolume.  # noqa: E501
        :rtype: str
        """
        return self._warning

    @warning.setter
    def warning(self, warning):
        """Sets the warning of this ResponseDataWithSingleVolume.


        :param warning: The warning of this ResponseDataWithSingleVolume.  # noqa: E501
        :type: str
        """

        self._warning = warning

    @property
    def data(self):
        """Gets the data of this ResponseDataWithSingleVolume.  # noqa: E501


        :return: The data of this ResponseDataWithSingleVolume.  # noqa: E501
        :rtype: Volume
        """
        return self._data

    @data.setter
    def data(self, data):
        """Sets the data of this ResponseDataWithSingleVolume.


        :param data: The data of this ResponseDataWithSingleVolume.  # noqa: E501
        :type: Volume
        """
        if data is None:
            raise ValueError("Invalid value for `data`, must not be `None`")  # noqa: E501

        self._data = data

    def to_dict(self):
        """Returns the model properties as a dict"""
        result = {}

        for attr, _ in self.swagger_types.items():
            value = getattr(self, attr)
            if isinstance(value, list):
                result[attr] = list(map(
                    lambda x: x.to_dict() if hasattr(x, "to_dict") else x,
                    value
                ))
            elif hasattr(value, "to_dict"):
                result[attr] = value.to_dict()
            elif isinstance(value, dict):
                result[attr] = dict(map(
                    lambda item: (item[0], item[1].to_dict())
                    if hasattr(item[1], "to_dict") else item,
                    value.items()
                ))
            else:
                result[attr] = value
        if issubclass(ResponseDataWithSingleVolume, dict):
            for key, value in self.items():
                result[key] = value

        return result

    def to_str(self):
        """Returns the string representation of the model"""
        return pprint.pformat(self.to_dict())

    def __repr__(self):
        """For `print` and `pprint`"""
        return self.to_str()

    def __eq__(self, other):
        """Returns true if both objects are equal"""
        if not isinstance(other, ResponseDataWithSingleVolume):
            return False

        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        """Returns true if both objects are not equal"""
        return not self == other


class ResponseDpuDriveHierarchy(object):
    """NOTE: This class is auto generated by the swagger code generator program

    Do not edit the class manually.
    """

    """
    Attributes:
      swagger_types (dict): The key is attribute name
                            and the value is attribute type.
      attribute_map (dict): The key is attribute name
                            and the value is json key in definition.
    """
    swagger_types = {
        'status': 'bool',
        'message': 'str',
        'error_message': 'str',
        'warning': 'str',
        'data': 'dict(str, NodeDpu)'
    }

    attribute_map = {
        'status': 'status',
        'message': 'message',
        'error_message': 'error_message',
        'warning': 'warning',
        'data': 'data'
    }

    def __init__(self, status=None, message=None, error_message=None, warning=None, data=None):  # noqa: E501
        """ResponseDpuDriveHierarchy - a model defined in Swagger"""  # noqa: E501

        self._status = None
        self._message = None
        self._error_message = None
        self._warning = None
        self._data = None
        self.discriminator = None

        self.status = status
        if message is not None:
            self.message = message
        if error_message is not None:
            self.error_message = error_message
        if warning is not None:
            self.warning = warning
        self.data = data

    @property
    def status(self):
        """Gets the status of this ResponseDpuDriveHierarchy.  # noqa: E501


        :return: The status of this ResponseDpuDriveHierarchy.  # noqa: E501
        :rtype: bool
        """
        return self._status

    @status.setter
    def status(self, status):
        """Sets the status of this ResponseDpuDriveHierarchy.


        :param status: The status of this ResponseDpuDriveHierarchy.  # noqa: E501
        :type: bool
        """
        if status is None:
            raise ValueError("Invalid value for `status`, must not be `None`")  # noqa: E501

        self._status = status

    @property
    def message(self):
        """Gets the message of this ResponseDpuDriveHierarchy.  # noqa: E501


        :return: The message of this ResponseDpuDriveHierarchy.  # noqa: E501
        :rtype: str
        """
        return self._message

    @message.setter
    def message(self, message):
        """Sets the message of this ResponseDpuDriveHierarchy.


        :param message: The message of this ResponseDpuDriveHierarchy.  # noqa: E501
        :type: str
        """

        self._message = message

    @property
    def error_message(self):
        """Gets the error_message of this ResponseDpuDriveHierarchy.  # noqa: E501


        :return: The error_message of this ResponseDpuDriveHierarchy.  # noqa: E501
        :rtype: str
        """
        return self._error_message

    @error_message.setter
    def error_message(self, error_message):
        """Sets the error_message of this ResponseDpuDriveHierarchy.


        :param error_message: The error_message of this ResponseDpuDriveHierarchy.  # noqa: E501
        :type: str
        """

        self._error_message = error_message

    @property
    def warning(self):
        """Gets the warning of this ResponseDpuDriveHierarchy.  # noqa: E501


        :return: The warning of this ResponseDpuDriveHierarchy.  # noqa: E501
        :rtype: str
        """
        return self._warning

    @warning.setter
    def warning(self, warning):
        """Sets the warning of this ResponseDpuDriveHierarchy.


        :param warning: The warning of this ResponseDpuDriveHierarchy.  # noqa: E501
        :type: str
        """

        self._warning = warning

    @property
    def data(self):
        """Gets the data of this ResponseDpuDriveHierarchy.  # noqa: E501


        :return: The data of this ResponseDpuDriveHierarchy.  # noqa: E501
        :rtype: dict(str, NodeDpu)
        """
        return self._data

    @data.setter
    def data(self, data):
        """Sets the data of this ResponseDpuDriveHierarchy.


        :param data: The data of this ResponseDpuDriveHierarchy.  # noqa: E501
        :type: dict(str, NodeDpu)
        """
        if data is None:
            raise ValueError("Invalid value for `data`, must not be `None`")  # noqa: E501

        self._data = data

    def to_dict(self):
        """Returns the model properties as a dict"""
        result = {}

        for attr, _ in self.swagger_types.items():
            value = getattr(self, attr)
            if isinstance(value, list):
                result[attr] = list(map(
                    lambda x: x.to_dict() if hasattr(x, "to_dict") else x,
                    value
                ))
            elif hasattr(value, "to_dict"):
                result[attr] = value.to_dict()
            elif isinstance(value, dict):
                result[attr] = dict(map(
                    lambda item: (item[0], item[1].to_dict())
                    if hasattr(item[1], "to_dict") else item,
                    value.items()
                ))
            else:
                result[attr] = value
        if issubclass(ResponseDpuDriveHierarchy, dict):
            for key, value in self.items():
                result[key] = value

        return result

    def to_str(self):
        """Returns the string representation of the model"""
        return pprint.pformat(self.to_dict())

    def __repr__(self):
        """For `print` and `pprint`"""
        return self.to_str()

    def __eq__(self, other):
        """Returns true if both objects are equal"""
        if not isinstance(other, ResponseDpuDriveHierarchy):
            return False

        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        """Returns true if both objects are not equal"""
        return not self == other


class Smart(object):
    """NOTE: This class is auto generated by the swagger code generator program

    Do not edit the class manually.
    """

    """
    Attributes:
      swagger_types (dict): The key is attribute name
                            and the value is attribute type.
      attribute_map (dict): The key is attribute name
                            and the value is json key in definition.
    """
    swagger_types = {
        'controller_busy_time': 'str',
        'host_read_commands': 'str',
        'available_spare': 'str',
        'critical_composite_temperature_time': 'str',
        'host_write_commands': 'str',
        'media_and_data_integrity_errors': 'str',
        'data_units_written': 'str',
        'warning_composite_temperature_time': 'str',
        'endurance_group_critical_warning_summary': 'str',
        'critical_warning': 'str',
        'power_cycles': 'str',
        'number_of_error_information_log_entries': 'str',
        'percentage_used': 'str',
        'power_on_hours': 'str',
        'composite_temperature': 'str',
        'data_units_read': 'str',
        'unsafe_shutdowns': 'str'
    }

    attribute_map = {
        'controller_busy_time': 'controller_busy_time',
        'host_read_commands': 'host_read_commands',
        'available_spare': 'available_spare',
        'critical_composite_temperature_time': 'critical_composite_temperature_time',  # noqa: E501
        'host_write_commands': 'host_write_commands',
        'media_and_data_integrity_errors': 'media_and_data_integrity_errors',
        'data_units_written': 'data_units_written',
        'warning_composite_temperature_time': 'warning_composite_temperature_time',  # noqa: E501
        'endurance_group_critical_warning_summary': 'endurance_group_critical_warning_summary',  # noqa: E501
        'critical_warning': 'critical_warning',
        'power_cycles': 'power_cycles',
        'number_of_error_information_log_entries': 'number_of_error_information_log_entries',  # noqa: E501
        'percentage_used': 'percentage_used',
        'power_on_hours': 'power_on_hours',
        'composite_temperature': 'composite_temperature',
        'data_units_read': 'data_units_read',
        'unsafe_shutdowns': 'unsafe_shutdowns'
    }

    def __init__(self, controller_busy_time=None, host_read_commands=None, available_spare=None, critical_composite_temperature_time=None, host_write_commands=None, media_and_data_integrity_errors=None, data_units_written=None, warning_composite_temperature_time=None, endurance_group_critical_warning_summary=None, critical_warning=None, power_cycles=None, number_of_error_information_log_entries=None, percentage_used=None, power_on_hours=None, composite_temperature=None, data_units_read=None, unsafe_shutdowns=None):  # noqa: E501
        """Smart - a model defined in Swagger"""  # noqa: E501

        self._controller_busy_time = None
        self._host_read_commands = None
        self._available_spare = None
        self._critical_composite_temperature_time = None
        self._host_write_commands = None
        self._media_and_data_integrity_errors = None
        self._data_units_written = None
        self._warning_composite_temperature_time = None
        self._endurance_group_critical_warning_summary = None
        self._critical_warning = None
        self._power_cycles = None
        self._number_of_error_information_log_entries = None
        self._percentage_used = None
        self._power_on_hours = None
        self._composite_temperature = None
        self._data_units_read = None
        self._unsafe_shutdowns = None
        self.discriminator = None

        if controller_busy_time is not None:
            self.controller_busy_time = controller_busy_time
        if host_read_commands is not None:
            self.host_read_commands = host_read_commands
        if available_spare is not None:
            self.available_spare = available_spare
        if critical_composite_temperature_time is not None:
            self.critical_composite_temperature_time = critical_composite_temperature_time  # noqa: E501
        if host_write_commands is not None:
            self.host_write_commands = host_write_commands
        if media_and_data_integrity_errors is not None:
            self.media_and_data_integrity_errors = media_and_data_integrity_errors  # noqa: E501
        if data_units_written is not None:
            self.data_units_written = data_units_written
        if warning_composite_temperature_time is not None:
            self.warning_composite_temperature_time = warning_composite_temperature_time  # noqa: E501
        if endurance_group_critical_warning_summary is not None:
            self.endurance_group_critical_warning_summary = endurance_group_critical_warning_summary  # noqa: E501
        if critical_warning is not None:
            self.critical_warning = critical_warning
        if power_cycles is not None:
            self.power_cycles = power_cycles
        if number_of_error_information_log_entries is not None:
            self.number_of_error_information_log_entries = number_of_error_information_log_entries  # noqa: E501
        if percentage_used is not None:
            self.percentage_used = percentage_used
        if power_on_hours is not None:
            self.power_on_hours = power_on_hours
        if composite_temperature is not None:
            self.composite_temperature = composite_temperature
        if data_units_read is not None:
            self.data_units_read = data_units_read
        if unsafe_shutdowns is not None:
            self.unsafe_shutdowns = unsafe_shutdowns

    @property
    def controller_busy_time(self):
        """Gets the controller_busy_time of this Smart.  # noqa: E501


        :return: The controller_busy_time of this Smart.  # noqa: E501
        :rtype: str
        """
        return self._controller_busy_time

    @controller_busy_time.setter
    def controller_busy_time(self, controller_busy_time):
        """Sets the controller_busy_time of this Smart.


        :param controller_busy_time: The controller_busy_time of this Smart.  # noqa: E501
        :type: str
        """

        self._controller_busy_time = controller_busy_time

    @property
    def host_read_commands(self):
        """Gets the host_read_commands of this Smart.  # noqa: E501


        :return: The host_read_commands of this Smart.  # noqa: E501
        :rtype: str
        """
        return self._host_read_commands

    @host_read_commands.setter
    def host_read_commands(self, host_read_commands):
        """Sets the host_read_commands of this Smart.


        :param host_read_commands: The host_read_commands of this Smart.  # noqa: E501
        :type: str
        """

        self._host_read_commands = host_read_commands

    @property
    def available_spare(self):
        """Gets the available_spare of this Smart.  # noqa: E501


        :return: The available_spare of this Smart.  # noqa: E501
        :rtype: str
        """
        return self._available_spare

    @available_spare.setter
    def available_spare(self, available_spare):
        """Sets the available_spare of this Smart.


        :param available_spare: The available_spare of this Smart.  # noqa: E501
        :type: str
        """

        self._available_spare = available_spare

    @property
    def critical_composite_temperature_time(self):
        """Gets the critical_composite_temperature_time of this Smart.  # noqa: E501


        :return: The critical_composite_temperature_time of this Smart.  # noqa: E501
        :rtype: str
        """
        return self._critical_composite_temperature_time

    @critical_composite_temperature_time.setter
    def critical_composite_temperature_time(self, critical_composite_temperature_time):  # noqa: E501
        """Sets the critical_composite_temperature_time of this Smart.


        :param critical_composite_temperature_time: The critical_composite_temperature_time of this Smart.  # noqa: E501
        :type: str
        """

        self._critical_composite_temperature_time = critical_composite_temperature_time  # noqa: E501

    @property
    def host_write_commands(self):
        """Gets the host_write_commands of this Smart.  # noqa: E501


        :return: The host_write_commands of this Smart.  # noqa: E501
        :rtype: str
        """
        return self._host_write_commands

    @host_write_commands.setter
    def host_write_commands(self, host_write_commands):
        """Sets the host_write_commands of this Smart.


        :param host_write_commands: The host_write_commands of this Smart.  # noqa: E501
        :type: str
        """

        self._host_write_commands = host_write_commands

    @property
    def media_and_data_integrity_errors(self):
        """Gets the media_and_data_integrity_errors of this Smart.  # noqa: E501


        :return: The media_and_data_integrity_errors of this Smart.  # noqa: E501
        :rtype: str
        """
        return self._media_and_data_integrity_errors

    @media_and_data_integrity_errors.setter
    def media_and_data_integrity_errors(self, media_and_data_integrity_errors):
        """Sets the media_and_data_integrity_errors of this Smart.


        :param media_and_data_integrity_errors: The media_and_data_integrity_errors of this Smart.  # noqa: E501
        :type: str
        """

        self._media_and_data_integrity_errors = media_and_data_integrity_errors

    @property
    def data_units_written(self):
        """Gets the data_units_written of this Smart.  # noqa: E501


        :return: The data_units_written of this Smart.  # noqa: E501
        :rtype: str
        """
        return self._data_units_written

    @data_units_written.setter
    def data_units_written(self, data_units_written):
        """Sets the data_units_written of this Smart.


        :param data_units_written: The data_units_written of this Smart.  # noqa: E501
        :type: str
        """

        self._data_units_written = data_units_written

    @property
    def warning_composite_temperature_time(self):
        """Gets the warning_composite_temperature_time of this Smart.  # noqa: E501


        :return: The warning_composite_temperature_time of this Smart.  # noqa: E501
        :rtype: str
        """
        return self._warning_composite_temperature_time

    @warning_composite_temperature_time.setter
    def warning_composite_temperature_time(self, warning_composite_temperature_time):  # noqa: E501
        """Sets the warning_composite_temperature_time of this Smart.


        :param warning_composite_temperature_time: The warning_composite_temperature_time of this Smart.  # noqa: E501
        :type: str
        """

        self._warning_composite_temperature_time = warning_composite_temperature_time  # noqa: E501

    @property
    def endurance_group_critical_warning_summary(self):
        """Gets the endurance_group_critical_warning_summary of this Smart.  # noqa: E501


        :return: The endurance_group_critical_warning_summary of this Smart.  # noqa: E501
        :rtype: str
        """
        return self._endurance_group_critical_warning_summary

    @endurance_group_critical_warning_summary.setter
    def endurance_group_critical_warning_summary(self, endurance_group_critical_warning_summary):  # noqa: E501
        """Sets the endurance_group_critical_warning_summary of this Smart.


        :param endurance_group_critical_warning_summary: The endurance_group_critical_warning_summary of this Smart.  # noqa: E501
        :type: str
        """

        self._endurance_group_critical_warning_summary = endurance_group_critical_warning_summary  # noqa: E501

    @property
    def critical_warning(self):
        """Gets the critical_warning of this Smart.  # noqa: E501


        :return: The critical_warning of this Smart.  # noqa: E501
        :rtype: str
        """
        return self._critical_warning

    @critical_warning.setter
    def critical_warning(self, critical_warning):
        """Sets the critical_warning of this Smart.


        :param critical_warning: The critical_warning of this Smart.  # noqa: E501
        :type: str
        """

        self._critical_warning = critical_warning

    @property
    def power_cycles(self):
        """Gets the power_cycles of this Smart.  # noqa: E501


        :return: The power_cycles of this Smart.  # noqa: E501
        :rtype: str
        """
        return self._power_cycles

    @power_cycles.setter
    def power_cycles(self, power_cycles):
        """Sets the power_cycles of this Smart.


        :param power_cycles: The power_cycles of this Smart.  # noqa: E501
        :type: str
        """

        self._power_cycles = power_cycles

    @property
    def number_of_error_information_log_entries(self):
        """Gets the number_of_error_information_log_entries of this Smart.  # noqa: E501


        :return: The number_of_error_information_log_entries of this Smart.  # noqa: E501
        :rtype: str
        """
        return self._number_of_error_information_log_entries

    @number_of_error_information_log_entries.setter
    def number_of_error_information_log_entries(self, number_of_error_information_log_entries):  # noqa: E501
        """Sets the number_of_error_information_log_entries of this Smart.


        :param number_of_error_information_log_entries: The number_of_error_information_log_entries of this Smart.  # noqa: E501
        :type: str
        """

        self._number_of_error_information_log_entries = number_of_error_information_log_entries  # noqa: E501

    @property
    def percentage_used(self):
        """Gets the percentage_used of this Smart.  # noqa: E501


        :return: The percentage_used of this Smart.  # noqa: E501
        :rtype: str
        """
        return self._percentage_used

    @percentage_used.setter
    def percentage_used(self, percentage_used):
        """Sets the percentage_used of this Smart.


        :param percentage_used: The percentage_used of this Smart.  # noqa: E501
        :type: str
        """

        self._percentage_used = percentage_used

    @property
    def power_on_hours(self):
        """Gets the power_on_hours of this Smart.  # noqa: E501


        :return: The power_on_hours of this Smart.  # noqa: E501
        :rtype: str
        """
        return self._power_on_hours

    @power_on_hours.setter
    def power_on_hours(self, power_on_hours):
        """Sets the power_on_hours of this Smart.


        :param power_on_hours: The power_on_hours of this Smart.  # noqa: E501
        :type: str
        """

        self._power_on_hours = power_on_hours

    @property
    def composite_temperature(self):
        """Gets the composite_temperature of this Smart.  # noqa: E501


        :return: The composite_temperature of this Smart.  # noqa: E501
        :rtype: str
        """
        return self._composite_temperature

    @composite_temperature.setter
    def composite_temperature(self, composite_temperature):
        """Sets the composite_temperature of this Smart.


        :param composite_temperature: The composite_temperature of this Smart.  # noqa: E501
        :type: str
        """

        self._composite_temperature = composite_temperature

    @property
    def data_units_read(self):
        """Gets the data_units_read of this Smart.  # noqa: E501


        :return: The data_units_read of this Smart.  # noqa: E501
        :rtype: str
        """
        return self._data_units_read

    @data_units_read.setter
    def data_units_read(self, data_units_read):
        """Sets the data_units_read of this Smart.


        :param data_units_read: The data_units_read of this Smart.  # noqa: E501
        :type: str
        """

        self._data_units_read = data_units_read

    @property
    def unsafe_shutdowns(self):
        """Gets the unsafe_shutdowns of this Smart.  # noqa: E501


        :return: The unsafe_shutdowns of this Smart.  # noqa: E501
        :rtype: str
        """
        return self._unsafe_shutdowns

    @unsafe_shutdowns.setter
    def unsafe_shutdowns(self, unsafe_shutdowns):
        """Sets the unsafe_shutdowns of this Smart.


        :param unsafe_shutdowns: The unsafe_shutdowns of this Smart.  # noqa: E501
        :type: str
        """

        self._unsafe_shutdowns = unsafe_shutdowns

    def to_dict(self):
        """Returns the model properties as a dict"""
        result = {}

        for attr, _ in self.swagger_types.items():
            value = getattr(self, attr)
            if isinstance(value, list):
                result[attr] = list(map(
                    lambda x: x.to_dict() if hasattr(x, "to_dict") else x,
                    value
                ))
            elif hasattr(value, "to_dict"):
                result[attr] = value.to_dict()
            elif isinstance(value, dict):
                result[attr] = dict(map(
                    lambda item: (item[0], item[1].to_dict())
                    if hasattr(item[1], "to_dict") else item,
                    value.items()
                ))
            else:
                result[attr] = value
        if issubclass(Smart, dict):
            for key, value in self.items():
                result[key] = value

        return result

    def to_str(self):
        """Returns the string representation of the model"""
        return pprint.pformat(self.to_dict())

    def __repr__(self):
        """For `print` and `pprint`"""
        return self.to_str()

    def __eq__(self, other):
        """Returns true if both objects are equal"""
        if not isinstance(other, Smart):
            return False

        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        """Returns true if both objects are not equal"""
        return not self == other


class SpaceAllocationPolicy(object):
    """NOTE: This class is auto generated by the swagger code generator program

    Do not edit the class manually.
    """

    """
    allowed enum values
    """
    BALANCED = "balanced"
    WRITE_OPTIMIZED = "write_optimized"
    CAPACITY_OPTIMIZED = "capacity_optimized"

    """
    Attributes:
      swagger_types (dict): The key is attribute name
                            and the value is attribute type.
      attribute_map (dict): The key is attribute name
                            and the value is json key in definition.
    """
    swagger_types = {
    }

    attribute_map = {
    }

    def __init__(self):  # noqa: E501
        """SpaceAllocationPolicy - a model defined in Swagger"""  # noqa: E501
        self.discriminator = None

    def to_dict(self):
        """Returns the model properties as a dict"""
        result = {}

        for attr, _ in self.swagger_types.items():
            value = getattr(self, attr)
            if isinstance(value, list):
                result[attr] = list(map(
                    lambda x: x.to_dict() if hasattr(x, "to_dict") else x,
                    value
                ))
            elif hasattr(value, "to_dict"):
                result[attr] = value.to_dict()
            elif isinstance(value, dict):
                result[attr] = dict(map(
                    lambda item: (item[0], item[1].to_dict())
                    if hasattr(item[1], "to_dict") else item,
                    value.items()
                ))
            else:
                result[attr] = value
        if issubclass(SpaceAllocationPolicy, dict):
            for key, value in self.items():
                result[key] = value

        return result

    def to_str(self):
        """Returns the string representation of the model"""
        return pprint.pformat(self.to_dict())

    def __repr__(self):
        """For `print` and `pprint`"""
        return self.to_str()

    def __eq__(self, other):
        """Returns true if both objects are equal"""
        if not isinstance(other, SpaceAllocationPolicy):
            return False

        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        """Returns true if both objects are not equal"""
        return not self == other


class SuccessResponseFields(object):
    """NOTE: This class is auto generated by the swagger code generator program

    Do not edit the class manually.
    """

    """
    Attributes:
      swagger_types (dict): The key is attribute name
                            and the value is attribute type.
      attribute_map (dict): The key is attribute name
                            and the value is json key in definition.
    """
    swagger_types = {
        'status': 'bool',
        'message': 'str'
    }

    attribute_map = {
        'status': 'status',
        'message': 'message'
    }

    def __init__(self, status=True, message=None):  # noqa: E501
        """SuccessResponseFields - a model defined in Swagger"""  # noqa: E501

        self._status = None
        self._message = None
        self.discriminator = None

        self.status = status
        self.message = message

    @property
    def status(self):
        """Gets the status of this SuccessResponseFields.  # noqa: E501


        :return: The status of this SuccessResponseFields.  # noqa: E501
        :rtype: bool
        """
        return self._status

    @status.setter
    def status(self, status):
        """Sets the status of this SuccessResponseFields.


        :param status: The status of this SuccessResponseFields.  # noqa: E501
        :type: bool
        """
        if status is None:
            raise ValueError("Invalid value for `status`, must not be `None`")  # noqa: E501

        self._status = status

    @property
    def message(self):
        """Gets the message of this SuccessResponseFields.  # noqa: E501


        :return: The message of this SuccessResponseFields.  # noqa: E501
        :rtype: str
        """
        return self._message

    @message.setter
    def message(self, message):
        """Sets the message of this SuccessResponseFields.


        :param message: The message of this SuccessResponseFields.  # noqa: E501
        :type: str
        """
        if message is None:
            raise ValueError("Invalid value for `message`, must not be `None`")  # noqa: E501

        self._message = message

    def to_dict(self):
        """Returns the model properties as a dict"""
        result = {}

        for attr, _ in self.swagger_types.items():
            value = getattr(self, attr)
            if isinstance(value, list):
                result[attr] = list(map(
                    lambda x: x.to_dict() if hasattr(x, "to_dict") else x,
                    value
                ))
            elif hasattr(value, "to_dict"):
                result[attr] = value.to_dict()
            elif isinstance(value, dict):
                result[attr] = dict(map(
                    lambda item: (item[0], item[1].to_dict())
                    if hasattr(item[1], "to_dict") else item,
                    value.items()
                ))
            else:
                result[attr] = value
        if issubclass(SuccessResponseFields, dict):
            for key, value in self.items():
                result[key] = value

        return result

    def to_str(self):
        """Returns the string representation of the model"""
        return pprint.pformat(self.to_dict())

    def __repr__(self):
        """For `print` and `pprint`"""
        return self.to_str()

    def __eq__(self, other):
        """Returns true if both objects are equal"""
        if not isinstance(other, SuccessResponseFields):
            return False

        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        """Returns true if both objects are not equal"""
        return not self == other


class Transport(object):
    """NOTE: This class is auto generated by the swagger code generator program

    Do not edit the class manually.
    """

    """
    allowed enum values
    """
    RDS = "RDS"
    PCI = "PCI"
    PCI_BDF = "PCI_BDF"
    TCP = "TCP"

    """
    Attributes:
      swagger_types (dict): The key is attribute name
                            and the value is attribute type.
      attribute_map (dict): The key is attribute name
                            and the value is json key in definition.
    """
    swagger_types = {
    }

    attribute_map = {
    }

    def __init__(self):  # noqa: E501
        """Transport - a model defined in Swagger"""  # noqa: E501
        self.discriminator = None

    def to_dict(self):
        """Returns the model properties as a dict"""
        result = {}

        for attr, _ in self.swagger_types.items():
            value = getattr(self, attr)
            if isinstance(value, list):
                result[attr] = list(map(
                    lambda x: x.to_dict() if hasattr(x, "to_dict") else x,
                    value
                ))
            elif hasattr(value, "to_dict"):
                result[attr] = value.to_dict()
            elif isinstance(value, dict):
                result[attr] = dict(map(
                    lambda item: (item[0], item[1].to_dict())
                    if hasattr(item[1], "to_dict") else item,
                    value.items()
                ))
            else:
                result[attr] = value
        if issubclass(Transport, dict):
            for key, value in self.items():
                result[key] = value

        return result

    def to_str(self):
        """Returns the string representation of the model"""
        return pprint.pformat(self.to_dict())

    def __repr__(self):
        """For `print` and `pprint`"""
        return self.to_str()

    def __eq__(self, other):
        """Returns true if both objects are equal"""
        if not isinstance(other, Transport):
            return False

        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        """Returns true if both objects are not equal"""
        return not self == other


class UserVolumeType(object):
    """NOTE: This class is auto generated by the swagger code generator program

    Do not edit the class manually.
    """

    """
    allowed enum values
    """
    REPLICA = "VOL_TYPE_BLK_REPLICA"
    EC = "VOL_TYPE_BLK_EC"
    RF1 = "VOL_TYPE_BLK_RF1"
    LOCAL_THIN = "VOL_TYPE_BLK_LOCAL_THIN"

    """
    Attributes:
      swagger_types (dict): The key is attribute name
                            and the value is attribute type.
      attribute_map (dict): The key is attribute name
                            and the value is json key in definition.
    """
    swagger_types = {
    }

    attribute_map = {
    }

    def __init__(self):  # noqa: E501
        """UserVolumeType - a model defined in Swagger"""  # noqa: E501
        self.discriminator = None

    def to_dict(self):
        """Returns the model properties as a dict"""
        result = {}

        for attr, _ in self.swagger_types.items():
            value = getattr(self, attr)
            if isinstance(value, list):
                result[attr] = list(map(
                    lambda x: x.to_dict() if hasattr(x, "to_dict") else x,
                    value
                ))
            elif hasattr(value, "to_dict"):
                result[attr] = value.to_dict()
            elif isinstance(value, dict):
                result[attr] = dict(map(
                    lambda item: (item[0], item[1].to_dict())
                    if hasattr(item[1], "to_dict") else item,
                    value.items()
                ))
            else:
                result[attr] = value
        if issubclass(UserVolumeType, dict):
            for key, value in self.items():
                result[key] = value

        return result

    def to_str(self):
        """Returns the string representation of the model"""
        return pprint.pformat(self.to_dict())

    def __repr__(self):
        """For `print` and `pprint`"""
        return self.to_str()

    def __eq__(self, other):
        """Returns true if both objects are equal"""
        if not isinstance(other, UserVolumeType):
            return False

        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        """Returns true if both objects are not equal"""
        return not self == other


class VolumeQos(object):
    """NOTE: This class is auto generated by the swagger code generator program

    Do not edit the class manually.
    """

    """
    Attributes:
      swagger_types (dict): The key is attribute name
                            and the value is attribute type.
      attribute_map (dict): The key is attribute name
                            and the value is json key in definition.
    """
    swagger_types = {
        'band_name': 'str',
        'band_index': 'int',
        'min_read_iops': 'int',
        'max_read_iops': 'int',
        'min_write_iops': 'int',
        'max_write_iops': 'int'
    }

    attribute_map = {
        'band_name': 'band_name',
        'band_index': 'band_index',
        'min_read_iops': 'min_read_iops',
        'max_read_iops': 'max_read_iops',
        'min_write_iops': 'min_write_iops',
        'max_write_iops': 'max_write_iops'
    }

    def __init__(self, band_name=None, band_index=None, min_read_iops=None, max_read_iops=None, min_write_iops=None, max_write_iops=None):  # noqa: E501
        """VolumeQos - a model defined in Swagger"""  # noqa: E501

        self._band_name = None
        self._band_index = None
        self._min_read_iops = None
        self._max_read_iops = None
        self._min_write_iops = None
        self._max_write_iops = None
        self.discriminator = None

        if band_name is not None:
            self.band_name = band_name
        self.band_index = band_index
        if min_read_iops is not None:
            self.min_read_iops = min_read_iops
        self.max_read_iops = max_read_iops
        if min_write_iops is not None:
            self.min_write_iops = min_write_iops
        if max_write_iops is not None:
            self.max_write_iops = max_write_iops

    @property
    def band_name(self):
        """Gets the band_name of this VolumeQos.  # noqa: E501

        e.g. Gold, Silver or Bronze  # noqa: E501

        :return: The band_name of this VolumeQos.  # noqa: E501
        :rtype: str
        """
        return self._band_name

    @band_name.setter
    def band_name(self, band_name):
        """Sets the band_name of this VolumeQos.

        e.g. Gold, Silver or Bronze  # noqa: E501

        :param band_name: The band_name of this VolumeQos.  # noqa: E501
        :type: str
        """

        self._band_name = band_name

    @property
    def band_index(self):
        """Gets the band_index of this VolumeQos.  # noqa: E501


        :return: The band_index of this VolumeQos.  # noqa: E501
        :rtype: int
        """
        return self._band_index

    @band_index.setter
    def band_index(self, band_index):
        """Sets the band_index of this VolumeQos.


        :param band_index: The band_index of this VolumeQos.  # noqa: E501
        :type: int
        """
        if band_index is None:
            raise ValueError("Invalid value for `band_index`, must not be `None`")  # noqa: E501

        self._band_index = band_index

    @property
    def min_read_iops(self):
        """Gets the min_read_iops of this VolumeQos.  # noqa: E501


        :return: The min_read_iops of this VolumeQos.  # noqa: E501
        :rtype: int
        """
        return self._min_read_iops

    @min_read_iops.setter
    def min_read_iops(self, min_read_iops):
        """Sets the min_read_iops of this VolumeQos.


        :param min_read_iops: The min_read_iops of this VolumeQos.  # noqa: E501
        :type: int
        """

        self._min_read_iops = min_read_iops

    @property
    def max_read_iops(self):
        """Gets the max_read_iops of this VolumeQos.  # noqa: E501


        :return: The max_read_iops of this VolumeQos.  # noqa: E501
        :rtype: int
        """
        return self._max_read_iops

    @max_read_iops.setter
    def max_read_iops(self, max_read_iops):
        """Sets the max_read_iops of this VolumeQos.


        :param max_read_iops: The max_read_iops of this VolumeQos.  # noqa: E501
        :type: int
        """
        if max_read_iops is None:
            raise ValueError("Invalid value for `max_read_iops`, must not be `None`")  # noqa: E501

        self._max_read_iops = max_read_iops

    @property
    def min_write_iops(self):
        """Gets the min_write_iops of this VolumeQos.  # noqa: E501


        :return: The min_write_iops of this VolumeQos.  # noqa: E501
        :rtype: int
        """
        return self._min_write_iops

    @min_write_iops.setter
    def min_write_iops(self, min_write_iops):
        """Sets the min_write_iops of this VolumeQos.


        :param min_write_iops: The min_write_iops of this VolumeQos.  # noqa: E501
        :type: int
        """

        self._min_write_iops = min_write_iops

    @property
    def max_write_iops(self):
        """Gets the max_write_iops of this VolumeQos.  # noqa: E501


        :return: The max_write_iops of this VolumeQos.  # noqa: E501
        :rtype: int
        """
        return self._max_write_iops

    @max_write_iops.setter
    def max_write_iops(self, max_write_iops):
        """Sets the max_write_iops of this VolumeQos.


        :param max_write_iops: The max_write_iops of this VolumeQos.  # noqa: E501
        :type: int
        """

        self._max_write_iops = max_write_iops

    def to_dict(self):
        """Returns the model properties as a dict"""
        result = {}

        for attr, _ in self.swagger_types.items():
            value = getattr(self, attr)
            if isinstance(value, list):
                result[attr] = list(map(
                    lambda x: x.to_dict() if hasattr(x, "to_dict") else x,
                    value
                ))
            elif hasattr(value, "to_dict"):
                result[attr] = value.to_dict()
            elif isinstance(value, dict):
                result[attr] = dict(map(
                    lambda item: (item[0], item[1].to_dict())
                    if hasattr(item[1], "to_dict") else item,
                    value.items()
                ))
            else:
                result[attr] = value
        if issubclass(VolumeQos, dict):
            for key, value in self.items():
                result[key] = value

        return result

    def to_str(self):
        """Returns the string representation of the model"""
        return pprint.pformat(self.to_dict())

    def __repr__(self):
        """For `print` and `pprint`"""
        return self.to_str()

    def __eq__(self, other):
        """Returns true if both objects are equal"""
        if not isinstance(other, VolumeQos):
            return False

        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        """Returns true if both objects are not equal"""
        return not self == other


class VolumeStats(object):
    """NOTE: This class is auto generated by the swagger code generator program

    Do not edit the class manually.
    """

    """
    Attributes:
      swagger_types (dict): The key is attribute name
                            and the value is attribute type.
      attribute_map (dict): The key is attribute name
                            and the value is json key in definition.
    """
    swagger_types = {
        'physical_usage': 'int',
        'physical_writes': 'int',
        'stats': 'VolumeStatsStats'
    }

    attribute_map = {
        'physical_usage': 'physical_usage',
        'physical_writes': 'physical_writes',
        'stats': 'stats'
    }

    def __init__(self, physical_usage=None, physical_writes=None, stats=None):  # noqa: E501
        """VolumeStats - a model defined in Swagger"""  # noqa: E501

        self._physical_usage = None
        self._physical_writes = None
        self._stats = None
        self.discriminator = None

        if physical_usage is not None:
            self.physical_usage = physical_usage
        if physical_writes is not None:
            self.physical_writes = physical_writes
        if stats is not None:
            self.stats = stats

    @property
    def physical_usage(self):
        """Gets the physical_usage of this VolumeStats.  # noqa: E501


        :return: The physical_usage of this VolumeStats.  # noqa: E501
        :rtype: int
        """
        return self._physical_usage

    @physical_usage.setter
    def physical_usage(self, physical_usage):
        """Sets the physical_usage of this VolumeStats.


        :param physical_usage: The physical_usage of this VolumeStats.  # noqa: E501
        :type: int
        """

        self._physical_usage = physical_usage

    @property
    def physical_writes(self):
        """Gets the physical_writes of this VolumeStats.  # noqa: E501


        :return: The physical_writes of this VolumeStats.  # noqa: E501
        :rtype: int
        """
        return self._physical_writes

    @physical_writes.setter
    def physical_writes(self, physical_writes):
        """Sets the physical_writes of this VolumeStats.


        :param physical_writes: The physical_writes of this VolumeStats.  # noqa: E501
        :type: int
        """

        self._physical_writes = physical_writes

    @property
    def stats(self):
        """Gets the stats of this VolumeStats.  # noqa: E501


        :return: The stats of this VolumeStats.  # noqa: E501
        :rtype: VolumeStatsStats
        """
        return self._stats

    @stats.setter
    def stats(self, stats):
        """Sets the stats of this VolumeStats.


        :param stats: The stats of this VolumeStats.  # noqa: E501
        :type: VolumeStatsStats
        """

        self._stats = stats

    def to_dict(self):
        """Returns the model properties as a dict"""
        result = {}

        for attr, _ in self.swagger_types.items():
            value = getattr(self, attr)
            if isinstance(value, list):
                result[attr] = list(map(
                    lambda x: x.to_dict() if hasattr(x, "to_dict") else x,
                    value
                ))
            elif hasattr(value, "to_dict"):
                result[attr] = value.to_dict()
            elif isinstance(value, dict):
                result[attr] = dict(map(
                    lambda item: (item[0], item[1].to_dict())
                    if hasattr(item[1], "to_dict") else item,
                    value.items()
                ))
            else:
                result[attr] = value
        if issubclass(VolumeStats, dict):
            for key, value in self.items():
                result[key] = value

        return result

    def to_str(self):
        """Returns the string representation of the model"""
        return pprint.pformat(self.to_dict())

    def __repr__(self):
        """For `print` and `pprint`"""
        return self.to_str()

    def __eq__(self, other):
        """Returns true if both objects are equal"""
        if not isinstance(other, VolumeStats):
            return False

        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        """Returns true if both objects are not equal"""
        return not self == other


class VolumeTypes(object):
    """NOTE: This class is auto generated by the swagger code generator program

    Do not edit the class manually.
    """

    """
    allowed enum values
    """
    LOCAL_THIN = "VOL_TYPE_BLK_LOCAL_THIN"
    RF1 = "VOL_TYPE_BLK_RF1"
    RDS = "VOL_TYPE_BLK_RDS"
    LSV = "VOL_TYPE_BLK_LSV"
    NV_MEMORY = "VOL_TYPE_BLK_NV_MEMORY"
    FILE = "VOL_TYPE_BLK_FILE"
    EC = "VOL_TYPE_BLK_EC"
    REPLICA = "VOL_TYPE_BLK_REPLICA"
    STRIPE = "VOL_TYPE_BLK_STRIPE"
    CONCAT = "VOL_TYPE_BLK_CONCAT"
    PART_VOL = "VOL_TYPE_BLK_PART_VOL"
    DURABLE = "VOL_TYPE_BLK_DURABLE"

    """
    Attributes:
      swagger_types (dict): The key is attribute name
                            and the value is attribute type.
      attribute_map (dict): The key is attribute name
                            and the value is json key in definition.
    """
    swagger_types = {
    }

    attribute_map = {
    }

    def __init__(self):  # noqa: E501
        """VolumeTypes - a model defined in Swagger"""  # noqa: E501
        self.discriminator = None

    def to_dict(self):
        """Returns the model properties as a dict"""
        result = {}

        for attr, _ in self.swagger_types.items():
            value = getattr(self, attr)
            if isinstance(value, list):
                result[attr] = list(map(
                    lambda x: x.to_dict() if hasattr(x, "to_dict") else x,
                    value
                ))
            elif hasattr(value, "to_dict"):
                result[attr] = value.to_dict()
            elif isinstance(value, dict):
                result[attr] = dict(map(
                    lambda item: (item[0], item[1].to_dict())
                    if hasattr(item[1], "to_dict") else item,
                    value.items()
                ))
            else:
                result[attr] = value
        if issubclass(VolumeTypes, dict):
            for key, value in self.items():
                result[key] = value

        return result

    def to_str(self):
        """Returns the string representation of the model"""
        return pprint.pformat(self.to_dict())

    def __repr__(self):
        """For `print` and `pprint`"""
        return self.to_str()

    def __eq__(self, other):
        """Returns true if both objects are equal"""
        if not isinstance(other, VolumeTypes):
            return False

        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        """Returns true if both objects are not equal"""
        return not self == other


class VolumeUpdateOp(object):
    """NOTE: This class is auto generated by the swagger code generator program

    Do not edit the class manually.
    """

    """
    allowed enum values
    """
    UNMOUNT = "UNMOUNT"
    MOUNT = "MOUNT"
    MARK_FAIL = "MARK_FAIL"
    UPDATE_VOLUME_DPU = "UPDATE_VOLUME_DPU"
    RESYNC = "RESYNC"
    UPDATE_STATE = "UPDATE_STATE"
    UPDATE_CAPACITY = "UPDATE_CAPACITY"
    UPDATE_PROPERTIES = "UPDATE_PROPERTIES"
    INJECT_FAILURE = "INJECT_FAILURE"
    RENAME_VOLUME = "RENAME_VOLUME"

    """
    Attributes:
      swagger_types (dict): The key is attribute name
                            and the value is attribute type.
      attribute_map (dict): The key is attribute name
                            and the value is json key in definition.
    """
    swagger_types = {
    }

    attribute_map = {
    }

    def __init__(self):  # noqa: E501
        """VolumeUpdateOp - a model defined in Swagger"""  # noqa: E501
        self.discriminator = None

    def to_dict(self):
        """Returns the model properties as a dict"""
        result = {}

        for attr, _ in self.swagger_types.items():
            value = getattr(self, attr)
            if isinstance(value, list):
                result[attr] = list(map(
                    lambda x: x.to_dict() if hasattr(x, "to_dict") else x,
                    value
                ))
            elif hasattr(value, "to_dict"):
                result[attr] = value.to_dict()
            elif isinstance(value, dict):
                result[attr] = dict(map(
                    lambda item: (item[0], item[1].to_dict())
                    if hasattr(item[1], "to_dict") else item,
                    value.items()
                ))
            else:
                result[attr] = value
        if issubclass(VolumeUpdateOp, dict):
            for key, value in self.items():
                result[key] = value

        return result

    def to_str(self):
        """Returns the string representation of the model"""
        return pprint.pformat(self.to_dict())

    def __repr__(self):
        """For `print` and `pprint`"""
        return self.to_str()

    def __eq__(self, other):
        """Returns true if both objects are equal"""
        if not isinstance(other, VolumeUpdateOp):
            return False

        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        """Returns true if both objects are not equal"""
        return not self == other


class Volume(object):
    """NOTE: This class is auto generated by the swagger code generator program

    Do not edit the class manually.
    """

    """
    Attributes:
      swagger_types (dict): The key is attribute name
                            and the value is attribute type.
      attribute_map (dict): The key is attribute name
                            and the value is json key in definition.
    """
    swagger_types = {
        'name': 'str',
        'uuid': 'str',
        'nguid': 'str',
        'drive_uuid': 'str',
        'type': 'str',
        'pool': 'str',
        'dpu': 'str',
        'secy_dpu': 'str',
        'capacity': 'int',
        'compress': 'bool',
        'encrypt': 'bool',
        'zip_effort': 'ZipEffort',
        'crc_enable': 'bool',
        'snap_support': 'bool',
        'crc_type': 'str',
        'is_clone': 'bool',
        'clone_source_volume_uuid': 'str',
        'state': 'ResourceState',
        'clone_source_volume_state': 'ResourceState',
        'version': 'str',
        'failed_uuids': 'list[str]',
        'num_failed_plexes': 'int',
        'rebuild_state': 'RebuildState',
        'rebuild_percent': 'int',
        'spare_vol': 'str',
        'subsys_nqn': 'str',
        'qos': 'VolumeQos',
        'ports': 'MapOfPorts',
        'src_vols': 'list[str]',
        'durability_scheme': 'str',
        'stats': 'VolumeStats',
        'physical_capacity': 'int',
        'space_allocation_policy': 'SpaceAllocationPolicy',
        'additional_fields': 'AdditionalFields',
        'created_at': 'datetime',
        'modified_at': 'datetime',
        'block_size': 'BlockSize',
        'operations': 'list[Operation]',
        'fault_domain_id': 'str',
        'volume_type': 'UserVolumeType'
    }

    attribute_map = {
        'name': 'name',
        'uuid': 'uuid',
        'nguid': 'nguid',
        'drive_uuid': 'drive_uuid',
        'type': 'type',
        'pool': 'pool',
        'dpu': 'dpu',
        'secy_dpu': 'secy_dpu',
        'capacity': 'capacity',
        'compress': 'compress',
        'encrypt': 'encrypt',
        'zip_effort': 'zip_effort',
        'crc_enable': 'crc_enable',
        'snap_support': 'snap_support',
        'crc_type': 'crc_type',
        'is_clone': 'is_clone',
        'clone_source_volume_uuid': 'clone_source_volume_uuid',
        'state': 'state',
        'clone_source_volume_state': 'clone_source_volume_state',
        'version': 'version',
        'failed_uuids': 'failed_uuids',
        'num_failed_plexes': 'num_failed_plexes',
        'rebuild_state': 'rebuild_state',
        'rebuild_percent': 'rebuild_percent',
        'spare_vol': 'spare_vol',
        'subsys_nqn': 'subsys_nqn',
        'qos': 'qos',
        'ports': 'ports',
        'src_vols': 'src_vols',
        'durability_scheme': 'durability_scheme',
        'stats': 'stats',
        'physical_capacity': 'physical_capacity',
        'space_allocation_policy': 'space_allocation_policy',
        'additional_fields': 'additional_fields',
        'created_at': 'created_at',
        'modified_at': 'modified_at',
        'block_size': 'block_size',
        'operations': 'operations',
        'fault_domain_id': 'fault_domain_id',
        'volume_type': 'volume_type'
    }

    def __init__(self, name=None, uuid=None, nguid=None, drive_uuid=None, type=None, pool=None, dpu=None, secy_dpu=None, capacity=None, compress=None, encrypt=None, zip_effort=None, crc_enable=None, snap_support=None, crc_type='nocrc', is_clone=None, clone_source_volume_uuid=None, state=None, clone_source_volume_state=None, version=None, failed_uuids=None, num_failed_plexes=None, rebuild_state=None, rebuild_percent=None, spare_vol=None, subsys_nqn=None, qos=None, ports=None, src_vols=None, durability_scheme=None, stats=None, physical_capacity=None, space_allocation_policy=None, additional_fields=None, created_at=None, modified_at=None, block_size=None, operations=None, fault_domain_id=None, volume_type=None):  # noqa: E501,C901
        """Volume - a model defined in Swagger"""  # noqa: E501

        self._name = None
        self._uuid = None
        self._nguid = None
        self._drive_uuid = None
        self._type = None
        self._pool = None
        self._dpu = None
        self._secy_dpu = None
        self._capacity = None
        self._compress = None
        self._encrypt = None
        self._zip_effort = None
        self._crc_enable = None
        self._snap_support = None
        self._crc_type = None
        self._is_clone = None
        self._clone_source_volume_uuid = None
        self._state = None
        self._clone_source_volume_state = None
        self._version = None
        self._failed_uuids = None
        self._num_failed_plexes = None
        self._rebuild_state = None
        self._rebuild_percent = None
        self._spare_vol = None
        self._subsys_nqn = None
        self._qos = None
        self._ports = None
        self._src_vols = None
        self._durability_scheme = None
        self._stats = None
        self._physical_capacity = None
        self._space_allocation_policy = None
        self._additional_fields = None
        self._created_at = None
        self._modified_at = None
        self._block_size = None
        self._operations = None
        self._fault_domain_id = None
        self._volume_type = None
        self.discriminator = None

        if name is not None:
            self.name = name
        self.uuid = uuid
        if nguid is not None:
            self.nguid = nguid
        if drive_uuid is not None:
            self.drive_uuid = drive_uuid
        self.type = type
        if pool is not None:
            self.pool = pool
        if dpu is not None:
            self.dpu = dpu
        if secy_dpu is not None:
            self.secy_dpu = secy_dpu
        if capacity is not None:
            self.capacity = capacity
        if compress is not None:
            self.compress = compress
        if encrypt is not None:
            self.encrypt = encrypt
        if zip_effort is not None:
            self.zip_effort = zip_effort
        if crc_enable is not None:
            self.crc_enable = crc_enable
        if snap_support is not None:
            self.snap_support = snap_support
        if crc_type is not None:
            self.crc_type = crc_type
        if is_clone is not None:
            self.is_clone = is_clone
        if clone_source_volume_uuid is not None:
            self.clone_source_volume_uuid = clone_source_volume_uuid
        if state is not None:
            self.state = state
        if clone_source_volume_state is not None:
            self.clone_source_volume_state = clone_source_volume_state
        if version is not None:
            self.version = version
        if failed_uuids is not None:
            self.failed_uuids = failed_uuids
        if num_failed_plexes is not None:
            self.num_failed_plexes = num_failed_plexes
        if rebuild_state is not None:
            self.rebuild_state = rebuild_state
        if rebuild_percent is not None:
            self.rebuild_percent = rebuild_percent
        if spare_vol is not None:
            self.spare_vol = spare_vol
        self.subsys_nqn = subsys_nqn
        if qos is not None:
            self.qos = qos
        if ports is not None:
            self.ports = ports
        if src_vols is not None:
            self.src_vols = src_vols
        if durability_scheme is not None:
            self.durability_scheme = durability_scheme
        if stats is not None:
            self.stats = stats
        self.physical_capacity = physical_capacity
        if space_allocation_policy is not None:
            self.space_allocation_policy = space_allocation_policy
        if additional_fields is not None:
            self.additional_fields = additional_fields
        if created_at is not None:
            self.created_at = created_at
        if modified_at is not None:
            self.modified_at = modified_at
        if block_size is not None:
            self.block_size = block_size
        if operations is not None:
            self.operations = operations
        if fault_domain_id is not None:
            self.fault_domain_id = fault_domain_id
        if volume_type is not None:
            self.volume_type = volume_type

    @property
    def name(self):
        """Gets the name of this Volume.  # noqa: E501

        user specified name of volume  # noqa: E501

        :return: The name of this Volume.  # noqa: E501
        :rtype: str
        """
        return self._name

    @name.setter
    def name(self, name):
        """Sets the name of this Volume.

        user specified name of volume  # noqa: E501

        :param name: The name of this Volume.  # noqa: E501
        :type: str
        """

        self._name = name

    @property
    def uuid(self):
        """Gets the uuid of this Volume.  # noqa: E501

        assigned by FC  # noqa: E501

        :return: The uuid of this Volume.  # noqa: E501
        :rtype: str
        """
        return self._uuid

    @uuid.setter
    def uuid(self, uuid):
        """Sets the uuid of this Volume.

        assigned by FC  # noqa: E501

        :param uuid: The uuid of this Volume.  # noqa: E501
        :type: str
        """
        if uuid is None:
            raise ValueError("Invalid value for `uuid`, must not be `None`")  # noqa: E501

        self._uuid = uuid

    @property
    def nguid(self):
        """Gets the nguid of this Volume.  # noqa: E501

        assigned by FC  # noqa: E501

        :return: The nguid of this Volume.  # noqa: E501
        :rtype: str
        """
        return self._nguid

    @nguid.setter
    def nguid(self, nguid):
        """Sets the nguid of this Volume.

        assigned by FC  # noqa: E501

        :param nguid: The nguid of this Volume.  # noqa: E501
        :type: str
        """

        self._nguid = nguid

    @property
    def drive_uuid(self):
        """Gets the drive_uuid of this Volume.  # noqa: E501


        :return: The drive_uuid of this Volume.  # noqa: E501
        :rtype: str
        """
        return self._drive_uuid

    @drive_uuid.setter
    def drive_uuid(self, drive_uuid):
        """Sets the drive_uuid of this Volume.


        :param drive_uuid: The drive_uuid of this Volume.  # noqa: E501
        :type: str
        """

        self._drive_uuid = drive_uuid

    @property
    def type(self):
        """Gets the type of this Volume.  # noqa: E501


        :return: The type of this Volume.  # noqa: E501
        :rtype: str
        """
        return self._type

    @type.setter
    def type(self, type):
        """Sets the type of this Volume.


        :param type: The type of this Volume.  # noqa: E501
        :type: str
        """
        if type is None:
            raise ValueError("Invalid value for `type`, must not be `None`")  # noqa: E501

        self._type = type

    @property
    def pool(self):
        """Gets the pool of this Volume.  # noqa: E501


        :return: The pool of this Volume.  # noqa: E501
        :rtype: str
        """
        return self._pool

    @pool.setter
    def pool(self, pool):
        """Sets the pool of this Volume.


        :param pool: The pool of this Volume.  # noqa: E501
        :type: str
        """

        self._pool = pool

    @property
    def dpu(self):
        """Gets the dpu of this Volume.  # noqa: E501


        :return: The dpu of this Volume.  # noqa: E501
        :rtype: str
        """
        return self._dpu

    @dpu.setter
    def dpu(self, dpu):
        """Sets the dpu of this Volume.


        :param dpu: The dpu of this Volume.  # noqa: E501
        :type: str
        """

        self._dpu = dpu

    @property
    def secy_dpu(self):
        """Gets the secy_dpu of this Volume.  # noqa: E501

        secondary dpu (valid for durable volume)  # noqa: E501

        :return: The secy_dpu of this Volume.  # noqa: E501
        :rtype: str
        """
        return self._secy_dpu

    @secy_dpu.setter
    def secy_dpu(self, secy_dpu):
        """Sets the secy_dpu of this Volume.

        secondary dpu (valid for durable volume)  # noqa: E501

        :param secy_dpu: The secy_dpu of this Volume.  # noqa: E501
        :type: str
        """

        self._secy_dpu = secy_dpu

    @property
    def capacity(self):
        """Gets the capacity of this Volume.  # noqa: E501


        :return: The capacity of this Volume.  # noqa: E501
        :rtype: int
        """
        return self._capacity

    @capacity.setter
    def capacity(self, capacity):
        """Sets the capacity of this Volume.


        :param capacity: The capacity of this Volume.  # noqa: E501
        :type: int
        """

        self._capacity = capacity

    @property
    def compress(self):
        """Gets the compress of this Volume.  # noqa: E501


        :return: The compress of this Volume.  # noqa: E501
        :rtype: bool
        """
        return self._compress

    @compress.setter
    def compress(self, compress):
        """Sets the compress of this Volume.


        :param compress: The compress of this Volume.  # noqa: E501
        :type: bool
        """

        self._compress = compress

    @property
    def encrypt(self):
        """Gets the encrypt of this Volume.  # noqa: E501


        :return: The encrypt of this Volume.  # noqa: E501
        :rtype: bool
        """
        return self._encrypt

    @encrypt.setter
    def encrypt(self, encrypt):
        """Sets the encrypt of this Volume.


        :param encrypt: The encrypt of this Volume.  # noqa: E501
        :type: bool
        """

        self._encrypt = encrypt

    @property
    def zip_effort(self):
        """Gets the zip_effort of this Volume.  # noqa: E501


        :return: The zip_effort of this Volume.  # noqa: E501
        :rtype: ZipEffort
        """
        return self._zip_effort

    @zip_effort.setter
    def zip_effort(self, zip_effort):
        """Sets the zip_effort of this Volume.


        :param zip_effort: The zip_effort of this Volume.  # noqa: E501
        :type: ZipEffort
        """

        self._zip_effort = zip_effort

    @property
    def crc_enable(self):
        """Gets the crc_enable of this Volume.  # noqa: E501


        :return: The crc_enable of this Volume.  # noqa: E501
        :rtype: bool
        """
        return self._crc_enable

    @crc_enable.setter
    def crc_enable(self, crc_enable):
        """Sets the crc_enable of this Volume.


        :param crc_enable: The crc_enable of this Volume.  # noqa: E501
        :type: bool
        """

        self._crc_enable = crc_enable

    @property
    def snap_support(self):
        """Gets the snap_support of this Volume.  # noqa: E501


        :return: The snap_support of this Volume.  # noqa: E501
        :rtype: bool
        """
        return self._snap_support

    @snap_support.setter
    def snap_support(self, snap_support):
        """Sets the snap_support of this Volume.


        :param snap_support: The snap_support of this Volume.  # noqa: E501
        :type: bool
        """

        self._snap_support = snap_support

    @property
    def crc_type(self):
        """Gets the crc_type of this Volume.  # noqa: E501


        :return: The crc_type of this Volume.  # noqa: E501
        :rtype: str
        """
        return self._crc_type

    @crc_type.setter
    def crc_type(self, crc_type):
        """Sets the crc_type of this Volume.


        :param crc_type: The crc_type of this Volume.  # noqa: E501
        :type: str
        """
        allowed_values = ["crc16", "crc32", "crc32c", "crc64", "nocrc"]  # noqa: E501
        if crc_type not in allowed_values:
            raise ValueError(
                "Invalid value for `crc_type` ({0}), must be one of {1}"  # noqa: E501
                .format(crc_type, allowed_values)
            )

        self._crc_type = crc_type

    @property
    def is_clone(self):
        """Gets the is_clone of this Volume.  # noqa: E501


        :return: The is_clone of this Volume.  # noqa: E501
        :rtype: bool
        """
        return self._is_clone

    @is_clone.setter
    def is_clone(self, is_clone):
        """Sets the is_clone of this Volume.


        :param is_clone: The is_clone of this Volume.  # noqa: E501
        :type: bool
        """

        self._is_clone = is_clone

    @property
    def clone_source_volume_uuid(self):
        """Gets the clone_source_volume_uuid of this Volume.  # noqa: E501


        :return: The clone_source_volume_uuid of this Volume.  # noqa: E501
        :rtype: str
        """
        return self._clone_source_volume_uuid

    @clone_source_volume_uuid.setter
    def clone_source_volume_uuid(self, clone_source_volume_uuid):
        """Sets the clone_source_volume_uuid of this Volume.


        :param clone_source_volume_uuid: The clone_source_volume_uuid of this Volume.  # noqa: E501
        :type: str
        """

        self._clone_source_volume_uuid = clone_source_volume_uuid

    @property
    def state(self):
        """Gets the state of this Volume.  # noqa: E501


        :return: The state of this Volume.  # noqa: E501
        :rtype: ResourceState
        """
        return self._state

    @state.setter
    def state(self, state):
        """Sets the state of this Volume.


        :param state: The state of this Volume.  # noqa: E501
        :type: ResourceState
        """

        self._state = state

    @property
    def clone_source_volume_state(self):
        """Gets the clone_source_volume_state of this Volume.  # noqa: E501


        :return: The clone_source_volume_state of this Volume.  # noqa: E501
        :rtype: ResourceState
        """
        return self._clone_source_volume_state

    @clone_source_volume_state.setter
    def clone_source_volume_state(self, clone_source_volume_state):
        """Sets the clone_source_volume_state of this Volume.


        :param clone_source_volume_state: The clone_source_volume_state of this Volume.  # noqa: E501
        :type: ResourceState
        """

        self._clone_source_volume_state = clone_source_volume_state

    @property
    def version(self):
        """Gets the version of this Volume.  # noqa: E501


        :return: The version of this Volume.  # noqa: E501
        :rtype: str
        """
        return self._version

    @version.setter
    def version(self, version):
        """Sets the version of this Volume.


        :param version: The version of this Volume.  # noqa: E501
        :type: str
        """

        self._version = version

    @property
    def failed_uuids(self):
        """Gets the failed_uuids of this Volume.  # noqa: E501

        list of uuids of failed data/parity partitions (valid for durable volumes)  # noqa: E501

        :return: The failed_uuids of this Volume.  # noqa: E501
        :rtype: list[str]
        """
        return self._failed_uuids

    @failed_uuids.setter
    def failed_uuids(self, failed_uuids):
        """Sets the failed_uuids of this Volume.

        list of uuids of failed data/parity partitions (valid for durable volumes)  # noqa: E501

        :param failed_uuids: The failed_uuids of this Volume.  # noqa: E501
        :type: list[str]
        """

        self._failed_uuids = failed_uuids

    @property
    def num_failed_plexes(self):
        """Gets the num_failed_plexes of this Volume.  # noqa: E501

        number of failed data/parity partitions (valid for durable volumes)  # noqa: E501

        :return: The num_failed_plexes of this Volume.  # noqa: E501
        :rtype: int
        """
        return self._num_failed_plexes

    @num_failed_plexes.setter
    def num_failed_plexes(self, num_failed_plexes):
        """Sets the num_failed_plexes of this Volume.

        number of failed data/parity partitions (valid for durable volumes)  # noqa: E501

        :param num_failed_plexes: The num_failed_plexes of this Volume.  # noqa: E501
        :type: int
        """

        self._num_failed_plexes = num_failed_plexes

    @property
    def rebuild_state(self):
        """Gets the rebuild_state of this Volume.  # noqa: E501


        :return: The rebuild_state of this Volume.  # noqa: E501
        :rtype: RebuildState
        """
        return self._rebuild_state

    @rebuild_state.setter
    def rebuild_state(self, rebuild_state):
        """Sets the rebuild_state of this Volume.


        :param rebuild_state: The rebuild_state of this Volume.  # noqa: E501
        :type: RebuildState
        """

        self._rebuild_state = rebuild_state

    @property
    def rebuild_percent(self):
        """Gets the rebuild_percent of this Volume.  # noqa: E501


        :return: The rebuild_percent of this Volume.  # noqa: E501
        :rtype: int
        """
        return self._rebuild_percent

    @rebuild_percent.setter
    def rebuild_percent(self, rebuild_percent):
        """Sets the rebuild_percent of this Volume.


        :param rebuild_percent: The rebuild_percent of this Volume.  # noqa: E501
        :type: int
        """
        if rebuild_percent is not None and rebuild_percent > 100:  # noqa: E501
            raise ValueError("Invalid value for `rebuild_percent`, must be a value less than or equal to `100`")  # noqa: E501
        if rebuild_percent is not None and rebuild_percent < 0:  # noqa: E501
            raise ValueError("Invalid value for `rebuild_percent`, must be a value greater than or equal to `0`")  # noqa: E501

        self._rebuild_percent = rebuild_percent

    @property
    def spare_vol(self):
        """Gets the spare_vol of this Volume.  # noqa: E501


        :return: The spare_vol of this Volume.  # noqa: E501
        :rtype: str
        """
        return self._spare_vol

    @spare_vol.setter
    def spare_vol(self, spare_vol):
        """Sets the spare_vol of this Volume.


        :param spare_vol: The spare_vol of this Volume.  # noqa: E501
        :type: str
        """

        self._spare_vol = spare_vol

    @property
    def subsys_nqn(self):
        """Gets the subsys_nqn of this Volume.  # noqa: E501


        :return: The subsys_nqn of this Volume.  # noqa: E501
        :rtype: str
        """
        return self._subsys_nqn

    @subsys_nqn.setter
    def subsys_nqn(self, subsys_nqn):
        """Sets the subsys_nqn of this Volume.


        :param subsys_nqn: The subsys_nqn of this Volume.  # noqa: E501
        :type: str
        """
        if subsys_nqn is None:
            raise ValueError("Invalid value for `subsys_nqn`, must not be `None`")  # noqa: E501

        self._subsys_nqn = subsys_nqn

    @property
    def qos(self):
        """Gets the qos of this Volume.  # noqa: E501


        :return: The qos of this Volume.  # noqa: E501
        :rtype: VolumeQos
        """
        return self._qos

    @qos.setter
    def qos(self, qos):
        """Sets the qos of this Volume.


        :param qos: The qos of this Volume.  # noqa: E501
        :type: VolumeQos
        """

        self._qos = qos

    @property
    def ports(self):
        """Gets the ports of this Volume.  # noqa: E501


        :return: The ports of this Volume.  # noqa: E501
        :rtype: MapOfPorts
        """
        return self._ports

    @ports.setter
    def ports(self, ports):
        """Sets the ports of this Volume.


        :param ports: The ports of this Volume.  # noqa: E501
        :type: MapOfPorts
        """

        self._ports = ports

    @property
    def src_vols(self):
        """Gets the src_vols of this Volume.  # noqa: E501


        :return: The src_vols of this Volume.  # noqa: E501
        :rtype: list[str]
        """
        return self._src_vols

    @src_vols.setter
    def src_vols(self, src_vols):
        """Sets the src_vols of this Volume.


        :param src_vols: The src_vols of this Volume.  # noqa: E501
        :type: list[str]
        """

        self._src_vols = src_vols

    @property
    def durability_scheme(self):
        """Gets the durability_scheme of this Volume.  # noqa: E501


        :return: The durability_scheme of this Volume.  # noqa: E501
        :rtype: str
        """
        return self._durability_scheme

    @durability_scheme.setter
    def durability_scheme(self, durability_scheme):
        """Sets the durability_scheme of this Volume.


        :param durability_scheme: The durability_scheme of this Volume.  # noqa: E501
        :type: str
        """

        self._durability_scheme = durability_scheme

    @property
    def stats(self):
        """Gets the stats of this Volume.  # noqa: E501


        :return: The stats of this Volume.  # noqa: E501
        :rtype: VolumeStats
        """
        return self._stats

    @stats.setter
    def stats(self, stats):
        """Sets the stats of this Volume.


        :param stats: The stats of this Volume.  # noqa: E501
        :type: VolumeStats
        """

        self._stats = stats

    @property
    def physical_capacity(self):
        """Gets the physical_capacity of this Volume.  # noqa: E501


        :return: The physical_capacity of this Volume.  # noqa: E501
        :rtype: int
        """
        return self._physical_capacity

    @physical_capacity.setter
    def physical_capacity(self, physical_capacity):
        """Sets the physical_capacity of this Volume.


        :param physical_capacity: The physical_capacity of this Volume.  # noqa: E501
        :type: int
        """
        if physical_capacity is None:
            raise ValueError("Invalid value for `physical_capacity`, must not be `None`")  # noqa: E501

        self._physical_capacity = physical_capacity

    @property
    def space_allocation_policy(self):
        """Gets the space_allocation_policy of this Volume.  # noqa: E501


        :return: The space_allocation_policy of this Volume.  # noqa: E501
        :rtype: SpaceAllocationPolicy
        """
        return self._space_allocation_policy

    @space_allocation_policy.setter
    def space_allocation_policy(self, space_allocation_policy):
        """Sets the space_allocation_policy of this Volume.


        :param space_allocation_policy: The space_allocation_policy of this Volume.  # noqa: E501
        :type: SpaceAllocationPolicy
        """

        self._space_allocation_policy = space_allocation_policy

    @property
    def additional_fields(self):
        """Gets the additional_fields of this Volume.  # noqa: E501


        :return: The additional_fields of this Volume.  # noqa: E501
        :rtype: AdditionalFields
        """
        return self._additional_fields

    @additional_fields.setter
    def additional_fields(self, additional_fields):
        """Sets the additional_fields of this Volume.


        :param additional_fields: The additional_fields of this Volume.  # noqa: E501
        :type: AdditionalFields
        """

        self._additional_fields = additional_fields

    @property
    def created_at(self):
        """Gets the created_at of this Volume.  # noqa: E501

        set on create  # noqa: E501

        :return: The created_at of this Volume.  # noqa: E501
        :rtype: datetime
        """
        return self._created_at

    @created_at.setter
    def created_at(self, created_at):
        """Sets the created_at of this Volume.

        set on create  # noqa: E501

        :param created_at: The created_at of this Volume.  # noqa: E501
        :type: datetime
        """

        self._created_at = created_at

    @property
    def modified_at(self):
        """Gets the modified_at of this Volume.  # noqa: E501

        set when modified  # noqa: E501

        :return: The modified_at of this Volume.  # noqa: E501
        :rtype: datetime
        """
        return self._modified_at

    @modified_at.setter
    def modified_at(self, modified_at):
        """Sets the modified_at of this Volume.

        set when modified  # noqa: E501

        :param modified_at: The modified_at of this Volume.  # noqa: E501
        :type: datetime
        """

        self._modified_at = modified_at

    @property
    def block_size(self):
        """Gets the block_size of this Volume.  # noqa: E501


        :return: The block_size of this Volume.  # noqa: E501
        :rtype: BlockSize
        """
        return self._block_size

    @block_size.setter
    def block_size(self, block_size):
        """Sets the block_size of this Volume.


        :param block_size: The block_size of this Volume.  # noqa: E501
        :type: BlockSize
        """

        self._block_size = block_size

    @property
    def operations(self):
        """Gets the operations of this Volume.  # noqa: E501

        The operations currently running  on this Volume  # noqa: E501

        :return: The operations of this Volume.  # noqa: E501
        :rtype: list[Operation]
        """
        return self._operations

    @operations.setter
    def operations(self, operations):
        """Sets the operations of this Volume.

        The operations currently running  on this Volume  # noqa: E501

        :param operations: The operations of this Volume.  # noqa: E501
        :type: list[Operation]
        """

        self._operations = operations

    @property
    def fault_domain_id(self):
        """Gets the fault_domain_id of this Volume.  # noqa: E501


        :return: The fault_domain_id of this Volume.  # noqa: E501
        :rtype: str
        """
        return self._fault_domain_id

    @fault_domain_id.setter
    def fault_domain_id(self, fault_domain_id):
        """Sets the fault_domain_id of this Volume.


        :param fault_domain_id: The fault_domain_id of this Volume.  # noqa: E501
        :type: str
        """

        self._fault_domain_id = fault_domain_id

    @property
    def volume_type(self):
        """Gets the volume_type of this Volume.  # noqa: E501


        :return: The volume_type of this Volume.  # noqa: E501
        :rtype: UserVolumeType
        """
        return self._volume_type

    @volume_type.setter
    def volume_type(self, volume_type):
        """Sets the volume_type of this Volume.


        :param volume_type: The volume_type of this Volume.  # noqa: E501
        :type: UserVolumeType
        """

        self._volume_type = volume_type

    def to_dict(self):
        """Returns the model properties as a dict"""
        result = {}

        for attr, _ in self.swagger_types.items():
            value = getattr(self, attr)
            if isinstance(value, list):
                result[attr] = list(map(
                    lambda x: x.to_dict() if hasattr(x, "to_dict") else x,
                    value
                ))
            elif hasattr(value, "to_dict"):
                result[attr] = value.to_dict()
            elif isinstance(value, dict):
                result[attr] = dict(map(
                    lambda item: (item[0], item[1].to_dict())
                    if hasattr(item[1], "to_dict") else item,
                    value.items()
                ))
            else:
                result[attr] = value
        if issubclass(Volume, dict):
            for key, value in self.items():
                result[key] = value

        return result

    def to_str(self):
        """Returns the string representation of the model"""
        return pprint.pformat(self.to_dict())

    def __repr__(self):
        """For `print` and `pprint`"""
        return self.to_str()

    def __eq__(self, other):
        """Returns true if both objects are equal"""
        if not isinstance(other, Volume):
            return False

        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        """Returns true if both objects are not equal"""
        return not self == other


class ZipEffort(object):
    """NOTE: This class is auto generated by the swagger code generator program

    Do not edit the class manually.
    """

    """
    allowed enum values
    """
    NONE = "ZIP_EFFORT_NONE"
    _64GBPS = "ZIP_EFFORT_64Gbps"
    _56GBPS = "ZIP_EFFORT_56Gbps"
    _30GBPS = "ZIP_EFFORT_30Gbps"
    _15GBPS = "ZIP_EFFORT_15Gbps"
    _7GBPS = "ZIP_EFFORT_7Gbps"
    _3GBPS = "ZIP_EFFORT_3Gbps"
    _2GBPS = "ZIP_EFFORT_2Gbps"
    AUTO = "ZIP_EFFORT_AUTO"

    """
    Attributes:
      swagger_types (dict): The key is attribute name
                            and the value is attribute type.
      attribute_map (dict): The key is attribute name
                            and the value is json key in definition.
    """
    swagger_types = {
    }

    attribute_map = {
    }

    def __init__(self):  # noqa: E501
        """ZipEffort - a model defined in Swagger"""  # noqa: E501
        self.discriminator = None

    def to_dict(self):
        """Returns the model properties as a dict"""
        result = {}

        for attr, _ in self.swagger_types.items():
            value = getattr(self, attr)
            if isinstance(value, list):
                result[attr] = list(map(
                    lambda x: x.to_dict() if hasattr(x, "to_dict") else x,
                    value
                ))
            elif hasattr(value, "to_dict"):
                result[attr] = value.to_dict()
            elif isinstance(value, dict):
                result[attr] = dict(map(
                    lambda item: (item[0], item[1].to_dict())
                    if hasattr(item[1], "to_dict") else item,
                    value.items()
                ))
            else:
                result[attr] = value
        if issubclass(ZipEffort, dict):
            for key, value in self.items():
                result[key] = value

        return result

    def to_str(self):
        """Returns the string representation of the model"""
        return pprint.pformat(self.to_dict())

    def __repr__(self):
        """For `print` and `pprint`"""
        return self.to_str()

    def __eq__(self, other):
        """Returns true if both objects are equal"""
        if not isinstance(other, ZipEffort):
            return False

        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        """Returns true if both objects are not equal"""
        return not self == other


class BodyCreateVolumeCopyTask(object):
    """This class is auto generated by the swagger code generator program

    Do not edit the class manually.
    """

    """
    Attributes:
      swagger_types (dict): The key is attribute name
                            and the value is attribute type.
      attribute_map (dict): The key is attribute name
                            and the value is json key in definition.
    """
    swagger_types = {
        'src_volume_uuid': 'str',
        'dest_volume_uuid': 'str',
        'num_threads': 'int',
        'timeout': 'int'
    }

    attribute_map = {
        'src_volume_uuid': 'src_volume_uuid',
        'dest_volume_uuid': 'dest_volume_uuid',
        'num_threads': 'num_threads',
        'timeout': 'timeout'
    }

    def __init__(self, src_volume_uuid=None, dest_volume_uuid=None, num_threads=None, timeout=None):  # noqa: E501
        """BodyCreateVolumeCopyTask - a model defined in Swagger"""  # noqa: E501

        self._src_volume_uuid = None
        self._dest_volume_uuid = None
        self._num_threads = None
        self._timeout = None
        self.discriminator = None

        if src_volume_uuid is not None:
            self.src_volume_uuid = src_volume_uuid
        if dest_volume_uuid is not None:
            self.dest_volume_uuid = dest_volume_uuid
        if num_threads is not None:
            self.num_threads = num_threads
        if timeout is not None:
            self.timeout = timeout

    @property
    def src_volume_uuid(self):
        """Gets the src_volume_uuid of this BodyCreateVolumeCopyTask.  # noqa: E501

        Source volume UUID  # noqa: E501

        :return: The src_volume_uuid of this BodyCreateVolumeCopyTask.  # noqa: E501
        :rtype: str
        """
        return self._src_volume_uuid

    @src_volume_uuid.setter
    def src_volume_uuid(self, src_volume_uuid):
        """Sets the src_volume_uuid of this BodyCreateVolumeCopyTask.

        Source volume UUID  # noqa: E501

        :param src_volume_uuid: The src_volume_uuid of this BodyCreateVolumeCopyTask.  # noqa: E501
        :type: str
        """

        self._src_volume_uuid = src_volume_uuid

    @property
    def dest_volume_uuid(self):
        """Gets the dest_volume_uuid of this BodyCreateVolumeCopyTask.  # noqa: E501

        Destination volume UUID  # noqa: E501

        :return: The dest_volume_uuid of this BodyCreateVolumeCopyTask.  # noqa: E501
        :rtype: str
        """
        return self._dest_volume_uuid

    @dest_volume_uuid.setter
    def dest_volume_uuid(self, dest_volume_uuid):
        """Sets the dest_volume_uuid of this BodyCreateVolumeCopyTask.

        Destination volume UUID  # noqa: E501

        :param dest_volume_uuid: The dest_volume_uuid of this BodyCreateVolumeCopyTask.  # noqa: E501
        :type: str
        """

        self._dest_volume_uuid = dest_volume_uuid

    @property
    def num_threads(self):
        """Gets the num_threads of this BodyCreateVolumeCopyTask.  # noqa: E501

        number of threads  # noqa: E501

        :return: The num_threads of this BodyCreateVolumeCopyTask.  # noqa: E501
        :rtype: int
        """
        return self._num_threads

    @num_threads.setter
    def num_threads(self, num_threads):
        """Sets the num_threads of this BodyCreateVolumeCopyTask.

        number of threads  # noqa: E501

        :param num_threads: The num_threads of this BodyCreateVolumeCopyTask.  # noqa: E501
        :type: int
        """
        if num_threads is not None and num_threads > 16:  # noqa: E501
            raise ValueError("Invalid value for `num_threads`, must be a value less than or equal to `16`")  # noqa: E501
        if num_threads is not None and num_threads < 1:  # noqa: E501
            raise ValueError("Invalid value for `num_threads`, must be a value greater than or equal to `1`")  # noqa: E501

        self._num_threads = num_threads

    @property
    def timeout(self):
        """Gets the timeout of this BodyCreateVolumeCopyTask.  # noqa: E501

        maximum duration in seconds  # noqa: E501

        :return: The timeout of this BodyCreateVolumeCopyTask.  # noqa: E501
        :rtype: int
        """
        return self._timeout

    @timeout.setter
    def timeout(self, timeout):
        """Sets the timeout of this BodyCreateVolumeCopyTask.

        maximum duration in seconds  # noqa: E501

        :param timeout: The timeout of this BodyCreateVolumeCopyTask.  # noqa: E501
        :type: int
        """
        if timeout is not None and timeout > 86400:  # noqa: E501
            raise ValueError("Invalid value for `timeout`, must be a value less than or equal to `86400`")  # noqa: E501
        if timeout is not None and timeout < 60:  # noqa: E501
            raise ValueError("Invalid value for `timeout`, must be a value greater than or equal to `60`")  # noqa: E501

        self._timeout = timeout

    def to_dict(self):
        """Returns the model properties as a dict"""
        result = {}

        for attr, _ in self.swagger_types.items():
            value = getattr(self, attr)
            if isinstance(value, list):
                result[attr] = list(map(
                    lambda x: x.to_dict() if hasattr(x, "to_dict") else x,
                    value
                ))
            elif hasattr(value, "to_dict"):
                result[attr] = value.to_dict()
            elif isinstance(value, dict):
                result[attr] = dict(map(
                    lambda item: (item[0], item[1].to_dict())
                    if hasattr(item[1], "to_dict") else item,
                    value.items()
                ))
            else:
                result[attr] = value
        if issubclass(BodyCreateVolumeCopyTask, dict):
            for key, value in self.items():
                result[key] = value

        return result

    def to_str(self):
        """Returns the string representation of the model"""
        return pprint.pformat(self.to_dict())

    def __repr__(self):
        """For `print` and `pprint`"""
        return self.to_str()

    def __eq__(self, other):
        """Returns true if both objects are equal"""
        if not isinstance(other, BodyCreateVolumeCopyTask):
            return False

        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        """Returns true if both objects are not equal"""
        return not self == other


class ResponseCreateVolumeCopyTask(object):
    """This class is auto generated by the swagger code generator program

    Do not edit the class manually.
    """

    """
    Attributes:
      swagger_types (dict): The key is attribute name
                            and the value is attribute type.
      attribute_map (dict): The key is attribute name
                            and the value is json key in definition.
    """
    swagger_types = {
        'status': 'bool',
        'message': 'str',
        'error_message': 'str',
        'warning': 'str',
        'data': 'VolumeCopyTask'
    }

    attribute_map = {
        'status': 'status',
        'message': 'message',
        'error_message': 'error_message',
        'warning': 'warning',
        'data': 'data'
    }

    def __init__(self, status=None, message=None, error_message=None, warning=None, data=None):  # noqa: E501
        """ResponseCreateVolumeCopyTask - a model defined in Swagger"""  # noqa: E501

        self._status = None
        self._message = None
        self._error_message = None
        self._warning = None
        self._data = None
        self.discriminator = None

        self.status = status
        if message is not None:
            self.message = message
        if error_message is not None:
            self.error_message = error_message
        if warning is not None:
            self.warning = warning
        if data is not None:
            self.data = data

    @property
    def status(self):
        """Gets the status of this ResponseCreateVolumeCopyTask.  # noqa: E501


        :return: The status of this ResponseCreateVolumeCopyTask.  # noqa: E501
        :rtype: bool
        """
        return self._status

    @status.setter
    def status(self, status):
        """Sets the status of this ResponseCreateVolumeCopyTask.


        :param status: The status of this ResponseCreateVolumeCopyTask.  # noqa: E501
        :type: bool
        """
        if status is None:
            raise ValueError("Invalid value for `status`, must not be `None`")  # noqa: E501

        self._status = status

    @property
    def message(self):
        """Gets the message of this ResponseCreateVolumeCopyTask.  # noqa: E501


        :return: The message of this ResponseCreateVolumeCopyTask.  # noqa: E501
        :rtype: str
        """
        return self._message

    @message.setter
    def message(self, message):
        """Sets the message of this ResponseCreateVolumeCopyTask.


        :param message: The message of this ResponseCreateVolumeCopyTask.  # noqa: E501
        :type: str
        """

        self._message = message

    @property
    def error_message(self):
        """Gets the error_message of this ResponseCreateVolumeCopyTask.  # noqa: E501


        :return: The error_message of this ResponseCreateVolumeCopyTask.  # noqa: E501
        :rtype: str
        """
        return self._error_message

    @error_message.setter
    def error_message(self, error_message):
        """Sets the error_message of this ResponseCreateVolumeCopyTask.


        :param error_message: The error_message of this ResponseCreateVolumeCopyTask.  # noqa: E501
        :type: str
        """

        self._error_message = error_message

    @property
    def warning(self):
        """Gets the warning of this ResponseCreateVolumeCopyTask.  # noqa: E501


        :return: The warning of this ResponseCreateVolumeCopyTask.  # noqa: E501
        :rtype: str
        """
        return self._warning

    @warning.setter
    def warning(self, warning):
        """Sets the warning of this ResponseCreateVolumeCopyTask.


        :param warning: The warning of this ResponseCreateVolumeCopyTask.  # noqa: E501
        :type: str
        """

        self._warning = warning

    @property
    def data(self):
        """Gets the data of this ResponseCreateVolumeCopyTask.  # noqa: E501


        :return: The data of this ResponseCreateVolumeCopyTask.  # noqa: E501
        :rtype: VolumeCopyTask
        """
        return self._data

    @data.setter
    def data(self, data):
        """Sets the data of this ResponseCreateVolumeCopyTask.


        :param data: The data of this ResponseCreateVolumeCopyTask.  # noqa: E501
        :type: VolumeCopyTask
        """

        self._data = data

    def to_dict(self):
        """Returns the model properties as a dict"""
        result = {}

        for attr, _ in self.swagger_types.items():
            value = getattr(self, attr)
            if isinstance(value, list):
                result[attr] = list(map(
                    lambda x: x.to_dict() if hasattr(x, "to_dict") else x,
                    value
                ))
            elif hasattr(value, "to_dict"):
                result[attr] = value.to_dict()
            elif isinstance(value, dict):
                result[attr] = dict(map(
                    lambda item: (item[0], item[1].to_dict())
                    if hasattr(item[1], "to_dict") else item,
                    value.items()
                ))
            else:
                result[attr] = value
        if issubclass(ResponseCreateVolumeCopyTask, dict):
            for key, value in self.items():
                result[key] = value

        return result

    def to_str(self):
        """Returns the string representation of the model"""
        return pprint.pformat(self.to_dict())

    def __repr__(self):
        """For `print` and `pprint`"""
        return self.to_str()

    def __eq__(self, other):
        """Returns true if both objects are equal"""
        if not isinstance(other, ResponseCreateVolumeCopyTask):
            return False

        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        """Returns true if both objects are not equal"""
        return not self == other


class ResponseGetVolumeCopyTask(object):
    """NOTE: This class is auto generated by the swagger code generator program

    Do not edit the class manually.
    """

    """
    Attributes:
      swagger_types (dict): The key is attribute name
                            and the value is attribute type.
      attribute_map (dict): The key is attribute name
                            and the value is json key in definition.
    """
    swagger_types = {
        'status': 'bool',
        'message': 'str',
        'error_message': 'str',
        'warning': 'str',
        'data': 'DataWithCopyTaskData'
    }

    attribute_map = {
        'status': 'status',
        'message': 'message',
        'error_message': 'error_message',
        'warning': 'warning',
        'data': 'data'
    }

    def __init__(self, status=None, message=None, error_message=None, warning=None, data=None):  # noqa: E501
        """ResponseGetVolumeCopyTask - a model defined in Swagger"""  # noqa: E501

        self._status = None
        self._message = None
        self._error_message = None
        self._warning = None
        self._data = None
        self.discriminator = None

        self.status = status
        if message is not None:
            self.message = message
        if error_message is not None:
            self.error_message = error_message
        if warning is not None:
            self.warning = warning
        if data is not None:
            self.data = data

    @property
    def status(self):
        """Gets the status of this ResponseGetVolumeCopyTask.  # noqa: E501


        :return: The status of this ResponseGetVolumeCopyTask.  # noqa: E501
        :rtype: bool
        """
        return self._status

    @status.setter
    def status(self, status):
        """Sets the status of this ResponseGetVolumeCopyTask.


        :param status: The status of this ResponseGetVolumeCopyTask.  # noqa: E501
        :type: bool
        """
        if status is None:
            raise ValueError("Invalid value for `status`, must not be `None`")  # noqa: E501

        self._status = status

    @property
    def message(self):
        """Gets the message of this ResponseGetVolumeCopyTask.  # noqa: E501


        :return: The message of this ResponseGetVolumeCopyTask.  # noqa: E501
        :rtype: str
        """
        return self._message

    @message.setter
    def message(self, message):
        """Sets the message of this ResponseGetVolumeCopyTask.


        :param message: The message of this ResponseGetVolumeCopyTask.  # noqa: E501
        :type: str
        """

        self._message = message

    @property
    def error_message(self):
        """Gets the error_message of this ResponseGetVolumeCopyTask.  # noqa: E501


        :return: The error_message of this ResponseGetVolumeCopyTask.  # noqa: E501
        :rtype: str
        """
        return self._error_message

    @error_message.setter
    def error_message(self, error_message):
        """Sets the error_message of this ResponseGetVolumeCopyTask.


        :param error_message: The error_message of this ResponseGetVolumeCopyTask.  # noqa: E501
        :type: str
        """

        self._error_message = error_message

    @property
    def warning(self):
        """Gets the warning of this ResponseGetVolumeCopyTask.  # noqa: E501


        :return: The warning of this ResponseGetVolumeCopyTask.  # noqa: E501
        :rtype: str
        """
        return self._warning

    @warning.setter
    def warning(self, warning):
        """Sets the warning of this ResponseGetVolumeCopyTask.


        :param warning: The warning of this ResponseGetVolumeCopyTask.  # noqa: E501
        :type: str
        """

        self._warning = warning

    @property
    def data(self):
        """Gets the data of this ResponseGetVolumeCopyTask.  # noqa: E501


        :return: The data of this ResponseGetVolumeCopyTask.  # noqa: E501
        :rtype: DataWithCopyTaskData
        """
        return self._data

    @data.setter
    def data(self, data):
        """Sets the data of this ResponseGetVolumeCopyTask.


        :param data: The data of this ResponseGetVolumeCopyTask.  # noqa: E501
        :type: DataWithCopyTaskData
        """

        self._data = data

    def to_dict(self):
        """Returns the model properties as a dict"""
        result = {}

        for attr, _ in self.swagger_types.items():
            value = getattr(self, attr)
            if isinstance(value, list):
                result[attr] = list(map(
                    lambda x: x.to_dict() if hasattr(x, "to_dict") else x,
                    value
                ))
            elif hasattr(value, "to_dict"):
                result[attr] = value.to_dict()
            elif isinstance(value, dict):
                result[attr] = dict(map(
                    lambda item: (item[0], item[1].to_dict())
                    if hasattr(item[1], "to_dict") else item,
                    value.items()
                ))
            else:
                result[attr] = value
        if issubclass(ResponseGetVolumeCopyTask, dict):
            for key, value in self.items():
                result[key] = value

        return result

    def to_str(self):
        """Returns the string representation of the model"""
        return pprint.pformat(self.to_dict())

    def __repr__(self):
        """For `print` and `pprint`"""
        return self.to_str()

    def __eq__(self, other):
        """Returns true if both objects are equal"""
        if not isinstance(other, ResponseGetVolumeCopyTask):
            return False

        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        """Returns true if both objects are not equal"""
        return not self == other


class VolumeCopyTask(object):
    """NOTE: This class is auto generated by the swagger code generator program

    Do not edit the class manually.
    """

    """
    Attributes:
      swagger_types (dict): The key is attribute name
                            and the value is attribute type.
      attribute_map (dict): The key is attribute name
                            and the value is json key in definition.
    """
    swagger_types = {
        'task_uuid': 'str'
    }

    attribute_map = {
        'task_uuid': 'task_uuid'
    }

    def __init__(self, task_uuid=None):  # noqa: E501
        """VolumeCopyTask - a model defined in Swagger"""  # noqa: E501

        self._task_uuid = None
        self.discriminator = None

        if task_uuid is not None:
            self.task_uuid = task_uuid

    @property
    def task_uuid(self):
        """Gets the task_uuid of this VolumeCopyTask.  # noqa: E501

        Volume copy task UUID  # noqa: E501

        :return: The task_uuid of this VolumeCopyTask.  # noqa: E501
        :rtype: str
        """
        return self._task_uuid

    @task_uuid.setter
    def task_uuid(self, task_uuid):
        """Sets the task_uuid of this VolumeCopyTask.

        Volume copy task UUID  # noqa: E501

        :param task_uuid: The task_uuid of this VolumeCopyTask.  # noqa: E501
        :type: str
        """

        self._task_uuid = task_uuid

    def to_dict(self):
        """Returns the model properties as a dict"""
        result = {}

        for attr, _ in self.swagger_types.items():
            value = getattr(self, attr)
            if isinstance(value, list):
                result[attr] = list(map(
                    lambda x: x.to_dict() if hasattr(x, "to_dict") else x,
                    value
                ))
            elif hasattr(value, "to_dict"):
                result[attr] = value.to_dict()
            elif isinstance(value, dict):
                result[attr] = dict(map(
                    lambda item: (item[0], item[1].to_dict())
                    if hasattr(item[1], "to_dict") else item,
                    value.items()
                ))
            else:
                result[attr] = value
        if issubclass(VolumeCopyTask, dict):
            for key, value in self.items():
                result[key] = value

        return result

    def to_str(self):
        """Returns the string representation of the model"""
        return pprint.pformat(self.to_dict())

    def __repr__(self):
        """For `print` and `pprint`"""
        return self.to_str()

    def __eq__(self, other):
        """Returns true if both objects are equal"""
        if not isinstance(other, VolumeCopyTask):
            return False

        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        """Returns true if both objects are not equal"""
        return not self == other


class DataWithUuidStringData(object):
    """NOTE: This class is auto generated by the swagger code generator program

    Do not edit the class manually.
    """

    """
    Attributes:
      swagger_types (dict): The key is attribute name
                            and the value is attribute type.
      attribute_map (dict): The key is attribute name
                            and the value is json key in definition.
    """
    swagger_types = {
        'uuid': 'str'
    }

    attribute_map = {
        'uuid': 'uuid'
    }

    def __init__(self, uuid=None):  # noqa: E501
        """DataWithUuidStringData - a model defined in Swagger"""  # noqa: E501

        self._uuid = None
        self.discriminator = None

        self.uuid = uuid

    @property
    def uuid(self):
        """Gets the uuid of this DataWithUuidStringData.  # noqa: E501


        :return: The uuid of this DataWithUuidStringData.  # noqa: E501
        :rtype: str
        """
        return self._uuid

    @uuid.setter
    def uuid(self, uuid):
        """Sets the uuid of this DataWithUuidStringData.


        :param uuid: The uuid of this DataWithUuidStringData.  # noqa: E501
        :type: str
        """
        if uuid is None:
            raise ValueError("Invalid value for `uuid`, must not be `None`")  # noqa: E501

        self._uuid = uuid

    def to_dict(self):
        """Returns the model properties as a dict"""
        result = {}

        for attr, _ in self.swagger_types.items():
            value = getattr(self, attr)
            if isinstance(value, list):
                result[attr] = list(map(
                    lambda x: x.to_dict() if hasattr(x, "to_dict") else x,
                    value
                ))
            elif hasattr(value, "to_dict"):
                result[attr] = value.to_dict()
            elif isinstance(value, dict):
                result[attr] = dict(map(
                    lambda item: (item[0], item[1].to_dict())
                    if hasattr(item[1], "to_dict") else item,
                    value.items()
                ))
            else:
                result[attr] = value
        if issubclass(DataWithUuidStringData, dict):
            for key, value in self.items():
                result[key] = value

        return result

    def to_str(self):
        """Returns the string representation of the model"""
        return pprint.pformat(self.to_dict())

    def __repr__(self):
        """For `print` and `pprint`"""
        return self.to_str()

    def __eq__(self, other):
        """Returns true if both objects are equal"""
        if not isinstance(other, DataWithUuidStringData):
            return False

        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        """Returns true if both objects are not equal"""
        return not self == other


class DataWithCopyTaskData(object):
    """NOTE: This class is auto generated by the swagger code generator program

    Do not edit the class manually.
    """

    """
    Attributes:
      swagger_types (dict): The key is attribute name
                            and the value is attribute type.
      attribute_map (dict): The key is attribute name
                            and the value is json key in definition.
    """
    swagger_types = {
        'task_state': 'str',
        'completion_pct': 'str'
    }

    attribute_map = {
        'task_state': 'task_state',
        'completion_pct': 'Completion_pct'
    }

    def __init__(self, task_state=None, completion_pct=None):  # noqa: E501
        """DataWithCopyTaskData - a model defined in Swagger"""  # noqa: E501

        self._task_state = None
        self._completion_pct = None
        self.discriminator = None

        if task_state is not None:
            self.task_state = task_state
        if completion_pct is not None:
            self.completion_pct = completion_pct

    @property
    def task_state(self):
        """Gets the task_state of this DataWithCopyTaskData.  # noqa: E501

        Status of the volume copy task (RUNNING, SUCCES or FAILED)  # noqa: E501

        :return: The task_state of this DataWithCopyTaskData.  # noqa: E501
        :rtype: str
        """
        return self._task_state

    @task_state.setter
    def task_state(self, task_state):
        """Sets the task_state of this DataWithCopyTaskData.

        Status of the volume copy task (RUNNING, SUCCES or FAILED)  # noqa: E501

        :param task_state: The task_state of this DataWithCopyTaskData.  # noqa: E501
        :type: str
        """
        allowed_values = ["RUNNING", "SUCCESS", "FAILED"]  # noqa: E501
        if task_state not in allowed_values:
            raise ValueError(
                "Invalid value for `task_state` ({0}), must be one of {1}"  # noqa: E501
                .format(task_state, allowed_values)
            )

        self._task_state = task_state

    @property
    def completion_pct(self):
        """Gets the completion_pct of this DataWithCopyTaskData.  # noqa: E501

        Percent complete (0-100)  # noqa: E501

        :return: The completion_pct of this DataWithCopyTaskData.  # noqa: E501
        :rtype: str
        """
        return self._completion_pct

    @completion_pct.setter
    def completion_pct(self, completion_pct):
        """Sets the completion_pct of this DataWithCopyTaskData.

        Percent complete (0-100)  # noqa: E501

        :param completion_pct: The completion_pct of this DataWithCopyTaskData.  # noqa: E501
        :type: str
        """

        self._completion_pct = completion_pct

    def to_dict(self):
        """Returns the model properties as a dict"""
        result = {}

        for attr, _ in self.swagger_types.items():
            value = getattr(self, attr)
            if isinstance(value, list):
                result[attr] = list(map(
                    lambda x: x.to_dict() if hasattr(x, "to_dict") else x,
                    value
                ))
            elif hasattr(value, "to_dict"):
                result[attr] = value.to_dict()
            elif isinstance(value, dict):
                result[attr] = dict(map(
                    lambda item: (item[0], item[1].to_dict())
                    if hasattr(item[1], "to_dict") else item,
                    value.items()
                ))
            else:
                result[attr] = value
        if issubclass(DataWithCopyTaskData, dict):
            for key, value in self.items():
                result[key] = value

        return result

    def to_str(self):
        """Returns the string representation of the model"""
        return pprint.pformat(self.to_dict())

    def __repr__(self):
        """For `print` and `pprint`"""
        return self.to_str()

    def __eq__(self, other):
        """Returns true if both objects are equal"""
        if not isinstance(other, DataWithCopyTaskData):
            return False

        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        """Returns true if both objects are not equal"""
        return not self == other
