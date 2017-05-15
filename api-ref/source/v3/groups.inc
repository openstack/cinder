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

Lists groups, since v3.31 if non-admin users specify
invalid filters in the url, API will return bad request.


Normal response codes: 200
Error response codes: badRequest(400)


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - sort_key: sort_key
   - sort_dir: sort_dir
   - limit: limit
   - offset: offset
   - marker: marker


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - id: id
   - name: name

Response Example
----------------

.. literalinclude:: ./samples/groups-list-response.json
   :language: javascript


Create group
~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/groups

Creates a group.

Normal response codes: 202
Error response codes: badRequest(400), itemNotFound(404)


Request
-------

.. rest_parameters:: parameters.yaml

   - description: description
   - availability_zone: availability_zone
   - group_type: group_type
   - volume_types: volume_types
   - name: name
   - project_id: project_id_path

Request Example
---------------

.. literalinclude:: ./samples/group-create-request.json
   :language: javascript


Show group details
~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/groups/{group_id}

Shows details for a group.

Normal response codes: 200
Error response codes: itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - group_id: group_id

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - status: status_8
   - description: description
   - availability_zone: availability_zone
   - created_at: created_at
   - group_type: group_type
   - volume_types: volume_types
   - id: id
   - name: name

Response Example
----------------

.. literalinclude:: ./samples/group-show-response.json
   :language: javascript


Create group from source
~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/groups/action

Creates a group from source.

Normal response codes: 202
Error response codes: badRequest(400), itemNotFound(404)


Request
-------

.. rest_parameters:: parameters.yaml

   - description: description
   - group_snapshot_id: group_snapshot_id
   - source_group_id: source_group_id
   - name: name
   - project_id: project_id_path

Request Example
---------------

.. literalinclude:: ./samples/group-create-from-src-request.json
   :language: javascript


Delete group
~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/groups/{group_id}/action

Deletes a group.

Normal response codes: 202
Error response codes: badRequest(400), itemNotFound(404)


Request
-------

.. rest_parameters:: parameters.yaml

   - delete-volumes: delete-volumes
   - project_id: project_id_path
   - group_id: group_id

Request Example
---------------

.. literalinclude:: ./samples/group-delete-request.json
   :language: javascript


List groups with details
~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/groups/detail

Lists groups with details, since v3.31 if non-admin
users specify invalid filters in the url, API will return bad request.


Normal response codes: 200
Error response codes: badRequest(400)


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - sort_key: sort_key
   - sort_dir: sort_dir
   - limit: limit
   - offset: offset
   - marker: marker


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - status: status_8
   - description: description
   - availability_zone: availability_zone
   - created_at: created_at
   - group_type: group_type
   - volume_types: volume_types
   - id: id
   - name: name

Response Example
----------------

.. literalinclude:: ./samples/groups-list-detailed-response.json
   :language: javascript


Update group
~~~~~~~~~~~~

.. rest_method::  PUT /v3/{project_id}/groups/{group_id}

Updates a group.

Normal response codes: 202
Error response codes: badRequest(400), itemNotFound(404)


Request
-------

.. rest_parameters:: parameters.yaml

   - remove_volumes: remove_volumes
   - description: description
   - add_volumes: add_volumes
   - name: name
   - project_id: project_id_path
   - group_id: group_id

Request Example
---------------

.. literalinclude:: ./samples/group-update-request.json
   :language: javascript


Reset group status
~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/groups/{group_id}/action

Resets the status for a group. Specify the ``reset_status`` action in the request body.

Normal response codes: 202
Error response codes: badRequest(400), itemNotFound(404)


Request
-------

.. rest_parameters:: parameters.yaml

   - reset_status: reset_status
   - status: status
   - project_id: project_id
   - group_id: group_id

Request Example
---------------

.. literalinclude:: ./samples/group-reset-status-request.json
   :language: javascript
