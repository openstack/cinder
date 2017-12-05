# Copyright (c) 2017 DataCore Software Corp. All Rights Reserved.
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

"""Exception definitions."""

from cinder import exception
from cinder.i18n import _


class DataCoreException(exception.VolumeBackendAPIException):
    """Base DataCore Exception."""

    message = _('DataCore exception.')


class DataCoreConnectionException(DataCoreException):
    """Thrown when there are connection problems during a DataCore API call."""

    message = _('Failed to connect to DataCore Server Group: %(reason)s.')


class DataCoreFaultException(DataCoreException):
    """Thrown when there are faults during a DataCore API call."""

    message = _('DataCore Server Group reported an error: %(reason)s.')
