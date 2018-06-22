.. -*- rst -*-

Quality of service (QoS) specifications (qos-specs)
===================================================

Administrators only, depending on policy settings.

Creates, lists, shows details for, associates, disassociates, sets
keys, unsets keys, and deletes quality of service (QoS)
specifications.


Disassociate a QoS specification from all associations
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/qos-specs/{qos_id}/disassociate_all

Disassociates a QoS specification from all associations.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - qos_id: qos_id


Unset keys in a QoS specification
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  PUT /v3/{project_id}/qos-specs/{qos_id}/delete_keys

Unsets keys in a QoS specification.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - qos_id: qos_id
   - keys: keys

Request Example
---------------

.. literalinclude:: ./samples/qos-unset-request.json
   :language: javascript


Get all associations for a QoS specification
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/qos-specs/{qos_id}/associations

Lists all associations for a QoS specification.


Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - qos_id: qos_id


Response
--------

.. rest_parameters:: parameters.yaml

   - qos_specs: qos_specs
   - specs: specs
   - consumer: consumer_1
   - name: name_4
   - id: id_3
   - links: links_2


Response Example
----------------

.. literalinclude:: ./samples/qos-show-response.json
   :language: javascript


Associate QoS specification with a volume type
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/qos-specs/{qos_id}/associate

Associates a QoS specification with a volume type.


Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - qos_id: qos_id
   - vol_type_id: vol_type_id_query


Disassociate QoS specification from a volume type
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/qos-specs/{qos_id}/disassociate

Disassociates a QoS specification from a volume type.


Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - qos_id: qos_id
   - vol_type_id: vol_type_id_query


Show a QoS specification details
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/qos-specs/{qos_id}

Shows details for a QoS specification.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200

.. rest_status_code:: error ../status.yaml

   - 400
   - 401
   - 403
   - 404
   - 405
   - 413
   - 503


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - qos_id: qos_id


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - qos_specs: qos_specs
   - specs: specs
   - consumer: consumer
   - name: name_4
   - id: id_3
   - links: links_2


Response Example
----------------

.. literalinclude:: ./samples/qos-show-response.json
   :language: javascript


Set keys in a QoS specification
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  PUT /v3/{project_id}/qos-specs/{qos_id}

Sets keys in a QoS specification.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - qos_id: qos_id
   - qos_specs: qos_specs

Request Example
---------------

.. literalinclude:: ./samples/qos-update-request.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

   - qos_specs: qos_specs


Response Example
----------------

.. literalinclude:: ./samples/qos-update-response.json
   :language: javascript


Delete a QoS specification
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  DELETE /v3/{project_id}/qos-specs/{qos_id}

Deletes a QoS specification.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - qos_id: qos_id
   - force: force_3


Create a QoS specification
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/qos-specs

Creates a QoS specification.

Specify one or more key and value pairs in the request body.


Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - qos_specs: qos_specs
   - name: name_4

Request Example
---------------

.. literalinclude:: ./samples/qos-create-request.json
   :language: javascript


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - qos_specs: qos_specs
   - name: name_4
   - links: links_2
   - id: id_3
   - consumer: consumer
   - specs: specs


List QoS Specifications
~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/qos-specs

Lists quality of service (QoS) specifications.


Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200

.. rest_status_code:: error ../status.yaml

   - 300


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - sort: sort
   - limit: limit
   - marker: marker


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - qos_specs: qos_specs
   - specs: specs
   - consumer: consumer
   - id: id_3
   - name: name_4


Response Example
----------------

.. literalinclude:: ./samples/qos-list-response.json
   :language: javascript
