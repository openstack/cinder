.. -*- rst -*-

Volume snapshots (snapshots)
============================

A snapshot is a point-in-time copy of the data that a volume
contains.

When you create, list, or delete snapshots, these status values are
possible:

**Snapshot statuses**

+----------------+---------------------------------------------+
| Status         | Description                                 |
+----------------+---------------------------------------------+
| creating       | The snapshot is being created.              |
+----------------+---------------------------------------------+
| available      | The snapshot is ready to use.               |
+----------------+---------------------------------------------+
| backing-up     | The snapshot is being backed up.            |
+----------------+---------------------------------------------+
| deleting       | The snapshot is being deleted.              |
+----------------+---------------------------------------------+
| error          | A snapshot creation error occurred.         |
+----------------+---------------------------------------------+
| deleted        | The snapshot has been deleted.              |
+----------------+---------------------------------------------+
| unmanaging     | The snapshot is being unmanaged.            |
+----------------+---------------------------------------------+
| restoring      | The snapshot is being restored to a volume. |
+----------------+---------------------------------------------+
| error_deleting | A snapshot deletion error occurred.         |
+----------------+---------------------------------------------+


List snapshots with details
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v2/{tenant_id}/snapshots/detail

Lists all Block Storage snapshots, with details, that the tenant can access.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id


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


Create snapshot
~~~~~~~~~~~~~~~

.. rest_method::  POST /v2/{tenant_id}/snapshots

Creates a volume snapshot, which is a point-in-time, complete copy of a volume. You can create a volume from a snapshot.

Normal response codes: 202,


Request
-------

.. rest_parameters:: parameters.yaml

   - snapshot: snapshot
   - volume_id: volume_id
   - force: force
   - description: description
   - name: name
   - tenant_id: tenant_id

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


List snapshots
~~~~~~~~~~~~~~

.. rest_method::  GET /v2/{tenant_id}/snapshots

Lists all Block Storage snapshots, with summary information, that the tenant can access.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - sort_key: sort_key
   - sort_dir: sort_dir
   - limit: limit
   - offset: offset
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


Show snapshot metadata
~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v2/{tenant_id}/snapshots/{snapshot_id}/metadata

Shows metadata for a snapshot.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
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


Create snapshot metadata
~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v2/{tenant_id}/snapshots/{snapshot_id}/metadata

Updates metadata for a snapshot.

Creates or replaces metadata items that match keys. Does not modify items that
are not in the request.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - metadata: metadata
   - tenant_id: tenant_id
   - snapshot_id: snapshot_id

Request Example
---------------

.. literalinclude:: ./samples/snapshot-metadata-create-request.json
   :language: javascript


Response Example
----------------

.. literalinclude:: ./samples/snapshot-metadata-create-response.json
   :language: javascript


Update snapshot metadata
~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  PUT /v2/{tenant_id}/snapshots/{snapshot_id}/metadata

Replaces all the snapshot's metadata with the key-value pairs in the request.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - metadata: metadata
   - tenant_id: tenant_id
   - snapshot_id: snapshot_id

Request Example
---------------

.. literalinclude:: ./samples/snapshot-metadata-update-request.json
   :language: javascript


Response Example
----------------

.. literalinclude:: ./samples/snapshot-metadata-update-response.json
   :language: javascript


Show snapshot details
~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v2/{tenant_id}/snapshots/{snapshot_id}

Shows details for a snapshot.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
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


Update snapshot
~~~~~~~~~~~~~~~

.. rest_method::  PUT /v2/{tenant_id}/snapshots/{snapshot_id}

Updates a snapshot.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - snapshot: snapshot
   - description: description
   - name: name
   - tenant_id: tenant_id
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


Delete snapshot
~~~~~~~~~~~~~~~

.. rest_method::  DELETE /v2/{tenant_id}/snapshots/{snapshot_id}

Deletes a snapshot.

Normal response codes: 202,


Request
-------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - snapshot_id: snapshot_id
