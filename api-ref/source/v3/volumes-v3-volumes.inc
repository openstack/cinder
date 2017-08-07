.. -*- rst -*-

Volumes (volumes)
=================

A volume is a detachable block storage device similar to a USB hard
drive. You can attach a volume to one instance at a time.

The ``snapshot_id`` and ``source_volid`` parameters specify the ID
of the snapshot or volume from which this volume originates. If the
volume was not created from a snapshot or source volume, these
values are null.

When you create, list, update, or delete volumes, the possible
status values are:

**Volume statuses**

+------------------+--------------------------------------------------------+
| Status           | Description                                            |
+------------------+--------------------------------------------------------+
| creating         | The volume is being created.                           |
+------------------+--------------------------------------------------------+
| available        | The volume is ready to attach to an instance.          |
+------------------+--------------------------------------------------------+
| reserved         | The volume is reserved for attaching or shelved.       |
+------------------+--------------------------------------------------------+
| attaching        | The volume is attaching to an instance.                |
+------------------+--------------------------------------------------------+
| detaching        | The volume is detaching from an instance.              |
+------------------+--------------------------------------------------------+
| in-use           | The volume is attached to an instance.                 |
+------------------+--------------------------------------------------------+
| maintenance      | The volume is locked and being migrated.               |
+------------------+--------------------------------------------------------+
| deleting         | The volume is being deleted.                           |
+------------------+--------------------------------------------------------+
| awaiting-transfer| The volume is awaiting for transfer.                   |
+------------------+--------------------------------------------------------+
| error            | A volume creation error occurred.                      |
+------------------+--------------------------------------------------------+
| error_deleting   | A volume deletion error occurred.                      |
+------------------+--------------------------------------------------------+
| backing-up       | The volume is being backed up.                         |
+------------------+--------------------------------------------------------+
| restoring-backup | A backup is being restored to the volume.              |
+------------------+--------------------------------------------------------+
| error_backing-up | A backup error occurred.                               |
+------------------+--------------------------------------------------------+
| error_restoring  | A backup restoration error occurred.                   |
+------------------+--------------------------------------------------------+
| error_extending  | An error occurred while attempting to extend a volume. |
+------------------+--------------------------------------------------------+
| downloading      | The volume is downloading an image.                    |
+------------------+--------------------------------------------------------+
| uploading        | The volume is being uploaded to an image.              |
+------------------+--------------------------------------------------------+
| retyping         | The volume is changing type to another volume type.    |
+------------------+--------------------------------------------------------+
| extending        | The volume is being extended.                          |
+------------------+--------------------------------------------------------+


List accessible volumes with details
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/volumes/detail

Lists all Block Storage volumes, with details, that the project can access,
since v3.31 if non-admin users specify invalid filters in the url, API will
return bad request.


Normal response codes: 200
Error response codes: badRequest(400)


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - sort_key: sort_key
   - sort_dir: sort_dir
   - limit: limit
   - offset: offset
   - marker: marker


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - migration_status: migration_status
   - attachments: attachments
   - links: links_3
   - availability_zone: availability_zone
   - os-vol-host-attr:host: os-vol-host-attr:host
   - encrypted: encrypted
   - updated_at: updated_at
   - os-volume-replication:extended_status: os-volume-replication:extended_status
   - replication_status: replication_status
   - snapshot_id: snapshot_id
   - id: id_5
   - size: size
   - user_id: user_id
   - os-vol-tenant-attr:tenant_id: os-vol-tenant-attr:tenant_id
   - os-vol-mig-status-attr:migstat: os-vol-mig-status-attr:migstat
   - metadata: metadata
   - status: status_3
   - description: description
   - multiattach: multiattach
   - source_volid: source_volid
   - consistencygroup_id: consistencygroup_id
   - os-vol-mig-status-attr:name_id: os-vol-mig-status-attr:name_id
   - name: name_13
   - bootable: bootable_response
   - created_at: created_at
   - os-volume-replication:driver_data: os-volume-replication:driver_data
   - volumes: volumes
   - volume_type: volume_type



Response Example
----------------

.. literalinclude:: ./samples/volumes-list-detailed-response.json
   :language: javascript




Create a volume
~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/volumes

Creates a volume.

To create a bootable volume, include the UUID of the image from
which you want to create the volume in the ``imageRef`` attribute
in the request body.

