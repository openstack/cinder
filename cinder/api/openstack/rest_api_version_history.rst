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

3.1
---
  Added the parameters ``protected`` and ``visibility`` to
  _volume_upload_image requests.

3.2
---
  Change in return value of 'GET API request' for fetching cinder volume
  list on the basis of 'bootable' status of volume as filter.

  Before V3.2, 'GET API request' to fetch volume list returns non-bootable
  volumes if bootable filter value is any of the false or False.
  For any other value provided to this filter, it always returns
  bootable volumes list.

  But in V3.2, this behavior is updated.
  In V3.2, bootable volume list will be returned for any of the
  'T/True/1/true' bootable filter values only.
  Non-bootable volume list will be returned for any of 'F/False/0/false'
  bootable filter values.
  But for any other values passed for bootable filter, it will return
  "Invalid input received: bootable={filter value}' error.

3.3
---
  Added /messages API.

3.4
---
  Added the filter parameters ``glance_metadata`` to
  list/detail volumes requests.

3.5
---
  Added pagination support to /messages API
