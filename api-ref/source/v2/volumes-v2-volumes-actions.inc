.. -*- rst -*-

Volume actions (volumes, action)
================================

Extends the size of, resets statuses for, sets image metadata for,
and removes image metadata from a volume. Attaches a volume to a
server, detaches a volume from a server, and removes a volume from
Block Storage management without actually removing the back-end
storage object associated with it.


Extend volume size
~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v2/{tenant_id}/volumes/{volume_id}/action

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

Normal response codes: 202,


Request
-------

.. rest_parameters:: parameters.yaml

   - os-extend: os-extend
   - new_size: new_size
   - tenant_id: tenant_id
   - volume_id: volume_id_path

Request Example
---------------

.. literalinclude:: ./samples/volume-extend-request.json
   :language: javascript







Reset volume statuses
~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v2/{tenant_id}/volumes/{volume_id}/action

Administrator only. Resets the status, attach status, and migration status for a volume. Specify the ``os-reset_status`` action in the request body.

Normal response codes: 202,


Request
-------

.. rest_parameters:: parameters.yaml

   - status: status_3
   - migration_status: migration_status
   - os-reset_status: os-reset_status
   - attach_status: attach_status
   - tenant_id: tenant_id
   - volume_id: volume_id_path

Request Example
---------------

.. literalinclude:: ./samples/volume-status-reset-request.json
   :language: javascript







Set image metadata for volume
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v2/{tenant_id}/volumes/{volume_id}/action

Sets the image metadata for a volume. Specify the ``os-set_image_metadata`` action in the request body.

Normal response codes: 200


Request
-------

.. rest_parameters:: parameters.yaml

   - os-set_image_metadata: os-set_image_metadata
   - metadata: metadata
   - tenant_id: tenant_id
   - volume_id: volume_id_path

Request Example
---------------

.. literalinclude:: ./samples/volume-image-metadata-set-request.json
   :language: javascript







Remove image metadata from volume
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v2/{tenant_id}/volumes/{volume_id}/action

Removes image metadata, by key, from a volume. Specify the ``os-unset_image_metadata`` action in the request body and the ``key`` for the metadata key and value pair that you want to remove.

Normal response codes: 200


Request
-------

.. rest_parameters:: parameters.yaml

   - os-unset_image_metadata: os-unset_image_metadata
   - key: key
   - tenant_id: tenant_id
   - volume_id: volume_id_path

Request Example
---------------

.. literalinclude:: ./samples/volume-image-metadata-unset-request.json
   :language: javascript





Show image metadata for volume
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v2/{project_id}/volumes/{volume_id}/action

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




Attach volume to server
~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v2/{tenant_id}/volumes/{volume_id}/action

Attaches a volume to a server. Specify the ``os-attach`` action in the request body.

Preconditions

- Volume status must be ``available``.

- You should set ``instance_uuid`` or ``host_name``.

Normal response codes: 202,


Request
-------

.. rest_parameters:: parameters.yaml

   - instance_uuid: instance_uuid
   - mountpoint: mountpoint
   - host_name: host_name
   - os-attach: os-attach
   - tenant_id: tenant_id
   - volume_id: volume_id_path

Request Example
---------------

.. literalinclude:: ./samples/volume-attach-request.json
   :language: javascript







Detach volume from a server
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v2/{tenant_id}/volumes/{volume_id}/action

Detaches a volume from a server. Specify the ``os-detach`` action in the request body.

Preconditions

- Volume status must be ``in-use``.

Normal response codes: 202,


Request
-------

.. rest_parameters:: parameters.yaml

   - attachment_id: attachment_id
   - os-detach: os-detach
   - tenant_id: tenant_id
   - volume_id: volume_id_path

Request Example
---------------

.. literalinclude:: ./samples/volume-detach-request.json
   :language: javascript










Unmanage volume
~~~~~~~~~~~~~~~

.. rest_method::  POST /v2/{tenant_id}/volumes/{volume_id}/action

Removes a volume from Block Storage management without removing the back-end storage object that is associated with it. Specify the ``os-unmanage`` action in the request body.

Preconditions

- Volume status must be ``available``.

Normal response codes: 202,


Request
-------

.. rest_parameters:: parameters.yaml

   - os-unmanage: os-unmanage
   - tenant_id: tenant_id
   - volume_id: volume_id_path

Request Example
---------------

.. literalinclude:: ./samples/volume-unmanage-request.json
   :language: javascript







Force detach volume
~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v2/{tenant_id}/volumes/{volume_id}/action

Forces a volume to detach. Specify the ``os-force_detach`` action in the request body.

Rolls back an unsuccessful detach operation after you disconnect
the volume.

Normal response codes: 202,


Request
-------

.. rest_parameters:: parameters.yaml

   - connector: connector
   - attachment_id: attachment_id
   - os-force_detach: os-force_detach
   - tenant_id: tenant_id
   - volume_id: volume_id_path

Request Example
---------------

.. literalinclude:: ./samples/volume-force-detach-request.json
   :language: javascript







Retype volume
~~~~~~~~~~~~~

.. rest_method::  POST /v2/{project_id}/volumes/{volume_id}/action

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







Force delete volume
~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v2/{tenant_id}/volumes/{volume_id}/action

Attempts force-delete of volume, regardless of state. Specify the ``os-force_delete`` action
in the request body.


Normal response codes: 202


Request
-------

.. rest_parameters:: parameters.yaml

   - os-force_delete: os-force_delete
   - tenant_id: tenant_id
   - volume_id: volume_id_path

Request Example
---------------

.. literalinclude:: ./samples/volume-force-delete-request.json
   :language: javascript







Update volume bootable status
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v2/{tenant_id}/volumes/{volume_id}/action

Update the bootable status for a volume, mark it as a bootable volume. Specify the ``os-set_bootable`` action in the request body.

Normal response codes: 200


Request
-------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - volume_id: volume_id_path
   - os-set_bootable: os-set_bootable
   - bootable: bootable

Request Example
---------------

.. literalinclude:: ./samples/volume-bootable-status-update-request.json
   :language: javascript

