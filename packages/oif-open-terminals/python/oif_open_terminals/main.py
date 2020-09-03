# -*- mode: python; python-indent: 4 -*-
import threading
import traceback

import ncs
from ncs.dp import Action
_ncs = __import__('_ncs') # pylint: disable=invalid-name


OUTPUT = '''Retreiving components in a background thread...
Use the following CLI to check the status:\n'''
CLI = 'show openconfig-cache device {} {} fetch-status\n'


class GetComponentsThread(threading.Thread):
    def __init__(self, log, username, device_name):
        super(GetComponentsThread, self).__init__()
        self.username = username
        self.device_name = device_name
        self.log = log
        self.components_dict = {}

    def read_live_components(self, root):
        device = root.devices.device[self.device_name]
        for live_component in device.live_status.\
                              oc_platform__components.component:

            component = get_values(live_component.state, [
                'parent', 'type', 'location', 'description', 'mfg-name',
                'software-version', 'serial-no', 'part-no',
                'removable', 'oper-status', 'used-power'])

            component['subcomponents'] = [
                subcomponent.name for subcomponent in
                live_component.subcomponents.subcomponent
            ]

            if 'type' not in component:
                line_port = live_component.oc_opt_term__optical_channel.\
                            config.line_port
                if line_port:
                    component['type'] = 'OPTICAL_CHANNEL'
                    component['line-port'] = line_port

            self.components_dict[live_component.name] = component

        for channel in device.live_status.oc_opt_term__terminal_device.\
                       logical_channels.channel:

            transceiver = channel.ingress.state.transceiver
            if transceiver and transceiver in self.components_dict:
                self.components_dict[transceiver][
                    'logical-channel'] = channel.index

            for assignment in channel.logical_channel_assignments.assignment:
                optical_channel = assignment.config.optical_channel
                if optical_channel and optical_channel in self.components_dict:
                    self.components_dict[optical_channel][
                        'logical-channel'] = channel.index

    def write_component_cache(self, root):
        device = root.openconfig_cache.device.create(self.device_name)
        del device.components.component

        for component_name, component_dict in self.components_dict.items():
            component = device.components.component.create(component_name)
            for key, value in component_dict.items():
                component[key] = value

    def set_status(self, status):
        with ncs.maapi.single_write_trans(self.username, 'python') as th:
            th.set_elem(status,
                        f'/openconfig-cache/device{{{self.device_name}}}'
                        f'/components/fetch-status')
            th.apply()

    def run(self):
        try:
            self.log.info('get-components device name: ', self.device_name)
            self.set_status('in-progress')

            with ncs.maapi.single_read_trans(self.username, 'python') as th:
                self.read_live_components(ncs.maagic.get_root(th))

            with ncs.maapi.single_write_trans(self.username, 'python') as th:
                self.write_component_cache(ncs.maagic.get_root(th))
                th.apply()

            self.set_status('done')

        except Exception as err:
            self.log.error(err)
            self.log.error(traceback.format_exc())
            self.set_status('error')
            raise


# Helper to get multiple leafs values from a node in one request instead of
# using maagic node attributes which cause a seperate request to the device
# for each leaf.
def get_values(maagic_node, tag_names):
    # pylint: disable=protected-access
    cs_node = maagic_node._cs_node.children()
    tag_values = []
    values_dict = {}
    cs_nodes = {}
    while cs_node:
        if _ncs.hash2str(cs_node.tag()) in tag_names:
            tag_values.append(_ncs.TagValue(tag=cs_node.tag(), ns=cs_node.ns()))
            cs_nodes[cs_node.tag()] = cs_node
        cs_node = cs_node.next()

    for tag_value in maagic_node._backend.trans.get_values(
            tag_values, maagic_node._path):
        if tag_value.v.confd_type() != _ncs.C_NOEXISTS:
            values_dict[_ncs.hash2str(tag_value.tag)] = tag_value.v.val2str(
                cs_nodes[tag_value.tag])

    return values_dict

def copy_values(from_node, to_node, tag_names):
    for key, value in get_values(from_node, tag_names).items():
        to_node[key] = value

class GetOperationalModesThread(threading.Thread):
    def __init__(self, log, username, device_name):
        super(GetOperationalModesThread, self).__init__()
        self.username = username
        self.device_name = device_name
        self.log = log
        self.modes = []

    def read_live_modes(self, root):
        self.modes = [
            get_values(live_mode.state, ['mode-id', 'description', 'vendor-id'])
            for live_mode in root.devices.device[self.device_name].live_status.\
            oc_opt_term__terminal_device.operational_modes.mode]

    def write_modes_cache(self, root):
        device = root.openconfig_cache.device[self.device_name]
        del device.operational_modes.mode
        for mode_dict in self.modes:
            mode = device.operational_modes.mode.create(mode_dict.pop('mode-id'))
            for key, value in mode_dict.items():
                mode[key] = value

    def set_status(self, status):
        with ncs.maapi.single_write_trans(self.username, 'python') as th:
            th.set_elem(status,
                        f'/openconfig-cache/device{{{self.device_name}}}'
                        f'/operational-modes/fetch-status')
            th.apply()

    def run(self):
        try:
            self.log.info('get-operational-modes device name: ',
                          self.device_name)
            self.set_status('in-progress')

            with ncs.maapi.single_read_trans(self.username, 'python') as th:
                self.read_live_modes(ncs.maagic.get_root(th))

            with ncs.maapi.single_write_trans(self.username, 'python') as th:
                self.write_modes_cache(ncs.maagic.get_root(th))
                th.apply()

            self.set_status('done')

        except Exception as err:
            self.log.error(err)
            self.log.error(traceback.format_exc())
            self.set_status('error')
            raise


