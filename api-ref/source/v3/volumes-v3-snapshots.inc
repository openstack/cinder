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

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200

.. rest_status_code:: error ../status.yaml

   - 400


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - all_tenants: all-tenants
   - sort: sort
   - limit: limit
   - offset: offset
   - marker: marker
   - with_count: with_count


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - status: status_snap
   - os-extended-snapshot-attributes:progress: os-ext-snap-attr:progress
   - description: description_snap_req
   - created_at: created_at
   - name: name
   - user_id: user_id_min
   - volume_id: volume_id_snap
   - os-extended-snapshot-attributes:project_id: os-ext-snap-attr:project_id
   - size: size
   - id: id_snap
   - metadata: metadata
   - count: count
   - updated_at: updated_at
   - snapshots_links: links_snap

Response Example
----------------

.. literalinclude:: ./samples/snapshots/snapshots-list-detailed-response.json
   :language: javascript


Create a snapshot
~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/snapshots

Creates a volume snapshot, which is a point-in-time, complete copy of a volume.
You can create a volume from a snapshot.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - snapshot: snapshot_obj
   - volume_id: volume_id
   - name: name_snap_req
   - description: description_snap
   - force: force
   - metadata: metadata_snap

Request Example
---------------

.. literalinclude:: ./samples/snapshots/snapshot-create-request.json
   :language: javascript

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - status: status_snap
   - description: description_snap_req
   - created_at: created_at
   - name: name_snap_req
   - snapshot: snapshot_obj
   - user_id: user_id_min
   - volume_id: volume_id_snap
   - metadata: metadata
   - id: id_snap
   - size: size
   - updated_at: updated_at

Response Example
----------------

.. literalinclude:: ./samples/snapshots/snapshot-create-response.json
   :language: javascript


List accessible snapshots
~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/snapshots

Lists all Block Storage snapshots, with summary information,
that the project can access, since v3.31 if non-admin users
specify invalid filters in the url, API will return bad request.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200

.. rest_status_code:: error ../status.yaml

   - 400


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - all_tenants: all-tenants
   - sort: sort
   - limit: limit
   - offset: offset
   - marker: marker
   - with_count: with_count


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - status: status_snap
   - description: description_snap_req
   - created_at: created_at
   - name: name
   - user_id: user_id_min
   - volume_id: volume_id_snap
   - metadata: metadata
   - id: id_snap
   - size: size
   - count: count
   - updated_at: updated_at
   - snapshots_links: links_snap

Response Example
----------------

.. literalinclude:: ./samples/snapshots/snapshots-list-response.json
   :language: javascript


Show a snapshot's metadata
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/snapshots/{snapshot_id}/metadata

Shows metadata for a snapshot.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - snapshot_id: snapshot_id_path


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - metadata: metadata

Response Example
----------------

.. literalinclude:: ./samples/snapshots/snapshot-metadata-show-response.json
   :language: javascript


Create a snapshot's metadata
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/snapshots/{snapshot_id}/metadata

Updates metadata for a snapshot.

Creates or replaces metadata items that match keys. Does not modify items that
are not in the request.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - snapshot_id: snapshot_id_path
   - metadata: metadata

Request Example
---------------

.. literalinclude:: ./samples/snapshots/snapshot-metadata-create-request.json
   :language: javascript

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - metadata: metadata

Response Example
----------------

.. literalinclude:: ./samples/snapshots/snapshot-metadata-create-response.json
   :language: javascript

Update a snapshot's metadata
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  PUT /v3/{project_id}/snapshots/{snapshot_id}/metadata

Replaces all the snapshot's metadata with the key-value pairs in the request.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - snapshot_id: snapshot_id_path
   - metadata: metadata

Request Example
---------------

.. literalinclude:: ./samples/snapshots/snapshot-metadata-update-request.json
   :language: javascript


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - metadata: metadata

Response Example
----------------

.. literalinclude:: ./samples/snapshots/snapshot-metadata-update-response.json
   :language: javascript


Show a snapshot's details
~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/snapshots/{snapshot_id}

Shows details for a snapshot.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - snapshot_id: snapshot_id_path


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - status: status_snap
   - os-extended-snapshot-attributes:progress: os-ext-snap-attr:progress
   - description: description_snap_req
   - created_at: created_at
   - name: name
   - snapshot: snapshot_obj
   - user_id: user_id_min
   - volume_id: volume_id_snap
   - os-extended-snapshot-attributes:project_id: os-ext-snap-attr:project_id
   - size: size
   - id: id_snap
   - metadata: metadata
   - updated_at: updated_at

Response Example
----------------

.. literalinclude:: ./samples/snapshots/snapshot-show-response.json
   :language: javascript


Update a snapshot
~~~~~~~~~~~~~~~~~

.. rest_method::  PUT /v3/{project_id}/snapshots/{snapshot_id}

Updates a snapshot.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - snapshot_id: snapshot_id_path
   - snapshot: snapshot_obj
   - description: description_snap
   - name: name

Request Example
---------------

.. literalinclude:: ./samples/snapshots/snapshot-update-request.json
   :language: javascript



Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - status: status_snap
   - description: description_snap_req
   - created_at: created_at
   - name: name
   - snapshot: snapshot_obj
   - id: id_snap
   - size: size
   - volume_id: volume_id_snap
   - user_id: user_id_min
   - metadata: metadata

Response Example
----------------

.. literalinclude:: ./samples/snapshots/snapshot-update-response.json
   :language: javascript


Delete a snapshot
~~~~~~~~~~~~~~~~~

.. rest_method::  DELETE /v3/{project_id}/snapshots/{snapshot_id}

Deletes a snapshot.

Preconditions:

    - Snapshot status must be ``available`` or ``error``

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202

.. rest_status_code:: error ../status.yaml

   - 400
   - 403
   - 404


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - snapshot_id: snapshot_id_path


Show a snapshot's metadata for a specific key
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/snapshot/{snapshot_id}/metadata/{key}

Shows metadata for a snapshot for a specific key.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - snapshot_id: snapshot_id_path
   - key: key_view


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - meta: meta_snap

Response Example
----------------

.. literalinclude:: ./samples/snapshots/snapshot-metadata-show-key-response.json
   :language: javascript



Delete a snapshot's metadata
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::
   DELETE /v3/{project_id}/snapshots/{snapshot_id}/metadata/{key}

Deletes metadata for a snapshot.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - snapshot_id: snapshot_id_path
   - key: key_path


Update a snapshot's metadata for a specific key
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  PUT /v3/{project_id}/snapshots/{snapshot_id}/metadata/{key}

Update metadata for a snapshot for a specific key.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - snapshot_id: snapshot_id_path
   - key: key_update
   - meta: meta_snap

Request Example
---------------

.. literalinclude:: ./samples/snapshots/snapshot-metadata-update-key-request.json
   :language: javascript

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - meta: meta_snap

Response Example
----------------

.. literalinclude:: ./samples/snapshots/snapshot-metadata-update-key-response.json
   :language: javascript
