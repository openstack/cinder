.. -*- rst -*-

Volume types
============

Lists, creates, updates, shows information for, and deletes volume
types.


List volume types (v1)
~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v1/{tenant_id}/types

Lists volume types.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id

Response Example
----------------

.. literalinclude:: ./samples/volume-types-list-response.json
   :language: javascript


Create volume type (v1)
~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v1/{tenant_id}/types

Creates a volume type.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - extra_specs: extra_specs
   - name: name
   - volume_type: volume_type
   - tenant_id: tenant_id

Request Example
---------------

.. literalinclude:: ./samples/volume-type-create-request.json
   :language: javascript

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - extra_specs: extra_specs
   - name: name
   - volume_type: volume_type

Response Example
----------------

.. literalinclude:: ./samples/volume-type-show-response.json
   :language: javascript


Update volume type (v1)
~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  PUT /v1/{tenant_id}/types/{volume_type_id}

Updates a volume type.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - extra_specs: extra_specs
   - name: name
   - volume_type: volume_type
   - tenant_id: tenant_id
   - volume_type_id: volume_type_id

Request Example
---------------

.. literalinclude:: ./samples/volume-type-create-request.json
   :language: javascript



Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - extra_specs: extra_specs
   - name: name
   - volume_type: volume_type

Response Example
----------------

.. literalinclude:: ./samples/volume-type-show-response.json
   :language: javascript


Update extra specs for a volume type (v1)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  PUT /v1/{tenant_id}/types/{volume_type_id}

Updates the extra specifications for a volume type.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - extra_specs: extra_specs
   - name: name
   - volume_type: volume_type
   - tenant_id: tenant_id
   - volume_type_id: volume_type_id

Request Example
---------------

.. literalinclude:: ./samples/volume-type-create-request.json
   :language: javascript


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - extra_specs: extra_specs
   - name: name
   - volume_type: volume_type

Response Example
----------------

.. literalinclude:: ./samples/volume-type-show-response.json
   :language: javascript


Show volume type details (v1)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v1/{tenant_id}/types/{volume_type_id}

Shows details for a volume type.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - volume_type_id: volume_type_id


Response Example
----------------

.. literalinclude:: ./samples/volume-type-show-response.json
   :language: javascript


Delete volume type (v1)
~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  DELETE /v1/{tenant_id}/types/{volume_type_id}

Deletes a volume type.

Normal response codes: 202


Request
-------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - volume_type_id: volume_type_id
