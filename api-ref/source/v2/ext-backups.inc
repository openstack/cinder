.. -*- rst -*-

Backups (backups)
=================

A backup is a full copy of a volume stored in an external service.
The service can be configured. The only supported service is Object
Storage. A backup can subsequently be restored from the external
service to either the same volume that the backup was originally
taken from or to a new volume. Backup and restore operations can
only be carried out on volumes that are in an unattached and
available state.

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
| error_restoring | A backup restoration error occurred.        |
+-----------------+---------------------------------------------+


If an error occurs, you can find more information about the error
in the ``fail_reason`` field for the backup.


List backups with details
~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v2/{tenant_id}/backups/detail

Lists Block Storage backups, with details, to which the tenant has access.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - sort_key: sort_key
   - sort_dir: sort_dir
   - limit: limit
   - marker: marker


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - status: status_4
   - object_count: object_count
   - fail_reason: fail_reason
   - description: description
   - links: links
   - availability_zone: availability_zone
   - created_at: created_at
   - updated_at: updated_at
   - name: name
   - has_dependent_backups: has_dependent_backups
   - volume_id: volume_id
   - container: container
   - backups: backups
   - size: size
   - id: id
   - is_incremental: is_incremental
   - data_timestamp: data_timestamp
   - snapshot_id: snapshot_id_2

Response Example
----------------

.. literalinclude:: ./samples/backups-list-detailed-response.json
   :language: javascript


Show backup details
~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v2/{tenant_id}/backups/{backup_id}

Shows details for a backup.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - backup_id: backup_id


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - status: status_4
   - object_count: object_count
   - container: container
   - description: description
   - links: links
   - availability_zone: availability_zone
   - created_at: created_at
   - updated_at: updated_at
   - name: name
   - has_dependent_backups: has_dependent_backups
   - volume_id: volume_id
   - fail_reason: fail_reason
   - size: size
   - backup: backup
   - id: id
   - is_incremental: is_incremental
   - data_timestamp: data_timestamp
   - snapshot_id: snapshot_id_2

Response Example
----------------

.. literalinclude:: ./samples/backup-show-response.json
   :language: javascript


Delete backup
~~~~~~~~~~~~~

.. rest_method::  DELETE /v2/{tenant_id}/backups/{backup_id}

Deletes a backup.

Normal response codes: 202,
Error response codes: Bad Request(400)




Request
-------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - backup_id: backup_id


Restore backup
~~~~~~~~~~~~~~

.. rest_method::  POST /v2/{tenant_id}/backups/{backup_id}/restore

Restores a Block Storage backup to an existing or new Block Storage volume.

You must specify either the UUID or name of the volume. If you
specify both the UUID and name, the UUID takes priority.

Normal response codes: 202,
Error response codes: Bad Request(400), Request Entity Too Large(413)


Request
-------

.. rest_parameters:: parameters.yaml

   - restore: restore
   - name: name
   - volume_id: volume_id
   - tenant_id: tenant_id
   - backup_id: backup_id

Request Example
---------------

.. literalinclude:: ./samples/backup-restore-request.json
   :language: javascript

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - restore: restore
   - backup_id: backup_id
   - volume_id: volume_id
   - volume_name: volume_name

Response Example
----------------

.. literalinclude:: ./samples/backup-restore-response.json
   :language: javascript

Create backup
~~~~~~~~~~~~~

.. rest_method::  POST /v2/{tenant_id}/backups

Creates a Block Storage backup from a volume.

Normal response codes: 202,
Error response codes: Bad Request(400), Internal Server Error(500)

Request
-------

.. rest_parameters:: parameters.yaml

   - container: container
   - description: description
   - incremental: incremental
   - volume_id: volume_id
   - force: force
   - backup: backup
   - name: name
   - tenant_id: tenant_id
   - snapshot_id: snapshot_id_2

Request Example
---------------

.. literalinclude:: ./samples/backup-create-request.json
   :language: javascript

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - backup: backup
   - id: id
   - links: links
   - name: name

List backups
~~~~~~~~~~~~

.. rest_method::  GET /v2/{tenant_id}/backups

Lists Block Storage backups to which the tenant has access.

Normal response codes: 200
Error response codes:

Request
-------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - sort_key: sort_key
   - sort_dir: sort_dir
   - limit: limit
   - marker: marker

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - backups: backups
   - id: id
   - links: links
   - name: name

Response Example
----------------

.. literalinclude:: ./samples/backups-list-response.json
   :language: javascript
