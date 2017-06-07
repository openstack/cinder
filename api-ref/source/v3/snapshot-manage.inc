.. -*- rst -*-

Snapshot manage extension (manageable_snapshots)
================================================

Creates or lists snapshots by using existing storage instead of allocating new
storage.


Manage an existing snapshot
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/manageable_snapshots

Creates a snapshot by using existing storage rather than allocating new storage.

The caller must specify a reference to an existing storage volume
in the ref parameter in the request. Although each storage driver
might interpret this reference differently, the driver should
accept a reference structure that contains either a source-id
or source-name element, if possible.

The API chooses the size of the snapshot by rounding up the size of
the existing snapshot to the next gibibyte (GiB).


Normal response codes: 202


Request
-------

.. rest_parameters:: parameters.yaml

   - description: description
   - name: name
   - ref: ref
   - volume_id: volume_id
   - metadata: metadata
   - project_id: project_id_path

Request Example
---------------

.. literalinclude:: ./samples/snapshot-manage-request.json
   :language: javascript



List summary of snapshots available to manage
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/manageable_snapshots

Search a volume backend and list summary of snapshots which are available to
manage.

Normal response codes: 200


Request
-------

.. rest_parameters:: parameters.yaml

   - sort: sort
   - offset: offset
   - limit: limit
   - marker: marker
   - project_id: project_id_path
   - host: hostname


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

Normal response codes: 200


Request
-------

.. rest_parameters:: parameters.yaml

   - sort: sort
   - offset: offset
   - limit: limit
   - marker: marker
   - project_id: project_id_path
   - host: hostname


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
