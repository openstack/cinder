.. -*- rst -*-

Volume manage extension (os-volume-manage)
==========================================

Creates volumes by using existing storage instead of allocating new
storage.


Manage existing volume
~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v2/{project_id}/os-volume-manage

Creates a Block Storage volume by using existing storage rather than allocating
new storage.

The caller must specify a reference to an existing storage volume
in the ref parameter in the request. Although each storage driver
might interpret this reference differently, the driver should
accept a reference structure that contains either a source-id
or source-name element, if possible.

The API chooses the size of the volume by rounding up the size of
the existing storage volume to the next gibibyte (GiB).

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202


Request
-------

.. rest_parameters:: parameters.yaml

   - description: description
   - availability_zone: availability_zone
   - bootable: bootable
   - volume_type: volume_type
   - name: name
   - volume: volume
   - host: host
   - ref: ref
   - metadata: metadata
   - project_id: project_id_path

Request Example
---------------

.. literalinclude:: ./samples/volume-manage-request.json
   :language: javascript


Response
--------

.. rest_parameters:: parameters.yaml

   - volume: volume
   - status: status_3
   - migration_status: migration_status
   - user_id: user_id
   - attachments: attachments
   - links: links_3
   - availability_zone: availability_zone
   - bootable: bootable_response
   - encrypted: encrypted
   - created_at: created_at
   - description: description_5
   - updated_at: updated_at
   - volume_type: volume_type
   - name: name_13
   - replication_status: replication_status
   - consistencygroup_id: consistencygroup_id
   - source_volid: source_volid
   - snapshot_id: snapshot_id
   - multiattach: multiattach_resp
   - metadata: metadata_1
   - id: id_5
   - size: size

Response Example
----------------

.. literalinclude:: ./samples/volume-manage-response.json
   :language: javascript
