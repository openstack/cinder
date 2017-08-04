
.. _fc_zone_manager:

==========================
Fibre Channel Zone Manager
==========================

The Fibre Channel Zone Manager allows FC SAN Zone/Access control
management in conjunction with Fibre Channel block storage. The
configuration of Fibre Channel Zone Manager and various zone drivers are
described in this section.

Configure Block Storage to use Fibre Channel Zone Manager
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If Block Storage is configured to use a Fibre Channel volume driver that
supports Zone Manager, update ``cinder.conf`` to add the following
configuration options to enable Fibre Channel Zone Manager.

Make the following changes in the ``/etc/cinder/cinder.conf`` file.

.. include:: ../tables/cinder-zoning.inc

To use different Fibre Channel Zone Drivers, use the parameters
described in this section.

.. note::

    When multi backend configuration is used, provide the
    ``zoning_mode`` configuration option as part of the volume driver
    configuration where ``volume_driver`` option is specified.

.. note::

    Default value of ``zoning_mode`` is ``None`` and this needs to be
    changed to ``fabric`` to allow fabric zoning.

.. note::

    ``zoning_policy`` can be configured as ``initiator-target`` or
    ``initiator``

Brocade Fibre Channel Zone Driver
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Brocade Fibre Channel Zone Driver performs zoning operations
through HTTP, HTTPS, or SSH.

Set the following options in the ``cinder.conf`` configuration file.

.. include:: ../tables/cinder-zoning_manager_brcd.inc

Configure SAN fabric parameters in the form of fabric groups as
described in the example below:

.. include:: ../tables/cinder-zoning_fabric_brcd.inc

.. note::

    Define a fabric group for each fabric using the fabric names used in
    ``fc_fabric_names`` configuration option as group name.

.. note::

    To define a fabric group for a switch which has Virtual Fabrics
    enabled, include the ``fc_virtual_fabric_id`` configuration option
    and ``fc_southbound_protocol`` configuration option set to ``HTTP``
    or ``HTTPS`` in the fabric group. Zoning on VF enabled fabric using
    ``SSH`` southbound protocol is not supported.

System requirements
-------------------

Brocade Fibre Channel Zone Driver requires firmware version FOS v6.4 or
higher.

As a best practice for zone management, use a user account with
``zoneadmin`` role. Users with ``admin`` role (including the default
``admin`` user account) are limited to a maximum of two concurrent SSH
sessions.

For information about how to manage Brocade Fibre Channel switches, see
the Brocade Fabric OS user documentation.

Cisco Fibre Channel Zone Driver
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Cisco Fibre Channel Zone Driver automates the zoning operations through
SSH. Configure Cisco Zone Driver, Cisco Southbound connector, FC SAN
lookup service and Fabric name.

Set the following options in the ``cinder.conf`` configuration file.

.. code-block:: ini

    [fc-zone-manager]
    zone_driver = cinder.zonemanager.drivers.cisco.cisco_fc_zone_driver.CiscoFCZoneDriver
    fc_san_lookup_service = cinder.zonemanager.drivers.cisco.cisco_fc_san_lookup_service.CiscoFCSanLookupService
    fc_fabric_names = CISCO_FABRIC_EXAMPLE
    cisco_sb_connector = cinder.zonemanager.drivers.cisco.cisco_fc_zone_client_cli.CiscoFCZoneClientCLI

.. include:: ../tables/cinder-zoning_manager_cisco.inc

Configure SAN fabric parameters in the form of fabric groups as
described in the example below:

.. include:: ../tables/cinder-zoning_fabric_cisco.inc

.. note::

    Define a fabric group for each fabric using the fabric names used in
    ``fc_fabric_names`` configuration option as group name.

    The Cisco Fibre Channel Zone Driver supports basic and enhanced
    zoning modes.The zoning VSAN must exist with an active zone set name
    which is same as the ``fc_fabric_names`` option.

System requirements
-------------------

Cisco MDS 9000 Family Switches.

Cisco MDS NX-OS Release 6.2(9) or later.

For information about how to manage Cisco Fibre Channel switches, see
the Cisco MDS 9000 user documentation.
