.. -*- rst -*-

============
API versions
============




List Known API versions
=======================

.. rest_method::  GET /

Lists information for all Block Storage API versions.


Normal response codes: 200
Error response codes:300,


Request
-------


Response Example
----------------

.. literalinclude:: ./samples/versions-response.json
   :language: javascript




Show API v3 details
===================

.. rest_method::  GET /v3

Shows details for Block Storage API v3.


Normal response codes: 200
Error response codes:203,


Request
-------



Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - location: location



Response Example
----------------

.. literalinclude:: ./samples/version-v3-show-response.json
   :language: javascript


