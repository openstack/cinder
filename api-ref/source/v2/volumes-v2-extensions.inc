.. -*- rst -*-

API extensions (extensions)
===========================




List API extensions
~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v2/{tenant_id}/extensions

Lists Block Storage API extensions.


Normal response codes: 200, 300


Request
-------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - updated: updated
   - description: description
   - links: links
   - namespace: namespace
   - alias: alias
   - name: name




Response Example
----------------

.. literalinclude:: ./samples/extensions-list-response.json
   :language: javascript



