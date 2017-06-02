Generalized filters
===================

Background
----------

Cinder introduced generalized resource filters since Pike, it has the
same purpose as ``query_volume_filters`` option, but it's more convenient
and can be applied to more cinder resources, administrator can control the
allowed filter keys for **non-admin** user by editing the filter
configuration file. Also since this feature, cinder will raise
``400 BadRequest`` if any invalid query filter is specified.

How do I configure the filter keys?
-----------------------------------

``resource_query_filters_file`` is introduced to cinder to represent the
filter config file path, and the config file accepts the valid filter keys
for **non-admin** user with json format:

.. code-block:: json

    {
       "volume": ["name", "status", "metadata"]
    }


the key ``volume`` (singular) here stands for the resource you want to apply and the value
accepts an list which contains the allowed filters collection, once the configuration
file is changed and API service is restarted, cinder will only recognize this filter
keys, **NOTE**: the default configuration file will include all the filters we already
enabled.

Which filter keys are supported?
--------------------------------

Not all the attributes are supported at present, so we add this table below to
indicate which filter keys are valid and can be used in the configuration.

Since v3.34 we could use '~' to indicate supporting querying resource by inexact match,
for example, if we have a configuration file as below:

.. code-block:: json

    {
       "volume": ["name~"]
    }

User can query volume both by ``name=volume`` and ``name~=volume``, and the volumes
named ``volume123`` and ``a_volume123`` are both valid for second input while neither are
valid for first. The supported APIs are marked with "*" below in the table.

+-----------------+-------------------------------------------------------------------------+
|    API          | Valid filter keys                                                       |
+=================+=========================================================================+
|                 | id, group_id, name, status, bootable, migration_status, metadata, host, |
| list volume*    | image_metadata, availability_zone, user_id, volume_type_id, project_id, |
|                 | size, description, replication_status, multiattach                      |
+-----------------+-------------------------------------------------------------------------+
|                 | id, volume_id, user_id, project_id, status, volume_size, name,          |
| list snapshot*  | description, volume_type_id, group_snapshot_id, metadata                |
+-----------------+-------------------------------------------------------------------------+
|                 | id, name, status, container, availability_zone, description,            |
| list backup*    | volume_id, is_incremental, size, host, parent_id                        |
+-----------------+-------------------------------------------------------------------------+
|                 | id, user_id, status, availability_zone, group_type, name, description,  |
| list group*     | host                                                                    |
+-----------------+-------------------------------------------------------------------------+
| list g-snapshot*| id, name, description, group_id, group_type_id, status                  |
+-----------------+-------------------------------------------------------------------------+
|                 | id, volume_id, instance_id, attach_status, attach_mode,                 |
| list attachment*| connection_info, mountpoint, attached_host                              |
+-----------------+-------------------------------------------------------------------------+
|                 | id, event_id, resource_uuid, resource_type, request_id, message_level,  |
| list message*   | project_id                                                              |
+-----------------+-------------------------------------------------------------------------+
| get pools       | name, volume_type                                                       |
+-----------------+-------------------------------------------------------------------------+
