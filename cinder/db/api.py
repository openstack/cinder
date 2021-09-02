# Copyright (c) 2011 X.commerce, a business unit of eBay Inc.
# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

"""Defines interface for DB access.

Functions in this module are imported into the cinder.db namespace. Call these
functions from cinder.db namespace, not the cinder.db.api namespace.

All functions in this module return objects that implement a dictionary-like
interface. Currently, many of these objects are sqlalchemy objects that
implement a dictionary interface. However, a future goal is to have all of
these objects be simple dictionaries.


**Related Flags**

:connection:  string specifying the sqlalchemy connection to use, like:
              `sqlite:///var/lib/cinder/cinder.sqlite`.

:enable_new_services:  when adding a new service to the database, is it in the
                       pool of available hardware (Default: True)

"""

from oslo_config import cfg
from oslo_db import api as oslo_db_api
from oslo_db import options as db_options

from cinder.api import common
from cinder.common import constants
from cinder.i18n import _

db_opts = [
    cfg.BoolOpt('enable_new_services',
                default=True,
                help='Services to be added to the available pool on create'),
    cfg.StrOpt('volume_name_template',
               default='volume-%s',
               help='Template string to be used to generate volume names'),
    cfg.StrOpt('snapshot_name_template',
               default='snapshot-%s',
               help='Template string to be used to generate snapshot names'),
]

backup_opts = [
    cfg.StrOpt('backup_name_template',
               default='backup-%s',
               help='Template string to be used to generate backup names'),
]

CONF = cfg.CONF
CONF.register_opts(db_opts)
CONF.register_opts(backup_opts)
db_options.set_defaults(CONF)

_BACKEND_MAPPING = {'sqlalchemy': 'cinder.db.sqlalchemy.api'}


IMPL = oslo_db_api.DBAPI.from_config(conf=CONF,
                                     backend_mapping=_BACKEND_MAPPING,
                                     lazy=True)

# The maximum value a signed INT type may have
MAX_INT = constants.DB_MAX_INT


###################

def dispose_engine():
    """Force the engine to establish new connections."""

    # FIXME(jdg): When using sqlite if we do the dispose
    # we seem to lose our DB here.  Adding this check
    # means we don't do the dispose, but we keep our sqlite DB
    # This likely isn't the best way to handle this

    if 'sqlite' not in IMPL.get_engine().name:
        return IMPL.dispose_engine()
    else:
        return


###################


def service_destroy(context, service_id):
    """Destroy the service or raise if it does not exist."""
    return IMPL.service_destroy(context, service_id)


def service_get(context, service_id=None, backend_match_level=None, **filters):
    """Get a service that matches the criteria.

    A possible filter is is_up=True and it will filter nodes that are down.

    :param service_id: Id of the service.
    :param filters: Filters for the query in the form of key/value.
    :param backend_match_level: 'pool', 'backend', or 'host' for host and
                                cluster filters (as defined in _filter_host
                                method)
    :raise ServiceNotFound: If service doesn't exist.
    """
    return IMPL.service_get(context, service_id, backend_match_level,
                            **filters)


def service_get_all(context, backend_match_level=None, **filters):
    """Get all services that match the criteria.

    A possible filter is is_up=True and it will filter nodes that are down,
    as well as host_or_cluster, that lets you look for services using both
    of these properties.

    :param filters: Filters for the query in the form of key/value arguments.
    :param backend_match_level: 'pool', 'backend', or 'host' for host and
                                cluster filters (as defined in _filter_host
                                method)
    """
    return IMPL.service_get_all(context, backend_match_level, **filters)


def service_create(context, values):
    """Create a service from the values dictionary."""
    return IMPL.service_create(context, values)


def service_update(context, service_id, values):
    """Set the given properties on an service and update it.

    Raises NotFound if service does not exist.
    """
    return IMPL.service_update(context, service_id, values)


def service_get_by_uuid(context, service_uuid):
    """Get a service by it's uuid.

    Return Service ref or raise if it does not exist.
    """
    return IMPL.service_get_by_uuid(context, service_uuid)


###############


def is_backend_frozen(context, host, cluster_name):
    """Check if a storage backend is frozen based on host and cluster_name."""
    return IMPL.is_backend_frozen(context, host, cluster_name)


###############


def cluster_get(context, id=None, is_up=None, get_services=False,
                services_summary=False, read_deleted='no',
                name_match_level=None, **filters):
    """Get a cluster that matches the criteria.

    :param id: Id of the cluster.
    :param is_up: Boolean value to filter based on the cluster's up status.
    :param get_services: If we want to load all services from this cluster.
    :param services_summary: If we want to load num_hosts and
                             num_down_hosts fields.
    :param read_deleted: Filtering based on delete status. Default value is
                         "no".
    :param name_match_level: 'pool', 'backend', or 'host' for name filter (as
                             defined in _filter_host method)
    :param filters: Field based filters in the form of key/value.
    :raise ClusterNotFound: If cluster doesn't exist.
    """
    return IMPL.cluster_get(context, id, is_up, get_services, services_summary,
                            read_deleted, name_match_level, **filters)


def cluster_get_all(context, is_up=None, get_services=False,
                    services_summary=False, read_deleted='no',
                    name_match_level=None, **filters):
    """Get all clusters that match the criteria.

    :param is_up: Boolean value to filter based on the cluster's up status.
    :param get_services: If we want to load all services from this cluster.
    :param services_summary: If we want to load num_hosts and
                             num_down_hosts fields.
    :param read_deleted: Filtering based on delete status. Default value is
                         "no".
    :param name_match_level: 'pool', 'backend', or 'host' for name filter (as
                             defined in _filter_host method)
    :param filters: Field based filters in the form of key/value.
    """
    return IMPL.cluster_get_all(context, is_up, get_services, services_summary,
                                read_deleted, name_match_level, **filters)


def cluster_create(context, values):
    """Create a cluster from the values dictionary."""
    return IMPL.cluster_create(context, values)


def cluster_update(context, id, values):
    """Set the given properties on an cluster and update it.

    Raises ClusterNotFound if cluster does not exist.
    """
    return IMPL.cluster_update(context, id, values)


def cluster_destroy(context, id):
    """Destroy the cluster or raise if it does not exist or has hosts.

    :raise ClusterNotFound: If cluster doesn't exist.
    """
    return IMPL.cluster_destroy(context, id)


###############


def volume_attach(context, values):
    """Attach a volume."""
    return IMPL.volume_attach(context, values)


def volume_attached(context, volume_id, instance_id, host_name, mountpoint,
                    attach_mode='rw', mark_attached=True):
    """Ensure that a volume is set as attached."""
    return IMPL.volume_attached(context, volume_id, instance_id, host_name,
                                mountpoint, attach_mode, mark_attached)


def volume_create(context, values):
    """Create a volume from the values dictionary."""
    return IMPL.volume_create(context, values)


def volume_data_get_for_host(context, host, count_only=False):
    """Get (volume_count, gigabytes) for project."""
    return IMPL.volume_data_get_for_host(context,
                                         host,
                                         count_only)


def volume_data_get_for_project(context, project_id, host=None):
    """Get (volume_count, gigabytes) for project."""
    return IMPL.volume_data_get_for_project(context, project_id, host=host)


def volume_destroy(context, volume_id):
    """Destroy the volume or raise if it does not exist."""
    return IMPL.volume_destroy(context, volume_id)


def volume_detached(context, volume_id, attachment_id):
    """Ensure that a volume is set as detached."""
    return IMPL.volume_detached(context, volume_id, attachment_id)


