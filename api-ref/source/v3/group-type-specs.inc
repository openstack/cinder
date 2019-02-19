.. -*- rst -*-

Group type specs
================

Create or update group specs for a group type
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/group_types/{group_type_id}/group_specs

Create group specs for a group type, if the specification key already exists in
group specs, this API will update the specification as well.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202

.. rest_status_code:: error ../status.yaml

   - 400
   - 403
   - 404


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - group_type_id: group_type_id_path
   - group_specs: group_specs_req

Request Example
---------------

.. literalinclude:: ./samples/group-type-specs-create-request.json
   :language: javascript



Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - group_specs: group_specs_req


Response Example
----------------

.. literalinclude:: ./samples/group-type-specs-create-response.json
   :language: javascript


List group specs for a group type
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/group_types/{group_type_id}/group_specs

List all the group specs for a group type,


Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200

.. rest_status_code:: error ../status.yaml

   - 403
   - 404


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - group_type_id: group_type_id_path


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - group_specs: group_specs_req


Response Example
----------------

.. literalinclude:: ./samples/group-type-specs-list-response.json
   :language: javascript


Show one specific group spec for a group type
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::
   GET /v3/{project_id}/group_types/{group_type_id}/group_specs/{spec_id}

Show a group spec for a group type,


Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200

.. rest_status_code:: error ../status.yaml

   - 403
   - 404


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - group_type_id: group_type_id_path
   - spec_id: spec_id


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - spec: spec_value

Response Example
----------------

.. literalinclude:: ./samples/group-type-specs-show-response.json
   :language: javascript


Update one specific group spec for a group type
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::
   PUT /v3/{project_id}/group_types/{group_type_id}/group_specs/{spec_id}

Update a group spec for a group type,


Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200

.. rest_status_code:: error ../status.yaml

   - 403
   - 404


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - group_type_id: group_type_id_path
   - spec_id: spec_id
   - spec: spec_value

Request Example
---------------

.. literalinclude:: ./samples/group-type-specs-update-request.json
   :language: javascript

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - spec: spec_value

Response Example
----------------

.. literalinclude:: ./samples/group-type-specs-update-response.json
   :language: javascript


Delete one specific group spec for a group type
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::
   DELETE /v3/{project_id}/group_types/{group_type_id}/group_specs/{spec_id}

Delete a group spec for a group type,


Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202

.. rest_status_code:: error ../status.yaml

   - 403
   - 404


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - group_type_id: group_type_id_path
   - spec_id: spec_id
