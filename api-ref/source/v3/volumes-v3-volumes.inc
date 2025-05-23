.. -*- rst -*-

Volumes (volumes)
=================

A volume is a detachable block storage device similar to a USB hard
drive. You can attach a volume to an instance, and if the volume is
of an appropriate volume type, a volume can be attached to multiple
instances.

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
   - sort_key: sort_key
   - sort_dir: sort_dir
   - limit: limit
   - offset: offset
   - marker: marker
   - with_count: with_count
   - created_at: filter_created_at
   - updated_at: filter_updated_at
   - consumes_quota: filter_consumes_quota


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - migration_status: migration_status
   - attachments: attachments
   - links: links_vol
   - availability_zone: availability_zone
   - os-vol-host-attr:host: os-vol-host-attr:host
   - encrypted: encrypted
   - encryption_key_id: encryption_key_id
   - updated_at: updated_at
   - replication_status: replication_status
   - snapshot_id: snapshot_id
   - id: id_vol
   - size: size
   - user_id: user_id
   - os-vol-tenant-attr:tenant_id: os-vol-tenant-attr:tenant_id
   - os-vol-mig-status-attr:migstat: os-vol-mig-status-attr:migstat
   - metadata: metadata_vol_obj
   - status: status_vol
   - volume_image_metadata: volume_image_metadata
   - description: description_vol_req
   - multiattach: multiattach_resp
   - source_volid: source_volid
   - consistencygroup_id: consistencygroup_id_required
   - os-vol-mig-status-attr:name_id: os-vol-mig-status-attr:name_id
   - name: name_vol
   - bootable: bootable_response
   - created_at: created_at
   - volumes: volumes
   - volume_type: volume_type_vol
   - volume_type_id: volume_type_id_363
   - group_id: group_id_optional
   - volumes_links: links_vol_optional
   - provider_id:  provider_id
   - service_uuid: service_uuid
   - shared_targets: shared_targets
   - shared_targets: shared_targets_tristate
   - cluster_name: volume_cluster_name
   - consumes_quota: consumes_quota
   - count: count


Response Example (v3.65)
------------------------

.. literalinclude:: ./samples/volumes/v3.65/volumes-list-detailed-response.json
   :language: javascript




Create a volume
~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/volumes

Creates a volume.

To create a bootable volume, include the UUID of the image from
which you want to create the volume in the ``imageRef`` attribute
in the request body.

Since the Train release, every volume must have a volume type.  It
is **optional** to specify a volume type as part of your `Create a
volume` request.  If you do not specify one, a default volume type
will be supplied for you.  This type may vary according to what
project you are in and how the operator has configured the Block
Storage service.  Use the `Show default volume type`_ request to
determine your effective default volume type.

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

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - volume: volume
   - size: size
   - availability_zone: availability_zone
   - source_volid: source_volid
   - description: description_vol
   - snapshot_id: snapshot_id
   - backup_id: backup_id
   - name: volume_name_optional
   - imageRef: imageRef
   - volume_type: volume_type_detail
   - metadata: metadata_vol
   - consistencygroup_id: consistencygroup_id_required
   - OS-SCH-HNT:scheduler_hints: OS-SCH-HNT:scheduler_hints

Request Example
---------------

.. literalinclude:: ./samples/volumes/volume-create-request.json
   :language: javascript



Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - migration_status: migration_status
   - attachments: attachments
   - links: links_vol
   - availability_zone: availability_zone
   - encrypted: encrypted
   - updated_at: updated_at
   - replication_status: replication_status
   - snapshot_id: snapshot_id
   - id: id_vol
   - size: size
   - user_id: user_id
   - metadata: metadata_vol_obj
   - status: status_vol
   - description: description_vol_req
   - multiattach: multiattach_resp
   - source_volid: source_volid
   - volume: volume
   - consistencygroup_id: consistencygroup_id_required
   - name: name_vol
   - bootable: bootable_response
   - created_at: created_at
   - volume_type: volume_type_vol
   - volume_type_id: volume_type_id_363
   - group_id: group_id_optional
   - provider_id:  provider_id
   - service_uuid: service_uuid
   - shared_targets: shared_targets
   - shared_targets: shared_targets_tristate
   - cluster_name: volume_cluster_name
   - consumes_quota: consumes_quota

