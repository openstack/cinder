.. -*- rst -*-

================================
Volume actions (volumes, action)
================================

Extends the size of, resets statuses for, sets image metadata for,
and removes image metadata from a volume. Attaches a volume to a
server, detaches a volume from a server, and removes a volume from
Block Storage management without actually removing the back-end
storage object associated with it.


Extend a volume size
====================

.. rest_method::  POST /v3/{project_id}/volumes/{volume_id}/action

Extends the size of a volume to a requested size, in gibibytes (GiB). Specify the ``os-extend`` action in the request body.

Preconditions

- Volume status must be ``available``.

- Sufficient amount of storage must exist to extend the volume.

- The user quota must have sufficient volume storage.

Troubleshooting

- An ``error_extending`` volume status indicates that the request
  failed. Ensure that you meet the preconditions and retry the
  request. If the request fails again, investigate the storage back
  end.

Error response codes:202,


Request
-------

.. rest_parameters:: parameters.yaml

   - os-extend: os-extend
   - new_size: new_size
   - project_id: project_id_path
   - volume_id: volume_id

Request Example
---------------

.. literalinclude:: ./samples/volume-extend-request.json
   :language: javascript







Reset a volume's statuses
=========================

.. rest_method::  POST /v3/{project_id}/volumes/{volume_id}/action

Administrator only. Resets the status, attach status, and migration status for a volume. Specify the ``os-reset_status`` action in the request body.

Error response codes:202,


Request
-------

.. rest_parameters:: parameters.yaml

   - status: status_3
   - migration_status: migration_status
   - os-reset_status: os-reset_status
   - attach_status: attach_status
   - project_id: project_id_path
   - volume_id: volume_id

Request Example
---------------

.. literalinclude:: ./samples/volume-status-reset-request.json
   :language: javascript







Set image metadata for a volume
===============================

.. rest_method::  POST /v3/{project_id}/volumes/{volume_id}/action

Sets the image metadata for a volume. Specify the ``os-set_image_metadata`` action in the request body.

Error response codes:202,


Request
-------

.. rest_parameters:: parameters.yaml

   - os-set_image_metadata: os-set_image_metadata
   - metadata: metadata
   - project_id: project_id_path
   - volume_id: volume_id

Request Example
---------------

.. literalinclude:: ./samples/volume-image-metadata-set-request.json
   :language: javascript







Remove image metadata from a volume
===================================

.. rest_method::  POST /v3/{project_id}/volumes/{volume_id}/action

Removes image metadata, by key, from a volume. Specify the ``os-unset_image_metadata`` action in the request body and the ``key`` for the metadata key and value pair that you want to remove.

Error response codes:202,


Request
-------

.. rest_parameters:: parameters.yaml

   - os-unset_image_metadata: os-unset_image_metadata
   - key: key
   - project_id: project_id_path
   - volume_id: volume_id

Request Example
---------------

.. literalinclude:: ./samples/volume-image-metadata-unset-request.json
   :language: javascript







Attach volume to a server
=========================

.. rest_method::  POST /v3/{project_id}/volumes/{volume_id}/action

Attaches a volume to a server. Specify the ``os-attach`` action in the request body.

Preconditions

- Volume status must be ``available``.

- You should set ``instance_uuid`` or ``host_name``.

Error response codes:202,


Request
-------

.. rest_parameters:: parameters.yaml

   - instance_uuid: instance_uuid
   - mountpoint: mountpoint
   - host_name: host_name
   - os-attach: os-attach
   - project_id: project_id_path
   - volume_id: volume_id

Request Example
---------------

.. literalinclude:: ./samples/volume-attach-request.json
   :language: javascript







Unmanage a volume
=================

.. rest_method::  POST /v3/{project_id}/volumes/{volume_id}/action

Removes a volume from Block Storage management without removing the back-end storage object that is associated with it. Specify the ``os-unmanage`` action in the request body.

Preconditions

- Volume status must be ``available``.

Error response codes:202,


Request
-------

.. rest_parameters:: parameters.yaml

   - os-unmanage: os-unmanage
   - project_id: project_id_path
   - volume_id: volume_id

Request Example
---------------

.. literalinclude:: ./samples/volume-unmanage-request.json
   :language: javascript







Force detach a volume
=====================

.. rest_method::  POST /v3/{project_id}/volumes/{volume_id}/action

Forces a volume to detach. Specify the ``os-force_detach`` action in the request body.

Rolls back an unsuccessful detach operation after you disconnect
the volume.

Error response codes:202,


Request
-------

.. rest_parameters:: parameters.yaml

   - connector: connector
   - attachment_id: attachment_id
   - os-force_detach: os-force_detach
   - project_id: project_id_path
   - volume_id: volume_id

Request Example
---------------

.. literalinclude:: ./samples/volume-force-detach-request.json
   :language: javascript







