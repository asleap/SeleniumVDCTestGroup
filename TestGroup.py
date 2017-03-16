#!/usr/bin/env python
# -*- coding: utf-8 -*-

from selenium import webdriver
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import Select
from selenium.common.exceptions import NoSuchElementException, ElementNotVisibleException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC

from paramiko import client
from paramiko.ssh_exception import AuthenticationException, NoValidConnectionsError

import sys
import time
import os
import platform


def ping(host):
    """Simple ping function, based on OS ping tool.
    Returns 0 if host responds to a ping request.
    Tested only on Linux.
    """
    params = '-n 4' if platform.system().lower() == 'windows' else '-c 4'
    return os.system('ping ' + params + ' ' + host)


def send_single_command(address, username, password, command, retries=5, timeout=4):
    """Establishes SSH-connection and sends single command"""
    ssh = None
    count = 0
    while count < retries:
        try:
            ssh = client.SSHClient()
            ssh.set_missing_host_key_policy(client.AutoAddPolicy())
            ssh.connect(hostname=address, username=username, password=password)
            count = retries
        except NoValidConnectionsError:
            count += 1
            time.sleep(timeout)
    if ssh is None:
        return '', -1
    stdin, stdout, stderr = ssh.exec_command(command)
    data, status = stdout.read(), int(stdout.channel.recv_exit_status())
    ssh.close()
    return data, status


class SSHClient:
    """SSHClient represents ssh connection with remote host.
    Based on paramiko package
    """

    def __init__(self, address, username, password):
        self.__client = client.SSHClient()
        self.__client.set_missing_host_key_policy(client.AutoAddPolicy())
        try:
            self.__client.connect(hostname=address, username=username, password=password)
        except AuthenticationException:
            print('SSH authentication failed. Please edit "$HOME/.ssh/known_hosts"')

    def send_command(self, command):
        """Sends command to remote host and returns stdout and exit status."""
        stdin, stdout, stderr = self.__client.exec_command(command)
        data = ''
        while not stdout.channel.exit_status_ready():
            if stdout.channel.recv_ready():
                data = stdout.channel.recv(1024)
                while stdout.channel.recv_ready():
                    data += stdout.channel.recv(1024)
        return data, int(stdout.channel.recv_exit_status())

    def close(self):
        """Closes connection.
        Call it after finished working with remote host.
        """
        self.__client.close()

    @staticmethod
    def get_ssh_client(address, username, password, retries=5, timeout=4):
        """Establishes SSH-connection to remote host with specific number
        of retries and timeout between them. Returns SSHClient instance or None
        if connection refused.
        """
        ssh_client = None
        count = 0
        while count < retries:
            try:
                ssh_client = SSHClient(address, username, password)
                count = retries
            except NoValidConnectionsError:
                count += 1
                time.sleep(timeout)

        return ssh_client


