# Copyright 2014 IBM Corp.
# Copyright 2015 Clinton Knight
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

import re

from cinder.api.openstack import versioned_method
from cinder import exception
from cinder.i18n import _
from cinder import utils

# Define the minimum and maximum version of the API across all of the
# REST API. The format of the version is:
# X.Y where:
#
# - X will only be changed if a significant backwards incompatible API
# change is made which affects the API as whole. That is, something
# that is only very very rarely incremented.
#
# - Y when you make any change to the API. Note that this includes
# semantic changes which may not affect the input or output formats or
# even originate in the API code layer. We are not distinguishing
# between backwards compatible and backwards incompatible changes in
# the versioning system. It must be made clear in the documentation as
# to what is a backwards compatible change and what is a backwards
# incompatible one.

#
# You must update the API version history string below with a one or
# two line description as well as update rest_api_version_history.rst
REST_API_VERSION_HISTORY = """

    REST API Version History:

    * 3.0 - Includes all V2 APIs and extensions. V1 API is still supported.
    * 3.0 - Versions API updated to reflect beginning of microversions epoch.
    * 3.1 - Adds visibility and protected to _volume_upload_image parameters.
    * 3.2 - Bootable filters in volume GET call no longer treats all values
            passed to it as true.
    * 3.3 - Add user messages APIs.
    * 3.4 - Adds glance_metadata filter to list/detail volumes in _get_volumes.
    * 3.5 - Add pagination support to messages API.
    * 3.6 - Allows to set empty description and empty name for consistency
            group in consisgroup-update operation.
    * 3.7 - Add cluster API and cluster_name field to service list API
    * 3.8 - Adds resources from volume_manage and snapshot_manage extensions.
    * 3.9 - Add backup update interface.
    * 3.10 - Add group_id filter to list/detail volumes in _get_volumes.
    * 3.11 - Add group types and group specs API.
    * 3.12 - Add volumes summary API.
    * 3.13 - Add generic volume groups API.
    * 3.14 - Add group snapshot and create group from src APIs.
    * 3.15 - Inject the response's `Etag` header to avoid the lost update
             problem with volume metadata.
    * 3.16 - Migrate volume now supports cluster
    * 3.17 - Getting manageable volumes and snapshots now accepts cluster.
    * 3.18 - Add backup project attribute.
    * 3.19 - Add API reset status actions 'reset_status' to group snapshot.
    * 3.20 - Add API reset status actions 'reset_status' to generic
             volume group.
    * 3.21 - Show provider_id in detailed view of a volume for admin.
    * 3.22 - Add filtering based on metadata for snapshot listing.
    * 3.23 - Allow passing force parameter to volume delete.
    * 3.24 - Add workers/cleanup endpoint.
    * 3.25 - Add ``volumes`` field to group list/detail and group show.
    * 3.26 - Add failover action and cluster listings accept new filters and
             return new data.
    * 3.27 - Add attachment API
    * 3.28 - Add filters support to get_pools
    * 3.29 - Add filter, sorter and pagination support in group snapshot.
    * 3.30 - Support sort snapshots with "name".
    * 3.31 - Add support for configure resource query filters.
    * 3.32 - Add set-log and get-log service actions.
    * 3.33 - Add ``resource_filters`` API to retrieve configured
             resource filters.
    * 3.34 - Add like filter support in ``volume``, ``backup``, ``snapshot``,
             ``message``, ``attachment``, ``group`` and ``group-snapshot``
             list APIs.
    * 3.35 - Add ``volume-type`` filter to Get-Pools API.
    * 3.36 - Add metadata to volumes/summary response body.
    * 3.37 - Support sort backup by "name".
    * 3.38 - Add replication group API (Tiramisu).
    * 3.39 - Add ``project_id`` admin filters support to limits.
    * 3.40 - Add volume revert to its latest snapshot support.
    * 3.41 - Add ``user_id`` field to snapshot list/detail and snapshot show.
    * 3.42 - Add ability to extend 'in-use' volume. User should be aware of the
             whole environment before using this feature because it's dependent
             on several external factors below:
             1. nova-compute version - needs to be the latest for Pike.
             2. only the libvirt compute driver supports this currently.
             3. only iscsi and fibre channel volume types are supported
                on the nova side currently.
             Administrator can disable this ability by updating the
             'volume:extend_attached_volume' policy rule. Extend in reserved
             state is intentionally NOT allowed.
    * 3.43 - Support backup CRUD with metadata.
    * 3.44 - Add attachment-complete.
    * 3.45 - Add ``count`` field to volume, backup and snapshot list and
             detail APIs.
    * 3.46 - Support create volume by Nova specific image (0 size image).
    * 3.47 - Support create volume from backup.
    * 3.48 - Add ``shared_targets`` and ``service_uuid`` fields to volume.
    * 3.49 - Support report backend storage state in service list.
    * 3.50 - Add multiattach capability
    * 3.51 - Add support for cross AZ backups.
    * 3.52 - ``RESKEY:availability_zones`` is a reserved spec key for AZ
             volume type, and filter volume type by ``extra_specs`` is
             supported now.
    * 3.53 - Add schema validation support for request body using jsonschema
             for V2/V3 volume APIs.
             1. Modified create volume API to accept only parameters which are
             documented in the api-ref otherwise it will return 400 error.
             2. Update volume API expects user to pass at least one valid
             parameter in the request body in order to update the volume.
             Also, additional parameters will not be allowed.
    * 3.54 - Add ``mode`` argument to attachment-create.
    * 3.55 - Support transfer volume with snapshots
    * 3.56 - Add ``user_id`` attribute to response body of list backup with
             detail and show backup detail APIs.
    * 3.57 - Add 'source_project_id', 'destination_project_id', 'accepted' to
             transfer.
    * 3.58 - Add ``project_id`` attribute to response body of list groups with
             detail, list group snapshots with detail, show group detail and
             show group snapshot detail APIs.
    * 3.59 - Support volume transfer pagination.
    * 3.60 - Support filtering on the "updated_at" and "created_at" fields with
             time comparison operators for the volume summary list
             ("GET /v3/{project_id}/volumes") and volume detail list
             ("GET /v3/{project_id}/volumes/detail") requests.
    * 3.61 - Add ``cluster_name`` attribute to response body of volume details
             for admin.
    * 3.62 - Default volume type overrides
    * 3.63 - Include volume type ID in the volume details JSON response. Before
             this microversion (MV), Cinder returns only the volume type name
             in the volume details. This MV affects the volume detail list
             ("GET /v3/{project_id}/volumes/detail") and volume-show
             ("GET /v3/{project_id}/volumes/{volume_id}") calls.
    * 3.64 - Include 'encryption_key_id' in volume and backup details
    * 3.65 - Include 'consumes_quota' in volume and snapshot details
           - Accept 'consumes_quota' filter in volume and snapshot list
             operation.
    * 3.66 - Allow snapshotting in-use volumes without force flag.
"""

