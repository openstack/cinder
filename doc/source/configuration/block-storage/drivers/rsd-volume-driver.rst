====================================
Intel Rack Scale Design (RSD) driver
====================================

The Intel Rack Scale Design volume driver is a block storage driver providing
NVMe-oF support for RSD storage.

System requirements
~~~~~~~~~~~~~~~~~~~

To use the RSD driver, the following requirements are needed:

* The driver only supports RSD API at version 2.4 or later.
* The driver requires rsd-lib.
* ``cinder-volume`` should be running on one of the composed node in RSD, and
  have access to the PODM url.
* All the ``nova-compute`` services should be running on the composed nodes in
  RSD.
* All the ``cinder-volume`` and ``nova-compute`` nodes should have installed
  ``dmidecode`` and the latest ``nvme-cli`` with connect/disconnect
  subcommands.

Supported operations
~~~~~~~~~~~~~~~~~~~~

* Create, delete volumes.
* Attach, detach volumes.
* Copy an image to a volume.
* Copy a volume to an image.
* Create, delete snapshots.
* Create a volume from a snapshot.
* Clone a volume.
* Extend a volume.
* Get volume statistics.

Configuration
~~~~~~~~~~~~~

On ``cinder-volume`` nodes, using the following configurations in your
``/etc/cinder/cinder.conf``:

.. code-block:: ini

   volume_driver = cinder.volume.drivers.rsd.RSDDriver

The following table contains the configuration options supported by the
RSD driver:

.. config-table::
   :config-target: RSD

   cinder.volume.drivers.rsd