def volume_get(context, volume_id):
    """Get a volume or raise if it does not exist."""
    return IMPL.volume_get(context, volume_id)


def volume_get_all(context, marker=None, limit=None, sort_keys=None,
                   sort_dirs=None, filters=None, offset=None):
    """Get all volumes."""
    return IMPL.volume_get_all(context, marker, limit, sort_keys=sort_keys,
                               sort_dirs=sort_dirs, filters=filters,
                               offset=offset)


def calculate_resource_count(context, resource_type, filters):
    return IMPL.calculate_resource_count(context, resource_type, filters)


def volume_get_all_by_host(context, host, filters=None):
    """Get all volumes belonging to a host."""
    return IMPL.volume_get_all_by_host(context, host, filters=filters)


def volume_get_all_by_group(context, group_id, filters=None):
    """Get all volumes belonging to a consistency group."""
    return IMPL.volume_get_all_by_group(context, group_id, filters=filters)


def volume_get_all_by_generic_group(context, group_id, filters=None):
    """Get all volumes belonging to a generic volume group."""
    return IMPL.volume_get_all_by_generic_group(context, group_id,
                                                filters=filters)


def volume_get_all_by_project(context, project_id, marker, limit,
                              sort_keys=None, sort_dirs=None, filters=None,
                              offset=None):
    """Get all volumes belonging to a project."""
    return IMPL.volume_get_all_by_project(context, project_id, marker, limit,
                                          sort_keys=sort_keys,
                                          sort_dirs=sort_dirs,
                                          filters=filters,
                                          offset=offset)


def get_volume_summary(context, project_only, filters=None):
    """Get volume summary."""
    return IMPL.get_volume_summary(context, project_only, filters)


def volume_update(context, volume_id, values):
    """Set the given properties on a volume and update it.

    Raises NotFound if volume does not exist.

    """
    return IMPL.volume_update(context, volume_id, values)


def volumes_update(context, values_list):
    """Set the given properties on a list of volumes and update them.

    Raises NotFound if a volume does not exist.
    """
    return IMPL.volumes_update(context, values_list)


def volume_include_in_cluster(context, cluster, partial_rename=True,
                              **filters):
    """Include all volumes matching the filters into a cluster.

    When partial_rename is set we will not set the cluster_name with cluster
    parameter value directly, we'll replace provided cluster_name or host
    filter value with cluster instead.

    This is useful when we want to replace just the cluster name but leave
    the backend and pool information as it is.  If we are using cluster_name
    to filter, we'll use that same DB field to replace the cluster value and
    leave the rest as it is.  Likewise if we use the host to filter.

    Returns the number of volumes that have been changed.
    """
    return IMPL.volume_include_in_cluster(context, cluster, partial_rename,
                                          **filters)


def volume_attachment_update(context, attachment_id, values):
    return IMPL.volume_attachment_update(context, attachment_id, values)


def volume_attachment_get(context, attachment_id):
    return IMPL.volume_attachment_get(context, attachment_id)


def volume_attachment_get_all_by_volume_id(context, volume_id,
                                           session=None):
    return IMPL.volume_attachment_get_all_by_volume_id(context,
                                                       volume_id,
                                                       session)


def volume_attachment_get_all_by_host(context, host, filters=None):
    # FIXME(jdg): Not using filters
    return IMPL.volume_attachment_get_all_by_host(context, host)


def volume_attachment_get_all_by_instance_uuid(context,
                                               instance_uuid, filters=None):
    # FIXME(jdg): Not using filters
    return IMPL.volume_attachment_get_all_by_instance_uuid(context,
                                                           instance_uuid)


def volume_attachment_get_all(context, filters=None, marker=None, limit=None,
                              offset=None, sort_keys=None, sort_dirs=None):
    return IMPL.volume_attachment_get_all(context, filters, marker, limit,
                                          offset, sort_keys, sort_dirs)


def volume_attachment_get_all_by_project(context, project_id, filters=None,
                                         marker=None, limit=None, offset=None,
                                         sort_keys=None, sort_dirs=None):
    return IMPL.volume_attachment_get_all_by_project(context, project_id,
                                                     filters, marker, limit,
                                                     offset, sort_keys,
                                                     sort_dirs)


def attachment_destroy(context, attachment_id):
    """Destroy the attachment or raise if it does not exist."""
    return IMPL.attachment_destroy(context, attachment_id)


def volume_update_status_based_on_attachment(context, volume_id):
    """Update volume status according to attached instance id"""
    return IMPL.volume_update_status_based_on_attachment(context, volume_id)


def volume_has_snapshots_filter():
    return IMPL.volume_has_snapshots_filter()


def volume_has_undeletable_snapshots_filter():
    return IMPL.volume_has_undeletable_snapshots_filter()


def volume_has_snapshots_in_a_cgsnapshot_filter():
    return IMPL.volume_has_snapshots_in_a_cgsnapshot_filter()


def volume_has_attachments_filter():
    return IMPL.volume_has_attachments_filter()


def volume_qos_allows_retype(new_vol_type):
    return IMPL.volume_qos_allows_retype(new_vol_type)


def volume_has_other_project_snp_filter():
    return IMPL.volume_has_other_project_snp_filter()


####################


def snapshot_create(context, values):
    """Create a snapshot from the values dictionary."""
    return IMPL.snapshot_create(context, values)


def snapshot_destroy(context, snapshot_id):
    """Destroy the snapshot or raise if it does not exist."""
    return IMPL.snapshot_destroy(context, snapshot_id)


def snapshot_get(context, snapshot_id):
    """Get a snapshot or raise if it does not exist."""
    return IMPL.snapshot_get(context, snapshot_id)


def snapshot_get_all(context, filters=None, marker=None, limit=None,
                     sort_keys=None, sort_dirs=None, offset=None):
    """Get all snapshots."""
    return IMPL.snapshot_get_all(context, filters, marker, limit, sort_keys,
                                 sort_dirs, offset)


def snapshot_get_all_by_project(context, project_id, filters=None, marker=None,
                                limit=None, sort_keys=None, sort_dirs=None,
                                offset=None):
    """Get all snapshots belonging to a project."""
    return IMPL.snapshot_get_all_by_project(context, project_id, filters,
                                            marker, limit, sort_keys,
                                            sort_dirs, offset)


def snapshot_get_all_by_host(context, host, filters=None):
    """Get all snapshots belonging to a host.

    :param host: Include include snapshots only for specified host.
    :param filters: Filters for the query in the form of key/value.
    """
    return IMPL.snapshot_get_all_by_host(context, host, filters)


def snapshot_get_all_for_cgsnapshot(context, project_id):
    """Get all snapshots belonging to a cgsnapshot."""
    return IMPL.snapshot_get_all_for_cgsnapshot(context, project_id)


def snapshot_get_all_for_group_snapshot(context, group_snapshot_id):
    """Get all snapshots belonging to a group snapshot."""
    return IMPL.snapshot_get_all_for_group_snapshot(context, group_snapshot_id)


def snapshot_get_all_for_volume(context, volume_id):
    """Get all snapshots for a volume."""
    return IMPL.snapshot_get_all_for_volume(context, volume_id)


def snapshot_get_latest_for_volume(context, volume_id):
    """Get latest snapshot for a volume"""
    return IMPL.snapshot_get_latest_for_volume(context, volume_id)


def snapshot_update(context, snapshot_id, values):
    """Set the given properties on an snapshot and update it.

    Raises NotFound if snapshot does not exist.

    """
    return IMPL.snapshot_update(context, snapshot_id, values)


