.. -*- rst -*-

Consistency group snapshots (DEPRECATED)
========================================

Lists all, lists all with details, shows details for, creates, and
deletes consistency group snapshots.


Delete a consistency group snapshot
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  DELETE /v3/{project_id}/cgsnapshots/{cgsnapshot_id}

Deletes a consistency group snapshot.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - cgsnapshot_id: cgsnapshot_id_path


Show consistency group snapshot detail
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/cgsnapshots/{cgsnapshot_id}

Shows details for a consistency group snapshot.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - cgsnapshot_id: cgsnapshot_id_path


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - cgsnapshot: cgsnapshot
   - status: status
   - description: description_cg_snapshot_true
   - created_at: created_at
   - consistencygroup_id: consistencygroup_id_required
   - id: id
   - name: name_cgsnap

Response Example
----------------

.. literalinclude:: ./samples/cgsnapshots-show-response.json
   :language: javascript


List all consistency group snapshots with details
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/cgsnapshots/detail

Lists all consistency group snapshots with details.

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

   - cgsnapshots: cgsnapshots
   - status: status
   - description: description_cg_snapshot_true
   - created_at: created_at
   - consistencygroup_id: consistencygroup_id_required
   - id: id
   - name: name_cgsnap

Response Example
----------------

.. literalinclude:: ./samples/cgsnapshots-list-detailed-response.json
   :language: javascript

List all consistency group snapshots
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/cgsnapshots

Lists all consistency group snapshots.


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

   - cgsnapshots: cgsnapshots
   - id: id
   - name: name_cgsnap



Response Example
----------------

.. literalinclude:: ./samples/cgsnapshots-list-response.json
   :language: javascript




Create a consistency group snapshot
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/cgsnapshots

Creates a consistency group snapshot.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202

Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - cgsnapshot: cgsnapshot
   - name: name_snap
   - consistencygroup_id: consistencygroup_id_required
   - description: description_cg_snapshot_false

Request Example
---------------

.. literalinclude:: ./samples/cgsnapshots-create-request.json
   :language: javascript

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - status: status
   - description: description_cg_snapshot_true
   - created_at: created_at
   - consistencygroup_id: consistencygroup_id_required
   - id: id
   - name: name_cgsnap
