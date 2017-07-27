REST API Version History
========================

This documents the changes made to the REST API with every
microversion change. The description for each version should be a
verbose one which has enough information to be suitable for use in
user documentation.

3.0
---
  The 3.0 Cinder API includes all v2 core APIs existing prior to
  the introduction of microversions.  The /v3 URL is used to call
  3.0 APIs.
  This is the initial version of the Cinder API which supports
  microversions.

  A user can specify a header in the API request::

    OpenStack-API-Version: volume <version>

  where ``<version>`` is any valid api version for this API.

  If no version is specified then the API will behave as if version 3.0
  was requested.

  The only API change in version 3.0 is versions, i.e.
  GET http://localhost:8786/, which now returns information about
  3.0 and later versions and their respective /v3 endpoints.

  All other 3.0 APIs are functionally identical to version 2.0.

3.1
---
  Added the parameters ``protected`` and ``visibility`` to
  _volume_upload_image requests.

3.2
---
  Change in return value of 'GET API request' for fetching cinder volume
  list on the basis of 'bootable' status of volume as filter.

  Before V3.2, 'GET API request' to fetch volume list returns non-bootable
  volumes if bootable filter value is any of the false or False.
  For any other value provided to this filter, it always returns
  bootable volume list.

  But in V3.2, this behavior is updated.
  In V3.2, bootable volume list will be returned for any of the
  'T/True/1/true' bootable filter values only.
  Non-bootable volume list will be returned for any of 'F/False/0/false'
  bootable filter values.
  But for any other values passed for bootable filter, it will return
  "Invalid input received: bootable={filter value}' error.

3.3
---
  Added /messages API.

3.4
---
  Added the filter parameters ``glance_metadata`` to
  list/detail volumes requests.

3.5
---
  Added pagination support to /messages API

3.6
---
  Allowed to set empty description and empty name for consistency
  group in consisgroup-update operation.

3.7
---
  Added ``cluster_name`` field to service list/detail.

  Added /clusters endpoint to list/show/update clusters.

  Show endpoint requires the cluster name and optionally the binary as a URL
  parameter (default is "cinder-volume").  Returns:

  .. code-block:: json

     {
         "cluster": {
             "created_at": "",
             "disabled_reason": null,
             "last_heartbeat": "",
             "name": "cluster_name",
             "num_down_hosts": 4,
             "num_hosts": 2,
             "state": "up",
             "status": "enabled",
             "updated_at": ""
         }
     }

  Update endpoint allows enabling and disabling a cluster in a similar way to
  service's update endpoint, but in the body we must specify the name and
  optionally the binary ("cinder-volume" is the default) and the disabled
  reason. Returns:

  .. code-block:: json

     {
         "cluster": {
             "name": "cluster_name",
             "state": "up",
             "status": "enabled",
             "disabled_reason": null
         }
     }

  Index and detail accept filtering by `name`, `binary`, `disabled`,
  `num_hosts` , `num_down_hosts`, and up/down status (`is_up`) as URL
  parameters.

  Index endpoint returns:

  .. code-block:: json

     {
         "clusters": [
             {
                 "name": "cluster_name",
                 "state": "up",
                 "status": "enabled"
             }
         ]
      }

  Detail endpoint returns:

  .. code-block:: json

     {
         "clusters": [
             {
                 "created_at": "",
                 "disabled_reason": null,
                 "last_heartbeat": "",
                 "name": "cluster_name",
                 "num_down_hosts": 4,
                 "num_hosts": 2,
                 "state": "up",
                 "status": "enabled",
                 "updated_at": ""
             }
         ]
     }

3.8
---
  Adds the following resources that were previously in extensions:
  - os-volume-manage => /v3/<project_id>/manageable_volumes
  - os-snapshot-manage => /v3/<project_id>/manageable_snapshots

3.9
---
  Added backup update interface to change name and description.
  Returns:

  .. code-block:: json

     {
         "backup": {
             "id": "backup_id",
             "name": "backup_name",
             "links": "backup_link"
         }
     }

3.10
----
  Added the filter parameters ``group_id`` to
  list/detail volumes requests.

3.11
----
  Added group types and group specs APIs.

3.12
----
  Added volumes/summary API.

3.13
----
  Added create/delete/update/list/show APIs for generic volume groups.

3.14
----
  Added group snapshots and create group from src APIs.

3.15 (Maximum in Newton)
------------------------
  Added injecting the response's `Etag` header to avoid the lost update
  problem with volume metadata.

