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
   - status: status_2

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
   - status: status_2
   - progress: snapshot_progress

Request Example
---------------

.. literalinclude:: ./samples/snapshot-status-update-request.json
   :language: javascript
