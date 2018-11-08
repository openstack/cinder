.. -*- rst -*-

Resource Filters
================

Lists all resource filters, available since
microversion 3.33.


List resource filters
~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/resource_filters

List filters.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - resource: resource

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - resource_filters: resource_filters_coll
   - filters: resource_filters
   - resource: resource_fil

Response Example
----------------

.. literalinclude:: ./samples/resource-filters-list-response.json
   :language: javascript