def snapshot_data_get_for_project(context, project_id, volume_type_id=None,
                                  host=None):
    """Get count and gigabytes used for snapshots for specified project."""
    return IMPL.snapshot_data_get_for_project(context,
                                              project_id,
                                              volume_type_id,
                                              host=host)


def snapshot_get_all_active_by_window(context, begin, end=None,
                                      project_id=None):
    """Get all the snapshots inside the window.

    Specifying a project_id will filter for a certain project.
    """
    return IMPL.snapshot_get_all_active_by_window(context, begin, end,
                                                  project_id)


def get_snapshot_summary(context, project_only, filters=None):
    """Get snapshot summary."""
    return IMPL.get_snapshot_summary(context, project_only, filters)


####################


def snapshot_metadata_get(context, snapshot_id):
    """Get all metadata for a snapshot."""
    return IMPL.snapshot_metadata_get(context, snapshot_id)


def snapshot_metadata_delete(context, snapshot_id, key):
    """Delete the given metadata item."""
    return IMPL.snapshot_metadata_delete(context, snapshot_id, key)


def snapshot_metadata_update(context, snapshot_id, metadata, delete):
    """Update metadata if it exists, otherwise create it."""
    return IMPL.snapshot_metadata_update(context, snapshot_id,
                                         metadata, delete)


####################


def volume_metadata_get(context, volume_id):
    """Get all metadata for a volume."""
    return IMPL.volume_metadata_get(context, volume_id)


def volume_metadata_delete(context, volume_id, key,
                           meta_type=common.METADATA_TYPES.user):
    """Delete the given metadata item."""
    return IMPL.volume_metadata_delete(context, volume_id,
                                       key, meta_type)


def volume_metadata_update(context, volume_id, metadata,
                           delete, meta_type=common.METADATA_TYPES.user):
    """Update metadata if it exists, otherwise create it."""
    return IMPL.volume_metadata_update(context, volume_id, metadata,
                                       delete, meta_type)


##################


def volume_admin_metadata_get(context, volume_id):
    """Get all administration metadata for a volume."""
    return IMPL.volume_admin_metadata_get(context, volume_id)


def volume_admin_metadata_delete(context, volume_id, key):
    """Delete the given metadata item."""
    return IMPL.volume_admin_metadata_delete(context, volume_id, key)


def volume_admin_metadata_update(context, volume_id, metadata, delete,
                                 add=True, update=True):
    """Update metadata if it exists, otherwise create it."""
    return IMPL.volume_admin_metadata_update(context, volume_id, metadata,
                                             delete, add, update)


##################


def volume_type_create(context, values, projects=None):
    """Create a new volume type."""
    return IMPL.volume_type_create(context, values, projects)


def volume_type_update(context, volume_type_id, values):
    return IMPL.volume_type_update(context, volume_type_id, values)


def volume_type_get_all(context, inactive=False, filters=None, marker=None,
                        limit=None, sort_keys=None, sort_dirs=None,
                        offset=None, list_result=False):
    """Get all volume types.

    :param context: context to query under
    :param inactive: Include inactive volume types to the result set
    :param filters: Filters for the query in the form of key/value.
    :param marker: the last item of the previous page, used to determine the
                   next page of results to return
    :param limit: maximum number of items to return
    :param sort_keys: list of attributes by which results should be sorted,
                      paired with corresponding item in sort_dirs
    :param sort_dirs: list of directions in which results should be sorted,
                      paired with corresponding item in sort_keys
    :param list_result: For compatibility, if list_result = True, return a list
                        instead of dict.

        :is_public: Filter volume types based on visibility:

            * **True**: List public volume types only
            * **False**: List private volume types only
            * **None**: List both public and private volume types

    :returns: list/dict of matching volume types
    """

    return IMPL.volume_type_get_all(context, inactive, filters, marker=marker,
                                    limit=limit, sort_keys=sort_keys,
                                    sort_dirs=sort_dirs, offset=offset,
                                    list_result=list_result)


def volume_type_get(context, id, inactive=False, expected_fields=None):
    """Get volume type by id.

    :param context: context to query under
    :param id: Volume type id to get.
    :param inactive: Consider inactive volume types when searching
    :param expected_fields: Return those additional fields.
                            Supported fields are: projects.
    :returns: volume type
    """
    return IMPL.volume_type_get(context, id, inactive, expected_fields)


def volume_type_get_by_name(context, name):
    """Get volume type by name."""
    return IMPL.volume_type_get_by_name(context, name)


def volume_types_get_by_name_or_id(context, volume_type_list):
    """Get volume types by name or id."""
    return IMPL.volume_types_get_by_name_or_id(context, volume_type_list)


def volume_type_qos_associations_get(context, qos_specs_id, inactive=False):
    """Get volume types that are associated with specific qos specs."""
    return IMPL.volume_type_qos_associations_get(context,
                                                 qos_specs_id,
                                                 inactive)


def volume_type_qos_associate(context, type_id, qos_specs_id):
    """Associate a volume type with specific qos specs."""
    return IMPL.volume_type_qos_associate(context, type_id, qos_specs_id)


def volume_type_qos_disassociate(context, qos_specs_id, type_id):
    """Disassociate a volume type from specific qos specs."""
    return IMPL.volume_type_qos_disassociate(context, qos_specs_id, type_id)


def volume_type_qos_disassociate_all(context, qos_specs_id):
    """Disassociate all volume types from specific qos specs."""
    return IMPL.volume_type_qos_disassociate_all(context,
                                                 qos_specs_id)


def volume_type_qos_specs_get(context, type_id):
    """Get all qos specs for given volume type."""
    return IMPL.volume_type_qos_specs_get(context, type_id)


def volume_type_destroy(context, id):
    """Delete a volume type."""
    return IMPL.volume_type_destroy(context, id)


def volume_get_all_active_by_window(context, begin, end=None, project_id=None):
    """Get all the volumes inside the window.

    Specifying a project_id will filter for a certain project.
    """
    return IMPL.volume_get_all_active_by_window(context, begin, end,
                                                project_id)


def volume_type_access_get_all(context, type_id):
    """Get all volume type access of a volume type."""
    return IMPL.volume_type_access_get_all(context, type_id)


def volume_type_access_add(context, type_id, project_id):
    """Add volume type access for project."""
    return IMPL.volume_type_access_add(context, type_id, project_id)


def volume_type_access_remove(context, type_id, project_id):
    """Remove volume type access for project."""
    return IMPL.volume_type_access_remove(context, type_id, project_id)


def project_default_volume_type_set(context, volume_type_id, project_id):
    """Set default volume type for a project"""
    return IMPL.project_default_volume_type_set(context, volume_type_id,
                                                project_id)


def project_default_volume_type_get(context, project_id=None):
    """Get default volume type for a project"""
    return IMPL.project_default_volume_type_get(context, project_id)


def project_default_volume_type_unset(context, project_id):
    """Unset default volume type for a project (hard delete)"""
    return IMPL.project_default_volume_type_unset(context, project_id)


def get_all_projects_with_default_type(context, volume_type_id):
    """Get all the projects associated with a default type"""
    return IMPL.get_all_projects_with_default_type(context, volume_type_id)


####################


def group_type_create(context, values, projects=None):
    """Create a new group type."""
    return IMPL.group_type_create(context, values, projects)


def group_type_update(context, group_type_id, values):
    return IMPL.group_type_update(context, group_type_id, values)


