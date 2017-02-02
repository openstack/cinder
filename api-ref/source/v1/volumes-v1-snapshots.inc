.. -*- rst -*-

Snapshots
=========

Creates, lists, shows information for, and deletes snapshots. Shows
and updates snapshot metadata.


Show snapshot details (v1)
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v1/{tenant_id}/snapshots/{snapshot_id}

Shows details for a snapshot.


Normal response codes: 200
Error response codes:

Request
-------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - snapshot_id: snapshot_id

Response Example
----------------

.. literalinclude:: ./samples/snapshot-show-response.json
   :language: javascript


Delete snapshot (v1)
~~~~~~~~~~~~~~~~~~~~

.. rest_method::  DELETE /v1/{tenant_id}/snapshots/{snapshot_id}

Deletes a snapshot.

Normal response codes:202,


Request
-------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - snapshot_id: snapshot_id


List snapshots with details (v1)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v1/{tenant_id}/snapshots/detail

Lists all snapshots, with details.


Normal response codes: 200
Error response codes:

Request
-------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id

Response Example
----------------

.. literalinclude:: ./samples/snapshots-list-response.json
   :language: javascript


Create snapshot (v1)
~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v1/{tenant_id}/snapshots

Creates a snapshot.

Normal response codes:201

Request
-------

.. rest_parameters:: parameters.yaml

   - snapshot: snapshot
   - tenant_id: tenant_id

Request Example
---------------

.. literalinclude:: ./samples/snapshot-create-request.json
   :language: javascript

List snapshots (v1)
~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v1/{tenant_id}/snapshots

Lists all snapshots.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id


Response Example
----------------

.. literalinclude:: ./samples/snapshots-list-response.json
   :language: javascript


Show snapshot metadata (v1)
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v1/{tenant_id}/snapshots/{snapshot_id}/metadata

Shows metadata for a snapshot.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - snapshot_id: snapshot_id


Response Example
----------------

.. literalinclude:: ./samples/snapshot-metadata-show-response.json
   :language: javascript


Update snapshot metadata (v1)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  PUT /v1/{tenant_id}/snapshots/{snapshot_id}/metadata

Updates metadata for a snapshot.

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
