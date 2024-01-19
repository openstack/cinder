.. _image_volume_cache:


==================
Image-Volume cache
==================

OpenStack Block Storage has an optional Image cache which can dramatically
improve the performance of creating a volume from an image. The improvement
depends on many factors, primarily how quickly the configured back end can
clone a volume.

When a volume is first created from an image, a new cached image-volume
will be created that is owned by the Block Storage Internal Tenant. Subsequent
requests to create volumes from that image will clone the cached version
instead of downloading the image contents and copying data to the volume.

The cache itself is configurable per back end and will contain the most
recently used images.

.. _internal-tenant:

Configure the Internal Tenant
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The Image-Volume cache requires that the Internal Tenant be configured for
the Block Storage services. This project will own the cached image-volumes so
they can be managed like normal users including tools like volume quotas. This
protects normal users from having to see the cached image-volumes, but does
not make them globally hidden.

To enable the Block Storage services to have access to an Internal Tenant, set
the following options in the ``cinder.conf`` file:

.. code-block:: ini

   cinder_internal_tenant_project_id = PROJECT_ID
   cinder_internal_tenant_user_id = USER_ID

An example ``cinder.conf`` configuration file:

.. code-block:: ini

   cinder_internal_tenant_project_id = b7455b8974bb4064ad247c8f375eae6c
   cinder_internal_tenant_user_id = f46924c112a14c80ab0a24a613d95eef

.. note::

   The actual user and project that are configured for the Internal Tenant do
   not require any special privileges. They can be the Block Storage service
   project or can be any normal project and user.

Configure the Image-Volume cache
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To enable the Image-Volume cache, set the following configuration option in
the ``cinder.conf`` file:

.. code-block:: ini

   image_volume_cache_enabled = True

.. note::

   If you use Ceph as a back end, set the following configuration option in
   the ``cinder.conf`` file:

   .. code-block:: ini

     [ceph]
     image_volume_cache_enabled = True

This can be scoped per back end definition or in the default options.

There are optional configuration settings that can limit the size of the cache.
These can also be scoped per back end or in the default options in
the ``cinder.conf`` file:

.. code-block:: ini

   image_volume_cache_max_size_gb = SIZE_GB
   image_volume_cache_max_count = MAX_COUNT

By default they will be set to 0, which means unlimited.

For example, a configuration which would limit the max size to 200 GB and 50
cache entries will be configured as:

.. code-block:: ini

   image_volume_cache_max_size_gb = 200
   image_volume_cache_max_count = 50

.. note::

   As mentioned above, the :ref:`internal tenant<internal-tenant>` configured
   as the cache owner does not require any special permissions and is subject
   to quotas like any other user.  Hence, it is possible that the quotas for
   the internal tenant may need to be adjusted to allow the internal tenant
   to hold at least ``image_volume_cache_max_count`` volumes not exceeding
   ``image_volume_cache_max_size_gb`` total size.  Thus, although the default
   value for these image volume cache settings is ``0`` (unlimited), in
   practice, these will be limited by the quotas that apply to the internal
   tenant.

   See :doc:`../cli/cli-cinder-quotas` for more information.

Notifications
~~~~~~~~~~~~~

Cache actions will trigger Telemetry messages. There are several that will be
sent.

- ``image_volume_cache.miss`` - A volume is being created from an image which
  was not found in the cache. Typically this will mean a new cache entry would
  be created for it.

- ``image_volume_cache.hit`` - A volume is being created from an image which
  was found in the cache and the fast path can be taken.

- ``image_volume_cache.evict`` - A cached image-volume has been deleted from
  the cache.


Managing cached Image-Volumes
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

In normal usage there should be no need for manual intervention with the cache.
The entries and their backing Image-Volumes are managed automatically.

If needed, you can delete these volumes manually to clear the cache.
By using the standard volume deletion APIs, the Block Storage service will
clean up correctly.
