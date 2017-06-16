.. -*- rst -*-

Volume manage extension (manageable_volumes)
============================================

Creates or lists volumes by using existing storage instead of allocating new
storage.


Manage an existing volume
~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/manageable_volumes

Creates a Block Storage volume by using existing storage rather than allocating new storage.

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

Normal response codes: 202


Request
-------

.. rest_parameters:: parameters.yaml

   - description: description
   - availability_zone: availability_zone
   - bootable: bootable
   - volume_type: volume_type
   - name: name
   - volume: volume
   - host: host_mutex
   - cluster: cluster_mutex
   - ref: ref
   - metadata: metadata
   - project_id: project_id_path

Request Example
---------------

.. literalinclude:: ./samples/volume-manage-request.json
   :language: javascript

.. literalinclude:: ./samples/volume-manage-request-cluster.json
   :language: javascript


List summary of volumes available to manage
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/manageable_volumes

Search a volume backend and list summary of volumes which are available to
manage.

Normal response codes: 200


Request
-------

.. rest_parameters:: parameters.yaml

   - sort: sort
   - offset: offset
   - limit: limit
   - marker: marker
   - project_id: project_id_path
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

Normal response codes: 200


Request
-------

.. rest_parameters:: parameters.yaml

   - sort: sort
   - offset: offset
   - limit: limit
   - marker: marker
   - project_id: project_id_path
   - host: hostname


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
