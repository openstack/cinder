.. -*- rst -*-

Consistency group snapshots
===========================

Lists all, lists all with details, shows details for, creates, and
deletes consistency group snapshots.


Delete a consistency group snapshot
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  DELETE /v3/{project_id}/cgsnapshots/{cgsnapshot_id}

Deletes a consistency group snapshot.

Normal response codes: 202


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - cgsnapshot_id: cgsnapshot_id


Show consistency group snapshot detail
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/cgsnapshots/{cgsnapshot_id}

Shows details for a consistency group snapshot.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - cgsnapshot_id: cgsnapshot_id


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - status: status
   - description: description
   - created_at: created_at
   - consistencygroup_id: consistencygroup_id
   - id: id
   - name: name

Response Example
----------------

.. literalinclude:: ./samples/cgsnapshots-show-response.json
   :language: javascript


List all consistency group snapshots with details
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/cgsnapshots/detail

Lists all consistency group snapshots with details.


Normal response codes: 200
Error response codes:

Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - status: status
   - description: description
   - created_at: created_at
   - consistencygroup_id: consistencygroup_id
   - id: id
   - name: name

Response Example
----------------

.. literalinclude:: ./samples/cgsnapshots-list-detailed-response.json
   :language: javascript

List all consistency group snapshots
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/cgsnapshots

Lists all consistency group snapshots.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - id: id
   - name: name



Response Example
----------------

.. literalinclude:: ./samples/cgsnapshots-list-response.json
   :language: javascript




Create a consistency group snapshot
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/cgsnapshots

Creates a consistency group snapshot.

Normal response codes: 202

Request
-------

.. rest_parameters:: parameters.yaml

   - name: name
   - project_id: project_id_path

Request Example
---------------

.. literalinclude:: ./samples/cgsnapshots-create-request.json
   :language: javascript

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - status: status
   - description: description
   - created_at: created_at
   - consistencygroup_id: consistencygroup_id
   - id: id
   - name: name
