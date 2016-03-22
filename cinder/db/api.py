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
from oslo_db import concurrency as db_concurrency
from oslo_db import options as db_options

from cinder.api import common

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
    cfg.StrOpt('backup_name_template',
               default='backup-%s',
               help='Template string to be used to generate backup names'), ]


CONF = cfg.CONF
CONF.register_opts(db_opts)
db_options.set_defaults(CONF)
CONF.set_default('sqlite_db', 'cinder.sqlite', group='database')

_BACKEND_MAPPING = {'sqlalchemy': 'cinder.db.sqlalchemy.api'}


IMPL = db_concurrency.TpoolDbapiWrapper(CONF, _BACKEND_MAPPING)

# The maximum value a signed INT type may have
MAX_INT = 0x7FFFFFFF


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


def service_get(context, service_id):
    """Get a service or raise if it does not exist."""
    return IMPL.service_get(context, service_id)


def service_get_by_host_and_topic(context, host, topic):
    """Get a service by host it's on and topic it listens to."""
    return IMPL.service_get_by_host_and_topic(context, host, topic)


def service_get_all(context, disabled=None):
    """Get all services."""
    return IMPL.service_get_all(context, disabled)


def service_get_all_by_topic(context, topic, disabled=None):
    """Get all services for a given topic."""
    return IMPL.service_get_all_by_topic(context, topic, disabled=disabled)


def service_get_by_args(context, host, binary):
    """Get the state of an service by node name and binary."""
    return IMPL.service_get_by_args(context, host, binary)


def service_create(context, values):
    """Create a service from the values dictionary."""
    return IMPL.service_create(context, values)


def service_update(context, service_id, values):
    """Set the given properties on an service and update it.

    Raises NotFound if service does not exist.

    """
    return IMPL.service_update(context, service_id, values)


###################


def iscsi_target_count_by_host(context, host):
    """Return count of export devices."""
    return IMPL.iscsi_target_count_by_host(context, host)


def iscsi_target_create_safe(context, values):
    """Create an iscsi_target from the values dictionary.

    The device is not returned. If the create violates the unique
    constraints because the iscsi_target and host already exist,
    no exception is raised.

    """
    return IMPL.iscsi_target_create_safe(context, values)


###############


def volume_attach(context, values):
    """Attach a volume."""
    return IMPL.volume_attach(context, values)


def volume_attached(context, volume_id, instance_id, host_name, mountpoint,
                    attach_mode='rw'):
    """Ensure that a volume is set as attached."""
    return IMPL.volume_attached(context, volume_id, instance_id, host_name,
                                mountpoint, attach_mode)


def volume_create(context, values):
    """Create a volume from the values dictionary."""
    return IMPL.volume_create(context, values)


def volume_data_get_for_host(context, host, count_only=False):
    """Get (volume_count, gigabytes) for project."""
    return IMPL.volume_data_get_for_host(context,
                                         host,
                                         count_only)


def volume_data_get_for_project(context, project_id):
    """Get (volume_count, gigabytes) for project."""
    return IMPL.volume_data_get_for_project(context, project_id)


def finish_volume_migration(context, src_vol_id, dest_vol_id):
    """Perform database updates upon completion of volume migration."""
    return IMPL.finish_volume_migration(context, src_vol_id, dest_vol_id)


def volume_destroy(context, volume_id):
    """Destroy the volume or raise if it does not exist."""
    return IMPL.volume_destroy(context, volume_id)


def volume_detached(context, volume_id, attachment_id):
    """Ensure that a volume is set as detached."""
    return IMPL.volume_detached(context, volume_id, attachment_id)


def volume_get(context, volume_id):
    """Get a volume or raise if it does not exist."""
    return IMPL.volume_get(context, volume_id)


def volume_get_all(context, marker, limit, sort_keys=None, sort_dirs=None,
                   filters=None, offset=None):
    """Get all volumes."""
    return IMPL.volume_get_all(context, marker, limit, sort_keys=sort_keys,
                               sort_dirs=sort_dirs, filters=filters,
                               offset=offset)


def volume_get_all_by_host(context, host, filters=None):
    """Get all volumes belonging to a host."""
    return IMPL.volume_get_all_by_host(context, host, filters=filters)


def volume_get_all_by_group(context, group_id, filters=None):
    """Get all volumes belonging to a consistency group."""
    return IMPL.volume_get_all_by_group(context, group_id, filters=filters)


def volume_get_all_by_project(context, project_id, marker, limit,
                              sort_keys=None, sort_dirs=None, filters=None,
                              offset=None):
    """Get all volumes belonging to a project."""
    return IMPL.volume_get_all_by_project(context, project_id, marker, limit,
                                          sort_keys=sort_keys,
                                          sort_dirs=sort_dirs,
                                          filters=filters,
                                          offset=offset)


def volume_get_iscsi_target_num(context, volume_id):
    """Get the target num (tid) allocated to the volume."""
    return IMPL.volume_get_iscsi_target_num(context, volume_id)


