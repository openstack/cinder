.. _cinder-verify:

Verify Cinder operation
~~~~~~~~~~~~~~~~~~~~~~~

Verify operation of the Block Storage service.

.. note::

   Perform these commands on the controller node.

#. Source the ``admin`` credentials to gain access to
   admin-only CLI commands:

   .. code-block:: console

      $ . admin-openrc

   .. end

#. List service components to verify successful launch of each process:

   .. code-block:: console

      $ openstack volume service list

      +------------------+------------+------+---------+-------+----------------------------+
      | Binary           | Host       | Zone | Status  | State | Updated_at                 |
      +------------------+------------+------+---------+-------+----------------------------+
      | cinder-scheduler | controller | nova | enabled | up    | 2016-09-30T02:27:41.000000 |
      | cinder-volume    | block@lvm  | nova | enabled | up    | 2016-09-30T02:27:46.000000 |
      +------------------+------------+------+---------+-------+----------------------------+


   .. end
