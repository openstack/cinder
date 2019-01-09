===================================
Inspur AS13000 series volume driver
===================================

Inspur AS13000 series volume driver provides OpenStack Compute instances
with access to Inspur AS13000 series storage system.

Inspur AS13000 storage can be used with iSCSI connection.

This documentation explains how to configure and connect the block storage
nodes to Inspur AS13000 series storage.

Driver options
~~~~~~~~~~~~~~

The following table contains the configuration options supported by the
Inspur AS13000 iSCSI driver.

.. config-table::
   :config-target: Inspur AS13000

   cinder.volume.drivers.inspur.as13000.as13000_driver

Supported operations
~~~~~~~~~~~~~~~~~~~~

- Create, list, delete, attach (map), and detach (unmap) volumes.
- Create, list and delete volume snapshots.
- Create a volume from a snapshot.
- Copy an image to a volume.
- Copy a volume to an image.
- Clone a volume.
- Extend a volume.

Configure Inspur AS13000 iSCSI backend
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This section details the steps required to configure the Inspur AS13000
storage cinder driver.

#. In the ``cinder.conf`` configuration file under the ``[DEFAULT]``
   section, set the enabled_backends parameter.

   .. code-block:: ini

       [DEFAULT]
       enabled_backends = AS13000-1


#. Add a backend group section for backend group specified
   in the enabled_backends parameter.

#. In the newly created backend group section, set the
   following configuration options:

   .. code-block:: ini

       [AS13000-1]
       # The driver path
       volume_driver = cinder.volume.drivers.inspur.as13000.as13000_driver.AS13000Driver
       # Management IP of Inspur AS13000 storage array
       san_ip = 10.0.0.10
       # The Rest API port
       san_api_port = 8088
       # Management username of Inspur AS13000 storage array
       san_login = root
       # Management password of Inspur AS13000 storage array
       san_password = passw0rd
       # The Pool used to allocated volumes
       as13000_ipsan_pools = Pool0
       # The Meta Pool to use, should be a replication Pool
       as13000_meta_pool = Pool_Rep
       # Backend name
       volume_backend_name = AS13000


#. Save the changes to the ``/etc/cinder/cinder.conf`` file and
   restart the ``cinder-volume`` service.
