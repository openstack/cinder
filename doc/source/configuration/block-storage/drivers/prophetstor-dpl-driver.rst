===========================================
ProphetStor Fibre Channel and iSCSI drivers
===========================================

ProhetStor Fibre Channel and iSCSI drivers add support for
ProphetStor Flexvisor through the Block Storage service.
ProphetStor Flexvisor enables commodity x86 hardware as software-defined
storage leveraging well-proven ZFS for disk management to provide
enterprise grade storage services such as snapshots, data protection
with different RAID levels, replication, and deduplication.

The ``DPLFCDriver`` and ``DPLISCSIDriver`` drivers run volume operations
by communicating with the ProphetStor storage system over HTTPS.

Supported operations
~~~~~~~~~~~~~~~~~~~~

* Create, delete, attach, and detach volumes.

* Create, list, and delete volume snapshots.

* Create a volume from a snapshot.

* Copy an image to a volume.

* Copy a volume to an image.

* Clone a volume.

* Extend a volume.

Enable the Fibre Channel or iSCSI drivers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The ``DPLFCDriver`` and ``DPLISCSIDriver`` are installed with the OpenStack
software.

#. Query storage pool id to configure ``dpl_pool`` of the ``cinder.conf``
   file.

   a. Log on to the storage system with administrator access.

      .. code-block:: console

         $ ssh root@STORAGE_IP_ADDRESS

   b. View the current usable pool id.

      .. code-block:: console

         $ flvcli show pool list
         - d5bd40b58ea84e9da09dcf25a01fdc07 : default_pool_dc07

   c. Use ``d5bd40b58ea84e9da09dcf25a01fdc07`` to configure the ``dpl_pool`` of
      ``/etc/cinder/cinder.conf`` file.

      .. note::

         Other management commands can be referenced with the help command
         :command:`flvcli -h`.

#. Make the following changes on the volume node ``/etc/cinder/cinder.conf``
   file.

   .. code-block:: ini

      # IP address of SAN controller (string value)
      san_ip=STORAGE IP ADDRESS

      # Username for SAN controller (string value)
      san_login=USERNAME

      # Password for SAN controller (string value)
      san_password=PASSWORD

      # Use thin provisioning for SAN volumes? (boolean value)
      san_thin_provision=true

      # The port that the iSCSI daemon is listening on. (integer value)
      iscsi_port=3260

      # DPL pool uuid in which DPL volumes are stored. (string value)
      dpl_pool=d5bd40b58ea84e9da09dcf25a01fdc07

      # DPL port number. (integer value)
      dpl_port=8357

      # Uncomment one of the next two option to enable Fibre channel or iSCSI
      # FIBRE CHANNEL(uncomment the next line to enable the FC driver)
      #volume_driver=cinder.volume.drivers.prophetstor.dpl_fc.DPLFCDriver
      # iSCSI (uncomment the next line to enable the iSCSI driver)
      #volume_driver=cinder.volume.drivers.prophetstor.dpl_iscsi.DPLISCSIDriver

#. Save the changes to the ``/etc/cinder/cinder.conf`` file and
   restart the ``cinder-volume`` service.

The ProphetStor Fibre Channel or iSCSI drivers are now enabled on your
OpenStack system. If you experience problems, review the Block Storage
service log files for errors.

The following table contains the options supported by the ProphetStor
storage driver.

.. include:: ../../tables/cinder-prophetstor_dpl.inc
