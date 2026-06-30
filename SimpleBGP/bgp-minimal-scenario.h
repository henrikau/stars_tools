#pragma once

#include "bgp-minimal-state.h"
#include "ns3/nstime.h"
#include "ns3/ipv4-address.h"
#include "ns3/node.h"
#include "ns3/ptr.h"
#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

/**
 * @file bgp-minimal-scenario.h
 * @brief Scenario orchestration for the bgp-minimal example.
 *
 * The scenario engine separates:
 * - system/orchestration events (planned link switchover intent), and
 * - physical-world events (link down/up availability changes).
 *
 * This class is introduced as a refactoring boundary to gradually move
 * topology setup and protocol configuration out of main().
 */
class BgpMinimalScenario
{
public:
  BgpMinimalScenario ();

  // Load link schedule/configuration data.
  void LoadLinkConfig (const std::string& path);

  // Build nodes, stack, and L2 links.
  void BuildTopology ();

  // Assign inter-router and LAN IPv4 addresses.
  void ConfigureAddressing ();

  // Configure host default routes.
  void ConfigureRouting ();

  // Configure BGP apps, routes, and peering.
  void ConfigureBgp (ns3::Time stopTime);

  void ApplyBgpPreference (std::size_t linkIndex, int32_t weight, bool active);

  // Schedule physical-world and BGP events from the JSON link config.
  void ScheduleConfiguredEvents (ns3::Time stopTime);

  // Accessors for orchestration-level traffic setup.
  ns3::Ptr<ns3::Node> GetPingSourceNode () const;
  ns3::Ipv4Address GetPingDestinationAddress () const;
  std::string GetActiveLinkName () const;

private:
  struct DelayProfile
  {
    double startUs{100.0};
    double minUs{100.0};
    double endUs{100.0};
  };

  struct LinkWindow
  {
    ns3::Time up;
    ns3::Time down;
    DelayProfile delay;
  };

  struct BgpPreferenceEvent
  {
    ns3::Time time;
    int32_t weight{0};
    bool active{false};
  };

  struct LinkConfig
  {
    std::size_t index{0};
    std::string name{"d12_link"};
    ns3::Ipv4Address d1Address;
    ns3::Ipv4Address d2Address;
    uint64_t capacityBps{10000000000ULL};
    std::vector<LinkWindow> schedule;
    int32_t initialBgpWeight{0};
    std::vector<BgpPreferenceEvent> bgpEvents;
  };

  const LinkConfig& GetLinkConfig (std::size_t linkIndex) const;
  LinkConfig& GetLinkConfig (std::size_t linkIndex);
  std::string GetLinkName (std::size_t linkIndex) const;
  ns3::NetDeviceContainer& GetLinkDevices (std::size_t linkIndex);
  ns3::Ipv4InterfaceContainer& GetLinkInterfaces (std::size_t linkIndex);
  bool IsLinkAvailableAt (const LinkConfig& link, ns3::Time time) const;
  void SetPhysicalLinkState (std::size_t linkIndex, bool up, ns3::Time delay);
  void ConfigureLinkDelay (std::size_t linkIndex, ns3::Time delay);
  std::size_t SelectBestActiveLink () const;
  void RefreshActiveBgpPeer (std::size_t triggerLinkIndex);

  std::vector<bool> m_linkPhysicalUp;
  std::vector<bool> m_linkBgpActive;
  std::vector<int32_t> m_linkBgpWeight;
  std::size_t m_activeLinkIndex;

  bool m_hasLinkConfig;
  std::vector<LinkConfig> m_linkConfigs;

  BgpMinimalState m_state;
};