# The minimum and maximum versions of the API supported
# The default api version request is defined to be the
# minimum version of the API supported.
_MIN_API_VERSION = "3.0"
_MAX_API_VERSION = "3.66"
UPDATED = "2021-09-16T00:00:00Z"


# NOTE(cyeoh): min and max versions declared as functions so we can
# mock them for unittests. Do not use the constants directly anywhere
# else.
def min_api_version():
    return APIVersionRequest(_MIN_API_VERSION)


def max_api_version():
    return APIVersionRequest(_MAX_API_VERSION)


class APIVersionRequest(utils.ComparableMixin):
    """This class represents an API Version Request.

    This class includes convenience methods for manipulation
    and comparison of version numbers as needed to implement
    API microversions.
    """

    def __init__(self, version_string=None, experimental=False):
        """Create an API version request object."""
        self._ver_major = None
        self._ver_minor = None

        if version_string is not None:
            match = re.match(r"^([1-9]\d*)\.([1-9]\d*|0)$",
                             version_string)
            if match:
                self._ver_major = int(match.group(1))
                self._ver_minor = int(match.group(2))
            else:
                raise exception.InvalidAPIVersionString(version=version_string)

    def __str__(self):
        """Debug/Logging representation of object."""
        return ("API Version Request Major: %(major)s, Minor: %(minor)s"
                % {'major': self._ver_major, 'minor': self._ver_minor})

    def __bool__(self):
        return (self._ver_major or self._ver_minor) is not None

    __nonzero__ = __bool__

    def _cmpkey(self):
        """Return the value used by ComparableMixin for rich comparisons."""
        return self._ver_major, self._ver_minor

    def matches_versioned_method(self, method):
        """Compares this version to that of a versioned method."""

        if type(method) != versioned_method.VersionedMethod:
            msg = _('An API version request must be compared '
                    'to a VersionedMethod object.')
            raise exception.InvalidParameterValue(err=msg)

        return self.matches(method.start_version,
                            method.end_version,
                            method.experimental)

    def matches(self, min_version, max_version=None, experimental=False):
        """Compares this version to the specified min/max range.

        Returns whether the version object represents a version
        greater than or equal to the minimum version and less than
        or equal to the maximum version.

        If min_version is null then there is no minimum limit.
        If max_version is null then there is no maximum limit.
        If self is null then raise ValueError.

        :param min_version: Minimum acceptable version.
        :param max_version: Maximum acceptable version.
        :param experimental: Whether to match experimental APIs.
        :returns: boolean
        """

        if not self:
            raise ValueError

        if isinstance(min_version, str):
            min_version = APIVersionRequest(version_string=min_version)
        if isinstance(max_version, str):
            max_version = APIVersionRequest(version_string=max_version)

        if not min_version and not max_version:
            return True

        if not max_version:
            return min_version <= self
        if not min_version:
            return self <= max_version
        return min_version <= self <= max_version

    def get_string(self):
        """Returns a string representation of this object.

        If this method is used to create an APIVersionRequest,
        the resulting object will be an equivalent request.
        """
        if not self:
            raise ValueError
        return ("%(major)s.%(minor)s" %
                {'major': self._ver_major, 'minor': self._ver_minor})