class TestGroup:
    """This group of tests is responsible for Linux VM testing.
    Contains tests number: 8, 11, 12, 13, 14 from tasks description.
    Tests are mutually connected with each other and share common resources (e.g. config fields)
    """

    def __init__(self, email, password, httpaddress):
        self.email = email
        self.password = password
        self.httpaddress = httpaddress

        # The config dicts are used to store VM parameters:
        # RAM, vCPU number, OS, IP Adresses, Software settings and VM id.
        # These parameters are shared among the tests
        self.ubuntu_config = {}
        self.centos_config = {}

        # Set up Firefox
        firefoxprofile = webdriver.FirefoxProfile('default-firefox-profile/default')
        self.driver = webdriver.Firefox(firefox_profile=firefoxprofile)

        # In QA, create instance page does not have 'create' button.
        # Run button callback instead.
        # Script copied from page source.
        # Might broke down, if namespace in page script is isolated.
        self.create_script = """
            create = function() {
              if (stop_estimation) return false;
              var cfg = get_vm_config();
              Backend.create_instance(cfg, function(data) {
                stop_estimation = 1;
                modal_hide();
              });
              return false;
            }
            create();
            """

        # In QA, reconfigure instance page does not have 'submit' button.
        # Run button callback instead.
        # Script copied from page source.
        # Might broke down, if namespace in page script is isolated.
        self.reconfigure_script = """
            submit = function() {
              if (stop_estimation) return false;
              var cfg = get_vm_config();

              // set size=0 for deleted disks
              var new_disks = {};
              $.each(cfg.configuration.disks, function() {
                if (this.disk_id) new_disks[this.disk_id] = this;
              });
              var del_disks = [];
              if (instance && instance.config.disks) {
                $.each(instance.config.disks, function() {
                  if (!new_disks[this.disk_id]) {
                    del_disks.push({
                      disk_id: this.disk_id,
                      profile_id: this.profile_id,
                      size: 0
                    });
                  }
                });
              }
              $.merge(cfg.configuration.disks, del_disks);

              delete cfg.password;
              delete cfg.hostname;
              delete cfg.os_id;
              delete cfg.software;

              Backend.update_instance(instance_id, cfg, function(data) {
                //console.log('stop_estimation = 1');
                stop_estimation = 1;
                modal_hide();
              });
              return false;
            }
            submit()
            """

    def __del__(self):
        # self.driver.quit()
        pass

    @staticmethod
    def sleep(seconds=2):
        """Simple sleep function with default value of 2 seconds."""
        time.sleep(seconds)

    @property
    def is_authorized(self):
        """Checks whether the user is authorized by scanning the page source for email or keywords."""
        return (self.email in self.driver.page_source) \
               or ('Profile' in self.driver.page_source) \
               or ('My Account' in self.driver.page_source)

    def login(self):
        """Carries out authorization procedure in both production and QA."""
        if self.is_authorized:
            return
        driver = self.driver

        print('Authorizing as %s on %s...' % (self.email, self.httpaddress))
        driver.get('%s' % self.httpaddress)

        # If in production, switch country. Pass if already switched
        try:
            driver.find_element_by_xpath("//*[contains(text(), 'Latvija')]").click()
            driver.find_element_by_xpath("//*[contains(text(), 'Krievija')]").click()
        except (NoSuchElementException, ElementNotVisibleException):
            pass

        # If attempted to log in before, switch country. Pass if already switched
        try:
            driver.find_element_by_xpath("//*[contains(text(), 'Latvia')]").click()
            driver.find_element_by_xpath("//*[contains(text(), 'Russia')]").click()
        except (NoSuchElementException, ElementNotVisibleException):
            pass

        # Switch from RU to EN, if not switched before. Pass if already switched
        try:
            driver.find_element_by_xpath("//*[contains(text(), 'RU')]").click()
            driver.find_element_by_xpath("//*[contains(text(), 'EN')]").click()
        except (NoSuchElementException, ElementNotVisibleException):
            pass

        # Go to login page and authorize
        self.sleep()
        driver.find_element_by_id('top-nav-login-link').click()
        self.sleep()
        driver.find_element_by_xpath("//input[contains(@id, 'email')]").send_keys('%s' % self.email)
        driver.find_element_by_xpath("//input[contains(@id, 'password')]").send_keys('%s' % self.password)
        driver.find_element_by_xpath("//input[contains(@id, 'password')]").send_keys(Keys.ENTER)

        # Go to catalog
        self.sleep(3)
        driver.find_element_by_xpath("//a[contains(text(), 'Catalog')]").click()

        # If in QA, go to cloud services
        try:
            driver.find_element_by_link_text('Cloud Services').click()
        except NoSuchElementException:
            pass

        # Go to virtual machines
        self.sleep()
        driver.find_element_by_link_text('Virtual machines').click()

        print('\t...authorized\n')

    def logout(self):
        """Logs out, first from the data centre, then from the service."""
        if self.is_authorized:
            try:
                self.driver.find_element_by_xpath("//a[contains(text(), 'Logout')]").click()
            except NoSuchElementException:
                pass

            self.sleep()
            try:
                self.driver.find_element_by_id('top-nav-logout-link').click()
            except NoSuchElementException:
                pass

    def delete_vm(self, vm_name):
        """Deletes vm with given name if on data center page"""
        driver = self.driver
        if vm_name in driver.page_source:
            print('VM %s will be deleted in 10 seconds')
            self.sleep(10)
            driver.find_element_by_xpath("//a[contains(text(), '%s')]/../../td/input" % vm_name).click()
            driver.find_element_by_xpath("//a[contains(text(), 'Destroy')]").click()
            self.sleep()
            driver.find_element_by_xpath("//form[contains(text(), 'You are going to destroy')]/input"). \
                send_keys('DESTROY', Keys.TAB, Keys.TAB, Keys.ENTER)

    def configure_vm(self, config):
        """Sets up virtual machine configuration according to given config."""
        print('Configuring VM...')
        driver = self.driver

        # VM Name
        elem = driver.find_element_by_xpath("//input[contains(@id, 'name')]")
        elem.send_keys(Keys.CONTROL + 'a')
        elem.send_keys(Keys.DELETE)
        elem.send_keys('%s' % config['VM Name'])
        print('\tVM Name: %s' % config['VM Name'])

        # OS
        Select(driver.find_element_by_id('os')).select_by_visible_text('%s' % config['OS'])
        print('\tOS: %s' % config['OS'])

        # Software
        if 'Software' in config:
            driver.find_element_by_xpath("//button[contains(@title, 'Select software')]").click()
            for sw in config['Software']:
                elem = driver.find_element_by_xpath("//label[contains(text(), '%s')]/input" % sw[0])
                if sw[1]:
                    if not elem.is_selected():
                        elem.click()
                    print('\t%s enabled' % sw[0])
                else:
                    if elem.is_selected():
                        elem.click()
                    print('\t%s disabled' % sw[0])
            driver.find_element_by_xpath("//button[contains(@title, '%s')]" % config['Software'][0][0]).click()

        # Recommended settings
        if 'Use recommended' in config:
            elem = driver.find_element_by_xpath("//input[contains(@id, 'use_recommended')]")
            if config['Use recommended']:
                if not elem.is_selected():
                    elem.click()
                print('\tUsing recommended settings')
            else:
                if elem.is_selected():
                    elem.click()
                print('\tUsing custom settings')

        # vCPU
        if 'vCPU' in config:
            elem = driver.find_element_by_id('f_input_vcpus')
            elem.send_keys(Keys.CONTROL + 'a')
            elem.send_keys(Keys.DELETE)
            elem.send_keys('%s' % config['vCPU'])
            print('\tvCPU: %s' % config['vCPU'])

        # RAM
        if 'RAM' in config:
            elem = driver.find_element_by_id('f_input_memory')
            elem.send_keys(Keys.CONTROL + 'a')
            elem.send_keys(Keys.DELETE)
            elem.send_keys('%s' % config['RAM'])
            print('\tRAM: %s' % config['RAM'])

        # HDD
        if 'HDD 1 Type' in config:
            Select(driver.find_element_by_id('hdd_type_1')).select_by_visible_text('%s' % config['HDD 1 Type'])
            print('\tHDD 1 Type: %s' % config['HDD 1 Type'])
        if 'HDD 1 Size' in config:
            elem = driver.find_element_by_id('f_input_hdd_1_size')
            elem.send_keys(Keys.CONTROL + 'a')
            elem.send_keys(Keys.DELETE)
            elem.send_keys('%s' % config['HDD 1 Size'])
            print('\tHDD 1 Size: %s' % config['HDD 1 Size'])

        # Bandwidth
        if 'Bandwidth' in config:
            elem = driver.find_element_by_id('f_input_bandwidth')
            elem.send_keys(Keys.CONTROL + 'a')
            elem.send_keys(Keys.DELETE)
            elem.send_keys('%s' % config['Bandwidth'])
            print('\tBandwidth: %s' % config['Bandwidth'])

        # Hostname
        if 'Hostname' in config:
            elem = driver.find_element_by_xpath("//input[contains(@name, 'hostname')]")
            elem.send_keys(Keys.CONTROL + 'a')
            elem.send_keys(Keys.DELETE)
            elem.send_keys('%s' % config['Hostname'])
            print('\tHostname: %s' % config['Hostname'])

        # Password
        if 'Password' in config:
            elem = driver.find_element_by_xpath("//input[contains(@name, 'password')]")
            elem.send_keys(Keys.CONTROL + 'a')
            elem.send_keys(Keys.DELETE)
            elem.send_keys('%s' % config['Password'])
            print('\tPassword: %s' % config['Password'])

        # Allow internet (public ipv4)
        if 'Allow public ipv4' in config:
            # elem = driver.find_element_by_xpath("//label[contains(text(), 'Public IPv4')]/input") # Bad selector
            elem = driver.find_element_by_xpath("//input[contains(@name, 'auto_floating')]")
            if config['Allow public ipv4']:
                if not elem.is_selected():
                    elem.click()
                print('\tPublic ipv4 enabled')
            else:
                if elem.is_selected():
                    elem.click()
                print('\tPublic ipv4 disabled')

        # Firewall settings
        if 'Firewall rules' in config:
            driver.find_element_by_xpath("//a[contains(text(), 'Firewall rules')]").click()
            self.sleep()

            if 'Select firewall templates' in driver.page_source:
                # In QA
                driver.find_element_by_xpath("//button[contains(@title, 'Select firewall templates')]").click()
                self.sleep()
                for rule in config['Firewall rules']:
                    try:
                        elem = driver.find_element_by_xpath("//label[contains(text(), '%s')]/input" % rule[0])
                        if rule[1]:
                            if not elem.is_selected():
                                elem.click()
                            print('\t%s enabled' % rule[0])
                        else:
                            if elem.is_selected():
                                elem.click()
                            print('\t%s disabled' % rule[0])
                    except NoSuchElementException:
                        print('\t%s not found' % rule[0])

                driver.find_element_by_xpath(
                    "//button[contains(@title, '%s')]" % config['Firewall rules'][0][0]).click()
                self.sleep()
            else:
                # In production
                for rule in config['Firewall rules']:
                    try:
                        elem = driver.find_element_by_xpath(
                            "//input[contains(@preinst_alias_id, '%s')]" % rule[0].lower())
                        if rule[1]:
                            if not elem.is_selected():
                                elem.click()
                            print('\t%s enabled' % rule[0])
                        else:
                            if elem.is_selected():
                                elem.click()
                            print('\t%s disabled' % rule[0])
                    except NoSuchElementException:
                        print('\t%s not found' % rule[0])

            driver.find_element_by_xpath("//a[contains(text(), 'Instance')]").click()

        # Press submit button
        try:
            driver.find_element_by_xpath("//button[contains(@id, 'createButton')]").click()
        except NoSuchElementException:
            # Call script to emulate button click
            self.sleep()
            driver.execute_script(self.create_script)

        print('\t...configured\n')

    def set_up(self):
        """This method is called before each test case"""
        # Authorize
        if not self.is_authorized:
            self.login()
            # Go to data center
            # Order now
            self.sleep(4)
            self.driver.find_element_by_xpath("//input[contains(@value, 'Order now')]").click()

            # Close default machine create popup
            WebDriverWait(self.driver, 40).until(
                EC.visibility_of_element_located(
                    (By.XPATH, "//button[contains(@class, 'btn btn-primary cart-clear')]")
                )
            )
            self.driver.find_element_by_xpath("//button[contains(@class, 'btn btn-primary cart-clear')]").click()

    def test_008(self):
        """Test number 8.
        Create Linux VM with LAMP
        """
        self.set_up()

        print('Running test 8...\n')
        driver = self.driver
        self.ubuntu_config = {
            'VM Name': 'Ubuntu-1410',
            'OS': 'Ubuntu 14.10 x64',
            'Software': [
                ('Web server (LAMP)', True)
            ],
            'Use recommended': False,
            'vCPU': '8',
            'RAM': '16384',
            'HDD 1 Type': 'Ultrafast SSD',
            'HDD 1 Size': '100',
            'Bandwidth': '50',
            'Hostname': 'Ubuntu-1410',
            'Password': 'jiJ:foig@',
            'Allow public ipv4': True,
            'Firewall rules': [
                ('SSH', True),
                ('web', True)
            ]
        }

        # Open create virtual machine popup (follow the actual address
        # instead of opening popup)
        self.sleep()
        driver.get(driver.find_element_by_xpath("//a[contains(text(), 'Create')]").get_attribute('href'))

        # Set up VM configuration
        self.sleep()
        self.configure_vm(self.ubuntu_config)

        # Go back
        print('Creating VM %s...' % self.ubuntu_config['VM Name'])
        self.sleep()
        driver.back()
        self.sleep()
        driver.refresh()

        # Wait for machine to create (5 mins)
        WebDriverWait(driver, 300).until(
            EC.text_to_be_present_in_element(
                (By.XPATH,
                 "//a[contains(text(), '%s')]/../../td[contains(@class, 'status')]" % self.ubuntu_config['VM Name']),
                'off'
            )
        )
        print('\t...created\n')

        # Get and remember VM id (it is used to get reconfigure page in the latter tests)
        href = driver.find_element_by_xpath(
            "//a[contains(text(), '%s')]" % self.ubuntu_config['VM Name']).get_attribute(
            'href')
        vm_id = href[href.rfind('/') + 1:]
        self.ubuntu_config['VM id'] = vm_id

        # Start VM
        print("Starting VM %s..." % self.ubuntu_config['VM Name'])
        elem = driver.find_element_by_xpath(
            "//a[contains(text(), '%s')]/../../td/input" % self.ubuntu_config['VM Name'])
        if not elem.is_selected():
            elem.click()
        driver.find_element_by_xpath("//a[contains(text(), 'Power')]").click()
        driver.find_element_by_xpath("//a[contains(text(), 'Power on')]").click()

        # Wait for machine to start (5 mins)
        WebDriverWait(driver, 300).until(
            EC.text_to_be_present_in_element(
                (By.XPATH,
                 "//a[contains(text(), '%s')]/../../td[contains(@class, 'status')]" % self.ubuntu_config['VM Name']),
                'on'
            )
        )
        print('\t...started\n')

        # Ping public ip
        self.sleep(5)
        self.ubuntu_config['Public ip'] = driver.find_element_by_xpath(
            "//a[contains(text(), '%s')]/../../td[4]" % self.ubuntu_config['VM Name']).text.strip()
        print('Pinging public ip: ' + self.ubuntu_config['Public ip'])
        status = ping(self.ubuntu_config['Public ip'])
        try:
            assert 0 == status
        except AssertionError:
            # Wait a bit longer if not available in first time and retry
            self.sleep(10)
            status = ping(self.ubuntu_config['Public ip'])
            assert 0 == status
        print('\t...pinging public ip OK\n')

        # Obtain private ip and gateway
        driver.find_element_by_xpath("//a[contains(text(), '%s')]" % self.ubuntu_config['VM Name']).click()
        self.sleep()
        self.ubuntu_config['Private ip'] = driver.find_element_by_xpath(
            "//td[contains(text(), 'Private IP')]/../td[2]").text.strip()
        self.ubuntu_config['Gateway'] = driver.find_element_by_xpath(
            "//td[contains(text(), 'Gateway')]/../td[2]").text.strip()
        driver.back()
        self.sleep()
        driver.refresh()

        # Start vm-side testing
        print('Starting vm-side testing...\n')
        ssh_client = SSHClient.get_ssh_client(self.ubuntu_config['Public ip'], 'root',
                                              self.ubuntu_config['Password'])

        if ssh_client is None:
            print('\t...SSH connection refused after 5 retries')
        else:
            # Check private ip
            print('Running: ifconfig:')
            data = ssh_client.send_command('ifconfig')[0]
            for line in data.splitlines():
                print('\t%s' % line)
            assert self.ubuntu_config['Private ip'] in data
            print('\t...private ip OK\n')

            # Ping gateway
            print('Running: ping -c 4 %s' % self.ubuntu_config['Gateway'])
            data, status = ssh_client.send_command('ping -c 4 %s' % self.ubuntu_config['Gateway'])
            for line in data.splitlines():
                print('\t%s' % line)
            assert 0 == status
            print('\t...pinging gateway OK\n')

            # Check apache
            print('Running: apt list --installed | grep apache2')
            data = ssh_client.send_command('apt list --installed | grep apache2')[0]
            for line in data.splitlines():
                print('\t%s' % line)
            assert 'apache2' in data
            print('\t...Apache OK\n')

            # Check mysql
            print('Running: apt list --installed | grep mysql-server')
            data = ssh_client.send_command('apt list --installed | grep mysql-server')[0]
            for line in data.splitlines():
                print('\t%s' % line)
            assert 'mysql-server' in data
            print('\t...MySQL OK\n')

            # Check php
            print('Running: apt list --installed | grep php5-common')
            data = ssh_client.send_command('apt list --installed | grep php5-common')[0]
            for line in data.splitlines():
                print('\t%s' % line)
            assert 'php5-common' in data
            print('\t...PHP OK\n')

            # Check processor
            print('Running: cat /proc/cpuinfo | grep processor')
            data = ssh_client.send_command('cat /proc/cpuinfo | grep processor')[0]
            for line in data.splitlines():
                print('\t%s' % line)
            assert '7' in data  # Number of processors starts with 0
            assert '8' not in data
            print('\t...processor OK\n')

            # Check RAM
            print('\nRunning: cat /proc/meminfo | grep MemTotal')
            data = ssh_client.send_command('cat /proc/meminfo | grep MemTotal')[0]
            for line in data.splitlines():
                print('\t%s' % line)
            assert '16433320' in data
            print('\t...RAM OK\n')

            # Check disk
            print('Running: parted -l | grep Disk')
            data = ssh_client.send_command('parted -l | grep Disk')[0]
            for line in data.splitlines():
                print('\t%s' % line)
            assert '107' in data
            print('\t...Disk OK\n')

            ssh_client.close()

        print('...finished test 8\n')

    def test_011(self):
        """Test number 11.
        Decrease VM settings.
        """
        self.set_up()

        print('Running test 11...\n')
        driver = self.driver

        # Select machine and stop it
        print("Stopping VM %s..." % self.ubuntu_config['VM Name'])
        elem = driver.find_element_by_xpath(
            "//a[contains(text(), '%s')]/../../td/input" % self.ubuntu_config['VM Name'])
        if not elem.is_selected():
            elem.click()
        driver.find_element_by_xpath("//a[contains(text(), 'Power')]").click()
        driver.find_element_by_xpath("//a[contains(text(), 'Power off')]").click()
        WebDriverWait(driver, 30).until(
            EC.visibility_of_element_located(
                (By.XPATH, "//button[contains(@value, 'yes')]")
            )
        )
        self.sleep(1)
        driver.find_element_by_xpath("//button[contains(@value, 'yes')]").click()

        # Wait for machine to stop (5 mins)
        WebDriverWait(driver, 300).until(
            EC.text_to_be_present_in_element(
                (By.XPATH,
                 "//a[contains(text(), '%s')]/../../td[contains(@class, 'status')]" % self.ubuntu_config['VM Name']),
                'off'
            )
        )
        print('\t...stopped\n')

        # Go to reconfigure page
        print('Reconfiguring VM %s...' % self.ubuntu_config['VM Name'])
        url = driver.current_url
        url = url[:len(url) - 1] + '/' + self.ubuntu_config['VM id'] + '/edit'
        driver.get(url)

        # Wait for price to load
        try:
            driver.find_element_by_xpath("//div[contains(@class, 'period')]")
            WebDriverWait(driver, 30).until(
                EC.visibility_of_element_located(
                    (By.XPATH, "//div[contains(text(), 'per month')]")
                )
            )
        except NoSuchElementException:
            self.sleep(8)

        # Reconfigure VM
        # vCPU
        elem = driver.find_element_by_id('f_input_vcpus')
        vcpus = elem.get_attribute('value').strip()
        elem.send_keys(Keys.CONTROL + 'a')
        self.sleep()
        elem.send_keys(Keys.DELETE)
        elem.send_keys('%s' % '2')
        print('\tvCPU: %s -> %s' % (vcpus, '2'))

        # RAM
        elem = driver.find_element_by_xpath("//input[contains(@id, 'f_input_memory')]")
        ram = elem.get_attribute('value').strip()
        elem.send_keys(Keys.CONTROL + 'a')
        self.sleep()
        elem.send_keys(Keys.DELETE)
        elem.send_keys('%s' % '4096')
        print('\tRAM: %s -> %s' % (ram, '4096'))

        try:
            driver.find_element_by_xpath("//button[contains(@id, 'createButton')]").click()
        except NoSuchElementException:
            # Call script to emulate button click
            self.sleep()
            driver.execute_script(self.reconfigure_script)

        # Wait for machine to rebuild (5 mins)
        driver.back()
        self.sleep()
        driver.refresh()
        WebDriverWait(driver, 300).until(
            EC.text_to_be_present_in_element(
                (By.XPATH,
                 "//a[contains(text(), '%s')]/../../td[contains(@class, 'status')]" % self.ubuntu_config['VM Name']),
                'off'
            )
        )
        print('\t...reconfigured\n')

        # Start VM
        print("Starting VM %s..." % self.ubuntu_config['VM Name'])
        elem = driver.find_element_by_xpath(
            "//a[contains(text(), '%s')]/../../td/input" % self.ubuntu_config['VM Name'])
        if not elem.is_selected():
            elem.click()
        driver.find_element_by_xpath("//a[contains(text(), 'Power')]").click()
        driver.find_element_by_xpath("//a[contains(text(), 'Power on')]").click()

        # Wait for machine to start (5 mins)
        WebDriverWait(driver, 300).until(
            EC.text_to_be_present_in_element(
                (By.XPATH,
                 "//a[contains(text(), '%s')]/../../td[contains(@class, 'status')]" % self.ubuntu_config['VM Name']),
                'on'
            )
        )
        print('\t...started\n')

        # Start vm-side testing
        print('Starting vm-side testing...\n')
        ssh_client = SSHClient.get_ssh_client(self.ubuntu_config['Public ip'], 'root',
                                              self.ubuntu_config['Password'])

        if ssh_client is None:
            print('\t...SSH connection refused after 5 retries')
        else:
            # Check processor
            print('Running: cat /proc/cpuinfo | grep processor')
            data = ssh_client.send_command('cat /proc/cpuinfo | grep processor')[0]
            for line in data.splitlines():
                print('\t%s' % line)
            assert '1' in data
            assert '2' not in data
            print('\t...processor OK\n')

            # Check RAM
            print('\nRunning: cat /proc/meminfo | grep MemTotal')
            data = ssh_client.send_command('cat /proc/meminfo | grep MemTotal')[0]
            for line in data.splitlines():
                print('\t%s' % line)
            assert '4047756' in data
            print('\t...RAM OK\n')

            ssh_client.close()

        print('...finished test 11\n')

    def test_012(self):
        """Test number 12.
        Increase VM settings.
        """
        self.set_up()

        print('Running test 12...\n')
        driver = self.driver

        # Select machine and stop it
        print("Stopping VM %s..." % self.ubuntu_config['VM Name'])
        elem = driver.find_element_by_xpath(
            "//a[contains(text(), '%s')]/../../td/input" % self.ubuntu_config['VM Name'])
        if not elem.is_selected():
            elem.click()
        driver.find_element_by_xpath("//a[contains(text(), 'Power')]").click()
        driver.find_element_by_xpath("//a[contains(text(), 'Power off')]").click()
        WebDriverWait(driver, 30).until(
            EC.visibility_of_element_located(
                (By.XPATH, "//button[contains(@value, 'yes')]")
            )
        )
        self.sleep(1)
        driver.find_element_by_xpath("//button[contains(@value, 'yes')]").click()

        # Wait for machine to stop (5 mins)
        WebDriverWait(driver, 300).until(
            EC.text_to_be_present_in_element(
                (By.XPATH,
                 "//a[contains(text(), '%s')]/../../td[contains(@class, 'status')]" % self.ubuntu_config['VM Name']),
                'off'
            )
        )
        print('\t...stopped\n')

        # Go to reconfigure page
        print('Reconfiguring VM %s...' % self.ubuntu_config['VM Name'])
        url = driver.current_url
        url = url[:len(url) - 1] + '/' + self.ubuntu_config['VM id'] + '/edit'
        driver.get(url)

        # Wait for price to load
        try:
            driver.find_element_by_xpath("//div[contains(@class, 'period')]")
            WebDriverWait(driver, 30).until(
                EC.visibility_of_element_located(
                    (By.XPATH, "//div[contains(text(), 'per month')]")
                )
            )
        except NoSuchElementException:
            self.sleep(8)

        # Reconfigure VM
        # vCPU
        elem = driver.find_element_by_id('f_input_vcpus')
        vcpus = elem.get_attribute('value').strip()
        elem.send_keys(Keys.CONTROL + 'a')
        self.sleep()
        elem.send_keys(Keys.DELETE)
        elem.send_keys('%s' % '16')
        print('\tvCPU: %s -> %s' % (vcpus, '16'))

        # RAM
        elem = driver.find_element_by_xpath("//input[contains(@id, 'f_input_memory')]")
        ram = elem.get_attribute('value').strip()
        elem.send_keys(Keys.CONTROL + 'a')
        self.sleep()
        elem.send_keys(Keys.DELETE)
        elem.send_keys('%s' % '32768')
        print('\tRAM: %s -> %s' % (ram, '32768'))

        try:
            driver.find_element_by_xpath("//button[contains(@id, 'createButton')]").click()
        except NoSuchElementException:
            # Call script to emulate button click
            self.sleep()
            driver.execute_script(self.reconfigure_script)

        # Wait for machine to rebuild (5 mins)
        driver.back()
        self.sleep()
        driver.refresh()
        WebDriverWait(driver, 300).until(
            EC.text_to_be_present_in_element(
                (By.XPATH,
                 "//a[contains(text(), '%s')]/../../td[contains(@class, 'status')]" % self.ubuntu_config['VM Name']),
                'off'
            )
        )
        print('\t...reconfigured\n')

        # Start VM
        print("Starting VM %s..." % self.ubuntu_config['VM Name'])
        elem = driver.find_element_by_xpath(
            "//a[contains(text(), '%s')]/../../td/input" % self.ubuntu_config['VM Name'])
        if not elem.is_selected():
            elem.click()
        driver.find_element_by_xpath("//a[contains(text(), 'Power')]").click()
        driver.find_element_by_xpath("//a[contains(text(), 'Power on')]").click()

        # Wait for machine to start (5 mins)
        WebDriverWait(driver, 300).until(
            EC.text_to_be_present_in_element(
                (By.XPATH,
                 "//a[contains(text(), '%s')]/../../td[contains(@class, 'status')]" % self.ubuntu_config['VM Name']),
                'on'
            )
        )
        print('\t...started\n')

        # Start vm-side testing
        print('Starting vm-side testing...\n')
        ssh_client = SSHClient.get_ssh_client(self.ubuntu_config['Public ip'], 'root',
                                              self.ubuntu_config['Password'])

        if ssh_client is None:
            print('\t...SSH connection refused after 5 retries')
        else:
            # Check processor
            print('Running: cat /proc/cpuinfo | grep processor')
            data = ssh_client.send_command('cat /proc/cpuinfo | grep processor')[0]
            for line in data.splitlines():
                print('\t%s' % line)
            assert '15' in data
            assert '16' not in data
            print('\t...processor OK\n')

            # Check RAM
            print('\nRunning: cat /proc/meminfo | grep MemTotal')
            data = ssh_client.send_command('cat /proc/meminfo | grep MemTotal')[0]
            for line in data.splitlines():
                print('\t%s' % line)
            assert '32947276' in data
            print('\t...RAM OK\n')

            ssh_client.close()

        print('...finished test 12\n')

    def test_013(self):
        """Test number 13.
        Create CentOS VM with LAMP
        """
        self.set_up()

        print('Running test 13...\n')
        driver = self.driver
        self.centos_config = {
            'VM Name': 'TEST_VM_01',
            'OS': 'CentOS 6 x64',
            'Software': [
                ('Web server (LAMP)', True)
            ],
            'Use recommended': False,
            'vCPU': '8',
            'RAM': '8192',
            'HDD 1 Type': 'Ultrafast SSD',
            'HDD 1 Size': '100',
            'Bandwidth': '50',
            'Hostname': 'tes-vm-01',
            'Password': 'jiJ:foig@',
            'Allow public ipv4': True,
            'Firewall rules': [
                ('SSH', True),
                ('web', True),
                ('internet', True),
                ('Port 5001 ok', True)
            ]
        }

        # Open create virtual machine popup (follow the actual address
        # instead of opening popup)
        self.sleep()
        driver.get(driver.find_element_by_xpath("//a[contains(text(), 'Create')]").get_attribute('href'))

        # Set up VM configuration
        self.sleep()
        self.configure_vm(self.centos_config)

        # Go back
        print('Creating VM %s...' % self.centos_config['VM Name'])
        self.sleep()
        driver.back()
        self.sleep()
        driver.refresh()

        # Wait for machine to create (5 mins)
        WebDriverWait(driver, 300).until(
            EC.text_to_be_present_in_element(
                (By.XPATH,
                 "//a[contains(text(), '%s')]/../../td[contains(@class, 'status')]" % self.centos_config['VM Name']),
                'off'
            )
        )
        print('\t...created\n')

        # Get and remember VM id (it is used to get reconfigure page in the latter tests)
        href = driver.find_element_by_xpath(
            "//a[contains(text(), '%s')]" % self.centos_config['VM Name']).get_attribute(
            'href')
        vm_id = href[href.rfind('/') + 1:]
        self.centos_config['VM id'] = vm_id

        # Start VM
        print("Starting VM %s..." % self.centos_config['VM Name'])
        elem = driver.find_element_by_xpath(
            "//a[contains(text(), '%s')]/../../td/input" % self.centos_config['VM Name'])
        if not elem.is_selected():
            elem.click()
        driver.find_element_by_xpath("//a[contains(text(), 'Power')]").click()
        driver.find_element_by_xpath("//a[contains(text(), 'Power on')]").click()

        # Wait for machine to start (5 mins)
        WebDriverWait(driver, 300).until(
            EC.text_to_be_present_in_element(
                (By.XPATH,
                 "//a[contains(text(), '%s')]/../../td[contains(@class, 'status')]" % self.centos_config['VM Name']),
                'on'
            )
        )
        print('\t...started\n')

        # Ping public ip
        self.sleep(5)
        self.centos_config['Public ip'] = driver.find_element_by_xpath(
            "//a[contains(text(), '%s')]/../../td[4]" % self.centos_config['VM Name']).text.strip()
        print('Pinging public ip: ' + self.centos_config['Public ip'])
        status = ping(self.centos_config['Public ip'])
        try:
            assert 0 == status
        except AssertionError:
            # Wait a bit longer if not available in first time and retry
            self.sleep(10)
            status = ping(self.centos_config['Public ip'])
            assert 0 == status
        print('\t...pinging public ip OK\n')

        # Obtain private ip and gateway
        driver.find_element_by_xpath("//a[contains(text(), '%s')]" % self.centos_config['VM Name']).click()
        self.sleep()
        self.centos_config['Private ip'] = driver.find_element_by_xpath(
            "//td[contains(text(), 'Private IP')]/../td[2]").text.strip()
        self.centos_config['Gateway'] = driver.find_element_by_xpath(
            "//td[contains(text(), 'Gateway')]/../td[2]").text.strip()
        driver.back()
        self.sleep()
        driver.refresh()

        # Start vm-side testing
        print('Starting vm-side testing...\n')
        ip = self.centos_config['Public ip']
        user = 'root'
        psswd = self.centos_config['Password']

        # Check private ip
        print('Running: ifconfig:')
        data = send_single_command(ip, user, psswd, 'ifconfig')[0]
        for line in data.splitlines():
            print('\t%s' % line)
        assert self.centos_config['Private ip'] in data
        print('\t...private ip OK\n')

        # Ping gateway
        print('Running: ping -c 4 %s' % self.centos_config['Gateway'])
        data, status = send_single_command(ip, user, psswd, 'ping -c4 %s' % self.centos_config['Gateway'])
        for line in data.splitlines():
            print('\t%s' % line)
        assert 0 == status
        print('\t...pinging gateway OK\n')

        print('...finished test 13\n')

    def test_014(self):
        """Test number 14.
        Install and check iperf
        """
        self.set_up()

        print('Running test 14...\n')

        # Start vm-side testing
        print('Starting vm-side testing...\n')
        ip = self.centos_config['Public ip']
        user = 'root'
        psswd = self.centos_config['Password']

        # Install epel-release.noarch
        print('Running: yum -y install epel-release.noarch:')
        data = send_single_command(ip, user, psswd, 'yum -y install epel-release.noarch')[0]
        for line in data.splitlines():
            print('\t%s' % line)
        assert 'Complete' in data

        # Installing iperf.x86_64
        print('Running: yum -y install iperf.x86_64')
        data, status = send_single_command(ip, user, psswd, 'yum -y install iperf.x86_64')
        for line in data.splitlines():
            print('\t%s' % line)
        assert 'Complete' in data

        # Checking iperf
        print('Running: rpm -qa | grep iperf')
        data, status = send_single_command(ip, user, psswd, 'rpm -qa | grep iperf')
        for line in data.splitlines():
            print('\t%s' % line)
        assert 'iperf' in data
        print('\t...iperf OK\n')

        print('...finished test 14\n')

    def run_tests(self):
        """Specifies the tests and the order to run"""
        self.test_008()

        self.test_011()
        self.test_012()

        self.test_013()

        self.test_014()


def main():
    if len(sys.argv) != 3:
        print('Usage: python3 TestGroup.py <email> <password> <httpaddress>')
        sys.exit(0)

    email = sys.argv[1]
    password = sys.argv[2]
    httpaddress = sys.argv[3]

    tests = TestGroup(email, password, httpaddress)
    tests.run_tests()


if __name__ == '__main__':
    main()
