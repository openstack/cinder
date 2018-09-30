.. -*- rst -*-

API extensions (extensions)
===========================




List API extensions
~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v2/{project_id}/extensions

Lists Block Storage API extensions.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - updated: updated_at
   - description: description
   - links: links
   - namespace: namespace
   - alias: alias
   - name: name




Response Example
----------------

.. literalinclude:: ./samples/extensions-list-response.json
   :language: javascript