Preconditions

- You must have enough volume storage quota remaining to create a
  volume of size requested.

Asynchronous Postconditions

- With correct permissions, you can see the volume status as
  ``available`` through API calls.

- With correct access, you can see the created volume in the storage
  system that OpenStack Block Storage manages.

Troubleshooting

- If volume status remains ``creating`` or shows another error
  status, the request failed. Ensure you meet the preconditions
  then investigate the storage back end.

- Volume is not created in the storage system that OpenStack Block
  Storage manages.

- The storage node needs enough free storage space to match the size
  of the volume creation request.

Normal response codes: 202


Request
-------

.. rest_parameters:: parameters.yaml

   - size: size
   - description: description
   - imageRef: imageRef
   - multiattach: multiattach
   - availability_zone: availability_zone
   - source_volid: source_volid
   - name: name_13
   - volume: volume
   - consistencygroup_id: consistencygroup_id
   - volume_type: volume_type
   - snapshot_id: snapshot_id
   - OS-SCH-HNT:scheduler_hints: OS-SCH-HNT:scheduler_hints
   - source_replica: source_replica
   - metadata: metadata
   - project_id: project_id_path

Request Example
---------------

.. literalinclude:: ./samples/volume-create-request.json
   :language: javascript



Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - migration_status: migration_status
   - attachments: attachments
   - links: links_3
   - availability_zone: availability_zone
   - encrypted: encrypted
   - updated_at: updated_at
   - replication_status: replication_status
   - snapshot_id: snapshot_id
   - id: id_5
   - size: size
   - user_id: user_id
   - metadata: metadata
   - status: status_3
   - description: description
   - multiattach: multiattach
   - source_volid: source_volid
   - volume: volume
   - consistencygroup_id: consistencygroup_id
   - name: name_13
   - bootable: bootable_response
   - created_at: created_at
   - volume_type: volume_type

Response Example
----------------

.. literalinclude:: ./samples/volume-create-response.json
   :language: javascript


List accessible volumes
~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/volumes

Lists summary information for all Block Storage volumes that the
project can access, since v3.31 if non-admin users specify invalid
filters in the url, API will return bad request.


Normal response codes: 200
Error response codes: badRequest(400)


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - sort_key: sort_key
   - sort_dir: sort_dir
   - limit: limit
   - offset: offset
   - marker: marker


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - volumes: volumes
   - id: id_5
   - links: links_3
   - name: name_13



Response Example
----------------

.. literalinclude:: ./samples/volumes-list-response.json
   :language: javascript




Show a volume's details
~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/volumes/{volume_id}

Shows details for a volume.

Preconditions

- The volume must exist.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - volume_id: volume_id_path


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - migration_status: migration_status
   - attachments: attachments
   - links: links_3
   - availability_zone: availability_zone
   - os-vol-host-attr:host: os-vol-host-attr:host
   - encrypted: encrypted
   - updated_at: updated_at
   - os-volume-replication:extended_status: os-volume-replication:extended_status
   - replication_status: replication_status
   - snapshot_id: snapshot_id
   - id: id_5
   - size: size
   - user_id: user_id
   - os-vol-tenant-attr:tenant_id: os-vol-tenant-attr:tenant_id
   - os-vol-mig-status-attr:migstat: os-vol-mig-status-attr:migstat
   - metadata: metadata
   - status: status_3
   - description: description
   - multiattach: multiattach
   - source_volid: source_volid
   - volume: volume
   - consistencygroup_id: consistencygroup_id
   - os-vol-mig-status-attr:name_id: os-vol-mig-status-attr:name_id
   - name: name_13
   - bootable: bootable_response
   - created_at: created_at
   - os-volume-replication:driver_data: os-volume-replication:driver_data
   - volume_type: volume_type



Response Example
----------------

.. literalinclude:: ./samples/volume-show-response.json
   :language: javascript




Update a volume
~~~~~~~~~~~~~~~

.. rest_method::  PUT /v3/{project_id}/volumes/{volume_id}

Updates a volume.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - volume: volume
   - description: description
   - name: name_13
   - metadata: metadata
   - project_id: project_id_path
   - volume_id: volume_id_path

Request Example
---------------

