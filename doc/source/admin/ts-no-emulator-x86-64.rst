=========================================
Cannot find suitable emulator for x86_64
=========================================

Problem
~~~~~~~

When you attempt to create a VM, the error shows the VM is in the
``BUILD`` then ``ERROR`` state.

Solution
~~~~~~~~

On the KVM host, run :command:`cat /proc/cpuinfo`. Make sure the ``vmx`` or
``svm`` flags are set.

Follow the instructions in the `Enable KVM
<https://docs.openstack.org/ocata/config-reference/compute/hypervisor-kvm.html#enable-kvm>`__ section in the OpenStack Configuration Reference to enable hardware
virtualization support in your BIOS.
