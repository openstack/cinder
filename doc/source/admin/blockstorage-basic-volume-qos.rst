===============================
Basic volume quality of service
===============================

Basic volume QoS allows you to define hard performance limits for volumes
on a per-volume basis.

Performance parameters for attached volumes are controlled using volume types
and associated extra-specs.

As of the 13.0.0 Rocky release, Cinder supports the following options to
control volume quality of service, the values of which should be fairly
self-explanatory:

* `read_iops_sec`
* `write_iops_sec`
* `total_iops_sec`
* `read_bytes_sec`
* `write_bytes_sec`
* `total_bytes_sec`
* `read_iops_sec_max`
* `write_iops_sec_max`
* `total_iops_sec_max`
* `read_bytes_sec_max`
* `write_bytes_sec_max`
* `total_bytes_sec_max`
* `size_iops_sec`

Note that the `total_*` and `total_*_max` options for both iops and bytes
cannot be used with the equivalent `read` and `write` values.

For example, in order to create a QoS extra-spec with 20000 read IOPs and
10000 write IOPs, you might use the Cinder client in the following way:

.. code-block:: console

   $ cinder qos-create high-iops consumer="front-end" \
     read_iops_sec=20000 write_iops_sec=10000
   +----------+--------------------------------------+
   | Property | Value                                |
   +----------+--------------------------------------+
   | consumer | front-end                            |
   | id       | f448f61c-4238-4eef-a93a-2024253b8f75 |
   | name     | high-iops                            |
   | specs    | read_iops_sec : 20000                |
   |          | write_iops_sec : 10000               |
   +----------+--------------------------------------+

The equivalent OpenStack client command would be:


.. code-block:: console

   $ openstack volume qos create --consumer "front-end" \
     --property "read_iops_sec=20000" \
     --property "write_iops_sec=10000" \
     high-iops

Once this is done, you can associate this QoS with a volume type by using
the `qos-associate` Cinder client command.

.. code-block:: console

   $ cinder qos-associate QOS_ID VOLUME_TYPE_ID

or using the `openstack volume qos associate` OpenStack client command.

.. code-block:: console

   $ openstack volume qos associate QOS_ID VOLUME_TYPE_ID

You can now create a new volume and attempt to attach it to a consumer such
as Nova.  If you login to the Nova compute host, you'll be able to see the
assigned limits when checking the XML definition of the virtual machine
with `virsh dumpxml`.

.. note::

   As of the Nova 18.0.0 Rocky release, front end QoS settings are only
   supported when using the libvirt driver.