def group_type_get_all(context, inactive=False, filters=None, marker=None,
                       limit=None, sort_keys=None, sort_dirs=None,
                       offset=None, list_result=False):
    """Get all group types.

    :param context: context to query under
    :param inactive: Include inactive group types to the result set
    :param filters: Filters for the query in the form of key/value.
    :param marker: the last item of the previous page, used to determine the
                   next page of results to return
    :param limit: maximum number of items to return
    :param sort_keys: list of attributes by which results should be sorted,
                      paired with corresponding item in sort_dirs
    :param sort_dirs: list of directions in which results should be sorted,
                      paired with corresponding item in sort_keys
    :param list_result: For compatibility, if list_result = True, return a list
                        instead of dict.

        :is_public: Filter group types based on visibility:

            * **True**: List public group types only
            * **False**: List private group types only
            * **None**: List both public and private group types

    :returns: list/dict of matching group types
    """

    return IMPL.group_type_get_all(context, inactive, filters, marker=marker,
                                   limit=limit, sort_keys=sort_keys,
                                   sort_dirs=sort_dirs, offset=offset,
                                   list_result=list_result)


def group_type_get(context, id, inactive=False, expected_fields=None):
    """Get group type by id.

    :param context: context to query under
    :param id: Group type id to get.
    :param inactive: Consider inactive group types when searching
    :param expected_fields: Return those additional fields.
                            Supported fields are: projects.
    :returns: group type
    """
    return IMPL.group_type_get(context, id, inactive, expected_fields)


def group_type_get_by_name(context, name):
    """Get group type by name."""
    return IMPL.group_type_get_by_name(context, name)


def group_types_get_by_name_or_id(context, group_type_list):
    """Get group types by name or id."""
    return IMPL.group_types_get_by_name_or_id(context, group_type_list)


def group_type_destroy(context, id):
    """Delete a group type."""
    return IMPL.group_type_destroy(context, id)


def group_type_access_get_all(context, type_id):
    """Get all group type access of a group type."""
    return IMPL.group_type_access_get_all(context, type_id)


def group_type_access_add(context, type_id, project_id):
    """Add group type access for project."""
    return IMPL.group_type_access_add(context, type_id, project_id)


def group_type_access_remove(context, type_id, project_id):
    """Remove group type access for project."""
    return IMPL.group_type_access_remove(context, type_id, project_id)


def volume_type_get_all_by_group(context, group_id):
    """Get all volumes in a group."""
    return IMPL.volume_type_get_all_by_group(context, group_id)


####################


def volume_type_extra_specs_get(context, volume_type_id):
    """Get all extra specs for a volume type."""
    return IMPL.volume_type_extra_specs_get(context, volume_type_id)


def volume_type_extra_specs_delete(context, volume_type_id, key):
    """Delete the given extra specs item."""
    return IMPL.volume_type_extra_specs_delete(context, volume_type_id, key)


def volume_type_extra_specs_update_or_create(context,
                                             volume_type_id,
                                             extra_specs):
    """Create or update volume type extra specs.

    This adds or modifies the key/value pairs specified in the extra specs dict
    argument.
    """
    return IMPL.volume_type_extra_specs_update_or_create(context,
                                                         volume_type_id,
                                                         extra_specs)


###################


def group_type_specs_get(context, group_type_id):
    """Get all group specs for a group type."""
    return IMPL.group_type_specs_get(context, group_type_id)


def group_type_specs_delete(context, group_type_id, key):
    """Delete the given group specs item."""
    return IMPL.group_type_specs_delete(context, group_type_id, key)


def group_type_specs_update_or_create(context,
                                      group_type_id,
                                      group_specs):
    """Create or update group type specs.

    This adds or modifies the key/value pairs specified in the group specs dict
    argument.
    """
    return IMPL.group_type_specs_update_or_create(context,
                                                  group_type_id,
                                                  group_specs)


###################


def volume_type_encryption_get(context, volume_type_id, session=None):
    return IMPL.volume_type_encryption_get(context, volume_type_id, session)


def volume_type_encryption_delete(context, volume_type_id):
    return IMPL.volume_type_encryption_delete(context, volume_type_id)


def volume_type_encryption_create(context, volume_type_id, encryption_specs):
    return IMPL.volume_type_encryption_create(context, volume_type_id,
                                              encryption_specs)


def volume_type_encryption_update(context, volume_type_id, encryption_specs):
    return IMPL.volume_type_encryption_update(context, volume_type_id,
                                              encryption_specs)


def volume_type_encryption_volume_get(context, volume_type_id, session=None):
    return IMPL.volume_type_encryption_volume_get(context, volume_type_id,
                                                  session)


def volume_encryption_metadata_get(context, volume_id, session=None):
    return IMPL.volume_encryption_metadata_get(context, volume_id, session)


###################


def qos_specs_create(context, values):
    """Create a qos_specs."""
    return IMPL.qos_specs_create(context, values)


def qos_specs_get(context, qos_specs_id):
    """Get all specification for a given qos_specs."""
    return IMPL.qos_specs_get(context, qos_specs_id)


def qos_specs_get_all(context, filters=None, marker=None, limit=None,
                      offset=None, sort_keys=None, sort_dirs=None):
    """Get all qos_specs."""
    return IMPL.qos_specs_get_all(context, filters=filters, marker=marker,
                                  limit=limit, offset=offset,
                                  sort_keys=sort_keys, sort_dirs=sort_dirs)


def qos_specs_get_by_name(context, name):
    """Get all specification for a given qos_specs."""
    return IMPL.qos_specs_get_by_name(context, name)


def qos_specs_associations_get(context, qos_specs_id):
    """Get all associated volume types for a given qos_specs."""
    return IMPL.qos_specs_associations_get(context, qos_specs_id)


def qos_specs_associate(context, qos_specs_id, type_id):
    """Associate qos_specs from volume type."""
    return IMPL.qos_specs_associate(context, qos_specs_id, type_id)


def qos_specs_disassociate(context, qos_specs_id, type_id):
    """Disassociate qos_specs from volume type."""
    return IMPL.qos_specs_disassociate(context, qos_specs_id, type_id)


def qos_specs_disassociate_all(context, qos_specs_id):
    """Disassociate qos_specs from all entities."""
    return IMPL.qos_specs_disassociate_all(context, qos_specs_id)


def qos_specs_delete(context, qos_specs_id):
    """Delete the qos_specs."""
    return IMPL.qos_specs_delete(context, qos_specs_id)


def qos_specs_item_delete(context, qos_specs_id, key):
    """Delete specified key in the qos_specs."""
    return IMPL.qos_specs_item_delete(context, qos_specs_id, key)


def qos_specs_update(context, qos_specs_id, specs):
    """Update qos specs.

    This adds or modifies the key/value pairs specified in the
    specs dict argument for a given qos_specs.
    """
    return IMPL.qos_specs_update(context, qos_specs_id, specs)


###################


def volume_glance_metadata_create(context, volume_id, key, value):
    """Update the Glance metadata for the specified volume."""
    return IMPL.volume_glance_metadata_create(context,
                                              volume_id,
                                              key,
                                              value)


def volume_glance_metadata_bulk_create(context, volume_id, metadata):
    """Add Glance metadata for specified volume (multiple pairs)."""
    return IMPL.volume_glance_metadata_bulk_create(context, volume_id,
                                                   metadata)


def volume_glance_metadata_get_all(context):
    """Return the glance metadata for all volumes."""
    return IMPL.volume_glance_metadata_get_all(context)