.. literalinclude:: ./samples/volume-update-request.json
   :language: javascript



Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - migration_status: migration_status
   - attachments: attachments
   - links: links_3
   - availability_zone: availability_zone
   - encrypted: encrypted
   - updated_at: updated_at
   - replication_status: replication_status
   - snapshot_id: snapshot_id
   - id: id_5
   - size: size
   - user_id: user_id
   - metadata: metadata
   - status: status_3
   - description: description
   - multiattach: multiattach
   - source_volid: source_volid
   - volume: volume
   - consistencygroup_id: consistencygroup_id
   - name: name_13
   - bootable: bootable_response
   - created_at: created_at
   - volume_type: volume_type



Response Example
----------------

.. literalinclude:: ./samples/volume-update-response.json
   :language: javascript




Delete a volume
~~~~~~~~~~~~~~~

.. rest_method::  DELETE /v3/{project_id}/volumes/{volume_id}

Deletes a volume.

Preconditions

- Volume status must be ``available``, ``in-use``, ``error``, or
  ``error_restoring``.

- You cannot already have a snapshot of the volume.

- You cannot delete a volume that is in a migration.

Asynchronous Postconditions

- The volume is deleted in volume index.

- The volume managed by OpenStack Block Storage is deleted in
  storage node.

Troubleshooting

- If volume status remains in ``deleting`` or becomes
  ``error_deleting`` the request failed. Ensure you meet the
  preconditions then investigate the storage back end.

- The volume managed by OpenStack Block Storage is not deleted from
  the storage system.

Normal response codes: 202


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - volume_id: volume_id_path
   - cascade: cascade
   - force: force_5






Create metadata for volume
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/volumes/{volume_id}/metadata

Creates or replaces metadata for a volume. Does not modify items that are not
in the request.

Normal response codes: 202


Request
-------

.. rest_parameters:: parameters.yaml

   - metadata: metadata_3
   - project_id: project_id_path
   - volume_id: volume_id_path

Request Example
---------------

.. literalinclude:: ./samples/volume-metadata-create-request.json
   :language: javascript



Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - metadata: metadata_3


Response Example
----------------

.. literalinclude:: ./samples/volume-metadata-create-response.json
   :language: javascript




Show a volume's metadata
~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/volumes/{volume_id}/metadata

Shows metadata for a volume.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - volume_id: volume_id_path


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - metadata: metadata_3



Response Example
----------------

.. literalinclude:: ./samples/volume-metadata-show-response.json
   :language: javascript




Update a volume's metadata
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  PUT /v3/{project_id}/volumes/{volume_id}/metadata

Replaces all the volume's metadata with the key-value pairs in the request.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - metadata: metadata_3
   - project_id: project_id_path
   - volume_id: volume_id_path

Request Example
---------------

.. literalinclude:: ./samples/volume-metadata-update-request.json
   :language: javascript



Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - metadata: metadata_3



Response Example
----------------

.. literalinclude:: ./samples/volume-metadata-update-response.json
   :language: javascript


Show a volume's metadata for a specific key
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/volumes/{volume_id}/metadata/{key}

Shows metadata for a volume for a specific key.

Normal response codes: 200


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - volume_id: volume_id_path
   - key: key_2


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - meta: meta



Response Example
----------------

.. literalinclude:: ./samples/volume-metadata-show-key-response.json
   :language: javascript



Delete a volume's metadata
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  DELETE /v3/{project_id}/volumes/{volume_id}/metadata/{key}

Deletes metadata for a volume.

Normal response codes: 200


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - volume_id: volume_id_path
   - key: key_1


Update a volume's metadata for a specific key
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  PUT /v3/{project_id}/volumes/{volume_id}/metadata/{key}

Update metadata for a volume for a specific key.

Normal response codes: 200


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - volume_id: volume_id_path
   - key: key_3
   - meta: meta

Request Example
---------------

.. literalinclude:: ./samples/volume-metadata-update-key-request.json
   :language: javascript

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - meta: meta

Response Example
----------------

.. literalinclude:: ./samples/volume-metadata-update-key-response.json
   :language: javascript


Get volumes summary
~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/volumes/summary

Display volumes summary with total number of volumes and total size in GB


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - all_tenants: all_tenants

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - volume-summary: volume-summary
   - total_size: total_size
   - total_count: total_count
   - metadata: summary_metadata


Response Example
----------------

.. literalinclude:: ./samples/volumes-list-summary-response.json
   :language: javascript
