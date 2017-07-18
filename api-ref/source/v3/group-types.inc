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

   - group_type: group_type
   - group_type_id: group_type_id
   - project_id: project_id_path

Request Example
---------------

.. literalinclude:: ./samples/group-type-update-request.json
   :language: javascript


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - is_public: is_public
   - group_specs: group_specs
   - description: description
   - group_type: group_type
   - name: name

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

   - group_type_id: group_type_id
   - project_id: project_id_path


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - is_public: is_public
   - group_specs: group_specs
   - description: description
   - group_type: group_type
   - name: name


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
Error response codes:


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

   - group_types: group_types
   - group_specs: group_specs
   - name: name
   - group_type: group_type

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

   - group_type: group_type
   - project_id: project_id_path

Request Example
---------------

.. literalinclude:: ./samples/group-type-create-request.json
   :language: javascript


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - is_public: is_public
   - group_specs: group_specs
   - description: description
   - group_type: group_type
   - name: name


Response Example
----------------

.. literalinclude:: ./samples/group-type-show-response.json
   :language: javascript
