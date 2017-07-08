==============================
Configure a GlusterFS back end
==============================

This section explains how to configure OpenStack Block Storage to use
GlusterFS as a back end. You must be able to access the GlusterFS shares
from the server that hosts the ``cinder`` volume service.

.. note::

   The GlusterFS volume driver, which was deprecated in the Newton release,
   has been removed in the Ocata release.

.. note::

   The cinder volume service is named ``openstack-cinder-volume`` on the
   following distributions:

   * CentOS

   * Fedora

   * openSUSE

   * Red Hat Enterprise Linux

   * SUSE Linux Enterprise

   In Ubuntu and Debian distributions, the ``cinder`` volume service is
   named ``cinder-volume``.

Mounting GlusterFS volumes requires utilities and libraries from the
``glusterfs-fuse`` package. This package must be installed on all systems
that will access volumes backed by GlusterFS.

.. note::

   The utilities and libraries required for mounting GlusterFS volumes on
   Ubuntu and Debian distributions are available from the ``glusterfs-client``
   package instead.

For information on how to install and configure GlusterFS, refer to the
`GlusterFS Documentation`_ page.

**Configure GlusterFS for OpenStack Block Storage**

The GlusterFS server must also be configured accordingly in order to allow
OpenStack Block Storage to use GlusterFS shares:

#. Log in as ``root`` to the GlusterFS server.

#. Set each Gluster volume to use the same UID and GID as the ``cinder`` user:

   .. code-block:: console

      # gluster volume set VOL_NAME storage.owner-uid CINDER_UID
      # gluster volume set VOL_NAME storage.owner-gid CINDER_GID


   Where:

   * VOL_NAME is the Gluster volume name.

   * CINDER_UID is the UID of the ``cinder`` user.

   * CINDER_GID is the GID of the ``cinder`` user.

   .. note::

      The default UID and GID of the ``cinder`` user is 165 on
      most distributions.

#. Configure each Gluster volume to accept ``libgfapi`` connections.
   To do this, set each Gluster volume to allow insecure ports:

   .. code-block:: console

      # gluster volume set VOL_NAME server.allow-insecure on

#. Enable client connections from unprivileged ports. To do this,
   add the following line to ``/etc/glusterfs/glusterd.vol``:

   .. code-block:: bash

      option rpc-auth-allow-insecure on

#. Restart the ``glusterd`` service:

   .. code-block:: console

      # service glusterd restart


**Configure Block Storage to use a GlusterFS back end**

After you configure the GlusterFS service, complete these steps:

#. Log in as ``root`` to the system hosting the Block Storage service.

#. Create a text file named ``glusterfs`` in ``/etc/cinder/`` directory.

#. Add an entry to ``/etc/cinder/glusterfs`` for each GlusterFS
   share that OpenStack Block Storage should use for back end storage.
   Each entry should be a separate line, and should use the following
   format:

   .. code-block:: bash

      HOST:/VOL_NAME


   Where:

   * HOST is the IP address or host name of the Red Hat Storage server.

   * VOL_NAME is the name of an existing and accessible volume on the
     GlusterFS server.

   |

   Optionally, if your environment requires additional mount options for
   a share, you can add them to the share's entry:

   .. code-block:: yaml

      HOST:/VOL_NAME -o OPTIONS

   Replace OPTIONS with a comma-separated list of mount options.

#. Set ``/etc/cinder/glusterfs`` to be owned by the root user
   and the ``cinder`` group:

   .. code-block:: console

      # chown root:cinder /etc/cinder/glusterfs

#. Set ``/etc/cinder/glusterfs`` to be readable by members of
   the ``cinder`` group:

   .. code-block:: console

      # chmod 0640 /etc/cinder/glusterfs

#. Configure OpenStack Block Storage to use the ``/etc/cinder/glusterfs``
   file created earlier. To do so, open the ``/etc/cinder/cinder.conf``
   configuration file and set the ``glusterfs_shares_config`` configuration
   key to ``/etc/cinder/glusterfs``.

   On distributions that include openstack-config, you can configure this
   by running the following command instead:

   .. code-block:: console

      # openstack-config --set /etc/cinder/cinder.conf \
        DEFAULT glusterfs_shares_config /etc/cinder/glusterfs

   The following distributions include ``openstack-config``:

   * CentOS

   * Fedora

   * openSUSE

   * Red Hat Enterprise Linux

   * SUSE Linux Enterprise

   |

#. Configure OpenStack Block Storage to use the correct volume driver,
   namely ``cinder.volume.drivers.glusterfs.GlusterfsDriver``. To do so,
   open the ``/etc/cinder/cinder.conf`` configuration file and set
   the ``volume_driver`` configuration key to
   ``cinder.volume.drivers.glusterfs.GlusterfsDriver``.

   On distributions that include ``openstack-config``, you can configure
   this by running the following command instead:

   .. code-block:: console

      # openstack-config --set /etc/cinder/cinder.conf \
        DEFAULT volume_driver cinder.volume.drivers.glusterfs.GlusterfsDriver

#. You can now restart the service to apply the configuration.


OpenStack Block Storage is now configured to use a GlusterFS back end.

.. warning::

   If a client host has SELinux enabled, the ``virt_use_fusefs`` boolean
   should also be enabled if the host requires access to GlusterFS volumes
   on an instance. To enable this Boolean, run the following command as
   the ``root`` user:

   .. code-block:: console

      # setsebool -P virt_use_fusefs on

   This command also makes the Boolean persistent across reboots. Run
   this command on all client hosts that require access to GlusterFS
   volumes on an instance. This includes all compute nodes.

.. Links
.. _`GlusterFS Documentation`: https://gluster.readthedocs.io/en/latest/
