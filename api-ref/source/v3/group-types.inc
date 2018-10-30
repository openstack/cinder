.. -*- rst -*-

Group types
===========

To create a generic volume group, you must specify a group type.


Update group type
~~~~~~~~~~~~~~~~~

.. rest_method::  PUT /v3/{project_id}/group_types/{group_type_id}

Updates a group type.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200

.. rest_status_code:: error ../status.yaml

   - 400
   - 403
   - 404
   - 409
   - 500


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - group_type_id: group_type_id_path
   - group_type: group_type
   - name: name_group
   - description: description_group_type_optional
   - is_public: is_public_group_type_optional

Request Example
---------------

.. literalinclude:: ./samples/group-type-update-request.json
   :language: javascript


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - group_type: group_type
   - id: group_type_id
   - is_public: is_public_group_type_required
   - group_specs: group_specs
   - description: description_group_type_required
   - name: name_group_type

Response Example
----------------

.. literalinclude:: ./samples/group-type-show-response.json
   :language: javascript


Show group type details
~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/group_types/{group_type_id}

Shows details for a group type.

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
   - group_type_id: group_type_id_path


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - group_type: group_type
   - id: group_type_id
   - name: name_group_type
   - is_public: is_public_group_type_required
   - group_specs: group_specs
   - description: description_group_type_required


Response Example
----------------

.. literalinclude:: ./samples/group-type-show-response.json
   :language: javascript


Show default group type details
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/group_types/default

Shows details for the default group type if configured.


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


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - group_type: group_type
   - id: group_type_id
   - name: name_group_type
   - is_public: is_public_group_type_required
   - group_specs: group_specs
   - description: description_group_type_required


Response Example
----------------

.. literalinclude:: ./samples/group-type-default-response.json
   :language: javascript


Delete group type
~~~~~~~~~~~~~~~~~

.. rest_method::  DELETE /v3/{project_id}/group_types/{group_type_id}

Deletes a group type.

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

   - group_type_id: group_type_id_path
   - project_id: project_id_path


List group types
~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/group_types

Lists group types.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200


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
   - id: group_type_id
   - group_specs: group_specs
   - name: name_group_type
   - is_public: is_public_group_type_required
   - description: description_group_type_required

Response Example
----------------

.. literalinclude:: ./samples/group-types-list-response.json
   :language: javascript


Create group type
~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/group_types

Creates a group type.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202

.. rest_status_code:: error ../status.yaml

   - 400
   - 403
   - 404
   - 409


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - group_type: group_type
   - name: name_group_type
   - description: description_group_type_optional
   - is_public: is_public_group_type_optional
   - group_specs: group_specs

Request Example
---------------

.. literalinclude:: ./samples/group-type-create-request.json
   :language: javascript


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - group_type: group_type
   - id: group_type_id
   - is_public: is_public_group_type_required
   - group_specs: group_specs
   - description: description_group_type_required
   - name: name_group_type


Response Example
----------------

.. literalinclude:: ./samples/group-type-show-response.json
   :language: javascript
