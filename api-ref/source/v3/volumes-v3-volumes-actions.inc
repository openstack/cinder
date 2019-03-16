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

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - volume_id: volume_id_path
   - os-extend: os-extend
   - new_size: new_size

Request Example
---------------

.. literalinclude:: ./samples/volume-extend-request.json
   :language: javascript


Reset a volume's statuses
~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/volumes/{volume_id}/action

Administrator only. Resets the status, attach status, revert to snapshot,
and migration status for a volume. Specify the ``os-reset_status`` action in
the request body.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - volume_id: volume_id_path
   - os-reset_status: os-reset_status
   - status: status_vol
   - migration_status: migration_status
   - attach_status: attach_status

Request Example
---------------

.. literalinclude:: ./samples/volume-status-reset-request.json
   :language: javascript


Revert volume to snapshot
~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/volumes/{volume_id}/action

Revert a volume to its latest snapshot, this API only support reverting a
detached volume, and the volume status must be ``available``.

Available since API microversion ``3.40``.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202

.. rest_status_code:: error ../status.yaml

   - 400
   - 403
   - 404
   - 409

Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - volume_id: volume_id_path
   - revert: revert
   - snapshot_id: snapshot_id_revert

Request Example
---------------

.. literalinclude:: ./samples/volume-revert-to-snapshot-request.json
   :language: javascript


Set image metadata for a volume
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/volumes/{volume_id}/action

Sets the image metadata for a volume. Specify the ``os-set_image_metadata``
action in the request body.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - volume_id: volume_id_path
   - os-set_image_metadata: os-set_image_metadata
   - metadata: metadata_image

Request Example
---------------

.. literalinclude:: ./samples/volume-image-metadata-set-request.json
   :language: javascript


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - metadata: metadata_image


Response Example
----------------

.. literalinclude:: ./samples/volume-image-metadata-update-response.json
   :language: javascript


Remove image metadata from a volume
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/volumes/{volume_id}/action

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

   - project_id: project_id_path
   - volume_id: volume_id_path
   - os-unset_image_metadata: os-unset_image_metadata
   - key: key

Request Example
---------------

.. literalinclude:: ./samples/volume-image-metadata-unset-request.json
   :language: javascript




Show image metadata for a volume
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/volumes/{volume_id}/action

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

   - metadata: metadata_image

Response Example
----------------

.. literalinclude:: ./samples/image-metadata-show-response.json
   :language: javascript



Attach volume to a server
~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/volumes/{volume_id}/action

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

   - project_id: project_id_path
   - volume_id: volume_id_path
   - os-attach: os-attach
   - instance_uuid: instance_uuid
   - mountpoint: mountpoint
   - host_name: host_name

Request Example
---------------

.. literalinclude:: ./samples/volume-attach-request.json
   :language: javascript



Detach volume from server
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/volumes/{volume_id}/action

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

   - project_id: project_id_path
   - volume_id: volume_id_path
   - os-detach: os-detach
   - attachment_id: attachment_id

Request Example
---------------

.. literalinclude:: ./samples/volume-detach-request.json
   :language: javascript


Unmanage a volume
~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/volumes/{volume_id}/action

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

   - project_id: project_id_path
   - volume_id: volume_id_path
   - os-unmanage: os-unmanage

Request Example
---------------

.. literalinclude:: ./samples/volume-unmanage-request.json
   :language: javascript


Force detach a volume
~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/volumes/{volume_id}/action

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

   - project_id: project_id_path
   - volume_id: volume_id_path
   - os-force_detach: os-force_detach
   - attachment_id: attachment_id
   - connector: connector

Request Example
---------------

.. literalinclude:: ./samples/volume-force-detach-request.json
   :language: javascript


Retype a volume
~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/volumes/{volume_id}/action

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

   - project_id: project_id_path
   - volume_id: volume_id_path
   - os-retype: os-retype
   - new_type: new_type
   - migration_policy: migration_policy

Request Example
---------------

.. literalinclude:: ./samples/volume-os-retype-request.json
   :language: javascript


Migrate a volume
~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/volumes/{volume_id}/action

Specify the ``os-migrate_volume`` action in the request body.

Migrates a volume to the specified host. Starting with the
`3.16 microversion`_ a cluster can be specified instead of a host.

It is generally not recommended to migrate an *in-use* multiattach volume if
that volume has more than one active read/write attachment.

Policy defaults enable only users with the administrative role to perform this
operation. Cloud providers can change these permissions through the
policy.json file.

.. _3.16 microversion: https://docs.openstack.org/cinder/latest/contributor/api_microversion_history.html#id15

**Preconditions**

