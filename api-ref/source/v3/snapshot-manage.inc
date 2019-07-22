.. -*- rst -*-

Snapshot manage extension (manageable_snapshots)
================================================

Creates or lists snapshots by using existing storage instead of allocating new
storage.


Manage an existing snapshot
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/manageable_snapshots

Creates a snapshot by using existing storage rather than allocating new
storage.

The caller must specify a reference to an existing storage volume
in the ref parameter in the request. Although each storage driver
might interpret this reference differently, the driver should
accept a reference structure that contains either a source-id
or source-name element, if possible.

The API chooses the size of the snapshot by rounding up the size of
the existing snapshot to the next gibibyte (GiB).


Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - snapshot: snapshot_obj
   - description: description_snap
   - metadata: metadata_snap
   - name: name_snap
   - ref: ref
   - volume_id: volume_id

Request Example
---------------

.. literalinclude:: ./samples/snapshot_manage_extensions/snapshot-manage-request.json
   :language: javascript


Response
--------

.. rest_parameters:: parameters.yaml

  - snapshot: snapshot_obj
  - status: status_snap
  - size: size
  - metadata: metadata_snap
  - name: name_snap
  - volume_id: volume_id
  - created_at: created_at
  - description: description_snap_req
  - id: id
  - updated_at: updated_at

Response Example
----------------

.. literalinclude:: ./samples/snapshot_manage_extensions/snapshot-manage-response.json
   :language: javascript


List summary of snapshots available to manage
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/manageable_snapshots

Search a volume backend and list summary of snapshots which are available to
manage.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - sort: sort
   - offset: offset
   - limit: limit
   - marker: marker
   - host: host_query


Response
--------

.. rest_parameters:: parameters.yaml

   - manageable-snapshots: manageable-snapshots
   - source_reference: source_reference
   - safe_to_manage: safe_to_manage
   - reference: reference
   - source-name: source-name
   - size: size


Response Example
----------------

.. literalinclude:: ./samples/snapshot-manage-list-response.json
   :language: javascript



List detail of snapshots available to manage
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/manageable_snapshots/detail

Search a volume backend and list detail of snapshots which are available to
manage.


Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - sort: sort
   - offset: offset
   - limit: limit
   - marker: marker
   - host: host_query


Response
--------

.. rest_parameters:: parameters.yaml

   - manageable-snapshots: manageable-snapshots
   - cinder_id: cinder_id
   - source_reference: source_reference
   - safe_to_manage: safe_to_manage
   - reason_not_safe: reason_not_safe
   - reference: reference
   - source-name: source-name
   - size: size
   - extra_info: extra_info


Response Example
----------------

.. literalinclude:: ./samples/snapshot-manage-list-detail-response.json
   :language: javascript
