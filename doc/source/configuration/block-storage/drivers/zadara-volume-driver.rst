=================================
Zadara Storage VPSA volume driver
=================================

Zadara Storage, Virtual Private Storage Array (VPSA) is the first software
defined, Enterprise-Storage-as-a-Service. It is an elastic and private block
and file storage system which, provides enterprise-grade data protection and
data management storage services.

The ``ZadaraVPSAISCSIDriver`` volume driver allows the Zadara Storage VPSA
to be used as a volume back end storage in OpenStack deployments.

System requirements
~~~~~~~~~~~~~~~~~~~

To use Zadara Storage VPSA Volume Driver you will require:

- Zadara Storage VPSA version 15.07 and above

- iSCSI or iSER host interfaces

Supported operations
~~~~~~~~~~~~~~~~~~~~~

- Create, delete, attach, and detach volumes
- Create, list, and delete volume snapshots
- Create a volume from a snapshot
- Copy an image to a volume
- Copy a volume to an image
- Clone a volume
- Extend a volume
- Migrate a volume with back end assistance

Configuration
~~~~~~~~~~~~~

#. Create a VPSA pool(s) or make sure you have an existing pool(s) that will
   be used for volume services. The VPSA pool(s) will be identified by its ID
   (pool-xxxxxxxx). For further details, see the
   `VPSA's user guide <http://tinyurl.com/hxo3tt5>`_.

#. Adjust the ``cinder.conf`` configuration file to define the volume driver
   name along with a storage back end entry for each VPSA pool that will be
   managed by the block storage service.
   Each back end entry requires a unique section name, surrounded by square
   brackets (or parentheses), followed by options in ``key=value`` format.

.. note::

   Restart cinder-volume service after modifying ``cinder.conf``.


Sample minimum back end configuration

.. code-block:: ini

   [DEFAULT]
   enabled_backends = vpsa

   [vpsa]
   zadara_vpsa_host = 172.31.250.10
   zadara_vpsa_port = 80
   zadara_user = vpsauser
   zadara_password = mysecretpassword
   zadara_use_iser = false
   zadara_vpsa_poolname = pool-00000001
   volume_driver = cinder.volume.drivers.zadara.ZadaraVPSAISCSIDriver
   volume_backend_name = vpsa

Driver-specific options
~~~~~~~~~~~~~~~~~~~~~~~

This section contains the configuration options that are specific
to the Zadara Storage VPSA driver.

.. include:: ../../tables/cinder-zadara.inc

.. note::

   By design, all volumes created within the VPSA are thin provisioned.
