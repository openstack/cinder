.. _accelerate_image_compression:


============================
Accelerate image compression
============================

A general framework to accommodate hardware compression accelerators for
compression of volumes uploaded to the Image service (Glance) as images and
decompression of compressed images used to create volumes is introduced in
Train release.

The only accelerator supported in this release is Intel QuickAssist Technology
(QAT), which produces a compressed file in gzip format.  Additionally, the
framework provides software-based compression using GUNzip tool if a suitable
hardware accelerator is not available.  Because this software fallback could
cause performance problems if the Cinder services are not deployed on
sufficiently powerful nodes, the default setting is *not* to enable compression
on image upload or download.

The compressed image of a volume will be stored in the Image service (Glance)
with the ``container_format`` image property of ``compressed``.  See the `Image
service documentation <https://docs.openstack.org/glance/latest>`_ for more
information about this image container format.

Configure image compression
~~~~~~~~~~~~~~~~~~~~~~~~~~~

To enable the image compression feature, set the following configuration option
in the ``cinder.conf`` file:

.. code-block:: ini

   allow_compression_on_image_upload = True

By default it will be set to False, which means image compression is disabled.

.. code-block:: ini

   compression_format = gzip

This is to specify image compression format. The only supported format is
``gzip`` in Train release.

System requirement
~~~~~~~~~~~~~~~~~~

In order to use this feature, there should be a hardware accelerator existing
in system, otherwise no benefit will get from this feature. Regarding the two
accelerators that supported, system should be configured as below:

- ``Intel QuickAssist Technology (QAT)`` - This is the hardware accelerator
  from Intel. The driver of QAT should be installed, refer to
  https://01.org/intel-quickassist-technology. Also the compression library
  QATzip should be installed, refer to https://github.com/intel/QATzip.

- ``GUNzip`` - The related package of ``GUNzip`` should be installed and the
  command ``gzip`` should be available. This is used as fallback when hardware
  accelerator is not available.
