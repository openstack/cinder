=============================
Open-E JovianDSS iSCSI driver
=============================

The ``JovianISCSIDriver`` allows usage of Open-E JovianDSS
Data Storage Solution to be used as Block Storage in OpenStack deployments.

Supported operations
~~~~~~~~~~~~~~~~~~~~

- Create, delete, attach, and detach volumes.
- Create, list, and delete volume snapshots.
- Create a volume from a snapshot.
- Copy an image to a volume.
- Copy a volume to an image.
- Clone a volume.
- Extend a volume.
- Migrate a volume with back-end assistance.


Configuring
~~~~~~~~~~~

Edit with your favourite editor Cinder config file. It can be found at
/etc/cinder/cinder.conf

Add the field enabled\_backends with value open-e-jdss-0:

::

    enabled_backends = open-e-jdss-0

Provide settings to Open-E JovianDSS driver by adding 'open-e-jdss-0'
description:

::

    [open-e-jdss-0]
    backend_name = Open-EJovianDSS
    chap_password_len = 14
    driver_use_ssl = True
    driver_ssl_cert_verify = True
    driver_ssl_cert_path = /etc/cinder/jdss.crt
    iscsi_target_prefix = iqn.2016-04.com.open-e.cinder:
    jovian_pool = Pool-0
    jovian_block_size = 128K
    san_api_port = 82
    target_port = 3260
    volume_driver = cinder.volume.drivers.open_e.iscsi.JovianISCSIDriver
    san_hosts = 192.168.0.40
    san_login = admin
    san_password = admin
    san_thin_provision = True

.. list-table:: **Open-E JovianDSS configuration options**
   :header-rows: 1

   * - Option
     - Default value
     - Description
   * - ``backend_name``
     - Open-EJovianDSS
     - Name of the back end
   * - ``chap_password_len``
     - 12
     - Length of the unique generated CHAP password.
   * - ``driver_use_ssl``
     - True
     - Use SSL to send requests to Open-E JovianDSS[1]
   * - ``driver_ssl_cert_verify``
     - True
     - Verify authenticity of Open-E JovianDSS[1] certificate
   * - ``driver_ssl_cert_path``
     - None
     - Path to the Open-E JovianDSS[1] certificate for verification
   * - ``iscsi_target_prefix``
     - iqn.2016-04.com.open-e:01:cinder-
     - Prefix that will be used to form target name for volume
   * - ``jovian_pool``
     - Pool-0
     - Pool name that is going to be used. Must be created in [2]
   * - ``jovian_block_size``
     - 128K
     - Block size for newly created volumes
   * - ``san_api_port``
     - 82
     - Rest port according to the settings in [1]
   * - ``target_port``
     - 3260
     - Port for iSCSI connections
   * - ``volume_driver``
     -
     - Location of the driver source code
   * - ``san_hosts``
     -
     - Comma separated list of IP address of the Open-E JovianDSS
   * - ``san_login``
     - admin
     - Must be set according to the settings in [1]
   * - ``san_password``
     - admin
     - Open-E Jovian DSS password [1], **should be changed**
   * - ``san_thin_provision``
     - False
     - Using thin provisioning for new volumes


1. Open-E JovianDSS Web interface/System Settings/REST Access

2. Pool can be created by going to Open-E JovianDSS Web interface/Storage

.. _interface/Storage:

`More info about Open-E JovianDSS <http://blog.open-e.com/?s=how+to>`__


Multiple Pools
~~~~~~~~~~~~~~

In order to add another Open-E JovianDSS Pool, create a copy of
Open-E JovianDSS config in cinder.conf file.

For instance if you want to add ``Pool-1`` located on the same host as
``Pool-0``. You extend ``cinder.conf`` file like:

::

    enabled_backends = open-e-jdss-0, open-e-jdss-1

    [open-e-jdss-0]
    backend_name = open-e-jdss-0
    chap_password_len = 14
    driver_use_ssl = True
    driver_ssl_cert_verify = False
    iscsi_target_prefix = iqn.2016-04.com.open-e.cinder:
    jovian_pool = Pool-0
    jovian_block_size = 128K
    san_api_port = 82
    target_port = 3260
    volume_driver = cinder.volume.drivers.open_e.iscsi.JovianISCSIDriver
    san_hosts = 192.168.0.40
    san_login = admin
    san_password = admin
    san_thin_provision = True

    [open-e-jdss-1]
    backend_name = open-e-jdss-1
    chap_password_len = 14
    driver_use_ssl = True
    driver_ssl_cert_verify = False
    iscsi_target_prefix = iqn.2016-04.com.open-e.cinder:
    jovian_pool = Pool-1
    jovian_block_size = 128K
    san_api_port = 82
    target_port = 3260
    volume_driver = cinder.volume.drivers.open_e.iscsi.JovianISCSIDriver
    san_hosts = 192.168.0.50
    san_login = admin
    san_password = admin
    san_thin_provision = True


HA Cluster
~~~~~~~~~~

To utilize High Availability feature of Open-E JovianDSS:

1. `Guide`_ on configuring Pool to high availability cluster

.. _Guide: https://www.youtube.com/watch?v=juWIQT_bAfM

2. Set ``jovian_hosts`` with list of ``virtual IPs`` associated with this Pool

For instance if you have ``Pool-2`` with 2 virtual IPs 192.168.21.100
and 192.168.31.100 the configuration file will look like:

::

    [open-e-jdss-2]
    backend_name = open-e-jdss-2
    chap_password_len = 14
    driver_use_ssl = True
    driver_ssl_cert_verify = False
    iscsi_target_prefix = iqn.2016-04.com.open-e.cinder:
    jovian_pool = Pool-0
    jovian_block_size = 128K
    san_api_port = 82
    target_port = 3260
    volume_driver = cinder.volume.drivers.open_e.iscsi.JovianISCSIDriver
    san_hosts = 192.168.21.100, 192.168.31.100
    san_login = admin
    san_password = admin
    san_thin_provision = True


Feedback
--------

Please address problems and proposals to andrei.perepiolkin@open-e.com
