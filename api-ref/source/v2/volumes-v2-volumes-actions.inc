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

.. rest_method::  POST /v2/{project_id}/volumes/{volume_id}/action

Extends the size of a volume to a requested size, in gibibytes (GiB). Specify
the ``os-extend`` action in the request body.

Preconditions

- Volume status must be ``available``.

- Sufficient amount of storage must exist to extend the volume.

- The user quota must have sufficient volume storage.

Troubleshooting

- An ``error_extending`` volume status indicates that the request
  failed. Ensure that you meet the preconditions and retry the
  request. If the request fails again, investigate the storage back
  end.


Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202


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


Reset volume statuses
~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v2/{project_id}/volumes/{volume_id}/action

Administrator only. Resets the status, attach status, and migration status for
a volume. Specify the ``os-reset_status`` action in the request body.


Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202


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


Set image metadata for volume
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v2/{project_id}/volumes/{volume_id}/action

Sets the image metadata for a volume. Specify the ``os-set_image_metadata``
action in the request body.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200


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


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - metadata: metadata_8


Response Example
----------------

.. literalinclude:: ./samples/volume-image-metadata-update-response.json
   :language: javascript


Remove image metadata from volume
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v2/{project_id}/volumes/{volume_id}/action

Removes image metadata, by key, from a volume. Specify the
``os-unset_image_metadata`` action in the request body and the ``key`` for the
metadata key and value pair that you want to remove.


Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200


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


Show image metadata for volume
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v2/{project_id}/volumes/{volume_id}/action

Shows image metadata for a volume.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - volume_id: volume_id_path
   - os-show_image_metadata: os-show_image_metadata

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

.. rest_method::  POST /v2/{project_id}/volumes/{volume_id}/action

Attaches a volume to a server. Specify the ``os-attach`` action in the request
body.

Preconditions

- Volume status must be ``available``.

- You should set ``instance_uuid`` or ``host_name``.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202


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


Detach volume from a server
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v2/{project_id}/volumes/{volume_id}/action

Detaches a volume from a server. Specify the ``os-detach`` action in the
request body.

Preconditions

- Volume status must be ``in-use``.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202


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



Unmanage volume
~~~~~~~~~~~~~~~

.. rest_method::  POST /v2/{project_id}/volumes/{volume_id}/action

Removes a volume from Block Storage management without removing the back-end
storage object that is associated with it. Specify the ``os-unmanage`` action
in the request body.

Preconditions

- Volume status must be ``available``.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202


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



Force detach volume
~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v2/{project_id}/volumes/{volume_id}/action

Forces a volume to detach. Specify the ``os-force_detach`` action in the
request body.

Rolls back an unsuccessful detach operation after you disconnect
the volume.

Policy defaults enable only users with the administrative role to
perform this operation. Cloud providers can change these permissions
through the ``volume_extension:volume_admin_actions:force_detach`` rule in
the ``policy.json`` file.


Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202


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



Retype volume
~~~~~~~~~~~~~

.. rest_method::  POST /v2/{project_id}/volumes/{volume_id}/action

Change type of existing volume. Specify the ``os-retype`` action in the request
body.

Change the volume type of existing volume, Cinder may migrate the volume to
proper volume host according to the new volume type.

Retyping an *in-use* volume from a multiattach-capable type to a
non-multiattach-capable type, or vice-versa, is not supported. It is generally
not recommended to retype an *in-use* multiattach volume if that volume has
more than one active read/write attachment.

Policy defaults enable only users with the administrative role or the owner of
the volume to perform this operation. Cloud providers can change these
permissions through the policy.json file.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202


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


Migrate volume
~~~~~~~~~~~~~~

.. rest_method::  POST /v2/{project_id}/volumes/{volume_id}/action

Specify the ``os-migrate_volume`` action in the request body.

Migrates a volume to the specified host.

It is generally not recommended to migrate an *in-use* multiattach volume if
that volume has more than one active read/write attachment.

Policy defaults enable only users with the administrative role to perform this
operation. Cloud providers can change these permissions through the
policy.json file.

**Preconditions**

* The volume ``status`` must be ``available`` or ``in-use``.
* The volume ``migration_status`` must be ``None``, ``deleting``, ``error``,
  or ``success``.
* The volume ``replication_status`` must be ``None``, ``disabled`` or
  ``not-capable``.
* The migration must happen to another host from which the
  volume currently resides.
* The volume must not be a member of a group.
* The volume must not have snapshots.

**Asynchronous Postconditions**

On success, the volume ``status`` will return to its original status of
``available`` or ``in-use`` and the ``migration_status`` will be ``success``.
On failure, the ``migration_status`` will be ``error``. In the case of failure,
if ``lock_volume`` was true and the volume was originally ``available`` when
it was migrated, the ``status`` will go back to ``available``.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202


Request
-------

.. rest_parameters:: parameters.yaml

   - volume_id: volume_id_path
   - project_id: project_id_path
   - os-migrate_volume: os-migrate_volume
   - host: migrate_host
   - force_host_copy: migrate_force_host_copy
   - lock_volume: migrate_lock_volume

Request Example
---------------

.. literalinclude:: ./samples/volume-os-migrate_volume-request.json
   :language: javascript


Complete migration of a volume
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v2/{project_id}/volumes/{volume_id}/action

Specify the ``os-migrate_volume_completion`` action in the request body.

Complete the migration of a volume, updating the new volume in the DB,
returning the ``status`` of the new volume to that of the original volume
and finally deleting the original volume.

**Preconditions**

* Both the original and new volume ``migration_status`` must be ``None`` or
  both must be set to a non ``None`` value.
* Additionally when set the new volume ``migration_status`` must take the
  form of ``target:VOLUME_UUID`` where VOLUME_UUID is the original volume UUID.

**Asynchronous Postconditions**

On success, the volume ``status`` will return to its original status of
``available`` or ``in-use`` and the ``migration_status`` will be ``success``.
On failure, the ``migration_status`` will be ``error``.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202


Request
-------

.. rest_parameters:: parameters.yaml

   - volume_id: volume_id_path
   - project_id: project_id_path
   - os-migrate_volume_completion: os-migrate_volume_completion
   - new_volume: new_volume
   - error: migration_completion_error

Request Example
---------------

.. literalinclude:: ./samples/volume-os-migrate_volume_completion-request.json
   :language: javascript


Force delete volume
~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v2/{project_id}/volumes/{volume_id}/action

Attempts force-delete of volume, regardless of state. Specify the
``os-force_delete`` action in the request body.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202


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


Update volume bootable status
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v2/{project_id}/volumes/{volume_id}/action

Update the bootable status for a volume, mark it as a bootable volume. Specify
the ``os-set_bootable`` action in the request body.


Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200


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

