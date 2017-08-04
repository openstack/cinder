==============
Quobyte driver
==============

The `Quobyte <http://www.quobyte.com/>`__ volume driver enables storing Block
Storage service volumes on a Quobyte storage back end. Block Storage service
back ends are mapped to Quobyte volumes and individual Block Storage service
volumes are stored as files on a Quobyte volume.  Selection of the appropriate
Quobyte volume is done by the aforementioned back end configuration that
specifies the Quobyte volume explicitly.

.. note::

   Note the dual use of the term ``volume`` in the context of Block Storage
   service volumes and in the context of Quobyte volumes.

For more information see `the Quobyte support webpage
<http://support.quobyte.com/>`__.

Supported operations
~~~~~~~~~~~~~~~~~~~~

The Quobyte volume driver supports the following volume operations:

- Create, delete, attach, and detach volumes

- Secure NAS operation (Starting with Mitaka release secure NAS operation is
  optional but still default)

- Create and delete a snapshot

- Create a volume from a snapshot

- Extend a volume

- Clone a volume

- Copy a volume to image

- Generic volume migration (no back end optimization)

.. note::

   When running VM instances off Quobyte volumes, ensure that the `Quobyte
   Compute service driver <https://wiki.openstack.org/wiki/Nova/Quobyte>`__
   has been configured in your OpenStack cloud.

Configuration
~~~~~~~~~~~~~

To activate the Quobyte volume driver, configure the corresponding
``volume_driver`` parameter:

.. code-block:: ini

   volume_driver = cinder.volume.drivers.quobyte.QuobyteDriver

The following table contains the configuration options supported by the
Quobyte driver:

.. include:: ../../tables/cinder-quobyte.inc
