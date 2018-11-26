.. -*- rst -*-

API version details
===================


Show API v3 details
~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/

Shows details for Block Storage API v3.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200

.. rest_status_code:: error ../status.yaml

   - 403


Request
-------

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - status: version_status
   - updated: version_updated
   - links: links_res
   - min_version: version_min
   - version: version_max
   - media-types: media_types
   - id: version_id

Response Example
----------------

.. literalinclude:: ./samples/versions/version-show-response.json
   :language: javascript


