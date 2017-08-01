.. -*- rst -*-

Volume actions (volumes, action)
================================

Extends the size of, resets statuses for, sets image metadata for,
and removes image metadata from a volume. Attaches a volume to a
server, detaches a volume from a server, and removes a volume from
Block Storage management without actually removing the back-end
storage object associated with it.


Extend a volume size
~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/volumes/{volume_id}/action

Extends the size of a volume to a requested size, in gibibytes (GiB).
Specify the ``os-extend`` action in the request body.

Preconditions

- Prior to microversion ``3.42`` the volume status must be ``available``.
  Starting with microversion ``3.42``, attached volumes with status ``in-use``
  may be able to be extended depending on policy and backend volume and
  compute driver constraints in the cloud. Note that ``reserved`` is not a
  valid state for extend.

- Sufficient amount of storage must exist to extend the volume.

- The user quota must have sufficient volume storage.

Postconditions

- If the request is processed successfully, the volume status will change to
  ``extending`` while the volume size is being extended.

- Upon successful completion of the extend operation, the volume status will
  go back to its original value.

- Starting with microversion ``3.42``, when extending the size of an attached
  volume, the Block Storage service will notify the Compute service that an
  attached volume has been extended. The Compute service will asynchronously
  process the volume size change for the related server instance. This can be
  monitored using the ``GET /servers/{server_id}/os-instance-actions`` API in
  the Compute service.

Troubleshooting

- An ``error_extending`` volume status indicates that the request
  failed. Ensure that you meet the preconditions and retry the
  request. If the request fails again, investigate the storage back
  end.

Normal response codes: 202


Request
-------

.. rest_parameters:: parameters.yaml

   - os-extend: os-extend
   - new_size: new_size
   - project_id: project_id_path
   - volume_id: volume_id_path

Request Example
---------------

.. literalinclude:: ./samples/volume-extend-request.json
   :language: javascript







Reset a volume's statuses
~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/volumes/{volume_id}/action

Administrator only. Resets the status, attach status, revert to snapshot,
and migration status for a volume. Specify the ``os-reset_status`` action in the request body.

Normal response codes: 202


Request
-------

.. rest_parameters:: parameters.yaml

   - status: status_3
   - migration_status: migration_status
   - os-reset_status: os-reset_status
   - attach_status: attach_status
   - project_id: project_id_path
   - volume_id: volume_id_path

Request Example
---------------

.. literalinclude:: ./samples/volume-status-reset-request.json
   :language: javascript


Revert volume to snapshot
~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/volumes/{volume_id}/action

Revert a volume to its latest snapshot, this API only support reverting a detached volume.

Normal response codes: 202
Error response codes: 400, 404

Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - volume_id: volume_id
   - revert: revert
   - snapshot_id: snapshot_id_4

Request Example
---------------

.. literalinclude:: ./samples/volume-revert-to-snapshot-request.json
   :language: javascript


Set image metadata for a volume
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/volumes/{volume_id}/action

Sets the image metadata for a volume. Specify the ``os-set_image_metadata`` action in the request body.

Normal response codes: 200


Request
-------

.. rest_parameters:: parameters.yaml

   - os-set_image_metadata: os-set_image_metadata
   - metadata: metadata
   - project_id: project_id_path
   - volume_id: volume_id_path

Request Example
---------------

.. literalinclude:: ./samples/volume-image-metadata-set-request.json
   :language: javascript







Remove image metadata from a volume
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/volumes/{volume_id}/action

Removes image metadata, by key, from a volume. Specify the ``os-unset_image_metadata`` action in the request body and the ``key`` for the metadata key and value pair that you want to remove.

Normal response codes: 200


Request
-------

.. rest_parameters:: parameters.yaml

   - os-unset_image_metadata: os-unset_image_metadata
   - key: key
   - project_id: project_id_path
   - volume_id: volume_id_path

Request Example
---------------

.. literalinclude:: ./samples/volume-image-metadata-unset-request.json
   :language: javascript




Show image metadata for a volume
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/volumes/{volume_id}/action

Shows image metadata for a volume.

Normal response codes: 200


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - volume_id: volume_id_path
   - os-vol-image-meta: os-show_image_metadata

Request Example
---------------

.. literalinclude:: ./samples/image-metadata-show-request.json
   :language: javascript

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - metadata: metadata_8

Response Example
----------------

.. literalinclude:: ./samples/image-metadata-show-response.json
   :language: javascript



Attach volume to a server
~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/volumes/{volume_id}/action

Attaches a volume to a server. Specify the ``os-attach`` action in the request body.

Preconditions

- Volume status must be ``available``.