def volume_update(context, volume_id, values):
    """Set the given properties on an volume and update it.

    Raises NotFound if volume does not exist.

    """
    return IMPL.volume_update(context, volume_id, values)


def volume_attachment_update(context, attachment_id, values):
    return IMPL.volume_attachment_update(context, attachment_id, values)


def volume_attachment_get(context, attachment_id, session=None):
    return IMPL.volume_attachment_get(context, attachment_id, session)


def volume_attachment_get_used_by_volume_id(context, volume_id):
    return IMPL.volume_attachment_get_used_by_volume_id(context, volume_id)


def volume_attachment_get_by_host(context, volume_id, host):
    return IMPL.volume_attachment_get_by_host(context, volume_id, host)


def volume_attachment_get_by_instance_uuid(context, volume_id, instance_uuid):
    return IMPL.volume_attachment_get_by_instance_uuid(context, volume_id,
                                                       instance_uuid)


def volume_update_status_based_on_attachment(context, volume_id):
    """Update volume status according to attached instance id"""
    return IMPL.volume_update_status_based_on_attachment(context, volume_id)


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


def snapshot_get_by_host(context, host, filters=None):
    """Get all snapshots belonging to a host.

    :param host: Include include snapshots only for specified host.
    :param filters: Filters for the query in the form of key/value.
    """
    return IMPL.snapshot_get_by_host(context, host, filters)


def snapshot_get_all_for_cgsnapshot(context, project_id):
    """Get all snapshots belonging to a cgsnapshot."""
    return IMPL.snapshot_get_all_for_cgsnapshot(context, project_id)


def snapshot_get_all_for_volume(context, volume_id):
    """Get all snapshots for a volume."""
    return IMPL.snapshot_get_all_for_volume(context, volume_id)


def snapshot_update(context, snapshot_id, values):
    """Set the given properties on an snapshot and update it.

    Raises NotFound if snapshot does not exist.

    """
    return IMPL.snapshot_update(context, snapshot_id, values)


def snapshot_data_get_for_project(context, project_id, volume_type_id=None):
    """Get count and gigabytes used for snapshots for specified project."""
    return IMPL.snapshot_data_get_for_project(context,
                                              project_id,
                                              volume_type_id)


def snapshot_get_active_by_window(context, begin, end=None, project_id=None):
    """Get all the snapshots inside the window.

    Specifying a project_id will filter for a certain project.
    """
    return IMPL.snapshot_get_active_by_window(context, begin, end, project_id)


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


def volume_admin_metadata_update(context, volume_id, metadata, delete):
    """Update metadata if it exists, otherwise create it."""
    return IMPL.volume_admin_metadata_update(context, volume_id, metadata,
                                             delete)


##################


def volume_type_create(context, values, projects=None):
    """Create a new volume type."""
    return IMPL.volume_type_create(context, values, projects)


def volume_type_update(context, volume_type_id, values):
    return IMPL.volume_type_update(context, volume_type_id, values)


def volume_type_get_all(context, inactive=False, filters=None):
    """Get all volume types.

    :param context: context to query under
    :param inactive: Include inactive volume types to the result set
    :param filters: Filters for the query in the form of key/value.

        :is_public: Filter volume types based on visibility:

            * **True**: List public volume types only
            * **False**: List private volume types only
            * **None**: List both public and private volume types

    :returns: list of matching volume types
    """

    return IMPL.volume_type_get_all(context, inactive, filters)


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


def volume_get_active_by_window(context, begin, end=None, project_id=None):
    """Get all the volumes inside the window.

    Specifying a project_id will filter for a certain project.
    """
    return IMPL.volume_get_active_by_window(context, begin, end, project_id)


def volume_type_access_get_all(context, type_id):
    """Get all volume type access of a volume type."""
    return IMPL.volume_type_access_get_all(context, type_id)


def volume_type_access_add(context, type_id, project_id):
    """Add volume type access for project."""
    return IMPL.volume_type_access_add(context, type_id, project_id)


def volume_type_access_remove(context, type_id, project_id):
    """Remove volume type access for project."""
    return IMPL.volume_type_access_remove(context, type_id, project_id)


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


def qos_specs_get_all(context, inactive=False, filters=None):
    """Get all qos_specs."""
    return IMPL.qos_specs_get_all(context, inactive, filters)


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


def quota_create(context, project_id, resource, limit, allocated=0):
    """Create a quota for the given project and resource."""
    return IMPL.quota_create(context, project_id, resource, limit,
                             allocated=allocated)


def quota_get(context, project_id, resource):
    """Retrieve a quota or raise if it does not exist."""
    return IMPL.quota_get(context, project_id, resource)


def quota_get_all_by_project(context, project_id):
    """Retrieve all quotas associated with a given project."""
    return IMPL.quota_get_all_by_project(context, project_id)


def quota_allocated_get_all_by_project(context, project_id):
    """Retrieve all allocated quotas associated with a given project."""
    return IMPL.quota_allocated_get_all_by_project(context, project_id)


def quota_allocated_update(context, project_id,
                           resource, allocated):
    """Update allocated quota to subprojects or raise if it does not exist.

    :raises: cinder.exception.ProjectQuotaNotFound
    """
    return IMPL.quota_allocated_update(context, project_id,
                                       resource, allocated)


