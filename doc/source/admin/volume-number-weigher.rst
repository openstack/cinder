.. _volume_number_weigher:

=======================================
Configure and use volume number weigher
=======================================

OpenStack Block Storage enables you to choose a volume back end according
to ``free_capacity`` and ``allocated_capacity``. The volume number weigher
feature lets the scheduler choose a volume back end based on its volume
number in the volume back end. This can provide another means to improve
the volume back ends' I/O balance and the volumes' I/O performance.

Enable volume number weigher
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To enable a volume number weigher, set the
``scheduler_default_weighers`` to ``VolumeNumberWeigher`` flag in the
``cinder.conf`` file to define ``VolumeNumberWeigher``
as the selected weigher.

Configure multiple-storage back ends
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To configure ``VolumeNumberWeigher``, use ``LVMVolumeDriver``
as the volume driver.

This configuration defines two LVM volume groups: ``stack-volumes`` with
10 GB capacity and ``stack-volumes-1`` with 60 GB capacity.
This example configuration defines two back ends:

.. code-block:: ini

   scheduler_default_weighers=VolumeNumberWeigher
   enabled_backends=lvmdriver-1,lvmdriver-2
   [lvmdriver-1]
   volume_group=stack-volumes
   volume_driver=cinder.volume.drivers.lvm.LVMVolumeDriver
   volume_backend_name=LVM

   [lvmdriver-2]
   volume_group=stack-volumes-1
   volume_driver=cinder.volume.drivers.lvm.LVMVolumeDriver
   volume_backend_name=LVM

Volume type
~~~~~~~~~~~

Define a volume type in Block Storage:

.. code-block:: console

   $ openstack volume type create lvm

Create an extra specification that links the volume type to a back-end name:

.. code-block:: console

   $ openstack volume type set lvm --property volume_backend_name=LVM

This example creates a lvm volume type with
``volume_backend_name=LVM`` as extra specifications.

Usage
~~~~~

To create six 1-GB volumes, run the
:command:`openstack volume create --size 1 --type lvm volume1` command
six times:

.. code-block:: console

   $ openstack volume create --size 1 --type lvm volume1

This command creates three volumes in ``stack-volumes`` and
three volumes in ``stack-volumes-1``.

List the available volumes:

.. code-block:: console

   # lvs
   LV                                          VG              Attr      LSize  Pool Origin Data%  Move Log Copy%  Convert
   volume-3814f055-5294-4796-b5e6-1b7816806e5d stack-volumes   -wi-a----  1.00g
   volume-72cf5e79-99d2-4d23-b84e-1c35d3a293be stack-volumes   -wi-a----  1.00g
   volume-96832554-0273-4e9d-902b-ad421dfb39d1 stack-volumes   -wi-a----  1.00g
   volume-169386ef-3d3e-4a90-8439-58ceb46889d9 stack-volumes-1 -wi-a----  1.00g
   volume-460b0bbb-d8a0-4bc3-9882-a129a5fe8652 stack-volumes-1 -wi-a----  1.00g
   volume-9a08413b-0dbc-47c9-afb8-41032ab05a41 stack-volumes-1 -wi-a----  1.00g
