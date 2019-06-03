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
#
"""Fake client exceptions to use."""


class UnsupportedVersion(Exception):
    """Unsupported version of the client."""
    pass


class ClientException(Exception):
    """The base exception class for these fake exceptions."""
    _error_code = None
    _error_desc = None
    _error_ref = None

    _debug1 = None
    _debug2 = None

    def __init__(self, error=None):
        if error:
            if 'code' in error:
                self._error_code = error['code']
            if 'desc' in error:
                self._error_desc = error['desc']
            if 'ref' in error:
                self._error_ref = error['ref']

            if 'debug1' in error:
                self._debug1 = error['debug1']
            if 'debug2' in error:
                self._debug2 = error['debug2']

    def get_code(self):
        return self._error_code

    def get_description(self):
        return self._error_desc

    def get_ref(self):
        return self._error_ref

    def __str__(self):
        formatted_string = self.message
        if self.http_status:
            formatted_string += " (HTTP %s)" % self.http_status
        if self._error_code:
            formatted_string += " %s" % self._error_code
        if self._error_desc:
            formatted_string += " - %s" % self._error_desc
        if self._error_ref:
            formatted_string += " - %s" % self._error_ref

        if self._debug1:
            formatted_string += " (1: '%s')" % self._debug1

        if self._debug2:
            formatted_string += " (2: '%s')" % self._debug2

        return formatted_string


class HTTPConflict(ClientException):
    http_status = 409
    message = "Conflict"

    def __init__(self, error=None):
        if error:
            super(HTTPConflict, self).__init__(error)
            if 'message' in error:
                self._error_desc = error['message']

    def get_description(self):
        return self._error_desc


class HTTPNotFound(ClientException):
    http_status = 404
    message = "Not found"


class HTTPForbidden(ClientException):
    http_status = 403
    message = "Forbidden"


class HTTPBadRequest(ClientException):
    http_status = 400
    message = "Bad request"


class HTTPUnauthorized(ClientException):
    http_status = 401
    message = "Unauthorized"


class HTTPServerError(ClientException):
    http_status = 500
    message = "Error"

    def __init__(self, error=None):
        if error and 'message' in error:
            self._error_desc = error['message']

    def get_description(self):
        return self._error_desc
