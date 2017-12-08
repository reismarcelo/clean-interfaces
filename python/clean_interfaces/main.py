# -*- mode: python; python-indent: 4 -*-
import ncs
from ncs.application import Service
from ncs.dp import Action
from _ncs.dp import action_set_timeout
import re
from itertools import starmap, islice
from time import time, sleep
from clean_interfaces.utils import apply_template, plan_data_service, split_intf_name, is_intf_sub


# ---------------------------------------------
# ACTIONS
# ---------------------------------------------
def live_status_any(device):
    # Mapping of ned-id to exec namespaces
    stats_exec = {
        'cisco-ios': 'ios_stats__exec',
        'cisco-nx': 'nx_stats__exec',
        'cisco-ios-xr-id:cisco-ios-xr': 'cisco_ios_xr_stats__exec',
        'cisco-ios-xr': 'cisco_ios_xr_stats__exec',
    }
    return getattr(device.live_status, stats_exec[device.device_type.cli.ned_id]).any


class CollectStatsAction(Action):
    @Action.action
    def cb_action(self, uinfo, name, kp, input, output):

        def parse_intf_block(intf_block, intf_name):
            parsed = re.search(r'\s+(?P<in_pkts>\d+)\s+packets input[^$]+\s+(?P<out_pkts>\d+)\s+packets output',
                               intf_block)
            if parsed is not None:
                return intf_name, parsed.group('in_pkts'), parsed.group('out_pkts')
            return None

        self.log.info('Executing action: ', name)
        action_set_timeout(uinfo, 240)

        parsed_intfs = []
        with ncs.maapi.single_read_trans(uinfo.username, uinfo.context) as read_t:
            root = ncs.maagic.get_root(read_t)
            service = ncs.maagic.cd(root, kp)
            device = root.devices.device[service.name]

            # Verify if we need to wait before collecting a new sample
            key_list = [sample_entry.timestamp for sample_entry in service.interface_counters.sample]
            if len(key_list) > 0:
                wait_time = root.ncs__services.clints__clean_interfaces.clints__setup.clints__min_interval - \
                            (int(time()) - sorted(key_list)[-1])
                if wait_time > 0:
                    self.log.info('Will wait {}s according to configured min-interval'.format(wait_time))
                    sleep(wait_time)
                    self.log.info('Done waiting, lets proceed'.format(wait_time))

            exec_any = live_status_any(device)
            exec_any_input = exec_any.get_input()
            exec_any_input.args = ["show interfaces"]

            # intf_blocks is [(<intf_block>, <intf_name>), ...]
            intf_blocks = re.findall(r'^((\S+) is (?:up|down), line protocol is (?:up|down).+?)^\s*$',
                                     exec_any(exec_any_input).result,
                                     re.MULTILINE+re.DOTALL)
            # parsed_intfs is [(<intf_name>, <in_pkts>, <out_pkts>), ...]
            parsed_intfs += filter(lambda x: x is not None, starmap(parse_intf_block, intf_blocks))

            self.log.info('Collected interface stats from device: ', device.name)

        if len(parsed_intfs) > 0:
            with ncs.maapi.single_write_trans(uinfo.username, uinfo.context) as write_t:
                root = ncs.maagic.get_root(write_t)
                service = ncs.maagic.cd(root, kp)

                # Create a new sample
                timestamp = int(time())
                new_sample = service.interface_counters.sample.create(timestamp)
                for intf_name, in_pkts, out_pkts in parsed_intfs:
                    new_intf = new_sample.interface.create(intf_name)
                    new_intf.in_pkts = in_pkts
                    new_intf.out_pkts = out_pkts

                # Trim old samples
                key_list = [sample_entry.timestamp for sample_entry in service.interface_counters.sample]
                items_to_trim = len(key_list) - root.ncs__services.clints__clean_interfaces.clints__setup.clints__max_samples
                if items_to_trim > 0:
                    for old_key in islice(sorted(key_list), items_to_trim):
                        del service.interface_counters.sample[old_key]
                    self.log.info('Trimmed {} sample(s)'.format(items_to_trim))

                write_t.apply()

                output.success = "Added new interface stats sample"
                self.log.info("Added new sample '{}' with {} interface entries".format(timestamp, len(parsed_intfs)))
        else:
            output.failure = "Could not parse the output of 'show interfaces'"
            self.log.warning(output.failure)

        self.log.info('Completed action: ', name)