def quota_update(context, project_id, resource, limit):
    """Update a quota or raise if it does not exist."""
    return IMPL.quota_update(context, project_id, resource, limit)


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


def quota_class_get_default(context):
    """Retrieve all default quotas."""
    return IMPL.quota_class_get_default(context)


def quota_class_get_all_by_name(context, class_name):
    """Retrieve all quotas associated with a given quota class."""
    return IMPL.quota_class_get_all_by_name(context, class_name)


def quota_class_update(context, class_name, resource, limit):
    """Update a quota class or raise if it does not exist."""
    return IMPL.quota_class_update(context, class_name, resource, limit)


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


def backup_get_all_by_project(context, project_id, filters=None, marker=None,
                              limit=None, offset=None, sort_keys=None,
                              sort_dirs=None):
    """Get all backups belonging to a project."""
    return IMPL.backup_get_all_by_project(context, project_id,
                                          filters=filters, marker=marker,
                                          limit=limit, offset=offset,
                                          sort_keys=sort_keys,
                                          sort_dirs=sort_dirs)


def backup_get_all_by_volume(context, volume_id, filters=None):
    """Get all backups belonging to a volume."""
    return IMPL.backup_get_all_by_volume(context, volume_id,
                                         filters=filters)


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


def transfer_get_all(context):
    """Get all volume transfer records."""
    return IMPL.transfer_get_all(context)


def transfer_get_all_by_project(context, project_id):
    """Get all volume transfer records for specified project."""
    return IMPL.transfer_get_all_by_project(context, project_id)


def transfer_create(context, values):
    """Create an entry in the transfers table."""
    return IMPL.transfer_create(context, values)


def transfer_destroy(context, transfer_id):
    """Destroy a record in the volume transfer table."""
    return IMPL.transfer_destroy(context, transfer_id)


def transfer_accept(context, transfer_id, user_id, project_id):
    """Accept a volume transfer."""
    return IMPL.transfer_accept(context, transfer_id, user_id, project_id)


###################


def consistencygroup_get(context, consistencygroup_id):
    """Get a consistencygroup or raise if it does not exist."""
    return IMPL.consistencygroup_get(context, consistencygroup_id)


def consistencygroup_get_all(context):
    """Get all consistencygroups."""
    return IMPL.consistencygroup_get_all(context)


def consistencygroup_create(context, values):
    """Create a consistencygroup from the values dictionary."""
    return IMPL.consistencygroup_create(context, values)


def consistencygroup_get_all_by_project(context, project_id):
    """Get all consistencygroups belonging to a project."""
    return IMPL.consistencygroup_get_all_by_project(context, project_id)


def consistencygroup_update(context, consistencygroup_id, values):
    """Set the given properties on a consistencygroup and update it.

    Raises NotFound if consistencygroup does not exist.
    """
    return IMPL.consistencygroup_update(context, consistencygroup_id, values)


def consistencygroup_destroy(context, consistencygroup_id):
    """Destroy the consistencygroup or raise if it does not exist."""
    return IMPL.consistencygroup_destroy(context, consistencygroup_id)


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


def purge_deleted_rows(context, age_in_days):
    """Purge deleted rows older than given age from cinder tables

    Raises InvalidParameterValue if age_in_days is incorrect.
    :returns: number of deleted rows
    """
    return IMPL.purge_deleted_rows(context, age_in_days=age_in_days)


def get_booleans_for_table(table_name):
    return IMPL.get_booleans_for_table(table_name)


###################


def driver_initiator_data_update(context, initiator, namespace, updates):
    """Create DriverPrivateData from the values dictionary."""
    return IMPL.driver_initiator_data_update(context, initiator,
                                             namespace, updates)


def driver_initiator_data_get(context, initiator, namespace):
    """Query for an DriverPrivateData that has the specified key"""
    return IMPL.driver_initiator_data_get(context, initiator, namespace)


###################


def image_volume_cache_create(context, host, image_id, image_updated_at,
                              volume_id, size):
    """Create a new image volume cache entry."""
    return IMPL.image_volume_cache_create(context,
                                          host,
                                          image_id,
                                          image_updated_at,
                                          volume_id,
                                          size)


def image_volume_cache_delete(context, volume_id):
    """Delete an image volume cache entry specified by volume id."""
    return IMPL.image_volume_cache_delete(context, volume_id)


def image_volume_cache_get_and_update_last_used(context, image_id, host):
    """Query for an image volume cache entry."""
    return IMPL.image_volume_cache_get_and_update_last_used(context,
                                                            image_id,
                                                            host)


def image_volume_cache_get_by_volume_id(context, volume_id):
    """Query to see if a volume id is an image-volume contained in the cache"""
    return IMPL.image_volume_cache_get_by_volume_id(context, volume_id)


def image_volume_cache_get_all_for_host(context, host):
    """Query for all image volume cache entry for a host."""
    return IMPL.image_volume_cache_get_all_for_host(context, host)
