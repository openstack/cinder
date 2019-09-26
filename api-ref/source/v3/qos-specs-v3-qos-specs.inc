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

.. literalinclude:: ./samples/qos/qos-unset-request.json
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

   - qos_associations: qos_associations
   - type: qos_association_type
   - id: qos_association_id
   - name: qos_association_name


Response Example
----------------

.. literalinclude:: ./samples/qos/qos_show_response.json
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
   - name: name_qos_spec
   - id: id_qos_spec
   - links: links_qos


Response Example
----------------

.. literalinclude:: ./samples/qos/qos-show-response.json
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

.. literalinclude:: ./samples/qos/qos-update-request.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

   - qos_specs: qos_specs


Response Example
----------------

.. literalinclude:: ./samples/qos/qos-update-response.json
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
   - force: force_del_qos


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
   - name: name_qos_spec

Request Example
---------------

.. literalinclude:: ./samples/qos/qos-create-request.json
   :language: javascript


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - qos_specs: qos_specs
   - name: name_qos_spec
   - links: links_qos
   - id: id_qos_spec
   - consumer: consumer
   - specs: specs


Response Example
----------------

.. literalinclude:: ./samples/qos/qos-create-response.json
   :language: javascript


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
   - id: id_qos_spec
   - name: name_qos_spec


Response Example
----------------

.. literalinclude:: ./samples/qos/qos-list-response.json
   :language: javascript