3.16
----
  os-migrate_volume now accepts ``cluster`` parameter when we want to migrate a
  volume to a cluster.  If we pass the ``host`` parameter for a volume that is
  in a cluster, the request will be sent to the cluster as if we had requested
  that specific cluster.  Only ``host`` or ``cluster`` can be provided.

  Creating a managed volume also supports the cluster parameter.

3.17
----
  os-snapshot-manage and os-volume-manage now support ``cluster`` parameter on
  listings (summary and detailed).  Both location parameters, ``cluster`` and
  ``host`` are exclusive and only one should be provided.

3.18
----
  Added backup project attribute.

3.19
----
  Added reset status actions 'reset_status' to group snapshot.

3.20
----
  Added reset status actions 'reset_status' to generic volume group.

3.21
----
  Show provider_id in detailed view of a volume for admin.

3.22
----
  Added support to filter snapshot list based on metadata of snapshot.

3.23
----
  Allow passing force parameter to volume delete.

3.24
----
  New API endpoint /workers/cleanup allows triggering cleanup for cinder-volume
  services.  Meant for cleaning ongoing operations from failed nodes.

  The cleanup will be performed by other services belonging to the same
  cluster, so at least one of them must be up to be able to do the cleanup.

  Cleanup cannot be triggered during a cloud upgrade.

  If no arguments are provided cleanup will try to issue a clean message for
  all nodes that are down, but we can restrict which nodes we want to be
  cleaned using parameters ``service_id``, ``cluster_name``, ``host``,
  ``binary``, and ``disabled``.

  Cleaning specific resources is also possible using ``resource_type`` and
  ``resource_id`` parameters.

  We can even force cleanup on nodes that are up with ``is_up``, but that's
  not recommended and should only used if you know what you are doing.  For
  example if you know a specific cinder-volume is down even though it's still
  not being reported as down when listing the services and you know the cluster
  has at least another service to do the cleanup.

  API will return a dictionary with 2 lists, one with services that have been
  issued a cleanup request (``cleaning`` key) and the other with services
  that cannot be cleaned right now because there is no alternative service to
  do the cleanup in that cluster (``unavailable`` key).

  Data returned for each service element in these two lists consist of the
  ``id``, ``host``, ``binary``, and ``cluster_name``.  These are not the
  services that will be performing the cleanup, but the services that will be
  cleaned up or couldn't be cleaned up.

3.25
----
  Add ``volumes`` field to group list/detail and group show.

3.26
----
  - New ``failover`` action equivalent to ``failover_host``, but accepting
    ``cluster`` parameter as well as the ``host`` cluster that
    ``failover_host`` accepts.

  - ``freeze`` and ``thaw`` actions accept ``cluster`` parameter.

  - Cluster listing accepts ``replication_status``, ``frozen`` and
    ``active_backend_id`` as filters, and returns additional fields for each
    cluster: ``replication_status``, ``frozen``, ``active_backend_id``.

3.27 (Maximum in Ocata)
-----------------------
  Added new attachment APIs

3.28
----
  Add filters support to get_pools

3.29
----
  Add filter, sorter and pagination support in group snapshot.

3.30
----
  Support sort snapshots with "name".

3.31
----
  Add support for configure resource query filters.

3.32
----
  Added ``set-log`` and ``get-log`` service actions.

3.33
----
  Add ``resource_filters`` API to retrieve configured resource filters.

3.34
----
  Add like filter support in ``volume``, ``backup``, ``snapshot``, ``message``,
  ``attachment``, ``group`` and ``group-snapshot`` list APIs.

3.35
----
  Add ``volume-type`` filter to Get-Pools API.

3.36
----
  Add metadata to volumes/summary response body.

3.37
----
  Support sort backup by "name".

3.38
----
  Added enable_replication/disable_replication/failover_replication/
  list_replication_targets for replication groups (Tiramisu).

3.39
----
  Add ``project_id`` admin filters support to limits.

3.40
----
  Add volume revert to its latest snapshot support.

3.41
----
  Add ``user_id`` field to snapshot list/detail and snapshot show.

3.42
----
  Add ability to extend 'in-use' volume. User should be aware of the
  whole environment before using this feature because it's dependent
  on several external factors below:

  1. nova-compute version - needs to be the latest for Pike.
  2. only the libvirt compute driver supports this currently.
  3. only iscsi and fibre channel volume types are supported on the
     nova side currently.

  Administrator can disable this ability by updating the
  ``volume:extend_attached_volume`` policy rule.  Extend of a resered
  Volume is NOT allowed.

3.43
----
  Support backup CRUD with metadata.