- You should set ``instance_uuid`` or ``host_name``.

Normal response codes: 202


Request
-------

.. rest_parameters:: parameters.yaml

   - instance_uuid: instance_uuid
   - mountpoint: mountpoint
   - host_name: host_name
   - os-attach: os-attach
   - project_id: project_id_path
   - volume_id: volume_id_path

Request Example
---------------

.. literalinclude:: ./samples/volume-attach-request.json
   :language: javascript







Detach volume from server
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/volumes/{volume_id}/action

Detaches a volume from a server. Specify the ``os-detach`` action in the request body.

Preconditions

- Volume status must be ``in-use``.

Normal response codes: 202


Request
-------

.. rest_parameters:: parameters.yaml

   - attachment_id: attachment_id
   - os-detach: os-detach
   - project_id: project_id_path
   - volume_id: volume_id_path

Request Example
---------------

.. literalinclude:: ./samples/volume-detach-request.json
   :language: javascript







Unmanage a volume
~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/volumes/{volume_id}/action

Removes a volume from Block Storage management without removing the back-end storage object that is associated with it. Specify the ``os-unmanage`` action in the request body.

Preconditions

- Volume status must be ``available``.

Normal response codes: 202


Request
-------

.. rest_parameters:: parameters.yaml

   - os-unmanage: os-unmanage
   - project_id: project_id_path
   - volume_id: volume_id_path

Request Example
---------------

.. literalinclude:: ./samples/volume-unmanage-request.json
   :language: javascript







Force detach a volume
~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/volumes/{volume_id}/action

Forces a volume to detach. Specify the ``os-force_detach`` action in the request body.

Rolls back an unsuccessful detach operation after you disconnect
the volume.

Normal response codes: 202


Request
-------

.. rest_parameters:: parameters.yaml

   - connector: connector
   - attachment_id: attachment_id
   - os-force_detach: os-force_detach
   - project_id: project_id_path
   - volume_id: volume_id_path

Request Example
---------------

.. literalinclude:: ./samples/volume-force-detach-request.json
   :language: javascript







Retype a volume
~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/volumes/{volume_id}/action

Change type of existing volume. Specify the ``os-retype`` action in the request body.

Change the volume type of existing volume, Cinder may migrate the volume to
proper volume host according to the new volume type.

Policy defaults enable only users with the administrative role or the owner of
the volume to perform this operation. Cloud providers can change these
permissions through the policy.json file.

Normal response codes: 202


Request
-------

.. rest_parameters:: parameters.yaml

   - new_type: new_type
   - migration_policy: migration_policy
   - os-retype: os-retype
   - volume_id: volume_id_path
   - project_id: project_id_path

Request Example
---------------

.. literalinclude:: ./samples/volume-os-retype-request.json
   :language: javascript







Force delete a volume
~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/volumes/{volume_id}/action

Attempts force-delete of volume, regardless of state. Specify the ``os-force_delete`` action
in the request body.


Normal response codes: 202


Request
-------

.. rest_parameters:: parameters.yaml

   - os-force_delete: os-force_delete
   - project_id: project_id_path
   - volume_id: volume_id_path

Request Example
---------------

.. literalinclude:: ./samples/volume-force-delete-request.json
   :language: javascript







Update a volume's bootable status
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/volumes/{volume_id}/action

Update the bootable status for a volume, mark it as a bootable volume. Specify the ``os-set_bootable`` action in the request body.

Normal response codes: 200


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - volume_id: volume_id_path
   - os-set_bootable: os-set_bootable
   - bootable: bootable

Request Example
---------------

.. literalinclude:: ./samples/volume-bootable-status-update-request.json
   :language: javascript






Upload volume to image
~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/volumes/{volume_id}/action

Uploads the specified volume to image service.

Normal response codes: 202


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - volume_id: volume_id_path
   - os-volume_upload_image: os-volume_upload_image
   - image_name: image_name
   - force: force_4
   - disk_format: disk_format
   - container_format: container_format
   - visibility: visibility_1
   - protected: protected

Request Example
---------------

.. literalinclude:: ./samples/volume-upload-to-image-request.json
   :language: javascript

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - os-volume_upload_image: os-volume_upload_image
   - status: status_3
   - image_name: image_name
   - disk_format: disk_format
   - container_format: container_format
   - visibility: visibility_1
   - protected: protected
   - updated_at: updated_at
   - image_id: image_id
   - display_description: description_9
   - id: id_5
   - size: size
   - volume_type: volume_type_6


Response Example
----------------

.. literalinclude:: ./samples/volume-upload-to-image-response.json
   :language: javascript
