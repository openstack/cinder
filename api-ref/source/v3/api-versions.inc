.. -*- rst -*-

List All Api Versions
=====================

.. rest_method:: GET /

Lists information for all Block Storage API versions.


Normal response codes: 300

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404), conflict(409)

Request
~~~~~~~

Response
~~~~~~~~

**Example List Api Versions: JSON request**


.. literalinclude:: ./samples/versions-response.json
   :language: javascript