Response Example (v3.65)
------------------------

.. literalinclude:: ./samples/volumes/v3.65/volume-create-response.json
   :language: javascript


List accessible volumes
~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/volumes

Lists summary information for all Block Storage volumes that the
project can access, since v3.31 if non-admin users specify invalid
filters in the url, API will return bad request.


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
   - sort_key: sort_key
   - sort_dir: sort_dir
   - limit: limit
   - offset: offset
   - marker: marker
   - with_count: with_count
   - created_at: filter_created_at
   - consumes_quota: filter_consumes_quota
   - updated_at: filter_updated_at


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - volumes: volumes
   - id: id_vol
   - links: links_vol
   - name: name_vol
   - volumes_links: links_vol_optional
   - count: count



Response Example
----------------

.. literalinclude:: ./samples/volumes/volumes-list-response.json
   :language: javascript




Show a volume's details
~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/volumes/{volume_id}

Shows details for a volume.

Preconditions

- The volume must exist.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200


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
   - links: links_vol
   - availability_zone: availability_zone
   - os-vol-host-attr:host: os-vol-host-attr:host
   - encrypted: encrypted
   - encryption_key_id: encryption_key_id
   - updated_at: updated_at
   - replication_status: replication_status
   - snapshot_id: snapshot_id
   - id: id_vol
   - size: size
   - user_id: user_id
   - os-vol-tenant-attr:tenant_id: os-vol-tenant-attr:tenant_id
   - os-vol-mig-status-attr:migstat: os-vol-mig-status-attr:migstat
   - metadata: metadata_vol_obj
   - status: status_vol
   - volume_image_metadata: volume_image_metadata
   - description: description_vol_req
   - multiattach: multiattach_resp
   - source_volid: source_volid
   - volume: volume
   - consistencygroup_id: consistencygroup_id_required
   - os-vol-mig-status-attr:name_id: os-vol-mig-status-attr:name_id
   - name: name_vol
   - bootable: bootable_response
   - created_at: created_at
   - volume_type: volume_type_vol
   - volume_type_id: volume_type_id_363
   - service_uuid: service_uuid
   - shared_targets: shared_targets
   - shared_targets: shared_targets_tristate
   - cluster_name: volume_cluster_name
   - provider_id:  provider_id
   - group_id: group_id_optional
   - consumes_quota: consumes_quota


Response Example (v3.65)
------------------------

.. literalinclude:: ./samples/volumes/v3.65/volume-show-response.json
   :language: javascript




Update a volume
~~~~~~~~~~~~~~~

.. rest_method::  PUT /v3/{project_id}/volumes/{volume_id}

Updates a volume.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - volume_id: volume_id_path
   - volume: volume
   - description: description_vol
   - name: volume_name_optional
   - metadata: metadata_vol_assoc

Request Example
---------------

.. literalinclude:: ./samples/volumes/volume-update-request.json
   :language: javascript



Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - migration_status: migration_status
   - attachments: attachments
   - links: links_vol
   - availability_zone: availability_zone
   - encrypted: encrypted
   - updated_at: updated_at
   - replication_status: replication_status
   - snapshot_id: snapshot_id
   - id: id_vol
   - size: size
   - user_id: user_id
   - metadata: metadata_vol_obj
   - status: status_vol
   - description: description_vol_req
   - multiattach: multiattach_resp
   - source_volid: source_volid
   - volume: volume
   - consistencygroup_id: consistencygroup_id_required
   - name: name_vol
   - bootable: bootable_response
   - created_at: created_at
   - volume_type: volume_type_vol
   - volume_type_id: volume_type_id_363
   - group_id: group_id_optional
   - provider_id:  provider_id
   - service_uuid: service_uuid
   - shared_targets: shared_targets
   - shared_targets: shared_targets_tristate
   - cluster_name: volume_cluster_name
   - consumes_quota: consumes_quota


