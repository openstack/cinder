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
Exception classes and SOAP response error checking module.
"""

from cinder import exception

NOT_AUTHENTICATED = 'NotAuthenticated'


class VimException(exception.CinderException):
    """The VIM Exception class."""

    def __init__(self, msg):
        exception.CinderException.__init__(self, msg)


class SessionOverLoadException(VimException):
    """Session Overload Exception."""
    pass


class VimAttributeException(VimException):
    """VI Attribute Error."""
    pass


class VimFaultException(exception.VolumeBackendAPIException):
    """The VIM Fault exception class."""

    def __init__(self, fault_list, msg):
        exception.VolumeBackendAPIException.__init__(self, msg)
        self.fault_list = fault_list
