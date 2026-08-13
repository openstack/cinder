=====================
HPE Alletra MP Driver
=====================

The HPE Alletra MP driver provides OpenStack Compute instances
with access to HPE Alletra MP Storage system.

HPE Alletra MP Storage system can be used with iSCSI, FC and
NVME TCP connections.


System requirements
~~~~~~~~~~~~~~~~~~~

To use HPE Alletra MP driver, following are pre-requisites on
storage system:

* HPE Alletra MP Operating System software version 10.5.0 or higher

* Web Services API Server must be enabled and running

* One Common Provisioning Group (CPG)

Additionally ``hpe-storage-flowkit-py`` package should be installed from PyPI


Supported operations
~~~~~~~~~~~~~~~~~~~~

- Create, list, delete, attach, and detach volumes
- Create, list and delete volume snapshots
- Create a volume from a snapshot
- Copy an image to a volume
- Copy a volume to an image
- Clone volume
- Extend volume
- Migrate volume
- Retype volume
- Volume Manage/Unmanage
- Snapshot Manage/Unmanage
- Replicate volume
- Create, delete, update volume group
- Create and delete snapshot group
- Volume Compression


Volume type support includes the ability to set the
following capabilities in the OpenStack Block Storage API
``cinder.api.contrib.types_extra_specs`` volume type extra specs extension
module:

* ``hpe3par:persona``

* ``hpe3par:provisioning``

* ``hpe3par:compression``

To work with the default filter scheduler, the key values are case sensitive
and scoped with ``hpe3par:``. For information about how to set the key-value
pairs and associate them with a volume type, run the following command:

.. code-block:: console

   $ openstack help volume type

If volume types are not used or a particular key is not set for a volume type,
the following defaults are used:

* ``hpe3par:persona`` - Defaults to the ``2 - Generic-ALUA`` persona. The
  valid values are:

  * ``1 - Generic``
  * ``2 - Generic-ALUA``
  * ``3 - Generic-legacy``
  * ``4 - HPUX-legacy``
  * ``5 - AIX-legacy``
  * ``6 - EGENERA``
  * ``7 - ONTAP-legacy``
  * ``8 - VMware``
  * ``9 - OpenVMS``
  * ``10 - HPUX``
  * ``11 - WindowsServer``

* ``hpe3par:provisioning`` - the valid values are ``thin`` (default)
  and ``dedup``.

* ``hpe3par:compression`` -  volume compression, which can be turned on and
  off (default) by setting the value to ``true`` or ``false`` (default).

.. warning::

   While creating volume on HPE Alletra MP storage system,
   only below two combinations are supported. If any other combination is used,
   then volume is not created.

   * thin volume: provisioning = ``thin`` and compression = ``false``
   * DECO volume: provisioning = ``dedup`` and compression = ``true``


Configure Alletra MP driver
~~~~~~~~~~~~~~~~~~~~~~~~~~~

This section details the steps required to configure the Alletra MP
cinder driver.

#. On the HPE Alletra MP storage system, verify that the Web Services API
   server is enabled and running

   a. Log onto the HPE Alletra MP storage system
      with administrator access.

      .. code-block:: console

         $ ssh username@<HPE storage system IP Address>

   b. View the current state of the Web Services API Server.

      .. code-block:: console

         $ showwsapi
         -Service- -State- HTTPS_Port -Version- -----------API_URL-----------
         Enabled   Active         443 1.15.0    https://10.1.2.3/api/v1

   c. If the Web Services API Server is disabled, start it.

      .. code-block:: console

         $ startwsapi


#. If you are not using an existing CPG, create a CPG on the HPE
   Alletra MP storage system to be used as the default location
   for creating volumes.


#. Install the ``hpe-storage-flowkit-py`` Python package on the OpenStack system

   .. code-block:: console

      $ pip install hpe-storage-flowkit-py


#. In the ``cinder.conf`` configuration file under the ``[DEFAULT]``
   section, set the enabled_backends parameter.

   .. code-block:: ini

       [DEFAULT]
       enabled_backends = AlletraMP


#. Add a backend group section for the backend group specified
   in the enabled_backends parameter.

#. In the newly created backend group section, set the
   following configuration options:

   .. code-block:: ini

      [AlletraMP]
      # Management IP of storage array
      san_ip = 10.1.2.3

      # Management username of storage array
      san_login = username

      # Management password of storage array
      san_password = password

      # WSAPI Server URL
      hpe3par_api_url = https://10.1.2.3/api/v1

      # WSAPI V3 Server URL
      hpe_api_url_v3 = https://10.1.2.3/api/v3

      # Alletra MP username with the 'edit' role
      hpe3par_username = username

      # Alletra MP password for the user specified in hpe3par_username
      hpe3par_password = password

      # Enable debug logs
      hpe3par_debug = True

      # CPG to use for volumes
      hpe3par_cpg = OpenStackCPG

      # Backend name
      volume_backend_name = AlletraMP

      # driver path: either one of below

      # FC driver path
      volume_driver = cinder.volume.drivers.hpe.alletramp_driver.HPEAlletraMPFCDriver

      # iSCSI driver path
      # If iSCSI driver is enabled then,
      # values for hpe3par_iscsi_ips should also be set
      volume_driver = cinder.volume.drivers.hpe.alletramp_driver.HPEAlletraMPISCSIDriver

      # hpe3par_iscsi_ips = 172.28.1.1,172.28.2.2

      # NVMe TCP driver path
      # If NVMe TCP driver is enabled then,
      # values for hpe3par_nvme_ips should also be set
      volume_driver = cinder.volume.drivers.hpe.alletramp_driver.HPEAlletraMPNVMETCPDriver

      hpe3par_nvme_ips = 172.28.3.3,172.28.4.4


