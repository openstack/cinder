.. -*- rst -*-

=========
Snapshots
=========

Creates, lists, shows information for, and deletes snapshots. Shows
and updates snapshot metadata.


Show snapshot details
=====================

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


Delete snapshot
===============

.. rest_method::  DELETE /v1/{tenant_id}/snapshots/{snapshot_id}

Deletes a snapshot.

Error response codes:202,


Request
-------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - snapshot_id: snapshot_id


List snapshots with details
===========================

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


Create snapshot
===============

.. rest_method::  POST /v1/{tenant_id}/snapshots

Creates a snapshot.

Error response codes:201,

Request
-------

.. rest_parameters:: parameters.yaml

   - snapshot: snapshot
   - tenant_id: tenant_id

Request Example
---------------

.. literalinclude:: ./samples/snapshot-create-request.json
   :language: javascript

List snapshots
==============

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


Show snapshot metadata
======================

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


Update snapshot metadata
========================

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
