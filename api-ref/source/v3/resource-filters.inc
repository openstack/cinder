.. -*- rst -*-

Resource Filters
================

Lists all resource filters, available since
microversion 3.33.


List resource filters
~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/resource_filters

List filters.

Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - resource: resource

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - filters: resource_filters
   - resource: resource_1

Response Example
----------------

.. literalinclude:: ./samples/resource-filters-list-response.json
   :language: javascript
