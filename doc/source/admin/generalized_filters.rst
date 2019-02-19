===================
Generalized filters
===================

Background
----------

Cinder introduced generalized resource filters since Pike. Administrator can
control the allowed filter keys for **non-admin** user by editing the filter
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


the key ``volume`` (singular) here stands for the resource you want to apply
and the value accepts an list which contains the allowed filters collection,
once the configuration file is changed and API service is restarted, cinder
will only recognize this filter keys, **NOTE**: the default configuration file
will include all the filters we already enabled.

Which filter keys are supported?
--------------------------------

Not all the attributes are supported at present, so we add this table below to
indicate which filter keys are valid and can be used in the configuration.

Since v3.34 we could use '~' to indicate supporting querying resource by
inexact match, for example, if we have a configuration file as below:

.. code-block:: json

    {
       "volume": ["name~"]
    }

User can query volume both by ``name=volume`` and ``name~=volume``, and the
volumes named ``volume123`` and ``a_volume123`` are both valid for second input
while neither are valid for first. The supported APIs are marked with "*" below
in the table.

.. list-table::
   :header-rows: 1

   * - API
     - Valid filter keys
   * - list volume*
     - id, group_id, name, status, bootable, migration_status, metadata, host,
       image_metadata, availability_zone, user_id, volume_type_id, project_id,
       size, description, replication_status, multiattach
   * - list snapshot*
     - id, volume_id, user_id, project_id, status, volume_size, name,
       description, volume_type_id, group_snapshot_id, metadata,
       availability_zone
   * - list backup*
     - id, name, status, container, availability_zone, description, volume_id,
       is_incremental, size, host, parent_id
   * - list group*
     - id, user_id, status, availability_zone, group_type, name, description,
       host
   * - list g-snapshot*
     - id, name, description, group_id, group_type_id, status
   * - list attachment*
     - id, volume_id, instance_id, attach_status, attach_mode, connection_info,
       mountpoint, attached_host
   * - list message*
     - id, event_id, resource_uuid, resource_type, request_id, message_level,
       project_id
   * - get pools
     - name, volume_type
   * - list types (3.51)
     - is_public, extra_specs
