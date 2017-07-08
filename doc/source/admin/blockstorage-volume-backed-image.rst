.. _volume_backed_image:


===================
Volume-backed image
===================

OpenStack Block Storage can quickly create a volume from an image that refers
to a volume storing image data (Image-Volume). Compared to the other stores
such as file and swift, creating a volume from a Volume-backed image performs
better when the block storage driver supports efficient volume cloning.

If the image is set to public in the Image service, the volume data can be
shared among projects.

Configure the Volume-backed image
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Volume-backed image feature requires locations information from the cinder
store of the Image service. To enable the Image service to use the cinder
store, add ``cinder`` to the ``stores`` option in the ``glance_store`` section
of the ``glance-api.conf`` file:

.. code-block:: ini

   stores = file, http, swift, cinder

To expose locations information, set the following options in the ``DEFAULT``
section of the ``glance-api.conf`` file:

.. code-block:: ini

   show_multiple_locations = True

To enable the Block Storage services to create a new volume by cloning Image-
Volume, set the following options in the ``DEFAULT`` section of the
``cinder.conf`` file. For example:

.. code-block:: ini

   glance_api_version = 2
   allowed_direct_url_schemes = cinder

To enable the :command:`openstack image create --volume <volume>` command to
create an image that refers an ``Image-Volume``, set the following options in
each back-end section of the ``cinder.conf`` file:

.. code-block:: ini

   image_upload_use_cinder_backend = True

By default, the :command:`openstack image create --volume <volume>` command
creates the Image-Volume in the current project. To store the Image-Volume into
the internal project, set the following options in each back-end section of the
``cinder.conf`` file:

.. code-block:: ini

    image_upload_use_internal_tenant = True

To make the Image-Volume in the internal project accessible from the Image
service, set the following options in the ``glance_store`` section of
the ``glance-api.conf`` file:

- ``cinder_store_auth_address``
- ``cinder_store_user_name``
- ``cinder_store_password``
- ``cinder_store_project_name``

Creating a Volume-backed image
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To register an existing volume as a new Volume-backed image, use the following
commands:

.. code-block:: console

  $ openstack image create --disk-format raw --container-format bare IMAGE_NAME

  $ glance location-add <image-uuid> --url cinder://<volume-uuid>

If the ``image_upload_use_cinder_backend`` option is enabled, the following
command creates a new Image-Volume by cloning the specified volume and then
registers its location to a new image. The disk format and the container format
must be raw and bare (default). Otherwise, the image is uploaded to the default
store of the Image service.

.. code-block:: console

   $ openstack image create --volume SOURCE_VOLUME IMAGE_NAME
