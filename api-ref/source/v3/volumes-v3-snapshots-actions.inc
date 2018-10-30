.. -*- rst -*-

Snapshot actions (snapshots, action)
====================================

Administrator only, depending on policy settings.
Resets, updates status for a snapshot.


Reset a snapshot's status
~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/snapshots/{snapshot_id}/action

Resets the status. Specify the ``os-reset_status`` action in the request body.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - snapshot_id: snapshot_id_path
   - os-reset_status: os-reset_status
   - status: status_snap

Request Example
---------------

.. literalinclude:: ./samples/snapshot-status-reset-request.json
   :language: javascript


Update status of a snapshot
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/snapshots/{snapshot_id}/action

Update fields related to the status of a snapshot.
Specify the ``os-update_snapshot_status`` action in the request body.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - snapshot_id: snapshot_id_path
   - os-update_snapshot_status: os-update_snapshot_status
   - status: status_snap
   - progress: snapshot_progress

Request Example
---------------

.. literalinclude:: ./samples/snapshot-status-update-request.json
   :language: javascript


Force delete a snapshot
~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/snapshots/{snapshot_id}/action

Attempts to force delete a snapshot, regardless of state. Specify the
``os-force_delete`` action in the request body.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - snapshot_id: snapshot_id_path
   - os-force_delete: os-force_delete


Request Example
---------------

.. literalinclude:: ./samples/snapshot-force-delete-request.json
   :language: javascript
