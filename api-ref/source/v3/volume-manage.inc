.. -*- rst -*-

Volume manage extension (manageable_volumes)
============================================

Creates or lists volumes by using existing storage instead of allocating new
storage.


Manage an existing volume
~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/manageable_volumes

Creates a Block Storage volume by using existing storage rather than allocating
new storage.

The caller must specify a reference to an existing storage volume
in the ref parameter in the request. Although each storage driver
might interpret this reference differently, the driver should
accept a reference structure that contains either a source-id
or source-name element, if possible.

The API chooses the size of the volume by rounding up the size of
the existing storage volume to the next gibibyte (GiB).

Prior to microversion 3.16 host field was required, with the possibility of
defining the cluster it is no longer required, but we must have either a host
or a cluster field but we cannot have them both with values.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - volume: volume
   - description: description_vol
   - availability_zone: availability_zone
   - bootable: bootable_required
   - volume_type: volume_type
   - name: volume_name_optional
   - host: host_mutex
   - cluster: cluster_mutex
   - ref: ref
   - metadata: metadata_vol

Request Example
---------------

.. literalinclude:: ./samples/volume_manage_extensions/volume-manage-request.json
   :language: javascript

.. literalinclude:: ./samples/volume-manage-request-cluster.json
   :language: javascript


Response
--------

.. rest_parameters:: parameters.yaml

   - volume: volume
   - status: status_vol
   - migration_status: migration_status
   - user_id: user_id
   - attachments: attachments
   - links: links_vol
   - availability_zone: availability_zone
   - bootable: bootable_response
   - encrypted: encrypted
   - created_at: created_at
   - description: description_vol
   - updated_at: updated_at
   - volume_type: volume_type
   - name: name_vol
   - replication_status: replication_status
   - consistencygroup_id: consistencygroup_id_required
   - source_volid: source_volid
   - snapshot_id: snapshot_id
   - multiattach: multiattach_resp
   - metadata: metadata_vol_obj
   - id: id_vol
   - size: size

Response Example
----------------

.. literalinclude:: ./samples/volume_manage_extensions/volume-manage-response.json
   :language: javascript


List summary of volumes available to manage
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/manageable_volumes

Search a volume backend and list summary of volumes which are available to
manage.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - sort: sort
   - offset: offset
   - limit: limit
   - marker: marker
   - host: hostname


Response
--------

.. rest_parameters:: parameters.yaml

   - manageable-volumes: manageable-volumes
   - safe_to_manage: safe_to_manage
   - reference: reference
   - source-name: source-name
   - size: size


Response Example
----------------

.. literalinclude:: ./samples/volume-manage-list-response.json
   :language: javascript



List detail of volumes available to manage
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/manageable_volumes/detail

Search a volume backend and list detail of volumes which are available to
manage.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - sort: sort
   - offset: offset
   - limit: limit
   - marker: marker
   - host: host_query


Response
--------

.. rest_parameters:: parameters.yaml

   - manageable-volumes: manageable-volumes
   - cinder_id: cinder_id
   - safe_to_manage: safe_to_manage
   - reason_not_safe: reason_not_safe
   - reference: reference
   - source-name: source-name
   - size: size
   - extra_info: extra_info


Response Example
----------------

.. literalinclude:: ./samples/volume-manage-list-detail-response.json
   :language: javascript