def volume_glance_metadata_get(context, volume_id):
    """Return the glance metadata for a volume."""
    return IMPL.volume_glance_metadata_get(context, volume_id)


def volume_glance_metadata_list_get(context, volume_id_list):
    """Return the glance metadata for a volume list."""
    return IMPL.volume_glance_metadata_list_get(context, volume_id_list)


def volume_snapshot_glance_metadata_get(context, snapshot_id):
    """Return the Glance metadata for the specified snapshot."""
    return IMPL.volume_snapshot_glance_metadata_get(context, snapshot_id)


def volume_glance_metadata_copy_to_snapshot(context, snapshot_id, volume_id):
    """Update the Glance metadata for a snapshot.

    This will copy all of the key:value pairs from the originating volume,
    to ensure that a volume created from the snapshot will retain the
    original metadata.
    """
    return IMPL.volume_glance_metadata_copy_to_snapshot(context, snapshot_id,
                                                        volume_id)


def volume_glance_metadata_copy_to_volume(context, volume_id, snapshot_id):
    """Update the Glance metadata from a volume (created from a snapshot).

    This will copy all of the key:value pairs from the originating snapshot,
    to ensure that the Glance metadata from the original volume is retained.
    """
    return IMPL.volume_glance_metadata_copy_to_volume(context, volume_id,
                                                      snapshot_id)


def volume_glance_metadata_delete_by_volume(context, volume_id):
    """Delete the glance metadata for a volume."""
    return IMPL.volume_glance_metadata_delete_by_volume(context, volume_id)


def volume_glance_metadata_delete_by_snapshot(context, snapshot_id):
    """Delete the glance metadata for a snapshot."""
    return IMPL.volume_glance_metadata_delete_by_snapshot(context, snapshot_id)


def volume_glance_metadata_copy_from_volume_to_volume(context,
                                                      src_volume_id,
                                                      volume_id):
    """Update the Glance metadata for a volume.

    Update the Glance metadata for a volume by copying all of the key:value
    pairs from the originating volume.

    This is so that a volume created from the volume (clone) will retain the
    original metadata.
    """
    return IMPL.volume_glance_metadata_copy_from_volume_to_volume(
        context,
        src_volume_id,
        volume_id)


###################


def quota_create(context, project_id, resource, limit):
    """Create a quota for the given project and resource."""
    return IMPL.quota_create(context, project_id, resource, limit)


def quota_get(context, project_id, resource):
    """Retrieve a quota or raise if it does not exist."""
    return IMPL.quota_get(context, project_id, resource)


def quota_get_all_by_project(context, project_id):
    """Retrieve all quotas associated with a given project."""
    return IMPL.quota_get_all_by_project(context, project_id)


def quota_update(context, project_id, resource, limit):
    """Update a quota or raise if it does not exist."""
    return IMPL.quota_update(context, project_id, resource, limit)


def quota_update_resource(context, old_res, new_res):
    """Update resource of quotas."""
    return IMPL.quota_update_resource(context, old_res, new_res)


def quota_destroy(context, project_id, resource):
    """Destroy the quota or raise if it does not exist."""
    return IMPL.quota_destroy(context, project_id, resource)


###################


def quota_class_create(context, class_name, resource, limit):
    """Create a quota class for the given name and resource."""
    return IMPL.quota_class_create(context, class_name, resource, limit)


def quota_class_get(context, class_name, resource):
    """Retrieve a quota class or raise if it does not exist."""
    return IMPL.quota_class_get(context, class_name, resource)


def quota_class_get_defaults(context):
    """Retrieve all default quotas."""
    return IMPL.quota_class_get_defaults(context)


def quota_class_get_all_by_name(context, class_name):
    """Retrieve all quotas associated with a given quota class."""
    return IMPL.quota_class_get_all_by_name(context, class_name)


def quota_class_update(context, class_name, resource, limit):
    """Update a quota class or raise if it does not exist."""
    return IMPL.quota_class_update(context, class_name, resource, limit)


def quota_class_update_resource(context, resource, new_resource):
    """Update resource name in quota_class."""
    return IMPL.quota_class_update_resource(context, resource, new_resource)


def quota_class_destroy(context, class_name, resource):
    """Destroy the quota class or raise if it does not exist."""
    return IMPL.quota_class_destroy(context, class_name, resource)


def quota_class_destroy_all_by_name(context, class_name):
    """Destroy all quotas associated with a given quota class."""
    return IMPL.quota_class_destroy_all_by_name(context, class_name)


###################


def quota_usage_get(context, project_id, resource):
    """Retrieve a quota usage or raise if it does not exist."""
    return IMPL.quota_usage_get(context, project_id, resource)


def quota_usage_get_all_by_project(context, project_id):
    """Retrieve all usage associated with a given resource."""
    return IMPL.quota_usage_get_all_by_project(context, project_id)


###################


def quota_reserve(context, resources, quotas, deltas, expire,
                  until_refresh, max_age, project_id=None):
    """Check quotas and create appropriate reservations."""
    return IMPL.quota_reserve(context, resources, quotas, deltas, expire,
                              until_refresh, max_age, project_id=project_id)


def reservation_commit(context, reservations, project_id=None):
    """Commit quota reservations."""
    return IMPL.reservation_commit(context, reservations,
                                   project_id=project_id)


def reservation_rollback(context, reservations, project_id=None):
    """Roll back quota reservations."""
    return IMPL.reservation_rollback(context, reservations,
                                     project_id=project_id)


def quota_destroy_by_project(context, project_id):
    """Destroy all quotas associated with a given project."""
    return IMPL.quota_destroy_by_project(context, project_id)


def reservation_expire(context):
    """Roll back any expired reservations."""
    return IMPL.reservation_expire(context)


def quota_usage_update_resource(context, old_res, new_res):
    """Update resource field in quota_usages."""
    return IMPL.quota_usage_update_resource(context, old_res, new_res)


###################


def backup_get(context, backup_id, read_deleted=None, project_only=True):
    """Get a backup or raise if it does not exist."""
    return IMPL.backup_get(context, backup_id, read_deleted, project_only)


def backup_get_all(context, filters=None, marker=None, limit=None,
                   offset=None, sort_keys=None, sort_dirs=None):
    """Get all backups."""
    return IMPL.backup_get_all(context, filters=filters, marker=marker,
                               limit=limit, offset=offset, sort_keys=sort_keys,
                               sort_dirs=sort_dirs)


def backup_get_all_by_host(context, host):
    """Get all backups belonging to a host."""
    return IMPL.backup_get_all_by_host(context, host)


def backup_create(context, values):
    """Create a backup from the values dictionary."""
    return IMPL.backup_create(context, values)


def backup_metadata_get(context, backup_id):
    return IMPL.backup_metadata_get(context, backup_id)


def backup_metadata_update(context, backup_id, metadata, delete):
    return IMPL.backup_metadata_update(context, backup_id, metadata, delete)


def backup_get_all_by_project(context, project_id, filters=None, marker=None,
                              limit=None, offset=None, sort_keys=None,
                              sort_dirs=None):
    """Get all backups belonging to a project."""
    return IMPL.backup_get_all_by_project(context, project_id,
                                          filters=filters, marker=marker,
                                          limit=limit, offset=offset,
                                          sort_keys=sort_keys,
                                          sort_dirs=sort_dirs)


def backup_get_all_by_volume(context, volume_id, vol_project_id, filters=None):
    """Get all backups belonging to a volume."""
    return IMPL.backup_get_all_by_volume(context, volume_id, vol_project_id,
                                         filters=filters)


