.. _volume_backed_image:


==============================
Cinder as a backend for Glance
==============================

OpenStack Block Storage (Cinder) provides the ability to be configured
as a backend for Glance. This configuration offers various optimizations
between Glance Cinder interaction and also allows a common storage strategy
where Cinder volumes are used to store Glance images.

Configure Cinder backend for Glance
===================================

To configure Cinder as a backend for Glance, refer to the detailed guide
in the Glance documentation `configuring-the-cinder-storage-backend`_.
Note that Glance has deprecated support for single store and recommends
configuring multi store deployment.

Optimization
============

Cinder requires location information from Glance to be able to perform
optimizations in the operations that involve Glance Cinder interaction.
Following are the operations that benefit from the optimzations:

- Create a bootable volume from image
- Upload a volume to Image Service

Starting with the 2025.2 (Flamingo) release, Cinder supports the `New
Location APIs`_ which allows Cinder to **Add** and **Get** the location from
the Image service without allowing the exploit of OSSN-0090 and OSSN-0065.
If you are running a version of Cinder prior to the 2025.2 (Flamingo)
release, read through OSSN-0090 and then configure the following parameters
in the Glance configuration file to allow Glance to expose the image location
that can be consumed by Cinder.

.. code-block:: ini

   [DEFAULT]
   show_image_direct_url = True
   show_multiple_locations = True

Creating a bootable volume from image
--------------------------------------

Cinder provides an optimized path for creating bootable volume from images
where the images are stored in volumes called Image-Volume. There are two
pre-conditions that needs to be satisfied for this optimization to work:

1. Image format should be 'raw' and container format should be 'bare'
2. The user requested volume should be in the same project as the image

To enable this optimization, configure the following parameter in the Cinder
configuration file:

.. code-block:: ini

   [DEFAULT]
   allowed_direct_url_schemes = cinder

This optimization allows efficient cloning of the Image-Volume to the user
requested volume which skips the generic path of downloading the image to
the image conversion directory and writing it into the volume hence saving
space and increasing performance for single or bulk operations.

Uploading a volume to Image Service
-----------------------------------

When uploading a volume to the Image service, the data is copied chunk by
chunk resulting in long wait time for the completion of the operation.
With this optimization, Cinder clones the source volume to an Image-Volume
and registers the location in Glance which is a significant performance
improvement over the generic path.
The pre-condition to enable this optimization is:

1. Image format should be 'raw' and container format should be 'bare'

Add the following configuration parameter in your Cinder configuration file
in the respective backend section. Here we've used ``lvmdriver-1`` as an
example.

.. code-block:: ini

   [lvmdriver-1]
   image_upload_use_cinder_backend = True

To avoid creating the Image-Volume in the user project, it is recommended to
configure the internal tenant so the Image-Volumes are always stored in the
service project. The ``image_upload_use_internal_tenant`` configuration should
be done in the backend section, Here we've used ``lvmdriver-1`` as an example.

.. code-block:: ini

    [DEFAULT]
    cinder_internal_tenant_project_id = <UUID of the service project>
    cinder_internal_tenant_user_id = <UUID of the Cinder user>
    [lvmdriver-1]
    image_upload_use_internal_tenant = True

.. _configuring-the-cinder-storage-backend: https://docs.openstack.org/glance/latest/configuration/configuring.html#configuring-the-cinder-storage-backend

.. _New Location APIs: https://docs.openstack.org/glance/latest/admin/new-location-apis.html
