def _stripped_first_line_of(filename):
    with open(filename, 'rb') as f:
        return f.readline().strip()


def get_this_vm_uuid():
    return _stripped_first_line_of('/sys/hypervisor/uuid')
