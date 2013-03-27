# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

The underlying driver is loaded as a :class:`LazyPluggable`.

Functions in this module are imported into the cinder.db namespace. Call these
functions from cinder.db namespace, not the cinder.db.api namespace.

All functions in this module return objects that implement a dictionary-like
interface. Currently, many of these objects are sqlalchemy objects that
implement a dictionary interface. However, a future goal is to have all of
these objects be simple dictionaries.


**Related Flags**

:db_backend:  string to lookup in the list of LazyPluggable backends.
              `sqlalchemy` is the only supported backend right now.

:sql_connection:  string specifying the sqlalchemy connection to use, like:
                  `sqlite:///var/lib/cinder/cinder.sqlite`.

:enable_new_services:  when adding a new service to the database, is it in the
                       pool of available hardware (Default: True)

"""

from oslo.config import cfg

from cinder import exception
from cinder import flags
from cinder import utils

db_opts = [
    cfg.StrOpt('db_backend',
               default='sqlalchemy',
               help='The backend to use for db'),
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

FLAGS = flags.FLAGS
FLAGS.register_opts(db_opts)

IMPL = utils.LazyPluggable('db_backend',
                           sqlalchemy='cinder.db.sqlalchemy.api')


class NoMoreTargets(exception.CinderException):
    """No more available targets"""
    pass


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


def service_get_all_by_topic(context, topic):
    """Get all services for a given topic."""
    return IMPL.service_get_all_by_topic(context, topic)


def service_get_all_by_host(context, host):
    """Get all services for a given host."""
    return IMPL.service_get_all_by_host(context, host)


def service_get_all_volume_sorted(context):
    """Get all volume services sorted by volume count.

    :returns: a list of (Service, volume_count) tuples.

    """
    return IMPL.service_get_all_volume_sorted(context)


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
def migration_update(context, id, values):
    """Update a migration instance."""
    return IMPL.migration_update(context, id, values)


def migration_create(context, values):
    """Create a migration record."""
    return IMPL.migration_create(context, values)


def migration_get(context, migration_id):
    """Finds a migration by the id."""
    return IMPL.migration_get(context, migration_id)


def migration_get_by_instance_and_status(context, instance_uuid, status):
    """Finds a migration by the instance uuid its migrating."""
    return IMPL.migration_get_by_instance_and_status(context,
                                                     instance_uuid,
                                                     status)


def migration_get_all_unconfirmed(context, confirm_window):
    """Finds all unconfirmed migrations within the confirmation window."""
    return IMPL.migration_get_all_unconfirmed(context, confirm_window)


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

def volume_allocate_iscsi_target(context, volume_id, host):
    """Atomically allocate a free iscsi_target from the pool."""
    return IMPL.volume_allocate_iscsi_target(context, volume_id, host)


def volume_attached(context, volume_id, instance_id, mountpoint):
    """Ensure that a volume is set as attached."""
    return IMPL.volume_attached(context, volume_id, instance_id, mountpoint)


def volume_create(context, values):
    """Create a volume from the values dictionary."""
    return IMPL.volume_create(context, values)


def volume_data_get_for_host(context, host, session=None):
    """Get (volume_count, gigabytes) for project."""
    return IMPL.volume_data_get_for_host(context,
                                         host,
                                         session)


def volume_data_get_for_project(context, project_id, session=None):
    """Get (volume_count, gigabytes) for project."""
    return IMPL.volume_data_get_for_project(context,
                                            project_id,
                                            session)


def volume_destroy(context, volume_id):
    """Destroy the volume or raise if it does not exist."""
    return IMPL.volume_destroy(context, volume_id)


def volume_detached(context, volume_id):
    """Ensure that a volume is set as detached."""
    return IMPL.volume_detached(context, volume_id)


def volume_get(context, volume_id):
    """Get a volume or raise if it does not exist."""
    return IMPL.volume_get(context, volume_id)


def volume_get_all(context, marker, limit, sort_key, sort_dir):
    """Get all volumes."""
    return IMPL.volume_get_all(context, marker, limit, sort_key, sort_dir)


def volume_get_all_by_host(context, host):
    """Get all volumes belonging to a host."""
    return IMPL.volume_get_all_by_host(context, host)


def volume_get_all_by_instance_uuid(context, instance_uuid):
    """Get all volumes belonging to a instance."""
    return IMPL.volume_get_all_by_instance_uuid(context, instance_uuid)


def volume_get_all_by_project(context, project_id, marker, limit, sort_key,
                              sort_dir):
    """Get all volumes belonging to a project."""
    return IMPL.volume_get_all_by_project(context, project_id, marker, limit,
                                          sort_key, sort_dir)


def volume_get_iscsi_target_num(context, volume_id):
    """Get the target num (tid) allocated to the volume."""
    return IMPL.volume_get_iscsi_target_num(context, volume_id)


def volume_update(context, volume_id, values):
    """Set the given properties on an volume and update it.

    Raises NotFound if volume does not exist.

    """
    return IMPL.volume_update(context, volume_id, values)


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


def snapshot_get_all(context):
    """Get all snapshots."""
    return IMPL.snapshot_get_all(context)


def snapshot_get_all_by_project(context, project_id):
    """Get all snapshots belonging to a project."""
    return IMPL.snapshot_get_all_by_project(context, project_id)


def snapshot_get_all_for_volume(context, volume_id):
    """Get all snapshots for a volume."""
    return IMPL.snapshot_get_all_for_volume(context, volume_id)


def snapshot_update(context, snapshot_id, values):
    """Set the given properties on an snapshot and update it.

    Raises NotFound if snapshot does not exist.

    """
    return IMPL.snapshot_update(context, snapshot_id, values)


def snapshot_data_get_for_project(context, project_id, session=None):
    """Get count and gigabytes used for snapshots for specified project."""
    return IMPL.snapshot_data_get_for_project(context,
                                              project_id,
                                              session)


def snapshot_get_active_by_window(context, begin, end=None, project_id=None):
    """Get all the snapshots inside the window.

    Specifying a project_id will filter for a certain project."""
    return IMPL.snapshot_get_active_by_window(context, begin, end, project_id)


####################


def snapshot_metadata_get(context, snapshot_id):
    """Get all metadata for a snapshot."""
    return IMPL.snapshot_metadata_get(context, snapshot_id)


def snapshot_metadata_delete(context, snapshot_id, key):
    """Delete the given metadata item."""
    IMPL.snapshot_metadata_delete(context, snapshot_id, key)


def snapshot_metadata_update(context, snapshot_id, metadata, delete):
    """Update metadata if it exists, otherwise create it."""
    IMPL.snapshot_metadata_update(context, snapshot_id, metadata, delete)


####################


def volume_metadata_get(context, volume_id):
    """Get all metadata for a volume."""
    return IMPL.volume_metadata_get(context, volume_id)


def volume_metadata_delete(context, volume_id, key):
    """Delete the given metadata item."""
    IMPL.volume_metadata_delete(context, volume_id, key)


def volume_metadata_update(context, volume_id, metadata, delete):
    """Update metadata if it exists, otherwise create it."""
    IMPL.volume_metadata_update(context, volume_id, metadata, delete)


##################


def volume_type_create(context, values):
    """Create a new volume type."""
    return IMPL.volume_type_create(context, values)


def volume_type_get_all(context, inactive=False):
    """Get all volume types."""
    return IMPL.volume_type_get_all(context, inactive)


def volume_type_get(context, id):
    """Get volume type by id."""
    return IMPL.volume_type_get(context, id)


def volume_type_get_by_name(context, name):
    """Get volume type by name."""
    return IMPL.volume_type_get_by_name(context, name)


def volume_type_destroy(context, id):
    """Delete a volume type."""
    return IMPL.volume_type_destroy(context, id)


def volume_get_active_by_window(context, begin, end=None, project_id=None):
    """Get all the volumes inside the window.

    Specifying a project_id will filter for a certain project."""
    return IMPL.volume_get_active_by_window(context, begin, end, project_id)


####################


def volume_type_extra_specs_get(context, volume_type_id):
    """Get all extra specs for a volume type."""
    return IMPL.volume_type_extra_specs_get(context, volume_type_id)


def volume_type_extra_specs_delete(context, volume_type_id, key):
    """Delete the given extra specs item."""
    IMPL.volume_type_extra_specs_delete(context, volume_type_id, key)


def volume_type_extra_specs_update_or_create(context,
                                             volume_type_id,
                                             extra_specs):
    """Create or update volume type extra specs. This adds or modifies the
    key/value pairs specified in the extra specs dict argument"""
    IMPL.volume_type_extra_specs_update_or_create(context,
                                                  volume_type_id,
                                                  extra_specs)


###################


def volume_glance_metadata_create(context, volume_id, key, value):
    """Update the Glance metadata for the specified volume."""
    return IMPL.volume_glance_metadata_create(context,
                                              volume_id,
                                              key,
                                              value)


def volume_glance_metadata_get(context, volume_id):
    """Return the glance metadata for a volume."""
    return IMPL.volume_glance_metadata_get(context, volume_id)


def volume_snapshot_glance_metadata_get(context, snapshot_id):
    """Return the Glance metadata for the specified snapshot."""
    return IMPL.volume_snapshot_glance_metadata_get(context, snapshot_id)


def volume_glance_metadata_copy_to_snapshot(context, snapshot_id, volume_id):
    """
    Update the Glance metadata for a snapshot by copying all of the key:value
    pairs from the originating volume. This is so that a volume created from
    the snapshot will retain the original metadata.
    """
    return IMPL.volume_glance_metadata_copy_to_snapshot(context, snapshot_id,
                                                        volume_id)


def volume_glance_metadata_copy_to_volume(context, volume_id, snapshot_id):
    """
    Update the Glance metadata from a volume (created from a snapshot) by
    copying all of the key:value pairs from the originating snapshot. This is
    so that the Glance metadata from the original volume is retained.
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
    """
    Update the Glance metadata for a volume by copying all of the key:value
    pairs from the originating volume. This is so that a volume created from
    the volume (clone) will retain the original metadata.
    """
    return IMPL.volume_glance_metadata_copy_from_volume_to_volume(
        context,
        src_volume_id,
        volume_id)

