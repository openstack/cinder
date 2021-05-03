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

"""API Microversion definitions.

All new microversions should have a constant added here to be used throughout
the code instead of the specific version number. Until patches land, it's
common to end up with merge conflicts with other microversion changes. Merge
conflicts will be easier to handle via the microversion constants defined here
as the version number will only need to be changed in a single location.

Actual version numbers should be used:

  * In this file
  * In cinder/api/openstack/rest_api_version_history.rst
  * In cinder/api/openstack/api_version_request.py
  * In release notes describing the new functionality
  * In updates to api-ref

Nearly all microversion changes should include changes to all of those
locations. Make sure to add relevant documentation, and make sure that
documentation includes the final version number used.
"""

from cinder.api.openstack import api_version_request as api_version
from cinder import exception


# Add new constants here for each new microversion.

BASE_VERSION = '3.0'

UPLOAD_IMAGE_PARAMS = '3.1'

VOLUME_LIST_BOOTABLE = '3.2'

MESSAGES = '3.3'

VOLUME_LIST_GLANCE_METADATA = '3.4'

MESSAGES_PAGINATION = '3.5'

CG_UPDATE_BLANK_PROPERTIES = '3.6'

CLUSTER_SUPPORT = '3.7'

MANAGE_EXISTING_LIST = '3.8'

BACKUP_UPDATE = '3.9'

VOLUME_LIST_GROUP = '3.10'

GROUP_TYPE = '3.11'

VOLUME_SUMMARY = '3.12'

GROUP_VOLUME = '3.13'

GROUP_SNAPSHOTS = '3.14'

ETAGS = '3.15'

VOLUME_MIGRATE_CLUSTER = '3.16'

MANAGE_EXISTING_CLUSTER = '3.17'

BACKUP_PROJECT = '3.18'

GROUP_SNAPSHOT_RESET_STATUS = '3.19'

GROUP_VOLUME_RESET_STATUS = '3.20'

VOLUME_DETAIL_PROVIDER_ID = '3.21'

SNAPSHOT_LIST_METADATA_FILTER = '3.22'

VOLUME_DELETE_FORCE = '3.23'

WORKERS_CLEANUP = '3.24'

GROUP_VOLUME_LIST = '3.25'

REPLICATION_CLUSTER = '3.26'

NEW_ATTACH = '3.27'

POOL_FILTER = '3.28'

GROUP_SNAPSHOT_PAGINATION = '3.29'

SNAPSHOT_SORT = '3.30'

RESOURCE_FILTER = '3.31'

LOG_LEVEL = '3.32'

RESOURCE_FILTER_CONFIG = '3.33'

LIKE_FILTER = '3.34'

POOL_TYPE_FILTER = '3.35'

VOLUME_SUMMARY_METADATA = '3.36'

BACKUP_SORT_NAME = '3.37'

GROUP_REPLICATION = '3.38'

LIMITS_ADMIN_FILTER = '3.39'

VOLUME_REVERT = '3.40'

SNAPSHOT_LIST_USER_ID = '3.41'

VOLUME_EXTEND_INUSE = '3.42'

BACKUP_METADATA = '3.43'

NEW_ATTACH_COMPLETION = '3.44'

SUPPORT_COUNT_INFO = '3.45'

SUPPORT_NOVA_IMAGE = '3.46'

VOLUME_CREATE_FROM_BACKUP = '3.47'

VOLUME_SHARED_TARGETS_AND_SERVICE_FIELDS = '3.48'

BACKEND_STATE_REPORT = '3.49'

MULTIATTACH_VOLUMES = '3.50'

BACKUP_AZ = '3.51'

SUPPORT_VOLUME_TYPE_FILTER = '3.52'

SUPPORT_VOLUME_SCHEMA_CHANGES = '3.53'

ATTACHMENT_CREATE_MODE_ARG = '3.54'

TRANSFER_WITH_SNAPSHOTS = '3.55'

BACKUP_PROJECT_USER_ID = '3.56'

TRANSFER_WITH_HISTORY = '3.57'

GROUP_GROUPSNAPSHOT_PROJECT_ID = '3.58'

SUPPORT_TRANSFER_PAGINATION = '3.59'

VOLUME_TIME_COMPARISON_FILTER = '3.60'

VOLUME_CLUSTER_NAME = '3.61'

DEFAULT_TYPE_OVERRIDES = '3.62'

VOLUME_TYPE_ID_IN_VOLUME_DETAIL = '3.63'

ENCRYPTION_KEY_ID_IN_DETAILS = '3.64'

USE_QUOTA = '3.65'

SNAPSHOT_IN_USE = '3.66'


def get_mv_header(version):
    """Gets a formatted HTTP microversion header.

    :param version: The microversion needed.
    :return: A tuple containing the microversion header with the
             requested version value.
    """
    return {'OpenStack-API-Version':
            'volume %s' % version}


def get_api_version(version):
    """Gets a ``APIVersionRequest`` instance.

    :param version: The microversion needed.
    :return: The ``APIVersionRequest`` instance.
    """
    return api_version.APIVersionRequest(version)


def get_prior_version(version):
    """Gets the microversion before the given version.

    Mostly useful for testing boundaries. This gets the microversion defined
    just prior to the given version.

    :param version: The version of interest.
    :return: The version just prior to the given version.
    """
    parts = version.split('.')

    if len(parts) != 2 or parts[0] != '3':
        raise exception.InvalidInput(reason='Version %s is not a valid '
                                     'microversion format.' % version)

    minor = int(parts[1]) - 1

    if minor < 0:
        # What's your problem? Are you trying to be difficult?
        minor = 0

    return '%s.%s' % (parts[0], minor)
