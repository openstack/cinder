REST API Version History
========================

This documents the changes made to the REST API with every
microversion change. The description for each version should be a
verbose one which has enough information to be suitable for use in
user documentation.

3.0
---
  The 3.0 Cinder API includes all v2 core APIs existing prior to
  the introduction of microversions.  The /v3 URL is used to call
  3.0 APIs.
  This it the initial version of the Cinder API which supports
  microversions.

  A user can specify a header in the API request::

    OpenStack-API-Version: volume <version>

  where ``<version>`` is any valid api version for this API.

  If no version is specified then the API will behave as if version 3.0
  was requested.

  The only API change in version 3.0 is versions, i.e.
  GET http://localhost:8786/, which now returns information about
  3.0 and later versions and their respective /v3 endpoints.

  All other 3.0 APIs are functionally identical to version 2.0.
