.. -*- rst -*-

Quality of service (QoS) specifications (qos-specs)
===================================================

Administrators only.

Creates, lists, shows details for, associates, disassociates, sets
keys, unsets keys, and deletes quality of service (QoS)
specifications.


Disassociate QoS specification from all associations
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v2/{tenant_id}/qos-specs/{qos_id}/disassociate_all

Disassociates a QoS specification from all associations.

Normal response codes: 202,


Request
-------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - qos_id: qos_id


Unset keys in QoS specification
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  PUT /v2/{tenant_id}/qos-specs/{qos_id}/delete_keys

Unsets keys in a QoS specification.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - keys: keys
   - tenant_id: tenant_id
   - qos_id: qos_id

Request Example
---------------

.. literalinclude:: ./samples/qos-unset-request.json
   :language: javascript



Response Example
----------------

.. literalinclude:: ./samples/qos-unset-response.json
   :language: javascript


Get all associations for QoS specification
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v2/{tenant_id}/qos-specs/{qos_id}/associations

Lists all associations for a QoS specification.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - qos_id: qos_id


Response Example
----------------

.. literalinclude:: ./samples/qos-show-response.json
   :language: javascript


Associate QoS specification with volume type
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v2/{tenant_id}/qos-specs/{qos_id}/associate

Associates a QoS specification with a volume type.

Normal response codes: 202,


Request
-------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - qos_id: qos_id
   - vol_type_id: vol_type_id


Disassociate QoS specification from volume type
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v2/{tenant_id}/qos-specs/{qos_id}/disassociate

Disassociates a QoS specification from a volume type.

Normal response codes: 202,


Request
-------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - qos_id: qos_id
   - vol_type_id: vol_type_id


Show QoS specification details
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v2/{tenant_id}/qos-specs/{qos_id}

Shows details for a QoS specification.


Normal response codes: 200
Error response codes: 413, 405, 404, 403, 401, 400, 503,


Request
-------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - qos_id: qos_id


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - name: name
   - links: links
   - id: id
   - qos_specs: qos_specs
   - consumer: consumer
   - specs: specs


Response Example
----------------

.. literalinclude:: ./samples/qos-show-response.json
   :language: javascript


Set keys in QoS specification
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  PUT /v2/{tenant_id}/qos-specs/{qos_id}

Sets keys in a QoS specification.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - qos_specs: qos_specs
   - specs: specs
   - tenant_id: tenant_id
   - qos_id: qos_id

Request Example
---------------

.. literalinclude:: ./samples/qos-update-request.json
   :language: javascript


Response Example
----------------

.. literalinclude:: ./samples/qos-update-response.json
   :language: javascript


Delete QoS specification
~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  DELETE /v2/{tenant_id}/qos-specs/{qos_id}

Deletes a QoS specification.

Normal response codes: 202,


Request
-------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - qos_id: qos_id
   - force: force


Create QoS specification
~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v2/{tenant_id}/qos-specs

Creates a QoS specification.

Specify one or more key and value pairs in the request body.

Normal response codes: 202,


Request
-------

.. rest_parameters:: parameters.yaml

   - qos_specs: qos_specs
   - consumer: consumer
   - name: name
   - tenant_id: tenant_id

Request Example
---------------

.. literalinclude:: ./samples/qos-create-request.json
   :language: javascript



Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - name: name
   - links: links
   - id: id
   - qos_specs: qos_specs
   - consumer: consumer
   - specs: specs


List QoS specs
~~~~~~~~~~~~~~

.. rest_method::  GET /v2/{tenant_id}/qos-specs

Lists quality of service (QoS) specifications.


Normal response codes: 200, 300,


Request
-------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - sort_key: sort_key
   - sort_dir: sort_dir
   - limit: limit
   - marker: marker


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - specs: specs
   - qos_specs: qos_specs
   - consumer: consumer
   - id: id
   - name: name


Response Example
----------------

.. literalinclude:: ./samples/qos-list-response.json
   :language: javascript
