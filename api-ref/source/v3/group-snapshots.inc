.. -*- rst -*-

Group snapshots
===============

Lists all, lists all with details, shows details for, creates, and
deletes group snapshots.


Delete group snapshot
~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  DELETE /v3/{project_id}/group_snapshots/{group_snapshot_id}

Deletes a group snapshot.

Normal response codes: 202
Error response codes: badRequest(400), itemNotFound(404)


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - group_snapshot_id: group_snapshot_id


Show group snapshot details
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/group_snapshots/{group_snapshot_id}

Shows details for a group snapshot.


Normal response codes: 200
Error response codes: badRequest(400), itemNotFound(404)


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - group_snapshot_id: group_snapshot_id


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - status: status_7
   - description: description
   - created_at: created_at
   - group_id: group_id
   - id: id
   - name: name

Response Example
----------------

.. literalinclude:: ./samples/group-snapshots-show-response.json
   :language: javascript


List group snapshots with details
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/group_snapshots/detail

Lists all group snapshots with details, since v3.31 if non-admin
users specify invalid filters in the url, API will return bad request.


Normal response codes: 200
Error response codes: badRequest(400)

Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - sort_key: sort_key_group_snapshot
   - sort_dir: sort_dir_group_snapshot
   - limit: limit_group_snapshot
   - offset: offset_group_snapshot
   - marker: marker_group_snapshot


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - status: status_7
   - description: description
   - created_at: created_at
   - group_id: group_id
   - id: id
   - name: name

Response Example
----------------

.. literalinclude:: ./samples/group-snapshots-list-detailed-response.json
   :language: javascript

List group snapshots
~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/group_snapshots

Lists all group snapshots, since v3.31 if non-admin users
specify invalid filters in the url, API will return bad request.


Normal response codes: 200
Error response codes: badRequest(400)


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - sort_key: sort_key_group_snapshot
   - sort_dir: sort_dir_group_snapshot
   - limit: limit_group_snapshot
   - offset: offset_group_snapshot
   - marker: marker_group_snapshot


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - id: id
   - name: name


Response Example
----------------

.. literalinclude:: ./samples/group-snapshots-list-response.json
   :language: javascript


Create group snapshot
~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/group_snapshots

Creates a group snapshot.

Normal response codes: 202
Error response codes: badRequest(400), itemNotFound(404)


Request
-------

.. rest_parameters:: parameters.yaml

   - name: name
   - description: description
   - group_id: group_id
   - project_id: project_id_path

Request Example
---------------

.. literalinclude:: ./samples/group-snapshots-create-request.json
   :language: javascript

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - status: status_7
   - description: description
   - created_at: created_at
   - group_id: group_id
   - id: id
   - name: name

Response Example
----------------

.. literalinclude:: ./samples/group-snapshots-create-response.json
   :language: javascript


Reset group snapshot status
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/group_snapshots/{group_snapshot_id}/action

Resets the status for a group snapshot. Specifies the ``reset_status`` action in the request body.

Normal response codes: 202
Error response codes: badRequest(400), itemNotFound(404)


Request
-------

.. rest_parameters:: parameters.yaml

   - reset_status: reset_status
   - status: status
   - project_id: project_id
   - group_snapshot_id: group_snapshot_id

Request Example
---------------

.. literalinclude:: ./samples/group-snapshot-reset-status-request.json
   :language: javascript
