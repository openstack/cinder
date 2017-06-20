.. -*- rst -*-

Consistency groups
==================

Consistency groups enable you to create snapshots at the exact same
point in time from multiple volumes. For example, a database might
place its tables, logs, and configuration on separate volumes. To
restore this database from a previous point in time, it makes sense
to restore the logs, tables, and configuration together from the
exact same point in time.

Use the ``policy.json`` file to grant permissions for these actions
to limit roles.


List consistency groups
~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v2/{tenant_id}/consistencygroups

Lists consistency groups.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - sort_key: sort_key
   - sort_dir: sort_dir
   - limit: limit
   - marker: marker


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - id: id
   - name: name

Response Example
----------------

.. literalinclude:: ./samples/consistency-groups-list-response.json
   :language: javascript


Create consistency group
~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v2/{tenant_id}/consistencygroups

Creates a consistency group.

Normal response codes: 202,


Request
-------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - description: description_6
   - availability_zone: availability_zone
   - volume_types: volume_types_2
   - name: name_15

Request Example
---------------

.. literalinclude:: ./samples/consistency-group-create-request.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

   - status: status_1
   - description: description_11
   - availability_zone: availability_zone
   - created_at: created_at
   - volume_types: volume_types
   - name: name_15
   - id: consistencygroup_id_1

Response Example
----------------

.. literalinclude:: ./samples/consistency-group-create-response.json
   :language: javascript

Show consistency group details
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v2/{tenant_id}/consistencygroups/{consistencygroup_id}

Shows details for a consistency group.

Normal response codes: 200
Error response codes:

Request
-------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - consistencygroup_id: consistencygroup_id

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - status: status_1
   - description: description
   - availability_zone: availability_zone
   - created_at: created_at
   - volume_types: volume_types
   - id: id
   - name: name

Response Example
----------------

.. literalinclude:: ./samples/consistency-group-show-response.json
   :language: javascript


Create consistency group from source
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v2/{tenant_id}/consistencygroups/create_from_src

Creates a consistency group from source.

Normal response codes: 202,


Request
-------

.. rest_parameters:: parameters.yaml

   - status: status_1
   - user_id: user_id
   - description: description
   - cgsnapshot_id: cgsnapshot_id
   - source_cgid: source_cgid
   - project_id: project_id
   - name: name
   - tenant_id: tenant_id

Request Example
---------------

.. literalinclude:: ./samples/consistency-group-create-from-src-request.json
   :language: javascript


Delete consistency group
~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v2/{tenant_id}/consistencygroups/{consistencygroup_id}/delete

Deletes a consistency group.

Normal response codes: 202,


Request
-------

.. rest_parameters:: parameters.yaml

   - force: force
   - tenant_id: tenant_id
   - consistencygroup_id: consistencygroup_id

Request Example
---------------

.. literalinclude:: ./samples/consistency-group-delete-request.json
   :language: javascript


List consistency groups with details
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v2/{tenant_id}/consistencygroups/detail

Lists consistency groups with details.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - sort_key: sort_key
   - sort_dir: sort_dir
   - limit: limit
   - marker: marker


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - status: status_1
   - description: description
   - availability_zone: availability_zone
   - created_at: created_at
   - volume_types: volume_types
   - id: id
   - name: name

Response Example
----------------

.. literalinclude:: ./samples/consistency-groups-list-detailed-response.json
   :language: javascript


Update consistency group
~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  PUT /v2/{tenant_id}/consistencygroups/{consistencygroup_id}/update

Updates a consistency group.

Normal response codes: 202,


Request
-------

.. rest_parameters:: parameters.yaml

   - remove_volumes: remove_volumes
   - description: description
   - add_volumes: add_volumes
   - name: name
   - tenant_id: tenant_id
   - consistencygroup_id: consistencygroup_id

Request Example
---------------

.. literalinclude:: ./samples/consistency-group-update-request.json
   :language: javascript
