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
  This it the initial version of the Cinder API which supports
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
  bootable volumes list.

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
  paramter (default is "cinder-volume").  Returns:

  .. code-block:: json

     "cluster": {
         "created_at": ...,
         "disabled_reason": null,
         "last_heartbeat": ...,
         "name": "cluster_name",
         "num_down_hosts": 4,
         "num_hosts": 2,
         "state": "up",
         "status": "enabled",
         "updated_at": ...
     }

  Update endpoint allows enabling and disabling a cluster in a similar way to
  service's update endpoint, but in the body we must specify the name and
  optionally the binary ("cinder-volume" is the default) and the disabled
  reason. Returns:

  .. code-block:: json

     "cluster": {
         "name": "cluster_name",
         "state": "up",
         "status": "enabled"
         "disabled_reason": null
     }

  Index and detail accept filtering by `name`, `binary`, `disabled`,
  `num_hosts` , `num_down_hosts`, and up/down status (`is_up`) as URL
  parameters.

  Index endpoint returns:

  .. code-block:: json

     "clusters": [
         {
             "name": "cluster_name",
             "state": "up",
             "status": "enabled"
         },
         {
             ...
         }
     ]

  Detail endpoint returns:

  .. code-block:: json

     "clusters": [
         {
             "created_at": ...,
             "disabled_reason": null,
             "last_heartbeat": ...,
             "name": "cluster_name",
             "num_down_hosts": 4,
             "num_hosts": 2,
             "state": "up",
             "status": "enabled",
             "updated_at": ...
         },
         {
             ...
         }
     ]

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

     "backup": {
         "id": "backup_id",
         "name": "backup_name",
         "links": "backup_link",
     }

3.10
----
  Added the filter parameters ``group_id`` to
  list/detail volumes requests.

3.11
----
  Added group types and group specs API.

3.12
----
  Added volumes/summary API.

3.13
----
  Added create/delete/update/list/show APIs for generic volume groups.

3.14
  Added group snapshots and create group from src APIs.
---

3.15
  Added injecting the response's `Etag` header to avoid the lost update
  problem with volume metadata.
