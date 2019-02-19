.. -*- rst -*-

Backups (backups)
=================

A backup is a full copy of a volume stored in an external service.
The service can be configured. The only supported service is Object
Storage. A backup can subsequently be restored from the external
service to either the same volume that the backup was originally
taken from or to a new volume.

When you create, list, or delete backups, these status values are
possible:

**Backup statuses**

+-----------------+---------------------------------------------+
| Status          | Description                                 |
+-----------------+---------------------------------------------+
| creating        | The backup is being created.                |
+-----------------+---------------------------------------------+
| available       | The backup is ready to restore to a volume. |
+-----------------+---------------------------------------------+
| deleting        | The backup is being deleted.                |
+-----------------+---------------------------------------------+
| error           | A backup error occurred.                    |
+-----------------+---------------------------------------------+
| restoring       | The backup is being restored to a volume.   |
+-----------------+---------------------------------------------+
| error_deleting  | An error occurred while deleting the backup.|
+-----------------+---------------------------------------------+


If an error occurs, you can find more information about the error
in the ``fail_reason`` field for the backup.


List backups with detail
~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/backups/detail

Lists Block Storage backups, with details, to which the project has access,
since v3.31 if non-admin users specify invalid filters in the url,
API will return bad request.


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

   - backups: backups
   - status: status_backup
   - object_count: object_count
   - fail_reason: fail_reason
   - description: description
   - links: links_backup
   - availability_zone: availability_zone
   - created_at: created_at
   - updated_at: updated_at
   - name: name_backup
   - has_dependent_backups: has_dependent_backups
   - volume_id: volume_id
   - container: container
   - size: size
   - id: id_backup
   - is_incremental: is_incremental
   - data_timestamp: data_timestamp
   - snapshot_id: snapshot_id_source_vol
   - os-backup-project-attr:project_id: os-backup-project-attr:project_id
   - count: count
   - metadata: metadata_backup
   - user_id: user_id_backup

Response Example
----------------

.. literalinclude:: ./samples/backups-list-detailed-response.json
   :language: javascript


Show backup detail
~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/backups/{backup_id}

Shows details for a backup.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - backup_id: backup_id_required


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - backup: backup
   - status: status_backup
   - object_count: object_count
   - container: container
   - description: description
   - links: links_backup
   - availability_zone: availability_zone
   - created_at: created_at
   - updated_at: updated_at
   - name: name_backup
   - has_dependent_backups: has_dependent_backups
   - volume_id: volume_id
   - fail_reason: fail_reason
   - size: size
   - backup: backup
   - id: id_backup
   - is_incremental: is_incremental
   - data_timestamp: data_timestamp
   - snapshot_id: snapshot_id_source_vol
   - os-backup-project-attr:project_id: os-backup-project-attr:project_id
   - metadata: metadata_backup
   - user_id: user_id_backup

Response Example
----------------

.. literalinclude:: ./samples/backup-show-response.json
   :language: javascript


Delete a backup
~~~~~~~~~~~~~~~

.. rest_method::  DELETE /v3/{project_id}/backups/{backup_id}

Deletes a backup.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202

.. rest_status_code:: error ../status.yaml

   - 400

Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - backup_id: backup_id_required


Restore a backup
~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/backups/{backup_id}/restore

Restores a Block Storage backup to an existing or new Block Storage volume.

The name parameter will work only if a new volume is created.

If UUID is specified, the backup will be restored to the specified volume.
The specified volume has the following requirements:

* the specified volume status is ``available``.
* the size of specified volume must be equal to or greater than the size of
  backup.

If no existing volume UUID is provided, the backup will be restored to a
new volume matching the size and name of the originally backed up volume.
In this case, if the name parameter is provided, it will be used as the
name of the new volume.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202

.. rest_status_code:: error ../status.yaml

   - 400
   - 413


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - backup_id: backup_id_required
   - restore: restore
   - name: volume_name_optional
   - volume_id: volume_id_restore

Request Example
---------------

.. literalinclude:: ./samples/backup-restore-request.json
   :language: javascript

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - restore: restore
   - backup_id: backup_id_required
   - volume_id: volume_id
   - volume_name: volume_name

Response Example
----------------

.. literalinclude:: ./samples/backup-restore-response.json
   :language: javascript

Create a backup
~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/backups

Creates a Block Storage backup from a volume or snapshot.

The status of the volume must be ``available`` or if the ``force`` flag is
used, backups of ``in-use`` volumes may also be created.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202

.. rest_status_code:: error ../status.yaml

   - 400
   - 500

Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - backup: backup
   - volume_id: volume_id_backup
   - container: container
   - description: description
   - incremental: incremental
   - force: force
   - name: name_optional
   - snapshot_id: snapshot_id_backup
   - metadata: metadata_backup
   - availability_zone: availability_zone_backup

Request Example
---------------

.. literalinclude:: ./samples/backup-create-request.json
   :language: javascript

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - backup: backup
   - id: id_backup
   - links: links_backup
   - name: name_backup

Response Example
----------------

.. literalinclude:: ./samples/backup-create-response.json
   :language: javascript

Update a backup
~~~~~~~~~~~~~~~

.. rest_method::  PUT /v3/{project_id}/backups/{backup_id}

Update a Block Storage backup. This API is available since v3.9.

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
   - backup_id: backup_id_required
   - backup: backup
   - description: description
   - name: name_optional
   - metadata: metadata_backup

Request Example
---------------

.. literalinclude:: ./samples/backup-update-request.json
   :language: javascript

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - backup: backup
   - id: id_backup
   - links: links_backup
   - name: name_backup
   - metadata: metadata_backup

Response Example
----------------

.. literalinclude:: ./samples/backup-update-response.json
   :language: javascript


List backups for project
~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/backups

Lists Block Storage backups to which the project has access,
since v3.31 if non-admin users specify invalid filters in the
url, API will return bad request.

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
   - marker: marker
   - with_count: with_count

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - backups: backups
   - id: id_backup
   - links: links_backup
   - name: name_backup
   - count: count

Response Example
----------------

.. literalinclude:: ./samples/backups-list-response.json
   :language: javascript


Export a backup
~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/backups/{backup_id}/export_record

Export information about a backup.


Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200

.. rest_status_code:: error ../status.yaml

   - 400
   - 404


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - backup_id: backup_id_required


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - backup-record: backup_record
   - backup_service: backup_service
   - backup_url: backup_url

Response Example
----------------

.. literalinclude:: ./samples/backup-record-export-response.json
   :language: javascript


Import a backup
~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/backups/{backup_id}/import_record

Import information about a backup.


Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 201

.. rest_status_code:: error ../status.yaml

   - 400
   - 503


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - backup_id: backup_id_required
   - backup-record: backup_record
   - backup_service: backup_service
   - backup_url: backup_url


Request Example
---------------

.. literalinclude:: ./samples/backup-record-import-request.json
   :language: javascript


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - id: id_backup
   - links: links_backup
   - name: name_backup

Response Example
----------------

.. literalinclude:: ./samples/backup-record-import-response.json

