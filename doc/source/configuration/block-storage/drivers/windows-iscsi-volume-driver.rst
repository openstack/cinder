.. _windows_iscsi_volume_driver:

===========================
Windows iSCSI volume driver
===========================

Windows Server offers an integrated iSCSI Target service that can be used with
OpenStack Block Storage in your stack.

Being entirely a software solution, consider it in particular for mid-sized
networks where the costs of a SAN might be excessive.

The Windows iSCSI Block Storage driver works with OpenStack Compute on any
hypervisor.

This driver creates volumes backed by fixed-type VHD images on Windows Server
2012 and dynamic-type VHDX on Windows Server 2012 R2 and onwards, stored
locally on a  user-specified path. The system uses those images as iSCSI disks
and exports them through iSCSI targets. Each volume has its own iSCSI target.

The ``cinder-volume`` service as well as the required Python components will
be installed directly onto the Windows node.

Prerequisites
~~~~~~~~~~~~~

The Windows iSCSI volume driver depends on the ``wintarget`` Windows service.
This will require the ``iSCSI Target Server`` Windows feature to be installed.

.. note::
   The Cinder MSI will automatically enable this feature, if available (some
   minimal Windows versions do not provide it).

   You may check the availability of this feature by running the following:

   .. code-block:: powershell

      Get-WindowsFeature FS-iSCSITarget-Server
   .. end
.. end

The Windows Server installation requires at least 16 GB of disk space. The
volumes hosted by this node will need extra space.

Configuring cinder-volume
~~~~~~~~~~~~~~~~~~~~~~~~~

Below is a configuration sample for using the Windows iSCSI Driver. Append
those options to your already existing ``cinder.conf`` file, described at
:ref:`cinder_storage_install_windows`.

.. code-block:: ini

   [DEFAULT]
   enabled_backends = winiscsi

   [winiscsi]
   volume_driver = cinder.volume.drivers.windows.iscsi.WindowsISCSIDriver
   windows_iscsi_lun_path = C:\iSCSIVirtualDisks
   volume_backend_name = winiscsi

   # The following config options are optional
   #
   # use_chap_auth = true
   # target_port = 3260
   # target_ip_addres = <IP_USED_FOR_ISCSI_TRAFFIC>
   # iscsi_secondary_ip_addresses = <SECONDARY_ISCSI_IPS>
   # reserved_percentage = 5
.. end

The ``windows_iscsi_lun_path`` config option specifies the directory in
which VHD backed volumes will be stored.
