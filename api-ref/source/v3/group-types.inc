.. -*- rst -*-

Group types
===========


Update group type
~~~~~~~~~~~~~~~~~

.. rest_method::  PUT /v3/{project_id}/group_types/{group_type_id}

Updates a group type.

To create a generic volume group, you must specify a group type.

Normal response codes: 200

Error response codes: badRequest(400), forbidden(403), itemNotFound(404),
conflict(409), computeFault(500)


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - group_type_id: group_type_id
   - group_type: group_type
   - name: name_16
   - description: description_12

Request Example
---------------

.. literalinclude:: ./samples/group-type-update-request.json
   :language: javascript


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - group_type: group_type
   - id: group_type_id_2
   - is_public: is_public_1
   - group_specs: group_specs
   - description: description_12
   - name: name_16

Response Example
----------------

.. literalinclude:: ./samples/group-type-show-response.json
   :language: javascript


Show group type details
~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/group_types/{group_type_id}

Shows details for a group type.


Normal response codes: 200

Error response codes: itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - group_type_id: group_type_id


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - group_type: group_type
   - id: group_type_id_2
   - name: name_16
   - is_public: is_public_1
   - group_specs: group_specs
   - description: description_12


Response Example
----------------

.. literalinclude:: ./samples/group-type-show-response.json
   :language: javascript


Delete group type
~~~~~~~~~~~~~~~~~

.. rest_method::  DELETE /v3/{project_id}/group_types/{group_type_id}

Deletes a group type.

Normal response codes: 202

Error response codes: badRequest(400), forbidden(403), itemNotFound(404)


Request
-------

.. rest_parameters:: parameters.yaml

   - group_type_id: group_type_id
   - project_id: project_id_path


List group types
~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/group_types

Lists group types.


Normal response codes: 200


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - sort: sort
   - limit: limit
   - offset: offset
   - marker: marker


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - group_types: group_types
   - id: group_type_id_2
   - group_specs: group_specs_2
   - name: name_16

Response Example
----------------

.. literalinclude:: ./samples/group-types-list-response.json
   :language: javascript


Create group type
~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/group_types

Creates a group type.

To create a generic volume group, you must specify a group type.


Normal response codes: 202

Error response codes: badRequest(400), forbidden(403), itemNotFound(404),
conflict(409)


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - group_type: group_type
   - name: name_16
   - description: description_12
   - group_specs: group_specs

Request Example
---------------

.. literalinclude:: ./samples/group-type-create-request.json
   :language: javascript


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - group_type: group_type
   - id: group_type_id_2
   - is_public: is_public_1
   - group_specs: group_specs
   - description: description_12
   - name: name_16


Response Example
----------------

.. literalinclude:: ./samples/group-type-show-response.json
   :language: javascript
