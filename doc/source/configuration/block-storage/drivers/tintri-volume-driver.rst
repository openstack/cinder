======
Tintri
======

Tintri VMstore is a smart storage that sees, learns, and adapts for cloud and
virtualization. The Tintri Block Storage driver interacts with configured
VMstore running Tintri OS 4.0 and above. It supports various operations using
Tintri REST APIs and NFS protocol.

To configure the use of a Tintri VMstore with Block Storage, perform the
following actions:

#. Edit the ``etc/cinder/cinder.conf`` file and set the
   ``cinder.volume.drivers.tintri`` options:

   .. code-block:: ini

      volume_driver=cinder.volume.drivers.tintri.TintriDriver
      # Mount options passed to the nfs client. See section of the
      # nfs man page for details. (string value)
      nfs_mount_options = vers=3,lookupcache=pos

      #
      # Options defined in cinder.volume.drivers.tintri
      #

      # The hostname (or IP address) for the storage system (string
      # value)
      tintri_server_hostname = {Tintri VMstore Management IP}

      # User name for the storage system (string value)
      tintri_server_username = {username}

      # Password for the storage system (string value)
      tintri_server_password = {password}

      # API version for the storage system (string value)
      # tintri_api_version = v310

      # Following options needed for NFS configuration
      # File with the list of available nfs shares (string value)
      # nfs_shares_config = /etc/cinder/nfs_shares

      # Tintri driver will clean up unused image snapshots. With the following
      # option, users can configure how long unused image snapshots are
      # retained. Default retention policy is 30 days
      # tintri_image_cache_expiry_days = 30

      # Path to NFS shares file storing images.
      # Users can store Glance images in the NFS share of the same VMstore
      # mentioned in the following file. These images need to have additional
      # metadata ``provider_location`` configured in Glance, which should point
      # to the NFS share path of the image.
      # This option will enable Tintri driver to directly clone from Glance
      # image stored on same VMstore (rather than downloading image
      # from Glance)
      # tintri_image_shares_config = <Path to image NFS share>
      #
      # For example:
      # Glance image metadata
      # provider_location =>
      # nfs://<data_ip>/tintri/glance/84829294-c48b-4e16-a878-8b2581efd505

#. Edit the ``/etc/nova/nova.conf`` file and set the ``nfs_mount_options``:

   .. code-block:: ini

      [libvirt]
      nfs_mount_options = vers=3

#. Edit the ``/etc/cinder/nfs_shares`` file and add the Tintri VMstore mount
   points associated with the configured VMstore management IP in the
   ``cinder.conf`` file:

   .. code-block:: bash

      {vmstore_data_ip}:/tintri/{submount1}
      {vmstore_data_ip}:/tintri/{submount2}


.. include:: ../../tables/cinder-tintri.inc