def backup_get_all_active_by_window(context, begin, end=None, project_id=None):
    """Get all the backups inside the window.

    Specifying a project_id will filter for a certain project.
    """
    return IMPL.backup_get_all_active_by_window(context, begin, end,
                                                project_id)


def backup_update(context, backup_id, values):
    """Set the given properties on a backup and update it.

    Raises NotFound if backup does not exist.
    """
    return IMPL.backup_update(context, backup_id, values)


def backup_destroy(context, backup_id):
    """Destroy the backup or raise if it does not exist."""
    return IMPL.backup_destroy(context, backup_id)


###################


def transfer_get(context, transfer_id):
    """Get a volume transfer record or raise if it does not exist."""
    return IMPL.transfer_get(context, transfer_id)


def transfer_get_all(context, marker=None, limit=None, sort_keys=None,
                     sort_dirs=None, filters=None, offset=None):
    """Get all volume transfer records."""
    return IMPL.transfer_get_all(context, marker=marker, limit=limit,
                                 sort_keys=sort_keys, sort_dirs=sort_dirs,
                                 filters=filters, offset=offset)


def transfer_get_all_by_project(context, project_id, marker=None,
                                limit=None, sort_keys=None,
                                sort_dirs=None, filters=None, offset=None):
    """Get all volume transfer records for specified project."""
    return IMPL.transfer_get_all_by_project(context, project_id, marker=marker,
                                            limit=limit, sort_keys=sort_keys,
                                            sort_dirs=sort_dirs,
                                            filters=filters, offset=offset)


def transfer_create(context, values):
    """Create an entry in the transfers table."""
    return IMPL.transfer_create(context, values)


def transfer_destroy(context, transfer_id):
    """Destroy a record in the volume transfer table."""
    return IMPL.transfer_destroy(context, transfer_id)


def transfer_accept(context, transfer_id, user_id, project_id,
                    no_snapshots=False):
    """Accept a volume transfer."""
    return IMPL.transfer_accept(context, transfer_id, user_id, project_id,
                                no_snapshots=no_snapshots)


###################


def consistencygroup_get(context, consistencygroup_id):
    """Get a consistencygroup or raise if it does not exist."""
    return IMPL.consistencygroup_get(context, consistencygroup_id)


def consistencygroup_get_all(context, filters=None, marker=None, limit=None,
                             offset=None, sort_keys=None, sort_dirs=None):
    """Get all consistencygroups."""
    return IMPL.consistencygroup_get_all(context, filters=filters,
                                         marker=marker, limit=limit,
                                         offset=offset, sort_keys=sort_keys,
                                         sort_dirs=sort_dirs)


def consistencygroup_create(context, values, cg_snap_id=None, cg_id=None):
    """Create a consistencygroup from the values dictionary."""
    return IMPL.consistencygroup_create(context, values, cg_snap_id, cg_id)


def consistencygroup_get_all_by_project(context, project_id, filters=None,
                                        marker=None, limit=None, offset=None,
                                        sort_keys=None, sort_dirs=None):
    """Get all consistencygroups belonging to a project."""
    return IMPL.consistencygroup_get_all_by_project(context, project_id,
                                                    filters=filters,
                                                    marker=marker, limit=limit,
                                                    offset=offset,
                                                    sort_keys=sort_keys,
                                                    sort_dirs=sort_dirs)


def consistencygroup_update(context, consistencygroup_id, values):
    """Set the given properties on a consistencygroup and update it.

    Raises NotFound if consistencygroup does not exist.
    """
    return IMPL.consistencygroup_update(context, consistencygroup_id, values)


def consistencygroup_destroy(context, consistencygroup_id):
    """Destroy the consistencygroup or raise if it does not exist."""
    return IMPL.consistencygroup_destroy(context, consistencygroup_id)


def cg_has_cgsnapshot_filter():
    """Return a filter that checks if a CG has CG Snapshots."""
    return IMPL.cg_has_cgsnapshot_filter()


def cg_has_volumes_filter(attached_or_with_snapshots=False):
    """Return a filter to check if a CG has volumes.

    When attached_or_with_snapshots parameter is given a True value only
    attached volumes or those with snapshots will be considered.
    """
    return IMPL.cg_has_volumes_filter(attached_or_with_snapshots)


def cg_creating_from_src(cg_id=None, cgsnapshot_id=None):
    """Return a filter to check if a CG is being used as creation source.

    Returned filter is meant to be used in the Conditional Update mechanism and
    checks if provided CG ID or CG Snapshot ID is currently being used to
    create another CG.

    This filter will not include CGs that have used the ID but have already
    finished their creation (status is no longer creating).

    Filter uses a subquery that allows it to be used on updates to the
    consistencygroups table.
    """
    return IMPL.cg_creating_from_src(cg_id, cgsnapshot_id)


def consistencygroup_include_in_cluster(context, cluster, partial_rename=True,
                                        **filters):
    """Include all consistency groups matching the filters into a cluster.

    When partial_rename is set we will not set the cluster_name with cluster
    parameter value directly, we'll replace provided cluster_name or host
    filter value with cluster instead.

    This is useful when we want to replace just the cluster name but leave
    the backend and pool information as it is.  If we are using cluster_name
    to filter, we'll use that same DB field to replace the cluster value and
    leave the rest as it is.  Likewise if we use the host to filter.

    Returns the number of consistency groups that have been changed.
    """
    return IMPL.consistencygroup_include_in_cluster(context, cluster,
                                                    partial_rename,
                                                    **filters)


def group_include_in_cluster(context, cluster, partial_rename=True, **filters):
    """Include all generic groups matching the filters into a cluster.

    When partial_rename is set we will not set the cluster_name with cluster
    parameter value directly, we'll replace provided cluster_name or host
    filter value with cluster instead.

    This is useful when we want to replace just the cluster name but leave
    the backend and pool information as it is.  If we are using cluster_name
    to filter, we'll use that same DB field to replace the cluster value and
    leave the rest as it is.  Likewise if we use the host to filter.

    Returns the number of generic groups that have been changed.
    """
    return IMPL.group_include_in_cluster(context, cluster, partial_rename,
                                         **filters)

###################


def group_get(context, group_id):
    """Get a group or raise if it does not exist."""
    return IMPL.group_get(context, group_id)


def group_get_all(context, filters=None, marker=None, limit=None,
                  offset=None, sort_keys=None, sort_dirs=None):
    """Get all groups."""
    return IMPL.group_get_all(context, filters=filters,
                              marker=marker, limit=limit,
                              offset=offset, sort_keys=sort_keys,
                              sort_dirs=sort_dirs)


def group_create(context, values, group_snapshot_id=None, group_id=None):
    """Create a group from the values dictionary."""
    return IMPL.group_create(context, values, group_snapshot_id, group_id)


def group_get_all_by_project(context, project_id, filters=None,
                             marker=None, limit=None, offset=None,
                             sort_keys=None, sort_dirs=None):
    """Get all groups belonging to a project."""
    return IMPL.group_get_all_by_project(context, project_id,
                                         filters=filters,
                                         marker=marker, limit=limit,
                                         offset=offset,
                                         sort_keys=sort_keys,
                                         sort_dirs=sort_dirs)


def group_update(context, group_id, values):
    """Set the given properties on a group and update it.

    Raises NotFound if group does not exist.
    """
    return IMPL.group_update(context, group_id, values)


def group_destroy(context, group_id):
    """Destroy the group or raise if it does not exist."""
    return IMPL.group_destroy(context, group_id)


