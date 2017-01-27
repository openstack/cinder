# Copyright (c) 2016 EMC Corporation
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.


try:
    import cookielib as cookie_lib
except ImportError:
    import http.cookiejar as cookie_lib
import socket

import requests
from requests import exceptions
import six
from six.moves import http_client

from cinder.i18n import _
from cinder.volume.drivers.coprhd.helpers import commoncoprhdapi as common


class Authentication(common.CoprHDResource):

    # Commonly used URIs for the 'Authentication' module
    URI_SERVICES_BASE = ''
    URI_AUTHENTICATION = '/login'

    HEADERS = {'Content-Type': 'application/json',
               'ACCEPT': 'application/json', 'X-EMC-REST-CLIENT': 'TRUE'}

    def authenticate_user(self, username, password):
        """Makes REST API call to generate the authentication token.

        Authentication token is generated for the specified user after
        validation

        :param username: Name of the user
        :param password: Password for the user
        :returns: The authtoken
        """

        SEC_REDIRECT = 302
        SEC_AUTHTOKEN_HEADER = 'X-SDS-AUTH-TOKEN'
        LB_API_PORT = 4443
        # Port on which load-balancer/reverse-proxy listens to all incoming
        # requests for CoprHD REST APIs
        APISVC_PORT = 8443  # Port on which apisvc listens to incoming requests

        cookiejar = cookie_lib.LWPCookieJar()

        url = ('https://%(ip)s:%(port)d%(uri)s' %
               {'ip': self.ipaddr, 'port': self.port,
                'uri': self.URI_AUTHENTICATION})

        try:
            if self.port == APISVC_PORT:
                login_response = requests.get(
                    url, headers=self.HEADERS, verify=False,
                    auth=(username, password), cookies=cookiejar,
                    allow_redirects=False, timeout=common.TIMEOUT_SEC)
                if login_response.status_code == SEC_REDIRECT:
                    location = login_response.headers['Location']
                    if not location:
                        raise common.CoprHdError(
                            common.CoprHdError.HTTP_ERR, (_("The redirect"
                                                            " location of the"
                                                            " authentication"
                                                            " service is not"
                                                            " provided")))
                    # Make the second request
                    login_response = requests.get(
                        location, headers=self.HEADERS, verify=False,
                        cookies=cookiejar, allow_redirects=False,
                        timeout=common.TIMEOUT_SEC)
                    if (login_response.status_code !=
                            http_client.UNAUTHORIZED):
                        raise common.CoprHdError(
                            common.CoprHdError.HTTP_ERR, (_("The"
                                                            " authentication"
                                                            " service failed"
                                                            " to reply with"
                                                            " 401")))

                    # Now provide the credentials
                    login_response = requests.get(
                        location, headers=self.HEADERS,
                        auth=(username, password), verify=False,
                        cookies=cookiejar, allow_redirects=False,
                        timeout=common.TIMEOUT_SEC)
                    if login_response.status_code != SEC_REDIRECT:
                        raise common.CoprHdError(
                            common.CoprHdError.HTTP_ERR,
                            (_("Access forbidden: Authentication required")))
                    location = login_response.headers['Location']
                    if not location:
                        raise common.CoprHdError(
                            common.CoprHdError.HTTP_ERR,
                            (_("The"
                               " authentication service failed to provide the"
                               " location of the service URI when redirecting"
                               " back")))
                    authtoken = login_response.headers[SEC_AUTHTOKEN_HEADER]
                    if not authtoken:
                        details_str = self.extract_error_detail(login_response)
                        raise common.CoprHdError(common.CoprHdError.HTTP_ERR,
                                                 (_("The token is not"
                                                    " generated by"
                                                    " authentication service."
                                                    "%s") %
                                                  details_str))
                    # Make the final call to get the page with the token
                    new_headers = self.HEADERS
                    new_headers[SEC_AUTHTOKEN_HEADER] = authtoken
                    login_response = requests.get(
                        location, headers=new_headers, verify=False,
                        cookies=cookiejar, allow_redirects=False,
                        timeout=common.TIMEOUT_SEC)
                    if login_response.status_code != http_client.OK:
                        raise common.CoprHdError(
                            common.CoprHdError.HTTP_ERR, (_(
                                "Login failure code: "
                                "%(statuscode)s Error: %(responsetext)s") %
                                {'statuscode': six.text_type(
                                    login_response.status_code),
                                 'responsetext': login_response.text}))
            elif self.port == LB_API_PORT:
                login_response = requests.get(
                    url, headers=self.HEADERS, verify=False,
                    cookies=cookiejar, allow_redirects=False)

                if(login_response.status_code ==
                   http_client.UNAUTHORIZED):
                    # Now provide the credentials
                    login_response = requests.get(
                        url, headers=self.HEADERS, auth=(username, password),
                        verify=False, cookies=cookiejar, allow_redirects=False)
                authtoken = None
                if SEC_AUTHTOKEN_HEADER in login_response.headers:
                    authtoken = login_response.headers[SEC_AUTHTOKEN_HEADER]
            else:
                raise common.CoprHdError(
                    common.CoprHdError.HTTP_ERR,
                    (_("Incorrect port number. Load balanced port is: "
                       "%(lb_api_port)s, api service port is: "
                       "%(apisvc_port)s") %
                     {'lb_api_port': LB_API_PORT,
                        'apisvc_port': APISVC_PORT}))

            if not authtoken:
                details_str = self.extract_error_detail(login_response)
                raise common.CoprHdError(
                    common.CoprHdError.HTTP_ERR,
                    (_("The token is not generated by authentication service."
                       " %s") % details_str))

            if login_response.status_code != http_client.OK:
                error_msg = None
                if login_response.status_code == http_client.UNAUTHORIZED:
                    error_msg = _("Access forbidden: Authentication required")
                elif login_response.status_code == http_client.FORBIDDEN:
                    error_msg = _("Access forbidden: You don't have"
                                  " sufficient privileges to perform"
                                  " this operation")
                elif (login_response.status_code ==
                        http_client.INTERNAL_SERVER_ERROR):
                    error_msg = _("Bourne internal server error")
                elif login_response.status_code == http_client.NOT_FOUND:
                    error_msg = _(
                        "Requested resource is currently unavailable")
                elif (login_response.status_code ==
                        http_client.METHOD_NOT_ALLOWED):
                    error_msg = (_("GET method is not supported by resource:"
                                   " %s"),
                                 url)
                elif (login_response.status_code ==
                        http_client.SERVICE_UNAVAILABLE):
                    error_msg = _("Service temporarily unavailable:"
                                  " The server is temporarily unable"
                                  " to service your request")
                else:
                    error_msg = login_response.text
                raise common.CoprHdError(common.CoprHdError.HTTP_ERR,
                                         (_("HTTP code: %(status_code)s"
                                            ", response: %(reason)s"
                                            " [%(error_msg)s]") % {
                                             'status_code': six.text_type(
                                                 login_response.status_code),
                                             'reason': six.text_type(
                                                 login_response.reason),
                                             'error_msg': six.text_type(
                                                 error_msg)
                                         }))
        except (exceptions.SSLError, socket.error, exceptions.ConnectionError,
                exceptions.Timeout) as e:
            raise common.CoprHdError(
                common.CoprHdError.HTTP_ERR, six.text_type(e))

        return authtoken

    def extract_error_detail(self, login_response):
        details_str = ""
        try:
            if login_response.content:
                json_object = common.json_decode(login_response.content)
                if 'details' in json_object:
                    details_str = json_object['details']

            return details_str
        except common.CoprHdError:
            return details_str
