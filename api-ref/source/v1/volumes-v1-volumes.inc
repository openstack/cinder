.. -*- rst -*-

Volumes
=======

The ``snapshot_id`` and ``source_volid`` parameters specify the ID
of the snapshot or volume from which the volume originates. If the
volume was not created from a snapshot or source volume, these
values are null.


List volumes, with details (v1)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v1/{tenant_id}/volumes/detail

Lists all volumes, with details.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id


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
   - consistencygroup_id: consistencygroup_id
   - name: name
   - bootable: bootable
   - created_at: created_at
   - volume_type: volume_type
   - volumes: volumes

Response Example
----------------

.. literalinclude:: ./samples/volumes-list-response.json
   :language: javascript


Create volume (v1)
~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v1/{tenant_id}/volumes

Creates a volume.

Normal response codes: 201,


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

   - description: description
   - imageRef: imageRef
   - multiattach: multiattach
   - created_at: created_at
   - availability_zone: availability_zone
   - source_volid: source_volid
   - name: name
   - volume: volume
   - volume_type: volume_type
   - snapshot_id: snapshot_id
   - size: size
   - metadata: metadata


List volumes (v1)
~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v1/{tenant_id}/volumes

Lists all volumes.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id


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


Show volume details (v1)
~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v1/{tenant_id}/volumes/{volume_id}

Shows details for a volume.


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

.. literalinclude:: ./samples/volume-show-response.json
   :language: javascript

Delete volume (v1)
~~~~~~~~~~~~~~~~~~

.. rest_method::  DELETE /v1/{tenant_id}/volumes/{volume_id}

Deletes a volume.

Normal response codes: 202,


Request
-------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - volume_id: volume_id
