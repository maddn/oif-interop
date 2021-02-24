# -*- mode: python; python-indent: 4 -*-
import threading
import json
import re
import requests

import ncs
from ncs.dp import Action
_ncs = __import__('_ncs') # pylint: disable=invalid-name


class EventStream(threading.Thread):
    def __init__(self, device_name, url, headers, username, log):
        super().__init__()
        self.device_name = device_name
        self.url = url
        self.headers = headers
        self.username = username
        self.log = log

    def create_notification(self, json_data):
        def create_node(node_name, data, key, parent):
            if isinstance(data, list):
                list_key = 'value-name'
                for list_entry in data:
                    key_value = list_entry[list_key]
                    parent[node_name].create(key_value)
                    create_node(key_value, list_entry, list_key,
                                parent[node_name])

            elif isinstance(data, dict):
                for child_node_name, child_data in data.items():
                    create_node(child_node_name, child_data, key,
                                parent[node_name])
            else:
                if data is not None and node_name != key:
                    if node_name == 'target-object-identifier':
                        parent[node_name] = data[-36:]
                    else:
                        parent[node_name] = data

        key = None

        if 'ietf-restconf:notification' in json_data:
            json_data = json_data['ietf-restconf:notification']
            if 'eventTime' in json_data:
                key = json_data['eventTime']
            json_data = json_data['tapi-notification:notification']

            if key and 'target-object-identifier' in json_data:
                key = (f'{key} - {json_data["target-object-identifier"][-36:]}')

        if 'uuid' in json_data:
            key = json_data['uuid']

        with ncs.maapi.single_write_trans(self.username, 'python',
                                          db=_ncs.OPERATIONAL) as th:
            root = ncs.maagic.get_root(th)
            device = root.devices.device[self.device_name]
            received = device.tapi_context.notifications.received
            received.notification.create(key)
            try:
                create_node(key, json_data, 'uuid', received.notification)
            except Exception as error: #pylint: disable=broad-except
                self.log.error("Error creating noitification: ", error)
            th.apply()

    def run(self):
        self.log.info('Subscribing to ', self.url)
        with requests.get(self.url, stream=True, headers=self.headers,
                          verify=False) as response:
            for json_chunk in response.iter_content(chunk_size=None):
                try:
                    decoded = json_chunk.decode('utf-8').strip('\r\n\t ')
                    if decoded and decoded != 'data:':
                        decoded = re.sub('^data:', '', decoded, flags=re.M)
                        json_data = json.loads(re.sub(r'^[^\{]*', '', decoded))
                        if len(json_data) > 0:
                            self.log.info(json.dumps(json_data, indent=4))
                            self.create_notification(json_data)
                except json.JSONDecodeError as error:
                    self.log.error('Error parsing notification: {} {}'.format(
                        error, json_chunk.decode('utf-8')))
        self.log.info('Subscription done')


class TapiSubscribe(Action):
    def get_device_details(self, username, device_name):
        with ncs.maapi.single_read_trans(username, 'python') as th:
            root = ncs.maagic.get_root(th)
            device = root.devices.device[device_name]
            notifications = device.tapi_context.notifications
            nokia_attr = getattr(device.ned_settings,"nokia_nrct", None)
            onf_tapi_attr = getattr(device.ned_settings,"onf_tapi_rc", None)

            assert(nokia_attr != None or onf_tapi_attr != None)

            ned_settings = nokia_attr if nokia_attr != None else onf_tapi_attr 
            auth_method = ned_settings.connection.authentication.method.string
            get_header_action = device.live_status.exec.get_login_header
            get_header_input = get_header_action.get_input()
            get_header_input.url = notifications.login_path
            get_header_output = get_header_action(get_header_input)
            self.log.info('Got login header %s' % get_header_output.result)

            return ('https://{}:{}{}'.format(device.address, device.port,
                                             notifications.subscription_path),
                    device.device_type.generic.ned_id,
                    get_header_output.result,
                    auth_method)

    @Action.action
    def cb_action(self, uinfo, name, kp, input, output, trans):
        device_name = str(kp[2][0])
        (url, ned_id, header, method) = self.get_device_details(uinfo.username,
                                                        device_name)
        headers = {'Cookie' if 'cas' in method else
                   'Authorization': header,
                   'Accept': 'text/event-stream'}

        event_stream = EventStream(device_name, url, headers,
                                   uinfo.username, self.log)
        event_stream.start()


class ClearNotifications(Action):
    @Action.action
    def cb_action(self, uinfo, name, kp, input, output, trans):
        self.log.info('action name: ', name)
        device_name = str(kp[2][0])
        self.log.info('Clearing received notifications for ' + device_name)
        with ncs.maapi.single_write_trans(uinfo.username, 'python',
                                          db=_ncs.OPERATIONAL) as th:
            root = ncs.maagic.get_root(th)
            device = root.devices.device[device_name]
            del device.tapi_context.notifications.received
            th.apply()
