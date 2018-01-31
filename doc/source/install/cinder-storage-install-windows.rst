.. _cinder_storage_install_windows:

Install and configure a storage node
====================================

Prerequisites
~~~~~~~~~~~~~

The following Windows versions are officially supported by Cinder:

* ``Windows Server 2012``
* ``Windows Server 2012 R2``
* ``Windows Server 2016``

The OpenStack Cinder Volume MSI installer is the recommended deployment tool
for Cinder on Windows. You can find it at
https://cloudbase.it/openstack-windows-storage/#download.

It installs an independent Python environment, in order to avoid conflicts
with existing applications. It can dynamically generate a ``cinder.conf`` file
based on the parameters you provide.

The OpenStack Cinder Volume MSI installer can be deployed in a fully automated
way using Puppet, Chef, SaltStack, Ansible, Juju, DSC, Windows Group Policies
or any other automated configuration framework.

Configure NTP
-------------

Network time services must be configured to ensure proper operation
of the OpenStack nodes. To set network time on your Windows host you
must run the following commands:

.. code-block:: bat

   net stop w32time
   w32tm /config /manualpeerlist:pool.ntp.org,0x8 /syncfromflags:MANUAL
   net start w32time

Keep in mind that the node will have to be time synchronized with
the other nodes of your OpenStack environment, so it is important to use
the same NTP server.

.. note::

    In case of an Active Directory environment, you may do this only for the
    AD Domain Controller.
.. end

Install and configure components
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The MSI may be run in the following modes:

Graphical mode
--------------
The installer will walk you through the commonly used cinder options,
automatically generating a config file based on your input.

You may run the following in order to run the installer in graphical mode,
also specifying a log file. Please use the installer full path.

.. code-block:: powershell

      msiexec /i CinderVolumeSetup.msi /l*v msi_log.txt
.. end

Unattended mode
---------------
The installer will deploy Cinder, taking care of required Windows services and
features. A minimal sample config file will be generated and need to be
updated accordingly.

Run the following in order to install Cinder in unattended mode, enabling the
iSCSI and SMB volume drivers.

.. code-block:: powershell

      msiexec /i CinderVolumeSetup.msi /qn /l*v msi_log.txt `
                 ADDLOCAL="iscsiDriver,smbDriver"
.. end

By default, Cinder will be installed at
``%ProgramFiles%\Cloudbase Solutions\OpenStack``. You may choose a different
install directory by using the ``INSTALLDIR`` argument, as following:


.. code-block:: powershell

      msiexec /i CinderVolumeSetup.msi /qn /l*v msi_log.txt `
                 ADDLOCAL="iscsiDriver,smbDriver" `
                 INSTALLDIR="C:\cinder"
.. end


The installer will generate a Windows service, called ``cinder-volume``.

.. note::
  Previous MSI releases may use a separate service per volume backend (e.g.
  cinder-volume-smb). You may double check the cinder services along with
  their executable paths by running the following:

  .. code-block:: powershell

      get-service cinder-volume*
      sc.exe qc cinder-volume-smb
  .. end

  Note that ``sc`` is also an alias for ``Set-Content``. To use the service
  control utility, you have to explicitly call ``sc.exe``.
.. end


Configuring Cinder
------------------
If you've run the installer in graphical mode, you may skip this part as the
MSI already took care of generating the configuration files.

The Cinder Volume Windows service configured by the MSI expects the cinder
config file to reside at::

   %INSTALLDIR%\etc\cinder.conf

You may use the following config sample, updating fields appropriately.

.. code-block:: ini

   [DEFAULT]
   my_ip = MANAGEMENT_INTERFACE_IP_ADDRESS
   auth_strategy = keystone
   transport_url = rabbit://RABBIT_USER:RABBIT_PASS@controller:5672
   glance_api_servers = http://controller/image
   sql_connection = mysql+pymysql://cinder:CINDER_DBPASS@controller/cinder
   image_conversion_dir = C:\OpenStack\ImageConversionDir\
   lock_path = C:\OpenStack\Lock\
   log_dir = C:\OpenStack\Log\
   log_file = cinder-volume.log

   [coordination]
   backend_url = file:///C:/OpenStack/Lock/

   [key_manager]
   api_class = cinder.keymgr.conf_key_mgr.ConfKeyManager
.. end

.. note::
    The above sample doesn't configure any Cinder Volume driver. To do
    so, follow the configuration guide for the driver of choice, appending
    driver specific config options.
.. end

Currently supported drivers on Windows:

* :ref:`windows_smb_volume_driver`
* :ref:`windows_iscsi_volume_driver`


Finalize installation
~~~~~~~~~~~~~~~~~~~~~

#. Restart the Cinder Volume service:

   .. code-block:: powershell

      Restart-Service cinder-volume

   .. end

#. Ensure that the Cinder Volume service is running:

   .. code-block:: powershell

      Get-Service cinder-volume

   .. end

