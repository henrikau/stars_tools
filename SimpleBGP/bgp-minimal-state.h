#pragma once
#include "ns3/network-module.h"
#include "ns3/internet-module.h"
#include "ns3/bgp.h"
#include <vector>

/**
 * @file bgp-minimal-state.h
 * @brief Shared scenario state for the bgp-minimal example.
 *
 * Centralizes runtime objects so setup code does not rely on scattered locals.
 * This is an intermediate step before moving setup into a dedicated scenario class.
 */
struct BgpMinimalState
{
  enum class EventStage
  {
    INIT,
    SWITCHOVER_SCHEDULED,
    SWITCHED_TO_RED,
    PHYSICAL_MAIN_DOWN,
    PHYSICAL_MAIN_UP,
    SWITCHED_BACK_TO_MAIN
  };

  ns3::NodeContainer nodes;

  ns3::NetDeviceContainer d01;
  std::vector<ns3::NetDeviceContainer> d12_links;

  ns3::NetDeviceContainer d0lan;
  ns3::NetDeviceContainer d1lan;
  ns3::NetDeviceContainer d2lan;

  ns3::Ipv4InterfaceContainer if01;
  std::vector<ns3::Ipv4InterfaceContainer> if12_links;

  ns3::Ipv4InterfaceContainer if0lan;
  ns3::Ipv4InterfaceContainer if1lan;
  ns3::Ipv4InterfaceContainer if2lan;

  ns3::Ptr<ns3::Ipv4> host0_ipv4;
  ns3::Ptr<ns3::Ipv4> host1_ipv4;
  ns3::Ptr<ns3::Ipv4> host2_ipv4;

  ns3::Ptr<ns3::Bgp> bgp1;
  ns3::Ptr<ns3::Bgp> bgp2;

  EventStage stage{EventStage::INIT};
};
