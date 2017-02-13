.. -*- rst -*-

API versions
============

Lists information about API versions.


Show API v1 details
~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v1

Shows Block Storage API v1 details.


Normal response codes: 200
Error response codes:203,


Request
-------


Response Example
----------------

.. literalinclude:: ./samples/version-show-response.json
   :language: javascript


List API versions (v1)
~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /

Lists information about all Block Storage API versions.


Normal response codes: 300


Request
-------



Response Example
----------------

.. literalinclude:: ./samples/versions-list-response.json
   :language: javascript
