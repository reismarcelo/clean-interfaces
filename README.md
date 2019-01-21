# Clean-interfaces package

Provided a device name this package will take two snapshots of 'show interfaces' and shutdown unused
interfaces. Unused interfaces are identified by calculating the delta input packets and delta output packets between 'show interfaces' snapshots. 

An interface is considered unused if:

    delta input packets + delta output packets < threshold
    

## Initial setup

NSO actions performed by this service are run as a 'system' user (because the actions are triggered by NSO kickers). 
The collect-stats action needs to login to a device and run cli commands, hence it is necessary to configure a 'system' user umap authgroup similar to the following:

    devices authgroups group <group name>
     umap system
      remote-name     <cli device username>
      remote-password <cli devivce password>
     !
    !

Before devices can be defined, a one-time service setup is necessary:

    admin@ncs(config)# services clean-interfaces ?
    Possible completions:
      setup   One-time service setup
      <cr>    
    
    admin@ncs(config)# services clean-interfaces setup
    admin@ncs(config-setup)# commit
    Commit complete.
    admin@ncs(config-setup)#    
   
Additional (optional) parameters can be configured under setup:

    admin@ncs(config)# services clean-interfaces setup ?
    Possible completions:          
      max-samples          Maximum number of samples to keep, older samples are trimmed
      min-interval         Minimum interval between samples, in seconds
      threshold            Threshold of delta in + out packets under which interfaces are considered
                           for shutdown
      <cr>

These optional parameters have the following defaults:
- max-samples: 2
- min-interval: 20s
- threshold: 10 packets


## Specifying a device to clean interfaces

    admin@ncs(config)# services clean-interfaces device A3-ASR9K-R6
    admin@ncs(config-device-A3-ASR9K-R6)# commit
    
## Tracking clean interface progress

Once a new device is configured under clean-interfaces, progress can be tracked with the 'show services clean-interfaces device <name> plan' command:

    admin@ncs# show services clean-interfaces device A3-ASR9K-R6 plan
    NAME  TYPE  STATE                    STATUS       WHEN                 ref  
    ----------------------------------------------------------------------------
    self  self  init                     reached      2019-01-21T17:03:01  -    
                first-sample-collected   reached      2019-01-21T17:03:07  -    
                second-sample-collected  not-reached  -                    -    
                ready                    not-reached  -                    -    

Interface cleanup is complete when the 'ready' state status is 'reached':

    admin@ncs# show services clean-interfaces device A3-ASR9K-R6 plan
    NAME  TYPE  STATE                    STATUS   WHEN                 ref  
    ------------------------------------------------------------------------
    self  self  init                     reached  2019-01-21T17:03:01  -    
                first-sample-collected   reached  2019-01-21T17:03:07  -    
                second-sample-collected  reached  2019-01-21T17:03:31  -    
                ready                    reached  2019-01-21T17:03:31  -    

## Verifying collected interface counters

    admin@ncs# show services clean-interfaces device A3-ASR9K-R6 interface-counters 
    TIMESTAMP   ID                       IN PKTS    OUT PKTS   
    -----------------------------------------------------------
    1548090187  Bundle-Ether1            0          0          
                Bundle-Ether2            111117021  111263994  
                Bundle-Ether300          232803658  3286499    
                Bundle-Ether300.900      2320303    13         
                Bundle-Ether300.902      2320303    1491422    
                Bundle-Ether300.903      2320303    1491541    
                GigabitEthernet0/2/0/1   111117022  111263995  
                GigabitEthernet0/2/0/19  0          0          
                MgmtEth0/RSP0/CPU0/0     3525902    114278     
                Multilink0/0/0/0/1       0          0          
                Multilink0/0/0/0/1.100   0          0          
                Multilink0/0/0/0/1.200   0          0          
                Multilink0/0/0/0/1.300   0          0          
                Null0                    0          0          
                Serial0/0/0/0/2:0        16013      16         
                Serial0/0/0/0/2:0.100    12         16         
                Serial0/0/0/0/2:0.200    0          0          
                Serial0/0/0/0/2:0.300    0          0          
                Serial0/0/0/3            460465     769387     
                TenGigE0/1/0/0           416337     2978799    
                TenGigE0/2/0/0           232387389  307701     
    1548090211  Bundle-Ether1            0          0          
                Bundle-Ether2            111117608  111264578  
                Bundle-Ether300          232804829  3286517    
                Bundle-Ether300.900      2320316    13         
                Bundle-Ether300.902      2320316    1491429    
                Bundle-Ether300.903      2320316    1491547    
                GigabitEthernet0/2/0/1   111117609  111264579  
                GigabitEthernet0/2/0/19  0          0          
                MgmtEth0/RSP0/CPU0/0     3526120    114498     
                Multilink0/0/0/0/1       0          0          
                Multilink0/0/0/0/1.100   0          0          
                Multilink0/0/0/0/1.200   0          0          
                Multilink0/0/0/0/1.300   0          0          
                Null0                    0          0          
                Serial0/0/0/0/2:0        16013      16         
                Serial0/0/0/0/2:0.100    12         16         
                Serial0/0/0/0/2:0.200    0          0          
                Serial0/0/0/0/2:0.300    0          0          
                Serial0/0/0/3            460468     769392     
                TenGigE0/1/0/0           416339     2978815    
                TenGigE0/2/0/0           232388591  307702   


We can also trigger the collection of a new sample by manually calling the collect-stats action:

    admin@ncs# services clean-interfaces device A3-ASR9K-R6 collect-stats          
    success Added new interface stats sample
    admin@ncs#

Interface samples from a given device can be cleaned with the following command:

    admin@ncs# services clean-interfaces device A3-ASR9K-R6 reset-stats 
    result Interface statistics data reset
    admin@ncs#


## Additional information

In order to display the kickers used by this service we need to create and unhide the debug group:

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











