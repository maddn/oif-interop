#!/usr/bin/env python3
import sys
import os
import ncs


def print_command_and_exit():
    print("""begin command
  modes: oper
  styles: j c i
  cmdpath: show component tree
  help: Display the components cache in a tree view
  more: true
end""")
    sys.exit(0)

def print_usage_and_exit():
    print("""Usage: {0} [--detail]
       {0} --command
       {0} --h

  --h           Display this help and exit
  --command     Display command configuration and exit
  --device      Include location details in output""".format(sys.argv[0]))
    sys.exit(1)


def print_component(name, cache, pad='', is_last=True):
    component_type = cache[name].type.replace('oc-platform-types:', '') if (
        name in cache and cache[name].type) else ''

    print(f'{pad}+--[{component_type}] {name}')

    has_sibling_below = ' ' if is_last else '|'
    indent = f'{pad}{has_sibling_below}   '

    if name in cache:
        subcomponents = cache[name].subcomponents
        for (index, subcomponent) in enumerate(subcomponents.as_list()):
            print_component(subcomponent, cache, indent,
                            index == len(subcomponents) - 1)

def print_component_tree():
    maapi = ncs.maapi.Maapi()
    ncs_maapi_usid = os.environ.get('NCS_MAAPI_USID')

    if ncs_maapi_usid:
        maapi.set_user_session(int(ncs_maapi_usid))
    else:
        maapi.start_user_session('admin', 'python')

    with maapi.start_read_trans() as trans:
        root = ncs.maagic.get_root(trans)

        for device in root.devices.device:
            cache = device.openconfig_cache.components.component

            if cache:
                print(f'Device: {device.name}')
                for component in cache:
                    if str(component.type).endswith('CHASSIS'):
                        print_component(component.name, cache)

def process_args(args):
    if len(args) > 1:
        print_usage_and_exit()

    if len(args) == 1:
        if args[0] == "--command":
            print_command_and_exit()


if __name__ == '__main__':
    process_args(sys.argv[1:])
    print_component_tree()
