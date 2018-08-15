.. -*- rst -*-

Snapshot actions (snapshots, action)
====================================

Administrator only. Resets status for a snapshot.


Reset snapshot's status
~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v2/{project_id}/snapshots/{snapshot_id}/action

Resets the status. Specify the ``os-reset_status`` action in the request body.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202


Request
-------

.. rest_parameters:: parameters.yaml

   - status: status_2
   - os-reset_status: os-reset_status
   - project_id: project_id_path
   - snapshot_id: snapshot_id

Request Example
---------------

.. literalinclude:: ./samples/snapshot-status-reset-request.json
   :language: javascript
