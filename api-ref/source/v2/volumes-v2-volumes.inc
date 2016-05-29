.. -*- rst -*-

=================
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
| attaching        | The volume is attaching to an instance.                |
+------------------+--------------------------------------------------------+
| in-use           | The volume is attached to an instance.                 |
+------------------+--------------------------------------------------------+
| deleting         | The volume is being deleted.                           |
+------------------+--------------------------------------------------------+
| error            | A volume creation error occurred.                      |
+------------------+--------------------------------------------------------+
| error_deleting   | A volume deletion error occurred.                      |
+------------------+--------------------------------------------------------+
| backing-up       | The volume is being backed up.                         |
+------------------+--------------------------------------------------------+
| restoring-backup | A backup is being restored to the volume.              |
+------------------+--------------------------------------------------------+
| error_restoring  | A backup restoration error occurred.                   |
+------------------+--------------------------------------------------------+
| error_extending  | An error occurred while attempting to extend a volume. |
+------------------+--------------------------------------------------------+


List volumes with details
=========================

.. rest_method::  GET /v2/{tenant_id}/volumes/detail

Lists all Block Storage volumes, with details, that the tenant can access.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - sort: sort
   - limit: limit
   - marker: marker


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - migration_status: migration_status
   - attachments: attachments
   - links: links
   - availability_zone: availability_zone
   - os-vol-host-attr:host: os-vol-host-attr:host
   - encrypted: encrypted
   - updated_at: updated_at
   - os-volume-replication:extended_status: os-volume-replication:extended_status
   - replication_status: replication_status
   - snapshot_id: snapshot_id
   - id: id
   - size: size
   - user_id: user_id
   - os-vol-tenant-attr:tenant_id: os-vol-tenant-attr:tenant_id
   - os-vol-mig-status-attr:migstat: os-vol-mig-status-attr:migstat
   - metadata: metadata
   - status: status
   - description: description
   - multiattach: multiattach
   - source_volid: source_volid
   - consistencygroup_id: consistencygroup_id
   - os-vol-mig-status-attr:name_id: os-vol-mig-status-attr:name_id
   - name: name
   - bootable: bootable
   - created_at: created_at
   - os-volume-replication:driver_data: os-volume-replication:driver_data
   - volumes: volumes
   - volume_type: volume_type



Response Example
----------------

.. literalinclude:: ./samples/volumes-list-detailed-response.json
   :language: javascript




Create volume
=============

.. rest_method::  POST /v2/{tenant_id}/volumes

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

Error response codes:202,


Request
-------

.. rest_parameters:: parameters.yaml

   - size: size
   - description: description
   - imageRef: imageRef
   - multiattach: multiattach
   - availability_zone: availability_zone
   - source_volid: source_volid
   - name: name
   - volume: volume
   - consistencygroup_id: consistencygroup_id
   - volume_type: volume_type
   - snapshot_id: snapshot_id
   - OS-SCH-HNT:scheduler_hints: OS-SCH-HNT:scheduler_hints
   - source_replica: source_replica
   - metadata: metadata
   - tenant_id: tenant_id

Request Example
---------------

.. literalinclude:: ./samples/volume-create-request.json
   :language: javascript



Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - migration_status: migration_status
   - attachments: attachments
   - links: links
   - availability_zone: availability_zone
   - encrypted: encrypted
   - updated_at: updated_at
   - replication_status: replication_status
   - snapshot_id: snapshot_id
   - id: id
   - size: size
   - user_id: user_id
   - metadata: metadata
   - status: status
   - description: description
   - multiattach: multiattach
   - source_volid: source_volid
   - volume: volume
   - consistencygroup_id: consistencygroup_id
   - name: name
   - bootable: bootable
   - created_at: created_at
   - volume_type: volume_type





List volumes
============

.. rest_method::  GET /v2/{tenant_id}/volumes

Lists summary information for all Block Storage volumes that the tenant can access.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - sort: sort
   - limit: limit
   - marker: marker


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - volumes: volumes
   - id: id
   - links: links
   - name: name



