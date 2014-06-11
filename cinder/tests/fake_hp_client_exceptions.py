# (c) Copyright 2014 Hewlett-Packard Development Company, L.P.
#    All Rights Reserved.
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
#
"""Fake HP client exceptions to use when mocking HP clients."""


class HTTPConflict(Exception):
    http_status = 409
    message = "Conflict"

    def __init__(self, error=None):
        if error and 'message' in error:
            self._error_desc = error['message']

    def get_description(self):
        return self._error_desc


class HTTPNotFound(Exception):
    http_status = 404
    message = "Not found"


class HTTPForbidden(Exception):
    http_status = 403
    message = "Forbidden"

    def __init__(self, error=None):
        if error and 'code' in error:
            self._error_code = error['code']

    def get_code(self):
        return self._error_code


class HTTPBadRequest(Exception):
    http_status = 400
    message = "Bad request"


class HTTPServerError(Exception):
    http_status = 500
    message = "Error"

    def __init__(self, error=None):
        if error and 'message' in error:
            self._error_desc = error['message']

    def get_description(self):
        return self._error_desc
