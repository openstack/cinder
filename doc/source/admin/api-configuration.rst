=================
API Configuration
=================

.. todo::

   This needs to be expanded to include information on e.g. PasteDeploy.

Rate limiting
-------------

.. warning::

   This is legacy functionality that is poorly tested and may be removed in the
   future. You may wish to enforce rate limiting through a proxy server
   instead.

Cinder supports admin-configured API limits. These are disabled by default but
can be configured by modifying :file:`api-paste.ini` to enabled the
``RateLimitingMiddleware`` middleware. For example, given the following
composite application definitions in e.g. ``/etc/cinder/api-paste.ini``:

.. code-block:: ini

  [composite:openstack_volume_api_v2]
  use = call:cinder.api.middleware.auth:pipeline_factory
  noauth = cors ... apiv2
  keystone = cors ... apiv2
  keystone_nolimit = cors ... apiv2

  [composite:openstack_volume_api_v3]
  use = call:cinder.api.middleware.auth:pipeline_factory
  noauth = cors ... apiv3
  keystone = cors ... apiv3
  keystone_nolimit = cors ... apiv3

You can configure rate limiting by adding a new filter to call
``RateLimitingMiddleware`` and configure the composite applications to use this
filter:

.. code-block:: ini

  [composite:openstack_volume_api_v2]
  use = call:cinder.api.middleware.auth:pipeline_factory
  noauth = cors ... ratelimit apiv2
  keystone = cors ... ratelimit apiv2
  keystone_nolimit = cors ... ratelimit apiv2

  [composite:openstack_volume_api_v3]
  use = call:cinder.api.middleware.auth:pipeline_factory
  noauth = cors ... ratelimit apiv3
  keystone = cors ... ratelimit apiv3
  keystone_nolimit = cors ... ratelimit apiv3

  [filter:ratelimit]
  paste.filter_factory = cinder.api.v2.limits:RateLimitingMiddleware.factory

Once configured, restart the :program:`cinder-api` service. Users can then view
API limits using the ``openstack limits show --rate`` command. For example:

.. code-block:: bash

   $ openstack limits show --rate
   +--------+-----------------+-------+--------+--------+---------------------+
   | Verb   | URI             | Value | Remain | Unit   | Next Available      |
   +--------+-----------------+-------+--------+--------+---------------------+
   | POST   | *               |    10 |     10 | MINUTE | 2021-03-23T12:36:09 |
   | PUT    | *               |    10 |     10 | MINUTE | 2021-03-23T12:36:09 |
   | DELETE | *               |   100 |    100 | MINUTE | 2021-03-23T12:36:09 |
   | POST   | */servers       |    50 |     50 | DAY    | 2021-03-23T12:36:09 |
   | GET    | *changes-since* |     3 |      3 | MINUTE | 2021-03-23T12:36:09 |
   +--------+-----------------+-------+--------+--------+---------------------+

.. note::

   Rate limits are entirely separate from absolute limits, which track resource
   utilization and can be seen using the ``openstack limits show --absolute``
   command.
