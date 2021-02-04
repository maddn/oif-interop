# -*- mode: python; python-indent: 4 -*-
from collections import defaultdict

import ncs
from ncs.dp import Action


# pylint: disable=attribute-defined-outside-init

def check_bad_inventory_id(node):
    for name in node.name:
        if name.value_name == 'INVENTORY_ID':
            if name.value is not None:
                return 0
    return 1

class SipSummary(Action):
    @Action.action
    def cb_action(self, uinfo, name, kp, input, output, trans):
        self.log.info('action name: ', name)
        device_name = str(kp[1][0])

        with ncs.maapi.single_read_trans(uinfo.username, 'python') as th:
            device = ncs.maagic.get_root(th).devices.device[device_name]
            context = device.live_status.tapi_common__context

            # Generate GET for each service-interface-point
            sip_list = [check_bad_inventory_id(sip)
                        for sip in context.service_interface_point]

            output.missing_inventory_id_count = sum(sip_list)
            output.service_interface_point_count = len(sip_list)


def get_topology_list(topology_context):
    if topology_context.nw_topology_service.uuid:
        return [topology.topology_uuid
                for topology in topology_context.nw_topology_service.topology]

    # Not all devices suppport nw-topology-service node, so loop
    # through topology-context/topology list directly
    return [topology.uuid
            for topology in topology_context.topology]


class TopologySummary(Action):
    def process_topology(self, topology):
        output_topology = self.output.topology.create(topology.uuid)

        # Access a leaf-list to force a new GET
        output_topology.link_count = len([
            len(link.layer_protocol_name) for link in topology.link])

        for node in topology.node:
            output_node = output_topology.node.create(node.uuid)
            missing_inventory_id = 0

            # Generate GET for each node
            _ = len(node.layer_protocol_name)

            for onep in node.owned_node_edge_point:
                # Generate GET for each owned-node-edge-point
                _ = len(onep.supported_cep_layer_protocol_qualifier)
                access_port = onep.supporting_access_port.access_port

                if access_port.access_port_uuid:
                    self.access_port_oneps.append((
                        access_port.access_port_uuid, access_port.device_uuid,
                        onep.uuid, node.uuid, topology.uuid))

                missing_inventory_id += check_bad_inventory_id(onep)

            output_node.missing_inventory_id_count = missing_inventory_id
            output_node.owned_node_edge_point_count = len(
                node.owned_node_edge_point)

        output_topology.node_count = len(output_topology.node)

    def write_oneps(self, device):
        access_port_oneps = (device.tapi_ols__tapi_context.topology.
                             access_port_owned_node_edge_point)
        access_port_oneps.delete()

        for (access_port_uuid, device_uuid,
             onep_uuid, node_uuid, topology_uuid) in self.access_port_oneps:
            access_port_onep = access_port_oneps.create(access_port_uuid)
            access_port_onep.device_uuid = device_uuid
            access_port_onep.owned_node_edge_point_uuid = onep_uuid
            access_port_onep.node_uuid = node_uuid
            access_port_onep.topology_uuid = topology_uuid

    @Action.action
    def cb_action(self, uinfo, name, kp, input, output, trans):
        self.log.info('action name: ', name)
        self.output = output
        self.access_port_oneps = []
        device_name = str(kp[1][0])

        with ncs.maapi.single_read_trans(uinfo.username, 'python') as th:
            device = ncs.maagic.get_root(th).devices.device[device_name]
            topology_context = (device.live_status.tapi_common__context.
                                tapi_topology__topology_context)

            for topology_uuid in get_topology_list(topology_context):
                self.process_topology(topology_context.topology[topology_uuid])

            output.topology_count = len(output.topology)

        with ncs.maapi.single_write_trans(uinfo.username, 'python') as th:
            device = ncs.maagic.get_root(th).devices.device[device_name]
            self.write_oneps(device)
            th.apply()


class ConnectivitySummary(Action):
    @Action.action
    def cb_action(self, uinfo, name, kp, input, output, trans):
        self.log.info('action name: ', name)
        device_name = str(kp[1][0])

        with ncs.maapi.single_read_trans(uinfo.username, 'python') as th:
            connectivity_services = (ncs.maagic.get_root(th).devices.device[
                device_name].live_status.tapi_common__context.
                tapi_connectivity__connectivity_context.connectivity_service)

            # Need second transaction here because TTL is added for connection
            # list by GET on connectivity-context.
            with ncs.maapi.single_read_trans(uinfo.username, 'python') as th2:
                connections = (ncs.maagic.get_root(th2).devices.device[
                    device_name].live_status.tapi_common__context.
                    tapi_connectivity__connectivity_context.connection)

                for connectivity_service in connectivity_services:
                    # Generate a GET for each corresponding connection
                    output.connectivity_service.create(connectivity_service.uuid
                        ).connection_count = len([
                            connections[connection.connection_uuid].uuid
                            for connection in connectivity_service.connection])

            output.connectivity_service_count = len(connectivity_services)


class ConnectivityServiceConnections(Action):
    @Action.action
    def cb_action(self, uinfo, name, kp, input, output, trans):
        self.log.info('action name: ', name)
        device_name = str(kp[1][0])

        with ncs.maapi.single_read_trans(uinfo.username, 'python') as th:
            device = ncs.maagic.get_root(th).devices.device[device_name]
            connectivity_context = (device.live_status.tapi_common__context.
                                    tapi_connectivity__connectivity_context)
            connectivity_service = (connectivity_context.
                                    connectivity_service[input.uuid])

            for connection in connectivity_service.connection:
                # Generate a GET for the corresponding connection
                output.connection.create(connectivity_context.connection[
                                         connection.connection_uuid].uuid)


class EquipmentSummary(Action):
    def init(self, init_args):
        self.output = None

    def process_device(self, device, access_port_oneps):
        output_device = self.output.device.create(device.uuid)

        missing_corresponding_onep = 0
        equipment_summary = defaultdict(int)

        for equipment in device.equipment:
            equipment_summary[equipment.category] += 1

        for category, count in equipment_summary.items():
            output_device.equipment_summary.create(
                category).count = count

        for access_port in device.access_port:
            # Generate GET for each access-port
            _ = len(access_port.name)

            if access_port.uuid not in access_port_oneps:
                missing_corresponding_onep += 1

        output_device.access_port_count = len(device.access_port)
        output_device.missing_corresponding_owned_node_edge_point = \
            missing_corresponding_onep

    @Action.action
    def cb_action(self, uinfo, name, kp, input, output, trans):
        self.log.info('action name: ', name)
        self.output = output
        device_name = str(kp[1][0])

        with ncs.maapi.single_read_trans(uinfo.username, 'python') as th:
            device = ncs.maagic.get_root(th).devices.device[device_name]
            common_context = device.live_status.tapi_common__context
            physical_context = common_context.tapi_equipment__physical_context
            access_port_oneps = (device.tapi_ols__tapi_context.topology.
                                 access_port_owned_node_edge_point)

            for physical_device in physical_context.device:
                self.process_device(physical_device, access_port_oneps)

            output.device_count = len(physical_context.device)

            # Generate GET for each physical-span
            output.physical_span_count = len([
                len(physical_span.access_port)
                for physical_span in physical_context.physical_span])
