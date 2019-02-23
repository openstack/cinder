.. -*- rst -*-

Consistency groups (DEPRECATED)
===============================

Consistency groups enable you to create snapshots at the exact same
point in time from multiple volumes. For example, a database might
place its tables, logs, and configuration on separate volumes. To
restore this database from a previous point in time, it makes sense
to restore the logs, tables, and configuration together from the
exact same point in time.

Use the ``policy.json`` file to grant permissions for these actions
to limit roles.


List project's consistency groups
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/consistencygroups

Lists consistency groups.


Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - all_tenants: all-tenants
   - sort: sort
   - limit: limit
   - marker: marker


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - consistencygroups: consistencygroups
   - id: id
   - name: name

Response Example
----------------

.. literalinclude:: ./samples/consistency-groups-list-response.json
   :language: javascript


Create a consistency group
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/consistencygroups

Creates a consistency group.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - consistencygroup: consistencygroup
   - description: description_consis
   - availability_zone: availability_zone
   - volume_types: volume_types_commas
   - name: name_consis

Request Example
---------------

.. literalinclude:: ./samples/consistency-group-create-request.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

   - consistencygroup: consistencygroup
   - status: status_consis
   - description: description_cg
   - availability_zone: availability_zone
   - created_at: created_at
   - volume_types: volume_types
   - name: name_consis
   - id: consistencygroup_id

Response Example
----------------

.. literalinclude:: ./samples/consistency-group-create-response.json
   :language: javascript

Show a consistency group's details
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/consistencygroups/{consistencygroup_id}

Shows details for a consistency group.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200

Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - consistencygroup_id: consistencygroup_id_path

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - status: status_consis
   - description: description_cg
   - availability_zone: availability_zone
   - created_at: created_at
   - volume_types: volume_types
   - id: id
   - name: name

Response Example
----------------

.. literalinclude:: ./samples/consistency-group-show-response.json
   :language: javascript


Create a consistency group from source
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/consistencygroups/create_from_src

Creates a consistency group from source.


Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - consistencygroup-from-src: consistencygroup-from-src
   - status: status_consis
   - user_id: user_id
   - description: description_consis
   - cgsnapshot_id: cgsnapshot_id
   - source_cgid: source_cgid
   - project_id: project_id
   - name: name

Request Example
---------------

.. literalinclude:: ./samples/consistency-group-create-from-src-request.json
   :language: javascript


Delete a consistency group
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::
   POST /v3/{project_id}/consistencygroups/{consistencygroup_id}/delete

Deletes a consistency group.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - consistencygroup_id: consistencygroup_id_path
   - consistencygroup: consistencygroup
   - force: force

Request Example
---------------

.. literalinclude:: ./samples/consistency-group-delete-request.json
   :language: javascript


List consistency groups and details
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/consistencygroups/detail

Lists consistency groups with details.


Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - all_tenants: all-tenants
   - sort: sort
   - limit: limit
   - marker: marker


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - consistencygroups: consistencygroups
   - status: status_consis
   - description: description_cg
   - availability_zone: availability_zone
   - created_at: created_at
   - volume_types: volume_types
   - id: id
   - name: name

Response Example
----------------

.. literalinclude:: ./samples/consistency-groups-list-detailed-response.json
   :language: javascript


Update a consistency group
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::
   PUT /v3/{project_id}/consistencygroups/{consistencygroup_id}/update

Updates a consistency group.


Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - consistencygroup_id: consistencygroup_id_path
   - consistencygroup: consistencygroup
   - remove_volumes: remove_volumes
   - description: description_consis
   - add_volumes: add_volumes
   - name: name

Request Example
---------------

.. literalinclude:: ./samples/consistency-group-update-request.json
   :language: javascript
