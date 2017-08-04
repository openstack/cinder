===========================
Windows iSCSI volume driver
===========================

Windows Server 2012 and Windows Storage Server 2012 offer an integrated iSCSI
Target service that can be used with OpenStack Block Storage in your stack.
Being entirely a software solution, consider it in particular for mid-sized
networks where the costs of a SAN might be excessive.

The Windows Block Storage driver works with OpenStack Compute on any
hypervisor. It includes snapshotting support and the ``boot from volume``
feature.

This driver creates volumes backed by fixed-type VHD images on Windows Server
2012 and dynamic-type VHDX on Windows Server 2012 R2, stored locally on a
user-specified path. The system uses those images as iSCSI disks and exports
them through iSCSI targets. Each volume has its own iSCSI target.

This driver has been tested with Windows Server 2012 and Windows Server R2
using the Server and Storage Server distributions.

Install the ``cinder-volume`` service as well as the required Python components
directly onto the Windows node.

You may install and configure ``cinder-volume`` and its dependencies manually
using the following guide or you may use the ``Cinder Volume Installer``,
presented below.

Installing using the OpenStack cinder volume installer
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

In case you want to avoid all the manual setup, you can use Cloudbase
Solutions' installer. You can find it at
https://www.cloudbase.it/downloads/CinderVolumeSetup_Beta.msi. It installs an
independent Python environment, in order to avoid conflicts with existing
applications, dynamically generates a ``cinder.conf`` file based on the
parameters provided by you.

``cinder-volume`` will be configured to run as a Windows Service, which can
be restarted using:

.. code-block:: console

   PS C:\> net stop cinder-volume ; net start cinder-volume

The installer can also be used in unattended mode. More details about how to
use the installer and its features can be found at https://www.cloudbase.it.

Windows Server configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The required service in order to run ``cinder-volume`` on Windows is
``wintarget``. This will require the iSCSI Target Server Windows feature
to be installed. You can install it by running the following command:

.. code-block:: console

   PS C:\> Add-WindowsFeature
   FS-iSCSITarget-ServerAdd-WindowsFeatureFS-iSCSITarget-Server

.. note::

   The Windows Server installation requires at least 16 GB of disk space. The
   volumes hosted by this node need the extra space.

For ``cinder-volume`` to work properly, you must configure NTP as explained
in :ref:`configure-ntp-windows`.

Next, install the requirements as described in :ref:`windows-requirements`.

Getting the code
~~~~~~~~~~~~~~~~

Git can be used to download the necessary source code. The installer to run Git
on Windows can be downloaded here:

https://git-for-windows.github.io/

Once installed, run the following to clone the OpenStack Block Storage code:

.. code-block:: console

   PS C:\> git.exe clone https://git.openstack.org/openstack/cinder

Configure cinder-volume
~~~~~~~~~~~~~~~~~~~~~~~

The ``cinder.conf`` file may be placed in ``C:\etc\cinder``. Below is a
configuration sample for using the Windows iSCSI Driver:

.. code-block:: ini

   [DEFAULT]
   auth_strategy = keystone
   volume_name_template = volume-%s
   volume_driver = cinder.volume.drivers.windows.WindowsDriver
   glance_api_servers = IP_ADDRESS:9292
   rabbit_host = IP_ADDRESS
   rabbit_port = 5672
   sql_connection = mysql+pymysql://root:Passw0rd@IP_ADDRESS/cinder
   windows_iscsi_lun_path = C:\iSCSIVirtualDisks
   rabbit_password = Passw0rd
   logdir = C:\OpenStack\Log\
   image_conversion_dir = C:\ImageConversionDir
   debug = True

The following table contains a reference to the only driver specific
option that will be used by the Block Storage Windows driver:

.. include:: ../../tables/cinder-windows.inc

Run cinder-volume
-----------------

After configuring ``cinder-volume`` using the ``cinder.conf`` file, you may
use the following commands to install and run the service (note that you
must replace the variables with the proper paths):

.. code-block:: console

   PS C:\> python $CinderClonePath\setup.py install
   PS C:\> cmd /c C:\python27\python.exe c:\python27\Scripts\cinder-volume" --config-file $CinderConfPath
