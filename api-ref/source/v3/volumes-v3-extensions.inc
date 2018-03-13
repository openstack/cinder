.. -*- rst -*-

API extensions (extensions)
===========================




List Known API extensions
~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/extensions

Lists Block Storage API extensions.

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


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - updated: updated
   - description: description_7
   - links: links
   - namespace: namespace
   - alias: alias
   - name: name




Response Example
----------------

.. literalinclude:: ./samples/extensions-list-response.json
   :language: javascript