###################


def sm_backend_conf_create(context, values):
    """Create a new SM Backend Config entry."""
    return IMPL.sm_backend_conf_create(context, values)


def sm_backend_conf_update(context, sm_backend_conf_id, values):
    """Update a SM Backend Config entry."""
    return IMPL.sm_backend_conf_update(context, sm_backend_conf_id, values)


def sm_backend_conf_delete(context, sm_backend_conf_id):
    """Delete a SM Backend Config."""
    return IMPL.sm_backend_conf_delete(context, sm_backend_conf_id)


def sm_backend_conf_get(context, sm_backend_conf_id):
    """Get a specific SM Backend Config."""
    return IMPL.sm_backend_conf_get(context, sm_backend_conf_id)


def sm_backend_conf_get_by_sr(context, sr_uuid):
    """Get a specific SM Backend Config."""
    return IMPL.sm_backend_conf_get_by_sr(context, sr_uuid)


def sm_backend_conf_get_all(context):
    """Get all SM Backend Configs."""
    return IMPL.sm_backend_conf_get_all(context)


####################


def sm_flavor_create(context, values):
    """Create a new SM Flavor entry."""
    return IMPL.sm_flavor_create(context, values)


def sm_flavor_update(context, sm_flavor_id, values):
    """Update a SM Flavor entry."""
    return IMPL.sm_flavor_update(context, values)


