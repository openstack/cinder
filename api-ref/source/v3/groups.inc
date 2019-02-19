.. -*- rst -*-

Generic volume groups
=====================

Generic volume groups enable you to create a group of volumes and
manage them together.

How is generic volume groups different from consistency groups?
Currently consistency groups in cinder only support consistent group
snapshot. It cannot be extended easily to serve other purposes. A project
may want to put volumes used in the same application together in a group
so that it is easier to manage them together, and this group of volumes
may or may not support consistent group snapshot. Generic volume group
is introduced to solve this problem. By decoupling the tight relationship
between the group construct and the consistency concept, generic volume
groups can be extended to support other features in the future.


List groups
~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/groups

Lists groups. Since v3.31 if non-admin users specify
invalid filters in the url, API will return bad request.

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
   - limit: limit
   - offset: offset
   - marker: marker


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - groups: groups
   - id: id
   - name: group_name

Response Example
----------------

.. literalinclude:: ./samples/groups-list-response.json
   :language: javascript


Create group
~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/groups

Creates a group.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202

.. rest_status_code:: error ../status.yaml

   - 400
   - 404


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - group: group
   - description: description_group_false
   - availability_zone: availability_zone
   - group_type: group_type_id
   - volume_types: volume_types
   - name: group_name

Request Example
---------------

.. literalinclude:: ./samples/group-create-request.json
   :language: javascript

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - id: group_id_path
   - name: group_name

Response Example
----------------

.. literalinclude:: ./samples/group-create-response.json
   :language: javascript


Show group details
~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/groups/{group_id}

Shows details for a group.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200

.. rest_status_code:: error ../status.yaml

   - 404

Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - group_id: group_id_path
   - list_volume: list_volume

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - group: group
   - status: status_group
   - description: description_group_true
   - availability_zone: availability_zone
   - created_at: created_at
   - group_type: group_type_id
   - group_snapshot_id: group_snapshot_id
   - source_group_id: source_group_id
   - volume_types: volume_types
   - id: id
   - name: group_name
   - volumes: volume_ids
   - replication_status: group_replication_status
   - project_id: project_id_group

Response Example
----------------

.. literalinclude:: ./samples/group-show-response.json
   :language: javascript


Create group from source
~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/groups/action

Creates a group from source.


Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202

.. rest_status_code:: error ../status.yaml

   - 400
   - 404


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - create-from-src: create-from-src
   - description: description_group_false
   - group_snapshot_id: group_snapshot_id_req
   - source_group_id: source_group_id_req
   - name: group_name

Request Example
---------------

.. literalinclude:: ./samples/group-create-from-src-request.json
   :language: javascript

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - id: group_id_path
   - name: group_name

Response Example
----------------

.. literalinclude:: ./samples/group-create-from-src-response.json
   :language: javascript


Delete group
~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/groups/{group_id}/action

Deletes a group.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202

.. rest_status_code:: error ../status.yaml

   - 400
   - 404


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - group_id: group_id_path
   - delete: delete
   - delete-volumes: delete-volumes

Request Example
---------------

.. literalinclude:: ./samples/group-delete-request.json
   :language: javascript


List groups with details
~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/groups/detail

Lists groups with details, since v3.31 if non-admin
users specify invalid filters in the url, API will return bad request.


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
   - limit: limit
   - offset: offset
   - marker: marker
   - list_volume: list_volume


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - groups: groups
   - status: status_group
   - description: description_group_true
   - availability_zone: availability_zone
   - created_at: created_at
   - group_type: group_type_id
   - group_snapshot_id: group_snapshot_id
   - source_group_id: source_group_id
   - volume_types: volume_types
   - id: group_id_path
   - name: name
   - volumes: volume_ids
   - project_id: project_id_group

Response Example
----------------

.. literalinclude:: ./samples/groups-list-detailed-response.json
   :language: javascript


Update group
~~~~~~~~~~~~

.. rest_method::  PUT /v3/{project_id}/groups/{group_id}

Updates a group.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202

.. rest_status_code:: error ../status.yaml

   - 400
   - 404


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - group_id: group_id_path
   - group: group
   - remove_volumes: remove_volumes
   - description: description_group_false
   - add_volumes: add_volumes
   - name: group_name

Request Example
---------------

.. literalinclude:: ./samples/group-update-request.json
   :language: javascript


Reset group status
~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/groups/{group_id}/action

Resets the status for a group. Specify the ``reset_status`` action in the
request body.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202

.. rest_status_code:: error ../status.yaml

   - 400
   - 404


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - group_id: group_id_path
   - reset_status: reset_status
   - status: status

Request Example
---------------

.. literalinclude:: ./samples/group-reset-status-request.json
   :language: javascript
