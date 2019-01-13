=================================
Capacity based quality of service
=================================

In many environments, the performance of the storage system which Cinder
manages scales with the storage space in the cluster.  For example, a Ceph RBD
cluster could have a capacity of 10,000 IOPs and 1000 GB storage.  However, as
the RBD cluster scales to 2000 GB, the IOPs scale to 20,000 IOPs.

Basic QoS allows you to define hard limits for volumes, however, if you have a
limit of 1000 IOPs for a volume and you have a user which creates 10x 1GB
volumes with 1000 IOPs (in a cluster with 1000GB storage and 10,000 IOPs),
you're not able to guarantee the quality of service without having to add
extra capacity (which will go un-used).  The inverse can be problematic, if a
user creates a 1000GB volume with 1000 IOPs, leaving 9000 un-used IOPs.

Capacity based quality of service allows you to multiply the quality of service
values by the size of the volume, which will allow you to efficiently use the
storage managed by Cinder.  In some cases, it will 'force' the user to
provision a larger volume than they need to get the IOPs they need, but that
extra space would have gone un-used if they didn't use it in order to deliver
the quality of service.

There are currently 6 options to control capacity based quality of service
which values should be fairly self explanatory:

* `read_iops_sec_per_gb`
* `write_iops_sec_per_gb`
* `total_iops_sec_per_gb`
* `read_bytes_sec_per_gb`
* `write_bytes_sec_per_gb`
* `total_bytes_sec_per_gb`

In addition, there are 6 more options which allow you to control the minimum
possible value.  This can be useful in cases where a user creates a volume that
is very small and ends up with an unusable volume because of performance.

* `read_iops_sec_per_gb_min`
* `write_iops_sec_per_gb_min`
* `total_iops_sec_per_gb_min`
* `read_bytes_sec_per_gb_min`
* `write_bytes_sec_per_gb_min`
* `total_bytes_sec_per_gb_min`

Capacity based options might be used in conjunction with basic options,
like `*_sec_max`, in order to set upper limits for volumes. This may be useful
for large volumes, which may consume all storage performance.

For example, in order to create a QoS with 30 IOPs total writes per GB and
a throughput of 1MB per GB, you might use the Cinder client in the following
way:

.. code-block:: console

   $ cinder qos-create high-iops consumer="front-end" \
     total_iops_sec_per_gb=30 total_bytes_sec_per_gb=1048576
   +----------+--------------------------------------+
   | Property | Value                                |
   +----------+--------------------------------------+
   | consumer | front-end                            |
   | id       | f448f61c-4238-4eef-a93a-2024253b8f75 |
   | name     | high-iops                            |
   | specs    | total_iops_sec_per_gb : 30           |
   |          | total_bytes_sec_per_gb : 1048576     |
   +----------+--------------------------------------+

Once this is done, you can associate this QoS with a volume type by using
the `qos-associate` Cinder client command.

.. code-block:: console

   $ cinder qos-associate <qos-id> <volume-type-id>

You can now create a new volume and attempt to attach it to a consumer such
as Nova.  If you login to a Nova compute host, you'll be able to see the
new calculated limits when checking the XML definition of the virtual machine
with `virsh dumpxml`.