def group_has_group_snapshot_filter():
    """Return a filter that checks if a Group has Group Snapshots."""
    return IMPL.group_has_group_snapshot_filter()


def group_has_volumes_filter(attached_or_with_snapshots=False):
    """Return a filter to check if a Group has volumes.

    When attached_or_with_snapshots parameter is given a True value only
    attached volumes or those with snapshots will be considered.
    """
    return IMPL.group_has_volumes_filter(attached_or_with_snapshots)


def group_creating_from_src(group_id=None, group_snapshot_id=None):
    """Return a filter to check if a Group is being used as creation source.

    Returned filter is meant to be used in the Conditional Update mechanism and
    checks if provided Group ID or Group Snapshot ID is currently being used to
    create another Group.

    This filter will not include Groups that have used the ID but have already
    finished their creation (status is no longer creating).

    Filter uses a subquery that allows it to be used on updates to the
    groups table.
    """
    return IMPL.group_creating_from_src(group_id, group_snapshot_id)


def group_volume_type_mapping_create(context, group_id, volume_type_id):
    """Create a group volume_type mapping entry."""
    return IMPL.group_volume_type_mapping_create(context, group_id,
                                                 volume_type_id)


###################


def cgsnapshot_get(context, cgsnapshot_id):
    """Get a cgsnapshot or raise if it does not exist."""
    return IMPL.cgsnapshot_get(context, cgsnapshot_id)


def cgsnapshot_get_all(context, filters=None):
    """Get all cgsnapshots."""
    return IMPL.cgsnapshot_get_all(context, filters)


def cgsnapshot_create(context, values):
    """Create a cgsnapshot from the values dictionary."""
    return IMPL.cgsnapshot_create(context, values)


def cgsnapshot_get_all_by_group(context, group_id, filters=None):
    """Get all cgsnapshots belonging to a consistency group."""
    return IMPL.cgsnapshot_get_all_by_group(context, group_id, filters)


def cgsnapshot_get_all_by_project(context, project_id, filters=None):
    """Get all cgsnapshots belonging to a project."""
    return IMPL.cgsnapshot_get_all_by_project(context, project_id, filters)


def cgsnapshot_update(context, cgsnapshot_id, values):
    """Set the given properties on a cgsnapshot and update it.

    Raises NotFound if cgsnapshot does not exist.
    """
    return IMPL.cgsnapshot_update(context, cgsnapshot_id, values)


def cgsnapshot_destroy(context, cgsnapshot_id):
    """Destroy the cgsnapshot or raise if it does not exist."""
    return IMPL.cgsnapshot_destroy(context, cgsnapshot_id)


def cgsnapshot_creating_from_src():
    """Get a filter that checks if a CGSnapshot is being created from a CG."""
    return IMPL.cgsnapshot_creating_from_src()


###################


def group_snapshot_get(context, group_snapshot_id):
    """Get a group snapshot or raise if it does not exist."""
    return IMPL.group_snapshot_get(context, group_snapshot_id)


def group_snapshot_get_all(context, filters=None, marker=None, limit=None,
                           offset=None, sort_keys=None, sort_dirs=None):
    """Get all group snapshots."""
    return IMPL.group_snapshot_get_all(context, filters, marker, limit,
                                       offset, sort_keys, sort_dirs)


def group_snapshot_create(context, values):
    """Create a group snapshot from the values dictionary."""
    return IMPL.group_snapshot_create(context, values)


def group_snapshot_get_all_by_group(context, group_id, filters=None,
                                    marker=None, limit=None,
                                    offset=None, sort_keys=None,
                                    sort_dirs=None):
    """Get all group snapshots belonging to a group."""
    return IMPL.group_snapshot_get_all_by_group(context, group_id,
                                                filters, marker, limit,
                                                offset, sort_keys, sort_dirs)


def group_snapshot_get_all_by_project(context, project_id, filters=None,
                                      marker=None, limit=None,
                                      offset=None, sort_keys=None,
                                      sort_dirs=None):
    """Get all group snapshots belonging to a project."""
    return IMPL.group_snapshot_get_all_by_project(context, project_id,
                                                  filters, marker, limit,
                                                  offset, sort_keys, sort_dirs)


def group_snapshot_update(context, group_snapshot_id, values):
    """Set the given properties on a group snapshot and update it.

    Raises NotFound if group snapshot does not exist.
    """
    return IMPL.group_snapshot_update(context, group_snapshot_id, values)


def group_snapshot_destroy(context, group_snapshot_id):
    """Destroy the group snapshot or raise if it does not exist."""
    return IMPL.group_snapshot_destroy(context, group_snapshot_id)


def group_snapshot_creating_from_src():
    """Get a filter to check if a grp snapshot is being created from a grp."""
    return IMPL.group_snapshot_creating_from_src()


###################


def purge_deleted_rows(context, age_in_days):
    """Purge deleted rows older than given age from cinder tables

    Raises InvalidParameterValue if age_in_days is incorrect.
    :returns: number of deleted rows
    """
    return IMPL.purge_deleted_rows(context, age_in_days=age_in_days)


def get_booleans_for_table(table_name):
    return IMPL.get_booleans_for_table(table_name)


###################


def reset_active_backend(context, enable_replication, active_backend_id,
                         backend_host):
    """Reset the active backend for a host."""
    return IMPL.reset_active_backend(context, enable_replication,
                                     active_backend_id, backend_host)


###################


def driver_initiator_data_insert_by_key(context, initiator,
                                        namespace, key, value):
    """Updates DriverInitiatorData entry.

    Sets the value for the specified key within the namespace.

    If the entry already exists return False, if it inserted successfully
    return True.
    """
    return IMPL.driver_initiator_data_insert_by_key(context,
                                                    initiator,
                                                    namespace,
                                                    key,
                                                    value)


def driver_initiator_data_get(context, initiator, namespace):
    """Query for an DriverInitiatorData that has the specified key"""
    return IMPL.driver_initiator_data_get(context, initiator, namespace)


###################


def image_volume_cache_create(context, host, cluster_name, image_id,
                              image_updated_at, volume_id, size):
    """Create a new image volume cache entry."""
    return IMPL.image_volume_cache_create(context,
                                          host,
                                          cluster_name,
                                          image_id,
                                          image_updated_at,
                                          volume_id,
                                          size)


def image_volume_cache_delete(context, volume_id):
    """Delete an image volume cache entry specified by volume id."""
    return IMPL.image_volume_cache_delete(context, volume_id)


def image_volume_cache_get_and_update_last_used(context, image_id, **filters):
    """Query for an image volume cache entry."""
    return IMPL.image_volume_cache_get_and_update_last_used(context,
                                                            image_id,
                                                            **filters)


def image_volume_cache_get_by_volume_id(context, volume_id):
    """Query to see if a volume id is an image-volume contained in the cache"""
    return IMPL.image_volume_cache_get_by_volume_id(context, volume_id)


def image_volume_cache_get_all(context, **filters):
    """Query for all image volume cache entry for a host."""
    return IMPL.image_volume_cache_get_all(context, **filters)


def image_volume_cache_include_in_cluster(context, cluster,
                                          partial_rename=True, **filters):
    """Include in cluster image volume cache entries matching the filters.

    When partial_rename is set we will not set the cluster_name with cluster
    parameter value directly, we'll replace provided cluster_name or host
    filter value with cluster instead.

    This is useful when we want to replace just the cluster name but leave
    the backend and pool information as it is.  If we are using cluster_name
    to filter, we'll use that same DB field to replace the cluster value and
    leave the rest as it is.  Likewise if we use the host to filter.

    Returns the number of volumes that have been changed.
    """
    return IMPL.image_volume_cache_include_in_cluster(
        context, cluster, partial_rename, **filters)


