#!/usr/bin/env python
# -*- coding: UTF-8 -*-
import os
import logging
import subprocess
import re
from time import sleep
from sanji.core import Sanji
from sanji.core import Route
from sanji.connection.mqtt import Mqtt
from sanji.model_initiator import ModelInitiator


logger = logging.getLogger()


class Cellular(Sanji):
    search_router_pattern =\
        re.compile(ur'routers ([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)')
    search_dns_pattern =\
        re.compile(ur'domain-name-servers (.*);')
    search_ip_pattern =\
        re.compile(ur'fixed-address ([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)')
    search_subnet_pattern =\
        re.compile(ur'subnet-mask ([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)')
    search_name_pattern =\
        re.compile(ur'interface "([a-z]+[0-9])"')

    def get_signal_by_id(self, dev_id):
        try:
            tmp = subprocess.check_output(
                "qmicli -p -d /dev/cdc-wdm" + dev_id +
                " --nas-get-signal-info | grep RSSI \
                | cut -d \"'\" -f 2 \
                | cut -d \" \" -f 1 \
                |tr -d [:cntrl:]",
                shell=True)
            return tmp
        except Exception:
            return 99

    def get_status_by_id(self, dev_id):
        try:
                tmp = subprocess.check_output("qmicli -p -d /dev/cdc-wdm" +
                                              dev_id +
                                              " --wds-get-packet-service-status\
                                              |awk '{print $4}'|\
                                              tr -d [:space:]",
                                              shell=True)
                return tmp
        except Exception:
                return 'disconnected'

    def set_online_by_id(self, dev_id):
        try:
                subprocess.check_output("rm -rf /var/lib/dhcp/dhclient.leases",
                                        shell=True)
                subprocess.check_output("qmi-network /dev/cdc-wdm" +
                                        dev_id + " start", shell=True)
                subprocess.check_output("dhclient wwan" +
                                        dev_id, shell=True)
                return 'success'
        except Exception:
                return 'fail'

    def set_offline_by_id(self, dev_id):
        try:
                subprocess.check_output("dhclient -r wwan" +
                                        dev_id, shell=True)
                subprocess.check_output("qmi-network /dev/cdc-wdm" +
                                        dev_id + " stop", shell=True)
                return 'success'
        except Exception:
                return 'fail'

    def init(self, *args, **kwargs):
        path_root = os.path.abspath(os.path.dirname(__file__))
        self.model = ModelInitiator("cellular", path_root)

    @Route(methods="get", resource="/network/cellulars")
    def get_root(self, message, response):
            return response(code=200, data=self.model.db)

    @Route(methods="get", resource="/network/cellulars/:id")
    def get_root_by_id(self, message, response):
            if int(message.param['id']) > len(self.model.db):
                    return response(code=400, data={
                        "message": "No such resources"})
            else:
                    return response(code=200,
                                    data=self.model.db
                                    [int(message.param['id'])])

    @Route(methods="put", resource="/network/cellulars/:id")
    def put_root_by_id(self, message, response):
        if not hasattr(message, "data"):
            return response(code=400, data={"message": "Invalid Input."})

        id = int(message.param['id'])

        if "enable" in message.data:
                self.model.db[id]["enable"] = message.data["enable"]

        if "apn" in message.data:
            self.model.db[id]["apn"] = message.data["apn"]

        if "username" in message.data:
            self.model.db[id]["username"] = message.data["username"]

        if "name" in message.data:
            self.model.db[id]["name"] = message.data["name"]

        if "dialNumber" in message.data:
            self.model.db[id]["dialNumber"] = message.data["dialNumber"]

        if "password" in message.data:
            self.model.db[id]["password"] = message.data["password"]

        if "pinCode" in message.data:
            self.model.db[id]["pinCode"] = message.data["pinCode"]

        if "enableAuth" in message.data:
                self.model.db[id]["enableAuth"] = message.data["enableAuth"]

        self.model.save_db()
        return response(code=200,
                        data=self.model.db[int(message.param['id'])])

    def run(self):
        while True:
            for model in self.model.db:
                if os.path.exists(model['modemPort']):
                    dev_id = str(model['id'])
                    # update signal
                    model['signal'] = self.get_signal_by_id(dev_id)
                    logger.debug("Signal %s on device path %s"
                                 % (model['signal'],
                                    model['modemPort']))

                    # check network availability
                    # if network status down, turn up
                    if model['enable'] == 1:
                            logger.debug("Enable is 1")
                            if self.get_status_by_id(dev_id) == \
                                    "'disconnected'":
                                logger.debug("Start connect")
                                self.set_offline_by_id(dev_id)
                                self.set_online_by_id(dev_id)
                                # update info according to dhclient.leases
                                try:
                                    with open('/var/lib/dhcp/dhclient.leases',
                                              'r') as leases:
                                        filetext = leases.read()
                                except Exception:
                                    logger.debug("File open failure")
                                    continue

                                # parse name
                                name = re.search(self.search_name_pattern,
                                                 filetext)
                                if name:
                                    model['name'] = name.group(1)
                                    logger.debug("name is %s" % name.group(1))

                                # parse router
                                router = re.search(self.search_router_pattern,
                                                   filetext)
                                if router:
                                    model['router'] = router.group(1)
                                    logger.debug("router is %s" %
                                                 router.group(1))
                                    try:
                                        self.publish.direct.\
                                            put("/network/routers",
                                                data={"name": model['name'],
                                                      "gateway":
                                                      model['router']})
                                    except Exception:
                                        logger.debug("Fail put %s-%s" %
                                                     model['name'],
                                                     model['router'])

                                # parse dns
                                dns = re.search(self.search_dns_pattern,
                                                filetext)
                                if dns:
                                    model['dns'] = dns.group(1)
                                    logger.debug("dns is %s" % dns.group(1))
                                    try:
                                        self.publish.direct.\
                                            put("/network/dns",
                                                data={"dns": model['dns']})
                                    except Exception:
                                        logger.debug("Fail put %s-%s" %
                                                     model['dns'])

                                # parse ip
                                ip = re.search(self.search_ip_pattern,
                                               filetext)
                                if ip:
                                    model['ip'] = ip.group(1)
                                    logger.debug("ip is %s" % ip.group(1))

                                # parse subnet
                                subnet = re.search(self.search_subnet_pattern,
                                                   filetext)
                                if subnet:
                                    model['subnet'] = subnet.group(1)
                                    logger.debug("subnet is %s" %
                                                 subnet.group(1))

                                self.model.save_db()
                    else:
                            if self.get_status_by_id(dev_id) == "'connected'":
                                self.set_offline_by_id(dev_id)

                else:
                        model['signal'] = 99

            sleep(30)
if __name__ == "__main__":
    FORMAT = "%(asctime)s - %(levelname)s - %(lineno)s - %(message)s"
    logging.basicConfig(level=0, format=FORMAT)
    logger = logging.getLogger("Sanji Cellular")

    cellular = Cellular(connection=Mqtt())
    cellular.start()