def sm_flavor_delete(context, sm_flavor_id):
    """Delete a SM Flavor."""
    return IMPL.sm_flavor_delete(context, sm_flavor_id)


def sm_flavor_get(context, sm_flavor):
    """Get a specific SM Flavor."""
    return IMPL.sm_flavor_get(context, sm_flavor)


def sm_flavor_get_all(context):
    """Get all SM Flavors."""
    return IMPL.sm_flavor_get_all(context)


####################


def sm_volume_create(context, values):
    """Create a new child Zone entry."""
    return IMPL.sm_volume_create(context, values)


def sm_volume_update(context, volume_id, values):
    """Update a child Zone entry."""
    return IMPL.sm_volume_update(context, values)


def sm_volume_delete(context, volume_id):
    """Delete a child Zone."""
    return IMPL.sm_volume_delete(context, volume_id)


def sm_volume_get(context, volume_id):
    """Get a specific child Zone."""
    return IMPL.sm_volume_get(context, volume_id)


def sm_volume_get_all(context):
    """Get all child Zones."""
    return IMPL.sm_volume_get_all(context)

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


def quota_usage_create(context, project_id, resource, in_use, reserved,
                       until_refresh):
    """Create a quota usage for the given project and resource."""
    return IMPL.quota_usage_create(context, project_id, resource,
                                   in_use, reserved, until_refresh)


def quota_usage_get(context, project_id, resource):
    """Retrieve a quota usage or raise if it does not exist."""
    return IMPL.quota_usage_get(context, project_id, resource)


def quota_usage_get_all_by_project(context, project_id):
    """Retrieve all usage associated with a given resource."""
    return IMPL.quota_usage_get_all_by_project(context, project_id)


###################


def reservation_create(context, uuid, usage, project_id, resource, delta,
                       expire):
    """Create a reservation for the given project and resource."""
    return IMPL.reservation_create(context, uuid, usage, project_id,
                                   resource, delta, expire)


def reservation_get(context, uuid):
    """Retrieve a reservation or raise if it does not exist."""
    return IMPL.reservation_get(context, uuid)


def reservation_get_all_by_project(context, project_id):
    """Retrieve all reservations associated with a given project."""
    return IMPL.reservation_get_all_by_project(context, project_id)


def reservation_destroy(context, uuid):
    """Destroy the reservation or raise if it does not exist."""
    return IMPL.reservation_destroy(context, uuid)


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


def quota_destroy_all_by_project(context, project_id):
    """Destroy all quotas associated with a given project."""
    return IMPL.quota_destroy_all_by_project(context, project_id)


def reservation_expire(context):
    """Roll back any expired reservations."""
    return IMPL.reservation_expire(context)


###################


def backup_get(context, backup_id):
    """Get a backup or raise if it does not exist."""
    return IMPL.backup_get(context, backup_id)


def backup_get_all(context):
    """Get all backups."""
    return IMPL.backup_get_all(context)


def backup_get_all_by_host(context, host):
    """Get all backups belonging to a host."""
    return IMPL.backup_get_all_by_host(context, host)


def backup_create(context, values):
    """Create a backup from the values dictionary."""
    return IMPL.backup_create(context, values)


def backup_get_all_by_project(context, project_id):
    """Get all backups belonging to a project."""
    return IMPL.backup_get_all_by_project(context, project_id)


def backup_update(context, backup_id, values):
    """
    Set the given properties on a backup and update it.

    Raises NotFound if backup does not exist.
    """
    return IMPL.backup_update(context, backup_id, values)


def backup_destroy(context, backup_id):
    """Destroy the backup or raise if it does not exist."""
    return IMPL.backup_destroy(context, backup_id)