###################


def message_get(context, message_id):
    """Return a message with the specified ID."""
    return IMPL.message_get(context, message_id)


def message_get_all(context, filters=None, marker=None, limit=None,
                    offset=None, sort_keys=None, sort_dirs=None):
    return IMPL.message_get_all(context, filters=filters, marker=marker,
                                limit=limit, offset=offset,
                                sort_keys=sort_keys, sort_dirs=sort_dirs)


def message_create(context, values):
    """Creates a new message with the specified values."""
    return IMPL.message_create(context, values)


def message_destroy(context, message_id):
    """Deletes message with the specified ID."""
    return IMPL.message_destroy(context, message_id)


def cleanup_expired_messages(context):
    """Soft delete expired messages"""
    return IMPL.cleanup_expired_messages(context)


###################


def workers_init():
    """Check if DB supports subsecond resolution and set global flag.

    MySQL 5.5 doesn't support subsecond resolution in datetime fields, so we
    have to take it into account when working with the worker's table.

    Once we drop support for MySQL 5.5 we can remove this method.
    """
    return IMPL.workers_init()


def worker_create(context, **values):
    """Create a worker entry from optional arguments."""
    return IMPL.worker_create(context, **values)


def worker_get(context, **filters):
    """Get a worker or raise exception if it does not exist."""
    return IMPL.worker_get(context, **filters)


def worker_get_all(context, until=None, db_filters=None, **filters):
    """Get all workers that match given criteria."""
    return IMPL.worker_get_all(context, until=until, db_filters=db_filters,
                               **filters)


def worker_update(context, id, filters=None, orm_worker=None, **values):
    """Update a worker with given values."""
    return IMPL.worker_update(context, id, filters=filters,
                              orm_worker=orm_worker, **values)


def worker_claim_for_cleanup(context, claimer_id, orm_worker):
    """Soft delete a worker, change the service_id and update the worker."""
    return IMPL.worker_claim_for_cleanup(context, claimer_id, orm_worker)


def worker_destroy(context, **filters):
    """Delete a worker (no soft delete)."""
    return IMPL.worker_destroy(context, **filters)


###################


def resource_exists(context, model, resource_id):
    return IMPL.resource_exists(context, model, resource_id)


def get_model_for_versioned_object(versioned_object):
    return IMPL.get_model_for_versioned_object(versioned_object)


def get_by_id(context, model, id, *args, **kwargs):
    return IMPL.get_by_id(context, model, id, *args, **kwargs)


class Condition(object):
    """Class for normal condition values for conditional_update."""
    def __init__(self, value, field=None):
        self.value = value
        # Field is optional and can be passed when getting the filter
        self.field = field

    def get_filter(self, model, field=None):
        return IMPL.condition_db_filter(model, self._get_field(field),
                                        self.value)

    def _get_field(self, field=None):
        # We must have a defined field on initialization or when called
        field = field or self.field
        if not field:
            raise ValueError(_('Condition has no field.'))
        return field

###################


def attachment_specs_exist(context):
    """Check if there are attachment specs left."""
    return IMPL.attachment_specs_exist(context)


def attachment_specs_get(context, attachment_id):
    """DEPRECATED: Get all specs for an attachment."""
    return IMPL.attachment_specs_get(context, attachment_id)


def attachment_specs_delete(context, attachment_id, key):
    """DEPRECATED: Delete the given attachment specs item."""
    return IMPL.attachment_specs_delete(context, attachment_id, key)


def attachment_specs_update_or_create(context,
                                      attachment_id,
                                      specs):
    """DEPRECATED: Create or update attachment specs.

    This adds or modifies the key/value pairs specified in the attachment
    specs dict argument.
    """
    return IMPL.attachment_specs_update_or_create(context,
                                                  attachment_id,
                                                  specs)


###################


class Not(Condition):
    """Class for negated condition values for conditional_update.

    By default NULL values will be treated like Python treats None instead of
    how SQL treats it.

    So for example when values are (1, 2) it will evaluate to True when we have
    value 3 or NULL, instead of only with 3 like SQL does.
    """
    def __init__(self, value, field=None, auto_none=True):
        super(Not, self).__init__(value, field)
        self.auto_none = auto_none

    def get_filter(self, model, field=None):
        # If implementation has a specific method use it
        if hasattr(IMPL, 'condition_not_db_filter'):
            return IMPL.condition_not_db_filter(model, self._get_field(field),
                                                self.value, self.auto_none)

        # Otherwise non negated object must adming ~ operator for not
        return ~super(Not, self).get_filter(model, field)


class Case(object):
    """Class for conditional value selection for conditional_update."""
    def __init__(self, whens, value=None, else_=None):
        self.whens = whens
        self.value = value
        self.else_ = else_


def is_orm_value(obj):
    """Check if object is an ORM field."""
    return IMPL.is_orm_value(obj)


def conditional_update(context, model, values, expected_values, filters=(),
                       include_deleted='no', project_only=False, order=None):
    """Compare-and-swap conditional update.

    Update will only occur in the DB if conditions are met.

    We have 4 different condition types we can use in expected_values:
     - Equality:  {'status': 'available'}
     - Inequality: {'status': vol_obj.Not('deleting')}
     - In range: {'status': ['available', 'error']
     - Not in range: {'status': vol_obj.Not(['in-use', 'attaching'])

    Method accepts additional filters, which are basically anything that can be
    passed to a sqlalchemy query's filter method, for example:

    .. code-block:: python

     [~sql.exists().where(models.Volume.id == models.Snapshot.volume_id)]

    We can select values based on conditions using Case objects in the 'values'
    argument. For example:

    .. code-block:: python

     has_snapshot_filter = sql.exists().where(
         models.Snapshot.volume_id == models.Volume.id)
     case_values = db.Case([(has_snapshot_filter, 'has-snapshot')],
                           else_='no-snapshot')
     db.conditional_update(context, models.Volume, {'status': case_values},
                           {'status': 'available'})

    And we can use DB fields for example to store previous status in the
    corresponding field even though we don't know which value is in the db from
    those we allowed:

    .. code-block:: python

     db.conditional_update(context, models.Volume,
                           {'status': 'deleting',
                            'previous_status': models.Volume.status},
                           {'status': ('available', 'error')})

    :param values: Dictionary of key-values to update in the DB.
    :param expected_values: Dictionary of conditions that must be met for the
                            update to be executed.
    :param filters: Iterable with additional filters.
    :param include_deleted: Should the update include deleted items, this is
                            equivalent to read_deleted.
    :param project_only: Should the query be limited to context's project.
    :param order: Specific order of fields in which to update the values
    :returns: Number of db rows that were updated.
    """
    return IMPL.conditional_update(context, model, values, expected_values,
                                   filters, include_deleted, project_only,
                                   order)


# TODO: (Y Release) remove method and this comment
def volume_use_quota_online_data_migration(context, max_count):
    return IMPL.volume_use_quota_online_data_migration(context, max_count)


# TODO: (Y Release) remove method and this comment
def snapshot_use_quota_online_data_migration(context, max_count):
    return IMPL.snapshot_use_quota_online_data_migration(context, max_count)


# TODO: (Z Release) remove method and this comment
# TODO: (Y Release) uncomment method
# def remove_temporary_admin_metadata_data_migration(context, max_count):
#     IMPL.remove_temporary_admin_metadata_data_migration(context, max_count)
