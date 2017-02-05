.. -*- rst -*-

============================
Volume snapshots (snapshots)
============================

A snapshot is a point-in-time copy of the data that a volume
contains.

When you create, list, or delete snapshots, these status values are
possible:

**Snapshot statuses**

+----------------+-------------------------------------+
| Status         | Description                         |
+----------------+-------------------------------------+
| creating       | The snapshot is being created.      |
+----------------+-------------------------------------+
| available      | The snapshot is ready to use.       |
+----------------+-------------------------------------+
| deleting       | The snapshot is being deleted.      |
+----------------+-------------------------------------+
| error          | A snapshot creation error occurred. |
+----------------+-------------------------------------+
| error_deleting | A snapshot deletion error occurred. |
+----------------+-------------------------------------+


List snapshots and details
==========================

.. rest_method::  GET /v3/{project_id}/snapshots/detail

Lists all Block Storage snapshots, with details, that the project can access.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - status: status_2
   - os-extended-snapshot-attributes:progress: os-extended-snapshot-attributes:progress
   - description: description
   - created_at: created_at
   - name: name
   - volume_id: volume_id
   - os-extended-snapshot-attributes:project_id: os-extended-snapshot-attributes:project_id
   - size: size
   - id: id
   - metadata: metadata

Response Example
----------------

.. literalinclude:: ./samples/snapshots-list-detailed-response.json
   :language: javascript


Create a snapshot
=================

.. rest_method::  POST /v3/{project_id}/snapshots

Creates a volume snapshot, which is a point-in-time, complete copy of a volume. You can create a volume from a snapshot.

Error response codes:202,


Request
-------

.. rest_parameters:: parameters.yaml

   - snapshot: snapshot
   - volume_id: volume_id
   - force: force
   - description: description
   - name: name
   - project_id: project_id_path

Request Example
---------------

.. literalinclude:: ./samples/snapshot-create-request.json
   :language: javascript

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - status: status_2
   - description: description
   - created_at: created_at
   - name: name
   - snapshot: snapshot
   - volume_id: volume_id
   - metadata: metadata
   - id: id
   - size: size


List accessible snapshots
=========================

.. rest_method::  GET /v3/{project_id}/snapshots

Lists all Block Storage snapshots, with summary information, that the project can access.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - sort_key: sort_key
   - sort_dir: sort_dir
   - limit: limit
   - marker: marker


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - status: status_2
   - description: description
   - created_at: created_at
   - name: name
   - volume_id: volume_id
   - metadata: metadata
   - id: id
   - size: size

Response Example
----------------

.. literalinclude:: ./samples/snapshots-list-response.json
   :language: javascript


Show a snapshot's metadata
==========================

.. rest_method::  GET /v3/{project_id}/snapshots/{snapshot_id}/metadata

Shows metadata for a snapshot.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - snapshot_id: snapshot_id


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - status: status_2
   - os-extended-snapshot-attributes:progress: os-extended-snapshot-attributes:progress
   - description: description
   - created_at: created_at
   - name: name
   - snapshot: snapshot
   - volume_id: volume_id
   - os-extended-snapshot-attributes:project_id: os-extended-snapshot-attributes:project_id
   - size: size
   - id: id
   - metadata: metadata

Response Example
----------------

.. literalinclude:: ./samples/snapshot-metadata-show-response.json
   :language: javascript


Update a snapshot's metadata
============================

.. rest_method::  PUT /v3/{project_id}/snapshots/{snapshot_id}/metadata

Updates metadata for a snapshot.

Replaces metadata items that match keys. Does not modify items that
are not in the request.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - metadata: metadata
   - project_id: project_id_path
   - snapshot_id: snapshot_id

Request Example
---------------

.. literalinclude:: ./samples/snapshot-metadata-update-request.json
   :language: javascript


Response Example
----------------

.. literalinclude:: ./samples/snapshot-metadata-update-response.json
   :language: javascript


Show a snapshot's details
=========================

.. rest_method::  GET /v3/{project_id}/snapshots/{snapshot_id}

Shows details for a snapshot.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - snapshot_id: snapshot_id


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - status: status_2
   - os-extended-snapshot-attributes:progress: os-extended-snapshot-attributes:progress
   - description: description
   - created_at: created_at
   - name: name
   - snapshot: snapshot
   - volume_id: volume_id
   - os-extended-snapshot-attributes:project_id: os-extended-snapshot-attributes:project_id
   - size: size
   - id: id
   - metadata: metadata

Response Example
----------------

.. literalinclude:: ./samples/snapshot-show-response.json
   :language: javascript


Update a snapshot
=================

.. rest_method::  PUT /v3/{project_id}/snapshots/{snapshot_id}

Updates a snapshot.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - snapshot: snapshot
   - description: description
   - name: name
   - project_id: project_id_path
   - snapshot_id: snapshot_id

Request Example
---------------

.. literalinclude:: ./samples/snapshot-update-request.json
   :language: javascript



Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - status: status_2
   - description: description
   - created_at: created_at
   - name: name
   - snapshot: snapshot
   - volume_id: volume_id
   - metadata: metadata
   - id: id
   - size: size

Response Example
----------------

.. literalinclude:: ./samples/snapshot-update-response.json
   :language: javascript


Delete a snapshot
=================

.. rest_method::  DELETE /v3/{project_id}/snapshots/{snapshot_id}

Deletes a snapshot.

Error response codes:202,


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - snapshot_id: snapshot_id