Response Example
----------------

.. literalinclude:: ./samples/volumes-list-response.json
   :language: javascript




Show volume details
===================

.. rest_method::  GET /v2/{tenant_id}/volumes/{volume_id}

Shows details for a volume.

Preconditions

- The volume must exist.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - volume_id: volume_id


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - migration_status: migration_status
   - attachments: attachments
   - links: links
   - availability_zone: availability_zone
   - os-vol-host-attr:host: os-vol-host-attr:host
   - encrypted: encrypted
   - updated_at: updated_at
   - os-volume-replication:extended_status: os-volume-replication:extended_status
   - replication_status: replication_status
   - snapshot_id: snapshot_id
   - id: id
   - size: size
   - user_id: user_id
   - os-vol-tenant-attr:tenant_id: os-vol-tenant-attr:tenant_id
   - os-vol-mig-status-attr:migstat: os-vol-mig-status-attr:migstat
   - metadata: metadata
   - status: status
   - description: description
   - multiattach: multiattach
   - source_volid: source_volid
   - volume: volume
   - consistencygroup_id: consistencygroup_id
   - os-vol-mig-status-attr:name_id: os-vol-mig-status-attr:name_id
   - name: name
   - bootable: bootable
   - created_at: created_at
   - os-volume-replication:driver_data: os-volume-replication:driver_data
   - volume_type: volume_type



Response Example
----------------

.. literalinclude:: ./samples/volume-show-response.json
   :language: javascript




Update volume
=============

.. rest_method::  PUT /v2/{tenant_id}/volumes/{volume_id}

Updates a volume.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - volume: volume
   - description: description
   - name: name
   - metadata: metadata
   - tenant_id: tenant_id
   - volume_id: volume_id

Request Example
---------------

.. literalinclude:: ./samples/volume-update-request.json
   :language: javascript



Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - migration_status: migration_status
   - attachments: attachments
   - links: links
   - availability_zone: availability_zone
   - encrypted: encrypted
   - updated_at: updated_at
   - replication_status: replication_status
   - snapshot_id: snapshot_id
   - id: id
   - size: size
   - user_id: user_id
   - metadata: metadata
   - status: status
   - description: description
   - multiattach: multiattach
   - source_volid: source_volid
   - volume: volume
   - consistencygroup_id: consistencygroup_id
   - name: name
   - bootable: bootable
   - created_at: created_at
   - volume_type: volume_type



Response Example
----------------

.. literalinclude:: ./samples/volume-update-response.json
   :language: javascript




Delete volume
=============

.. rest_method::  DELETE /v2/{tenant_id}/volumes/{volume_id}

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

Error response codes:202,


Request
-------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - volume_id: volume_id






Create volume metadata
======================

.. rest_method::  POST /v2/{tenant_id}/volumes/{volume_id}/metadata

Creates metadata for a volume.

Error response codes:202,


Request
-------

.. rest_parameters:: parameters.yaml

   - metadata: metadata
   - tenant_id: tenant_id
   - volume_id: volume_id

Request Example
---------------

.. literalinclude:: ./samples/volume-metadata-create-request.json
   :language: javascript



Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - metadata: metadata





Show volume metadata
====================

.. rest_method::  GET /v2/{tenant_id}/volumes/{volume_id}/metadata

Shows metadata for a volume.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - volume_id: volume_id


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - metadata: metadata



Response Example
----------------

.. literalinclude:: ./samples/volume-metadata-show-response.json
   :language: javascript




Update volume metadata
======================

.. rest_method::  PUT /v2/{tenant_id}/volumes/{volume_id}/metadata

Updates metadata for a volume.

Replaces metadata items that match keys. Does not modify items that
are not in the request.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - metadata: metadata
   - tenant_id: tenant_id
   - volume_id: volume_id

Request Example
---------------

.. literalinclude:: ./samples/volume-metadata-update-request.json
   :language: javascript



Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - metadata: metadata



Response Example
----------------

.. literalinclude:: ./samples/volume-metadata-update-response.json
   :language: javascript
