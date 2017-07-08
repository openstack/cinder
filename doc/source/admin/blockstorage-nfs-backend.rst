=================================
Configure an NFS storage back end
=================================

This section explains how to configure OpenStack Block Storage to use
NFS storage. You must be able to access the NFS shares from the server
that hosts the ``cinder`` volume service.

.. note::

   The ``cinder`` volume service is named ``openstack-cinder-volume``
   on the following distributions:

   * CentOS

   * Fedora

   * openSUSE

   * Red Hat Enterprise Linux

   * SUSE Linux Enterprise

   In Ubuntu and Debian distributions, the ``cinder`` volume service is
   named ``cinder-volume``.

**Configure Block Storage to use an NFS storage back end**

#. Log in as ``root`` to the system hosting the ``cinder`` volume
   service.

#. Create a text file named ``nfsshares`` in the ``/etc/cinder/`` directory.

#. Add an entry to ``/etc/cinder/nfsshares`` for each NFS share
   that the ``cinder`` volume service should use for back end storage.
   Each entry should be a separate line, and should use the following
   format:

   .. code-block:: bash

      HOST:SHARE


   Where:

   * HOST is the IP address or host name of the NFS server.

   * SHARE is the absolute path to an existing and accessible NFS share.

   |

#. Set ``/etc/cinder/nfsshares`` to be owned by the ``root`` user and
   the ``cinder`` group:

   .. code-block:: console

      # chown root:cinder /etc/cinder/nfsshares

#. Set ``/etc/cinder/nfsshares`` to be readable by members of the
   cinder group:

   .. code-block:: console

      # chmod 0640 /etc/cinder/nfsshares

#. Configure the ``cinder`` volume service to use the
   ``/etc/cinder/nfsshares`` file created earlier. To do so, open
   the ``/etc/cinder/cinder.conf`` configuration file and set
   the ``nfs_shares_config`` configuration key
   to ``/etc/cinder/nfsshares``.

   On distributions that include ``openstack-config``, you can configure
   this by running the following command instead:

   .. code-block:: console

      # openstack-config --set /etc/cinder/cinder.conf \
        DEFAULT nfs_shares_config /etc/cinder/nfsshares

   The following distributions include openstack-config:

   * CentOS

   * Fedora

   * openSUSE

   * Red Hat Enterprise Linux

   * SUSE Linux Enterprise


#. Optionally, provide any additional NFS mount options required in
   your environment in the ``nfs_mount_options`` configuration key
   of ``/etc/cinder/cinder.conf``. If your NFS shares do not
   require any additional mount options (or if you are unsure),
   skip this step.

   On distributions that include ``openstack-config``, you can
   configure this by running the following command instead:

   .. code-block:: console

      # openstack-config --set /etc/cinder/cinder.conf \
        DEFAULT nfs_mount_options OPTIONS

   Replace OPTIONS with the mount options to be used when accessing
   NFS shares. See the manual page for NFS for more information on
   available mount options (:command:`man nfs`).

#. Configure the ``cinder`` volume service to use the correct volume
   driver, namely ``cinder.volume.drivers.nfs.NfsDriver``. To do so,
   open the ``/etc/cinder/cinder.conf`` configuration file and
   set the volume_driver configuration key
   to ``cinder.volume.drivers.nfs.NfsDriver``.

   On distributions that include ``openstack-config``, you can configure
   this by running the following command instead:

   .. code-block:: console

      # openstack-config --set /etc/cinder/cinder.conf \
        DEFAULT volume_driver cinder.volume.drivers.nfs.NfsDriver

#. You can now restart the service to apply the configuration.

   .. note::

      The ``nfs_sparsed_volumes`` configuration key determines whether
      volumes are created as sparse files and grown as needed or fully
      allocated up front. The default and recommended value is ``true``,
      which ensures volumes are initially created as sparse files.

      Setting ``nfs_sparsed_volumes`` to ``false`` will result in
      volumes being fully allocated at the time of creation. This leads
      to increased delays in volume creation.

      However, should you choose to set ``nfs_sparsed_volumes`` to
      ``false``, you can do so directly in ``/etc/cinder/cinder.conf``.

      On distributions that include ``openstack-config``, you can
      configure this by running the following command instead:

      .. code-block:: console

         # openstack-config --set /etc/cinder/cinder.conf \
           DEFAULT nfs_sparsed_volumes false

   .. warning::

      If a client host has SELinux enabled, the ``virt_use_nfs``
      boolean should also be enabled if the host requires access to
      NFS volumes on an instance. To enable this boolean, run the
      following command as the ``root`` user:

      .. code-block:: console

         # setsebool -P virt_use_nfs on

      This command also makes the boolean persistent across reboots.
      Run this command on all client hosts that require access to NFS
      volumes on an instance. This includes all compute nodes.
