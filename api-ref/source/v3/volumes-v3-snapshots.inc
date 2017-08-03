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


List snapshots and details
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/snapshots/detail

Lists all Block Storage snapshots, with details, that the project can access,
since v3.31 if non-admin users specify invalid filters in the url, API will
return bad request.


Normal response codes: 200
Error response codes: badRequest(400)


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - sort_key: sort_key
   - sort_dir: sort_dir
   - limit: limit
   - offset: offset
   - marker: marker


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - status: status_2
   - os-extended-snapshot-attributes:progress: os-extended-snapshot-attributes:progress
   - description: description
   - created_at: created_at
   - name: name
   - user_id: user_id_2
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
~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/snapshots

Creates a volume snapshot, which is a point-in-time, complete copy of a volume. You can create a volume from a snapshot.

Normal response codes: 202


Request
-------

.. rest_parameters:: parameters.yaml

   - snapshot: snapshot
   - volume_id: volume_id
   - force: force
   - description: description
   - name: name
   - project_id: project_id_path
   - metadata: metadata_7

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
   - user_id: user_id_2
   - volume_id: volume_id
   - metadata: metadata
   - id: id
   - size: size
   - updated_at: updated_at

Response Example
----------------

.. literalinclude:: ./samples/snapshot-create-response.json
   :language: javascript


List accessible snapshots
~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/snapshots

Lists all Block Storage snapshots, with summary information,
that the project can access, since v3.31 if non-admin users
specify invalid filters in the url, API will return bad request.


Normal response codes: 200
Error response codes: badRequest(400)


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
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
   - user_id: user_id_2
   - volume_id: volume_id
   - metadata: metadata
   - id: id
   - size: size

Response Example
----------------

.. literalinclude:: ./samples/snapshots-list-response.json
   :language: javascript


Show a snapshot's metadata
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/snapshots/{snapshot_id}/metadata

Shows metadata for a snapshot.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - snapshot_id: snapshot_id_path


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


Create a snapshot's metadata
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/snapshots/{snapshot_id}/metadata

Updates metadata for a snapshot.

Creates or replaces metadata items that match keys. Does not modify items that
are not in the request.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - metadata: metadata
   - project_id: project_id_path
   - snapshot_id: snapshot_id_path

Request Example
---------------

.. literalinclude:: ./samples/snapshot-metadata-create-request.json
   :language: javascript


Response Example
----------------

.. literalinclude:: ./samples/snapshot-metadata-create-response.json
   :language: javascript

Update a snapshot's metadata
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  PUT /v3/{project_id}/snapshots/{snapshot_id}/metadata

Replaces all the snapshot's metadata with the key-value pairs in the request.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - metadata: metadata
   - project_id: project_id_path
   - snapshot_id: snapshot_id_path

Request Example
---------------

.. literalinclude:: ./samples/snapshot-metadata-update-request.json
   :language: javascript


Response Example
----------------

.. literalinclude:: ./samples/snapshot-metadata-update-response.json
   :language: javascript


Show a snapshot's details
~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/snapshots/{snapshot_id}

Shows details for a snapshot.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - snapshot_id: snapshot_id_path


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - status: status_2
   - os-extended-snapshot-attributes:progress: os-extended-snapshot-attributes:progress
   - description: description
   - created_at: created_at
   - name: name
   - snapshot: snapshot
   - user_id: user_id_2
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
~~~~~~~~~~~~~~~~~

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
   - snapshot_id: snapshot_id_path

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
   - user_id: user_id_2
   - volume_id: volume_id
   - metadata: metadata
   - id: id
   - size: size

Response Example
----------------

.. literalinclude:: ./samples/snapshot-update-response.json
   :language: javascript


Delete a snapshot
~~~~~~~~~~~~~~~~~

.. rest_method::  DELETE /v3/{project_id}/snapshots/{snapshot_id}

Deletes a snapshot.

Normal response codes: 202


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - snapshot_id: snapshot_id_path




Show a snapshot's metadata for a specific key
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/snapshot/{snapshot_id}/metadata/{key}

Shows metadata for a snapshot for a specific key.

Normal response codes: 200


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - snapshot_id: snapshot_id_path
   - key: key_2


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - meta: meta_1



Response Example
----------------

.. literalinclude:: ./samples/snapshot-metadata-show-key-response.json
   :language: javascript



Delete a snapshot's metadata
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  DELETE /v3/{project_id}/snapshots/{snapshot_id}/metadata/{key}

Deletes metadata for a snapshot.

Normal response codes: 200


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - snapshot_id: snapshot_id_path
   - key: key_1


Update a snapshot's metadata for a specific key
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  PUT /v3/{project_id}/snapshots/{snapshot_id}/metadata/{key}

Update metadata for a snapshot for a specific key.

Normal response codes: 200


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - snapshot_id: snapshot_id_path
   - key: key_3
   - meta: meta_1

Request Example
---------------

.. literalinclude:: ./samples/snapshot-metadata-update-key-request.json
   :language: javascript

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - meta: meta_1

Response Example
----------------

.. literalinclude:: ./samples/snapshot-metadata-update-key-response.json
   :language: javascript
