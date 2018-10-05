# Clean-interfaces package

Provided a device name this package will take two snapshots of 'show interfaces' on that device and shutdown unused
interfaces.

## Initial setup

Kicker-triggered actions are run as the 'system' user. Because the collect-stats action needs to login to a device and
run cli commands, there is a need for a system user umap authgroup configuration similar to the below:

    devices authgroups group <group name>
     umap system
      remote-name     <cli device username>
      remote-password <cli devivce password>
     !
    !

The setup container allows the customization of some parameters. It is a presence container, when set it applies the
global-collect-stats-kicker.xml template.

    admin@ncs(config)# services clean-interfaces ?
    Possible completions:
      setup   One-time setup of global kickers
      <cr>
    admin@ncs(config)# services clean-interfaces setup ?
    Possible completions:
      max-samples    Maximum number of interface stats samples to keep
      min-interval   Minimum interval between samples in seconds
      threshold      Threshold in in/out packets under which interfaces are considered for shutdown
      <cr>
    admin@ncs(config)# services clean-interfaces setup
    admin@ncs(config-setup)# commit
    Commit complete.

In order to view the configured kickers we need to create and unhide the debug group:
a. Add the following to ncs.conf file and restart NSO:

    <hide-group>
        <name>debug</name>
    </hide-group>

b. Unhide the debug group via cli:

    admin@ncs# unhide debug
    
    c. Show running kickers:
    admin@ncs# show running-config kickers
    kickers data-kicker clean-interfaces-collect-stats
     monitor     /ncs:services/clints:clean-interfaces/clints:stats-requests/clints:target-instance
     kick-node   /ncs:services/clints:clean-interfaces/clints:device[clints:name=current()]
     action-name collect-stats
    !
    <snip>


## Specifying device to clean interfaces

    admin@ncs(config)# services clean-interfaces device A3-ASR9K-R6
    admin@ncs(config-device-A3-ASR9K-R6)# commit

## Checking captured interface counters

    admin@ncs# show services clean-interfaces device A3-ASR9K-R6 interface-counters
                                                 OUT
    TIMESTAMP   ID                      IN PKTS  PKTS
    ------------------------------------------------------
    1511384016  Bundle-Ether1           0        0
                Bundle-Ether2           4180007  3873223
                Bundle-Ether300         0        0
                Bundle-Ether300.900     0        0
                GigabitEthernet0/2/0/1  4180007  3873224
                MgmtEth0/RSP0/CPU0/0    2717142  1141751
                Multilink0/0/0/0/1      0        0
                Multilink0/0/0/0/1.100  0        0
                Multilink0/0/0/0/1.200  0        0
                Multilink0/0/0/0/1.300  0        0
                Null0                   0        0
    1511384071  Bundle-Ether1           0        0
                Bundle-Ether2           4180199  3873404
                Bundle-Ether300         0        0
                Bundle-Ether300.900     0        0
                GigabitEthernet0/2/0/1  4180199  3873404
                MgmtEth0/RSP0/CPU0/0    2717428  1142058
                Multilink0/0/0/0/1      0        0
                Multilink0/0/0/0/1.100  0        0
                Multilink0/0/0/0/1.200  0        0
                Multilink0/0/0/0/1.300  0        0
                Null0                   0        0


We can also trigger the collection of a new sample by manually calling the collect-stats action:

    admin@ncs# services clean-interfaces device A3-ASR9K-R6 collect-stats
    success Added new interface stats sample
    admin@ncs#
    System message at 2017-11-22 15:57:43...
    Commit performed by admin via tcp using cli.












