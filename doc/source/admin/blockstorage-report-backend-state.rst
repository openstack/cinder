====================================
Report backend state in service list
====================================

Currently, Cinder couldn't report backend state to service, operators only
know that cinder-volume process is up, but isn't aware of whether the backend
storage device is ok. Users still can create volume and go to fail over and
over again. To make maintenance easier, operator could query storage device
state via service list and fix the problem more quickly. If device state is
*down*, that means volume creation will fail.

To do so, use the Block Storage API: service list to get the backend state.
Run this command:

.. code-block:: console

   $ openstack volume service list

Add backend_state: up/down into response body of service list. This feature
is supported after microversion 3.49.