class Inventory():
    def __init__(self, log, username, device_name):
        self.log = log
        self.username = username
        self.device_name = device_name

        self.components_dict = {}
        self.live_components = None
        self.live_channels = None

    def init_transaction(self, root):
        live_status = root.devices.device[self.device_name].live_status

        self.live_components = live_status.oc_platform__components.component
        self.live_channels = live_status.oc_opt_term__terminal_device.\
                             logical_channels.channel

        _ = next(iter(self.live_components), None)
        _ = next(iter(self.live_channels), None)


    def read_component_cache(self, root):
        device = root.openconfig_cache.device[self.device_name]
        for component in device.components.component:
            self.components_dict[component.name] = {
                'type': component.type,
                'subcomponents': component.subcomponents.as_list(),
                'oper-status': component.oper_status,
                'line-port': component.line_port,
                'logical-channel': component.logical_channel
                }

        for component_name in self.components_dict:
            for subcomponent_name in self.components_dict[component_name][
                    'subcomponents']:
                if subcomponent_name in self.components_dict:
                    self.components_dict[subcomponent_name][
                        'parent'] = component_name

    def find_children(self, parent, type):
        components = []

        if parent:
            if parent in self.components_dict:
                components = self.components_dict[parent]['subcomponents']
        else:
            components = self.components_dict.keys()

        children = [component for component in components
                    if component in self.components_dict and
                    str(self.components_dict[component]['type']).endswith(type)]

        return children or [
            child for component in components
            for child in self.find_children(component, type)]

    def populate_logical_channel(self, channel, channel_index):
        live_channel = self.live_channels[channel_index]
        copy_values(live_channel.config, channel, [
            'description', 'logical-channel-type',
            'rate-class', 'trib-protocol'])

    def add_logical_channel(self, channel_index, channel_list):
        live_channel = self.live_channels[channel_index]

        channel = channel_list.create(channel_index)
        self.populate_logical_channel(channel, channel_index)

        for assignment in live_channel.logical_channel_assignments.assignment:
            values = get_values(assignment.config, [
                'logical-channel', 'optical-channel', 'allocation'])

            if values.get('optical-channel'):
                channel.q_value = live_channel.otn.state.q_value.instant

            next_index = values.get('logical-channel')
            next_channel = channel.next_channel.create(
                next_index or values['optical-channel'])
            next_channel.allocation = values.get('allocation')

            if next_index:
                self.add_logical_channel(next_index, channel_list)


    def find_optical_channel(self, port_name, linecard_name):
        optical_channel_name = next((
            component_name
            for component_name, component in self.components_dict.items()
            if component['type'] == 'OPTICAL_CHANNEL' and
            component['line-port'] == port_name), None)

        if not optical_channel_name:
            port_parent = self.components_dict[port_name]['parent']
            optical_channel_name = next(iter(self.find_children(
                port_parent if port_parent != linecard_name
                else port_name, 'OPTICAL_CHANNEL')), None)

        return optical_channel_name

    def process_optical_channel(self, port, optical_channel_name):
        optical_channel = port.terminal_line.optical_channel
        optical_channel.name = optical_channel_name

        live_channel = self.live_components[
            optical_channel_name].optical_channel
        copy_values(live_channel.config, optical_channel, [
            'frequency', 'operational-mode', 'target-output-power'])

        logical_channel_index = self.components_dict[
            optical_channel_name]['logical-channel']

        if logical_channel_index:
            channel = optical_channel.logical_channel
            channel.index = logical_channel_index

            self.populate_logical_channel(
                channel, logical_channel_index)

            live_channel = self.live_channels[logical_channel_index]
            for assignment in live_channel.\
                              logical_channel_assignments.assignment:

                values = get_values(assignment.config, [
                    'optical-channel', 'allocation'])
                if values.get('optical-channel') == optical_channel_name:
                    channel.allocation = values.get('allocation')
                    channel.q_value = live_channel.otn.state.q_value.instant

    def process_transceiver(self, port, transceiver_name):
        transceiver = port.terminal_client.transceiver
        transceiver.name = transceiver_name
        transceiver.oper_status = self.components_dict[transceiver_name].get(
            'oper-status')

        for physical_channel in self.live_components[
                transceiver_name].transceiver.physical_channels.channel:
            transceiver.physical_channels.channel.create(physical_channel.index)

        logical_channel = self.components_dict[
            transceiver_name]['logical-channel']
        if logical_channel:
            self.add_logical_channel(logical_channel,
                                     transceiver.logical_channels.channel)

    def process_components(self, device):
        for chassis_name in self.find_children(None, 'CHASSIS'):
            chassis = device.inventory.chassis.create(chassis_name)

            for linecard_name in self.find_children(chassis_name, 'LINECARD'):
                linecard = chassis.linecards.linecard.create(linecard_name)
                copy_values(self.live_components[linecard_name].
                            oc_linecard__linecard.state, linecard,
                            ['power-admin-state', 'slot-id'])

                for port_name in self.find_children(linecard_name, 'PORT'):
                    port = linecard.ports.port.create(port_name)

                    optical_channel_name = self.find_optical_channel(
                        port_name, linecard_name)

                    if optical_channel_name:
                        self.process_optical_channel(port, optical_channel_name)

                    transceiver_name = next(iter(self.find_children(
                        port_name, 'TRANSCEIVER')), None)
                    if transceiver_name:
                        self.process_transceiver(port, transceiver_name)

            for fan_name in self.find_children(chassis_name, 'FAN'):
                chassis.fans.fan.create(fan_name)

            for psu_name in self.find_children(chassis_name, 'POWER_SUPPLY'):
                chassis.psus.psu.create(psu_name)

    def generate(self):
        self.log.info('generate-inventory device name: ', self.device_name)
        with ncs.maapi.single_read_trans(self.username, 'python') as th:
            root = ncs.maagic.get_root(th)
            if self.device_name not in root.openconfig_cache.device:
                return
            self.read_component_cache(root)

        with ncs.maapi.single_write_trans(self.username, 'python') as th:
            root = ncs.maagic.get_root(th)
            self.init_transaction(root)

            device = root.openconfig_cache.device[self.device_name]
            del device.inventory.chassis

            self.process_components(device)
            th.apply()


