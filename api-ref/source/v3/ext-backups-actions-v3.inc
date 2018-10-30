.. -*- rst -*-

Backup actions (backups, action)
================================

Force-deletes a backup and reset status for a backup.


Force-delete a backup
~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/backups/{backup_id}/action

Force-deletes a backup. Specify the ``os-force_delete`` action in the request
body.

This operation deletes the backup and any backup data.

The backup driver returns the ``405`` status code if it does not
support this operation.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202

.. rest_status_code:: error ../status.yaml

   - 404
   - 405

Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - backup_id: backup_id_required
   - os-force_delete: os-force_delete

Request Example
---------------

.. literalinclude:: ./samples/backup-force-delete-request.json
   :language: javascript



Reset a backup's status
~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/backups/{backup_id}/action

Reset a backup's status. Specify the ``os-reset_status`` action in the request
body.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202

.. rest_status_code:: error ../status.yaml

   - 400
   - 404


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - backup_id: backup_id_required
   - os-reset_status: os-reset_status
   - status: status_backup_action

Request Example
---------------

.. literalinclude:: ./samples/backup-reset-status-request.json
   :language: javascript

