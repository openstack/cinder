.. -*- rst -*-

API versions
============

List All Api Versions
~~~~~~~~~~~~~~~~~~~~~

.. rest_method:: GET /

Lists information for all Block Storage API versions.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 300

.. rest_status_code:: error ../status.yaml

   - 400
   - 401
   - 403
   - 405
   - 404
   - 409
   - 500
   - 503

Request
-------

Response
--------

**Example List Api Versions: JSON request**


.. literalinclude:: ./samples/versions/versions-response.json
   :language: javascript
