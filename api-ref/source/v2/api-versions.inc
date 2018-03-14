.. -*- rst -*-

API versions
============

List Api Versions
~~~~~~~~~~~~~~~~~

.. rest_method:: GET /

Lists information for all Block Storage API versions.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200
   - 300

.. rest_status_code:: error ../status.yaml

   - 400
   - 401
   - 403
   - 404
   - 405
   - 500
   - 503

Response
--------

**Example List Api Versions: JSON request**


.. literalinclude:: ./samples/versions-response.json
   :language: javascript