class ResetStatsAction(Action):
    @Action.action
    def cb_action(self, uinfo, name, kp, input, output):
        self.log.info('Executing action: ', name)
        with ncs.maapi.single_write_trans(uinfo.username, uinfo.context) as write_t:
            root = ncs.maagic.get_root(write_t)
            service = ncs.maagic.cd(root, kp)

            del service.interface_counters.sample

            write_t.apply()

            output.result = "Interface statistics data reset"

        self.log.info('Completed action: ', name)


# ---------------------------------------------
# SERVICES
# ---------------------------------------------
class CleanInterfacesService(Service):
    @Service.create
    @plan_data_service('clints:first-sample-collected', 'clints:second-sample-collected')
    def cb_create(self, tctx, root, service, proplist, self_plan):

        key_list = [sample_entry.timestamp for sample_entry in service.interface_counters.sample]

        if len(key_list) > 0:
            self_plan.set_reached('clints:first-sample-collected')
        if len(key_list) > 1:
            self_plan.set_reached('clints:second-sample-collected')

        if len(key_list) < 2:
            self.log.info('Requesting more samples')
            # Request new stats sample and setup kicker for re-deploy
            apply_template('instance-request-stats-kicker', service, {'ID': len(key_list)})
            return

        self.log.info('Enough samples, figuring something out')

        # sample_dict is {<intf>: [(<in_pkts1>, <out_pkts1>), (<in_pkts2>, <out_pkts2>), ...], ...}
        sample_dict = {}
        for timestamp in sorted(key_list):
            sample = service.interface_counters.sample[timestamp]
            for intf in sample.interface:
                sample_dict.setdefault(intf.id, []).append((intf.in_pkts, intf.out_pkts))

        delta_dict = {intf: (samples[-1][0] - samples[-2][0]) + (samples[-1][1] - samples[-2][1])
                      for intf, samples in sample_dict.items() if len(samples) > 1}

        configured_threshold = root.ncs__services.clints__clean_interfaces.clints__setup.clints__threshold
        template_mapping = {
            'GigabitEthernet': 'shutdown-gigabitethernet',
            'TenGigE': 'shutdown-tengige',
        }

        for intf, delta_pkts in delta_dict.items():
            if not is_intf_sub(intf) and (delta_pkts < configured_threshold):
                intf_type, intf_id = split_intf_name(intf)
                t_vars = {
                    'INTERFACE_TYPE': intf_type,
                    'INTERFACE_ID': intf_id
                }
                if intf_type in template_mapping:
                    self.log.info('Identified unused interface: {}{}'.format(intf_type, intf_id))
                    apply_template(template_mapping[intf_type], service, t_vars)

        return proplist


class SetupKickersService(Service):
    @Service.create
    def cb_create(self, tctx, root, service, proplist):
        self.log.info('Service create ({})'.format(service._path))
        apply_template('global-collect-stats-kicker', service)


# ---------------------------------------------
# COMPONENT THREAD THAT WILL BE STARTED BY NCS.
# ---------------------------------------------
class Main(ncs.application.Application):
    def setup(self):
        # The application class sets up logging for us. It is accessible
        # through 'self.log' and is a ncs.log.Log instance.
        self.log.info('Main RUNNING')

        # Registration of service callbacks
        self.register_service('clean-interfaces-servicepoint', CleanInterfacesService)
        self.register_service('setup-kickers-servicepoint', SetupKickersService)

        # Registration of action callbacks
        self.register_action('collect-stats-action', CollectStatsAction)
        self.register_action('reset-stats-action', ResetStatsAction)

    def teardown(self):
        self.log.info('Main FINISHED')