Response Example (v3.65)
------------------------

.. literalinclude:: ./samples/volumes/v3.65/volume-update-response.json
   :language: javascript


Delete a volume
~~~~~~~~~~~~~~~

.. rest_method::  DELETE /v3/{project_id}/volumes/{volume_id}

Deletes a volume.

Preconditions

- Volume status must be ``available``, ``in-use``, ``error``,
  ``error_restoring``, ``error_extending``, ``error_managing``,
  and must not be ``migrating``, ``attached``, ``awaiting-transfer``,
  belong to a group, have snapshots or be disassociated from
  snapshots after volume transfer.

- The ``cascade`` option can be passed in the request if you want
  all snapshots of this volume to be deleted automatically,
  which should allow the volume deletion to succeed.

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

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - volume_id: volume_id_path
   - cascade: cascade
   - force: force_vol_del


Create metadata for volume
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/volumes/{volume_id}/metadata

Creates or replaces metadata for a volume. Does not modify items that are not
in the request.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - volume_id: volume_id_path
   - metadata: metadata_vol_assoc_req

Request Example
---------------

.. literalinclude:: ./samples/volumes/volume-metadata-create-request.json
   :language: javascript



Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - metadata: metadata_vol_assoc_req


Response Example
----------------

.. literalinclude:: ./samples/volumes/volume-metadata-create-response.json
   :language: javascript


Show a volume's metadata
~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/volumes/{volume_id}/metadata

Shows metadata for a volume.


Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - volume_id: volume_id_path


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - metadata: metadata_vol_assoc_req



Response Example
----------------

.. literalinclude:: ./samples/volumes/volume-metadata-show-response.json
   :language: javascript


Update a volume's metadata
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  PUT /v3/{project_id}/volumes/{volume_id}/metadata

Replaces all the volume's metadata with the key-value pairs in the request.


Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - volume_id: volume_id_path
   - metadata: metadata_vol_assoc_req

Request Example
---------------

.. literalinclude:: ./samples/volumes/volume-metadata-update-request.json
   :language: javascript



Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - metadata: metadata_vol_assoc_req



Response Example
----------------

.. literalinclude:: ./samples/volumes/volume-metadata-update-response.json
   :language: javascript


Show a volume's metadata for a specific key
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/volumes/{volume_id}/metadata/{key}

Shows metadata for a volume for a specific key.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - volume_id: volume_id_path
   - key: key_view


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - meta: meta



Response Example
----------------

.. literalinclude:: ./samples/volumes/volume-metadata-show-key-response.json
   :language: javascript



Delete a volume's metadata
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  DELETE /v3/{project_id}/volumes/{volume_id}/metadata/{key}

Deletes metadata for a volume.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - volume_id: volume_id_path
   - key: key_path


Update a volume's metadata for a specific key
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  PUT /v3/{project_id}/volumes/{volume_id}/metadata/{key}

Update metadata for a volume for a specific key.


Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - volume_id: volume_id_path
   - key: key_update
   - meta: meta

Request Example
---------------

.. literalinclude:: ./samples/volumes/volume-metadata-update-key-request.json
   :language: javascript

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - meta: meta

Response Example
----------------

.. literalinclude:: ./samples/volumes/volume-metadata-update-key-response.json
   :language: javascript


Get volumes summary
~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/volumes/summary

Display volumes summary with total number of volumes and total size in GB.
Available since API microversion 3.12.


Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - all_tenants: all-tenants

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - volume-summary: volume-summary
   - total_size: total_size
   - total_count: total_count_int
   - metadata: summary_metadata


Response Example
----------------

.. literalinclude:: ./samples/volumes/volumes-list-summary-response.json
   :language: javascript
