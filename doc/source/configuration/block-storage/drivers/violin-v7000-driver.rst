===========================================
Violin Memory 7000 Series FSP volume driver
===========================================

The OpenStack V7000 driver package from Violin Memory adds Block Storage
service support for Violin 7300 Flash Storage Platforms (FSPs) and 7700 FSP
controllers.

The driver package release can be used with any OpenStack Liberty deployment
for all 7300 FSPs and 7700 FSP controllers running Concerto 7.5.3 and later
using Fibre Channel HBAs.

System requirements
~~~~~~~~~~~~~~~~~~~

To use the Violin driver, the following are required:

- Violin 7300/7700 series FSP with:

  - Concerto OS version 7.5.3 or later

  - Fibre channel host interfaces

- The Violin block storage driver: This driver implements the block storage API
  calls. The driver is included with the OpenStack Liberty release.

- The vmemclient library: This is the Violin Array Communications library to
  the Flash Storage Platform through a REST-like interface.  The client can be
  installed using the python 'pip' installer tool.  Further information on
  vmemclient can be found on `PyPI
  <https://pypi.python.org/pypi/vmemclient/>`__.

  .. code-block:: console

     pip install vmemclient

Supported operations
~~~~~~~~~~~~~~~~~~~~

- Create, delete, attach, and detach volumes.

- Create, list, and delete volume snapshots.

- Create a volume from a snapshot.

- Copy an image to a volume.

- Copy a volume to an image.

- Clone a volume.

- Extend a volume.

.. note::

   Listed operations are supported for thick, thin, and dedup luns,
   with the exception of cloning. Cloning operations are supported only
   on thick luns.

Driver configuration
~~~~~~~~~~~~~~~~~~~~

Once the array is configured as per the installation guide, it is simply a
matter of editing the cinder configuration file to add or modify the
parameters. The driver currently only supports fibre channel configuration.

Fibre channel configuration
---------------------------

Set the following in your ``cinder.conf`` configuration file, replacing the
variables using the guide in the following section:

.. code-block:: ini

   volume_driver = cinder.volume.drivers.violin.v7000_fcp.V7000FCPDriver
   volume_backend_name = vmem_violinfsp
   extra_capabilities = VMEM_CAPABILITIES
   san_ip = VMEM_MGMT_IP
   san_login = VMEM_USER_NAME
   san_password = VMEM_PASSWORD
   use_multipath_for_image_xfer = true

Configuration parameters
------------------------

Description of configuration value placeholders:

VMEM_CAPABILITIES
    User defined capabilities, a JSON formatted string specifying key-value
    pairs (string value). The ones particularly supported are
    ``dedup`` and ``thin``. Only these two capabilities are listed here in
    ``cinder.conf`` file, indicating this backend be selected for creating
    luns which have a volume type associated with them that have ``dedup``
    or ``thin`` extra_specs specified. For example, if the FSP is configured
    to support dedup luns, set the associated driver capabilities
    to: {"dedup":"True","thin":"True"}.

VMEM_MGMT_IP
    External IP address or host name of the Violin 7300 Memory Gateway.  This
    can be an IP address or host name.

VMEM_USER_NAME
    Log-in user name for the Violin 7300 Memory Gateway or 7700 FSP controller.
    This user must have administrative rights on the array or controller.

VMEM_PASSWORD
    Log-in user's password.