class GetComponentsAction(Action):
    @Action.action
    def cb_action(self, uinfo, name, kp, input, output, trans):
        self.log.info('action name: ', name)
        device_name = kp[1][0].as_pyval()
        GetComponentsThread(self.log, uinfo.username, device_name).start()
        output.status = OUTPUT + CLI.format(device_name, 'components')


class GetOperationalModesAction(Action):
    @Action.action
    def cb_action(self, uinfo, name, kp, input, output, trans):
        self.log.info('action name: ', name)
        device_name = kp[1][0].as_pyval()
        GetOperationalModesThread(self.log, uinfo.username, device_name).start()
        output.status = OUTPUT + CLI.format(device_name, 'operational-modes')


class GenerateInventoryAction(Action):
    @Action.action
    def cb_action(self, uinfo, name, kp, input, output, trans):
        self.log.info('action name: ', name)
        inventory = Inventory(self.log, uinfo.username, kp[1][0].as_pyval())
        inventory.generate()


class GenerateOpenConfigCache(Action):
    def generate_cache(self, device_name, username, get_components,
                       get_operational_modes, generate_inventory):
        try:
            if get_components:
                get_components_thread = GetComponentsThread(
                    self.log, username, device_name)
                get_components_thread.start()
                get_components_thread.join()

            if get_operational_modes:
                get_modes_thread = GetOperationalModesThread(
                    self.log, username, device_name)
                get_modes_thread.start()
                get_modes_thread.join()

            if generate_inventory:
                inventory = Inventory(self.log, username, device_name)
                inventory.generate()

        except Exception as err:
            self.log.error(err)
            self.log.error(traceback.format_exc())
            raise

    @Action.action
    def cb_action(self, uinfo, name, kp, input, output, trans):
        self.log.info('action name: ', name)
        device_name = kp[0][0].as_pyval()

        if (input.get_components or input.get_operational_modes or
                input.generate_inventory):
            thread = threading.Thread(target=self.generate_cache, args=(
                device_name, uinfo.username, input.get_components,
                input.get_operational_modes, input.generate_inventory))
            thread.start()

            message = OUTPUT
            if input.get_components:
                message += CLI.format(device_name, 'components')
            if input.get_operational_modes:
                message += CLI.format(device_name, 'operational-modes')

            output.message = message


# ---------------------------------------------
# COMPONENT THREAD THAT WILL BE STARTED BY NCS.
# ---------------------------------------------
class Main(ncs.application.Application):
    def setup(self):
        # The application class sets up logging for us. It is accessible
        # through 'self.log' and is a ncs.log.Log instance.
        self.log.info('Main RUNNING')

        # When using actions, this is how we register them:
        #
        self.register_action('get-device-components', GetComponentsAction)
        self.register_action('get-device-operational-modes',
                             GetOperationalModesAction)
        self.register_action('generate-device-inventory',
                             GenerateInventoryAction)
        self.register_action('generate-openconfig-cache',
                             GenerateOpenConfigCache)

        # If we registered any callback(s) above, the Application class
        # took care of creating a daemon (related to the service/action point).

        # When this setup method is finished, all registrations are
        # considered done and the application is 'started'.

    def teardown(self):
        # When the application is finished (which would happen if NCS went
        # down, packages were reloaded or some error occurred) this teardown
        # method will be called.

        self.log.info('Main FINISHED')