* The volume ``status`` must be ``available`` or ``in-use``.
* The volume ``migration_status`` must be ``None``, ``deleting``, ``error``,
  or ``success``.
* The volume ``replication_status`` must be ``None``, ``disabled`` or
  ``not-capable``.
* The migration must happen to another host (or cluster) from which the
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
   - cluster: migrate_cluster

Request Example
---------------

.. literalinclude:: ./samples/volume-os-migrate_volume-request.json
   :language: javascript


Complete migration of a volume
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/volumes/{volume_id}/action

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


Force delete a volume
~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/volumes/{volume_id}/action

Attempts force-delete of volume, regardless of state. Specify the
``os-force_delete`` action in the request body.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - volume_id: volume_id_path
   - os-force_delete: os-force_delete

Request Example
---------------

.. literalinclude:: ./samples/volume-force-delete-request.json
   :language: javascript


Update a volume's bootable status
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/volumes/{volume_id}/action

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
   - bootable: bootable_required

Request Example
---------------

.. literalinclude:: ./samples/volume-bootable-status-update-request.json
   :language: javascript


Upload volume to image
~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/volumes/{volume_id}/action

Uploads the specified volume to image service.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - volume_id: volume_id_path
   - os-volume_upload_image: os-volume_upload_image
   - image_name: image_name
   - force: force_upload_vol
   - disk_format: disk_format
   - container_format: container_format
   - visibility: visibility_min
   - protected: protected

Request Example
---------------

.. literalinclude:: ./samples/volume_actions/volume-upload-to-image-request.json
   :language: javascript

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - os-volume_upload_image: os-volume_upload_image
   - status: status_vol
   - image_name: image_name
   - disk_format: disk_format
   - container_format: container_format
   - visibility: visibility_min
   - protected: protected
   - updated_at: updated_at
   - image_id: image_id
   - display_description: description_vol_req
   - id: id_vol
   - size: size
   - volume_type: volume_type_vol


Response Example
----------------

.. literalinclude:: ./samples/volume_actions/volume-upload-to-image-response.json
   :language: javascript


Reserve volume
~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/volumes/{volume_id}/action

Mark volume as reserved. Specify the ``os-reserve`` action in the
request body.

Preconditions

- Volume status must be ``available``.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - volume_id: volume_id_path
   - os-reserve: os-reserve

Request Example
---------------

.. literalinclude:: ./samples/volume-reserve-request.json
   :language: javascript


Unmark volume as reserved.
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/volumes/{volume_id}/action

Unmark volume as reserved. Specify the ``os-unreserve`` action in
the request body.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - volume_id: volume_id_path
   - os-unreserve: os-unreserve

Request Example
---------------

.. literalinclude:: ./samples/volume-unreserve-request.json
   :language: javascript


Update volume status to detaching
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/volumes/{volume_id}/action

Update volume status to 'detaching'.. Specify the ``os-begin_detaching`` action
in the request body.


Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - volume_id: volume_id_path
   - os-begin_detaching: os-begin_detaching

Request Example
---------------

.. literalinclude:: ./samples/volume-begin-detaching-request.json
   :language: javascript



Roll back volume status to in-use
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/volumes/{volume_id}/action

Roll back volume status to 'in-use'. Specify the ``os-roll_detaching`` action
in the request body.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - volume_id: volume_id_path
   - os-roll_detaching: os-roll_detaching

Request Example
---------------

.. literalinclude:: ./samples/volume-roll-detaching-request.json
   :language: javascript


Terminate volume attachment
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/volumes/{volume_id}/action

Terminate volume attachment. Specify the ``os-terminate_connection``
action in the request body.

Preconditions

- Volume status must be ``in-use``.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - volume_id: volume_id_path
   - os-terminate_connection: os-terminate_connection
   - connector: connector_required

Request Example
---------------

.. literalinclude:: ./samples/volume-terminate-connection-request.json
   :language: javascript



Initialize volume attachment
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/volumes/{volume_id}/action

Initialize volume attachment. Specify the ``os-initialize_connection``
action in the request body.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - volume_id: volume_id_path
   - os-initialize_connection: os-initialize_connection
   - connector: connector_required

Request Example
---------------

.. literalinclude:: ./samples/volume-initialize-connection-request.json
   :language: javascript


Updates volume read-only access-mode flag
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/volumes/{volume_id}/action

Enables or disables update of volume to read-only access mode.
Specify the ``os-update_readonly_flag`` action in the request body.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - volume_id: volume_id_path
   - os-update_readonly_flag: os-update_readonly_flag
   - readonly: readonly

Request Example
---------------

.. literalinclude:: ./samples/volume-readonly-update-request.json
   :language: javascript
